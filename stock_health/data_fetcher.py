from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

from .config import (
    mops_current_day_events_url,
    mops_historical_events_url,
    tpex_index_url,
    tpex_daily_url,
    tpex_institutional_url,
    tpex_margin_short_url,
    twse_taiex_index_url,
    twse_institutional_url,
    twse_margin_short_url,
    twse_mi_index_url,
    mops_major_events_url,
    mops_realtime_events_url,
)
from .http_client import HttpClient
from .models import (
    FetchResult,
    IndexFetchResult,
    IndexRecord,
    InstitutionalFetchResult,
    InstitutionalTradingRecord,
    MarginShortFetchResult,
    MarginShortRecord,
    MopsEventFetchResult,
    MopsEventRecord,
    OhlcvRecord,
)

LOGGER = logging.getLogger(__name__)

STATUS_SUCCESS = "success"
STATUS_EMPTY_BUT_VALID = "empty_but_valid"
STATUS_NOT_YET_PUBLISHED = "not_yet_published"
STATUS_SOURCE_UNAVAILABLE = "source_unavailable"
STATUS_PARSER_ERROR = "parser_error"
STATUS_BLOCKED_OR_SECURITY_PAGE = "blocked_or_security_page"
STATUS_NON_TRADING_DAY = "non_trading_day"

CSV_FIELDS = [
    "date",
    "symbol",
    "name",
    "market",
    "open",
    "high",
    "low",
    "close",
    "change",
    "change_pct",
    "volume",
    "turnover",
    "transactions",
    "source",
    "security_type",
    "is_common_stock",
    "is_etf",
    "is_warrant",
    "is_bond_etf",
    "is_leveraged_inverse",
    "is_etn",
    "is_preferred_stock",
    "is_dr",
    "scan_eligible",
    "exclude_reason",
]

INSTITUTIONAL_CSV_FIELDS = [
    "date",
    "symbol",
    "name",
    "market",
    "foreign_buy",
    "foreign_sell",
    "foreign_net_buy",
    "investment_trust_buy",
    "investment_trust_sell",
    "investment_trust_net_buy",
    "dealer_buy",
    "dealer_sell",
    "dealer_net_buy",
    "institutional_net_buy",
    "source",
]

MARGIN_SHORT_CSV_FIELDS = [
    "date",
    "symbol",
    "name",
    "market",
    "margin_buy",
    "margin_sell",
    "margin_balance",
    "margin_change",
    "short_sell",
    "short_cover",
    "short_balance",
    "short_change",
    "offsetting",
    "source",
]

MOPS_EVENT_CSV_FIELDS = [
    "date",
    "time",
    "symbol",
    "name",
    "market",
    "title",
    "category",
    "summary",
    "url",
    "source",
]

INDEX_CSV_FIELDS = [
    "date",
    "symbol",
    "name",
    "market",
    "open",
    "high",
    "low",
    "close",
    "change",
    "change_pct",
    "source",
]

MOPS_EVENT_CATEGORIES = [
    "財報",
    "營收",
    "股利",
    "除權息",
    "董事會",
    "併購",
    "處分資產",
    "取得資產",
    "增資",
    "減資",
    "法說會",
    "重大合約",
    "訴訟",
    "注意事項",
]


def _clean_text(value: Any) -> str:
    return str(value).replace(",", "").replace("--", "").replace("X", "").strip()


def _to_float(value: Any) -> float | None:
    text = _clean_text(value)
    if text in {"", "-"}:
        return None
    text = text.replace("+", "")
    try:
        return float(text)
    except ValueError:
        return None


def _to_int(value: Any) -> int | None:
    number = _to_float(value)
    return int(number) if number is not None else None


def _sum_ints(*values: int | None) -> int | None:
    if all(value is None for value in values):
        return None
    return sum(value or 0 for value in values)


def _change(current: int | None, previous: int | None) -> int | None:
    if current is None or previous is None:
        return None
    return current - previous


def _to_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _row_value(row: list[Any], fields: list[str], candidates: list[str]) -> Any:
    normalized = [field.strip() for field in fields]
    for candidate in candidates:
        if candidate in normalized:
            idx = normalized.index(candidate)
            if idx < len(row):
                return row[idx]
    return ""


def _change_value(row: list[Any], fields: list[str]) -> float | None:
    sign = str(_row_value(row, fields, ["漲跌(+/-)", "漲跌", "漲跌符號"])).strip()
    raw = _to_float(_row_value(row, fields, ["漲跌價差", "漲跌"]))
    if raw is None:
        return None
    if "-" in sign or sign in {"-", "跌"}:
        return -abs(raw)
    return raw


def _calc_change_pct(close: float | None, change: float | None) -> float | None:
    if close is None or change is None:
        return None
    previous = close - change
    if previous == 0:
        return None
    return round(change / previous * 100, 4)


def _parse_json(text: str) -> Any:
    return json.loads(text)


def fetch_twse_listed_ohlcv(target_date: date, client: HttpClient | None = None) -> FetchResult:
    client = client or HttpClient()
    response = client.get(twse_mi_index_url(target_date))
    if response.status != 200:
        return FetchResult(errors=[response.error or f"TWSE HTTP status {response.status}"])
    try:
        payload = _parse_json(response.text)
    except json.JSONDecodeError as exc:
        return FetchResult(errors=[f"TWSE JSON parse failed: {exc}"])

    fields, rows = _extract_table(
        payload,
        required_fields=["證券代號", "開盤價", "最高價", "最低價", "收盤價"],
        title_keywords=["每日收盤行情"],
    )

    if not fields or not rows:
        no_data = _payload_has_no_data(payload)
        return FetchResult(
            data_date=_extract_payload_date(payload),
            errors=[]
            if no_data
            else [
                _table_error(
                    "TWSE",
                    payload,
                    ["證券代號", "開盤價", "最高價", "最低價", "收盤價"],
                )
            ],
            status=STATUS_NON_TRADING_DAY if no_data else STATUS_PARSER_ERROR,
        )

    data_date = _extract_payload_date(payload)
    requested_date = target_date.isoformat()
    if data_date != requested_date:
        return FetchResult(
            data_date=data_date,
            errors=[
                f"TWSE OHLCV data date {data_date or 'unknown'} did not match "
                f"requested date {requested_date}"
            ],
            status=STATUS_SOURCE_UNAVAILABLE,
        )
    records = [_normalize_twse_row(target_date, fields, row) for row in rows]
    return FetchResult(
        rows=[record for record in records if record.symbol],
        data_date=data_date,
        status=STATUS_SUCCESS,
    )


def _extract_payload_date(payload: dict[str, Any]) -> str | None:
    for key in ("date", "queryDate", "reportDate"):
        value = payload.get(key)
        if not value:
            continue
        text = str(value)
        match = re.search(r"(20\d{2})(\d{2})(\d{2})", text)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        match = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", text)
        if match:
            return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    return None


