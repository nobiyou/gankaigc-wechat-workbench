import assert from "node:assert/strict";

import { formatProjectChainStateLabel, formatProjectNextStepLabel } from "./projectStatus.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("formatProjectChainStateLabel maps known backend chain states into readable Chinese labels", () => {
  assert.equal(formatProjectChainStateLabel("outline_ready"), "待生成初稿");
  assert.equal(formatProjectChainStateLabel("draft_ready"), "待生成素材");
  assert.equal(formatProjectChainStateLabel("assets_quality_blocked"), "素材需重生成");
  assert.equal(formatProjectChainStateLabel("cover_pending"), "封面待补齐");
  assert.equal(formatProjectChainStateLabel("assets_ready"), "待生成发布包");
  assert.equal(formatProjectChainStateLabel("publish_ready"), "待审核发布包");
  assert.equal(formatProjectChainStateLabel("published"), "已发布");
  assert.equal(formatProjectChainStateLabel("revision_requested"), "审核打回");
});

test("formatProjectChainStateLabel falls back for unknown or missing values", () => {
  assert.equal(formatProjectChainStateLabel("custom_state"), "custom_state");
  assert.equal(formatProjectChainStateLabel(null), "未知链路状态");
});

test("formatProjectNextStepLabel reuses task labels for known next steps", () => {
  assert.equal(formatProjectNextStepLabel("generate_outline"), "生成大纲");
  assert.equal(formatProjectNextStepLabel("generate_draft"), "生成初稿");
  assert.equal(formatProjectNextStepLabel("generate_assets"), "生成素材包");
  assert.equal(formatProjectNextStepLabel("regenerate_cover_image"), "重试图片 API");
  assert.equal(formatProjectNextStepLabel("build_publish_package"), "生成发布包");
});

test("formatProjectNextStepLabel handles missing and unknown steps", () => {
  assert.equal(formatProjectNextStepLabel(null), "已无待推进步骤");
  assert.equal(formatProjectNextStepLabel("custom_step"), "custom_step");
});
