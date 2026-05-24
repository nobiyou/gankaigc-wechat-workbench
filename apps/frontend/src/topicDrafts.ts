import type { TopicItem } from "./api/workbench";

export type TopicDraftState = Pick<TopicItem, "title" | "angle" | "status">;

export function buildTopicDraft(topic: Pick<TopicItem, "title" | "angle" | "status">): TopicDraftState {
  return {
    title: topic.title,
    angle: topic.angle,
    status: topic.status,
  };
}

export function hasTopicDraftChanged(
  topic: Pick<TopicItem, "title" | "angle" | "status">,
  draft: Pick<TopicItem, "title" | "angle" | "status">,
): boolean {
  return topic.title !== draft.title || topic.angle !== draft.angle || topic.status !== draft.status;
}

export function formatTopicStatusLabel(status: string): string {
  if (status === "pending") {
    return "待建项目";
  }
  if (status === "drafting") {
    return "写作中";
  }
  if (status === "approved") {
    return "已确认";
  }
  if (status === "dropped") {
    return "已废弃";
  }
  return status;
}
