# 專案協作指示

## 專案目標

本專案用於建立「台股每日資料源健康檢查」自動化系統。

系統會在每日盤後檢查台股相關官方與第三方資料來源，產生結構化 JSON、Markdown 報告與每日歷史紀錄，並由 GitHub Actions 自動執行及提交結果。

---

## 一般工作原則

* 開始任何工作前，先閱讀本檔案、README、既有程式碼與 GitHub Actions workflow。
* 修改前先了解目前專案架構，不得任意覆蓋、刪除或破壞既有功能。
* 優先進行最小且必要的修改，避免無關重構。
* 完成修改後必須執行測試。
* 所有程式碼、設定與文件應保持清楚、可維護及可重現。
* 發現需求、資料來源或執行環境不明確時，不得自行捏造結果。
* 若執行環境無法連線外部網站，應明確記錄限制，不得產生虛假的正常檢查結果。

---

## 日期與時區

* 所有日期與時間一律以 `Asia/Taipei` 為準。
* 不得直接使用執行環境預設的 UTC 日期作為報告日期。
* JSON 中的時間應使用含時區的 ISO 8601 格式，例如：

```text
2026-06-09T18:15:00+08:00
```

* Markdown 報告日期格式必須為：

```text
YYYY/MM/DD（星期X）
```

* 星期名稱使用中文：

```text
星期一、星期二、星期三、星期四、星期五、星期六、星期日
```

---

## 安全與秘密資訊

* 絕對不得將以下內容寫入程式碼、測試、設定檔、README、JSON、Markdown 或 GitHub Actions log：

  * GitHub 密碼
  * Personal Access Token
  * API Key
  * Cookie
  * Session Token
  * 私鑰
  * OAuth 憑證
  * Google 帳號密碼
  * 任何其他秘密或認證資訊
* 不得在程式碼中硬編碼以 `ghp_`、`github_pat_` 或其他 Token 格式開頭的內容。
* GitHub Actions 應優先使用內建的 `GITHUB_TOKEN`。
* GitHub Actions 權限必須採最小權限原則。
* 若未來需要外部 API Key，必須透過 GitHub Actions Secrets 與環境變數傳入。
* 不得將 Secrets 顯示在 log 中。
* 不得使用帳號密碼進行 `git push`。

---

## GitHub Actions 規則

* 使用 GitHub Actions 內建的 `GITHUB_TOKEN`。
* 寫入 repository 時，僅授予：

```yaml
permissions:
  contents: write
```

* workflow 必須支援：

  * 排程執行
  * `workflow_dispatch` 手動執行
* GitHub Actions cron 使用 UTC。
* 台灣時間 18:15 對應 UTC 10:15。
* 排程應避開整點。
* 自動提交作者使用：

```text
github-actions[bot]
```

* 沒有檔案變更時，不得建立空 commit。
* 自動提交僅限以下產出：

  * `latest.json`
  * `latest.md`
  * `history/`
* 測試失敗時不得執行正式資料產生及提交。
* 不得在 workflow 中明文寫入密碼、Token 或其他秘密。

---

## 資料來源優先順序

官方來源優先於第三方來源。

### 官方主資料來源

* TWSE
* TPEx
* data.gov.tw
* MOPS

### 第三方候補或複核來源

* Goodinfo
* Yahoo 奇摩股市
* 鉅亨網 Cnyes
* MoneyDJ
* TradingView
* WantGoo
* CMoney
* 財報狗 StatementDog

不得因第三方網站顯示資料，就忽略官方來源。

---

## 資料用途規則

