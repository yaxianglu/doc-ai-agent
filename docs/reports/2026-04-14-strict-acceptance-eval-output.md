# 严格 50 题评测输出说明

## 目标

本文档用于说明当前 `doc-ai-agent` 严格 50 题评测的：

- 题库来源
- 运行方式
- 输出目录
- 自动评分逻辑
- 对比逻辑
- 当前最新结果
- 后续使用方式

这份文档面向开发、测试、上线验收三类场景，目的是让评测从“临时跑一次”变成“可以稳定复现和对比”的工程能力。

## 题库

- 固定题库文件：`evals/strict_acceptance_50.json`
- 当前题库规模：`50` 题
- 题目分组：
  - 基础查询
  - 区域粒度
  - 时间理解
  - 趋势分析
  - 预测能力
  - 原因解释
  - 建议能力
  - 设备明细
  - 异常与空数据
  - 多轮上下文

固定题库的意义：

- 不再从历史运行结果里反向抽题
- 每次评测输入一致
- 可以稳定对比不同版本的分数变化

## 运行入口

### 1. 直接跑完整 strict eval

```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent
PYTHONPATH=src python3.11 scripts/run_strict_acceptance_eval.py --score --compare
```

说明：

- 会读取固定题库
- 会执行 50 题
- 会自动生成原始结果、评分结果、markdown 报告
- 如果 baseline 存在，会自动生成 comparison 报告

### 2. 基于已有 raw 结果重新评分

```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent
PYTHONPATH=src python3.11 scripts/run_strict_acceptance_eval.py \
  --score \
  --compare \
  --baseline output/evals/baseline/scored.json \
  --from-raw output/acceptance_run_final_2026-04-14.json
```

适用场景：

- raw 结果已经跑完，不想重复调用 agent
- 只调整了评分规则
- 想重算 baseline / latest / comparison

### 3. 单独评分已有 raw 文件

```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent
PYTHONPATH=src python3.11 scripts/score_strict_acceptance_eval.py \
  output/acceptance_run_final_2026-04-14.json \
  output/evals/manual-score
```

### 4. 单独对比两个 scored 文件

```bash
cd /Users/mac/Desktop/personal/doc-cloud/doc-ai-agent
PYTHONPATH=src python3.11 scripts/compare_acceptance_eval.py \
  output/evals/latest/scored.json \
  output/evals/baseline/scored.json \
  output/evals/latest/comparison.md
```

## 输出目录

### 最新结果

- 原始结果：`output/evals/latest/raw.json`
- 自动评分：`output/evals/latest/scored.json`
- 评分报告：`output/evals/latest/report.md`
- 对比报告：`output/evals/latest/comparison.md`

### 基线结果

- 当前基线评分：`output/evals/baseline/scored.json`
- 当前基线报告：`output/evals/baseline/report.md`

### 按时间归档

每次运行会生成时间戳目录，例如：

- `output/evals/20260414-103101/raw.json`
- `output/evals/20260414-103101/scored.json`
- `output/evals/20260414-103101/report.md`
- `output/evals/20260414-103101/comparison.md`

这样可以保留历史记录，同时 `latest/` 始终指向最近一次结果。

## 自动评分逻辑

评分实现位置：`src/doc_ai_agent/acceptance_eval.py`

当前自动评分重点检查：

### 1. 运行正确性

- 是否 `ok=true`
- 是否有非空回答
- 是否超慢

### 2. 语义/路由错误

- `报警/预警` 问题答成 `墒情异常最多`
- 明显数据题被误打到 `advice`

### 3. 墒情方向错误

- `低墒/偏低/缺水` 问题答成 `高墒`

### 4. 预测证据完整性

- 是否包含 `置信度`
- 是否包含 `依据`
- 是否包含 `样本覆盖`

### 5. 原因解释完整性

- 是否有 `原因`
- 是否有数据化依据
- 是否有 `待核查` / 下一步核验点

## 自动评分的边界

自动评分不是最终人工验收替代物，主要作用是：

