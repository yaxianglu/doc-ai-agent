# doc-cloud Phase 1 and 2 Upgrade Design

## Goal
在现有 `doc-ai-agent + doc-frontend` 基础上，把系统从“SQL/规则问答 MVP”升级成真正具备编排与记忆的农业数据智能体：支持更强的多轮上下文、线程级记忆、历史数据预测，以及基于数据上下文的处置建议。

## Chosen Approach
采用“保留现有 API / UI 外壳，但真实接入 LangGraph + Letta”的方案：
- 保留现有 HTTP API 与前端聊天壳子，避免把已可用链路推倒重来。
- 后端升级为四层能力：
  1. **LangGraph Orchestration**：统一 `load_memory -> plan -> query/forecast/advice/clarify -> persist_memory`。
  2. **Thread Memory**：前端会话 `thread_id` 直通后端；LangGraph checkpoint 负责短期线程状态。
  3. **Letta-backed Long-term Memory**：优先用 Letta block 存持久上下文；未配置时自动回退到本地 JSON memory store。
  4. **Forecast + Contextual Advice**：预测和建议都消费结构化分析上下文，不再只看单轮 question。

## Why This Version
- 用户现在最痛的问题就是“agent 很弱、会失忆、不会预测、建议空泛”。
- 用户已经明确要求不要只做原地微调，而是要把 LangGraph / Letta 真正整进来。
- 这版既满足框架级升级，又保留可测、可运行、可回退的工程稳定性。

## Scope
### Phase 1 - Dialogue Memory
- LangGraph 线程编排
- 多轮 follow-up 继承：domain / region / time window / intent / query family
- 支持短追问：`虫情`、`徐州市呢`、`未来两周呢`、`给建议`
- 后端返回 `context_trace`，解释这次为什么这么理解
- 前端 `thread_id` 全链路透传

### Phase 2 - Prediction + Advice
- 新增预测类 query：虫情预测、墒情预测、区域风险展望
- 基于历史趋势做未来窗口风险评分和等级判断
- 建议生成使用分析上下文与预测结果，不再只是 question 文本匹配
- 处理链上显式暴露 `LangGraph` / `Memory backend`

## Non-Goals
- 今晚不做定时主动汇报/巡检（Phase 3）
- 今晚不做 Letta server 运维与部署自动化
- 今晚不重写前端信息架构，只做必要适配

## Files Likely Affected
- `doc-ai-agent/src/doc_ai_agent/query_planner.py`
- `doc-ai-agent/src/doc_ai_agent/agent.py`
- `doc-ai-agent/src/doc_ai_agent/letta_memory.py`
- `doc-ai-agent/src/doc_ai_agent/forecast_engine.py`
- `doc-ai-agent/src/doc_ai_agent/query_engine.py`
- `doc-ai-agent/src/doc_ai_agent/advice_engine.py`
- `doc-ai-agent/src/doc_ai_agent/server.py`
- `doc-ai-agent/tests/*.py`
- `doc-frontend/src/*` (thread_id / analysis panel minimal adaptation)
