#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.data_fetcher import (
    fetch_tpex_institutional_trading,
    fetch_tpex_index,
    fetch_tpex_margin_short,
    fetch_tpex_otc_ohlcv,
    fetch_mops_events,
    fetch_mops_historical_events,
    fetch_twse_institutional_trading,
    fetch_twse_taiex_index,
    fetch_twse_listed_ohlcv,
    fetch_twse_margin_short,
    mops_events_payload,
    records_to_csv_text,
)
from stock_health.config import (
    HISTORY_MAX_CALENDAR_DAYS,
    HISTORY_TARGET_TRADING_DAYS,
)
from stock_health.history_store import (
    build_symbol_history_coverage,
    ensure_dirs,
    load_mops_event_history_payloads,
    load_ohlcv_history_day,
    mops_event_history_paths,
    rebuild_history_index_from_files,
    upsert_ohlcv_records,
    write_index_outputs,
    write_institutional_outputs,
    write_json,
    write_margin_short_outputs,
    write_mops_event_outputs,
    write_ohlcv_history_outputs,
    write_text,
)
from stock_health.trading_calendar import (
    ensure_taipei,
    expected_market_data_date,
    is_trading_day,
    iter_recent_calendar_days,
)

LOGGER = logging.getLogger("stock_health.bootstrap_history")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap recent Taiwan stock OHLCV history.")
    parser.add_argument(
        "--trading-days",
        type=int,
        default=HISTORY_TARGET_TRADING_DAYS,
    )
    parser.add_argument(
        "--max-calendar-days",
        type=int,
        default=HISTORY_MAX_CALENDAR_DAYS,
    )
    parser.add_argument(
        "--include-institutional",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--include-margin-short",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--mops-calendar-days", type=int, default=90)
    parser.add_argument("--include-mops-backfill", action="store_true", default=False)
    parser.add_argument("--skip-mops", action="store_true", default=False)
    parser.add_argument("--skip-index", action="store_true", default=False)
    parser.add_argument("--require-complete", action="store_true", default=False)
    parser.add_argument("--mops-max-dates-per-run", type=int, default=5)
    parser.add_argument("--sleep-seconds", type=float, default=0.5)
    parser.add_argument("--root", default=".")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    root = Path(args.root).resolve()
    ensure_dirs(root)
    now = ensure_taipei()
    latest_complete_market_date = expected_market_data_date(now)
    initial_index = rebuild_history_index_from_files(
        root,
        now.isoformat(timespec="seconds"),
        args.trading_days,
        include_symbol_coverage=False,
    )
    before_days = int(initial_index.get("available_trading_days") or 0)
    before_coverage = build_symbol_history_coverage(root, args.trading_days)
    common_days = set(initial_index.get("common_ohlcv_days") or [])
    previous_status = _load_bootstrap_status(root)
    confirmed_non_trading_dates = set(
        previous_status.get("confirmed_non_trading_dates") or []
    )
    attempted_dates: list[str] = []
    completed_dates: list[str] = []
    failed_dates: list[dict[str, object]] = []
    listed_institutional_days: list[str] = []
    otc_institutional_days: list[str] = []
    listed_margin_short_days: list[str] = []
    otc_margin_short_days: list[str] = []
    mops_event_days: list[str] = []
    errors: list[str] = []
    consecutive_network_failures = 0

    for target_date in iter_recent_calendar_days(
        latest_complete_market_date,
        args.max_calendar_days,
    ):
        if not is_trading_day(target_date):
            continue
        if len(common_days) >= args.trading_days:
            break
        day = f"{target_date:%Y-%m-%d}"
        if day in common_days or day in confirmed_non_trading_dates:
            continue
        LOGGER.info("Fetching %s", target_date)
        attempted_dates.append(day)
        existing_listed, existing_otc = load_ohlcv_history_day(
            root,
            target_date,
        )
        listed = (
            fetch_twse_listed_ohlcv(target_date)
            if not existing_listed
            else None
        )
        otc = (
            fetch_tpex_otc_ohlcv(target_date)
            if not existing_otc
            else None
        )
        listed_rows = upsert_ohlcv_records(
            existing_listed,
            listed.rows if listed else [],
        )
        otc_rows = upsert_ohlcv_records(
            existing_otc,
            otc.rows if otc else [],
        )
        taiex_index = (
            fetch_twse_taiex_index(target_date) if not args.skip_index else None
        )
        tpex_index = fetch_tpex_index(target_date) if not args.skip_index else None
        listed_institutional = fetch_twse_institutional_trading(target_date) if args.include_institutional else None
        otc_institutional = fetch_tpex_institutional_trading(target_date) if args.include_institutional else None
        listed_margin_short = fetch_twse_margin_short(target_date) if args.include_margin_short else None
        otc_margin_short = fetch_tpex_margin_short(target_date) if args.include_margin_short else None
        if listed_institutional and listed_institutional.rows:
            listed_institutional_days.append(day)
        if otc_institutional and otc_institutional.rows:
            otc_institutional_days.append(day)
        if listed_margin_short and listed_margin_short.rows:
            listed_margin_short_days.append(day)
        if otc_margin_short and otc_margin_short.rows:
            otc_margin_short_days.append(day)
        if listed_rows and otc_rows:
            write_ohlcv_history_outputs(
                root,
                target_date,
                listed_rows,
                otc_rows,
            )
            common_days.add(day)
            completed_dates.append(day)
            consecutive_network_failures = 0
        else:
            day_errors = (
                [f"{day} listed: {err}" for err in (listed.errors if listed else [])]
                + [f"{day} otc: {err}" for err in (otc.errors if otc else [])]
            )
            status_values = {
                getattr(listed, "status", None),
                getattr(otc, "status", None),
            }
            if status_values <= {None, "non_trading_day", "empty_but_valid"}:
                LOGGER.info("Skipping non-trading date %s", day)
                confirmed_non_trading_dates.add(day)
            else:
                errors.extend(day_errors or [f"{day}: no OHLCV rows parsed"])
                failed_dates.append(
                    {
                        "date": day,
                        "listed_rows": len(listed_rows),
                        "otc_rows": len(otc_rows),
                        "errors": day_errors or ["no OHLCV rows parsed"],
                    }
                )
            if _looks_like_network_unavailable(day_errors):
                consecutive_network_failures += 1
            else:
                consecutive_network_failures = 0
            if consecutive_network_failures >= 5:
                errors.append("連續 5 個交易日皆疑似無法連外，停止 bootstrap 以避免無效重試")
                break
        if taiex_index and tpex_index and (taiex_index.rows or tpex_index.rows):
            write_index_outputs(root, target_date, taiex_index.rows, tpex_index.rows)
        elif taiex_index and tpex_index:
            errors.extend([f"{day} taiex index: {err}" for err in taiex_index.errors])
            errors.extend([f"{day} tpex index: {err}" for err in tpex_index.errors])
        if args.include_institutional and listed_institutional and otc_institutional:
            if listed_institutional.rows or otc_institutional.rows:
                write_institutional_outputs(
                    root,
                    target_date,
                    listed_institutional.rows,
                    otc_institutional.rows,
                    update_latest=False,
                )
            else:
                errors.extend([f"{day} listed institutional: {err}" for err in listed_institutional.errors])
                errors.extend([f"{day} otc institutional: {err}" for err in otc_institutional.errors])
        if args.include_margin_short and listed_margin_short and otc_margin_short:
            if listed_margin_short.rows or otc_margin_short.rows:
                write_margin_short_outputs(
                    root,
                    target_date,
                    listed_margin_short.rows,
                    otc_margin_short.rows,
                    update_latest=False,
                )
            else:
                errors.extend([f"{day} listed margin_short: {err}" for err in listed_margin_short.errors])
                errors.extend([f"{day} otc margin_short: {err}" for err in otc_margin_short.errors])
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    mops_backfill_mode = "manual_backfill" if args.include_mops_backfill else "forward_accumulation"
    mops_days_to_fetch = [] if args.skip_mops else [now.date()]
    if args.include_mops_backfill:
        mops_days_to_fetch = []
        for target_date in iter_recent_calendar_days(now.date(), args.mops_calendar_days):
            if _has_complete_mops_history(root, target_date):
                LOGGER.info("Skipping MOPS events %s; already complete", target_date)
                continue
            mops_days_to_fetch.append(target_date)
            if len(mops_days_to_fetch) >= max(args.mops_max_dates_per_run, 1):
                break

    mops_fetcher = fetch_mops_historical_events if args.include_mops_backfill else fetch_mops_events
    for target_date in mops_days_to_fetch:
        day = f"{target_date:%Y-%m-%d}"
        LOGGER.info("Fetching MOPS events %s", target_date)
        mops_events = mops_fetcher(target_date)
        mops_summary = mops_events_payload(
            day,
            now.isoformat(timespec="seconds"),
            mops_events.data_date,
            mops_events.ok and mops_events.data_date == day,
            mops_events.rows,
            mops_events.errors,
            mops_events.limitations,
            mops_events.status,
            mops_events.source_url,
            mops_events.requested_date,
            mops_events.source_endpoint,
            mops_events.fallback_used,
            mops_events.date_validation,
            mops_events.status_reason,
        )
        write_mops_event_outputs(root, target_date, mops_summary, mops_events.rows)
        if mops_events.ok and mops_events.data_date == day:
            mops_event_days.append(day)
        else:
            errors.extend([f"{day} mops events: {err}" for err in mops_events.errors])
        if mops_events.status == "blocked_or_security_page":
            errors.append("MOPS 回傳安全頁，停止 MOPS 重大訊息回補以避免持續請求")
            mops_backfill_mode = "disabled_due_to_security_page"
            break
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    if args.include_mops_backfill:
        _refresh_latest_mops_outputs(root)

    index = rebuild_history_index_from_files(
        root,
        now.isoformat(timespec="seconds"),
        args.trading_days,
        errors,
        mops_backfill_mode,
        include_symbol_coverage=False,
    )
    after_days = int(index.get("available_trading_days") or 0)
    complete = after_days >= args.trading_days
    source_limitations: list[str] = []
    if not complete:
        source_limitations.append(
            f"only {after_days}/{args.trading_days} verified common market sessions "
            f"were available within {args.max_calendar_days} calendar days"
        )
    bootstrap_status = {
        "schema_version": "1.0",
        "status": "complete" if complete else "incomplete",
        "started_at": now.isoformat(timespec="seconds"),
        "completed_at": ensure_taipei().isoformat(timespec="seconds"),
        "last_success_at": (
            ensure_taipei().isoformat(timespec="seconds")
            if complete
            else previous_status.get("last_success_at")
        ),
        "target_trading_days": args.trading_days,
        "before_available_trading_days": before_days,
        "before_earliest_market_data_date": initial_index.get(
            "earliest_market_data_date"
        ),
        "before_latest_market_data_date": initial_index.get(
            "latest_market_data_date"
        ),
        "before_missing_dates": initial_index.get("missing_dates", []),
        "before_symbol_coverage": {
            key: value
            for key, value in before_coverage.items()
            if key != "symbols"
        },
        "after_available_trading_days": after_days,
        "after_earliest_market_data_date": index.get(
            "earliest_market_data_date"
        ),
        "after_latest_market_data_date": index.get("latest_market_data_date"),
        "attempted_dates": attempted_dates,
        "completed_dates": completed_dates,
        "failed_dates": failed_dates,
        "missing_or_failed_dates": [
            item["date"] for item in failed_dates
        ],
        "confirmed_non_trading_dates": sorted(confirmed_non_trading_dates),
        "errors": errors,
        "source_limitations": source_limitations,
    }
    write_json(
        root / "data" / "history-bootstrap-status.json",
        bootstrap_status,
    )
    index = rebuild_history_index_from_files(
        root,
        ensure_taipei().isoformat(timespec="seconds"),
        args.trading_days,
        errors,
        mops_backfill_mode,
        coverage_output_path=root / "data" / "history-coverage.json",
    )
    write_json(root / "data" / "history-index.json", index)
    _refresh_latest_ohlcv_outputs(root, index)
    LOGGER.info("Available trading days: %s", index["available_trading_days"])
    if args.require_complete and not complete:
        LOGGER.error(
            "History remains incomplete: %s/%s verified trading days",
            after_days,
            args.trading_days,
        )
        return 2
    return 0


