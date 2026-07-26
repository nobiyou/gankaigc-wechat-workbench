const projectChainStateLabelMap: Record<string, string> = {
  missing_outline: "待生成大纲",
  outline_ready: "待生成初稿",
  draft_ready: "待生成素材",
  cover_pending: "封面待补齐",
  assets_ready: "待生成发布包",
  publish_ready: "待审核发布包",
  published: "已发布",
  revision_requested: "审核打回",
};

const nextStepLabelMap: Record<string, string> = {
  generate_outline: "生成大纲",
  generate_draft: "生成初稿",
  generate_assets: "生成素材包",
  regenerate_cover_image: "重试图片 API",
  build_publish_package: "生成发布包",
  approve_publish_package: "通过发布审核",
  request_publish_revision: "请求发布修改",
  regenerate_from_review: "按审核意见重生成",
};

export function formatProjectChainStateLabel(chainState?: string | null): string {
  if (!chainState) {
    return "未知链路状态";
  }

  return projectChainStateLabelMap[chainState] ?? chainState;
}

export function formatProjectNextStepLabel(nextRequiredStep?: string | null): string {
  if (!nextRequiredStep) {
    return "已无待推进步骤";
  }

  return nextStepLabelMap[nextRequiredStep] ?? nextRequiredStep;
}
