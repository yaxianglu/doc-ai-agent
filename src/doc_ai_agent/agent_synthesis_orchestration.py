"""回复合成编排：拼装解释、建议和最终分析回答。"""

from __future__ import annotations

from .agri_semantics import extract_crop_hint, extract_scene_hint
from .agent_contracts import AnalysisResponseEnvelope, AnalysisSynthesisPayload
from .answer_style import (
    compose_analysis_answer,
    format_answer_section,
    polish_advice_text,
    polish_conclusion_text,
    polish_explanation_text,
)
from .response_assembler import build_evidence_layers


def first_region_name(response: dict) -> str:
    """从查询结果里提取最适合作为回答主语的地区名。"""
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
    """构建解释/建议共享的上下文，统一字段口径。"""
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
    crop = extract_crop_hint(question, str(plan_context.get("crop") or ""))
    scene = extract_scene_hint(question, str(plan_context.get("scene") or ""))
    if crop:
        plan_context["crop"] = crop
    if scene:
        plan_context["scene"] = scene
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
    reasoning_capability=None,
) -> tuple[str, list]:
    """优先使用数据驱动解释，必要时回退到 advice 引擎。"""
    if not understanding.get("needs_explanation"):
        return "", []
    historical_evidence = dict(query_result.get("evidence") or {})
    no_data_reasons = list(historical_evidence.get("no_data_reasons") or [])
    explanation_text = build_data_grounded_explanation(
        plan_context=plan_context,
        query_result=query_result,
        forecast_result=forecast_result,
        knowledge=knowledge,
    )
    if explanation_text:
        if reasoning_capability is not None:
            capability = reasoning_capability.execute(
                plan_context=plan_context,
                query_result=query_result,
                forecast_result=forecast_result,
                knowledge=knowledge,
                grounded_answer=explanation_text,
            )
            return str(capability.data.get("answer") or ""), list(capability.data.get("sources") or knowledge)
        return explanation_text, knowledge
    if no_data_reasons:
        region_name = str(plan_context.get("region_name") or "当前地区")
        return (
            f"当前证据不足：缺少足够的结构化监测证据，暂时不能可靠判断{region_name}这段时间异常背后的主要原因；"
            "建议先确认该地区在所问时间窗内是否存在有效监测记录，再继续分析。"
            " 待核查：原始监测点位、时间窗、阈值口径和现场处置记录是否匹配。",
            knowledge,
        )
    if reasoning_capability is not None:
        capability = reasoning_capability.execute(
            plan_context=plan_context,
            query_result=query_result,
            forecast_result=forecast_result,
            knowledge=knowledge,
        )
        return str(capability.data.get("answer") or ""), list(capability.data.get("sources") or [])
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
    advice_capability=None,
) -> tuple[str, list]:
    """优先使用数据驱动建议，必要时回退到 advice 引擎。"""
    if not understanding.get("needs_advice"):
        return "", []
    advice_text = build_data_grounded_advice(
        plan_context=plan_context,
        query_result=query_result,
        forecast_result=forecast_result,
    )
    if advice_text:
        if advice_capability is not None:
            capability = advice_capability.execute(
                plan_context=plan_context,
                query_result=query_result,
                forecast_result=forecast_result,
                knowledge=knowledge,
                grounded_answer=advice_text,
            )
            return str(capability.data.get("answer") or ""), list(capability.data.get("sources") or knowledge)
        return advice_text, knowledge
    if advice_capability is not None:
        capability = advice_capability.execute(
            plan_context=plan_context,
            query_result=query_result,
            forecast_result=forecast_result,
            knowledge=knowledge,
        )
        return str(capability.data.get("answer") or ""), list(capability.data.get("sources") or [])
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
    """把结论、原因、预测、依据、建议拼成完整分析回答。"""
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
    knowledge_policy: dict | None,
    explanation_text: str,
    explanation_sources: list,
    advice_text: str,
    advice_sources: list,
) -> dict:
    """合成 analysis 模式响应，并拼接统一 evidence。"""
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
        knowledge_policy=dict(knowledge_policy or {}),
        evidence_layers=build_evidence_layers(
            query_result=query_result,
            forecast_result=forecast_result,
            knowledge=knowledge,
            knowledge_policy=knowledge_policy,
            analysis_context=plan_context,
        ),
        generation_mode="analysis_synthesis",
        context_trace=list(plan.get("context_trace") or []),
    )
    return AnalysisResponseEnvelope(
        answer=answer,
        historical_data=query_result.get("data"),
        forecast_data=forecast_result.get("data"),
        payload=payload,
    ).to_response()
