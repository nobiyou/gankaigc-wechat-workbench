import type { DomainPackSummary, ToneProfileItem } from "./api/workbench";

export function buildProjectConfigPreviewLines(params: {
  domainPacks: DomainPackSummary[];
  domainPackKey: string | null;
  toneProfiles: ToneProfileItem[];
  toneProfileId: number | null;
}): string[] {
  const selectedDomainPack =
    params.domainPacks.find((pack) => pack.key === params.domainPackKey) ??
    params.domainPacks.find((pack) => pack.is_default) ??
    null;
  const selectedToneProfile =
    params.toneProfiles.find((profile) => profile.id === params.toneProfileId) ??
    params.toneProfiles.find((profile) => profile.is_active) ??
    params.toneProfiles[0] ??
    null;

  const lines: string[] = [];

  if (selectedDomainPack) {
    lines.push(`后续大纲、初稿、素材和发布包将按「${selectedDomainPack.label}」赛道语境生成。`);
    lines.push(`赛道语气：${selectedDomainPack.voice}`);
  }

  if (selectedToneProfile) {
    lines.push(`风格约束：${selectedToneProfile.name} · 开头 ${selectedToneProfile.opening_style} · 结尾 ${selectedToneProfile.closing_style}`);
  }

  return lines;
}
