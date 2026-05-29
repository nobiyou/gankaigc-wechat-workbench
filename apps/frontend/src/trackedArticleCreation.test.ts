import assert from "node:assert/strict";

import {
  buildTrackedArticleCreatePayload,
  createTrackedArticleCreateDraft,
  syncTrackedArticleDraftTitle,
} from "./trackedArticleCreation.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("createTrackedArticleCreateDraft starts with empty editable fields and manual source fallback", () => {
  assert.deepEqual(createTrackedArticleCreateDraft(), {
    title: "",
    slug: "",
    url: "",
    source_name: "手动录入",
    author: "",
    summary: "",
    body_markdown: "",
    structure_notes: "",
    tags_text: "",
  });
});

test("syncTrackedArticleDraftTitle derives slug while preserving a custom slug", () => {
  assert.deepEqual(
    syncTrackedArticleDraftTitle(
      {
        title: "",
        slug: "",
        url: "",
        source_name: "手动录入",
        author: "",
        summary: "",
        body_markdown: "",
        structure_notes: "",
        tags_text: "",
      },
      "成年后真正养人的关系",
    ),
    {
      title: "成年后真正养人的关系",
      slug: "成年后真正养人的关系",
      url: "",
      source_name: "手动录入",
      author: "",
      summary: "",
      body_markdown: "",
      structure_notes: "",
      tags_text: "",
    },
  );

  assert.deepEqual(
    syncTrackedArticleDraftTitle(
      {
        title: "成年后真正养人的关系",
        slug: "my-custom-article",
        url: "",
        source_name: "手动录入",
        author: "",
        summary: "",
        body_markdown: "",
        structure_notes: "",
        tags_text: "",
      },
      "比心动更重要的是被接住",
    ),
    {
      title: "比心动更重要的是被接住",
      slug: "my-custom-article",
      url: "",
      source_name: "手动录入",
      author: "",
      summary: "",
      body_markdown: "",
      structure_notes: "",
      tags_text: "",
    },
  );
});

test("buildTrackedArticleCreatePayload trims fields, normalizes tags, and fills defaults", () => {
  assert.deepEqual(
    buildTrackedArticleCreatePayload({
      title: "  成年后真正养人的关系  ",
      slug: " ",
      url: " https://mp.weixin.qq.com/s/example ",
      source_name: " ",
      author: "  晚晴  ",
      summary: "  写成年关系里的安稳陪伴  ",
      body_markdown: "  第一段：先写下班回家。\n\n第二段：再写饭桌和夜路。  ",
      structure_notes: "  场景开头，饭桌过渡到夜路  ",
      tags_text: " 陪伴，关系修复, 女性成长 \n 安全感 ",
    }),
    {
      title: "成年后真正养人的关系",
      slug: "成年后真正养人的关系",
      url: "https://mp.weixin.qq.com/s/example",
      source_name: "手动录入",
      author: "晚晴",
      summary: "写成年关系里的安稳陪伴",
      body_markdown: "第一段：先写下班回家。\n\n第二段：再写饭桌和夜路。",
      structure_notes: "场景开头，饭桌过渡到夜路",
      tags: ["陪伴", "关系修复", "女性成长", "安全感"],
    },
  );
});

test("buildTrackedArticleCreatePayload rejects missing title and invalid url", () => {
  assert.throws(
    () =>
      buildTrackedArticleCreatePayload({
        title: "",
        slug: "",
        url: "https://mp.weixin.qq.com/s/example",
        source_name: "手动录入",
        author: "",
        summary: "",
        body_markdown: "",
        structure_notes: "",
        tags_text: "",
      }),
    /参考文章标题不能为空/u,
  );

  assert.throws(
    () =>
      buildTrackedArticleCreatePayload({
        title: "关系里的安稳感",
        slug: "",
        url: "not-a-valid-url",
        source_name: "手动录入",
        author: "",
        summary: "",
        body_markdown: "",
        structure_notes: "",
        tags_text: "",
      }),
    /参考文章链接必须是有效的 http\(s\) 地址/u,
  );
});
