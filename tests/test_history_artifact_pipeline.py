from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from stock_health.history_store import (
    build_symbol_history_coverage,
    load_history_rows,
    rebuild_history_index_from_files,
    upsert_ohlcv_records,
    write_json,
    write_ohlcv_history_outputs,
)
from stock_health.models import OhlcvRecord
from scripts.validate_generated_artifacts import validate_generated_artifacts


def test_ohlcv_upsert_is_idempotent_and_replaces_same_symbol_date() -> None:
    original = record(date(2026, 1, 2), "2330", 100.0)
    replacement = record(date(2026, 1, 2), "2330", 101.0)

    once = upsert_ohlcv_records([original], [replacement])
    twice = upsert_ohlcv_records(once, [replacement])

    assert len(once) == len(twice) == 1
    assert twice[0].close == 101.0


def test_partial_symbol_history_does_not_mark_other_symbol_incomplete(
    tmp_path: Path,
) -> None:
    first = date(2026, 1, 2)
    for offset in range(3):
        day = first + timedelta(days=offset)
        listed = [record(day, "2330", 100.0 + offset)]
        if offset != 1:
            listed.append(record(day, "2317", 90.0 + offset))
        write_ohlcv_history_outputs(
            tmp_path,
            day,
            listed,
            [record(day, "6488", 80.0 + offset, market="otc")],
        )

    coverage = build_symbol_history_coverage(tmp_path, 3)

    assert coverage["symbols"]["2330"]["available_trading_days"] == 3
    assert coverage["symbols"]["2330"]["missing_trading_day_count"] == 0
    assert coverage["symbols"]["2317"]["available_trading_days"] == 2
    assert coverage["symbols"]["2317"]["missing_trading_day_count"] == 1
    assert coverage["symbols"]["6488"]["available_trading_days"] == 3


def test_missing_market_day_can_be_added_without_duplicate_days(
    tmp_path: Path,
) -> None:
    days = [date(2026, 1, 2), date(2026, 1, 5), date(2026, 1, 6)]
    for day in (days[0], days[2]):
        write_ohlcv_history_outputs(
            tmp_path,
            day,
            [record(day, "2330", 100.0)],
            [record(day, "6488", 80.0, market="otc")],
        )
    before = rebuild_history_index_from_files(
        tmp_path,
        "2026-01-06T18:00:00+08:00",
        3,
        include_symbol_coverage=False,
    )

    write_ohlcv_history_outputs(
        tmp_path,
        days[1],
        [record(days[1], "2330", 101.0)],
        [record(days[1], "6488", 81.0, market="otc")],
    )
    write_ohlcv_history_outputs(
        tmp_path,
        days[1],
        [record(days[1], "2330", 101.0)],
        [record(days[1], "6488", 81.0, market="otc")],
    )
    after = rebuild_history_index_from_files(
        tmp_path,
        "2026-01-06T18:00:00+08:00",
        3,
        include_symbol_coverage=False,
    )

    assert before["available_trading_days"] == 2
    assert after["available_trading_days"] == 3
    assert after["common_ohlcv_days"] == [day.isoformat() for day in days]


def test_scan_history_consumer_excludes_noneligible_rows_but_raw_file_keeps_them(
    tmp_path: Path,
) -> None:
    day = date(2026, 1, 2)
    etf = record(day, "0050", 50.0)
    etf.scan_eligible = False
    etf.is_common_stock = False
    etf.security_type = "etf"
    write_ohlcv_history_outputs(
        tmp_path,
        day,
        [record(day, "2330", 100.0), etf],
        [record(day, "6488", 80.0, market="otc")],
    )

    raw = load_history_rows(tmp_path)
    scan_history = load_history_rows(tmp_path, scan_eligible_only=True)

    assert {row.symbol for row in raw[day.isoformat()]} == {
        "0050",
        "2330",
        "6488",
    }
    assert {row.symbol for row in scan_history[day.isoformat()]} == {
        "2330",
        "6488",
    }


def test_atomic_json_write_preserves_previous_file_on_serialization_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifact.json"
    write_json(path, {"status": "valid"})

    with pytest.raises(TypeError):
        write_json(path, {"invalid": object()})

    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "valid"}
    assert not list(tmp_path.glob(".artifact.json.*.tmp"))


def test_generated_artifact_validation_checks_counts_paths_and_dates(
    tmp_path: Path,
) -> None:
    report_date = "2026-07-29"
    market_date = "2026-07-28"
    symbol_path = "data/chatgpt/symbols/2330.json"
    write_json(
        tmp_path / "latest.json",
        {"report_date": report_date, "market_data_date": market_date},
    )
    history = {
        "available_trading_days": 260,
        "has_252d_history": True,
    }
    write_json(tmp_path / "data/history-index.json", history)
    write_json(tmp_path / "data/history-coverage.json", history)
    full_index_path = tmp_path / "data/chatgpt/symbol-index.json"
    write_json(
        full_index_path,
        {
            "report_date": report_date,
            "market_data_date": market_date,
            "symbol_count": 1,
        },
    )
    full_index_bytes = full_index_path.read_bytes()
    full_blob_sha = hashlib.sha1(
        f"blob {len(full_index_bytes)}\0".encode("ascii") + full_index_bytes
    ).hexdigest()
    write_json(
        tmp_path / "data/chatgpt/symbol-index-compact.json",
        {
            "report_date": report_date,
            "market_data_date": market_date,
            "symbol_count": 1,
            "full_index": {
                "path": "data/chatgpt/symbol-index.json",
                "byte_size": len(full_index_bytes),
                "blob_sha": full_blob_sha,
            },
            "sharded": False,
            "symbols": [
                {"symbol": "2330", "market": "listed", "path": symbol_path}
            ],
        },
    )
    write_json(
        tmp_path / "data/chatgpt/schedule-readiness.json",
        {
            "report_date": report_date,
            "market_data_date": market_date,
            "available_trading_days": 260,
            "has_252d_history": True,
            "symbol_count": 1,
        },
    )
    write_json(
        tmp_path / symbol_path,
        {"symbol": "2330", "market_data_date": market_date},
    )

    assert validate_generated_artifacts(tmp_path, 252) == []

    (tmp_path / symbol_path).unlink()
    errors = validate_generated_artifacts(tmp_path, 252)
    assert "missing_or_empty_symbol:2330" in errors


def record(
    day: date,
    symbol: str,
    close: float,
    *,
    market: str = "listed",
) -> OhlcvRecord:
    return OhlcvRecord(
        date=day.isoformat(),
        symbol=symbol,
        name=f"{symbol}公司",
        market=market,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        change=0.0,
        change_pct=0.0,
        volume=1_000,
        turnover=1_000_000,
        transactions=100,
        source="TWSE" if market == "listed" else "TPEx",
        security_type="common_stock",
        is_common_stock=True,
        scan_eligible=True,
    )
