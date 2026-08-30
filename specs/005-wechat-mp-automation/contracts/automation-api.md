# Automation API Contract

All routes are under the existing \`/api\` prefix. Payloads are JSON. No route accepts or returns AppID/AppSecret credentials.

## Subscriptions

\`GET /wechat-mp/automation/subscriptions\`

Returns \`AutomationSubscriptionItem[]\`, including stable account identity, display metadata, enabled state, schedule, timezone, fetch limit, automatic draft mode, next run, and last run summary.

\`POST /wechat-mp/automation/subscriptions\`

Request:

\`\`\`json
{
  "account_fakeid": "stable-fakeid",
  "account_nickname": "示例公众号",
  "account_alias": "example",
  "account_avatar_url": "https://...",
  "enabled": true,
  "schedule_time": "21:00",
  "timezone": "Asia/Shanghai",
  "fetch_limit": 1,
  "automatic_draft": true
}
\`\`\`

Returns \`201 AutomationSubscriptionItem\`. A duplicate stable account identity returns \`409\`.

\`PATCH /wechat-mp/automation/subscriptions/{subscription_id}\`

Accepts any editable schedule/display/enabled fields and returns the updated item. Invalid time, timezone, or limit returns \`422\`.

\`DELETE /wechat-mp/automation/subscriptions/{subscription_id}\`

Disables the subscription without deleting run/workflow history. Returns the updated item.

## Runs

\`GET /wechat-mp/automation/runs?subscription_id=&limit=\`

Returns newest-first \`AutomationRunItem[]\`, with stage, counts, source article, project/package links, draft status, and error/retryability.

\`POST /wechat-mp/automation/subscriptions/{subscription_id}/runs\`

Starts the same pipeline immediately for an enabled subscription. Returns \`202 AutomationRunSubmission\` with \`run_id\`, \`status\`, and \`trigger=manual\`.

\`POST /wechat-mp/automation/runs/{run_id}/retry\`

Retries a failed or skipped run through its persisted workflow state. Returns \`202 AutomationRunSubmission\` with a new run identifier referencing the same workflow identity.

\`GET /wechat-mp/automation/runs/{run_id}\`

Returns one \`AutomationRunDetail\`, including links to \`/projects/{project_slug}/workbench/publish\` and the generated preview artifact when available.

\`POST /wechat-mp/automation/cycle\`

Runs one due-cycle evaluation synchronously for diagnostics/tests and returns counts plus claimed run IDs. It is not a public-publication action.

## Error contract

Run-level upstream failures are stored in \`error\` and \`stage\` and returned as normal run data; the API itself uses \`404\` for missing records, \`409\` for invalid state/claim conflicts, and \`422\` for invalid subscription input. Session expiry uses the existing WeChat session status surface and the existing message \`公众号登录已过期，请重新扫码登录\`.

## Provenance contract

Automatic workflow artifacts and draft writes carry \`scheduled_automation\` in their source/provenance fields. Manual routes retain their existing provenance. The API does not expose a final group-send command.
