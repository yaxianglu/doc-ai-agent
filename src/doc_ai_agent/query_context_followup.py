"""上下文追问规划。

该模块处理“上一轮问题的延续提问”，例如：
- “换成虫情看下”
- “那这个县呢”
- “未来两周会更糟吗”

核心思想：优先复用线程上下文，最小化重复提问，同时保证安全边界。
"""

from __future__ import annotations

from .agri_semantics import has_trend_intent
from .followup_semantics import (
    explicit_domain_from_text,
    has_domain_switch_verb,
    is_advice_follow_up,
    is_detail_follow_up,
    is_explanation_follow_up,
    is_scope_correction_follow_up,
    looks_like_contextual_follow_up,
)


def _asks_region_ranking(planner, question: str) -> bool:
    """判断问题是否在追问“地区排行”。"""
    helper = getattr(planner, "_asks_region_ranking", None)
    if callable(helper):
        return bool(helper(question))
    normalized = str(question or "")
    return any(token in normalized for token in ["哪里", "哪儿", "哪些地区", "哪些地方", "最高的县", "最高的区", "最严重的地方", "风险最高"])


def _query_family_from_type(query_type: str) -> str:
    normalized = str(query_type or "")
    if normalized == "active_devices":
        return "activity"
    if normalized.endswith("_top") or normalized == "joint_risk":
        return "ranking"
    if normalized.endswith("_trend"):
        return "trend"
    if normalized.endswith("_detail"):
        return "detail"
    if normalized.endswith("_overview"):
        return "overview"
    if normalized.endswith("_forecast"):
        return "forecast"
    return ""


def _query_type_from_family(domain: str, family: str) -> str:
    if family == "activity":
        return "active_devices"
    if domain not in {"pest", "soil"}:
        return ""
    if family == "ranking":
        return f"{domain}_top"
    if family == "trend":
        return f"{domain}_trend"
    if family == "detail":
        return f"{domain}_detail"
    if family == "overview":
        return f"{domain}_overview"
    if family == "forecast":
        return f"{domain}_forecast"
    return ""


def _has_explicit_follow_up_cue(question: str) -> bool:
    normalized = str(question or "").strip()
    if not normalized:
        return False
    return any(
        token in normalized
        for token in [
            "呢",
            "其中",
            "这个",
            "该",
            "那",
            "那么",
            "那就",
            "按县",
            "按区",
            "按市",
            "换成",
            "改成",
            "切到",
            "为什么",
            "原因",
            "建议",
            "怎么办",
            "怎么做",
            "怎么处理",
        ]
    )


def _asks_forecast_support(question: str) -> bool:
    normalized = str(question or "").strip()
    if not normalized:
        return False
    return any(
        token in normalized
        for token in ["依据", "证据", "置信度", "样本覆盖", "证据弱", "证据够", "怎么回答", "如何回答"]
    )


