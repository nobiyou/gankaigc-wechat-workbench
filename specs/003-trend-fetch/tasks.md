# Tasks: Trend Fetch

- [x] T001 Add spec artifacts under `specs/003-trend-fetch/`
- [x] T002 Add RSS trend-fetch settings and backend response schema updates in `apps/backend/app/core/settings.py` and `apps/backend/app/schemas/trends.py`
- [x] T003 Implement `POST /trends/fetch` and RSS parsing/import flow in `apps/backend/app/api/trends.py` and `apps/backend/app/services/workbench.py`
- [x] T004 Add backend tests for configured fetch, duplicate skip behavior, and missing-config handling in `apps/backend/tests/test_app.py`
- [x] T005 Add frontend API call and Sources trends fetch action in `apps/frontend/src/api/workbench.ts` and `apps/frontend/src/pages/SourcesPage.tsx`
- [x] T006 Run focused verification and update this task file
