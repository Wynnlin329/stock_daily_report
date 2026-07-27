# ORH 影子模擬資料可行性

評估日期：2026-07-27
時區：Asia/Taipei

## 結論

目前資料可靠性閘門不通過，因此不啟用 ORH 計算，也不將 ORH 欄位接入每日
symbol JSON、compact source、Watchlist 或 TradePlan。正式進場模型維持
`breakout_confirmation_close`。

本次只建立停用政策、輸出欄位契約、point-in-time snapshot 契約與 validator。
不得以現有日 K 推測開盤區間、觸發時間或盤中成交價。

## 資料源查核

| 來源 | 1/5/30/60 分 K | OHLCV | 歷史保存 | 公司行動 | 異常交易 | 目前可用 |
| --- | --- | --- | --- | --- | --- | --- |
| TWSE 公開 OpenAPI | 未發現公開分鐘 K 端點 | 不適用 | 未發現公開分鐘 K 保存契約 | 可由其他官方資料補強 | 需另整合 | 否 |
| TWSE 資訊商品 | 可由成交檔自行聚合 | 成交資料可購買 | 依訂購商品 | 需另整合 | 需另整合 | 否 |
| TPEx 資訊服務 | 即時資料需契約或資訊商 | 原始即時資料 | 未驗證公開分鐘 K 保存契約 | 需另整合 | 需另整合 | 否 |
| Fugle MarketData | 文件支援 | 文件支援 | 分 K 固定近 30 日 | 有獨立股務 API | 未驗證完整正規化 | 否 |

Fugle 文件列出 1、5、30、60 分 K 與時間戳、OHLCV，也說明歷史分 K固定回傳
近 30 日且不可指定起訖日。歷史 K 可選擇還原股價，股務 API 另提供除權息、
分割、面額變更與減資資訊；完整股務 API 屬特定付費方案。

本次僅做一次不含憑證的低頻請求：

```text
GET /marketdata/v1.0/stock/intraday/candles/2330?timeframe=5
HTTP 401 Unauthorized
```

這只證明目前環境沒有可用授權，不能證明授權後資料品質。未使用或寫入任何
API key。

## 官方與供應商證據

- TWSE 資訊服務：<https://www.twse.com.tw/zh/products/information/information.html>
- TWSE 歷史交易資料商品：<https://eshop.twse.com.tw/zh/category/main/7>
- TPEx 資訊購買：<https://www.tpex.org.tw/zh-tw/service/data/overview.html>
- Fugle 日內 K：<https://developer.fugle.tw/docs/data/http-api/intraday/candles/>
- Fugle 歷史 K：<https://developer.fugle.tw/docs/data/http-api/historical/candles/>
- Fugle 方案：<https://developer.fugle.tw/docs/pricing/>
- Fugle 除權息：<https://developer.fugle.tw/docs/data/http-api/corporate-actions/dividends/>
- Fugle 資本變動：<https://developer.fugle.tw/docs/data/http-api/corporate-actions/capital-changes/>

## 啟用前必要條件

1. 以 GitHub Actions Secret 設定供應商憑證，不得寫入 repository 或 log。
2. 至少連續五個交易日驗證 TWSE 與 TPEx 普通股的 1/5/30/60 分 K。
3. 驗證每根 K 的時區、OHLC、成交量單位、缺 K、重複 K 與收盤邊界。
4. 建立 append-only 原始快照，保存事件時間、接收時間、擷取時間、查詢參數及
   payload hash。
5. 驗證除權息、分割、減資、停止／恢復交易、處置、分盤、延後開盤及暫緩撮合。
6. 以 replay test 證明訊號只能看見觸發時已收到的資料。

## ORH 介面契約

預定欄位如下；在 gate 通過前不會出現在每日 runtime artifact，介面模板一律為
`null`：

```text
orh_1m, orh_5m, orh_30m, orh_60m,
orh_triggered_at, orh_entry_price, orh_initial_stop,
orh_slippage_pct, confirmation_close_entry,
orh_model_r, close_confirmation_model_r
```

未來啟用後，ORH 仍只作影子模擬，不得寫入正式 TradePlan、SimEntry、SimExit
或 TradeLog，也不得觸發真實交易。正式模型的 entry price 仍是突破日收盤確認價。
