import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";

import {
  approvePublishPackage,
  fetchBackgroundTask,
  buildPublishPackage,
  fetchProjectDetail,
  fetchProjectVersions,
  generateAssets,
  generateDraft,
  generateOutline,
  polishDraft,
  recordProjectRetro,
  regenerateFromReview,
  requestPublishRevision,
  restoreAssetsVersion,
  restoreDraftVersion,
  restoreOutlineVersion,
  restorePublishPackageVersion,
  type BackgroundTaskDetail,
  type BackgroundTaskSubmission,
  type ProjectDetail,
  type ProjectRetroCreatePayload,
  type ProjectVersions,
} from "../api/workbench";
import { WORKBENCH_STAGES, type WorkbenchStage } from "../app/navigation";
import { formatProjectChainStateLabel, formatProjectNextStepLabel } from "../projectStatus";
import { buildRetroDraft } from "../retroDraft";
import { buildWorkbenchActionPlan, type WorkbenchActionKind } from "../view-models/workbenchActions";
import { buildWorkbenchHistoryEntries, buildWorkbenchHistoryGroups, formatPublishStatusLabel } from "../view-models/workbenchHistory";
import { buildWorkbenchStageViews, resolveRecommendedWorkbenchStage } from "../view-models/workbenchStages";

type WorkbenchLoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; detail: ProjectDetail; versions: ProjectVersions };

function buildStageContent(stage: WorkbenchStage, detail: ProjectDetail): { title: string; body: string; meta: string[] } {
  if (stage === "topic") {
    return {
      title: detail.project.title,
      body: `选题 slug：${detail.project.topic_slug}`,
      meta: [
        `链路状态：${formatProjectChainStateLabel(detail.project.current_chain_state)}`,
        detail.project.preferred_tone_profile_name ? `风格：${detail.project.preferred_tone_profile_name}` : "风格：默认",
      ],
    };
  }
  if (stage === "outline") {
    return {
      title: detail.outline?.hook ?? "还没有大纲",
      body: detail.outline?.outline_body ?? "当前项目还没有生成大纲，可以从推荐步骤继续推进。",
      meta: [
        detail.outline ? `版本：v${detail.outline.version}` : "未生成",
        `下一步：${formatProjectNextStepLabel(detail.project.next_required_step)}`,
      ],
    };
  }
  if (stage === "draft") {
    return {
      title: detail.draft?.title ?? "还没有初稿",
      body: detail.draft?.body_markdown ?? "当前项目还没有初稿，可以先回到大纲或继续推荐步骤。",
      meta: [
        detail.draft ? `字数：${detail.draft.word_count}` : "未生成",
        `下一步：${formatProjectNextStepLabel(detail.project.next_required_step)}`,
      ],
    };
  }
  if (stage === "assets") {
    return {
      title: detail.assets?.title_options[0] ?? "还没有素材包",
      body: detail.assets?.cover_copy ?? "当前项目还没有素材包，可在生成后回到这里查看标题与封面文案。",
      meta: [detail.assets ? `版本：v${detail.assets.version}` : "未生成", detail.assets?.social_teaser ?? "暂无分发导语"],
    };
  }

  const latestReviewedPublishPackage = detail.project.current_publish_package_version == null ? detail.publish_package : null;

  return {
    title:
      detail.publish_package?.abstract ??
      (latestReviewedPublishPackage?.abstract ??
      (detail.project.stage === "revision_requested" || detail.project.current_chain_state !== "published"
        ? "审核后正在回退重生成"
        : "还没有发布包")),
    body:
      detail.publish_package?.editor_note ??
      (latestReviewedPublishPackage?.editor_note ??
      (detail.project.stage === "revision_requested"
        ? "当前项目已收到审核修改意见，系统正在沿着初稿 -> 素材 -> 发布包链路重新生成，完成后会回到这里继续审核。"
        : "Publish 阶段会集中承接发布包、审核状态和打回反馈。")),
    meta: [
      detail.publish_package
        ? `状态：${formatPublishStatusLabel(detail.publish_package.status)}`
        : latestReviewedPublishPackage
          ? `状态：${formatPublishStatusLabel(latestReviewedPublishPackage.status)}`
          : detail.project.stage === "revision_requested"
          ? `链路回退中：${formatProjectChainStateLabel(detail.project.current_chain_state)}`
          : "未生成",
      detail.publish_package?.review_comment
        ? `审核意见：${detail.publish_package.review_comment}`
        : latestReviewedPublishPackage?.review_comment
          ? `审核意见：${latestReviewedPublishPackage.review_comment}`
          : detail.project.stage === "revision_requested" || detail.project.current_publish_package_version == null
            ? `链路回退中：${formatProjectChainStateLabel(detail.project.current_chain_state)}`
            : "暂无审核意见",
    ],
  };
}

