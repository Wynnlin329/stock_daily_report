#!/usr/bin/env python
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.config import HISTORY_MINIMUM_READY_TRADING_DAYS


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate generated stock-health JSON artifacts."
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--minimum-history-days",
        type=int,
        default=HISTORY_MINIMUM_READY_TRADING_DAYS,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    errors = validate_generated_artifacts(root, args.minimum_history_days)
    if errors:
        for error in errors:
            print(f"ERROR {error}", file=sys.stderr)
        return 1
    print(
        f"Validated generated artifacts with at least "
        f"{args.minimum_history_days} common trading days."
    )
    return 0


def validate_generated_artifacts(
    root: Path,
    minimum_history_days: int,
) -> list[str]:
    errors: list[str] = []
    payloads: dict[str, dict[str, Any]] = {}
    required_paths = [
        "latest.json",
        "data/history-index.json",
        "data/history-coverage.json",
        "data/chatgpt/symbol-index.json",
        "data/chatgpt/symbol-index-compact.json",
        "data/chatgpt/schedule-readiness.json",
    ]
    for relative_path in required_paths:
        path = root / relative_path
        if not path.is_file() or path.stat().st_size <= 0:
            errors.append(f"missing_or_empty:{relative_path}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid_json:{relative_path}:{exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"json_root_not_object:{relative_path}")
            continue
        payloads[relative_path] = payload

    history = payloads.get("data/history-index.json", {})
    available_days = int(history.get("available_trading_days") or 0)
    if available_days < minimum_history_days:
        errors.append(
            f"history_incomplete:{available_days}/{minimum_history_days}"
        )

    full_index = payloads.get("data/chatgpt/symbol-index.json", {})
    compact_index = payloads.get("data/chatgpt/symbol-index-compact.json", {})
    readiness = payloads.get("data/chatgpt/schedule-readiness.json", {})
    symbol_count = int(full_index.get("symbol_count") or 0)
    if symbol_count <= 0:
        errors.append("symbol_index_empty")
    if compact_index.get("symbol_count") != symbol_count:
        errors.append("compact_symbol_count_mismatch")
    full_reference = compact_index.get("full_index") or {}
    full_path = root / str(
        full_reference.get("path") or "data/chatgpt/symbol-index.json"
    )
    try:
        full_bytes = full_path.read_bytes()
    except OSError:
        errors.append("missing_full_symbol_index")
    else:
        if full_reference.get("byte_size") != len(full_bytes):
            errors.append("full_symbol_index_size_mismatch")
        if full_reference.get("blob_sha") != _git_blob_sha(full_bytes):
            errors.append("full_symbol_index_blob_sha_mismatch")
    if readiness.get("symbol_count") != symbol_count:
        errors.append("readiness_symbol_count_mismatch")
    if readiness.get("available_trading_days") != available_days:
        errors.append("readiness_history_day_count_mismatch")
    if bool(readiness.get("has_252d_history")) != (available_days >= 252):
        errors.append("readiness_252d_flag_mismatch")

    compact_entries = _compact_entries(root, compact_index, errors)
    if len(compact_entries) != symbol_count:
        errors.append("compact_entry_count_mismatch")
    for item in compact_entries:
        relative_path = str(item.get("path") or "")
        path = root / relative_path
        if not path.is_file() or path.stat().st_size <= 0:
            errors.append(f"missing_or_empty_symbol:{item.get('symbol')}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid_symbol_json:{item.get('symbol')}:{exc}")
            continue
        if payload.get("symbol") != item.get("symbol"):
            errors.append(f"symbol_payload_mismatch:{item.get('symbol')}")
        if payload.get("market_data_date") != compact_index.get(
            "market_data_date"
        ):
            errors.append(f"symbol_market_data_date_mismatch:{item.get('symbol')}")

    dates = {
        payload.get("market_data_date")
        for payload in (
            payloads.get("latest.json", {}),
            full_index,
            compact_index,
            readiness,
        )
        if payload.get("market_data_date") is not None
    }
    if len(dates) > 1:
        errors.append(f"market_data_date_mismatch:{sorted(dates)}")
    return errors


def _compact_entries(
    root: Path,
    compact_index: dict[str, Any],
    errors: list[str],
) -> list[dict[str, Any]]:
    if not compact_index.get("sharded"):
        return list(compact_index.get("symbols") or [])
    entries: list[dict[str, Any]] = []
    for reference in compact_index.get("shards") or []:
        relative_path = str(reference.get("path") or "")
        path = root / relative_path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"invalid_shard:{relative_path}:{exc}")
            continue
        entries.extend(payload.get("symbols") or [])
    return entries


def _git_blob_sha(content: bytes) -> str:
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
