"""语义解析结果契约。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SemanticParseResult:
    """统一承载语义解析阶段的最小结果。"""

    normalized_query: str = ""
    intent: str = "advice"
    is_out_of_scope: bool = False
    fallback_reason: str = ""
    trace: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict | None) -> "SemanticParseResult":
        """从松散字典构造默认安全的语义结果。"""
        raw = dict(payload or {})
        return cls(
            normalized_query=str(raw.get("normalized_query") or ""),
            intent=str(raw.get("intent") or "advice"),
            is_out_of_scope=bool(raw.get("is_out_of_scope")),
            fallback_reason=str(raw.get("fallback_reason") or ""),
            trace=list(raw.get("trace") or []),
        )

    def to_dict(self) -> dict:
        """导出为可序列化字典，便于兼容旧链路渐进接入。"""
        return {
            "normalized_query": self.normalized_query,
            "intent": self.intent,
            "is_out_of_scope": self.is_out_of_scope,
            "fallback_reason": self.fallback_reason,
            "trace": list(self.trace),
        }
