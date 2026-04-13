from __future__ import annotations

from .agent_contracts import ForecastExecutionContext


def build_query_result_payload(result, route: dict) -> dict:
    evidence = dict(getattr(result, "evidence", {}) or {})
    evidence.setdefault("query_type", route.get("query_type") or "")
    evidence.setdefault("city", route.get("city"))
    evidence.setdefault("county", route.get("county"))
    evidence.setdefault("window", route.get("window") or {})
    return {
        "mode": "data_query",
        "answer": getattr(result, "answer", ""),
        "data": getattr(result, "data", []),
        "evidence": evidence,
    }


def run_query_node(
    *,
    question: str,
    understanding: dict,
    plan: dict,
    memory_context: dict | None,
    detect_compare_request,
    answer_compare_request,
    normalize_historical_route,
    plan_route,
    query_engine,
) -> dict:
    compare_request = detect_compare_request(question, understanding, plan, memory_context)
    if compare_request:
        return {"query_result": answer_compare_request(question, compare_request, understanding, plan, memory_context)}
    if not understanding.get("needs_historical") and plan.get("intent") != "data_query":
        return {"query_result": {}}
    question_for_query = understanding.get("historical_query_text") or question
    route = normalize_historical_route(question_for_query, plan_route(plan), understanding, memory_context)
    if route.get("query_type") in {"pest_forecast", "soil_forecast"}:
        return {"query_result": {}}
    result = query_engine.answer(question_for_query, plan=route)
    return {"query_result": build_query_result_payload(result, route)}


def build_forecast_execution_context(
    *,
    question: str,
    understanding: dict,
    plan: dict,
    memory_context: dict | None,
    query_result: dict,
    normalize_historical_route,
    plan_route,
    derive_domain,
    infer_region_level_from_name,
    asks_region_ranking,
    first_region_name,
) -> ForecastExecutionContext:
    if not understanding.get("needs_forecast"):
        return ForecastExecutionContext(route=None, runtime_context={})

    plan = dict(plan or {})
    memory_context = dict(memory_context or {})
    route = normalize_historical_route(
        understanding.get("historical_query_text") or question,
        plan_route(plan),
        understanding,
        memory_context,
    )
    future_window = understanding.get("future_window") or {"horizon_days": 14}
    domain = understanding.get("domain") or memory_context.get("domain") or derive_domain(question, plan, memory_context)
    first_region = first_region_name(query_result) if query_result else ""
    inherited_region = memory_context.get("region_name") if understanding.get("reuse_region_from_context") else ""
    region_name = understanding.get("region_name") or route.get("county") or route.get("city") or inherited_region or first_region
    region_level = (
        understanding.get("region_level")
        or route.get("region_level")
        or str((memory_context.get("route") or {}).get("region_level") or "")
        or infer_region_level_from_name(str(region_name or ""))
        or "city"
    )
    forecast_mode = route.get("forecast_mode") or ("ranking" if not region_name and asks_region_ranking(understanding.get("original_question", "")) else "region")
    forecast_route = {
        "query_type": f"{domain}_forecast",
        "since": route.get("since") or memory_context.get("route", {}).get("since") or "1970-01-01 00:00:00",
        "until": route.get("until"),
        "city": region_name if region_level != "county" else None,
        "county": region_name if region_level == "county" else None,
        "region_level": region_level,
        "top_n": route.get("top_n") or 1,
        "window": route.get("window") or understanding.get("window") or memory_context.get("window") or {"window_type": "all", "window_value": None},
        "forecast_window": future_window,
        "forecast_mode": forecast_mode,
    }
    runtime_context = {
        "domain": domain,
        "region_name": region_name or "",
        "region_level": region_level,
        "query_type": route.get("query_type") or memory_context.get("query_type") or "",
        "window": forecast_route["window"],
        "route": route or memory_context.get("route") or {},
        "forecast": memory_context.get("forecast") or {},
    }
    return ForecastExecutionContext(route=forecast_route, runtime_context=runtime_context)


def run_knowledge_node(
    *,
    question: str,
    understanding: dict,
    plan: dict,
    memory_context: dict | None,
    query_result: dict,
    forecast_result: dict,
    source_provider,
    build_runtime_context,
    first_region_name,
) -> dict:
    if not (understanding.get("needs_explanation") or understanding.get("needs_advice")):
        return {"knowledge": []}
    if source_provider is None:
        return {"knowledge": []}
    context = build_runtime_context(
        understanding.get("normalized_question") or question,
        plan,
        previous_context=memory_context,
        understanding=understanding,
    )
    context["region_name"] = (
        forecast_result.get("analysis_context", {}).get("region_name")
        or context.get("region_name")
        or first_region_name(query_result)
    )
    if forecast_result.get("forecast"):
        context["forecast"] = forecast_result["forecast"]
    knowledge = source_provider.search(
        understanding.get("normalized_question") or question,
        limit=3,
        context=context,
    )
    return {"knowledge": knowledge}


def build_advice_response(
    *,
    question: str,
    plan: dict,
    understanding: dict,
    memory_context: dict | None,
    build_runtime_context,
    advice_engine,
    execution_plan: list[str],
) -> dict:
    runtime_context = build_runtime_context(
        understanding.get("normalized_question") or question,
        plan,
        previous_context=memory_context,
        understanding=understanding,
    )
    result = advice_engine.answer(question, context=runtime_context)
    evidence = {
        "sources": result.sources,
        "generation_mode": result.generation_mode,
        "analysis_context": runtime_context,
        "execution_plan": execution_plan,
    }
    if result.model:
        evidence["model"] = result.model
    return {
        "response": {
            "mode": "advice",
            "answer": result.answer,
            "data": [],
            "evidence": evidence,
        }
    }


def build_clarification_response(plan: dict) -> dict:
    return {
        "response": {
            "mode": "advice",
            "answer": plan.get("clarification"),
            "data": [],
            "evidence": {
                "generation_mode": "clarification",
                "confidence": plan.get("confidence", 0.0),
            },
        }
    }
