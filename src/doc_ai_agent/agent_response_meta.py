"""响应元信息工具：统一计算置信度、来源类型与回退原因。"""

from __future__ import annotations


def normalized_confidence(value: object, default: float = 0.0) -> float:
    """把任意输入归一化到 0~0.99 的置信度区间。"""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(default)
    return round(min(max(numeric, 0.0), 0.99), 2)


def dedupe_source_types(source_types: list[str]) -> list[str]:
    """去重并保留来源类型原始顺序。"""
    seen: list[str] = []
    for item in source_types:
        if item and item not in seen:
            seen.append(item)
    return seen


def has_meaningful_value(value: object) -> bool:
    """判断值是否足以作为“存在证据”的信号。"""
    return value not in (None, "", [])


def response_source_types(response: dict, evidence: dict, plan: dict) -> list[str]:
    """从响应与 evidence 中归纳数据来源类型。"""
    source_types: list[str] = []
    if evidence.get("generation_mode") == "clarification" or plan.get("needs_clarification"):
        source_types.append("planner")

    historical_query = dict(evidence.get("historical_query") or {})
    if not historical_query and response.get("mode") == "data_query":
        historical_query = dict(evidence)
    if historical_query and any(
        historical_query.get(key)
        for key in ["sql", "query_type", "rule", "no_data_reasons", "available_data_ranges"]
    ):
        source_types.append("db")

    forecast = dict(evidence.get("forecast") or {})
    if forecast and any(
        has_meaningful_value(forecast.get(key))
        for key in ["domain", "mode", "horizon_days", "risk_level"]
    ):
        source_types.append("forecast")

    knowledge = evidence.get("knowledge")
    knowledge_sources = evidence.get("knowledge_sources")
    sources = evidence.get("sources")
    if isinstance(knowledge, list) and knowledge:
        source_types.append("rag")
    elif isinstance(knowledge_sources, list) and any(
        isinstance(item, dict) and (item.get("retrieval_backend") or item.get("retrieval_engine") or item.get("url"))
        for item in knowledge_sources
    ):
        source_types.append("rag")
    elif isinstance(sources, list) and any(
        isinstance(item, dict) and (item.get("retrieval_backend") or item.get("retrieval_engine") or item.get("url"))
        for item in sources
    ):
        source_types.append("rag")

    generation_mode = str(evidence.get("generation_mode") or "")
    if generation_mode == "llm":
        source_types.append("llm")
    elif generation_mode == "rule" and response.get("mode") == "advice":
        source_types.append("rules")

    return dedupe_source_types(source_types)


def historical_response_confidence(response: dict, evidence: dict, plan: dict) -> float:
    """估算历史查询结果的可信度。"""
    historical_query = dict(evidence.get("historical_query") or {})
    if not historical_query and response.get("mode") == "data_query":
        historical_query = dict(evidence)
    if isinstance(historical_query.get("no_data_reasons"), list) and historical_query.get("no_data_reasons"):
        return 0.35

    plan_confidence = normalized_confidence(plan.get("confidence"), 0.0)
    data = response.get("data")
    if isinstance(data, list) and data:
        return max(plan_confidence, 0.78)
    if isinstance(data, dict) and data:
        return max(plan_confidence, 0.76)
    return min(max(plan_confidence, 0.0), 0.45)


def response_confidence(plan: dict, response: dict, evidence: dict, source_types: list[str]) -> float:
    """综合计划、数据来源与模式计算最终响应置信度。"""
    forecast = dict(evidence.get("forecast") or {})
    generation_mode = str(evidence.get("generation_mode") or "")
    mode = str(response.get("mode") or "")

    if generation_mode == "clarification":
        return normalized_confidence(plan.get("confidence"), 0.4)

    if mode == "analysis":
        components: list[tuple[float, float]] = []
        if "db" in source_types:
            components.append((historical_response_confidence(response, evidence, plan), 0.45))
        if "forecast" in source_types:
            components.append((normalized_confidence(forecast.get("confidence"), 0.0), 0.2))
        if "rag" in source_types:
            components.append((0.76, 0.35))
        if not components:
            return normalized_confidence(plan.get("confidence"), 0.5)

        total_weight = sum(weight for _, weight in components) or 1.0
        evidence_confidence = sum(value * weight for value, weight in components) / total_weight
        if len(components) >= 2:
            plan_confidence = normalized_confidence(plan.get("confidence"), evidence_confidence)
            evidence_confidence = (evidence_confidence * 0.8) + (plan_confidence * 0.2)
        return normalized_confidence(evidence_confidence, 0.5)

    if mode == "data_query":
        if "forecast" in source_types and forecast:
            return normalized_confidence(forecast.get("confidence"), 0.0)
        if "db" in source_types:
            return historical_response_confidence(response, evidence, plan)
        return normalized_confidence(plan.get("confidence"), 0.6)

    if mode == "advice":
        if generation_mode == "llm":
            return 0.84 if "rag" in source_types else 0.76
        if generation_mode == "rule":
            answer = str(response.get("answer") or "")
            if "AI农情工作台" in answer:
                return 0.98
            analysis_context = dict(evidence.get("analysis_context") or {})
            if analysis_context.get("domain"):
                return 0.72
            return 0.58
        return normalized_confidence(plan.get("confidence"), 0.55)

    return normalized_confidence(plan.get("confidence"), 0.5)


def response_fallback_reason(response: dict, evidence: dict, plan: dict, source_types: list[str]) -> str:
    """提取响应中最值得向前端暴露的降级原因。"""
    if evidence.get("generation_mode") == "clarification" or plan.get("needs_clarification"):
        return str(plan.get("reason") or "clarification")

    historical_query = dict(evidence.get("historical_query") or {})
    no_data_reasons = historical_query.get("no_data_reasons")
    if isinstance(no_data_reasons, list) and no_data_reasons:
        first = no_data_reasons[0]
        if isinstance(first, dict) and first.get("code"):
            return str(first["code"])

    forecast = dict(evidence.get("forecast") or {})
    fallback_reason = str(forecast.get("fallback_reason") or "")
    if fallback_reason:
        return fallback_reason

    if response.get("mode") == "advice" and evidence.get("generation_mode") == "rule" and "rag" not in source_types:
        analysis_context = dict(evidence.get("analysis_context") or {})
        if not analysis_context.get("domain"):
            return "rule_only_advice"

    return ""


def build_response_meta(plan: dict, response: dict, evidence: dict) -> dict:
    """构建统一 response_meta，便于前端展示与回放。"""
    source_types = response_source_types(response, evidence, plan)
    return {
        "confidence": response_confidence(plan, response, evidence, source_types),
        "source_types": source_types,
        "fallback_reason": response_fallback_reason(response, evidence, plan, source_types),
    }


def execution_plan(plan: dict | None, understanding: dict | None) -> list[str]:
    """根据计划与理解结果推导可读的执行步骤列表。"""
    normalized_plan = dict(plan or {})
    query_plan = dict(normalized_plan.get("query_plan") or {})
    decomposition = dict(query_plan.get("decomposition") or {})
    if decomposition:
        execution_plan_items = list(decomposition.get("execution_plan") or [])
        if execution_plan_items:
            return execution_plan_items
    task_graph = dict(normalized_plan.get("task_graph") or {})
    execution_plan_items = list(task_graph.get("execution_plan") or [])
    if execution_plan_items:
        return execution_plan_items
    normalized_understanding = dict(understanding or {})
    return list(normalized_understanding.get("execution_plan") or ["understand_request", "answer_synthesis"])
