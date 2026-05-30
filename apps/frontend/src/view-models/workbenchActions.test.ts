import assert from "node:assert/strict";

import {
  buildWorkbenchActionPlan,
  getWorkbenchBackgroundTaskDisplayError,
  shouldRetryWorkbenchBackgroundTaskPoll,
  shouldClearWorkbenchActionAfterPollError,
  shouldKeepWorkbenchActionActive,
} from "./workbenchActions.ts";

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

const baseCreativeDetail = {
  project: baseProject,
  outline: null,
  draft: null,
  assets: null,
  publish_package: null,
  retro: null,
  problem_brief: null,
  benchmarks: [],
  strategy_card: null,
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
  assert.equal(plan.primaryAction?.label, "原创增强精修");
  assert.equal(plan.secondaryActions.some((action) => action.kind === "generate_draft"), true);
  assert.equal(plan.showInstructionField, true);
  assert.equal(plan.canRestoreHistory, true);
});

test("buildWorkbenchActionPlan exposes cover-only regeneration separately from full assets regeneration", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "assets",
    detail: {
      project: {
        ...baseProject,
        stage: "assets_ready",
        chain_status: "ready",
        current_chain_state: "assets_ready",
        next_required_step: "build_publish_package",
        current_outline_version: 1,
        current_draft_version: 1,
        current_assets_version: 2,
      },
      outline: null,
      draft: {
        project_slug: "demo-project",
        outline_version: 1,
        version: 1,
        title: "draft title",
        body_markdown: "# draft",
        word_count: 1000,
        tone_profile_id: null,
        tone_profile_name: null,
      },
      assets: {
        project_slug: "demo-project",
        draft_version: 1,
        version: 2,
        title_options: ["title a"],
        cover_prompt: "prompt",
        cover_copy: "cover copy",
        social_teaser: "teaser",
        cover_image_path: "cover.png",
        cover_image_url: "/cover.png",
        tone_profile_id: null,
        tone_profile_name: null,
      },
      publish_package: null,
      retro: null,
    },
    historyEntryCount: 2,
  });

  assert.equal(plan.primaryAction?.kind, "polish_and_generate_assets");
  assert.equal(plan.primaryAction?.label, "原创增强后重生成素材包");
  assert.equal(plan.secondaryActions.some((action) => action.kind === "generate_assets"), true);
  assert.equal(plan.secondaryActions.some((action) => action.kind === "regenerate_cover_image"), true);
  assert.equal(plan.secondaryActions.some((action) => action.kind === "restore_assets"), true);
  assert.equal(plan.showInstructionField, true);
});

test("shouldKeepWorkbenchActionActive only keeps submitted background actions locked", () => {
  assert.equal(shouldKeepWorkbenchActionActive("build_publish_package", true), true);
  assert.equal(shouldKeepWorkbenchActionActive("polish_and_build_publish_package", true), true);
  assert.equal(shouldKeepWorkbenchActionActive("regenerate_from_review", true), true);
  assert.equal(shouldKeepWorkbenchActionActive("regenerate_cover_image", true), true);

  assert.equal(shouldKeepWorkbenchActionActive("build_publish_package", false), false);
  assert.equal(shouldKeepWorkbenchActionActive("polish_and_build_publish_package", false), false);
  assert.equal(shouldKeepWorkbenchActionActive("regenerate_from_review", false), false);
  assert.equal(shouldKeepWorkbenchActionActive("regenerate_cover_image", false), false);
  assert.equal(shouldKeepWorkbenchActionActive("generate_assets", true), false);
});

test("shouldRetryWorkbenchBackgroundTaskPoll keeps polling after transient poll errors", () => {
  assert.equal(shouldRetryWorkbenchBackgroundTaskPoll("queued"), true);
  assert.equal(shouldRetryWorkbenchBackgroundTaskPoll("running"), true);
  assert.equal(shouldRetryWorkbenchBackgroundTaskPoll("done"), false);
  assert.equal(shouldRetryWorkbenchBackgroundTaskPoll("failed"), false);
});

test("shouldClearWorkbenchActionAfterPollError keeps background actions locked while task is still active", () => {
  assert.equal(shouldClearWorkbenchActionAfterPollError(true), false);
  assert.equal(shouldClearWorkbenchActionAfterPollError(false), true);
});

