# Quickstart: Creative Workflow

## Goal

Verify that the workbench can generate explicit prewriting strategy artifacts, diagnose draft weaknesses, launch diagnosis-driven polish, produce a creative review report, and promote a reusable pattern without breaking legacy project behavior.

## Backend

```powershell
python -m pytest apps/backend/tests/test_app.py apps/backend/tests/test_creative_strategy.py apps/backend/tests/test_content_diagnosis.py apps/backend/tests/test_creative_reports.py
```

## Frontend

```powershell
Set-Location apps/frontend
npm test
npm run build
Set-Location ../..
```

## Manual Checks

1. Open `http://127.0.0.1:3000/projects`.
2. Enter a project workbench and stay on the `Topic` stage.
3. Trigger creative strategy generation and confirm the workbench shows a problem brief, benchmark references, and a strategy card.
4. If the strategy package is reviewable, explicitly adopt it and then generate or regenerate the outline.
5. Move to `Draft`, generate a draft, then run content diagnosis.
6. Confirm the diagnosis separates upstream issues from downstream expression problems and offers an explicit recommended next action.
7. Launch a diagnosis-driven polish pass and confirm a new draft version appears with preserved history.
8. Move to `Publish` and generate a creative review report.
9. Promote one retained lesson into the reusable pattern library.
10. Open another project and confirm that active reusable patterns appear as optional references during strategy setup.
11. Open a legacy project without strategy artifacts and confirm diagnosis and report features still work without mandatory backfill.
