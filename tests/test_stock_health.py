from __future__ import annotations

import json
import re
from http.client import IncompleteRead
from datetime import date, datetime
from pathlib import Path

from stock_health.config import github_raw_url
from stock_health.coverage import build_coverage
from stock_health.data_fetcher import (
    classify_mops_event,
    fetch_tpex_institutional_trading,
    fetch_tpex_margin_short,
    fetch_tpex_otc_ohlcv,
    fetch_mops_events,
    fetch_twse_institutional_trading,
    fetch_twse_listed_ohlcv,
    fetch_twse_margin_short,
    mops_events_from_csv_text,
    mops_events_payload,
    mops_events_to_csv_text,
    parse_mops_events_html,
    records_from_csv_text,
    records_to_csv_text,
)
from stock_health.history_store import build_history_index, history_report_paths, load_history_rows, write_json, write_ohlcv_outputs
from stock_health.http_client import HttpResponse
import stock_health.http_client as http_client_module
from stock_health.models import InstitutionalTradingRecord, MarginShortRecord, MopsEventRecord, OhlcvRecord, SourceHealth
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

    def post(self, url: str, data: dict[str, str], headers: dict[str, str] | None = None) -> HttpResponse:
        self.urls.append(url)
        if self.responses:
            return self.responses.pop(0)
        return HttpResponse(url=url, status=None, body=b"", elapsed_ms=1, error="URLError: mocked failure")


def sample_record(
    symbol: str = "2330",
    name: str = "台積電",
    volume: int = 1000,
    close: float = 100.0,
    turnover: int = 100000,
) -> OhlcvRecord:
    return OhlcvRecord(
        date="2026-06-15",
        symbol=symbol,
        name=name,
        market="listed",
        open=99.0,
        high=101.0,
        low=98.0,
        close=close,
        change=1.0,
        change_pct=1.0101,
        volume=volume,
        turnover=turnover,
        transactions=10,
        source="TWSE",
    )


def sample_institutional_record(
    symbol: str = "2330",
    name: str = "台積電",
    market: str = "listed",
    net_buy: int | None = 1000,
) -> InstitutionalTradingRecord:
    return InstitutionalTradingRecord(
        date="2026-06-15",
        symbol=symbol,
        name=name,
        market=market,
        foreign_buy=2000,
        foreign_sell=1000,
        foreign_net_buy=1000,
        investment_trust_buy=500,
        investment_trust_sell=0,
        investment_trust_net_buy=500,
        dealer_buy=100,
        dealer_sell=600,
        dealer_net_buy=-500,
        institutional_net_buy=net_buy,
        source="TWSE" if market == "listed" else "TPEx",
    )


def sample_margin_short_record(
    symbol: str = "2330",
    name: str = "台積電",
    market: str = "listed",
    margin_balance: int | None = 1000,
    margin_change: int | None = 100,
    short_balance: int | None = 50,
    short_change: int | None = 10,
) -> MarginShortRecord:
    return MarginShortRecord(
        date="2026-06-15",
        symbol=symbol,
        name=name,
        market=market,
        margin_buy=200,
        margin_sell=100,
        margin_balance=margin_balance,
        margin_change=margin_change,
        short_sell=20,
        short_cover=10,
        short_balance=short_balance,
        short_change=short_change,
        offsetting=0,
        source="TWSE" if market == "listed" else "TPEx",
    )


def sample_mops_event(
    symbol: str = "2330",
    name: str = "台積電",
    title: str = "董事會決議股利",
    category: str | None = "股利",
) -> MopsEventRecord:
    return MopsEventRecord(
        date="2026-06-15",
        time="18:01",
        symbol=symbol,
        name=name,
        market=None,
        title=title,
        category=category,
        summary="重大訊息摘要",
        url="https://mops.twse.com.tw/mops/web/example",
        source="MOPS",
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


def test_github_raw_url_uses_current_default_branch() -> None:
    assert github_raw_url("latest.json") == (
        "https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/"
        "codex/stock-health-v1/latest.json"
    )
    assert github_raw_url("/data/latest-screening-summary.json") == (
        "https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/"
        "codex/stock-health-v1/data/latest-screening-summary.json"
    )


def test_latest_artifact_urls_do_not_use_template_or_main_branch() -> None:
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "latest.json").read_text(encoding="utf-8"))
    serialized = json.dumps(payload.get("artifact_urls", {}), ensure_ascii=False)
    assert "<OWNER>" not in serialized
    assert "<REPO>" not in serialized
    assert "/main/" not in serialized
    assert payload["artifact_urls"]["latest_json"] == github_raw_url("latest.json")
    assert payload["artifact_urls"]["screening_summary"] == github_raw_url("data/latest-screening-summary.json")


