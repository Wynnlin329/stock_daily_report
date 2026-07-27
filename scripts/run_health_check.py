#!/usr/bin/env python
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.config import SCHEMA_VERSION, TIMEZONE, github_raw_url
from stock_health.coverage import build_coverage
from stock_health.chatgpt_source import (
    attach_screening_as_of_metadata,
    build_daily_qullamaggie_compact,
    build_daily_qullamaggie_markdown,
    build_daily_qullamaggie_source,
    build_schedule_readiness,
    build_screening_history_index,
    build_symbol_index,
    build_symbol_technical_payloads,
    build_weekly_qullamaggie_compact,
    build_weekly_qullamaggie_markdown,
    build_weekly_qullamaggie_source,
    load_recent_screening_summaries,
    screening_history_path,
    screening_history_index_path,
)
from stock_health.data_fetcher import (
    fetch_tpex_institutional_trading,
    fetch_tpex_index,
    fetch_tpex_margin_short,
    fetch_tpex_otc_ohlcv,
    fetch_mops_events,
    fetch_twse_institutional_trading,
    fetch_twse_taiex_index,
    fetch_twse_listed_ohlcv,
    fetch_twse_margin_short,
    mops_events_payload,
)
from stock_health.history_store import (
    benchmark_history_from_index_rows,
    ensure_dirs,
    history_report_paths,
    load_history_rows,
    load_index_history_rows,
    load_institutional_history_rows,
    load_margin_short_history_rows,
    load_mops_event_history_payloads,
    rebuild_history_index_from_files,
    write_chatgpt_symbol_outputs,
    write_index_outputs,
    write_institutional_outputs,
    write_json,
    write_margin_short_outputs,
    write_mops_event_outputs,
    write_ohlcv_outputs,
    write_text,
)
from stock_health.grading_shadow import (
    apply_shadow_grades,
    build_shadow_history_index,
    shadow_history_index_path,
    shadow_history_path,
)
from stock_health.index_summary import build_index_summary
from stock_health.report_writer import build_health_markdown, build_market_scan_markdown
from stock_health.screening import build_screening_summary
from stock_health.source_health import check_all_sources
from stock_health.trading_calendar import ensure_taipei, expected_market_data_date, is_trading_day

