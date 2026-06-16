from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any


ETF_NAME_KEYWORDS = [
    "ETF",
    "元大",
    "富邦",
    "國泰",
    "群益",
    "復華",
    "凱基",
    "中信",
    "永豐",
    "兆豐",
    "統一",
    "主動",
    "台灣50",
    "高股息",
    "期貨",
    "黃金",
    "原油",
]
BOND_ETF_KEYWORDS = ["美債", "公司債", "金融債", "投資級", "非投等", "債"]
LEVERAGED_INVERSE_KEYWORDS = ["正2", "反1"]
WARRANT_NAME_KEYWORDS = ["認購", "認售", "購", "售", "牛", "熊"]
DR_KEYWORDS = ["DR", "存託"]


@dataclass(frozen=True)
class UniverseClassification:
    security_type: str
    is_common_stock: bool
    is_etf: bool
    is_warrant: bool
    is_bond_etf: bool
    is_leveraged_inverse: bool
    is_etn: bool
    is_preferred_stock: bool
    is_dr: bool
    scan_eligible: bool
    exclude_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_security(
    symbol: str,
    name: str,
    close: float | None,
    volume: int | None,
    turnover: int | None,
) -> UniverseClassification:
    normalized_symbol = (symbol or "").strip()
    normalized_name = (name or "").strip()
    upper_symbol = normalized_symbol.upper()
    upper_name = normalized_name.upper()

    is_etn = "ETN" in upper_name or "ETN" in upper_symbol
    is_bond_etf = _contains_any(normalized_name, BOND_ETF_KEYWORDS)
    is_leveraged_inverse = _contains_any(normalized_name, LEVERAGED_INVERSE_KEYWORDS)
    is_etf = is_etn or is_bond_etf or is_leveraged_inverse or _contains_any(upper_name, ETF_NAME_KEYWORDS)
    is_preferred_stock = "特別股" in normalized_name or "特別" in normalized_name
    is_dr = _contains_any(upper_symbol, DR_KEYWORDS) or _contains_any(upper_name, DR_KEYWORDS)
    is_warrant = (
        (len(normalized_symbol) > 4 and bool(re.search(r"[A-Za-z]", normalized_symbol)))
        or _contains_any(normalized_name, WARRANT_NAME_KEYWORDS)
    )

    close_valid = close is not None and close > 0
    volume_valid = volume is not None and volume > 0
    turnover_valid = turnover is not None and turnover > 0
    is_four_digit_symbol = bool(re.fullmatch(r"\d{4}", normalized_symbol))
    excluded_flags = {
        "etf": is_etf,
        "warrant": is_warrant,
        "bond_etf": is_bond_etf,
        "leveraged_inverse": is_leveraged_inverse,
        "etn": is_etn,
        "preferred_stock": is_preferred_stock,
        "dr": is_dr,
    }
    is_common_stock = (
        is_four_digit_symbol
        and not any(excluded_flags.values())
        and close_valid
        and volume_valid
        and turnover_valid
    )
    scan_eligible = is_common_stock and close_valid and volume_valid and turnover_valid
    security_type = _security_type(
        is_common_stock=is_common_stock,
        is_etf=is_etf,
        is_warrant=is_warrant,
        is_bond_etf=is_bond_etf,
        is_leveraged_inverse=is_leveraged_inverse,
        is_etn=is_etn,
        is_preferred_stock=is_preferred_stock,
        is_dr=is_dr,
    )
    exclude_reason = "" if scan_eligible else _exclude_reason(
        security_type,
        is_four_digit_symbol,
        close_valid,
        volume_valid,
        turnover_valid,
    )

    return UniverseClassification(
        security_type=security_type,
        is_common_stock=is_common_stock,
        is_etf=is_etf,
        is_warrant=is_warrant,
        is_bond_etf=is_bond_etf,
        is_leveraged_inverse=is_leveraged_inverse,
        is_etn=is_etn,
        is_preferred_stock=is_preferred_stock,
        is_dr=is_dr,
        scan_eligible=scan_eligible,
        exclude_reason=exclude_reason,
    )


def build_universe_summary(rows: list[Any]) -> dict[str, Any]:
    excluded_by_type: dict[str, int] = {}
    scan_eligible_rows = 0
    for row in rows:
        if getattr(row, "scan_eligible", False):
            scan_eligible_rows += 1
            continue
        security_type = getattr(row, "security_type", "") or "other"
        excluded_by_type[security_type] = excluded_by_type.get(security_type, 0) + 1
    total_rows = len(rows)
    return {
        "total_rows": total_rows,
        "scan_eligible_rows": scan_eligible_rows,
        "excluded_rows": total_rows - scan_eligible_rows,
        "excluded_by_type": dict(sorted(excluded_by_type.items())),
    }


def _security_type(
    *,
    is_common_stock: bool,
    is_etf: bool,
    is_warrant: bool,
    is_bond_etf: bool,
    is_leveraged_inverse: bool,
    is_etn: bool,
    is_preferred_stock: bool,
    is_dr: bool,
) -> str:
    if is_common_stock:
        return "common_stock"
    if is_preferred_stock:
        return "preferred_stock"
    if is_dr:
        return "dr"
    if is_etn:
        return "etn"
    if is_bond_etf:
        return "bond_etf"
    if is_leveraged_inverse:
        return "leveraged_inverse"
    if is_etf:
        return "etf"
    if is_warrant:
        return "warrant"
    return "other"


def _exclude_reason(
    security_type: str,
    is_four_digit_symbol: bool,
    close_valid: bool,
    volume_valid: bool,
    turnover_valid: bool,
) -> str:
    reasons: list[str] = []
    if security_type != "other":
        reasons.append(f"security_type={security_type}")
    if not is_four_digit_symbol:
        reasons.append("symbol_not_4_digit")
    if not close_valid:
        reasons.append("invalid_close")
    if not volume_valid:
        reasons.append("invalid_volume")
    if not turnover_valid:
        reasons.append("invalid_turnover")
    return ";".join(reasons) if reasons else "not_common_stock"


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)
