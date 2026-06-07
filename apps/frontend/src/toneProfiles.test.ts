import assert from "node:assert/strict";

import {
  buildToneProfileFormState,
  buildToneProfileReorderIds,
  buildToneProfileUpdatePayload,
  createToneProfileFormState,
  getToneProfileSelectionLabel,
  formatVersionToneProfileLabel,
  formatProjectToneProfileLabel,
  hasProjectToneProfileSelectionChanged,
  pickToneProfileSelectionAfterRemoval,
  pickEditableToneProfile,
  resolveDraftPolishInstruction,
  sortToneProfiles,
} from "./toneProfiles.ts";

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    throw error;
  }
}

test("buildToneProfileFormState maps API tone profile into editable form values", () => {
  const form = buildToneProfileFormState({
    id: 7,
    preset_key: "women-growth-classic",
    name: "克制陪伴风",
    opening_style: "冷启动场景切入",
    paragraph_rhythm: "短段落，慢推进",
    closing_style: "留白式收束",
    forbidden_phrases: ["你必须", "立刻改变"],
    value_constraints: "不说教，不制造羞耻感",
    target_word_count: 1400,
    default_polish_instruction: "重写开头和结尾，调整段落连接。",
  });

  assert.deepEqual(form, {
    id: 7,
    preset_key: "women-growth-classic",
    name: "克制陪伴风",
    opening_style: "冷启动场景切入",
    paragraph_rhythm: "短段落，慢推进",
    closing_style: "留白式收束",
    forbidden_phrases_text: "你必须, 立刻改变",
    value_constraints: "不说教，不制造羞耻感",
    target_word_count: "1400",
    default_polish_instruction: "重写开头和结尾，调整段落连接。",
  });
});

test("createToneProfileFormState prepares an empty draft with default target word count", () => {
  assert.deepEqual(createToneProfileFormState(), {
    id: 0,
    preset_key: "",
    name: "",
    opening_style: "",
    paragraph_rhythm: "",
    closing_style: "",
    forbidden_phrases_text: "",
    value_constraints: "",
    target_word_count: "1400",
    default_polish_instruction: "",
  });
});

test("buildToneProfileUpdatePayload trims fields and splits forbidden phrases from mixed commas", () => {
  const payload = buildToneProfileUpdatePayload({
    id: 7,
    preset_key: "jinwan-youyu-answer",
    name: "  克制陪伴风  ",
    opening_style: " 冷启动场景切入 ",
    paragraph_rhythm: " 短段落，慢推进 ",
    closing_style: " 留白式收束 ",
    forbidden_phrases_text: " 你必须，立刻改变,  空话  , ",
    value_constraints: " 不说教，不制造羞耻感 ",
    target_word_count: " 1600 ",
    default_polish_instruction: " 重写开头，压缩重复表达 ",
  });

  assert.deepEqual(payload, {
    preset_key: "jinwan-youyu-answer",
    name: "克制陪伴风",
    opening_style: "冷启动场景切入",
    paragraph_rhythm: "短段落，慢推进",
    closing_style: "留白式收束",
    forbidden_phrases: ["你必须", "立刻改变", "空话"],
    value_constraints: "不说教，不制造羞耻感",
    target_word_count: 1600,
    default_polish_instruction: "重写开头，压缩重复表达",
  });
});

test("buildToneProfileUpdatePayload rejects non-positive target word counts", () => {
  assert.throws(
    () =>
      buildToneProfileUpdatePayload({
        id: 7,
        preset_key: "",
        name: "克制陪伴风",
        opening_style: "冷启动场景切入",
        paragraph_rhythm: "短段落，慢推进",
        closing_style: "留白式收束",
        forbidden_phrases_text: "你必须",
        value_constraints: "不说教",
        target_word_count: "0",
        default_polish_instruction: "",
      }),
    /目标字数必须是正整数/u,
  );
});

test("pickEditableToneProfile prefers explicit selection and otherwise falls back to active profile", () => {
  const profiles = [
    {
      id: 1,
      preset_key: "women-growth-classic",
      name: "默认风格",
      opening_style: "场景切入",
      paragraph_rhythm: "短段落",
      closing_style: "留白",
      forbidden_phrases: ["必须"],
      value_constraints: "不说教",
      target_word_count: 1400,
      is_active: false,
    },
    {
      id: 2,
      preset_key: "custom",
      name: "纪实复盘风",
      opening_style: "对话开场",
      paragraph_rhythm: "中短段交错",
      closing_style: "行动句",
      forbidden_phrases: ["绝对"],
      value_constraints: "不夸大冲突",
      target_word_count: 1800,
      is_active: true,
    },
  ];

  assert.equal(pickEditableToneProfile(profiles, null)?.id, 2);
  assert.equal(pickEditableToneProfile(profiles, 1)?.id, 1);
  assert.equal(pickEditableToneProfile(profiles, 999)?.id, 2);
});

test("formatVersionToneProfileLabel prefers recorded tone profile name and falls back when absent", () => {
  assert.equal(
    formatVersionToneProfileLabel({ tone_profile_name: "纪实关系复盘风" }),
    "风格：纪实关系复盘风",
  );
  assert.equal(
    formatVersionToneProfileLabel({ tone_profile_name: null }),
    "风格：未记录",
  );
});

