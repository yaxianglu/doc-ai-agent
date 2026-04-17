"""会话记忆快照工具：负责槽位标准化与持久化结构构建。"""

from __future__ import annotations


def query_family_from_type(query_type: str) -> str:
    """把 query_type 折叠成稳定的查询家族，便于跨轮追问复用。"""
    normalized = str(query_type or "")
    if normalized == "active_devices":
        return "activity"
    if normalized.endswith("_top") or normalized in {"top", "joint_risk"}:
        return "ranking"
    if normalized.endswith("_trend") or normalized == "city_day_change":
        return "trend"
    if normalized.endswith("_detail"):
        return "detail"
    if normalized.endswith("_overview"):
        return "overview"
    if normalized.endswith("_forecast"):
        return "forecast"
    return ""


def memory_time_range_value(window: dict | None) -> dict:
    """把 window 结构转换为标准化 time_range 槽位值。"""
    normalized_window = dict(window or {})
    window_type = str(normalized_window.get("window_type") or "")
    window_value = normalized_window.get("window_value")
    if window_type in {"months", "weeks", "days"} and window_value not in {None, ""}:
        return {"mode": "relative", "value": f"{window_value}_{window_type}"}
    return {"mode": "none", "value": None}


def memory_scalar_value(value: object) -> str:
    """把普通字符串槽位统一归一化。"""
    return str(value or "").strip()


def memory_slot_priority(source: str) -> int:
    """按来源类型给记忆槽位分配优先级。"""
    if source == "explicit":
        return 100
    if source == "carried":
        return 90
    if source == "system":
        return 80
    if source == "inferred":
        return 60
    if source == "legacy":
        return 50
    return 0


def memory_slot_ttl(source: str) -> int:
    """按来源类型给记忆槽位设置有效轮次。"""
    if source in {"explicit", "carried"}:
        return 4
    if source == "system":
        return 2
    if source in {"inferred", "legacy"}:
        return 2
    return 0


def build_memory_slot(
    *,
    value,
    source: str,
    turn_count: int,
    previous_slot: dict | None = None,
    preserve_previous: bool = False,
) -> dict:
    """构建单个记忆槽位，附带来源优先级与有效轮次信息。"""
    if preserve_previous and previous_slot:
        return dict(previous_slot)

    if previous_slot and previous_slot.get("value") == value and previous_slot.get("source") == source:
        updated_at_turn = int(previous_slot.get("updated_at_turn") or turn_count)
    else:
        updated_at_turn = turn_count
    return {
        "value": value,
        "source": source,
        "priority": memory_slot_priority(source),
        "ttl": memory_slot_ttl(source),
        "updated_at_turn": updated_at_turn,
    }


