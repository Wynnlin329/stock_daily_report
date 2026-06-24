# 台股每日資料收集、健康檢查與全市場掃描摘要

本專案建立一套 Python 與 GitHub Actions 自動化流程，用於每日盤後檢查台股資料來源健康狀態、收集官方 OHLCV 資料、產生掃描摘要，並輸出給 ChatGPT 排程讀取的固定 JSON、CSV 與 Markdown 檔案。

系統不需要 GitHub 帳號密碼或 Personal Access Token。GitHub Actions 使用內建 `GITHUB_TOKEN`，權限只需要 `contents: write`。

## 專案結構

```text
stock_health/                 Python 套件
scripts/run_health_check.py   每日健康檢查與資料產生
scripts/bootstrap_history.py  首次回補最近 N 個交易日
docs/chatgpt-task-prompt.md   ChatGPT 排程 Prompt 範例
docs/chatgpt-schedule-repo-source.md ChatGPT 排程專用資料包說明
latest.json                   最新資料源健康檢查 JSON
latest.md                     最新資料源健康檢查 Markdown
data/                         OHLCV、歷史索引與掃描摘要
reports/latest-market-scan.md 全市場掃描摘要
.github/workflows/            GitHub Actions
```

## 本機安裝

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 測試

```bash
python -m pytest -q
```

網路相關測試使用 mock，不依賴外部網站。

## 回補歷史資料

第一次建立專案時可手動回補最近 60 個交易日：

```bash
python scripts/bootstrap_history.py --trading-days 60
```

腳本會從 Asia/Taipei 執行日往前檢查最多約 120 個自然日，跳過週末，單日失敗不會中止整體流程。若執行環境無法連外，輸出會明確記錄錯誤，不會偽造可用資料。

## 每日健康檢查

```bash
python scripts/run_health_check.py
```

輸出包含：

```text
latest.json
latest.md
history/YYYY/MM/YYYY-MM-DD.json
history/YYYY/MM/YYYY-MM-DD.md
data/latest-listed-ohlcv.csv
data/latest-otc-ohlcv.csv
data/latest-institutional-trading.csv
data/latest-institutional-trading-summary.json
data/latest-margin-short.csv
data/latest-margin-short-summary.json
data/latest-index-summary.json
data/latest-mops-events.json
data/latest-mops-events.csv
data/latest-screening-summary.json
data/chatgpt/schedule-readiness.json
data/chatgpt/daily-qullamaggie-source-compact.json
data/chatgpt/weekly-qullamaggie-source-compact.json
data/chatgpt/symbol-index.json
data/chatgpt/symbols/{symbol}.json
reports/latest-market-scan.md
```

## GitHub Actions

`daily-health-check.yml` 每週一至週五台灣時間 23:55 執行。GitHub Actions cron 使用 UTC，因此設定為 `55 15 * * 1-5`。流程會先執行 pytest，測試通過後才產生正式資料並提交限定產物。

`bootstrap-history.yml` 僅支援手動執行，input `trading_days` 預設 60。

## latest.json schema

`latest.json` 只保存資料源健康狀態與 coverage 摘要，不包含全市場逐檔 OHLCV 明細。主要欄位：

```text
schema_version, report_date, generated_at, timezone,
market_is_trading_day, latest_market_data_date, data_freshness,
sources, coverage, main_sources, backup_sources,
catalyst_news_sources, manual_review_sources,
not_recommended_sources, artifact_urls,
full_market_scan_ready, scan_readiness, missing_sections,
overall_confidence, errors
```

`data_freshness` 會標示 `report_date`、`latest_market_data_date` 與 `is_latest_trading_data_current`。當盤後資料尚未完整發布時，`full_market_scan_ready` 可維持 false，且 `scan_readiness.can_generate_new_paper_trade_candidate=false`。

`scan_readiness` 將「能否執行技術掃描」與「是否可產生新的模擬候選」分開：

```text
can_run_technical_scan, can_run_qullamaggie_scan,
can_generate_new_paper_trade_candidate,
can_use_institutional_confirmation,
can_use_margin_short_risk,
can_use_mops_catalyst, reasons
```

MOPS、法人或資券資料不可用不會阻止技術掃描或 Qullamaggie-style 掃描；但 OHLCV 或 60 日歷史不足、指數歷史不足導致 `market_regime.status=insufficient_data`、盤後最新交易日資料尚未完整，或沒有 breakout / episodic_pivot / anticipation 候選時，不得產生新的模擬候選。

每個來源至少包含：

