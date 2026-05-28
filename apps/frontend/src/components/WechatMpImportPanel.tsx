import { useEffect, useRef, useState } from "react";

import {
  fetchWechatMpArticles,
  fetchWechatMpLoginStatus,
  importWechatMpArticles,
  logoutWechatMp,
  searchWechatMpAccounts,
  startWechatMpLoginQrcode,
  type WechatMpAccountItem,
  type WechatMpArticleImportResponse,
  type WechatMpArticlePreviewItem,
  type WechatMpSessionStatus,
} from "../api/workbench";
import { getWechatMpSessionRefreshDelay } from "../wechatMpSession";
import { prepareWechatMpArticlesForImport } from "../wechatMpImport";

type WechatMpImportPanelProps = {
  session: WechatMpSessionStatus | null;
  onSessionChange: (session: WechatMpSessionStatus) => void;
  onImportComplete: (result: WechatMpArticleImportResponse) => Promise<void> | void;
  disabled?: boolean;
};

function getLoginStageLabel(session: WechatMpSessionStatus | null): string {
  if (!session) {
    return "未连接";
  }
  if (session.logged_in) {
    return "已登录";
  }
  if (session.login_stage === "waiting_confirmation") {
    return "待确认";
  }
  if (session.login_stage === "expired") {
    return "二维码已过期";
  }
  if (session.login_stage === "waiting_scan") {
    return "等待扫码";
  }
  return "未登录";
}