def test_docs_do_not_publish_main_branch_raw_urls_for_current_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    docs_text = "\n".join(
        [
            (root / "README.md").read_text(encoding="utf-8"),
            (root / "docs" / "chatgpt-task-prompt.md").read_text(encoding="utf-8"),
        ]
    )
    assert "raw.githubusercontent.com/<OWNER>/<REPO>/main" not in docs_text
    assert "raw.githubusercontent.com/Wynnlin329/stock_daily_report/main" not in docs_text
    assert github_raw_url("latest.json") in docs_text
    assert github_raw_url("data/latest-screening-summary.json") in docs_text


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


def test_screening_candidate_lists_are_capped() -> None:
    rows = [sample_record(symbol=f"{index:04d}", close=110.0) for index in range(80)]
    for row in rows:
        row.change = 10.0
        row.change_pct = 10.0
    summary = build_screening_summary(
        "2026-06-15",
        "2026-06-15T18:15:00+08:00",
        rows,
        [],
        {},
        {},
        False,
        [],
        "low",
    )
    assert len(summary["screening"]["limit_up"]) == 50


def test_common_stock_is_scan_eligible() -> None:
    row = sample_record(symbol="2330", name="台積電")
    assert row.security_type == "common_stock"
    assert row.is_common_stock is True
    assert row.scan_eligible is True
    assert row.exclude_reason == ""


def test_etf_and_bond_etf_are_excluded() -> None:
    etf = sample_record(symbol="0050", name="元大台灣50")
    bond_etf = sample_record(symbol="00720B", name="元大投資級公司債")
    assert etf.is_etf is True
    assert etf.scan_eligible is False
    assert bond_etf.security_type == "bond_etf"
    assert bond_etf.is_bond_etf is True
    assert bond_etf.scan_eligible is False


def test_leveraged_inverse_products_are_excluded() -> None:
    leveraged = sample_record(symbol="00631L", name="元大台灣50正2")
    inverse = sample_record(symbol="00632R", name="元大台灣50反1")
    assert leveraged.security_type == "leveraged_inverse"
    assert inverse.security_type == "leveraged_inverse"
    assert leveraged.scan_eligible is False
    assert inverse.scan_eligible is False


def test_warrants_are_excluded_by_symbol_or_name() -> None:
    warrant_symbol = sample_record(symbol="12345A", name="台積電一")
    warrant_name = sample_record(symbol="1234", name="台積電認購")
    assert warrant_symbol.security_type == "warrant"
    assert warrant_symbol.scan_eligible is False
    assert warrant_name.is_warrant is True
    assert warrant_name.scan_eligible is False


def test_dr_is_excluded_and_ky_is_not_excluded_by_name() -> None:
    dr = sample_record(symbol="9105", name="泰金寶-DR")
    ky = sample_record(symbol="1234", name="測試-KY")
    assert dr.security_type == "dr"
    assert dr.is_dr is True
    assert dr.scan_eligible is False
    assert ky.security_type == "common_stock"
    assert ky.scan_eligible is True


def test_old_csv_missing_universe_fields_is_readable() -> None:
    csv_text = (
        "date,symbol,name,market,open,high,low,close,change,change_pct,volume,turnover,transactions,source\n"
        "2026-06-15,2330,台積電,listed,99,101,98,100,1,1.0101,1000,100000,10,TWSE\n"
    )
    rows = records_from_csv_text(csv_text)
    assert rows[0].symbol == "2330"
    assert rows[0].scan_eligible is True
    assert rows[0].security_type == "common_stock"


