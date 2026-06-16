from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, TIMEZONE
from .data_fetcher import (
    institutional_records_to_csv_text,
    margin_short_records_from_csv_text,
    margin_short_records_to_csv_text,
    records_from_csv_text,
    records_to_csv_text,
)
from .models import InstitutionalTradingRecord, MarginShortRecord, OhlcvRecord


def ensure_dirs(root: Path) -> None:
    for path in [
        root / "history",
        root / "data",
        root / "data" / "market",
        root / "data" / "institutional",
        root / "data" / "margin_short",
        root / "reports",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def history_report_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    folder = root / "history" / f"{report_date:%Y}" / f"{report_date:%m}"
    return folder / f"{report_date:%Y-%m-%d}.json", folder / f"{report_date:%Y-%m-%d}.md"


def market_history_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    folder = root / "data" / "market" / f"{report_date:%Y}" / f"{report_date:%m}"
    return folder / f"{report_date:%Y-%m-%d}-listed-ohlcv.csv", folder / f"{report_date:%Y-%m-%d}-otc-ohlcv.csv"


def institutional_history_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    folder = root / "data" / "institutional" / f"{report_date:%Y}" / f"{report_date:%m}"
    return folder / f"{report_date:%Y-%m-%d}-listed-institutional.csv", folder / f"{report_date:%Y-%m-%d}-otc-institutional.csv"


def margin_short_history_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    folder = root / "data" / "margin_short" / f"{report_date:%Y}" / f"{report_date:%m}"
    return folder / f"{report_date:%Y-%m-%d}-listed-margin-short.csv", folder / f"{report_date:%Y-%m-%d}-otc-margin-short.csv"


def write_ohlcv_outputs(root: Path, report_date: date, listed_rows: list[OhlcvRecord], otc_rows: list[OhlcvRecord]) -> None:
    listed_csv = records_to_csv_text(listed_rows)
    otc_csv = records_to_csv_text(otc_rows)
    write_text(root / "data" / "latest-listed-ohlcv.csv", listed_csv)
    write_text(root / "data" / "latest-otc-ohlcv.csv", otc_csv)
    listed_history, otc_history = market_history_paths(root, report_date)
    write_text(listed_history, listed_csv)
    write_text(otc_history, otc_csv)


def write_institutional_outputs(
    root: Path,
    report_date: date,
    listed_rows: list[InstitutionalTradingRecord],
    otc_rows: list[InstitutionalTradingRecord],
) -> None:
    latest_csv = institutional_records_to_csv_text(listed_rows + otc_rows)
    listed_csv = institutional_records_to_csv_text(listed_rows)
    otc_csv = institutional_records_to_csv_text(otc_rows)
    write_text(root / "data" / "latest-institutional-trading.csv", latest_csv)
    listed_history, otc_history = institutional_history_paths(root, report_date)
    write_text(listed_history, listed_csv)
    write_text(otc_history, otc_csv)


def write_margin_short_outputs(
    root: Path,
    report_date: date,
    listed_rows: list[MarginShortRecord],
    otc_rows: list[MarginShortRecord],
) -> None:
    latest_csv = margin_short_records_to_csv_text(listed_rows + otc_rows)
    listed_csv = margin_short_records_to_csv_text(listed_rows)
    otc_csv = margin_short_records_to_csv_text(otc_rows)
    write_text(root / "data" / "latest-margin-short.csv", latest_csv)
    listed_history, otc_history = margin_short_history_paths(root, report_date)
    write_text(listed_history, listed_csv)
    write_text(otc_history, otc_csv)


def load_history_rows(root: Path) -> dict[str, list[OhlcvRecord]]:
    market_dir = root / "data" / "market"
    rows: dict[str, list[OhlcvRecord]] = {}
    if not market_dir.exists():
        return rows
    for path in sorted(market_dir.glob("*/*/*-listed-ohlcv.csv")):
        day = path.name.removesuffix("-listed-ohlcv.csv")
        listed_rows = records_from_csv_text(path.read_text(encoding="utf-8"))
        otc_path = path.with_name(f"{day}-otc-ohlcv.csv")
        otc_rows = records_from_csv_text(otc_path.read_text(encoding="utf-8")) if otc_path.exists() else []
        if listed_rows and otc_rows:
            rows[day] = listed_rows + otc_rows
    return rows


def load_margin_short_history_rows(root: Path) -> dict[str, list[MarginShortRecord]]:
    margin_dir = root / "data" / "margin_short"
    rows: dict[str, list[MarginShortRecord]] = {}
    if not margin_dir.exists():
        return rows
    for path in sorted(margin_dir.glob("*/*/*-listed-margin-short.csv")):
        day = path.name.removesuffix("-listed-margin-short.csv")
        listed_rows = margin_short_records_from_csv_text(path.read_text(encoding="utf-8"))
        otc_path = path.with_name(f"{day}-otc-margin-short.csv")
        otc_rows = margin_short_records_from_csv_text(otc_path.read_text(encoding="utf-8")) if otc_path.exists() else []
        if listed_rows or otc_rows:
            rows[day] = listed_rows + otc_rows
    return rows


def build_history_index(
    generated_at: str,
    target_trading_days: int,
    listed_days: list[str],
    otc_days: list[str],
    errors: list[str],
    listed_institutional_days: list[str] | None = None,
    otc_institutional_days: list[str] | None = None,
    listed_margin_short_days: list[str] | None = None,
    otc_margin_short_days: list[str] | None = None,
) -> dict[str, Any]:
    listed_institutional_days = listed_institutional_days or []
    otc_institutional_days = otc_institutional_days or []
    listed_margin_short_days = listed_margin_short_days or []
    otc_margin_short_days = otc_margin_short_days or []
    common_days = sorted(set(listed_days) & set(otc_days))
    all_days = sorted(set(listed_days) | set(otc_days))
    institutional_days = sorted(set(listed_institutional_days) | set(otc_institutional_days))
    margin_short_days = sorted(set(listed_margin_short_days) | set(otc_margin_short_days))
    latest_reference_day = max(all_days or institutional_days or margin_short_days, default=None)
    missing_dates = [day for day in all_days if day not in common_days]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "target_trading_days": target_trading_days,
        "available_trading_days": len(common_days),
        "start_date": common_days[0] if common_days else None,
        "end_date": common_days[-1] if common_days else None,
        "listed_ohlcv_days": sorted(listed_days),
        "otc_ohlcv_days": sorted(otc_days),
        "listed_institutional_days": sorted(listed_institutional_days),
        "otc_institutional_days": sorted(otc_institutional_days),
        "listed_margin_short_days": sorted(listed_margin_short_days),
        "otc_margin_short_days": sorted(otc_margin_short_days),
        "missing_dates": missing_dates,
        "errors": errors,
        "has_20d_history": len(common_days) >= 20,
        "has_60d_history": len(common_days) >= 60,
        "has_institutional_history": bool(institutional_days and institutional_days[-1] == latest_reference_day),
        "has_margin_short_history": bool(margin_short_days and margin_short_days[-1] == latest_reference_day),
    }
