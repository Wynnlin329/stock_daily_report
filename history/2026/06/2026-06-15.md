# 報告日期：2026/06/15（星期一）

- 執行時間：2026-06-15T15:55:41+08:00
- 交易日判定：True
- 最新市場資料日期：2026-06-15
- 是否足以執行全市場掃描：False
- 整體信心等級：low

## 資料來源健康狀態

| 來源 | 角色 | 可連線 | HTTP | 資料日期 | 明確日期 | 當期 | 排程可用 | 錯誤 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TWSE | 主資料源 | True | 200 |  | False | False | False | TWSE response did not contain a parsable listed OHLCV table |
| TPEx | 主資料源 | True | 200 |  | False | False | False | TPEx response did not contain a parsable OTC OHLCV table |
| data.gov.tw | 主資料源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| MOPS | 主資料源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| Goodinfo | 候補資料源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| Yahoo 奇摩股市 | 催化新聞源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| 鉅亨網 Cnyes | 催化新聞源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| MoneyDJ | 催化新聞源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| TradingView | 人工複核源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| WantGoo | 人工複核源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| CMoney | 人工複核源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |
| 財報狗 StatementDog | 人工複核源 | True | 200 |  | False | False | False | 未取得明確資料日期；不可判定為當日資料可用 |

## 今日可用主資料源

- 無

## 今日候補資料源

- 無

## 催化新聞源

- 無

## 人工複核來源

- 無

## 不建議自動化來源

- 無

## 失敗來源與錯誤

- TWSE：TWSE response did not contain a parsable listed OHLCV table
- TPEx：TPEx response did not contain a parsable OTC OHLCV table
- data.gov.tw：未取得明確資料日期；不可判定為當日資料可用
- MOPS：未取得明確資料日期；不可判定為當日資料可用
- Goodinfo：未取得明確資料日期；不可判定為當日資料可用
- Yahoo 奇摩股市：未取得明確資料日期；不可判定為當日資料可用
- 鉅亨網 Cnyes：未取得明確資料日期；不可判定為當日資料可用
- MoneyDJ：未取得明確資料日期；不可判定為當日資料可用
- TradingView：未取得明確資料日期；不可判定為當日資料可用
- WantGoo：未取得明確資料日期；不可判定為當日資料可用
- CMoney：未取得明確資料日期；不可判定為當日資料可用
- 財報狗 StatementDog：未取得明確資料日期；不可判定為當日資料可用

## 掃描模組覆蓋狀況

- market_environment：False（TWSE current market environment not verified）
- listed_ohlcv：False（Listed OHLCV unavailable）
- otc_ohlcv：False（OTC OHLCV unavailable）
- volume_ranking：False（Requires listed or OTC OHLCV）
- turnover_ranking：False（Requires listed or OTC OHLCV）
- price_change_screening：False（Requires listed or OTC OHLCV）
- limit_up_screening：False（Requires listed or OTC OHLCV）
- volume_spike_screening：False（Requires at least 20 trading days of history）
- institutional_trading：False（First version does not parse institutional trading yet）
- margin_short：False（First version does not parse margin short data yet）
- material_information：False（MOPS material information date not verified）
- revenue_financials：False（First version does not parse revenue or financial statements yet）
- news_topics：True（At least one catalyst news source reachable）
- technical_review：False（TradingView/WantGoo/CMoney are manual review sources, not automated signals）

## 缺少的資料段落

- market_environment
- listed_ohlcv
- otc_ohlcv
- institutional_trading
- margin_short
- material_information

## 限制

- TWSE response did not contain a parsable listed OHLCV table
- TPEx response did not contain a parsable OTC OHLCV table
- 核心資料段落缺失：market_environment, listed_ohlcv, otc_ohlcv, institutional_trading, margin_short, material_information
