from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from .config import (
    ANTICIPATION_MAX_DISTANCE_TO_PIVOT_PCT,
    ANTICIPATION_MIN_DISTANCE_TO_PIVOT_PCT,
    BREAKOUT_VOLUME_RATIO,
    CLOSE_NEAR_HIGH_PCT,
    EP_MIN_CHANGE_PCT,
    EP_MIN_VOLUME_RATIO,
    MAX_BASE_DAYS,
    MAX_BASE_DEPTH_PCT,
    MAX_EXTENDED_FROM_PIVOT_PCT,
    MAX_RISK_TO_STOP_PCT,
    MIN_AVG_TURNOVER_20D,
    MIN_BASE_DAYS,
    MIN_DAILY_TURNOVER,
    QULLAMAGGIE_MAX_CANDIDATES_PER_SETUP,
    QULLAMAGGIE_MAX_TOP_CANDIDATES,
    QULLAMAGGIE_SCORE_WEIGHTS,
    QULLAMAGGIE_SETUP_TYPES,
)
from .models import InstitutionalTradingRecord, MopsEventRecord, OhlcvRecord

BenchmarkHistory = dict[str, list[float]]


def calculate_qullamaggie_signals(
    current_rows: list[OhlcvRecord],
    history_rows: dict[str, list[OhlcvRecord]],
    benchmark_history: BenchmarkHistory | None = None,
    catalyst_symbols: dict[str, set[str]] | None = None,
    institutional_by_symbol: dict[str, InstitutionalTradingRecord] | None = None,
    margin_short_by_symbol: dict[str, dict[str, Any]] | None = None,
    margin_short_attention_symbols: set[str] | None = None,
    mops_events_by_symbol: dict[str, list[MopsEventRecord]] | None = None,
) -> dict[str, Any]:
    benchmark_history = benchmark_history or {}
    catalyst_symbols = catalyst_symbols or {}
    institutional_by_symbol = institutional_by_symbol or {}
    margin_short_by_symbol = margin_short_by_symbol or {}
    margin_short_attention_symbols = margin_short_attention_symbols or set()
    mops_events_by_symbol = mops_events_by_symbol or {}
    market_regime = calculate_market_regime(benchmark_history)
    eligible_rows = [row for row in current_rows if row.scan_eligible]
    limitations: list[str] = ["Qullamaggie-style 掃描僅針對 scan_eligible=true 的普通股 universe。"]
    if market_regime["status"] == "insufficient_data":
        limitations.append("TAIEX 或 OTC 指數歷史不足；market_regime 與相對強弱可能無法完整計算")

    candidates = [
        _calculate_candidate(
            row,
            history_rows,
            benchmark_history,
            market_regime,
            catalyst_symbols,
            institutional_by_symbol,
            margin_short_by_symbol,
            margin_short_attention_symbols,
            mops_events_by_symbol,
        )
        for row in eligible_rows
    ]
    _apply_relative_strength_ranks(candidates)

    grouped: dict[str, list[dict[str, Any]]] = {setup_type: [] for setup_type in QULLAMAGGIE_SETUP_TYPES}
    for candidate in candidates:
        grouped[candidate["setup_type"]].append(candidate)

    for setup_type in grouped:
        grouped[setup_type] = sorted(grouped[setup_type], key=_candidate_sort_key)[:QULLAMAGGIE_MAX_CANDIDATES_PER_SETUP]

    top_candidates = sorted(
        [candidate for candidate in candidates if candidate["setup_type"] != "insufficient_data"],
        key=_candidate_sort_key,
    )[:QULLAMAGGIE_MAX_TOP_CANDIDATES]

    if any(candidate["setup_type"] == "insufficient_data" for candidate in candidates):
        limitations.append("部分個股歷史或必要欄位不足，已歸類為 insufficient_data")
    if not candidates:
        limitations.append("今日 scan_eligible=true 的 OHLCV 不足，無法產生 Qullamaggie-style 候選清單")

    return {
        "market_regime": market_regime,
        "candidates": grouped,
        "top_candidates": top_candidates,
        "limitations": limitations,
    }