- 发现明显回退
- 保证关键红线不失手
- 让版本间对比有稳定门槛

当前自动评分已对两类“合理澄清”做豁免，不再误伤：

- 占位问法：如 `某县`、`某设备`、`这个县`
- 领域澄清：如 `过去5个月最严重的是哪里？`

## 当前最新结果

当前最新评分报告来源：

- `output/evals/latest/report.md`
- `output/evals/latest/comparison.md`

本次最新自动评分摘要：

- 总题数：`50`
- 自动评分均分：`9.58`
- 低于 7 分：`2` 题
- 相比 baseline 平均分变化：`+0.01`
- 明确提升题：`1` 题
- 明确回退题：`0` 题

### 当前自动评分下的主要残留问题

1. `最近30天预警最多的是哪些地区？`
   - 自动评分：`6.5`
   - 仍被判定存在 `alert_domain_mismatch`

2. `最近10天报警最多的是哪里？`
   - 自动评分：`6.5`
   - 仍被判定存在 `alert_domain_mismatch`

3. 预测类的局部问题仍在：
   - `常州市未来两周虫情趋势如何？`
   - `未来10天哪些县风险最高？`
   - `那未来两周呢？`
   - 主要扣分点：`forecast_missing_sample_coverage` / `forecast_missing_evidence`

4. 原因解释类虽然明显提升，但仍有若干题因为未显式写出 `待核查项` 被轻扣：
   - `为什么最近虫情变严重了？`
   - `过去两个月虫情上升的主要原因是什么？`
   - `为什么同一个市里不同县差异这么明显？`
   - `从数据看，这次异常最可能的原因是什么？`
   - `为什么会出现“未知区域”？`
   - `为什么会这样？`

### 对比结论

- 这套自动评分链路已经可以稳定工作
- 第一批红线修复已被 eval 捕捉到
- 后续可以继续围绕低分题做小步迭代，再持续对比分数变化

## CI 使用方式

CI workflow：

- `.github/workflows/strict-acceptance-eval.yml`

当前包含两层：

1. `eval-plumbing`
   - 只检查题库、评分器、对比器这些“评测基础设施”
   - 适合 PR 默认跑

2. `strict-live-eval`
   - 依赖密钥与数据库
   - 当 `OPENAI_API_KEY` 和 `DOC_AGENT_DB_URL` 存在时执行
   - 适合手动触发或有条件启用

## 推荐使用规范

建议每次涉及以下改动，都至少跑一次 strict eval：

- `RequestUnderstanding`
- `QueryPlanner`
- `QueryEngine`
- `ForecastService`
- `AgentAnalysisSynthesis`
- 题库与评分规则

推荐流程：

1. 先跑单测
2. 再跑 strict eval
3. 看 `report.md`
4. 看 `comparison.md`
5. 只要有回退题，就先处理再提交

## 相关文件索引

### 题库与评分

- 题库：`evals/strict_acceptance_50.json`
- 评分模块：`src/doc_ai_agent/acceptance_eval.py`

### 脚本

- 主运行器：`scripts/run_strict_acceptance_eval.py`
- 评分器：`scripts/score_strict_acceptance_eval.py`
- 对比器：`scripts/compare_acceptance_eval.py`
- 旧 acceptance 运行器：`scripts/run_acceptance_suite.py`

### 测试

- `tests/test_acceptance_eval.py`
- `tests/test_question_suite.py`
- `tests/test_query_planner.py`
- `tests/test_query_engine.py`
- `tests/test_agent.py`

### 报告

- 最新评分报告：`output/evals/latest/report.md`
- 最新对比报告：`output/evals/latest/comparison.md`
- 严格人工 rubric：`docs/reports/2026-04-12-strict-eval-rubric.md`

## 下一步建议

如果继续推进，建议按下面顺序：

1. 继续修 `报警/预警` 残留串线
2. 修预测类 `sample coverage / evidence` 缺失
3. 统一解释类 `待核查项` 模板
4. 再跑一次 live 50 题，刷新 `latest`