LOGGER = logging.getLogger("stock_health.run_health_check")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Taiwan stock source health check.")
    parser.add_argument("--date", help="Report date in YYYY-MM-DD. Defaults to Asia/Taipei today.")
    parser.add_argument("--root", default=".", help="Repository root.")
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args()
    root = Path(args.root).resolve()
    ensure_dirs(root)
    now = ensure_taipei()
    report_date = date.fromisoformat(args.date) if args.date else now.date()
    market_data_date = date.fromisoformat(args.date) if args.date else expected_market_data_date(now)
    generated_at = now.isoformat(timespec="seconds")
    market_is_trading_day = is_trading_day(report_date)
    market_data_is_trading_day = is_trading_day(market_data_date)

    LOGGER.info("Checking sources for report_date=%s market_data_date=%s", report_date, market_data_date)
    sources = check_all_sources(now, market_data_date)
    listed_result = fetch_twse_listed_ohlcv(market_data_date)
    otc_result = fetch_tpex_otc_ohlcv(market_data_date)
    listed_institutional = fetch_twse_institutional_trading(market_data_date)
    otc_institutional = fetch_tpex_institutional_trading(market_data_date)
    listed_margin_short = fetch_twse_margin_short(market_data_date)
    otc_margin_short = fetch_tpex_margin_short(market_data_date)
    taiex_index = fetch_twse_taiex_index(market_data_date)
    tpex_index = fetch_tpex_index(market_data_date)
    mops_events = fetch_mops_events(market_data_date)
    _apply_ohlcv_source_result(sources["twse"], listed_result, "上市 OHLCV", market_data_date)
    _apply_ohlcv_source_result(sources["tpex"], otc_result, "上櫃 OHLCV", market_data_date)
    _apply_mops_source_result(sources["mops"], mops_events, market_data_date, market_data_is_trading_day)
    write_ohlcv_outputs(root, market_data_date, listed_result.rows, otc_result.rows)
    write_index_outputs(root, market_data_date, taiex_index.rows, tpex_index.rows)
    write_institutional_outputs(root, market_data_date, listed_institutional.rows, otc_institutional.rows)
    write_margin_short_outputs(root, market_data_date, listed_margin_short.rows, otc_margin_short.rows)
    mops_is_current = mops_events.ok and _is_data_current(mops_events.data_date, market_data_date, market_data_is_trading_day)
    mops_summary = mops_events_payload(
        f"{market_data_date:%Y-%m-%d}",
        generated_at,
        mops_events.data_date,
        mops_is_current,
        mops_events.rows,
        mops_events.errors,
        mops_events.limitations,
        mops_events.status,
        mops_events.source_url,
        mops_events.requested_date,
        mops_events.source_endpoint,
        mops_events.fallback_used,
        mops_events.date_validation,
        mops_events.status_reason,
    )
    mops_summary["report_date"] = f"{report_date:%Y-%m-%d}"
    mops_summary["as_of_date"] = f"{market_data_date:%Y-%m-%d}"
    mops_summary["market_data_date"] = f"{market_data_date:%Y-%m-%d}"
    write_mops_event_outputs(root, market_data_date, mops_summary, mops_events.rows)

    history_rows = load_history_rows(root)
    index_history_rows = load_index_history_rows(root)
    benchmark_history = benchmark_history_from_index_rows(index_history_rows)
    institutional_history_rows = load_institutional_history_rows(root)
    margin_short_history_rows = load_margin_short_history_rows(root)
    mops_event_history_payloads = load_mops_event_history_payloads(root)
    history_index = rebuild_history_index_from_files(root, generated_at, 60)
    write_json(root / "data" / "history-index.json", history_index)
    has_20d_history = bool(history_index.get("has_20d_history"))
    has_60d_history = bool(history_index.get("has_60d_history"))
    institutional_rows = listed_institutional.rows + otc_institutional.rows
    institutional_is_current = any(
        _is_data_current(result.data_date, market_data_date, market_data_is_trading_day) and bool(result.rows)
        for result in (listed_institutional, otc_institutional)
    )
    margin_short_rows = listed_margin_short.rows + otc_margin_short.rows
    margin_short_is_current = any(
        _is_data_current(result.data_date, market_data_date, market_data_is_trading_day) and bool(result.rows)
        for result in (listed_margin_short, otc_margin_short)
    )
    coverage, full_market_scan_ready, missing_sections = build_coverage(
        sources,
        listed_result.rows,
        otc_result.rows,
        has_20d_history=has_20d_history,
        has_60d_history=has_60d_history,
        institutional_rows=institutional_rows,
        institutional_is_current=institutional_is_current,
        institutional_status=_merge_statuses([getattr(listed_institutional, "status", "source_unavailable"), getattr(otc_institutional, "status", "source_unavailable")]),
        margin_short_rows=margin_short_rows,
        margin_short_is_current=margin_short_is_current,
        margin_short_status=_merge_statuses([getattr(listed_margin_short, "status", "source_unavailable"), getattr(otc_margin_short, "status", "source_unavailable")]),
        mops_event_rows=mops_events.rows,
        mops_events_is_current=mops_is_current,
        mops_events_date_explicit=mops_events.data_date is not None,
        mops_events_status=mops_events.status,
    )
    institutional_summary = _build_institutional_summary(
        report_date,
        market_data_date,
        generated_at,
        market_data_is_trading_day,
        listed_institutional,
        otc_institutional,
    )
    margin_short_summary = _build_margin_short_summary(
        report_date,
        market_data_date,
        generated_at,
        market_data_is_trading_day,
        listed_margin_short,
        otc_margin_short,
    )
    index_summary = build_index_summary(
        market_data_date,
        generated_at,
        index_history_rows,
        benchmark_history,
        taiex_index.errors + tpex_index.errors,
    )
    errors = (
        listed_result.errors
        + otc_result.errors
        + listed_institutional.errors
        + otc_institutional.errors
        + listed_margin_short.errors
        + otc_margin_short.errors
        + mops_events.errors
    )
    if not market_is_trading_day:
        errors.append("週末非交易日；未使用官方交易日曆判定國定假日或特殊休市日")
    if missing_sections:
        errors.append("核心資料段落缺失：" + ", ".join(missing_sections))
    overall_confidence = "high" if full_market_scan_ready else ("medium" if (listed_result.rows or otc_result.rows) else "low")
    latest_market_data_date = max([value for value in [listed_result.data_date, otc_result.data_date] if value], default=None)
    data_freshness = _build_data_freshness(report_date, market_data_date, latest_market_data_date, market_data_is_trading_day)
    artifact_urls = {
        "latest_json": github_raw_url("latest.json"),
        "screening_summary": github_raw_url("data/latest-screening-summary.json"),
        "institutional_summary": github_raw_url("data/latest-institutional-trading-summary.json"),
        "margin_short_summary": github_raw_url("data/latest-margin-short-summary.json"),
        "mops_events": github_raw_url("data/latest-mops-events.json"),
        "index_summary": github_raw_url("data/latest-index-summary.json"),
        "history_index": github_raw_url("data/history-index.json"),
        "market_scan": github_raw_url("reports/latest-market-scan.md"),
        "chatgpt_daily_qullamaggie_source": github_raw_url("data/chatgpt/daily-qullamaggie-source.json"),
        "chatgpt_daily_qullamaggie_compact": github_raw_url("data/chatgpt/daily-qullamaggie-source-compact.json"),
        "chatgpt_weekly_qullamaggie_source": github_raw_url("data/chatgpt/weekly-qullamaggie-source.json"),
        "chatgpt_weekly_qullamaggie_compact": github_raw_url("data/chatgpt/weekly-qullamaggie-source-compact.json"),
        "chatgpt_symbol_index": github_raw_url("data/chatgpt/symbol-index.json"),
        "chatgpt_schedule_readiness": github_raw_url("data/chatgpt/schedule-readiness.json"),
        "grading_policy_v1": github_raw_url("data/chatgpt/qullamaggie-grading-policy-v1.json"),
        "grading_policy_v2_shadow": github_raw_url("data/chatgpt/qullamaggie-grading-policy-v2.json"),
        "grading_v2_shadow_latest": github_raw_url("data/chatgpt/grading-shadow-v2-latest.json"),
        "grading_v2_shadow_history_index": github_raw_url("data/grading-shadow-v2/history-index.json"),
        "screening_history_index": github_raw_url("data/screening/history-index.json"),
        "chatgpt_daily_qullamaggie_markdown": github_raw_url("reports/chatgpt-daily-qullamaggie-source.md"),
        "chatgpt_weekly_qullamaggie_markdown": github_raw_url("reports/chatgpt-weekly-qullamaggie-source.md"),
    }

    summary = build_screening_summary(
        f"{market_data_date:%Y-%m-%d}",
        generated_at,
        listed_result.rows,
        otc_result.rows,
        history_rows,
        coverage,
        full_market_scan_ready,
        missing_sections,
        overall_confidence,
        institutional_rows=institutional_rows,
        institutional_history_rows=institutional_history_rows,
        margin_short_rows=margin_short_rows,
        margin_short_history_rows=margin_short_history_rows,
        mops_event_rows=mops_events.rows,
        mops_event_history_payloads=mops_event_history_payloads,
        mops_events_status=mops_events.status,
        history_index=history_index,
        benchmark_history=benchmark_history,
        include_symbol_candidates=True,
    )
    symbol_candidates = summary.pop("_chatgpt_symbol_candidates", [])
    used_input_dates = [
        value
        for value in [
            latest_market_data_date,
            history_index.get("end_date"),
            listed_institutional.data_date,
            otc_institutional.data_date,
            listed_margin_short.data_date,
            otc_margin_short.data_date,
            mops_events.data_date,
        ]
        if value
    ]
    attach_screening_as_of_metadata(summary, f"{market_data_date:%Y-%m-%d}", used_input_dates, "daily_health_check")
    summary["report_date"] = f"{market_data_date:%Y-%m-%d}"
    summary["generated_report_date"] = f"{report_date:%Y-%m-%d}"
    summary["market_data_date"] = f"{market_data_date:%Y-%m-%d}"
    scan_readiness = _build_scan_readiness(coverage, summary, data_freshness)

    report = {
        "schema_version": SCHEMA_VERSION,
        "report_date": f"{report_date:%Y-%m-%d}",
        "as_of_date": f"{market_data_date:%Y-%m-%d}",
        "market_data_date": f"{market_data_date:%Y-%m-%d}",
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "market_is_trading_day": market_is_trading_day,
        "market_data_is_trading_day": market_data_is_trading_day,
        "latest_market_data_date": latest_market_data_date,
        "data_freshness": data_freshness,
        "sources": {key: value.to_dict() for key, value in sources.items()},
        "coverage": coverage,
        "main_sources": _sources_by_role(sources, "主資料源"),
        "backup_sources": _sources_by_role(sources, "候補資料源"),
        "catalyst_news_sources": _sources_by_role(sources, "催化新聞源"),
        "manual_review_sources": _sources_by_role(sources, "人工複核源"),
        "not_recommended_sources": _sources_by_role(sources, "不建議自動化"),
        "artifact_urls": artifact_urls,
        "full_market_scan_ready": full_market_scan_ready,
        "scan_readiness": scan_readiness,
        "missing_sections": missing_sections,
        "overall_confidence": overall_confidence,
        "errors": errors,
    }
    symbol_payloads = build_symbol_technical_payloads(report, symbol_candidates)
    market_regime = str(
        summary.get("qullamaggie", {}).get("market_regime", {}).get(
            "status", "insufficient_data"
        )
    )
    shadow_report = apply_shadow_grades(
        root,
        symbol_payloads,
        symbol_candidates,
        summary,
        market_regime,
    )
    report["grading_policy"] = summary["grading_policy"]
    latest_md = build_health_markdown(report, report_date)
    market_scan_md = build_market_scan_markdown(summary, market_data_date)
    daily_chatgpt_source = build_daily_qullamaggie_source(
        report,
        summary,
        institutional_summary,
        margin_short_summary,
        mops_summary,
        history_index,
    )
    symbol_index = build_symbol_index(report, symbol_payloads)
    daily_chatgpt_source_compact = build_daily_qullamaggie_compact(daily_chatgpt_source)

    write_json(root / "latest.json", report)
    write_text(root / "latest.md", latest_md)
    write_json(root / "data" / "latest-screening-summary.json", summary)
    write_json(screening_history_path(root, f"{market_data_date:%Y-%m-%d}"), summary)
    write_json(root / "data" / "latest-institutional-trading-summary.json", institutional_summary)
    write_json(root / "data" / "latest-margin-short-summary.json", margin_short_summary)
    write_json(root / "data" / "latest-index-summary.json", index_summary)
    write_json(root / "data" / "latest-mops-events.json", mops_summary)
    write_json(root / "data" / "chatgpt" / "daily-qullamaggie-source.json", daily_chatgpt_source)
    write_json(root / "data" / "chatgpt" / "daily-qullamaggie-source-compact.json", daily_chatgpt_source_compact)
    write_json(root / "data" / "chatgpt" / "grading-shadow-v2-latest.json", shadow_report)
    write_json(
        shadow_history_path(root, f"{market_data_date:%Y-%m-%d}"),
        shadow_report,
    )
    write_chatgpt_symbol_outputs(root, symbol_payloads, symbol_index)
    write_text(root / "reports" / "latest-market-scan.md", market_scan_md)
    write_text(root / "reports" / "chatgpt-daily-qullamaggie-source.md", build_daily_qullamaggie_markdown(daily_chatgpt_source))
    history_json, history_md = history_report_paths(root, report_date)
    write_json(history_json, report)
    write_text(history_md, latest_md)
    screening_history_index = build_screening_history_index(
        root,
        generated_at,
        list(history_index.get("common_ohlcv_days") or []),
    )
    write_json(screening_history_index_path(root), screening_history_index)
    shadow_history_index = build_shadow_history_index(root, generated_at)
    write_json(shadow_history_index_path(root), shadow_history_index)
    weekly_chatgpt_source = build_weekly_qullamaggie_source(report, load_recent_screening_summaries(root, 5))
    weekly_chatgpt_source_compact = build_weekly_qullamaggie_compact(weekly_chatgpt_source)
    schedule_readiness = build_schedule_readiness(
        report,
        symbol_index,
        screening_history_index,
        daily_chatgpt_source_compact,
        weekly_chatgpt_source_compact,
        shadow_history_index,
    )
    write_json(root / "data" / "chatgpt" / "weekly-qullamaggie-source.json", weekly_chatgpt_source)
    write_json(root / "data" / "chatgpt" / "weekly-qullamaggie-source-compact.json", weekly_chatgpt_source_compact)
    write_json(root / "data" / "chatgpt" / "schedule-readiness.json", schedule_readiness)
    write_text(root / "reports" / "chatgpt-weekly-qullamaggie-source.md", build_weekly_qullamaggie_markdown(weekly_chatgpt_source))
    LOGGER.info("Wrote latest report for report_date=%s market_data_date=%s", report_date, market_data_date)
    return 0


