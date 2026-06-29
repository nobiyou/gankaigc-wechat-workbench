# Feature Specification: Creative Workflow

**Feature Branch**: `[004-creative-workflow]`

**Created**: 2026-05-30

**Status**: Implemented

**Input**: User description: "将 dbskill 的完整创作编排迁移到公众号内容工作台，新增选题立案、问题说明书、对标分析、创作策略卡、内容诊断、AI 指纹检测、定向精修、复盘报告和经验沉淀能力"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Build A Prewriting Strategy Package (Priority: P1)

As the operator, I want each article project to generate a complete prewriting strategy package before outline generation so that the draft starts from a differentiated angle instead of generic emotional templates.

**Why this priority**: The current originality ceiling is set before writing starts. Downstream polish can reduce AI flavor, but it cannot replace missing judgment about audience, conflict, angle, and benchmark choice.

**Independent Test**: Can be fully tested by creating a project from either a trend-based topic or an original idea, generating the strategy package, and verifying that the package includes a clear problem brief, benchmark rationale, and strategy card that can directly support outline generation.

**Acceptance Scenarios**:

1. **Given** a project has a selected topic or original idea, **When** the operator runs prewriting strategy generation, **Then** the workbench produces a structured package covering audience situation, core conflict, point of view, benchmark references, and expression constraints.
2. **Given** the input topic is still vague or contradictory, **When** the operator runs prewriting strategy generation, **Then** the workbench explicitly marks the unclear parts instead of treating them as approved writing direction.
3. **Given** benchmark references are included in the package, **When** the package is reviewed, **Then** it is clear which elements are being borrowed as structure or pacing references and which wording or phrasing must not be reused directly.

---

### User Story 2 - Diagnose Draft Quality And Launch Directional Polish (Priority: P1)

As the operator, I want every draft to receive a multi-dimensional diagnosis plus AI fingerprint detection so that I can fix the real weakness instead of applying generic polish passes blindly.

**Why this priority**: The new upstream strategy layer only pays off if the operator can also see whether a weak draft comes from topic selection, scene density, viewpoint clarity, progression problems, ending weakness, or AI-like phrasing habits.

**Independent Test**: Can be fully tested by taking an existing draft, running diagnosis, and verifying that the workbench returns concrete findings, a prioritized next action, and a directional polish path linked to the resulting revised draft.

**Acceptance Scenarios**:

1. **Given** a project has a draft, **When** the operator runs content diagnosis, **Then** the workbench returns labeled findings for opening strength, scene specificity, viewpoint clarity, progression efficiency, ending quality, and AI fingerprint risk.
2. **Given** a draft has both upstream and downstream problems, **When** the diagnosis is shown, **Then** the workbench distinguishes structural or angle issues from phrasing-level issues instead of collapsing everything into one generic score.
3. **Given** the operator selects a diagnosis-driven polish objective, **When** a revised draft is generated, **Then** the new version records the chosen objective and preserves the earlier version for comparison.

---

### User Story 3 - Generate A Creative Review Report For Each Project (Priority: P2)

As the operator, I want each finished or mid-flight article project to produce a single creative review report so that I can understand how the topic was framed, how the draft changed, and what was learned without reconstructing the story from scattered versions.

**Why this priority**: Once the workflow adds strategy, benchmark, diagnosis, and revision layers, the project becomes harder to review unless the workbench can summarize the full path in one place.

**Independent Test**: Can be fully tested by taking a project that has strategy artifacts, a diagnosed draft, and at least one revision, then generating a creative review report and verifying that it summarizes the decisions, changes, and retained lessons in chronological order.

**Acceptance Scenarios**:

1. **Given** a project contains prewriting, diagnosis, and revision artifacts, **When** the operator requests a creative review report, **Then** the workbench generates one report that summarizes strategy choices, benchmark rationale, draft findings, revision outcomes, and final retained lessons.
2. **Given** a project was created before this feature and lacks prewriting artifacts, **When** the operator requests a review report, **Then** the workbench includes the available history without forcing backfill or discarding older draft and publish records.

---

### User Story 4 - Promote Lessons Into A Reusable Pattern Library (Priority: P3)

As the operator, I want to save selected lessons from one project into a reusable pattern library so that future projects can start from proven openings, conflict frames, benchmark pairings, and expression constraints without copying old articles.

**Why this priority**: Experience only compounds if project-level lessons can be promoted into reusable creative patterns for later projects.

**Independent Test**: Can be fully tested by saving a lesson or pattern from one completed project, opening another project, and verifying that the saved pattern appears as an optional reusable reference during strategy setup.

**Acceptance Scenarios**:

1. **Given** a project review report contains a lesson worth reusing, **When** the operator promotes it to the pattern library, **Then** the saved pattern retains its source project, intended use, and caution notes.
2. **Given** a new project is preparing its strategy package, **When** the operator reviews reusable patterns, **Then** the workbench offers relevant saved patterns as optional references and does not auto-apply them without confirmation.

---

### Edge Cases

