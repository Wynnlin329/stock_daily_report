from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from stock_health.episodic_pivot import (
    calculate_episodic_pivot,
    load_episodic_pivot_policy,
    validate_episodic_pivot_policy,
)
from stock_health.models import MopsEventRecord, OhlcvRecord
from stock_health.qullamaggie import calculate_qullamaggie_signals
from stock_health.screening import build_screening_summary


ROOT = Path(__file__).resolve().parents[1]


def record(
    day: date,
    *,
    close: float = 100.0,
    open_price: float | None = None,
    volume: int = 1_000,
    change_pct: float = 0.0,
) -> OhlcvRecord:
    open_value = close if open_price is None else open_price
    return OhlcvRecord(
        date=day.isoformat(),
        symbol="2330",
        name="台積電",
        market="listed",
        open=open_value,
        high=max(open_value, close) + 1,
        low=min(open_value, close) - 1,
        close=close,
        change=close * change_pct / 100,
        change_pct=change_pct,
        volume=volume,
        turnover=200_000_000,
        transactions=1_000,
        source="TWSE",
    )


def history(
    *,
    days: int = 127,
    closes: list[float] | None = None,
) -> list[OhlcvRecord]:
    start = date(2025, 12, 1)
    values = closes or [100.0] * days
    return [
        record(start + timedelta(days=index), close=close)
        for index, close in enumerate(values)
    ]


def current_after(rows: list[OhlcvRecord], **overrides: object) -> OhlcvRecord:
    day = date.fromisoformat(rows[-1].date) + timedelta(days=1)
    values = {
        "close": 108.0,
        "open_price": 105.0,
        "volume": 3_000,
        "change_pct": 8.0,
    }
    values.update(overrides)
    return record(day, **values)  # type: ignore[arg-type]


def mops_event(
    current: OhlcvRecord,
    *,
    days_before: int = 1,
    event_time: str = "18:01",
) -> MopsEventRecord:
    event_day = date.fromisoformat(current.date) - timedelta(days=days_before)
    return MopsEventRecord(
        date=event_day.isoformat(),
        time=event_time,
        symbol=current.symbol,
        name=current.name,
        market=current.market,
        title="公告重大合約",
        category="重大合約",
        summary="事件存在，方向需另行驗證",
        url=None,
        source="MOPS",
    )


def mops_context(current: OhlcvRecord, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "requested_date": current.date,
        "data_date": current.date,
        "status": "success",
        "source_endpoint": "ajax_t05st01",
        "date_validation": "matched",
    }
    payload.update(overrides)
    return payload


def test_policy_is_valid_and_forbids_breakout_score_reuse() -> None:
    policy = load_episodic_pivot_policy(ROOT)
    assert validate_episodic_pivot_policy(policy) == []
    assert policy["scoring"]["breakout_score_reuse_forbidden"] is True
    assert policy["event_interpretation"][
        "event_existence_is_separate_from_direction"
    ] is True

    invalid = deepcopy(policy)
    invalid["scoring"]["breakout_score_reuse_forbidden"] = False
    assert "breakout_score_reuse_must_be_forbidden" in (
        validate_episodic_pivot_policy(invalid)
    )


def test_valid_ep_uses_verified_event_repricing_and_abnormal_volume() -> None:
    rows = history()
    current = current_after(rows)
    result = calculate_episodic_pivot(
        current,
        rows,
        [mops_event(current)],
        mops_context(current),
        load_episodic_pivot_policy(ROOT),
    )

    assert result["gap_pct"] == 5.0
    assert result["open_vs_prior_close_pct"] == 5.0
    assert result["daily_volume_ratio"] == 3.0
    assert result["catalyst_type"] == "重大合約"
    assert result["catalyst_source"] == "MOPS"
    assert result["catalyst_event_verified"] is True
    assert result["mops_data_date_matches_analysis_date"] is True
    assert result["ep_quality_score"] == 100
    assert result["ep_status"] == "valid_ep"
    assert result["ep_rejection_reasons"] == []