```text
name, checked_at, reachable, http_status, data_date,
is_current, date_explicit, machine_readable, login_required,
dynamic_loading_suspected, schedule_ready, role, evidence,
error, response_time_ms
```

## latest-screening-summary.json schema

`data/latest-screening-summary.json` 是 pipeline 除錯、稽核與原始掃描結果追溯用輸出，不是 ChatGPT 每日排程的主要輸入。正式 ChatGPT 排程應優先讀取 `data/chatgpt/schedule-readiness.json`、`data/chatgpt/daily-qullamaggie-source-compact.json`、`data/chatgpt/weekly-qullamaggie-source-compact.json`、`data/chatgpt/symbol-index.json` 與 `data/chatgpt/symbols/{symbol}.json`。

`latest-screening-summary.json` 包含資料品質、歷史資料狀態、市場統計、成交量/成交金額/漲幅排行、初步篩選清單、coverage、缺失項目與限制。由於 `rankings`、法人、資券、MOPS 與 Qullamaggie 候選共用穩定 schema，未套用於該區塊的輔助欄位會保留 `null`。不得因 `rankings` 中的法人、資券或 MOPS 欄位為 `null`，直接判斷資料源失效或降低候選股評價。

`historical_data_status`、`institutional_data_status`、`margin_short_data_status` 與 `mops_event_data_status` 皆以 `data/history-index.json` 為準。`history-index.json` 由 `data/market/`、`data/institutional/`、`data/margin_short/` 與 `data/mops/` 的實際檔案掃描重建，避免單一 backfill 清空其他 section。

`data/latest-index-summary.json` 保存 TAIEX 與 TPEx 櫃買指數歷史狀態與 `market_regime`。每日與 bootstrap 流程會輸出：

```text
data/index/taiex/YYYY/MM/YYYY-MM-DD-taiex.csv
data/index/tpex/YYYY/MM/YYYY-MM-DD-tpex.csv
data/latest-index-summary.json
```

指數資料來源為 TWSE `MI_INDEX` 的「發行量加權股價指數」與 TPEx `Inx_result.php` 的「櫃買指數(月查詢)」。至少要有 TAIEX 或 TPEx 50 日有效收盤歷史，才會判斷 `risk_on`、`neutral` 或 `risk_off`；不足時固定為 `insufficient_data`。

若歷史資料不足，系統不會產生 20 日均量、60 日突破或爆量倍數等長週期訊號，並會在 `historical_data_status` 與 `limitations` 中標示。

### 普通股 Universe 過濾

OHLCV CSV 會保留 TWSE / TPEx 原始行情中可解析的各類商品列，並額外輸出以下標準化欄位：

```text
security_type, is_common_stock, is_etf, is_warrant,
is_bond_etf, is_leveraged_inverse, is_etn,
is_preferred_stock, is_dr, scan_eligible, exclude_reason
```

第一版 universe 過濾採用保守的 symbol 與 name 規則。名稱包含 ETF / ETN、主要 ETF 發行商、台灣50、高股息、美債、公司債、金融債、投資級、非投等、正2、反1、期貨、黃金、原油或「債」等關鍵字時，會標示為 ETF / 債券 ETF / 槓反商品並排除。代號長度大於 4 且含英文字母，或名稱包含購、售、牛、熊、認購、認售時，會標示為權證並排除。DR 第一版保守排除；KY 不會只因名稱包含 KY 被排除。

`scan_eligible=true` 代表該列符合第一版普通股條件：4 位數字代號、不是 ETF / 權證 / ETN / 債券 ETF / 槓反 / 特別股 / DR，且 close、volume、turnover 皆大於 0。`rankings`、漲停初篩、爆量、突破與 Qullamaggie-style 候選清單預設只使用 `scan_eligible=true` 的普通股 universe。

這套規則可能誤殺少數普通股，例如名稱碰到 ETF 發行商或「債」等保守關鍵字。日後若接入官方證券分類表，應以官方分類改善本層規則。若要分析 ETF，應新增獨立 ETF 掃描模式，不要混入普通股掃描。

### Qullamaggie-style 動能掃描

`latest-screening-summary.json` 另包含 `qullamaggie` 區塊。這是以 Qullamaggie 常見公開動能交易框架為靈感的可重現欄位計算，僅供研究與人工複核，不代表 Qullamaggie 本人選股，也不輸出買賣建議。

Qullamaggie-style 動能掃描僅處理 `scan_eligible=true` 的普通股。ETF、權證、槓反、債券 ETF、ETN、DR 等仍可保存在原始 OHLCV CSV，但不會進入 `qullamaggie.candidates` 或 `qullamaggie.top_candidates`。

