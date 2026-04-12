# Task Decomposition Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Promote complex-question decomposition into a first-class planning artifact so mixed requests are represented as explicit tasks, dependencies, execution stages, and a merge strategy.

**Architecture:** Keep the existing LangGraph execution graph, but move decomposition ownership into `query_plan.decomposition`. The planner emits a canonical task graph, the agent derives `execution_plan` from it, and responses expose the richer decomposition so the system is testable and explainable without relying on scattered heuristics.

**Tech Stack:** Python, `unittest`, LangGraph, current query planner / task decomposition / synthesis pipeline.

---

### Task 1: Lock decomposition behavior with failing tests

**Files:**
- Modify: `tests/test_query_planner.py`
- Modify: `tests/test_agent.py`

**Step 1: Write the failing tests**
- Assert mixed requests populate `query_plan.decomposition.tasks`
- Assert decomposition carries `execution_plan`
- Assert mixed responses expose `merge_strategy` and stage-level task metadata

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_planner.QueryPlannerTests.test_query_plan_marks_mixed_analysis_needs tests.test_agent.AgentGraphTests.test_mixed_historical_forecast_and_rag_request_returns_execution_plan`

**Step 3: Write minimal implementation**
- Enrich `task_decomposition.py`
- Wire planner and agent to use decomposition as the source for execution metadata

**Step 4: Run test to verify it passes**
Run the same targeted command.

### Task 2: Enrich decomposition output

**Files:**
- Modify: `src/doc_ai_agent/task_decomposition.py`

**Step 1: Add task metadata**
- `title`
- `stage`
- `output_key`
- `parallel_group`

**Step 2: Add plan-level metadata**
- `execution_plan`
- `merge_strategy`
- keep backward-compatible `tasks`

**Step 3: Verify**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_planner`

### Task 3: Make agent consume decomposition

**Files:**
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/agent.py`

**Step 1: Planner embeds decomposition**
- Store decomposition under `query_plan["decomposition"]`

**Step 2: Agent derives execution metadata from decomposition**
- Prefer `query_plan.decomposition.execution_plan`
- Expose decomposition in evidence
- Keep top-level `plan["task_graph"]` as a compatibility alias

**Step 3: Verify**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent tests.test_query_planner tests.test_forecast_service`

### Task 4: Full verification and redeploy

**Files:**
- No new code unless regressions are found

**Step 1: Backend suite**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_quality_benchmark tests.test_query_planner tests.test_forecast_service tests.test_agent`

**Step 2: Frontend integration**
Run: `npm run test -- --run src/App.integration.test.tsx`

**Step 3: Restart and smoke-check**
- Restart local services
- Verify `/health`
- Verify public `ai.luyaxiang.com` answers still reflect the upgraded mixed-analysis behavior
