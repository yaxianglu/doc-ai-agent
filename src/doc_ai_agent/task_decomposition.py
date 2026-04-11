from __future__ import annotations


def _primary_task_type(query_plan: dict) -> str | None:
    slots = dict(query_plan.get("slots") or {})
    aggregation = str(slots.get("aggregation") or "")

    if aggregation == "top_k":
        return "historical_rank"
    if aggregation == "detail":
        return "historical_detail"
    if aggregation == "overview":
        return "historical_overview"
    if aggregation == "trend":
        return "trend_analysis"
    if aggregation == "forecast":
        return "forecast"
    return None


def build_task_graph(query_plan: dict) -> dict:
    normalized_plan = dict(query_plan or {})
    slots = dict(normalized_plan.get("slots") or {})
    goal = str(normalized_plan.get("goal") or "")
    intent = str(normalized_plan.get("intent") or "")

    tasks: list[dict] = []

    def add_task(task_type: str, depends_on: list[str] | None = None) -> str:
        task_id = f"t{len(tasks) + 1}"
        tasks.append(
            {
                "id": task_id,
                "type": task_type,
                "depends_on": list(depends_on or []),
            }
        )
        return task_id

    if goal == "conversation" and intent == "greeting":
        return {
            "version": "v1",
            "plan_goal": goal,
            "tasks": [],
        }

    primary_task_id = None
    primary_task_type = _primary_task_type(normalized_plan)
    if primary_task_type:
        primary_task_id = add_task(primary_task_type)

    if intent == "clarification":
        clarification_id = add_task("clarification", [primary_task_id] if primary_task_id else [])
        add_task("merge_answer", [clarification_id])
        return {
            "version": "v1",
            "plan_goal": goal or "agri_analysis",
            "tasks": tasks,
        }

    if bool(slots.get("need_explanation")):
        add_task("cause_retrieval", [primary_task_id] if primary_task_id else [])

    forecast_task_id = primary_task_id if primary_task_type == "forecast" else None
    if bool(slots.get("need_forecast")) and primary_task_type != "forecast":
        forecast_task_id = add_task("forecast", [primary_task_id] if primary_task_id else [])

    if bool(slots.get("need_advice")):
        advice_dependencies = [task["id"] for task in tasks if task["type"] in {"historical_rank", "historical_detail", "historical_overview", "trend_analysis", "forecast"}]
        if not advice_dependencies and primary_task_id:
            advice_dependencies = [primary_task_id]
        if forecast_task_id and forecast_task_id not in advice_dependencies:
            advice_dependencies.append(forecast_task_id)
        add_task("advice_retrieval", advice_dependencies)

    merge_dependencies = [task["id"] for task in tasks]
    if not merge_dependencies:
        merge_dependencies = [add_task("clarification")]
    add_task("merge_answer", merge_dependencies)

    return {
        "version": "v1",
        "plan_goal": goal or "agri_analysis",
        "tasks": tasks,
    }
