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
  problem_brief: null,
  benchmarks: [],
  strategy_card: null,
};

test("buildWorkbenchPreview returns draft preview with正文内容", () => {
  const preview = buildWorkbenchPreview("draft", baseDetail);

  assert.equal(preview?.eyebrow, "Draft Preview");
  assert.equal(preview?.title, "越在乎的人，为什么越想在关系里反复确认");
  assert.equal(preview?.blocks[0]?.label, "正文预览");
  assert.equal(preview?.blocks[0]?.kind, "markdown");
  assert.equal(preview?.blocks[0]?.content.includes("第一段"), true);
  assert.equal(preview?.blocks[0]?.copyText, "# 标题\n\n第一段\n\n第二段");
});

test("buildWorkbenchPreview shows ai-flavor risk on first draft without previous version", () => {
  const preview = buildWorkbenchPreview("draft", {
    ...baseDetail,
    draft: {
      ...baseDetail.draft,
      title: "你赌我不敢走，我赌你再也遇不到真诚的人",
      body_markdown:
        "# 标题\n\n不是不爱，而是太久没有被看见。其实很多时候，关系崩塌不是从争吵开始，而是从一次赌气开始。\n\n你以为他懂，他以为你不在乎，所以两个人都在等对方先低头。最后，真正受伤的不是面子，而是那颗还想靠近的心。\n\n从今天开始，别再赌气，愿你有话直说，成为不靠试探也能被懂的人。",
      word_count: 188,
    },
  });

  assert.equal(preview?.blocks[1]?.label, "AI味风险提示");
  assert.equal(preview?.blocks[1]?.content.includes("AI味风险（启发式）：高"), true);
  assert.equal(preview?.blocks[1]?.content.includes("命中：不是A，是B"), true);
  assert.equal(preview?.blocks[1]?.content.includes("命中：结尾口号感"), true);
});

test("buildWorkbenchPreview adds previous draft comparison blocks when prior version exists", () => {
  const comparisonDetail = {
    ...baseDetail,
    draft: {
      ...baseDetail.draft,
      body_markdown: "# 标题\n\n新开头第一句\n\n共享中段句子\n\n新的补充论证\n\n新结尾最后一句",
    },
  };

  const preview = buildWorkbenchPreview("draft", comparisonDetail, {
    project_slug: "project-a",
    outlines: [],
    drafts: [
      comparisonDetail.draft,
      {
        ...comparisonDetail.draft,
        version: 0,
        title: "旧版标题",
        body_markdown: "# 旧版标题\n\n旧开头第一句\n\n共享中段句子\n\n旧结尾最后一句",
        word_count: 980,
      },
    ],
    assets: [],
    publish_packages: [],
  });

  assert.equal(preview?.blocks[1]?.label, "改写验收摘要");
  assert.equal(preview?.blocks[1]?.kind, "markdown");
  assert.equal(preview?.blocks[1]?.content.includes("改写原创度（启发式）：83 / 100"), true);
  assert.equal(preview?.blocks[1]?.content.includes("当前版本：v1"), true);
  assert.equal(preview?.blocks[1]?.content.includes("对照版本：v0"), true);
  assert.equal(preview?.blocks[1]?.content.includes("标题已变化：是"), true);
  assert.equal(preview?.blocks[1]?.content.includes("字数变化：+280"), true);
  assert.equal(preview?.blocks[1]?.content.includes("段落数变化：+1 段"), true);
  assert.equal(preview?.blocks[1]?.content.includes("段落重写占比：75%"), true);
  assert.equal(preview?.blocks[1]?.content.includes("开头已重写：是"), true);
  assert.equal(preview?.blocks[1]?.content.includes("中段已重写：是"), true);
  assert.equal(preview?.blocks[1]?.content.includes("结尾已重写：是"), true);
  assert.equal(preview?.blocks[1]?.content.includes("完全复用段落：1 段"), true);
  assert.equal(preview?.blocks[1]?.content.includes("不等同第三方查重"), true);
  assert.equal(preview?.blocks[2]?.label, "上一版对照");
  assert.equal(preview?.blocks[2]?.content.includes("当前标题：越在乎的人，为什么越想在关系里反复确认"), true);
  assert.equal(preview?.blocks[2]?.content.includes("上一版标题：旧版标题"), true);
  assert.equal(preview?.blocks[3]?.label, "AI味风险提示");
  assert.equal(preview?.blocks[3]?.content.includes("AI味风险（启发式）"), true);
  assert.equal(preview?.blocks[3]?.content.includes("短促判断段偏多"), true);
  assert.equal(preview?.blocks[4]?.label, "开头对照");
  assert.equal(preview?.blocks[4]?.content.includes("当前版"), true);
  assert.equal(preview?.blocks[4]?.content.includes("上一版"), true);
  assert.equal(preview?.blocks[5]?.label, "中段对照");
  assert.equal(preview?.blocks[5]?.content.includes("共享中段句子"), true);
  assert.equal(preview?.blocks[6]?.label, "结尾对照");
});

