from __future__ import annotations

from hashlib import sha256
from html import unescape
import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx

from app.core.settings import settings
from app.services.wechat_mp_client import extract_wechat_article_body_markdown


class WxChannelApiError(RuntimeError):
    """A bounded, user-facing error from the wx_channel HTTP API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: int | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(str(message).strip()[:500])


class WxChannelNotConfiguredError(WxChannelApiError):
    pass


_ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
_RSS_CONTENT_TIMEOUT_SECONDS = 60.0
_SENSITIVE_QUERY_KEYS = {
    "appmsg_token",
    "key",
    "pass_ticket",
    "token",
    "uin",
    "wxtoken",
}


def _normalize_base_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise WxChannelNotConfiguredError(
            "未配置 wx_channel 地址，请设置 WX_CHANNEL_API_BASE_URL。"
        )
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise WxChannelNotConfiguredError(
            "WX_CHANNEL_API_BASE_URL 必须是 http:// 或 https:// 地址。"
        )
    return raw.rstrip("/")


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_article_url(value: object) -> str:
    raw = str(value or "").strip().replace("&amp%3B", "&")
    raw = unescape(raw)
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.netloc:
        return raw
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _SENSITIVE_QUERY_KEYS
    ]
    query.sort()
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def _article_identity(value: object) -> str:
    normalized = _clean_article_url(value)
    parsed = urlsplit(normalized)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    mid = str(query.get("mid") or "").strip()
    idx = str(query.get("idx") or "").strip()
    if mid:
        return f"mid:{mid}:idx:{idx or '1'}"
    return normalized or str(value or "").strip()


def _response_data(payload: object) -> object:
    if not isinstance(payload, Mapping):
        raise WxChannelApiError("wx_channel 返回格式无效：缺少 JSON 对象。")
    if "code" not in payload:
        return payload
    code = _safe_int(payload.get("code"), default=-1)
    if code != 0:
        message = str(payload.get("message") or payload.get("msg") or "接口业务失败").strip()
        raise WxChannelApiError(
            f"wx_channel 接口失败（错误码 {code}：{message}）",
            code=code,
        )
    return payload.get("data")


class WxChannelClient:
    """HTTP adapter for the local, credential-owning wx_channel service."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self._timeout_seconds = float(timeout_seconds or settings.wechat_mp_request_timeout_seconds)
        self._client = client or httpx.Client(
            timeout=self._timeout_seconds,
            headers={"Accept": "application/json, text/plain, */*"},
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def list_accounts(self, keyword: str, *, page: int = 1, page_size: int = 20) -> list[dict[str, object]]:
        payload = self._request_json(
            "/api/mp/list",
            params={
                "keyword": str(keyword or "").strip(),
                "page": max(1, int(page)),
                "page_size": max(1, min(int(page_size), 100)),
            },
        )
        data = _response_data(payload)
        items: object = data
        if isinstance(data, Mapping):
            items = data.get("items") or data.get("list") or []
        if not isinstance(items, list):
            raise WxChannelApiError("wx_channel 公众号目录格式无效：items 不是数组。")
        return [self._normalize_account(item) for item in items if isinstance(item, Mapping)]

    def list_articles(self, *, biz: str, offset: int = 0, limit: int = 10) -> list[dict[str, object]]:
        normalized_biz = str(biz or "").strip()
        if not normalized_biz:
            raise WxChannelApiError("读取 wx_channel 文章失败：缺少 biz。")
        payload = self._request_json(
            "/api/mp/msg/list",
            params={"biz": normalized_biz, "offset": max(0, int(offset))},
        )
        data = _response_data(payload)
        if not isinstance(data, Mapping):
            raise WxChannelApiError("wx_channel 文章列表格式无效：data 不是对象。")
        ret = _safe_int(data.get("ret"), default=0)
        if ret != 0:
            message = str(data.get("errmsg") or data.get("err_msg") or "文章列表请求失败").strip()
            raise WxChannelApiError(
                f"wx_channel 读取文章失败（错误码 {ret}：{message}）",
                code=ret,
            )
        raw_articles = data.get("articles")
        if not isinstance(raw_articles, list):
            raw_articles = self._flatten_message_items(data.get("list"))
        normalized = [
            self._normalize_article(item, normalized_biz)
            for item in raw_articles
            if isinstance(item, Mapping)
        ]
        normalized = [item for item in normalized if item["link"] or item["title"]]
        return normalized[: max(1, int(limit))]

    def fetch_article_body(
        self,
        article_link: str,
        fallback_digest: str,
        *,
        biz: str | None = None,
    ) -> tuple[str, str]:
        normalized_digest = str(fallback_digest or "").strip()
        normalized_biz = str(biz or "").strip() or self._biz_from_article_url(article_link)
        if not normalized_biz:
            return normalized_digest, "digest_fallback"
        try:
            response = self._request_text(
                "/rss/mp",
                params={"biz": normalized_biz, "content": 1},
                timeout_seconds=max(self._timeout_seconds, _RSS_CONTENT_TIMEOUT_SECONDS),
            )
            body = self._extract_rss_body(response, article_link)
        except WxChannelApiError:
            return normalized_digest, "digest_fallback"
        if body:
            return body, "wx_channel_rss"
        return normalized_digest, "digest_fallback"

    def _request_json(self, path: str, *, params: Mapping[str, object]) -> object:
        response = self._request(path, params=params)
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise WxChannelApiError(f"wx_channel 返回的 {path} 不是合法 JSON。") from exc

    def _request_text(
        self,
        path: str,
        *,
        params: Mapping[str, object],
        timeout_seconds: float | None = None,
    ) -> str:
        return self._request(path, params=params, timeout_seconds=timeout_seconds).text

    def _request(
        self,
        path: str,
        *,
        params: Mapping[str, object],
        timeout_seconds: float | None = None,
    ) -> httpx.Response:
        endpoint = f"{self.base_url}/{str(path).lstrip('/')}"
        try:
            if timeout_seconds is None:
                response = self._client.get(endpoint, params=params)
            else:
                response = self._client.get(endpoint, params=params, timeout=timeout_seconds)
        except httpx.TimeoutException as exc:
            raise WxChannelApiError("wx_channel 请求超时，请确认服务正在运行且文章采集已完成。") from exc
        except httpx.RequestError as exc:
            raise WxChannelApiError(
                f"无法连接 wx_channel（{exc.__class__.__name__}），请启动 wx_channel 并检查地址。"
            ) from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise WxChannelApiError(
                f"wx_channel 请求失败：HTTP {response.status_code} ({path})",
                status_code=response.status_code,
            )
        return response

    @staticmethod
    def _normalize_account(item: Mapping[str, object]) -> dict[str, object]:
        return {
            "source": "wx_channel",
            "biz": str(item.get("biz") or "").strip(),
            "nickname": str(item.get("nickname") or "").strip(),
            "avatar_url": str(item.get("avatar_url") or "").strip(),
            "is_effective": bool(item.get("is_effective")),
            "article_count": _safe_int(item.get("article_count")),
            "archived_count": _safe_int(item.get("archived_count")),
            "last_sync_at": _safe_int(item.get("last_sync_at")),
            "sync_status": str(item.get("sync_status") or "").strip(),
            "sync_error": str(item.get("sync_error") or "").strip(),
        }

    @classmethod
    def _flatten_message_items(cls, value: object) -> list[Mapping[str, object]]:
        if not isinstance(value, list):
            return []
        result: list[Mapping[str, object]] = []
        for item in value:
            if not isinstance(item, Mapping):
                continue
            ext = item.get("app_msg_ext_info")
            if not isinstance(ext, Mapping):
                result.append(item)
                continue
            published = item.get("comm_msg_info", {}).get("datetime") if isinstance(item.get("comm_msg_info"), Mapping) else None
            parent = dict(ext)
            parent.setdefault("publish_time", published)
            result.append(parent)
            children = ext.get("multi_app_msg_item_list")
            if isinstance(children, list):
                for child in children:
                    if isinstance(child, Mapping):
                        child_item = dict(child)
                        child_item.setdefault("publish_time", published)
                        result.append(child_item)
        return result

    @classmethod
    def _normalize_article(cls, item: Mapping[str, object], biz: str) -> dict[str, object]:
        link = _clean_article_url(item.get("content_url") or item.get("url") or item.get("link"))
        source_url = _clean_article_url(item.get("source_url"))
        parsed = urlsplit(link)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        mid = str(item.get("mid") or query.get("mid") or "").strip()
        idx = str(item.get("idx") or query.get("idx") or "").strip()
        raw_id = str(item.get("article_id") or item.get("aid") or "").strip()
        article_id = raw_id or (f"mid:{mid}:idx:{idx or '1'}" if mid else "")
        if not article_id:
            article_id = "url:" + sha256(f"{biz}|{link}|{item.get('title', '')}".encode("utf-8")).hexdigest()[:32]
        return {
            "article_id": article_id,
            "account_biz": biz,
            "account_nickname": str(item.get("account_nickname") or item.get("nickname") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "link": link or source_url,
            "source_url": source_url,
            "author": str(item.get("author") or item.get("author_name") or "").strip(),
            "digest": str(item.get("digest") or "").strip(),
            "update_time": _safe_int(item.get("publish_time") or item.get("update_time") or item.get("datetime")),
            "cover_url": str(item.get("cover") or item.get("cover_url") or "").strip(),
        }

    @staticmethod
    def _biz_from_article_url(article_link: str) -> str:
        query = dict(parse_qsl(urlsplit(str(article_link or "")).query, keep_blank_values=True))
        return str(query.get("__biz") or "").strip()

    @classmethod
    def _extract_rss_body(cls, payload: str, article_link: str) -> str:
        try:
            root = ElementTree.fromstring(payload)
        except ElementTree.ParseError:
            return ""
        target_identity = _article_identity(article_link)
        for entry in root.findall(f"{{{_ATOM_NAMESPACE}}}entry"):
            entry_link = ""
            for link in entry.findall(f"{{{_ATOM_NAMESPACE}}}link"):
                if link.attrib.get("rel", "alternate") == "alternate":
                    entry_link = link.attrib.get("href", "")
                    break
            if entry_link and _article_identity(entry_link) != target_identity:
                continue
            content = entry.find(f"{{{_ATOM_NAMESPACE}}}content")
            raw_content = "".join(content.itertext()).strip() if content is not None else ""
            body, _ = extract_wechat_article_body_markdown(raw_content)
            if not body and raw_content:
                body, _ = extract_wechat_article_body_markdown(
                    f'<div id="js_content">{raw_content}</div>'
                )
            if body:
                return body
        return ""


def get_wx_channel_client() -> WxChannelClient:
    return WxChannelClient(
        settings.wx_channel_api_base_url,
        timeout_seconds=settings.wx_channel_request_timeout_seconds,
    )
