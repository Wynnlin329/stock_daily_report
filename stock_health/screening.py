from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from typing import Any

from .config import SCHEMA_VERSION, SCREENING_MAX_CANDIDATES, TIMEZONE
from .models import InstitutionalTradingRecord, MarginShortRecord, MopsEventRecord, OhlcvRecord
from .qullamaggie import calculate_qullamaggie_signals
from .universe import build_universe_summary


def build_screening_summary(
    report_date: str,
    generated_at: str,
    listed_rows: list[OhlcvRecord],
    otc_rows: list[OhlcvRecord],
    history_rows: dict[str, list[OhlcvRecord]],
    coverage: dict[str, dict[str, object]],
    full_market_scan_ready: bool,
    missing_sections: list[str],
    overall_confidence: str,
    institutional_rows: list[InstitutionalTradingRecord] | None = None,
    institutional_history_rows: dict[str, list[InstitutionalTradingRecord]] | None = None,
    margin_short_rows: list[MarginShortRecord] | None = None,
    margin_short_history_rows: dict[str, list[MarginShortRecord]] | None = None,
    mops_event_rows: list[MopsEventRecord] | None = None,
    mops_event_history_payloads: dict[str, dict[str, Any]] | None = None,
    mops_events_status: str = "source_unavailable",
    history_index: dict[str, Any] | None = None,
    benchmark_history: dict[str, list[float]] | None = None,
    include_symbol_candidates: bool = False,
) -> dict[str, Any]:
    all_rows = listed_rows + otc_rows
    eligible_rows = [row for row in all_rows if row.scan_eligible]
    institutional_rows = institutional_rows or []
    institutional_history_rows = institutional_history_rows or {}
    margin_short_rows = margin_short_rows or []
    margin_short_history_rows = margin_short_history_rows or {}
    mops_event_rows = mops_event_rows or []
    mops_event_history_payloads = mops_event_history_payloads or {}
    mops_events_available = mops_events_status in {"success", "empty_but_valid"}
    mops_event_metrics_by_symbol = (
        _mops_event_metrics_by_symbol(report_date, mops_event_rows, mops_event_history_payloads)
        if mops_events_available
        else {}
    )
    mops_context = _mops_analysis_context(
        report_date,
        mops_event_history_payloads,
        mops_events_status,
    )
    mops_events_by_symbol = {
        symbol: [event for event in metrics["events_7d"]]
        for symbol, metrics in mops_event_metrics_by_symbol.items()
    }
    history_index = history_index or {}
    institutional_latest_available = bool(history_index.get("has_institutional_latest", bool(institutional_rows)))
    margin_short_latest_available = bool(history_index.get("has_margin_short_latest", bool(margin_short_rows)))
    institutional_by_symbol = {row.symbol: row for row in institutional_rows} if institutional_latest_available else {}
    institutional_metrics_by_symbol = _institutional_metrics_by_symbol(institutional_by_symbol, institutional_history_rows)
    margin_short_by_symbol = {row.symbol: row for row in margin_short_rows} if margin_short_latest_available else {}
    margin_short_history_by_symbol = _history_by_symbol(margin_short_history_rows)
    margin_short_metrics_by_symbol = {
        symbol: _margin_short_metrics(row, margin_short_history_by_symbol.get(symbol, []))
        for symbol, row in margin_short_by_symbol.items()
    }
    historical_days = sorted(history_rows)
    has_20d_history = bool(history_index.get("has_20d_history", len(historical_days) >= 20))
    has_60d_history = bool(history_index.get("has_60d_history", len(historical_days) >= 60))
    limitations: list[str] = []
    if not has_20d_history:
        limitations.append("歷史資料不足 20 個交易日；未產生 20 日均量、爆量倍數或 20 日突破訊號")
    if not has_60d_history:
        limitations.append("歷史資料不足 60 個交易日；未產生 60 日突破訊號")
    if missing_sections:
        limitations.append("核心資料段落缺失：" + ", ".join(missing_sections))
    if not mops_events_available:
        limitations.append("MOPS 重大訊息不可用，未納入事件催化判斷。")
    if margin_short_rows and len(margin_short_history_rows) < 20:
        limitations.append("資券歷史資料不足 20 個交易日；margin_balance_ratio_20d 與 short_balance_ratio_20d 保留 null")
    historical_status = _historical_data_status(history_index, historical_days)
    institutional_status = _institutional_data_status(institutional_rows, institutional_history_rows, history_index)
    margin_short_status = _margin_short_data_status(margin_short_rows, margin_short_history_rows, history_index)
    mops_event_status = _mops_event_data_status(report_date, mops_event_history_payloads, mops_events_status, history_index)
    margin_short_attention = _margin_short_attention_candidates(eligible_rows, margin_short_metrics_by_symbol)
    margin_short_attention_symbols = {item["symbol"] for item in margin_short_attention}
    mops_event_candidates = _mops_event_candidates(eligible_rows, mops_event_metrics_by_symbol)
    qullamaggie = calculate_qullamaggie_signals(
        eligible_rows,
        history_rows,
        benchmark_history=benchmark_history,
        institutional_by_symbol=institutional_by_symbol,
        institutional_metrics_by_symbol=institutional_metrics_by_symbol,
        margin_short_by_symbol=margin_short_metrics_by_symbol,
        margin_short_attention_symbols=margin_short_attention_symbols,
        mops_events_by_symbol=mops_events_by_symbol,
        mops_event_metrics_by_symbol=mops_event_metrics_by_symbol,
        mops_context=mops_context,
    )
    symbol_candidates = qullamaggie.pop("all_candidates", [])
    limitations.extend(qullamaggie["limitations"])

    payload = {
        "schema_version": SCHEMA_VERSION,
        "report_date": report_date,
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "data_quality": {
            "listed_rows": len(listed_rows),
            "otc_rows": len(otc_rows),
            "coverage": coverage,
        },
        "coverage": coverage,
        "historical_data_status": historical_status,
        "institutional_data_status": institutional_status,
        "margin_short_data_status": margin_short_status,
        "mops_event_data_status": mops_event_status,
        "universe_summary": build_universe_summary(all_rows),
        "market_summary": _market_summary(all_rows),
        "rankings": {
            "top_turnover": [_candidate(row, []) for row in sorted(eligible_rows, key=lambda item: item.turnover or 0, reverse=True)[:20]],
            "top_volume": [_candidate(row, []) for row in sorted(eligible_rows, key=lambda item: item.volume or 0, reverse=True)[:20]],
            "top_gainers": [_candidate(row, []) for row in sorted(eligible_rows, key=lambda item: item.change_pct if item.change_pct is not None else -999, reverse=True)[:20]],
        },
        "screening": {
            "limit_up": [_candidate(row, ["漲停初篩"]) for row in eligible_rows if row.change_pct is not None and row.change_pct >= 9.5][:SCREENING_MAX_CANDIDATES],
            "volume_spike": _volume_spike_candidates(eligible_rows, history_rows) if has_20d_history else [],
            "breakout_candidates": _breakout_candidates(eligible_rows, history_rows, 60) if has_60d_history else [],
            "institutional_buy_candidates": _institutional_buy_candidates(eligible_rows, institutional_by_symbol, institutional_metrics_by_symbol),
            "margin_short_attention": margin_short_attention,
            "mops_event_candidates": mops_event_candidates,
            "revenue_financial_candidates": [],
            "manual_review_candidates": [],
        },
        "qullamaggie": qullamaggie,
        "full_market_scan_ready": full_market_scan_ready,
        "missing_sections": missing_sections,
        "overall_confidence": overall_confidence,
        "limitations": limitations,
    }
    if include_symbol_candidates:
        payload["_chatgpt_symbol_candidates"] = symbol_candidates
    return payload


