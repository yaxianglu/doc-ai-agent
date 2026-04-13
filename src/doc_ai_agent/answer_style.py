from __future__ import annotations


def _ensure_terminal_punctuation(text: str) -> str:
    stripped = str(text or "").strip()
    if not stripped:
        return ""
    if stripped[-1] in "。！？；":
        return stripped
    return f"{stripped}。"


def polish_conclusion_text(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    if text.startswith(("当前判断，", "综合判断，")):
        return _ensure_terminal_punctuation(text)
    return _ensure_terminal_punctuation(f"当前判断，{text}")


def polish_explanation_text(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    if text.startswith(("原因：", "依据：")):
        return text
    if text.startswith(("从数据看，", "结合近几个月变化看，", "综合历史变化看，")):
        return _ensure_terminal_punctuation(text)
    return _ensure_terminal_punctuation(f"从数据看，{text}")


def polish_advice_text(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    if text.startswith(("建议优先", "建议先", "可优先", "可先")):
        return _ensure_terminal_punctuation(text)
    if text.startswith("先"):
        return _ensure_terminal_punctuation(f"建议优先{text}")
    return _ensure_terminal_punctuation(f"建议优先{text}")


def format_answer_section(title: str, content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    prefix = f"{title}："
    return text if text.startswith(prefix) else f"{prefix}{text}"


def compose_analysis_answer(sections: list[str]) -> str:
    normalized: list[str] = []
    for section in sections:
        text = str(section or "").strip()
        if not text or text in normalized:
            continue
        normalized.append(text)
    return "\n\n".join(normalized)
