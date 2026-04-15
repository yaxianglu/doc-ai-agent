# Invalid Input Governance Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a unified invalid-input governance chain so gibberish, keyboard mash, and ultra-low-signal prompts are clarified early instead of being routed into business advice or data-query execution.

**Architecture:** Keep the current Agent V2 flow, but insert a deterministic input-governance layer ahead of normal planning, demote router output to a candidate signal instead of final authority, add execution gates for advice/data-query, and keep `Answer Guard` as a final fail-safe. The implementation prioritizes “can we answer this at all?” before “how should we answer it?”

**Tech Stack:** Python 3.11, unittest, existing `semantic_parser` / `query_planner` / `answer_guard` stack, current OpenAI router, LlamaIndex-backed retrieval, existing agent tests.

---

### Task 1: Add invalid-input classification helpers

**Files:**
- Create: `src/doc_ai_agent/input_guard.py`
- Modify: `src/doc_ai_agent/query_intent_routing.py`
- Test: `tests/test_input_guard.py`

**Step 1: Write the failing test**

```python
import unittest

from doc_ai_agent.input_guard import classify_input_quality


class InputGuardTests(unittest.TestCase):
    def test_keyboard_mash_is_marked_invalid(self):
        decision = classify_input_quality("h d k j h sa d k l j")

        self.assertFalse(decision["is_valid_input"])
        self.assertEqual(decision["reason"], "invalid_gibberish")
        self.assertTrue(decision["should_clarify"])
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent && PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_input_guard`
Expected: FAIL with `ModuleNotFoundError` or missing helper

**Step 3: Write minimal implementation**

```python
def classify_input_quality(text: str) -> dict:
    normalized = str(text or "").strip()
    if normalized == "h d k j h sa d k l j":
        return {
            "is_valid_input": False,
            "reason": "invalid_gibberish",
            "should_clarify": True,
            "clarification": "我没看懂这条输入。你可以直接问虫情、墒情、预警数据，或让我给处置建议。",
            "confidence": 0.98,
        }
    return {
        "is_valid_input": True,
        "reason": "",
        "should_clarify": False,
        "clarification": None,
        "confidence": 0.0,
    }
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent && PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_input_guard`
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add src/doc_ai_agent/input_guard.py src/doc_ai_agent/query_intent_routing.py tests/test_input_guard.py
git commit -m "feat: add invalid input guard helpers"
```

### Task 2: Make semantic parsing honor invalid input before follow-up reuse

**Files:**
- Modify: `src/doc_ai_agent/semantic_parser.py`
- Modify: `src/doc_ai_agent/request_understanding.py`
- Test: `tests/test_semantic_parser.py`
- Test: `tests/test_request_understanding.py`

**Step 1: Write the failing test**

```python
def test_invalid_input_does_not_become_follow_up(self):
    parser = SemanticParser()
    result = parser.parse(
        "h d k j h sa d k l j",
        context={"domain": "soil", "region_name": "徐州市"},
    )

    self.assertTrue(result.needs_clarification)
    self.assertEqual(result.fallback_reason, "invalid_gibberish")
    self.assertEqual(result.followup_type, "none")
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent && PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_semantic_parser tests.test_request_understanding`
Expected: FAIL because invalid input is not yet elevated above follow-up/context logic

**Step 3: Write minimal implementation**

```python
guard = classify_input_quality(normalized)
if not guard["is_valid_input"]:
    return SemanticParseResult(
        normalized_query=normalized,
        intent="advice",
        needs_clarification=True,
        fallback_reason=guard["reason"],
        trace=["normalize", "input_guard"],
    )
```

**Step 4: Run test to verify it passes**

Run the same command as Step 2.
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add src/doc_ai_agent/semantic_parser.py src/doc_ai_agent/request_understanding.py tests/test_semantic_parser.py tests/test_request_understanding.py
git commit -m "parser: prioritize invalid input clarification"
```

### Task 3: Block router advice from overriding invalid or low-signal inputs

**Files:**
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/query_intent_routing.py`
- Test: `tests/test_query_planner.py`

**Step 1: Write the failing test**

```python
def test_router_advice_does_not_override_invalid_input(self):
    planner = QueryPlanner(FakeAdviceRouter())

    plan = planner.plan("h d k j h sa d k l j")

    self.assertTrue(plan["needs_clarification"])
    self.assertEqual(plan["reason"], "invalid_gibberish")
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent && PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_query_planner`
Expected: FAIL because planner still trusts `router_advice`

**Step 3: Write minimal implementation**

```python
if input_guard_reason:
    return clarification_plan

if route_intent == "advice" and not has_explicit_advice_signal(question):
    return clarification_plan
```

**Step 4: Run test to verify it passes**

Run the same command as Step 2.
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add src/doc_ai_agent/query_planner.py src/doc_ai_agent/query_intent_routing.py tests/test_query_planner.py
git commit -m "planner: gate router advice behind valid input checks"
```

### Task 4: Add execution gates for advice and data-query

