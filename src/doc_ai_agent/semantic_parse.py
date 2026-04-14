"""语义解析结果契约。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SemanticParseResult:
    """统一承载语义解析阶段的最小结果。"""

    normalized_query: str = ""
    intent: str = "advice"
    domain: str = ""
    task_type: str = "unknown"
    region_name: str = ""
    region_level: str = ""
    historical_window: dict = field(default_factory=lambda: {"window_type": "all", "window_value": None})
    future_window: dict | None = None
    followup_type: str = "none"
    needs_clarification: bool = False
    confidence: float = 0.0
    is_out_of_scope: bool = False
    fallback_reason: str = ""
    trace: list[str] = field(default_factory=list)

    @staticmethod
    def _normalize_historical_window(payload: object) -> dict:
        if not isinstance(payload, dict):
            return {"window_type": "all", "window_value": None}
        window_type = str(payload.get("window_type") or "")
        if window_type not in {"all", "months", "weeks", "days", "year_since"}:
            return {"window_type": "all", "window_value": None}
        return {
            "window_type": window_type,
            "window_value": payload.get("window_value"),
        }

    @staticmethod
    def _normalize_future_window(payload: object) -> dict | None:
        if not isinstance(payload, dict):
            return None
        window_type = str(payload.get("window_type") or "")
        if window_type not in {"months", "weeks", "days", "year_since"}:
            return None
        normalized = {
            "window_type": window_type,
            "window_value": payload.get("window_value"),
        }
        if payload.get("horizon_days") not in {None, ""}:
            normalized["horizon_days"] = int(payload["horizon_days"])
        return normalized

    @classmethod
    def from_dict(cls, payload: dict | None) -> "SemanticParseResult":
        """从松散字典构造默认安全的语义结果。"""
        raw = dict(payload or {})
        return cls(
            normalized_query=str(raw.get("normalized_query") or ""),
            intent=str(raw.get("intent") or "advice"),
            domain=str(raw.get("domain") or ""),
            task_type=str(raw.get("task_type") or "unknown"),
            region_name=str(raw.get("region_name") or ""),
            region_level=str(raw.get("region_level") or ""),
            historical_window=cls._normalize_historical_window(raw.get("historical_window")),
            future_window=cls._normalize_future_window(raw.get("future_window")),
            followup_type=str(raw.get("followup_type") or "none"),
            needs_clarification=bool(raw.get("needs_clarification")),
            confidence=float(raw.get("confidence") or 0.0),
            is_out_of_scope=bool(raw.get("is_out_of_scope")),
            fallback_reason=str(raw.get("fallback_reason") or ""),
            trace=list(raw.get("trace") or []),
        )

    def to_dict(self) -> dict:
        """导出为可序列化字典，便于兼容旧链路渐进接入。"""
        return {
            "normalized_query": self.normalized_query,
            "intent": self.intent,
            "domain": self.domain,
            "task_type": self.task_type,
            "region_name": self.region_name,
            "region_level": self.region_level,
            "historical_window": dict(self.historical_window),
            "future_window": dict(self.future_window) if isinstance(self.future_window, dict) else None,
            "followup_type": self.followup_type,
            "needs_clarification": self.needs_clarification,
            "confidence": self.confidence,
            "is_out_of_scope": self.is_out_of_scope,
            "fallback_reason": self.fallback_reason,
            "trace": list(self.trace),
        }
