from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from stock_health.position_management import (
    evaluate_position_management,
    load_position_management_policy,
    validate_position_management_policy,
)


ROOT = Path(__file__).resolve().parents[1]


def position(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "2330",
        "position_status": "open",
        "entry_date": "2026-07-01",
        "entry_price": 100.0,
        "initial_stop": 95.0,
        "trigger_reference": 98.0,
        "completed_event_ids": [],
    }
    payload.update(overrides)
    return payload


def bars(
    closes: list[float],
    ma10: float | None = 101.0,
    ma20: float | None = 98.0,
) -> list[dict[str, object]]:
    days = [
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
        "2026-07-09",
    ]
    return [
        {"date": day, "close": close, "ma10": ma10, "ma20": ma20}
        for day, close in zip(days[: len(closes)], closes, strict=True)
    ]


def official(result: dict[str, object]) -> dict[str, object]:
    return result["model_comparison_snapshot"]["models"]["plus_2r_v1"]  # type: ignore[index]


def shadow(result: dict[str, object]) -> dict[str, object]:
    return result["model_comparison_snapshot"]["models"]["qullamaggie_3_5d_shadow"]  # type: ignore[index]


def test_policy_is_valid_and_routes_shadow_model_officially_off() -> None:
    policy = load_position_management_policy(ROOT)
    assert validate_position_management_policy(policy) == []
    assert policy["official_model"] == "plus_2r_v1"
    assert policy["models"]["qullamaggie_3_5d_shadow"]["role"] == "shadow_comparison_only"
    assert policy["validation_rules"]["real_trading_forbidden"] is True


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (
            lambda policy: policy["models"]["plus_2r_v1"]["partial_exit"].update(
                {"ratio": 0.9}
            ),
            "partial_exit_ratio_invalid:plus_2r_v1",
        ),
        (
            lambda policy: policy["models"]["qullamaggie_3_5d_shadow"][
                "trailing_exit"
            ].update({"moving_average": "ma50"}),
            "trailing_ma_invalid:qullamaggie_3_5d_shadow",
        ),
        (
            lambda policy: policy["risk_calculation"].update(
                {"entry_source": "trigger_reference"}
            ),
            "risk_source_invalid",
        ),
    ],
)
def test_policy_validator_rejects_unsafe_configuration(
    mutator: object, expected: str
) -> None:
    policy = deepcopy(load_position_management_policy(ROOT))
    mutator(policy)  # type: ignore[operator]
    assert expected in validate_position_management_policy(policy)


def test_not_entered_keeps_original_references() -> None:
    result = evaluate_position_management(
        position(position_status="pending", entry_price=None),
        [],
        policy=load_position_management_policy(ROOT),
    )
    assert result["position_stage"] == "not_entered"
    assert result["entry_price"] is None
    assert result["initial_stop"] == 95.0
    assert result["trigger_reference"] == 98.0
    assert result["current_r"] is None
    assert result["immutable_field_check"]["trigger_used_as_entry"] is False


def test_holding_before_partial_exit_threshold() -> None:
    result = evaluate_position_management(
        position(),
        bars([100.0, 102.0, 104.0]),
        policy=load_position_management_policy(ROOT),
    )
    assert result["days_since_entry"] == 2
    assert result["current_r"] == 0.8
    assert result["position_stage"] == "holding_pre_partial"
    assert result["partial_exit_due"] is False
    assert official(result)["events_to_create"] == []
    assert shadow(result)["events_to_create"] == []


def test_qullamaggie_shadow_reduces_on_day_three_without_changing_official() -> None:
    result = evaluate_position_management(
        position(),
        bars([100.0, 102.0, 103.0, 104.0]),
        policy=load_position_management_policy(ROOT),
    )
    assert result["days_since_entry"] == 3
    assert result["position_stage"] == "holding_pre_partial"
    assert result["exit_model"] == "plus_2r_v1"
    assert official(result)["partial_exit_due"] is False
    assert shadow(result)["partial_exit_due"] is True
    assert shadow(result)["partial_exit_ratio"] == pytest.approx(0.333333)
    assert shadow(result)["exit_signal"] == "partial_exit"
    assert shadow(result)["events_to_create"] == []
    assert result["model_comparison_snapshot"]["shadow_output_drives_simulation"] is False


