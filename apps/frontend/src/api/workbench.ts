const API_BASE_URL =
  (typeof import.meta !== "undefined" && (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env
    ? (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env?.VITE_API_BASE_URL
    : undefined) ?? "http://localhost:8000/api";

export type DashboardSummary = {
  today_trends: number;
  pending_topics: number;
  draft_ready_projects: number;
  publish_ready_projects: number;
  tracked_articles_count: number;
  source_ingestion_runs_count: number;
  latest_source_ingestion_at: string | null;
  latest_source_ingestion_kind: string | null;
  source_freshness_state: "fresh" | "stale" | "missing";
  recent_tasks: TaskLogItem[];
};

export type TaskLogItem = {
  id?: string | number;
  task_type?: string;
  status?: string;
  entity_slug?: string;
  entity_type?: string;
  created_at?: string;
  background_task_id?: string | null;
};

export type TrendItem = {
  slug: string;
  title: string;
  source: string;
  heat_score: number;
  status: string;
};

export type TrendImportResult = {
  line_number: number;
  raw_line: string;
  status: string;
  error: string | null;
  trend: TrendItem | null;
};

export type TrendImportResponse = {
  run_id: number | null;
  requested_count: number;
  created_count: number;
  skipped_count: number;
  failed_count: number;
  results: TrendImportResult[];
};

export type TrendFetchResponse = {
  run_id: number | null;
  requested_source_count: number;
  processed_source_count: number;
  created_count: number;
  skipped_count: number;
  failed_count: number;
  results: Array<{
    source_url: string;
    source_label: string;
    status: string;
    fetched_count: number;
    created_count: number;
    skipped_count: number;
    failed_count: number;
    error: string | null;
  }>;
};

export type TopicItem = {
  slug: string;
  trend_slug: string | null;
  source_type: string;
  source_ref_slug: string;
  title: string;
  angle: string;
  status: string;
};

export type TrackedArticleItem = {
  slug: string;
  source_name: string;
  title: string;
  url: string;
  author: string;
  summary: string;
  structure_notes: string;
  tags: string[];
};

export type WechatMpSessionStatus = {
  logged_in: boolean;
  nickname: string | null;
  expires_at: string | null;
  login_stage: string | null;
  status_message: string | null;
};

export type WechatMpAccountItem = {
  fakeid: string;
  nickname: string;
  alias: string | null;
  round_head_img: string | null;
  service_type: number | null;
  signature: string | null;
};

export type WechatMpArticlePreviewItem = {
  article_id: string;
  account_fakeid: string;
  account_nickname: string;
  title: string;
  link: string;
  author: string;
  digest: string;
  update_time: number;
};

export type WechatMpArticleImportResponse = {
  run_id: number | null;
  requested_count: number;
  imported_count: number;
  skipped_count: number;
  failed_count: number;
  created: TrackedArticleItem[];
  results: Array<{
    status: string;
    reason: string | null;
    article: TrackedArticleItem | null;
  }>;
};

export type ProjectItem = {
  slug: string;
  topic_slug: string;
  title: string;
  stage: string;
  owner: string;
  preferred_tone_profile_id: number | null;
  preferred_tone_profile_name: string | null;
  domain_pack_key: string | null;
  chain_status: "missing" | "stale" | "ready";
  current_chain_state: string;
  next_required_step: string | null;
  current_outline_version: number | null;
  current_draft_version: number | null;
  current_assets_version: number | null;
  current_publish_package_version: number | null;
  retro: ProjectRetroItem | null;
};

export type OutlineItem = {
  project_slug: string;
  version: number;
  hook: string;
  outline_body: string;
  created_at: string | null;
  origin: string | null;
  tone_profile_id: number | null;
  tone_profile_name: string | null;
};

export type DraftItem = {
  project_slug: string;
  outline_version: number;
  version: number;
  title: string;
  body_markdown: string;
  word_count: number;
  created_at: string | null;
  origin: string | null;
  tone_profile_id: number | null;
  tone_profile_name: string | null;
};

export type AssetItem = {
  project_slug: string;
  draft_version: number;
  version: number;
  title_options: string[];
  cover_prompt: string;
  cover_copy: string;
  social_teaser: string;
  cover_image_path: string;
  cover_image_url: string;
  created_at: string | null;
  origin: string | null;
  tone_profile_id: number | null;
  tone_profile_name: string | null;
};

export type PublishPackageItem = {
  project_slug: string;
  draft_version: number;
  assets_version: number;
  version: number;
  abstract: string;
  tags: string[];
  publish_checklist: string[];
  editor_note: string;
  markdown_path: string;
  markdown_url: string;
  manifest_path: string;
  manifest_url: string;
  status: string;
  review_comment: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string | null;
  origin: string | null;
  tone_profile_id: number | null;
  tone_profile_name: string | null;
};

export type ProjectRetroItem = {
  project_slug: string;
  performance_rating: number;
  summary: string;
  wins: string[];
  gaps: string[];
  next_focus: string;
  recorded_at: string;
};

export type ToneProfileItem = {
  id: number;
  is_active: boolean;
  sort_order: number;
  name: string;
  opening_style: string;
  paragraph_rhythm: string;
  closing_style: string;
  forbidden_phrases: string[];
  value_constraints: string;
  target_word_count: number;
};

export type ToneProfileUpsert = Omit<ToneProfileItem, "id" | "is_active" | "sort_order">;

export type ToneProfileReorder = {
  profile_ids: number[];
};

export type AIConfigSummary = {
  api_key_configured: boolean;
  base_url: string | null;
  model: string;
  image_model: string;
  reasoning_effort: string | null;
  request_timeout_seconds: number;
};

export type AIConfigCheckResult = {
  ok: boolean;
  status: string;
  message: string;
  checked_at: string;
};

export type DomainPackSummary = {
  key: string;
  label: string;
  audience: string;
  voice: string;
  constraints: string;
  is_default: boolean;
};

export type PromptTemplateSummary = {
  key: string;
  label: string;
  role: string;
  objective: string;
  output_fields: string[];
  supports_tone_profile: boolean;
  supports_domain_pack: boolean;
  supports_review_feedback: boolean;
};

export type TrendUpdatePayload = Pick<TrendItem, "title" | "heat_score" | "status">;
export type TopicCreatePayload = Pick<TopicItem, "slug" | "title" | "angle">;
export type TopicUpdatePayload = Pick<TopicItem, "title" | "angle" | "status">;
export type TrackedArticleCreatePayload = TrackedArticleItem;

export type ProjectCreatePayload = Pick<ProjectItem, "slug" | "title" | "owner"> & {
  preferred_tone_profile_id?: number | null;
  domain_pack_key?: string | null;
};

export type ProjectUpdatePayload = {
  stage: ProjectItem["stage"];
  preferred_tone_profile_id?: number | null;
  domain_pack_key?: string | null;
};

export type ProjectRetroCreatePayload = {
  performance_rating: number;
  summary: string;
  wins: string[];
  gaps: string[];
  next_focus: string;
};

export type ProjectDetail = {
  project: ProjectItem;
  outline: OutlineItem | null;
  draft: DraftItem | null;
  assets: AssetItem | null;
  publish_package: PublishPackageItem | null;
  retro: ProjectRetroItem | null;
};

export type ProjectVersions = {
  project_slug: string;
  outlines: OutlineItem[];
  drafts: DraftItem[];
  assets: AssetItem[];
  publish_packages: PublishPackageItem[];
};

export type BatchContinueProjectResult = {
  slug: string;
  status: string;
  started_next_step: string | null;
  completed_steps: string[];
  error: string | null;
  project: ProjectItem | null;
};

export type BatchContinueProjectsResponse = {
  requested_count: number;
  processed_count: number;
  skipped_count: number;
  failed_count: number;
  results: BatchContinueProjectResult[];
};

export type BackgroundTaskSubmission = {
  task_id: string;
  job_type: string;
  status: string;
  created_at: string;
};

export type BackgroundTaskDetail = BackgroundTaskSubmission & {
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  result: Record<string, unknown> | null;
};

export type BatchGenerateTopicResult = {
  trend_slug: string;
  status: string;
  error: string | null;
  topic: TopicItem | null;
};

export type BatchGenerateTopicsResponse = {
  requested_count: number;
  processed_count: number;
  skipped_count: number;
  failed_count: number;
  results: BatchGenerateTopicResult[];
};

export type BatchGenerateTrackedArticleTopicResult = {
  article_slug: string;
  status: string;
  error: string | null;
  topic: TopicItem | null;
};

export type BatchGenerateTrackedArticleTopicsResponse = {
  requested_count: number;
  processed_count: number;
  skipped_count: number;
  failed_count: number;
  results: BatchGenerateTrackedArticleTopicResult[];
};

export type BatchCreateProjectResult = {
  topic_slug: string;
  status: string;
  error: string | null;
  project: ProjectItem | null;
};

export type BatchCreateProjectsResponse = {
  requested_count: number;
  processed_count: number;
  skipped_count: number;
  failed_count: number;
  results: BatchCreateProjectResult[];
};

async function buildApiError(response: Response, fallbackMessage: string): Promise<Error> {
  try {
    const payload = (await response.json()) as { detail?: string; message?: string };
    return new Error(payload.detail || payload.message || fallbackMessage);
  } catch {
    return new Error(fallbackMessage);
  }
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw await buildApiError(response, `Failed to fetch ${path}`);
  }
  return response.json() as Promise<T>;
}

async function sendJson<T>(path: string, method: string, body: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw await buildApiError(response, `Failed to ${method} ${path}`);
  }
  return response.json() as Promise<T>;
}

