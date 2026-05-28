import assert from "node:assert/strict";

import type { WechatMpSessionStatus } from "./api/workbench.ts";
import { getWechatMpSessionRefreshDelay } from "./wechatMpSession.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("getWechatMpSessionRefreshDelay keeps fast polling while waiting for scan states", () => {
  const waitingScan: WechatMpSessionStatus = {
    logged_in: false,
    nickname: null,
    expires_at: null,
    login_stage: "waiting_scan",
    status_message: "等待扫码",
  };
  const waitingConfirmation: WechatMpSessionStatus = {
    ...waitingScan,
    login_stage: "waiting_confirmation",
    status_message: "扫码成功，等待确认",
  };

  assert.equal(getWechatMpSessionRefreshDelay(waitingScan), 2000);
  assert.equal(getWechatMpSessionRefreshDelay(waitingConfirmation), 2000);
});

test("getWechatMpSessionRefreshDelay keeps slow self-check for active logged in session", () => {
  const loggedIn: WechatMpSessionStatus = {
    logged_in: true,
    nickname: "测试公众号",
    expires_at: "2026-05-31T12:00:00+08:00",
    login_stage: "logged_in",
    status_message: "登录成功",
  };

  assert.equal(getWechatMpSessionRefreshDelay(loggedIn), 60000);
});

test("getWechatMpSessionRefreshDelay stops polling for idle logged out states", () => {
  const loggedOut: WechatMpSessionStatus = {
    logged_in: false,
    nickname: null,
    expires_at: null,
    login_stage: "expired",
    status_message: "公众号登录已过期，请重新扫码登录",
  };

  assert.equal(getWechatMpSessionRefreshDelay(loggedOut), null);
  assert.equal(getWechatMpSessionRefreshDelay(null), null);
});
