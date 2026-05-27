import assert from "node:assert/strict";

import { buildPromptTemplateSummaryLines } from "./promptTemplates.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildPromptTemplateSummaryLines exposes stage role outputs and capability badges", () => {
  assert.deepEqual(
    buildPromptTemplateSummaryLines({
      key: "draft",
      label: "初稿生成",
      role: "正文作者",
      objective: "基于大纲扩写正文，并支持原创增强精修。",
      output_fields: ["title", "body_markdown"],
      supports_tone_profile: true,
      supports_domain_pack: true,
      supports_review_feedback: true,
    }),
    [
      "职责：正文作者",
      "目标：基于大纲扩写正文，并支持原创增强精修。 默认按公众号正文自然表达与原创增强约束执行。",
      "输出：title / body_markdown",
      "输入：赛道 / 风格 / 审核意见",
    ],
  );
});

test("buildPromptTemplateSummaryLines adds public-account draft note for draft template", () => {
  assert.deepEqual(
    buildPromptTemplateSummaryLines({
      key: "draft",
      label: "初稿生成",
      role: "正文作者",
      objective: "基于大纲扩写正文，并支持原创增强精修。",
      output_fields: ["title", "body_markdown"],
      supports_tone_profile: true,
      supports_domain_pack: true,
      supports_review_feedback: true,
    })[1],
    "目标：基于大纲扩写正文，并支持原创增强精修。 默认按公众号正文自然表达与原创增强约束执行。",
  );
});
