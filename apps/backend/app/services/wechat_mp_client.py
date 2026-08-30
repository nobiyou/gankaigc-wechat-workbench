from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from hashlib import md5
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import httpx

from app.core.settings import settings
from app.schemas.wechat_mp import WechatMpArticleImportRequest


class _WechatArticleBodyParser(HTMLParser):
    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "form",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "ul",
    }
    _SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capturing = False
        self._capture_depth = 0
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {name: value or "" for name, value in attrs}
        if not self._capturing and attrs_map.get("id") == "js_content":
            self._capturing = True
            self._capture_depth = 1
            return
        if not self._capturing:
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if tag == "br":
            self._parts.append("\n")
            return
        if tag in self._BLOCK_TAGS:
            self._parts.append("\n\n")
        self._capture_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self._capturing:
            return
        if self._skip_depth > 0 and tag in self._SKIP_TAGS:
            self._skip_depth -= 1
            return
        if self._skip_depth > 0:
            return
        if tag in self._BLOCK_TAGS and tag != "br":
            self._parts.append("\n\n")
        self._capture_depth -= 1
        if self._capture_depth <= 0:
            self._capturing = False
            self._capture_depth = 0

    def handle_data(self, data: str) -> None:
        if not self._capturing or self._skip_depth > 0:
            return
        if data:
            self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if not self._capturing or self._skip_depth > 0:
            return
        self._parts.append(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        if not self._capturing or self._skip_depth > 0:
            return
        self._parts.append(html.unescape(f"&#{name};"))

    def get_text(self) -> str:
        raw_text = "".join(self._parts)
        return _normalize_wechat_text(raw_text, preserve_paragraphs=True)


def _strip_wechat_topic_link_markup(text: str) -> str:
    stripped = text
    patterns = [
        re.compile(
            r'<a\b[^>]*class\s*=\s*["\'][^"\']*wx_topic_link[^"\']*["\'][^>]*>(.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"&lt;a\b[^&]*class\s*=\s*[\"']?[^\"'>]*wx_topic_link[^\"'>]*[\"']?[^&]*&gt;(.*?)&lt;/a&gt;",
            re.IGNORECASE | re.DOTALL,
        ),
    ]
    changed = True
    while changed:
        changed = False
        for pattern in patterns:
            next_value = pattern.sub(lambda match: match.group(1).strip(), stripped)
            if next_value != stripped:
                stripped = next_value
                changed = True
    return stripped


def _normalize_wechat_text(text: str, *, preserve_paragraphs: bool) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = html.unescape(normalized)
    normalized = _strip_wechat_topic_link_markup(normalized)
    normalized = html.unescape(normalized)
    normalized = normalized.replace("\xa0", " ")
    normalized = re.sub(r"[ \t\f\v]+", " ", normalized)
    normalized = re.sub(r" *\n *", "\n", normalized)
    if preserve_paragraphs:
        paragraphs = [segment.strip() for segment in re.split(r"\n{2,}", normalized) if segment.strip()]
        return "\n\n".join(paragraphs)
    normalized = re.sub(r"\n{2,}", "\n", normalized)
    normalized = re.sub(r"\n", " ", normalized)
    normalized = re.sub(r" {2,}", " ", normalized)
    return normalized.strip()


def _decode_wechat_script_escaped_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    previous = None
    while previous != normalized:
        previous = normalized
        normalized = normalized.replace("\\\\x", "\\x").replace("\\\\u", "\\u")

    def replace_unicode_escape(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    def replace_hex_escape(match: re.Match[str]) -> str:
        return bytes.fromhex(match.group(1)).decode("latin1")

    normalized = re.sub(r"\\u([0-9a-fA-F]{4})", replace_unicode_escape, normalized)
    normalized = re.sub(r"\\x([0-9a-fA-F]{2})", replace_hex_escape, normalized)
    normalized = normalized.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t")
    normalized = normalized.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
    return normalized


def extract_wechat_article_body_markdown(html_text: str) -> tuple[str, str]:
    """Extract the readable body from a WeChat article or RSS HTML fragment."""
    parser = _WechatArticleBodyParser()
    parser.feed(str(html_text or ""))
    parser.close()
    body_from_dom = parser.get_text()
    if body_from_dom:
        return body_from_dom, "dom"
    match = re.search(r"content_noencode:\s*'((?:\\.|[^'])*)'", str(html_text or ""), re.DOTALL)
    if not match:
        return "", "missing"
    body_from_script = _normalize_wechat_text(
        _decode_wechat_script_escaped_text(match.group(1)),
        preserve_paragraphs=True,
    )
    return body_from_script, "content_noencode" if body_from_script else "missing"


WECHAT_MP_SESSION_REQUIRED_MESSAGE = "请先扫码登录公众号后台"
WECHAT_MP_SESSION_EXPIRED_MESSAGE = "公众号登录已过期，请重新扫码登录"


class WechatMpArticleFetchError(RuntimeError):
    """微信文章列表接口返回业务失败时的可识别错误。"""

    def __init__(
        self,
        *,
        code: int,
        err_msg: str = "",
        detail: str | None = None,
    ) -> None:
        self.code = int(code)
        self.err_msg = str(err_msg or "").strip()[:200]
        if detail:
            message = str(detail).strip()
        elif self.code == 200013:
            message = (
                "微信后台拒绝读取文章列表（错误码 200013：freq control）；"
                "文章列表接口当前受到频率或访问范围限制，无法可靠确认目标账号的最新文章。"
                "请稍后低频重试；若目标账号不是当前扫码登录账号，请扫码登录目标账号或改用手动导入。"
            )
        else:
            message = (
                f"读取公众号文章列表失败（错误码 {self.code}："
                f"{self.err_msg or '未知错误'}）"
            )
        super().__init__(message)


class WechatMpSessionStore:
    def __init__(self, session_path: str) -> None:
        self._path = Path(session_path)

    def load(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        return json.loads(self._path.read_text(encoding="utf-8"))

    def save(self, payload: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        if self._path.exists():
            self._path.unlink()

    def status(self) -> dict[str, object]:
        payload = self.load() or {}
        return {
            "logged_in": bool(payload.get("logged_in")),
            "nickname": payload.get("nickname"),
            "expires_at": payload.get("expires_at"),
            "login_stage": payload.get("login_stage"),
            "status_message": payload.get("status_message"),
        }


class WechatMpClient:
    def __init__(self, session_store: WechatMpSessionStore) -> None:
        self._session_store = session_store

    def get_session_status(self) -> dict[str, object]:
        return self._refresh_logged_in_session_status_if_needed()

    def get_cached_session_status(self) -> dict[str, object]:
        """读取本地扫码会话，供不需要远端自检的后台流程使用。"""
        session = self._session_store.load() or {}
        if session.get("logged_in") and self._is_local_session_expired(str(session.get("expires_at") or "").strip()):
            return self._expire_logged_in_session()
        return self._session_store.status()

    def start_login_qrcode(self) -> dict[str, object]:
        pre_login_cookie = self._start_login_session()
        response = self._request_response(
            method="GET",
            endpoint="https://mp.weixin.qq.com/cgi-bin/scanloginqrcode",
            query={
                "action": "getqrcode",
                "random": int(datetime.now(timezone.utc).timestamp() * 1000),
            },
            cookie=pre_login_cookie,
        )
        return {
            "content_type": response.headers.get("content-type", "image/jpeg"),
            "image_bytes": response.content,
        }

    def poll_login_status(self) -> dict[str, object]:
        session = self._session_store.load() or {}
        if session.get("logged_in"):
            return self.get_session_status()

        pre_login_cookie = str(session.get("pre_login_cookie") or "").strip()
        if not pre_login_cookie:
            return self._session_store.status()

        payload = self._request_json(
            method="GET",
            endpoint="https://mp.weixin.qq.com/cgi-bin/scanloginqrcode",
            query={
                "action": "ask",
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            cookie=pre_login_cookie,
        )
        base_resp = payload.get("base_resp") or {}
        if int(base_resp.get("ret") or 0) != 0:
            err_msg = str(base_resp.get("err_msg") or "公众号扫码状态查询失败")
            raise RuntimeError(err_msg)

        status_code = int(payload.get("status") or 0)
        acct_size = int(payload.get("acct_size") or 0)

        if status_code == 1:
            return self.complete_login()
        if status_code in {4, 6} and acct_size >= 1:
            return self._save_pending_status("waiting_confirmation", "扫码成功，等待确认")
        if status_code == 5:
            return self._save_pending_status("waiting_scan", "该账号尚未绑定邮箱")
        if status_code in {2, 3}:
            return self._save_pending_status("expired", "二维码已过期，请重新获取")

        return self._save_pending_status("waiting_scan", "等待扫码")

    def complete_login(self) -> dict[str, object]:
        session = self._session_store.load() or {}
        pre_login_cookie = str(session.get("pre_login_cookie") or "").strip()
        if not pre_login_cookie:
            raise RuntimeError("WeChat MP login session has not been started")

        response = self._request_response(
            method="POST",
            endpoint="https://mp.weixin.qq.com/cgi-bin/bizlogin",
            query={"action": "login"},
            body={
                "userlang": "zh_CN",
                "redirect_url": "",
                "cookie_forbidden": 0,
                "cookie_cleaned": 0,
                "plugin_used": 0,
                "login_type": 3,
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
            cookie=pre_login_cookie,
        )
        payload = response.json()
        base_resp = payload.get("base_resp") or {}
        if int(base_resp.get("ret") or 0) != 0:
            err_msg = str(base_resp.get("err_msg") or "公众号登录失败")
            raise RuntimeError(err_msg)

        redirect_url = str(payload.get("redirect_url") or "").strip()
        token = self._extract_token_from_redirect_url(redirect_url)
        final_cookie = self._collect_cookie_header(response)
        if not final_cookie:
            raise RuntimeError("公众号登录成功但未返回有效 Cookie")

        account_profile = self._fetch_account_profile(cookie=final_cookie, token=token)
        nickname = account_profile.get("nickname") or "WeChat MP"
        avatar = account_profile.get("avatar")
        return self.finalize_login(cookie=final_cookie, token=token, nickname=nickname, avatar=avatar)

    def finalize_login(
        self,
        *,
        cookie: str,
        token: str,
        nickname: str | None = None,
        avatar: str | None = None,
    ) -> dict[str, object]:
        expires_at = (datetime.now(timezone.utc) + timedelta(days=4)).isoformat()
        self._session_store.save(
            {
                "logged_in": True,
                "cookie": cookie,
                "token": token,
                "nickname": nickname or "WeChat MP",
                "avatar": avatar,
                "expires_at": expires_at,
                "pre_login_cookie": None,
                "login_stage": "logged_in",
                "status_message": "登录成功",
            }
        )
        return self._session_store.status()

    def logout(self) -> dict[str, object]:
        self._session_store.clear()
        return {
            "logged_in": False,
            "nickname": None,
            "expires_at": None,
            "login_stage": "logged_out",
            "status_message": None,
        }

    def mark_session_expired(self) -> dict[str, object]:
        """让内部写入协议在确认后台会话失效时复用统一的过期状态。"""
        return self._expire_logged_in_session()

    def get_authenticated_upload_context(self) -> dict[str, str]:
        """读取后台图片上传需要的短期票据，仅供内部 adapter 使用。"""
        session = self._require_logged_in_session()
        cookie = str(session.get("cookie") or "").strip()
        token = str(session.get("token") or "").strip()
        response, profile = self._fetch_account_profile_response(cookie=cookie, token=token)
        if self._is_login_redirect_response(response) or not profile.get("nickname"):
            self._expire_logged_in_session()
            raise RuntimeError(WECHAT_MP_SESSION_EXPIRED_MESSAGE)
        return {
            "ticket": str(profile.get("ticket") or "").strip(),
            "ticket_id": str(profile.get("ticket_id") or profile.get("user_name") or "").strip(),
            "svr_time": str(profile.get("svr_time") or "").strip(),
        }

    def _request_authenticated_response(
        self,
        *,
        method: str,
        endpoint: str,
        query: Mapping[str, object] | None = None,
        data: Mapping[str, object] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
    ) -> httpx.Response:
        """为扫码后台 adapter 提供带会话的原始请求能力，不暴露 Cookie/token。"""
        session = self._require_logged_in_session()
        token = str(session.get("token") or "").strip()
        request_query = dict(query or {})
        request_query.setdefault("token", token)
        headers = self._build_headers()
        try:
            with httpx.Client(
                timeout=settings.wechat_mp_request_timeout_seconds,
                headers=headers,
                follow_redirects=False,
            ) as client:
                response = client.request(
                    method,
                    endpoint,
                    params=request_query,
                    data=data,
                    files=files,
                )
        except httpx.HTTPError:
            raise
        response.raise_for_status()
        return response

    def search_accounts(self, *, keyword: str, begin: int, size: int) -> list[dict[str, object]]:
        token = self._require_token()
        payload = self._request_json(
            method="GET",
            endpoint="https://mp.weixin.qq.com/cgi-bin/searchbiz",
            query={
                "action": "search_biz",
                "begin": begin,
                "count": size,
                "query": keyword,
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": "1",
            },
        )
        return list(payload.get("list") or [])

    def list_articles(self, *, fakeid: str, begin: int, size: int, keyword: str | None) -> list[dict[str, object]]:
        token = self._require_token()
        normalized_keyword = keyword or ""
        is_searching = bool(normalized_keyword)
        payload = self._request_json(
            method="GET",
            endpoint="https://mp.weixin.qq.com/cgi-bin/appmsgpublish",
            query={
                "sub": "search" if is_searching else "list",
                "search_field": "7" if is_searching else "null",
                "begin": begin,
                "count": size,
                "query": normalized_keyword,
                "fakeid": fakeid,
                "type": "101_1",
                "free_publish_type": 1,
                "sub_action": "list_ex",
                "token": token,
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
        )
        base_resp = payload.get("base_resp")
        if not isinstance(base_resp, Mapping):
            raise WechatMpArticleFetchError(
                code=-1,
                detail="读取公众号文章列表失败：微信响应缺少 base_resp。",
            )
        try:
            response_code = int(base_resp.get("ret") or 0)
        except (TypeError, ValueError):
            raise WechatMpArticleFetchError(
                code=-1,
                detail="读取公众号文章列表失败：微信响应包含无效错误码。",
            ) from None
        if response_code != 0:
            raise WechatMpArticleFetchError(
                code=response_code,
                err_msg=str(base_resp.get("err_msg") or base_resp.get("errmsg") or ""),
            )

        publish_page_raw = payload.get("publish_page")
        if not publish_page_raw:
            raise WechatMpArticleFetchError(
                code=0,
                detail="读取公众号文章列表失败：微信响应缺少 publish_page。",
            )
        try:
            publish_page = (
                json.loads(str(publish_page_raw))
                if not isinstance(publish_page_raw, Mapping)
                else publish_page_raw
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            raise WechatMpArticleFetchError(
                code=0,
                detail="读取公众号文章列表失败：微信返回的 publish_page 无法解析。",
            ) from None
        if not isinstance(publish_page, Mapping):
            raise WechatMpArticleFetchError(
                code=0,
                detail="读取公众号文章列表失败：微信返回的 publish_page 格式无效。",
            )
        publish_list = list(publish_page.get("publish_list") or [])
        previews: list[dict[str, object]] = []
        for publish_item in publish_list:
            if not isinstance(publish_item, Mapping):
                continue
            publish_info_raw = publish_item.get("publish_info")
            if not publish_info_raw:
                continue
            try:
                publish_info = (
                    json.loads(str(publish_info_raw))
                    if not isinstance(publish_info_raw, Mapping)
                    else publish_info_raw
                )
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if not isinstance(publish_info, Mapping):
                continue
            for article in list(publish_info.get("appmsgex") or []):
                if not isinstance(article, Mapping):
                    continue
                previews.append(
                    {
                        "article_id": str(article.get("aid") or f"{article.get('appmsgid')}_{article.get('itemidx')}"),
                        "account_fakeid": fakeid,
                        "account_nickname": str(article.get("nickname") or ""),
                        "title": str(article.get("title") or ""),
                        "link": str(article.get("link") or ""),
                        "author": str(article.get("author_name") or ""),
                        "digest": _normalize_wechat_text(str(article.get("digest") or ""), preserve_paragraphs=False),
                        "update_time": int(article.get("update_time") or 0),
                    }
                )
        return previews

    def import_articles(self, payload: WechatMpArticleImportRequest) -> dict[str, object]:
        created: list[dict[str, object]] = []
        fallback_account_nickname = (payload.fallback_account_nickname or "").strip()
        for article in payload.articles:
            effective_account_nickname = (article.account_nickname or "").strip() or fallback_account_nickname
            body_markdown, body_source = self.fetch_article_body(article.link, article.digest)
            created.append(
                {
                    "slug": self._build_article_slug(
                        account_nickname=effective_account_nickname,
                        article_id=article.article_id,
                    ),
                    "source_name": effective_account_nickname,
                    "title": article.title,
                    "url": article.link,
                    "author": article.author or effective_account_nickname,
                    "summary": article.digest,
                    "body_markdown": body_markdown,
                    "body_source": body_source,
                    "structure_notes": "Imported from WeChat MP article list; structure notes pending review.",
                    "tags": ["wechat-mp", effective_account_nickname] if effective_account_nickname else ["wechat-mp"],
                }
            )
        return {
            "requested_count": len(payload.articles),
            "imported_count": len(created),
            "created": created,
        }

    def fetch_article_body(self, article_link: str, fallback_digest: str) -> tuple[str, str]:
        normalized_digest = (fallback_digest or "").strip()
        normalized_link = (article_link or "").strip()
        if not normalized_link:
            return normalized_digest, "digest_fallback"
        try:
            response = self._request_response(
                method="GET",
                endpoint=normalized_link,
                query={},
                cookie=None,
            )
        except httpx.HTTPError:
            return normalized_digest, "digest_fallback"
        body_markdown, body_source = self._extract_article_body_markdown(response.text)
        if body_markdown:
            return body_markdown, body_source
        return normalized_digest, "digest_fallback"

    def _fetch_article_body_markdown(self, article_link: str, fallback_digest: str) -> str:
        body_markdown, _ = self.fetch_article_body(article_link, fallback_digest)
        return body_markdown

    def _extract_article_body_markdown(self, html_text: str) -> tuple[str, str]:
        return extract_wechat_article_body_markdown(html_text)

    def _extract_article_body_from_embedded_script(self, html_text: str) -> str:
        match = re.search(r"content_noencode:\s*'((?:\\.|[^'])*)'", html_text, re.DOTALL)
        if not match:
            return ""
        decoded = _decode_wechat_script_escaped_text(match.group(1))
        return _normalize_wechat_text(decoded, preserve_paragraphs=True)

    def _start_login_session(self) -> str:
        response = self._request_response(
            method="POST",
            endpoint="https://mp.weixin.qq.com/cgi-bin/bizlogin",
            query={"action": "startlogin"},
            body={
                "userlang": "zh_CN",
                "redirect_url": "",
                "login_type": 3,
                "sessionid": self._build_login_session_id(),
                "token": "",
                "lang": "zh_CN",
                "f": "json",
                "ajax": 1,
            },
        )
        payload = response.json()
        base_resp = payload.get("base_resp") or {}
        if int(base_resp.get("ret") or 0) != 0:
            err_msg = str(base_resp.get("err_msg") or "公众号预登录会话创建失败")
            raise RuntimeError(err_msg)

        pre_login_cookie = self._extract_cookie_from_response(response, "uuid")
        if not pre_login_cookie:
            raise RuntimeError("公众号预登录会话未返回 uuid Cookie")

        self._session_store.save(
            {
                "logged_in": False,
                "nickname": None,
                "expires_at": None,
                "pre_login_cookie": pre_login_cookie,
                "cookie": None,
                "token": None,
                "login_stage": "waiting_scan",
                "status_message": "等待扫码",
            }
        )
        return pre_login_cookie

    def _save_pending_status(self, login_stage: str, status_message: str | None) -> dict[str, object]:
        payload = self._session_store.load() or {}
        payload["logged_in"] = False
        payload["nickname"] = None
        payload["expires_at"] = None
        payload["login_stage"] = login_stage
        payload["status_message"] = status_message
        self._session_store.save(payload)
        return self._session_store.status()

    def _refresh_logged_in_session_status_if_needed(self) -> dict[str, object]:
        session = self._session_store.load() or {}
        if not session.get("logged_in"):
            return self._session_store.status()

        if self._is_local_session_expired(str(session.get("expires_at") or "").strip()):
            return self._expire_logged_in_session()

        cookie = str(session.get("cookie") or "").strip()
        token = str(session.get("token") or "").strip()
        if not cookie or not token:
            return self._expire_logged_in_session()

        try:
            response, profile = self._fetch_account_profile_response(cookie=cookie, token=token)
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in {401, 403}:
                return self._expire_logged_in_session()
            return self._session_store.status()
        except httpx.HTTPError:
            return self._session_store.status()

        if self._is_login_redirect_response(response) or not profile.get("nickname"):
            return self._expire_logged_in_session()

        return self._session_store.status()

    def _expire_logged_in_session(self) -> dict[str, object]:
        self._session_store.save(
            {
                "logged_in": False,
                "cookie": None,
                "token": None,
                "nickname": None,
                "avatar": None,
                "expires_at": None,
                "pre_login_cookie": None,
                "login_stage": "expired",
                "status_message": WECHAT_MP_SESSION_EXPIRED_MESSAGE,
            }
        )
        return self._session_store.status()

    def _is_local_session_expired(self, expires_at: str) -> bool:
        if not expires_at:
            return False
        try:
            expires_at_value = datetime.fromisoformat(expires_at)
        except ValueError:
            return False
        return datetime.now(timezone.utc) >= expires_at_value.astimezone(timezone.utc)

    def _fetch_account_profile(self, *, cookie: str, token: str) -> dict[str, str]:
        _, profile = self._fetch_account_profile_response(cookie=cookie, token=token)
        return profile

    def _fetch_account_profile_response(self, *, cookie: str, token: str) -> tuple[httpx.Response, dict[str, str]]:
        response = self._request_response(
            method="GET",
            endpoint="https://mp.weixin.qq.com/cgi-bin/home",
            query={
                "t": "home/index",
                "token": token,
                "lang": "zh_CN",
            },
            cookie=cookie,
        )
        html = response.text
        nickname = ""
        avatar = ""
        nickname_match = self._match_script_value(html, "nick_name")
        if nickname_match:
            nickname = nickname_match
        avatar_match = self._match_script_value(html, "head_img")
        if avatar_match:
            avatar = avatar_match
        return response, {
            "nickname": nickname,
            "avatar": avatar,
            "ticket": self._match_page_value(html, "ticket"),
            "ticket_id": self._match_page_value(html, "ticket_id"),
            "user_name": self._match_page_value(html, "user_name"),
            "svr_time": self._match_page_value(html, "svr_time"),
        }

    def _is_login_redirect_response(self, response: httpx.Response) -> bool:
        if response.status_code not in {301, 302, 303, 307, 308}:
            return False
        location = response.headers.get("location", "")
        return "loginpage" in location or "wxm2-login" in location

    def _match_script_value(self, html: str, field_name: str) -> str:
        marker = f'wx.cgiData.{field_name} = "'
        start = html.find(marker)
        if start < 0:
            return ""
        value_start = start + len(marker)
        value_end = html.find('"', value_start)
        if value_end < 0:
            return ""
        return html[value_start:value_end]

    def _match_page_value(self, html: str, field_name: str) -> str:
        patterns = (
            rf"(?:wx\.data|wx\.cgiData)\.{re.escape(field_name)}\s*[:=]\s*['\"]?([^'\",;\s}}]+)",
            rf"['\"]{re.escape(field_name)}['\"]\s*:\s*['\"]?([^'\",;\s}}]+)",
        )
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return html.unescape(match.group(1)).strip()
        return ""

    def _require_token(self) -> str:
        payload = self._require_logged_in_session()
        token = str(payload.get("token") or "").strip()
        if not token:
            raise RuntimeError(self._build_login_required_message(payload))
        return token

    def _require_logged_in_session(self) -> dict[str, Any]:
        self._refresh_logged_in_session_status_if_needed()
        payload = self._session_store.load() or {}
        if not payload.get("logged_in"):
            raise RuntimeError(self._build_login_required_message(payload))
        return payload

    def _build_login_required_message(self, payload: dict[str, Any]) -> str:
        status_message = str(payload.get("status_message") or "").strip()
        if status_message:
            return status_message
        if str(payload.get("login_stage") or "").strip() == "expired":
            return WECHAT_MP_SESSION_EXPIRED_MESSAGE
        return WECHAT_MP_SESSION_REQUIRED_MESSAGE

    def _request_json(
        self,
        *,
        method: str,
        endpoint: str,
        query: dict[str, object],
        cookie: str | None = None,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        response = self._request_response(
            method=method,
            endpoint=endpoint,
            query=query,
            cookie=cookie,
            body=body,
        )
        return response.json()

    def _request_bytes(
        self,
        *,
        method: str,
        endpoint: str,
        query: dict[str, object],
        cookie: str | None = None,
        body: dict[str, object] | None = None,
    ) -> bytes:
        response = self._request_response(
            method=method,
            endpoint=endpoint,
            query=query,
            cookie=cookie,
            body=body,
        )
        return response.content

    def _request_response(
        self,
        *,
        method: str,
        endpoint: str,
        query: dict[str, object],
        cookie: str | None = None,
        body: dict[str, object] | None = None,
    ) -> httpx.Response:
        headers = self._build_headers(cookie=cookie)
        with httpx.Client(timeout=settings.wechat_mp_request_timeout_seconds, headers=headers) as client:
            response = client.request(method=method, url=endpoint, params=query, data=body)
            response.raise_for_status()
            return response

    def _build_headers(self, *, cookie: str | None = None) -> dict[str, str]:
        session = self._session_store.load() or {}
        effective_cookie = cookie if cookie is not None else str(session.get("cookie") or "").strip()
        headers = {
            "Referer": "https://mp.weixin.qq.com/",
            "Origin": "https://mp.weixin.qq.com",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
            "Accept-Encoding": "identity",
        }
        if effective_cookie:
            headers["Cookie"] = effective_cookie
        return headers

    def _extract_cookie_from_response(self, response: httpx.Response, cookie_name: str) -> str | None:
        for set_cookie in self._get_set_cookie_headers(response):
            first_segment = set_cookie.split(";", 1)[0].strip()
            if not first_segment or "=" not in first_segment:
                continue
            name, value = first_segment.split("=", 1)
            if name.strip() == cookie_name:
                return f"{name.strip()}={value.strip()}"
        return None

    def _collect_cookie_header(self, response: httpx.Response) -> str:
        cookie_map: dict[str, str] = {}
        for set_cookie in self._get_set_cookie_headers(response):
            first_segment = set_cookie.split(";", 1)[0].strip()
            if not first_segment or "=" not in first_segment:
                continue
            name, value = first_segment.split("=", 1)
            normalized_name = name.strip()
            normalized_value = value.strip()
            if not normalized_name:
                continue
            if not normalized_value or normalized_value.upper() == "EXPIRED":
                cookie_map.pop(normalized_name, None)
                continue
            cookie_map[normalized_name] = normalized_value
        return "; ".join(f"{name}={value}" for name, value in cookie_map.items())

    def _get_set_cookie_headers(self, response: httpx.Response) -> list[str]:
        try:
            return list(response.headers.get_list("set-cookie"))
        except AttributeError:
            raw_value = response.headers.get("set-cookie", "")
            return [raw_value] if raw_value else []

    def _extract_token_from_redirect_url(self, redirect_url: str) -> str:
        if not redirect_url:
            raise RuntimeError("公众号登录响应缺少 redirect_url")
        token = httpx.QueryParams(redirect_url.split("?", 1)[1] if "?" in redirect_url else "").get("token")
        if not token:
            raise RuntimeError(f"公众号登录 redirect_url 中缺少 token: {redirect_url}")
        return token

    def _build_login_session_id(self) -> str:
        return f"{int(datetime.now(timezone.utc).timestamp() * 1000)}{uuid4().hex[:6]}"

    def _build_article_slug(self, *, account_nickname: str, article_id: str) -> str:
        nickname_slug = _slugify(account_nickname) or "wechat-mp"
        article_slug = _slugify(article_id)
        if article_slug:
            return f"wechat-mp-{nickname_slug}-{article_slug}"
        short_hash = md5(article_id.encode("utf-8")).hexdigest()[:10]
        return f"wechat-mp-{nickname_slug}-{short_hash}"


def _slugify(value: str) -> str:
    normalized = []
    last_dash = False
    for char in value.strip().lower():
        if char.isalnum():
            normalized.append(char)
            last_dash = False
            continue
        if char in {"-", "_"}:
            normalized.append("-")
            last_dash = True
            continue
        if "\u4e00" <= char <= "\u9fff":
            normalized.append(char)
            last_dash = False
            continue
        if not last_dash:
            normalized.append("-")
            last_dash = True
    slug = "".join(normalized).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def get_wechat_mp_client() -> WechatMpClient:
    return WechatMpClient(WechatMpSessionStore(settings.wechat_mp_session_path))
