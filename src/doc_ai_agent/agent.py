from __future__ import annotations

import re
from uuid import uuid4
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .advice_engine import AdviceEngine
from .forecast_engine import ForecastEngine
from .forecast_service import ForecastService
from .intent_router import IntentRouter
from .letta_memory import LocalMemoryStore, LettaMemoryStore, ResilientMemoryStore
from .query_playbook_router import create_query_playbook_router
from .query_planner import QueryPlanner
from .query_engine import QueryEngine
from .request_understanding import CITY_ALIASES as REQUEST_CITY_ALIASES, RequestUnderstanding
from .repository import AlertRepository
from .task_decomposition import build_task_graph


class AgentState(TypedDict, total=False):
    question: str
    history: list[dict[str, str]]
    thread_id: str
    memory_context: dict
    understanding: dict
    plan: dict
    query_result: dict
    forecast_result: dict
    knowledge: list[dict]
    response: dict


class DocAIAgent:
    def __init__(
        self,
        repo: AlertRepository,
        llm_client=None,
        router_model: str = "",
        advice_model: str = "",
        source_provider=None,
        query_playbook_router=None,
        understanding_backend=None,
        memory_store_path: str = "./data/agent-memory.json",
        letta_base_url: str = "",
        letta_api_key: str = "",
        letta_block_prefix: str = "doc-cloud-thread",
    ):
        self.repo = repo
        self.router_model = router_model
        self.advice_model = advice_model
        self.query_engine = QueryEngine(repo)
        self.forecast_engine = ForecastEngine(repo)
        self.forecast_service = ForecastService(repo)
        self.source_provider = source_provider
        self.advice_engine = AdviceEngine(
            llm_client=llm_client,
            model=advice_model,
            source_provider=source_provider,
        )
        self.intent_router = None
        if llm_client and router_model:
            self.intent_router = IntentRouter(llm_client, router_model)
        self.query_playbook_router = query_playbook_router or create_query_playbook_router()
        self.query_planner = QueryPlanner(self.intent_router, self.query_playbook_router)
        self.request_understanding = RequestUnderstanding(backend=understanding_backend)
        self.memory_store = self._build_memory_store(
            memory_store_path=memory_store_path,
            letta_base_url=letta_base_url,
            letta_api_key=letta_api_key,
            letta_block_prefix=letta_block_prefix,
        )
        self.graph = self._build_graph()

    @staticmethod
    def _build_memory_store(memory_store_path: str, letta_base_url: str, letta_api_key: str, letta_block_prefix: str):
        fallback = LocalMemoryStore(memory_store_path)
        if not letta_base_url:
            return ResilientMemoryStore(None, fallback)
        try:
            from letta_client import Letta

            client = Letta(base_url=letta_base_url, api_key=letta_api_key or None)
            primary = LettaMemoryStore(client, block_prefix=letta_block_prefix)
            return ResilientMemoryStore(primary, fallback)
        except Exception:
            return ResilientMemoryStore(None, fallback)

    def _build_graph(self):
        workflow = StateGraph(AgentState)
        workflow.add_node("load_memory", self._load_memory_node)
        workflow.add_node("understand_request", self._understand_request_node)
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("query", self._query_node)
        workflow.add_node("forecast", self._forecast_node)
        workflow.add_node("knowledge", self._knowledge_node)
        workflow.add_node("synthesize", self._synthesize_node)
        workflow.add_node("advice", self._advice_node)
        workflow.add_node("clarify", self._clarify_node)
        workflow.add_node("persist", self._persist_node)
        workflow.add_edge(START, "load_memory")
        workflow.add_edge("load_memory", "understand_request")
        workflow.add_edge("understand_request", "plan")
        workflow.add_conditional_edges(
            "plan",
            self._route_from_plan,
            {
                "analysis": "query",
                "advice": "advice",
                "clarify": "clarify",
            },
        )
        workflow.add_edge("query", "forecast")
        workflow.add_edge("forecast", "knowledge")
        workflow.add_edge("knowledge", "synthesize")
        workflow.add_edge("synthesize", "persist")
        workflow.add_edge("advice", "persist")
        workflow.add_edge("clarify", "persist")
        workflow.add_edge("persist", END)
        return workflow.compile()

    @staticmethod
    def _format_model_name(model: str) -> str:
        if not model:
            return ""
        if model.startswith("gpt-"):
            return "GPT-" + model[4:]
        return model

    def _repo_label(self) -> str:
        return "MySQL" if self.repo.__class__.__name__ == "MySQLRepository" else "SQLite"

    def _intent_recognition_label(self, plan: dict) -> tuple[str, bool]:
        if str(plan.get("reason", "")).startswith("router_") and self.router_model:
            return self._format_model_name(self.router_model), True
        return "规则判定", False

    def _data_query_label(self, response: dict) -> str:
        if response.get("mode") == "analysis":
            return "SQL + Forecast + RAG"
        if response.get("mode") != "data_query":
            return "未使用"
        evidence = response.get("evidence") or {}
        forecast = evidence.get("forecast") if isinstance(evidence, dict) else None
        if isinstance(forecast, dict) and forecast.get("domain"):
            return f"Forecast / {forecast['domain']}"
        sql = evidence.get("sql") if isinstance(evidence, dict) else None
        if isinstance(sql, str) and sql:
            operation = "SQL" if "SELECT" in sql.upper() else sql
            return f"{self._repo_label()} / {operation}"
        return f"{self._repo_label()} / 查询"

    @staticmethod
    def _retrieval_label(response: dict) -> str:
        evidence = response.get("evidence") or {}
        for key in ["knowledge_sources", "knowledge", "sources"]:
            items = evidence.get(key) if isinstance(evidence, dict) else None
            if isinstance(items, list) and items:
                first = items[0] if isinstance(items[0], dict) else {}
                backend = str(first.get("retrieval_backend") or first.get("retrieval_engine") or "")
                strategy = str(first.get("retrieval_strategy") or "")
                if backend:
                    backend_label = backend.replace("-", " ").title().replace(" ", "")
                    if backend == "qdrant":
                        backend_label = "Qdrant"
                    elif backend == "llamaindex":
                        backend_label = "LlamaIndex"
                    elif backend == "static":
                        backend_label = "Static"
                    elif backend == "qdrant-fallback":
                        backend_label = "QdrantFallback"
                    elif backend == "llamaindex-fallback":
                        backend_label = "LlamaIndexFallback"
                    return f"{backend_label} / {strategy or 'retrieval'}"
        return "未使用"

    def _answer_generation_label(self, response: dict) -> tuple[str, bool]:
        if response.get("mode") == "analysis":
            return "综合回答", False
        if response.get("mode") == "data_query":
            evidence = response.get("evidence") or {}
            if isinstance(evidence, dict) and evidence.get("forecast"):
                return "预测回答", False
            return "模板回答", False

        evidence = response.get("evidence") or {}
        generation_mode = evidence.get("generation_mode") if isinstance(evidence, dict) else None
        model = evidence.get("model") if isinstance(evidence, dict) else None

        if generation_mode == "clarification":
            return "澄清回复", False
        if generation_mode == "llm":
            return self._format_model_name(str(model or self.advice_model)), True
        if generation_mode == "rule":
            return "规则回答", False
        return "未知", False

    @staticmethod
    def _ai_involvement_label(used_ai_in_routing: bool, used_ai_in_answer: bool) -> str:
        ai_steps = int(used_ai_in_routing) + int(used_ai_in_answer)
        if ai_steps >= 2:
            return "高"
        if ai_steps == 1:
            return "中"
        return "低"

    def _attach_processing(self, response: dict, plan: dict) -> dict:
        intent_recognition, used_ai_in_routing = self._intent_recognition_label(plan)
        answer_generation, used_ai_in_answer = self._answer_generation_label(response)
        response["processing"] = {
            "intent_recognition": intent_recognition,
            "data_query": self._data_query_label(response),
            "retrieval": self._retrieval_label(response),
            "answer_generation": answer_generation,
            "ai_involvement": self._ai_involvement_label(used_ai_in_routing, used_ai_in_answer),
            "orchestration": "LangGraph",
            "memory": self.memory_store.backend_label(),
        }
        return response

    def _load_memory_node(self, state: AgentState) -> dict:
        thread_id = str(state.get("thread_id") or "default")
        persisted = {} if thread_id.startswith("__stateless__:") else self.memory_store.load(thread_id)
        return {
            "thread_id": thread_id,
            "memory_context": dict(persisted),
            "understanding": {},
            "plan": {},
            "query_result": {},
            "forecast_result": {},
            "knowledge": [],
            "response": {},
        }

    def _understand_request_node(self, state: AgentState) -> dict:
        understanding = self.request_understanding.analyze(
            state.get("question", ""),
            history=state.get("history"),
            context=state.get("memory_context"),
        )
        return {"understanding": understanding}

    @staticmethod
    def _asks_region_ranking(question: str) -> bool:
        return any(token in question for token in ["哪里", "哪儿", "哪些地区", "哪些地方", "最严重的地方"])

    @staticmethod
    def _infer_region_level_from_name(region_name: str) -> str:
        normalized = str(region_name or "")
        if normalized.endswith(("县", "区")):
            return "county"
        if normalized.endswith("市"):
            return "city"
        return ""

    def _build_forecast_plan_from_understanding(self, understanding: dict, memory_context: dict | None = None) -> dict:
        memory_context = dict(memory_context or {})
        domain = understanding.get("domain") or memory_context.get("domain") or ""
        future_window = understanding.get("future_window") or {"horizon_days": 14}
        inherited_region = memory_context.get("region_name") if understanding.get("reuse_region_from_context") else None
        region_name = understanding.get("region_name") or inherited_region or None
        region_level = (
            understanding.get("region_level")
            or str((memory_context.get("route") or {}).get("region_level") or "")
            or self._infer_region_level_from_name(str(region_name or ""))
            or "city"
        )
        route = {
            "query_type": f"{domain}_forecast" if domain else "count",
            "since": memory_context.get("route", {}).get("since") or "1970-01-01 00:00:00",
            "until": None,
            "city": region_name if region_level != "county" else None,
            "county": region_name if region_level == "county" else None,
            "device_code": None,
            "region_level": region_level,
            "window": understanding.get("window") or memory_context.get("window") or {"window_type": "all", "window_value": None},
            "forecast_window": future_window,
            "forecast_mode": "ranking" if self._asks_region_ranking(understanding.get("original_question", "")) and not region_name else "region",
        }
        return {
            "intent": "data_query",
            "confidence": 0.86,
            "route": route,
            "needs_clarification": False,
            "clarification": None,
            "reason": "understanding_forecast_direct",
            "context_trace": ["request understanding selected direct forecast route"],
        }

    def _plan_node(self, state: AgentState) -> dict:
        understanding = dict(state.get("understanding") or {})
        if (
            understanding.get("used_context")
            and understanding.get("needs_explanation")
            and not understanding.get("needs_historical")
            and not understanding.get("needs_forecast")
            and not understanding.get("needs_advice")
        ):
            question_for_planning = state.get("question", "")
        elif understanding.get("needs_historical"):
            question_for_planning = understanding.get("historical_query_text")
        else:
            question_for_planning = understanding.get("normalized_question") or state.get("question", "")
        if understanding.get("needs_forecast") and not understanding.get("needs_historical") and understanding.get("domain"):
            plan = self._build_forecast_plan_from_understanding(understanding, state.get("memory_context"))
        else:
            plan = self.query_planner.plan(
                question_for_planning,
                history=state.get("history"),
                context=state.get("memory_context"),
                understanding=understanding,
            )
        plan = dict(plan)
        plan["task_graph"] = build_task_graph(plan.get("query_plan") or {})
        route = dict(plan.get("route") or {})
        if route.get("query_type") in {"pest_forecast", "soil_forecast"} and not understanding.get("needs_forecast"):
            updated_understanding = dict(understanding)
            updated_understanding["needs_forecast"] = True
            updated_understanding["needs_historical"] = False
            execution_plan = list(updated_understanding.get("execution_plan") or ["understand_request", "answer_synthesis"])
            if "forecast" not in execution_plan:
                if "answer_synthesis" in execution_plan:
                    insert_at = execution_plan.index("answer_synthesis")
                    execution_plan.insert(insert_at, "forecast")
                else:
                    execution_plan.append("forecast")
            updated_understanding["execution_plan"] = execution_plan
            return {"plan": plan, "understanding": updated_understanding}
        return {"plan": plan}

    def _route_from_plan(self, state: AgentState) -> str:
        plan = state.get("plan") or {}
        understanding = state.get("understanding") or {}
        if plan.get("needs_clarification"):
            return "clarify"
        if (
            plan.get("intent") == "advice"
            and not understanding.get("needs_historical")
            and not understanding.get("needs_forecast")
        ):
            return "advice"
        if (
            understanding.get("needs_historical")
            or understanding.get("needs_forecast")
            or understanding.get("needs_explanation")
            or understanding.get("needs_advice")
            or plan.get("intent") == "data_query"
        ):
            return "analysis"
        if plan.get("intent") == "advice":
            return "advice"
        return "analysis"

    def _query_node(self, state: AgentState) -> dict:
        understanding = state.get("understanding") or {}
        plan = state.get("plan") or {}
        compare_request = self._detect_compare_request(
            state.get("question", ""),
            understanding,
            plan,
            state.get("memory_context"),
        )
        if compare_request:
            return {
                "query_result": self._answer_compare_request(
                    state.get("question", ""),
                    compare_request,
                    understanding,
                    plan,
                    state.get("memory_context"),
                )
            }
        if not understanding.get("needs_historical") and plan.get("intent") != "data_query":
            return {"query_result": {}}
        question_for_query = understanding.get("historical_query_text") or state.get("question", "")
        route = self._normalize_historical_route(
            question_for_query,
            dict(plan.get("route") or {}),
            understanding,
            state.get("memory_context"),
        )
        if route.get("query_type") in {"pest_forecast", "soil_forecast"}:
            return {"query_result": {}}
        result = self.query_engine.answer(question_for_query, plan=route)
        evidence = dict(result.evidence or {})
        evidence.setdefault("query_type", route.get("query_type") or "")
        evidence.setdefault("city", route.get("city"))
        evidence.setdefault("county", route.get("county"))
        evidence.setdefault("window", route.get("window") or {})
        return {
            "query_result": {
                "mode": "data_query",
                "answer": result.answer,
                "data": result.data,
                "evidence": evidence,
            }
        }

    def _resolve_forecast_context(self, state: AgentState) -> tuple[dict | None, dict]:
        understanding = dict(state.get("understanding") or {})
        if not understanding.get("needs_forecast"):
            return None, {}

        plan = dict(state.get("plan") or {})
        route = self._normalize_historical_route(
            understanding.get("historical_query_text") or state.get("question", ""),
            dict(plan.get("route") or {}),
            understanding,
            state.get("memory_context"),
        )
        query_result = dict(state.get("query_result") or {})
        memory_context = dict(state.get("memory_context") or {})
        future_window = understanding.get("future_window") or {"horizon_days": 14}
        domain = understanding.get("domain") or memory_context.get("domain") or self._derive_domain(state.get("question", ""), plan, memory_context)
        first_region = self._first_region_name(query_result) if query_result else ""
        inherited_region = memory_context.get("region_name") if understanding.get("reuse_region_from_context") else ""
        region_name = understanding.get("region_name") or route.get("county") or route.get("city") or inherited_region or first_region
        region_level = (
            understanding.get("region_level")
            or route.get("region_level")
            or str((memory_context.get("route") or {}).get("region_level") or "")
            or self._infer_region_level_from_name(str(region_name or ""))
            or "city"
        )
        forecast_mode = route.get("forecast_mode") or ("ranking" if not region_name and self._asks_region_ranking(understanding.get("original_question", "")) else "region")
        forecast_route = {
            "query_type": f"{domain}_forecast",
            "since": route.get("since") or memory_context.get("route", {}).get("since") or "1970-01-01 00:00:00",
            "until": route.get("until"),
            "city": region_name if region_level != "county" else None,
            "county": region_name if region_level == "county" else None,
            "region_level": region_level,
            "window": route.get("window") or understanding.get("window") or memory_context.get("window") or {"window_type": "all", "window_value": None},
            "forecast_window": future_window,
            "forecast_mode": forecast_mode,
        }
        runtime_context = {
            "domain": domain,
            "region_name": region_name or "",
            "region_level": region_level,
            "query_type": route.get("query_type") or memory_context.get("query_type") or "",
            "window": forecast_route["window"],
            "route": route or memory_context.get("route") or {},
            "forecast": memory_context.get("forecast") or {},
        }
        return forecast_route, runtime_context

    def _forecast_node(self, state: AgentState) -> dict:
        forecast_route, runtime_context = self._resolve_forecast_context(state)
        if not forecast_route:
            return {"forecast_result": {}}
        if forecast_route.get("forecast_mode") == "ranking":
            result = self.forecast_service.forecast_top_regions(
                domain=str(runtime_context.get("domain") or "pest"),
                since=str(forecast_route.get("since") or "1970-01-01 00:00:00"),
                horizon_days=int(forecast_route.get("forecast_window", {}).get("horizon_days") or 14),
                region_level=str(forecast_route.get("region_level") or "city"),
            )
        else:
            result = self.forecast_service.forecast_region(forecast_route, context=runtime_context)
        return {"forecast_result": result}

    def _knowledge_node(self, state: AgentState) -> dict:
        understanding = dict(state.get("understanding") or {})
        if not (understanding.get("needs_explanation") or understanding.get("needs_advice")):
            return {"knowledge": []}
        if self.source_provider is None:
            return {"knowledge": []}
        plan = state.get("plan") or {}
        query_result = state.get("query_result") or {}
        forecast_result = state.get("forecast_result") or {}
        context = self._build_runtime_context(
            understanding.get("normalized_question") or state.get("question", ""),
            plan,
            previous_context=state.get("memory_context"),
            understanding=understanding,
        )
        context["region_name"] = (
            forecast_result.get("analysis_context", {}).get("region_name")
            or context.get("region_name")
            or self._first_region_name(query_result)
        )
        if forecast_result.get("forecast"):
            context["forecast"] = forecast_result["forecast"]
        knowledge = self.source_provider.search(
            understanding.get("normalized_question") or state.get("question", ""),
            limit=3,
            context=context,
        )
        return {"knowledge": knowledge}

    def _derive_domain(self, question: str, plan: dict, previous_context: dict | None = None) -> str:
        previous_context = dict(previous_context or {})
        route = plan.get("route") or {}
        query_type = str(route.get("query_type") or "")
        if query_type.startswith("pest"):
            return "pest"
        if query_type.startswith("soil"):
            return "soil"
        if previous_context.get("domain"):
            return str(previous_context["domain"])
        if "虫" in question:
            return "pest"
        if "墒" in question:
            return "soil"
        return ""

    def _build_runtime_context(self, question: str, plan: dict, previous_context: dict | None = None, understanding: dict | None = None) -> dict:
        previous_context = dict(previous_context or {})
        understanding = dict(understanding or {})
        route = self._normalize_historical_route(
            understanding.get("historical_query_text") or question,
            dict(plan.get("route") or {}),
            understanding,
            previous_context,
        )
        if self.query_planner._is_greeting_question(question):
            return {
                "domain": "",
                "region_name": "",
                "region_level": "",
                "query_type": "",
                "window": {},
                "route": {},
                "forecast": {},
            }
        inherited_region = previous_context.get("region_name") if understanding.get("reuse_region_from_context", True) else ""
        return {
            "domain": self._derive_domain(question, plan, previous_context),
            "region_name": route.get("county") or route.get("city") or inherited_region or "",
            "region_level": route.get("region_level") or str((previous_context.get("route") or {}).get("region_level") or ""),
            "query_type": route.get("query_type") or previous_context.get("query_type") or "",
            "window": route.get("window") or previous_context.get("window") or {},
            "route": route or previous_context.get("route") or {},
            "forecast": previous_context.get("forecast") or {},
        }

    def _normalize_historical_route(
        self,
        question: str,
        route: dict,
        understanding: dict | None = None,
        previous_context: dict | None = None,
    ) -> dict:
        normalized = dict(route or {})
        understanding = dict(understanding or {})
        previous_context = dict(previous_context or {})
        query_text = understanding.get("resolved_question") or question
        base_route = dict(self.query_planner._build_route(query_text, str(normalized.get("query_type") or "structured_agri")))
        domain = understanding.get("domain") or self._derive_domain(query_text, {"route": normalized}, previous_context)
        region_name = str(understanding.get("region_name") or "")
        region_level = str(understanding.get("region_level") or "")
        task_type = str(understanding.get("task_type") or "")
        explicit_window = understanding.get("window") if isinstance(understanding.get("window"), dict) else {}

        if normalized.get("query_type") == "structured_agri" and domain in {"pest", "soil"}:
            if task_type == "data_detail":
                normalized["query_type"] = f"{domain}_detail"
            elif task_type == "trend":
                normalized["query_type"] = f"{domain}_trend"
            elif task_type == "ranking":
                normalized["query_type"] = f"{domain}_top"
            elif region_name:
                normalized["query_type"] = f"{domain}_overview"
            else:
                normalized["query_type"] = f"{domain}_top"

        if not normalized.get("city") and not normalized.get("county"):
            if region_name:
                resolved_region_level = region_level or self._infer_region_level_from_name(region_name) or "city"
                if resolved_region_level == "county":
                    normalized["county"] = region_name
                else:
                    normalized["city"] = region_name
                normalized["region_level"] = resolved_region_level
            elif base_route.get("city"):
                normalized["city"] = base_route.get("city")
                normalized["region_level"] = base_route.get("region_level") or normalized.get("region_level") or "city"
            elif base_route.get("county"):
                normalized["county"] = base_route.get("county")
                normalized["region_level"] = base_route.get("region_level") or normalized.get("region_level") or "county"

        current_window = normalized.get("window") if isinstance(normalized.get("window"), dict) else {}
        if (not current_window or current_window.get("window_type") in {"none", "all"}) and explicit_window:
            normalized["window"] = explicit_window
            current_window = explicit_window
        elif not current_window and base_route.get("window"):
            normalized["window"] = base_route.get("window")
            current_window = normalized["window"]

        if normalized.get("since") in {None, "", "1970-01-01 00:00:00"}:
            if current_window and current_window.get("window_type") not in {"none", "all"}:
                normalized["since"] = base_route.get("since") or normalized.get("since")
            elif normalized.get("since") in {None, ""}:
                normalized["since"] = base_route.get("since") or normalized.get("since")
        if normalized.get("until") in {None, ""} and base_route.get("until"):
            normalized["until"] = base_route.get("until")
        if not normalized.get("region_level") and base_route.get("region_level"):
            normalized["region_level"] = base_route.get("region_level")
        return normalized

    @staticmethod
    def _extract_all_regions(text: str) -> list[str]:
        normalized = RequestUnderstanding._normalize_city_mentions(text)
        hits: list[tuple[int, str]] = []
        for canonical in REQUEST_CITY_ALIASES.values():
            for match in re.finditer(re.escape(canonical), normalized):
                hits.append((match.start(), canonical))
        hits.sort(key=lambda item: item[0])
        regions: list[str] = []
        for _, region in hits:
            if region not in regions:
                regions.append(region)
        return regions

    def _detect_compare_request(
        self,
        question: str,
        understanding: dict | None,
        plan: dict | None,
        previous_context: dict | None,
    ) -> dict | None:
        text = str(question or "").strip()
        if not text:
            return None
        understanding = dict(understanding or {})
        plan = dict(plan or {})
        previous_context = dict(previous_context or {})
        compare_signal = any(token in text for token in ["对比", "比较", "相比", "哪个更突出", "哪个问题更突出"])
        if not compare_signal:
            return None

        regions = self._extract_all_regions(text)
        domain = understanding.get("domain") or self._derive_domain(text, plan, previous_context)
        task_type = str(understanding.get("task_type") or "")
        prefers_trend = task_type == "trend" or any(token in text for token in ["趋势", "走势", "走向", "变化", "波动"])
        prefers_detail = task_type == "data_detail"

        if len(regions) >= 2 and domain in {"pest", "soil"}:
            if prefers_detail:
                base_query_type = f"{domain}_detail"
            elif prefers_trend:
                base_query_type = f"{domain}_trend"
            else:
                base_query_type = f"{domain}_overview"
            return {
                "kind": "region_compare",
                "query_type": f"{domain}_compare",
                "base_query_type": base_query_type,
                "domain": domain,
                "regions": regions[:2],
            }

        cross_domain_signal = (
            len(regions) >= 1
            and any(token in text for token in ["虫情", "虫害"])
            and any(token in text for token in ["墒情", "缺水", "干旱"])
        )
        if cross_domain_signal:
            return {
                "kind": "cross_domain_compare",
                "query_type": "cross_domain_compare",
                "base_query_type": "trend" if prefers_trend else ("detail" if prefers_detail else "overview"),
                "region": regions[-1],
            }
        return None

    @staticmethod
    def _comparison_metric_key(domain: str) -> str:
        return "severity_score" if domain == "pest" else "avg_anomaly_score"

    @staticmethod
    def _comparison_domain_label(domain: str) -> str:
        return "虫情" if domain == "pest" else "墒情"

    @staticmethod
    def _comparison_trend(series: list[dict], key: str) -> str:
        if len(series) < 2:
            return "样本不足"
        first = float(series[0].get(key) or 0)
        last = float(series[-1].get(key) or 0)
        if last > first * 1.15:
            return "整体上升"
        if last < first * 0.85:
            return "整体下降"
        return "整体平稳"

    @staticmethod
    def _comparison_average(series: list[dict], key: str) -> float:
        if not series:
            return 0.0
        return sum(float(item.get(key) or 0) for item in series) / len(series)

    @staticmethod
    def _comparison_peak(series: list[dict], key: str) -> float:
        if not series:
            return 0.0
        return max(float(item.get(key) or 0) for item in series)

    @staticmethod
    def _comparison_latest(series: list[dict], key: str) -> float:
        if not series:
            return 0.0
        return float(series[-1].get(key) or 0)

    @staticmethod
    def _window_summary(window: dict | None) -> str:
        payload = dict(window or {})
        window_type = str(payload.get("window_type") or "")
        window_value = payload.get("window_value")
        if window_type == "months" and window_value:
            return f"过去{window_value}个月"
        if window_type == "weeks" and window_value:
            return f"过去{window_value}周"
        if window_type == "days" and window_value:
            return f"过去{window_value}天"
        return "当前时间窗"

    def _comparison_summary(self, domain: str, region_name: str, series: list[dict]) -> dict:
        key = self._comparison_metric_key(domain)
        return {
            "region_name": region_name,
            "domain": domain,
            "trend": self._comparison_trend(series, key),
            "average": self._comparison_average(series, key),
            "peak": self._comparison_peak(series, key),
            "latest": self._comparison_latest(series, key),
            "sample_days": len(series),
        }

    def _comparison_conclusion(self, left: dict, right: dict, left_label: str, right_label: str) -> str:
        left_score = (float(left.get("average") or 0), float(left.get("peak") or 0), float(left.get("latest") or 0))
        right_score = (float(right.get("average") or 0), float(right.get("peak") or 0), float(right.get("latest") or 0))
        if left_score == right_score:
            return f"综合看，{left_label}和{right_label}接近，没有明显一边更突出。"
        winner = left_label if left_score > right_score else right_label
        return f"综合看，{winner}更突出。"

    @staticmethod
    def _reasoning_metric_key(domain: str, series: list[dict]) -> tuple[str, str, str]:
        if domain == "soil" or any("avg_anomaly_score" in item for item in series):
            return "avg_anomaly_score", "异常值", "墒情"
        return "severity_score", "严重度", "虫情"

    @staticmethod
    def _reasoning_point_date(point: dict) -> str:
        return str(point.get("date") or point.get("bucket") or "")

    @staticmethod
    def _reasoning_format_metric(value: float) -> str:
        if float(value).is_integer():
            return f"{value:.0f}"
        return f"{value:.1f}"

    def _reasoning_series_summary(self, domain: str, series: list[dict]) -> dict:
        metric_key, metric_label, domain_label = self._reasoning_metric_key(domain, series)
        if not series:
            return {
                "domain_label": domain_label,
                "metric_label": metric_label,
                "trend": "样本不足",
                "average": 0.0,
                "peak_value": 0.0,
                "peak_date": "",
                "latest_value": 0.0,
                "latest_date": "",
                "active_days": 0,
                "sample_days": 0,
            }

        peak_point = max(series, key=lambda item: float(item.get(metric_key) or 0))
        latest_point = series[-1]
        active_days = sum(1 for item in series if float(item.get(metric_key) or 0) > 0)
        return {
            "domain_label": domain_label,
            "metric_label": metric_label,
            "trend": self._comparison_trend(series, metric_key),
            "average": self._comparison_average(series, metric_key),
            "peak_value": float(peak_point.get(metric_key) or 0),
            "peak_date": self._reasoning_point_date(peak_point),
            "latest_value": float(latest_point.get(metric_key) or 0),
            "latest_date": self._reasoning_point_date(latest_point),
            "active_days": active_days,
            "sample_days": len(series),
        }

    def _build_data_grounded_explanation(
        self,
        *,
        plan_context: dict,
        query_result: dict,
        forecast_result: dict,
        knowledge: list[dict],
    ) -> str:
        domain = str(plan_context.get("domain") or "")
        region_name = str(plan_context.get("region_name") or self._first_region_name(query_result) or "当前地区")
        series = list(query_result.get("data") or [])
        if not series or not isinstance(series[0], dict):
            return ""

        summary = self._reasoning_series_summary(domain, series)
        average = float(summary["average"] or 0)
        peak_value = float(summary["peak_value"] or 0)
        latest_value = float(summary["latest_value"] or 0)
        trend = str(summary["trend"] or "整体平稳")
        metric_label = str(summary["metric_label"] or "指标")

        sentences = [
            f"{region_name}{summary['domain_label']}在这个时间窗内{trend}，高值主要出现在{summary['peak_date'] or '窗口内高点'}，峰值{self._reasoning_format_metric(peak_value)}。"
        ]
        if latest_value <= average * 0.7 and peak_value > 0:
            sentences.append(
                f"最近值{self._reasoning_format_metric(latest_value)}，明显低于窗口均值{self._reasoning_format_metric(average)}，说明当前已经从前期高点回落，但前段时间确实存在一轮明显抬升。"
            )
        elif latest_value >= average * 1.2 and latest_value > 0:
            sentences.append(
                f"最近值{self._reasoning_format_metric(latest_value)}，仍高于窗口均值{self._reasoning_format_metric(average)}，说明当前压力还没有完全消退。"
            )
        else:
            sentences.append(
                f"最近值{self._reasoning_format_metric(latest_value)}，与窗口均值{self._reasoning_format_metric(average)}接近，说明当前处于高点后的回落或平稳阶段。"
            )

        if summary["active_days"] >= max(3, summary["sample_days"] // 3):
            sentences.append(
                f"窗口内共有{summary['active_days']}个观测日{metric_label}大于0，不是单点异常，更像是一段持续性的高值过程。"
            )
        else:
            sentences.append(
                f"窗口内只有{summary['active_days']}个观测日{metric_label}大于0，更像是局部时段冲高。"
            )

        forecast = dict(forecast_result.get("forecast") or {})
        if forecast:
            horizon_days = int(forecast.get("horizon_days") or 14)
            horizon_phrase = "未来两周" if horizon_days == 14 else f"未来{horizon_days}天"
            risk_level = str(forecast.get("risk_level") or "中")
            projected_score = self._reasoning_format_metric(float(forecast.get("projected_score") or 0))
            sentences.append(
                f"按{horizon_phrase}预测，风险仍为{risk_level}，预测得分{projected_score}，所以后续应优先复核前期高值点位，而不是只看单日波动。"
            )

        if knowledge:
            first_title = str(knowledge[0].get("title") or "")
            if first_title:
                sentences.append(f"结合{first_title}的经验，这类“先冲高、后回落”或持续高值形态，通常都需要复核监测点位、阈值判断和田间处置时机。")

        return "".join(sentences)

    def _build_data_grounded_advice(
        self,
        *,
        plan_context: dict,
        query_result: dict,
        forecast_result: dict,
    ) -> str:
        domain = str(plan_context.get("domain") or "")
        region_name = str(plan_context.get("region_name") or self._first_region_name(query_result) or "当前地区")
        series = list(query_result.get("data") or [])
        if not series or not isinstance(series[0], dict):
            return ""

        summary = self._reasoning_series_summary(domain, series)
        average = float(summary["average"] or 0)
        latest_value = float(summary["latest_value"] or 0)
        peak_value = float(summary["peak_value"] or 0)
        forecast = dict(forecast_result.get("forecast") or {})
        risk_level = str(forecast.get("risk_level") or "")
        rising_pressure = latest_value >= average * 1.2 if average > 0 else latest_value > 0
        clearly_receded = latest_value <= average * 0.7 if average > 0 else latest_value == 0

        if domain == "pest":
            if risk_level == "高" or rising_pressure:
                return (
                    f"{region_name}当前仍处在偏高压力区，先复核高值点位和诱捕监测，再对连续高值地块按阈值分区处置；"
                    "本轮不要全域铺开，优先盯住峰值附近区域，处置后 24-48 小时复查虫口变化。"
                )
            if clearly_receded:
                return (
                    f"{region_name}当前已经较峰值阶段明显回落，建议先以复核高值点位和维持监测为主，"
                    "暂不直接扩大处置范围；如果后续连续几天再抬升，再升级到分区防控。"
                )
            return (
                f"{region_name}当前处于中间压力阶段，建议先复核高值点位，再对持续偏高地块做分区处置，"
                "同时保留连续监测，避免因为短时回落就过早撤掉巡查。"
            )

        if risk_level == "高" or rising_pressure:
            return (
                f"{region_name}当前异常压力偏高，建议先分区复核低墒/高墒地块，再优先处理持续异常区域；"
                "低墒先补灌，高墒先排水，处置后继续看 3-5 天监测是否回落。"
            )
        if clearly_receded:
            return (
                f"{region_name}当前已经较前期高点回落，建议先维持监测和抽样复核，不要一次性加大灌排动作；"
                "重点盯住此前异常最集中的地块，看是否再次抬头。"
            )
        return (
            f"{region_name}当前仍有一定异常压力，建议先复核异常分布，再按地块类型做补灌或排水，"
            "并持续复查，避免处置动作和实时墒情脱节。"
        )

    def _answer_compare_request(
        self,
        question: str,
        compare_request: dict,
        understanding: dict | None,
        plan: dict | None,
        previous_context: dict | None,
    ) -> dict:
        understanding = dict(understanding or {})
        plan = dict(plan or {})
        previous_context = dict(previous_context or {})
        route_seed = self._normalize_historical_route(
            understanding.get("historical_query_text") or question,
            dict(plan.get("route") or {}),
            understanding,
            previous_context,
        )
        if compare_request["kind"] == "region_compare":
            domain = str(compare_request["domain"])
            domain_label = self._comparison_domain_label(domain)
            regions = list(compare_request["regions"])
            base_query_type = str(compare_request["base_query_type"])
            summaries: list[dict] = []
            subqueries: list[dict] = []
            for region in regions:
                route = dict(route_seed)
                route.update(
                    {
                        "query_type": base_query_type,
                        "city": region,
                        "county": None,
                        "region_level": "city",
                    }
                )
                result = self.query_engine.answer(question, plan=route)
                summaries.append(self._comparison_summary(domain, region, list(result.data or [])))
                subqueries.append(
                    {
                        "region_name": region,
                        "query_type": base_query_type,
                        "since": route.get("since"),
                        "until": route.get("until"),
                    }
                )
            title = "变化对比" if base_query_type.endswith("_trend") else "对比结果"
            left, right = summaries[0], summaries[1]
            answer = "\n".join(
                [
                    f"{self._window_summary(route_seed.get('window'))}{domain_label}{title}：",
                    f"- {left['region_name']}：趋势{left['trend']}，均值{left['average']:.1f}，峰值{left['peak']:.1f}，最近值{left['latest']:.1f}",
                    f"- {right['region_name']}：趋势{right['trend']}，均值{right['average']:.1f}，峰值{right['peak']:.1f}，最近值{right['latest']:.1f}",
                    self._comparison_conclusion(left, right, left["region_name"], right["region_name"]),
                ]
            )
            evidence = {
                "query_type": compare_request["query_type"],
                "sql": base_query_type,
                "compare_kind": "region_compare",
                "subqueries": subqueries,
                "comparisons": summaries,
                "analysis_context": {
                    "domain": domain,
                    "region_name": "",
                    "region_level": "city",
                    "query_type": compare_request["query_type"],
                    "window": route_seed.get("window") or {},
                },
            }
            return {
                "mode": "data_query",
                "answer": answer,
                "data": summaries,
                "evidence": evidence,
            }

        region = str(compare_request["region"])
        base_mode = str(compare_request["base_query_type"])
        pest_query_type = f"pest_{base_mode}" if base_mode in {"detail", "trend", "overview"} else "pest_overview"
        soil_query_type = f"soil_{base_mode}" if base_mode in {"detail", "trend", "overview"} else "soil_overview"
        pest_route = dict(route_seed)
        pest_route.update({"query_type": pest_query_type, "city": region, "county": None, "region_level": "city"})
        soil_route = dict(route_seed)
        soil_route.update({"query_type": soil_query_type, "city": region, "county": None, "region_level": "city"})
        pest_result = self.query_engine.answer(question, plan=pest_route)
        soil_result = self.query_engine.answer(question, plan=soil_route)
        pest_summary = self._comparison_summary("pest", region, list(pest_result.data or []))
        soil_summary = self._comparison_summary("soil", region, list(soil_result.data or []))
        answer = "\n".join(
            [
                f"{region}{self._window_summary(route_seed.get('window'))}问题对比：",
                f"- 虫情：趋势{pest_summary['trend']}，均值{pest_summary['average']:.1f}，峰值{pest_summary['peak']:.1f}，最近值{pest_summary['latest']:.1f}",
                f"- 墒情：趋势{soil_summary['trend']}，均值{soil_summary['average']:.1f}，峰值{soil_summary['peak']:.1f}，最近值{soil_summary['latest']:.1f}",
                self._comparison_conclusion(pest_summary, soil_summary, "虫情", "墒情"),
            ]
        )
        evidence = {
            "query_type": compare_request["query_type"],
            "sql": "cross_domain_compare",
            "compare_kind": "cross_domain_compare",
            "subqueries": [
                {"domain": "pest", "query_type": pest_query_type, "region_name": region, "since": pest_route.get("since"), "until": pest_route.get("until")},
                {"domain": "soil", "query_type": soil_query_type, "region_name": region, "since": soil_route.get("since"), "until": soil_route.get("until")},
            ],
            "comparisons": [pest_summary, soil_summary],
            "analysis_context": {
                "domain": "mixed",
                "region_name": region,
                "region_level": self._infer_region_level_from_name(region) or "city",
                "query_type": compare_request["query_type"],
                "window": route_seed.get("window") or {},
            },
        }
        return {
            "mode": "data_query",
            "answer": answer,
            "data": [pest_summary, soil_summary],
            "evidence": evidence,
        }

    def _advice_node(self, state: AgentState) -> dict:
        plan = state.get("plan") or {}
        runtime_context = self._build_runtime_context(
            (state.get("understanding") or {}).get("normalized_question") or state.get("question", ""),
            plan,
            previous_context=state.get("memory_context"),
            understanding=state.get("understanding"),
        )
        result = self.advice_engine.answer(state.get("question", ""), context=runtime_context)
        evidence = {
            "sources": result.sources,
            "generation_mode": result.generation_mode,
            "analysis_context": runtime_context,
            "execution_plan": list((state.get("understanding") or {}).get("execution_plan") or ["understand_request", "answer_synthesis"]),
        }
        if result.model:
            evidence["model"] = result.model
        return {
            "response": {
                "mode": "advice",
                "answer": result.answer,
                "data": [],
                "evidence": evidence,
            }
        }

    def _clarify_node(self, state: AgentState) -> dict:
        plan = state.get("plan") or {}
        return {
            "response": {
                "mode": "advice",
                "answer": plan.get("clarification"),
                "data": [],
                "evidence": {
                    "generation_mode": "clarification",
                    "confidence": plan.get("confidence", 0.0),
                },
            }
        }

    def _synthesize_node(self, state: AgentState) -> dict:
        understanding = dict(state.get("understanding") or {})
        plan = dict(state.get("plan") or {})
        query_result = dict(state.get("query_result") or {})
        forecast_result = dict(state.get("forecast_result") or {})
        knowledge = list(state.get("knowledge") or [])

        if not (understanding.get("needs_forecast") or understanding.get("needs_explanation") or understanding.get("needs_advice")):
            if query_result:
                merged_evidence = dict(query_result.get("evidence") or {})
                merged_evidence["execution_plan"] = list(understanding.get("execution_plan") or [])
                query_result["evidence"] = merged_evidence
                return {"response": query_result}
        if (
            understanding.get("needs_forecast")
            and not understanding.get("needs_historical")
            and not understanding.get("needs_explanation")
            and not understanding.get("needs_advice")
        ):
            evidence = {
                **dict(forecast_result),
                "execution_plan": list(understanding.get("execution_plan") or []),
                "generation_mode": "forecast",
            }
            return {
                "response": {
                    "mode": "data_query",
                    "answer": forecast_result.get("answer", ""),
                    "data": forecast_result.get("data", []),
                    "evidence": evidence,
                }
            }

        plan_context = self._build_runtime_context(
            understanding.get("normalized_question") or state.get("question", ""),
            plan,
            previous_context=state.get("memory_context"),
            understanding=understanding,
        )
        if forecast_result.get("analysis_context", {}).get("region_name"):
            plan_context["region_name"] = forecast_result["analysis_context"]["region_name"]
        elif not plan_context.get("region_name") and self._first_region_name(query_result):
            plan_context["region_name"] = self._first_region_name(query_result)
        if forecast_result.get("forecast"):
            plan_context["forecast"] = forecast_result["forecast"]

        explanation_text = ""
        explanation_sources = []
        if understanding.get("needs_explanation"):
            explanation_text = self._build_data_grounded_explanation(
                plan_context=plan_context,
                query_result=query_result,
                forecast_result=forecast_result,
                knowledge=knowledge,
            )
            if not explanation_text:
                explanation_result = self.advice_engine.answer("为什么", context=plan_context)
                explanation_text = explanation_result.answer
                explanation_sources = explanation_result.sources
            else:
                explanation_sources = knowledge

        advice_text = ""
        advice_sources = []
        if understanding.get("needs_advice"):
            advice_text = self._build_data_grounded_advice(
                plan_context=plan_context,
                query_result=query_result,
                forecast_result=forecast_result,
            )
            if not advice_text:
                advice_result = self.advice_engine.answer("给建议", context=plan_context)
                advice_text = advice_result.answer
                advice_sources = advice_result.sources
            else:
                advice_sources = knowledge

        sections: list[str] = []
        if query_result.get("answer"):
            sections.append(f"历史数据：{query_result['answer']}")
        if explanation_text:
            sections.append(f"原因解释：{explanation_text}")
        if forecast_result.get("answer"):
            sections.append(f"预测：{forecast_result['answer']}")
        if knowledge:
            titles = "；".join(str(item.get("title") or "") for item in knowledge[:2] if item.get("title"))
            if titles:
                sections.append(f"知识依据：参考 {titles}")
        if advice_text:
            sections.append(f"建议：{advice_text}")
        answer = "\n".join(sections) if sections else (query_result.get("answer") or advice_text or "当前暂无可综合输出的结果。")

        evidence = {
            "execution_plan": list(understanding.get("execution_plan") or []),
            "request_understanding": understanding,
            "analysis_context": plan_context,
            "historical_query": query_result.get("evidence") or {},
            "forecast": forecast_result.get("forecast") or {},
            "knowledge": knowledge,
            "knowledge_sources": advice_sources or explanation_sources or knowledge,
            "generation_mode": "analysis_synthesis",
        }
        if plan.get("context_trace"):
            evidence["context_trace"] = list(plan.get("context_trace") or [])

        combined_data = {
            "historical": query_result.get("data"),
            "forecast": forecast_result.get("data"),
        }
        return {
            "response": {
                "mode": "analysis",
                "answer": answer,
                "data": combined_data,
                "evidence": evidence,
            }
        }

    @staticmethod
    def _first_region_name(response: dict) -> str:
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

    @staticmethod
    def _memory_time_range_value(window: dict | None) -> dict:
        normalized_window = dict(window or {})
        window_type = str(normalized_window.get("window_type") or "")
        window_value = normalized_window.get("window_value")
        if window_type in {"months", "weeks", "days"} and window_value not in {None, ""}:
            return {"mode": "relative", "value": f"{window_value}_{window_type}"}
        return {"mode": "none", "value": None}

    @staticmethod
    def _memory_slot_priority(source: str) -> int:
        if source == "explicit":
            return 100
        if source == "carried":
            return 90
        if source == "system":
            return 80
        if source == "inferred":
            return 60
        if source == "legacy":
            return 50
        return 0

    @staticmethod
    def _memory_slot_ttl(source: str) -> int:
        if source in {"explicit", "carried"}:
            return 4
        if source == "system":
            return 2
        if source in {"inferred", "legacy"}:
            return 2
        return 0

    def _build_memory_slot(
        self,
        *,
        value,
        source: str,
        turn_count: int,
        previous_slot: dict | None = None,
        preserve_previous: bool = False,
    ) -> dict:
        if preserve_previous and previous_slot:
            return dict(previous_slot)

        if previous_slot and previous_slot.get("value") == value and previous_slot.get("source") == source:
            updated_at_turn = int(previous_slot.get("updated_at_turn") or turn_count)
        else:
            updated_at_turn = turn_count
        return {
            "value": value,
            "source": source,
            "priority": self._memory_slot_priority(source),
            "ttl": self._memory_slot_ttl(source),
            "updated_at_turn": updated_at_turn,
        }

    def _build_memory_snapshot(self, state: AgentState) -> dict:
        question = state.get("question", "")
        plan = state.get("plan") or {}
        response = state.get("response") or {}
        previous_context = dict(state.get("memory_context") or {})
        preserve_thread_scope = str(plan.get("reason") or "") in {"greeting_intro", "identity_self_intro"}
        route = dict(plan.get("route") or previous_context.get("route") or {})
        evidence = dict(response.get("evidence") or {})
        analysis_context = dict(evidence.get("analysis_context") or {})
        forecast = dict(evidence.get("forecast") or previous_context.get("forecast") or {})
        understanding = dict(state.get("understanding") or {})
        previous_slots = dict(previous_context.get("slots") or {})
        turn_count = int(previous_context.get("turn_count") or 0) + 1

        if preserve_thread_scope and previous_context:
            route = dict(previous_context.get("route") or route)
            forecast = dict(previous_context.get("forecast") or forecast)

        domain = (
            analysis_context.get("domain")
            or (previous_context.get("domain") if preserve_thread_scope else "")
            or self._derive_domain(question, plan, previous_context)
        )
        inherited_region = previous_context.get("region_name") if understanding.get("reuse_region_from_context", True) else ""
        region_name = (
            analysis_context.get("region_name")
            or (previous_context.get("region_name") if preserve_thread_scope else "")
            or route.get("county")
            or route.get("city")
            or self._first_region_name(response)
            or inherited_region
            or ""
        )
        window = route.get("window") or previous_context.get("window") or {}
        query_plan = dict(plan.get("query_plan") or {})
        query_plan_intent = str(query_plan.get("intent") or plan.get("intent") or "")

        domain_source = "explicit" if understanding.get("domain") else ("carried" if preserve_thread_scope and previous_slots.get("domain") else ("inferred" if domain else "empty"))
        region_source = (
            "explicit"
            if understanding.get("region_name") or route.get("county") or route.get("city")
            else ("carried" if preserve_thread_scope and previous_slots.get("region") else ("inferred" if region_name else "empty"))
        )
        explicit_window = dict(understanding.get("window") or {})
        window_source = (
            "explicit"
            if str(explicit_window.get("window_type") or "") in {"months", "weeks", "days"} and explicit_window.get("window_value") not in {None, ""}
            else ("carried" if preserve_thread_scope and previous_slots.get("time_range") else ("inferred" if window else "empty"))
        )
        intent_source = "system" if query_plan_intent else "empty"

        slots = {
            "domain": self._build_memory_slot(
                value=domain,
                source=domain_source,
                turn_count=turn_count,
                previous_slot=previous_slots.get("domain"),
                preserve_previous=preserve_thread_scope,
            ),
            "region": self._build_memory_slot(
                value=region_name,
                source=region_source,
                turn_count=turn_count,
                previous_slot=previous_slots.get("region"),
                preserve_previous=preserve_thread_scope,
            ),
            "time_range": self._build_memory_slot(
                value=self._memory_time_range_value(window),
                source=window_source,
                turn_count=turn_count,
                previous_slot=previous_slots.get("time_range"),
                preserve_previous=preserve_thread_scope,
            ),
            "intent": self._build_memory_slot(
                value=query_plan_intent,
                source=intent_source,
                turn_count=turn_count,
                previous_slot=previous_slots.get("intent"),
            ),
        }

        pending_user_question = None
        pending_clarification = None
        if plan.get("reason") == "agri_domain_ambiguous":
            pending_user_question = question
            pending_clarification = "agri_domain"
        elif plan.get("reason") in {"generic_ambiguous", "ambiguous", "low_signal"}:
            pending_user_question = question
            pending_clarification = "generic_intent"

        return {
            "memory_version": 2,
            "turn_count": turn_count,
            "domain": domain,
            "region_name": region_name,
            "query_type": analysis_context.get("query_type") or route.get("query_type") or previous_context.get("query_type") or "",
            "window": window,
            "route": route,
            "forecast": forecast,
            "last_question": question,
            "last_answer": response.get("answer", ""),
            "last_verified_answer": response.get("answer", "") if response.get("mode") != "advice" or not plan.get("needs_clarification") else "",
            "pending_user_question": pending_user_question,
            "pending_clarification": pending_clarification,
            "user_preferences": dict(previous_context.get("user_preferences") or {}),
            "conversation_state": {
                "last_intent": str(plan.get("intent") or ""),
                "last_answer_mode": str(response.get("mode") or ""),
                "last_clarification_reason": str(plan.get("reason") or "") if plan.get("needs_clarification") else "",
            },
            "slots": slots,
        }

    def _persist_node(self, state: AgentState) -> dict:
        thread_id = str(state.get("thread_id") or "default")
        response = dict(state.get("response") or {})
        plan = state.get("plan") or {}
        understanding = dict(state.get("understanding") or {})
        query_result = dict(state.get("query_result") or {})
        snapshot = self._build_memory_snapshot(state)
        if not thread_id.startswith("__stateless__:"):
            self.memory_store.remember(thread_id, snapshot)

        evidence = dict(response.get("evidence") or {})
        evidence.setdefault("execution_plan", list(understanding.get("execution_plan") or []))
        evidence.setdefault(
            "analysis_context",
            {
                "domain": snapshot.get("domain"),
                "region_name": snapshot.get("region_name"),
                "region_level": str((snapshot.get("route") or {}).get("region_level") or ""),
                "query_type": snapshot.get("query_type"),
            },
        )
        if query_result.get("evidence"):
            evidence.setdefault("historical_query", dict(query_result.get("evidence") or {}))
        if plan.get("task_graph"):
            evidence.setdefault("task_graph", dict(plan.get("task_graph") or {}))
        evidence.setdefault("memory_state", snapshot)
        if understanding:
            evidence.setdefault("request_understanding", understanding)
        if plan.get("context_trace"):
            evidence["context_trace"] = list(plan.get("context_trace") or [])
        response["evidence"] = evidence
        return {"memory_context": snapshot, "response": response}

    def answer(self, question: str, history: object = None, thread_id: str | None = None) -> dict:
        effective_thread_id = thread_id or f"__stateless__:{uuid4()}"
        state = self.graph.invoke(
            {
                "question": question,
                "history": history if isinstance(history, list) else [],
                "thread_id": effective_thread_id,
                "memory_context": {},
                "understanding": {},
                "plan": {},
                "query_result": {},
                "forecast_result": {},
                "knowledge": [],
                "response": {},
            },
            config={"configurable": {"thread_id": effective_thread_id}},
        )
        response = dict(state.get("response") or {})
        plan = dict(state.get("plan") or {})
        return self._attach_processing(response, plan)
