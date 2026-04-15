# Query DSL

`QueryDSL` 是 V2 架构迁移里的统一中间表示，用来连接：

- Request Understanding
- Router
- Planner
- Orchestrator

## Core Shape

```json
{
  "domain": "pest",
  "intent": ["data_query"],
  "task_type": "ranking",
  "region": {
    "name": "常州市",
    "level": "county"
  },
  "historical_window": {
    "kind": "history",
    "window_type": "months",
    "window_value": 3
  },
  "future_window": {
    "kind": "future",
    "window_type": "weeks",
    "window_value": 2,
    "horizon_days": 14
  },
  "follow_up": false,
  "followup_type": "none",
  "needs_clarification": false,
  "capabilities": ["data_query", "forecast"],
  "confidence": 0.92
}
```

## Design Rules

- Parser 负责产出 `QueryDSL`
- Router 负责基于 `QueryDSL` 选择 capabilities
- Planner 只消费 `QueryDSL`，不重复猜语义
- V2 迁移期间，允许旧的 `understanding` 字典与 `QueryDSL` 并存
