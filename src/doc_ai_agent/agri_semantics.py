"""农业语义规则层。

本模块只做“轻量规则判断”，用于把自然语言问题映射成可执行语义信号：
- 是否在问排行、趋势、概览、明细；
- 是否需要原因解释、处置建议、未来预测；
- 问题更偏虫情、墒情还是两者混合。

这些函数都保持无副作用，便于在理解流程中反复组合调用。
"""

from __future__ import annotations

import re

OVERVIEW_HINTS = ["情况", "概况", "整体", "总体", "态势", "表现", "怎么样", "如何", "什么情况"]
RANKING_HINTS = ["最严重", "最厉害", "最多", "最高", "最突出", "最重", "最异常", "重点盯防", "top", "排行", "排名", "前5", "前十"]
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
    """判断用户是否明确表达“不要建议/处置”。

    例如“先不要给建议”“别说处置方案”等都应视为否定建议意图。
    """
    normalized = str(text or "")
    return bool(re.search(r"(不要|别|不用|不需要|先不要|先别)(?:再)?(?:给)?(?:我)?建议", normalized)) or bool(
        re.search(r"(不要|别|不用|不需要|先不要|先别)(?:给)?(?:我)?(?:处置|防治)", normalized)
    )


def needs_explanation(text: str) -> bool:
    """判断是否需要“原因解释”类回答。"""
    normalized = str(text or "")
    return any(token in normalized for token in EXPLANATION_HINTS)


def needs_advice(text: str) -> bool:
    """判断是否需要“处置建议”类回答。"""
    normalized = str(text or "")
    return not has_negated_advice(normalized) and any(token in normalized for token in ADVICE_HINTS)


def needs_forecast(text: str, future_window: dict | None, needs_advice: bool = False) -> bool:
    """判断是否需要未来预测。

    规则优先级：
    1) 只要识别到未来时间窗，直接需要预测；
    2) 命中“会不会恶化”等强提示，也需要预测；
    3) 单独要建议时默认不自动开启预测，避免答非所问。
    """
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
    """推断默认地区粒度：县级优先，否则回到市级。"""
    return "county" if asks_county_scope(text) else "city"


def asks_county_scope(text: str) -> bool:
    """判断用户是否在要求县/区粒度。"""
    normalized = str(text or "")
    if not normalized:
        return False
    if re.search(r"(最严重|最高|最突出|风险最高).*(县|区|区县)", normalized):
        return True
    if re.search(r"(再细到|细到|细分到)(?:区|县|区县)", normalized):
        return True
    if re.search(r"(县|区).*(不是).*(市)", normalized):
        return True
    if re.search(r"(我问的是|我说的是|问的是|说的是).*(县|区)", normalized):
        return True
    if any(token in normalized for token in COUNTY_SCOPE_HINTS):
        return True
    return bool(re.search(r"(?:县|区)(?:有哪些|有哪几个|有哪个|是哪些|是哪几个|是什么)", normalized))


def has_ranking_intent(text: str) -> bool:
    """判断是否为排行/Top 类问题。"""
    normalized = str(text or "")
    lowered = normalized.lower()
    if any(token in lowered for token in [token.lower() for token in RANKING_HINTS]):
        return True
    return bool(re.search(r"(排前面|排前列|最靠前|靠前的)", normalized))


def has_trend_intent(text: str) -> bool:
    """判断是否为趋势/变化类问题。"""
    normalized = str(text or "")
    if any(token in normalized for token in TREND_HINTS):
        return True
    return bool(
        re.search(r"(上升|下降).*(吗|还是|趋势|原因)?", normalized)
        or re.search(r"(增加|减少).*(吗|还是|趋势|变化)?", normalized)
        or re.search(r"(有没有|是否).*(缓解|好转)", normalized)
        or re.search(r"(继续).*(恶化|变严重)", normalized)
        or re.search(r"(变严重|变糟|加重了?)", normalized)
        or "缓解" in normalized
    )


def has_overview_intent(text: str) -> bool:
    """判断是否为概览类问题（整体情况）。"""
    normalized = str(text or "")
    return any(token in normalized for token in OVERVIEW_HINTS)


def has_detail_intent(text: str) -> bool:
    """判断是否为明细数据诉求。"""
    normalized = str(text or "")
    if any(token in normalized for token in DETAIL_HINTS):
        return True
    return any(token in normalized for token in ["明细", "按天", "逐天", "列出来"]) or ("数据" in normalized and not has_overview_intent(normalized))


def infer_domain_from_text(text: str, context_domain: str = "") -> str:
    """根据文本推断领域：虫情 / 墒情 / 混合。

    当文本里没有明显领域词时，允许回退到上下文领域，保持多轮对话连贯。
    """
    normalized = str(text or "")
    has_pest = "虫情" in normalized or "虫害" in normalized
    has_soil = any(token in normalized for token in SOIL_HINTS)
    if has_pest and has_soil:
        return "mixed"
    if has_pest:
        return "pest"
    if has_soil:
        return "soil"
    if "联合风险" not in normalized and re.search(r"(风险最高|最值得重点盯防|最需要关注)", normalized):
        return "pest"
    if context_domain in {"pest", "soil", "mixed"}:
        return context_domain
    return ""
