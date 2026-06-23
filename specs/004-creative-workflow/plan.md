# Implementation Plan: Creative Workflow

**Branch**: `[004-creative-workflow]` | **Date**: 2026-05-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-creative-workflow/spec.md`

**Note**: This plan converts the approved “full creative workflow” direction into a repository-native implementation slice, without introducing a second agent-runtime-style system.

## Summary

Add a project-native creative workflow on top of the existing content pipeline by introducing explicit prewriting strategy artifacts, draft diagnosis, diagnosis-driven polish, creative review reports, and a reusable pattern library. Keep the existing `topic -> outline -> draft -> assets -> publish` chain intact, but insert new creative judgment layers into the existing Topic, Draft, and Publish workbench stages.

## Technical Context

**Language/Version**: Python 3.11, TypeScript 5.8, React 19.1

**Primary Dependencies**: FastAPI, Pydantic, sqlite3, React, React Router, Vite

**Storage**: Existing SQLite workbench store, extended with new creative-workflow artifact tables

**Testing**: `pytest`, frontend helper tests via `npm test`, frontend build via `npm run build`

**Target Platform**: Local desktop-first web app on Windows, serving FastAPI + React

**Project Type**: Full-stack web application with backend in `apps/backend` and frontend in `apps/frontend`

**Performance Goals**:

- Preserve current single-operator workbench responsiveness for normal navigation
- Keep strategy, diagnosis, and report generation within existing operator tolerance for AI-backed actions
- Reuse background-task flow only for chained actions that are materially slower than the current synchronous draft path

**Constraints**:

- Preserve the existing direct writing path for operators who skip full prewriting rigor
- Keep business logic in backend owner modules rather than adding more preview-only heuristics
- Preserve current draft, asset, publish-package, and retro histories
- Do not copy dbskill text assets or knowledge files directly into the product runtime
- Avoid a second parallel project system; all new artifacts remain project-owned extensions of the current workbench

**Scale/Scope**: One additive workflow slice spanning backend services, project APIs, SQLite persistence, workbench actions, settings-level pattern management, and targeted frontend stage rendering

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository still relies on project rules plus Aegis baseline as the effective constitution surface. The `.specify/memory/constitution.md` file is still a placeholder and does not override repo-local governance.

Gate result: PASS

- Feature-level artifacts live only under `specs/004-creative-workflow/`
- Project-level governance remains under `docs/aegis/`
- The current content pipeline remains the main backbone; this batch extends it with creative decision layers rather than replacing it
- No duplicate feature plan is created under `docs/aegis/plans/`

## Baseline / Authority Refs

- `AGENTS.md`
- `docs/aegis/BASELINE-GOVERNANCE.md`
- `docs/aegis/specs/2026-05-18-spec-kit-aegis-operating-model.md`
- `docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md`
- `docs/aegis/baseline/2026-05-16-gankaigc-content-domain-file-mapping.md`
- `specs/002-source-ingestion/plan.md`
- `specs/003-trend-fetch/plan.md`
- `apps/backend/app/services/workbench.py`
- `apps/backend/app/services/ai_flavor.py`
- `apps/backend/app/services/prompt_templates.py`
- `apps/backend/app/api/projects.py`
- `apps/backend/app/api/topics.py`
- `apps/backend/app/schemas/projects.py`
- `apps/backend/app/schemas/topics.py`
- `apps/frontend/src/pages/WorkbenchPage.tsx`
- `apps/frontend/src/view-models/workbenchActions.ts`
- `apps/frontend/src/view-models/workbenchStages.ts`
- `apps/frontend/src/view-models/workbenchPreview.ts`
- `apps/frontend/src/app/navigation.ts`

## Compatibility Boundary

- Preserve current routes for project detail, outline generation, draft generation, manual polish, asset generation, publish-package generation, and retro
- Preserve current topic creation flows from trend, tracked article, and manual topic entry
- Preserve current workbench top-level stage model and grow new creative steps inside existing stage surfaces where possible
- Preserve current version history behavior by recording new strategy, diagnosis, and report artifacts alongside existing project versions instead of replacing them
- Preserve operator choice between direct draft generation and the new full creative workflow

## Project Structure

### Documentation (this feature)

```text
specs/004-creative-workflow/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── creative-workflow-contract.md
└── tasks.md
```

### Source Code (repository root)

```text
apps/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── projects.py
│   │   │   └── creative_patterns.py
│   │   ├── schemas/
│   │   │   ├── projects.py
│   │   │   └── creative_workflow.py
│   │   └── services/
│   │       ├── workbench.py
│   │       ├── creative_strategy.py
│   │       ├── content_diagnosis.py
│   │       ├── creative_reports.py
│   │       └── creative_patterns.py
│   └── tests/
│       ├── test_app.py
│       ├── test_creative_strategy.py
│       ├── test_content_diagnosis.py
│       └── test_creative_reports.py
└── frontend/
    └── src/
        ├── api/workbench.ts
        ├── app/navigation.ts
        ├── pages/
        │   ├── WorkbenchPage.tsx
        │   └── SettingsPage.tsx
        └── view-models/
            ├── workbenchActions.ts
            ├── workbenchPreview.ts
            └── workbenchStages.ts
```

**Structure Decision**: Keep the creative workflow inside the existing backend + frontend application shape. Introduce dedicated backend owner modules for strategy, diagnosis, reports, and reusable patterns so that `workbench.py` stays the orchestration layer rather than absorbing every new heuristic and artifact type.

## Design Decisions Carried Into Planning

- Topic-stage workbench remains the project entry surface, but gains explicit prewriting strategy generation and strategy adoption actions
- Draft-stage workbench gains diagnosis and diagnosis-driven polish actions without removing manual polish
- Publish-stage workbench gains creative review report generation and pattern promotion
- Settings gains reusable pattern library management rather than creating a separate top-level navigation area

## Risks

- `apps/backend/app/services/workbench.py` is already large, so orchestration and owner boundaries must stay disciplined
- Adding strategy and diagnosis artifacts can confuse operators if UI actions are not explicit and stage-scoped
- Legacy projects without upstream artifacts must still work cleanly, which raises null-state and history-compatibility pressure
- Pattern-library features can become noisy quickly if everything is auto-promoted instead of operator-curated

## Verification

- Add backend tests for strategy generation, benchmark persistence, diagnosis separation, directional polish attachment, creative review reports, and pattern promotion
- Keep existing project detail and version history tests passing after response-shape extensions
- Add or update frontend tests for workbench action plans, stage rendering, and settings-level pattern surfacing
- Run backend tests first, then frontend tests and build

## Retirement / Follow-up

- This batch does not attempt to import dbskill’s original knowledge-base files into runtime storage
- This batch does not introduce autonomous pattern extraction from every project; pattern promotion stays operator-driven
- If the creative workflow keeps growing, the next retirement target is more behavior extracted out of `workbench.py`, not more UI heuristics layered into preview-only view-model code
