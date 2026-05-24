import assert from "node:assert/strict";

import {
  buildTopicCreatePayload,
  createTopicCreateDraft,
  syncTopicDraftTitle,
} from "./topicCreation.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("createTopicCreateDraft starts with empty title angle and slug", () => {
  assert.deepEqual(createTopicCreateDraft(), {
    title: "",
    slug: "",
    angle: "",
  });
});

test("syncTopicDraftTitle derives slug while preserving a manually edited slug", () => {
  assert.deepEqual(
    syncTopicDraftTitle(
      {
        title: "",
        slug: "",
        angle: "",
      },
      "深夜情绪修复",
    ),
    {
      title: "深夜情绪修复",
      slug: "深夜情绪修复",
      angle: "",
    },
  );

  assert.deepEqual(
    syncTopicDraftTitle(
      {
        title: "深夜情绪修复",
        slug: "my-custom-topic",
        angle: "",
      },
      "新的原创角度",
    ),
    {
      title: "新的原创角度",
      slug: "my-custom-topic",
      angle: "",
    },
  );
});

test("buildTopicCreatePayload trims fields and rejects missing values", () => {
  assert.deepEqual(
    buildTopicCreatePayload({
      title: "  深夜情绪修复  ",
      slug: " midnight-emotion-repair ",
      angle: "  原创灵感  ",
    }),
    {
      title: "深夜情绪修复",
      slug: "midnight-emotion-repair",
      angle: "原创灵感",
    },
  );

  assert.throws(
    () =>
      buildTopicCreatePayload({
        title: "",
        slug: "midnight-emotion-repair",
        angle: "原创灵感",
      }),
    /选题标题不能为空/u,
  );
});
