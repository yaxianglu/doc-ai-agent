"""统一 capability 输出契约。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CapabilityResult:
    """能力层统一输出。"""

    type: str
    data: object
    evidence: dict = field(default_factory=dict)
    confidence: float = 0.0
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "data": self.data,
            "evidence": dict(self.evidence),
            "confidence": self.confidence,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_query_result(cls, result) -> "CapabilityResult":
        """把 QueryResult 适配为统一 capability 输出。"""
        evidence = dict(getattr(result, "evidence", {}) or {})
        confidence = float(evidence.get("confidence") or evidence.get("overall_confidence") or 0.0)
        result_type = str(evidence.get("query_type") or evidence.get("capability_type") or "data_query")
        return cls(
            type=result_type,
            data=getattr(result, "data", None),
            evidence=evidence,
            confidence=confidence,
            meta={"answer": getattr(result, "answer", "")},
        )

    @classmethod
    def from_advice_result(cls, result) -> "CapabilityResult":
        """把 AdviceResult 适配为统一 capability 输出。"""
        sources = list(getattr(result, "sources", []) or [])
        mode = str(getattr(result, "generation_mode", "") or "")
        return cls(
            type="advice" if "为什么" not in str(getattr(result, "answer", "")) else "reasoning",
            data={"answer": getattr(result, "answer", ""), "sources": sources},
            evidence={"sources": sources, "generation_mode": mode},
            confidence=0.75 if mode == "llm" else 0.9,
            meta={"model": str(getattr(result, "model", "") or "")},
        )
