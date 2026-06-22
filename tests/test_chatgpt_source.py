from __future__ import annotations

import json
from pathlib import Path

from stock_health.chatgpt_source import (
    build_daily_qullamaggie_markdown,
    build_daily_qullamaggie_source,
    build_weekly_qullamaggie_markdown,
    build_weekly_qullamaggie_source,
    load_recent_screening_summaries,
    screening_history_path,
)
from stock_health.config import github_raw_url
from stock_health.history_store import write_json


def sample_report(*, fresh: bool = True, actionable_ready: bool = True) -> dict:
    return {
        "schema_version": "1.0",
        "report_date": "2026-06-15",
        "generated_at": "2026-06-15T18:15:00+08:00",
        "timezone": "Asia/Taipei",
        "market_is_trading_day": True,
        "latest_market_data_date": "2026-06-15" if fresh else "2026-06-14",
        "data_freshness": {
            "report_date": "2026-06-15",
            "latest_market_data_date": "2026-06-15" if fresh else "2026-06-14",
            "is_latest_trading_data_current": fresh,
            "reason": "Latest trading data is current" if fresh else "Current trading day OHLCV not fully available yet",
        },
        "coverage": {
            "listed_ohlcv": {"available": True},
            "otc_ohlcv": {"available": True},
            "institutional_trading": {"available": False},
            "margin_short": {"available": False},
            "material_information": {"available": False},
        },
        "scan_readiness": {
            "can_run_technical_scan": True,
            "can_run_qullamaggie_scan": True,
            "can_generate_new_paper_trade_candidate": actionable_ready,
            "can_use_institutional_confirmation": False,
            "can_use_margin_short_risk": False,
            "can_use_mops_catalyst": False,
            "reasons": [] if fresh else ["Current trading day OHLCV not fully available yet"],
        },
        "artifact_urls": {
            "latest_json": github_raw_url("latest.json"),
            "screening_summary": github_raw_url("data/latest-screening-summary.json"),
            "institutional_summary": github_raw_url("data/latest-institutional-trading-summary.json"),
            "margin_short_summary": github_raw_url("data/latest-margin-short-summary.json"),
            "mops_events": github_raw_url("data/latest-mops-events.json"),
            "index_summary": github_raw_url("data/latest-index-summary.json"),
            "history_index": github_raw_url("data/history-index.json"),
            "market_scan": github_raw_url("reports/latest-market-scan.md"),
            "chatgpt_daily_qullamaggie_source": github_raw_url("data/chatgpt/daily-qullamaggie-source.json"),
            "chatgpt_weekly_qullamaggie_source": github_raw_url("data/chatgpt/weekly-qullamaggie-source.json"),
            "chatgpt_daily_qullamaggie_markdown": github_raw_url("reports/chatgpt-daily-qullamaggie-source.md"),
            "chatgpt_weekly_qullamaggie_markdown": github_raw_url("reports/chatgpt-weekly-qullamaggie-source.md"),
        },
    }


def sample_candidate(symbol: str = "2330", setup_type: str = "breakout") -> dict:
    return {
        "symbol": symbol,
        "name": f"{symbol}公司",
        "market": "listed",
        "setup_type": setup_type,
        "qullamaggie_score": 82.5,
        "setup_reasons": ["突破型態符合研究條件"],
        "risk_notes": ["需人工複核資料狀態"],
    }


def sample_screening_summary(*, include_actionable: bool = True, report_date: str = "2026-06-15") -> dict:
    breakout = [sample_candidate()] if include_actionable else []
    top_candidates = [sample_candidate()] if include_actionable else []
    return {
        "schema_version": "1.0",
        "report_date": report_date,
        "generated_at": f"{report_date}T18:15:00+08:00",
        "coverage": {
            "listed_ohlcv": {"available": True},
            "otc_ohlcv": {"available": True},
        },
        "historical_data_status": {
            "has_20d_history": True,
            "has_60d_history": True,
        },
        "institutional_data_status": {"latest_available": False},
        "margin_short_data_status": {"latest_available": False},
        "mops_event_data_status": {"latest_available": False},
        "market_summary": {"total_rows": 1},
        "universe_summary": {"total_rows": 1, "scan_eligible_rows": 1, "excluded_rows": 0, "excluded_by_type": {}},
        "screening": {
            "institutional_buy_candidates": [],
            "margin_short_attention": [],
            "mops_event_candidates": [],
        },
        "qullamaggie": {
            "market_regime": {"status": "risk_on"},
            "candidates": {
                "breakout": breakout,
                "episodic_pivot": [],
                "anticipation": [],
                "extended_watch": [],
                "failed_breakout": [],
                "insufficient_data": [],
            },
            "top_candidates": top_candidates,
            "limitations": ["僅針對 scan_eligible=true 普通股 universe。"],
        },
    }


def empty_status() -> dict:
    return {
        "data_date": None,
        "is_current": False,
        "status": "source_unavailable",
        "errors": [],
        "limitations": [],
    }


