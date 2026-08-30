# Feature Specification: Scheduled WeChat MP Draft Automation

**Feature Branch**: `[codex/005-wechat-mp-automation]`

**Created**: 2026-08-26

**Status**: Draft

**Input**: User description: "每天晚上 21:00，从扫码登录会话中指定的公众号抓取最新 1 篇文章，自动改写、排版、生成发布包并写入公众号草稿箱；不使用 Windows 任务计划，支持多系统。"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Manage Scheduled Source Accounts (Priority: P1)

As the operator, I want to select公众号 accounts from the existing扫码登录会话 and enable or disable scheduled processing for each account, so that the automation only acts on sources I explicitly choose.

**Why this priority**: Without an explicit account subscription, scheduled collection could operate on the wrong source or create an uncontrolled content stream.

**Independent Test**: Can be fully tested by selecting one account, saving the default schedule, disabling it, and verifying that disabled accounts are not selected for a due run.

**Acceptance Scenarios**:

1. **Given** a valid扫码登录会话 and a searched公众号 account, **When** the operator enables scheduled processing, **Then** the account appears in the subscription list with its stable account identity, display name, next run time, fetch count, and automatic draft mode.
2. **Given** two accounts have the same display name but different stable identities, **When** the operator subscribes to both, **Then** they remain separate subscriptions and each can be enabled or disabled independently.
3. **Given** a subscription is disabled, **When** the next scheduled cycle runs, **Then** that account is not fetched or processed and its last successful run remains visible.

### User Story 2 - Turn the Latest Source Article Into a WeChat Draft (Priority: P1)

As the operator, I want the system to process the latest new article from each enabled account at the configured time, so that a rewritten and formatted article is ready in the公众号草稿箱 without manual stage-by-stage operation.

**Why this priority**: This is the core value of the automation: converting a selected source article into a reviewable draft on a predictable daily cadence.

**Independent Test**: Can be fully tested with one enabled account and one unseen source article by running a due cycle, then verifying the imported article, generated project chain, formatted publish package, and公众号 draft status.

**Acceptance Scenarios**:

1. **Given** an enabled account, a valid session, and a new article, **When** the scheduled time arrives, **Then** the system imports at most the configured number of new articles, runs the existing rewrite and content-production workflow, generates a formatted publish package, and writes the result to the公众号草稿箱.
2. **Given** the newest article has already been imported or processed, **When** the scheduled cycle runs, **Then** the article is marked as skipped and no duplicate topic, project, publish package, or公众号 draft is created.
3. **Given** the automatic draft mode is enabled, **When** the publish package is ready, **Then** the package is eligible for automatic draft writing without a manual approval click, while final群发 remains unavailable to the automation.
4. **Given** multiple accounts are enabled, **When** one account completes successfully, **Then** the system records its result independently and continues evaluating the other enabled accounts.

### User Story 3 - Observe and Recover Automation Runs (Priority: P1)

As the operator, I want each scheduled run to expose its progress, result, and failure stage, so that I can understand why a draft was not created and resume it without creating duplicates.

**Why this priority**: Source sessions, AI generation, media generation, and公众号后台 requests can fail independently; silent or non-resumable failures would make scheduled production unsafe to operate.

**Independent Test**: Can be fully tested by forcing failures at article import, AI generation, cover generation, session validation, and draft writing, then verifying the recorded stage, actionable error, and resumable state.

**Acceptance Scenarios**:

1. **Given** a scheduled run fails at any stage, **When** the operator opens the run history, **Then** the run shows `failed`, the affected account and article, the failed stage, a user-readable reason, and whether manual retry is available.
2. **Given** the扫码登录会话 is expired, **When** a scheduled cycle attempts to use it, **Then** the run stops before content generation, marks the session as requiring a new扫码登录, and does not repeatedly retry in the same cycle.
3. **Given** the service restarts after a run has begun, **When** the scheduler starts again, **Then** it can resume the unfinished article from the latest persisted workflow state without duplicating completed artifacts.
4. **Given** two scheduler instances evaluate the same due subscription, **When** both attempt to start the run, **Then** only one instance processes the subscription and the other records that the work was already claimed or completed.
5. **Given** an article fails, **When** a later scheduled cycle or explicit manual retry is started, **Then** it performs at most one attempt for that article in the current cycle and does not create a second project or draft for the same source article.

