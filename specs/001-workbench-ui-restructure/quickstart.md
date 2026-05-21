# Quickstart: Workbench UI Restructure

## Goal

Implement the approved route-based UI restructure for the frontend without changing backend ownership or breaking the existing content production chain.

## Preconditions

- Work on branch `001-workbench-ui-restructure`
- Read:
  - `specs/001-workbench-ui-restructure/spec.md`
  - `specs/001-workbench-ui-restructure/plan.md`
  - `docs/aegis/specs/2026-05-19-workbench-ui-information-architecture-design.md`
- Confirm the frontend dependencies are installed under `apps/frontend`

## Local Commands

### Run tests

```powershell
cd E:\dev\gankaigc-wechat-workbench\apps\frontend
npm test
```

### Run production build

```powershell
cd E:\dev\gankaigc-wechat-workbench\apps\frontend
npm run build
```

### Run local dev server

```powershell
cd E:\dev\gankaigc-wechat-workbench\apps\frontend
npm run dev
```

Open `http://127.0.0.1:3000/`.

## Manual Verification Checklist

### Dashboard

- Root route opens into a task-first dashboard
- Dashboard cards route directly into the relevant page or filtered view
- Empty queues show a meaningful “nothing to do” state rather than blank space

### Sources

- `Sources` exposes `Trends`, `Tracked Articles`, and `WeChat Import`
- Single-item actions remain available in source context
- Source pages do not show global batch-result dashboards

### Pipeline

- Topic queue appears under `Pipeline`
- Batch results, task logs, and retry actions appear only in pipeline views
- Failed results can be located without relying on a retired `Task Center`

### Projects

- Projects page shows search/filter controls plus grouped lists
- A project can be opened into the dedicated workbench route from this page

### Workbench

- Workbench has a summary bar, left stage navigator, and right active stage workspace
- Recommended next stage is highlighted without blocking stage switching
- Stage history is accessed from a drawer or equivalent contextual surface
- Final review actions live in `Publish`

### Settings

- Tone profile management remains accessible under `Settings`
- Settings no longer compete with production views on the default landing experience

## Expected Non-Goals

- Do not spend this phase on a brand-new design system
- Do not redesign backend APIs
- Do not add a new client-state framework unless extraction proves impossible with existing patterns