test("getWorkbenchBackgroundTaskDisplayError prefers task failure detail then poll error", () => {
  assert.equal(
    getWorkbenchBackgroundTaskDisplayError({
      taskError: "生成失败",
      pollError: "网络中断",
    }),
    "生成失败",
  );
  assert.equal(
    getWorkbenchBackgroundTaskDisplayError({
      taskError: "",
      pollError: "网络中断",
    }),
    "网络中断",
  );
  assert.equal(
    getWorkbenchBackgroundTaskDisplayError({
      taskError: null,
      pollError: null,
    }),
    null,
  );
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

test("buildWorkbenchActionPlan exposes polish-before-publish generation when package is not ready yet", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "publish",
    detail: {
      project: {
        ...baseProject,
        stage: "assets_ready",
        chain_status: "ready",
        current_chain_state: "assets_ready",
        next_required_step: "build_publish_package",
        current_outline_version: 1,
        current_draft_version: 2,
        current_assets_version: 2,
        current_publish_package_version: null,
      },
      outline: null,
      draft: {
        project_slug: "demo-project",
        outline_version: 1,
        version: 2,
        title: "第二版正文",
        body_markdown: "# draft",
        word_count: 1280,
        tone_profile_id: null,
        tone_profile_name: null,
      },
      assets: {
        project_slug: "demo-project",
        draft_version: 2,
        version: 2,
        title_options: ["title a"],
        cover_prompt: "prompt",
        cover_copy: "cover copy",
        social_teaser: "teaser",
        cover_image_path: "cover.png",
        cover_image_url: "/cover.png",
        tone_profile_id: null,
        tone_profile_name: null,
      },
      publish_package: null,
      retro: null,
    },
    historyEntryCount: 2,
  });

  assert.equal(plan.primaryAction?.kind, "polish_and_build_publish_package");
  assert.equal(plan.primaryAction?.label, "原创增强后生成发布包");
  assert.equal(plan.secondaryActions.some((action) => action.kind === "build_publish_package"), true);
  assert.equal(plan.showInstructionField, true);
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

test("buildWorkbenchActionPlan exposes strategy generation on topic stage before any strategy exists", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "topic",
    detail: {
      ...baseCreativeDetail,
    },
    historyEntryCount: 0,
  });

  assert.equal(plan.primaryAction?.kind, "generate_strategy_package");
  assert.equal(plan.primaryAction?.label, "生成策略包");
  assert.equal(plan.secondaryActions.some((action) => action.kind === "generate_outline"), true);
  assert.equal(plan.showInstructionField, false);
});

test("buildWorkbenchActionPlan exposes strategy adoption on topic stage when a card exists but is not adopted", () => {
  const plan = buildWorkbenchActionPlan({
    stage: "topic",
    detail: {
      ...baseCreativeDetail,
      problem_brief: {
        project_slug: "demo-project",
        version: 2,
        source_mode: "topic",
        raw_goal: "写一篇关系文",
        clarified_problem: "读者总在反复确认关系稳定性。",
        target_reader_situation: "她总在等回复。",
        core_conflict: "越想确认越不敢直接开口。",
        unknowns: [],
        status: "ready",
        created_at: "2026-05-30T10:00:00Z",
      },
      benchmarks: [
        {
          project_slug: "demo-project",
          strategy_version: 2,
          reference_kind: "trend",
          reference_label: "关系边界重设",
          reference_pointer: "trend://relationship-boundary-reset",
          borrow_focus: "情绪入口",
          avoid_focus: "空泛喊话",
          rationale: "能借鉴开头的具体处境。",
          sort_order: 1,
        },
      ],
      strategy_card: {
        project_slug: "demo-project",
        version: 2,
        problem_brief_version: 2,
        reader_situation: "深夜反复看对话框，却不知道怎么开口。",
        point_of_view: "先承认不安，再拆开误会和期待。",
        conflict_frame: "想被重视，却总用沉默逼对方证明。",
        emotional_path: "嘴硬 -> 拉扯 -> 看见自己真正想要什么",
        expression_constraints: ["不要鸡汤总结", "避免对称句"],
        benchmark_summary: "借鉴情绪起手，避免模板化劝解。",
        status: "ready",
        created_at: "2026-05-30T10:02:00Z",
        adopted_at: null,
      },
    },
    historyEntryCount: 2,
  });

  assert.equal(plan.primaryAction?.kind, "adopt_strategy_card");
  assert.equal(plan.primaryAction?.label, "采纳当前策略卡");
  assert.equal(plan.secondaryActions.some((action) => action.kind === "generate_strategy_package"), true);
  assert.equal(plan.secondaryActions.some((action) => action.kind === "generate_outline"), true);
});
