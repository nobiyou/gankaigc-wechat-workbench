// @ts-ignore TS5097: the local test harness executes raw .ts modules via Node.
import { slugifyProjectTitle } from "./projectCreation.ts";

export type TopicCreateDraft = {
  title: string;
  slug: string;
  angle: string;
};

function trimRequiredValue(value: string, label: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error(`${label}不能为空`);
  }
  return trimmed;
}

export function createTopicCreateDraft(): TopicCreateDraft {
  return {
    title: "",
    slug: "",
    angle: "",
  };
}

export function syncTopicDraftTitle(current: TopicCreateDraft, nextTitle: string): TopicCreateDraft {
  const generatedSlugFromCurrentTitle = current.title ? slugifyProjectTitle(current.title) : "";
  const shouldSyncSlug = !current.slug || current.slug === generatedSlugFromCurrentTitle;

  return {
    ...current,
    title: nextTitle,
    slug: shouldSyncSlug ? slugifyProjectTitle(nextTitle) : current.slug,
  };
}

export function buildTopicCreatePayload(draft: TopicCreateDraft): TopicCreateDraft {
  return {
    title: trimRequiredValue(draft.title, "选题标题"),
    slug: trimRequiredValue(draft.slug, "选题 slug"),
    angle: trimRequiredValue(draft.angle, "选题角度"),
  };
}
