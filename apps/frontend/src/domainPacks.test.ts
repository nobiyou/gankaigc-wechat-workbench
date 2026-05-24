import assert from "node:assert/strict";

import { buildDomainPackSummaryLines, formatProjectDomainPackLabel } from "./domainPacks.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

const domainPacks = [
  {
    key: "women-growth",
    label: "女性情感成长",
    audience: "女性情感成长",
    voice: "语言要克制、真实、具体",
    constraints: "避免空泛口号、说教感和鸡汤腔",
    is_default: true,
  },
  {
    key: "workplace-growth",
    label: "职场成长",
    audience: "职场成长",
    voice: "语言要冷静、务实、直接",
    constraints: "避免抒情过度、泛心理化和悬浮表达",
    is_default: false,
  },
];

test("formatProjectDomainPackLabel prefers explicit project domain pack", () => {
  assert.equal(
    formatProjectDomainPackLabel({ domain_pack_key: "workplace-growth" }, domainPacks),
    "项目赛道：职场成长",
  );
});

test("formatProjectDomainPackLabel falls back to default domain pack when project is not bound", () => {
  assert.equal(
    formatProjectDomainPackLabel({ domain_pack_key: null }, domainPacks),
    "项目赛道：女性情感成长",
  );
});

test("buildDomainPackSummaryLines exposes audience voice and constraints in readable order", () => {
  assert.deepEqual(buildDomainPackSummaryLines(domainPacks[1]), [
    "受众：职场成长",
    "语气：语言要冷静、务实、直接",
    "约束：避免抒情过度、泛心理化和悬浮表达",
  ]);
});