def _sources_by_role(sources: dict[str, object], role: str) -> list[str]:
    return [source.name for source in sources.values() if source.role == role and source.schedule_ready]


def _merge_statuses(statuses: list[str]) -> str:
    for status in ("success", "empty_but_valid", "not_yet_published", "blocked_or_security_page", "parser_error", "source_unavailable"):
        if status in statuses:
            return status
    return statuses[0] if statuses else "source_unavailable"


def _build_data_freshness(
    report_date: date,
    market_data_date: date,
    latest_market_data_date: str | None,
    market_data_is_trading_day: bool,
) -> dict[str, object]:
    is_current = _is_data_current(latest_market_data_date, market_data_date, market_data_is_trading_day)
    reason = "Latest trading data is current"
    if not is_current:
        reason = (
            f"Expected market data date {market_data_date:%Y-%m-%d} is not fully available yet"
            if market_data_is_trading_day
            else "Latest market data date is not available"
        )
    return {
        "report_date": f"{report_date:%Y-%m-%d}",
        "as_of_date": f"{market_data_date:%Y-%m-%d}",
        "market_data_date": f"{market_data_date:%Y-%m-%d}",
        "expected_market_data_date": f"{market_data_date:%Y-%m-%d}",
        "latest_market_data_date": latest_market_data_date,
        "is_latest_trading_data_current": is_current,
        "reason": reason,
    }


