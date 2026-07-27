from __future__ import annotations

import json
from pathlib import Path
from typing import Any


POLICY_RELATIVE_PATH = Path("data/chatgpt/orh-shadow-policy-v1.json")
ORH_OUTPUT_FIELDS = (
    "orh_1m",
    "orh_5m",
    "orh_30m",
    "orh_60m",
    "orh_triggered_at",
    "orh_entry_price",
    "orh_initial_stop",
    "orh_slippage_pct",
    "confirmation_close_entry",
    "orh_model_r",
    "close_confirmation_model_r",
)
REQUIRED_TIMEFRAMES_MINUTES = {1, 5, 30, 60}
REQUIRED_CAPABILITIES = {
    "ohlcv_available",
    "timestamps_include_timezone",
    "historical_retention_documented",
    "corporate_actions_handled",
    "abnormal_trading_handled",
    "authenticated_runtime_verified",
    "cross_market_coverage_verified",
}


def load_orh_shadow_policy(root: Path | str = ".") -> dict[str, Any]:
    with (Path(root) / POLICY_RELATIVE_PATH).open(encoding="utf-8") as handle:
        return json.load(handle)


def validate_orh_shadow_policy(policy: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_sections = {
        "policy_id",
        "version",
        "schema_version",
        "status",
        "official_entry_model",
        "orh_model",
        "data_reliability_gate",
        "source_assessment",
        "output_contract",
        "snapshot_contract",
        "look_ahead_policy",
        "comparison_metrics",
        "activation_criteria",
        "validation_rules",
    }
    missing = sorted(required_sections - policy.keys())
    if missing:
        errors.append("missing_sections:" + ",".join(missing))

    if policy.get("status") != "blocked_data_source":
        errors.append("status_must_remain_blocked")
    if policy.get("official_entry_model") != "breakout_confirmation_close":
        errors.append("official_entry_model_invalid")

    orh_model = policy.get("orh_model", {})
    if (
        orh_model.get("role") != "shadow_only"
        or orh_model.get("enabled") is not False
        or orh_model.get("may_write_tradeplan") is not False
        or orh_model.get("may_execute_real_trade") is not False
    ):
        errors.append("orh_shadow_safety_invalid")

    gate = policy.get("data_reliability_gate", {})
    if gate.get("passed") is not False:
        errors.append("data_reliability_gate_must_be_false")
    if set(gate.get("required_timeframes_minutes", [])) != REQUIRED_TIMEFRAMES_MINUTES:
        errors.append("required_timeframes_invalid")
    if set(gate.get("required_capabilities", [])) != REQUIRED_CAPABILITIES:
        errors.append("required_capabilities_invalid")
    if not gate.get("blocking_reasons"):
        errors.append("blocking_reasons_required")

    assessments = policy.get("source_assessment", [])
    if not assessments:
        errors.append("source_assessment_required")
    for assessment in assessments:
        source_id = str(assessment.get("source_id") or "unknown")
        if assessment.get("current_pipeline_usable") is not False:
            errors.append(f"source_must_remain_unavailable:{source_id}")
        if assessment.get("capabilities") and source_assessment_passes(assessment):
            errors.append(f"source_cannot_pass_before_gate:{source_id}")

    if set(policy.get("output_contract", {}).get("nullable_fields", [])) != set(
        ORH_OUTPUT_FIELDS
    ):
        errors.append("output_contract_invalid")
    snapshot = policy.get("snapshot_contract", {})
    if (
        snapshot.get("append_only") is not True
        or snapshot.get("source_payload_hash_required") is not True
        or snapshot.get("captured_at_timezone") != "Asia/Taipei"
    ):
        errors.append("snapshot_contract_invalid")

    look_ahead = policy.get("look_ahead_policy", {})
    if (
        look_ahead.get("daily_ohlcv_inference_forbidden") is not True
        or look_ahead.get("future_bars_forbidden") is not True
        or look_ahead.get("recompute_past_signal_with_new_data_forbidden") is not True
    ):
        errors.append("look_ahead_policy_invalid")

    rules = policy.get("validation_rules", {})
    if (
        rules.get("official_model_must_remain_confirmation_close") is not True
        or rules.get("orh_must_remain_shadow_only") is not True
        or rules.get("business_writes_forbidden") is not True
        or rules.get("real_trading_forbidden") is not True
    ):
        errors.append("validation_rules_invalid")
    return errors


def orh_output_template() -> dict[str, None]:
    """Return the disabled interface shape without inferring values from daily bars."""
    return {field: None for field in ORH_OUTPUT_FIELDS}


def source_assessment_passes(assessment: dict[str, Any]) -> bool:
    timeframes = set(assessment.get("timeframes_minutes", []))
    capabilities = assessment.get("capabilities", {})
    return REQUIRED_TIMEFRAMES_MINUTES.issubset(timeframes) and all(
        capabilities.get(capability) is True
        for capability in REQUIRED_CAPABILITIES
    )


def assert_orh_activation_allowed(policy: dict[str, Any]) -> None:
    errors = validate_orh_shadow_policy(policy)
    if errors:
        raise ValueError("invalid ORH shadow policy: " + ",".join(errors))
    if not policy["data_reliability_gate"]["passed"]:
        raise RuntimeError("ORH shadow activation blocked: intraday source not verified")