export function fetchDashboardSummary(): Promise<DashboardSummary> {
  return fetchJson<DashboardSummary>("/dashboard/summary");
}

export function fetchTrends(): Promise<TrendItem[]> {
  return fetchJson<TrendItem[]>("/trends");
}

export function fetchTopics(): Promise<TopicItem[]> {
  return fetchJson<TopicItem[]>("/topics");
}

export function fetchTrackedArticles(): Promise<TrackedArticleItem[]> {
  return fetchJson<TrackedArticleItem[]>("/tracked-articles");
}

export function fetchWechatMpSession(): Promise<WechatMpSessionStatus> {
  return fetchJson<WechatMpSessionStatus>("/wechat-mp/session");
}

export function startWechatMpLoginQrcode(): Promise<string> {
  return fetch(`${API_BASE_URL}/wechat-mp/login/qrcode`, {
    method: "POST",
  }).then((response) => {
    if (!response.ok) {
      throw new Error("Failed to POST /wechat-mp/login/qrcode");
    }
    return response.blob();
  }).then((blob) => {
    return URL.createObjectURL(blob);
  });
}

export function fetchWechatMpLoginStatus(): Promise<WechatMpSessionStatus> {
  return fetchJson<WechatMpSessionStatus>("/wechat-mp/login/status");
}

