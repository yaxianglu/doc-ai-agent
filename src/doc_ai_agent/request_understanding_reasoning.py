from __future__ import annotations

import re

from .agri_semantics import has_detail_intent, has_overview_intent, has_ranking_intent, has_trend_intent
from .request_context_resolution import contains_pest, contains_soil


def extract_all_regions(text: str, city_aliases: dict[str, str], normalize_city_mentions) -> list[str]:
    normalized = normalize_city_mentions(text, city_aliases)
    city_positions: list[tuple[int, str]] = []
    for canonical in city_aliases.values():
        for match in re.finditer(re.escape(canonical), normalized):
            city_positions.append((match.start(), canonical))
    city_positions.sort(key=lambda item: item[0])
    regions: list[str] = []
    for _, canonical in city_positions:
        if canonical not in regions:
            regions.append(canonical)
    return regions


def has_negated_trend(text: str) -> bool:
    return any(token in text for token in ["不是趋势", "别看趋势", "不要趋势", "不看趋势"])


def infer_task_type(text: str, domain: str, region_name: str, needs_explanation: bool, needs_advice: bool, compare_hints: list[str], city_aliases: dict[str, str], normalize_city_mentions) -> str:
    if any(token in text for token in compare_hints):
        if domain == "mixed" or (contains_pest(text) and contains_soil(text)):
            return "cross_domain_compare"
        if len(extract_all_regions(text, city_aliases, normalize_city_mentions)) >= 2:
            return "compare"
    if needs_explanation or needs_advice:
        if has_trend_intent(text) and not has_negated_trend(text):
            return "trend"
        if has_ranking_intent(text):
            return "ranking"
        if domain == "mixed" and any(token in text for token in ["同时", "而且", "共同", "叠加"]):
            return "joint_risk"
        if has_detail_intent(text) and domain in {"pest", "soil"} and region_name:
            return "data_detail"
        if region_name and domain in {"pest", "soil"}:
            return "region_overview"
        return "unknown"
    if domain == "mixed" or (
        ("虫情" in text or "虫害" in text)
        and any(token in text for token in ["墒情", "缺水", "低墒", "干旱"])
        and any(token in text for token in ["同时", "而且", "共同", "叠加"])
    ):
        return "joint_risk"
    if has_detail_intent(text) and domain in {"pest", "soil"} and region_name:
        return "data_detail"
    if has_trend_intent(text) and not has_negated_trend(text):
        return "trend"
    if has_ranking_intent(text):
        return "ranking"
    if region_name and domain in {"pest", "soil"} and has_overview_intent(text):
        return "region_overview"
    if region_name and domain in {"pest", "soil"} and "数据" in text:
        return "data_detail"
    if region_name and domain in {"pest", "soil"} and not has_trend_intent(text) and not has_ranking_intent(text):
        return "region_overview"
    if domain and re.search(r"(哪些地区|哪些地方|哪个地区|哪个地方|哪里|哪儿)", text):
        return "ranking"
    return "unknown"


def needs_historical_data(text: str, historical_window: dict, future_window: dict | None, domain: str, task_type: str, region_name: str) -> bool:
    if future_window and historical_window.get("window_type") == "all":
        if not any(token in text for token in ["过去", "最近", "近", "历史", "此前", "之前"]):
            return False
    if (
        historical_window.get("window_type") == "all"
        and domain in {"pest", "soil"}
        and any(token in text for token in ["为什么", "为啥", "原因", "依据", "建议", "处置", "咋办"])
        and not any(token in text for token in ["过去", "最近", "近", "历史", "此前", "之前"])
        and not has_ranking_intent(text)
        and not has_trend_intent(text)
    ):
        return False
    if task_type in {"ranking", "trend", "region_overview", "joint_risk", "data_detail"} and domain:
        return True
    if historical_window.get("window_type") != "all":
        return True
    if (has_ranking_intent(text) or has_trend_intent(text) or any(token in text for token in ["历史", "过去", "近"])) and domain:
        return True
    if domain and re.search(r"(哪些地区|哪些地方|哪个地区|哪个地方|哪里|哪儿)", text):
        return True
    if region_name and domain in {"pest", "soil"} and not any(token in text for token in ["为什么", "为啥", "原因", "依据", "建议", "处置", "咋办"]):
        return True
    return False


def window_prefix(window: dict) -> str:
    if window.get("window_type") == "months":
        return f"过去{window['window_value']}个月"
    if window.get("window_type") == "weeks":
        return f"过去{window['window_value']}个星期"
    if window.get("window_type") == "days":
        return f"过去{window['window_value']}天"
    return "历史上"


def build_historical_query_text(domain: str, historical_window: dict, cleaned: str, task_type: str, region_name: str, region_level: str) -> str:
    if not domain:
        return cleaned
    if task_type in {"trend", "region_overview", "joint_risk", "compare", "cross_domain_compare"}:
        return cleaned
    if task_type == "ranking" and region_level == "county":
        return cleaned
    prefix = window_prefix(historical_window)
    if domain == "pest" and task_type == "ranking":
        return f"{prefix}虫情最严重的地方是哪里"
    if domain == "soil" and task_type == "ranking":
        return f"{prefix}墒情最严重的地方是哪里"
    if region_name and task_type == "region_overview":
        return cleaned
    return cleaned


def future_window_phrase(future_window: dict) -> str:
    window_type = str(future_window.get("window_type") or "")
    window_value = future_window.get("window_value")
    if window_type == "weeks" and window_value == 2:
        return "未来两周"
    if window_type == "months":
        return f"未来{window_value}个月"
    if window_type == "weeks" and window_value not in {None, ""}:
        return f"未来{window_value}周"
    if window_type == "days" and window_value not in {None, ""}:
        return f"未来{window_value}天"
    horizon_days = future_window.get("horizon_days")
    if horizon_days not in {None, ""}:
        return f"未来{horizon_days}天"
    return "未来一段时间"


def build_normalized_question(
    *,
    domain: str,
    historical_window: dict,
    future_window: dict | None,
    cleaned: str,
    needs_explanation: bool,
    needs_advice: bool,
    task_type: str,
    region_name: str,
    region_level: str,
) -> str:
    parts: list[str] = []
    if needs_historical_data(cleaned, historical_window, future_window, domain, task_type, region_name):
        parts.append(build_historical_query_text(domain, historical_window, cleaned, task_type, region_name, region_level))
    elif cleaned:
        parts.append(cleaned)
    if future_window:
        parts.append(future_window_phrase(future_window))
    if needs_explanation:
        parts.append("原因")
    if needs_advice:
        parts.append("处置建议")
    normalized = " ".join(part for part in parts if part)
    return re.sub(r"\s+", " ", normalized).strip()
