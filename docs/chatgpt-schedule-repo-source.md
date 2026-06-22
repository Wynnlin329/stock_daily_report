# ChatGPT 排程專用資料包

本專案每日 health check 會產生 ChatGPT 排程可直接讀取的整合資料包。排程應優先讀取這些檔案，不要在 ChatGPT 端重新爬 TWSE、TPEx、MOPS 或第三方網站。

## Daily Source

```text
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/daily-qullamaggie-source.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/reports/chatgpt-daily-qullamaggie-source.md
```

`data/chatgpt/daily-qullamaggie-source.json` 包含：

- `report_date`
- `generated_at`
- `timezone`
- `data_freshness`
- `scan_readiness`
- `source_urls`
- `market_context`
- `data_status`
- `qullamaggie_style`
- `paper_trading_decision_gate`
- `supporting_candidates`
- `reporting_rules`

`paper_trading_decision_gate.can_create_new_simulated_buy_candidate=false` 時，ChatGPT 只能產生資料狀態報告、研究清單或觀察名單，不得產生新的模擬候選。法人、資券與 MOPS 是確認或風險複核資料，不會單獨解除技術資料不足或資料過期的限制。

## Weekly Source

```text
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/weekly-qullamaggie-source.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/reports/chatgpt-weekly-qullamaggie-source.md
```

`data/chatgpt/weekly-qullamaggie-source.json` 由 `data/screening/YYYY/MM/YYYY-MM-DD-screening-summary.json` 最近 5 份 screening summary 組成，包含：

- `week_data_status`
- `weekly_setup_summary`
- `weekly_supporting_data`
- `next_week_watchlist_candidates`
- `paper_trading_weekly_review_gate`

若最近 5 份 screening summary 不足，`paper_trading_weekly_review_gate.can_generate_weekly_review=false`，ChatGPT 只能說明可用資料與缺口。

## Symbol Source

```text
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/symbol-index.json
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/symbols/{symbol}.json
```

`data/chatgpt/symbol-index.json` 列出所有已產生逐檔資料的 `scan_eligible=true` 普通股。查詢單一股票時，先用 index 確認代號存在，再讀取 `data/chatgpt/symbols/{symbol}.json`。

每個 symbol JSON 至少包含：

- `date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `ma10`
- `ma20`
- `ma50`
- `avg_volume_20d`
- `volume_ratio_20d`
- `pivot_price`
- `stop_reference`
- `setup_type`
- `extended_risk`
- `risk_notes`

這些逐檔檔案只保存研究用技術資料，不輸出真實交易建議。

## Screening History

每日執行會保留：

```text
data/screening/YYYY/MM/YYYY-MM-DD-screening-summary.json
```

這份檔案是 weekly source 的唯一輸入來源。週度資料包不重新計算行情，也不回頭爬外部網站。

## Artifact URLs

`latest.json.artifact_urls` 會包含：

- `chatgpt_daily_qullamaggie_source`
- `chatgpt_weekly_qullamaggie_source`
- `chatgpt_symbol_index`
- `chatgpt_daily_qullamaggie_markdown`
- `chatgpt_weekly_qullamaggie_markdown`

Raw URL 由 `stock_health/config.py` 的 `github_raw_url()` 集中產生。目前正式讀取分支是 `codex/stock-health-v1`；若未來改成 `main`，只需調整 `GITHUB_RAW_BRANCH` 並重產 artifacts。

## 排程規則

- 只使用 repository artifacts。
- 不自行爬外部網站。
- 不把 MOPS 重大訊息解讀成方向性訊號。
- 不把法人買賣超或資券變化解讀成單獨訊號。
- 不輸出真實交易建議用語，例如目標價或停損價。
- Qullamaggie-style 是規則化研究篩選，非 Qullamaggie 本人選股。