def _market_summary(rows: list[OhlcvRecord]) -> dict[str, Any]:
    change_values = [row.change_pct for row in rows if row.change_pct is not None]
    return {
        "total_symbols": len(rows),
        "advancers": sum(1 for row in rows if row.change_pct is not None and row.change_pct > 0),
        "decliners": sum(1 for row in rows if row.change_pct is not None and row.change_pct < 0),
        "unchanged": sum(1 for row in rows if row.change_pct == 0),
        "average_change_pct": round(mean(change_values), 4) if change_values else None,
    }


def _historical_data_status(history_index: dict[str, Any], history_days: list[str]) -> dict[str, Any]:
    common_days = list(history_index.get("common_ohlcv_days") or history_days)
    return {
        "available_trading_days": int(history_index.get("available_trading_days", len(common_days))),
        "has_20d_history": bool(history_index.get("has_20d_history", len(common_days) >= 20)),
        "has_60d_history": bool(history_index.get("has_60d_history", len(common_days) >= 60)),
        "has_126d_history": bool(history_index.get("has_126d_history", len(common_days) >= 126)),
        "has_252d_history": bool(history_index.get("has_252d_history", len(common_days) >= 252)),
        "start_date": history_index.get("start_date") or (common_days[0] if common_days else None),
        "end_date": history_index.get("end_date") or (common_days[-1] if common_days else None),
    }