export function logoutWechatMp(): Promise<WechatMpSessionStatus> {
  return sendJson<WechatMpSessionStatus>("/wechat-mp/logout", "POST", {});
}

export function searchWechatMpAccounts(
  keyword: string,
  begin: number = 0,
  size: number = 5,
): Promise<WechatMpAccountItem[]> {
  const params = new URLSearchParams({
    keyword,
    begin: String(begin),
    size: String(size),
  });
  return fetchJson<WechatMpAccountItem[]>(`/wechat-mp/accounts?${params.toString()}`);
}

export function fetchWechatMpArticles(
  fakeid: string,
  begin: number = 0,
  size: number = 5,
  keyword: string = "",
): Promise<WechatMpArticlePreviewItem[]> {
  const params = new URLSearchParams({
    begin: String(begin),
    size: String(size),
    keyword,
  });
  return fetchJson<WechatMpArticlePreviewItem[]>(`/wechat-mp/accounts/${fakeid}/articles?${params.toString()}`);
}

export function importWechatMpArticles(
  articles: WechatMpArticlePreviewItem[],
  fallbackAccountNickname?: string,
): Promise<WechatMpArticleImportResponse> {
  return sendJson<WechatMpArticleImportResponse>("/wechat-mp/articles/import", "POST", {
    articles,
    fallback_account_nickname: fallbackAccountNickname?.trim() || null,
  });
}

export function fetchProjects(): Promise<ProjectItem[]> {
  return fetchJson<ProjectItem[]>("/projects");
}

export function fetchToneProfiles(): Promise<ToneProfileItem[]> {
  return fetchJson<ToneProfileItem[]>("/tone-profiles");
}

export function fetchAIConfigSummary(): Promise<AIConfigSummary> {
  return fetchJson<AIConfigSummary>("/settings/ai-config");
}

export function checkAIConfig(): Promise<AIConfigCheckResult> {
  return sendJson<AIConfigCheckResult>("/settings/ai-config/check", "POST", {});
}

export function fetchDomainPacks(): Promise<DomainPackSummary[]> {
  return fetchJson<DomainPackSummary[]>("/settings/domain-packs");
}

