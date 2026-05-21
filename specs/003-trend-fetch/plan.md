# Implementation Plan: Trend Fetch

**Branch**: `[003-trend-fetch]` | **Date**: 2026-05-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-trend-fetch/spec.md`

## Summary

Add a minimal live trend fetcher using configured RSS feeds, wire it into the existing trend ingestion path, and expose a refresh action on the Sources trends page.

## Technical Context

**Language/Version**: Python 3.11, TypeScript 5.8, React 19.1

**Primary Dependencies**: FastAPI, httpx, sqlite3, React

**Storage**: Existing SQLite store via `apps/backend/app/services/workbench.py`

**Testing**: `pytest`, `npm test`, `npm run build`

## Compatibility Boundary

- Preserve existing `trends/import` behavior
- Reuse source-ingestion tracking rather than inventing a second fetch history mechanism
- Keep the UI action inside `Sources / trends`

## Files

- `apps/backend/app/core/settings.py`
- `apps/backend/app/schemas/trends.py`
- `apps/backend/app/api/trends.py`
- `apps/backend/app/services/workbench.py`
- `apps/backend/tests/test_app.py`
- `apps/frontend/src/api/workbench.ts`
- `apps/frontend/src/pages/SourcesPage.tsx`
- `specs/003-trend-fetch/`
