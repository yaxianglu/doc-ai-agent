# Agent Architecture Refactor Design

**Problem:** The current `doc-ai-agent` runtime is functional and well-covered by regression tests, but core responsibilities are still spread across overlapping modules. Parsing is duplicated across `RequestUnderstanding` and `QueryPlanner`, orchestration logic leaks planner internals into `DocAIAgent`, and repository capabilities are inferred with `hasattr(...)` checks rather than a stable contract.

**Goal:** Tighten architectural boundaries without breaking the current request/response contract or the strict 140-case evaluation gate, so future capability work can land with lower coupling and clearer ownership.

## Current pain points

- **Duplicate semantic work**
  - `RequestUnderstanding` already emits `canonical_understanding` and `parsed_query`.
  - `QueryPlanner` still re-runs semantic parsing and may re-derive route decisions from raw question text.
  - Result: unclear source of truth, harder debugging, and more edge-case drift in follow-up turns.

- **Overweight orchestrator**
  - `DocAIAgent` wires the graph, patches plans, derives runtime context, coordinates retries, builds memory snapshots, and assembles final evidence.
  - It also reaches into `QueryPlanner` private helpers such as `_finalize_plan`, `_extract_top_n`, and `_build_route`.
  - Result: orchestration and planning are coupled by implementation details instead of stable interfaces.

- **Weak data access contract**
  - `QueryEngine` and `ForecastService` branch on `hasattr(self.repo, ...)` to discover backend capabilities.
  - `AlertRepository` and `MySQLRepository` are shape-compatible in practice, but not through an explicit interface.
  - Result: backend support is implicit, fragile, and expensive to extend.

- **Facade not yet acting as a boundary**
  - `AccessFacade` exists, but only partially fronts retrieval and playbook routing.
  - Advice, planner, and execution code still reach underlying dependencies directly.
  - Result: the facade documents intent, but does not yet enforce dependency direction.

- **Large domain services**
  - `QueryEngine`, `MySQLRepository`, and `agent.py` have grown into multi-responsibility modules.
  - Result: features are additive, but maintenance cost rises quickly and test scopes stay broad.

## Approaches considered

### Option A: Keep the current structure and continue adding guardrails

- Pros: lowest short-term change cost
- Cons: duplication remains; private cross-module coupling keeps growing; future changes get slower

### Option B: Full rewrite around a new V2 runtime

- Pros: cleanest end state on paper
- Cons: high migration risk; likely to regress current eval behavior; expensive to validate

### Option C: Incremental boundary tightening on the existing runtime (**recommended**)

- Pros: preserves current contract and eval gate; fixes the highest-leverage seams first; allows staged rollout
- Cons: requires discipline to stop short of a rewrite; some transitional adapters will remain for a while

## Recommended design

Use **Option C** and tighten the architecture in three sequential layers.

### Layer 1: One semantic source of truth

- `RequestUnderstanding` becomes the only module that converts raw question + context into normalized semantic state.
- Its durable outputs are:
  - `canonical_understanding`
  - `parsed_query` (`QueryDSL`)
  - compatibility fields already required by the current response contract
- `QueryPlanner` stops re-parsing raw input and instead consumes:
  - `parsed_query`
  - `canonical_understanding`
  - memory context
- Planner responsibility narrows to:
  - clarification decision
  - capability routing
  - task template selection
  - execution route assembly

### Layer 2: Stable ports around backends

- Introduce an explicit `AnalyticsRepository` Protocol for the operations needed by:
  - `QueryEngine`
  - `ForecastService`
  - related capabilities
- Replace backend capability detection via `hasattr(...)` with:
  - required protocol methods where behavior is mandatory
  - clearly named optional adapters only where behavior is genuinely backend-specific
- Expand `AccessFacade` into the dependency boundary for:
  - knowledge retrieval
  - playbook routing
  - optional future access to unified backend metadata

