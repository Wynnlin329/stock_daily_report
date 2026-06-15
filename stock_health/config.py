from __future__ import annotations

from dataclasses import dataclass
from datetime import date

TIMEZONE = "Asia/Taipei"
SCHEMA_VERSION = "1.0"
HTTP_TIMEOUT_SECONDS = 12
HTTP_RETRIES = 2
HTTP_BACKOFF_SECONDS = 1.5
USER_AGENT = "stock-daily-report/1.0 (+https://github.com/<OWNER>/<REPO>)"

ALLOWED_ROLES = {
    "主資料源",
    "候補資料源",
    "催化新聞源",
    "人工複核源",
    "不建議自動化",
}

CORE_COVERAGE_SECTIONS = [
    "market_environment",
    "listed_ohlcv",
    "otc_ohlcv",
    "institutional_trading",
    "margin_short",
    "material_information",
]

COVERAGE_SECTIONS = [
    "market_environment",
    "listed_ohlcv",
    "otc_ohlcv",
    "volume_ranking",
    "turnover_ranking",
    "price_change_screening",
    "limit_up_screening",
    "volume_spike_screening",
    "institutional_trading",
    "margin_short",
    "material_information",
    "revenue_financials",
    "news_topics",
    "technical_review",
]


@dataclass(frozen=True)
class SourceConfig:
    key: str
    name: str
    role: str
    url: str
    machine_readable: bool
    login_required: bool = False
    dynamic_loading_suspected: bool = False
    schedule_ready: bool = False


def twse_mi_index_url(target_date: date) -> str:
    return (
        "https://www.twse.com.tw/exchangeReport/MI_INDEX"
        f"?response=json&date={target_date:%Y%m%d}&type=ALLBUT0999"
    )


def tpex_daily_url(target_date: date) -> str:
    roc_year = target_date.year - 1911
    roc_date = f"{roc_year}/{target_date:%m/%d}"
    return (
        "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/"
        f"stk_quote_result.php?l=zh-tw&d={roc_date}&o=json"
    )


def source_configs(target_date: date) -> list[SourceConfig]:
    return [
        SourceConfig("twse", "TWSE", "主資料源", twse_mi_index_url(target_date), True, schedule_ready=True),
        SourceConfig("tpex", "TPEx", "主資料源", tpex_daily_url(target_date), True, schedule_ready=True),
        SourceConfig("data_gov_tw", "data.gov.tw", "主資料源", "https://data.gov.tw/", True),
        SourceConfig("mops", "MOPS", "主資料源", "https://mops.twse.com.tw/mops/web/index", True),
        SourceConfig("goodinfo", "Goodinfo", "候補資料源", "https://goodinfo.tw/tw/index.asp", False),
        SourceConfig("yahoo_tw_stock", "Yahoo 奇摩股市", "催化新聞源", "https://tw.stock.yahoo.com/", False, dynamic_loading_suspected=True),
        SourceConfig("cnyes", "鉅亨網 Cnyes", "催化新聞源", "https://www.cnyes.com/twstock/", False, dynamic_loading_suspected=True),
        SourceConfig("moneydj", "MoneyDJ", "催化新聞源", "https://www.moneydj.com/", False),
        SourceConfig("tradingview", "TradingView", "人工複核源", "https://tw.tradingview.com/markets/stocks-taiwan/", False, dynamic_loading_suspected=True),
        SourceConfig("wantgoo", "WantGoo", "人工複核源", "https://www.wantgoo.com/", False, dynamic_loading_suspected=True),
        SourceConfig("cmoney", "CMoney", "人工複核源", "https://www.cmoney.tw/", False, dynamic_loading_suspected=True),
        SourceConfig("statementdog", "財報狗 StatementDog", "人工複核源", "https://statementdog.com/", False, login_required=False, dynamic_loading_suspected=True),
    ]