def _normalize_twse_row(target_date: date, fields: list[str], row: list[Any]) -> OhlcvRecord:
    close = _to_float(_row_value(row, fields, ["收盤價"]))
    change = _change_value(row, fields)
    return OhlcvRecord(
        date=f"{target_date:%Y-%m-%d}",
        symbol=str(_row_value(row, fields, ["證券代號"])).strip(),
        name=str(_row_value(row, fields, ["證券名稱"])).strip(),
        market="listed",
        open=_to_float(_row_value(row, fields, ["開盤價"])),
        high=_to_float(_row_value(row, fields, ["最高價"])),
        low=_to_float(_row_value(row, fields, ["最低價"])),
        close=close,
        change=change,
        change_pct=_calc_change_pct(close, change),
        volume=_to_int(_row_value(row, fields, ["成交股數", "成交股數(股)"])),
        turnover=_to_int(_row_value(row, fields, ["成交金額"])),
        transactions=_to_int(_row_value(row, fields, ["成交筆數"])),
        source="TWSE",
    )


def fetch_tpex_otc_ohlcv(target_date: date, client: HttpClient | None = None) -> FetchResult:
    client = client or HttpClient()
    response = client.get(tpex_daily_url(target_date))
    if response.status != 200:
        return FetchResult(errors=[response.error or f"TPEx HTTP status {response.status}"])
    try:
        payload = _parse_json(response.text)
    except json.JSONDecodeError as exc:
        return FetchResult(errors=[f"TPEx JSON parse failed: {exc}"])

    fields, rows = _extract_table(
        payload,
        required_fields=["代號", "開盤", "最高", "最低", "收盤"],
        title_keywords=["上櫃股票行情"],
        legacy_field_keys=["aaDataHeader", "fields"],
        legacy_data_keys=["aaData", "data"],
    )
    if not fields or not rows:
        no_data = _payload_has_no_data(payload)
        return FetchResult(
            data_date=_extract_payload_date(payload),
            errors=[]
            if no_data
            else [
                _table_error(
                    "TPEx",
                    payload,
                    ["代號", "開盤", "最高", "最低", "收盤"],
                )
            ],
            status=STATUS_NON_TRADING_DAY if no_data else STATUS_PARSER_ERROR,
        )

    data_date = _extract_payload_date(payload)
    requested_date = target_date.isoformat()
    if data_date != requested_date:
        return FetchResult(
            data_date=data_date,
            errors=[
                f"TPEx OHLCV data date {data_date or 'unknown'} did not match "
                f"requested date {requested_date}"
            ],
            status=STATUS_SOURCE_UNAVAILABLE,
        )
    records = [_normalize_tpex_row(target_date, fields, row) for row in rows]
    return FetchResult(
        rows=[record for record in records if record.symbol],
        data_date=data_date,
        status=STATUS_SUCCESS,
    )


def _normalize_tpex_row(target_date: date, fields: list[str], row: list[Any]) -> OhlcvRecord:
    close = _to_float(_row_value(row, fields, ["收盤", "收盤價"]))
    change = _to_float(_row_value(row, fields, ["漲跌", "漲跌價差"]))
    return OhlcvRecord(
        date=f"{target_date:%Y-%m-%d}",
        symbol=str(_row_value(row, fields, ["代號", "證券代號"])).strip(),
        name=str(_row_value(row, fields, ["名稱", "證券名稱"])).strip(),
        market="otc",
        open=_to_float(_row_value(row, fields, ["開盤", "開盤價"])),
        high=_to_float(_row_value(row, fields, ["最高", "最高價"])),
        low=_to_float(_row_value(row, fields, ["最低", "最低價"])),
        close=close,
        change=change,
        change_pct=_calc_change_pct(close, change),
        volume=_to_int(_row_value(row, fields, ["成交股數", "成交股數(仟股)", "成交量"])),
        turnover=_to_int(_row_value(row, fields, ["成交金額", "成交金額(元)"])),
        transactions=_to_int(_row_value(row, fields, ["成交筆數"])),
        source="TPEx",
    )


def fetch_twse_taiex_index(target_date: date, client: HttpClient | None = None) -> IndexFetchResult:
    client = client or HttpClient()
    response = client.get(twse_taiex_index_url(target_date))
    if response.status != 200:
        return IndexFetchResult(errors=[response.error or f"TWSE TAIEX HTTP status {response.status}"], status=STATUS_SOURCE_UNAVAILABLE)
    try:
        payload = _parse_json(response.text)
    except json.JSONDecodeError as exc:
        return IndexFetchResult(errors=[f"TWSE TAIEX JSON parse failed: {exc}"], status=STATUS_PARSER_ERROR)

    fields, rows = _extract_table(
        payload,
        required_fields=["指數", "收盤指數", "漲跌點數"],
        title_keywords=["價格指數"],
    )
    data_date = _extract_payload_date(payload) or f"{target_date:%Y-%m-%d}"
    if not fields or not rows:
        status = _empty_payload_status(payload) if _payload_has_no_data(payload) or payload.get("stat") else STATUS_PARSER_ERROR
        return IndexFetchResult(
            data_date=data_date,
            errors=[_table_error("TWSE TAIEX", payload, ["指數", "收盤指數", "漲跌點數"])],
            status=status,
        )

    for row in rows:
        name = str(_row_value(row, fields, ["指數"])).strip()
        if name == "發行量加權股價指數":
            record = _normalize_twse_index_row(target_date, fields, row)
            return IndexFetchResult(rows=[record], data_date=data_date, status=STATUS_SUCCESS)
    return IndexFetchResult(
        data_date=data_date,
        errors=["TWSE TAIEX table did not contain 發行量加權股價指數"],
        status=STATUS_PARSER_ERROR,
    )


def fetch_tpex_index(target_date: date, client: HttpClient | None = None) -> IndexFetchResult:
    client = client or HttpClient()
    response = client.get(tpex_index_url(target_date))
    if response.status != 200:
        return IndexFetchResult(errors=[response.error or f"TPEx index HTTP status {response.status}"], status=STATUS_SOURCE_UNAVAILABLE)
    try:
        payload = _parse_json(response.text)
    except json.JSONDecodeError as exc:
        return IndexFetchResult(errors=[f"TPEx index JSON parse failed: {exc}"], status=STATUS_PARSER_ERROR)

    fields, rows = _extract_table(
        payload,
        required_fields=["日期", "開市", "最高", "最低", "收市"],
        title_keywords=["櫃買指數"],
    )
    if not fields or not rows:
        status = _empty_payload_status(payload) if _payload_has_no_data(payload) or payload.get("stat") else STATUS_PARSER_ERROR
        return IndexFetchResult(
            data_date=_extract_payload_date(payload),
            errors=[_table_error("TPEx index", payload, ["日期", "開市", "最高", "最低", "收市"])],
            status=status,
        )

    target_day = f"{target_date:%Y/%m/%d}"
    for row in rows:
        if str(_row_value(row, fields, ["日期"])).strip() == target_day:
            record = _normalize_tpex_index_row(target_date, fields, row)
            return IndexFetchResult(rows=[record], data_date=record.date, status=STATUS_SUCCESS)
    return IndexFetchResult(
        data_date=_extract_payload_date(payload),
        errors=[f"TPEx index table did not contain target date {target_day}"],
        status=STATUS_NOT_YET_PUBLISHED if payload.get("stat") == "ok" else STATUS_PARSER_ERROR,
    )


