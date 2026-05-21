import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { fetchProjects } from "../api/workbench";
import { formatProjectChainStateLabel, formatProjectNextStepLabel } from "../projectStatus";
import { buildProjectGroups } from "../view-models/projectGroups";
import { buildProjectWorkbenchTarget } from "../view-models/workbenchStages";

type ProjectsLoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; projects: Awaited<ReturnType<typeof fetchProjects>> };

export function ProjectsPage() {
  const [loadState, setLoadState] = useState<ProjectsLoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);
  const [query, setQuery] = useState("");
  const [owner, setOwner] = useState("");

  useEffect(() => {
    let isCancelled = false;
    setLoadState({ status: "loading" });

    fetchProjects()
      .then((projects) => {
        if (!isCancelled) {
          setLoadState({ status: "ready", projects });
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "Projects 数据加载失败。",
          });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [reloadToken]);

  const ownerOptions = useMemo(() => {
    if (loadState.status !== "ready") {
      return [];
    }
    return [...new Set(loadState.projects.map((project) => project.owner).filter(Boolean))];
  }, [loadState]);

  if (loadState.status === "loading") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--loading">
          <p className="dashboard-state__eyebrow">加载中</p>
          <h3>正在加载 Projects</h3>
          <p>正在同步项目分组、链路状态与 Workbench 入口。</p>
        </div>
      </section>
    );
  }

  if (loadState.status === "error") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--error">
          <p className="dashboard-state__eyebrow">加载失败</p>
          <h3>Projects 加载失败</h3>
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

  const groups = buildProjectGroups({
    projects: loadState.projects,
    filters: {
      query,
      owner: owner || null,
    },
  });

  return (
    <section className="workspace-page">
      <section className="workspace-section">
        <div className="workspace-section__header">
          <div>
            <p className="workspace-section__eyebrow">Projects</p>
            <h3>项目分组与 Workbench 入口</h3>
            <p className="workspace-section__description">
              这里负责项目管理和分组筛选，单项目生产则进入专属 Workbench，不再挤在单页底部。
            </p>
          </div>
        </div>
        <div className="workspace-summary-grid">
          <article className="workspace-summary-card">
            <span>项目总数</span>
            <strong>{loadState.projects.length}</strong>
          </article>
          <article className="workspace-summary-card">
            <span>当前分组</span>
            <strong>{groups.length}</strong>
            <p>仅展示有项目的生产分组。</p>
          </article>
        </div>
      </section>

      <section className="workspace-section">
        <div className="workspace-toolbar">
          <label className="workspace-search">
            <span>搜索项目</span>
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="按标题、slug、topic slug 或链路状态筛选"
            />
          </label>
          <label className="workspace-search">
            <span>负责人</span>
            <select className="workspace-select" value={owner} onChange={(event) => setOwner(event.target.value)}>
              <option value="">全部负责人</option>
              {ownerOptions.map((item) => (
                <option key={item} value={item}>
                  {item}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>

      {groups.length === 0 ? (
        <div className="dashboard-state dashboard-state--empty">
          <p className="dashboard-state__eyebrow">暂无结果</p>
          <h3>当前筛选下没有项目</h3>
          <p>可以清空搜索条件，或先去 Pipeline / 选题队列 把选题推进成项目。</p>
        </div>
      ) : (
        groups.map((group) => (
          <section key={group.groupKey} className="workspace-section">
            <div className="workspace-section__header">
              <div>
                <p className="workspace-section__eyebrow">项目分组</p>
                <h4>{group.title}</h4>
                <p className="workspace-section__description">{group.filterHint}</p>
              </div>
              <span className="workspace-run-card__count">{group.count}</span>
            </div>

            <div className="workspace-list">
              {group.projects.map((project) => (
                <article key={project.slug} className="workspace-item">
                  <div className="workspace-item__header">
                    <div>
                      <h4>{project.title}</h4>
                      <p>{project.slug}</p>
                    </div>
                    <span className="workspace-pill">{formatProjectChainStateLabel(project.current_chain_state)}</span>
                  </div>
                  <div className="workspace-item__meta">
                    <span>{`选题：${project.topic_slug}`}</span>
                    <span>{`负责人：${project.owner}`}</span>
                    <span>{`下一步：${formatProjectNextStepLabel(project.next_required_step)}`}</span>
                  </div>
                  <div className="workspace-actions">
                    <Link className="dashboard-inline-link" to={buildProjectWorkbenchTarget(project)}>
                      打开 Workbench
                    </Link>
                  </div>
                </article>
              ))}
            </div>
          </section>
        ))
      )}
    </section>
  );
}
