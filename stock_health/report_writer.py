from __future__ import annotations

from datetime import date
from typing import Any

from .trading_calendar import markdown_report_date


def build_health_markdown(report: dict[str, Any], target_date: date) -> str:
    lines = [
        f"# 報告日期：{markdown_report_date(target_date)}",
        "",
        f"- 執行時間：{report['generated_at']}",
        f"- 交易日判定：{report['market_is_trading_day']}",
        f"- 最新市場資料日期：{report['latest_market_data_date'] or '未取得'}",
        f"- 是否足以執行全市場掃描：{report['full_market_scan_ready']}",
        f"- 整體信心等級：{report['overall_confidence']}",
        "",
        "## 資料來源健康狀態",
        "",
        "| 來源 | 角色 | 可連線 | HTTP | 資料日期 | 明確日期 | 當期 | 排程可用 | 錯誤 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for source in report["sources"].values():
        lines.append(
            "| {name} | {role} | {reachable} | {http_status} | {data_date} | {date_explicit} | {is_current} | {schedule_ready} | {error} |".format(
                **{key: _md(source.get(key)) for key in source}
            )
        )
    lines.extend(["", "## 今日可用主資料源", ""])
    lines.extend(_list_or_empty(report["main_sources"]))
    lines.extend(["", "## 今日候補資料源", ""])
    lines.extend(_list_or_empty(report["backup_sources"]))
    lines.extend(["", "## 催化新聞源", ""])
    lines.extend(_list_or_empty(report["catalyst_news_sources"]))
    lines.extend(["", "## 人工複核來源", ""])
    lines.extend(_list_or_empty(report["manual_review_sources"]))
    lines.extend(["", "## 不建議自動化來源", ""])
    lines.extend(_list_or_empty(report["not_recommended_sources"]))
    lines.extend(["", "## 失敗來源與錯誤", ""])
    failures = [f"{source['name']}：{source['error']}" for source in report["sources"].values() if source.get("error")]
    lines.extend(_list_or_empty(failures))
    lines.extend(["", "## 掃描模組覆蓋狀況", ""])
    for key, value in report["coverage"].items():
        lines.append(f"- {key}：{value['available']}（{value['notes']}）")
    lines.extend(["", "## 缺少的資料段落", ""])
    lines.extend(_list_or_empty(report["missing_sections"]))
    lines.extend(["", "## 限制", ""])
    lines.extend(_list_or_empty(report.get("errors", [])))
    lines.append("")
    return "\n".join(lines)


def build_market_scan_markdown(summary: dict[str, Any], target_date: date) -> str:
    lines = [
        f"# 全市場掃描摘要：{markdown_report_date(target_date)}",
        "",
        "本摘要僅供研究與人工複核，不構成買賣建議。",
        "",
        f"- 執行時間：{summary['generated_at']}",
        f"- 是否足以執行全市場掃描：{summary['full_market_scan_ready']}",
        f"- 整體信心等級：{summary['overall_confidence']}",
        f"- 可用歷史交易日：{summary['historical_data_status']['available_trading_days']}",
        "",
        "## 普通股 Universe 過濾摘要",
        "",
    ]
    universe_summary = summary.get("universe_summary", {})
    for key in ("total_rows", "scan_eligible_rows", "excluded_rows"):
        lines.append(f"- {key}：{universe_summary.get(key, 0)}")
    lines.append(f"- excluded_by_type：{universe_summary.get('excluded_by_type', {})}")
    lines.extend(
        [
            "",
            "## 市場概況",
            "",
        ]
    )
    for key, value in summary["market_summary"].items():
        lines.append(f"- {key}：{value}")
    lines.extend(["", "## 成交金額排行", ""])
    lines.extend(_candidate_lines(summary["rankings"]["top_turnover"][:10]))
    lines.extend(["", "## 成交量排行", ""])
    lines.extend(_candidate_lines(summary["rankings"]["top_volume"][:10]))
    lines.extend(["", "## 漲幅排行", ""])
    lines.extend(_candidate_lines(summary["rankings"]["top_gainers"][:10]))
    lines.extend(["", "## 初步篩選", ""])
    for key, values in summary["screening"].items():
        lines.append(f"### {key}")
        lines.extend(_candidate_lines(values[:10]))
        lines.append("")
    lines.extend(["## Qullamaggie-style 動能掃描", ""])
    qullamaggie = summary.get("qullamaggie", {})
    market_regime = qullamaggie.get("market_regime", {})
    lines.append(f"- 市場狀態：{market_regime.get('status', 'insufficient_data')}")
    lines.append(f"- 市場分數：{market_regime.get('score', 0)}")
    lines.append("")
    for setup_type, values in qullamaggie.get("candidates", {}).items():
        lines.append(f"### {setup_type}")
        lines.extend(_candidate_lines(values[:10]))
        lines.append("")
    lines.extend(["### top_candidates", ""])
    lines.extend(_candidate_lines(qullamaggie.get("top_candidates", [])[:10]))
    lines.append("")
    lines.extend(["## 缺少的資料段落", ""])
    lines.extend(_list_or_empty(summary["missing_sections"]))
    lines.extend(["", "## 限制", ""])
    lines.extend(_list_or_empty(summary["limitations"]))
    lines.append("")
    return "\n".join(lines)


def _candidate_lines(values: list[dict[str, Any]]) -> list[str]:
    if not values:
        return ["- 無"]
    return [
        f"- {item['symbol']} {item['name']}（{item['market']}）：close={item['close']} change_pct={item['change_pct']} volume={item['volume']} turnover={item['turnover']}"
        for item in values
    ]


def _list_or_empty(values: list[Any]) -> list[str]:
    if not values:
        return ["- 無"]
    return [f"- {value}" for value in values]


def _md(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|").replace("\n", " ")
