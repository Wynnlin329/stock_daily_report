from __future__ import annotations

from datetime import date
from typing import Any

from .config import SCHEMA_VERSION, TIMEZONE
from .models import IndexRecord
from .qullamaggie import calculate_market_regime


def build_index_summary(
    report_date: date,
    generated_at: str,
    index_rows: dict[str, list[IndexRecord]],
    benchmark_history: dict[str, list[float]],
    errors: list[str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    market_regime = calculate_market_regime(benchmark_history)
    return {
        "schema_version": SCHEMA_VERSION,
        "report_date": f"{report_date:%Y-%m-%d}",
        "generated_at": generated_at,
        "timezone": TIMEZONE,
        "taiex": _index_status(index_rows.get("taiex", []), report_date),
        "tpex_index": _index_status(index_rows.get("tpex_index", []), report_date),
        "market_regime": market_regime,
        "errors": errors or [],
        "limitations": _limitations(index_rows, market_regime, limitations or []),
    }


def _index_status(rows: list[IndexRecord], report_date: date) -> dict[str, Any]:
    valid_rows = [row for row in rows if row.close is not None and row.close > 0]
    data_date = valid_rows[-1].date if valid_rows else None
    return {
        "data_date": data_date,
        "is_current": data_date == f"{report_date:%Y-%m-%d}" if data_date else False,
        "rows": len(valid_rows),
        "has_20d_history": len(valid_rows) >= 20,
        "has_50d_history": len(valid_rows) >= 50,
        "has_60d_history": len(valid_rows) >= 60,
    }


def _limitations(
    index_rows: dict[str, list[IndexRecord]],
    market_regime: dict[str, Any],
    base_limitations: list[str],
) -> list[str]:
    limitations = list(base_limitations)
    if market_regime.get("status") == "insufficient_data":
        limitations.append("TAIEX 或 TPEx 指數歷史不足 50 日，market_regime 不宣稱 risk_on / neutral / risk_off。")
    if not index_rows.get("taiex"):
        limitations.append("TAIEX 指數歷史尚未建立。")
    if not index_rows.get("tpex_index"):
        limitations.append("TPEx 櫃買指數歷史尚未建立。")
    return list(dict.fromkeys(limitations))
