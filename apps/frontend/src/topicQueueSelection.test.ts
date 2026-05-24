import assert from "node:assert/strict";

import {
  buildTopicSelectionSummary,
  collectBatchDroppableTopicSlugs,
  collectBatchProjectCreatableTopicSlugs,
  toggleTopicSelection,
} from "./topicQueueSelection.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("toggleTopicSelection adds and removes slugs idempotently", () => {
  assert.deepEqual(toggleTopicSelection([], "topic-a"), ["topic-a"]);
  assert.deepEqual(toggleTopicSelection(["topic-a"], "topic-a"), []);
  assert.deepEqual(toggleTopicSelection(["topic-a"], "topic-b"), ["topic-a", "topic-b"]);
});

test("buildTopicSelectionSummary counts selected topics and action eligibility", () => {
  const summary = buildTopicSelectionSummary({
    selectedTopicSlugs: ["topic-a", "topic-b", "topic-c"],
    topicQueueItems: [
      {
        topic: {
          slug: "topic-a",
          trend_slug: "trend-a",
          source_type: "trend",
          source_ref_slug: "trend-a",
          title: "热点选题",
          angle: "趋势切入",
          status: "pending",
        },
        sourceLabel: "热点 / trend-a",
        targetPath: "/pipeline/topics?topic=topic-a",
      },
      {
        topic: {
          slug: "topic-b",
          trend_slug: null,
          source_type: "tracked_article",
          source_ref_slug: "article-b",
          title: "参考选题",
          angle: "拆解切入",
          status: "drafting",
        },
        sourceLabel: "参考文章 / article-b",
        targetPath: "/pipeline/topics?topic=topic-b",
      },
      {
        topic: {
          slug: "topic-c",
          trend_slug: null,
          source_type: "manual",
          source_ref_slug: "manual-c",
          title: "原创选题",
          angle: "原创切入",
          status: "dropped",
        },
        sourceLabel: "原创选题 / 手动录入",
        targetPath: "/pipeline/topics?topic=topic-c",
      },
    ],
  });

  assert.deepEqual(summary, {
    selectedCount: 3,
    projectCreatableCount: 1,
    droppableCount: 2,
  });
});

test("collect helpers only return eligible slugs in visible queue order", () => {
  const topicQueueItems = [
    {
      topic: {
        slug: "topic-b",
        trend_slug: null,
        source_type: "tracked_article",
        source_ref_slug: "article-b",
        title: "参考选题",
        angle: "拆解切入",
        status: "drafting",
      },
      sourceLabel: "参考文章 / article-b",
      targetPath: "/pipeline/topics?topic=topic-b",
    },
    {
      topic: {
        slug: "topic-a",
        trend_slug: "trend-a",
        source_type: "trend",
        source_ref_slug: "trend-a",
        title: "热点选题",
        angle: "趋势切入",
        status: "pending",
      },
      sourceLabel: "热点 / trend-a",
      targetPath: "/pipeline/topics?topic=topic-a",
    },
    {
      topic: {
        slug: "topic-c",
        trend_slug: null,
        source_type: "manual",
        source_ref_slug: "manual-c",
        title: "原创选题",
        angle: "原创切入",
        status: "approved",
      },
      sourceLabel: "原创选题 / 手动录入",
      targetPath: "/pipeline/topics?topic=topic-c",
    },
  ];

  assert.deepEqual(collectBatchProjectCreatableTopicSlugs(topicQueueItems, ["topic-c", "topic-a", "topic-b"]), ["topic-a"]);
  assert.deepEqual(collectBatchDroppableTopicSlugs(topicQueueItems, ["topic-c", "topic-a", "topic-b"]), ["topic-b", "topic-a"]);
});
