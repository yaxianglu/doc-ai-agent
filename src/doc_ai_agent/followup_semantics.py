from __future__ import annotations

import re

from .agri_semantics import has_detail_intent, infer_domain_from_text, needs_advice, needs_explanation


def looks_like_contextual_follow_up(question: str, *, is_greeting_question) -> bool:
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
    return has_detail_intent(question or "")


def is_advice_follow_up(question: str) -> bool:
    return needs_advice(question or "")


def is_explanation_follow_up(question: str) -> bool:
    return needs_explanation(question or "")


def has_domain_switch_verb(question: str) -> bool:
    return bool(re.search(r"(换成|改成|改看|切到|切换到|切换成|改为|换看)", question or ""))


def explicit_domain_from_text(question: str, *, context_domain: str = "") -> str:
    return infer_domain_from_text(question or "", context_domain=context_domain)


def is_scope_correction_follow_up(question: str) -> bool:
    stripped = (question or "").strip()
    if not stripped:
        return False
    return bool(
        re.search(r"(我问的是|我说的是|问的是|说的是).*(县|区).*(不是).*(市)", stripped)
        or re.search(r"(我问的是|我说的是|问的是|说的是).*(市).*(不是).*(县|区)", stripped)
    )
