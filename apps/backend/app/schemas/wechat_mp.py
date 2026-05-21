from pydantic import BaseModel

from app.schemas.tracked_articles import TrackedArticleItem


class WechatMpSessionStatus(BaseModel):
    logged_in: bool
    nickname: str | None = None
    expires_at: str | None = None
    login_stage: str | None = None
    status_message: str | None = None


class WechatMpAccountItem(BaseModel):
    fakeid: str
    nickname: str
    alias: str | None = None
    round_head_img: str | None = None
    service_type: int | None = None
    signature: str | None = None


class WechatMpArticlePreviewItem(BaseModel):
    article_id: str
    account_fakeid: str
    account_nickname: str
    title: str
    link: str
    author: str
    digest: str
    update_time: int


class WechatMpArticleImportRequest(BaseModel):
    articles: list[WechatMpArticlePreviewItem]
    fallback_account_nickname: str | None = None


class WechatMpArticleImportResult(BaseModel):
    status: str
    reason: str | None = None
    article: TrackedArticleItem | None = None


class WechatMpArticleImportResponse(BaseModel):
    run_id: int | None = None
    requested_count: int
    imported_count: int
    skipped_count: int = 0
    failed_count: int = 0
    created: list[TrackedArticleItem]
    results: list[WechatMpArticleImportResult]
