"""语义解析结果契约。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SemanticParseResult:
    """统一承载语义解析阶段的最小结果。"""

    normalized_query: str = ""
    intent: str = "advice"
    is_out_of_scope: bool = False
    trace: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict | None) -> "SemanticParseResult":
        """从松散字典构造默认安全的语义结果。"""
        raw = dict(payload or {})
        return cls(
            normalized_query=str(raw.get("normalized_query") or ""),
            intent=str(raw.get("intent") or "advice"),
            is_out_of_scope=bool(raw.get("is_out_of_scope")),
            trace=list(raw.get("trace") or []),
        )
