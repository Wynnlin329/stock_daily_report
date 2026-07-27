from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, TIMEZONE, github_raw_url

ACTIONABLE_SETUPS = {"breakout", "episodic_pivot", "anticipation"}
TOP_WEEKLY_LIMIT = 50
SYMBOL_SCHEMA_VERSION = "1.2"
COMPACT_SIZE_LIMIT_BYTES = 1_048_576
SYMBOL_TECHNICAL_FIELDS = [
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "ma10",
    "ma20",
    "ma50",
    "avg_volume_20d",
    "volume_ratio_20d",
    "pivot_price",
    "stop_reference",
    "adr20_pct",
    "atr14",
    "atr14_pct",
    "stop_risk_pct",
    "stop_to_adr_ratio",
    "stop_to_atr_ratio",
    "return_1m",
    "return_3m",
    "return_6m",
    "rs_rank_1m",
    "rs_rank_3m",
    "rs_rank_6m",
    "composite_rs_rank",
    "missing_reason",
    "indicator_basis",
    "setup_type",
    "extended_risk",
    "risk_notes",
]


def screening_history_path(root: Path, report_date: str) -> Path:
    year, month, _day = report_date.split("-")
    return root / "data" / "screening" / year / month / f"{report_date}-screening-summary.json"


def symbol_file_path(root: Path, symbol: str) -> Path:
    return root / "data" / "chatgpt" / "symbols" / f"{symbol}.json"


def screening_history_index_path(root: Path) -> Path:
    return root / "data" / "screening" / "history-index.json"


def build_daily_qullamaggie_source(
    report: dict[str, Any],
    screening_summary: dict[str, Any],
    institutional_summary: dict[str, Any],
    margin_short_summary: dict[str, Any],
    mops_summary: dict[str, Any],
    history_index: dict[str, Any],
) -> dict[str, Any]:
    qullamaggie = screening_summary.get("qullamaggie", {})
    candidates = qullamaggie.get("candidates", {})
    setup_counts = {setup: len(candidates.get(setup, [])) for setup in _setup_names()}
    artifact_urls = report.get("artifact_urls", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "report_date": report.get("report_date"),
        "as_of_date": report.get("as_of_date") or screening_summary.get("as_of_date"),
        "market_data_date": report.get("market_data_date") or screening_summary.get("market_data_date"),
        "generated_at": report.get("generated_at"),
        "timezone": TIMEZONE,
        "data_freshness": report.get("data_freshness", {}),
        "scan_readiness": report.get("scan_readiness", {}),
        "source_urls": _source_urls(artifact_urls),
        "market_context": {
            "latest_market_data_date": report.get("latest_market_data_date"),
            "as_of_date": report.get("as_of_date") or screening_summary.get("as_of_date"),
            "market_data_date": report.get("market_data_date") or screening_summary.get("market_data_date"),
            "market_is_trading_day": report.get("market_is_trading_day", False),
            "market_data_is_trading_day": report.get("market_data_is_trading_day", False),
            "market_regime": qullamaggie.get("market_regime", {}),
            "market_summary": screening_summary.get("market_summary", {}),
            "universe_summary": screening_summary.get("universe_summary", {}),
        },
        "data_status": {
            "ohlcv": {
                "listed": screening_summary.get("coverage", {}).get("listed_ohlcv", {}),
                "otc": screening_summary.get("coverage", {}).get("otc_ohlcv", {}),
            },
            "historical": screening_summary.get("historical_data_status", {}),
            "institutional": {
                "status": screening_summary.get("institutional_data_status", {}),
                "summary": _summary_status(institutional_summary),
            },
            "margin_short": {
                "status": screening_summary.get("margin_short_data_status", {}),
                "summary": _summary_status(margin_short_summary),
            },
            "mops": {
                "status": screening_summary.get("mops_event_data_status", {}),
                "summary": _summary_status(mops_summary),
            },
            "history_index": {
                "available_trading_days": history_index.get("available_trading_days", 0),
                "has_60d_history": history_index.get("has_60d_history", False),
                "has_126d_history": history_index.get("has_126d_history", False),
                "has_mops_event_90d_history": history_index.get("has_mops_event_90d_history", False),
            },
        },
        "qullamaggie_style": {
            "naming_note": "This is a rules-based Qullamaggie-style research screen. It is not affiliated with or endorsed by Qullamaggie.",
            "market_regime": qullamaggie.get("market_regime", {}),
            "setup_counts": setup_counts,
            "top_candidates": qullamaggie.get("top_candidates", []),
            "breakout": candidates.get("breakout", []),
            "episodic_pivot": candidates.get("episodic_pivot", []),
            "anticipation": candidates.get("anticipation", []),
            "extended_watch": candidates.get("extended_watch", []),
            "failed_breakout": candidates.get("failed_breakout", []),
            "limitations": qullamaggie.get("limitations", []),
            "indicator_coverage": qullamaggie.get("indicator_coverage", {}),
        },
        "paper_trading_decision_gate": build_paper_trading_decision_gate(report, screening_summary),
        "supporting_candidates": {
            "institutional_buy_candidates": screening_summary.get("screening", {}).get("institutional_buy_candidates", []),
            "margin_short_attention": screening_summary.get("screening", {}).get("margin_short_attention", []),
            "mops_event_candidates": screening_summary.get("screening", {}).get("mops_event_candidates", []),
        },
        "reporting_rules": {
            "do_not_crawl_external_sites": True,
            "do_not_generate_real_trade_advice": True,
            "mops_is_catalyst_only": True,
            "institutional_is_confirmation_only": True,
            "margin_short_is_risk_review_only": True,
        },
    }


