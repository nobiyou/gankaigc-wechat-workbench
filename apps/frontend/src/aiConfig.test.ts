import assert from "node:assert/strict";

import type { AIConfigSummary } from "./api/workbench";
import {
  formatAiConfigBaseUrl,
  formatAiConfigAttemptBudget,
  formatAiConfigFallbackKeyLabel,
  formatAiConfigFallbackSourceLabel,
  formatAiConfigLocalFallbackMode,
  formatAiConfigReasoning,
  formatAiConfigRouteLabel,
  formatAiConfigSummaryLabel,
  formatAiConfigTimeoutSeconds,
  formatAiImageRouteProbeStatus,
} from "./aiConfig.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

function buildSummary(overrides: Partial<AIConfigSummary> = {}): AIConfigSummary {
  return {
    api_key_configured: true,
    base_url: null,
    model: "test-model",
    trust_env: false,
    image_model: "test-image-model",
    image_api_key_configured: true,
    image_base_url: null,
    image_request_timeout_seconds: 45,
    image_generation_max_attempts: 1,
    image_uses_dedicated_config: false,
    creative_quality_retry_max_attempts: 1,
    allow_local_creative_fallbacks: false,
    image_fallback_route_configured: false,
    image_fallback_route_active: false,
    image_fallback_model: null,
    image_fallback_base_url: null,
    image_fallback_effective_model: null,
    image_fallback_effective_base_url: null,
    image_fallback_effective_request_timeout_seconds: null,
    image_fallback_effective_api_key_configured: false,
    image_fallback_uses_inherited_model: null,
    image_fallback_uses_inherited_api_key: null,
    image_fallback_uses_inherited_base_url: null,
    image_fallback_uses_inherited_request_timeout: null,
    image_fallback_route_difference_labels: [],
    image_fallback_route_note: null,
    image_fallback_route_recovery_actions: [],
    image_fallback_route_config_hints: [],
    image_fallback_route_env_example: [],
    image_fallback_route_env_example_note: null,
    image_fallback_account_pool_diagnosis_status: "not_configured",
    image_fallback_account_pool_diagnosis_label: "未形成第二套上游",
    image_fallback_account_pool_diagnosis_note: "当前还没有配置 fallback，所以主路由一旦因为账号池问题失败，系统没有第二套图片上游可以尝试。",
    reasoning_effort: null,
    request_timeout_seconds: 45,
    ...overrides,
  };
}

test("formatAiConfigBaseUrl falls back to OpenAI default when custom base url is empty", () => {
  assert.equal(formatAiConfigBaseUrl(null), "OpenAI 默认");
  assert.equal(formatAiConfigBaseUrl(""), "OpenAI 默认");
});

test("formatAiConfigSummaryLabel reflects whether api key is configured", () => {
  assert.equal(
    formatAiConfigSummaryLabel(
      buildSummary({
        api_key_configured: true,
        base_url: "https://example.com/v1",
        image_model: "test-image-model",
        image_api_key_configured: true,
        image_base_url: "https://images.example.com/v1",
        image_request_timeout_seconds: 90,
        image_uses_dedicated_config: true,
        reasoning_effort: "medium",
      }),
    ),
    "已配置",
  );
  assert.equal(
    formatAiConfigSummaryLabel(
      buildSummary({
        api_key_configured: false,
        image_api_key_configured: false,
      }),
    ),
    "缺少 Key",
  );
});

test("formatAiConfigReasoning falls back when reasoning effort is missing", () => {
  assert.equal(
    formatAiConfigReasoning(
      buildSummary({
        reasoning_effort: "medium",
      }),
    ),
    "medium",
  );
  assert.equal(formatAiConfigReasoning(buildSummary()), "未设置");
});

test("formatAiConfigTimeoutSeconds renders configured and missing values", () => {
  assert.equal(formatAiConfigTimeoutSeconds(45), "45 秒");
  assert.equal(formatAiConfigTimeoutSeconds(null), "未配置");
});

test("formatAiConfigAttemptBudget renders bounded attempt count", () => {
  assert.equal(formatAiConfigAttemptBudget(1), "1 次");
  assert.equal(formatAiConfigAttemptBudget(2.8), "2 次");
  assert.equal(formatAiConfigAttemptBudget(-1), "0 次");
});

test("formatAiConfigLocalFallbackMode reflects creative fallback switch", () => {
  assert.equal(formatAiConfigLocalFallbackMode(buildSummary()), "关闭");
  assert.equal(formatAiConfigLocalFallbackMode(buildSummary({ allow_local_creative_fallbacks: true })), "允许");
});

