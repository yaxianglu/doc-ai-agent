"""受限规划元数据：为现有计划附加固定模板与约束信息。"""

from __future__ import annotations

from .planner_templates import infer_plan_type, normalize_task_template


def _missing_slots(required_slots: list[str], *, route: dict, domain: str, historical_window: dict | None, future_window: dict | None) -> list[str]:
    missing: list[str] = []
    normalized_route = dict(route or {})
    normalized_historical = dict(historical_window or {})
    normalized_future = dict(future_window or {}) if isinstance(future_window, dict) else None
    for slot in required_slots:
        if slot == "domain" and not str(domain or ""):
            missing.append(slot)
        elif slot == "historical_window" and str(normalized_historical.get("window_type") or "all") in {"", "all", "none"}:
            missing.append(slot)
        elif slot == "future_window" and not normalized_future:
            missing.append(slot)
        elif slot == "region" and not any(normalized_route.get(key) for key in ("city", "county")):
            missing.append(slot)
    return missing


def build_restricted_task_graph(task_dsl: dict | None, *, plan_type: str) -> dict:
    """把现有 task_dsl 转为更显式的 restricted task graph。"""

    payload = dict(task_dsl or {})
    tasks = []
    for item in payload.get("templates") or []:
        task = dict(item or {})
        tasks.append(
            {
                "id": str(task.get("id") or ""),
                "template": normalize_task_template(str(task.get("template") or "")),
                "stage": str(task.get("stage") or ""),
                "depends_on": list(task.get("depends_on") or []),
                "output_key": str(task.get("output_key") or ""),
            }
        )
    return {
        "version": "v1",
        "plan_type": plan_type,
        "tasks": tasks,
        "execution_plan": list(payload.get("execution_plan") or []),
    }


def build_restricted_plan_metadata(
    *,
    intent: str,
    route: dict,
    answer_mode: str,
    needs_clarification: bool,
    needs_explanation: bool,
    needs_advice: bool,
    needs_forecast: bool,
    domain: str,
    historical_window: dict | None,
    future_window: dict | None,
    task_dsl: dict | None,
    enabled_capabilities: list[str] | tuple[str, ...] | None,
) -> dict:
    """生成受限规划元数据，不改写现有主计划结构。"""

    decision = infer_plan_type(
        intent=intent,
        route=route,
        answer_mode=answer_mode,
        needs_clarification=needs_clarification,
        needs_explanation=needs_explanation,
        needs_advice=needs_advice,
        needs_forecast=needs_forecast,
    )
    required_slots = list(decision.required_slots)
    return {
        "plan_type": decision.plan_type,
        "planner_template": decision.plan_type,
        "required_slots": required_slots,
        "missing_slots": _missing_slots(
            required_slots,
            route=route,
            domain=domain,
            historical_window=historical_window,
            future_window=future_window,
        ),
        "enabled_capabilities": list(enabled_capabilities or []),
        "restricted_task_graph": build_restricted_task_graph(task_dsl, plan_type=decision.plan_type),
    }
