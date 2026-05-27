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
  if (normalized === "partial") {
    return "部分完成";
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

function getCreatedAtTime(createdAt?: string): number {
  if (!createdAt) {
    return 0;
  }

  const timestamp = Date.parse(createdAt);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function compareCreatedAtDesc(left: RecentTaskItem, right: RecentTaskItem): number {
  const leftTime = getCreatedAtTime(left.created_at);
  const rightTime = getCreatedAtTime(right.created_at);
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

      if (task.entity_type === "source_ingestion_run") {
        const isWechatImport = task.task_type === "wechat_mp_import";
        return {
          id: String(task.id ?? fallbackId),
          label: getTaskTypeLabel(task.task_type),
          statusLabel: formatTaskStatusLabel(task.status),
          timestampLabel: formatTimestampLabel(task.created_at),
          targetPath: isWechatImport ? "/sources/wechat-import" : "/sources/trends",
          targetLabel: isWechatImport ? "打开公众号导入" : "打开热点池",
          targetHint: isWechatImport ? "最近公众号导入批次" : "最近热点导入批次",
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
