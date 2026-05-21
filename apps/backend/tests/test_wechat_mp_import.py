from __future__ import annotations

import json

import httpx
from fastapi.testclient import TestClient

from app.main import app
from app.services import workbench
from app.services.wechat_mp_client import WechatMpClient, WechatMpSessionStore


client = TestClient(app)


def test_wechat_mp_session_response_excludes_sensitive_fields(monkeypatch) -> None:
    class FakeClient:
        def get_session_status(self) -> dict[str, object]:
            return {
                "logged_in": True,
                "nickname": "测试公众号",
                "expires_at": "2026-05-19T12:00:00+08:00",
                "login_stage": "logged_in",
                "status_message": "登录成功",
            }

    monkeypatch.setattr("app.api.wechat_mp.get_wechat_mp_client", lambda: FakeClient())

    response = client.get("/api/wechat-mp/session")
    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "logged_in": True,
        "nickname": "测试公众号",
        "expires_at": "2026-05-19T12:00:00+08:00",
        "login_stage": "logged_in",
        "status_message": "登录成功",
    }
    assert "cookie" not in payload
    assert "token" not in payload
    assert "headers" not in payload


def test_wechat_mp_login_qrcode_route_returns_binary_image_response(monkeypatch) -> None:
    class FakeClient:
        def start_login_qrcode(self) -> dict[str, object]:
            return {
                "content_type": "image/jpeg",
                "image_bytes": b"fake-qrcode-bytes",
            }

    monkeypatch.setattr("app.api.wechat_mp.get_wechat_mp_client", lambda: FakeClient())

    response = client.post("/api/wechat-mp/login/qrcode")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"fake-qrcode-bytes"


