from __future__ import annotations

import re

from .entity_extraction import EntityExtractionService

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
    OVERVIEW_HINTS = ["情况", "概况", "整体", "总体", "态势", "表现", "怎么样", "如何", "什么情况"]
    RANKING_HINTS = ["最严重", "最厉害", "最多", "top", "Top", "TOP", "排行", "排名", "前5", "前十"]
    TREND_HINTS = ["走势", "趋势", "走向", "波动", "变化"]

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
        historical_window = structured.get("historical_window") or extracted.get("historical_window") or self._extract_past_window(cleaned)
        future_window = structured.get("future_window") or extracted.get("future_window") or self._extract_future_window(cleaned)
        region_name = self._coalesce_region_name(
            structured.get("region_name") if isinstance(structured.get("region_name"), str) else "",
            extracted.get("region_name") if isinstance(extracted.get("region_name"), str) else self._extract_region(cleaned),
        ) or (str((context or {}).get("region_name") or "") if reuse_region_from_context else "")

        needs_explanation = any(token in cleaned for token in ["为什么", "原因", "依据"])
        needs_advice = (
            any(token in cleaned for token in ["建议", "处置", "怎么办", "怎么做", "怎么处理", "怎么养", "防治", "如何防治"])
            and not self._asks_stored_disposal_field(cleaned)
        )
        if structured.get("needs_explanation") is True:
            needs_explanation = True
        if structured.get("needs_advice") is True:
            needs_advice = True

        task_type = structured.get("task_type") or self._infer_task_type(cleaned, domain, region_name, needs_explanation, needs_advice)
        needs_forecast = self._needs_forecast(cleaned, future_window, needs_advice)
        needs_historical = self._needs_historical(cleaned, historical_window, future_window, domain, task_type, region_name)

        execution_plan = ["understand_request"]
        if needs_historical:
            execution_plan.append("historical_query")
        if needs_forecast:
            execution_plan.append("forecast")
        if needs_explanation or needs_advice:
            execution_plan.append("knowledge_retrieval")
        execution_plan.append("answer_synthesis")

        normalized_question = self._build_normalized_question(
            domain=domain,
            historical_window=historical_window,
            future_window=future_window,
            cleaned=cleaned,
            needs_explanation=needs_explanation,
            needs_advice=needs_advice,
            task_type=task_type,
            region_name=region_name,
        )
        historical_query_text = self._build_historical_query_text(
            domain=domain,
            historical_window=historical_window,
            cleaned=cleaned,
            task_type=task_type,
            region_name=region_name,
        )

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
            "needs_historical": needs_historical,
            "needs_forecast": needs_forecast,
            "needs_explanation": needs_explanation,
            "needs_advice": needs_advice,
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
        if self.backend is None or not cleaned:
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
        if task_type in {"ranking", "trend", "region_overview", "joint_risk"}:
            normalized["task_type"] = task_type
        region_name = self._coalesce_region_name(str(payload.get("region_name") or ""), "")
        if region_name:
            normalized["region_name"] = region_name
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

    def _resolve_with_context(self, text: str, context: dict | None) -> tuple[str, list[str]]:
        context = dict(context or {})
        cleaned = self._normalize_city_mentions(self._normalize_spaces(text))
        if not cleaned:
            return cleaned, []

        pending_question = self._normalize_spaces(str(context.get("pending_user_question") or ""))
        pending_clarification = str(context.get("pending_clarification") or "")
        if pending_question and pending_clarification == "agri_domain":
            if self._contains_pest(cleaned):
                return self._inject_domain_into_question(pending_question, "pest"), ["resolved_agri_domain_from_pending_question"]
            if self._contains_soil(cleaned):
                return self._inject_domain_into_question(pending_question, "soil"), ["resolved_agri_domain_from_pending_question"]

        domain = str(context.get("domain") or "")
        region_name = self._normalize_spaces(str(context.get("region_name") or ""))
        if (domain or region_name) and self._is_contextual_follow_up(cleaned):
            current_region = self._extract_region(cleaned)
            reuse_region = not current_region and self._should_reuse_context_region(cleaned)
            prefix_region = region_name if reuse_region else ""
            parts = [part for part in [prefix_region, self._domain_label(domain), cleaned] if part]
            resolution = ["expanded_short_follow_up_from_memory"]
            if reuse_region:
                resolution.append("reused_region_from_memory")
            return self._normalize_spaces(" ".join(parts)), resolution

        return cleaned, []

    def _strip_noise(self, text: str) -> tuple[str, list[str]]:
        ignored: list[str] = []
        cleaned = text
        for phrase in self.NOISE_PHRASES:
            if phrase in cleaned:
                ignored.append(phrase)
                cleaned = cleaned.replace(phrase, " ")
        cleaned = re.sub(r"[，。！？；、]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned, ignored

    @staticmethod
    def _normalize_spaces(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "").strip())

    @staticmethod
    def _normalize_city_mentions(text: str) -> str:
        normalized = text
        for alias, canonical in CITY_ALIASES.items():
            normalized = re.sub(rf"{alias}(?!市)", canonical, normalized)
        return normalized

    @staticmethod
    def _coalesce_region_name(primary: str, secondary: str | None) -> str:
        for candidate in [primary, secondary or ""]:
            if not candidate:
                continue
            if candidate in CITY_ALIASES.values():
                return candidate
            if re.fullmatch(r"[\u4e00-\u9fa5]{2,12}(?:市|县|区)", candidate):
                return candidate
        return ""

    @staticmethod
    def _contains_pest(text: str) -> bool:
        return "虫情" in text or "虫害" in text or text.strip() == "虫"

    @staticmethod
    def _contains_soil(text: str) -> bool:
        return "墒情" in text or text.strip() == "墒"

    @classmethod
    def _domain_label(cls, domain: str) -> str:
        if domain == "pest":
            return "虫情"
        if domain == "soil":
            return "墒情"
        return ""

    @classmethod
    def _inject_domain_into_question(cls, question: str, domain: str) -> str:
        label = cls._domain_label(domain)
        if not label:
            return cls._normalize_spaces(question)
        base = cls._normalize_spaces(question)
        if label in base:
            return base
        for token in ["受灾", "灾害情况", "灾害"]:
            if token in base:
                return cls._normalize_follow_up_question(base.replace(token, label))
        if "最严重的地方" in base:
            return cls._normalize_follow_up_question(base.replace("最严重的地方", f"{label}最严重的地方"))
        if "最严重" in base:
            return cls._normalize_follow_up_question(base.replace("最严重", f"{label}最严重"))
        return cls._normalize_follow_up_question(f"{base} {label}")

    @staticmethod
    def _is_contextual_follow_up(text: str) -> bool:
        stripped = text.strip()
        if re.search(r"(SNS\d+|设备|预警时间|等级|最近一次|这条预警|哪个|多少|Top|TOP|20\d{2}年)", stripped):
            return False
        if len(stripped) <= 8:
            return True
        return stripped in {"未来两周呢", "未来两周", "给建议", "建议", "处置建议", "原因呢", "为什么呢", "怎么办", "怎么做"}

    @staticmethod
    def _should_reuse_context_region(text: str) -> bool:
        stripped = text.strip()
        if stripped in {"未来两周呢", "未来两周", "给建议", "建议", "处置建议", "原因呢", "为什么呢", "怎么办", "怎么做", "怎么处理"}:
            return True
        if len(stripped) <= 4:
            return True
        return any(token in stripped for token in ["那里", "那边", "这边", "这里", "这个地方", "这地方", "该地区", "该地", "那呢", "这呢"])

    @staticmethod
    def _normalize_follow_up_question(text: str) -> str:
        normalized = re.sub(r"[，。！？；、]+", "", text)
        return re.sub(r"\s+", " ", normalized).strip()

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
    def _needs_forecast(text: str, future_window: dict | None, needs_advice: bool) -> bool:
        if future_window is not None:
            return True
        if any(token in text for token in ["会不会更糟", "会不会恶化"]):
            return True
        if needs_advice:
            return False
        return bool(re.search(r"未来.*(会怎样|怎么样|趋势|风险|变化)", text))

    @staticmethod
    def _infer_domain(text: str, context: dict | None) -> str:
        has_pest = "虫情" in text or "虫害" in text
        has_soil = any(token in text for token in ["墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"])
        if has_pest and has_soil:
            return "mixed"
        if has_pest:
            return "pest"
        if has_soil:
            return "soil"
        if context and context.get("domain"):
            return str(context["domain"])
        return ""

    @staticmethod
    def _extract_region(text: str) -> str | None:
        normalized = RequestUnderstanding._normalize_city_mentions(text)
        city_positions: list[tuple[int, str]] = []
        for canonical in CITY_ALIASES.values():
            for match in re.finditer(re.escape(canonical), normalized):
                city_positions.append((match.start(), canonical))
        if city_positions:
            city_positions.sort(key=lambda item: item[0])
            return city_positions[-1][1]
        county = re.findall(r"([\u4e00-\u9fa5]{1,12}(?:县|区))", normalized)
        if county:
            return county[-1]
        city = re.findall(r"([\u4e00-\u9fa5]{2,6}市)", normalized)
        for item in reversed(city):
            if item not in {"城市"} and not item.endswith("城市"):
                return item
        return None

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
        if m := re.search(r"(?:过去|最近|近)(\d+|[一二两三四五六七八九十])个?月", text):
            months = max(1, RequestUnderstanding._parse_number_token(m.group(1)) or 1)
            return {"window_type": "months", "window_value": months}
        if m := re.search(r"(?:过去|最近|近)(\d+|[一二两三四五六七八九十])个?(?:星期|周)", text):
            weeks = max(1, RequestUnderstanding._parse_number_token(m.group(1)) or 1)
            return {"window_type": "weeks", "window_value": weeks}
        if m := re.search(r"(?:过去|最近|近)(\d+|[一二两三四五六七八九十])天", text):
            days = max(1, RequestUnderstanding._parse_number_token(m.group(1)) or 1)
            return {"window_type": "days", "window_value": days}
        return {"window_type": "all", "window_value": None}

    @staticmethod
    def _extract_future_window(text: str) -> dict | None:
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

    @classmethod
    def _infer_task_type(cls, text: str, domain: str, region_name: str, needs_explanation: bool, needs_advice: bool) -> str:
        if needs_explanation or needs_advice:
            if any(token in text for token in cls.TREND_HINTS):
                return "trend"
            if any(token in text for token in cls.RANKING_HINTS):
                return "ranking"
            if domain == "mixed" and any(token in text for token in ["同时", "而且", "共同", "叠加"]):
                return "joint_risk"
            return "unknown"
        if domain == "mixed" or (
            ("虫情" in text or "虫害" in text)
            and any(token in text for token in ["墒情", "缺水", "低墒", "干旱"])
            and any(token in text for token in ["同时", "而且", "共同", "叠加"])
        ):
            return "joint_risk"
        if any(token in text for token in cls.TREND_HINTS):
            return "trend"
        if any(token in text for token in cls.RANKING_HINTS):
            return "ranking"
        if region_name and domain in {"pest", "soil"} and any(token in text for token in cls.OVERVIEW_HINTS):
            return "region_overview"
        if region_name and domain in {"pest", "soil"} and not any(token in text for token in cls.TREND_HINTS + cls.RANKING_HINTS):
            return "region_overview"
        if domain and re.search(r"(哪些地区|哪些地方|哪个地区|哪个地方|哪里|哪儿)", text):
            return "ranking"
        return "unknown"

    @staticmethod
    def _needs_historical(text: str, historical_window: dict, future_window: dict | None, domain: str, task_type: str, region_name: str) -> bool:
        if future_window and historical_window.get("window_type") == "all":
            if not any(token in text for token in ["过去", "最近", "近", "历史", "此前", "之前"]):
                return False
        if task_type in {"ranking", "trend", "region_overview", "joint_risk"} and domain:
            return True
        if historical_window.get("window_type") != "all":
            return True
        if any(token in text for token in ["最严重", "最多", "最高", "趋势", "历史", "过去", "近"]) and domain:
            return True
        if domain and re.search(r"(哪些地区|哪些地方|哪个地区|哪个地方|哪里|哪儿)", text):
            return True
        if region_name and domain in {"pest", "soil"} and not any(token in text for token in ["为什么", "原因", "依据", "建议", "处置"]):
            return True
        return False

    @staticmethod
    def _window_prefix(window: dict) -> str:
        if window.get("window_type") == "months":
            return f"过去{window['window_value']}个月"
        if window.get("window_type") == "weeks":
            return f"过去{window['window_value']}个星期"
        if window.get("window_type") == "days":
            return f"过去{window['window_value']}天"
        return "历史上"

    def _build_historical_query_text(self, domain: str, historical_window: dict, cleaned: str, task_type: str, region_name: str) -> str:
        if not domain:
            return cleaned
        if task_type in {"trend", "region_overview", "joint_risk"}:
            return cleaned
        prefix = self._window_prefix(historical_window)
        if domain == "pest" and task_type == "ranking":
            return f"{prefix}虫情最严重的地方是哪里"
        if domain == "soil" and task_type == "ranking":
            return f"{prefix}墒情最严重的地方是哪里"
        if region_name and task_type == "region_overview":
            return cleaned
        return cleaned

    def _build_normalized_question(
        self,
        *,
        domain: str,
        historical_window: dict,
        future_window: dict | None,
        cleaned: str,
        needs_explanation: bool,
        needs_advice: bool,
        task_type: str,
        region_name: str,
    ) -> str:
        parts: list[str] = []
        if domain and self._needs_historical(cleaned, historical_window, future_window, domain, task_type, region_name):
            parts.append(self._build_historical_query_text(domain, historical_window, cleaned, task_type, region_name))
        elif cleaned:
            parts.append(cleaned)

        if future_window:
            if future_window["window_type"] == "weeks" and future_window["window_value"] == 2:
                parts.append("未来两周")
            elif future_window["window_type"] == "months":
                parts.append(f"未来{future_window['window_value']}个月")
            else:
                parts.append(f"未来{future_window['horizon_days']}天")

        if needs_explanation:
            parts.append("原因")
        if needs_advice:
            parts.append("处置建议")

        normalized = " ".join(part for part in parts if part)
        return re.sub(r"\s+", " ", normalized).strip()
