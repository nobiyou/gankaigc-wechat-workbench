import type { ProjectDetail } from "../api/workbench";
import type { WorkbenchStage } from "../app/navigation";

export type WorkbenchActionKind =
  | "generate_strategy_package"
  | "adopt_strategy_card"
  | "generate_outline"
  | "restore_outline"
  | "generate_draft"
  | "polish_draft"
  | "restore_draft"
  | "polish_and_generate_assets"
  | "generate_assets"
  | "regenerate_cover_image"
  | "restore_assets"
  | "polish_and_build_publish_package"
  | "build_publish_package"
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

export function shouldKeepWorkbenchActionActive(actionKind: WorkbenchActionKind, backgroundTaskSubmitted: boolean): boolean {
  return backgroundTaskSubmitted && BACKGROUND_ACTION_KINDS.has(actionKind);
}

export function shouldRetryWorkbenchBackgroundTaskPoll(status?: string | null): boolean {
  return status === "queued" || status === "running";
}

export function shouldClearWorkbenchActionAfterPollError(hasActiveBackgroundTask: boolean): boolean {
  return !hasActiveBackgroundTask;
}

export function getWorkbenchBackgroundTaskDisplayError({
  taskError,
  pollError,
}: {
  taskError?: string | null;
  pollError?: string | null;
}): string | null {
  const normalizedTaskError = taskError?.trim();
  if (normalizedTaskError) {
    return normalizedTaskError;
  }

  const normalizedPollError = pollError?.trim();
  return normalizedPollError || null;
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
    return {
      primaryAction: detail.draft ? { kind: "polish_draft", label: "原创增强精修" } : { kind: "generate_draft", label: "生成初稿" },
      secondaryActions: [
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
    return {
      primaryAction: detail.draft
        ? {
            kind: "polish_and_generate_assets",
            label: detail.assets ? "原创增强后重生成素材包" : "原创增强后生成素材包",
          }
        : { kind: "generate_assets", label: detail.assets ? "重新生成素材包" : "生成素材包" },
      secondaryActions: [
        ...(detail.draft ? [{ kind: "generate_assets" as const, label: detail.assets ? "仅重生成素材包" : "仅生成素材包" }] : []),
        ...(detail.assets ? [{ kind: "regenerate_cover_image" as const, label: "重生成封面图" }] : []),
        ...(historyEntryCount > 1 ? [{ kind: "restore_assets" as const, label: "恢复历史素材" }] : []),
      ],
      canRestoreHistory: historyEntryCount > 1,
      showInstructionField: true,
      showPublishReviewForm: false,
      showRetroForm: false,
    };
  }

  if (stage === "publish") {
    const isRollbackInProgress =
      !detail.publish_package &&
      historyEntryCount > 0 &&
      detail.project.current_publish_package_version == null &&
      detail.project.next_required_step !== "build_publish_package" &&
      detail.project.current_chain_state !== "published";

    if (isRollbackInProgress) {
      return {
        primaryAction: null,
        secondaryActions: historyEntryCount > 1 ? [{ kind: "restore_publish_package", label: "基于历史版本重建发布包" }] : [],
        canRestoreHistory: historyEntryCount > 1,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: false,
      };
    }

    if (detail.publish_package?.status === "needs_revision") {
      return {
        primaryAction: { kind: "regenerate_from_review", label: "按审核意见重生成" },
        secondaryActions: historyEntryCount > 1 ? [{ kind: "restore_publish_package", label: "基于历史版本重建发布包" }] : [],
        canRestoreHistory: historyEntryCount > 1,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: false,
      };
    }

    if (detail.project.current_chain_state === "published" && detail.publish_package?.status === "approved" && !detail.retro) {
      return {
        primaryAction: { kind: "record_project_retro", label: "记录项目复盘" },
        secondaryActions: historyEntryCount > 1 ? [{ kind: "restore_publish_package", label: "基于历史版本重建发布包" }] : [],
        canRestoreHistory: historyEntryCount > 1,
        showInstructionField: false,
        showPublishReviewForm: false,
        showRetroForm: true,
      };
    }

    if (detail.project.current_chain_state === "published" && detail.publish_package?.status === "approved" && detail.retro) {
      return {
        primaryAction: null,
        secondaryActions: historyEntryCount > 1 ? [{ kind: "restore_publish_package", label: "基于历史版本重建发布包" }] : [],
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
          { kind: "request_publish_revision", label: "请求修改" },
          ...(historyEntryCount > 1 ? [{ kind: "restore_publish_package" as const, label: "基于历史版本重建发布包" }] : []),
        ],
        canRestoreHistory: historyEntryCount > 1,
        showInstructionField: false,
        showPublishReviewForm: true,
        showRetroForm: false,
      };
    }

    return {
      primaryAction: detail.draft
        ? {
            kind: "polish_and_build_publish_package",
            label: detail.publish_package ? "原创增强后重生成发布包" : "原创增强后生成发布包",
          }
        : { kind: "build_publish_package", label: detail.publish_package ? "重新生成发布包" : "生成发布包" },
      secondaryActions: [
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
