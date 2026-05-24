import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import {
  fetchDomainPacks,
  fetchProjects,
  fetchToneProfiles,
  updateProject,
  type DomainPackSummary,
  type ToneProfileItem,
} from "../api/workbench";
import { formatProjectDomainPackLabel } from "../domainPacks";
import { formatProjectChainStateLabel, formatProjectNextStepLabel } from "../projectStatus";
import { buildProjectConfigPreviewLines } from "../projectConfigPreview";
import { formatProjectToneProfileLabel, hasProjectToneProfileSelectionChanged } from "../toneProfiles";
import { buildProjectGroups } from "../view-models/projectGroups";
import { buildProjectWorkbenchTarget } from "../view-models/workbenchStages";

type ProjectsLoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      projects: Awaited<ReturnType<typeof fetchProjects>>;
      domainPacks: DomainPackSummary[];
      toneProfiles: ToneProfileItem[];
    };

export function ProjectsPage() {
  const [loadState, setLoadState] = useState<ProjectsLoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);
  const [query, setQuery] = useState("");
  const [owner, setOwner] = useState("");
  const [domainDrafts, setDomainDrafts] = useState<Record<string, string>>({});
  const [toneProfileDrafts, setToneProfileDrafts] = useState<Record<string, string>>({});
  const [expandedProjectSlug, setExpandedProjectSlug] = useState<string | null>(null);
  const [savingProjectSlug, setSavingProjectSlug] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    let isCancelled = false;
    setLoadState({ status: "loading" });

    Promise.all([fetchProjects(), fetchDomainPacks(), fetchToneProfiles()])
      .then(([projects, domainPacks, toneProfiles]) => {
        if (!isCancelled) {
          setLoadState({ status: "ready", projects, domainPacks, toneProfiles });
          setDomainDrafts(
            Object.fromEntries(projects.map((project) => [project.slug, project.domain_pack_key ?? ""])),
          );
          setToneProfileDrafts(
            Object.fromEntries(
              projects.map((project) => [project.slug, project.preferred_tone_profile_id == null ? "" : String(project.preferred_tone_profile_id)]),
            ),
          );
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

  async function handleSaveProjectConfig(projectSlug: string, stage: string) {
    if (loadState.status !== "ready") {
      return;
    }

    try {
      setSavingProjectSlug(projectSlug);
      setActionError(null);
      setActionMessage(null);
      const nextDomainPackKey = domainDrafts[projectSlug] || null;
      const nextToneProfileIdRaw = toneProfileDrafts[projectSlug] ?? "";
      const nextToneProfileId = nextToneProfileIdRaw ? Number.parseInt(nextToneProfileIdRaw, 10) : null;
      const updatedProject = await updateProject(projectSlug, {
        stage,
        domain_pack_key: nextDomainPackKey,
        preferred_tone_profile_id: nextToneProfileId,
      });
      setLoadState({
        ...loadState,
        projects: loadState.projects.map((project) => (project.slug === projectSlug ? updatedProject : project)),
      });
      setActionMessage(`已更新项目配置：${updatedProject.title}`);
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "更新项目配置失败。");
    } finally {
      setSavingProjectSlug(null);
    }
  }

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

      {actionMessage ? <div className="workspace-note workspace-note--success"><p>{actionMessage}</p></div> : null}
      {actionError ? <div className="workspace-note workspace-note--error"><p>{actionError}</p></div> : null}

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
                    <span>{formatProjectDomainPackLabel(project, loadState.domainPacks)}</span>
                    <span>{formatProjectToneProfileLabel(project)}</span>
                  </div>
                  <div className="workspace-actions">
                    <button
                      className="dashboard-button dashboard-button--ghost"
                      type="button"
                      onClick={() => setExpandedProjectSlug((current) => (current === project.slug ? null : project.slug))}
                    >
                      {expandedProjectSlug === project.slug ? "收起配置" : "项目配置"}
                    </button>
                    <Link className="dashboard-inline-link" to={buildProjectWorkbenchTarget(project)}>
                      打开 Workbench
                    </Link>
                  </div>
                  {expandedProjectSlug === project.slug ? (
                    <div className="workspace-subsection workspace-project-config-panel">
                      <div className="workspace-section__header">
                        <div>
                          <p className="workspace-section__eyebrow">项目配置</p>
                          <h4>赛道与风格</h4>
                          <p className="workspace-section__description">这里集中管理项目级赛道和项目绑定风格。</p>
                        </div>
                      </div>
                      <div className="workspace-actions workspace-actions--row workspace-actions--project-config">
                        <label className="workspace-search workspace-search--compact">
                          <span>项目风格</span>
                          <select
                            className="workspace-select"
                            value={toneProfileDrafts[project.slug] ?? ""}
                            onChange={(event) =>
                              setToneProfileDrafts((current) => ({
                                ...current,
                                [project.slug]: event.target.value,
                              }))
                            }
                          >
                            <option value="">跟随全局风格</option>
                            {loadState.toneProfiles.map((profile) => (
                              <option key={profile.id} value={String(profile.id)}>
                                {profile.name}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label className="workspace-search workspace-search--compact">
                          <span>项目赛道</span>
                          <select
                            className="workspace-select"
                            value={domainDrafts[project.slug] ?? ""}
                            onChange={(event) =>
                              setDomainDrafts((current) => ({
                                ...current,
                                [project.slug]: event.target.value,
                              }))
                            }
                          >
                            <option value="">跟随默认赛道</option>
                            {loadState.domainPacks.map((pack) => (
                              <option key={pack.key} value={pack.key}>
                                {pack.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <button
                          className="dashboard-button dashboard-button--ghost"
                          type="button"
                          disabled={
                            savingProjectSlug === project.slug ||
                            (!hasProjectToneProfileSelectionChanged(
                              project,
                              (toneProfileDrafts[project.slug] ?? "") ? Number.parseInt(toneProfileDrafts[project.slug] ?? "", 10) : null,
                            ) &&
                              (project.domain_pack_key ?? "") === (domainDrafts[project.slug] ?? ""))
                          }
                          onClick={() => void handleSaveProjectConfig(project.slug, project.stage)}
                        >
                          {savingProjectSlug === project.slug ? "保存中..." : "保存配置"}
                        </button>
                      </div>
                      <div className="workspace-note workspace-note--info">
                        {buildProjectConfigPreviewLines({
                          domainPacks: loadState.domainPacks,
                          domainPackKey: (domainDrafts[project.slug] || null),
                          toneProfiles: loadState.toneProfiles,
                          toneProfileId: (toneProfileDrafts[project.slug] ?? "") ? Number.parseInt(toneProfileDrafts[project.slug] ?? "", 10) : null,
                        }).map((line) => (
                          <p key={line}>{line}</p>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </article>
              ))}
            </div>
          </section>
        ))
      )}
    </section>
  );
}
