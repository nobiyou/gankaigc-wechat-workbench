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
  assert.equal(getTaskTypeLabel("draft_polished"), "原创增强精修");
});

test("getTaskTypeLabel covers polish and generate assets task", () => {
  assert.equal(getTaskTypeLabel("polish_and_generate_assets"), "原创增强后生成素材包");
});

test("getTaskTypeLabel covers polish and build publish package task", () => {
  assert.equal(getTaskTypeLabel("polish_and_build_publish_package"), "原创增强后生成发布包");
});

test("getTaskTypeLabel covers cover-only asset refresh events", () => {
  assert.equal(getTaskTypeLabel("cover_image_regenerated"), "重生成封面图");
  assert.equal(getTaskTypeLabel("regenerate_cover_image"), "重生成封面图");
});
