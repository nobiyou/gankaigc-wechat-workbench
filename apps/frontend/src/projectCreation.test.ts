import assert from "node:assert/strict";

import { buildProjectCreateDraft, pickDefaultDomainPackKey, slugifyProjectTitle } from "./projectCreation.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("slugifyProjectTitle normalizes mixed separators into a compact slug", () => {
  assert.equal(slugifyProjectTitle(" 职场 表达 / 修复 周更 "), "职场-表达-修复-周更");
});

test("pickDefaultDomainPackKey returns default key when present", () => {
  assert.equal(
    pickDefaultDomainPackKey([
      {
        key: "women-growth",
        label: "女性情感成长",
        audience: "女性情感成长",
        voice: "语言要克制、真实、具体",
        constraints: "避免空泛口号、说教感和鸡汤腔",
        is_default: true,
      },
    ]),
    "women-growth",
  );
});

test("buildProjectCreateDraft pre-fills title slug owner and default domain pack", () => {
  const draft = buildProjectCreateDraft(
    { title: "关系边界重设系列", slug: "relationship-boundary-reset-playbook" },
    [
      {
        key: "women-growth",
        label: "女性情感成长",
        audience: "女性情感成长",
        voice: "语言要克制、真实、具体",
        constraints: "避免空泛口号、说教感和鸡汤腔",
        is_default: true,
      },
    ],
  );

  assert.equal(draft.title, "关系边界重设系列");
  assert.equal(draft.slug, "relationship-boundary-reset-playbook");
  assert.equal(draft.owner, "editorial");
  assert.equal(draft.domain_pack_key, "women-growth");
  assert.equal(draft.preferred_tone_profile_id, null);
});
