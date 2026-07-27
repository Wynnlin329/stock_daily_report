# 模擬持倉管理狀態機

本模組只產生模擬建議與結構化狀態，不執行真實交易、不連接券商，也不直接寫入 Google Sheets。

## 不可變欄位

- `entry_price` 必須是收盤確認後的實際模擬成交價。
- `initial_stop` 必須是進場時保存的原始停損。
- `trigger_reference` 只供計畫稽核，不參與 R 值分母，也不得取代 `entry_price`。
- 狀態機輸出會原樣保留 `entry_price` 與 `initial_stop`。

R 值固定使用：

```text
current_r = (current_close - entry_price) / (entry_price - initial_stop)
max_r_reached = (max_close_since_entry - entry_price) / (entry_price - initial_stop)
```

若 `initial_stop >= entry_price`、缺少價格歷史或欄位型別錯誤，狀態為 `invalid_data`，不產生模擬出場事件。

## 模型

參數集中於：

```text
data/chatgpt/position-management-policy-v1.json
```

### 模型 A：plus_2r_v1

- 正式模擬模型。
- 預設歷史收盤 `max_r_reached >= 2.0` 時建議減碼 50%；達標後即使目前 R 值回落，仍保留已達標事實。
- 完成部分減碼後啟動成本停損。
- 剩餘部位預設使用 10MA，以收盤跌破確認移動停利。

### 模型 B：qullamaggie_3_5d_shadow

- 只供影子比較，不驅動正式模擬紀錄。
- 進場後第 3 至第 5 個有效交易日建議減碼。
- 預設減碼 1/3，可設定為 1/3 至 1/2。
- 完成部分減碼後啟動成本停損。
- 剩餘部位可設定使用 10MA 或 20MA，以收盤跌破確認。

## 輸入

`evaluate_position_management()` 接收：

```json
{
  "symbol": "2330",
  "position_status": "open",
  "entry_date": "2026-07-01",
  "entry_price": 100.0,
  "initial_stop": 95.0,
  "trigger_reference": 98.0,
  "completed_event_ids": []
}
```

第二個參數為從進場日起的有效交易日資料：

```json
[
  {"date": "2026-07-01", "close": 100.0, "ma10": 98.0, "ma20": 95.0},
  {"date": "2026-07-02", "close": 104.0, "ma10": 99.0, "ma20": 96.0}
]
```

`days_since_entry` 依不重複的有效交易日計算，進場日為 0；不使用自然日差。

## 狀態與訊號

狀態包含：

```text
not_entered
holding_pre_partial
partial_exit_due
partially_reduced
break_even_active
trailing_active
stopped_out
fully_exited
invalid_data
```

完整出場判斷優先順序：

1. 原始停損收盤確認。
2. 部分減碼後的成本停損收盤確認。
3. 部分減碼後的 10MA／20MA 收盤確認。
4. 部分減碼條件。

`model_comparison_snapshot.official_output_drives_simulation=true`，而
`shadow_output_drives_simulation=false`。頂層欄位永遠複製模型 A 結果。

## 冪等事件

每個模擬事件使用穩定 ID：

```text
symbol:model:event_type:first_signal_date
```

- 正式模型事件第一次出現時放入 `events_to_create` 與 `pending_events`。
- 影子模型只保留 `pending_events` 作比較，`events_to_create` 固定為空。
- 同日或隔日重跑且事件尚未完成時，沿用同一 pending event，`events_to_create=[]`。
- 模擬動作確認後，呼叫端將 event ID 放入 `completed_event_ids`。
- 完成事件不得再次建立。
- 完整出場事件完成後，狀態固定為 `fully_exited`。

狀態機本身不寫外部資料；Google Sheets 排程必須以 event ID 作唯一鍵並在寫入後回讀驗證。

## 驗證

```bash
python scripts/validate_position_management_policy.py
python -m pytest -q tests/test_position_management.py
```
