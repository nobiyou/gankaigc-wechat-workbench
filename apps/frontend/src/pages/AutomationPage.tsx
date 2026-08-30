import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import {
  createAutomationSubscription,
  disableAutomationSubscription,
  fetchAutomationRuns,
  fetchAutomationSubscriptions,
  fetchWechatMpSession,
  retryAutomationRun,
  runAutomationCycle,
  searchWechatMpAccounts,
  searchWxChannelAccounts,
  startAutomationRun,
  updateAutomationSubscription,
  type AutomationRun,
  type AutomationSubscription,
  type WechatMpSessionStatus,
} from "../api/workbench";
import {
  type AutomationAccount,
  canRetryAutomationRun,
  createAutomationSubscriptionDraft,
  createAutomationSubscriptionEditDraft,
  findAutomationSubscription,
  formatAutomationSaveError,
  formatAutomationRunStatus,
  formatAutomationSchedule,
  getAutomationAccountIdentity,
  getAutomationRunDisplayTitle,
} from "../automation";

type FormState = ReturnType<typeof createAutomationSubscriptionDraft>;

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; subscriptions: AutomationSubscription[]; runs: AutomationRun[]; session: WechatMpSessionStatus };

type Notice = { tone: "success" | "error" | "info"; message: string } | null;

function formatDateTime(value: string | null | undefined, fallback = "未记录"): string {
  if (!value) return fallback;
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(timestamp));
}

function formatDraftStatus(run: AutomationRun): string {
  if (run.draft_status === "published") return `已写入草稿箱${run.draft_id ? ` · ${run.draft_id}` : ""}`;
  if (run.draft_status === "failed") return "草稿写入失败";
  if (run.draft_status) return `草稿：${run.draft_status}`;
  return "尚未写入草稿箱";
}

function updateFormValue<K extends keyof FormState>(setForm: Dispatch<SetStateAction<FormState>>, key: K, value: FormState[K]) {
  setForm((current) => ({ ...current, [key]: value }));
}

