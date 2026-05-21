# Quickstart: Source Ingestion And Freshness

## Goal

Verify that source intake is deduplicated, tracked, and visible from the dashboard.

## Backend

```powershell
python -m pytest apps/backend/tests/test_app.py apps/backend/tests/test_wechat_mp_import.py
```

## Frontend

```powershell
Set-Location apps/frontend
npm test
npm run build
Set-Location ../..
node scripts/verify-workbench-ui-smoke.cjs
```

## Manual Checks

1. Open `http://127.0.0.1:3000/settings/tone-profiles` once to ensure the app boots normally.
2. Go to `http://127.0.0.1:3000/sources/wechat-import`.
3. Import one WeChat article, then import it again.
4. Confirm the second import reports a skipped duplicate instead of creating a second tracked article.
5. Open `http://127.0.0.1:3000/` and confirm the dashboard shows source freshness and latest source activity.
