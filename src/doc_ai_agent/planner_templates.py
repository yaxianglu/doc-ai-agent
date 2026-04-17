"""受限规划模板：约束 planner 输出到固定 plan_type 集合。"""

from __future__ import annotations

from dataclasses import dataclass

PLAN_TYPES = {
    "fact_query",
    "trend_query",
    "ranking_query",
    "forecast_query",
    "explanation_query",
    "advice_query",
    "clarify_query",
}

TASK_TEMPLATES = {
    "rank",
    "detail",
    "overview",
    "trend",
    "compare",
    "forecast",
    "reason",
    "advice",
    "clarify",
    "merge",
}


@dataclass(frozen=True)
class PlannerTemplateDecision:
    """受限规划模板决策。"""

    plan_type: str
    required_slots: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "plan_type": self.plan_type,
            "required_slots": list(self.required_slots),
        }


def infer_plan_type(
    *,
    intent: str,
    route: dict,
    answer_mode: str,
    needs_clarification: bool,
    needs_explanation: bool,
    needs_advice: bool,
    needs_forecast: bool,
) -> PlannerTemplateDecision:
    """根据当前 plan 信号收敛为固定 plan_type。"""

    query_type = str((route or {}).get("query_type") or "")
    if needs_clarification:
        return PlannerTemplateDecision("clarify_query", ())
    if needs_forecast or query_type.endswith("_forecast") or answer_mode == "forecast":
        return PlannerTemplateDecision("forecast_query", ("domain", "future_window"))
    if answer_mode == "ranking" or query_type.endswith("_top") or query_type in {"joint_risk", "alerts_high_pest_low", "pest_high_alerts_low"}:
        return PlannerTemplateDecision("ranking_query", ("domain",))
    if answer_mode == "trend" or query_type.endswith("_trend"):
        return PlannerTemplateDecision("trend_query", ("domain", "historical_window"))
    if needs_explanation:
        return PlannerTemplateDecision("explanation_query", ("domain",))
    if intent == "advice" or needs_advice:
        return PlannerTemplateDecision("advice_query", ())
    return PlannerTemplateDecision("fact_query", ("domain",))


def normalize_task_template(template: str) -> str:
    """把任务模板约束到允许集合。"""

    normalized = str(template or "")
    if normalized in TASK_TEMPLATES:
        return normalized
    return "merge"
