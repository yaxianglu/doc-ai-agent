"""Centralized semantic edge-case arbitration for planner/advice layers."""

from __future__ import annotations

import re

from .agri_semantics import needs_explanation


class SemanticJudger:
    """Judge edge-case intent before normal query planning."""

    REASON_GREETING = "greeting_intro"
    REASON_IDENTITY = "identity_self_intro"
    REASON_GENERIC_EXPLANATION = "generic_explanation"
    REASON_OOD_WEATHER = "out_of_scope_weather"
    REASON_OOD_NEWS = "out_of_scope_news"
    REASON_OOD_TRANSPORT_TICKET = "out_of_scope_transport_ticket"
    REASON_OOD_TYPHOON = "out_of_scope_typhoon"
    REASON_OOD_CAPABILITY = "out_of_scope_capability"

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
    AGRI_SIGNAL_PATTERN = re.compile(r"(虫情|虫害|墒情|预警|报警|农情|作物|农田|田块|小麦|水稻|玉米|病害|灌排|补灌|排水)")
    WEATHER_SIGNAL_PATTERN = re.compile(r"(天气|下雨|降雨|气温|温度|天气预报)")
    NEWS_SIGNAL_PATTERN = re.compile(r"新闻")
    TICKET_SIGNAL_PATTERN = re.compile(r"(高铁票|火车票|车票|订票)")
    TYPHOON_SIGNAL_PATTERN = re.compile(r"台风")
    STOCK_SIGNAL_PATTERN = re.compile(r"(股价|股票|A股|港股|美股)")
    SPORTS_SIGNAL_PATTERN = re.compile(r"(体育|比赛|球赛|NBA|CBA|足球)")
    GENERIC_EXPLANATION_PATTERN = re.compile(r"(从数据看|这次异常|未知区域|为什么会这样|为何会这样)")
    CAPABILITY_SCOPE_PATTERN = re.compile(r"(主要能回答什么问题|主要支持什么|能回答什么问题|支持查.+吗|支持.+么|能查.+吗|能不能查.+)")
    NEGATED_AGRI_PATTERN = re.compile(r"(不是|先别|别|不要).{0,4}农情")
    IDENTITY_QUESTIONS = {"你是谁", "你是干什么的", "你能做什么", "你可以做什么"}
    OUT_OF_SCOPE_REASON_PATTERNS = (
        (REASON_OOD_WEATHER, WEATHER_SIGNAL_PATTERN),
        (REASON_OOD_NEWS, NEWS_SIGNAL_PATTERN),
        (REASON_OOD_TRANSPORT_TICKET, TICKET_SIGNAL_PATTERN),
        (REASON_OOD_TYPHOON, TYPHOON_SIGNAL_PATTERN),
        (REASON_OOD_CAPABILITY, STOCK_SIGNAL_PATTERN),
        (REASON_OOD_CAPABILITY, SPORTS_SIGNAL_PATTERN),
    )
    OUT_OF_SCOPE_REASON_REPLIES = {
        REASON_OOD_WEATHER: "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供天气查询。你如果要看农情，我可以继续帮你查某个地区、时间范围内的虫情或墒情情况。",
        REASON_OOD_NEWS: "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供通用新闻检索。你如果要看农情，我可以继续帮你查相关地区的历史、趋势、预测或处置建议。",
        REASON_OOD_TRANSPORT_TICKET: "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供购票或车次查询。你如果要看农情，我可以继续帮你查相关地区的监测数据和建议。",
        REASON_OOD_TYPHOON: "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供通用台风动态查询。你如果想评估台风对农业的影响，可以直接告诉我地区、作物或风险场景。",
        REASON_OOD_CAPABILITY: "我目前主要支持农业虫情、墒情、预警数据分析，包括历史查询、趋势分析、风险预测和处置建议。股价、体育新闻这类通用信息我暂不直接提供；如果你要看农情，可以直接告诉我地区和时间范围。",
    }

    @classmethod
    def is_out_of_scope_reason(cls, reason: str) -> bool:
        return str(reason or "") in cls.OUT_OF_SCOPE_REASON_REPLIES

    @classmethod
    def is_identity_question(cls, question: str) -> bool:
        stripped = str(question or "").strip().rstrip("？?")
        return stripped in cls.IDENTITY_QUESTIONS or bool(re.search(r"(告诉我|说说|介绍一下).*(你是谁|你是干什么的)", stripped))

    @classmethod
    def is_greeting_question(cls, question: str) -> bool:
        stripped = str(question or "").strip().rstrip("？?！!。").lower()
        if not stripped:
            return False
        if stripped in cls.GREETING_PATTERNS:
            return True
        return bool(re.fullmatch(r"(你好吗|最近好吗|在吗)", stripped))

    @classmethod
    def out_of_scope_capability_category(cls, question: str) -> str:
        normalized = str(question or "").strip()
        if not normalized:
            return ""
        if cls.NEGATED_AGRI_PATTERN.search(normalized):
            return cls.REASON_OOD_CAPABILITY
        if cls.CAPABILITY_SCOPE_PATTERN.search(normalized):
            return cls.REASON_OOD_CAPABILITY
        if cls.AGRI_SIGNAL_PATTERN.search(normalized):
            return ""
        for reason, pattern in cls.OUT_OF_SCOPE_REASON_PATTERNS:
            if pattern.search(normalized):
                return reason
        return ""

    @classmethod
    def out_of_scope_capability_reply(cls, question: str) -> str | None:
        reason = cls.out_of_scope_capability_category(question)
        if not reason:
            return None
        return cls.OUT_OF_SCOPE_REASON_REPLIES.get(reason)

    @classmethod
    def is_generic_explanation_question(cls, question: str) -> bool:
        normalized = str(question or "").strip()
        if len(normalized) < 8:
            return False
        if not needs_explanation(normalized):
            return False
        return bool(cls.GENERIC_EXPLANATION_PATTERN.search(normalized))

    def judge(self, question: str) -> dict:
        """Return a normalized semantic edge decision payload."""
        if self.is_greeting_question(question):
            return {
                "reason": self.REASON_GREETING,
                "fallback_reason": self.REASON_GREETING,
                "intent": "advice",
                "confidence": 0.98,
                "needs_clarification": False,
                "clarification": None,
            }
        if out_of_scope_reason := self.out_of_scope_capability_category(question):
            return {
                "reason": out_of_scope_reason,
                "fallback_reason": out_of_scope_reason,
                "intent": "advice",
                "confidence": 0.92,
                "needs_clarification": True,
                "clarification": self.OUT_OF_SCOPE_REASON_REPLIES[out_of_scope_reason],
            }
        if self.is_identity_question(question):
            return {
                "reason": self.REASON_IDENTITY,
                "fallback_reason": self.REASON_IDENTITY,
                "intent": "advice",
                "confidence": 0.95,
                "needs_clarification": False,
                "clarification": None,
            }
        if self.is_generic_explanation_question(question):
            return {
                "reason": self.REASON_GENERIC_EXPLANATION,
                "fallback_reason": self.REASON_GENERIC_EXPLANATION,
                "intent": "advice",
                "confidence": 0.78,
                "needs_clarification": False,
                "clarification": None,
            }
        return {
            "reason": "",
            "fallback_reason": "",
            "intent": "advice",
            "confidence": 0.0,
            "needs_clarification": False,
            "clarification": None,
        }