def test_unavailable_intraday_financial_and_direction_fields_remain_null() -> None:
    rows = history()
    current = current_after(rows)
    result = calculate_episodic_pivot(
        current,
        rows,
        [mops_event(current)],
        mops_context(current),
    )

    for field in (
        "volume_first_15m_ratio",
        "volume_first_30m_ratio",
        "opening_range_high",
        "opening_range_low",
        "catalyst_surprise_score",
        "revenue_growth_yoy",
        "eps_growth_yoy",
        "catalyst_direction",
    ):
        assert result[field] is None
    assert result["catalyst_direction_interpreted"] is False
    assert result["ep_basis"]["event_direction_inferred"] is False
    assert result["ep_missing_reason"]["catalyst_surprise_score"] == (
        "directional_event_surprise_not_available"
    )


def test_mops_date_mismatch_is_insufficient_data() -> None:
    rows = history()
    current = current_after(rows)
    result = calculate_episodic_pivot(
        current,
        rows,
        [mops_event(current)],
        mops_context(current, data_date="2026-01-01", date_validation="mismatch"),
    )

    assert result["ep_status"] == "insufficient_data"
    assert result["ep_quality_score"] is None
    assert "mops_data_date_not_verified_for_analysis_date" in (
        result["ep_rejection_reasons"]
    )


def test_missing_history_is_insufficient_instead_of_zero_scored() -> None:
    rows = history(days=10)
    current = current_after(rows)
    result = calculate_episodic_pivot(
        current,
        rows,
        [mops_event(current)],
        mops_context(current),
    )

    assert result["ep_status"] == "insufficient_data"
    assert result["ep_quality_score"] is None
    assert result["prior_3m_extension_pct"] is None
    assert result["prior_6m_extension_pct"] is None
    assert result["ep_score_breakdown"] == {}


def test_three_month_history_is_sufficient_when_six_month_is_unavailable() -> None:
    rows = history(days=64)
    current = current_after(rows)
    result = calculate_episodic_pivot(
        current,
        rows,
        [mops_event(current)],
        mops_context(current),
    )

    assert result["prior_3m_extension_pct"] == 0.0
    assert result["prior_6m_extension_pct"] is None
    assert result["ep_status"] == "valid_ep"
    assert result["ep_quality_score"] == 100
    assert result["ep_missing_reason"]["prior_6m_extension_pct"].startswith(
        "insufficient_valid_trading_days:"
    )


def test_missing_catalyst_is_rejected_with_complete_market_data() -> None:
    rows = history()
    current = current_after(rows)
    result = calculate_episodic_pivot(
        current,
        rows,
        [],
        mops_context(current),
    )

    assert result["ep_status"] == "rejected"
    assert result["ep_quality_score"] == 60
    assert "no_verified_mops_catalyst_in_allowed_window" in (
        result["ep_rejection_reasons"]
    )


def test_confirmed_empty_mops_date_is_complete_but_has_no_catalyst() -> None:
    rows = history()
    current = current_after(rows)
    result = calculate_episodic_pivot(
        current,
        rows,
        [],
        mops_context(
            current,
            status="empty_but_valid",
            date_validation="query_confirmed_empty",
        ),
    )

    assert result["mops_data_date_matches_analysis_date"] is True
    assert result["ep_status"] == "rejected"
    assert result["ep_quality_score"] == 60


def test_ordinary_news_reaction_without_repricing_is_rejected() -> None:
    rows = history()
    current = current_after(
        rows,
        close=102.0,
        open_price=101.0,
        change_pct=2.0,
    )
    result = calculate_episodic_pivot(
        current,
        rows,
        [mops_event(current)],
        mops_context(current),
    )

    assert result["ep_status"] == "rejected"
    assert "no_material_gap_or_repricing" in result["ep_rejection_reasons"]


def test_low_volume_repricing_is_rejected() -> None:
    rows = history()
    current = current_after(rows, volume=1_500)
    result = calculate_episodic_pivot(
        current,
        rows,
        [mops_event(current)],
        mops_context(current),
    )

    assert result["daily_volume_ratio"] == 1.5
    assert result["ep_status"] == "rejected"
    assert "daily_volume_ratio_below_threshold" in (
        result["ep_rejection_reasons"]
    )