def _build_scan_readiness(
    coverage: dict[str, dict[str, object]],
    summary: dict[str, object],
    data_freshness: dict[str, object],
) -> dict[str, object]:
    historical_status = summary.get("historical_data_status", {})
    institutional_status = summary.get("institutional_data_status", {})
    margin_short_status = summary.get("margin_short_data_status", {})
    mops_event_status = summary.get("mops_event_data_status", {})
    qullamaggie = summary.get("qullamaggie", {})
    market_regime = qullamaggie.get("market_regime", {}) if isinstance(qullamaggie, dict) else {}
    candidate_groups = qullamaggie.get("candidates", {}) if isinstance(qullamaggie, dict) else {}
    has_actionable_qullamaggie_candidate = any(
        candidate_groups.get(setup_type)
        for setup_type in ("breakout", "episodic_pivot", "anticipation")
    )

    can_run_technical_scan = (
        bool(coverage.get("listed_ohlcv", {}).get("available"))
        and bool(coverage.get("otc_ohlcv", {}).get("available"))
        and bool(historical_status.get("has_20d_history"))
    )
    can_run_qullamaggie_scan = (
        can_run_technical_scan
        and bool(historical_status.get("has_60d_history"))
        and market_regime.get("status") != "insufficient_data"
    )
    can_generate_new_paper_trade_candidate = (
        can_run_qullamaggie_scan
        and has_actionable_qullamaggie_candidate
        and bool(data_freshness.get("is_latest_trading_data_current"))
    )
    can_use_institutional_confirmation = (
        bool(coverage.get("institutional_trading", {}).get("available"))
        and bool(institutional_status.get("latest_available"))
    )
    can_use_margin_short_risk = (
        bool(coverage.get("margin_short", {}).get("available"))
        and bool(margin_short_status.get("latest_available"))
    )
    can_use_mops_catalyst = (
        bool(coverage.get("material_information", {}).get("available"))
        and bool(mops_event_status.get("latest_available"))
    )

    reasons: list[str] = []
    if not bool(coverage.get("listed_ohlcv", {}).get("available")):
        reasons.append("listed_ohlcv unavailable")
    if not bool(coverage.get("otc_ohlcv", {}).get("available")):
        reasons.append("otc_ohlcv unavailable")
    if not bool(historical_status.get("has_20d_history")):
        reasons.append("requires at least 20 common OHLCV trading days")
    if not bool(historical_status.get("has_60d_history")):
        reasons.append("requires at least 60 common OHLCV trading days for Qullamaggie-style scan")
    if not bool(coverage.get("market_environment", {}).get("available")):
        reasons.append("market_environment unavailable")
    if market_regime.get("status") == "insufficient_data":
        reasons.append("Qullamaggie market_regime is insufficient_data")
    if not has_actionable_qullamaggie_candidate:
        reasons.append("no breakout, episodic_pivot, or anticipation candidate")
    if not bool(data_freshness.get("is_latest_trading_data_current")):
        reasons.append(str(data_freshness.get("reason") or "latest trading data is not current"))

    return {
        "can_run_technical_scan": can_run_technical_scan,
        "can_run_qullamaggie_scan": can_run_qullamaggie_scan,
        "can_generate_new_paper_trade_candidate": can_generate_new_paper_trade_candidate,
        "can_use_institutional_confirmation": can_use_institutional_confirmation,
        "can_use_margin_short_risk": can_use_margin_short_risk,
        "can_use_mops_catalyst": can_use_mops_catalyst,
        "reasons": reasons,
    }


