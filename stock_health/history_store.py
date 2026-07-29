from __future__ import annotations

import csv
import json
import os
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, TIMEZONE
from .data_fetcher import (
    index_records_from_csv_text,
    index_records_to_csv_text,
    institutional_records_from_csv_text,
    institutional_records_to_csv_text,
    margin_short_records_from_csv_text,
    margin_short_records_to_csv_text,
    mops_events_to_csv_text,
    records_from_csv_text,
    records_to_csv_text,
)
from .models import IndexRecord, InstitutionalTradingRecord, MarginShortRecord, MopsEventRecord, OhlcvRecord


def ensure_dirs(root: Path) -> None:
    for path in [
        root / "history",
        root / "data",
        root / "data" / "market",
        root / "data" / "institutional",
        root / "data" / "index",
        root / "data" / "index" / "taiex",
        root / "data" / "index" / "tpex",
        root / "data" / "margin_short",
        root / "data" / "mops",
        root / "reports",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    json.loads(content)
    write_text(path, content)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if temporary_path.stat().st_size <= 0:
            raise ValueError(f"refusing to publish empty artifact: {path}")
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_chatgpt_symbol_outputs(
    root: Path,
    symbol_payloads: dict[str, dict[str, Any]],
    symbol_index: dict[str, Any],
    compact_index: dict[str, Any],
    compact_shards: dict[str, dict[str, Any]] | None = None,
) -> None:
    symbols_dir = root / "data" / "chatgpt" / "symbols"
    symbols_dir.mkdir(parents=True, exist_ok=True)
    for symbol, payload in sorted(symbol_payloads.items()):
        write_json(symbols_dir / f"{symbol}.json", payload)
    write_json(root / "data" / "chatgpt" / "symbol-index.json", symbol_index)
    write_json(
        root / "data" / "chatgpt" / "symbol-index-compact.json",
        compact_index,
    )
    shard_dir = root / "data" / "chatgpt" / "symbol-index-shards"
    current_shards = set((compact_shards or {}).keys())
    for relative_path, payload in sorted((compact_shards or {}).items()):
        write_json(root / relative_path, payload)

    current_files = {f"{symbol}.json" for symbol in symbol_payloads}
    for path in symbols_dir.glob("*.json"):
        if path.name not in current_files:
            path.unlink()
    if shard_dir.exists():
        for path in shard_dir.glob("*.json"):
            relative_path = path.relative_to(root).as_posix()
            if relative_path not in current_shards:
                path.unlink()


def history_report_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    folder = root / "history" / f"{report_date:%Y}" / f"{report_date:%m}"
    return folder / f"{report_date:%Y-%m-%d}.json", folder / f"{report_date:%Y-%m-%d}.md"


def market_history_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    folder = root / "data" / "market" / f"{report_date:%Y}" / f"{report_date:%m}"
    return folder / f"{report_date:%Y-%m-%d}-listed-ohlcv.csv", folder / f"{report_date:%Y-%m-%d}-otc-ohlcv.csv"


def index_history_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    taiex_folder = root / "data" / "index" / "taiex" / f"{report_date:%Y}" / f"{report_date:%m}"
    tpex_folder = root / "data" / "index" / "tpex" / f"{report_date:%Y}" / f"{report_date:%m}"
    return taiex_folder / f"{report_date:%Y-%m-%d}-taiex.csv", tpex_folder / f"{report_date:%Y-%m-%d}-tpex.csv"


def institutional_history_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    folder = root / "data" / "institutional" / f"{report_date:%Y}" / f"{report_date:%m}"
    return folder / f"{report_date:%Y-%m-%d}-listed-institutional.csv", folder / f"{report_date:%Y-%m-%d}-otc-institutional.csv"


def margin_short_history_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    folder = root / "data" / "margin_short" / f"{report_date:%Y}" / f"{report_date:%m}"
    return folder / f"{report_date:%Y-%m-%d}-listed-margin-short.csv", folder / f"{report_date:%Y-%m-%d}-otc-margin-short.csv"


def mops_event_history_paths(root: Path, report_date: date) -> tuple[Path, Path]:
    folder = root / "data" / "mops" / f"{report_date:%Y}" / f"{report_date:%m}"
    return folder / f"{report_date:%Y-%m-%d}-mops-events.json", folder / f"{report_date:%Y-%m-%d}-mops-events.csv"


def write_ohlcv_outputs(root: Path, report_date: date, listed_rows: list[OhlcvRecord], otc_rows: list[OhlcvRecord]) -> None:
    if not listed_rows or not otc_rows:
        return
    write_ohlcv_history_outputs(root, report_date, listed_rows, otc_rows)
    listed_csv = records_to_csv_text(listed_rows)
    otc_csv = records_to_csv_text(otc_rows)
    write_text(root / "data" / "latest-listed-ohlcv.csv", listed_csv)
    write_text(root / "data" / "latest-otc-ohlcv.csv", otc_csv)


def write_ohlcv_history_outputs(
    root: Path,
    report_date: date,
    listed_rows: list[OhlcvRecord],
    otc_rows: list[OhlcvRecord],
) -> None:
    if not listed_rows or not otc_rows:
        raise ValueError(
            f"both listed and OTC OHLCV rows are required for {report_date}"
        )
    listed_rows = upsert_ohlcv_records([], listed_rows)
    otc_rows = upsert_ohlcv_records([], otc_rows)
    listed_csv = records_to_csv_text(listed_rows)
    otc_csv = records_to_csv_text(otc_rows)
    listed_history, otc_history = market_history_paths(root, report_date)
    write_text(listed_history, listed_csv)
    write_text(otc_history, otc_csv)


def load_ohlcv_history_day(
    root: Path,
    report_date: date,
) -> tuple[list[OhlcvRecord], list[OhlcvRecord]]:
    listed_path, otc_path = market_history_paths(root, report_date)
    listed_rows = (
        records_from_csv_text(listed_path.read_text(encoding="utf-8"))
        if listed_path.exists()
        else []
    )
    otc_rows = (
        records_from_csv_text(otc_path.read_text(encoding="utf-8"))
        if otc_path.exists()
        else []
    )
    return listed_rows, otc_rows


def upsert_ohlcv_records(
    existing_rows: list[OhlcvRecord],
    incoming_rows: list[OhlcvRecord],
) -> list[OhlcvRecord]:
    keyed: dict[tuple[str, str], OhlcvRecord] = {}
    for row in [*existing_rows, *incoming_rows]:
        if not row.date or not row.symbol:
            continue
        keyed[(row.date, row.symbol)] = row
    return [
        keyed[key]
        for key in sorted(keyed, key=lambda item: (item[0], item[1]))
    ]


def write_index_outputs(root: Path, report_date: date, taiex_rows: list[IndexRecord], tpex_rows: list[IndexRecord]) -> None:
    taiex_csv = index_records_to_csv_text(taiex_rows)
    tpex_csv = index_records_to_csv_text(tpex_rows)
    taiex_history, tpex_history = index_history_paths(root, report_date)
    write_text(taiex_history, taiex_csv)
    write_text(tpex_history, tpex_csv)


def write_institutional_outputs(
    root: Path,
    report_date: date,
    listed_rows: list[InstitutionalTradingRecord],
    otc_rows: list[InstitutionalTradingRecord],
    *,
    update_latest: bool = True,
) -> None:
    latest_csv = institutional_records_to_csv_text(listed_rows + otc_rows)
    listed_csv = institutional_records_to_csv_text(listed_rows)
    otc_csv = institutional_records_to_csv_text(otc_rows)
    if update_latest:
        write_text(root / "data" / "latest-institutional-trading.csv", latest_csv)
    listed_history, otc_history = institutional_history_paths(root, report_date)
    write_text(listed_history, listed_csv)
    write_text(otc_history, otc_csv)


def write_margin_short_outputs(
    root: Path,
    report_date: date,
    listed_rows: list[MarginShortRecord],
    otc_rows: list[MarginShortRecord],
    *,
    update_latest: bool = True,
) -> None:
    latest_csv = margin_short_records_to_csv_text(listed_rows + otc_rows)
    listed_csv = margin_short_records_to_csv_text(listed_rows)
    otc_csv = margin_short_records_to_csv_text(otc_rows)
    if update_latest:
        write_text(root / "data" / "latest-margin-short.csv", latest_csv)
    listed_history, otc_history = margin_short_history_paths(root, report_date)
    write_text(listed_history, listed_csv)
    write_text(otc_history, otc_csv)


def write_mops_event_outputs(root: Path, report_date: date, payload: dict[str, Any], rows: list[MopsEventRecord]) -> None:
    csv_text = mops_events_to_csv_text(rows)
    write_json(root / "data" / "latest-mops-events.json", payload)
    write_text(root / "data" / "latest-mops-events.csv", csv_text)
    history_json, history_csv = mops_event_history_paths(root, report_date)
    write_json(history_json, payload)
    write_text(history_csv, csv_text)


def load_history_rows(
    root: Path,
    *,
    scan_eligible_only: bool = False,
) -> dict[str, list[OhlcvRecord]]:
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
            combined = listed_rows + otc_rows
            rows[day] = (
                [row for row in combined if row.scan_eligible]
                if scan_eligible_only
                else combined
            )
    return rows


def load_index_history_rows(root: Path) -> dict[str, list[IndexRecord]]:
    output = {"taiex": [], "tpex_index": []}
    for key, folder_name, suffix in (
        ("taiex", "taiex", "-taiex.csv"),
        ("tpex_index", "tpex", "-tpex.csv"),
    ):
        folder = root / "data" / "index" / folder_name
        if not folder.exists():
            continue
        rows: list[IndexRecord] = []
        for path in sorted(folder.glob(f"*/*/*{suffix}")):
            rows.extend(index_records_from_csv_text(path.read_text(encoding="utf-8")))
        rows.sort(key=lambda item: item.date)
        output[key] = rows
    return output


def benchmark_history_from_index_rows(index_rows: dict[str, list[IndexRecord]]) -> dict[str, list[float]]:
    return {
        "listed": [row.close for row in index_rows.get("taiex", []) if row.close is not None and row.close > 0],
        "otc": [row.close for row in index_rows.get("tpex_index", []) if row.close is not None and row.close > 0],
    }


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


def load_institutional_history_rows(root: Path) -> dict[str, list[InstitutionalTradingRecord]]:
    institutional_dir = root / "data" / "institutional"
    rows: dict[str, list[InstitutionalTradingRecord]] = {}
    if not institutional_dir.exists():
        return rows
    for path in sorted(institutional_dir.glob("*/*/*-listed-institutional.csv")):
        day = path.name.removesuffix("-listed-institutional.csv")
        listed_rows = institutional_records_from_csv_text(path.read_text(encoding="utf-8"))
        otc_path = path.with_name(f"{day}-otc-institutional.csv")
        otc_rows = institutional_records_from_csv_text(otc_path.read_text(encoding="utf-8")) if otc_path.exists() else []
        if listed_rows or otc_rows:
            rows[day] = listed_rows + otc_rows
    return rows


def load_mops_event_history_payloads(root: Path) -> dict[str, dict[str, Any]]:
    mops_dir = root / "data" / "mops"
    payloads: dict[str, dict[str, Any]] = {}
    if not mops_dir.exists():
        return payloads
    for path in sorted(mops_dir.glob("*/*/*-mops-events.json")):
        day = path.name.removesuffix("-mops-events.json")
        payloads[day] = json.loads(path.read_text(encoding="utf-8"))
    return payloads


def rebuild_history_index_from_files(
    root: Path,
    generated_at: str,
    target_trading_days: int,
    errors: list[str] | None = None,
    mops_backfill_mode: str = "forward_accumulation",
    *,
    include_symbol_coverage: bool = True,
    coverage_output_path: Path | None = None,
) -> dict[str, Any]:
    listed_days, otc_days = _market_history_days(root)
    listed_institutional_days, otc_institutional_days = _paired_csv_history_days(
        root / "data" / "institutional",
        "-listed-institutional.csv",
        "-otc-institutional.csv",
        institutional_records_from_csv_text,
    )
    listed_margin_short_days, otc_margin_short_days = _paired_csv_history_days(
        root / "data" / "margin_short",
        "-listed-margin-short.csv",
        "-otc-margin-short.csv",
        margin_short_records_from_csv_text,
    )
    mops_event_days = sorted(
        day
        for day, payload in load_mops_event_history_payloads(root).items()
        if payload.get("status") in {"success", "empty_but_valid"} and payload.get("data_date") == day
    )
    bootstrap_status = _load_json_object(
        root / "data" / "history-bootstrap-status.json"
    )
    symbol_coverage = (
        build_symbol_history_coverage(root, target_trading_days)
        if include_symbol_coverage
        else None
    )
    if symbol_coverage is not None and coverage_output_path is not None:
        write_json(coverage_output_path, symbol_coverage)
    return build_history_index(
        generated_at,
        target_trading_days,
        listed_days,
        otc_days,
        errors or [],
        listed_institutional_days,
        otc_institutional_days,
        listed_margin_short_days,
        otc_margin_short_days,
        mops_event_days,
        mops_backfill_mode,
        bootstrap_status,
        symbol_coverage,
    )


def _market_history_days(root: Path) -> tuple[list[str], list[str]]:
    market_dir = root / "data" / "market"
    if not market_dir.exists():
        return [], []
    listed_days: list[str] = []
    otc_days: list[str] = []
    for path in sorted(market_dir.glob("*/*/*-listed-ohlcv.csv")):
        day = path.name.removesuffix("-listed-ohlcv.csv")
        if _csv_has_data_row(path):
            listed_days.append(day)
    for path in sorted(market_dir.glob("*/*/*-otc-ohlcv.csv")):
        day = path.name.removesuffix("-otc-ohlcv.csv")
        if _csv_has_data_row(path):
            otc_days.append(day)
    return listed_days, otc_days


def _paired_csv_history_days(
    folder: Path,
    listed_suffix: str,
    otc_suffix: str,
    parser: Any,
) -> tuple[list[str], list[str]]:
    if not folder.exists():
        return [], []
    listed_days: list[str] = []
    otc_days: list[str] = []
    for path in sorted(folder.glob(f"*/*/*{listed_suffix}")):
        day = path.name.removesuffix(listed_suffix)
        if _csv_has_data_row(path):
            listed_days.append(day)
    for path in sorted(folder.glob(f"*/*/*{otc_suffix}")):
        day = path.name.removesuffix(otc_suffix)
        if _csv_has_data_row(path):
            otc_days.append(day)
    return listed_days, otc_days


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
    mops_event_days: list[str] | None = None,
    mops_backfill_mode: str = "forward_accumulation",
    bootstrap_status: dict[str, Any] | None = None,
    symbol_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    listed_institutional_days = listed_institutional_days or []
    otc_institutional_days = otc_institutional_days or []
    listed_margin_short_days = listed_margin_short_days or []
    otc_margin_short_days = otc_margin_short_days or []
    mops_event_days = mops_event_days or []
    common_days = sorted(set(listed_days) & set(otc_days))
    all_days = sorted(set(listed_days) | set(otc_days))
    institutional_days = sorted(set(listed_institutional_days) | set(otc_institutional_days))
    common_institutional_days = sorted(set(listed_institutional_days) & set(otc_institutional_days))
    margin_short_days = sorted(set(listed_margin_short_days) | set(otc_margin_short_days))
    common_margin_short_days = sorted(set(listed_margin_short_days) & set(otc_margin_short_days))
    latest_reference_day = common_days[-1] if common_days else max(institutional_days or margin_short_days or mops_event_days, default=None)
    missing_dates = [day for day in all_days if day not in common_days]
    sorted_mops_days = sorted(mops_event_days)
    mops_event_day_set = set(sorted_mops_days)
    latest_mops_day = date.fromisoformat(sorted_mops_days[-1]) if sorted_mops_days else None
    bootstrap_status = bootstrap_status or {}
    bootstrap_complete = len(common_days) >= target_trading_days
    symbol_coverage = symbol_coverage or {
        "symbol_count": 0,
        "symbols_with_126d_history": 0,
        "symbols_with_252d_history": 0,
        "symbols_with_target_history": 0,
        "symbols": {},
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "target_trading_days": target_trading_days,
        "available_trading_days": len(common_days),
        "start_date": common_days[0] if common_days else None,
        "end_date": common_days[-1] if common_days else None,
        "earliest_market_data_date": common_days[0] if common_days else None,
        "latest_market_data_date": common_days[-1] if common_days else None,
        "listed_ohlcv_days": sorted(listed_days),
        "otc_ohlcv_days": sorted(otc_days),
        "common_ohlcv_days": common_days,
        "listed_institutional_days": sorted(listed_institutional_days),
        "otc_institutional_days": sorted(otc_institutional_days),
        "common_institutional_days": common_institutional_days,
        "listed_margin_short_days": sorted(listed_margin_short_days),
        "otc_margin_short_days": sorted(otc_margin_short_days),
        "common_margin_short_days": common_margin_short_days,
        "mops_event_days": sorted_mops_days,
        "mops_backfill_mode": mops_backfill_mode,
        "missing_dates": missing_dates,
        "errors": errors,
        "history_bootstrap_status": (
            "complete"
            if bootstrap_complete
            else "incomplete"
            if bootstrap_status
            else "not_run"
        ),
        "history_bootstrap_last_success_at": bootstrap_status.get(
            "last_success_at"
        ),
        "history_bootstrap_errors": bootstrap_status.get("errors", errors),
        "history_bootstrap_source_limitations": bootstrap_status.get(
            "source_limitations", []
        ),
        "symbol_coverage": {
            key: value
            for key, value in symbol_coverage.items()
            if key != "symbols"
        },
        "has_20d_history": len(common_days) >= 20,
        "has_60d_history": len(common_days) >= 60,
        "has_126d_history": len(common_days) >= 126,
        "has_252d_history": len(common_days) >= 252,
        "has_institutional_history": bool(common_institutional_days and common_institutional_days[-1] == latest_reference_day),
        "has_margin_short_history": bool(common_margin_short_days and common_margin_short_days[-1] == latest_reference_day),
        "has_mops_event_history": bool(sorted_mops_days and sorted_mops_days[-1] == latest_reference_day),
        "has_institutional_latest": bool(latest_reference_day and latest_reference_day in common_institutional_days),
        "has_institutional_5d_history": len(common_institutional_days) >= 5,
        "has_institutional_20d_history": len(common_institutional_days) >= 20,
        "has_institutional_60d_history": len(common_institutional_days) >= 60,
        "has_margin_short_latest": bool(latest_reference_day and latest_reference_day in common_margin_short_days),
        "has_margin_short_5d_history": len(common_margin_short_days) >= 5,
        "has_margin_short_20d_history": len(common_margin_short_days) >= 20,
        "has_margin_short_60d_history": len(common_margin_short_days) >= 60,
        "has_mops_event_latest": bool(latest_reference_day and latest_reference_day in sorted_mops_days),
        "has_mops_event_7d_history": _has_recent_calendar_days(latest_mops_day, mops_event_day_set, 7),
        "has_mops_event_30d_history": _has_recent_calendar_days(latest_mops_day, mops_event_day_set, 30),
        "has_mops_event_90d_history": _has_recent_calendar_days(latest_mops_day, mops_event_day_set, 90),
    }


def build_symbol_history_coverage(
    root: Path,
    target_trading_days: int,
) -> dict[str, Any]:
    history = load_history_rows(root, scan_eligible_only=True)
    common_days = sorted(history)
    symbol_days: dict[str, set[str]] = defaultdict(set)
    symbol_markets: dict[str, str] = {}
    for day, rows in history.items():
        for row in rows:
            if not row.symbol or not row.scan_eligible:
                continue
            symbol_days[row.symbol].add(day)
            symbol_markets[row.symbol] = row.market
    symbols: dict[str, dict[str, Any]] = {}
    for symbol in sorted(symbol_days):
        days = sorted(symbol_days[symbol])
        missing = [day for day in common_days if day not in symbol_days[symbol]]
        symbols[symbol] = {
            "market": symbol_markets.get(symbol),
            "available_trading_days": len(days),
            "earliest_market_data_date": days[0] if days else None,
            "latest_market_data_date": days[-1] if days else None,
            "coverage_pct": (
                round(len(days) / len(common_days) * 100, 4)
                if common_days
                else 0.0
            ),
            "missing_trading_day_count": len(missing),
            "missing_trading_days_sample": missing[:20],
        }
    counts = [item["available_trading_days"] for item in symbols.values()]
    return {
        "schema_version": SCHEMA_VERSION,
        "target_trading_days": target_trading_days,
        "universe": "scan_eligible_common_stocks",
        "available_trading_days": len(common_days),
        "earliest_market_data_date": common_days[0] if common_days else None,
        "latest_market_data_date": common_days[-1] if common_days else None,
        "symbol_count": len(symbols),
        "symbols_with_126d_history": sum(count >= 126 for count in counts),
        "symbols_with_252d_history": sum(count >= 252 for count in counts),
        "symbols_with_target_history": sum(
            count >= target_trading_days for count in counts
        ),
        "symbols": symbols,
    }


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _csv_has_data_row(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            return next(reader, None) is not None
    except (OSError, UnicodeDecodeError, csv.Error):
        return False


def _has_recent_calendar_days(latest_day: date | None, available_days: set[str], required_days: int) -> bool:
    if latest_day is None:
        return False
    return all((latest_day - timedelta(days=offset)).isoformat() in available_days for offset in range(required_days))
