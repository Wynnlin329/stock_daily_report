#!/usr/bin/env python
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.chatgpt_source import (
    attach_screening_as_of_metadata,
    build_screening_history_index,
    screening_history_index_path,
    screening_history_path,
)
from stock_health.coverage import build_coverage
from stock_health.history_store import (
    benchmark_history_from_index_rows,
    build_history_index,
    load_history_rows,
    load_index_history_rows,
    load_institutional_history_rows,
    load_margin_short_history_rows,
    load_mops_event_history_payloads,
    write_json,
)
from stock_health.models import SourceHealth
from stock_health.screening import build_screening_summary
from stock_health.trading_calendar import ensure_taipei

LOGGER = logging.getLogger("stock_health.backfill_screening_history")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill ChatGPT screening summaries from local market history.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--trading-days", type=int, default=5, help="Number of latest common OHLCV trading days to rebuild.")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    root = Path(args.root).resolve()
    generated_at = ensure_taipei().isoformat(timespec="seconds")
    history_index_path = root / "data" / "history-index.json"
    if not history_index_path.exists():
        raise SystemExit("data/history-index.json not found; run scripts/run_health_check.py or bootstrap history first.")
    history_index = _read_json(history_index_path)
    common_days = list(history_index.get("common_ohlcv_days") or [])
    target_days = common_days[-args.trading_days :]
    if not target_days:
        raise SystemExit("data/history-index.json has no common_ohlcv_days.")

    ohlcv_history = load_history_rows(root, scan_eligible_only=True)
    index_history_rows = load_index_history_rows(root)
    institutional_history_rows = load_institutional_history_rows(root)
    margin_short_history_rows = load_margin_short_history_rows(root)
    mops_payloads = load_mops_event_history_payloads(root)

    for report_day in target_days:
        summary = _build_as_of_summary(
            report_day,
            generated_at,
            ohlcv_history,
            index_history_rows,
            institutional_history_rows,
            margin_short_history_rows,
            mops_payloads,
            history_index,
        )
        write_json(screening_history_path(root, report_day), summary)
        LOGGER.info("Wrote as-of screening summary for %s", report_day)

    refreshed_index = build_screening_history_index(root, generated_at, common_days, args.trading_days)
    write_json(screening_history_index_path(root), refreshed_index)
    LOGGER.info("Wrote screening history index with %s valid days", refreshed_index.get("available_valid_days"))
    return 0


def _build_as_of_summary(
    report_day: str,
    generated_at: str,
    ohlcv_history: dict[str, list[Any]],
    index_history_rows: dict[str, list[Any]],
    institutional_history_rows: dict[str, list[Any]],
    margin_short_history_rows: dict[str, list[Any]],
    mops_payloads: dict[str, dict[str, Any]],
    full_history_index: dict[str, Any],
) -> dict[str, Any]:
    current_rows = list(ohlcv_history.get(report_day, []))
    listed_rows = [row for row in current_rows if row.market == "listed"]
    otc_rows = [row for row in current_rows if row.market == "otc"]
    as_of_ohlcv_history = _filter_history_map(ohlcv_history, report_day)
    as_of_index_rows = {
        key: [row for row in rows if row.date <= report_day]
        for key, rows in index_history_rows.items()
    }
    as_of_benchmark = benchmark_history_from_index_rows(as_of_index_rows)
    as_of_institutional_history = _filter_history_map(institutional_history_rows, report_day)
    as_of_margin_short_history = _filter_history_map(margin_short_history_rows, report_day)
    as_of_mops_payloads = _filter_history_map(mops_payloads, report_day)
    institutional_rows = list(institutional_history_rows.get(report_day, []))
    margin_short_rows = list(margin_short_history_rows.get(report_day, []))
    current_mops_payload = mops_payloads.get(report_day, {})
    mops_status = str(current_mops_payload.get("status") or "source_unavailable")
    as_of_history_index = _history_index_as_of(full_history_index, report_day, generated_at)
    sources = _sources_for_as_of(report_day, generated_at, bool(listed_rows), bool(otc_rows), bool(current_mops_payload))
    coverage, full_market_scan_ready, missing_sections = build_coverage(
        sources,
        listed_rows,
        otc_rows,
        has_20d_history=bool(as_of_history_index.get("has_20d_history")),
        has_60d_history=bool(as_of_history_index.get("has_60d_history")),
        institutional_rows=institutional_rows,
        institutional_is_current=bool(institutional_rows),
        institutional_status="success" if institutional_rows else "source_unavailable",
        margin_short_rows=margin_short_rows,
        margin_short_is_current=bool(margin_short_rows),
        margin_short_status="success" if margin_short_rows else "source_unavailable",
        mops_event_rows=[],
        mops_events_is_current=mops_status in {"success", "empty_but_valid"},
        mops_events_date_explicit=current_mops_payload.get("data_date") == report_day,
        mops_events_status=mops_status,
    )
    summary = build_screening_summary(
        report_day,
        generated_at,
        listed_rows,
        otc_rows,
        as_of_ohlcv_history,
        coverage,
        full_market_scan_ready,
        missing_sections,
        "high" if listed_rows and otc_rows else "low",
        institutional_rows=institutional_rows,
        institutional_history_rows=as_of_institutional_history,
        margin_short_rows=margin_short_rows,
        margin_short_history_rows=as_of_margin_short_history,
        mops_event_rows=[],
        mops_event_history_payloads=as_of_mops_payloads,
        mops_events_status=mops_status,
        history_index=as_of_history_index,
        benchmark_history=as_of_benchmark,
    )
    used_dates = (
        list(as_of_ohlcv_history)
        + _dates_from_index_rows(as_of_index_rows)
        + list(as_of_institutional_history)
        + list(as_of_margin_short_history)
        + list(as_of_mops_payloads)
    )
    return attach_screening_as_of_metadata(summary, report_day, used_dates, "historical_as_of_backfill")


