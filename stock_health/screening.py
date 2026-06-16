from __future__ import annotations

from collections import defaultdict
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
    margin_short_rows: list[MarginShortRecord] | None = None,
    margin_short_history_rows: dict[str, list[MarginShortRecord]] | None = None,
    mops_event_rows: list[MopsEventRecord] | None = None,
) -> dict[str, Any]:
    all_rows = listed_rows + otc_rows
    eligible_rows = [row for row in all_rows if row.scan_eligible]
    institutional_rows = institutional_rows or []
    institutional_by_symbol = {row.symbol: row for row in institutional_rows}
    margin_short_rows = margin_short_rows or []
    margin_short_history_rows = margin_short_history_rows or {}
    margin_short_by_symbol = {row.symbol: row for row in margin_short_rows}
    margin_short_metrics_by_symbol = {
        symbol: _margin_short_metrics(row, margin_short_history_rows)
        for symbol, row in margin_short_by_symbol.items()
    }
    mops_event_rows = mops_event_rows or []
    mops_events_by_symbol = _mops_events_by_symbol(mops_event_rows)
    historical_days = sorted(history_rows)
    has_20d_history = len(historical_days) >= 20
    has_60d_history = len(historical_days) >= 60
    limitations: list[str] = []
    if not has_20d_history:
        limitations.append("歷史資料不足 20 個交易日；未產生 20 日均量、爆量倍數或 20 日突破訊號")
    if not has_60d_history:
        limitations.append("歷史資料不足 60 個交易日；未產生 60 日突破訊號")
    if missing_sections:
        limitations.append("核心資料段落缺失：" + ", ".join(missing_sections))
    if margin_short_rows and len(margin_short_history_rows) < 20:
        limitations.append("資券歷史資料不足 20 個交易日；margin_balance_ratio_20d 與 short_balance_ratio_20d 保留 null")
    margin_short_attention = _margin_short_attention_candidates(eligible_rows, margin_short_metrics_by_symbol)
    margin_short_attention_symbols = {item["symbol"] for item in margin_short_attention}
    mops_event_candidates = _mops_event_candidates(eligible_rows, mops_events_by_symbol)
    qullamaggie = calculate_qullamaggie_signals(
        eligible_rows,
        history_rows,
        institutional_by_symbol=institutional_by_symbol,
        margin_short_by_symbol=margin_short_metrics_by_symbol,
        margin_short_attention_symbols=margin_short_attention_symbols,
        mops_events_by_symbol=mops_events_by_symbol,
    )
    limitations.extend(qullamaggie["limitations"])

    return {
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
        "historical_data_status": {
            "available_trading_days": len(historical_days),
            "has_20d_history": has_20d_history,
            "has_60d_history": has_60d_history,
            "start_date": historical_days[0] if historical_days else None,
            "end_date": historical_days[-1] if historical_days else None,
        },
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
            "institutional_buy_candidates": _institutional_buy_candidates(eligible_rows, institutional_by_symbol),
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


def _market_summary(rows: list[OhlcvRecord]) -> dict[str, Any]:
    change_values = [row.change_pct for row in rows if row.change_pct is not None]
    return {
        "total_symbols": len(rows),
        "advancers": sum(1 for row in rows if row.change_pct is not None and row.change_pct > 0),
        "decliners": sum(1 for row in rows if row.change_pct is not None and row.change_pct < 0),
        "unchanged": sum(1 for row in rows if row.change_pct == 0),
        "average_change_pct": round(mean(change_values), 4) if change_values else None,
    }


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
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        institutional = institutional_by_symbol.get(row.symbol)
        if institutional is None or institutional.institutional_net_buy is None or institutional.institutional_net_buy <= 0:
            continue
        candidates.append(_candidate(row, ["法人買超"], institutional=institutional))
    candidates.sort(key=lambda item: item.get("institutional_net_buy") or 0, reverse=True)
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
    mops_events_by_symbol: dict[str, list[MopsEventRecord]],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in rows:
        events = mops_events_by_symbol.get(row.symbol, [])
        if not events:
            continue
        candidates.append(_candidate(row, ["重大訊息"], mops_events=events))
    candidates.sort(key=lambda item: (-(item.get("event_count") or 0), item["symbol"]))
    return candidates[:SCREENING_MAX_CANDIDATES]


def _margin_short_metrics(row: MarginShortRecord, history_rows: dict[str, list[MarginShortRecord]]) -> dict[str, Any]:
    history = [
        item
        for day in sorted(history_rows)
        for item in history_rows[day]
        if item.symbol == row.symbol and item.date < row.date
    ]
    margin_values = [item.margin_balance for item in history[-20:] if item.margin_balance is not None]
    short_values = [item.short_balance for item in history[-20:] if item.short_balance is not None]
    avg_margin = mean(margin_values) if len(margin_values) >= 20 else None
    avg_short = mean(short_values) if len(short_values) >= 20 else None
    return {
        "margin_balance": row.margin_balance,
        "margin_change": row.margin_change,
        "short_balance": row.short_balance,
        "short_change": row.short_change,
        "margin_balance_ratio_20d": round(row.margin_balance / avg_margin, 4) if row.margin_balance is not None and avg_margin else None,
        "short_balance_ratio_20d": round(row.short_balance / avg_short, 4) if row.short_balance is not None and avg_short else None,
        "source": row.source,
    }


def _margin_short_sort_key(candidate: dict[str, Any]) -> tuple[int, int, int]:
    return (
        -(candidate.get("short_change") or 0),
        -(candidate.get("margin_change") or 0),
        -(candidate.get("margin_balance") or 0),
    )


def _candidate(row: OhlcvRecord, tags: list[str], **extra: Any) -> dict[str, Any]:
    institutional: InstitutionalTradingRecord | None = extra.get("institutional")
    margin_short: dict[str, Any] | None = extra.get("margin_short")
    mops_events: list[MopsEventRecord] = extra.get("mops_events") or []
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
        "margin_balance": margin_short.get("margin_balance") if margin_short else None,
        "margin_change": margin_short.get("margin_change") if margin_short else None,
        "short_balance": margin_short.get("short_balance") if margin_short else None,
        "short_change": margin_short.get("short_change") if margin_short else None,
        "margin_balance_ratio_20d": margin_short.get("margin_balance_ratio_20d") if margin_short else None,
        "short_balance_ratio_20d": margin_short.get("short_balance_ratio_20d") if margin_short else None,
        "event_count": len(mops_events) if mops_events else None,
        "event_categories": sorted({event.category for event in mops_events if event.category}) if mops_events else [],
        "event_titles": [event.title for event in mops_events if event.title] if mops_events else [],
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
