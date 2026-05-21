export type PrimaryNavKey = "dashboard" | "sources" | "pipeline" | "projects" | "settings";

export type PrimaryNavItem = {
  key: PrimaryNavKey;
  label: string;
  to: string;
  description: string;
};

export type SectionNavItem = {
  key: string;
  label: string;
  to: string;
  description: string;
};

export type WorkbenchStage = "topic" | "outline" | "draft" | "assets" | "publish";

export const PRIMARY_NAV_ITEMS: PrimaryNavItem[] = [
  {
    key: "dashboard",
    label: "Dashboard",
    to: "/",
    description: "优先处理今天最该推进的选题、项目和发布动作。",
  },
  {
    key: "sources",
    label: "Sources",
    to: "/sources/trends",
    description: "管理热点、跟踪文章和公众号导入等来源侧动作。",
  },
  {
    key: "pipeline",
    label: "Pipeline",
    to: "/pipeline/topics",
    description: "查看批量执行、任务日志、失败项和重跑入口。",
  },
  {
    key: "projects",
    label: "Projects",
    to: "/projects",
    description: "按分组管理项目，并进入单项目 Workbench 持续生产。",
  },
  {
    key: "settings",
    label: "Settings",
    to: "/settings/tone-profiles",
    description: "维护风格配置等低频设置，不干扰日常生产界面。",
  },
];

export const SOURCES_NAV_ITEMS: SectionNavItem[] = [
  {
    key: "trends",
    label: "Trends",
    to: "/sources/trends",
    description: "浏览热点信号，并按单条方式转成候选选题。",
  },
  {
    key: "articles",
    label: "Tracked Articles",
    to: "/sources/articles",
    description: "审核跟踪文章后，再决定是否进入下游转选题。",
  },
  {
    key: "wechat-import",
    label: "WeChat Import",
    to: "/sources/wechat-import",
    description: "把公众号文章导入来源池，供后续人工审核与转选题。",
  },
];

export const PIPELINE_NAV_ITEMS: SectionNavItem[] = [
  {
    key: "topics",
    label: "Topic Queue",
    to: "/pipeline/topics",
    description: "在项目创建前集中管理待推进的选题队列。",
  },
  {
    key: "runs",
    label: "Batch Runs",
    to: "/pipeline/runs",
    description: "发起并查看批量推进任务的执行情况。",
  },
  {
    key: "tasks",
    label: "Task Log",
    to: "/pipeline/tasks",
    description: "跟踪异步状态、失败重跑和批任务聚合结果。",
  },
];

export const SETTINGS_NAV_ITEMS: SectionNavItem[] = [
  {
    key: "tone-profiles",
    label: "Tone Profiles",
    to: "/settings/tone-profiles",
    description: "维护写作风格配置，同时与生产界面保持隔离。",
  },
];

export const WORKBENCH_STAGES: Array<{ key: WorkbenchStage; label: string; description: string }> = [
  {
    key: "topic",
    label: "Topic",
    description: "确认选题定位，并完成从来源到项目的立项判断。",
  },
  {
    key: "outline",
    label: "Outline",
    description: "在写作前先搭好文章结构与推进顺序。",
  },
  {
    key: "draft",
    label: "Draft",
    description: "生成并打磨文章主体内容。",
  },
  {
    key: "assets",
    label: "Assets",
    description: "准备标题、封面文案和分发配套素材。",
  },
  {
    key: "publish",
    label: "Publish",
    description: "完成终审、发布包确认和上线前检查。",
  },
];

export const SECTION_NAV_ITEMS: Partial<Record<PrimaryNavKey, SectionNavItem[]>> = {
  sources: SOURCES_NAV_ITEMS,
  pipeline: PIPELINE_NAV_ITEMS,
  settings: SETTINGS_NAV_ITEMS,
};

export function resolvePrimaryNavKey(pathname: string): PrimaryNavKey {
  if (pathname.startsWith("/sources")) {
    return "sources";
  }
  if (pathname.startsWith("/pipeline")) {
    return "pipeline";
  }
  if (pathname.startsWith("/projects")) {
    return "projects";
  }
  if (pathname.startsWith("/settings")) {
    return "settings";
  }
  return "dashboard";
}
