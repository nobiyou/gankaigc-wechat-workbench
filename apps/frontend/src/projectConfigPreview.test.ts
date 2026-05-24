import assert from "node:assert/strict";

import { buildProjectConfigPreviewLines } from "./projectConfigPreview.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildProjectConfigPreviewLines combines selected domain pack and tone profile", () => {
  const lines = buildProjectConfigPreviewLines({
    domainPacks: [
      {
        key: "women-growth",
        label: "女性情感成长",
        audience: "女性情感成长",
        voice: "语言要克制、真实、具体",
        constraints: "避免空泛口号、说教感和鸡汤腔",
        is_default: true,
      },
    ],
    domainPackKey: "women-growth",
    toneProfiles: [
      {
        id: 2,
        is_active: true,
        sort_order: 1,
        name: "项目专属纪实风",
        opening_style: "从一次具体互动切入",
        paragraph_rhythm: "中短段交错",
        closing_style: "低压行动句收束",
        forbidden_phrases: ["马上"],
        value_constraints: "不夸张，不说教",
        target_word_count: 1600,
      },
    ],
    toneProfileId: 2,
  });

  assert.equal(lines[0], "后续大纲、初稿、素材和发布包将按「女性情感成长」赛道语境生成。");
  assert.equal(lines[1], "赛道语气：语言要克制、真实、具体");
  assert.equal(lines[2], "风格约束：项目专属纪实风 · 开头 从一次具体互动切入 · 结尾 低压行动句收束");
});

test("buildProjectConfigPreviewLines falls back to default domain pack and active tone profile", () => {
  const lines = buildProjectConfigPreviewLines({
    domainPacks: [
      {
        key: "women-growth",
        label: "女性情感成长",
        audience: "女性情感成长",
        voice: "语言要克制、真实、具体",
        constraints: "避免空泛口号、说教感和鸡汤腔",
        is_default: true,
      },
    ],
    domainPackKey: null,
    toneProfiles: [
      {
        id: 1,
        is_active: true,
        sort_order: 1,
        name: "全局默认风格",
        opening_style: "场景切入",
        paragraph_rhythm: "短段落推进",
        closing_style: "留白收束",
        forbidden_phrases: [],
        value_constraints: "不说教",
        target_word_count: 1400,
      },
    ],
    toneProfileId: null,
  });

  assert.equal(lines[0], "后续大纲、初稿、素材和发布包将按「女性情感成长」赛道语境生成。");
  assert.equal(lines[2], "风格约束：全局默认风格 · 开头 场景切入 · 结尾 留白收束");
});
