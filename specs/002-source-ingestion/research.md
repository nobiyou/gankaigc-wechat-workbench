# Research: Source Ingestion And Freshness

## Decision 1: Treat Source Intake As An Operational Layer, Not Just CRUD

**Decision**: Add explicit ingestion-run tracking for trend and WeChat article imports instead of relying only on raw item rows plus generic task logs.

**Rationale**:

- The current upstream problem is not only persistence; it is trust and traceability
- Operators need aggregate created and skipped counts, latest sync time, and partial-failure visibility
- Import summaries are easier to reuse in dashboard and future source-center views when they have a first-class shape

**Alternatives considered**:

- Reuse only `task_logs`: rejected because task logs do not preserve import-level counts or item-level skip reasons
- Store import summaries only in frontend state: rejected because dashboard freshness and retries need persisted backend truth

## Decision 2: Deduplicate Tracked Articles By Stable Source Identity

**Decision**: Deduplicate WeChat tracked articles primarily by URL, while still preserving slug-based uniqueness for manually created items.

**Rationale**:

- URL is the most stable import identity available in the current WeChat article payload
- Slug uniqueness alone is insufficient because the same article can be re-imported with the same semantic identity but a derived slug
- This keeps manual article creation backward-compatible while protecting the import path

**Alternatives considered**:

- Deduplicate only by title: rejected because titles can collide across accounts or revisions
- Deduplicate by account nickname plus title: rejected because nickname is weaker than the canonical article URL

## Decision 3: Default Batch Topic Generation To The Eligible Pool

**Decision**: When batch topic generation omits explicit source slugs, process the current eligible pending pool and return skipped reasons for ineligible items only when explicit slugs are requested.

**Rationale**:

- Operators usually want “process what is ready now”, not an empty no-op
- This keeps the UI simple and allows future one-click source queue promotion
- Existing background-task infrastructure already supports async batch execution and result summaries

**Alternatives considered**:

- Require explicit selections always: rejected because it adds friction to routine daily use
- Auto-process every source item including already-converted ones: rejected because it hides duplicate or stale-source problems

## Decision 4: Extend Dashboard Summary Instead Of Creating A New Source Dashboard First

**Decision**: Add source freshness metrics to the existing dashboard summary response and dashboard page instead of creating a dedicated new report route in this batch.

**Rationale**:

- The current user need is quick diagnosis of stale upstream inputs
- Existing homepage is already the first operator stop after the UI restructure
- A smaller dashboard extension delivers immediate value without splintering navigation again

**Alternatives considered**:

- Build a separate source-health page: rejected because the need is an at-a-glance signal, not a full analytics surface
- Keep freshness hidden in task logs only: rejected because operators should not have to infer source health indirectly
