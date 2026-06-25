# 報告日期：2026/06/25（星期四）

- 執行時間：2026-06-25T10:54:10+08:00
- 交易日判定：True
- 最新市場資料日期：2026-06-24
- 是否足以執行全市場掃描：False
- 整體信心等級：medium

## 資料來源健康狀態

| 來源 | 角色 | 可連線 | HTTP | 資料日期 | 明確日期 | 當期 | 排程可用 | 錯誤 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TWSE | 主資料源 | True | 200 | 2026-06-24 | True | True | True |  |
| TPEx | 主資料源 | True | 200 | 2026-06-24 | True | True | True |  |
| data.gov.tw | 主資料源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| MOPS | 主資料源 | True | 200 | 2026-04-08 | True | False | False | MOPS material information unavailable |
| Goodinfo | 候補資料源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| Yahoo 奇摩股市 | 催化新聞源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| 鉅亨網 Cnyes | 催化新聞源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| MoneyDJ | 催化新聞源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| TradingView | 人工複核源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| WantGoo | 人工複核源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| CMoney | 人工複核源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| 財報狗 StatementDog | 人工複核源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |

## 今日可用主資料源

- TWSE
- TPEx

## 今日候補資料源

- 無

## 催化新聞源

- 無

## 人工複核來源

- 無

## 不建議自動化來源

- 無

## 失敗來源與錯誤

- data.gov.tw：未取得明確資料日期；不可判定為當日資料可用
- MOPS：MOPS material information unavailable
- Goodinfo：未取得明確資料日期；不可判定為當日資料可用
- Yahoo 奇摩股市：未取得明確資料日期；不可判定為當日資料可用
- 鉅亨網 Cnyes：未取得明確資料日期；不可判定為當日資料可用
- MoneyDJ：未取得明確資料日期；不可判定為當日資料可用
- TradingView：未取得明確資料日期；不可判定為當日資料可用
- WantGoo：未取得明確資料日期；不可判定為當日資料可用
- CMoney：未取得明確資料日期；不可判定為當日資料可用
- 財報狗 StatementDog：未取得明確資料日期；不可判定為當日資料可用

## 掃描模組覆蓋狀況

- market_environment：True（TWSE has explicit current market date）
- listed_ohlcv：True（1367 listed rows parsed）
- otc_ohlcv：True（10030 OTC rows parsed）
- volume_ranking：True（Computed from official OHLCV）
- turnover_ranking：True（Computed from official OHLCV）
- price_change_screening：True（Computed from official OHLCV）
- limit_up_screening：True（Estimated from daily change percent）
- volume_spike_screening：True（20-day volume history available）
- institutional_trading：True（14721 institutional rows parsed from official sources）
- margin_short：True（1957 margin/short rows parsed from official sources）
- material_information：False（empty_but_valid）
- revenue_financials：False（First version does not parse revenue or financial statements yet）
- news_topics：True（At least one catalyst news source reachable）
- technical_review：False（TradingView/WantGoo/CMoney are manual review sources, not automated signals）

## 缺少的資料段落

- material_information

## 限制

- 核心資料段落缺失：material_information
