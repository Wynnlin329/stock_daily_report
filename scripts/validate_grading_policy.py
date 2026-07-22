from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.grading_policy import grade_symbol, load_grading_policy, validate_grading_policy


LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the Qullamaggie grading policy and dry-run current artifacts")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--dry-run-symbols", type=int, default=5, help="Number of current symbol artifacts to map")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    root = Path(args.root).resolve()
    policy = load_grading_policy(root)
    errors = validate_grading_policy(policy)
    if errors:
        for error in errors:
            LOGGER.error("Policy validation failed: %s", error)
        return 1

    daily = _read_json(root / "data/chatgpt/daily-qullamaggie-source-compact.json")
    candidates = _current_candidates(root, daily)
    if len(candidates) < args.dry_run_symbols:
        LOGGER.error("Only %d current candidates are available for dry-run", len(candidates))
        return 1

    market_regime = daily.get("market_context", {}).get("market_regime", {}).get("status")
    dry_run: list[dict[str, Any]] = []
    for candidate in candidates[: args.dry_run_symbols]:
        symbol = str(candidate["symbol"])
        symbol_payload = _read_json(root / f"data/chatgpt/symbols/{symbol}.json")
        result = grade_symbol(symbol_payload, candidate, market_regime, policy)
        dry_run.append(
            {
                "symbol": symbol,
                "name": symbol_payload.get("name"),
                "setup_type": result["setup_type"],
                "grade_score_v1": result["grade_score_v1"],
                "final_grade": result["final_grade"],
                "market_regime": result["market_regime"],
                "action_status": result["action_status"],
                "applied_caps": result["applied_caps"],
                "missing_fields": result["missing_fields"],
                "data_errors": result["data_errors"],
            }
        )

    print(json.dumps({"policy_valid": True, "dry_run": dry_run}, ensure_ascii=False, indent=2))
    return 0


def _current_candidates(root: Path, daily: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in ("top_candidates", "breakout", "episodic_pivot", "anticipation", "extended_watch", "failed_breakout"):
        for candidate in daily.get(group, []):
            symbol = str(candidate.get("symbol", ""))
            if symbol and symbol not in seen and (root / f"data/chatgpt/symbols/{symbol}.json").exists():
                seen.add(symbol)
                output.append(candidate)
    return output


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


if __name__ == "__main__":
    raise SystemExit(main())
