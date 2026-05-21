import type { WechatMpArticlePreviewItem } from "./api/workbench";

export function prepareWechatMpArticlesForImport(
  articles: WechatMpArticlePreviewItem[],
  selectedArticleIds: string[],
): WechatMpArticlePreviewItem[] {
  return articles.filter((article) => selectedArticleIds.includes(article.article_id));
}
