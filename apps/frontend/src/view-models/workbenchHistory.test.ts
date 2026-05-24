import assert from "node:assert/strict";

import { buildWorkbenchHistoryEntries, buildWorkbenchHistoryGroups } from "./workbenchHistory.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildWorkbenchHistoryEntries maps stage-specific version history into contextual entries", () => {
  const draftEntries = buildWorkbenchHistoryEntries({
    stage: "draft",
    currentVersionNumber: 2,
    versions: {
      project_slug: "demo-project",
      outlines: [],
      drafts: [
        {
          project_slug: "demo-project",
          outline_version: 1,
          version: 2,
          title: "第二版初稿",
          body_markdown: "# v2",
          word_count: 1680,
          tone_profile_id: null,
          tone_profile_name: null,
        },
        {
          project_slug: "demo-project",
          outline_version: 1,
          version: 1,
          title: "第一版初稿",
          body_markdown: "# v1",
          word_count: 1520,
          tone_profile_id: null,
          tone_profile_name: null,
        },
      ],
      assets: [],
      publish_packages: [],
    },
  });

  assert.deepEqual(
    draftEntries.map((entry) => ({
      version: entry.versionNumber,
      summary: entry.summary,
      fullSummary: entry.fullSummary,
      truncated: entry.truncated,
      restorable: entry.restorable,
    })),
    [
      { version: 2, summary: "第二版初稿 · 1680 字", fullSummary: "第二版初稿 · 1680 字", truncated: false, restorable: false },
      { version: 1, summary: "第一版初稿 · 1520 字", fullSummary: "第一版初稿 · 1520 字", truncated: false, restorable: true },
    ],
  );
  assert.deepEqual(draftEntries.map((entry) => entry.reviewState), [null, null]);
});

test("buildWorkbenchHistoryEntries attaches readable meta lines for timestamps and origins", () => {
  const entries = buildWorkbenchHistoryEntries({
    stage: "draft",
    currentVersionNumber: 2,
    versions: {
      project_slug: "demo-project",
      outlines: [],
      drafts: [
        {
          project_slug: "demo-project",
          outline_version: 1,
          version: 2,
          title: "第二版初稿",
          body_markdown: "# v2",
          word_count: 1680,
          tone_profile_id: null,
          tone_profile_name: "女性成长克制陪伴风",
          created_at: "2026-05-24T08:30:00Z",
          origin: "polish",
        },
      ],
      assets: [],
      publish_packages: [],
    },
  });

  assert.deepEqual(entries[0]?.meta, [
    "时间：5/24 16:30",
    "来源：精修生成",
    "风格：女性成长克制陪伴风",
  ]);
});

test("buildWorkbenchHistoryEntries returns empty history for stages without persisted versions", () => {
  const entries = buildWorkbenchHistoryEntries({
    stage: "topic",
    currentVersionNumber: null,
    versions: {
      project_slug: "demo-project",
      outlines: [],
      drafts: [],
      assets: [],
      publish_packages: [],
    },
  });

  assert.deepEqual(entries, []);
});

test("buildWorkbenchHistoryEntries renders readable publish review states", () => {
  const entries = buildWorkbenchHistoryEntries({
    stage: "publish",
    currentVersionNumber: 4,
    versions: {
      project_slug: "demo-project",
      outlines: [],
      drafts: [],
      assets: [],
      publish_packages: [
        {
          project_slug: "demo-project",
          draft_version: 3,
          assets_version: 3,
          version: 4,
          abstract: "当前待审核发布包",
          tags: ["tag-a"],
          publish_checklist: ["check-a"],
          editor_note: "note-a",
          markdown_path: "a.md",
          markdown_url: "/a.md",
          manifest_path: "a.json",
          manifest_url: "/a.json",
          status: "ready",
          review_comment: null,
          reviewed_by: null,
          reviewed_at: null,
          created_at: "2026-05-20T02:00:00Z",
          origin: "generate",
          tone_profile_id: null,
          tone_profile_name: null,
        },
        {
          project_slug: "demo-project",
          draft_version: 2,
          assets_version: 2,
          version: 3,
          abstract: "上一版已打回",
          tags: ["tag-b"],
          publish_checklist: ["check-b"],
          editor_note: "note-b",
          markdown_path: "b.md",
          markdown_url: "/b.md",
          manifest_path: "b.json",
          manifest_url: "/b.json",
          status: "needs_revision",
          review_comment: "需要加强开头",
          reviewed_by: "ops",
          reviewed_at: "2026-05-20T01:00:00Z",
          created_at: "2026-05-20T04:30:00Z",
          origin: "review_regeneration",
          tone_profile_id: null,
          tone_profile_name: null,
        },
        {
          project_slug: "demo-project",
          draft_version: 1,
          assets_version: 1,
          version: 2,
          abstract: "更早版本已通过",
          tags: ["tag-c"],
          publish_checklist: ["check-c"],
          editor_note: "note-c",
          markdown_path: "c.md",
          markdown_url: "/c.md",
          manifest_path: "c.json",
          manifest_url: "/c.json",
          status: "approved",
          review_comment: "可以发布",
          reviewed_by: "chief-editor",
          reviewed_at: "2026-05-19T01:00:00Z",
          created_at: "2026-05-19T01:10:00Z",
          origin: "generate",
          tone_profile_id: null,
          tone_profile_name: null,
        },
      ],
    },
  });

  assert.deepEqual(
    entries.map((entry) => entry.summary),
    ["待审核 · 当前待审核发布包", "已打回 · 上一版已打回", "已通过 · 更早版本已通过"],
  );
  assert.deepEqual(
    entries.map((entry) => entry.restorable),
    [false, true, true],
  );
  assert.deepEqual(entries[1]?.meta.includes("来源：按审核意见重生成"), true);
  assert.deepEqual(entries[1]?.meta.includes("审核意见：需要加强开头"), true);
  assert.deepEqual(entries[2]?.meta.includes("审核意见：可以发布"), true);
});

