from __future__ import annotations


def _task_stage(task_type: str) -> str:
    if task_type in {"historical_rank", "historical_detail", "historical_overview", "trend_analysis", "comparison_analysis"}:
        return "historical_query"
    if task_type == "forecast":
        return "forecast"
    if task_type in {"cause_retrieval", "advice_retrieval"}:
        return "knowledge_retrieval"
    if task_type in {"clarification", "merge_answer"}:
        return "answer_synthesis"
    return "answer_synthesis"


def _task_title(task_type: str) -> str:
    return {
        "historical_rank": "查询历史排行",
        "historical_detail": "查询历史明细",
        "historical_overview": "查询历史概况",
        "trend_analysis": "查询历史趋势",
        "comparison_analysis": "执行对比分析",
        "forecast": "执行未来预测",
        "cause_retrieval": "检索原因依据",
        "advice_retrieval": "检索处置建议",
        "clarification": "生成澄清问题",
        "merge_answer": "汇总生成答案",
    }.get(task_type, task_type)


def _task_output(task_type: str) -> str:
    return {
        "historical_rank": "historical",
        "historical_detail": "historical",
        "historical_overview": "historical",
        "trend_analysis": "historical",
        "comparison_analysis": "historical",
        "forecast": "forecast",
        "cause_retrieval": "knowledge",
        "advice_retrieval": "knowledge",
        "clarification": "answer",
        "merge_answer": "answer",
    }.get(task_type, "answer")


def _primary_task_type(query_plan: dict) -> str | None:
    slots = dict(query_plan.get("slots") or {})
    aggregation = str(slots.get("aggregation") or "")

    if aggregation == "top_k":
        return "historical_rank"
    if aggregation == "compare":
        return "comparison_analysis"
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

    def add_task(task_type: str, depends_on: list[str] | None = None, parallel_group: str = "") -> str:
        task_id = f"t{len(tasks) + 1}"
        tasks.append(
            {
                "id": task_id,
                "type": task_type,
                "title": _task_title(task_type),
                "stage": _task_stage(task_type),
                "output_key": _task_output(task_type),
                "parallel_group": parallel_group,
                "depends_on": list(depends_on or []),
            }
        )
        return task_id

    if goal == "conversation" and intent == "greeting":
        return {
            "version": "v2",
            "plan_goal": goal,
            "execution_plan": ["understand_request", "answer_synthesis"],
            "merge_strategy": "direct_answer",
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
            "version": "v2",
            "plan_goal": goal or "agri_analysis",
            "execution_plan": ["understand_request", "answer_synthesis"],
            "merge_strategy": "clarification_only",
            "tasks": tasks,
        }

    if bool(slots.get("need_explanation")):
        add_task("cause_retrieval", [primary_task_id] if primary_task_id else [], parallel_group="analysis_followups")

    forecast_task_id = primary_task_id if primary_task_type == "forecast" else None
    if bool(slots.get("need_forecast")) and primary_task_type != "forecast":
        forecast_task_id = add_task("forecast", [primary_task_id] if primary_task_id else [], parallel_group="analysis_followups")

    if bool(slots.get("need_advice")):
        advice_dependencies = [task["id"] for task in tasks if task["type"] in {"historical_rank", "historical_detail", "historical_overview", "trend_analysis", "forecast"}]
        if not advice_dependencies and primary_task_id:
            advice_dependencies = [primary_task_id]
        if forecast_task_id and forecast_task_id not in advice_dependencies:
            advice_dependencies.append(forecast_task_id)
        add_task("advice_retrieval", advice_dependencies, parallel_group="analysis_followups")

    merge_dependencies = [task["id"] for task in tasks]
    if not merge_dependencies:
        merge_dependencies = [add_task("clarification")]
    merge_id = add_task("merge_answer", merge_dependencies)

    execution_plan = ["understand_request"]
    task_stages = [str(task.get("stage") or "") for task in tasks]
    for stage in ["historical_query", "forecast", "knowledge_retrieval", "answer_synthesis"]:
        if stage in task_stages and stage not in execution_plan:
            execution_plan.append(stage)

    return {
        "version": "v2",
        "plan_goal": goal or "agri_analysis",
        "execution_plan": execution_plan,
        "merge_strategy": "sectioned_answer" if merge_id else "direct_answer",
        "tasks": tasks,
    }