def calculate_market_regime(benchmark_history: BenchmarkHistory | None) -> dict[str, Any]:
    benchmark_history = benchmark_history or {}
    scores: list[str] = []
    metrics: dict[str, Any] = {}
    for market in ("listed", "otc"):
        closes = [value for value in benchmark_history.get(market, []) if value is not None and value > 0]
        if len(closes) < 50:
            continue
        ma20 = _avg(closes[-20:])
        ma50 = _avg(closes[-50:])
        current = closes[-1]
        metrics[market] = {"close": current, "ma20": ma20, "ma50": ma50}
        if current > ma20 and ma20 > ma50:
            scores.append("risk_on")
        elif current < ma20 and ma20 < ma50:
            scores.append("risk_off")
        else:
            scores.append("neutral")

    if not scores:
        return {
            "status": "insufficient_data",
            "score": 5,
            "reasons": ["指數歷史不足 50 日，無法判定市場狀態"],
            "risk_notes": ["未收集 TAIEX/OTC 指數歷史時，不宣稱完整市場順風程度"],
            "metrics": metrics,
        }
    if "risk_off" in scores:
        status = "risk_off"
        score = 0
    elif all(item == "risk_on" for item in scores):
        status = "risk_on"
        score = 15
    else:
        status = "neutral"
        score = 8
    return {
        "status": status,
        "score": score,
        "reasons": [f"benchmark regime={status}"],
        "risk_notes": [],
        "metrics": metrics,
    }


def classify_setup_type(metrics: dict[str, Any]) -> str:
    if (
        metrics["history_days"] < 20
        or metrics["close"] is None
        or metrics["volume"] is None
        or metrics["pivot_price"] is None
    ):
        return "insufficient_data"
    if (
        metrics["high"] is not None
        and metrics["pivot_price"] is not None
        and metrics["high"] > metrics["pivot_price"]
        and metrics["close"] < metrics["pivot_price"]
        and _ge(metrics["volume_ratio_20d"], BREAKOUT_VOLUME_RATIO)
    ):
        return "failed_breakout"
    if (
        (metrics["new_high_20d"] or metrics["new_high_60d"])
        and (metrics["extended_risk"] or _gt(metrics["risk_to_stop_pct"], MAX_RISK_TO_STOP_PCT))
    ):
        return "extended_watch"
    if (
        (metrics["new_high_20d"] or metrics["new_high_60d"])
        and metrics["breakout_volume_confirmed"]
        and metrics["close_near_high"]
        and metrics["above_ma20"]
        and metrics["above_ma50"]
        and not metrics["extended_risk"]
        and metrics["liquidity_ok"]
    ):
        return "breakout"
    if (
        (metrics["mops_event_flag"] or metrics["revenue_financial_flag"] or metrics["news_topic_flag"])
        and _ge(metrics["change_pct"], EP_MIN_CHANGE_PCT)
        and _ge(metrics["volume_ratio_20d"], EP_MIN_VOLUME_RATIO)
        and metrics["close_near_high"]
        and metrics["liquidity_ok"]
    ):
        return "episodic_pivot"
    if (
        not metrics["new_high_20d"]
        and not metrics["new_high_60d"]
        and _between(metrics["distance_to_pivot_pct"], ANTICIPATION_MIN_DISTANCE_TO_PIVOT_PCT, ANTICIPATION_MAX_DISTANCE_TO_PIVOT_PCT)
        and (metrics["range_contraction"] or metrics["volatility_contraction"])
        and metrics["above_ma20"]
        and metrics["above_ma50"]
        and metrics["liquidity_ok"]
    ):
        return "anticipation"
    return "insufficient_data"


