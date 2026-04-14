"""Centralized semantic edge-case arbitration for planner/advice layers."""

from __future__ import annotations

import re

from .agri_semantics import needs_explanation


class SemanticJudger:
    """Judge edge-case intent before normal query planning."""

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
    GENERIC_EXPLANATION_PATTERN = re.compile(r"(从数据看|这次异常|未知区域|为什么会这样|为何会这样)")
    IDENTITY_QUESTIONS = {"你是谁", "你是干什么的", "你能做什么", "你可以做什么"}

    @classmethod
    def is_identity_question(cls, question: str) -> bool:
        stripped = str(question or "").strip().rstrip("？?")
        return stripped in cls.IDENTITY_QUESTIONS

    @classmethod
    def is_greeting_question(cls, question: str) -> bool:
        stripped = str(question or "").strip().rstrip("？?！!。").lower()
        if not stripped:
            return False
        if stripped in cls.GREETING_PATTERNS:
            return True
        return bool(re.fullmatch(r"(你好吗|最近好吗|在吗)", stripped))

    @classmethod
    def out_of_scope_capability_reply(cls, question: str) -> str | None:
        normalized = str(question or "").strip()
        if not normalized or cls.AGRI_SIGNAL_PATTERN.search(normalized):
            return None
        if cls.WEATHER_SIGNAL_PATTERN.search(normalized):
            return "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供天气查询。你如果要看农情，我可以继续帮你查某个地区、时间范围内的虫情或墒情情况。"
        if cls.NEWS_SIGNAL_PATTERN.search(normalized):
            return "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供通用新闻检索。你如果要看农情，我可以继续帮你查相关地区的历史、趋势、预测或处置建议。"
        if cls.TICKET_SIGNAL_PATTERN.search(normalized):
            return "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供购票或车次查询。你如果要看农情，我可以继续帮你查相关地区的监测数据和建议。"
        if cls.TYPHOON_SIGNAL_PATTERN.search(normalized):
            return "我目前主要支持农业虫情、墒情、预警数据分析，暂不直接提供通用台风动态查询。你如果想评估台风对农业的影响，可以直接告诉我地区、作物或风险场景。"
        return None

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
                "reason": "greeting_intro",
                "intent": "advice",
                "confidence": 0.98,
                "needs_clarification": False,
                "clarification": None,
            }
        if self.is_identity_question(question):
            return {
                "reason": "identity_self_intro",
                "intent": "advice",
                "confidence": 0.95,
                "needs_clarification": False,
                "clarification": None,
            }
        if out_of_scope_reply := self.out_of_scope_capability_reply(question):
            return {
                "reason": "out_of_scope_capability",
                "intent": "advice",
                "confidence": 0.92,
                "needs_clarification": True,
                "clarification": out_of_scope_reply,
            }
        if self.is_generic_explanation_question(question):
            return {
                "reason": "generic_explanation",
                "intent": "advice",
                "confidence": 0.78,
                "needs_clarification": False,
                "clarification": None,
            }
        return {
            "reason": "",
            "intent": "advice",
            "confidence": 0.0,
            "needs_clarification": False,
            "clarification": None,
        }