**Files:**
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/agent_orchestration.py`
- Test: `tests/test_query_planner.py`
- Test: `tests/test_agent.py`

**Step 1: Write the failing test**

```python
def test_invalid_input_never_enters_analysis_or_advice_execution(self):
    result = agent.answer("h d k j h sa d k l j", thread_id="thread-invalid")

    self.assertEqual(result["evidence"]["generation_mode"], "clarification")
    self.assertEqual(result["evidence"]["response_meta"]["fallback_reason"], "invalid_gibberish")
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent && PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_query_planner tests.test_agent`
Expected: FAIL because invalid input can still route to advice

**Step 3: Write minimal implementation**

```python
def advice_gate(...):
    if not has_explicit_advice_signal(question):
        return clarification_plan

def data_query_gate(...):
    if not has_query_signal(question):
        return clarification_plan
```

**Step 4: Run test to verify it passes**

Run the same command as Step 2.
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add src/doc_ai_agent/query_planner.py src/doc_ai_agent/agent_orchestration.py tests/test_query_planner.py tests/test_agent.py
git commit -m "agent: add execution gates for invalid inputs"
```

### Task 5: Add answer-guard fallback for invalid-input business hallucinations

**Files:**
- Modify: `src/doc_ai_agent/answer_guard.py`
- Modify: `src/doc_ai_agent/agent.py`
- Test: `tests/test_answer_guard.py`
- Test: `tests/test_agent.py`

**Step 1: Write the failing test**

```python
def test_invalid_input_business_advice_is_rewritten_to_clarification(self):
    review = guard.review(
        question="h d k j h sa d k l j",
        understanding={"fallback_reason": "invalid_gibberish"},
        plan={"intent": "advice"},
        query_result={},
        forecast_result={},
        response={"answer": "建议：先分区核查土壤墒情。"},
    )

    self.assertEqual(review["action"], "fallback")
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent && PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_answer_guard tests.test_agent`
Expected: FAIL because guard currently accepts the advice answer

**Step 3: Write minimal implementation**

```python
if invalid_input_reason and answer_contains_business_claim(answer):
    return fallback_clarification
```

**Step 4: Run test to verify it passes**

Run the same command as Step 2.
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add src/doc_ai_agent/answer_guard.py src/doc_ai_agent/agent.py tests/test_answer_guard.py tests/test_agent.py
git commit -m "guard: block business answers for invalid inputs"
```

### Task 6: Add an invalid-input regression pack

**Files:**
- Create: `tests/test_invalid_input_regressions.py`
- Modify: `tests/test_agent.py`
- Modify: `tests/test_query_planner.py`

**Step 1: Write the failing test**

```python
INVALID_CASES = [
    "h d k j h sa d k l j",
    "asd qwe zxc",
    ".....",
    "徐州 那个",
]

for question in INVALID_CASES:
    result = agent.answer(question, thread_id=f"invalid-{question}")
    self.assertIn("没看懂", result["answer"])
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent && PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest tests.test_invalid_input_regressions`
Expected: FAIL on one or more invalid input variants

**Step 3: Write minimal implementation**

```python
# Reuse the new input guard and planner clarification path.
# Do not special-case each string inside the agent layer.
```

**Step 4: Run test to verify it passes**

Run the same command as Step 2.
Expected: PASS

**Step 5: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add tests/test_invalid_input_regressions.py tests/test_agent.py tests/test_query_planner.py
git commit -m "tests: add invalid input governance regressions"
```

### Task 7: Run focused verification and record the capability score

**Files:**
- Modify: `docs/plans/2026-04-16-invalid-input-governance-design.md`
- Modify: `docs/plans/2026-04-16-invalid-input-governance-implementation.md`
- Optional: `docs/reports/` if a score report is created

**Step 1: Run the focused verification suite**

Run:

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
PYTHONPATH=src /Users/mac/.pyenv/versions/3.11.10/bin/python3.11 -m unittest \
  tests.test_input_guard \
  tests.test_semantic_parser \
  tests.test_request_understanding \
  tests.test_query_planner \
  tests.test_answer_guard \
  tests.test_agent \
  tests.test_invalid_input_regressions
```

Expected: PASS

**Step 2: Run a real-config reproduction check**

Run:

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
set -a && source /Users/mac/.doc-cloud/config/doc-ai-agent.env && set +a
PYTHONPATH=src python /Users/mac/Desktop/gago-cloud/code/doc-ai-agent/scripts/run_server.py
```

Then verify a real request similar to:

```bash
curl -sS -X POST http://127.0.0.1:38117/chat \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer <token>" \
  -d '{"question":"h d k j h sa d k l j","history":[],"thread_id":"invalid-input-smoke"}'
```

Expected: clarification response; not business advice, not business overview

**Step 3: Update capability score note**

- Record current achieved score against:
  - current baseline `2.5/10`
  - Phase 1 target `7/10`
  - Phase 2 target `8.5/10`

**Step 4: Commit**

```bash
cd /Users/mac/Desktop/gago-cloud/code/doc-ai-agent
git add docs/plans/2026-04-16-invalid-input-governance-design.md docs/plans/2026-04-16-invalid-input-governance-implementation.md
git commit -m "docs: finalize invalid input governance plan"
```
