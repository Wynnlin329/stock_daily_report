#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.grading_policy_v2 import (
    grade_symbol_v2_shadow,
    load_grading_policy_v2,
    validate_grading_policy_v2,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the v2 shadow grading policy.")
    parser.add_argument("--root", default=".", help="Repository root.")
    parser.add_argument("--dry-run-limit", type=int, default=5)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    policy = load_grading_policy_v2(root)
    errors = validate_grading_policy_v2(policy)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    daily_path = root / "data" / "chatgpt" / "daily-qullamaggie-source-compact.json"
    daily = json.loads(daily_path.read_text(encoding="utf-8")) if daily_path.exists() else {}
    candidates = _unique_candidates(daily)
    market_regime = (
        daily.get("market_context", {})
        .get("market_regime", {})
        .get("status", "insufficient_data")
    )
    dry_run: list[dict[str, object]] = []
    for candidate in candidates[: args.dry_run_limit]:
        symbol = str(candidate["symbol"])
        symbol_path = root / "data" / "chatgpt" / "symbols" / f"{symbol}.json"
        if not symbol_path.exists():
            continue
        symbol_payload = json.loads(symbol_path.read_text(encoding="utf-8"))
        result = grade_symbol_v2_shadow(
            symbol_payload, candidate, market_regime, policy
        )
        dry_run.append(
            {
                "symbol": symbol,
                "grade_v2_shadow": result["grade_v2_shadow"],
                "score_v2_shadow": result["score_v2_shadow"],
                "missing_fields": result["missing_fields"],
            }
        )
    print(
        json.dumps(
            {
                "valid": True,
                "policy_id": policy["policy_id"],
                "version": policy["version"],
                "status": policy["status"],
                "dry_run": dry_run,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _unique_candidates(payload: dict[str, object]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen: set[str] = set()
    for group in (
        "top_candidates",
        "breakout",
        "episodic_pivot",
        "anticipation",
        "extended_watch",
        "failed_breakout",
    ):
        for item in payload.get(group, []):  # type: ignore[union-attr]
            symbol = str(item.get("symbol") or "")
            if symbol and symbol not in seen:
                seen.add(symbol)
                candidates.append(item)
    return candidates


if __name__ == "__main__":
    raise SystemExit(main())
