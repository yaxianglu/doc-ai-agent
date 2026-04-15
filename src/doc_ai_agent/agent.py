"""Doc AI Agent 主流程：负责记忆、理解、规划、执行与回复编排。"""

from __future__ import annotations

import re
from uuid import uuid4
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .advice_engine import AdviceEngine
from .agent_analysis_synthesis import build_data_grounded_advice, build_data_grounded_explanation
from .agent_comparison import detect_compare_request
from .agent_compare_execution import execute_compare_request
from .agent_contracts import FinalResponseEvidence, ForecastExecutionContext
from .agent_contracts import OrchestrationStateEnvelope
from .answer_guard import AnswerGuard
from .capabilities.data_query import DataQueryCapability
from .capabilities.forecast import ForecastCapability
from .agent_execution_nodes import (
    build_advice_response,
    build_clarification_response,
    build_forecast_execution_context,
    build_query_result_payload,
    run_knowledge_node,
    run_query_node,
)
from .agent_orchestration import resolve_planning_question, route_target, should_build_direct_forecast_plan, update_plan_outcome
from .agent_memory import build_memory_snapshot
from .agent_response_meta import build_response_meta as build_agent_response_meta
from .agent_response_meta import execution_plan as resolve_execution_plan
from .agent_runtime_context import build_runtime_context, derive_domain, normalize_historical_route
from .agent_synthesis_orchestration import build_advice_payload, build_explanation_payload
from .agent_synthesis_orchestration import build_plan_context, first_region_name, synthesize_analysis_response
from .forecast_engine import ForecastEngine
from .forecast_service import ForecastService
from .intent_router import IntentRouter
from .letta_memory import LocalMemoryStore, LettaMemoryStore, ResilientMemoryStore
from .query_playbook_router import create_query_playbook_router
from .query_plan import execution_route, replace_execution_route
from .query_planner import QueryPlanner
from .query_engine import QueryEngine
from .request_understanding import RequestUnderstanding
from .repository import AlertRepository


class AgentState(TypedDict, total=False):
    """LangGraph 状态载体：在各节点间传递执行上下文。"""
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
    orchestration_state: dict


