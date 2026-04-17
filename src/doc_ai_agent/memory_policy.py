"""多轮记忆继承策略：限制哪些上下文可以安全复用。"""

from __future__ import annotations


DEFAULT_ALLOWED_SLOTS = ("domain", "region", "time_window", "referent")
DEFAULT_FORBIDDEN_SLOTS = ("facts", "rank_results", "forecast_results")
FACT_REFERENCE_TOKENS = ("这个结论", "这个结果", "这个排名", "这个数", "这个值")
AMBIGUOUS_REFERENCE_TOKENS = ("还是这个吗", "还是这样吗", "这个吗", "这样吗", "还是这个")
WEAK_FOLLOW_UP_TOKENS = ("那", "呢", "未来", "过去", "近", "原因", "为什么", "建议", "处置", "怎么办", "怎么做")


def evaluate_memory_policy(question: str, context: dict | None) -> dict:
    """基于当前问题和历史上下文判断是否允许继承。"""

    normalized_question = str(question or "").strip()
    normalized_context = dict(context or {})
    configured = dict(normalized_context.get("memory_policy") or {})
    allowed_slots = list(configured.get("allowed_slots") or DEFAULT_ALLOWED_SLOTS)
    forbidden_slots = list(configured.get("forbidden_slots") or DEFAULT_FORBIDDEN_SLOTS)

    has_context = bool(
        normalized_context.get("domain")
        or normalized_context.get("region_name")
        or normalized_context.get("window")
        or normalized_context.get("last_answer")
    )
    inherited_slots: list[str] = []
    if normalized_context.get("domain"):
        inherited_slots.append("domain")
    if normalized_context.get("region_name"):
        inherited_slots.append("region")
    if isinstance(normalized_context.get("window"), dict) and str((normalized_context.get("window") or {}).get("window_type") or "") not in {"", "all", "none"}:
        inherited_slots.append("time_window")

    if not has_context:
        return {
            "inheritance_decision": "none",
            "allowed_slots": allowed_slots,
            "forbidden_slots": forbidden_slots,
            "inherited_slots": [],
            "blocked_slots": [],
            "confidence": 0.0,
            "should_clarify": False,
            "allow_context_rewrite": False,
        }

    if any(token in normalized_question for token in FACT_REFERENCE_TOKENS):
        return {
            "inheritance_decision": "block",
            "allowed_slots": allowed_slots,
            "forbidden_slots": forbidden_slots,
            "inherited_slots": [],
            "blocked_slots": ["facts"],
            "confidence": 0.92,
            "should_clarify": False,
            "allow_context_rewrite": False,
        }

    if any(token in normalized_question for token in AMBIGUOUS_REFERENCE_TOKENS):
        return {
            "inheritance_decision": "clarify",
            "allowed_slots": allowed_slots,
            "forbidden_slots": forbidden_slots,
            "inherited_slots": [],
            "blocked_slots": ["facts"],
            "confidence": 0.55,
            "should_clarify": True,
            "allow_context_rewrite": False,
        }

    if len(normalized_question) <= 12 and any(token in normalized_question for token in WEAK_FOLLOW_UP_TOKENS):
        safe_slots = [slot for slot in inherited_slots if slot in allowed_slots]
        return {
            "inheritance_decision": "allow",
            "allowed_slots": allowed_slots,
            "forbidden_slots": forbidden_slots,
            "inherited_slots": safe_slots,
            "blocked_slots": [],
            "confidence": 0.82 if safe_slots else 0.4,
            "should_clarify": False,
            "allow_context_rewrite": bool(safe_slots),
        }

    return {
        "inheritance_decision": "none",
        "allowed_slots": allowed_slots,
        "forbidden_slots": forbidden_slots,
        "inherited_slots": [],
        "blocked_slots": [],
        "confidence": 0.2,
        "should_clarify": False,
        "allow_context_rewrite": False,
    }
