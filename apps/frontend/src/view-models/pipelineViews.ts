import type { ProjectItem, TaskLogItem, TopicItem, TrackedArticleItem, TrendItem } from "../api/workbench";
// @ts-ignore TS5097: the local test harness executes raw .ts modules via Node.
import { buildTopicQueueTopics, buildTrendQueueTrends } from "./dashboardQueues.ts";
// @ts-ignore TS5097: the local test harness executes raw .ts modules via Node.
import { buildPendingTrackedArticles, formatTopicSourceLabel } from "../contentSources.ts";

export type RecentTaskItem = TaskLogItem;
export type PipelineTaskStatus = "done" | "running" | "failed" | "skipped";
export type PipelineTaskLogFilter = "all" | "done" | "running" | "failed" | "skipped";
export type TopicSourceFilter = "all" | "trend" | "tracked_article" | "manual";

export type TopicQueueItem = {
  topic: TopicItem;
  sourceLabel: string;
  targetPath: string;
};

export type PipelineTaskItem = RecentTaskItem & {
  normalizedStatus: PipelineTaskStatus;
  canRetry: boolean;
  isBatchRun: boolean;
  backgroundTaskId: string | null;
  backgroundTaskFailedCount: number | null;
};

export type PipelineTaskSummary = {
  total: number;
  done: number;
  running: number;
  failed: number;
  skipped: number;
};

export type PipelineViewsState = {
  topicQueue: {
    items: TopicQueueItem[];
    statusSummary: {
      total: number;
      pending: number;
      drafting: number;
    };
    sourceSummary: {
      all: number;
      trend: number;
      tracked_article: number;
      manual: number;
    };
    filter: TopicSourceFilter;
  };
  batchRuns: {
    items: PipelineTaskItem[];
    statusSummary: PipelineTaskSummary;
  };
  taskLog: {
    items: PipelineTaskItem[];
    statusSummary: PipelineTaskSummary;
    filter: PipelineTaskLogFilter;
  };
};

export type BatchRunCardKey =
  | "generate-trend-topics"
  | "generate-article-topics"
  | "create-projects"
  | "continue-projects";

export type BatchRunCard = {
  key: BatchRunCardKey;
  title: string;
  description: string;
  count: number;
  buttonLabel: string;
};

const PIPELINE_BATCH_TASK_TYPES = new Set([
  "batch_continue_projects",
  "batch_create_projects",
  "batch_generate_topics",
  "batch_generate_topics_from_tracked_articles",
]);

function normalizeTaskStatus(status?: string): PipelineTaskStatus {
  const normalized = status?.trim().toLowerCase() ?? "";
  if (normalized === "done" || normalized === "success" || normalized === "succeeded" || normalized === "completed") {
    return "done";
  }
  if (normalized === "failed" || normalized === "error") {
    return "failed";
  }
  if (normalized === "skipped") {
    return "skipped";
  }
  return "running";
}

function isBatchRunTask(task: RecentTaskItem): boolean {
  return task.entity_type === "batch" || (task.task_type?.toLowerCase().includes("batch") ?? false);
}

function isPipelineOwnedTask(task: RecentTaskItem): boolean {
  if (task.entity_type === "batch") {
    return true;
  }

  const taskType = task.task_type?.trim().toLowerCase();
  return taskType ? PIPELINE_BATCH_TASK_TYPES.has(taskType) : false;
}

