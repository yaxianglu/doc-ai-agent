# Semantic Understanding V2 Design

**Status:** Approved for planning

**Goal:** 将当前分散在规则、路由、理解与规划层中的语言理解逻辑，收敛为一个稳定、可解释、可评测的统一语义中间层。

**Why Now**

当前项目已经具备较强业务能力，但语言理解链路仍有三个结构性问题：

1. **判断分散**：`request_understanding`、`intent_router`、`query_planner` 都在做语义判断，边界问题容易重复修补。
2. **缺少统一仲裁**：越界问题、身份问题、泛解释问题、澄清问题没有单一出口，导致策略容易漂移。
3. **评测难以收口**：60 题能测出效果，但很难从“退化是哪个理解层造成的”直接定位根因。

本次 V2 不追求“全模型替代规则”，而是优先追求企业级系统更重要的三个属性：**稳定、可解释、可迭代**。

---

## Current State

当前语言理解主干大致如下：

- `src/doc_ai_agent/request_understanding.py`
  - 负责上下文补全、噪声清理、实体抽取融合、任务类型推断
- `src/doc_ai_agent/request_understanding_backend.py`
  - 使用 `Instructor + OpenAI` 做结构化抽取
- `src/doc_ai_agent/entity_extraction.py`
  - 使用规则抽取，HanLP 作为可选增强
- `src/doc_ai_agent/intent_router.py`
  - 使用 LLM 做 `intent/query_type` 路由
- `src/doc_ai_agent/query_planner.py`
  - 仍然包含大量语义判断、边界判断与澄清策略

问题不在于某一层“做错了”，而在于它们都在做一部分理解，导致理解责任没有真正单点收口。

---

## Target Architecture

### 1. Unified Semantic Parse Result

新增统一结构 `SemanticParseResult`，作为语言理解层唯一可信输出。建议字段：

- `original_query`
- `normalized_query`
- `resolved_query`
- `domain`
- `intent`
- `task_type`
- `region_name`
- `region_level`
- `historical_window`
- `future_window`
- `device_code`
- `is_out_of_scope`
- `needs_clarification`
- `clarification_reason`
- `confidence`
- `fallback_reason`
- `trace`

这意味着后续模块不再重复“猜”语义，而是消费已经定型的语义结果。

### 2. Semantic Parser as Orchestrator

新增 `semantic_parser.py` 作为新主编排器，职责如下：

1. 输入规范化
2. 多轮上下文补全
3. 本地 slot 抽取
4. LLM 结构化抽取
5. 仲裁与置信度计算
6. 输出 `SemanticParseResult`

`request_understanding.py` 保留为兼容适配层，内部逐步转调 `semantic_parser.py`。

### 3. Single Arbitration Layer

新增 `semantic_judger.py`，集中处理这些高风险分支：

- 问候语
- 身份问题
- 越界问题（天气、新闻、车票等）
- 泛解释问题
- 低信号问题
- 待澄清问题

原则是：**这些判断只允许在一处发生。**

### 4. Planner Becomes Consumer

`query_planner.py` 的职责从“理解 + 规划”调整为“基于 parse result 做执行规划”。

它应当只负责：

- 生成 route
- 生成 query plan
- 生成 answer mode
- 保留 execution trace

它不再负责重复判断是否越界、是否泛解释、是否该澄清。

---

## Confidence Strategy

V2 必须加统一置信度策略，否则“结构统一”之后仍然难以稳定落地。

建议分三层：

- **高置信度（>= 0.8）**
  - 直接执行
- **中置信度（0.5 ~ 0.79）**
  - 允许执行，但必须带 `fallback_reason` 或显式 trace
- **低置信度（< 0.5）**
  - 优先澄清，不直接查数

对于越界问题，判定不依赖“数据意图分数”，而依赖独立的 `is_out_of_scope` 判断结果。

---

## Model Usage Strategy

V2 不建议改成“完全依赖大模型”，而是采用以下策略：

- **规则**：负责高确定性 slot 与硬边界
- **LLM 结构化抽取**：负责领域、任务、时间窗、复杂句式理解
- **向量检索/embedding**：负责知识召回，不负责最终语义仲裁
- **HanLP**：继续作为可选增强，不作为主决策中心

也就是说，Transformer 能力仍然重要，但位置应当是：

- 强化 `semantic parse`
- 支撑语义召回
- 不直接替代整个策略层

---

## Evaluation Strategy

现有 60 题保留，并进一步拆成四个子集：

- `ood_eval.json`
- `explanation_eval.json`
- `forecast_eval.json`
- `context_eval.json`

每次改动至少输出：

- 总分
- 各子集分
- 低分题列表
- 与上次基线对比

这样就能看出是“解释退化了”还是“越界判断退化了”，而不是只有一个平均分。

---

## Rollout Strategy

采用三阶段渐进替换，避免一次性重构带来不可控回归：

### Phase 1: Introduce the Contract

- 新增 `SemanticParseResult`
- 新增 `semantic_parser.py`
- 保持旧链路不删，仅做并行接入与 trace 输出

### Phase 2: Migrate Special Cases

- 先迁移最容易失手的场景：
  - OOD
  - identity / greeting
  - generic explanation
  - clarification

### Phase 3: Planner Simplification

- `query_planner.py` 开始只消费 parse result
- 删除重复判断
- 让语言理解责任真正单点收口

---

## Risks

- **风险 1：双轨期行为不一致**
  - 对策：在过渡期保留 trace，比对旧链路与新链路差异
- **风险 2：Planner 迁移后出现隐性回归**
  - 对策：60 题 + 子集评测 + targeted unittest 同时跑
- **风险 3：过度抽象导致开发变慢**
  - 对策：只收口语义判断，不一次性重写执行层

---

## Success Criteria

视为 V2 成功的标准：

- 60 题总分稳定在 `9.8+`
- OOD、异常解释、多轮上下文不再反复回退
- `query_planner.py` 不再承担主要语义理解责任
- 每次回答都能通过 `trace / fallback_reason / confidence` 解释“为什么这样答”
- 新增理解场景时，通常只改 `semantic_parser` 或 `semantic_judger`

---

## Recommended Next Step

下一步进入实施计划，按以下优先级推进：

1. 定义 `SemanticParseResult`
2. 搭建 `semantic_parser.py`
3. 收口 OOD / explanation / clarification
4. 简化 `query_planner.py`
5. 拆分 eval 并固化回归流程