def score_qullamaggie_candidate(metrics: dict[str, Any], market_regime: dict[str, Any]) -> tuple[int, dict[str, int]]:
    breakdown = {
        "market_regime": int(market_regime.get("score", 0)),
        "liquidity": 10 if metrics["liquidity_ok"] else (5 if metrics["turnover_ok"] and metrics["avg_turnover_20d"] is None else 0),
        "trend": sum(5 for key in ("above_ma10", "above_ma20", "above_ma50", "ma20_above_ma50") if metrics[key] is True),
        "base_and_pivot": 0,
        "breakout_and_volume": 0,
        "relative_strength_and_catalyst": 0,
        "risk_control": 0,
    }
    if metrics["base_days"] >= MIN_BASE_DAYS:
        breakdown["base_and_pivot"] += 5
    if metrics["base_depth_pct"] is not None and metrics["base_depth_pct"] <= MAX_BASE_DEPTH_PCT:
        breakdown["base_and_pivot"] += 5
    if metrics["range_contraction"] or metrics["volatility_contraction"]:
        breakdown["base_and_pivot"] += 5
    if _between(metrics["distance_to_pivot_pct"], -3, 3):
        breakdown["base_and_pivot"] += 5
    if metrics["new_high_20d"]:
        breakdown["breakout_and_volume"] += 5
    if metrics["new_high_60d"]:
        breakdown["breakout_and_volume"] += 5
    if metrics["breakout_volume_confirmed"]:
        breakdown["breakout_and_volume"] += 5
    if metrics["close_near_high"]:
        breakdown["breakout_and_volume"] += 5
    if _ge(metrics["relative_strength_rank"], 80):
        breakdown["relative_strength_and_catalyst"] += 5
    if metrics["mops_event_flag"] or metrics["revenue_financial_flag"] or metrics["news_topic_flag"]:
        breakdown["relative_strength_and_catalyst"] += 5
    if not metrics["extended_risk"] and _le(metrics["risk_to_stop_pct"], MAX_RISK_TO_STOP_PCT):
        breakdown["risk_control"] = 5
    score = max(0, min(100, sum(min(value, QULLAMAGGIE_SCORE_WEIGHTS[key]) for key, value in breakdown.items())))
    return score, breakdown


def _calculate_candidate(
    row: OhlcvRecord,
    history_rows: dict[str, list[OhlcvRecord]],
    benchmark_history: BenchmarkHistory,
    market_regime: dict[str, Any],
    catalyst_symbols: dict[str, set[str]],
    institutional_by_symbol: dict[str, InstitutionalTradingRecord],
    margin_short_by_symbol: dict[str, dict[str, Any]],
    margin_short_attention_symbols: set[str],
    mops_events_by_symbol: dict[str, list[MopsEventRecord]],
) -> dict[str, Any]:
    history = _history_for_symbol_before_date(history_rows, row.symbol, row.date)
    metrics = _calculate_metrics(
        row,
        history,
        benchmark_history,
        catalyst_symbols,
        institutional_by_symbol.get(row.symbol),
        margin_short_by_symbol.get(row.symbol),
        row.symbol in margin_short_attention_symbols,
        mops_events_by_symbol.get(row.symbol, []),
    )
    metrics["setup_type"] = classify_setup_type(metrics)
    score, breakdown = score_qullamaggie_candidate(metrics, market_regime)
    metrics["qullamaggie_score"] = score
    metrics["score_breakdown"] = breakdown
    metrics["setup_reasons"] = _setup_reasons(metrics)
    metrics["risk_notes"] = _risk_notes(metrics)
    metrics["tags"] = _tags(metrics)
    metrics["source_refs"] = [row.source]
    return _candidate_payload(metrics)