def test_plus_two_r_model_emits_partial_exit_once() -> None:
    policy = load_position_management_policy(ROOT)
    first = evaluate_position_management(
        position(),
        bars([100.0, 102.0, 106.0, 110.0]),
        policy=policy,
    )
    first_official = official(first)
    assert first_official["current_r"] == 2.0
    assert first_official["partial_exit_due"] is True
    assert first_official["partial_exit_ratio"] == 0.5
    assert len(first_official["events_to_create"]) == 1

    rerun = evaluate_position_management(
        position(),
        bars([100.0, 102.0, 106.0, 110.0]),
        previous_snapshot=first,
        policy=policy,
    )
    rerun_official = official(rerun)
    assert rerun_official["pending_events"] == first_official["pending_events"]
    assert rerun_official["events_to_create"] == []
    assert rerun_official["emitted_event_ids"] == first_official["emitted_event_ids"]


def test_plus_two_r_uses_max_r_reached_after_pullback() -> None:
    result = evaluate_position_management(
        position(),
        bars([100.0, 110.0, 108.0]),
        policy=load_position_management_policy(ROOT),
    )
    current = official(result)
    assert current["current_r"] == 1.6
    assert current["max_r_reached"] == 2.0
    assert current["partial_exit_due"] is True


def test_completed_shadow_event_does_not_change_official_model() -> None:
    shadow_partial_id = (
        "2330:qullamaggie_3_5d_shadow:partial_exit:2026-07-06"
    )
    result = evaluate_position_management(
        position(completed_event_ids=[shadow_partial_id]),
        bars([100.0, 101.0, 102.0, 103.0]),
        policy=load_position_management_policy(ROOT),
    )
    assert official(result)["partial_exit_completed"] is False
    assert official(result)["position_stage"] == "holding_pre_partial"
    assert shadow(result)["partial_exit_completed"] is True


def test_completed_partial_exit_is_not_recreated_and_activates_break_even() -> None:
    policy = load_position_management_policy(ROOT)
    due = evaluate_position_management(
        position(),
        bars([100.0, 103.0, 106.0, 110.0]),
        policy=policy,
    )
    event_id = official(due)["pending_events"][0]["event_id"]  # type: ignore[index]
    completed_position = position(completed_event_ids=[event_id])
    reduced = evaluate_position_management(
        completed_position,
        bars([100.0, 103.0, 106.0, 110.0]),
        previous_snapshot=due,
        policy=policy,
    )
    reduced_official = official(reduced)
    assert reduced_official["position_stage"] == "partially_reduced"
    assert reduced_official["partial_exit_completed"] is True
    assert reduced_official["break_even_stop_activated"] is True
    assert reduced_official["active_trailing_ma"] == "ma10"
    assert reduced_official["events_to_create"] == []
    assert reduced_official["pending_events"] == []

    rerun = evaluate_position_management(
        completed_position,
        bars([100.0, 103.0, 106.0, 110.0]),
        previous_snapshot=reduced,
        policy=policy,
    )
    assert official(rerun)["position_stage"] == "partially_reduced"
    assert official(rerun)["events_to_create"] == []


def test_break_even_stop_uses_close_and_requires_completed_partial() -> None:
    policy = load_position_management_policy(ROOT)
    partial_id = "2330:plus_2r_v1:partial_exit:2026-07-06"
    previous = evaluate_position_management(
        position(completed_event_ids=[partial_id]),
        bars([100.0, 104.0, 108.0, 110.0]),
        policy=policy,
    )
    result = evaluate_position_management(
        position(completed_event_ids=[partial_id]),
        bars([100.0, 104.0, 108.0, 110.0, 99.5], ma10=105.0),
        previous_snapshot=previous,
        policy=policy,
    )
    current = official(result)
    assert current["break_even_stop_activated"] is True
    assert current["exit_signal"] == "stop_exit"
    assert current["exit_reason"] == "close_at_or_below_break_even_stop"
    assert current["position_stage"] == "stopped_out"


def test_completed_partial_moves_to_break_even_stage_when_ma_is_missing() -> None:
    policy = load_position_management_policy(ROOT)
    partial_id = "2330:plus_2r_v1:partial_exit:2026-07-06"
    previous = evaluate_position_management(
        position(completed_event_ids=[partial_id]),
        bars([100.0, 104.0, 108.0, 110.0], ma10=None),
        policy=policy,
    )
    result = evaluate_position_management(
        position(completed_event_ids=[partial_id]),
        bars([100.0, 104.0, 108.0, 110.0, 103.0], ma10=None),
        previous_snapshot=previous,
        policy=policy,
    )
    current = official(result)
    assert current["position_stage"] == "break_even_active"
    assert current["break_even_stop_activated"] is True
    assert current["active_trailing_ma"] == "ma10"
    assert current["close_below_trailing_ma"] is None
    assert current["exit_signal"] == "none"


