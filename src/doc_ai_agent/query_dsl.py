"""统一查询 DSL：为解析层、路由层和规划层提供稳定中间表示。"""

from __future__ import annotations

from dataclasses import dataclass, field

ANSWER_FORMS = {"unknown", "boolean", "trend", "rank", "detail", "explanation", "advice", "composite"}


@dataclass(frozen=True)
class QueryRegion:
    """地区槽位。"""

    name: str = ""
    level: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "level": self.level}

    @classmethod
    def from_dict(cls, payload: dict | None) -> "QueryRegion":
        raw = dict(payload or {})
        return cls(name=str(raw.get("name") or ""), level=str(raw.get("level") or ""))


@dataclass(frozen=True)
class QueryWindow:
    """统一的时间窗表示。"""

    kind: str = "history"
    window_type: str = "all"
    window_value: int | None = None
    horizon_days: int | None = None

    def to_dict(self) -> dict:
        payload = {
            "kind": self.kind,
            "window_type": self.window_type,
            "window_value": self.window_value,
        }
        if self.horizon_days not in {None, 0}:
            payload["horizon_days"] = self.horizon_days
        return payload

    @classmethod
    def from_dict(cls, payload: dict | None, *, kind: str = "history") -> "QueryWindow":
        raw = dict(payload or {})
        horizon_days = raw.get("horizon_days")
        parsed_horizon = None
        if horizon_days not in {None, ""}:
            try:
                parsed_horizon = int(horizon_days)
            except (TypeError, ValueError):
                parsed_horizon = None
        window_value = raw.get("window_value")
        try:
            parsed_window_value = int(window_value) if window_value not in {None, ""} else None
        except (TypeError, ValueError):
            parsed_window_value = None
        return cls(
            kind=str(raw.get("kind") or kind),
            window_type=str(raw.get("window_type") or "all"),
            window_value=parsed_window_value,
            horizon_days=parsed_horizon,
        )


@dataclass(frozen=True)
class QueryDSL:
    """解析层产出的统一查询 DSL。"""

    domain: str = ""
    intent: tuple[str, ...] = field(default_factory=tuple)
    task_type: str = "unknown"
    answer_form: str = "unknown"
    region: QueryRegion = field(default_factory=QueryRegion)
    historical_window: QueryWindow = field(default_factory=QueryWindow)
    future_window: QueryWindow | None = None
    follow_up: bool = False
    followup_type: str = "none"
    needs_clarification: bool = False
    capabilities: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    original_question: str = ""
    resolved_question: str = ""

    def to_dict(self) -> dict:
        payload = {
            "domain": self.domain,
            "intent": list(self.intent),
            "task_type": self.task_type,
            "answer_form": self.answer_form,
            "region": self.region.to_dict(),
            "historical_window": self.historical_window.to_dict(),
            "follow_up": self.follow_up,
            "followup_type": self.followup_type,
            "needs_clarification": self.needs_clarification,
            "capabilities": list(self.capabilities),
            "confidence": self.confidence,
            "original_question": self.original_question,
            "resolved_question": self.resolved_question,
        }
        if self.future_window is not None:
            payload["future_window"] = self.future_window.to_dict()
        return payload

    @classmethod
    def from_dict(cls, payload: dict | None) -> "QueryDSL":
        raw = dict(payload or {})
        future_window = raw.get("future_window")
        return cls(
            domain=str(raw.get("domain") or ""),
            intent=tuple(str(item) for item in raw.get("intent") or [] if str(item or "")),
            task_type=str(raw.get("task_type") or "unknown"),
            answer_form=normalize_answer_form(raw.get("answer_form")),
            region=QueryRegion.from_dict(raw.get("region")),
            historical_window=QueryWindow.from_dict(raw.get("historical_window"), kind="history"),
            future_window=QueryWindow.from_dict(future_window, kind="future") if isinstance(future_window, dict) else None,
            follow_up=bool(raw.get("follow_up")),
            followup_type=str(raw.get("followup_type") or "none"),
            needs_clarification=bool(raw.get("needs_clarification")),
            capabilities=tuple(str(item) for item in raw.get("capabilities") or [] if str(item or "")),
            confidence=float(raw.get("confidence") or 0.0),
            original_question=str(raw.get("original_question") or ""),
            resolved_question=str(raw.get("resolved_question") or ""),
        )


