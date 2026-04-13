from __future__ import annotations


def derive_domain(question: str, route: dict, previous_context: dict | None = None) -> str:
    previous_context = dict(previous_context or {})
    query_type = str(route.get("query_type") or "")
    if query_type.startswith("pest"):
        return "pest"
    if query_type.startswith("soil"):
        return "soil"
    if previous_context.get("domain"):
        return str(previous_context["domain"])
    if "虫" in question:
        return "pest"
    if "墒" in question:
        return "soil"
    return ""


def normalize_historical_route(
    *,
    question: str,
    route: dict,
    understanding: dict | None,
    previous_context: dict | None,
    build_route,
    infer_region_level_from_name,
) -> dict:
    normalized = dict(route or {})
    understanding = dict(understanding or {})
    previous_context = dict(previous_context or {})
    query_text = understanding.get("resolved_question") or question
    base_route = dict(build_route(query_text, str(normalized.get("query_type") or "structured_agri")))
    domain = understanding.get("domain") or derive_domain(query_text, normalized, previous_context)
    region_name = str(understanding.get("region_name") or "")
    region_level = str(understanding.get("region_level") or "")
    task_type = str(understanding.get("task_type") or "")
    explicit_window = understanding.get("window") if isinstance(understanding.get("window"), dict) else {}

    if normalized.get("query_type") == "structured_agri" and domain in {"pest", "soil"}:
        if task_type == "data_detail":
            normalized["query_type"] = f"{domain}_detail"
        elif task_type == "trend":
            normalized["query_type"] = f"{domain}_trend"
        elif task_type == "ranking":
            normalized["query_type"] = f"{domain}_top"
        elif region_name:
            normalized["query_type"] = f"{domain}_overview"
        else:
            normalized["query_type"] = f"{domain}_top"

    if not normalized.get("city") and not normalized.get("county"):
        if region_name:
            resolved_region_level = region_level or infer_region_level_from_name(region_name) or "city"
            if resolved_region_level == "county":
                normalized["county"] = region_name
            else:
                normalized["city"] = region_name
            normalized["region_level"] = resolved_region_level
        elif base_route.get("city"):
            normalized["city"] = base_route.get("city")
            normalized["region_level"] = base_route.get("region_level") or normalized.get("region_level") or "city"
        elif base_route.get("county"):
            normalized["county"] = base_route.get("county")
            normalized["region_level"] = base_route.get("region_level") or normalized.get("region_level") or "county"

    current_window = normalized.get("window") if isinstance(normalized.get("window"), dict) else {}
    if (not current_window or current_window.get("window_type") in {"none", "all"}) and explicit_window:
        normalized["window"] = explicit_window
        current_window = explicit_window
    elif not current_window and base_route.get("window"):
        normalized["window"] = base_route.get("window")
        current_window = normalized["window"]

    if normalized.get("since") in {None, "", "1970-01-01 00:00:00"}:
        if current_window and current_window.get("window_type") not in {"none", "all"}:
            normalized["since"] = base_route.get("since") or normalized.get("since")
        elif normalized.get("since") in {None, ""}:
            normalized["since"] = base_route.get("since") or normalized.get("since")
    if normalized.get("until") in {None, ""} and base_route.get("until"):
        normalized["until"] = base_route.get("until")
    if not normalized.get("region_level") and base_route.get("region_level"):
        normalized["region_level"] = base_route.get("region_level")
    if str(normalized.get("city") or "") in {"江苏", "江苏省"}:
        normalized["city"] = None
    if str(normalized.get("county") or "") in {"江苏", "江苏省"}:
        normalized["county"] = None
    return normalized


def build_runtime_context(
    *,
    question: str,
    plan: dict,
    previous_context: dict | None,
    understanding: dict | None,
    build_route,
    plan_route,
    infer_region_level_from_name,
    is_greeting_question,
) -> dict:
    previous_context = dict(previous_context or {})
    understanding = dict(understanding or {})
    route = normalize_historical_route(
        question=understanding.get("historical_query_text") or question,
        route=plan_route(plan),
        understanding=understanding,
        previous_context=previous_context,
        build_route=build_route,
        infer_region_level_from_name=infer_region_level_from_name,
    )
    if is_greeting_question(question):
        return {
            "domain": "",
            "region_name": "",
            "region_level": "",
            "query_type": "",
            "window": {},
            "route": {},
            "forecast": {},
        }
    inherited_region = previous_context.get("region_name") if understanding.get("reuse_region_from_context", True) else ""
    return {
        "domain": derive_domain(question, route, previous_context),
        "region_name": route.get("county") or route.get("city") or inherited_region or "",
        "region_level": route.get("region_level") or str((previous_context.get("route") or {}).get("region_level") or ""),
        "query_type": route.get("query_type") or previous_context.get("query_type") or "",
        "window": route.get("window") or previous_context.get("window") or {},
        "route": route or previous_context.get("route") or {},
        "forecast": previous_context.get("forecast") or {},
    }
