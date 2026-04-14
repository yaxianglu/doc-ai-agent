"""对比识别与统计工具：抽取地区并生成可比较指标。"""

from __future__ import annotations

import re

from .request_understanding import CITY_ALIASES as REQUEST_CITY_ALIASES, RequestUnderstanding


def extract_all_regions(text: str) -> list[str]:
    """从问题中抽取全部出现的标准地区名，并保持出现顺序。"""
    normalized = RequestUnderstanding._normalize_city_mentions(text)
    hits: list[tuple[int, str]] = []
    for canonical in REQUEST_CITY_ALIASES.values():
        for match in re.finditer(re.escape(canonical), normalized):
            hits.append((match.start(), canonical))
    hits.sort(key=lambda item: item[0])
    regions: list[str] = []
    for _, region in hits:
        if region not in regions:
            regions.append(region)
    return regions


def detect_compare_request(
    question: str,
    understanding: dict | None,
    plan: dict | None,
    previous_context: dict | None,
    derive_domain,
) -> dict | None:
    """识别用户是否在提出双地区对比需求。"""
    text = str(question or "").strip()
    if not text:
        return None
    understanding = dict(understanding or {})
    plan = dict(plan or {})
    previous_context = dict(previous_context or {})
    compare_signal = any(token in text for token in ["对比", "比较", "相比", "哪个更突出", "哪个问题更突出"])
    if not compare_signal:
        return None

    regions = extract_all_regions(text)
    domain = understanding.get("domain") or derive_domain(text, plan, previous_context)
    task_type = str(understanding.get("task_type") or "")
    prefers_trend = task_type == "trend" or any(token in text for token in ["趋势", "走势", "走向", "变化", "波动"])
    prefers_detail = task_type == "data_detail"

    if len(regions) >= 2 and domain in {"pest", "soil"}:
        if prefers_detail:
            base_query_type = f"{domain}_detail"
        elif prefers_trend:
            base_query_type = f"{domain}_trend"
        else:
            base_query_type = f"{domain}_overview"
        return {
            "kind": "region_compare",
            "query_type": f"{domain}_compare",
            "base_query_type": base_query_type,
            "domain": domain,
            "regions": regions[:2],
        }

    cross_domain_signal = (
        len(regions) >= 1
        and any(token in text for token in ["虫情", "虫害"])
        and any(token in text for token in ["墒情", "缺水", "干旱"])
    )
    if cross_domain_signal:
        return {
            "kind": "cross_domain_compare",
            "query_type": "cross_domain_compare",
            "base_query_type": "trend" if prefers_trend else ("detail" if prefers_detail else "overview"),
            "region": regions[-1],
        }
    return None


def comparison_metric_key(domain: str) -> str:
    """返回对比分析中应使用的主指标字段名。"""
    return "severity_score" if domain == "pest" else "avg_anomaly_score"


def comparison_domain_label(domain: str) -> str:
    """把内部领域枚举转换成中文展示名称。"""
    return "虫情" if domain == "pest" else "墒情"


def comparison_trend(series: list[dict], key: str) -> str:
    """根据序列首尾变化给出粗粒度趋势结论。"""
    if len(series) < 2:
        return "样本不足"
    first = float(series[0].get(key) or 0)
    last = float(series[-1].get(key) or 0)
    if last > first * 1.15:
        return "整体上升"
    if last < first * 0.85:
        return "整体下降"
    return "整体平稳"


def comparison_average(series: list[dict], key: str) -> float:
    """计算某地区在时间窗内的均值表现。"""
    if not series:
        return 0.0
    return sum(float(item.get(key) or 0) for item in series) / len(series)


def comparison_peak(series: list[dict], key: str) -> float:
    """计算某地区在时间窗内的峰值。"""
    if not series:
        return 0.0
    return max(float(item.get(key) or 0) for item in series)


def comparison_latest(series: list[dict], key: str) -> float:
    """读取序列最新一天的指标值。"""
    if not series:
        return 0.0
    return float(series[-1].get(key) or 0)


def window_summary(window: dict | None) -> str:
    """把结构化时间窗转换成中文摘要。"""
    payload = dict(window or {})
    window_type = str(payload.get("window_type") or "")
    window_value = payload.get("window_value")
    if window_type == "months" and window_value:
        return f"过去{window_value}个月"
    if window_type == "weeks" and window_value:
        return f"过去{window_value}周"
    if window_type == "days" and window_value:
        return f"过去{window_value}天"
    return "当前时间窗"


def comparison_summary(domain: str, region_name: str, series: list[dict]) -> dict:
    """提取地区序列的对比摘要指标（均值、峰值、趋势等）。"""
    key = comparison_metric_key(domain)
    return {
        "region_name": region_name,
        "domain": domain,
        "trend": comparison_trend(series, key),
        "average": comparison_average(series, key),
        "peak": comparison_peak(series, key),
        "latest": comparison_latest(series, key),
        "sample_days": len(series),
    }


def comparison_conclusion(left: dict, right: dict, left_label: str, right_label: str) -> str:
    """根据两个摘要指标生成自然语言对比结论。"""
    left_score = (float(left.get("average") or 0), float(left.get("peak") or 0), float(left.get("latest") or 0))
    right_score = (float(right.get("average") or 0), float(right.get("peak") or 0), float(right.get("latest") or 0))
    if left_score == right_score:
        return f"综合看，{left_label}和{right_label}接近，没有明显一边更突出。"
    winner = left_label if left_score > right_score else right_label
    return f"综合看，{winner}更突出。"
