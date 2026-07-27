#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.orh_shadow import (
    load_orh_shadow_policy,
    validate_orh_shadow_policy,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the disabled ORH shadow policy.")
    parser.add_argument("--root", default=".", help="Repository root.")
    root = Path(parser.parse_args().root).resolve()
    policy = load_orh_shadow_policy(root)
    errors = validate_orh_shadow_policy(policy)
    print(
        json.dumps(
            {
                "valid": not errors,
                "policy_id": policy.get("policy_id"),
                "version": policy.get("version"),
                "status": policy.get("status"),
                "data_reliability_gate_passed": policy.get(
                    "data_reliability_gate", {}
                ).get("passed"),
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
