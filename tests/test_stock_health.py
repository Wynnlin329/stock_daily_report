from __future__ import annotations

import json
import re
from http.client import IncompleteRead
from datetime import date, datetime
from pathlib import Path

from stock_health.coverage import build_coverage
from stock_health.data_fetcher import fetch_twse_listed_ohlcv, records_to_csv_text
from stock_health.history_store import build_history_index, history_report_paths, write_json
from stock_health.http_client import HttpResponse
import stock_health.http_client as http_client_module
from stock_health.models import OhlcvRecord, SourceHealth
from stock_health.report_writer import build_health_markdown
from stock_health.screening import build_screening_summary
from stock_health.source_health import check_all_sources
from stock_health.trading_calendar import TAIPEI, is_trading_day, markdown_report_date


class FakeClient:
    def __init__(self, responses: list[HttpResponse] | None = None) -> None:
        self.responses = responses or []
        self.urls: list[str] = []

    def get(self, url: str) -> HttpResponse:
        self.urls.append(url)
        if self.responses:
            return self.responses.pop(0)
        return HttpResponse(url=url, status=None, body=b"", elapsed_ms=1, error="URLError: mocked failure")


def sample_record(symbol: str = "2330", volume: int = 1000, close: float = 100.0) -> OhlcvRecord:
    return OhlcvRecord(
        date="2026-06-15",
        symbol=symbol,
        name="台積電",
        market="listed",
        open=99.0,
        high=101.0,
        low=98.0,
        close=close,
        change=1.0,
        change_pct=1.0101,
        volume=volume,
        turnover=100000,
        transactions=10,
        source="TWSE",
    )


def test_asia_taipei_date_and_chinese_weekday() -> None:
    now = datetime(2026, 6, 15, 18, 15, tzinfo=TAIPEI)
    assert now.isoformat(timespec="seconds").endswith("+08:00")
    assert markdown_report_date(date(2026, 6, 15)) == "2026/06/15（星期一）"


def test_non_trading_weekend_rule() -> None:
    assert is_trading_day(date(2026, 6, 13)) is False
    assert is_trading_day(date(2026, 6, 15)) is True


def test_latest_json_required_fields_parseable(tmp_path: Path) -> None:
    payload = {
        "schema_version": "1.0",
        "report_date": "2026-06-15",
        "generated_at": "2026-06-15T18:15:00+08:00",
        "timezone": "Asia/Taipei",
        "market_is_trading_day": True,
        "latest_market_data_date": None,
        "sources": {},
        "coverage": {},
        "main_sources": [],
        "backup_sources": [],
        "catalyst_news_sources": [],
        "manual_review_sources": [],
        "not_recommended_sources": [],
        "artifact_urls": {},
        "full_market_scan_ready": False,
        "missing_sections": [],
        "overall_confidence": "low",
        "errors": [],
    }
    path = tmp_path / "latest.json"
    write_json(path, payload)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload).issubset(loaded)


def test_source_failure_does_not_stop_whole_flow() -> None:
    responses = [
        HttpResponse(url="mock", status=200, body=b'{"date":"20260615"}', elapsed_ms=2),
        HttpResponse(url="mock", status=None, body=b"", elapsed_ms=2, error="URLError: mocked"),
    ]
    responses.extend([HttpResponse(url="mock", status=200, body=b"no explicit date", elapsed_ms=2) for _ in range(10)])
    results = check_all_sources(datetime(2026, 6, 15, 18, 15, tzinfo=TAIPEI), date(2026, 6, 15), FakeClient(responses))
    assert len(results) == 12
    assert results["twse"].is_current is True
    assert results["tpex"].reachable is False
    assert results["goodinfo"].is_current is False


def test_full_market_scan_and_missing_sections() -> None:
    sources = {
        "twse": SourceHealth("TWSE", "", True, 200, "2026-06-15", True, True, True, False, False, True, "主資料源", "", "", 1),
        "mops": SourceHealth("MOPS", "", True, 200, None, False, False, True, False, False, False, "主資料源", "", "no date", 1),
    }
    coverage, ready, missing = build_coverage(sources, [sample_record()], [], False, False)
    assert ready is False
    assert "otc_ohlcv" in missing
    assert "institutional_trading" in missing
    assert coverage["listed_ohlcv"]["available"] is True


