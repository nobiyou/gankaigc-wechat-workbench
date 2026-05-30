import type { DraftItem, ProjectDetail, ProjectVersions } from "../api/workbench";
import type { WorkbenchStage } from "../app/navigation";

export type WorkbenchPreviewBlock = {
  key: string;
  label: string;
  content: string;
  kind?: "text" | "markdown" | "image";
  imageUrl?: string;
  copyText?: string;
};

export type WorkbenchPreviewModel = {
  title: string;
  eyebrow: string;
  summary: string;
  tone: "default" | "outline" | "draft" | "assets" | "publish";
  blocks: WorkbenchPreviewBlock[];
};

const API_BASE_URL =
  (typeof import.meta !== "undefined" && (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env
    ? (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env?.VITE_API_BASE_URL
    : undefined) ?? "http://localhost:8000/api";

function joinLines(lines: Array<string | null | undefined>): string {
  return lines
    .map((line) => line?.trim())
    .filter((line): line is string => Boolean(line))
    .join("\n");
}

function buildPublishArticleMarkdown(title: string, bodyMarkdown: string): string {
  const normalizedTitle = title.trim();
  const normalizedBody = bodyMarkdown.trim();

  if (!normalizedBody) {
    return normalizedTitle ? `# ${normalizedTitle}` : "";
  }

  if (normalizedBody.startsWith("#")) {
    return normalizedBody;
  }

  return normalizedTitle ? `# ${normalizedTitle}\n\n${normalizedBody}` : normalizedBody;
}

function resolvePreviewAssetUrl(path: string | null | undefined): string {
  const normalizedPath = path?.trim();
  if (!normalizedPath) {
    return "";
  }
  if (/^https?:\/\//i.test(normalizedPath)) {
    return normalizedPath;
  }
  return new URL(normalizedPath, `${new URL(API_BASE_URL).origin}/`).toString();
}

function extractParagraphs(markdown: string): string[] {
  return markdown
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter((part) => Boolean(part) && !part.startsWith("#"));
}

function pickLeadingExcerpt(markdown: string): string {
  const paragraphs = extractParagraphs(markdown);
  return paragraphs[0] ?? "暂无内容";
}

function pickTrailingExcerpt(markdown: string): string {
  const paragraphs = extractParagraphs(markdown);
  return paragraphs.length > 0 ? paragraphs[paragraphs.length - 1] ?? "暂无内容" : "暂无内容";
}

function pickMiddleExcerpt(markdown: string): string {
  const paragraphs = extractParagraphs(markdown);
  if (paragraphs.length <= 2) {
    return paragraphs[1] ?? paragraphs[0] ?? "暂无内容";
  }
  return paragraphs[Math.floor(paragraphs.length / 2)] ?? "暂无内容";
}

function formatSignedNumber(value: number): string {
  return value > 0 ? `+${value}` : `${value}`;
}

function formatSignedParagraphDelta(value: number): string {
  return `${formatSignedNumber(value)} 段`;
}

function hasMeaningfulChange(currentValue: string, previousValue: string): boolean {
  return currentValue.trim() !== previousValue.trim();
}

function countReusedParagraphs(currentMarkdown: string, previousMarkdown: string): number {
  const currentParagraphs = extractParagraphs(currentMarkdown).map((item) => item.trim()).filter(Boolean);
  const previousParagraphs = new Set(extractParagraphs(previousMarkdown).map((item) => item.trim()).filter(Boolean));
  return currentParagraphs.filter((item) => previousParagraphs.has(item)).length;
}

type DraftComparisonSummary = {
  previousDraft: DraftItem;
  titleChanged: boolean;
  openingChanged: boolean;
  middleChanged: boolean;
  endingChanged: boolean;
  reusedParagraphCount: number;
  currentParagraphCount: number;
  previousParagraphCount: number;
  rewrittenParagraphRate: number;
  originalityScore: number;
};

type AiFlavorRiskSummary = {
  score: number;
  level: "低" | "中" | "高";
  hits: string[];
  suggestions: string[];
};

function pickPreviousDraft(
  currentDraft: DraftItem,
  versions?: ProjectVersions | null,
): DraftItem | null {
  if (!versions) {
    return null;
  }

  const previousDrafts = versions.drafts
    .filter((item) => item.version !== currentDraft.version)
    .sort((left, right) => right.version - left.version);

  return (
    previousDrafts.find((item) => item.version < currentDraft.version) ??
    previousDrafts[0] ??
    null
  );
}

function calculateHeuristicOriginalityScore(input: {
  titleChanged: boolean;
  openingChanged: boolean;
  middleChanged: boolean;
  endingChanged: boolean;
  reusedParagraphCount: number;
  currentParagraphCount: number;
  previousParagraphCount: number;
}): number {
  const rewrittenParagraphRate =
    input.currentParagraphCount > 0
      ? (input.currentParagraphCount - input.reusedParagraphCount) / input.currentParagraphCount
      : 0;
  const structureDeltaRate =
    Math.abs(input.currentParagraphCount - input.previousParagraphCount) /
    Math.max(input.currentParagraphCount, input.previousParagraphCount, 1);

  const score =
    rewrittenParagraphRate * 55 +
    (input.titleChanged ? 10 : 0) +
    (input.openingChanged ? 10 : 0) +
    (input.middleChanged ? 10 : 0) +
    (input.endingChanged ? 10 : 0) +
    Math.min(structureDeltaRate, 1) * 5;

  return Math.max(0, Math.min(100, Math.round(score)));
}

function buildDraftComparisonSummary(
  currentDraft: DraftItem,
  versions?: ProjectVersions | null,
): DraftComparisonSummary | null {
  const previousDraft = pickPreviousDraft(currentDraft, versions);
  if (!previousDraft) {
    return null;
  }

  const currentParagraphs = extractParagraphs(currentDraft.body_markdown);
  const previousParagraphs = extractParagraphs(previousDraft.body_markdown);
  const titleChanged = currentDraft.title.trim() !== previousDraft.title.trim();
  const openingChanged = hasMeaningfulChange(
    pickLeadingExcerpt(currentDraft.body_markdown),
    pickLeadingExcerpt(previousDraft.body_markdown),
  );
  const middleChanged = hasMeaningfulChange(
    pickMiddleExcerpt(currentDraft.body_markdown),
    pickMiddleExcerpt(previousDraft.body_markdown),
  );
  const endingChanged = hasMeaningfulChange(
    pickTrailingExcerpt(currentDraft.body_markdown),
    pickTrailingExcerpt(previousDraft.body_markdown),
  );
  const reusedParagraphCount = countReusedParagraphs(
    currentDraft.body_markdown,
    previousDraft.body_markdown,
  );
  const currentParagraphCount = currentParagraphs.length;
  const previousParagraphCount = previousParagraphs.length;
  const rewrittenParagraphRate =
    currentParagraphCount > 0
      ? Math.round(((currentParagraphCount - reusedParagraphCount) / currentParagraphCount) * 100)
      : 0;

  return {
    previousDraft,
    titleChanged,
    openingChanged,
    middleChanged,
    endingChanged,
    reusedParagraphCount,
    currentParagraphCount,
    previousParagraphCount,
    rewrittenParagraphRate,
    originalityScore: calculateHeuristicOriginalityScore({
      titleChanged,
      openingChanged,
      middleChanged,
      endingChanged,
      reusedParagraphCount,
      currentParagraphCount,
      previousParagraphCount,
    }),
  };
}

function buildRewriteAcceptanceSummaryLines(
  currentDraft: DraftItem,
  comparison: DraftComparisonSummary,
): string[] {
  return [
    `改写原创度（启发式）：${comparison.originalityScore} / 100`,
    `当前版本：v${currentDraft.version}`,
    `对照版本：v${comparison.previousDraft.version}`,
    `标题已变化：${comparison.titleChanged ? "是" : "否"}`,
    `字数变化：${formatSignedNumber(currentDraft.word_count - comparison.previousDraft.word_count)}`,
    `段落数变化：${formatSignedParagraphDelta(comparison.currentParagraphCount - comparison.previousParagraphCount)}`,
    `段落重写占比：${comparison.rewrittenParagraphRate}%`,
    `开头已重写：${comparison.openingChanged ? "是" : "否"}`,
    `中段已重写：${comparison.middleChanged ? "是" : "否"}`,
    `结尾已重写：${comparison.endingChanged ? "是" : "否"}`,
    `完全复用段落：${comparison.reusedParagraphCount} 段`,
    "说明：基于标题、首中尾改写、段落复用和结构变化估算，不等同第三方查重。",
  ];
}

function countPatternMatches(markdown: string, pattern: RegExp): number {
  return (markdown.match(pattern) ?? []).length;
}

function buildAiFlavorRiskSummary(draft: DraftItem): AiFlavorRiskSummary {
  const body = draft.body_markdown;
  const hits: string[] = [];
  const suggestions = new Set<string>();
  let score = 0;

  const notABCount = countPatternMatches(body, /不是[^，。；\n]{1,20}[，,、]?\s*而?是[^，。；\n]{1,20}/gu);
  if (notABCount > 0) {
    hits.push(`命中：不是A，是B x${notABCount}`);
    suggestions.add("建议：把整齐反转句拆成一个具体场景和一个延迟出现的判断。");
    score += Math.min(30, notABCount * 12);
  }

  const stepCount = countPatternMatches(body, /第[一二三四五六七八九十]+步/gu);
  if (stepCount > 0) {
    hits.push(`命中：教程分步 x${stepCount}`);
    suggestions.add("建议：把分步教程改成自然叙事推进，让观察和情绪先发生。");
    score += Math.min(24, stepCount * 8);
  }

  const connectorCount = countPatternMatches(body, /(?:比如|例如|其实|所以|因此|也就是说|换句话说|接下来|然后|首先|其次|最后)/gu);
  if (connectorCount >= 4) {
    hits.push(`命中：解释连接词偏多 x${connectorCount}`);
    suggestions.add("建议：删掉部分解释连接词，让动作和细节承担转场。");
    score += Math.min(22, Math.max(8, connectorCount));
  }

  const yiCadenceCount = countPatternMatches(body, /(?:一点|一下|一些|一个|一种|一件|一句|一段|一整天|一会儿|一遍)/gu);
  if (yiCadenceCount >= 5) {
    hits.push(`命中：“一”字节奏偏密 x${yiCadenceCount}`);
    suggestions.add("建议：替换一半以上的一字量词起手，改用具体动作、物件或时间推进。");
    score += Math.min(18, yiCadenceCount * 2);
  }

  const paragraphs = extractParagraphs(body);
  const shortParagraphs = paragraphs.filter((item) => item.length <= 38).length;
  if (paragraphs.length >= 4 && shortParagraphs / paragraphs.length >= 0.55) {
    hits.push(`命中：短促判断段偏多 ${shortParagraphs}/${paragraphs.length}`);
    suggestions.add("建议：把连续短判断段合并为带场景推进的长短句组合。");
    score += 12;
  }

  if (draft.title.includes("不是") && draft.title.includes("，")) {
    hits.push("命中：标题判断句模板");
    suggestions.add("建议：标题少用对称判断，优先写具体处境或情绪入口。");
    score += 16;
  }

  const clicheCount = countPatternMatches(body, /(?:真正的成长|好好爱自己|成为更好的自己|重新选择自己|从今天开始|愿你|治愈自己)/gu);
  if (clicheCount > 0) {
    hits.push(`命中：万能成长套话 x${clicheCount}`);
    suggestions.add("建议：把万能成长句改成本文人物当下能看见的动作、物件或停顿。");
    score += Math.min(24, clicheCount * 10);
  }

  const ending = pickTrailingExcerpt(body);
  if (/(?:愿你|从今天开始|好好爱自己|成为更好的自己|你要相信|终会)/u.test(ending)) {
    hits.push("命中：结尾口号感");
    suggestions.add("建议：结尾回到人物处境或心绪余波，避免喊话式总结。");
    score += 16;
  }

  const boundedScore = Math.max(0, Math.min(100, Math.round(score)));
  const level = boundedScore >= 60 ? "高" : boundedScore >= 30 ? "中" : "低";

  return {
    score: boundedScore,
    level,
    hits,
    suggestions: [...suggestions],
  };
}

function buildAiFlavorRiskSummaryLines(summary: AiFlavorRiskSummary): string[] {
  return [
    `AI味风险（启发式）：${summary.level}`,
    `风险分：${summary.score} / 100`,
    ...(summary.hits.length > 0 ? summary.hits : ["未命中明显模板风险"]),
    ...(summary.suggestions.length > 0 ? summary.suggestions : ["建议：保持具体场景、自然句式和克制收束。"]),
    "说明：基于模板句式、教程骨架、解释连接词和段落形态估算，不等同第三方检测。",
  ];
}

export function buildWorkbenchPreview(
  stage: WorkbenchStage,
  detail: ProjectDetail,
  versions?: ProjectVersions | null,
): WorkbenchPreviewModel | null {
  if (stage === "topic") {
    const strategyCard = detail.strategy_card ?? null;
    const problemBrief = detail.problem_brief ?? null;
    const benchmarks = detail.benchmarks ?? [];
    const strategyStatus = !strategyCard
      ? "还没有生成策略包，先明确问题、读者处境和表达边界。"
      : strategyCard.adopted_at
        ? `当前已采纳策略卡 v${strategyCard.version}，后续生成大纲会带入这套前写作策略。`
        : `当前已有策略卡 v${strategyCard.version}，建议先采纳后再继续生成大纲。`;

    const blocks: WorkbenchPreviewBlock[] = [
      {
        key: "strategy-status",
        label: "策略状态",
        content: strategyStatus,
      },
    ];

    if (problemBrief) {
      const problemBriefLines = [
        `澄清问题：${problemBrief.clarified_problem}`,
        `读者处境：${problemBrief.target_reader_situation}`,
        `核心冲突：${problemBrief.core_conflict}`,
        problemBrief.raw_goal ? `原始目标：${problemBrief.raw_goal}` : null,
        problemBrief.unknowns.length > 0 ? `待补未知项：${problemBrief.unknowns.join(" / ")}` : null,
      ];

      blocks.push({
        key: "problem-brief",
        label: "问题澄清",
        content: joinLines(problemBriefLines),
        kind: "markdown",
        copyText: joinLines(problemBriefLines),
      });
    }

    if (strategyCard) {
      const strategyCardLines = [
        `读者处境：${strategyCard.reader_situation}`,
        `切入视角：${strategyCard.point_of_view}`,
        `冲突框架：${strategyCard.conflict_frame}`,
        `情绪路径：${strategyCard.emotional_path}`,
        strategyCard.expression_constraints.length > 0 ? `表达约束：${strategyCard.expression_constraints.join(" / ")}` : null,
        strategyCard.benchmark_summary ? `参考提要：${strategyCard.benchmark_summary}` : null,
      ];

      blocks.push({
        key: "strategy-card",
        label: "策略卡",
        content: joinLines(strategyCardLines),
        kind: "markdown",
        copyText: joinLines(strategyCardLines),
      });
    }

    if (benchmarks.length > 0) {
      const benchmarkLines = benchmarks.map(
        (item, index) =>
          `${index + 1}. ${item.reference_label}（${item.reference_kind}）\n借鉴：${item.borrow_focus}\n避免：${item.avoid_focus}\n原因：${item.rationale}`,
      );

      blocks.push({
        key: "benchmarks",
        label: "参考基准",
        content: benchmarkLines.join("\n\n"),
        kind: "markdown",
        copyText: benchmarkLines.join("\n\n"),
      });
    }

    return {
      title: problemBrief?.clarified_problem ?? detail.project.title,
      eyebrow: "Topic Preview",
      summary: !strategyCard
        ? "先生成策略包，再确认是否采纳当前策略。"
        : strategyCard.adopted_at
          ? `前写作策略已锁定 · 已采纳 v${strategyCard.version}`
          : `前写作策略待确认 · 待采纳 v${strategyCard.version}`,
      tone: "default",
      blocks,
    };
  }

  if (stage === "outline") {
    if (!detail.outline) {
      return null;
    }

    return {
      title: detail.outline.hook,
      eyebrow: "Outline Preview",
      summary: `结构预览 · v${detail.outline.version}`,
      tone: "outline",
      blocks: [
        {
          key: "hook",
          label: "开篇钩子",
          content: detail.outline.hook,
        },
        {
          key: "outline-body",
          label: "大纲内容",
          content: detail.outline.outline_body,
          kind: "markdown",
          copyText: detail.outline.outline_body,
        },
      ],
    };
  }

  if (stage === "draft") {
    if (!detail.draft) {
      return null;
    }

    const comparison = buildDraftComparisonSummary(detail.draft, versions);

    const blocks: WorkbenchPreviewBlock[] = [
      {
        key: "body",
        label: "正文预览",
        content: detail.draft.body_markdown,
        kind: "markdown",
        copyText: detail.draft.body_markdown,
      },
    ];

    if (comparison) {
      const aiFlavorRisk = buildAiFlavorRiskSummary(detail.draft);
      blocks.push(
        {
          key: "rewrite-acceptance-summary",
          label: "改写验收摘要",
          content: buildRewriteAcceptanceSummaryLines(detail.draft, comparison).join("\n"),
          kind: "markdown",
        },
        {
          key: "previous-draft-summary",
          label: "上一版对照",
          content: [
            `当前标题：${detail.draft.title}`,
            `上一版标题：${comparison.previousDraft.title}`,
            `当前字数：${detail.draft.word_count}`,
            `上一版字数：${comparison.previousDraft.word_count}`,
          ].join("\n"),
          kind: "markdown",
        },
        {
          key: "ai-flavor-risk-summary",
          label: "AI味风险提示",
          content: buildAiFlavorRiskSummaryLines(aiFlavorRisk).join("\n"),
          kind: "markdown",
        },
        {
          key: "opening-compare",
          label: "开头对照",
          content: [
            "当前版：",
            pickLeadingExcerpt(detail.draft.body_markdown),
            "",
            "上一版：",
            pickLeadingExcerpt(comparison.previousDraft.body_markdown),
          ].join("\n"),
          kind: "markdown",
        },
        {
          key: "middle-compare",
          label: "中段对照",
          content: [
            "当前版：",
            pickMiddleExcerpt(detail.draft.body_markdown),
            "",
            "上一版：",
            pickMiddleExcerpt(comparison.previousDraft.body_markdown),
          ].join("\n"),
          kind: "markdown",
        },
        {
          key: "ending-compare",
          label: "结尾对照",
          content: [
            "当前版：",
            pickTrailingExcerpt(detail.draft.body_markdown),
            "",
            "上一版：",
            pickTrailingExcerpt(comparison.previousDraft.body_markdown),
          ].join("\n"),
          kind: "markdown",
        },
      );
    } else {
      const aiFlavorRisk = buildAiFlavorRiskSummary(detail.draft);
      blocks.push({
        key: "ai-flavor-risk-summary",
        label: "AI味风险提示",
        content: buildAiFlavorRiskSummaryLines(aiFlavorRisk).join("\n"),
        kind: "markdown",
      });
    }

    return {
      title: detail.draft.title,
      eyebrow: "Draft Preview",
      summary: `正文预览 · ${detail.draft.word_count} 字`,
      tone: "draft",
      blocks,
    };
  }

  if (stage === "assets") {
    if (!detail.assets) {
      return null;
    }

    return {
      title: detail.assets.title_options[0] ?? "未生成标题",
      eyebrow: "Assets Preview",
      summary: "标题、封面文案与分发导语预览",
      tone: "assets",
      blocks: [
        {
          key: "cover-image",
          label: "封面图",
          content: detail.assets.cover_image_url || "未生成（图片服务暂时不可用）",
          kind: detail.assets.cover_image_url ? "image" : "text",
          imageUrl: resolvePreviewAssetUrl(detail.assets.cover_image_url),
        },
        {
          key: "titles",
          label: "标题组选项",
          content: detail.assets.title_options.map((item, index) => `${index + 1}. ${item}`).join("\n"),
          kind: "markdown",
          copyText: detail.assets.title_options.map((item, index) => `${index + 1}. ${item}`).join("\n"),
        },
        {
          key: "cover-copy",
          label: "封面文案",
          content: detail.assets.cover_copy,
          copyText: detail.assets.cover_copy,
        },
        {
          key: "social-teaser",
          label: "分发导语",
          content: detail.assets.social_teaser,
          copyText: detail.assets.social_teaser,
        },
        {
          key: "cover-prompt",
          label: "配图提示词",
          content: detail.assets.cover_prompt,
          copyText: detail.assets.cover_prompt,
        },
      ],
    };
  }

  if (stage === "publish") {
    if (!detail.draft && !detail.publish_package) {
      return null;
    }

    const comparison = detail.draft ? buildDraftComparisonSummary(detail.draft, versions) : null;

    const blocks: WorkbenchPreviewBlock[] = [];

    if (detail.draft && comparison) {
      const aiFlavorRisk = buildAiFlavorRiskSummary(detail.draft);
      blocks.push({
        key: "publish-rewrite-acceptance-summary",
        label: "原创改写结果",
        content: buildRewriteAcceptanceSummaryLines(detail.draft, comparison).join("\n"),
        kind: "markdown",
      });
      blocks.push({
        key: "publish-ai-flavor-risk-summary",
        label: "AI味风险提示",
        content: buildAiFlavorRiskSummaryLines(aiFlavorRisk).join("\n"),
        kind: "markdown",
      });
    }

    if (detail.draft) {
      const articleMarkdown = buildPublishArticleMarkdown(detail.draft.title, detail.draft.body_markdown);
      blocks.push({
        key: "article",
        label: "正文成品",
        content: articleMarkdown,
        kind: "markdown",
        copyText: articleMarkdown,
      });
    }

    if (!detail.publish_package) {
      blocks.push({
        key: "publish-package-pending",
        label: "发布包状态",
        content: "当前草稿已更新，但发布包尚未生成。先确认原创改写结果，再继续执行素材和发布包生成。",
      });

      return {
        title: detail.draft?.title ?? detail.project.title,
        eyebrow: "Publish Preview",
        summary: "发布包待生成，先预览当前正文与改写结果",
        tone: "publish",
        blocks,
      };
    }

    return {
      title: detail.draft?.title ?? detail.project.title,
      eyebrow: "Publish Preview",
      summary: "最终发布包与上线前检查预览",
      tone: "publish",
      blocks: [
        ...blocks,
        {
          key: "abstract",
          label: "摘要",
          content: detail.publish_package.abstract,
        },
        {
          key: "tags",
          label: "标签",
          content: detail.publish_package.tags.length > 0 ? detail.publish_package.tags.join(" / ") : "暂无标签",
        },
        {
          key: "checklist",
          label: "发布前检查清单",
          content:
            detail.publish_package.publish_checklist.length > 0
              ? detail.publish_package.publish_checklist.map((item, index) => `${index + 1}. ${item}`).join("\n")
              : "暂无检查项",
          kind: "markdown",
        },
        {
          key: "editor-note",
          label: "编辑备注",
          content: detail.publish_package.editor_note,
        },
      ],
    };
  }

  return null;
}
