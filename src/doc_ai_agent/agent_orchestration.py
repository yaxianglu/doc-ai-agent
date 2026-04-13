from __future__ import annotations

from dataclasses import dataclass

from .agent_contracts import PlanPayload, RequestUnderstandingPayload


@dataclass(frozen=True)
class PlanNodeOutcome:
    plan: dict
    understanding: dict


def resolve_planning_question(question: str, understanding: dict) -> str:
    payload = RequestUnderstandingPayload.from_dict(understanding)
    if (
        payload.used_context
        and payload.needs_explanation
        and not payload.needs_historical
        and not payload.needs_forecast
        and not payload.needs_advice
    ):
        return question
    if payload.needs_historical:
        return payload.historical_query_text or question
    return payload.normalized_question or question


def should_build_direct_forecast_plan(understanding: dict) -> bool:
    payload = RequestUnderstandingPayload.from_dict(understanding)
    return bool(
        payload.needs_forecast
        and not payload.needs_historical
        and payload.domain
    )


def update_plan_outcome(*, plan: dict, understanding: dict) -> PlanNodeOutcome:
    plan_payload = PlanPayload.from_dict(plan)
    understanding_payload = RequestUnderstandingPayload.from_dict(understanding)
    route = dict(plan_payload.route)
    if route.get("query_type") in {"pest_forecast", "soil_forecast"} and not understanding_payload.needs_forecast:
        updated_understanding = understanding_payload.to_dict()
        updated_understanding["needs_forecast"] = True
        updated_understanding["needs_historical"] = False
        execution_plan = list(
            plan_payload.task_graph.get("execution_plan")
            or updated_understanding.get("execution_plan")
            or ["understand_request", "answer_synthesis"]
        )
        if "forecast" not in execution_plan:
            if "answer_synthesis" in execution_plan:
                execution_plan.insert(execution_plan.index("answer_synthesis"), "forecast")
            else:
                execution_plan.append("forecast")
        updated_understanding["execution_plan"] = execution_plan
        return PlanNodeOutcome(plan=plan_payload.to_dict(), understanding=updated_understanding)
    return PlanNodeOutcome(plan=plan_payload.to_dict(), understanding=understanding_payload.to_dict())


def route_target(plan: dict, understanding: dict) -> str:
    plan_payload = PlanPayload.from_dict(plan)
    understanding_payload = RequestUnderstandingPayload.from_dict(understanding)
    if plan_payload.needs_clarification:
        return "clarify"
    if (
        plan_payload.intent == "advice"
        and not understanding_payload.needs_historical
        and not understanding_payload.needs_forecast
    ):
        return "advice"
    if (
        understanding_payload.needs_historical
        or understanding_payload.needs_forecast
        or understanding_payload.needs_explanation
        or understanding_payload.needs_advice
        or plan_payload.intent == "data_query"
    ):
        return "analysis"
    if plan_payload.intent == "advice":
        return "advice"
    return "analysis"