主要門檻集中在 `stock_health/config.py`：

```text
MIN_DAILY_TURNOVER = 100_000_000
MIN_AVG_TURNOVER_20D = 50_000_000
MAX_BASE_DEPTH_PCT = 25
MIN_BASE_DAYS = 10
MAX_BASE_DAYS = 30
BREAKOUT_VOLUME_RATIO = 1.5
MAX_EXTENDED_FROM_PIVOT_PCT = 8
MAX_RISK_TO_STOP_PCT = 10
EP_MIN_CHANGE_PCT = 5
EP_MIN_VOLUME_RATIO = 2
```

主要欄位包含：

```text
ma10, ma20, ma50,
above_ma10, above_ma20, above_ma50, ma20_above_ma50,
avg_volume_20d, volume_ratio_20d, avg_turnover_20d,
daily_range_pct, close_location_pct, close_near_high,
prior_20d_high, prior_60d_high, pivot_price,
distance_to_pivot_pct, breakout_volume_confirmed,
base_days, base_high, base_low, base_depth_pct,
range_contraction, volatility_contraction, tight_close_count,
relative_strength_20d, relative_strength_60d, relative_strength_rank,
relative_strength_rank_basis,
extended_from_pivot_pct, extended_risk, stop_reference, risk_to_stop_pct,
mops_event_flag, revenue_financial_flag, news_topic_flag,
setup_type, qullamaggie_score, score_breakdown
```

`setup_type` 只使用：

```text
breakout, episodic_pivot, anticipation, extended_watch, failed_breakout, insufficient_data
```

歷史資料不足時會停用對應條件：

```text
少於 20 個交易日：不計算 20 日均量、20 日新高、20 日相對強弱、量能倍數。
少於 60 個交易日：不計算 60 日新高、60 日相對強弱，也不宣稱完整 Qullamaggie-style 訊號。
缺少 TAIEX/TPEx 指數歷史：market_regime 為 insufficient_data，相對強弱欄位保留 null。
```

`relative_strength_20d` 與 `relative_strength_60d` 定義為個股 20/60 日報酬減同市場指數 20/60 日報酬；`relative_strength_rank` 是在 `scan_eligible=true` 普通股 universe 中的百分位排名，`relative_strength_rank_basis=scan_eligible_common_stock`。

`market_regime` 使用保守規則：指數收盤高於 MA20 與 MA50、MA20 >= MA50 且 20 日報酬為正時為 `risk_on`；收盤低於 MA20 與 MA50、MA20 < MA50 且 20 日報酬為負時為 `risk_off`；其他為 `neutral`。breakout 不會在 `risk_off` 市場狀態下產生。

`top_candidates` 只會從 `breakout`、`episodic_pivot`、`anticipation` 與 `extended_watch` 排序而來，不包含 `insufficient_data` 或 `failed_breakout`。排序優先順序為 setup 類型、`qullamaggie_score`、`liquidity_ok`、`extended_risk` 與 `relative_strength_rank`。

### 法人買賣超

法人買賣超優先使用官方公開資料來源：

```text
上市：TWSE 三大法人買賣超日報
上櫃：TPEx 三大法人買賣明細資訊
```

每日輸出：

```text
data/latest-institutional-trading.csv
data/latest-institutional-trading-summary.json
data/institutional/YYYY/MM/YYYY-MM-DD-listed-institutional.csv
data/institutional/YYYY/MM/YYYY-MM-DD-otc-institutional.csv
```

標準化欄位包含：

```text
foreign_buy, foreign_sell, foreign_net_buy,
investment_trust_buy, investment_trust_sell, investment_trust_net_buy,
dealer_buy, dealer_sell, dealer_net_buy,
institutional_net_buy
```

`institutional_net_buy` 是外資、投信與自營商買賣超合計。若官方欄位缺失，系統不會補值；summary 會在 `errors` 或 `limitations` 標示資料不足。

`screening.institutional_buy_candidates` 僅列出 `scan_eligible=true` 且 `institutional_net_buy > 0` 的普通股，依三大法人合計買超排序，最多 50 檔。這只作為研究與人工複核清單，不是買進訊號，也不輸出目標價或停損價。若法人資料缺失，`coverage.institutional_trading.available` 會保持 false。

Qullamaggie-style candidate 會附上可選欄位 `foreign_net_buy`、`investment_trust_net_buy`、`dealer_net_buy`、`institutional_net_buy` 與 `institutional_confirmation`。法人買超只作為確認資訊與 tag，不會單獨產生 breakout 或其他技術 setup。

### 融資融券

融資融券優先使用官方公開資料來源：

