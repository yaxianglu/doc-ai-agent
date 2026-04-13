from __future__ import annotations

import re

from .agri_semantics import (
    has_detail_intent,
    has_overview_intent,
    has_ranking_intent,
    has_trend_intent,
    infer_domain_from_text,
    infer_region_scope,
    needs_advice,
    needs_explanation,
    needs_forecast,
)
from .entity_extraction import EntityExtractionService
from .request_context_resolution import (
    coalesce_region_name,
    contains_pest,
    contains_soil,
    domain_label,
    extract_region,
    inject_domain_into_question,
    is_contextual_follow_up,
    is_domain_switch_follow_up,
    is_greeting,
    is_invalid_region_candidate,
    is_window_only_follow_up,
    normalize_city_mentions,
    normalize_follow_up_question,
    normalize_relative_window_typos,
    normalize_spaces,
    resolve_with_context,
    should_reuse_context_region,
)
from .request_understanding_reasoning import (
    build_historical_query_text,
    build_normalized_question,
    infer_task_type,
    needs_historical_data,
)

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


class RequestUnderstanding:
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
    NOISE_PHRASES = [
        "我其实不太确定怎么表达",
        "我其实不太确定",
        "我不太确定",
        "我不清楚",
        "如果方便的话",
        "如果可以的话",
        "你先帮我",
        "顺便帮我",
        "最后给我",
        "最后给",
        "解释一下",
        "判断一下",
        "判断",
    ]
    NOISE_REGEX_PATTERNS = [
        r"(?<=[\u4e00-\u9fa5])啊哥(?=(?:[\s，。！？；、]|$))",
        r"(?<=[\u4e00-\u9fa5])老哥(?=(?:[\s，。！？；、]|$))",
    ]
    COMPARE_HINTS = ["对比", "比较", "相比", "哪个更突出", "哪个问题更突出", "哪边更突出", "谁更突出"]
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
    INVALID_REGION_PHRASES = {
        "我问的是县",
        "我说的是县",
        "问的是县",
        "说的是县",
        "我问的是区",
        "我说的是区",
        "问的是区",
        "说的是区",
        "我问的是市",
        "我说的是市",
        "问的是市",
        "说的是市",
        "看县",
        "看区",
        "看市",
    }

    def __init__(self, backend=None, extractor: EntityExtractionService | None = None):
        self.backend = backend
        self.extractor = extractor or EntityExtractionService()

    def analyze(self, question: str, history: object = None, context: dict | None = None) -> dict:
        text = (question or "").strip()
        resolved_question, context_resolution = self._resolve_with_context(text, context)
        cleaned, ignored = self._strip_noise(resolved_question)
        used_context = bool(context_resolution)
        reuse_region_from_context = "reused_region_from_memory" in context_resolution
        extracted = self._extract_with_entity_service(cleaned)
        structured = self._extract_with_backend(cleaned, context if used_context else None)

        domain = structured.get("domain") or extracted.get("domain") or self._infer_domain(cleaned, context if used_context else None)
        historical_window = self._coalesce_window(
            structured.get("historical_window"),
            extracted.get("historical_window"),
            self._extract_past_window(cleaned),
        )
        future_window = self._extract_future_window(cleaned) or structured.get("future_window") or extracted.get("future_window")
        region_name = self._coalesce_region_name(
            structured.get("region_name") if isinstance(structured.get("region_name"), str) else "",
            extracted.get("region_name") if isinstance(extracted.get("region_name"), str) else self._extract_region(cleaned),
        ) or (str((context or {}).get("region_name") or "") if reuse_region_from_context else "")
        region_level = self._resolve_region_level(
            text=cleaned,
            region_name=region_name,
            structured_level=str(structured.get("region_level") or ""),
            extracted_level=str(extracted.get("region_level") or ""),
            context_level=str(((context or {}).get("route") or {}).get("region_level") or "") if reuse_region_from_context else "",
        )

        needs_explanation_flag = needs_explanation(cleaned)
        needs_advice_flag = (
            needs_advice(cleaned)
            and not self._asks_stored_disposal_field(cleaned)
        )
        if structured.get("needs_explanation") is True:
            needs_explanation_flag = True
        if structured.get("needs_advice") is True:
            needs_advice_flag = True

        task_type = structured.get("task_type") or infer_task_type(
            cleaned,
            domain,
            region_name,
            needs_explanation_flag,
            needs_advice_flag,
            self.COMPARE_HINTS,
            CITY_ALIASES,
            normalize_city_mentions,
        )
        needs_forecast_flag = needs_forecast(cleaned, future_window, needs_advice_flag)
        needs_historical = needs_historical_data(cleaned, historical_window, future_window, domain, task_type, region_name)

        execution_plan = ["understand_request"]
        if needs_historical:
            execution_plan.append("historical_query")
        if needs_forecast_flag:
            execution_plan.append("forecast")
        if needs_explanation_flag or needs_advice_flag:
            execution_plan.append("knowledge_retrieval")
        execution_plan.append("answer_synthesis")

        normalized_question = build_normalized_question(
            domain=domain,
            historical_window=historical_window,
            future_window=future_window,
            cleaned=cleaned,
            needs_explanation=needs_explanation_flag,
            needs_advice=needs_advice_flag,
            task_type=task_type,
            region_name=region_name,
            region_level=region_level,
        )
        historical_query_text = build_historical_query_text(domain, historical_window, cleaned, task_type, region_name, region_level)

        return {
            "original_question": text,
            "resolved_question": resolved_question,
            "normalized_question": normalized_question,
            "historical_query_text": historical_query_text,
            "ignored_phrases": ignored,
            "task_type": task_type,
            "understanding_engine": structured.get("engine") or extracted.get("engine") or "rules",
            "used_context": used_context,
            "context_resolution": context_resolution,
            "reuse_region_from_context": reuse_region_from_context,
            "domain": domain,
            "window": historical_window,
            "future_window": future_window,
            "region_name": region_name,
            "region_level": region_level,
            "needs_historical": needs_historical,
            "needs_forecast": needs_forecast_flag,
            "needs_explanation": needs_explanation_flag,
            "needs_advice": needs_advice_flag,
            "execution_plan": execution_plan,
        }

    def _extract_with_entity_service(self, cleaned: str) -> dict:
        if not cleaned:
            return {}
        try:
            payload = self.extractor.extract(cleaned)
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        return payload

    def _extract_with_backend(self, cleaned: str, context: dict | None) -> dict:
        if self.backend is None or not cleaned or self._should_skip_backend(cleaned):
            return {}
        try:
            payload = self.backend.extract(cleaned, context=context)
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}

        normalized: dict = {"engine": "instructor"}
        domain = str(payload.get("domain") or "")
        if domain in {"pest", "soil", "mixed"}:
            normalized["domain"] = domain
        task_type = str(payload.get("task_type") or "")
        if task_type in {"ranking", "trend", "region_overview", "joint_risk", "data_detail"}:
            normalized["task_type"] = task_type
        region_name = self._coalesce_region_name(str(payload.get("region_name") or ""), "")
        if region_name:
            normalized["region_name"] = region_name
        region_level = str(payload.get("region_level") or "")
        if region_level in {"city", "county"}:
            normalized["region_level"] = region_level
        historical_window = self._normalize_window_payload(payload.get("historical_window"))
        if historical_window:
            normalized["historical_window"] = historical_window
        future_window = self._normalize_window_payload(payload.get("future_window"))
        if future_window:
            normalized["future_window"] = future_window
        if payload.get("needs_explanation") is True:
            normalized["needs_explanation"] = True
        if payload.get("needs_advice") is True:
            normalized["needs_advice"] = True
        return normalized

    @classmethod
    def _should_skip_backend(cls, text: str) -> bool:
        normalized = str(text or "")
        if not normalized:
            return True
        if any(token in normalized for token in ["某设备", "某县", "某市", "某地区", "某区域", "某个设备", "某个县"]):
            return True
        deterministic_data_tokens = [
            "最近一次",
            "最活跃",
            "最频繁",
            "未知区域",
            "县字段为空",
            "没有匹配到区域",
            "未匹配到区域",
            "sms_content",
            "告警值",
            "占比",
            "连续两天",
        ]
        if any(token in normalized for token in deterministic_data_tokens):
            return True
        if not needs_explanation(normalized) and not needs_advice(normalized):
            if has_ranking_intent(normalized) or has_trend_intent(normalized) or has_detail_intent(normalized) or has_overview_intent(normalized):
                return True
            if cls._extract_future_window(normalized):
                return True
        return False

    @staticmethod
    def _normalize_window_payload(payload: object) -> dict | None:
        if not isinstance(payload, dict):
            return None
        window_type = str(payload.get("window_type") or "")
        if window_type not in {"all", "months", "weeks", "days"}:
            return None
        normalized = {
            "window_type": window_type,
            "window_value": payload.get("window_value"),
        }
        if payload.get("horizon_days") not in {None, ""}:
            normalized["horizon_days"] = int(payload["horizon_days"])
        return normalized

    @staticmethod
    def _coalesce_window(*windows: object) -> dict:
        fallback = {"window_type": "all", "window_value": None}
        all_window: dict | None = None
        for candidate in windows:
            if not isinstance(candidate, dict):
                continue
            window_type = str(candidate.get("window_type") or "")
            if window_type in {"months", "weeks", "days"}:
                return candidate
            if window_type == "all" and all_window is None:
                all_window = candidate
        return all_window or fallback

    def _resolve_with_context(self, text: str, context: dict | None) -> tuple[str, list[str]]:
        return resolve_with_context(
            text,
            context,
            city_aliases=CITY_ALIASES,
            invalid_region_phrases=self.INVALID_REGION_PHRASES,
            greeting_patterns=self.GREETING_PATTERNS,
            extract_past_window=self._extract_past_window,
        )

    def _strip_noise(self, text: str) -> tuple[str, list[str]]:
        ignored: list[str] = []
        cleaned = text
        for phrase in self.NOISE_PHRASES:
            if phrase in cleaned:
                ignored.append(phrase)
                cleaned = cleaned.replace(phrase, " ")
        for pattern in self.NOISE_REGEX_PATTERNS:
            if re.search(pattern, cleaned):
                ignored.append(re.sub(r"[?:(?<=>)|\\[\\]\\\\]", "", pattern))
                cleaned = re.sub(pattern, " ", cleaned)
        cleaned = re.sub(r"[，。！？；、]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned, ignored

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return normalize_spaces(text)

    @staticmethod
    def _normalize_relative_window_typos(text: str) -> str:
        return normalize_relative_window_typos(text)

    @staticmethod
    def _normalize_city_mentions(text: str) -> str:
        return normalize_city_mentions(text, CITY_ALIASES)

    @classmethod
    def _coalesce_region_name(cls, primary: str, secondary: str | None) -> str:
        return coalesce_region_name(primary, secondary, CITY_ALIASES, cls.INVALID_REGION_PHRASES)

    @classmethod
    def _is_invalid_region_candidate(cls, candidate: str) -> bool:
        return is_invalid_region_candidate(candidate, cls.INVALID_REGION_PHRASES)

    @staticmethod
    def _contains_pest(text: str) -> bool:
        return contains_pest(text)

    @staticmethod
    def _contains_soil(text: str) -> bool:
        return contains_soil(text)

    @classmethod
    def _domain_label(cls, domain: str) -> str:
        return domain_label(domain)

    @classmethod
    def _inject_domain_into_question(cls, question: str, domain: str) -> str:
        return inject_domain_into_question(question, domain)

    @staticmethod
    def _is_contextual_follow_up(text: str) -> bool:
        return is_contextual_follow_up(text, RequestUnderstanding.GREETING_PATTERNS)

    @staticmethod
    def _should_reuse_context_region(text: str) -> bool:
        return should_reuse_context_region(text, RequestUnderstanding.GREETING_PATTERNS)

    @classmethod
    def _is_greeting(cls, text: str) -> bool:
        return is_greeting(text, cls.GREETING_PATTERNS)

    @staticmethod
    def _normalize_follow_up_question(text: str) -> str:
        return normalize_follow_up_question(text)

    @classmethod
    def _is_domain_switch_follow_up(cls, text: str) -> bool:
        return is_domain_switch_follow_up(text)

    @classmethod
    def _is_window_only_follow_up(cls, text: str) -> bool:
        return is_window_only_follow_up(
            text,
            extract_past_window=cls._extract_past_window,
            city_aliases=CITY_ALIASES,
            invalid_region_phrases=cls.INVALID_REGION_PHRASES,
        )

    @staticmethod
    def _asks_stored_disposal_field(text: str) -> bool:
        if "处置建议" not in text:
            return False
        return bool(
            "最近一次" in text
            or "最近一条" in text
            or "这条预警" in text
            or "这条" in text
            or re.search(r"SNS\d+", text)
            or "镇" in text
            or "街道" in text
        )

    @staticmethod
    def _infer_domain(text: str, context: dict | None) -> str:
        return infer_domain_from_text(text, str((context or {}).get("domain") or ""))

    @staticmethod
    def _extract_region(text: str) -> str | None:
        return extract_region(text, CITY_ALIASES, RequestUnderstanding.INVALID_REGION_PHRASES)

    @staticmethod
    def _asks_for_county_scope(text: str) -> bool:
        return infer_region_scope(text) == "county"

    @classmethod
    def _resolve_region_level(
        cls,
        *,
        text: str,
        region_name: str,
        structured_level: str,
        extracted_level: str,
        context_level: str,
    ) -> str:
        for level in [structured_level, extracted_level]:
            if level in {"city", "county"}:
                return level
        if cls._asks_for_county_scope(text):
            return "county"
        if region_name.endswith(("县", "区")):
            return "county"
        if region_name.endswith("市"):
            return "city"
        if context_level in {"city", "county"} and region_name:
            return context_level
        return ""

    @classmethod
    def _parse_number_token(cls, token: str) -> int | None:
        token = str(token or "").strip()
        if not token:
            return None
        if token.isdigit():
            return int(token)
        return cls.CHINESE_NUMBER_MAP.get(token)

    @staticmethod
    def _extract_past_window(text: str) -> dict:
        if re.search(r"(?:过去|最近|近|这)半年", text):
            return {"window_type": "months", "window_value": 6}
        if "半年内" in text:
            return {"window_type": "months", "window_value": 6}
        if m := re.search(r"(?:过去|最近|近|进)(\d+|[一二两三四五六七八九十])个?月", text):
            months = max(1, RequestUnderstanding._parse_number_token(m.group(1)) or 1)
            return {"window_type": "months", "window_value": months}
        if m := re.search(r"(?:过去|最近|近|进)(\d+|[一二两三四五六七八九十])个?(?:星期|周)", text):
            weeks = max(1, RequestUnderstanding._parse_number_token(m.group(1)) or 1)
            return {"window_type": "weeks", "window_value": weeks}
        if m := re.search(r"(?:过去|最近|近|进)(\d+|[一二两三四五六七八九十])天", text):
            days = max(1, RequestUnderstanding._parse_number_token(m.group(1)) or 1)
            return {"window_type": "days", "window_value": days}
        return {"window_type": "all", "window_value": None}

    @staticmethod
    def _extract_future_window(text: str) -> dict | None:
        if "下个月" in text or "下月" in text:
            return {"window_type": "months", "window_value": 1, "horizon_days": 30}
        if "未来半个月" in text:
            return {"window_type": "days", "window_value": 15, "horizon_days": 15}
        if "未来两周" in text:
            return {"window_type": "weeks", "window_value": 2, "horizon_days": 14}
        if m := re.search(r"未来(\d+|[一二两三四五六七八九十])个?(?:星期|周)", text):
            weeks = max(1, RequestUnderstanding._parse_number_token(m.group(1)) or 1)
            return {"window_type": "weeks", "window_value": weeks, "horizon_days": weeks * 7}
        if m := re.search(r"未来(\d+|[一二两三四五六七八九十])个?月", text):
            months = max(1, RequestUnderstanding._parse_number_token(m.group(1)) or 1)
            return {"window_type": "months", "window_value": months, "horizon_days": months * 30}
        if m := re.search(r"未来(\d+|[一二两三四五六七八九十])天", text):
            days = max(1, RequestUnderstanding._parse_number_token(m.group(1)) or 1)
            return {"window_type": "days", "window_value": days, "horizon_days": days}
        return None
