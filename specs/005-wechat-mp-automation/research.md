# Research: Scheduled WeChat MP Draft Automation

## Decision: Reuse the existing QR-session and workbench owners

The new service calls \`WechatMpClient\` for session status, account article listing, and article-body retrieval. It calls the public workbench stage functions for tracked article import, topic generation, project creation, outline, draft, assets, publish package, and project detail. It does not copy those workflows or add a parallel project database.

Rationale: the current repository already persists each content artifact and has manual preview and draft-box behavior. Reusing those owners makes restart recovery and manual inspection possible without migrating existing projects.

Alternatives considered: a new end-to-end pipeline would duplicate AI/content semantics and create two sources of truth; using only \`background_tasks\` would not model subscriptions, schedule dates, or resumable stage state.

## Decision: FastAPI lifespan plus an optional resident runner

The application lifespan starts a daemon scheduler thread that polls due subscriptions. \`apps/backend/app/automation_runner.py\` exposes the same scheduler through \`python -m app.automation_runner --loop\` for Windows, Linux, and macOS. Both entry points call the same \`run_due_cycle()\` and persist all claims in SQLite.

Rationale: no OS-specific task scheduler is required, and the service can continue to run in the API process or a dedicated process. A poll interval of 30 seconds is sufficient for the five-minute schedule tolerance.

Alternatives considered: Windows Task Scheduler violates the explicit cross-platform constraint; an in-memory timer would lose schedules on restart; adding Celery/Redis is disproportionate for the single-operator local app.

## Decision: \`zoneinfo\` for local schedule evaluation

Each subscription stores an IANA time-zone name, defaulting to \`Asia/Shanghai\`, and a strict \`HH:MM\` local schedule. The scheduler converts the injected current UTC instant into that zone before deciding whether the current local date/time is due. A run is eligible after the configured minute and only once for that local date.

Rationale: this keeps the persisted schedule independent of host locale and works on supported operating systems with Python's standard library.

Alternatives considered: host-local time would make a subscription drift when deployed elsewhere; fixed UTC offsets do not handle named zones or future daylight changes.

## Decision: Durable idempotency plus a SQLite lease

Scheduled run creation uses a unique \`(subscription_id, scheduled_local_date)\` key. A short-lived \`automation_locks\` row is claimed atomically with \`BEGIN IMMEDIATE\`, an owner token, and an expiry. The unique run row remains the durable record if the process crashes; a later run resumes its workflow rather than creating a second project or draft.

Rationale: a lease alone expires during long AI/media operations, while a unique run row alone does not provide a reusable scheduler claim primitive. Together they protect concurrent processes and retain recovery evidence.

Alternatives considered: a Python lock only protects one process; an unbounded retry loop could duplicate external draft writes; relying on project slug uniqueness alone does not protect pre-project article claims.

## Decision: One persisted workflow row per account/article identity

The source identity is derived from stable account \`fakeid\` plus \`article_id\`, with the normalized link retained for manual-import compatibility. Each workflow row records tracked article, topic, project, publish package, current stage, and draft-box result. Existing tracked article URL matching is checked before creating a new source record.

Rationale: article IDs are the upstream identity while URLs are the existing local duplicate boundary. Keeping both supports account rename, manual imports, and recovery after a partial stage.

Alternatives considered: title-only deduplication collides on same-title articles; link-only deduplication misses account identity and can incorrectly merge accounts; creating a fresh project on every retry violates the accepted idempotency behavior.

## Decision: Automatic approval is explicit and draft-only

An automatic run builds a normal publish package, marks it approved through an internal provenance-marked workbench transition, then calls the existing \`publish_wechat_mp_draft\` adapter with \`scheduled_automation\` provenance. The package and draft write retain source markers, and no final group-send operation exists in this flow.

Rationale: the current publisher intentionally requires approval as a guard. Automation needs a controlled exception for the user-approved automatic draft mode, but the approval and draft write must remain distinguishable from manual clicks.

Alternatives considered: bypassing the approval state in the scheduler would weaken the existing safety guard; exposing automatic group-send would exceed scope and create a much higher-risk boundary.

## Decision: Failure stops the current article and remains resumable

The orchestrator records \`stage\`, a bounded error message, and all completed artifact IDs after every stage. It performs no immediate retry beyond behavior already owned by existing AI/workbench services. Manual retry or the next due cycle invokes the same workflow row and skips completed stages.

Rationale: failures from session, upstream AI, media, HTML, and WeChat requests need a concrete diagnostic and a deterministic recovery point.

Alternatives considered: swallowing errors would make scheduled losses invisible; retrying the complete chain could duplicate artifacts and external draft writes.
