# 台股每日資料收集、健康檢查與全市場掃描摘要

本專案建立一套 Python 與 GitHub Actions 自動化流程，用於每日盤後檢查台股資料來源健康狀態、收集官方 OHLCV 資料、產生掃描摘要，並輸出給 ChatGPT 排程讀取的固定 JSON、CSV 與 Markdown 檔案。

系統不需要 GitHub 帳號密碼或 Personal Access Token。GitHub Actions 使用內建 `GITHUB_TOKEN`，權限只需要 `contents: write`。

## 專案結構

```text
stock_health/                 Python 套件
scripts/run_health_check.py   每日健康檢查與資料產生
scripts/bootstrap_history.py  首次回補最近 N 個交易日
docs/chatgpt-task-prompt.md   ChatGPT 排程 Prompt 範例
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
data/latest-screening-summary.json
reports/latest-market-scan.md
```

## GitHub Actions

`daily-health-check.yml` 每週一至週五台灣時間 18:15 執行。GitHub Actions cron 使用 UTC，因此設定為 `15 10 * * 1-5`。流程會先執行 pytest，測試通過後才產生正式資料並提交限定產物。

`bootstrap-history.yml` 僅支援手動執行，input `trading_days` 預設 60。

## latest.json schema

`latest.json` 只保存資料源健康狀態與 coverage 摘要，不包含全市場逐檔 OHLCV 明細。主要欄位：

```text
schema_version, report_date, generated_at, timezone,
market_is_trading_day, latest_market_data_date,
sources, coverage, main_sources, backup_sources,
catalyst_news_sources, manual_review_sources,
not_recommended_sources, artifact_urls,
full_market_scan_ready, missing_sections,
overall_confidence, errors
```

每個來源至少包含：

```text
name, checked_at, reachable, http_status, data_date,
is_current, date_explicit, machine_readable, login_required,
dynamic_loading_suspected, schedule_ready, role, evidence,
error, response_time_ms
```

## latest-screening-summary.json schema

`data/latest-screening-summary.json` 是 ChatGPT 後續排程的主要輸入。它包含資料品質、歷史資料狀態、市場統計、成交量/成交金額/漲幅排行、初步篩選清單、coverage、缺失項目與限制。

若歷史資料不足，系統不會產生 20 日均量、60 日突破或爆量倍數等長週期訊號，並會在 `historical_data_status` 與 `limitations` 中標示。

## Raw URL

將 repository 建立完成並推到 GitHub 後，把 `<OWNER>` 與 `<REPO>` 換成實際值：

```text
https://raw.githubusercontent.com/<OWNER>/<REPO>/main/latest.json
https://raw.githubusercontent.com/<OWNER>/<REPO>/main/data/latest-screening-summary.json
```

若使用 PR branch 測試，可暫時把 `main` 換成 branch 名稱。

## ChatGPT 排程讀取方式

ChatGPT 排程應讀取 `latest.json` 與 `data/latest-screening-summary.json`。若 `full_market_scan_ready=false`，應先說明缺少的核心資料段落，不得把摘要解讀成完整市場掃描。

## 第三方網站限制

官方來源優先於第三方來源。Goodinfo、Yahoo 奇摩股市、鉅亨網、MoneyDJ、TradingView、WantGoo、CMoney 與財報狗只作為候補、催化新聞或人工複核來源。本專案不繞過登入、驗證碼、Cloudflare、付費牆或任何存取控制；遇到 403、429、逾時、動態載入或解析失敗時會記錄實際錯誤。

