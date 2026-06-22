from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .config import SCHEMA_VERSION, TIMEZONE

ACTIONABLE_SETUPS = {"breakout", "episodic_pivot", "anticipation"}
TOP_WEEKLY_LIMIT = 50


def screening_history_path(root: Path, report_date: str) -> Path:
    year, month, _day = report_date.split("-")
    return root / "data" / "screening" / year / month / f"{report_date}-screening-summary.json"


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
        "generated_at": report.get("generated_at"),
        "timezone": TIMEZONE,
        "data_freshness": report.get("data_freshness", {}),
        "scan_readiness": report.get("scan_readiness", {}),
        "source_urls": _source_urls(artifact_urls),
        "market_context": {
            "latest_market_data_date": report.get("latest_market_data_date"),
            "market_is_trading_day": report.get("market_is_trading_day", False),
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

    allowed_actions = [
        "可產生資料狀態報告",
        "可產生候選股研究清單",
        "可更新觀察名單",
    ]
    if readiness.get("can_use_mops_catalyst"):
        allowed_actions.append("可做 MOPS 事件人工複核")
    blocked_actions: list[str] = []
    if not can_create:
        blocked_actions.append("不得產生新的模擬候選")
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
    missing_dates: list[str] = []
    limitations: list[str] = []
    if len(dates) < 5:
        limitations.append("最近 5 個交易日 screening summary 歷史不足。")
    weekly_summary = _weekly_setup_summary(screening_payloads)
    weekly_support = _weekly_supporting_data(screening_payloads)
    watchlist = _next_week_watchlist(weekly_summary, screening_payloads)
    can_review = len(dates) >= 5
    reasons = [] if can_review else ["最近 5 個交易日資料不足，週度複盤僅可輸出部分觀察。"]
    return {
        "schema_version": SCHEMA_VERSION,
        "week_end_date": report.get("report_date"),
        "generated_at": report.get("generated_at"),
        "timezone": TIMEZONE,
        "source_urls": _source_urls(report.get("artifact_urls", {})),
        "week_data_status": {
            "available_trading_days": len(dates),
            "dates": dates,
            "missing_dates": missing_dates,
            "limitations": limitations,
        },
        "weekly_setup_summary": weekly_summary,
        "weekly_supporting_data": weekly_support,
        "next_week_watchlist_candidates": watchlist,
        "paper_trading_weekly_review_gate": {
            "can_generate_weekly_review": can_review,
            "reason": reasons,
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
    repeated = [
        {**latest_by_symbol[symbol], "seen_count": count}
        for symbol, count in symbol_counter.most_common()
        if count >= 2 and symbol in latest_by_symbol
    ][:TOP_WEEKLY_LIMIT]
    return {
        "setup_counts": dict(setup_counts),
        "repeated_candidates": repeated,
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
        "chatgpt_weekly_qullamaggie_source",
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
