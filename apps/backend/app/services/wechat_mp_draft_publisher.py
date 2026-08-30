from __future__ import annotations

import json
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.services.wechat_mp_html import WechatMpHtmlRenderError, render_wechat_html
from app.services.wechat_mp_client import (
    WECHAT_MP_SESSION_EXPIRED_MESSAGE,
    WechatMpClient,
)


class WechatMpDraftPublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class WechatMpDraftPublishResult:
    draft_id: str | None
    thumb_media_id: str
    content_html: str


class WechatMpDraftPublisher:
    """扫码登录会话的公众号后台草稿 adapter。

    这里故意不复用 AppID/AppSecret API。扫码会话只能访问 mp.weixin.qq.com
    后台内部接口，所有不稳定的 endpoint 和表单字段都集中在本模块。
    """

    _UPLOAD_ENDPOINT = "https://mp.weixin.qq.com/cgi-bin/filetransfer"
    _DRAFT_ENDPOINT = "https://mp.weixin.qq.com/cgi-bin/operate_appmsg"

    def __init__(self, client: WechatMpClient) -> None:
        self._client = client

    def publish(
        self,
        *,
        title: str,
        digest: str,
        author: str,
        markdown_path: str | Path,
        cover_image_path: str | Path,
    ) -> WechatMpDraftPublishResult:
        markdown_file = Path(markdown_path)
        cover_file = Path(cover_image_path)
        if not markdown_file.is_file():
            raise WechatMpDraftPublishError(f"发布包正文文件不存在：{markdown_file}")
        if not cover_file.is_file():
            raise WechatMpDraftPublishError(f"公众号草稿封面不存在：{cover_file}")

        markdown_text = markdown_file.read_text(encoding="utf-8")
        content_html = self._markdown_to_html(markdown_text, base_dir=markdown_file.parent)
        if not content_html.strip():
            raise WechatMpDraftPublishError("发布包正文为空，无法写入公众号草稿箱")

        thumb_media_id = self._upload_image(cover_file, scene="8", expect="cover")
        draft_id = self._create_draft(
            title=title,
            digest=digest,
            author=author,
            content_html=content_html,
            thumb_media_id=thumb_media_id,
        )
        return WechatMpDraftPublishResult(
            draft_id=draft_id,
            thumb_media_id=thumb_media_id,
            content_html=content_html,
        )

    def _upload_image(self, image_path: Path, *, scene: str, expect: str) -> str:
        raw = image_path.read_bytes()
        if not raw:
            raise WechatMpDraftPublishError(f"图片文件为空：{image_path}")
        mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        try:
            upload_context = self._client.get_authenticated_upload_context()
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code in {401, 403}:
                self._mark_session_expired()
                raise WechatMpDraftPublishError(WECHAT_MP_SESSION_EXPIRED_MESSAGE) from None
            raise WechatMpDraftPublishError("微信后台请求失败，请检查网络或扫码会话状态") from None
        except httpx.HTTPError:
            raise WechatMpDraftPublishError("微信后台请求失败，请检查网络或扫码会话状态") from None
        except RuntimeError as exc:
            raise WechatMpDraftPublishError(str(exc)) from None
        query = {
            "action": "upload_material",
            "f": "json",
            "scene": scene,
            "writetype": "doublewrite",
            "groupid": "1",
            "lang": "zh_CN",
            "seq": str(int(time.time() * 1000)),
            "t": str(time.time()),
        }
        query.update({key: value for key, value in upload_context.items() if value})
        response = self._request(
            method="POST",
            endpoint=self._UPLOAD_ENDPOINT,
            query=query,
            data={
                "id": "WU_FILE_0",
                "name": image_path.name,
                "type": mime_type,
                "lastModifiedDate": str(time.ctime()),
                "size": str(len(raw)),
            },
            files={"file": (image_path.name, raw, mime_type)},
        )
        payload = self._response_json(response, operation=f"上传{expect}")
        upload_keys = (
            ("content", "file_id", "fileid", "media_id", "thumb_media_id", "content_url", "url")
            if expect == "cover"
            else ("content_url", "url", "content", "file_id", "fileid", "media_id", "thumb_media_id")
        )
        value = self._first_payload_value(payload, *upload_keys)
        if not value:
            raise WechatMpDraftPublishError(f"上传{expect}成功但响应缺少文件标识")
        return value

    def _create_draft(
        self,
        *,
        title: str,
        digest: str,
        author: str,
        content_html: str,
        thumb_media_id: str,
    ) -> str | None:
        normalized_title = title.strip()
        if not normalized_title:
            raise WechatMpDraftPublishError("公众号草稿标题不能为空")
        normalized_digest = digest.strip()[:120]
        normalized_author = author.strip()[:8]
        response = self._request(
            method="POST",
            endpoint=self._DRAFT_ENDPOINT,
            query={
                "t": "ajax-response",
                "sub": "create",
                "type": "10",
            },
            data={
                "ajax": "1",
                "title": normalized_title[:64],
                "title0": normalized_title[:64],
                "author": normalized_author,
                "author0": normalized_author,
                "digest": normalized_digest,
                "digest0": normalized_digest,
                "content": content_html,
                "content0": content_html,
                "content_noencode": content_html,
                "sourceurl": "",
                "sourceurl0": "",
                "fileid": thumb_media_id,
                "fileid0": thumb_media_id,
                "cover": thumb_media_id,
                "cover0": thumb_media_id,
                "show_cover_pic": "1",
                "show_cover_pic0": "1",
                "need_open_comment": "0",
                "only_fans_can_comment": "0",
                "sub": "create",
                "count": "1",
                "AppMsgId": "0",
                "appmsgid": "0",
                "itemidx": "1",
                "data_seq": "0",
                "random": "0",
                "type": "10",
            },
        )
        payload = self._response_json(response, operation="写入公众号草稿")
        return self._first_payload_value(payload, "appMsgId", "appmsgid", "media_id", "draft_id")

    def _request(self, *, method: str, endpoint: str, query: dict[str, object], data: dict[str, object] | None = None, files: dict[str, tuple[str, bytes, str]] | None = None) -> httpx.Response:
        try:
            response = self._client._request_authenticated_response(
                method=method,
                endpoint=endpoint,
                query=query,
                data=data,
                files=files,
            )
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code in {401, 403}:
                self._mark_session_expired()
                raise WechatMpDraftPublishError(WECHAT_MP_SESSION_EXPIRED_MESSAGE) from None
            raise WechatMpDraftPublishError("微信后台请求失败，请检查网络或扫码会话状态") from None
        except httpx.HTTPError:
            raise WechatMpDraftPublishError("微信后台请求失败，请检查网络或扫码会话状态") from None
        if self._is_login_redirect(response):
            self._mark_session_expired()
            raise WechatMpDraftPublishError(WECHAT_MP_SESSION_EXPIRED_MESSAGE)
        return response

    def _response_json(self, response: httpx.Response, *, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            raise WechatMpDraftPublishError(f"{operation}失败：微信后台返回了非 JSON 响应") from None
        if not isinstance(payload, dict):
            raise WechatMpDraftPublishError(f"{operation}失败：微信后台响应格式异常")
        base_resp = payload.get("base_resp") or {}
        ret_value = base_resp.get("ret", payload.get("ret", 0)) if isinstance(base_resp, dict) else 0
        try:
            ret = int(ret_value or 0)
        except (TypeError, ValueError):
            ret = 0
        if ret != 0:
            if ret in {200002, 200003, 200004, 200013, 200040}:
                self._mark_session_expired()
                raise WechatMpDraftPublishError(WECHAT_MP_SESSION_EXPIRED_MESSAGE)
            err_msg = ""
            if isinstance(base_resp, dict):
                err_msg = str(base_resp.get("err_msg") or "").strip()
            raise WechatMpDraftPublishError(f"{operation}失败：{err_msg or f'微信后台错误码 {ret}'}")
        return payload

    @staticmethod
    def _first_payload_value(payload: dict[str, Any], *keys: str) -> str | None:
        candidates: list[Any] = [payload]
        for nested_key in ("data", "base_resp", "appmsg"):
            nested = payload.get(nested_key)
            if isinstance(nested, dict):
                candidates.append(nested)
        for candidate in candidates:
            for key in keys:
                value = candidate.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
        return None

    def _mark_session_expired(self) -> None:
        self._client.mark_session_expired()

    @staticmethod
    def _is_login_redirect(response: httpx.Response) -> bool:
        if response.status_code not in {301, 302, 303, 307, 308}:
            return False
        location = response.headers.get("location", "")
        return "loginpage" in location or "wxm2-login" in location

    def _markdown_to_html(self, markdown_text: str, *, base_dir: Path) -> str:
        try:
            rendered = render_wechat_html(
                markdown_text,
                base_dir=base_dir,
                image_resolver=lambda image_path, _alt: self._upload_image(
                    image_path,
                    scene="2",
                    expect="正文图片",
                ),
            )
        except WechatMpHtmlRenderError as exc:
            raise WechatMpDraftPublishError(str(exc)) from None
        return rendered.body_html


def get_wechat_mp_draft_publisher() -> WechatMpDraftPublisher:
    from app.services.wechat_mp_client import get_wechat_mp_client

    return WechatMpDraftPublisher(get_wechat_mp_client())