function getCreatedAtTime(createdAt?: string): number {
  if (!createdAt) {
    return 0;
  }

  const timestamp = Date.parse(createdAt);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function compareCreatedAtDesc(left: RecentTaskItem, right: RecentTaskItem): number {
  const leftTime = getCreatedAtTime(left.created_at);
  const rightTime = getCreatedAtTime(right.created_at);
  return rightTime - leftTime;
}

function summarizeTasks(tasks: PipelineTaskItem[]): PipelineTaskSummary {
  return tasks.reduce(
    (summary, task) => {
      summary.total += 1;
      summary[task.normalizedStatus] += 1;
      return summary;
    },
    { total: 0, done: 0, running: 0, failed: 0, skipped: 0 },
  );
}

export function buildPipelineViewsState({
  topics,
  projects,
  recentTasks,
  taskLogFilter = "all",
  topicSourceFilter = "all",
  backgroundTaskDetails = {},
}: {
  topics: TopicItem[];
  projects: ProjectItem[];
  recentTasks: RecentTaskItem[];
  taskLogFilter?: PipelineTaskLogFilter;
  topicSourceFilter?: TopicSourceFilter;
  backgroundTaskDetails?: Record<string, { result: Record<string, unknown> | null } | null>;
}): PipelineViewsState {
  const topicQueueTopics = buildTopicQueueTopics({ topics, projects });
  const allTopicQueueItems = topicQueueTopics.map((topic) => ({
    topic,
    sourceLabel: formatTopicSourceLabel(topic),
    targetPath: `/pipeline/topics?topic=${encodeURIComponent(topic.slug)}`,
  }));
  const topicQueueItems =
    topicSourceFilter === "all"
      ? allTopicQueueItems
      : allTopicQueueItems.filter((item) => item.topic.source_type === topicSourceFilter);

  const allTaskItems = [...recentTasks]
    .sort(compareCreatedAtDesc)
    .map((task) => {
      const backgroundTaskId = task.background_task_id ?? null;
      const backgroundTaskResult = backgroundTaskId ? backgroundTaskDetails[backgroundTaskId]?.result : null;
      const failedCount =
        backgroundTaskResult && typeof backgroundTaskResult.failed_count === "number"
          ? backgroundTaskResult.failed_count
          : null;
      const normalizedStatus =
        failedCount !== null && failedCount > 0 ? "failed" : normalizeTaskStatus(task.status);

      return {
        ...task,
        normalizedStatus,
        canRetry: normalizedStatus === "failed",
        isBatchRun: isBatchRunTask(task),
        backgroundTaskId,
        backgroundTaskFailedCount: failedCount,
      };
    });

  const batchRunItems = allTaskItems.filter((task) => task.isBatchRun);
  const pipelineOwnedTaskItems = allTaskItems.filter((task) => isPipelineOwnedTask(task));
  const taskLogItems =
    taskLogFilter === "all"
      ? pipelineOwnedTaskItems
      : pipelineOwnedTaskItems.filter((task) => task.normalizedStatus === taskLogFilter);

  return {
    topicQueue: {
      items: topicQueueItems,
      statusSummary: {
        total: topicQueueItems.length,
        pending: topicQueueItems.filter((item) => item.topic.status === "pending").length,
        drafting: topicQueueItems.filter((item) => item.topic.status === "drafting").length,
      },
      sourceSummary: {
        all: allTopicQueueItems.length,
        trend: allTopicQueueItems.filter((item) => item.topic.source_type === "trend").length,
        tracked_article: allTopicQueueItems.filter((item) => item.topic.source_type === "tracked_article").length,
        manual: allTopicQueueItems.filter((item) => item.topic.source_type === "manual").length,
      },
      filter: topicSourceFilter,
    },
    batchRuns: {
      items: batchRunItems,
      statusSummary: summarizeTasks(batchRunItems),
    },
    taskLog: {
      items: taskLogItems,
      statusSummary: summarizeTasks(taskLogItems),
      filter: taskLogFilter,
    },
  };
}

export function buildBatchRunCards({
  trends,
  trackedArticles,
  topics,
  projects,
}: {
  trends: TrendItem[];
  trackedArticles: TrackedArticleItem[];
  topics: TopicItem[];
  projects: ProjectItem[];
}): BatchRunCard[] {
  const queuedTrends = buildTrendQueueTrends({ trends, topics });
  const pendingArticles = buildPendingTrackedArticles({ trackedArticles, topics });
  const topicQueueTopics = buildTopicQueueTopics({ topics, projects });
  const continuableProjects = projects.filter((project) => Boolean(project.next_required_step));

  return [
    {
      key: "generate-trend-topics",
      title: "趋势转选题",
      description: "把仍处于 screening 的热点批量推进为选题。",
      count: queuedTrends.length,
      buttonLabel: "批量转选题",
    },
    {
      key: "generate-article-topics",
      title: "参考文章转选题",
      description: "把尚未转成选题的 tracked articles 批量生成 Topic Queue。",
      count: pendingArticles.length,
      buttonLabel: "批量转选题",
    },
    {
      key: "create-projects",
      title: "选题建项目",
      description: "把 Topic Queue 中待建项目选题批量转成生产项目。",
      count: topicQueueTopics.length,
      buttonLabel: "批量建项目",
    },
    {
      key: "continue-projects",
      title: "项目续链",
      description: "对仍有 next step 的项目统一发起批量续链。",
      count: continuableProjects.length,
      buttonLabel: "批量续链",
    },
  ];
}