test("buildWorkbenchPreview adds high ai-flavor risk summary for templated draft patterns", () => {
  const preview = buildWorkbenchPreview("draft", {
    ...baseDetail,
    draft: {
      ...baseDetail.draft,
      title: "不是你太敏感，是你在关系里一直没被接住",
      body_markdown:
        "# 标题\n\n不是你太敏感，而是你一直太委屈。\n\n第一步，先看见问题。比如你明明已经很累了，却还是想解释清楚。\n\n第二步，再理解原因。其实很多时候，你不是状态不好，而是太久没有被回应。\n\n第三步，最后学会调整。所以你要慢慢把注意力放回自己身上。最后，你要记得把注意力放回自己身上。",
      word_count: 168,
    },
  }, {
    project_slug: "project-a",
    outlines: [],
    drafts: [
      {
        ...baseDetail.draft,
        title: "不是你太敏感，是你在关系里一直没被接住",
        body_markdown:
          "# 标题\n\n不是你太敏感，而是你一直太委屈。\n\n第一步，先看见问题。比如你明明已经很累了，却还是想解释清楚。\n\n第二步，再理解原因。其实很多时候，你不是状态不好，而是太久没有被回应。\n\n第三步，最后学会调整。所以你要慢慢把注意力放回自己身上。最后，你要记得把注意力放回自己身上。",
        word_count: 168,
        version: 2,
      },
      {
        ...baseDetail.draft,
        version: 1,
        title: "旧版标题",
        body_markdown: "# 旧版标题\n\n旧开头第一句\n\n旧中段\n\n旧结尾",
        word_count: 120,
      },
    ],
    assets: [],
    publish_packages: [],
  });

  assert.equal(preview?.blocks[3]?.label, "AI味风险提示");
  assert.equal(preview?.blocks[3]?.content.includes("AI味风险（启发式）：高"), true);
  assert.equal(preview?.blocks[3]?.content.includes("命中：不是A，是B"), true);
  assert.equal(preview?.blocks[3]?.content.includes("命中：教程分步"), true);
  assert.equal(preview?.blocks[3]?.content.includes("命中：解释连接词偏多"), true);
  assert.equal(preview?.blocks[3]?.content.includes("建议：把整齐反转句拆成一个具体场景和一个延迟出现的判断"), true);
  assert.equal(preview?.blocks[3]?.content.includes("建议：把分步教程改成自然叙事推进"), true);
  assert.equal(preview?.blocks[3]?.content.includes("建议：删掉部分解释连接词，让动作和细节承担转场"), true);
});

test("buildWorkbenchPreview flags overused '一' cadence in ai-flavor risk summary", () => {
  const preview = buildWorkbenchPreview("draft", {
    ...baseDetail,
    draft: {
      ...baseDetail.draft,
      title: "工位上的那种累，先别急着怪自己",
      body_markdown:
        "# 标题\n\n她盯着屏幕亮了一下，心里像漏了一格电。\n\n很多时候，倦怠不是一下压过来，而是一点一点磨出来的。\n\n有一些瞬间很轻，一个消息，一句催促，一件临时加进来的事，都让人往下沉一点。\n\n到下班前，她想把一整天理清，却只觉得自己又被什么拽了一下。",
      word_count: 146,
    },
  }, {
    project_slug: "project-a",
    outlines: [],
    drafts: [
      {
        ...baseDetail.draft,
        title: "工位上的那种累，先别急着怪自己",
        body_markdown:
          "# 标题\n\n她盯着屏幕亮了一下，心里像漏了一格电。\n\n很多时候，倦怠不是一下压过来，而是一点一点磨出来的。\n\n有一些瞬间很轻，一个消息，一句催促，一件临时加进来的事，都让人往下沉一点。\n\n到下班前，她想把一整天理清，却只觉得自己又被什么拽了一下。",
        word_count: 146,
        version: 2,
      },
      {
        ...baseDetail.draft,
        version: 1,
        title: "旧版标题",
        body_markdown: "# 旧版标题\n\n旧开头第一句\n\n旧中段\n\n旧结尾",
        word_count: 120,
      },
    ],
    assets: [],
    publish_packages: [],
  });

  assert.equal(preview?.blocks[3]?.label, "AI味风险提示");
  assert.equal(preview?.blocks[3]?.content.includes("命中：“一”字节奏偏密"), true);
  assert.equal(preview?.blocks[3]?.content.includes("建议：替换一半以上的一字量词起手"), true);
});

