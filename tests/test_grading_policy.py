from __future__ import annotations

import json
from pathlib import Path

import pytest

from stock_health.grading_policy import grade_symbol, load_grading_policy, validate_grading_policy


ROOT = Path(__file__).resolve().parents[1]


def symbol_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "2330",
        "scan_eligible": True,
        "data_quality": {"ohlcv_complete": True, "technical_indicators_complete": True},
        "close": 100.0,
        "ma10": 95.0,
        "ma20": 90.0,
        "ma50": 80.0,
        "avg_volume_20d": 400_000.0,
        "volume_ratio_20d": 1.6,
        "pivot_price": 99.0,
        "stop_reference": 94.0,
        "setup_type": "breakout",
        "extended_risk": False,
        "risk_notes": [],
    }
    payload.update(overrides)
    return payload


def candidate_payload(relative_strength_rank: float = 95.0, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "symbol": "2330",
        "relative_strength_rank": relative_strength_rank,
        "score": 0,
    }
    payload.update(overrides)
    return payload


def test_policy_json_structure_weights_thresholds_and_caps() -> None:
    policy = load_grading_policy(ROOT)
    assert validate_grading_policy(policy) == []
    assert policy["policy_id"] == "qullamaggie-grading-policy"
    assert policy["version"] == "1.0.0"
    assert sum(policy["scoring"]["weights"].values()) == 100
    assert [item["grade"] for item in policy["grade_thresholds"]["ordered_descending"]] == ["A", "A-", "B", "C"]
    assert all(cap["maximum_grade"] in policy["supported_grades"] for cap in policy["grade_caps"])


def test_complete_high_quality_candidate_is_a() -> None:
    result = grade_symbol(symbol_payload(), candidate_payload(), "risk_on", load_grading_policy(ROOT))
    assert result["grade_score_v1"] == 100
    assert result["preliminary_grade"] == "A"
    assert result["final_grade"] == "A"
    assert result["action_status"] == "tradeplan_eligible"


def test_single_minor_defect_candidate_is_a_minus() -> None:
    result = grade_symbol(symbol_payload(), candidate_payload(82.0), "risk_on", load_grading_policy(ROOT))
    assert result["grade_score_v1"] == 97
    assert result["final_grade"] == "A-"
    assert result["minor_defects"] == ["relative_strength_75_to_below_85"]
    assert result["major_defects"] == []


def test_immature_anticipation_is_b_with_upgrade_path() -> None:
    payload = symbol_payload(
        setup_type="anticipation",
        close=94.0,
        ma10=90.0,
        ma20=85.0,
        ma50=80.0,
        pivot_price=100.0,
        stop_reference=92.0,
    )
    result = grade_symbol(payload, candidate_payload(), "risk_on", load_grading_policy(ROOT))
    assert result["preliminary_grade"] == "A-"
    assert result["final_grade"] == "B"
    assert "anticipation_distance_over_5_cap_b" in result["applied_caps"]
    assert result["upgrade_requirements"]


@pytest.mark.parametrize(
    ("setup_type", "extended_risk", "expected_cap"),
    [
        ("extended_watch", True, "extended_risk_cap_c"),
        ("failed_breakout", False, "failed_breakout_cap_c"),
    ],
)
def test_extended_or_failed_breakout_is_c(setup_type: str, extended_risk: bool, expected_cap: str) -> None:
    payload = symbol_payload(setup_type=setup_type, extended_risk=extended_risk)
    result = grade_symbol(payload, candidate_payload(), "risk_on", load_grading_policy(ROOT))
    assert result["final_grade"] == "C"
    assert expected_cap in result["applied_caps"]


def test_required_null_is_ungraded_and_never_scored_as_zero() -> None:
    payload = symbol_payload(ma50=None)
    result = grade_symbol(payload, candidate_payload(), "risk_on", load_grading_policy(ROOT))
    assert result["final_grade"] == "Ungraded"
    assert result["grade_score_v1"] is None
    assert result["component_scores"] == {}
    assert result["missing_fields"] == ["ma50"]


def test_scan_ineligible_is_eliminated_before_quality_scoring() -> None:
    result = grade_symbol({"scan_eligible": False, "setup_type": "insufficient_data"}, {}, "risk_on", load_grading_policy(ROOT))
    assert result["final_grade"] == "Eliminated"
    assert result["grade_score_v1"] is None
    assert result["action_status"] == "not_applicable"


def test_invalid_stop_reference_is_ungraded() -> None:
    result = grade_symbol(
        symbol_payload(stop_reference=100.0), candidate_payload(), "risk_on", load_grading_policy(ROOT)
    )
    assert result["final_grade"] == "Ungraded"
    assert result["grade_score_v1"] is None
    assert "stop_reference_must_be_below_entry_reference" in result["data_errors"]


def test_relative_strength_below_60_is_c_even_when_raw_score_is_high() -> None:
    result = grade_symbol(symbol_payload(), candidate_payload(59.0), "risk_on", load_grading_policy(ROOT))
    assert result["grade_score_v1"] >= 60
    assert result["final_grade"] == "C"
    assert "relative_strength_below_60_cap_c" in result["applied_caps"]


def test_risk_off_keeps_a_grade_but_blocks_action() -> None:
    result = grade_symbol(symbol_payload(), candidate_payload(), "risk_off", load_grading_policy(ROOT))
    assert result["final_grade"] == "A"
    assert result["market_gate"] == "blocked"
    assert result["action_status"] == "blocked_market"
    assert result["block_reason"] == "market_regime_risk_off"


def test_existing_scan_score_is_not_used_for_grade_score() -> None:
    policy = load_grading_policy(ROOT)
    low_scan_score = grade_symbol(symbol_payload(score=0), candidate_payload(score=0), "risk_on", policy)
    high_scan_score = grade_symbol(symbol_payload(score=999), candidate_payload(score=999), "risk_on", policy)
    assert low_scan_score["grade_score_v1"] == high_scan_score["grade_score_v1"] == 100
    assert low_scan_score["final_grade"] == high_scan_score["final_grade"] == "A"


def test_output_contract_is_complete() -> None:
    policy = load_grading_policy(ROOT)
    result = grade_symbol(symbol_payload(), candidate_payload(), "neutral", policy)
    assert set(policy["output_contract"]["required_fields"]).issubset(result)


def test_dry_run_maps_at_least_five_current_symbol_json_files() -> None:
    policy = load_grading_policy(ROOT)
    daily = json.loads((ROOT / "data/chatgpt/daily-qullamaggie-source-compact.json").read_text(encoding="utf-8"))
    candidates: list[dict[str, object]] = []
    seen: set[str] = set()
    for group in ("top_candidates", "breakout", "episodic_pivot", "anticipation", "extended_watch", "failed_breakout"):
        for candidate in daily.get(group, []):
            symbol = str(candidate.get("symbol", ""))
            if symbol and symbol not in seen and (ROOT / f"data/chatgpt/symbols/{symbol}.json").exists():
                seen.add(symbol)
                candidates.append(candidate)
    assert len(candidates) >= 5

    market_regime = daily["market_context"]["market_regime"]["status"]
    for candidate in candidates[:5]:
        symbol = str(candidate["symbol"])
        symbol_data = json.loads((ROOT / f"data/chatgpt/symbols/{symbol}.json").read_text(encoding="utf-8"))
        result = grade_symbol(symbol_data, candidate, market_regime, policy)
        assert result["final_grade"] in policy["supported_grades"]
        assert result["final_grade"] != "Eliminated"
        assert set(policy["output_contract"]["required_fields"]).issubset(result)
