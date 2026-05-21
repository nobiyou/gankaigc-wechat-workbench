import { useEffect, useState } from "react";

import {
  fetchLiveTrends,
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
import { filterTrackedArticlesByQuery, filterTrendsByQuery } from "../contentSources";

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
  const [actionSlug, setActionSlug] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [fetchingTrends, setFetchingTrends] = useState(false);

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
      setActionSlug(trendSlug);
      setActionError(null);
      const topic = await generateTopicFromTrend(trendSlug);
      setActionMessage(buildTopicCreatedMessage(topic));
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "从热点生成选题失败。");
    } finally {
      setActionSlug(null);
    }
  }

  async function handleGenerateTopicFromTrackedArticle(articleSlug: string) {
    try {
      setActionSlug(articleSlug);
      setActionError(null);
      const topic = await generateTopicFromTrackedArticle(articleSlug);
      setActionMessage(buildTopicCreatedMessage(topic));
    } catch (error: unknown) {
      setActionError(error instanceof Error ? error.message : "从参考文章生成选题失败。");
    } finally {
      setActionSlug(null);
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
    setActionMessage("参考文章池已刷新，可继续在 Sources / 参考文章 中审核新导入内容。");
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
                placeholder="按标题、来源或 slug 筛选"
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
                  </div>
                  <div className="workspace-actions">
                    <button
                      className="dashboard-button"
                      type="button"
                      onClick={() => handleGenerateTopicFromTrend(trend.slug)}
                      disabled={actionSlug === trend.slug}
                    >
                      {actionSlug === trend.slug ? "生成中..." : "AI 转选题"}
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
              <p>可以去 WeChat Import 导入新内容，或切回其他 Sources 子区继续处理输入。</p>
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
                    <span className="workspace-pill">tracked article</span>
                  </div>
                  <div className="workspace-item__meta">
                    <span>{formatTrackedArticleMeta(article)}</span>
                    <span>{article.tags.length > 0 ? `${article.tags.length} 个标签` : "无标签"}</span>
                  </div>
                  <p>{article.summary || "暂无摘要"}</p>
                  {article.tags.length > 0 ? (
                    <div className="workspace-tag-list">
                      {article.tags.map((tag) => (
                        <span key={tag} className="workspace-tag">
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <div className="workspace-actions">
                    <button
                      className="dashboard-button"
                      type="button"
                      onClick={() => handleGenerateTopicFromTrackedArticle(article.slug)}
                      disabled={actionSlug === article.slug}
                    >
                      {actionSlug === article.slug ? "生成中..." : "AI 转选题"}
                    </button>
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
