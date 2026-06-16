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
from stock_health.data_fetcher import (
    fetch_tpex_institutional_trading,
    fetch_tpex_otc_ohlcv,
    fetch_twse_institutional_trading,
    fetch_twse_listed_ohlcv,
)
from stock_health.history_store import ensure_dirs, history_report_paths, load_history_rows, write_institutional_outputs, write_json, write_ohlcv_outputs, write_text
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
    listed_institutional = fetch_twse_institutional_trading(report_date)
    otc_institutional = fetch_tpex_institutional_trading(report_date)
    _apply_ohlcv_source_result(sources["twse"], listed_result, "上市 OHLCV", report_date)
    _apply_ohlcv_source_result(sources["tpex"], otc_result, "上櫃 OHLCV", report_date)
    write_ohlcv_outputs(root, report_date, listed_result.rows, otc_result.rows)
    write_institutional_outputs(root, report_date, listed_institutional.rows, otc_institutional.rows)

    history_rows = load_history_rows(root)
    has_20d_history = len(history_rows) >= 20
    has_60d_history = len(history_rows) >= 60
    institutional_rows = listed_institutional.rows + otc_institutional.rows
    institutional_is_current = any(
        _is_data_current(result.data_date, report_date, market_is_trading_day) and bool(result.rows)
        for result in (listed_institutional, otc_institutional)
    )
    coverage, full_market_scan_ready, missing_sections = build_coverage(
        sources,
        listed_result.rows,
        otc_result.rows,
        has_20d_history=has_20d_history,
        has_60d_history=has_60d_history,
        institutional_rows=institutional_rows,
        institutional_is_current=institutional_is_current,
    )
    institutional_summary = _build_institutional_summary(
        report_date,
        generated_at,
        market_is_trading_day,
        listed_institutional,
        otc_institutional,
    )
    errors = listed_result.errors + otc_result.errors + listed_institutional.errors + otc_institutional.errors
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
            "institutional_summary": "https://raw.githubusercontent.com/<OWNER>/<REPO>/main/data/latest-institutional-trading-summary.json",
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
        institutional_rows=institutional_rows,
    )
    latest_md = build_health_markdown(report, report_date)
    market_scan_md = build_market_scan_markdown(summary, report_date)

    write_json(root / "latest.json", report)
    write_text(root / "latest.md", latest_md)
    write_json(root / "data" / "latest-screening-summary.json", summary)
    write_json(root / "data" / "latest-institutional-trading-summary.json", institutional_summary)
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


def _build_institutional_summary(
    report_date: date,
    generated_at: str,
    market_is_trading_day: bool,
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
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "listed_rows": len(listed_result.rows),
        "otc_rows": len(otc_result.rows),
        "data_date": max(data_dates) if data_dates else None,
        "is_current": any(_is_data_current(result.data_date, report_date, market_is_trading_day) and bool(result.rows) for result in (listed_result, otc_result)),
        "sources": {
            "twse": _institutional_source_summary(listed_result, report_date, market_is_trading_day),
            "tpex": _institutional_source_summary(otc_result, report_date, market_is_trading_day),
        },
        "errors": listed_result.errors + otc_result.errors,
        "limitations": limitations,
    }


def _institutional_source_summary(result: object, report_date: date, market_is_trading_day: bool) -> dict[str, object]:
    return {
        "rows": len(result.rows),
        "data_date": result.data_date,
        "is_current": _is_data_current(result.data_date, report_date, market_is_trading_day) and bool(result.rows),
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


if __name__ == "__main__":
    raise SystemExit(main())
