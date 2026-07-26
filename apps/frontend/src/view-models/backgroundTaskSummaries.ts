import type { BackgroundTaskDetail, BackgroundTaskErrorContext, ProjectItem } from "../api/workbench";

export type BatchCreateProjectResultView = {
  topicSlug: string;
  status: string;
  canRetry: boolean;
  message: string | null;
  projectSlug: string | null;
  line: string;
};

export function buildBackgroundTaskSummaryLines(taskDetail: BackgroundTaskDetail | null): string[] {
  if (!taskDetail?.result) {
    return [];
  }

  const requested = taskDetail.result.requested_count;
  const processed = taskDetail.result.processed_count;
  const skipped = taskDetail.result.skipped_count;
  const failed = taskDetail.result.failed_count;

  if (
    typeof requested !== "number" ||
    typeof processed !== "number" ||
    typeof skipped !== "number" ||
    typeof failed !== "number"
  ) {
    return [];
  }

  return [`请求 ${requested} 项`, `完成 ${processed} 项`, `跳过 ${skipped} 项`, `失败 ${failed} 项`];
}

type ParsedBackgroundTaskError = {
  code: string | null;
  message: string | null;
  errorType: string | null;
  raw: string;
};

function pickFirstString(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === "string" && value.trim().length > 0) {
      return value.trim();
    }
  }

  return null;
}

function resolveBackgroundTaskItemLabel(item: Record<string, unknown>, index: number): string {
  return (
    pickFirstString(
      item.title,
      item.slug,
      item.topic_slug,
      item.article_slug,
      item.trend_slug,
      item.project_slug,
      item.source_label,
      item.source_url,
      item.article_id,
    ) ?? `第 ${index + 1} 项`
  );
}

function normalizeBackgroundTaskStatus(status: unknown): string | null {
  if (typeof status !== "string") {
    return null;
  }

  const normalized = status.trim().toLowerCase();
  return normalized.length > 0 ? normalized : null;
}

function pickNestedRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

