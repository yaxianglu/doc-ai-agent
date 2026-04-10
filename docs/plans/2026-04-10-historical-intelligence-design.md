# doc-cloud Historical Intelligence Upgrade Design

## Goal
把 `doc-ai-agent` 从“能聊、能查一点数据”的聊天助手，升级成一个更完整的历史数据智能体：
- 能理解带噪声的自然语言需求
- 能把用户问题拆成可执行 plan
- 能精准使用历史数据做结构化分析
- 能基于知识库解释“为什么”与“怎么处置”
- 能结合历史趋势做预测

## Core Principle
**历史数据查询不走 RAG，知识解释和处置建议才走 RAG。**

原因：
- 历史数据来自结构化表，最佳路径是 `NL -> structured plan -> SQL/aggregation`
- RAG 更适合处理农业规则、处置经验、解释性文本、政策条文
- 如果把事实查询也交给 RAG，准确率和可核验性都会下降

## Target Architecture
采用五层架构：

1. **Request Understanding**
   - 从自然语言里提取真正有用的信息
   - 识别 domain / time window / region / metric / output expectations
   - 过滤“我感觉”“我不清楚”“是不是”这类元话语
   - 生成 `execution_plan`

2. **Historical Data Layer**
   - 把 `execution_plan` 映射到结构化 route
   - 历史分析、排行、趋势、对比全部走 `QueryEngine + Repository`
   - 事实结果必须能回溯到 SQL / rule / sample rows

3. **Knowledge Layer (RAG)**
   - 面向“为什么”“怎么处置”“依据是什么”
   - 检索农业规则、经验、处置知识
   - 输出匹配来源、命中词、引用片段

4. **Forecast Layer**
   - 独立 `ForecastService`
   - 历史趋势 -> 区域风险展望 / 未来窗口预测
   - 与事实查询分离，避免把预测逻辑塞进 QueryEngine

5. **Answer Synthesis**
   - LangGraph 统一编排多阶段执行
   - 根据 `execution_plan` 决定是否依次执行：
     - 历史查询
     - 预测
     - RAG
     - 组合回答

## Why This Version
这是市面上更成熟的 Agent 方案：
- **LangGraph** 负责多阶段可控编排
- **Letta** 负责长期记忆
- **Structured Query / tool calling** 负责事实数据
- **RAG** 负责规则知识与解释
- **Forecast service** 负责时间序列外推

相比“全靠聊天模型直接回答”，这套架构更稳定，也更容易验证。

## Scope
### Phase A - Request Understanding
- 新增噪声过滤 / 意图拆解 / 执行计划
- 支持一句话里同时包含：
  - 历史数据查询
  - 预测
  - 原因解释
  - 处置建议

### Phase B - Historical Intelligence
- 历史查询结果附带 `execution_plan`
- 输出“它是怎么理解你这句话的”
- 输出“它为什么选择这条数据链路”

### Phase C - Knowledge RAG
- 新增农业规则知识检索
- 数据问答后可继续解释：
  - 为什么会这样
  - 有什么依据
  - 该怎么处置

### Phase D - Forecast Service
- 新增独立 forecast service
- 支持：
  - 指定地区未来风险展望
  - 指定窗口的高风险区域预测

### Phase E - UI Transparency
- 前端分析面板展示：
  - 执行计划
  - 历史数据链
  - 预测链
  - RAG 命中来源

## Non-Goals
- 这次不做主动预警
- 这次不做复杂在线训练
- 这次不做真正的时间序列模型平台化（先做 deterministic forecast service）

## Files Likely Affected
- `src/doc_ai_agent/agent.py`
- `src/doc_ai_agent/query_planner.py`
- `src/doc_ai_agent/query_engine.py`
- `src/doc_ai_agent/forecast_engine.py`
- `src/doc_ai_agent/advice_engine.py`
- `src/doc_ai_agent/source_provider.py`
- `src/doc_ai_agent/server.py`
- `src/doc_ai_agent/*.py` (new helper modules)
- `tests/*.py`
- `doc-frontend/src/*`
