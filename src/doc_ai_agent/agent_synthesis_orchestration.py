from __future__ import annotations

from .agent_contracts import AnalysisResponseEnvelope, AnalysisSynthesisPayload
from .answer_style import (
    compose_analysis_answer,
    format_answer_section,
    polish_advice_text,
    polish_conclusion_text,
    polish_explanation_text,
)


def first_region_name(response: dict) -> str:
    data = response.get("data")
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return str(
                first.get("region_name")
                or first.get("county_name")
                or first.get("city_name")
                or first.get("name")
                or ""
            )
    return ""


def build_plan_context(
    *,
    question: str,
    understanding: dict,
    plan: dict,
    memory_context: dict | None,
    query_result: dict,
    forecast_result: dict,
    build_runtime_context,
) -> dict:
    plan_context = build_runtime_context(
        understanding.get("normalized_question") or question,
        plan,
        previous_context=memory_context,
        understanding=understanding,
    )
    if forecast_result.get("analysis_context", {}).get("region_name"):
        plan_context["region_name"] = forecast_result["analysis_context"]["region_name"]
    elif not plan_context.get("region_name") and first_region_name(query_result):
        plan_context["region_name"] = first_region_name(query_result)
    if forecast_result.get("forecast"):
        plan_context["forecast"] = forecast_result["forecast"]
    return plan_context


def build_explanation_payload(
    *,
    understanding: dict,
    plan_context: dict,
    query_result: dict,
    forecast_result: dict,
    knowledge: list[dict],
    build_data_grounded_explanation,
    advice_engine,
) -> tuple[str, list]:
    if not understanding.get("needs_explanation"):
        return "", []
    explanation_text = build_data_grounded_explanation(
        plan_context=plan_context,
        query_result=query_result,
        forecast_result=forecast_result,
        knowledge=knowledge,
    )
    if explanation_text:
        return explanation_text, knowledge
    explanation_result = advice_engine.answer("为什么", context=plan_context)
    return explanation_result.answer, explanation_result.sources


def build_advice_payload(
    *,
    understanding: dict,
    plan_context: dict,
    query_result: dict,
    forecast_result: dict,
    knowledge: list[dict],
    build_data_grounded_advice,
    advice_engine,
) -> tuple[str, list]:
    if not understanding.get("needs_advice"):
        return "", []
    advice_text = build_data_grounded_advice(
        plan_context=plan_context,
        query_result=query_result,
        forecast_result=forecast_result,
    )
    if advice_text:
        return advice_text, knowledge
    advice_result = advice_engine.answer("给建议", context=plan_context)
    return advice_result.answer, advice_result.sources


def build_analysis_answer(
    *,
    query_result: dict,
    explanation_text: str,
    forecast_result: dict,
    knowledge: list[dict],
    advice_text: str,
) -> str:
    sections: list[str] = []
    if query_result.get("answer"):
        sections.append(format_answer_section("结论", polish_conclusion_text(query_result["answer"])))
    if explanation_text:
        polished_explanation = polish_explanation_text(explanation_text)
        if polished_explanation.startswith("原因：") or polished_explanation.startswith("依据："):
            sections.append(polished_explanation)
        else:
            sections.append(format_answer_section("原因", polished_explanation))
    if forecast_result.get("answer"):
        sections.append(format_answer_section("预测", forecast_result["answer"]))
    if knowledge:
        titles = "；".join(str(item.get("title") or "") for item in knowledge[:2] if item.get("title"))
        if titles:
            sections.append(format_answer_section("依据", f"参考 {titles}"))
    if advice_text:
        sections.append(format_answer_section("建议", polish_advice_text(advice_text)))
    return compose_analysis_answer(sections) if sections else (query_result.get("answer") or advice_text or "当前暂无可综合输出的结果。")


def synthesize_analysis_response(
    *,
    execution_plan: list[str],
    understanding: dict,
    plan: dict,
    plan_context: dict,
    query_result: dict,
    forecast_result: dict,
    knowledge: list[dict],
    explanation_text: str,
    explanation_sources: list,
    advice_text: str,
    advice_sources: list,
) -> dict:
    answer = build_analysis_answer(
        query_result=query_result,
        explanation_text=explanation_text,
        forecast_result=forecast_result,
        knowledge=knowledge,
        advice_text=advice_text,
    )
    payload = AnalysisSynthesisPayload(
        execution_plan=list(execution_plan),
        request_understanding=dict(understanding),
        analysis_context=dict(plan_context),
        historical_query=dict(query_result.get("evidence") or {}),
        forecast=dict(forecast_result.get("forecast") or {}),
        knowledge=list(knowledge),
        knowledge_sources=list(advice_sources or explanation_sources or knowledge),
        generation_mode="analysis_synthesis",
        context_trace=list(plan.get("context_trace") or []),
    )
    return AnalysisResponseEnvelope(
        answer=answer,
        historical_data=query_result.get("data"),
        forecast_data=forecast_result.get("data"),
        payload=payload,
    ).to_response()