function parseBackgroundTaskError(rawError: string): ParsedBackgroundTaskError {
  const raw = rawError.trim();
  const codeMatch = raw.match(/^Error code:\s*(\d+)\s*-\s*(.+)$/i);
  const payload = codeMatch ? codeMatch[2] : raw;
  const messageMatch = payload.match(/["']message["']\s*:\s*["']([^"']+)["']/i);
  const typeMatch = payload.match(/["']type["']\s*:\s*["']([^"']+)["']/i);

  return {
    code: codeMatch?.[1] ?? null,
    message: messageMatch?.[1]?.trim() ?? null,
    errorType: typeMatch?.[1]?.trim() ?? null,
    raw,
  };
}

function formatCoverRouteLabel(value?: string | null): string {
  if (value === "primary") {
    return "主路由";
  }
  if (value === "fallback") {
    return "降级路由";
  }
  return value?.trim() || "未知";
}

function buildBackgroundTaskErrorContextLines(errorContext?: BackgroundTaskErrorContext | null): string[] {
  if (!errorContext) {
    return [];
  }

  const lines: string[] = [];
  const routeParts = [
    errorContext.cover_image_route_label ? formatCoverRouteLabel(errorContext.cover_image_route_label) : null,
    errorContext.cover_image_route_model?.trim() || null,
  ].filter((item): item is string => Boolean(item));

  if (routeParts.length > 0) {
    lines.push(`封面链路：${routeParts.join(" · ")}`);
  }
  if (errorContext.cover_image_route_base_url?.trim()) {
    lines.push(`图片接口：${errorContext.cover_image_route_base_url.trim()}`);
  }
  if (errorContext.fallback_account_pool_diagnosis_label?.trim()) {
    lines.push(`备用链路诊断：${errorContext.fallback_account_pool_diagnosis_label.trim()}`);
  }
  if (errorContext.fallback_account_pool_diagnosis_note?.trim()) {
    lines.push(errorContext.fallback_account_pool_diagnosis_note.trim());
  }

  return lines;
}

export function buildBackgroundTaskErrorLines(taskDetail: BackgroundTaskDetail | null): string[] {
  const coverTaskNote =
    taskDetail?.job_type === "regenerate_cover_image" ? "当前封面只走 API 图片链路，不会回退到本地生成。" : null;

  if (!taskDetail?.error) {
    const lines = buildBackgroundTaskErrorContextLines(taskDetail?.error_context);
    return coverTaskNote && !lines.includes(coverTaskNote) ? [...lines, coverTaskNote] : lines;
  }

  const parsed = parseBackgroundTaskError(taskDetail.error);
  const code = parsed.code;
  const errorType = parsed.errorType?.toLowerCase() ?? null;

  let headline: string | null = null;
  let suggestion: string | null = null;

  if (code === "502" || errorType === "upstream_error") {
    headline = "上游 AI 服务暂时不可用（502）";
    suggestion = "建议：稍后重试；如果持续失败，去 Settings 检查当前 AI 服务与模型配置。";
  } else if (code === "401" || errorType === "auth_error") {
    headline = "AI 配置认证失败（401）";
    suggestion = "建议：去 Settings 检查 API Key、Base URL 和模型权限。";
  } else if (code === "403" || errorType === "permission_error") {
    headline = "当前模型或账号没有权限（403）";
    suggestion = "建议：确认当前模型可用，并检查账号权限或服务商侧限制。";
  } else if (code === "404" || errorType === "not_found") {
    headline = "当前模型或接口不存在（404）";
    suggestion = "建议：去 Settings 检查 Base URL、模型名和接口兼容性。";
  } else if (code === "429" || errorType === "rate_limited") {
    headline = "当前请求频率已超限（429）";
    suggestion = "建议：稍后重试，或检查当前服务商的频率与额度限制。";
  } else if (code === "400" || errorType === "bad_request") {
    headline = "当前请求被上游拒绝（400）";
    suggestion = "建议：去 Settings 检查模型、参数和服务商兼容性。";
  }

  if (!headline) {
    const lines = [parsed.raw, ...buildBackgroundTaskErrorContextLines(taskDetail.error_context)];
    return coverTaskNote && !lines.includes(coverTaskNote) ? [...lines, coverTaskNote] : lines;
  }

  const lines = [headline];
  if (parsed.message) {
    lines.push(`来源返回：${parsed.message}`);
  }
  if (parsed.errorType) {
    lines.push(`错误类型：${parsed.errorType}`);
  }
  if (suggestion) {
    lines.push(suggestion);
  }
  const mergedLines = [...lines, ...buildBackgroundTaskErrorContextLines(taskDetail.error_context)];
  return coverTaskNote && !mergedLines.includes(coverTaskNote) ? [...mergedLines, coverTaskNote] : mergedLines;
}

export function buildBackgroundTaskIssueLines(taskDetail: BackgroundTaskDetail | null, maxLines = 5): string[] {
  if (!taskDetail?.result || typeof taskDetail.result !== "object") {
    return [];
  }

  const results = (taskDetail.result as { results?: unknown }).results;
  if (!Array.isArray(results)) {
    return [];
  }

  const lines: string[] = [];

  for (const [index, rawItem] of results.entries()) {
    if (!rawItem || typeof rawItem !== "object") {
      continue;
    }

    const item = rawItem as Record<string, unknown>;
    const status = normalizeBackgroundTaskStatus(item.status);
    const message = pickFirstString(item.error, item.reason);

    if (status !== "failed" && status !== "skipped" && !message) {
      continue;
    }

    const label = resolveBackgroundTaskItemLabel(item, index);
    const statusLabel = status === "skipped" ? "跳过" : status === "failed" ? "失败" : "提示";
    lines.push(message ? `${statusLabel}: ${label} - ${message}` : `${statusLabel}: ${label}`);

    if (lines.length >= maxLines) {
      break;
    }
  }

  return lines;
}

export function buildBatchCreateProjectResultLines(taskDetail: BackgroundTaskDetail | null, maxLines = 5): string[] {
  return Object.values(buildBatchCreateProjectResultMap(taskDetail))
    .slice(0, maxLines)
    .map((item) => item.line);
}

export function mergeBatchCreateProjectResultMaps(
  current: Record<string, BatchCreateProjectResultView>,
  next: Record<string, BatchCreateProjectResultView>,
): Record<string, BatchCreateProjectResultView> {
  return {
    ...current,
    ...next,
  };
}

export function pruneBatchCreateProjectResultMap(
  resultMap: Record<string, BatchCreateProjectResultView>,
  validTopicSlugs: string[],
): Record<string, BatchCreateProjectResultView> {
  const validTopicSlugSet = new Set(validTopicSlugs);
  return Object.fromEntries(
    Object.entries(resultMap).filter(([topicSlug]) => validTopicSlugSet.has(topicSlug)),
  );
}

function resolveBatchCreateResultRecordedAt(taskDetail: BackgroundTaskDetail): number {
  const recordedAt = taskDetail.finished_at ?? taskDetail.created_at ?? taskDetail.started_at ?? "";
  const timestamp = Date.parse(recordedAt);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

export function buildRecentBatchCreateProjectResultMap(
  taskDetails: Array<BackgroundTaskDetail | null | undefined>,
): Record<string, BatchCreateProjectResultView> {
  return [...taskDetails]
    .filter((detail): detail is BackgroundTaskDetail => {
      if (!detail) {
        return false;
      }

      return detail.job_type === "batch_create_projects";
    })
    .sort((left, right) => resolveBatchCreateResultRecordedAt(left) - resolveBatchCreateResultRecordedAt(right))
    .reduce<Record<string, BatchCreateProjectResultView>>(
      (resultMap, detail) => mergeBatchCreateProjectResultMaps(resultMap, buildBatchCreateProjectResultMap(detail)),
      {},
    );
}

export function buildBatchCreateProjectResultMap(
  taskDetail: BackgroundTaskDetail | null,
): Record<string, BatchCreateProjectResultView> {
  if (!taskDetail?.result || typeof taskDetail.result !== "object") {
    return {};
  }

  const results = (taskDetail.result as { results?: unknown }).results;
  if (!Array.isArray(results)) {
    return {};
  }

  const resultMap: Record<string, BatchCreateProjectResultView> = {};

  for (const [index, rawItem] of results.entries()) {
    if (!rawItem || typeof rawItem !== "object") {
      continue;
    }

    const item = rawItem as Record<string, unknown>;
    const status = normalizeBackgroundTaskStatus(item.status);
    const label = pickFirstString(item.topic_slug, item.slug) ?? `第 ${index + 1} 项`;
    const message = pickFirstString(item.error, item.reason);
    const project = pickNestedRecord(item.project);
    const projectLabel = pickFirstString(project?.slug, project?.title, item.project_slug);
    let line: string | null = null;

    if (status === "done") {
      line = projectLabel ? `完成: ${label} -> ${projectLabel}` : `完成: ${label}`;
    } else if (status === "skipped") {
      line = message ? `跳过: ${label} - ${message}` : `跳过: ${label}`;
    } else if (status === "failed") {
      line = message ? `失败: ${label} - ${message}` : `失败: ${label}`;
    }

    if (!line) {
      continue;
    }

    resultMap[label] = {
      topicSlug: label,
      status: status ?? "unknown",
      canRetry: status === "failed" || status === "skipped",
      message,
      projectSlug: projectLabel,
      line,
    };
  }

  return resultMap;
}

export function patchBatchCreateProjectResultAsDone(
  taskDetail: BackgroundTaskDetail | null,
  project: ProjectItem,
  topicSlug: string,
): BackgroundTaskDetail | null {
  if (!taskDetail?.result || typeof taskDetail.result !== "object") {
    return taskDetail;
  }

  const currentResult = taskDetail.result as Record<string, unknown>;
  const results = currentResult.results;
  if (!Array.isArray(results)) {
    return taskDetail;
  }

  let matched = false;
  let nextProcessed = typeof currentResult.processed_count === "number" ? currentResult.processed_count : null;
  let nextSkipped = typeof currentResult.skipped_count === "number" ? currentResult.skipped_count : null;
  let nextFailed = typeof currentResult.failed_count === "number" ? currentResult.failed_count : null;

  const nextResults = results.map((rawItem) => {
    if (!rawItem || typeof rawItem !== "object") {
      return rawItem;
    }

    const item = rawItem as Record<string, unknown>;
    if (pickFirstString(item.topic_slug, item.slug) !== topicSlug) {
      return rawItem;
    }

    matched = true;
    const previousStatus = normalizeBackgroundTaskStatus(item.status);
    if (previousStatus === "failed" && nextFailed !== null && nextProcessed !== null) {
      nextFailed = Math.max(0, nextFailed - 1);
      nextProcessed += 1;
    } else if (previousStatus === "skipped" && nextSkipped !== null && nextProcessed !== null) {
      nextSkipped = Math.max(0, nextSkipped - 1);
      nextProcessed += 1;
    }

    return {
      ...item,
      status: "done",
      error: null,
      reason: null,
      project,
    };
  });

  if (!matched) {
    return taskDetail;
  }

  return {
    ...taskDetail,
    result: {
      ...currentResult,
      processed_count: nextProcessed ?? currentResult.processed_count,
      skipped_count: nextSkipped ?? currentResult.skipped_count,
      failed_count: nextFailed ?? currentResult.failed_count,
      results: nextResults,
    },
  };
}
