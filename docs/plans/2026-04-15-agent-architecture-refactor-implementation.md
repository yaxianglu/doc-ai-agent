# Agent Architecture Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the current agent architecture to reduce duplicated parsing, implicit backend contracts, and orchestration coupling while preserving the current API and strict-eval behavior.

**Architecture:** The implementation is incremental. First freeze `RequestUnderstanding` as the single semantic source of truth and make `QueryPlanner` consume normalized state instead of re-parsing raw questions. Next introduce explicit repository and facade boundaries. Finally slim `DocAIAgent` so orchestration depends on public contracts rather than planner internals.

**Tech Stack:** Python 3.11, LangGraph, unittest, existing `QueryDSL` and capability layers, strict acceptance eval scripts.

---

### Task 1: Freeze the parse boundary

**Files:**
- Modify: `src/doc_ai_agent/request_understanding.py`
- Modify: `src/doc_ai_agent/query_parser.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Test: `tests/test_request_understanding.py`
- Test: `tests/test_query_parser.py`
- Test: `tests/test_query_planner.py`

**Implementation notes:**
- Ensure `RequestUnderstanding.analyze()` always emits a complete `parsed_query` and `canonical_understanding`.
- Make `QueryParser` a thin compatibility adapter around `RequestUnderstanding`, not a second semantic entry point.
- Change `QueryPlanner.plan()` to trust `understanding["parsed_query"]` and only fall back when that payload is absent.

**Step 1: Write the failing planner-boundary tests**

- Add tests asserting:
  - planner does not invoke a secondary parse when `understanding["parsed_query"]` is present
  - planner still works when `parsed_query` is missing and compatibility fallback is needed
  - request understanding emits `parsed_query` and `canonical_understanding` together

**Step 2: Run the targeted tests to confirm current gaps**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_request_understanding tests.test_query_parser tests.test_query_planner -v`

Expected: at least one new assertion fails before implementation.

**Step 3: Implement the minimal parsing-boundary change**

- Keep all current response fields intact.
- Remove duplicate planner-side parsing from the happy path.
- Preserve fallback behavior for legacy or incomplete understanding payloads.

**Step 4: Re-run the targeted tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_request_understanding tests.test_query_parser tests.test_query_planner -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/request_understanding.py src/doc_ai_agent/query_parser.py src/doc_ai_agent/query_planner.py tests/test_request_understanding.py tests/test_query_parser.py tests/test_query_planner.py
git commit -m "refactor: freeze request understanding boundary"
```

### Task 2: Replace planner-private agent coupling with public helpers

**Files:**
- Modify: `src/doc_ai_agent/query_planner.py`
- Modify: `src/doc_ai_agent/agent.py`
- Modify: `src/doc_ai_agent/agent_orchestration.py`
- Test: `tests/test_agent_orchestration.py`
- Test: `tests/test_agent.py`

**Implementation notes:**
- Add public planner helpers where the agent currently reaches into `_finalize_plan`, `_extract_top_n`, or `_build_route`.
- Keep semantics unchanged; this task is about dependency direction, not behavior redesign.

**Step 1: Write the failing coupling tests**

- Add tests asserting:
  - `DocAIAgent` uses public planner APIs only
  - explicit `top_n` override still survives planning
  - direct forecast plan repair still produces the same execution behavior

**Step 2: Run the focused orchestration tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent_orchestration tests.test_agent -v`

Expected: new tests fail before the API cleanup.

**Step 3: Implement public planner entry points**

- Promote the agent-used planner helpers into stable public methods.
- Update `DocAIAgent` to stop calling private planner methods directly.

**Step 4: Re-run the focused tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent_orchestration tests.test_agent -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/query_planner.py src/doc_ai_agent/agent.py src/doc_ai_agent/agent_orchestration.py tests/test_agent_orchestration.py tests/test_agent.py
git commit -m "refactor: remove planner private coupling from agent"
```

### Task 3: Introduce an explicit analytics repository contract

**Files:**
- Modify: `src/doc_ai_agent/repository.py`
- Modify: `src/doc_ai_agent/mysql_repository.py`
- Create: `src/doc_ai_agent/repository_contracts.py`
- Test: `tests/test_repository.py`
- Test: `tests/test_mysql_auth_repository.py`

**Implementation notes:**
- Define a focused Protocol for the query and forecast operations used on the main path.
- Start with the methods already shared in practice by SQLite and MySQL implementations.
- Do not widen the contract to every backend-specific helper on day one.

**Step 1: Write contract tests**

- Add tests asserting both repository implementations satisfy the new Protocol shape for required operations.
- Add tests for any adapter or normalization shim introduced by the contract.

**Step 2: Run repository-focused tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_repository tests.test_mysql_auth_repository -v`

