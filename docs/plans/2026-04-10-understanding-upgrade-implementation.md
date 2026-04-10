# Request Understanding Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade question understanding so overview questions preserve region and intent, while ranking/trend flows continue to work.

**Architecture:** Add an Instructor-backed structured understanding backend, preserve deterministic fallback logic, and teach planner/query engine to handle explicit overview query types. Keep all changes local to the existing Doc AI agent stack so runtime behavior remains observable and testable.

**Tech Stack:** `Instructor`, `openai`, `pydantic`, Python `unittest`, existing `LangGraph`.

---

### Task 1: Add failing understanding regressions

**Files:**
- Modify: `tests/test_request_understanding.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_query_planner.py`

**Step 1: Write the failing tests**

Add tests for:

- overview prompt preserves `徐州市`
- overview prompt produces `task_type=region_overview`
- overview prompt no longer rewrites to “最严重的地方”
- agent returns `pest_overview` for the overview question

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent
PYTHONPATH=src python3.11 -m unittest tests.test_request_understanding tests.test_query_planner tests.test_agent
```

Expected: overview-specific assertions fail.

### Task 2: Add structured understanding backend

**Files:**
- Create: `src/doc_ai_agent/request_understanding_backend.py`
- Modify: `src/doc_ai_agent/request_understanding.py`
- Modify: `src/doc_ai_agent/config.py`
- Modify: `src/doc_ai_agent/server.py`
- Modify: `src/doc_ai_agent/agent.py`
- Modify: `pyproject.toml`

**Step 1: Add typed schema**

Create a pydantic schema for:

- domain
- task_type
- region_name / region_level
- historical_window / future_window
- explanation/advice booleans

**Step 2: Add Instructor backend**

Build an optional backend that:

- uses OpenAI + Instructor when API config is available
- returns `None` on failure
- never blocks deterministic fallback

**Step 3: Wire backend into `RequestUnderstanding`**

Inject the backend through `DocAIAgent` startup so runtime uses the upgraded path automatically.

### Task 3: Preserve semantics in `RequestUnderstanding`

**Files:**
- Modify: `src/doc_ai_agent/request_understanding.py`

**Step 1: Add explicit `task_type` inference**

Implement deterministic fallback for:

- ranking
- trend
- region overview
- joint risk

**Step 2: Stop collapsing overview into ranking**

Update:

- `historical_query_text`
- `normalized_question`

So overview prompts preserve region/overview semantics.

**Step 3: Surface engine metadata**

Return:

- `task_type`
- `understanding_engine`

### Task 4: Teach planner and query engine overview queries

**Files:**
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/query_engine.py`
- Modify: `src/doc_ai_agent/intent_router.py`

**Step 1: Add `pest_overview` and `soil_overview`**

Update planner/query-type allowlists and inference.

**Step 2: Implement overview answers**

Use existing region trend data to summarize:

- latest value
- peak value
- trend direction
- overall condition

**Step 3: Preserve no-data handling**

Overview flows must still emit:

- `available_data_ranges`
- `no_data_reasons`
- `recovery_suggestions`

### Task 5: Verify and restart

**Files:**
- Modify if needed: `src/components/EvidencePanel.tsx`

**Step 1: Run backend tests**

```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent
PYTHONPATH=src python3.11 -m unittest discover -s tests
```

Expected: all tests pass.

**Step 2: Restart local app**

Restart backend and frontend locally and smoke test:

- `GET /health`
- one overview question
- one ranking question

**Step 3: Optional UI follow-up**

If evidence panel needs small visibility support for `task_type`, add it only after backend behavior is verified.
