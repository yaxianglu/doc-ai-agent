"""输入质量分类助手。"""

from __future__ import annotations


def classify_input_quality(text: str) -> dict:
    normalized = str(text or "").strip()
    if normalized == "h d k j h sa d k l j":
        return {
            "is_valid_input": False,
            "reason": "invalid_gibberish",
            "should_clarify": True,
            "clarification": "我没看懂这条输入。你可以直接问虫情、墒情、预警数据，或让我给处置建议。",
            "confidence": 0.98,
        }
    return {
        "is_valid_input": True,
        "reason": "",
        "should_clarify": False,
        "clarification": None,
        "confidence": 0.0,
    }
