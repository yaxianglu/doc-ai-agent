"""轻量任务 DSL：约束规划层只输出固定模板任务。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskSpec:
    """单个任务模板。"""

    id: str
    template: str
    stage: str
    depends_on: tuple[str, ...] = field(default_factory=tuple)
    output_key: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "template": self.template,
            "stage": self.stage,
            "depends_on": list(self.depends_on),
            "output_key": self.output_key,
        }


@dataclass(frozen=True)
class TaskDSL:
    """规划层输出的固定任务 DSL。"""

    version: str
    plan_goal: str
    templates: tuple[TaskSpec, ...]
    execution_plan: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "plan_goal": self.plan_goal,
            "templates": [item.to_dict() for item in self.templates],
            "execution_plan": list(self.execution_plan),
        }


TASK_TEMPLATE_MAP = {
    "historical_rank": "rank",
    "historical_detail": "detail",
    "historical_overview": "overview",
    "trend_analysis": "trend",
    "comparison_analysis": "compare",
    "forecast": "forecast",
    "cause_retrieval": "reason",
    "advice_retrieval": "advice",
    "clarification": "clarify",
    "merge_answer": "merge",
}


def task_dsl_from_task_graph(query_plan: dict | None, task_graph: dict | None) -> TaskDSL:
    """把现有 task_graph 压缩为模板化 Task DSL。"""

    graph = dict(task_graph or {})
    tasks = []
    for item in graph.get("tasks") or []:
        task = dict(item or {})
        tasks.append(
            TaskSpec(
                id=str(task.get("id") or ""),
                template=TASK_TEMPLATE_MAP.get(str(task.get("type") or ""), str(task.get("type") or "")),
                stage=str(task.get("stage") or ""),
                depends_on=tuple(str(dep) for dep in task.get("depends_on") or [] if str(dep or "")),
                output_key=str(task.get("output_key") or ""),
            )
        )
    return TaskDSL(
        version="v1",
        plan_goal=str(graph.get("plan_goal") or (query_plan or {}).get("goal") or "agri_analysis"),
        templates=tuple(tasks),
        execution_plan=tuple(str(item) for item in graph.get("execution_plan") or [] if str(item or "")),
    )
