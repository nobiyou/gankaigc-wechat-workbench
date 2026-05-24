import type { DomainPackSummary, TopicItem } from "./api/workbench";

export type ProjectCreateDraft = {
  title: string;
  slug: string;
  owner: string;
  domain_pack_key: string | null;
  preferred_tone_profile_id: number | null;
};

export function slugifyProjectTitle(title: string): string {
  const normalized = title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
  return normalized || "project";
}

export function pickDefaultDomainPackKey(domainPacks: DomainPackSummary[]): string | null {
  return domainPacks.find((pack) => pack.is_default)?.key ?? null;
}

export function buildProjectCreateDraft(topic: Pick<TopicItem, "title" | "slug">, domainPacks: DomainPackSummary[]): ProjectCreateDraft {
  return {
    title: topic.title,
    slug: slugifyProjectTitle(topic.slug),
    owner: "editorial",
    domain_pack_key: pickDefaultDomainPackKey(domainPacks),
    preferred_tone_profile_id: null,
  };
}
