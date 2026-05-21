import type { ProjectItem, ProjectVersions } from "../api/workbench";
import type { WorkbenchStage } from "../app/navigation";

export type WorkbenchStageView = {
  key: WorkbenchStage;
  label: string;
  description: string;
  isActive: boolean;
  isRecommended: boolean;
  versionCount: number;
  targetPath: string;
};

const STAGE_META: Array<{ key: WorkbenchStage; label: string; description: string }> = [
  { key: "topic", label: "Topic", description: "选题定位与来源上下文。" },
  { key: "outline", label: "Outline", description: "结构骨架与章节安排。" },
  { key: "draft", label: "Draft", description: "正文写作与精修。" },
  { key: "assets", label: "Assets", description: "标题、封面与分发素材。" },
  { key: "publish", label: "Publish", description: "发布包、审核与回退。" },
];

function mapNextRequiredStepToStage(nextRequiredStep?: string | null): WorkbenchStage | null {
  if (nextRequiredStep === "generate_outline") {
    return "outline";
  }
  if (nextRequiredStep === "generate_draft") {
    return "draft";
  }
  if (nextRequiredStep === "generate_assets") {
    return "assets";
  }
  if (nextRequiredStep === "build_publish_package" || nextRequiredStep === "regenerate_from_review") {
    return "publish";
  }
  return null;
}

function mapCurrentChainStateToStage(currentChainState?: string | null): WorkbenchStage {
  if (!currentChainState) {
    return "topic";
  }
  if (currentChainState.includes("outline")) {
    return "outline";
  }
  if (currentChainState.includes("draft")) {
    return "draft";
  }
  if (currentChainState.includes("assets")) {
    return "assets";
  }
  if (currentChainState.includes("publish") || currentChainState.includes("published")) {
    return "publish";
  }
  return "topic";
}

function getVersionCount(stage: WorkbenchStage, versions: ProjectVersions): number {
  if (stage === "outline") {
    return versions.outlines.length;
  }
  if (stage === "draft") {
    return versions.drafts.length;
  }
  if (stage === "assets") {
    return versions.assets.length;
  }
  if (stage === "publish") {
    return versions.publish_packages.length;
  }
  return 1;
}

export function resolveRecommendedWorkbenchStage(project: ProjectItem): WorkbenchStage {
  return mapNextRequiredStepToStage(project.next_required_step) ?? mapCurrentChainStateToStage(project.current_chain_state);
}

export function buildProjectWorkbenchTarget(project: ProjectItem): string {
  return `/projects/${project.slug}/workbench/${resolveRecommendedWorkbenchStage(project)}`;
}

export function buildWorkbenchStageViews({
  project,
  activeStage,
  versions,
}: {
  project: ProjectItem;
  activeStage: WorkbenchStage;
  versions: ProjectVersions;
}): WorkbenchStageView[] {
  const recommendedStage = resolveRecommendedWorkbenchStage(project);

  return STAGE_META.map((stage) => ({
    ...stage,
    isActive: stage.key === activeStage,
    isRecommended: stage.key === recommendedStage,
    versionCount: getVersionCount(stage.key, versions),
    targetPath: `/projects/${project.slug}/workbench/${stage.key}`,
  }));
}