```text
上市：TWSE 融資融券彙總（股票）
上櫃：TPEx 上櫃股票融資融券餘額
```

每日輸出：

```text
data/latest-margin-short.csv
data/latest-margin-short-summary.json
data/margin_short/YYYY/MM/YYYY-MM-DD-listed-margin-short.csv
data/margin_short/YYYY/MM/YYYY-MM-DD-otc-margin-short.csv
```

標準化欄位包含：

```text
margin_buy, margin_sell, margin_balance, margin_change,
short_sell, short_cover, short_balance, short_change,
offsetting
```

`margin_balance` 是融資餘額，`margin_change` 是融資餘額日變化；`short_balance` 是融券餘額，`short_change` 是融券餘額日變化。若官方來源只提供部分欄位，缺失欄位會保留 null，不會補值。

`screening.margin_short_attention` 僅列出 `scan_eligible=true` 且資券餘額或變化需要人工複核的普通股。此清單只作為籌碼與風險複核，不是方向性訊號。ChatGPT 或人工摘要不得把融資或融券變化單獨視為買賣訊號。

Qullamaggie-style candidate 會附上可選欄位 `margin_balance`、`margin_change`、`short_balance`、`short_change`、`margin_balance_ratio_20d`、`short_balance_ratio_20d` 與 `margin_short_attention_flag`。資券資料只作為風險資訊，不會改變 breakout、anticipation 等 setup 判定。

### MOPS 重大訊息

重大訊息優先使用 MOPSOV 即時重大訊息公開頁：

```text
https://mopsov.twse.com.tw/mops/web/t05sr01_1
```

若即時頁不可用，才嘗試 `https://mopsov.twse.com.tw/mops/web/t05st02` 作為第二來源。手動歷史回補使用 MOPSOV 歷史重大訊息查詢端點 `https://mopsov.twse.com.tw/mops/web/ajax_t05st01`，以空公司代號低頻查詢單一日期的全市場重大訊息。若任何 MOPS 來源回傳 security page、驗證頁或禁止存取頁，系統會立即停止該 MOPS 來源，標示 `blocked_or_security_page`，且不嘗試繞過、不使用瀏覽器自動化、不偽造 Cookie/Token/Session。每日輸出：

```text
data/latest-mops-events.json
data/latest-mops-events.csv
data/mops/YYYY/MM/YYYY-MM-DD-mops-events.json
data/mops/YYYY/MM/YYYY-MM-DD-mops-events.csv
```

JSON 欄位包含：

```text
schema_version, report_date, generated_at, timezone,
data_date, is_current, event_count, status, source_url, events, errors, limitations
```

CSV 與 `events` 欄位包含：

```text
date, time, symbol, name, market, title, category, summary, url, source
```

第一版分類只用公告標題與摘要的可重現關鍵字：財報、營收、股利、除權息、董事會、併購、處分資產、取得資產、增資、減資、法說會、重大合約、訴訟、注意事項；未命中則為「其他」。若 MOPS 回傳安全頁、無法解析、或沒有明確資料日期，`coverage.material_information.available=false`，不會把請求日期當成資料日期。

MOPS 歷史預設採 forward accumulation：每日 GitHub Actions 抓一次即時重大訊息並寫入 `data/mops/YYYY/MM/`，自然累積成 7 日、30 日、90 日事件歷史。`bootstrap_history.py` 預設不強制回補 90 天；只有手動指定 `--include-mops-backfill` 才會改用 `t05st01` 歷史查詢端點，低頻嘗試少量日期，且任一天遇到 security page 會立即停止。`screening.mops_event_candidates` 僅列出今日或近 7 日有 MOPS 事件且 `scan_eligible=true` 的普通股。重大訊息只作為研究與人工複核清單，不代表利多，也不得自動解讀為方向性訊號。

Qullamaggie-style candidate 會附上 `mops_event_flag`、`mops_event_count`、`mops_event_categories`、`mops_event_titles` 與 `catalyst_tags`。MOPS 事件只作為 catalyst，不會單獨產生 breakout；episodic pivot 仍需符合既有價格、量能與流動性條件。

### 歷史資料窗口

本專案的歷史窗口固定如下：

```text
OHLCV：60 個交易日，用於技術面、突破、量能與 Qullamaggie-style setup。
法人買賣超：60 個交易日，用於 5D / 20D / 60D 累積買賣超與連買連賣天數。
融資融券：60 個交易日，用於 5D / 20D / 60D 餘額變化、20D 比例與資券風險複核。
MOPS 重大訊息：每日累積，手動 backfill 可用 `t05st01` 低頻回補，最多使用近 90 個自然日，用於 7D / 30D / 90D 事件統計與 catalyst 標記。
```

