# ChatGPT 每日排程規則更新 Prompt

請更新每日台股掃描排程規則如下：

1. 每次先讀 `data/chatgpt/schedule-readiness.json`。
2. `report_date` 是報告產生日；`as_of_date` / `market_data_date` 是本次掃描依據的收盤行情日。判斷資料是否可用時，以 `as_of_date` / `market_data_date` 與 `checks.latest_market_data_current` 為準，不得因 `report_date` 跨到隔天就自行判定前一交易日收盤資料過期。
3. 若 `schedule_switch.can_switch_daily_scan_schedule=false`，只列出 `blocking_reasons` 與 `warnings`，不得建立新 Watchlist 候選、不得建立 TradePlan、不得產生新的模擬買進候選。
4. 若 `schedule_switch.can_switch_watchlist_schedule=false`，不得新增 Watchlist、不得移除 Watchlist、不得取消 Pending / 候選項目。
5. 若 `schedule_switch.can_switch_position_management_schedule=false`，不得判斷續抱、減碼、停損或出場。
6. `data/chatgpt/symbols/{symbol}.json` 只能作為只讀技術資料查詢來源；不得在任何 schedule gate=false 時，用逐股檔內容推導 Watchlist / Pending / 候選項目的新增、移除或取消。
7. 若 `daily-qullamaggie-source-compact.json.paper_trading_decision_gate.can_create_new_simulated_buy_candidate=false`，不得產生新的模擬候選，也不得建立 TradePlan。
8. 法人、資券或 MOPS 輔助資料不可用時，必須揭露 `warnings`，但不得自行爬外部網站補資料，不得宣稱法人確認、資券風險已驗證或 MOPS 事件方向性解讀。
9. 每次輸出資料狀態時，請列出 `report_date`、`as_of_date`、`market_data_date`、`latest_market_data_date`、`checks`、`schedule_switch`、`blocking_reasons` 與 `warnings`。
10. 當 `can_switch_position_management_schedule=true` 時，必須先讀取 `data/chatgpt/position-management-policy-v1.json`。`plus_2r_v1` 是正式模擬模型；`qullamaggie_3_5d_shadow` 只產生比較快照，不得直接建立減碼或出場紀錄。
11. 持倉評估必須保留原始 `entry_price` 與 `initial_stop`。`trigger_reference` 只作進場門檻稽核，不得作為實際成交價或 R 值分母。
12. 減碼、停損與移動停利一律使用收盤確認。每個模擬事件必須使用 policy 定義的穩定 `event_id`，寫入前先檢查是否已完成或待處理，避免每日重跑重複減碼或重複出場。
13. 若需將正式模型 A 的事件寫入 Google Sheets，寫入後必須回讀驗證；影子模型 B 僅可寫入報告或比較欄位。所有結果均為模擬研究，不得送出真實交易。