test("buildWorkbenchHistoryEntries truncates long publish summaries while preserving full text", () => {
  const longAbstract = "这是一段很长的发布包摘要，用来验证历史区会对超长文案做截断展示，但仍然保留完整内容以便前端展开查看。".repeat(3);
  const [entry] = buildWorkbenchHistoryEntries({
    stage: "publish",
    currentVersionNumber: 5,
    versions: {
      project_slug: "demo-project",
      outlines: [],
      drafts: [],
      assets: [],
      publish_packages: [
        {
          project_slug: "demo-project",
          draft_version: 4,
          assets_version: 4,
          version: 5,
          abstract: longAbstract,
          tags: ["tag-a"],
          publish_checklist: ["check-a"],
          editor_note: "note-a",
          markdown_path: "a.md",
          markdown_url: "/a.md",
          manifest_path: "a.json",
          manifest_url: "/a.json",
          status: "ready",
          review_comment: null,
          reviewed_by: null,
          reviewed_at: null,
          tone_profile_id: null,
          tone_profile_name: null,
        },
      ],
    },
  });

  assert.equal(entry.truncated, true);
  assert.equal(entry.fullSummary.startsWith("待审核 · 这是一段很长的发布包摘要"), true);
  assert.equal(entry.summary.endsWith("..."), true);
});

test("buildWorkbenchHistoryGroups groups publish history by review state while preserving order", () => {
  const entries = buildWorkbenchHistoryEntries({
    stage: "publish",
    currentVersionNumber: 7,
    versions: {
      project_slug: "demo-project",
      outlines: [],
      drafts: [],
      assets: [],
      publish_packages: [
        {
          project_slug: "demo-project",
          draft_version: 7,
          assets_version: 6,
          version: 8,
          abstract: "被打回版本",
          tags: [],
          publish_checklist: [],
          editor_note: "note-a",
          markdown_path: "a.md",
          markdown_url: "/a.md",
          manifest_path: "a.json",
          manifest_url: "/a.json",
          status: "needs_revision",
          review_comment: "comment-a",
          reviewed_by: "editor-a",
          reviewed_at: "2026-05-20T01:00:00Z",
          tone_profile_id: null,
          tone_profile_name: null,
        },
        {
          project_slug: "demo-project",
          draft_version: 6,
          assets_version: 5,
          version: 7,
          abstract: "当前待审核版本",
          tags: [],
          publish_checklist: [],
          editor_note: "note-b",
          markdown_path: "b.md",
          markdown_url: "/b.md",
          manifest_path: "b.json",
          manifest_url: "/b.json",
          status: "ready",
          review_comment: null,
          reviewed_by: null,
          reviewed_at: null,
          tone_profile_id: null,
          tone_profile_name: null,
        },
        {
          project_slug: "demo-project",
          draft_version: 5,
          assets_version: 4,
          version: 6,
          abstract: "更早待审核版本",
          tags: [],
          publish_checklist: [],
          editor_note: "note-c",
          markdown_path: "c.md",
          markdown_url: "/c.md",
          manifest_path: "c.json",
          manifest_url: "/c.json",
          status: "ready",
          review_comment: null,
          reviewed_by: null,
          reviewed_at: null,
          tone_profile_id: null,
          tone_profile_name: null,
        },
        {
          project_slug: "demo-project",
          draft_version: 4,
          assets_version: 3,
          version: 5,
          abstract: "已通过版本",
          tags: [],
          publish_checklist: [],
          editor_note: "note-d",
          markdown_path: "d.md",
          markdown_url: "/d.md",
          manifest_path: "d.json",
          manifest_url: "/d.json",
          status: "approved",
          review_comment: "comment-d",
          reviewed_by: "chief-editor",
          reviewed_at: "2026-05-19T01:00:00Z",
          tone_profile_id: null,
          tone_profile_name: null,
        },
      ],
    },
  });

  const groups = buildWorkbenchHistoryGroups({
    stage: "publish",
    entries,
  });

  assert.deepEqual(
    groups.map((group) => ({ key: group.key, versions: group.entries.map((entry) => entry.versionNumber) })),
    [
      { key: "ready", versions: [7, 6] },
      { key: "needs_revision", versions: [8] },
      { key: "approved", versions: [5] },
    ],
  );
});
