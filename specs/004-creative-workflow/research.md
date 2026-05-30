# Research: Creative Workflow

## Decision 1: Model Creative Strategy As Project-Owned Artifacts, Not A Parallel Idea System

**Decision**: Add prewriting artifacts such as problem briefs, benchmark references, and strategy cards directly to content projects instead of creating a second stand-alone “diagnosis workspace” beside the workbench.

**Rationale**:

- The current repository already uses projects as the unit of production, versioning, and downstream publishing
- Operators need strategy, diagnosis, and report artifacts to stay attached to the same project that owns outlines, drafts, and publish packages
- A project-owned model keeps legacy history, workbench rendering, and later reporting coherent

**Alternatives considered**:

- Build a separate creative-diagnosis subsystem with its own lifecycle: rejected because it duplicates the project system and creates adoption friction
- Store strategy only as prompt text in outline generation: rejected because operators need explicit reviewable artifacts before and after writing

## Decision 2: Keep The Existing Workbench Stages, But Add Explicit Stage-Scoped Creative Actions

**Decision**: Preserve the current top-level `Topic / Outline / Draft / Assets / Publish` workbench stage model, and add explicit creative workflow actions inside those stages instead of introducing a brand-new stage tree.

**Rationale**:

- The current workbench already teaches operators where each project action belongs
- Topic stage is the natural place for strategy generation, Draft stage for diagnosis and polish, and Publish stage for reports and pattern promotion
- This keeps navigation stable while still making the new workflow visible

**Alternatives considered**:

- Add five new top-level creative stages: rejected because it would fragment the current workbench and increase operator overhead
- Hide everything behind automatic background behavior: rejected because the user explicitly wants visible, controllable creative steps

## Decision 3: Split Strategy, Diagnosis, And Report Logic Into Dedicated Backend Owner Modules

**Decision**: Keep `workbench.py` as the orchestration boundary, but move creative strategy, diagnosis, report generation, and reusable-pattern rules into focused backend service modules.

**Rationale**:

- `workbench.py` already owns too much behavior to safely absorb another large logic family
- Strategy generation, diagnosis scoring, and report synthesis are distinct owners with different tests and future evolution paths
- This keeps UI heuristics out of business rules and supports narrower backend tests

**Alternatives considered**:

- Continue adding helper blocks directly inside `workbench.py`: rejected because the file is already a bottleneck and would become harder to reason about
- Push parts of diagnosis into frontend preview helpers: rejected because the user prefers business logic to remain backend-owned

## Decision 4: Store Creative Workflow Artifacts In SQLite Tables Rather Than Markdown Session Files

**Decision**: Persist strategy artifacts, diagnosis reports, creative reports, and reusable patterns as first-class SQLite records tied to projects and draft versions instead of following dbskill’s markdown session-file model.

**Rationale**:

- This repository is a product runtime, not an agent skill pack
- The workbench needs queryable state for APIs, version histories, reports, and settings views
- SQLite persistence aligns with the existing project, draft, and publish-package storage model

**Alternatives considered**:

- Save artifacts as markdown files beside project exports: rejected because they are harder to query, index, and attach to UI state
- Keep artifacts only in transient API responses: rejected because reports, history, and reusable patterns need durable storage

## Decision 5: Separate Diagnosis Reporting From Directional Polish Execution

**Decision**: Diagnosis produces an explicit report first, and directional polish is launched as a separate operator action that references the report or a chosen objective.

**Rationale**:

- Operators need to see whether a weak draft problem is upstream or downstream before choosing how to revise it
- The repository already supports manual draft polish, so diagnosis-driven polish should extend that path instead of replacing it
- This avoids silent automatic rewrites when the real issue may be the topic angle or benchmark choice

**Alternatives considered**:

- Automatically polish every diagnosed draft immediately: rejected because it hides the real decision and can mask upstream strategy problems
- Merge diagnosis into one generic “quality score”: rejected because it removes the operator’s ability to target a specific weakness

## Decision 6: Keep Reusable Patterns Operator-Curated And Optional

**Decision**: Promote reusable patterns only when the operator explicitly selects a lesson or framing from a creative review report, and show those patterns as optional references in future strategy setup.

**Rationale**:

- Not every project insight is worth reusing
- Automatic pattern promotion would quickly fill the library with noisy, duplicate, or context-bound fragments
- Operator-curated patterns better match the project’s single-user, self-use operating model

**Alternatives considered**:

- Auto-promote every diagnosis finding or report summary: rejected because it would create clutter and weaken trust in the library
- Skip reusable patterns entirely: rejected because the user explicitly wants experience to compound across projects

## Decision 7: Support Legacy Projects Through Nullable Additive Artifacts Rather Than Forced Backfill

**Decision**: Treat all new creative-workflow artifacts as additive and nullable so old projects can use diagnosis, report generation, and pattern promotion without backfilling strategy history.

**Rationale**:

- The repository already contains projects in different maturity states
- Forced backfill would block immediate use of diagnosis and reports on existing drafts
- Nullable artifacts preserve compatibility and make adoption incremental

**Alternatives considered**:

- Require every existing project to regenerate strategy before using any new feature: rejected because it breaks continuity and slows rollout
- Fork behavior between legacy and new projects at the route level: rejected because it adds unnecessary API surface fragmentation
