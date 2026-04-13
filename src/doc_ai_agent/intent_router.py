from __future__ import annotations


class IntentRouter:
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

    def __init__(self, llm_client, model: str):
        self.llm_client = llm_client
        self.model = model

    def route(self, question: str) -> dict:
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
        intent = str(data.get("intent", "advice"))
        if intent not in {"data_query", "advice"}:
            intent = "advice"
        result = {"intent": intent}
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
            query_type = str(data.get("query_type", "count"))
            if query_type not in self.ALLOWED_QUERY_TYPES:
                query_type = "count"
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
            region_level = str(data.get("region_level") or "")
            if region_level in self.ALLOWED_REGION_LEVELS:
                result["region_level"] = region_level
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