def _calculate_metrics(
    row: OhlcvRecord,
    history: list[OhlcvRecord],
    benchmark_history: BenchmarkHistory,
    catalyst_symbols: dict[str, set[str]],
    institutional: InstitutionalTradingRecord | None = None,
    margin_short: dict[str, Any] | None = None,
    margin_short_attention_flag: bool = False,
    mops_events: list[MopsEventRecord] | None = None,
) -> dict[str, Any]:
    mops_events = mops_events or []
    closes = [item.close for item in history if item.close is not None]
    highs = [item.high for item in history if item.high is not None]
    lows = [item.low for item in history if item.low is not None]
    volumes = [item.volume for item in history if item.volume is not None]
    turnovers = [item.turnover for item in history if item.turnover is not None]
    current_close = row.close
    ma10 = _ma(closes + ([current_close] if current_close is not None else []), 10)
    ma20 = _ma(closes + ([current_close] if current_close is not None else []), 20)
    ma50 = _ma(closes + ([current_close] if current_close is not None else []), 50)
    avg_volume_20d = _avg(volumes[-20:]) if len(volumes) >= 20 else None
    avg_turnover_20d = _avg(turnovers[-20:]) if len(turnovers) >= 20 else None
    prior_20d_high = max(highs[-20:]) if len(highs) >= 20 else None
    prior_60d_high = max(highs[-60:]) if len(highs) >= 60 else None
    pivot_price = prior_60d_high if prior_60d_high is not None else prior_20d_high
    daily_range_pct = _pct((row.high - row.low) / current_close * 100) if row.high is not None and row.low is not None and current_close else None
    close_location_pct = None
    if row.high is not None and row.low is not None and current_close is not None and row.high != row.low:
        close_location_pct = _pct((current_close - row.low) / (row.high - row.low) * 100)
    base = _find_base(history)
    range_contraction = _range_contraction(history)
    volatility_contraction = _volatility_contraction(history)
    tight_close_count = _tight_close_count(history, row)
    rs20, rs60 = _relative_strength(row, history, benchmark_history)
    stop_reference = base["base_low"] if base["base_low"] is not None else (min(lows[-10:]) if len(lows) >= 10 else None)
    distance_to_pivot_pct = _relative_pct(current_close, pivot_price)
    risk_to_stop_pct = _relative_pct(current_close, stop_reference)
    volume_ratio_20d = row.volume / avg_volume_20d if row.volume is not None and avg_volume_20d else None
    mops_event_flag = bool(mops_events) or row.symbol in catalyst_symbols.get("mops", set())
    mops_event_categories = sorted({event.category for event in mops_events if event.category})
    mops_event_titles = [event.title for event in mops_events if event.title]
    catalyst_tags = _catalyst_tags(row.symbol, catalyst_symbols, mops_event_categories, bool(mops_events))

    return {
        "symbol": row.symbol,
        "name": row.name,
        "market": row.market,
        "security_type": row.security_type,
        "scan_eligible": row.scan_eligible,
        "history_days": len(history),
        "close": current_close,
        "high": row.high,
        "low": row.low,
        "change_pct": row.change_pct,
        "volume": row.volume,
        "turnover": row.turnover,
        "foreign_net_buy": institutional.foreign_net_buy if institutional else None,
        "investment_trust_net_buy": institutional.investment_trust_net_buy if institutional else None,
        "dealer_net_buy": institutional.dealer_net_buy if institutional else None,
        "institutional_net_buy": institutional.institutional_net_buy if institutional else None,
        "institutional_confirmation": bool(institutional and institutional.institutional_net_buy is not None and institutional.institutional_net_buy > 0),
        "institutional_source": institutional.source if institutional else None,
        "margin_balance": margin_short.get("margin_balance") if margin_short else None,
        "margin_change": margin_short.get("margin_change") if margin_short else None,
        "short_balance": margin_short.get("short_balance") if margin_short else None,
        "short_change": margin_short.get("short_change") if margin_short else None,
        "margin_balance_ratio_20d": margin_short.get("margin_balance_ratio_20d") if margin_short else None,
        "short_balance_ratio_20d": margin_short.get("short_balance_ratio_20d") if margin_short else None,
        "margin_short_attention_flag": margin_short_attention_flag,
        "margin_short_source": margin_short.get("source") if margin_short else None,
        "ma10": _pct(ma10),
        "ma20": _pct(ma20),
        "ma50": _pct(ma50),
        "above_ma10": _bool_gt(current_close, ma10),
        "above_ma20": _bool_gt(current_close, ma20),
        "above_ma50": _bool_gt(current_close, ma50),
        "ma20_above_ma50": _bool_gt(ma20, ma50),
        "close_vs_ma10_pct": _relative_pct(current_close, ma10),
        "close_vs_ma20_pct": _relative_pct(current_close, ma20),
        "close_vs_ma50_pct": _relative_pct(current_close, ma50),
        "avg_volume_20d": _pct(avg_volume_20d),
        "volume_ratio_20d": _pct(volume_ratio_20d),
        "avg_turnover_20d": _pct(avg_turnover_20d),
        "turnover_ok": bool(row.turnover is not None and row.turnover >= MIN_DAILY_TURNOVER),
        "liquidity_ok": bool(row.turnover is not None and row.turnover >= MIN_DAILY_TURNOVER and avg_turnover_20d is not None and avg_turnover_20d >= MIN_AVG_TURNOVER_20D),
        "daily_range_pct": daily_range_pct,
        "close_location_pct": close_location_pct,
        "close_near_high": bool(close_location_pct is not None and close_location_pct >= CLOSE_NEAR_HIGH_PCT),
        "prior_20d_high": prior_20d_high,
        "prior_60d_high": prior_60d_high,
        "new_high_20d": bool(current_close is not None and prior_20d_high is not None and current_close > prior_20d_high),
        "new_high_60d": bool(current_close is not None and prior_60d_high is not None and current_close > prior_60d_high),
        "pivot_price": pivot_price,
        "distance_to_pivot_pct": distance_to_pivot_pct,
        "breakout_volume_confirmed": bool(volume_ratio_20d is not None and volume_ratio_20d >= BREAKOUT_VOLUME_RATIO),
        "base_days": base["base_days"],
        "base_high": base["base_high"],
        "base_low": base["base_low"],
        "base_depth_pct": base["base_depth_pct"],
        "range_contraction": range_contraction,
        "volatility_contraction": volatility_contraction,
        "tight_close_count": tight_close_count,
        "relative_strength_20d": rs20,
        "relative_strength_60d": rs60,
        "relative_strength_rank": None,
        "relative_strength_rank_basis": None,
        "extended_from_pivot_pct": max(0, distance_to_pivot_pct) if distance_to_pivot_pct is not None else None,
        "extended_risk": bool(distance_to_pivot_pct is not None and max(0, distance_to_pivot_pct) > MAX_EXTENDED_FROM_PIVOT_PCT),
        "stop_reference": stop_reference,
        "risk_to_stop_pct": risk_to_stop_pct,
        "mops_event_flag": mops_event_flag,
        "mops_event_count": len(mops_events),
        "mops_event_categories": mops_event_categories,
        "mops_event_titles": mops_event_titles,
        "revenue_financial_flag": row.symbol in catalyst_symbols.get("revenue_financials", set()),
        "news_topic_flag": row.symbol in catalyst_symbols.get("news_topics", set()),
        "catalyst_tags": catalyst_tags,
    }


