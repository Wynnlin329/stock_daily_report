from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


POLICY_RELATIVE_PATH = Path("data/chatgpt/qullamaggie-grading-policy-v1.json")
QUALITY_GRADES = ["A", "A-", "B", "C"]


def load_grading_policy(root: Path | str = ".") -> dict[str, Any]:
    path = Path(root) / POLICY_RELATIVE_PATH
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_grading_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_sections = {
        "policy_id",
        "version",
        "schema_version",
        "status",
        "effective_date",
        "methodology",
        "score_name",
        "score_range",
        "source_of_truth",
        "supported_grades",
        "field_definitions",
        "required_fields",
        "formulas",
        "hard_gates",
        "scoring",
        "grade_thresholds",
        "grade_caps",
        "missing_data_policy",
        "market_gate_policy",
        "output_contract",
        "validation_rules",
    }
    missing_sections = sorted(required_sections - policy.keys())
    if missing_sections:
        errors.append("missing_sections:" + ",".join(missing_sections))

    weights = policy.get("scoring", {}).get("weights", {})
    expected_total = policy.get("validation_rules", {}).get("weights_must_sum_to")
    if sum(weights.values()) != expected_total:
        errors.append(f"invalid_weight_total:{sum(weights.values())}")

    thresholds = policy.get("grade_thresholds", {}).get("ordered_descending", [])
    threshold_scores = [item.get("minimum_score") for item in thresholds]
    if any(not _is_number(value) for value in threshold_scores):
        errors.append("invalid_grade_threshold_type")
    elif threshold_scores != sorted(threshold_scores, reverse=True) or len(threshold_scores) != len(set(threshold_scores)):
        errors.append("grade_thresholds_not_strictly_descending")

    supported_grades = set(policy.get("supported_grades", []))
    for cap in policy.get("grade_caps", []):
        if cap.get("maximum_grade") not in supported_grades:
            errors.append(f"invalid_cap_grade:{cap.get('id')}")

    if policy.get("input_contract", {}).get("existing_scan_score_is_not_grade_score") is not True:
        errors.append("scan_score_separation_missing")
    if policy.get("missing_data_policy", {}).get("missing_value_is_zero") is not False:
        errors.append("null_zero_policy_invalid")
    return errors


