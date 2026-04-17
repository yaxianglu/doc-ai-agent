"""业务语义口径解析：把自然语言指标映射为标准口径。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SemanticMetric:
    """标准化业务指标口径。"""

    metric: str
    aggregation: str
    ranking_basis: str
    time_scope_mode: str
    geo_scope_mode: str

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "aggregation": self.aggregation,
            "ranking_basis": self.ranking_basis,
            "time_scope_mode": self.time_scope_mode,
            "geo_scope_mode": self.geo_scope_mode,
        }


def _metric_for_question(question: str, domain: str) -> str:
    if any(token in question for token in ["预警", "报警", "告警"]):
        return "alert_count"
    if domain == "soil" or "墒情" in question:
        return "soil_anomaly"
    if domain == "mixed" or ("虫情" in question and "墒情" in question):
        return "joint_risk_score"
    if domain == "pest" or "虫情" in question or "虫害" in question:
        return "pest_severity"
    return ""


def _aggregation_for_question(question: str, task_type: str, answer_form: str, future_window: dict | None) -> str:
    if task_type == "ranking" or answer_form == "rank" or any(token in question for token in ["前5", "前五", "前十", "top", "Top", "最严重", "最重", "最多"]):
        return "top_k"
    if task_type == "trend" or answer_form == "trend" or any(token in question for token in ["趋势", "走势", "走向", "上升", "下降", "增加", "减少"]):
        return "trend"
    if task_type == "data_detail" or answer_form == "detail":
        return "detail"
    if future_window:
        return "forecast"
    if any(token in question for token in ["数量", "多少", "条数"]):
        return "count"
    return "overview"


def _ranking_basis(metric: str, aggregation: str) -> str:
    if aggregation != "top_k":
        return ""
    if metric == "alert_count":
        return "count"
    if metric in {"pest_severity", "soil_anomaly", "joint_risk_score"}:
        return "severity"
    return "value"


def _time_scope_mode(window: dict | None) -> str:
    normalized = dict(window or {})
    window_type = str(normalized.get("window_type") or "")
    if window_type == "year_since":
        return "year_since"
    if window_type in {"days", "weeks", "months"}:
        return "rolling_window"
    return "all_time"


def _geo_scope_mode(question: str, region_name: str, region_level: str) -> str:
    if any(token in question for token in ["哪个县", "哪些县", "哪个区", "哪些区"]):
        return "county_scope"
    if region_level == "county":
        return "specific_county"
    if region_level == "city" and region_name:
        return "specific_city"
    if region_level == "county":
        return "county_scope"
    return "all_regions"


def resolve_semantic_metric(question: str, understanding: dict) -> dict:
    """解析标准业务指标口径。"""

    payload = dict(understanding or {})
    domain = str(payload.get("domain") or "")
    task_type = str(payload.get("task_type") or "")
    answer_form = str(payload.get("answer_form") or "")
    window = payload.get("window") if isinstance(payload.get("window"), dict) else payload.get("historical_window")
    future_window = payload.get("future_window") if isinstance(payload.get("future_window"), dict) else None
    metric = _metric_for_question(question, domain)
    aggregation = _aggregation_for_question(question, task_type, answer_form, future_window)
    semantic_metric = SemanticMetric(
        metric=metric,
        aggregation=aggregation,
        ranking_basis=_ranking_basis(metric, aggregation),
        time_scope_mode=_time_scope_mode(window if isinstance(window, dict) else None),
        geo_scope_mode=_geo_scope_mode(
            question,
            str(payload.get("region_name") or ""),
            str(payload.get("region_level") or ""),
        ),
    )
    return semantic_metric.to_dict()
