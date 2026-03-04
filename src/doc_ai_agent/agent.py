from __future__ import annotations

from .advice_engine import AdviceEngine
from .intent_router import IntentRouter
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

    def answer(self, question: str) -> dict:
        route = None
        if self.intent_router is not None:
            route = self.intent_router.route(question)

        if route and route.get("intent") == "data_query":
            result = self.query_engine.answer(question, plan=route)
            return {
                "mode": "data_query",
                "answer": result.answer,
                "data": result.data,
                "evidence": result.evidence,
            }

        if route and route.get("intent") == "advice":
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

        force_data_query = any(
            k in question
            for k in [
                "多少",
                "top",
                "TOP",
                "Top",
                "统计",
                "哪几个",
                "平均",
                "分组",
                "连续两天",
                "设备",
                "最多",
                "最高",
                "超过",
                "最近一次",
                "sms_content",
                "占比",
                "变化",
            ]
        ) or ("处置建议" in question and ("镇" in question or "街道" in question))

        if "短信版本" in question or ("改写" in question and "处置建议" in question):
            force_data_query = False

        if force_data_query:
            result = self.query_engine.answer(question)
            return {
                "mode": "data_query",
                "answer": result.answer,
                "data": result.data,
                "evidence": result.evidence,
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