法人資料只作為籌碼確認，不是買進訊號。融資融券只作為籌碼與風險複核，不是買賣訊號。MOPS 重大訊息不等於利多，需人工閱讀公告內容確認事件性質。ChatGPT 排程必須尊重 `coverage`、`institutional_data_status`、`margin_short_data_status` 與 `mops_event_data_status`；若資料不可用，不得自行爬外部網站補資料。

## Raw URL

目前 repository default branch 是 `codex/stock-health-v1`。排程請使用以下可直接讀取的 Raw URL：

```text
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/latest.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/latest-screening-summary.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/latest-index-summary.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/latest-mops-events.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/history-index.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/schedule-readiness.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/daily-qullamaggie-source-compact.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/weekly-qullamaggie-source-compact.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/daily-qullamaggie-source.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/weekly-qullamaggie-source.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/symbol-index.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/reports/chatgpt-daily-qullamaggie-source.md
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/reports/chatgpt-weekly-qullamaggie-source.md
```

Raw URL 由 `stock_health/config.py` 的 `GITHUB_OWNER`、`GITHUB_REPO`、`GITHUB_RAW_BRANCH` 與 `github_raw_url()` 集中產生。`<OWNER>/<REPO>/main` 這類 placeholder 只適合模板，不是本 repository 目前可用 URL。若未來正式改用 `main`，只需修改 `GITHUB_RAW_BRANCH` 並重產 artifacts。

程式中的 Raw URL 由 `stock_health/config.py` 的 `GITHUB_OWNER`、`GITHUB_REPO`、`GITHUB_RAW_BRANCH` 與 `github_raw_url()` 集中產生。若未來 repository 合併到 `main` 並改用 `main` 作為正式讀取分支，只需把 `GITHUB_RAW_BRANCH` 改成 `main`，不要在 README、prompt 或 runner 中分散硬編碼。

`<OWNER>/<REPO>/main` 這類 placeholder 只適合專案模板，不是本 repository 目前可用的讀取 URL。

## ChatGPT 排程讀取方式

ChatGPT 排程必須先讀取 `data/chatgpt/schedule-readiness.json`，再依 gate 狀態讀取 `data/chatgpt/daily-qullamaggie-source-compact.json` 與 `data/chatgpt/weekly-qullamaggie-source-compact.json`。完整 `daily-qullamaggie-source.json`、`weekly-qullamaggie-source.json` 與 `data/latest-screening-summary.json` 僅供除錯、稽核或回查原始欄位，不應作為每日選股主輸入。

若 `schedule_switch.can_switch_daily_scan_schedule=false`，應先說明 `blocking_reasons`，不得建立新 Watchlist 候選或 TradePlan。若 `schedule_switch.can_switch_position_management_schedule=false`，不得判斷續抱、減碼、停損或出場。`warnings` 必須揭露；法人、資券或 MOPS 輔助資料不可用不一定代表技術掃描失敗。

若需要動能候選清單，ChatGPT 應優先讀取 `data/chatgpt/daily-qullamaggie-source-compact.json` 的 `top_candidates` 與各 setup 分組，不應重新爬外部網站。compact 內的候選欄位已針對 ChatGPT 排程整理，`latest-screening-summary.json.rankings` 中大量 `null` 不得用來判斷候選股資料不完整。`top_candidates` 與各 setup 分組都只可作為研究與人工複核清單。

若需要查詢單一普通股技術欄位，ChatGPT 應先讀取 `data/chatgpt/symbol-index.json`，再依股票代號讀取 `data/chatgpt/symbols/{symbol}.json`。逐檔檔案只為 `scan_eligible=true` 的普通股產生，至少包含 OHLCV、MA10/20/50、20 日均量與量比、pivot、風險參考、setup 與 risk notes。

若需要重大事件清單，ChatGPT 應讀取 `data/latest-mops-events.json` 與 `screening.mops_event_candidates`，不得重新爬 MOPS，也不得把重大訊息自動解讀為利多。摘要時應列出公司、分類、標題與需要人工閱讀確認的重點。

## 第三方網站限制

官方來源優先於第三方來源。Goodinfo、Yahoo 奇摩股市、鉅亨網、MoneyDJ、TradingView、WantGoo、CMoney 與財報狗只作為候補、催化新聞或人工複核來源。本專案不繞過登入、驗證碼、Cloudflare、付費牆或任何存取控制；遇到 403、429、逾時、動態載入或解析失敗時會記錄實際錯誤。
