# ChatGPT Daily Qullamaggie Source: 2026-08-20

本資料包僅供 ChatGPT 排程研究與人工複核，不構成交易建議。

## 資料日期與 Freshness
- data_freshness: {'report_date': '2026-08-20', 'as_of_date': '2026-08-19', 'market_data_date': '2026-08-19', 'expected_market_data_date': '2026-08-19', 'latest_market_data_date': '2026-08-19', 'is_latest_trading_data_current': True, 'reason': 'Latest trading data is current'}

## Scan Readiness
- scan_readiness: {'can_run_technical_scan': False, 'can_run_qullamaggie_scan': False, 'can_generate_new_paper_trade_candidate': False, 'can_use_institutional_confirmation': True, 'can_use_margin_short_risk': True, 'can_use_mops_catalyst': True, 'reasons': ['listed_ohlcv unavailable', 'market_environment unavailable']}

## Qullamaggie Market Regime
- market_regime: {'status': 'neutral', 'score': 8, 'reasons': ['benchmark regime=neutral'], 'risk_notes': [], 'metrics': {'listed': {'close': 44719.35, 'ma20': 44026.5565, 'ma50': 44801.3384, 'return_20d_pct': 1.0998}, 'otc': {'close': 384.79, 'ma20': 378.7965, 'ma50': 404.3758, 'return_20d_pct': 0.7409}}}

## Setup Counts
- setup_counts: {'breakout': 0, 'episodic_pivot': 5, 'anticipation': 1, 'extended_watch': 11, 'failed_breakout': 3, 'insufficient_data': 50}

## Top Candidates
- 3490 單井 setup=episodic_pivot score=100
- 4430 耀億 setup=episodic_pivot score=100
- 4747 強生 setup=episodic_pivot score=100
- 8937 合騏* setup=episodic_pivot score=100
- 3508 位速 setup=episodic_pivot score=100
- 6547 高端疫苗 setup=anticipation score=53
- 7792 安葆 setup=extended_watch score=68
- 5703 亞都 setup=extended_watch score=68
- 3498 陽程 setup=extended_watch score=63
- 4416 三圓 setup=extended_watch score=58
- 6597 立誠 setup=extended_watch score=58
- 6218 豪勉 setup=extended_watch score=53
- 2641 正德 setup=extended_watch score=53
- 4304 勝昱 setup=extended_watch score=53
- 6859 伯特光 setup=extended_watch score=48
- 1780 立弘 setup=extended_watch score=48
- 7842 天能綠電 setup=extended_watch score=38

## Paper Trading Decision Gate
- gate: {'can_create_new_simulated_buy_candidate': False, 'reason': ['listed_ohlcv unavailable', 'market_environment unavailable', '上市 OHLCV 不完整'], 'allowed_actions': ['可產生資料狀態報告', '可產生候選股研究清單', '可做 MOPS 事件人工複核'], 'blocked_actions': ['不得產生新的模擬候選', '不得新增、移除或取消 Watchlist / Pending / 候選項目', '不得建立新的 TradePlan']}

## Disabled Sections
- 不得產生新的模擬候選
- 不得新增、移除或取消 Watchlist / Pending / 候選項目
- 不得建立新的 TradePlan

## Source URLs
- latest_json: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/latest.json
- screening_summary: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/latest-screening-summary.json
- institutional_summary: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/latest-institutional-trading-summary.json
- margin_short_summary: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/latest-margin-short-summary.json
- mops_events: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/latest-mops-events.json
- index_summary: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/latest-index-summary.json
- history_index: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/history-index.json
- market_scan: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/reports/latest-market-scan.md
- chatgpt_daily_qullamaggie_source: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/daily-qullamaggie-source.json
- chatgpt_daily_qullamaggie_compact: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/daily-qullamaggie-source-compact.json
- chatgpt_weekly_qullamaggie_source: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/weekly-qullamaggie-source.json
- chatgpt_weekly_qullamaggie_compact: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/weekly-qullamaggie-source-compact.json
- chatgpt_symbol_index: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/symbol-index.json
- chatgpt_symbol_index_compact: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/symbol-index-compact.json
- chatgpt_schedule_readiness: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/schedule-readiness.json
- grading_policy_v1: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/qullamaggie-grading-policy-v1.json
- grading_policy_v2_shadow: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/qullamaggie-grading-policy-v2.json
- grading_v2_shadow_latest: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/grading-shadow-v2-latest.json
- grading_v2_shadow_history_index: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/grading-shadow-v2/history-index.json
- position_management_policy: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/position-management-policy-v1.json
- episodic_pivot_policy: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/chatgpt/episodic-pivot-policy-v1.json
- screening_history_index: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/data/screening/history-index.json
- chatgpt_daily_qullamaggie_markdown: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/reports/chatgpt-daily-qullamaggie-source.md
- chatgpt_weekly_qullamaggie_markdown: https://raw.githubusercontent.com/Wynnlin329/stock_daily_report/codex/stock-health-v1/reports/chatgpt-weekly-qullamaggie-source.md
