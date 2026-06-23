from pydantic import BaseModel, Field

from app.schemas.creative_workflow import (
    BenchmarkReferenceItem,
    CreativeReviewReportItem,
    DraftQualitySummaryItem,
    DirectionalPolishLinkItem,
    DraftDiagnosisReportItem,
    ProblemBriefItem,
    ReusablePatternItem,
    StrategyCardItem,
)


class ProjectItem(BaseModel):
    slug: str
    topic_slug: str
    title: str
    stage: str
    owner: str
    preferred_tone_profile_id: int | None = None
    preferred_tone_profile_name: str | None = None
    domain_pack_key: str | None = None
    chain_status: str = "healthy"
    current_chain_state: str = "missing_outline"
    next_required_step: str | None = None
    current_outline_version: int | None = None
    current_draft_version: int | None = None
    current_assets_version: int | None = None
    current_publish_package_version: int | None = None
    retro: dict[str, object] | None = None


class ProjectCreate(BaseModel):
    slug: str
    title: str
    owner: str
    preferred_tone_profile_id: int | None = None
    domain_pack_key: str | None = None


class ProjectStageUpdate(BaseModel):
    stage: str
    preferred_tone_profile_id: int | None = None
    domain_pack_key: str | None = None


class BatchContinueProjectsRequest(BaseModel):
    project_slugs: list[str] | None = None


class BatchGenerateTopicsRequest(BaseModel):
    trend_slugs: list[str] | None = None


class BatchGenerateTopicResult(BaseModel):
    trend_slug: str
    status: str
    error: str | None = None
    topic: dict[str, object] | None = None


class BatchGenerateTopicsResponse(BaseModel):
    requested_count: int
    processed_count: int
    skipped_count: int
    failed_count: int
    results: list[BatchGenerateTopicResult]


class BatchGenerateTrackedArticleTopicsRequest(BaseModel):
    article_slugs: list[str] | None = None


class BatchGenerateTrackedArticleTopicResult(BaseModel):
    article_slug: str
    status: str
    error: str | None = None
    topic: dict[str, object] | None = None


class BatchGenerateTrackedArticleTopicsResponse(BaseModel):
    requested_count: int
    processed_count: int
    skipped_count: int
    failed_count: int
    results: list[BatchGenerateTrackedArticleTopicResult]


class BatchCreateProjectsRequest(BaseModel):
    topic_slugs: list[str] | None = None


class BatchCreateProjectResult(BaseModel):
    topic_slug: str
    status: str
    error: str | None = None
    project: ProjectItem | None = None


class BatchCreateProjectsResponse(BaseModel):
    requested_count: int
    processed_count: int
    skipped_count: int
    failed_count: int
    results: list[BatchCreateProjectResult]


class OutlineItem(BaseModel):
    project_slug: str
    version: int
    hook: str
    outline_body: str
    created_at: str | None = None
    origin: str | None = None
    tone_profile_id: int | None = None
    tone_profile_name: str | None = None


class DraftItem(BaseModel):
    project_slug: str
    outline_version: int
    version: int
    title: str
    body_markdown: str
    word_count: int
    created_at: str | None = None
    origin: str | None = None
    tone_profile_id: int | None = None
    tone_profile_name: str | None = None


class AssetItem(BaseModel):
    project_slug: str
    draft_version: int
    version: int
    title_options: list[str]
    cover_prompt: str
    cover_copy: str
    social_teaser: str
    cover_image_path: str
    cover_image_url: str
    created_at: str | None = None
    origin: str | None = None
    tone_profile_id: int | None = None
    tone_profile_name: str | None = None


class PublishPackageItem(BaseModel):
    project_slug: str
    draft_version: int
    assets_version: int
    version: int
    abstract: str
    tags: list[str]
    publish_checklist: list[str]
    editor_note: str
    markdown_path: str
    markdown_url: str
    manifest_path: str
    manifest_url: str
    status: str
    review_comment: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    created_at: str | None = None
    origin: str | None = None
    tone_profile_id: int | None = None
    tone_profile_name: str | None = None


class PublishReviewAction(BaseModel):
    reviewer: str
    comment: str


class DraftPolishAction(BaseModel):
    instruction: str | None = None
    diagnosis_report_version: int | None = None
    objective_key: str | None = None


class DiagnoseDraftAction(BaseModel):
    draft_version: int | None = None


class GenerateAssetsAction(BaseModel):
    polish_before_generate: bool = False
    polish_instruction: str | None = None


class BuildPublishPackageAction(BaseModel):
    polish_before_generate: bool = False
    polish_instruction: str | None = None


class ProjectRetroItem(BaseModel):
    project_slug: str
    performance_rating: int
    summary: str
    wins: list[str]
    gaps: list[str]
    next_focus: str
    recorded_at: str


class ProjectRetroCreate(BaseModel):
    performance_rating: int
    summary: str
    wins: list[str]
    gaps: list[str]
    next_focus: str


class ProjectDetail(BaseModel):
    project: ProjectItem
    outline: OutlineItem | None
    draft: DraftItem | None
    assets: AssetItem | None
    publish_package: PublishPackageItem | None
    retro: ProjectRetroItem | None
    problem_brief: ProblemBriefItem | None = None
    benchmarks: list[BenchmarkReferenceItem] = Field(default_factory=list)
    strategy_card: StrategyCardItem | None = None
    diagnosis_report: DraftDiagnosisReportItem | None = None
    creative_review_report: CreativeReviewReportItem | None = None
    draft_quality_summary: DraftQualitySummaryItem | None = None
    reusable_patterns: list[ReusablePatternItem] = Field(default_factory=list)
    reference_originality_report: dict[str, object] | None = None


class ProjectVersions(BaseModel):
    project_slug: str
    outlines: list[OutlineItem]
    drafts: list[DraftItem]
    assets: list[AssetItem]
    publish_packages: list[PublishPackageItem]
    strategy_cards: list[StrategyCardItem] = Field(default_factory=list)
    diagnosis_reports: list[DraftDiagnosisReportItem] = Field(default_factory=list)
    directional_polish_links: list[DirectionalPolishLinkItem] = Field(default_factory=list)
    creative_review_reports: list[CreativeReviewReportItem] = Field(default_factory=list)


class BatchContinueProjectResult(BaseModel):
    slug: str
    status: str
    started_next_step: str | None = None
    completed_steps: list[str] = Field(default_factory=list)
    error: str | None = None
    project: ProjectItem | None = None


class BatchContinueProjectsResponse(BaseModel):
    requested_count: int
    processed_count: int
    skipped_count: int
    failed_count: int
    results: list[BatchContinueProjectResult]
