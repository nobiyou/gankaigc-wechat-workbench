import type { ProjectItem, TopicItem, TrendItem } from "../api/workbench";

export type DashboardQueueCardKey = "review" | "retro" | "chain" | "topic" | "trend";
export type DashboardQueueTone = "ready" | "warning" | "empty";

export type DashboardActionableItem =
  | {
      kind: "project-review";
      project: ProjectItem;
    }
  | {
      kind: "project-retro";
      project: ProjectItem;
    }
  | {
      kind: "project-chain";
      project: ProjectItem;
    }
  | {
      kind: "topic-project";
      topic: TopicItem;
    }
  | {
      kind: "trend-topic";
      trend: TrendItem;
    };

export type DashboardQueueCard = {
  key: DashboardQueueCardKey;
  title: string;
  count: number;
  summary: string;
  targetPath: string;
  tone: DashboardQueueTone;
};

export type DashboardQueueState = {
  reviewQueueProjects: ProjectItem[];
  retroQueueProjects: ProjectItem[];
  chainQueueProjects: ProjectItem[];
  topicQueueTopics: TopicItem[];
  trendQueueTrends: TrendItem[];
  actionableItems: DashboardActionableItem[];
};

export function buildTopicQueueTopics({
  topics,
  projects,
}: {
  topics: TopicItem[];
  projects: ProjectItem[];
}): TopicItem[] {
  const projectTopicSlugs = new Set(projects.map((project) => project.topic_slug));
  return topics.filter(
    (topic) => (topic.status === "pending" || topic.status === "drafting") && !projectTopicSlugs.has(topic.slug),
  );
}

export function buildTrendQueueTrends({
  trends,
  topics,
}: {
  trends: TrendItem[];
  topics: TopicItem[];
}): TrendItem[] {
  const topicTrendSlugs = new Set(topics.flatMap((topic) => (topic.trend_slug ? [topic.trend_slug] : [])));
  return trends.filter((trend) => trend.status === "screening" && !topicTrendSlugs.has(trend.slug));
}

export function buildDashboardQueueState({
  trends,
  topics,
  projects,
}: {
  trends: TrendItem[];
  topics: TopicItem[];
  projects: ProjectItem[];
}): DashboardQueueState {
  const reviewQueueProjects = projects.filter((project) => project.current_chain_state === "publish_ready");
  const retroQueueProjects = projects.filter((project) => project.current_chain_state === "published" && !project.retro);
  const chainQueueProjects = projects.filter((project) => Boolean(project.next_required_step));
  const topicQueueTopics = buildTopicQueueTopics({ topics, projects });
  const trendQueueTrends = buildTrendQueueTrends({ trends, topics });

  return {
    reviewQueueProjects,
    retroQueueProjects,
    chainQueueProjects,
    topicQueueTopics,
    trendQueueTrends,
    actionableItems: [
      ...reviewQueueProjects.map((project) => ({ kind: "project-review" as const, project })),
      ...retroQueueProjects.map((project) => ({ kind: "project-retro" as const, project })),
      ...chainQueueProjects.map((project) => ({ kind: "project-chain" as const, project })),
      ...topicQueueTopics.map((topic) => ({ kind: "topic-project" as const, topic })),
      ...trendQueueTrends.map((trend) => ({ kind: "trend-topic" as const, trend })),
    ],
  };
}

export function buildDashboardQueueCards(state: DashboardQueueState): DashboardQueueCard[] {
  return [
    {
      key: "review",
      title: "待发布审稿",
      count: state.reviewQueueProjects.length,
      summary: "进入 Projects 工作区处理待审稿发布包。",
      targetPath: "/projects",
      tone: state.reviewQueueProjects.length > 0 ? "ready" : "empty",
    },
    {
      key: "retro",
      title: "待复盘项目",
      count: state.retroQueueProjects.length,
      summary: "进入 Projects 工作区补齐发布后的复盘记录。",
      targetPath: "/projects",
      tone: state.retroQueueProjects.length > 0 ? "warning" : "empty",
    },
    {
      key: "chain",
      title: "待续链项目",
      count: state.chainQueueProjects.length,
      summary: "进入 Projects 工作区继续推进内容生产链。",
      targetPath: "/projects",
      tone: state.chainQueueProjects.length > 0 ? "warning" : "empty",
    },
    {
      key: "topic",
      title: "待建项目选题",
      count: state.topicQueueTopics.length,
      summary: "到 Pipeline 的 Topic Queue 处理选题转项目。",
      targetPath: "/pipeline/topics",
      tone: state.topicQueueTopics.length > 0 ? "warning" : "empty",
    },
    {
      key: "trend",
      title: "待转选题热点",
      count: state.trendQueueTrends.length,
      summary: "回到 Sources 处理仍处于 screening 的热点。",
      targetPath: "/sources/trends",
      tone: state.trendQueueTrends.length > 0 ? "warning" : "empty",
    },
  ];
}
