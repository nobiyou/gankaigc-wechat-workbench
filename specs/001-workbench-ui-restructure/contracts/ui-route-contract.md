# UI Route Contract: Workbench UI Restructure

## Purpose

Define the route and ownership contract for the refactored frontend workbench so implementation can split pages without reintroducing single-page sprawl.

## Primary Routes

| Route | Owner | Purpose |
| --- | --- | --- |
| `/` | Dashboard | Task-first homepage showing actionable work queues |
| `/sources/trends` | Sources | Browse and act on trend items |
| `/sources/articles` | Sources | Browse and act on tracked articles |
| `/sources/wechat-import` | Sources | Import and review WeChat MP articles before downstream actions |
| `/pipeline/topics` | Pipeline | Review topics as transitional queue items |
| `/pipeline/runs` | Pipeline | Launch or inspect batch pipeline runs |
| `/pipeline/tasks` | Pipeline | Inspect async task status, results, and retries |
| `/projects` | Projects | Search, filter, and group project list |
| `/projects/:projectSlug/workbench/:stage` | Workbench | Focused single-project production route |
| `/settings/tone-profiles` | Settings | Manage tone profiles and related configuration |

## Route Rules

1. Only the five work modes `Dashboard`, `Sources`, `Pipeline`, `Projects`, and `Settings` appear in primary navigation.
2. `Workbench` is entered from `Projects` and is never a persistent primary navigation item.
3. `:stage` MUST be one of `topic`, `outline`, `draft`, `assets`, or `publish`.
4. Unknown or missing workbench stages MUST normalize to a valid stage, preferably the recommended next stage for the project.
5. Missing `projectSlug` or missing project data MUST return the user to `/projects` with a clear error or empty-state message.

## Legacy Surface Retirement

The following legacy standalone surfaces must not survive as top-level destinations:

- `Task Center`
- `Version History`
- Monolithic single-page workbench layout

Their responsibilities move to:

- `Dashboard` for task-first entry
- `Pipeline` for batch runs, async status, and retries
- `Workbench` stage history drawers and contextual review state

## Navigation Behavior

- Primary navigation changes work mode
- Secondary navigation within `Sources` and `Pipeline` changes subview
- Stage navigation inside `Workbench` changes the active project stage
- Dashboard cards may deep-link to filtered `Projects` or `Pipeline` views when that shortens the operator path
