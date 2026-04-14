"""回答文案轻量润色工具。

用于统一结论、解释、建议等段落的语气和格式，
不改变业务语义，仅做可读性增强。
"""

from __future__ import annotations


def _ensure_terminal_punctuation(text: str) -> str:
    """确保文本以中文句末标点结尾。"""
    stripped = str(text or "").strip()
    if not stripped:
        return ""
    if stripped[-1] in "。！？；":
        return stripped
    return f"{stripped}。"


def polish_conclusion_text(content: str) -> str:
    """统一结论段的开头话术与句末标点。"""
    text = str(content or "").strip()
    if not text:
        return ""
    if text.startswith(("当前判断，", "综合判断，")):
        return _ensure_terminal_punctuation(text)
    return _ensure_terminal_punctuation(f"当前判断，{text}")


def polish_explanation_text(content: str) -> str:
    """统一解释段的引导语。"""
    text = str(content or "").strip()
    if not text:
        return ""
    if text.startswith(("原因：", "依据：")):
        return text
    if text.startswith(("从数据看，", "结合近几个月变化看，", "综合历史变化看，")):
        return _ensure_terminal_punctuation(text)
    return _ensure_terminal_punctuation(f"从数据看，{text}")


def polish_advice_text(content: str) -> str:
    """统一建议段语气，默认采用“建议优先…”表达。"""
    text = str(content or "").strip()
    if not text:
        return ""
    if text.startswith(("建议优先", "建议先", "可优先", "可先")):
        return _ensure_terminal_punctuation(text)
    if text.startswith("先"):
        return _ensure_terminal_punctuation(f"建议优先{text}")
    return _ensure_terminal_punctuation(f"建议优先{text}")


def format_answer_section(title: str, content: str) -> str:
    """为段落补齐“标题：内容”格式。"""
    text = str(content or "").strip()
    if not text:
        return ""
    prefix = f"{title}："
    return text if text.startswith(prefix) else f"{prefix}{text}"


def compose_analysis_answer(sections: list[str]) -> str:
    """拼接多段回答，自动去重并保留原有顺序。"""
    normalized: list[str] = []
    for section in sections:
        text = str(section or "").strip()
        if not text or text in normalized:
            continue
        normalized.append(text)
    return "\n\n".join(normalized)
