from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from stock_health.grading_policy_v2 import (
    cloned_policy,
    grade_symbol_v2_shadow,
    load_grading_policy_v2,
    validate_grading_policy_v2,
)
from stock_health.grading_shadow import (
    apply_shadow_grades,
    build_shadow_history_index,
    shadow_history_path,
)
from stock_health.history_store import write_json


ROOT = Path(__file__).resolve().parents[1]


def symbol_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "2330",
        "name": "測試普通股",
        "market": "listed",
        "scan_eligible": True,
        "data_quality": {"ohlcv_complete": True},
        "close": 100.0,
        "ma10": 96.0,
        "ma20": 92.0,
        "ma50": 85.0,
        "avg_volume_20d": 600_000.0,
        "avg_turnover_20d": 60_000_000.0,
        "volume_ratio_20d": 1.6,
        "pivot_price": 99.0,
        "stop_reference": 94.0,
        "setup_type": "breakout",
        "monthly_above_ma12": True,
        "weekly_trend_state": "uptrend",
        "daily_trigger_state": "breakout_confirmed",
        "rs_rank_1m": 95.0,
        "rs_rank_3m": 94.0,
        "rs_rank_6m": 92.0,
        "composite_rs_rank": 94.0,
        "prior_move_pct_20d": 105.0,
        "prior_move_pct_60d": 130.0,
        "htf_structure_score": 90.0,
        "htf_structure_status": "valid_htf",
        "adr20_pct": 4.0,
        "atr14_pct": 3.5,
        "stop_risk_pct": 6.0,
        "stop_to_adr_ratio": 1.5,
        "stop_to_atr_ratio": 1.7,
        "volume_contraction_ratio": 0.7,
        "extended_risk": False,
        "distance_to_ma10_pct": 4.2,
    }
    payload.update(overrides)
    return payload


def candidate_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "2330",
        "relative_strength_rank": 95.0,
        "qullamaggie_score": 88,
        "setup_type": "breakout",
    }
    payload.update(overrides)
    return payload


def test_v2_policy_validator_accepts_canonical_policy() -> None:
    policy = load_grading_policy_v2(ROOT)
    assert validate_grading_policy_v2(policy) == []
    assert sum(policy["scoring"]["weights"].values()) == 100
    assert policy["status"] == "shadow"
    assert policy["shadow_routing"]["watchlist_policy"] == "v1"
    assert policy["shadow_routing"]["tradeplan_policy"] == "v1"
    assert policy["shadow_routing"]["v2_may_drive_business_writes"] is False


@pytest.mark.parametrize(
    ("mutation", "expected_error"),
    [
        (lambda policy: policy["scoring"]["weights"].update({"liquidity": 6}), "invalid_weight_total"),
        (lambda policy: policy["missing_data_policy"].update({"missing_value_is_zero": True}), "missing_data_policy_invalid"),
        (lambda policy: policy["market_gate_policy"].update({"grade_is_independent_of_market_regime": False}), "market_gate_separation_invalid"),
        (lambda policy: policy["shadow_routing"].update({"watchlist_policy": "v2"}), "official_routing_not_v1"),
    ],
)
def test_v2_policy_validator_rejects_invalid_contract(
    mutation: object, expected_error: str
) -> None:
    policy = cloned_policy(load_grading_policy_v2(ROOT))
    mutation(policy)  # type: ignore[operator]
    assert any(
        error.startswith(expected_error) for error in validate_grading_policy_v2(policy)
    )


def test_high_quality_symbol_receives_shadow_a() -> None:
    result = grade_symbol_v2_shadow(
        symbol_payload(), candidate_payload(), "risk_on", load_grading_policy_v2(ROOT)
    )
    assert result["grade_v2_shadow"] == "A"
    assert result["score_v2_shadow"] >= 85
    assert result["market_gate_shadow"] == "open"


def test_missing_field_is_ungraded_and_never_zero() -> None:
    result = grade_symbol_v2_shadow(
        symbol_payload(atr14_pct=None),
        candidate_payload(),
        "risk_on",
        load_grading_policy_v2(ROOT),
    )
    assert result["grade_v2_shadow"] == "Ungraded"
    assert result["score_v2_shadow"] is None
    assert result["component_scores"] == {}
    assert result["missing_fields"] == ["atr14_pct"]
    assert result["v2_rejection_reasons"]


