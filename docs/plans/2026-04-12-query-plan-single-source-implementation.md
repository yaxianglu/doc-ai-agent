# Query Plan Single Source Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `query_plan` the single source of truth for execution so downstream query, forecast, and memory code derive runtime routes from the plan instead of ad-hoc `route` copies.

**Architecture:** Keep the existing planner and LangGraph graph, but promote `query_plan.execution.route` into the canonical execution payload. The legacy top-level `plan["route"]` remains as a compatibility mirror derived from `query_plan`, while agent runtime code reads the canonical execution route first and only falls back to the legacy field when needed.

**Tech Stack:** Python, `unittest`, LangGraph, current query planner/query engine/forecast service stack.

---

### Task 1: Lock single-source semantics with failing tests

**Files:**
- Modify: `tests/test_query_planner.py`
- Modify: `tests/test_agent.py`

**Step 1: Write the failing test**
- Assert planner output includes `query_plan.execution.route`
- Assert top-level `plan["route"]` mirrors `query_plan.execution.route`
- Assert the agent prefers `query_plan.execution.route` over a stale legacy `plan["route"]`

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_planner.QueryPlannerTests.test_query_plan_execution_route_is_single_source tests.test_agent.AgentGraphTests.test_agent_prefers_query_plan_execution_route_over_legacy_route`

**Step 3: Write minimal implementation**
- Add query-plan helpers for reading/updating canonical execution routes
- Rewire planner/agent to derive runtime routes from query-plan execution data

**Step 4: Run test to verify it passes**
Run the same targeted command.

### Task 2: Promote execution route into Query Plan

**Files:**
- Modify: `src/doc_ai_agent/query_plan.py`
- Modify: `src/doc_ai_agent/query_planner.py`

**Step 1: Add execution payload**
- Store normalized execution data under `query_plan["execution"]`
- Keep route-compatible fields: `query_type`, `since`, `until`, region scope, `top_n`, forecast fields

**Step 2: Mirror top-level route from query plan**
- After building `query_plan`, regenerate `plan["route"]` from `query_plan.execution.route`
- Ensure explicit `top_n` overrides patch `query_plan` first, then regenerate the mirror route

**Step 3: Verify**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_planner`

### Task 3: Rewire runtime execution to canonical plan route

**Files:**
- Modify: `src/doc_ai_agent/agent.py`

**Step 1: Add a canonical route helper**
- Resolve route from `query_plan.execution.route` first
- Fall back to legacy `plan["route"]` only if needed

**Step 2: Replace runtime consumers**
- Query execution
- Forecast resolution
- Runtime context building
- Memory snapshot persistence
- Compare-request route seeding

**Step 3: Verify**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent tests.test_query_planner tests.test_forecast_service`

### Task 4: Full regression and deployment verification

**Files:**
- No additional code unless regressions appear

**Step 1: Run backend regression suite**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_quality_benchmark tests.test_query_planner tests.test_forecast_service tests.test_agent`

**Step 2: Run frontend integration**
Run: `npm run test -- --run src/App.integration.test.tsx`

**Step 3: Restart and smoke-check**
- Restart local stack
- Verify local `/health`
- Verify `https://ai.luyaxiang.com/api/chat` still returns upgraded forecast/ranking behavior