def grade_symbol(
    symbol_payload: dict[str, Any],
    candidate_payload: dict[str, Any] | None = None,
    market_regime: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_policy = policy or load_grading_policy()
    candidate = candidate_payload or {}
    values = _resolve_fields(active_policy, symbol_payload, candidate)
    result = _base_result(active_policy, values.get("setup_type"), market_regime)

    if values.get("scan_eligible") is False:
        result["final_grade"] = "Eliminated"
        result["hard_gate_results"] = [{"id": "scan_eligible_false", "triggered": True}]
        result["reasons"] = ["scan_eligible=false，不進入品質評分。"]
        return _apply_market_gate(result, active_policy)

    missing_fields, type_errors = _required_field_errors(active_policy, values)
    if missing_fields:
        result["missing_fields"] = missing_fields
        result["data_errors"] = type_errors
        result["hard_gate_results"] = [{"id": "required_data_missing_or_invalid", "triggered": True}]
        result["reasons"] = ["必要欄位缺少或型別無效，依 policy 保持 Ungraded。"]
        return _apply_market_gate(result, active_policy)

    if values["ohlcv_complete"] is not True:
        result["data_errors"] = ["ohlcv_incomplete"]
        result["hard_gate_results"] = [{"id": "ohlcv_incomplete", "triggered": True}]
        result["reasons"] = ["OHLCV 不完整，無法進行品質評分。"]
        return _apply_market_gate(result, active_policy)

    valid_setups = active_policy["validation_rules"]["valid_setup_types"]
    if values["setup_type"] == "insufficient_data" or values["setup_type"] not in valid_setups:
        result["hard_gate_results"] = [{"id": "setup_insufficient_or_unknown", "triggered": True}]
        if values["setup_type"] not in valid_setups:
            result["data_errors"] = [f"unknown_setup_type:{values['setup_type']}"]
        result["reasons"] = ["Setup 資料不足或類型未知，依 policy 保持 Ungraded。"]
        return _apply_market_gate(result, active_policy)

    entry_reference = _entry_reference(values)
    derived_errors = _derived_data_errors(values, entry_reference)
    if derived_errors:
        result["entry_reference"] = _round_price(entry_reference)
        result["data_errors"] = derived_errors
        result["hard_gate_results"] = [{"id": "derived_data_invalid", "triggered": True}]
        result["reasons"] = ["衍生欄位無效，依 policy 保持 Ungraded。"]
        return _apply_market_gate(result, active_policy)

    pivot_distance_pct = (values["pivot_price"] - values["close"]) / values["pivot_price"] * 100
    stop_risk_pct = (entry_reference - values["stop_reference"]) / entry_reference * 100
    avg_turnover_20d_est = values["avg_volume_20d"] * values["close"]
    metrics = {
        **values,
        "entry_reference": entry_reference,
        "pivot_distance_pct": pivot_distance_pct,
        "stop_risk_pct": stop_risk_pct,
        "avg_turnover_20d_est": avg_turnover_20d_est,
    }

    component_scores = _component_scores(active_policy, metrics)
    raw_score = sum(component_scores.values())
    preliminary_grade = _preliminary_grade(active_policy, raw_score)
    applied_caps = _applied_caps(active_policy, metrics)
    minor_defects, major_defects = _defects(active_policy, metrics, component_scores)
    upgrade_requirements = _upgrade_requirements(
        active_policy, component_scores, minor_defects, major_defects
    )
    final_grade = _final_grade(
        active_policy,
        metrics,
        raw_score,
        preliminary_grade,
        applied_caps,
        minor_defects,
        major_defects,
        upgrade_requirements,
    )

    result.update(
        {
            "grade_score_v1": raw_score,
            "component_scores": component_scores,
            "preliminary_grade": preliminary_grade,
            "final_grade": final_grade,
            "entry_reference": _round_price(entry_reference),
            "pivot_distance_pct": round(pivot_distance_pct, 2),
            "stop_risk_pct": round(stop_risk_pct, 2),
            "avg_turnover_20d_est": round(avg_turnover_20d_est, 2),
            "hard_gate_results": [
                {"id": gate_id, "triggered": False}
                for gate_id in (
                    "scan_eligible_false",
                    "required_data_missing_or_invalid",
                    "ohlcv_incomplete",
                    "setup_insufficient_or_unknown",
                    "derived_data_invalid",
                )
            ],
            "applied_caps": applied_caps,
            "major_defects": major_defects,
            "minor_defects": minor_defects,
            "reasons": [
                f"raw_score={raw_score} 對應 preliminary_grade={preliminary_grade}。",
                f"套用必要條件與 grade caps 後 final_grade={final_grade}。",
            ],
            "upgrade_requirements": upgrade_requirements if final_grade == "B" else [],
        }
    )
    return _apply_market_gate(result, active_policy)


def _base_result(policy: dict[str, Any], setup_type: Any, market_regime: str | None) -> dict[str, Any]:
    return {
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "grade_score_v1": None,
        "component_scores": {},
        "preliminary_grade": None,
        "final_grade": "Ungraded",
        "setup_type": setup_type,
        "entry_reference": None,
        "pivot_distance_pct": None,
        "stop_risk_pct": None,
        "avg_turnover_20d_est": None,
        "hard_gate_results": [],
        "applied_caps": [],
        "major_defects": [],
        "minor_defects": [],
        "reasons": [],
        "upgrade_requirements": [],
        "missing_fields": [],
        "data_errors": [],
        "market_regime": market_regime or "insufficient_data",
        "market_gate": "not_applicable",
        "action_status": "not_applicable",
        "block_reason": "quality_grade_unavailable",
    }


def _resolve_fields(
    policy: dict[str, Any], symbol_payload: dict[str, Any], candidate_payload: dict[str, Any]
) -> dict[str, Any]:
    sources = {"symbol_payload": symbol_payload, "candidate_payload": candidate_payload}
    values: dict[str, Any] = {}
    for field, definition in policy["field_definitions"].items():
        values[field] = None
        for alias in definition["aliases"]:
            source_name, _, path = alias.partition(".")
            value = _nested_value(sources.get(source_name, {}), path)
            if value is not None:
                values[field] = value
                break
    return values


def _nested_value(payload: dict[str, Any], path: str) -> Any:
    value: Any = payload
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _required_field_errors(policy: dict[str, Any], values: dict[str, Any]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    errors: list[str] = []
    for field in policy["required_fields"]:
        value = values.get(field)
        expected = policy["field_definitions"][field]["type"]
        valid = value is not None
        if expected == "number":
            valid = _is_number(value)
        elif expected == "boolean":
            valid = isinstance(value, bool)
        elif expected == "string":
            valid = isinstance(value, str) and bool(value)
        elif expected == "array":
            valid = isinstance(value, list)
        if not valid:
            missing.append(field)
            if value is not None:
                errors.append(f"invalid_type:{field}")
    return missing, errors


def _entry_reference(values: dict[str, Any]) -> float:
    setup_type = values["setup_type"]
    if setup_type == "anticipation":
        return float(values["pivot_price"])
    if setup_type in {"breakout", "episodic_pivot"} and values["close"] >= values["pivot_price"]:
        return float(values["close"])
    return float(values["pivot_price"])


def _derived_data_errors(values: dict[str, Any], entry_reference: float) -> list[str]:
    errors: list[str] = []
    if values["close"] <= 0:
        errors.append("close_must_be_positive")
    for moving_average in ("ma10", "ma20", "ma50"):
        if values[moving_average] <= 0:
            errors.append(f"{moving_average}_must_be_positive")
    if values["pivot_price"] <= 0:
        errors.append("pivot_price_must_be_positive")
    if values["stop_reference"] <= 0:
        errors.append("stop_reference_must_be_positive")
    if values["avg_volume_20d"] < 0:
        errors.append("avg_volume_20d_must_be_non_negative")
    if values["volume_ratio_20d"] < 0:
        errors.append("volume_ratio_20d_must_be_non_negative")
    if not 0 <= values["relative_strength_rank"] <= 100:
        errors.append("relative_strength_rank_out_of_range")
    if entry_reference <= 0:
        errors.append("entry_reference_must_be_positive")
    if values["stop_reference"] >= entry_reference:
        errors.append("stop_reference_must_be_below_entry_reference")
    return errors


def _component_scores(policy: dict[str, Any], metrics: dict[str, Any]) -> dict[str, int]:
    components = policy["scoring"]["components"]
    trend = 0
    if metrics["close"] > metrics["ma10"] > metrics["ma20"] > metrics["ma50"]:
        trend = components["trend"][0]["score"]
    elif metrics["close"] > metrics["ma20"] > metrics["ma50"]:
        trend = components["trend"][1]["score"]
    elif metrics["close"] > metrics["ma50"]:
        trend = components["trend"][2]["score"]

    pivot_distance = metrics["pivot_distance_pct"]
    if pivot_distance >= 0:
        trigger_position = _score_upper_ranges(pivot_distance, components["trigger_position"]["below_pivot"])
    else:
        trigger_position = _score_upper_ranges(abs(pivot_distance), components["trigger_position"]["above_pivot"])

    return {
        "trend": trend,
        "relative_strength": _score_lower_ranges(metrics["relative_strength_rank"], components["relative_strength"]),
        "setup_structure": components["setup_structure"][metrics["setup_type"]],
        "trigger_position": trigger_position,
        "stop_quality": _score_upper_ranges(metrics["stop_risk_pct"], components["stop_quality"]),
        "liquidity": _score_lower_ranges(metrics["avg_turnover_20d_est"], components["liquidity"]),
        "volume_confirmation": _score_lower_ranges(metrics["volume_ratio_20d"], components["volume_confirmation"]),
    }


def _score_lower_ranges(value: float, levels: list[dict[str, Any]]) -> int:
    for level in levels:
        minimum = level["minimum"]
        maximum = level.get("maximum_exclusive")
        if value >= minimum and (maximum is None or value < maximum):
            return level["score"]
    raise ValueError(f"No scoring range for value {value}")


def _score_upper_ranges(value: float, levels: list[dict[str, Any]]) -> int:
    for level in levels:
        minimum = level.get("minimum_exclusive")
        maximum = level.get("maximum")
        if (minimum is None or value > minimum) and (maximum is None or value <= maximum):
            return level["score"]
    raise ValueError(f"No scoring range for value {value}")


def _preliminary_grade(policy: dict[str, Any], score: int) -> str:
    for threshold in policy["grade_thresholds"]["ordered_descending"]:
        if score >= threshold["minimum_score"]:
            return threshold["grade"]
    return "C"


def _applied_caps(policy: dict[str, Any], metrics: dict[str, Any]) -> list[str]:
    return [cap["id"] for cap in policy["grade_caps"] if _cap_matches(cap, metrics)]


def _cap_matches(cap: dict[str, Any], metrics: dict[str, Any]) -> bool:
    if "all" in cap:
        return all(_condition_matches(condition, metrics) for condition in cap["all"])
    return _condition_matches(cap, metrics)


def _condition_matches(condition: dict[str, Any], metrics: dict[str, Any]) -> bool:
    actual = metrics[condition["field"]]
    expected = condition["value"]
    operator = condition["operator"]
    if operator == "eq":
        return actual == expected
    if operator == "lt":
        return actual < expected
    if operator == "gt":
        return actual > expected
    raise ValueError(f"Unsupported policy operator: {operator}")


def _defects(
    policy: dict[str, Any], metrics: dict[str, Any], scores: dict[str, int]
) -> tuple[list[str], list[str]]:
    minor: list[str] = []
    major: list[str] = []
    a_rules = policy["grade_requirements"]["A"]
    a_minus_rules = policy["grade_requirements"]["A-"]
    c_cap_values = {cap["id"]: cap["value"] for cap in policy["grade_caps"] if "value" in cap}
    rs = metrics["relative_strength_rank"]
    stop = metrics["stop_risk_pct"]
    turnover = metrics["avg_turnover_20d_est"]
    distance = metrics["pivot_distance_pct"]

    if a_minus_rules["minimum_relative_strength_rank"] <= rs < a_rules["minimum_relative_strength_rank"]:
        minor.append("relative_strength_75_to_below_85")
    elif rs < a_minus_rules["minimum_relative_strength_rank"]:
        major.append(
            "relative_strength_below_60"
            if rs < c_cap_values["relative_strength_below_60_cap_c"]
            else "relative_strength_below_75"
        )
    if a_rules["maximum_stop_risk_pct"] < stop <= a_minus_rules["maximum_stop_risk_pct"]:
        minor.append("stop_risk_above_8_to_10")
    elif stop > a_minus_rules["maximum_stop_risk_pct"]:
        major.append(
            "stop_risk_over_12"
            if stop > c_cap_values["stop_risk_over_12_cap_c"]
            else "stop_risk_above_10"
        )
    if metrics["setup_type"] == "anticipation":
        if (
            a_rules["maximum_anticipation_pivot_distance_pct"]
            < distance
            <= a_minus_rules["maximum_absolute_pivot_distance_pct"]
        ):
            minor.append("anticipation_pivot_distance_above_3_to_5")
        elif distance > a_minus_rules["maximum_absolute_pivot_distance_pct"]:
            major.append("anticipation_pivot_distance_over_5")
    preferred_volume_ratio = policy["scoring"]["components"]["volume_confirmation"][0]["minimum"]
    if metrics["volume_ratio_20d"] < preferred_volume_ratio:
        minor.append("volume_ratio_below_1_5")
    if scores["trend"] < policy["scoring"]["weights"]["trend"]:
        minor.append("trend_not_fully_aligned")
    if turnover < a_rules["minimum_avg_turnover_20d_est"]:
        major.append(
            "avg_turnover_below_15m"
            if turnover < c_cap_values["avg_turnover_below_15m_cap_c"]
            else "avg_turnover_below_30m"
        )
    if metrics["setup_type"] == "failed_breakout":
        major.append("failed_breakout")
    if metrics["extended_risk"]:
        major.append("extended_risk")
    if distance < -5:
        major.append("above_pivot_over_5")
    return _unique(minor), _unique(major)


def _upgrade_requirements(
    policy: dict[str, Any],
    scores: dict[str, int],
    minor: list[str],
    major: list[str],
) -> list[str]:
    requirements = [f"resolve:{defect}" for defect in major + minor]
    if scores["trigger_position"] < policy["scoring"]["weights"]["trigger_position"]:
        requirements.append("move_within_preferred_pivot_distance")
    if scores["volume_confirmation"] < policy["scoring"]["weights"]["volume_confirmation"]:
        requirements.append("volume_ratio_20d_reach_1_5")
    if scores["trend"] < policy["scoring"]["weights"]["trend"]:
        requirements.append("restore_full_ma_alignment")
    return _unique(requirements)


def _final_grade(
    policy: dict[str, Any],
    metrics: dict[str, Any],
    score: int,
    preliminary_grade: str,
    applied_caps: list[str],
    minor_defects: list[str],
    major_defects: list[str],
    upgrade_requirements: list[str],
) -> str:
    cap_by_id = {cap["id"]: cap["maximum_grade"] for cap in policy["grade_caps"]}
    maximum_grade_index = QUALITY_GRADES.index(preliminary_grade)
    for cap_id in applied_caps:
        maximum_grade_index = max(maximum_grade_index, QUALITY_GRADES.index(cap_by_id[cap_id]))

    if maximum_grade_index <= QUALITY_GRADES.index("A") and _meets_a(policy, metrics, score, minor_defects, major_defects):
        return "A"
    if maximum_grade_index <= QUALITY_GRADES.index("A-") and _meets_a_minus(
        policy, metrics, score, minor_defects, major_defects
    ):
        return "A-"

    c_cap_present = any(cap_by_id[cap_id] == "C" for cap_id in applied_caps)
    clear_upgrade_path = not c_cap_present
    b_rules = policy["grade_requirements"]["B"]
    if (
        maximum_grade_index <= QUALITY_GRADES.index("B")
        and score >= b_rules["minimum_score"]
        and metrics["stop_risk_pct"] <= b_rules["maximum_stop_risk_pct"]
        and clear_upgrade_path
        and upgrade_requirements
    ):
        return "B"
    return "C"


def _meets_a(
    policy: dict[str, Any], metrics: dict[str, Any], score: int, minor: list[str], major: list[str]
) -> bool:
    rules = policy["grade_requirements"]["A"]
    setup_ok = metrics["setup_type"] in rules["allowed_setup_types"]
    if metrics["setup_type"] == "anticipation":
        setup_ok = setup_ok and metrics["pivot_distance_pct"] <= rules["maximum_anticipation_pivot_distance_pct"]
    above_pivot_ok = metrics["pivot_distance_pct"] >= -rules["maximum_above_pivot_pct"]
    return all(
        (
            score >= rules["minimum_score"],
            metrics["relative_strength_rank"] >= rules["minimum_relative_strength_rank"],
            metrics["stop_risk_pct"] <= rules["maximum_stop_risk_pct"],
            metrics["extended_risk"] is rules["extended_risk"],
            setup_ok,
            above_pivot_ok,
            metrics["avg_turnover_20d_est"] >= rules["minimum_avg_turnover_20d_est"],
            len(minor) <= rules["maximum_minor_defects"],
            len(major) <= rules["maximum_major_defects"],
        )
    )


def _meets_a_minus(
    policy: dict[str, Any], metrics: dict[str, Any], score: int, minor: list[str], major: list[str]
) -> bool:
    rules = policy["grade_requirements"]["A-"]
    return all(
        (
            score >= rules["minimum_score"],
            metrics["relative_strength_rank"] >= rules["minimum_relative_strength_rank"],
            metrics["stop_risk_pct"] <= rules["maximum_stop_risk_pct"],
            metrics["extended_risk"] is rules["extended_risk"],
            metrics["setup_type"] in rules["allowed_setup_types"],
            abs(metrics["pivot_distance_pct"]) <= rules["maximum_absolute_pivot_distance_pct"],
            metrics["avg_turnover_20d_est"] >= rules["minimum_avg_turnover_20d_est"],
            len(minor) <= rules["maximum_minor_defects"],
            len(major) <= rules["maximum_major_defects"],
        )
    )


def _apply_market_gate(result: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    grade = result["final_grade"]
    market_policy = policy["market_gate_policy"]
    if grade not in QUALITY_GRADES:
        gate = market_policy["non_graded"]
    else:
        regime_policy = market_policy.get(result["market_regime"], market_policy["fallback"])
        gate = regime_policy[grade]
    result.update(gate)
    return result


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _round_price(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))
