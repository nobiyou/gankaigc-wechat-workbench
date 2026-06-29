// @ts-ignore TS5097: the local test harness executes raw .ts modules via Node.
import { slugifyProjectTitle } from "./projectCreation.ts";
import type { TrackedArticleCreatePayload } from "./api/workbench";

export type TrackedArticleCreateDraft = {
  title: string;
  slug: string;
  url: string;
  source_name: string;
  author: string;
  summary: string;
  body_markdown: string;
  structure_notes: string;
  tags_text: string;
};

function requireTrimmedValue(value: string, label: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error(`${label}不能为空`);
  }
  return trimmed;
}

function normalizeUrl(value: string): string {
  const trimmed = requireTrimmedValue(value, "参考文章链接");

  try {
    const parsed = new URL(trimmed);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      throw new Error("unsupported protocol");
    }
    return parsed.toString();
  } catch {
    throw new Error("参考文章链接必须是有效的 http(s) 地址");
  }
}

function splitTrackedArticleTags(tagsText: string): string[] {
  return tagsText
    .split(/[，,、\n]/u)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function createTrackedArticleCreateDraft(): TrackedArticleCreateDraft {
  return {
    title: "",
    slug: "",
    url: "",
    source_name: "手动录入",
    author: "",
    summary: "",
    body_markdown: "",
    structure_notes: "",
    tags_text: "",
  };
}

export function syncTrackedArticleDraftTitle(
  current: TrackedArticleCreateDraft,
  nextTitle: string,
): TrackedArticleCreateDraft {
  const generatedSlugFromCurrentTitle = current.title ? slugifyProjectTitle(current.title) : "";
  const shouldSyncSlug = !current.slug.trim() || current.slug.trim() === generatedSlugFromCurrentTitle;

  return {
    ...current,
    title: nextTitle,
    slug: shouldSyncSlug ? slugifyProjectTitle(nextTitle) : current.slug,
  };
}

export function buildTrackedArticleCreatePayload(draft: TrackedArticleCreateDraft): TrackedArticleCreatePayload {
  const title = requireTrimmedValue(draft.title, "参考文章标题");
  const slug = draft.slug.trim() || slugifyProjectTitle(title);

  return {
    title,
    slug,
    url: normalizeUrl(draft.url),
    source_name: draft.source_name.trim() || "手动录入",
    author: draft.author.trim(),
    summary: draft.summary.trim(),
    body_markdown: draft.body_markdown.trim(),
    structure_notes: draft.structure_notes.trim(),
    tags: splitTrackedArticleTags(draft.tags_text),
  };
}
