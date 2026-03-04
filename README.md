# doc-ai-agent

面向“指挥调度报表”场景的 AI-Agent MVP，支持：
- 基于真实数据的可核验问答（统计、Top5）
- 建议类问答（MVP 内置规则，后续可接联网检索）
- 周期刷新（默认 5 分钟扫描一次数据目录）

## 目录结构

```text
src/doc_ai_agent/
  config.py
  xlsx_loader.py
  repository.py
  query_engine.py
  advice_engine.py
  agent.py
  server.py
scripts/run_server.py
tests/
```

## 快速启动

```bash
cd /Users/mac/Desktop/code/service/doc-ai-agent
set -a && source .env.local && set +a
PYTHONPATH=src python3 scripts/run_server.py
```

可选环境变量：
- `DOC_AGENT_DATA_DIR`：xlsx 文件目录，默认 `.`  
- `DOC_AGENT_DB_PATH`：sqlite 文件路径，默认 `./data/alerts.db`
- `DOC_AGENT_REFRESH_MINUTES`：刷新周期（分钟），默认 `5`
- `DOC_AGENT_PORT`：监听端口，默认 `8000`
- `OPENAI_API_KEY`：OpenAI API Key（配置后启用大模型）
- `OPENAI_BASE_URL`：默认 `https://api.openai.com/v1`
- `OPENAI_ROUTER_MODEL`：路由/参数抽取模型，默认 `gpt-4.1-mini`
- `OPENAI_ADVICE_MODEL`：建议生成模型，默认 `gpt-4.1`
- `OPENAI_TIMEOUT_SECONDS`：请求超时，默认 `30`
- `DOC_AGENT_SOURCE_CATALOG`：建议知识源 JSON 文件路径，默认 `./data/knowledge_sources.json`

示例：

```bash
export OPENAI_API_KEY="sk-xxxx"
export OPENAI_ROUTER_MODEL="gpt-4.1-mini"
export OPENAI_ADVICE_MODEL="gpt-4.1"
PYTHONPATH=src python3 scripts/run_server.py
```

## API

### 1) 健康检查

```bash
curl -s http://127.0.0.1:8000/health
```

### 2) 手动刷新数据

```bash
curl -s -X POST http://127.0.0.1:8000/refresh -H 'Content-Type: application/json' -d '{}'
```

### 3) 对话问答

```bash
curl -s -X POST http://127.0.0.1:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"question":"2026年以来指挥调度平台发生了多少预警信息？"}'
```

返回包含：
- `answer`：中文结论
- `data`：结构化结果
- `evidence`：SQL 模板、时间窗口、样本明细（便于核验）

## 模型使用说明

- 数据问答：大模型只做“意图路由+查询参数抽取”，真实结果仍由数据库查询返回，避免幻觉。
- 建议问答：由大模型生成处置建议；未配置 `OPENAI_API_KEY` 时自动回退到本地规则建议。
- 建议来源：优先从 `DOC_AGENT_SOURCE_CATALOG` 里按关键词检索引用来源，再交给模型生成建议。

## 测试

```bash
cd /Users/mac/Desktop/code/service/doc-ai-agent
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