def test_new_csv_outputs_universe_fields() -> None:
    csv_text = records_to_csv_text([sample_record()])
    assert "security_type" in csv_text.splitlines()[0]
    assert "scan_eligible" in csv_text.splitlines()[0]
    rows = records_from_csv_text(csv_text)
    assert rows[0].scan_eligible is True


def test_rankings_exclude_etf_and_warrant_with_universe_summary() -> None:
    common = sample_record(symbol="2330", name="台積電", turnover=100000)
    etf = sample_record(symbol="0050", name="元大台灣50", turnover=900000)
    warrant = sample_record(symbol="12345A", name="台積電一", turnover=800000)
    summary = build_screening_summary(
        "2026-06-15",
        "2026-06-15T18:15:00+08:00",
        [common, etf, warrant],
        [],
        {},
        {},
        False,
        [],
        "low",
    )
    assert [row["symbol"] for row in summary["rankings"]["top_turnover"]] == ["2330"]
    assert summary["universe_summary"]["total_rows"] == 3
    assert summary["universe_summary"]["scan_eligible_rows"] == 1
    assert summary["universe_summary"]["excluded_rows"] == 2
    assert summary["universe_summary"]["excluded_by_type"]["etf"] == 1
    assert summary["universe_summary"]["excluded_by_type"]["warrant"] == 1


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


def test_load_history_rows_requires_both_markets(tmp_path: Path) -> None:
    listed = sample_record(symbol="2330")
    otc = sample_record(symbol="8069")
    otc.market = "otc"
    write_ohlcv_outputs(tmp_path, date(2026, 6, 15), [listed], [otc])
    write_ohlcv_outputs(tmp_path, date(2026, 6, 16), [listed], [])
    rows = load_history_rows(tmp_path)
    assert sorted(rows) == ["2026-06-15"]


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


def test_twse_parser_with_tables_response() -> None:
    payload = {
        "date": "20260615",
        "stat": "OK",
        "tables": [
            {
                "title": "115年06月15日 每日收盤行情(全部(不含權證、牛熊證、可展延牛熊證))",
                "fields": ["證券代號", "證券名稱", "成交股數", "成交筆數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌(+/-)", "漲跌價差", "本益比"],
                "data": [["2330", "台積電", "1,000", "10", "100,000", "99.00", "101.00", "98.00", "100.00", "<p style ='color:red'>+</p>", "1.00", "20.00"]],
            }
        ],
    }
    result = fetch_twse_listed_ohlcv(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(payload).encode(), 1)]))
    assert result.ok is True
    assert result.data_date == "2026-06-15"
    assert result.rows[0].symbol == "2330"
    assert result.rows[0].turnover == 100000


def test_tpex_parser_with_tables_response() -> None:
    payload = {
        "date": "20260615",
        "stat": "OK",
        "tables": [
            {
                "title": "上櫃股票行情",
                "fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數", "成交金額(元)", "成交筆數"],
                "data": [["8069", "元太", "200.50", "+4.50", "200.00", "202.00", "196.50", "199.21", "6,455,900", "1,286,086,332", "5,247"]],
            }
        ],
    }
    result = fetch_tpex_otc_ohlcv(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(payload).encode(), 1)]))
    assert result.ok is True
    assert result.data_date == "2026-06-15"
    assert result.rows[0].symbol == "8069"
    assert result.rows[0].turnover == 1286086332


def test_twse_institutional_parser_with_mock_response() -> None:
    payload = {
        "stat": "OK",
        "date": "20260615",
        "fields": [
            "證券代號",
            "證券名稱",
            "外陸資買進股數(不含外資自營商)",
            "外陸資賣出股數(不含外資自營商)",
            "外陸資買賣超股數(不含外資自營商)",
            "外資自營商買進股數",
            "外資自營商賣出股數",
            "外資自營商買賣超股數",
            "投信買進股數",
            "投信賣出股數",
            "投信買賣超股數",
            "自營商買賣超股數",
            "自營商買進股數(自行買賣)",
            "自營商賣出股數(自行買賣)",
            "自營商買賣超股數(自行買賣)",
            "自營商買進股數(避險)",
            "自營商賣出股數(避險)",
            "自營商買賣超股數(避險)",
            "三大法人買賣超股數",
        ],
        "data": [["2330", "台積電", "1,000", "200", "800", "100", "50", "50", "300", "100", "200", "-100", "10", "20", "-10", "40", "130", "-90", "950"]],
    }
    result = fetch_twse_institutional_trading(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(payload).encode(), 1)]))
    assert result.ok is True
    row = result.rows[0]
    assert row.symbol == "2330"
    assert row.foreign_net_buy == 850
    assert row.investment_trust_net_buy == 200
    assert row.dealer_net_buy == -100
    assert row.institutional_net_buy == 950