def _apply_ohlcv_source_result(source: object, fetch_result: object, label: str, report_date: date) -> None:
    if fetch_result.rows:
        source.data_date = fetch_result.data_date
        source.date_explicit = fetch_result.data_date is not None
        source.is_current = fetch_result.data_date == f"{report_date:%Y-%m-%d}" if fetch_result.data_date else False
        source.schedule_ready = source.is_current and source.machine_readable
        source.evidence = f"{label} parsed {len(fetch_result.rows)} rows from official endpoint"
        source.error = ""
        return
    source.data_date = None
    source.date_explicit = False
    source.is_current = False
    source.schedule_ready = False
    source.evidence = f"{label} official endpoint reachable status={source.http_status}, but no parsable OHLCV rows were obtained"
    source.error = "; ".join(fetch_result.errors) if fetch_result.errors else f"{label} unavailable"


def _apply_mops_source_result(source: object, fetch_result: object, report_date: date, market_is_trading_day: bool) -> None:
    source.data_date = fetch_result.data_date
    source.date_explicit = fetch_result.data_date is not None
    source.is_current = fetch_result.ok and _is_data_current(fetch_result.data_date, report_date, market_is_trading_day)
    source.schedule_ready = source.is_current and source.machine_readable
    if source.is_current:
        source.evidence = f"MOPS 重大訊息查詢成功，資料日期 {fetch_result.data_date}，事件 {len(fetch_result.rows)} 則"
        source.error = ""
        return
    source.evidence = "MOPS 重大訊息查詢未取得可驗證日期或可解析內容"
    source.error = "; ".join(fetch_result.errors) if fetch_result.errors else "MOPS material information unavailable"


