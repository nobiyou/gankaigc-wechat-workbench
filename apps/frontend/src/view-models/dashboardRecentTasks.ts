import type { DashboardSummary } from "../api/workbench";
// @ts-ignore TS5097: the local test harness executes raw .ts modules via Node.
import { getTaskTypeLabel } from "../taskLabels.ts";

export type RecentTaskItem = DashboardSummary["recent_tasks"][number];

export type DashboardRecentTaskView = {
  id: string;
  label: string;
  statusLabel: string;
  timestampLabel: string;
  targetPath: string;
  targetLabel: string;
  targetHint: string;
};

function formatTaskStatusLabel(status?: string): string {
  const normalized = status?.trim().toLowerCase() ?? "";
  if (normalized === "done" || normalized === "success" || normalized === "succeeded" || normalized === "completed") {
    return "已完成";
  }
  if (normalized === "failed" || normalized === "error") {
    return "失败";
  }
  if (normalized === "skipped") {
    return "已跳过";
  }
  if (normalized === "queued") {
    return "排队中";
  }
  return "进行中";
}

function formatTimestampLabel(createdAt?: string): string {
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

function compareCreatedAtDesc(left: RecentTaskItem, right: RecentTaskItem): number {
  const leftTime = left.created_at ? Date.parse(left.created_at) : 0;
  const rightTime = right.created_at ? Date.parse(right.created_at) : 0;
  return rightTime - leftTime;
}

export function buildDashboardRecentTaskViews(recentTasks: RecentTaskItem[]): DashboardRecentTaskView[] {
  return [...recentTasks]
    .sort(compareCreatedAtDesc)
    .slice(0, 4)
    .map((task, index) => {
      const fallbackId = `${task.entity_type ?? "task"}-${task.entity_slug ?? "unknown"}-${task.id ?? index}`;

      if (task.entity_type === "project") {
        return {
          id: String(task.id ?? fallbackId),
          label: getTaskTypeLabel(task.task_type),
          statusLabel: formatTaskStatusLabel(task.status),
          timestampLabel: formatTimestampLabel(task.created_at),
          targetPath: "/projects",
          targetLabel: "查看项目列表",
          targetHint: task.entity_slug ?? "project",
        };
      }

      if (task.entity_type === "topic" && task.entity_slug) {
        return {
          id: String(task.id ?? fallbackId),
          label: getTaskTypeLabel(task.task_type),
          statusLabel: formatTaskStatusLabel(task.status),
          timestampLabel: formatTimestampLabel(task.created_at),
          targetPath: `/pipeline/topics?topic=${encodeURIComponent(task.entity_slug)}`,
          targetLabel: "查看 Topic Queue",
          targetHint: task.entity_slug,
        };
      }

      if (task.entity_type === "trend" && task.entity_slug) {
        return {
          id: String(task.id ?? fallbackId),
          label: getTaskTypeLabel(task.task_type),
          statusLabel: formatTaskStatusLabel(task.status),
          timestampLabel: formatTimestampLabel(task.created_at),
          targetPath: `/sources/trends?trend=${encodeURIComponent(task.entity_slug)}`,
          targetLabel: "回到 Sources",
          targetHint: task.entity_slug,
        };
      }

      if (task.entity_type === "tracked_article") {
        return {
          id: String(task.id ?? fallbackId),
          label: getTaskTypeLabel(task.task_type),
          statusLabel: formatTaskStatusLabel(task.status),
          timestampLabel: formatTimestampLabel(task.created_at),
          targetPath: "/sources/articles",
          targetLabel: "查看参考文章",
          targetHint: task.entity_slug ?? "tracked_article",
        };
      }

      return {
        id: String(task.id ?? fallbackId),
        label: getTaskTypeLabel(task.task_type),
        statusLabel: formatTaskStatusLabel(task.status),
        timestampLabel: formatTimestampLabel(task.created_at),
        targetPath: "/pipeline/tasks",
        targetLabel: "查看任务日志",
        targetHint: task.entity_slug ?? task.entity_type ?? "batch",
      };
    });
}
