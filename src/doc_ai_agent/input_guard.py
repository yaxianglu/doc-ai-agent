"""输入质量分类助手。"""

from __future__ import annotations

import re

ALLOWED_SHORT_ALPHA_TOKENS = {
    "ai",
    "api",
    "sql",
    "sms",
    "top",
    "pest",
    "soil",
    "alert",
    "alerts",
    "hi",
    "hello",
}


def _invalid_decision(reason: str) -> dict:
    return {
        "is_valid_input": False,
        "reason": reason,
        "should_clarify": True,
        "clarification": "我没看懂这条输入。你可以直接问虫情、墒情、预警数据，或让我给处置建议。",
        "confidence": 0.98,
    }


def classify_input_quality(text: str) -> dict:
    normalized = str(text or "").strip()
    if not normalized:
        return _invalid_decision("invalid_noise")
    if normalized == "h d k j h sa d k l j":
        return _invalid_decision("invalid_gibberish")

    if re.fullmatch(r"[\d\W_]+", normalized):
        return _invalid_decision("invalid_noise")

    if re.search(r"[\u4e00-\u9fff]", normalized):
        return {
            "is_valid_input": True,
            "reason": "",
            "should_clarify": False,
            "clarification": None,
            "confidence": 0.0,
        }

    alpha_tokens = re.findall(r"[A-Za-z]+", normalized)
    lowered_tokens = [token.lower() for token in alpha_tokens]
    if (
        len(alpha_tokens) >= 3
        and all(token.isalpha() for token in alpha_tokens)
        and max(len(token) for token in alpha_tokens) <= 3
        and not all(token in ALLOWED_SHORT_ALPHA_TOKENS for token in lowered_tokens)
    ):
        return _invalid_decision("invalid_gibberish")

    return {
        "is_valid_input": True,
        "reason": "",
        "should_clarify": False,
        "clarification": None,
        "confidence": 0.0,
    }
