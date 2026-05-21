import assert from "node:assert/strict";

import { buildProjectGroups } from "./projectGroups.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildProjectGroups buckets projects by production ownership without duplicating pending retro work", () => {
  const groups = buildProjectGroups({
    projects: [
      {
        slug: "chain-project",
        topic_slug: "chain-topic",
        title: "待续链项目",
        stage: "outline_ready",
        owner: "editorial",
        preferred_tone_profile_id: 1,
        preferred_tone_profile_name: "叙事",
        chain_status: "stale",
        current_chain_state: "outline_ready",
        next_required_step: "generate_draft",
        current_outline_version: 1,
        current_draft_version: null,
        current_assets_version: null,
        current_publish_package_version: null,
        retro: null,
      },
      {
        slug: "review-project",
        topic_slug: "review-topic",
        title: "待审稿项目",
        stage: "publish_ready",
        owner: "qa",
        preferred_tone_profile_id: 2,
        preferred_tone_profile_name: "观点",
        chain_status: "ready",
        current_chain_state: "publish_ready",
        next_required_step: null,
        current_outline_version: 1,
        current_draft_version: 1,
        current_assets_version: 1,
        current_publish_package_version: 1,
        retro: null,
      },
      {
        slug: "retro-project",
        topic_slug: "retro-topic",
        title: "已发布待复盘",
        stage: "published",
        owner: "editorial",
        preferred_tone_profile_id: null,
        preferred_tone_profile_name: null,
        chain_status: "ready",
        current_chain_state: "published",
        next_required_step: null,
        current_outline_version: 1,
        current_draft_version: 1,
        current_assets_version: 1,
        current_publish_package_version: 1,
        retro: null,
      },
      {
        slug: "published-project",
        topic_slug: "published-topic",
        title: "已完成复盘项目",
        stage: "published",
        owner: "editorial",
        preferred_tone_profile_id: null,
        preferred_tone_profile_name: null,
        chain_status: "ready",
        current_chain_state: "published",
        next_required_step: null,
        current_outline_version: 1,
        current_draft_version: 1,
        current_assets_version: 1,
        current_publish_package_version: 1,
        retro: {
          project_slug: "published-project",
          performance_rating: 4,
          summary: "完成复盘",
          wins: ["结构稳定"],
          gaps: ["封面普通"],
          next_focus: "增强标题",
          recorded_at: "2026-05-18T10:00:00Z",
        },
      },
    ],
  });

  assert.deepEqual(groups.map((group) => ({ key: group.groupKey, count: group.count })), [
    { key: "chain", count: 1 },
    { key: "review", count: 1 },
    { key: "retro", count: 1 },
    { key: "published", count: 1 },
  ]);
});

test("buildProjectGroups applies lightweight search and owner filtering before grouping", () => {
  const groups = buildProjectGroups({
    projects: [
      {
        slug: "chain-project",
        topic_slug: "chain-topic",
        title: "办公室关系修复",
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
      {
        slug: "review-project",
        topic_slug: "review-topic",
        title: "亲密关系边界",
        stage: "publish_ready",
        owner: "qa",
        preferred_tone_profile_id: null,
        preferred_tone_profile_name: null,
        chain_status: "ready",
        current_chain_state: "publish_ready",
        next_required_step: null,
        current_outline_version: 1,
        current_draft_version: 1,
        current_assets_version: 1,
        current_publish_package_version: 1,
        retro: null,
      },
    ],
    filters: {
      query: "办公室",
      owner: "editorial",
    },
  });

  assert.deepEqual(groups.map((group) => group.groupKey), ["chain"]);
  assert.deepEqual(groups[0]?.projects.map((project) => project.slug), ["chain-project"]);
});
