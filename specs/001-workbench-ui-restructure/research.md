# Research: Workbench UI Restructure

## Decision 1: Use Route-Driven Workspace Navigation

**Decision**: Replace the current section-stacked single page with explicit top-level routes for `Dashboard`, `Sources`, `Pipeline`, `Projects`, and `Settings`, plus a project-scoped workbench route.

**Rationale**:

- The main problem is information architecture, not missing visual polish
- Explicit routes make page ownership clearer and eliminate the current “scroll through everything” experience
- Browser navigation, deep links, and manual QA all become simpler when work modes have real paths

**Alternatives considered**:

- Keep one page and hide/show sections with tabs: rejected because state ownership and page sprawl remain mixed
- Make every object its own first-level page: rejected because it promotes object taxonomy over daily workflow

## Decision 2: Keep Data Access in Existing API Layer and Extract View-Model Helpers First

**Decision**: Continue using `apps/frontend/src/api/workbench.ts` as the frontend API boundary and extract pure view-model/helper modules before introducing any new client-side state framework.

**Rationale**:

- The refactor goal is page ownership and navigation clarity, not a data-layer rewrite
- Existing helper tests already use a lightweight pure-function harness, which fits extracted derivation modules well
- A shared data-loading hook or page-level fetch orchestration can be added without expanding the dependency surface

**Alternatives considered**:

- Introduce a dedicated state library during the UI refactor: rejected because it adds a second architectural change at the same time
- Leave all derivation logic inside page components: rejected because it would recreate another monolith under different filenames

## Decision 3: Put Workbench Stage in the URL

**Decision**: The workbench should use a route shape that encodes project identity and active stage, for example `/projects/:projectSlug/workbench/:stage`.

**Rationale**:

- Stage selection becomes deep-linkable and browser-history friendly
- Manual QA can validate exact stages directly
- Invalid or missing stages can be normalized centrally by the workbench route

**Alternatives considered**:

- Keep stage selection only in component state: rejected because refresh and deep-link behavior become fragile
- Encode stage in query string only: rejected because stage is part of the primary interaction model, not a secondary filter

## Decision 4: Reuse Existing Test Style for Refactor-Safe Helpers

**Decision**: Add tests primarily around pure view-model helpers for navigation, dashboard queues, project grouping, and workbench stage/history derivation, then rely on `npm run build` plus manual browser smoke verification for route-level behavior.

**Rationale**:

- The current frontend already uses Node-powered TypeScript helper tests
- Introducing a new component-test stack would expand the scope beyond the approved refactor
- The riskiest logic in this refactor is derivation and redistribution of responsibilities, which is well-suited to pure-function tests

**Alternatives considered**:

- Add a full component testing library during this refactor: rejected because it widens scope and slows the structural rewrite
- Skip tests and rely only on manual validation: rejected because queue and stage derivation regressions are easy to miss without executable checks
