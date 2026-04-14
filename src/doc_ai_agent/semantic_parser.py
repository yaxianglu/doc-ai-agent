"""统一语义解析编排器。

当前版本先提供一个最小可用的 orchestrator：
- 统一做基础归一化；
- 识别明显越界的问题；
- 输出 `SemanticParseResult`，供后续模块渐进接入。
"""

from __future__ import annotations

import re
from datetime import datetime

from .agri_semantics import infer_domain_from_text, infer_region_scope, needs_advice, needs_explanation
from .entity_extraction import EntityExtractionService
from .request_context_resolution import (
    extract_region,
    is_contextual_follow_up,
    is_domain_switch_follow_up,
    is_window_only_follow_up,
    normalize_city_mentions,
    should_reuse_context_region,
)
from .request_understanding_reasoning import infer_task_type
from .semantic_parse import SemanticParseResult
from .semantic_judger import SemanticJudger


class SemanticParser:
    """语义解析编排器。

    该类后续会逐步吸纳更多理解能力；当前先提供稳定的最小合同。
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
        self.semantic_judger = SemanticJudger()

    def parse(self, question: str, context: dict | None = None) -> SemanticParseResult:
        """把原始问题解析为统一语义结果。"""
        context = dict(context or {})
        normalized = str(question or "").strip()
        trace = ["normalize"]
        followup_type = self._infer_followup_type(normalized, context)
        if followup_type != "none":
            trace.append(f"followup:{followup_type}")

        semantic_decision = self.semantic_judger.judge(normalized)
        backend_signal = self._semantic_backend_signal(normalized, context)
        semantic_reason = str(semantic_decision.get("fallback_reason") or semantic_decision.get("reason") or "")

        if self.semantic_judger.is_out_of_scope_reason(semantic_reason):
            trace.extend(["ood", f"ood:{semantic_reason}"])
            return SemanticParseResult(
                normalized_query=normalized,
                intent=str(semantic_decision.get("intent") or "advice"),
                confidence=self._confidence_score(
                    domain="",
                    task_type="unknown",
                    region_name="",
                    historical_window={"window_type": "all", "window_value": None},
                    future_window=None,
                    followup_type=followup_type,
                    needs_clarification=True,
                    semantic_reason=semantic_reason,
                    semantic_confidence=semantic_decision.get("confidence"),
                    backend_signal=backend_signal,
                ),
                is_out_of_scope=True,
                fallback_reason=semantic_reason,
                followup_type=followup_type,
                needs_clarification=True,
                trace=trace,
            )
        if semantic_reason in {self.semantic_judger.REASON_GREETING, self.semantic_judger.REASON_IDENTITY}:
            trace.extend(["edge", f"edge:{semantic_reason}"])
            return SemanticParseResult(
                normalized_query=normalized,
                intent=str(semantic_decision.get("intent") or "advice"),
                confidence=self._confidence_score(
                    domain="",
                    task_type="unknown",
                    region_name="",
                    historical_window={"window_type": "all", "window_value": None},
                    future_window=None,
                    followup_type=followup_type,
                    needs_clarification=bool(semantic_decision.get("needs_clarification")),
                    semantic_reason=semantic_reason,
                    semantic_confidence=semantic_decision.get("confidence"),
                    backend_signal=backend_signal,
                ),
                is_out_of_scope=False,
                fallback_reason=semantic_reason,
                followup_type=followup_type,
                needs_clarification=bool(semantic_decision.get("needs_clarification")),
                trace=trace,
            )

        domain = self._infer_domain(normalized, context, followup_type)
        region_name = self._infer_region_name(normalized, context, followup_type)
        region_level = self._resolve_region_level(normalized, region_name)
        historical_window = self._extract_past_window(normalized)
        future_window = self._extract_future_window(normalized)
        needs_explanation_flag = needs_explanation(normalized)
        needs_advice_flag = needs_advice(normalized)
        task_type = infer_task_type(
            normalized,
            domain,
            region_name,
            needs_explanation_flag,
            needs_advice_flag,
            self.COMPARE_HINTS,
            self.CITY_ALIASES,
            normalize_city_mentions,
        )
        needs_clarification = bool(followup_type in {"contextual", "window_only"} and not domain and not region_name)
        trace.append("slots")

        return SemanticParseResult(
            normalized_query=normalized,
            intent="data_query" if self._is_data_query(domain, task_type, historical_window, future_window) else "advice",
            domain=domain,
            task_type=task_type,
            region_name=region_name,
            region_level=region_level,
            historical_window=historical_window,
            future_window=future_window,
            followup_type=followup_type,
            needs_clarification=needs_clarification,
            confidence=self._confidence_score(
                domain=domain,
                task_type=task_type,
                region_name=region_name,
                historical_window=historical_window,
                future_window=future_window,
                followup_type=followup_type,
                needs_clarification=needs_clarification,
                semantic_reason=semantic_reason,
                semantic_confidence=semantic_decision.get("confidence"),
                backend_signal=backend_signal,
            ),
            trace=trace,
        )

    @classmethod
    def _is_data_query(cls, domain: str, task_type: str, historical_window: dict, future_window: dict | None) -> bool:
        if domain:
            return True
        if task_type != "unknown":
            return True
        if isinstance(historical_window, dict) and historical_window.get("window_type") != "all":
            return True
        return future_window is not None

    @classmethod
    def _safe_confidence(cls, value: object) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        return max(0.0, min(0.99, numeric))

    def _semantic_backend_signal(self, text: str, context: dict) -> dict:
        if self.backend is None:
            return {}
        for method_name in ("semantic_evidence", "semantic_judge", "extract"):
            method = getattr(self.backend, method_name, None)
            if not callable(method):
                continue
            try:
                payload = method(text, context=context)
            except TypeError:
                try:
                    payload = method(text)
                except Exception:
                    return {}
            except Exception:
                return {}
            if not isinstance(payload, dict):
                return {}
            domain = str(payload.get("domain") or "")
            if domain not in {"pest", "soil", "mixed"}:
                domain = ""
            return {
                "domain": domain,
                "reason": str(payload.get("fallback_reason") or payload.get("reason") or ""),
                "confidence": self._safe_confidence(payload.get("confidence")),
            }
        return {}

    @classmethod
    def _semantic_agreement_delta(cls, domain: str, semantic_reason: str, backend_signal: dict) -> float:
        backend_domain = str((backend_signal or {}).get("domain") or "")
        backend_reason = str((backend_signal or {}).get("reason") or "")
        if SemanticJudger.is_out_of_scope_reason(semantic_reason):
            if backend_reason == semantic_reason:
                return 0.08
            if SemanticJudger.is_out_of_scope_reason(backend_reason) and backend_reason != semantic_reason:
                return -0.12
            return 0.0
        if SemanticJudger.is_out_of_scope_reason(backend_reason):
            return -0.18
        if domain and backend_domain:
            return 0.08 if domain == backend_domain else -0.18
        return 0.0

    @classmethod
    def _confidence_score(
        cls,
        *,
        domain: str,
        task_type: str,
        region_name: str,
        historical_window: dict,
        future_window: dict | None,
        followup_type: str,
        needs_clarification: bool,
        semantic_reason: str,
        semantic_confidence: object,
        backend_signal: dict,
    ) -> float:
        score = 0.44
        if domain:
            score += 0.14
        if task_type != "unknown":
            score += 0.08
        if region_name:
            score += 0.06
        if isinstance(historical_window, dict) and str(historical_window.get("window_type") or "all") != "all":
            score += 0.06
        if isinstance(future_window, dict):
            score += 0.06
        if followup_type in {"contextual", "window_only", "domain_switch"}:
            score += 0.03
        if needs_clarification:
            score -= 0.27
        score += cls._semantic_agreement_delta(domain, semantic_reason, backend_signal)

        semantic_confidence_score = cls._safe_confidence(semantic_confidence)
        if semantic_reason in {SemanticJudger.REASON_GREETING, SemanticJudger.REASON_IDENTITY}:
            score = max(score, semantic_confidence_score or 0.9)
        elif semantic_confidence_score > 0:
            score = (score * 0.7) + (semantic_confidence_score * 0.3)

        if SemanticJudger.is_out_of_scope_reason(semantic_reason):
            score = max(score, 0.9)
            if str((backend_signal or {}).get("reason") or "") == semantic_reason:
                score += 0.07
        return max(0.0, min(0.99, round(score, 2)))

    @classmethod
    def _infer_followup_type(cls, text: str, context: dict) -> str:
        normalized = str(text or "").strip()
        if not normalized:
            return "none"
        has_context_memory = bool(str(context.get("domain") or "").strip() or str(context.get("region_name") or "").strip())
        if is_domain_switch_follow_up(normalized):
            return "domain_switch"
        if (
            has_context_memory
            and len(normalized) <= 10
            and is_window_only_follow_up(
                normalized,
                extract_past_window=cls._extract_past_window,
                city_aliases=cls.CITY_ALIASES,
                invalid_region_phrases=cls.INVALID_REGION_PHRASES,
            )
        ):
            return "window_only"
        if has_context_memory and is_contextual_follow_up(normalized, cls.GREETING_PATTERNS):
            return "contextual"
        return "none"

    @staticmethod
    def _infer_domain(text: str, context: dict, followup_type: str) -> str:
        context_domain = str(context.get("domain") or "")
        if followup_type in {"contextual", "window_only"}:
            return infer_domain_from_text(text, context_domain)
        return infer_domain_from_text(text, "")

    @classmethod
    def _infer_region_name(cls, text: str, context: dict, followup_type: str) -> str:
        region_name = str(extract_region(text, cls.CITY_ALIASES, cls.INVALID_REGION_PHRASES) or "")
        if region_name:
            return region_name
        if followup_type == "contextual" and should_reuse_context_region(text, cls.GREETING_PATTERNS):
            return str(context.get("region_name") or "").strip()
        return ""

    @classmethod
    def _resolve_region_level(cls, text: str, region_name: str) -> str:
        if infer_region_scope(text) == "county":
            return "county"
        if region_name.endswith(("县", "区")):
            return "county"
        if region_name.endswith("市"):
            return "city"
        return ""

    @classmethod
    def _parse_number_token(cls, token: str) -> int | None:
        normalized = str(token or "").strip()
        if not normalized:
            return None
        if normalized.isdigit():
            return int(normalized)
        return cls.CHINESE_NUMBER_MAP.get(normalized)

    @classmethod
    def _extract_past_window(cls, text: str) -> dict:
        if "今年以来" in text:
            return {"window_type": "year_since", "window_value": datetime.now().year}
        if re.search(r"(?:过去|最近|近|这)半年", text) or "半年内" in text:
            return {"window_type": "months", "window_value": 6}
        if m := re.search(r"(?:过去|最近|近|进)(\d+|[一二两三四五六七八九十])个?月", text):
            months = max(1, cls._parse_number_token(m.group(1)) or 1)
            return {"window_type": "months", "window_value": months}
        if m := re.search(r"(?:过去|最近|近|进)(\d+|[一二两三四五六七八九十])个?(?:星期|周)", text):
            weeks = max(1, cls._parse_number_token(m.group(1)) or 1)
            return {"window_type": "weeks", "window_value": weeks}
        if m := re.search(r"(?:过去|最近|近|进)(\d+|[一二两三四五六七八九十])天", text):
            days = max(1, cls._parse_number_token(m.group(1)) or 1)
            return {"window_type": "days", "window_value": days}
        return {"window_type": "all", "window_value": None}

    @classmethod
    def _extract_future_window(cls, text: str) -> dict | None:
        if "下个月" in text or "下月" in text:
            return {"window_type": "months", "window_value": 1, "horizon_days": 30}
        if "未来半个月" in text:
            return {"window_type": "days", "window_value": 15, "horizon_days": 15}
        if "未来两周" in text:
            return {"window_type": "weeks", "window_value": 2, "horizon_days": 14}
        if m := re.search(r"未来(\d+|[一二两三四五六七八九十])个?(?:星期|周)", text):
            weeks = max(1, cls._parse_number_token(m.group(1)) or 1)
            return {"window_type": "weeks", "window_value": weeks, "horizon_days": weeks * 7}
        if m := re.search(r"未来(\d+|[一二两三四五六七八九十])个?月", text):
            months = max(1, cls._parse_number_token(m.group(1)) or 1)
            return {"window_type": "months", "window_value": months, "horizon_days": months * 30}
        if m := re.search(r"未来(\d+|[一二两三四五六七八九十])天", text):
            days = max(1, cls._parse_number_token(m.group(1)) or 1)
            return {"window_type": "days", "window_value": days, "horizon_days": days}
        return None