def test_tpex_institutional_parser_with_mock_response() -> None:
    payload = {
        "date": "20260615",
        "tables": [
            {
                "title": "三大法人買賣明細資訊",
                "fields": ["代號", "名稱"] + ["買進股數", "賣出股數", "買賣超股數"] * 7 + ["三大法人買賣超股數合計"],
                "data": [["8069", "元太", "1", "2", "-1", "0", "0", "0", "1", "2", "-1", "30", "10", "20", "0", "0", "0", "8", "3", "5", "8", "3", "5", "24"]],
            }
        ],
    }
    result = fetch_tpex_institutional_trading(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(payload).encode(), 1)]))
    assert result.ok is True
    row = result.rows[0]
    assert row.symbol == "8069"
    assert row.foreign_net_buy == -1
    assert row.investment_trust_net_buy == 20
    assert row.dealer_net_buy == 5
    assert row.institutional_net_buy == 24


def test_single_institutional_source_failure_does_not_block_other_source() -> None:
    tpex_payload = {
        "date": "20260615",
        "tables": [
            {
                "title": "三大法人買賣明細資訊",
                "fields": ["代號", "名稱"] + ["買進股數", "賣出股數", "買賣超股數"] * 7 + ["三大法人買賣超股數合計"],
                "data": [["8069", "元太", "1", "2", "-1", "0", "0", "0", "1", "2", "-1", "30", "10", "20", "0", "0", "0", "8", "3", "5", "8", "3", "5", "24"]],
            }
        ],
    }
    listed = fetch_twse_institutional_trading(date(2026, 6, 15), FakeClient([HttpResponse("mock", None, b"", 1, "URLError: mocked")]))
    otc = fetch_tpex_institutional_trading(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(tpex_payload).encode(), 1)]))
    assert listed.rows == []
    assert listed.errors
    assert otc.ok is True
    assert otc.rows[0].symbol == "8069"


def test_twse_margin_short_parser_with_mock_response() -> None:
    payload = {
        "date": "20260615",
        "tables": [
            {},
            {
                "title": "115年06月15日 融資融券彙總 (股票)",
                "fields": ["代號", "名稱", "買進", "賣出", "現金償還", "前日餘額", "今日餘額", "次一營業日限額", "買進", "賣出", "現券償還", "前日餘額", "今日餘額", "次一營業日限額", "資券互抵", "註記"],
                "data": [["2330", "台積電", "100", "20", "0", "1,000", "1,080", "9999", "30", "5", "0", "80", "55", "9999", "3", " "]],
            },
        ],
    }
    result = fetch_twse_margin_short(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(payload).encode(), 1)]))
    assert result.ok is True
    row = result.rows[0]
    assert row.symbol == "2330"
    assert row.margin_balance == 1080
    assert row.margin_change == 80
    assert row.short_sell == 5
    assert row.short_cover == 30
    assert row.short_balance == 55
    assert row.short_change == -25


def test_tpex_margin_short_parser_with_mock_response() -> None:
    payload = {
        "date": "20260615",
        "tables": [
            {
                "title": "上櫃股票融資融券餘額",
                "fields": ["代號", "名稱", "前資餘額(張)", "資買", "資賣", "現償", "資餘額", "資屬證金", "資使用率(%)", "資限額", "前券餘額(張)", "券賣", "券買", "券償", "券餘額", "券屬證金", "券使用率(%)", "券限額", "資券相抵(張)", "備註"],
                "data": [["8069", "元太", "900", "150", "30", "0", "1,020", "0", "0", "9999", "40", "12", "5", "0", "47", "0", "0", "9999", "2", ""]],
            }
        ],
    }
    result = fetch_tpex_margin_short(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(payload).encode(), 1)]))
    assert result.ok is True
    row = result.rows[0]
    assert row.symbol == "8069"
    assert row.margin_balance == 1020
    assert row.margin_change == 120
    assert row.short_sell == 12
    assert row.short_cover == 5
    assert row.short_balance == 47
    assert row.short_change == 7


