from __future__ import annotations

from dataclasses import dataclass
from datetime import date

TIMEZONE = "Asia/Taipei"
SCHEMA_VERSION = "1.0"
HTTP_TIMEOUT_SECONDS = 12
HTTP_RETRIES = 2
HTTP_BACKOFF_SECONDS = 1.5
SCREENING_MAX_CANDIDATES = 50
GITHUB_OWNER = "Wynnlin329"
GITHUB_REPO = "stock_daily_report"
GITHUB_RAW_BRANCH = "codex/stock-health-v1"
GITHUB_REPO_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}"
USER_AGENT = f"stock-daily-report/1.0 (+{GITHUB_REPO_URL})"

MIN_DAILY_TURNOVER = 100_000_000
MIN_AVG_TURNOVER_20D = 50_000_000
MAX_BASE_DEPTH_PCT = 25
MIN_BASE_DAYS = 10
MAX_BASE_DAYS = 30
MAX_EXTENDED_FROM_PIVOT_PCT = 8
MAX_RISK_TO_STOP_PCT = 10
EP_MIN_CHANGE_PCT = 5
EP_MIN_VOLUME_RATIO = 2
BREAKOUT_VOLUME_RATIO = 1.5
CLOSE_NEAR_HIGH_PCT = 75
ANTICIPATION_MIN_DISTANCE_TO_PIVOT_PCT = -3
ANTICIPATION_MAX_DISTANCE_TO_PIVOT_PCT = 1
ADR_WINDOW_DAYS = 20
ATR_WINDOW_DAYS = 14
ATR_METHOD = "sma"
MULTI_PERIOD_RETURN_WINDOWS = {
    "1m": 21,
    "3m": 63,
    "6m": 126,
}
COMPOSITE_RS_WEIGHTS = {
    "1m": 0.40,
    "3m": 0.35,
    "6m": 0.25,
}
QULLAMAGGIE_MAX_CANDIDATES_PER_SETUP = 50
QULLAMAGGIE_MAX_TOP_CANDIDATES = 100
QULLAMAGGIE_SCORE_WEIGHTS = {
    "market_regime": 15,
    "liquidity": 10,
    "trend": 20,
    "base_and_pivot": 20,
    "breakout_and_volume": 20,
    "relative_strength_and_catalyst": 10,
    "risk_control": 5,
}

QULLAMAGGIE_SETUP_TYPES = [
    "breakout",
    "episodic_pivot",
    "anticipation",
    "extended_watch",
    "failed_breakout",
    "insufficient_data",
]

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


def twse_taiex_index_url(target_date: date) -> str:
    return twse_mi_index_url(target_date)


def tpex_index_url(target_date: date) -> str:
    return (
        "https://www.tpex.org.tw/web/stock/iNdex_info/inxh/"
        f"Inx_result.php?l=zh-tw&d={target_date:%Y/%m/%d}&o=json"
    )


def tpex_daily_url(target_date: date) -> str:
    roc_year = target_date.year - 1911
    roc_date = f"{roc_year}/{target_date:%m/%d}"
    return (
        "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/"
        f"stk_quote_result.php?l=zh-tw&d={roc_date}&o=json"
    )


def twse_institutional_url(target_date: date) -> str:
    return (
        "https://www.twse.com.tw/rwd/zh/fund/T86"
        f"?date={target_date:%Y%m%d}&selectType=ALL&response=json"
    )


def tpex_institutional_url(target_date: date) -> str:
    roc_year = target_date.year - 1911
    roc_date = f"{roc_year}/{target_date:%m/%d}"
    return (
        "https://www.tpex.org.tw/web/stock/3insti/daily_trade/"
        f"3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={roc_date}"
    )


def twse_margin_short_url(target_date: date) -> str:
    return (
        "https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
        f"?date={target_date:%Y%m%d}&selectType=STOCK&response=json"
    )


def tpex_margin_short_url(target_date: date) -> str:
    roc_year = target_date.year - 1911
    roc_date = f"{roc_year}/{target_date:%m/%d}"
    return (
        "https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/"
        f"margin_bal_result.php?l=zh-tw&o=json&d={roc_date}"
    )


def mops_major_events_url() -> str:
    return "https://mops.twse.com.tw/mops/web/ajax_t05sr01_1"


def mops_realtime_events_url() -> str:
    return "https://mopsov.twse.com.tw/mops/web/t05sr01_1"


def mops_current_day_events_url() -> str:
    return "https://mopsov.twse.com.tw/mops/web/t05st02"


def mops_historical_events_url() -> str:
    return "https://mopsov.twse.com.tw/mops/web/ajax_t05st01"


def github_raw_url(path: str) -> str:
    normalized_path = path.strip().lstrip("/")
    return f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{GITHUB_RAW_BRANCH}/{normalized_path}"


def source_configs(target_date: date) -> list[SourceConfig]:
    return [
        SourceConfig("twse", "TWSE", "主資料源", twse_mi_index_url(target_date), True, schedule_ready=True),
        SourceConfig("tpex", "TPEx", "主資料源", tpex_daily_url(target_date), True, schedule_ready=True),
        SourceConfig("data_gov_tw", "data.gov.tw", "主資料源", "https://data.gov.tw/", True),
        SourceConfig("mops", "MOPS", "主資料源", mops_realtime_events_url(), True),
        SourceConfig("goodinfo", "Goodinfo", "候補資料源", "https://goodinfo.tw/tw/index.asp", False),
        SourceConfig("yahoo_tw_stock", "Yahoo 奇摩股市", "催化新聞源", "https://tw.stock.yahoo.com/", False, dynamic_loading_suspected=True),
        SourceConfig("cnyes", "鉅亨網 Cnyes", "催化新聞源", "https://www.cnyes.com/twstock/", False, dynamic_loading_suspected=True),
        SourceConfig("moneydj", "MoneyDJ", "催化新聞源", "https://www.moneydj.com/", False),
        SourceConfig("tradingview", "TradingView", "人工複核源", "https://tw.tradingview.com/markets/stocks-taiwan/", False, dynamic_loading_suspected=True),
        SourceConfig("wantgoo", "WantGoo", "人工複核源", "https://www.wantgoo.com/", False, dynamic_loading_suspected=True),
        SourceConfig("cmoney", "CMoney", "人工複核源", "https://www.cmoney.tw/", False, dynamic_loading_suspected=True),
        SourceConfig("statementdog", "財報狗 StatementDog", "人工複核源", "https://statementdog.com/", False, login_required=False, dynamic_loading_suspected=True),
    ]
