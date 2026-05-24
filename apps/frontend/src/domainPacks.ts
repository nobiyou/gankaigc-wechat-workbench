import type { DomainPackSummary, ProjectItem } from "./api/workbench";

export function buildDomainPackSummaryLines(domainPack: Pick<DomainPackSummary, "audience" | "voice" | "constraints">): string[] {
  return [`受众：${domainPack.audience}`, `语气：${domainPack.voice}`, `约束：${domainPack.constraints}`];
}

export function formatProjectDomainPackLabel(
  project: Pick<ProjectItem, "domain_pack_key">,
  domainPacks: DomainPackSummary[],
): string {
  const matched = domainPacks.find((pack) => pack.key === project.domain_pack_key);
  if (matched) {
    return `项目赛道：${matched.label}`;
  }

  const fallbackDefault = domainPacks.find((pack) => pack.is_default);
  if (fallbackDefault) {
    return `项目赛道：${fallbackDefault.label}`;
  }

  return "项目赛道：默认";
}
