import assert from "node:assert/strict";

import type { ProjectRetroItem } from "./api/workbench";
import { buildRetroDraft } from "./retroDraft.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildRetroDraft returns empty fields when project has no retro yet", () => {
  assert.deepEqual(buildRetroDraft(null), {
    performance_rating: "",
    summary: "",
    wins_text: "",
    gaps_text: "",
    next_focus: "",
  });
});

test("buildRetroDraft maps existing retro into editable multiline fields", () => {
  const retro: ProjectRetroItem = {
    project_slug: "project-a",
    performance_rating: 4,
    summary: "本轮标题更稳，但首屏钩子还能更强。",
    wins: ["链路闭环", "审核意见吸收及时"],
    gaps: ["封面记忆点偏弱", "导语可再短一些"],
    next_focus: "继续优化标题点击欲。",
    recorded_at: "2026-05-19T10:00:00+08:00",
  };

  assert.deepEqual(buildRetroDraft(retro), {
    performance_rating: "4",
    summary: "本轮标题更稳，但首屏钩子还能更强。",
    wins_text: "链路闭环\n审核意见吸收及时",
    gaps_text: "封面记忆点偏弱\n导语可再短一些",
    next_focus: "继续优化标题点击欲。",
  });
});