def test_margin_short_parser_missing_fields_does_not_fabricate_rows() -> None:
    payload = {"date": "20260615", "tables": [{"title": "上櫃股票融資融券餘額", "fields": ["代號", "名稱"], "data": [["8069", "元太"]]}]}
    result = fetch_tpex_margin_short(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(payload).encode(), 1)]))
    assert result.rows == []
    assert result.data_date == "2026-06-15"
    assert result.errors


def test_single_margin_short_source_failure_does_not_block_other_source() -> None:
    tpex_payload = {
        "date": "20260615",
        "tables": [
            {
                "title": "上櫃股票融資融券餘額",
                "fields": ["代號", "名稱", "前資餘額(張)", "資買", "資賣", "現償", "資餘額", "資屬證金", "資使用率(%)", "資限額", "前券餘額(張)", "券賣", "券買", "券償", "券餘額", "券屬證金", "券使用率(%)", "券限額", "資券相抵(張)", "備註"],
                "data": [["8069", "元太", "900", "150", "30", "0", "1,020", "0", "0", "9999", "40", "12", "5", "0", "47", "0", "0", "9999", "2", ""]],
            }
        ],
    }
    listed = fetch_twse_margin_short(date(2026, 6, 15), FakeClient([HttpResponse("mock", None, b"", 1, "URLError: mocked")]))
    otc = fetch_tpex_margin_short(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(tpex_payload).encode(), 1)]))
    assert listed.rows == []
    assert listed.errors
    assert otc.ok is True
    assert otc.rows[0].symbol == "8069"


def test_mops_event_parser_with_mock_html() -> None:
    html = """
    <html><body>
    <div>資料日期：民國115年06月15日</div>
    <table>
      <tr><th>公司代號</th><th>公司名稱</th><th>發言日期</th><th>發言時間</th><th>主旨</th><th>說明</th></tr>
      <tr><td>2330</td><td>台積電</td><td>115/06/15</td><td>18:01</td><td><a href="/mops/web/t05st01">董事會決議股利</a></td><td>決議現金股利</td></tr>
    </table>
    </body></html>
    """
    result = fetch_mops_events(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, html.encode("utf-8"), 1)]))
    assert result.ok is True
    assert result.data_date == "2026-06-15"
    assert result.rows[0].symbol == "2330"
    assert result.rows[0].category == "股利"
    assert result.rows[0].url and result.rows[0].url.startswith("https://mops.twse.com.tw")


def test_mops_zero_events_with_explicit_date_counts_as_success() -> None:
    html = "<html><body>資料日期：民國115年06月15日 查無資料</body></html>"
    result = fetch_mops_events(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, html.encode("utf-8"), 1)]))
    payload = mops_events_payload("2026-06-15", "2026-06-15T18:15:00+08:00", result.data_date, result.ok, result.rows, result.errors)
    assert result.ok is True
    assert result.rows == []
    assert payload["event_count"] == 0
    assert payload["is_current"] is True


def test_mops_unknown_data_date_is_not_success() -> None:
    html = "<html><body><table><tr><th>公司代號</th><th>公司名稱</th><th>主旨</th></tr></table></body></html>"
    result = fetch_mops_events(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, html.encode("utf-8"), 1)]))
    assert result.ok is False
    assert result.data_date is None
    assert result.errors


def test_mops_event_classification_keywords() -> None:
    assert classify_mops_event("公告本公司月營收") == "營收"
    assert classify_mops_event("本公司取得資產") == "取得資產"
    assert classify_mops_event("召開法說會") == "法說會"
    assert classify_mops_event("其他公告") == "其他"


