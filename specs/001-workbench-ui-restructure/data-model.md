# Data Model: Workbench UI Restructure

## Overview

This feature does not introduce new backend persistence entities. It introduces frontend interaction models and derived view models that reorganize existing business data into a route-based workspace structure.

## Navigation Workspace

**Purpose**: Represents one top-level work mode visible in primary navigation.

**Fields**

- `key`: stable identifier such as `dashboard`, `sources`, `pipeline`, `projects`, `settings`
- `label`: user-facing title
- `path`: route path
- `description`: short purpose statement
- `children`: optional nested views or sub-navigation entries

**Rules**

- Only five primary workspaces should be visible in daily navigation
- `workbench` is not a primary workspace entry

## Dashboard Task Card

**Purpose**: Summarizes an actionable queue on the homepage.

**Fields**

- `key`: queue identifier
- `title`: queue title
- `count`: number of actionable items
- `summary`: short operator-facing explanation
- `targetPath`: destination route or filtered route
- `tone`: visual emphasis level such as ready, warning, empty

**Derived From**

- Dashboard summary API
- Existing task-center queue derivation logic
- Project/topic/trend lists when summary data alone is not enough

## Source Workspace View

**Purpose**: Represents a browsable input surface under `Sources`.

**Fields**

- `sourceType`: `trends`, `tracked_articles`, or `wechat_import`
- `items`: visible source items
- `filters`: active filter state
- `singleActions`: allowed single-item actions such as `create_topic` or `create_project`
- `emptyState`: message shown when no items match

**Rules**

- Supports browse, search/filter, and single-item actions
- Does not own batch result logs or retry dashboards

## Pipeline Workspace View

**Purpose**: Represents an execution-oriented subview under `Pipeline`.

**Fields**

- `pipelineView`: `topic_queue`, `batch_runs`, or `task_log`
- `items`: visible queue items or task results
- `statusSummary`: counts such as requested/done/failed/skipped
- `bulkActions`: allowed batch actions or retries
- `filters`: execution-state filters

**Rules**

- `Topic Queue` owns the transitional topics object
- `Task Log` owns async results and retries

## Project Group

**Purpose**: Represents one grouped bucket on the `Projects` page.

**Fields**

- `groupKey`: stable identifier such as `chain`, `review`, `published`, `retro`
- `title`: user-facing group title
- `projects`: projects in the bucket
- `count`: derived project count
- `filterHint`: explanation of why projects appear in that group

**Derived From**

- `ProjectItem.current_chain_state`
- `ProjectItem.next_required_step`
- retro presence

## Workbench Session

**Purpose**: Represents the focused single-project route state.

**Fields**

- `projectSlug`: selected project id/slug
- `projectSummary`: title, status, tone profile, timestamps, current bottleneck
- `recommendedStage`: stage recommended as next step
- `activeStage`: currently open stage
- `availableStages`: ordered chain stages
- `reviewState`: publish-stage review or revision context

**Rules**

- Must allow stage switching even when the recommended stage is elsewhere
- Must gracefully handle invalid stage or missing project

## Workbench Stage View

**Purpose**: Represents the right-side active workspace for one stage.

**Fields**

- `stageKey`: `topic`, `outline`, `draft`, `assets`, or `publish`
- `currentContent`: current effective content payload for that stage
- `historyEntries`: prior versions available via drawer
- `localSignals`: warnings, review hints, or next-step messaging
- `actions`: stage-specific allowed actions

**Rules**

- History is contextual and drawer-based
- Publish stage owns final approve / request revision actions

## Stage History Entry

**Purpose**: Represents one prior saved version accessible from a stage drawer.

**Fields**

- `versionNumber`: ordinal identifier
- `createdAt`: recorded time
- `createdByContext`: optional generation origin or action label
- `summary`: compact description of what changed
- `restorable`: whether restore action is permitted

**Rules**

- History exists only in context of a stage, not as a standalone page
- Empty history must be distinguishable from loading failure
