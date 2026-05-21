import assert from "node:assert/strict";

import { buildPendingTrackedArticles, filterTrackedArticlesByQuery, filterTrendsByQuery, formatTopicSourceLabel } from "./contentSources.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("formatTopicSourceLabel renders trend source with readable prefix", () => {
  assert.equal(
    formatTopicSourceLabel({ source_type: "trend", source_ref_slug: "office-burnout-recovery" }),
    "热点 / office-burnout-recovery",
  );
});

test("formatTopicSourceLabel renders tracked article source with readable prefix", () => {
  assert.equal(
    formatTopicSourceLabel({ source_type: "tracked_article", source_ref_slug: "slow-repair-template" }),
    "参考文章 / slow-repair-template",
  );
});

test("filterTrendsByQuery matches trend title and source case-insensitively", () => {
  const filtered = filterTrendsByQuery(
    [
      {
        slug: "emotion-reset",
        title: "情绪复位模板",
        source: "Weibo",
        heat_score: 92,
        status: "screening",
      },
      {
        slug: "career-pivot",
        title: "转岗情绪管理",
        source: "Zhihu",
        heat_score: 77,
        status: "archived",
      },
    ],
    "weibo",
  );

  assert.deepEqual(filtered.map((item) => item.slug), ["emotion-reset"]);
});

test("filterTrackedArticlesByQuery matches title, author, and tags", () => {
  const filtered = filterTrackedArticlesByQuery(
    [
      {
        slug: "repair-rhythm",
        source_name: "公众号A",
        title: "修复关系的节奏",
        url: "https://example.com/a",
        author: "林夏",
        summary: "围绕关系修复展开。",
        structure_notes: "三段递进",
        tags: ["关系", "修复"],
      },
      {
        slug: "work-anxiety",
        source_name: "公众号B",
        title: "工作的焦虑感",
        url: "https://example.com/b",
        author: "周舟",
        summary: "处理职场焦虑。",
        structure_notes: "总分总",
        tags: ["职场"],
      },
    ],
    "修复",
  );

  assert.deepEqual(filtered.map((item) => item.slug), ["repair-rhythm"]);
});

test("buildPendingTrackedArticles excludes articles that already became topics", () => {
  const pending = buildPendingTrackedArticles({
    trackedArticles: [
      {
        slug: "queued-article",
        source_name: "公众号A",
        title: "排队中的参考文章",
        url: "https://example.com/a",
        author: "作者A",
        summary: "",
        structure_notes: "",
        tags: [],
      },
      {
        slug: "converted-article",
        source_name: "公众号B",
        title: "已经转成选题",
        url: "https://example.com/b",
        author: "作者B",
        summary: "",
        structure_notes: "",
        tags: [],
      },
    ],
    topics: [
      {
        slug: "topic-from-article",
        trend_slug: null,
        source_type: "tracked_article",
        source_ref_slug: "converted-article",
        title: "已生成选题",
        angle: "角度",
        status: "pending",
      },
    ],
  });

  assert.deepEqual(pending.map((item) => item.slug), ["queued-article"]);
});
