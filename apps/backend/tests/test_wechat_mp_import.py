from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.wechat_mp import WechatMpArticleImportRequest
from app.services import workbench
from app.services.wechat_mp_client import WechatMpClient, WechatMpSessionStore


client = TestClient(app)


def wait_for_background_task(task_id: str, timeout_seconds: float = 5.0) -> dict[str, object]:
    import time

    deadline = time.time() + timeout_seconds
    last_payload: dict[str, object] | None = None
    while time.time() < deadline:
        response = client.get(f"/api/background-tasks/{task_id}")
        assert response.status_code == 200
        last_payload = response.json()
        if last_payload["status"] in {"done", "failed"}:
            return last_payload
        time.sleep(0.05)
    raise AssertionError(f"Background task {task_id} did not finish in time: {last_payload}")


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
                        "body_markdown": "第一段：先接住失望。\n\n第二段：再谈解释。",
                        "body_source": "dom",
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
    assert tracked_articles[0]["source_kind"] == "wechat_mp_import"
    assert tracked_articles[0]["created_at"]
    assert tracked_articles[0]["body_markdown"] == "第一段：先接住失望。\n\n第二段：再谈解释。"
    assert tracked_articles[0]["body_source"] == "dom"
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


def test_wechat_mp_import_background_metadata_enrichment_runs_as_pipeline_task(monkeypatch) -> None:
    class FakeClient:
        def import_articles(self, payload):
            return {
                "imported_count": 2,
                "created": [
                    {
                        "slug": "wechat-mp-cold-love-1",
                        "source_name": "冷爱",
                        "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                        "url": "https://mp.weixin.qq.com/s/cold-love-1",
                        "author": "冷爱",
                        "summary": "",
                        "body_markdown": "第一段：先写卡住感。",
                        "body_source": "content_noencode",
                        "structure_notes": "",
                        "tags": [],
                    },
                    {
                        "slug": "wechat-mp-cold-love-2",
                        "source_name": "冷爱",
                        "title": "关系修复里最难的，不是方法，是那点没回来的心气",
                        "url": "https://mp.weixin.qq.com/s/cold-love-2",
                        "author": "",
                        "summary": "已有原始摘要。",
                        "body_markdown": "第一段：先写无力感。",
                        "body_source": "content_noencode",
                        "structure_notes": "",
                        "tags": ["公众号参考"],
                    },
                ],
            }

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(str(payload["article_title"]))
            return {
                "author": "冷爱",
                "summary": f"补全：{payload['article_title']}",
                "structure_notes": "先写问题感，再拆中段推进，最后回到现实动作。",
                "tags": ["关系修复", "公众号参考"],
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr("app.api.wechat_mp.get_wechat_mp_client", lambda: FakeClient())
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    import_response = client.post(
        "/api/wechat-mp/articles/import",
        json={
            "articles": [
                {
                    "article_id": "cold-love-1",
                    "account_fakeid": "MzA3NzAyMzMyMA==",
                    "account_nickname": "冷爱",
                    "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                    "link": "https://mp.weixin.qq.com/s/cold-love-1",
                    "author": "冷爱",
                    "digest": "",
                    "update_time": 1716012345,
                },
                {
                    "article_id": "cold-love-2",
                    "account_fakeid": "MzA3NzAyMzMyMA==",
                    "account_nickname": "冷爱",
                    "title": "关系修复里最难的，不是方法，是那点没回来的心气",
                    "link": "https://mp.weixin.qq.com/s/cold-love-2",
                    "author": "",
                    "digest": "已有原始摘要。",
                    "update_time": 1716012350,
                },
            ]
        },
    )
    assert import_response.status_code == 201

    submit_response = client.post(
        "/api/tracked-articles/enrich-metadata/background",
        json={"article_slugs": ["wechat-mp-cold-love-1", "wechat-mp-cold-love-2"]},
    )
    assert submit_response.status_code == 202
    submit_payload = submit_response.json()
    assert submit_payload["job_type"] == "enrich_tracked_articles_metadata"

    task_payload = wait_for_background_task(submit_payload["task_id"])
    assert task_payload["status"] == "done"
    assert task_payload["result"] is not None
    assert task_payload["result"]["requested_count"] == 2
    assert task_payload["result"]["processed_count"] == 2
    assert task_payload["result"]["skipped_count"] == 0
    assert task_payload["result"]["failed_count"] == 0

    tracked_articles = {item["slug"]: item for item in client.get("/api/tracked-articles").json()}
    assert tracked_articles["wechat-mp-cold-love-1"]["summary"] == "补全：关系卡住的本质：意愿有、懂方法、但无能量"
    assert tracked_articles["wechat-mp-cold-love-2"]["author"] == "冷爱"
    assert tracked_articles["wechat-mp-cold-love-2"]["structure_notes"] == "先写问题感，再拆中段推进，最后回到现实动作。"

    pipeline_logs = client.get("/api/background-tasks/logs?scope=pipeline").json()
    matching_log = next((item for item in pipeline_logs if item["background_task_id"] == submit_payload["task_id"]), None)
    assert matching_log is not None
    assert matching_log["task_type"] == "enrich_tracked_articles_metadata"


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
                        "body_markdown": "第一段：先接住失望。",
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

        def fetch_article_body(self, article_link: str, fallback_digest: str) -> tuple[str, str]:
            assert article_link == "https://mp.weixin.qq.com/s/example"
            assert fallback_digest == "从关系修复案例提炼表达顺序。"
            return ("第一段：关系里的失望先要被接住。", "dom")

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
    assert payload["created"][0]["body_markdown"] == "第一段：关系里的失望先要被接住。"
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

    monkeypatch.setattr(client_instance, "_refresh_logged_in_session_status_if_needed", session_store.status)
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

    monkeypatch.setattr(client_instance, "_refresh_logged_in_session_status_if_needed", session_store.status)
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


def test_wechat_mp_client_import_articles_fetches_full_article_body_from_article_page(monkeypatch, tmp_path) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save({"logged_in": True, "cookie": "auth-key=test"})
    client_instance = WechatMpClient(session_store)
    captured: dict[str, object] = {}

    def fake_request_response(
        *,
        method: str,
        endpoint: str,
        query: dict[str, object],
        body: dict[str, object] | None = None,
        cookie: str | None = None,
    ) -> httpx.Response:
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["query"] = query
        captured["body"] = body
        captured["cookie"] = cookie
        return httpx.Response(
            200,
            text="""
            <html>
              <body>
                <div id="js_content">
                  <p>第一段：先接住那一下失望。</p>
                  <p>第二段：别急着解释，先把情绪放稳。</p>
                  <section>
                    <p><strong>第三段</strong>：等对方不再绷着，话才进得去。</p>
                  </section>
                  <script>window.shouldNotAppear = true;</script>
                  <style>.hidden { display:none; }</style>
                </div>
              </body>
            </html>
            """,
        )

    monkeypatch.setattr(client_instance, "_request_response", fake_request_response)

    payload = client_instance.import_articles(
        WechatMpArticleImportRequest.model_validate(
            {
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
            }
        )
    )

    assert payload["requested_count"] == 1
    assert payload["imported_count"] == 1
    assert payload["created"][0]["body_markdown"] == (
        "第一段：先接住那一下失望。\n\n"
        "第二段：别急着解释，先把情绪放稳。\n\n"
        "第三段：等对方不再绷着，话才进得去。"
    )
    assert captured == {
        "method": "GET",
        "endpoint": "https://mp.weixin.qq.com/s/example",
        "query": {},
        "body": None,
        "cookie": None,
    }


def test_wechat_mp_client_fetch_article_body_markdown_falls_back_to_digest_when_fetch_fails(
    monkeypatch,
    tmp_path,
) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    client_instance = WechatMpClient(session_store)

    def fake_request_response(**_: object) -> httpx.Response:
        raise httpx.ConnectError("network down")

    monkeypatch.setattr(client_instance, "_request_response", fake_request_response)

    payload = client_instance._fetch_article_body_markdown(
        "https://mp.weixin.qq.com/s/example",
        "从关系修复案例提炼表达顺序。",
    )

    assert payload == "从关系修复案例提炼表达顺序。"


def test_wechat_mp_client_list_articles_sanitizes_dirty_digest_from_wechat_publish_payload(
    monkeypatch,
    tmp_path,
) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save({"logged_in": True, "token": "test-token", "cookie": "auth-key=test"})
    client_instance = WechatMpClient(session_store)

    def fake_request(*, method: str, endpoint: str, query: dict[str, object], **kwargs):
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
                                            "title": "离婚不离家最大的代价，到底在惩罚谁",
                                            "link": "https://mp.weixin.qq.com/s/example",
                                            "author_name": "冷爱",
                                            "digest": (
                                                "很多人离婚后，因为孩子、房子、经济压力，选择继续住在一起。"
                                                "&nbsp;点击菜单栏-【情感咨询】，或点击下方文章给自己一个机会。 "
                                                '&lt;a class="wx_topic_link" topic-id="abc"&gt;#离婚不离家&lt;/a&gt; '
                                                '&lt;a class="wx_topic_link" topic-id="def"&gt;#情感内耗&lt;/a&gt;'
                                            ),
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

    monkeypatch.setattr(client_instance, "_refresh_logged_in_session_status_if_needed", session_store.status)
    monkeypatch.setattr(client_instance, "_request_json", fake_request)

    payload = client_instance.list_articles(fakeid="MzA3NzAyMzMyMA==", begin=0, size=5, keyword="")
    assert payload[0]["digest"] == (
        "很多人离婚后，因为孩子、房子、经济压力，选择继续住在一起。 "
        "点击菜单栏-【情感咨询】，或点击下方文章给自己一个机会。 "
        "#离婚不离家 #情感内耗"
    )


def test_wechat_mp_client_extract_article_body_markdown_strips_escaped_topic_links_and_nbsp() -> None:
    client_instance = WechatMpClient(WechatMpSessionStore("memory://unused"))

    body_markdown, body_source = client_instance._extract_article_body_markdown(
        """
        <html>
          <body>
            <div id="js_content">
              <p>很多人离婚后，因为孩子、房子、经济压力，选择继续住在一起。&nbsp;最难受的状态就是：关系已经结束了，生活却还绑在一起。</p>
              <p>点击菜单栏-【情感咨询】，或点击下方文章给自己一个机会。&lt;a class="wx_topic_link" topic-id="abc"&gt;#离婚不离家&lt;/a&gt; &lt;a class="wx_topic_link" topic-id="def"&gt;#情感内耗&lt;/a&gt;</p>
            </div>
          </body>
        </html>
        """
    )

    assert body_markdown == (
        "很多人离婚后，因为孩子、房子、经济压力，选择继续住在一起。 最难受的状态就是：关系已经结束了，生活却还绑在一起。\n\n"
        "点击菜单栏-【情感咨询】，或点击下方文章给自己一个机会。#离婚不离家 #情感内耗"
    )
    assert body_source == "dom"


def test_wechat_mp_client_extract_article_body_markdown_falls_back_to_content_noencode_when_js_content_dom_missing() -> None:
    client_instance = WechatMpClient(WechatMpSessionStore("memory://unused"))

    body_markdown, body_source = client_instance._extract_article_body_markdown(
        r"""
        <html>
          <head><title>微信公众平台</title></head>
          <body>
            <script>
              window.__testData = {
                title: '\u5173\u7cfb\u5361\u4f4f\u7684\u672c\u8d28\uff1a\u610f\u613f\u6709\u3001\u61c2\u65b9\u6cd5\u3001\u4f46\u65e0\u80fd\u91cf',
                content_noencode: '\u5f88\u591a\u4eba\u4ee5\u4e3a\u81ea\u5df1\u7684\u5173\u7cfb\u5361\u4f4f\uff0c\u662f\u56e0\u4e3a\uff1a\\x0a\u4e0d\u77e5\u9053\u600e\u4e48\u9009\\x0a\u65b9\u6cd5\u4e0d\u5bf9\\x0a\\x0a\u771f\u6b63\u8ba9\u4eba\u957f\u671f\u5361\u4f4f\u7684\uff0c\u4ece\u6765\u4e0d\u662f\u201c\u4e0d\u4f1a\u505a\u201d\uff0c\u800c\u662f\u201c\u6ca1\u6709\u80fd\u91cf\u53bb\u505a\u201d\u3002\\x0a\\x0a\u2714 \u610f\u613f\u6709\\x0a\u2714 \u65b9\u6cd5\u4e5f\u77e5\u9053\\x0a\u274c \u4f46\u6ca1\u6709\u80fd\u91cf',
                desc: ''
              };
            </script>
          </body>
        </html>
        """
    )

    assert body_markdown == (
        "很多人以为自己的关系卡住，是因为：\n"
        "不知道怎么选\n"
        "方法不对\n\n"
        "真正让人长期卡住的，从来不是“不会做”，而是“没有能量去做”。\n\n"
        "✔ 意愿有\n"
        "✔ 方法也知道\n"
        "❌ 但没有能量"
    )
    assert body_source == "content_noencode"


def test_wechat_mp_client_extract_article_body_markdown_preserves_unicode_when_content_noencode_mixes_chinese_and_escaped_newlines() -> None:
    client_instance = WechatMpClient(WechatMpSessionStore("memory://unused"))

    body_markdown, body_source = client_instance._extract_article_body_markdown(
        r"""
        <html>
          <body>
            <script>
              window.__testData = {
                content_noencode: '很多人以为自己的关系卡住，是因为：\\x0a不知道怎么选\\x0a方法不对\\x0a\\x0a真正让人长期卡住的，从来不是“不会做”，而是“没有能量去做”。'
              };
            </script>
          </body>
        </html>
        """
    )

    assert body_markdown == (
        "很多人以为自己的关系卡住，是因为：\n"
        "不知道怎么选\n"
        "方法不对\n\n"
        "真正让人长期卡住的，从来不是“不会做”，而是“没有能量去做”。"
    )
    assert body_source == "content_noencode"


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


def test_wechat_mp_client_get_session_status_keeps_valid_logged_in_session(monkeypatch, tmp_path) -> None:
    future_expires_at = "2099-05-31T12:00:00+08:00"
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save(
        {
            "logged_in": True,
            "cookie": "uuid=test; auth-key=abc",
            "token": "token-123",
            "nickname": "测试公众号",
            "expires_at": future_expires_at,
            "login_stage": "logged_in",
            "status_message": "登录成功",
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
        return httpx.Response(
            200,
            request=httpx.Request(method, endpoint),
            content='wx.cgiData.nick_name = "测试公众号";'.encode("utf-8"),
        )

    monkeypatch.setattr(client_instance, "_request_response", fake_request_response)

    payload = client_instance.get_session_status()
    assert payload == {
        "logged_in": True,
        "nickname": "测试公众号",
        "expires_at": future_expires_at,
        "login_stage": "logged_in",
        "status_message": "登录成功",
    }
    assert captured == [
        {
            "method": "GET",
            "endpoint": "https://mp.weixin.qq.com/cgi-bin/home",
            "query": {
                "t": "home/index",
                "token": "token-123",
                "lang": "zh_CN",
            },
            "body": None,
            "cookie": "uuid=test; auth-key=abc",
        }
    ]


def test_wechat_mp_client_get_session_status_marks_expired_logged_in_session(monkeypatch, tmp_path) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save(
        {
            "logged_in": True,
            "cookie": "uuid=test; auth-key=abc",
            "token": "token-123",
            "nickname": "测试公众号",
            "expires_at": "2026-05-31T12:00:00+08:00",
            "login_stage": "logged_in",
            "status_message": "登录成功",
        }
    )
    client_instance = WechatMpClient(session_store)

    def fake_request_response(
        *,
        method: str,
        endpoint: str,
        query: dict[str, object],
        body: dict[str, object] | None = None,
        cookie: str | None = None,
    ) -> httpx.Response:
        return httpx.Response(
            302,
            request=httpx.Request(method, endpoint),
            headers={"location": "https://mp.weixin.qq.com/cgi-bin/loginpage?t=wxm2-login&lang=zh_CN"},
        )

    monkeypatch.setattr(client_instance, "_request_response", fake_request_response)

    payload = client_instance.get_session_status()
    assert payload == {
        "logged_in": False,
        "nickname": None,
        "expires_at": None,
        "login_stage": "expired",
        "status_message": "公众号登录已过期，请重新扫码登录",
    }

    stored = session_store.load()
    assert stored is not None
    assert stored["logged_in"] is False
    assert stored["nickname"] is None
    assert stored["expires_at"] is None
    assert stored["login_stage"] == "expired"
    assert stored["status_message"] == "公众号登录已过期，请重新扫码登录"
    assert stored.get("cookie") is None
    assert stored.get("token") is None


def test_wechat_mp_client_search_accounts_rejects_expired_logged_in_session(monkeypatch, tmp_path) -> None:
    session_store = WechatMpSessionStore(str(tmp_path / "wechat-session.json"))
    session_store.save(
        {
            "logged_in": True,
            "cookie": "uuid=test; auth-key=abc",
            "token": "token-123",
            "nickname": "测试公众号",
            "expires_at": "2026-05-31T12:00:00+08:00",
            "login_stage": "logged_in",
            "status_message": "登录成功",
        }
    )
    client_instance = WechatMpClient(session_store)

    def fake_request_response(
        *,
        method: str,
        endpoint: str,
        query: dict[str, object],
        body: dict[str, object] | None = None,
        cookie: str | None = None,
    ) -> httpx.Response:
        if endpoint != "https://mp.weixin.qq.com/cgi-bin/home":
            raise AssertionError(f"unexpected request after expired session check: {endpoint}")
        return httpx.Response(
            302,
            request=httpx.Request(method, endpoint),
            headers={"location": "https://mp.weixin.qq.com/cgi-bin/loginpage?t=wxm2-login&lang=zh_CN"},
        )

    monkeypatch.setattr(client_instance, "_request_response", fake_request_response)

    with pytest.raises(RuntimeError, match="公众号登录已过期，请重新扫码登录"):
        client_instance.search_accounts(keyword="关系", begin=0, size=5)

    assert session_store.status() == {
        "logged_in": False,
        "nickname": None,
        "expires_at": None,
        "login_stage": "expired",
        "status_message": "公众号登录已过期，请重新扫码登录",
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
