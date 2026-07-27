from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from stock_health.orh_shadow import (
    ORH_OUTPUT_FIELDS,
    assert_orh_activation_allowed,
    load_orh_shadow_policy,
    orh_output_template,
    source_assessment_passes,
    validate_orh_shadow_policy,
)


ROOT = Path(__file__).resolve().parents[1]


def test_policy_is_valid_but_data_source_gate_is_blocked() -> None:
    policy = load_orh_shadow_policy(ROOT)
    assert validate_orh_shadow_policy(policy) == []
    assert policy["status"] == "blocked_data_source"
    assert policy["official_entry_model"] == "breakout_confirmation_close"
    assert policy["orh_model"]["role"] == "shadow_only"
    assert policy["orh_model"]["daily_pipeline_integrated"] is False
    assert policy["data_reliability_gate"]["passed"] is False


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (
            lambda policy: policy.update({"official_entry_model": "orh_5m"}),
            "official_entry_model_invalid",
        ),
        (
            lambda policy: policy["orh_model"].update({"may_write_tradeplan": True}),
            "orh_shadow_safety_invalid",
        ),
        (
            lambda policy: policy["look_ahead_policy"].update(
                {"daily_ohlcv_inference_forbidden": False}
            ),
            "look_ahead_policy_invalid",
        ),
        (
            lambda policy: policy["source_assessment"][2].update(
                {"current_pipeline_usable": True}
            ),
            "source_must_remain_unavailable:fugle_marketdata_candidate",
        ),
    ],
)
def test_validator_rejects_unsafe_policy(
    mutator: object,
    expected: str,
) -> None:
    policy = deepcopy(load_orh_shadow_policy(ROOT))
    mutator(policy)  # type: ignore[operator]
    assert expected in validate_orh_shadow_policy(policy)


def test_disabled_interface_keeps_all_orh_values_null() -> None:
    template = orh_output_template()
    assert set(template) == set(ORH_OUTPUT_FIELDS)
    assert all(value is None for value in template.values())


def test_candidate_source_fails_until_every_capability_is_verified() -> None:
    assessment = {
        "timeframes_minutes": [1, 5, 30, 60],
        "capabilities": {
            "ohlcv_available": True,
            "timestamps_include_timezone": True,
            "historical_retention_documented": True,
            "corporate_actions_handled": True,
            "abnormal_trading_handled": True,
            "authenticated_runtime_verified": True,
            "cross_market_coverage_verified": False,
        },
    }
    assert source_assessment_passes(assessment) is False
    assessment["capabilities"]["cross_market_coverage_verified"] = True
    assert source_assessment_passes(assessment) is True


def test_activation_is_rejected_and_daily_bars_are_not_accepted() -> None:
    policy = load_orh_shadow_policy(ROOT)
    with pytest.raises(RuntimeError, match="intraday source not verified"):
        assert_orh_activation_allowed(policy)
    assert "daily_ohlcv" not in str(orh_output_template())
