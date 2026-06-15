#!/usr/bin/env python
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_health.config import SCHEMA_VERSION, TIMEZONE
from stock_health.coverage import build_coverage
from stock_health.data_fetcher import fetch_tpex_otc_ohlcv, fetch_twse_listed_ohlcv
from stock_health.history_store import ensure_dirs, history_report_paths, load_history_rows, write_json, write_ohlcv_outputs, write_text
from stock_health.report_writer import build_health_markdown, build_market_scan_markdown
from stock_health.screening import build_screening_summary
from stock_health.source_health import check_all_sources
from stock_health.trading_calendar import ensure_taipei, is_trading_day

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
    generated_at = now.isoformat(timespec="seconds")
    market_is_trading_day = is_trading_day(report_date)

    LOGGER.info("Checking sources for %s", report_date)
    sources = check_all_sources(now, report_date)
    listed_result = fetch_twse_listed_ohlcv(report_date)
    otc_result = fetch_tpex_otc_ohlcv(report_date)
    _apply_ohlcv_source_result(sources["twse"], listed_result, "上市 OHLCV", report_date)
    _apply_ohlcv_source_result(sources["tpex"], otc_result, "上櫃 OHLCV", report_date)
    write_ohlcv_outputs(root, report_date, listed_result.rows, otc_result.rows)

    history_rows = load_history_rows(root)
    has_20d_history = len(history_rows) >= 20
    has_60d_history = len(history_rows) >= 60
    coverage, full_market_scan_ready, missing_sections = build_coverage(
        sources,
        listed_result.rows,
        otc_result.rows,
        has_20d_history=has_20d_history,
        has_60d_history=has_60d_history,
    )
    errors = listed_result.errors + otc_result.errors
    if not market_is_trading_day:
        errors.append("週末非交易日；未使用官方交易日曆判定國定假日或特殊休市日")
    if missing_sections:
        errors.append("核心資料段落缺失：" + ", ".join(missing_sections))
    overall_confidence = "high" if full_market_scan_ready else ("medium" if (listed_result.rows or otc_result.rows) else "low")
    latest_market_data_date = max([value for value in [listed_result.data_date, otc_result.data_date] if value], default=None)

    report = {
        "schema_version": SCHEMA_VERSION,
        "report_date": f"{report_date:%Y-%m-%d}",
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "market_is_trading_day": market_is_trading_day,
        "latest_market_data_date": latest_market_data_date,
        "sources": {key: value.to_dict() for key, value in sources.items()},
        "coverage": coverage,
        "main_sources": _sources_by_role(sources, "主資料源"),
        "backup_sources": _sources_by_role(sources, "候補資料源"),
        "catalyst_news_sources": _sources_by_role(sources, "催化新聞源"),
        "manual_review_sources": _sources_by_role(sources, "人工複核源"),
        "not_recommended_sources": _sources_by_role(sources, "不建議自動化"),
        "artifact_urls": {
            "latest_json": "https://raw.githubusercontent.com/<OWNER>/<REPO>/main/latest.json",
            "screening_summary": "https://raw.githubusercontent.com/<OWNER>/<REPO>/main/data/latest-screening-summary.json",
            "market_scan": "https://raw.githubusercontent.com/<OWNER>/<REPO>/main/reports/latest-market-scan.md",
        },
        "full_market_scan_ready": full_market_scan_ready,
        "missing_sections": missing_sections,
        "overall_confidence": overall_confidence,
        "errors": errors,
    }
    summary = build_screening_summary(
        f"{report_date:%Y-%m-%d}",
        generated_at,
        listed_result.rows,
        otc_result.rows,
        history_rows,
        coverage,
        full_market_scan_ready,
        missing_sections,
        overall_confidence,
    )
    latest_md = build_health_markdown(report, report_date)
    market_scan_md = build_market_scan_markdown(summary, report_date)

    write_json(root / "latest.json", report)
    write_text(root / "latest.md", latest_md)
    write_json(root / "data" / "latest-screening-summary.json", summary)
    write_text(root / "reports" / "latest-market-scan.md", market_scan_md)
    history_json, history_md = history_report_paths(root, report_date)
    write_json(history_json, report)
    write_text(history_md, latest_md)
    LOGGER.info("Wrote latest report for %s", report_date)
    return 0


def _sources_by_role(sources: dict[str, object], role: str) -> list[str]:
    return [source.name for source in sources.values() if source.role == role and source.schedule_ready]


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


if __name__ == "__main__":
    raise SystemExit(main())
