import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";

import {
  approvePublishPackage,
  fetchBackgroundTask,
  buildPublishPackageInBackground,
  fetchDomainPacks,
  fetchProjectDetail,
  fetchProjectVersions,
  fetchToneProfiles,
  generateAssets,
  generateDraft,
  generateOutline,
  polishDraft,
  regenerateCoverImage,
  recordProjectRetro,
  regenerateFromReview,
  requestPublishRevision,
  restoreAssetsVersion,
  restoreDraftVersion,
  restoreOutlineVersion,
  restorePublishPackageVersion,
  updateProject,
  type BackgroundTaskDetail,
  type BackgroundTaskSubmission,
  type DomainPackSummary,
  type ProjectDetail,
  type ProjectRetroCreatePayload,
  type ToneProfileItem,
  type ProjectVersions,
} from "../api/workbench";
import { WORKBENCH_STAGES, type WorkbenchStage } from "../app/navigation";
import { formatProjectDomainPackLabel } from "../domainPacks";
import { buildProjectConfigPreviewLines } from "../projectConfigPreview";
import { formatProjectChainStateLabel, formatProjectNextStepLabel } from "../projectStatus";
import { buildRetroDraft } from "../retroDraft";
import { getTaskTypeLabel } from "../taskLabels";
import { formatProjectToneProfileLabel, hasProjectToneProfileSelectionChanged, resolveDraftPolishInstruction } from "../toneProfiles";
import {
  buildWorkbenchActionPlan,
  getWorkbenchBackgroundTaskDisplayError,
  shouldClearWorkbenchActionAfterPollError,
  shouldKeepWorkbenchActionActive,
  shouldRetryWorkbenchBackgroundTaskPoll,
  type WorkbenchActionKind,
} from "../view-models/workbenchActions";
import { buildWorkbenchHistoryEntries, buildWorkbenchHistoryGroups, formatPublishStatusLabel } from "../view-models/workbenchHistory";
import { buildWorkbenchPreview } from "../view-models/workbenchPreview";
import { buildWorkbenchStageViews, resolveRecommendedWorkbenchStage } from "../view-models/workbenchStages";

type WorkbenchLoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; detail: ProjectDetail; versions: ProjectVersions; domainPacks: DomainPackSummary[]; toneProfiles: ToneProfileItem[] };

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

