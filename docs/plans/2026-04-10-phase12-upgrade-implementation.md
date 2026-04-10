# doc-cloud Phase 1 and 2 Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade the current agent into a robust multi-turn agricultural data agent with LangGraph orchestration, Letta-compatible memory, prediction, and context-aware advice.

**Architecture:** Keep the existing HTTP + frontend interface and add a LangGraph execution graph plus a Letta/local-memory adapter. The planner resolves context from `history + thread memory`, the graph routes to query/forecast/advice/clarify nodes, and the advice layer consumes structured analysis context instead of only raw user text.

**Tech Stack:** Python, unittest, LangGraph, Letta client, existing repository/query abstractions, React frontend (minimal changes only if needed)

---

### Task 1: Add failing tests for thread memory and richer follow-ups
- Files: `tests/test_query_planner.py`, `tests/test_agent.py`, `tests/test_server.py`
- Cover:
  - thread_id follow-up without explicit history
  - forecast follow-up (`未来两周呢`)
  - advice follow-up (`给建议`)
  - context trace / processing labels (`LangGraph`, memory backend)

### Task 2: Add failing tests for memory adapters
- Files: `tests/test_memory_store.py`
- Add:
  - Local memory round-trip
  - Letta block-backed round-trip

### Task 3: Implement Letta/local memory adapter
- Files:
  - Create `src/doc_ai_agent/letta_memory.py`
  - Modify `src/doc_ai_agent/config.py`
- Add LocalMemoryStore, LettaMemoryStore, resilient fallback behavior, and env/config plumbing.

### Task 4: Implement LangGraph orchestration
- Files:
  - Modify `src/doc_ai_agent/agent.py`
  - Modify `src/doc_ai_agent/query_planner.py`
- Add `load_memory -> plan -> query/forecast/advice/clarify -> persist_memory` graph and thread-aware follow-up resolution.

### Task 5: Implement forecast and context-aware advice
- Files:
  - Create `src/doc_ai_agent/forecast_engine.py`
  - Modify `src/doc_ai_agent/advice_engine.py`
  - Modify `src/doc_ai_agent/agent.py`
- Feed analysis context, forecast summary, and sources into advice generation.

### Task 6: Thread `thread_id` through frontend and render processing metadata
- Files:
  - Modify `doc-frontend/src/services/chatApi.ts`
  - Modify `doc-frontend/src/hooks/useChatActions.ts`
  - Modify `doc-frontend/src/types/chat.ts`
  - Modify `doc-frontend/src/components/EvidencePanel.tsx`
  - Modify related frontend tests

### Task 7: Verify end-to-end behavior
- Run targeted tests, then broader backend/frontend tests and frontend build.
