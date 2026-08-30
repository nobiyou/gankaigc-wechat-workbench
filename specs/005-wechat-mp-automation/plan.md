# Implementation Plan: Scheduled WeChat MP Draft Automation

**Branch**: `codex/005-wechat-mp-automation` | **Date**: 2026-08-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-wechat-mp-automation/spec.md`

This plan is the feature-level owner for the approved cross-platform scheduler. It keeps the existing manual workbench and QR-session draft route as compatibility boundaries.

## Summary

Add a persisted scheduled automation layer that selects explicitly subscribed WeChat public accounts, fetches the newest unseen source article at the subscription's local 21:00 schedule, resumes the existing tracked-article -> topic -> project -> outline -> draft -> assets -> formatted publish package chain, and writes only the approved result to the WeChat draft box. The scheduler runs inside the FastAPI process and is also exposed through the same service as an optional cross-platform resident runner; SQLite stores subscriptions, durable run/workflow state, and atomic claim records.

## Technical Context

**Language/Version**: Python 3.11, TypeScript 5.8, React 19.1

**Primary Dependencies**: FastAPI, Uvicorn lifespan, Pydantic, sqlite3, zoneinfo, threading, httpx, React, React Router, Vite

**Storage**: Existing SQLite workbench store plus automation-owned subscription, run, workflow-state, and lease tables; existing generated-assets directory remains the artifact store

**Testing**: pytest for service/API/persistence/concurrency cases; frontend helper tests via `npm test`; frontend type/build verification via `npm run build`

**Target Platform**: Windows, Linux, and macOS with a running FastAPI process or `python -m app.automation_runner --loop`; no OS task scheduler

**Project Type**: Full-stack local web application with a persistent background scheduler and optional resident CLI runner

**Performance Goals**: Scheduler poll interval is configurable and defaults to 30 seconds; due evaluation begins within 5 minutes of a subscription's local schedule; one subscription's failure must not block other due subscriptions

**Constraints**: Reuse existing workflow owners; persist after every stage; one current-date catch-up only; no unbounded immediate retry; automatic path writes draft box only; do not add AppID/AppSecret; preserve manual routes and user dirty files

**Scale/Scope**: Single operator, a small number of subscribed public accounts, one sequential article pipeline per scheduler instance, one automation management/run-history view

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository `.specify/memory/constitution.md` is still a template and does not provide operative principles. The effective governance surface is `AGENTS.md`, `docs/aegis/BASELINE-GOVERNANCE.md`, the current direction plan, and the existing `004` feature artifacts.

Gate result: PASS

- Feature-level design remains under `specs/005-wechat-mp-automation/`; no duplicate feature plan is added under `docs/aegis/plans/`.
- Existing QR-session, manual import, manual workbench, preview, review, and draft-box routes remain owners of those manual actions.
- Scheduling, subscription, cursor, run history, workflow resumption, and automation provenance have one new owner: `wechat_mp_automation`.
- SQLite uniqueness plus an atomic lease claim is required before processing; automatic final group-send remains outside scope.
- The missing `docs/current/AEGIS_MINIMALITY_REFERENCE.md` is recorded as an authority gap, not silently invented.

## Baseline / Authority Refs

- `AGENTS.md`
- `docs/aegis/BASELINE-GOVERNANCE.md`
- `docs/aegis/specs/2026-05-18-spec-kit-aegis-operating-model.md`
- `docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md`
- `docs/aegis/baseline/2026-05-16-gankaigc-content-domain-file-mapping.md`
- `specs/004-creative-workflow/spec.md`
- `specs/004-creative-workflow/plan.md`
- `apps/backend/app/services/workbench.py`
- `apps/backend/app/services/wechat_mp_client.py`
- `apps/backend/app/services/wechat_mp_draft_publisher.py`
- `apps/backend/app/api/wechat_mp.py`
- `apps/backend/app/api/projects.py`
- `apps/backend/app/main.py`
- `apps/frontend/src/app/navigation.ts`
- `apps/frontend/src/app/routes.tsx`

## Compatibility Boundary

- Keep `/wechat-mp/session`, QR login, account search, article listing, and manual import behavior unchanged.
- Keep `workbench.py` as the owner of tracked articles, topics, projects, outlines, drafts, assets, publish packages, previews, and manual review.
- Keep `publish_wechat_mp_draft()` as the only low-level manual/automatic draft-box adapter; extend it with an explicit provenance parameter without adding a group-send route.
- Automatic approval is an internal, provenance-marked transition to the existing `approved` package state; it does not expose or call final publication.
- All pre-existing dirty files are outside this task's staging/commit scope.

## Project Structure

### Documentation (this feature)

```text
specs/005-wechat-mp-automation/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── automation-api.md
└── tasks.md
```

### Source Code (repository root)

```text
apps/
├── backend/
│   ├── app/
│   │   ├── api/wechat_mp_automation.py
│   │   ├── schemas/wechat_mp_automation.py
│   │   ├── services/wechat_mp_automation.py
│   │   └── automation_runner.py
│   └── tests/test_wechat_mp_automation.py
└── frontend/
    └── src/
        ├── pages/AutomationPage.tsx
        ├── api/workbench.ts
        ├── app/navigation.ts
        ├── app/routes.tsx
        ├── automation.test.ts
        └── test.ts
```

**Structure Decision**: Keep the scheduler as a backend service owner beside the existing WeChat and workbench services. The API layer only validates and serializes automation commands. The FastAPI lifespan starts one in-process scheduler per process; SQLite durable claims make multiple processes safe. The optional runner imports the same scheduler and does not create a second workflow. The frontend adds one top-level Automation view so subscriptions and run history are visible without hiding the feature in an unrelated project screen.

## Phase 0 Research Summary

See [research.md](./research.md). Decisions resolved before implementation:

- `zoneinfo.ZoneInfo` stores and evaluates per-subscription time zones.
- Durable unique scheduled run keys are the primary idempotency boundary; `automation_locks` is the short-lived cross-process lease.
- Existing synchronous workbench functions are called one stage at a time and their returned identifiers are persisted in workflow state.
- Automatic draft writing uses an internal provenance-marked approval and the existing draft adapter; no AppID/AppSecret path is added.

## Phase 1 Design Summary

See [data-model.md](./data-model.md), [contracts/automation-api.md](./contracts/automation-api.md), and [quickstart.md](./quickstart.md). The design covers subscriptions, runs, source identity/workflow state, lease claims, manual run/retry actions, status polling, and preview/project links.

## Implementation Slices

1. Add schemas, SQLite migrations, and service primitives for subscription/run/workflow state and atomic claims.
2. Add the resumable automation orchestrator and cross-platform scheduler/runner, including explicit automatic approval/draft provenance.
3. Add API routes and frontend management/run-history/preview links.
4. Add focused backend and frontend verification, then run the existing regression/build suites.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| New persisted automation owner | The schedule, resume state, and source identity must survive process restarts and be visible independently of a project | Reusing `background_tasks` would lose subscription/date uniqueness and stage-level recovery semantics |
| Optional resident runner | A non-Windows process entry point is required when the API is not the preferred long-lived host | Delegating to Windows Task Scheduler would violate the cross-platform requirement |

## Authority Gaps / Deferred Work

- `docs/current/AEGIS_MINIMALITY_REFERENCE.md` is not present in the repository; no content is fabricated for it.
- Automatic group-send, multi-user permissions, and fully stopped-machine wake-up remain explicitly out of scope.
