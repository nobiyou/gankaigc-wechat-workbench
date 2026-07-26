import type { BackgroundTaskErrorContext, ProjectDetail } from "../api/workbench";
import type { WorkbenchStage } from "../app/navigation";

export type WorkbenchActionKind =
  | "generate_strategy_package"
  | "adopt_strategy_card"
  | "generate_outline"
  | "restore_outline"
  | "generate_draft"
  | "diagnose_draft"
  | "polish_draft"
  | "restore_draft"
  | "polish_and_generate_assets"
  | "generate_assets"
  | "regenerate_cover_image"
  | "restore_assets"
  | "polish_and_build_publish_package"
  | "build_publish_package"
  | "generate_creative_review_report"
  | "restore_publish_package"
  | "approve_publish_package"
  | "request_publish_revision"
  | "regenerate_from_review"
  | "record_project_retro";

export type WorkbenchAction = {
  kind: WorkbenchActionKind;
  label: string;
};

export type WorkbenchActionPlan = {
  primaryAction: WorkbenchAction | null;
  secondaryActions: WorkbenchAction[];
  canRestoreHistory: boolean;
  showInstructionField: boolean;
  showPublishReviewForm: boolean;
  showRetroForm: boolean;
};

const BACKGROUND_ACTION_KINDS = new Set<WorkbenchActionKind>([
  "regenerate_cover_image",
  "polish_and_build_publish_package",
  "build_publish_package",
  "regenerate_from_review",
]);

function formatCoverRouteLabel(value?: string | null): string {
  if (value === "primary") {
    return "主路由";
  }
  if (value === "fallback") {
    return "降级路由";
  }
  return value?.trim() || "未知";
}

function buildBackgroundTaskErrorContextSummary(errorContext?: BackgroundTaskErrorContext | null): string | null {
  if (!errorContext) {
    return null;
  }

  if (
    !errorContext.cover_image_route_label &&
    !errorContext.cover_image_route_model &&
    !errorContext.cover_image_route_base_url &&
    !errorContext.fallback_account_pool_diagnosis_label
  ) {
    return null;
  }

  const parts = [
    `封面链路：${formatCoverRouteLabel(errorContext.cover_image_route_label)}`,
    errorContext.cover_image_route_model?.trim() || null,
    errorContext.cover_image_route_base_url?.trim() || null,
    errorContext.fallback_account_pool_diagnosis_label?.trim()
      ? `备用链路：${errorContext.fallback_account_pool_diagnosis_label.trim()}`
      : null,
  ].filter((item): item is string => Boolean(item));

  return parts.join(" · ");
}

function hasReferenceIsolationRisk(detail: ProjectDetail): boolean {
  const report = detail.reference_originality_report;
  if (!report) {
    return false;
  }
  return (
    report.risk_level === "high" ||
    report.risk_level === "medium" ||
    Boolean(report.recommended_polish_instruction?.trim())
  );
}

function hasCurrentDraftDiagnosis(detail: ProjectDetail): boolean {
  return Boolean(
    detail.draft &&
      detail.diagnosis_report &&
      detail.diagnosis_report.draft_version === detail.draft.version,
  );
}

function buildCreativeReportAction(detail: ProjectDetail): WorkbenchAction | null {
  if (!detail.draft && !detail.publish_package && !detail.strategy_card && !detail.diagnosis_report) {
    return null;
  }
  return {
    kind: "generate_creative_review_report",
    label: detail.creative_review_report ? "重新生成创作复盘" : "生成创作复盘",
  };
}

export function shouldKeepWorkbenchActionActive(actionKind: WorkbenchActionKind, backgroundTaskSubmitted: boolean): boolean {
  return backgroundTaskSubmitted && BACKGROUND_ACTION_KINDS.has(actionKind);
}

export function shouldRetryWorkbenchBackgroundTaskPoll(status?: string | null): boolean {
  return status === "queued" || status === "running";
}

export function shouldClearWorkbenchActionAfterPollError(hasActiveBackgroundTask: boolean): boolean {
  return !hasActiveBackgroundTask;
}

type BackgroundTaskCopy = {
  submittedMessage: string;
  completedMessage: string;
  failedMessage: string;
  progressMessage: string;
};

