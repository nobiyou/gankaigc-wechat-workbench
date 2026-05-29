import { useEffect, useState } from "react";

import {
  enrichTrackedArticlesMetadataInBackground,
  createTrackedArticle,
  enrichTrackedArticleMetadata,
  fetchLiveTrends,
  refreshTrackedArticleBody,
  fetchTrackedArticles,
  fetchTrends,
  fetchWechatMpSession,
  generateTopicFromTrackedArticle,
  generateTopicFromTrend,
  type TopicItem,
  type TrackedArticleItem,
  type TrendItem,
  type WechatMpArticleImportResponse,
  type WechatMpSessionStatus,
} from "../api/workbench";
import { WechatMpImportPanel } from "../components/WechatMpImportPanel";
import {
  buildTrendSummaryPreview,
  filterTrackedArticlesByQuery,
  filterTrendsByQuery,
  shouldCollapseTrendSummary,
} from "../contentSources";
import { hasTrackedArticleMetadataGaps } from "../trackedArticleEnrichment";
import {
  buildTrackedArticleCreatePayload,
  createTrackedArticleCreateDraft,
  syncTrackedArticleDraftTitle,
} from "../trackedArticleCreation";

type SourcesSection = "trends" | "articles" | "wechat-import";

type SourcesData = {
  trends: TrendItem[];
  trackedArticles: TrackedArticleItem[];
  session: WechatMpSessionStatus | null;
};

type SourcesLoadState =
  | {
      status: "loading";
    }
  | {
      status: "error";
      message: string;
    }
  | {
      status: "ready";
      data: SourcesData;
    };

type SourceActionKey =
  | "trend-generate-topic"
  | "tracked-article-enrich-metadata"
  | "tracked-article-generate-topic"
  | "tracked-article-refresh-body";

const SECTION_COPY: Record<SourcesSection, { title: string; description: string }> = {
  trends: {
    title: "热点池与单条转选题",
    description: "Sources 负责采集、浏览、筛选和单条动作，不在这里承接批量结果总览。",
  },
  articles: {
    title: "参考文章浏览与单条转选题",
    description: "参考文章保持来源层视角，先看素材质量，再决定是否生成单条选题。",
  },
  "wechat-import": {
    title: "公众号文章导入",
    description: "公众号导入属于 Sources，导入后仍先回到来源层审核，不直接跳成批量任务中心。",
  },
};

function buildTopicCreatedMessage(topic: TopicItem): string {
  return `已生成选题：${topic.title}`;
}

function formatTrackedArticleMeta(article: TrackedArticleItem): string {
  return [article.source_name, article.author].filter(Boolean).join(" / ");
}

function formatTrackedArticleSourceKind(article: TrackedArticleItem): string {
  return article.source_kind === "wechat_mp_import" ? "公众号导入" : "手动录入";
}

function formatTrackedArticleCreatedAt(article: TrackedArticleItem): string {
  if (!article.created_at) {
    return "入池时间未记录";
  }

  const parsed = Date.parse(article.created_at);
  if (Number.isNaN(parsed)) {
    return `入池时间：${article.created_at}`;
  }

  return `入池时间：${new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(parsed))}`;
}

function formatDateTimeLabel(label: string, value: string | null | undefined, fallback: string): string {
  if (!value) {
    return `${label}：${fallback}`;
  }

  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return `${label}：${value}`;
  }

  return `${label}：${new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(parsed))}`;
}

function formatTrackedArticleBodySource(article: TrackedArticleItem): string {
  switch (article.body_source) {
    case "dom":
      return "正文来源：静态 DOM";
    case "content_noencode":
      return "正文来源：脚本正文数据";
    case "digest_fallback":
      return "正文来源：摘要回退";
    case "manual":
      return "正文来源：手动录入";
    default:
      return "正文来源：未识别";
  }
}

