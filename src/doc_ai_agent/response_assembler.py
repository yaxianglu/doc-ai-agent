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