Expected: FAIL until the Protocol and implementations line up.

**Step 3: Implement the Protocol and align repositories**

- Create `repository_contracts.py` with the shared Protocol.
- Update repository modules to type against the Protocol.
- Keep backend-specific behavior behind separate methods or adapters.

**Step 4: Re-run repository-focused tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_repository tests.test_mysql_auth_repository -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/repository_contracts.py src/doc_ai_agent/repository.py src/doc_ai_agent/mysql_repository.py tests/test_repository.py tests/test_mysql_auth_repository.py
git commit -m "refactor: add analytics repository protocol"
```

### Task 4: Remove `hasattr(...)` discovery from query and forecast services

**Files:**
- Modify: `src/doc_ai_agent/query_engine.py`
- Modify: `src/doc_ai_agent/forecast_service.py`
- Modify: `src/doc_ai_agent/capabilities/data_query.py`
- Modify: `src/doc_ai_agent/capabilities/forecast.py`
- Test: `tests/test_query_engine.py`
- Test: `tests/test_forecast_service.py`

**Implementation notes:**
- Migrate standard behavior to the repository Protocol from Task 3.
- Leave only deliberate optional behavior behind explicit adapter checks if still needed.
- Preserve answer payloads and evidence fields.

**Step 1: Write the failing service-boundary tests**

- Add tests asserting standard query and forecast flows no longer depend on backend feature discovery by `hasattr(...)`.
- Add tests for any explicit optional-adapter fallback that remains.

**Step 2: Run the service tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_engine tests.test_forecast_service -v`

Expected: FAIL before service cleanup.

**Step 3: Implement the service refactor**

- Type services against the repository Protocol.
- Replace repeated dynamic checks with explicit contract calls.
- Keep capability result shapes unchanged.

**Step 4: Re-run the service tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_query_engine tests.test_forecast_service -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/query_engine.py src/doc_ai_agent/forecast_service.py src/doc_ai_agent/capabilities/data_query.py src/doc_ai_agent/capabilities/forecast.py tests/test_query_engine.py tests/test_forecast_service.py
git commit -m "refactor: align query and forecast services to repository contract"
```

### Task 5: Make `AccessFacade` a real dependency boundary

**Files:**
- Modify: `src/doc_ai_agent/access_facade.py`
- Modify: `src/doc_ai_agent/advice_engine.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Modify: `src/doc_ai_agent/query_planner.py`
- Test: `tests/test_source_provider.py`
- Test: `tests/test_agent_execution_nodes.py`
- Test: `tests/test_query_planner.py`

**Implementation notes:**
- Decide one direction and follow it consistently:
  - either expand `AccessFacade` and route retrieval/playbook access through it
  - or remove redundant surface area if direct access is preferred
- Recommended: expand it and make it the explicit dependency boundary.

**Step 1: Write the failing boundary tests**

- Add tests asserting:
  - advice retrieval uses facade methods rather than raw provider access
  - knowledge node uses the same facade contract
  - planner playbook access goes through the chosen boundary consistently

**Step 2: Run the focused boundary tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_source_provider tests.test_agent_execution_nodes tests.test_query_planner -v`

Expected: FAIL before the dependency cleanup.

**Step 3: Implement the facade consolidation**

- Align advice, planner, and execution modules to one boundary.
- Preserve current backend summary evidence and retrieval behavior.

**Step 4: Re-run the focused tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_source_provider tests.test_agent_execution_nodes tests.test_query_planner -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/access_facade.py src/doc_ai_agent/advice_engine.py src/doc_ai_agent/agent_execution_nodes.py src/doc_ai_agent/query_planner.py tests/test_source_provider.py tests/test_agent_execution_nodes.py tests/test_query_planner.py
git commit -m "refactor: consolidate access facade boundary"
```

### Task 6: Slim `DocAIAgent` into a coordinator

**Files:**
- Modify: `src/doc_ai_agent/agent.py`
- Modify: `src/doc_ai_agent/agent_execution_nodes.py`
- Modify: `src/doc_ai_agent/agent_runtime_context.py`
- Modify: `src/doc_ai_agent/agent_synthesis_orchestration.py`
- Test: `tests/test_agent.py`
- Test: `tests/test_agent_execution_nodes.py`
- Test: `tests/test_agent_contracts.py`

**Implementation notes:**
- Extract route normalization, synthesis-prep, and node-specific logic out of `DocAIAgent` where possible.
- Keep graph topology stable unless there is a clear correctness win.
- Preserve response evidence and memory-state fields.

**Step 1: Write the failing coordinator-shape tests**

