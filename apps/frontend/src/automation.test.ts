import assert from "node:assert/strict";

import {
  canRetryAutomationRun,
  createAutomationSubscriptionDraft,
  createAutomationSubscriptionEditDraft,
  findAutomationSubscription,
  formatAutomationSaveError,
  formatAutomationRunStatus,
  formatAutomationSchedule,
  getAutomationAccountIdentity,
} from "./automation.ts";
import { resolveBackendAssetUrl } from "./view-models/workbenchPreview.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("automation draft defaults to the approved 21:00 schedule", () => {
  assert.deepEqual(createAutomationSubscriptionDraft(), {
    account_fakeid: "",
    account_biz: "",
    account_nickname: "",
    account_alias: "",
    account_avatar_url: "",
    article_source: "wechat_mp",
    schedule_time: "21:00",
    timezone: "Asia/Shanghai",
    fetch_limit: 1,
    automatic_draft: true,
  });
});

test("wx_channel account draft uses biz as its stable subscription identity", () => {
  const draft = createAutomationSubscriptionDraft({
    source: "wx_channel",
    biz: "MzA4-example",
    nickname: "Example Account",
    avatar_url: "https://img.example/avatar.jpg",
    is_effective: true,
    article_count: 3,
    archived_count: 0,
    last_sync_at: 0,
    sync_status: "completed",
    sync_error: "",
  });

  assert.equal(draft.account_fakeid, "MzA4-example");
  assert.equal(draft.account_biz, "MzA4-example");
  assert.equal(draft.article_source, "wx_channel");
  assert.equal(getAutomationAccountIdentity({ nickname: "Example Account", biz: "MzA4-example" }), "Example Account · MzA4-example");
});

test("editing a subscription keeps its account identity and loads editable settings", () => {
  const draft = createAutomationSubscriptionEditDraft({
    account_fakeid: "MzA4-example",
    account_biz: "MzA4-example",
    account_nickname: "Example Account",
    account_alias: null,
    account_avatar_url: null,
    article_source: "wx_channel",
    schedule_time: "20:30",
    timezone: "Asia/Shanghai",
    fetch_limit: 3,
    automatic_draft: false,
  });

  assert.deepEqual(draft, {
    account_fakeid: "MzA4-example",
    account_biz: "MzA4-example",
    account_nickname: "Example Account",
    account_alias: "",
    account_avatar_url: "",
    article_source: "wx_channel",
    schedule_time: "20:30",
    timezone: "Asia/Shanghai",
    fetch_limit: 3,
    automatic_draft: false,
  });
});

test("scan and captured account results resolve to the same existing subscription", () => {
  const subscription = {
    id: 7,
    account_fakeid: "MzA4-example",
    account_biz: null,
    account_nickname: "Example Account",
    account_alias: "example",
    account_avatar_url: null,
    article_source: "wechat_mp" as const,
    enabled: true,
    schedule_time: "21:00",
    timezone: "Asia/Shanghai",
    fetch_limit: 1,
    automatic_draft: true,
    next_run_at: null,
    last_scheduled_local_date: null,
    last_run_id: null,
    last_run_status: null,
    last_run_stage: null,
    last_success_at: null,
    last_error: null,
    created_at: "2026-08-30T00:00:00Z",
    updated_at: "2026-08-30T00:00:00Z",
  };
  const match = findAutomationSubscription(
    {
      source: "wx_channel",
      biz: "MzA4-example",
      nickname: "Example Account",
      avatar_url: "",
      is_effective: true,
      article_count: 1,
      archived_count: 0,
      last_sync_at: 0,
      sync_status: "completed",
      sync_error: "",
    },
    [subscription],
  );
  assert.equal(match?.id, 7);
});

test("automation account identity keeps same-nickname accounts distinct", () => {
  assert.equal(getAutomationAccountIdentity({ nickname: "同名公众号", fakeid: "fakeid-a" }), "同名公众号 · fakeid-a");
  assert.notEqual(
    getAutomationAccountIdentity({ nickname: "同名公众号", fakeid: "fakeid-a" }),
    getAutomationAccountIdentity({ nickname: "同名公众号", fakeid: "fakeid-b" }),
  );
});

test("automation labels expose schedule and retry state", () => {
  assert.equal(
    formatAutomationSchedule({ schedule_time: "21:00", timezone: "Asia/Shanghai", enabled: true }),
    "每天 21:00 · Asia/Shanghai",
  );
  assert.equal(
    formatAutomationRunStatus({ status: "failed", stage: "writing_draft" }),
    "失败 · writing_draft",
  );
  assert.equal(canRetryAutomationRun({ retryable: true, status: "failed" }), true);
  assert.equal(canRetryAutomationRun({ retryable: true, status: "completed" }), false);
});

test("duplicate subscription errors point to editing the existing subscription", () => {
  assert.equal(
    formatAutomationSaveError(new Error("This WeChat account is already subscribed")),
    "该公众号已经有订阅，请在右侧订阅列表中点击“编辑”修改。",
  );
  assert.equal(formatAutomationSaveError(new Error("network unavailable")), "network unavailable");
});

test("generated asset links resolve against the backend origin", () => {
  assert.equal(
    resolveBackendAssetUrl("/generated-assets/run-preview.html"),
    "http://localhost:8000/generated-assets/run-preview.html",
  );
  assert.equal(
    resolveBackendAssetUrl("https://cdn.example.com/run-preview.html"),
    "https://cdn.example.com/run-preview.html",
  );
  assert.equal(resolveBackendAssetUrl("  "), "");
});
