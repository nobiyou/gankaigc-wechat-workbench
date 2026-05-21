# Tasks: Workbench UI Restructure

**Input**: Design documents from `/specs/001-workbench-ui-restructure/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ui-route-contract.md, quickstart.md

**Tests**: Include helper/view-model tests plus frontend build and manual browser smoke verification because the repo already has a lightweight TypeScript test harness.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g. `US1`, `US2`)
- Include exact file paths in descriptions

## Path Conventions

- Frontend app root: `apps/frontend/`
- Frontend source: `apps/frontend/src/`
- Feature docs: `specs/001-workbench-ui-restructure/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the route shell and shared structure needed for the refactor.

- [x] T001 Create route-shell folders and initial modules in `apps/frontend/src/app/`, `apps/frontend/src/pages/`, and `apps/frontend/src/view-models/`
- [x] T002 Create primary navigation metadata in `apps/frontend/src/app/navigation.ts`
- [x] T003 [P] Add navigation metadata tests in `apps/frontend/src/app/navigation.test.ts`
- [x] T004 Wire route shell composition through `apps/frontend/src/App.tsx` and `apps/frontend/src/app/routes.tsx`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Extract shared derivation logic and route-safe app scaffolding before page-by-page implementation.

**⚠️ CRITICAL**: No user story work should start until this phase is complete.

- [x] T005 Extract shared dashboard queue derivation into `apps/frontend/src/view-models/dashboardQueues.ts`
- [x] T006 [P] Extract grouped project-list derivation into `apps/frontend/src/view-models/projectGroups.ts`
- [x] T007 [P] Extract pipeline summary/filter derivation into `apps/frontend/src/view-models/pipelineViews.ts`
- [x] T008 Add tests for shared view-model helpers in `apps/frontend/src/view-models/dashboardQueues.test.ts`, `apps/frontend/src/view-models/projectGroups.test.ts`, and `apps/frontend/src/view-models/pipelineViews.test.ts`
- [x] T009 Refactor legacy task-center helpers to delegate to new view models in `apps/frontend/src/taskCenter.ts` and `apps/frontend/src/taskCenter.test.ts`
- [x] T010 Add shell-level layout styles for routed pages in `apps/frontend/src/styles.css`

**Checkpoint**: Route shell and shared derivation helpers are ready for story-level page extraction.

---

## Phase 3: User Story 1 - Start Today’s Work Fast (Priority: P1) 🎯 MVP

**Goal**: Deliver a task-first dashboard that routes directly into the right work area.

**Independent Test**: Open the root route and verify the homepage shows task-priority cards with direct navigation into target pages instead of long lists.

- [x] T011 [P] [US1] Add dashboard queue and card-shaping tests in `apps/frontend/src/view-models/dashboardQueues.test.ts`
- [x] T012 [US1] Implement `DashboardPage` in `apps/frontend/src/pages/DashboardPage.tsx`
- [x] T013 [US1] Wire dashboard routes and root entry behavior in `apps/frontend/src/app/routes.tsx`
- [x] T014 [US1] Add dashboard task-card and empty-state styling in `apps/frontend/src/styles.css`

**Checkpoint**: The root route behaves like a task-first dashboard and is independently usable.

---

## Phase 4: User Story 2 - Separate Sources From Pipeline Work (Priority: P1)

**Goal**: Split browse/curate flows from batch execution and async task result flows.

**Independent Test**: Navigate between `Sources` and `Pipeline` and verify source pages keep single-item actions while batch runs, results, and retries live only in pipeline views.

- [x] T015 [P] [US2] Add source-view grouping tests in `apps/frontend/src/view-models/pipelineViews.test.ts` and `apps/frontend/src/contentSources.test.ts`
- [x] T016 [US2] Implement `SourcesPage` with trends, tracked articles, and WeChat import subviews in `apps/frontend/src/pages/SourcesPage.tsx`
- [x] T017 [US2] Implement `PipelinePage` with topic queue, batch runs, and task log subviews in `apps/frontend/src/pages/PipelinePage.tsx`
- [x] T018 [US2] Re-home batch result rendering and topic-queue presentation from `apps/frontend/src/App.tsx` into `apps/frontend/src/pages/PipelinePage.tsx`
- [x] T019 [US2] Add sources and pipeline navigation/state styling in `apps/frontend/src/styles.css`

**Checkpoint**: Sources and pipeline work areas are visibly separate and independently navigable.

---

## Phase 5: User Story 3 - Enter a Focused Single-Project Workbench (Priority: P1)

**Goal**: Let the operator enter one project into a full-screen workbench with left-stage navigation and contextual history.

**Independent Test**: Open a project from the grouped projects page and verify the workbench has summary bar, stage navigation, active stage workspace, and stage-history access.

