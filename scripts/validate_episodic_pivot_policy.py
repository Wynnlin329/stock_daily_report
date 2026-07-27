#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.episodic_pivot import (
    load_episodic_pivot_policy,
    validate_episodic_pivot_policy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the independent Episodic Pivot policy."
    )
    parser.add_argument("--root", default=".", help="Repository root.")
    return parser.parse_args()


def main() -> int:
    root = Path(parse_args().root).resolve()
    policy = load_episodic_pivot_policy(root)
    errors = validate_episodic_pivot_policy(policy)
    print(
        json.dumps(
            {
                "valid": not errors,
                "policy_id": policy.get("policy_id"),
                "version": policy.get("version"),
                "status": policy.get("status"),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
