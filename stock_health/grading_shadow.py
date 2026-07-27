from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .config import TIMEZONE
from .grading_policy import grade_symbol, load_grading_policy
from .grading_policy_v2 import grade_symbol_v2_shadow, load_grading_policy_v2


SHADOW_SCHEMA_VERSION = "1.0"
SHADOW_HISTORY_REQUIRED_DAYS = 20


def apply_shadow_grades(
    root: Path,
    symbol_payloads: dict[str, dict[str, Any]],
    symbol_candidates: list[dict[str, Any]],
    screening_summary: dict[str, Any],
    market_regime: str,
) -> dict[str, Any]:
    policy_v1 = load_grading_policy(root)
    policy_v2 = load_grading_policy_v2(root)
    candidates_by_symbol = {
        str(candidate.get("symbol")): candidate
        for candidate in symbol_candidates
        if candidate.get("symbol")
    }
    comparisons: list[dict[str, Any]] = []
    for symbol, symbol_payload in sorted(symbol_payloads.items()):
        candidate = candidates_by_symbol.get(symbol, {})
        v1 = grade_symbol(symbol_payload, candidate, market_regime, policy_v1)
        v2 = grade_symbol_v2_shadow(symbol_payload, candidate, market_regime, policy_v2)
        fields = _comparison_fields(v1, v2)
        symbol_payload.update(fields)
        symbol_payload["grading_v1"] = v1
        symbol_payload["grading_v2_shadow"] = v2
        if candidate:
            candidate.update(fields)
        comparisons.append(
            {
                "symbol": symbol,
                "name": symbol_payload.get("name"),
                "market": symbol_payload.get("market"),
                "setup_type": symbol_payload.get("setup_type"),
                **fields,
            }
        )

    grade_fields_by_symbol = {
        item["symbol"]: {key: item.get(key) for key in _public_grade_fields()}
        for item in comparisons
    }
    _attach_to_qullamaggie_candidates(
        screening_summary.get("qullamaggie", {}), grade_fields_by_symbol
    )
    routing = dict(policy_v2["shadow_routing"])
    summary = _comparison_summary(comparisons)
    screening_summary["grading_policy"] = {
        "official": {
            "policy_id": policy_v1["policy_id"],
            "version": policy_v1["version"],
            "grade_field": "grade_v1",
            "score_field": "score_v1",
        },
        "shadow": {
            "policy_id": policy_v2["policy_id"],
            "version": policy_v2["version"],
            "status": policy_v2["status"],
            "grade_field": "grade_v2_shadow",
            "score_field": "score_v2_shadow",
        },
        "routing": routing,
        "summary": summary,
    }
    return {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "report_date": screening_summary.get("generated_report_date")
        or screening_summary.get("report_date"),
        "as_of_date": screening_summary.get("as_of_date"),
        "market_data_date": screening_summary.get("market_data_date"),
        "generated_at": screening_summary.get("generated_at"),
        "timezone": TIMEZONE,
        "official_policy": screening_summary["grading_policy"]["official"],
        "shadow_policy": screening_summary["grading_policy"]["shadow"],
        "routing": routing,
        "market_regime": market_regime,
        "summary": summary,
        "comparisons": comparisons,
    }


def shadow_history_path(root: Path, market_data_date: str) -> Path:
    year, month, _day = market_data_date.split("-")
    return (
        root
        / "data"
        / "grading-shadow-v2"
        / year
        / month
        / f"{market_data_date}.json"
    )


def shadow_history_index_path(root: Path) -> Path:
    return root / "data" / "grading-shadow-v2" / "history-index.json"