def _normalize_twse_index_row(target_date: date, fields: list[str], row: list[Any]) -> IndexRecord:
    close = _to_float(_row_value(row, fields, ["收盤指數"]))
    change = _signed_change(_row_value(row, fields, ["漲跌(+/-)"]), _row_value(row, fields, ["漲跌點數"]))
    return IndexRecord(
        date=f"{target_date:%Y-%m-%d}",
        symbol="TAIEX",
        name="發行量加權股價指數",
        market="listed",
        open=None,
        high=None,
        low=None,
        close=close,
        change=change,
        change_pct=_to_float(_row_value(row, fields, ["漲跌百分比(%)"])),
        source="TWSE",
    )


def _normalize_tpex_index_row(target_date: date, fields: list[str], row: list[Any]) -> IndexRecord:
    close = _to_float(_row_value(row, fields, ["收市"]))
    change = _to_float(_row_value(row, fields, ["漲/跌", "漲跌"]))
    return IndexRecord(
        date=f"{target_date:%Y-%m-%d}",
        symbol="TPEx",
        name="櫃買指數",
        market="otc",
        open=_to_float(_row_value(row, fields, ["開市"])),
        high=_to_float(_row_value(row, fields, ["最高"])),
        low=_to_float(_row_value(row, fields, ["最低"])),
        close=close,
        change=change,
        change_pct=_calc_change_pct(close, change),
        source="TPEx",
    )


def _signed_change(sign_value: Any, raw_value: Any) -> float | None:
    value = _to_float(raw_value)
    if value is None:
        return None
    sign_text = re.sub(r"<[^>]+>", " ", str(sign_value)).strip()
    if "-" in sign_text or "green" in str(sign_value).lower() or "跌" in sign_text:
        return -abs(value)
    return value


def fetch_twse_institutional_trading(target_date: date, client: HttpClient | None = None) -> InstitutionalFetchResult:
    client = client or HttpClient()
    response = client.get(twse_institutional_url(target_date))
    if response.status != 200:
        return InstitutionalFetchResult(errors=[response.error or f"TWSE institutional HTTP status {response.status}"], status=STATUS_SOURCE_UNAVAILABLE)
    if _looks_like_mops_security_page(response.text):
        return InstitutionalFetchResult(errors=["TWSE institutional response returned security page"], status=STATUS_BLOCKED_OR_SECURITY_PAGE)
    try:
        payload = _parse_json(response.text)
    except json.JSONDecodeError as exc:
        return InstitutionalFetchResult(errors=[f"TWSE institutional JSON parse failed: {exc}"], status=STATUS_PARSER_ERROR)

    fields = [str(item).strip() for item in payload.get("fields", [])]
    rows = payload.get("data", [])
    data_date = _extract_payload_date(payload)
    required = ["證券代號", "證券名稱", "三大法人買賣超股數"]
    if fields and _has_required_fields(fields, required) and not rows:
        return InstitutionalFetchResult(data_date=data_date, status=_empty_payload_status(payload))
    if not fields and _payload_has_no_data(payload):
        return InstitutionalFetchResult(data_date=data_date, status=_empty_payload_status(payload))
    if not fields or not _has_required_fields(fields, required):
        return InstitutionalFetchResult(
            data_date=data_date,
            errors=[_table_error("TWSE institutional", payload, required)],
            status=STATUS_PARSER_ERROR,
        )
    records = [_normalize_twse_institutional_row(target_date, fields, row) for row in rows]
    return InstitutionalFetchResult(rows=[record for record in records if record.symbol], data_date=data_date or f"{target_date:%Y-%m-%d}", status=STATUS_SUCCESS)


def fetch_tpex_institutional_trading(target_date: date, client: HttpClient | None = None) -> InstitutionalFetchResult:
    client = client or HttpClient()
    response = client.get(tpex_institutional_url(target_date))
    if response.status != 200:
        return InstitutionalFetchResult(errors=[response.error or f"TPEx institutional HTTP status {response.status}"], status=STATUS_SOURCE_UNAVAILABLE)
    if _looks_like_mops_security_page(response.text):
        return InstitutionalFetchResult(errors=["TPEx institutional response returned security page"], status=STATUS_BLOCKED_OR_SECURITY_PAGE)
    try:
        payload = _parse_json(response.text)
    except json.JSONDecodeError as exc:
        return InstitutionalFetchResult(errors=[f"TPEx institutional JSON parse failed: {exc}"], status=STATUS_PARSER_ERROR)

    fields, rows = _extract_table(
        payload,
        required_fields=["代號", "名稱", "三大法人買賣超股數合計"],
        title_keywords=["三大法人買賣明細"],
    )
    data_date = _extract_payload_date(payload)
    if fields and not rows:
        return InstitutionalFetchResult(data_date=data_date, status=_empty_payload_status(payload))
    if not fields and _payload_has_no_data(payload):
        return InstitutionalFetchResult(data_date=data_date, status=_empty_payload_status(payload))
    if not fields:
        return InstitutionalFetchResult(
            data_date=data_date,
            errors=[_table_error("TPEx institutional", payload, ["代號", "名稱", "三大法人買賣超股數合計"])],
            status=STATUS_PARSER_ERROR,
        )
    records = [_normalize_tpex_institutional_row(target_date, row) for row in rows]
    return InstitutionalFetchResult(rows=[record for record in records if record.symbol], data_date=data_date or f"{target_date:%Y-%m-%d}", status=STATUS_SUCCESS)


