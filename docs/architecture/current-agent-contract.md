# Current Agent Contract

当前 `doc-ai-agent` 的稳定契约，作为 V2 架构迁移的基线。

## Request Contract

- 对话入口：`POST /chat`
- 请求字段：
  - `question`
  - `history`（可选）
  - `thread_id`（可选）

## Core Runtime Contract

- 请求理解输出至少包含：
  - `intent`
  - `task_type`
  - `domain`
  - `window`
  - `future_window`
  - `region_name`
  - `region_level`
  - `needs_historical`
  - `needs_forecast`
  - `needs_explanation`
  - `needs_advice`
- 规划输出至少包含：
  - `route`
  - `query_plan`
  - `task_graph`
  - `reason`
  - `context_trace`

## Response Contract

- 响应字段：
  - `mode`
  - `answer`
  - `data`
  - `evidence`
  - `processing`
- `evidence` 至少保留：
  - `request_understanding`
  - `historical_query`
  - `task_graph`
  - `memory_state`
  - `response_meta`

## Regression Gate

- 主回归门：`evals/strict_acceptance_140.json`
- 推荐脚本：
  - `scripts/run_strict_acceptance_eval.py --score --compare`
- 任何 V2 迁移都必须：
  - 不破坏现有响应字段
  - 不降低 140 题严格评测的核心表现
