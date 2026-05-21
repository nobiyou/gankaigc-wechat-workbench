# Feature Specification: Workbench UI Restructure

**Feature Branch**: `[001-workbench-ui-restructure]`

**Created**: 2026-05-19

**Status**: Draft

**Input**: User description: "Restructure the frontend workbench from a single-page layout into a multi-page task-oriented information architecture with Dashboard, Sources, Pipeline, Projects, Settings, and a full-screen Workbench."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Start Today’s Work Fast (Priority: P1)

As the operator of the content workbench, I want the homepage to show the tasks I should advance today so that I can immediately continue the production pipeline without scrolling through unrelated configuration and history sections.

**Why this priority**: The current single-page structure hides the primary work queue. The redesign fails if the first screen still feels like a feature dump instead of an execution dashboard.

**Independent Test**: Can be fully tested by opening the homepage and verifying that queued work categories are visible first, with direct navigation into the corresponding work areas, without requiring access to long lists below the fold.

**Acceptance Scenarios**:

1. **Given** there are pending trends, pending projects, and publish-ready projects, **When** the user opens the homepage, **Then** the page shows task-first cards for those queues before detailed data lists.
2. **Given** a dashboard task card is visible, **When** the user activates it, **Then** the system routes the user directly to the corresponding page or filtered view for that task.

---

### User Story 2 - Separate Sources From Pipeline Work (Priority: P1)

As the operator, I want source collection and batch pipeline actions to live in separate work areas so that I can browse and curate inputs without confusing single-item actions with batch runs and async task results.

**Why this priority**: The current page mixes list management and processing actions at the same level, which makes operation scope unclear and increases misclick risk during daily production.

**Independent Test**: Can be fully tested by navigating between `Sources` and `Pipeline`, confirming that source pages support browse/filter/single-item actions while batch run management and retry flows live only in pipeline views.

**Acceptance Scenarios**:

1. **Given** the user is on a source page, **When** they review a single trend or tracked article, **Then** they can run a single-item action such as creating a topic or project from that item without entering a batch result view.
2. **Given** the user needs to inspect bulk topic generation or rerun failures, **When** they open `Pipeline`, **Then** they can see batch run status, result summaries, and retry controls in that workspace instead of on source pages.

---

### User Story 3 - Enter a Focused Single-Project Workbench (Priority: P1)

As the operator, I want to open one project into a dedicated full-screen workbench so that I can move through `topic -> outline -> draft -> assets -> publish` without the distraction of unrelated lists, settings, or global sections.

**Why this priority**: The current workbench is buried in the single-page flow and does not feel like the core production environment for one article.

**Independent Test**: Can be fully tested by selecting a project from the projects page and verifying that the resulting workbench uses a left-stage navigator, a right-side active workspace, stage recommendations, and contextual version history access.

**Acceptance Scenarios**:

1. **Given** a project exists, **When** the user opens it from the projects list, **Then** the app shows a dedicated workbench view with the project summary, stage navigator, and current stage workspace.
2. **Given** the project is missing a draft but has an outline, **When** the workbench opens, **Then** the next recommended stage highlights `Draft` while still allowing the user to inspect or revisit previous stages.
3. **Given** a stage has prior saved versions, **When** the user opens that stage’s history drawer, **Then** they can review prior versions without leaving the current workbench screen.

---

### User Story 4 - Review and Return Work in Context (Priority: P2)

As the operator, I want review signals and history to stay attached to the relevant page or stage so that I do not have to jump into separate standalone `Task Center` or `Version History` pages to understand what happened.

**Why this priority**: Quality and history remain important, but separate top-level pages recreate the same sprawl the redesign is trying to remove.

**Independent Test**: Can be fully tested by verifying that review-ready projects surface through dashboard/projects/workbench flows and that stage history or task logs appear in their business context instead of standalone pages.

**Acceptance Scenarios**:

1. **Given** a project is publish-ready, **When** the user opens the project workbench, **Then** the publish stage shows final review actions and any existing review status.
2. **Given** a batch run fails for some items, **When** the user opens pipeline task logs, **Then** the failures and retry actions are available there without navigating to an old global task center.

---