def fetch_twse_margin_short(target_date: date, client: HttpClient | None = None) -> MarginShortFetchResult:
    client = client or HttpClient()
    response = client.get(twse_margin_short_url(target_date))
    if response.status != 200:
        return MarginShortFetchResult(errors=[response.error or f"TWSE margin short HTTP status {response.status}"], status=STATUS_SOURCE_UNAVAILABLE)
    if _looks_like_mops_security_page(response.text):
        return MarginShortFetchResult(errors=["TWSE margin short response returned security page"], status=STATUS_BLOCKED_OR_SECURITY_PAGE)
    try:
        payload = _parse_json(response.text)
    except json.JSONDecodeError as exc:
        return MarginShortFetchResult(errors=[f"TWSE margin short JSON parse failed: {exc}"], status=STATUS_PARSER_ERROR)

    fields, rows = _extract_table(
        payload,
        required_fields=["代號", "名稱", "資券互抵"],
        title_keywords=["融資融券彙總"],
    )
    data_date = _extract_payload_date(payload)
    if fields and not rows:
        return MarginShortFetchResult(data_date=data_date, status=_empty_payload_status(payload))
    if not fields and _payload_has_no_data(payload):
        return MarginShortFetchResult(data_date=data_date, status=_empty_payload_status(payload))
    if not fields:
        return MarginShortFetchResult(
            data_date=data_date,
            errors=[_table_error("TWSE margin short", payload, ["代號", "名稱", "資券互抵"])],
            status=STATUS_PARSER_ERROR,
        )
    records = [_normalize_twse_margin_short_row(target_date, row) for row in rows]
    return MarginShortFetchResult(rows=[record for record in records if record.symbol and record.symbol.isdigit()], data_date=data_date or f"{target_date:%Y-%m-%d}", status=STATUS_SUCCESS)


def fetch_tpex_margin_short(target_date: date, client: HttpClient | None = None) -> MarginShortFetchResult:
    client = client or HttpClient()
    response = client.get(tpex_margin_short_url(target_date))
    if response.status != 200:
        return MarginShortFetchResult(errors=[response.error or f"TPEx margin short HTTP status {response.status}"], status=STATUS_SOURCE_UNAVAILABLE)
    if _looks_like_mops_security_page(response.text):
        return MarginShortFetchResult(errors=["TPEx margin short response returned security page"], status=STATUS_BLOCKED_OR_SECURITY_PAGE)
    try:
        payload = _parse_json(response.text)
    except json.JSONDecodeError as exc:
        return MarginShortFetchResult(errors=[f"TPEx margin short JSON parse failed: {exc}"], status=STATUS_PARSER_ERROR)

    fields, rows = _extract_table(
        payload,
        required_fields=["代號", "名稱", "資餘額", "券餘額"],
        title_keywords=["融資融券餘額"],
    )
    data_date = _extract_payload_date(payload)
    if fields and not rows:
        return MarginShortFetchResult(data_date=data_date, status=_empty_payload_status(payload))
    if not fields and _payload_has_no_data(payload):
        return MarginShortFetchResult(data_date=data_date, status=_empty_payload_status(payload))
    if not fields:
        return MarginShortFetchResult(
            data_date=data_date,
            errors=[_table_error("TPEx margin short", payload, ["代號", "名稱", "資餘額", "券餘額"])],
            status=STATUS_PARSER_ERROR,
        )
    records = [_normalize_tpex_margin_short_row(target_date, fields, row) for row in rows]
    return MarginShortFetchResult(rows=[record for record in records if record.symbol], data_date=data_date or f"{target_date:%Y-%m-%d}", status=STATUS_SUCCESS)


def fetch_mops_events(target_date: date, client: HttpClient | None = None) -> MopsEventFetchResult:
    client = client or HttpClient()
    realtime = fetch_mops_realtime_events(target_date, client)
    if realtime.status == STATUS_BLOCKED_OR_SECURITY_PAGE or realtime.ok:
        return realtime

    historical = fetch_mops_historical_events(target_date, client)
    historical.fallback_used = True
    historical.limitations = [
        *realtime.limitations,
        *(f"realtime fallback: {error}" for error in realtime.errors),
        *historical.limitations,
    ]
    if not historical.ok and historical.status != STATUS_BLOCKED_OR_SECURITY_PAGE:
        historical.errors = [*realtime.errors, *historical.errors]
    return historical


def fetch_mops_realtime_events(report_date: date, client: HttpClient | None = None) -> MopsEventFetchResult:
    client = client or HttpClient()
    source_url = mops_realtime_events_url()
    report_day = report_date.isoformat()
    response = client.get(source_url)
    if response.status != 200:
        return MopsEventFetchResult(
            requested_date=report_day,
            errors=[response.error or f"MOPSOV realtime material information HTTP status {response.status}"],
            status=STATUS_SOURCE_UNAVAILABLE,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available",
            status_reason="network_or_http_error",
        )

    text = response.text
    if _looks_like_mops_security_page(text):
        return MopsEventFetchResult(
            requested_date=report_day,
            errors=["MOPSOV realtime material information response returned security page; stop this source"],
            limitations=["MOPS 重大訊息來源回傳 security page，未納入事件催化判斷。"],
            status=STATUS_BLOCKED_OR_SECURITY_PAGE,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available",
            status_reason="security_page",
        )

    all_events, parser_errors = parse_mops_events_html(text)
    events = [event for event in all_events if event.date == report_day]
    data_date = _extract_mops_data_date(all_events)
    if parser_errors:
        return MopsEventFetchResult(
            requested_date=report_day,
            data_date=data_date,
            errors=parser_errors,
            status=STATUS_PARSER_ERROR,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available" if data_date is None else "mismatch",
            status_reason="unexpected_html",
        )
    if data_date is None:
        return MopsEventFetchResult(
            requested_date=report_day,
            errors=["MOPSOV realtime material information response did not expose event-row dates"],
            status=STATUS_PARSER_ERROR,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available",
            status_reason="response_date_unverified",
        )
    if data_date != report_day:
        return MopsEventFetchResult(
            requested_date=report_day,
            data_date=data_date,
            errors=[f"MOPSOV realtime material information data date {data_date} did not match target date {report_day}"],
            status=STATUS_PARSER_ERROR,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="mismatch",
            status_reason="source_date_mismatch",
        )
    return MopsEventFetchResult(
        rows=events,
        requested_date=report_day,
        data_date=data_date,
        errors=[],
        status=STATUS_SUCCESS,
        source_url=source_url,
        source_endpoint=source_url,
        date_validation="matched",
        status_reason="realtime_target_events_found",
    )