def _candidate_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "symbol",
        "name",
        "market",
        "security_type",
        "scan_eligible",
        "setup_type",
        "qullamaggie_score",
        "score_breakdown",
        "close",
        "change_pct",
        "volume",
        "turnover",
        "foreign_net_buy",
        "investment_trust_net_buy",
        "dealer_net_buy",
        "institutional_net_buy",
        "institutional_confirmation",
        "margin_balance",
        "margin_change",
        "short_balance",
        "short_change",
        "margin_balance_ratio_20d",
        "short_balance_ratio_20d",
        "margin_short_attention_flag",
        "ma10",
        "ma20",
        "ma50",
        "above_ma10",
        "above_ma20",
        "above_ma50",
        "ma20_above_ma50",
        "close_vs_ma10_pct",
        "close_vs_ma20_pct",
        "close_vs_ma50_pct",
        "avg_volume_20d",
        "volume_ratio_20d",
        "avg_turnover_20d",
        "turnover_ok",
        "liquidity_ok",
        "prior_20d_high",
        "prior_60d_high",
        "new_high_20d",
        "new_high_60d",
        "pivot_price",
        "distance_to_pivot_pct",
        "breakout_volume_confirmed",
        "daily_range_pct",
        "close_location_pct",
        "close_near_high",
        "base_days",
        "base_high",
        "base_low",
        "base_depth_pct",
        "range_contraction",
        "volatility_contraction",
        "tight_close_count",
        "relative_strength_20d",
        "relative_strength_60d",
        "relative_strength_rank",
        "relative_strength_rank_basis",
        "extended_from_pivot_pct",
        "extended_risk",
        "stop_reference",
        "risk_to_stop_pct",
        "mops_event_flag",
        "mops_event_count",
        "mops_event_categories",
        "mops_event_titles",
        "revenue_financial_flag",
        "news_topic_flag",
        "catalyst_tags",
        "tags",
        "setup_reasons",
        "risk_notes",
        "source_refs",
    ]
    payload = {key: metrics.get(key) for key in keys}
    if metrics.get("institutional_source"):
        payload["source_refs"] = list(dict.fromkeys([*(payload.get("source_refs") or []), metrics["institutional_source"]]))
    if metrics.get("margin_short_source"):
        payload["source_refs"] = list(dict.fromkeys([*(payload.get("source_refs") or []), metrics["margin_short_source"]]))
    if metrics.get("mops_event_count"):
        payload["source_refs"] = list(dict.fromkeys([*(payload.get("source_refs") or []), "MOPS"]))
    return payload


