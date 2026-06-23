# Tasks: Creative Workflow

**Input**: Design documents from `/specs/004-creative-workflow/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/creative-workflow-contract.md, quickstart.md

**Tests**: Include backend regression coverage for strategy, diagnosis, reports, and reusable patterns, plus frontend helper tests and build verification.

**Organization**: Tasks are grouped by user story so each story can be implemented and validated independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this belongs to
- Include exact file paths in descriptions

## Path Conventions

- Backend app root: `apps/backend/app/`
- Backend tests: `apps/backend/tests/`
- Frontend app root: `apps/frontend/src/`
- Feature docs: `specs/004-creative-workflow/`

## Status Update

- As of 2026-06-23, implementation, automated verification, and manual browser acceptance are complete through T045.
- Verified flows include strategy generation/adoption, diagnosis-driven polish, creative review reporting, reusable pattern promotion, and legacy `missing_strategy` project compatibility.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish module ownership and route placeholders for the creative workflow slice.

- [x] T001 Create backend creative-workflow module skeletons in `apps/backend/app/schemas/creative_workflow.py`, `apps/backend/app/services/creative_strategy.py`, `apps/backend/app/services/content_diagnosis.py`, `apps/backend/app/services/creative_reports.py`, and `apps/backend/app/services/creative_patterns.py`
- [x] T002 [P] Create reusable-pattern API router scaffolding and register it in `apps/backend/app/api/creative_patterns.py` and `apps/backend/app/api/__init__.py`
- [x] T003 [P] Add frontend creative-workflow API and settings-navigation placeholders in `apps/frontend/src/api/workbench.ts` and `apps/frontend/src/app/navigation.ts`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add additive persistence and loading scaffolding that every user story relies on.

**⚠️ CRITICAL**: No user story work should start until this phase is complete.

- [x] T004 Add SQLite schema migrations and hydration scaffolding for problem briefs, benchmark references, strategy cards, diagnosis reports, creative review reports, and reusable patterns in `apps/backend/app/services/workbench.py`
- [x] T005 [P] Extend backend response schemas for creative-workflow detail, version, and action payloads in `apps/backend/app/schemas/projects.py` and `apps/backend/app/schemas/creative_workflow.py`
- [x] T006 [P] Add foundational backend regression coverage for legacy null-state loading and extended version payloads in `apps/backend/tests/test_app.py`
- [x] T007 Wire project detail and version loading for new creative-workflow artifacts in `apps/backend/app/services/workbench.py` and `apps/backend/app/api/projects.py`
- [x] T008 Extend frontend project detail, version, and action typing assumptions in `apps/frontend/src/api/workbench.ts`, `apps/frontend/src/view-models/workbenchStages.ts`, and `apps/frontend/src/view-models/workbenchActions.ts`

**Checkpoint**: The workbench can now load empty or populated creative-workflow artifacts without breaking legacy projects.

---

## Phase 3: User Story 1 - Build A Prewriting Strategy Package (Priority: P1) 🎯 MVP

**Goal**: Let operators generate and adopt an explicit prewriting strategy package before outline generation.

**Independent Test**: Create a project from either a manual topic or a trend-derived topic, generate a strategy package, review its problem brief and benchmark references, adopt the strategy card, and then proceed into outline generation without losing the old direct path.

### Tests for User Story 1

- [x] T009 [P] [US1] Add backend tests for strategy package generation, ambiguous-input handling, and strategy adoption in `apps/backend/tests/test_app.py` and `apps/backend/tests/test_creative_strategy.py`
- [x] T010 [P] [US1] Add frontend tests for topic-stage strategy actions and stage recommendation behavior in `apps/frontend/src/view-models/workbenchActions.test.ts` and `apps/frontend/src/view-models/workbenchStages.test.ts`

### Implementation for User Story 1

- [x] T011 [P] [US1] Implement problem-brief, benchmark, and strategy-card generation logic in `apps/backend/app/services/creative_strategy.py`
- [x] T012 [US1] Persist strategy artifacts, active-strategy adoption state, and outline-generation strategy lookup in `apps/backend/app/services/workbench.py`
- [x] T013 [US1] Add strategy generation and strategy adoption routes in `apps/backend/app/api/projects.py` and `apps/backend/app/schemas/creative_workflow.py`
- [x] T014 [US1] Extend frontend client calls and payload types for strategy actions in `apps/frontend/src/api/workbench.ts`
- [x] T015 [US1] Surface topic-stage strategy actions and state transitions in `apps/frontend/src/view-models/workbenchActions.ts` and `apps/frontend/src/view-models/workbenchStages.ts`
- [x] T016 [US1] Render problem brief, benchmark references, and strategy-card panels in `apps/frontend/src/pages/WorkbenchPage.tsx` and `apps/frontend/src/view-models/workbenchPreview.ts`
- [x] T017 [US1] Add topic-stage strategy layout and review-state styling in `apps/frontend/src/styles.css`

**Checkpoint**: Operators can generate a reviewable strategy package and use it before outline generation.

---

## Phase 4: User Story 2 - Diagnose Draft Quality And Launch Directional Polish (Priority: P1)

**Goal**: Diagnose draft weaknesses explicitly and let operators run diagnosis-driven polish without losing manual polish paths.

**Independent Test**: Take an existing draft, run diagnosis, confirm that upstream and downstream findings are separated, launch a diagnosis-driven polish action, and verify that a new draft version records the chosen objective.

### Tests for User Story 2

- [x] T018 [P] [US2] Add backend tests for diagnosis separation, AI fingerprint findings, and diagnosis-driven polish in `apps/backend/tests/test_app.py` and `apps/backend/tests/test_content_diagnosis.py`
- [x] T019 [P] [US2] Add frontend tests for diagnosis actions and diagnosis-preview states in `apps/frontend/src/view-models/workbenchActions.test.ts` and `apps/frontend/src/view-models/workbenchPreview.test.ts`

### Implementation for User Story 2

- [x] T020 [P] [US2] Implement multi-dimensional diagnosis and AI fingerprint aggregation in `apps/backend/app/services/content_diagnosis.py` and `apps/backend/app/services/ai_flavor.py`
- [x] T021 [US2] Persist diagnosis reports and directional-polish links in `apps/backend/app/services/workbench.py`
- [x] T022 [US2] Add diagnose-draft and diagnosis-driven polish request handling in `apps/backend/app/api/projects.py` and `apps/backend/app/schemas/projects.py`
- [x] T023 [US2] Extend frontend API payloads for diagnosis requests and diagnosis-driven polish in `apps/frontend/src/api/workbench.ts`
- [x] T024 [US2] Surface draft-stage diagnosis actions and objective selection in `apps/frontend/src/pages/WorkbenchPage.tsx` and `apps/frontend/src/view-models/workbenchActions.ts`
- [x] T025 [US2] Render diagnosis findings and linked revision history in `apps/frontend/src/view-models/workbenchPreview.ts` and `apps/frontend/src/view-models/workbenchHistory.ts`
- [x] T026 [US2] Add draft-stage diagnosis and directional-polish styling in `apps/frontend/src/styles.css`

**Checkpoint**: Operators can see what is wrong with a draft and launch a revision tied to a specific diagnosis objective.

---

## Phase 5: User Story 3 - Generate A Creative Review Report For Each Project (Priority: P2)

**Goal**: Produce one project-level report that summarizes strategy, diagnosis, revisions, and retained lessons.

**Independent Test**: Use a project with strategy artifacts and at least one revised draft, generate a creative review report, and confirm that the report still works on a legacy project with partial history.

### Tests for User Story 3

- [x] T027 [P] [US3] Add backend tests for creative review reports on full and legacy projects in `apps/backend/tests/test_app.py` and `apps/backend/tests/test_creative_reports.py`
- [x] T028 [P] [US3] Add frontend tests for publish-stage creative report actions and preview rendering in `apps/frontend/src/view-models/workbenchActions.test.ts` and `apps/frontend/src/view-models/workbenchPreview.test.ts`

### Implementation for User Story 3

- [x] T029 [P] [US3] Implement creative review report synthesis in `apps/backend/app/services/creative_reports.py`
- [x] T030 [US3] Persist and load creative review report artifacts in `apps/backend/app/services/workbench.py`
- [x] T031 [US3] Add creative review report route and response wiring in `apps/backend/app/api/projects.py` and `apps/frontend/src/api/workbench.ts`
- [x] T032 [US3] Surface publish-stage report generation and report preview in `apps/frontend/src/pages/WorkbenchPage.tsx` and `apps/frontend/src/view-models/workbenchPreview.ts`
- [x] T033 [US3] Add publish-stage creative-report styling and empty states in `apps/frontend/src/styles.css`

**Checkpoint**: A project can produce one review artifact that explains how the article was framed and revised.

---

## Phase 6: User Story 4 - Promote Lessons Into A Reusable Pattern Library (Priority: P3)

**Goal**: Let operators promote reusable lessons from reports and reference them in future strategy work.

**Independent Test**: Promote one retained lesson from a report, open another project, and verify that the saved pattern appears as an optional reusable reference during strategy setup and in settings management.

### Tests for User Story 4

- [x] T034 [P] [US4] Add backend tests for reusable-pattern promotion and listing in `apps/backend/tests/test_app.py` and `apps/backend/tests/test_creative_reports.py`
- [x] T035 [P] [US4] Add frontend tests for settings-level pattern navigation and project reuse hints in `apps/frontend/src/app/navigation.test.ts` and `apps/frontend/src/view-models/workbenchPreview.test.ts`

### Implementation for User Story 4

- [x] T036 [P] [US4] Implement reusable-pattern promotion and listing services in `apps/backend/app/services/creative_patterns.py` and `apps/backend/app/services/creative_reports.py`
- [x] T037 [US4] Add reusable-pattern routes and promotion payload handling in `apps/backend/app/api/creative_patterns.py`, `apps/backend/app/api/projects.py`, and `apps/backend/app/api/__init__.py`
- [x] T038 [US4] Extend frontend API clients and data types for reusable patterns in `apps/frontend/src/api/workbench.ts`
- [x] T039 [US4] Add settings navigation and reusable-pattern management views in `apps/frontend/src/app/navigation.ts` and `apps/frontend/src/pages/SettingsPage.tsx`
- [x] T040 [US4] Surface reusable-pattern hints during strategy setup in `apps/frontend/src/pages/WorkbenchPage.tsx` and `apps/frontend/src/view-models/workbenchPreview.ts`
- [x] T041 [US4] Add reusable-pattern management and strategy-hint styling in `apps/frontend/src/styles.css`

**Checkpoint**: Lessons can be promoted from one project and safely reused as optional references in another.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Validate the feature end-to-end, clean up null-state handling, and confirm compatibility with legacy projects.

- [x] T042 [P] Harden null-state and compatibility handling across `apps/backend/app/services/workbench.py`, `apps/frontend/src/pages/WorkbenchPage.tsx`, and `apps/frontend/src/view-models/workbenchPreview.ts`
- [x] T043 [P] Run backend verification with `python -m pytest apps/backend/tests/test_app.py apps/backend/tests/test_creative_strategy.py apps/backend/tests/test_content_diagnosis.py apps/backend/tests/test_creative_reports.py`
- [x] T044 [P] Run frontend verification with `cd apps/frontend && npm test && npm run build`
- [x] T045 Run manual quickstart verification from `specs/004-creative-workflow/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1: Setup**: starts immediately
- **Phase 2: Foundational**: depends on Phase 1 and blocks all user stories
- **Phase 3: US1**: starts after Phase 2
- **Phase 4: US2**: starts after Phase 2 and gains full value once US1 strategy artifacts exist
- **Phase 5: US3**: starts after Phase 2 and gains full value once US1 and US2 are present
- **Phase 6: US4**: depends on US3 because report output is the promotion source
- **Phase 7: Polish**: depends on all desired user stories being complete

