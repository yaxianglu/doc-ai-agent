from __future__ import annotations

import re

OVERVIEW_HINTS = ["情况", "概况", "整体", "总体", "态势", "表现", "怎么样", "如何", "什么情况"]
RANKING_HINTS = ["最严重", "最厉害", "最多", "最高", "最突出", "top", "排行", "排名", "前5", "前十"]
TREND_HINTS = ["走势", "趋势", "走向", "波动", "变化"]
DETAIL_HINTS = ["具体数据", "详细数据", "数据明细", "明细数据", "原始数据", "具体数值", "详细数值", "逐日数据", "每天数据"]
COUNTY_SCOPE_HINTS = ["区县", "按县", "按区县", "各县", "各区县", "哪个县", "哪些县", "什么县", "哪几个县", "哪个区", "哪些区", "什么区", "哪几个区"]
SOIL_HINTS = ["墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"]
EXPLANATION_HINTS = ["为什么", "为啥", "原因", "依据"]
ADVICE_HINTS = ["建议", "处置", "怎么办", "该咋办", "咋办", "怎么做", "怎么处理", "咋处理", "怎么养", "防治", "如何防治"]
FORECAST_SEVERITY_HINTS = [
    "会不会更糟",
    "会不会恶化",
    "会更糟吗",
    "会恶化吗",
    "未来会更糟",
    "会不会更严重",
    "会更严重吗",
    "未来会更严重",
    "会不会继续变严重",
    "会继续变严重吗",
    "继续变严重吗",
    "会不会继续恶化",
]


def has_negated_advice(text: str) -> bool:
    normalized = str(text or "")
    return bool(re.search(r"(不要|别|不用|不需要|先不要|先别)(?:再)?(?:给)?(?:我)?建议", normalized)) or bool(
        re.search(r"(不要|别|不用|不需要|先不要|先别)(?:给)?(?:我)?(?:处置|防治)", normalized)
    )


def needs_explanation(text: str) -> bool:
    normalized = str(text or "")
    return any(token in normalized for token in EXPLANATION_HINTS)


def needs_advice(text: str) -> bool:
    normalized = str(text or "")
    return not has_negated_advice(normalized) and any(token in normalized for token in ADVICE_HINTS)


def needs_forecast(text: str, future_window: dict | None, needs_advice: bool = False) -> bool:
    normalized = str(text or "")
    if future_window is not None:
        return True
    if any(token in normalized for token in FORECAST_SEVERITY_HINTS):
        return True
    if re.search(r"未来.*(会怎样|怎么样|趋势|风险|变化)", normalized):
        return True
    if needs_advice:
        return False
    return False


def infer_region_scope(text: str) -> str:
    return "county" if asks_county_scope(text) else "city"


def asks_county_scope(text: str) -> bool:
    normalized = str(text or "")
    if not normalized:
        return False
    if re.search(r"(县|区).*(不是).*(市)", normalized):
        return True
    if re.search(r"(我问的是|我说的是|问的是|说的是).*(县|区)", normalized):
        return True
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