test("buildWorkbenchPreview flags cliche slogan endings with concrete rewrite advice", () => {
  const preview = buildWorkbenchPreview("draft", {
    ...baseDetail,
    draft: {
      ...baseDetail.draft,
      title: "把自己放回生活里",
      body_markdown:
        "# 标题\n\n她把电脑合上，手还停在桌沿。\n\n真正的成长，从来不是一夜之间变强，而是在每一个疲惫的瞬间重新选择自己。\n\n愿你从今天开始，好好爱自己，成为更好的自己。",
      word_count: 108,
    },
  }, {
    project_slug: "project-a",
    outlines: [],
    drafts: [
      {
        ...baseDetail.draft,
        title: "把自己放回生活里",
        body_markdown:
          "# 标题\n\n她把电脑合上，手还停在桌沿。\n\n真正的成长，从来不是一夜之间变强，而是在每一个疲惫的瞬间重新选择自己。\n\n愿你从今天开始，好好爱自己，成为更好的自己。",
        word_count: 108,
        version: 2,
      },
      {
        ...baseDetail.draft,
        version: 1,
        title: "旧版标题",
        body_markdown: "# 旧版标题\n\n旧开头\n\n旧中段\n\n旧结尾",
        word_count: 90,
      },
    ],
    assets: [],
    publish_packages: [],
  });

  assert.equal(preview?.blocks[3]?.label, "AI味风险提示");
  assert.equal(preview?.blocks[3]?.content.includes("命中：万能成长套话"), true);
  assert.equal(preview?.blocks[3]?.content.includes("命中：结尾口号感"), true);
  assert.equal(preview?.blocks[3]?.content.includes("建议：把万能成长句改成本文人物当下能看见的动作、物件或停顿"), true);
  assert.equal(preview?.blocks[3]?.content.includes("建议：结尾回到人物处境或心绪余波"), true);
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
  assert.equal(
    preview?.blocks[1]?.copyText,
    "1. 为什么越在乎，越容易反复确认\n2. 真正让人不安的并不是一句话\n3. 关系里的稳定感来自可持续回应",
  );
});

test("buildWorkbenchPreview returns assets preview with title and teaser blocks", () => {
  const preview = buildWorkbenchPreview("assets", baseDetail);

  assert.equal(preview?.eyebrow, "Assets Preview");
  assert.equal(preview?.blocks.length, 5);
  assert.equal(preview?.blocks[0]?.label, "封面图");
  assert.equal(preview?.blocks[0]?.content, "/generated-assets/cover.png");
  assert.equal(preview?.blocks[1]?.kind, "markdown");
  assert.equal(preview?.blocks[1]?.content.includes("1. 越在乎的人，为什么越想在关系里反复确认"), true);
  assert.equal(
    preview?.blocks[1]?.copyText,
    "1. 越在乎的人，为什么越想在关系里反复确认\n2. 她不是作，她只是没有被真正接住",
  );
  assert.equal(preview?.blocks[2]?.copyText, "越在乎，越想确认");
  assert.equal(preview?.blocks[3]?.content, "真正让人反复确认的，往往不是一句话，而是关系里长期没有被看见。");
  assert.equal(preview?.blocks[3]?.copyText, "真正让人反复确认的，往往不是一句话，而是关系里长期没有被看见。");
  assert.equal(preview?.blocks[4]?.label, "配图提示词");
  assert.equal(preview?.blocks[4]?.copyText, "close-up portrait, soft light, emotional realism");
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
  assert.equal(preview?.blocks[0]?.copyText, "# 标题\n\n第一段\n\n第二段");
  assert.equal(preview?.blocks[1]?.content, "写给总在关系里反复确认、又不知道为什么停不下来的人。");
  assert.equal(preview?.blocks[2]?.content, "关系 / 确认 / 女性成长");
  assert.equal(preview?.blocks[3]?.kind, "markdown");
  assert.equal(preview?.blocks[3]?.content.includes("1. 检查标题"), true);
});

