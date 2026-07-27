# Episodic Pivot 獨立評分

本模組只產生 Qullamaggie-style Episodic Pivot 研究欄位，不執行真實交易。EP 使用 `data/chatgpt/episodic-pivot-policy-v1.json`，不沿用一般 Breakout 分數。

## 資料邊界

- OHLCV 只使用日期小於分析日的歷史列與分析日當日列，禁止使用未來資料。
- 有效歷史列必須具有正數且完整的 OHLC、`volume>0`、`high>=low`。
- MOPS payload 的 `requested_date` 與 `data_date` 必須等於分析日；狀態必須是 `success`／`empty_but_valid`，日期驗證必須是 `matched`／`query_confirmed_empty`。只有 `success` 會含事件，但已確認零事件仍代表日期資料完整。
- 催化事件只能來自 MOPS，事件日不得晚於分析日，且必須位於分析日前 3 個自然日至分析日之間。
- 分析日當天 13:30 後發布的公告不會被倒推為當日催化；可在後續交易日落入回看時窗。
- MOPS 只驗證事件存在、日期、來源與公告類別，不推論事件利多或利空。

## 價格與量能

```text
gap_pct = (current_open / prior_close - 1) * 100
open_vs_prior_close_pct = gap_pct
daily_volume_ratio = current_volume / prior_20d_average_volume
prior_3m_extension_pct = prior_close / close_63_trading_days_before - 1
prior_6m_extension_pct = prior_close / close_126_trading_days_before - 1
```

百分比欄位乘以 100。3 個月與 6 個月窗口分別固定為 63、126 個有效交易日，且都以分析日前一個有效收盤為終點。

預設門檻集中在 policy：

```text
minimum_gap_pct = 4
minimum_repricing_pct = 5
minimum_close_location_pct = 60
minimum_daily_volume_ratio = 2
maximum_prior_3m_extension_pct = 80
maximum_prior_6m_extension_pct = 150
terminal_gap = prior_3m_extension_pct >= 50 and gap_pct >= 8
```

重新定價條件為 `gap_pct>=minimum_gap_pct` 或當日 `change_pct>=minimum_repricing_pct`，且 `ep_close_location_pct` 至少為 60。末端跳空、高開低走、3/6 個月過度延伸、量能不足或沒有可驗證催化都會寫入 `ep_rejection_reasons`。

## 獨立分數

`ep_quality_score` 的權重總和為 100：

```text
verified_catalyst 25
repricing 25
abnormal_volume 25
catalyst_timing 15
extension_quality 10
```

`ep_status` 僅使用：

```text
valid_ep
rejected
insufficient_data
```

- 核心 OHLCV、20/63 日歷史或 MOPS 日期驗證不足時，`ep_status=insufficient_data`、`ep_quality_score=null`。
- 63 日是必要的最低延伸窗口；126 日是優先補充窗口。已有 63 日但未滿 126 日時，`prior_6m_extension_pct=null` 並記錄原因，仍可使用 3 個月延伸完成 EP 判斷；未滿 63 日才是核心歷史不足。
- 資料完整但不符合 EP 門檻時，`ep_status=rejected` 並保留實際分數與拒絕原因。
- 無拒絕原因且分數達 policy 門檻時，才是 `valid_ep`。
- `setup_type=episodic_pivot` 僅能由 `ep_status=valid_ep` 產生。
- EP 候選的正式掃描分數來源為 `ep_quality_score`；一般分數僅保存在 `general_qullamaggie_score` 與 `general_score_breakdown` 供稽核。

## 明確缺值

目前沒有可靠盤中開盤區間資料，因此以下欄位固定為 `null`：

```text
volume_first_15m_ratio
volume_first_30m_ratio
opening_range_high
opening_range_low
```

MOPS 不提供可直接量化的事件驚喜、營收年增或 EPS 年增，因此以下欄位也固定為 `null`：

```text
catalyst_surprise_score
revenue_growth_yoy
eps_growth_yoy
catalyst_direction
```

原因記錄於 `ep_missing_reason`。上述可選欄位為 `null` 不會被當成 0 分，也不會自行推測；只有 EP 核心必要資料缺失才會標記 `insufficient_data`。

## 驗證

```bash
python scripts/validate_episodic_pivot_policy.py
python -m pytest -q tests/test_episodic_pivot.py
```