def test_wechat_mp_account_search_uses_expected_searchbiz_params(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def search_accounts(self, *, keyword: str, begin: int, size: int) -> list[dict[str, object]]:
            captured["keyword"] = keyword
            captured["begin"] = begin
            captured["size"] = size
            return [
                {
                    "fakeid": "MzA3NzAyMzMyMA==",
                    "nickname": "关系练习手册",
                    "alias": "gh_test",
                    "round_head_img": "https://example.com/avatar.png",
                    "service_type": 2,
                    "signature": "测试签名",
                }
            ]

    monkeypatch.setattr("app.api.wechat_mp.get_wechat_mp_client", lambda: FakeClient())

    response = client.get("/api/wechat-mp/accounts", params={"keyword": "关系", "begin": 0, "size": 5})
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["fakeid"] == "MzA3NzAyMzMyMA=="
    assert captured == {"keyword": "关系", "begin": 0, "size": 5}


def test_wechat_mp_article_preview_uses_expected_appmsgpublish_params(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def list_articles(self, *, fakeid: str, begin: int, size: int, keyword: str | None) -> list[dict[str, object]]:
            captured["fakeid"] = fakeid
            captured["begin"] = begin
            captured["size"] = size
            captured["keyword"] = keyword
            return [
                {
                    "article_id": "12345_1",
                    "account_fakeid": fakeid,
                    "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
                    "link": "https://mp.weixin.qq.com/s/example",
                    "author": "北岛",
                    "digest": "从关系修复案例提炼表达顺序。",
                    "update_time": 1716012345,
                    "account_nickname": "夜读关系实验室",
                }
            ]

    monkeypatch.setattr("app.api.wechat_mp.get_wechat_mp_client", lambda: FakeClient())

    response = client.get(
        "/api/wechat-mp/accounts/MzA3NzAyMzMyMA==/articles",
        params={"begin": 0, "size": 5, "keyword": ""},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["article_id"] == "12345_1"
    assert payload[0]["account_fakeid"] == "MzA3NzAyMzMyMA=="
    assert payload[0]["title"] == "真正让关系缓回来，不是解释，是先接住那一下失望"
    assert captured == {
        "fakeid": "MzA3NzAyMzMyMA==",
        "begin": 0,
        "size": 5,
        "keyword": "",
    }


def test_wechat_mp_import_creates_tracked_articles_and_can_generate_topics(monkeypatch) -> None:
    class FakeClient:
        def import_articles(self, payload):
            return {
                "imported_count": 1,
                "created": [
                    {
                        "slug": "wechat-mp-night-read-12345-1",
                        "source_name": "夜读关系实验室",
                        "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
                        "url": "https://mp.weixin.qq.com/s/example",
                        "author": "北岛",
                        "summary": "从关系修复案例提炼表达顺序。",
                        "structure_notes": "Imported from WeChat MP article list; structure notes pending review.",
                        "tags": ["wechat-mp", "夜读关系实验室"],
                    }
                ],
            }

    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "比解释更重要的，是先接住关系里的那一下失望",
                "angle": "修复顺序",
            }

    monkeypatch.setattr("app.api.wechat_mp.get_wechat_mp_client", lambda: FakeClient())
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    import_response = client.post(
        "/api/wechat-mp/articles/import",
        json={
            "articles": [
                {
                    "article_id": "12345_1",
                    "account_fakeid": "MzA3NzAyMzMyMA==",
                    "account_nickname": "夜读关系实验室",
                    "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
                    "link": "https://mp.weixin.qq.com/s/example",
                    "author": "北岛",
                    "digest": "从关系修复案例提炼表达顺序。",
                    "update_time": 1716012345,
                }
            ]
        },
    )
    assert import_response.status_code == 201
    imported_payload = import_response.json()
    assert imported_payload["requested_count"] == 1
    assert imported_payload["imported_count"] == 1
    assert imported_payload["skipped_count"] == 0
    assert imported_payload["failed_count"] == 0
    assert imported_payload["run_id"] is not None
    assert imported_payload["created"][0]["slug"] == "wechat-mp-night-read-12345-1"
    assert imported_payload["results"][0]["status"] == "created"

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    tracked_articles = list_response.json()
    assert tracked_articles[0]["slug"] == "wechat-mp-night-read-12345-1"
    assert tracked_articles[0]["tags"] == ["wechat-mp", "夜读关系实验室"]

    dashboard_response = client.get("/api/dashboard/summary")
    assert dashboard_response.status_code == 200
    dashboard_payload = dashboard_response.json()
    assert dashboard_payload["tracked_articles_count"] == 1
    assert dashboard_payload["source_ingestion_runs_count"] == 1
    assert dashboard_payload["latest_source_ingestion_kind"] == "wechat_mp_import"
    assert dashboard_payload["source_freshness_state"] == "fresh"

    topic_response = client.post("/api/tracked-articles/wechat-mp-night-read-12345-1/generate-topic")
    assert topic_response.status_code == 201
    topic_payload = topic_response.json()
    assert topic_payload["source_type"] == "tracked_article"
    assert topic_payload["title"] == "比解释更重要的，是先接住关系里的那一下失望"


def test_wechat_mp_import_skips_duplicate_articles_by_url(monkeypatch) -> None:
    class FakeClient:
        def import_articles(self, payload):
            return {
                "created": [
                    {
                        "slug": "wechat-mp-night-read-12345-1",
                        "source_name": "夜读关系实验室",
                        "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
                        "url": "https://mp.weixin.qq.com/s/example",
                        "author": "北岛",
                        "summary": "从关系修复案例提炼表达顺序。",
                        "structure_notes": "Imported from WeChat MP article list; structure notes pending review.",
                        "tags": ["wechat-mp", "夜读关系实验室"],
                    }
                ],
            }

    monkeypatch.setattr("app.api.wechat_mp.get_wechat_mp_client", lambda: FakeClient())

    first_response = client.post(
        "/api/wechat-mp/articles/import",
        json={
            "articles": [
                {
                    "article_id": "12345_1",
                    "account_fakeid": "MzA3NzAyMzMyMA==",
                    "account_nickname": "夜读关系实验室",
                    "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
                    "link": "https://mp.weixin.qq.com/s/example",
                    "author": "北岛",
                    "digest": "从关系修复案例提炼表达顺序。",
                    "update_time": 1716012345,
                }
            ]
        },
    )
    assert first_response.status_code == 201

    second_response = client.post(
        "/api/wechat-mp/articles/import",
        json={
            "articles": [
                {
                    "article_id": "12345_1",
                    "account_fakeid": "MzA3NzAyMzMyMA==",
                    "account_nickname": "夜读关系实验室",
                    "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
                    "link": "https://mp.weixin.qq.com/s/example",
                    "author": "北岛",
                    "digest": "从关系修复案例提炼表达顺序。",
                    "update_time": 1716012345,
                }
            ]
        },
    )
    assert second_response.status_code == 201
    payload = second_response.json()
    assert payload["requested_count"] == 1
    assert payload["imported_count"] == 0
    assert payload["skipped_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["results"][0]["status"] == "skipped"
    assert payload["results"][0]["reason"] == "Tracked article already exists for this URL"

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


def test_wechat_mp_import_falls_back_to_selected_account_nickname_when_article_nickname_missing(monkeypatch) -> None:
    class FakeClient:
        def import_articles(self, payload):
            return WechatMpClient.import_articles(self, payload)

        def _build_article_slug(self, *, account_nickname: str, article_id: str) -> str:
            return WechatMpClient._build_article_slug(self, account_nickname=account_nickname, article_id=article_id)

    monkeypatch.setattr("app.api.wechat_mp.get_wechat_mp_client", lambda: FakeClient())

    response = client.post(
        "/api/wechat-mp/articles/import",
        json={
            "fallback_account_nickname": "今晚有语",
            "articles": [
                {
                    "article_id": "12345_1",
                    "account_fakeid": "MzA3NzAyMzMyMA==",
                    "account_nickname": "",
                    "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
                    "link": "https://mp.weixin.qq.com/s/example",
                    "author": "",
                    "digest": "从关系修复案例提炼表达顺序。",
                    "update_time": 1716012345,
                }
            ],
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["imported_count"] == 1
    assert payload["created"][0]["slug"] == "wechat-mp-今晚有语-12345-1"
    assert payload["created"][0]["source_name"] == "今晚有语"
    assert payload["created"][0]["author"] == "今晚有语"
    assert payload["created"][0]["tags"] == ["wechat-mp", "今晚有语"]


def test_wechat_mp_client_search_accounts_builds_expected_searchbiz_request(monkeypatch, tmp_path) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save({"logged_in": True, "token": "test-token", "cookie": "auth-key=test"})
    client_instance = WechatMpClient(session_store)
    captured: dict[str, object] = {}

    def fake_request(*, method: str, endpoint: str, query: dict[str, object], **kwargs):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["query"] = query
        return {
            "list": [
                {
                    "fakeid": "MzA3NzAyMzMyMA==",
                    "nickname": "关系练习手册",
                    "alias": "gh_test",
                    "round_head_img": "https://example.com/avatar.png",
                    "service_type": 2,
                    "signature": "测试签名",
                }
            ]
        }

    monkeypatch.setattr(client_instance, "_request_json", fake_request)

    payload = client_instance.search_accounts(keyword="关系", begin=0, size=5)
    assert payload[0]["fakeid"] == "MzA3NzAyMzMyMA=="
    assert captured["method"] == "GET"
    assert captured["endpoint"] == "https://mp.weixin.qq.com/cgi-bin/searchbiz"
    assert captured["query"] == {
        "action": "search_biz",
        "begin": 0,
        "count": 5,
        "query": "关系",
        "token": "test-token",
        "lang": "zh_CN",
        "f": "json",
        "ajax": "1",
    }


def test_wechat_mp_client_list_articles_builds_expected_appmsgpublish_request_and_flattens_publish_page(
    monkeypatch,
    tmp_path,
) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save({"logged_in": True, "token": "test-token", "cookie": "auth-key=test"})
    client_instance = WechatMpClient(session_store)
    captured: dict[str, object] = {}

    def fake_request(*, method: str, endpoint: str, query: dict[str, object], **kwargs):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["query"] = query
        return {
            "base_resp": {"ret": 0},
            "publish_page": json.dumps(
                {
                    "publish_list": [
                        {
                            "publish_info": json.dumps(
                                {
                                    "appmsgex": [
                                        {
                                            "aid": "12345_1",
                                            "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
                                            "link": "https://mp.weixin.qq.com/s/example",
                                            "author_name": "北岛",
                                            "digest": "从关系修复案例提炼表达顺序。",
                                            "update_time": 1716012345,
                                        }
                                    ]
                                }
                            )
                        }
                    ]
                }
            ),
        }

    monkeypatch.setattr(client_instance, "_request_json", fake_request)

    payload = client_instance.list_articles(fakeid="MzA3NzAyMzMyMA==", begin=0, size=5, keyword="")
    assert payload == [
        {
            "article_id": "12345_1",
            "account_fakeid": "MzA3NzAyMzMyMA==",
            "account_nickname": "",
            "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "link": "https://mp.weixin.qq.com/s/example",
            "author": "北岛",
            "digest": "从关系修复案例提炼表达顺序。",
            "update_time": 1716012345,
        }
    ]
    assert captured["method"] == "GET"
    assert captured["endpoint"] == "https://mp.weixin.qq.com/cgi-bin/appmsgpublish"
    assert captured["query"] == {
        "sub": "list",
        "search_field": "null",
        "begin": 0,
        "count": 5,
        "query": "",
        "fakeid": "MzA3NzAyMzMyMA==",
        "type": "101_1",
        "free_publish_type": 1,
        "sub_action": "list_ex",
        "token": "test-token",
        "lang": "zh_CN",
        "f": "json",
        "ajax": 1,
    }


def test_wechat_mp_client_start_login_qrcode_bootstraps_prelogin_session_and_fetches_qrcode(
    monkeypatch,
    tmp_path,
) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    client_instance = WechatMpClient(session_store)
    captured: list[dict[str, object]] = []

    def fake_request_response(
        *,
        method: str,
        endpoint: str,
        query: dict[str, object],
        body: dict[str, object] | None = None,
        cookie: str | None = None,
    ) -> httpx.Response:
        captured.append(
            {
                "method": method,
                "endpoint": endpoint,
                "query": query,
                "body": body,
                "cookie": cookie,
            }
        )
        if endpoint.endswith("/cgi-bin/bizlogin"):
            return httpx.Response(
                200,
                headers={"set-cookie": "uuid=test-uuid; Path=/; HttpOnly"},
                json={"base_resp": {"ret": 0}},
            )
        return httpx.Response(
            200,
            headers={"content-type": "image/jpeg"},
            content=b"fake-qrcode-bytes",
        )

    monkeypatch.setattr(client_instance, "_request_response", fake_request_response)

    payload = client_instance.start_login_qrcode()
    assert payload["content_type"] == "image/jpeg"
    assert payload["image_bytes"] == b"fake-qrcode-bytes"
    assert captured[0]["method"] == "POST"
    assert captured[0]["endpoint"] == "https://mp.weixin.qq.com/cgi-bin/bizlogin"
    assert captured[0]["query"] == {"action": "startlogin"}
    assert captured[0]["body"] is not None
    assert captured[0]["body"]["login_type"] == 3
    assert captured[1]["method"] == "GET"
    assert captured[1]["endpoint"] == "https://mp.weixin.qq.com/cgi-bin/scanloginqrcode"
    assert captured[1]["query"]["action"] == "getqrcode"
    assert "random" in captured[1]["query"]
    assert captured[1]["cookie"] == "uuid=test-uuid"

    stored = session_store.load()
    assert stored is not None
    assert stored["logged_in"] is False
    assert stored["pre_login_cookie"] == "uuid=test-uuid"
    assert stored["login_stage"] == "waiting_scan"
    assert stored["status_message"] == "等待扫码"


def test_wechat_mp_client_poll_login_status_marks_waiting_confirmation(monkeypatch, tmp_path) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save(
        {
            "logged_in": False,
            "pre_login_cookie": "uuid=test-uuid",
            "login_stage": "waiting_scan",
            "status_message": "等待扫码",
        }
    )
    client_instance = WechatMpClient(session_store)
    captured: dict[str, object] = {}

    def fake_json_request(*, method: str, endpoint: str, query: dict[str, object], cookie: str | None = None):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["query"] = query
        captured["cookie"] = cookie
        return {
            "base_resp": {"ret": 0},
            "status": 4,
            "acct_size": 1,
        }

    monkeypatch.setattr(client_instance, "_request_json", fake_json_request)

    payload = client_instance.poll_login_status()
    assert payload == {
        "logged_in": False,
        "nickname": None,
        "expires_at": None,
        "login_stage": "waiting_confirmation",
        "status_message": "扫码成功，等待确认",
    }
    assert captured == {
        "method": "GET",
        "endpoint": "https://mp.weixin.qq.com/cgi-bin/scanloginqrcode",
        "query": {
            "action": "ask",
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": 1,
        },
        "cookie": "uuid=test-uuid",
    }


def test_wechat_mp_client_poll_login_status_completes_login_after_confirmation(monkeypatch, tmp_path) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save(
        {
            "logged_in": False,
            "pre_login_cookie": "uuid=test-uuid",
            "login_stage": "waiting_scan",
            "status_message": "等待扫码",
        }
    )
    client_instance = WechatMpClient(session_store)
    captured: dict[str, object] = {"completed": False}

    def fake_json_request(*, method: str, endpoint: str, query: dict[str, object], cookie: str | None = None):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["query"] = query
        captured["cookie"] = cookie
        return {
            "base_resp": {"ret": 0},
            "status": 1,
            "acct_size": 1,
        }

    def fake_complete_login() -> dict[str, object]:
        captured["completed"] = True
        return {
            "logged_in": True,
            "nickname": "测试公众号",
            "expires_at": "2026-05-22T12:00:00+00:00",
            "login_stage": "logged_in",
            "status_message": "登录成功",
        }

    monkeypatch.setattr(client_instance, "_request_json", fake_json_request)
    monkeypatch.setattr(client_instance, "complete_login", fake_complete_login)

    payload = client_instance.poll_login_status()
    assert payload["logged_in"] is True
    assert payload["nickname"] == "测试公众号"
    assert payload["login_stage"] == "logged_in"
    assert captured["completed"] is True


def test_wechat_mp_client_complete_login_persists_real_session_from_wechat_responses(monkeypatch, tmp_path) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save(
        {
            "logged_in": False,
            "pre_login_cookie": "uuid=test-uuid",
            "login_stage": "waiting_confirmation",
            "status_message": "扫码成功，等待确认",
        }
    )
    client_instance = WechatMpClient(session_store)
    captured: list[dict[str, object]] = []

    def fake_request_response(
        *,
        method: str,
        endpoint: str,
        query: dict[str, object],
        body: dict[str, object] | None = None,
        cookie: str | None = None,
    ) -> httpx.Response:
        captured.append(
            {
                "method": method,
                "endpoint": endpoint,
                "query": query,
                "body": body,
                "cookie": cookie,
            }
        )
        if endpoint.endswith("/cgi-bin/bizlogin"):
            return httpx.Response(
                200,
                headers=[
                    ("set-cookie", "uuid=EXPIRED; Path=/; HttpOnly"),
                    ("set-cookie", "noticeLoginFlag=1; Path=/; HttpOnly"),
                    ("set-cookie", "bizuin=123456; Path=/; HttpOnly"),
                ],
                json={
                    "base_resp": {"ret": 0},
                    "redirect_url": "/cgi-bin/home?t=home/index&token=token-123&lang=zh_CN",
                },
            )
        return httpx.Response(
            200,
            content=(
                'wx.cgiData.nick_name = "测试公众号";'
                'wx.cgiData.head_img = "https://example.com/avatar.png";'
            ).encode("utf-8"),
        )

    monkeypatch.setattr(client_instance, "_request_response", fake_request_response)

    payload = client_instance.complete_login()
    assert payload["logged_in"] is True
    assert payload["nickname"] == "测试公众号"
    assert payload["login_stage"] == "logged_in"
    assert payload["status_message"] == "登录成功"

    assert captured[0]["method"] == "POST"
    assert captured[0]["endpoint"] == "https://mp.weixin.qq.com/cgi-bin/bizlogin"
    assert captured[0]["query"] == {"action": "login"}
    assert captured[0]["body"] == {
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
    }
    assert captured[0]["cookie"] == "uuid=test-uuid"
    assert captured[1]["method"] == "GET"
    assert captured[1]["endpoint"] == "https://mp.weixin.qq.com/cgi-bin/home"
    assert captured[1]["query"] == {
        "t": "home/index",
        "token": "token-123",
        "lang": "zh_CN",
    }
    assert "bizuin=123456" in str(captured[1]["cookie"])

    stored = session_store.load()
    assert stored is not None
    assert stored["logged_in"] is True
    assert stored["token"] == "token-123"
    assert stored["nickname"] == "测试公众号"
    assert stored["avatar"] == "https://example.com/avatar.png"
    assert stored["login_stage"] == "logged_in"
    assert stored["status_message"] == "登录成功"
    assert stored["pre_login_cookie"] is None
    assert "bizuin=123456" in stored["cookie"]
    assert "uuid=EXPIRED" not in stored["cookie"]


def test_wechat_mp_client_finalize_login_persists_safe_session_status(tmp_path) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    client_instance = WechatMpClient(session_store)

    payload = client_instance.finalize_login(
        cookie="uuid=test; auth-key=abc",
        token="token-123",
        nickname="测试公众号",
    )
    assert payload["logged_in"] is True
    assert payload["nickname"] == "测试公众号"
    assert payload["expires_at"] is not None
    assert payload["login_stage"] == "logged_in"
    assert payload["status_message"] == "登录成功"

    stored = session_store.load()
    assert stored is not None
    assert stored["cookie"] == "uuid=test; auth-key=abc"
    assert stored["token"] == "token-123"
    assert stored["nickname"] == "测试公众号"
    assert stored["login_stage"] == "logged_in"
    assert stored["status_message"] == "登录成功"

    public_status = session_store.status()
    assert public_status == {
        "logged_in": True,
        "nickname": "测试公众号",
        "expires_at": stored["expires_at"],
        "login_stage": "logged_in",
        "status_message": "登录成功",
    }


def test_wechat_mp_login_status_and_logout_routes_return_safe_fields(monkeypatch) -> None:
    class FakeClient:
        def poll_login_status(self) -> dict[str, object]:
            return {
                "logged_in": True,
                "nickname": "测试公众号",
                "expires_at": "2026-05-19T12:00:00+08:00",
                "login_stage": "waiting_confirmation",
                "status_message": "扫码成功，等待确认",
            }

        def logout(self) -> dict[str, object]:
            return {
                "logged_in": False,
                "nickname": None,
                "expires_at": None,
                "login_stage": "logged_out",
                "status_message": None,
            }

    monkeypatch.setattr("app.api.wechat_mp.get_wechat_mp_client", lambda: FakeClient())

    status_response = client.get("/api/wechat-mp/login/status")
    assert status_response.status_code == 200
    assert status_response.json() == {
        "logged_in": True,
        "nickname": "测试公众号",
        "expires_at": "2026-05-19T12:00:00+08:00",
        "login_stage": "waiting_confirmation",
        "status_message": "扫码成功，等待确认",
    }

    logout_response = client.post("/api/wechat-mp/logout")
    assert logout_response.status_code == 200
    assert logout_response.json() == {
        "logged_in": False,
        "nickname": None,
        "expires_at": None,
        "login_stage": "logged_out",
        "status_message": None,
    }