function formatBackgroundTaskStatusLabel(status?: string | null): string {
  if (status === "queued") {
    return "已排队";
  }
  if (status === "running") {
    return "执行中";
  }
  if (status === "done") {
    return "已完成";
  }
  if (status === "failed") {
    return "失败";
  }
  return "未知";
}

export function WorkbenchPage({ stage }: { stage: WorkbenchStage }) {
  const { projectSlug } = useParams<{ projectSlug: string }>();
  const [loadState, setLoadState] = useState<WorkbenchLoadState>({ status: "loading" });
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [activeAction, setActiveAction] = useState<string | null>(null);
  const [draftInstruction, setDraftInstruction] = useState("");
  const [reviewer, setReviewer] = useState("主编");
  const [reviewComment, setReviewComment] = useState("");
  const [retroDraft, setRetroDraft] = useState(() => buildRetroDraft(null));
  const [expandedHistoryVersions, setExpandedHistoryVersions] = useState<number[]>([]);
  const historySectionRef = useRef<HTMLElement | null>(null);
  const [activeBackgroundTask, setActiveBackgroundTask] = useState<{
    submission: BackgroundTaskSubmission;
    detail: BackgroundTaskDetail | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    if (!projectSlug) {
      setLoadState({ status: "error", message: "缺少 project slug，无法打开 Workbench。" });
      return;
    }

    let isCancelled = false;
    setLoadState({ status: "loading" });

    Promise.all([fetchProjectDetail(projectSlug), fetchProjectVersions(projectSlug)])
      .then(([detail, versions]) => {
        if (!isCancelled) {
          setLoadState({ status: "ready", detail, versions });
          setRetroDraft(buildRetroDraft(detail.retro));
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "Workbench 数据加载失败。",
          });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [projectSlug]);

  useEffect(() => {
    if (!activeBackgroundTask?.submission.task_id || !projectSlug) {
      return;
    }

    const currentProjectSlug = projectSlug;
    const taskId = activeBackgroundTask.submission.task_id;
    let isCancelled = false;
    let timerId: number | null = null;

    async function pollTask() {
      try {
        const detail = await fetchBackgroundTask(taskId);
        if (isCancelled) {
          return;
        }

        setActiveBackgroundTask((current) =>
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

        if (detail.status === "done") {
          await reloadWorkbench(currentProjectSlug);
          setActionMessage("按审核意见重生成已完成，Workbench 已刷新到最新链路状态。");
          setActionError(null);
        } else {
          setActionError(detail.error || "按审核意见重生成失败。");
        }
        setActiveBackgroundTask(null);
        setActiveAction(null);
      } catch (error: unknown) {
        if (!isCancelled) {
          setActiveBackgroundTask((current) =>
            current
              ? {
                  ...current,
                  error: error instanceof Error ? error.message : "拉取后台任务状态失败。",
                }
              : current,
          );
          setActionError(error instanceof Error ? error.message : "拉取后台任务状态失败。");
          setActiveAction(null);
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
  }, [activeBackgroundTask?.submission.task_id, projectSlug]);

  if (loadState.status === "loading") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--loading">
          <p className="dashboard-state__eyebrow">加载中</p>
          <h3>正在加载 Workbench</h3>
          <p>正在同步项目详情、链路阶段和版本历史。</p>
        </div>
      </section>
    );
  }

  if (loadState.status === "error") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--error">
          <p className="dashboard-state__eyebrow">加载失败</p>
          <h3>Workbench 加载失败</h3>
          <p>{loadState.message}</p>
          <div className="dashboard-state__actions">
            <Link className="dashboard-button" to="/projects">
              返回项目列表
            </Link>
          </div>
        </div>
      </section>
    );
  }

  const recommendedStage = resolveRecommendedWorkbenchStage(loadState.detail.project);
  const stageViews = buildWorkbenchStageViews({
    project: loadState.detail.project,
    activeStage: stage,
    versions: loadState.versions,
  });
  const historyEntries = buildWorkbenchHistoryEntries({
    stage,
    versions: loadState.versions,
    currentVersionNumber:
      stage === "outline"
        ? loadState.detail.project.current_outline_version
        : stage === "draft"
          ? loadState.detail.project.current_draft_version
          : stage === "assets"
            ? loadState.detail.project.current_assets_version
          : loadState.detail.project.current_publish_package_version,
  });
  const historyGroups = buildWorkbenchHistoryGroups({
    stage,
    entries: historyEntries,
  });
  const stageContent = buildStageContent(stage, loadState.detail);
  const actionPlan = buildWorkbenchActionPlan({
    stage,
    detail: loadState.detail,
    historyEntryCount: historyEntries.length,
  });

  async function reloadWorkbench(projectSlugValue: string) {
    const [detail, versions] = await Promise.all([fetchProjectDetail(projectSlugValue), fetchProjectVersions(projectSlugValue)]);
    setLoadState({ status: "ready", detail, versions });
    setRetroDraft(buildRetroDraft(detail.retro));
  }

  async function runAction(actionKind: WorkbenchActionKind, versionNumber?: number) {
    if (!projectSlug) {
      return;
    }

    if (
      versionNumber === undefined &&
      (actionKind === "restore_outline" ||
        actionKind === "restore_draft" ||
        actionKind === "restore_assets" ||
        actionKind === "restore_publish_package")
    ) {
      historySectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      setActionError(null);
      setActionMessage(
        actionKind === "restore_publish_package"
          ? "请在下方历史版本列表中选择具体版本，系统会基于该版本重建一个新的发布包。"
          : "请在下方历史版本列表中选择要恢复的具体版本。",
      );
      return;
    }

    try {
      setActiveAction(versionNumber ? `${actionKind}-${versionNumber}` : actionKind);
      setActionError(null);
      setActionMessage(null);

      if (actionKind === "generate_outline") {
        await generateOutline(projectSlug);
      } else if (actionKind === "restore_outline" && versionNumber) {
        await restoreOutlineVersion(projectSlug, versionNumber);
      } else if (actionKind === "generate_draft") {
        await generateDraft(projectSlug);
      } else if (actionKind === "polish_draft") {
        await polishDraft(projectSlug, draftInstruction || "请在不改变核心观点的前提下提升表达质量与节奏。");
      } else if (actionKind === "restore_draft" && versionNumber) {
        await restoreDraftVersion(projectSlug, versionNumber);
      } else if (actionKind === "generate_assets") {
        await generateAssets(projectSlug);
      } else if (actionKind === "restore_assets" && versionNumber) {
        await restoreAssetsVersion(projectSlug, versionNumber);
      } else if (actionKind === "build_publish_package") {
        await buildPublishPackage(projectSlug);
      } else if (actionKind === "restore_publish_package" && versionNumber) {
        await restorePublishPackageVersion(projectSlug, versionNumber);
      } else if (actionKind === "approve_publish_package") {
        await approvePublishPackage(projectSlug, {
          reviewer,
          comment: reviewComment || "审核通过，可进入发布。",
        });
      } else if (actionKind === "request_publish_revision") {
        await requestPublishRevision(projectSlug, {
          reviewer,
          comment: reviewComment || "需要继续修改后再提交审核。",
        });
      } else if (actionKind === "regenerate_from_review") {
        const submission = await regenerateFromReview(projectSlug);
        setActiveBackgroundTask({
          submission,
          detail: null,
          error: null,
        });
        setActionMessage("已提交按审核意见重生成任务，正在后台刷新初稿、素材和发布包。");
        return;
      } else if (actionKind === "record_project_retro") {
        const payload: ProjectRetroCreatePayload = {
          performance_rating: Number.parseInt(retroDraft.performance_rating || "4", 10),
          summary: retroDraft.summary || "本轮交付已完成，补齐简要复盘。",
          wins: retroDraft.wins_text.split("\n").map((item) => item.trim()).filter(Boolean),
          gaps: retroDraft.gaps_text.split("\n").map((item) => item.trim()).filter(Boolean),
          next_focus: retroDraft.next_focus || "下一轮继续强化标题与开头钩子。",
        };
        await recordProjectRetro(projectSlug, payload);
      }

      await reloadWorkbench(projectSlug);
      setActionMessage(
        actionKind === "restore_publish_package"
          ? "已基于所选历史版本重建新的发布包，当前阶段数据已刷新。"
          : "Workbench 已刷新，当前阶段数据已更新。",
      );
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "执行阶段动作失败。");
    } finally {
      if (actionKind !== "regenerate_from_review") {
        setActiveAction(null);
      }
    }
  }

  return (
    <div className="workbench-shell">
      <header className="workbench-shell__header">
        <div>
          <p className="workbench-shell__eyebrow">Workbench</p>
          <h1>{loadState.detail.project.title}</h1>
          <p className="workbench-shell__description">
            单项目工作台聚焦内容链路各阶段，把历史和审核留在当前阶段语境里。
          </p>
        </div>
        <div className="workbench-shell__header-actions">
          <span className="workspace-pill">推荐阶段：{recommendedStage}</span>
          <Link className="workbench-shell__backlink" to="/projects">
            返回项目列表
          </Link>
        </div>
      </header>

      {actionMessage ? (
        <div className="workspace-note workspace-note--success">
          <p>{actionMessage}</p>
        </div>
      ) : null}

      {actionError ? (
        <div className="workspace-note workspace-note--error">
          <p>{actionError}</p>
        </div>
      ) : null}

      {activeBackgroundTask ? (
        <div className="workspace-note workspace-note--info">
          <p>
            后台任务状态：{formatBackgroundTaskStatusLabel(activeBackgroundTask.detail?.status ?? activeBackgroundTask.submission.status)}
            {activeBackgroundTask.submission.task_id ? ` · ${activeBackgroundTask.submission.task_id}` : ""}
          </p>
          <p>
            当前正在按审核意见重生成初稿、素材和发布包。
            {activeBackgroundTask.detail?.error ? ` 错误：${activeBackgroundTask.detail.error}` : ""}
          </p>
        </div>
      ) : null}

      <div className="workbench-shell__body">
        <nav aria-label="Workbench stages" className="workbench-shell__stages">
          {stageViews.map((item) => (
            <NavLink
              key={item.key}
              className={({ isActive }) =>
                isActive ? "workbench-stage workbench-stage--active" : item.isRecommended ? "workbench-stage workbench-stage--recommended" : "workbench-stage"
              }
              to={item.targetPath}
            >
              <span className="workbench-stage__label">{item.label}</span>
              <span className="workbench-stage__description">{item.description}</span>
              <span className="workbench-stage__meta">
                {item.versionCount > 0 ? `${item.versionCount} 个版本` : "暂无版本"}
                {item.isRecommended ? " · 推荐" : ""}
              </span>
            </NavLink>
          ))}
        </nav>

        <div className="workbench-shell__content">
          <section ref={historySectionRef} className="workbench-shell__panel">
            <p className="workbench-shell__eyebrow">当前阶段</p>
            <h2>{WORKBENCH_STAGES.find((item) => item.key === stage)?.label ?? stage}</h2>
            <p className="workbench-shell__description">{stageContent.title}</p>
            <div className="workbench-stage-card">
              <p className="workbench-stage-card__body">{stageContent.body}</p>
              <div className="workspace-tag-list">
                {stageContent.meta.map((item) => (
                  <span key={item} className="workspace-tag">
                    {item}
                  </span>
                ))}
              </div>
            </div>

            {actionPlan.showInstructionField ? (
              <label className="workspace-search">
                <span>精修指令</span>
                <input
                  value={draftInstruction}
                  onChange={(event) => setDraftInstruction(event.target.value)}
                  placeholder="例如：加强开头钩子，压缩重复表达，保留情绪递进。"
                />
              </label>
            ) : null}

            {actionPlan.showPublishReviewForm ? (
              <div className="workbench-form-grid">
                <label className="workspace-search">
                  <span>审核人</span>
                  <input value={reviewer} onChange={(event) => setReviewer(event.target.value)} placeholder="填写审核人，例如主编" />
                </label>
                <label className="workspace-search">
                  <span>审核意见</span>
                  <input value={reviewComment} onChange={(event) => setReviewComment(event.target.value)} placeholder="填写通过说明或修改意见" />
                </label>
              </div>
            ) : null}

            {actionPlan.showRetroForm ? (
              <div className="workbench-form-grid">
                <label className="workspace-search">
                  <span>评分</span>
                  <input
                    value={retroDraft.performance_rating}
                    onChange={(event) => setRetroDraft((current) => ({ ...current, performance_rating: event.target.value }))}
                    placeholder="1-5"
                  />
                </label>
                <label className="workspace-search">
                  <span>复盘摘要</span>
                  <input
                    value={retroDraft.summary}
                    onChange={(event) => setRetroDraft((current) => ({ ...current, summary: event.target.value }))}
                    placeholder="一句话总结这次交付。"
                  />
                </label>
                <label className="workspace-search">
                  <span>亮点（每行一条）</span>
                  <input
                    value={retroDraft.wins_text}
                    onChange={(event) => setRetroDraft((current) => ({ ...current, wins_text: event.target.value }))}
                    placeholder="结构稳定"
                  />
                </label>
                <label className="workspace-search">
                  <span>问题（每行一条）</span>
                  <input
                    value={retroDraft.gaps_text}
                    onChange={(event) => setRetroDraft((current) => ({ ...current, gaps_text: event.target.value }))}
                    placeholder="开头钩子偏弱"
                  />
                </label>
                <label className="workspace-search">
                  <span>下一轮重点</span>
                  <input
                    value={retroDraft.next_focus}
                    onChange={(event) => setRetroDraft((current) => ({ ...current, next_focus: event.target.value }))}
                    placeholder="强化标题与首段情绪抓手"
                  />
                </label>
              </div>
            ) : null}

            {stage === "publish" && loadState.detail.retro ? (
              <div className="workspace-retro-card">
                <div className="workspace-section__header">
                  <div>
                    <p className="workspace-section__eyebrow">Project retro</p>
                    <h4>已记录项目复盘</h4>
                    <p className="workspace-section__description">{loadState.detail.retro.summary}</p>
                  </div>
                  <span className="workspace-run-card__count">{loadState.detail.retro.performance_rating}/5</span>
                </div>
                <div className="workspace-tag-list">
                  {loadState.detail.retro.wins.map((item) => (
                    <span key={`win-${item}`} className="workspace-tag">
                      亮点：{item}
                    </span>
                  ))}
                  {loadState.detail.retro.gaps.map((item) => (
                    <span key={`gap-${item}`} className="workspace-tag">
                      问题：{item}
                    </span>
                  ))}
                  <span className="workspace-tag">下一轮重点：{loadState.detail.retro.next_focus}</span>
                </div>
              </div>
            ) : null}

            <div className="workspace-actions workspace-actions--row">
              {actionPlan.primaryAction ? (
                <button
                  className="dashboard-button"
                  type="button"
                  onClick={() => void runAction(actionPlan.primaryAction!.kind)}
                  disabled={activeAction === actionPlan.primaryAction.kind}
                >
                  {activeAction === actionPlan.primaryAction.kind
                    ? actionPlan.primaryAction.kind === "regenerate_from_review"
                      ? activeBackgroundTask?.detail?.status === "running"
                        ? "后台重生成中..."
                        : "提交后台任务..."
                      : "执行中..."
                    : actionPlan.primaryAction.label}
                </button>
              ) : null}
              {actionPlan.secondaryActions.map((action) => (
                <button
                  key={action.kind}
                  className="dashboard-button dashboard-button--ghost"
                  type="button"
                  onClick={() => void runAction(action.kind)}
                  disabled={activeAction === action.kind}
                >
                  {activeAction === action.kind ? "执行中..." : action.label}
                </button>
              ))}
            </div>
          </section>

          <section className="workbench-shell__panel">
            <p className="workbench-shell__eyebrow">Stage history</p>
            <h2>历史版本</h2>
            {historyEntries.length === 0 ? (
              <p className="workbench-shell__description">当前阶段还没有可展示的历史版本。</p>
            ) : historyGroups.length > 0 ? (
              <div className="workspace-section-list">
                {historyGroups.map((group) => (
                  <section key={group.key} className="workspace-subsection">
                    <div className="workspace-section__header">
                      <div>
                        <p className="workspace-section__eyebrow">Publish history</p>
                        <h4>{group.title}</h4>
                        <p className="workspace-section__description">{group.description}</p>
                      </div>
                      <span className="workspace-run-card__count">{group.entries.length}</span>
                    </div>
                    <div className="workspace-list">
                      {group.entries.map((entry) => (
                        <article key={entry.versionNumber} className="workspace-item">
                          <div className="workspace-item__header">
                            <div>
                              <h4>版本 {entry.versionNumber}</h4>
                              <p>
                                {expandedHistoryVersions.includes(entry.versionNumber) ? entry.fullSummary : entry.summary}
                              </p>
                              {entry.truncated ? (
                                <button
                                  className="workspace-inline-toggle"
                                  type="button"
                                  onClick={() =>
                                    setExpandedHistoryVersions((current) =>
                                      current.includes(entry.versionNumber)
                                        ? current.filter((versionNumber) => versionNumber !== entry.versionNumber)
                                        : [...current, entry.versionNumber],
                                    )
                                  }
                                >
                                  {expandedHistoryVersions.includes(entry.versionNumber) ? "收起" : "展开"}
                                </button>
                              ) : null}
                            </div>
                            <span className="workspace-pill">{entry.restorable ? "可恢复" : "当前版本"}</span>
                          </div>
                          {entry.restorable && actionPlan.canRestoreHistory ? (
                            <div className="workspace-actions">
                              <button
                                className="dashboard-button dashboard-button--ghost"
                                type="button"
                                onClick={() =>
                                  void runAction(
                                    stage === "outline"
                                      ? "restore_outline"
                                      : stage === "draft"
                                        ? "restore_draft"
                                        : stage === "assets"
                                          ? "restore_assets"
                                          : "restore_publish_package",
                                    entry.versionNumber,
                                  )
                                }
                                disabled={
                                  activeAction ===
                                  `${
                                    stage === "outline"
                                      ? "restore_outline"
                                      : stage === "draft"
                                        ? "restore_draft"
                                        : stage === "assets"
                                          ? "restore_assets"
                                          : "restore_publish_package"
                                  }-${entry.versionNumber}`
                                }
                              >
                                恢复这个版本
                              </button>
                            </div>
                          ) : null}
                        </article>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            ) : (
              <div className="workspace-list">
                {historyEntries.map((entry) => (
                  <article key={entry.versionNumber} className="workspace-item">
                    <div className="workspace-item__header">
                      <div>
                        <h4>版本 {entry.versionNumber}</h4>
                        <p>
                          {expandedHistoryVersions.includes(entry.versionNumber) ? entry.fullSummary : entry.summary}
                        </p>
                        {entry.truncated ? (
                          <button
                            className="workspace-inline-toggle"
                            type="button"
                            onClick={() =>
                              setExpandedHistoryVersions((current) =>
                                current.includes(entry.versionNumber)
                                  ? current.filter((versionNumber) => versionNumber !== entry.versionNumber)
                                  : [...current, entry.versionNumber],
                              )
                            }
                          >
                            {expandedHistoryVersions.includes(entry.versionNumber) ? "收起" : "展开"}
                          </button>
                        ) : null}
                      </div>
                      <span className="workspace-pill">{entry.restorable ? "可恢复" : "当前版本"}</span>
                    </div>
                    {entry.restorable && actionPlan.canRestoreHistory ? (
                      <div className="workspace-actions">
                        <button
                          className="dashboard-button dashboard-button--ghost"
                          type="button"
                          onClick={() =>
                            void runAction(
                              stage === "outline"
                                ? "restore_outline"
                                : stage === "draft"
                                  ? "restore_draft"
                                  : stage === "assets"
                                    ? "restore_assets"
                                    : "restore_publish_package",
                              entry.versionNumber,
                            )
                          }
                          disabled={
                            activeAction ===
                            `${
                              stage === "outline"
                                ? "restore_outline"
                                : stage === "draft"
                                  ? "restore_draft"
                                  : stage === "assets"
                                    ? "restore_assets"
                                    : "restore_publish_package"
                            }-${entry.versionNumber}`
                          }
                        >
                          恢复这个版本
                        </button>
                      </div>
                    ) : null}
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
