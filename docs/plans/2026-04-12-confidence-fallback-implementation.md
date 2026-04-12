# Confidence Fallback Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify confidence, source attribution, and fallback reasons into a single `response_meta` envelope so every response mode exposes stable, explainable execution metadata.

**Architecture:** Keep response generation paths unchanged, but centralize metadata synthesis in the agent persistence layer. `response_meta` is derived from planner state plus execution evidence, and the frontend reads the same shape directly so backend logic and UI stay aligned.

**Tech Stack:** Python, `unittest`, TypeScript, React, Vitest, LangGraph.

---

### Task 1: Lock backend metadata behavior with failing tests

**Files:**
- Modify: `tests/test_agent.py`

**Step 1: Add failing assertions**
- No-data historical query emits low confidence and `outside_available_window`
- LLM advice emits `llm` source type and high confidence
- Mixed analysis emits `db / forecast / rag` and no fallback
- Clarification emits planner-driven fallback metadata

**Step 2: Run targeted tests**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent.AgentTests.test_top_query_returns_empty_message_with_available_range_when_no_rows tests.test_agent.AgentTests.test_llm_driven_advice tests.test_agent.AgentGraphTests.test_mixed_historical_forecast_and_rag_request_returns_execution_plan tests.test_agent.AgentGraphTests.test_domain_clarification_for_dataset_question_returns_detail_data`

### Task 2: Centralize backend response metadata

**Files:**
- Modify: `src/doc_ai_agent/agent.py`

**Step 1: Add metadata helpers**
- Normalize confidence values
- Deduplicate source types
- Detect fallback reasons
- Compute per-mode response confidence

**Step 2: Persist canonical metadata**
- Write `evidence["response_meta"]` in `_persist_node`
- Use planner + evidence instead of per-response ad hoc fields

**Step 3: Verify**
Run the same targeted backend tests until green.

### Task 3: Expose metadata in the frontend evidence panel

**Files:**
- Modify: `src/App.integration.test.tsx`
- Modify: `src/components/EvidencePanel.tsx`

**Step 1: Add failing UI assertions**
- Mixed analysis panel shows response confidence
- Mixed analysis panel shows source types
- Mixed analysis panel shows fallback reason

**Step 2: Render metadata**
- Add a `回答元信息` section driven by `evidence.response_meta`

**Step 3: Verify**
Run: `pnpm test -- src/App.integration.test.tsx -t "renders execution plan, forecast, and knowledge sections for a mixed analysis reply"`

### Task 4: Full verification and restart

**Files:**
- No new code unless regressions are found

**Step 1: Backend suite**
Run: `PYTHONPATH=src python3.11 -m unittest tests.test_quality_benchmark tests.test_query_planner tests.test_forecast_service tests.test_agent`

**Step 2: Frontend suite**
Run: `pnpm test`

**Step 3: Restart and smoke-check**
- Restart local services
- Verify `http://127.0.0.1:38117/health`
- Verify `https://ai.luyaxiang.com`
- Smoke a no-data query, a mixed analysis query, and a clarification query
