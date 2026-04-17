# Restricted Agent Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor `doc-ai-agent` into a restricted data-task pipeline with explicit semantic metric resolution, capability gating, memory inheritance policy, and knowledge boundaries while preserving the current `/chat` contract and strict-eval behavior.

**Architecture:** Keep the current LangGraph topology as the outer shell, but progressively move business semantics and admission decisions out of `QueryPlanner` and `DocAIAgent`. The implementation sequence first constrains planning, then adds semantic metric resolution, forecast eligibility, memory policy, and knowledge policy, with contract-preserving tests at each stage.

**Tech Stack:** Python 3.11, LangGraph, unittest, existing `RequestUnderstanding` / `QueryDSL` / capability modules, strict acceptance eval scripts.

---

### Task 1: Add planner templates and restricted planning contract

**Files:**
- Create: `src/doc_ai_agent/planner_templates.py`
- Create: `src/doc_ai_agent/restricted_planner.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/agent_orchestration.py`
- Test: `tests/test_query_planner.py`
- Test: `tests/test_agent_orchestration.py`

**Step 1: Write the failing tests**

- Add tests asserting:
  - planner output is selected from a finite plan-type set
  - unsupported free-form task graphs are not emitted on the main path
  - current route behavior remains compatible for analysis / advice / clarify

**Step 2: Run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_planner tests.test_agent_orchestration -v`

Expected: at least one new assertion fails before implementation.

**Step 3: Implement the minimal planning restriction**

- Create reusable plan templates for:
  - `fact_query`
  - `trend_query`
  - `ranking_query`
  - `forecast_query`
  - `explanation_query`
  - `advice_query`
  - `clarify_query`
- Make `QueryPlanner` delegate template selection to the restricted planner path.
- Preserve current outward fields such as `route`, `query_plan`, `task_graph`, `reason`, `context_trace`.

**Step 4: Re-run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_planner tests.test_agent_orchestration -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/planner_templates.py src/doc_ai_agent/restricted_planner.py src/doc_ai_agent/query_planner.py src/doc_ai_agent/agent_orchestration.py tests/test_query_planner.py tests/test_agent_orchestration.py
git commit -m "refactor: restrict planner to template-based plans"
```

### Task 2: Introduce `SemanticMetricResolver`

**Files:**
- Create: `src/doc_ai_agent/semantic_metric_resolver.py`
- Modify: `src/doc_ai_agent/request_understanding.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/query_plan.py`
- Test: `tests/test_request_understanding.py`
- Test: `tests/test_query_planner.py`
- Test: `tests/test_query_plan.py`

**Step 1: Write the failing tests**

- Add tests asserting explicit resolution for:
  - alert count queries
  - TopN ranking queries
  - trend queries
  - rolling time-window queries
  - region-scope disambiguation

**Step 2: Run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_request_understanding tests.test_query_planner tests.test_query_plan -v`

Expected: FAIL until the resolver is wired in.

**Step 3: Implement the resolver**

- Add a normalized metric payload, for example:
  - `metric`
  - `aggregation`
  - `ranking_basis`
  - `time_scope_mode`
  - `geo_scope_mode`
- Call the resolver after request understanding and before planning.
- Preserve compatibility by keeping existing understanding fields alongside the new semantic metric payload.

**Step 4: Re-run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_request_understanding tests.test_query_planner tests.test_query_plan -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/semantic_metric_resolver.py src/doc_ai_agent/request_understanding.py src/doc_ai_agent/query_planner.py src/doc_ai_agent/query_plan.py tests/test_request_understanding.py tests/test_query_planner.py tests/test_query_plan.py
git commit -m "feat: add semantic metric resolver"
```

### Task 3: Add `ForecastEligibilityCheck`

**Files:**
- Create: `src/doc_ai_agent/forecast_eligibility.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Modify: `src/doc_ai_agent/forecast_service.py`
- Modify: `src/doc_ai_agent/capabilities/forecast.py`
- Test: `tests/test_forecast_service.py`
- Test: `tests/test_agent_execution_nodes.py`

**Step 1: Write the failing tests**

- Add tests asserting:
  - low-sample forecasts are rejected or downgraded
  - long unsupported horizons are rejected
  - high-missingness or unstable series trigger fallback
  - eligible forecasts keep the current happy-path behavior

**Step 2: Run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_forecast_service tests.test_agent_execution_nodes -v`

Expected: FAIL before eligibility checks exist.

**Step 3: Implement forecast eligibility**

- Add an eligibility result with:
  - `eligible`
  - `reason`
  - `fallback_mode`
  - `confidence_band`
- Evaluate eligibility before forecast execution.
- Degrade to trend-only or clarification when forecast reliability is insufficient.

