import assert from "node:assert/strict";

import { buildBackgroundTaskSummaryLines } from "./backgroundTaskSummaries.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildBackgroundTaskSummaryLines returns request and result counts for batch task details", () => {
  const lines = buildBackgroundTaskSummaryLines({
    task_id: "task-1",
    job_type: "batch_generate_topics",
    status: "done",
    created_at: "2026-05-19T10:00:00Z",
    started_at: "2026-05-19T10:00:01Z",
    finished_at: "2026-05-19T10:00:10Z",
    error: null,
    result: {
      requested_count: 5,
      processed_count: 3,
      skipped_count: 1,
      failed_count: 1,
    },
  });

  assert.deepEqual(lines, ["请求 5 项", "完成 3 项", "跳过 1 项", "失败 1 项"]);
});

test("buildBackgroundTaskSummaryLines ignores incomplete or missing background task results", () => {
  assert.deepEqual(
    buildBackgroundTaskSummaryLines({
      task_id: "task-2",
      job_type: "batch_generate_topics",
      status: "failed",
      created_at: "2026-05-19T10:00:00Z",
      started_at: "2026-05-19T10:00:01Z",
      finished_at: "2026-05-19T10:00:10Z",
      error: "boom",
      result: {
        requested_count: 2,
      },
    }),
    [],
  );
  assert.deepEqual(buildBackgroundTaskSummaryLines(null), []);
});