def fetch_mops_current_day_events(report_date: date, client: HttpClient | None = None) -> MopsEventFetchResult:
    client = client or HttpClient()
    source_url = mops_current_day_events_url()
    report_day = report_date.isoformat()
    response = client.get(source_url)
    if response.status != 200:
        return MopsEventFetchResult(
            requested_date=report_day,
            errors=[response.error or f"MOPSOV current-day material information HTTP status {response.status}"],
            status=STATUS_SOURCE_UNAVAILABLE,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available",
            status_reason="network_or_http_error",
        )
    text = response.text
    if _looks_like_mops_security_page(text):
        return MopsEventFetchResult(
            requested_date=report_day,
            errors=["MOPSOV current-day material information response returned security page; stop this source"],
            limitations=["MOPS 重大訊息來源回傳 security page，未納入事件催化判斷。"],
            status=STATUS_BLOCKED_OR_SECURITY_PAGE,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available",
            status_reason="security_page",
        )

    all_events, parser_errors = parse_mops_events_html(text)
    events = [event for event in all_events if event.date == report_day]
    data_date = _extract_mops_data_date(all_events)
    if parser_errors:
        return MopsEventFetchResult(
            requested_date=report_day,
            data_date=data_date,
            errors=parser_errors,
            status=STATUS_PARSER_ERROR,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available" if data_date is None else "mismatch",
            status_reason="unexpected_html",
        )
    if data_date == report_day and events:
        return MopsEventFetchResult(
            rows=events,
            requested_date=report_day,
            data_date=data_date,
            status=STATUS_SUCCESS,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="matched",
            status_reason="current_day_target_events_found",
        )
    if data_date is not None:
        return MopsEventFetchResult(
            requested_date=report_day,
            data_date=data_date,
            errors=[f"MOPSOV current-day material information data date {data_date} did not match target date {report_day}"],
            status=STATUS_PARSER_ERROR,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="mismatch",
            status_reason="source_date_mismatch",
        )
    if _looks_like_current_day_query_form(text):
        return MopsEventFetchResult(
            rows=[],
            requested_date=report_day,
            data_date=None,
            errors=[],
            limitations=["MOPSOV 當日重大訊息頁僅回傳查詢表單，未取得可驗證資料日期。"],
            status=STATUS_SOURCE_UNAVAILABLE,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available",
            status_reason="query_form_only",
        )
    return MopsEventFetchResult(
        rows=[],
        requested_date=report_day,
        data_date=None,
        errors=parser_errors or ["MOPSOV current-day material information response did not expose a verifiable data date"],
        status=STATUS_PARSER_ERROR,
        source_url=source_url,
        source_endpoint=source_url,
        date_validation="not_available",
        status_reason="response_date_unverified",
    )


def fetch_mops_historical_events(report_date: date, client: HttpClient | None = None) -> MopsEventFetchResult:
    client = client or HttpClient()
    source_url = mops_historical_events_url()
    roc_year = report_date.year - 1911
    report_day = report_date.isoformat()
    payload = {
        "step": "1",
        "firstin": "ture",
        "TYPEK": "all",
        "TYPEK2": "",
        "queryName": "co_id",
        "inpuType": "co_id",
        "co_id": "",
        "year": str(roc_year),
        "month": f"{report_date.month:02d}",
        "b_date": f"{report_date.day:02d}",
        "e_date": f"{report_date.day:02d}",
    }
    response = client.post(source_url, payload)
    if response.status != 200:
        return MopsEventFetchResult(
            requested_date=report_day,
            errors=[response.error or f"MOPSOV historical material information HTTP status {response.status}"],
            status=STATUS_SOURCE_UNAVAILABLE,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available",
            status_reason="network_or_http_error",
        )
    text = response.text
    if _looks_like_mops_security_page(text):
        return MopsEventFetchResult(
            requested_date=report_day,
            errors=["MOPSOV historical material information response returned security page; stop this source"],
            limitations=["MOPS 歷史重大訊息來源回傳 security page，未納入事件回補。"],
            status=STATUS_BLOCKED_OR_SECURITY_PAGE,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="not_available",
            status_reason="security_page",
        )

    all_events, parser_errors = parse_mops_events_html(text, source="MOPSOV:t05st01", base_url=source_url)
    events = [event for event in all_events if event.date == report_day]
    data_date = _extract_mops_data_date(all_events)
    if events:
        return MopsEventFetchResult(
            rows=events,
            requested_date=report_day,
            data_date=report_day,
            errors=parser_errors,
            status=STATUS_SUCCESS,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="matched",
            status_reason="historical_target_events_found",
        )
    if _looks_like_no_mops_events(_clean_mops_html(text)):
        return MopsEventFetchResult(
            rows=[],
            requested_date=report_day,
            data_date=report_day,
            errors=[],
            status=STATUS_EMPTY_BUT_VALID,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="query_confirmed_empty",
            status_reason="historical_query_confirmed_no_events",
        )
    if data_date is not None:
        return MopsEventFetchResult(
            requested_date=report_day,
            data_date=data_date,
            errors=[f"MOPSOV historical material information data date {data_date} did not match target date {report_day}"],
            status=STATUS_PARSER_ERROR,
            source_url=source_url,
            source_endpoint=source_url,
            date_validation="mismatch",
            status_reason="source_date_mismatch",
        )
    return MopsEventFetchResult(
        rows=[],
        requested_date=report_day,
        data_date=None,
        errors=parser_errors or ["MOPSOV historical material information response did not expose a verifiable data date"],
        status=STATUS_PARSER_ERROR,
        source_url=source_url,
        source_endpoint=source_url,
        date_validation="not_available",
        status_reason="response_date_unverified",
    )


def parse_mops_events_html(text: str, source: str = "MOPSOV:t05sr01_1", base_url: str | None = None) -> tuple[list[MopsEventRecord], list[str]]:
    cleaned_text = _clean_mops_html(text)
    parser = _MopsTableParser()
    parser.feed(cleaned_text)
    events: list[MopsEventRecord] = []
    errors: list[str] = []
    for table in parser.tables:
        if not table:
            continue
        header_index = _mops_header_index(table)
        if header_index is None:
            continue
        headers = [_normalize_header(cell["text"]) for cell in table[header_index]]
        for row in table[header_index + 1 :]:
            if len(row) < 3:
                continue
            event = _mops_event_from_row(headers, row, source, base_url or mops_realtime_events_url())
            if event:
                events.append(event)
    if not events and parser.tables and not _looks_like_no_mops_events(cleaned_text):
        errors.append("MOPS material information HTML tables did not match expected company/date/title headers")
    return events, errors


def classify_mops_event(title: str, summary: str | None = None) -> str:
    text = f"{title} {summary or ''}"
    for keyword in MOPS_EVENT_CATEGORIES:
        if keyword in text:
            return keyword
    return "其他"


class _MopsTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict[str, str]]]] = []
        self._table: list[list[dict[str, str]]] | None = None
        self._row: list[dict[str, str]] | None = None
        self._cell: dict[str, Any] | None = None
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key.lower(): value for key, value in attrs}
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = {"text_parts": [], "href": None}
        elif tag == "a" and self._cell is not None:
            self._href = attrs_dict.get("href")
            if self._href and not self._cell.get("href"):
                self._cell["href"] = self._href

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text_parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None and self._row is not None:
            text = " ".join(" ".join(self._cell["text_parts"]).split())
            self._row.append({"text": text, "href": self._cell.get("href") or ""})
            self._cell = None
            self._href = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if self._row:
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


