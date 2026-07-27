from __future__ import annotations

import json
from datetime import date, timedelta

from stock_health.models import InstitutionalTradingRecord, MopsEventRecord, OhlcvRecord
from stock_health.qullamaggie import calculate_market_regime, calculate_qullamaggie_signals
from stock_health.screening import build_screening_summary


def make_record(
    day: date,
    symbol: str = "2330",
    name: str | None = None,
    close: float = 95.0,
    high: float = 100.0,
    low: float = 95.0,
    volume: int = 1000,
    turnover: int = 80_000_000,
    market: str = "listed",
) -> OhlcvRecord:
    return OhlcvRecord(
        date=day.isoformat(),
        symbol=symbol,
        name=name or f"{symbol}公司",
        market=market,
        open=close - 1,
        high=high,
        low=low,
        close=close,
        change=1.0,
        change_pct=1.0,
        volume=volume,
        turnover=turnover,
        transactions=100,
        source="TWSE" if market == "listed" else "TPEx",
    )


def history_for(symbol: str = "2330", days: int = 60, close: float = 95.0, high: float = 100.0, low: float = 95.0, volume: int = 1000, turnover: int = 80_000_000) -> dict[str, list[OhlcvRecord]]:
    start = date(2026, 3, 1)
    output: dict[str, list[OhlcvRecord]] = {}
    for offset in range(days):
        day = start + timedelta(days=offset)
        output[day.isoformat()] = [make_record(day, symbol=symbol, close=close, high=high, low=low, volume=volume, turnover=turnover)]
    return output


def first_candidate(result: dict, setup_type: str) -> dict:
    return result["candidates"][setup_type][0]


def make_mops_event(symbol: str = "2330", title: str = "公告重大合約", category: str = "重大合約") -> MopsEventRecord:
    return MopsEventRecord(
        date="2026-06-15",
        time="18:01",
        symbol=symbol,
        name=f"{symbol}公司",
        market=None,
        title=title,
        category=category,
        summary="重大訊息摘要",
        url=None,
        source="MOPS",
    )


def test_qullamaggie_prior_high_uses_history_only_no_lookahead() -> None:
    history = history_for(high=100.0)
    current = make_record(date(2026, 6, 15), close=105.0, high=200.0, low=104.0, volume=2000, turnover=200_000_000)
    result = calculate_qullamaggie_signals([current], history, {"listed": [100 + i for i in range(61)]})
    candidate = [candidate for group in result["candidates"].values() for candidate in group if candidate["symbol"] == "2330"][0]
    assert candidate["prior_20d_high"] == 100.0
    assert candidate["prior_60d_high"] == 100.0
    assert candidate["new_high_20d"] is True
    assert candidate["new_high_60d"] is True


def test_qullamaggie_insufficient_history_setup() -> None:
    current = make_record(date(2026, 6, 15), close=105.0, high=106.0, low=100.0)
    result = calculate_qullamaggie_signals([current], history_for(days=10), {"listed": [100 + i for i in range(61)]})
    candidate = first_candidate(result, "insufficient_data")
    assert candidate["setup_type"] == "insufficient_data"
    assert candidate["volume_ratio_20d"] is None


def test_qullamaggie_volume_close_location_distance_and_risk_metrics() -> None:
    current = make_record(date(2026, 6, 15), close=102.0, high=103.0, low=99.0, volume=3000, turnover=200_000_000)
    result = calculate_qullamaggie_signals([current], history_for(), {"listed": [100 + i for i in range(61)]})
    candidate = result["top_candidates"][0]
    assert candidate["volume_ratio_20d"] == 3.0
    assert candidate["close_location_pct"] == 75.0
    assert candidate["close_near_high"] is True
    assert candidate["distance_to_pivot_pct"] == 2.0
    assert candidate["extended_risk"] is False
    assert candidate["risk_to_stop_pct"] == round((102.0 / 95.0 - 1) * 100, 4)


def test_qullamaggie_breakout_classification() -> None:
    current = make_record(date(2026, 6, 15), close=102.0, high=103.0, low=99.0, volume=3000, turnover=200_000_000)
    result = calculate_qullamaggie_signals([current], history_for(), {"listed": [100 + i for i in range(61)]})
    candidate = first_candidate(result, "breakout")
    assert candidate["setup_type"] == "breakout"
    assert 0 <= candidate["qullamaggie_score"] <= 100


def test_market_regime_insufficient_data_when_index_history_under_50d() -> None:
    result = calculate_market_regime({"listed": [100.0 + index for index in range(49)]})
    assert result["status"] == "insufficient_data"


