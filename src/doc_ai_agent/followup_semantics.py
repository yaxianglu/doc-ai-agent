"""多轮追问语义判断。

本模块用于识别“当前输入是不是在接着上一轮问”，并抽取追问类型：
- 是否是短追问；
- 是否在补充明细/建议/原因；
- 是否显式切换领域或修正范围。
"""

from __future__ import annotations

import re

from .agri_semantics import has_detail_intent, infer_domain_from_text, needs_advice, needs_explanation


def looks_like_contextual_follow_up(question: str, *, is_greeting_question) -> bool:
    """判断输入是否“看起来像”依赖上下文的追问。"""
    stripped = (question or "").strip()
    if not stripped:
        return False
    if is_greeting_question(stripped):
        return False
    if re.search(r"(SNS\d+|设备|最近一次|预警时间|告警值|按告警等级|20\d{2}年)", stripped):
        return False
    if len(stripped) <= 12:
        return True
    return bool(re.match(r"^(那|那么|那就|未来|换成|改成|建议|给建议|处置建议|为什么|原因|我说的是|不是趋势|具体数据)", stripped))


def is_detail_follow_up(question: str) -> bool:
    """判断是否在追问“具体数据/明细”。"""
    return has_detail_intent(question or "")


def is_advice_follow_up(question: str) -> bool:
    """判断是否在追问“处置建议”。"""
    return needs_advice(question or "")


def is_explanation_follow_up(question: str) -> bool:
    """判断是否在追问“原因解释”。"""
    return needs_explanation(question or "")


def has_domain_switch_verb(question: str) -> bool:
    """判断是否包含“换成/切到”等领域切换动词。"""
    return bool(re.search(r"(换成|改成|改看|切到|切换到|切换成|改为|换看)", question or ""))


def explicit_domain_from_text(question: str, *, context_domain: str = "") -> str:
    """从文本里抽取显式领域，必要时回退到上下文领域。"""
    return infer_domain_from_text(question or "", context_domain=context_domain)


def is_scope_correction_follow_up(question: str) -> bool:
    """判断是否在纠正范围（如“我问县，不是市”）。"""
    stripped = (question or "").strip()
    if not stripped:
        return False
    return bool(
        re.search(r"(我问的是|我说的是|问的是|说的是).*(县|区).*(不是).*(市)", stripped)
        or re.search(r"(我问的是|我说的是|问的是|说的是).*(市).*(不是).*(县|区)", stripped)
    )