def _institutional_data_status(
    current_rows: list[InstitutionalTradingRecord],
    history_rows: dict[str, list[InstitutionalTradingRecord]],
    history_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history_index = history_index or {}
    days = list(history_index.get("common_institutional_days") or sorted(history_rows))
    limitations: list[str] = []
    if len(days) < 5:
        limitations.append("法人歷史資料不足 5 個交易日")
    if len(days) < 20:
        limitations.append("法人歷史資料不足 20 個交易日")
    if len(days) < 60:
        limitations.append("法人歷史資料不足 60 個交易日")
    if current_rows and any(_has_partial_institutional(row) for row in current_rows):
        limitations.append("部分法人拆分欄位缺失，institutional_partial=true")
    return {
        "latest_available": bool(history_index.get("has_institutional_latest", bool(current_rows))),
        "available_trading_days": len(days),
        "has_5d_history": bool(history_index.get("has_institutional_5d_history", len(days) >= 5)),
        "has_20d_history": bool(history_index.get("has_institutional_20d_history", len(days) >= 20)),
        "has_60d_history": bool(history_index.get("has_institutional_60d_history", len(days) >= 60)),
        "limitations": limitations,
    }


def _margin_short_data_status(
    current_rows: list[MarginShortRecord],
    history_rows: dict[str, list[MarginShortRecord]],
    history_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history_index = history_index or {}
    days = list(history_index.get("common_margin_short_days") or sorted(history_rows))
    limitations: list[str] = []
    if len(days) < 20:
        limitations.append("資券歷史資料不足 20 個交易日，無法計算 20 日資券比例")
    if len(days) < 60:
        limitations.append("資券歷史資料不足 60 個交易日，無法計算 60 日資券變化")
    return {
        "latest_available": bool(history_index.get("has_margin_short_latest", bool(current_rows))),
        "available_trading_days": len(days),
        "has_5d_history": bool(history_index.get("has_margin_short_5d_history", len(days) >= 5)),
        "has_20d_history": bool(history_index.get("has_margin_short_20d_history", len(days) >= 20)),
        "has_60d_history": bool(history_index.get("has_margin_short_60d_history", len(days) >= 60)),
        "limitations": limitations,
    }


def _mops_event_data_status(
    report_date: str,
    history_payloads: dict[str, dict[str, Any]],
    current_status: str = "source_unavailable",
    history_index: dict[str, Any] | None = None,
) -> dict[str, Any]:
    history_index = history_index or {}
    end_date = date.fromisoformat(report_date)
    verified_days = {
        day
        for day, payload in history_payloads.items()
        if payload.get("status") in {"success", "empty_but_valid"} and payload.get("data_date") == day
    }
    index_days = set(history_index.get("mops_event_days") or [])
    if index_days:
        verified_days = index_days
    limitations: list[str] = []
    if current_status not in {"success", "empty_but_valid"}:
        limitations.append("MOPS 重大訊息不可用，未納入事件催化判斷。")
    if len(verified_days) < 7:
        limitations.append("MOPS 重大訊息歷史不足 7 個自然日")
    if len(verified_days) < 30:
        limitations.append("MOPS 重大訊息歷史不足 30 個自然日")
    if len(verified_days) < 90:
        limitations.append("MOPS 重大訊息歷史不足 90 個自然日")
        limitations.append("MOPS 事件歷史採每日累積，目前尚未滿 90 自然日。")
    return {
        "latest_available": bool(history_index.get("has_mops_event_latest", report_date in verified_days)),
        "available_calendar_days": len(verified_days),
        "has_7d_history": bool(history_index.get("has_mops_event_7d_history", all((end_date - timedelta(days=offset)).isoformat() in verified_days for offset in range(7)))),
        "has_30d_history": bool(history_index.get("has_mops_event_30d_history", all((end_date - timedelta(days=offset)).isoformat() in verified_days for offset in range(30)))),
        "has_90d_history": bool(history_index.get("has_mops_event_90d_history", all((end_date - timedelta(days=offset)).isoformat() in verified_days for offset in range(90)))),
        "limitations": limitations,
    }


def _has_partial_institutional(row: InstitutionalTradingRecord) -> bool:
    values = [row.foreign_net_buy, row.investment_trust_net_buy, row.dealer_net_buy, row.institutional_net_buy]
    return any(value is None for value in values) and any(value is not None for value in values)


def _history_by_symbol(history_rows: dict[str, list[OhlcvRecord]]) -> dict[str, list[OhlcvRecord]]:
    grouped: dict[str, list[OhlcvRecord]] = defaultdict(list)
    for day in sorted(history_rows):
        for row in history_rows[day]:
            if not row.scan_eligible:
                continue
            grouped[row.symbol].append(row)
    return grouped


def _volume_spike_candidates(rows: list[OhlcvRecord], history_rows: dict[str, list[OhlcvRecord]]) -> list[dict[str, Any]]:
    grouped = _history_by_symbol(history_rows)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        history = [item.volume for item in grouped.get(row.symbol, [])[-20:] if item.volume is not None]
        if row.volume is None or len(history) < 20:
            continue
        avg_volume = mean(history)
        if avg_volume > 0 and row.volume / avg_volume >= 1.8:
            candidates.append(_candidate(row, ["量增"], volume_ratio_20d=round(row.volume / avg_volume, 4)))
    return candidates[:SCREENING_MAX_CANDIDATES]


def _breakout_candidates(rows: list[OhlcvRecord], history_rows: dict[str, list[OhlcvRecord]], days: int) -> list[dict[str, Any]]:
    grouped = _history_by_symbol(history_rows)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        closes = [item.close for item in grouped.get(row.symbol, [])[-days:] if item.close is not None]
        if row.close is None or len(closes) < days:
            continue
        if row.close > max(closes):
            candidates.append(_candidate(row, [f"{days}日突破"], new_high_60d=days == 60))
    return candidates[:SCREENING_MAX_CANDIDATES]


def _institutional_buy_candidates(
    rows: list[OhlcvRecord],
    institutional_by_symbol: dict[str, InstitutionalTradingRecord],
    institutional_metrics_by_symbol: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        institutional = institutional_by_symbol.get(row.symbol)
        if institutional is None or institutional.institutional_net_buy is None or institutional.institutional_net_buy <= 0:
            continue
        candidates.append(_candidate(row, ["法人買超"], institutional=institutional, institutional_metrics=institutional_metrics_by_symbol.get(row.symbol, {})))
    candidates.sort(key=lambda item: (item.get("institutional_net_buy_5d") or 0, item.get("institutional_net_buy_20d") or 0, item.get("institutional_net_buy") or 0), reverse=True)
    return candidates[:SCREENING_MAX_CANDIDATES]


def _margin_short_attention_candidates(
    rows: list[OhlcvRecord],
    margin_short_by_symbol: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    row_by_symbol = {row.symbol: row for row in rows}
    top_short_change = {
        symbol
        for symbol, metrics in sorted(
            margin_short_by_symbol.items(),
            key=lambda item: item[1].get("short_change") if item[1].get("short_change") is not None else -10**18,
            reverse=True,
        )[:SCREENING_MAX_CANDIDATES]
    }
    top_margin_balance = {
        symbol
        for symbol, metrics in sorted(
            margin_short_by_symbol.items(),
            key=lambda item: item[1].get("margin_balance") if item[1].get("margin_balance") is not None else -10**18,
            reverse=True,
        )[:SCREENING_MAX_CANDIDATES]
    }
    candidates: list[dict[str, Any]] = []
    for symbol, row in row_by_symbol.items():
        metrics = margin_short_by_symbol.get(symbol)
        if not metrics:
            continue
        if (
            (metrics.get("short_change") is not None and metrics["short_change"] > 0)
            or (metrics.get("margin_change") is not None and metrics["margin_change"] > 0)
            or (metrics.get("short_balance_ratio_20d") is not None and metrics["short_balance_ratio_20d"] >= 1.5)
            or (metrics.get("margin_balance_ratio_20d") is not None and metrics["margin_balance_ratio_20d"] >= 1.5)
            or (metrics.get("short_margin_ratio") is not None and metrics["short_margin_ratio"] >= 0.3)
            or symbol in top_short_change
            or symbol in top_margin_balance
        ):
            candidates.append(_candidate(row, ["資券異常"], margin_short=metrics))
    candidates.sort(key=_margin_short_sort_key)
    return candidates[:SCREENING_MAX_CANDIDATES]


def _mops_events_by_symbol(rows: list[MopsEventRecord]) -> dict[str, list[MopsEventRecord]]:
    grouped: dict[str, list[MopsEventRecord]] = defaultdict(list)
    for row in rows:
        if row.symbol:
            grouped[row.symbol].append(row)
    return grouped


def _mops_event_candidates(
    rows: list[OhlcvRecord],
    mops_event_metrics_by_symbol: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        metrics = mops_event_metrics_by_symbol.get(row.symbol, {})
        if not metrics.get("mops_event_flag"):
            continue
        candidates.append(_candidate(row, ["重大訊息"], mops_event_metrics=metrics))
    candidates.sort(key=lambda item: (-(item.get("mops_event_count_7d") or 0), item["symbol"]))
    return candidates[:SCREENING_MAX_CANDIDATES]


def _institutional_metrics_by_symbol(
    current_by_symbol: dict[str, InstitutionalTradingRecord],
    history_rows: dict[str, list[InstitutionalTradingRecord]],
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    history_by_symbol = _history_by_symbol(history_rows)
    for symbol, current in current_by_symbol.items():
        history = [item for item in history_by_symbol.get(symbol, []) if item.date <= current.date]
        if not any(item.date == current.date for item in history):
            history.append(current)
        history.sort(key=lambda item: item.date)
        output[symbol] = _institutional_metrics(history)
    _apply_institutional_ranks(output)
    return output


def _history_by_symbol(history_rows: dict[str, list[Any]]) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for day in sorted(history_rows):
        for item in history_rows[day]:
            if item.symbol:
                grouped[item.symbol].append(item)
    for rows in grouped.values():
        rows.sort(key=lambda item: item.date)
    return grouped


def _institutional_metrics(rows: list[InstitutionalTradingRecord]) -> dict[str, Any]:
    current = rows[-1]
    return {
        "foreign_net_buy_5d": _sum_record_values(rows, "foreign_net_buy", 5),
        "foreign_net_buy_20d": _sum_record_values(rows, "foreign_net_buy", 20),
        "foreign_net_buy_60d": _sum_record_values(rows, "foreign_net_buy", 60),
        "investment_trust_net_buy_5d": _sum_record_values(rows, "investment_trust_net_buy", 5),
        "investment_trust_net_buy_20d": _sum_record_values(rows, "investment_trust_net_buy", 20),
        "investment_trust_net_buy_60d": _sum_record_values(rows, "investment_trust_net_buy", 60),
        "dealer_net_buy_5d": _sum_record_values(rows, "dealer_net_buy", 5),
        "dealer_net_buy_20d": _sum_record_values(rows, "dealer_net_buy", 20),
        "dealer_net_buy_60d": _sum_record_values(rows, "dealer_net_buy", 60),
        "institutional_net_buy_5d": _sum_record_values(rows, "institutional_net_buy", 5),
        "institutional_net_buy_20d": _sum_record_values(rows, "institutional_net_buy", 20),
        "institutional_net_buy_60d": _sum_record_values(rows, "institutional_net_buy", 60),
        "foreign_consecutive_buy_days": _consecutive_days(rows, "foreign_net_buy", positive=True),
        "foreign_consecutive_sell_days": _consecutive_days(rows, "foreign_net_buy", positive=False),
        "investment_trust_consecutive_buy_days": _consecutive_days(rows, "investment_trust_net_buy", positive=True),
        "investment_trust_consecutive_sell_days": _consecutive_days(rows, "investment_trust_net_buy", positive=False),
        "institutional_consecutive_buy_days": _consecutive_days(rows, "institutional_net_buy", positive=True),
        "institutional_consecutive_sell_days": _consecutive_days(rows, "institutional_net_buy", positive=False),
        "institutional_rank_20d": None,
        "institutional_rank_60d": None,
        "institutional_confirmation": bool(current.institutional_net_buy is not None and current.institutional_net_buy > 0),
        "institutional_partial": any(
            value is None
            for value in (current.foreign_net_buy, current.investment_trust_net_buy, current.dealer_net_buy, current.institutional_net_buy)
        ),
    }


def _sum_record_values(rows: list[Any], attr: str, days: int) -> int | None:
    selected = rows[-days:]
    values = [getattr(row, attr) for row in selected if getattr(row, attr) is not None]
    return sum(values) if values else None


def _consecutive_days(rows: list[Any], attr: str, positive: bool) -> int:
    total = 0
    for row in reversed(rows):
        value = getattr(row, attr)
        if value is None or (value <= 0 if positive else value >= 0):
            break
        total += 1
    return total


def _apply_institutional_ranks(metrics_by_symbol: dict[str, dict[str, Any]]) -> None:
    for field, rank_field in (("institutional_net_buy_20d", "institutional_rank_20d"), ("institutional_net_buy_60d", "institutional_rank_60d")):
        ranked = sorted(
            [(symbol, metrics.get(field)) for symbol, metrics in metrics_by_symbol.items() if metrics.get(field) is not None],
            key=lambda item: item[1],
            reverse=True,
        )
        for index, (symbol, _value) in enumerate(ranked, start=1):
            metrics_by_symbol[symbol][rank_field] = index


def _margin_short_metrics(row: MarginShortRecord, history: list[MarginShortRecord]) -> dict[str, Any]:
    history = [item for item in history if item.date < row.date]
    margin_values = [item.margin_balance for item in history[-20:] if item.margin_balance is not None]
    short_values = [item.short_balance for item in history[-20:] if item.short_balance is not None]
    avg_margin = mean(margin_values) if len(margin_values) >= 20 else None
    avg_short = mean(short_values) if len(short_values) >= 20 else None
    short_margin_ratio = row.short_balance / row.margin_balance if row.short_balance is not None and row.margin_balance else None
    attention_flag = (
        (row.short_change is not None and row.short_change > 0)
        or (row.margin_change is not None and row.margin_change > 0)
        or (row.margin_balance is not None and avg_margin is not None and avg_margin > 0 and row.margin_balance / avg_margin >= 1.5)
        or (row.short_balance is not None and avg_short is not None and avg_short > 0 and row.short_balance / avg_short >= 1.5)
        or (short_margin_ratio is not None and short_margin_ratio >= 0.3)
    )
    return {
        "margin_balance": row.margin_balance,
        "margin_change": row.margin_change,
        "short_balance": row.short_balance,
        "short_change": row.short_change,
        "margin_balance_5d_change": _balance_change(row.margin_balance, history, "margin_balance", 5),
        "margin_balance_20d_change": _balance_change(row.margin_balance, history, "margin_balance", 20),
        "margin_balance_60d_change": _balance_change(row.margin_balance, history, "margin_balance", 60),
        "short_balance_5d_change": _balance_change(row.short_balance, history, "short_balance", 5),
        "short_balance_20d_change": _balance_change(row.short_balance, history, "short_balance", 20),
        "short_balance_60d_change": _balance_change(row.short_balance, history, "short_balance", 60),
        "margin_balance_avg_20d": round(avg_margin, 4) if avg_margin is not None else None,
        "short_balance_avg_20d": round(avg_short, 4) if avg_short is not None else None,
        "margin_balance_ratio_20d": round(row.margin_balance / avg_margin, 4) if row.margin_balance is not None and avg_margin else None,
        "short_balance_ratio_20d": round(row.short_balance / avg_short, 4) if row.short_balance is not None and avg_short else None,
        "short_margin_ratio": round(short_margin_ratio, 4) if short_margin_ratio is not None else None,
        "margin_short_attention_flag": attention_flag,
        "margin_short_risk_notes": _margin_short_risk_notes(row, avg_margin, avg_short, short_margin_ratio),
        "source": row.source,
    }


def _balance_change(current_value: int | None, history: list[MarginShortRecord], attr: str, days: int) -> int | None:
    values = [getattr(item, attr) for item in history if getattr(item, attr) is not None]
    if current_value is None or len(values) < days:
        return None
    return current_value - values[-days]


def _margin_short_risk_notes(row: MarginShortRecord, avg_margin: float | None, avg_short: float | None, short_margin_ratio: float | None) -> list[str]:
    notes: list[str] = []
    if row.margin_balance is not None and avg_margin and row.margin_balance / avg_margin >= 1.5:
        notes.append("融資餘額高於 20 日均值 1.5 倍")
    if row.short_balance is not None and avg_short and row.short_balance / avg_short >= 1.5:
        notes.append("融券餘額高於 20 日均值 1.5 倍")
    if short_margin_ratio is not None and short_margin_ratio >= 0.3:
        notes.append("融券／融資比例偏高，需人工複核")
    return notes


def _mops_event_metrics_by_symbol(
    report_date: str,
    current_events: list[MopsEventRecord],
    history_payloads: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    end_date = date.fromisoformat(report_date)
    all_events: list[MopsEventRecord] = list(current_events)
    for payload in history_payloads.values():
        for event in payload.get("events", []):
            all_events.append(
                MopsEventRecord(
                    date=event.get("date", ""),
                    time=event.get("time"),
                    symbol=event.get("symbol", ""),
                    name=event.get("name", ""),
                    market=event.get("market"),
                    title=event.get("title", ""),
                    category=event.get("category"),
                    summary=event.get("summary"),
                    url=event.get("url"),
                    source=event.get("source", "MOPS"),
                )
            )
    grouped: dict[str, list[MopsEventRecord]] = defaultdict(list)
    for event in all_events:
        if event.symbol:
            grouped[event.symbol].append(event)
    output: dict[str, dict[str, Any]] = {}
    for symbol, events in grouped.items():
        today = _events_since(events, end_date, 1)
        events_7d = _events_since(events, end_date, 7)
        events_30d = _events_since(events, end_date, 30)
        events_90d = _events_since(events, end_date, 90)
        output[symbol] = {
            "mops_event_count_today": len(today),
            "mops_event_count_7d": len(events_7d),
            "mops_event_count_30d": len(events_30d),
            "mops_event_count_90d": len(events_90d),
            "mops_event_categories_7d": sorted({event.category for event in events_7d if event.category}),
            "mops_event_categories_30d": sorted({event.category for event in events_30d if event.category}),
            "mops_recent_event_titles": [event.title for event in events_7d[:10] if event.title],
            "mops_event_flag": bool(today or events_7d),
            "events_7d": events_7d,
        }
    return output


def _mops_analysis_context(
    report_date: str,
    history_payloads: dict[str, dict[str, Any]],
    current_status: str,
) -> dict[str, Any]:
    payload = history_payloads.get(report_date, {})
    return {
        "requested_date": payload.get("requested_date"),
        "data_date": payload.get("data_date"),
        "status": payload.get("status") or current_status,
        "source_endpoint": payload.get("source_endpoint"),
        "date_validation": payload.get("date_validation"),
    }


def _events_since(events: list[MopsEventRecord], end_date: date, days: int) -> list[MopsEventRecord]:
    start = end_date - timedelta(days=days - 1)
    selected = []
    for event in events:
        if not event.date:
            continue
        event_date = date.fromisoformat(event.date)
        if start <= event_date <= end_date:
            selected.append(event)
    return sorted(selected, key=lambda item: (item.date, item.time or ""), reverse=True)


def _margin_short_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int]:
    return (
        -(candidate.get("short_change") or 0),
        -(candidate.get("margin_change") or 0),
        -(candidate.get("margin_balance") or 0),
    )


def _candidate(row: OhlcvRecord, tags: list[str], **extra: Any) -> dict[str, Any]:
    institutional: InstitutionalTradingRecord | None = extra.get("institutional")
    institutional_metrics: dict[str, Any] = extra.get("institutional_metrics") or {}
    margin_short: dict[str, Any] | None = extra.get("margin_short")
    mops_event_metrics: dict[str, Any] = extra.get("mops_event_metrics") or {}
    mops_events: list[MopsEventRecord] = extra.get("mops_events") or mops_event_metrics.get("events_7d") or []
    payload: dict[str, Any] = {
        "symbol": row.symbol,
        "name": row.name,
        "market": row.market,
        "close": row.close,
        "change_pct": row.change_pct,
        "volume": row.volume,
        "turnover": row.turnover,
        "security_type": row.security_type,
        "scan_eligible": row.scan_eligible,
        "exclude_reason": row.exclude_reason,
        "volume_ratio_20d": extra.get("volume_ratio_20d"),
        "new_high_20d": extra.get("new_high_20d", False),
        "new_high_60d": extra.get("new_high_60d", False),
        "foreign_net_buy": institutional.foreign_net_buy if institutional else None,
        "investment_trust_net_buy": institutional.investment_trust_net_buy if institutional else None,
        "dealer_net_buy": institutional.dealer_net_buy if institutional else None,
        "institutional_net_buy": institutional.institutional_net_buy if institutional else None,
        "institutional_net_buy_5d": institutional_metrics.get("institutional_net_buy_5d"),
        "institutional_net_buy_20d": institutional_metrics.get("institutional_net_buy_20d"),
        "institutional_net_buy_60d": institutional_metrics.get("institutional_net_buy_60d"),
        "foreign_net_buy_5d": institutional_metrics.get("foreign_net_buy_5d"),
        "foreign_net_buy_20d": institutional_metrics.get("foreign_net_buy_20d"),
        "foreign_net_buy_60d": institutional_metrics.get("foreign_net_buy_60d"),
        "investment_trust_net_buy_5d": institutional_metrics.get("investment_trust_net_buy_5d"),
        "investment_trust_net_buy_20d": institutional_metrics.get("investment_trust_net_buy_20d"),
        "investment_trust_net_buy_60d": institutional_metrics.get("investment_trust_net_buy_60d"),
        "dealer_net_buy_5d": institutional_metrics.get("dealer_net_buy_5d"),
        "dealer_net_buy_20d": institutional_metrics.get("dealer_net_buy_20d"),
        "dealer_net_buy_60d": institutional_metrics.get("dealer_net_buy_60d"),
        "foreign_consecutive_buy_days": institutional_metrics.get("foreign_consecutive_buy_days"),
        "foreign_consecutive_sell_days": institutional_metrics.get("foreign_consecutive_sell_days"),
        "investment_trust_consecutive_buy_days": institutional_metrics.get("investment_trust_consecutive_buy_days"),
        "investment_trust_consecutive_sell_days": institutional_metrics.get("investment_trust_consecutive_sell_days"),
        "institutional_consecutive_buy_days": institutional_metrics.get("institutional_consecutive_buy_days"),
        "institutional_consecutive_sell_days": institutional_metrics.get("institutional_consecutive_sell_days"),
        "institutional_rank_20d": institutional_metrics.get("institutional_rank_20d"),
        "institutional_rank_60d": institutional_metrics.get("institutional_rank_60d"),
        "institutional_confirmation": bool(institutional_metrics.get("institutional_confirmation")) if institutional else False,
        "institutional_partial": bool(institutional_metrics.get("institutional_partial")) if institutional else False,
        "margin_balance": margin_short.get("margin_balance") if margin_short else None,
        "margin_change": margin_short.get("margin_change") if margin_short else None,
        "short_balance": margin_short.get("short_balance") if margin_short else None,
        "short_change": margin_short.get("short_change") if margin_short else None,
        "margin_balance_5d_change": margin_short.get("margin_balance_5d_change") if margin_short else None,
        "margin_balance_20d_change": margin_short.get("margin_balance_20d_change") if margin_short else None,
        "margin_balance_60d_change": margin_short.get("margin_balance_60d_change") if margin_short else None,
        "short_balance_5d_change": margin_short.get("short_balance_5d_change") if margin_short else None,
        "short_balance_20d_change": margin_short.get("short_balance_20d_change") if margin_short else None,
        "short_balance_60d_change": margin_short.get("short_balance_60d_change") if margin_short else None,
        "margin_balance_avg_20d": margin_short.get("margin_balance_avg_20d") if margin_short else None,
        "short_balance_avg_20d": margin_short.get("short_balance_avg_20d") if margin_short else None,
        "margin_balance_ratio_20d": margin_short.get("margin_balance_ratio_20d") if margin_short else None,
        "short_balance_ratio_20d": margin_short.get("short_balance_ratio_20d") if margin_short else None,
        "short_margin_ratio": margin_short.get("short_margin_ratio") if margin_short else None,
        "margin_short_attention_flag": bool(margin_short.get("margin_short_attention_flag")) if margin_short else False,
        "margin_short_risk_notes": margin_short.get("margin_short_risk_notes") if margin_short else [],
        "event_count": len(mops_events) if mops_events else None,
        "event_categories": sorted({event.category for event in mops_events if event.category}) if mops_events else [],
        "event_titles": [event.title for event in mops_events if event.title] if mops_events else [],
        "mops_event_flag": bool(mops_event_metrics.get("mops_event_flag")) if mops_event_metrics else bool(mops_events),
        "mops_event_count_today": mops_event_metrics.get("mops_event_count_today", 0),
        "mops_event_count_7d": mops_event_metrics.get("mops_event_count_7d", 0),
        "mops_event_count_30d": mops_event_metrics.get("mops_event_count_30d", 0),
        "mops_event_count_90d": mops_event_metrics.get("mops_event_count_90d", 0),
        "mops_event_categories_7d": mops_event_metrics.get("mops_event_categories_7d", []),
        "mops_event_categories_30d": mops_event_metrics.get("mops_event_categories_30d", []),
        "mops_recent_event_titles": mops_event_metrics.get("mops_recent_event_titles", []),
        "tags": tags,
        "reasons": _reasons(tags, extra),
        "risk_notes": _risk_notes(tags),
        "source_refs": [row.source]
        + ([institutional.source] if institutional else [])
        + ([margin_short["source"]] if margin_short else [])
        + (["MOPS"] if mops_events else []),
    }
    return payload


def _reasons(tags: list[str], extra: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if "漲停初篩" in tags:
        reasons.append("漲幅接近或達到台股一般漲停幅度")
    if "量增" in tags:
        reasons.append(f"成交量高於 20 日均量 {extra.get('volume_ratio_20d')} 倍")
    institutional: InstitutionalTradingRecord | None = extra.get("institutional")
    if "法人買超" in tags and institutional:
        reasons.append("三大法人合計買超")
        if institutional.foreign_net_buy is not None and institutional.foreign_net_buy > 0:
            reasons.append("外資買超")
        if institutional.investment_trust_net_buy is not None and institutional.investment_trust_net_buy > 0:
            reasons.append("投信買超")
        if institutional.dealer_net_buy is not None and institutional.dealer_net_buy > 0:
            reasons.append("自營商買超")
    margin_short: dict[str, Any] | None = extra.get("margin_short")
    if "資券異常" in tags and margin_short:
        if margin_short.get("margin_change") is not None and margin_short["margin_change"] > 0:
            reasons.append("融資餘額增加")
        if margin_short.get("short_change") is not None and margin_short["short_change"] > 0:
            reasons.append("融券餘額增加")
        reasons.append("資券變化需人工複核")
    mops_events: list[MopsEventRecord] = extra.get("mops_events") or []
    if "重大訊息" in tags and mops_events:
        reasons.append(f"MOPS 重大訊息 {len(mops_events)} 則")
        categories = sorted({event.category for event in mops_events if event.category})
        if categories:
            reasons.append("事件類別：" + ", ".join(categories))
    for tag in tags:
        if tag.endswith("日突破"):
            reasons.append(f"收盤價創近 {tag.removesuffix('突破')} 新高")
    return reasons


def _risk_notes(tags: list[str]) -> list[str]:
    notes = ["僅供研究與人工複核，不構成買賣建議"]
    if "資券異常" in tags:
        notes.append("資券變化可能代表籌碼分歧，不可單獨視為買賣訊號")
    if "重大訊息" in tags:
        notes.append("重大訊息不等於利多，需人工閱讀公告內容與確認事件性質。")
    return notes