def _looks_like_network_unavailable(errors: list[str]) -> bool:
    text = "\n".join(errors).lower()
    return any(marker in text for marker in ["urlerror", "timed out", "name or service", "temporary failure", "network is unreachable"])


def _load_bootstrap_status(root: Path) -> dict[str, object]:
    path = root / "data" / "history-bootstrap-status.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _refresh_latest_ohlcv_outputs(
    root: Path,
    history_index: dict[str, object],
) -> None:
    end_date = history_index.get("end_date")
    if not end_date:
        return
    latest = date.fromisoformat(str(end_date))
    listed_rows, otc_rows = load_ohlcv_history_day(root, latest)
    if not listed_rows or not otc_rows:
        return
    write_text(
        root / "data" / "latest-listed-ohlcv.csv",
        records_to_csv_text(listed_rows),
    )
    write_text(
        root / "data" / "latest-otc-ohlcv.csv",
        records_to_csv_text(otc_rows),
    )


def _has_complete_mops_history(root: Path, target_date: date) -> bool:
    history_json, _ = mops_event_history_paths(root, target_date)
    day = f"{target_date:%Y-%m-%d}"
    if not history_json.exists():
        return False
    try:
        payload = json.loads(history_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("status") in {"success", "empty_but_valid"} and payload.get("data_date") == day


def _refresh_latest_mops_outputs(root: Path) -> None:
    payloads = load_mops_event_history_payloads(root)
    complete_days = sorted(
        day
        for day, payload in payloads.items()
        if payload.get("status") in {"success", "empty_but_valid"} and payload.get("data_date") == day
    )
    if not complete_days:
        return
    latest_day = date.fromisoformat(complete_days[-1])
    history_json, history_csv = mops_event_history_paths(root, latest_day)
    if history_json.exists():
        (root / "data" / "latest-mops-events.json").write_text(history_json.read_text(encoding="utf-8"), encoding="utf-8")
    if history_csv.exists():
        (root / "data" / "latest-mops-events.csv").write_text(history_csv.read_text(encoding="utf-8"), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
