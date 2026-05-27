import type { ToneProfileItem, ToneProfileUpsert } from "./api/workbench";

export type ToneProfileFormState = {
  id: number;
  name: string;
  opening_style: string;
  paragraph_rhythm: string;
  closing_style: string;
  forbidden_phrases_text: string;
  value_constraints: string;
  target_word_count: string;
  default_polish_instruction: string;
};

export type ToneProfileMoveDirection = "up" | "down";

function requireTrimmedValue(value: string, label: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error(`${label}不能为空`);
  }
  return trimmed;
}

export function buildToneProfileFormState(profile: ToneProfileItem): ToneProfileFormState {
  return {
    id: profile.id,
    name: profile.name,
    opening_style: profile.opening_style,
    paragraph_rhythm: profile.paragraph_rhythm,
    closing_style: profile.closing_style,
    forbidden_phrases_text: profile.forbidden_phrases.join(", "),
    value_constraints: profile.value_constraints,
    target_word_count: String(profile.target_word_count),
    default_polish_instruction: profile.default_polish_instruction ?? "",
  };
}

export function createToneProfileFormState(): ToneProfileFormState {
  return {
    id: 0,
    name: "",
    opening_style: "",
    paragraph_rhythm: "",
    closing_style: "",
    forbidden_phrases_text: "",
    value_constraints: "",
    target_word_count: "1400",
    default_polish_instruction: "",
  };
}

export function pickEditableToneProfile(
  profiles: ToneProfileItem[],
  selectedProfileId: number | null,
): ToneProfileItem | null {
  if (selectedProfileId !== null) {
    const selectedProfile = profiles.find((profile) => profile.id === selectedProfileId);
    if (selectedProfile) {
      return selectedProfile;
    }
  }

  return profiles.find((profile) => profile.is_active) ?? profiles[0] ?? null;
}

export function sortToneProfiles(profiles: ToneProfileItem[]): ToneProfileItem[] {
  return [...profiles].sort((left, right) => {
    if (left.sort_order !== right.sort_order) {
      return left.sort_order - right.sort_order;
    }

    return left.id - right.id;
  });
}

export function formatVersionToneProfileLabel(version: { tone_profile_name: string | null }): string {
  return version.tone_profile_name ? `风格：${version.tone_profile_name}` : "风格：未记录";
}

export function formatProjectToneProfileLabel(project: { preferred_tone_profile_name: string | null }): string {
  return project.preferred_tone_profile_name
    ? `项目风格：${project.preferred_tone_profile_name}`
    : "项目风格：跟随全局";
}

export function getToneProfileSelectionLabel(
  toneProfileId: number | null,
  toneProfiles: Array<{ id: number; name: string }>,
): string {
  if (toneProfileId == null) {
    return "跟随当前全局风格";
  }

  return toneProfiles.find((profile) => profile.id === toneProfileId)?.name ?? "所选风格";
}

export function hasProjectToneProfileSelectionChanged(
  project: { preferred_tone_profile_id: number | null },
  nextToneProfileId: number | null,
): boolean {
  return project.preferred_tone_profile_id !== nextToneProfileId;
}

export function pickToneProfileSelectionAfterRemoval(
  profiles: ToneProfileItem[],
  removedProfileId: number,
): number | null {
  const remainingProfiles = profiles.filter((profile) => profile.id !== removedProfileId);
  return remainingProfiles.find((profile) => profile.is_active)?.id ?? remainingProfiles[0]?.id ?? null;
}

export function buildToneProfileReorderIds(
  profiles: ToneProfileItem[],
  profileId: number,
  direction: ToneProfileMoveDirection,
): number[] {
  const currentIndex = profiles.findIndex((profile) => profile.id === profileId);
  if (currentIndex === -1) {
    return profiles.map((profile) => profile.id);
  }

  const targetIndex = direction === "up" ? currentIndex - 1 : currentIndex + 1;
  if (targetIndex < 0 || targetIndex >= profiles.length) {
    return profiles.map((profile) => profile.id);
  }

  const reordered = [...profiles];
  const [movedProfile] = reordered.splice(currentIndex, 1);
  reordered.splice(targetIndex, 0, movedProfile);
  return reordered.map((profile) => profile.id);
}

export function buildToneProfileUpdatePayload(form: ToneProfileFormState): ToneProfileUpsert {
  const targetWordCount = Number.parseInt(form.target_word_count.trim(), 10);
  if (!Number.isInteger(targetWordCount) || targetWordCount <= 0) {
    throw new Error("目标字数必须是正整数");
  }

  return {
    name: requireTrimmedValue(form.name, "风格名称"),
    opening_style: requireTrimmedValue(form.opening_style, "开头风格"),
    paragraph_rhythm: requireTrimmedValue(form.paragraph_rhythm, "段落节奏"),
    closing_style: requireTrimmedValue(form.closing_style, "结尾风格"),
    forbidden_phrases: form.forbidden_phrases_text
      .split(/[，,]/u)
      .map((item) => item.trim())
      .filter(Boolean),
    value_constraints: requireTrimmedValue(form.value_constraints, "价值约束"),
    target_word_count: targetWordCount,
    default_polish_instruction: form.default_polish_instruction.trim(),
  };
}

export function resolveDraftPolishInstruction(
  draftInstruction: string,
  toneProfile: { default_polish_instruction?: string } | null,
): string {
  const normalizedDraftInstruction = draftInstruction.trim();
  if (normalizedDraftInstruction) {
    return normalizedDraftInstruction;
  }

  return toneProfile?.default_polish_instruction?.trim() ?? "";
}
