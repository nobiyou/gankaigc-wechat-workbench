from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services.wx_channel_client import WxChannelApiError, WxChannelClient


def _client(handler):
    return WxChannelClient(
        "http://wx-channel.test:2026/",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_list_accounts_unwraps_wx_channel_response_and_keeps_safe_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/mp/list"
        assert parse_qs(request.url.query.decode()) == {
            "keyword": ["example"],
            "page": ["1"],
            "page_size": ["20"],
        }
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "success",
                "data": {
                    "items": [
                        {
                            "biz": "MzA4-example",
                            "nickname": "Example Account",
                            "avatar_url": "https://img.example/avatar.jpg",
                            "is_effective": True,
                            "article_count": 12,
                            "sync_status": "completed",
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 20,
                },
            },
        )

    account = _client(handler).list_accounts("example", page=1, page_size=20)[0]

    assert account == {
        "source": "wx_channel",
        "biz": "MzA4-example",
        "nickname": "Example Account",
        "avatar_url": "https://img.example/avatar.jpg",
        "is_effective": True,
        "article_count": 12,
        "archived_count": 0,
        "last_sync_at": 0,
        "sync_status": "completed",
        "sync_error": "",
    }
    assert "key" not in account


def test_list_articles_maps_msg_items_to_automation_contract() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/mp/msg/list"
        assert request.url.params["biz"] == "MzA4-example"
        assert request.url.params["offset"] == "0"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "success",
                "data": {
                    "ret": 0,
                    "articles": [
                        {
                            "title": "New article",
                            "digest": "A short summary",
                            "content_url": "https://mp.weixin.qq.com/s/article-1?__biz=MzA4-example&mid=123&idx=2",
                            "source_url": "",
                            "cover": "https://img.example/cover.jpg",
                            "author": "Author",
                            "publish_time": 1730000000,
                            "fileid": 91,
                        }
                    ],
                    "can_msg_continue": 0,
                    "next_offset": 0,
                },
            },
        )

    article = _client(handler).list_articles(
        biz="MzA4-example",
        offset=0,
        limit=5,
    )[0]

    assert article["article_id"] == "mid:123:idx:2"
    assert article["account_biz"] == "MzA4-example"
    assert article["title"] == "New article"
    assert article["link"] == "https://mp.weixin.qq.com/s/article-1?__biz=MzA4-example&idx=2&mid=123"
    assert article["author"] == "Author"
    assert article["update_time"] == 1730000000
    assert article["cover_url"] == "https://img.example/cover.jpg"


def test_fetch_article_body_reads_atom_rss_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rss/mp"
        assert request.url.params["biz"] == "MzA4-example"
        assert request.url.params["content"] == "1"
        return httpx.Response(
            200,
            text=(
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<feed xmlns="http://www.w3.org/2005/Atom">'
                "<entry>"
                '<link rel="alternate" href="https://mp.weixin.qq.com/s/article-1?mid=123&amp;idx=2"/>'
                    '<content type="html"><![CDATA[<section><p>First paragraph</p><p>Second paragraph</p></section>]]></content>'
                "</entry>"
                "</feed>"
            ),
        )

    body, source = _client(handler).fetch_article_body(
        "https://mp.weixin.qq.com/s/article-1?__biz=MzA4-example&amp%3Bmid=123&amp%3Bidx=2",
        "fallback",
        biz="MzA4-example",
    )

    assert body == "First paragraph\n\nSecond paragraph"
    assert source == "wx_channel_rss"


def test_nonzero_wx_channel_response_is_actionable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 401, "message": "account credential expired", "data": None},
        )

    with pytest.raises(WxChannelApiError, match="account credential expired"):
        _client(handler).list_articles(biz="MzA4-example", offset=0, limit=1)
