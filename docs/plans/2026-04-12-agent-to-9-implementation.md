# Agent To 9 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the Doc AI agent from ~7.8/10 to a stricter 9.0 by improving compare semantics, data-grounded explanations, constraint obedience, and evaluation coverage.

**Architecture:** Keep the current LangGraph graph, but strengthen the layers above it: request understanding, plan semantics, response synthesis, and regression scoring. The highest-value changes are data-grounded explanation synthesis and first-class handling of compare / user-constraint scenarios.

**Tech Stack:** Python, `unittest`, LangGraph, current query engine, current forecast service.

---

### Task 1: Add failing tests for data-grounded explanation

**Files:**
- Modify: `tests/test_agent.py`

**Step 1: Write the failing test**
- Add assertions that “原因解释” includes actual observed metrics like peak value, recent value, or forecast risk when available.

**Step 2: Run test to verify it fails**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent.AgentGraphTests.test_mixed_reasoning_references_observed_metrics`

**Step 3: Write minimal implementation**
- Add a deterministic explanation synthesizer in `src/doc_ai_agent/agent.py` that uses `query_result`, `forecast_result`, and `knowledge`.

**Step 4: Run test to verify it passes**
Run the same targeted test.

### Task 2: Persist user constraints in synthesis path

**Files:**
- Modify: `src/doc_ai_agent/request_understanding.py`
- Modify: `src/doc_ai_agent/agent.py`
- Modify: `tests/test_agent.py`

**Step 1: Add failing test**
- Ensure explicit “不要建议” survives mixed synthesis flows and future follow-ups.

**Step 2: Implement**
- Carry a lightweight constraint flag through understanding and synthesis.

**Step 3: Verify**
- Run the targeted test.

### Task 3: Make compare semantics first-class

**Files:**
- Modify: `src/doc_ai_agent/request_understanding.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/query_plan.py`
- Modify: `src/doc_ai_agent/task_decomposition.py`
- Modify: `tests/test_request_understanding.py`
- Modify: `tests/test_query_planner.py`

**Step 1: Add failing tests**
- Add compare task typing and query-plan assertions.

**Step 2: Implement**
- Promote compare from an ad-hoc agent shortcut into first-class planning metadata.

**Step 3: Verify**
- Run targeted planner / understanding tests.

### Task 4: Add strict evaluation harness notes

**Files:**
- Modify: `docs/reports/` or create new evaluation note

**Step 1: Record the hard scoring rubric**
- correctness
- completeness
- constraint obedience
- multi-turn stability
- evidence quality

### Task 5: Full regression and strict rescore

**Files:**
- No code required unless regressions are found

**Step 1: Run backend suite**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_request_understanding tests.test_query_planner tests.test_agent tests.test_server tests.test_forecast_service`

**Step 2: Spot-check representative dialogues**
- compare
- no-advice
- mixed why+forecast+advice
- follow-up detail inheritance

**Step 3: Re-rate strictly**
- Do not claim 9.0 unless the weak categories are actually closed.

