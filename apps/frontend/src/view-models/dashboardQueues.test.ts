import assert from "node:assert/strict";

import { buildDashboardQueueCards, buildDashboardQueueState } from "./dashboardQueues.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildDashboardQueueState derives task-first queues from projects, topics, and trends", () => {
  const state = buildDashboardQueueState({
    trends: [
      {
        slug: "late-night-recovery",
        title: "深夜情绪恢复观察",
        source: "manual",
        heat_score: 73,
        status: "screening",
      },
      {
        slug: "already-promoted",
        title: "已推进热点",
        source: "manual",
        heat_score: 66,
        status: "screening",
      },
    ],
    topics: [
      {
        slug: "office-burnout-recovery-topic",
        trend_slug: "office-burnout-recovery",
        source_type: "trend",
        source_ref_slug: "office-burnout-recovery",
        title: "深夜恢复可写选题",
        angle: "共鸣切入",
        status: "pending",
      },
      {
        slug: "already-promoted-topic",
        trend_slug: "already-promoted",
        source_type: "trend",
        source_ref_slug: "already-promoted",
        title: "已推进选题",
        angle: "观点提炼",
        status: "pending",
      },
    ],
    projects: [
      {
        slug: "publish-ready-project",
        topic_slug: "review-topic",
        title: "待审稿项目",
        stage: "publish_ready",
        owner: "editorial",
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
      {
        slug: "chain-project",
        topic_slug: "chain-topic",
        title: "待续链项目",
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
        slug: "retro-project",
        topic_slug: "retro-topic",
        title: "待复盘项目",
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
        slug: "promoted-project",
        topic_slug: "already-promoted-topic",
        title: "已从选题建项目",
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
      },
    ],
  });

  assert.deepEqual(
    state.actionableItems.map((item) => item.kind),
    ["project-review", "project-retro", "project-chain", "project-chain", "topic-project", "trend-topic"],
  );
  assert.deepEqual(state.topicQueueTopics.map((topic) => topic.slug), ["office-burnout-recovery-topic"]);
  assert.deepEqual(state.trendQueueTrends.map((trend) => trend.slug), ["late-night-recovery"]);
});

test("buildDashboardQueueCards shapes deep-linkable queue cards with tone", () => {
  const cards = buildDashboardQueueCards(
    buildDashboardQueueState({
      trends: [],
      topics: [],
      projects: [
        {
          slug: "publish-ready-project",
          topic_slug: "review-topic",
          title: "待审稿项目",
          stage: "publish_ready",
          owner: "editorial",
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
    }),
  );

  assert.deepEqual(
    cards.map((card) => ({ key: card.key, count: card.count, tone: card.tone, targetPath: card.targetPath })),
    [
      { key: "review", count: 1, tone: "ready", targetPath: "/projects" },
      { key: "retro", count: 0, tone: "empty", targetPath: "/projects" },
      { key: "chain", count: 0, tone: "empty", targetPath: "/projects" },
      { key: "topic", count: 0, tone: "empty", targetPath: "/pipeline/topics" },
      { key: "trend", count: 0, tone: "empty", targetPath: "/sources/trends" },
    ],
  );
});

test("buildDashboardQueueCards keeps all cards empty when no actionable work exists", () => {
  const cards = buildDashboardQueueCards(
    buildDashboardQueueState({
      trends: [],
      topics: [],
      projects: [],
    }),
  );

  assert.deepEqual(
    cards.map((card) => ({ key: card.key, count: card.count, tone: card.tone })),
    [
      { key: "review", count: 0, tone: "empty" },
      { key: "retro", count: 0, tone: "empty" },
      { key: "chain", count: 0, tone: "empty" },
      { key: "topic", count: 0, tone: "empty" },
      { key: "trend", count: 0, tone: "empty" },
    ],
  );
});

test("buildDashboardQueueCards marks non-review queues as warning when they contain actionable work", () => {
  const cards = buildDashboardQueueCards(
    buildDashboardQueueState({
      trends: [
        {
          slug: "trend-backlog",
          title: "待转热点",
          source: "manual",
          heat_score: 80,
          status: "screening",
        },
      ],
      topics: [
        {
          slug: "topic-backlog",
          trend_slug: null,
          source_type: "manual",
          source_ref_slug: "manual-note",
          title: "待建项目选题",
          angle: "共鸣切入",
          status: "pending",
        },
      ],
      projects: [
        {
          slug: "chain-project",
          topic_slug: "existing-topic",
          title: "待续链项目",
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
          slug: "retro-project",
          topic_slug: "retro-topic",
          title: "待复盘项目",
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
      ],
    }),
  );

  assert.deepEqual(
    cards.map((card) => ({ key: card.key, count: card.count, tone: card.tone })),
    [
      { key: "review", count: 0, tone: "empty" },
      { key: "retro", count: 1, tone: "warning" },
      { key: "chain", count: 1, tone: "warning" },
      { key: "topic", count: 1, tone: "warning" },
      { key: "trend", count: 1, tone: "warning" },
    ],
  );
});
