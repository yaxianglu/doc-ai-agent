"""知识边界策略：限制外部知识对事实型回答的影响范围。"""

from __future__ import annotations

from .query_plan import execution_route

FACT_QUERY_TYPES = {
    "alerts_count",
    "alerts_top",
    "alerts_trend",
    "pest_top",
    "pest_trend",
    "pest_overview",
    "soil_top",
    "soil_trend",
    "soil_overview",
}


def decide_knowledge_policy(*, understanding: dict | None, plan: dict | None) -> dict:
    """根据理解结果与计划决定是否允许知识检索。"""
    understanding = dict(understanding or {})
    plan = dict(plan or {})
    route = dict(plan.get("route") or execution_route(plan.get("query_plan")))
    query_type = str(route.get("query_type") or "")

    if understanding.get("needs_explanation") or understanding.get("needs_advice"):
        return {
            "mode": "augmentation",
            "should_retrieve": True,
            "reason": "explanation_or_advice_requested",
            "query_type": query_type,
        }

    if plan.get("intent") == "data_query" or query_type in FACT_QUERY_TYPES:
        return {
            "mode": "disabled",
            "should_retrieve": False,
            "reason": "fact_query_no_external_knowledge",
            "query_type": query_type,
        }

    return {
        "mode": "disabled",
        "should_retrieve": False,
        "reason": "knowledge_not_required",
        "query_type": query_type,
    }
