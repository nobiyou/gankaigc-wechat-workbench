import assert from "node:assert/strict";

import { buildProjectWorkbenchTarget, buildWorkbenchStageViews, resolveRecommendedWorkbenchStage } from "./workbenchStages.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("resolveRecommendedWorkbenchStage prefers the next required production step", () => {
  assert.equal(
    resolveRecommendedWorkbenchStage({
      slug: "draft-project",
      topic_slug: "draft-topic",
      title: "待生成初稿",
      stage: "outline_ready",
      owner: "editorial",
      preferred_tone_profile_id: null,
      preferred_tone_profile_name: null,
      chain_status: "stale",
      current_chain_state: "outline_ready",
      next_required_step: "generate_draft",
      current_outline_version: 1,
      current_draft_version: null,
      current_assets_version: null,
      current_publish_package_version: null,
      retro: null,
    }),
    "draft",
  );

  assert.equal(
    resolveRecommendedWorkbenchStage({
      slug: "publish-project",
      topic_slug: "publish-topic",
      title: "待发布包",
      stage: "assets_ready",
      owner: "editorial",
      preferred_tone_profile_id: null,
      preferred_tone_profile_name: null,
      chain_status: "ready",
      current_chain_state: "assets_ready",
      next_required_step: "build_publish_package",
      current_outline_version: 1,
      current_draft_version: 1,
      current_assets_version: 1,
      current_publish_package_version: null,
      retro: null,
    }),
    "publish",
  );
});

test("resolveRecommendedWorkbenchStage falls back to current chain state when no next step is pending", () => {
  assert.equal(
    resolveRecommendedWorkbenchStage({
      slug: "published-project",
      topic_slug: "published-topic",
      title: "已发布项目",
      stage: "published",
      owner: "editorial",
      preferred_tone_profile_id: null,
      preferred_tone_profile_name: null,
      chain_status: "ready",
      current_chain_state: "published",
      next_required_step: null,
      current_outline_version: 1,
      current_draft_version: 2,
      current_assets_version: 2,
      current_publish_package_version: 2,
      retro: null,
    }),
    "publish",
  );
});

test("resolveRecommendedWorkbenchStage follows rollback chain state after review sends publish back upstream", () => {
  assert.equal(
    resolveRecommendedWorkbenchStage({
      slug: "revision-project",
      topic_slug: "revision-topic",
      title: "审核退回项目",
      stage: "revision_requested",
      owner: "editorial",
      preferred_tone_profile_id: null,
      preferred_tone_profile_name: null,
      chain_status: "stale",
      current_chain_state: "draft_ready",
      next_required_step: "generate_assets",
      current_outline_version: 1,
      current_draft_version: 3,
      current_assets_version: null,
      current_publish_package_version: null,
      retro: null,
    }),
    "assets",
  );
});

test("buildProjectWorkbenchTarget deep-links projects into their recommended workbench stage", () => {
  assert.equal(
    buildProjectWorkbenchTarget({
      slug: "outline-project",
      topic_slug: "outline-topic",
      title: "待生成大纲",
      stage: "outline",
      owner: "editorial",
      preferred_tone_profile_id: null,
      preferred_tone_profile_name: null,
      chain_status: "missing",
      current_chain_state: "missing_outline",
      next_required_step: "generate_outline",
      current_outline_version: null,
      current_draft_version: null,
      current_assets_version: null,
      current_publish_package_version: null,
      retro: null,
    }),
    "/projects/outline-project/workbench/outline",
  );
});

test("buildWorkbenchStageViews marks active and recommended stages while exposing version counts", () => {
  const stages = buildWorkbenchStageViews({
    project: {
      slug: "draft-project",
      topic_slug: "draft-topic",
      title: "待生成初稿",
      stage: "outline_ready",
      owner: "editorial",
      preferred_tone_profile_id: null,
      preferred_tone_profile_name: null,
      chain_status: "stale",
      current_chain_state: "outline_ready",
      next_required_step: "generate_draft",
      current_outline_version: 1,
      current_draft_version: null,
      current_assets_version: null,
      current_publish_package_version: null,
      retro: null,
    },
    activeStage: "outline",
    versions: {
      project_slug: "draft-project",
      outlines: [{ project_slug: "draft-project", version: 1, hook: "hook", outline_body: "1. a", tone_profile_id: null, tone_profile_name: null }],
      drafts: [],
      assets: [],
      publish_packages: [],
    },
  });

  assert.equal(stages.find((stage) => stage.key === "outline")?.isActive, true);
  assert.equal(stages.find((stage) => stage.key === "draft")?.isRecommended, true);
  assert.equal(stages.find((stage) => stage.key === "outline")?.versionCount, 1);
  assert.equal(stages.find((stage) => stage.key === "publish")?.targetPath, "/projects/draft-project/workbench/publish");
});
