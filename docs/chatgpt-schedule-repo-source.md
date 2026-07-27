# ChatGPT 排程專用資料包

本專案每日 health check 會產生 ChatGPT 排程可直接讀取的整合資料包。排程應優先讀取這些檔案，不要在 ChatGPT 端重新爬 TWSE、TPEx、MOPS 或第三方網站。

## Daily Source

每日排程優先讀 compact JSON：

```text
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/daily-qullamaggie-source-compact.json
```

完整 JSON 與 Markdown 只供除錯或人工檢查：

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

每週排程優先讀 compact JSON：

```text
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/weekly-qullamaggie-source-compact.json
```

完整 JSON 與 Markdown 只供除錯或人工檢查：

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

v2 影子比較欄位加入後，symbol JSON 與 symbol index 的 schema version 為 `1.4`。

每個 symbol JSON 至少包含：

- `date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `turnover`
- `ma10`
- `ma20`
- `ma50`
- `avg_volume_20d`
- `volume_ratio_20d`
- `pivot_price`
- `stop_reference`
- `adr20_pct`
- `atr14`
- `atr14_pct`
- `stop_risk_pct`
- `stop_to_adr_ratio`
- `stop_to_atr_ratio`
- `return_1m`
- `return_3m`
- `return_6m`
- `rs_rank_1m`
- `rs_rank_3m`
- `rs_rank_6m`
- `composite_rs_rank`
- `missing_reason`
- `indicator_basis`
- `prior_move_pct_20d`
- `prior_move_pct_60d`
- `distance_to_52w_high_pct`
- `flag_duration_days`
- `flag_depth_pct`
- `higher_lows_count`
- `range_contraction_ratio`
- `volume_contraction_ratio`
- `ma10_slope`
- `ma20_slope`
- `distance_to_ma10_pct`
- `distance_to_ma20_pct`
- `monthly_above_ma12`
- `weekly_trend_state`
- `daily_trigger_state`
- `htf_structure_score`
- `htf_structure_status`
- `htf_rejection_reasons`
- `htf_missing_reason`
- `htf_structure_basis`
- `htf_data_quality`
- `setup_type`
- `extended_risk`
- `risk_notes`
- `data_quality.ohlcv_complete`
- `data_quality.technical_indicators_complete`
- `data_quality.enhanced_indicators_complete`
- `data_quality.enhanced_indicator_missing_reason`
- `data_quality.htf_structure_complete`
- `data_quality.htf_structure_missing_reason`
- `data_quality.source_market_file`

這些逐檔檔案只保存研究用技術資料，不輸出真實交易建議。

波動欄位與多期間 RS 欄位定義以 README 為準。它們會同步出現在 daily／weekly compact candidate；資料不足時必須保留 `null` 並讀取 `missing_reason`。這些欄位供 v2 影子評分，但不參與正式 v1 grading policy，不得據此自行改寫既有 A／A-／B／C。

HTF 欄位定義以 `docs/high-tight-flag.md` 為準。`htf_structure_status` 不可由 `setup_type=anticipation` 推導，必須使用逐股 JSON 或 compact 中的原始數值、狀態與 `htf_rejection_reasons`。v2 只在影子模式使用這些欄位。

## v2 Shadow Grading

```text
data/chatgpt/qullamaggie-grading-policy-v2.json
data/chatgpt/grading-shadow-v2-latest.json
data/grading-shadow-v2/history-index.json
data/grading-shadow-v2/YYYY/MM/YYYY-MM-DD.json
```

逐股 JSON、symbol index 與 daily／weekly compact 同時輸出 `grade_v1`、`score_v1`、`grade_v2_shadow`、`score_v2_shadow`、`grade_difference`、`v2_rejection_reasons`。正式 Watchlist 與 TradePlan 固定使用 v1；`v2_may_drive_business_writes=false`。

`checks.grading_v2_shadow_20d_ready` 是非阻擋檢查。歷史索引只計算實際產生且通過日期／routing 驗證的影子檔案，未滿 20 個交易日不會回填舊日推算值。市場 Gate 只影響 `market_gate_shadow`，不會改寫 v2 品質分數。

## Simulated Position Management

```text
data/chatgpt/position-management-policy-v1.json
docs/position-management-state-machine.md
```

正式模擬持倉模型是 `plus_2r_v1`；`qullamaggie_3_5d_shadow` 只輸出比較 snapshot，不得驅動 SimExit、TradeLog 或持倉狀態寫入。兩個模型都保留原始 `entry_price` 與 `initial_stop`，且不得使用 trigger 代替實際 Entry。

狀態機事件使用穩定 event ID。Google Sheets 寫入前必須以 event ID 查重，寫入後回讀並把 ID 保存至 `completed_event_ids`。同一 pending event 重跑時 `events_to_create` 必須為空，避免重複減碼或重複出場。

若 `schedule_switch.can_switch_position_management_schedule=false`，兩個模型都不得產生新的持倉管理事件。即使 Gate 允許，本階段也只執行模擬資料寫入，不進行真實交易或券商操作。

## Episodic Pivot

```text
data/chatgpt/episodic-pivot-policy-v1.json
docs/episodic-pivot.md
```

EP 使用獨立的 `ep_quality_score` 與 `ep_status`，不得沿用一般 Breakout 分數。只有 `ep_status=valid_ep` 可成為 `setup_type=episodic_pivot`；`insufficient_data` 不得由 ChatGPT 自行補足。

MOPS 僅驗證事件存在。事件方向、驚喜程度、營收與 EPS 成長以及盤中 opening range 欄位沒有可靠資料時均為 `null`。ChatGPT 不得從標題推測事件方向，也不得用外部網站補值。

## Schedule Readiness

正式切換排程前先讀：

```text
https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/schedule-readiness.json
```

`schedule-readiness.json` 會列出：

- `report_date`
- `as_of_date`
- `market_data_date`
- `latest_market_data_date`
- `checks.latest_market_data_current`
- `checks.technical_scan_ready`
- `checks.qullamaggie_scan_ready`
- `checks.daily_compact_source_ready`
- `checks.symbol_index_ready`
- `checks.symbol_ohlcv_complete`
- `checks.screening_history_5d_ready`
- `checks.weekly_compact_source_ready`
- `checks.weekly_review_gate_ready`
- `checks.enhanced_technical_indicators_complete`
- `checks.htf_structure_complete`
- `checks.grading_v2_shadow_20d_ready`
- `non_blocking_checks`
- `enhanced_indicator_completeness`
- `htf_structure_completeness`
- `grading_v2_shadow_completeness`
- `schedule_switch.can_switch_daily_scan_schedule`
- `schedule_switch.can_switch_watchlist_schedule`
- `schedule_switch.can_switch_position_management_schedule`
- `schedule_switch.can_switch_weekly_review_schedule`
- `schedule_switch.can_switch_all_schedules`

`report_date` 是報告產生日；`as_of_date` / `market_data_date` 是本次掃描依據的收盤行情日。若 GitHub Actions 延遲到隔天凌晨，`report_date` 可能是隔天，但 `market_data_date` 仍應是前一個交易日，ChatGPT 不得因此把前一交易日收盤資料視為過期。

法人、資券與 MOPS 缺失可列入 `warnings`，但不得在 OHLCV 與技術資料完整時單獨阻止每日技術選股。若 `warnings` 顯示法人或資券停用，ChatGPT 不得宣稱法人確認，也不得宣稱資券風險已驗證。

`checks.enhanced_technical_indicators_complete` 屬於 `non_blocking_checks`。在 126 個有效交易日尚未累積完成前可以為 false，但不得因此單獨關閉現有 schedule switch。

`checks.htf_structure_complete` 同樣屬於 `non_blocking_checks`。在 252 個有效交易日與 12 個月份尚未累積完成前可以為 false，不得因此單獨改變正式 v1 分級或關閉現有 schedule switch。

若 `schedule_switch.can_switch_watchlist_schedule=false`，ChatGPT 不得新增、移除或取消 Watchlist / Pending / 候選項目。逐股 `data/chatgpt/symbols/{symbol}.json` 只能作為只讀技術資料查詢，不得在 gate=false 時驅動狀態變更。

## Screening History

每日執行會保留：

```text
data/screening/YYYY/MM/YYYY-MM-DD-screening-summary.json
```

這份檔案是 weekly source 的唯一輸入來源。週度資料包不重新計算行情，也不回頭爬外部網站。

`data/screening/history-index.json` 記錄最近 5 個有效 screening summary、缺漏日期與 lookahead 檢查結果。weekly gate 只使用通過 as-of 檢查的 5 個交易日。

## Artifact URLs

`latest.json.artifact_urls` 會包含：

- `chatgpt_daily_qullamaggie_source`
- `chatgpt_daily_qullamaggie_compact`
- `chatgpt_weekly_qullamaggie_source`
- `chatgpt_weekly_qullamaggie_compact`
- `chatgpt_symbol_index`
- `chatgpt_schedule_readiness`
- `position_management_policy`
- `episodic_pivot_policy`
- `screening_history_index`
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