- How does the workbench handle a legacy project that already has drafts and publish packages but no strategy package?
- What happens when the operator cannot provide any usable benchmark reference for a topic?
- What happens when the selected benchmarks conflict with the project tone profile or the chosen point of view?
- How does diagnosis behave when the biggest problem is the topic angle itself rather than sentence-level AI fingerprints?
- What happens when the operator wants to skip prewriting strategy for an urgent rewrite but still use diagnosis and report features?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a prewriting strategy flow for each content project that combines topic positioning, problem clarification, benchmark analysis, and a strategy card before writing begins.
- **FR-002**: System MUST allow the prewriting strategy flow to start from either a trend-based topic or an operator-entered original idea.
- **FR-003**: System MUST explicitly mark unclear, contradictory, or weak upstream inputs instead of silently treating them as approved writing direction.
- **FR-004**: System MUST record benchmark references with the reason each reference was chosen and what can be borrowed from it versus what must not be reused directly.
- **FR-005**: System MUST allow outline generation to use an approved strategy package while keeping the existing direct outline-and-draft path available for projects that continue without the new prewriting steps.
- **FR-006**: System MUST provide multi-dimensional diagnosis for any draft, covering opening strength, scene specificity, viewpoint clarity, progression efficiency, ending quality, and AI fingerprint risk.
- **FR-007**: System MUST separate upstream strategy problems from downstream expression problems when presenting diagnosis results.
- **FR-008**: System MUST allow the operator to launch a directional polish pass from diagnosis findings and attach the selected polish objective to the resulting revised draft version.
- **FR-009**: System MUST preserve existing draft version history and publish-package history when new strategy, diagnosis, and report artifacts are added to a project.
- **FR-010**: System MUST generate a project-level creative review report that summarizes prewriting decisions, benchmark choices, diagnosis findings, revision outcomes, and retained lessons.
- **FR-011**: System MUST allow legacy projects without prewriting artifacts to use diagnosis, revision, and reporting capabilities without forced backfill.
- **FR-012**: System MUST expose new strategy, diagnosis, revision, and reporting steps as explicit workbench actions rather than hiding them behind automatic behavior only.
- **FR-013**: System MUST let the operator promote selected project lessons into a reusable pattern library for future projects.
- **FR-014**: System MUST present reusable patterns as optional references with source context and caution notes instead of applying them automatically.

### Key Entities *(include if feature involves data)*

- **Problem Brief**: A structured statement of what the article is trying to explain, shift, or resolve for the target reader, including the core conflict and missing clarity.
- **Benchmark Reference**: A chosen external or internal example used as a reference for angle, pacing, structure, or emotional handling, with explicit notes on what is safe to emulate.
- **Strategy Card**: The approved prewriting package that defines reader situation, point of view, conflict framing, emotional path, expression constraints, and benchmark rationale for one project.
- **Diagnosis Report**: A structured assessment of one draft that records upstream and downstream weaknesses, AI fingerprint findings, and the highest-priority next action.
- **Directional Polish Objective**: The explicit revision goal chosen from a diagnosis result, such as strengthening the opening, rebuilding the middle progression, or removing templated phrasing.
- **Creative Review Report**: A project-level summary that connects strategy, diagnosis, revisions, and retained lessons into one reviewable artifact.
- **Reusable Pattern**: A promoted lesson, rule, warning, or proven framing from a prior project that can be referenced in future strategy work.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a standard project with a confirmed topic or original idea, the operator can generate a complete prewriting strategy package in one guided flow within 5 minutes.
- **SC-002**: After running diagnosis on a draft, the operator can identify the highest-priority weakness and launch a matching directional polish action within 2 workbench actions.
- **SC-003**: Existing projects created before this feature can continue draft, polish, asset, and publish work without mandatory backfill of strategy artifacts or loss of history.
- **SC-004**: Every project that uses the new workflow can produce a single creative review report summarizing strategy, diagnosis, revisions, and lessons in one place.
- **SC-005**: An operator can promote a reusable pattern from one project and reference it during strategy setup for another project without copying old article text directly.

## Assumptions

- The current single-operator, self-use workbench model remains the target operating mode for this feature.
- The existing content production chain of topics, outlines, drafts, assets, and publish packages remains the main project backbone.
- The new creative workflow is additive; operators may still use the existing direct writing path when speed matters more than full prewriting rigor.
- Benchmark materials may come from manually selected references or existing tracked content; automated acquisition of new benchmark sources is outside this feature's scope.
- Reusable patterns start as operator-curated knowledge rather than autonomous system-generated rules.

## Implementation Status

- Implementation audited against the current codebase on 2026-06-23.
- Core delivered capabilities now include:
  - prewriting strategy package generation and adoption
  - draft diagnosis with AI-fingerprint and reference-isolation signals
  - diagnosis-driven polish that records the chosen objective
  - creative review reports on project history
  - reusable pattern promotion and listing
- Automated verification completed on 2026-06-23:
  - `python -m pytest apps/backend/tests/test_app.py apps/backend/tests/test_creative_strategy.py apps/backend/tests/test_content_diagnosis.py apps/backend/tests/test_creative_reports.py`
  - `cd apps/frontend && npm test && npm run build`
- A local end-to-end content run also completed on 2026-06-23 through `published / approved`, covering tracked article import, topic and project creation, strategy generation and adoption, outline, draft, diagnosis, diagnosis-driven polish, assets, publish package generation, and publish approval.
- Scope boundary: this feature implements the workbench-native creative workflow inspired by `magic-distillation`; it does not attempt a 1:1 port of that repository's standalone skill/tool bundle layout.