**Step 4: Re-run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_forecast_service tests.test_agent_execution_nodes -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/forecast_eligibility.py src/doc_ai_agent/agent_execution_nodes.py src/doc_ai_agent/forecast_service.py src/doc_ai_agent/capabilities/forecast.py tests/test_forecast_service.py tests/test_agent_execution_nodes.py
git commit -m "feat: gate forecast execution with eligibility checks"
```

### Task 4: Add `MemoryPolicy`

**Files:**
- Create: `src/doc_ai_agent/memory_policy.py`
- Modify: `src/doc_ai_agent/agent.py`
- Modify: `src/doc_ai_agent/request_context_resolution.py`
- Modify: `src/doc_ai_agent/request_understanding.py`
- Test: `tests/test_agent.py`
- Test: `tests/test_request_understanding.py`

**Step 1: Write the failing tests**

- Add tests asserting:
  - region / window / domain can be inherited in follow-up turns
  - fact values and ranking outcomes are never inherited as truth
  - ambiguous follow-up questions trigger clarification instead of unsafe inheritance

**Step 2: Run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent tests.test_request_understanding -v`

Expected: FAIL before memory policy is explicit.

**Step 3: Implement memory policy**

- Create a memory-policy result with:
  - `inherited_slots`
  - `forbidden_slots`
  - `confidence`
  - `should_clarify`
- Use it before request understanding consumes prior context.
- Preserve current thread memory persistence behavior.

**Step 4: Re-run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent tests.test_request_understanding -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/memory_policy.py src/doc_ai_agent/agent.py src/doc_ai_agent/request_context_resolution.py src/doc_ai_agent/request_understanding.py tests/test_agent.py tests/test_request_understanding.py
git commit -m "feat: add explicit memory inheritance policy"
```

### Task 5: Add `KnowledgePolicy` and evidence separation

**Files:**
- Create: `src/doc_ai_agent/knowledge_policy.py`
- Create: `src/doc_ai_agent/response_assembler.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Modify: `src/doc_ai_agent/agent_synthesis_orchestration.py`
- Modify: `src/doc_ai_agent/answer_guard.py`
- Test: `tests/test_agent_execution_nodes.py`
- Test: `tests/test_answer_guard.py`
- Test: `tests/test_agent_contracts.py`

**Step 1: Write the failing tests**

- Add tests asserting:
  - fact queries do not use external knowledge as a fact source
  - explanation / advice queries still receive knowledge augmentation
  - evidence distinguishes internal data from external knowledge

**Step 2: Run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent_execution_nodes tests.test_answer_guard tests.test_agent_contracts -v`

Expected: FAIL before policy enforcement exists.

**Step 3: Implement the policy and response assembly split**

- Add a knowledge-policy decision before retrieval.
- Route explanation / advice through knowledge augmentation only when allowed.
- Introduce response assembly helpers that preserve:
  - `mode`
  - `answer`
  - `data`
  - `evidence`
  - `processing`
- Separate evidence into internal facts vs external knowledge.

**Step 4: Re-run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent_execution_nodes tests.test_answer_guard tests.test_agent_contracts -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/knowledge_policy.py src/doc_ai_agent/response_assembler.py src/doc_ai_agent/agent_execution_nodes.py src/doc_ai_agent/agent_synthesis_orchestration.py src/doc_ai_agent/answer_guard.py tests/test_agent_execution_nodes.py tests/test_answer_guard.py tests/test_agent_contracts.py
git commit -m "feat: enforce knowledge boundary and split evidence"
```

### Task 6: Slim `DocAIAgent` into a coordinator

**Files:**
- Modify: `src/doc_ai_agent/agent.py`
- Modify: `src/doc_ai_agent/agent_orchestration.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Test: `tests/test_agent.py`
- Test: `tests/test_agent_contracts.py`

**Step 1: Write the failing tests**

- Add tests asserting:
  - `DocAIAgent` mainly passes state between layers
  - node-specific decisions live in policy or capability modules
  - current `/chat` response fields remain unchanged

**Step 2: Run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent tests.test_agent_contracts -v`

Expected: FAIL before orchestration slimming is complete.

**Step 3: Implement the coordinator slimming**

- Keep graph topology stable where possible.
- Remove planner- and policy-specific decision logic from `DocAIAgent`.
- Make orchestration depend on public helpers only.

**Step 4: Re-run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent tests.test_agent_contracts -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/agent.py src/doc_ai_agent/agent_orchestration.py src/doc_ai_agent/agent_execution_nodes.py tests/test_agent.py tests/test_agent_contracts.py
git commit -m "refactor: slim agent into pipeline coordinator"
```

### Task 7: Run regression and eval gates

**Files:**
- Modify if needed: `docs/architecture/current-agent-contract.md`
- Verify: `evals/strict_acceptance_140.json`
- Verify: `scripts/run_strict_acceptance_eval.py`

**Step 1: Run targeted unit suites**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_planner tests.test_request_understanding tests.test_agent tests.test_agent_execution_nodes tests.test_forecast_service tests.test_answer_guard tests.test_agent_contracts -v`

Expected: PASS.

**Step 2: Run the strict acceptance eval**

Run: `PYTHONPATH=src python3.11 scripts/run_strict_acceptance_eval.py --score --compare`

Expected:
- core metrics do not regress
- output contract remains stable

**Step 3: Update contract doc only if compatibility fields changed internally**

- Document any new internal evidence blocks that were added without breaking the external contract.

**Step 4: Commit**

```bash
git add docs/architecture/current-agent-contract.md
git commit -m "test: verify restricted pipeline against strict eval gate"
```
