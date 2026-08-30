import type {
  AutomationRun,
  AutomationSubscription,
  WechatMpAccountItem,
  WxChannelAccountItem,
} from "./api/workbench";

export const AUTOMATION_DEFAULT_SCHEDULE = "21:00";
export const AUTOMATION_DEFAULT_TIMEZONE = "Asia/Shanghai";
export const AUTOMATION_DEFAULT_FETCH_LIMIT = 1;

export type AutomationAccount = WechatMpAccountItem | WxChannelAccountItem;

export function createAutomationSubscriptionDraft(
  account?: AutomationAccount | null,
): {
  account_fakeid: string;
  account_biz: string;
  account_nickname: string;
  account_alias: string;
  account_avatar_url: string;
  article_source: "wechat_mp" | "wx_channel";
  schedule_time: string;
  timezone: string;
  fetch_limit: number;
  automatic_draft: boolean;
} {
  return {
    account_fakeid: account && "biz" in account ? account.biz : account?.fakeid ?? "",
    account_biz: account && "biz" in account ? account.biz : "",
    account_nickname: account?.nickname ?? "",
    account_alias: account && "biz" in account ? "" : account?.alias ?? "",
    account_avatar_url: account && "biz" in account ? account.avatar_url : account?.round_head_img ?? "",
    article_source: account && "biz" in account ? "wx_channel" : "wechat_mp",
    schedule_time: AUTOMATION_DEFAULT_SCHEDULE,
    timezone: AUTOMATION_DEFAULT_TIMEZONE,
    fetch_limit: AUTOMATION_DEFAULT_FETCH_LIMIT,
    automatic_draft: true,
  };
}

export function createAutomationSubscriptionEditDraft(
  subscription: Pick<
    AutomationSubscription,
    | "account_fakeid"
    | "account_biz"
    | "account_nickname"
    | "account_alias"
    | "account_avatar_url"
    | "article_source"
    | "schedule_time"
    | "timezone"
    | "fetch_limit"
    | "automatic_draft"
  >,
): ReturnType<typeof createAutomationSubscriptionDraft> {
  return {
    account_fakeid: subscription.account_fakeid,
    account_biz: subscription.account_biz ?? "",
    account_nickname: subscription.account_nickname,
    account_alias: subscription.account_alias ?? "",
    account_avatar_url: subscription.account_avatar_url ?? "",
    article_source: subscription.article_source,
    schedule_time: subscription.schedule_time,
    timezone: subscription.timezone,
    fetch_limit: subscription.fetch_limit,
    automatic_draft: subscription.automatic_draft,
  };
}

export function findAutomationSubscription(
  account: AutomationAccount,
  subscriptions: readonly AutomationSubscription[],
): AutomationSubscription | null {
  const identity = "biz" in account ? account.biz : account.fakeid;
  return subscriptions.find(
    (subscription) => subscription.account_fakeid === identity || subscription.account_biz === identity,
  ) ?? null;
}

export function formatAutomationSchedule(subscription: Pick<AutomationSubscription, "schedule_time" | "timezone" | "enabled">): string {
  return subscription.enabled
    ? `每天 ${subscription.schedule_time} · ${subscription.timezone}`
    : `已停用 · ${subscription.schedule_time} · ${subscription.timezone}`;
}

export function formatAutomationRunStatus(run: Pick<AutomationRun, "status" | "stage">): string {
  if (run.status === "completed") return "已完成";
  if (run.status === "failed") return `失败 · ${run.stage}`;
  if (run.status === "skipped") return `已跳过 · ${run.stage}`;
  if (run.status === "running" || run.status === "claimed") return `运行中 · ${run.stage}`;
  return `排队中 · ${run.stage}`;
}

export function canRetryAutomationRun(run: Pick<AutomationRun, "retryable" | "status">): boolean {
  return Boolean(run.retryable && (run.status === "failed" || run.status === "skipped"));
}

export function getAutomationRunDisplayTitle(run: Pick<AutomationRun, "source_article_title" | "id">): string {
  return run.source_article_title?.trim() || `自动化运行 #${run.id}`;
}

export function formatAutomationSaveError(error: unknown): string {
  const message = error instanceof Error ? error.message : "保存订阅失败。";
  if (message.toLowerCase().includes("already subscribed") || message.includes("已存在订阅") || message.includes("重复")) {
    return "该公众号已经有订阅，请在右侧订阅列表中点击“编辑”修改。";
  }
  return message;
}

export function getAutomationAccountIdentity(
  account: Pick<WechatMpAccountItem, "nickname" | "fakeid"> | Pick<WxChannelAccountItem, "nickname" | "biz">,
): string {
  return `${account.nickname} · ${"biz" in account ? account.biz : account.fakeid}`;
}
