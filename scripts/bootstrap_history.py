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
)
from stock_health.history_store import ensure_dirs, load_mops_event_history_payloads, mops_event_history_paths, rebuild_history_index_from_files, write_index_outputs, write_json, write_institutional_outputs, write_margin_short_outputs, write_mops_event_outputs, write_ohlcv_outputs
from stock_health.trading_calendar import ensure_taipei, is_trading_day, iter_recent_calendar_days

LOGGER = logging.getLogger("stock_health.bootstrap_history")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap recent Taiwan stock OHLCV history.")
    parser.add_argument("--trading-days", type=int, default=60)
    parser.add_argument("--max-calendar-days", type=int, default=180)
    parser.add_argument("--include-institutional", action="store_true", default=True)
    parser.add_argument("--include-margin-short", action="store_true", default=True)
    parser.add_argument("--mops-calendar-days", type=int, default=90)
    parser.add_argument("--include-mops-backfill", action="store_true", default=False)
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
    listed_days: list[str] = []
    otc_days: list[str] = []
    listed_institutional_days: list[str] = []
    otc_institutional_days: list[str] = []
    listed_margin_short_days: list[str] = []
    otc_margin_short_days: list[str] = []
    mops_event_days: list[str] = []
    errors: list[str] = []
    consecutive_network_failures = 0

    for target_date in iter_recent_calendar_days(now.date(), args.max_calendar_days):
        if not is_trading_day(target_date):
            continue
        if len(set(listed_days) & set(otc_days)) >= args.trading_days:
            break
        LOGGER.info("Fetching %s", target_date)
        listed = fetch_twse_listed_ohlcv(target_date)
        otc = fetch_tpex_otc_ohlcv(target_date)
        taiex_index = fetch_twse_taiex_index(target_date)
        tpex_index = fetch_tpex_index(target_date)
        listed_institutional = fetch_twse_institutional_trading(target_date) if args.include_institutional else None
        otc_institutional = fetch_tpex_institutional_trading(target_date) if args.include_institutional else None
        listed_margin_short = fetch_twse_margin_short(target_date) if args.include_margin_short else None
        otc_margin_short = fetch_tpex_margin_short(target_date) if args.include_margin_short else None
        day = f"{target_date:%Y-%m-%d}"
        if listed.rows:
            listed_days.append(day)
        if otc.rows:
            otc_days.append(day)
        if listed_institutional and listed_institutional.rows:
            listed_institutional_days.append(day)
        if otc_institutional and otc_institutional.rows:
            otc_institutional_days.append(day)
        if listed_margin_short and listed_margin_short.rows:
            listed_margin_short_days.append(day)
        if otc_margin_short and otc_margin_short.rows:
            otc_margin_short_days.append(day)
        if listed.rows or otc.rows:
            write_ohlcv_outputs(root, target_date, listed.rows, otc.rows)
            consecutive_network_failures = 0
        else:
            day_errors = [f"{day} listed: {err}" for err in listed.errors] + [f"{day} otc: {err}" for err in otc.errors]
            errors.extend(day_errors or [f"{day}: no OHLCV rows parsed"])
            if _looks_like_network_unavailable(day_errors):
                consecutive_network_failures += 1
            if consecutive_network_failures >= 5:
                errors.append("連續 5 個交易日皆疑似無法連外，停止 bootstrap 以避免無效重試")
                break
        if taiex_index.rows or tpex_index.rows:
            write_index_outputs(root, target_date, taiex_index.rows, tpex_index.rows)
        else:
            errors.extend([f"{day} taiex index: {err}" for err in taiex_index.errors])
            errors.extend([f"{day} tpex index: {err}" for err in tpex_index.errors])
        if args.include_institutional and listed_institutional and otc_institutional:
            if listed_institutional.rows or otc_institutional.rows:
                write_institutional_outputs(root, target_date, listed_institutional.rows, otc_institutional.rows)
            else:
                errors.extend([f"{day} listed institutional: {err}" for err in listed_institutional.errors])
                errors.extend([f"{day} otc institutional: {err}" for err in otc_institutional.errors])
        if args.include_margin_short and listed_margin_short and otc_margin_short:
            if listed_margin_short.rows or otc_margin_short.rows:
                write_margin_short_outputs(root, target_date, listed_margin_short.rows, otc_margin_short.rows)
            else:
                errors.extend([f"{day} listed margin_short: {err}" for err in listed_margin_short.errors])
                errors.extend([f"{day} otc margin_short: {err}" for err in otc_margin_short.errors])
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    mops_backfill_mode = "manual_backfill" if args.include_mops_backfill else "forward_accumulation"
    mops_days_to_fetch = [now.date()]
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

    common_days = sorted(set(listed_days) & set(otc_days))
    if common_days:
        latest = date.fromisoformat(common_days[-1])
        latest_listed = fetch_twse_listed_ohlcv(latest)
        latest_otc = fetch_tpex_otc_ohlcv(latest)
        latest_taiex_index = fetch_twse_taiex_index(latest)
        latest_tpex_index = fetch_tpex_index(latest)
        write_ohlcv_outputs(root, latest, latest_listed.rows, latest_otc.rows)
        write_index_outputs(root, latest, latest_taiex_index.rows, latest_tpex_index.rows)
        if args.include_institutional:
            latest_listed_institutional = fetch_twse_institutional_trading(latest)
            latest_otc_institutional = fetch_tpex_institutional_trading(latest)
            write_institutional_outputs(root, latest, latest_listed_institutional.rows, latest_otc_institutional.rows)
        if args.include_margin_short:
            latest_listed_margin_short = fetch_twse_margin_short(latest)
            latest_otc_margin_short = fetch_tpex_margin_short(latest)
            write_margin_short_outputs(root, latest, latest_listed_margin_short.rows, latest_otc_margin_short.rows)

    index = rebuild_history_index_from_files(
        root,
        now.isoformat(timespec="seconds"),
        args.trading_days,
        errors,
        mops_backfill_mode,
    )
    write_json(root / "data" / "history-index.json", index)
    LOGGER.info("Available trading days: %s", index["available_trading_days"])
    return 0


def _looks_like_network_unavailable(errors: list[str]) -> bool:
    text = "\n".join(errors).lower()
    return any(marker in text for marker in ["urlerror", "timed out", "name or service", "temporary failure", "network is unreachable"])


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
