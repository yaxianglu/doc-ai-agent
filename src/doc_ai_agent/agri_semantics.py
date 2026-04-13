from __future__ import annotations

import re

OVERVIEW_HINTS = ["情况", "概况", "整体", "总体", "态势", "表现", "怎么样", "如何", "什么情况"]
RANKING_HINTS = ["最严重", "最厉害", "最多", "最高", "最突出", "top", "排行", "排名", "前5", "前十"]
TREND_HINTS = ["走势", "趋势", "走向", "波动", "变化"]
DETAIL_HINTS = ["具体数据", "详细数据", "数据明细", "明细数据", "原始数据", "具体数值", "详细数值", "逐日数据", "每天数据"]
COUNTY_SCOPE_HINTS = ["区县", "按县", "按区县", "各县", "各区县", "哪个县", "哪些县", "什么县", "哪几个县", "哪个区", "哪些区", "什么区", "哪几个区"]
SOIL_HINTS = ["墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"]


def asks_county_scope(text: str) -> bool:
    normalized = str(text or "")
    if not normalized:
        return False
    if any(token in normalized for token in COUNTY_SCOPE_HINTS):
        return True
    return bool(re.search(r"(?:县|区)(?:有哪些|有哪几个|有哪个|是哪些|是哪几个|是什么)", normalized))


def has_ranking_intent(text: str) -> bool:
    normalized = str(text or "")
    lowered = normalized.lower()
    if any(token in lowered for token in [token.lower() for token in RANKING_HINTS]):
        return True
    return bool(re.search(r"(排前面|排前列|最靠前|靠前的)", normalized))


def has_trend_intent(text: str) -> bool:
    normalized = str(text or "")
    return any(token in normalized for token in TREND_HINTS)


def has_overview_intent(text: str) -> bool:
    normalized = str(text or "")
    return any(token in normalized for token in OVERVIEW_HINTS)


def has_detail_intent(text: str) -> bool:
    normalized = str(text or "")
    if any(token in normalized for token in DETAIL_HINTS):
        return True
    return any(token in normalized for token in ["明细", "按天", "逐天", "列出来"]) or ("数据" in normalized and not has_overview_intent(normalized))


def infer_domain_from_text(text: str, context_domain: str = "") -> str:
    normalized = str(text or "")
    has_pest = "虫情" in normalized or "虫害" in normalized
    has_soil = any(token in normalized for token in SOIL_HINTS)
    if has_pest and has_soil:
        return "mixed"
    if has_pest:
        return "pest"
    if has_soil:
        return "soil"
    if context_domain in {"pest", "soil", "mixed"}:
        return context_domain
    return ""
