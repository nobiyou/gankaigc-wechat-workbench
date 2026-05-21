# Implementation Plan: Workbench UI Restructure

**Branch**: `[001-workbench-ui-restructure]` | **Date**: 2026-05-19 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-workbench-ui-restructure/spec.md`

**Note**: This plan converts the approved UI information architecture into an executable frontend refactor path without changing backend ownership.

## Summary

Refactor the frontend from a monolithic single-page workbench into a route-based, task-oriented workspace with five primary navigation modes: `Dashboard`, `Sources`, `Pipeline`, `Projects`, and `Settings`, plus a dedicated full-screen `Workbench` route for single-project production. The refactor preserves existing backend capabilities and business semantics while redistributing `Task Center` and `Version History` responsibilities into their business contexts.

## Technical Context

**Language/Version**: TypeScript 5.8, React 19.1

**Primary Dependencies**: React, React DOM, React Router DOM 7.6, Vite 6.3

**Storage**: N/A on the frontend; existing backend APIs remain the source of truth

**Testing**: `node --experimental-strip-types src/test.ts`, `npm run build`, targeted browser smoke verification on local Vite server

**Target Platform**: Desktop browser-first local web app, with baseline mobile-safe layout expectations

**Project Type**: Full-stack web application with a React frontend under `apps/frontend`

**Performance Goals**: Preserve current local responsiveness, avoid duplicate initial fetch storms, keep task-entry navigation shallow and predictable

**Constraints**:

- No backend contract redesign in this phase
- No new global state library unless extraction proves impossible without it
- No more than five primary daily-work navigation entries
- `Settings` must not compete visually with production work areas
- `Task Center` and `Version History` must retire as standalone pages

**Scale/Scope**: One frontend app, one route shell, five primary work modes, six-to-nine nested subviews, and one dedicated project workbench route extracted from a ~2800-line `App.tsx`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The repository does not yet have a filled `spec-kit` constitution, so this plan uses the enforced project rules from `AGENTS.md` plus the Aegis baseline and approved design spec as the effective governance surface.

Gate result before planning: PASS

- Feature-level spec and plan live under `specs/001-workbench-ui-restructure/`, which matches project ownership rules
- Project-level architecture and compatibility boundaries remain recorded in `docs/aegis/specs/2026-05-19-workbench-ui-information-architecture-design.md`
- The plan preserves the content chain invariant `topic -> outline -> draft -> assets -> publish`
- No backend ownership or source-of-truth changes are introduced

Post-design re-check: PASS

- Route ownership is clearer than the current single-file page
- No duplicate feature plan is created under `docs/aegis/plans/`
- Retirement path for `Task Center` and `Version History` is explicit

## Baseline / Authority Refs

- `AGENTS.md`
- `docs/aegis/BASELINE-GOVERNANCE.md`
- `docs/aegis/specs/2026-05-18-spec-kit-aegis-operating-model.md`
- `docs/aegis/specs/2026-05-19-workbench-ui-information-architecture-design.md`
- `docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md`
- `docs/aegis/baseline/2026-05-16-gankaigc-content-domain-file-mapping.md`
- `apps/frontend/src/App.tsx`
- `apps/frontend/src/main.tsx`
- `apps/frontend/package.json`

## Compatibility Boundary

- Preserve existing backend API entry points in `apps/frontend/src/api/workbench.ts`
- Preserve current business objects: trends, tracked articles, topics, projects, tone profiles, workbench chain actions
- Preserve WeChat MP import as a source-side capability, not a pipeline-wide page
- Keep `Workbench` focused on one project and keep batch orchestration in `Pipeline`
- Retire standalone `Task Center` and `Version History` views rather than re-skinning them

## Verification

- Static verification: `cd apps/frontend && npm test`
- Build verification: `cd apps/frontend && npm run build`
- Manual smoke verification: run `npm run dev`, open `http://127.0.0.1:3000/`, and verify route navigation, dashboard task entry, sources/pipeline separation, project-to-workbench entry, stage switching, history drawer access, and empty-state behavior

## Project Structure

### Documentation (this feature)

```text
specs/001-workbench-ui-restructure/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── ui-route-contract.md
└── tasks.md
```

### Source Code (repository root)

