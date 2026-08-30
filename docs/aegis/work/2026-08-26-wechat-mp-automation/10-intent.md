# 跨平台公众号自动抓取与自动草稿 - Intent

## TaskIntentDraft

- Requested outcome: 每天21:00从指定公众号抓取最新1篇，改写、排版并写入公众号草稿箱，支持跨平台运行
- Goal: 建立可持久化、可恢复、只写草稿不群发的公众号自动化流程
- Success evidence:
- feature spec获用户审阅；后续实现通过调度、幂等、会话过期、失败恢复和草稿写入测试
- Stop condition: 完成、需要验证、阻塞或超出范围时停止；不自动群发，不覆盖现有脏改动
- Non-goals:
- Windows专属任务计划、多账号权限系统、公众号自动群发、无限重试
- Scope: 跨平台调度、公众号订阅配置、抓取游标、自动改写排版、草稿写入、管理界面与验证
- Change kinds:
- architecture-contract-cross-module
- Risk hints:
- 涉及持久化配置、跨进程调度、扫码会话和外部草稿写入；需防重复处理与会话过期

## BaselineReadSetHint

- docs/aegis/BASELINE-GOVERNANCE.md
- docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md
- specs/004-creative-workflow/spec.md

## BaselineUsageDraft

- Required baseline refs:
- docs/aegis/BASELINE-GOVERNANCE.md
- docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md
- specs/004-creative-workflow/spec.md
- Acknowledged before plan:
- none
- Cited in plan:
- none
- Missing refs:
- docs/aegis/BASELINE-GOVERNANCE.md
- docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md
- specs/004-creative-workflow/spec.md
- Advisory decision: needs-baseline-readback

## ImpactStatementDraft

- Compatibility boundary: 保留现有扫码会话、手动工作台链路、人工草稿发布入口和所有用户未提交改动
- Affected layers:
- apps/backend/app/services/wechat_mp_client.py, apps/backend/app/services/workbench.py, apps/backend/app/services/wechat_mp_draft_publisher.py
- Owners:
- wechat_mp_automation service owns subscription, scheduling, cursor and orchestration; existing services retain fetch, content pipeline and draft adapter ownership
- Invariants:
- 同一订阅同一文章不重复创建项目或写入草稿；自动化只进入草稿箱，不群发
- Non-goals:
- Windows专属任务计划、多账号权限系统、公众号自动群发、无限重试

These records are Method Pack drafts / hints, not authoritative runtime decisions.

## BaselineUsageDraft

- Required baseline refs:
- docs/aegis/BASELINE-GOVERNANCE.md
- docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md
- specs/004-creative-workflow/spec.md
- Delivered context refs:
- none
- Acknowledged before plan:
- docs/aegis/BASELINE-GOVERNANCE.md
- docs/aegis/plans/2026-05-16-gankaigc-wechat-content-workbench-plan.md
- specs/004-creative-workflow/spec.md
- Cited in plan:
- none
- Missing refs:
- none
- Advisory decision: continue