### User Story Dependencies

- **US1**: independent after Phase 2
- **US2**: independent after Phase 2, but should be validated again after US1 because upstream findings rely on strategy artifacts
- **US3**: can work with legacy projects, but is most valuable after US1 and US2
- **US4**: depends on US3 and is most useful once US1 patterns can be referenced during strategy setup

### Within Each User Story

- Backend tests should be added before considering the story complete
- Backend owner modules should land before route wiring
- Route wiring should land before frontend action surfacing
- Workbench rendering should land before manual quickstart verification

### Parallel Opportunities

- T002 and T003 can run in parallel
- T005 and T006 can run in parallel
- T009 and T010 can run in parallel
- T018 and T019 can run in parallel
- T027 and T028 can run in parallel
- T034 and T035 can run in parallel
- T043 and T044 can run in parallel

---

## Parallel Example: User Story 1

```text
T009 [US1] Add backend tests for strategy package generation, ambiguous-input handling, and strategy adoption in apps/backend/tests/test_app.py and apps/backend/tests/test_creative_strategy.py
T010 [US1] Add frontend tests for topic-stage strategy actions and stage recommendation behavior in apps/frontend/src/view-models/workbenchActions.test.ts and apps/frontend/src/view-models/workbenchStages.test.ts
```

```text
T011 [US1] Implement problem-brief, benchmark, and strategy-card generation logic in apps/backend/app/services/creative_strategy.py
T014 [US1] Extend frontend client calls and payload types for strategy actions in apps/frontend/src/api/workbench.ts
```

---

## Implementation Strategy

### MVP First

1. Complete Phase 1 and Phase 2
2. Complete US1 so the workbench can generate and adopt a real prewriting strategy package
3. Validate the operator can still use the old direct path if strategy is skipped

### Incremental Delivery

1. Add additive persistence and response scaffolding
2. Add strategy generation and adoption
3. Add diagnosis and directional polish
4. Add creative review reports
5. Add reusable pattern promotion and settings management
6. Finish with compatibility hardening and end-to-end verification

### Parallel Team Strategy

With multiple developers:

1. One developer handles backend persistence and owner modules
2. One developer handles project API and schema wiring
3. One developer handles workbench action/rendering and settings management
4. Merge only after each story is independently testable

---

## Notes

- `[P]` tasks are safe to parallelize because they target different files or isolated test helpers
- Keep creative workflow logic backend-owned; do not rebuild business rules only in preview helpers
- Preserve the existing direct draft-generation and manual-polish paths while the new workflow is added
- Do not copy dbskill knowledge assets or prompt text verbatim into product runtime files
