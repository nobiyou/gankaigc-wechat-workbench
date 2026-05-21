import assert from "node:assert/strict";

import { buildBatchRunCards, buildPipelineViewsState } from "./pipelineViews.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildPipelineViewsState exposes topic queue, batch runs, and pipeline-owned task log entries", () => {
  const state = buildPipelineViewsState({
    topics: [
      {
        slug: "topic-queue-item",
        trend_slug: "trend-1",
        source_type: "tracked_article",
        source_ref_slug: "trend-1",
        title: "待建项目选题",
        angle: "共鸣切入",
        status: "pending",
      },
      {
        slug: "already-project-topic",
        trend_slug: "trend-2",
        source_type: "trend",
        source_ref_slug: "trend-2",
        title: "已建项目选题",
        angle: "观点提炼",
        status: "pending",
      },
    ],
    projects: [
      {
        slug: "existing-project",
        topic_slug: "already-project-topic",
        title: "已建项目",
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
    recentTasks: [
      {
        id: "task-batch-done",
        task_type: "batch_create_projects",
        status: "done",
        entity_slug: "batch-20260519",
        entity_type: "batch",
        created_at: "2026-05-19T09:00:00Z",
      },
      {
        id: "task-batch-running",
        task_type: "batch_generate_topics",
        status: "running",
        entity_slug: "batch-20260518",
        entity_type: "batch",
        created_at: "2026-05-19T08:00:00Z",
      },
      {
        id: "task-batch-skipped",
        task_type: "batch_generate_topics",
        status: "skipped",
        entity_slug: "batch-20260517",
        entity_type: "batch",
        created_at: "2026-05-19T07:00:00Z",
      },
    ],
  });

  assert.deepEqual(state.topicQueue.items.map((item) => item.topic.slug), ["topic-queue-item"]);
  assert.equal(state.topicQueue.items[0]?.sourceLabel, "参考文章 / trend-1");
  assert.deepEqual(
    state.batchRuns.items.map((item) => ({ id: item.id, status: item.normalizedStatus })),
    [
      { id: "task-batch-done", status: "done" },
      { id: "task-batch-running", status: "running" },
      { id: "task-batch-skipped", status: "skipped" },
    ],
  );
  assert.deepEqual(state.batchRuns.statusSummary, { total: 3, done: 1, running: 1, failed: 0, skipped: 1 });
  assert.deepEqual(state.taskLog.statusSummary, { total: 3, done: 1, running: 1, failed: 0, skipped: 1 });
});

test("buildPipelineViewsState filters task log by normalized status and preserves retry signals", () => {
  const state = buildPipelineViewsState({
    topics: [],
    projects: [],
    recentTasks: [
      {
        id: "task-failed",
        task_type: "batch_continue_projects",
        status: "error",
        entity_slug: "batch-1",
        entity_type: "batch",
        created_at: "2026-05-19T10:00:00Z",
      },
      {
        id: "task-done",
        task_type: "outline_generation",
        status: "done",
        entity_slug: "project-1",
        entity_type: "project",
        created_at: "2026-05-19T09:00:00Z",
      },
      {
        id: "task-skipped",
        task_type: "batch_create_projects",
        status: "skipped",
        entity_slug: "batch-2",
        entity_type: "batch",
        created_at: "2026-05-19T08:00:00Z",
      },
    ],
    taskLogFilter: "failed",
  });

  assert.deepEqual(state.taskLog.items.map((item) => item.id), ["task-failed"]);
  assert.equal(state.taskLog.items[0]?.canRetry, true);
  assert.equal(state.taskLog.items[0]?.normalizedStatus, "failed");
  assert.deepEqual(state.taskLog.statusSummary, { total: 1, done: 0, running: 0, failed: 1, skipped: 0 });
});

test("buildPipelineViewsState treats batch runs with failed_count in background task detail as failed", () => {
  const state = buildPipelineViewsState({
    topics: [],
    projects: [],
    recentTasks: [
      {
        id: "task-partial-failure",
        task_type: "batch_generate_topics",
        status: "done",
        entity_slug: "batch-3",
        entity_type: "batch",
        created_at: "2026-05-19T10:00:00Z",
        background_task_id: "bg-task-3",
      },
    ],
    taskLogFilter: "failed",
    backgroundTaskDetails: {
      "bg-task-3": {
        result: {
          requested_count: 2,
          processed_count: 1,
          skipped_count: 0,
          failed_count: 1,
        },
      },
    },
  });

  assert.deepEqual(state.taskLog.items.map((item) => item.id), ["task-partial-failure"]);
  assert.equal(state.taskLog.items[0]?.normalizedStatus, "failed");
  assert.equal(state.taskLog.items[0]?.canRetry, true);
  assert.equal(state.taskLog.items[0]?.backgroundTaskFailedCount, 1);
  assert.deepEqual(state.taskLog.statusSummary, { total: 1, done: 0, running: 0, failed: 1, skipped: 0 });
});

test("buildPipelineViewsState supports skipped task filtering without collapsing it into running", () => {
  const state = buildPipelineViewsState({
    topics: [],
    projects: [],
    recentTasks: [
      {
        id: "task-skipped",
        task_type: "batch_continue_projects",
        status: "skipped",
        entity_slug: "batch-1",
        entity_type: "batch",
        created_at: "2026-05-19T10:00:00Z",
      },
      {
        id: "task-running",
        task_type: "batch_continue_projects",
        status: "running",
        entity_slug: "batch-2",
        entity_type: "batch",
        created_at: "2026-05-19T09:00:00Z",
      },
    ],
    taskLogFilter: "skipped",
  });

  assert.deepEqual(state.taskLog.items.map((item) => item.id), ["task-skipped"]);
  assert.equal(state.taskLog.items[0]?.normalizedStatus, "skipped");
  assert.deepEqual(state.taskLog.statusSummary, { total: 1, done: 0, running: 0, failed: 0, skipped: 1 });
});

test("buildPipelineViewsState excludes workbench-owned project tasks from pipeline task log", () => {
  const state = buildPipelineViewsState({
    topics: [],
    projects: [],
    recentTasks: [
      {
        id: "project-outline",
        task_type: "outline_generation",
        status: "done",
        entity_slug: "project-1",
        entity_type: "project",
        created_at: "2026-05-19T10:00:00Z",
      },
      {
        id: "project-draft",
        task_type: "draft_generation",
        status: "failed",
        entity_slug: "project-2",
        entity_type: "project",
        created_at: "2026-05-19T09:00:00Z",
      },
      {
        id: "batch-task",
        task_type: "batch_create_projects",
        status: "done",
        entity_slug: "batch-1",
        entity_type: "batch",
        created_at: "2026-05-19T08:00:00Z",
      },
    ],
  });

  assert.deepEqual(state.taskLog.items.map((item) => item.id), ["batch-task"]);
  assert.deepEqual(state.taskLog.statusSummary, { total: 1, done: 1, running: 0, failed: 0, skipped: 0 });
});

test("buildBatchRunCards derives four pipeline batch actions with source-aware counts", () => {
  const cards = buildBatchRunCards({
    trends: [
      { slug: "trend-a", title: "热点A", source: "Weibo", heat_score: 88, status: "screening" },
      { slug: "trend-b", title: "热点B", source: "Weibo", heat_score: 76, status: "screening" },
    ],
    trackedArticles: [
      {
        slug: "article-a",
        source_name: "公众号A",
        title: "参考A",
        url: "https://example.com/a",
        author: "作者A",
        summary: "",
        structure_notes: "",
        tags: [],
      },
      {
        slug: "article-b",
        source_name: "公众号B",
        title: "参考B",
        url: "https://example.com/b",
        author: "作者B",
        summary: "",
        structure_notes: "",
        tags: [],
      },
    ],
    topics: [
      {
        slug: "topic-a",
        trend_slug: "trend-a",
        source_type: "trend",
        source_ref_slug: "trend-a",
        title: "选题A",
        angle: "角度A",
        status: "pending",
      },
    ],
    projects: [
      {
        slug: "project-a",
        topic_slug: "topic-ready",
        title: "项目A",
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
    cards.map((card) => ({ key: card.key, count: card.count })),
    [
      { key: "generate-trend-topics", count: 1 },
      { key: "generate-article-topics", count: 2 },
      { key: "create-projects", count: 1 },
      { key: "continue-projects", count: 1 },
    ],
  );
  assert.equal(cards[0]?.buttonLabel, "批量转选题");
  assert.equal(cards[2]?.buttonLabel, "批量建项目");
});