function formatBackgroundTaskTimestamp(value?: string | null): string {
  if (!value) {
    return "时间未知";
  }

  const timestamp = Date.parse(value);
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

function describeBackgroundTask(jobType?: string | null): {
  submittedMessage: string;
  completedMessage: string;
  failedMessage: string;
  progressMessage: string;
} {
  if (jobType === "build_publish_package") {
    return {
      submittedMessage: "已提交生成发布包任务，正在后台构建正文成品与发布清单。",
      completedMessage: "发布包生成已完成，Workbench 已刷新到最新发布状态。",
      failedMessage: "生成发布包失败。",
      progressMessage: "当前正在后台生成发布包，并刷新发布阶段数据。",
    };
  }

  if (jobType === "regenerate_cover_image") {
    return {
      submittedMessage: "已提交重生成封面图任务，正在后台刷新素材版本。",
      completedMessage: "封面图重生成已完成，Workbench 已刷新到最新素材版本。",
      failedMessage: "重生成封面图失败。",
      progressMessage: "当前正在后台重生成封面图，并写入新的素材版本。",
    };
  }

  if (jobType === "polish_and_generate_assets") {
    return {
      submittedMessage: "已提交原创增强后生成素材任务，正在基于新正文刷新素材版本。",
      completedMessage: "原创增强与素材重生成已完成，Workbench 已刷新到最新素材版本。",
      failedMessage: "原创增强后生成素材失败。",
      progressMessage: "当前正在先做原创增强精修，再基于新正文生成素材包。",
    };
  }

  if (jobType === "polish_and_build_publish_package") {
    return {
      submittedMessage: "已提交原创增强后生成发布包任务，正在后台刷新正文、素材和发布成品。",
      completedMessage: "原创增强与发布包重生成已完成，Workbench 已刷新到最新发布状态。",
      failedMessage: "原创增强后生成发布包失败。",
      progressMessage: "当前正在先做原创增强精修，再生成新的素材和发布包。",
    };
  }

  return {
    submittedMessage: "已提交按审核意见重生成任务，正在后台刷新初稿、素材和发布包。",
    completedMessage: "按审核意见重生成已完成，Workbench 已刷新到最新链路状态。",
    failedMessage: "按审核意见重生成失败。",
    progressMessage: "当前正在按审核意见重生成初稿、素材和发布包。",
  };
}

const DEFAULT_POLISH_HELP =
  "请执行原创增强精修，目标是把当前正文改到更像真实公众号作者手写稿，而不是AI顺滑稿；重写大部分句子，减少模板感、重复句式和总结腔，结尾收得更安静。";

function renderSimpleMarkdown(markdown: string): ReactNode {
  const lines = markdown.split("\n");
  const nodes: React.ReactNode[] = [];
  let listItems: string[] = [];

  function flushList() {
    if (listItems.length === 0) {
      return;
    }

    nodes.push(
      <ol key={`list-${nodes.length}`} className="workbench-markdown__list">
        {listItems.map((item, index) => (
          <li key={`${item}-${index}`}>{item}</li>
        ))}
      </ol>,
    );
    listItems = [];
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();

    if (!line) {
      flushList();
      continue;
    }

    const orderedMatch = line.match(/^\d+[.)、]\s+(.*)$/);
    if (orderedMatch) {
      listItems.push(orderedMatch[1]);
      continue;
    }

    flushList();

    if (line.startsWith("### ")) {
      nodes.push(
        <h5 key={`h5-${nodes.length}`} className="workbench-markdown__heading workbench-markdown__heading--sm">
          {line.slice(4)}
        </h5>,
      );
      continue;
    }

    if (line.startsWith("## ")) {
      nodes.push(
        <h4 key={`h4-${nodes.length}`} className="workbench-markdown__heading">
          {line.slice(3)}
        </h4>,
      );
      continue;
    }

    if (line.startsWith("# ")) {
      nodes.push(
        <h3 key={`h3-${nodes.length}`} className="workbench-markdown__heading workbench-markdown__heading--lg">
          {line.slice(2)}
        </h3>,
      );
      continue;
    }

    nodes.push(
      <p key={`p-${nodes.length}`} className="workbench-markdown__paragraph">
        {line}
      </p>,
    );
  }

  flushList();
  return nodes;
}

