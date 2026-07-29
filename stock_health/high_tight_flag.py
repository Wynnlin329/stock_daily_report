from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import mean
from typing import Any

from .config import (
    HTF_FLAG_MAX_DAYS,
    HTF_FLAG_MIN_DAYS,
    HTF_52W_TRADING_DAYS,
    HTF_CONTRACTION_SAMPLE_DAYS,
    HTF_ISOLATED_PRICE_OUTLIER_PCT,
    HTF_MA_SLOPE_LOOKBACK_DAYS,
    HTF_MONTHLY_MA_MONTHS,
    HTF_MAX_DISTANCE_TO_52W_HIGH_PCT,
    HTF_MAX_DISTANCE_TO_MA10_PCT,
    HTF_MAX_EXTENSION_FROM_TRIGGER_PCT,
    HTF_MAX_FLAG_DEPTH_PCT,
    HTF_MAX_RANGE_CONTRACTION_RATIO,
    HTF_MAX_VOLUME_CONTRACTION_RATIO,
    HTF_MIN_HIGHER_LOWS_RATIO,
    HTF_NEAR_TRIGGER_PCT,
    HTF_PRIOR_MOVE_MIN_PCT,
    HTF_STRUCTURE_SCORE_WEIGHTS,
    HTF_VALID_SCORE_MIN,
    HTF_VOLUME_BASELINE_DAYS,
    HTF_WEEKLY_FAST_MA_WEEKS,
    HTF_WEEKLY_SLOW_MA_WEEKS,
)
from .models import OhlcvRecord

HTF_OUTPUT_FIELDS = [
    "prior_move_pct_20d",
    "prior_move_pct_60d",
    "high_52w",
    "distance_to_52w_high_pct",
    "flag_duration_days",
    "flag_depth_pct",
    "higher_lows_count",
    "range_contraction_ratio",
    "volume_contraction_ratio",
    "ma10_slope",
    "ma20_slope",
    "ma50_slope",
    "distance_to_ma10_pct",
    "distance_to_ma20_pct",
    "monthly_close",
    "monthly_ma12",
    "monthly_above_ma12",
    "weekly_trend_state",
    "long_term_ma_state",
    "daily_trigger_state",
    "htf_structure_score",
    "htf_structure_status",
    "htf_rejection_reasons",
]


