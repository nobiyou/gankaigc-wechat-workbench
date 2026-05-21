import type { BackgroundTaskDetail } from "../api/workbench";

export function buildBackgroundTaskSummaryLines(taskDetail: BackgroundTaskDetail | null): string[] {
  if (!taskDetail?.result) {
    return [];
  }

  const requested = taskDetail.result.requested_count;
  const processed = taskDetail.result.processed_count;
  const skipped = taskDetail.result.skipped_count;
  const failed = taskDetail.result.failed_count;

  if (
    typeof requested !== "number" ||
    typeof processed !== "number" ||
    typeof skipped !== "number" ||
    typeof failed !== "number"
  ) {
    return [];
  }

  return [`请求 ${requested} 项`, `完成 ${processed} 项`, `跳过 ${skipped} 项`, `失败 ${failed} 项`];
}