def test_completed_partial_moves_to_trailing_stage_above_ma() -> None:
    policy = load_position_management_policy(ROOT)
    partial_id = "2330:plus_2r_v1:partial_exit:2026-07-06"
    previous = evaluate_position_management(
        position(completed_event_ids=[partial_id]),
        bars([100.0, 104.0, 108.0, 110.0], ma10=104.0),
        policy=policy,
    )
    result = evaluate_position_management(
        position(completed_event_ids=[partial_id]),
        bars([100.0, 104.0, 108.0, 110.0, 106.0], ma10=104.0),
        previous_snapshot=previous,
        policy=policy,
    )
    current = official(result)
    assert current["position_stage"] == "trailing_active"
    assert current["break_even_stop_activated"] is True
    assert current["close_below_trailing_ma"] is False
    assert current["exit_signal"] == "none"


def test_trailing_ma_exit_uses_close_confirmation() -> None:
    policy = load_position_management_policy(ROOT)
    partial_id = "2330:plus_2r_v1:partial_exit:2026-07-06"
    previous = evaluate_position_management(
        position(completed_event_ids=[partial_id]),
        bars([100.0, 104.0, 108.0, 110.0]),
        policy=policy,
    )
    result = evaluate_position_management(
        position(completed_event_ids=[partial_id]),
        bars([100.0, 104.0, 108.0, 110.0, 103.0], ma10=104.0),
        previous_snapshot=previous,
        policy=policy,
    )
    current = official(result)
    assert current["close_below_trailing_ma"] is True
    assert current["exit_signal"] == "trailing_exit"
    assert current["exit_reason"] == "close_below_ma10"


def test_initial_stop_exit_and_fully_exited_transition_are_idempotent() -> None:
    policy = load_position_management_policy(ROOT)
    stopped = evaluate_position_management(
        position(),
        bars([100.0, 98.0, 94.5]),
        policy=policy,
    )
    stopped_model = official(stopped)
    assert stopped_model["position_stage"] == "stopped_out"
    assert stopped_model["exit_reason"] == "close_at_or_below_initial_stop"
    assert len(stopped_model["events_to_create"]) == 1

    rerun = evaluate_position_management(
        position(),
        bars([100.0, 98.0, 94.5]),
        previous_snapshot=stopped,
        policy=policy,
    )
    assert official(rerun)["events_to_create"] == []

    event_id = stopped_model["pending_events"][0]["event_id"]  # type: ignore[index]
    exited = evaluate_position_management(
        position(completed_event_ids=[event_id]),
        bars([100.0, 98.0, 94.5]),
        previous_snapshot=rerun,
        policy=policy,
    )
    assert official(exited)["position_stage"] == "fully_exited"
    assert official(exited)["exit_signal"] == "fully_exited"
    assert official(exited)["events_to_create"] == []


def test_trigger_never_replaces_entry_in_r_calculation() -> None:
    result = evaluate_position_management(
        position(entry_price=100.0, initial_stop=95.0, trigger_reference=80.0),
        bars([100.0, 105.0]),
        policy=load_position_management_policy(ROOT),
    )
    assert result["entry_price"] == 100.0
    assert result["trigger_reference"] == 80.0
    assert result["current_r"] == 1.0
    assert result["max_r_reached"] == 1.0


def test_shadow_ratio_and_trailing_ma_are_configurable() -> None:
    policy = deepcopy(load_position_management_policy(ROOT))
    shadow_policy = policy["models"]["qullamaggie_3_5d_shadow"]
    shadow_policy["partial_exit"]["ratio"] = 0.5
    shadow_policy["trailing_exit"]["moving_average"] = "ma20"
    due = evaluate_position_management(
        position(),
        bars([100.0, 101.0, 102.0, 103.0]),
        policy=policy,
    )
    assert shadow(due)["partial_exit_ratio"] == 0.5
    event_id = shadow(due)["pending_events"][0]["event_id"]  # type: ignore[index]
    reduced = evaluate_position_management(
        position(completed_event_ids=[event_id]),
        bars([100.0, 101.0, 102.0, 103.0]),
        previous_snapshot=due,
        policy=policy,
    )
    assert shadow(reduced)["active_trailing_ma"] == "ma20"


def test_invalid_stop_is_structured_invalid_data() -> None:
    result = evaluate_position_management(
        position(initial_stop=101.0),
        bars([100.0, 102.0]),
        policy=load_position_management_policy(ROOT),
    )
    assert result["position_stage"] == "invalid_data"
    assert "initial_stop_must_be_below_entry_price" in official(result)["data_errors"]