test("buildWorkbenchPreview adds heuristic originality summary to publish preview when prior draft exists", () => {
  const comparisonDetail = {
    ...baseDetail,
    draft: {
      ...baseDetail.draft,
      body_markdown: "# 标题\n\n新开头第一句\n\n共享中段句子\n\n新的补充论证\n\n新结尾最后一句",
    },
  };

  const preview = buildWorkbenchPreview("publish", comparisonDetail, {
    project_slug: "project-a",
    outlines: [],
    drafts: [
      comparisonDetail.draft,
      {
        ...comparisonDetail.draft,
        version: 0,
        title: "旧版标题",
        body_markdown: "# 旧版标题\n\n旧开头第一句\n\n共享中段句子\n\n旧结尾最后一句",
        word_count: 980,
      },
    ],
    assets: [],
    publish_packages: [],
  });

  assert.equal(preview?.blocks[0]?.label, "原创改写结果");
  assert.equal(preview?.blocks[0]?.content.includes("改写原创度（启发式）：83 / 100"), true);
  assert.equal(preview?.blocks[0]?.content.includes("完全复用段落：1 段"), true);
  assert.equal(preview?.blocks[1]?.label, "AI味风险提示");
  assert.equal(preview?.blocks[2]?.label, "正文成品");
});

test("buildWorkbenchPreview returns publish fallback preview when publish package is missing", () => {
  const comparisonDetail = {
    ...baseDetail,
    draft: {
      ...baseDetail.draft,
      body_markdown: "# 标题\n\n新开头第一句\n\n共享中段句子\n\n新的补充论证\n\n新结尾最后一句",
    },
    publish_package: null,
  };

  const preview = buildWorkbenchPreview("publish", comparisonDetail, {
    project_slug: "project-a",
    outlines: [],
    drafts: [
      comparisonDetail.draft,
      {
        ...comparisonDetail.draft,
        version: 0,
        title: "旧版标题",
        body_markdown: "# 旧版标题\n\n旧开头第一句\n\n共享中段句子\n\n旧结尾最后一句",
        word_count: 980,
      },
    ],
    assets: [],
    publish_packages: [],
  });

  assert.equal(preview?.summary, "发布包待生成，先预览当前正文与改写结果");
  assert.equal(preview?.blocks[0]?.label, "原创改写结果");
  assert.equal(preview?.blocks[1]?.label, "AI味风险提示");
  assert.equal(preview?.blocks[2]?.label, "正文成品");
  assert.equal(preview?.blocks[3]?.label, "发布包状态");
  assert.equal(preview?.blocks[3]?.content.includes("发布包尚未生成"), true);
});

test("buildWorkbenchPreview renders topic preview with strategy package context", () => {
  const preview = buildWorkbenchPreview("topic", {
    ...baseDetail,
    problem_brief: {
      project_slug: "project-a",
      version: 1,
      source_mode: "topic",
      raw_goal: "写一篇关于关系里反复确认的文章",
      clarified_problem: "她明明很在乎，却总在关系里用试探替代开口。",
      target_reader_situation: "深夜反复点开对话框，却不知道这句话该不该发。",
      core_conflict: "想被重视，但又不敢直接说出自己的期待。",
      unknowns: ["对方近期冷淡的具体触发点"],
      status: "ready",
      created_at: "2026-05-30T11:00:00Z",
    },
    strategy_card: {
      project_slug: "project-a",
      version: 1,
      problem_brief_version: 1,
      reader_situation: "在沉默里反复确认对方是否还在乎自己。",
      point_of_view: "先承认这种不安，再拆开她为什么总是用赌气代替表达。",
      conflict_frame: "越想确认越不敢说，最后把关系推远。",
      emotional_path: "嘴硬 -> 失望 -> 看见真正的渴望",
      expression_constraints: ["不要空泛劝和", "不要对称句"],
      benchmark_summary: "借鉴具体处境开头，避免模板化喊话。",
      status: "ready",
      created_at: "2026-05-30T11:02:00Z",
      adopted_at: null,
    },
    benchmarks: [
      {
        project_slug: "project-a",
        strategy_version: 1,
        reference_kind: "trend",
        reference_label: "关系边界重设",
        reference_pointer: "trend://relationship-boundary-reset",
        borrow_focus: "开头具体处境",
        avoid_focus: "一上来就说教",
        rationale: "先落到动作细节，读者更容易代入。",
        sort_order: 1,
      },
    ],
  });

  assert.equal(preview?.eyebrow, "Topic Preview");
  assert.equal(preview?.summary, "前写作策略待确认 · 待采纳 v1");
  assert.equal(preview?.blocks[0]?.label, "策略状态");
  assert.equal(preview?.blocks[1]?.label, "问题澄清");
  assert.equal(preview?.blocks[1]?.content.includes("澄清问题：她明明很在乎"), true);
  assert.equal(preview?.blocks[2]?.label, "策略卡");
  assert.equal(preview?.blocks[2]?.content.includes("切入视角：先承认这种不安"), true);
  assert.equal(preview?.blocks[3]?.label, "参考基准");
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
});
