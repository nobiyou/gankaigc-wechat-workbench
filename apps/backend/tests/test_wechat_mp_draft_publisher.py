from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from app.main import app
from app.services.wechat_mp_draft_publisher import WechatMpDraftPublisher, WechatMpDraftPublishError
from app.services.wechat_mp_draft_publisher import WechatMpDraftPublishResult
import app.services.workbench as workbench


api_client = TestClient(app)


class FakeWechatClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.expired = False

    def _request_authenticated_response(self, **kwargs):
        self.calls.append(kwargs)
        query = kwargs["query"]
        if query.get("scene") == "8":
            payload = {"base_resp": {"ret": 0}, "content": "cover-file-id"}
        elif query.get("scene") == "2":
            payload = {"base_resp": {"ret": 0}, "content_url": "https://mmbiz.qpic.cn/body-image"}
        else:
            payload = {"base_resp": {"ret": 0}, "appMsgId": "draft-123"}
        return httpx.Response(200, json=payload)

    def mark_session_expired(self) -> None:
        self.expired = True

    def get_authenticated_upload_context(self) -> dict[str, str]:
        return {}


def _seed_publish_package(
    project_slug: str,
    *,
    package_status: str = "approved",
    draft_status: str = "not_published",
    markdown_path: Path | None = None,
    cover_path: Path | None = None,
) -> None:
    topic_slug = f"{project_slug}-topic"
    stage = "published" if package_status == "approved" else "assets_ready"
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (topic_slug, "", "manual", "", "测试草稿选题", "从具体场景切入。", "approved"),
        )
        connection.execute(
            """
            INSERT INTO projects (slug, topic_slug, title, stage, owner)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_slug, topic_slug, "测试草稿项目", stage, "editor"),
        )
        connection.execute(
            """
            INSERT INTO outlines (project_slug, version, hook, outline_body)
            VALUES (?, ?, ?, ?)
            """,
            (project_slug, 1, "先写一个具体瞬间。", "1. 现场\n2. 变化\n3. 收束"),
        )
        connection.execute(
            """
            INSERT INTO drafts (project_slug, outline_version, version, title, body_markdown, word_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (project_slug, 1, 1, "测试草稿标题", "# 测试草稿标题\n\n正文内容。", 16),
        )
        connection.execute(
            """
            INSERT INTO assets (
                project_slug, draft_version, version, title_options, recommended_title,
                cover_prompt, cover_copy, social_teaser, social_teaser_options,
                cover_image_path, cover_image_url, cover_image_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                1,
                1,
                json.dumps(["测试草稿标题"], ensure_ascii=False),
                "测试草稿标题",
                "16:9 横版公众号封面。",
                "测试封面文案",
                "测试发布导语",
                "[]",
                str(cover_path or ""),
                "/generated-assets/test-cover.png" if cover_path else "",
                "ready" if cover_path else "pending",
            ),
        )
        connection.execute(
            """
            INSERT INTO publish_packages (
                project_slug, draft_version, assets_version, version, abstract, tags,
                publish_checklist, editor_note, publish_title, publish_lead, intro_options,
                markdown_path, markdown_url, manifest_path, manifest_url, status,
                review_comment, reviewed_by, reviewed_at, created_at, origin,
                wechat_mp_draft_status, wechat_mp_draft_id, wechat_mp_draft_error,
                wechat_mp_draft_published_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                1,
                1,
                1,
                "测试摘要",
                "[]",
                "[]",
                "测试备注",
                "测试草稿标题",
                "测试发布导语",
                "[]",
                str(markdown_path or ""),
                "/generated-assets/test-package.md" if markdown_path else "",
                "",
                "",
                package_status,
                "审核通过" if package_status == "approved" else None,
                "editor" if package_status == "approved" else None,
                "2026-08-26T00:00:00+00:00" if package_status == "approved" else None,
                "2026-08-26T00:00:00+00:00",
                "test",
                draft_status,
                None,
                None,
                None,
            ),
        )
        connection.commit()


def _wait_for_api_background_task(task_id: str, timeout_seconds: float = 5.0) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    last_payload: dict[str, object] | None = None
    while time.time() < deadline:
        response = api_client.get(f"/api/background-tasks/{task_id}")
        assert response.status_code == 200
        last_payload = response.json()
        if last_payload["status"] in {"done", "failed"}:
            return last_payload
        time.sleep(0.02)
    raise AssertionError(f"background task {task_id} did not finish: {last_payload}")


def test_publish_uploads_cover_and_writes_draft_without_leaking_session_values(tmp_path: Path) -> None:
    markdown_path = tmp_path / "article.md"
    cover_path = tmp_path / "cover.jpg"
    markdown_path.write_text("# 标题\n\n正文 **重点**。\n", encoding="utf-8")
    cover_path.write_bytes(b"fake-image")
    client = FakeWechatClient()

    result = WechatMpDraftPublisher(client).publish(
        title="标题",
        digest="摘要",
        author="作者",
        markdown_path=markdown_path,
        cover_image_path=cover_path,
    )

    assert result.draft_id == "draft-123"
    assert result.thumb_media_id == "cover-file-id"
    assert "<h1" not in result.content_html
    assert '<p style="' in result.content_html
    assert '<strong style="' in result.content_html
    assert len(client.calls) == 2
    upload_call, draft_call = client.calls
    assert upload_call["endpoint"].endswith("/cgi-bin/filetransfer")
    assert upload_call["files"]["file"][0] == "cover.jpg"
    assert draft_call["endpoint"].endswith("/cgi-bin/operate_appmsg")
    assert draft_call["query"]["t"] == "ajax-response"
    assert draft_call["query"]["sub"] == "create"
    assert draft_call["query"]["type"] == "10"
    assert draft_call["data"]["ajax"] == "1"
    assert draft_call["data"]["fileid0"] == "cover-file-id"
    assert draft_call["data"]["content_noencode"] == result.content_html
    serialized_calls = repr(client.calls)
    assert "Cookie" not in serialized_calls
    assert "token" not in serialized_calls


def test_publish_converts_local_body_images_to_wechat_urls(tmp_path: Path) -> None:
    markdown_path = tmp_path / "article.md"
    cover_path = tmp_path / "cover.jpg"
    body_image_path = tmp_path / "body.png"
    markdown_path.write_text("正文\n\n![配图](body.png)\n", encoding="utf-8")
    cover_path.write_bytes(b"fake-cover")
    body_image_path.write_bytes(b"fake-body")
    client = FakeWechatClient()

    result = WechatMpDraftPublisher(client).publish(
        title="标题",
        digest="摘要",
        author="",
        markdown_path=markdown_path,
        cover_image_path=cover_path,
    )

    assert '<img src="https://mmbiz.qpic.cn/body-image" alt="配图" style="' in result.content_html
    assert [call["query"].get("scene") for call in client.calls] == ["2", "8", None]


def test_publish_marks_expired_session_on_backend_login_error(tmp_path: Path) -> None:
    class ExpiredClient(FakeWechatClient):
        def _request_authenticated_response(self, **kwargs):
            return httpx.Response(200, json={"base_resp": {"ret": 200003, "err_msg": "invalid session"}})

    markdown_path = tmp_path / "article.md"
    cover_path = tmp_path / "cover.jpg"
    markdown_path.write_text("# 标题\n\n正文。\n", encoding="utf-8")
    cover_path.write_bytes(b"fake-cover")
    client = ExpiredClient()

    try:
        WechatMpDraftPublisher(client).publish(
            title="标题",
            digest="",
            author="",
            markdown_path=markdown_path,
            cover_image_path=cover_path,
        )
    except WechatMpDraftPublishError as exc:
        assert str(exc) == "公众号登录已过期，请重新扫码登录"
    else:
        raise AssertionError("expected expired session error")
    assert client.expired is True


def test_workbench_persists_successful_draft_state_without_session_credentials(tmp_path: Path, monkeypatch) -> None:
    markdown_path = tmp_path / "package.md"
    cover_path = tmp_path / "cover.jpg"
    markdown_path.write_text("# 标题\n\n正文。\n", encoding="utf-8")
    cover_path.write_bytes(b"fake-cover")

    with workbench._get_connection() as connection:
        connection.execute(
            "INSERT INTO projects (slug, topic_slug, title, stage, owner) VALUES (?, ?, ?, ?, ?)",
            ("project-1", "topic-1", "项目标题", "published", "owner"),
        )
        connection.execute(
            """
            INSERT INTO assets (
                project_slug, draft_version, version, title_options, recommended_title,
                cover_prompt, cover_copy, social_teaser, social_teaser_options,
                cover_image_path, cover_image_url, cover_image_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("project-1", 1, 1, '["标题"]', "标题", "prompt", "copy", "teaser", "[]", str(cover_path), "/cover.jpg", "ready"),
        )
        connection.execute(
            """
            INSERT INTO publish_packages (
                project_slug, draft_version, assets_version, version, abstract, tags,
                publish_checklist, editor_note, publish_title, publish_lead, intro_options,
                markdown_path, markdown_url, manifest_path, manifest_url, status,
                reviewed_by, reviewed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "project-1", 1, 1, 1, "摘要", "[]", "[]", "note", "标题", "导语", "[]",
                str(markdown_path), "/package.md", str(tmp_path / "manifest.json"), "/manifest.json",
                "approved", "reviewer", "2026-08-09T00:00:00+00:00",
            ),
        )
        connection.commit()

    class FakePublisher:
        def publish(self, **kwargs):
            assert kwargs["markdown_path"] == markdown_path
            assert kwargs["cover_image_path"] == cover_path
            return WechatMpDraftPublishResult(
                draft_id="draft-123",
                thumb_media_id="cover-id",
                content_html="<h1>标题</h1><p>正文。</p>",
            )

    monkeypatch.setattr(workbench, "get_wechat_mp_draft_publisher", lambda: FakePublisher())
    result = workbench.publish_wechat_mp_draft("project-1")

    assert result.wechat_mp_draft_status == "published"
    assert result.wechat_mp_draft_id == "draft-123"
    assert result.wechat_mp_draft_error is None
    with workbench._get_connection() as connection:
        row = connection.execute(
            "SELECT wechat_mp_draft_status, wechat_mp_draft_id, wechat_mp_draft_error FROM publish_packages WHERE project_slug = ?",
            ("project-1",),
        ).fetchone()
    assert dict(row) == {
        "wechat_mp_draft_status": "published",
        "wechat_mp_draft_id": "draft-123",
        "wechat_mp_draft_error": None,
    }


def test_background_task_dispatches_wechat_draft_job(monkeypatch) -> None:
    task_id = "background-wechat-draft-test"
    with workbench._get_connection() as connection:
        connection.execute(
            "INSERT INTO background_tasks (task_id, job_type, status, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                task_id,
                "publish_wechat_mp_draft",
                "queued",
                json.dumps({"project_slug": "project-1"}),
                "2026-08-26T00:00:00+00:00",
            ),
        )
        connection.commit()

    monkeypatch.setattr(
        workbench,
        "publish_wechat_mp_draft",
        lambda project_slug: SimpleNamespace(model_dump=lambda: {"project_slug": project_slug, "status": "approved"}),
    )

    workbench._run_background_task(task_id)

    with workbench._get_connection() as connection:
        row = connection.execute(
            "SELECT status, result, error FROM background_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    assert row["status"] == "done"
    assert json.loads(row["result"]) == {"project_slug": "project-1", "status": "approved"}
    assert row["error"] is None


def test_publish_package_schema_migrates_draft_box_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-publish-packages.db"
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE publish_packages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_slug TEXT NOT NULL,
                draft_version INTEGER NOT NULL,
                assets_version INTEGER NOT NULL,
                version INTEGER NOT NULL,
                abstract TEXT NOT NULL,
                tags TEXT NOT NULL,
                publish_checklist TEXT NOT NULL,
                editor_note TEXT NOT NULL,
                markdown_path TEXT NOT NULL,
                markdown_url TEXT NOT NULL,
                manifest_path TEXT NOT NULL,
                manifest_url TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO publish_packages (
                project_slug, draft_version, assets_version, version, abstract, tags,
                publish_checklist, editor_note, markdown_path, markdown_url,
                manifest_path, manifest_url, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("legacy-project", 1, 1, 1, "摘要", "[]", "[]", "", "article.md", "", "", "", "ready"),
        )

        workbench._ensure_publish_packages_schema(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(publish_packages)").fetchall()}
        row = connection.execute(
            """
            SELECT wechat_mp_draft_status, wechat_mp_draft_id,
                   wechat_mp_draft_error, wechat_mp_draft_published_at
            FROM publish_packages
            """
        ).fetchone()

    assert {
        "wechat_mp_draft_status",
        "wechat_mp_draft_id",
        "wechat_mp_draft_error",
        "wechat_mp_draft_published_at",
    }.issubset(columns)
    assert tuple(row) == ("not_published", None, None, None)


def test_publish_wechat_draft_api_keeps_unapproved_package_out_of_draft_box() -> None:
    project_slug = "api-unapproved-wechat-draft-project"
    _seed_publish_package(project_slug, package_status="ready")

    response = api_client.post(f"/api/projects/{project_slug}/publish-wechat-draft/background")
    assert response.status_code == 202

    task = _wait_for_api_background_task(response.json()["task_id"])
    assert task["status"] == "failed"
    assert "Approve the current publish package" in str(task["error"])

    detail = api_client.get(f"/api/projects/{project_slug}")
    assert detail.status_code == 200
    package = detail.json()["publish_package"]
    assert package["status"] == "ready"
    assert package["wechat_mp_draft_status"] == "not_published"
    assert package["wechat_mp_draft_error"] is None


def test_publish_wechat_draft_api_persists_failure_allows_retry_and_blocks_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_slug = "api-wechat-draft-retry-project"
    markdown_path = tmp_path / "article.md"
    cover_path = tmp_path / "cover.jpg"
    markdown_path.write_text("# 测试草稿标题\n\n正文内容。", encoding="utf-8")
    cover_path.write_bytes(b"cover")
    _seed_publish_package(
        project_slug,
        markdown_path=markdown_path,
        cover_path=cover_path,
    )

    class FailingPublisher:
        def publish(self, **kwargs):
            raise WechatMpDraftPublishError("公众号登录已过期，请重新扫码登录")

    monkeypatch.setattr(workbench, "get_wechat_mp_draft_publisher", lambda: FailingPublisher())
    first_response = api_client.post(f"/api/projects/{project_slug}/publish-wechat-draft/background")
    assert first_response.status_code == 202
    first_task = _wait_for_api_background_task(first_response.json()["task_id"])
    assert first_task["status"] == "failed"
    assert first_task["error"] == "公众号登录已过期，请重新扫码登录"

    failed_detail = api_client.get(f"/api/projects/{project_slug}")
    assert failed_detail.status_code == 200
    failed_package = failed_detail.json()["publish_package"]
    assert failed_package["wechat_mp_draft_status"] == "failed"
    assert failed_package["wechat_mp_draft_error"] == "公众号登录已过期，请重新扫码登录"

    class SuccessfulPublisher:
        def publish(self, **kwargs):
            return WechatMpDraftPublishResult(
                draft_id="draft-api-123",
                thumb_media_id="cover-api-123",
                content_html="<h1>测试草稿标题</h1><p>正文内容。</p>",
            )

    monkeypatch.setattr(workbench, "get_wechat_mp_draft_publisher", lambda: SuccessfulPublisher())
    retry_response = api_client.post(f"/api/projects/{project_slug}/publish-wechat-draft/background")
    assert retry_response.status_code == 202
    retry_task = _wait_for_api_background_task(retry_response.json()["task_id"])
    assert retry_task["status"] == "done"
    assert retry_task["result"]["wechat_mp_draft_status"] == "published"

    published_detail = api_client.get(f"/api/projects/{project_slug}")
    assert published_detail.status_code == 200
    published_package = published_detail.json()["publish_package"]
    assert published_package["wechat_mp_draft_status"] == "published"
    assert published_package["wechat_mp_draft_id"] == "draft-api-123"
    assert published_package["wechat_mp_draft_error"] is None
    assert published_package["wechat_mp_draft_published_at"]

    duplicate_response = api_client.post(f"/api/projects/{project_slug}/publish-wechat-draft/background")
    assert duplicate_response.status_code == 202
    duplicate_task = _wait_for_api_background_task(duplicate_response.json()["task_id"])
    assert duplicate_task["status"] == "failed"
    assert "请勿重复提交" in str(duplicate_task["error"])

    unchanged_detail = api_client.get(f"/api/projects/{project_slug}")
    assert unchanged_detail.status_code == 200
    unchanged_package = unchanged_detail.json()["publish_package"]
    assert unchanged_package["wechat_mp_draft_status"] == "published"
    assert unchanged_package["wechat_mp_draft_id"] == "draft-api-123"


def test_publish_wechat_draft_does_not_call_publisher_while_claim_is_in_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_slug = "wechat-draft-publishing-lock-project"
    markdown_path = tmp_path / "article.md"
    cover_path = tmp_path / "cover.jpg"
    markdown_path.write_text("# 测试草稿标题\n\n正文内容。", encoding="utf-8")
    cover_path.write_bytes(b"cover")
    _seed_publish_package(
        project_slug,
        draft_status="publishing",
        markdown_path=markdown_path,
        cover_path=cover_path,
    )

    calls = 0

    class Publisher:
        def publish(self, **kwargs):
            nonlocal calls
            calls += 1
            raise AssertionError("publisher should not be called for a claimed package")

    monkeypatch.setattr(workbench, "get_wechat_mp_draft_publisher", lambda: Publisher())
    with pytest.raises(HTTPException) as excinfo:
        workbench.publish_wechat_mp_draft(project_slug)

    assert excinfo.value.status_code == 409
    assert "being written" in str(excinfo.value.detail)
    assert calls == 0
