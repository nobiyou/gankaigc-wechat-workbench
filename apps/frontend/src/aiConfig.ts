import type { AIConfigCheckResult, AIConfigSummary, AIImageRouteProbeItem } from "./api/workbench";

export function formatAiConfigBaseUrl(baseUrl: string | null): string {
  return baseUrl?.trim() || "OpenAI 默认";
}

export function formatAiConfigSummaryLabel(summary: AIConfigSummary): string {
  return summary.api_key_configured ? "已配置" : "缺少 Key";
}

export function formatAiConfigReasoning(summary: AIConfigSummary): string {
  return summary.reasoning_effort?.trim() || "未设置";
}

export function formatAiConfigImageMode(): string {
  return "API-only";
}

export function formatAiConfigAttemptBudget(attempts: number): string {
  const normalized = Number.isFinite(attempts) ? Math.max(0, Math.trunc(attempts)) : 0;
  return `${normalized} 次`;
}

export function formatAiConfigLocalFallbackMode(summary: AIConfigSummary): string {
  return summary.allow_local_creative_fallbacks ? "允许" : "关闭";
}

export function formatAiConfigImageFallbackRoute(summary: AIConfigSummary): string {
  if (!summary.image_fallback_route_configured) {
    return "未配置";
  }
  if (!summary.image_fallback_route_active) {
    return "已填写但未生效";
  }
  return summary.image_fallback_model?.trim() || "已生效";
}

export function formatAiConfigImageFallbackRouteDifferences(summary: AIConfigSummary): string | null {
  if (!summary.image_fallback_route_difference_labels.length) {
    return null;
  }
  return `差异项：${summary.image_fallback_route_difference_labels.join("、")}`;
}

export function formatAiConfigImageFallbackRouteNote(summary: AIConfigSummary): string | null {
  if (summary.image_fallback_route_active) {
    return null;
  }
  return summary.image_fallback_route_note?.trim() || null;
}

export function formatAiConfigTimeoutSeconds(timeoutSeconds: number | null): string {
  if (timeoutSeconds === null) {
    return "未配置";
  }
  return `${timeoutSeconds} 秒`;
}

export function formatAiConfigFallbackSourceLabel(
  configured: boolean,
  usesInherited: boolean | null,
  inheritedLabel: string,
  dedicatedLabel: string,
): string {
  if (!configured || usesInherited === null) {
    return "未配置";
  }
  return usesInherited ? inheritedLabel : dedicatedLabel;
}

export function formatAiConfigFallbackKeyLabel(summary: AIConfigSummary): string {
  if (!summary.image_fallback_route_configured) {
    return "未配置";
  }
  if (!summary.image_fallback_effective_api_key_configured) {
    return "缺少 Key";
  }
  return summary.image_fallback_uses_inherited_api_key ? "继承主出图链路 Key" : "独立 fallback Key";
}

export function formatAiConfigCheckRouteLabel(result: AIConfigCheckResult): string | null {
  if (!result.route_label) {
    return null;
  }
  if (result.route_label === "primary") {
    return "本次检测命中主出图链路";
  }
  if (result.route_label === "fallback") {
    return "本次检测命中备用图片链路";
  }
  return `本次检测命中 ${result.route_label}`;
}

export function formatAiConfigRouteLabel(routeLabel: string): string {
  if (routeLabel === "primary") {
    return "主出图链路";
  }
  if (routeLabel === "fallback") {
    return "备用图片链路";
  }
  return routeLabel;
}

export function formatAiImageRouteProbeStatus(item: AIImageRouteProbeItem): string {
  if (item.status === "not_configured") {
    return "未配置";
  }
  if (item.status === "inactive") {
    return "未生效";
  }
  return item.ok ? "检测通过" : "检测失败";
}
