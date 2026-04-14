"""规划器决策辅助函数。

这里放置可复用的小型决策逻辑，避免 `query_planner.py` 过度膨胀。
函数以“纯函数”为主，便于测试与复用。
"""

from __future__ import annotations


def query_type_for_domain_switch(previous_query_type: str, next_domain: str) -> str:
    """在“切换领域”时保留原任务形态（forecast/detail/trend/top）。"""
    if previous_query_type.endswith("_forecast"):
        return f"{next_domain}_forecast"
    if previous_query_type.endswith("_detail"):
        return f"{next_domain}_detail"
    if previous_query_type.endswith("_trend"):
        return f"{next_domain}_trend"
    if previous_query_type.endswith("_top"):
        return f"{next_domain}_top"
    return f"{next_domain}_overview"


def query_type_for_region_follow_up(previous_query_type: str, domain: str) -> str:
    """在“切换地区”时保持分析类型不变，仅替换领域前缀。"""
    if previous_query_type.endswith("_forecast"):
        return f"{domain}_forecast"
    if previous_query_type.endswith("_detail"):
        return f"{domain}_detail"
    if previous_query_type.endswith("_trend"):
        return f"{domain}_trend"
    if previous_query_type.endswith("_top"):
        return f"{domain}_top"
    return f"{domain}_overview"


def query_type_for_window_follow_up(previous_query_type: str, domain: str) -> str:
    """在“切换时间窗”时推导新 query_type。"""
    if previous_query_type.endswith("_forecast"):
        return f"{domain}_forecast"
    if previous_query_type.endswith("_detail"):
        return f"{domain}_detail"
    if previous_query_type.endswith("_trend"):
        return f"{domain}_trend"
    if previous_query_type.endswith("_top"):
        return f"{domain}_top"
    if previous_query_type == "joint_risk":
        return "joint_risk"
    return f"{domain}_overview"


def has_agri_signal(question: str, playbook_route: dict | None, context: dict | None = None) -> bool:
    """判断问题是否具备农业领域信号（虫情/墒情）。"""
    q = question or ""
    if any(token in q for token in ["虫情", "虫害", "害虫", "墒情", "低墒", "高墒", "缺水", "干旱", "土壤", "含水"]):
        return True
    context_domain = str((context or {}).get("domain") or "")
    if context_domain in {"pest", "soil", "mixed"}:
        return True
    matched_terms = (playbook_route or {}).get("matched_terms")
    if isinstance(matched_terms, list):
        return any(any(token in str(term) for token in ["虫", "墒", "缺水", "干旱", "土壤", "含水"]) for term in matched_terms)
    return False


def asks_advice_or_explanation(question: str) -> bool:
    """判断是否偏向建议或解释，而非结构化数据检索。"""
    q = question or ""
    return any(token in q for token in ["建议", "处置", "怎么办", "怎么做", "怎么处理", "怎么养", "防治", "为什么", "原因", "依据"])


def should_use_playbook_route(
    *,
    question: str,
    heuristic_query_type: str,
    playbook_route: dict | None,
    deterministic_query_types: set[str],
    playbook_upgradeable_query_types: set[str],
    context: dict | None = None,
) -> bool:
    """判定是否采用 playbook 路由结果。"""
    if playbook_route is None:
        return False
    if heuristic_query_type in deterministic_query_types:
        return False
    if asks_advice_or_explanation(question):
        return False
    if not has_agri_signal(question, playbook_route, context=context):
        return False
    return heuristic_query_type in playbook_upgradeable_query_types


def playbook_context_trace(playbook_route: dict) -> list[str]:
    """提取可追踪的 playbook 命中信息，便于调试与审计。"""
    trace: list[str] = []
    reason = str(playbook_route.get("reason") or "").strip()
    if reason:
        trace.append(reason)
    retrieval_engine = str(playbook_route.get("retrieval_engine") or "").strip()
    if retrieval_engine:
        trace.append(f"playbook_router={retrieval_engine}")
    matched_terms = playbook_route.get("matched_terms")
    if isinstance(matched_terms, list) and matched_terms:
        trace.append("matched_terms=" + ",".join(str(term) for term in matched_terms[:4]))
    return trace


def normalize_history(history: object) -> list[dict[str, str]]:
    """清洗历史消息，仅保留合法的 user/assistant 文本。"""
    if not isinstance(history, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        normalized.append({"role": role, "content": content.strip()})
    return normalized


def resolve_follow_up_question(question: str, *, history: object, context: dict | None = None) -> str:
    """把“短回复式追问”拼接回上一轮用户主问题。

    例如上一轮问“看虫情还是墒情？”，本轮只回“虫情”，
    会重写成“上一轮主问题 + 虫情”，便于后续统一解析。
    """
    current = (question or "").strip()
    if not current:
        return current

    normalized_history = normalize_history(history)
    context = dict(context or {})
    if not normalized_history and not context:
        return current

    last_user_question = next((item["content"] for item in reversed(normalized_history) if item["role"] == "user"), "")
    last_assistant_reply = next((item["content"] for item in reversed(normalized_history) if item["role"] == "assistant"), "")
    pending_user_question = str(context.get("pending_user_question") or "")
    pending_clarification = str(context.get("pending_clarification") or "")

    if not last_user_question and pending_user_question:
        last_user_question = pending_user_question
    if not last_assistant_reply and pending_clarification == "agri_domain":
        last_assistant_reply = "你想看虫情还是墒情？"
    if not last_assistant_reply and pending_clarification == "generic_intent":
        last_assistant_reply = "你希望我做数据统计，还是生成处置建议？"

    if not last_user_question:
        return current

    is_domain_follow_up = current in {"虫情", "虫害", "墒情", "低墒", "高墒"} and "虫情还是墒情" in last_assistant_reply
    is_intent_follow_up = current in {"数据统计", "统计", "查数据", "数据", "处置建议", "建议"} and "数据统计" in last_assistant_reply and "处置建议" in last_assistant_reply

    if is_domain_follow_up or is_intent_follow_up:
        # 只在高置信追问模式下拼接，避免把独立新问题误当追问。
        return f"{last_user_question} {current}"
    return current
