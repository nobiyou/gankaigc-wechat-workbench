# Tasks: Scheduled WeChat MP Draft Automation

Input: Design documents from specs/005-wechat-mp-automation/

Prerequisites: plan.md, spec.md, research.md, data-model.md, contracts/automation-api.md, quickstart.md

Tests: Included because the feature specification defines independent test scenarios and the user requested verification.

## Phase 1: Setup

Purpose: Establish feature-owned modules and test surfaces without changing existing manual owner behavior.

- [x] T001 Add the automation schema, API, service, runner, and focused test paths listed in specs/005-wechat-mp-automation/plan.md
- [x] T002 [P] Add automation request/response models and enum literals in apps/backend/app/schemas/wechat_mp_automation.py
- [x] T003 [P] Add frontend automation type/helper test registration in apps/frontend/src/automation.test.ts and apps/frontend/src/test.ts

## Phase 2: Foundational

Purpose: Add durable storage and shared validation/claim primitives that every user story depends on.

- [x] T004 Implement additive SQLite migrations for subscriptions, runs, workflows, and leases in apps/backend/app/services/wechat_mp_automation.py and call them from apps/backend/app/services/workbench.py store initialization/reset
- [x] T005 Add schedule/timezone/limit validation, UTC/local-date conversion, next-run calculation, and bounded error normalization in apps/backend/app/services/wechat_mp_automation.py
- [x] T006 Add atomic SQLite lease acquisition/release and unique scheduled subscription/date claim helpers in apps/backend/app/services/wechat_mp_automation.py
- [x] T007 [P] Add default scheduler poll interval and lease configuration to apps/backend/app/core/settings.py
- [x] T008 [P] Add automation log/status labels for the existing task surfaces in apps/frontend/src/taskLabels.ts
- [x] T009 Add foundational backend tests for schema initialization/reset, invalid schedules, timezone due checks, lease expiry, and concurrent scheduled claims in apps/backend/tests/test_wechat_mp_automation.py

Checkpoint: Automation storage and claims are durable, validated, and independently testable before any content workflow is started.

## Phase 3: User Story 1 - Manage Scheduled Source Accounts (Priority: P1) MVP

Goal: Subscribe/unsubscribe stable WeChat accounts discovered from the existing QR session, with editable schedule and automatic draft settings.

Independent Test: Create two subscriptions with the same nickname and different fakeids, disable one, and verify only the enabled subscription is due with its configured next run.

### Tests for User Story 1

- [x] T010 [US1] Add service/API tests for create, list, update, soft-disable, duplicate fakeid conflict, same-nickname separation, and disabled-subscription exclusion in apps/backend/tests/test_wechat_mp_automation.py
- [x] T011 [P] [US1] Add frontend view-model tests for subscription defaults, schedule labels, enabled toggling, and same-nickname account identity in apps/frontend/src/automation.test.ts

### Implementation for User Story 1

- [x] T012 [US1] Implement subscription CRUD/list and next-run serialization in apps/backend/app/services/wechat_mp_automation.py
- [x] T013 [US1] Implement subscription schemas with defaults of 21:00, Asia/Shanghai, fetch limit 1, and automatic draft enabled in apps/backend/app/schemas/wechat_mp_automation.py
- [x] T014 [US1] Add subscription management API routes under apps/backend/app/api/wechat_mp_automation.py and register them in apps/backend/app/api/__init__.py
- [x] T015 [US1] Add the Automation page route/navigation entry in apps/frontend/src/app/routes.tsx and apps/frontend/src/app/navigation.ts
- [x] T016 [US1] Add subscription API calls and the management form/list in apps/frontend/src/api/workbench.ts and apps/frontend/src/pages/AutomationPage.tsx

Checkpoint: An operator can select an account payload from the existing WeChat account search, save its schedule, disable it, and see next-run metadata.

## Phase 4: User Story 2 - Turn the Latest Source Article Into a WeChat Draft (Priority: P1)

Goal: Process at most the configured number of newest unseen articles per enabled account through the existing content chain and write only the resulting draft box item.

Independent Test: Mock one account/session/article and the existing stage owners, run one due subscription, and verify one tracked article, project chain, formatted package, automatic approval marker, and draft-box write with no group-send call.

