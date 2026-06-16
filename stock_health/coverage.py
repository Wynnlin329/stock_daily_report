from __future__ import annotations

from .config import CORE_COVERAGE_SECTIONS, COVERAGE_SECTIONS
from .models import InstitutionalTradingRecord, OhlcvRecord, SourceHealth


def build_coverage(
    sources: dict[str, SourceHealth],
    listed_rows: list[OhlcvRecord],
    otc_rows: list[OhlcvRecord],
    has_20d_history: bool = False,
    has_60d_history: bool = False,
    institutional_rows: list[InstitutionalTradingRecord] | None = None,
    institutional_is_current: bool = False,
) -> tuple[dict[str, dict[str, object]], bool, list[str]]:
    source_current = {key: value.is_current and value.date_explicit for key, value in sources.items()}
    any_rows = bool(listed_rows or otc_rows)
    institutional_rows = institutional_rows or []
    institutional_available = bool(institutional_rows) and institutional_is_current and any(
        row.symbol and _has_institutional_values(row) for row in institutional_rows
    )
    coverage = {
        "market_environment": _item(source_current.get("twse", False), "TWSE", "TWSE has explicit current market date" if source_current.get("twse", False) else "TWSE current market environment not verified"),
        "listed_ohlcv": _item(bool(listed_rows), "TWSE", f"{len(listed_rows)} listed rows parsed" if listed_rows else "Listed OHLCV unavailable"),
        "otc_ohlcv": _item(bool(otc_rows), "TPEx", f"{len(otc_rows)} OTC rows parsed" if otc_rows else "OTC OHLCV unavailable"),
        "volume_ranking": _item(any_rows, "official_ohlcv", "Computed from official OHLCV" if any_rows else "Requires listed or OTC OHLCV"),
        "turnover_ranking": _item(any_rows, "official_ohlcv", "Computed from official OHLCV" if any_rows else "Requires listed or OTC OHLCV"),
        "price_change_screening": _item(any_rows, "official_ohlcv", "Computed from official OHLCV" if any_rows else "Requires listed or OTC OHLCV"),
        "limit_up_screening": _item(any_rows, "official_ohlcv", "Estimated from daily change percent" if any_rows else "Requires listed or OTC OHLCV"),
        "volume_spike_screening": _item(any_rows and has_20d_history, "official_ohlcv_history", "20-day volume history available" if has_20d_history else "Requires at least 20 trading days of history"),
        "institutional_trading": _item(
            institutional_available,
            "TWSE/TPEx",
            f"{len(institutional_rows)} institutional rows parsed from official sources"
            if institutional_available
            else "Institutional trading unavailable or data date not current",
        ),
        "margin_short": _item(False, "TWSE/TPEx", "First version does not parse margin short data yet"),
        "material_information": _item(source_current.get("mops", False), "MOPS", "MOPS current material information verified" if source_current.get("mops", False) else "MOPS material information date not verified"),
        "revenue_financials": _item(False, "MOPS", "First version does not parse revenue or financial statements yet"),
        "news_topics": _item(any(sources[key].reachable for key in ("yahoo_tw_stock", "cnyes", "moneydj") if key in sources), "news_sources", "At least one catalyst news source reachable"),
        "technical_review": _item(False, "manual_review", "TradingView/WantGoo/CMoney are manual review sources, not automated signals"),
    }
    ordered = {key: coverage[key] for key in COVERAGE_SECTIONS}
    missing = [key for key in CORE_COVERAGE_SECTIONS if not bool(ordered[key]["available"])]
    return ordered, not missing, missing


def _item(available: bool, source: str, notes: str) -> dict[str, object]:
    return {"available": available, "source": source, "notes": notes}


def _has_institutional_values(row: InstitutionalTradingRecord) -> bool:
    return any(
        value is not None
        for value in (
            row.institutional_net_buy,
            row.foreign_net_buy,
            row.investment_trust_net_buy,
            row.dealer_net_buy,
        )
    )
