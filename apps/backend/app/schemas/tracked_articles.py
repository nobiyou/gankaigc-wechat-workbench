from pydantic import BaseModel


class TrackedArticleItem(BaseModel):
    slug: str
    source_kind: str = "manual"
    source_name: str
    title: str
    url: str
    author: str
    summary: str
    body_markdown: str = ""
    body_source: str = "missing"
    structure_notes: str
    analysis_theme: str = ""
    analysis_core_conflict: str = ""
    analysis_emotional_exit: str = ""
    analysis_structure_mode: str = ""
    analysis_opening_pattern: str = ""
    analysis_do_not_turn_into: str = ""
    created_at: str | None = None
    tags: list[str]


class TrackedArticleCreate(TrackedArticleItem):
    pass


class TrackedArticleBatchEnrichRequest(BaseModel):
    article_slugs: list[str]


class TrackedArticleBatchEnrichResult(BaseModel):
    article_slug: str
    status: str
    error: str | None = None
    article: TrackedArticleItem | None = None


class TrackedArticleBatchEnrichResponse(BaseModel):
    requested_count: int
    processed_count: int
    skipped_count: int
    failed_count: int
    results: list[TrackedArticleBatchEnrichResult]