def build_context_follow_up_plan(planner, question: str, context: dict | None, understanding: dict | None = None) -> dict | None:
    """基于线程上下文构造追问计划。

    返回 `None` 表示当前问题不适合走“上下文追问复用”链路。
    """
    context = dict(context or {})
    understanding = dict(understanding or {})
    if not context:
        return None
    if planner._is_greeting_question(question):
        return None
    followup_type = str(
        understanding.get("followup_type")
        or ((understanding.get("semantic_parse") or {}).get("followup_type") if isinstance(understanding.get("semantic_parse"), dict) else "")
        or "none"
    )
    explicit_followup = followup_type in {
        "domain_follow_up",
        "time_follow_up",
        "region_follow_up",
        "explanation_follow_up",
        "forecast_follow_up",
        "advice_follow_up",
    }
    previous_route = dict(context.get("route") or {})
    conversation_state = dict(context.get("conversation_state") or {})
    previous_query_type = str(previous_route.get("query_type") or context.get("query_type") or "")
    domain = str(context.get("domain") or planner._domain_from_query_type(previous_query_type) or "")
    previous_query_family = str(conversation_state.get("last_query_family") or _query_family_from_type(previous_query_type))
    if not previous_query_type and previous_query_family:
        previous_query_type = _query_type_from_family(domain, previous_query_family)
    trace = [f"reused thread context domain={domain or 'unknown'}"]
    previous_region_name = str(context.get("region_name") or "")
    previous_region_level = str(previous_route.get("region_level") or conversation_state.get("last_region_level") or "")
    if any(token in question for token in ["这个县", "该县", "这个区", "该区"]) and previous_region_level != "county":
        # 县/区指代对粒度要求更高，若上文不是县级上下文则先澄清，避免误用。
        return {
            "intent": "advice",
            "confidence": 0.3,
            "route": dict(previous_route),
            "needs_clarification": True,
            "clarification": "请补充具体对象，比如县名、区名或设备编码，我再继续分析。",
            "reason": "context_placeholder_county_clarification",
            "context_trace": trace + ["county placeholder cannot safely reuse non-county context"],
        }
    if any(token in question for token in ["这个市", "该市", "这个地区", "该地区", "这个区域", "该区域"]) and not previous_region_name:
        return {
            "intent": "advice",
            "confidence": 0.3,
            "route": dict(previous_route),
            "needs_clarification": True,
            "clarification": "请补充具体对象，比如市名、地区名或设备编码，我再继续分析。",
            "reason": "context_placeholder_region_clarification",
            "context_trace": trace + ["placeholder region missing concrete context"],
        }
    future_window = planner._extract_future_window(question)
    explicit_domain = explicit_domain_from_text(question, context_domain=domain)
    explicit_domain_signal = explicit_domain_from_text(question, context_domain="")
    relative_since, relative_until, relative_window = planner._extract_relative_window(question)
    city = planner._extract_city(question)
    county = planner._extract_county(question)
    device_code = str(previous_route.get("device_code") or context.get("route", {}).get("device_code") or "")
    ranking_follow_up = _asks_region_ranking(planner, question)
    trend_follow_up = has_trend_intent(question)
    has_explicit_historical_window = relative_window.get("window_type") not in {"all", "none", ""}
    has_explicit_follow_up_cue = _has_explicit_follow_up_cue(question)
    allow_implicit_ranking_follow_up = ranking_follow_up and not has_explicit_historical_window and not future_window
    allow_forecast_support_follow_up = previous_query_family == "forecast" and _asks_forecast_support(question)

    if (
        not explicit_followup
        and ranking_follow_up
        and has_explicit_historical_window
        and not future_window
        and not explicit_domain_signal
        and not city
        and not county
        and not has_explicit_follow_up_cue
    ):
        return None

    if (
        not explicit_followup
        and not looks_like_contextual_follow_up(question, is_greeting_question=planner._is_greeting_question)
        and not allow_implicit_ranking_follow_up
        and not allow_forecast_support_follow_up
    ):
        return None

    if (
        previous_query_type == "latest_device"
        and device_code
        and relative_window.get("window_type") != "none"
    ):
        route = dict(previous_route)
        route["query_type"] = "latest_device"
        route["device_code"] = device_code
        route["since"] = relative_since
        route["until"] = relative_until
        route["window"] = relative_window
        return {
            "intent": "data_query",
            "confidence": 0.89,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_device_window_follow_up",
            "context_trace": trace + [f"reuse device={device_code} and switch window={relative_window['window_type']}:{relative_window['window_value']}"],
        }

    if ranking_follow_up and domain in {"pest", "soil"} and not future_window:
        route = dict(previous_route)
        route["query_type"] = planner._query_type_for_region_follow_up(previous_query_type, explicit_domain or domain)
        route["region_level"] = "county" if planner._asks_for_county_scope(question) else str(route.get("region_level") or "city")
        route["city"] = city
        route["county"] = county
        if not city and not county:
            # 用户只问“哪里最严重”这类问题时，主动清空地域，交由排名逻辑全域检索。
            route["city"] = None
            route["county"] = None
        return {
            "intent": "data_query",
            "confidence": 0.9,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_ranking_follow_up",
            "context_trace": trace + [f"preserve ranking intent scope={route['region_level']}"],
        }

    if (
        trend_follow_up
        and not planner._has_negated_trend(question)
        and domain in {"pest", "soil"}
        and previous_query_family in {"ranking", "overview", "trend"}
    ):
        route = dict(previous_route)
        route["query_type"] = f"{explicit_domain or domain}_trend"
        route["city"] = city or route.get("city")
        route["county"] = county or route.get("county")
        if county:
            route["region_level"] = "county"
        elif city:
            route["region_level"] = "city"
        return {
            "intent": "data_query",
            "confidence": 0.9,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_trend_follow_up",
            "context_trace": trace + ["switch query family from ranking to trend"],
        }

    if is_detail_follow_up(question) and domain in {"pest", "soil"}:
        route = dict(previous_route)
        route["query_type"] = f"{explicit_domain or domain}_detail"
        if relative_window.get("window_type") != "none":
            route["since"] = relative_since
            route["until"] = relative_until
            route["window"] = relative_window
        if not route.get("city") and not route.get("county") and context.get("region_name"):
            route["city"] = context.get("region_name")
            route["region_level"] = "city"
        return {
            "intent": "data_query",
            "confidence": 0.91,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_detail_follow_up",
            "context_trace": trace + ["reused previous analysis context for concrete data"],
        }

    if previous_query_family == "forecast" and domain in {"pest", "soil"} and (
        followup_type == "forecast_follow_up"
        or is_explanation_follow_up(question)
        or _asks_forecast_support(question)
    ):
        route = dict(previous_route)
        route["query_type"] = f"{explicit_domain or domain}_forecast"
        route["forecast_window"] = route.get("forecast_window") or dict(context.get("forecast") or {}).get("window") or {
            "window_type": "days",
            "window_value": 14,
            "horizon_days": 14,
        }
        return {
            "intent": "data_query",
            "confidence": 0.92,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_forecast_support_follow_up",
            "context_trace": trace + ["reused previous forecast context for support/evidence"],
        }

    if (followup_type == "advice_follow_up" or is_advice_follow_up(question)) and domain in {"pest", "soil"}:
        return {
            "intent": "advice",
            "confidence": 0.9,
            "route": dict(previous_route),
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_advice_follow_up",
            "context_trace": trace + ["reused previous analysis context for advice"],
        }

    if (followup_type == "explanation_follow_up" or is_explanation_follow_up(question)) and domain in {"pest", "soil"}:
        return {
            "intent": "advice",
            "confidence": 0.91,
            "route": dict(previous_route),
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_explanation_follow_up",
            "context_trace": trace + ["reused previous analysis context for explanation"],
        }

    if is_scope_correction_follow_up(question) and domain in {"pest", "soil"}:
        route = dict(previous_route)
        route["query_type"] = planner._query_type_for_region_follow_up(previous_query_type, domain)
        route["city"] = None
        route["county"] = None
        route["region_level"] = "county" if planner._asks_for_county_scope(question) else "city"
        return {
            "intent": "data_query",
            "confidence": 0.89,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_scope_correction_follow_up",
            "context_trace": trace + [f"switch region scope={route['region_level']} and preserve analysis intent"],
        }

    if explicit_domain in {"pest", "soil"} and domain in {"pest", "soil"} and (
        followup_type == "domain_follow_up" or explicit_domain != domain or has_domain_switch_verb(question)
    ):
        next_query_type = planner._query_type_for_domain_switch(previous_query_type, explicit_domain)
        route = dict(previous_route)
        route["query_type"] = next_query_type
        if relative_window.get("window_type") != "none":
            route["since"] = relative_since
            route["until"] = relative_until
            route["window"] = relative_window
        if not route.get("city") and not route.get("county") and context.get("region_name"):
            route["city"] = context.get("region_name")
            route["region_level"] = "city"
        return {
            "intent": "data_query",
            "confidence": 0.9,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_domain_switch_follow_up",
            "context_trace": trace + [f"switch domain={explicit_domain} and preserve scope"],
        }

    if (followup_type == "forecast_follow_up" or future_window) and domain in {"pest", "soil"}:
        route = dict(previous_route)
        route["query_type"] = f"{domain}_forecast"
        route["forecast_window"] = future_window or dict(context.get("forecast") or {}).get("window") or {"window_type": "days", "window_value": 14, "horizon_days": 14}
        forecast_ranking_follow_up = ranking_follow_up or (
            previous_query_family == "ranking"
            and not previous_region_name
            and not city
            and not county
        ) or (
            previous_query_type in {"pest_top", "soil_top"}
            and str(previous_route.get("region_level") or "") == "county"
            and not any(token in question for token in ["更糟", "恶化", "更严重", "会怎样", "怎么样"])
            and len((question or "").strip()) <= 8
        )
        if forecast_ranking_follow_up:
            route["forecast_mode"] = "ranking"
            route["region_level"] = "county" if planner._asks_for_county_scope(question) else str(route.get("region_level") or "city")
            route["city"] = city
            route["county"] = county
            if not city and not county:
                # 预测排行追问但未给具体地区时，保留“全域排行”语义。
                route["city"] = None
                route["county"] = None
        elif not route.get("city") and not route.get("county") and context.get("region_name"):
            route["city"] = context.get("region_name")
            route["region_level"] = "city"
        return {
            "intent": "data_query",
            "confidence": 0.92,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_forecast_follow_up",
            "context_trace": trace + [f"forecast horizon={future_window['horizon_days']}d"],
        }

    if (
        (followup_type == "time_follow_up" or relative_window.get("window_type") != "none")
        and (domain in {"pest", "soil"} or previous_query_type == "active_devices")
        and not (city or county)
    ):
        route = dict(previous_route)
        route["query_type"] = (
            "active_devices"
            if previous_query_type == "active_devices"
            else planner._query_type_for_window_follow_up(previous_query_type, domain)
        )
        if relative_window.get("window_type") != "none":
            route["since"] = relative_since
            route["until"] = relative_until
            route["window"] = relative_window
        if not route.get("city") and not route.get("county") and context.get("region_name"):
            route["city"] = context.get("region_name")
            route["region_level"] = "city"
        if previous_query_type == "active_devices":
            route["city"] = previous_route.get("city")
            route["county"] = previous_route.get("county")
            route["region_level"] = previous_route.get("region_level") or route.get("region_level") or "city"
        return {
            "intent": "data_query",
            "confidence": 0.89,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_window_follow_up",
            "context_trace": trace + [f"switch window={relative_window['window_type']}:{relative_window['window_value']}"],
        }

    if (followup_type == "region_follow_up" or (city or county)) and domain in {"pest", "soil"} and len(question.strip()) <= 12:
        route = dict(previous_route)
        route["city"] = city
        route["county"] = county
        route["region_level"] = "county" if county else "city"
        forecast = dict(context.get("forecast") or {})
        previous_forecast_window = dict(route.get("forecast_window") or {})
        if previous_query_type == f"{domain}_forecast" or forecast.get("horizon_days"):
            horizon_days = int(forecast.get("horizon_days") or previous_forecast_window.get("horizon_days") or 14)
            route["query_type"] = f"{domain}_forecast"
            route["forecast_window"] = {
                "window_type": previous_forecast_window.get("window_type") or "days",
                "window_value": previous_forecast_window.get("window_value") or horizon_days,
                "horizon_days": horizon_days,
            }
            return {
                "intent": "data_query",
                "confidence": 0.88,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "context_region_forecast_follow_up",
                "context_trace": trace + [f"switch region={(county or city)} and preserve forecast intent"],
            }
        route["query_type"] = planner._query_type_for_region_follow_up(previous_query_type, domain)
        return {
            "intent": "data_query",
            "confidence": 0.86,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "context_region_follow_up",
            "context_trace": trace + [f"focus region={(county or city)}"],
        }

    return None
