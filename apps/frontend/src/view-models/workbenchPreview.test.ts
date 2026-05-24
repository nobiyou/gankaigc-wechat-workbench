import assert from "node:assert/strict";

import { buildWorkbenchPreview } from "./workbenchPreview.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

const baseDetail = {
  project: {
    slug: "project-a",
    topic_slug: "topic-a",
    title: "为什么有些女性在关系里总想反复确认",
    stage: "draft_ready",
    owner: "editor",
    preferred_tone_profile_id: null,
    preferred_tone_profile_name: null,
    chain_status: "ready" as const,
    current_chain_state: "draft_ready",
    next_required_step: "generate_assets",
    current_outline_version: 1,
    current_draft_version: 1,
    current_assets_version: 1,
    current_publish_package_version: 1,
    retro: null,
  },
  outline: {
    project_slug: "project-a",
    version: 1,
    hook: "先写那个总在等回复、等表情、等一句确定的人。",
    outline_body: "1. 为什么越在乎，越容易反复确认\n2. 真正让人不安的并不是一句话\n3. 关系里的稳定感来自可持续回应",
    tone_profile_id: null,
    tone_profile_name: null,
  },
  draft: {
    project_slug: "project-a",
    outline_version: 1,
    version: 1,
    title: "越在乎的人，为什么越想在关系里反复确认",
    body_markdown: "# 标题\n\n第一段\n\n第二段",
    word_count: 1260,
    tone_profile_id: null,
    tone_profile_name: null,
  },
  assets: {
    project_slug: "project-a",
    draft_version: 1,
    version: 1,
    title_options: ["越在乎的人，为什么越想在关系里反复确认", "她不是作，她只是没有被真正接住"],
    cover_prompt: "close-up portrait, soft light, emotional realism",
    cover_copy: "越在乎，越想确认",
    social_teaser: "真正让人反复确认的，往往不是一句话，而是关系里长期没有被看见。",
    cover_image_path: "cover.png",
    cover_image_url: "/generated-assets/cover.png",
    tone_profile_id: null,
    tone_profile_name: null,
  },
  publish_package: {
    project_slug: "project-a",
    draft_version: 1,
    assets_version: 1,
    version: 1,
    abstract: "写给总在关系里反复确认、又不知道为什么停不下来的人。",
    tags: ["关系", "确认", "女性成长"],
    publish_checklist: ["检查标题", "检查首图", "检查结尾 CTA"],
    editor_note: "发布前确认封面图与标题 1 保持一致。",
    markdown_path: "publish.md",
    markdown_url: "/generated-assets/publish.md",
    manifest_path: "publish.json",
    manifest_url: "/generated-assets/publish.json",
    status: "ready",
    review_comment: null,
    reviewed_by: null,
    reviewed_at: null,
    tone_profile_id: null,
    tone_profile_name: null,
  },
  retro: null,
};

test("buildWorkbenchPreview returns draft preview with正文内容", () => {
  const preview = buildWorkbenchPreview("draft", baseDetail);

  assert.equal(preview?.eyebrow, "Draft Preview");
  assert.equal(preview?.title, "越在乎的人，为什么越想在关系里反复确认");
  assert.equal(preview?.blocks[0]?.label, "正文预览");
  assert.equal(preview?.blocks[0]?.kind, "markdown");
  assert.equal(preview?.blocks[0]?.content.includes("第一段"), true);
});

test("buildWorkbenchPreview returns outline preview with hook and outline body", () => {
  const preview = buildWorkbenchPreview("outline", baseDetail);

  assert.equal(preview?.eyebrow, "Outline Preview");
  assert.equal(preview?.summary, "结构预览 · v1");
  assert.equal(preview?.blocks.length, 2);
  assert.equal(preview?.blocks[0]?.label, "开篇钩子");
  assert.equal(preview?.blocks[1]?.label, "大纲内容");
  assert.equal(preview?.blocks[1]?.content.includes("1. 为什么越在乎，越容易反复确认"), true);
  assert.equal(preview?.blocks[1]?.content.includes("3. 关系里的稳定感来自可持续回应"), true);
});

test("buildWorkbenchPreview returns assets preview with title and teaser blocks", () => {
  const preview = buildWorkbenchPreview("assets", baseDetail);

  assert.equal(preview?.eyebrow, "Assets Preview");
  assert.equal(preview?.blocks.length, 5);
  assert.equal(preview?.blocks[0]?.label, "封面图");
  assert.equal(preview?.blocks[0]?.content, "/generated-assets/cover.png");
  assert.equal(preview?.blocks[1]?.kind, "markdown");
  assert.equal(preview?.blocks[1]?.content.includes("1. 越在乎的人，为什么越想在关系里反复确认"), true);
  assert.equal(preview?.blocks[3]?.content, "真正让人反复确认的，往往不是一句话，而是关系里长期没有被看见。");
});

test("buildWorkbenchPreview marks missing assets cover image clearly", () => {
  const preview = buildWorkbenchPreview("assets", {
    ...baseDetail,
    assets: {
      ...baseDetail.assets,
      cover_image_path: "",
      cover_image_url: "",
    },
  });

  assert.equal(preview?.blocks[0]?.label, "封面图");
  assert.equal(preview?.blocks[0]?.content, "未生成（图片服务暂时不可用）");
});

test("buildWorkbenchPreview returns publish preview with article, abstract, tags and checklist", () => {
  const preview = buildWorkbenchPreview("publish", baseDetail);

  assert.equal(preview?.eyebrow, "Publish Preview");
  assert.equal(preview?.blocks.length, 5);
  assert.equal(preview?.blocks[0]?.kind, "markdown");
  assert.equal(preview?.blocks[0]?.content.includes("# 标题"), true);
  assert.equal(preview?.blocks[1]?.content, "写给总在关系里反复确认、又不知道为什么停不下来的人。");
  assert.equal(preview?.blocks[2]?.content, "关系 / 确认 / 女性成长");
  assert.equal(preview?.blocks[3]?.kind, "markdown");
  assert.equal(preview?.blocks[3]?.content.includes("1. 检查标题"), true);
});

test("buildWorkbenchPreview returns null when current stage has no previewable content", () => {
  assert.equal(
    buildWorkbenchPreview("draft", {
      ...baseDetail,
      draft: null,
    }),
    null,
  );
  assert.equal(
    buildWorkbenchPreview("outline", {
      ...baseDetail,
      outline: null,
    }),
    null,
  );
  assert.equal(buildWorkbenchPreview("topic", baseDetail), null);
});
