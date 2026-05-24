import type { TopicItem, TrackedArticleItem, TrendItem } from "./api/workbench";

export function formatTopicSourceLabel(topic: {
  source_type?: string;
  source_ref_slug?: string | null;
  trend_slug?: string | null;
}): string {
  const sourceRef = topic.source_ref_slug ?? topic.trend_slug ?? "未记录来源";
  if (topic.source_type === "manual") {
    return "原创选题 / 手动录入";
  }
  if (topic.source_type === "tracked_article") {
    return `参考文章 / ${sourceRef}`;
  }
  return `热点 / ${sourceRef}`;
}

function normalizeSearchValue(value: string): string {
  return value.trim().toLowerCase();
}

export function filterTrendsByQuery(trends: TrendItem[], query: string): TrendItem[] {
  const normalizedQuery = normalizeSearchValue(query);
  if (!normalizedQuery) {
    return trends;
  }

  return trends.filter((trend) =>
    [trend.title, trend.source, trend.slug].some((field) => field.toLowerCase().includes(normalizedQuery)),
  );
}

export function filterTrackedArticlesByQuery(trackedArticles: TrackedArticleItem[], query: string): TrackedArticleItem[] {
  const normalizedQuery = normalizeSearchValue(query);
  if (!normalizedQuery) {
    return trackedArticles;
  }

  return trackedArticles.filter((article) =>
    [
      article.title,
      article.source_name,
      article.author,
      article.summary,
      article.structure_notes,
      article.slug,
      ...article.tags,
    ].some((field) => field.toLowerCase().includes(normalizedQuery)),
  );
}

export function buildPendingTrackedArticles({
  trackedArticles,
  topics,
}: {
  trackedArticles: TrackedArticleItem[];
  topics: TopicItem[];
}): TrackedArticleItem[] {
  const convertedArticleSlugs = new Set(
    topics
      .filter((topic) => topic.source_type === "tracked_article")
      .map((topic) => topic.source_ref_slug)
      .filter((slug): slug is string => Boolean(slug)),
  );

  return trackedArticles.filter((article) => !convertedArticleSlugs.has(article.slug));
}