* 大盤環境：優先使用 TWSE。
* 上市個股 OHLCV：優先使用 TWSE 或 data.gov.tw。
* 上櫃個股 OHLCV：優先使用 TPEx。
* 成交量與成交金額排行：優先由官方 OHLCV 自行計算。
* 漲幅、漲停與爆量初篩：優先由官方 OHLCV 自行計算。
* 法人買賣超：優先使用 TWSE、TPEx。
* 融資融券：優先使用 TWSE、TPEx。
* 重大訊息：以 MOPS 為正式驗證來源。
* 月營收與財報：以 MOPS 為正式驗證來源。
* 鉅亨網、MoneyDJ、Yahoo 新聞只能作為催化新聞來源。
* TradingView、WantGoo、CMoney 主要作為人工技術圖表複核來源。
* Goodinfo 可作候補或複核來源，但不得取代所有官方來源。
* 財報狗主要作為月營收與財報分析輔助來源，不得作為 OHLCV 主資料源。

---

## 網路存取與爬取規則

* 不得繞過登入、驗證碼、Cloudflare、付費牆或其他存取控制。
* 不得嘗試破解、模擬登入或取得非公開資料。
* 不得將 Selenium 或瀏覽器自動化作為主要資料取得方案。
* 對公開 HTTP 資料應設定：

  * 合理的 timeout
  * 明確的 User-Agent
  * 有限次數的重試
  * 適當的退避機制
* 不得無限制重試。
* 不得高頻請求或造成資料來源負擔。
* 發生 403、429、逾時、解析失敗、動態載入或反爬蟲時，必須記錄實際錯誤。
* 單一來源失敗不得中止整個檢查流程。
* 網站首頁可以開啟，不等於當日資料可用。
* 搜尋引擎摘要不得作為資料日期的唯一證據。
* 若沒有實際取得明確資料日期，`is_current` 不得設為 `true`。
* 不得捏造 HTTP status、資料日期、資料筆數、欄位、回應時間或成功狀態。

---

## 資料來源角色

每個來源的 `role` 僅允許使用以下值：

* 主資料源
* 候補資料源
* 催化新聞源
* 人工複核源
* 不建議自動化

不得建立未定義的新角色名稱，除非同步更新 schema、測試與文件。

---

## JSON 輸出規則

`latest.json` 必須：

* 為有效 UTF-8 JSON。
* 中文不得強制轉成 Unicode escape。
* 可由 Python `json.load()` 正常解析。
* 保持穩定欄位與排序，降低不必要的 Git diff。
* 即使資料缺失，也應保留 schema 欄位。
* 缺失值使用：

  * `null`
  * `false`
  * 空字串
  * 空陣列
* 不得刪除既有欄位，除非同步提高 `schema_version`。
* 修改 schema 時，必須同步修改：

  * 測試
  * README
  * Markdown 產生器
  * ChatGPT 排程範例

每個資料來源至少包含：

```text
name
checked_at
reachable
http_status
data_date
is_current
date_explicit
machine_readable
login_required
dynamic_loading_suspected
schedule_ready
role
evidence
error
response_time_ms
```

---

## Markdown 報告規則

`latest.md` 最上方必須顯示：

```text
# 報告日期：YYYY/MM/DD（星期X）
```

報告至少包含：

* 執行時間
* 每個資料來源的健康狀態
* 實際觀察到的資料日期
* 今日可用主資料源
* 今日候補資料源
* 催化新聞源
* 人工複核來源
* 不建議自動化來源
* 失敗來源與錯誤
* 各掃描模組覆蓋狀況
* 是否足以執行全市場掃描
* 缺少的資料段落
* 整體信心等級

不得將未驗證、無法解析或資料日期不明的項目寫成正常。

---

## 全市場掃描判定

只有以下核心資料皆可用時，`full_market_scan_ready` 才能為 `true`：

* `market_environment`
* `listed_ohlcv`
* `otc_ohlcv`
* `institutional_trading`
* `margin_short`
* `material_information`

若任何核心項目缺失：

* `full_market_scan_ready` 必須為 `false`。
* 缺失項目必須寫入 `missing_sections`。
* Markdown 報告必須清楚說明缺少哪一段資料。

不得只因大部分網站可以開啟，就判定足以執行全市場掃描。

---

## 非交易日規則