class DocAIAgent:
    """文档智能代理入口：编排查询、预测、知识与回答合成流程。"""
    def __init__(
        self,
        repo: AlertRepository,
        llm_client=None,
        router_model: str = "",
        advice_model: str = "",
        source_provider=None,
        query_playbook_router=None,
        understanding_backend=None,
        semantic_parser=None,
        memory_store_path: str = "./data/agent-memory.json",
        letta_base_url: str = "",
        letta_api_key: str = "",
        letta_block_prefix: str = "doc-cloud-thread",
    ):
        self.repo = repo
        self.router_model = router_model
        self.advice_model = advice_model
        self.query_engine = QueryEngine(repo)
        self.data_query_capability = DataQueryCapability(self.query_engine)
        self.answer_guard = AnswerGuard()
        self.forecast_engine = ForecastEngine(repo)
        self.forecast_service = ForecastService(repo)
        self.forecast_capability = ForecastCapability(self.forecast_service)
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
        self.query_planner = QueryPlanner(
            self.intent_router,
            self.query_playbook_router,
            semantic_parser=semantic_parser,
        )
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
        """构建 LangGraph 工作流，定义节点与路由边。"""
        workflow = StateGraph(AgentState)
        workflow.add_node("load_memory", self._load_memory_node)
        workflow.add_node("understand_request", self._understand_request_node)
        workflow.add_node("plan", self._plan_node)
        workflow.add_node("query", self._query_node)
        workflow.add_node("forecast", self._forecast_node)
        workflow.add_node("knowledge", self._knowledge_node)
        workflow.add_node("synthesize", self._synthesize_node)
        workflow.add_node("answer_guard", self._answer_guard_node)
        workflow.add_node("advice", self._advice_node)
        workflow.add_node("clarify", self._clarify_node)
        workflow.add_node("persist", self._persist_node)
        workflow.add_edge(START, "load_memory")
        workflow.add_edge("load_memory", "understand_request")
        workflow.add_edge("understand_request", "plan")
        # 规划节点决定主路径：分析、建议或澄清。
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
        workflow.add_edge("synthesize", "answer_guard")
        workflow.add_edge("advice", "answer_guard")
        workflow.add_edge("clarify", "answer_guard")
        workflow.add_edge("answer_guard", "persist")
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

    def _build_response_meta(self, state: AgentState, response: dict, evidence: dict) -> dict:
        return build_agent_response_meta(
            plan=dict(state.get("plan") or {}),
            response=response,
            evidence=evidence,
        )

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
        return any(token in question for token in ["哪里", "哪儿", "哪些地区", "哪些地方", "最严重的地方", "哪个县", "哪些县", "哪几个县", "哪个区", "哪些区"])

    @staticmethod
    def _infer_region_level_from_name(region_name: str) -> str:
        normalized = str(region_name or "")
        if normalized.endswith(("县", "区")):
            return "county"
        if normalized.endswith("市"):
            return "city"
        return ""

    @staticmethod
    def _plan_route(plan: dict | None) -> dict:
        normalized_plan = dict(plan or {})
        canonical_route = execution_route(normalized_plan.get("query_plan") or {})
        if canonical_route:
            return canonical_route
        return dict(normalized_plan.get("route") or {})

    @staticmethod
    def _plan_task_graph(plan: dict | None) -> dict:
        normalized_plan = dict(plan or {})
        query_plan = dict(normalized_plan.get("query_plan") or {})
        decomposition = dict(query_plan.get("decomposition") or {})
        if decomposition:
            return decomposition
        return dict(normalized_plan.get("task_graph") or {})

    def _execution_plan(self, state: AgentState) -> list[str]:
        return resolve_execution_plan(
            plan=state.get("plan"),
            understanding=state.get("understanding"),
        )

    def _build_forecast_plan_from_understanding(self, understanding: dict, memory_context: dict | None = None) -> dict:
        memory_context = dict(memory_context or {})
        domain = understanding.get("domain") or memory_context.get("domain") or ""
        future_window = understanding.get("future_window") or {"horizon_days": 14}
        original_question = str(understanding.get("original_question", "") or "")
        forecast_mode = "ranking" if self._asks_region_ranking(original_question) else "region"
        if (
            forecast_mode != "ranking"
            and str(memory_context.get("query_type") or "") in {"pest_top", "soil_top"}
            and str((memory_context.get("route") or {}).get("region_level") or "") == "county"
            and len(original_question.strip()) <= 8
            and not any(token in original_question for token in ["更糟", "恶化", "更严重", "会怎样", "怎么样"])
        ):
            forecast_mode = "ranking"
        inherited_region = memory_context.get("region_name") if understanding.get("reuse_region_from_context") else None
        region_name = understanding.get("region_name") or (None if forecast_mode == "ranking" else inherited_region) or None
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
            "forecast_mode": forecast_mode,
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
        """生成执行计划，并在必要时补齐预测直连计划。"""
        understanding = dict(state.get("understanding") or {})
        question_for_planning = resolve_planning_question(state.get("question", ""), understanding)
        if should_build_direct_forecast_plan(understanding):
            plan = self._build_forecast_plan_from_understanding(understanding, state.get("memory_context"))
        else:
            plan = self.query_planner.plan(
                question_for_planning,
                history=state.get("history"),
                context=state.get("memory_context"),
                understanding=understanding,
            )
        plan = dict(plan)
        if not plan.get("query_plan"):
            plan = self.query_planner._finalize_plan(
                plan,
                question_for_planning,
                context=state.get("memory_context"),
                understanding=understanding,
            )
        query_plan = dict(plan.get("query_plan") or {})
        route = self._plan_route(plan)
        explicit_top_n = self.query_planner._extract_top_n(state.get("question", ""))
        if explicit_top_n:
            route["top_n"] = explicit_top_n
            if query_plan:
                query_plan = replace_execution_route(query_plan, route)
                plan["query_plan"] = query_plan
        plan["route"] = self._plan_route(plan) or route
        plan["task_graph"] = self._plan_task_graph(plan)
        outcome = update_plan_outcome(plan=plan, understanding=understanding)
        updates = {"plan": outcome.plan, "orchestration_state": self._orchestration_state(state, plan=outcome.plan, understanding=outcome.understanding)}
        if outcome.understanding != understanding:
            updates["understanding"] = outcome.understanding
        return updates

    def _route_from_plan(self, state: AgentState) -> str:
        return route_target(state.get("plan") or {}, state.get("understanding") or {})

    def _query_node(self, state: AgentState) -> dict:
        result = run_query_node(
            question=state.get("question", ""),
            understanding=state.get("understanding") or {},
            plan=state.get("plan") or {},
            memory_context=state.get("memory_context"),
            detect_compare_request=self._detect_compare_request,
            answer_compare_request=self._answer_compare_request,
            normalize_historical_route=self._normalize_historical_route,
            plan_route=self._plan_route,
            query_engine=self.query_engine,
            data_query_capability=self.data_query_capability,
        )
        query_result = dict(result.get("query_result") or {})
        result["orchestration_state"] = self._orchestration_state(
            state,
            task_results={"query": query_result},
            evidence={"query": dict(query_result.get("evidence") or {})},
        )
        return result

    def _resolve_forecast_context(self, state: AgentState) -> ForecastExecutionContext:
        return build_forecast_execution_context(
            question=state.get("question", ""),
            understanding=state.get("understanding") or {},
            plan=state.get("plan") or {},
            memory_context=state.get("memory_context"),
            query_result=state.get("query_result") or {},
            normalize_historical_route=self._normalize_historical_route,
            plan_route=self._plan_route,
            derive_domain=self._derive_domain,
            infer_region_level_from_name=self._infer_region_level_from_name,
            asks_region_ranking=self._asks_region_ranking,
            first_region_name=self._first_region_name,
        )

    def _forecast_node(self, state: AgentState) -> dict:
        forecast_context = self._resolve_forecast_context(state)
        if not forecast_context.enabled:
            return {"forecast_result": {}, "orchestration_state": self._orchestration_state(state)}
        forecast_route = dict(forecast_context.route or {})
        runtime_context = dict(forecast_context.runtime_context)
        if forecast_route.get("forecast_mode") == "ranking":
            pass
        capability_result = self.forecast_capability.execute(forecast_route, runtime_context)
        result = {
            "answer": str(capability_result.meta.get("answer") or ""),
            "data": capability_result.data,
            "forecast": dict(capability_result.meta.get("forecast") or capability_result.evidence),
            "analysis_context": dict(capability_result.meta.get("analysis_context") or {}),
            "capability_result": capability_result.to_dict(),
        }
        return {
            "forecast_result": result,
            "orchestration_state": self._orchestration_state(
                state,
                task_results={"forecast": dict(result)},
                evidence={"forecast": dict(result.get("forecast") or {}) if isinstance(result, dict) else {}},
            ),
        }

    def _knowledge_node(self, state: AgentState) -> dict:
        result = run_knowledge_node(
            question=state.get("question", ""),
            understanding=state.get("understanding") or {},
            plan=state.get("plan") or {},
            memory_context=state.get("memory_context"),
            query_result=state.get("query_result") or {},
            forecast_result=state.get("forecast_result") or {},
            source_provider=self.source_provider,
            build_runtime_context=self._build_runtime_context,
            first_region_name=self._first_region_name,
        )
        result["orchestration_state"] = self._orchestration_state(
            state,
            task_results={"knowledge": {"count": len(result.get("knowledge") or [])}},
        )
        return result

    def _derive_domain(self, question: str, plan: dict, previous_context: dict | None = None) -> str:
        return derive_domain(question, self._plan_route(plan), previous_context)

    def _build_runtime_context(self, question: str, plan: dict, previous_context: dict | None = None, understanding: dict | None = None) -> dict:
        return build_runtime_context(
            question=question,
            plan=plan,
            previous_context=previous_context,
            understanding=understanding,
            build_route=self.query_planner._build_route,
            plan_route=self._plan_route,
            infer_region_level_from_name=self._infer_region_level_from_name,
            is_greeting_question=self.query_planner._is_greeting_question,
        )

    def _normalize_historical_route(
        self,
        question: str,
        route: dict,
        understanding: dict | None = None,
        previous_context: dict | None = None,
    ) -> dict:
        return normalize_historical_route(
            question=question,
            route=route,
            understanding=understanding,
            previous_context=previous_context,
            build_route=self.query_planner._build_route,
            infer_region_level_from_name=self._infer_region_level_from_name,
        )

    def _detect_compare_request(
        self,
        question: str,
        understanding: dict | None,
        plan: dict | None,
        previous_context: dict | None,
    ) -> dict | None:
        return detect_compare_request(question, understanding, plan, previous_context, self._derive_domain)

    def _build_data_grounded_explanation(
        self,
        *,
        plan_context: dict,
        query_result: dict,
        forecast_result: dict,
        knowledge: list[dict],
    ) -> str:
        return build_data_grounded_explanation(
            plan_context=plan_context,
            query_result=query_result,
            forecast_result=forecast_result,
            knowledge=knowledge,
            default_region_name=self._first_region_name(query_result),
        )

    def _build_data_grounded_advice(
        self,
        *,
        plan_context: dict,
        query_result: dict,
        forecast_result: dict,
    ) -> str:
        return build_data_grounded_advice(
            plan_context=plan_context,
            query_result=query_result,
            forecast_result=forecast_result,
            default_region_name=self._first_region_name(query_result),
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
            self._plan_route(plan),
            understanding,
            previous_context,
        )
        return execute_compare_request(
            question=question,
            compare_request=compare_request,
            route_seed=route_seed,
            query_engine=self.query_engine,
            infer_region_level_from_name=self._infer_region_level_from_name,
        )

    def _advice_node(self, state: AgentState) -> dict:
        result = build_advice_response(
            question=state.get("question", ""),
            plan=state.get("plan") or {},
            understanding=state.get("understanding") or {},
            memory_context=state.get("memory_context"),
            build_runtime_context=self._build_runtime_context,
            advice_engine=self.advice_engine,
            execution_plan=self._execution_plan(state),
        )
        response = dict(result.get("response") or {})
        result["orchestration_state"] = self._orchestration_state(
            state,
            task_results={"advice": {"mode": response.get("mode"), "answer": response.get("answer")}},
            evidence={"advice": dict(response.get("evidence") or {})},
        )
        return result

    def _clarify_node(self, state: AgentState) -> dict:
        result = build_clarification_response(state.get("plan") or {})
        response = dict(result.get("response") or {})
        result["orchestration_state"] = self._orchestration_state(
            state,
            task_results={"clarify": {"answer": response.get("answer")}},
            evidence={"clarify": dict(response.get("evidence") or {})},
        )
        return result

    def _synthesize_node(self, state: AgentState) -> dict:
        """合并查询、预测与知识证据，生成最终分析响应。"""
        understanding = dict(state.get("understanding") or {})
        plan = dict(state.get("plan") or {})
        query_result = dict(state.get("query_result") or {})
        forecast_result = dict(state.get("forecast_result") or {})
        knowledge = list(state.get("knowledge") or [])

        if not (understanding.get("needs_forecast") or understanding.get("needs_explanation") or understanding.get("needs_advice")):
            if query_result:
                merged_evidence = dict(query_result.get("evidence") or {})
                merged_evidence["execution_plan"] = self._execution_plan(state)
                query_result["evidence"] = merged_evidence
                return {
                    "response": query_result,
                    "orchestration_state": self._orchestration_state(
                        state,
                        task_results={"synthesize": {"mode": query_result.get("mode"), "answer": query_result.get("answer")}},
                        evidence={"response": dict(query_result.get("evidence") or {})},
                    ),
                }
        if (
            understanding.get("needs_forecast")
            and not understanding.get("needs_historical")
            and not understanding.get("needs_explanation")
            and not understanding.get("needs_advice")
        ):
            evidence = {
                **dict(forecast_result),
                "execution_plan": self._execution_plan(state),
                "generation_mode": "forecast",
            }
            return {
                "response": {
                    "mode": "data_query",
                    "answer": forecast_result.get("answer", ""),
                    "data": forecast_result.get("data", []),
                    "evidence": evidence,
                },
                "orchestration_state": self._orchestration_state(
                    state,
                    task_results={"synthesize": {"mode": "data_query", "answer": forecast_result.get("answer", "")}},
                    evidence={"response": evidence},
                ),
            }

        # 统一上下文后再合成，可避免解释与建议使用不同口径。
        plan_context = build_plan_context(
            question=state.get("question", ""),
            understanding=understanding,
            plan=plan,
            memory_context=state.get("memory_context"),
            query_result=query_result,
            forecast_result=forecast_result,
            build_runtime_context=self._build_runtime_context,
        )
        explanation_text, explanation_sources = build_explanation_payload(
            understanding=understanding,
            plan_context=plan_context,
            query_result=query_result,
            forecast_result=forecast_result,
            knowledge=knowledge,
            build_data_grounded_explanation=self._build_data_grounded_explanation,
            advice_engine=self.advice_engine,
        )
        advice_text, advice_sources = build_advice_payload(
            understanding=understanding,
            plan_context=plan_context,
            query_result=query_result,
            forecast_result=forecast_result,
            knowledge=knowledge,
            build_data_grounded_advice=self._build_data_grounded_advice,
            advice_engine=self.advice_engine,
        )
        result = synthesize_analysis_response(
            execution_plan=self._execution_plan(state),
            understanding=understanding,
            plan=plan,
            plan_context=plan_context,
            query_result=query_result,
            forecast_result=forecast_result,
            knowledge=knowledge,
            explanation_text=explanation_text,
            explanation_sources=explanation_sources,
            advice_text=advice_text,
            advice_sources=advice_sources,
        )
        response = dict(result.get("response") or {})
        result["orchestration_state"] = self._orchestration_state(
            state,
            task_results={"synthesize": {"mode": response.get("mode"), "answer": response.get("answer")}},
            evidence={"response": dict(response.get("evidence") or {})},
        )
        return result

    def _answer_guard_node(self, state: AgentState) -> dict:
        response = dict(state.get("response") or {})
        if not response.get("answer") or response.get("mode") == "advice":
            return {"response": response, "orchestration_state": self._orchestration_state(state)}
        review = self.answer_guard.review(
            question=state.get("question", ""),
            understanding=dict(state.get("understanding") or {}),
            plan=dict(state.get("plan") or {}),
            query_result=dict(state.get("query_result") or {}),
            forecast_result=dict(state.get("forecast_result") or {}),
            response=response,
        )
        final_answer = response.get("answer", "")
        refreshed_query_result = None
        if review["action"] == "rewrite":
            final_answer = review["rewritten_answer"] or final_answer
        elif review["action"] == "retry":
            retry_route = dict(review.get("retry_route") or {})
            retry_result = self.query_engine.answer(state.get("question", ""), plan=retry_route)
            refreshed_query_result = build_query_result_payload(retry_result, retry_route)
            final_answer = refreshed_query_result.get("answer") or final_answer
        elif review["action"] == "fallback":
            final_answer = review["fallback_answer"] or final_answer
        guarded = dict(response)
        guarded["answer"] = final_answer
        if refreshed_query_result:
            guarded["data"] = refreshed_query_result.get("data", [])
            merged_evidence = dict(guarded.get("evidence") or {})
            merged_evidence.update(dict(refreshed_query_result.get("evidence") or {}))
            guarded["evidence"] = merged_evidence
        evidence = dict(guarded.get("evidence") or {})
        evidence["answer_guard"] = {
            "ok": review["ok"],
            "action": review["action"],
            "violations": list(review["violations"]),
            "violation_codes": [str(item.get("code") or "") for item in review["violations"]],
        }
        guarded["evidence"] = evidence
        if refreshed_query_result:
            return {
                "response": guarded,
                "query_result": refreshed_query_result,
                "orchestration_state": self._orchestration_state(
                    state,
                    task_results={"answer_guard": {"action": review["action"]}},
                    evidence={"response": evidence},
                ),
            }
        return {
            "response": guarded,
            "orchestration_state": self._orchestration_state(
                state,
                task_results={"answer_guard": {"action": review["action"]}},
                evidence={"response": evidence},
            ),
        }

    @staticmethod
    def _first_region_name(response: dict) -> str:
        return first_region_name(response)

    def _build_memory_snapshot(self, state: AgentState) -> dict:
        snapshot = build_memory_snapshot(
            question=state.get("question", ""),
            plan=state.get("plan") or {},
            response=state.get("response") or {},
            previous_context=state.get("memory_context"),
            understanding=state.get("understanding"),
            plan_route=self._plan_route,
            first_region_name=self._first_region_name,
            derive_domain=lambda question, route, previous_context: derive_domain(question, route, previous_context),
        )
        understanding = dict(state.get("understanding") or {})
        followup_type = str(understanding.get("followup_type") or "none")
        snapshot["followup_type"] = followup_type
        conversation_state = dict(snapshot.get("conversation_state") or {})
        conversation_state["last_followup_type"] = followup_type
        snapshot["conversation_state"] = conversation_state
        return snapshot

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
        evidence.setdefault("execution_plan", self._execution_plan(state))
        evidence.setdefault(
            "analysis_context",
            {
                "domain": snapshot.get("domain"),
                "region_name": snapshot.get("region_name"),
                "region_level": str((snapshot.get("route") or {}).get("region_level") or ""),
                "query_type": snapshot.get("query_type"),
            },
        )
        evidence = FinalResponseEvidence(
            base_evidence=evidence,
            historical_query=dict(query_result.get("evidence") or {}) or None,
            task_graph=dict(plan.get("task_graph") or {}) or None,
            memory_state=snapshot,
            request_understanding=understanding or None,
            context_trace=list(plan.get("context_trace") or []),
            response_meta={},
        ).to_dict()
        evidence["response_meta"] = self._build_response_meta(state, response, evidence)
        response["evidence"] = evidence
        return {
            "memory_context": snapshot,
            "response": response,
            "orchestration_state": self._orchestration_state(
                state,
                memory_context=snapshot,
                evidence={"response": evidence},
            ),
        }

    def _orchestration_state(self, state: AgentState, **overrides) -> dict:
        """统一收口编排状态，便于后续 V2 迁移。"""
        current = dict(state.get("orchestration_state") or {})
        parsed_query = dict(overrides.get("parsed_query") or current.get("parsed_query") or (state.get("understanding") or {}).get("parsed_query") or {})
        route = dict(overrides.get("route") or current.get("route") or self._plan_route(state.get("plan") or {}) or {})
        plan = dict(overrides.get("plan") or current.get("plan") or state.get("plan") or {})
        task_results = dict(current.get("task_results") or {})
        task_results.update(dict(overrides.get("task_results") or {}))
        evidence = dict(current.get("evidence") or {})
        evidence.update(dict(overrides.get("evidence") or {}))
        confidence = dict(current.get("confidence") or {})
        understanding = dict(state.get("understanding") or {})
        if "request_understanding" not in confidence and understanding.get("confidence") not in {None, ""}:
            confidence["request_understanding"] = understanding.get("confidence")
        memory_context = dict(overrides.get("memory_context") or current.get("memory_context") or state.get("memory_context") or {})
        return OrchestrationStateEnvelope(
            parsed_query=parsed_query,
            route=route,
            plan=plan,
            task_results=task_results,
            evidence=evidence,
            confidence=confidence,
            memory_context=memory_context,
        ).to_dict()

    def answer(self, question: str, history: object = None, thread_id: str | None = None) -> dict:
        """对外主入口：驱动状态图执行并返回最终响应。"""
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
