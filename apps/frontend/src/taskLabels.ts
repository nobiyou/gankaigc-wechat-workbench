export const taskTypeLabelMap: Record<string, string> = {
  trend_created: "录入热点",
  trend_updated: "更新热点",
  topic_created: "创建选题",
  topic_generation: "AI 生成选题",
  batch_generate_topics: "批量生成选题",
  batch_generate_topics_from_tracked_articles: "批量生成参考文章选题",
  batch_create_projects: "批量建项目",
  batch_continue_projects: "批量续链",
  topic_updated: "更新选题",
  tracked_article_created: "录入参考文章",
  project_created: "创建项目",
  outline_generation: "生成大纲",
  generate_outline: "生成大纲",
  outline_restored: "恢复大纲版本",
  draft_generation: "生成初稿",
  generate_draft: "生成初稿",
  polish_draft: "精修初稿",
  draft_polished: "精修初稿",
  draft_restored: "恢复初稿版本",
  assets_generation: "生成素材",
  generate_assets: "生成素材包",
  assets_restored: "恢复素材版本",
  publish_package_built: "导出发布包",
  build_publish_package: "生成发布包",
  approve_publish_package: "通过发布审核",
  publish_review: "发布审核",
  request_publish_revision: "请求发布修改",
  regenerate_from_review: "按审核意见重生成",
  project_retro_recorded: "记录项目复盘",
};

export function getTaskTypeLabel(taskType?: string): string {
  if (!taskType) {
    return "未知动作";
  }
  return taskTypeLabelMap[taskType] ?? taskType;
}
