# Data Model: Scheduled WeChat MP Draft Automation

The automation tables are additive to the existing SQLite workbench store. They are created by the existing store initialization path and are reset only when the existing test/store reset path is explicitly used.

## Automation Subscription

Table: \`automation_subscriptions\`

| Field | Type | Rules |
|---|---|---|
| \`id\` | INTEGER | primary key |
| \`account_fakeid\` | TEXT | required, unique stable WeChat account identity |
| \`account_nickname\` | TEXT | required display snapshot, refreshable |
| \`account_alias\` | TEXT | optional display metadata |
| \`account_avatar_url\` | TEXT | optional display metadata |
| \`enabled\` | INTEGER | 0/1, default 1 |
| \`schedule_time\` | TEXT | strict local \`HH:MM\`, default \`21:00\` |
| \`timezone\` | TEXT | IANA name, default \`Asia/Shanghai\` |
| \`fetch_limit\` | INTEGER | 1..10, default 1 |
| \`automatic_draft\` | INTEGER | 0/1, default 1 |
| \`last_scheduled_local_date\` | TEXT | last claimed scheduled local date |
| \`last_run_id\` | INTEGER | latest run reference |
| \`last_success_at\` | TEXT | latest successful completion |
| \`created_at\` / \`updated_at\` | TEXT | UTC ISO timestamps |

Validation: fakeid and nickname are non-empty; time is \`00:00\` through \`23:59\`; timezone must be accepted by \`zoneinfo\`; fetch limit is bounded; disabled subscriptions are never due.

## Automation Run

Table: \`automation_runs\`

| Field | Type | Rules |
|---|---|---|
| \`id\` | INTEGER | primary key |
| \`subscription_id\` | INTEGER | foreign-key-shaped reference to subscription |
| \`trigger\` | TEXT | \`scheduled\`, \`manual\`, or \`retry\` |
| \`scheduled_local_date\` | TEXT | local date used for scheduled idempotency; nullable for manual |
| \`status\` | TEXT | \`queued\`, \`running\`, \`completed\`, \`skipped\`, \`failed\`, \`claimed\` |
| \`stage\` | TEXT | current pipeline stage |
| \`fetched_count\` / \`imported_count\` / \`skipped_count\` | INTEGER | per-run counters |
| \`source_article_id\` / \`source_article_link\` | TEXT | inspected source identity |
| \`source_article_title\` | TEXT | inspected source title |
| \`tracked_article_slug\` / \`topic_slug\` / \`project_slug\` | TEXT | downstream links |
| \`publish_package_version\` | INTEGER | formatted package link |
| \`draft_status\` / \`draft_id\` | TEXT | draft-box result |
| \`error\` | TEXT | bounded user-readable failure |
| \`result_json\` | TEXT | structured result summary |
| \`started_at\` / \`finished_at\` / \`created_at\` | TEXT | UTC ISO timestamps |

Constraint: unique \`(subscription_id, scheduled_local_date)\` for scheduled records. A manual run may point to an existing workflow and must not create a new workflow identity.

## Automation Workflow State

Table: \`automation_workflows\`

| Field | Type | Rules |
|---|---|---|
| \`id\` | INTEGER | primary key |
| \`subscription_id\` | INTEGER | owning subscription |
| \`source_article_key\` | TEXT | unique per subscription, derived from article ID/link |
| \`source_article_id\` / \`source_article_link\` | TEXT | original upstream identity |
| \`source_article_title\` / \`source_update_time\` | TEXT/INTEGER | source snapshot |
| \`status\` | TEXT | \`active\`, \`completed\`, \`skipped\`, or \`failed\` |
| \`last_stage\` | TEXT | last durable stage |
| \`tracked_article_slug\` / \`topic_slug\` / \`project_slug\` | TEXT | persisted artifact keys |
| \`publish_package_version\` | INTEGER | latest package version |
| \`draft_status\` / \`draft_id\` | TEXT | draft-box state |
| \`error\` | TEXT | latest bounded failure |
| \`created_at\` / \`updated_at\` | TEXT | UTC ISO timestamps |

Constraint: unique \`(subscription_id, source_article_key)\`. This is the resume boundary for imported/manual/restarted articles.

## Automation Lease

Table: \`automation_locks\`

| Field | Type | Rules |
|---|---|---|
| \`lock_key\` | TEXT | primary key, e.g. \`scheduler-cycle:2026-08-26\` or \`subscription:7:2026-08-26\` |
| \`owner_token\` | TEXT | process/run token |
| \`lease_until\` | TEXT | UTC expiry |
| \`acquired_at\` / \`updated_at\` | TEXT | UTC ISO timestamps |

The claim is a single SQLite transaction. Expired leases can be replaced; a live lease held by another owner is not replaced.

## State Transitions

\`\`\`text
queued -> running -> completed
                  -> skipped
                  -> failed -> running (manual retry or later due cycle)

workflow active -> completed
                -> skipped
                -> failed -> active (resume)

package ready -> approved (automatic approval marker) -> draft writing -> published
                                                   \\-> failed -> draft writing (explicit retry)
\`\`\`

The \`published\` value refers to the existing package's WeChat draft status, not a public group send. The automation service never transitions a run to a public publication state.
