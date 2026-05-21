import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  fetchDashboardSummary,
  fetchProjects,
  fetchTopics,
  fetchTrends,
  type DashboardSummary,
} from "../api/workbench";
import { buildDashboardRecentTaskViews } from "../view-models/dashboardRecentTasks";
import { buildDashboardQueueCards, buildDashboardQueueState } from "../view-models/dashboardQueues";

type DashboardData = {
  summary: DashboardSummary;
  projects: Awaited<ReturnType<typeof fetchProjects>>;
  topics: Awaited<ReturnType<typeof fetchTopics>>;
  trends: Awaited<ReturnType<typeof fetchTrends>>;
};

type DashboardLoadState =
  | {
      status: "loading";
    }
  | {
      status: "error";
      message: string;
    }
  | {
      status: "ready";
      data: DashboardData;
    };

const QUICK_LINKS = [
  { label: "补充热点素材", description: "回到 Sources 处理热点与参考输入。", to: "/sources/trends" },
  { label: "清理选题队列", description: "把待建项目选题推进到 Pipeline。", to: "/pipeline/topics" },
  { label: "查看项目列表", description: "进入 Projects 聚焦项目管理和链路推进。", to: "/projects" },
] as const;

function loadDashboardData(): Promise<DashboardData> {
  return Promise.all([fetchDashboardSummary(), fetchTrends(), fetchTopics(), fetchProjects()]).then(
    ([summary, trends, topics, projects]) => ({
      summary,
      trends,
      topics,
      projects,
    }),
  );
}

function formatCount(count: number): string {
  return `${count} 项`;
}

export function DashboardPage() {
  const [loadState, setLoadState] = useState<DashboardLoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let isCancelled = false;
    setLoadState({ status: "loading" });

    loadDashboardData()
      .then((data) => {
        if (!isCancelled) {
          setLoadState({ status: "ready", data });
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "Dashboard 数据加载失败。",
          });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [reloadToken]);

  if (loadState.status === "loading") {
    return (
      <section className="dashboard-page">
        <div className="dashboard-state dashboard-state--loading">
          <p className="dashboard-state__eyebrow">加载中</p>
          <h3>正在加载今日任务面板</h3>
          <p>正在同步待办队列、项目状态和最近任务摘要。</p>
        </div>
      </section>
    );
  }

  if (loadState.status === "error") {
    return (
      <section className="dashboard-page">
        <div className="dashboard-state dashboard-state--error">
          <p className="dashboard-state__eyebrow">加载失败</p>
          <h3>Dashboard 加载失败</h3>
          <p>{loadState.message}</p>
          <div className="dashboard-state__actions">
            <button className="dashboard-button" type="button" onClick={() => setReloadToken((value) => value + 1)}>
              重新加载
            </button>
            <Link className="dashboard-button dashboard-button--ghost" to="/pipeline/tasks">
              先看任务日志
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const queueState = buildDashboardQueueState(loadState.data);
  const queueCards = buildDashboardQueueCards(queueState);
  const recentTasks = buildDashboardRecentTaskViews(loadState.data.summary.recent_tasks);
  const hasActionableQueues = queueCards.some((card) => card.count > 0);
  const isEmpty = !hasActionableQueues && recentTasks.length === 0;

  return (
    <section className="dashboard-page">
      {isEmpty ? (
        <div className="dashboard-state dashboard-state--empty">
          <p className="dashboard-state__eyebrow">当前空闲</p>
          <h3>当前没有待处理队列</h3>
          <p>今天的首页没有发现待发布、待续链、待建项目选题或待转选题热点。可以从下面入口主动开始新一轮工作。</p>
        </div>
      ) : null}

      <div className="dashboard-layout">
        <div className="dashboard-primary">
          <section className="dashboard-section">
            <div className="dashboard-section__header">
              <div>
                <p className="dashboard-section__eyebrow">Queues</p>
                <h4>待办队列</h4>
                <p className="dashboard-section__description">
                  首页优先只放今天最该推进的入口，先处理待发布、待续链、待建项目选题，再回头看概览统计。
                </p>
              </div>
              <Link className="dashboard-inline-link" to="/projects">
                查看全部项目
              </Link>
            </div>
            <div className="dashboard-card-grid">
              {queueCards.map((card) => (
                <article
                  key={card.key}
                  className={`dashboard-queue-card dashboard-queue-card--${card.tone}`}
                  aria-label={`${card.title} ${card.count} 项`}
                >
                  <div className="dashboard-queue-card__header">
                    <h5>{card.title}</h5>
                    <span className="dashboard-queue-card__count">{card.count}</span>
                  </div>
                  <p>{card.summary}</p>
                  <Link className="dashboard-inline-link" to={card.targetPath}>
                    打开入口
                  </Link>
                </article>
              ))}
            </div>
          </section>
        </div>

        <aside className="dashboard-secondary">
          <section className="dashboard-section dashboard-section--compact">
            <div className="dashboard-section__header">
              <div>
                <p className="dashboard-section__eyebrow">Summary</p>
                <h4>概览摘要</h4>
              </div>
            </div>
            <div className="dashboard-metrics" aria-label="Dashboard summary">
              <article className="dashboard-metric">
                <span className="dashboard-metric__label">今日热点</span>
                <strong>{formatCount(loadState.data.summary.today_trends)}</strong>
              </article>
              <article className="dashboard-metric">
                <span className="dashboard-metric__label">待写选题</span>
                <strong>{formatCount(loadState.data.summary.pending_topics)}</strong>
              </article>
              <article className="dashboard-metric">
                <span className="dashboard-metric__label">待精修稿件</span>
                <strong>{formatCount(loadState.data.summary.draft_ready_projects)}</strong>
              </article>
              <article className="dashboard-metric">
                <span className="dashboard-metric__label">待发布项目</span>
                <strong>{formatCount(loadState.data.summary.publish_ready_projects)}</strong>
              </article>
            </div>
          </section>

          <section className="dashboard-section dashboard-section--compact">
            <div className="dashboard-section__header">
              <div>
                <p className="dashboard-section__eyebrow">Recent</p>
                <h4>最近任务摘要</h4>
              </div>
              <Link className="dashboard-inline-link" to="/pipeline/tasks">
                打开任务日志
              </Link>
            </div>
            {recentTasks.length > 0 ? (
              <div className="dashboard-task-list">
                {recentTasks.map((task) => (
                  <article key={task.id} className="dashboard-task-item">
                    <div className="dashboard-task-item__meta">
                      <span className="dashboard-task-item__status">{task.statusLabel}</span>
                      <span>{task.timestampLabel}</span>
                    </div>
                    <h5>{task.label}</h5>
                    <p>{task.targetHint}</p>
                    <Link className="dashboard-inline-link" to={task.targetPath}>
                      {task.targetLabel}
                    </Link>
                  </article>
                ))}
              </div>
            ) : (
              <div className="dashboard-panel-note">
                <p>最近没有可展示的任务摘要，任务日志会在后台任务产生后自动补齐。</p>
              </div>
            )}
          </section>

          <section className="dashboard-section dashboard-section--compact">
            <div className="dashboard-section__header">
              <div>
                <p className="dashboard-section__eyebrow">Entrypoints</p>
                <h4>快速入口</h4>
              </div>
            </div>
            <div className="dashboard-link-list">
              {QUICK_LINKS.map((item) => (
                <Link key={item.to} className="dashboard-link-card" to={item.to}>
                  <strong>{item.label}</strong>
                  <span>{item.description}</span>
                </Link>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </section>
  );
}