export function fetchPromptTemplates(): Promise<PromptTemplateSummary[]> {
  return fetchJson<PromptTemplateSummary[]>("/settings/prompt-templates");
}

export function fetchProjectDetail(projectSlug: string): Promise<ProjectDetail> {
  return fetchJson<ProjectDetail>(`/projects/${projectSlug}`);
}

export function fetchProjectVersions(projectSlug: string): Promise<ProjectVersions> {
  return fetchJson<ProjectVersions>(`/projects/${projectSlug}/versions`);
}

export function createTrend(payload: TrendItem): Promise<TrendItem> {
  return sendJson<TrendItem>("/trends", "POST", payload);
}

export function importTrends(rawText: string): Promise<TrendImportResponse> {
  return sendJson<TrendImportResponse>("/trends/import", "POST", {
    raw_text: rawText,
  });
}

export function fetchLiveTrends(): Promise<TrendFetchResponse> {
  return sendJson<TrendFetchResponse>("/trends/fetch", "POST", {});
}

export function updateTrend(trendSlug: string, payload: TrendUpdatePayload): Promise<TrendItem> {
  return sendJson<TrendItem>(`/trends/${trendSlug}`, "PATCH", payload);
}

export function createTopicFromTrend(
  trendSlug: string,
  payload: Pick<TopicItem, "slug" | "title" | "angle">,
): Promise<TopicItem> {
  return sendJson<TopicItem>(`/trends/${trendSlug}/to-topic`, "POST", payload);
}

export function createTopicFromTrackedArticle(
  articleSlug: string,
  payload: Pick<TopicItem, "slug" | "title" | "angle">,
): Promise<TopicItem> {
  return sendJson<TopicItem>(`/tracked-articles/${articleSlug}/to-topic`, "POST", payload);
}

export function generateTopicFromTrend(trendSlug: string): Promise<TopicItem> {
  return sendJson<TopicItem>(`/trends/${trendSlug}/generate-topic`, "POST", {});
}

export function generateTopicFromTrackedArticle(articleSlug: string): Promise<TopicItem> {
  return sendJson<TopicItem>(`/tracked-articles/${articleSlug}/generate-topic`, "POST", {});
}

export function createTrackedArticle(payload: TrackedArticleCreatePayload): Promise<TrackedArticleItem> {
  return sendJson<TrackedArticleItem>("/tracked-articles", "POST", payload);
}

export function updateTopic(topicSlug: string, payload: TopicUpdatePayload): Promise<TopicItem> {
  return sendJson<TopicItem>(`/topics/${topicSlug}`, "PATCH", payload);
}

export function createTopic(payload: TopicCreatePayload): Promise<TopicItem> {
  return sendJson<TopicItem>("/topics", "POST", payload);
}

export function createProjectFromTopic(
  topicSlug: string,
  payload: ProjectCreatePayload,
): Promise<ProjectItem> {
  return sendJson<ProjectItem>(`/topics/${topicSlug}/create-project`, "POST", payload);
}

export function updateToneProfile(
  profileId: number,
  payload: ToneProfileUpsert,
): Promise<ToneProfileItem> {
  return sendJson<ToneProfileItem>(`/tone-profiles/${profileId}`, "PATCH", payload);
}

export function createToneProfile(payload: ToneProfileUpsert): Promise<ToneProfileItem> {
  return sendJson<ToneProfileItem>("/tone-profiles", "POST", payload);
}

export function activateToneProfile(profileId: number): Promise<ToneProfileItem> {
  return sendJson<ToneProfileItem>(`/tone-profiles/${profileId}/activate`, "POST", {});
}

export function duplicateToneProfile(profileId: number): Promise<ToneProfileItem> {
  return sendJson<ToneProfileItem>(`/tone-profiles/${profileId}/duplicate`, "POST", {});
}

export function reorderToneProfiles(payload: ToneProfileReorder): Promise<ToneProfileItem[]> {
  return sendJson<ToneProfileItem[]>("/tone-profiles/reorder", "POST", payload);
}

export function deleteToneProfile(profileId: number): Promise<{ deleted_profile_id: number }> {
  return sendJson<{ deleted_profile_id: number }>(`/tone-profiles/${profileId}`, "DELETE", {});
}

export function updateProject(
  projectSlug: string,
  payload: ProjectUpdatePayload,
): Promise<ProjectItem> {
  return sendJson<ProjectItem>(`/projects/${projectSlug}`, "PATCH", payload);
}

