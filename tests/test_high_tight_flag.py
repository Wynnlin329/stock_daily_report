from __future__ import annotations

from datetime import date, timedelta

from stock_health.high_tight_flag import calculate_htf_structure
from stock_health.models import OhlcvRecord


def test_valid_prior_run_and_high_tight_contraction() -> None:
    history, current = htf_sample()

    result = calculate_htf_structure(current, history)

    assert result["prior_move_pct_60d"] >= 50
    assert result["flag_duration_days"] == 20
    assert result["flag_depth_pct"] < 15
    assert result["higher_lows_count"] >= 10
    assert result["range_contraction_ratio"] < 0.8
    assert result["volume_contraction_ratio"] < 0.8
    assert result["monthly_above_ma12"] is True
    assert result["weekly_trend_state"] == "uptrend"
    assert result["daily_trigger_state"] == "near_trigger"
    assert result["htf_structure_score"] >= 75
    assert result["htf_structure_status"] == "valid_htf"
    assert result["htf_rejection_reasons"] == []


def test_missing_prior_move_is_developing() -> None:
    history, current = htf_sample(with_prior_move=False)

    result = calculate_htf_structure(current, history)

    assert result["prior_move_pct_60d"] < 50
    assert result["htf_structure_status"] == "developing"
    assert "prior_move_below_threshold" in result["htf_rejection_reasons"]


def test_flag_too_deep_is_rejected_with_raw_depth() -> None:
    history, current = htf_sample()
    history[-10].low = 120.0

    result = calculate_htf_structure(current, history)

    assert result["flag_depth_pct"] > 25
    assert result["htf_structure_status"] == "too_deep"
    assert "flag_depth_exceeds_threshold" in result["htf_rejection_reasons"]


def test_range_expansion_is_too_loose() -> None:
    history, current = htf_sample()
    recent_rows = [*history[-4:], current]
    for index, row in enumerate(recent_rows):
        row.low = 160.0 + index
        row.high = 179.0
        row.close = 176.0
        row.open = 176.0

    result = calculate_htf_structure(current, history)

    assert result["range_contraction_ratio"] > 0.8
    assert result["htf_structure_status"] == "too_loose"
    assert "range_not_contracting" in result["htf_rejection_reasons"]


def test_volume_not_contracting_is_too_loose() -> None:
    history, current = htf_sample()
    for row in [*history[-4:], current]:
        row.volume = 6_000

    result = calculate_htf_structure(current, history)

    assert result["volume_contraction_ratio"] > 0.8
    assert result["htf_structure_status"] == "too_loose"
    assert "volume_not_contracting" in result["htf_rejection_reasons"]


def test_overextended_breakout_is_extended() -> None:
    history, current = htf_sample()
    current.open = 198.0
    current.high = 202.0
    current.low = 197.0
    current.close = 200.0

    result = calculate_htf_structure(current, history)

    assert result["daily_trigger_state"] == "extended"
    assert result["htf_structure_status"] == "extended"


def test_failed_breakout_has_distinct_state() -> None:
    history, current = htf_sample()
    current.high = 185.0
    current.close = 178.0

    result = calculate_htf_structure(current, history)

    assert result["daily_trigger_state"] == "failed_breakout"
    assert result["htf_structure_status"] == "failed_breakout"


def test_insufficient_history_keeps_auditable_nulls() -> None:
    history, current = short_sample()

    result = calculate_htf_structure(current, history)

    assert result["distance_to_52w_high_pct"] is None
    assert result["monthly_above_ma12"] is None
    assert result["weekly_trend_state"] is None
    assert result["htf_structure_status"] == "insufficient_data"
    assert result["htf_missing_reason"]["distance_to_52w_high_pct"].startswith(
        "insufficient_valid_trading_days"
    )


def test_isolated_price_outlier_is_excluded_and_reported() -> None:
    history, current = htf_sample()
    outlier = history[100]
    outlier.open /= 10
    outlier.high /= 10
    outlier.low /= 10
    outlier.close /= 10

    result = calculate_htf_structure(current, history)

    assert result["prior_move_pct_60d"] < 100
    assert result["htf_data_quality"]["excluded_isolated_price_outlier_dates"] == [outlier.date]


def htf_sample(*, with_prior_move: bool = True) -> tuple[list[OhlcvRecord], OhlcvRecord]:
    days = business_days(299)
    history: list[OhlcvRecord] = []
    for index, day in enumerate(days[:240]):
        close = 50.0 + 50.0 * index / 239 if with_prior_move else 100.0
        history.append(record(day, close, close * 1.01, close * 0.99, 3_000))
    for index, day in enumerate(days[240:280]):
        close = 100.0 + 80.0 * index / 39 if with_prior_move else 100.0
        history.append(record(day, close, close * 1.01, close * 0.99, 5_000))
    peak = 180.0 if with_prior_move else 102.0
    floor = 165.0 if with_prior_move else 96.0
    for index, day in enumerate(days[280:298]):
        low = floor + (peak - floor - 6.0) * index / 17
        high = peak - 2.0 * index / 17
        close = (low + high) / 2
        history.append(record(day, close, high, low, int(1_800 - 700 * index / 17)))
    current_close = 178.0 if with_prior_move else 100.0
    current = record(
        days[298],
        current_close,
        179.0 if with_prior_move else 101.0,
        175.0 if with_prior_move else 98.0,
        900,
    )
    return history, current


def short_sample() -> tuple[list[OhlcvRecord], OhlcvRecord]:
    days = business_days(31)
    history = [
        record(day, 100.0 + index, 102.0 + index, 99.0 + index, 1_000)
        for index, day in enumerate(days[:-1])
    ]
    return history, record(days[-1], 131.0, 132.0, 130.0, 1_000)


def business_days(count: int) -> list[date]:
    current = date(2025, 1, 1)
    output: list[date] = []
    while len(output) < count:
        if current.weekday() < 5:
            output.append(current)
        current += timedelta(days=1)
    return output


def record(
    day: date,
    close: float,
    high: float,
    low: float,
    volume: int,
) -> OhlcvRecord:
    return OhlcvRecord(
        date=day.isoformat(),
        symbol="2330",
        name="測試公司",
        market="listed",
        open=close,
        high=high,
        low=low,
        close=close,
        change=0.0,
        change_pct=0.0,
        volume=volume,
        turnover=int(close * volume),
        transactions=100,
        source="TWSE",
        security_type="common_stock",
        is_common_stock=True,
        scan_eligible=True,
    )
