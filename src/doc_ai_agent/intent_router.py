from __future__ import annotations


class IntentRouter:
    def __init__(self, llm_client, model: str):
        self.llm_client = llm_client
        self.model = model

    def route(self, question: str) -> dict:
        system_prompt = (
            "你是意图路由器。请仅输出JSON，字段包含: intent(data_query|advice),"
            "query_type(count|top|avg_by_level|consecutive_devices), field(city|county|alert_type|alert_level), top_n, min_days, since(YYYY-MM-DD HH:MM:SS)。"
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
            result.update(
                {
                    "query_type": str(data.get("query_type", "count")),
                    "field": str(data.get("field", "city")),
                    "top_n": top_n,
                    "min_days": max(2, min_days),
                    "since": str(since),
                }
            )
        return result
