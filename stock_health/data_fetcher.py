from __future__ import annotations

import csv
import io
import json
import logging
import re
from datetime import date
from typing import Any

from .config import tpex_daily_url, twse_mi_index_url
from .http_client import HttpClient
from .models import FetchResult, OhlcvRecord

LOGGER = logging.getLogger(__name__)

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
        return FetchResult(
            data_date=_extract_payload_date(payload),
            errors=[_table_error("TWSE", payload, ["證券代號", "開盤價", "最高價", "最低價", "收盤價"])],
        )

    records = [_normalize_twse_row(target_date, fields, row) for row in rows]
    return FetchResult(rows=[record for record in records if record.symbol], data_date=_extract_payload_date(payload) or f"{target_date:%Y-%m-%d}")


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
        return FetchResult(
            data_date=_extract_payload_date(payload),
            errors=[_table_error("TPEx", payload, ["代號", "開盤", "最高", "最低", "收盤"])],
        )

    records = [_normalize_tpex_row(target_date, fields, row) for row in rows]
    return FetchResult(rows=[record for record in records if record.symbol], data_date=_extract_payload_date(payload) or f"{target_date:%Y-%m-%d}")


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
        if not fields or not rows:
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
        if fields and rows and _has_required_fields(fields, required_fields):
            return fields, rows

    if legacy_field_keys or legacy_data_keys:
        fields = [str(item).strip() for key in (legacy_field_keys or []) for item in payload.get(key, [])]
        rows: list[list[Any]] = []
        for key in legacy_data_keys or []:
            candidate_rows = payload.get(key, [])
            if candidate_rows:
                rows = candidate_rows
                break
        if fields and rows and _has_required_fields(fields, required_fields):
            return fields, rows

    for key, value in payload.items():
        if not key.startswith("fields"):
            continue
        fields = [str(item).strip() for item in value]
        data_key = "data" + key.removeprefix("fields")
        rows = payload.get(data_key, [])
        if fields and rows and _has_required_fields(fields, required_fields):
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
            f"title={table.get('title')!r}, rows={len(table.get('data') or [])}, fields={','.join(str(field) for field in fields[:8])}"
        )
    stat = payload.get("stat", "")
    return (
        f"{source} response did not contain a parsable OHLCV table with required fields "
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
