"""Agent 领域契约：集中定义规划、执行和响应的数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field

from .semantic_parse import SemanticParseResult

__all__ = [
    "SemanticParseResult",
    "AnalysisSynthesisPayload",
    "RequestUnderstandingPayload",
    "PlanPayload",
    "AnalysisResponseEnvelope",
    "ForecastExecutionContext",
    "FinalResponseEvidence",
    "OrchestrationStateEnvelope",
]


@dataclass(frozen=True)
class AnalysisSynthesisPayload:
    """分析模式响应的证据载体。"""
    execution_plan: list[str]
    request_understanding: dict
    analysis_context: dict
    historical_query: dict
    forecast: dict
    knowledge: list[dict]
    knowledge_sources: list
    generation_mode: str
    knowledge_policy: dict = field(default_factory=dict)
    evidence_layers: dict = field(default_factory=dict)
    context_trace: list[str] = field(default_factory=list)

    def to_evidence(self) -> dict:
        """转换为可直接写入响应 evidence 的字典。"""
        evidence = {
            "execution_plan": list(self.execution_plan),
            "request_understanding": dict(self.request_understanding),
            "analysis_context": dict(self.analysis_context),
            "historical_query": dict(self.historical_query),
            "forecast": dict(self.forecast),
            "knowledge": list(self.knowledge),
            "knowledge_sources": list(self.knowledge_sources),
            "generation_mode": self.generation_mode,
        }
        if self.knowledge_policy:
            evidence["knowledge_policy"] = dict(self.knowledge_policy)
        if self.evidence_layers:
            evidence["evidence_layers"] = dict(self.evidence_layers)
        if self.context_trace:
            evidence["context_trace"] = list(self.context_trace)
        return evidence


@dataclass(frozen=True)
class RequestUnderstandingPayload:
    """请求理解结果的强类型包装。"""
    original_question: str
    resolved_question: str
    normalized_question: str
    historical_query_text: str
    task_type: str
    domain: str
    window: dict
    future_window: dict | None
    region_name: str
    region_level: str
    needs_historical: bool
    needs_forecast: bool
    needs_explanation: bool
    needs_advice: bool
    used_context: bool
    execution_plan: list[str]
    extras: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict | None) -> "RequestUnderstandingPayload":
        """从松散字典恢复为理解载体对象。"""
        raw = dict(payload or {})
        future_window = raw.get("future_window")
        return cls(
            original_question=str(raw.get("original_question") or ""),
            resolved_question=str(raw.get("resolved_question") or ""),
            normalized_question=str(raw.get("normalized_question") or ""),
            historical_query_text=str(raw.get("historical_query_text") or ""),
            task_type=str(raw.get("task_type") or ""),
            domain=str(raw.get("domain") or ""),
            window=dict(raw.get("window") or {}),
            future_window=dict(future_window) if isinstance(future_window, dict) else None,
            region_name=str(raw.get("region_name") or ""),
            region_level=str(raw.get("region_level") or ""),
            needs_historical=bool(raw.get("needs_historical")),
            needs_forecast=bool(raw.get("needs_forecast")),
            needs_explanation=bool(raw.get("needs_explanation")),
            needs_advice=bool(raw.get("needs_advice")),
            used_context=bool(raw.get("used_context")),
            execution_plan=list(raw.get("execution_plan") or []),
            extras={
                key: value
                for key, value in raw.items()
                if key
                not in {
                    "original_question",
                    "resolved_question",
                    "normalized_question",
                    "historical_query_text",
                    "task_type",
                    "domain",
                    "window",
                    "future_window",
                    "region_name",
                    "region_level",
                    "needs_historical",
                    "needs_forecast",
                    "needs_explanation",
                    "needs_advice",
                    "used_context",
                    "execution_plan",
                }
            },
        )

    def to_dict(self) -> dict:
        """导出为可序列化字典，并保留额外字段。"""
        payload = {
            "original_question": self.original_question,
            "resolved_question": self.resolved_question,
            "normalized_question": self.normalized_question,
            "historical_query_text": self.historical_query_text,
            "task_type": self.task_type,
            "domain": self.domain,
            "window": dict(self.window),
            "future_window": dict(self.future_window) if isinstance(self.future_window, dict) else None,
            "region_name": self.region_name,
            "region_level": self.region_level,
            "needs_historical": self.needs_historical,
            "needs_forecast": self.needs_forecast,
            "needs_explanation": self.needs_explanation,
            "needs_advice": self.needs_advice,
            "used_context": self.used_context,
            "execution_plan": list(self.execution_plan),
        }
        payload.update(dict(self.extras))
        return payload


@dataclass(frozen=True)
class PlanPayload:
    """规划器输出的强类型包装。"""
    intent: str
    confidence: float
    route: dict
    query_plan: dict
    task_graph: dict
    needs_clarification: bool
    clarification: str | None
    reason: str
    context_trace: list[str]
    extras: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict | None) -> "PlanPayload":
        """从原始计划字典恢复为结构化对象。"""
        raw = dict(payload or {})
        return cls(
            intent=str(raw.get("intent") or ""),
            confidence=float(raw.get("confidence") or 0.0),
            route=dict(raw.get("route") or {}),
            query_plan=dict(raw.get("query_plan") or {}),
            task_graph=dict(raw.get("task_graph") or {}),
            needs_clarification=bool(raw.get("needs_clarification")),
            clarification=raw.get("clarification"),
            reason=str(raw.get("reason") or ""),
            context_trace=list(raw.get("context_trace") or []),
            extras={
                key: value
                for key, value in raw.items()
                if key
                not in {
                    "intent",
                    "confidence",
                    "route",
                    "query_plan",
                    "task_graph",
                    "needs_clarification",
                    "clarification",
                    "reason",
                    "context_trace",
                }
            },
        )

    def to_dict(self) -> dict:
        """导出为响应与状态节点可复用的字典。"""
        payload = {
            "intent": self.intent,
            "confidence": self.confidence,
            "route": dict(self.route),
            "query_plan": dict(self.query_plan),
            "task_graph": dict(self.task_graph),
            "needs_clarification": self.needs_clarification,
            "clarification": self.clarification,
            "reason": self.reason,
            "context_trace": list(self.context_trace),
        }
        payload.update(dict(self.extras))
        return payload


@dataclass(frozen=True)
class AnalysisResponseEnvelope:
    """analysis 模式响应外壳。"""
    answer: str
    historical_data: object
    forecast_data: object
    payload: AnalysisSynthesisPayload

    def to_response(self) -> dict:
        """组装前端消费的统一响应结构。"""
        return {
            "response": {
                "mode": "analysis",
                "answer": self.answer,
                "data": {
                    "historical": self.historical_data,
                    "forecast": self.forecast_data,
                },
                "evidence": self.payload.to_evidence(),
            }
        }


@dataclass(frozen=True)
class ForecastExecutionContext:
    """预测节点执行时需要的最小上下文。"""
    route: dict | None
    runtime_context: dict

    @property
    def enabled(self) -> bool:
        """判断当前计划是否真的启用了预测分支。"""
        return bool(self.route)


@dataclass(frozen=True)
class FinalResponseEvidence:
    """最终响应 evidence 的聚合包装器。"""
    base_evidence: dict
    historical_query: dict | None
    task_graph: dict | None
    memory_state: dict
    request_understanding: dict | None
    context_trace: list[str]
    response_meta: dict

    def to_dict(self) -> dict:
        """合并各阶段 evidence，得到最终可序列化结果。"""
        evidence = dict(self.base_evidence or {})
        if self.historical_query:
            evidence.setdefault("historical_query", dict(self.historical_query))
        if self.task_graph:
            evidence.setdefault("task_graph", dict(self.task_graph))
        evidence.setdefault("memory_state", dict(self.memory_state))
        if self.request_understanding:
            evidence.setdefault("request_understanding", dict(self.request_understanding))
        if self.context_trace:
            evidence["context_trace"] = list(self.context_trace)
        evidence["response_meta"] = dict(self.response_meta)
        return evidence


@dataclass(frozen=True)
class OrchestrationStateEnvelope:
    """统一编排状态快照。"""

    parsed_query: dict = field(default_factory=dict)
    route: dict = field(default_factory=dict)
    plan: dict = field(default_factory=dict)
    task_results: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    confidence: dict = field(default_factory=dict)
    memory_context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "parsed_query": dict(self.parsed_query),
            "route": dict(self.route),
            "plan": dict(self.plan),
            "task_results": dict(self.task_results),
            "evidence": dict(self.evidence),
            "confidence": dict(self.confidence),
            "memory_context": dict(self.memory_context),
        }