function renderPreviewBlockBody(block: { content: string; kind?: "text" | "markdown" | "image"; imageUrl?: string }): ReactNode {
  if (block.kind === "image" && block.imageUrl) {
    return (
      <figure className="workbench-preview__image-frame">
        <img src={block.imageUrl} alt="生成的封面图" className="workbench-preview__image" />
      </figure>
    );
  }

  if (block.kind === "markdown") {
    return <div className="workbench-preview__body workbench-markdown">{renderSimpleMarkdown(block.content)}</div>;
  }

  return <pre className="workbench-preview__body">{block.content}</pre>;
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
  const [isConfigExpanded, setIsConfigExpanded] = useState(false);
  const [domainPackDraft, setDomainPackDraft] = useState("");
  const [toneProfileDraft, setToneProfileDraft] = useState("");
  const [savingConfig, setSavingConfig] = useState(false);
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

    Promise.all([fetchProjectDetail(projectSlug), fetchProjectVersions(projectSlug), fetchDomainPacks(), fetchToneProfiles()])
      .then(([detail, versions, domainPacks, toneProfiles]) => {
        if (!isCancelled) {
          setLoadState({ status: "ready", detail, versions, domainPacks, toneProfiles });
          setRetroDraft(buildRetroDraft(detail.retro));
          setDomainPackDraft(detail.project.domain_pack_key ?? "");
          setToneProfileDraft(detail.project.preferred_tone_profile_id == null ? "" : String(detail.project.preferred_tone_profile_id));
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

        if (shouldRetryWorkbenchBackgroundTaskPoll(detail.status)) {
          timerId = window.setTimeout(() => {
            void pollTask();
          }, 2000);
          return;
        }

        if (detail.status === "done") {
          await reloadWorkbench(currentProjectSlug);
          setActionMessage(describeBackgroundTask(detail.job_type).completedMessage);
          setActionError(null);
        } else {
          setActionError(detail.error || describeBackgroundTask(detail.job_type).failedMessage);
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
          if (shouldClearWorkbenchActionAfterPollError(Boolean(activeBackgroundTask))) {
            setActiveAction(null);
          }
          timerId = window.setTimeout(() => {
            void pollTask();
          }, 2000);
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
  const preview = buildWorkbenchPreview(stage, loadState.detail, loadState.versions);
  const activeBackgroundTaskError = activeBackgroundTask
    ? getWorkbenchBackgroundTaskDisplayError({
        taskError: activeBackgroundTask.detail?.error,
        pollError: activeBackgroundTask.error,
      })
    : null;

  async function handleCopyPreviewBlock(label: string, copyText: string) {
    try {
      await navigator.clipboard.writeText(copyText);
      setActionError(null);
      setActionMessage(`已复制${label}，可直接粘贴去做原创检测。`);
    } catch (error: unknown) {
      setActionMessage(null);
      setActionError(error instanceof Error ? error.message : `复制${label}失败。`);
    }
  }
  const nextToneProfileId = toneProfileDraft ? Number.parseInt(toneProfileDraft, 10) : null;
  const hasConfigChanged =
    (loadState.detail.project.domain_pack_key ?? "") !== domainPackDraft ||
    hasProjectToneProfileSelectionChanged(loadState.detail.project, nextToneProfileId);
  const activeProjectToneProfile =
    loadState.toneProfiles.find((profile) => profile.id === nextToneProfileId) ??
    loadState.toneProfiles.find((profile) => profile.is_active) ??
    null;
  const effectiveDraftPolishInstruction = resolveDraftPolishInstruction(draftInstruction, activeProjectToneProfile);

  async function reloadWorkbench(projectSlugValue: string) {
    const [detail, versions, domainPacks, toneProfiles] = await Promise.all([
      fetchProjectDetail(projectSlugValue),
      fetchProjectVersions(projectSlugValue),
      fetchDomainPacks(),
      fetchToneProfiles(),
    ]);
    setLoadState({ status: "ready", detail, versions, domainPacks, toneProfiles });
    setRetroDraft(buildRetroDraft(detail.retro));
    setDomainPackDraft(detail.project.domain_pack_key ?? "");
    setToneProfileDraft(detail.project.preferred_tone_profile_id == null ? "" : String(detail.project.preferred_tone_profile_id));
  }

  async function handleSaveProjectConfig() {
    if (!projectSlug || loadState.status !== "ready") {
      return;
    }

    try {
      setSavingConfig(true);
      setActionError(null);
      setActionMessage(null);
      await updateProject(projectSlug, {
        stage: loadState.detail.project.stage,
        domain_pack_key: domainPackDraft || null,
        preferred_tone_profile_id: nextToneProfileId,
      });
      await reloadWorkbench(projectSlug);
      setActionMessage("已更新当前项目的赛道和风格配置。");
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "保存项目配置失败。");
    } finally {
      setSavingConfig(false);
    }
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

    let backgroundTaskSubmitted = false;

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
        await polishDraft(
          projectSlug,
          effectiveDraftPolishInstruction,
        );
      } else if (actionKind === "polish_and_generate_assets") {
        await generateAssets(projectSlug, {
          polish_before_generate: true,
          polish_instruction: effectiveDraftPolishInstruction,
        });
      } else if (actionKind === "restore_draft" && versionNumber) {
        await restoreDraftVersion(projectSlug, versionNumber);
      } else if (actionKind === "generate_assets") {
        await generateAssets(projectSlug);
      } else if (actionKind === "regenerate_cover_image") {
        const submission = await regenerateCoverImage(projectSlug);
        setActiveBackgroundTask({
          submission,
          detail: null,
          error: null,
        });
        backgroundTaskSubmitted = true;
        setActionMessage(describeBackgroundTask(submission.job_type).submittedMessage);
        return;
      } else if (actionKind === "restore_assets" && versionNumber) {
        await restoreAssetsVersion(projectSlug, versionNumber);
      } else if (actionKind === "build_publish_package") {
        const submission = await buildPublishPackageInBackground(projectSlug);
        setActiveBackgroundTask({
          submission,
          detail: null,
          error: null,
        });
        backgroundTaskSubmitted = true;
        setActionMessage(describeBackgroundTask(submission.job_type).submittedMessage);
        return;
      } else if (actionKind === "polish_and_build_publish_package") {
        const submission = await buildPublishPackageInBackground(projectSlug, {
          polish_before_generate: true,
          polish_instruction: effectiveDraftPolishInstruction,
        });
        setActiveBackgroundTask({
          submission,
          detail: null,
          error: null,
        });
        backgroundTaskSubmitted = true;
        setActionMessage(describeBackgroundTask(submission.job_type).submittedMessage);
        return;
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
        backgroundTaskSubmitted = true;
        setActionMessage(describeBackgroundTask(submission.job_type).submittedMessage);
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
      if (!shouldKeepWorkbenchActionActive(actionKind, backgroundTaskSubmitted)) {
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
          <div className="workspace-tag-list">
            <span className="workspace-tag">{formatProjectDomainPackLabel(loadState.detail.project, loadState.domainPacks)}</span>
            <span className="workspace-tag">{formatProjectToneProfileLabel(loadState.detail.project)}</span>
          </div>
        </div>
        <div className="workbench-shell__header-actions">
          <span className="workspace-pill">推荐阶段：{recommendedStage}</span>
          <button
            className="dashboard-button dashboard-button--ghost"
            type="button"
            onClick={() => setIsConfigExpanded((current) => !current)}
          >
            {isConfigExpanded ? "收起项目配置" : "切换赛道/风格"}
          </button>
          <Link className="workbench-shell__backlink" to="/projects">
            返回项目列表
          </Link>
        </div>
      </header>

      {isConfigExpanded ? (
        <section className="workspace-subsection workspace-project-config-panel workbench-shell__config-panel">
          <div className="workspace-section__header">
            <div>
              <p className="workspace-section__eyebrow">项目配置</p>
              <h4>当前项目的赛道与风格</h4>
              <p className="workspace-section__description">这里的切换只影响当前项目后续生成，不会改动全局默认风格。</p>
            </div>
          </div>
          <div className="workspace-actions workspace-actions--row workspace-actions--project-config">
            <label className="workspace-search workspace-search--compact">
              <span>项目赛道</span>
              <select className="workspace-select" value={domainPackDraft} onChange={(event) => setDomainPackDraft(event.target.value)}>
                <option value="">跟随默认赛道</option>
                {loadState.domainPacks.map((pack) => (
                  <option key={pack.key} value={pack.key}>
                    {pack.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="workspace-search workspace-search--compact">
              <span>项目风格</span>
              <select className="workspace-select" value={toneProfileDraft} onChange={(event) => setToneProfileDraft(event.target.value)}>
                <option value="">跟随当前全局风格</option>
                {loadState.toneProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {profile.name}
                    {profile.is_active ? " · 当前全局" : ""}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="dashboard-button"
              type="button"
              onClick={() => void handleSaveProjectConfig()}
              disabled={savingConfig || !hasConfigChanged}
            >
              {savingConfig ? "保存中..." : "保存当前配置"}
            </button>
          </div>
          <div className="workspace-note workspace-note--info">
            {buildProjectConfigPreviewLines({
              domainPacks: loadState.domainPacks,
              domainPackKey: domainPackDraft || null,
              toneProfiles: loadState.toneProfiles,
              toneProfileId: nextToneProfileId,
            }).map((line) => (
              <p key={line}>{line}</p>
            ))}
          </div>
        </section>
      ) : null}

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
        <div className="workspace-note workspace-note--info workbench-task-note">
          <div className="workspace-section__header">
            <div>
              <p className="workspace-section__eyebrow">Background Task</p>
              <h4>{getTaskTypeLabel(activeBackgroundTask.submission.job_type)}</h4>
              <p>{describeBackgroundTask(activeBackgroundTask.submission.job_type).progressMessage}</p>
            </div>
            <span className="workspace-run-card__count">
              {formatBackgroundTaskStatusLabel(activeBackgroundTask.detail?.status ?? activeBackgroundTask.submission.status)}
            </span>
          </div>
          <div className="workspace-item__meta">
            <span>{`任务 ID：${activeBackgroundTask.submission.task_id}`}</span>
            <span>{`提交时间：${formatBackgroundTaskTimestamp(activeBackgroundTask.submission.created_at)}`}</span>
            {activeBackgroundTask.detail?.started_at ? (
              <span>{`开始执行：${formatBackgroundTaskTimestamp(activeBackgroundTask.detail.started_at)}`}</span>
            ) : null}
          </div>
          <div className="workspace-tag-list">
            <span className="workspace-tag">可先切换到其他阶段继续查看</span>
            <span className="workspace-tag">任务完成后会自动刷新当前 Workbench</span>
          </div>
          {activeBackgroundTaskError ? (
            <p className="workbench-task-note__error">{`错误：${activeBackgroundTaskError}`}</p>
          ) : null}
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
          <div className="workbench-shell__main-column">
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
              <>
                <label className="workspace-search">
                  <span>
                    {stage === "assets"
                      ? "素材重生前精修指令"
                      : stage === "publish"
                        ? "发布包生成前精修指令"
                        : "精修指令"}
                  </span>
                  <input
                    value={draftInstruction}
                    onChange={(event) => setDraftInstruction(event.target.value)}
                    placeholder={
                      stage === "assets"
                        ? "例如：更像人写的公众号稿，重写开头和结尾，减少重复句式，压低模板感。"
                        : stage === "publish"
                          ? "例如：生成发布包前先把正文压一版，减少模板感和对称句，更像真实公众号作者在写。"
                        : "例如：重写开头和结尾，调整段落连接，减少重复句式，保留情绪递进。"
                    }
                  />
                </label>
                {activeProjectToneProfile?.default_polish_instruction ? (
                  <div className="workspace-note workspace-note--info">
                    <p>
                      {draftInstruction.trim()
                        ? "当前将优先使用你手填的精修指令。"
                        : `当前未手填指令，将自动使用风格「${activeProjectToneProfile.name}」的默认原创增强精修策略。`}
                    </p>
                    <p>{`默认策略：${effectiveDraftPolishInstruction || DEFAULT_POLISH_HELP}`}</p>
                  </div>
                ) : null}
                {!activeProjectToneProfile?.default_polish_instruction && (stage === "assets" || stage === "publish") ? (
                  <div className="workspace-note workspace-note--info">
                    <p>
                      {stage === "assets"
                        ? "当前风格未配置默认精修策略，素材阶段会自动回退到系统内置的“更像人写的公众号稿”原创增强策略。"
                        : "当前风格未配置默认精修策略，发布阶段会自动回退到系统内置的“更像人写的公众号稿”原创增强策略。"}
                    </p>
                    <p>{`系统策略：${DEFAULT_POLISH_HELP}`}</p>
                  </div>
                ) : null}
              </>
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
                    ? actionPlan.primaryAction.kind === "regenerate_from_review" ||
                      actionPlan.primaryAction.kind === "build_publish_package" ||
                      actionPlan.primaryAction.kind === "polish_and_build_publish_package"
                      ? activeBackgroundTask?.detail?.status === "running"
                        ? actionPlan.primaryAction.kind === "build_publish_package"
                          ? "后台生成中..."
                          : actionPlan.primaryAction.kind === "polish_and_build_publish_package"
                            ? "后台处理中..."
                          : "后台重生成中..."
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
                                {entry.meta.length > 0 ? (
                                  <div className="workspace-tag-list">
                                    {entry.meta.map((item) => (
                                      <span key={item} className="workspace-tag">
                                        {item}
                                      </span>
                                    ))}
                                  </div>
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
                          {entry.meta.length > 0 ? (
                            <div className="workspace-tag-list">
                              {entry.meta.map((item) => (
                                <span key={item} className="workspace-tag">
                                  {item}
                                </span>
                              ))}
                            </div>
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

          {preview ? (
            <aside className="workbench-shell__panel workbench-shell__preview">
              <p className="workbench-shell__eyebrow">{preview.eyebrow}</p>
              <h2>{preview.title}</h2>
              <p className="workbench-shell__description">{preview.summary}</p>
              <div className={`workbench-preview workbench-preview--${preview.tone}`}>
                {preview.blocks.map((block) => (
                  <section key={block.key} className="workbench-preview__section">
                    <div className="workbench-preview__section-header">
                      <h3>{block.label}</h3>
                      {block.copyText ? (
                        <button
                          className="workspace-inline-toggle"
                          type="button"
                          onClick={() => void handleCopyPreviewBlock(block.label, block.copyText ?? block.content)}
                        >
                          复制
                        </button>
                      ) : null}
                    </div>
                    {renderPreviewBlockBody(block)}
                  </section>
                ))}
              </div>
            </aside>
          ) : null}
        </div>
      </div>
    </div>
  );
}
