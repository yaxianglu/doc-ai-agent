from __future__ import annotations

import re

from .agri_semantics import (
    has_detail_intent,
    has_overview_intent,
    has_ranking_intent,
    has_trend_intent,
    needs_advice,
    needs_explanation,
    needs_forecast,
)
from .query_plan import build_query_plan, execution_route
from .task_decomposition import build_task_graph


def score_data(question: str) -> float:
    q = question.lower()
    score = 0.0
    for token, weight in [
        ("数据", 0.25),
        ("多少", 0.35),
        ("top", 0.3),
        ("统计", 0.3),
        ("哪几个", 0.25),
        ("哪个", 0.2),
        ("哪些", 0.2),
        ("平均", 0.3),
        ("分组", 0.2),
        ("连续两天", 0.35),
        ("设备", 0.2),
        ("最多", 0.2),
        ("区县", 0.2),
        ("最高", 0.2),
        ("记录", 0.2),
        ("告警值", 0.2),
        ("超过", 0.2),
        ("最近一次", 0.3),
        ("sms_content", 0.3),
        ("为空", 0.2),
        ("占比", 0.25),
        ("变化", 0.25),
        ("以来", 0.2),
        ("预警", 0.2),
        ("预警信息", 0.15),
        ("严重", 0.25),
        ("异常", 0.25),
        ("走势", 0.25),
        ("走向", 0.25),
        ("波动", 0.25),
        ("趋势", 0.25),
        ("过去", 0.15),
        ("最近", 0.15),
        ("虫情", 0.3),
        ("虫害", 0.3),
        ("墒情", 0.3),
        ("同时", 0.15),
    ]:
        if token in q:
            score += weight

    if re.search(r"20\d{2}年\d{1,2}月\d{1,2}日", question):
        score += 0.25
    if re.search(r"20\d{2}年以?来", question):
        score += 0.2
    if re.search(r"SNS\d+", question):
        score += 0.25
    if re.search(r"[\u4e00-\u9fa5]{2,12}市", question):
        score += 0.15
    return min(score, 1.0)


def score_advice(question: str) -> float:
    q = question.lower()
    score = 0.0
    for token, weight in [
        ("建议", 0.35),
        ("怎么办", 0.35),
        ("如何", 0.25),
        ("怎么", 0.25),
        ("注意", 0.2),
        ("需要", 0.15),
        ("处置", 0.25),
        ("措施", 0.3),
        ("清单", 0.25),
        ("排查", 0.2),
        ("判断依据", 0.25),
        ("短信版本", 0.35),
        ("短信", 0.2),
        ("改写", 0.3),
        ("台风", 0.2),
        ("给我", 0.1),
        ("24小时", 0.2),
        ("农户", 0.15),
    ]:
        if token in q:
            score += weight
    return min(score, 1.0)


def infer_query_type(
    question: str,
    *,
    extract_city,
    extract_county,
    extract_future_window,
    extract_relative_window,
    extract_day_range,
    has_negated_trend,
    extract_device_code,
) -> str:
    if ("同时" in question or "共同" in question) and (("高虫情" in question or "虫情" in question) and ("低墒情" in question or "墒情" in question)):
        return "joint_risk"
    has_region = extract_city(question) is not None or extract_county(question) is not None
    future_window = extract_future_window(question)
    _, _, historical_window = extract_relative_window(question)
    has_explicit_historical_window = historical_window.get("window_type") != "none" or extract_day_range(question)[0] is not None
    if future_window and not has_explicit_historical_window and ("虫情" in question or "虫害" in question):
        return "pest_forecast"
    if future_window and not has_explicit_historical_window and "墒情" in question:
        return "soil_forecast"
    if has_region and has_detail_intent(question) and ("虫情" in question or "虫害" in question):
        return "pest_detail"
    if has_region and has_detail_intent(question) and "墒情" in question:
        return "soil_detail"
    if has_trend_intent(question) and not has_negated_trend(question) and ("虫情" in question or "虫害" in question):
        return "pest_trend"
    if has_trend_intent(question) and not has_negated_trend(question) and "墒情" in question:
        return "soil_trend"
    asks_overview = has_overview_intent(question) or "数据" in question
    if has_region and asks_overview and ("虫情" in question or "虫害" in question):
        return "pest_overview"
    if has_region and asks_overview and "墒情" in question:
        return "soil_overview"
    if (has_ranking_intent(question) or "严重" in question) and ("虫情" in question or "虫害" in question):
        return "pest_top"
    if ("异常最多" in question or "异常" in question or has_ranking_intent(question) or "严重" in question) and "墒情" in question:
        return "soil_top"
    if "最近一次" in question and extract_device_code(question):
        return "latest_device"
    if "处置建议" in question and ("镇" in question or "街道" in question):
        return "region_disposal"
    if "sms_content" in question and "为空" in question:
        return "sms_empty"
    if "占比" in question and "子类型" in question:
        return "subtype_ratio"
    if "变化了多少" in question and "到" in question and "市" in question:
        return "city_day_change"
    if "最高" in question and "告警值" in question:
        return "highest_values"
    if "超过" in question and "告警值" in question:
        return "threshold_summary"
    if "连续两天" in question and "设备" in question:
        return "consecutive_devices"
    if ("平均" in question and "告警值" in question) or ("按告警等级分组" in question and "平均" in question):
        return "avg_by_level"
    if "top" in question.lower() or "Top" in question or "前5" in question or "前十" in question or re.search(r"前\s*\d+", question) or "最多" in question:
        return "top"
    if "虫情" in question or "墒情" in question or "虫害" in question:
        return "structured_agri"
    return "count"


