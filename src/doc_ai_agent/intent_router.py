"""LLM 意图路由封装。

该模块负责把大模型返回的 JSON 路由结果做白名单校验与类型纠正，
确保进入规划层的数据结构稳定、可控。
"""

from __future__ import annotations


class IntentRouter:
    """意图路由器：调用 LLM 并输出受限字段的路由结果。"""

    ALLOWED_INTENTS = {"data_query", "advice"}
    ALLOWED_DOMAINS = {"", "pest", "soil", "mixed"}
    ALLOWED_TASK_TYPES = {
        "unknown",
        "ranking",
        "trend",
        "region_overview",
        "joint_risk",
        "data_detail",
        "compare",
        "cross_domain_compare",
    }
    ALLOWED_WINDOW_TYPES = {"all", "months", "weeks", "days", "year_since"}
    ALLOWED_QUERY_TYPES = {
        "count",
        "active_devices",
        "top",
        "avg_by_level",
        "consecutive_devices",
        "empty_county_records",
        "pest_top",
        "pest_overview",
        "soil_top",
        "soil_overview",
        "pest_trend",
        "soil_trend",
        "joint_risk",
        "structured_agri",
        "latest_device",
        "region_disposal",
        "sms_empty",
        "subtype_ratio",
        "city_day_change",
        "highest_values",
        "threshold_summary",
        "unknown_region_devices",
        "unmatched_region_records",
    }
    ALLOWED_FIELDS = {"city", "county", "alert_type", "alert_level", "region_level"}
    ALLOWED_REGION_LEVELS = {"city", "county"}
    QUERY_TYPE_DOMAIN_HINTS = {
        "pest_top": "pest",
        "pest_overview": "pest",
        "pest_trend": "pest",
        "soil_top": "soil",
        "soil_overview": "soil",
        "soil_trend": "soil",
        "joint_risk": "mixed",
    }
    QUERY_TYPE_TASK_HINTS = {
        "top": "ranking",
        "active_devices": "ranking",
        "consecutive_devices": "ranking",
        "pest_top": "ranking",
        "soil_top": "ranking",
        "city_day_change": "trend",
        "pest_trend": "trend",
        "soil_trend": "trend",
        "joint_risk": "joint_risk",
        "pest_overview": "region_overview",
        "soil_overview": "region_overview",
    }

    def __init__(self, llm_client, model: str):
        """初始化路由器。"""
        self.llm_client = llm_client
        self.model = model

    def route(self, question: str) -> dict:
        """根据问题返回路由结果。

        即使模型输出异常，也会通过白名单和类型兜底返回安全结构。
        """
        system_prompt = (
            "你是意图路由器。请仅输出JSON，字段包含: intent(data_query|advice),"
            "query_type(count|active_devices|top|avg_by_level|consecutive_devices|empty_county_records|pest_top|pest_overview|soil_top|soil_overview|pest_trend|soil_trend|joint_risk|structured_agri|latest_device|region_disposal|sms_empty|subtype_ratio|city_day_change|highest_values|threshold_summary|unknown_region_devices|unmatched_region_records), "
            "field(city|county|alert_type|alert_level|region_level), top_n, min_days, since(YYYY-MM-DD HH:MM:SS), until(YYYY-MM-DD HH:MM:SS|null), "
            "region_level(city|county|null), city, county, device_code, threshold(number|null)。"
            "如果是设备最近一次预警、设备活跃排行、未知区域设备、空字段检查、地区处置建议、阈值统计、短信为空、子类型占比、城市日变化、最高告警值等确定性数据问题，必须返回 intent=data_query。"
            "如果不是数据统计问题，intent=advice。"
        )
        user_prompt = f"问题: {question}"
        data = self.llm_client.complete_json(self.model, system_prompt, user_prompt)
        if not isinstance(data, dict):
            data = {}
        intent = str(data.get("intent", "advice"))
        if intent not in self.ALLOWED_INTENTS:
            intent = "advice"
        query_type = str(data.get("query_type", "count"))
        if query_type not in self.ALLOWED_QUERY_TYPES:
            query_type = "count"
        region_level = str(data.get("region_level") or "")
        if region_level not in self.ALLOWED_REGION_LEVELS:
            region_level = ""

        city = str(data.get("city") or "")
        county = str(data.get("county") or "")
        region_name = str(data.get("region_name") or "")
        if not region_name:
            if region_level == "county" and county:
                region_name = county
            elif city:
                region_name = city
            elif county:
                region_name = county

        domain = str(data.get("domain") or "")
        if domain not in self.ALLOWED_DOMAINS:
            domain = self.QUERY_TYPE_DOMAIN_HINTS.get(query_type, "")
        task_type = str(data.get("task_type") or "")
        if task_type not in self.ALLOWED_TASK_TYPES:
            task_type = self.QUERY_TYPE_TASK_HINTS.get(query_type, "unknown")

        historical_window = self._normalize_window(data.get("historical_window")) or {"window_type": "all", "window_value": None}
        future_window = self._normalize_window(data.get("future_window"))

        result = {
            "intent": intent,
            "domain": domain,
            "task_type": task_type,
            "region_name": region_name,
            "region_level": region_level,
            "historical_window": historical_window,
        }
        if future_window:
            result["future_window"] = future_window
        if intent == "data_query":
            top_n_raw = data.get("top_n", 5)
            try:
                top_n = int(top_n_raw) if top_n_raw is not None else 5
            except (TypeError, ValueError):
                top_n = 5
            min_days_raw = data.get("min_days", 2)
            try:
                min_days = int(min_days_raw) if min_days_raw is not None else 2
            except (TypeError, ValueError):
                min_days = 2
            since = data.get("since") or "1970-01-01 00:00:00"
            field = str(data.get("field", "city"))
            if field not in self.ALLOWED_FIELDS:
                field = "city"
            result.update(
                {
                    "query_type": query_type,
                    "field": field,
                    "top_n": top_n,
                    "min_days": max(2, min_days),
                    "since": str(since),
                }
            )
            until = data.get("until")
            if until not in {None, ""}:
                result["until"] = str(until)
            for key in ("city", "county", "device_code"):
                value = data.get(key)
                if value not in {None, ""}:
                    result[key] = str(value)
            threshold_raw = data.get("threshold")
            if threshold_raw not in {None, ""}:
                try:
                    result["threshold"] = float(threshold_raw)
                except (TypeError, ValueError):
                    pass
        return result

    @classmethod
    def _normalize_window(cls, payload: object) -> dict | None:
        if not isinstance(payload, dict):
            return None
        window_type = str(payload.get("window_type") or "")
        if window_type not in cls.ALLOWED_WINDOW_TYPES:
            return None
        normalized = {
            "window_type": window_type,
            "window_value": payload.get("window_value"),
        }
        horizon_days = payload.get("horizon_days")
        if horizon_days not in {None, ""}:
            try:
                normalized["horizon_days"] = int(horizon_days)
            except (TypeError, ValueError):
                pass
        return normalized
