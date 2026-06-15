from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SourceHealth:
    name: str
    checked_at: str
    reachable: bool
    http_status: int | None
    data_date: str | None
    is_current: bool
    date_explicit: bool
    machine_readable: bool
    login_required: bool
    dynamic_loading_suspected: bool
    schedule_ready: bool
    role: str
    evidence: str
    error: str
    response_time_ms: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "checked_at": self.checked_at,
            "reachable": self.reachable,
            "http_status": self.http_status,
            "data_date": self.data_date,
            "is_current": self.is_current,
            "date_explicit": self.date_explicit,
            "machine_readable": self.machine_readable,
            "login_required": self.login_required,
            "dynamic_loading_suspected": self.dynamic_loading_suspected,
            "schedule_ready": self.schedule_ready,
            "role": self.role,
            "evidence": self.evidence,
            "error": self.error,
            "response_time_ms": self.response_time_ms,
        }


@dataclass
class OhlcvRecord:
    date: str
    symbol: str
    name: str
    market: str
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    change: float | None
    change_pct: float | None
    volume: int | None
    turnover: int | None
    transactions: int | None
    source: str

    def to_csv_row(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "open": self.open if self.open is not None else "",
            "high": self.high if self.high is not None else "",
            "low": self.low if self.low is not None else "",
            "close": self.close if self.close is not None else "",
            "change": self.change if self.change is not None else "",
            "change_pct": self.change_pct if self.change_pct is not None else "",
            "volume": self.volume if self.volume is not None else "",
            "turnover": self.turnover if self.turnover is not None else "",
            "transactions": self.transactions if self.transactions is not None else "",
            "source": self.source,
        }


@dataclass
class FetchResult:
    rows: list[OhlcvRecord] = field(default_factory=list)
    data_date: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.rows)

