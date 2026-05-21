# Feature Specification: Trend Fetch

**Feature Branch**: `[003-trend-fetch]`

**Created**: 2026-05-21

**Status**: Draft

**Input**: User description: "提交，然后继续" after completing source ingestion hardening, with the next implementation target set to real trend fetching.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pull Real Trends Into The Source Pool (Priority: P1)

As the operator, I want the system to fetch trends from configured live sources so that I do not have to paste raw trend text manually for each refresh.

**Why this priority**: The source pool is now ingestion-safe, but trend collection still depends on manual input. That leaves the upstream chain only half operational.

**Independent Test**: Can be fully tested by mocking one RSS source, triggering `/trends/fetch`, and verifying that fetched items are imported into the trend pool with created and skipped counts.

**Acceptance Scenarios**:

1. **Given** at least one RSS source is configured, **When** the operator triggers trend fetch, **Then** the system fetches items, imports new trends, and returns a structured batch summary.
2. **Given** the fetched feed contains titles already present locally, **When** the fetch completes, **Then** duplicate trends are skipped and counted explicitly.

---

### User Story 2 - Trigger Fetch From Sources UI (Priority: P1)

As the operator, I want a visible fetch action on the trends source page so that I can refresh live sources without leaving the workbench.

**Why this priority**: The backend route alone is not enough for daily use. The source page must expose the action where operators already manage trends.

**Independent Test**: Can be fully tested by opening `Sources / 热点来源`, clicking the fetch action, and confirming the list and summary refresh after completion.

### Edge Cases

- What happens when no trend feed source is configured?
- What happens when one feed source fails but another succeeds?
- What happens when a feed returns malformed XML?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide `POST /trends/fetch` for live trend refresh.
- **FR-002**: System MUST support one or more configured RSS feed URLs as fetch sources.
- **FR-003**: System MUST treat fetched titles that already exist locally as skipped duplicates rather than failures.
- **FR-004**: System MUST record live trend fetches through the same source-ingestion tracking introduced in `002-source-ingestion`.
- **FR-005**: System MUST expose a fetch action in `Sources / trends` and refresh the visible trend list after a successful fetch.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Triggering `/trends/fetch` with a mocked RSS source imports new trends and returns created and skipped counts.
- **SC-002**: Triggering the trends fetch from the UI refreshes the list without a full app reload.