def build_memory_snapshot(
    *,
    question: str,
    plan: dict,
    response: dict,
    previous_context: dict | None,
    understanding: dict | None,
    plan_route,
    first_region_name,
    derive_domain,
) -> dict:
    """生成标准化记忆快照，供持久化层写入。"""
    previous_context = dict(previous_context or {})
    plan = dict(plan or {})
    response = dict(response or {})
    understanding = dict(understanding or {})
    preserve_thread_scope = str(plan.get("reason") or "") in {"greeting_intro", "identity_self_intro"}
    route = plan_route(plan) or dict(previous_context.get("route") or {})
    evidence = dict(response.get("evidence") or {})
    analysis_context = dict(evidence.get("analysis_context") or {})
    forecast = dict(evidence.get("forecast") or previous_context.get("forecast") or {})
    previous_slots = dict(previous_context.get("slots") or {})
    turn_count = int(previous_context.get("turn_count") or 0) + 1

    if preserve_thread_scope and previous_context:
        route = dict(previous_context.get("route") or route)
        forecast = dict(previous_context.get("forecast") or forecast)

    domain = (
        analysis_context.get("domain")
        or (previous_context.get("domain") if preserve_thread_scope else "")
        or derive_domain(question, route, previous_context)
    )
    inherited_region = previous_context.get("region_name") if understanding.get("reuse_region_from_context", True) else ""
    region_name = (
        analysis_context.get("region_name")
        or (previous_context.get("region_name") if preserve_thread_scope else "")
        or route.get("county")
        or route.get("city")
        or first_region_name(response)
        or inherited_region
        or ""
    )
    window = route.get("window") or previous_context.get("window") or {}
    query_plan = dict(plan.get("query_plan") or {})
    query_plan_intent = str(query_plan.get("intent") or plan.get("intent") or "")
    query_type = analysis_context.get("query_type") or route.get("query_type") or previous_context.get("query_type") or ""
    answer_form = memory_scalar_value(
        understanding.get("answer_form")
        or analysis_context.get("answer_form")
        or previous_context.get("answer_form")
        or ""
    )
    region_level = memory_scalar_value(
        analysis_context.get("region_level")
        or route.get("region_level")
        or (previous_context.get("route") or {}).get("region_level")
        or ""
    )

    domain_source = "explicit" if understanding.get("domain") else ("carried" if preserve_thread_scope and previous_slots.get("domain") else ("inferred" if domain else "empty"))
    region_source = (
        "explicit"
        if understanding.get("region_name") or route.get("county") or route.get("city")
        else ("carried" if preserve_thread_scope and previous_slots.get("region") else ("inferred" if region_name else "empty"))
    )
    explicit_window = dict(understanding.get("window") or {})
    window_source = (
        "explicit"
        if str(explicit_window.get("window_type") or "") in {"months", "weeks", "days"} and explicit_window.get("window_value") not in {None, ""}
        else ("carried" if preserve_thread_scope and previous_slots.get("time_range") else ("inferred" if window else "empty"))
    )
    intent_source = "system" if query_plan_intent else "empty"
    answer_form_source = (
        "explicit"
        if understanding.get("answer_form")
        else ("carried" if previous_slots.get("answer_form") and answer_form else ("inferred" if answer_form else "empty"))
    )
    region_level_source = (
        "explicit"
        if understanding.get("region_level") or route.get("region_level")
        else ("carried" if previous_slots.get("region_level") and region_level else ("inferred" if region_level else "empty"))
    )

    slots = {
        "domain": build_memory_slot(
            value=domain,
            source=domain_source,
            turn_count=turn_count,
            previous_slot=previous_slots.get("domain"),
            preserve_previous=preserve_thread_scope,
        ),
        "region": build_memory_slot(
            value=region_name,
            source=region_source,
            turn_count=turn_count,
            previous_slot=previous_slots.get("region"),
            preserve_previous=preserve_thread_scope,
        ),
        "time_range": build_memory_slot(
            value=memory_time_range_value(window),
            source=window_source,
            turn_count=turn_count,
            previous_slot=previous_slots.get("time_range"),
            preserve_previous=preserve_thread_scope,
        ),
        "intent": build_memory_slot(
            value=query_plan_intent,
            source=intent_source,
            turn_count=turn_count,
            previous_slot=previous_slots.get("intent"),
        ),
        "answer_form": build_memory_slot(
            value=answer_form,
            source=answer_form_source,
            turn_count=turn_count,
            previous_slot=previous_slots.get("answer_form"),
            preserve_previous=preserve_thread_scope,
        ),
        "region_level": build_memory_slot(
            value=region_level,
            source=region_level_source,
            turn_count=turn_count,
            previous_slot=previous_slots.get("region_level"),
            preserve_previous=preserve_thread_scope,
        ),
    }

    pending_user_question = None
    pending_clarification = None
    if plan.get("reason") == "agri_domain_ambiguous":
        pending_user_question = question
        pending_clarification = "agri_domain"
    elif plan.get("reason") == "placeholder_entity_clarification":
        pending_user_question = question
        pending_clarification = "placeholder_entity"
    elif plan.get("reason") in {"generic_ambiguous", "ambiguous", "low_signal"}:
        pending_user_question = question
        pending_clarification = "generic_intent"

    time_range_value = slots["time_range"]["value"]
    memory_layers = {
        "session_context": {
            "domain": domain,
            "region_name": region_name,
            "route": dict(route),
            "forecast": dict(forecast),
            "last_question": question,
            "turn_count": turn_count,
        },
        "task_context": {
            "query_type": query_type,
            "query_family": query_family_from_type(query_type),
            "intent": query_plan_intent,
            "answer_form": answer_form,
            "region_level": region_level,
            "time_range": dict(time_range_value) if isinstance(time_range_value, dict) else {"mode": "none", "value": None},
            "pending_clarification": pending_clarification,
        },
        "user_context": dict(previous_context.get("user_preferences") or {}),
    }

    return {
        "memory_version": 2,
        "turn_count": turn_count,
        "domain": domain,
        "region_name": region_name,
        "answer_form": answer_form,
        "query_type": query_type,
        "window": window,
        "route": route,
        "forecast": forecast,
        "last_question": question,
        "last_answer": response.get("answer", ""),
        "last_verified_answer": response.get("answer", "") if response.get("mode") != "advice" or not plan.get("needs_clarification") else "",
        "pending_user_question": pending_user_question,
        "pending_clarification": pending_clarification,
        "user_preferences": dict(previous_context.get("user_preferences") or {}),
        "memory_layers": memory_layers,
        "conversation_state": {
            "last_intent": str(plan.get("intent") or ""),
            "last_answer_mode": str(response.get("mode") or ""),
            "last_clarification_reason": str(plan.get("reason") or "") if plan.get("needs_clarification") else "",
            "last_query_family": query_family_from_type(query_type),
            "last_region_level": region_level,
            "last_answer_form": answer_form,
        },
        "slots": slots,
    }