test("formatAiConfigFallbackSourceLabel distinguishes inherited, dedicated, and missing states", () => {
  assert.equal(formatAiConfigFallbackSourceLabel(true, true, "继承主出图模型", "独立 fallback 模型"), "继承主出图模型");
  assert.equal(formatAiConfigFallbackSourceLabel(true, false, "继承主出图模型", "独立 fallback 模型"), "独立 fallback 模型");
  assert.equal(formatAiConfigFallbackSourceLabel(false, null, "继承主出图模型", "独立 fallback 模型"), "未配置");
});

test("formatAiConfigFallbackKeyLabel reflects effective key source", () => {
  assert.equal(
    formatAiConfigFallbackKeyLabel(
      buildSummary({
        image_fallback_route_configured: true,
        image_fallback_route_active: true,
        image_fallback_model: "backup-image-model",
        image_fallback_base_url: "https://fallback.example.com/v1",
        image_fallback_effective_model: "backup-image-model",
        image_fallback_effective_base_url: "https://fallback.example.com/v1",
        image_fallback_effective_request_timeout_seconds: 60,
        image_fallback_effective_api_key_configured: true,
        image_fallback_uses_inherited_model: false,
        image_fallback_uses_inherited_api_key: true,
        image_fallback_uses_inherited_base_url: false,
        image_fallback_uses_inherited_request_timeout: false,
        image_fallback_route_difference_labels: ["模型", "接口"],
      }),
    ),
    "继承主出图链路 Key",
  );
  assert.equal(
    formatAiConfigFallbackKeyLabel(
      buildSummary({
        image_fallback_route_configured: true,
        image_fallback_route_active: true,
        image_fallback_model: "backup-image-model",
        image_fallback_base_url: "https://fallback.example.com/v1",
        image_fallback_effective_model: "backup-image-model",
        image_fallback_effective_base_url: "https://fallback.example.com/v1",
        image_fallback_effective_request_timeout_seconds: 60,
        image_fallback_effective_api_key_configured: true,
        image_fallback_uses_inherited_model: false,
        image_fallback_uses_inherited_api_key: false,
        image_fallback_uses_inherited_base_url: false,
        image_fallback_uses_inherited_request_timeout: false,
        image_fallback_route_difference_labels: ["模型", "接口"],
      }),
    ),
    "独立 fallback Key",
  );
  assert.equal(
    formatAiConfigFallbackKeyLabel(
      buildSummary({
        image_fallback_route_configured: true,
        image_fallback_effective_model: "gpt-image-2",
        image_fallback_effective_request_timeout_seconds: 45,
        image_fallback_effective_api_key_configured: false,
        image_fallback_uses_inherited_model: true,
        image_fallback_uses_inherited_api_key: true,
        image_fallback_uses_inherited_base_url: true,
        image_fallback_uses_inherited_request_timeout: true,
      }),
    ),
    "缺少 Key",
  );
});

test("formatAiConfigRouteLabel renders primary and fallback route names", () => {
  assert.equal(formatAiConfigRouteLabel("primary"), "主出图链路");
  assert.equal(formatAiConfigRouteLabel("fallback"), "备用图片链路");
  assert.equal(formatAiConfigRouteLabel("custom"), "custom");
});

test("formatAiImageRouteProbeStatus reflects success or failure", () => {
  assert.equal(
    formatAiImageRouteProbeStatus({
      route_label: "primary",
      configured_model: "gpt-image-2",
      configured_base_url: "https://example.com/v1",
      ok: true,
      status: "ok",
      message: "ok",
      checked_at: "2026-07-17T00:00:00Z",
      recovery_actions: [],
    }),
    "检测通过",
  );
  assert.equal(
    formatAiImageRouteProbeStatus({
      route_label: "fallback",
      configured_model: "fallback-image-model",
      configured_base_url: "https://fallback.example.com/v1",
      ok: false,
      status: "upstream_error",
      message: "failed",
      checked_at: "2026-07-17T00:00:00Z",
      recovery_actions: [],
    }),
    "检测失败",
  );
});

test("formatAiImageRouteProbeStatus renders fallback setup states", () => {
  assert.equal(
    formatAiImageRouteProbeStatus({
      route_label: "fallback",
      configured_model: null,
      configured_base_url: null,
      ok: false,
      status: "not_configured",
      message: "当前未配置备用图片链路。",
      checked_at: "2026-07-17T00:00:00Z",
      recovery_actions: [],
    }),
    "未配置",
  );
  assert.equal(
    formatAiImageRouteProbeStatus({
      route_label: "fallback",
      configured_model: "gpt-image-2",
      configured_base_url: "https://example.com/v1",
      ok: false,
      status: "inactive",
      message: "已填写 fallback 字段，但生效后与主出图链路完全一致。",
      checked_at: "2026-07-17T00:00:00Z",
      recovery_actions: [],
    }),
    "未生效",
  );
});
