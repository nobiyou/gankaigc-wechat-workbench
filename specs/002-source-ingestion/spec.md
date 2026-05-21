# Feature Specification: Source Ingestion And Freshness

**Feature Branch**: `[002-source-ingestion]`

**Created**: 2026-05-21

**Status**: Draft

**Input**: User description: "开始下一批功能开发，做真实来源接入与入库闭环。优先补热点抓取、公众号导入闭环、来源侧批量转选题、来源新鲜度指标。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Import Source Materials Reliably (Priority: P1)

As the operator, I want source imports to be deduplicated, summarized, and recorded so that I can import trends or WeChat articles repeatedly without polluting the source pool or losing track of what happened.

**Why this priority**: The current project already supports the downstream chain, but the upstream source pool is still too fragile for daily production. Duplicate imports and weak traceability directly reduce trust in the workbench.

**Independent Test**: Can be fully tested by importing trends and WeChat MP articles twice, then verifying that the system reports created versus skipped results, persists only one copy of duplicates, and exposes the latest import activity in dashboard or task history.

**Acceptance Scenarios**:

1. **Given** the same WeChat MP article is imported twice, **When** the second import runs, **Then** the system skips the duplicate and returns a per-item result that explains why it was skipped.
2. **Given** a trends text import contains repeated titles, **When** the import finishes, **Then** the response includes created and skipped counts plus per-line results.
3. **Given** an import finishes, **When** the operator opens the dashboard or task history, **Then** they can see that a source ingestion action happened and whether it succeeded, partially succeeded, or failed.

---

### User Story 2 - Batch Promote Sources Into Topics (Priority: P1)

As the operator, I want to batch-generate topics from current source pools so that I can quickly turn newly imported trends or tracked articles into a workable topic queue.

**Why this priority**: Once source intake becomes reliable, the next bottleneck is still manual one-by-one promotion into topics. Batch promotion is the minimum throughput feature needed for daily operation.

**Independent Test**: Can be fully tested by selecting source filters or using the default pending pool, running a batch generation task, and confirming that the task detail shows created, skipped, and failed items with reasons.

**Acceptance Scenarios**:

1. **Given** the source pool contains trends that do not yet have topics, **When** the operator triggers batch topic generation without explicit slugs, **Then** the system processes the eligible pending pool instead of doing nothing.
2. **Given** some tracked articles already produced topics, **When** the operator runs tracked-article batch topic generation, **Then** duplicates are skipped with explicit reasons and only eligible items are generated.

---

### User Story 3 - See Source Freshness At A Glance (Priority: P2)

As the operator, I want the dashboard to show source freshness and ingestion activity so that I can immediately tell whether today’s production is blocked by stale upstream inputs rather than by downstream writing work.

**Why this priority**: The current dashboard emphasizes project queues but hides whether the source pool itself is stale. That makes it harder to decide whether to collect more material or continue writing.

**Independent Test**: Can be fully tested by importing or creating new source items, loading the dashboard, and verifying that freshness metrics and latest source activity update accordingly.

**Acceptance Scenarios**:

1. **Given** new trends or tracked articles were imported today, **When** the dashboard loads, **Then** it shows the latest source sync time and counts for source-side queues.
2. **Given** no source ingestion has happened recently, **When** the dashboard loads, **Then** it shows an explicit stale or missing freshness state instead of implying that sources are healthy.

---

### Edge Cases

- What happens when a WeChat import payload contains two duplicate articles in the same request?
- How does the system report a partially successful import where some items are created and others are skipped?
- What happens when batch topic generation is triggered with an empty source pool?
- How does the dashboard behave when there is no recorded source ingestion history yet?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST persist source-ingestion outcomes for trend import and WeChat article import, including aggregate counts and completion time.
- **FR-002**: System MUST return per-item import results for WeChat article import with statuses such as `created`, `skipped`, or `failed`.
- **FR-003**: System MUST prevent duplicate tracked-article creation when the same article URL or source-specific import identity has already been ingested.
- **FR-004**: System MUST record source-ingestion actions in task history so dashboard and pipeline views can surface recent activity.
- **FR-005**: System MUST allow batch topic generation from the default eligible source pool when explicit source slugs are omitted.
- **FR-006**: System MUST skip source items that already produced topics during batch generation and MUST return explicit skip reasons.
- **FR-007**: System MUST expose dashboard source-freshness metrics, including the latest source-ingestion time and source-side queue counts.
- **FR-008**: System MUST surface source import summaries in the frontend without requiring the operator to inspect backend logs.

### Key Entities *(include if feature involves data)*

- **Source Ingestion Run**: A persisted record of one trend import or WeChat article import attempt, including source kind, status, counts, and timestamps.
- **Source Ingestion Item Result**: A per-item outcome inside one ingestion run, including item identity, status, and optional skip or failure reason.
- **Tracked Article**: A persisted reference article with source metadata, content summary, and deduplication identity.
- **Dashboard Source Freshness Summary**: A derived dashboard view model that reports latest source activity and whether source inputs are stale or missing.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Re-importing the same WeChat article does not create duplicates and returns a structured skipped result for 100% of duplicate items.
- **SC-002**: Batch topic generation without explicit source slugs processes the current eligible source pool and returns counts for created, skipped, and failed items.
- **SC-003**: Dashboard source freshness updates after a successful source import without requiring backend restarts or manual database inspection.
- **SC-004**: The new source-ingestion flows are covered by automated backend tests and do not regress the existing frontend smoke routes.
