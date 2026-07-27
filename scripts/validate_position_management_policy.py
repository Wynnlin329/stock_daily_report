#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.position_management import (
    load_position_management_policy,
    validate_position_management_policy,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the simulated position management policy."
    )
    parser.add_argument("--root", default=".", help="Repository root.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    policy = load_position_management_policy(Path(args.root).resolve())
    errors = validate_position_management_policy(policy)
    print(
        json.dumps(
            {
                "valid": not errors,
                "policy_id": policy.get("policy_id"),
                "version": policy.get("version"),
                "official_model": policy.get("official_model"),
                "shadow_models": policy.get("shadow_models"),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
