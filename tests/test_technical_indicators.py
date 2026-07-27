from __future__ import annotations

from datetime import date, timedelta

from stock_health.models import OhlcvRecord
from stock_health.qullamaggie import calculate_qullamaggie_candidate_payloads, score_qullamaggie_candidate
from stock_health.technical_indicators import (
    apply_multi_period_rs_ranks,
    calculate_enhanced_technical_metrics,
)


def make_record(
    day: date,
    *,
    symbol: str = "2330",
    close: float = 100.0,
    high: float = 103.0,
    low: float = 97.0,
    volume: int = 1_000,
) -> OhlcvRecord:
    return OhlcvRecord(
        date=day.isoformat(),
        symbol=symbol,
        name=f"{symbol}公司",
        market="listed",
        open=100.0,
        high=high,
        low=low,
        close=close,
        change=0.0,
        change_pct=0.0,
        volume=volume,
        turnover=100_000_000,
        transactions=100,
        source="TWSE",
        security_type="common_stock",
        is_common_stock=True,
        scan_eligible=True,
    )


def valid_history(days: int, *, symbol: str = "2330", close: float = 100.0) -> list[OhlcvRecord]:
    start = date(2025, 1, 1)
    return [make_record(start + timedelta(days=index), symbol=symbol, close=close) for index in range(days)]


def test_adr20_and_sma_atr14_known_values() -> None:
    history = valid_history(20)
    current = make_record(date(2025, 1, 21))

    metrics = calculate_enhanced_technical_metrics(current, history, stop_reference=90.0)

    assert metrics["adr20_pct"] == 6.0
    assert metrics["atr14"] == 6.0
    assert metrics["atr14_pct"] == 6.0
    assert metrics["stop_risk_pct"] == 10.0
    assert metrics["stop_to_adr_ratio"] == 1.6667
    assert metrics["stop_to_atr_ratio"] == 1.6667
    assert metrics["indicator_basis"]["atr_method"] == "sma"


def test_missing_history_outputs_null_and_reason() -> None:
    current = make_record(date(2025, 1, 5))

    metrics = calculate_enhanced_technical_metrics(current, valid_history(4), stop_reference=90.0)

    assert metrics["adr20_pct"] is None
    assert metrics["atr14"] is None
    assert metrics["return_1m"] is None
    assert metrics["return_6m"] is None
    assert metrics["missing_reason"]["adr20_pct"] == "insufficient_valid_trading_days:5/20"
    assert metrics["missing_reason"]["return_6m"] == "insufficient_valid_trading_days:5/127"


def test_suspended_current_row_does_not_reuse_stale_history() -> None:
    current = make_record(date(2025, 2, 1), volume=0)

    metrics = calculate_enhanced_technical_metrics(current, valid_history(130), stop_reference=90.0)

    assert metrics["adr20_pct"] is None
    assert metrics["atr14"] is None
    assert metrics["return_1m"] is None
    assert metrics["stop_risk_pct"] is None
    assert set(metrics["missing_reason"].values()) == {"current_row_invalid_or_suspended"}


def test_missing_and_suspended_history_days_are_skipped() -> None:
    history = valid_history(22)
    history[-1].volume = 0
    history[-2].high = None
    current = make_record(date(2025, 1, 23))

    metrics = calculate_enhanced_technical_metrics(current, history, stop_reference=90.0)

    assert metrics["adr20_pct"] == 6.0
    assert metrics["return_1m"] is None
    assert metrics["missing_reason"]["return_1m"] == "insufficient_valid_trading_days:21/22"


def test_multi_period_rs_cross_section_ranking_and_ties() -> None:
    candidates = [
        _return_candidate("1101", 10.0),
        _return_candidate("2330", 30.0),
        _return_candidate("2317", 20.0),
        _return_candidate("2303", 20.0),
    ]

    apply_multi_period_rs_ranks(candidates)
    by_symbol = {candidate["symbol"]: candidate for candidate in candidates}

    assert by_symbol["1101"]["rs_rank_1m"] == 0.0
    assert by_symbol["2330"]["rs_rank_1m"] == 100.0
    assert by_symbol["2317"]["rs_rank_1m"] == 50.0
    assert by_symbol["2303"]["rs_rank_1m"] == 50.0
    assert by_symbol["2330"]["composite_rs_rank"] == 100.0


def test_multi_period_rs_ranking_is_separated_by_date() -> None:
    older = _return_candidate("1101", 100.0, day="2025-01-30")
    current_low = _return_candidate("2330", 10.0, day="2025-01-31")
    current_high = _return_candidate("2317", 20.0, day="2025-01-31")

    apply_multi_period_rs_ranks([older, current_low, current_high])

    assert older["rs_rank_1m"] == 100.0
    assert current_low["rs_rank_1m"] == 0.0
    assert current_high["rs_rank_1m"] == 100.0


def test_future_history_rows_do_not_affect_returns() -> None:
    current_day = date(2025, 6, 1)
    history_rows: dict[str, list[OhlcvRecord]] = {}
    for row in valid_history(130):
        history_rows.setdefault(row.date, []).append(row)
    future = make_record(date(2025, 6, 2), close=1.0, high=1.1, low=0.9)
    history_rows[future.date] = [future]
    current = make_record(current_day, close=120.0, high=121.0, low=119.0)

    result = calculate_qullamaggie_candidate_payloads([current], history_rows)
    candidate = result["all_candidates"][0]

    assert candidate["return_1m"] == 20.0
    assert candidate["return_3m"] == 20.0
    assert candidate["return_6m"] == 20.0


def test_enhanced_fields_do_not_change_legacy_qullamaggie_score() -> None:
    current = make_record(date(2025, 6, 1), close=120.0, high=121.0, low=119.0)
    history_rows = {
        row.date: [row]
        for row in valid_history(130)
    }
    candidate = calculate_qullamaggie_candidate_payloads([current], history_rows)["all_candidates"][0]
    legacy_candidate = {
        key: value
        for key, value in candidate.items()
        if key
        not in {
            "adr20_pct",
            "atr14",
            "atr14_pct",
            "stop_risk_pct",
            "stop_to_adr_ratio",
            "stop_to_atr_ratio",
            "return_1m",
            "return_3m",
            "return_6m",
            "rs_rank_1m",
            "rs_rank_3m",
            "rs_rank_6m",
            "composite_rs_rank",
            "missing_reason",
            "indicator_basis",
        }
    }

    enhanced_score = score_qullamaggie_candidate(candidate, {"score": 5})
    legacy_score = score_qullamaggie_candidate(legacy_candidate, {"score": 5})

    assert enhanced_score == legacy_score


def _return_candidate(symbol: str, value: float, *, day: str = "2025-01-31") -> dict[str, object]:
    return {
        "symbol": symbol,
        "date": day,
        "scan_eligible": True,
        "return_1m": value,
        "return_3m": value,
        "return_6m": value,
        "rs_rank_1m": None,
        "rs_rank_3m": None,
        "rs_rank_6m": None,
        "composite_rs_rank": None,
        "missing_reason": {},
    }
