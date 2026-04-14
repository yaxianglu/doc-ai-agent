"""查询规划器主入口。

`QueryPlanner` 会综合：
- 规则抽取（时间、地区、设备等）
- 上下文追问识别
- playbook 路由
- 意图路由器输出

最终产出统一的计划对象（含 query_plan、任务分解和执行 route）。
"""

from __future__ import annotations

import re
from typing import Optional

from .agri_semantics import (
    has_detail_intent,
    has_ranking_intent,
    infer_domain_from_text,
    needs_advice,
    needs_explanation,
    needs_forecast,
)
from .semantic_judger import SemanticJudger
from .followup_semantics import (
    explicit_domain_from_text,
    has_domain_switch_verb,
    is_advice_follow_up,
    is_detail_follow_up,
    is_explanation_follow_up,
    is_scope_correction_follow_up,
    looks_like_contextual_follow_up,
)
from .query_context_followup import build_context_follow_up_plan
from .query_planner_decisions import (
    playbook_context_trace,
    query_type_for_domain_switch,
    query_type_for_region_follow_up,
    query_type_for_window_follow_up,
    resolve_follow_up_question,
    should_use_playbook_route,
)
from .query_extractors import CITY_ALIASES, CHINESE_NUMBER_MAP, asks_for_county_scope
from .query_extractors import asks_for_multiple_ranked_results as query_asks_for_multiple_ranked_results
from .query_extractors import build_route as build_query_route
from .query_extractors import default_top_n as query_default_top_n
from .query_extractors import extract_city, extract_county, extract_day_range, extract_device_code
from .query_extractors import extract_future_window, extract_relative_window, extract_top_n, parse_number_token
from .query_intent_routing import (
    answer_mode_for_plan,
    domain_from_query_type,
    finalize_plan,
    infer_query_type,
    is_low_signal,
    merge_router_route,
    needs_agri_domain_clarification,
    normalize_router_route,
    score_advice,
    score_data,
)
from .query_plan import canonical_understanding_payload, route_from_canonical_understanding
from .semantic_parse import SemanticParseResult
from .semantic_parser import SemanticParser