### Layer 3: Thin orchestrator, thicker capabilities

- `DocAIAgent` remains the LangGraph coordinator but sheds domain logic.
- Node helpers and capabilities own:
  - route normalization
  - query execution
  - forecast execution
  - synthesis payload assembly
- `DocAIAgent` should only:
  - load state
  - pass stable payloads between nodes
  - invoke public planner/capability APIs
  - persist memory
  - attach final processing metadata

## Target dependency direction

Preferred direction after refactor:

- `server` -> `DocAIAgent`
- `DocAIAgent` -> `RequestUnderstanding`, `QueryPlanner`, capabilities, memory, `ResponseBuilder`
- capabilities -> `AnalyticsRepository` Protocol and `AccessFacade`
- concrete backends -> Protocol implementations

Avoid after refactor:

- `DocAIAgent` -> planner private helpers
- planner -> raw semantic parsing of already-understood requests
- query/forecast services -> backend feature discovery by `hasattr(...)`

## Migration phases

### Phase 1: Parse boundary tightening

- Freeze `RequestUnderstanding` outputs as the upstream semantic truth.
- Teach `QueryPlanner` to trust `parsed_query` and `canonical_understanding`.
- Preserve current compatibility fields and response evidence.

### Phase 2: Repository and facade boundary tightening

- Add repository Protocol and adapters.
- Migrate `QueryEngine` and `ForecastService` to Protocol-based access.
- Expand or simplify `AccessFacade` so it becomes real architecture, not decorative structure.

### Phase 3: Orchestrator slimming

- Move plan repair, route normalization, and synthesis preparation behind public helpers or capability methods.
- Reduce `DocAIAgent` knowledge of planner and service internals.
- Keep LangGraph topology stable unless there is a proven eval benefit to changing it.

## In scope

- Parsing boundary cleanup
- Planner interface tightening
- Repository Protocol extraction
- Access facade consolidation
- Agent and capability responsibility rebalance
- Contract-preserving tests and eval verification

## Out of scope

- Replacing LangGraph
- Replacing current forecast algorithms
- Changing public API fields for `/chat`
- Rewriting domain SQL behavior unless required by boundary cleanup
- Large model strategy changes

## Risks and mitigations

- **Risk: semantic regressions in follow-up turns**
  - Mitigation: preserve `canonical_understanding` and `parsed_query` side by side during migration; add follow-up regression tests first.

- **Risk: backend divergence between SQLite and MySQL**
  - Mitigation: introduce repository Protocol with focused contract tests before removing `hasattr(...)` fallbacks.

- **Risk: architectural cleanup accidentally becomes behavior rewrite**
  - Mitigation: keep strict 140-case eval as the release gate and prefer adapter layers over semantic behavior changes.

- **Risk: orchestration refactor touches too many responsibilities at once**
  - Mitigation: slim `DocAIAgent` in small extractions, one node boundary at a time.

## Success criteria

- `RequestUnderstanding` is the only semantic parser on the main path.
- `QueryPlanner` consumes normalized understanding state instead of re-deriving it.
- `QueryEngine` and `ForecastService` no longer rely on repeated `hasattr(self.repo, ...)` checks for standard behavior.
- `DocAIAgent` no longer calls planner private helpers.
- Existing `/chat` response fields and strict-eval expectations remain intact.
- New feature work can target capabilities or repositories without editing the orchestration core first.

## Implementation note added on 2026-04-15

- Query-side repository contracts needed one extra refinement during execution:
  - a single broad monitoring protocol was too coarse for runtime checks
  - structured repos that support `pest / soil / joint_risk` main paths but omit optional `available_*` helpers were being rejected
- The refactor therefore split monitoring access into narrower query-facing contracts plus optional availability contracts.
- This keeps the architecture aligned with the original goal: explicit contracts replace implicit `hasattr(...)`, but the contracts must be scoped to the actual behavior each path requires.