def build_symbol_technical_payloads(
    report: dict[str, Any],
    symbol_candidates: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    payloads: dict[str, dict[str, Any]] = {}
    for candidate in sorted(symbol_candidates, key=lambda item: item.get("symbol", "")):
        symbol = str(candidate.get("symbol") or "")
        if not symbol:
            continue
        data_quality = _symbol_data_quality(candidate)
        payload = {
            "schema_version": SYMBOL_SCHEMA_VERSION,
            "symbol": symbol,
            "name": candidate.get("name"),
            "market": candidate.get("market"),
            "security_type": candidate.get("security_type"),
            "scan_eligible": candidate.get("scan_eligible"),
            "report_date": report.get("report_date"),
            "as_of_date": report.get("as_of_date") or candidate.get("date"),
            "market_data_date": report.get("market_data_date") or candidate.get("date"),
            "generated_at": report.get("generated_at"),
            "timezone": TIMEZONE,
            "source_url": github_raw_url(f"data/chatgpt/symbols/{symbol}.json"),
            "data_quality": data_quality,
        }
        for field in SYMBOL_TECHNICAL_FIELDS:
            payload[field] = candidate.get(field)
        payloads[symbol] = payload
    return payloads


def build_symbol_index(report: dict[str, Any], symbol_payloads: dict[str, dict[str, Any]]) -> dict[str, Any]:
    symbols = [
        {
            "symbol": symbol,
            "name": payload.get("name"),
            "market": payload.get("market"),
            "setup_type": payload.get("setup_type"),
            "extended_risk": payload.get("extended_risk"),
            "ohlcv_complete": bool(payload.get("data_quality", {}).get("ohlcv_complete")),
            "technical_indicators_complete": bool(payload.get("data_quality", {}).get("technical_indicators_complete")),
            "enhanced_indicators_complete": bool(payload.get("data_quality", {}).get("enhanced_indicators_complete")),
            "path": f"data/chatgpt/symbols/{symbol}.json",
            "url": payload.get("source_url"),
        }
        for symbol, payload in sorted(symbol_payloads.items())
    ]
    complete_ohlcv_count = sum(1 for item in symbols if item["ohlcv_complete"])
    complete_technical_count = sum(1 for item in symbols if item["technical_indicators_complete"])
    complete_enhanced_count = sum(1 for item in symbols if item["enhanced_indicators_complete"])
    return {
        "schema_version": SYMBOL_SCHEMA_VERSION,
        "report_date": report.get("report_date"),
        "as_of_date": report.get("as_of_date"),
        "market_data_date": report.get("market_data_date"),
        "generated_at": report.get("generated_at"),
        "timezone": TIMEZONE,
        "symbol_count": len(symbols),
        "complete_ohlcv_count": complete_ohlcv_count,
        "incomplete_ohlcv_count": len(symbols) - complete_ohlcv_count,
        "complete_technical_indicators_count": complete_technical_count,
        "incomplete_technical_indicators_count": len(symbols) - complete_technical_count,
        "complete_enhanced_indicators_count": complete_enhanced_count,
        "incomplete_enhanced_indicators_count": len(symbols) - complete_enhanced_count,
        "enhanced_indicator_coverage_pct": round(complete_enhanced_count / len(symbols) * 100, 4) if symbols else 0.0,
        "incomplete_ohlcv_symbols": [item["symbol"] for item in symbols if not item["ohlcv_complete"]],
        "symbols": symbols,
    }


def build_paper_trading_decision_gate(report: dict[str, Any], screening_summary: dict[str, Any]) -> dict[str, Any]:
    readiness = report.get("scan_readiness", {})
    freshness = report.get("data_freshness", {})
    coverage = report.get("coverage", {})
    qullamaggie = screening_summary.get("qullamaggie", {})
    top_candidates = qullamaggie.get("top_candidates", [])
    actionable = [
        candidate
        for candidate in top_candidates
        if candidate.get("setup_type") in ACTIONABLE_SETUPS and candidate.get("setup_type") != "insufficient_data"
    ]
    can_create = (
        bool(readiness.get("can_generate_new_paper_trade_candidate"))
        and bool(actionable)
        and bool(freshness.get("is_latest_trading_data_current"))
    )
    reasons = list(readiness.get("reasons") or [])
    if not coverage.get("listed_ohlcv", {}).get("available"):
        reasons.append("上市 OHLCV 不完整")
    if not coverage.get("otc_ohlcv", {}).get("available"):
        reasons.append("上櫃 OHLCV 不完整")
    market_regime = qullamaggie.get("market_regime", {})
    if market_regime.get("status") == "insufficient_data":
        reasons.append("Qullamaggie market_regime insufficient_data")
    if not actionable:
        reasons.append("沒有 breakout / episodic_pivot / anticipation candidate")
    if not freshness.get("is_latest_trading_data_current"):
        reasons.append(str(freshness.get("reason") or "latest market data is not current"))
    if not readiness.get("can_use_institutional_confirmation"):
        reasons.append("法人資料不可用，僅停用法人確認")
    if not readiness.get("can_use_margin_short_risk"):
        reasons.append("資券資料不可用，僅停用資券風險")
    if not readiness.get("can_use_mops_catalyst"):
        reasons.append("MOPS 不可用或歷史不足，僅停用事件延續性判斷")

    can_update_watchlist = bool(readiness.get("can_generate_new_paper_trade_candidate")) and bool(
        freshness.get("is_latest_trading_data_current")
    )
    allowed_actions = [
        "可產生資料狀態報告",
        "可產生候選股研究清單",
    ]
    if can_update_watchlist:
        allowed_actions.append("可更新觀察名單")
    if readiness.get("can_use_mops_catalyst"):
        allowed_actions.append("可做 MOPS 事件人工複核")
    blocked_actions: list[str] = []
    if not can_create:
        blocked_actions.append("不得產生新的模擬候選")
        blocked_actions.append("不得新增、移除或取消 Watchlist / Pending / 候選項目")
        blocked_actions.append("不得建立新的 TradePlan")
    if not readiness.get("can_use_institutional_confirmation"):
        blocked_actions.append("不得宣稱法人確認")
    if not readiness.get("can_use_margin_short_risk"):
        blocked_actions.append("不得宣稱資券風險已驗證")
    if market_regime.get("status") == "insufficient_data":
        blocked_actions.append("不得宣稱完整市場順風")
    return {
        "can_create_new_simulated_buy_candidate": can_create,
        "reason": list(dict.fromkeys(reasons)),
        "allowed_actions": allowed_actions,
        "blocked_actions": blocked_actions,
    }


def load_recent_screening_summaries(root: Path, limit: int = 5) -> list[dict[str, Any]]:
    indexed_dates = _screening_dates_from_index(root, limit)
    if indexed_dates:
        payloads = []
        for report_date in indexed_dates:
            path = screening_history_path(root, report_date)
            try:
                payloads.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        if payloads:
            return sorted(payloads, key=lambda item: item.get("report_date", ""))

    screening_dir = root / "data" / "screening"
    if not screening_dir.exists():
        return []
    payloads: list[dict[str, Any]] = []
    for path in sorted(screening_dir.glob("*/*/*-screening-summary.json"), reverse=True):
        try:
            payloads.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
        if len(payloads) >= limit:
            break
    return sorted(payloads, key=lambda item: item.get("report_date", ""))


def build_weekly_qullamaggie_source(
    report: dict[str, Any],
    screening_payloads: list[dict[str, Any]],
) -> dict[str, Any]:
    dates = [payload.get("report_date") for payload in screening_payloads if payload.get("report_date")]
    valid_payloads = [payload for payload in screening_payloads if _screening_payload_valid(payload)]
    valid_dates = [payload.get("report_date") for payload in valid_payloads if payload.get("report_date")]
    missing_dates: list[str] = []
    invalid_dates = [day for day in dates if day not in set(valid_dates)]
    limitations: list[str] = []
    if len(valid_dates) < 5:
        limitations.append("最近 5 個交易日 screening summary 歷史不足。")
    if invalid_dates:
        limitations.append("部分 screening summary 未通過 as-of 或 schema 檢查。")
    weekly_summary = _weekly_setup_summary(valid_payloads)
    weekly_support = _weekly_supporting_data(valid_payloads)
    watchlist = _next_week_watchlist(weekly_summary, valid_payloads)
    can_review = len(valid_dates) >= 5 and not invalid_dates
    reasons = [] if can_review else ["最近 5 個有效交易日資料不足，週度複盤僅可輸出部分觀察。"]
    return {
        "schema_version": SCHEMA_VERSION,
        "week_end_date": report.get("as_of_date") or report.get("market_data_date") or report.get("report_date"),
        "report_date": report.get("report_date"),
        "as_of_date": report.get("as_of_date"),
        "market_data_date": report.get("market_data_date"),
        "generated_at": report.get("generated_at"),
        "timezone": TIMEZONE,
        "source_urls": _source_urls(report.get("artifact_urls", {})),
        "week_data_status": {
            "available_trading_days": len(valid_dates),
            "required_trading_days": 5,
            "dates": valid_dates,
            "missing_dates": missing_dates,
            "invalid_dates": invalid_dates,
            "has_complete_5d_history": can_review,
            "limitations": limitations,
        },
        "weekly_setup_summary": weekly_summary,
        "indicator_coverage": (
            valid_payloads[-1].get("qullamaggie", {}).get("indicator_coverage", {}) if valid_payloads else {}
        ),
        "weekly_supporting_data": weekly_support,
        "next_week_watchlist_candidates": watchlist,
        "paper_trading_weekly_review_gate": {
            "can_generate_weekly_review": can_review,
            "reason": reasons,
        },
    }


def build_daily_qullamaggie_compact(payload: dict[str, Any]) -> dict[str, Any]:
    q = payload.get("qullamaggie_style", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "report_date": payload.get("report_date"),
        "as_of_date": payload.get("as_of_date"),
        "market_data_date": payload.get("market_data_date"),
        "generated_at": payload.get("generated_at"),
        "timezone": payload.get("timezone"),
        "data_freshness": payload.get("data_freshness", {}),
        "scan_readiness": payload.get("scan_readiness", {}),
        "source_urls": payload.get("source_urls", {}),
        "market_context": payload.get("market_context", {}),
        "setup_counts": q.get("setup_counts", {}),
        "indicator_coverage": q.get("indicator_coverage", {}),
        "top_candidates": [_compact_candidate(item) for item in q.get("top_candidates", [])[:100]],
        "breakout": [_compact_candidate(item) for item in q.get("breakout", [])[:100]],
        "episodic_pivot": [_compact_candidate(item) for item in q.get("episodic_pivot", [])[:100]],
        "anticipation": [_compact_candidate(item) for item in q.get("anticipation", [])[:100]],
        "extended_watch": [_compact_candidate(item) for item in q.get("extended_watch", [])[:100]],
        "failed_breakout": [_compact_candidate(item) for item in q.get("failed_breakout", [])[:100]],
        "paper_trading_decision_gate": payload.get("paper_trading_decision_gate", {}),
    }


def build_weekly_qullamaggie_compact(payload: dict[str, Any]) -> dict[str, Any]:
    weekly = payload.get("weekly_setup_summary", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "week_end_date": payload.get("week_end_date"),
        "report_date": payload.get("report_date"),
        "as_of_date": payload.get("as_of_date"),
        "market_data_date": payload.get("market_data_date"),
        "generated_at": payload.get("generated_at"),
        "timezone": payload.get("timezone"),
        "source_urls": payload.get("source_urls", {}),
        "week_data_status": payload.get("week_data_status", {}),
        "setup_counts": weekly.get("setup_counts", {}),
        "indicator_coverage": payload.get("indicator_coverage", {}),
        "repeated_candidates": [_compact_weekly_candidate(item) for item in weekly.get("repeated_candidates", [])[:100]],
        "setup_transitions": weekly.get("setup_transitions", [])[:100],
        "next_week_watchlist_candidates": [
            _compact_weekly_candidate(item) for item in payload.get("next_week_watchlist_candidates", [])[:100]
        ],
        "paper_trading_weekly_review_gate": payload.get("paper_trading_weekly_review_gate", {}),
    }


def build_screening_history_index(
    root: Path,
    generated_at: str,
    common_ohlcv_days: list[str],
    required_trading_days: int = 5,
) -> dict[str, Any]:
    latest_days = list(common_ohlcv_days[-required_trading_days:])
    files: list[dict[str, Any]] = []
    valid_dates: list[str] = []
    missing_dates: list[str] = []
    invalid_dates: list[str] = []
    for report_date in latest_days:
        path = screening_history_path(root, report_date)
        rel_path = path.relative_to(root).as_posix()
        if not path.exists():
            files.append({"date": report_date, "path": rel_path, "exists": False, "valid": False, "errors": ["missing_file"]})
            missing_dates.append(report_date)
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            files.append({"date": report_date, "path": rel_path, "exists": True, "valid": False, "errors": [str(exc)]})
            invalid_dates.append(report_date)
            continue
        errors = _screening_payload_errors(payload, report_date)
        valid = not errors
        files.append({"date": report_date, "path": rel_path, "exists": True, "valid": valid, "errors": errors})
        if valid:
            valid_dates.append(report_date)
        else:
            invalid_dates.append(report_date)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "required_trading_days": required_trading_days,
        "latest_5_trading_days": latest_days,
        "valid_dates": valid_dates,
        "missing_dates": missing_dates,
        "invalid_dates": invalid_dates,
        "available_valid_days": len(valid_dates),
        "has_5d_history": len(valid_dates) >= required_trading_days and not missing_dates and not invalid_dates,
        "files": files,
    }