def _looks_like_mops_security_page(text: str) -> bool:
    markers = [
        "FOR SECURITY REASONS",
        "安全性考量",
        "錯誤代碼",
        "禁止存取",
        "驗證碼",
        "captcha",
        "security",
        "access denied",
    ]
    lowered = text.lower()
    return any(marker in text or marker.lower() in lowered for marker in markers)


def _clean_mops_html(text: str) -> str:
    cleaned = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    cleaned = re.sub(r"<script\b[^>]*>.*?</script\s*>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"<style\b[^>]*>.*?</style\s*>", " ", cleaned, flags=re.DOTALL | re.IGNORECASE)


def _looks_like_no_mops_events(text: str) -> bool:
    return any(
        marker in text
        for marker in [
            "資料庫中查無需求資料",
            "查無符合條件之資料",
            "無符合條件之資料",
        ]
    )


def _looks_like_current_day_query_form(text: str) -> bool:
    return "funcName" in text and "t05st02" in text and ("查詢" in text or "公司代號" in text)


def _empty_payload_status(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    if any(marker in text for marker in ["尚未", "未公告", "暫無", "not yet"]):
        return STATUS_NOT_YET_PUBLISHED
    return STATUS_EMPTY_BUT_VALID


def _payload_has_no_data(payload: dict[str, Any]) -> bool:
    text = json.dumps(payload, ensure_ascii=False)
    if any(marker in text for marker in ["沒有符合條件", "查無資料", "無資料", "no data"]):
        return True
    tables = payload.get("tables")
    return bool(
        isinstance(tables, list)
        and tables
        and all(not table.get("data") for table in tables if isinstance(table, dict))
    )


def _mops_header_index(table: list[list[dict[str, str]]]) -> int | None:
    for index, row in enumerate(table):
        headers = [_normalize_header(cell["text"]) for cell in row]
        if (
            any("公司代號" in header or header == "代號" for header in headers)
            and any("公司名稱" in header or "公司簡稱" in header or header == "名稱" for header in headers)
            and any("主旨" in header or "標題" in header for header in headers)
        ):
            return index
    return None


def _normalize_header(value: str) -> str:
    return re.sub(r"\s+", "", value)


def _mops_cell(row: list[dict[str, str]], headers: list[str], candidates: list[str]) -> dict[str, str]:
    for candidate in candidates:
        for index, header in enumerate(headers):
            if candidate in header and index < len(row):
                return row[index]
    return {"text": "", "href": ""}


def _mops_event_from_row(headers: list[str], row: list[dict[str, str]], source: str, base_url: str) -> MopsEventRecord | None:
    symbol = _mops_cell(row, headers, ["公司代號", "證券代號", "代號"])["text"].strip()
    name = _mops_cell(row, headers, ["公司名稱", "公司簡稱", "名稱"])["text"].strip()
    market = _mops_cell(row, headers, ["市場別"])["text"].strip() or None
    title_cell = _mops_cell(row, headers, ["重大訊息主旨", "主旨", "標題"])
    title = title_cell["text"].strip()
    event_date = _normalize_mops_date(_mops_cell(row, headers, ["發言日期", "公告日期", "日期"])["text"].strip())
    event_time = _normalize_mops_time(_mops_cell(row, headers, ["發言時間", "公告時間", "時間"])["text"].strip())
    summary = _mops_cell(row, headers, ["說明", "詳細內容", "詳細資料", "內容"])["text"].strip() or None
    category = classify_mops_event(title, summary)
    if not symbol or not title:
        return None
    return MopsEventRecord(
        date=event_date or "",
        time=event_time,
        symbol=symbol,
        name=name,
        market=market,
        title=title,
        category=category,
        summary=summary,
        url=urljoin(base_url, title_cell["href"]) if title_cell["href"] else None,
        source=source,
    )


def _extract_mops_data_date(events: list[MopsEventRecord]) -> str | None:
    event_dates = sorted({event.date for event in events if event.date})
    return event_dates[-1] if event_dates else None


def _normalize_mops_date(value: str) -> str | None:
    for pattern in (
        r"(20\d{2})[年/-](\d{1,2})[月/-](\d{1,2})",
        r"\b(20\d{2})(\d{2})(\d{2})\b",
    ):
        match = re.search(pattern, value)
        if match:
            return _validated_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    roc_match = re.search(r"(?:民國)?(1\d{2})[年/-](\d{1,2})[月/-](\d{1,2})", value)
    if not roc_match:
        return None
    return _validated_date(
        int(roc_match.group(1)) + 1911,
        int(roc_match.group(2)),
        int(roc_match.group(3)),
    )


def _validated_date(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def _normalize_mops_time(value: str) -> str | None:
    match = re.search(r"(\d{1,2})[:：](\d{2})(?:[:：]\d{2})?", value)
    if match:
        return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
    compact = re.search(r"\b(\d{2})(\d{2})\b", value)
    if compact:
        return f"{int(compact.group(1)):02d}:{int(compact.group(2)):02d}"
    return None


def _normalize_twse_institutional_row(target_date: date, fields: list[str], row: list[Any]) -> InstitutionalTradingRecord:
    foreign_buy = _sum_ints(
        _to_int(_row_value(row, fields, ["外陸資買進股數(不含外資自營商)"])),
        _to_int(_row_value(row, fields, ["外資自營商買進股數"])),
    )
    foreign_sell = _sum_ints(
        _to_int(_row_value(row, fields, ["外陸資賣出股數(不含外資自營商)"])),
        _to_int(_row_value(row, fields, ["外資自營商賣出股數"])),
    )
    foreign_net_buy = _sum_ints(
        _to_int(_row_value(row, fields, ["外陸資買賣超股數(不含外資自營商)"])),
        _to_int(_row_value(row, fields, ["外資自營商買賣超股數"])),
    )
    dealer_buy = _sum_ints(
        _to_int(_row_value(row, fields, ["自營商買進股數(自行買賣)"])),
        _to_int(_row_value(row, fields, ["自營商買進股數(避險)"])),
    )
    dealer_sell = _sum_ints(
        _to_int(_row_value(row, fields, ["自營商賣出股數(自行買賣)"])),
        _to_int(_row_value(row, fields, ["自營商賣出股數(避險)"])),
    )
    return InstitutionalTradingRecord(
        date=f"{target_date:%Y-%m-%d}",
        symbol=str(_row_value(row, fields, ["證券代號"])).strip(),
        name=str(_row_value(row, fields, ["證券名稱"])).strip(),
        market="listed",
        foreign_buy=foreign_buy,
        foreign_sell=foreign_sell,
        foreign_net_buy=foreign_net_buy,
        investment_trust_buy=_to_int(_row_value(row, fields, ["投信買進股數"])),
        investment_trust_sell=_to_int(_row_value(row, fields, ["投信賣出股數"])),
        investment_trust_net_buy=_to_int(_row_value(row, fields, ["投信買賣超股數"])),
        dealer_buy=dealer_buy,
        dealer_sell=dealer_sell,
        dealer_net_buy=_to_int(_row_value(row, fields, ["自營商買賣超股數"])),
        institutional_net_buy=_to_int(_row_value(row, fields, ["三大法人買賣超股數"])),
        source="TWSE",
    )


def _normalize_twse_margin_short_row(target_date: date, row: list[Any]) -> MarginShortRecord:
    previous_margin = _to_int(row[5] if len(row) > 5 else None)
    margin_balance = _to_int(row[6] if len(row) > 6 else None)
    previous_short = _to_int(row[11] if len(row) > 11 else None)
    short_balance = _to_int(row[12] if len(row) > 12 else None)
    return MarginShortRecord(
        date=f"{target_date:%Y-%m-%d}",
        symbol=str(row[0]).strip() if len(row) > 0 else "",
        name=str(row[1]).strip() if len(row) > 1 else "",
        market="listed",
        margin_buy=_to_int(row[2] if len(row) > 2 else None),
        margin_sell=_to_int(row[3] if len(row) > 3 else None),
        margin_balance=margin_balance,
        margin_change=_change(margin_balance, previous_margin),
        short_sell=_to_int(row[9] if len(row) > 9 else None),
        short_cover=_to_int(row[8] if len(row) > 8 else None),
        short_balance=short_balance,
        short_change=_change(short_balance, previous_short),
        offsetting=_to_int(row[14] if len(row) > 14 else None),
        source="TWSE",
    )


def _normalize_tpex_margin_short_row(target_date: date, fields: list[str], row: list[Any]) -> MarginShortRecord:
    previous_margin = _to_int(_row_value(row, fields, ["前資餘額(張)"]))
    margin_balance = _to_int(_row_value(row, fields, ["資餘額"]))
    previous_short = _to_int(_row_value(row, fields, ["前券餘額(張)"]))
    short_balance = _to_int(_row_value(row, fields, ["券餘額"]))
    return MarginShortRecord(
        date=f"{target_date:%Y-%m-%d}",
        symbol=str(_row_value(row, fields, ["代號"])).strip(),
        name=str(_row_value(row, fields, ["名稱"])).strip(),
        market="otc",
        margin_buy=_to_int(_row_value(row, fields, ["資買"])),
        margin_sell=_to_int(_row_value(row, fields, ["資賣"])),
        margin_balance=margin_balance,
        margin_change=_change(margin_balance, previous_margin),
        short_sell=_to_int(_row_value(row, fields, ["券賣"])),
        short_cover=_to_int(_row_value(row, fields, ["券買"])),
        short_balance=short_balance,
        short_change=_change(short_balance, previous_short),
        offsetting=_to_int(_row_value(row, fields, ["資券相抵(張)"])),
        source="TPEx",
    )


def _normalize_tpex_institutional_row(target_date: date, row: list[Any]) -> InstitutionalTradingRecord:
    return InstitutionalTradingRecord(
        date=f"{target_date:%Y-%m-%d}",
        symbol=str(row[0]).strip() if len(row) > 0 else "",
        name=str(row[1]).strip() if len(row) > 1 else "",
        market="otc",
        foreign_buy=_to_int(row[8] if len(row) > 8 else None),
        foreign_sell=_to_int(row[9] if len(row) > 9 else None),
        foreign_net_buy=_to_int(row[10] if len(row) > 10 else None),
        investment_trust_buy=_to_int(row[11] if len(row) > 11 else None),
        investment_trust_sell=_to_int(row[12] if len(row) > 12 else None),
        investment_trust_net_buy=_to_int(row[13] if len(row) > 13 else None),
        dealer_buy=_to_int(row[20] if len(row) > 20 else None),
        dealer_sell=_to_int(row[21] if len(row) > 21 else None),
        dealer_net_buy=_to_int(row[22] if len(row) > 22 else None),
        institutional_net_buy=_to_int(row[23] if len(row) > 23 else None),
        source="TPEx",
    )


def _extract_table(
    payload: dict[str, Any],
    required_fields: list[str],
    title_keywords: list[str] | None = None,
    legacy_field_keys: list[str] | None = None,
    legacy_data_keys: list[str] | None = None,
) -> tuple[list[str] | None, list[list[Any]]]:
    title_keywords = title_keywords or []
    for table in payload.get("tables", []):
        if not isinstance(table, dict):
            continue
        fields = [str(item).strip() for item in table.get("fields", [])]
        rows = table.get("data", [])
        title = str(table.get("title") or "")
        if not fields:
            continue
        if not _has_required_fields(fields, required_fields):
            continue
        if title_keywords and not any(keyword in title for keyword in title_keywords):
            continue
        return fields, rows

    for table in payload.get("tables", []):
        if not isinstance(table, dict):
            continue
        fields = [str(item).strip() for item in table.get("fields", [])]
        rows = table.get("data", [])
        if fields and _has_required_fields(fields, required_fields):
            return fields, rows

    if legacy_field_keys or legacy_data_keys:
        fields = [str(item).strip() for key in (legacy_field_keys or []) for item in payload.get(key, [])]
        rows: list[list[Any]] = []
        for key in legacy_data_keys or []:
            candidate_rows = payload.get(key, [])
            if candidate_rows:
                rows = candidate_rows
                break
        if fields and _has_required_fields(fields, required_fields):
            return fields, rows

    for key, value in payload.items():
        if not key.startswith("fields"):
            continue
        fields = [str(item).strip() for item in value]
        data_key = "data" + key.removeprefix("fields")
        rows = payload.get(data_key, [])
        if fields and _has_required_fields(fields, required_fields):
            return fields, rows
    return None, []


def _has_required_fields(fields: list[str], required_fields: list[str]) -> bool:
    return all(field in fields for field in required_fields)


def _table_error(source: str, payload: dict[str, Any], required_fields: list[str]) -> str:
    table_summaries: list[str] = []
    for table in payload.get("tables", []):
        if not isinstance(table, dict):
            continue
        fields = table.get("fields") or []
        table_summaries.append(
            f"title={table.get('title')!r}, rows={len(table.get('data') or [])}, fields_count={len(fields)}"
        )
    stat = payload.get("stat", "")
    return (
        f"{source} response did not contain a parsable table with required fields "
        f"{required_fields}; stat={stat!r}; tables={' | '.join(table_summaries[:5])}"
    )


def records_to_csv_text(records: list[OhlcvRecord]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(record.to_csv_row())
    return output.getvalue()


def records_from_csv_text(text: str) -> list[OhlcvRecord]:
    reader = csv.DictReader(io.StringIO(text))
    records: list[OhlcvRecord] = []
    for row in reader:
        kwargs: dict[str, Any] = {
            "date": row.get("date", ""),
            "symbol": row.get("symbol", ""),
            "name": row.get("name", ""),
            "market": row.get("market", ""),
            "open": _to_float(row.get("open")),
            "high": _to_float(row.get("high")),
            "low": _to_float(row.get("low")),
            "close": _to_float(row.get("close")),
            "change": _to_float(row.get("change")),
            "change_pct": _to_float(row.get("change_pct")),
            "volume": _to_int(row.get("volume")),
            "turnover": _to_int(row.get("turnover")),
            "transactions": _to_int(row.get("transactions")),
            "source": row.get("source", ""),
        }
        if row.get("security_type"):
            kwargs.update(
                {
                    "security_type": row.get("security_type", ""),
                    "is_common_stock": _to_bool(row.get("is_common_stock")),
                    "is_etf": _to_bool(row.get("is_etf")),
                    "is_warrant": _to_bool(row.get("is_warrant")),
                    "is_bond_etf": _to_bool(row.get("is_bond_etf")),
                    "is_leveraged_inverse": _to_bool(row.get("is_leveraged_inverse")),
                    "is_etn": _to_bool(row.get("is_etn")),
                    "is_preferred_stock": _to_bool(row.get("is_preferred_stock")),
                    "is_dr": _to_bool(row.get("is_dr")),
                    "scan_eligible": _to_bool(row.get("scan_eligible")),
                    "exclude_reason": row.get("exclude_reason", ""),
                }
            )
        records.append(
            OhlcvRecord(**kwargs)
        )
    return records


def index_records_to_csv_text(records: list[IndexRecord]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=INDEX_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(record.to_csv_row())
    return output.getvalue()


def index_records_from_csv_text(text: str) -> list[IndexRecord]:
    reader = csv.DictReader(io.StringIO(text))
    records: list[IndexRecord] = []
    for row in reader:
        records.append(
            IndexRecord(
                date=row.get("date", ""),
                symbol=row.get("symbol", ""),
                name=row.get("name", ""),
                market=row.get("market", ""),
                open=_to_float(row.get("open")),
                high=_to_float(row.get("high")),
                low=_to_float(row.get("low")),
                close=_to_float(row.get("close")),
                change=_to_float(row.get("change")),
                change_pct=_to_float(row.get("change_pct")),
                source=row.get("source", ""),
            )
        )
    return records


def institutional_records_to_csv_text(records: list[InstitutionalTradingRecord]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=INSTITUTIONAL_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(record.to_csv_row())
    return output.getvalue()


def institutional_records_from_csv_text(text: str) -> list[InstitutionalTradingRecord]:
    reader = csv.DictReader(io.StringIO(text))
    records: list[InstitutionalTradingRecord] = []
    for row in reader:
        records.append(
            InstitutionalTradingRecord(
                date=row.get("date", ""),
                symbol=row.get("symbol", ""),
                name=row.get("name", ""),
                market=row.get("market", ""),
                foreign_buy=_to_int(row.get("foreign_buy")),
                foreign_sell=_to_int(row.get("foreign_sell")),
                foreign_net_buy=_to_int(row.get("foreign_net_buy")),
                investment_trust_buy=_to_int(row.get("investment_trust_buy")),
                investment_trust_sell=_to_int(row.get("investment_trust_sell")),
                investment_trust_net_buy=_to_int(row.get("investment_trust_net_buy")),
                dealer_buy=_to_int(row.get("dealer_buy")),
                dealer_sell=_to_int(row.get("dealer_sell")),
                dealer_net_buy=_to_int(row.get("dealer_net_buy")),
                institutional_net_buy=_to_int(row.get("institutional_net_buy")),
                source=row.get("source", ""),
            )
        )
    return records


def margin_short_records_to_csv_text(records: list[MarginShortRecord]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=MARGIN_SHORT_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(record.to_csv_row())
    return output.getvalue()


def margin_short_records_from_csv_text(text: str) -> list[MarginShortRecord]:
    reader = csv.DictReader(io.StringIO(text))
    records: list[MarginShortRecord] = []
    for row in reader:
        records.append(
            MarginShortRecord(
                date=row.get("date", ""),
                symbol=row.get("symbol", ""),
                name=row.get("name", ""),
                market=row.get("market", ""),
                margin_buy=_to_int(row.get("margin_buy")),
                margin_sell=_to_int(row.get("margin_sell")),
                margin_balance=_to_int(row.get("margin_balance")),
                margin_change=_to_int(row.get("margin_change")),
                short_sell=_to_int(row.get("short_sell")),
                short_cover=_to_int(row.get("short_cover")),
                short_balance=_to_int(row.get("short_balance")),
                short_change=_to_int(row.get("short_change")),
                offsetting=_to_int(row.get("offsetting")),
                source=row.get("source", ""),
            )
        )
    return records


def mops_events_to_csv_text(records: list[MopsEventRecord]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=MOPS_EVENT_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(record.to_csv_row())
    return output.getvalue()


def mops_events_from_csv_text(text: str) -> list[MopsEventRecord]:
    reader = csv.DictReader(io.StringIO(text))
    records: list[MopsEventRecord] = []
    for row in reader:
        records.append(
            MopsEventRecord(
                date=row.get("date", ""),
                time=row.get("time") or None,
                symbol=row.get("symbol", ""),
                name=row.get("name", ""),
                market=row.get("market") or None,
                title=row.get("title", ""),
                category=row.get("category") or None,
                summary=row.get("summary") or None,
                url=row.get("url") or None,
                source=row.get("source", "MOPS"),
            )
        )
    return records


def mops_events_payload(
    report_date: str,
    generated_at: str,
    data_date: str | None,
    is_current: bool,
    events: list[MopsEventRecord],
    errors: list[str] | None = None,
    limitations: list[str] | None = None,
    status: str = STATUS_SOURCE_UNAVAILABLE,
    source_url: str | None = None,
    requested_date: str | None = None,
    source_endpoint: str | None = None,
    fallback_used: bool = False,
    date_validation: str = "not_available",
    status_reason: str = "source_unavailable",
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "report_date": report_date,
        "generated_at": generated_at,
        "timezone": "Asia/Taipei",
        "requested_date": requested_date or report_date,
        "data_date": data_date,
        "is_current": is_current,
        "event_count": len(events),
        "status": status,
        "source_url": source_url,
        "source_endpoint": source_endpoint or source_url,
        "fallback_used": fallback_used,
        "date_validation": date_validation,
        "status_reason": status_reason,
        "events": [
            {
                "date": event.date,
                "time": event.time,
                "symbol": event.symbol,
                "name": event.name,
                "market": event.market,
                "title": event.title,
                "category": event.category,
                "summary": event.summary,
                "url": event.url,
                "source": event.source,
            }
            for event in events
        ],
        "errors": errors or [],
        "limitations": limitations or [],
    }