def test_history_index_flags() -> None:
    index = build_history_index("2026-06-15T18:15:00+08:00", 60, [f"2026-05-{i:02d}" for i in range(1, 21)], [f"2026-05-{i:02d}" for i in range(1, 21)], [])
    assert index["has_20d_history"] is True
    assert index["has_60d_history"] is False


def test_screening_does_not_fake_history_signals() -> None:
    summary = build_screening_summary(
        "2026-06-15",
        "2026-06-15T18:15:00+08:00",
        [sample_record(volume=5000)],
        [],
        {},
        {},
        False,
        ["margin_short"],
        "low",
    )
    assert summary["screening"]["volume_spike"] == []
    assert summary["screening"]["breakout_candidates"] == []
    assert summary["historical_data_status"]["has_20d_history"] is False
    assert summary["historical_data_status"]["has_60d_history"] is False
    assert summary["limitations"]


def test_markdown_generation() -> None:
    report = {
        "generated_at": "2026-06-15T18:15:00+08:00",
        "market_is_trading_day": True,
        "latest_market_data_date": None,
        "full_market_scan_ready": False,
        "overall_confidence": "low",
        "sources": {
            "twse": SourceHealth("TWSE", "", False, None, None, False, False, True, False, False, False, "主資料源", "", "mock failure", None).to_dict()
        },
        "main_sources": [],
        "backup_sources": [],
        "catalyst_news_sources": [],
        "manual_review_sources": [],
        "not_recommended_sources": [],
        "coverage": {"listed_ohlcv": {"available": False, "notes": "missing"}},
        "missing_sections": ["listed_ohlcv"],
        "errors": ["mock failure"],
    }
    markdown = build_health_markdown(report, date(2026, 6, 15))
    assert markdown.startswith("# 報告日期：2026/06/15（星期一）")
    assert "mock failure" in markdown


def test_history_paths() -> None:
    json_path, md_path = history_report_paths(Path("/repo"), date(2026, 6, 15))
    assert str(json_path).endswith("history/2026/06/2026-06-15.json")
    assert str(md_path).endswith("history/2026/06/2026-06-15.md")


def test_twse_parser_with_mock_response() -> None:
    payload = {
        "date": "20260615",
        "fields9": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差"],
        "data9": [["2330", "台積電", "1,000", "10", "100,000", "99.00", "101.00", "98.00", "100.00", "+", "1.00"]],
    }
    result = fetch_twse_listed_ohlcv(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(payload).encode(), 1)]))
    assert result.ok is True
    assert result.rows[0].symbol == "2330"
    assert result.rows[0].volume == 1000


def test_http_client_handles_incomplete_read(monkeypatch) -> None:
    def fake_urlopen(*_args, **_kwargs):
        raise IncompleteRead(b"partial")

    monkeypatch.setattr(http_client_module, "urlopen", fake_urlopen)
    client = http_client_module.HttpClient(retries=0)
    response = client.get("https://example.test/")
    assert response.status is None
    assert "IncompleteRead" in response.error


def test_csv_and_json_outputs_parseable(tmp_path: Path) -> None:
    csv_text = records_to_csv_text([sample_record()])
    assert "symbol" in csv_text
    summary = {"schema_version": "1.0", "report_date": "2026-06-15"}
    path = tmp_path / "data" / "latest-screening-summary.json"
    write_json(path, summary)
    assert json.load(path.open(encoding="utf-8"))["schema_version"] == "1.0"


def test_no_hardcoded_secret_patterns() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden_patterns = [
        re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
        re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*=\s*['\"][^'\"]+['\"]"),
    ]
    for path in root.rglob("*"):
        if ".git" in path.parts or path.is_dir() or path.suffix in {".pyc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in forbidden_patterns:
            assert not pattern.search(text), f"{pattern.pattern} found in {path}"
