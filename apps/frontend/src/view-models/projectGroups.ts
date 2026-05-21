import type { ProjectItem } from "../api/workbench";

export type ProjectGroupKey = "chain" | "review" | "retro" | "published";

export type ProjectGroup = {
  groupKey: ProjectGroupKey;
  title: string;
  projects: ProjectItem[];
  count: number;
  filterHint: string;
};

export type ProjectGroupFilters = {
  query?: string;
  owner?: string | null;
};

function matchesFilters(project: ProjectItem, filters: ProjectGroupFilters): boolean {
  const query = filters.query?.trim().toLowerCase() ?? "";
  const owner = filters.owner?.trim().toLowerCase() ?? "";

  if (owner && project.owner.toLowerCase() !== owner) {
    return false;
  }

  if (!query) {
    return true;
  }

  return [project.slug, project.topic_slug, project.title, project.current_chain_state].some((value) =>
    value.toLowerCase().includes(query),
  );
}

export function buildProjectGroups({
  projects,
  filters = {},
}: {
  projects: ProjectItem[];
  filters?: ProjectGroupFilters;
}): ProjectGroup[] {
  const filteredProjects = projects.filter((project) => matchesFilters(project, filters));
  const chainProjects: ProjectItem[] = [];
  const reviewProjects: ProjectItem[] = [];
  const retroProjects: ProjectItem[] = [];
  const publishedProjects: ProjectItem[] = [];

  for (const project of filteredProjects) {
    if (project.current_chain_state === "publish_ready") {
      reviewProjects.push(project);
      continue;
    }
    if (project.current_chain_state === "published" && !project.retro) {
      retroProjects.push(project);
      continue;
    }
    if (project.current_chain_state === "published" && project.retro) {
      publishedProjects.push(project);
      continue;
    }
    if (project.next_required_step) {
      chainProjects.push(project);
    }
  }

  const groups: ProjectGroup[] = [
    {
      groupKey: "chain",
      title: "待续链项目",
      projects: chainProjects,
      count: 0,
      filterHint: "继续推进内容生产链上的下一步动作。",
    },
    {
      groupKey: "review",
      title: "待审稿项目",
      projects: reviewProjects,
      count: 0,
      filterHint: "发布包已就绪，等待人工审稿或回退修改。",
    },
    {
      groupKey: "retro",
      title: "待复盘项目",
      projects: retroProjects,
      count: 0,
      filterHint: "项目已发布，但还没有补齐复盘沉淀。",
    },
    {
      groupKey: "published",
      title: "已完成复盘",
      projects: publishedProjects,
      count: 0,
      filterHint: "已发布并完成复盘，可作为后续复用样本。",
    },
  ];

  return groups
    .map((group) => ({
      ...group,
      count: group.projects.length,
    }))
    .filter((group) => group.count > 0);
}
