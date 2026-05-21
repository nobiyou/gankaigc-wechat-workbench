# Implementation Plan: Source Ingestion And Freshness

**Branch**: `[002-source-ingestion]` | **Date**: 2026-05-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-source-ingestion/spec.md`

**Note**: This plan turns the approved next batch into an implementation slice focused on source-side operability before deeper provider expansion.

## Summary

Strengthen the upstream source layer by adding persisted ingestion-run tracking, duplicate-safe WeChat article imports, default-eligible batch topic generation, and dashboard freshness signals. This batch keeps the existing downstream project chain intact and improves operator trust in the source pool.

## Technical Context

**Language/Version**: Python 3.11, TypeScript 5.8, React 19.1

**Primary Dependencies**: FastAPI, Pydantic, sqlite3, React, React Router, Vite

**Storage**: SQLite via `apps/backend/app/services/workbench.py`

**Testing**: `pytest`, frontend helper tests via `npm test`, frontend build, existing smoke script `node scripts/verify-workbench-ui-smoke.cjs`

**Target Platform**: Local desktop-first web app on Windows, serving FastAPI + React

**Project Type**: Full-stack web application with backend in `apps/backend` and frontend in `apps/frontend`

**Performance Goals**: Keep source imports responsive for small manual batches and preserve current dashboard/page load expectations

**Constraints**:

- Do not redesign the downstream `topic -> outline -> draft -> assets -> publish` chain
- Reuse the current SQLite store instead of introducing a migration framework
- Preserve current routes and UI information architecture from `001-workbench-ui-restructure`

**Scale/Scope**: One backend service module, a few API schema/route updates, dashboard summary extension, and source import UI adjustments

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository still relies on project rules plus Aegis baseline as the effective constitution surface.

Gate result: PASS

- Feature artifacts live only under `specs/002-source-ingestion/`
- Project-level source-of-truth docs remain under `docs/aegis/`
- The existing content chain stays intact; this batch only improves source-side intake and visibility
- No duplicate feature plan is created under `docs/aegis/plans/`

## Baseline / Authority Refs

- `AGENTS.md`
- `docs/aegis/BASELINE-GOVERNANCE.md`
- `docs/aegis/specs/2026-05-18-spec-kit-aegis-operating-model.md`
- `docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md`
- `docs/aegis/baseline/2026-05-16-gankaigc-content-domain-file-mapping.md`
- `specs/001-workbench-ui-restructure/plan.md`
- `apps/backend/app/services/workbench.py`
- `apps/backend/app/api/trends.py`
- `apps/backend/app/api/tracked_articles.py`
- `apps/backend/app/api/wechat_mp.py`
- `apps/backend/app/services/wechat_mp_client.py`
- `apps/backend/tests/test_app.py`
- `apps/backend/tests/test_wechat_mp_import.py`
- `apps/frontend/src/api/workbench.ts`
- `apps/frontend/src/pages/DashboardPage.tsx`
- `apps/frontend/src/components/WechatMpImportPanel.tsx`

## Compatibility Boundary

- Preserve current API routes for trends, tracked articles, dashboard, and WeChat MP import
- Preserve existing tracked-article and trend entities while extending them with stronger ingestion behavior
- Preserve current dashboard queues and add source-freshness signals without changing primary navigation
- Preserve existing background task shapes for pipeline batch runs

## Project Structure

### Documentation (this feature)

```text
specs/002-source-ingestion/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── source-ingestion-contract.md
└── tasks.md
```

### Source Code (repository root)

```text
apps/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── dashboard.py
│   │   │   ├── tracked_articles.py
│   │   │   ├── trends.py
│   │   │   └── wechat_mp.py
│   │   ├── schemas/
│   │   │   ├── tracked_articles.py
│   │   │   ├── trends.py
│   │   │   └── wechat_mp.py
│   │   └── services/
│   │       ├── wechat_mp_client.py
│   │       └── workbench.py
│   └── tests/
│       ├── test_app.py
│       └── test_wechat_mp_import.py
└── frontend/
    └── src/
        ├── api/workbench.ts
        ├── components/WechatMpImportPanel.tsx
        ├── pages/DashboardPage.tsx
        └── view-models/
            └── dashboardRecentTasks.ts
```

**Structure Decision**: Keep the feature inside the existing backend service and current routed frontend. Avoid adding new top-level modules until source providers themselves become a separate subsystem.

## Risks

- The current backend concentrates a lot of behavior in `workbench.py`; changes must stay surgical to avoid regressions in the downstream project chain.
- Dashboard payload changes can silently break frontend assumptions if types and render logic are not updated together.
- Import deduplication must preserve current manual tracked-article creation behavior.

## Verification

- Add backend tests for trend import summaries, duplicate-safe WeChat imports, dashboard freshness, and default eligible-pool batch generation
- Run focused backend tests first
- Run frontend tests and build after updating dashboard and import UI
- Run existing smoke verification to ensure route-level behavior still works

## Retirement / Follow-up

- This batch does not yet add third-party trend-provider fetch adapters such as specific hot-list crawlers
- If source providers expand, split provider adapters and ingestion runs into dedicated modules after this operational baseline is stable