class QueryPlanner:
    """面向生产的查询规划器。

    设计目标是“多来源信号融合 + 稳健兜底”：
    - 能利用外部路由时尽量利用
    - 外部失败时保持可用
    - 对低信息输入优先澄清，避免误查
    """
    CHINESE_NUMBER_MAP = CHINESE_NUMBER_MAP
    DETERMINISTIC_QUERY_TYPES = {
        "avg_by_level",
        "active_devices",
        "alerts_trend",
        "consecutive_devices",
        "empty_county_records",
        "latest_device",
        "pest_detail",
        "region_disposal",
        "sms_empty",
        "soil_detail",
        "subtype_ratio",
        "city_day_change",
        "highest_values",
        "threshold_summary",
        "unknown_region_devices",
        "unmatched_region_records",
    }

    PLAYBOOK_UPGRADEABLE_QUERY_TYPES = {"count", "top", "structured_agri"}
    GREETING_PATTERNS = SemanticJudger.GREETING_PATTERNS

    def __init__(
        self,
        intent_router=None,
        playbook_router=None,
        semantic_judger: SemanticJudger | None = None,
        semantic_parser: SemanticParser | None = None,
    ):
        """注入可选的意图路由器与 playbook 路由器。"""
        self.intent_router = intent_router
        self.playbook_router = playbook_router
        self.semantic_judger = semantic_judger or SemanticJudger()
        self.semantic_parser = semantic_parser or SemanticParser()

    def _parse_semantics(self, question: str, context: dict | None = None) -> SemanticParseResult:
        try:
            raw = self.semantic_parser.parse(question, context=context)
        except Exception:
            return SemanticParseResult(normalized_query=str(question or "").strip())
        if isinstance(raw, SemanticParseResult):
            return raw
        if isinstance(raw, dict):
            return SemanticParseResult.from_dict(raw)
        return SemanticParseResult(normalized_query=str(question or "").strip())

    @staticmethod
    def _is_agri_query_type(query_type: str) -> bool:
        return query_type in {
            "pest_detail",
            "pest_top",
            "pest_overview",
            "soil_detail",
            "soil_top",
            "soil_overview",
            "pest_trend",
            "soil_trend",
            "pest_forecast",
            "soil_forecast",
            "joint_risk",
            "structured_agri",
        }

    def _score_data(self, question: str) -> float:
        return score_data(question)

    def _score_advice(self, question: str) -> float:
        return score_advice(question)

    def _extract_day_range(self, question: str) -> tuple[Optional[str], Optional[str]]:
        return extract_day_range(question)

    def _extract_city(self, question: str) -> Optional[str]:
        return extract_city(question)

    def _extract_county(self, question: str) -> Optional[str]:
        return extract_county(question)

    @staticmethod
    def _asks_for_county_scope(question: str) -> bool:
        return asks_for_county_scope(question)

    def _extract_device_code(self, question: str) -> Optional[str]:
        return extract_device_code(question)

    def _extract_top_n(self, question: str) -> Optional[int]:
        return extract_top_n(question)

    @staticmethod
    def _asks_for_multiple_ranked_results(question: str) -> bool:
        return query_asks_for_multiple_ranked_results(question)

    def _default_top_n(self, question: str, query_type: str) -> Optional[int]:
        return query_default_top_n(question, query_type)

    def _extract_relative_window(self, question: str) -> tuple[Optional[str], Optional[str], dict]:
        return extract_relative_window(question)

    def _extract_future_window(self, question: str) -> dict | None:
        return extract_future_window(question)

    @classmethod
    def _parse_number_token(cls, token: str) -> int:
        return parse_number_token(token)

    def _infer_query_type(self, question: str) -> str:
        return infer_query_type(
            question,
            extract_city=self._extract_city,
            extract_county=self._extract_county,
            extract_future_window=self._extract_future_window,
            extract_relative_window=self._extract_relative_window,
            extract_day_range=self._extract_day_range,
            has_negated_trend=self._has_negated_trend,
            extract_device_code=self._extract_device_code,
        )

    def _build_route(self, question: str, query_type: str) -> dict:
        return build_query_route(question, query_type)

    def _normalize_router_route(self, question: str, route: dict) -> dict:
        return normalize_router_route(
            question,
            route,
            infer_query_type_fn=self._infer_query_type,
            is_agri_query_type=self._is_agri_query_type,
            deterministic_query_types=self.DETERMINISTIC_QUERY_TYPES,
        )

    def _merge_router_route(self, question: str, route: dict) -> dict:
        return merge_router_route(question, route, build_route=self._build_route)

    def _is_low_signal(self, question: str) -> bool:
        return is_low_signal(question, is_greeting_question=self._is_greeting_question)

    @classmethod
    def _out_of_scope_capability_reply(cls, question: str) -> str | None:
        return SemanticJudger.out_of_scope_capability_reply(question)

    @classmethod
    def _is_generic_explanation_question(cls, question: str) -> bool:
        return SemanticJudger.is_generic_explanation_question(question)

    @staticmethod
    def _is_out_of_scope_reason(reason: str) -> bool:
        return SemanticJudger.is_out_of_scope_reason(reason)

    @classmethod
    def _semantic_context_trace(cls, reason: str, parse_trace: list[str] | None = None) -> list[str]:
        trace = list(parse_trace or [])
        normalized_reason = str(reason or "")
        if not normalized_reason:
            return trace
        if cls._is_out_of_scope_reason(normalized_reason):
            if "ood" not in trace:
                trace.append("ood")
            ood_tag = f"ood:{normalized_reason}"
            if ood_tag not in trace:
                trace.append(ood_tag)
            return trace
        if normalized_reason in {SemanticJudger.REASON_GREETING, SemanticJudger.REASON_IDENTITY}:
            if "edge" not in trace:
                trace.append("edge")
            edge_tag = f"edge:{normalized_reason}"
            if edge_tag not in trace:
                trace.append(edge_tag)
        return trace

    @staticmethod
    def _safe_confidence(value: object) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        return max(0.0, min(0.99, round(numeric, 2)))

    @classmethod
    def _semantic_confidence(cls, parse_result: SemanticParseResult, semantic_decision: dict, default: float = 0.0) -> float:
        parse_confidence = cls._safe_confidence(parse_result.confidence)
        decision_confidence = cls._safe_confidence((semantic_decision or {}).get("confidence"))
        if parse_confidence > 0 and decision_confidence > 0:
            blended = round((parse_confidence * 0.7) + (decision_confidence * 0.3), 2)
            return cls._safe_confidence(max(parse_confidence, blended))
        if parse_confidence > 0:
            return parse_confidence
        if decision_confidence > 0:
            return decision_confidence
        return cls._safe_confidence(default)

    def _needs_agri_domain_clarification(self, question: str) -> bool:
        return needs_agri_domain_clarification(question, build_route=self._build_route)

    @staticmethod
    def _domain_from_query_type(query_type: str) -> str | None:
        return domain_from_query_type(query_type)

    def _infer_domain_from_text(self, question: str, context: dict | None = None) -> str:
        return infer_domain_from_text(question, str((context or {}).get("domain") or ""))

    @staticmethod
    def _answer_mode_for_plan(intent: str, route: dict, needs_clarification: bool) -> str:
        return answer_mode_for_plan(intent, route, needs_clarification)

    def _typed_metadata(self, question: str, route: dict, intent: str, needs_clarification: bool, context: dict | None, understanding: dict | None) -> dict:
        from .query_intent_routing import typed_metadata
        return typed_metadata(
            question,
            route,
            intent,
            needs_clarification,
            context,
            understanding,
            is_greeting_question=self._is_greeting_question,
            domain_from_query_type_fn=self._domain_from_query_type,
            infer_domain_from_text=self._infer_domain_from_text,
            is_scope_correction_follow_up=self._is_scope_correction_follow_up,
        )

    def _finalize_plan(self, plan: dict, question: str, context: dict | None = None, understanding: dict | None = None) -> dict:
        return finalize_plan(
            plan,
            question,
            context=context,
            understanding=understanding,
            is_greeting_question=self._is_greeting_question,
            domain_from_query_type_fn=self._domain_from_query_type,
            infer_domain_from_text=self._infer_domain_from_text,
            is_scope_correction_follow_up=self._is_scope_correction_follow_up,
        )

    @staticmethod
    def _has_actionable_canonical_understanding(understanding: dict | None) -> bool:
        canonical = canonical_understanding_payload(understanding)
        return bool(
            canonical.get("domain")
            and canonical.get("task_type") not in {"", "unknown"}
            and not canonical.get("needs_clarification")
        )

    def _context_follow_up_plan(self, question: str, context: dict | None, understanding: dict | None = None) -> dict | None:
        return build_context_follow_up_plan(self, question, context, understanding)

    @staticmethod
    def _looks_like_contextual_follow_up(question: str) -> bool:
        return looks_like_contextual_follow_up(question, is_greeting_question=QueryPlanner._is_greeting_question)

    @staticmethod
    def _has_detail_hint(question: str) -> bool:
        return has_detail_intent(question)

    @staticmethod
    def _has_negated_trend(question: str) -> bool:
        q = question or ""
        return any(token in q for token in ["不是趋势", "别看趋势", "不要趋势", "不看趋势"])

    @staticmethod
    def _has_domain_switch_verb(question: str) -> bool:
        return has_domain_switch_verb(question)

    @staticmethod
    def _is_advice_follow_up(question: str) -> bool:
        return is_advice_follow_up(question)

    @staticmethod
    def _is_explanation_follow_up(question: str) -> bool:
        return is_explanation_follow_up(question)

    @classmethod
    def _is_detail_follow_up(cls, question: str) -> bool:
        return is_detail_follow_up(question)

    @staticmethod
    def _explicit_domain_from_text(question: str) -> str:
        return explicit_domain_from_text(question)

    @staticmethod
    def _query_type_for_domain_switch(previous_query_type: str, next_domain: str) -> str:
        return query_type_for_domain_switch(previous_query_type, next_domain)

    @staticmethod
    def _query_type_for_region_follow_up(previous_query_type: str, domain: str) -> str:
        return query_type_for_region_follow_up(previous_query_type, domain)

    @staticmethod
    def _query_type_for_window_follow_up(previous_query_type: str, domain: str) -> str:
        return query_type_for_window_follow_up(previous_query_type, domain)

    def _playbook_route(self, question: str, context: dict | None = None) -> dict | None:
        """尝试走 playbook 路由，并确保结果是农业数据查询类型。"""
        if self.playbook_router is None:
            return None
        try:
            route = self.playbook_router.route(question, context=context)
        except Exception:
            return None
        if not isinstance(route, dict):
            return None
        query_type = str(route.get("query_type") or "")
        intent = str(route.get("intent") or "data_query")
        if intent != "data_query" or not self._is_agri_query_type(query_type):
            return None
        return route

    def _should_use_playbook_route(self, question: str, heuristic_query_type: str, playbook_route: dict | None, context: dict | None = None) -> bool:
        """判断当前问题是否应由 playbook 结果覆盖基础启发式结果。"""
        return should_use_playbook_route(
            question=question,
            heuristic_query_type=heuristic_query_type,
            playbook_route=playbook_route,
            deterministic_query_types=self.DETERMINISTIC_QUERY_TYPES,
            playbook_upgradeable_query_types=self.PLAYBOOK_UPGRADEABLE_QUERY_TYPES,
            context=context,
        )

    @staticmethod
    def _playbook_context_trace(playbook_route: dict) -> list[str]:
        return playbook_context_trace(playbook_route)

    def _resolve_follow_up_question(self, question: str, history: object, context: dict | None = None) -> str:
        """将“短追问”与历史主问题合并成完整问题文本。"""
        return resolve_follow_up_question(question, history=history, context=context)

    @staticmethod
    def _is_identity_question(question: str) -> bool:
        return SemanticJudger.is_identity_question(question)

    @classmethod
    def _is_greeting_question(cls, question: str) -> bool:
        return SemanticJudger.is_greeting_question(question)

    @staticmethod
    def _is_scope_correction_follow_up(question: str) -> bool:
        return is_scope_correction_follow_up(question)

    @staticmethod
    def _has_placeholder_entity(question: str) -> bool:
        q = question or ""
        return any(
            token in q
            for token in [
                "某设备",
                "某县",
                "某市",
                "某地区",
                "某区域",
                "某个设备",
                "某个县",
                "这个县",
                "该县",
                "这个市",
                "该市",
                "这个地区",
                "该地区",
                "这个区域",
                "该区域",
            ]
        )

    @staticmethod
    def _refine_structured_agri_route(route: dict, understanding: dict | None) -> dict:
        """把 `structured_agri` 细化成更具体 query_type。

        当上游理解层已给出领域/任务类型时，这里做一次定向细化，
        降低后续执行层的分支复杂度。
        """
        refined = dict(route or {})
        understanding = dict(understanding or {})
        if str(refined.get("query_type") or "") != "structured_agri":
            return refined
        domain = str(understanding.get("domain") or "")
        task_type = str(understanding.get("task_type") or "")
        region_name = str(understanding.get("region_name") or "")
        if domain not in {"pest", "soil"}:
            return refined
        if task_type == "data_detail":
            refined["query_type"] = f"{domain}_detail"
        elif task_type == "trend":
            refined["query_type"] = f"{domain}_trend"
        elif task_type == "ranking":
            refined["query_type"] = f"{domain}_top"
        elif task_type == "joint_risk":
            refined["query_type"] = "joint_risk"
        elif region_name:
            refined["query_type"] = f"{domain}_overview"
        else:
            refined["query_type"] = f"{domain}_top"
        return refined

    def plan(self, question: str, history: object = None, context: dict | None = None, understanding: dict | None = None) -> dict:
        """生成最终查询计划。

        主要决策顺序：
        1) 问候/身份问题快速返回
        2) 上下文追问复用
        3) 低信号与歧义澄清
        4) playbook/外部路由优先
        5) 本地启发式兜底
        """
        original_question = question
        question = self._resolve_follow_up_question(question, history, context=context)
        parse_result = self._parse_semantics(question, context=context)
        if parse_result.normalized_query:
            question = parse_result.normalized_query
        semantic_decision = self.semantic_judger.judge(question)
        semantic_confidence = self._semantic_confidence(parse_result, semantic_decision)
        semantic_reason = str(parse_result.fallback_reason or semantic_decision.get("fallback_reason") or semantic_decision.get("reason") or "")
        if parse_result.is_out_of_scope:
            out_of_scope_reason = semantic_reason if self._is_out_of_scope_reason(semantic_reason) else "out_of_scope_capability"
            clarification = (
                semantic_decision.get("clarification")
                or self._out_of_scope_capability_reply(question)
                or "我目前主要支持农业虫情、墒情、预警数据分析。你可以告诉我地区和时间范围，我帮你查询虫情或墒情。"
            )
            return self._finalize_plan({
                "intent": str(parse_result.intent or semantic_decision.get("intent") or "advice"),
                "confidence": self._semantic_confidence(parse_result, semantic_decision, default=0.9),
                "route": self._build_route(question, "count"),
                "needs_clarification": True,
                "clarification": clarification,
                "reason": out_of_scope_reason,
                "context_trace": self._semantic_context_trace(out_of_scope_reason, parse_result.trace),
            }, question, context=context, understanding=understanding)
        if semantic_reason == SemanticJudger.REASON_GREETING:
            return self._finalize_plan({
                "intent": str(semantic_decision.get("intent") or "advice"),
                "confidence": self._semantic_confidence(parse_result, semantic_decision, default=0.95),
                "route": self._build_route(question, "count"),
                "needs_clarification": bool(semantic_decision.get("needs_clarification")),
                "clarification": semantic_decision.get("clarification"),
                "reason": SemanticJudger.REASON_GREETING,
                "context_trace": self._semantic_context_trace(SemanticJudger.REASON_GREETING, parse_result.trace),
            }, question, context=context, understanding=understanding)
        if parse_result.needs_clarification or semantic_confidence < 0.35:
            return self._finalize_plan({
                "intent": "advice",
                "confidence": semantic_confidence,
                "route": self._build_route(question, "structured_agri"),
                "needs_clarification": True,
                "clarification": "请补充你要查询的领域、地区或时间范围，我再继续查询。",
                "reason": "semantic_low_confidence",
                "context_trace": list(parse_result.trace),
            }, question, context=context, understanding=understanding)
        if context_follow_up := self._context_follow_up_plan(original_question, context, understanding):
            # 若识别为上下文追问，优先复用线程状态，避免重复抽取和重复提问。
            return self._finalize_plan(context_follow_up, question, context=context, understanding=understanding)
        if self._has_actionable_canonical_understanding(understanding):
            canonical = canonical_understanding_payload(understanding)
            route = route_from_canonical_understanding(
                understanding,
                self._build_route(question, self._infer_query_type(question)),
            )
            if (
                isinstance(understanding, dict)
                and understanding.get("needs_advice")
                and not understanding.get("needs_historical")
                and not understanding.get("needs_forecast")
                and not understanding.get("needs_explanation")
            ):
                return self._finalize_plan({
                    "intent": "advice",
                    "confidence": max(semantic_confidence, 0.88),
                    "route": route,
                    "needs_clarification": False,
                    "clarification": None,
                    "reason": "understanding_advice_follow_up",
                    "context_trace": ["canonical understanding reused"],
                }, question, context=context, understanding=understanding)
            if (
                isinstance(understanding, dict)
                and understanding.get("needs_historical")
                and canonical.get("domain") in {"pest", "soil", "mixed"}
            ):
                return self._finalize_plan({
                    "intent": "data_query",
                    "confidence": max(semantic_confidence, 0.88),
                    "route": route,
                    "needs_clarification": False,
                    "clarification": None,
                    "reason": "understanding_historical_data_query",
                    "context_trace": ["canonical understanding reused"],
                }, question, context=context, understanding=understanding)
            if (
                isinstance(understanding, dict)
                and understanding.get("needs_forecast")
                and canonical.get("domain") in {"pest", "soil"}
            ):
                return self._finalize_plan({
                    "intent": "data_query",
                    "confidence": max(semantic_confidence, 0.88),
                    "route": route,
                    "needs_clarification": False,
                    "clarification": None,
                    "reason": "understanding_forecast_data_query",
                    "context_trace": ["canonical understanding reused"],
                }, question, context=context, understanding=understanding)
        if semantic_reason == SemanticJudger.REASON_IDENTITY:
            return self._finalize_plan({
                "intent": str(semantic_decision.get("intent") or "advice"),
                "confidence": self._semantic_confidence(parse_result, semantic_decision, default=0.92),
                "route": self._build_route(question, "count"),
                "needs_clarification": bool(semantic_decision.get("needs_clarification")),
                "clarification": semantic_decision.get("clarification"),
                "reason": SemanticJudger.REASON_IDENTITY,
                "context_trace": self._semantic_context_trace(SemanticJudger.REASON_IDENTITY, parse_result.trace),
            }, question, context=context, understanding=understanding)
        if self._is_out_of_scope_reason(semantic_reason):
            return self._finalize_plan({
                "intent": str(semantic_decision.get("intent") or "advice"),
                "confidence": self._semantic_confidence(parse_result, semantic_decision, default=0.9),
                "route": self._build_route(question, "count"),
                "needs_clarification": bool(semantic_decision.get("needs_clarification")),
                "clarification": semantic_decision.get("clarification"),
                "reason": semantic_reason,
                "context_trace": self._semantic_context_trace(semantic_reason, parse_result.trace),
            }, question, context=context, understanding=understanding)
        if semantic_reason == SemanticJudger.REASON_GENERIC_EXPLANATION:
            return self._finalize_plan({
                "intent": str(semantic_decision.get("intent") or "advice"),
                "confidence": self._semantic_confidence(parse_result, semantic_decision, default=0.72),
                "route": self._build_route(question, "count"),
                "needs_clarification": bool(semantic_decision.get("needs_clarification")),
                "clarification": semantic_decision.get("clarification"),
                "reason": SemanticJudger.REASON_GENERIC_EXPLANATION,
                "context_trace": [],
            }, question, context=context, understanding=understanding)
        if self._is_low_signal(question):
            return self._finalize_plan({
                "intent": "advice",
                "confidence": 0.0,
                "route": self._build_route(question, "count"),
                "needs_clarification": True,
                "clarification": "你这条输入信息不足。请告诉我：要做数据统计，还是要处置建议？",
                "reason": "low_signal",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        if self._needs_agri_domain_clarification(question):
            return self._finalize_plan({
                "intent": "advice",
                "confidence": 0.4,
                "route": self._build_route(question, "structured_agri"),
                "needs_clarification": True,
                "clarification": "你想看虫情还是墒情？比如可以问：近3个星期虫情最严重的地方是哪里，或者近3个星期墒情异常最严重的地方是哪里。",
                "reason": "agri_domain_ambiguous",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        heuristic_query_type = self._infer_query_type(question)
        if self._has_placeholder_entity(question):
            return self._finalize_plan({
                "intent": "advice",
                "confidence": 0.3,
                "route": self._build_route(question, heuristic_query_type),
                "needs_clarification": True,
                "clarification": "请补充具体对象，比如设备编码、县名或市名，我再继续查询。",
                "reason": "placeholder_entity_clarification",
                "context_trace": [],
            }, question, context=context, understanding=understanding)
        playbook_route = self._playbook_route(question, context=context)
        if self._should_use_playbook_route(question, heuristic_query_type, playbook_route, context=context):
            return self._finalize_plan({
                "intent": "data_query",
                "confidence": 0.88,
                "route": self._merge_router_route(
                    question,
                    {
                        "query_type": playbook_route.get("query_type"),
                    },
                ),
                "needs_clarification": False,
                "clarification": None,
                "reason": "playbook_data_query",
                "context_trace": self._playbook_context_trace(playbook_route),
            }, question, context=context, understanding=understanding)

        if self.intent_router is not None:
            try:
                route = self._normalize_router_route(question, self.intent_router.route(question))
                intent = route.get("intent", "advice")
                if intent == "data_query":
                    return self._finalize_plan({
                        "intent": "data_query",
                        "confidence": 0.95,
                        "route": self._merge_router_route(question, route),
                        "needs_clarification": False,
                        "clarification": None,
                        "reason": "router_data_query",
                        "context_trace": [],
                    }, question, context=context, understanding=understanding)
                if not (
                    isinstance(understanding, dict)
                    and understanding.get("needs_historical")
                    and str(understanding.get("domain") or "") in {"pest", "soil", "mixed"}
                ):
                    return self._finalize_plan({
                        "intent": "advice",
                        "confidence": 0.9,
                        "route": route,
                        "needs_clarification": False,
                        "clarification": None,
                        "reason": "router_advice",
                        "context_trace": [],
                    }, question, context=context, understanding=understanding)
            except Exception:
                # 路由器异常不应中断主链路，继续走本地启发式兜底。
                pass

        route = self._refine_structured_agri_route(self._build_route(question, heuristic_query_type), understanding)

        if "处置建议" in question and ("镇" in question or "街道" in question or re.search(r"SNS\d+", question)):
            return self._finalize_plan({
                "intent": "data_query",
                "confidence": 0.9,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "heuristic_region_disposal_data_query",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        inferred_domain = self._infer_domain_from_text(question, context)
        relative_since, _, relative_window = self._extract_relative_window(question)
        day_since, _ = self._extract_day_range(question)
        future_window = self._extract_future_window(question)
        has_historical_scope = bool(
            day_since
            or relative_since
            or relative_window.get("window_type") == "year_since"
            or "今年以来" in question
            or route.get("city")
            or route.get("county")
            or (isinstance(understanding, dict) and understanding.get("needs_historical"))
        )
        if (
            needs_explanation(question)
            and inferred_domain in {"pest", "soil"}
            and has_historical_scope
            and not needs_advice(question)
            and not future_window
            and not has_ranking_intent(question)
        ):
            # “解释型问题 + 已有历史范围”优先落到 overview 数据查询，再由回答层解释。
            explanation_route = self._build_route(question, f"{inferred_domain}_overview")
            return self._finalize_plan({
                "intent": "data_query",
                "confidence": 0.87,
                "route": explanation_route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "explanation_grounded_data_query",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        if (
            isinstance(understanding, dict)
            and understanding.get("needs_advice")
            and not understanding.get("needs_historical")
            and not understanding.get("needs_forecast")
            and not understanding.get("needs_explanation")
        ):
            return self._finalize_plan({
                "intent": "advice",
                "confidence": 0.88,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "understanding_advice_follow_up",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        if (
            isinstance(understanding, dict)
            and understanding.get("needs_historical")
            and str(understanding.get("domain") or "") in {"pest", "soil", "mixed"}
        ):
            return self._finalize_plan({
                "intent": "data_query",
                "confidence": 0.88,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "understanding_historical_data_query",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        if route.get("query_type") in {
            "active_devices",
            "alerts_trend",
            "empty_county_records",
            "pest_top",
            "pest_detail",
            "soil_top",
            "soil_detail",
            "pest_trend",
            "soil_trend",
            "pest_overview",
            "soil_overview",
            "joint_risk",
            "pest_forecast",
            "soil_forecast",
            "unknown_region_devices",
            "unmatched_region_records",
        }:
            return self._finalize_plan({
                "intent": "data_query",
                "confidence": 0.85,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "heuristic_agri_data_query",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        data_score = self._score_data(question)
        advice_score = self._score_advice(question)

        if (
            re.search(r"(这个|这种|该).*(怎么办|如何处理|怎么处理)", question)
            and not re.search(r"(预警|设备|城市|区县|告警|处置建议|台风|小麦|虫情|墒情)", question)
        ):
            return self._finalize_plan({
                "intent": "advice",
                "confidence": max(data_score, advice_score),
                "route": route,
                "needs_clarification": True,
                "clarification": "你希望我做数据统计，还是生成处置建议？可以补充时间范围或地区。",
                "reason": "generic_ambiguous",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        if data_score >= 0.55 and data_score > advice_score + 0.1:
            return self._finalize_plan({
                "intent": "data_query",
                "confidence": data_score,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "heuristic_data_query",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        if advice_score >= 0.55 and advice_score >= data_score:
            return self._finalize_plan({
                "intent": "advice",
                "confidence": advice_score,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "heuristic_advice",
                "context_trace": [],
            }, question, context=context, understanding=understanding)

        return self._finalize_plan({
            "intent": "advice",
            "confidence": max(data_score, advice_score),
            "route": route,
            "needs_clarification": True,
            "clarification": "你希望我做数据统计，还是生成处置建议？可以补充时间范围或地区。",
            "reason": "ambiguous",
            "context_trace": [],
        }, question, context=context, understanding=understanding)
