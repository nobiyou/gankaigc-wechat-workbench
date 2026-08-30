import { useEffect, useMemo, useState } from "react";

import {
  fetchWechatMpHtmlStylePreview,
  fetchWechatMpHtmlStyles,
  setDefaultWechatMpHtmlStyle,
  updateWechatMpHtmlStyle,
  type WechatMpHtmlStyleItem,
  type WechatMpHtmlStylePreview,
} from "../api/workbench";
import {
  ALL_WECHAT_MP_HTML_STYLE_GROUP,
  filterWechatMpHtmlStyles,
  listWechatMpHtmlStyleGroups,
  resolveWechatMpHtmlStyleSelection,
} from "../wechatMpStyles";

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; styles: WechatMpHtmlStyleItem[] };

type PreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; preview: WechatMpHtmlStylePreview };

type NoticeState = {
  tone: "success" | "error" | "info";
  message: string;
} | null;

export function WechatHtmlStylesPage() {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [previewState, setPreviewState] = useState<PreviewState>({ status: "idle" });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState(ALL_WECHAT_MP_HTML_STYLE_GROUP);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<NoticeState>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let isCancelled = false;
    setLoadState({ status: "loading" });

    fetchWechatMpHtmlStyles()
      .then((styles) => {
        if (isCancelled) {
          return;
        }
        setLoadState({ status: "ready", styles });
        setSelectedKey((current) => resolveWechatMpHtmlStyleSelection(styles, current));
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setLoadState({
            status: "error",
            message: error instanceof Error ? error.message : "公众号排版风格加载失败。",
          });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [reloadToken]);

  const styles = loadState.status === "ready" ? loadState.styles : [];
  const groups = useMemo(() => listWechatMpHtmlStyleGroups(styles), [styles]);
  const filteredStyles = useMemo(() => filterWechatMpHtmlStyles(styles, query, group), [group, query, styles]);
  const selectedStyle = styles.find((style) => style.key === selectedKey) ?? null;
  const activeCount = styles.filter((style) => style.is_active).length;
  const defaultStyle = styles.find((style) => style.is_default) ?? null;

  useEffect(() => {
    if (!selectedKey) {
      setPreviewState({ status: "idle" });
      return;
    }

    let isCancelled = false;
    setPreviewState({ status: "loading" });
    fetchWechatMpHtmlStylePreview(selectedKey)
      .then((preview) => {
        if (!isCancelled) {
          setPreviewState({ status: "ready", preview });
        }
      })
      .catch((error: unknown) => {
        if (!isCancelled) {
          setPreviewState({
            status: "error",
            message: error instanceof Error ? error.message : "排版预览加载失败。",
          });
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [selectedKey]);

  async function reloadStyles() {
    const nextStyles = await fetchWechatMpHtmlStyles();
    setLoadState({ status: "ready", styles: nextStyles });
    setSelectedKey((current) => resolveWechatMpHtmlStyleSelection(nextStyles, current));
  }

  async function handleToggle(style: WechatMpHtmlStyleItem) {
    setPendingAction(`toggle-${style.key}`);
    setNotice(null);
    try {
      await updateWechatMpHtmlStyle(style.key, !style.is_active);
      await reloadStyles();
      setNotice({
        tone: "success",
        message: style.is_active ? `已停用「${style.name}」。` : `已启用「${style.name}」。`,
      });
    } catch (error: unknown) {
      setNotice({
        tone: "error",
        message: error instanceof Error ? error.message : "更新排版状态失败。",
      });
    } finally {
      setPendingAction(null);
    }
  }

  async function handleSetDefault(style: WechatMpHtmlStyleItem) {
    setPendingAction(`default-${style.key}`);
    setNotice(null);
    try {
      await setDefaultWechatMpHtmlStyle(style.key);
      await reloadStyles();
      setNotice({ tone: "success", message: `已将「${style.name}」设为默认排版。` });
    } catch (error: unknown) {
      setNotice({
        tone: "error",
        message: error instanceof Error ? error.message : "设置默认排版失败。",
      });
    } finally {
      setPendingAction(null);
    }
  }

  if (loadState.status === "loading") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--loading">
          <p className="dashboard-state__eyebrow">加载中</p>
          <h3>正在加载公众号排版</h3>
          <p>正在同步 15 种内置排版风格。</p>
        </div>
      </section>
    );
  }

  if (loadState.status === "error") {
    return (
      <section className="workspace-page">
        <div className="dashboard-state dashboard-state--error">
          <p className="dashboard-state__eyebrow">加载失败</p>
          <h3>公众号排版加载失败</h3>
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

  return (
    <section className="workspace-page wechat-styles-page">
      <section className="workspace-section wechat-styles-page__intro">
        <div className="workspace-section__header">
          <div>
            <p className="workspace-section__eyebrow">Settings / WeChat HTML</p>
            <h3>公众号排版风格</h3>
            <p className="workspace-section__description">
              发布包未指定项目风格时，只会从启用项中按文章场景智能选择；已生成的发布包保留原排版版本。
            </p>
          </div>
          <button className="dashboard-button dashboard-button--ghost" type="button" onClick={() => setReloadToken((value) => value + 1)}>
            刷新风格
          </button>
        </div>
        <div className="workspace-summary-grid">
          <article className="workspace-summary-card">
            <span>全部风格</span>
            <strong>{styles.length}</strong>
            <p>内置风格定义不会被删除。</p>
          </article>
          <article className="workspace-summary-card">
            <span>当前启用</span>
            <strong>{activeCount}</strong>
            <p>智能选择只在启用风格中匹配。</p>
          </article>
          <article className="workspace-summary-card">
            <span>默认排版</span>
            <strong>{defaultStyle?.name ?? "未设置"}</strong>
            <p>未命中明确场景时使用。</p>
          </article>
        </div>
      </section>

      {notice ? <div className={`workspace-note workspace-note--${notice.tone}`}>{notice.message}</div> : null}

      <div className="wechat-styles-manager">
        <section className="workspace-section wechat-styles-manager__list">
          <div className="workspace-section__header">
            <div>
              <p className="workspace-section__eyebrow">Style library</p>
              <h3>风格清单</h3>
            </div>
            <span className="workspace-pill">显示 {filteredStyles.length} / {styles.length}</span>
          </div>
          <div className="wechat-styles-filters">
            <label className="workspace-search">
              <span>搜索</span>
              <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="名称、别名或适用场景" />
            </label>
            <label className="workspace-search">
              <span>分组</span>
              <select className="workspace-select" value={group} onChange={(event) => setGroup(event.target.value)}>
                {groups.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
          </div>
          <div className="wechat-styles-list">
            {filteredStyles.map((style) => {
              const isSelected = style.key === selectedKey;
              return (
                <button
                  key={style.key}
                  className={isSelected ? "wechat-style-item wechat-style-item--selected" : "wechat-style-item"}
                  type="button"
                  aria-pressed={isSelected}
                  onClick={() => setSelectedKey(style.key)}
                >
                  <span className="wechat-style-item__topline">
                    <strong>{style.name}</strong>
                    <span className="workspace-pill">{style.is_default ? "默认" : style.is_active ? "启用" : "停用"}</span>
                  </span>
                  <span className="wechat-style-item__meta">{style.group} · {style.key}</span>
                  <span className="wechat-style-item__detail">{style.suitable_for.join("、")}</span>
                </button>
              );
            })}
          </div>
          {filteredStyles.length === 0 ? <div className="workspace-note workspace-note--info">没有匹配的排版风格。</div> : null}
        </section>

        <section className="workspace-section wechat-styles-manager__detail">
          {selectedStyle ? (
            <>
              <div className="workspace-section__header">
                <div>
                  <p className="workspace-section__eyebrow">Selected style</p>
                  <h3>{selectedStyle.name}</h3>
                  <p className="workspace-section__description">{selectedStyle.group} · {selectedStyle.key}</p>
                </div>
                <div className="wechat-style-detail__actions">
                  <label className="wechat-style-switch">
                    <input
                      type="checkbox"
                      checked={selectedStyle.is_active}
                      onChange={() => void handleToggle(selectedStyle)}
                      disabled={pendingAction !== null || (selectedStyle.is_active && activeCount <= 1)}
                    />
                    <span>{selectedStyle.is_active ? "已启用" : "已停用"}</span>
                  </label>
                  <button
                    className="dashboard-button dashboard-button--ghost"
                    type="button"
                    onClick={() => void handleSetDefault(selectedStyle)}
                    disabled={pendingAction !== null || selectedStyle.is_default}
                  >
                    {selectedStyle.is_default ? "当前默认" : "设为默认"}
                  </button>
                </div>
              </div>

              <div className="wechat-style-detail__meta">
                <div>
                  <span>别名</span>
                  <strong>{selectedStyle.aliases.join("、") || "无"}</strong>
                </div>
                <div>
                  <span>适用场景</span>
                  <strong>{selectedStyle.suitable_for.join("、") || "通用"}</strong>
                </div>
              </div>

              <div className="wechat-style-preview">
                <div className="workspace-section__header">
                  <div>
                    <p className="workspace-section__eyebrow">Live preview</p>
                    <h4>排版预览</h4>
                  </div>
                  {pendingAction === `toggle-${selectedStyle.key}` || pendingAction === `default-${selectedStyle.key}` ? (
                    <span className="workspace-pill">保存中</span>
                  ) : null}
                </div>
                {previewState.status === "loading" ? <div className="workspace-note workspace-note--info">预览加载中...</div> : null}
                {previewState.status === "error" ? <div className="workspace-note workspace-note--error">{previewState.message}</div> : null}
                {previewState.status === "ready" ? (
                  <iframe
                    className="wechat-style-preview__frame"
                    srcDoc={previewState.preview.html}
                    title={`公众号排版预览：${selectedStyle.name}`}
                    sandbox=""
                  />
                ) : null}
              </div>
            </>
          ) : (
            <div className="workspace-note workspace-note--info">请选择一种排版风格查看详情。</div>
          )}
        </section>
      </div>
    </section>
  );
}