def attach_screening_as_of_metadata(
    summary: dict[str, Any],
    as_of_date: str,
    used_input_dates: list[str],
    generation_mode: str,
) -> dict[str, Any]:
    latest_input_date = max(used_input_dates) if used_input_dates else None
    future_dates = [day for day in used_input_dates if day > as_of_date]
    summary["as_of_date"] = as_of_date
    summary["generation_mode"] = generation_mode
    summary["lookahead_check"] = {
        "passed": not future_dates,
        "as_of_date": as_of_date,
        "latest_input_date": latest_input_date,
        "future_input_dates": future_dates,
    }
    return summary


def build_schedule_readiness(
    report: dict[str, Any],
    symbol_index: dict[str, Any],
    screening_history_index: dict[str, Any],
    daily_compact: dict[str, Any],
    weekly_compact: dict[str, Any],
) -> dict[str, Any]:
    scan_readiness = report.get("scan_readiness", {})
    freshness = report.get("data_freshness", {})
    daily_compact_size = _json_size_bytes(daily_compact)
    weekly_compact_size = _json_size_bytes(weekly_compact)
    checks = {
        "latest_market_data_current": bool(freshness.get("is_latest_trading_data_current")),
        "technical_scan_ready": bool(scan_readiness.get("can_run_technical_scan")),
        "qullamaggie_scan_ready": bool(scan_readiness.get("can_run_qullamaggie_scan")),
        "daily_compact_source_ready": bool(daily_compact.get("top_candidates") is not None and daily_compact_size < COMPACT_SIZE_LIMIT_BYTES),
        "symbol_index_ready": bool(symbol_index.get("symbol_count", 0) > 0),
        "symbol_ohlcv_complete": bool(symbol_index.get("symbol_count", 0) > 0 and symbol_index.get("incomplete_ohlcv_count") == 0),
        "screening_history_5d_ready": bool(screening_history_index.get("has_5d_history")),
        "weekly_compact_source_ready": bool(weekly_compact.get("week_data_status") is not None and weekly_compact_size < COMPACT_SIZE_LIMIT_BYTES),
        "weekly_review_gate_ready": bool(
            weekly_compact.get("paper_trading_weekly_review_gate", {}).get("can_generate_weekly_review")
        ),
        "enhanced_technical_indicators_complete": bool(
            symbol_index.get("symbol_count", 0) > 0
            and symbol_index.get("incomplete_enhanced_indicators_count") == 0
        ),
    }
    can_switch_daily_scan_schedule = all(
        checks[key]
        for key in (
            "latest_market_data_current",
            "technical_scan_ready",
            "qullamaggie_scan_ready",
            "daily_compact_source_ready",
            "symbol_index_ready",
        )
    )
    can_switch_watchlist_schedule = can_switch_daily_scan_schedule and checks["symbol_index_ready"]
    can_switch_position_management_schedule = all(
        checks[key]
        for key in (
            "symbol_index_ready",
            "symbol_ohlcv_complete",
        )
    )
    can_switch_weekly_review_schedule = all(
        checks[key]
        for key in (
            "screening_history_5d_ready",
            "weekly_compact_source_ready",
            "weekly_review_gate_ready",
        )
    )
    blocking_check_keys = {
        "latest_market_data_current",
        "technical_scan_ready",
        "qullamaggie_scan_ready",
        "daily_compact_source_ready",
        "symbol_index_ready",
        "symbol_ohlcv_complete",
        "screening_history_5d_ready",
        "weekly_compact_source_ready",
        "weekly_review_gate_ready",
    }
    blocking_reasons = [key for key, value in checks.items() if key in blocking_check_keys and not value]
    warnings: list[str] = []
    if not scan_readiness.get("can_use_institutional_confirmation"):
        warnings.append("法人確認停用；不得宣稱法人確認。")
    if not scan_readiness.get("can_use_margin_short_risk"):
        warnings.append("資券風險驗證停用；不得宣稱資券風險已驗證。")
    if not scan_readiness.get("can_use_mops_catalyst"):
        warnings.append("MOPS 催化延續性停用或不足；僅可列為人工複核素材。")
    if symbol_index.get("incomplete_ohlcv_symbols"):
        warnings.append("部分 symbol 技術檔 OHLCV 不完整。")
    if not checks["enhanced_technical_indicators_complete"]:
        warnings.append("部分波動或多期間相對強度指標資料不足；新指標僅供研究，不影響正式 v1 分級與排程 gate。")
    return {
        "schema_version": SCHEMA_VERSION,
        "report_date": report.get("report_date"),
        "as_of_date": report.get("as_of_date"),
        "market_data_date": report.get("market_data_date"),
        "latest_market_data_date": report.get("latest_market_data_date"),
        "generated_at": report.get("generated_at"),
        "timezone": TIMEZONE,
        "checks": checks,
        "non_blocking_checks": ["enhanced_technical_indicators_complete"],
        "enhanced_indicator_completeness": {
            "complete_symbols": symbol_index.get("complete_enhanced_indicators_count", 0),
            "incomplete_symbols": symbol_index.get("incomplete_enhanced_indicators_count", 0),
            "coverage_pct": symbol_index.get("enhanced_indicator_coverage_pct", 0.0),
            "affects_grading_policy_v1": False,
        },
        "compact_sizes": {
            "daily_qullamaggie_source_compact_bytes": daily_compact_size,
            "weekly_qullamaggie_source_compact_bytes": weekly_compact_size,
            "limit_bytes": COMPACT_SIZE_LIMIT_BYTES,
        },
        "schedule_switch": {
            "can_switch_daily_scan_schedule": can_switch_daily_scan_schedule,
            "can_switch_watchlist_schedule": can_switch_watchlist_schedule,
            "can_switch_position_management_schedule": can_switch_position_management_schedule,
            "can_switch_weekly_review_schedule": can_switch_weekly_review_schedule,
            "can_switch_all_schedules": all(
                [
                    can_switch_daily_scan_schedule,
                    can_switch_watchlist_schedule,
                    can_switch_position_management_schedule,
                    can_switch_weekly_review_schedule,
                ]
            ),
        },
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "source_urls": {
            "daily_compact": github_raw_url("data/chatgpt/daily-qullamaggie-source-compact.json"),
            "weekly_compact": github_raw_url("data/chatgpt/weekly-qullamaggie-source-compact.json"),
            "symbol_index": github_raw_url("data/chatgpt/symbol-index.json"),
            "screening_history_index": github_raw_url("data/screening/history-index.json"),
        },
    }


