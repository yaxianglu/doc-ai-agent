# Semantic Understanding V2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a unified semantic parse layer so language understanding becomes stable, explainable, and easier to evolve without scattering logic across multiple modules.

**Architecture:** Introduce a new `SemanticParseResult` contract plus a `semantic_parser.py` orchestrator that merges normalization, slot extraction, LLM extraction, and arbitration. Keep compatibility by routing `request_understanding.py` through the new parser first, then gradually simplify `query_planner.py` into a consumer of parse output instead of a second understanding engine.

**Tech Stack:** Python 3.11, unittest, existing OpenAI client / Instructor backend, regex + rules, optional HanLP, existing eval pipeline.

---

### Task 1: Define the Semantic Parse contract

**Files:**
- Create: `src/doc_ai_agent/semantic_parse.py`
- Modify: `src/doc_ai_agent/agent_contracts.py`
- Test: `tests/test_semantic_parse.py`

**Step 1: Write the failing test**

```python
import unittest

from doc_ai_agent.semantic_parse import SemanticParseResult


class SemanticParseResultTests(unittest.TestCase):
    def test_from_minimal_payload_sets_defaults(self):
        result = SemanticParseResult.from_dict({
            "normalized_query": "浙江天气",
            "intent": "advice",
            "is_out_of_scope": True,
        })

        self.assertEqual(result.normalized_query, "浙江天气")
        self.assertEqual(result.intent, "advice")
        self.assertTrue(result.is_out_of_scope)
        self.assertEqual(result.trace, [])
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_semantic_parse`
Expected: FAIL with `ModuleNotFoundError` or `AttributeError`

**Step 3: Write minimal implementation**

```python
from dataclasses import dataclass, field


@dataclass
class SemanticParseResult:
    normalized_query: str = ""
    intent: str = "advice"
    is_out_of_scope: bool = False
    trace: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict | None) -> "SemanticParseResult":
        payload = dict(payload or {})
        return cls(
            normalized_query=str(payload.get("normalized_query") or ""),
            intent=str(payload.get("intent") or "advice"),
            is_out_of_scope=bool(payload.get("is_out_of_scope")),
            trace=list(payload.get("trace") or []),
        )
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_semantic_parse`
Expected: PASS

**Step 5: Commit**

```bash
git add src/doc_ai_agent/semantic_parse.py src/doc_ai_agent/agent_contracts.py tests/test_semantic_parse.py
git commit -m "feat: add semantic parse contract"
```

### Task 2: Build the semantic parser orchestrator

**Files:**
- Create: `src/doc_ai_agent/semantic_parser.py`
- Modify: `src/doc_ai_agent/request_understanding.py`
- Modify: `src/doc_ai_agent/request_understanding_backend.py`
- Modify: `src/doc_ai_agent/entity_extraction.py`
- Test: `tests/test_semantic_parser.py`

**Step 1: Write the failing test**

```python
import unittest

from doc_ai_agent.semantic_parser import SemanticParser


class SemanticParserTests(unittest.TestCase):
    def test_weather_question_is_marked_out_of_scope(self):
        parser = SemanticParser()
        result = parser.parse("浙江天气")

        self.assertTrue(result.is_out_of_scope)
        self.assertEqual(result.intent, "advice")
        self.assertIn("ood", result.trace)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_semantic_parser`
Expected: FAIL because `SemanticParser` does not exist

**Step 3: Write minimal implementation**

```python
class SemanticParser:
    def parse(self, question: str, context: dict | None = None) -> SemanticParseResult:
        normalized = str(question or "").strip()
        if "天气" in normalized:
            return SemanticParseResult(
                normalized_query=normalized,
                intent="advice",
                is_out_of_scope=True,
                fallback_reason="out_of_scope_capability",
                trace=["normalize", "ood"],
            )
        return SemanticParseResult(
            normalized_query=normalized,
            intent="data_query" if "虫情" in normalized else "advice",
            trace=["normalize"],
        )
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_semantic_parser tests.test_request_understanding`
Expected: PASS

**Step 5: Commit**

```bash
git add src/doc_ai_agent/semantic_parser.py src/doc_ai_agent/request_understanding.py src/doc_ai_agent/request_understanding_backend.py src/doc_ai_agent/entity_extraction.py tests/test_semantic_parser.py
git commit -m "feat: add semantic parser orchestrator"
```

### Task 3: Centralize OOD, identity, clarification, and generic explanation

**Files:**
- Create: `src/doc_ai_agent/semantic_judger.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/advice_engine.py`
- Test: `tests/test_semantic_judger.py`
- Test: `tests/test_query_planner.py`
- Test: `tests/test_agent.py`

**Step 1: Write the failing test**

```python
import unittest

from doc_ai_agent.semantic_judger import SemanticJudger


class SemanticJudgerTests(unittest.TestCase):
    def test_generic_explanation_returns_direct_explanation_mode(self):
        judger = SemanticJudger()
        decision = judger.judge("从数据看，这次异常最可能的原因是什么？")

        self.assertEqual(decision["reason"], "generic_explanation")
        self.assertFalse(decision["needs_clarification"])
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_semantic_judger`
Expected: FAIL because `SemanticJudger` does not exist

**Step 3: Write minimal implementation**

```python
class SemanticJudger:
    def judge(self, question: str) -> dict:
        q = str(question or "").strip()
        if "从数据看" in q or "未知区域" in q:
            return {"reason": "generic_explanation", "needs_clarification": False}
        if "天气" in q:
            return {"reason": "out_of_scope_capability", "needs_clarification": True}
        return {"reason": "", "needs_clarification": False}
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_semantic_judger tests.test_query_planner tests.test_agent`
Expected: PASS