### User Story 4 - Test and Preview the Automated Result (Priority: P2)

As the operator, I want to run an enabled subscription immediately and open the resulting project or publish-package preview, so that I can validate the automation before relying on the daily schedule.

**Why this priority**: A manual test path makes session, AI, media, formatting, and draft-box failures diagnosable without waiting for the next scheduled time.

**Independent Test**: Can be fully tested by selecting an enabled subscription, starting an immediate run, polling its status, and opening the generated publish-package preview or failure details.

**Acceptance Scenarios**:

1. **Given** an enabled subscription, **When** the operator chooses “立即执行”, **Then** the system starts the same workflow used by the scheduled cycle and exposes a task identifier and run detail.
2. **Given** an immediate run creates a publish package, **When** the operator opens its result, **Then** the formatted公众号 preview, source reference, selected style, and公众号 draft status are visible.
3. **Given** an immediate run fails, **When** the operator opens its result, **Then** the UI shows the failed stage and retry action without hiding the original error.

### Edge Cases

- The扫码登录会话 is missing, locally expired, or rejected by the公众号后台 while an account subscription is enabled.
- The account returns no articles or the latest available article has an empty link, unavailable body, or only a digest fallback.
- More than one new article appeared since the previous cycle; the run processes only the configured maximum and leaves the remaining articles eligible for later cycles.
- A source article was imported manually under the same link before the scheduled cycle; the scheduled cycle skips it.
- AI generation, cover generation, HTML rendering, image upload, or草稿写入 fails after an earlier stage has already persisted its output.
- The machine or service is offline at 21:00 and comes back later; the scheduler performs at most one catch-up run for the current local date instead of replaying every missed date.
- The service runs with multiple workers or a second runner is started accidentally; the same account/date is still processed at most once.
- A subscription is disabled while its run is already in progress; the current claimed run finishes or fails, and future cycles do not start another run.
- The selected account nickname changes after subscription creation; the stable account identity remains the subscription key while the display name can be refreshed.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow the operator to create a scheduled subscription from an account discovered through the existing扫码登录会话.
- **FR-002**: System MUST identify a subscription by the account's stable公众号 identity rather than by its display name alone.
- **FR-003**: System MUST persist whether each subscription is enabled, its schedule time, its time zone, its per-cycle fetch limit, and whether automatic draft writing is enabled.
- **FR-004**: System MUST default new subscriptions to 21:00 in `Asia/Shanghai`, a per-cycle fetch limit of 1, and automatic draft writing enabled.
- **FR-005**: System MUST evaluate due subscriptions on supported Windows, Linux, and macOS environments without requiring a Windows-specific task-scheduling mechanism.
- **FR-006**: System MUST retain the schedule and workflow state across service restarts and perform at most one current-date catch-up run for a missed schedule.
- **FR-007**: System MUST fetch the newest available articles for each due subscription and process no more than that subscription's configured per-cycle limit.
- **FR-008**: System MUST skip a source article that has already been imported or processed, using the source account and article identity/link as the duplicate boundary.
- **FR-009**: System MUST reuse the existing content-production chain to create the tracked article, topic, project, outline, rewritten draft, assets, formatted publish package, and preview.
- **FR-010**: System MUST persist enough workflow state to resume after a failure without recreating completed source, topic, project, asset, or package artifacts.
- **FR-011**: When automatic draft writing is enabled, the system MUST write only to the公众号草稿箱 and MUST NOT perform final群发 or public publication.
- **FR-012**: System MUST retain an explicit provenance marker that distinguishes automatically generated and automatically approved draft-box writes from manually operated workbench actions.
- **FR-013**: System MUST record each run's subscription, start and finish time, status, fetched count, imported count, skipped count, processed article, current stage, result, and failure reason when applicable.
- **FR-014**: System MUST stop the current article workflow at the first unrecoverable failure, expose an actionable error, and avoid unbounded immediate retries.
- **FR-015**: System MUST expose session-expired failures in the same扫码登录 status surface used by the existing manual flow.
- **FR-016**: System MUST provide an operator action to start the same workflow immediately for an enabled subscription without waiting for the scheduled time.
- **FR-017**: System MUST provide subscription management and run-history views that link successful runs to the generated project, formatted preview, and公众号 draft status.
- **FR-018**: System MUST claim a due subscription/date atomically so concurrent scheduler instances cannot process the same subscription/date more than once.
- **FR-019**: System MUST preserve the existing manual article import, manual project workflow, manual preview, manual approval, and manual draft-writing paths.
- **FR-020**: System MUST not require the operator to add AppID/AppSecret credentials when the existing扫码登录会话 is valid.

