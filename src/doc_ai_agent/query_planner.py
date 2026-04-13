from __future__ import annotations

import re
from typing import Optional

from .agri_semantics import (
    has_detail_intent,
    infer_domain_from_text,
    needs_advice,
    needs_explanation,
    needs_forecast,
)
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


class QueryPlanner:
    CHINESE_NUMBER_MAP = CHINESE_NUMBER_MAP
    DETERMINISTIC_QUERY_TYPES = {
        "avg_by_level",
        "consecutive_devices",
        "latest_device",
        "pest_detail",
        "region_disposal",
        "sms_empty",
        "soil_detail",
        "subtype_ratio",
        "city_day_change",
        "highest_values",
        "threshold_summary",
    }

    PLAYBOOK_UPGRADEABLE_QUERY_TYPES = {"count", "top", "structured_agri"}
    GREETING_PATTERNS = {
        "你好",
        "您好",
        "嗨",
        "哈喽",
        "hello",
        "hi",
        "早上好",
        "上午好",
        "中午好",
        "下午好",
        "晚上好",
    }

    def __init__(self, intent_router=None, playbook_router=None):
        self.intent_router = intent_router
        self.playbook_router = playbook_router

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

    def _context_follow_up_plan(self, question: str, context: dict | None) -> dict | None:
        return build_context_follow_up_plan(self, question, context)

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
        return resolve_follow_up_question(question, history=history, context=context)

    @staticmethod
    def _is_identity_question(question: str) -> bool:
        stripped = (question or "").strip().rstrip("？?")
        return stripped in {"你是谁", "你是干什么的", "你能做什么", "你可以做什么"}

    @classmethod
    def _is_greeting_question(cls, question: str) -> bool:
        stripped = (question or "").strip().rstrip("？?！!。").lower()
        if not stripped:
            return False
        if stripped in cls.GREETING_PATTERNS:
            return True
        return bool(re.fullmatch(r"(你好吗|最近好吗|在吗)", stripped))

    @staticmethod
    def _is_scope_correction_follow_up(question: str) -> bool:
        return is_scope_correction_follow_up(question)

    def plan(self, question: str, history: object = None, context: dict | None = None, understanding: dict | None = None) -> dict:
        original_question = question
        question = self._resolve_follow_up_question(question, history, context=context)
        if self._is_greeting_question(question):
            return self._finalize_plan({
                "intent": "advice",
                "confidence": 0.98,
                "route": self._build_route(question, "count"),
                "needs_clarification": False,
                "clarification": None,
                "reason": "greeting_intro",
                "context_trace": [],
            }, question, context=context, understanding=understanding)
        if context_follow_up := self._context_follow_up_plan(original_question, context):
            return self._finalize_plan(context_follow_up, question, context=context, understanding=understanding)
        if self._is_identity_question(question):
            return self._finalize_plan({
                "intent": "advice",
                "confidence": 0.95,
                "route": self._build_route(question, "count"),
                "needs_clarification": False,
                "clarification": None,
                "reason": "identity_self_intro",
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
                pass

        route = self._build_route(question, heuristic_query_type)

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

        if route.get("query_type") in {
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
