import assert from "node:assert/strict";

import {
  buildPendingTrackedArticles,
  buildTrendSummaryPreview,
  filterTrackedArticlesByQuery,
  filterTrendsByQuery,
  formatTopicSourceLabel,
  shouldCollapseTrendSummary,
} from "./contentSources.ts";

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

test("formatTopicSourceLabel renders manual source with readable prefix", () => {
  assert.equal(
    formatTopicSourceLabel({ source_type: "manual", source_ref_slug: "late-night-emotion-repair" }),
    "原创选题 / 手动录入",
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

test("filterTrendsByQuery also matches trend summary content", () => {
  const filtered = filterTrendsByQuery(
    [
      {
        slug: "emotion-reset",
        title: "情绪复位模板",
        source: "Weibo",
        heat_score: 92,
        status: "screening",
        summary: "很多时候不是拖延，而是情绪电量先掉到了谷底。",
      },
      {
        slug: "career-pivot",
        title: "转岗情绪管理",
        source: "Zhihu",
        heat_score: 77,
        status: "archived",
        summary: "更关注转岗阶段的自我定位。",
      },
    ],
    "拖延",
  );

  assert.deepEqual(filtered.map((item) => item.slug), ["emotion-reset"]);
});

test("shouldCollapseTrendSummary only returns true for long summaries", () => {
  assert.equal(shouldCollapseTrendSummary("简短摘要"), false);
  assert.equal(shouldCollapseTrendSummary("很长".repeat(120)), true);
});

test("buildTrendSummaryPreview trims long summary for collapsed display", () => {
  const summary = "这是一个很长的热点摘要。".repeat(30);
  const preview = buildTrendSummaryPreview(summary, 60);

  assert.equal(preview.length <= 61, true);
  assert.equal(preview.endsWith("…"), true);
});

test("filterTrackedArticlesByQuery matches title, author, and tags", () => {
  const filtered = filterTrackedArticlesByQuery(
    [
      {
        slug: "repair-rhythm",
        source_kind: "manual",
        source_name: "公众号A",
        title: "修复关系的节奏",
        url: "https://example.com/a",
        author: "林夏",
        summary: "围绕关系修复展开。",
        body_markdown: "第一段",
        body_source: "manual",
        structure_notes: "三段递进",
        created_at: "2026-05-27T12:00:00+08:00",
        tags: ["关系", "修复"],
      },
      {
        slug: "work-anxiety",
        source_kind: "wechat_mp_import",
        source_name: "公众号B",
        title: "工作的焦虑感",
        url: "https://example.com/b",
        author: "周舟",
        summary: "处理职场焦虑。",
        body_markdown: "第二段",
        body_source: "dom",
        structure_notes: "总分总",
        created_at: "2026-05-27T12:30:00+08:00",
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
        source_kind: "manual",
        source_name: "公众号A",
        title: "排队中的参考文章",
        url: "https://example.com/a",
        author: "作者A",
        summary: "",
        body_markdown: "",
        body_source: "missing",
        structure_notes: "",
        created_at: "2026-05-27T12:00:00+08:00",
        tags: [],
      },
      {
        slug: "converted-article",
        source_kind: "wechat_mp_import",
        source_name: "公众号B",
        title: "已经转成选题",
        url: "https://example.com/b",
        author: "作者B",
        summary: "",
        body_markdown: "",
        body_source: "digest_fallback",
        structure_notes: "",
        created_at: "2026-05-27T12:30:00+08:00",
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