def test_market_regime_risk_on_neutral_and_risk_off_rules() -> None:
    risk_on = calculate_market_regime({"listed": [100.0 + index for index in range(60)]})
    risk_off = calculate_market_regime({"listed": [160.0 - index for index in range(60)]})
    neutral = calculate_market_regime({"listed": [100.0] * 60})
    assert risk_on["status"] == "risk_on"
    assert risk_on["metrics"]["listed"]["return_20d_pct"] > 0
    assert risk_off["status"] == "risk_off"
    assert risk_off["metrics"]["listed"]["return_20d_pct"] < 0
    assert neutral["status"] == "neutral"


def test_qullamaggie_anticipation_classification() -> None:
    history = history_for()
    # Force contraction: older ranges are wider than the latest ranges.
    for index, rows in enumerate(history.values()):
        row = rows[0]
        if index < 45:
            row.high = 102.0
            row.low = 90.0
        else:
            row.high = 100.0
            row.low = 97.0
    current = make_record(date(2026, 6, 15), close=99.0, high=100.0, low=98.5, volume=1200, turnover=200_000_000)
    result = calculate_qullamaggie_signals([current], history, {"listed": [100 + i for i in range(61)]})
    candidate = first_candidate(result, "anticipation")
    assert candidate["setup_type"] == "anticipation"
    assert candidate["range_contraction"] is True


def test_qullamaggie_extended_watch_classification() -> None:
    current = make_record(date(2026, 6, 15), close=112.0, high=113.0, low=110.0, volume=3000, turnover=250_000_000)
    result = calculate_qullamaggie_signals([current], history_for(), {"listed": [100 + i for i in range(61)]})
    candidate = first_candidate(result, "extended_watch")
    assert candidate["setup_type"] == "extended_watch"
    assert candidate["extended_risk"] is True


def test_qullamaggie_failed_breakout_classification() -> None:
    current = make_record(date(2026, 6, 15), close=99.0, high=101.0, low=98.0, volume=3000, turnover=200_000_000)
    result = calculate_qullamaggie_signals([current], history_for(), {"listed": [100 + i for i in range(61)]})
    candidate = first_candidate(result, "failed_breakout")
    assert candidate["setup_type"] == "failed_breakout"


def test_qullamaggie_relative_strength_values_and_rank() -> None:
    history = history_for(symbol="2330", close=100.0)
    other_history = history_for(symbol="2317", close=100.0)
    for day, rows in other_history.items():
        history.setdefault(day, []).extend(rows)
    current_strong = make_record(date(2026, 6, 15), symbol="2330", close=130.0, high=131.0, low=125.0, volume=3000, turnover=250_000_000)
    current_weak = make_record(date(2026, 6, 15), symbol="2317", close=105.0, high=106.0, low=101.0, volume=3000, turnover=250_000_000)
    result = calculate_qullamaggie_signals([current_strong, current_weak], history, {"listed": [100.0] * 61})
    candidates = {item["symbol"]: item for group in result["candidates"].values() for item in group}
    assert candidates["2330"]["relative_strength_20d"] == 30.0
    assert candidates["2330"]["relative_strength_60d"] == 30.0
    assert candidates["2330"]["relative_strength_rank"] == 100.0
    assert candidates["2317"]["relative_strength_rank"] == 0.0
    assert candidates["2330"]["relative_strength_rank_basis"] == "scan_eligible_common_stock"
    assert "相對強弱排名資料不足" not in candidates["2330"]["risk_notes"]
    assert "相對強弱排名資料不足" not in candidates["2317"]["risk_notes"]


def test_qullamaggie_json_fields_and_no_trading_advice_text() -> None:
    current = make_record(date(2026, 6, 15), close=102.0, high=103.0, low=99.0, volume=3000, turnover=200_000_000)
    summary = build_screening_summary(
        "2026-06-15",
        "2026-06-15T18:15:00+08:00",
        [current],
        [],
        history_for(),
        {},
        False,
        ["institutional_trading"],
        "low",
    )
    payload = json.loads(json.dumps(summary, ensure_ascii=False))
    candidate = payload["qullamaggie"]["top_candidates"][0]
    required = {
        "symbol",
        "name",
        "market",
        "setup_type",
        "qullamaggie_score",
        "score_breakdown",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "ma10",
        "avg_volume_20d",
        "volume_ratio_20d",
        "prior_20d_high",
        "pivot_price",
        "relative_strength_rank",
        "risk_to_stop_pct",
        "prior_move_pct_20d",
        "prior_move_pct_60d",
        "distance_to_52w_high_pct",
        "flag_duration_days",
        "flag_depth_pct",
        "higher_lows_count",
        "range_contraction_ratio",
        "volume_contraction_ratio",
        "ma10_slope",
        "ma20_slope",
        "distance_to_ma10_pct",
        "distance_to_ma20_pct",
        "monthly_above_ma12",
        "weekly_trend_state",
        "daily_trigger_state",
        "htf_structure_score",
        "htf_structure_status",
        "htf_rejection_reasons",
        "setup_reasons",
        "risk_notes",
    }
    assert required.issubset(candidate)
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in ["買進", "賣出", "目標價", "停損價"]:
        assert forbidden not in serialized


