from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .models import MopsEventRecord, OhlcvRecord


POLICY_RELATIVE_PATH = Path("data/chatgpt/episodic-pivot-policy-v1.json")
EP_OUTPUT_FIELDS = [
    "gap_pct",
    "open_vs_prior_close_pct",
    "daily_volume_ratio",
    "catalyst_type",
    "catalyst_date",
    "catalyst_source",
    "catalyst_surprise_score",
    "revenue_growth_yoy",
    "eps_growth_yoy",
    "prior_3m_extension_pct",
    "prior_6m_extension_pct",
    "volume_first_15m_ratio",
    "volume_first_30m_ratio",
    "opening_range_high",
    "opening_range_low",
    "ep_quality_score",
    "ep_status",
    "ep_rejection_reasons",
]
OPTIONAL_UNAVAILABLE_FIELDS = {
    "catalyst_surprise_score": "directional_event_surprise_not_available",
    "revenue_growth_yoy": "verified_structured_revenue_growth_not_available",
    "eps_growth_yoy": "verified_structured_eps_growth_not_available",
    "volume_first_15m_ratio": "reliable_intraday_data_not_available",
    "volume_first_30m_ratio": "reliable_intraday_data_not_available",
    "opening_range_high": "reliable_intraday_data_not_available",
    "opening_range_low": "reliable_intraday_data_not_available",
}


def load_episodic_pivot_policy(root: Path | str = ".") -> dict[str, Any]:
    with (Path(root) / POLICY_RELATIVE_PATH).open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_episodic_pivot_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_sections = {
        "policy_id",
        "version",
        "schema_version",
        "status",
        "parameters",
        "scoring",
        "event_interpretation",
        "intraday_data_policy",
        "mops_date_policy",
        "statuses",
        "required_output_fields",
        "validation_rules",
    }
    missing_sections = sorted(required_sections - policy.keys())
    if missing_sections:
        errors.append("missing_sections:" + ",".join(missing_sections))

    scoring = policy.get("scoring", {})
    weights = scoring.get("weights", {})
    if sum(weights.values()) != scoring.get("weights_must_sum_to"):
        errors.append(f"invalid_weight_total:{sum(weights.values())}")
    if scoring.get("breakout_score_reuse_forbidden") is not True:
        errors.append("breakout_score_reuse_must_be_forbidden")

    parameters = policy.get("parameters", {})
    positive_parameters = [
        "average_volume_window_days",
        "catalyst_lookback_calendar_days",
        "minimum_gap_pct",
        "minimum_repricing_pct",
        "minimum_close_location_pct",
        "minimum_daily_volume_ratio",
        "maximum_prior_3m_extension_pct",
        "maximum_prior_6m_extension_pct",
        "terminal_gap_prior_3m_extension_pct",
        "terminal_gap_minimum_gap_pct",
        "valid_ep_score_minimum",
    ]
    for field in positive_parameters:
        if not _is_number(parameters.get(field)) or parameters[field] <= 0:
            errors.append(f"invalid_parameter:{field}")
    windows = parameters.get("prior_extension_windows", {})
    if windows.get("3m") != 63 or windows.get("6m") != 126:
        errors.append("prior_extension_windows_invalid")
    if (
        parameters.get("minimum_required_extension_window") != "3m"
        or parameters.get("preferred_extension_window") != "6m"
    ):
        errors.append("extension_window_policy_invalid")
    latest_time = parameters.get("latest_same_day_catalyst_time")
    if (
        not isinstance(latest_time, str)
        or len(latest_time) != 5
        or latest_time[2] != ":"
    ):
        errors.append("latest_same_day_catalyst_time_invalid")

    interpretation = policy.get("event_interpretation", {})
    if (
        interpretation.get("event_existence_is_separate_from_direction") is not True
        or interpretation.get("title_sentiment_inference_allowed") is not False
        or interpretation.get("missing_surprise_must_remain_null") is not True
    ):
        errors.append("event_interpretation_policy_invalid")

    intraday = policy.get("intraday_data_policy", {})
    expected_intraday = {
        "volume_first_15m_ratio",
        "volume_first_30m_ratio",
        "opening_range_high",
        "opening_range_low",
    }
    if (
        intraday.get("available") is not False
        or set(intraday.get("fields_must_remain_null", [])) != expected_intraday
    ):
        errors.append("intraday_null_policy_invalid")

    date_policy = policy.get("mops_date_policy", {})
    if (
        date_policy.get("analysis_date_must_match_data_date") is not True
        or set(date_policy.get("accepted_date_validation", []))
        != {"matched", "query_confirmed_empty"}
        or set(date_policy.get("accepted_statuses", []))
        != {"success", "empty_but_valid"}
        or date_policy.get("future_events_forbidden") is not True
    ):
        errors.append("mops_date_policy_invalid")

    if set(policy.get("statuses", [])) != {
        "valid_ep",
        "rejected",
        "insufficient_data",
    }:
        errors.append("statuses_invalid")
    missing_outputs = set(EP_OUTPUT_FIELDS) - set(
        policy.get("required_output_fields", [])
    )
    if missing_outputs:
        errors.append("missing_output_fields:" + ",".join(sorted(missing_outputs)))

    rules = policy.get("validation_rules", {})
    if not str(policy.get("version", "")).startswith(
        str(rules.get("required_policy_version_prefix", ""))
    ):
        errors.append("policy_version_invalid")
    if policy.get("schema_version") != rules.get("required_schema_version"):
        errors.append("schema_version_invalid")
    if policy.get("status") != rules.get("required_status"):
        errors.append("policy_status_invalid")
    if rules.get("real_trading_forbidden") is not True:
        errors.append("real_trading_must_be_forbidden")
    return errors