export function AutomationPage() {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [reloadToken, setReloadToken] = useState(0);
  const [form, setForm] = useState<FormState>(() => createAutomationSubscriptionDraft());
  const [accountKeyword, setAccountKeyword] = useState("");
  const [accountSource, setAccountSource] = useState<"wechat_mp" | "wx_channel">("wx_channel");
  const [accounts, setAccounts] = useState<AutomationAccount[]>([]);
  const [accountSearchState, setAccountSearchState] = useState<"idle" | "loading" | "error">("idle");
  const [selectedAccountKey, setSelectedAccountKey] = useState<string | null>(null);
  const [editingSubscriptionId, setEditingSubscriptionId] = useState<number | null>(null);
  const [pendingAction, setPendingAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadState({ status: "loading" });
    Promise.all([fetchAutomationSubscriptions(), fetchAutomationRuns({ limit: 50 }), fetchWechatMpSession()])
      .then(([subscriptions, runs, session]) => {
        if (!cancelled) setLoadState({ status: "ready", subscriptions, runs, session });
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadState({ status: "error", message: error instanceof Error ? error.message : "自动化数据加载失败。" });
      });
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  const subscriptions = loadState.status === "ready" ? loadState.subscriptions : [];
  const runs = loadState.status === "ready" ? loadState.runs : [];
  const session = loadState.status === "ready" ? loadState.session : null;
  const activeSubscriptions = useMemo(() => subscriptions.filter((item) => item.enabled), [subscriptions]);

  async function reload() {
    setReloadToken((current) => current + 1);
  }

  async function handleSearchAccounts() {
    const keyword = accountKeyword.trim();
    if (!keyword) {
      setNotice({ tone: "info", message: "请输入公众号名称或账号关键词。" });
      return;
    }
    setAccountSearchState("loading");
    setNotice(null);
    try {
      const results = accountSource === "wx_channel"
        ? await searchWxChannelAccounts(keyword, 1, 20)
        : await searchWechatMpAccounts(keyword, 0, 10);
      setAccounts(results);
      setAccountSearchState("idle");
    } catch (error: unknown) {
      setAccountSearchState("error");
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "公众号搜索失败。" });
    }
  }

  function selectAccount(account: AutomationAccount) {
    const existing = findAutomationSubscription(account, subscriptions);
    if (existing) {
      handleEditSubscription(existing, account);
      return;
    }
    setEditingSubscriptionId(null);
    setForm(createAutomationSubscriptionDraft(account));
    setSelectedAccountKey("biz" in account ? `wx_channel:${account.biz}` : `wechat_mp:${account.fakeid}`);
    setNotice({ tone: "info", message: `已选择 ${getAutomationAccountIdentity(account)}，确认后保存订阅。` });
  }

  function handleEditSubscription(subscription: AutomationSubscription, sourceAccount?: AutomationAccount) {
    const draft = createAutomationSubscriptionEditDraft(subscription);
    const selectedSource = sourceAccount ? ("biz" in sourceAccount ? "wx_channel" : "wechat_mp") : subscription.article_source;
    if (sourceAccount) {
      draft.article_source = selectedSource;
      draft.account_fakeid = "biz" in sourceAccount ? sourceAccount.biz : sourceAccount.fakeid;
      draft.account_nickname = sourceAccount.nickname || draft.account_nickname;
      if ("biz" in sourceAccount) {
        draft.account_biz = sourceAccount.biz;
        draft.account_avatar_url = sourceAccount.avatar_url || draft.account_avatar_url;
      } else {
        draft.account_biz = "";
        draft.account_alias = sourceAccount.alias || draft.account_alias;
        draft.account_avatar_url = sourceAccount.round_head_img || draft.account_avatar_url;
      }
    }
    setEditingSubscriptionId(subscription.id);
    setAccountSource(selectedSource);
    setAccounts([]);
    setForm(draft);
    setSelectedAccountKey(
      selectedSource === "wx_channel"
        ? `wx_channel:${draft.account_biz || draft.account_fakeid}`
        : `wechat_mp:${draft.account_fakeid}`,
    );
    setNotice({
      tone: "info",
      message: sourceAccount
        ? `「${subscription.account_nickname}」已经有订阅，已打开原订阅并切换为${selectedSource === "wx_channel" ? "wx_channel 捕获" : "扫码后台"}来源；保存只会更新这一条记录。`
        : `正在编辑「${subscription.account_nickname}」的订阅设置。`,
    });
  }

  function handleCancelEdit() {
    setEditingSubscriptionId(null);
    setForm(createAutomationSubscriptionDraft());
    setSelectedAccountKey(null);
    setNotice({ tone: "info", message: "已取消编辑，未修改现有订阅。" });
  }

  async function handleSaveSubscription() {
    if (!form.account_fakeid.trim() || !form.account_nickname.trim()) {
      setNotice({ tone: "error", message: "请先从公众号目录搜索结果中选择一个公众号。" });
      return;
    }
    const subscriptionId = editingSubscriptionId;
    setPendingAction(subscriptionId === null ? "create" : `update-${subscriptionId}`);
    setNotice(null);
    try {
      if (subscriptionId === null) {
        await createAutomationSubscription({
          account_fakeid: form.account_fakeid.trim(),
          account_biz: form.account_biz.trim() || null,
          account_nickname: form.account_nickname.trim(),
          account_alias: form.account_alias.trim() || null,
          account_avatar_url: form.account_avatar_url.trim() || null,
          article_source: form.article_source,
          schedule_time: form.schedule_time,
          timezone: form.timezone.trim() || "Asia/Shanghai",
          fetch_limit: Number(form.fetch_limit),
          automatic_draft: form.automatic_draft,
        });
        setNotice({ tone: "success", message: `已保存「${form.account_nickname}」的自动草稿订阅。` });
      } else {
        await updateAutomationSubscription(subscriptionId, {
          account_fakeid: form.account_fakeid.trim(),
          account_biz: form.article_source === "wx_channel" ? form.account_biz.trim() || null : null,
          account_nickname: form.account_nickname.trim(),
          account_alias: form.account_alias.trim() || null,
          account_avatar_url: form.account_avatar_url.trim() || null,
          article_source: form.article_source,
          schedule_time: form.schedule_time,
          timezone: form.timezone.trim() || "Asia/Shanghai",
          fetch_limit: Number(form.fetch_limit),
          automatic_draft: form.automatic_draft,
        });
        setNotice({ tone: "success", message: `已更新「${form.account_nickname}」的订阅设置。` });
      }
      setForm(createAutomationSubscriptionDraft());
      setSelectedAccountKey(null);
      setEditingSubscriptionId(null);
      await reload();
    } catch (error: unknown) {
      setNotice({ tone: "error", message: formatAutomationSaveError(error) });
    } finally {
      setPendingAction(null);
    }
  }

  async function handleToggle(subscription: AutomationSubscription) {
    setPendingAction(`toggle-${subscription.id}`);
    setNotice(null);
    try {
      if (subscription.enabled) {
        await disableAutomationSubscription(subscription.id);
      } else {
        await updateAutomationSubscription(subscription.id, { enabled: true });
      }
      setNotice({ tone: "success", message: subscription.enabled ? `已停用「${subscription.account_nickname}」。` : `已恢复「${subscription.account_nickname}」。` });
      await reload();
    } catch (error: unknown) {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "更新订阅状态失败。" });
    } finally {
      setPendingAction(null);
    }
  }

  async function handleRun(subscriptionId: number) {
    setPendingAction(`run-${subscriptionId}`);
    setNotice(null);
    try {
      const submission = await startAutomationRun(subscriptionId);
      setNotice({ tone: "success", message: `已提交运行 #${submission.run_id}，正在抓取并生成草稿。` });
      await reload();
    } catch (error: unknown) {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "提交自动运行失败。" });
    } finally {
      setPendingAction(null);
    }
  }

  async function handleRetry(run: AutomationRun) {
    setPendingAction(`retry-${run.id}`);
    setNotice(null);
    try {
      const submission = await retryAutomationRun(run.id);
      setNotice({ tone: "success", message: `已提交运行 #${submission.run_id}，将沿用原工作流继续。` });
      await reload();
    } catch (error: unknown) {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "重试自动运行失败。" });
    } finally {
      setPendingAction(null);
    }
  }

  async function handleCycle() {
    setPendingAction("cycle");
    setNotice(null);
    try {
      const cycle = await runAutomationCycle();
      setNotice({ tone: "success", message: `已完成一次到期检查：评估 ${cycle.evaluated_count} 个订阅，领取 ${cycle.claimed_count} 个运行。` });
      await reload();
    } catch (error: unknown) {
      setNotice({ tone: "error", message: error instanceof Error ? error.message : "执行到期检查失败。" });
    } finally {
      setPendingAction(null);
    }
  }

  if (loadState.status === "loading") {
    return <section className="workspace-page"><div className="dashboard-state dashboard-state--loading"><p className="dashboard-state__eyebrow">Automation</p><h3>正在加载自动草稿</h3><p>正在读取订阅和最近运行记录。</p></div></section>;
  }

  if (loadState.status === "error") {
    return <section className="workspace-page"><div className="dashboard-state dashboard-state--error"><p className="dashboard-state__eyebrow">Automation</p><h3>自动化加载失败</h3><p>{loadState.message}</p><div className="dashboard-state__actions"><button className="dashboard-button" type="button" onClick={() => void reload()}>重新加载</button></div></div></section>;
  }

  return (
    <section className="workspace-page automation-page">
      <section className="workspace-section automation-page__intro">
        <div className="workspace-section__header">
          <div>
            <p className="workspace-section__eyebrow">Automation / WeChat MP</p>
            <h3>定时抓取与自动草稿</h3>
            <p className="workspace-section__description">每天按公众号自己的时区检查最新未处理文章，沿用现有改写、排版和发布包流程，最终只写入公众号草稿箱。</p>
          </div>
          <div className="automation-page__header-actions">
            <span className={session?.logged_in ? "workspace-pill workspace-pill--success" : "workspace-pill workspace-pill--warning"}>{session?.logged_in ? `扫码会话：${session.nickname ?? "已登录"}` : "扫码会话未登录"}</span>
            <button className="dashboard-button dashboard-button--ghost" type="button" onClick={() => void handleCycle()} disabled={pendingAction !== null}>{pendingAction === "cycle" ? "检查中..." : "立即检查到期订阅"}</button>
          </div>
        </div>
        <div className="workspace-summary-grid">
          <article className="workspace-summary-card"><span>启用订阅</span><strong>{activeSubscriptions.length}</strong><p>默认执行时间 21:00。</p></article>
          <article className="workspace-summary-card"><span>最近运行</span><strong>{runs.length}</strong><p>运行记录会保留失败阶段和恢复入口。</p></article>
          <article className="workspace-summary-card"><span>发布边界</span><strong>草稿箱</strong><p>自动化不会调用群发或最终发布。</p></article>
        </div>
      </section>

      {notice ? <div className={`workspace-note workspace-note--${notice.tone}`}>{notice.message}</div> : null}

      <div className="automation-page__grid">
        <section className="workspace-section automation-page__setup">
          <div className="workspace-section__header"><div><p className="workspace-section__eyebrow">Account binding</p><h3>{editingSubscriptionId === null ? "绑定公众号" : "编辑订阅"}</h3><p className="workspace-section__description">可从扫码后台搜索，或从 wx_channel 已捕获目录按 biz 订阅文章来源。</p></div></div>
          <div className="automation-source-switch" role="group" aria-label="文章来源">
            <button className={accountSource === "wx_channel" ? "automation-source-switch__item automation-source-switch__item--active" : "automation-source-switch__item"} type="button" onClick={() => { setAccountSource("wx_channel"); setAccounts([]); setSelectedAccountKey(null); setEditingSubscriptionId(null); setForm(createAutomationSubscriptionDraft()); }}>wx_channel 已捕获</button>
            <button className={accountSource === "wechat_mp" ? "automation-source-switch__item automation-source-switch__item--active" : "automation-source-switch__item"} type="button" onClick={() => { setAccountSource("wechat_mp"); setAccounts([]); setSelectedAccountKey(null); setEditingSubscriptionId(null); setForm(createAutomationSubscriptionDraft()); }}>扫码后台搜索</button>
          </div>
          <div className="automation-search-row">
            <label className="workspace-search"><span>{accountSource === "wx_channel" ? "搜索已捕获公众号" : "搜索公众号"}</span><input value={accountKeyword} onChange={(event) => setAccountKeyword(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") void handleSearchAccounts(); }} placeholder={accountSource === "wx_channel" ? "输入名称或 biz" : "输入名称或账号"} /></label>
            <button className="dashboard-button" type="button" onClick={() => void handleSearchAccounts()} disabled={accountSearchState === "loading"}>{accountSearchState === "loading" ? "搜索中..." : "搜索"}</button>
          </div>
          {accounts.length > 0 ? <div className="automation-account-results">{accounts.map((account) => { const key = "biz" in account ? `wx_channel:${account.biz}` : `wechat_mp:${account.fakeid}`; const existing = findAutomationSubscription(account, subscriptions); const detail = existing ? `已订阅 · 来源${existing.article_source === "wx_channel" ? " wx_channel 捕获" : "扫码后台"} · 点击后编辑原订阅` : "biz" in account ? `${account.sync_status || "已捕获"} · 已存 ${account.article_count} 篇文章` : account.signature || account.alias || "扫码会话可用账号"; return <button key={key} className={selectedAccountKey === key ? "automation-account-result automation-account-result--selected" : "automation-account-result"} type="button" onClick={() => selectAccount(account)}><strong>{account.nickname}</strong><span>{getAutomationAccountIdentity(account)}</span><small>{detail}</small></button>; })}</div> : <div className="workspace-note workspace-note--info">{accountSource === "wx_channel" ? "这里只显示 wx_channel 已捕获的公众号；请先在 wx_channel 打开公众号文章页完成捕获。" : "搜索结果会显示在这里。"}</div>}

          <div className="automation-selected-account"><span>当前账号 · {form.article_source === "wx_channel" ? "wx_channel" : "扫码后台"}</span><strong>{form.account_nickname || "尚未选择"}</strong><small>{form.account_biz || form.account_fakeid || "请从搜索结果选择"}</small></div>
          <div className="automation-form-grid">
            <label className="workspace-search"><span>执行时间</span><input type="time" value={form.schedule_time} onChange={(event) => updateFormValue(setForm, "schedule_time", event.target.value)} /></label>
            <label className="workspace-search"><span>时区</span><input value={form.timezone} onChange={(event) => updateFormValue(setForm, "timezone", event.target.value)} /></label>
            <label className="workspace-search"><span>每次最多处理</span><input type="number" min={1} max={10} value={form.fetch_limit} onChange={(event) => updateFormValue(setForm, "fetch_limit", Number(event.target.value))} /></label>
            <label className="automation-checkbox"><input type="checkbox" checked={form.automatic_draft} onChange={(event) => updateFormValue(setForm, "automatic_draft", event.target.checked)} /><span>自动写入公众号草稿箱</span></label>
          </div>
          <div className="workspace-actions">
            <button className="dashboard-button" type="button" onClick={() => void handleSaveSubscription()} disabled={pendingAction !== null}>{pendingAction === "create" || editingSubscriptionId !== null && pendingAction === `update-${editingSubscriptionId}` ? "保存中..." : editingSubscriptionId === null ? "保存定时订阅" : "保存订阅修改"}</button>
            {editingSubscriptionId !== null ? <button className="dashboard-button dashboard-button--ghost" type="button" onClick={handleCancelEdit} disabled={pendingAction !== null}>取消编辑</button> : null}
          </div>
        </section>

        <section className="workspace-section automation-page__subscriptions">
          <div className="workspace-section__header"><div><p className="workspace-section__eyebrow">Subscriptions</p><h3>订阅列表</h3></div><span className="workspace-pill">{subscriptions.length} 个账号</span></div>
          {subscriptions.length === 0 ? <div className="dashboard-state dashboard-state--empty"><p className="dashboard-state__eyebrow">暂无订阅</p><h3>先绑定一个公众号</h3><p>保存后，系统会在每天 21:00 检查最新文章。</p></div> : <div className="automation-subscription-list">{subscriptions.map((subscription) => <article key={subscription.id} className={subscription.enabled ? "automation-subscription" : "automation-subscription automation-subscription--disabled"}><div className="automation-subscription__header"><div><h4>{subscription.account_nickname}</h4><p>{subscription.article_source === "wx_channel" ? `biz: ${subscription.account_biz || subscription.account_fakeid}` : `fakeid: ${subscription.account_fakeid}`}{subscription.account_alias ? ` · ${subscription.account_alias}` : ""}</p></div><span className={subscription.enabled ? "workspace-pill workspace-pill--success" : "workspace-pill"}>{subscription.enabled ? "已启用" : "已停用"}</span></div><div className="automation-subscription__meta"><span>{subscription.article_source === "wx_channel" ? "来源 wx_channel" : "来源扫码后台"}</span><span>{formatAutomationSchedule(subscription)}</span><span>{subscription.enabled ? "停用后仍可手动运行" : "定时已停用，可手动运行"}</span><span>每次 {subscription.fetch_limit} 篇</span><span>{subscription.automatic_draft ? "自动写草稿" : "仅生成发布包"}</span></div><div className="automation-subscription__next"><span>下次检查：{formatDateTime(subscription.next_run_at)}</span><span>最近成功：{formatDateTime(subscription.last_success_at)}</span></div>{subscription.last_error ? <div className="workspace-note workspace-note--error">{subscription.last_error}</div> : null}<div className="workspace-actions"><button className="dashboard-button dashboard-button--compact" type="button" onClick={() => handleEditSubscription(subscription)} disabled={pendingAction !== null}>{editingSubscriptionId === subscription.id ? "编辑中..." : "编辑"}</button><button className="dashboard-button dashboard-button--compact" type="button" onClick={() => void handleRun(subscription.id)} disabled={pendingAction !== null}>{pendingAction === `run-${subscription.id}` ? "提交中..." : "立即运行"}</button><button className="dashboard-button dashboard-button--ghost dashboard-button--compact" type="button" onClick={() => void handleToggle(subscription)} disabled={pendingAction !== null}>{pendingAction === `toggle-${subscription.id}` ? "保存中..." : subscription.enabled ? "停用" : "恢复"}</button></div></article>)}</div>}
        </section>
      </div>

      <section className="workspace-section automation-page__runs">
        <div className="workspace-section__header"><div><p className="workspace-section__eyebrow">Run history</p><h3>运行记录与预览</h3><p className="workspace-section__description">每条失败记录都保留当前阶段；重试会沿用已写入的工作流，不重新创建已完成的文章。</p></div><button className="dashboard-button dashboard-button--ghost" type="button" onClick={() => void reload()} disabled={pendingAction !== null}>刷新记录</button></div>
        {runs.length === 0 ? <div className="workspace-note workspace-note--info">还没有自动化运行记录。可以点击订阅上的“立即运行”验证当前扫码会话。</div> : <div className="automation-run-list">{runs.map((run) => <article key={run.id} className="automation-run"><div className="automation-run__header"><div><h4>{getAutomationRunDisplayTitle(run)}</h4><p>运行 #{run.id} · {run.trigger === "scheduled" ? "定时" : run.trigger === "retry" ? "重试" : "手动"} · {formatDateTime(run.created_at)}</p></div><span className={run.status === "failed" ? "workspace-pill workspace-pill--danger" : run.status === "completed" ? "workspace-pill workspace-pill--success" : "workspace-pill"}>{formatAutomationRunStatus(run)}</span></div><div className="automation-run__meta"><span>抓取 {run.fetched_count} · 新增 {run.imported_count} · 跳过 {run.skipped_count}</span><span>{formatDraftStatus(run)}</span><span>{run.style_name ? `排版：${run.style_name}` : "排版待生成"}</span></div>{run.error ? <div className="workspace-note workspace-note--error"><strong>失败原因：</strong>{run.error}</div> : null}<div className="workspace-actions">{run.source_url ? <a className="dashboard-inline-link dashboard-inline-link--compact" href={run.source_url} target="_blank" rel="noreferrer">查看来源文章</a> : null}{run.project_url ? <a className="dashboard-inline-link dashboard-inline-link--compact" href={run.project_url}>打开项目预览</a> : null}{run.preview_url ? <a className="dashboard-inline-link dashboard-inline-link--compact" href={run.preview_url} target="_blank" rel="noreferrer">查看 HTML 排版</a> : null}{canRetryAutomationRun(run) ? <button className="dashboard-button dashboard-button--compact" type="button" onClick={() => void handleRetry(run)} disabled={pendingAction !== null}>{pendingAction === `retry-${run.id}` ? "提交中..." : "沿用工作流重试"}</button> : null}</div></article>)}</div>}
      </section>
    </section>
  );
}
