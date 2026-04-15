# Low-Score Remediation Design

**Problem:** The strict 140-case eval still has 32 items below 7, concentrated in county scope, trend judgments, boolean/judgment questions, multi-turn carry-over, and composite risk answers.

**Goal:** Raise strict-eval quality by fixing routing and response-shaping errors before changing model strategy, so the agent answers the right question first and only then optimizes phrasing.

## Current failure clusters

- **Boolean questions answered as rankings**
  - Example: “是否 / 有没有 / 会不会” questions return TopN lists instead of direct yes/no or direction answers.
- **County scope mismatches**
  - The agent falls back instead of forcing county-granularity execution or a precise “no county-level evidence” answer.
- **Trend questions answered with fallback**
  - Trend intent is recognized too late and repaired in the guard layer instead of being planned as a first-class task.
- **Multi-turn slot drift**
  - Follow-up questions such as “其中虫情的呢 -> 按县给我看 -> 那未来两周呢” lose domain, granularity, or window.
- **Composite questions under-structured**
  - “排名 + 原因 + 建议” and “历史 + 预测” requests are not rendered through a stable answer contract.

## Approaches considered

### Option A: Upgrade the LLM / semantic parser first

- Pros: minimal code-path changes
- Cons: does not fix deterministic contract errors; expensive; unstable; hard to debug

### Option B: Add guardrail logic only

- Pros: fast to ship
- Cons: guard becomes the main behavior engine; too many fallback answers; hard to maintain

### Option C: Tighten parse -> route -> answer contract first (**recommended**)

- Pros: fixes root cause; improves determinism; easier to test; preserves current architecture
- Cons: needs coordinated changes across parser, planner, guard, and builder

## Recommended design

Use **Option C**. Add a stronger structured contract at the top and bottom of the pipeline:

1. **Query shape classification**
   - Extend query semantics with an explicit answer form:
     - `boolean`
     - `trend`
     - `rank`
     - `detail`
     - `explanation`
     - `advice`
     - `composite`
2. **Hard planning constraints**
   - County questions must route to county-capable query templates.
   - Boolean/trend questions must route to direct-answer templates, not ranking templates.
3. **Response contract before natural language**
   - Build structured answers with required first-line conclusions:
     - boolean -> `是/否`
     - trend -> `上升/下降/平稳/暂无法判断`
     - composite -> `结论 -> 证据 -> 建议`
4. **Repair-first guard**
   - The guard should try rewrite and corrected-route retry before fallback.
5. **Low-score regression pack**
   - Promote the current low-score items into deterministic regression tests and a dedicated eval slice.

## Scope

### In scope

- Query DSL / parser enrichment
- Planner template tightening
- Response Builder strengthening
- Answer Guard repair-first logic
- Multi-turn slot carry-over
- Regression tests for the current low-score set

### Out of scope

- Model upgrades
- New database schema
- Replacing LangGraph
- Rewriting forecast algorithms

## Success criteria

- Boolean questions answer yes/no or direct direction first.
- County questions no longer degrade to city rankings silently.
- Trend questions stop falling back when data exists.
- Multi-turn county/domain/window carry-over becomes stable.
- Strict 140-case average improves and low-score count drops materially.

