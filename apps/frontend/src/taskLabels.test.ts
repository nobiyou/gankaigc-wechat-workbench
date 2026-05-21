import assert from "node:assert/strict";

import { getTaskTypeLabel } from "./taskLabels.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("getTaskTypeLabel renders retro task in Chinese", () => {
  assert.equal(getTaskTypeLabel("project_retro_recorded"), "记录项目复盘");
});

test("getTaskTypeLabel falls back to original task type when unknown", () => {
  assert.equal(getTaskTypeLabel("custom_task"), "custom_task");
});

test("getTaskTypeLabel reuses dashboard-related batch and publish labels", () => {
  assert.equal(getTaskTypeLabel("batch_generate_topics"), "批量生成选题");
  assert.equal(getTaskTypeLabel("build_publish_package"), "生成发布包");
});

test("getTaskTypeLabel covers draft polished events recorded by backend", () => {
  assert.equal(getTaskTypeLabel("draft_polished"), "精修初稿");
});
