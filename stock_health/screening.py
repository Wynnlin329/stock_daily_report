from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from .config import SCHEMA_VERSION, TIMEZONE
from .models import OhlcvRecord
from .qullamaggie import calculate_qullamaggie_signals


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
) -> dict[str, Any]:
    all_rows = listed_rows + otc_rows
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
    qullamaggie = calculate_qullamaggie_signals(all_rows, history_rows)
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
        "historical_data_status": {
            "available_trading_days": len(historical_days),
            "has_20d_history": has_20d_history,
            "has_60d_history": has_60d_history,
            "start_date": historical_days[0] if historical_days else None,
            "end_date": historical_days[-1] if historical_days else None,
        },
        "market_summary": _market_summary(all_rows),
        "rankings": {
            "top_turnover": [_candidate(row, []) for row in sorted(all_rows, key=lambda item: item.turnover or 0, reverse=True)[:20]],
            "top_volume": [_candidate(row, []) for row in sorted(all_rows, key=lambda item: item.volume or 0, reverse=True)[:20]],
            "top_gainers": [_candidate(row, []) for row in sorted(all_rows, key=lambda item: item.change_pct if item.change_pct is not None else -999, reverse=True)[:20]],
        },
        "screening": {
            "limit_up": [_candidate(row, ["漲停初篩"]) for row in all_rows if row.change_pct is not None and row.change_pct >= 9.5],
            "volume_spike": _volume_spike_candidates(all_rows, history_rows) if has_20d_history else [],
            "breakout_candidates": _breakout_candidates(all_rows, history_rows, 60) if has_60d_history else [],
            "institutional_buy_candidates": [],
            "margin_short_attention": [],
            "mops_event_candidates": [],
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
    return candidates[:50]


def _breakout_candidates(rows: list[OhlcvRecord], history_rows: dict[str, list[OhlcvRecord]], days: int) -> list[dict[str, Any]]:
    grouped = _history_by_symbol(history_rows)
    candidates: list[dict[str, Any]] = []
    for row in rows:
        closes = [item.close for item in grouped.get(row.symbol, [])[-days:] if item.close is not None]
        if row.close is None or len(closes) < days:
            continue
        if row.close > max(closes):
            candidates.append(_candidate(row, [f"{days}日突破"], new_high_60d=days == 60))
    return candidates[:50]


def _candidate(row: OhlcvRecord, tags: list[str], **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": row.symbol,
        "name": row.name,
        "market": row.market,
        "close": row.close,
        "change_pct": row.change_pct,
        "volume": row.volume,
        "turnover": row.turnover,
        "volume_ratio_20d": extra.get("volume_ratio_20d"),
        "new_high_20d": extra.get("new_high_20d", False),
        "new_high_60d": extra.get("new_high_60d", False),
        "institutional_net_buy": None,
        "margin_change": None,
        "tags": tags,
        "reasons": _reasons(tags, extra),
        "risk_notes": ["僅供研究與人工複核，不構成買賣建議"],
        "source_refs": [row.source],
    }
    return payload


def _reasons(tags: list[str], extra: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if "漲停初篩" in tags:
        reasons.append("漲幅接近或達到台股一般漲停幅度")
    if "量增" in tags:
        reasons.append(f"成交量高於 20 日均量 {extra.get('volume_ratio_20d')} 倍")
    for tag in tags:
        if tag.endswith("日突破"):
            reasons.append(f"收盤價創近 {tag.removesuffix('突破')} 新高")
    return reasons
