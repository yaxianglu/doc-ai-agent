# Low-Score Remediation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the current low-score eval clusters by strengthening answer-form parsing, county/trend routing, repair-first guarding, multi-turn slot carry-over, and structured composite responses.

**Architecture:** Keep the current Agent V2 architecture, but tighten the deterministic contract at the parser, planner, response builder, and guard boundaries. The implementation prioritizes root-cause routing/output fixes over model changes and converts the current low-score items into a stable regression pack.

**Tech Stack:** Python 3.11, unittest, current `doc_ai_agent` parser/planner/guard stack, strict acceptance eval scripts.

---

### Task A: Add low-score regression fixtures

**Files:**
- Create: `tests/test_low_score_regressions.py`
- Modify: `output/evals/latest/scored.json`
- Test: `tests/test_low_score_regressions.py`

**Step 1: Write the failing regression tests**

- Cover the main clusters:
  - boolean question returns yes/no first
  - trend question returns direction first
  - county question does not silently degrade to city ranking
  - multi-turn county/domain carry-over remains stable
  - composite question includes rank + reason + advice sections

**Step 2: Run test to verify it fails**

Run:

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_low_score_regressions
```

Expected: one or more failures matching the current low-score behavior.

**Step 3: Build a reusable low-score sample set**

- Derive fixtures from the current 32 low-score items in `output/evals/latest/scored.json`.
- Keep the fixture list focused and deterministic; do not use all 140 cases in unit tests.

**Step 4: Run test to verify the fixture harness is stable**

Run:

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_low_score_regressions
```

Expected: still failing on the target behaviors, but fixture loading itself is stable.

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add tests/test_low_score_regressions.py
git commit -m "tests: lock low-score regression cases"
```

### Task B: Add answer-form semantics to parsing and planning

**Files:**
- Modify: `src/doc_ai_agent/query_dsl.py`
- Modify: `src/doc_ai_agent/query_parser.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/request_understanding.py`
- Test: `tests/test_query_dsl.py`
- Test: `tests/test_query_parser.py`
- Test: `tests/test_query_planner.py`

**Step 1: Write failing parser/planner tests**

- Add assertions for:
  - `是否/有没有/会不会` -> `answer_form=boolean`
  - `上升还是下降/增加还是减少/有没有缓解` -> `answer_form=trend`
  - `先排县，再解释，再建议` -> `answer_form=composite`

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_query_dsl tests.test_query_parser tests.test_query_planner
```

Expected: missing-field or wrong-route failures.

**Step 3: Implement minimal parsing and planning changes**

- Extend the DSL with `answer_form`.
- Detect boolean/trend/composite cues in the parser.
- Make planner templates route these forms to fixed execution patterns instead of generic rank logic.

**Step 4: Run tests to verify they pass**

Run the same command as Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add src/doc_ai_agent/query_dsl.py src/doc_ai_agent/query_parser.py src/doc_ai_agent/query_planner.py src/doc_ai_agent/request_understanding.py tests/test_query_dsl.py tests/test_query_parser.py tests/test_query_planner.py
git commit -m "planner: add answer-form routing semantics"
```

### Task C: Strengthen county and trend execution templates

**Files:**
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Modify: `src/doc_ai_agent/query_engine.py`
- Modify: `src/doc_ai_agent/agent.py`
- Test: `tests/test_agent_execution_nodes.py`
- Test: `tests/test_query_engine.py`
- Test: `tests/test_agent.py`

**Step 1: Write failing execution tests**

- County queries:
  - if county data exists, return county answer
  - if county data does not exist, return explicit county-unavailable answer
- Trend queries:
  - return direction first
  - include sample coverage when available

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_agent_execution_nodes tests.test_query_engine tests.test_agent
```

Expected: current fallback/routing behavior fails the new assertions.

**Step 3: Implement minimal execution changes**

- Add county-specific execution branches.
- Add direct trend execution payloads instead of relying on late guard rewrites.
- Preserve existing ranking behavior for rank-form questions.

**Step 4: Run tests to verify they pass**

Run the same command as Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add src/doc_ai_agent/query_planner.py src/doc_ai_agent/agent_execution_nodes.py src/doc_ai_agent/query_engine.py src/doc_ai_agent/agent.py tests/test_agent_execution_nodes.py tests/test_query_engine.py tests/test_agent.py
git commit -m "agent: tighten county and trend execution"
```

### Task D: Make Response Builder and Guard repair-first

**Files:**
- Modify: `src/doc_ai_agent/response_builder.py`
- Modify: `src/doc_ai_agent/answer_guard.py`
- Modify: `src/doc_ai_agent/agent.py`
- Test: `tests/test_answer_guard.py`
- Test: `tests/test_agent_contracts.py`
- Test: `tests/test_low_score_regressions.py`

**Step 1: Write failing output-contract tests**

- Boolean questions must start with yes/no.
- Trend questions must start with direction or explicit uncertainty.
- Composite questions must render stable sections.
- Guard must prefer rewrite/retry over fallback for recoverable county/trend mistakes.

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_answer_guard tests.test_agent_contracts tests.test_low_score_regressions
```

Expected: failures showing current fallback-first behavior.

**Step 3: Implement minimal builder and guard changes**

- Add structured answer types in `ResponseBuilder`.
- Add required first-line templates by `answer_form`.
- Update guard so:
  - rewrite first
  - corrected-route retry second
  - fallback last

**Step 4: Run tests to verify they pass**

Run the same command as Step 2.

Expected: PASS.

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add src/doc_ai_agent/response_builder.py src/doc_ai_agent/answer_guard.py src/doc_ai_agent/agent.py tests/test_answer_guard.py tests/test_agent_contracts.py tests/test_low_score_regressions.py
git commit -m "answer: enforce direct-form responses and repair-first guard"
```

### Task E: Stabilize multi-turn slot carry-over and rerun strict eval

**Files:**
- Modify: `src/doc_ai_agent/agent_memory.py`
- Modify: `src/doc_ai_agent/agent.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/agent_contracts.py`
- Test: `tests/test_memory_store.py`
- Test: `tests/test_agent.py`
- Test: `tests/test_low_score_regressions.py`
- Test: `output/evals/latest/report.md`

**Step 1: Write failing multi-turn tests**

- Lock slot inheritance for:
  - domain
  - region
  - granularity
  - time window
  - answer form

**Step 2: Run tests to verify they fail**

Run:

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_memory_store tests.test_agent tests.test_low_score_regressions
```

Expected: existing multi-turn follow-up failures.

**Step 3: Implement minimal slot-state changes**

- Persist the five key slots in memory context.
- Make follow-up planning prefer explicit slot inheritance over fuzzy re-inference.

**Step 4: Run tests and full strict eval**

Run:

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest discover -s tests
DOC_AGENT_MEMORY_STORE_PATH=./output/eval-memory-v2.json PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 scripts/run_strict_acceptance_eval.py --score --compare
```

Expected:
- unit tests pass
- strict 140-case average increases
- low-score count drops below the current 32

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add src/doc_ai_agent/agent_memory.py src/doc_ai_agent/agent.py src/doc_ai_agent/query_planner.py src/doc_ai_agent/agent_contracts.py tests/test_memory_store.py tests/test_agent.py tests/test_low_score_regressions.py output/evals/latest/report.md output/evals/latest/scored.json output/evals/latest/raw.json
git commit -m "memory: stabilize multi-turn low-score regressions"
```

