"""响应组装工具：统一构建直出响应与证据分层。"""

from __future__ import annotations


def _historical_evidence_target(query_result: dict | None) -> dict:
    evidence = dict((query_result or {}).get("evidence") or {})
    return {
        "kind": "historical_query",
        "query_type": str(evidence.get("query_type") or ""),
        "city": evidence.get("city"),
        "county": evidence.get("county"),
        "region_level": str(evidence.get("region_level") or ("county" if evidence.get("county") else "city")),
    }


def _forecast_evidence_target(forecast_result: dict | None) -> dict:
    forecast_result = dict(forecast_result or {})
    forecast = dict(forecast_result.get("forecast") or {})
    analysis_context = dict(forecast_result.get("analysis_context") or {})
    domain = str(forecast.get("domain") or analysis_context.get("domain") or "")
    return {
        "kind": "forecast",
        "query_type": f"{domain}_forecast" if domain else "forecast",
        "region_name": str(analysis_context.get("region_name") or ""),
        "region_level": str(analysis_context.get("region_level") or ""),
        "domain": domain,
    }


def attach_query_execution_evidence(query_result: dict, execution_plan: list[str], knowledge_policy: dict | None = None) -> dict:
    """给历史查询直出结果补齐执行步骤。"""
    payload = dict(query_result or {})
    evidence = dict(payload.get("evidence") or {})
    evidence["execution_plan"] = list(execution_plan)
    evidence.setdefault("evidence_target", _historical_evidence_target(payload))
    if knowledge_policy:
        evidence["knowledge_policy"] = dict(knowledge_policy)
    payload["evidence"] = evidence
    return payload


def build_forecast_only_response(
    forecast_result: dict,
    execution_plan: list[str],
    knowledge_policy: dict | None = None,
) -> dict:
    """构建仅预测型问题的统一响应。"""
    evidence = {
        **dict(forecast_result or {}),
        "execution_plan": list(execution_plan),
        "generation_mode": "forecast",
    }
    evidence["evidence_target"] = _forecast_evidence_target(forecast_result)
    if knowledge_policy:
        evidence["knowledge_policy"] = dict(knowledge_policy)
    return {
        "mode": "data_query",
        "answer": str((forecast_result or {}).get("answer") or ""),
        "data": (forecast_result or {}).get("data", []),
        "evidence": evidence,
    }


def _forecast_history_points(forecast: dict) -> int:
    value = forecast.get("history_points")
    if value not in {None, ""}:
        return int(value)
    for item in forecast.get("top_factors") or []:
        text = str(item or "")
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            return int(digits)
    return 0


def _forecast_evidence_label(confidence: float, history_points: int, evidence_strength: str) -> str:
    strength = str(evidence_strength or "").lower()
    if strength == "weak" or confidence < 0.65 or history_points < 14:
        return "偏弱"
    if confidence >= 0.75 and history_points >= 30 and strength != "weak":
        return "基本够"
    return "基本够"


def build_forecast_evidence_followup_response(
    *,
    question: str,
    forecast_result: dict,
    execution_plan: list[str],
    knowledge_policy: dict | None = None,
) -> dict:
    """回答“证据够吗/证据弱怎么办”这类预测证据追问。"""
    forecast_result = dict(forecast_result or {})
    forecast = dict(forecast_result.get("forecast") or {})
    confidence = float(forecast.get("confidence") or 0)
    history_points = _forecast_history_points(forecast)
    evidence_strength = str(forecast.get("evidence_strength") or "")
    label = _forecast_evidence_label(confidence, history_points, evidence_strength)
    factors = [str(item) for item in (forecast.get("top_factors") or []) if str(item)]
    factor_text = "；".join(factors[:2]) if factors else f"样本覆盖 {history_points} 个观测日"
    normalized_question = str(question or "")
    if any(token in normalized_question for token in ["证据弱", "如果证据弱", "应该怎么回答", "怎么回答", "如何回答"]):
        answer = (
            f"如果证据偏弱，应该明确说：当前证据{label}，置信度{confidence:.2f}，"
            f"样本覆盖 {history_points} 个观测日；只能作为趋势判断，不建议下确定性结论。"
            "同时要列出待核查项：监测点位是否连续、时间窗是否足够、阈值口径是否一致，以及现场记录是否能相互印证。"
        )
    else:
        answer = (
            f"证据{label}。当前预测置信度{confidence:.2f}，样本覆盖 {history_points} 个观测日，"
            f"主要依据是{factor_text}。这个证据可以用于短期趋势判断，但不应表述为确定结论；"
            "待核查：原始监测点位、时间窗覆盖、阈值口径和现场处置记录是否匹配。"
        )
    evidence = {
        **forecast_result,
        "execution_plan": list(execution_plan),
        "generation_mode": "forecast_evidence_followup",
        "evidence_assessment": {
            "label": label,
            "confidence": confidence,
            "history_points": history_points,
            "evidence_strength": evidence_strength,
        },
    }
    evidence["evidence_target"] = _forecast_evidence_target(forecast_result)
    if knowledge_policy:
        evidence["knowledge_policy"] = dict(knowledge_policy)
    return {
        "mode": "data_query",
        "answer": answer,
        "data": forecast_result.get("data", []),
        "evidence": evidence,
    }


def build_evidence_layers(
    *,
    query_result: dict,
    forecast_result: dict,
    knowledge: list[dict],
    knowledge_policy: dict | None,
    analysis_context: dict | None = None,
) -> dict:
    """把内部事实与外部知识拆成显式证据层。"""
    analysis_context = dict(analysis_context or {})
    layers = {
        "internal_facts": {
            "historical_query": dict((query_result or {}).get("evidence") or {}),
            "forecast": dict((forecast_result or {}).get("forecast") or {}),
        },
        "targets": {
            "historical_query": _historical_evidence_target(query_result),
            "forecast": _forecast_evidence_target(forecast_result),
        },
        "external_knowledge": {
            "items": list(knowledge or []),
            "source": "external",
            "policy": dict(knowledge_policy or {}),
        },
        "conversation_hints": {
            "domain": str(analysis_context.get("domain") or ""),
            "crop": str(analysis_context.get("crop") or ""),
            "scene": str(analysis_context.get("scene") or ""),
        },
    }
    return layers