def test_qullamaggie_candidates_exclude_scan_ineligible_rows() -> None:
    current_common = make_record(date(2026, 6, 15), symbol="2330", close=102.0, high=103.0, low=99.0, volume=3000, turnover=200_000_000)
    current_etf = make_record(date(2026, 6, 15), symbol="0050", name="元大台灣50", close=200.0, high=201.0, low=198.0, volume=9000, turnover=900_000_000)
    result = calculate_qullamaggie_signals([current_common, current_etf], history_for(), {"listed": [100 + i for i in range(61)]})
    all_candidates = [candidate for group in result["candidates"].values() for candidate in group]
    assert current_etf.scan_eligible is False
    assert all(candidate["symbol"] != "0050" for candidate in all_candidates)
    assert all(candidate["symbol"] != "0050" for candidate in result["top_candidates"])
    assert any("scan_eligible=true" in limitation for limitation in result["limitations"])


def test_qullamaggie_candidate_includes_institutional_confirmation() -> None:
    current = make_record(date(2026, 6, 15), close=102.0, high=103.0, low=99.0, volume=3000, turnover=200_000_000)
    institutional = InstitutionalTradingRecord(
        date="2026-06-15",
        symbol="2330",
        name="2330公司",
        market="listed",
        foreign_buy=None,
        foreign_sell=None,
        foreign_net_buy=1000,
        investment_trust_buy=None,
        investment_trust_sell=None,
        investment_trust_net_buy=500,
        dealer_buy=None,
        dealer_sell=None,
        dealer_net_buy=-100,
        institutional_net_buy=1400,
        source="TWSE",
    )
    result = calculate_qullamaggie_signals(
        [current],
        history_for(),
        {"listed": [100 + i for i in range(61)]},
        institutional_by_symbol={"2330": institutional},
    )
    candidate = result["top_candidates"][0]
    assert candidate["institutional_confirmation"] is True
    assert candidate["institutional_net_buy"] == 1400
    assert "法人買超" in candidate["tags"]
    assert "TWSE" in candidate["source_refs"]


def test_qullamaggie_candidate_includes_margin_short_fields() -> None:
    current = make_record(date(2026, 6, 15), close=102.0, high=103.0, low=99.0, volume=3000, turnover=200_000_000)
    margin_short = {
        "margin_balance": 1000,
        "margin_change": 120,
        "short_balance": 50,
        "short_change": 20,
        "margin_balance_ratio_20d": 1.5,
        "short_balance_ratio_20d": 2.0,
        "source": "TWSE",
    }
    result = calculate_qullamaggie_signals(
        [current],
        history_for(),
        {"listed": [100 + i for i in range(61)]},
        margin_short_by_symbol={"2330": margin_short},
        margin_short_attention_symbols={"2330"},
    )
    candidate = result["top_candidates"][0]
    assert candidate["margin_balance"] == 1000
    assert candidate["short_change"] == 20
    assert candidate["short_balance_ratio_20d"] == 2.0
    assert candidate["margin_short_attention_flag"] is True
    assert "資券異常" in candidate["tags"]
    assert any("籌碼分歧" in note for note in candidate["risk_notes"])


def test_qullamaggie_candidate_includes_mops_event_catalyst_fields() -> None:
    current = make_record(date(2026, 6, 15), close=102.0, high=103.0, low=99.0, volume=3000, turnover=200_000_000)
    result = calculate_qullamaggie_signals(
        [current],
        history_for(),
        {"listed": [100 + i for i in range(61)]},
        mops_events_by_symbol={"2330": [make_mops_event(), make_mops_event(title="董事會決議股利", category="股利")]},
    )
    candidate = result["top_candidates"][0]
    assert candidate["mops_event_flag"] is True
    assert candidate["mops_event_count"] == 2
    assert candidate["mops_event_categories"] == ["股利", "重大合約"]
    assert "重大訊息" in candidate["catalyst_tags"]
    assert "重大訊息:股利" in candidate["catalyst_tags"]
    assert "MOPS" in candidate["source_refs"]


def test_qullamaggie_episodic_pivot_not_created_by_mops_alone() -> None:
    current = make_record(date(2026, 6, 15), close=96.0, high=97.0, low=95.0, volume=1000, turnover=200_000_000)
    result = calculate_qullamaggie_signals(
        [current],
        history_for(),
        {"listed": [100 + i for i in range(61)]},
        mops_events_by_symbol={"2330": [make_mops_event()]},
    )
    episodic = result["candidates"]["episodic_pivot"]
    assert episodic == []
    assert all(candidate["symbol"] != "2330" for candidate in episodic)