export function generateOutline(projectSlug: string): Promise<OutlineItem> {
  return sendJson<OutlineItem>(`/projects/${projectSlug}/generate-outline`, "POST", {});
}

export function restoreOutlineVersion(projectSlug: string, version: number): Promise<OutlineItem> {
  return sendJson<OutlineItem>(`/projects/${projectSlug}/restore-outline/${version}`, "POST", {});
}

export function generateDraft(projectSlug: string): Promise<DraftItem> {
  return sendJson<DraftItem>(`/projects/${projectSlug}/generate-draft`, "POST", {});
}

export function polishDraft(projectSlug: string, instruction: string): Promise<DraftItem> {
  return sendJson<DraftItem>(`/projects/${projectSlug}/polish-draft`, "POST", { instruction });
}

export function restoreDraftVersion(projectSlug: string, version: number): Promise<DraftItem> {
  return sendJson<DraftItem>(`/projects/${projectSlug}/restore-draft/${version}`, "POST", {});
}

export function generateAssets(projectSlug: string): Promise<AssetItem> {
  return sendJson<AssetItem>(`/projects/${projectSlug}/generate-assets`, "POST", {});
}

export function restoreAssetsVersion(projectSlug: string, version: number): Promise<AssetItem> {
  return sendJson<AssetItem>(`/projects/${projectSlug}/restore-assets/${version}`, "POST", {});
}

export function buildPublishPackage(projectSlug: string): Promise<PublishPackageItem> {
  return sendJson<PublishPackageItem>(`/projects/${projectSlug}/build-publish-package`, "POST", {});
}

export function restorePublishPackageVersion(projectSlug: string, version: number): Promise<PublishPackageItem> {
  return sendJson<PublishPackageItem>(`/projects/${projectSlug}/restore-publish-package/${version}`, "POST", {});
}

export function approvePublishPackage(
  projectSlug: string,
  payload: { reviewer: string; comment: string },
): Promise<PublishPackageItem> {
  return sendJson<PublishPackageItem>(`/projects/${projectSlug}/approve-publish-package`, "POST", payload);
}

export function requestPublishRevision(
  projectSlug: string,
  payload: { reviewer: string; comment: string },
): Promise<PublishPackageItem> {
  return sendJson<PublishPackageItem>(`/projects/${projectSlug}/request-publish-revision`, "POST", payload);
}

export function recordProjectRetro(
  projectSlug: string,
  payload: ProjectRetroCreatePayload,
): Promise<ProjectRetroItem> {
  return sendJson<ProjectRetroItem>(`/projects/${projectSlug}/retro`, "POST", payload);
}

export function regenerateFromReview(projectSlug: string): Promise<BackgroundTaskSubmission> {
  return sendJson<BackgroundTaskSubmission>(`/projects/${projectSlug}/regenerate-from-review`, "POST", {});
}

export function batchContinueProjects(projectSlugs?: string[]): Promise<BackgroundTaskSubmission> {
  return sendJson<BackgroundTaskSubmission>("/projects/batch-continue", "POST", {
    project_slugs: projectSlugs ?? null,
  });
}

export function fetchBackgroundTask(taskId: string): Promise<BackgroundTaskDetail> {
  return fetchJson<BackgroundTaskDetail>(`/background-tasks/${taskId}`);
}

export function fetchPipelineTaskLogs(limit = 20): Promise<TaskLogItem[]> {
  return fetchJson<TaskLogItem[]>(`/background-tasks/logs?scope=pipeline&limit=${limit}`);
}

export function batchGenerateTopics(trendSlugs?: string[]): Promise<BackgroundTaskSubmission> {
  return sendJson<BackgroundTaskSubmission>("/trends/batch-generate-topics", "POST", {
    trend_slugs: trendSlugs ?? null,
  });
}

export function batchGenerateTopicsFromTrackedArticles(
  articleSlugs?: string[],
): Promise<BackgroundTaskSubmission> {
  return sendJson<BackgroundTaskSubmission>("/tracked-articles/batch-generate-topics", "POST", {
    article_slugs: articleSlugs ?? null,
  });
}

export function batchCreateProjects(topicSlugs?: string[]): Promise<BackgroundTaskSubmission> {
  return sendJson<BackgroundTaskSubmission>("/topics/batch-create-projects", "POST", {
    topic_slugs: topicSlugs ?? null,
  });
}