def test_daily_chatgpt_source_schema_urls_and_gate() -> None:
    payload = build_daily_qullamaggie_source(
        sample_report(),
        sample_screening_summary(),
        empty_status(),
        empty_status(),
        empty_status(),
        {"available_trading_days": 60, "has_60d_history": True, "has_mops_event_90d_history": False},
    )

    assert payload["source_urls"]["chatgpt_daily_qullamaggie_source"] == github_raw_url(
        "data/chatgpt/daily-qullamaggie-source.json"
    )
    assert payload["source_urls"]["chatgpt_weekly_qullamaggie_source"] == github_raw_url(
        "data/chatgpt/weekly-qullamaggie-source.json"
    )
    assert payload["paper_trading_decision_gate"]["can_create_new_simulated_buy_candidate"] is True
    assert payload["reporting_rules"]["do_not_crawl_external_sites"] is True
    assert payload["reporting_rules"]["do_not_generate_real_trade_advice"] is True


def test_latest_json_contains_chatgpt_artifact_urls() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    artifact_urls = payload["artifact_urls"]

    assert artifact_urls["chatgpt_daily_qullamaggie_source"] == github_raw_url(
        "data/chatgpt/daily-qullamaggie-source.json"
    )
    assert artifact_urls["chatgpt_weekly_qullamaggie_source"] == github_raw_url(
        "data/chatgpt/weekly-qullamaggie-source.json"
    )
    assert artifact_urls["chatgpt_daily_qullamaggie_markdown"] == github_raw_url(
        "reports/chatgpt-daily-qullamaggie-source.md"
    )
    assert artifact_urls["chatgpt_weekly_qullamaggie_markdown"] == github_raw_url(
        "reports/chatgpt-weekly-qullamaggie-source.md"
    )


def test_daily_chatgpt_gate_blocks_stale_or_empty_actionable_data() -> None:
    stale_payload = build_daily_qullamaggie_source(
        sample_report(fresh=False),
        sample_screening_summary(),
        empty_status(),
        empty_status(),
        empty_status(),
        {"available_trading_days": 60, "has_60d_history": True, "has_mops_event_90d_history": False},
    )
    no_candidate_payload = build_daily_qullamaggie_source(
        sample_report(actionable_ready=True),
        sample_screening_summary(include_actionable=False),
        empty_status(),
        empty_status(),
        empty_status(),
        {"available_trading_days": 60, "has_60d_history": True, "has_mops_event_90d_history": False},
    )

    assert stale_payload["paper_trading_decision_gate"]["can_create_new_simulated_buy_candidate"] is False
    assert no_candidate_payload["paper_trading_decision_gate"]["can_create_new_simulated_buy_candidate"] is False


def test_weekly_chatgpt_source_uses_recent_screening_history(tmp_path: Path) -> None:
    for day in range(11, 16):
        report_date = f"2026-06-{day}"
        payload = sample_screening_summary(report_date=report_date)
        write_json(screening_history_path(tmp_path, report_date), payload)

    screening_payloads = load_recent_screening_summaries(tmp_path, 5)
    weekly = build_weekly_qullamaggie_source(sample_report(), screening_payloads)

    assert weekly["week_data_status"]["available_trading_days"] == 5
    assert weekly["week_data_status"]["dates"] == [
        "2026-06-11",
        "2026-06-12",
        "2026-06-13",
        "2026-06-14",
        "2026-06-15",
    ]
    assert weekly["weekly_setup_summary"]["setup_counts"]["breakout"] == 5
    assert weekly["paper_trading_weekly_review_gate"]["can_generate_weekly_review"] is True


def test_weekly_chatgpt_gate_blocks_when_history_under_5_days() -> None:
    weekly = build_weekly_qullamaggie_source(sample_report(), [sample_screening_summary()])

    assert weekly["week_data_status"]["available_trading_days"] == 1
    assert weekly["paper_trading_weekly_review_gate"]["can_generate_weekly_review"] is False
    assert weekly["week_data_status"]["limitations"]


def test_chatgpt_source_outputs_do_not_contain_real_trade_advice_terms() -> None:
    daily = build_daily_qullamaggie_source(
        sample_report(),
        sample_screening_summary(),
        empty_status(),
        empty_status(),
        empty_status(),
        {"available_trading_days": 60, "has_60d_history": True, "has_mops_event_90d_history": False},
    )
    weekly = build_weekly_qullamaggie_source(sample_report(), [sample_screening_summary(report_date=f"2026-06-{day}") for day in range(11, 16)])
    serialized = "\n".join(
        [
            json.dumps(daily, ensure_ascii=False),
            build_daily_qullamaggie_markdown(daily),
            json.dumps(weekly, ensure_ascii=False),
            build_weekly_qullamaggie_markdown(weekly),
        ]
    )

    for forbidden in ["買進", "賣出", "目標價", "停損價"]:
        assert forbidden not in serialized
