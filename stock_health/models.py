from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .universe import classify_security


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
    security_type: str = ""
    is_common_stock: bool = False
    is_etf: bool = False
    is_warrant: bool = False
    is_bond_etf: bool = False
    is_leveraged_inverse: bool = False
    is_etn: bool = False
    is_preferred_stock: bool = False
    is_dr: bool = False
    scan_eligible: bool = False
    exclude_reason: str = ""

    def __post_init__(self) -> None:
        if self.security_type:
            return
        classification = classify_security(self.symbol, self.name, self.close, self.volume, self.turnover)
        for key, value in classification.to_dict().items():
            setattr(self, key, value)

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
            "security_type": self.security_type,
            "is_common_stock": _csv_bool(self.is_common_stock),
            "is_etf": _csv_bool(self.is_etf),
            "is_warrant": _csv_bool(self.is_warrant),
            "is_bond_etf": _csv_bool(self.is_bond_etf),
            "is_leveraged_inverse": _csv_bool(self.is_leveraged_inverse),
            "is_etn": _csv_bool(self.is_etn),
            "is_preferred_stock": _csv_bool(self.is_preferred_stock),
            "is_dr": _csv_bool(self.is_dr),
            "scan_eligible": _csv_bool(self.scan_eligible),
            "exclude_reason": self.exclude_reason,
        }


def _csv_bool(value: bool) -> str:
    return "true" if value else "false"


@dataclass
class FetchResult:
    rows: list[OhlcvRecord] = field(default_factory=list)
    data_date: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.rows)


@dataclass
class InstitutionalTradingRecord:
    date: str
    symbol: str
    name: str
    market: str
    foreign_buy: int | None
    foreign_sell: int | None
    foreign_net_buy: int | None
    investment_trust_buy: int | None
    investment_trust_sell: int | None
    investment_trust_net_buy: int | None
    dealer_buy: int | None
    dealer_sell: int | None
    dealer_net_buy: int | None
    institutional_net_buy: int | None
    source: str

    def to_csv_row(self) -> dict[str, Any]:
        return {
            "date": self.date,
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "foreign_buy": self.foreign_buy if self.foreign_buy is not None else "",
            "foreign_sell": self.foreign_sell if self.foreign_sell is not None else "",
            "foreign_net_buy": self.foreign_net_buy if self.foreign_net_buy is not None else "",
            "investment_trust_buy": self.investment_trust_buy if self.investment_trust_buy is not None else "",
            "investment_trust_sell": self.investment_trust_sell if self.investment_trust_sell is not None else "",
            "investment_trust_net_buy": self.investment_trust_net_buy if self.investment_trust_net_buy is not None else "",
            "dealer_buy": self.dealer_buy if self.dealer_buy is not None else "",
            "dealer_sell": self.dealer_sell if self.dealer_sell is not None else "",
            "dealer_net_buy": self.dealer_net_buy if self.dealer_net_buy is not None else "",
            "institutional_net_buy": self.institutional_net_buy if self.institutional_net_buy is not None else "",
            "source": self.source,
        }


@dataclass
class InstitutionalFetchResult:
    rows: list[InstitutionalTradingRecord] = field(default_factory=list)
    data_date: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.rows)
