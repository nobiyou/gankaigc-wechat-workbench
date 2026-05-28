import type { WechatMpSessionStatus } from "./api/workbench.ts";

const PENDING_SESSION_REFRESH_DELAY_MS = 2000;
const ACTIVE_SESSION_REFRESH_DELAY_MS = 60000;
const POLLING_STAGES = new Set(["waiting_scan", "waiting_confirmation"]);

export function getWechatMpSessionRefreshDelay(session: WechatMpSessionStatus | null): number | null {
  if (!session) {
    return null;
  }
  if (session.logged_in) {
    return ACTIVE_SESSION_REFRESH_DELAY_MS;
  }
  if (POLLING_STAGES.has(session.login_stage ?? "")) {
    return PENDING_SESSION_REFRESH_DELAY_MS;
  }
  return null;
}
