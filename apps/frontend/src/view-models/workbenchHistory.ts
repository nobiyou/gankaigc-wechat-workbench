import type { ProjectVersions } from "../api/workbench";
import type { WorkbenchStage } from "../app/navigation";

export type WorkbenchHistoryEntry = {
  versionNumber: number;
  summary: string;
  fullSummary: string;
  truncated: boolean;
  restorable: boolean;
  reviewState: string | null;
};

export type WorkbenchHistoryGroup = {
  key: string;
  title: string;
  description: string;
  entries: WorkbenchHistoryEntry[];
};

const HISTORY_SUMMARY_PREVIEW_LENGTH = 72;

function buildSummaryText(summary: string): { summary: string; fullSummary: string; truncated: boolean } {
  const normalized = summary.trim();
  if (normalized.length <= HISTORY_SUMMARY_PREVIEW_LENGTH) {
    return {
      summary: normalized,
      fullSummary: normalized,
      truncated: false,
    };
  }

  return {
    summary: `${normalized.slice(0, HISTORY_SUMMARY_PREVIEW_LENGTH).trimEnd()}...`,
    fullSummary: normalized,
    truncated: true,
  };
}

export function formatPublishStatusLabel(status: string): string {
  if (status === "ready") {
    return "待审核";
  }
  if (status === "approved") {
    return "已通过";
  }
  if (status === "needs_revision") {
    return "已打回";
  }
  return status;
}

export function buildWorkbenchHistoryEntries({
  stage,
  versions,
  currentVersionNumber,
}: {
  stage: WorkbenchStage;
  versions: ProjectVersions;
  currentVersionNumber?: number | null;
}): WorkbenchHistoryEntry[] {
  if (stage === "outline") {
    return versions.outlines.map((item) => ({
      versionNumber: item.version,
      ...buildSummaryText(`${item.hook || "大纲版本"} · v${item.version}`),
      restorable: item.version !== currentVersionNumber,
      reviewState: null,
    }));
  }

  if (stage === "draft") {
    return versions.drafts.map((item) => ({
      versionNumber: item.version,
      ...buildSummaryText(`${item.title} · ${item.word_count} 字`),
      restorable: item.version !== currentVersionNumber,
      reviewState: null,
    }));
  }

  if (stage === "assets") {
    return versions.assets.map((item) => ({
      versionNumber: item.version,
      ...buildSummaryText(`${item.title_options[0] ?? "素材版本"} · ${item.cover_copy}`),
      restorable: item.version !== currentVersionNumber,
      reviewState: null,
    }));
  }

  if (stage === "publish") {
    return versions.publish_packages.map((item) => ({
      versionNumber: item.version,
      ...buildSummaryText(`${formatPublishStatusLabel(item.status)} · ${item.abstract}`),
      restorable: item.version !== currentVersionNumber,
      reviewState: item.status,
    }));
  }

  return [];
}

export function buildWorkbenchHistoryGroups({
  stage,
  entries,
}: {
  stage: WorkbenchStage;
  entries: WorkbenchHistoryEntry[];
}): WorkbenchHistoryGroup[] {
  if (stage !== "publish") {
    return [];
  }

  const groups: Array<{ key: string; title: string; description: string; matches: (entry: WorkbenchHistoryEntry) => boolean }> = [
    {
      key: "ready",
      title: "待审核",
      description: "当前仍可直接进入审核或回退重建的发布包。",
      matches: (entry) => entry.reviewState === "ready",
    },
    {
      key: "needs_revision",
      title: "已打回",
      description: "被审核打回过的版本，适合对照当前包回看差异。",
      matches: (entry) => entry.reviewState === "needs_revision",
    },
    {
      key: "approved",
      title: "已通过",
      description: "已经明确通过审核的历史发布包。",
      matches: (entry) => entry.reviewState === "approved",
    },
    {
      key: "other",
      title: "其他状态",
      description: "未命中主审核状态的历史版本。",
      matches: (entry) => entry.reviewState !== "ready" && entry.reviewState !== "needs_revision" && entry.reviewState !== "approved",
    },
  ];

  return groups
    .map((group) => ({
      key: group.key,
      title: group.title,
      description: group.description,
      entries: entries.filter(group.matches),
    }))
    .filter((group) => group.entries.length > 0);
}
