import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  batchContinueProjects,
  batchCreateProjects,
  batchGenerateTopics,
  batchGenerateTopicsFromTrackedArticles,
  createTopic,
  createProjectFromTopic,
  fetchBackgroundTask,
  fetchDashboardSummary,
  fetchDomainPacks,
  fetchPipelineTaskLogs,
  fetchProjects,
  fetchToneProfiles,
  fetchTopics,
  fetchTrackedArticles,
  fetchTrends,
  updateTopic,
  type BackgroundTaskDetail,
  type BackgroundTaskSubmission,
  type DashboardSummary,
  type DomainPackSummary,
  type ProjectItem,
  type TaskLogItem,
  type ToneProfileItem,
  type TopicItem,
  type TrackedArticleItem,
  type TrendItem,
} from "../api/workbench";
import { buildProjectCreateDraft, type ProjectCreateDraft } from "../projectCreation";
import { getTaskTypeLabel } from "../taskLabels";
import { getToneProfileSelectionLabel } from "../toneProfiles";
import {
  buildTopicCreatePayload,
  createTopicCreateDraft,
  syncTopicDraftTitle,
  type TopicCreateDraft,
} from "../topicCreation";
import {
  buildTopicSelectionSummary,
  collectBatchDroppableTopicSlugs,
  collectBatchProjectCreatableTopicSlugs,
  toggleTopicSelection,
} from "../topicQueueSelection";
import { buildTopicDraft, formatTopicStatusLabel, hasTopicDraftChanged, type TopicDraftState } from "../topicDrafts";
import {
  type BatchCreateProjectResultView,
  buildBackgroundTaskErrorLines,
  buildBackgroundTaskIssueLines,
  buildRecentBatchCreateProjectResultMap,
  buildBatchCreateProjectResultMap,
  buildBackgroundTaskSummaryLines,
  buildBatchCreateProjectResultLines,
  mergeBatchCreateProjectResultMaps,
  patchBatchCreateProjectResultAsDone,
  pruneBatchCreateProjectResultMap,
} from "../view-models/backgroundTaskSummaries";
import {
  buildBatchRunCards,
  buildPipelineViewsState,
  type BatchRunCard,
  type BatchRunCardKey,
  type PipelineTaskLogFilter,
  type PipelineTaskStatus,
  type TopicSourceFilter,
} from "../view-models/pipelineViews";
import { buildProjectConfigPreviewLines } from "../projectConfigPreview";

type PipelineSection = "topics" | "runs" | "tasks";

type PipelineData = {
  summary: DashboardSummary;
  taskLog: TaskLogItem[];
  topics: TopicItem[];
  projects: ProjectItem[];
  trends: TrendItem[];
  trackedArticles: TrackedArticleItem[];
  domainPacks: DomainPackSummary[];
  toneProfiles: ToneProfileItem[];
};

type PipelineLoadState =
  | {
      status: "loading";
    }
  | {
      status: "error";
      message: string;
    }
  | {
      status: "ready";
      data: PipelineData;
    };

type BatchRunTaskState = {
  submission: BackgroundTaskSubmission;
  detail: BackgroundTaskDetail | null;
  error: string | null;
};

const SECTION_COPY: Record<PipelineSection, { title: string; description: string }> = {
  topics: {
    title: "选题队列过渡管理区",
    description: "Topics 在 Pipeline 中作为过渡对象管理，承接来源层转出的候选内容，再决定是否批量建项目。",
  },
  runs: {
    title: "批量运行与推进",
    description: "趋势转选题、参考文章转选题、选题建项目和项目续链统一在这里发起与查看。",
  },
  tasks: {
    title: "任务日志与失败归位",
    description: "批量任务的状态、失败项和重跑入口留在 Pipeline，不再散落到来源页或旧 Task Center。",
  },
};

const TASK_LOG_FILTERS: Array<{ key: PipelineTaskLogFilter; label: string }> = [
  { key: "all", label: "全部" },
  { key: "running", label: "进行中" },
  { key: "failed", label: "失败" },
  { key: "done", label: "已完成" },
  { key: "skipped", label: "已跳过" },
];

const TOPIC_SOURCE_FILTERS: Array<{ key: TopicSourceFilter; label: string }> = [
  { key: "all", label: "全部来源" },
  { key: "trend", label: "热点" },
  { key: "tracked_article", label: "参考文章" },
  { key: "manual", label: "原创选题" },
];

function loadPipelineData(): Promise<PipelineData> {
  return Promise.all([
    fetchDashboardSummary(),
    fetchPipelineTaskLogs(),
    fetchTopics(),
    fetchProjects(),
    fetchTrends(),
    fetchTrackedArticles(),
    fetchDomainPacks(),
    fetchToneProfiles(),
  ]).then(([summary, taskLog, topics, projects, trends, trackedArticles, domainPacks, toneProfiles]) => ({
    summary,
    taskLog,
    topics,
    projects,
    trends,
    trackedArticles,
    domainPacks,
    toneProfiles,
  }));
}

function formatTaskStatusLabel(status: PipelineTaskStatus): string {
  if (status === "done") {
    return "已完成";
  }
  if (status === "failed") {
    return "失败";
  }
  if (status === "skipped") {
    return "已跳过";
  }
  return "进行中";
}

