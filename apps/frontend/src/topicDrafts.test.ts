import assert from "node:assert/strict";

import { buildTopicDraft, formatTopicStatusLabel, hasTopicDraftChanged } from "./topicDrafts.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildTopicDraft maps topic fields into editable draft state", () => {
  assert.deepEqual(
    buildTopicDraft({
      title: "关系边界重设",
      angle: "从女性的边界表达切入",
      status: "pending",
    }),
    {
      title: "关系边界重设",
      angle: "从女性的边界表达切入",
      status: "pending",
    },
  );
});

test("hasTopicDraftChanged detects title angle and status changes", () => {
  const topic = {
    title: "关系边界重设",
    angle: "从女性的边界表达切入",
    status: "pending",
  };

  assert.equal(hasTopicDraftChanged(topic, buildTopicDraft(topic)), false);
  assert.equal(
    hasTopicDraftChanged(topic, {
      title: "关系边界重设2",
      angle: "从女性的边界表达切入",
      status: "pending",
    }),
    true,
  );
  assert.equal(
    hasTopicDraftChanged(topic, {
      title: "关系边界重设",
      angle: "新的角度",
      status: "pending",
    }),
    true,
  );
  assert.equal(
    hasTopicDraftChanged(topic, {
      title: "关系边界重设",
      angle: "从女性的边界表达切入",
      status: "dropped",
    }),
    true,
  );
});

test("formatTopicStatusLabel returns readable chinese labels and falls back for unknown values", () => {
  assert.equal(formatTopicStatusLabel("pending"), "待建项目");
  assert.equal(formatTopicStatusLabel("drafting"), "写作中");
  assert.equal(formatTopicStatusLabel("approved"), "已确认");
  assert.equal(formatTopicStatusLabel("dropped"), "已废弃");
  assert.equal(formatTopicStatusLabel("custom"), "custom");
});