### Tests for User Story 2

- [x] T017 [US2] Add orchestration tests for newest-unseen selection, fetch limit, manual-import duplicate skip, independent multi-account results, automatic draft-only behavior, and provenance in apps/backend/tests/test_wechat_mp_automation.py
- [x] T018 [P] [US2] Add API contract tests for immediate run submission and run polling in apps/backend/tests/test_wechat_mp_automation.py

### Implementation for User Story 2

- [x] T019 [US2] Implement source identity normalization, account article fetch, article-body import, duplicate detection, and workflow-row creation in apps/backend/app/services/wechat_mp_automation.py
- [x] T020 [US2] Implement resumable calls to tracked article import, topic generation, project creation, outline, draft, assets, and publish-package stages in apps/backend/app/services/wechat_mp_automation.py
- [x] T021 [US2] Add explicit automatic package approval and draft-write provenance fields/migration while preserving manual behavior in apps/backend/app/services/workbench.py, apps/backend/app/schemas/projects.py, and apps/backend/app/services/wechat_mp_draft_publisher.py
- [x] T022 [US2] Implement the shared scheduled/manual run executor and draft-box completion persistence in apps/backend/app/services/wechat_mp_automation.py
- [x] T023 [US2] Add due-cycle evaluation and scheduler loop in apps/backend/app/services/wechat_mp_automation.py, starting it from apps/backend/app/main.py lifespan
- [x] T024 [US2] Add immediate run and due-cycle API routes in apps/backend/app/api/wechat_mp_automation.py
- [x] T025 [US2] Add run status types, immediate-run action, and draft status/provenance display in apps/frontend/src/api/workbench.ts and apps/frontend/src/pages/AutomationPage.tsx

Checkpoint: One unseen article can complete the same content path as manual production and remain only in the公众号草稿箱.

## Phase 5: User Story 3 - Observe and Recover Automation Runs (Priority: P1)

Goal: Persist stage-level progress/errors and resume incomplete workflows after failure or service restart without duplicate artifacts or draft writes.

Independent Test: Force failures at session validation, import, AI, cover, HTML, and draft-write stages; verify explicit failed stage/error, session status update, retryability, and stage resume.

### Tests for User Story 3

- [x] T026 [US3] Add failure-stage, session-expiry, restart-resume, next-cycle retry, manual retry, and no-duplicate artifact tests in apps/backend/tests/test_wechat_mp_automation.py
- [x] T027 [P] [US3] Add run-history/retry UI helper tests for error detail and retry availability in apps/frontend/src/automation.test.ts

### Implementation for User Story 3

- [x] T028 [US3] Implement run detail/list hydration, workflow links, retry eligibility, and latest-run subscription summaries in apps/backend/app/services/wechat_mp_automation.py
- [x] T029 [US3] Implement retry route using the existing workflow identity in apps/backend/app/api/wechat_mp_automation.py
- [x] T030 [US3] Add persistent run-history, stage/error, project/preview links, draft status, and retry controls in apps/frontend/src/pages/AutomationPage.tsx
- [x] T031 [US3] Expose session-expired automation failures through the existing WeChat session state and verify no same-cycle retry in apps/backend/app/services/wechat_mp_automation.py and apps/backend/tests/test_wechat_mp_automation.py

Checkpoint: A failed run is actionable, visible, and resumable; restarting or retrying does not recreate completed content artifacts.

## Phase 6: User Story 4 - Test and Preview the Automated Result (Priority: P2)

Goal: Let the operator execute an enabled subscription immediately and open the generated project/formatted preview from run history.

Independent Test: Start an immediate run, poll it to completion, and verify links to the project publish stage, generated HTML preview, source reference, selected style, and draft status.

### Tests for User Story 4

- [x] T032 [US4] Add success/failure run-detail contract tests for project link, HTML preview URL, style, source reference, and draft status in apps/backend/tests/test_wechat_mp_automation.py
- [x] T033 [P] [US4] Add frontend tests for preview/project link rendering and failed-run detail states in apps/frontend/src/automation.test.ts

### Implementation for User Story 4

