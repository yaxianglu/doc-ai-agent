# Shared Semantics and Answer Quality Design

## Goal

在不大改主架构的前提下，同时解决三类问题：
1. 语义规则分散，`request_understanding` 与 `query_planner` 存在重复维护。
2. 中文变体问法覆盖不足，导致同义问法命中不稳定。
3. 解释/建议回答更偏“能答对”，还不够“像业务专家”。

## Scope

本轮只做高收益、低风险优化：
- 新增一个共享语义模块，集中维护农业问答里的核心词法/语义判断。
- 让 `request_understanding` 和 `query_planner` 复用共享判断，减少双维护。
- 升级 analysis/advice 输出模板，让回答默认包含更清晰的结论、原因、依据、建议结构。
- 补充变体问法回归测试，优先覆盖“最高/最突出/县有哪些”这类高频表达。

不做的内容：
- 不引入新的外部模型或训练流程。
- 不重写 Query Plan 架构。
- 不做大范围前端改版。

## Design

### 1. Shared Semantics Layer

新增一个轻量共享模块（建议命名 `src/doc_ai_agent/agri_semantics.py`），集中提供：
- 共享词表：排行词、趋势词、概况词、明细词、县级范围词。
- 共享判断函数：
  - `asks_county_scope(text)`
  - `has_ranking_intent(text)`
  - `has_trend_intent(text)`
  - `has_overview_intent(text)`
  - `has_detail_intent(text)`
  - `infer_domain_from_text(text)`（仅在现有逻辑允许时复用，不强推替换全部 domain 逻辑）

目标不是把所有理解逻辑都塞进一个文件，而是把**最容易在两处漂移的规则判断**收拢成单一事实源。

### 2. Robust Variant Handling

共享模块会把高频中文变体纳入统一判断，例如：
- 排行：`最高`、`最突出`、`排前面`、`最靠前`、`最多`
- 县级范围：`哪些县`、`县有哪些`、`哪些区`、`区有哪些`
- 明细：`具体数据`、`详细数据`、`原始数据`
- 概况：`情况`、`概况`、`整体`、`怎么样`

本轮不追求无限泛化，而是把**当前真实 badcase + 同类型高频变体**补齐，并用测试锁住。

### 3. Expert-Style Answer Framing

对 explanation / mixed analysis / advice 回答统一成更稳定的结构：
- `结论：...`
- `原因：...`
- `依据：...`
- `建议：...`

实现上分两层：
- `AdviceEngine`：无论 rule 还是 llm，统一输出结构化段落，而不是散句。
- `DocAIAgent._synthesize_node`：analysis 模式下统一拼装 section，保证历史数据、原因、预测、依据、建议的顺序一致。

### 4. Testing Strategy

TDD 增加三类回归：
- 共享语义单测：验证变体表达能命中同一语义。
- planner / understanding 回归：验证共享语义在两个入口行为一致。
- answer quality 回归：验证 mixed analysis 和 advice 回答包含明确的结构化段落。

## Risks and Mitigations

- 风险：共享语义模块过度抽象，反而让原逻辑更绕。
  - 规避：只抽“共享词法判断”，不抽整个理解流程。
- 风险：回答模板过于机械。
  - 规避：统一段落名，但段落内容继续保留数据驱动差异。
- 风险：补词表引入误判。
  - 规避：先写失败测试，再跑全量后端回归。

## Success Criteria

- `request_understanding` 与 `query_planner` 共享关键语义判断，不再各自维护县级范围/排行等高频规则。
- `近3个月虫情最高的县有哪些` 这类问法稳定走 `county + ranking`。
- mixed analysis / advice 回答默认带明确段落，读起来更像业务专家总结。
- 后端回归保持全绿，并重新部署到 `ai.luyaxiang.com`。