def _build_institutional_summary(
    report_date: date,
    market_data_date: date,
    generated_at: str,
    market_data_is_trading_day: bool,
    listed_result: object,
    otc_result: object,
) -> dict[str, object]:
    rows = listed_result.rows + otc_result.rows
    data_dates = [result.data_date for result in (listed_result, otc_result) if result.data_date]
    limitations: list[str] = []
    if not rows:
        limitations.append("官方法人買賣超未取得可解析逐股資料")
    if any(_has_partial_institutional_values(row) for row in rows):
        limitations.append("部分法人欄位缺失，institutional_net_buy 可能為 partial")
    return {
        "schema_version": SCHEMA_VERSION,
        "report_date": f"{report_date:%Y-%m-%d}",
        "as_of_date": f"{market_data_date:%Y-%m-%d}",
        "market_data_date": f"{market_data_date:%Y-%m-%d}",
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "listed_rows": len(listed_result.rows),
        "otc_rows": len(otc_result.rows),
        "data_date": max(data_dates) if data_dates else None,
        "is_current": any(_is_data_current(result.data_date, market_data_date, market_data_is_trading_day) and bool(result.rows) for result in (listed_result, otc_result)),
        "status": _merge_statuses([getattr(listed_result, "status", "source_unavailable"), getattr(otc_result, "status", "source_unavailable")]),
        "sources": {
            "twse": _institutional_source_summary(listed_result, market_data_date, market_data_is_trading_day),
            "tpex": _institutional_source_summary(otc_result, market_data_date, market_data_is_trading_day),
        },
        "errors": listed_result.errors + otc_result.errors,
        "limitations": limitations,
    }