- [x] T034 [US4] Add run-detail result serialization with source/project/package/preview URLs in apps/backend/app/services/wechat_mp_automation.py
- [x] T035 [US4] Add run detail and preview link rendering in apps/frontend/src/pages/AutomationPage.tsx
- [x] T036 [US4] Add the optional cross-platform resident runner using the same scheduler in apps/backend/app/automation_runner.py

Checkpoint: The operator can validate the automation without waiting for 21:00 and inspect the formatted article before any later manual action.

## Phase 7: Polish & Cross-Cutting Concerns

Purpose: Verify the full feature, preserve existing manual workflows, and keep the implementation within the no-group-send boundary.

- [x] T037 [P] Add backend regression coverage for manual import, manual package approval, manual draft writing, and existing session routes in apps/backend/tests/test_wechat_mp_automation.py
- [x] T038 [P] Add frontend navigation/build regression coverage for existing sources, pipeline, projects, settings, and workbench routes in apps/frontend/src/app/navigation.test.ts and apps/frontend/src/automation.test.ts
- [x] T039 Run focused backend tests for apps/backend/tests/test_wechat_mp_automation.py and related WeChat/workbench tests; record results in specs/005-wechat-mp-automation/tasks.md
- [x] T040 Run frontend npm test and npm run build in apps/frontend; record results in specs/005-wechat-mp-automation/tasks.md
- [x] T041 Run git diff --check, inspect the task-owned diff against the TaskStartSnapshot, and verify no AppID/AppSecret or final group-send path was introduced
- [x] T042 Update docs/aegis/work/2026-08-26-wechat-mp-automation/ checkpoint, evidence, drift, and reflection records after fresh verification

## Verification Note (2026-08-26)

- Automation tests: `16 passed`.
- WeChat-related backend tests (`automation`, draft publisher, HTML, import, styles): `55 passed`.
- Frontend `npm test` and `npm run build`: passed.
- `git diff --check`: passed; no new AppID/AppSecret or final group-send path was introduced.
- The fresh full command `python -m pytest apps/backend/tests -q` returned `978 passed, 6 failed`; all six failures are in pre-existing content-quality tests outside this task's automation files and remain unresolved: three tracked-article/material cases in `test_app.py`, two dbskill bridge strategy cases, and one complete-contract cover prompt case.

## Dependencies & Execution Order

### Phase Dependencies

- Setup (Phase 1) has no implementation dependency.
- Foundational (Phase 2) depends on Setup and blocks all user stories.
- US1 and US2 are both P1, but US2 depends on the schema/claim primitives from Phase 2 and the subscription payload from US1.
- US3 depends on the run executor from US2 and can then be completed independently from the UI.
- US4 depends on run detail data from US3 and the existing preview artifacts.
- Polish depends on the desired user stories being implemented.

### User Story Dependencies

- US1: Starts after Foundational; provides subscription management and defaults.
- US2: Starts after Foundational and uses US1 subscription records; delivers the MVP article-to-draft path.
- US3: Depends on US2 executor and state transitions; hardens recovery and observability.
- US4: Depends on US2 immediate run and US3 run detail; adds operator preview ergonomics.

### Parallel Opportunities

- T002, T003, and T007 can run in parallel during Setup.
- T010/T011 can run in parallel before US1 implementation.
- T017/T018 can run in parallel before US2 implementation, but implementation touching the same service file remains sequential.
- T026/T027 and T032/T033 can run in parallel with their respective backend/frontend implementation slices.
- T037/T038 can run in parallel after the main feature paths stabilize.

## Implementation Strategy

### MVP First

1. Complete Setup and Foundational phases.
2. Complete US1 subscription management.
3. Complete US2 article-to-draft orchestration.
4. Validate the one-account immediate/due-cycle flow and no-group-send boundary.

### Incremental Delivery

1. Add US3 failure/resume observability without changing content owners.
2. Add US4 preview/run-detail ergonomics and resident runner.
3. Run cross-cutting regression/build checks.

### Notes

- Every task follows the required checkbox + ID + optional parallel/story label format and includes an exact file path.
- The automation service may call existing owner functions but must not create a second project/content pipeline.
- A successful automated run means draft-box write only; it is never a public WeChat group send.