function formatTimestampLabel(createdAt?: string | null): string {
  if (!createdAt) {
    return "时间未知";
  }

  const timestamp = Date.parse(createdAt);
  if (Number.isNaN(timestamp)) {
    return "时间未知";
  }

  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function getBatchRunJobTypeLabel(jobType?: string): string {
  if (!jobType) {
    return "后台任务";
  }

  return getTaskTypeLabel(jobType);
}

function getBatchRetryLabel(taskType?: string): string {
  const normalized = taskType?.trim().toLowerCase();
  if (normalized === "batch_generate_topics") {
    return "重跑趋势转选题";
  }
  if (normalized === "batch_generate_topics_from_tracked_articles") {
    return "重跑参考文章转选题";
  }
  if (normalized === "batch_create_projects") {
    return "重跑选题建项目";
  }
  if (normalized === "batch_continue_projects") {
    return "重跑项目续链";
  }
  return "回到批量运行";
}

function resolveRetryBatchRunKey(taskType?: string): BatchRunCardKey | null {
  const normalized = taskType?.trim().toLowerCase();
  if (normalized === "batch_generate_topics") {
    return "generate-trend-topics";
  }
  if (normalized === "batch_generate_topics_from_tracked_articles") {
    return "generate-article-topics";
  }
  if (normalized === "batch_create_projects") {
    return "create-projects";
  }
  if (normalized === "batch_continue_projects") {
    return "continue-projects";
  }
  return null;
}

function getTopicSourceCount(
  sourceSummary: {
    all: number;
    trend: number;
    tracked_article: number;
    manual: number;
  },
  filter: TopicSourceFilter,
): number {
  if (filter === "all") {
    return sourceSummary.all;
  }
  return sourceSummary[filter];
}

function formatTopicSourceFilterLabel(filter: TopicSourceFilter): string {
  if (filter === "trend") {
    return "热点";
  }
  if (filter === "tracked_article") {
    return "参考文章";
  }
  if (filter === "manual") {
    return "原创选题";
  }
  return "全部来源";
}

export function PipelinePage({ section }: { section: PipelineSection }) {
  const [loadState, setLoadState] = useState<PipelineLoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);
  const [taskLogFilter, setTaskLogFilter] = useState<PipelineTaskLogFilter>("all");
  const [topicSourceFilter, setTopicSourceFilter] = useState<TopicSourceFilter>("all");
  const [activeRun, setActiveRun] = useState<BatchRunTaskState | null>(null);
  const [taskDetails, setTaskDetails] = useState<Record<string, BackgroundTaskDetail | null>>({});
  const [taskDetailErrors, setTaskDetailErrors] = useState<Record<string, string | null>>({});
  const [runMessage, setRunMessage] = useState<string | null>(null);
  const [projectDrafts, setProjectDrafts] = useState<Record<string, ProjectCreateDraft>>({});
  const [topicDrafts, setTopicDrafts] = useState<Record<string, TopicDraftState>>({});
  const [topicCreateDraft, setTopicCreateDraft] = useState<TopicCreateDraft>(() => createTopicCreateDraft());
  const [isCreateTopicExpanded, setIsCreateTopicExpanded] = useState(false);
  const [selectedTopicSlugs, setSelectedTopicSlugs] = useState<string[]>([]);
  const [topicBatchCreateResultMap, setTopicBatchCreateResultMap] = useState<Record<string, BatchCreateProjectResultView>>({});
  const [creatingTopicSlug, setCreatingTopicSlug] = useState<string | null>(null);
  const [creatingManualTopic, setCreatingManualTopic] = useState(false);
  const [isBulkDroppingTopics, setIsBulkDroppingTopics] = useState(false);
  const [savingTopicSlug, setSavingTopicSlug] = useState<string | null>(null);
  const [expandedTopicSlug, setExpandedTopicSlug] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;
    setLoadState({ status: "loading" });

    loadPipelineData()
      .then((data) => {
        if (!isCancelled) {
          setLoadState({ status: "ready", data });
          setProjectDrafts(
            Object.fromEntries(
              data.topics.map((topic) => [topic.slug, buildProjectCreateDraft(topic, data.domainPacks)]),
            ),
          );
          setTopicDrafts(
            Object.fromEntries(
              data.topics.map((topic) => [topic.slug, buildTopicDraft(topic)]),
            ),
          );
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "Pipeline 数据加载失败。",
          });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [reloadToken]);

  useEffect(() => {
    if (!activeRun?.submission.task_id) {
      return;
    }

    const taskId = activeRun.submission.task_id;
    let isCancelled = false;
    let timerId: number | null = null;

    async function pollTask() {
      try {
        const detail = await fetchBackgroundTask(taskId);
        if (isCancelled) {
          return;
        }

        setActiveRun((current) =>
          current
            ? {
                ...current,
                detail,
                error: null,
              }
            : current,
        );
        if (detail.job_type === "batch_create_projects") {
          setTopicBatchCreateResultMap((current) =>
            mergeBatchCreateProjectResultMaps(current, buildBatchCreateProjectResultMap(detail)),
          );
        }

        if (detail.status === "queued" || detail.status === "running") {
          timerId = window.setTimeout(() => {
            void pollTask();
          }, 2000);
          return;
        }

        setRunMessage(`批量任务已更新：${getBatchRunJobTypeLabel(detail.job_type)} 当前状态 ${detail.status}。`);
        setReloadToken((value) => value + 1);
      } catch (error: unknown) {
        if (!isCancelled) {
          setActiveRun((current) =>
            current
              ? {
                  ...current,
                  error: error instanceof Error ? error.message : "拉取后台任务状态失败。",
                }
              : current,
          );
        }
      }
    }

    void pollTask();

    return () => {
      isCancelled = true;
      if (timerId !== null) {
        window.clearTimeout(timerId);
      }
    };
  }, [activeRun?.submission.task_id]);

  useEffect(() => {
    if (loadState.status !== "ready") {
      setSelectedTopicSlugs([]);
      setTopicBatchCreateResultMap({});
      return;
    }

    const visibleTopicSlugSet = new Set(
      buildPipelineViewsState({
        topics: loadState.data.topics,
        projects: loadState.data.projects,
        recentTasks: loadState.data.taskLog,
        taskLogFilter,
        topicSourceFilter,
      }).topicQueue.items.map((item) => item.topic.slug),
    );

    setSelectedTopicSlugs((current) => current.filter((topicSlug) => visibleTopicSlugSet.has(topicSlug)));
    setTopicBatchCreateResultMap((current) =>
      pruneBatchCreateProjectResultMap(current, Array.from(visibleTopicSlugSet)),
    );
  }, [loadState, taskLogFilter, topicSourceFilter]);

  useEffect(() => {
    if (loadState.status !== "ready") {
      return;
    }

    const pipelineState = buildPipelineViewsState({
      topics: loadState.data.topics,
      projects: loadState.data.projects,
      recentTasks: loadState.data.taskLog,
      taskLogFilter,
    });

    const missingTaskIds = pipelineState.taskLog.items
      .map((task) => task.backgroundTaskId)
      .filter((taskId): taskId is string => Boolean(taskId))
      .filter((taskId) => !(taskId in taskDetails) && !(taskId in taskDetailErrors));

    if (missingTaskIds.length === 0) {
      return;
    }

    let isCancelled = false;
    void Promise.all(
      missingTaskIds.map(async (taskId) => {
        try {
          const detail = await fetchBackgroundTask(taskId);
          if (!isCancelled) {
            setTaskDetails((current) => ({ ...current, [taskId]: detail }));
            setTaskDetailErrors((current) => ({ ...current, [taskId]: null }));
          }
        } catch (error: unknown) {
          if (!isCancelled) {
            setTaskDetailErrors((current) => ({
              ...current,
              [taskId]: error instanceof Error ? error.message : "加载任务详情失败。",
            }));
          }
        }
      }),
    );

    return () => {
      isCancelled = true;
    };
  }, [loadState, taskDetails, taskDetailErrors, taskLogFilter]);

  async function handleRunBatch(key: BatchRunCardKey) {
    try {
      setRunMessage(null);
      setActiveRun(null);

      let submission: BackgroundTaskSubmission;
      if (key === "generate-trend-topics") {
        submission = await batchGenerateTopics();
      } else if (key === "generate-article-topics") {
        submission = await batchGenerateTopicsFromTrackedArticles();
      } else if (key === "create-projects") {
        submission = await batchCreateProjects();
      } else {
        submission = await batchContinueProjects();
      }

      setActiveRun({
        submission,
        detail: null,
        error: null,
      });
      setRunMessage(`已提交批量任务：${getBatchRunJobTypeLabel(submission.job_type)}，当前状态 ${submission.status}。`);
    } catch (error: unknown) {
      setRunMessage(error instanceof Error ? error.message : "提交批量任务失败。");
      setActiveRun(null);
    }
  }

  async function handleRetryTask(taskType?: string) {
    const retryKey = resolveRetryBatchRunKey(taskType);
    if (!retryKey) {
      setRunMessage("当前任务类型暂不支持从 Task Log 直接重跑。");
      return;
    }

    await handleRunBatch(retryKey);
  }

  async function handleCreateProject(topic: TopicItem) {
    if (loadState.status !== "ready") {
      return;
    }

    const draft = projectDrafts[topic.slug] ?? buildProjectCreateDraft(topic, loadState.data.domainPacks);
    try {
      setCreatingTopicSlug(topic.slug);
      const created = await createProjectFromTopic(topic.slug, {
        slug: draft.slug,
        title: draft.title,
        owner: draft.owner,
        domain_pack_key: draft.domain_pack_key,
        preferred_tone_profile_id: draft.preferred_tone_profile_id,
      });
      setRunMessage(`已创建项目：${created.title}`);
      setLoadState({
        status: "ready",
        data: {
          ...loadState.data,
          projects: [created, ...loadState.data.projects],
          topics: loadState.data.topics.map((item) => (item.slug === topic.slug ? { ...item, status: "drafting" } : item)),
        },
      });
      setTopicBatchCreateResultMap((current) =>
        pruneBatchCreateProjectResultMap(
          mergeBatchCreateProjectResultMaps(current, {
            [topic.slug]: {
              topicSlug: topic.slug,
              status: "done",
              canRetry: false,
              message: null,
              projectSlug: created.slug,
              line: `完成: ${topic.slug} -> ${created.slug}`,
            },
          }),
          loadState.data.topics
            .filter((item) => item.status === "pending" || item.status === "drafting")
            .map((item) => item.slug),
        ),
      );
      setActiveRun((current) => {
        if (!current || current.submission.job_type !== "batch_create_projects") {
          return current;
        }

        return {
          ...current,
          detail: patchBatchCreateProjectResultAsDone(current.detail, created, topic.slug),
        };
      });
    } catch (error: unknown) {
      setRunMessage(error instanceof Error ? error.message : "创建项目失败。");
    } finally {
      setCreatingTopicSlug(null);
    }
  }

  async function handleCreateManualTopic() {
    if (loadState.status !== "ready") {
      return;
    }

    try {
      setCreatingManualTopic(true);
      setRunMessage(null);

      const payload = buildTopicCreatePayload(topicCreateDraft);
      const created = await createTopic(payload);

      setLoadState({
        status: "ready",
        data: {
          ...loadState.data,
          topics: [created, ...loadState.data.topics],
        },
      });
      setTopicDrafts((current) => ({
        ...current,
        [created.slug]: buildTopicDraft(created),
      }));
      setProjectDrafts((current) => ({
        ...current,
        [created.slug]: buildProjectCreateDraft(created, loadState.data.domainPacks),
      }));
      setTopicCreateDraft(createTopicCreateDraft());
      setIsCreateTopicExpanded(false);
      setExpandedTopicSlug(created.slug);
      setRunMessage(`已创建原创选题：${created.title}`);
    } catch (error: unknown) {
      setRunMessage(error instanceof Error ? error.message : "创建原创选题失败。");
    } finally {
      setCreatingManualTopic(false);
    }
  }

  async function handleCreateSelectedProjects(topicSlugs: string[]) {
    try {
      setRunMessage(null);
      setActiveRun(null);

      const submission = await batchCreateProjects(topicSlugs);
      setActiveRun({
        submission,
        detail: null,
        error: null,
      });
      setSelectedTopicSlugs([]);
      setRunMessage(
        `已提交批量任务：${getBatchRunJobTypeLabel(submission.job_type)}，当前状态 ${submission.status}。`,
      );
    } catch (error: unknown) {
      setRunMessage(error instanceof Error ? error.message : "提交批量建项目失败。");
      setActiveRun(null);
    }
  }

  async function handleDropSelectedTopics() {
    if (loadState.status !== "ready") {
      return;
    }

    const droppableTopicSlugs = collectBatchDroppableTopicSlugs(pipelineState.topicQueue.items, selectedTopicSlugs);

    if (droppableTopicSlugs.length === 0) {
      setRunMessage("当前选择中没有可批量废弃的选题。");
      return;
    }

    try {
      setIsBulkDroppingTopics(true);
      setRunMessage(null);

      const result = await Promise.allSettled(
        droppableTopicSlugs.map(async (topicSlug) => {
          const topic = loadState.data.topics.find((item) => item.slug === topicSlug);
          if (!topic) {
            throw new Error(`Topic not found: ${topicSlug}`);
          }
          const draft = topicDrafts[topic.slug] ?? buildTopicDraft(topic);
          return updateTopic(topic.slug, {
            ...draft,
            status: "dropped",
          });
        }),
      );

      const updatedTopics = result
        .filter((item): item is PromiseFulfilledResult<TopicItem> => item.status === "fulfilled")
        .map((item) => item.value);
      const failedCount = result.length - updatedTopics.length;

      if (updatedTopics.length > 0) {
        const updatedTopicMap = new Map(updatedTopics.map((topic) => [topic.slug, topic]));
        setLoadState({
          status: "ready",
          data: {
            ...loadState.data,
            topics: loadState.data.topics.map((topic) => updatedTopicMap.get(topic.slug) ?? topic),
          },
        });
        setTopicDrafts((current) => ({
          ...current,
          ...Object.fromEntries(updatedTopics.map((topic) => [topic.slug, buildTopicDraft(topic)])),
        }));
      }

      setSelectedTopicSlugs([]);
      setExpandedTopicSlug((current) => (current && droppableTopicSlugs.includes(current) ? null : current));
      if (failedCount > 0) {
        setRunMessage(`批量废弃完成：成功 ${updatedTopics.length} 条，失败 ${failedCount} 条。`);
      } else {
        setRunMessage(`已批量废弃 ${updatedTopics.length} 条选题。`);
      }
    } catch (error: unknown) {
      setRunMessage(error instanceof Error ? error.message : "批量废弃选题失败。");
    } finally {
      setIsBulkDroppingTopics(false);
    }
  }

  async function handleSaveTopic(topic: TopicItem) {
    if (loadState.status !== "ready") {
      return;
    }

    const draft = topicDrafts[topic.slug] ?? buildTopicDraft(topic);
    try {
      setSavingTopicSlug(topic.slug);
      setRunMessage(null);
      const updated = await updateTopic(topic.slug, draft);
      setLoadState({
        status: "ready",
        data: {
          ...loadState.data,
          topics: loadState.data.topics.map((item) => (item.slug === topic.slug ? updated : item)),
        },
      });
      setTopicDrafts((current) => ({
        ...current,
        [topic.slug]: buildTopicDraft(updated),
      }));
      setRunMessage(`已更新选题：${updated.title}`);
    } catch (error: unknown) {
      setRunMessage(error instanceof Error ? error.message : "保存选题失败。");
    } finally {
      setSavingTopicSlug(null);
    }
  }

  if (loadState.status === "loading") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--loading">
          <p className="dashboard-state__eyebrow">加载中</p>
          <h3>正在加载 Pipeline</h3>
          <p>正在同步选题队列、批量任务和异步状态。</p>
        </div>
      </section>
    );
  }

  if (loadState.status === "error") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--error">
          <p className="dashboard-state__eyebrow">加载失败</p>
          <h3>Pipeline 加载失败</h3>
          <p>{loadState.message}</p>
          <div className="dashboard-state__actions">
            <button className="dashboard-button" type="button" onClick={() => setReloadToken((value) => value + 1)}>
              重新加载
            </button>
          </div>
        </div>
      </section>
    );
  }

  const content = SECTION_COPY[section];
  const pipelineState = buildPipelineViewsState({
    topics: loadState.data.topics,
    projects: loadState.data.projects,
    recentTasks: loadState.data.taskLog,
    taskLogFilter,
    topicSourceFilter,
    backgroundTaskDetails: taskDetails,
  });
  const batchRunCards = buildBatchRunCards({
    trends: loadState.data.trends,
    trackedArticles: loadState.data.trackedArticles,
    topics: loadState.data.topics,
    projects: loadState.data.projects,
  });
  const batchRunSummaryLines = buildBackgroundTaskSummaryLines(activeRun?.detail ?? null);
  const restoredBatchCreateResultMap = buildRecentBatchCreateProjectResultMap(Object.values(taskDetails));
  const batchCreateProjectResultMap = mergeBatchCreateProjectResultMaps(
    mergeBatchCreateProjectResultMaps(restoredBatchCreateResultMap, topicBatchCreateResultMap),
    buildBatchCreateProjectResultMap(activeRun?.detail ?? null),
  );
  const batchCreateProjectResultLines = buildBatchCreateProjectResultLines(activeRun?.detail ?? null);
  const isSubmittingBatchRun = activeRun?.detail?.status === "queued" || activeRun?.detail?.status === "running";
  const hasAnyTopicQueueItems = pipelineState.topicQueue.sourceSummary.all > 0;
  const isTopicBatchCreateRun = activeRun?.submission.job_type === "batch_create_projects";
  const topicSelectionSummary = buildTopicSelectionSummary({
    selectedTopicSlugs,
    topicQueueItems: pipelineState.topicQueue.items,
  });
  const visibleTopicSlugs = pipelineState.topicQueue.items.map((item) => item.topic.slug);
  const allVisibleTopicsSelected =
    visibleTopicSlugs.length > 0 && visibleTopicSlugs.every((topicSlug) => selectedTopicSlugs.includes(topicSlug));
  const renderBackgroundTaskDiagnostics = (taskId?: string | null) => {
    if (!taskId) {
      return null;
    }

    const detail = taskDetails[taskId] ?? null;
    const detailFetchError = taskDetailErrors[taskId];
    const errorLines = buildBackgroundTaskErrorLines(detail);
    const issueLines = buildBackgroundTaskIssueLines(detail);

    if (errorLines.length === 0 && issueLines.length === 0 && !detailFetchError) {
      return null;
    }

    return (
      <>
        {errorLines.length > 0 ? (
          <div className="workspace-note workspace-note--error">
            {errorLines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        ) : null}
        {issueLines.length > 0 ? (
          <div className={`workspace-note ${errorLines.length > 0 ? "workspace-note--info" : "workspace-note--error"}`}>
            {issueLines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        ) : null}
        {detailFetchError ? (
          <div className="workspace-note workspace-note--error">
            <p>{detailFetchError}</p>
          </div>
        ) : null}
      </>
    );
  };

  return (
    <section className="workspace-page">
      <section className="workspace-section">
        <div className="workspace-section__header">
          <div>
            <p className="workspace-section__eyebrow">Pipeline</p>
            <h3>{content.title}</h3>
            <p className="workspace-section__description">{content.description}</p>
          </div>
        </div>
        <div className="workspace-summary-grid">
          <article className="workspace-summary-card">
            <span>选题队列</span>
            <strong>{pipelineState.topicQueue.statusSummary.total} 项</strong>
            <p>待建项目与撰写中选题统一在这里归位。</p>
          </article>
          <article className="workspace-summary-card">
            <span>批量运行</span>
            <strong>{pipelineState.batchRuns.statusSummary.total} 条</strong>
            <p>最近的批量任务提交会在这里聚合显示。</p>
          </article>
          <article className="workspace-summary-card">
            <span>任务日志</span>
            <strong>{pipelineState.taskLog.statusSummary.failed} 条失败</strong>
            <p>失败项与后续重跑入口统一留在 Pipeline。</p>
          </article>
        </div>
      </section>

      {runMessage ? (
        <div className="workspace-note workspace-note--success">
          <p>{runMessage}</p>
        </div>
      ) : null}

      {activeRun?.error ? (
        <div className="workspace-note workspace-note--error">
          <p>{activeRun.error}</p>
        </div>
      ) : null}

      {section === "topics" ? (
        <section className="workspace-section">
          <div className="workspace-section__header">
            <div>
              <p className="workspace-section__eyebrow">选题队列</p>
              <h4>待转项目选题</h4>
              <p className="workspace-section__description">
                选题队列是来源到项目之间的集中管理区，不混入来源页的单条素材浏览。
              </p>
            </div>
            <div className="workspace-actions">
              <button
                className="dashboard-button dashboard-button--ghost"
                type="button"
                onClick={() => setIsCreateTopicExpanded((current) => !current)}
              >
                {isCreateTopicExpanded ? "收起原创选题" : "新建原创选题"}
              </button>
              <Link className="dashboard-inline-link" to="/pipeline/runs">
                去批量建项目
              </Link>
            </div>
          </div>

          {isCreateTopicExpanded ? (
            <div className="workspace-subsection workspace-project-config-panel">
              <div className="workspace-section__header">
                <div>
                  <p className="workspace-section__eyebrow">原创选题</p>
                  <h4>标题、slug 与角度</h4>
                  <p className="workspace-section__description">适合没有热点来源的原创灵感，先录入再流转到项目队列。</p>
                </div>
              </div>
              <div className="quick-form workspace-actions--row">
                <label className="workspace-search workspace-search--compact">
                  <span>选题标题</span>
                  <input
                    value={topicCreateDraft.title}
                    onChange={(event) =>
                      setTopicCreateDraft((current) => syncTopicDraftTitle(current, event.target.value))
                    }
                  />
                </label>
                <label className="workspace-search workspace-search--compact">
                  <span>选题 slug</span>
                  <input
                    value={topicCreateDraft.slug}
                    onChange={(event) =>
                      setTopicCreateDraft((current) => ({
                        ...current,
                        slug: event.target.value,
                      }))
                    }
                  />
                </label>
                <label className="workspace-search workspace-search--compact">
                  <span>选题角度</span>
                  <input
                    value={topicCreateDraft.angle}
                    onChange={(event) =>
                      setTopicCreateDraft((current) => ({
                        ...current,
                        angle: event.target.value,
                      }))
                    }
                  />
                </label>
                <button
                  className="dashboard-button"
                  type="button"
                  disabled={creatingManualTopic}
                  onClick={() => void handleCreateManualTopic()}
                >
                  {creatingManualTopic ? "创建中..." : "创建选题"}
                </button>
              </div>
              <div className="workspace-note workspace-note--info">
                <p>标题会自动联动 slug，手动改过 slug 后会保留自定义值。</p>
                <p>创建后会直接进入选题队列，并可继续转项目。</p>
              </div>
            </div>
          ) : null}

          {hasAnyTopicQueueItems ? (
            <div className="workspace-filter-row">
              {TOPIC_SOURCE_FILTERS.map((item) => (
                <button
                  key={item.key}
                  className={
                    item.key === topicSourceFilter
                      ? "workspace-filter-button workspace-filter-button--active"
                      : "workspace-filter-button"
                  }
                  type="button"
                  onClick={() => setTopicSourceFilter(item.key)}
                >
                  {`${item.label} ${getTopicSourceCount(pipelineState.topicQueue.sourceSummary, item.key)}`}
                </button>
              ))}
            </div>
          ) : null}

          {!hasAnyTopicQueueItems ? (
            <div className="dashboard-state dashboard-state--empty">
              <p className="dashboard-state__eyebrow">暂无数据</p>
              <h3>当前没有待处理选题队列</h3>
              <p>可以回到 Sources 生成单条选题，或去批量运行启动新一轮批量推进。</p>
            </div>
          ) : pipelineState.topicQueue.items.length === 0 ? (
            <div className="dashboard-state dashboard-state--empty">
              <p className="dashboard-state__eyebrow">筛选结果为空</p>
              <h3>{`当前没有来自${formatTopicSourceFilterLabel(topicSourceFilter)}的待处理选题`}</h3>
              <p>可以切回其他来源，或继续从 Sources / 原创入口补充新的 Topic Queue。</p>
            </div>
          ) : (
            <>
              <div className="workspace-summary-grid">
                <article className="workspace-summary-card">
                  <span>待建项目</span>
                  <strong>{pipelineState.topicQueue.statusSummary.pending}</strong>
                </article>
                <article className="workspace-summary-card">
                  <span>撰写中</span>
                  <strong>{pipelineState.topicQueue.statusSummary.drafting}</strong>
                </article>
              </div>
              <div className="workspace-subsection workspace-bulk-toolbar">
                <div className="workspace-item__header">
                  <div>
                    <p className="workspace-section__eyebrow">批量操作</p>
                    <h4>当前筛选内多选推进</h4>
                    <p className="workspace-section__description">
                      {`已选 ${topicSelectionSummary.selectedCount} 条，可批量建项目 ${topicSelectionSummary.projectCreatableCount} 条，可批量废弃 ${topicSelectionSummary.droppableCount} 条。`}
                    </p>
                  </div>
                </div>
                <div className="workspace-actions workspace-actions--row">
                  <button
                    className="dashboard-button dashboard-button--ghost"
                    type="button"
                    onClick={() => setSelectedTopicSlugs(allVisibleTopicsSelected ? [] : visibleTopicSlugs)}
                  >
                    {allVisibleTopicsSelected ? "清空当前筛选选择" : "全选当前筛选"}
                  </button>
                  <button
                    className="dashboard-button"
                    type="button"
                    disabled={topicSelectionSummary.projectCreatableCount === 0 || isSubmittingBatchRun}
                    onClick={() =>
                      void handleCreateSelectedProjects(
                        collectBatchProjectCreatableTopicSlugs(pipelineState.topicQueue.items, selectedTopicSlugs),
                      )
                    }
                  >
                    {isSubmittingBatchRun ? "提交中..." : "批量建项目"}
                  </button>
                  <button
                    className="dashboard-button dashboard-button--ghost"
                    type="button"
                    disabled={topicSelectionSummary.droppableCount === 0 || isBulkDroppingTopics}
                    onClick={() => void handleDropSelectedTopics()}
                  >
                    {isBulkDroppingTopics ? "废弃中..." : "批量废弃"}
                  </button>
                </div>
              </div>
              {isTopicBatchCreateRun ? (
                <div className="workspace-note workspace-note--info">
                  <p>最近一次批量建项目结果</p>
                  {batchRunSummaryLines.length > 0 ? (
                    <div className="workspace-tag-list">
                      {batchRunSummaryLines.map((line) => (
                        <span key={line} className="workspace-tag">
                          {line}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p>正在等待后台回传批量建项目结果。</p>
                  )}
                  {batchCreateProjectResultLines.length > 0 ? (
                    <>
                      {batchCreateProjectResultLines.map((line) => (
                        <p key={line}>{line}</p>
                      ))}
                    </>
                  ) : null}
                </div>
              ) : null}
              <div className="workspace-list">
                {pipelineState.topicQueue.items.map((item) => (
                  <article key={item.topic.slug} className="workspace-item">
                    {(() => {
                      const latestBatchCreateResult = batchCreateProjectResultMap[item.topic.slug] ?? null;
                      const showRetryCreateProject =
                        latestBatchCreateResult?.status === "failed" || latestBatchCreateResult?.status === "skipped";

                      return (
                        <>
                    <div className="workspace-item__header">
                      <label className="workspace-selection-toggle">
                        <input
                          type="checkbox"
                          checked={selectedTopicSlugs.includes(item.topic.slug)}
                          onChange={() =>
                            setSelectedTopicSlugs((current) => toggleTopicSelection(current, item.topic.slug))
                          }
                        />
                        <span>选择</span>
                      </label>
                      <div>
                        <h4>{item.topic.title}</h4>
                        <p>{item.topic.slug}</p>
                      </div>
                      <span className="workspace-pill">{formatTopicStatusLabel(item.topic.status)}</span>
                    </div>
                    <div className="workspace-item__meta">
                      <span>{item.sourceLabel}</span>
                      <span>{item.topic.angle}</span>
                    </div>
                    {latestBatchCreateResult ? (
                      <div className="workspace-note workspace-note--info">
                        <p>最近一次批量建项反馈</p>
                        <p>{latestBatchCreateResult.line}</p>
                        {latestBatchCreateResult.canRetry ? (
                          <div className="workspace-actions workspace-actions--row">
                            <button
                              className="dashboard-button dashboard-button--ghost"
                              type="button"
                              disabled={creatingTopicSlug === item.topic.slug}
                              onClick={() => void handleCreateProject(item.topic)}
                            >
                              {creatingTopicSlug === item.topic.slug ? "重试中..." : "按当前配置重试"}
                            </button>
                          </div>
                        ) : null}
                      </div>
                    ) : null}
                    <div className="workspace-actions">
                      <button
                        className="dashboard-button dashboard-button--ghost"
                        type="button"
                        onClick={() => setExpandedTopicSlug((current) => (current === item.topic.slug ? null : item.topic.slug))}
                      >
                        {expandedTopicSlug === item.topic.slug
                          ? "收起建项配置"
                          : showRetryCreateProject
                            ? "重试建项目"
                            : "直接建项目"}
                      </button>
                      <Link className="dashboard-inline-link" to="/pipeline/runs">
                        去批量建项目
                      </Link>
                    </div>
                    {expandedTopicSlug === item.topic.slug ? (
                      <div className="workspace-subsection workspace-project-config-panel">
                        <div className="workspace-section__header">
                          <div>
                            <p className="workspace-section__eyebrow">选题配置</p>
                            <h4>标题、角度与状态</h4>
                            <p className="workspace-section__description">先确认选题本身，再决定是否转成项目。</p>
                          </div>
                        </div>
                        <div className="quick-form workspace-actions--row">
                          <label className="workspace-search workspace-search--compact">
                            <span>选题标题</span>
                            <input
                              value={topicDrafts[item.topic.slug]?.title ?? item.topic.title}
                              onChange={(event) =>
                                setTopicDrafts((current) => ({
                                  ...current,
                                  [item.topic.slug]: {
                                    ...(current[item.topic.slug] ?? buildTopicDraft(item.topic)),
                                    title: event.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                          <label className="workspace-search workspace-search--compact">
                            <span>选题角度</span>
                            <input
                              value={topicDrafts[item.topic.slug]?.angle ?? item.topic.angle}
                              onChange={(event) =>
                                setTopicDrafts((current) => ({
                                  ...current,
                                  [item.topic.slug]: {
                                    ...(current[item.topic.slug] ?? buildTopicDraft(item.topic)),
                                    angle: event.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                          <label className="workspace-search workspace-search--compact">
                            <span>选题状态</span>
                            <select
                              className="workspace-select"
                              value={topicDrafts[item.topic.slug]?.status ?? item.topic.status}
                              onChange={(event) =>
                                setTopicDrafts((current) => ({
                                  ...current,
                                  [item.topic.slug]: {
                                    ...(current[item.topic.slug] ?? buildTopicDraft(item.topic)),
                                    status: event.target.value,
                                  },
                                }))
                              }
                            >
                              <option value="pending">待建项目</option>
                              <option value="drafting">写作中</option>
                              <option value="approved">已确认</option>
                              <option value="dropped">已废弃</option>
                            </select>
                          </label>
                          <button
                            className="dashboard-button"
                            type="button"
                            disabled={
                              savingTopicSlug === item.topic.slug ||
                              !hasTopicDraftChanged(item.topic, topicDrafts[item.topic.slug] ?? buildTopicDraft(item.topic))
                            }
                            onClick={() => void handleSaveTopic(item.topic)}
                          >
                            {savingTopicSlug === item.topic.slug ? "保存中..." : "保存选题"}
                          </button>
                        </div>
                        <div className="workspace-note workspace-note--info">
                          <p>{`当前状态：${formatTopicStatusLabel(topicDrafts[item.topic.slug]?.status ?? item.topic.status)}`}</p>
                          <p>把状态切到“已废弃”后，会从 Topic Queue 中移出；切回“待建项目/写作中”会重新回到队列。</p>
                        </div>
                        <div className="workspace-section__header">
                          <div>
                            <p className="workspace-section__eyebrow">建项目配置</p>
                            <h4>标题、slug 与赛道</h4>
                            <p className="workspace-section__description">单条选题可直接建项目，不必先走批量入口。</p>
                          </div>
                        </div>
                      <div className="quick-form workspace-actions--row">
                          <label className="workspace-search workspace-search--compact">
                            <span>项目标题</span>
                            <input
                              value={projectDrafts[item.topic.slug]?.title ?? item.topic.title}
                              onChange={(event) =>
                                setProjectDrafts((current) => ({
                                  ...current,
                                  [item.topic.slug]: {
                                    ...(current[item.topic.slug] ?? buildProjectCreateDraft(item.topic, loadState.data.domainPacks)),
                                    title: event.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                          <label className="workspace-search workspace-search--compact">
                            <span>项目 slug</span>
                            <input
                              value={projectDrafts[item.topic.slug]?.slug ?? item.topic.slug}
                              onChange={(event) =>
                                setProjectDrafts((current) => ({
                                  ...current,
                                  [item.topic.slug]: {
                                    ...(current[item.topic.slug] ?? buildProjectCreateDraft(item.topic, loadState.data.domainPacks)),
                                    slug: event.target.value,
                                  },
                                }))
                              }
                            />
                          </label>
                          <label className="workspace-search workspace-search--compact">
                            <span>项目赛道</span>
                            <select
                              className="workspace-select"
                              value={projectDrafts[item.topic.slug]?.domain_pack_key ?? ""}
                              onChange={(event) =>
                                setProjectDrafts((current) => ({
                                  ...current,
                                  [item.topic.slug]: {
                                    ...(current[item.topic.slug] ?? buildProjectCreateDraft(item.topic, loadState.data.domainPacks)),
                                    domain_pack_key: event.target.value || null,
                                  },
                                }))
                              }
                            >
                              <option value="">跟随默认赛道</option>
                              {loadState.data.domainPacks.map((pack) => (
                                <option key={pack.key} value={pack.key}>
                                  {pack.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label className="workspace-search workspace-search--compact">
                            <span>项目风格</span>
                            <select
                              className="workspace-select"
                              value={
                                projectDrafts[item.topic.slug]?.preferred_tone_profile_id == null
                                  ? ""
                                  : String(projectDrafts[item.topic.slug]?.preferred_tone_profile_id)
                              }
                              onChange={(event) =>
                                setProjectDrafts((current) => ({
                                  ...current,
                                  [item.topic.slug]: {
                                    ...(current[item.topic.slug] ?? buildProjectCreateDraft(item.topic, loadState.data.domainPacks)),
                                    preferred_tone_profile_id: event.target.value ? Number.parseInt(event.target.value, 10) : null,
                                  },
                                }))
                              }
                            >
                              <option value="">跟随当前全局风格</option>
                              {loadState.data.toneProfiles.map((profile) => (
                                <option key={profile.id} value={profile.id}>
                                  {profile.name}
                                  {profile.is_active ? " · 当前全局" : ""}
                                </option>
                              ))}
                            </select>
                          </label>
                          <button
                            className="dashboard-button dashboard-button--ghost"
                            type="button"
                            disabled={creatingTopicSlug === item.topic.slug}
                            onClick={() => void handleCreateProject(item.topic)}
                          >
                            {creatingTopicSlug === item.topic.slug ? "创建中..." : "确认创建项目"}
                          </button>
                        </div>
                        <div className="workspace-note workspace-note--info">
                          {buildProjectConfigPreviewLines({
                            domainPacks: loadState.data.domainPacks,
                            domainPackKey: projectDrafts[item.topic.slug]?.domain_pack_key ?? null,
                            toneProfiles: loadState.data.toneProfiles,
                            toneProfileId: projectDrafts[item.topic.slug]?.preferred_tone_profile_id ?? null,
                          }).map((line) => (
                            <p key={line}>{line}</p>
                          ))}
                          <p>{`当前选择：${getToneProfileSelectionLabel(
                            projectDrafts[item.topic.slug]?.preferred_tone_profile_id ?? null,
                            loadState.data.toneProfiles,
                          )}`}</p>
                        </div>
                      </div>
                    ) : null}
                        </>
                      );
                    })()}
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      ) : null}

      {section === "runs" ? (
        <>
          <section className="workspace-section">
            <div className="workspace-section__header">
              <div>
                <p className="workspace-section__eyebrow">批量运行</p>
                <h4>批量推进入口</h4>
                <p className="workspace-section__description">所有会产生批量结果和异步任务状态的动作，都从这里发起与回看。</p>
              </div>
            </div>
            <div className="workspace-run-grid">
              {batchRunCards.map((card: BatchRunCard) => (
                <article key={card.key} className="workspace-run-card">
                  <div className="workspace-item__header">
                    <div>
                      <h4>{card.title}</h4>
                      <p>{card.description}</p>
                    </div>
                    <span className="workspace-run-card__count">{card.count}</span>
                  </div>
                  <button
                    className="dashboard-button"
                    type="button"
                    onClick={() => handleRunBatch(card.key)}
                    disabled={isSubmittingBatchRun}
                  >
                    {card.buttonLabel}
                  </button>
                </article>
              ))}
            </div>
          </section>

          <section className="workspace-section">
            <div className="workspace-section__header">
              <div>
                <p className="workspace-section__eyebrow">最近提交</p>
                <h4>最近一次批量提交</h4>
              </div>
            </div>
            {activeRun ? (
              <article className="workspace-item">
                <div className="workspace-item__header">
                  <div>
                    <h4>{getBatchRunJobTypeLabel(activeRun.submission.job_type)}</h4>
                    <p>{activeRun.submission.task_id}</p>
                  </div>
                  <span className="workspace-pill">
                    {activeRun.detail ? formatTaskStatusLabel(activeRun.detail.status as PipelineTaskStatus) : activeRun.submission.status}
                  </span>
                </div>
                <div className="workspace-item__meta">
                  <span>创建时间：{formatTimestampLabel(activeRun.submission.created_at)}</span>
                  <span>{activeRun.detail?.finished_at ? `完成时间：${formatTimestampLabel(activeRun.detail.finished_at)}` : "等待后台更新"}</span>
                </div>
                {batchRunSummaryLines.length > 0 ? (
                  <div className="workspace-tag-list">
                    {batchRunSummaryLines.map((line) => (
                      <span key={line} className="workspace-tag">
                        {line}
                      </span>
                    ))}
                  </div>
                ) : null}
              </article>
            ) : (
              <div className="dashboard-state dashboard-state--empty">
                <p className="dashboard-state__eyebrow">尚未提交</p>
                <h3>还没有新的批量提交</h3>
                <p>从上方四类批量入口中选择一个动作，提交后这里会持续显示最新状态。</p>
              </div>
            )}
          </section>

          <section className="workspace-section">
            <div className="workspace-section__header">
              <div>
                <p className="workspace-section__eyebrow">最近批量运行</p>
                <h4>最近批量任务</h4>
              </div>
              <Link className="dashboard-inline-link" to="/pipeline/tasks">
                打开任务日志
              </Link>
            </div>
            {pipelineState.batchRuns.items.length === 0 ? (
              <div className="dashboard-state dashboard-state--empty">
                <p className="dashboard-state__eyebrow">暂无数据</p>
                <h3>当前没有已记录的批量任务</h3>
                <p>发起一次批量推进后，最近的批量任务记录会出现在这里。</p>
              </div>
            ) : (
              <div className="workspace-list">
                {pipelineState.batchRuns.items.map((task) => (
                  <article key={String(task.id)} className="workspace-item">
                    <div className="workspace-item__header">
                      <div>
                        <h4>{getTaskTypeLabel(task.task_type)}</h4>
                        <p>{task.entity_slug ?? "批量任务"}</p>
                      </div>
                      <span className="workspace-pill">{formatTaskStatusLabel(task.normalizedStatus)}</span>
                    </div>
                    <div className="workspace-item__meta">
                      <span>{formatTimestampLabel(task.created_at)}</span>
                      <span>{task.canRetry ? "可重跑" : "已记录"}</span>
                      {typeof task.backgroundTaskFailedCount === "number" && task.backgroundTaskFailedCount > 0 ? (
                        <span>{`批内失败 ${task.backgroundTaskFailedCount} 项`}</span>
                      ) : null}
                    </div>
                    {task.backgroundTaskId && taskDetails[task.backgroundTaskId] ? (
                    <div className="workspace-tag-list">
                      {buildBackgroundTaskSummaryLines(taskDetails[task.backgroundTaskId] ?? null).map((line) => (
                        <span key={line} className="workspace-tag">
                          {line}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {renderBackgroundTaskDiagnostics(task.backgroundTaskId)}
                  {task.canRetry ? (
                    <div className="workspace-actions">
                      <button className="dashboard-button" type="button" onClick={() => void handleRetryTask(task.task_type)}>
                          {getBatchRetryLabel(task.task_type)}
                        </button>
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}

      {section === "tasks" ? (
        <section className="workspace-section">
          <div className="workspace-section__header">
            <div>
              <p className="workspace-section__eyebrow">Task Log</p>
              <h4>异步任务日志</h4>
              <p className="workspace-section__description">失败项留在 Pipeline 里集中归位，需要重跑时也从这里回到批量入口。</p>
            </div>
            <Link className="dashboard-inline-link" to="/pipeline/runs">
              回到批量运行
            </Link>
          </div>

          <div className="workspace-filter-row">
            {TASK_LOG_FILTERS.map((item) => (
              <button
                key={item.key}
                className={
                  item.key === taskLogFilter
                    ? "workspace-filter-button workspace-filter-button--active"
                    : "workspace-filter-button"
                }
                type="button"
                onClick={() => setTaskLogFilter(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>

          {pipelineState.taskLog.items.length === 0 ? (
            <div className="dashboard-state dashboard-state--empty">
              <p className="dashboard-state__eyebrow">暂无数据</p>
              <h3>当前筛选下没有任务日志</h3>
              <p>可以切换状态筛选，或先去批量运行发起一次新任务。</p>
            </div>
          ) : (
            <div className="workspace-list">
              {pipelineState.taskLog.items.map((task) => (
                <article key={String(task.id)} className="workspace-item">
                  <div className="workspace-item__header">
                    <div>
                      <h4>{getTaskTypeLabel(task.task_type)}</h4>
                      <p>{task.entity_slug ?? task.entity_type ?? "未知任务"}</p>
                    </div>
                      <span className="workspace-pill">{formatTaskStatusLabel(task.normalizedStatus)}</span>
                    </div>
                  <div className="workspace-item__meta">
                    <span>{formatTimestampLabel(task.created_at)}</span>
                    <span>{task.canRetry ? "失败项待重跑" : "批量任务记录"}</span>
                    {typeof task.backgroundTaskFailedCount === "number" && task.backgroundTaskFailedCount > 0 ? (
                      <span>{`批内失败 ${task.backgroundTaskFailedCount} 项`}</span>
                    ) : null}
                  </div>
                  {task.backgroundTaskId && taskDetails[task.backgroundTaskId] ? (
                    <div className="workspace-tag-list">
                      {buildBackgroundTaskSummaryLines(taskDetails[task.backgroundTaskId] ?? null).map((line) => (
                        <span key={line} className="workspace-tag">
                          {line}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {renderBackgroundTaskDiagnostics(task.backgroundTaskId)}
                  <div className="workspace-actions">
                    {task.canRetry ? (
                      <button
                        className="dashboard-button"
                        type="button"
                        onClick={() => void handleRetryTask(task.task_type)}
                        disabled={isSubmittingBatchRun}
                      >
                        {getBatchRetryLabel(task.task_type)}
                      </button>
                    ) : null}
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}
    </section>
  );
}