def build_daily_qullamaggie_markdown(payload: dict[str, Any]) -> str:
    q = payload.get("qullamaggie_style", {})
    gate = payload.get("paper_trading_decision_gate", {})
    lines = [
        f"# ChatGPT Daily Qullamaggie Source: {payload.get('report_date')}",
        "",
        "本資料包僅供 ChatGPT 排程研究與人工複核，不構成交易建議。",
        "",
        "## 資料日期與 Freshness",
        f"- data_freshness: {payload.get('data_freshness', {})}",
        "",
        "## Scan Readiness",
        f"- scan_readiness: {payload.get('scan_readiness', {})}",
        "",
        "## Qullamaggie Market Regime",
        f"- market_regime: {q.get('market_regime', {})}",
        "",
        "## Setup Counts",
        f"- setup_counts: {q.get('setup_counts', {})}",
        "",
        "## Top Candidates",
        *_candidate_lines(q.get("top_candidates", [])[:20]),
        "",
        "## Paper Trading Decision Gate",
        f"- gate: {gate}",
        "",
        "## Disabled Sections",
        *_disabled_section_lines(gate),
        "",
        "## Source URLs",
        *_url_lines(payload.get("source_urls", {})),
    ]
    return "\n".join(lines).rstrip() + "\n"


def build_weekly_qullamaggie_markdown(payload: dict[str, Any]) -> str:
    weekly_summary = payload.get("weekly_setup_summary", {})
    lines = [
        f"# ChatGPT Weekly Qullamaggie Source: {payload.get('week_end_date')}",
        "",
        "本資料包僅供 ChatGPT 排程週度複盤與觀察名單研究，不構成交易建議。",
        "",
        "## 本週資料日期",
        f"- dates: {payload.get('week_data_status', {}).get('dates', [])}",
        "",
        "## 缺失日期",
        f"- missing_dates: {payload.get('week_data_status', {}).get('missing_dates', [])}",
        "",
        "## 本週 Setup 統計",
        f"- counts: {weekly_summary.get('setup_counts', {})}",
        "",
        "## 重複出現候選",
        *_candidate_lines(weekly_summary.get("repeated_candidates", [])[:20]),
        "",
        "## 本週 Breakout / Failed Breakout",
        *_candidate_lines(weekly_summary.get("breakout_this_week", [])[:20]),
        *_candidate_lines(weekly_summary.get("failed_breakout_this_week", [])[:20]),
        "",
        "## 下週 Watchlist Candidates",
        *_candidate_lines(payload.get("next_week_watchlist_candidates", [])[:20]),
        "",
        "## Weekly Review Gate",
        f"- gate: {payload.get('paper_trading_weekly_review_gate', {})}",
        "",
        "## Source URLs",
        *_url_lines(payload.get("source_urls", {})),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _weekly_setup_summary(payloads: list[dict[str, Any]]) -> dict[str, Any]:
    setup_items: dict[str, list[dict[str, Any]]] = {setup: [] for setup in _setup_names() if setup != "insufficient_data"}
    symbol_counter: Counter[str] = Counter()
    latest_by_symbol: dict[str, dict[str, Any]] = {}
    setup_counts: Counter[str] = Counter()
    appearances: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for payload in payloads:
        report_date = payload.get("report_date")
        candidates = payload.get("qullamaggie", {}).get("candidates", {})
        for setup in _setup_names():
            values = candidates.get(setup, [])
            setup_counts[setup] += len(values)
            if setup == "insufficient_data":
                continue
            for candidate in values:
                item = _candidate_with_seen_date(candidate, report_date)
                setup_items[setup].append(item)
                symbol = candidate.get("symbol")
                if symbol:
                    symbol_counter[symbol] += 1
                    latest_by_symbol[symbol] = item
                    appearances[symbol].append(
                        {
                            "date": report_date,
                            "setup_type": candidate.get("setup_type") or setup,
                            "score": candidate.get("qullamaggie_score"),
                        }
                    )
    repeated = [
        {
            **latest_by_symbol[symbol],
            "seen_count": count,
            "appearance_count": count,
            "dates": [item["date"] for item in appearances[symbol] if item.get("date")],
            "setup_types": [item["setup_type"] for item in appearances[symbol] if item.get("setup_type")],
            "latest_setup_type": latest_by_symbol[symbol].get("setup_type"),
            "latest_score": latest_by_symbol[symbol].get("qullamaggie_score"),
        }
        for symbol, count in symbol_counter.most_common()
        if count >= 2 and symbol in latest_by_symbol
    ][:TOP_WEEKLY_LIMIT]
    return {
        "setup_counts": dict(setup_counts),
        "repeated_candidates": repeated,
        "setup_transitions": _setup_transitions(appearances),
        "breakout_this_week": setup_items.get("breakout", [])[:TOP_WEEKLY_LIMIT],
        "episodic_pivot_this_week": setup_items.get("episodic_pivot", [])[:TOP_WEEKLY_LIMIT],
        "anticipation_this_week": setup_items.get("anticipation", [])[:TOP_WEEKLY_LIMIT],
        "failed_breakout_this_week": setup_items.get("failed_breakout", [])[:TOP_WEEKLY_LIMIT],
        "extended_watch_this_week": setup_items.get("extended_watch", [])[:TOP_WEEKLY_LIMIT],
    }


def _weekly_supporting_data(payloads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    institutional: list[dict[str, Any]] = []
    margin_short: list[dict[str, Any]] = []
    mops: list[dict[str, Any]] = []
    for payload in payloads:
        report_date = payload.get("report_date")
        screening = payload.get("screening", {})
        institutional.extend(_candidate_with_seen_date(item, report_date) for item in screening.get("institutional_buy_candidates", []))
        margin_short.extend(_candidate_with_seen_date(item, report_date) for item in screening.get("margin_short_attention", []))
        mops.extend(_candidate_with_seen_date(item, report_date) for item in screening.get("mops_event_candidates", []))
    return {
        "institutional_5d_summary": institutional[:TOP_WEEKLY_LIMIT],
        "margin_short_5d_risk": margin_short[:TOP_WEEKLY_LIMIT],
        "mops_events_this_week": mops[:TOP_WEEKLY_LIMIT],
    }


def _next_week_watchlist(weekly_summary: dict[str, Any], payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in weekly_summary.get("repeated_candidates", []):
        symbol = item.get("symbol")
        if symbol and symbol not in seen:
            output.append(item)
            seen.add(symbol)
    if payloads:
        for item in payloads[-1].get("qullamaggie", {}).get("top_candidates", []):
            if item.get("setup_type") not in {"breakout", "episodic_pivot", "anticipation", "extended_watch"}:
                continue
            symbol = item.get("symbol")
            if symbol and symbol not in seen:
                output.append(item)
                seen.add(symbol)
            if len(output) >= TOP_WEEKLY_LIMIT:
                break
    return output


def _source_urls(artifact_urls: dict[str, str]) -> dict[str, str]:
    keys = [
        "latest_json",
        "screening_summary",
        "institutional_summary",
        "margin_short_summary",
        "mops_events",
        "index_summary",
        "history_index",
        "market_scan",
        "chatgpt_daily_qullamaggie_source",
        "chatgpt_daily_qullamaggie_compact",
        "chatgpt_weekly_qullamaggie_source",
        "chatgpt_weekly_qullamaggie_compact",
        "chatgpt_symbol_index",
        "chatgpt_schedule_readiness",
        "screening_history_index",
        "chatgpt_daily_qullamaggie_markdown",
        "chatgpt_weekly_qullamaggie_markdown",
    ]
    return {key: artifact_urls.get(key, "") for key in keys if key in artifact_urls}


def _summary_status(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "data_date": payload.get("data_date"),
        "is_current": payload.get("is_current"),
        "status": payload.get("status"),
        "errors": payload.get("errors", []),
        "limitations": payload.get("limitations", []),
    }


def _setup_names() -> list[str]:
    return ["breakout", "episodic_pivot", "anticipation", "extended_watch", "failed_breakout", "insufficient_data"]


def _candidate_with_seen_date(candidate: dict[str, Any], report_date: str | None) -> dict[str, Any]:
    return {**candidate, "seen_date": report_date}


def _symbol_data_quality(candidate: dict[str, Any]) -> dict[str, Any]:
    market = str(candidate.get("market") or "")
    report_date = str(candidate.get("date") or "")
    return {
        "ohlcv_complete": _ohlcv_complete(candidate),
        "technical_indicators_complete": _technical_indicators_complete(candidate),
        "enhanced_indicators_complete": _enhanced_indicators_complete(candidate),
        "enhanced_indicator_missing_reason": candidate.get("missing_reason", {}),
        "source_market_file": _source_market_file(report_date, market),
    }


def _ohlcv_complete(candidate: dict[str, Any]) -> bool:
    open_price = _number(candidate.get("open"))
    high = _number(candidate.get("high"))
    low = _number(candidate.get("low"))
    close = _number(candidate.get("close"))
    volume = _number(candidate.get("volume"))
    if None in (open_price, high, low, close, volume):
        return False
    if close <= 0 or volume <= 0:
        return False
    return bool(high >= low and high >= max(open_price, close) and low <= min(open_price, close))


def _technical_indicators_complete(candidate: dict[str, Any]) -> bool:
    fields = ["ma10", "ma20", "ma50", "avg_volume_20d", "volume_ratio_20d", "pivot_price", "stop_reference"]
    return all(_number(candidate.get(field)) is not None for field in fields)


def _enhanced_indicators_complete(candidate: dict[str, Any]) -> bool:
    fields = [
        "adr20_pct",
        "atr14",
        "atr14_pct",
        "stop_risk_pct",
        "stop_to_adr_ratio",
        "stop_to_atr_ratio",
        "return_1m",
        "return_3m",
        "return_6m",
        "rs_rank_1m",
        "rs_rank_3m",
        "rs_rank_6m",
        "composite_rs_rank",
    ]
    return all(_number(candidate.get(field)) is not None for field in fields)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_market_file(report_date: str, market: str) -> str | None:
    if not report_date:
        return None
    try:
        parsed = date.fromisoformat(report_date)
    except ValueError:
        return None
    suffix = "listed" if market == "listed" else "otc" if market == "otc" else None
    if suffix is None:
        return None
    return f"data/market/{parsed:%Y/%m}/{report_date}-{suffix}-ohlcv.csv"


def _screening_dates_from_index(root: Path, limit: int) -> list[str]:
    path = screening_history_index_path(root)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    dates = [str(day) for day in payload.get("valid_dates", []) if day]
    return dates[-limit:]


def _screening_payload_valid(payload: dict[str, Any]) -> bool:
    report_date = str(payload.get("report_date") or "")
    return not _screening_payload_errors(payload, report_date)


def _screening_payload_errors(payload: dict[str, Any], expected_date: str) -> list[str]:
    errors: list[str] = []
    if payload.get("report_date") != expected_date:
        errors.append("report_date_mismatch")
    if payload.get("as_of_date") and payload.get("as_of_date") != expected_date:
        errors.append("as_of_date_mismatch")
    lookahead = payload.get("lookahead_check", {})
    if lookahead and not lookahead.get("passed"):
        errors.append("lookahead_check_failed")
    if not isinstance(payload.get("qullamaggie"), dict):
        errors.append("missing_qullamaggie")
    else:
        candidates = payload.get("qullamaggie", {}).get("candidates")
        if not isinstance(candidates, dict):
            errors.append("missing_qullamaggie_candidates")
    return errors


def _compact_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    symbol = str(candidate.get("symbol") or "")
    return {
        "symbol": symbol,
        "name": candidate.get("name"),
        "market": candidate.get("market"),
        "setup_type": candidate.get("setup_type"),
        "score": candidate.get("qullamaggie_score"),
        "date": candidate.get("date"),
        "close": candidate.get("close"),
        "volume": candidate.get("volume"),
        "volume_ratio_20d": candidate.get("volume_ratio_20d"),
        "relative_strength_rank": candidate.get("relative_strength_rank"),
        "adr20_pct": candidate.get("adr20_pct"),
        "atr14": candidate.get("atr14"),
        "atr14_pct": candidate.get("atr14_pct"),
        "stop_risk_pct": candidate.get("stop_risk_pct"),
        "stop_to_adr_ratio": candidate.get("stop_to_adr_ratio"),
        "stop_to_atr_ratio": candidate.get("stop_to_atr_ratio"),
        "return_1m": candidate.get("return_1m"),
        "return_3m": candidate.get("return_3m"),
        "return_6m": candidate.get("return_6m"),
        "rs_rank_1m": candidate.get("rs_rank_1m"),
        "rs_rank_3m": candidate.get("rs_rank_3m"),
        "rs_rank_6m": candidate.get("rs_rank_6m"),
        "composite_rs_rank": candidate.get("composite_rs_rank"),
        "missing_reason": candidate.get("missing_reason", {}),
        "pivot_price": candidate.get("pivot_price"),
        "stop_reference": candidate.get("stop_reference"),
        "extended_risk": candidate.get("extended_risk"),
        "risk_notes": candidate.get("risk_notes", []),
        "symbol_data_url": github_raw_url(f"data/chatgpt/symbols/{symbol}.json") if symbol else "",
    }


def _compact_weekly_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    item = _compact_candidate(candidate)
    item.update(
        {
            "seen_date": candidate.get("seen_date"),
            "seen_count": candidate.get("seen_count"),
            "appearance_count": candidate.get("appearance_count"),
            "dates": candidate.get("dates", []),
            "setup_types": candidate.get("setup_types", []),
            "latest_setup_type": candidate.get("latest_setup_type"),
            "latest_score": candidate.get("latest_score"),
        }
    )
    return item


def _setup_transitions(appearances: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    transitions: list[dict[str, Any]] = []
    for symbol, rows in sorted(appearances.items()):
        ordered = sorted([row for row in rows if row.get("date")], key=lambda item: str(item["date"]))
        for previous, current in zip(ordered, ordered[1:]):
            previous_setup = previous.get("setup_type")
            current_setup = current.get("setup_type")
            if previous_setup and current_setup and previous_setup != current_setup:
                transitions.append(
                    {
                        "symbol": symbol,
                        "from_date": previous.get("date"),
                        "to_date": current.get("date"),
                        "from_setup_type": previous_setup,
                        "to_setup_type": current_setup,
                        "transition": f"{previous_setup}->{current_setup}",
                    }
                )
                break
    return transitions[:TOP_WEEKLY_LIMIT]


def _json_size_bytes(payload: dict[str, Any]) -> int:
    return len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _candidate_lines(candidates: list[dict[str, Any]]) -> list[str]:
    if not candidates:
        return ["- 無"]
    return [
        f"- {item.get('symbol')} {item.get('name')} setup={item.get('setup_type')} score={item.get('qullamaggie_score')}"
        for item in candidates
    ]


def _disabled_section_lines(gate: dict[str, Any]) -> list[str]:
    blocked = gate.get("blocked_actions", [])
    return [f"- {item}" for item in blocked] if blocked else ["- 無"]


def _url_lines(urls: dict[str, str]) -> list[str]:
    return [f"- {key}: {value}" for key, value in urls.items()]