def _history_index_as_of(history_index: dict[str, Any], report_day: str, generated_at: str) -> dict[str, Any]:
    return build_history_index(
        generated_at,
        int(history_index.get("target_trading_days", 60)),
        _days_lte(history_index.get("listed_ohlcv_days", []), report_day),
        _days_lte(history_index.get("otc_ohlcv_days", []), report_day),
        [],
        _days_lte(history_index.get("listed_institutional_days", []), report_day),
        _days_lte(history_index.get("otc_institutional_days", []), report_day),
        _days_lte(history_index.get("listed_margin_short_days", []), report_day),
        _days_lte(history_index.get("otc_margin_short_days", []), report_day),
        _days_lte(history_index.get("mops_event_days", []), report_day),
        str(history_index.get("mops_backfill_mode") or "forward_accumulation"),
    )


def _sources_for_as_of(
    report_day: str,
    generated_at: str,
    listed_available: bool,
    otc_available: bool,
    mops_available: bool,
) -> dict[str, SourceHealth]:
    return {
        "twse": _source("TWSE", generated_at, report_day, listed_available, "主資料源"),
        "tpex": _source("TPEx", generated_at, report_day, otc_available, "主資料源"),
        "mops": _source("MOPS", generated_at, report_day, mops_available, "主資料源"),
        "yahoo_tw_stock": _source("Yahoo 奇摩股市", generated_at, report_day, False, "催化新聞源"),
        "cnyes": _source("鉅亨網 Cnyes", generated_at, report_day, False, "催化新聞源"),
        "moneydj": _source("MoneyDJ", generated_at, report_day, False, "催化新聞源"),
    }


def _source(name: str, generated_at: str, report_day: str, available: bool, role: str) -> SourceHealth:
    return SourceHealth(
        name=name,
        checked_at=generated_at,
        reachable=available,
        http_status=200 if available else None,
        data_date=report_day if available else None,
        is_current=available,
        date_explicit=available,
        machine_readable=True,
        login_required=False,
        dynamic_loading_suspected=False,
        schedule_ready=available,
        role=role,
        evidence="local historical as-of file available" if available else "local historical as-of file unavailable",
        error="" if available else "missing local historical as-of file",
        response_time_ms=None,
    )


def _filter_history_map(rows_by_day: dict[str, Any], report_day: str) -> dict[str, Any]:
    return {day: rows for day, rows in rows_by_day.items() if day <= report_day}


def _days_lte(days: list[str], report_day: str) -> list[str]:
    return sorted(day for day in days if day <= report_day)


def _dates_from_index_rows(index_rows: dict[str, list[Any]]) -> list[str]:
    return [row.date for rows in index_rows.values() for row in rows]


def _read_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
