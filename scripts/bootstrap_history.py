#!/usr/bin/env python
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.data_fetcher import fetch_tpex_otc_ohlcv, fetch_twse_listed_ohlcv
from stock_health.history_store import build_history_index, ensure_dirs, write_json, write_ohlcv_outputs
from stock_health.trading_calendar import ensure_taipei, is_trading_day, iter_recent_calendar_days

LOGGER = logging.getLogger("stock_health.bootstrap_history")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap recent Taiwan stock OHLCV history.")
    parser.add_argument("--trading-days", type=int, default=60)
    parser.add_argument("--max-calendar-days", type=int, default=120)
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
        day = f"{target_date:%Y-%m-%d}"
        if listed.rows:
            listed_days.append(day)
        if otc.rows:
            otc_days.append(day)
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
        if args.sleep_seconds > 0:
            time.sleep(args.sleep_seconds)

    common_days = sorted(set(listed_days) & set(otc_days))
    if common_days:
        latest = date.fromisoformat(common_days[-1])
        latest_listed = fetch_twse_listed_ohlcv(latest)
        latest_otc = fetch_tpex_otc_ohlcv(latest)
        write_ohlcv_outputs(root, latest, latest_listed.rows, latest_otc.rows)

    index = build_history_index(now.isoformat(timespec="seconds"), args.trading_days, listed_days, otc_days, errors)
    write_json(root / "data" / "history-index.json", index)
    LOGGER.info("Available trading days: %s", index["available_trading_days"])
    return 0


def _looks_like_network_unavailable(errors: list[str]) -> bool:
    text = "\n".join(errors).lower()
    return any(marker in text for marker in ["urlerror", "timed out", "name or service", "temporary failure", "network is unreachable"])


if __name__ == "__main__":
    raise SystemExit(main())