def normalize_router_route(question: str, route: dict, *, infer_query_type_fn, is_agri_query_type, deterministic_query_types: set[str]) -> dict:
    normalized = dict(route)
    router_query_type = str(normalized.get("query_type") or "count")
    heuristic_query_type = infer_query_type_fn(question)

    if heuristic_query_type in deterministic_query_types:
        normalized["query_type"] = heuristic_query_type
        normalized["intent"] = "data_query"
    elif is_agri_query_type(heuristic_query_type) and not is_agri_query_type(router_query_type):
        normalized["query_type"] = heuristic_query_type

    return normalized


def merge_router_route(question: str, route: dict, *, build_route) -> dict:
    base = build_route(question, route.get("query_type", "count"))
    merged = dict(base)

    for key, value in route.items():
        if key in {"city", "county", "device_code", "until"} and value in {None, ""}:
            continue
        if key in {"city", "county", "device_code"} and base.get(key) not in {None, ""}:
            continue
        if key == "region_level" and base.get("region_level") == "county" and value == "city":
            continue
        if key in {"since", "until"} and base["window"]["window_type"] != "all":
            continue
        if key == "since":
            if value in {None, ""}:
                continue
            if value == "1970-01-01 00:00:00" and base["window"]["window_type"] != "all":
                continue
        merged[key] = value

    return merged


def is_low_signal(question: str, *, is_greeting_question) -> bool:
    q = (question or "").strip()
    if not q:
        return True
    if is_greeting_question(q):
        return False
    if re.fullmatch(r"[\d\W_]+", q):
        return True
    if re.fullmatch(r"(哈|呵|啊|嗯|哦|呀){3,}", q):
        return True
    if len(q) <= 4 and not re.search(r"(预警|设备|处置|建议|统计|多少|怎么|如何|虫情|墒情)", q):
        return True
    return False


def needs_agri_domain_clarification(question: str, *, build_route) -> bool:
    has_agri_domain = re.search(r"(虫情|虫害|墒情)", question) is not None
    asks_severity = re.search(r"(受灾|灾情|最严重|最重)", question) is not None
    asks_region = re.search(r"(地方|地区|哪里|哪儿)", question) is not None
    asks_generic_agri = re.search(r"(受灾|灾情|灾害)", question) is not None
    asks_dataset_or_overview = re.search(r"(数据|情况|概况|整体|总体|态势|走势|趋势)", question) is not None
    route = build_route(question, "structured_agri")
    window = dict(route.get("window") or {})
    has_scope = route.get("city") is not None or route.get("county") is not None or window.get("window_type") not in {"none", "all"}
    return not has_agri_domain and (
        (asks_severity and asks_region) or (asks_generic_agri and asks_dataset_or_overview and has_scope)
    )


def domain_from_query_type(query_type: str) -> str | None:
    if query_type.startswith("pest"):
        return "pest"
    if query_type.startswith("soil"):
        return "soil"
    return None