def _apply_relative_strength_ranks(candidates: list[dict[str, Any]]) -> None:
    by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_market[candidate["market"]].append(candidate)
    for values in by_market.values():
        basis = "60d" if any(candidate["relative_strength_60d"] is not None for candidate in values) else "20d"
        field = "relative_strength_60d" if basis == "60d" else "relative_strength_20d"
        ranked = [candidate for candidate in values if candidate[field] is not None]
        ranked.sort(key=lambda item: item[field])
        if not ranked:
            continue
        denominator = max(1, len(ranked) - 1)
        for position, candidate in enumerate(ranked):
            candidate["relative_strength_rank"] = round(position / denominator * 100, 4) if len(ranked) > 1 else 100.0
            candidate["relative_strength_rank_basis"] = basis
            score, breakdown = score_qullamaggie_candidate(candidate, {"score": candidate["score_breakdown"]["market_regime"]})
            candidate["qullamaggie_score"] = score
            candidate["score_breakdown"] = breakdown


def _history_for_symbol_before_date(history_rows: dict[str, list[OhlcvRecord]], symbol: str, current_date: str) -> list[OhlcvRecord]:
    records: list[OhlcvRecord] = []
    for day in sorted(history_rows):
        for row in history_rows[day]:
            if row.symbol == symbol and row.date < current_date and row.scan_eligible:
                records.append(row)
    return records


def _find_base(history: list[OhlcvRecord]) -> dict[str, Any]:
    selected = {"base_days": 0, "base_high": None, "base_low": None, "base_depth_pct": None}
    for days in range(MIN_BASE_DAYS, MAX_BASE_DAYS + 1):
        window = history[-days:]
        highs = [row.high for row in window if row.high is not None]
        lows = [row.low for row in window if row.low is not None]
        if len(highs) != days or len(lows) != days:
            continue
        base_high = max(highs)
        base_low = min(lows)
        if base_low <= 0:
            continue
        depth = (base_high / base_low - 1) * 100
        if depth <= MAX_BASE_DEPTH_PCT and days >= selected["base_days"]:
            selected = {"base_days": days, "base_high": base_high, "base_low": base_low, "base_depth_pct": _pct(depth)}
    return selected


def _range_contraction(history: list[OhlcvRecord]) -> bool:
    values = [_daily_range_pct(row) for row in history[-20:]]
    if len(values) < 20 or any(value is None for value in values):
        return False
    return mean(values[-5:]) < mean(values[:15])


def _volatility_contraction(history: list[OhlcvRecord]) -> bool:
    if len(history) < 20:
        return False
    atr_values = _atr_pct_series(history)
    if len(atr_values) < 20:
        return False
    recent_5 = [value for value in atr_values[-5:] if value is not None]
    recent_20 = [value for value in atr_values[-20:] if value is not None]
    return len(recent_5) == 5 and len(recent_20) == 20 and mean(recent_5) < mean(recent_20)


def _tight_close_count(history: list[OhlcvRecord], row: OhlcvRecord) -> int:
    window = history[-4:] + [row]
    if len(window) < 5:
        return 0
    closes = [item.close for item in window if item.close is not None]
    if len(closes) < 5:
        return 0
    ma5 = mean(closes)
    return sum(1 for close in closes if abs(close / ma5 - 1) <= 0.03)


def _relative_strength(row: OhlcvRecord, history: list[OhlcvRecord], benchmark_history: BenchmarkHistory) -> tuple[float | None, float | None]:
    benchmark = benchmark_history.get(row.market, [])
    closes = [item.close for item in history if item.close is not None]
    rs20 = _relative_strength_for_window(row.close, closes, benchmark, 20)
    rs60 = _relative_strength_for_window(row.close, closes, benchmark, 60)
    return rs20, rs60


def _relative_strength_for_window(current_close: float | None, closes: list[float], benchmark: list[float], days: int) -> float | None:
    if current_close is None or len(closes) < days or len(benchmark) < days + 1:
        return None
    stock_base = closes[-days]
    benchmark_base = benchmark[-days - 1]
    benchmark_current = benchmark[-1]
    if stock_base == 0 or benchmark_base == 0:
        return None
    stock_return = current_close / stock_base - 1
    benchmark_return = benchmark_current / benchmark_base - 1
    return _pct((stock_return - benchmark_return) * 100)