- [x] T020 [P] [US3] Add workbench stage recommendation tests in `apps/frontend/src/view-models/workbenchStages.test.ts`
- [x] T021 [P] [US3] Add workbench history-drawer tests in `apps/frontend/src/view-models/workbenchHistory.test.ts`
- [x] T022 [US3] Implement grouped projects page in `apps/frontend/src/pages/ProjectsPage.tsx`
- [x] T023 [US3] Implement dedicated workbench route and page in `apps/frontend/src/pages/WorkbenchPage.tsx`
- [x] T024 [US3] Add workbench stage and history view-model helpers in `apps/frontend/src/view-models/workbenchStages.ts` and `apps/frontend/src/view-models/workbenchHistory.ts`
- [x] T025 [US3] Wire project-to-workbench navigation and stage route normalization in `apps/frontend/src/app/routes.tsx` and `apps/frontend/src/projectSelection.ts`
- [x] T026 [US3] Add projects/workbench responsive layout and stage UI styling in `apps/frontend/src/styles.css`

**Checkpoint**: A project can be opened into a dedicated workbench route and used independently of the old single-page structure.

---

## Phase 6: User Story 4 - Review and Return Work in Context (Priority: P2)

**Goal**: Keep review, history, and retry flows attached to the correct workspace instead of standalone global pages.

**Independent Test**: Confirm publish review actions live in the publish stage, stage history stays in contextual drawers, and failed async work is accessible through pipeline task logs.

- [x] T027 [US4] Move publish-review and revision entry behavior into `apps/frontend/src/pages/WorkbenchPage.tsx`
- [x] T028 [US4] Surface contextual activity/history affordances through `apps/frontend/src/pages/WorkbenchPage.tsx` and `apps/frontend/src/view-models/workbenchHistory.ts`
- [x] T029 [US4] Remove standalone `Task Center` and `Version History` page rendering from `apps/frontend/src/App.tsx`
- [x] T030 [US4] Ensure pipeline task-log entry points cover failed batch work in `apps/frontend/src/pages/PipelinePage.tsx`

**Checkpoint**: Review, history, and retries are all available in context without standalone legacy pages.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Clean up the refactor, verify behavior, and remove lingering single-page assumptions.

- [x] T031 [P] Remove obsolete single-page helpers and dead UI branches from `apps/frontend/src/App.tsx` and related modules
- [x] T032 [P] Final responsive and visual consistency cleanup in `apps/frontend/src/styles.css`
- [x] T033 Run frontend helper tests with `cd apps/frontend && npm test`
- [x] T034 Run production build with `cd apps/frontend && npm run build`
- [x] T035 Run manual quickstart verification from `specs/001-workbench-ui-restructure/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1: Setup**: starts immediately
- **Phase 2: Foundational**: depends on Phase 1 and blocks all user stories
- **Phase 3: US1**: starts after Phase 2
- **Phase 4: US2**: starts after Phase 2
- **Phase 5: US3**: starts after Phase 2 and depends on route shell from Phase 1
- **Phase 6: US4**: depends on US2 and US3 because it relocates contextual review/history ownership
- **Phase 7: Polish**: depends on all selected stories being complete

### User Story Dependencies

- **US1**: independent after Phase 2
- **US2**: independent after Phase 2
- **US3**: independent after Phase 2, but most valuable after US1 shell routing exists
- **US4**: depends on the new pipeline and workbench pages being present

### Within Each User Story

- Update or add helper tests before finishing the corresponding page extraction
- Add or update page components before deleting legacy rendering
- Complete route wiring before manual browser verification

### Parallel Opportunities

- T003 can run with T002
- T006 and T007 can run in parallel
- T011 can run while T012 is being prepared
- T015 can run while T016/T017 are being prepared
- T020 and T021 can run in parallel
- T031 and T032 can run in parallel after story work is stable

---

## Parallel Example: User Story 3

```text
T020 [US3] Add workbench stage recommendation tests in apps/frontend/src/view-models/workbenchStages.test.ts
T021 [US3] Add workbench history-drawer tests in apps/frontend/src/view-models/workbenchHistory.test.ts
```

```text
T022 [US3] Implement grouped projects page in apps/frontend/src/pages/ProjectsPage.tsx
T024 [US3] Add workbench stage and history view-model helpers in apps/frontend/src/view-models/workbenchStages.ts and apps/frontend/src/view-models/workbenchHistory.ts
```

---

## Implementation Strategy

### MVP First

1. Complete Phase 1 and Phase 2
2. Complete US1 so the app lands on a task-first dashboard
3. Complete US2 and US3 to make the new work modes actually usable
4. Validate the new navigation model before deleting legacy page surfaces

### Incremental Delivery

1. Shell and shared view-model extraction
2. Dashboard
3. Sources + Pipeline
4. Projects + Workbench
5. Contextual review/history retirement
6. Polish and verification

### Subagent Strategy

- Run one implementation subagent per task slice, not per entire phase
- Keep write scopes disjoint when running parallel helper-test tasks
- Always review for spec compliance before code-quality review

---

## Notes

- `[P]` tasks are safe to parallelize because they target different files or pure helper tests
- Do not reintroduce a standalone `Task Center` or `Version History` during cleanup
- Keep backend contract changes out of this feature unless a route-friendly fetch helper requires a harmless frontend-only API wrapper
- `T035` was signed off with frontend tests, production build, and enhanced smoke verification covering the quickstart route checklist
