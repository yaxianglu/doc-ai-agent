from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional


class QueryPlanner:
    def __init__(self, intent_router=None):
        self.intent_router = intent_router

    def _score_data(self, question: str) -> float:
        q = question.lower()
        score = 0.0
        for token, weight in [
            ("多少", 0.35),
            ("top", 0.3),
            ("统计", 0.3),
            ("哪几个", 0.25),
            ("哪个", 0.2),
            ("平均", 0.3),
            ("分组", 0.2),
            ("连续两天", 0.35),
            ("设备", 0.2),
            ("最多", 0.2),
            ("区县", 0.2),
            ("最高", 0.2),
            ("记录", 0.2),
            ("告警值", 0.2),
            ("超过", 0.2),
            ("最近一次", 0.3),
            ("sms_content", 0.3),
            ("为空", 0.2),
            ("占比", 0.25),
            ("变化", 0.25),
            ("以来", 0.2),
            ("预警信息", 0.15),
        ]:
            if token in q:
                score += weight

        if re.search(r"20\d{2}年\d{1,2}月\d{1,2}日", question):
            score += 0.25
        if re.search(r"20\d{2}年以?来", question):
            score += 0.2
        if re.search(r"SNS\d+", question):
            score += 0.25
        if re.search(r"[\u4e00-\u9fa5]{2,12}市", question):
            score += 0.15
        return min(score, 1.0)

    def _score_advice(self, question: str) -> float:
        q = question.lower()
        score = 0.0
        for token, weight in [
            ("建议", 0.35),
            ("怎么办", 0.35),
            ("如何", 0.25),
            ("怎么", 0.25),
            ("注意", 0.2),
            ("需要", 0.15),
            ("处置", 0.25),
            ("预警", 0.2),
            ("措施", 0.3),
            ("清单", 0.25),
            ("排查", 0.2),
            ("判断依据", 0.25),
            ("短信版本", 0.35),
            ("短信", 0.2),
            ("改写", 0.3),
            ("台风", 0.2),
            ("给我", 0.1),
        ]:
            if token in q:
                score += weight
        return min(score, 1.0)

    def _extract_day_range(self, question: str) -> tuple[Optional[str], Optional[str]]:
        m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", question)
        if not m:
            return None, None
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        start = datetime(year, month, day)
        end = start + timedelta(days=1)
        return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")

    def _extract_city(self, question: str) -> Optional[str]:
        matches = re.findall(r"([\u4e00-\u9fa5]{2,12}市)", question)
        if matches:
            city = matches[-1]
            if city.startswith("日") and len(city) > 2:
                city = city[1:]
            return city
        return None

    def _extract_county(self, question: str) -> Optional[str]:
        m = re.search(r"([\u4e00-\u9fa5]{1,12}(?:县|区))", question)
        if m:
            return m.group(1)
        return None

    def _extract_device_code(self, question: str) -> Optional[str]:
        m = re.search(r"(SNS\d+)", question)
        if m:
            return m.group(1)
        return None

    def _infer_query_type(self, question: str) -> str:
        if "最近一次" in question and self._extract_device_code(question):
            return "latest_device"
        if "处置建议" in question and ("镇" in question or "街道" in question):
            return "region_disposal"
        if "sms_content" in question and "为空" in question:
            return "sms_empty"
        if "占比" in question and "子类型" in question:
            return "subtype_ratio"
        if "变化了多少" in question and "到" in question and "市" in question:
            return "city_day_change"
        if "最高" in question and "告警值" in question:
            return "highest_values"
        if "超过" in question and "告警值" in question:
            return "threshold_summary"
        if "连续两天" in question and "设备" in question:
            return "consecutive_devices"
        if ("平均" in question and "告警值" in question) or ("按告警等级分组" in question and "平均" in question):
            return "avg_by_level"
        if "top" in question.lower() or "前5" in question or "最多" in question:
            return "top"
        return "count"

    def _build_route(self, question: str, query_type: str) -> dict:
        since, until = self._extract_day_range(question)
        if since is None:
            m = re.search(r"(20\d{2})年以?来", question)
            if m:
                since = f"{m.group(1)}-01-01 00:00:00"
        if since is None:
            since = "1970-01-01 00:00:00"
        return {
            "query_type": query_type,
            "since": since,
            "until": until,
            "city": self._extract_city(question),
            "county": self._extract_county(question),
            "device_code": self._extract_device_code(question),
        }

    def plan(self, question: str) -> dict:
        if self.intent_router is not None:
            route = self.intent_router.route(question)
            intent = route.get("intent", "advice")
            if intent == "data_query":
                return {
                    "intent": "data_query",
                    "confidence": 0.95,
                    "route": route,
                    "needs_clarification": False,
                    "clarification": None,
                    "reason": "router_data_query",
                }
            return {
                "intent": "advice",
                "confidence": 0.9,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "router_advice",
            }

        query_type = self._infer_query_type(question)
        route = self._build_route(question, query_type)

        if "处置建议" in question and ("镇" in question or "街道" in question or re.search(r"SNS\d+", question)):
            return {
                "intent": "data_query",
                "confidence": 0.9,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "heuristic_region_disposal_data_query",
            }

        data_score = self._score_data(question)
        advice_score = self._score_advice(question)

        if (
            re.search(r"(这个|这种|该).*(怎么办|如何处理|怎么处理)", question)
            and not re.search(r"(预警|设备|城市|区县|告警|处置建议|台风|小麦)", question)
        ):
            return {
                "intent": "advice",
                "confidence": max(data_score, advice_score),
                "route": route,
                "needs_clarification": True,
                "clarification": "你希望我做数据统计查询，还是生成处置建议？可以补充时间范围或地区。",
                "reason": "generic_ambiguous",
            }

        if data_score >= 0.55 and data_score > advice_score + 0.1:
            return {
                "intent": "data_query",
                "confidence": data_score,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "heuristic_data_query",
            }

        if advice_score >= 0.55 and advice_score >= data_score:
            return {
                "intent": "advice",
                "confidence": advice_score,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "heuristic_advice",
            }

        return {
            "intent": "advice",
            "confidence": max(data_score, advice_score),
            "route": route,
            "needs_clarification": True,
            "clarification": "你希望我做数据统计查询，还是生成处置建议？可以补充时间范围或地区。",
            "reason": "ambiguous",
        }