def test_mops_csv_and_json_outputs_parseable() -> None:
    event = sample_mops_event()
    csv_text = mops_events_to_csv_text([event])
    assert "date,time,symbol,name,market,title,category,summary,url,source" in csv_text.splitlines()[0]
    rows = mops_events_from_csv_text(csv_text)
    assert rows[0].symbol == "2330"
    payload = mops_events_payload("2026-06-15", "2026-06-15T18:15:00+08:00", "2026-06-15", True, rows)
    assert payload["event_count"] == 1


def test_institutional_parser_missing_fields_does_not_fabricate_rows() -> None:
    payload = {"date": "20260615", "fields": ["證券代號", "證券名稱"], "data": [["2330", "台積電"]]}
    result = fetch_twse_institutional_trading(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, json.dumps(payload).encode(), 1)]))
    assert result.rows == []
    assert result.data_date == "2026-06-15"
    assert result.errors


def test_institutional_coverage_requires_current_explicit_parsable_data() -> None:
    sources = {
        "twse": SourceHealth("TWSE", "", True, 200, "2026-06-15", True, True, True, False, False, True, "主資料源", "", "", 1),
        "mops": SourceHealth("MOPS", "", True, 200, None, False, False, True, False, False, False, "主資料源", "", "no date", 1),
    }
    coverage, _, missing = build_coverage(
        sources,
        [sample_record()],
        [sample_record(symbol="8069")],
        institutional_rows=[sample_institutional_record()],
        institutional_is_current=True,
    )
    assert coverage["institutional_trading"]["available"] is True
    assert "institutional_trading" not in missing
    stale_coverage, _, stale_missing = build_coverage(
        sources,
        [sample_record()],
        [sample_record(symbol="8069")],
        institutional_rows=[sample_institutional_record()],
        institutional_is_current=False,
    )
    assert stale_coverage["institutional_trading"]["available"] is False
    assert "institutional_trading" in stale_missing


def test_material_information_coverage_requires_explicit_current_mops_query() -> None:
    sources = {
        "twse": SourceHealth("TWSE", "", True, 200, "2026-06-15", True, True, True, False, False, True, "主資料源", "", "", 1),
        "mops": SourceHealth("MOPS", "", True, 200, None, False, False, True, False, False, False, "主資料源", "", "no date", 1),
    }
    coverage, _, missing = build_coverage(
        sources,
        [sample_record()],
        [sample_record(symbol="8069")],
        mops_event_rows=[],
        mops_events_is_current=True,
        mops_events_date_explicit=True,
    )
    assert coverage["material_information"]["available"] is True
    assert "material_information" not in missing
    stale_coverage, _, stale_missing = build_coverage(
        sources,
        [sample_record()],
        [sample_record(symbol="8069")],
        mops_event_rows=[sample_mops_event()],
        mops_events_is_current=False,
        mops_events_date_explicit=False,
    )
    assert stale_coverage["material_information"]["available"] is False
    assert "material_information" in stale_missing


def test_margin_short_coverage_requires_current_explicit_parsable_data() -> None:
    sources = {
        "twse": SourceHealth("TWSE", "", True, 200, "2026-06-15", True, True, True, False, False, True, "主資料源", "", "", 1),
        "mops": SourceHealth("MOPS", "", True, 200, None, False, False, True, False, False, False, "主資料源", "", "no date", 1),
    }
    coverage, _, missing = build_coverage(
        sources,
        [sample_record()],
        [sample_record(symbol="8069")],
        margin_short_rows=[sample_margin_short_record()],
        margin_short_is_current=True,
    )
    assert coverage["margin_short"]["available"] is True
    assert "margin_short" not in missing
    stale_coverage, _, stale_missing = build_coverage(
        sources,
        [sample_record()],
        [sample_record(symbol="8069")],
        margin_short_rows=[sample_margin_short_record()],
        margin_short_is_current=False,
    )
    assert stale_coverage["margin_short"]["available"] is False
    assert "margin_short" in stale_missing