- Add tests asserting:
  - node-specific logic can be exercised outside `DocAIAgent`
  - orchestration still emits the same response contract
  - memory persistence and response metadata remain unchanged

**Step 2: Run the focused agent tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent tests.test_agent_execution_nodes tests.test_agent_contracts -v`

Expected: FAIL before extraction.

**Step 3: Implement the coordinator slimming**

- Move extractable logic behind public helpers or execution-node utilities.
- Keep `DocAIAgent` focused on state handoff, graph invocation, and final attachment steps.

**Step 4: Re-run the focused agent tests**

Run: `PYTHONPATH=src python3.11 -m unittest tests.test_agent tests.test_agent_execution_nodes tests.test_agent_contracts -v`

Expected: PASS.

**Step 5: Commit**

```bash
git add src/doc_ai_agent/agent.py src/doc_ai_agent/agent_execution_nodes.py src/doc_ai_agent/agent_runtime_context.py src/doc_ai_agent/agent_synthesis_orchestration.py tests/test_agent.py tests/test_agent_execution_nodes.py tests/test_agent_contracts.py
git commit -m "refactor: slim agent orchestration core"
```

### Task 7: Run the full regression gate

**Files:**
- Modify: `docs/plans/2026-04-15-agent-architecture-refactor-design.md`
- Modify: `docs/plans/2026-04-15-agent-architecture-refactor-implementation.md`
- Optional output: `output/evals/latest/`

**Implementation notes:**
- This task is verification and documentation only.
- Record any architecture adjustments discovered during execution.

**Step 1: Run the full unit test suite**

Run: `PYTHONPATH=src python3.11 -m unittest`

Expected: PASS.

**Step 2: Run the strict eval gate**

Run: `DOC_AGENT_MEMORY_STORE_PATH=./output/eval-memory-architecture-refactor.json PYTHONPATH=src python3.11 scripts/run_strict_acceptance_eval.py --score --compare`

Expected: no regression on the strict 140-case gate; investigate any score drop before merging.

**Step 3: Update the plan docs with findings if needed**

- Note any deviations from the original refactor sequence.
- Document any permanent adapter kept for compatibility.

**Step 4: Commit verification notes**

```bash
git add docs/plans/2026-04-15-agent-architecture-refactor-design.md docs/plans/2026-04-15-agent-architecture-refactor-implementation.md
git commit -m "docs: record architecture refactor verification notes"
```

---

## Execution Notes

### 2026-04-15 progress snapshot

- Task 1–6 对应的聚焦测试已通过，说明以下重构已经落地：
  - `RequestUnderstanding` 与 `QueryPlanner` 的解析边界收紧
  - Agent 对 planner 私有 helper 的直接耦合已替换为公共入口
  - `repository_contracts.py` 已引入显式协议
  - `QueryEngine` / `ForecastService` 主路径已迁移到协议化访问
  - `AccessFacade` 已被 advice / planner / knowledge node 使用
  - `DocAIAgent` 已把部分节点逻辑下沉到 execution helpers

### Verification findings

- 计划原文中的全量单测命令 `PYTHONPATH=src python3.11 -m unittest` 在当前仓库里会得到 `Ran 0 tests`。
- 实际可用的全量单测命令为：

```bash
PYTHONPATH=src python3.11 -m unittest discover -s tests -v
```

- 2026-04-15 执行 Task 7 时发现一个真实兼容性回归：
  - `QueryEngine` 之前用过宽的 `MonitoringRepository` runtime protocol 识别结构化 repo
  - 某些只实现 `pest / soil / joint_risk` 主路径、但未实现 `available_*` 方法的 repo stub 会被误判为“不支持结构化查询”
  - 结果导致全量回归中的 `tests.test_low_score_regressions` 6 个用例报错
- 已修复方式：
  - 在 `repository_contracts.py` 中把查询侧监测契约拆成更细的 `PestQueryRepository`、`SoilQueryRepository`、`JointRiskRepository`
  - 把 `available_pest_time_range` / `available_soil_time_range` 作为可选 availability protocol 处理
  - `QueryEngine` 改为按 query type 选择更细的契约，而不是用一个过宽协议拦住所有结构化查询

### Current gate status

- 全量单测：PASS（`434` tests，`4` skipped）
- strict eval：
  - 一次运行得到平均分 `8.27`
  - 修复兼容性回归后再次运行得到平均分 `8.09`
- 当前 blocker：
  - strict eval 仍有多轮上下文 / 县级追问项回退到保守澄清，尚不能把 Task 7 视为完全完成
  - 受影响较明显的题号包括：`47`、`48`、`121`、`139`、`140`
