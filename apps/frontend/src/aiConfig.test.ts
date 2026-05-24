import assert from "node:assert/strict";

import { formatAiConfigBaseUrl, formatAiConfigReasoning, formatAiConfigSummaryLabel } from "./aiConfig.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("formatAiConfigBaseUrl falls back to OpenAI default when custom base url is empty", () => {
  assert.equal(formatAiConfigBaseUrl(null), "OpenAI 默认");
  assert.equal(formatAiConfigBaseUrl(""), "OpenAI 默认");
});

test("formatAiConfigSummaryLabel reflects whether api key is configured", () => {
  assert.equal(
    formatAiConfigSummaryLabel({
      api_key_configured: true,
      base_url: "https://example.com/v1",
      model: "test-model",
      image_model: "test-image-model",
      reasoning_effort: "medium",
      request_timeout_seconds: 45,
    }),
    "已配置",
  );
  assert.equal(
    formatAiConfigSummaryLabel({
      api_key_configured: false,
      base_url: null,
      model: "test-model",
      image_model: "test-image-model",
      reasoning_effort: null,
      request_timeout_seconds: 45,
    }),
    "缺少 Key",
  );
});

test("formatAiConfigReasoning falls back when reasoning effort is missing", () => {
  assert.equal(
    formatAiConfigReasoning({
      api_key_configured: true,
      base_url: null,
      model: "test-model",
      image_model: "test-image-model",
      reasoning_effort: "medium",
      request_timeout_seconds: 45,
    }),
    "medium",
  );
  assert.equal(
    formatAiConfigReasoning({
      api_key_configured: true,
      base_url: null,
      model: "test-model",
      image_model: "test-image-model",
      reasoning_effort: null,
      request_timeout_seconds: 45,
    }),
    "未设置",
  );
});
