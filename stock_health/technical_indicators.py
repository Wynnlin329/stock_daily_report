from __future__ import annotations

from collections import defaultdict
from statistics import mean
from typing import Any

from .config import (
    ADR_WINDOW_DAYS,
    ATR_METHOD,
    ATR_WINDOW_DAYS,
    COMPOSITE_RS_WEIGHTS,
    MULTI_PERIOD_RETURN_WINDOWS,
)
from .models import OhlcvRecord

ENHANCED_TECHNICAL_FIELDS = [
    "adr20_pct",
    "atr14",
    "atr14_pct",
    "stop_risk_pct",
    "stop_to_adr_ratio",
    "stop_to_atr_ratio",
    "return_1m",
    "return_3m",
    "return_6m",
    "rs_rank_1m",
    "rs_rank_3m",
    "rs_rank_6m",
    "composite_rs_rank",
]


def calculate_enhanced_technical_metrics(
    current: OhlcvRecord,
    history: list[OhlcvRecord],
    stop_reference: float | None,
) -> dict[str, Any]:
    missing_reason: dict[str, str] = {}
    current_valid = _is_valid_trading_row(current)
    valid_rows = _valid_rows_through_date(history, current)
    history_reason = (
        "current_row_invalid_or_suspended"
        if not current_valid
        else None
    )

    adr20_pct = _adr_pct(valid_rows, ADR_WINDOW_DAYS)
    if adr20_pct is None:
        missing_reason["adr20_pct"] = history_reason or _history_reason(valid_rows, ADR_WINDOW_DAYS)

    atr14 = _sma_atr(valid_rows, ATR_WINDOW_DAYS)
    if atr14 is None:
        missing_reason["atr14"] = history_reason or _history_reason(valid_rows, ATR_WINDOW_DAYS + 1)
    atr14_pct = None
    if atr14 is not None and current.close is not None and current.close > 0:
        atr14_pct = _round(atr14 / current.close * 100)
    else:
        missing_reason["atr14_pct"] = missing_reason.get("atr14", "invalid_current_close")

    stop_risk_pct = None
    if not current_valid:
        missing_reason["stop_risk_pct"] = "current_row_invalid_or_suspended"
    elif current.close is None or current.close <= 0:
        missing_reason["stop_risk_pct"] = "invalid_current_close"
    elif stop_reference is None or stop_reference <= 0:
        missing_reason["stop_risk_pct"] = "missing_stop_reference"
    elif stop_reference >= current.close:
        missing_reason["stop_risk_pct"] = "stop_reference_not_below_close"
    else:
        stop_risk_pct = _round((current.close - stop_reference) / current.close * 100)

    stop_to_adr_ratio = _ratio(stop_risk_pct, adr20_pct)
    if stop_to_adr_ratio is None:
        missing_reason["stop_to_adr_ratio"] = _ratio_reason(
            stop_risk_pct,
            adr20_pct,
            missing_reason.get("stop_risk_pct"),
            missing_reason.get("adr20_pct"),
        )
    stop_to_atr_ratio = _ratio(stop_risk_pct, atr14_pct)
    if stop_to_atr_ratio is None:
        missing_reason["stop_to_atr_ratio"] = _ratio_reason(
            stop_risk_pct,
            atr14_pct,
            missing_reason.get("stop_risk_pct"),
            missing_reason.get("atr14_pct"),
        )

    returns: dict[str, float | None] = {}
    for period, window in MULTI_PERIOD_RETURN_WINDOWS.items():
        field = f"return_{period}"
        returns[field] = _return_for_window(valid_rows, window)
        if returns[field] is None:
            missing_reason[field] = history_reason or _history_reason(valid_rows, window + 1)

    return {
        "adr20_pct": adr20_pct,
        "atr14": atr14,
        "atr14_pct": atr14_pct,
        "stop_risk_pct": stop_risk_pct,
        "stop_to_adr_ratio": stop_to_adr_ratio,
        "stop_to_atr_ratio": stop_to_atr_ratio,
        **returns,
        "rs_rank_1m": None,
        "rs_rank_3m": None,
        "rs_rank_6m": None,
        "composite_rs_rank": None,
        "missing_reason": missing_reason,
        "indicator_basis": {
            "adr_window": ADR_WINDOW_DAYS,
            "adr_formula": "mean((high-low)/close*100)",
            "atr_window": ATR_WINDOW_DAYS,
            "atr_method": ATR_METHOD,
            "atr_pct_denominator": "current_close",
            "stop_risk_denominator": "current_close",
            "return_windows": dict(MULTI_PERIOD_RETURN_WINDOWS),
            "composite_rs_weights": dict(COMPOSITE_RS_WEIGHTS),
            "valid_trading_day": "positive complete OHLC and volume>0",
        },
    }


