"""响应组装工具：统一构建直出响应与证据分层。"""

from __future__ import annotations


def attach_query_execution_evidence(query_result: dict, execution_plan: list[str], knowledge_policy: dict | None = None) -> dict:
    """给历史查询直出结果补齐执行步骤。"""
    payload = dict(query_result or {})
    evidence = dict(payload.get("evidence") or {})
    evidence["execution_plan"] = list(execution_plan)
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
) -> dict:
    """把内部事实与外部知识拆成显式证据层。"""
    layers = {
        "internal_facts": {
            "historical_query": dict((query_result or {}).get("evidence") or {}),
            "forecast": dict((forecast_result or {}).get("forecast") or {}),
        },
        "external_knowledge": {
            "items": list(knowledge or []),
            "source": "external",
            "policy": dict(knowledge_policy or {}),
        },
    }
    return layers