export function getWorkbenchBackgroundTaskCopy(jobType?: string | null): BackgroundTaskCopy {
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
      submittedMessage: "已提交重生成封面图任务，正在后台调用 API 图片链路刷新素材版本。",
      completedMessage: "封面图重生成已完成，Workbench 已刷新到最新素材版本。",
      failedMessage: "重生成封面图失败。当前封面只走 API 图片链路。",
      progressMessage: "当前正在通过 API 图片链路重生成封面图，并写入新的素材版本。",
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

export function getWorkbenchBackgroundTaskStatusMessage(jobType?: string | null, status?: string | null): string {
  const copy = getWorkbenchBackgroundTaskCopy(jobType);
  if (status === "failed") {
    return `${copy.failedMessage} 诊断信息会保留在这里，方便你按链路继续排查。`;
  }
  if (status === "done") {
    return copy.completedMessage;
  }
  if (status === "queued") {
    return copy.submittedMessage;
  }
  return copy.progressMessage;
}

export function getWorkbenchBackgroundTaskTone(status?: string | null): "info" | "error" | "success" {
  if (status === "failed") {
    return "error";
  }
  if (status === "done") {
    return "success";
  }
  return "info";
}

export function getWorkbenchBackgroundTaskDisplayError({
  taskError,
  pollError,
  errorContext,
}: {
  taskError?: string | null;
  pollError?: string | null;
  errorContext?: BackgroundTaskErrorContext | null;
}): string | null {
  const normalizedTaskError = taskError?.trim();
  const errorContextSummary = buildBackgroundTaskErrorContextSummary(errorContext);
  if (normalizedTaskError) {
    return errorContextSummary ? `${normalizedTaskError} | ${errorContextSummary}` : normalizedTaskError;
  }

  const normalizedPollError = pollError?.trim();
  if (normalizedPollError) {
    return normalizedPollError;
  }

  return errorContextSummary || null;
}

export function buildWorkbenchActionPlan({
  stage,
  detail,
  historyEntryCount,
}: {
  stage: WorkbenchStage;
  detail: ProjectDetail;
  historyEntryCount: number;
}): WorkbenchActionPlan {
  if (stage === "topic") {
    if (!detail.strategy_card) {
      return {
        primaryAction: { kind: "generate_strategy_package", label: "生成策略包" },
        secondaryActions: [{ kind: "generate_outline", label: "直接生成大纲" }],
        canRestoreHistory: false,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: false,
      };
    }

    if (!detail.strategy_card.adopted_at) {
      return {
        primaryAction: { kind: "adopt_strategy_card", label: "采纳当前策略卡" },
        secondaryActions: [
          { kind: "generate_strategy_package", label: "重新生成策略包" },
          { kind: "generate_outline", label: "直接生成大纲" },
        ],
        canRestoreHistory: false,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: false,
      };
    }

    return {
      primaryAction: detail.outline ? { kind: "generate_outline", label: "重新生成大纲" } : { kind: "generate_outline", label: "生成大纲" },
      secondaryActions: [{ kind: "generate_strategy_package", label: "重新生成策略包" }],
      canRestoreHistory: false,
      showInstructionField: false,
      showPublishReviewForm: false,
      showRetroForm: false,
    };
  }

  if (stage === "outline") {
    return {
      primaryAction: detail.outline ? { kind: "generate_outline", label: "重新生成大纲" } : { kind: "generate_outline", label: "生成大纲" },
      secondaryActions: historyEntryCount > 1 ? [{ kind: "restore_outline", label: "恢复历史大纲" }] : [],
      canRestoreHistory: historyEntryCount > 1,
      showInstructionField: false,
      showPublishReviewForm: false,
      showRetroForm: false,
    };
  }

  if (stage === "draft") {
    const needsReferenceIsolation = hasReferenceIsolationRisk(detail);
    const hasDiagnosis = hasCurrentDraftDiagnosis(detail);
    const polishLabel = hasDiagnosis ? "按诊断目标精修" : needsReferenceIsolation ? "参考文隔离精修" : "原创增强精修";
    return {
      primaryAction: detail.draft
        ? hasDiagnosis
          ? { kind: "polish_draft", label: polishLabel }
          : { kind: "diagnose_draft", label: "运行内容诊断" }
        : { kind: "generate_draft", label: "生成初稿" },
      secondaryActions: [
        ...(detail.draft
          ? hasDiagnosis
            ? [{ kind: "diagnose_draft" as const, label: "重新运行内容诊断" }]
            : [{ kind: "polish_draft" as const, label: polishLabel }]
          : []),
        ...(detail.outline ? [{ kind: "generate_draft" as const, label: detail.draft ? "重新生成初稿" : "生成初稿" }] : []),
        ...(historyEntryCount > 1 ? [{ kind: "restore_draft" as const, label: "恢复历史初稿" }] : []),
      ],
      canRestoreHistory: historyEntryCount > 1,
      showInstructionField: true,
      showPublishReviewForm: false,
      showRetroForm: false,
    };
  }

  if (stage === "assets") {
    const needsReferenceIsolation = hasReferenceIsolationRisk(detail);
    const assetsQualityBlocked = detail.assets?.cover_image_status === "quality_blocked";
    const coverPending =
      !assetsQualityBlocked &&
      (detail.assets?.cover_image_status === "pending" || (detail.assets ? !detail.assets.cover_image_url : false));
    return {
      primaryAction: coverPending
        ? { kind: "regenerate_cover_image", label: "重试图片 API" }
        : detail.draft
        ? {
            kind: "polish_and_generate_assets",
            label: needsReferenceIsolation
              ? detail.assets
                ? "参考文隔离后重生成素材包"
                : "参考文隔离后生成素材包"
              : detail.assets
                ? "原创增强后重生成素材包"
                : "原创增强后生成素材包",
          }
        : { kind: "generate_assets", label: detail.assets ? "重新生成素材包" : "生成素材包" },
      secondaryActions: [
        ...(detail.draft ? [{ kind: "generate_assets" as const, label: detail.assets ? "仅重生成素材包" : "仅生成素材包" }] : []),
        ...(detail.assets && !coverPending && !assetsQualityBlocked
          ? [{ kind: "regenerate_cover_image" as const, label: "重生成封面图" }]
          : []),
        ...(historyEntryCount > 1 ? [{ kind: "restore_assets" as const, label: "恢复历史素材" }] : []),
      ],
      canRestoreHistory: historyEntryCount > 1,
      showInstructionField: true,
      showPublishReviewForm: false,
      showRetroForm: false,
    };
  }

  if (stage === "publish") {
    const assetsQualityBlocked = detail.assets?.cover_image_status === "quality_blocked";
    const coverPending =
      !assetsQualityBlocked &&
      (detail.assets?.cover_image_status === "pending" || (detail.assets ? !detail.assets.cover_image_url : false));
    if (coverPending) {
      return {
        primaryAction: { kind: "regenerate_cover_image", label: "重试图片 API" },
        secondaryActions: [],
        canRestoreHistory: false,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: false,
      };
    }
    const creativeReportAction = buildCreativeReportAction(detail);
    const isRollbackInProgress =
      !detail.publish_package &&
      historyEntryCount > 0 &&
      detail.project.current_publish_package_version == null &&
      detail.project.next_required_step !== "build_publish_package" &&
      detail.project.current_chain_state !== "published";

    if (isRollbackInProgress) {
      return {
        primaryAction: null,
        secondaryActions: [
          ...(creativeReportAction ? [creativeReportAction] : []),
          ...(historyEntryCount > 1 ? [{ kind: "restore_publish_package" as const, label: "基于历史版本重建发布包" }] : []),
        ],
        canRestoreHistory: historyEntryCount > 1,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: false,
      };
    }

    if (detail.publish_package?.status === "needs_revision") {
      return {
        primaryAction: { kind: "regenerate_from_review", label: "按审核意见重生成" },
        secondaryActions: [
          ...(creativeReportAction ? [creativeReportAction] : []),
          ...(historyEntryCount > 1 ? [{ kind: "restore_publish_package" as const, label: "基于历史版本重建发布包" }] : []),
        ],
        canRestoreHistory: historyEntryCount > 1,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: false,
      };
    }

    if (detail.project.current_chain_state === "published" && detail.publish_package?.status === "approved" && !detail.retro) {
      return {
        primaryAction: { kind: "record_project_retro", label: "记录项目复盘" },
        secondaryActions: [
          ...(creativeReportAction ? [creativeReportAction] : []),
          ...(historyEntryCount > 1 ? [{ kind: "restore_publish_package" as const, label: "基于历史版本重建发布包" }] : []),
        ],
        canRestoreHistory: historyEntryCount > 1,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: true,
      };
    }

    if (detail.project.current_chain_state === "published" && detail.publish_package?.status === "approved" && detail.retro) {
      return {
        primaryAction: null,
        secondaryActions: [
          ...(creativeReportAction ? [creativeReportAction] : []),
          ...(historyEntryCount > 1 ? [{ kind: "restore_publish_package" as const, label: "基于历史版本重建发布包" }] : []),
        ],
        canRestoreHistory: historyEntryCount > 1,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: false,
      };
    }

    if (detail.publish_package?.status === "ready") {
      return {
        primaryAction: { kind: "approve_publish_package", label: "审核通过" },
        secondaryActions: [
          ...(creativeReportAction ? [creativeReportAction] : []),
          { kind: "request_publish_revision", label: "请求修改" },
          ...(historyEntryCount > 1 ? [{ kind: "restore_publish_package" as const, label: "基于历史版本重建发布包" }] : []),
        ],
        canRestoreHistory: historyEntryCount > 1,
        showInstructionField: false,
        showPublishReviewForm: true,
        showRetroForm: false,
      };
    }

    const needsReferenceIsolation = hasReferenceIsolationRisk(detail);
    return {
      primaryAction: detail.draft
        ? {
            kind: "polish_and_build_publish_package",
            label: needsReferenceIsolation
              ? detail.publish_package
                ? "参考文隔离后重生成发布包"
                : "参考文隔离后生成发布包"
              : detail.publish_package
                ? "原创增强后重生成发布包"
                : "原创增强后生成发布包",
          }
        : { kind: "build_publish_package", label: detail.publish_package ? "重新生成发布包" : "生成发布包" },
      secondaryActions: [
        ...(creativeReportAction ? [creativeReportAction] : []),
        ...(detail.assets ? [{ kind: "build_publish_package" as const, label: detail.publish_package ? "仅重生成发布包" : "仅生成发布包" }] : []),
        ...(historyEntryCount > 1 ? [{ kind: "restore_publish_package" as const, label: "基于历史版本重建发布包" }] : []),
      ],
      canRestoreHistory: historyEntryCount > 1,
      showInstructionField: detail.draft != null,
      showPublishReviewForm: false,
      showRetroForm: false,
    };
  }

  return {
    primaryAction: null,
    secondaryActions: [],
    canRestoreHistory: false,
    showInstructionField: false,
    showPublishReviewForm: false,
    showRetroForm: false,
  };
}
