import assert from "node:assert/strict";

import { buildDashboardRecentTaskViews } from "./dashboardRecentTasks.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildDashboardRecentTaskViews shapes project, topic, trend, tracked-article, and batch destinations without workbench deep links", () => {
  const recentTasks = buildDashboardRecentTaskViews([
    {
      id: 1,
      task_type: "draft_generation",
      status: "completed",
      entity_slug: "project-a",
      entity_type: "project",
      created_at: "2026-05-19T11:00:00Z",
    },
    {
      id: 2,
      task_type: "tracked_article_created",
      status: "done",
      entity_slug: "article-a",
      entity_type: "tracked_article",
      created_at: "2026-05-19T12:00:00Z",
    },
    {
      id: 3,
      task_type: "trend_updated",
      status: "failed",
      entity_slug: "trend-a",
      entity_type: "trend",
      created_at: "2026-05-19T13:00:00Z",
    },
    {
      id: 4,
      task_type: "topic_generation",
      status: "queued",
      entity_slug: "topic-a",
      entity_type: "topic",
      created_at: "2026-05-19T14:00:00Z",
    },
  ]);

  assert.deepEqual(
    recentTasks.map((task) => ({
      label: task.label,
      statusLabel: task.statusLabel,
      targetPath: task.targetPath,
      targetLabel: task.targetLabel,
      targetHint: task.targetHint,
    })),
    [
      {
        label: "AI 生成选题",
        statusLabel: "排队中",
        targetPath: "/pipeline/topics?topic=topic-a",
        targetLabel: "查看 Topic Queue",
        targetHint: "topic-a",
      },
      {
        label: "更新热点",
        statusLabel: "失败",
        targetPath: "/sources/trends?trend=trend-a",
        targetLabel: "回到 Sources",
        targetHint: "trend-a",
      },
      {
        label: "录入参考文章",
        statusLabel: "已完成",
        targetPath: "/sources/articles",
        targetLabel: "查看参考文章",
        targetHint: "article-a",
      },
      {
        label: "生成初稿",
        statusLabel: "已完成",
        targetPath: "/projects",
        targetLabel: "查看项目列表",
        targetHint: "project-a",
      },
    ],
  );
});

test("buildDashboardRecentTaskViews caps the list, preserves newest-first order, and handles unknown values", () => {
  const recentTasks = buildDashboardRecentTaskViews([
    { id: 1, task_type: "custom_a", status: "skipped", entity_type: "batch", created_at: "2026-05-19T09:00:00Z" },
    { id: 2, task_type: "custom_b", status: "done", entity_type: "batch", created_at: "2026-05-19T10:00:00Z" },
    { id: 3, task_type: "custom_c", status: "running", entity_type: "batch", created_at: "2026-05-19T11:00:00Z" },
    { id: 4, task_type: "custom_d", status: "error", entity_type: "batch", created_at: "2026-05-19T12:00:00Z" },
    { id: 5, status: "done", entity_type: "batch", created_at: "invalid" },
  ]);

  assert.equal(recentTasks.length, 4);
  assert.deepEqual(recentTasks.map((task) => task.id), ["4", "3", "2", "1"]);
  assert.equal(recentTasks[0]?.label, "custom_d");
  assert.equal(recentTasks[0]?.statusLabel, "失败");
  assert.equal(recentTasks[3]?.statusLabel, "已跳过");
});

test("buildDashboardRecentTaskViews treats invalid timestamps as oldest before capping", () => {
  const recentTasks = buildDashboardRecentTaskViews([
    { id: "invalid", task_type: "custom_invalid", status: "done", entity_type: "batch", created_at: "not-a-date" },
    { id: "old", task_type: "custom_old", status: "done", entity_type: "batch", created_at: "2026-05-19T09:00:00Z" },
    { id: "middle", task_type: "custom_middle", status: "done", entity_type: "batch", created_at: "2026-05-19T10:00:00Z" },
    { id: "new", task_type: "custom_new", status: "done", entity_type: "batch", created_at: "2026-05-19T11:00:00Z" },
    { id: "newest", task_type: "custom_newest", status: "done", entity_type: "batch", created_at: "2026-05-19T12:00:00Z" },
  ]);

  assert.deepEqual(
    recentTasks.map((task) => task.id),
    ["newest", "new", "middle", "old"],
  );
});