def test_risk_off_changes_only_market_gate() -> None:
    policy = load_grading_policy_v2(ROOT)
    risk_on = grade_symbol_v2_shadow(
        symbol_payload(), candidate_payload(), "risk_on", policy
    )
    risk_off = grade_symbol_v2_shadow(
        symbol_payload(), candidate_payload(), "risk_off", policy
    )
    assert risk_on["grade_v2_shadow"] == risk_off["grade_v2_shadow"]
    assert risk_on["score_v2_shadow"] == risk_off["score_v2_shadow"]
    assert risk_on["market_gate_shadow"] == "open"
    assert risk_off["market_gate_shadow"] == "blocked"


def test_a_grade_requires_hard_risk_checks() -> None:
    result = grade_symbol_v2_shadow(
        symbol_payload(htf_structure_status="developing"),
        candidate_payload(),
        "risk_on",
        load_grading_policy_v2(ROOT),
    )
    assert result["score_v2_shadow"] >= 85
    assert result["grade_v2_shadow"] == "A-"
    assert result["hard_risk_checks"][0]["passed"] is False


def test_adr_threshold_is_read_from_policy() -> None:
    policy = load_grading_policy_v2(ROOT)
    baseline = grade_symbol_v2_shadow(
        symbol_payload(), candidate_payload(), "risk_on", policy
    )
    changed = deepcopy(policy)
    changed["parameters"]["adr"]["preferred_minimum_pct"] = 5.0
    stricter = grade_symbol_v2_shadow(
        symbol_payload(), candidate_payload(), "risk_on", changed
    )
    assert stricter["score_v2_shadow"] < baseline["score_v2_shadow"]


def test_apply_shadow_grades_keeps_official_routing_on_v1(tmp_path: Path) -> None:
    policy_dir = tmp_path / "data" / "chatgpt"
    policy_dir.mkdir(parents=True)
    for name in (
        "qullamaggie-grading-policy-v1.json",
        "qullamaggie-grading-policy-v2.json",
    ):
        (policy_dir / name).write_text(
            (ROOT / "data" / "chatgpt" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    candidate = candidate_payload()
    summary = {
        "report_date": "2026-07-27",
        "generated_report_date": "2026-07-27",
        "as_of_date": "2026-07-27",
        "market_data_date": "2026-07-27",
        "generated_at": "2026-07-27T23:55:00+08:00",
        "qullamaggie": {
            "market_regime": {"status": "risk_on"},
            "top_candidates": [candidate],
            "candidates": {"breakout": [candidate]},
        },
    }
    symbols = {"2330": symbol_payload()}
    report = apply_shadow_grades(
        tmp_path, symbols, [candidate], summary, "risk_on"
    )

    assert report["routing"]["watchlist_policy"] == "v1"
    assert report["routing"]["tradeplan_policy"] == "v1"
    assert report["routing"]["v2_may_drive_business_writes"] is False
    for field in (
        "grade_v1",
        "score_v1",
        "grade_v2_shadow",
        "score_v2_shadow",
        "grade_difference",
        "v2_rejection_reasons",
    ):
        assert field in symbols["2330"]
        assert field in candidate


def test_shadow_history_index_requires_20_real_daily_files(tmp_path: Path) -> None:
    for day in range(1, 21):
        date_value = f"2026-07-{day:02d}"
        payload = {
            "schema_version": "1.0",
            "market_data_date": date_value,
            "routing": {
                "watchlist_policy": "v1",
                "tradeplan_policy": "v1",
                "v2_may_drive_business_writes": False,
            },
            "comparisons": [{"symbol": "2330"}],
        }
        write_json(shadow_history_path(tmp_path, date_value), payload)

    index = build_shadow_history_index(
        tmp_path, "2026-07-27T23:55:00+08:00"
    )
    assert index["available_valid_days"] == 20
    assert index["has_20d_shadow_history"] is True
    assert len(index["latest_20_trading_days"]) == 20


def test_shadow_history_does_not_count_invalid_or_missing_days(tmp_path: Path) -> None:
    path = shadow_history_path(tmp_path, "2026-07-01")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"market_data_date": "2026-07-01"}), encoding="utf-8")
    index = build_shadow_history_index(tmp_path, "2026-07-27T23:55:00+08:00")
    assert index["available_valid_days"] == 0
    assert index["has_20d_shadow_history"] is False
    assert index["limitations"]