def calculate_episodic_pivot(
    current: OhlcvRecord,
    history: list[OhlcvRecord],
    mops_events: list[MopsEventRecord] | None = None,
    mops_context: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_policy = policy or load_episodic_pivot_policy()
    policy_errors = validate_episodic_pivot_policy(active_policy)
    if policy_errors:
        raise ValueError("invalid episodic pivot policy: " + ",".join(policy_errors))

    parameters = active_policy["parameters"]
    analysis_date = _parse_date(current.date)
    valid_history = _valid_history_before(history, analysis_date)
    prior_close = valid_history[-1].close if valid_history else None
    avg_window = int(parameters["average_volume_window_days"])
    average_volume = (
        sum(row.volume for row in valid_history[-avg_window:]) / avg_window
        if len(valid_history) >= avg_window
        else None
    )
    gap_pct = _relative_pct(current.open, prior_close)
    close_location_pct = _close_location_pct(current)
    daily_volume_ratio = (
        _round(current.volume / average_volume)
        if current.volume is not None
        and current.volume > 0
        and average_volume is not None
        and average_volume > 0
        else None
    )
    extension_windows = parameters["prior_extension_windows"]
    prior_3m = _prior_extension(valid_history, int(extension_windows["3m"]))
    prior_6m = _prior_extension(valid_history, int(extension_windows["6m"]))

    context = dict(mops_context or {})
    mops_date = context.get("data_date")
    date_validation = context.get("date_validation")
    mops_status = context.get("status")
    mops_date_matches = bool(
        analysis_date
        and context.get("requested_date") == analysis_date.isoformat()
        and mops_date == analysis_date.isoformat()
        and date_validation
        in active_policy["mops_date_policy"]["accepted_date_validation"]
        and mops_status in active_policy["mops_date_policy"]["accepted_statuses"]
    )
    selected_event = _select_verified_event(
        mops_events or [],
        analysis_date,
        int(parameters["catalyst_lookback_calendar_days"]),
        str(parameters["latest_same_day_catalyst_time"]),
    )
    catalyst_type = (
        selected_event.category or "material_information"
        if selected_event
        else None
    )
    catalyst_source = selected_event.source if selected_event else None
    catalyst_date = selected_event.date if selected_event else None

    missing_reason = dict(OPTIONAL_UNAVAILABLE_FIELDS)
    required_missing: list[str] = []
    if analysis_date is None:
        required_missing.append("analysis_date_invalid")
    if prior_close is None:
        required_missing.append("prior_close_missing")
        missing_reason["gap_pct"] = "prior_close_missing"
        missing_reason["open_vs_prior_close_pct"] = "prior_close_missing"
    if average_volume is None:
        required_missing.append(
            f"insufficient_volume_history:{len(valid_history)}/{avg_window}"
        )
        missing_reason["daily_volume_ratio"] = (
            f"insufficient_valid_trading_days:{len(valid_history)}/{avg_window}"
        )
    if prior_3m is None:
        required_missing.append("prior_3m_extension_missing")
        missing_reason["prior_3m_extension_pct"] = (
            f"insufficient_valid_trading_days:{len(valid_history)}/"
            f"{int(extension_windows['3m']) + 1}"
        )
    if prior_6m is None:
        missing_reason["prior_6m_extension_pct"] = (
            f"insufficient_valid_trading_days:{len(valid_history)}/"
            f"{int(extension_windows['6m']) + 1}"
        )
    if not mops_date_matches:
        required_missing.append("mops_data_date_not_verified_for_analysis_date")
    if current.open is None or current.open <= 0:
        required_missing.append("current_open_missing_or_invalid")
    if current.close is None or current.close <= 0:
        required_missing.append("current_close_missing_or_invalid")
    if (
        current.high is None
        or current.low is None
        or current.high < current.low
        or close_location_pct is None
    ):
        required_missing.append("current_range_missing_or_invalid")
    if current.volume is None or current.volume <= 0:
        required_missing.append("current_volume_missing_or_invalid")

    score_breakdown = _score_breakdown(
        current,
        gap_pct,
        close_location_pct,
        daily_volume_ratio,
        prior_3m,
        prior_6m,
        selected_event,
        analysis_date,
        parameters,
        active_policy["scoring"]["weights"],
    )
    rejection_reasons = _rejection_reasons(
        current,
        gap_pct,
        close_location_pct,
        daily_volume_ratio,
        prior_3m,
        prior_6m,
        selected_event,
        parameters,
    )
    if required_missing:
        status = "insufficient_data"
        quality_score = None
        rejection_reasons = list(dict.fromkeys(required_missing + rejection_reasons))
    else:
        quality_score = sum(score_breakdown.values())
        status = (
            "valid_ep"
            if not rejection_reasons
            and quality_score >= parameters["valid_ep_score_minimum"]
            else "rejected"
        )

    return {
        "gap_pct": gap_pct,
        "open_vs_prior_close_pct": gap_pct,
        "daily_volume_ratio": daily_volume_ratio,
        "ep_close_location_pct": close_location_pct,
        "catalyst_type": catalyst_type,
        "catalyst_date": catalyst_date,
        "catalyst_source": catalyst_source,
        "catalyst_surprise_score": None,
        "revenue_growth_yoy": None,
        "eps_growth_yoy": None,
        "prior_3m_extension_pct": prior_3m,
        "prior_6m_extension_pct": prior_6m,
        "volume_first_15m_ratio": None,
        "volume_first_30m_ratio": None,
        "opening_range_high": None,
        "opening_range_low": None,
        "ep_quality_score": quality_score,
        "ep_status": status,
        "ep_rejection_reasons": rejection_reasons,
        "ep_missing_reason": missing_reason,
        "ep_score_breakdown": score_breakdown if quality_score is not None else {},
        "ep_policy_version": active_policy["version"],
        "ep_scoring_model": "episodic_pivot_v1",
        "catalyst_event_verified": bool(selected_event and mops_date_matches),
        "catalyst_direction": None,
        "catalyst_direction_interpreted": False,
        "mops_data_date": mops_date,
        "mops_date_validation": date_validation,
        "mops_data_date_matches_analysis_date": mops_date_matches,
        "ep_basis": {
            "analysis_date": current.date,
            "prior_close": prior_close,
            "average_volume_window_days": avg_window,
            "catalyst_lookback_calendar_days": parameters[
                "catalyst_lookback_calendar_days"
            ],
            "latest_same_day_catalyst_time": parameters[
                "latest_same_day_catalyst_time"
            ],
            "future_events_forbidden": True,
            "breakout_score_reused": False,
            "event_direction_inferred": False,
            "real_trading": False,
        },
    }


def build_episodic_pivot_coverage(
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    eligible = [item for item in candidates if item.get("scan_eligible")]
    statuses: dict[str, int] = defaultdict(int)
    for candidate in eligible:
        statuses[str(candidate.get("ep_status") or "missing")] += 1
    complete = sum(
        1 for candidate in eligible if candidate.get("ep_status") != "insufficient_data"
    )
    return {
        "eligible_symbols": len(eligible),
        "complete_symbols": complete,
        "incomplete_symbols": len(eligible) - complete,
        "coverage_pct": _round(complete / len(eligible) * 100)
        if eligible
        else 0.0,
        "status_counts": dict(sorted(statuses.items())),
        "independent_scoring": True,
        "breakout_score_reused": False,
    }


def _valid_history_before(
    history: list[OhlcvRecord], analysis_date: date | None
) -> list[OhlcvRecord]:
    if analysis_date is None:
        return []
    by_date: dict[str, OhlcvRecord] = {}
    for row in history:
        row_date = _parse_date(row.date)
        if (
            row_date is None
            or row_date >= analysis_date
            or row.open is None
            or row.high is None
            or row.low is None
            or row.close is None
            or row.volume is None
            or min(row.open, row.high, row.low, row.close) <= 0
            or row.volume <= 0
            or row.high < row.low
        ):
            continue
        by_date[row.date] = row
    return [by_date[key] for key in sorted(by_date)]


def _select_verified_event(
    events: list[MopsEventRecord],
    analysis_date: date | None,
    lookback_days: int,
    latest_same_day_time: str,
) -> MopsEventRecord | None:
    if analysis_date is None:
        return None
    start_date = analysis_date - timedelta(days=lookback_days)
    unique: dict[tuple[str, str, str, str], MopsEventRecord] = {}
    for event in events:
        event_date = _parse_date(event.date)
        if (
            event_date is None
            or event_date > analysis_date
            or event_date < start_date
            or not event.source.upper().startswith("MOPS")
            or (
                event_date == analysis_date
                and event.time is not None
                and _time_is_after(event.time, latest_same_day_time)
            )
        ):
            continue
        key = (event.date, event.time or "", event.symbol, event.title)
        unique[key] = event
    if not unique:
        return None
    return max(
        unique.values(),
        key=lambda event: (event.date, event.time or "", event.title),
    )


def _prior_extension(history: list[OhlcvRecord], window: int) -> float | None:
    if len(history) < window + 1:
        return None
    start_close = history[-window - 1].close
    end_close = history[-1].close
    if start_close is None or end_close is None or start_close <= 0:
        return None
    return _round((end_close / start_close - 1) * 100)


def _score_breakdown(
    current: OhlcvRecord,
    gap_pct: float | None,
    close_location_pct: float | None,
    volume_ratio: float | None,
    prior_3m: float | None,
    prior_6m: float | None,
    event: MopsEventRecord | None,
    analysis_date: date | None,
    parameters: dict[str, Any],
    weights: dict[str, int],
) -> dict[str, int]:
    repricing = bool(
        (
            _ge(gap_pct, parameters["minimum_gap_pct"])
            or _ge(current.change_pct, parameters["minimum_repricing_pct"])
        )
        and _ge(
            close_location_pct,
            parameters["minimum_close_location_pct"],
        )
    )
    event_date = _parse_date(event.date) if event else None
    timely = bool(
        analysis_date
        and event_date
        and analysis_date - timedelta(
            days=int(parameters["catalyst_lookback_calendar_days"])
        )
        <= event_date
        <= analysis_date
    )
    extension_ok = bool(
        prior_3m is not None
        and prior_3m <= parameters["maximum_prior_3m_extension_pct"]
        and (
            prior_6m is None
            or prior_6m <= parameters["maximum_prior_6m_extension_pct"]
        )
        and not _is_terminal_gap(gap_pct, prior_3m, parameters)
    )
    return {
        "verified_catalyst": weights["verified_catalyst"] if event else 0,
        "repricing": weights["repricing"] if repricing else 0,
        "abnormal_volume": weights["abnormal_volume"]
        if _ge(volume_ratio, parameters["minimum_daily_volume_ratio"])
        else 0,
        "catalyst_timing": weights["catalyst_timing"] if timely else 0,
        "extension_quality": weights["extension_quality"] if extension_ok else 0,
    }


def _rejection_reasons(
    current: OhlcvRecord,
    gap_pct: float | None,
    close_location_pct: float | None,
    volume_ratio: float | None,
    prior_3m: float | None,
    prior_6m: float | None,
    event: MopsEventRecord | None,
    parameters: dict[str, Any],
) -> list[str]:
    reasons: list[str] = []
    if event is None:
        reasons.append("no_verified_mops_catalyst_in_allowed_window")
    if not (
        _ge(gap_pct, parameters["minimum_gap_pct"])
        or _ge(current.change_pct, parameters["minimum_repricing_pct"])
    ):
        reasons.append("no_material_gap_or_repricing")
    if not _ge(
        close_location_pct,
        parameters["minimum_close_location_pct"],
    ):
        reasons.append("weak_close_after_repricing")
    if not _ge(volume_ratio, parameters["minimum_daily_volume_ratio"]):
        reasons.append("daily_volume_ratio_below_threshold")
    if (
        prior_3m is not None
        and prior_3m > parameters["maximum_prior_3m_extension_pct"]
    ):
        reasons.append("prior_3m_overextended")
    if (
        prior_6m is not None
        and prior_6m > parameters["maximum_prior_6m_extension_pct"]
    ):
        reasons.append("prior_6m_overextended")
    if _is_terminal_gap(gap_pct, prior_3m, parameters):
        reasons.append("possible_terminal_gap_after_extended_run")
    return reasons


def _is_terminal_gap(
    gap_pct: float | None,
    prior_3m: float | None,
    parameters: dict[str, Any],
) -> bool:
    return bool(
        _ge(
            prior_3m,
            parameters["terminal_gap_prior_3m_extension_pct"],
        )
        and _ge(gap_pct, parameters["terminal_gap_minimum_gap_pct"])
    )


def _relative_pct(value: float | None, reference: float | None) -> float | None:
    if value is None or reference is None or reference <= 0:
        return None
    return _round((value / reference - 1) * 100)


def _close_location_pct(current: OhlcvRecord) -> float | None:
    if (
        current.high is None
        or current.low is None
        or current.close is None
        or current.high <= current.low
    ):
        return None
    return _round(
        (current.close - current.low) / (current.high - current.low) * 100
    )


def _ge(value: float | None, threshold: float) -> bool:
    return value is not None and value >= threshold


def _round(value: float) -> float:
    return round(value, 4)


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _time_is_after(value: str, cutoff: str) -> bool:
    parsed_value = _parse_hour_minute(value)
    parsed_cutoff = _parse_hour_minute(cutoff)
    if parsed_value is None or parsed_cutoff is None:
        return True
    return parsed_value > parsed_cutoff


def _parse_hour_minute(value: str) -> tuple[int, int] | None:
    try:
        hour_text, minute_text = value.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (AttributeError, TypeError, ValueError):
        return None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour, minute


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )
