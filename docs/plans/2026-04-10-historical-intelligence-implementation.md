# Historical Intelligence Upgrade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade doc-cloud into a historical-intelligence agent with structured request understanding, data-first historical analysis, RAG-backed explanation/advice, and a dedicated forecast service.

**Architecture:** Keep the current HTTP and chat UI surface, but insert a richer LangGraph pipeline that produces an execution plan, runs historical data retrieval and forecast as separate stages, retrieves agricultural knowledge through a RAG-style retriever, and synthesizes the answer with transparent evidence.

**Tech Stack:** Python, unittest, LangGraph, Letta-compatible memory, deterministic retrieval/ranking, React, Vitest

---

### Task 1: Add failing tests for request understanding
- Files:
  - `tests/test_request_understanding.py`
  - `tests/test_agent.py`
- Cover:
  - noisy long-form user input is normalized into a clean executable request
  - mixed questions generate multi-step execution plans
  - filler/meta phrases do not hijack intent

### Task 2: Add failing tests for knowledge retrieval
- Files:
  - `tests/test_source_provider.py`
  - `tests/test_agent.py`
- Cover:
  - retrieval for “为什么/怎么处置”
  - domain-aware ranking
  - matched terms and source snippets in evidence

### Task 3: Add failing tests for forecast service
- Files:
  - `tests/test_forecast_service.py`
  - `tests/test_agent.py`
- Cover:
  - region forecast
  - top-risk forecast ranking
  - forecast evidence structure

### Task 4: Implement request understanding
- Files:
  - Create `src/doc_ai_agent/request_understanding.py`
  - Modify `src/doc_ai_agent/query_planner.py`
  - Modify `src/doc_ai_agent/agent.py`
- Add:
  - noise filtering
  - actionable slot extraction
  - execution plan generation

### Task 5: Implement knowledge layer / RAG retriever
- Files:
  - Modify `src/doc_ai_agent/source_provider.py`
  - Modify `src/doc_ai_agent/advice_engine.py`
  - Modify `src/doc_ai_agent/agent.py`
- Add:
  - chunk/keyword retrieval
  - domain-aware ranking
  - evidence payload for retrieved sources

### Task 6: Implement forecast service
- Files:
  - Create `src/doc_ai_agent/forecast_service.py`
  - Modify `src/doc_ai_agent/forecast_engine.py`
  - Modify `src/doc_ai_agent/agent.py`
- Add:
  - per-region forecast
  - top-risk forecast ranking
  - service-level evidence model

### Task 7: Upgrade LangGraph pipeline
- Files:
  - Modify `src/doc_ai_agent/agent.py`
- Add nodes for:
  - request understanding
  - historical query
  - forecast
  - knowledge retrieval
  - answer synthesis

### Task 8: Upgrade frontend transparency
- Files:
  - `doc-frontend/src/types/chat.ts`
  - `doc-frontend/src/components/EvidencePanel.tsx`
  - related tests
- Show:
  - execution plan
  - knowledge retrieval
  - forecast summary

### Task 9: Verify end-to-end
- Run backend full unittest
- Run frontend full vitest
- Run frontend build
- Run at least one mixed-query smoke
