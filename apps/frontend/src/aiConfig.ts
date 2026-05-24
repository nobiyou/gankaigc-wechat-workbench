import type { AIConfigSummary } from "./api/workbench";

export function formatAiConfigBaseUrl(baseUrl: string | null): string {
  return baseUrl?.trim() || "OpenAI 默认";
}

export function formatAiConfigSummaryLabel(summary: AIConfigSummary): string {
  return summary.api_key_configured ? "已配置" : "缺少 Key";
}

export function formatAiConfigReasoning(summary: AIConfigSummary): string {
  return summary.reasoning_effort?.trim() || "未设置";
}