def _atr_pct_series(rows: list[OhlcvRecord]) -> list[float | None]:
    true_ranges: list[float] = []
    output: list[float | None] = []
    previous_close: float | None = None
    for row in rows:
        if row.high is None or row.low is None:
            output.append(None)
            continue
        if previous_close is None:
            true_range = row.high - row.low
        else:
            true_range = max(row.high - row.low, abs(row.high - previous_close), abs(row.low - previous_close))
        true_ranges.append(true_range)
        previous_close = row.close
        if len(true_ranges) < 14 or row.close in {None, 0}:
            output.append(None)
        else:
            output.append(mean(true_ranges[-14:]) / row.close * 100)
    return output


def _daily_range_pct(row: OhlcvRecord) -> float | None:
    if row.high is None or row.low is None or not row.close:
        return None
    return (row.high - row.low) / row.close * 100


def _catalyst_tags(
    symbol: str,
    catalyst_symbols: dict[str, set[str]],
    mops_event_categories: list[str] | None = None,
    has_mops_events: bool = False,
) -> list[str]:
    tags: list[str] = []
    if has_mops_events or symbol in catalyst_symbols.get("mops", set()):
        tags.append("重大訊息")
    for category in mops_event_categories or []:
        tags.append(f"重大訊息:{category}")
    if symbol in catalyst_symbols.get("revenue_financials", set()):
        tags.append("營收財報")
    if symbol in catalyst_symbols.get("news_topics", set()):
        tags.append("新聞題材")
    return tags


def _setup_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if metrics["new_high_20d"]:
        reasons.append("收盤價高於今日以前 20 日高點")
    if metrics["new_high_60d"]:
        reasons.append("收盤價高於今日以前 60 日高點")
    if metrics["breakout_volume_confirmed"]:
        reasons.append("成交量高於 20 日均量門檻")
    if metrics["close_near_high"]:
        reasons.append("收盤位置接近日內高點")
    if metrics["range_contraction"] or metrics["volatility_contraction"]:
        reasons.append("整理區間出現收斂特徵")
    if metrics["setup_type"] == "insufficient_data":
        reasons.append("歷史資料或必要欄位不足")
    return reasons


def _risk_notes(metrics: dict[str, Any]) -> list[str]:
    notes = ["僅供研究與人工複核，不構成買賣建議"]
    if metrics.get("margin_short_attention_flag"):
        notes.append("資券變化可能代表籌碼分歧，不可單獨視為買賣訊號")
    if metrics["extended_risk"]:
        notes.append("距離 pivot 已超過延伸風險門檻")
    if _gt(metrics["risk_to_stop_pct"], MAX_RISK_TO_STOP_PCT):
        notes.append("距離風險參考位置超過門檻")
    if metrics["relative_strength_rank"] is None:
        notes.append("相對強弱排名資料不足")
    return notes


def _tags(metrics: dict[str, Any]) -> list[str]:
    tags = [metrics["setup_type"]]
    if metrics["new_high_20d"]:
        tags.append("20日新高")
    if metrics["new_high_60d"]:
        tags.append("60日新高")
    if metrics["breakout_volume_confirmed"]:
        tags.append("量能確認")
    if metrics.get("institutional_confirmation"):
        tags.append("法人買超")
    if metrics.get("foreign_net_buy") is not None and metrics["foreign_net_buy"] > 0:
        tags.append("外資買超")
    if metrics.get("investment_trust_net_buy") is not None and metrics["investment_trust_net_buy"] > 0:
        tags.append("投信買超")
    if metrics.get("margin_short_attention_flag"):
        tags.append("資券異常")
    tags.extend(metrics["catalyst_tags"])
    return tags


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float]:
    return (
        -(candidate.get("qullamaggie_score") or 0),
        -(candidate.get("volume_ratio_20d") or 0),
        -(candidate.get("turnover") or 0),
    )


def _ma(values: list[float | None], days: int) -> float | None:
    clean = [value for value in values if value is not None]
    if len(clean) < days:
        return None
    return mean(clean[-days:])


def _avg(values: list[float | int]) -> float | None:
    return mean(values) if values else None


def _relative_pct(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in {None, 0}:
        return None
    return _pct((numerator / denominator - 1) * 100)


def _bool_gt(left: float | None, right: float | None) -> bool | None:
    if left is None or right is None:
        return None
    return left > right


def _between(value: float | None, low: float, high: float) -> bool:
    return value is not None and low <= value <= high


def _ge(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _gt(value: float | None, threshold: float) -> bool:
    return value is not None and value > threshold


def _le(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def _pct(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None
