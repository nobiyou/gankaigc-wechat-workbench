# Tasks: Source Ingestion And Freshness

**Input**: Design documents from `/specs/002-source-ingestion/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/source-ingestion-contract.md, quickstart.md

**Tests**: Include backend regression tests for ingestion and dashboard summary, plus frontend type/build verification and existing smoke coverage.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this belongs to
- Include exact file paths in descriptions

## Path Conventions

- Backend app root: `apps/backend/app/`
- Backend tests: `apps/backend/tests/`
- Frontend app root: `apps/frontend/src/`
- Feature docs: `specs/002-source-ingestion/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the new source-ingestion documentation and storage scaffolding.

- [x] T001 Create source-ingestion spec artifacts in `specs/002-source-ingestion/`
- [x] T002 Add source-ingestion persistence scaffolding in `apps/backend/app/services/workbench.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish the backend shapes required by all source-side stories.

**⚠️ CRITICAL**: No user story work should start until this phase is complete.

- [x] T003 Add backend schema updates for dashboard, trend import, tracked article import, and WeChat import responses in `apps/backend/app/schemas/trends.py`, `apps/backend/app/schemas/tracked_articles.py`, and `apps/backend/app/schemas/wechat_mp.py`
- [x] T004 [P] Add backend tests for ingestion-run tracking and dashboard freshness in `apps/backend/tests/test_app.py` and `apps/backend/tests/test_wechat_mp_import.py`
- [x] T005 Wire API routes to the new source-ingestion response shapes in `apps/backend/app/api/trends.py`, `apps/backend/app/api/tracked_articles.py`, and `apps/backend/app/api/wechat_mp.py`

**Checkpoint**: Source-ingestion data can now be recorded, surfaced, and tested.

---

## Phase 3: User Story 1 - Import Source Materials Reliably (Priority: P1) 🎯 MVP

**Goal**: Make trend and WeChat article imports duplicate-safe, summarized, and traceable.

**Independent Test**: Import duplicate source materials twice and verify item-level results, aggregate counts, and no duplicate persisted rows.

- [x] T006 [P] [US1] Add trend-import run recording and aggregate counters in `apps/backend/app/services/workbench.py`
- [x] T007 [P] [US1] Add tracked-article deduplication by URL plus structured import results in `apps/backend/app/services/workbench.py`
- [x] T008 [US1] Update WeChat import route and client integration response handling in `apps/backend/app/api/wechat_mp.py` and `apps/backend/app/services/wechat_mp_client.py`
- [x] T009 [US1] Update frontend import response types and result rendering in `apps/frontend/src/api/workbench.ts` and `apps/frontend/src/components/WechatMpImportPanel.tsx`

**Checkpoint**: Source imports are production-safe enough for repeated daily use.

---

## Phase 4: User Story 2 - Batch Promote Sources Into Topics (Priority: P1)

**Goal**: Allow operators to turn the current eligible source pool into topics without manual one-by-one promotion.

**Independent Test**: Trigger batch generation with empty selection payloads and verify that eligible source items are processed and ineligible ones are skipped clearly.

- [x] T010 [P] [US2] Add default eligible-pool selection and skip-reason behavior for trend batch generation in `apps/backend/app/services/workbench.py`
- [x] T011 [P] [US2] Add default eligible-pool selection and skip-reason behavior for tracked-article batch generation in `apps/backend/app/services/workbench.py`
- [x] T012 [US2] Extend backend tests for default-pool batch generation behavior in `apps/backend/tests/test_app.py`

**Checkpoint**: Operators can reliably promote sources into the topic queue in bulk.

---

## Phase 5: User Story 3 - See Source Freshness At A Glance (Priority: P2)

**Goal**: Make stale or healthy source intake visible from the homepage.

**Independent Test**: Perform a source import, reload the dashboard, and verify freshness metrics and latest source activity render correctly.

- [x] T013 [P] [US3] Extend dashboard summary generation with source-freshness fields in `apps/backend/app/services/workbench.py`
- [x] T014 [P] [US3] Update dashboard summary types and freshness rendering in `apps/frontend/src/api/workbench.ts` and `apps/frontend/src/pages/DashboardPage.tsx`
- [x] T015 [US3] Add or adjust frontend helper rendering for latest task and freshness copy in `apps/frontend/src/view-models/dashboardRecentTasks.ts`

**Checkpoint**: The homepage shows whether the upstream source pool is fresh enough for daily production.

---

## Phase 6: Polish & Verification

**Purpose**: Validate the batch end-to-end and align task status with real execution.

- [x] T016 Run `python -m pytest apps/backend/tests/test_app.py apps/backend/tests/test_wechat_mp_import.py`
- [x] T017 Run `npm test` and `npm run build` in `apps/frontend`
- [x] T018 Run `node scripts/verify-workbench-ui-smoke.cjs`
- [x] T019 Mark completed tasks in `specs/002-source-ingestion/tasks.md` based on actual verification
