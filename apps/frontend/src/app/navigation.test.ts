import assert from "node:assert/strict";

import {
  PIPELINE_NAV_ITEMS,
  PRIMARY_NAV_ITEMS,
  SETTINGS_NAV_ITEMS,
  SOURCES_NAV_ITEMS,
  WORKBENCH_STAGES,
  resolvePrimaryNavKey,
} from "./navigation.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("primary navigation exposes exactly five work modes", () => {
  assert.deepEqual(
    PRIMARY_NAV_ITEMS.map((item) => item.label),
    ["Dashboard", "Sources", "Pipeline", "Projects", "Settings"],
  );
});

test("secondary navigation routes match the route contract", () => {
  assert.deepEqual(
    SOURCES_NAV_ITEMS.map((item) => item.to),
    ["/sources/trends", "/sources/articles", "/sources/wechat-import"],
  );
  assert.deepEqual(
    PIPELINE_NAV_ITEMS.map((item) => item.to),
    ["/pipeline/topics", "/pipeline/runs", "/pipeline/tasks"],
  );
  assert.deepEqual(SETTINGS_NAV_ITEMS.map((item) => item.to), ["/settings/tone-profiles", "/settings/patterns"]);
});

test("resolvePrimaryNavKey maps workbench routes back to projects", () => {
  assert.equal(resolvePrimaryNavKey("/"), "dashboard");
  assert.equal(resolvePrimaryNavKey("/sources/articles"), "sources");
  assert.equal(resolvePrimaryNavKey("/pipeline/tasks"), "pipeline");
  assert.equal(resolvePrimaryNavKey("/projects/demo-project/workbench/draft"), "projects");
  assert.equal(resolvePrimaryNavKey("/settings/tone-profiles"), "settings");
  assert.equal(resolvePrimaryNavKey("/settings/patterns"), "settings");
});

test("workbench stages stay in the approved canonical order", () => {
  assert.deepEqual(
    WORKBENCH_STAGES.map((item) => item.key),
    ["topic", "outline", "draft", "assets", "publish"],
  );
});