* 星期六與星期日應標示：

```text
market_is_trading_day=false
```

* 國定假日或特殊休市日若沒有可靠官方交易日曆，不得自行推測。
* 非交易日可接受最新交易日資料，但必須分開記錄：

  * `report_date`
  * `latest_market_data_date`
  * `market_is_trading_day`
* 非交易日不得因資料日期不是今日，就將所有資料來源判定為故障。
* 不確定是否為交易日時，應降低整體信心等級並說明原因。

---

## 歷史檔案規則

每次執行同時產生：

```text
history/YYYY/MM/YYYY-MM-DD.json
history/YYYY/MM/YYYY-MM-DD.md
```

* 同一天重跑可覆寫同一天的檔案。
* 不得刪除過去日期的歷史紀錄。
* 歷史檔案內容須與當次 `latest.json`、`latest.md` 一致。
* 歷史路徑必須依 Asia/Taipei 日期建立。

---

## 程式碼品質

* 使用 Python 型別提示。
* 使用清楚的函式或類別拆分責任。
* 不得將所有邏輯放在單一巨大 `main()` 函式中。
* URL、timeout、重試次數與來源設定應集中管理。
* 官方來源與第三方來源應分開處理。
* 使用 `logging` 記錄執行資訊，不要只使用 `print`。
* 錯誤訊息應保留足夠資訊，但不得洩漏秘密。
* 避免不必要的大型套件與過度複雜設計。
* 優先使用可讀、可測試、可維護的實作。
* 程式成功產出有效報告時，即使部分來源失敗，也可退出 0。
* 只有無法產出有效 `latest.json` 時，才應使用非 0 退出碼。

---

## 測試要求

完成任何程式修改後，至少執行：

```bash
python -m pytest -q
```

涉及正式資料產生時，另執行：

```bash
python stock_source_health_check.py
```

測試至少涵蓋：

* Asia/Taipei 日期
* 中文星期格式
* JSON 必要欄位
* JSON 可正常解析
* 單一來源失敗不會中止全流程
* `full_market_scan_ready` 判定
* `missing_sections` 判定
* 非交易日判定
* Markdown 產生
* 歷史路徑產生
* 不得存在硬編碼 Token 或密碼
* 網路測試使用 mock，不依賴外部網站

不得刪除測試只是為了讓測試通過。

---

## 修改完成前檢查

完成工作前必須確認：

1. 所有測試通過。
2. `latest.json` 可由 `json.load()` 正常解析。
3. Markdown 日期使用 Asia/Taipei。
4. 歷史檔案路徑正確。
5. workflow YAML 結構合理。
6. Git diff 不包含帳號、密碼、Token、Cookie 或私鑰。
7. 未將失敗來源偽裝成正常。
8. README 與實際程式行為一致。
9. 沒有不必要修改。
10. 列出仍未解決的限制。

---

## Git 與 Pull Request

* 不得直接修改 `main` 分支。
* 每項工作應建立獨立 branch。
* Commit 訊息應清楚描述修改內容。
* Pull Request 必須說明：

  * 修改目的
  * 修改檔案
  * 實作方式
  * 測試結果
  * 已知限制
  * 是否涉及 schema 變更
* 不得將產生檔以外的無關檔案提交進 repository。
* 不得提交：

  * `.env`
  * 本機虛擬環境
  * IDE 暫存檔
  * 作業系統暫存檔
  * 認證檔案
  * 測試產生的快取

---

## Codex 執行要求

Codex 執行任務時必須：

1. 先閱讀本 `AGENTS.md`。
2. 閱讀 README、現有程式與 workflow。
3. 先提出簡短計畫。
4. 再進行實作。
5. 執行測試。
6. 檢查 Git diff。
7. 說明外部網路是否可用。
8. 不得捏造實際網路測試結果。
9. 回報修改檔案、測試結果與剩餘限制。
10. 未經明確要求，不得降低安全規則、測試要求或資料驗證標準。
