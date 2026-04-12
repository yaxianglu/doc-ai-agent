# Doc AI Agent 9.0 Upgrade Design

**Goal:** Push the Doc AI agent from a usable data QA assistant to a stronger, more reliable agricultural analysis agent that can hold context, compare entities, ground explanations in data, and obey user constraints.

**Current Baseline:** The agent is now around 7.8/10 under strict human review. It can answer explicit historical, detail, forecast, and some multi-turn questions, but it still sounds generic in causal explanations and is not yet consistently “expert-agent” grade.

---

## Upgrade Options

### Option A — System-layer strengthening (recommended)

Keep the current LangGraph runtime, but strengthen the layers above it:

- first-class query planning
- better constraint handling
- data-grounded explanation synthesis
- stronger evaluation harness

**Pros:** highest ROI, lowest rewrite risk, directly addresses current failure modes.

**Cons:** less flashy than swapping frameworks; still requires disciplined cleanup.

### Option B — Framework-led rewrite

Adopt more of Letta / full memory-agent orchestration / deeper graph indirection first.

**Pros:** cleaner long-term agent architecture.

**Cons:** high migration cost, low short-term quality gain; does not by itself fix bad reasoning over structured data.

### Option C — Model or fine-tune first

Invest early in training / fine-tuning / prompt-heavy tuning.

**Pros:** may improve language smoothness.

**Cons:** expensive, unstable, and premature before execution semantics and evaluation are fixed.

## Recommended Path

Take Option A now, keep LangGraph, and upgrade the agent in four layers.

1. **Execution semantics**
   - first-class compare / cross-domain compare
   - explicit user constraints such as “不要建议”
   - stronger task graph semantics
2. **Data-grounded reasoning**
   - explanations must cite historical trend, peak, latest value, and forecast where present
   - advice should reference actual observed severity rather than only generic rule text
3. **Memory and control**
   - preserve domain / region / time / constraint slots explicitly
   - reduce drift in follow-up turns
4. **Strict evaluation loop**
   - codify a harsh scoring rubric
   - keep regression coverage for low-score cases

---

## Phase Plan

### Phase 1 — Reliability to 8.4
- formalize compare answers
- enforce no-advice constraints
- split explanation and advice sections
- stabilize memory carry-over for detail follow-ups

### Phase 2 — Stronger reasoning to 8.9
- replace generic explanation text with data-grounded explanation synthesis
- thread observed metrics into explanation/advice generation
- expose stronger evidence structure for debugging and UI

### Phase 3 — Evaluation-driven hardening to 9.0
- strict scoring harness for representative dialogue sets
- add category-level regression tests
- trim remaining over-clarification and generic fallback behavior

---

## What Will Not Move the Score Much Right Now

- swapping LangGraph for another orchestration framework alone
- adding fine-tuning before the execution layer is stable
- adding more generic RAG content without evidence alignment

## Success Criteria for 9.0

The agent can:

- answer comparisons without dropping one side
- obey explicit user constraints like “不要建议”
- carry region/domain/time reliably across follow-ups
- explain “为什么” with actual historical/forecast evidence, not generic filler
- stay stable across a strict representative test set