def test_high_open_with_weak_close_is_rejected() -> None:
    rows = history()
    current = current_after(
        rows,
        close=105.0,
        open_price=110.0,
        change_pct=5.0,
    )
    result = calculate_episodic_pivot(
        current,
        rows,
        [mops_event(current)],
        mops_context(current),
    )

    assert result["gap_pct"] == 10.0
    assert result["ep_close_location_pct"] < 60
    assert result["ep_status"] == "rejected"
    assert "weak_close_after_repricing" in result["ep_rejection_reasons"]


def test_terminal_gap_after_extended_run_is_rejected() -> None:
    closes = [100.0] * 64 + [170.0] * 63
    rows = history(closes=closes)
    current = current_after(
        rows,
        close=190.0,
        open_price=187.0,
        change_pct=11.76,
    )
    result = calculate_episodic_pivot(
        current,
        rows,
        [mops_event(current)],
        mops_context(current),
    )

    assert result["prior_3m_extension_pct"] == 70.0
    assert result["gap_pct"] == 10.0
    assert result["ep_status"] == "rejected"
    assert "possible_terminal_gap_after_extended_run" in (
        result["ep_rejection_reasons"]
    )


def test_future_and_after_close_same_day_events_are_not_used() -> None:
    rows = history()
    current = current_after(rows)
    future = mops_event(current, days_before=-1)
    after_close = mops_event(current, days_before=0, event_time="18:01")
    result = calculate_episodic_pivot(
        current,
        rows,
        [future, after_close],
        mops_context(current),
    )

    assert result["catalyst_event_verified"] is False
    assert result["catalyst_date"] is None
    assert "no_verified_mops_catalyst_in_allowed_window" in (
        result["ep_rejection_reasons"]
    )


def test_qullamaggie_routes_valid_ep_to_independent_score() -> None:
    rows = history()
    current = current_after(rows)
    history_rows = {row.date: [row] for row in rows}
    result = calculate_qullamaggie_signals(
        [current],
        history_rows,
        benchmark_history={"listed": [100.0 + index for index in range(60)]},
        mops_events_by_symbol={current.symbol: [mops_event(current)]},
        mops_context=mops_context(current),
    )

    candidate = result["candidates"]["episodic_pivot"][0]
    assert candidate["setup_type"] == "episodic_pivot"
    assert candidate["ep_status"] == "valid_ep"
    assert candidate["scoring_model"] == "episodic_pivot_v1"
    assert candidate["qullamaggie_score"] == candidate["ep_quality_score"]
    assert set(candidate["score_breakdown"]) == {
        "verified_catalyst",
        "repricing",
        "abnormal_volume",
        "catalyst_timing",
        "extension_quality",
    }
    assert "market_regime" in candidate["general_score_breakdown"]
    assert result["episodic_pivot_coverage"]["breakout_score_reused"] is False


def test_screening_passes_verified_mops_payload_date_into_ep() -> None:
    rows = history()
    current = current_after(rows)
    event = mops_event(current)
    history_rows = {row.date: [row] for row in rows}
    summary = build_screening_summary(
        current.date,
        f"{current.date}T23:55:00+08:00",
        [current],
        [],
        history_rows,
        {},
        False,
        [],
        "medium",
        mops_event_rows=[event],
        mops_event_history_payloads={
            current.date: {
                **mops_context(current),
                "events": [event.__dict__],
            }
        },
        mops_events_status="success",
        history_index={
            "available_trading_days": len(rows),
            "has_20d_history": True,
            "has_60d_history": True,
        },
    )

    candidate = summary["qullamaggie"]["candidates"]["episodic_pivot"][0]
    assert candidate["mops_data_date"] == current.date
    assert candidate["mops_date_validation"] == "matched"
    assert candidate["mops_data_date_matches_analysis_date"] is True
    assert candidate["catalyst_event_verified"] is True
