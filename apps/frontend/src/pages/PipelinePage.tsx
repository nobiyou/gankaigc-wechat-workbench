import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  batchContinueProjects,
  batchCreateProjects,
  batchGenerateTopics,
  batchGenerateTopicsFromTrackedArticles,
  fetchBackgroundTask,
  fetchDashboardSummary,
  fetchProjects,
  fetchTopics,
  fetchTrackedArticles,
  fetchTrends,
  type BackgroundTaskDetail,
  type BackgroundTaskSubmission,
  type DashboardSummary,
  type ProjectItem,
  type TopicItem,
  type TrackedArticleItem,
  type TrendItem,
} from "../api/workbench";
import { getTaskTypeLabel } from "../taskLabels";
import { buildBackgroundTaskSummaryLines } from "../view-models/backgroundTaskSummaries";
import {
  buildBatchRunCards,
  buildPipelineViewsState,
  type BatchRunCard,
  type BatchRunCardKey,
  type PipelineTaskLogFilter,
  type PipelineTaskStatus,
} from "../view-models/pipelineViews";

type PipelineSection = "topics" | "runs" | "tasks";

type PipelineData = {
  summary: DashboardSummary;
  topics: TopicItem[];
  projects: ProjectItem[];
  trends: TrendItem[];
  trackedArticles: TrackedArticleItem[];
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

function loadPipelineData(): Promise<PipelineData> {
  return Promise.all([
    fetchDashboardSummary(),
    fetchTopics(),
    fetchProjects(),
    fetchTrends(),
    fetchTrackedArticles(),
  ]).then(([summary, topics, projects, trends, trackedArticles]) => ({
    summary,
    topics,
    projects,
    trends,
    trackedArticles,
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

export function PipelinePage({ section }: { section: PipelineSection }) {
  const [loadState, setLoadState] = useState<PipelineLoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);
  const [taskLogFilter, setTaskLogFilter] = useState<PipelineTaskLogFilter>("all");
  const [activeRun, setActiveRun] = useState<BatchRunTaskState | null>(null);
  const [taskDetails, setTaskDetails] = useState<Record<string, BackgroundTaskDetail | null>>({});
  const [taskDetailErrors, setTaskDetailErrors] = useState<Record<string, string | null>>({});
  const [runMessage, setRunMessage] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;
    setLoadState({ status: "loading" });

    loadPipelineData()
      .then((data) => {
        if (!isCancelled) {
          setLoadState({ status: "ready", data });
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
      return;
    }

    const pipelineState = buildPipelineViewsState({
      topics: loadState.data.topics,
      projects: loadState.data.projects,
      recentTasks: loadState.data.summary.recent_tasks,
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
    recentTasks: loadState.data.summary.recent_tasks,
    taskLogFilter,
    backgroundTaskDetails: taskDetails,
  });
  const batchRunCards = buildBatchRunCards({
    trends: loadState.data.trends,
    trackedArticles: loadState.data.trackedArticles,
    topics: loadState.data.topics,
    projects: loadState.data.projects,
  });
  const batchRunSummaryLines = buildBackgroundTaskSummaryLines(activeRun?.detail ?? null);
  const isSubmittingBatchRun = activeRun?.detail?.status === "queued" || activeRun?.detail?.status === "running";

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
            <Link className="dashboard-inline-link" to="/pipeline/runs">
              去批量建项目
            </Link>
          </div>

          {pipelineState.topicQueue.items.length === 0 ? (
            <div className="dashboard-state dashboard-state--empty">
              <p className="dashboard-state__eyebrow">暂无数据</p>
              <h3>当前没有待处理选题队列</h3>
              <p>可以回到 Sources 生成单条选题，或去批量运行启动新一轮批量推进。</p>
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
              <div className="workspace-list">
                {pipelineState.topicQueue.items.map((item) => (
                  <article key={item.topic.slug} className="workspace-item">
                    <div className="workspace-item__header">
                      <div>
                        <h4>{item.topic.title}</h4>
                        <p>{item.topic.slug}</p>
                      </div>
                      <span className="workspace-pill">{item.topic.status}</span>
                    </div>
                    <div className="workspace-item__meta">
                      <span>{item.sourceLabel}</span>
                      <span>{item.topic.angle}</span>
                    </div>
                    <div className="workspace-actions">
                      <Link className="dashboard-inline-link" to="/pipeline/runs">
                        去批量建项目
                      </Link>
                    </div>
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
                  {task.backgroundTaskId && taskDetailErrors[task.backgroundTaskId] ? (
                    <div className="workspace-note workspace-note--error">
                      <p>{taskDetailErrors[task.backgroundTaskId]}</p>
                    </div>
                  ) : null}
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
