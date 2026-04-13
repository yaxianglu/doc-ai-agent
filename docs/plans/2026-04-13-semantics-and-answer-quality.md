# Semantics and Answer Quality Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 收拢共享语义判断，增强中文变体鲁棒性，并把解释/建议回答升级为更稳定的专家式结构。

**Architecture:** 新增一个共享语义模块承载排行/趋势/概况/明细/县级范围等高频语义判断，让 `RequestUnderstanding` 与 `QueryPlanner` 共同依赖它；同时在 `AdviceEngine` 和 `DocAIAgent` 的 analysis synthesis 里统一回答段落结构，提升解释与建议的表达质量。

**Tech Stack:** Python 3.11、unittest、现有 `doc_ai_agent` 模块结构。

---

### Task 1: Add shared semantics regression tests

**Files:**
- Modify: `tests/test_request_understanding.py`
- Modify: `tests/test_query_planner.py`
- Modify: `tests/test_agent.py`

**Step 1: Write the failing tests**

新增以下测试：
- `最突出` / `排前面` / `县有哪些` 这类表达在 understanding 层仍识别为 ranking / county。
- planner 层对同义表达仍给出 `pest_top` / `soil_top` 和正确 `region_level`。
- mixed analysis / advice 回答包含 `结论：`、`原因：`、`依据：`、`建议：` 之类结构化段落。

**Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent && PYTHONPATH=src python3.11 -m unittest \
  tests.test_request_understanding \
  tests.test_query_planner \
  tests.test_agent
```

Expected:
- 新增测试失败，且失败原因是语义未覆盖或回答结构未升级。

**Step 3: Commit**

```bash
# commit after implementation task finishes
```

### Task 2: Introduce shared semantics module

**Files:**
- Create: `src/doc_ai_agent/agri_semantics.py`
- Modify: `src/doc_ai_agent/request_understanding.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Test: `tests/test_request_understanding.py`
- Test: `tests/test_query_planner.py`

**Step 1: Write minimal shared helpers**

在 `agri_semantics.py` 中增加：
- 共享词表常量
- `asks_county_scope(text)`
- `has_ranking_intent(text)`
- `has_trend_intent(text)`
- `has_overview_intent(text)`
- `has_detail_intent(text)`

**Step 2: Refactor understanding/planner to reuse helpers**

- `RequestUnderstanding` 用共享 helper 替换重复词表判断。
- `QueryPlanner` 用共享 helper 替换重复排行/县级范围判断。
- 保持现有行为兼容，只收口重复规则，不重写整套流程。

**Step 3: Run targeted tests**

Run:
```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent && PYTHONPATH=src python3.11 -m unittest \
  tests.test_request_understanding \
  tests.test_query_planner
```

Expected:
- understanding / planner 相关新增和旧有测试都通过。

### Task 3: Upgrade explanation and advice answer structure

**Files:**
- Modify: `src/doc_ai_agent/advice_engine.py`
- Modify: `src/doc_ai_agent/agent.py`
- Test: `tests/test_agent.py`

**Step 1: Add failing answer-structure tests**

测试 mixed analysis / advice：
- analysis 回答包含稳定段落顺序：结论、原因、依据、建议（有预测时允许插入预测段）
- advice fallback 回答至少包含 `建议：`
- explanation fallback 回答至少包含 `原因：` / `依据：`

**Step 2: Implement minimal formatting layer**

- 给 `AdviceEngine` 增加统一格式化 helper。
- 给 `DocAIAgent._synthesize_node` 增加统一 section formatter。
- 保持原有数据驱动内容，只升级组织方式。

**Step 3: Run targeted tests**

Run:
```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent && PYTHONPATH=src python3.11 -m unittest tests.test_agent
```

Expected:
- `tests.test_agent` 全绿。

### Task 4: Full verification and redeploy

**Files:**
- No code changes expected unless verification发现回归

**Step 1: Run full backend suite**

Run:
```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent && PYTHONPATH=src python3.11 -m unittest \
  tests.test_request_understanding \
  tests.test_quality_benchmark \
  tests.test_query_planner \
  tests.test_forecast_service \
  tests.test_agent
```

Expected:
- 全量后端测试通过。

**Step 2: Restart service**

Run:
```bash
cd /Users/mac/Desktop/personal/doc-cloud && BACKEND_PORT=38117 FRONTEND_PORT=5173 ./scripts/dev-down.sh
cd /Users/mac/Desktop/personal/doc-cloud && BACKEND_PORT=38117 FRONTEND_PORT=5173 ./scripts/dev-up.sh
```

**Step 3: Smoke test local and public**

Run:
```bash
curl -fsS http://127.0.0.1:38117/health
curl -fsS 'https://ai.luyaxiang.com/api/chat' \
  -H 'Content-Type: application/json' \
  -H 'Origin: https://ai.luyaxiang.com' \
  -H 'Referer: https://ai.luyaxiang.com/' \
  -H 'User-Agent: Mozilla/5.0' \
  --data '{"question":"近3个月虫情最高的县有哪些","thread_id":"smoke-semantics-answer-quality"}'
```

Expected:
- health 返回 ok
- 线上返回 `county` + `pest_top`
- 回答结构比此前更清晰
