# Agent V2 Architecture Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate the current agricultural analysis agent toward the V2 production architecture with unified query DSL, standardized capability outputs, lighter planning, stronger state management, and structured response building while preserving current behavior and eval coverage.

**Architecture:** The migration is incremental. First introduce stable schemas (`QueryDSL`, `CapabilityResult`) and a unified parser/router boundary without breaking the existing query planner. Then gradually refactor orchestration and execution layers to consume those structures. Finally, add a response builder and stronger memory/access abstractions so the agent emits structured intermediate results before natural-language synthesis.

**Tech Stack:** Python 3.11, LangGraph, unittest, current repository/query/advice engines, existing strict acceptance eval scripts.

---

### Task 1: Freeze current agent contract

**Files:**
- Create: `docs/architecture/current-agent-contract.md`
- Modify: `README.md`
- Test: `tests/test_agent_contracts.py`

**Implementation notes:**
- Document the current request, response, state, and eval contract.
- Record that the strict 140-case suite is the main regression gate.
- Add targeted contract assertions if a response field is undocumented.

### Task 2: Define unified Query DSL

**Files:**
- Create: `src/doc_ai_agent/query_dsl.py`
- Modify: `src/doc_ai_agent/agri_semantics.py`
- Modify: `src/doc_ai_agent/query_extractors.py`
- Create: `docs/architecture/query-dsl.md`
- Test: `tests/test_query_dsl.py`

**Implementation notes:**
- Introduce a normalized query schema/dataclass and helper constructors.
- Represent domain, intent, region, granularity, historical/future windows, follow-up, and clarification flags.
- Keep adapters so old planner code can map to and from DSL during migration.

### Task 3: Define unified Capability Result schema

**Files:**
- Create: `src/doc_ai_agent/capability_result.py`
- Modify: `src/doc_ai_agent/query_engine.py`
- Modify: `src/doc_ai_agent/advice_engine.py`
- Test: `tests/test_capability_result.py`

**Implementation notes:**
- Standardize capability output as structured objects with `type`, `data`, `evidence`, `confidence`, and `meta`.
- Preserve current `QueryResult` and `AdviceResult` compatibility through adapters.

### Task 4: Add unified Query Parser

**Files:**
- Create: `src/doc_ai_agent/query_parser.py`
- Modify: `src/doc_ai_agent/request_understanding.py`
- Modify: `src/doc_ai_agent/request_understanding_backend.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Test: `tests/test_query_parser.py`

**Implementation notes:**
- Centralize natural-language parsing into a single parser that emits `QueryDSL`.
- Keep rules-first parsing and use the backend only to fill gaps.

### Task 5: Refactor Router to capability routing

**Files:**
- Modify: `src/doc_ai_agent/query_intent_routing.py`
- Modify: `src/doc_ai_agent/intent_router.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Test: `tests/test_intent_router.py`

**Implementation notes:**
- Router should choose capabilities and clarification needs, not perform full planning.
- Add a stable route payload that downstream planning consumes.

### Task 6: Constrain planner to template task DSL

**Files:**
- Create: `src/doc_ai_agent/task_dsl.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/task_decomposition.py`
- Test: `tests/test_query_planner.py`
- Test: `tests/test_query_planner_decisions.py`

**Implementation notes:**
- Planner should emit fixed task templates (rank→forecast, rank→reason, rank→advice, trend→reason, joint-risk→advice).
- Eliminate free-form plan text from execution paths.

### Task 7: Unify orchestrator state

**Files:**
- Modify: `src/doc_ai_agent/agent_contracts.py`
- Modify: `src/doc_ai_agent/agent.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Modify: `src/doc_ai_agent/agent_orchestration.py`
- Test: `tests/test_agent_orchestration.py`
- Test: `tests/test_agent_execution_nodes.py`

**Implementation notes:**
- Move to a single orchestration state carrying parsed query, route, plan, task results, evidence, confidence, and memory context.

### Task 8: Introduce Data Query Capability

**Files:**
- Create: `src/doc_ai_agent/capabilities/data_query.py`
- Modify: `src/doc_ai_agent/query_engine.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Test: `tests/test_query_engine.py`

**Implementation notes:**
- Wrap historical rank/trend/detail/device queries in a stable capability interface.

### Task 9: Introduce Forecast Capability

**Files:**
- Create: `src/doc_ai_agent/capabilities/forecast.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Modify: `src/doc_ai_agent/agent.py`
- Test: `tests/test_forecast_service.py`
- Test: `tests/test_agent.py`

**Implementation notes:**
- Provide a single forecast capability output with evidence, confidence, and backend metadata.

### Task 10: Merge explanation and cross-signal into Reasoning Capability

**Files:**
- Create: `src/doc_ai_agent/capabilities/reasoning.py`
- Modify: `src/doc_ai_agent/query_engine.py`
- Modify: `src/doc_ai_agent/query_intent_routing.py`
- Test: `tests/test_query_engine.py`
- Test: `tests/test_agent.py`

**Implementation notes:**
- Add `single_factor_explanation` and `multi_signal_reasoning` modes behind one interface.

### Task 11: Refactor Advice Capability

**Files:**
- Create: `src/doc_ai_agent/capabilities/advice.py`
- Modify: `src/doc_ai_agent/advice_engine.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Test: `tests/test_agent.py`

**Implementation notes:**
- Advice should consume structured evidence from data/forecast/reasoning outputs rather than raw text only.

### Task 12: Upgrade memory to three-layer state

**Files:**
- Modify: `src/doc_ai_agent/letta_memory.py`
- Modify: `src/doc_ai_agent/agent_memory.py`
- Modify: `src/doc_ai_agent/agent.py`
- Test: `tests/test_memory_store.py`
- Test: `tests/test_agent.py`

**Implementation notes:**
- Keep memory as an independent module, but track session context, task context, and optional user preferences separately.

### Task 13: Add unified access facade

**Files:**
- Create: `src/doc_ai_agent/access_facade.py`
- Modify: `src/doc_ai_agent/repository.py`
- Modify: `src/doc_ai_agent/mysql_repository.py`
- Modify: `src/doc_ai_agent/source_provider.py`
- Modify: `src/doc_ai_agent/query_playbook_router.py`
- Test: `tests/test_repository.py`
- Test: `tests/test_source_provider.py`

**Implementation notes:**
- Present a single high-level access layer to capabilities while preserving separate repository and knowledge implementations under the hood.

### Task 14: Add Response Builder and Guard V2

**Files:**
- Create: `src/doc_ai_agent/response_builder.py`
- Modify: `src/doc_ai_agent/answer_guard.py`
- Modify: `src/doc_ai_agent/agent.py`
- Test: `tests/test_answer_guard.py`
- Test: `tests/test_agent.py`
- Test: `tests/test_agent_contracts.py`

**Implementation notes:**
- Build a structured answer object before natural-language rendering.
- Guard should validate granularity, time consistency, evidence completeness, and answer-to-question alignment.

### Verification and release cadence

**For every batch:**
- Run the most local new tests first.
- Then run the relevant integration tests.
- Commit after each batch with a scoped message.

**Final gate:**
- Run `PYTHONPATH=src python3.11 -m unittest`
- Run `DOC_AGENT_MEMORY_STORE_PATH=./output/eval-memory-v2.json PYTHONPATH=src python3.11 scripts/run_strict_acceptance_eval.py --score --compare`
- Save the strict 140-case report and summarize average score, low-score count, and key regressions/improvements.
