from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any


POLICY_V2_RELATIVE_PATH = Path("data/chatgpt/qullamaggie-grading-policy-v2.json")
QUALITY_GRADES = ["A", "A-", "B", "C"]


def load_grading_policy_v2(root: Path | str = ".") -> dict[str, Any]:
    with (Path(root) / POLICY_V2_RELATIVE_PATH).open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_grading_policy_v2(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_sections = {
        "policy_id",
        "version",
        "schema_version",
        "status",
        "supported_grades",
        "input_contract",
        "required_fields",
        "field_definitions",
        "parameters",
        "scoring",
        "grade_thresholds",
        "grade_caps",
        "hard_risk_checks_for_a_grades",
        "missing_data_policy",
        "market_gate_policy",
        "shadow_routing",
        "output_contract",
        "shadow_history",
        "validation_rules",
    }
    missing_sections = sorted(required_sections - policy.keys())
    if missing_sections:
        errors.append("missing_sections:" + ",".join(missing_sections))

    rules = policy.get("validation_rules", {})
    weights = policy.get("scoring", {}).get("weights", {})
    if sum(weights.values()) != rules.get("weights_must_sum_to"):
        errors.append(f"invalid_weight_total:{sum(weights.values())}")

    thresholds = policy.get("grade_thresholds", {}).get("ordered_descending", [])
    scores = [item.get("minimum_score") for item in thresholds]
    grades = [item.get("grade") for item in thresholds]
    if any(not _is_number(value) for value in scores):
        errors.append("invalid_grade_threshold_type")
    elif scores != sorted(scores, reverse=True) or len(scores) != len(set(scores)):
        errors.append("grade_thresholds_not_strictly_descending")
    if grades != QUALITY_GRADES:
        errors.append("grade_threshold_order_invalid")

    supported = set(policy.get("supported_grades", []))
    allowed_operators = set(rules.get("allowed_cap_operators", []))
    for cap in policy.get("grade_caps", []):
        if cap.get("maximum_grade") not in supported:
            errors.append(f"invalid_cap_grade:{cap.get('id')}")
        if cap.get("operator") not in allowed_operators:
            errors.append(f"invalid_cap_operator:{cap.get('id')}")
        if cap.get("field") not in policy.get("field_definitions", {}):
            errors.append(f"invalid_cap_field:{cap.get('id')}")

    definitions = policy.get("field_definitions", {})
    for field in policy.get("required_fields", []):
        if field not in definitions:
            errors.append(f"undefined_required_field:{field}")

    missing_policy = policy.get("missing_data_policy", {})
    if (
        missing_policy.get("grade") != "Ungraded"
        or missing_policy.get("score_v2_shadow", "invalid") is not None
        or missing_policy.get("missing_value_is_zero") is not False
        or missing_policy.get("imputation_allowed") is not False
    ):
        errors.append("missing_data_policy_invalid")

    market_policy = policy.get("market_gate_policy", {})
    if (
        market_policy.get("grade_is_independent_of_market_regime") is not True
        or market_policy.get("score_is_independent_of_market_regime") is not True
    ):
        errors.append("market_gate_separation_invalid")

    routing = policy.get("shadow_routing", {})
    if (
        routing.get("watchlist_policy") != "v1"
        or routing.get("tradeplan_policy") != "v1"
        or routing.get("v2_may_drive_business_writes") is not False
    ):
        errors.append("official_routing_not_v1")

    version = str(policy.get("version", ""))
    if not version.startswith(str(rules.get("required_policy_version_prefix", ""))):
        errors.append("policy_version_invalid")
    if policy.get("schema_version") != rules.get("required_schema_version"):
        errors.append("schema_version_invalid")
    if policy.get("status") != rules.get("required_status"):
        errors.append("policy_status_not_shadow")
    return errors


def grade_symbol_v2_shadow(
    symbol_payload: dict[str, Any],
    candidate_payload: dict[str, Any] | None = None,
    market_regime: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_policy = policy or load_grading_policy_v2()
    candidate = candidate_payload or {}
    values = _resolve_fields(active_policy, symbol_payload, candidate)
    result = _base_result(active_policy, market_regime)

    if values.get("scan_eligible") is False:
        result["grade_v2_shadow"] = "Eliminated"
        result["v2_rejection_reasons"] = ["scan_eligible=false，不進入 v2 影子評分。"]
        return _apply_market_gate(result, active_policy)

    missing_fields, data_errors = _required_field_errors(active_policy, values)
    if missing_fields:
        result["missing_fields"] = missing_fields
        result["data_errors"] = data_errors
        result["v2_rejection_reasons"] = [
            "必要欄位缺少或型別無效，依 v2 缺值政策維持 Ungraded。"
        ]
        return _apply_market_gate(result, active_policy)
    if values["ohlcv_complete"] is not True:
        result["data_errors"] = ["ohlcv_incomplete"]
        result["v2_rejection_reasons"] = ["OHLCV 不完整，維持 Ungraded。"]
        return _apply_market_gate(result, active_policy)

    derived_errors = _derived_data_errors(values)
    if derived_errors:
        result["data_errors"] = derived_errors
        result["v2_rejection_reasons"] = ["衍生欄位無效，維持 Ungraded。"]
        return _apply_market_gate(result, active_policy)

    values["pivot_distance_pct"] = (values["close"] / values["pivot_price"] - 1) * 100
    components = _component_scores(active_policy, values)
    raw_score = round(sum(components.values()), 2)
    preliminary = _preliminary_grade(active_policy, raw_score)
    caps = _applied_caps(active_policy, values)
    capped_grade = _apply_caps(preliminary, caps)
    final_grade, hard_checks, rejection_reasons = _apply_a_grade_hard_checks(
        active_policy, capped_grade, values
    )
    result.update(
        {
            "score_v2_shadow": raw_score,
            "grade_v2_shadow": final_grade,
            "preliminary_grade_v2_shadow": preliminary,
            "component_scores": components,
            "pivot_distance_pct": round(values["pivot_distance_pct"], 2),
            "applied_caps": caps,
            "hard_risk_checks": hard_checks,
            "v2_rejection_reasons": rejection_reasons,
        }
    )
    return _apply_market_gate(result, active_policy)


def _base_result(policy: dict[str, Any], market_regime: str | None) -> dict[str, Any]:
    return {
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "policy_status": policy["status"],
        "grade_v2_shadow": "Ungraded",
        "score_v2_shadow": None,
        "preliminary_grade_v2_shadow": None,
        "component_scores": {},
        "pivot_distance_pct": None,
        "missing_fields": [],
        "data_errors": [],
        "applied_caps": [],
        "hard_risk_checks": [],
        "v2_rejection_reasons": [],
        "market_regime": market_regime or "insufficient_data",
        "market_gate_shadow": "not_applicable",
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


def _required_field_errors(
    policy: dict[str, Any], values: dict[str, Any]
) -> tuple[list[str], list[str]]:
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
        if not valid:
            missing.append(field)
            if value is not None:
                errors.append(f"invalid_type:{field}")
    return missing, errors


def _derived_data_errors(values: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in (
        "close",
        "pivot_price",
        "adr20_pct",
        "atr14_pct",
        "avg_turnover_20d",
    ):
        if values[field] <= 0:
            errors.append(f"{field}_must_be_positive")
    for field in (
        "rs_rank_1m",
        "rs_rank_3m",
        "rs_rank_6m",
        "composite_rs_rank",
        "htf_structure_score",
    ):
        if not 0 <= values[field] <= 100:
            errors.append(f"{field}_outside_0_100")
    for field in (
        "stop_risk_pct",
        "stop_to_adr_ratio",
        "stop_to_atr_ratio",
        "volume_contraction_ratio",
        "volume_ratio_20d",
    ):
        if values[field] < 0:
            errors.append(f"{field}_must_be_non_negative")
    return errors


def _component_scores(policy: dict[str, Any], values: dict[str, Any]) -> dict[str, float]:
    weights = policy["scoring"]["weights"]
    params = policy["parameters"]

    trend_points = 0.0
    trend_points += 5.0 if values["monthly_above_ma12"] else 0.0
    trend_points += {"uptrend": 5.0, "neutral": 2.5, "downtrend": 0.0}.get(
        values["weekly_trend_state"], 0.0
    )
    trend_points += {
        "breakout_confirmed": 5.0,
        "near_trigger": 4.0,
        "inside_flag": 3.0,
        "extended": 1.0,
        "failed_breakout": 0.0,
    }.get(values["daily_trigger_state"], 0.0)

    weighted_rs = (
        values["rs_rank_1m"] * 0.20
        + values["rs_rank_3m"] * 0.30
        + values["rs_rank_6m"] * 0.30
        + values["composite_rs_rank"] * 0.20
    )
    prior_move = max(values["prior_move_pct_20d"], values["prior_move_pct_60d"])
    prior_move_ratio = 1.0 if prior_move >= 100 else 0.7 if prior_move >= 50 else 0.4 if prior_move >= 30 else 0.0
    pivot_distance = abs(values["pivot_distance_pct"])
    pivot_cfg = params["pivot"]
    pivot_ratio = (
        1.0
        if pivot_distance <= pivot_cfg["preferred_absolute_distance_pct"]
        else 0.6
        if pivot_distance <= pivot_cfg["maximum_absolute_distance_pct"]
        else 0.0
    )

    stop_cfg = params["stop_quality"]
    adr_cfg = params["adr"]
    stop_points = 0.0
    stop_points += 5.0 if values["stop_risk_pct"] <= stop_cfg["preferred_maximum_stop_risk_pct"] else 2.5
    stop_points += (
        4.0
        if adr_cfg["preferred_minimum_pct"] <= values["adr20_pct"] <= adr_cfg["maximum_pct"]
        else 2.0
        if adr_cfg["minimum_pct"] <= values["adr20_pct"] <= adr_cfg["maximum_pct"]
        else 0.0
    )
    stop_points += 3.0 if values["stop_to_adr_ratio"] <= stop_cfg["preferred_maximum_stop_to_adr_ratio"] else 1.5
    stop_points += 3.0 if values["stop_to_atr_ratio"] <= stop_cfg["preferred_maximum_stop_to_atr_ratio"] else 1.5

    volume_points = 0.0
    volume_points += 3.0 if values["volume_contraction_ratio"] <= 0.8 else 1.0 if values["volume_contraction_ratio"] <= 1.0 else 0.0
    volume_points += 2.0 if values["volume_ratio_20d"] >= 1.5 else 1.0 if values["volume_ratio_20d"] >= 1.0 else 0.0

    liquidity_cfg = params["liquidity"]
    liquidity_ratio = (
        1.0
        if values["avg_turnover_20d"] >= liquidity_cfg["preferred_avg_turnover_20d"]
        else 0.6
        if values["avg_turnover_20d"] >= liquidity_cfg["minimum_avg_turnover_20d"]
        else 0.0
    )
    extension_ratio = (
        0.0
        if values["extended_risk"]
        else 1.0
        if values["distance_to_ma10_pct"] <= params["extension"]["maximum_distance_to_ma10_pct"]
        else 0.4
    )
    return {
        "timeframe_trend": round(trend_points / 15 * weights["timeframe_trend"], 2),
        "multi_period_rs": round(weighted_rs / 100 * weights["multi_period_rs"], 2),
        "prior_move": round(prior_move_ratio * weights["prior_move"], 2),
        "htf_structure": round(values["htf_structure_score"] / 100 * weights["htf_structure"], 2),
        "pivot_position": round(pivot_ratio * weights["pivot_position"], 2),
        "stop_quality": round(stop_points / 15 * weights["stop_quality"], 2),
        "volume_behavior": round(volume_points / 5 * weights["volume_behavior"], 2),
        "liquidity": round(liquidity_ratio * weights["liquidity"], 2),
        "extension_risk": round(extension_ratio * weights["extension_risk"], 2),
    }


def _preliminary_grade(policy: dict[str, Any], score: float) -> str:
    for threshold in policy["grade_thresholds"]["ordered_descending"]:
        if score >= threshold["minimum_score"]:
            return str(threshold["grade"])
    return "C"


def _applied_caps(policy: dict[str, Any], values: dict[str, Any]) -> list[dict[str, str]]:
    applied: list[dict[str, str]] = []
    for cap in policy["grade_caps"]:
        target = cap["value"]
        operator = cap["operator"]
        if operator.endswith("_parameter"):
            target = _parameter(policy, str(target))
            operator = operator.removesuffix("_parameter")
        if _condition(values.get(cap["field"]), operator, target):
            applied.append({"id": cap["id"], "maximum_grade": cap["maximum_grade"]})
    return applied


def _apply_caps(grade: str, caps: list[dict[str, str]]) -> str:
    index = QUALITY_GRADES.index(grade)
    for cap in caps:
        index = max(index, QUALITY_GRADES.index(cap["maximum_grade"]))
    return QUALITY_GRADES[index]


def _apply_a_grade_hard_checks(
    policy: dict[str, Any], grade: str, values: dict[str, Any]
) -> tuple[str, list[dict[str, Any]], list[str]]:
    if grade not in {"A", "A-"}:
        reasons = [f"grade_cap:{item['id']}" for item in _applied_caps(policy, values)]
        return grade, [], reasons

    checked: list[dict[str, Any]] = []
    grades_to_try = ["A", "A-"] if grade == "A" else ["A-"]
    for candidate_grade in grades_to_try:
        failures = _hard_check_failures(policy, candidate_grade, values)
        checked.append({"grade": candidate_grade, "passed": not failures, "failures": failures})
        if not failures:
            reasons = [] if candidate_grade == grade else [f"hard_risk_downgrade:{grade}_to_{candidate_grade}"]
            return candidate_grade, checked, reasons
    return "B", checked, [f"hard_risk_downgrade:{grade}_to_B"]


def _hard_check_failures(
    policy: dict[str, Any], grade: str, values: dict[str, Any]
) -> list[str]:
    rules = policy["hard_risk_checks_for_a_grades"][grade]
    failures: list[str] = []
    if values["htf_structure_status"] not in rules["allowed_htf_statuses"]:
        failures.append("htf_structure_status")
    if values["composite_rs_rank"] < rules["minimum_composite_rs_rank"]:
        failures.append("composite_rs_rank")
    checks = (
        ("stop_risk_pct", "maximum_stop_risk_pct_parameter"),
        ("stop_to_adr_ratio", "maximum_stop_to_adr_ratio_parameter"),
        ("stop_to_atr_ratio", "maximum_stop_to_atr_ratio_parameter"),
        ("avg_turnover_20d", "minimum_avg_turnover_20d_parameter"),
    )
    for field, parameter_key in checks:
        threshold = _parameter(policy, rules[parameter_key])
        failed = values[field] < threshold if parameter_key.startswith("minimum") else values[field] > threshold
        if failed:
            failures.append(field)
    pivot_limit = _parameter(policy, rules["maximum_absolute_pivot_distance_pct_parameter"])
    if abs(values["pivot_distance_pct"]) > pivot_limit:
        failures.append("pivot_distance_pct")
    if values["extended_risk"] is not rules["extended_risk"]:
        failures.append("extended_risk")
    return failures


def _parameter(policy: dict[str, Any], path: str) -> float:
    value: Any = policy["parameters"]
    for key in path.split("."):
        value = value[key]
    return float(value)


def _condition(value: Any, operator: str, target: Any) -> bool:
    if operator == "eq":
        return value == target
    if operator == "in":
        return value in target
    if operator == "lt":
        return value < target
    if operator == "gt":
        return value > target
    return False


def _apply_market_gate(result: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    grade = result["grade_v2_shadow"]
    market = result["market_regime"]
    market_policy = policy["market_gate_policy"]
    if grade not in QUALITY_GRADES:
        result["market_gate_shadow"] = market_policy["non_graded"]
        return result
    regime_rules = market_policy.get(market, market_policy["fallback"])
    result["market_gate_shadow"] = regime_rules[grade]
    return result


def cloned_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Return a test-safe mutable policy copy."""
    return deepcopy(policy)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
