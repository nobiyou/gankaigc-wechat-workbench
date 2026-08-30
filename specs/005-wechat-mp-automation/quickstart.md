# Quickstart: Scheduled WeChat MP Draft Automation

## Run the API-hosted scheduler

From the repository root:

\`\`\`powershell
python -m uvicorn app.main:app --app-dir apps/backend --reload
\`\`\`

The FastAPI lifespan initializes SQLite and starts the scheduler. Keep the existing QR session valid. Open the Automation view, search/select a公众号 from the WeChat Import source flow, and create a subscription. New subscriptions default to \`21:00\`, \`Asia/Shanghai\`, one article, and automatic draft writing.

## Run the optional resident process

\`\`\`powershell
python -m app.automation_runner --app-dir apps/backend --loop
\`\`\`

The resident process uses the same SQLite store and workflow owner. Do not run it against a different \`DB_PATH\` if the API should show the same subscriptions and runs.

## Immediate verification flow

1. Establish a QR login session and confirm \`GET /api/wechat-mp/session\` reports \`logged_in: true\`.
2. Create one subscription with \`POST /api/wechat-mp/automation/subscriptions\`.
3. Start \`POST /api/wechat-mp/automation/subscriptions/{id}/runs\`.
4. Poll \`GET /api/wechat-mp/automation/runs/{run_id}\` until \`completed\`, \`skipped\`, or \`failed\`.
5. On success, open the project link and its formatted HTML preview; confirm the package draft status is \`published\` and the provenance is \`scheduled_automation\`.
6. On failure, read \`stage\` and \`error\`, repair the session/configuration, then use the retry action. The retry must reuse the same source workflow row.

## Focused test scenarios

- Due evaluation at 21:00 and after-service-restart catch-up.
- Disabled subscription is ignored.
- Two accounts with the same nickname remain separate by fakeid.
- Duplicate source link/article ID creates no second project or draft write.
- Session-expired, AI, cover, HTML, and draft-box failures persist stage/error.
- Two scheduler instances produce one scheduled claim.
- A failed run resumes at the first incomplete stage.

No test or runtime path sends a public WeChat post.