function loadSourcesData(section: SourcesSection): Promise<SourcesData> {
  if (section === "trends") {
    return fetchTrends().then((trends) => ({
      trends,
      trackedArticles: [],
      session: null,
    }));
  }

  if (section === "articles") {
    return fetchTrackedArticles().then((trackedArticles) => ({
      trends: [],
      trackedArticles,
      session: null,
    }));
  }

  return Promise.all([fetchWechatMpSession(), fetchTrackedArticles()]).then(([session, trackedArticles]) => ({
    trends: [],
    trackedArticles,
    session,
  }));
}

export function SourcesPage({ section }: { section: SourcesSection }) {
  const [loadState, setLoadState] = useState<SourcesLoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);
  const [searchQuery, setSearchQuery] = useState("");
  const [trackedArticleDraft, setTrackedArticleDraft] = useState(createTrackedArticleCreateDraft);
  const [activeAction, setActiveAction] = useState<{ key: SourceActionKey; slug: string } | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [fetchingTrends, setFetchingTrends] = useState(false);
  const [creatingTrackedArticle, setCreatingTrackedArticle] = useState(false);
  const [expandedTrendSlugs, setExpandedTrendSlugs] = useState<string[]>([]);
  const [expandedArticleSlugs, setExpandedArticleSlugs] = useState<string[]>([]);

  useEffect(() => {
    let isCancelled = false;
    setLoadState({ status: "loading" });
    setActionMessage(null);
    setActionError(null);

    loadSourcesData(section)
      .then((data) => {
        if (!isCancelled) {
          setLoadState({ status: "ready", data });
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "Sources 数据加载失败。",
          });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [reloadToken, section]);

  useEffect(() => {
    setSearchQuery("");
  }, [section]);

  async function handleGenerateTopicFromTrend(trendSlug: string) {
    try {
      setActiveAction({ key: "trend-generate-topic", slug: trendSlug });
      setActionError(null);
      const topic = await generateTopicFromTrend(trendSlug);
      setActionMessage(buildTopicCreatedMessage(topic));
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "从热点生成选题失败。");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleGenerateTopicFromTrackedArticle(articleSlug: string) {
    try {
      setActiveAction({ key: "tracked-article-generate-topic", slug: articleSlug });
      setActionError(null);
      const topic = await generateTopicFromTrackedArticle(articleSlug);
      setActionMessage(buildTopicCreatedMessage(topic));
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "从参考文章生成选题失败。");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleRefreshTrackedArticleBody(articleSlug: string) {
    try {
      setActiveAction({ key: "tracked-article-refresh-body", slug: articleSlug });
      setActionError(null);
      const refreshed = await refreshTrackedArticleBody(articleSlug);
      setActionMessage(`已重新抓取正文：${refreshed.title}`);
      setReloadToken((current) => current + 1);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "重新抓正文失败");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleEnrichTrackedArticleMetadata(articleSlug: string) {
    try {
      setActiveAction({ key: "tracked-article-enrich-metadata", slug: articleSlug });
      setActionError(null);
      const enriched = await enrichTrackedArticleMetadata(articleSlug);
      setActionMessage(`已智能补全字段：${enriched.title}`);
      setReloadToken((current) => current + 1);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "智能补全字段失败");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleCreateTrackedArticle() {
    try {
      setCreatingTrackedArticle(true);
      setActionError(null);
      const payload = buildTrackedArticleCreatePayload(trackedArticleDraft);
      const created = await createTrackedArticle(payload);
      await enrichTrackedArticleMetadata(created.slug);
      const trackedArticles = await fetchTrackedArticles();
      setLoadState((current) =>
        current.status === "ready"
          ? {
              status: "ready",
              data: {
                ...current.data,
                trackedArticles,
              },
            }
          : current,
      );
      setTrackedArticleDraft(createTrackedArticleCreateDraft());
      setSearchQuery("");
      setActionMessage(`已录入参考文章并自动补全字段：${created.title}`);
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "手动录入参考文章失败。");
    } finally {
      setCreatingTrackedArticle(false);
    }
  }

  async function handleFetchLiveTrends() {
    try {
      setFetchingTrends(true);
      setActionError(null);
      const result = await fetchLiveTrends();
      const trends = await fetchTrends();
      setLoadState((current) =>
        current.status === "ready"
          ? {
              status: "ready",
              data: {
                ...current.data,
                trends,
              },
            }
          : current,
      );
      setActionMessage(
        `实时抓取完成：新增 ${result.created_count} 条，跳过 ${result.skipped_count} 条，处理来源 ${result.processed_source_count}/${result.requested_source_count} 个。`,
      );
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "抓取实时热点失败。");
    } finally {
      setFetchingTrends(false);
    }
  }

  function handleWechatSessionChange(session: WechatMpSessionStatus) {
    setLoadState((current) =>
      current.status === "ready"
        ? {
            status: "ready",
            data: {
              ...current.data,
              session,
            },
          }
        : current,
    );
  }

  async function handleWechatImportComplete(_result: WechatMpArticleImportResponse) {
    const trackedArticles = await fetchTrackedArticles();
    const latestImportedArticles = trackedArticles.filter((article) => article.source_kind === "wechat_mp_import").slice(0, 5);
    const articleSlugsToEnrich = latestImportedArticles.filter(hasTrackedArticleMetadataGaps).map((article) => article.slug);
    setLoadState((current) =>
      current.status === "ready"
        ? {
            status: "ready",
            data: {
              ...current.data,
              trackedArticles,
            },
          }
        : current,
    );
    if (articleSlugsToEnrich.length === 0) {
      setActionMessage("参考文章池已刷新，最近导入文章的字段已经完整。");
    } else {
      const submission = await enrichTrackedArticlesMetadataInBackground(articleSlugsToEnrich);
      setActionMessage(
        `参考文章池已刷新，已提交 ${articleSlugsToEnrich.length} 篇最近导入文章的智能补全任务，可去 Pipeline 查看进度。任务 ID：${submission.task_id}`,
      );
    }
    setActionError(null);
  }

  if (loadState.status === "loading") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--loading">
          <p className="dashboard-state__eyebrow">加载中</p>
          <h3>正在加载 Sources</h3>
          <p>正在同步当前来源视图的数据与单条处理入口。</p>
        </div>
      </section>
    );
  }

  if (loadState.status === "error") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--error">
          <p className="dashboard-state__eyebrow">加载失败</p>
          <h3>Sources 加载失败</h3>
          <p>{loadState.message}</p>
          <div className="dashboard-state__actions">
            <button className="dashboard-button" type="button" onClick={() => setReloadToken((value) => value + 1)}>
              重新加载
            </button>
          </div>
        </div>
      </section>
    );
  }

  const content = SECTION_COPY[section];
  const visibleTrends = filterTrendsByQuery(loadState.data.trends, searchQuery);
  const visibleTrackedArticles = filterTrackedArticlesByQuery(loadState.data.trackedArticles, searchQuery);

  return (
    <section className="workspace-page">
      <section className="workspace-section">
        <div className="workspace-section__header">
          <div>
            <p className="workspace-section__eyebrow">Sources</p>
            <h3>{content.title}</h3>
            <p className="workspace-section__description">{content.description}</p>
          </div>
        </div>
        <div className="workspace-summary-grid">
          <article className="workspace-summary-card">
            <span>当前子区</span>
            <strong>{section === "trends" ? "热点来源" : section === "articles" ? "参考文章" : "公众号导入"}</strong>
          </article>
          <article className="workspace-summary-card">
            <span>工作边界</span>
            <strong>单条处理</strong>
            <p>批量结果、任务日志和失败重试统一留在 Pipeline。</p>
          </article>
        </div>
      </section>

      {actionMessage ? (
        <div className="workspace-note workspace-note--success">
          <p>{actionMessage}</p>
        </div>
      ) : null}

      {actionError ? (
        <div className="workspace-note workspace-note--error">
          <p>{actionError}</p>
        </div>
      ) : null}

      {section === "trends" ? (
        <section className="workspace-section">
          <div className="workspace-toolbar">
            <label className="workspace-search">
              <span>搜索热点</span>
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="按标题、摘要、来源、链接或 slug 筛选"
              />
            </label>
            <div className="workspace-toolbar__meta">
              <span>共 {loadState.data.trends.length} 条</span>
              <span>筛选后 {visibleTrends.length} 条</span>
            </div>
            <button type="button" className="dashboard-button" onClick={handleFetchLiveTrends} disabled={fetchingTrends}>
              {fetchingTrends ? "抓取中..." : "立即抓取"}
            </button>
          </div>

          <div className="workspace-note workspace-note--info">
            <p>实时抓取依赖后端 `.env` 里的 `TREND_FEED_URLS` 配置；未配置时会直接返回明确错误。</p>
          </div>

          {visibleTrends.length === 0 ? (
            <div className="dashboard-state dashboard-state--empty">
              <p className="dashboard-state__eyebrow">暂无数据</p>
              <h3>当前没有可展示热点</h3>
              <p>可以调整搜索词，或稍后回到 Sources 补充新的热点输入。</p>
            </div>
          ) : (
            <div className="workspace-list">
              {visibleTrends.map((trend) => (
                <article key={trend.slug} className="workspace-item">
                  <div className="workspace-item__header">
                    <div>
                      <h4>{trend.title}</h4>
                      <p>{trend.slug}</p>
                    </div>
                    <span className="workspace-pill">{trend.status}</span>
                  </div>
                  <div className="workspace-item__meta">
                    <span>来源：{trend.source}</span>
                    <span>热度：{trend.heat_score}</span>
                    <span>{formatDateTimeLabel("发布时间", trend.published_at, "未记录")}</span>
                    <span>{formatDateTimeLabel("抓取时间", trend.fetched_at, "未记录")}</span>
                  </div>
                  {(() => {
                    const summary = trend.summary?.trim() || "当前热点仅收录了标题，尚未带出摘要。";
                    const canCollapse = shouldCollapseTrendSummary(summary);
                    const isExpanded = expandedTrendSlugs.includes(trend.slug);
                    const displayedSummary = canCollapse && !isExpanded ? buildTrendSummaryPreview(summary) : summary;

                    return (
                      <p className="trend-card__summary">{displayedSummary}</p>
                    );
                  })()}
                  <div className="workspace-actions workspace-actions--row trend-card__actions">
                    {(() => {
                      const summary = trend.summary?.trim() || "";
                      const canCollapse = shouldCollapseTrendSummary(summary);
                      const isExpanded = expandedTrendSlugs.includes(trend.slug);
                      if (!canCollapse) {
                        return null;
                      }
                      return (
                        <button
                          className="dashboard-button dashboard-button--ghost dashboard-button--compact"
                          type="button"
                          onClick={() =>
                            setExpandedTrendSlugs((current) =>
                              current.includes(trend.slug)
                                ? current.filter((slug) => slug !== trend.slug)
                                : [...current, trend.slug],
                            )
                          }
                        >
                          {isExpanded ? "收起内容" : "展开内容"}
                        </button>
                      );
                    })()}
                    {trend.link ? (
                      <a
                        className="dashboard-inline-link dashboard-inline-link--compact"
                        href={trend.link}
                        target="_blank"
                        rel="noreferrer"
                      >
                        查看来源
                      </a>
                    ) : null}
                    <button
                      className="dashboard-button dashboard-button--compact"
                      type="button"
                      onClick={() => handleGenerateTopicFromTrend(trend.slug)}
                      disabled={activeAction?.slug === trend.slug}
                    >
                      {activeAction?.slug === trend.slug && activeAction.key === "trend-generate-topic"
                        ? "生成中..."
                        : "AI 转选题"}
                    </button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {section === "articles" ? (
        <section className="workspace-section">
          <div className="workspace-subsection workspace-project-config-panel">
            <div className="workspace-section__header">
              <div>
                <p className="workspace-section__eyebrow">Manual Tracked Article</p>
                <h4>手动录入参考文章</h4>
                <p className="workspace-section__description">适合把外部参考稿、手头样稿或单篇链接直接录入来源池，再继续转选题。</p>
              </div>
            </div>
            <div className="quick-form workspace-actions--row">
              <label className="workspace-search workspace-search--compact">
                <span>文章标题</span>
                <input
                  value={trackedArticleDraft.title}
                  onChange={(event) =>
                    setTrackedArticleDraft((current) => syncTrackedArticleDraftTitle(current, event.target.value))
                  }
                  placeholder="例如：成年后最养人的关系，常常只是一起吃饭散步"
                />
              </label>
              <label className="workspace-search workspace-search--compact">
                <span>文章 slug</span>
                <input
                  value={trackedArticleDraft.slug}
                  onChange={(event) =>
                    setTrackedArticleDraft((current) => ({
                      ...current,
                      slug: event.target.value,
                    }))
                  }
                  placeholder="默认随标题生成"
                />
              </label>
              <label className="workspace-search">
                <span>原文链接</span>
                <input
                  value={trackedArticleDraft.url}
                  onChange={(event) =>
                    setTrackedArticleDraft((current) => ({
                      ...current,
                      url: event.target.value,
                    }))
                  }
                  placeholder="粘贴完整文章链接，例如 https://mp.weixin.qq.com/..."
                />
              </label>
            </div>
            <div className="quick-form workspace-actions--row">
              <label className="workspace-search workspace-search--compact">
                <span>来源账号</span>
                <input
                  value={trackedArticleDraft.source_name}
                  onChange={(event) =>
                    setTrackedArticleDraft((current) => ({
                      ...current,
                      source_name: event.target.value,
                    }))
                  }
                  placeholder="默认手动录入"
                />
              </label>
              <label className="workspace-search workspace-search--compact">
                <span>作者</span>
                <input
                  value={trackedArticleDraft.author}
                  onChange={(event) =>
                    setTrackedArticleDraft((current) => ({
                      ...current,
                      author: event.target.value,
                    }))
                  }
                  placeholder="可留空"
                />
              </label>
              <label className="workspace-search">
                <span>标签</span>
                <input
                  value={trackedArticleDraft.tags_text}
                  onChange={(event) =>
                    setTrackedArticleDraft((current) => ({
                      ...current,
                      tags_text: event.target.value,
                    }))
                  }
                  placeholder="用逗号、顿号或换行分隔，例如 陪伴，安全感，女性成长"
                />
              </label>
            </div>
            <div className="quick-form workspace-actions--row">
              <label className="workspace-search">
                <span>摘要</span>
                <textarea
                  value={trackedArticleDraft.summary}
                  onChange={(event) =>
                    setTrackedArticleDraft((current) => ({
                      ...current,
                      summary: event.target.value,
                    }))
                  }
                  placeholder="提炼这篇参考文章的主题、情绪和核心判断"
                />
              </label>
              <label className="workspace-search">
                <span>全文</span>
                <textarea
                  value={trackedArticleDraft.body_markdown}
                  onChange={(event) =>
                    setTrackedArticleDraft((current) => ({
                      ...current,
                      body_markdown: event.target.value,
                    }))
                  }
                  placeholder="手动录入时可直接粘贴全文；公众号导入文章会尽量自动带入正文。"
                />
              </label>
              <label className="workspace-search">
                <span>结构备注</span>
                <textarea
                  value={trackedArticleDraft.structure_notes}
                  onChange={(event) =>
                    setTrackedArticleDraft((current) => ({
                      ...current,
                      structure_notes: event.target.value,
                    }))
                  }
                  placeholder="可记录开头切入、段落推进、收束方式等结构观察"
                />
              </label>
            </div>
            <div className="workspace-actions workspace-actions--row workspace-actions--project-config">
              <button className="dashboard-button" type="button" disabled={creatingTrackedArticle} onClick={() => void handleCreateTrackedArticle()}>
                {creatingTrackedArticle ? "录入中..." : "录入参考文章"}
              </button>
              <button
                className="dashboard-button dashboard-button--ghost"
                type="button"
                disabled={creatingTrackedArticle}
                onClick={() => setTrackedArticleDraft(createTrackedArticleCreateDraft())}
              >
                清空草稿
              </button>
            </div>
            <div className="workspace-note workspace-note--info">
              <p>标题会自动联动 slug，手动改过 slug 后会保留自定义值。</p>
              <p>录入后会先留在参考文章池审核，再决定是否转成选题。</p>
            </div>
          </div>

          <div className="workspace-toolbar">
            <label className="workspace-search">
              <span>搜索参考文章</span>
              <input
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="按标题、作者、标签或 slug 筛选"
              />
            </label>
            <div className="workspace-toolbar__meta">
              <span>共 {loadState.data.trackedArticles.length} 篇</span>
              <span>筛选后 {visibleTrackedArticles.length} 篇</span>
            </div>
          </div>

          {visibleTrackedArticles.length === 0 ? (
            <div className="dashboard-state dashboard-state--empty">
              <p className="dashboard-state__eyebrow">暂无数据</p>
              <h3>当前没有可展示参考文章</h3>
              <p>可以先在上方手动录入，或去 WeChat Import 导入新内容，再回到这里审核。</p>
            </div>
          ) : (
            <div className="workspace-list">
              {visibleTrackedArticles.map((article) => (
                <article key={article.slug} className="workspace-item">
                  <div className="workspace-item__header">
                    <div>
                      <h4>{article.title}</h4>
                      <p>{article.slug}</p>
                    </div>
                    <span className="workspace-pill">{formatTrackedArticleSourceKind(article)}</span>
                  </div>
                  <div className="workspace-item__meta">
                    <span>{formatTrackedArticleMeta(article)}</span>
                    <span>{formatTrackedArticleCreatedAt(article)}</span>
                    <span>{article.tags.length > 0 ? `${article.tags.length} 个标签` : "无标签"}</span>
                  </div>
                  <p>{article.summary || "暂无摘要"}</p>
                  <div className="workspace-note workspace-note--info">
                    <p>{article.body_markdown ? "已收录正文，可展开全文预览。" : "当前只收录了摘要，尚未拿到全文内容。"}</p>
                    <p>{formatTrackedArticleBodySource(article)}</p>
                    <p>{article.structure_notes || "暂无结构备注"}</p>
                  </div>
                  {expandedArticleSlugs.includes(article.slug) && article.body_markdown ? (
                    <pre className="workbench-preview__body">{article.body_markdown}</pre>
                  ) : null}
                  <div className="tracked-article-card__footer">
                    {article.tags.length > 0 ? (
                      <div className="workspace-tag-list">
                        {article.tags.map((tag) => (
                          <span key={tag} className="workspace-tag">
                            {tag}
                          </span>
                        ))}
                      </div>
                    ) : null}
                    <div className="tracked-article-card__actions">
                      {article.url ? (
                        <a
                          className="dashboard-inline-link dashboard-inline-link--compact"
                          href={article.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          查看原文
                        </a>
                      ) : null}
                      <button
                        className="dashboard-button dashboard-button--ghost dashboard-button--compact"
                        type="button"
                        onClick={() =>
                          setExpandedArticleSlugs((current) =>
                            current.includes(article.slug)
                              ? current.filter((slug) => slug !== article.slug)
                              : [...current, article.slug],
                          )
                        }
                        disabled={!article.body_markdown}
                      >
                        {expandedArticleSlugs.includes(article.slug) ? "收起全文" : "预览全文"}
                      </button>
                      <button
                        className="dashboard-button dashboard-button--ghost dashboard-button--compact"
                        type="button"
                        onClick={() => handleEnrichTrackedArticleMetadata(article.slug)}
                        disabled={activeAction?.slug === article.slug}
                      >
                        {activeAction?.slug === article.slug && activeAction.key === "tracked-article-enrich-metadata"
                          ? "补全中..."
                          : "智能补全字段"}
                      </button>
                      <button
                        className="dashboard-button dashboard-button--ghost dashboard-button--compact"
                        type="button"
                        onClick={() => handleRefreshTrackedArticleBody(article.slug)}
                        disabled={activeAction?.slug === article.slug || !article.url}
                      >
                        {activeAction?.slug === article.slug && activeAction.key === "tracked-article-refresh-body"
                          ? "抓取中..."
                          : "重新抓正文"}
                      </button>
                      <button
                        className="dashboard-button dashboard-button--compact"
                        type="button"
                        onClick={() => handleGenerateTopicFromTrackedArticle(article.slug)}
                        disabled={activeAction?.slug === article.slug}
                      >
                        {activeAction?.slug === article.slug && activeAction.key === "tracked-article-generate-topic"
                          ? "生成中..."
                          : "AI 转选题"}
                      </button>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {section === "wechat-import" ? (
        <>
          <section className="workspace-section">
            <div className="workspace-section__header">
              <div>
                <p className="workspace-section__eyebrow">WeChat Import</p>
                <h4>公众号导入与来源确认</h4>
                <p className="workspace-section__description">
                  导入动作发生在 Sources，导入后的内容仍先留在来源层审核，再决定是否进入 Topic Queue。
                </p>
              </div>
            </div>
            <WechatMpImportPanel
              session={loadState.data.session}
              onSessionChange={handleWechatSessionChange}
              onImportComplete={handleWechatImportComplete}
            />
          </section>

          <section className="workspace-section">
            <div className="workspace-section__header">
              <div>
                <p className="workspace-section__eyebrow">Tracked Articles</p>
                <h4>最近来源文章</h4>
              </div>
            </div>
            {loadState.data.trackedArticles.length === 0 ? (
              <div className="dashboard-state dashboard-state--empty">
                <p className="dashboard-state__eyebrow">Empty</p>
                <h3>还没有导入到 Tracked Articles 的文章</h3>
                <p>完成一次公众号导入后，这里会展示最近进入来源池的文章。</p>
              </div>
            ) : (
              <div className="workspace-list">
                {loadState.data.trackedArticles.slice(0, 5).map((article) => (
                  <article key={article.slug} className="workspace-item">
                    <div className="workspace-item__header">
                      <div>
                        <h4>{article.title}</h4>
                        <p>{article.slug}</p>
                      </div>
                      <span className="workspace-pill">review source</span>
                    </div>
                    <div className="workspace-item__meta">
                      <span>{formatTrackedArticleMeta(article)}</span>
                      <span>{article.url}</span>
                    </div>
                    <div className="tracked-article-card__actions">
                      <button
                        className="dashboard-button dashboard-button--ghost dashboard-button--compact"
                        type="button"
                        onClick={() => handleEnrichTrackedArticleMetadata(article.slug)}
                        disabled={activeAction?.slug === article.slug}
                      >
                        {activeAction?.slug === article.slug && activeAction.key === "tracked-article-enrich-metadata"
                          ? "补全中..."
                          : "智能补全字段"}
                      </button>
                      <button
                        className="dashboard-button dashboard-button--ghost dashboard-button--compact"
                        type="button"
                        onClick={() => handleRefreshTrackedArticleBody(article.slug)}
                        disabled={activeAction?.slug === article.slug || !article.url}
                      >
                        {activeAction?.slug === article.slug && activeAction.key === "tracked-article-refresh-body"
                          ? "抓取中..."
                          : "重新抓正文"}
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>
        </>
      ) : null}
    </section>
  );
}
