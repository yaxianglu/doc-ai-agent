from __future__ import annotations


def _normalized_route(route: dict | None) -> dict:
    raw = dict(route or {})
    top_n = raw.get("top_n")
    if top_n not in {None, ""}:
        top_n = max(1, int(top_n))
    return {
        "query_type": str(raw.get("query_type") or ""),
        "since": str(raw.get("since") or "1970-01-01 00:00:00"),
        "until": raw.get("until"),
        "city": raw.get("city"),
        "county": raw.get("county"),
        "device_code": raw.get("device_code"),
        "region_level": str(raw.get("region_level") or ("county" if raw.get("county") else "city")),
        "window": dict(raw.get("window") or {"window_type": "all", "window_value": None}),
        "top_n": top_n,
        "forecast_window": dict(raw.get("forecast_window") or {}) if isinstance(raw.get("forecast_window"), dict) else None,
        "forecast_mode": str(raw.get("forecast_mode") or ""),
    }


def _metric_for_query_type(query_type: str, domain: str) -> str:
    if query_type.startswith("pest") or domain == "pest":
        return "pest_severity"
    if query_type.startswith("soil") or domain == "soil":
        return "soil_anomaly"
    if query_type == "joint_risk" or domain == "mixed":
        return "joint_risk_score"
    return ""


def _time_range_payload(historical_window: dict | None) -> dict:
    window = dict(historical_window or {})
    window_type = str(window.get("window_type") or "")
    window_value = window.get("window_value")
    if window_type in {"months", "weeks", "days"} and window_value not in {None, ""}:
        return {"mode": "relative", "value": f"{window_value}_{window_type}"}
    return {"mode": "none", "value": None}


def _region_scope_payload(route: dict, region_name: str, goal: str) -> dict:
    if goal == "conversation":
        return {"level": "none", "value": ""}
    if region_name:
        return {
            "level": str(route.get("region_level") or ("county" if route.get("county") else "city")),
            "value": region_name,
        }
    return {"level": str(route.get("region_level") or "city"), "value": "all"}


def _aggregation_for_query_type(query_type: str, answer_mode: str, goal: str) -> str:
    if goal == "conversation":
        return "none"
    if query_type.endswith("_compare") or answer_mode == "compare":
        return "compare"
    if query_type.endswith("_top") or answer_mode == "ranking":
        return "top_k"
    if query_type.endswith("_detail") or answer_mode == "detail":
        return "detail"
    if query_type.endswith("_overview") or answer_mode == "overview":
        return "overview"
    if query_type.endswith("_trend") or answer_mode == "trend":
        return "trend"
    if query_type.endswith("_forecast") or answer_mode == "forecast":
        return "forecast"
    if query_type == "joint_risk":
        return "top_k"
    return "none"


def execution_route(query_plan: dict | None) -> dict:
    execution = dict((query_plan or {}).get("execution") or {})
    route = execution.get("route")
    if isinstance(route, dict):
        return _normalized_route(route)
    return {}


def replace_execution_route(query_plan: dict | None, route: dict) -> dict:
    updated = dict(query_plan or {})
    execution = dict(updated.get("execution") or {})
    execution["route"] = _normalized_route(route)
    updated["execution"] = execution
    slots = dict(updated.get("slots") or {})
    if slots.get("aggregation") == "top_k":
        slots["k"] = execution["route"].get("top_n") or 1
        updated["slots"] = slots
    return updated


def build_query_plan(
    *,
    plan_intent: str,
    route: dict,
    domain: str,
    region_name: str,
    historical_window: dict | None,
    future_window: dict | None,
    answer_mode: str,
    needs_clarification: bool,
    is_greeting: bool,
    needs_explanation: bool,
    needs_forecast: bool,
    needs_advice: bool,
) -> dict:
    if is_greeting:
        return {
            "version": "v1",
            "goal": "conversation",
            "intent": "greeting",
            "slots": {
                "domain": "",
                "metric": "",
                "time_range": {"mode": "none", "value": None},
                "region_scope": {"level": "none", "value": ""},
                "aggregation": "none",
                "k": None,
                "need_explanation": False,
                "need_forecast": False,
                "need_advice": False,
            },
            "constraints": {
                "must_use_structured_data": False,
                "allow_clarification": False,
            },
            "execution": {
                "route": _normalized_route(route),
                "domain": "",
                "region_name": "",
                "historical_window": {"window_type": "none", "window_value": None},
                "future_window": None,
                "answer_mode": "clarify" if needs_clarification else "none",
            },
        }

    query_type = str(route.get("query_type") or "")
    normalized_route = _normalized_route(route)
    aggregation = _aggregation_for_query_type(query_type, answer_mode, "agri_analysis" if domain else "conversation")
    return {
        "version": "v1",
        "goal": "agri_analysis" if domain else "conversation",
        "intent": "clarification" if needs_clarification else ("analysis" if plan_intent == "data_query" or domain else plan_intent),
        "slots": {
            "domain": domain,
            "metric": _metric_for_query_type(query_type, domain),
            "time_range": _time_range_payload(historical_window),
            "region_scope": _region_scope_payload(route, region_name, "agri_analysis" if domain else "conversation"),
            "aggregation": aggregation,
            "k": (route.get("top_n") or 1) if aggregation == "top_k" else None,
            "need_explanation": bool(needs_explanation),
            "need_forecast": bool(needs_forecast or future_window),
            "need_advice": bool(needs_advice),
        },
        "constraints": {
            "must_use_structured_data": bool(domain),
            "allow_clarification": not is_greeting,
        },
        "execution": {
            "route": normalized_route,
            "domain": domain,
            "region_name": region_name,
            "historical_window": dict(historical_window or {}),
            "future_window": dict(future_window or {}) if isinstance(future_window, dict) else None,
            "answer_mode": answer_mode,
        },
    }