def calculate_htf_structure(current: OhlcvRecord, history: list[OhlcvRecord]) -> dict[str, Any]:
    missing_reason: dict[str, str] = {}
    rows, excluded_outlier_dates = _valid_rows_through_date(history, current)
    if not rows:
        return _insufficient_payload("current_row_invalid_or_suspended", excluded_outlier_dates)

    flag_peak_index = _flag_peak_index(rows)
    flag_rows = rows[flag_peak_index:] if flag_peak_index is not None else []
    flag_peak_price = rows[flag_peak_index].high if flag_peak_index is not None else None
    flag_duration_days = len(flag_rows) if flag_rows else None
    flag_depth_pct = _flag_depth_pct(flag_rows, flag_peak_price)
    higher_lows_count = _higher_lows_count(flag_rows) if flag_rows else None
    range_contraction_ratio = _range_contraction_ratio(flag_rows)
    volume_contraction_ratio = _volume_contraction_ratio(rows, flag_peak_index)
    prior_move_pct_20d = _prior_move_pct(rows, flag_peak_index, 20)
    prior_move_pct_60d = _prior_move_pct(rows, flag_peak_index, 60)
    high_52w = (
        max((row.high for row in rows[-HTF_52W_TRADING_DAYS:]), default=None)
        if len(rows) >= HTF_52W_TRADING_DAYS
        else None
    )
    distance_to_52w_high_pct = _relative_pct(current.close, high_52w)
    ma10 = _moving_average(rows, 10)
    ma20 = _moving_average(rows, 20)
    ma10_slope = _ma_slope(rows, 10, HTF_MA_SLOPE_LOOKBACK_DAYS)
    ma20_slope = _ma_slope(rows, 20, HTF_MA_SLOPE_LOOKBACK_DAYS)
    ma50_slope = _ma_slope(rows, 50, HTF_MA_SLOPE_LOOKBACK_DAYS)
    distance_to_ma10_pct = _relative_pct(current.close, ma10)
    distance_to_ma20_pct = _relative_pct(current.close, ma20)
    monthly_close, monthly_ma12, monthly_above_ma12 = _monthly_metrics(rows)
    weekly_trend_state = _weekly_trend_state(rows)
    long_term_ma_state = _long_term_ma_state(
        current.close,
        _moving_average(rows, 50),
        ma50_slope,
    )
    daily_trigger_state = _daily_trigger_state(
        current,
        flag_peak_price,
        distance_to_ma10_pct,
    )

    values = {
        "prior_move_pct_20d": prior_move_pct_20d,
        "prior_move_pct_60d": prior_move_pct_60d,
        "high_52w": high_52w,
        "distance_to_52w_high_pct": distance_to_52w_high_pct,
        "flag_duration_days": flag_duration_days,
        "flag_depth_pct": flag_depth_pct,
        "higher_lows_count": higher_lows_count,
        "range_contraction_ratio": range_contraction_ratio,
        "volume_contraction_ratio": volume_contraction_ratio,
        "ma10_slope": ma10_slope,
        "ma20_slope": ma20_slope,
        "ma50_slope": ma50_slope,
        "distance_to_ma10_pct": distance_to_ma10_pct,
        "distance_to_ma20_pct": distance_to_ma20_pct,
        "monthly_close": monthly_close,
        "monthly_ma12": monthly_ma12,
        "monthly_above_ma12": monthly_above_ma12,
        "weekly_trend_state": weekly_trend_state,
        "long_term_ma_state": long_term_ma_state,
        "daily_trigger_state": daily_trigger_state,
    }
    required_days = {
        "prior_move_pct_20d": 20,
        "prior_move_pct_60d": 60,
        "high_52w": HTF_52W_TRADING_DAYS,
        "distance_to_52w_high_pct": HTF_52W_TRADING_DAYS,
        "range_contraction_ratio": HTF_FLAG_MIN_DAYS,
        "volume_contraction_ratio": HTF_VOLUME_BASELINE_DAYS,
        "ma10_slope": 10 + HTF_MA_SLOPE_LOOKBACK_DAYS,
        "ma20_slope": 20 + HTF_MA_SLOPE_LOOKBACK_DAYS,
        "ma50_slope": 50 + HTF_MA_SLOPE_LOOKBACK_DAYS,
        "distance_to_ma10_pct": 10,
        "distance_to_ma20_pct": 20,
    }
    for field, value in values.items():
        if value is not None:
            continue
        if field in {"prior_move_pct_20d", "prior_move_pct_60d"}:
            window = 20 if field.endswith("20d") else 60
            available = flag_peak_index + 1 if flag_peak_index is not None else 0
            missing_reason[field] = f"insufficient_pre_peak_trading_days:{available}/{window}"
        elif field == "range_contraction_ratio":
            missing_reason[field] = (
                f"insufficient_flag_duration:{flag_duration_days or 0}/{HTF_FLAG_MIN_DAYS}"
            )
        elif field == "volume_contraction_ratio":
            if flag_peak_index is None or flag_peak_index < HTF_VOLUME_BASELINE_DAYS:
                available = flag_peak_index or 0
                missing_reason[field] = (
                    f"insufficient_pre_peak_volume_days:{available}/{HTF_VOLUME_BASELINE_DAYS}"
                )
            else:
                missing_reason[field] = (
                    f"insufficient_flag_duration:{flag_duration_days or 0}/{HTF_FLAG_MIN_DAYS}"
                )
        elif field == "monthly_close":
            missing_reason[field] = "insufficient_monthly_closes:requires_1"
        elif field in {"monthly_ma12", "monthly_above_ma12"}:
            missing_reason[field] = f"insufficient_monthly_closes:requires_{HTF_MONTHLY_MA_MONTHS}"
        elif field == "weekly_trend_state":
            missing_reason[field] = f"insufficient_weekly_closes:requires_{HTF_WEEKLY_SLOW_MA_WEEKS}"
        elif field == "long_term_ma_state":
            missing_reason[field] = (
                f"insufficient_valid_trading_days:"
                f"{len(rows)}/{50 + HTF_MA_SLOPE_LOOKBACK_DAYS}"
            )
        elif field == "daily_trigger_state":
            missing_reason[field] = "missing_flag_peak"
        elif field in required_days:
            missing_reason[field] = f"insufficient_valid_trading_days:{len(rows)}/{required_days[field]}"
        else:
            missing_reason[field] = "insufficient_flag_structure"

    score = _structure_score(values)
    rejection_reasons = _rejection_reasons(values)
    status = _structure_status(values, rejection_reasons, missing_reason, score)
    return {
        **values,
        "htf_structure_score": score,
        "htf_structure_status": status,
        "htf_rejection_reasons": rejection_reasons,
        "htf_missing_reason": missing_reason,
        "htf_structure_basis": {
            "flag_duration_range": [HTF_FLAG_MIN_DAYS, HTF_FLAG_MAX_DAYS],
            "prior_move_min_pct": HTF_PRIOR_MOVE_MIN_PCT,
            "max_flag_depth_pct": HTF_MAX_FLAG_DEPTH_PCT,
            "max_range_contraction_ratio": HTF_MAX_RANGE_CONTRACTION_RATIO,
            "max_volume_contraction_ratio": HTF_MAX_VOLUME_CONTRACTION_RATIO,
            "min_higher_lows_ratio": HTF_MIN_HIGHER_LOWS_RATIO,
            "max_distance_to_52w_high_pct": HTF_MAX_DISTANCE_TO_52W_HIGH_PCT,
            "ma_slope_lookback_days": HTF_MA_SLOPE_LOOKBACK_DAYS,
            "monthly_ma_months": HTF_MONTHLY_MA_MONTHS,
            "valid_score_min": HTF_VALID_SCORE_MIN,
            "score_weights": dict(HTF_STRUCTURE_SCORE_WEIGHTS),
            "informational_only": True,
            "affects_grading_policy_v1": False,
        },
        "htf_data_quality": {
            "excluded_isolated_price_outlier_dates": excluded_outlier_dates,
            "isolated_price_outlier_threshold_pct": HTF_ISOLATED_PRICE_OUTLIER_PCT,
        },
    }


