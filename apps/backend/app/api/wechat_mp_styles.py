from fastapi import APIRouter

from app.schemas.wechat_mp_styles import WechatMpHtmlStyleActiveUpdate
from app.services.workbench import (
    get_wechat_mp_html_style_preview,
    list_wechat_mp_html_styles,
    set_default_wechat_mp_html_style,
    update_wechat_mp_html_style,
)


router = APIRouter(prefix="/wechat-mp-html-styles", tags=["wechat-mp-html-styles"])


@router.get("")
def get_wechat_mp_html_styles() -> list[dict[str, object]]:
    return [style.model_dump() for style in list_wechat_mp_html_styles()]


@router.get("/{style_key}/preview")
def get_wechat_mp_html_style_preview_view(style_key: str) -> dict[str, object]:
    return get_wechat_mp_html_style_preview(style_key).model_dump()


@router.patch("/{style_key}")
def patch_wechat_mp_html_style(
    style_key: str,
    payload: WechatMpHtmlStyleActiveUpdate,
) -> dict[str, object]:
    return update_wechat_mp_html_style(style_key, payload).model_dump()


@router.post("/{style_key}/default")
def post_default_wechat_mp_html_style(style_key: str) -> dict[str, object]:
    return set_default_wechat_mp_html_style(style_key).model_dump()

