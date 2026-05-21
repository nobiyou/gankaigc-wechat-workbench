from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import md5
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.core.settings import settings
from app.schemas.wechat_mp import WechatMpArticleImportRequest


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
            return self._session_store.status()

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
        publish_page = json.loads(str(payload.get("publish_page") or "{}"))
        publish_list = list(publish_page.get("publish_list") or [])
        previews: list[dict[str, object]] = []
        for publish_item in publish_list:
            publish_info_raw = publish_item.get("publish_info")
            if not publish_info_raw:
                continue
            publish_info = json.loads(str(publish_info_raw))
            for article in list(publish_info.get("appmsgex") or []):
                previews.append(
                    {
                        "article_id": str(article.get("aid") or f"{article.get('appmsgid')}_{article.get('itemidx')}"),
                        "account_fakeid": fakeid,
                        "account_nickname": str(article.get("nickname") or ""),
                        "title": str(article.get("title") or ""),
                        "link": str(article.get("link") or ""),
                        "author": str(article.get("author_name") or ""),
                        "digest": str(article.get("digest") or ""),
                        "update_time": int(article.get("update_time") or 0),
                    }
                )
        return previews

    def import_articles(self, payload: WechatMpArticleImportRequest) -> dict[str, object]:
        created: list[dict[str, object]] = []
        fallback_account_nickname = (payload.fallback_account_nickname or "").strip()
        for article in payload.articles:
            effective_account_nickname = (article.account_nickname or "").strip() or fallback_account_nickname
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
                    "structure_notes": "Imported from WeChat MP article list; structure notes pending review.",
                    "tags": ["wechat-mp", effective_account_nickname] if effective_account_nickname else ["wechat-mp"],
                }
            )
        return {
            "imported_count": len(created),
            "created": created,
        }

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

    def _fetch_account_profile(self, *, cookie: str, token: str) -> dict[str, str]:
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
        return {
            "nickname": nickname,
            "avatar": avatar,
        }

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

    def _require_token(self) -> str:
        payload = self._session_store.load() or {}
        token = str(payload.get("token") or "").strip()
        if not token:
            raise RuntimeError("WeChat MP session is not logged in")
        return token

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