**Step 5: Commit**

```bash
git add src/doc_ai_agent/semantic_judger.py src/doc_ai_agent/query_planner.py src/doc_ai_agent/advice_engine.py tests/test_semantic_judger.py tests/test_query_planner.py tests/test_agent.py
git commit -m "feat: centralize semantic edge-case arbitration"
```

### Task 4: Make the planner consume parse output

**Files:**
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/query_plan.py`
- Modify: `src/doc_ai_agent/agent.py`
- Test: `tests/test_query_planner.py`
- Test: `tests/test_agent.py`

**Step 1: Write the failing test**

```python
def test_planner_uses_semantic_parse_result_for_ood_question(self):
    planner = QueryPlanner(None)
    plan = planner.plan("浙江天气")
    self.assertEqual(plan["reason"], "out_of_scope_capability")
    self.assertEqual(plan["route"]["query_type"], "count")
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_planner -k out_of_scope`
Expected: FAIL if planner still re-derives logic incorrectly

**Step 3: Write minimal implementation**

```python
# planner.plan(...)
parse_result = self.semantic_parser.parse(question, context=context)
if parse_result.is_out_of_scope:
    return self._finalize_plan({...})
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_planner tests.test_agent`
Expected: PASS

**Step 5: Commit**

```bash
git add src/doc_ai_agent/query_planner.py src/doc_ai_agent/query_plan.py src/doc_ai_agent/agent.py tests/test_query_planner.py tests/test_agent.py
git commit -m "refactor: planner consume semantic parse results"
```

### Task 5: Expose confidence, fallback reason, and trace end-to-end

**Files:**
- Modify: `src/doc_ai_agent/semantic_parse.py`
- Modify: `src/doc_ai_agent/request_understanding.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/agent_response_meta.py`
- Test: `tests/test_request_understanding.py`
- Test: `tests/test_agent.py`

**Step 1: Write the failing test**

```python
def test_weather_question_exposes_confidence_and_fallback_reason(self):
    result = self.understanding.analyze("浙江天气")
    self.assertGreaterEqual(result["confidence"], 0.8)
    self.assertEqual(result["fallback_reason"], "out_of_scope_capability")
    self.assertIn("ood", result["trace"])
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_request_understanding`
Expected: FAIL because fields do not exist yet

**Step 3: Write minimal implementation**

```python
return {
    ...
    "confidence": parse_result.confidence,
    "fallback_reason": parse_result.fallback_reason,
    "trace": parse_result.trace,
}
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_request_understanding tests.test_agent`
Expected: PASS

**Step 5: Commit**

```bash
git add src/doc_ai_agent/semantic_parse.py src/doc_ai_agent/request_understanding.py src/doc_ai_agent/query_planner.py src/doc_ai_agent/agent_response_meta.py tests/test_request_understanding.py tests/test_agent.py
git commit -m "feat: expose semantic confidence and trace"
```

### Task 6: Split evals and automate regression comparison

**Files:**
- Create: `evals/ood_eval.json`
- Create: `evals/explanation_eval.json`
- Create: `evals/forecast_eval.json`
- Create: `evals/context_eval.json`
- Modify: `src/doc_ai_agent/acceptance_eval.py`
- Modify: `scripts/run_strict_acceptance_eval.py`
- Modify: `README.md`
- Test: `tests/test_acceptance_eval.py`

**Step 1: Write the failing test**

```python
def test_score_run_reports_subsuite_scores(self):
    scored = score_run([...])
    self.assertIn("ood", scored["summary"]["suite_scores"])
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_acceptance_eval`
Expected: FAIL because `suite_scores` does not exist

**Step 3: Write minimal implementation**

```python
summary["suite_scores"] = {
    "ood": ...,
    "explanation": ...,
    "forecast": ...,
    "context": ...,
}
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_acceptance_eval`
Expected: PASS

**Step 5: Commit**

```bash
git add evals/ood_eval.json evals/explanation_eval.json evals/forecast_eval.json evals/context_eval.json src/doc_ai_agent/acceptance_eval.py scripts/run_strict_acceptance_eval.py README.md tests/test_acceptance_eval.py
git commit -m "feat: split semantic eval suites and regression reporting"
```

### Task 7: Run the full verification gate and capture the new baseline

**Files:**
- Modify: `output/evals/latest/raw.json`
- Modify: `output/evals/latest/scored.json`
- Modify: `output/evals/latest/report.md`
- Modify: `output/evals/latest/comparison.md`

**Step 1: Run the targeted test gate**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_semantic_parse tests.test_semantic_parser tests.test_semantic_judger tests.test_request_understanding tests.test_query_planner tests.test_agent tests.test_acceptance_eval`
Expected: PASS

**Step 2: Run the wider regression gate**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent tests.test_query_engine tests.test_request_understanding tests.test_query_planner tests.test_server tests.test_acceptance_eval`
Expected: PASS

**Step 3: Run the strict eval**

Run: `PYTHONPATH=src python3.11 scripts/run_strict_acceptance_eval.py --score --compare`
Expected: new reports under `output/evals/latest/`

**Step 4: Review low-score items**

Run: `python3 - <<'PY'\nimport json\nfrom pathlib import Path\nscored=json.loads(Path('output/evals/latest/scored.json').read_text())\nprint([item for item in scored['items'] if item['score'] < 8])\nPY`
Expected: no unexpected regressions

**Step 5: Commit**

```bash
git add output/evals/latest/raw.json output/evals/latest/scored.json output/evals/latest/report.md output/evals/latest/comparison.md
git commit -m "chore: refresh semantic understanding eval baseline"
```

