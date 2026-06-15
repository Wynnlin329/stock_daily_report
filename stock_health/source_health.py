from __future__ import annotations

import re
from datetime import date, datetime

from .config import SourceConfig, source_configs
from .http_client import HttpClient
from .models import SourceHealth
from .trading_calendar import is_trading_day


def check_all_sources(generated_at: datetime, report_date: date, client: HttpClient | None = None) -> dict[str, SourceHealth]:
    client = client or HttpClient()
    results: dict[str, SourceHealth] = {}
    for config in source_configs(report_date):
        results[config.key] = check_source(config, generated_at, report_date, client)
    return results


def check_source(config: SourceConfig, generated_at: datetime, report_date: date, client: HttpClient) -> SourceHealth:
    response = client.get(config.url)
    reachable = bool(response.status and 200 <= response.status < 400)
    data_date = _extract_explicit_date(response.text) if reachable and config.schedule_ready else None
    date_explicit = data_date is not None
    current = _is_current(data_date, report_date) if date_explicit else False
    error = response.error
    if reachable and not date_explicit:
        error = "未取得明確資料日期；不可判定為當日資料可用"
    evidence = _evidence(config, response.status, data_date, reachable)
    return SourceHealth(
        name=config.name,
        checked_at=generated_at.isoformat(timespec="seconds"),
        reachable=reachable,
        http_status=response.status,
        data_date=data_date,
        is_current=current,
        date_explicit=date_explicit,
        machine_readable=config.machine_readable,
        login_required=config.login_required,
        dynamic_loading_suspected=config.dynamic_loading_suspected,
        schedule_ready=config.schedule_ready and current and config.machine_readable,
        role=config.role,
        evidence=evidence,
        error=error,
        response_time_ms=response.elapsed_ms if response.elapsed_ms >= 0 else None,
    )


def _is_current(data_date: str | None, report_date: date) -> bool:
    if not data_date:
        return False
    parsed = date.fromisoformat(data_date)
    if is_trading_day(report_date):
        return parsed == report_date
    return parsed <= report_date


def _evidence(config: SourceConfig, status: int | None, data_date: str | None, reachable: bool) -> str:
    if not reachable:
        return f"GET {config.url} failed with status={status}"
    if data_date:
        return f"GET {config.url} returned explicit data date {data_date}"
    return f"GET {config.url} succeeded, but no explicit data date was parsed"


def _extract_explicit_date(text: str) -> str | None:
    patterns = [
        r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})",
        r"(20\d{2})(\d{2})(\d{2})",
        r"(\d{3})[/-](\d{1,2})[/-](\d{1,2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        year = int(match.group(1))
        if year < 1000:
            year += 1911
        month = int(match.group(2))
        day = int(match.group(3))
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None
