# Qullamaggie-style High Tight Flag 結構欄位

本模組產生可稽核研究欄位並供 v2 影子評分使用；不取代正式 v1 grading policy，也不構成交易建議。

## 有效資料與時間邊界

- 只使用日期小於或等於候選 `market_data_date` 的資料，禁止使用未來資料。
- 有效交易日必須具備正數且完整的 OHLC、`high>=low`、`volume>0`。
- 停牌、零成交量與 OHLC 缺值列不進入任何窗口。
- 若某歷史列相對前一日與後一日收盤皆偏離超過 40%，且前後兩日彼此偏離不超過 40%，視為孤立價格異常列並排除。排除日期記錄於 `htf_data_quality.excluded_isolated_price_outlier_dates`；不會修改原始 OHLCV。
- 歷史不足時數值輸出 `null`，原因寫入 `htf_missing_reason`。

## 旗桿與整理期

- 在今日以前最近 40 個有效交易日內尋找最高 `high`，該日為旗桿高點。
- `flag_duration_days` 是旗桿高點日至今日的有效交易日數。
- 合理整理期集中設定為 10 至 40 日：`HTF_FLAG_MIN_DAYS`、`HTF_FLAG_MAX_DAYS`。
- `flag_depth_pct=(旗桿高點-整理期最低 low)/旗桿高點*100`。
- `higher_lows_count` 是整理期相鄰兩日中，後一日 low 高於前一日 low 的次數。

## 前段漲幅與高位位置

- `prior_move_pct_20d`：旗桿高點相對截至旗桿日最近 20 個有效交易日最低 low 的漲幅。
- `prior_move_pct_60d`：相同公式，窗口為 60 日。
- 明顯前段漲幅門檻為 20 日或 60 日任一值至少 50%。
- `distance_to_52w_high_pct=(current_close/最近252日最高high-1)*100`；高點下方為負值。
- `high_52w`：最近 252 個有效交易日的最高價；不足時為 `null`。
- 距 52 週高點超過 15% 不取得 high proximity 分數。

## 收斂、量縮與均線

- `range_contraction_ratio`：整理期最近 5 日平均 `(high-low)/close*100`，除以整理期最初 5 日平均值。
- `volume_contraction_ratio`：整理期最近 5 日均量，除以旗桿日前 20 日均量。
- 兩個 ratio 的合格門檻均為 `<=0.80`。
- `ma10_slope`／`ma20_slope`：目前均線相對 5 個有效交易日前同週期均線的百分比變化。
- `distance_to_ma10_pct`／`distance_to_ma20_pct`：`current_close/MA-1` 的百分比。

## 多時間框架

- `monthly_close`：每個曆月最後一個有效交易日收盤所形成序列的最新值。
- `monthly_ma12`：最近 12 個有效月收盤的簡單平均。
- `monthly_above_ma12`：至少 12 個有效月份後，判斷最新月收盤是否高於 MA12。
  不足時保持 `null`，reason code 為 `insufficient_monthly_closes:requires_12`。
- `ma50_slope`：50 日均線相對固定 lookback 的百分比斜率。
- `long_term_ma_state`：依收盤相對 MA50 與 `ma50_slope` 分為
  `rising`、`neutral`、`falling`；僅供結構稽核，不改動正式 v1。
- `weekly_trend_state`：以每個 ISO week 最後一個有效收盤建立週線。
- `uptrend`：週收盤高於 MA10、MA10 高於 MA20，且 MA10 高於四週前的 MA10。
- `downtrend`：上述條件反向；其他為 `neutral`；不足 20 週為 `null`。
- `daily_trigger_state` 使用 `failed_breakout`、`extended`、`breakout_confirmed`、`near_trigger`、`inside_flag`。

## 綜合狀態

狀態優先順序：

1. 核心歷史或月／週／日狀態不足：`insufficient_data`
2. 盤中突破但收盤跌回旗桿高點下：`failed_breakout`
3. 高於旗桿高點 8% 以上，或距 MA10 超過 10%：`extended`
4. 整理深度超過 25%：`too_deep`
5. 整理期不足 10 日或前段漲幅不足：`developing`
6. 整理過久、波動未縮、量未縮或 higher lows 比率不足：`too_loose`
7. 無上述拒絕且 `htf_structure_score>=75`：`valid_htf`
8. 其餘：`developing`

分數權重集中在 `HTF_STRUCTURE_SCORE_WEIGHTS`：

```text
prior_move 25, flag_depth 15, higher_lows 10,
range_contraction 10, volume_contraction 10,
ma_support 10, high_proximity 10, higher_timeframes 10
```

所有門檻、權重與期間常數均集中於 `stock_health/config.py`。