def test_institutional_buy_candidates_sorted_and_scan_eligible_only() -> None:
    eligible_small = sample_record(symbol="2330", name="台積電", turnover=100000)
    eligible_big = sample_record(symbol="2317", name="鴻海", turnover=100000)
    etf = sample_record(symbol="0050", name="元大台灣50", turnover=100000)
    summary = build_screening_summary(
        "2026-06-15",
        "2026-06-15T18:15:00+08:00",
        [eligible_small, eligible_big, etf],
        [],
        {},
        {},
        False,
        [],
        "low",
        institutional_rows=[
            sample_institutional_record(symbol="2330", net_buy=100),
            sample_institutional_record(symbol="2317", name="鴻海", net_buy=500),
            sample_institutional_record(symbol="0050", name="元大台灣50", net_buy=999),
        ],
    )
    candidates = summary["screening"]["institutional_buy_candidates"]
    assert [item["symbol"] for item in candidates] == ["2317", "2330"]
    assert candidates[0]["institutional_net_buy"] == 500
    assert "三大法人合計買超" in candidates[0]["reasons"]


def test_margin_short_attention_sorted_and_scan_eligible_only() -> None:
    eligible_small = sample_record(symbol="2330", name="台積電", turnover=100000)
    eligible_big = sample_record(symbol="2317", name="鴻海", turnover=100000)
    etf = sample_record(symbol="0050", name="元大台灣50", turnover=100000)
    summary = build_screening_summary(
        "2026-06-15",
        "2026-06-15T18:15:00+08:00",
        [eligible_small, eligible_big, etf],
        [],
        {},
        {},
        False,
        [],
        "low",
        margin_short_rows=[
            sample_margin_short_record(symbol="2330", margin_balance=100, margin_change=10, short_change=3),
            sample_margin_short_record(symbol="2317", name="鴻海", margin_balance=500, margin_change=50, short_change=30),
            sample_margin_short_record(symbol="0050", name="元大台灣50", margin_balance=999, margin_change=999, short_change=999),
        ],
    )
    candidates = summary["screening"]["margin_short_attention"]
    assert [item["symbol"] for item in candidates] == ["2317", "2330"]
    assert candidates[0]["short_change"] == 30
    assert "資券變化需人工複核" in candidates[0]["reasons"]
    assert any("不可單獨視為買賣訊號" in note for note in candidates[0]["risk_notes"])


def test_mops_event_candidates_aggregate_and_scan_eligible_only() -> None:
    eligible = sample_record(symbol="2330", name="台積電", turnover=100000)
    etf = sample_record(symbol="0050", name="元大台灣50", turnover=100000)
    summary = build_screening_summary(
        "2026-06-15",
        "2026-06-15T18:15:00+08:00",
        [eligible, etf],
        [],
        {},
        {},
        False,
        [],
        "low",
        mops_event_rows=[
            sample_mops_event(symbol="2330", title="董事會決議股利", category="股利"),
            sample_mops_event(symbol="2330", title="公告重大合約", category="重大合約"),
            sample_mops_event(symbol="0050", name="元大台灣50", title="ETF公告", category="其他"),
        ],
    )
    candidates = summary["screening"]["mops_event_candidates"]
    assert [item["symbol"] for item in candidates] == ["2330"]
    assert candidates[0]["event_count"] == 2
    assert candidates[0]["event_categories"] == ["股利", "重大合約"]
    assert "重大訊息" in candidates[0]["tags"]
    assert any("需人工閱讀公告內容" in note for note in candidates[0]["risk_notes"])


def test_mops_source_failure_does_not_stop_screening_summary() -> None:
    security_page = "<html>因為安全性考量，您所執行的頁面無法呈現。 FOR SECURITY REASONS</html>"
    result = fetch_mops_events(date(2026, 6, 15), FakeClient([HttpResponse("mock", 200, security_page.encode("utf-8"), 1)]))
    summary = build_screening_summary(
        "2026-06-15",
        "2026-06-15T18:15:00+08:00",
        [sample_record()],
        [],
        {},
        {},
        False,
        ["material_information"],
        "low",
        mops_event_rows=result.rows,
    )
    assert result.rows == []
    assert result.errors
    assert summary["rankings"]["top_turnover"][0]["symbol"] == "2330"


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
