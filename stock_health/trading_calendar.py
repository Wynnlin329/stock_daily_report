from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .config import TIMEZONE

TAIPEI = ZoneInfo(TIMEZONE)
CHINESE_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def taipei_now() -> datetime:
    return datetime.now(TAIPEI)


def ensure_taipei(value: datetime | None = None) -> datetime:
    if value is None:
        return taipei_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=TAIPEI)
    return value.astimezone(TAIPEI)


def chinese_weekday(target_date: date) -> str:
    return CHINESE_WEEKDAYS[target_date.weekday()]


def markdown_report_date(target_date: date) -> str:
    return f"{target_date:%Y/%m/%d}（{chinese_weekday(target_date)}）"


def is_weekend(target_date: date) -> bool:
    return target_date.weekday() >= 5


def is_trading_day(target_date: date) -> bool:
    return not is_weekend(target_date)


def previous_trading_day(target_date: date) -> date:
    day = target_date - timedelta(days=1)
    while not is_trading_day(day):
        day -= timedelta(days=1)
    return day


def expected_market_data_date(now: datetime | None = None, cutoff: time = time(23, 0)) -> date:
    taipei_now_value = ensure_taipei(now)
    today = taipei_now_value.date()
    if not is_trading_day(today):
        return previous_trading_day(today)
    if taipei_now_value.time() < cutoff:
        return previous_trading_day(today)
    return today


def iter_recent_calendar_days(start: date, max_days: int) -> list[date]:
    return [start - timedelta(days=offset) for offset in range(max_days)]
