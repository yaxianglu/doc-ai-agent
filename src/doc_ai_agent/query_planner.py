from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from .query_plan import build_query_plan

CITY_ALIASES = {
    "南京": "南京市",
    "无锡": "无锡市",
    "徐州": "徐州市",
    "常州": "常州市",
    "苏州": "苏州市",
    "南通": "南通市",
    "连云港": "连云港市",
    "淮安": "淮安市",
    "盐城": "盐城市",
    "扬州": "扬州市",
    "镇江": "镇江市",
    "泰州": "泰州市",
    "宿迁": "宿迁市",
}


class QueryPlanner:
    CHINESE_NUMBER_MAP = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
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
        q = question.lower()
        score = 0.0
        for token, weight in [
            ("数据", 0.25),
            ("多少", 0.35),
            ("top", 0.3),
            ("统计", 0.3),
            ("哪几个", 0.25),
            ("哪个", 0.2),
            ("哪些", 0.2),
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
            ("预警", 0.2),
            ("预警信息", 0.15),
            ("严重", 0.25),
            ("异常", 0.25),
            ("走势", 0.25),
            ("走向", 0.25),
            ("波动", 0.25),
            ("趋势", 0.25),
            ("过去", 0.15),
            ("最近", 0.15),
            ("虫情", 0.3),
            ("虫害", 0.3),
            ("墒情", 0.3),
            ("同时", 0.15),
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
            ("措施", 0.3),
            ("清单", 0.25),
            ("排查", 0.2),
            ("判断依据", 0.25),
            ("短信版本", 0.35),
            ("短信", 0.2),
            ("改写", 0.3),
            ("台风", 0.2),
            ("给我", 0.1),
            ("24小时", 0.2),
            ("农户", 0.15),
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
        normalized = question or ""
        city_positions: list[tuple[int, str]] = []
        for alias, canonical in CITY_ALIASES.items():
            for match in re.finditer(re.escape(canonical), normalized):
                city_positions.append((match.start(), canonical))
            for match in re.finditer(rf"{re.escape(alias)}(?!市)", normalized):
                city_positions.append((match.start(), canonical))
        if city_positions:
            city_positions.sort(key=lambda item: item[0])
            return city_positions[-1][1]
        matches = re.finditer(r"([\u4e00-\u9fa5]{2,6}市)", normalized)
        filtered = [match.group(1) for match in matches if match.group(1) not in {"城市"} and not match.group(1).endswith("城市")]
        if filtered:
            return filtered[-1]
        for alias, canonical in CITY_ALIASES.items():
            if re.search(rf"{alias}(?!市)", question):
                return canonical
        return None

    def _extract_county(self, question: str) -> Optional[str]:
        m = re.search(r"(?<!哪些)(?<!哪个)(?<!什么)([\u4e00-\u9fa5]{1,12}(?:县|区))", question)
        if m:
            county = m.group(1)
            if county in {"地区", "区域", "市区", "城区"}:
                return None
            if any(token in county for token in ["预警", "最多", "最严重", "地方", "地区"]):
                return None
            if county.startswith("个"):
                return None
            return county
        return None

    @staticmethod
    def _asks_for_county_scope(question: str) -> bool:
        q = question or ""
        if not q:
            return False
        if any(token in q for token in ["区县", "按县", "按区县", "各县", "各区县"]):
            return True
        return any(token in q for token in ["哪个县", "哪些县", "什么县", "哪几个县", "哪个区", "哪些区", "什么区", "哪几个区"])

    def _extract_device_code(self, question: str) -> Optional[str]:
        m = re.search(r"(SNS\d+)", question)
        if m:
            return m.group(1)
        return None

    def _extract_relative_window(self, question: str) -> tuple[Optional[str], Optional[str], dict]:
        now = datetime.now()
        if re.search(r"(?:过去|最近|近|这)半年", question) or "半年内" in question:
            since = now - timedelta(days=30 * 6)
            return since.strftime("%Y-%m-%d 00:00:00"), None, {"window_type": "months", "window_value": 6}
        if m := re.search(r"(?:近|进|过去|最近)(\d+|[一二两三四五六七八九十])个?(?:星期|周)", question):
            weeks = max(1, self._parse_number_token(m.group(1)))
            since = now - timedelta(days=7 * weeks)
            return since.strftime("%Y-%m-%d 00:00:00"), None, {"window_type": "weeks", "window_value": weeks}
        if m := re.search(r"(?:近|进|过去|最近)(\d+|[一二两三四五六七八九十])个?月", question):
            months = max(1, self._parse_number_token(m.group(1)))
            since = now - timedelta(days=30 * months)
            return since.strftime("%Y-%m-%d 00:00:00"), None, {"window_type": "months", "window_value": months}
        if m := re.search(r"(?:近|进|过去|最近)(\d+|[一二两三四五六七八九十])天", question):
            days = max(1, self._parse_number_token(m.group(1)))
            since = now - timedelta(days=days)
            return since.strftime("%Y-%m-%d 00:00:00"), None, {"window_type": "days", "window_value": days}
        return None, None, {"window_type": "none", "window_value": None}

    def _extract_future_window(self, question: str) -> dict | None:
        if "下个月" in question or "下月" in question:
            return {"window_type": "months", "window_value": 1, "horizon_days": 30}
        if "未来两周" in question:
            return {"window_type": "weeks", "window_value": 2, "horizon_days": 14}
        if any(token in question for token in ["未来会更糟", "会更糟吗", "会恶化吗", "会不会更糟", "会不会恶化"]):
            return {"window_type": "weeks", "window_value": 2, "horizon_days": 14}
        if m := re.search(r"未来(\d+|[一二两三四五六七八九十])个?(?:星期|周)", question):
            weeks = max(1, self._parse_number_token(m.group(1)))
            return {"window_type": "weeks", "window_value": weeks, "horizon_days": weeks * 7}
        if m := re.search(r"未来(\d+|[一二两三四五六七八九十])天", question):
            days = max(1, self._parse_number_token(m.group(1)))
            return {"window_type": "days", "window_value": days, "horizon_days": days}
        if m := re.search(r"未来(\d+|[一二两三四五六七八九十])个?月", question):
            months = max(1, self._parse_number_token(m.group(1)))
            return {"window_type": "months", "window_value": months, "horizon_days": months * 30}
        return None

    @classmethod
    def _parse_number_token(cls, token: str) -> int:
        value = str(token or "").strip()
        if value.isdigit():
            return int(value)
        return cls.CHINESE_NUMBER_MAP.get(value, 1)

    def _infer_query_type(self, question: str) -> str:
        if ("同时" in question or "共同" in question) and (("高虫情" in question or "虫情" in question) and ("低墒情" in question or "墒情" in question)):
            return "joint_risk"
        has_region = self._extract_city(question) is not None or self._extract_county(question) is not None
        if has_region and self._has_detail_hint(question) and ("虫情" in question or "虫害" in question):
            return "pest_detail"
        if has_region and self._has_detail_hint(question) and "墒情" in question:
            return "soil_detail"
        if any(token in question for token in ["走势", "走向", "波动", "趋势", "变化"]) and not self._has_negated_trend(question) and ("虫情" in question or "虫害" in question):
            return "pest_trend"
        if any(token in question for token in ["走势", "走向", "波动", "趋势", "变化"]) and not self._has_negated_trend(question) and "墒情" in question:
            return "soil_trend"
        asks_overview = any(token in question for token in ["情况", "概况", "整体", "总体", "态势", "表现", "怎么样", "如何", "数据"])
        if has_region and asks_overview and ("虫情" in question or "虫害" in question):
            return "pest_overview"
        if has_region and asks_overview and "墒情" in question:
            return "soil_overview"
        if ("最严重" in question or "严重" in question or "最多" in question) and ("虫情" in question or "虫害" in question):
            return "pest_top"
        if ("异常最多" in question or "异常" in question or "最多" in question or "最严重" in question or "严重" in question) and "墒情" in question:
            return "soil_top"
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
        if "top" in question.lower() or "Top" in question or "前5" in question or "最多" in question:
            return "top"
        if "虫情" in question or "墒情" in question or "虫害" in question:
            return "structured_agri"
        return "count"

    def _build_route(self, question: str, query_type: str) -> dict:
        since, until = self._extract_day_range(question)
        if since is None:
            rel_since, rel_until, window = self._extract_relative_window(question)
            since, until = rel_since, rel_until
        else:
            window = {"window_type": "day", "window_value": 1}
        if since is None:
            m = re.search(r"(20\d{2})年以?来", question)
            if m:
                since = f"{m.group(1)}-01-01 00:00:00"
                window = {"window_type": "year_since", "window_value": int(m.group(1))}
        if since is None:
            since = "1970-01-01 00:00:00"
            window = {"window_type": "all", "window_value": None}
        county = self._extract_county(question)
        region_level = "county" if county or self._asks_for_county_scope(question) else "city"
        return {
            "query_type": query_type,
            "since": since,
            "until": until,
            "city": self._extract_city(question),
            "county": county,
            "device_code": self._extract_device_code(question),
            "region_level": region_level,
            "window": window,
        }

    def _normalize_router_route(self, question: str, route: dict) -> dict:
        normalized = dict(route)
        router_query_type = str(normalized.get("query_type") or "count")
        heuristic_query_type = self._infer_query_type(question)

        if heuristic_query_type in self.DETERMINISTIC_QUERY_TYPES:
            normalized["query_type"] = heuristic_query_type
            normalized["intent"] = "data_query"
        elif self._is_agri_query_type(heuristic_query_type) and not self._is_agri_query_type(router_query_type):
            normalized["query_type"] = heuristic_query_type

        return normalized

    def _merge_router_route(self, question: str, route: dict) -> dict:
        base = self._build_route(question, route.get("query_type", "count"))
        merged = dict(base)

        for key, value in route.items():
            if key in {"city", "county", "device_code", "until"} and value in {None, ""}:
                continue
            if key in {"city", "county", "device_code"} and base.get(key) not in {None, ""}:
                continue
            if key == "region_level" and base.get("region_level") == "county" and value == "city":
                continue
            if key in {"since", "until"} and base["window"]["window_type"] != "all":
                continue
            if key == "since":
                if value in {None, ""}:
                    continue
                if value == "1970-01-01 00:00:00" and base["window"]["window_type"] != "all":
                    continue
            merged[key] = value

        return merged

    def _is_low_signal(self, question: str) -> bool:
        q = (question or "").strip()
        if not q:
            return True
        if self._is_greeting_question(q):
            return False
        if re.fullmatch(r"[\d\W_]+", q):
            return True
        if re.fullmatch(r"(哈|呵|啊|嗯|哦|呀){3,}", q):
            return True
        if len(q) <= 4 and not re.search(r"(预警|设备|处置|建议|统计|多少|怎么|如何|虫情|墒情)", q):
            return True
        return False

    def _needs_agri_domain_clarification(self, question: str) -> bool:
        has_agri_domain = re.search(r"(虫情|虫害|墒情)", question) is not None
        asks_severity = re.search(r"(受灾|灾情|最严重|最重)", question) is not None
        asks_region = re.search(r"(地方|地区|哪里|哪儿)", question) is not None
        asks_generic_agri = re.search(r"(受灾|灾情|灾害)", question) is not None
        asks_dataset_or_overview = re.search(r"(数据|情况|概况|整体|总体|态势|走势|趋势)", question) is not None
        route = self._build_route(question, "structured_agri")
        window = dict(route.get("window") or {})
        has_scope = route.get("city") is not None or route.get("county") is not None or window.get("window_type") not in {"none", "all"}
        return not has_agri_domain and (
            (asks_severity and asks_region) or (asks_generic_agri and asks_dataset_or_overview and has_scope)
        )

    def _normalize_history(self, history: object) -> list[dict[str, str]]:
        if not isinstance(history, list):
            return []
        normalized: list[dict[str, str]] = []
        for item in history:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in {"user", "assistant"}:
                continue
            if not isinstance(content, str) or not content.strip():
                continue
            normalized.append({"role": role, "content": content.strip()})
        return normalized

    @staticmethod
    def _domain_from_query_type(query_type: str) -> str | None:
        if query_type.startswith("pest"):
            return "pest"
        if query_type.startswith("soil"):
            return "soil"
        return None

    def _infer_domain_from_text(self, question: str, context: dict | None = None) -> str:
        has_pest = "虫情" in question or "虫害" in question
        has_soil = any(token in question for token in ["墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"])
        if has_pest and has_soil:
            return "mixed"
        if has_pest:
            return "pest"
        if has_soil:
            return "soil"
        context_domain = str((context or {}).get("domain") or "")
        if context_domain in {"pest", "soil", "mixed"}:
            return context_domain
        return ""

    @staticmethod
    def _answer_mode_for_plan(intent: str, route: dict, needs_clarification: bool) -> str:
        if needs_clarification:
            return "clarify"
        if intent == "advice":
            return "advice"
        query_type = str(route.get("query_type") or "")
        if query_type.endswith("_compare") or query_type == "cross_domain_compare":
            return "compare"
        if query_type.endswith("_detail"):
            return "detail"
        if query_type.endswith("_overview"):
            return "overview"
        if query_type.endswith("_trend"):
            return "trend"
        if query_type.endswith("_forecast"):
            return "forecast"
        if query_type.endswith("_top"):
            return "ranking"
        if query_type == "joint_risk":
            return "joint_risk"
        return "data_query"

    def _typed_metadata(self, question: str, route: dict, intent: str, needs_clarification: bool, context: dict | None, understanding: dict | None) -> dict:
        understanding = dict(understanding or {})
        context = dict(context or {})
        if self._is_greeting_question(question):
            return {
                "domain": "",
                "region_name": "",
                "historical_window": {"window_type": "all", "window_value": None},
                "future_window": None,
                "answer_mode": self._answer_mode_for_plan(intent, route, needs_clarification),
            }
        domain = str(understanding.get("domain") or self._domain_from_query_type(str(route.get("query_type") or "")) or self._infer_domain_from_text(question, context=context) or "")
        region_name = (
            str(understanding.get("region_name") or "")
            or str(route.get("county") or "")
            or str(route.get("city") or "")
            or (str(context.get("region_name") or "") if len((question or "").strip()) <= 12 else "")
        )
        historical_window = understanding.get("window") or route.get("window") or {"window_type": "all", "window_value": None}
        future_window = understanding.get("future_window") or route.get("forecast_window")
        return {
            "domain": domain,
            "region_name": region_name,
            "historical_window": historical_window,
            "future_window": future_window,
            "answer_mode": self._answer_mode_for_plan(intent, route, needs_clarification),
        }

    def _finalize_plan(self, plan: dict, question: str, context: dict | None = None, understanding: dict | None = None) -> dict:
        route = dict(plan.get("route") or {})
        finalized = dict(plan)
        finalized.update(self._typed_metadata(question, route, str(plan.get("intent") or "advice"), bool(plan.get("needs_clarification")), context, understanding))
        task_type = str((understanding or {}).get("task_type") or "")
        if task_type in {"compare", "cross_domain_compare"}:
            finalized["answer_mode"] = "compare"
        understanding_payload = dict(understanding or {})
        inferred_needs_explanation = bool(understanding_payload.get("needs_explanation")) or any(token in question for token in ["为什么", "原因", "依据"])
        inferred_needs_advice = bool(understanding_payload.get("needs_advice")) or (
            not self._has_negated_advice(question)
            and any(token in question for token in ["建议", "处置", "怎么办", "怎么做", "怎么处理", "怎么养", "防治"])
        )
        inferred_needs_forecast = (
            bool(understanding_payload.get("needs_forecast"))
            or isinstance(finalized.get("future_window"), dict)
            or "未来" in question
        )
        finalized["query_plan"] = build_query_plan(
            plan_intent=str(finalized.get("intent") or "advice"),
            route=route,
            domain=str(finalized.get("domain") or ""),
            region_name=str(finalized.get("region_name") or ""),
            historical_window=dict(finalized.get("historical_window") or {}),
            future_window=finalized.get("future_window") if isinstance(finalized.get("future_window"), dict) else None,
            answer_mode=str(finalized.get("answer_mode") or ""),
            needs_clarification=bool(finalized.get("needs_clarification")),
            is_greeting=self._is_greeting_question(question),
            needs_explanation=inferred_needs_explanation,
            needs_forecast=inferred_needs_forecast,
            needs_advice=inferred_needs_advice,
        )
        return finalized

    def _context_follow_up_plan(self, question: str, context: dict | None) -> dict | None:
        context = dict(context or {})
        if not context:
            return None
        if self._is_greeting_question(question):
            return None
        if not self._looks_like_contextual_follow_up(question):
            return None

        previous_route = dict(context.get("route") or {})
        previous_query_type = str(previous_route.get("query_type") or context.get("query_type") or "")
        domain = str(context.get("domain") or self._domain_from_query_type(previous_query_type) or "")
        trace = [f"reused thread context domain={domain or 'unknown'}"]
        future_window = self._extract_future_window(question)
        explicit_domain = self._explicit_domain_from_text(question)
        relative_since, relative_until, relative_window = self._extract_relative_window(question)
        city = self._extract_city(question)
        county = self._extract_county(question)

        if self._is_detail_follow_up(question) and domain in {"pest", "soil"}:
            route = dict(previous_route)
            route["query_type"] = f"{explicit_domain or domain}_detail"
            if relative_window.get("window_type") != "none":
                route["since"] = relative_since
                route["until"] = relative_until
                route["window"] = relative_window
            if not route.get("city") and not route.get("county") and context.get("region_name"):
                route["city"] = context.get("region_name")
                route["region_level"] = "city"
            return {
                "intent": "data_query",
                "confidence": 0.91,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "context_detail_follow_up",
                "context_trace": trace + ["reused previous analysis context for concrete data"],
            }

        if self._is_advice_follow_up(question) and domain in {"pest", "soil"}:
            return {
                "intent": "advice",
                "confidence": 0.9,
                "route": dict(previous_route),
                "needs_clarification": False,
                "clarification": None,
                "reason": "context_advice_follow_up",
                "context_trace": trace + ["reused previous analysis context for advice"],
            }

        if self._is_explanation_follow_up(question) and domain in {"pest", "soil"}:
            return {
                "intent": "advice",
                "confidence": 0.91,
                "route": dict(previous_route),
                "needs_clarification": False,
                "clarification": None,
                "reason": "context_explanation_follow_up",
                "context_trace": trace + ["reused previous analysis context for explanation"],
            }

        if explicit_domain in {"pest", "soil"} and domain in {"pest", "soil"} and (
            explicit_domain != domain or self._has_domain_switch_verb(question)
        ):
            next_query_type = self._query_type_for_domain_switch(previous_query_type, explicit_domain)
            route = dict(previous_route)
            route["query_type"] = next_query_type
            if relative_window.get("window_type") != "none":
                route["since"] = relative_since
                route["until"] = relative_until
                route["window"] = relative_window
            if not route.get("city") and not route.get("county") and context.get("region_name"):
                route["city"] = context.get("region_name")
                route["region_level"] = "city"
            return {
                "intent": "data_query",
                "confidence": 0.9,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "context_domain_switch_follow_up",
                "context_trace": trace + [f"switch domain={explicit_domain} and preserve scope"],
            }

        if future_window and domain in {"pest", "soil"}:
            route = dict(previous_route)
            route["query_type"] = f"{domain}_forecast"
            route["forecast_window"] = future_window
            if not route.get("city") and not route.get("county") and context.get("region_name"):
                route["city"] = context.get("region_name")
                route["region_level"] = "city"
            return {
                "intent": "data_query",
                "confidence": 0.92,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "context_forecast_follow_up",
                "context_trace": trace + [f"forecast horizon={future_window['horizon_days']}d"],
            }

        if relative_window.get("window_type") != "none" and domain in {"pest", "soil"} and not (city or county):
            route = dict(previous_route)
            route["query_type"] = self._query_type_for_window_follow_up(previous_query_type, domain)
            route["since"] = relative_since
            route["until"] = relative_until
            route["window"] = relative_window
            if not route.get("city") and not route.get("county") and context.get("region_name"):
                route["city"] = context.get("region_name")
                route["region_level"] = "city"
            return {
                "intent": "data_query",
                "confidence": 0.89,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "context_window_follow_up",
                "context_trace": trace + [f"switch window={relative_window['window_type']}:{relative_window['window_value']}"],
            }

        if (city or county) and domain in {"pest", "soil"} and len(question.strip()) <= 12:
            route = dict(previous_route)
            route["city"] = city
            route["county"] = county
            route["region_level"] = "county" if county else "city"
            forecast = dict(context.get("forecast") or {})
            previous_forecast_window = dict(route.get("forecast_window") or {})
            if previous_query_type == f"{domain}_forecast" or forecast.get("horizon_days"):
                horizon_days = int(forecast.get("horizon_days") or previous_forecast_window.get("horizon_days") or 14)
                route["query_type"] = f"{domain}_forecast"
                route["forecast_window"] = {
                    "window_type": previous_forecast_window.get("window_type") or "days",
                    "window_value": previous_forecast_window.get("window_value") or horizon_days,
                    "horizon_days": horizon_days,
                }
                return {
                    "intent": "data_query",
                    "confidence": 0.88,
                    "route": route,
                    "needs_clarification": False,
                    "clarification": None,
                    "reason": "context_region_forecast_follow_up",
                    "context_trace": trace + [f"switch region={(county or city)} and preserve forecast intent"],
                }
            route["query_type"] = self._query_type_for_region_follow_up(previous_query_type, domain)
            return {
                "intent": "data_query",
                "confidence": 0.86,
                "route": route,
                "needs_clarification": False,
                "clarification": None,
                "reason": "context_region_follow_up",
                "context_trace": trace + [f"focus region={(county or city)}"],
            }

        return None

    @staticmethod
    def _looks_like_contextual_follow_up(question: str) -> bool:
        stripped = (question or "").strip()
        if not stripped:
            return False
        if QueryPlanner._is_greeting_question(stripped):
            return False
        if re.search(r"(SNS\d+|设备|最近一次|预警时间|告警值|按告警等级|20\d{2}年)", stripped):
            return False
        if len(stripped) <= 12:
            return True
        return bool(re.match(r"^(那|那么|那就|未来|换成|改成|建议|给建议|处置建议|为什么|原因|我说的是|不是趋势|具体数据)", stripped))

    @staticmethod
    def _has_detail_hint(question: str) -> bool:
        q = question or ""
        return any(token in q for token in ["具体数据", "详细数据", "数据明细", "明细数据", "原始数据", "具体数值", "详细数值", "逐日数据", "每天数据", "明细", "按天", "逐天", "列出来"]) or (
            "数据" in q and not any(token in q for token in ["概况", "情况", "整体", "总体", "态势"])
        )

    @staticmethod
    def _has_negated_trend(question: str) -> bool:
        q = question or ""
        return any(token in q for token in ["不是趋势", "别看趋势", "不要趋势", "不看趋势"])

    @staticmethod
    def _has_domain_switch_verb(question: str) -> bool:
        return bool(re.search(r"(换成|改成|改看|切到|切换到|切换成|改为|换看)", question or ""))

    @staticmethod
    def _is_advice_follow_up(question: str) -> bool:
        q = question or ""
        return not QueryPlanner._has_negated_advice(q) and any(
            token in q for token in ["建议", "处置", "怎么办", "怎么做", "怎么处理", "怎么养", "防治"]
        )

    @staticmethod
    def _has_negated_advice(question: str) -> bool:
        q = question or ""
        return bool(re.search(r"(不要|别|不用|不需要|先不要|先别)(?:再)?(?:给)?(?:我)?建议", q)) or bool(
            re.search(r"(不要|别|不用|不需要|先不要|先别)(?:给)?(?:我)?(?:处置|防治)", q)
        )

    @staticmethod
    def _is_explanation_follow_up(question: str) -> bool:
        q = question or ""
        return any(token in q for token in ["为什么", "原因", "依据"])

    @classmethod
    def _is_detail_follow_up(cls, question: str) -> bool:
        return cls._has_detail_hint(question)

    @staticmethod
    def _explicit_domain_from_text(question: str) -> str:
        has_pest = "虫情" in question or "虫害" in question
        has_soil = "墒情" in question or "缺水" in question or "干旱" in question
        if has_pest and not has_soil:
            return "pest"
        if has_soil and not has_pest:
            return "soil"
        return ""

    @staticmethod
    def _query_type_for_domain_switch(previous_query_type: str, next_domain: str) -> str:
        if previous_query_type.endswith("_forecast"):
            return f"{next_domain}_forecast"
        if previous_query_type.endswith("_detail"):
            return f"{next_domain}_detail"
        if previous_query_type.endswith("_trend"):
            return f"{next_domain}_trend"
        if previous_query_type.endswith("_top"):
            return f"{next_domain}_top"
        return f"{next_domain}_overview"

    @staticmethod
    def _query_type_for_region_follow_up(previous_query_type: str, domain: str) -> str:
        if previous_query_type.endswith("_forecast"):
            return f"{domain}_forecast"
        if previous_query_type.endswith("_detail"):
            return f"{domain}_detail"
        if previous_query_type.endswith("_trend"):
            return f"{domain}_trend"
        return f"{domain}_overview"

    @staticmethod
    def _query_type_for_window_follow_up(previous_query_type: str, domain: str) -> str:
        if previous_query_type.endswith("_forecast"):
            return f"{domain}_forecast"
        if previous_query_type.endswith("_detail"):
            return f"{domain}_detail"
        if previous_query_type.endswith("_trend"):
            return f"{domain}_trend"
        if previous_query_type.endswith("_top"):
            return f"{domain}_top"
        if previous_query_type == "joint_risk":
            return "joint_risk"
        return f"{domain}_overview"

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

    @staticmethod
    def _has_agri_signal(question: str, playbook_route: dict | None, context: dict | None = None) -> bool:
        q = question or ""
        if any(token in q for token in ["虫情", "虫害", "害虫", "墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"]):
            return True
        context_domain = str((context or {}).get("domain") or "")
        if context_domain in {"pest", "soil", "mixed"}:
            return True
        matched_terms = (playbook_route or {}).get("matched_terms")
        if isinstance(matched_terms, list):
            return any(
                any(token in str(term) for token in ["虫", "墒", "缺水", "干旱", "土壤", "含水"])
                for term in matched_terms
            )
        return False

    @staticmethod
    def _asks_advice_or_explanation(question: str) -> bool:
        q = question or ""
        return any(token in q for token in ["建议", "处置", "怎么办", "怎么做", "怎么处理", "怎么养", "防治", "为什么", "原因", "依据"])

    def _should_use_playbook_route(self, question: str, heuristic_query_type: str, playbook_route: dict | None, context: dict | None = None) -> bool:
        if playbook_route is None:
            return False
        if heuristic_query_type in self.DETERMINISTIC_QUERY_TYPES:
            return False
        if self._asks_advice_or_explanation(question):
            return False
        if not self._has_agri_signal(question, playbook_route, context=context):
            return False
        return heuristic_query_type in self.PLAYBOOK_UPGRADEABLE_QUERY_TYPES

    @staticmethod
    def _playbook_context_trace(playbook_route: dict) -> list[str]:
        trace: list[str] = []
        reason = str(playbook_route.get("reason") or "").strip()
        if reason:
            trace.append(reason)
        retrieval_engine = str(playbook_route.get("retrieval_engine") or "").strip()
        if retrieval_engine:
            trace.append(f"playbook_router={retrieval_engine}")
        matched_terms = playbook_route.get("matched_terms")
        if isinstance(matched_terms, list) and matched_terms:
            trace.append("matched_terms=" + ",".join(str(term) for term in matched_terms[:4]))
        return trace

    def _resolve_follow_up_question(self, question: str, history: object, context: dict | None = None) -> str:
        current = (question or "").strip()
        if not current:
            return current

        normalized_history = self._normalize_history(history)
        context = dict(context or {})
        if not normalized_history and not context:
            return current

        last_user_question = next((item["content"] for item in reversed(normalized_history) if item["role"] == "user"), "")
        last_assistant_reply = next((item["content"] for item in reversed(normalized_history) if item["role"] == "assistant"), "")
        pending_user_question = str(context.get("pending_user_question") or "")
        pending_clarification = str(context.get("pending_clarification") or "")

        if not last_user_question and pending_user_question:
            last_user_question = pending_user_question
        if not last_assistant_reply and pending_clarification == "agri_domain":
            last_assistant_reply = "你想看虫情还是墒情？"
        if not last_assistant_reply and pending_clarification == "generic_intent":
            last_assistant_reply = "你希望我做数据统计，还是生成处置建议？"

        if not last_user_question:
            return current

        is_domain_follow_up = current in {"虫情", "虫害", "墒情", "低墒", "高墒"} and "虫情还是墒情" in last_assistant_reply
        is_intent_follow_up = current in {"数据统计", "统计", "查数据", "数据", "处置建议", "建议"} and "数据统计" in last_assistant_reply and "处置建议" in last_assistant_reply

        if is_domain_follow_up or is_intent_follow_up:
            return f"{last_user_question} {current}"

        return current

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
