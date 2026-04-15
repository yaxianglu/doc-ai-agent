"""结构化响应构建器：先收口结构化答案，再交给自然语言层渲染。"""

from __future__ import annotations


class ResponseBuilder:
    """把多阶段执行结果统一组织成稳定的结构化答案对象。"""

    @staticmethod
    def _extract_sections(answer: str) -> dict:
        normalized = str(answer or "")
        sections = {
            "conclusion": "",
            "reason": "",
            "forecast": "",
            "evidence": "",
            "advice": "",
        }
        labels = [("结论：", "conclusion"), ("原因：", "reason"), ("预测：", "forecast"), ("依据：", "evidence"), ("建议：", "advice")]
        for index, (label, key) in enumerate(labels):
            start = normalized.find(label)
            if start < 0:
                continue
            start += len(label)
            end = len(normalized)
            for next_label, _ in labels[index + 1 :]:
                next_index = normalized.find(next_label, start)
                if next_index >= 0:
                    end = min(end, next_index)
            sections[key] = normalized[start:end].strip()
        return sections

    def build(
        self,
        *,
        question: str,
        answer: str,
        response_mode: str,
        answer_form: str = "",
        analysis_context: dict | None = None,
        historical_data=None,
        forecast_data=None,
        evidence_items: list[str] | None = None,
    ) -> dict:
        sections = self._extract_sections(answer)
        return {
            "question": str(question or ""),
            "summary": str(answer or ""),
            "response_mode": str(response_mode or ""),
            "answer_form": str(answer_form or ""),
            "analysis_context": dict(analysis_context or {}),
            "historical_data": list(historical_data or []),
            "forecast_data": list(forecast_data or []),
            "evidence": [str(item) for item in (evidence_items or []) if str(item).strip()],
            "sections": sections,
        }