def build_htf_structure_coverage(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [candidate for candidate in candidates if candidate.get("scan_eligible")]
    statuses: dict[str, int] = defaultdict(int)
    for candidate in eligible:
        statuses[str(candidate.get("htf_structure_status") or "missing")] += 1
    complete = sum(
        1
        for candidate in eligible
        if candidate.get("htf_structure_status") not in {None, "insufficient_data"}
    )
    return {
        "eligible_symbols": len(eligible),
        "complete_symbols": complete,
        "incomplete_symbols": len(eligible) - complete,
        "coverage_pct": _round(complete / len(eligible) * 100) if eligible else 0.0,
        "status_counts": dict(sorted(statuses.items())),
        "informational_only": True,
        "affects_grading_policy_v1": False,
    }


def _flag_peak_index(rows: list[OhlcvRecord]) -> int | None:
    if len(rows) < 2:
        return None
    start = max(0, len(rows) - HTF_FLAG_MAX_DAYS - 1)
    prior_window = rows[start:-1]
    if not prior_window:
        return None
    relative_index = max(range(len(prior_window)), key=lambda index: prior_window[index].high)
    return start + relative_index


def _prior_move_pct(
    rows: list[OhlcvRecord],
    peak_index: int | None,
    window: int,
) -> float | None:
    if peak_index is None or peak_index + 1 < window:
        return None
    selected = rows[peak_index - window + 1 : peak_index + 1]
    base_low = min(row.low for row in selected)
    peak_high = rows[peak_index].high
    if base_low <= 0:
        return None
    return _round((peak_high / base_low - 1) * 100)


def _flag_depth_pct(flag_rows: list[OhlcvRecord], peak_price: float | None) -> float | None:
    if not flag_rows or peak_price is None or peak_price <= 0:
        return None
    flag_low = min(row.low for row in flag_rows)
    return _round((peak_price - flag_low) / peak_price * 100)


def _higher_lows_count(flag_rows: list[OhlcvRecord]) -> int:
    return sum(1 for previous, current in zip(flag_rows, flag_rows[1:]) if current.low > previous.low)


def _range_contraction_ratio(flag_rows: list[OhlcvRecord]) -> float | None:
    if len(flag_rows) < HTF_FLAG_MIN_DAYS:
        return None
    initial = [_daily_range_pct(row) for row in flag_rows[:HTF_CONTRACTION_SAMPLE_DAYS]]
    recent = [_daily_range_pct(row) for row in flag_rows[-HTF_CONTRACTION_SAMPLE_DAYS:]]
    initial_mean = mean(initial)
    if initial_mean <= 0:
        return None
    return _round(mean(recent) / initial_mean)


def _volume_contraction_ratio(rows: list[OhlcvRecord], peak_index: int | None) -> float | None:
    if peak_index is None or peak_index < HTF_VOLUME_BASELINE_DAYS:
        return None
    flag_rows = rows[peak_index:]
    if len(flag_rows) < HTF_FLAG_MIN_DAYS:
        return None
    prior_volume = mean(row.volume for row in rows[peak_index - HTF_VOLUME_BASELINE_DAYS : peak_index])
    if prior_volume <= 0:
        return None
    return _round(mean(row.volume for row in flag_rows[-HTF_CONTRACTION_SAMPLE_DAYS:]) / prior_volume)


def _moving_average(rows: list[OhlcvRecord], window: int, offset: int = 0) -> float | None:
    end = len(rows) - offset
    start = end - window
    if start < 0 or end <= 0:
        return None
    return mean(row.close for row in rows[start:end])


def _ma_slope(rows: list[OhlcvRecord], window: int, lookback: int) -> float | None:
    current = _moving_average(rows, window)
    previous = _moving_average(rows, window, lookback)
    if current is None or previous is None or previous <= 0:
        return None
    return _round((current / previous - 1) * 100)


def _monthly_metrics(rows: list[OhlcvRecord]) -> tuple[float | None, float | None, bool | None]:
    closes = _period_closes(rows, "month")
    monthly_close = closes[-1] if closes else None
    if len(closes) < HTF_MONTHLY_MA_MONTHS:
        return monthly_close, None, None
    ma12 = mean(closes[-HTF_MONTHLY_MA_MONTHS:])
    return monthly_close, _round(ma12), monthly_close > ma12


def _weekly_trend_state(rows: list[OhlcvRecord]) -> str | None:
    closes = _period_closes(rows, "week")
    if len(closes) < HTF_WEEKLY_SLOW_MA_WEEKS:
        return None
    ma10 = mean(closes[-HTF_WEEKLY_FAST_MA_WEEKS:])
    ma20 = mean(closes[-HTF_WEEKLY_SLOW_MA_WEEKS:])
    comparison_offset = 4
    required = HTF_WEEKLY_FAST_MA_WEEKS + comparison_offset
    prior_ma10 = (
        mean(closes[-required:-comparison_offset])
        if len(closes) >= max(HTF_WEEKLY_SLOW_MA_WEEKS, required)
        else None
    )
    if closes[-1] > ma10 > ma20 and prior_ma10 is not None and ma10 > prior_ma10:
        return "uptrend"
    if closes[-1] < ma10 < ma20 and prior_ma10 is not None and ma10 < prior_ma10:
        return "downtrend"
    return "neutral"


def _long_term_ma_state(
    close: float | None,
    ma50: float | None,
    ma50_slope: float | None,
) -> str | None:
    if close is None or ma50 is None or ma50_slope is None:
        return None
    if close > ma50 and ma50_slope > 0:
        return "rising"
    if close < ma50 and ma50_slope < 0:
        return "falling"
    return "neutral"


def _period_closes(rows: list[OhlcvRecord], period: str) -> list[float]:
    closes: dict[tuple[int, int], float] = {}
    for row in rows:
        parsed = date.fromisoformat(row.date)
        key = (parsed.year, parsed.month) if period == "month" else (parsed.isocalendar().year, parsed.isocalendar().week)
        closes[key] = row.close
    return list(closes.values())


def _daily_trigger_state(
    current: OhlcvRecord,
    flag_peak_price: float | None,
    distance_to_ma10_pct: float | None,
) -> str | None:
    if flag_peak_price is None or flag_peak_price <= 0 or current.close is None:
        return None
    trigger_distance = (current.close / flag_peak_price - 1) * 100
    if current.high > flag_peak_price and current.close < flag_peak_price:
        return "failed_breakout"
    if (
        trigger_distance > HTF_MAX_EXTENSION_FROM_TRIGGER_PCT
        or distance_to_ma10_pct is not None
        and distance_to_ma10_pct > HTF_MAX_DISTANCE_TO_MA10_PCT
    ):
        return "extended"
    if current.close >= flag_peak_price:
        return "breakout_confirmed"
    if trigger_distance >= -HTF_NEAR_TRIGGER_PCT:
        return "near_trigger"
    return "inside_flag"


def _structure_score(values: dict[str, Any]) -> int:
    score = 0
    prior_move = max(
        value
        for value in (values["prior_move_pct_20d"], values["prior_move_pct_60d"])
        if value is not None
    ) if any(value is not None for value in (values["prior_move_pct_20d"], values["prior_move_pct_60d"])) else None
    if prior_move is not None and prior_move >= HTF_PRIOR_MOVE_MIN_PCT:
        score += HTF_STRUCTURE_SCORE_WEIGHTS["prior_move"]
    elif prior_move is not None and prior_move >= HTF_PRIOR_MOVE_MIN_PCT * 0.6:
        score += 15
    depth = values["flag_depth_pct"]
    if depth is not None and depth <= 15:
        score += HTF_STRUCTURE_SCORE_WEIGHTS["flag_depth"]
    elif depth is not None and depth <= HTF_MAX_FLAG_DEPTH_PCT:
        score += 10
    duration = values["flag_duration_days"] or 0
    higher_lows = values["higher_lows_count"]
    if higher_lows is not None and duration > 1 and higher_lows / (duration - 1) >= HTF_MIN_HIGHER_LOWS_RATIO:
        score += HTF_STRUCTURE_SCORE_WEIGHTS["higher_lows"]
    if _le(values["range_contraction_ratio"], HTF_MAX_RANGE_CONTRACTION_RATIO):
        score += HTF_STRUCTURE_SCORE_WEIGHTS["range_contraction"]
    if _le(values["volume_contraction_ratio"], HTF_MAX_VOLUME_CONTRACTION_RATIO):
        score += HTF_STRUCTURE_SCORE_WEIGHTS["volume_contraction"]
    if _gt(values["ma10_slope"], 0) and _gt(values["ma20_slope"], 0):
        score += HTF_STRUCTURE_SCORE_WEIGHTS["ma_support"]
    if (
        values["distance_to_52w_high_pct"] is not None
        and values["distance_to_52w_high_pct"] >= -HTF_MAX_DISTANCE_TO_52W_HIGH_PCT
    ):
        score += HTF_STRUCTURE_SCORE_WEIGHTS["high_proximity"]
    if values["monthly_above_ma12"] is True:
        score += 5
    if values["weekly_trend_state"] == "uptrend":
        score += 5
    return min(100, score)


def _rejection_reasons(values: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    prior_move = max(
        value
        for value in (values["prior_move_pct_20d"], values["prior_move_pct_60d"])
        if value is not None
    ) if any(value is not None for value in (values["prior_move_pct_20d"], values["prior_move_pct_60d"])) else None
    duration = values["flag_duration_days"]
    if prior_move is not None and prior_move < HTF_PRIOR_MOVE_MIN_PCT:
        reasons.append("prior_move_below_threshold")
    if duration is not None and duration < HTF_FLAG_MIN_DAYS:
        reasons.append("flag_duration_too_short")
    if duration is not None and duration > HTF_FLAG_MAX_DAYS:
        reasons.append("flag_duration_too_long")
    if _gt(values["flag_depth_pct"], HTF_MAX_FLAG_DEPTH_PCT):
        reasons.append("flag_depth_exceeds_threshold")
    if _gt(values["range_contraction_ratio"], HTF_MAX_RANGE_CONTRACTION_RATIO):
        reasons.append("range_not_contracting")
    if _gt(values["volume_contraction_ratio"], HTF_MAX_VOLUME_CONTRACTION_RATIO):
        reasons.append("volume_not_contracting")
    if duration and duration > 1 and values["higher_lows_count"] is not None:
        if values["higher_lows_count"] / (duration - 1) < HTF_MIN_HIGHER_LOWS_RATIO:
            reasons.append("higher_lows_insufficient")
    if not _gt(values["ma10_slope"], 0):
        reasons.append("ma10_not_rising")
    if not _gt(values["ma20_slope"], 0):
        reasons.append("ma20_not_rising")
    if values["monthly_above_ma12"] is False:
        reasons.append("monthly_below_ma12")
    if values["weekly_trend_state"] in {"neutral", "downtrend"}:
        reasons.append(f"weekly_trend_{values['weekly_trend_state']}")
    return reasons


def _structure_status(
    values: dict[str, Any],
    rejection_reasons: list[str],
    missing_reason: dict[str, str],
    score: int,
) -> str:
    critical_fields = {
        "prior_move_pct_60d",
        "distance_to_52w_high_pct",
        "flag_duration_days",
        "flag_depth_pct",
        "range_contraction_ratio",
        "volume_contraction_ratio",
        "ma10_slope",
        "ma20_slope",
        "ma50_slope",
        "monthly_above_ma12",
        "weekly_trend_state",
        "long_term_ma_state",
        "daily_trigger_state",
    }
    if any(field in missing_reason for field in critical_fields):
        return "insufficient_data"
    if values["daily_trigger_state"] == "failed_breakout":
        return "failed_breakout"
    if values["daily_trigger_state"] == "extended":
        return "extended"
    if "flag_depth_exceeds_threshold" in rejection_reasons:
        return "too_deep"
    if "flag_duration_too_short" in rejection_reasons or "prior_move_below_threshold" in rejection_reasons:
        return "developing"
    loose_reasons = {
        "flag_duration_too_long",
        "range_not_contracting",
        "volume_not_contracting",
        "higher_lows_insufficient",
    }
    if loose_reasons.intersection(rejection_reasons):
        return "too_loose"
    return "valid_htf" if score >= HTF_VALID_SCORE_MIN else "developing"


def _insufficient_payload(reason: str, excluded_outlier_dates: list[str]) -> dict[str, Any]:
    missing = {field: reason for field in HTF_OUTPUT_FIELDS if field not in {"htf_structure_status", "htf_rejection_reasons"}}
    return {
        **{field: None for field in HTF_OUTPUT_FIELDS},
        "htf_structure_score": None,
        "htf_structure_status": "insufficient_data",
        "htf_rejection_reasons": [reason],
        "htf_missing_reason": missing,
        "htf_structure_basis": {
            "informational_only": True,
            "affects_grading_policy_v1": False,
        },
        "htf_data_quality": {
            "excluded_isolated_price_outlier_dates": excluded_outlier_dates,
            "isolated_price_outlier_threshold_pct": HTF_ISOLATED_PRICE_OUTLIER_PCT,
        },
    }


def _valid_rows_through_date(
    history: list[OhlcvRecord],
    current: OhlcvRecord,
) -> tuple[list[OhlcvRecord], list[str]]:
    if not _valid_row(current):
        return [], []
    by_date: dict[str, OhlcvRecord] = {}
    for row in [*history, current]:
        if row.date <= current.date and _valid_row(row):
            by_date[row.date] = row
    rows = [by_date[day] for day in sorted(by_date)]
    excluded_dates: list[str] = []
    filtered: list[OhlcvRecord] = []
    for index, row in enumerate(rows):
        if 0 < index < len(rows) - 1 and _is_isolated_price_outlier(rows[index - 1], row, rows[index + 1]):
            excluded_dates.append(row.date)
            continue
        filtered.append(row)
    return filtered, excluded_dates


def _is_isolated_price_outlier(
    previous: OhlcvRecord,
    current: OhlcvRecord,
    following: OhlcvRecord,
) -> bool:
    current_vs_previous = abs(current.close / previous.close - 1) * 100
    current_vs_following = abs(current.close / following.close - 1) * 100
    previous_vs_following = abs(following.close / previous.close - 1) * 100
    return bool(
        current_vs_previous > HTF_ISOLATED_PRICE_OUTLIER_PCT
        and current_vs_following > HTF_ISOLATED_PRICE_OUTLIER_PCT
        and previous_vs_following <= HTF_ISOLATED_PRICE_OUTLIER_PCT
    )


def _valid_row(row: OhlcvRecord) -> bool:
    prices = (row.open, row.high, row.low, row.close)
    return bool(
        all(value is not None and value > 0 for value in prices)
        and row.high >= row.low
        and row.volume is not None
        and row.volume > 0
    )


def _daily_range_pct(row: OhlcvRecord) -> float:
    return (row.high - row.low) / row.close * 100


def _relative_pct(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference <= 0:
        return None
    return _round((value / reference - 1) * 100)


def _gt(value: float | None, threshold: float) -> bool:
    return value is not None and value > threshold


def _le(value: float | None, threshold: float) -> bool:
    return value is not None and value <= threshold


def _round(value: float) -> float:
    return round(value, 4)
