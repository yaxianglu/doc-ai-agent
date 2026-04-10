# Request Understanding Upgrade Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the current brittle regex-only question understanding path with a layered understanding pipeline that preserves user intent, keeps region/time slots stable, and stops rewriting overview questions into ranking questions.

**Architecture:** Keep the existing `RequestUnderstanding` entrypoint, but split it into three layers: context resolution, structured extraction, and deterministic fallback normalization. The new structured extraction path uses an Instructor-backed schema to classify domain, task type, region, and windows; the deterministic layer remains as a high-availability fallback and as a guardrail for slots like city aliases and short follow-up resolution.

**Tech Stack:** `Instructor`, `openai`, `pydantic`, existing `LangGraph`, existing playbook/query engine.

---

## Problem

The current implementation in `src/doc_ai_agent/request_understanding.py` rewrites many agri questions into a single ranking template such as “过去5个月虫情最严重的地方是哪里”. That is acceptable for some ranking prompts, but it breaks overview prompts like “给我过去五个月徐州的虫害情况” by dropping the region and changing the task semantics.

The bug is architectural, not cosmetic:

- The UI shows `normalized_question`, which is currently planner-oriented rather than user-faithful.
- The planner and query engine still treat many `structured_agri` questions as ranking by default.
- The existing path has no explicit task type such as `ranking`, `trend`, or `region_overview`.

## Target Behavior

For questions like:

- `给我过去五个月徐州的虫害情况`

The understanding layer should return:

- `domain = pest`
- `region_name = 徐州市`
- `task_type = region_overview`
- `window = 过去5个月`
- `normalized_question` should preserve overview semantics
- `historical_query_text` should preserve region summary semantics instead of collapsing to ranking

Ranking prompts should still stay ranking:

- `过去5个月虫情最严重的地方是哪里`

Trend prompts should still stay trend:

- `徐州近三周虫害走势怎么样`

## Proposed Runtime Design

### 1. Structured extractor

Add an Instructor-backed extractor module that returns a typed schema:

- `domain`
- `task_type`
- `region_name`
- `region_level`
- `historical_window`
- `future_window`
- `needs_explanation`
- `needs_advice`

This extractor is optional at runtime:

- If OpenAI is configured, use it.
- If extraction fails, fall back to the deterministic parser.

### 2. Deterministic fallback and guardrails

Keep deterministic logic for:

- city alias normalization
- pending clarification resolution
- short follow-up expansion
- noise stripping
- final slot fallback when the structured extractor is missing or weak

This keeps the system reliable even if the LLM path is unavailable.

### 3. Explicit task typing

Introduce explicit `task_type` values:

- `ranking`
- `trend`
- `region_overview`
- `joint_risk`
- `unknown`

This lets the system preserve semantics instead of inferring everything from a single rewritten string.

### 4. Query path upgrade

Planner and query engine must learn two new agri query types:

- `pest_overview`
- `soil_overview`

These should summarize a single region over a time window using existing trend data, instead of forcing top-region ranking.

## UI / Evidence Changes

The evidence panel should eventually expose:

- `task_type`
- `understanding_engine`

This makes the upgraded reasoning visible and debuggable.

## Testing Strategy

1. Add failing request-understanding tests for overview semantics.
2. Add planner tests for overview query type inference.
3. Add agent-level regression tests showing that overview questions no longer collapse into ranking.
4. Keep old ranking/trend/joint-risk tests green.

## Rollout Strategy

Phase 1 in this change:

- Implement Instructor-backed understanding
- Add explicit task types
- Add `pest_overview` / `soil_overview`
- Preserve stable fallback behavior

Deferred:

- HanLP model-backed slot extraction once a local production model path is chosen and cached
- richer UI controls such as click-to-retry suggested understanding rewrites
