from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.schemas.tracked_articles import TrackedArticleCreate
from app.schemas.wechat_mp import (
    WechatMpAccountItem,
    WechatMpArticleImportRequest,
    WechatMpArticleImportResponse,
    WechatMpArticleImportResult,
    WechatMpArticlePreviewItem,
    WechatMpSessionStatus,
)
from app.services.wechat_mp_client import get_wechat_mp_client
from app.services.workbench import import_tracked_articles


router = APIRouter(prefix="/wechat-mp", tags=["wechat-mp"])


@router.get("/session")
def get_wechat_mp_session() -> dict[str, object]:
    payload = get_wechat_mp_client().get_session_status()
    return WechatMpSessionStatus(**payload).model_dump()


@router.post("/login/qrcode")
def post_wechat_mp_login_qrcode() -> Response:
    payload = get_wechat_mp_client().start_login_qrcode()
    return Response(content=payload["image_bytes"], media_type=str(payload["content_type"]))


@router.get("/login/status")
def get_wechat_mp_login_status() -> dict[str, object]:
    payload = get_wechat_mp_client().poll_login_status()
    return WechatMpSessionStatus(**payload).model_dump()


@router.post("/logout")
def post_wechat_mp_logout() -> dict[str, object]:
    payload = get_wechat_mp_client().logout()
    return WechatMpSessionStatus(**payload).model_dump()


@router.get("/accounts")
def get_wechat_mp_accounts(keyword: str, begin: int = 0, size: int = 5) -> list[dict[str, object]]:
    accounts = get_wechat_mp_client().search_accounts(keyword=keyword, begin=begin, size=size)
    return [WechatMpAccountItem(**item).model_dump() for item in accounts]


@router.get("/accounts/{fakeid}/articles")
def get_wechat_mp_articles(
    fakeid: str,
    begin: int = 0,
    size: int = 5,
    keyword: str = "",
) -> list[dict[str, object]]:
    articles = get_wechat_mp_client().list_articles(fakeid=fakeid, begin=begin, size=size, keyword=keyword)
    return [WechatMpArticlePreviewItem(**item).model_dump() for item in articles]


@router.post("/articles/import", status_code=status.HTTP_201_CREATED)
def post_wechat_mp_articles_import(payload: WechatMpArticleImportRequest) -> dict[str, object]:
    result = get_wechat_mp_client().import_articles(payload)
    created_payloads = [TrackedArticleCreate(**item) for item in result.get("created", [])]
    imported = import_tracked_articles(created_payloads, source_kind="wechat_mp_import")
    return WechatMpArticleImportResponse(
        run_id=imported.get("run_id"),
        requested_count=int(imported.get("requested_count", result.get("requested_count", 0))),
        imported_count=int(imported.get("imported_count", 0)),
        skipped_count=int(imported.get("skipped_count", 0)),
        failed_count=int(imported.get("failed_count", 0)),
        created=[TrackedArticleCreate(**item) for item in imported.get("created", [])],
        results=[WechatMpArticleImportResult(**item) for item in imported.get("results", [])],
    ).model_dump()
