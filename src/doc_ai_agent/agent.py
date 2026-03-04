from __future__ import annotations

from .advice_engine import AdviceEngine
from .intent_router import IntentRouter
from .query_planner import QueryPlanner
from .query_engine import QueryEngine
from .repository import AlertRepository


class DocAIAgent:
    def __init__(
        self,
        repo: AlertRepository,
        llm_client=None,
        router_model: str = "",
        advice_model: str = "",
        source_provider=None,
    ):
        self.repo = repo
        self.query_engine = QueryEngine(repo)
        self.advice_engine = AdviceEngine(
            llm_client=llm_client,
            model=advice_model,
            source_provider=source_provider,
        )
        self.intent_router = None
        if llm_client and router_model:
            self.intent_router = IntentRouter(llm_client, router_model)
        self.query_planner = QueryPlanner(self.intent_router)

    def answer(self, question: str) -> dict:
        plan = self.query_planner.plan(question)
        route = plan.get("route")

        if plan.get("intent") == "data_query":
            result = self.query_engine.answer(question, plan=route)
            return {
                "mode": "data_query",
                "answer": result.answer,
                "data": result.data,
                "evidence": result.evidence,
            }

        if plan.get("needs_clarification"):
            return {
                "mode": "advice",
                "answer": plan.get("clarification"),
                "data": [],
                "evidence": {"generation_mode": "clarification", "confidence": plan.get("confidence", 0.0)},
            }

        result = self.advice_engine.answer(question)
        evidence = {
            "sources": result.sources,
            "generation_mode": result.generation_mode,
        }
        if result.model:
            evidence["model"] = result.model
        return {
            "mode": "advice",
            "answer": result.answer,
            "data": [],
            "evidence": evidence,
        }