def _build_margin_short_summary(
    report_date: date,
    market_data_date: date,
    generated_at: str,
    market_data_is_trading_day: bool,
    listed_result: object,
    otc_result: object,
) -> dict[str, object]:
    rows = listed_result.rows + otc_result.rows
    data_dates = [result.data_date for result in (listed_result, otc_result) if result.data_date]
    limitations: list[str] = []
    if not rows:
        limitations.append("官方融資融券未取得可解析逐股資料")
    if any(_has_partial_margin_short_values(row) for row in rows):
        limitations.append("部分資券欄位缺失，margin_change 或 short_change 可能為 partial")
    return {
        "schema_version": SCHEMA_VERSION,
        "report_date": f"{report_date:%Y-%m-%d}",
        "as_of_date": f"{market_data_date:%Y-%m-%d}",
        "market_data_date": f"{market_data_date:%Y-%m-%d}",
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "listed_rows": len(listed_result.rows),
        "otc_rows": len(otc_result.rows),
        "data_date": max(data_dates) if data_dates else None,
        "is_current": any(_is_data_current(result.data_date, market_data_date, market_data_is_trading_day) and bool(result.rows) for result in (listed_result, otc_result)),
        "status": _merge_statuses([getattr(listed_result, "status", "source_unavailable"), getattr(otc_result, "status", "source_unavailable")]),
        "sources": {
            "twse": _source_summary(listed_result, market_data_date, market_data_is_trading_day),
            "tpex": _source_summary(otc_result, market_data_date, market_data_is_trading_day),
        },
        "errors": listed_result.errors + otc_result.errors,
        "limitations": limitations,
    }


def _institutional_source_summary(result: object, report_date: date, market_is_trading_day: bool) -> dict[str, object]:
    return _source_summary(result, report_date, market_is_trading_day)


def _source_summary(result: object, report_date: date, market_is_trading_day: bool) -> dict[str, object]:
    return {
        "rows": len(result.rows),
        "data_date": result.data_date,
        "is_current": _is_data_current(result.data_date, report_date, market_is_trading_day) and bool(result.rows),
        "status": getattr(result, "status", "source_unavailable"),
        "errors": result.errors,
    }


def _is_data_current(data_date: str | None, report_date: date, market_is_trading_day: bool) -> bool:
    if not data_date:
        return False
    parsed = date.fromisoformat(data_date)
    return parsed == report_date if market_is_trading_day else parsed <= report_date


def _has_partial_institutional_values(row: object) -> bool:
    values = [
        row.foreign_net_buy,
        row.investment_trust_net_buy,
        row.dealer_net_buy,
        row.institutional_net_buy,
    ]
    return any(value is None for value in values) and any(value is not None for value in values)


def _has_partial_margin_short_values(row: object) -> bool:
    values = [
        row.margin_balance,
        row.margin_change,
        row.short_balance,
        row.short_change,
    ]
    return any(value is None for value in values) and any(value is not None for value in values)


if __name__ == "__main__":
    raise SystemExit(main())