### Key Entities *(include if feature involves data)*

- **Automation Subscription**: A persisted instruction for one stable公众号 account, including display metadata, enabled state, local schedule, fetch limit, automatic draft mode, and latest run/cursor information.
- **Automation Run**: One scheduled or immediate execution for a subscription, including status, counts, current stage, timestamps, source article, generated project, and failure details.
- **Source Article Identity**: The stable account-and-article reference used to distinguish a new source article from one already imported or processed.
- **Automation Workflow State**: The persisted association between a source article and its tracked article, topic, project, publish package, and公众号 draft result, including the last completed stage.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can subscribe or unsubscribe one discovered公众号 account and see its next scheduled time in under 1 minute.
- **SC-002**: When the scheduler is running, an enabled subscription starts no later than 5 minutes after its configured local schedule time, including a current-date catch-up after a service restart.
- **SC-003**: For each subscription and scheduled local date, at most one source article is processed by default and concurrent scheduler instances create zero duplicate projects or草稿写入 operations.
- **SC-004**: For an unseen article and valid upstream services, one completed run exposes the generated project, formatted preview, and公众号草稿 status without manual stage-by-stage actions.
- **SC-005**: When a run fails, the operator can identify the account, article, failed stage, and actionable reason from the run detail within 1 minute of opening the automation view.
- **SC-006**: Retrying a failed article after a restart does not create duplicate tracked articles, topics, projects, publish packages, or公众号 drafts.
- **SC-007**: The same subscription and workflow behavior is available on supported Windows, Linux, and macOS environments without OS-specific scheduling configuration.
- **SC-008**: Across a verification set containing no-new-article, session-expired, AI-failure, cover-failure, and草稿写入-failure cases, every run ends in an explicit `completed`, `skipped`, or `failed` state with no silent loss.
- **SC-009**: No automated run results in final公众号群发; all automated successful outcomes remain identifiable as草稿箱 writes pending any later manual operation.

## Assumptions

- The operator has already established a valid扫码登录会话 and keeps at least one supported application or runner process available for schedule evaluation; the feature does not wake a fully stopped machine by itself.
- The default time zone is `Asia/Shanghai`; the subscription time zone is persisted so the schedule does not depend on the host machine's local time zone.
- The existing AI, cover-image, HTML rendering, and公众号后台 services remain configured and reachable when a run executes.
- A scheduled cycle processes one new article per account by default; if multiple unseen articles are available, later cycles or an explicit retry can process the remainder.
- Automatic draft mode is enabled for each new subscription by default and can be disabled per subscription, while final群发 always remains outside this feature.
- The feature remains single-operator and does not add multi-user permissions, account sharing, or operational BI.
- Source article rights, platform rules, and editorial suitability remain the operator's responsibility; the system only prepares a草稿 for review.
