export type TrackedArticleMetadataShape = {
  slug: string;
  author: string;
  summary: string;
  structure_notes: string;
  tags: string[];
};

export type TrackedArticleEnrichmentFailure = {
  slug: string;
  message: string;
};

export type AutoTrackedArticleEnrichmentResult = {
  requestedCount: number;
  eligibleCount: number;
  successCount: number;
  failures: TrackedArticleEnrichmentFailure[];
};

export function hasTrackedArticleMetadataGaps(article: TrackedArticleMetadataShape): boolean {
  return (
    !article.author.trim() ||
    !article.summary.trim() ||
    !article.structure_notes.trim() ||
    article.tags.length === 0
  );
}

export async function autoEnrichTrackedArticles(
  articles: TrackedArticleMetadataShape[],
  enrichArticle: (slug: string) => Promise<unknown>,
): Promise<AutoTrackedArticleEnrichmentResult> {
  const eligibleArticles = articles.filter(hasTrackedArticleMetadataGaps);
  const failures: TrackedArticleEnrichmentFailure[] = [];
  let successCount = 0;

  for (const article of eligibleArticles) {
    try {
      await enrichArticle(article.slug);
      successCount += 1;
    } catch (error) {
      failures.push({
        slug: article.slug,
        message: error instanceof Error ? error.message : "智能补全字段失败",
      });
    }
  }

  return {
    requestedCount: articles.length,
    eligibleCount: eligibleArticles.length,
    successCount,
    failures,
  };
}