export function WechatMpImportPanel({
  session,
  onSessionChange,
  onImportComplete,
  disabled = false,
}: WechatMpImportPanelProps) {
  const [accountKeyword, setAccountKeyword] = useState("关系");
  const [accounts, setAccounts] = useState<WechatMpAccountItem[]>([]);
  const [selectedAccount, setSelectedAccount] = useState<WechatMpAccountItem | null>(null);
  const [articles, setArticles] = useState<WechatMpArticlePreviewItem[]>([]);
  const [selectedArticleIds, setSelectedArticleIds] = useState<string[]>([]);
  const [importResult, setImportResult] = useState<WechatMpArticleImportResponse | null>(null);
  const [qrcodeUrl, setQrcodeUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollingTimerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (qrcodeUrl) {
        URL.revokeObjectURL(qrcodeUrl);
      }
    };
  }, [qrcodeUrl]);

  useEffect(() => {
    const refreshDelay = getWechatMpSessionRefreshDelay(session);
    if (refreshDelay === null) {
      if (pollingTimerRef.current !== null) {
        window.clearTimeout(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
      return;
    }

    pollingTimerRef.current = window.setTimeout(() => {
      void refreshSessionStatus();
    }, refreshDelay);

    return () => {
      if (pollingTimerRef.current !== null) {
        window.clearTimeout(pollingTimerRef.current);
        pollingTimerRef.current = null;
      }
    };
  }, [session]);

  async function refreshSessionStatus() {
    try {
      const latestSession = await fetchWechatMpLoginStatus();
      onSessionChange(latestSession);
      if (latestSession.logged_in) {
        setQrcodeUrl((current) => {
          if (current) {
            URL.revokeObjectURL(current);
          }
          return null;
        });
      }
      if (!latestSession.logged_in) {
        setAccounts([]);
        setSelectedAccount(null);
        setArticles([]);
        setSelectedArticleIds([]);
      }
      if (latestSession.login_stage === "expired") {
        setQrcodeUrl((current) => {
          if (current) {
            URL.revokeObjectURL(current);
          }
          return null;
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新公众号登录状态失败");
    }
  }

  function toggleArticle(articleId: string) {
    setSelectedArticleIds((current) =>
      current.includes(articleId) ? current.filter((item) => item !== articleId) : [...current, articleId],
    );
  }

  async function handleStartLogin() {
    try {
      setLoading(true);
      setError(null);
      const nextQrcodeUrl = await startWechatMpLoginQrcode();
      setQrcodeUrl((current) => {
        if (current) {
          URL.revokeObjectURL(current);
        }
        return nextQrcodeUrl;
      });
      await refreshSessionStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取公众号登录二维码失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleRefreshSession() {
    try {
      setLoading(true);
      setError(null);
      await refreshSessionStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新公众号登录状态失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleLogout() {
    try {
      setLoading(true);
      setError(null);
      const latestSession = await logoutWechatMp();
      onSessionChange(latestSession);
      setQrcodeUrl((current) => {
        if (current) {
          URL.revokeObjectURL(current);
        }
        return null;
      });
      setAccounts([]);
      setSelectedAccount(null);
      setArticles([]);
      setSelectedArticleIds([]);
      setImportResult(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "退出公众号登录失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleSearchAccounts() {
    try {
      setLoading(true);
      setError(null);
      const result = await searchWechatMpAccounts(accountKeyword, 0, 5);
      setAccounts(result);
      setSelectedAccount(null);
      setArticles([]);
      setSelectedArticleIds([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "搜索公众号失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleLoadArticles(account: WechatMpAccountItem) {
    try {
      setLoading(true);
      setError(null);
      setSelectedAccount(account);
      const result = await fetchWechatMpArticles(account.fakeid, 0, 5, "");
      setArticles(result);
      setSelectedArticleIds([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "获取公众号文章列表失败");
    } finally {
      setLoading(false);
    }
  }

  async function handleImportArticles() {
    try {
      setLoading(true);
      setError(null);
      const selected = prepareWechatMpArticlesForImport(
        articles,
        selectedArticleIds,
      );
      const result = await importWechatMpArticles(selected, selectedAccount?.nickname);
      setImportResult(result);
      await onImportComplete(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入公众号文章失败");
    } finally {
      setLoading(false);
    }
  }

  const canSearchAccounts = Boolean(session?.logged_in);

  return (
    <section className="panel wechat-mp-panel">
      <div className="panel-head">
        <h2>公众号文章导入</h2>
        <span>{getLoginStageLabel(session)}</span>
      </div>
      <div className="wechat-mp-grid">
        <article className="detail-card">
          <h3>登录状态</h3>
          <p>{session?.logged_in ? `当前账号：${session.nickname ?? "未知公众号"}` : "请先登录公众号后台会话。"}</p>
          <span>{session?.expires_at ? `过期时间：${session.expires_at}` : "未建立本地会话"}</span>
          <p className="wechat-mp-hint">{session?.status_message ?? "点击获取二维码，建立本地公众号会话。"}</p>
          {qrcodeUrl ? (
            <div className="wechat-mp-qrcode-card">
              <img src={qrcodeUrl} alt="公众号登录二维码" className="wechat-mp-qrcode-image" />
            </div>
          ) : null}
          <div className="wechat-mp-actions">
            <button type="button" onClick={handleStartLogin} disabled={disabled || loading}>
              获取二维码
            </button>
            <button type="button" onClick={handleRefreshSession} disabled={disabled || loading}>
              刷新状态
            </button>
            <button type="button" onClick={handleLogout} disabled={disabled || loading}>
              退出登录
            </button>
          </div>
        </article>
        <article className="detail-card">
          <h3>搜索公众号</h3>
          <div className="quick-form wechat-mp-search-form">
            <input
              value={accountKeyword}
              onChange={(event) => setAccountKeyword(event.target.value)}
              placeholder="输入公众号名称"
              disabled={disabled || loading || !canSearchAccounts}
            />
            <button
              type="button"
              onClick={handleSearchAccounts}
              disabled={disabled || loading || !canSearchAccounts || !accountKeyword.trim()}
            >
              搜索
            </button>
          </div>
          {!canSearchAccounts ? <p className="wechat-mp-hint">登录成功后才能搜索公众号和拉取文章。</p> : null}
          <ul className="wechat-mp-list">
            {accounts.map((account) => (
              <li key={account.fakeid}>
                <div>
                  <strong>{account.nickname}</strong>
                  <p>{account.alias ? `别名：${account.alias}` : "无别名"}</p>
                </div>
                <button type="button" onClick={() => handleLoadArticles(account)} disabled={disabled || loading}>
                  查看文章
                </button>
              </li>
            ))}
          </ul>
        </article>
      </div>
      <div className="wechat-mp-grid">
        <article className="detail-card">
          <h3>{selectedAccount ? `${selectedAccount.nickname} 文章预览` : "文章预览"}</h3>
          <ul className="wechat-mp-list">
            {articles.map((article) => (
              <li key={article.article_id}>
                <label className="wechat-mp-article-select">
                  <input
                    type="checkbox"
                    checked={selectedArticleIds.includes(article.article_id)}
                    onChange={() => toggleArticle(article.article_id)}
                    disabled={disabled || loading}
                  />
                  <div>
                    <strong>{article.title}</strong>
                    <p>{article.author || article.account_nickname}</p>
                    <p>{article.digest || "暂无摘要"}</p>
                  </div>
                </label>
              </li>
            ))}
          </ul>
          <div className="wechat-mp-actions">
            <button
              type="button"
              onClick={handleImportArticles}
              disabled={disabled || loading || selectedArticleIds.length === 0}
            >
              导入到参考文章池
            </button>
          </div>
        </article>
        <article className="detail-card">
          <h3>导入结果</h3>
          <p>
            {importResult
              ? `请求 ${importResult.requested_count} 篇，新增 ${importResult.imported_count} 篇，跳过 ${importResult.skipped_count} 篇`
              : "尚未执行导入"}
          </p>
          <ul className="wechat-mp-list">
            {importResult?.results.map((result, index) => (
              <li key={result.article?.slug ?? `${result.status}-${index}`}>
                <div>
                  <strong>{result.article?.title ?? "未创建条目"}</strong>
                  <p>
                    {result.article?.source_name ?? "来源未记录"}
                    {` · ${result.status}`}
                  </p>
                  {result.reason ? <p>{result.reason}</p> : null}
                </div>
              </li>
            )) ?? []}
          </ul>
        </article>
      </div>
      {error ? <p className="error">{error}</p> : null}
    </section>
  );
}
