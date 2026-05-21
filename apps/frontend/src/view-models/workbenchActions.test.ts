import assert from "node:assert/strict";

import { buildWorkbenchActionPlan } from "./workbenchActions.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

const baseProject = {
  slug: "demo-project",
  topic_slug: "demo-topic",
  title: "演示项目",
  stage: "outline",
  owner: "editorial",
  preferred_tone_profile_id: null,
  preferred_tone_profile_name: null,
  chain_status: "missing" as const,
  current_chain_state: "missing_outline",
  next_required_step: "generate_outline",
  current_outline_version: null,
  current_draft_version: null,
  current_assets_version: null,
  current_publish_package_version: null,
  retro: null,
};

test("buildWorkbenchActionPlan exposes outline generation when outline is missing", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "outline",
    detail: {
      project: baseProject,
      outline: null,
      draft: null,
      assets: null,
      publish_package: null,
      retro: null,
    },
    historyEntryCount: 0,
  });

  assert.equal(plan.primaryAction?.kind, "generate_outline");
  assert.equal(plan.primaryAction?.label, "生成大纲");
  assert.equal(plan.canRestoreHistory, false);
});

test("buildWorkbenchActionPlan only exposes history restore entry when a concrete version list exists", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "outline",
    detail: {
      project: {
        ...baseProject,
        current_chain_state: "outline_ready",
        next_required_step: "generate_draft",
        current_outline_version: 2,
      },
      outline: {
        project_slug: "demo-project",
        version: 2,
        hook: "hook v2",
        outline_body: "1. a\n2. b",
        tone_profile_id: null,
        tone_profile_name: null,
      },
      draft: null,
      assets: null,
      publish_package: null,
      retro: null,
    },
    historyEntryCount: 2,
  });

  assert.equal(plan.secondaryActions.some((action) => action.kind === "restore_outline"), true);
  assert.equal(plan.canRestoreHistory, true);
});

test("buildWorkbenchActionPlan exposes draft generation and polish paths when draft stage is active", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "draft",
    detail: {
      project: {
        ...baseProject,
        current_chain_state: "outline_ready",
        next_required_step: "generate_draft",
        current_outline_version: 1,
      },
      outline: {
        project_slug: "demo-project",
        version: 1,
        hook: "hook",
        outline_body: "1. a",
        tone_profile_id: null,
        tone_profile_name: null,
      },
      draft: {
        project_slug: "demo-project",
        outline_version: 1,
        version: 2,
        title: "第二版初稿",
        body_markdown: "# body",
        word_count: 1200,
        tone_profile_id: null,
        tone_profile_name: null,
      },
      assets: null,
      publish_package: null,
      retro: null,
    },
    historyEntryCount: 2,
  });

  assert.equal(plan.primaryAction?.kind, "polish_draft");
  assert.equal(plan.primaryAction?.label, "精修初稿");
  assert.equal(plan.secondaryActions.some((action) => action.kind === "generate_draft"), true);
  assert.equal(plan.showInstructionField, true);
  assert.equal(plan.canRestoreHistory, true);
});

test("buildWorkbenchActionPlan exposes publish review actions for ready packages", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "publish",
    detail: {
      project: {
        ...baseProject,
        stage: "publish_ready",
        chain_status: "ready",
        current_chain_state: "publish_ready",
        next_required_step: null,
        current_outline_version: 1,
        current_draft_version: 1,
        current_assets_version: 1,
        current_publish_package_version: 1,
      },
      outline: null,
      draft: null,
      assets: null,
      publish_package: {
        project_slug: "demo-project",
        draft_version: 1,
        assets_version: 1,
        version: 1,
        abstract: "摘要",
        tags: ["a"],
        publish_checklist: ["check"],
        editor_note: "note",
        markdown_path: "a.md",
        markdown_url: "/a.md",
        manifest_path: "a.json",
        manifest_url: "/a.json",
        status: "ready",
        review_comment: null,
        reviewed_by: null,
        reviewed_at: null,
        tone_profile_id: null,
        tone_profile_name: null,
      },
      retro: null,
    },
    historyEntryCount: 1,
  });

  assert.equal(plan.showPublishReviewForm, true);
  assert.equal(plan.primaryAction?.kind, "approve_publish_package");
  assert.equal(plan.secondaryActions.some((action) => action.kind === "request_publish_revision"), true);
});

