import type { PromptTemplateSummary } from "./api/workbench";

export function buildPromptTemplateSummaryLines(template: PromptTemplateSummary): string[] {
  const inputCapabilities: string[] = [];
  if (template.supports_domain_pack) {
    inputCapabilities.push("赛道");
  }
  if (template.supports_tone_profile) {
    inputCapabilities.push("风格");
  }
  if (template.supports_review_feedback) {
    inputCapabilities.push("审核意见");
  }

  return [
    `职责：${template.role}`,
    `目标：${template.key === "draft" ? `${template.objective} 默认按公众号正文自然表达与原创增强约束执行。` : template.objective}`,
    `输出：${template.output_fields.join(" / ")}`,
    `输入：${inputCapabilities.length > 0 ? inputCapabilities.join(" / ") : "固定模板"}`,
  ];
}