```text
apps/frontend/
├── src/
│   ├── api/
│   │   └── workbench.ts
│   ├── components/
│   │   └── WechatMpImportPanel.tsx
│   ├── App.tsx
│   ├── contentSources.ts
│   ├── main.tsx
│   ├── projectSelection.ts
│   ├── retroDraft.ts
│   ├── styles.css
│   ├── taskCenter.ts
│   ├── taskLabels.ts
│   ├── toneProfiles.ts
│   └── wechatMpImport.ts
└── package.json
```

**Structure Decision**: Introduce a route-centric frontend structure under `apps/frontend/src/` by extracting page-level components, route shell logic, and pure view-model helpers from the monolithic `App.tsx`. Keep API access in `api/workbench.ts`, keep reusable derivation logic in testable helper modules, and allow `App.tsx` to shrink into router and shell composition.

## Research Summary

Phase 0 research is captured in [research.md](./research.md). The key decisions are:

1. Use route-driven information architecture instead of conditionally hiding sections inside one page
2. Keep shared data loading in lightweight extracted hooks/helpers before considering any state library
3. Use explicit route segments for sources, pipeline views, and workbench stages so navigation can be deep-linked and browser-history friendly
4. Prefer pure helper tests plus build/manual smoke checks over introducing a heavy UI test stack in this refactor

## Design Artifacts

Phase 1 artifacts are captured in:

- [data-model.md](./data-model.md)
- [contracts/ui-route-contract.md](./contracts/ui-route-contract.md)
- [quickstart.md](./quickstart.md)

These documents define the route contract, page/workbench view models, and local verification workflow for the refactor.

## Implementation Slices

### Slice 1: Introduce App Shell and Primary Navigation

**Why**: Without a stable shell and route map, page extraction will keep collapsing back into ad hoc conditionals.

**Files**

- Modify `apps/frontend/src/App.tsx`
- Modify `apps/frontend/src/main.tsx`
- Create `apps/frontend/src/app/AppShell.tsx`
- Create `apps/frontend/src/app/routes.tsx`
- Create `apps/frontend/src/app/navigation.ts`
- Create `apps/frontend/src/app/navigation.test.ts`
- Modify `apps/frontend/src/styles.css`

**Impact / Compatibility**

- Changes top-level frontend ownership from one giant page to route shell composition
- Must preserve the existing root app boot path and avoid breaking local Vite startup
- Must not drop access to existing summary data or source/task capabilities during shell extraction

**Verification**

- `cd apps/frontend && npm test`
- `cd apps/frontend && npm run build`
- Manual: confirm primary nav renders and route transitions work for all top-level entries

**Repair Track**

- Root cause: `App.tsx` currently owns unrelated views, task derivation, and detailed workbench interactions at the same layer
- Canonical owner after repair: `App.tsx` becomes composition-only, while app shell and route modules own navigation layout

**Retirement Track**

- Old owner: top-level single-page section ordering inside `App.tsx`
- Retirement target: remove shell-level responsibility for rendering every work mode at once

### Slice 2: Split Dashboard, Sources, Pipeline, Projects, and Settings Views

**Why**: These pages are the main information architecture outcome promised by the design and spec.

**Files**

- Create `apps/frontend/src/pages/DashboardPage.tsx`
- Create `apps/frontend/src/pages/SourcesPage.tsx`
- Create `apps/frontend/src/pages/PipelinePage.tsx`
- Create `apps/frontend/src/pages/ProjectsPage.tsx`
- Create `apps/frontend/src/pages/SettingsPage.tsx`
- Create `apps/frontend/src/pages/pageTabs.ts`
- Create `apps/frontend/src/view-models/dashboardQueues.ts`
- Create `apps/frontend/src/view-models/projectGroups.ts`
- Create `apps/frontend/src/view-models/pipelineViews.ts`
- Create `apps/frontend/src/view-models/dashboardQueues.test.ts`
- Create `apps/frontend/src/view-models/projectGroups.test.ts`
- Create `apps/frontend/src/view-models/pipelineViews.test.ts`
- Modify `apps/frontend/src/taskCenter.ts`
- Modify `apps/frontend/src/taskCenter.test.ts`
- Modify `apps/frontend/src/contentSources.ts`
- Modify `apps/frontend/src/toneProfiles.ts`
- Modify `apps/frontend/src/components/WechatMpImportPanel.tsx`
- Modify `apps/frontend/src/styles.css`

**Impact / Compatibility**

- `Task Center` responsibilities must be redistributed without losing queue logic
- `Topics` moves from a visible standalone page section into `Pipeline / Topic Queue`
- `Tone Profiles` must stay available through `Settings`

