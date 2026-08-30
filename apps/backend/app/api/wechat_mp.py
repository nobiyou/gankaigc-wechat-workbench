from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.schemas.tracked_articles import TrackedArticleCreate
from app.schemas.wechat_mp import (
    WechatMpAccountItem,
    WechatMpArticleImportRequest,
    WechatMpArticleImportResponse,
    WechatMpArticleImportResult,
    WechatMpArticlePreviewItem,
    WechatMpSessionStatus,
    WxChannelAccountItem,
    WxChannelArticleItem,
)
from app.services.wechat_mp_client import WechatMpArticleFetchError, get_wechat_mp_client
from app.services.wx_channel_client import WxChannelApiError, get_wx_channel_client
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


@router.get("/accounts/wx-channel")
def get_wx_channel_accounts(keyword: str = "", page: int = 1, page_size: int = 20) -> list[dict[str, object]]:
    client = get_wx_channel_client()
    try:
        accounts = client.list_accounts(
            keyword,
            page=page,
            page_size=page_size,
        )
    except WxChannelApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return [WxChannelAccountItem(**item).model_dump() for item in accounts]


@router.get("/accounts/wx-channel/{biz}/articles")
def get_wx_channel_articles(biz: str, offset: int = 0, limit: int = 10) -> list[dict[str, object]]:
    client = get_wx_channel_client()
    try:
        articles = client.list_articles(biz=biz, offset=offset, limit=limit)
    except WxChannelApiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    return [WxChannelArticleItem(**item).model_dump() for item in articles]


@router.get("/accounts/{fakeid}/articles")
def get_wechat_mp_articles(
    fakeid: str,
    begin: int = 0,
    size: int = 5,
    keyword: str = "",
) -> list[dict[str, object]]:
    try:
        articles = get_wechat_mp_client().list_articles(fakeid=fakeid, begin=begin, size=size, keyword=keyword)
    except WechatMpArticleFetchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
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
