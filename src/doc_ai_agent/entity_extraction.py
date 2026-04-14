from __future__ import annotations

import os
import re
from datetime import datetime
from dataclasses import dataclass

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


@dataclass
class EntityExtractionService:
    enable_hanlp: bool | None = None
    hanlp_pipeline: object | None = None

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

    def __post_init__(self) -> None:
        if self.enable_hanlp is None:
            self.enable_hanlp = str(os.getenv("DOC_AI_ENABLE_HANLP", "0")).strip() == "1"
        self._hanlp_attempted = self.hanlp_pipeline is not None

    def extract(self, text: str) -> dict:
        cleaned = self._normalize_city_mentions(self._normalize_spaces(text))
        if not cleaned:
            return {"engine": "fallback"}

        if self.enable_hanlp:
            hanlp_payload = self._extract_with_hanlp(cleaned)
            if hanlp_payload:
                return hanlp_payload

        return {
            "engine": "fallback",
            "domain": self._infer_domain(cleaned),
            "region_name": self._extract_region(cleaned),
            "historical_window": self._extract_past_window(cleaned),
            "future_window": self._extract_future_window(cleaned),
        }

    def _extract_with_hanlp(self, text: str) -> dict | None:
        pipeline = self._load_hanlp_pipeline()
        if pipeline is None:
            return None
        try:
            result = pipeline(text)
        except Exception:
            return None

        tokens = result.get("tok/fine") if isinstance(result, dict) else None
        ner = result.get("ner/msra") if isinstance(result, dict) else None
        region_name = self._region_from_hanlp(tokens, ner, text)
        domain = self._infer_domain(text)
        historical_window = self._extract_past_window(text)
        future_window = self._extract_future_window(text)
        if not any([region_name, domain, historical_window.get("window_type") != "all", future_window]):
            return None
        return {
            "engine": "hanlp",
            "domain": domain,
            "region_name": region_name,
            "historical_window": historical_window,
            "future_window": future_window,
        }

    def _load_hanlp_pipeline(self):
        if self._hanlp_attempted:
            return self.hanlp_pipeline
        self._hanlp_attempted = True
        try:
            import hanlp
        except Exception:
            self.hanlp_pipeline = None
            return None
        try:
            self.hanlp_pipeline = hanlp.load(hanlp.pretrained.mtl.CLOSE_TOK_POS_NER_SRL_DEP_SDP_CON_ELECTRA_SMALL_ZH)
        except Exception:
            self.hanlp_pipeline = None
        return self.hanlp_pipeline

    @classmethod
    def _region_from_hanlp(cls, tokens: object, ner: object, text: str) -> str:
        if isinstance(ner, list):
            for item in reversed(ner):
                if not isinstance(item, (list, tuple)) or not item:
                    continue
                candidate = str(item[0] or "")
                normalized = cls._canonicalize_region(candidate)
                if normalized:
                    return normalized
        if isinstance(tokens, list):
            for token in reversed(tokens):
                normalized = cls._canonicalize_region(str(token or ""))
                if normalized:
                    return normalized
        return cls._extract_region(text)

    @classmethod
    def _canonicalize_region(cls, text: str) -> str:
        candidate = cls._normalize_spaces(text)
        if not candidate:
            return ""
        if candidate in CITY_ALIASES:
            return CITY_ALIASES[candidate]
        if candidate in CITY_ALIASES.values():
            return candidate
        if re.fullmatch(r"[\u4e00-\u9fa5]{1,12}(?:县|区)", candidate):
            return candidate
        if re.fullmatch(r"[\u4e00-\u9fa5]{2,12}市", candidate) and candidate not in {"城市"} and not candidate.endswith("城市"):
            return candidate
        return ""

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
    def _infer_domain(text: str) -> str:
        has_pest = "虫情" in text or "虫害" in text
        has_soil = any(token in text for token in ["墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"])
        if has_pest and has_soil:
            return "mixed"
        if has_pest:
            return "pest"
        if has_soil:
            return "soil"
        return ""

    @classmethod
    def _parse_number_token(cls, token: str) -> int | None:
        value = str(token or "").strip()
        if not value:
            return None
        if value.isdigit():
            return int(value)
        return cls.CHINESE_NUMBER_MAP.get(value)

    @classmethod
    def _extract_past_window(cls, text: str) -> dict:
        if "今年以来" in text:
            current_year = datetime.now().year
            return {"window_type": "year_since", "window_value": current_year}
        if m := re.search(r"(?:过去|最近|近)(\d+|[一二两三四五六七八九十])个?月", text):
            months = max(1, cls._parse_number_token(m.group(1)) or 1)
            return {"window_type": "months", "window_value": months}
        if m := re.search(r"(?:过去|最近|近)(\d+|[一二两三四五六七八九十])个?(?:星期|周)", text):
            weeks = max(1, cls._parse_number_token(m.group(1)) or 1)
            return {"window_type": "weeks", "window_value": weeks}
        if m := re.search(r"(?:过去|最近|近)(\d+|[一二两三四五六七八九十])天", text):
            days = max(1, cls._parse_number_token(m.group(1)) or 1)
            return {"window_type": "days", "window_value": days}
        return {"window_type": "all", "window_value": None}

    @classmethod
    def _extract_future_window(cls, text: str) -> dict | None:
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

    @classmethod
    def _extract_region(cls, text: str) -> str:
        normalized = cls._normalize_city_mentions(text)
        city_positions: list[tuple[int, str]] = []
        for canonical in CITY_ALIASES.values():
            for match in re.finditer(re.escape(canonical), normalized):
                city_positions.append((match.start(), canonical))
        if city_positions:
            city_positions.sort(key=lambda item: item[0])
            return city_positions[-1][1]
        county_match = re.search(r"(?<!哪些)(?<!哪个)(?<!什么)([\u4e00-\u9fa5]{1,12}(?:县|区))", normalized)
        if county_match:
            county = county_match.group(1)
            if county not in {"地区", "区域", "市区", "城区"} and not any(
                token in county for token in ["预警", "最多", "最严重", "地方", "地区"]
            ) and not county.startswith("个"):
                return county
        city = re.findall(r"([\u4e00-\u9fa5]{2,6}市)", normalized)
        for item in reversed(city):
            if item not in {"城市"} and not item.endswith("城市"):
                return item
        return ""