def build_shadow_history_index(
    root: Path,
    generated_at: str,
    required_trading_days: int = SHADOW_HISTORY_REQUIRED_DAYS,
) -> dict[str, Any]:
    base = root / "data" / "grading-shadow-v2"
    entries: list[dict[str, Any]] = []
    for path in sorted(base.glob("*/*/*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            entries.append(
                {
                    "date": path.stem,
                    "path": path.relative_to(root).as_posix(),
                    "valid": False,
                    "errors": [str(exc)],
                }
            )
            continue
        errors = _shadow_payload_errors(payload, path.stem)
        entries.append(
            {
                "date": path.stem,
                "path": path.relative_to(root).as_posix(),
                "valid": not errors,
                "errors": errors,
                "comparison_count": len(payload.get("comparisons", [])),
            }
        )
    valid_entries = [item for item in entries if item["valid"]]
    latest = valid_entries[-required_trading_days:]
    return {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "required_trading_days": required_trading_days,
        "review_horizon_weeks": 12,
        "available_valid_days": len(valid_entries),
        "has_20d_shadow_history": len(valid_entries) >= required_trading_days,
        "valid_dates": [item["date"] for item in valid_entries],
        "latest_20_trading_days": [item["date"] for item in latest],
        "files": entries,
        "limitations": (
            []
            if len(valid_entries) >= required_trading_days
            else [
                "v2 影子資料自啟用日起逐日累積；未滿 20 個交易日前不得宣稱已有 20 日比較結果。"
            ]
        ),
    }


def _comparison_fields(v1: dict[str, Any], v2: dict[str, Any]) -> dict[str, Any]:
    grade_v1 = v1.get("final_grade")
    grade_v2 = v2.get("grade_v2_shadow")
    score_v1 = v1.get("grade_score_v1")
    score_v2 = v2.get("score_v2_shadow")
    if grade_v1 == grade_v2:
        difference = "same"
    else:
        difference = f"{grade_v1}->{grade_v2}"
    return {
        "grade_v1": grade_v1,
        "score_v1": score_v1,
        "grade_v2_shadow": grade_v2,
        "score_v2_shadow": score_v2,
        "grade_difference": difference,
        "v2_rejection_reasons": list(v2.get("v2_rejection_reasons") or []),
    }


def _comparison_summary(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    v1_counts = Counter(str(item.get("grade_v1")) for item in comparisons)
    v2_counts = Counter(str(item.get("grade_v2_shadow")) for item in comparisons)
    changed = sum(1 for item in comparisons if item.get("grade_difference") != "same")
    comparable = sum(
        1
        for item in comparisons
        if item.get("score_v1") is not None and item.get("score_v2_shadow") is not None
    )
    return {
        "total_symbols": len(comparisons),
        "comparable_symbols": comparable,
        "ungraded_v2_symbols": v2_counts.get("Ungraded", 0),
        "grade_changed_symbols": changed,
        "grade_v1_counts": dict(sorted(v1_counts.items())),
        "grade_v2_shadow_counts": dict(sorted(v2_counts.items())),
    }


def _attach_to_qullamaggie_candidates(
    value: Any, grade_fields_by_symbol: dict[str, dict[str, Any]]
) -> None:
    if isinstance(value, dict):
        symbol = str(value.get("symbol") or "")
        if symbol in grade_fields_by_symbol:
            value.update(grade_fields_by_symbol[symbol])
        for child in value.values():
            _attach_to_qullamaggie_candidates(child, grade_fields_by_symbol)
    elif isinstance(value, list):
        for child in value:
            _attach_to_qullamaggie_candidates(child, grade_fields_by_symbol)


def _shadow_payload_errors(payload: dict[str, Any], expected_date: str) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != SHADOW_SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if payload.get("market_data_date") != expected_date:
        errors.append("market_data_date_mismatch")
    routing = payload.get("routing", {})
    if (
        routing.get("watchlist_policy") != "v1"
        or routing.get("tradeplan_policy") != "v1"
        or routing.get("v2_may_drive_business_writes") is not False
    ):
        errors.append("official_routing_not_v1")
    if not isinstance(payload.get("comparisons"), list):
        errors.append("comparisons_missing")
    return errors


def _public_grade_fields() -> tuple[str, ...]:
    return (
        "grade_v1",
        "score_v1",
        "grade_v2_shadow",
        "score_v2_shadow",
        "grade_difference",
        "v2_rejection_reasons",
    )
