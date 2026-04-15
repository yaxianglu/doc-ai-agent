"""Advice Capability：基于证据的建议能力统一出口。"""

from __future__ import annotations

from ..capability_result import CapabilityResult


class AdviceCapability:
    """建议能力。"""

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
        if grounded_answer:
            return CapabilityResult(
                type="advice",
                data={"answer": grounded_answer, "sources": list(knowledge)},
                evidence={"sources": list(knowledge), "has_forecast": bool(forecast_result.get("forecast"))},
                confidence=0.9,
                meta={"generation_mode": "grounded"},
            )
        result = self.advice_engine.answer("给建议", context=plan_context)
        return CapabilityResult(
            type="advice",
            data={"answer": result.answer, "sources": list(result.sources)},
            evidence={"sources": list(result.sources), "has_forecast": bool(forecast_result.get("forecast"))},
            confidence=0.78 if result.generation_mode == "llm" else 0.9,
            meta={"generation_mode": result.generation_mode, "model": result.model},
        )