test("buildWorkbenchActionPlan exposes regenerate and retro actions in the right publish states", () => {
  const regeneratePlan = buildWorkbenchActionPlan({
    stage: "publish",
    detail: {
      project: {
        ...baseProject,
        stage: "revision_requested",
        current_chain_state: "publish_ready",
        next_required_step: "regenerate_from_review",
        current_outline_version: 1,
        current_draft_version: 1,
        current_assets_version: 1,
        current_publish_package_version: 2,
      },
      outline: null,
      draft: null,
      assets: null,
      publish_package: {
        project_slug: "demo-project",
        draft_version: 1,
        assets_version: 1,
        version: 2,
        abstract: "摘要",
        tags: ["a"],
        publish_checklist: ["check"],
        editor_note: "note",
        markdown_path: "a.md",
        markdown_url: "/a.md",
        manifest_path: "a.json",
        manifest_url: "/a.json",
        status: "needs_revision",
        review_comment: "需要更强开头",
        reviewed_by: "ops",
        reviewed_at: "2026-05-19T10:00:00Z",
        tone_profile_id: null,
        tone_profile_name: null,
      },
      retro: null,
    },
    historyEntryCount: 2,
  });

  assert.equal(regeneratePlan.primaryAction?.kind, "regenerate_from_review");
  assert.equal(regeneratePlan.secondaryActions.some((action) => action.label === "基于历史版本重建发布包"), true);

  const retroPlan = buildWorkbenchActionPlan({
    stage: "publish",
    detail: {
      project: {
        ...baseProject,
        stage: "published",
        chain_status: "ready",
        current_chain_state: "published",
        next_required_step: null,
        current_outline_version: 1,
        current_draft_version: 1,
        current_assets_version: 1,
        current_publish_package_version: 3,
      },
      outline: null,
      draft: null,
      assets: null,
      publish_package: {
        project_slug: "demo-project",
        draft_version: 1,
        assets_version: 1,
        version: 3,
        abstract: "摘要",
        tags: ["a"],
        publish_checklist: ["check"],
        editor_note: "note",
        markdown_path: "a.md",
        markdown_url: "/a.md",
        manifest_path: "a.json",
        manifest_url: "/a.json",
        status: "approved",
        review_comment: "通过",
        reviewed_by: "ops",
        reviewed_at: "2026-05-19T10:00:00Z",
        tone_profile_id: null,
        tone_profile_name: null,
      },
      retro: null,
    },
    historyEntryCount: 3,
  });

  assert.equal(retroPlan.showRetroForm, true);
  assert.equal(retroPlan.primaryAction?.kind, "record_project_retro");
  assert.equal(retroPlan.secondaryActions.some((action) => action.label === "基于历史版本重建发布包"), true);
});

test("buildWorkbenchActionPlan suppresses publish regeneration while rollback chain is still upstream", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "publish",
    detail: {
      project: {
        ...baseProject,
        stage: "draft_ready",
        chain_status: "ready",
        current_chain_state: "draft_ready",
        next_required_step: "generate_assets",
        current_outline_version: 1,
        current_draft_version: 7,
        current_assets_version: null,
        current_publish_package_version: null,
      },
      outline: null,
      draft: {
        project_slug: "demo-project",
        outline_version: 1,
        version: 7,
        title: "回退重生成后的初稿",
        body_markdown: "# regenerated",
        word_count: 1320,
        tone_profile_id: null,
        tone_profile_name: null,
      },
      assets: null,
      publish_package: null,
      retro: null,
    },
    historyEntryCount: 4,
  });

  assert.equal(plan.primaryAction, null);
  assert.equal(plan.secondaryActions.some((action) => action.kind === "restore_publish_package"), true);
  assert.equal(plan.showPublishReviewForm, false);
});

test("buildWorkbenchActionPlan keeps published-and-retro-complete workbench in read-only publish mode", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "publish",
    detail: {
      project: {
        ...baseProject,
        stage: "published",
        chain_status: "ready",
        current_chain_state: "published",
        next_required_step: null,
        current_outline_version: 1,
        current_draft_version: 7,
        current_assets_version: 6,
        current_publish_package_version: 11,
      },
      outline: null,
      draft: null,
      assets: null,
      publish_package: {
        project_slug: "demo-project",
        draft_version: 7,
        assets_version: 6,
        version: 11,
        abstract: "摘要",
        tags: ["a"],
        publish_checklist: ["check"],
        editor_note: "note",
        markdown_path: "a.md",
        markdown_url: "/a.md",
        manifest_path: "a.json",
        manifest_url: "/a.json",
        status: "approved",
        review_comment: "审核通过，可进入发布。",
        reviewed_by: "chief-editor",
        reviewed_at: "2026-05-20T10:00:00Z",
        tone_profile_id: null,
        tone_profile_name: null,
      },
      retro: {
        project_slug: "demo-project",
        performance_rating: 5,
        summary: "复盘已记录",
        wins: ["审核链打通"],
        gaps: ["需要继续优化中段节奏"],
        next_focus: "优化封面与标题一致性。",
        recorded_at: "2026-05-20T10:10:00Z",
      },
    },
    historyEntryCount: 4,
  });

  assert.equal(plan.primaryAction, null);
  assert.equal(plan.showRetroForm, false);
  assert.equal(plan.secondaryActions.some((action) => action.kind === "restore_publish_package"), true);
});