### Edge Cases

- What happens when there is no pending work in one or more dashboard queues?
- How does the system behave when a project has partial chain data and multiple stages could reasonably be revisited?
- How does navigation behave when the user opens a route for an entity that no longer exists or is no longer selected?
- What happens when history is empty for a stage that supports a history drawer?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The frontend MUST replace the current single-page workbench layout with top-level navigation for `Dashboard`, `Sources`, `Pipeline`, `Projects`, and `Settings`.
- **FR-002**: The homepage (`Dashboard`) MUST prioritize actionable work queues over broad statistics and MUST provide direct navigation into the relevant work area for each queue.
- **FR-003**: The `Sources` area MUST provide dedicated views for trends, tracked articles, and WeChat import inputs, with filtering, browsing, and single-item actions available in context.
- **FR-004**: The `Pipeline` area MUST provide dedicated views for topic queue management, batch runs, async task status, result summaries, and retry flows for failed bulk operations.
- **FR-005**: The `Projects` area MUST provide search and filters plus grouped project lists organized by production state, including at least pending chain continuation, pending review, published, and pending retro states when data exists.
- **FR-006**: The frontend MUST provide a dedicated project `Workbench` route entered from the projects area rather than exposing workbench as a persistent top-level navigation item.
- **FR-007**: The `Workbench` MUST present the content chain as a left-side stage navigator with `Topic`, `Outline`, `Draft`, `Assets`, and `Publish` stages, and a right-side active stage workspace.
- **FR-008**: The `Workbench` MUST highlight the recommended next stage based on current project state while still allowing users to move to other stages.
- **FR-009**: Each workbench stage MUST default to showing the current effective content and MUST expose prior stage versions through a contextual history drawer or equivalent in-place mechanism.
- **FR-010**: Final approval, revision request, and publish-review actions MUST be concentrated in the `Publish` stage, while earlier stages MAY display local quality signals or upstream review context.
- **FR-011**: The frontend MUST retire standalone `Task Center` and `Version History` pages by redistributing their responsibilities into `Dashboard`, `Pipeline`, `Projects`, and `Workbench`.
- **FR-012**: The UI restructure MUST preserve the existing content pipeline semantics and current business capabilities for trends, tracked articles, topics, projects, workbench chain actions, and tone profile configuration.
- **FR-013**: The restructure MUST avoid placing configuration-heavy workflows such as tone profile management at the same visual priority level as day-to-day production work.
- **FR-014**: Routes and page states introduced by the restructure MUST handle empty states gracefully so that users can distinguish “nothing to do” from “data failed to load.”

### Key Entities *(include if feature involves data)*

- **Navigation Workspace**: A top-level work mode that groups related actions and views, such as dashboard, sources, pipeline, projects, or settings.
- **Source Item**: An input entity used to derive content work, including trends, tracked articles, and imported WeChat MP articles.
- **Topic Queue Item**: A topic candidate waiting to be reviewed, converted into a project, or included in a batch pipeline step.
- **Project Workbench Session**: The active single-project view that exposes summary data, current chain stage, available actions, and stage-specific history.
- **Stage History Entry**: A prior saved version of outline, draft, assets, or publish-package content attached to one workbench stage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can reach a targeted production task area from the dashboard in one navigation action after the homepage loads.
- **SC-002**: A user can reach a dedicated single-project workbench from the projects page in no more than two interactions.
- **SC-003**: The top-level navigation contains no more than five primary entries for daily work modes.
- **SC-004**: Standalone `Task Center` and `Version History` screens are no longer required to complete the primary daily workflow of sourcing, pipeline advancement, project work, and publish review.

## Assumptions

- Existing backend APIs for dashboard summary, trends, tracked articles, topics, projects, workbench detail, version history, and tone profiles remain available and can be reorganized on the frontend without requiring a backend redesign in this phase.
- React Router is already available in the frontend and can be used to introduce route-based page structure.
- The current frontend helpers such as task-center derivation, content-source labeling, and project-selection utilities can either be reused or redistributed during refactor rather than discarded wholesale.
- Responsive polish and visual branding refinements are outside the first restructure pass as long as the page architecture and navigation are stable.
