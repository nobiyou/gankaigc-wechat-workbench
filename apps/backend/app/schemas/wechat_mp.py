from pydantic import BaseModel


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


class WechatMpArticleImportResponse(BaseModel):
    imported_count: int
    created: list[dict[str, object]]
