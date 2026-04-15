"""结构化响应构建器：先收口结构化答案，再交给自然语言层渲染。"""

from __future__ import annotations


class ResponseBuilder:
    """把多阶段执行结果统一组织成稳定的结构化答案对象。"""

    def build(
        self,
        *,
        question: str,
        answer: str,
        response_mode: str,
        analysis_context: dict | None = None,
        historical_data=None,
        forecast_data=None,
        evidence_items: list[str] | None = None,
    ) -> dict:
        return {
            "question": str(question or ""),
            "summary": str(answer or ""),
            "response_mode": str(response_mode or ""),
            "analysis_context": dict(analysis_context or {}),
            "historical_data": list(historical_data or []),
            "forecast_data": list(forecast_data or []),
            "evidence": [str(item) for item in (evidence_items or []) if str(item).strip()],
        }