def apply_multi_period_rs_ranks(candidates: list[dict[str, Any]]) -> None:
    by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        if candidate.get("scan_eligible"):
            by_date[str(candidate.get("date") or "")].append(candidate)

    for same_date_candidates in by_date.values():
        for period in MULTI_PERIOD_RETURN_WINDOWS:
            return_field = f"return_{period}"
            rank_field = f"rs_rank_{period}"
            ranked = [item for item in same_date_candidates if _number(item.get(return_field)) is not None]
            _apply_percentile_rank(ranked, return_field, rank_field)
            for candidate in same_date_candidates:
                if candidate.get(rank_field) is None:
                    reasons = candidate.setdefault("missing_reason", {})
                    reasons[rank_field] = reasons.get(return_field, f"missing_{return_field}")

        for candidate in same_date_candidates:
            ranks = {
                period: _number(candidate.get(f"rs_rank_{period}"))
                for period in MULTI_PERIOD_RETURN_WINDOWS
            }
            if all(value is not None for value in ranks.values()):
                candidate["composite_rs_rank"] = _round(
                    sum(float(ranks[period]) * COMPOSITE_RS_WEIGHTS[period] for period in MULTI_PERIOD_RETURN_WINDOWS)
                )
            else:
                candidate["composite_rs_rank"] = None
                candidate.setdefault("missing_reason", {})["composite_rs_rank"] = "one_or_more_rs_periods_missing"


def build_enhanced_indicator_coverage(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [candidate for candidate in candidates if candidate.get("scan_eligible")]
    total = len(eligible)
    fields: dict[str, dict[str, int | float]] = {}
    for field in ENHANCED_TECHNICAL_FIELDS:
        available = sum(1 for candidate in eligible if candidate.get(field) is not None)
        fields[field] = {
            "available": available,
            "missing": total - available,
            "coverage_pct": round(available / total * 100, 4) if total else 0.0,
        }
    return {
        "eligible_symbols": total,
        "fields": fields,
        "all_fields_complete_symbols": sum(
            1 for candidate in eligible if all(candidate.get(field) is not None for field in ENHANCED_TECHNICAL_FIELDS)
        ),
        "informational_only": True,
        "affects_grading_policy_v1": False,
    }


def _valid_rows_through_date(history: list[OhlcvRecord], current: OhlcvRecord) -> list[OhlcvRecord]:
    if not _is_valid_trading_row(current):
        return []
    by_date: dict[str, OhlcvRecord] = {}
    for row in [*history, current]:
        if row.date <= current.date and _is_valid_trading_row(row):
            by_date[row.date] = row
    return [by_date[day] for day in sorted(by_date)]


def _is_valid_trading_row(row: OhlcvRecord) -> bool:
    prices = (row.open, row.high, row.low, row.close)
    if any(value is None or value <= 0 for value in prices):
        return False
    if row.volume is None or row.volume <= 0:
        return False
    return bool(row.high >= row.low)


def _adr_pct(rows: list[OhlcvRecord], window: int) -> float | None:
    if len(rows) < window:
        return None
    values = [(row.high - row.low) / row.close * 100 for row in rows[-window:]]
    return _round(mean(values))


def _sma_atr(rows: list[OhlcvRecord], window: int) -> float | None:
    if len(rows) < window + 1:
        return None
    selected = rows[-(window + 1) :]
    true_ranges = [
        max(
            row.high - row.low,
            abs(row.high - previous.close),
            abs(row.low - previous.close),
        )
        for previous, row in zip(selected, selected[1:])
    ]
    return _round(mean(true_ranges))


def _return_for_window(rows: list[OhlcvRecord], window: int) -> float | None:
    if len(rows) < window + 1:
        return None
    base_close = rows[-(window + 1)].close
    current_close = rows[-1].close
    if base_close is None or base_close <= 0 or current_close is None or current_close <= 0:
        return None
    return _round((current_close / base_close - 1) * 100)


def _apply_percentile_rank(candidates: list[dict[str, Any]], value_field: str, rank_field: str) -> None:
    if not candidates:
        return
    ordered = sorted(candidates, key=lambda item: (_number(item.get(value_field)), str(item.get("symbol") or "")))
    denominator = max(1, len(ordered) - 1)
    start = 0
    while start < len(ordered):
        value = _number(ordered[start].get(value_field))
        end = start
        while end + 1 < len(ordered) and _number(ordered[end + 1].get(value_field)) == value:
            end += 1
        percentile = 100.0 if len(ordered) == 1 else _round(((start + end) / 2) / denominator * 100)
        for index in range(start, end + 1):
            ordered[index][rank_field] = percentile
            ordered[index].setdefault("missing_reason", {}).pop(rank_field, None)
        start = end + 1


def _history_reason(rows: list[OhlcvRecord], required: int) -> str:
    return f"insufficient_valid_trading_days:{len(rows)}/{required}"


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return _round(numerator / denominator)


def _ratio_reason(
    numerator: float | None,
    denominator: float | None,
    numerator_reason: str | None,
    denominator_reason: str | None,
) -> str:
    if numerator is None:
        return numerator_reason or "missing_numerator"
    if denominator is None:
        return denominator_reason or "missing_denominator"
    return "non_positive_denominator"


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: float) -> float:
    return round(value, 4)
