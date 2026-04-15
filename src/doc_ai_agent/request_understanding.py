"""请求语义理解主入口。

该模块负责把“原始用户问题 + 上下文”转换成统一结构化结果，供后续流程使用：
- 先做上下文补全与噪声清理；
- 再融合实体抽取、后端抽取与规则推理；
- 最终产出任务类型、时间窗、地区、执行计划等字段。
"""

from __future__ import annotations

import re
from datetime import datetime

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
from .query_plan import canonical_understanding_payload
from .query_dsl import query_dsl_from_understanding
from .semantic_parser import SemanticParser

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
    """农业问答请求理解器。

    这是语义理解层的编排器（orchestrator），本身不直接做数据查询。
    """
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
    ALLOWED_INTENTS = {"data_query", "advice"}
    ALLOWED_TASK_TYPES = {
        "ranking",
        "trend",
        "region_overview",
        "joint_risk",
        "data_detail",
        "compare",
        "cross_domain_compare",
    }

    def __init__(self, backend=None, extractor: EntityExtractionService | None = None):
        """初始化可选后端抽取器与本地实体抽取服务。"""
        self.backend = backend
        self.extractor = extractor or EntityExtractionService()
        self.semantic_parser = SemanticParser(backend=backend, extractor=self.extractor)

    def analyze(self, question: str, history: object = None, context: dict | None = None) -> dict:
        """把用户问题解析成结构化语义结果。

        注意：`history` 当前保留为接口兼容参数，本函数核心使用的是 `context`。
        """
        text = (question or "").strip()
        semantic_parse = self.semantic_parser.parse(text, context=context)
        resolved_question, context_resolution = self._resolve_with_context(text, context)
        cleaned, ignored = self._strip_noise(resolved_question)
        used_context = bool(context_resolution)
        reuse_region_from_context = "reused_region_from_memory" in context_resolution
        extracted = self._extract_with_entity_service(cleaned)
        structured = self._extract_with_backend(cleaned, context if used_context else None)

        domain = semantic_parse.domain or structured.get("domain") or extracted.get("domain") or self._infer_domain(cleaned, context if used_context else None)
        historical_window = self._coalesce_window(
            semantic_parse.historical_window,
            structured.get("historical_window"),
            extracted.get("historical_window"),
            self._extract_past_window(cleaned),
        )
        future_window = semantic_parse.future_window or self._extract_future_window(cleaned) or structured.get("future_window") or extracted.get("future_window")
        region_primary = semantic_parse.region_name or (
            structured.get("region_name") if isinstance(structured.get("region_name"), str) else ""
        )
        region_secondary = (
            extracted.get("region_name") if isinstance(extracted.get("region_name"), str) else self._extract_region(cleaned)
        )
        region_name = self._coalesce_region_name(region_primary, region_secondary) or (
            str((context or {}).get("region_name") or "") if reuse_region_from_context else ""
        )
        region_level = self._resolve_region_level(
            text=cleaned,
            region_name=region_name,
            structured_level=semantic_parse.region_level or str(structured.get("region_level") or ""),
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

        task_type = semantic_parse.task_type if semantic_parse.task_type != "unknown" else (
            structured.get("task_type") or infer_task_type(
                cleaned,
                domain,
                region_name,
                needs_explanation_flag,
                needs_advice_flag,
                self.COMPARE_HINTS,
                CITY_ALIASES,
                normalize_city_mentions,
            )
        )
        intent = self._resolve_intent(
            semantic_intent=semantic_parse.intent,
            structured_intent=str(structured.get("intent") or ""),
        )
        needs_forecast_flag = needs_forecast(cleaned, future_window, needs_advice_flag)
        needs_historical = needs_historical_data(cleaned, historical_window, future_window, domain, task_type, region_name)

        execution_plan = ["understand_request"]
        if needs_historical:
            execution_plan.append("historical_query")
        if needs_forecast_flag:
            execution_plan.append("forecast")
        if needs_explanation_flag or needs_advice_flag:
            # 需要解释/建议时，加入知识检索步骤，供答案合成引用依据。
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

        result = {
            "original_question": text,
            "resolved_question": resolved_question,
            "normalized_question": normalized_question,
            "historical_query_text": historical_query_text,
            "ignored_phrases": ignored,
            "intent": intent,
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
            "followup_type": semantic_parse.followup_type,
            "needs_clarification": semantic_parse.needs_clarification,
            "needs_historical": needs_historical,
            "needs_forecast": needs_forecast_flag,
            "needs_explanation": needs_explanation_flag,
            "needs_advice": needs_advice_flag,
            "execution_plan": execution_plan,
            "confidence": semantic_parse.confidence,
            "fallback_reason": semantic_parse.fallback_reason,
            "trace": list(semantic_parse.trace),
            "semantic_parse": semantic_parse.to_dict(),
        }
        result["canonical_understanding"] = canonical_understanding_payload(
            {
                "intent": intent,
                "domain": domain,
                "task_type": task_type,
                "region_name": region_name,
                "region_level": region_level,
                "historical_window": historical_window,
                "future_window": future_window,
                "followup_type": semantic_parse.followup_type,
                "needs_clarification": semantic_parse.needs_clarification,
            }
        )
        result["parsed_query"] = query_dsl_from_understanding(result).to_dict()
        return result

    def _extract_with_entity_service(self, cleaned: str) -> dict:
        """调用实体抽取服务，异常时安全降级为空结果。"""
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
        """调用后端抽取并规范字段。"""
        if self.backend is None or not cleaned or self._should_skip_backend(cleaned):
            return {}
        try:
            payload = self.backend.extract(cleaned, context=context)
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}

        normalized: dict = {"engine": "instructor"}
        intent = str(payload.get("intent") or "")
        if intent in self.ALLOWED_INTENTS:
            normalized["intent"] = intent
        domain = str(payload.get("domain") or "")
        if domain in {"pest", "soil", "mixed"}:
            normalized["domain"] = domain
        task_type = str(payload.get("task_type") or "")
        if task_type in self.ALLOWED_TASK_TYPES:
            normalized["task_type"] = task_type
        region_name = self._coalesce_region_name(str(payload.get("region_name") or ""), "")
        if region_name:
            normalized["region_name"] = region_name
        region_level = str(payload.get("region_level") or "")
        if region_level in {"city", "county"}:
            normalized["region_level"] = region_level
        historical_window = self._normalize_window_payload(payload.get("historical_window") or payload.get("window"))
        if historical_window:
            normalized["historical_window"] = historical_window
        future_window = self._normalize_window_payload(payload.get("future_window") or payload.get("forecast_window"))
        if future_window:
            normalized["future_window"] = future_window
        if payload.get("needs_explanation") is True:
            normalized["needs_explanation"] = True
        if payload.get("needs_advice") is True:
            normalized["needs_advice"] = True
        return normalized

    @classmethod
    def _should_skip_backend(cls, text: str) -> bool:
        """判断当前问题是否应跳过后端抽取。

        对于确定性很强的模式（如设备字段问答、明显排行/趋势短句），
        规则层即可稳定处理，跳过后端可减少不必要成本与波动。
        """
        normalized = str(text or "")
        if not normalized:
            return True
        if any(
            token in normalized
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
        ):
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
        """把后端时间窗载荷规范成内部统一格式。"""
        if not isinstance(payload, dict):
            return None
        window_type = str(payload.get("window_type") or "")
        if window_type not in {"all", "months", "weeks", "days", "year_since"}:
            return None
        normalized = {
            "window_type": window_type,
            "window_value": payload.get("window_value"),
        }
        horizon_days = payload.get("horizon_days")
        if horizon_days not in {None, ""}:
            try:
                normalized["horizon_days"] = int(horizon_days)
            except (TypeError, ValueError):
                pass
        return normalized

    @staticmethod
    def _coalesce_window(*windows: object) -> dict:
        """在多个时间窗候选中选择最具体的一个。"""
        fallback = {"window_type": "all", "window_value": None}
        all_window: dict | None = None
        for candidate in windows:
            if not isinstance(candidate, dict):
                continue
            window_type = str(candidate.get("window_type") or "")
            if window_type in {"months", "weeks", "days", "year_since"}:
                return candidate
            if window_type == "all" and all_window is None:
                all_window = candidate
        return all_window or fallback

    @classmethod
    def _resolve_intent(cls, semantic_intent: str, structured_intent: str) -> str:
        intent = semantic_intent if semantic_intent in cls.ALLOWED_INTENTS else "advice"
        if intent == "advice" and structured_intent == "data_query":
            return "data_query"
        return intent

    def _resolve_with_context(self, text: str, context: dict | None) -> tuple[str, list[str]]:
        """调用上下文解析模块补全追问。"""
        return resolve_with_context(
            text,
            context,
            city_aliases=CITY_ALIASES,
            invalid_region_phrases=self.INVALID_REGION_PHRASES,
            greeting_patterns=self.GREETING_PATTERNS,
            extract_past_window=self._extract_past_window,
        )

    def _strip_noise(self, text: str) -> tuple[str, list[str]]:
        """去除口语噪声短语，返回清理后文本与被忽略项。"""
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
        """判断“处置建议”是否指向已有告警字段而非通用建议。"""
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
        """综合多个来源推断地区层级（市/县）。"""
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
        """抽取历史时间窗。"""
        if "今年以来" in text:
            current_year = datetime.now().year
            return {"window_type": "year_since", "window_value": current_year}
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
        """抽取未来时间窗。"""
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