**Verification**

- `cd apps/frontend && npm test`
- `cd apps/frontend && npm run build`
- Manual: confirm dashboard task cards, source subviews, pipeline subviews, grouped projects page, and settings entry all render with expected empty states

**Repair Track**

- Root cause: source browsing, pipeline execution, and project management are currently mixed at the same hierarchy level
- Canonical owner after repair: route pages own visible layout; pure view-model helpers own queue/group derivation

**Retirement Track**

- Old owner: inline `Task Center`, inline `Topics`, inline batch result sections on the same page
- Retirement target: remove their standalone full-page identity and re-home them in context

### Slice 3: Build Dedicated Project Workbench Route

**Why**: The single-project production surface is the highest-value interaction and must stop behaving like an inline section buried below lists.

**Files**

- Create `apps/frontend/src/pages/WorkbenchPage.tsx`
- Create `apps/frontend/src/view-models/workbenchStages.ts`
- Create `apps/frontend/src/view-models/workbenchHistory.ts`
- Create `apps/frontend/src/view-models/workbenchStages.test.ts`
- Create `apps/frontend/src/view-models/workbenchHistory.test.ts`
- Modify `apps/frontend/src/projectSelection.ts`
- Modify `apps/frontend/src/retroDraft.ts`
- Modify `apps/frontend/src/taskLabels.ts`
- Modify `apps/frontend/src/api/workbench.ts` only if route-friendly fetch helpers are needed without changing backend contracts
- Modify `apps/frontend/src/styles.css`
- Modify `apps/frontend/src/App.tsx`

**Impact / Compatibility**

- Must preserve the current chain semantics and project detail actions
- Must expose stage recommendation, stage switching, publish review entry, and contextual history access
- Must gracefully handle missing project slug, invalid stage, or no history

**Verification**

- `cd apps/frontend && npm test`
- `cd apps/frontend && npm run build`
- Manual: open a project, confirm left-stage nav, recommended next step, stage switching, history drawer behavior, publish review actions, and return navigation to projects

**Repair Track**

- Root cause: project workbench state is entangled with unrelated page sections and cannot provide a focused interaction model
- Canonical owner after repair: dedicated workbench route and stage view-model helpers

**Retirement Track**

- Old owner: inline `Project Workbench` section and standalone version history block
- Retirement target: replace with contextual stage history and workbench activity surfaces

### Slice 4: Remove Legacy Single-Page Surfaces and Finalize UX Consistency

**Why**: The refactor is incomplete if the old single-page sections remain partially active or duplicate the new navigation model.

**Files**

- Modify `apps/frontend/src/App.tsx`
- Modify `apps/frontend/src/styles.css`
- Modify any now-orphaned helper modules created only for the old page structure
- Optionally remove or rename obsolete selectors after their replacements are verified

**Impact / Compatibility**

- Prevent duplicate entry points that confuse users
- Preserve readable fallbacks and empty states
- Keep CSS consistent across desktop and mobile widths

**Verification**

- `cd apps/frontend && npm test`
- `cd apps/frontend && npm run build`
- Manual: verify there is no remaining standalone `Task Center` or `Version History` page, and no top-level single-page dump remains accessible as the default experience

**Repair Track**

- Root cause: residual legacy sections can silently reintroduce the same IA problems under a different visual layout
- Canonical owner after repair: new route shell and page modules only

**Retirement Track**

- Old owner: all-in-one homepage flow
- Retirement target: complete removal from the default user path

## Risks

- `App.tsx` currently combines fetching, derivation, and rendering, so extraction may create accidental duplicate fetches or stale derived state
- The current frontend test setup is pure-TypeScript helper based, so route/component regressions require disciplined manual smoke checks until a richer UI test stack exists
- CSS written for one long page may not translate cleanly to nested route layouts without explicit layout cleanup

## Rollback Surface

- If page extraction causes instability, revert by slice rather than reverting the entire refactor
- Preserve backend contract compatibility so rollback remains frontend-only
- Avoid deleting helper logic until replacement view models and manual verification have passed

## Retirement

- Retire `Task Center` as a standalone page-level concept
- Retire `Version History` as a standalone page-level concept
- Retire `App.tsx` as the primary owner of all work modes at once
- Keep batch/task logic and version logic, but relocate them into `Pipeline` and `Workbench` contexts

## Complexity Tracking

No constitution violations are currently required for this feature.