test("pickToneProfileSelectionAfterRemoval falls back to active profile then first remaining item", () => {
  const profiles = [
    {
      id: 1,
      preset_key: "women-growth-classic",
      name: "默认风格",
      opening_style: "场景切入",
      paragraph_rhythm: "短段落",
      closing_style: "留白",
      forbidden_phrases: ["必须"],
      value_constraints: "不说教",
      target_word_count: 1400,
      is_active: true,
    },
    {
      id: 2,
      preset_key: "custom",
      name: "纪实复盘风",
      opening_style: "对话开场",
      paragraph_rhythm: "中短段交错",
      closing_style: "行动句",
      forbidden_phrases: ["绝对"],
      value_constraints: "不夸大冲突",
      target_word_count: 1800,
      is_active: false,
    },
  ];

  assert.equal(pickToneProfileSelectionAfterRemoval(profiles, 2), 1);
  assert.equal(pickToneProfileSelectionAfterRemoval([], 2), null);
});

test("formatProjectToneProfileLabel shows project binding and falls back to global mode", () => {
  assert.equal(
    formatProjectToneProfileLabel({ preferred_tone_profile_name: "项目专属纪实风" }),
    "项目风格：项目专属纪实风",
  );
  assert.equal(
    formatProjectToneProfileLabel({ preferred_tone_profile_name: null }),
    "项目风格：跟随全局",
  );
});

test("getToneProfileSelectionLabel shows follow-global label and specific profile names", () => {
  assert.equal(getToneProfileSelectionLabel(null, []), "跟随当前全局风格");
  assert.equal(
    getToneProfileSelectionLabel(3, [
      {
        id: 3,
        preset_key: "custom",
        name: "纪实复盘风",
        opening_style: "对话开场",
        paragraph_rhythm: "中短段交错",
        closing_style: "行动句",
        forbidden_phrases: [],
        value_constraints: "不夸大冲突",
        target_word_count: 1800,
        is_active: true,
        sort_order: 1,
      },
    ]),
    "纪实复盘风",
  );
});

test("hasProjectToneProfileSelectionChanged compares nullable project binding ids directly", () => {
  assert.equal(hasProjectToneProfileSelectionChanged({ preferred_tone_profile_id: 2 }, 2), false);
  assert.equal(hasProjectToneProfileSelectionChanged({ preferred_tone_profile_id: 2 }, null), true);
  assert.equal(hasProjectToneProfileSelectionChanged({ preferred_tone_profile_id: null }, 3), true);
});

test("buildToneProfileReorderIds swaps neighboring profiles when moving up or down", () => {
  const profiles = [
    {
      id: 1,
      preset_key: "women-growth-classic",
      name: "默认风格",
      opening_style: "场景切入",
      paragraph_rhythm: "短段落",
      closing_style: "留白",
      forbidden_phrases: ["必须"],
      value_constraints: "不说教",
      target_word_count: 1400,
      is_active: true,
      sort_order: 1,
    },
    {
      id: 2,
      preset_key: "custom",
      name: "纪实复盘风",
      opening_style: "对话开场",
      paragraph_rhythm: "中短段交错",
      closing_style: "行动句",
      forbidden_phrases: ["绝对"],
      value_constraints: "不夸大冲突",
      target_word_count: 1800,
      is_active: false,
      sort_order: 2,
    },
    {
      id: 3,
      preset_key: "jinwan-youyu-answer",
      name: "轻陪伴风",
      opening_style: "情绪切入",
      paragraph_rhythm: "松弛短句",
      closing_style: "问题收束",
      forbidden_phrases: ["赶紧"],
      value_constraints: "不下命令",
      target_word_count: 1500,
      is_active: false,
      sort_order: 3,
    },
  ];

  assert.deepEqual(buildToneProfileReorderIds(profiles, 2, "up"), [2, 1, 3]);
  assert.deepEqual(buildToneProfileReorderIds(profiles, 2, "down"), [1, 3, 2]);
  assert.deepEqual(buildToneProfileReorderIds(profiles, 1, "up"), [1, 2, 3]);
  assert.deepEqual(buildToneProfileReorderIds(profiles, 999, "down"), [1, 2, 3]);
});

test("sortToneProfiles follows backend sort_order instead of local insertion order", () => {
  const profiles = [
    {
      id: 9,
      preset_key: "custom",
      name: "第三个",
      opening_style: "A",
      paragraph_rhythm: "A",
      closing_style: "A",
      forbidden_phrases: [],
      value_constraints: "A",
      target_word_count: 1500,
      is_active: false,
      sort_order: 3,
    },
    {
      id: 7,
      preset_key: "women-growth-classic",
      name: "第一个",
      opening_style: "B",
      paragraph_rhythm: "B",
      closing_style: "B",
      forbidden_phrases: [],
      value_constraints: "B",
      target_word_count: 1400,
      is_active: true,
      sort_order: 1,
    },
    {
      id: 8,
      preset_key: "jinwan-youyu-answer",
      name: "第二个",
      opening_style: "C",
      paragraph_rhythm: "C",
      closing_style: "C",
      forbidden_phrases: [],
      value_constraints: "C",
      target_word_count: 1450,
      is_active: false,
      sort_order: 2,
    },
  ];

  assert.deepEqual(
    sortToneProfiles(profiles).map((profile) => profile.id),
    [7, 8, 9],
  );
});

test("resolveDraftPolishInstruction prefers explicit input and otherwise falls back to tone profile default", () => {
  assert.equal(
    resolveDraftPolishInstruction("  重写开头  ", { default_polish_instruction: "默认策略" }),
    "重写开头",
  );
  assert.equal(
    resolveDraftPolishInstruction("   ", { default_polish_instruction: "  默认策略  " }),
    "默认策略",
  );
  assert.equal(resolveDraftPolishInstruction("", null), "");
});