def answer_mode_for_plan(intent: str, route: dict, needs_clarification: bool) -> str:
    if needs_clarification:
        return "clarify"
    if intent == "advice":
        return "advice"
    query_type = str(route.get("query_type") or "")
    if query_type.endswith("_compare") or query_type == "cross_domain_compare":
        return "compare"
    if query_type.endswith("_detail"):
        return "detail"
    if query_type.endswith("_overview"):
        return "overview"
    if query_type.endswith("_trend"):
        return "trend"
    if query_type.endswith("_forecast"):
        return "forecast"
    if query_type.endswith("_top"):
        return "ranking"
    if query_type == "joint_risk":
        return "joint_risk"
    return "data_query"


def typed_metadata(
    question: str,
    route: dict,
    intent: str,
    needs_clarification: bool,
    context: dict | None,
    understanding: dict | None,
    *,
    is_greeting_question,
    domain_from_query_type_fn,
    infer_domain_from_text,
    is_scope_correction_follow_up,
) -> dict:
    understanding = dict(understanding or {})
    context = dict(context or {})
    if is_greeting_question(question):
        return {
            "domain": "",
            "region_name": "",
            "historical_window": {"window_type": "all", "window_value": None},
            "future_window": None,
            "answer_mode": answer_mode_for_plan(intent, route, needs_clarification),
        }
    domain = str(
        understanding.get("domain")
        or domain_from_query_type_fn(str(route.get("query_type") or ""))
        or infer_domain_from_text(question, context=context)
        or ""
    )
    region_name = (
        str(understanding.get("region_name") or "")
        or str(route.get("county") or "")
        or str(route.get("city") or "")
        or (
            str(context.get("region_name") or "")
            if len((question or "").strip()) <= 12 and not is_scope_correction_follow_up(question)
            else ""
        )
    )
    historical_window = understanding.get("window") or route.get("window") or {"window_type": "all", "window_value": None}
    future_window = understanding.get("future_window") or route.get("forecast_window")
    return {
        "domain": domain,
        "region_name": region_name,
        "historical_window": historical_window,
        "future_window": future_window,
        "answer_mode": answer_mode_for_plan(intent, route, needs_clarification),
    }


def finalize_plan(
    plan: dict,
    question: str,
    *,
    context: dict | None = None,
    understanding: dict | None = None,
    is_greeting_question,
    domain_from_query_type_fn,
    infer_domain_from_text,
    is_scope_correction_follow_up,
) -> dict:
    route = dict(plan.get("route") or {})
    finalized = dict(plan)
    finalized.update(
        typed_metadata(
            question,
            route,
            str(plan.get("intent") or "advice"),
            bool(plan.get("needs_clarification")),
            context,
            understanding,
            is_greeting_question=is_greeting_question,
            domain_from_query_type_fn=domain_from_query_type_fn,
            infer_domain_from_text=infer_domain_from_text,
            is_scope_correction_follow_up=is_scope_correction_follow_up,
        )
    )
    task_type = str((understanding or {}).get("task_type") or "")
    if task_type in {"compare", "cross_domain_compare"}:
        finalized["answer_mode"] = "compare"
    understanding_payload = dict(understanding or {})
    inferred_needs_explanation = bool(understanding_payload.get("needs_explanation")) or needs_explanation(question)
    inferred_needs_advice = bool(understanding_payload.get("needs_advice")) or needs_advice(question)
    inferred_needs_forecast = bool(understanding_payload.get("needs_forecast")) or needs_forecast(
        question,
        finalized.get("future_window") if isinstance(finalized.get("future_window"), dict) else None,
        inferred_needs_advice,
    )
    finalized["query_plan"] = build_query_plan(
        plan_intent=str(finalized.get("intent") or "advice"),
        route=route,
        domain=str(finalized.get("domain") or ""),
        region_name=str(finalized.get("region_name") or ""),
        historical_window=dict(finalized.get("historical_window") or {}),
        future_window=finalized.get("future_window") if isinstance(finalized.get("future_window"), dict) else None,
        answer_mode=str(finalized.get("answer_mode") or ""),
        needs_clarification=bool(finalized.get("needs_clarification")),
        is_greeting=is_greeting_question(question),
        needs_explanation=inferred_needs_explanation,
        needs_forecast=inferred_needs_forecast,
        needs_advice=inferred_needs_advice,
    )
    finalized["query_plan"]["decomposition"] = build_task_graph(finalized["query_plan"])
    finalized["route"] = execution_route(finalized["query_plan"])
    return finalized