def normalize_answer_form(value: object) -> str:
    """标准化答案形态，避免自由字符串进入规划层。"""

    normalized = str(value or "").strip()
    return normalized if normalized in ANSWER_FORMS else "unknown"


def infer_answer_form(
    question: str,
    *,
    task_type: str = "",
    needs_explanation: bool = False,
    needs_advice: bool = False,
    needs_forecast: bool = False,
) -> str:
    """从问题和旧语义字段推导回答形态。"""

    normalized = str(question or "")
    if (
        (needs_explanation and needs_advice)
        or ("先" in normalized and "再" in normalized and any(token in normalized for token in ["建议", "解释", "原因"]))
        or ("解释" in normalized and "建议" in normalized)
    ):
        return "composite"
    if any(token in normalized for token in ["上升还是下降", "增加还是减少", "减少还是增加", "下降还是上升", "趋势", "走势", "走向", "有没有缓解"]):
        return "trend"
    if any(token in normalized for token in ["是否", "会不会", "能否", "可不可以", "有没有"]) or normalized.endswith(("吗", "吗？", "吗?")):
        return "boolean"
    if task_type == "trend":
        return "trend"
    if task_type == "ranking":
        return "rank"
    if task_type == "data_detail":
        return "detail"
    if needs_explanation:
        return "explanation"
    if needs_advice:
        return "advice"
    if needs_forecast:
        return "trend"
    return "unknown"


def capabilities_from_semantics(*, intent: str, task_type: str, needs_forecast: bool, needs_explanation: bool, needs_advice: bool) -> tuple[str, ...]:
    """把旧语义字段映射到新的 capability 列表。"""

    capabilities: list[str] = []
    if intent == "data_query":
        capabilities.append("data_query")
    if task_type in {"joint_risk", "compare", "cross_domain_compare"} and "reasoning" not in capabilities:
        capabilities.append("reasoning")
    if needs_forecast:
        capabilities.append("forecast")
    if needs_explanation and "reasoning" not in capabilities:
        capabilities.append("reasoning")
    if needs_advice:
        capabilities.append("advice")
    if intent == "advice" and not capabilities:
        capabilities.append("advice")
    return tuple(capabilities)


def query_dsl_from_understanding(understanding: dict | None) -> QueryDSL:
    """把当前请求理解结果映射成统一 QueryDSL。"""

    raw = dict(understanding or {})
    intent = str(raw.get("intent") or "advice")
    needs_forecast = bool(raw.get("needs_forecast"))
    needs_explanation = bool(raw.get("needs_explanation"))
    needs_advice = bool(raw.get("needs_advice"))
    followup_type = str(raw.get("followup_type") or "none")
    answer_form = normalize_answer_form(raw.get("answer_form"))
    if answer_form == "unknown":
        answer_form = infer_answer_form(
            str(raw.get("resolved_question") or raw.get("original_question") or ""),
            task_type=str(raw.get("task_type") or "unknown"),
            needs_forecast=needs_forecast,
            needs_explanation=needs_explanation,
            needs_advice=needs_advice,
        )
    return QueryDSL(
        domain=str(raw.get("domain") or ""),
        intent=(intent,),
        task_type=str(raw.get("task_type") or "unknown"),
        answer_form=answer_form,
        region=QueryRegion(
            name=str(raw.get("region_name") or ""),
            level=str(raw.get("region_level") or ""),
        ),
        historical_window=QueryWindow.from_dict(raw.get("window"), kind="history"),
        future_window=QueryWindow.from_dict(raw.get("future_window"), kind="future") if isinstance(raw.get("future_window"), dict) else None,
        follow_up=followup_type != "none" or bool(raw.get("used_context")),
        followup_type=followup_type,
        needs_clarification=bool(raw.get("needs_clarification")),
        capabilities=capabilities_from_semantics(
            intent=intent,
            task_type=str(raw.get("task_type") or "unknown"),
            needs_forecast=needs_forecast,
            needs_explanation=needs_explanation,
            needs_advice=needs_advice,
        ),
        confidence=float(raw.get("confidence") or 0.0),
        original_question=str(raw.get("original_question") or ""),
        resolved_question=str(raw.get("resolved_question") or ""),
    )
