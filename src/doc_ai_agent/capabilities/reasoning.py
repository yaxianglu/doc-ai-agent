"""Reasoning Capability：统一承载原因解释与多信号推理。"""

from __future__ import annotations

from ..capability_result import CapabilityResult


class ReasoningCapability:
    """解释与交叉信号推理能力。"""

    CROSS_SIGNAL_QUERY_TYPES = {"joint_risk", "alerts_high_pest_low", "pest_high_alerts_low", "cross_domain_compare"}

    def __init__(self, advice_engine):
        self.advice_engine = advice_engine

    def execute(
        self,
        *,
        plan_context: dict,
        query_result: dict,
        forecast_result: dict,
        knowledge: list[dict],
        grounded_answer: str = "",
    ) -> CapabilityResult:
        query_type = str((query_result.get("evidence") or {}).get("query_type") or "")
        mode = "multi_signal_reasoning" if query_type in self.CROSS_SIGNAL_QUERY_TYPES else "single_factor_explanation"
        if grounded_answer:
            return CapabilityResult(
                type="reasoning",
                data={"answer": grounded_answer, "sources": list(knowledge)},
                evidence={"mode": mode, "sources": list(knowledge), "query_type": query_type},
                confidence=0.88,
                meta={"generation_mode": "grounded"},
            )
        result = self.advice_engine.answer("为什么", context=plan_context)
        return CapabilityResult(
            type="reasoning",
            data={"answer": result.answer, "sources": list(result.sources)},
            evidence={"mode": mode, "sources": list(result.sources), "query_type": query_type},
            confidence=0.78 if result.generation_mode == "llm" else 0.9,
            meta={"generation_mode": result.generation_mode, "model": result.model},
        )
