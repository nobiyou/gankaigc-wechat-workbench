from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import json
import re
import sqlite3
import threading
import time
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import openai
import pytest

from app.main import app
from app.schemas.tracked_articles import TrackedArticleCreate
from app.services import workbench


client = TestClient(app)


def wait_for_background_task(task_id: str, timeout_seconds: float = 5.0) -> dict[str, object]:
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


def test_healthcheck() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_vite_dev_server_origin() -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_get_connection_sets_sqlite_busy_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(workbench, "DB_PATH", tmp_path / "busy-timeout.db")

    with workbench._get_connection() as connection:
        busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

    assert busy_timeout == 30000


def test_assets_schema_migration_marks_legacy_blank_covers_pending(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy-assets.db"
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute(
            """
            CREATE TABLE assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_slug TEXT NOT NULL,
                draft_version INTEGER NOT NULL,
                version INTEGER NOT NULL,
                title_options TEXT NOT NULL,
                cover_prompt TEXT NOT NULL,
                cover_copy TEXT NOT NULL,
                social_teaser TEXT NOT NULL,
                cover_image_path TEXT NOT NULL,
                cover_image_url TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO assets (
                project_slug, draft_version, version, title_options, cover_prompt,
                cover_copy, social_teaser, cover_image_path, cover_image_url
            )
            VALUES (?, 1, 1, '[]', 'prompt', 'copy', 'teaser', ?, ?)
            """,
            [
                ("legacy-pending", "", ""),
                ("legacy-ready", "cover.png", "/generated-assets/cover.png"),
            ],
        )

        workbench._ensure_assets_schema(connection)
        rows = connection.execute(
            "SELECT project_slug, cover_image_status, cover_image_error, cover_image_route_label FROM assets ORDER BY project_slug"
        ).fetchall()

    assert [dict(row) for row in rows] == [
        {
            "project_slug": "legacy-pending",
            "cover_image_status": "pending",
            "cover_image_error": None,
            "cover_image_route_label": None,
        },
        {
            "project_slug": "legacy-ready",
            "cover_image_status": "ready",
            "cover_image_error": None,
            "cover_image_route_label": None,
        },
    ]


def test_cors_allows_localhost_and_loopback_frontend_origins() -> None:
    localhost_response = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert localhost_response.status_code == 200
    assert localhost_response.headers.get("access-control-allow-origin") == "http://localhost:3000"

    loopback_response = client.get("/api/health", headers={"Origin": "http://127.0.0.1:3000"})
    assert loopback_response.status_code == 200
    assert loopback_response.headers.get("access-control-allow-origin") == "http://127.0.0.1:3000"


def test_dashboard_summary_shape() -> None:
    response = client.get("/api/dashboard/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["today_trends"] == 3
    assert payload["pending_topics"] == 2
    assert payload["draft_ready_projects"] == 3
    assert payload["publish_ready_projects"] == 0
    assert payload["tracked_articles_count"] == 0
    assert payload["source_ingestion_runs_count"] == 0
    assert payload["latest_source_ingestion_at"] is None
    assert payload["latest_source_ingestion_kind"] is None
    assert payload["source_freshness_state"] == "missing"
    assert isinstance(payload["recent_tasks"], list)


def test_trends_list_returns_seed_data() -> None:
    response = client.get("/api/trends")
    assert response.status_code == 200
    payload = response.json()

    assert len(payload) == 3
    assert payload[0]["slug"] == "office-burnout-recovery"
    assert payload[0]["status"] == "screening"
    assert payload[0]["source"] == "xiaohongshu"


def test_trends_list_prefers_latest_timestamp_first() -> None:
    older_slug = "trend-order-older"
    newer_slug = "trend-order-newer"

    older_response = client.post(
        "/api/trends",
        json={
            "slug": older_slug,
            "title": "更早的一条热点",
            "source": "manual",
            "heat_score": 50,
            "status": "screening",
            "summary": "旧热点摘要",
            "published_at": "2026-05-28T08:00:00+00:00",
            "fetched_at": "2026-05-28T08:05:00+00:00",
        },
    )
    assert older_response.status_code == 201

    newer_response = client.post(
        "/api/trends",
        json={
            "slug": newer_slug,
            "title": "更新的一条热点",
            "source": "manual",
            "heat_score": 50,
            "status": "screening",
            "summary": "新热点摘要",
            "published_at": "2026-05-28T09:00:00+00:00",
            "fetched_at": "2026-05-28T09:05:00+00:00",
        },
    )
    assert newer_response.status_code == 201

    list_response = client.get("/api/trends")
    assert list_response.status_code == 200
    payload = list_response.json()
    slug_positions = {item["slug"]: index for index, item in enumerate(payload)}
    assert slug_positions[newer_slug] < slug_positions[older_slug]


def test_create_trend_persists_and_updates_dashboard() -> None:
    create_response = client.post(
        "/api/trends",
        json={
            "slug": "midlife-reset-notes",
            "title": "中年关系重启观察",
            "source": "manual",
            "heat_score": 77,
            "status": "screening",
            "link": "https://example.com/midlife-reset-notes",
            "summary": "从一次关系停顿切入，讨论中年关系如何重新启动。",
            "published_at": "2026-05-28T08:30:00+08:00",
            "fetched_at": "2026-05-28T08:45:00+08:00",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["slug"] == "midlife-reset-notes"
    assert created["link"] == "https://example.com/midlife-reset-notes"
    assert created["summary"] == "从一次关系停顿切入，讨论中年关系如何重新启动。"
    assert created["published_at"] == "2026-05-28T08:30:00+08:00"
    assert created["fetched_at"] == "2026-05-28T08:45:00+08:00"

    list_response = client.get("/api/trends")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 4
    assert any(
        item["slug"] == "midlife-reset-notes"
        and item["link"] == "https://example.com/midlife-reset-notes"
        and item["summary"] == "从一次关系停顿切入，讨论中年关系如何重新启动。"
        and item["published_at"] == "2026-05-28T08:30:00+08:00"
        and item["fetched_at"] == "2026-05-28T08:45:00+08:00"
        for item in payload
    )

    dashboard_response = client.get("/api/dashboard/summary")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["today_trends"] == 4


def test_import_trends_supports_multiline_text_defaults_and_per_item_results() -> None:
    response = client.post(
        "/api/trends/import",
        json={
            "raw_text": "\n".join(
                [
                    "关系修复表达顺序 | wechat-search | 88 | screening",
                    "高敏感稳定感恢复",
                    "关系修复表达顺序 | duplicate-source | 66 | selected",
                ]
            )
        },
    )
    assert response.status_code == 201
    payload = response.json()

    assert payload["requested_count"] == 3
    assert payload["created_count"] == 2
    assert payload["skipped_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["run_id"] is not None
    assert [item["status"] for item in payload["results"]] == ["done", "done", "skipped"]
    assert payload["results"][0]["trend"]["slug"] == "trend-1"
    assert payload["results"][0]["trend"]["title"] == "关系修复表达顺序"
    assert payload["results"][0]["trend"]["source"] == "wechat-search"
    assert payload["results"][0]["trend"]["heat_score"] == 88
    assert payload["results"][0]["trend"]["status"] == "screening"
    assert payload["results"][1]["trend"]["slug"] == "trend-2"
    assert payload["results"][1]["trend"]["source"] == "manual-import"
    assert payload["results"][1]["trend"]["heat_score"] == 50
    assert payload["results"][1]["trend"]["status"] == "screening"
    assert payload["results"][2]["trend"] is None
    assert payload["results"][2]["error"] == "Trend title already exists"

    list_response = client.get("/api/trends")
    assert list_response.status_code == 200
    trends = list_response.json()
    assert any(item["slug"] == "trend-1" for item in trends)
    assert any(item["slug"] == "trend-2" for item in trends)


def test_fetch_trends_requires_configured_feed_sources(monkeypatch) -> None:
    monkeypatch.setattr(workbench.settings, "trend_feed_urls", [])

    response = client.post("/api/trends/fetch")
    assert response.status_code == 400
    assert response.json()["detail"] == "No trend feed sources configured"


def test_fetch_trends_imports_new_feed_items_and_skips_existing_titles(monkeypatch) -> None:
    monkeypatch.setattr(workbench.settings, "trend_feed_urls", ["https://example.com/feed.xml"])
    monkeypatch.setattr(workbench.settings, "trend_fetch_max_items_per_feed", 10)
    monkeypatch.setattr(
        workbench,
        "_fetch_trend_feed_xml",
        lambda _source_url: """
        <rss>
          <channel>
            <title>示例热榜</title>
            <item><title>办公室倦怠修复</title><link>https://example.com/1</link></item>
            <item>
              <title>情绪恢复不是拖延</title>
              <link>https://example.com/2</link>
              <description>别急着把自己归类成懒散，很多时候只是情绪电量先见底了。</description>
              <pubDate>Wed, 28 May 2026 08:00:00 +0800</pubDate>
            </item>
          </channel>
        </rss>
        """.encode("utf-8"),
    )

    response = client.post("/api/trends/fetch")
    assert response.status_code == 201
    payload = response.json()
    assert payload["requested_source_count"] == 1
    assert payload["processed_source_count"] == 1
    assert payload["created_count"] == 1
    assert payload["skipped_count"] == 1
    assert payload["failed_count"] == 0
    assert payload["run_id"] is not None
    assert payload["results"][0]["source_label"] == "示例热榜"
    assert payload["results"][0]["fetched_count"] == 2
    assert payload["results"][0]["created_count"] == 1
    assert payload["results"][0]["skipped_count"] == 1

    trends_response = client.get("/api/trends")
    assert trends_response.status_code == 200
    trends = trends_response.json()
    imported = next(item for item in trends if item["title"] == "情绪恢复不是拖延")
    assert imported["source"] == "示例热榜"
    assert imported["link"] == "https://example.com/2"
    assert imported["summary"] == "别急着把自己归类成懒散，很多时候只是情绪电量先见底了。"
    assert imported["published_at"] == "2026-05-28T08:00:00+08:00"
    assert imported["fetched_at"] is not None

    dashboard_response = client.get("/api/dashboard/summary")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["source_ingestion_runs_count"] == 1
    assert dashboard["latest_source_ingestion_kind"] == "trend_fetch"
    assert dashboard["source_freshness_state"] == "fresh"


def test_convert_trend_to_topic_creates_pending_topic() -> None:
    response = client.post(
        "/api/trends/office-burnout-recovery/to-topic",
        json={
            "slug": "office-burnout-recovery-checklist",
            "title": "办公室倦怠后的恢复清单",
            "angle": "恢复节奏",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["trend_slug"] == "office-burnout-recovery"
    assert payload["status"] == "pending"

    topic_list = client.get("/api/topics")
    assert topic_list.status_code == 200
    topics = topic_list.json()
    assert topics[0]["slug"] == "office-burnout-recovery-checklist"


def test_create_manual_topic_enters_topic_queue_with_manual_source() -> None:
    existing_topics = client.get("/api/topics").json()
    matching_count = sum(1 for topic in existing_topics if topic["slug"].startswith("midnight-emotion-repair-manual-"))
    slug = f"midnight-emotion-repair-manual-{matching_count + 1}"

    response = client.post(
        "/api/topics",
        json={
            "slug": slug,
            "title": "深夜情绪回稳，不是忍住，而是先把自己接回来",
            "angle": "原创灵感",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["slug"] == slug
    assert payload["trend_slug"] is None
    assert payload["source_type"] == "manual"
    assert payload["source_ref_slug"] == slug
    assert payload["status"] == "pending"

    topic_list = client.get("/api/topics")
    assert topic_list.status_code == 200
    topics = topic_list.json()
    assert topics[0]["slug"] == slug


def test_manual_topic_projects_use_manual_source_context_for_outline_generation(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {"hook": "从一次深夜情绪回稳切入", "outline_body": "1. 情绪现场\n2. 自我接住\n3. 回到行动"}

    existing_topics = client.get("/api/topics").json()
    matching_count = sum(1 for topic in existing_topics if topic["slug"].startswith("manual-outline-topic-"))
    topic_slug = f"manual-outline-topic-{matching_count + 1}"
    project_slug = f"{topic_slug}-project"

    create_topic_response = client.post(
        "/api/topics",
        json={
            "slug": topic_slug,
            "title": "深夜情绪回稳，不是忍住，而是先把自己接回来",
            "angle": "原创灵感",
        },
    )
    assert create_topic_response.status_code == 201

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    create_project_response = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={
            "slug": project_slug,
            "title": "原创情绪回稳项目",
            "owner": "editorial",
        },
    )
    assert create_project_response.status_code == 201

    outline_response = client.post(f"/api/projects/{project_slug}/generate-outline")
    assert outline_response.status_code == 201
    assert outline_response.json()["hook"] == "从一次深夜情绪回稳切入"

    assert len(fake_generator.calls) == 1
    call_type, call_payload = fake_generator.calls[0]
    assert call_type == "outline"
    assert call_payload["trend_title"] == "原创选题 / 手动录入"
    assert call_payload["topic_title"] == "深夜情绪回稳，不是忍住，而是先把自己接回来"
    assert call_payload["topic_angle"] == "原创灵感"


def test_create_project_from_topic_persists_topic_as_drafting() -> None:
    existing_topics = client.get("/api/topics").json()
    matching_count = sum(1 for topic in existing_topics if topic["slug"].startswith("manual-project-state-topic-"))
    topic_slug = f"manual-project-state-topic-{matching_count + 1}"
    project_slug = f"{topic_slug}-project"

    create_topic_response = client.post(
        "/api/topics",
        json={
            "slug": topic_slug,
            "title": "先把夜班情绪接住，再决定明天怎么推进",
            "angle": "原创灵感",
        },
    )
    assert create_topic_response.status_code == 201

    create_project_response = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={
            "slug": project_slug,
            "title": "夜班情绪接住测试项目",
            "owner": "editorial",
        },
    )
    assert create_project_response.status_code == 201
    created_project = create_project_response.json()
    assert created_project["topic_slug"] == topic_slug

    topics_response = client.get("/api/topics")
    assert topics_response.status_code == 200
    topics = topics_response.json()
    created_topic = next(topic for topic in topics if topic["slug"] == topic_slug)
    assert created_topic["status"] == "drafting"


def test_generate_topic_from_trend_uses_ai_and_persists(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "办公室倦怠不是懒，是你的身心在报警",
                "angle": "情绪识别",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/trends/office-burnout-recovery/generate-topic")
    assert response.status_code == 201
    payload = response.json()
    assert payload["trend_slug"] == "office-burnout-recovery"
    assert payload["title"] == "办公室倦怠不是懒，是你的身心在报警"
    assert payload["angle"] == "情绪识别"
    assert payload["status"] == "pending"
    assert payload["slug"] == "office-burnout-recovery-ai-topic-1"

    topics_response = client.get("/api/topics")
    assert topics_response.status_code == 200
    topics = topics_response.json()
    assert topics[0]["slug"] == "office-burnout-recovery-ai-topic-1"
    assert len(fake_generator.calls) == 1
    call_type, call_payload = fake_generator.calls[0]
    assert call_type == "topic"
    assert call_payload["trend_slug"] == "office-burnout-recovery"
    assert call_payload["trend_title"] == "办公室倦怠修复"
    assert call_payload["source"] == "xiaohongshu"
    assert call_payload["heat_score"] == 92
    assert call_payload["status"] == "screening"
    assert call_payload["tone_profile"]["name"] == "女性成长克制陪伴风"
    assert "直接问题、现实接口或判断切入" in call_payload["tone_profile"]["opening_style"]
    assert "不用生活场景冷启动" in call_payload["tone_profile"]["opening_style"]
    assert "不靠整段场景铺陈" in call_payload["tone_profile"]["paragraph_rhythm"]
    assert call_payload["tone_profile"]["closing_style"] == "明确结论或行动落点收束"
    assert call_payload["tone_profile"]["forbidden_phrases"] == ["你必须", "立刻改变"]
    assert "具体、克制、有承接" in call_payload["tone_profile"]["value_constraints"]
    assert call_payload["tone_profile"]["target_word_count"] == 1400


def test_generate_topic_from_tracked_article_uses_ai_and_persists(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "比解释更重要的，是先接住关系里的那一下失望",
                "angle": "修复顺序",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "slow-repair-template",
            "source_name": "夜读关系实验室",
            "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "url": "https://example.com/slow-repair-template",
            "author": "北岛",
            "summary": "从关系修复案例提炼表达顺序。",
            "body_markdown": "她那天没有继续解释，只是先停下来接住那一下失望。\n\n第二天才重新整理要说的话。",
            "structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "tags": ["表达修复", "关系修复"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/slow-repair-template/generate-topic")
    assert response.status_code == 201
    payload = response.json()
    assert payload["source_type"] == "tracked_article"
    assert payload["source_ref_slug"] == "slow-repair-template"
    assert payload["title"] == "比解释更重要的，是先接住关系里的那一下失望"
    assert payload["angle"] == "修复顺序"
    assert payload["slug"] == "slow-repair-template-ai-topic-1"

    topics_response = client.get("/api/topics")
    assert topics_response.status_code == 200
    topics = topics_response.json()
    assert topics[0]["slug"] == "slow-repair-template-ai-topic-1"
    assert len(fake_generator.calls) == 1
    call_type, call_payload = fake_generator.calls[0]
    assert call_type == "topic"
    assert call_payload["source_type"] == "tracked_article"
    assert call_payload["source_ref_slug"] == "slow-repair-template"
    assert call_payload["source_name"] == "夜读关系实验室"
    assert call_payload["article_title"] == "真正让关系缓回来，不是解释，是先接住那一下失望"
    assert call_payload["author"] == "北岛"
    assert call_payload["summary"] == "从关系修复案例提炼表达顺序。"
    assert call_payload["body_markdown"] == "她那天没有继续解释，只是先停下来接住那一下失望。\n\n第二天才重新整理要说的话。"
    assert call_payload["structure_notes"] == "案例开头 + 情绪拆解 + 动作建议。"
    assert call_payload["tags"] == ["表达修复", "关系修复"]


def test_generate_topic_from_tracked_article_auto_enriches_analysis_before_topic(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("tracked_article_metadata", payload))
            return {
                "author": "北岛",
                "summary": "从关系修复案例提炼表达顺序。",
                "structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
                "analysis_theme": "关系修复里，先接住失望比立刻解释更重要。",
                "analysis_core_conflict": "双方都想说明白时，最容易漏掉当下需要被安顿的情绪。",
                "analysis_emotional_exit": "把关系从对错争执里带回能继续开口的位置。",
                "analysis_structure_mode": "relationship_aftercare",
                "analysis_opening_pattern": "从一次没继续解释的现场起笔。",
                "analysis_do_not_turn_into": "不要写成泛沟通技巧或谁输谁赢的辩论稿。",
                "tags": ["表达修复", "关系修复"],
            }

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "比解释更重要的，是先接住关系里的那一下失望",
                "angle": "修复顺序",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "slow-repair-auto-analyze",
            "source_name": "夜读关系实验室",
            "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "url": "https://example.com/slow-repair-auto-analyze",
            "author": "北岛",
            "summary": "从关系修复案例提炼表达顺序。",
            "body_markdown": "她那天没有继续解释，只是先停下来接住那一下失望。\n\n第二天才重新整理要说的话。",
            "structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "tags": ["表达修复", "关系修复"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/slow-repair-auto-analyze/generate-topic")
    assert response.status_code == 201

    assert [call[0] for call in fake_generator.calls] == ["tracked_article_metadata", "topic"]
    topic_payload = fake_generator.calls[1][1]
    assert topic_payload["analysis_theme"] == "关系修复里，先接住失望比立刻解释更重要。"
    assert topic_payload["analysis_core_conflict"] == "双方都想说明白时，最容易漏掉当下需要被安顿的情绪。"
    assert topic_payload["analysis_emotional_exit"] == "把关系从对错争执里带回能继续开口的位置。"
    assert topic_payload["analysis_structure_mode"] == "relationship_aftercare"
    assert topic_payload["analysis_opening_pattern"] == "从一次没继续解释的现场起笔。"
    assert topic_payload["analysis_do_not_turn_into"] == "不要写成泛沟通技巧或谁输谁赢的辩论稿。"

    tracked_article = next(
        article for article in client.get("/api/tracked-articles").json() if article["slug"] == "slow-repair-auto-analyze"
    )
    assert tracked_article["analysis_theme"] == "关系修复里，先接住失望比立刻解释更重要。"
    assert tracked_article["analysis_structure_mode"] == "relationship_aftercare"


def test_generate_topic_from_tracked_article_falls_back_when_auto_enrich_times_out(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("tracked_article_metadata", payload))
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/chat/completions"))

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "真正让关系缓回来的是，先把那一下失望安顿好",
                "angle": "关系修复",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "slow-repair-enrich-timeout",
            "source_name": "夜读关系实验室",
            "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "url": "https://example.com/slow-repair-enrich-timeout",
            "author": "北岛",
            "summary": "从关系修复案例提炼表达顺序。",
            "body_markdown": "她那天没有继续解释，只是先停下来接住那一下失望。\n\n第二天才重新整理要说的话。",
            "structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "tags": ["表达修复", "关系修复"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    response = client.post("/api/tracked-articles/slow-repair-enrich-timeout/generate-topic")
    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "真正让关系缓回来的是，先把那一下失望安顿好"
    assert payload["angle"] == "关系修复"

    assert [call[0] for call in fake_generator.calls] == ["tracked_article_metadata", "topic"]
    topic_payload = fake_generator.calls[1][1]
    assert topic_payload["source_ref_slug"] == "slow-repair-enrich-timeout"
    assert topic_payload["summary"] == "从关系修复案例提炼表达顺序。"
    assert topic_payload["structure_notes"] == "案例开头 + 情绪拆解 + 动作建议。"
    assert topic_payload["analysis_theme"] == ""
    assert topic_payload["analysis_core_conflict"] == ""
    assert topic_payload["analysis_structure_mode"] in {"", "emotional_engine_direct"}


def test_generate_topic_from_tracked_article_surfaces_upstream_failure_when_topic_generation_times_out(monkeypatch) -> None:
    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/chat/completions"))

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "responsibility-shelter-topic-fallback",
            "source_name": "手动录入",
            "title": "中年人的那句我没事，背后都是责任",
            "url": "https://example.com/responsibility-shelter-topic-fallback",
            "author": "未知",
            "summary": "文章借成年人常说的“我没事”，写父母养老、孩子缴费、家里开销和伴侣依靠一起压上来时，很多人怎样先把自己往后放。重点不在歌颂吃苦，而在说明很多硬撑后来真的会变成一家人的安稳。",
            "body_markdown": (
                "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
                "生病了不敢请假，怕影响这个月的绩效；委屈了不敢辞职，因为你要撑起一个家的重量。\n\n"
                "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；慢慢长大的孩子，拥有了对生活说“不”的底气；深深爱着的伴侣，也能在风雨来临时有一处温暖的屋檐庇护。"
            ),
            "structure_notes": "先从一句“没事，有我”和电话账单这些现实重量切入，中段写责任怎样让人把自己往后收，结尾落回家里安稳和这些辛苦没有白熬。",
            "tags": ["责任托家", "中年压力", "家庭安稳"],
        },
    )

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    response = client.post("/api/tracked-articles/responsibility-shelter-topic-fallback/generate-topic")
    assert response.status_code == 503
    payload = response.json()

    assert payload["detail"].startswith("选题生成失败：当前文本 AI 服务暂时不可用，请稍后重试。")
    assert "当前已关闭本地兜底，避免写成退化稿。" in payload["detail"]


def test_generate_topic_from_tracked_article_rewrites_abstract_internal_pressure_angle_with_body_cues(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总把自己排到最后的人，迟早要为失序的生活付账",
                "angle": "从“总能再撑一下”的自我调度入手，拆开很多女性怎样在工作、家人和体面之间持续撤掉自我照料，直到身体和情绪一起追债。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "pressure-chain-notes",
            "source_name": "手动录入",
            "title": "善待自己，好好爱自己",
            "url": "https://example.com/pressure-chain-notes",
            "author": "未知",
            "summary": "文章重点是人生遗憾、内耗、自我照料缺位和身体代价，不是关系修复。",
            "body_markdown": (
                "后来得了尿毒症，又开始怀念当初长褥疮的时候。\n\n"
                "又过了一些年，要透析，清醒的时间很少，便又开始怀念起刚得尿毒症的时候。"
            ),
            "structure_notes": "从遗憾反思和内耗进入，再落到身体代价、自我照料和生活排序。",
            "tags": ["自我关照", "人生遗憾", "自我照料", "生活排序"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/pressure-chain-notes/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "从尿毒症到透析，身体到底替你扛了多少"
    assert "尿毒症" in payload["angle"]
    assert "透析" in payload["angle"]
    assert "求救信号" in payload["angle"]
    assert "不先抛人生答案" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_internal_pressure_angle_even_with_relationship_noise_tags(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "身体先发出的那些钝感，往往不是累一阵就会过去",
                "angle": "从很多女性在关系、工作和体面之间不断撤掉自我照料写起，解释身体和情绪为什么会一起追债。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "pressure-chain-noisy-tags",
            "source_name": "手动录入",
            "title": "总把自己放最后的人，身体会替你记账",
            "url": "https://example.com/pressure-chain-noisy-tags",
            "author": "未知",
            "summary": "文章重点是内耗、身体代价和生活排序失衡，不在亲密关系沟通里打转，也不要写成冷战复合流程。",
            "body_markdown": (
                "她先把体检往后改，又把回家吃饭这件事往后推。\n\n"
                "后来整个人越来越钝，连一句解释都懒得说。"
            ),
            "structure_notes": "从日常顺延和身体变钝切入，再落到自我照料缺位。",
            "tags": ["身体提醒", "关系修复", "生活排序"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/pressure-chain-noisy-tags/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "身体先发出的那些钝感，往往不是累一阵就会过去"
    assert "体检" in payload["angle"] or "回家吃饭" in payload["angle"] or "越来越钝" in payload["angle"]
    assert "不先抛人生答案" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_abstract_internal_pressure_title_with_daily_interface(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总把自己放最后的人，生活为什么会慢慢失序",
                "angle": "从很多人总把自己往后放这件事切入，解释生活排序为什么总会越来越乱。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "pressure-daily-interface-title",
            "source_name": "手动录入",
            "title": "别再把自己往后拖",
            "url": "https://example.com/pressure-daily-interface-title",
            "author": "未知",
            "summary": "文章重点是身体代价和生活排序，不是关系修复。",
            "body_markdown": (
                "她先把体检往后改，又把回家吃饭这件事往后推。\n\n"
                "后来整个人越来越钝，连一句解释都懒得说。"
            ),
            "structure_notes": "从顺延动作和身体变钝切入，再落到自我照料缺位。",
            "tags": ["身体提醒", "生活排序"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/pressure-daily-interface-title/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "那次体检被你改到第几回了"
    assert "体检" in payload["angle"] or "回家吃饭" in payload["angle"] or "越来越钝" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_abstract_internal_pressure_title_to_review_sheet_interface(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总把休息和复查排在最后的人，最后会怀念那个“只是有点累”的自己",
                "angle": "从人总把自己的求救信号压后这件事切入，解释为什么很多人会一路拖到更重的代价。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "pressure-review-sheet-title",
            "source_name": "手动录入",
            "title": "善待自己，好好爱自己",
            "url": "https://example.com/pressure-review-sheet-title",
            "author": "未知",
            "summary": "文章重点是自我照料缺位和身体代价，不是人生感悟空话。",
            "body_markdown": (
                "复查提醒弹出来，你顺手划掉。\n\n"
                "那句“建议复查”没有消失，只是又被往后放了一次。"
            ),
            "structure_notes": "从复查提醒和延后动作切入，再落到身体代价。",
            "tags": ["身体提醒", "自我照料"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/pressure-review-sheet-title/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "那张“建议复查”的单子，被你压了多久"
    assert "求救信号" in payload["angle"]


def test_generate_topic_from_tracked_article_does_not_force_happiness_release_article_into_pressure_interface(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "人这一生，最难得的幸福，其实是不再强求",
                "angle": "从关系和目标里那些迟迟放不下的不甘心切入，写人为什么总把幸福误解成不断得到，而忘了珍惜已经拥有的部分。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "happiness-release-notes",
            "source_name": "手动录入",
            "title": "幸福是什么",
            "url": "https://example.com/happiness-release-notes",
            "author": "未知",
            "summary": "文章把幸福的定义从“不断获得”转向“适时放下”，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。核心判断是，幸福未必来自追到更多，而更可能来自停止拉扯、看见眼前已经拥有的部分。",
            "body_markdown": (
                "幸福是什么？我们总以为，幸福是“得到”：得到爱，得到钱，得到想要的一切。后来才懂，幸福其实是“放下”：放下强求，放下执念，放下那些得不到的东西。\n\n"
                "别再盯着自己没有的东西了，转过头，看看你拥有的。你无忧、无虑、无病、无灾，你有健康的身体，爱你的家人，三两好友，一碗热饭。\n\n"
                "愿你学会“不再强求”的放下，也学会“别无所求”的知足。"
            ),
            "structure_notes": "开头用“幸福是得到还是放下”的反差提问切入，再列举关系、目标和不甘心三种常见执拗场景，建立共鸣。中段把重点转到“强求只会消耗自己”，进一步提出把注意力从得不到的东西移回已拥有的现实支持。结尾回收到“放手不是失去，而是腾出位置”，用珍惜当下和知足作收束。",
            "tags": ["幸福认知", "停止强求", "关系执念", "自我消耗", "珍惜当下"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/happiness-release-notes/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "幸福" in payload["title"] or "放下" in payload["title"]
    assert "体检" not in payload["title"]
    assert "复查" not in payload["title"]
    assert "坏关系" not in payload["title"]
    assert "体检" not in payload["angle"]
    assert "复查" not in payload["angle"]
    assert "沉没成本" not in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_happiness_release_article_out_of_relationship_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "你迟迟离不开一段坏关系，往往输给了“已经付出这么多”",
                "angle": "很多关系拖到最后，卡住人的并不是爱得太深，而是投入太久后的舍不得；这篇稿子要拆开“不甘心”怎样把人留在坏关系里，以及及时止损为什么是一种自我保护。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "happiness-release-reroute",
            "source_name": "手动录入",
            "title": "幸福是什么",
            "url": "https://example.com/happiness-release-reroute",
            "author": "未知",
            "summary": "文章把幸福的定义从“不断获得”转向“适时放下”，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。核心判断是，幸福未必来自追到更多，而更可能来自停止拉扯、看见眼前已经拥有的部分。",
            "body_markdown": (
                "幸福是什么？我们总以为，幸福是“得到”：得到爱，得到钱，得到想要的一切。后来才懂，幸福其实是“放下”：放下强求，放下执念，放下那些得不到的东西。\n\n"
                "你有没有过这样的时刻？明明一段关系已经烂了，你还死死抓着不放，安慰自己“再坚持一下就好了”；明明一个目标根本不合适你，你还拼命往前冲，骗自己“只要够努力就能成功”；把自己困在“不甘心”的牢笼里，一遍遍问：“为什么我付出了，却得不到？”\n\n"
                "可真正的幸福，恰恰是该结束的时候，不再强求，该珍惜的时候，别无所求。\n\n"
                "亲爱的，该放手的，就放手，那不是失去，是腾出位置。"
            ),
            "structure_notes": "开头用“幸福是得到还是放下”的反差提问切入，再列举关系、目标和不甘心三种常见执拗场景，建立共鸣。中段把重点转到“强求只会消耗自己”，结尾回收到“放手不是失去，而是腾出位置”。",
            "tags": ["幸福认知", "停止强求", "关系执念", "珍惜当下"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/happiness-release-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "坏关系" not in payload["title"]
    assert "沉没成本" not in payload["title"]
    assert "幸福" in payload["title"] or "放下" in payload["title"]
    assert "坏关系" not in payload["angle"]
    assert "沉没成本" not in payload["angle"]
    assert "放手" in payload["angle"] or "不再强求" in payload["angle"] or "已经拥有" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_memory_reflux_phrase_out_of_emotional_release_topic(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总会冒出“要是他还在就好了”的人，心里卡着一段没被收尾的关系",
                "angle": "从“要是他还在就好了”这句反复冒头的心声切入，拆开关系为何会在多年后仍回潮：真正挂住人的，常是没说完的话、没兑现的承诺和没被接住的自己。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "memory-reflux-reroute",
            "source_name": "手动录入",
            "title": "遗忘再长，也长不过明天和以后",
            "url": "https://example.com/memory-reflux-reroute",
            "author": "未知",
            "summary": "文章围绕过去不会自动沉下去展开，重点不是复合，而是没收尾的关系为什么会在日常缝隙里反复回潮。",
            "body_markdown": (
                "又有多少个心绪翻涌的当下，你低眉叹息，因一点不起眼的小事，而不由自主地感慨，要是他还在就好了。\n\n"
                "有些情有些人，却只适合收藏。过去再美好，也终究是过去了。\n\n"
                "毕竟人生海海，缘分最奇妙的地方就在于，当你离一个人远去，也就意味着你离另一段际遇越来越近了。"
            ),
            "structure_notes": "先从旧事会回潮的判断切入，中段拆未完成关系如何反复触发想念，结尾回到带着遗憾往前走。",
            "tags": ["旧关系", "回忆回潮", "未完成"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/memory-reflux-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "要是他还在就好了" not in payload["title"]
    assert "要是他还在就好了" not in payload["angle"]
    assert "回潮" in payload["title"]
    assert "旧关系" in payload["title"] or "没收好" in payload["title"]
    assert "背影" in payload["angle"] or "聊天记录" in payload["angle"]
    assert "没被接住" in payload["angle"] or "不再拿今天去补昨天" in payload["angle"]


def test_apply_tracked_article_topic_rewrites_emotional_memory_reflux_reroutes_generic_acceptance_result() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "遗忘再长，也长不过明天和以后",
        "summary": "文章写旧关系并不会自动沉底，背影、旧相册和聊天记录会让往事在普通时刻反复回潮。",
        "body_markdown": (
            "可多少次灯火阑珊的街头，你久久伫立，因一个擦肩的背影有点像他，而蓦然回想起那年那天那一刻。\n\n"
            "又有多少个心绪翻涌的当下，你低眉叹息，因一点不起眼的小事，而不由自主地感慨，要是他还在就好了。\n\n"
            "可很多时候，他好像依然存在于你的世界里，随处可见，却又让你碰不到摸不着。"
        ),
        "structure_notes": "先从旧事会回潮切入，再拆旧关系为什么在普通时刻反复被想起，结尾回到把这段路安放好。",
        "analysis_structure_mode": "emotional_engine_direct",
    }

    rewritten = workbench._apply_tracked_article_topic_rewrites(
        payload,
        {
            "title": "有些相遇没能走到最后，却会悄悄成全后来的你",
            "angle": "把感谢留下，把成长收回自己身上，新的日子才会慢慢朝你走来。",
        },
    )

    assert rewritten["title"] == "那段旧关系没收好，往事就会在某个普通时刻回潮"
    assert "背影" in rewritten["angle"] or "聊天记录" in rewritten["angle"]
    assert "不再拿今天去补昨天" in rewritten["angle"]


def test_generate_topic_from_tracked_article_rewrites_endings_acceptance_out_of_pressure_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "你迟迟走不出来，往往是在向一段旧关系追讨完整定义",
                "angle": "写关系结束后最耗人的那一层：人反复受困，常常是因为还在替那段付出、温柔和改变追讨一个完整定义。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "endings-acceptance-reroute",
            "source_name": "手动录入",
            "title": "感谢相遇，不谈亏欠",
            "url": "https://example.com/endings-acceptance-reroute",
            "author": "未知",
            "summary": "文章讨论关系结束后如何把失去从亏欠叙事里松开，重点不是劝人立刻忘记，而是接纳离开、保存相遇意义，并把留下来的温暖内化成继续往前的力量。",
            "body_markdown": (
                "成年人的关系，原本就是一段一段的。接纳离开，才是对这段关系最好的祝福。\n\n"
                "真正的成熟，不是变得麻木，而是允许一切发生，也允许一切结束。\n\n"
                "感谢相遇，不谈亏欠。带着这份从容与爱意，整理行囊，去拥抱下一场未知的山海。"
            ),
            "structure_notes": "开头先借引语点出聚散有时，中段拆为什么人会替一段关系追讨完整定义，结尾回到感谢相遇、不谈亏欠和继续前行。",
            "analysis_theme": "这篇文章真正想讨论的是：成年人如何把一段关系的结束，从失去和亏欠的叙事，转化为对相遇意义的接纳与内在消化。",
            "analysis_core_conflict": "真正让人反复受困的，不只是关系结束，而是对必须长久、必须有结果的执念，与关系本就会阶段性结束的现实之间的冲突。",
            "analysis_emotional_exit": "承认离别会疼，但不再把自己困在追问里，而是把关系中留下的温暖内化成继续前行的力量。",
            "analysis_structure_mode": "pressure_interface_direct",
            "analysis_opening_pattern": "以引语起笔，再从年轻时执着永远、后来才懂聚散有时切入主题。",
            "analysis_do_not_turn_into": "不要改写成劝人立刻放下的鸡汤安慰，也不要写成所有离开都值得感恩的强行升华。",
            "tags": ["关系结束", "接纳离开", "不谈亏欠", "感谢相遇"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/endings-acceptance-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "体检" not in payload["title"]
    assert "休息" not in payload["angle"]
    assert any(token in payload["title"] for token in ("关系", "相遇", "成全", "永远", "生命"))
    assert any(token in payload["title"] for token in ("感谢", "成全", "相遇", "现在的你"))
    assert "完整定义" not in payload["title"]
    assert "继续往前" in payload["angle"] or "感谢" in payload["angle"] or "温暖" in payload["angle"]
    assert "白费" in payload["angle"] or "阶段" in payload["angle"] or "成长" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_withdrawn_aftercare_topic_out_of_self_processing_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总在天亮前把自己哄好的人，后来会慢慢失去求助能力",
                "angle": "从“天亮前先把情绪收拾好”这个自我处理动作切入，拆开长期独自消化的人为什么会在关系里越来越少开口，也越来越难相信有人能接住她。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "withdrawn-aftercare-reroute",
            "source_name": "手动录入",
            "title": "你推开我的那一刻，我就学会不再示弱",
            "url": "https://example.com/withdrawn-aftercare-reroute",
            "author": "未知",
            "summary": "文章借“情绪很累却不被理解”的时刻，写亲密关系里最伤人的并不是争吵，而是在脆弱时被嫌烦、被推开。它的判断很明确：一个人不是突然冷下来，而是在多次求助落空后，慢慢学会不再向你袒露软弱。",
            "body_markdown": (
                "有时候，会莫名其妙地觉得累。\n\n"
                "可真正让人寒心的，不是生活本身的压力，而是在求助和示弱时，被最亲近的人嫌烦、推开。\n\n"
                "当你在一个人最无助的时候选择推开他，下一次，他就不会再在你面前脆弱了。"
            ),
            "structure_notes": "开头先从成年人常见的情绪透支感切入，写出表面正常、内里耗尽的状态；中段把这种疲惫放进亲密关系里，转向“对方把脆弱误判成无理取闹”的具体场景；结尾落在一次被推开的后果上，强调失望积累后，人会主动收起依赖和示弱。",
            "tags": ["亲密关系", "脆弱误读", "求助落空", "不再示弱"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/withdrawn-aftercare-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "被推开几次以后，很多人就不再开口了"
    assert "最需要被接住的时候" in payload["angle"]
    assert "谁误解了她" in payload["angle"]
    assert "谁没有接住她" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_everyday_warmth_return_article_out_of_pressure_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "身体一停，才看见谁一直被你排在待办清单最后",
                "angle": "从体检、手术和在家休养这条现实线索切入，拆开成年女性把陪伴和自我照料长期后置的机制，也接住终于停下来的那份内疚。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "small-things-reroute",
            "source_name": "手动录入",
            "title": "一生最重要的事，不是大事",
            "url": "https://example.com/small-things-reroute",
            "author": "未知",
            "summary": "文章把“做大事”的社会期待，与人在身体受挫、生活放慢后重新确认的日常幸福放在一起比较，核心判断是：真正支撑一个人生活感受的，往往不是成就叙事，而是陪伴、相处和被看见的细碎时刻。",
            "body_markdown": (
                "年轻时，我们都想改变世界，觉得人生一定要轰轰烈烈，要做大事，要出人头地。可走过半生，才发现，这世界再喧嚣，最重要的事，不过是活在人间烟火里，陪在爱的人身边。\n\n"
                "朋友是上市公司的高管，前些年，没日没夜地加班，最近因为身体不舒服做了个手术，在家休养。\n\n"
                "他终于在日落之前，陪爱人做了一顿晚饭。他久违地去接孩子放学。那一刻，他突然觉得，那些拼了命追求的大事，好像瞬间祛魅了。\n\n"
                "其实，真正让人眼眶发热的，可能从来不是升职加薪、远大抱负，而是这些不起眼的、细碎的、平淡的日常瞬间。宏大叙事属于时代，属于历史书，而一碗热汤、一盏夜灯、一句晚安，才属于你我。"
            ),
            "structure_notes": "开头先摆出追逐成就的大命题，中段借手术停下来后的家庭陪伴完成价值转向，结尾回到普通日常和陪伴。",
            "tags": ["日常治愈", "家庭陪伴", "价值重估"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/small-things-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "体检" not in payload["title"]
    assert "待办清单最后" not in payload["title"]
    assert "大事" in payload["title"] or "小事" in payload["title"] or "重要" in payload["title"]
    assert "体检" not in payload["angle"]
    assert "复查" not in payload["angle"]
    assert "关系接住" not in payload["angle"]
    assert "等你回应" not in payload["title"]
    assert "托底感" not in payload["title"]
    assert "中年以后" not in payload["title"]
    assert "晚饭" not in payload["angle"]
    assert "接孩子" not in payload["angle"]
    assert "晚安" not in payload["angle"]
    assert "陪伴" in payload["angle"] or "日常" in payload["angle"] or "联系" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_everyday_warmth_return_article_out_of_empty_life_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总把回家往后排的人，为什么更容易突然觉得一切都没意思",
                "angle": "从“总有更重要的事”这套排序切入，拆开成就感退潮后为什么会先出现空心感，以及晚饭、陪伴、晚安如何重新成为一个人的情绪托底。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "small-things-empty-life-reroute",
            "source_name": "手动录入",
            "title": "一生最重要的事，不是大事",
            "url": "https://example.com/small-things-empty-life-reroute",
            "author": "未知",
            "summary": "文章把“做大事”的社会期待，与人在生活放慢后重新确认的日常幸福放在一起比较，重点不是空心感自救，而是成就祛魅之后，小事和陪伴怎样重新显出分量。",
            "body_markdown": (
                "年轻时，我们都想改变世界，觉得人生一定要轰轰烈烈，要做大事，要出人头地。可走过半生，才发现，这世界再喧嚣，最重要的事，不过是活在人间烟火里，陪在爱的人身边。\n\n"
                "朋友是上市公司的高管，前些年，没日没夜地加班，最近因为身体不舒服做了个手术，在家休养。\n\n"
                "他终于在日落之前，陪爱人做了一顿晚饭。他久违地去接孩子放学。那一刻，他突然觉得，那些拼了命追求的大事，好像瞬间祛魅了。\n\n"
                "真正让人眼眶发热的，可能从来不是升职加薪、远大抱负，而是这些不起眼的、细碎的、平淡的日常瞬间。宏大叙事属于时代，而一碗热汤、一盏夜灯、一句晚安，才属于你我。"
            ),
            "structure_notes": "开头先摆出追逐成就的大命题，中段借停下来后的家庭陪伴完成价值转向，结尾回到普通日常和陪伴。",
            "tags": ["日常治愈", "家庭陪伴", "价值重估"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/small-things-empty-life-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "没意思" not in payload["title"]
    assert "往后排" not in payload["title"]
    assert "空心感" not in payload["angle"]
    assert "情绪托底" not in payload["angle"]
    assert "晚饭" not in payload["angle"]
    assert "接孩子" not in payload["angle"]
    assert "晚安" not in payload["angle"]
    assert "大事" in payload["title"] or "小事" in payload["title"] or "人这一生" in payload["title"]
    assert "陪伴" in payload["angle"] or "日常" in payload["angle"] or "联系" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_simple_happiness_article_out_of_emotional_release_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "为什么我们总把好日子放在下一次达成之后",
                "angle": "从人为什么总把幸福误解成继续争取切入，写我们怎样在强求和不甘心里耗尽自己，又怎样在放手后重新看见已经拥有的部分。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "simple-happiness-reroute",
            "source_name": "手动录入",
            "title": "人生不求大富大贵，但求简单快乐",
            "url": "https://example.com/simple-happiness-reroute",
            "author": "未知",
            "summary": "文章借幸福观的变化，讨论人到中年后对人生所求的重新排序：比起钱、排场和热闹，真正托住人的往往是健康、知己、家里的温度。",
            "body_markdown": (
                "人活着，到底是为了什么？人生苦短，只求心情愉悦，家人安康，吃穿不愁，知己二三，四季平安。人生不求大富大贵，但求简单快乐。\n\n"
                "中年后，我们才慢慢发现，幸福其实是一种心态，知足最幸福。\n\n"
                "世间最大的幸福，从来不是你认识多少人，有多大的交际圈，而是能有一个惺惺相惜、同甘共苦的知己。\n\n"
                "开什么车、住什么房子不重要，只要一家人能整整齐齐，平安健康，就比什么都珍贵。"
            ),
            "structure_notes": "开头先用人生发问和朴素愿望起势，中段分到知足、知己和一家温暖，结尾回到名利短暂、平安可贵。",
            "tags": ["幸福观重估", "知足感", "知己关系", "家庭温暖"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/simple-happiness-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "下一次达成" not in payload["title"]
    assert "继续争取" not in payload["angle"]
    assert "放手" not in payload["angle"]
    assert "不是" not in payload["title"]
    assert "大富大贵" not in payload["title"]
    assert "简单快乐" not in payload["title"]
    assert any(token in payload["title"] for token in ("知己", "家", "日子"))
    assert any(token in payload["angle"] for token in ("家人", "知己", "烟火", "踏实"))


def test_generate_topic_from_tracked_article_local_fallback_keeps_simple_happiness_article_out_of_emotional_engine_sink(
    monkeypatch,
) -> None:
    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            raise RuntimeError("forced local topic fallback")

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "simple-happiness-local-fallback",
            "source_name": "手动录入",
            "title": "人生不求大富大贵，但求简单快乐",
            "url": "https://example.com/simple-happiness-local-fallback",
            "author": "未知",
            "summary": "文章主线是幸福不一定在更大的拥有里，常常就在平凡日常和家人知己身边。",
            "body_markdown": (
                "人活着，到底是为了什么？人生苦短，只求心情愉悦，家人安康，吃穿不愁，知己二三，四季平安。\n\n"
                "生活简单就迷人，人心简单就幸福。\n\n"
                "人这一辈子，谁也争不过朝夕，财富、名利、地位不过是过眼云烟。"
            ),
            "structure_notes": "从幸福被误认成更大拥有切入，落到一餐一饭和陪伴。",
            "tags": ["幸福", "家人", "知己"],
        },
    )

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)
    monkeypatch.setattr(workbench.settings, "openai_allow_local_creative_fallbacks", True, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/simple-happiness-local-fallback/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] != "很多答案，都藏在失去以后才明白"
    assert (
        "家人" in payload["title"]
        or "知己" in payload["title"]
        or "日子过到眼前" in payload["title"]
        or "慢慢看清" in payload["title"]
    )
    assert "放手" not in payload["angle"]
    assert "不谈亏欠" not in payload["angle"]
    assert "更大的拥有" in payload["angle"] or "平凡日常" in payload["angle"] or "家人知己" in payload["angle"]


def test_generate_strategy_package_keeps_simple_happiness_article_on_everyday_warmth_lane(monkeypatch) -> None:
    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            raise RuntimeError("forced local topic fallback")

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "simple-happiness-strategy-fallback",
            "source_name": "手动录入",
            "title": "人生不求大富大贵，但求简单快乐",
            "url": "https://example.com/simple-happiness-strategy-fallback",
            "author": "未知",
            "summary": "文章主线是幸福不一定在更大的拥有里，常常就在平凡日常和家人知己身边。",
            "body_markdown": (
                "人活着，到底是为了什么？人生苦短，只求心情愉悦，家人安康，吃穿不愁，知己二三，四季平安。\n\n"
                "生活简单就迷人，人心简单就幸福。\n\n"
                "人这一辈子，谁也争不过朝夕，财富、名利、地位不过是过眼云烟。"
            ),
            "structure_notes": "从幸福被误认成更大拥有切入，落到一餐一饭和陪伴。",
            "tags": ["幸福", "家人", "知己"],
        },
    )

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)
    monkeypatch.setattr(workbench.settings, "openai_allow_local_creative_fallbacks", True, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    topic_response = client.post("/api/tracked-articles/simple-happiness-strategy-fallback/generate-topic")
    assert topic_response.status_code == 201
    topic_payload = topic_response.json()

    to_topic_response = client.post(
        "/api/tracked-articles/simple-happiness-strategy-fallback/to-topic",
        json={
            "slug": "simple-happiness-strategy-topic",
            "title": topic_payload["title"],
            "angle": topic_payload["angle"],
        },
    )
    assert to_topic_response.status_code == 201

    create_project_response = client.post(
        "/api/topics/simple-happiness-strategy-topic/create-project",
        json={"slug": "simple-happiness-strategy-project", "title": "简单幸福策略链路测试", "owner": "editorial"},
    )
    assert create_project_response.status_code == 201

    strategy_response = client.post("/api/projects/simple-happiness-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    strategy_payload = strategy_response.json()

    assert strategy_payload["strategy_card"]["structure_mode"] == "everyday_warmth_return"
    assert "家人平安、知己仍在" in strategy_payload["problem_brief"]["theme_axis"]
    assert "外在标准明明够了" in strategy_payload["strategy_card"]["opening_move"]
    assert "朴素却很准确的生活愿望" in strategy_payload["strategy_card"]["opening_move"]
    assert "继续投入" not in strategy_payload["strategy_card"]["body_shift"]


def test_generate_topic_from_tracked_article_rewrites_responsibility_shelter_article_out_of_generic_smallthings_sink(
    monkeypatch,
) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "原来一生里最重要的，常常都是那些不起眼的小事",
                "angle": "从人为什么总把重要感押在更大的目标上切入，写我们往前赶了很久以后，才怎样重新看见陪人吃饭、回家说话和有人惦记的日常分量。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "responsibility-shelter-reroute",
            "source_name": "手动录入",
            "title": "中年人的那句我没事，背后都是责任",
            "url": "https://example.com/responsibility-shelter-reroute",
            "author": "未知",
            "summary": "文章借成年人常说的“我没事”，写父母养老、孩子缴费、家里开销和伴侣依靠一起压上来时，很多人怎样先把自己往后放。重点不在歌颂吃苦，而在说明很多硬撑后来真的会变成一家人的安稳。",
            "body_markdown": (
                "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
                "生病了不敢请假，怕影响这个月的绩效；委屈了不敢辞职，因为你要撑起一个家的重量。\n\n"
                "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；慢慢长大的孩子，拥有了对生活说“不”的底气；深深爱着的伴侣，也能在风雨来临时有一处温暖的屋檐庇护。"
            ),
            "structure_notes": "先从一句“没事，有我”和电话账单这些现实重量切入，中段写责任怎样让人把自己往后收，结尾落回家里安稳和这些辛苦没有白熬。",
            "tags": ["责任托家", "中年压力", "家庭安稳"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    response = client.post("/api/tracked-articles/responsibility-shelter-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "不起眼的小事" not in payload["title"]
    assert "更大的目标上" not in payload["angle"]
    assert payload["title"] in {
        "电话一响，你先翻日历",
        "电话一响，你先把顺序往前排",
        "家里有事时，你先把今天排稳",
    }
    assert "没事，有我" not in payload["title"]
    assert "安稳" in payload["angle"]
    assert any(token in payload["angle"] for token in ("父母", "孩子", "家里", "辛苦"))


def test_generate_topic_from_tracked_article_rewrites_responsibility_shelter_article_out_of_abstract_emotion_sink(
    monkeypatch,
) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, str]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "每次接完家里电话都要缓一会儿的人，正在替全家消化情绪",
                "angle": "从“挂了电话才敢累”这个身体反应切入，拆开很多女性为什么总把委屈和疲惫往后收，以及她们长期托底后，家里那份安稳到底是怎样被一点点撑出来的。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "responsibility-shelter-abstract-emotion-reroute",
            "source_name": "手动录入",
            "title": "中年人的那句我没事，背后都是责任",
            "url": "https://example.com/responsibility-shelter-abstract-emotion-reroute",
            "author": "未知",
            "summary": "文章借成年人常说的“我没事”，写父母养老、孩子缴费、家里开销和伴侣依靠一起压上来时，很多人怎样先把自己往后放。重点不在歌颂吃苦，而在说明很多硬撑后来真的会变成一家人的安稳。",
            "body_markdown": (
                "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
                "生病了不敢请假，怕影响这个月的绩效；委屈了不敢辞职，因为你要撑起一个家的重量。\n\n"
                "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；慢慢长大的孩子，拥有了对生活说“不”的底气；深深爱着的伴侣，也能在风雨来临时有一处温暖的屋檐庇护。"
            ),
            "structure_notes": "先从一句“没事，有我”和电话账单这些现实重量切入，中段写责任怎样让人把自己往后收，结尾落回家里安稳和这些辛苦没有白熬。",
            "tags": ["责任托家", "中年压力", "家庭安稳"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    response = client.post("/api/tracked-articles/responsibility-shelter-abstract-emotion-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] != "每次接完家里电话都要缓一会儿的人，正在替全家消化情绪"
    assert "消化情绪" not in payload["title"]
    assert any(token in payload["title"] for token in ("责任", "家里", "灯"))
    assert "没事，有我" not in payload["title"]
    assert "安稳" in payload["angle"]
    assert any(token in payload["angle"] for token in ("父母", "孩子", "家里", "辛苦"))


def test_generate_topic_from_tracked_article_rewrites_responsibility_shelter_explanatory_title_to_scene_first(
    monkeypatch,
) -> None:
    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "你总想先把家里安排稳，这不是爱操心，是责任把你推成了那个多想一步的人",
                "angle": "这篇写清你为什么总把自己的累往后放：很多安稳并非天生存在，而是你提前排顺序、兜风险、接住情绪，家里才没那么慌。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "responsibility-shelter-explanatory-title-reroute",
            "source_name": "手动录入",
            "title": "中年人的那句我没事，背后都是责任",
            "url": "https://example.com/responsibility-shelter-explanatory-title-reroute",
            "author": "未知",
            "summary": "文章借成年人常说的“我没事”，写父母养老、孩子缴费、家里开销和伴侣依靠一起压上来时，很多人怎样先把自己往后放。",
            "body_markdown": (
                "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
                "生病了不敢请假，怕影响这个月的绩效；委屈了不敢辞职，因为你要撑起一个家的重量。\n\n"
                "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；慢慢长大的孩子，拥有了对生活说“不”的底气。"
            ),
            "structure_notes": "先从一句“没事，有我”和电话账单这些现实重量切入，中段写责任怎样让人把自己往后收，结尾落回家里安稳和这些辛苦没有白熬。",
            "tags": ["责任托家", "中年压力", "家庭安稳"],
        },
    )

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    response = client.post("/api/tracked-articles/responsibility-shelter-explanatory-title-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] in {
        "电话一响，你先翻日历",
        "电话一响，你先把顺序往前排",
        "家里有事时，你先把今天排稳",
    }
    assert "这不是爱操心" not in payload["title"]
    assert "多想一步的人" not in payload["title"]


def test_generate_topic_from_tracked_article_rewrites_responsibility_shelter_negative_topic_sink(
    monkeypatch,
) -> None:
    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "总说“先把家里理顺”的人，后来为什么更难开口说自己快撑不住了",
                "angle": "从总把顺序理清的人为什么慢慢把自己熬沉默切入，写责任怎样让人把话咽回去。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "responsibility-shelter-negative-topic-sink",
            "source_name": "手动录入",
            "title": "中年人的那句我没事，背后都是责任",
            "url": "https://example.com/responsibility-shelter-negative-topic-sink",
            "author": "未知",
            "summary": "文章借成年人常说的“我没事”，写父母养老、孩子缴费、家里开销和伴侣依靠一起压上来时，很多人怎样先把自己往后放。重点不在歌颂吃苦，而在说明很多认真托住日子的时刻后来真的会变成一家人的安稳。",
            "body_markdown": (
                "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
                "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；慢慢长大的孩子，拥有了对生活说“不”的底气；伴侣也能在风雨来临时有一处温暖的屋檐庇护。"
            ),
            "structure_notes": "先从一句“没事，有我”和电话账单这些现实重量切入，中段写责任怎样让人把家里理顺，结尾落回家里安稳和这些辛苦没有白费。",
            "tags": ["责任托家", "中年责任", "家庭安稳"],
        },
    )

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    response = client.post("/api/tracked-articles/responsibility-shelter-negative-topic-sink/generate-topic")
    assert response.status_code == 201
    payload = response.json()
    combined = f"{payload['title']} {payload['angle']}"

    for forbidden in ("快撑不住", "熬沉默", "咽回去", "沉默", "女性", "把自己往后放", "自己往后放"):
        assert forbidden not in combined
    assert any(token in payload["title"] for token in ("责任", "家里", "灯"))


def test_build_local_tracked_article_topic_fallback_uses_endurance_title_for_i_am_ok_responsibility_case() -> None:
    topic = workbench._build_local_tracked_article_topic_fallback(
        {
            "source_type": "tracked_article",
            "article_title": "中年人的世界，半生风雨，半生奔波",
            "summary": "成年人常说的我没事，背后是父母、孩子、账单和一家人的安稳。",
            "body_markdown": (
                "电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。"
                "成年人说过最多的谎，就是“我没事”。"
                "有时候，你也会问自己，这样熬到底值不值得。"
                "熬过万般辛苦，便得人间安稳。"
            ),
            "structure_notes": "从我没事切入，写那些不肯说出口的辛苦最后怎样慢慢落成一家人的安稳。",
            "tags": ["责任托家", "中年责任", "家庭安稳"],
        }
    )

    assert topic["title"] in {
        "家里一有事，你总会先把家稳住",
        "家里一有事，总是你先把顺序理出来",
    }
    assert "我没事" in topic["angle"]
    assert "父母" in topic["angle"]
    assert "孩子" in topic["angle"]
    assert "安稳" in topic["angle"]


def test_generate_topic_from_tracked_article_rewrites_inner_settlement_article_out_of_relationship_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "很多关系拖着不结束，真正消耗你的，是心里一直在等一个交代",
                "angle": "从聊天框、没说出口的话和那句迟迟等不到的回应切入，写一个人为什么总在旧关系里耗着自己。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "heart-settled-reroute",
            "source_name": "手动录入",
            "title": "此心安处，才是一个人最好的归宿",
            "url": "https://example.com/heart-settled-reroute",
            "author": "未知",
            "summary": "文章把外界起伏和内心安顿放在一起比较，重点不是某段关系有没有结果，也不是身体有没有告警，而是心为什么一直安不下来，人怎样把自己慢慢安顿回当下。",
            "body_markdown": (
                "杨绛先生说：人生最曼妙的风景，竟是内心的淡定与从容。心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
                "有时候，看似过不去的坎儿，其实是心结难解。把心抚平了，脚下自有坦途；把心看透了，郁结自会消散。\n\n"
                "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂，于岁岁年年中与内心相拥。此心安处是吾乡。"
            ),
            "structure_notes": "先写心为什么一直悬着，再拆人为什么总想把一切想明白，中段回到一餐一饮和一呼一吸怎样让生活重新有轻重。",
            "tags": ["心安", "内在归处", "与内心和解", "安顿自己"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/heart-settled-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "人这一生真正想要的，不过是一颗终于有归处的心"
    assert "总想先把一切想稳、想透、想明白" in payload["angle"]
    assert "一顿饭" in payload["angle"]
    assert "一口气" in payload["angle"]
    assert "一呼一吸" not in payload["angle"]
    assert "让生活重新有了轻重和归处" in payload["angle"]
    assert "聊天框" not in payload["title"]
    assert "交代" not in payload["title"]
    assert "旧关系" not in payload["angle"]
    assert "回应" not in payload["angle"]
    assert "体检" not in payload["angle"]
    assert "复查" not in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_inner_settlement_article_out_of_diagnostic_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "反复复盘过去、提前演练未来，心为什么更难落地",
                "angle": "从总怕自己失控、总想把最坏结果先演练完切入，写一个人为什么会把自己长期留在悬着和戒备里。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "heart-settled-diagnostic-reroute",
            "source_name": "手动录入",
            "title": "此心安处，才是一个人最好的归宿",
            "url": "https://example.com/heart-settled-diagnostic-reroute",
            "author": "未知",
            "summary": "文章把外界起伏和内心安顿放在一起比较，重点不是某段关系有没有结果，也不是身体有没有告警，而是心为什么一直安不下来，人怎样把自己慢慢安顿回当下。",
            "body_markdown": (
                "杨绛先生说：人生最曼妙的风景，竟是内心的淡定与从容。心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
                "有时候，看似过不去的坎儿，其实是心结难解。把心抚平了，脚下自有坦途；把心看透了，郁结自会消散。\n\n"
                "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂，于岁岁年年中与内心相拥。此心安处是吾乡。"
            ),
            "structure_notes": "先写心为什么一直悬着，再拆人为什么总想把一切想明白，中段回到一餐一饮和一呼一吸怎样让生活重新有轻重。",
            "tags": ["心安", "内在归处", "与内心和解", "安顿自己"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/heart-settled-diagnostic-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "人这一生真正想要的，不过是一颗终于有归处的心"
    assert "更难落地" not in payload["title"]
    assert "安放回当下" not in payload["angle"]
    assert "总想先把一切想稳、想透、想明白" in payload["angle"]
    assert "生活重新有了轻重和归处" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_inner_settlement_article_when_only_title_stays_suspended(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总把确认留给别人，心就会一直悬着",
                "angle": "很多不安并不是事情本身太难，而是我们把认可、结果和安全感都押在外部，连今天这一刻都没真正住进去；先把注意力收回到吃饭、呼吸和手头这件事上，心才会慢慢落地。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "heart-settled-title-suspended-reroute",
            "source_name": "手动录入",
            "title": "此心安处，才是一个人最好的归宿",
            "url": "https://example.com/heart-settled-title-suspended-reroute",
            "author": "未知",
            "summary": "文章把外界起伏和内心安顿放在一起比较，重点不是某段关系有没有结果，也不是身体有没有告警，而是心为什么一直安不下来，人怎样把自己慢慢安顿回当下。",
            "body_markdown": (
                "杨绛先生说：人生最曼妙的风景，竟是内心的淡定与从容。心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
                "有时候，看似过不去的坎儿，其实是心结难解。把心抚平了，脚下自有坦途；把心看透了，郁结自会消散。\n\n"
                "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂，于岁岁年年中与内心相拥。此心安处是吾乡。"
            ),
            "structure_notes": "先写心为什么一直悬着，再拆人为什么总想把一切想明白，中段回到一餐一饮和一呼一吸怎样让生活重新有轻重。",
            "tags": ["心安", "内在归处", "与内心和解", "安顿自己"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/heart-settled-title-suspended-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "人这一生真正想要的，不过是一颗终于有归处的心"
    assert "总想先把一切想稳、想透、想明白" in payload["angle"]
    assert "重新有了轻重和归处" in payload["angle"]
    assert "悬着" not in payload["title"]


def test_generate_topic_from_tracked_article_rewrites_inner_settlement_article_out_of_waiting_result_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "把安稳交给结果的人，最容易在等待里把自己耗空",
                "angle": "很多女性把情绪稳定交给回复、评价和结果，真正耗人的并不是事情没变，而是迟迟不肯把自己从等待里接回来。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "heart-settled-waiting-result-reroute",
            "source_name": "手动录入",
            "title": "此心安处，才是一个人最好的归宿",
            "url": "https://example.com/heart-settled-waiting-result-reroute",
            "author": "未知",
            "summary": "文章把外界起伏和内心安顿放在一起比较，重点不是某段关系有没有结果，也不是身体有没有告警，而是心为什么一直安不下来，人怎样把自己慢慢安顿回当下。",
            "body_markdown": (
                "杨绛先生说：人生最曼妙的风景，竟是内心的淡定与从容。心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
                "有时候，看似过不去的坎儿，其实是心结难解。把心抚平了，脚下自有坦途；把心看透了，郁结自会消散。\n\n"
                "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂，于岁岁年年中与内心相拥。此心安处是吾乡。"
            ),
            "structure_notes": "先写心为什么一直悬着，再拆人为什么总想把一切想明白，中段回到一餐一饮和一呼一吸怎样让生活重新有轻重。",
            "tags": ["心安", "内在归处", "与内心和解", "安顿自己"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/heart-settled-waiting-result-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "人这一生真正想要的，不过是一颗终于有归处的心"
    assert "总想先把一切想稳、想透、想明白" in payload["angle"]
    assert "一顿饭" in payload["angle"]
    assert "一口气" in payload["angle"]
    assert "一呼一吸" not in payload["angle"]
    assert "等待里把自己耗空" not in payload["title"]
    assert "交给回复、评价和结果" not in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_inner_settlement_article_out_of_result_dependence_sink(
    monkeypatch,
) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "把安全感押在结果上的人，为什么总觉得日子落不了地",
                "angle": "这篇稿子想拆开一种常见内耗：越想等外部确定了再松下来，越会把自己长期留在悬着的位置，真正的回稳往往从吃饭、呼吸和暂停解释开始。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "heart-settled-result-dependence-reroute",
            "source_name": "手动录入",
            "title": "此心安处，才是一个人最好的归宿",
            "url": "https://example.com/heart-settled-result-dependence-reroute",
            "author": "未知",
            "summary": "文章把外界起伏和内心安顿放在一起比较，重点不是某段关系有没有结果，也不是身体有没有告警，而是心为什么一直安不下来，人怎样把自己慢慢安顿回当下。",
            "body_markdown": (
                "杨绛先生说：人生最曼妙的风景，竟是内心的淡定与从容。心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
                "有时候，看似过不去的坎儿，其实是心结难解。把心抚平了，脚下自有坦途；把心看透了，郁结自会消散。\n\n"
                "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂，于岁岁年年中与内心相拥。此心安处是吾乡。"
            ),
            "structure_notes": "先写心为什么一直悬着，再拆人为什么总想把一切想明白，中段回到一餐一饮和一呼一吸怎样让生活重新有轻重。",
            "tags": ["心安", "内在归处", "与内心和解", "安顿自己"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/heart-settled-result-dependence-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "人这一生真正想要的，不过是一颗终于有归处的心"
    assert "总想先把一切想稳、想透、想明白" in payload["angle"]
    assert "一顿饭" in payload["angle"]
    assert "一口气" in payload["angle"]
    assert "一呼一吸" not in payload["angle"]
    assert "安全感押在结果上" not in payload["title"]
    assert "日子落不了地" not in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_stage_restart_article_toward_halfyear_restart_theme(
    monkeypatch,
) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总想先把一切想稳的人，心要靠日常一点点落地",
                "angle": "从半年节点最常见的自责误判写起，拆开未完成为何总被算成“我不够好”，再把注意力带回一餐一饮和仍在身边的人。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "halfyear-stage-restart-reroute",
            "source_name": "手动录入",
            "title": "过去的这半年，你过得好吗？",
            "url": "https://example.com/halfyear-stage-restart-reroute",
            "author": "未知",
            "summary": "文章围绕半年节点回望、事与愿违另有安排、珍惜身边人和接纳每个阶段的自己，给人重新出发的勇气。",
            "body_markdown": (
                "过去的这半年，你过得好吗？年初定下的目标又实现了多少呢？若事与愿违，一定另有安排。\n\n"
                "下半年，多腾点时间和精力，去做好眼前之事，珍惜身边所爱之人。\n\n"
                "人生的每个阶段，其实都有得有失，有好有坏。我们能做的，就是接受并努力爱每一个阶段的自己。"
            ),
            "structure_notes": "先写阶段节点上的自我盘点和遗憾，再转到珍惜眼前与接纳每个阶段的自己。",
            "tags": ["半年复盘", "下半年", "事与愿违另有安排", "珍惜身边人", "阶段接纳"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/halfyear-stage-restart-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "这半年没按你想的那样来，也不代表你白走了一程"
    assert "阶段节点" in payload["angle"]
    assert "遗憾怎样被安放" in payload["angle"]
    assert "重新接纳眼前这个阶段的自己" in payload["angle"]
    assert "带着期待继续往前" in payload["angle"]
    assert "日常一点点落地" not in payload["title"]


def test_generate_topic_from_tracked_article_rewrites_self_reliance_article_out_of_relationship_expression_sink(
    monkeypatch,
) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "把需要说得很轻的人，常常等不到真正的帮助",
                "angle": "很多人习惯先替别人考虑，把求助包装成‘顺手帮一下’，结果边界不清、需求不明，真正的支持反而更难落地。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "self-reliance-reroute",
            "source_name": "手动录入",
            "title": "即使没有帮助，也要学会自救自渡",
            "url": "https://example.com/self-reliance-reroute",
            "author": "未知",
            "summary": "文章从想找人倾诉却发现身边人也自顾不暇的场景切入，写成年人在低谷里对外求助常常得不到及时回应，于是逐渐学会收起委屈、转向自我消化和自我修复。核心落点不是拒绝他人，而是提醒人在不被接住的时候，也要有把自己托起来的能力。",
            "body_markdown": (
                "相信你也有过这样的时刻：心情不好的时候想找朋友倾诉，却发现朋友也愁眉不展。\n\n"
                "只有向内求，才能自我疗愈，生生不息。只有靠自己，你才能有所顿悟、有所收获、有所改变。\n\n"
                "即使没有帮助，也不会孤立无援，而是能够自救自渡。"
            ),
            "structure_notes": "先写想倾诉却发现别人也各自承压的现实处境，中段再拆为什么外求未必总能接住人，结尾回到向内稳住、自救自渡和慢慢把自己托起来。",
            "tags": ["自我疗愈", "情绪自救", "成年人压力", "低谷时刻", "自我支撑"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/self-reliance-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "说得很轻" not in payload["title"]
    assert "真正的帮助" not in payload["title"]
    assert "顺手帮一下" not in payload["angle"]
    assert "边界不清" not in payload["angle"]
    assert "需求不明" not in payload["angle"]
    assert any(anchor in payload["title"] for anchor in ("力气", "主心骨", "眼前这一步", "自己的光"))
    assert "现实触发点" in payload["angle"]
    assert "具体判断、行动或选择" in payload["angle"]
    assert "回稳" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_resilience_article_out_of_self_help_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总要多耗那11下的女性，先把自己从列表最底下挪上来",
                "angle": "从很多女性总把自己放在提醒列表最底下切入，拆开她们为什么总先照顾别人、先替所有人兜底，最后才想起把自己排回前面。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "jiang-yuyan-reroute",
            "source_name": "手动录入",
            "title": "一个人最大的底气，不是美貌，也不是金钱，而是韧性",
            "url": "https://example.com/jiang-yuyan-reroute",
            "author": "未知",
            "summary": "文章以残奥会冠军蒋裕燕的人生为例，重点写命运重击、长期疼痛、泳池训练和不被定义后的重建，而不是女性把自己放最后的情绪照顾。",
            "body_markdown": (
                "3岁那年，一场车祸无情夺走了蒋裕燕的右臂与右腿。从3岁到8岁，她每一年都要被迫走上手术台，接受锯掉新生骨头的剧痛。\n\n"
                "为了康复，她走进了泳池。没有右臂维持平衡，没有右腿蹬水发力，她每一次划水都要比常人多划11下。\n\n"
                "疲惫与酸痛，肩伤反复发作、背痛缠扰不休、炎症如影随形，可她从未停下前进的脚步。命运以痛吻她，她却在破碎中重建自己，不让任何人定义她能做的事情。"
            ),
            "structure_notes": "先写命运重击和手术台，再转到泳池里的训练硬撑，结尾回到不被定义和韧性重建。",
            "tags": ["韧性", "残奥冠军", "命运重击", "训练", "不被定义"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/jiang-yuyan-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "女性" not in payload["title"]
    assert "列表最底下" not in payload["title"]
    assert "把自己放最后" not in payload["title"]
    assert "提醒列表" not in payload["angle"]
    assert "先照顾别人" not in payload["angle"]
    assert "兜底" not in payload["angle"]
    assert "11下" in payload["title"] or "命运" in payload["title"] or "韧性" in payload["title"]
    assert "训练" in payload["angle"] or "命运" in payload["angle"] or "重建" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_response_priority_article_out_of_aftercare_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总让你等的人，也默认你会替这段关系善后",
                "angle": "这篇稿子拆开一种常见失衡：反复被晾着的代价，不只是联系变少，而是等待的人会被迫接下解释、体谅和关系善后的全部工作。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "no-time-priority-reroute",
            "source_name": "手动录入",
            "title": "没时间，不一定是真的没时间",
            "url": "https://example.com/no-time-priority-reroute",
            "author": "未知",
            "summary": "文章借日常联系里的“没时间”现象，讨论一段关系里真实的优先级排序。核心判断是：多数迟迟不回应并非真的抽不出空，而是投入意愿不足，时间分配往往比语言更能说明在乎程度。",
            "body_markdown": (
                "听过一句话：“红灯30秒，我喝了一口水，拍了张照片，回了条消息，连上蓝牙，放了一首喜欢的歌，所以你告诉我，什么是没时间？”\n\n"
                "真正的原因可能是，因为我们不够重要，所以对方漫不经心，爱搭不理。人对在乎的人，永远都有时间。\n\n"
                "没时间，是因为你不在他心里，或者顺序没那么优先。一个人的时间在哪儿，他的心就在哪儿。"
            ),
            "structure_notes": "开头借红灯30秒的细节切入，中段拆“忙”和“在乎”并不等价，结尾落到时间分配如何显出真实顺序。",
            "tags": ["关系优先级", "回应顺序", "时间分配"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/no-time-priority-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "善后" not in payload["title"]
    assert "把日子重新接上" not in payload["title"]
    assert "冷战" not in payload["angle"]
    assert "修复" not in payload["angle"]
    assert "没时间" in payload["title"] or "优先级" in payload["title"] or "时间" in payload["title"]
    assert "顺序" in payload["angle"] or "时间分配" in payload["angle"] or "在乎程度" in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_comment_followup_article_out_of_pressure_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "一直会回你消息的人，为什么还是让你慢慢不再开口",
                "angle": "从身体代价链切入，写人为什么总把自己的求救信号继续压后，不先抛人生答案。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "comment-followup-reroute",
            "source_name": "手动录入",
            "title": "真正关心你的人，会停下来读懂你没说完的话",
            "url": "https://example.com/comment-followup-reroute",
            "author": "未知",
            "summary": "文章借点赞和评论的差别，讨论什么才算真正把注意力和心力放在你身上。重点不在热闹，而在有没有人愿意停下来、多问一句、接住你没说完的话。",
            "body_markdown": (
                "朋友圈里，是给你点赞的人更在意你，还是给你评论的人更在意你？\n\n"
                "而评论，却需要停下来，读懂你的言外之意。\n\n"
                "真正关心你的人，是哪怕相隔千里，也能透过你的一句“我没事”，听出你心底的“我有点累”。"
            ),
            "structure_notes": "开头先拆点赞和评论的差别，中段写表层互动和真正关心之间的落差，结尾落到谁会回来追问、谁会接住你没说完的话。",
            "tags": ["回应差别", "真正在意", "追问", "接住情绪"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/comment-followup-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "身体代价链" not in payload["angle"]
    assert "求救信号继续压后" not in payload["angle"]
    assert "评论" in payload["angle"] or "追问" in payload["angle"] or "读懂" in payload["angle"]
    assert (
        "再问一句" in payload["title"]
        or "轻轻带过" in payload["title"]
        or "在意的人" in payload["title"]
    )
    assert "优先顺序" not in payload["title"]
    assert "排在前面" not in payload["title"]


def test_generate_topic_from_tracked_article_rewrites_self_worth_article_out_of_response_priority_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总被敷衍的人，常常先取消了自己的优先级",
                "angle": "把反复受委屈拆回三个更具体的接口：时间总让位、情绪总自我消化、底线总一退再退，关系里的轻慢往往就是这样长出来的。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "self-worth-reroute",
            "source_name": "手动录入",
            "title": "把自己养贵一点，日子才能过好一点",
            "url": "https://example.com/self-worth-reroute",
            "author": "未知",
            "summary": "文章真正想讨论的是，一个人在关系和生活里被怎样对待，往往与她是否尊重自己、是否守住边界密切相关。",
            "body_markdown": (
                "有一段话说得很好：你爱自己的程度，决定了谁能走进你的人生。\n\n"
                "总在委屈里迁就的人，会活成打折品；只在欢喜里停留的人，会活成奢侈品。\n\n"
                "所以，要学会把自己养贵一点。把门槛抬高一点，把标准收紧一点，把精力多用来喂养自己，托举自己。"
            ),
            "structure_notes": "开头从一句判断性引用起笔，中段拆将就和贬值怎样慢慢发生，结尾回到尊重自己、抬高边界和标准。",
            "analysis_theme": "这篇文章真正想讨论的是：一个人在关系和生活里被怎样对待，往往与她是否尊重自己、是否守住边界密切相关。",
            "analysis_core_conflict": "很多人在关系里反复受委屈、被轻慢，以为是运气差或他人问题，实际上更深的冲突是自我价值感过低、边界松散，导致不断用讨好和将就换取连接。",
            "analysis_emotional_exit": "先把精力从无效关系里收回来，抬高边界、尊重自己，不必急着讨好谁，也相信日子会因此慢慢变稳、变体面。",
            "analysis_structure_mode": "emotional_engine_direct",
            "analysis_opening_pattern": "从一句带判断性的引用起笔，先建立你爱自己的程度会影响别人如何对你的核心前提。",
            "analysis_do_not_turn_into": "不要改写成单纯鼓吹高价值感的鸡汤，也不要写成教人冷漠抬价的爽文套路；它更接近在谈自尊、边界和自我照料。",
            "tags": ["自爱", "自尊", "边界", "自我价值"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/self-worth-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "优先级" not in payload["title"]
    assert "被敷衍" not in payload["title"]
    assert "时间总让位" not in payload["angle"]
    assert "情绪总自我消化" not in payload["angle"]
    assert payload["title"] == "把自己看重一点，关系里的分寸才会回来"
    assert "把自己看重一点" in payload["title"] or "关系里的分寸" in payload["title"]
    assert "门槛" in payload["angle"] or "标准" in payload["angle"] or "边界" in payload["angle"]
    assert "体面" in payload["angle"] or "分寸" in payload["angle"] or "把精力收回来" in payload["angle"]
    for forbidden in ("养贵", "贱卖", "打折品", "奢侈品", "不是高傲", "不是冷漠"):
        assert forbidden not in payload["title"]
        assert forbidden not in payload["angle"]
    assert not re.search(r"不是[^。！？!?；;\n]{1,24}(?:而是|只是|就是|(?<!不)是)", payload["title"])


def test_generate_topic_from_tracked_article_rewrites_supportive_appreciation_article_out_of_negative_exhaustion_sink(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总在替别人收拾情绪的人，最后最容易把自己耗空",
                "angle": "从长期替关系兜底的人为什么会在反复原谅里慢慢失去自我感切入，拆开那种总先顾及别人感受的人，后来如何把自己放到越来越后面。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "soft-hearted-reroute",
            "source_name": "手动录入",
            "title": "如果你身边有这样一个心软的人，请一定要牵紧他的手",
            "url": "https://example.com/soft-hearted-reroute",
            "author": "未知",
            "summary": "文章重点不是谁在关系里耗空自己，而是心软为什么常被误解，以及那些明明拎得清、却还是愿意包容和体谅别人的人，为什么最值得被珍惜。",
            "body_markdown": (
                "有一种人，习惯了燃烧自己，去照亮别人。你对他好，他会对你更好。\n\n"
                "心软的人并不傻，他们的心里比谁都拎得清。不去计较，是因为心里在乎，不想与爱的人争辩输赢、对错和得失。\n\n"
                "那些愿意包容你的人，一定很爱你。如果你身边有这样一个心软的人，请你一定要牵紧他的手。"
            ),
            "structure_notes": "先写心软的人总会先替别人着想，再拆这种柔软为什么常被误读，结尾回到这样的人最值得被珍惜。",
            "tags": ["心软", "包容", "体谅", "值得珍惜"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post("/api/tracked-articles/soft-hearted-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "收拾情绪" not in payload["title"]
    assert "耗空" not in payload["title"]
    assert "失去自我" not in payload["angle"]
    assert "兜底" not in payload["angle"]
    assert any(token in payload["title"] for token in ("心软", "珍惜", "温柔"))
    assert any(token in payload["angle"] for token in ("包容", "体谅", "珍惜", "温柔"))


def test_generate_topic_from_tracked_article_rewrites_scene_first_office_topic_toward_continuous_scene_entry(monkeypatch) -> None:
    slug = f"scene-first-office-topic-reroute-{time.time_ns()}"

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "散会后还在心里补那段发言的人，真正被耗掉的是表达时机感",
                "angle": "从“会后才把该说的话在心里补完”这个接口切入，拆开女性在权威现场反复延迟表达后，如何一步步失去开口的内部时机。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": slug,
            "source_name": "手动录入",
            "title": "很多话不是没想好，是总在那个要开口的会议室里被咽回去",
            "url": f"https://example.com/{slug}",
            "author": "未知",
            "summary": "文章重点不是先讲职场道理，而是先让读者跟着会议前、中、后的连续现场走一遍，再意识到真正被压后的是什么。",
            "body_markdown": (
                "周一早会开始前，她站在投影幕布旁，把昨晚改好的方案又往后翻了一页。\n\n"
                "主管进门，随手把咖啡放在桌角，先说了一句‘今天先按老方案过吧’，会议室里的人都低头去翻手里的资料。\n\n"
                "散会以后，她还坐在原位，看着屏幕上的最后一页，直到清洁阿姨来收水杯，才把那句本来该在会上说出来的话关掉。\n\n"
                "很多时候，问题不是没看见，而是一个人总在那个现场里先替气氛让路。"
            ),
            "structure_notes": "开头先让会议前后几个连续场景带路，后面再把总在现场里先让路这件事讲明白，不要一上来平铺观点。",
            "analysis_theme": "这篇文章真正想讨论的是：很多职场沉默不是没想法，而是总有人在那个现场里先替秩序和气氛让路。",
            "analysis_core_conflict": "明明知道有话该说，可一回到会议室和现场顺序里，人就先把更重要的话压后。",
            "analysis_emotional_exit": "先让人认出自己是怎么一步步把发言机会让过去的，后面才谈表达和位置感。",
            "analysis_structure_mode": "scene_first_progression",
            "analysis_opening_pattern": "先从会议室前后连续现场切入，再慢慢提判断。",
            "analysis_do_not_turn_into": "不要一开头就把它写成抽象职场说理文。",
            "tags": ["会议室", "场景推进", "表达时机"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post(f"/api/tracked-articles/{slug}/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "散会后才开口，位置就会慢慢往后退"
    assert "会前先压住改过的那页" in payload["angle"]
    assert "会后还在心里补那句提醒" in payload["angle"]
    assert "现场切入" in payload["angle"] or "一整段现场" in payload["angle"]
    assert "表达时机感" not in payload["title"]


def test_generate_topic_from_tracked_article_rewrites_scene_first_friendship_topic_toward_continuous_scene_entry(monkeypatch) -> None:
    slug = f"scene-first-friendship-topic-reroute-{time.time_ns()}"

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "关系会慢慢失联，常常卡在这一步：你先替对方决定了‘别说了’",
                "angle": "把‘沉默’拆成一种常见的人际预判机制：你以为是在体谅、避嫌和保留分寸，实际也在反复撤回一次本可验证的靠近。",
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": slug,
            "source_name": "手动录入",
            "title": "很多关系后来变淡，不是因为吵散了，是因为每次想说的时候都先算了",
            "url": f"https://example.com/{slug}",
            "author": "未知",
            "summary": "文章重点不是先讲疏远道理，而是先让读者跟着地铁口、等车、上车后的连续现场走一遍，再意识到那句话为什么没问出口。",
            "body_markdown": (
                "雨停以后，她们站在地铁口等最后一班接驳车，手机屏幕上还停着那句没发出去的‘你最近是不是不太开心’。\n\n"
                "朋友把围巾往上拉了拉，只说‘最近有点忙’，然后低头去看脚边那滩还没干透的水。\n\n"
                "车来了，她们一前一后上去，坐定以后谁都没有再提刚才的话题，只剩窗户上被呵出来的一小团白雾。\n\n"
                "很多疏远，不是从翻脸开始的，而是从这些明明看见了、却还是决定先不碰的瞬间开始的。"
            ),
            "structure_notes": "开头先让地铁口到车上的连续现场带路，后面再把想问又没问这件事讲明白，不要一上来平铺关系判断。",
            "analysis_theme": "这篇文章真正想讨论的是：很多关系里的变淡，不是一次冲突决定的，而是一个人一次次先替对方决定别开口。",
            "analysis_core_conflict": "明明看见了对方的低落，可一回到那个现场里，人就先把更重要的话收回去。",
            "analysis_emotional_exit": "先让人认出自己是怎么一次次把靠近撤回去的，后面才谈关系为什么会慢慢变远。",
            "analysis_structure_mode": "scene_first_progression",
            "analysis_opening_pattern": "先从等车和上车的连续现场切入，再慢慢提判断。",
            "analysis_do_not_turn_into": "不要一开头就把它写成抽象关系总结。",
            "tags": ["地铁口", "场景推进", "关系变淡"],
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    response = client.post(f"/api/tracked-articles/{slug}/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "没问出口的那句话，最容易把关系拖远"
    assert "等车时看出不对劲却还是先没问" in payload["angle"]
    assert "上车后话题跟着白气一起散掉" in payload["angle"]
    assert "连续现场" in payload["angle"]
    assert "人际预判机制" not in payload["angle"]


def test_generate_topic_from_tracked_article_rewrites_scene_first_household_topic_toward_night_scene_entry() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "那张检查单放在桌上时，她忽然不想再说自己没事",
        "summary": "文章重点不是先讲家庭责任，而是让读者跟着夜里回家、看见检查单、想问又收回去的连续现场走一遍，再意识到沉默是怎么留下来的。",
        "body_markdown": (
            "夜里回到家，餐桌上的检查单还没收。她把包放下，先去摸了一下水壶外壁，还是温的。\n\n"
            "孩子已经睡了，灯还留着一盏。她原本想问一句今天复查到底怎么说，可看见对方揉了揉眉心，话又先收了回去。\n\n"
            "很多家里的心事，不是不能说，只是总被那句‘明天再说吧’轻轻按住了。"
        ),
        "structure_notes": "开头先让夜里回家、餐桌、检查单、水壶这些连续现场带路，后面再把为什么总把话往后放讲明白。",
        "analysis_theme": "这篇文章真正想讨论的是：家里的很多沉默，不是没有爱，而是总有人先把更重要的话往后压。",
        "analysis_core_conflict": "明明想问、也看见了对方的疲惫，可一回到那个晚上和那个家里的气氛里，人就先把更重要的话收回去。",
        "analysis_emotional_exit": "先让人认出自己是怎么把话一天天压后的，后面才谈家为什么要慢慢把心事说开。",
        "analysis_structure_mode": "scene_first_progression",
        "analysis_opening_pattern": "先从夜里回家和餐桌前的连续现场切入，再慢慢提判断。",
    }

    topic = workbench._apply_tracked_article_topic_rewrites(
        payload,
        {
            "title": "很多重要的话，不是忘了说，是总在那个刚好能开口的晚上又被压回去了",
            "angle": "从家里总有人先把气氛稳住这件事切入，拆开沉默怎样慢慢变成关系里的惯性和误会。",
        },
    )

    assert topic["title"] == "家里的心事，最怕总被顺到明天"
    assert "夜里回家看见检查单" in topic["angle"]
    assert "第二天照常出门却还悬着" in topic["angle"]
    assert "连续现场" in topic["angle"]
    assert "关系里的惯性和误会" not in topic["angle"]


def test_build_local_tracked_article_topic_fallback_scene_first_household_prefers_analysis_structure_mode_seed() -> None:
    topic = workbench._build_local_tracked_article_topic_fallback(
        {
            "article_title": "那张检查单放在桌上时，她忽然不想再说自己没事",
            "summary": "写家里那些总被明天再说压住的重要话题。",
            "body_markdown": (
                "夜里回到家，餐桌上的检查单还没收。她把包放下，先去摸了一下水壶外壁，还是温的。\n\n"
                "孩子已经睡了，灯还留着一盏。她原本想问一句今天复查到底怎么说，可看见对方揉了揉眉心，话又先收了回去。"
            ),
            "structure_notes": "夜里回家看见检查单-想问的话又往回收-第二天照常出门-回到家里的心事要慢慢说开。",
            "analysis_theme": "主线不是忍耐，而是家里很多沉默，都是先想稳住这个晚上。",
            "analysis_structure_mode": "scene_first_progression",
        }
    )

    assert topic["title"] == "家里的心事，最怕总被顺到明天"
    assert "夜里回家看见检查单" in topic["angle"]
    for forbidden in ("围绕《", "重建新的具体入口", "更贴近真人表达", "很多答案，都是把日子过到眼前以后，才慢慢看清的"):
        assert forbidden not in topic["title"]
        assert forbidden not in topic["angle"]


def test_apply_tracked_article_topic_rewrites_infers_scene_first_household_without_analysis_mode() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "那张检查单放在桌上时，她忽然不想再说自己没事",
        "summary": "文章重点不是抽象讲放下，而是让读者先认出夜里回家、看见检查单、想问又收回去的那个晚上。",
        "body_markdown": (
            "夜里回到家，餐桌上的检查单还没收。她把包放下，先去摸了一下水壶外壁，还是温的。\n\n"
            "孩子已经睡了，灯还留着一盏。她原本想问一句今天复查到底怎么说，可看见对方揉了揉眉心，话又先收了回去。\n\n"
            "很多家里的心事，不是不能说，只是总被那句‘明天再说吧’轻轻按住了。"
        ),
        "structure_notes": "先把夜里回家、检查单、水壶、孩子睡了这些连续现场走完，再谈家里的沉默是怎么留下来的。",
    }

    topic = workbench._apply_tracked_article_topic_rewrites(
        payload,
        {
            "title": "很多答案，都是把日子过到眼前以后，才慢慢看清的",
            "angle": "围绕《那张检查单放在桌上时，她忽然不想再说自己没事》对应的现实处境切入，重建新的具体入口。",
        },
    )

    assert topic["title"] == "家里的心事，最怕总被顺到明天"
    assert "夜里回家看见检查单" in topic["angle"]
    assert "第二天照常出门却还悬着" in topic["angle"]
    for forbidden in ("围绕《", "重建新的具体入口", "很多答案，都是把日子过到眼前以后，才慢慢看清的"):
        assert forbidden not in topic["title"]
        assert forbidden not in topic["angle"]


def test_resolve_tracked_article_expected_selection_mode_infers_scene_first_from_household_scene() -> None:
    payload = {
        "article_title": "那张检查单放在桌上时，她忽然不想再说自己没事",
        "summary": "文章重点不是抽象讲放下，而是让读者先认出夜里回家、看见检查单、想问又收回去的那个晚上。",
        "body_markdown": (
            "夜里回到家，餐桌上的检查单还没收。她把包放下，先去摸了一下水壶外壁，还是温的。\n\n"
            "孩子已经睡了，灯还留着一盏。她原本想问一句今天复查到底怎么说，可看见对方揉了揉眉心，话又先收了回去。"
        ),
        "structure_notes": "先把夜里回家、检查单、水壶、孩子睡了这些连续现场走完，再谈家里的沉默是怎么留下来的。",
    }

    assert workbench._resolve_tracked_article_expected_selection_mode(payload) == "scene_first_progression"


def test_tracked_articles_can_be_created_listed_and_turned_into_topics() -> None:
    initial_response = client.get("/api/tracked-articles")
    assert initial_response.status_code == 200
    assert len(initial_response.json()) == 0

    create_response = client.post(
        "/api/tracked-articles",
        json={
            "slug": "accountability-repair-notes",
            "source_name": "关系练习手册",
            "title": "吵完架之后，真正让关系回来的是这一步",
            "url": "https://example.com/accountability-repair-notes",
            "author": "阿沉",
            "summary": "拆解冲突后的修复动作和表达顺序。",
            "body_markdown": "第一段：先回到现场。\n\n第二段：再说修复动作。",
            "structure_notes": "先回到现场，再拆动作，最后落到可执行表达。",
            "tags": ["关系修复", "冲突沟通"],
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["slug"] == "accountability-repair-notes"
    assert created["source_kind"] == "manual"
    assert created["source_name"] == "关系练习手册"
    assert created["created_at"]
    assert created["body_markdown"] == "第一段：先回到现场。\n\n第二段：再说修复动作。"
    assert created["tags"] == ["关系修复", "冲突沟通"]

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    tracked_articles = list_response.json()
    assert tracked_articles[0]["slug"] == "accountability-repair-notes"
    assert tracked_articles[0]["source_kind"] == "manual"
    assert tracked_articles[0]["created_at"]
    assert tracked_articles[0]["body_markdown"] == "第一段：先回到现场。\n\n第二段：再说修复动作。"

    topic_response = client.post(
        "/api/tracked-articles/accountability-repair-notes/to-topic",
        json={
            "slug": "repair-after-fight-topic",
            "title": "吵完架后，怎么把关系真正拉回来",
            "angle": "修复动作",
        },
    )
    assert topic_response.status_code == 201
    topic = topic_response.json()
    assert topic["source_type"] == "tracked_article"
    assert topic["source_ref_slug"] == "accountability-repair-notes"
    assert topic["status"] == "pending"

    topics_response = client.get("/api/topics")
    assert topics_response.status_code == 200
    topics = topics_response.json()
    assert topics[0]["slug"] == "repair-after-fight-topic"
    assert topics[0]["source_type"] == "tracked_article"


def test_tracked_article_blank_source_name_falls_back_to_manual_label() -> None:
    create_response = client.post(
        "/api/tracked-articles",
        json={
            "slug": "blank-source-article",
            "source_name": "",
            "title": "来源名缺失时也要能继续进入选题链",
            "url": "https://example.com/blank-source-article",
            "author": "编辑部",
            "summary": "验证空来源名的兜底展示。",
            "body_markdown": "",
            "structure_notes": "场景切入 + 兜底校验。",
            "tags": ["兜底"],
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["source_kind"] == "manual"
    assert created["source_name"] == "手动录入"

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    tracked_articles = list_response.json()
    assert tracked_articles[0]["slug"] == "blank-source-article"
    assert tracked_articles[0]["source_name"] == "手动录入"


def test_tracked_articles_list_sanitizes_existing_wechat_markup_in_summary_and_body() -> None:
    create_response = client.post(
        "/api/tracked-articles",
        json={
            "slug": "dirty-wechat-body",
            "source_name": "冷爱",
            "title": "离婚不离家最大的代价，到底在惩罚谁",
            "url": "https://mp.weixin.qq.com/s/dirty-example",
            "author": "冷爱",
            "summary": (
                "很多人离婚后，因为孩子、房子、经济压力，选择继续住在一起。&nbsp;"
                '&lt;a class="wx_topic_link" topic-id="abc"&gt;#离婚不离家&lt;/a&gt;'
            ),
            "body_markdown": (
                "很多人离婚后，因为孩子、房子、经济压力，选择继续住在一起。&nbsp;"
                '&lt;a class="wx_topic_link" topic-id="abc"&gt;#离婚不离家&lt;/a&gt;\n\n'
                '&lt;a class="wx_topic_link" topic-id="def"&gt;#情感内耗&lt;/a&gt;'
            ),
            "structure_notes": "Imported from WeChat MP article list; structure notes pending review.",
            "tags": ["wechat-mp", "冷爱"],
        },
    )
    assert create_response.status_code == 201

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    tracked_article = next(article for article in list_response.json() if article["slug"] == "dirty-wechat-body")
    assert tracked_article["summary"] == "很多人离婚后，因为孩子、房子、经济压力，选择继续住在一起。 #离婚不离家"
    assert tracked_article["body_markdown"] == (
        "很多人离婚后，因为孩子、房子、经济压力，选择继续住在一起。 #离婚不离家\n\n"
        "#情感内耗"
    )


def test_tracked_article_refresh_body_updates_body_and_source(monkeypatch) -> None:
    create_response = client.post(
        "/api/tracked-articles",
        json={
            "slug": "wechat-refresh-target",
            "source_name": "冷爱",
            "title": "需要补抓正文的公众号文章",
            "url": "https://mp.weixin.qq.com/s/refresh-example",
            "author": "冷爱",
            "summary": "当前只有摘要。",
            "body_markdown": "",
            "structure_notes": "Imported from WeChat MP article list; structure notes pending review.",
            "tags": ["wechat-mp", "冷爱"],
        },
    )
    assert create_response.status_code == 201

    class FakeWechatClient:
        def fetch_article_body(self, article_link: str, fallback_digest: str) -> tuple[str, str]:
            assert article_link == "https://mp.weixin.qq.com/s/refresh-example"
            assert fallback_digest == "当前只有摘要。"
            return ("第一段：这是补抓到的正文。\n\n第二段：正文已经回填。", "content_noencode")

    monkeypatch.setattr("app.api.tracked_articles.get_wechat_mp_client", lambda: FakeWechatClient())

    refresh_response = client.post("/api/tracked-articles/wechat-refresh-target/refresh-body")
    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert payload["slug"] == "wechat-refresh-target"
    assert payload["body_markdown"] == "第一段：这是补抓到的正文。\n\n第二段：正文已经回填。"
    assert payload["body_source"] == "content_noencode"

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    tracked_article = next(article for article in list_response.json() if article["slug"] == "wechat-refresh-target")
    assert tracked_article["body_markdown"] == "第一段：这是补抓到的正文。\n\n第二段：正文已经回填。"
    assert tracked_article["body_source"] == "content_noencode"


def test_tracked_article_metadata_enrichment_uses_ai_and_persists(monkeypatch) -> None:
    create_response = client.post(
        "/api/tracked-articles",
        json={
            "slug": "repair-over-dinner",
            "source_name": "关系练习手册",
            "title": "真正让关系缓回来，常常不是解释，而是先把饭吃完",
            "url": "https://example.com/repair-over-dinner",
            "author": "",
            "summary": "",
            "body_markdown": "那天谁都没有再争，只是安安静静把饭吃完。\n\n后来我才明白，很多关系不是输在道理，而是输在当下那口气里。",
            "structure_notes": "",
            "tags": [],
        },
    )
    assert create_response.status_code == 201

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("tracked_article_metadata", payload))
            return {
                "author": "晚舟",
                "summary": "从一顿没说破的晚饭切入，拆开关系缓和时真正起作用的顺序。",
                "structure_notes": "生活场景起笔，接着回看情绪卡点，最后落到能执行的表达动作。",
                "analysis_theme": "关系修复里，真正起作用的常常不是解释，而是先接住当下那一下失望。",
                "analysis_core_conflict": "两个人都急着说明白时，最先被漏掉的反而是当下的情绪承接。",
                "analysis_emotional_exit": "把关系从对错争执里带回可被接住、可重新开口的位置。",
                "analysis_structure_mode": "relationship_aftercare",
                "analysis_opening_pattern": "从一顿没说破的晚饭现场起笔。",
                "analysis_do_not_turn_into": "不要写成泛沟通技巧清单或谁更有道理的辩论稿。",
                "tags": ["关系修复", "沟通节奏", "饭桌场景"],
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    enrich_response = client.post("/api/tracked-articles/repair-over-dinner/enrich-metadata")
    assert enrich_response.status_code == 200
    payload = enrich_response.json()
    assert payload["slug"] == "repair-over-dinner"
    assert payload["author"] == "晚舟"
    assert payload["summary"] == "从一顿没说破的晚饭切入，拆开关系缓和时真正起作用的顺序。"
    assert payload["structure_notes"] == "生活场景起笔，接着回看情绪卡点，最后落到能执行的表达动作。"
    assert payload["analysis_theme"] == "关系修复里，真正起作用的常常不是解释，而是先接住当下那一下失望。"
    assert payload["analysis_core_conflict"] == "两个人都急着说明白时，最先被漏掉的反而是当下的情绪承接。"
    assert payload["analysis_emotional_exit"] == "把关系从对错争执里带回可被接住、可重新开口的位置。"
    assert payload["analysis_structure_mode"] == "relationship_aftercare"
    assert payload["analysis_opening_pattern"] == "从一顿没说破的晚饭现场起笔。"
    assert payload["analysis_do_not_turn_into"] == "不要写成泛沟通技巧清单或谁更有道理的辩论稿。"
    assert payload["tags"] == ["关系修复", "沟通节奏", "饭桌场景"]

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    tracked_article = next(article for article in list_response.json() if article["slug"] == "repair-over-dinner")
    assert tracked_article["author"] == "晚舟"
    assert tracked_article["summary"] == "从一顿没说破的晚饭切入，拆开关系缓和时真正起作用的顺序。"
    assert tracked_article["structure_notes"] == "生活场景起笔，接着回看情绪卡点，最后落到能执行的表达动作。"
    assert tracked_article["analysis_theme"] == "关系修复里，真正起作用的常常不是解释，而是先接住当下那一下失望。"
    assert tracked_article["analysis_structure_mode"] == "relationship_aftercare"
    assert tracked_article["tags"] == ["关系修复", "沟通节奏", "饭桌场景"]

    assert len(fake_generator.calls) == 1
    call_type, call_payload = fake_generator.calls[0]
    assert call_type == "tracked_article_metadata"
    assert call_payload["source_kind"] == "manual"
    assert call_payload["source_name"] == "关系练习手册"
    assert call_payload["article_title"] == "真正让关系缓回来，常常不是解释，而是先把饭吃完"
    assert call_payload["body_source"] == "manual"
    assert call_payload["body_markdown"] == (
        "那天谁都没有再争，只是安安静静把饭吃完。\n\n后来我才明白，很多关系不是输在道理，而是输在当下那口气里。"
    )


def test_tracked_article_metadata_enrichment_reuses_same_flow_for_wechat_import(monkeypatch) -> None:
    workbench.import_tracked_articles(
        [
            TrackedArticleCreate(
                slug="wechat-import-enrich-target",
                source_kind="wechat_mp_import",
                source_name="冷爱",
                title="关系卡住的时候，很多人不是不想改，而是没电了",
                url="https://mp.weixin.qq.com/s/enrich-target",
                author="冷爱",
                summary="文章把检验爱情的试金石放到争吵后的表现里观察：关键不是要不要吵架，而是对方回避修复还是主动沟通、接住失望。",
                body_markdown="先写关系修复里的无力感，伴侣之间的冷暴力和争执，再回到能量耗尽这件小事本身。\n\n最后才谈两个人的修复能做的那一步，让读者看见回避修复的代价，不是永远不吵架，而是有人回来沟通。",
                body_source="content_noencode",
                structure_notes="",
                tags=["wechat-mp"],
            )
        ],
        source_kind="wechat_mp_import",
    )

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("tracked_article_metadata", payload))
            return {
                "author": "不该覆盖的作者名",
                "summary": "从关系里的无力感切入，把问题落到精力透支而非方法缺失。",
                "structure_notes": "先写卡住感，再拆能量缺口，最后回到现实动作。",
                "analysis_theme": "关系卡住时，很多人真正缺的不是方法，而是继续修复的心力。",
                "analysis_core_conflict": "嘴上知道该怎么做，身体和情绪却已经没有余量把关系接回来了。",
                "analysis_emotional_exit": "先承认没电，再把修复动作压回现实能做到的一小步。",
                "analysis_structure_mode": "relationship_aftercare",
                "analysis_opening_pattern": "先从关系里那种无力感和卡住感切入。",
                "analysis_do_not_turn_into": "不要写成技巧课或单纯责怪谁不够努力。",
                "tags": ["关系修复", "能量耗尽", "公众号参考"],
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    enrich_response = client.post("/api/tracked-articles/wechat-import-enrich-target/enrich-metadata")
    assert enrich_response.status_code == 200
    payload = enrich_response.json()
    assert payload["source_kind"] == "wechat_mp_import"
    assert payload["author"] == "冷爱"
    assert payload["summary"] == "从关系里的无力感切入，把问题落到精力透支而非方法缺失。"
    assert payload["structure_notes"] == "先写卡住感，再拆能量缺口，最后回到现实动作。"
    assert payload["analysis_theme"] == "关系卡住时，很多人真正缺的不是方法，而是继续修复的心力。"
    assert payload["analysis_structure_mode"] == "relationship_aftercare"
    assert payload["tags"] == ["关系修复", "能量耗尽", "公众号参考"]
    assert payload["body_source"] == "content_noencode"

    assert len(fake_generator.calls) == 1
    _, call_payload = fake_generator.calls[0]
    assert call_payload["source_kind"] == "wechat_mp_import"
    assert call_payload["author"] == "冷爱"
    assert "检验爱情" in call_payload["summary"]
    assert call_payload["body_source"] == "content_noencode"


def test_project_generation_works_for_topics_created_from_tracked_articles(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {"hook": "从一次沉默后的回头动作切入", "outline_body": "1. 冲突现场\n2. 错位感受\n3. 修复动作"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {
                "title": "别急着解释，先把那一下失望接住",
                "body_markdown": (
                    "# 别急着解释，先把那一下失望接住\n\n"
                    "先写失望现场，再把那一下没有被回应的委屈慢慢拆开。"
                ),
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "slow-repair-template",
            "source_name": "夜读关系实验室",
            "title": "别急着解释，先把那一下失望接住",
            "url": "https://example.com/slow-repair-template",
            "author": "北岛",
            "summary": "从关系修复案例提炼表达顺序。",
            "body_markdown": (
                "# 别急着解释，先把那一下失望接住\n\n"
                "先写失望现场，再把那一下没有被回应的委屈慢慢拆开。"
            ),
            "body_source": "manual",
            "structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "tags": ["表达修复"],
        },
    )
    client.post(
        "/api/tracked-articles/slow-repair-template/to-topic",
        json={
            "slug": "slow-repair-topic",
            "title": "先接住失望，再谈道理",
            "angle": "关系修复",
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    project_response = client.post(
        "/api/topics/slow-repair-topic/create-project",
        json={
            "slug": "slow-repair-project",
            "title": "慢修复关系稿",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    project = project_response.json()
    assert project["topic_slug"] == "slow-repair-topic"
    assert project["current_chain_state"] == "missing_strategy"
    assert project["next_required_step"] == "generate_strategy_package"

    blocked_outline_response = client.post("/api/projects/slow-repair-project/generate-outline")
    assert blocked_outline_response.status_code == 409
    assert blocked_outline_response.json()["detail"] == (
        "Tracked article projects require an adopted strategy card before outline generation"
    )

    blocked_draft_response = client.post("/api/projects/slow-repair-project/generate-draft")
    assert blocked_draft_response.status_code == 409
    assert blocked_draft_response.json()["detail"] == (
        "Tracked article projects require an adopted strategy card before draft generation"
    )

    strategy_response = client.post("/api/projects/slow-repair-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    assert strategy_response.json()["strategy_card"]["version"] == 1
    assert strategy_response.json()["problem_brief"]["emotional_value_goal"]
    assert strategy_response.json()["strategy_card"]["positive_direction"]
    assert strategy_response.json()["strategy_card"]["hook_trigger"]
    assert strategy_response.json()["strategy_card"]["progression_drive"]
    assert strategy_response.json()["strategy_card"]["share_reason"]
    assert strategy_response.json()["strategy_card"]["quotable_line_goal"]
    assert strategy_response.json()["strategy_card"]["packaging_focus"]

    adopt_response = client.post("/api/projects/slow-repair-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200
    adopted_project = adopt_response.json()["project"]
    assert adopted_project["current_chain_state"] == "missing_outline"
    assert adopted_project["next_required_step"] == "generate_outline"

    outline_response = client.post("/api/projects/slow-repair-project/generate-outline")
    assert outline_response.status_code == 201
    outline = outline_response.json()
    assert outline["hook"] == "从一次沉默后的回头动作切入"

    draft_response = client.post("/api/projects/slow-repair-project/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()
    assert draft["title"] == "别急着解释，先把那一下失望接住"

    detail_response = client.get("/api/projects/slow-repair-project")
    assert detail_response.status_code == 200
    reference_report = detail_response.json()["reference_originality_report"]
    assert reference_report["risk_level"] == "high"
    assert reference_report["risk_label"] == "原创隔离风险高"
    assert reference_report["overlap_report"]["title_same"] is True
    assert reference_report["overlap_report"]["exact_long_sentence_overlap_count"] >= 1
    assert reference_report["danger_fragment_hits"]
    assert reference_report["quality_signals"]["functional_equivalence_ready"] is False

    assert len(fake_generator.calls) in {2, 3}
    outline_call_type, outline_payload = fake_generator.calls[0]
    assert outline_call_type == "outline"
    assert outline_payload["trend_title"] == "参考文章 / 夜读关系实验室"
    assert outline_payload["topic_title"] == "先接住失望，再谈道理"
    assert outline_payload["topic_angle"] == "关系修复"
    assert outline_payload["source_type"] == "tracked_article"
    assert outline_payload["reference_article_hidden"] is True
    assert "reference_article_title" not in outline_payload
    assert "reference_article_author" not in outline_payload
    assert "reference_article_source_name" not in outline_payload
    assert "reference_article_summary" not in outline_payload
    assert "reference_article_structure_notes" not in outline_payload
    assert "reference_article_tags" not in outline_payload
    assert outline_payload["strategy_card"]["version"] == 1
    assert outline_payload["problem_brief"]["version"] == 1

    draft_calls = [payload for call_type, payload in fake_generator.calls if call_type == "draft"]
    assert draft_calls
    draft_payload = draft_calls[0]
    assert draft_payload["source_type"] == "tracked_article"
    assert draft_payload["reference_article_hidden"] is True
    assert "reference_article_title" not in draft_payload
    assert "reference_article_summary" not in draft_payload
    assert "reference_article_structure_notes" not in draft_payload
    assert "reference_article_tags" not in draft_payload
    assert draft_payload["strategy_card"]["version"] == 1
    assert draft_payload["problem_brief"]["version"] == 1
    if len(draft_calls) > 1:
        assert draft_calls[1]["polish_instruction"]


def test_generate_draft_persists_responsibility_shelter_final_guard_cleanup(monkeypatch) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {
                "hook": "手机刚震了一下，你还没接起来。",
                "outline_body": "1. 家里的事先排顺序\n2. 责任落在日常安排里\n3. 认真生活慢慢换来踏实",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {
                "title": "肩上有责任的人，心里也要留一盏灯",
                "body_markdown": (
                    "手机刚震了一下，你还没接起来，心里已经开始替家里排顺序。\n\n"
                    "很多成年人先把家里的事理顺，是因为心里有一个很清楚的顺序：先让家稳住，再谈自己。\n\n"
                    "你会因为他们，愿意少买一件自己喜欢的东西，愿意把不容易压一压，愿意在最累的时候还是把话说得温和一点，把事情办得妥当一点。不是不辛苦，是知道自己停不下来。\n\n"
                    "日子就是这样一点点被理顺的。看上去不起眼，甚至没有多少值得夸耀的时刻，但正是这些重复的判断和安排，撑住了一家人的基本秩序。\n\n"
                    "很多人以为，责任重的人一定很有力量。其实不是。责任最重的地方，往往只是心里一直装着想守护的人。\n\n"
                    "可真正成熟的承担，不是把自己彻底烧干。人也需要给自己留一盏灯。"
                ),
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("assets", payload))
            return {
                "recommended_title": "把家里日子撑稳的人，也该被好好心疼",
                "title_options": ["把家里日子撑稳的人，也该被好好心疼"],
                "cover_prompt": "16:9 微信封面，不要聊天界面，在看手机。金句：责任不是把自己活成钢铁，而是明知道不容易，仍愿意把灯留在家里。",
                "cover_copy": "辛苦没有白扛，都在接住生活的风浪",
                "social_teaser": "很多成年人真正累的，是一路撑着把难关熬过去。",
                "social_teaser_options": ["你是在一点点把所爱之人的生活托稳。"],
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("publish_package", payload))
            draft_body = str(payload["draft"]["body_markdown"])
            for forbidden in (
                "手机刚震",
                "身体会记账",
                "情绪硬吞",
                "身体先报警",
                "一个人先顶着",
            ):
                assert forbidden not in draft_body
            assert "也该给自己留一点余地" in draft_body
            return {
                "abstract": "成年人的不容易，常常不是因为想歇一歇，而是因为一直在替家人把日子稳住。读到最后你会发现，那些没说出口的认真，真的在一点点变成家里的安稳。",
                "tags": ["中年责任", "家庭安稳"],
                "editor_note": "写清楚来电背后催款、问候、托付和等待。点出“肩上有责任的人”为什么连沉默都要计算分寸。",
                "publish_title": "肩上扛着责任的人，别再硬撑",
                "publish_lead": "成年人的累，很多时候不是难，而是一直在替家人稳住日子。",
                "intro_options": ["手机一响，成年人第一反应不是自己，而是先在心里把家里的事排个顺序。"],
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_positive_payoff", lambda **_: False, raising=False)

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "responsibility-save-guard-source",
            "source_name": "手动录入",
            "title": "中年人的那句没事，背后都是责任",
            "url": "https://example.com/responsibility-save-guard-source",
            "author": "未知",
            "summary": "从中年人把压力先放下、把家里安排稳写起，落点是责任被看见、日子更踏实。",
            "body_markdown": (
                "中年人的世界，半生风雨，半生奔波。电话的那头，是父母，是孩子，是账单。\n\n"
                "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；慢慢长大的孩子，拥有了对生活说不的底气。\n\n"
                "你熬过的每一个黑夜，都在为身边所爱之人撑起一片晴空。"
            ),
            "structure_notes": "现实压力起手，转到责任的意义，再回到家里的踏实。",
            "tags": ["中年责任", "家庭安稳"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/responsibility-save-guard-source/to-topic",
        json={
            "slug": "responsibility-save-guard-topic",
            "title": "肩上有责任的人，心里也要留一盏灯",
            "angle": "从手机亮起时先想家里的安排切入，写责任怎样把日子慢慢托稳。",
        },
    )
    assert create_topic.status_code == 201

    create_project = client.post(
        "/api/topics/responsibility-save-guard-topic/create-project",
        json={
            "slug": "responsibility-save-guard-project",
            "title": "责任终稿清洗写库项目",
            "owner": "editorial",
        },
    )
    assert create_project.status_code == 201
    assert client.post("/api/projects/responsibility-save-guard-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/responsibility-save-guard-project/adopt-strategy-card/1").status_code == 200
    assert client.post("/api/projects/responsibility-save-guard-project/generate-outline").status_code == 201

    draft_response = client.post("/api/projects/responsibility-save-guard-project/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()
    persisted = client.get("/api/projects/responsibility-save-guard-project/versions").json()["drafts"][0]

    for body in (draft["body_markdown"], persisted["body_markdown"]):
        for forbidden in (
            "不是不辛苦，是",
            "撑住了一家人的基本秩序",
            "不是把自己彻底烧干",
            "其实不是。",
        ):
            assert forbidden not in body
        assert "托住了一家人的基本秩序" in body
        assert workbench.extract_not_ab_skeletons(body) == []
        assert workbench.evaluate_ai_flavor_risk(
            title="肩上有责任的人，心里也要留一盏灯",
            body_markdown=body,
        ).score == 0

    assert any(call_type == "draft" for call_type, _ in fake_generator.calls)
    assets_response = client.post("/api/projects/responsibility-save-guard-project/generate-assets")
    assert assets_response.status_code == 201
    assets = assets_response.json()

    legacy_dirty_body = (
        "手机刚震了一下，你还没接起来，心里已经开始替家里排顺序。\n\n"
        "你把日历翻来翻去，把能挪的时间先挪出来，把能缓一口的事先记在纸上。最难的常常在这里：每一件事都在等你给个说法。可身体会记账。\n\n"
        "睡眠变浅、心里的不容易不说、情绪硬吞、身体先报警，这些都是一个人先顶着留下来的痕迹。"
    )
    with workbench._get_connection() as connection:
        connection.execute(
            "UPDATE drafts SET body_markdown = ?, word_count = ? WHERE project_slug = ? AND version = ?",
            (
                legacy_dirty_body,
                len(legacy_dirty_body),
                "responsibility-save-guard-project",
                draft["version"],
            ),
        )
        connection.commit()

    package_response = client.post("/api/projects/responsibility-save-guard-project/build-publish-package")
    assert package_response.status_code == 201
    package = package_response.json()
    markdown_body = Path(package["markdown_path"]).read_text(encoding="utf-8")

    combined_delivery_text = "\n".join(
        [
            assets["recommended_title"],
            assets["cover_prompt"],
            assets["cover_copy"],
            assets["social_teaser"],
            *assets.get("title_options", []),
            *assets.get("social_teaser_options", []),
            package["abstract"],
            package["publish_title"],
            package["publish_lead"],
            package["editor_note"],
            *package.get("intro_options", []),
            markdown_body,
        ]
    )
    for forbidden in (
        "撑稳",
        "硬撑",
        "扛着责任",
        "真正累的",
        "一路撑着",
        "把难关熬过去",
        "所爱之人",
        "辛苦没有白扛",
        "风浪",
        "金句",
        "写清楚",
        "点出",
        "不是因为想歇一歇",
        "不是难，而是",
        "而是因为一直",
        "而是一直",
        "手机一响",
        "手机刚震",
        "手机屏幕亮起",
        "身体会记账",
        "情绪硬吞",
        "身体先报警",
        "一个人先顶着",
    ):
        assert forbidden not in combined_delivery_text
    assert "托稳" in combined_delivery_text
    assert any(
        fragment in combined_delivery_text
        for fragment in (
            "把日子往前托的人，也别忘了给自己留一点光。",
            "把家撑住的人，也别忘了照顾那个总说“我没事”的自己。",
            "你替一家人多想的那几步，最后都会落成家里的踏实。",
            "把日子往前托的人，也该被日子温柔托住。",
            "给自己留一点光。",
        )
    )
    assert "也该给自己留一点余地" in markdown_body
    assert any(call_type == "assets" for call_type, _ in fake_generator.calls)
    assert any(call_type == "publish_package" for call_type, _ in fake_generator.calls)


def test_generate_strategy_package_for_everyday_warmth_tracked_article_stays_on_small_things_lane() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "small-things-strategy-article",
            "source_name": "手动录入",
            "title": "一生最重要的事，不是大事",
            "url": "https://example.com/small-things-strategy-article",
            "author": "未知",
            "summary": "文章把“做大事”的社会期待，与人在生活放慢后重新确认的日常幸福放在一起比较，重点不是关系善后，而是成就祛魅之后，小事和陪伴怎样重新显出分量。",
            "body_markdown": (
                "年轻时，我们都想改变世界，觉得人生一定要轰轰烈烈，要做大事，要出人头地。可走过半生，才发现，这世界再喧嚣，最重要的事，不过是活在人间烟火里，陪在爱的人身边。\n\n"
                "朋友是上市公司的高管，前些年，没日没夜地加班，最近因为身体不舒服做了个手术，在家休养。\n\n"
                "他终于在日落之前，陪爱人做了一顿晚饭。他久违地去接孩子放学。那一刻，他突然觉得，那些拼了命追求的大事，好像瞬间祛魅了。\n\n"
                "真正让人眼眶发热的，可能从来不是升职加薪、远大抱负，而是这些不起眼的、细碎的、平淡的日常瞬间。宏大叙事属于时代，而一碗热汤、一盏夜灯、一句晚安，才属于你我。"
            ),
            "structure_notes": "开头先摆出追逐成就的大命题，中段借停下来后的家庭陪伴完成价值转向，结尾回到普通日常和陪伴。",
            "tags": ["日常治愈", "家庭陪伴", "价值重估"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/small-things-strategy-article/to-topic",
        json={
            "slug": "small-things-strategy-topic",
            "title": "当头衔开始失重，晚饭、回家和一句晚安为什么反而变贵了",
            "angle": "从头衔满足感会递减切入，拆开人在长期向上奔跑后，为什么会重新把晚饭、回家、陪父母和一句晚安看得更重。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "small-things-strategy-project", "title": "小事回归策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/small-things-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "everyday_warmth_return"
    combined = "\n".join(
        [
            payload["problem_brief"]["clarified_problem"],
            payload["problem_brief"]["observed_phenomenon"],
            payload["problem_brief"]["writing_goal"],
            payload["problem_brief"]["feedback_entry"],
            payload["strategy_card"]["point_of_view"],
            payload["strategy_card"]["conflict_frame"],
            payload["strategy_card"]["emotional_path"],
            payload["strategy_card"]["opening_move"],
            payload["strategy_card"]["body_shift"],
            payload["strategy_card"]["ending_move"],
        ]
    )
    constraints_text = "\n".join(payload["strategy_card"]["expression_constraints"])

    assert "祛魅" in combined
    assert "陪伴" in combined
    assert "家人平安" in combined or "知己仍在" in combined or "有人可回" in combined
    assert "低声量联系" not in combined
    assert "长期体谅" not in combined
    assert "继续等你的心气" not in combined
    assert "关系坏在冲突" not in combined
    assert "才发现" not in combined
    assert "长期体谅" in constraints_text
    assert "吃饭、散步" not in payload["problem_brief"]["problem_statement_markdown"]
    assert "陪伴家人的具体场景" not in payload["problem_brief"]["problem_statement_markdown"]
    assert "伴侣、孩子、父母" not in payload["problem_brief"]["problem_statement_markdown"]


def test_generate_strategy_package_for_responsibility_shelter_tracked_article_exposes_responsibility_mode() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "responsibility-shelter-strategy-article",
            "source_name": "手动录入",
            "title": "万般辛苦，皆为序章，人间安稳，终会如愿",
            "url": "https://example.com/responsibility-shelter-strategy-article",
            "author": "未知",
            "summary": "文章围绕成年人把辛苦和委屈先往后收、把父母孩子伴侣的安稳顶在前面展开，重点不在控诉生活难，而在那些认真撑住的日子后来怎样变成一个家的底气。",
            "body_markdown": (
                "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
                "白天的时候，你是父母的拐杖，是孩子的雨伞，是伴侣的靠山。你熬过的每一个黑夜，都在为身边所爱之人撑起一片晴空。\n\n"
                "人间安稳，从来不是没有风雨，而是风雨再大，你知道家在哪里，路再难走，你知道有人在爱你。"
            ),
            "structure_notes": "先从一句“没事，有我”和电话账单这些现实重量切入，中段写责任怎样让人把自己往后收，结尾落回家里安稳、有人被护住和这些辛苦没有白熬。",
            "tags": ["责任托家", "中年责任", "家庭安稳"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/responsibility-shelter-strategy-article/to-topic",
        json={
            "slug": "responsibility-shelter-strategy-topic",
            "title": "肩上有责任的人，心里也要留一盏灯",
            "angle": "从家里临时有事、自己先把顺序理清切入，写责任怎样变成一家人的安稳，也写那个一直认真托住日子的人为什么值得被回温。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "responsibility-shelter-strategy-project", "title": "责任托家策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/responsibility-shelter-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "responsibility_shelter"
    combined = "\n".join(
        [
            payload["problem_brief"]["clarified_problem"],
            payload["problem_brief"]["observed_phenomenon"],
            payload["problem_brief"]["writing_goal"],
            payload["strategy_card"]["hook_trigger"],
            payload["strategy_card"]["progression_drive"],
            payload["strategy_card"]["packaging_focus"],
            payload["strategy_card"]["ending_move"],
        ]
    )

    assert "家里" in combined
    assert "安稳" in combined or "踏实" in combined
    assert "更大目标" not in combined
    assert "简单快乐" not in combined
    assert "责任托家回温推进" in payload["strategy_card"]["strategy_markdown"]


def test_generate_strategy_package_for_everyday_warmth_tracked_article_uses_generated_topic_lane(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("topic", payload))
            return {
                "title": "总把回家往后排的人，为什么更容易突然觉得一切都没意思",
                "angle": "从“总有更重要的事”这套排序切入，拆开成就感退潮后为什么会先出现空心感，以及晚饭、陪伴、晚安如何重新成为一个人的情绪托底。",
            }

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "small-things-generated-strategy-article",
            "source_name": "手动录入",
            "title": "一生最重要的事，不是大事",
            "url": "https://example.com/small-things-generated-strategy-article",
            "author": "未知",
            "summary": "文章把“做大事”的社会期待，与人在生活放慢后重新确认的日常幸福放在一起比较，重点不是关系善后，也不是空心感自救，而是成就祛魅之后，小事和陪伴怎样重新显出分量。",
            "body_markdown": (
                "年轻时，我们都想改变世界，觉得人生一定要轰轰烈烈，要做大事，要出人头地。可走过半生，才发现，这世界再喧嚣，最重要的事，不过是活在人间烟火里，陪在爱的人身边。\n\n"
                "朋友是上市公司的高管，前些年，没日没夜地加班，最近因为身体不舒服做了个手术，在家休养。\n\n"
                "他终于在日落之前，陪爱人做了一顿晚饭。他久违地去接孩子放学。那一刻，他突然觉得，那些拼了命追求的大事，好像瞬间祛魅了。\n\n"
                "真正让人眼眶发热的，可能从来不是升职加薪、远大抱负，而是这些不起眼的、细碎的、平淡的日常瞬间。宏大叙事属于时代，而一碗热汤、一盏夜灯、一句晚安，才属于你我。"
            ),
            "structure_notes": "开头先摆出追逐成就的大命题，中段借停下来后的家庭陪伴完成价值转向，结尾回到普通日常和陪伴。",
            "tags": ["日常治愈", "家庭陪伴", "价值重估"],
        },
    )
    assert create_article.status_code == 201

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    topic_response = client.post("/api/tracked-articles/small-things-generated-strategy-article/generate-topic")
    assert topic_response.status_code == 201
    topic_payload = topic_response.json()
    assert "没意思" not in topic_payload["title"]
    assert "空心感" not in topic_payload["angle"]

    create_project = client.post(
        f"/api/topics/{topic_payload['slug']}/create-project",
        json={"slug": "small-things-generated-strategy-project", "title": "小事回归自动出题策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/small-things-generated-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "everyday_warmth_return"
    combined = "\n".join(
        [
            topic_payload["title"],
            topic_payload["angle"],
            payload["problem_brief"]["clarified_problem"],
            payload["problem_brief"]["observed_phenomenon"],
            payload["problem_brief"]["writing_goal"],
            payload["strategy_card"]["point_of_view"],
            payload["strategy_card"]["conflict_frame"],
            payload["strategy_card"]["emotional_path"],
            payload["strategy_card"]["ending_move"],
        ]
    )

    assert "祛魅" in combined
    assert "陪伴" in combined
    assert "陪伴" in combined or "日常" in combined or "祛魅" in combined
    assert "家人平安" in combined or "知己仍在" in combined or "有人可回" in combined
    assert "没意思" not in combined
    assert "空心感" not in combined
    assert "情绪托底" not in combined
    assert "才发现" not in combined
    assert "晚饭、陪伴、晚安" not in payload["problem_brief"]["problem_statement_markdown"]


def test_generate_strategy_package_for_resilience_tracked_article_stays_on_reconstruction_lane() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "jiang-yuyan-strategy-article",
            "source_name": "手动录入",
            "title": "一个人最大的底气，不是美貌，也不是金钱，而是韧性",
            "url": "https://example.com/jiang-yuyan-strategy-article",
            "author": "未知",
            "summary": "文章以残奥会冠军蒋裕燕的人生为例，重点写命运重击、长期疼痛、泳池训练和不被定义后的重建，而不是女性把自己放最后的情绪照顾。",
            "body_markdown": (
                "3岁那年，一场车祸无情夺走了蒋裕燕的右臂与右腿。从3岁到8岁，她每一年都要被迫走上手术台，接受锯掉新生骨头的剧痛。\n\n"
                "为了康复，她走进了泳池。没有右臂维持平衡，没有右腿蹬水发力，她每一次划水都要比常人多划11下。\n\n"
                "疲惫与酸痛，肩伤反复发作、背痛缠扰不休、炎症如影随形，可她从未停下前进的脚步。命运以痛吻她，她却在破碎中重建自己，不让任何人定义她能做的事情。"
            ),
            "structure_notes": "先写命运重击和手术台，再转到泳池里的训练硬撑，结尾回到不被定义和韧性重建。",
            "tags": ["韧性", "残奥冠军", "命运重击", "训练", "不被定义"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/jiang-yuyan-strategy-article/to-topic",
        json={
            "slug": "jiang-yuyan-strategy-topic",
            "title": "手术台下来以后，一个人是怎么靠重复训练把自己重新托住的",
            "angle": "从伤痛、复健到泳池里多划出的每一下，拆开一个人在身体受限之后，怎样靠持续行动慢慢重建意志，而不把低谷当成自我定义。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "jiang-yuyan-strategy-project", "title": "韧性重建策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/jiang-yuyan-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "resilience_reconstruction"
    combined = "\n".join(
        [
            payload["problem_brief"]["clarified_problem"],
            payload["problem_brief"]["observed_phenomenon"],
            payload["problem_brief"]["writing_goal"],
            payload["problem_brief"]["feedback_entry"],
            payload["strategy_card"]["point_of_view"],
            payload["strategy_card"]["conflict_frame"],
            payload["strategy_card"]["emotional_path"],
            payload["strategy_card"]["opening_move"],
            payload["strategy_card"]["body_shift"],
            payload["strategy_card"]["ending_move"],
        ]
    )
    constraints_text = "\n".join(payload["strategy_card"]["expression_constraints"])

    assert "命运" in combined
    assert "训练" in combined
    assert "被定义" in combined or "自我定义" in combined or "重建" in combined
    assert "把自己排到最后" not in combined
    assert "照顾自己" not in combined
    assert "稳住自己" not in combined
    assert "照顾自己" in constraints_text
    assert "术后恢复" in constraints_text


def test_generate_strategy_package_for_regret_reference_tracked_article_stays_on_emotional_engine_lane() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "regret-reference-strategy-article",
            "source_name": "手动录入",
            "title": "有些遗憾，不是忘不掉，而是总忍不住回头假设",
            "url": "https://example.com/regret-reference-strategy-article",
            "author": "未知",
            "summary": "文章围绕人为什么会被未完成的告别和没走成的路反复牵住，重点是遗憾、回头设想和把心重新收回今天，不是把普通错过抬成人生终局问题。",
            "body_markdown": (
                "如果当初那班车没有开走，她也许不会隔着这么多年，还在心里追问那天要是再晚一点离开，会不会不一样。\n\n"
                "后来她才发现，人真正困住自己的，不一定是那次错过本身，而是把所有没走成的路都拿回来反复比较。\n\n"
                "旧裙子也好，旧合影也好，真正需要放下的不是一个物件，而是总想替过去改写结局的那股劲。"
            ),
            "structure_notes": "开头先给如果当初的回头假设，中段拆开人为什么会被未发生的另一种可能牵住，结尾回到如何把遗憾安放回今天。",
            "tags": ["遗憾", "回头", "释怀", "错过"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/regret-reference-strategy-article/to-topic",
        json={
            "slug": "regret-reference-strategy-topic",
            "title": "总想替过去改写结局的人，为什么更难把心收回今天",
            "angle": "从如果当初这类回头假设切入，拆开人为什么会被没说完的话和没走成的路持续牵住，以及真正的前行为什么不是否认遗憾，而是重新安放它。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "regret-reference-strategy-project", "title": "遗憾回望策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/regret-reference-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "emotional_engine_direct"
    constraints_text = "\n".join(payload["strategy_card"]["expression_constraints"])

    assert "抽象反思" in constraints_text


def test_generate_strategy_package_for_regret_reference_with_pressureish_topic_copy_stays_on_emotional_engine_lane() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "regret-reference-pressureish-topic-article",
            "source_name": "手动录入",
            "title": "遗忘再长，也长不过明天和以后",
            "url": "https://example.com/regret-reference-pressureish-topic-article",
            "author": "未知",
            "summary": "文章借邻居老人反复惦记一件旧裙子的细节，讨论人为什么会长期困在‘如果当初’的设想里。重点不在劝人强行忘记，而在提醒读者承认遗憾存在，同时把注意力慢慢挪回仍在继续的当下生活。",
            "body_markdown": (
                "傍晚下楼扔垃圾，撞见邻居阿婆正蹲在垃圾桶旁，对着一袋旧衣物发呆。\n\n"
                "原来我们都一样，总爱攥着过去的遗憾不放，盯着没走成的路反复设想，却忘了脚下的路，从来都是朝前延伸的。\n\n"
                "你看，放下从来都不是遗忘，而是给心找一个更轻盈的去处。"
            ),
            "structure_notes": "开头从生活场景切入，用旧裙子的细节带出对过往遗憾的停留；中段扩展到普遍心理；结尾回到阿婆买新裙子的后续，落到放下不是遗忘，而是继续生活。",
            "analysis_theme": "这篇文章真正想谈的是：人该怎样和已经无法更改的遗憾相处，才能不再被过去持续消耗。",
            "analysis_core_conflict": "一边是人对错过的人、事、选择反复设想、迟迟不肯松手；另一边是现实已经无法回退，继续沉溺只会占用当下和未来的生活感受。",
            "analysis_emotional_exit": "不必否认曾经在意过，也不必逼自己立刻忘掉，而是允许过去被安放，再把心力转回新的日常、新的关系和新的期待里。",
            "analysis_structure_mode": "emotional_engine_direct",
            "analysis_opening_pattern": "从生活接口里的偶遇场景起笔，以邻居阿婆对旧衣物发呆的细节切入遗憾与回头心理。",
            "analysis_do_not_turn_into": "不要改写成单纯鼓吹立刻断舍离、彻底忘掉过去的励志口号文。",
            "tags": ["遗憾", "回头", "释怀", "错过"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/regret-reference-pressureish-topic-article/to-topic",
        json={
            "slug": "regret-reference-pressureish-topic-topic",
            "title": "你反复回想的那件事，正在悄悄占用今天",
            "angle": "从‘每天醒来还在接着想昨天那件事’的身体提醒切入，拆开遗憾为何会被大脑反复续播，以及怎样把心力从无效复盘挪回正在发生的生活。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "regret-reference-pressureish-topic-project", "title": "遗憾释怀误伤回归测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/regret-reference-pressureish-topic-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "emotional_engine_direct"


def test_generate_strategy_package_for_self_reliance_tracked_article_uses_self_reliance_lane() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "self-reliance-strategy-article",
            "source_name": "手动录入",
            "title": "即使没有帮助，也要学会自救自渡",
            "url": "https://example.com/self-reliance-strategy-article",
            "author": "未知",
            "summary": "文章从想找人倾诉却发现身边人也自顾不暇的场景切入，写成年人在低谷里对外求助常常得不到及时回应，于是逐渐学会收起委屈、转向自我消化和自我修复。核心落点不是拒绝他人，而是提醒人在不被接住的时候，也要有把自己托起来的能力。",
            "body_markdown": (
                "相信你也有过这样的时刻：心情不好的时候想找朋友倾诉，却发现朋友也愁眉不展。\n\n"
                "只有向内求，才能自我疗愈，生生不息。只有靠自己，你才能有所顿悟、有所收获、有所改变。\n\n"
                "即使没有帮助，也不会孤立无援，而是能够自救自渡。"
            ),
            "structure_notes": "先写想倾诉却发现别人也各自承压的现实处境，中段再拆为什么外求未必总能接住人，结尾回到向内稳住、自救自渡和慢慢把自己托起来。",
            "analysis_theme": "文章真正讨论的是：成年人在困境中如何从依赖外界安慰，转向建立内在的自我支撑与恢复能力。",
            "analysis_core_conflict": "想向外寻求安慰和帮助，但现实里身边的人也各自承压，外部支撑不稳定，只能重新把依靠收回到自己身上。",
            "analysis_emotional_exit": "把读者从无助和失望带到一种更稳的状态：接受帮助未必及时，但自己也有能力慢慢把日子撑过去。",
            "analysis_structure_mode": "emotional_engine_direct",
            "analysis_opening_pattern": "从生活接口和现实压力切入，先写想倾诉却无人可依的具体处境。",
            "analysis_do_not_turn_into": "不要写成鼓励一味硬扛、拒绝求助，或把自我成长说成空泛的鸡汤式宣言。",
            "tags": ["自我疗愈", "情绪自救", "成年人压力", "低谷时刻", "自我支撑"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/self-reliance-strategy-article/to-topic",
        json={
            "slug": "self-reliance-strategy-topic",
            "title": "低谷里，真正撑住人的，是回稳能力",
            "angle": "当外部回应不稳定时，文章拆的是人怎样把失落感转成回稳步骤：先稳住身体和判断，再慢慢把自己托起来。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "self-reliance-strategy-project-app", "title": "自救自渡策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/self-reliance-strategy-project-app/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "self_reliance_inward_support"
    assert "承压时先乱了顺序" in payload["problem_brief"]["writing_goal"]
    assert "具体判断、动作或选择" in payload["problem_brief"]["writing_goal"]
    assert "把今天过稳" in payload["strategy_card"]["emotional_path"]
    assert "越想解释越说不出口" not in payload["strategy_card"]["body_shift"]


def test_generate_strategy_package_for_response_priority_tracked_article_uses_response_priority_lane() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "response-priority-strategy-article",
            "source_name": "手动录入",
            "title": "没时间，不一定是真的没时间",
            "url": "https://example.com/response-priority-strategy-article",
            "author": "未知",
            "summary": "文章借日常联系里的“没时间”现象，讨论一段关系里真实的优先级排序。核心判断是：多数迟迟不回应并非真的抽不出空，而是投入意愿不足，时间分配往往比语言更能说明在乎程度。",
            "body_markdown": (
                "听过一句话：“红灯30秒，我喝了一口水，拍了张照片，回了条消息，连上蓝牙，放了一首喜欢的歌，所以你告诉我，什么是没时间？”\n\n"
                "真正的原因可能是，因为我们不够重要，所以对方漫不经心，爱搭不理。人对在乎的人，永远都有时间。\n\n"
                "没时间，是因为你不在他心里，或者顺序没那么优先。一个人的时间在哪儿，他的心就在哪儿。"
            ),
            "structure_notes": "开头借红灯30秒的细节切入，中段拆“忙”和“在乎”并不等价，结尾落到时间分配如何显出真实顺序。",
            "tags": ["关系优先级", "回应顺序", "时间分配"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/response-priority-strategy-article/to-topic",
        json={
            "slug": "response-priority-strategy-topic",
            "title": "不是没时间，很多时候，是你根本没被排进他的优先级",
            "angle": "从“没时间”为什么很多时候说的不是日程，而是顺序切入，写时间分配和回应动作怎样显出一个人的真实在乎程度。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "response-priority-strategy-project", "title": "回应优先级策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/response-priority-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "response_priority"
    combined = "\n".join(
        [
            payload["problem_brief"]["clarified_problem"],
            payload["problem_brief"]["observed_phenomenon"],
            payload["problem_brief"]["writing_goal"],
            payload["strategy_card"]["point_of_view"],
            payload["strategy_card"]["conflict_frame"],
            payload["strategy_card"]["emotional_path"],
            payload["strategy_card"]["opening_move"],
            payload["strategy_card"]["body_shift"],
            payload["strategy_card"]["ending_move"],
        ]
    )

    assert "没时间" in combined or "顺序" in combined or "时间分配" in combined
    assert "在乎程度" in combined or "优先级" in combined or "时间投向" in combined
    assert "善后" not in combined
    assert "吵完" not in combined
    assert "修复" not in combined
    assert "位置感" in combined or "真正愿意回应的人" in combined or "把时间留给" in combined


def test_generate_strategy_package_for_comment_followup_article_stays_on_response_priority_lane() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "comment-followup-strategy-article",
            "source_name": "手动录入",
            "title": "真正关心你的人，会停下来读懂你没说完的话",
            "url": "https://example.com/comment-followup-strategy-article",
            "author": "未知",
            "summary": "文章借点赞和评论的差别，讨论什么才算真正把注意力和心力放在你身上。重点不在热闹，而在有没有人愿意停下来、多问一句、接住你没说完的话。",
            "body_markdown": (
                "朋友圈里，是给你点赞的人更在意你，还是给你评论的人更在意你？\n\n"
                "而评论，却需要停下来，读懂你的言外之意，斟酌字句，再留下专属的痕迹。\n\n"
                "真正关心你的人，愿意努力去读懂你的每一份脆弱。\n\n"
                "真正关心你的人，是哪怕相隔千里，也能透过你的一句“我没事”，听出你心底的“我有点累”。"
            ),
            "structure_notes": "开头先拆点赞和评论的差别，中段写表层互动和真正关心之间的落差，结尾落到谁会回来追问、谁会接住你没说完的话。",
            "tags": ["回应差别", "真正在意", "追问", "接住情绪"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/comment-followup-strategy-article/to-topic",
        json={
            "slug": "comment-followup-strategy-topic",
            "title": "你轻轻带过的话，真正在意的人会再问一句",
            "angle": "从点赞、评论和一句“我没事”背后的分量差别切入，写为什么轻互动很多，人却还是会悬着；也写真正的关心，往往藏在一句追问、一次补问和被认真听懂的那一下。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "comment-followup-strategy-project", "title": "评论追问策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/comment-followup-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "response_priority"
    combined = "\n".join(
        [
            payload["problem_brief"]["clarified_problem"],
            payload["problem_brief"]["observed_phenomenon"],
            payload["problem_brief"]["writing_goal"],
            payload["strategy_card"]["point_of_view"],
            payload["strategy_card"]["conflict_frame"],
            payload["strategy_card"]["emotional_path"],
            payload["strategy_card"]["opening_move"],
            payload["strategy_card"]["body_shift"],
            payload["strategy_card"]["ending_move"],
        ]
    )

    assert "追问" in combined or "评论" in combined or "读懂" in combined
    assert "安稳" in combined or "理解" in combined or "珍惜" in combined
    assert "把自己排到最后" not in combined
    assert "失去后才懂得拥有" not in combined
    assert "没时间" not in combined
    assert "红灯30秒" not in combined
    assert "优先级" not in combined
    assert "位置感" not in combined


def test_generate_strategy_package_for_supportive_appreciation_tracked_article_stays_on_supportive_lane() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "supportive-appreciation-strategy-article",
            "source_name": "手动录入",
            "title": "如果你身边有这样一个心软的人，请一定要牵紧他的手",
            "url": "https://example.com/supportive-appreciation-strategy-article",
            "author": "未知",
            "summary": "文章重点不是谁在关系里耗空自己，而是心软为什么常被误解，以及那些明明拎得清、却还是愿意包容和体谅别人的人，为什么最值得被珍惜。",
            "body_markdown": (
                "有一种人，习惯了燃烧自己，去照亮别人。你对他好，他会对你更好。\n\n"
                "心软的人并不傻，他们的心里比谁都拎得清。不去计较，是因为心里在乎，不想与爱的人争辩输赢、对错和得失。\n\n"
                "那些愿意包容你的人，一定很爱你。如果你身边有这样一个心软的人，请你一定要牵紧他的手。"
            ),
            "structure_notes": "先写心软的人总会先替别人着想，再拆这种柔软为什么常被误读，结尾回到这样的人最值得被珍惜。",
            "analysis_theme": "这篇文章真正想讨论的是：很多人把柔软误读成好说话，却忽略了那些明明拎得清、却还是愿意包容和体谅别人的人，其实最值得被认真珍惜。",
            "analysis_core_conflict": "一边是心软的人总在关系里先让一步、先顾及别人感受；另一边是旁人把这种包容误认成没底线、好说话，忽略了它背后的分寸感和珍贵。",
            "analysis_emotional_exit": "让读者重新看见：心软不是傻，真正稀缺的是那份明明看得清，却还是愿意把温柔给出来的分量。",
            "analysis_structure_mode": "supportive_appreciation",
            "analysis_opening_pattern": "先从心软的人总在关系里先让一步的常见处境切入，再慢慢提判断。",
            "analysis_do_not_turn_into": "不要改写成谁在关系里耗空自己、谁总在善后或谁该先照顾自己的诊断稿。",
            "tags": ["心软", "包容", "体谅", "值得珍惜"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/supportive-appreciation-strategy-article/to-topic",
        json={
            "slug": "supportive-appreciation-strategy-topic",
            "title": "那些明明拎得清、却还是愿意包容你的人，最值得被珍惜",
            "angle": "从人为什么总把心软误认成好说话切入，写那些明明拎得清、却还是愿意体谅和包容别人的人，为什么反而最值得被认真珍惜。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "supportive-appreciation-strategy-project", "title": "心软珍惜策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/supportive-appreciation-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "supportive_appreciation"
    combined = "\n".join(
        [
            payload["problem_brief"]["clarified_problem"],
            payload["problem_brief"]["observed_phenomenon"],
            payload["problem_brief"]["writing_goal"],
            payload["problem_brief"]["feedback_entry"],
            payload["strategy_card"]["point_of_view"],
            payload["strategy_card"]["conflict_frame"],
            payload["strategy_card"]["emotional_path"],
            payload["strategy_card"]["opening_move"],
            payload["strategy_card"]["body_shift"],
            payload["strategy_card"]["ending_move"],
        ]
    )

    assert "柔软" in combined
    assert "珍惜" in combined
    assert "体谅" in combined or "包容" in combined
    assert "越稳越累" not in combined
    assert "失去自我" not in combined
    assert "把日子接回去" not in combined
    assert "收拾情绪" not in combined


def test_generate_strategy_package_for_self_worth_tracked_article_uses_self_worth_lane() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "self-worth-strategy-article",
            "source_name": "手动录入",
            "title": "把自己养贵一点，日子才能过好一点",
            "url": "https://example.com/self-worth-strategy-article",
            "author": "未知",
            "summary": "文章真正想讨论的是：很多轻慢并不是突然发生的，而是从一个人不断将就、不断放轻自己开始的。",
            "body_markdown": (
                "有一段话说得很好：你爱自己的程度，决定了谁能走进你的人生。\n\n"
                "你越将就，遇见的人就对你越随便；你越讲究，遇见的人对你越认真。\n\n"
                "所以，要学会把自己养贵一点。把门槛抬高一点，把标准收紧一点，把精力多用来喂养自己。"
            ),
            "structure_notes": "开头先从一句判断性引语立住前提，中段拆将就和贬值怎样慢慢发生，结尾回到尊重自己、抬高门槛和标准。",
            "analysis_theme": "这篇文章真正想讨论的是：别人怎么对你，很多时候都和你是否尊重自己、是否守住边界和标准紧密相关。",
            "analysis_core_conflict": "一边是人总怕失去、总想证明自己值得被爱，另一边是边界、标准和体面在一次次迁就里被让出去。",
            "analysis_emotional_exit": "把精力从无效关系里收回来，重新尊重自己、守住边界，让日子慢慢变稳、变体面。",
            "analysis_structure_mode": "emotional_engine_direct",
            "analysis_opening_pattern": "从一句带判断性的引语起笔，再落到现实里的将就接口。",
            "analysis_do_not_turn_into": "不要写成没时间回消息、谁先回头沟通或争吵后善后的关系表达稿。",
            "tags": ["自我价值", "边界", "标准", "体面"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/self-worth-strategy-article/to-topic",
        json={
            "slug": "self-worth-strategy-topic",
            "title": "把自己养贵一点，不是高傲，而是别再把自己一再放轻",
            "angle": "从一个人总说都可以、总先迁就、总怕让别人不高兴切入，写边界、标准和体面为什么会在一次次将就里慢慢变薄。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "self-worth-strategy-project", "title": "自我价值策略测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/self-worth-strategy-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "self_worth_rebuild"
    combined = "\n".join(
        [
            payload["problem_brief"]["clarified_problem"],
            payload["problem_brief"]["observed_phenomenon"],
            payload["problem_brief"]["writing_goal"],
            payload["problem_brief"]["feedback_entry"],
            payload["strategy_card"]["point_of_view"],
            payload["strategy_card"]["conflict_frame"],
            payload["strategy_card"]["emotional_path"],
            payload["strategy_card"]["body_shift"],
            payload["strategy_card"]["ending_move"],
        ]
    )

    assert "边界" in combined
    assert "标准" in combined
    assert "体面" in combined
    assert "尊重自己" in combined
    assert "顺序" not in combined
    assert "回消息" not in combined
    assert "善后" not in combined
    assert "吵架" not in combined


def test_generate_strategy_package_prefers_response_priority_signal_over_wrong_analysis_hint() -> None:
    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "response-priority-analysis-hint-mismatch",
            "source_name": "手动录入",
            "title": "没时间，不一定是真的没时间",
            "url": "https://example.com/response-priority-analysis-hint-mismatch",
            "author": "未知",
            "summary": "文章借日常联系里的“没时间”现象，讨论一段关系里真实的优先级排序。",
            "body_markdown": (
                "听过一句话：‘红灯30秒，我喝了一口水，拍了张照片，回了条消息。’\n\n"
                "人对在乎的人，永远都有时间。\n\n"
                "一个人的时间在哪儿，他的心就在哪儿。"
            ),
            "structure_notes": "开头借红灯30秒的细节切入，中段拆‘忙’和‘在乎’并不等价，结尾落到时间分配如何显出真实顺序。",
            "analysis_theme": "文章真正想讨论的是，关系中的时间分配会暴露一个人的在意程度和优先级。",
            "analysis_core_conflict": "表面上说忙，实际上是你总被排在后面。",
            "analysis_emotional_exit": "少替别人找理由，把时间收回到值得回应的人和自己身上。",
            "analysis_structure_mode": "pressure_interface_direct",
            "analysis_opening_pattern": "从红灯30秒的生活接口起笔。",
            "analysis_do_not_turn_into": "不要写成制造焦虑的情感审判文。",
            "tags": ["关系优先级", "回应顺序", "时间分配"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/response-priority-analysis-hint-mismatch/to-topic",
        json={
            "slug": "response-priority-analysis-hint-mismatch-topic",
            "title": "不是没时间，很多时候，是你根本没被排进他的优先级",
            "angle": "从‘没时间’为什么很多时候说的不是日程，而是顺序切入，写时间分配和回应动作怎样显出一个人的真实在乎程度。",
        },
    )
    assert create_topic.status_code == 201

    create_project = client.post(
        "/api/topics/response-priority-analysis-hint-mismatch-topic/create-project",
        json={"slug": "response-priority-analysis-hint-mismatch-project", "title": "回应优先级误判回拉测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/response-priority-analysis-hint-mismatch-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    payload = strategy_response.json()

    assert payload["strategy_card"]["structure_mode"] == "response_priority"


def test_enrich_tracked_article_metadata_resolves_wrong_response_priority_hint_before_persist(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "response-priority-enrich-hint-fix",
            "source_name": "手动录入",
            "title": "没时间，不一定是真的没时间",
            "url": "https://example.com/response-priority-enrich-hint-fix",
            "author": "",
            "summary": "",
            "body_markdown": (
                "听过一句话：‘红灯30秒，我喝了一口水，拍了张照片，回了条消息。’\n\n"
                "人对在乎的人，永远都有时间。\n\n"
                "一个人的时间在哪儿，他的心就在哪儿。"
            ),
            "structure_notes": "开头借红灯30秒切入，中段拆忙和在乎并不等价，结尾落到时间分配和优先级。",
            "tags": [],
        },
    )

    class FakeGenerator:
        def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "author": "",
                "summary": "文章借日常联系里的‘没时间’现象，讨论一段关系里真实的优先级排序。",
                "structure_notes": "开头借红灯30秒的细节切入，中段拆‘忙’和‘在乎’并不等价，结尾落到时间分配如何显出真实顺序。",
                "analysis_theme": "文章真正想讨论的是，关系中的时间分配会暴露一个人的在意程度和优先级。",
                "analysis_core_conflict": "表面上说忙，实际上是你总被排在后面。",
                "analysis_emotional_exit": "少替别人找理由，把时间收回到值得回应的人和自己身上。",
                "analysis_structure_mode": "pressure_interface_direct",
                "analysis_opening_pattern": "从红灯30秒的生活接口起笔。",
                "analysis_do_not_turn_into": "不要写成制造焦虑的情感审判文。",
                "tags": ["关系优先级", "回应顺序", "时间分配"],
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    enrich_response = client.post("/api/tracked-articles/response-priority-enrich-hint-fix/enrich-metadata")
    assert enrich_response.status_code == 200
    payload = enrich_response.json()
    assert payload["analysis_structure_mode"] == "response_priority"

    tracked_article = next(
        article for article in client.get("/api/tracked-articles").json() if article["slug"] == "response-priority-enrich-hint-fix"
    )
    assert tracked_article["analysis_structure_mode"] == "response_priority"


def test_enrich_tracked_article_metadata_resolves_withdrawn_aftercare_hint_before_persist(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "withdrawn-aftercare-enrich-hint-fix",
            "source_name": "手动录入",
            "title": "累的时候，最怕被最在乎的人推开",
            "url": "https://example.com/withdrawn-aftercare-enrich-hint-fix",
            "author": "",
            "summary": "",
            "body_markdown": (
                "有时候，会莫名其妙的感到累，不是身体上的累，而是心里的累。\n\n"
                "你可以不善言辞，但是当你爱的人红着眼站在你面前的时候，你只要给她一个拥抱就够了。\n\n"
                "哪有人会莫名其妙的闹情绪，只不过是有点累，只不过是想要在你肩膀上靠一会。\n\n"
                "当你在一个人最无助的时候选择推开他，下一次，他再也不会在你面前脆弱了。"
            ),
            "structure_notes": "开头从成年人被迫坚强、心累却说不出口的状态切入，中段转到关系里最需要的不是讲道理，而是被理解、被接住，结尾落在一次被推开后的后撤与沉默。",
            "tags": [],
        },
    )

    class FakeGenerator:
        def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "author": "",
                "summary": "文章借情绪透支和关系错位，讨论很多人不是不想说，而是在最需要被接住的时候被推开以后，慢慢收回了求助和示弱。",
                "structure_notes": "开头先写心累和硬撑，中段把重点转到亲密关系里对脆弱的误读，结尾落在被推开一次后的后撤与沉默。",
                "analysis_theme": "这篇文章真正想讨论的是：人在情绪低谷时，一段关系里最重要的不是讲道理，而是有没有把脆弱接住。",
                "analysis_core_conflict": "一个人在最想被接住、最需要关系托住的时候，另一方却把真实情绪误读成了闹脾气，结果不是问题被解决，而是关系里的求助通道失效。",
                "analysis_emotional_exit": "一个人在最需要你时被拒绝和推开，之后就会把求助和示弱收回来，再也不愿意在你面前脆弱。",
                "analysis_structure_mode": "pressure_interface_direct",
                "analysis_opening_pattern": "先从疲惫、想躲起来、被迫坚强的状态切入，再把重点转到关系里的情绪回应失位上。",
                "analysis_do_not_turn_into": "不要改写成一个人单独硬扛、自我强撑、自我疗伤，也不要写成冷冰冰地指责谁不够爱谁；重点是关系里最需要被接住时，情绪没有被接住。",
                "tags": ["亲密关系", "脆弱误读", "求助落空", "不再示弱"],
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    enrich_response = client.post("/api/tracked-articles/withdrawn-aftercare-enrich-hint-fix/enrich-metadata")
    assert enrich_response.status_code == 200
    payload = enrich_response.json()
    assert payload["analysis_structure_mode"] == "relationship_aftercare"

    tracked_article = next(
        article
        for article in client.get("/api/tracked-articles").json()
        if article["slug"] == "withdrawn-aftercare-enrich-hint-fix"
    )
    assert tracked_article["analysis_structure_mode"] == "relationship_aftercare"


def test_enrich_tracked_article_metadata_promotes_scene_first_from_body_before_persist(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "scene-first-enrich-hint-fix",
            "source_name": "手动录入",
            "title": "总有些话，卡在那个刚好能开口的时刻",
            "url": "https://example.com/scene-first-enrich-hint-fix",
            "author": "",
            "summary": "",
            "body_markdown": (
                "夜里十点，她听见钥匙转动，先把茶几上的药盒往里推了推。\n\n"
                "他弯腰换鞋，问了一句‘孩子睡了？’她点头，把那张揉皱的检查单重新压回杯子底下。\n\n"
                "第二天送孩子出门前，她又看见那张单子露出一角，想开口，最后只说了句‘路上慢点’。\n\n"
                "有些人不是不知道问题在那儿，而是每次走到那个场景里，就先把更重要的话往后放。\n\n"
                "拖久了，卡住的就不只是一次开口，而是整段关系里谁都习惯了避开真正该面对的东西。"
            ),
            "structure_notes": "",
            "tags": [],
        },
    )

    class FakeGenerator:
        def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "author": "",
                "summary": "文章重点不是先下结论，而是让读者先跟着一连串家庭现场慢慢走进去，再意识到真正卡住的是什么。",
                "structure_notes": "开头先让连续场景带路，中段再把迟迟开不了口这件事讲明白，不要一上来平铺观点。",
                "analysis_theme": "这篇文章真正想讨论的是：很多关系里的卡住，不是没有问题，而是总在那个该开口的现场里把更重要的话压后。",
                "analysis_core_conflict": "明明知道有事该说，可一回到那个具体场景里，人就会先把更要紧的话咽回去。",
                "analysis_emotional_exit": "先让人认出自己是怎么一步步错过开口时机的，后面才谈表达和面对。",
                "analysis_structure_mode": "emotional_engine_direct",
                "analysis_opening_pattern": "先从家里的连续现场切入，再慢慢提判断。",
                "analysis_do_not_turn_into": "不要一开头就把它写成抽象关系道理。",
                "tags": ["场景推进", "关系沉默", "开口时机"],
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    enrich_response = client.post("/api/tracked-articles/scene-first-enrich-hint-fix/enrich-metadata")
    assert enrich_response.status_code == 200
    payload = enrich_response.json()
    assert payload["analysis_structure_mode"] == "scene_first_progression"

    tracked_article = next(
        article for article in client.get("/api/tracked-articles").json() if article["slug"] == "scene-first-enrich-hint-fix"
    )
    assert tracked_article["analysis_structure_mode"] == "scene_first_progression"


def test_enrich_tracked_article_metadata_sanitizes_responsibility_shelter_before_persist(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "responsibility-shelter-live-metadata-cleanup",
            "source_name": "手动录入",
            "title": "万般辛苦，皆为序章，人间安稳，终会如愿",
            "url": "https://example.com/responsibility-shelter-live-metadata-cleanup",
            "author": "",
            "summary": "",
            "body_markdown": (
                "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
                "电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。\n\n"
                "直到你看见，渐渐老去的父母不必在医院的缴费窗口前踌躇，慢慢长大的孩子有了底气，"
                "伴侣也能在风雨来临时有一处温暖的屋檐庇护。\n\n"
                "人间安稳，从来不是没有风雨，而是风雨再大，你知道家在哪里。"
            ),
            "structure_notes": "",
            "tags": [],
        },
    )

    class FakeGenerator:
        def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "author": "",
                "summary": "文章把辛苦咽下去、沉默疲惫和硬扛压力写成成年人硬撑后的家里安稳。",
                "structure_notes": "先写没事，有我和那一刻的重压，再写万般辛苦怎样换来人间安稳。",
                "analysis_theme": "这篇文章真正想讨论的是：成年人硬撑时，怎样把苦咽下去并换来人间安稳。",
                "analysis_core_conflict": "一个人长期硬扛、咬牙、孤撑，容易把责任写成苦难必有回报。",
                "analysis_emotional_exit": "不是没有风雨，而是你会发现，硬撑以后家里终于有了人间安稳。",
                "analysis_structure_mode": "emotional_engine_direct",
                "analysis_opening_pattern": "从一句“我没事”和喉咙发紧起笔。",
                "analysis_hook_trigger": "那一刻，读者认出自己撑不撑得住、把辛苦咽下去的样子。",
                "analysis_progression_drive": "靠一路忍着、扛着的误判推动，再让孤撑感变成回报。",
                "analysis_share_reason": "让总在硬扛的人相信苦难必有回报，也能接住生活的风浪；不是天生坚强，只是暂时不能倒，也不是白天扛事晚上崩一下。",
                "analysis_do_not_turn_into": "不要写成沉默疲惫、孤立无援的负面诊断。",
                "tags": ["成年人硬撑", "人间安稳", "中年压力"],
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    enrich_response = client.post("/api/tracked-articles/responsibility-shelter-live-metadata-cleanup/enrich-metadata")
    assert enrich_response.status_code == 200
    payload = enrich_response.json()
    assert payload["analysis_structure_mode"] == "everyday_warmth_return"
    assert payload["tags"] == ["家庭责任", "家里踏实", "中年责任"]

    with workbench._get_connection() as connection:
        row = connection.execute(
            """
            SELECT summary, structure_notes, tags, analysis_theme, analysis_core_conflict,
                   analysis_emotional_exit, analysis_opening_pattern, analysis_hook_trigger,
                   analysis_progression_drive, analysis_share_reason, analysis_do_not_turn_into
            FROM tracked_articles
            WHERE slug = ?
            """,
            ("responsibility-shelter-live-metadata-cleanup",),
        ).fetchone()
    assert row is not None
    persisted_surface = " ".join(str(row[field] or "") for field in row.keys())
    for forbidden in (
        "成年人硬撑",
        "把辛苦咽下去",
        "把苦咽下去",
        "硬扛压力",
        "沉默疲惫",
        "孤撑感",
        "孤立无援",
        "撑不撑得住",
        "一路忍着、扛着",
        "暂时不能倒",
        "不能倒",
        "扛事",
        "天生坚强",
        "崩一下",
        "苦难必有回报",
        "苦难",
        "风浪",
        "万般辛苦",
        "人间安稳",
        "那一刻",
        "你会发现",
        "不是没有",
        "喉咙发紧",
    ):
        assert forbidden not in persisted_surface


def test_create_project_from_topic_and_advance_stage() -> None:
    create_response = client.post(
        "/api/topics/relationship-boundary-reset-playbook/create-project",
        json={
            "slug": "relationship-boundary-reset-delivery",
            "title": "关系边界重设交付稿",
            "owner": "editorial",
            "domain_pack_key": "relationship-repair",
        },
    )
    assert create_response.status_code == 201
    project = create_response.json()
    assert project["topic_slug"] == "relationship-boundary-reset-playbook"
    assert project["stage"] == "outline"
    assert project["domain_pack_key"] == "relationship-repair"

    update_response = client.patch(
        "/api/projects/relationship-boundary-reset-delivery",
        json={"stage": "draft_ready", "domain_pack_key": "workplace-growth"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["stage"] == "draft_ready"
    assert updated["domain_pack_key"] == "workplace-growth"

    dashboard_response = client.get("/api/dashboard/summary")
    assert dashboard_response.status_code == 200
    payload = dashboard_response.json()
    assert payload["draft_ready_projects"] == 4


def test_project_can_bind_tone_profile_and_generation_prefers_project_binding(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("assets", payload))
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("publish_package", payload))
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    created_profile_response = client.post(
        "/api/tone-profiles",
        json={
            "name": "项目专属纪实风",
            "opening_style": "从一次具体互动切入",
            "paragraph_rhythm": "中短段交错",
            "closing_style": "低压行动句收束",
            "forbidden_phrases": ["马上", "绝对"],
            "value_constraints": "不夸张，不说教",
            "target_word_count": 1600,
        },
    )
    assert created_profile_response.status_code == 201
    bound_profile = created_profile_response.json()

    project_create_response = client.post(
        "/api/topics/relationship-boundary-reset-playbook/create-project",
        json={
            "slug": "relationship-boundary-reset-bound-tone",
            "title": "关系边界重设绑定风格项目",
            "owner": "editorial",
            "preferred_tone_profile_id": bound_profile["id"],
            "domain_pack_key": "relationship-repair",
        },
    )
    assert project_create_response.status_code == 201
    created_project = project_create_response.json()
    assert created_project["preferred_tone_profile_id"] == bound_profile["id"]
    assert created_project["preferred_tone_profile_name"] == "项目专属纪实风"
    assert created_project["domain_pack_key"] == "relationship-repair"

    outline_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-outline")
    assert outline_response.status_code == 201
    first_outline_call = fake_generator.calls[0]
    assert first_outline_call[1]["tone_profile"]["name"] == "项目专属纪实风"
    assert first_outline_call[1]["domain_pack"]["key"] == "relationship-repair"

    draft_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-draft")
    assert draft_response.status_code == 201
    first_draft_call = next(call for call in fake_generator.calls if call[0] == "draft")
    assert first_draft_call[1]["tone_profile"]["name"] == "项目专属纪实风"
    assert first_draft_call[1]["domain_pack"]["key"] == "relationship-repair"

    assets_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-assets")
    assert assets_response.status_code == 201
    first_assets_call = next(call for call in fake_generator.calls if call[0] == "assets")
    assert first_assets_call[1]["tone_profile"]["name"] == "项目专属纪实风"
    assert first_assets_call[1]["domain_pack"]["key"] == "relationship-repair"

    publish_package_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/build-publish-package")
    assert publish_package_response.status_code == 201
    first_publish_package_call = next(call for call in fake_generator.calls if call[0] == "publish_package")
    assert first_publish_package_call[1]["tone_profile"]["name"] == "项目专属纪实风"
    assert first_publish_package_call[1]["domain_pack"]["key"] == "relationship-repair"

    patch_response = client.patch(
        "/api/projects/relationship-boundary-reset-bound-tone",
        json={"stage": "outline", "preferred_tone_profile_id": None, "domain_pack_key": None},
    )
    assert patch_response.status_code == 200
    patched_project = patch_response.json()
    assert patched_project["preferred_tone_profile_id"] is None
    assert patched_project["preferred_tone_profile_name"] is None
    assert patched_project["domain_pack_key"] is None

    second_outline_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-outline")
    assert second_outline_response.status_code == 201
    second_outline_call = [call for call in fake_generator.calls if call[0] == "outline"][-1]
    assert second_outline_call[1]["tone_profile"]["name"] == "女性成长克制陪伴风"
    assert second_outline_call[1]["domain_pack"]["key"] == "women-growth"

    second_draft_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-draft")
    assert second_draft_response.status_code == 201
    second_draft_call = [call for call in fake_generator.calls if call[0] == "draft"][-1]
    assert second_draft_call[1]["tone_profile"]["name"] == "女性成长克制陪伴风"
    assert second_draft_call[1]["domain_pack"]["key"] == "women-growth"

    second_assets_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-assets")
    assert second_assets_response.status_code == 201
    second_assets_call = [call for call in fake_generator.calls if call[0] == "assets"][-1]
    assert second_assets_call[1]["tone_profile"]["name"] == "女性成长克制陪伴风"
    assert second_assets_call[1]["domain_pack"]["key"] == "women-growth"

    second_publish_package_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/build-publish-package")
    assert second_publish_package_response.status_code == 201
    second_publish_package_call = [call for call in fake_generator.calls if call[0] == "publish_package"][-1]
    assert second_publish_package_call[1]["tone_profile"]["name"] == "女性成长克制陪伴风"
    assert second_publish_package_call[1]["domain_pack"]["key"] == "women-growth"


def test_tone_profiles_can_be_updated_and_are_applied_to_generation(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("assets", payload))
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("publish_package", payload))
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    profiles_response = client.get("/api/tone-profiles")
    assert profiles_response.status_code == 200
    profiles = profiles_response.json()
    assert len(profiles) >= 2
    default_profile = next(profile for profile in profiles if profile["name"] == "女性成长克制陪伴风")
    profile_id = default_profile["id"]

    update_response = client.patch(
        f"/api/tone-profiles/{profile_id}",
        json={
            "name": "克制陪伴风",
            "opening_style": "冷启动场景切入",
            "paragraph_rhythm": "短段落，慢推进",
            "closing_style": "留白式收束",
            "forbidden_phrases": ["必须", "立刻"],
            "value_constraints": "不说教，不制造羞耻感",
            "target_word_count": 1400,
        },
    )
    assert update_response.status_code == 200
    updated_profile = update_response.json()
    assert updated_profile["opening_style"] == "冷启动场景切入"
    assert updated_profile["forbidden_phrases"] == ["必须", "立刻"]
    assert updated_profile["target_word_count"] == 1400

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    outline_call = next(call for call in fake_generator.calls if call[0] == "outline")
    draft_call = next(call for call in fake_generator.calls if call[0] == "draft")
    assets_call = next(call for call in fake_generator.calls if call[0] == "assets")
    publish_call = next(call for call in fake_generator.calls if call[0] == "publish_package")

    assert outline_call[1]["tone_profile"]["opening_style"] == "冷启动场景切入"
    assert draft_call[1]["tone_profile"]["paragraph_rhythm"] == "短段落，慢推进"
    assert assets_call[1]["tone_profile"]["forbidden_phrases"] == ["必须", "立刻"]
    assert publish_call[1]["tone_profile"]["target_word_count"] == 1400


def test_tone_profiles_can_be_created_and_activated(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    profiles_response = client.get("/api/tone-profiles")
    assert profiles_response.status_code == 200
    profiles = profiles_response.json()
    assert len(profiles) >= 2
    active_profiles = [profile for profile in profiles if profile["is_active"]]
    assert len(active_profiles) == 1
    default_profile_id = active_profiles[0]["id"]

    create_response = client.post(
        "/api/tone-profiles",
        json={
            "name": "纪实关系复盘风",
            "opening_style": "从一次真实对话切入",
            "paragraph_rhythm": "中短段交错，强调停顿",
            "closing_style": "给出一个低压行动句",
            "forbidden_phrases": ["马上", "绝对"],
            "value_constraints": "不替读者下判断，不夸大冲突",
            "target_word_count": 1800,
        },
    )
    assert create_response.status_code == 201
    created_profile = create_response.json()
    assert created_profile["is_active"] is False

    activate_response = client.post(f"/api/tone-profiles/{created_profile['id']}/activate")
    assert activate_response.status_code == 200
    activated_profile = activate_response.json()
    assert activated_profile["is_active"] is True

    refreshed_profiles_response = client.get("/api/tone-profiles")
    assert refreshed_profiles_response.status_code == 200
    refreshed_profiles = refreshed_profiles_response.json()
    assert len(refreshed_profiles) >= 3
    assert [profile["id"] for profile in refreshed_profiles if profile["is_active"]] == [created_profile["id"]]
    default_profile = next(profile for profile in refreshed_profiles if profile["id"] == default_profile_id)
    assert default_profile["is_active"] is False

    generate_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    assert generate_response.status_code == 201

    outline_call = next(call for call in fake_generator.calls if call[0] == "outline")
    assert outline_call[1]["tone_profile"]["name"] == "纪实关系复盘风"
    assert outline_call[1]["tone_profile"]["opening_style"] == "从一次真实对话切入"


def test_generated_versions_record_tone_profile_metadata_and_restore_preserves_it(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            profile_name = str(payload["tone_profile"]["name"])
            return {
                "hook": f"{profile_name} hook",
                "outline_body": f"{profile_name} outline",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            profile_name = str(payload["tone_profile"]["name"])
            return {
                "title": f"{profile_name} draft",
                "body_markdown": f"# {profile_name}\n\nbody",
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            profile_name = str(payload["tone_profile"]["name"])
            return {
                "title_options": [f"{profile_name} title"],
                "cover_prompt": f"{profile_name} prompt",
                "cover_copy": f"{profile_name} cover",
                "social_teaser": f"{profile_name} teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            profile_name = str(payload["tone_profile"]["name"])
            return {
                "abstract": f"{profile_name} abstract",
                "tags": [profile_name],
                "editor_note": f"{profile_name} note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    create_response = client.post(
        "/api/tone-profiles",
        json={
            "name": "纪实关系复盘风",
            "opening_style": "从一次真实对话切入",
            "paragraph_rhythm": "中短段交错，强调停顿",
            "closing_style": "给出一个低压行动句",
            "forbidden_phrases": ["马上", "绝对"],
            "value_constraints": "不替读者下判断，不夸大冲突",
            "target_word_count": 1800,
        },
    )
    assert create_response.status_code == 201
    created_profile = create_response.json()

    activate_response = client.post(f"/api/tone-profiles/{created_profile['id']}/activate")
    assert activate_response.status_code == 200

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    detail_response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["outline"]["tone_profile_id"] == created_profile["id"]
    assert detail["outline"]["tone_profile_name"] == "纪实关系复盘风"
    assert detail["draft"]["tone_profile_name"] == "纪实关系复盘风"
    assert detail["assets"]["tone_profile_name"] == "纪实关系复盘风"
    assert detail["publish_package"]["tone_profile_name"] == "纪实关系复盘风"

    versions_response = client.get("/api/projects/office-burnout-recovery-weekly/versions")
    assert versions_response.status_code == 200
    versions = versions_response.json()
    assert versions["outlines"][0]["created_at"]
    assert versions["outlines"][0]["origin"] == "generate"
    assert versions["outlines"][0]["tone_profile_name"] == "纪实关系复盘风"
    assert versions["drafts"][0]["created_at"]
    assert versions["drafts"][0]["origin"] == "generate"
    assert versions["drafts"][0]["tone_profile_name"] == "纪实关系复盘风"
    assert versions["assets"][0]["created_at"]
    assert versions["assets"][0]["origin"] == "generate"
    assert versions["assets"][0]["tone_profile_name"] == "纪实关系复盘风"
    assert versions["publish_packages"][0]["created_at"]
    assert versions["publish_packages"][0]["origin"] == "generate"
    assert versions["publish_packages"][0]["tone_profile_name"] == "纪实关系复盘风"

    default_profile = next(profile for profile in client.get("/api/tone-profiles").json() if profile["name"] == "女性成长克制陪伴风")
    deactivate_response = client.post(f"/api/tone-profiles/{default_profile['id']}/activate")
    assert deactivate_response.status_code == 200

    restored_outline_response = client.post("/api/projects/office-burnout-recovery-weekly/restore-outline/1")
    assert restored_outline_response.status_code == 201
    restored_outline = restored_outline_response.json()
    assert restored_outline["created_at"]
    assert restored_outline["origin"] == "restore"
    assert restored_outline["tone_profile_id"] == created_profile["id"]
    assert restored_outline["tone_profile_name"] == "纪实关系复盘风"


def test_initialize_store_backfills_missing_version_metadata_from_task_logs() -> None:
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO outlines (
                project_slug, version, hook, outline_body, created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                1,
                "hook v1",
                "outline v1",
                None,
                None,
                None,
                "女性成长克制陪伴风",
            ),
        )
        connection.executemany(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "office-burnout-recovery-weekly",
                    1,
                    1,
                    "draft v1",
                    "# draft v1",
                    100,
                    None,
                    None,
                    None,
                    "女性成长克制陪伴风",
                ),
                (
                    "office-burnout-recovery-weekly",
                    1,
                    2,
                    "draft v2",
                    "# draft v2",
                    120,
                    None,
                    None,
                    None,
                    "女性成长克制陪伴风",
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO assets (
                project_slug, draft_version, version, title_options, cover_prompt, cover_copy, social_teaser,
                cover_image_path, cover_image_url, created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "office-burnout-recovery-weekly",
                    1,
                    1,
                    '["title v1"]',
                    "prompt v1",
                    "copy v1",
                    "teaser v1",
                    "",
                    "",
                    None,
                    None,
                    None,
                    "女性成长克制陪伴风",
                ),
                (
                    "office-burnout-recovery-weekly",
                    2,
                    2,
                    '["title v2"]',
                    "prompt v2",
                    "copy v2",
                    "teaser v2",
                    "",
                    "",
                    None,
                    None,
                    None,
                    "女性成长克制陪伴风",
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO publish_packages (
                project_slug, draft_version, assets_version, version, abstract, tags, publish_checklist, editor_note,
                markdown_path, markdown_url, manifest_path, manifest_url, status, review_comment, reviewed_by, reviewed_at,
                created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "office-burnout-recovery-weekly",
                    1,
                    1,
                    1,
                    "abstract v1",
                    '["tag-v1"]',
                    '["check-v1"]',
                    "note v1",
                    "v1.md",
                    "/v1.md",
                    "v1.json",
                    "/v1.json",
                    "needs_revision",
                    "需要加强开头",
                    "ops",
                    "2026-05-24T01:04:00Z",
                    None,
                    None,
                    None,
                    "女性成长克制陪伴风",
                ),
                (
                    "office-burnout-recovery-weekly",
                    2,
                    2,
                    2,
                    "abstract v2",
                    '["tag-v2"]',
                    '["check-v2"]',
                    "note v2",
                    "v2.md",
                    "/v2.md",
                    "v2.json",
                    "/v2.json",
                    "ready",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    "女性成长克制陪伴风",
                ),
            ],
        )
        connection.executemany(
            """
            INSERT INTO task_logs (task_type, status, entity_slug, entity_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("outline_generation", "done", "office-burnout-recovery-weekly", "project", "2026-05-24T01:00:00Z"),
                ("draft_generation", "done", "office-burnout-recovery-weekly", "project", "2026-05-24T01:01:00Z"),
                ("assets_generation", "done", "office-burnout-recovery-weekly", "project", "2026-05-24T01:02:00Z"),
                ("publish_package_built", "done", "office-burnout-recovery-weekly", "project", "2026-05-24T01:03:00Z"),
                ("publish_review", "needs_revision", "office-burnout-recovery-weekly", "project", "2026-05-24T01:04:00Z"),
                ("draft_generation", "done", "office-burnout-recovery-weekly", "project", "2026-05-24T01:05:00Z"),
                ("assets_generation", "done", "office-burnout-recovery-weekly", "project", "2026-05-24T01:06:00Z"),
                ("publish_package_built", "done", "office-burnout-recovery-weekly", "project", "2026-05-24T01:07:00Z"),
            ],
        )
        connection.commit()

    workbench.initialize_store()

    versions_response = client.get("/api/projects/office-burnout-recovery-weekly/versions")
    assert versions_response.status_code == 200
    versions = versions_response.json()

    assert versions["outlines"][0]["created_at"] == "2026-05-24T01:00:00Z"
    assert versions["outlines"][0]["origin"] == "generate"

    assert versions["drafts"][1]["created_at"] == "2026-05-24T01:01:00Z"
    assert versions["drafts"][1]["origin"] == "generate"
    assert versions["drafts"][0]["created_at"] == "2026-05-24T01:05:00Z"
    assert versions["drafts"][0]["origin"] == "review_regeneration"

    assert versions["assets"][1]["created_at"] == "2026-05-24T01:02:00Z"
    assert versions["assets"][1]["origin"] == "generate"
    assert versions["assets"][0]["created_at"] == "2026-05-24T01:06:00Z"
    assert versions["assets"][0]["origin"] == "review_regeneration"

    assert versions["publish_packages"][1]["created_at"] == "2026-05-24T01:03:00Z"
    assert versions["publish_packages"][1]["origin"] == "generate"
    assert versions["publish_packages"][0]["created_at"] == "2026-05-24T01:07:00Z"
    assert versions["publish_packages"][0]["origin"] == "review_regeneration"


def test_tone_profiles_support_copy_delete_and_reorder() -> None:
    default_profiles_response = client.get("/api/tone-profiles")
    assert default_profiles_response.status_code == 200
    default_profiles = default_profiles_response.json()
    assert len(default_profiles) >= 2
    default_profile = next(profile for profile in default_profiles if profile["name"] == "女性成长克制陪伴风")

    second_profile_response = client.post(
        "/api/tone-profiles",
        json={
            "name": "纪实关系复盘风",
            "opening_style": "从一次真实对话切入",
            "paragraph_rhythm": "中短段交错，强调停顿",
            "closing_style": "给出一个低压行动句",
            "forbidden_phrases": ["马上", "绝对"],
            "value_constraints": "不替读者下判断，不夸大冲突",
            "target_word_count": 1800,
        },
    )
    assert second_profile_response.status_code == 201
    second_profile = second_profile_response.json()

    copy_response = client.post(f"/api/tone-profiles/{second_profile['id']}/duplicate")
    assert copy_response.status_code == 201
    copied_profile = copy_response.json()
    assert copied_profile["name"] == "纪实关系复盘风 副本"
    assert copied_profile["preset_key"] is None
    assert copied_profile["is_active"] is False

    current_profiles = client.get("/api/tone-profiles").json()
    other_profile_ids = [
        profile["id"]
        for profile in current_profiles
        if profile["id"] not in {default_profile["id"], second_profile["id"], copied_profile["id"]}
    ]

    reorder_response = client.post(
        "/api/tone-profiles/reorder",
        json={"profile_ids": [copied_profile["id"], default_profile["id"], second_profile["id"], *other_profile_ids]},
    )
    assert reorder_response.status_code == 200
    reordered_profiles = reorder_response.json()
    assert [profile["id"] for profile in reordered_profiles][:3] == [
        default_profile["id"],
        copied_profile["id"],
        second_profile["id"],
    ]

    activate_response = client.post(f"/api/tone-profiles/{copied_profile['id']}/activate")
    assert activate_response.status_code == 200
    assert activate_response.json()["is_active"] is True

    delete_active_response = client.request("DELETE", f"/api/tone-profiles/{copied_profile['id']}")
    assert delete_active_response.status_code == 200
    deleted_payload = delete_active_response.json()
    assert deleted_payload["deleted_profile_id"] == copied_profile["id"]

    profiles_after_delete = client.get("/api/tone-profiles").json()
    assert len(profiles_after_delete) >= 3
    active_profiles = [profile for profile in profiles_after_delete if profile["is_active"]]
    assert len(active_profiles) == 1
    assert active_profiles[0]["id"] == default_profile["id"]

    delete_last_guard_response = client.request("DELETE", f"/api/tone-profiles/{default_profile['id']}")
    assert delete_last_guard_response.status_code == 200
    delete_second_guard_response = client.request("DELETE", f"/api/tone-profiles/{second_profile['id']}")
    assert delete_second_guard_response.status_code == 200
    remaining_profiles = client.get("/api/tone-profiles").json()
    final_profile = next(profile for profile in remaining_profiles if profile["name"] == "今晚有语")
    delete_preset_guard_response = client.request("DELETE", f"/api/tone-profiles/{final_profile['id']}")
    assert delete_preset_guard_response.status_code == 409


def test_builtin_tone_profiles_include_jinwan_youyu_preset() -> None:
    response = client.get("/api/tone-profiles")
    assert response.status_code == 200
    profiles = response.json()

    default_profile = next(profile for profile in profiles if profile["name"] == "女性成长克制陪伴风")
    assert default_profile["preset_key"] == "women-growth-classic"
    assert default_profile["is_active"] is True
    assert "直接问题、现实接口或判断切入" in default_profile["opening_style"]
    assert "不用生活场景冷启动" in default_profile["opening_style"]
    assert "不靠整段场景铺陈" in default_profile["paragraph_rhythm"]
    assert "多数段落以 1 到 3 句为主" in default_profile["paragraph_rhythm"]
    assert default_profile["closing_style"] == "明确结论或行动落点收束"
    assert "具体、克制、有承接" in default_profile["value_constraints"]
    assert "必须有情绪价值" in default_profile["value_constraints"]
    assert "不要靠环境、动作、物件和氛围凑篇幅" in default_profile["value_constraints"]
    assert "不用整段空场景托情绪" in default_profile["value_constraints"]
    assert "场景铺陈" in default_profile["default_polish_instruction"]
    assert "不要保留整段场景描述" in default_profile["default_polish_instruction"]
    assert "情绪空转" in default_profile["default_polish_instruction"]

    jinwan_profile = next(profile for profile in profiles if profile["name"] == "今晚有语")
    assert jinwan_profile["preset_key"] == "jinwan-youyu-answer"
    assert jinwan_profile["is_active"] is False
    assert jinwan_profile["target_word_count"] == 1500
    assert "你应该" in jinwan_profile["forbidden_phrases"]
    assert "给出答案" in jinwan_profile["value_constraints"]
    assert "必须有情绪价值" in jinwan_profile["value_constraints"]
    assert "每个判断都要给依据、情绪承接或行动落点" in jinwan_profile["value_constraints"]
    assert "不要靠大段场景描写托情绪" in jinwan_profile["value_constraints"]
    assert "不含蓄收尾" in jinwan_profile["value_constraints"]
    assert "直接问题、现实接口或一句共鸣判断切入" in jinwan_profile["opening_style"]
    assert "不靠整段氛围铺陈" in jinwan_profile["paragraph_rhythm"]
    assert "多数段落以 1 到 2 句为主" in jinwan_profile["paragraph_rhythm"]
    assert "行动落点" in jinwan_profile["paragraph_rhythm"]
    assert "开头用直接问题、现实接口或一句共鸣判断迅速点题" in jinwan_profile["default_polish_instruction"]
    assert "多数段落控制在 1 到 2 句" in jinwan_profile["default_polish_instruction"]
    assert "不要保留大段场景描写" in jinwan_profile["default_polish_instruction"]
    assert "不要写成场景散文" in jinwan_profile["default_polish_instruction"]
    assert "避免空转抒情" in jinwan_profile["default_polish_instruction"]


def test_builtin_jinwan_youyu_preset_flows_through_project_generation(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {"hook": "先说答案", "outline_body": "1. 开头点题\n2. 中段展开\n3. 结尾落点"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {"title": "答案先行的关系文", "body_markdown": "# 答案先行\n\n正文内容"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("assets", payload))
            return {
                "title_options": ["真正成熟的人，不再等别人来懂", "别再把人生遥控器交给别人"],
                "cover_prompt": "一位女性夜晚独处，克制而坚定，横版构图",
                "cover_copy": "真正的底气，来自自己",
                "social_teaser": "把期待收回来，人才会稳下来。",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("publish_package", payload))
            return {
                "abstract": "这篇稿子直接回答读者为何总把安全感寄托在别人身上。",
                "tags": ["女性成长", "关系边界"],
                "editor_note": "主打直接给答案，适合今晚有语风格发布。",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    profiles_response = client.get("/api/tone-profiles")
    assert profiles_response.status_code == 200
    jinwan_profile = next(profile for profile in profiles_response.json() if profile["name"] == "今晚有语")

    project_create_response = client.post(
        "/api/topics/relationship-boundary-reset-playbook/create-project",
        json={
            "slug": "relationship-boundary-reset-jinwan-youyu",
            "title": "今晚有语绑定风格项目",
            "owner": "editorial",
            "preferred_tone_profile_id": jinwan_profile["id"],
        },
    )
    assert project_create_response.status_code == 201
    created_project = project_create_response.json()
    assert created_project["preferred_tone_profile_id"] == jinwan_profile["id"]
    assert created_project["preferred_tone_profile_name"] == "今晚有语"

    outline_response = client.post("/api/projects/relationship-boundary-reset-jinwan-youyu/generate-outline")
    assert outline_response.status_code == 201
    outline_payload = outline_response.json()
    assert outline_payload["tone_profile_name"] == "今晚有语"

    draft_response = client.post("/api/projects/relationship-boundary-reset-jinwan-youyu/generate-draft")
    assert draft_response.status_code == 201
    draft_payload = draft_response.json()
    assert draft_payload["tone_profile_name"] == "今晚有语"

    assets_response = client.post("/api/projects/relationship-boundary-reset-jinwan-youyu/generate-assets")
    assert assets_response.status_code == 201
    assets_payload = assets_response.json()
    assert assets_payload["tone_profile_name"] == "今晚有语"

    publish_package_response = client.post("/api/projects/relationship-boundary-reset-jinwan-youyu/build-publish-package")
    assert publish_package_response.status_code == 201
    publish_package_payload = publish_package_response.json()
    assert publish_package_payload["tone_profile_name"] == "今晚有语"

    for stage in ("outline", "draft", "assets", "publish_package"):
        call_payload = next(payload for call_stage, payload in fake_generator.calls if call_stage == stage)
        tone_profile = call_payload["tone_profile"]
        assert tone_profile["name"] == "今晚有语"
        assert tone_profile["preset_key"] == "jinwan-youyu-answer"
        assert tone_profile["target_word_count"] == 1500
        assert "给出答案" in tone_profile["value_constraints"]


def test_project_detail_includes_outline_draft_assets_and_publish_slots() -> None:
    response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["slug"] == "office-burnout-recovery-weekly"
    assert payload["outline"] is None
    assert payload["draft"] is None
    assert payload["assets"] is None
    assert payload["publish_package"] is None
    assert payload["problem_brief"] is None
    assert payload["benchmarks"] == []
    assert payload["strategy_card"] is None


def test_generate_strategy_package_and_adopt_strategy_card_for_project() -> None:
    generate_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-strategy-package")
    assert generate_response.status_code == 201
    generated = generate_response.json()

    assert generated["project_slug"] == "office-burnout-recovery-weekly"
    assert generated["problem_brief"]["project_slug"] == "office-burnout-recovery-weekly"
    assert generated["problem_brief"]["version"] == 1
    assert generated["problem_brief"]["status"] == "ready"
    assert "办公室倦怠" in generated["problem_brief"]["clarified_problem"]
    assert generated["problem_brief"]["observed_phenomenon"]
    assert generated["problem_brief"]["writing_goal"]
    assert len(generated["problem_brief"]["constraints"]) >= 2
    assert generated["problem_brief"]["feedback_entry"]
    assert generated["problem_brief"]["problem_statement_markdown"].startswith("# 问题说明书")
    assert generated["benchmarks"][0]["strategy_version"] == 1
    assert generated["benchmarks"][0]["reference_kind"] == "trend"
    assert generated["benchmarks"][0]["reference_label"] == "办公室倦怠修复"
    assert generated["strategy_card"]["project_slug"] == "office-burnout-recovery-weekly"
    assert generated["strategy_card"]["version"] == 1
    assert generated["strategy_card"]["problem_brief_version"] == 1
    assert generated["strategy_card"]["status"] == "ready"
    assert generated["strategy_card"]["adopted_at"] is None
    assert generated["strategy_card"]["structure_mode"]
    assert generated["strategy_card"]["opening_move"]
    assert generated["strategy_card"]["body_shift"]
    assert generated["strategy_card"]["ending_move"]
    assert len(generated["strategy_card"]["divergence_axes"]) >= 4
    assert len(generated["strategy_card"]["execution_checklist"]) >= 4
    assert generated["strategy_card"]["strategy_markdown"].startswith("# 创作策略卡")

    detail_response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["problem_brief"]["version"] == 1
    assert detail["problem_brief"]["observed_phenomenon"] == generated["problem_brief"]["observed_phenomenon"]
    assert detail["problem_brief"]["writing_goal"] == generated["problem_brief"]["writing_goal"]
    assert detail["problem_brief"]["problem_statement_markdown"].startswith("# 问题说明书")
    assert detail["strategy_card"]["version"] == 1
    assert detail["strategy_card"]["structure_mode"] == generated["strategy_card"]["structure_mode"]
    assert detail["strategy_card"]["opening_move"] == generated["strategy_card"]["opening_move"]
    assert detail["strategy_card"]["body_shift"] == generated["strategy_card"]["body_shift"]
    assert detail["strategy_card"]["ending_move"] == generated["strategy_card"]["ending_move"]
    assert detail["strategy_card"]["strategy_markdown"].startswith("# 创作策略卡")
    assert detail["strategy_card"]["adopted_at"] is None
    assert detail["benchmarks"][0]["reference_label"] == "办公室倦怠修复"

    versions_response = client.get("/api/projects/office-burnout-recovery-weekly/versions")
    assert versions_response.status_code == 200
    versions = versions_response.json()
    assert versions["strategy_cards"][0]["version"] == 1
    assert versions["strategy_cards"][0]["status"] == "ready"

    adopt_response = client.post("/api/projects/office-burnout-recovery-weekly/adopt-strategy-card/1")
    assert adopt_response.status_code == 200
    adopted = adopt_response.json()

    assert adopted["project_slug"] == "office-burnout-recovery-weekly"
    assert adopted["strategy_card"]["version"] == 1
    assert adopted["strategy_card"]["adopted_at"] is not None
    assert adopted["project"]["slug"] == "office-burnout-recovery-weekly"
    assert adopted["project"]["current_chain_state"] == "missing_outline"
    assert adopted["project"]["next_required_step"] == "generate_outline"

    adopted_detail_response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert adopted_detail_response.status_code == 200
    adopted_detail = adopted_detail_response.json()
    assert adopted_detail["strategy_card"]["version"] == 1
    assert adopted_detail["strategy_card"]["adopted_at"] is not None


def test_generate_outline_uses_strategy_only_after_card_is_adopted(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(payload)
            return {
                "hook": f"{payload['project_title']} hook",
                "outline_body": "1. a\n2. b",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    generate_response = client.post("/api/projects/high-sensitivity-restoration-notes/generate-strategy-package")
    assert generate_response.status_code == 201

    first_outline_response = client.post("/api/projects/high-sensitivity-restoration-notes/generate-outline")
    assert first_outline_response.status_code == 201
    first_payload = fake_generator.calls[0]
    assert "strategy_card" not in first_payload
    assert "problem_brief" not in first_payload
    assert "benchmarks" not in first_payload

    adopt_response = client.post("/api/projects/high-sensitivity-restoration-notes/adopt-strategy-card/1")
    assert adopt_response.status_code == 200

    second_outline_response = client.post("/api/projects/high-sensitivity-restoration-notes/generate-outline")
    assert second_outline_response.status_code == 201
    second_payload = fake_generator.calls[1]
    assert second_payload["strategy_card"]["version"] == 1
    assert second_payload["strategy_card"]["strategy_markdown"].startswith("# 创作策略卡")
    assert second_payload["problem_brief"]["version"] == 1
    assert second_payload["problem_brief"]["problem_statement_markdown"].startswith("# 问题说明书")
    assert second_payload["benchmarks"][0]["reference_label"] == "关系边界重设"


def test_generate_outline_retries_once_for_custom_provider_tracked_article_transport_error(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "outline-retry-source",
            "source_name": "夜读关系实验室",
            "title": "总在照顾别人情绪的人，也会突然一句话都不想说",
            "url": "https://example.com/outline-retry-source",
            "author": "北岛",
            "summary": "从关系里的消耗切入，写一个人怎样在长期硬撑里慢慢安静下来。",
            "structure_notes": "现实切口 + 过程观察 + 收束回暖。",
            "tags": ["情绪消耗", "关系负重"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n她不是不想说，只是那阵子真的太累了。",
        },
    )
    client.post(
        "/api/tracked-articles/outline-retry-source/to-topic",
        json={
            "slug": "outline-retry-topic",
            "title": "总在照顾别人情绪的人，也需要有人接住",
            "angle": "关系负重",
        },
    )
    project_response = client.post(
        "/api/topics/outline-retry-topic/create-project",
        json={
            "slug": "outline-retry-project",
            "title": "outline retry 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/outline-retry-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/outline-retry-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(dict(payload))
            if len(self.calls) == 1:
                raise openai.APIConnectionError(
                    request=httpx.Request("POST", "https://proxy.example/v1/responses")
                )
            return {
                "hook": "她终于没有再把那句我没事咽回去。",
                "outline_body": "1. 总在接住别人\n2. 身体先慢下来\n3. 关系里开始沉默\n4. 有人愿意接住她",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    outline = workbench.generate_outline("outline-retry-project")

    assert outline.hook == "她终于没有再把那句我没事咽回去。"
    assert outline.version == 1
    assert len(fake_generator.calls) == 2
    assert fake_generator.calls[0]["strategy_first_outline_mode"] is True
    assert fake_generator.calls[1]["strategy_first_outline_mode"] is True
    assert fake_generator.calls[0].get("outline_timeout_recovery_mode") is None
    assert fake_generator.calls[1]["outline_timeout_recovery_mode"] is True
    assert fake_generator.calls[0]["problem_brief"]["version"] == 1
    assert fake_generator.calls[0]["strategy_card"]["version"] == 1
    assert fake_generator.calls[0]["benchmarks"]
    assert fake_generator.calls[0]["reference_article_hidden"] is True


def test_generate_outline_does_not_retry_when_provider_is_not_custom_base_url(monkeypatch) -> None:
    class FakeGenerator:
        uses_custom_base_url = False

        def __init__(self) -> None:
            self.calls = 0

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls += 1
            raise openai.APIConnectionError(
                request=httpx.Request("POST", "https://api.openai.com/v1/responses")
            )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    with pytest.raises(openai.APIConnectionError):
        workbench.generate_outline("office-burnout-recovery-weekly")

    assert fake_generator.calls == 1


def test_generate_outline_custom_provider_retry_falls_back_to_local_outline_after_one_extra_attempt(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "outline-retry-fail-source",
            "source_name": "夜读关系实验室",
            "title": "那些总说没事的人，往往已经很久没被真正问过一句你还好吗",
            "url": "https://example.com/outline-retry-fail-source",
            "author": "北岛",
            "summary": "从一次长期硬撑后的停顿切入，写被理解这件事对成年人有多重要。",
            "structure_notes": "问题起手 + 过程拆解 + 暖意回落。",
            "tags": ["长期硬撑", "被理解"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n她没崩溃，只是慢慢不再开口。",
        },
    )
    client.post(
        "/api/tracked-articles/outline-retry-fail-source/to-topic",
        json={
            "slug": "outline-retry-fail-topic",
            "title": "那些总说没事的人，其实更需要被认真问一句",
            "angle": "被理解",
        },
    )
    project_response = client.post(
        "/api/topics/outline-retry-fail-topic/create-project",
        json={
            "slug": "outline-retry-fail-project",
            "title": "outline retry fail 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/outline-retry-fail-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/outline-retry-fail-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls = 0

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls += 1
            raise openai.APIConnectionError(
                request=httpx.Request("POST", "https://proxy.example/v1/responses")
            )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench.settings, "openai_allow_local_creative_fallbacks", True, raising=False)

    outline = workbench.generate_outline("outline-retry-fail-project")

    assert outline.version == 1
    assert outline.hook
    assert "### 1." in outline.outline_body
    assert "### 4." in outline.outline_body
    assert fake_generator.calls == 2


def test_generate_assets_uses_full_prompt_first_for_custom_tracked_article_provider(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "assets-retry-source",
            "source_name": "夜读关系实验室",
            "title": "夜里那句我没事，背后都是责任",
            "url": "https://example.com/assets-retry-source",
            "author": "北岛",
            "summary": "从成年人把疲惫先咽回去写起，再把辛苦回收到家里的安稳和被护住的秩序里。",
            "structure_notes": "现实接口起手 + 责任代价推进 + 回到家里安稳。",
            "tags": ["中年责任", "家庭安稳"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n他说没事的时候，手心其实已经凉了。",
        },
    )
    client.post(
        "/api/tracked-articles/assets-retry-source/to-topic",
        json={
            "slug": "assets-retry-topic",
            "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样把辛苦压回去。",
        },
    )
    project_response = client.post(
        "/api/topics/assets-retry-topic/create-project",
        json={
            "slug": "assets-retry-project",
            "title": "assets retry 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/assets-retry-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/assets-retry-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.asset_calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "他说没事的时候，手心其实已经凉了。",
                "outline_body": "1. 为什么先把自己往后放\n2. 责任怎样把辛苦压回去\n3. 家里的安稳怎么把意义接回来",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
                "body_markdown": (
                    "很多时候，说这句话的人并不轻松。\n\n"
                    "可他还是得先把家里的气稳住，再把自己的慌乱往后放。"
                ),
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.asset_calls.append(dict(payload))
            return {
                "title_options": [
                    "夜里那句“没事，有我”，背后压着的是一个家的秩序",
                    "很多人不是不累，只是先把发紧和慌乱压回去了",
                    "把家稳住的人，往往先把自己的累咽了回去",
                ],
                "recommended_title": "夜里那句“没事，有我”，背后压着的是一个家的秩序",
                "cover_prompt": "16:9 横版公众号头图，夜里灯还亮着，饭桌留着一盏暖灯，克制现实感",
                "cover_copy": "那点发紧没有白挨，最后都在把家稳住。",
                "social_teaser": "那句没事，有我，背后压着的是整屋子的秩序和发紧以后还得继续撑住。",
                "social_teaser_options": ["导语一", "导语二", "导语三"],
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    client.post("/api/projects/assets-retry-project/generate-outline")
    client.post("/api/projects/assets-retry-project/generate-draft")
    assets = workbench.generate_assets("assets-retry-project")

    assert assets.recommended_title == "夜里那句“没事，有我”，背后压着的是一个家的秩序"
    assert assets.title_options[0] == assets.recommended_title
    assert "背后压着的是一个家的秩序" in assets.recommended_title
    assert len(fake_generator.asset_calls) >= 1
    assert fake_generator.asset_calls[0].get("assets_timeout_recovery_mode") is None
    assert fake_generator.asset_calls[0]["problem_brief"]["version"] == 1
    assert fake_generator.asset_calls[0]["strategy_card"]["version"] == 1
    assert fake_generator.asset_calls[0]["benchmarks"]


def test_generate_assets_surfaces_upstream_failure_when_tracked_article_assets_timeout(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "assets-local-fallback-source",
            "source_name": "夜读关系实验室",
            "title": "夜里那句我没事，背后都是责任",
            "url": "https://example.com/assets-local-fallback-source",
            "author": "北岛",
            "summary": "从成年人把疲惫先咽回去写起，再把辛苦回收到家里的安稳和被护住的秩序里。",
            "structure_notes": "现实接口起手 + 责任代价推进 + 回到家里安稳。",
            "tags": ["中年责任", "家庭安稳"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n他说没事的时候，手心其实已经凉了。",
        },
    )
    client.post(
        "/api/tracked-articles/assets-local-fallback-source/to-topic",
        json={
            "slug": "assets-local-fallback-topic",
            "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样把辛苦压回去。",
        },
    )
    project_response = client.post(
        "/api/topics/assets-local-fallback-topic/create-project",
        json={
            "slug": "assets-local-fallback-project",
            "title": "assets local fallback 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/assets-local-fallback-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/assets-local-fallback-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "他说没事的时候，手心其实已经凉了。",
                "outline_body": "1. 为什么先把自己往后放\n2. 责任怎样把辛苦压回去\n3. 家里的安稳怎么把意义接回来",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
                "body_markdown": (
                    "很多时候，说这句话的人并不轻松。\n\n"
                    "可他还是得先把家里的气稳住，再把自己的慌乱往后放。"
                ),
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://proxy.example/v1/chat/completions"))

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    assert client.post("/api/projects/assets-local-fallback-project/generate-outline").status_code == 201
    assert client.post("/api/projects/assets-local-fallback-project/generate-draft").status_code == 201

    with pytest.raises(HTTPException) as exc_info:
        workbench.generate_assets("assets-local-fallback-project")

    assert exc_info.value.status_code == 503
    assert str(exc_info.value.detail).startswith("素材文案生成失败：当前文本 AI 服务暂时不可用，请稍后重试。")
    assert "当前已关闭本地兜底，避免写成退化稿。" in str(exc_info.value.detail)


def test_generate_assets_retries_compact_prompt_after_custom_tracked_article_transport_error(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "assets-retry-after-error-source",
            "source_name": "夜读关系实验室",
            "title": "夜里那句我没事，背后都是责任",
            "url": "https://example.com/assets-retry-after-error-source",
            "author": "北岛",
            "summary": "从成年人把疲惫先咽回去写起，再把辛苦回收到家里的安稳和被护住的秩序里。",
            "structure_notes": "现实接口起手 + 责任代价推进 + 回到家里安稳。",
            "tags": ["中年责任", "家庭安稳"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n他说没事的时候，手心其实已经凉了。",
        },
    )
    client.post(
        "/api/tracked-articles/assets-retry-after-error-source/to-topic",
        json={
            "slug": "assets-retry-after-error-topic",
            "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样把辛苦压回去。",
        },
    )
    project_response = client.post(
        "/api/topics/assets-retry-after-error-topic/create-project",
        json={
            "slug": "assets-retry-after-error-project",
            "title": "assets retry after error 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/assets-retry-after-error-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/assets-retry-after-error-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.asset_calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "他说没事的时候，手心其实已经凉了。",
                "outline_body": "1. 为什么先把自己往后放\n2. 责任怎样把辛苦压回去\n3. 家里的安稳怎么把意义接回来",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
                "body_markdown": (
                    "很多时候，说这句话的人并不轻松。\n\n"
                    "可他还是得先把家里的气稳住，再把自己的慌乱往后放。"
                ),
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.asset_calls.append(dict(payload))
            if len(self.asset_calls) == 1:
                raise openai.APIConnectionError(
                    request=httpx.Request("POST", "https://proxy.example/v1/chat/completions")
                )
            return {
                "title_options": ["那句轻轻的没事，先把一家人的慌稳住了"],
                "recommended_title": "那句轻轻的没事，先把一家人的慌稳住了",
                "cover_prompt": "16:9 横版公众号头图，夜里灯还亮着，饭桌留着一盏暖灯，克制现实感",
                "cover_copy": "有人把慌稳住，家里才有了亮处。",
                "social_teaser": "那句轻轻说出口的没事，很多时候先稳住的是一家人的慌。",
                "social_teaser_options": ["导语一", "导语二", "导语三"],
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    assert client.post("/api/projects/assets-retry-after-error-project/generate-outline").status_code == 201
    assert client.post("/api/projects/assets-retry-after-error-project/generate-draft").status_code == 201

    assets = workbench.generate_assets("assets-retry-after-error-project")

    assert assets.recommended_title == "那句轻轻的没事，先把一家人的慌稳住了"
    assert len(fake_generator.asset_calls) >= 2
    assert fake_generator.asset_calls[0].get("assets_timeout_recovery_mode") is None
    assert fake_generator.asset_calls[0]["problem_brief"]["version"] == 1
    assert fake_generator.asset_calls[0]["strategy_card"]["version"] == 1
    assert fake_generator.asset_calls[0]["benchmarks"]
    assert fake_generator.asset_calls[1]["assets_timeout_recovery_mode"] is True


def test_generate_assets_surfaces_upstream_failure_when_packaging_retry_times_out(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "assets-retry-timeout-source",
            "source_name": "夜读关系实验室",
            "title": "夜里那句我没事，背后都是责任",
            "url": "https://example.com/assets-retry-timeout-source",
            "author": "北岛",
            "summary": "从成年人把疲惫先咽回去写起，再把辛苦回收到家里的安稳和被护住的秩序里。",
            "structure_notes": "现实接口起手 + 责任代价推进 + 回到家里安稳。",
            "tags": ["中年责任", "家庭安稳"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n他说没事的时候，手心其实已经凉了。",
        },
    )
    client.post(
        "/api/tracked-articles/assets-retry-timeout-source/to-topic",
        json={
            "slug": "assets-retry-timeout-topic",
            "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样把辛苦压回去。",
        },
    )
    project_response = client.post(
        "/api/topics/assets-retry-timeout-topic/create-project",
        json={
            "slug": "assets-retry-timeout-project",
            "title": "assets retry timeout 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/assets-retry-timeout-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/assets-retry-timeout-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.asset_calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "他说没事的时候，手心其实已经凉了。",
                "outline_body": "1. 为什么先把自己往后放\n2. 责任怎样把辛苦压回去\n3. 家里的安稳怎么把意义接回来",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "肩上有责任的人，心里也要留一盏灯",
                "body_markdown": (
                    "很多时候，说这句话的人并不轻松。\n\n"
                    "可他还是得先把家里的气稳住，再把自己的慌乱往后放。"
                ),
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.asset_calls.append(dict(payload))
            if len(self.asset_calls) == 1:
                return {
                    "title_options": ["很多人的那句我没事，藏着没说出口的累"],
                    "recommended_title": "很多人的那句我没事，藏着没说出口的累",
                    "cover_prompt": "16:9 横版公众号头图，夜里灯还亮着",
                    "cover_copy": "很多人都在悄悄把生活接住。",
                    "social_teaser": "很多时候，那句我没事背后，是成年人说不出口的累。",
                    "social_teaser_options": ["很多人都在悄悄把生活接住。"],
                }
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://proxy.example/v1/chat/completions"))

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

    fake_generator = FakeGenerator()
    retry_checks: list[Mapping[str, object]] = []

    def should_retry_once(*, strategy_bundle_payload: Mapping[str, object], ai_result: Mapping[str, object]) -> bool:
        retry_checks.append(ai_result)
        return len(retry_checks) == 1

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_assets_for_packaging", should_retry_once)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    assert client.post("/api/projects/assets-retry-timeout-project/generate-outline").status_code == 201
    assert client.post("/api/projects/assets-retry-timeout-project/generate-draft").status_code == 201

    with pytest.raises(HTTPException) as exc_info:
        workbench.generate_assets("assets-retry-timeout-project")

    assert len(fake_generator.asset_calls) == 2
    assert exc_info.value.status_code == 503
    assert str(exc_info.value.detail).startswith("素材文案生成失败：当前文本 AI 服务暂时不可用，请稍后重试。")
    assert "当前已关闭本地兜底，避免写成退化稿。" in str(exc_info.value.detail)


def test_generate_draft_uses_strategy_only_after_card_is_adopted(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(payload)
            return {"title": "title", "body_markdown": "# title\n\nbody"}

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    generate_response = client.post("/api/projects/high-sensitivity-restoration-notes/generate-strategy-package")
    assert generate_response.status_code == 201

    outline_response = client.post("/api/projects/high-sensitivity-restoration-notes/generate-outline")
    assert outline_response.status_code == 201

    first_draft_response = client.post("/api/projects/high-sensitivity-restoration-notes/generate-draft")
    assert first_draft_response.status_code == 201
    first_payload = fake_generator.calls[0]
    assert first_payload["problem_brief"] is None
    assert first_payload["strategy_card"] is None
    assert first_payload["benchmarks"] is None

    adopt_response = client.post("/api/projects/high-sensitivity-restoration-notes/adopt-strategy-card/1")
    assert adopt_response.status_code == 200

    second_draft_response = client.post("/api/projects/high-sensitivity-restoration-notes/generate-draft")
    assert second_draft_response.status_code == 201
    second_payload = fake_generator.calls[1]
    assert second_payload["strategy_card"]["version"] == 1
    assert second_payload["strategy_card"]["strategy_markdown"].startswith("# 创作策略卡")
    assert second_payload["problem_brief"]["version"] == 1
    assert second_payload["problem_brief"]["problem_statement_markdown"].startswith("# 问题说明书")
    assert second_payload["benchmarks"][0]["reference_label"] == "关系边界重设"


def test_generate_outline_draft_assets_and_publish_package_for_project(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {
                "hook": "先写一个加班后情绪崩掉的瞬间",
                "outline_body": "1. 情绪瞬间\n2. 倦怠来源\n3. 恢复动作\n4. 复盘收束",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {
                "title": "办公室倦怠后，先把自己的电量接回来",
                "body_markdown": (
                    "# 办公室倦怠后，先把自己的电量接回来\n\n"
                    "那天晚上十点，你坐在工位前，突然发现自己已经没有任何解释的力气。"
                ),
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("assets", payload))
            return {
                "title_options": [
                    "不是你矫情，是你真的太久没休息了",
                    "成年人的倦怠，往往从不敢停开始",
                ],
                "cover_prompt": "夜晚办公室，一个女生独自坐在工位前，暖黄灯光，情绪克制写实风",
                "cover_copy": "你不是突然垮掉的，只是太久没有被接住",
                "social_teaser": "从情绪崩点写到恢复动作，这篇适合发给正在硬撑的她。",
            }

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            self.calls.append(("cover_image", payload))
            return b"fake-png-binary"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("publish_package", payload))
            return {
                "abstract": "一篇关于办公室倦怠识别与恢复动作的公众号稿件。",
                "tags": ["女性成长", "情绪恢复", "办公室倦怠"],
                "editor_note": "首图情绪到位，正文节奏自然，适合午后推送。",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    outline_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    assert outline_response.status_code == 201
    outline = outline_response.json()
    assert outline["project_slug"] == "office-burnout-recovery-weekly"
    assert outline["version"] == 1
    assert outline["hook"] == "先写一个加班后情绪崩掉的瞬间"

    draft_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()
    assert draft["project_slug"] == "office-burnout-recovery-weekly"
    assert draft["outline_version"] == 1
    assert draft["version"] == 1
    assert draft["title"] == "办公室倦怠后，先把自己的电量接回来"
    assert draft["word_count"] == len(draft["body_markdown"])

    assets_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    assert assets_response.status_code == 201
    assets = assets_response.json()
    assert assets["project_slug"] == "office-burnout-recovery-weekly"
    assert assets["draft_version"] == 1
    assert assets["version"] == 1
    assert assets["title_options"][0] == "不是你矫情，是你真的太久没休息了"
    assert assets["cover_copy"] == "你不是突然垮掉的，只是太久没有被接住"
    assert assets["cover_image_path"].endswith("office-burnout-recovery-weekly-assets-v1.png")
    assert assets["cover_image_url"] == "/generated-assets/office-burnout-recovery-weekly-assets-v1.png"

    detail_response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["outline"]["version"] == 1
    assert detail["draft"]["version"] == 1
    assert detail["assets"]["version"] == 1
    assert detail["project"]["stage"] == "assets_ready"
    assert Path(detail["assets"]["cover_image_path"]).read_bytes() == b"fake-png-binary"
    image_response = client.get(detail["assets"]["cover_image_url"])
    assert image_response.status_code == 200
    assert image_response.content == b"fake-png-binary"

    publish_response = client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    assert publish_response.status_code == 201
    publish_package = publish_response.json()
    assert publish_package["project_slug"] == "office-burnout-recovery-weekly"
    assert publish_package["draft_version"] == 1
    assert publish_package["assets_version"] == 1
    assert publish_package["status"] == "ready"
    assert publish_package["markdown_path"].endswith("office-burnout-recovery-weekly-publish-v1.md")
    assert publish_package["manifest_path"].endswith("office-burnout-recovery-weekly-publish-v1.json")
    assert publish_package["markdown_url"] == "/generated-assets/office-burnout-recovery-weekly-publish-v1.md"
    assert publish_package["manifest_url"] == "/generated-assets/office-burnout-recovery-weekly-publish-v1.json"
    assert publish_package["publish_checklist"] == [
        "核对标题与封面文案是否同一情绪主线",
        "确认摘要、标签、导语和正文结论一致",
        "检查配图、错别字和发布时间建议后再发布",
    ]
    markdown_text = Path(publish_package["markdown_path"]).read_text(encoding="utf-8")
    assert markdown_text.startswith("# 不是你矫情，是你真的太久没休息了")
    assert "那天晚上十点，你坐在工位前" in markdown_text
    manifest_text = Path(publish_package["manifest_path"]).read_text(encoding="utf-8")
    assert "情绪恢复" in manifest_text
    assert "publish_checklist" in manifest_text
    assert "核对标题与封面文案是否同一情绪主线" in manifest_text
    assert "tone_profile_name" in manifest_text
    assert "女性成长克制陪伴风" in manifest_text

    publish_file_response = client.get(publish_package["markdown_url"])
    assert publish_file_response.status_code == 200
    assert publish_file_response.text.startswith("# 不是你矫情，是你真的太久没休息了")
    assert "那天晚上十点，你坐在工位前" in publish_file_response.text

    detail_after_publish_response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert detail_after_publish_response.status_code == 200
    detail_after_publish = detail_after_publish_response.json()
    assert detail_after_publish["publish_package"]["status"] == "ready"
    assert detail_after_publish["publish_package"]["publish_checklist"][1] == "确认摘要、标签、导语和正文结论一致"
    assert detail_after_publish["project"]["stage"] == "publish_ready"

    call_types = [call[0] for call in fake_generator.calls]
    assert call_types == ["outline", "draft", "assets", "cover_image", "publish_package"]
    assert fake_generator.calls[0][1]["topic_title"] == "把办公室倦怠写成自救路径"
    assert fake_generator.calls[1][1]["outline"]["hook"] == "先写一个加班后情绪崩掉的瞬间"
    assert fake_generator.calls[2][1]["draft"]["title"] == "办公室倦怠后，先把自己的电量接回来"
    assert "16:9" in fake_generator.calls[3][1]["cover_prompt"]
    assert "横版" in fake_generator.calls[3][1]["cover_prompt"]
    assert "夜晚办公室，一个女生独自坐在工位前，暖黄灯光，情绪克制写实风" in fake_generator.calls[3][1]["cover_prompt"]
    assert "竖版" not in fake_generator.calls[3][1]["cover_prompt"]
    assert fake_generator.calls[4][1]["assets"]["cover_image_url"] == "/generated-assets/office-burnout-recovery-weekly-assets-v1.png"


def test_generate_draft_auto_polishes_high_ai_flavor_first_pass(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "她把那句我没事说出口的时候，其实已经在往后退了。",
                "outline_body": "1. 对话卡住的瞬间\n2. 赌气背后的误解\n3. 关系怎么慢慢冷下来\n4. 重新开口的动作",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                return {
                    "title": "她说完“我没事”之后，关系是怎么慢慢冷下去的",
                    "body_markdown": (
                        "# 她说完“我没事”之后，关系是怎么慢慢冷下去的\n\n"
                        "那天晚上，她把手机扣在桌面上，只说了一句我没事。灯没关，水也还热着，可屋子里已经没有人继续把话往下接了。\n\n"
                        "更常见的情况是，两个人都以为对方会懂，于是把真正的委屈留在了停顿里。\n\n"
                        "后来他们都想过靠近，只是每一次都慢了半拍。有人等解释，有人等台阶，最后只剩下一张谁也没碰的餐桌。\n\n"
                        "如果还舍不得，不如从把那句当时没说出口的话补回来开始。"
                    ),
                }

            return {
                "title": "你赌我不敢走，我赌你再也遇不到真诚的人",
                "body_markdown": (
                    "# 标题\n\n"
                    "不是不爱，而是太久没有被看见。其实很多时候，关系崩塌不是从争吵开始，而是从一次赌气开始。\n\n"
                    "你以为他懂，他以为你不在乎，所以两个人都在等对方先低头。换句话说，真正受伤的不是面子，而是那颗还想靠近的心。\n\n"
                    "很多人会这样，一点委屈、一个沉默、一些误会，最后都变成一种谁也不肯先开口的僵持。\n\n"
                    "从今天开始，别再赌气，愿你有话直说，成为不靠试探也能被懂的人。"
                ),
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    outline_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()

    assert draft["version"] == 1
    assert draft["title"] == "她说完“我没事”之后，关系是怎么慢慢冷下去的"
    assert "那天晚上" in draft["body_markdown"]

    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    assert len(draft_calls) == 2
    initial_payload = draft_calls[0][1]
    polished_payload = draft_calls[1][1]
    assert initial_payload.get("polish_instruction") in {None, ""}
    assert polished_payload["draft"]["title"] == "你赌我不敢走，我赌你再也遇不到真诚的人"
    assert "去模板化重写" in str(polished_payload["polish_instruction"])
    assert "不是……而是" in str(polished_payload["polish_instruction"])

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["draft"]["version"] == 1
    assert detail["draft"]["title"] == "她说完“我没事”之后，关系是怎么慢慢冷下去的"


def test_generate_draft_runs_single_auto_polish_pass_for_custom_base_url_generator(monkeypatch) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "她把那句我没事说出口的时候，其实已经在往后退了。",
                "outline_body": "1. 对话卡住的瞬间\n2. 赌气背后的误解\n3. 关系怎么慢慢冷下来\n4. 重新开口的动作",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                return {
                    "title": "她说完“我没事”之前，身体其实已经慢慢把人往后拖了",
                    "body_markdown": (
                        "# 她说完“我没事”之前，身体其实已经慢慢把人往后拖了\n\n"
                        "电梯门快合上的时候，她明明已经往前迈了半步，鞋尖碰到金属边，又收了回来。\n\n"
                        "电脑包勒着手指，主管那句“上午会别迟到”还挂在手机最上面。她把屏幕按灭，胸口那阵发空没有立刻过去。\n\n"
                        "这不是突然垮掉，更像很多次把不舒服往后按，最后连自己也差点认不出来。\n\n"
                        "洗手台前那次干呕、回家找不到钥匙那次发火、站在挂号页面前迟迟没按下去，都是同一件事在往外冒。\n\n"
                        "她真正怕的不是去医院，而是承认自己已经慢下来很久了。"
                    ),
                }
            return {
                "title": "你赌我不敢走，我赌你再也遇不到真诚的人",
                "body_markdown": (
                    "# 标题\n\n"
                    "不是不爱，而是太久没有被看见。其实很多时候，关系崩塌不是从争吵开始，而是从一次赌气开始。\n\n"
                    "你以为他懂，他以为你不在乎，所以两个人都在等对方先低头。换句话说，真正受伤的不是面子，而是那颗还想靠近的心。\n\n"
                    "很多人会这样，一点委屈、一个沉默、一些误会，最后都变成一种谁也不肯先开口的僵持。\n\n"
                    "从今天开始，别再赌气，愿你有话直说，成为不靠试探也能被懂的人。"
                ),
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    outline_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()

    assert draft["version"] == 1
    assert draft["title"] == "她说完“我没事”之前，身体其实已经慢慢把人往后拖了"
    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    assert len(draft_calls) == 2
    assert draft_calls[0][1].get("polish_instruction") in {None, ""}
    polished_payload = draft_calls[1][1]
    assert "去模板化重写" in str(polished_payload.get("polish_instruction") or "")
    assert polished_payload["problem_brief"] is None
    assert polished_payload["strategy_card"] is None
    assert polished_payload["benchmarks"] is None
    assert polished_payload.get("compact_polish_mode") is True


def test_generate_draft_auto_polish_for_custom_provider_keeps_strategy_bundle_on_tracked_article(monkeypatch) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {
                "hook": "先落一个没接住的停顿。",
                "outline_body": "1. 停顿现场\n2. 为什么总先解释\n3. 关系怎么慢慢冷下来\n4. 重新开口的动作",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                return {
                    "title": "她把解释咽回去之后，关系为什么还是没有慢慢好起来",
                    "body_markdown": (
                        "# 她把解释咽回去之后，关系为什么还是没有慢慢好起来\n\n"
                        "她盯着对话框看了两秒，先删掉了那句已经打好的“我不是那个意思”。\n\n"
                        "桌上的水没动，屏幕亮了一下又暗下去。她没有继续往下解释，只把手机扣回桌面。\n\n"
                        "很多关系不是坏在不会说，而是坏在那一下失望先掉到了地上，后面的解释都慢了半步。\n\n"
                        "后来她重新开口，也不是一下就说清了，只是先把那晚没接住的情绪补了回来。"
                    ),
                }
            return {
                "title": "先接住失望，再谈道理",
                "body_markdown": (
                    "# 先接住失望，再谈道理\n\n"
                    "不是不会说，而是每次都先急着解释。很多时候，关系就是这样一点点冷下去的。\n\n"
                    "你以为说明白就够了，他以为你根本没在听，所以两个人都在各自那边用力。\n\n"
                    "真正难的不是道理，而是那一下失望没有被接住。\n\n"
                    "从今天开始，别急着解释，先把情绪接回来。"
                ),
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "custom-provider-auto-polish-source",
            "source_name": "夜读关系实验室",
            "title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "url": "https://example.com/custom-provider-auto-polish-source",
            "author": "北岛",
            "summary": "从关系修复案例提炼表达顺序。",
            "structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "tags": ["表达修复", "关系修复"],
        },
    )
    client.post(
        "/api/tracked-articles/custom-provider-auto-polish-source/to-topic",
        json={
            "slug": "custom-provider-auto-polish-topic",
            "title": "先接住失望，再谈道理",
            "angle": "关系修复",
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    project_response = client.post(
        "/api/topics/custom-provider-auto-polish-topic/create-project",
        json={
            "slug": "custom-provider-auto-polish-project",
            "title": "慢修复关系稿",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201

    strategy_response = client.post("/api/projects/custom-provider-auto-polish-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    adopt_response = client.post("/api/projects/custom-provider-auto-polish-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200

    outline_response = client.post("/api/projects/custom-provider-auto-polish-project/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/custom-provider-auto-polish-project/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()

    assert draft["title"] == "她把解释咽回去之后，关系为什么还是没有慢慢好起来"

    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    draft_payloads = [payload for _, payload in draft_calls]
    initial_payloads = [payload for payload in draft_payloads if payload.get("polish_instruction") in {None, ""}]
    polished_payloads = [payload for payload in draft_payloads if payload.get("polish_instruction") not in {None, ""}]

    assert len(initial_payloads) == 1
    assert polished_payloads
    polish_signatures = [
        (payload.get("compact_polish_mode") is True, str(payload.get("polish_instruction") or ""))
        for payload in polished_payloads
    ]
    assert len(polish_signatures) == len(set(polish_signatures))

    benchmark_label = "真正让关系缓回来，不是解释，是先接住那一下失望"

    def assert_tracked_article_strategy_bundle(payload: dict[str, object]) -> None:
        assert payload["source_type"] == "tracked_article"
        assert payload["reference_article_hidden"] is True
        assert payload["problem_brief"]["version"] == 1
        assert payload["strategy_card"]["version"] == 1
        assert payload["benchmarks"][0]["reference_label"] == benchmark_label

    for payload in initial_payloads:
        assert_tracked_article_strategy_bundle(payload)

    regular_initial_payloads = [payload for payload in initial_payloads if payload.get("compact_strategy_mode") is not True]
    compact_initial_payloads = [payload for payload in initial_payloads if payload.get("compact_strategy_mode") is True]
    assert regular_initial_payloads
    assert not compact_initial_payloads

    for payload in polished_payloads:
        assert_tracked_article_strategy_bundle(payload)
        assert payload["allow_structure_recomposition"] is True
        assert payload["preserve_structure_anchors"] is False
        assert payload.get("compact_polish_mode") is True
        assert "去模板化重写" in str(payload["polish_instruction"] or "")


def test_generate_draft_auto_polish_skips_extra_quality_retry_by_default(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "夜里安静下来，人才会想起那些一直往后拖的事。",
                "outline_body": "1. 夜里回想\n2. 身体的账\n3. 失去后的空\n4. 别把日子往后押",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "上一次精修后，模板风险还没压够" in instruction:
                    return {
                        "title": "别把日子过反了",
                        "body_markdown": (
                            "# 别把日子过反了\n\n"
                            "夜深了，人才会慢慢看见，自己把哪些真正重要的东西一再往后放。\n\n"
                            "阿杰总说项目结束再休息，可身体不会一直等人腾空。\n\n"
                            "外婆走后，我翻手机时才知道，有些平常时刻当时没留住，后来就真的没有了。\n\n"
                            "想做的事别全押给以后，把今天该顾到的先顾住。"
                        ),
                    }
                return {
                    "title": "别把日子过反了",
                    "body_markdown": (
                        "# 别把日子过反了\n\n"
                        "夜里收拾抽屉时，她翻到那张旧车票，才想起那次说好要去看的海，后来一直没去成。\n\n"
                        "阿杰总说项目结束再休息，可日历翻过去一页又一页，身体和身边人都没有一直等他腾空。\n\n"
                        "外婆走后，她才发现很多想留下来的瞬间，当时都只是顺手放到了以后。\n\n"
                        "想做的事别全押给以后，把今天该顾到的先顾住。"
                    ),
                }

            return {
                "title": "别把日子过反了",
                "body_markdown": (
                    "# 别把日子过反了\n\n"
                    "不是失去了才知道痛，而是很多东西在拥有的时候，就已经被我们慢慢忽略。\n\n"
                    "朋友阿杰总说等忙完这阵就休息，外婆离世后我才发现有些话再也来不及说。\n\n"
                    "从今天开始，别再把重要的东西推到以后。"
                ),
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    outline_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()

    assert draft["title"] == "别把日子过反了"
    assert "从今天开始" not in draft["body_markdown"]
    assert "夜里收拾抽屉" in draft["body_markdown"]
    assert "夜深了" not in draft["body_markdown"]

    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    assert len(draft_calls) == 2
    assert draft_calls[0][1].get("polish_instruction") in {None, ""}
    instructions = [str(call[1].get("polish_instruction") or "") for call in draft_calls[1:]]
    assert any("去模板化重写" in instruction for instruction in instructions)
    assert not any("上一次精修后，模板风险还没压够" in instruction for instruction in instructions)
    assert not any("最后一轮局部清理" in instruction for instruction in instructions)


def test_generate_draft_auto_polish_retries_when_quality_retry_enabled(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "夜里安静下来，人才会想起那些一直往后拖的事。",
                "outline_body": "1. 夜里回想\n2. 身体的账\n3. 失去后的空\n4. 别把日子往后押",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "上一次精修后，模板风险还没压够" in instruction:
                    return {
                        "title": "别把日子过反了",
                        "body_markdown": (
                            "# 别把日子过反了\n\n"
                            "夜深了，人才会慢慢看见，自己把哪些真正重要的东西一再往后放。\n\n"
                            "阿杰总说项目结束再休息，可身体不会一直等人腾空。\n\n"
                            "外婆走后，我翻手机时才知道，有些平常时刻当时没留住，后来就真的没有了。\n\n"
                            "想做的事别全押给以后，把今天该顾到的先顾住。"
                        ),
                    }
                return {
                    "title": "别把日子过反了",
                    "body_markdown": (
                        "# 别把日子过反了\n\n"
                        "日子真正难的，不是忙，而是总把重要的东西放到最后面。\n\n"
                        "不是你不想停下来，而是你总觉得还能再撑一阵。阿杰就是这样，把休息一拖再拖。\n\n"
                        "外婆走后，我才发现很多想留下来的瞬间，当时都没有好好接住。\n\n"
                        "从今天开始，别再把最重要的东西往后放。"
                    ),
                }

            return {
                "title": "别把日子过反了",
                "body_markdown": (
                    "# 别把日子过反了\n\n"
                    "不是失去了才知道痛，而是很多东西在拥有的时候，就已经被我们慢慢忽略。\n\n"
                    "朋友阿杰总说等忙完这阵就休息，外婆离世后我才发现有些话再也来不及说。\n\n"
                    "从今天开始，别再把重要的东西推到以后。"
                ),
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_creative_quality_retry_max_attempts", lambda: 1)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    outline_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()

    assert draft["title"] == "别把日子过反了"
    assert "从今天开始" not in draft["body_markdown"]
    assert "夜深了" in draft["body_markdown"]

    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    assert len(draft_calls) == 3
    assert draft_calls[0][1].get("polish_instruction") in {None, ""}
    instructions = [str(call[1].get("polish_instruction") or "") for call in draft_calls[1:]]
    assert any("去模板化重写" in instruction for instruction in instructions)
    assert any("上一次精修后，模板风险还没压够" in instruction for instruction in instructions)
    assert not any("最后一轮局部清理" in instruction for instruction in instructions)


def test_generate_draft_skips_full_branch_when_compact_candidate_is_already_low_risk(monkeypatch) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "她把消息读完，却没有立刻回。",
                "outline_body": "1. 消息停住\n2. 白天继续硬撑\n3. 身体提醒开始变密\n4. 夜里终于看见自己在往后退",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if payload.get("compact_strategy_mode"):
                return {
                    "title": "消息先回出去了，她才看见自己已经慢下来",
                    "body_markdown": (
                        "# 消息先回出去了，她才看见自己已经慢下来\n\n"
                        "手机震了一下，她先把那句“收到，晚点给你”发了出去，才发现自己还站在门口，没有继续往里走。\n\n"
                        "白天能顶住的事，她照样都顶着。开会、改表、回消息，看起来没什么不对。只是到了晚上，手指停在输入框上更久了，楼梯走到一半也会下意识扶一下栏杆。\n\n"
                        "她没把这些立刻叫成问题，只是顺手往后压。可越往后压，第二天要装作没事的力气就越多。\n\n"
                        "回到家，她把包放下，先坐了两分钟，才去接那杯已经凉掉的水。"
                    ),
                }
            raise AssertionError("full strategy branch should not run when compact candidate is already low risk")

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )
    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "compact-first-low-risk-source",
            "source_name": "夜读关系实验室",
            "title": "真正让人慢下来的，不是某一天，而是一直把自己往后放",
            "url": "https://example.com/compact-first-low-risk-source",
            "author": "北岛",
            "summary": "从身体提醒和日常顺延写人为什么会一点点耗尽。",
            "structure_notes": "动作入口 + 白天硬撑 + 夜里回看。",
            "tags": ["身体提醒", "关系修复"],
        },
    )
    client.post(
        "/api/tracked-articles/compact-first-low-risk-source/to-topic",
        json={
            "slug": "compact-first-low-risk-topic",
            "title": "真正让人慢下来的，不是某一天，而是一直把自己往后放",
            "angle": "身体提醒",
        },
    )

    project_response = client.post(
        "/api/topics/compact-first-low-risk-topic/create-project",
        json={
            "slug": "compact-first-low-risk-project",
            "title": "compact 优先低风险稿",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201

    assert client.post("/api/projects/compact-first-low-risk-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/compact-first-low-risk-project/adopt-strategy-card/1").status_code == 200
    assert client.post("/api/projects/compact-first-low-risk-project/generate-outline").status_code == 201

    draft_response = client.post("/api/projects/compact-first-low-risk-project/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()

    assert draft["title"] == "消息先回出去了，她才看见自己已经慢下来"
    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    assert len(draft_calls) == 1
    initial_payloads = [payload for _, payload in draft_calls if payload.get("polish_instruction") in {None, ""}]
    assert len(initial_payloads) == 1
    assert initial_payloads[0]["compact_strategy_mode"] is True


def test_generate_draft_uses_strategy_first_full_prompt_for_tracked_article_with_adopted_strategy(monkeypatch) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", dict(payload)))
            return {
                "hook": "复查提醒弹出来的时候，她先停了一下。",
                "outline_body": "1. 提醒弹出\n2. 饭点被推迟\n3. 把自己排回今天",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", dict(payload)))
            return {
                "title": "那次复查没有再改期",
                "body_markdown": (
                    "# 那次复查没有再改期\n\n"
                    "复查提醒弹出来的时候，她先停了一下。\n\n"
                    "以前她总说等忙完再去，这次却把日期重新圈回日历上。"
                ),
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "strategy-first-full-draft-source",
            "source_name": "手动录入",
            "title": "别把该照顾自己的事一再往后放",
            "url": "https://example.com/strategy-first-full-draft-source",
            "author": "未知",
            "summary": "从体检复查和生活排序切入，写人怎样把照顾自己重新排回今天。",
            "structure_notes": "现实接口起手 + 顺延代价推进 + 正向回到生活排序。",
            "tags": ["生活排序", "照顾自己"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n体检提醒弹出来，她还是先把工作排在前面。",
            "analysis_structure_mode": "pressure_interface_direct",
        },
    )
    assert create_article.status_code == 201
    create_topic = client.post(
        "/api/tracked-articles/strategy-first-full-draft-source/to-topic",
        json={
            "slug": "strategy-first-full-draft-topic",
            "title": "别把该照顾自己的事一再往后放",
            "angle": "从复查提醒被反复改期切入，写生活顺序怎样一点点被自己重新拿回来。",
        },
    )
    assert create_topic.status_code == 201
    create_project = client.post(
        "/api/topics/strategy-first-full-draft-topic/create-project",
        json={
            "slug": "strategy-first-full-draft-project",
            "title": "strategy first full draft 项目",
            "owner": "editorial",
        },
    )
    assert create_project.status_code == 201
    assert client.post("/api/projects/strategy-first-full-draft-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/strategy-first-full-draft-project/adopt-strategy-card/1").status_code == 200
    assert client.post("/api/projects/strategy-first-full-draft-project/generate-outline").status_code == 201
    draft_response = client.post("/api/projects/strategy-first-full-draft-project/generate-draft")

    assert draft_response.status_code == 201
    draft_payloads = [payload for call_type, payload in fake_generator.calls if call_type == "draft"]
    assert draft_payloads
    draft_payload = draft_payloads[0]
    assert draft_payload["strategy_first_draft_mode"] is True
    assert draft_payload.get("compact_strategy_mode") is None
    assert draft_payload.get("timeout_recovery_mode") is None
    assert draft_payload["source_type"] == "tracked_article"
    assert draft_payload["reference_article_hidden"] is True
    assert draft_payload["problem_brief"]["version"] == 1
    assert draft_payload["strategy_card"]["version"] == 1
    assert draft_payload["benchmarks"]


def test_generate_initial_draft_candidates_runs_full_branch_when_compact_candidate_is_low_risk_but_over_smoothed(
    monkeypatch,
) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(dict(payload))
            if payload.get("compact_strategy_mode"):
                return {
                    "title": "过度顺滑 compact 稿",
                    "body_markdown": "过度顺滑 compact 正文",
                }
            return {
                "title": "常规分支稿",
                "body_markdown": "常规分支正文",
            }

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        return SimpleNamespace(score=0, level="低", hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)
    monkeypatch.setattr(
        workbench,
        "_looks_like_over_smoothed_tracked_article_candidate",
        lambda markdown: markdown == "过度顺滑 compact 正文",
    )
    monkeypatch.setattr(workbench, "_looks_like_tracked_article_fragment_chain_candidate", lambda _: False)

    generator = FakeGenerator()
    candidates = workbench._generate_initial_draft_candidates(
        project={"source_type": "tracked_article", "slug": "compact-over-smoothed-demo"},
        generator=generator,
        draft_payload={},
    )

    assert len(generator.calls) == 2
    assert generator.calls[0]["compact_strategy_mode"] is True
    assert generator.calls[1]["full_fallback_single_attempt_mode"] is True
    assert candidates == [
        ("过度顺滑 compact 稿", "过度顺滑 compact 正文"),
        ("常规分支稿", "常规分支正文"),
    ]


def test_generate_initial_draft_candidates_skips_compact_branches_for_strategy_first_draft_mode() -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(dict(payload))
            return {
                "title": "默认首稿",
                "body_markdown": "默认首稿正文",
            }

    generator = FakeGenerator()
    candidates = workbench._generate_initial_draft_candidates(
        project={"source_type": "tracked_article", "slug": "strategy-first-draft-demo"},
        generator=generator,
        draft_payload={
            "source_type": "tracked_article",
            "problem_brief": {"version": 1, "clarified_problem": "先把顺序落差写清。"},
            "strategy_card": {"version": 1, "structure_mode": "response_priority"},
            "benchmarks": [{"reference_label": "原文"}],
        },
    )

    assert len(generator.calls) == 1
    assert "compact_strategy_mode" not in generator.calls[0]
    assert "timeout_recovery_mode" not in generator.calls[0]
    assert generator.calls[0]["strategy_first_draft_mode"] is True
    assert candidates == [("默认首稿", "默认首稿正文")]


def test_generate_initial_draft_candidates_retries_strategy_first_branch_with_timeout_recovery_on_transient_error(
    caplog,
) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(dict(payload))
            if payload.get("timeout_recovery_mode"):
                return {
                    "title": "救援首稿",
                    "body_markdown": "救援首稿正文",
                }
            raise workbench.APITimeoutError(request=None)

    caplog.set_level("WARNING")

    generator = FakeGenerator()
    candidates = workbench._generate_initial_draft_candidates(
        project={"source_type": "tracked_article", "slug": "strategy-first-recovery-demo"},
        generator=generator,
        draft_payload={
            "source_type": "tracked_article",
            "problem_brief": {"version": 1, "theme_axis": "先把顺序落差写清。"},
            "strategy_card": {"version": 1, "positive_direction": "回到被护住的安稳。"},
            "benchmarks": [{"reference_label": "原文"}],
            "reference_article_hidden": True,
            "outline": {
                "hook": "一句“没事，有我”背后那点喉咙发紧。",
                "outline_body": "1. 先写硬撑\n2. 再写代价\n3. 最后回到安稳",
            },
            "project_title": "夜里那句“没事，有我”",
        },
    )

    assert len(generator.calls) == 2
    assert generator.calls[0]["strategy_first_draft_mode"] is True
    assert generator.calls[1]["timeout_recovery_mode"] is True
    assert "strategy_first_draft_mode" not in generator.calls[1]
    assert "benchmarks" not in generator.calls[1]
    assert "reference_article_hidden" not in generator.calls[1]
    assert "problem_brief" in generator.calls[1]
    assert "strategy_card" in generator.calls[1]
    assert candidates == [("救援首稿", "救援首稿正文")]
    assert "Strategy-first draft transient failure for project strategy-first-recovery-demo" in caplog.text


def test_generate_initial_draft_candidates_surfaces_upstream_failure_when_strategy_first_recovery_also_fails(
    caplog,
) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(dict(payload))
            raise workbench.APITimeoutError(request=None)

    caplog.set_level("WARNING")

    generator = FakeGenerator()
    with pytest.raises(HTTPException) as exc_info:
        workbench._generate_initial_draft_candidates(
            project={"source_type": "tracked_article", "slug": "strategy-first-recovery-full-fallback-demo"},
            generator=generator,
            draft_payload={
                "source_type": "tracked_article",
                "problem_brief": {"version": 1, "theme_axis": "先把顺序落差写清。"},
                "strategy_card": {"version": 1, "positive_direction": "回到被护住的安稳。"},
                "benchmarks": [{"reference_label": "原文"}],
                "reference_article_hidden": True,
                "outline": {
                    "hook": "一句“没事，有我”背后那点喉咙发紧。",
                    "outline_body": "1. 先写硬撑\n2. 再写代价\n3. 最后回到安稳",
                },
                "project_title": "夜里那句“没事，有我”",
            },
        )

    assert len(generator.calls) == 2
    assert generator.calls[0]["strategy_first_draft_mode"] is True
    assert generator.calls[1]["timeout_recovery_mode"] is True
    assert exc_info.value.status_code == 503
    assert str(exc_info.value.detail).startswith("正文生成失败：当前文本 AI 服务暂时不可用，请稍后重试。")
    assert "Strategy-first draft transient failure for project strategy-first-recovery-full-fallback-demo" in caplog.text
    assert "using local draft fallback" not in caplog.text


def test_generate_initial_draft_candidates_surfaces_upstream_failure_when_non_strategy_first_recovery_fails(
    monkeypatch,
    caplog,
) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(dict(payload))
            raise workbench.APITimeoutError(request=None)

    caplog.set_level("WARNING")
    monkeypatch.setattr(
        workbench,
        "_resolve_tracked_article_expected_selection_mode",
        lambda payload: "everyday_warmth_return",
    )
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    generator = FakeGenerator()
    with pytest.raises(HTTPException) as exc_info:
        workbench._generate_initial_draft_candidates(
            project={"source_type": "tracked_article", "slug": "responsibility-nonstrategy-recovery-demo"},
            generator=generator,
            draft_payload={
                "source_type": "tracked_article",
                "project_title": "肩上有责任的人，心里也要留一盏灯",
                "topic_title": "肩上有责任的人，心里也要留一盏灯",
                "topic_angle": "从家里临时有事、自己先把顺序理清切入，写责任怎样把日子慢慢托稳。",
                "reference_article_body_markdown": "这些年来，你是不是也是这样：生病了不敢请假，怕影响这个月的绩效；电话的那头，是父母、孩子和账单。",
                "outline": {
                    "hook": "很多中年人的一通来电，听着只是家里有事，心里却已经开始替所有人排顺序。",
                    "outline_body": (
                        "### 1. 从一通来电或一个日历安排写起\n"
                        "### 2. 说清责任怎样让人多想一步\n"
                        "### 3. 写出责任怎样回到日常\n"
                        "### 4. 结尾回到家里那点安稳"
                    ),
                },
                "strategy_card": {
                    "version": 1,
                    "structure_mode": "everyday_warmth_return",
                    "positive_direction": "结尾回到家里仍亮着的灯、有人一起分担和日子被慢慢托稳。",
                },
                "problem_brief": {"version": 1, "theme_axis": "主线是责任怎样慢慢换来家里的踏实。"},
            },
        )

    assert len(generator.calls) == 2
    assert "timeout_recovery_mode" not in generator.calls[0]
    assert generator.calls[1]["timeout_recovery_mode"] is True
    assert exc_info.value.status_code == 503
    assert str(exc_info.value.detail).startswith("正文生成失败：当前文本 AI 服务暂时不可用，请稍后重试。")
    assert "Tracked article draft transient failure for project responsibility-nonstrategy-recovery-demo" in caplog.text
    assert "using local draft fallback" not in caplog.text


def test_clean_local_fallback_instruction_phrase_strips_outline_labels() -> None:
    cleaned = workbench._clean_local_fallback_instruction_phrase(
        "责任怎样把人推着往前：上有父母、下有孩子、工作也不敢松，很多人慢慢学会先稳住别人，再往后放自己。"
    )

    assert cleaned == "上有父母、下有孩子、工作也不敢松，很多人慢慢学会先稳住别人，再往后放自己。"


def test_build_local_tracked_article_draft_fallback_avoids_instruction_leakage_for_responsibility_payload() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "topic_angle": "责任把人往前推，也让辛苦慢慢显出意义",
            "reference_article_body_markdown": "中年人的世界，半生风雨，半生奔波。电话的那头，是父母，是孩子，是账单。生病了不敢请假，怕影响这个月的绩效。",
            "outline": {
                "hook": "一句“没事，有我”背后那点喉咙发紧。",
                "outline_body": (
                    "1. 开头先落一句“没事，有我”背后的发紧\n"
                    "2. 责任怎样把人推着往前：上有父母、下有孩子、工作也不敢松，很多人慢慢学会先稳住别人，再往后放自己。\n"
                    "3. 责任怎样回到日常：父母少一点担心，孩子多一点底气，家里的灯还亮着，让辛苦落成看得见的踏实。\n"
                    "4. 结尾回到家里仍被护住的安稳、有人还在等你和这些辛苦没有白熬。"
                ),
            },
            "strategy_card": {
                "positive_direction": "结尾回到家里仍被护住的安稳、有人还在等你和这些辛苦没有白熬，不要收成苦难赞歌或空泛打气。",
                "scene_anchor_requirements": ["电话响起", "学校门口等孩子"],
                "quotable_line_seeds": ["那句“没事，有我”背后，往往压着一个家的分量。"],
            },
            "problem_brief": {
                "theme_axis": "主线是很多成年人为什么会把“我没事”顶在前面。",
                "core_conflict": "明明很疲惫了，还是要把那句“有我”稳稳顶在前面。",
            },
        }
    )

    assert title in {
        "家里一有事，你总会先把家稳住",
        "肩上有责任的人，心里也要留一盏灯",
    }
    assert "责任怎样把人推着往前：" not in body_markdown
    assert "代价落在哪里：" not in body_markdown
    assert "但这篇文章真正想托住的" not in body_markdown
    assert "你你" not in body_markdown
    assert "生病了想请假的时候" not in body_markdown
    assert "这个月的绩效" not in body_markdown
    assert "缴费窗口前" not in body_markdown
    assert "没事，有我" not in body_markdown
    assert any(
        fragment in body_markdown
        for fragment in (
            "这几样一下都排到前面了",
            "先看哪张单子得今天处理",
            "先把这个月的工作、父母和孩子的事排了一遍",
        )
    )
    assert "不是天生能扛" not in body_markdown
    assert "不是天生能把事情接住" not in body_markdown
    assert "学校门口" not in body_markdown
    assert any(
        fragment in body_markdown
        for fragment in (
            "想到这儿，心里会松一点。",
            "那个瞬间人不会一下子被治愈，却会真真切切地松一口气。",
        )
    )
    assert any(
        fragment in body_markdown
        for fragment in (
            "替家里多想的每一步，都会慢慢变成日子的底气。",
            "你替家里挡过的风，也会慢慢变成照回自己身上的光。",
        )
    )
    assert "身体先报警" not in body_markdown
    assert "情绪硬吞" not in body_markdown
    assert "身体会记账" not in body_markdown


def test_rewrite_tracked_article_danger_fragments_keeps_response_priority_meishi_scene() -> None:
    source = (
        "真正关心你的人，是哪怕相隔千里，也能透过你的一句“我没事”，听出你心底的“我有点累”。"
        "真正关心你的人，总能穿透那些云淡风轻的表象，看到你背后的波澜。"
    )
    body = "真正的在意，不会被你那句“我没事”轻轻带过去。"

    rewritten = workbench._rewrite_tracked_article_danger_fragments(
        source_markdown=source,
        body_markdown=body,
    )

    assert "我没事" in rewritten
    assert "先稳住场面" not in rewritten

def test_build_local_tracked_article_responsibility_fallback_avoids_reference_danger_fragments() -> None:
    source = (
        "中年人的世界，半生风雨，半生奔波。电话的那头，是父母日渐佝偻的身影，"
        "是孩子越来越高的补习费用，是每个月如期而至的各种账单。电话的这头，"
        "你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。"
        "生病了不敢请假，怕影响这个月的绩效；委屈了不敢辞职，因为你要撑起一个家的重量。"
        "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；慢慢长大的孩子，拥有了对生活说“不”的底气。"
        "你熬过的每一个黑夜，都在为身边所爱之人撑起一片晴空。"
    )
    payload = {
        "topic_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
        "topic_angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样让辛苦最后落到家里的安稳里。",
        "reference_article_body_markdown": source,
        "outline": {
            "hook": "一句“没事，有我”背后那点喉咙发紧。",
            "outline_body": (
                "1. 开头先落一句“没事，有我”背后的发紧\n"
                "2. 责任怎样把人推着往前：上有父母、下有孩子、工作也不敢松，很多人慢慢学会先稳住别人，再往后放自己。\n"
                "3. 责任怎样回到日常：父母少一点担心，孩子多一点底气，家里的灯还亮着，让辛苦落成看得见的踏实。\n"
                "4. 结尾回到家里仍被护住的安稳、有人还在等你和这些辛苦没有白熬。"
            ),
        },
        "strategy_card": {
            "structure_mode": "responsibility_shelter",
            "positive_direction": "结尾回到家里仍被护住的安稳、有人还在等你和这些辛苦没有白熬。",
        },
        "problem_brief": {
            "theme_axis": "主线是很多成年人为什么会把“我没事”顶在前面。",
            "core_conflict": "明明很疲惫了，还是要把那句“有我”稳稳顶在前面。",
        },
    }

    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(payload)
    assets = workbench._build_local_assets_fallback(
        project_title=title,
        topic_title=title,
        topic_angle=str(payload["topic_angle"]),
        draft_title=title,
        draft_body_markdown=body_markdown,
    )

    combined = "\n".join([title, body_markdown, assets["cover_copy"], assets["social_teaser"]])
    for fragment in ("没事，有我", "这个月的绩效", "缴费窗口前", "一个家的"):
        assert fragment not in combined
    assert title in {
        "电话一响，你先翻日历",
        "电话一响，你先把顺序往前排",
        "手机一亮，你先算今天怎么排",
    }
    assert "电话一响" in body_markdown
    assert any(fragment in body_markdown for fragment in ("爸妈", "父母"))
    assert any(fragment in body_markdown for fragment in ("孩子", "这个家"))
    assert any(
        fragment in body_markdown
        for fragment in (
            "很多中年人的“我没事”",
            "先说出口的那句“我没事”",
        )
    )
    assert any(
        fragment in body_markdown
        for fragment in (
            "爸妈那边谁去跑",
            "哪笔开销得先处理过一遍",
            "把自己往后放半步",
        )
    )
    assert any(
        fragment in body_markdown
        for fragment in (
            "最难的不是事情一下都来了，是轮到你时，还得先装作心里已经有数。",
            "很多时候你不是比谁更有答案，只是知道这会儿不能让家里那头先乱。",
            "你顾不上先想自己累不累，只能先把最急的那件事接过去。",
        )
    )
    assert "夜里躺下以后，脑子" in body_markdown
    assert "不是谁天生更会扛" not in body_markdown
    assert "所谓人间安稳，从来不是生活忽然不难了。" not in body_markdown
    assert "天亮之前总有一段路最黑" not in body_markdown
    assert "你忙这一圈，心里惦记的其实很简单：爸妈来电话别先慌，孩子碰上事知道还有人顶着。" in body_markdown
    assert any(
        fragment in body_markdown
        for fragment in (
            "也该轮到别人心疼你一下。",
            "别总等所有事都稳了，才想起自己也累。",
        )
    )
    assert "怎么天天都是这些事" not in body_markdown
    assert assets["cover_copy"] in {
        "你扛住的那些日常，后来都在替家里换安稳。",
        "你替一家人扛住风雨，也别忘了给自己留一盏灯。",
    }
    assert any(
        fragment in assets["social_teaser"]
        for fragment in (
            "这些事你都得先想在前面",
            "那句“没事”放在前面久了",
        )
    )
    assert any(
        fragment in assets["social_teaser"]
        for fragment in (
            "家里那几个人的心，才会跟着慢慢落下来",
            "家里的日子才能继续照常往前走",
            "家里的那点踏实会替你记着",
        )
    )
    assert "心里很快就排了一遍：" not in assets["social_teaser"]


def test_build_local_tracked_article_responsibility_fallback_rewrites_diagnosis_outline_points() -> None:
    payload = {
        "topic_title": "肩上有责任的人，心里也要留一盏灯",
        "topic_angle": "从家里临时有事、自己先把顺序理清切入，写责任怎样变成一家人的安稳。",
        "reference_article_body_markdown": (
            "电话的那头，是父母，是孩子，是账单。生病了不敢请假，"
            "委屈了不敢辞职。后来父母安心，孩子有底气，伴侣有屋檐。"
        ),
        "outline": {
            "hook": "电话这头的人，常常一边扛住生活的重量，一边还得悄悄给自己留住不塌下去的那点光。",
            "outline_body": (
                "### 一、从一通电话写起：电话那头是父母、孩子和账单，电话这头的人没有退路，只能先把情绪收起来，把该接住的现实一件件接住。\n"
                "### 二、为什么会这样：责任集中落在一个人身上，往往不是因为他更强，而是因为家庭分工、经济压力和长期习惯，慢慢把“能扛的人”推成了默认的承担者。\n"
                "### 三、代价落在哪：表面上日子还在往前走，实际上被透支的是睡眠、耐心、身体和自我感受，很多人不是突然崩的，而是在长期压缩自己之后变得麻木。\n"
                "### 四、现实怎么顶上来并走向结尾：真正踏实的自我确认，不是逼自己永远坚强，而是承认自己也会累、也值得被照顾，在责任之外留一盏灯，让自己有力气把日子继续稳稳撑下去。"
            ),
        },
        "strategy_card": {
            "structure_mode": "responsibility_shelter",
            "positive_direction": "这些认真不必夸大，但自己没有白忙，眼下的付出正在慢慢变成家人的安稳。",
        },
        "problem_brief": {
            "theme_axis": "成年人持续承受生活压力的意义，往往在为家人换来可感的安稳。",
            "core_conflict": "责任最重的地方，不是一个人有多厉害，而是他心里一直装着想守护的人。",
        },
    }

    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(payload)

    assert title == "肩上有责任的人，心里也要留一盏灯"
    for fragment in (
        "家庭分工",
        "经济压力",
        "长期习惯",
        "默认的承担者",
        "被透支的是睡眠",
        "自我感受",
        "长期压缩",
        "麻木",
        "不是突然崩",
    ):
        assert fragment not in body_markdown
    assert "父母的事要惦记，孩子的事要跟上，工作那头也不能松" in body_markdown
    assert "父母少一点担心，孩子多一点底气，家里多一点踏实" in body_markdown
    assert "桌上给你留着一口热饭，屋里有人问你累不累。" in body_markdown
    assert "一个家要走得稳，靠的是彼此都愿意搭一把手。" in body_markdown
    assert "替家里多想的每一步，都会慢慢变成日子的底气。" in body_markdown


def test_local_fallback_mode_promotes_responsibility_variant_before_everyday_warmth() -> None:
    source = (
        "电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
        "电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。"
        "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；"
        "慢慢长大的孩子，拥有了对生活说“不”的底气；深深爱着的伴侣，也能在风雨来临时有一处温暖的屋檐庇护。"
    )
    payload = {
        "topic_title": "肩上有责任的人，心里也要留一盏灯",
        "topic_angle": "从家里临时有事、自己先把顺序理清切入，写责任怎样变成一家人的安稳。",
        "reference_article_body_markdown": source,
        "reference_article_structure_notes": "先从一句“没事，有我”和电话账单这些现实重量切入，中段写责任怎样让人把自己往后收，结尾落回家里安稳和这些辛苦没有白熬。",
        "analysis_structure_mode": "everyday_warmth_return",
        "strategy_card": {
            "structure_mode": "everyday_warmth_return",
            "reader_situation": "习惯先把父母、孩子和伴侣安顿好，也努力给家里留住踏实感的人",
            "conflict_frame": "真正让人愿意多走一步的，常常不是某一笔开销或某一次加班，而是你知道父母、孩子、伴侣和这个家，都因为你的认真多了一点踏实。",
            "hook_trigger": "家里临时有事、自己先把顺序理清，让一家人跟着稳下来的当场。",
            "positive_direction": "结尾回到家里仍亮着的灯、有人一起分担和日子被慢慢托稳，不要收成空泛吃苦叙事、消耗诊断或空泛打气。",
        },
        "problem_brief": {
            "theme_axis": "责任为什么会让人多想一步，也写这些认真托住日子的时刻怎样变成一家人的安稳。",
            "core_conflict": "责任最重的地方，不是一个人有多厉害，而是他心里一直装着想守护的人。",
        },
        "outline": {
            "hook": "家里临时有事、自己先把顺序理清，让一家人跟着稳下来的当场。",
            "outline_body": (
                "### 1. 写责任怎样让人多想一步、把日子安排稳；也写那些认真托住日子的时刻，后来为什么会在父母、孩子、伴侣和家里的安稳里慢慢显出意义。\n"
                "### 2. 责任最重的地方，不是一个人有多厉害，而是他心里一直装着想守护的人。\n"
                "### 3. 眼前的日常一旦被放轻，人就算站在热闹里，心里也还是不踏实。\n"
                "### 4. 家里仍亮着的灯、有人一起分担和日子被慢慢托稳。"
            ),
        },
    }

    assert workbench._resolve_local_fallback_mode(payload) == "responsibility_shelter"

    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(payload)

    assert title == "肩上有责任的人，心里也要留一盏灯"
    assert "年轻时总觉得幸福要有很大的样子" not in body_markdown
    assert "有个朋友前阵子说，他最开心的一天" not in body_markdown
    assert "先把家里那头安顿好" in body_markdown
    assert "一盒药提前买好，把校服洗出来晾着，把冰箱里缺的菜顺手记下来" in body_markdown
    assert "把日子往前托的人，也该被日子温柔托住。" in body_markdown


def test_should_use_local_responsibility_shelter_fallback_even_with_conflicting_strategy_bundle() -> None:
    payload = {
        "source_type": "tracked_article",
        "project_title": "责任终稿清洗写库项目",
        "topic_title": "肩上有责任的人，心里也要留一盏灯",
        "topic_angle": "从手机亮起时先想家里的安排切入，写责任怎样把日子慢慢托稳。",
        "draft_title": "肩上有责任的人，心里也要留一盏灯",
        "recommended_title": "把家里日子托稳的人，也该被好好心疼",
        "cover_copy": "你替一家人多想的那几步，最后都会落成家里的踏实。",
        "social_teaser": "家里一有动静，你还没来得及细想，心里已经开始替家里排顺序。",
        "reference_article_body_markdown": (
            "中年人的世界，半生风雨，半生奔波。电话的那头，是父母，是孩子，是账单。"
            "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇；"
            "慢慢长大的孩子，拥有了对生活说不的底气。"
        ),
        "body_markdown": (
            "家里一有动静，你还没来得及细想，心里已经开始替家里排顺序。\n\n"
            "你把日历翻来翻去，把能挪的时间先挪出来，把能缓一口的事先记在纸上。"
            "最难的常常在这里：每一件事都在等你给个说法。也该给自己留一点余地。"
        ),
        "problem_brief": {
            "theme_axis": "主线是人为什么总把执念、遗憾或舍不得误认成非要抓住不放，后来又怎样把这段经历安放回自己的人生里。",
            "core_conflict": "真正把人困住的，不是没有答案，而是总把舍不得放手误认成还有希望。",
        },
        "strategy_card": {
            "structure_mode": "emotional_engine_direct",
            "opening_move": "先抓误认被点破的那一下。",
            "positive_direction": "把那段路安放好，今天的日子才会重新朝前走。",
        },
    }

    assert workbench._uses_local_responsibility_midlife_variant(payload) is True
    assert workbench._should_use_local_responsibility_shelter_fallback(payload) is True
    assert workbench._resolve_local_fallback_mode(payload) == "responsibility_shelter"


def test_final_tracked_article_guard_cleans_live_responsibility_not_ab_pattern_family() -> None:
    candidate_markdown = (
        "电话的那头，是父母、孩子和一笔笔现实开销。电话这头，是一个人把不容易压住，继续把日子顶住的沉默。\n\n"
        "很多成年人先想到的，不是自己想要什么，而是家里缺什么。生活就不再只是“过得去”，而是要把每一件事都放回它该去的位置。\n\n"
        "这不是谁天生更能把事情接住，而是责任会把人往前推半步。\n\n"
        "责任重的时候，最明显的变化不是人变得多厉害，而是心里装的人更多了。不是不想要，而是更愿意把有限的力气，先用在能让家里安稳的地方。\n\n"
        "金句也许很朴素：真正撑起一家人的，不是轰轰烈烈的证明，而是日复一日的安排。真正让人继续往前走的，也不是外人的认可，而是你知道，自己没有白忙。\n\n"
        "肩上的责任并不只是在消耗你，它也在悄悄回报你。\n\n"
        "而心里那盏灯，也要记得留着。不是为了照给谁看，是为了你在忙完一圈之后，还能认得回家的路，也认得自己。\n\n"
        "金句是：人可以很累，但别把自己活成一盏只照别人、不照自己的灯。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in (
        "电话的那头，是父母",
        "不是自己想要什么，而是",
        "不再只是“过得去”，而是",
        "这不是谁天生更能把事情接住，而是",
        "不是人变得多厉害，而是",
        "不是不想要，而是",
        "金句也许很朴素：",
        "金句是：",
        "不是轰轰烈烈的证明，而是",
        "也不是外人的认可，而是",
        "并不只是在消耗你",
        "不是为了照给谁看，是为了",
    ):
        assert forbidden not in repaired
    assert "家里一有事，父母、孩子、账单和当天的安排，都会先挤到心里。" in repaired
    assert "很多成年人第一反应，是先想起家里还缺什么" in repaired
    assert "责任会把人往前推半步。" in repaired
    assert "最明显的变化，是心里装的人更多了。" in repaired
    assert "真正撑起一家人的，常常就是日复一日的安排。" in repaired
    assert "肩上的责任也会在日子里慢慢回报你" in repaired

def test_final_tracked_article_guard_cleans_live_responsibility_model_residue() -> None:
    candidate_markdown = (
        "电话的那头，是父母、孩子和现实开销。电话这头，是一个人把不容易咽回去，把答案先准备好。\n\n"
        "很多成年人都会先把家里的事理顺，不是因为自己天生更能把事情接住，而是因为心里清楚，日子不能只靠情绪往前推。\n\n"
        "真正重的地方，不是一个人有多厉害，而是他心里一直装着想守护的人。"
        "一个人加班到很晚，不只是为了把工作做完，也是在把明天的麻烦往前挪一挪。\n\n"
        "成年人会慢慢明白，生活里的稳，不是等风停了才有，而是边走边收拾出来的。\n\n"
        "很多人不是不累，只是知道自己一松，家里的地面就会晃。\n\n"
        "“责任不是把自己磨得更硬，而是把日子过得更稳。”\n\n"
        "“心里留一盏灯，不是为了照给别人看，是为了你知道，自己还走得下去。”"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in (
        "电话的那头，是父母",
        "不是因为自己天生更能把事情接住",
        "不是一个人有多厉害，而是",
        "不只是为了把工作做完",
        "不是等风停了才有，而是",
        "不是不累，只是",
        "责任不是把自己磨得更硬，而是",
        "不是为了照给别人看，是为了",
    ):
        assert forbidden not in repaired
    assert "家里一有事，父母、孩子和这个月的安排就会先排到心里。" in repaired
    assert "真正重的地方，藏在那些一直想守护的人身上。" in repaired
    assert "生活里的稳，要边走边慢慢收拾出来。" in repaired
    assert "心里留一盏灯，是为了提醒自己" in repaired

def test_final_tracked_article_guard_cleans_live_31_responsibility_not_ab_output() -> None:
    candidate_markdown = (
        "电话那头是父母、孩子和现实开销，电话这头是沉默、认真和继续往前的人。\n\n"
        "很多成年人先把家里的事理顺，不是因为自己天生更能把事情接住，而是因为一旦肩上有了责任，心里就会自动多想一步。先看房租，再看学费；\n\n"
        "先算眼下这段时间的药费，再想下个月的饭桌。不是不想轻松一点，是知道日子不能只凭情绪往前走。\n\n"
        "成年人承受生活压力，意义常常不在自我成就，而在让身边的人少受一点惊。你会发现，很多坚持不是为了证明什么，而是为了把一家人的日子慢慢收拢起来。\n\n"
        "人到了一定年纪，最难得的不是逞强，是不乱。\n\n"
        "“真正的责任，不是把自己耗尽，而是在不容易里仍然留住照亮别人的那一点心气。”\n\n"
        "走到今天，你已经不是在一个人先顶着了，你是在把生活往更稳的地方推。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in (
        "电话那头是父母",
        "不是因为自己天生更能把事情接住",
        "不是不想轻松一点，是知道",
        "不是为了证明什么，而是",
        "不是逞强，是不乱",
        "不是把自己耗尽，而是",
        "不是在一个人先顶着",
    ):
        assert forbidden not in repaired
    assert "家里的事一冒出来，人就会先把眼前的顺序理清。" in repaired
    assert "一旦肩上有了责任，心里就会自动多想一步。" in repaired
    assert "也想轻松一点，只是知道日子不能只凭情绪往前走。" in repaired
    assert "很多坚持，是为了把一家人的日子慢慢收拢起来。" in repaired
    assert "真正的责任，是在不容易里仍然留住一点照亮日子的心气。" in repaired
    assert "走到今天，你是在把生活往更稳的地方推。" in repaired


def test_final_tracked_article_guard_cleans_live_32_responsibility_phone_opening_residue() -> None:
    candidate_markdown = (
        "电话响起来的时候，很多成年人都会先停一下。\n\n"
        "电话那头是父母问近况，孩子问什么时候回家，账单提醒还差一点。电话这头，是一个人把不容易压低，把声音放稳，先说“没事，我来处理”\n\n"
        "电话那头，是父母、孩子和账单。电话这头，是一个人把不容易按下去，先把今天撑住。\n\n"
        "这很多责任常常赶在同一段日子里压上来，也不是谁比谁更坚强。\n\n"
        "撑住一家人的人，未必总是最闪亮的那一个。\n\n"
        "路还长，但你不是白走。你是在用自己的方式，把日子往能住下去的方向，慢慢推过去。\n\n"
        "我没有白撑，我真的让一些人过得更安稳了。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in ("电话那头", "电话这头", "这很多责任", "先把今天撑住", "撑住一家人", "但你不是白走", "你是在用", "白撑"):
        assert forbidden not in repaired
    assert "家里一有事，父母、孩子、账单和当天的安排，都会先挤到心里。" in repaired
    assert "很多责任常常赶在同一段日子里压上来" in repaired
    assert "把家放在心上的人" in repaired
    assert "路还长，但这一路不是白走。" in repaired
    assert "我没有白忙" in repaired


def test_final_tracked_article_guard_cleans_live_34_responsibility_negative_not_ab_residue() -> None:
    candidate_markdown = (
        "手机刚震了一下，你还没接起来，心里已经开始替家里排顺序。\n\n"
        "照顾、还贷、教育、养老、职场评价交叠在一起，真正拖垮人的不是某一件事，而是长期没有缓冲、没有退路、也没有被看见。你先把能协调的时间圈出来，再给家里留出一个更稳的安排。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in ("真正拖垮", "不是某一件事，而是", "没有缓冲", "没有退路"):
        assert forbidden not in repaired
    assert "真正让人不容易的，是很多事挤在一起，还要把家里的节奏稳住。" in repaired


def test_responsibility_shelter_result_field_cleanup_removes_live_34_intro_not_ab_skeleton() -> None:
    cleaned = workbench._sanitize_responsibility_shelter_result_fields(
        ai_result={
            "social_teaser": "手机刚震一下，你还没接，心里已经先替家里排好了顺序。成年人的辛苦，很多时候不是为了证明自己，而是为了让身边的人更安心。",
            "intro_options": [
                "手机刚震一下，你还没接，心里已经先替家里排好了顺序。成年人的辛苦，很多时候不是为了证明自己，而是为了让身边的人更安心。",
            ],
        },
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown="电话、父母、孩子、家里、账单、责任和安稳都在同一篇文章里。",
        reference_source_markdown="电话的那头，是父母、孩子和各种账单。电话这头只能说：没事，有我。",
        text_fields=("social_teaser",),
        list_fields=("intro_options",),
    )

    combined = "\n".join([str(cleaned["social_teaser"]), *[str(item) for item in cleaned["intro_options"]]])
    for forbidden in ("不是为了证明自己，而是", "不是为了证明自己", "而是为了"):
        assert forbidden not in combined
    assert "这份辛苦，很多时候都落在让身边的人更安心这件事上。" in combined


def test_final_tracked_article_guard_cleans_live_35_responsibility_not_ab_cluster() -> None:
    candidate_markdown = (
        "电话这头的人，常常不是不累，而是还要把顺序理清。\n\n"
        "很多成年人的第一反应，不是先问自己想要什么，而是先想家里缺什么。孩子的学费、父母的身体、房租水电、下个月的安排，都会在心里过一遍。不是他们天生更能把事情接住，而是责任一落下来，人就会自然地多想一步，把眼前的日子先理顺。\n\n"
        "责任真正改变一个人的地方，不是让他变得多强，而是让他变得更稳。以前觉得差不多就行的事，后来会提前确认；\n\n"
        "以前会拖一拖的决定，后来会尽快落地。不是因为心变硬了，是因为知道，家里有人会等一个明确的结果，等一个不让人慌的回应。\n\n"
        "一个人肩上有了要守的人，做事的重心就会悄悄变。很多时候，努力不是为了证明自己，而是为了让家里少一点悬着的心。\n\n"
        "责任重的时候，最怕的不是忙，而是心里只剩下忙。人不能一直被事务推着走，也要给自己留一点亮。心里也要知道：我不是在白撑，我是在把一家人的生活慢慢稳住。\n\n"
        "“真正托住一家人的，不是豪言壮语，是那些一次次没有缺席的回应。”\n\n"
        "那些你为家人留出来的余地，都不是空的。它们正在一点点变成安稳。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in (
        "不是不累，而是",
        "不是先问自己想要什么，而是",
        "不是他们天生更能把事情接住，而是",
        "不是让他变得多强，而是",
        "后来会提前确认；",
        "不是因为心变硬了，是因为",
        "不是为了证明自己，而是",
        "不是忙，而是",
        "我不是在白撑，我是在",
        "不是豪言壮语，是",
    ):
        assert forbidden not in repaired
    summary = workbench.evaluate_ai_flavor_risk(title="肩上有责任的人，心里也要留一盏灯", body_markdown=repaired)
    assert not any("不是A，是B" in hit for hit in summary.hits)
    assert not any("截断残句" in hit for hit in summary.hits)
    assert "电话这头的人也会累，只是还要先把顺序理清。" in repaired
    assert "责任真正改变一个人的地方，是让人慢慢变得更稳。" in repaired
    assert "我没有白忙，我正在把一家人的生活慢慢稳住。" in repaired


def test_final_tracked_article_guard_cleans_live_36_responsibility_phone_and_label_residue() -> None:
    candidate_markdown = (
        "电话的那头是父母、孩子和现实开销，电话这头，是一个人把不容易压住、继续认真往前走的安静。\n\n"
        "很多成年人到了某个阶段，想的第一件事不再是自己想要什么，而是家里先缺什么。\n\n"
        "你会发现，真正让人停不下来、也放不下的，是“家里不能乱”。这四个字很轻，压在心里却很重。\n\n"
        "真正的责任，是让家人在你的稳里，慢慢过上稳的日子。另一句是：你今天多做的那一点安排，明天就会变成家人少受的一点惊。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in (
        "电话的那头",
        "电话这头",
        "不再是自己想要什么，而是",
        "你会发现",
        "另一句是",
        "你的稳里",
        "少受的一点惊",
    ):
        assert forbidden not in repaired
    assert "家里一有事，父母、孩子、账单和当天的安排，都会先挤到心里。" in repaired
    assert "很多成年人到了某个阶段，第一反应会先落到家里的安排上。" in repaired
    assert "慢慢也就明白，真正让人停不下来、也放不下的，是“家里不能乱”。" in repaired
    assert "真正的责任，是让家人在你的安排里，慢慢过上更踏实的日子。" in repaired
    assert "家人少一点慌张" in repaired


def test_responsibility_shelter_result_field_cleanup_removes_live_36_publish_residue() -> None:
    cleaned = workbench._sanitize_responsibility_shelter_result_fields(
        ai_result={
            "abstract": "电话的那头是父母、孩子和现实开销，电话这头，是一个人继续往前走。读到最后你会发现，那些认真没有白忙。",
            "publish_lead": "真正的责任，是让家人在你的稳里，慢慢过上稳的日子。另一句是：你今天多做的安排，会让家人少受的一点惊。",
            "intro_options": [
                "很多成年人到了某个阶段，想的第一件事不再是自己想要什么，而是家里先缺什么。你会发现，责任会让人多想一步。",
            ],
        },
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown="电话、父母、孩子、家里、账单、责任和安稳都在同一篇文章里。",
        reference_source_markdown="电话的那头，是父母、孩子和各种账单。电话这头只能说：没事，有我。",
        text_fields=("abstract", "publish_lead"),
        list_fields=("intro_options",),
    )

    combined = "\n".join([str(cleaned["abstract"]), str(cleaned["publish_lead"]), *[str(item) for item in cleaned["intro_options"]]])
    for forbidden in ("电话的那头", "电话这头", "读到最后你会发现", "你会发现", "另一句是", "你的稳里", "少受的一点惊", "不再是自己想要什么，而是"):
        assert forbidden not in combined
    assert "读到最后会明白" in combined
    assert "家人在你的安排里" in combined
    assert "家人少一点慌张" in combined


def test_final_tracked_article_guard_cleans_live_38_responsibility_structural_residue() -> None:
    candidate_markdown = (
        "手机刚震了一下，你还没接起来，心里已经开始替家里排顺序。\n\n"
        "责任不断加码、家庭支持不足、生活成本上升、时间被工作和照护双向挤压，个人只是在结构缝隙里一个人先顶着。\n\n"
        "把人往前推着走的，还有那些被你慢慢托稳的日子。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in ("责任不断加码", "家庭支持不足", "结构缝隙", "一个人先顶着"):
        assert forbidden not in repaired
    assert "父母的事要惦记，孩子的事要跟上，工作那头也不能松。" in repaired


def test_responsibility_shelter_result_field_cleanup_removes_live_38_publish_residue() -> None:
    cleaned = workbench._sanitize_responsibility_shelter_result_fields(
        ai_result={
            "abstract": "很多成年人的辛苦，不是为了证明自己，而是为了让家人过得更稳一点。那些没说出口的认真，最后都会慢慢变成家里的底气。",
            "publish_lead": "肩上扛着责任的人，往往最先想到的不是自己。真正让人撑下去的，常常不是成就感，而是家里那份可感的安稳。",
            "intro_options": ["为家人撑起安稳的人，也该被好好心疼。"],
        },
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown="手机、父母、孩子、家里、责任和安稳都在同一篇文章里。",
        reference_source_markdown="电话的那头，是父母、孩子和各种账单。电话这头只能说：没事，有我。",
        text_fields=("abstract", "publish_lead"),
        list_fields=("intro_options",),
    )

    combined = "\n".join([str(cleaned["abstract"]), str(cleaned["publish_lead"]), *[str(item) for item in cleaned["intro_options"]]])
    for forbidden in ("不是为了证明自己，而是", "扛着责任", "撑下去", "撑起安稳"):
        assert forbidden not in combined
    assert "最后都落在让家人过得更稳一点这件事上" in combined
    assert "肩上有责任的人" in combined
    assert "真正让人继续往前走的，常常是家里那份可感的安稳。" in combined
    assert "为家人托起安稳的人" in combined


def test_final_tracked_article_guard_cleans_live_39_responsibility_model_residue() -> None:
    candidate_markdown = (
        "当电话那头同时响起父母、孩子和账单的声音，很多人会发现，真正压在肩上的从来不只是责任，还包括一种不能松手的习惯。先把家里的事理顺，很多成年人就是这样，一步一步，把自己的日子放到后面。\n\n"
        "这不是谁天生更能把事情接住，也不是谁比谁更懂事。更多时候，是因为心里有牵挂。\n\n"
        "成年人最常见的成长，不在于变得多强，而在于变得更稳。\n\n"
        "正因为放不下，所以才会在不容易里继续把日子往前推。很多撑住生活的瞬间，都很普通。\n\n"
        "人到了一定年纪，会慢慢明白，努力不一定总是为了证明什么，更常常是为了让身边的人少一点不安。\n\n"
        "金句一：真正的责任，是把日子一点点照亮。金句二：你今天替家人多想的一步，都会在以后，变成他们少一点慌、你多一点稳。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in (
        "电话那头",
        "很多人会发现",
        "很多成年人就是这样",
        "这不是谁天生更能把事情接住",
        "成年人最常见的成长，不在于",
        "很多撑住生活的瞬间",
        "努力不一定总是为了证明什么",
        "金句一",
        "金句二",
    ):
        assert forbidden not in repaired
    assert "家里一有动静，你还没来得及细想，心里已经开始替家里排顺序。" in repaired
    assert "先把家里的事理顺，很多人就是这样" in repaired
    assert "很多人就是这样" in repaired
    assert "这份多想一步，更多时候是因为心里有牵挂。" in repaired
    assert "人到了一定年纪，常见的成长，是慢慢把日子安排得更稳。" in repaired
    assert "很多认真生活的瞬间" in repaired
    assert "努力常常会落在让身边的人少一点不安这件事上。" in repaired


def test_final_tracked_article_guard_cleans_live_40_responsibility_boundary_and_hard_support_residue() -> None:
    candidate_markdown = (
        "屏幕亮起来那一下，父母、孩子、账单和当天的安排，一起挤到心里。你把声音放稳，说：“我来处理。”很多人以为，这是因为他更能把事情接住。其实是因为他知道，家里不能乱。\n\n"
        "成年人为什么总是先把家里的事理顺？是责任一落在肩上，人就会自然多想一步。\n\n"
        "真正的撑住，是累的时候，依然愿意把家往稳处放。真正的成熟，也是知道自己肩上的重量，仍然不把日子过散。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="成年人说过最多的谎，就是“我没事”。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in ("。成年人", "\n\n成年人", "真正的撑住", "撑住"):
        assert forbidden not in repaired
    assert "人到中年，为什么总是先把家里的事理顺？" in repaired
    assert "真正的稳住，是累的时候" in repaired


def test_responsibility_shelter_result_field_cleanup_removes_live_40_boundary_and_hard_support_residue() -> None:
    cleaned = workbench._sanitize_responsibility_shelter_result_fields(
        ai_result={
            "publish_lead": "成年人为什么总是先把家里的事理顺？真正的撑住，是累的时候也把家往稳处放。",
            "intro_options": ["真正的撑住，是累的时候，依然愿意把家往稳处放。"],
        },
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown="手机、父母、孩子、家里、责任和安稳都在同一篇文章里。",
        reference_source_markdown="成年人说过最多的谎，就是“我没事”。电话这头只能说：没事，有我。",
        text_fields=("publish_lead",),
        list_fields=("intro_options",),
    )

    combined = "\n".join([str(cleaned["publish_lead"]), *[str(item) for item in cleaned["intro_options"]]])
    for forbidden in ("。成年人", "\n\n成年人", "真正的撑住", "撑住"):
        assert forbidden not in combined
    assert "真正的稳住" in combined

def test_final_tracked_article_guard_cleans_live_41_responsibility_report_tone_residue() -> None:
    candidate_markdown = (
        "手机刚震了一下，你还没接起来，心里已经开始替家里排顺序。\n\n"
        "把家庭支出、赡养压力、育儿成本、工作不稳定和情绪耗竭连起来看，说明不是某个人不够努力，而是很多责任被挤到同一个人身上。你先把能协调的时间圈出来，再给家里留出一个更稳的安排。\n\n"
        "责任外包给最能把事情接住的人、情绪不被允许松动、资源永远优先给别人，导致自我被不断后置，不容易变成长期状态。\n\n"
        "把人往前推着走的，还有那些被你慢慢托稳的日子。后来你会看见，父母遇事少一点慌，孩子说话多一点底气，都是你认真托住日子后留下的回响。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in (
        "家庭支出",
        "赡养压力",
        "育儿成本",
        "工作不稳定",
        "情绪耗竭",
        "不是某个人不够努力，而是",
        "责任被挤到同一个人身上",
        "责任外包",
        "情绪不被允许松动",
        "资源永远优先给别人",
        "自我被不断后置",
        "长期状态",
        "后来你会看见",
    ):
        assert forbidden not in repaired
    assert "父母的事要惦记，孩子的事要跟上，工作那头也不能松，很多安排就挤到了一起。" in repaired
    assert "后来再看，父母遇事少一点慌" in repaired

def test_responsibility_shelter_cleanup_removes_live_43_publish_and_body_not_ab_residue() -> None:
    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown="成年人被同时拉扯在亲情、养育、收入和体面之间，很多人不是不想轻松，而是根本没有“停下来”的余地。\n\n用“电话的那头是父母、孩子和现实开销，屏幕这边却只能先把情绪放平”切入，写出责任如何把人从“只顾自己”推成“先顾别人”",
        source_type="tracked_article",
        reference_source_markdown="成年人说过最多的谎，就是“我没事”。责任和家里的安稳，是这篇文章的主线。",
    )
    for forbidden in ("成年人被同时拉扯", "不是不想轻松，而是", "停下来", "电话的那头", "切入", "写出", "只顾自己", "先顾别人"):
        assert forbidden not in repaired
    assert "父母的事要惦记，孩子的事要跟上，工作那头也不能松，很多安排就挤到了一起。" in repaired

    cleaned = workbench._sanitize_responsibility_shelter_result_fields(
        ai_result={
            "abstract": "这篇文章从一个很现实的瞬间切入：手机一响，成年人第一反应不是自己，而是先在心里把家里的事排个顺序。它要讲的不是“吃苦有多光荣”，而是一个人长期接住生活压力时，真正支撑他的，往往是对家人的责任感，以及把日子慢慢托稳的能力。",
            "publish_lead": "手机刚震了一下，你还没来得及接，心里已经先把家里的事排了一遍。很多成年人的辛苦就是这样，不声张，也不轻易说累，只是在一次次应对里，把日子慢慢托稳。",
            "intro_options": [
                "手机一响，先想到的不是自己要不要接，而是家里是不是又临时有事。很多人的责任感，就是从这种下意识的反应里长出来的。",
                "成年人最熟悉的不是轻松，而是随时要接住变化。日历里的安排、家里的电话、眼前的账单，都会让人明白，肩上的重量从来不是空话。",
            ],
        },
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown="手机、父母、孩子、家里、责任和安稳都在同一篇文章里。",
        reference_source_markdown="成年人说过最多的谎，就是“我没事”。电话这头只能说：没事，有我。",
        text_fields=("abstract", "publish_lead"),
        list_fields=("intro_options",),
    )
    combined = "\n".join([str(cleaned["abstract"]), str(cleaned["publish_lead"]), *[str(item) for item in cleaned["intro_options"]]])
    for forbidden in (
        "成年人第一反应不是自己，而是",
        "不是“吃苦有多光荣”，而是",
        "先想到的不是自己要不要接，而是",
        "成年人最熟悉的不是轻松，而是",
    ):
        assert forbidden not in combined
    assert "家里一有动静，很多人会先在心里把家里的事排个顺序。" in combined
    assert "它把目光放在那些长期接住生活压力的人身上" in combined
    assert "家里一有动静，人会先想到是不是又要临时调顺序。" in combined
    assert "日子过到后来，最熟悉的常常是随时接住变化。" in combined


def test_final_tracked_article_guard_repairs_midlife_maturity_merge_regression() -> None:
    repaired = workbench._apply_final_tracked_article_guard(
        title="家里一有事，你总会先把家稳住",
        body_markdown=(
            "电话一响，你先把手里的事停了一下。还没接起来，心里已经明白，今天原本排好的事，多半又要重新挪一遍。爸妈那边谁去跑，孩子这周怎么接，这个月哪笔钱得先留出来。\n\n"
            "人不舒服的时候，也想过请一天假。心里堵得慌的时候，也想过先不管了。可假还没请出口，你先想到的，还是手头的工作、家里的开销，还有后面一串安排。\n\n"
            "很多人的成熟，轮到家里有事时，知道自己不能先慌，夜里也会冒出一句：怎么天天都是这些事。可第二天一早，水壶一响，消息一来，老人等回话，孩子等安排，你还是得起身去接。\n\n"
            "再往后看，父母去医院没以前那么慌了，孩子碰上事也知道先想办法了，伴侣那边也不用什么都一个人扛。这样一想，这几年确实不算白忙。"
        ),
        source_type="tracked_article",
        reference_source_markdown=(
            "中年人的世界，半生风雨，半生奔波。电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，"
            "是每个月如期而至的各种账单。电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。"
            "这些年来，你是不是也是这样：生病了不敢请假，怕影响这个月的绩效；委屈了不敢辞职，因为你要撑起一个家的重量。"
        ),
    )

    assert "很多人的成熟，不在别处，就在这种时候。家里这一头还乱着，你先知道自己不能跟着乱。" in repaired
    assert "夜里躺下以后，脑子也不消停。可第二天一早" in repaired
    assert "很多人的成熟，轮到家里有事时，知道自己不能先慌" not in repaired
    assert "怎么天天都是这些事" not in repaired


def test_resolve_tracked_article_expected_selection_mode_prefers_responsibility_shelter() -> None:
    mode = workbench._resolve_tracked_article_expected_selection_mode(
        {
            "source_type": "tracked_article",
            "topic_title": "家里一有事，你总会先把家稳住",
            "topic_angle": "从电话那头是父母、孩子和账单切入，写中年人为什么总把“我没事”说得很轻。",
            "reference_article_body_markdown": (
                "中年人的世界，半生风雨，半生奔波。电话的那头，是父母日渐佝偻的身影，"
                "是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
            ),
            "strategy_card": {
                "structure_mode": "everyday_warmth_return",
                "positive_direction": "结尾回到一家人的安稳。"
            },
        }
    )

    assert mode == "responsibility_shelter"


def test_resolve_tracked_article_candidate_mode_prefers_responsibility_shelter_over_generic_everyday_warmth() -> None:
    mode = workbench._resolve_tracked_article_candidate_mode(
        title="家里一有事，你总会先把家稳住",
        markdown=(
            "电话一响，你先把手里的事停了一下。还没接起来，心里已经开始替爸妈、孩子和这个月的安排排顺序。\n\n"
            "很多人的成熟，不在别处，就在这种时候。家里这一头还乱着，你先知道自己不能跟着乱。\n\n"
            "后来爸妈少一点着急，孩子多一点底气，回家还有口热饭等着。"
        ),
    )

    assert mode == "responsibility_shelter"


def test_final_tracked_article_guard_repairs_midlife_maturity_merge_after_softening() -> None:
    repaired = workbench._apply_final_tracked_article_guard(
        title="家里一有事，你总会先把家稳住",
        body_markdown=(
            "电话一响，你先把手里的事停了一下。还没接起来，心里已经明白，今天原本排好的事，多半又要重新挪一遍。\n\n"
            "很多人的成熟，轮到家里有事时，知道自己不能先慌，夜里也会觉得累，也会盯着第二天的安排发一会儿呆。可第二天一早，水壶一响，消息一来，老人等回话，孩子等安排，你还是得起身去接。"
        ),
        source_type="tracked_article",
        reference_source_markdown=(
            "中年人的世界，半生风雨，半生奔波。电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。"
        ),
    )

    assert "很多人的成熟，不在别处，就在这种时候。家里这一头还乱着，你先知道自己不能跟着乱。" in repaired
    assert "夜里躺下以后，脑子也不消停。可第二天一早" in repaired
    assert "很多人的成熟，轮到家里有事时，知道自己不能先慌" not in repaired


def test_final_tracked_article_guard_cleans_live_46_embedded_not_ab_residue() -> None:
    candidate_markdown = (
        "屏幕亮起来那一下，父母、孩子、账单和当天的安排，一起挤到心里。你把声音放稳，说：“我来处理。”\n\n"
        "很多人就是这样，先接住家里的事，再去想自己的事。不是不在乎自己，而是心里总有个顺序：先让一家人安稳，自己晚一点再说。\n\n"
        "人到了一定阶段，做决定会变慢。不是犹豫，是开始多想一步。\n\n"
        "下周房贷怎么安排，孩子的报名费什么时候交，父母最近身体有没有不舒服，这些事一件一件落下来，逼着人把日子理顺。责任最重的时候，往往不是你有多厉害，而是你一直记得，背后还有人等着你把生活接稳。\n\n"
        "成年人持续承受压力，意义常常不在“我做成了什么”，而在“我让谁安心了”。你提前把钱算清楚，把时间挤出来，把麻烦挡在门外，很多时候不会立刻被看见。\n\n"
        "真正让人认真往前走的，不是空喊一句“要坚强”，而是心里清楚：今天这份认真，正在变成家里可感的安稳。\n\n"
        "“责任不是把自己耗空，而是把日子稳稳托住。”这句话听着普通，真正做起来并不容易。\n\n"
        "不是每一步都值得被夸大，但每一步都没有白走。\n\n"
        "不是为了证明自己多厉害，只是提醒自己：我正在认真生活，我正在保护我在乎的人，我没有白忙。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in (
        "不是不在乎自己，而是",
        "不是犹豫，是",
        "不是你有多厉害，而是",
        "背后还有人等着你把生活接稳",
        "不在“我做成了什么”，而在",
        "不是空喊一句“要坚强”，而是",
        "不是把自己耗空，而是",
        "不是每一步都值得被夸大",
        "不是为了证明自己多厉害",
    ):
        assert forbidden not in repaired
    assert workbench.extract_not_ab_skeletons(repaired) == []
    assert workbench.evaluate_ai_flavor_risk(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=repaired,
    ).score == 0
    assert "也在乎自己，只是心里总有个顺序" in repaired
    assert "父母、孩子和这个家，都还盼着日子稳一点" in repaired
    assert "责任到最后，是把日子稳稳托住，也把自己慢慢照顾回来" in repaired

def test_final_tracked_article_guard_removes_responsibility_gold_label_and_not_ab_residue() -> None:
    candidate_markdown = (
        "很多成年人会先把家里的事理顺，不是因为自己天生更能把事情接住，而是因为心里有一条很清楚的线：先把该稳住的稳住。"
        "一个人真正开始承担责任，往往不是在说“我要变强”的那个瞬间，而是在默默把日子一项一项排好。\n\n"
        "成年人身上最重的地方，常常不是工作本身，而是心里一直装着想守护的人。\n\n"
        "金句：责任不是把自己活成钢铁，而是明知道不容易，仍愿意把灯留在家里。\n\n"
        "金句：人不是靠硬扛证明价值的，很多时候，是靠把日子稳稳接住，才真正站住了。"
    )

    repaired = workbench._apply_final_tracked_article_guard(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=candidate_markdown,
        source_type="tracked_article",
        reference_source_markdown="电话的那头，是父母、孩子和账单。责任和家里的安稳，是这篇文章的主线。",
    )

    for forbidden in (
        "金句：",
        "不是因为自己天生更能把事情接住",
        "不是在说“我要变强”的那个瞬间",
        "不是工作本身，而是",
        "责任不是把自己活成钢铁，而是",
        "人不是靠硬扛证明价值的",
    ):
        assert forbidden not in repaired
    assert "他们心里有一条很清楚的线：先把该稳住的稳住。" in repaired
    assert "常常发生在默默把日子一项一项排好的时候。" in repaired
    assert "有些责任不必说得轰烈" in repaired
    assert "把日子一件件接稳，也是在认真站住。" in repaired

def test_build_local_tracked_article_responsibility_fallback_rewrites_live_outline_scaffold_points() -> None:
    payload = {
        "topic_title": "肩上有责任的人，心里也要留一盏灯",
        "topic_angle": "从家里临时有事、自己先把顺序理清切入，写责任怎样变成一家人的安稳。",
        "reference_article_body_markdown": (
            "中年人的世界，半生风雨，半生奔波。电话的那头，是父母，是孩子，是账单。"
            "直到父母安心、孩子有底气、伴侣有屋檐，才觉得那些辛苦有了落点。"
        ),
        "outline": {
            "hook": "手机刚震了一下，你还没接起来，心里已经开始替家里排顺序。",
            "outline_body": (
                "### 一、电话这头为什么总是安静下来：责任不是抽象词，而是每天都在被催缴的现实，先点出父母、孩子和现实开销同时来袭的生活场景。\n"
                "### 二、它为什么会这样：用“电话的那头是父母、孩子和现实开销，屏幕这边却只能先把情绪放平”切入，写出责任如何把人从“只顾自己”推成“先顾别人”。\n"
                "### 三、代价落在哪里：睡眠、情绪、关系、判断力与身体都在透支，表面是稳住家里，背后是自己越来越像一盏快没油的灯。\n"
                "### 四、现实怎么顶上来：不是喊口号，而是做边界、排优先级、留应急空间、学会求助，把责任拆小、把自己安放回生活里。"
            ),
        },
        "strategy_card": {
            "structure_mode": "responsibility_shelter",
            "positive_direction": "这些认真不必夸大，但自己没有白忙，眼下的付出正在慢慢变成家人的安稳。",
        },
        "problem_brief": {
            "theme_axis": "成年人持续承受生活压力的意义，往往在为家人换来可感的安稳。",
            "core_conflict": "责任最重的地方，不是一个人有多厉害，而是他心里一直装着想守护的人。",
        },
    }

    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(payload)

    assert title == "肩上有责任的人，心里也要留一盏灯"
    for fragment in (
        "家庭支持变薄",
        "养育成本",
        "照护责任前移",
        "结构性压力",
        "必须扛",
        "睡眠、情绪",
        "判断力",
        "快没油的灯",
        "写透",
        "排优先级",
        "留应急空间",
        "资源不足",
        "时间被挤占",
        "情绪无处安放",
        "高压运转",
        "喘气都要算成本",
        "亲情、养育、收入和体面",
        "不是不想轻松",
        "停下来",
        "没有余地",
        "切入",
        "写出",
        "只顾自己",
        "先顾别人",
        "电话的那头",
        "家不是一个人的独角戏",
        "责任不是让一个人永远站在前面",
    ):
        assert fragment not in body_markdown
    assert "父母的事要惦记，孩子的事要跟上，工作那头也不能松" in body_markdown
    assert "父母少一点担心，孩子多一点底气，家里多一点踏实" in body_markdown
    assert "桌上给你留着一口热饭，屋里有人问你累不累。" in body_markdown
    assert "一个家要走得稳，靠的是彼此都愿意搭一把手。" in body_markdown
    assert "替家里多想的每一步，都会慢慢变成日子的底气。" in body_markdown

def test_rewrite_tracked_article_danger_result_fields_cleans_publish_surfaces() -> None:
    source = (
        "电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。"
        "生病了不敢请假，怕影响这个月的绩效。"
        "直到你看见，渐渐老去的父母，不必在医院的缴费窗口前踌躇。"
    )
    result = workbench._rewrite_tracked_article_danger_result_fields(
        source_markdown=source,
        ai_result={
            "recommended_title": "那句“没事，有我”之后",
            "cover_copy": "没事，有我\n家就稳一点",
            "publish_lead": "很多时候，那句“没事，有我”会先把这个月的事接住。",
            "intro_options": ["生病了怕影响这个月的绩效", "不必在缴费窗口前发慌"],
        },
        text_fields=("recommended_title", "cover_copy", "publish_lead"),
        list_fields=("intro_options",),
    )

    combined = "\n".join(
        [
            str(result["recommended_title"]),
            str(result["cover_copy"]),
            str(result["publish_lead"]),
            *[str(item) for item in result["intro_options"]],
        ]
    )
    for fragment in ("没事，有我", "这个月的绩效", "这个月的", "缴费窗口前", "缴费窗口"):
        assert fragment not in combined
    assert "我来想办法" in combined
    assert "手头的工作考核" in combined
    assert "办事窗口" in combined


def test_build_local_tracked_article_draft_fallback_everyday_warmth_does_not_enter_responsibility_shelter() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "article_title": "人生不求大富大贵，但求简单快乐",
            "topic_title": "那些简单日子，才是真正托住人的幸福",
            "topic_angle": "从幸福坐标慢慢回到家人平安、知己仍在和一顿热饭切入。",
            "reference_article_body_markdown": (
                "人生不求大富大贵，但求简单快乐。家人安康，知己二三，四季平安。"
                "当你深夜晚归时，有一盏灯为你而留；有人做好热腾腾的饭等你回家。父母做的饭，孩子的笑声，知己的一句懂你，都是简单日子里的幸福。"
            ),
            "strategy_card": {
                "structure_mode": "everyday_warmth_return",
                "positive_direction": "结尾回到简单快乐、家人平安、知己仍在和一顿热饭一盏灯这类具体回温动作。",
            },
            "problem_brief": {
                "theme_axis": "主线是人为什么把幸福误认成更大的拥有，后来又被眼前日常慢慢托住。",
                "core_conflict": "财富、排场、圈子和房子未必持续提供踏实感，家人平安和知己仍在反而更有分量。",
            },
        }
    )

    assert title == "那些简单日子，才是真正托住人的幸福"
    assert "没事，有我" not in body_markdown
    assert "很多中年人的那句" not in body_markdown
    assert "账单" not in body_markdown
    assert "肩上有责任" not in body_markdown
    assert "学校门口" not in body_markdown
    assert "人生不求大富大贵" not in body_markdown
    assert "那些看起来" not in body_markdown
    paragraphs = [part for part in body_markdown.split("\n\n") if part.strip()]
    assert len(paragraphs) >= 9
    assert len(body_markdown) >= 450
    assert body_markdown.startswith(
        (
            "人走过一些事以后，才会承认，最想守住的不是排场，是那些简单却没丢的日子。",
            "有些晚上，推开家门闻到饭香，人才忽然不想再和谁比较了。",
        )
    )
    assert "回来啦？先洗手。" not in body_markdown
    assert "所谓简单快乐，是见过起落以后，依然知道什么东西值得你一直放在心上" in body_markdown
    assert "知己不必很多，三两个就够" in body_markdown
    assert "家人平安，知己仍在，心里没有那么多挂心事，就是一种实打实的福气" in body_markdown
    assert not re.search(r"不是[^。！？!?\n]{1,40}(?:而是|也不是)", body_markdown)
    assert "所以人活到后来，求的未必是大富大贵" in body_markdown
    for stale_phrase in ("幸福到最后", "人这一生", "愿你往后", "越普通的暖", "好日子", "时候，幸福", "幸福其实", "苏轼写过一句"):
        assert stale_phrase not in body_markdown


def test_initial_cleanup_keeps_everyday_warmth_return_in_short_paragraphs() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "article_title": "人生不求大富大贵，但求简单快乐",
            "topic_title": "日子过到后来，有家人有知己就很踏实",
            "topic_angle": "人会一路追着更多拥有往前走，直到某个普通晚上被一顿热饭、一通惦记和一句到哪了轻轻接住，才重新看见家人平安、知己仍在的分量。",
            "reference_article_body_markdown": (
                "人生不求大富大贵，但求简单快乐。家人安康，知己二三，四季平安。"
                "有人做好热腾腾的饭等你回家，有一盏灯为你而留。"
            ),
            "strategy_card": {"structure_mode": "everyday_warmth_return"},
            "problem_brief": {
                "theme_axis": "主线是人为什么把幸福误认成更大的拥有，后来又被眼前日常慢慢托住。",
                "core_conflict": "财富、排场、圈子和房子未必持续提供踏实感，家人平安和知己仍在反而更有分量。",
            },
        }
    )

    result = workbench._build_initial_draft_candidate_result(
        title=title,
        body_markdown=body_markdown,
        source_type="tracked_article",
        reference_source_markdown="人生不求大富大贵，但求简单快乐。家人安康，知己二三，四季平安。",
    )
    paragraphs = [part.strip() for part in result.body_markdown.split("\n\n") if part.strip()]

    assert max(len(part) for part in paragraphs) <= 80
    assert any(part.startswith("知己不必很多，三两个就够。") for part in paragraphs)
    assert any(part.startswith("所以人活到后来，求的未必是大富大贵") for part in paragraphs)
    assert "有人等你接回来" not in result.body_markdown

def test_initial_cleanup_keeps_response_priority_followup_variant_in_short_paragraphs() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "真正在意你的人，会读懂你的言外之意",
            "topic_angle": "从点赞、评论和一句我没事背后的分量差别切入，写为什么轻互动很多，人却还是会悬着；也写真正的关心，往往藏在一句追问、一次补问和被认真听懂的那一下。",
            "body_markdown": (
                "而评论，却需要停下来，读懂你的言外之意。"
                "真正关心你的人，愿意努力去读懂你的每一份脆弱。"
                "哪怕相隔千里，也能透过你的一句我没事，听出你心底的我有点累。"
            ),
            "strategy_card": {"structure_mode": "response_priority"},
            "problem_brief": {
                "theme_axis": "主线是轻互动为什么不等于真正的关心；真正让人踏实的，常常是有人愿意停下来读懂你、把你那句没说完的话接下去。",
                "core_conflict": "很多时候真正让人踏实的，不是互动不断，而是有人能从你轻描淡写的话里听出分量，并愿意把那句话接下去。",
            },
        }
    )

    result = workbench._build_initial_draft_candidate_result(
        title=title,
        body_markdown=body_markdown,
        source_type="tracked_article",
        reference_source_markdown="而评论，却需要停下来，读懂你的言外之意。真正关心你的人，愿意努力去读懂你的每一份脆弱。",
    )
    paragraphs = [part.strip() for part in result.body_markdown.split("\n\n") if part.strip()]

    assert max(len(part) for part in paragraphs) <= 150
    assert any("真正的在意" in part for part in paragraphs)
    assert any("被这样接住过一次" in part for part in paragraphs)
    assert "等电梯的半分钟，够不够回一句话？其实够的。" not in result.body_markdown



def test_response_priority_followup_variant_keeps_specific_comment_scene() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "你轻轻带过的话，真正在意的人会再问一句",
            "topic_angle": "从点赞、评论和一句我没事背后的分量差别切入，写为什么轻互动很多，人却还是会悬着；也写真正的关心，往往藏在一句追问、一次补问和被认真听懂的那一下。",
            "body_markdown": (
                "我有个好友，曾经在朋友圈发了一张落日余晖的照片，配文是：今天的夕阳真美，终于下班了。"
                "底下一排整齐的点赞，只有一个人问她：是不是项目又出岔子了？"
                "后来她告诉我，那天她不仅工作受了委屈，还挨了领导痛批。"
            ),
            "strategy_card": {"structure_mode": "response_priority"},
            "problem_brief": {
                "theme_axis": "主线是轻互动为什么不等于真正的关心；真正让人踏实的，常常是有人愿意停下来读懂你、把你那句没说完的话接下去。",
                "core_conflict": "很多时候真正让人踏实的，不是互动不断，而是有人能从你轻描淡写的话里听出分量，并愿意把那句话接下去。",
            },
        }
    )

    result = workbench._build_initial_draft_candidate_result(
        title=title,
        body_markdown=body_markdown,
        source_type="tracked_article",
        reference_source_markdown=(
            "我有个好友，曾经在朋友圈发了一张落日余晖的照片，配文是：今天的夕阳真美，终于下班了。"
            "底下一排整齐的点赞，只有一个人问她：是不是项目又出岔子了？"
            "真正关心你的人，是哪怕相隔千里，也能透过你的一句“我没事”，听出你心底的“我有点累”。"
        ),
    )
    paragraphs = [part.strip() for part in result.body_markdown.split("\n\n") if part.strip()]

    assert any("今天的夕阳真美，终于下班了" in part for part in paragraphs)
    assert any("是不是项目又出岔子了" in part for part in paragraphs)
    assert any("很多人也会陪你热闹，会点赞，会寒暄" in part for part in paragraphs)
    assert any("谁只是路过，谁是真的把你放在心上" in part for part in paragraphs)
def test_build_local_tracked_article_outline_fallback_everyday_warmth_avoids_strategy_hook_leak() -> None:
    outline = workbench._build_local_tracked_article_outline_fallback(
        {
            "source_type": "tracked_article",
            "topic_title": "日子过到后来，有家人有知己就很踏实",
            "topic_angle": "从人为什么总把好日子押在更大的拥有上切入，写我们一路追着排场、热闹和体面往前赶。",
            "reference_article_body_markdown": (
                "人生不求大富大贵，但求简单快乐。家人安康，知己二三，四季平安。"
                "有人做好热腾腾的饭等你回家，有一盏灯为你而留。"
            ),
            "strategy_card": {
                "structure_mode": "everyday_warmth_return",
                "hook_trigger": "更大的目标突然失重，饭桌、回家或有人惦记这些小日常重新有了分量的那一下。",
            },
            "problem_brief": {
                "theme_axis": "主线是人为什么把幸福误认成更大的拥有，后来又被眼前日常慢慢托住。",
                "core_conflict": "财富、排场、圈子和房子未必持续提供踏实感，家人平安和知己仍在反而更有分量。",
            },
        }
    )

    assert outline["hook"] == "后来你会发现，真正让人踏实的，常常不是赢了多少，而是家里那盏灯还亮着，老朋友还在。"
    assert "更大的目标突然失重" not in outline["hook"]
    assert "从人为什么" not in outline["outline_body"]
    assert "写我们一路" not in outline["outline_body"]



def test_generate_assets_keeps_api_result_when_packaging_retry_stays_generic(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "assets-retry-still-generic-source",
            "source_name": "夜读关系实验室",
            "title": "夜里那句我没事，背后都是责任",
            "url": "https://example.com/assets-retry-still-generic-source",
            "author": "北岛",
            "summary": "从成年人把疲惫先咽回去写起，再把辛苦回收到家里的安稳和被护住的秩序里。",
            "structure_notes": "现实接口起手 + 责任代价推进 + 回到家里安稳。",
            "tags": ["中年责任", "家庭安稳"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n他说没事的时候，手心其实已经凉了。",
        },
    )
    client.post(
        "/api/tracked-articles/assets-retry-still-generic-source/to-topic",
        json={
            "slug": "assets-retry-still-generic-topic",
            "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样把辛苦压回去。",
        },
    )
    project_response = client.post(
        "/api/topics/assets-retry-still-generic-topic/create-project",
        json={
            "slug": "assets-retry-still-generic-project",
            "title": "assets retry still generic 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/assets-retry-still-generic-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/assets-retry-still-generic-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.asset_calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "他说没事的时候，手心其实已经凉了。",
                "outline_body": "1. 为什么先把自己往后放\n2. 责任怎样把辛苦压回去\n3. 家里的安稳怎么把意义接回来",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "肩上有责任的人，心里也要留一盏灯",
                "body_markdown": (
                    "很多时候，说这句话的人并不轻松。\n\n"
                    "可他还是得先把家里的气稳住，再把自己的慌乱往后放。"
                ),
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.asset_calls.append(dict(payload))
            return {
                "title_options": ["很多人的那句我没事，藏着没说出口的累"],
                "recommended_title": "很多人的那句我没事，藏着没说出口的累",
                "cover_prompt": "16:9 横版公众号头图，夜里灯还亮着",
                "cover_copy": "很多人都在悄悄把生活接住。",
                "social_teaser": "很多时候，那句我没事背后，是成年人说不出口的累。",
                "social_teaser_options": ["很多人都在悄悄把生活接住。"],
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_creative_quality_retry_max_attempts", lambda: 1)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    assert client.post("/api/projects/assets-retry-still-generic-project/generate-outline").status_code == 201
    assert client.post("/api/projects/assets-retry-still-generic-project/generate-draft").status_code == 201

    assets = workbench.generate_assets("assets-retry-still-generic-project")

    assert len(fake_generator.asset_calls) == 2
    assert assets.recommended_title != "肩上有责任的人，心里也要留一盏灯"
    assert "那句我没事" in assets.recommended_title
    assert "藏着没说出口的累" in assets.recommended_title
    assert assets.title_options == [assets.recommended_title]
    assert "说不出口的累" in assets.social_teaser
    assert "悄悄把生活接住" in assets.cover_copy


def test_generate_assets_skips_packaging_quality_retry_by_default(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "assets-default-no-quality-retry-source",
            "source_name": "夜读关系实验室",
            "title": "夜里那句我没事，背后都是责任",
            "url": "https://example.com/assets-default-no-quality-retry-source",
            "author": "北岛",
            "summary": "从成年人把疲惫先咽回去写起，再把辛苦回收到家里的安稳和被护住的秩序里。",
            "structure_notes": "现实接口起手 + 责任代价推进 + 回到家里安稳。",
            "tags": ["中年责任", "家庭安稳"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n他说没事的时候，手心其实已经凉了。",
        },
    )
    client.post(
        "/api/tracked-articles/assets-default-no-quality-retry-source/to-topic",
        json={
            "slug": "assets-default-no-quality-retry-topic",
            "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样把辛苦压回去。",
        },
    )
    project_response = client.post(
        "/api/topics/assets-default-no-quality-retry-topic/create-project",
        json={
            "slug": "assets-default-no-quality-retry-project",
            "title": "assets default no quality retry 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/assets-default-no-quality-retry-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/assets-default-no-quality-retry-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.asset_calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "他说没事的时候，手心其实已经凉了。",
                "outline_body": "1. 为什么先把自己往后放\n2. 责任怎样把辛苦压回去\n3. 家里的安稳怎么把意义接回来",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "肩上有责任的人，心里也要留一盏灯",
                "body_markdown": "很多时候，说这句话的人并不轻松。\n\n可他还是得先把家里的气稳住，再把自己的慌乱往后放。",
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.asset_calls.append(dict(payload))
            return {
                "title_options": ["很多人的那句我没事，藏着没说出口的累"],
                "recommended_title": "很多人的那句我没事，藏着没说出口的累",
                "cover_prompt": "16:9 横版公众号头图，夜里灯还亮着",
                "cover_copy": "很多人都在悄悄把生活接住。",
                "social_teaser": "很多时候，那句我没事背后，是成年人说不出口的累。",
                "social_teaser_options": ["很多人都在悄悄把生活接住。"],
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_creative_quality_retry_max_attempts", lambda: 0)
    monkeypatch.setattr(workbench, "_should_retry_assets_for_packaging", lambda **_: True)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    assert client.post("/api/projects/assets-default-no-quality-retry-project/generate-outline").status_code == 201
    assert client.post("/api/projects/assets-default-no-quality-retry-project/generate-draft").status_code == 201

    assets = workbench.generate_assets("assets-default-no-quality-retry-project")

    assert len(fake_generator.asset_calls) == 1
    assert "那句我没事" in assets.recommended_title


def test_build_publish_package_keeps_api_result_when_packaging_retry_stays_generic(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "publish-retry-still-generic-source",
            "source_name": "夜读关系实验室",
            "title": "夜里那句我没事，背后都是责任",
            "url": "https://example.com/publish-retry-still-generic-source",
            "author": "北岛",
            "summary": "从成年人把疲惫先咽回去写起，再把辛苦回收到家里的安稳和被护住的秩序里。",
            "structure_notes": "现实接口起手 + 责任代价推进 + 回到家里安稳。",
            "tags": ["中年责任", "家庭安稳"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n他说没事的时候，手心其实已经凉了。",
        },
    )
    client.post(
        "/api/tracked-articles/publish-retry-still-generic-source/to-topic",
        json={
            "slug": "publish-retry-still-generic-topic",
            "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样把辛苦压回去。",
        },
    )
    project_response = client.post(
        "/api/topics/publish-retry-still-generic-topic/create-project",
        json={
            "slug": "publish-retry-still-generic-project",
            "title": "publish retry still generic 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/publish-retry-still-generic-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/publish-retry-still-generic-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.publish_calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "他说没事的时候，手心其实已经凉了。",
                "outline_body": "1. 为什么先把自己往后放\n2. 责任怎样把辛苦压回去\n3. 家里的安稳怎么把意义接回来",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "肩上有责任的人，心里也要留一盏灯",
                "body_markdown": (
                    "很多时候，说这句话的人并不轻松。\n\n"
                    "可他还是得先把家里的气稳住，再把自己的慌乱往后放。"
                ),
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["肩上有责任的人，心里也要留一盏灯"],
                "recommended_title": "肩上有责任的人，心里也要留一盏灯",
                "cover_prompt": "16:9 横版公众号头图，夜里灯还亮着",
                "cover_copy": "肩上有责任，心里也要留一盏灯。",
                "social_teaser": "把家里放在心上的人，也要记得给自己留一点光。",
                "social_teaser_options": ["把家里放在心上的人，也要记得给自己留一点光。"],
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.publish_calls.append(dict(payload))
            return {
                "abstract": "很多人都在悄悄把生活接住。",
                "publish_title": "很多人的那句我没事，藏着没说出口的累",
                "publish_lead": "很多人会在一句我没事里，把所有累都放到后面。",
                "intro_options": ["很多人会在一句我没事里，把所有累都放到后面。"],
                "tags": ["中年责任", "家庭安稳"],
                "editor_note": "泛概括包装。",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_creative_quality_retry_max_attempts", lambda: 1)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    assert client.post("/api/projects/publish-retry-still-generic-project/generate-outline").status_code == 201
    assert client.post("/api/projects/publish-retry-still-generic-project/generate-draft").status_code == 201
    assert client.post("/api/projects/publish-retry-still-generic-project/generate-assets").status_code == 201

    publish_response = client.post("/api/projects/publish-retry-still-generic-project/build-publish-package")
    assert publish_response.status_code == 201
    package = publish_response.json()

    assert len(fake_generator.publish_calls) == 2
    assert fake_generator.publish_calls[0].get("publish_timeout_recovery_mode") is None
    assert fake_generator.publish_calls[0]["problem_brief"]["version"] == 1
    assert fake_generator.publish_calls[0]["strategy_card"]["version"] == 1
    assert fake_generator.publish_calls[0]["benchmarks"]
    assert fake_generator.publish_calls[1].get("publish_timeout_recovery_mode") is None
    assert package["publish_title"] != "肩上有责任的人，心里也要留一盏灯"
    assert "那句我没事" in package["publish_title"]
    assert "藏着没说出口的累" in package["publish_title"]
    assert package["publish_lead"]
    assert package["intro_options"] == [package["publish_lead"]]


def test_build_publish_package_skips_packaging_quality_retry_by_default(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "publish-default-no-quality-retry-source",
            "source_name": "夜读关系实验室",
            "title": "夜里那句我没事，背后都是责任",
            "url": "https://example.com/publish-default-no-quality-retry-source",
            "author": "北岛",
            "summary": "从成年人把疲惫先咽回去写起，再把辛苦回收到家里的安稳和被护住的秩序里。",
            "structure_notes": "现实接口起手 + 责任代价推进 + 回到家里安稳。",
            "tags": ["中年责任", "家庭安稳"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n他说没事的时候，手心其实已经凉了。",
        },
    )
    client.post(
        "/api/tracked-articles/publish-default-no-quality-retry-source/to-topic",
        json={
            "slug": "publish-default-no-quality-retry-topic",
            "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样把辛苦压回去。",
        },
    )
    project_response = client.post(
        "/api/topics/publish-default-no-quality-retry-topic/create-project",
        json={
            "slug": "publish-default-no-quality-retry-project",
            "title": "publish default no quality retry 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/publish-default-no-quality-retry-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/publish-default-no-quality-retry-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.publish_calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "他说没事的时候，手心其实已经凉了。",
                "outline_body": "1. 为什么先把自己往后放\n2. 责任怎样把辛苦压回去\n3. 家里的安稳怎么把意义接回来",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "肩上有责任的人，心里也要留一盏灯",
                "body_markdown": "很多时候，说这句话的人并不轻松。\n\n可他还是得先把家里的气稳住，再把自己的慌乱往后放。",
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["肩上有责任的人，心里也要留一盏灯"],
                "recommended_title": "肩上有责任的人，心里也要留一盏灯",
                "cover_prompt": "16:9 横版公众号头图，夜里灯还亮着",
                "cover_copy": "肩上有责任，心里也要留一盏灯。",
                "social_teaser": "把家里放在心上的人，也要记得给自己留一点光。",
                "social_teaser_options": ["把家里放在心上的人，也要记得给自己留一点光。"],
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.publish_calls.append(dict(payload))
            return {
                "abstract": "很多人都在悄悄把生活接住。",
                "publish_title": "很多人的那句我没事，藏着没说出口的累",
                "publish_lead": "很多人会在一句我没事里，把所有累都放到后面。",
                "intro_options": ["很多人会在一句我没事里，把所有累都放到后面。"],
                "tags": ["中年责任", "家庭安稳"],
                "editor_note": "泛概括包装。",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_creative_quality_retry_max_attempts", lambda: 0)
    monkeypatch.setattr(workbench, "_should_retry_publish_package_for_packaging", lambda **_: True)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    assert client.post("/api/projects/publish-default-no-quality-retry-project/generate-outline").status_code == 201
    assert client.post("/api/projects/publish-default-no-quality-retry-project/generate-draft").status_code == 201
    assert client.post("/api/projects/publish-default-no-quality-retry-project/generate-assets").status_code == 201

    publish_response = client.post("/api/projects/publish-default-no-quality-retry-project/build-publish-package")

    assert publish_response.status_code == 201
    assert len(fake_generator.publish_calls) == 1
    assert "那句我没事" in publish_response.json()["publish_title"]


def test_build_publish_package_retries_compact_prompt_after_custom_tracked_article_transport_error(monkeypatch) -> None:
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "publish-retry-after-error-source",
            "source_name": "夜读关系实验室",
            "title": "夜里那句我没事，背后都是责任",
            "url": "https://example.com/publish-retry-after-error-source",
            "author": "北岛",
            "summary": "从成年人把疲惫先咽回去写起，再把辛苦回收到家里的安稳和被护住的秩序里。",
            "structure_notes": "现实接口起手 + 责任代价推进 + 回到家里安稳。",
            "tags": ["中年责任", "家庭安稳"],
            "body_source": "manual",
            "body_markdown": "# 原文\n\n他说没事的时候，手心其实已经凉了。",
        },
    )
    client.post(
        "/api/tracked-articles/publish-retry-after-error-source/to-topic",
        json={
            "slug": "publish-retry-after-error-topic",
            "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "angle": "从成年人为什么总把“我没事”说得很轻切入，写责任怎样把辛苦压回去。",
        },
    )
    project_response = client.post(
        "/api/topics/publish-retry-after-error-topic/create-project",
        json={
            "slug": "publish-retry-after-error-project",
            "title": "publish retry after error 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201
    assert client.post("/api/projects/publish-retry-after-error-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/publish-retry-after-error-project/adopt-strategy-card/1").status_code == 200

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.publish_calls: list[dict[str, object]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "他说没事的时候，手心其实已经凉了。",
                "outline_body": "1. 为什么先把自己往后放\n2. 责任怎样把辛苦压回去\n3. 家里的安稳怎么把意义接回来",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
                "body_markdown": (
                    "很多时候，说这句话的人并不轻松。\n\n"
                    "可他还是得先把家里的气稳住，再把自己的慌乱往后放。"
                ),
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["那句轻轻的没事，先把一家人的慌稳住了"],
                "recommended_title": "那句轻轻的没事，先把一家人的慌稳住了",
                "cover_prompt": "16:9 横版公众号头图，夜里灯还亮着",
                "cover_copy": "有人把慌稳住，家里才有了亮处。",
                "social_teaser": "那句轻轻说出口的没事，很多时候先稳住的是一家人的慌。",
                "social_teaser_options": ["导语一", "导语二", "导语三"],
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.publish_calls.append(dict(payload))
            if len(self.publish_calls) == 1:
                raise openai.APIConnectionError(
                    request=httpx.Request("POST", "https://proxy.example/v1/chat/completions")
                )
            return {
                "abstract": "写那句轻轻的没事背后，成年人怎样先稳住一家人的慌。",
                "publish_title": "那句轻轻的没事，先把一家人的慌稳住了",
                "publish_lead": "有些话说得越轻，背后越是一个人先把慌乱压住。",
                "intro_options": ["有些话说得越轻，背后越是一个人先把慌乱压住。"],
                "tags": ["中年责任", "家庭安稳"],
                "editor_note": "主题守在责任怎样落成家里的安稳。",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    assert client.post("/api/projects/publish-retry-after-error-project/generate-outline").status_code == 201
    assert client.post("/api/projects/publish-retry-after-error-project/generate-draft").status_code == 201
    assert client.post("/api/projects/publish-retry-after-error-project/generate-assets").status_code == 201
    publish_response = client.post("/api/projects/publish-retry-after-error-project/build-publish-package")

    assert publish_response.status_code == 201
    package = publish_response.json()
    assert len(fake_generator.publish_calls) >= 2
    assert fake_generator.publish_calls[0].get("publish_timeout_recovery_mode") is None
    assert fake_generator.publish_calls[0]["problem_brief"]["version"] == 1
    assert fake_generator.publish_calls[0]["strategy_card"]["version"] == 1
    assert fake_generator.publish_calls[0]["benchmarks"]
    assert fake_generator.publish_calls[1]["publish_timeout_recovery_mode"] is True
    assert package["publish_title"] == "那句轻轻的没事，先把一家人的慌稳住了"
def test_build_local_assets_fallback_everyday_warmth_uses_human_cover_and_lead() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="日子过到后来，有家人有知己就很踏实",
        topic_title="日子过到后来，有家人有知己就很踏实",
        topic_angle="从人为什么总把好日子押在更大的拥有上切入，写我们一路追着排场、热闹和体面往前赶。",
        draft_title="日子过到后来，有家人有知己就很踏实",
        draft_body_markdown=(
            "有些晚上，推开家门闻到饭香，人才忽然不想再和谁比较了。\n\n"
            "我很喜欢一句话：能把平凡日子过热乎，本身就是一种本事。\n\n"
            "有人记得你爱吃什么，有人问你几点回，有个朋友不催你、也愿意认真听你说两句，这些都不是小事。\n\n"
            "一顿热饭、一盏灯、三两知己和家人平安，放在一起，就是很多人走到后来最想守住的幸福。"
        ),
    )

    assert assets["recommended_title"] == "日子过到后来，有家人有知己就很踏实"
    assert assets["cover_copy"] == "家里人平安，知己还在，平淡日子也很值得。"
    assert (
        assets["social_teaser"]
        == "有些晚上，推开家门闻到饭香，人才忽然不想再和谁比较了。有人惦记，话有人听，平淡日子也能把人稳稳托住。"
    )
    assert "从人为什么" not in assets["cover_copy"]
    assert "从人为什么" not in assets["social_teaser"]


def test_build_initial_draft_candidate_result_keeps_local_responsibility_fallback_human_lines() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "topic_angle": "责任把人往前推，也让辛苦慢慢显出意义",
            "reference_article_body_markdown": "中年人的世界，半生风雨，半生奔波。电话的那头，是父母，是孩子，是账单。生病了不敢请假，怕影响这个月的绩效。",
            "outline": {
                "hook": "一句“没事，有我”背后那点喉咙发紧。",
                "outline_body": (
                    "1. 开头先落一句“没事，有我”背后的发紧\n"
                    "2. 责任怎样把人推着往前：上有父母、下有孩子、工作也不敢松，很多人慢慢学会先稳住别人，再往后放自己。\n"
                    "3. 责任怎样回到日常：父母少一点担心，孩子多一点底气，家里的灯还亮着，让辛苦落成看得见的踏实。\n"
                    "4. 结尾回到家里仍被护住的安稳、有人还在等你和这些辛苦没有白熬。"
                ),
            },
            "strategy_card": {
                "positive_direction": "结尾回到家里仍被护住的安稳、有人还在等你和这些辛苦没有白熬，不要收成苦难赞歌或空泛打气。"
            },
            "problem_brief": {
                "theme_axis": "主线是很多成年人为什么会把“我没事”顶在前面。",
                "core_conflict": "明明很疲惫了，还是要把那句“有我”稳稳顶在前面。",
            },
        }
    )

    result = workbench._build_initial_draft_candidate_result(
        title=title,
        body_markdown=body_markdown,
        source_type="tracked_article",
    )

    assert "你你" not in result.body_markdown
    assert "真要把它算成" not in result.body_markdown
    assert "你只。" not in result.body_markdown
    assert any(
        fragment in result.body_markdown
        for fragment in (
            "这几样一下都排到前面了",
            "先把这几样过了一遍",
            "先看哪张单子得今天处理",
            "先把这个月的工作、父母和孩子的事排了一遍",
        )
    )
    assert any(
        fragment in result.body_markdown
        for fragment in (
            "所以电话那头一着急，你还是先回一句“我先来想办法”",
            "你不是天生会扛事，只是轮到你时，习惯先说一句“我来想办法”。",
        )
    )
    assert any(
        fragment in result.body_markdown
        for fragment in (
            "爸妈再遇事时，电话那头没以前那么慌了",
            "孩子碰上事情，也知道先稳一下再想办法了。",
        )
    )


def test_build_local_responsibility_shelter_fallback_skips_outline_instruction_leakage() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "肩上有责任的人，心里也要留一盏灯",
            "topic_angle": "从家里临时有事、自己先把顺序理清切入，重点写责任为什么会让人多想一步，也写这些认真托住日子的时刻怎样变成一家人的安稳、底气和被照亮的日常。",
            "reference_article_body_markdown": "中年人的世界，半生风雨，半生奔波。电话的那头，是父母、孩子和账单。",
            "outline": {
                "hook": "手机刚震了一下，你还没接起来，心里已经开始替家里排顺序。",
                "outline_body": (
                    "### 1. 开头：把“接电话”写成一种生活状态\n"
                    "从一通电话切入，写清楚来电背后不是寒暄，而是催款、问候、托付和等待；点出“肩上有责任的人”为什么连沉默都要计算分寸。\n"
                    "### 2. 中段一：这份压力为什么会变成常态\n"
                    "拆开责任的来源：家庭供养、育儿成本、职业不确定性和体面焦虑如何叠加，让人长期处在“不能倒”的位置上；写明它不是脆弱，而是结构性的消耗。\n"
                    "### 3. 中段二：代价落在哪里\n"
                    "写情绪被压缩、睡眠被打散、消费被切薄、关系被延后，进一步写到自我感受被挤到边角；不渲染悲情，只呈现那些每天都在发生的小损耗。\n"
                    "### 4. 结尾：把人带回一种踏实的自我确认\n"
                    "收束到“我不是只会硬撑的人”，强调真正的支撑不是突然变轻松，而是在责任之内保留判断、节奏和一点点自己的光；落点是承认疲惫，也承认自己一直在认真生活。"
                ),
            },
            "strategy_card": {
                "positive_direction": "你替一家人多想一步，也要记得给自己留一盏灯。"
            },
        }
    )

    assert title == "肩上有责任的人，心里也要留一盏灯"
    for forbidden in (
        "写清楚来电背后",
        "点出“肩上有责任的人”",
        "这份压力为什么会变成常态",
        "家庭供养",
        "育儿成本",
        "职业不确定性",
        "体面焦虑",
        "结构性的消耗",
        "写情绪被压缩",
    ):
        assert forbidden not in body_markdown
    assert "父母的事要惦记，孩子的事要跟上，工作那头也不能松" in body_markdown
    assert "父母少一点担心，孩子多一点底气，家里多一点踏实，这些都在告诉你，自己没有白忙" in body_markdown
    assert any(
        fragment in body_markdown
        for fragment in (
            "时间久了，你就习惯先把家里那头安顿好",
            "事情一多，你会把能办的先办，把能问的先问。",
        )
    )
    assert "靠的是彼此都愿意搭一把手" in body_markdown
    assert "你并是" not in body_markdown
    assert "一直认真" not in body_markdown
    assert any(
        fragment in body_markdown
        for fragment in (
            "那口热饭、那句“先吃饭，别急”",
            "推门回家，桌上给你留着一口热饭",
        )
    )
    assert workbench.evaluate_ai_flavor_risk(
        title=title,
        body_markdown=body_markdown,
    ).score == 0


def test_build_local_responsibility_shelter_fallback_keeps_richer_human_positive_flow() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "肩上有责任的人，心里也要留一盏灯",
            "topic_angle": "从家里临时有事、自己先把顺序理清切入，写责任为什么会让人多想一步，也写这些认真托住日子的时刻怎样变成一家人的安稳、底气和被照亮的日常。",
            "reference_article_body_markdown": (
                "中年人的世界，半生风雨，半生奔波。电话的那头，是父母、孩子和账单。"
                "生病了不敢请假，怕影响这个月的绩效。"
            ),
            "outline": {
                "hook": "手机刚震了一下，你还没接起来，心里已经开始替家里排顺序。",
                "outline_body": (
                    "### 1. 写清楚来电背后\n"
                    "### 2. 家庭供养、育儿成本、职业不确定性\n"
                    "### 3. 父母少一点担心，孩子多一点底气，家里多一点踏实。"
                ),
            },
            "strategy_card": {
                "positive_direction": "你替一家人多想一步，也要记得给自己留一盏灯。"
            },
        }
    )

    paragraphs = [paragraph for paragraph in body_markdown.split("\n\n") if paragraph.strip()]
    assert title == "肩上有责任的人，心里也要留一盏灯"
    assert len(body_markdown) >= 780
    assert len(paragraphs) >= 10
    for anchor in ("一盒药", "校服", "冰箱", "先吃饭，别急"):
        assert anchor in body_markdown
    assert any(
        fragment in body_markdown
        for fragment in (
            "把日子往前托的人，也该有人来接一接",
            "把日子往前托的人，也该被日子温柔托住",
        )
    )
    for forbidden in (
        "耗空",
        "身体先报警",
        "情绪硬吞",
        "写清楚",
        "点出",
        "结构性消耗",
        "不是一句漂亮话",
        "硬撑",
        "撑住",
    ):
        assert forbidden not in body_markdown
    assert not any(paragraph.startswith(("很多人", "有些人", "总有人")) for paragraph in paragraphs)
    assert workbench.extract_not_ab_skeletons(body_markdown) == []
    assert workbench.evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown).score == 0

def test_local_responsibility_assets_and_publish_package_keep_human_positive_theme() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "万般辛苦，皆为序章，人间安稳，终会如愿",
            "topic_angle": "从中年人扛起父母、孩子、伴侣和账单的现实切入，写那些不张扬的辛苦如何慢慢换成一家人的安稳，也提醒肩上有责任的人别忘了照顾自己。",
            "reference_article_body_markdown": "中年人的世界，半生风雨，半生奔波。电话的那头，是父母日渐佝偻的身影，是孩子越来越高的补习费用，是每个月如期而至的各种账单。",
            "outline": {
                "hook": "家里一有动静，你还没来得及细想，心里已经开始替家里排顺序。",
                "outline_body": "父母的事要惦记，孩子的事要跟上，工作那头也不能松。\n父母少一点担心，孩子多一点底气，家里多一点踏实。",
            },
            "strategy_card": {"positive_direction": "你替一家人多想一步，也要记得给自己留一盏灯。"},
        }
    )
    body_markdown = workbench._apply_final_tracked_article_guard(
        title=title,
        body_markdown=body_markdown,
        source_type="tracked_article",
        reference_source_markdown="中年人的世界，半生风雨，半生奔波。电话的那头，是父母、孩子和账单。",
    )

    assets = workbench._build_local_assets_fallback(
        project_title=title,
        topic_title="万般辛苦，皆为序章，人间安稳，终会如愿",
        topic_angle="从中年人扛起父母、孩子、伴侣和账单的现实切入。",
        draft_title=title,
        draft_body_markdown=body_markdown,
    )
    asset_item = workbench.AssetItem(
        project_slug="local-responsibility",
        draft_version=1,
        version=1,
        cover_image_path="",
        cover_image_url="",
        **assets,
    )
    package = workbench._build_local_publish_package_fallback(
        draft_title=title,
        draft_body_markdown=body_markdown,
        assets=asset_item,
    )

    assert "16:9 横版" in str(assets["cover_prompt"])
    assert "不要手机聊天界面" in str(assets["cover_prompt"])
    assert "不要消息气泡" in str(assets["cover_prompt"])
    normalized_cover_prompt = workbench._normalize_cover_prompt_layout(str(assets["cover_prompt"]))
    assert "不要人物看手机" not in normalized_cover_prompt
    assert "普通单屏手机" not in normalized_cover_prompt
    assert "前后双屏" not in normalized_cover_prompt
    assert "不出现聊天界面、输入框、消息气泡或可读屏幕文字" in normalized_cover_prompt
    assert "真实摄影感" in normalized_cover_prompt
    assert "不要扁平插画感" in normalized_cover_prompt
    assert "不要在画面里生成中文文字" in normalized_cover_prompt
    assert "很多认真多想的一步" not in "\n".join(str(item) for item in assets["social_teaser_options"])
    assert "一个家能慢慢稳下来，总得有人先把那口气接住。" in "\n".join(str(item) for item in assets["social_teaser_options"])
    assert any(
        fragment in package["publish_lead"]
        for fragment in (
            "背后往往是父母、孩子、伴侣和一整个家的分量",
            "人间安稳不是没有风雨",
            "这些事一下都排到前面",
            "一个家能慢慢稳下来",
        )
    )
    assert "这些事你心里很快就排了一遍：" not in package["publish_lead"]
    assert package["abstract"] != assets["cover_copy"]
    assert any(
        fragment in package["abstract"]
        for fragment in (
            "家里那口悬着的气",
            "万般辛苦不是终点",
            "这些年真没白忙",
        )
    )
    assert all(not workbench._starts_with_generic_packaging_openers(item) for item in package["intro_options"])


def test_build_local_responsibility_shelter_fallback_uses_endurance_variant_for_i_am_ok_article() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "肩上有责任的人，心里也要留一盏灯",
            "topic_angle": "从成年人总把那句“我没事”顶在前面切入，写万般辛苦最后怎样慢慢换成一家人的安稳。",
            "reference_article_body_markdown": (
                "中年人的世界，半生风雨，半生奔波。电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。"
                "成年人说过最多的谎，就是“我没事”。"
                "有时候，你也会问自己，我们拼尽全力去蹚这生活的泥水，咽下这么多的苦，到底值不值得？"
                "有一句话说：熬过万般辛苦，便得人间安稳。"
            ),
            "outline": {
                "hook": "电话一响，你还没来得及说累，先把那句“没事，有我”放到了前面。",
                "outline_body": (
                    "### 1. 从“我没事”切入\n"
                    "### 2. 写清责任为什么总让人把自己往后放\n"
                    "### 3. 写那些辛苦怎样慢慢换成家里的安稳\n"
                    "### 4. 结尾回到万般辛苦终会落成人间安稳"
                ),
            },
            "strategy_card": {
                "positive_direction": "万般辛苦不是终点，最后回到一家人的安稳和那个一直认真生活的人也该被温柔接住。"
            },
        }
    )

    assert title in {
        "电话一响，你先翻日历",
        "电话一响，你先把顺序往前排",
        "手机一亮，你先算今天怎么排",
    }
    assert body_markdown.startswith("电话一响，你先把手里的事停了一下")
    assert "嘴上先说一句“我先来想办法”" in body_markdown
    assert "你也会在夜里问一句：这样一天天接着，到底图什么。" in body_markdown
    assert "所谓人间安稳，从来不是生活忽然不难了。" in body_markdown
    assert "家里后来这点安稳，都是你一件事一件事接出来的。" in body_markdown
    assert "认真过日子的人，本来就值得被这样心疼。" in body_markdown
    assert "一盒药" not in body_markdown
    assert "校服" not in body_markdown
    assert "冰箱" not in body_markdown
    assert workbench.evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown).score == 0


def test_local_responsibility_assets_and_publish_package_use_endurance_variant_packaging() -> None:
    draft_title, draft_body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "肩上有责任的人，心里也要留一盏灯",
            "topic_angle": "从成年人总把那句“我没事”顶在前面切入，写万般辛苦最后怎样慢慢换成一家人的安稳。",
            "reference_article_body_markdown": (
                "中年人的世界，半生风雨，半生奔波。电话的那头，是父母、孩子和账单。"
                "电话的这头，你扛住压力，喉咙发紧，却只能故作轻松地说一句：没事，有我。"
                "成年人说过最多的谎，就是“我没事”。"
                "有时候，你也会问自己，值不值得。"
                "生病了不敢请假，怕影响这个月的绩效；委屈了不敢辞职，因为你要撑起一个家的重量。"
                "熬过万般辛苦，便得人间安稳。"
            ),
            "outline": {
                "hook": "电话一响，你还没来得及说累，先把那句“没事，有我”放到了前面。",
                "outline_body": "### 1. 从“我没事”切入\n### 2. 写责任\n### 3. 写安稳\n### 4. 回到人间安稳",
            },
            "strategy_card": {
                "positive_direction": "最后回到一家人的安稳，也回到那个一直认真生活的人值得被温柔接住。"
            },
        }
    )
    assets = workbench._build_local_assets_fallback(
        project_title=draft_title,
        topic_title="肩上有责任的人，心里也要留一盏灯",
        topic_angle="从成年人总把那句“我没事”顶在前面切入，写万般辛苦最后怎样慢慢换成一家人的安稳。",
        draft_title=draft_title,
        draft_body_markdown=draft_body_markdown,
    )
    asset_item = workbench.AssetItem(
        project_slug="local-responsibility-endurance",
        draft_version=1,
        version=1,
        cover_image_path="",
        cover_image_url="",
        **assets,
    )
    package = workbench._build_local_publish_package_fallback(
        draft_title=draft_title,
        draft_body_markdown=draft_body_markdown,
        assets=asset_item,
    )

    assert assets["recommended_title"] in {
        "电话一响，你先翻日历",
        "电话一响，你先把顺序往前排",
        "手机一亮，你先算今天怎么排",
    }
    assert assets["cover_copy"] in {
        "你扛住的那些日常，后来都在替家里换安稳。",
        "你替一家人扛住风雨，也别忘了给自己留一盏灯。",
    }
    assert any(
        fragment in assets["social_teaser"]
        for fragment in (
            "父母那边谁陪",
            "孩子这边谁接",
        )
    )
    assert any(
        fragment in assets["social_teaser"]
        for fragment in (
            "把家慢慢托稳",
            "家里的安稳",
        )
    )
    assert "心里很快就排了一遍：" not in assets["social_teaser"]
    assert any(
        fragment in "\n".join(str(item) for item in assets["social_teaser_options"])
        for fragment in (
            "很多中年人的一天，都是从把自己往后放半步开始的。",
            "把家撑住的人，也别忘了照顾那个总说“我没事”的自己。",
        )
    )
    assert any(
        fragment in str(package["publish_lead"])
        for fragment in (
            "电话一响，你先想的不是自己累不累",
            "很多中年人的日子，就是这样一件件往前接出来的",
            "自己稳一点，家里那盏灯就稳一点",
            "很多中年人的日子，就是这样一件件往前接出来的",
        )
    )
    assert "这些事你心里很快就排了一遍：" not in str(package["publish_lead"])
    assert any(
        fragment in str(package["abstract"])
        for fragment in (
            "家里那口悬着的气",
            "嘴上那句“没事”后面的辛苦",
        )
    )
    assert "这些年真没白忙" in str(package["abstract"])
    assert all(not workbench._starts_with_generic_packaging_openers(item) for item in package["intro_options"])


def test_local_everyday_warmth_publish_package_uses_small_things_variant() -> None:
    draft_body = (
        "有些晚上，推开家门闻到饭香，人才忽然不想再和谁比较了。\n\n"
        "年轻时总觉得幸福要有很大的样子：账户数字再漂亮一点，房子再大一点，朋友圈再热闹一点。\n\n"
        "可人走到后来，会被很小的事劝住。\n\n"
        "父母电话里一句“别太累”，朋友饭桌上一句“你先说完”，孩子回头喊你一声，心就落了地。\n\n"
        "见面、拥抱、吃饭、散步、晒太阳，这些微小的事堆叠起来，才是我们的一生。"
    )
    assets = workbench._build_local_assets_fallback(
        project_title="很多“大事”最后都会祛魅，留下你的反而是这些小事",
        topic_title="很多“大事”最后都会祛魅，留下你的反而是这些小事",
        topic_angle="从人为什么总被做大事推着往前跑切入，也写那些不起眼的小事怎样慢慢把人劝回人间烟火里。",
        draft_title="很多“大事”最后都会祛魅，留下你的反而是这些小事",
        draft_body_markdown=draft_body,
    )
    asset_item = workbench.AssetItem(
        project_slug="local-everyday-small-things",
        draft_version=1,
        version=1,
        cover_image_path="",
        cover_image_url="",
        **assets,
    )
    package = workbench._build_local_publish_package_fallback(
        draft_title="很多“大事”最后都会祛魅，留下你的反而是这些小事",
        draft_body_markdown=draft_body,
        assets=asset_item,
    )

    assert package["publish_lead"] == "周末陪父母在小区慢慢走一圈，陪孩子把积木铺满地，再和爱人拎着菜回家。一天没有发生什么大事，可晚上躺下时，心里是满的。"
    assert package["abstract"] == "真正属于你的生活，很少写在履历上。它藏在一次没有催促的散步、一个肯好好陪伴的下午里。把这些小事捡回来，日子就有了温度。"
    assert package["abstract"] != assets["social_teaser"]
    assert any("陪父母走慢一点" in item or "履历写不下的陪伴" in item for item in package["intro_options"])


def test_build_local_tracked_article_draft_fallback_shapes_everyday_warmth_simple_happiness_variant() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "article_title": "人活着，到底是为了什么？",
            "topic_title": "人到后来才明白，最好的福气不过是家人平安、知己仍在",
            "topic_angle": "从人为什么总把幸福押在更大的拥有上切入，写一路追着体面和更多往前赶，最后却被家人平安、知己仍在和一顿热饭轻轻劝回来的过程。",
            "reference_article_body_markdown": (
                "人生不求大富大贵，但求简单快乐。家人安康，知己二三，四季平安。"
                "知己二三，父母做的饭，孩子的笑声，都是最真实的幸福。"
            ),
            "strategy_card": {"structure_mode": "everyday_warmth_return"},
            "problem_brief": {
                "theme_axis": "主线是人为什么把幸福误认成更大的拥有，后来又被眼前日常慢慢托住。",
                "core_conflict": "财富、排场、圈子和房子未必持续提供踏实感，家人平安和知己仍在反而更有分量。",
            },
        }
    )

    paragraphs = [part for part in body_markdown.split("\n\n") if part.strip()]
    assert title == "人到后来才明白，最好的福气不过是家人平安、知己仍在"
    assert body_markdown.startswith("后来你会发现，真正让人踏实的，常常不是赢了多少，而是家里那盏灯还亮着，老朋友还在。")
    assert "所谓简单快乐，是见过起落以后，依然知道什么东西值得你一直放在心上" in body_markdown
    assert "家人平安，知己仍在，心里没有那么多挂心事，就是一种实打实的福气" in body_markdown
    assert "人活到后来，求的未必是大富大贵，更多是一家人平安，饭能趁热吃，话能慢慢说" in body_markdown
    assert "鞋还没换好" not in body_markdown
    assert "回来啦？先洗手。" not in body_markdown
    assert "人间有味是清欢" not in body_markdown
    assert "会被很小的事劝住" not in body_markdown
    assert "那一刻，他忽然觉得" not in body_markdown
    assert len(paragraphs) == 9
    assert all(len(part) <= 100 for part in paragraphs)


def test_local_everyday_warmth_publish_package_uses_simple_happiness_variant() -> None:
    draft_title, draft_body = workbench._build_local_tracked_article_draft_fallback(
        {
            "article_title": "人活着，到底是为了什么？",
            "topic_title": "人到后来才明白，最好的福气不过是家人平安、知己仍在",
            "topic_angle": "从人为什么总把幸福押在更大的拥有上切入，写一路追着体面和更多往前赶，最后却被家人平安、知己仍在和一顿热饭轻轻劝回来的过程。",
            "reference_article_body_markdown": (
                "人生不求大富大贵，但求简单快乐。家人安康，知己二三，四季平安。"
                "知己二三，父母做的饭，孩子的笑声，都是最真实的幸福。"
            ),
            "strategy_card": {"structure_mode": "everyday_warmth_return"},
            "problem_brief": {
                "theme_axis": "主线是人为什么把幸福误认成更大的拥有，后来又被眼前日常慢慢托住。",
                "core_conflict": "财富、排场、圈子和房子未必持续提供踏实感，家人平安和知己仍在反而更有分量。",
            },
        }
    )
    assets = workbench._build_local_assets_fallback(
        project_title=draft_title,
        topic_title="人到后来才明白，最好的福气不过是家人平安、知己仍在",
        topic_angle="从人为什么总把幸福押在更大的拥有上切入，写一路追着体面和更多往前赶，最后却被家人平安、知己仍在和一顿热饭轻轻劝回来的过程。",
        draft_title=draft_title,
        draft_body_markdown=draft_body,
    )
    asset_item = workbench.AssetItem(
        project_slug="local-everyday-simple-happiness",
        draft_version=1,
        version=1,
        cover_image_path="",
        cover_image_url="",
        **assets,
    )
    package = workbench._build_local_publish_package_fallback(
        draft_title=draft_title,
        draft_body_markdown=draft_body,
        assets=asset_item,
    )

    assert assets["cover_copy"] == "家人平安，老友还在，普通日子也会慢慢发光。"
    assert assets["social_teaser"] == "后来你会发现，真正让人踏实的，常常不是赢了多少，而是家里那盏灯还亮着，老朋友还在。家人平安，知己仍在，很多普通日子也会慢慢发光。"
    assert "傍晚家中餐桌或客厅一角" in assets["cover_prompt"]
    assert "热饭" in assets["cover_prompt"]
    assert "药盒" not in assets["cover_prompt"]
    assert "检查单" not in assets["cover_prompt"]
    assert package["publish_lead"] == "人活到后来，求的未必是大富大贵，更多是一家人平安、知己仍在、饭能趁热吃、话能慢慢说。"
    assert package["abstract"] == "幸福不一定长在高处，它常常就在晚饭的热气、老友的回应和家里的灯光里。能把这样的日常守住，已经很难得。"
    assert package["abstract"] != assets["social_teaser"]
    assert "一顿热饭、一句惦记" not in package["publish_lead"]
    assert any("一日三餐" in item or "平凡日子也会发光" in item for item in package["intro_options"])


def test_build_local_tracked_article_draft_fallback_shapes_self_reliance_mode_with_distinct_voice() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "扛事久了的人，最后都要学会把自己慢慢接回来",
            "reference_article_body_markdown": "很多时候不是没人可找，而是大家都在忙。先把自己稳住，才慢慢把日子接回来。",
            "outline": {
                "hook": "事情一下撞到眼前、四周都腾不出空的时候，最先冒出来的往往是慌。",
                "outline_body": (
                    "1. 很多人就是这样慢慢习惯先自己扛下去\n"
                    "2. 总向外等的时候，力气也会一点点散掉\n"
                    "3. 那些代价最后都会落进每天的日常里\n"
                    "4. 最后还是要把自己一点点接回来"
                ),
            },
            "strategy_card": {
                "structure_mode": "self_reliance_inward_support",
                "positive_direction": "最后回到先把自己一点点接回来，不要写成苦撑赞歌。",
            },
            "problem_brief": {
                "theme_axis": "主线是成年人怎样慢慢把向外等的力气收回来。",
                "core_conflict": "人明明很累了，却总习惯先自己顶住。",
            },
        }
    )

    assert title == "扛事久了的人，最后都要学会把自己慢慢接回来"
    assert not body_markdown.startswith("事情一多的时候，先把眼前能确定的一件事抓住。")
    assert body_markdown.startswith(("有些难处不是不想说", "真正长大以后你会发现", "人最清醒的一刻"))
    assert "事情一下撞到眼前、四周都腾不出空的时候，最先冒出来的往往是慌。" not in body_markdown
    assert "真正的稳，不是把委屈都咽回去。" not in body_markdown
    assert "先把眼前能确定的一件事抓住" not in body_markdown
    assert "能把日子往前带的人" in body_markdown
    assert "把选择重新拿回来" in body_markdown
    assert "并不是认输" not in body_markdown
    assert "不等于只能硬撑" not in body_markdown
    assert "并不是一个人把所有难处硬熬过去" not in body_markdown
    assert "不是立刻想通所有事" not in body_markdown
    assert "人最有力量的时候，不是从来不慌。" not in body_markdown
    assert "大家手里都各有难处" not in body_markdown
    assert "没人腾得出手" not in body_markdown
    assert len([paragraph for paragraph in body_markdown.split("\n\n") if paragraph.strip()]) >= 8
    for forbidden in ("磨钝", "睡眠", "胃口", "束手无策", "忍住不哭", "很多事真正难的地方", "每个人都在", "孤立无援", "靠自己，", "。这不是"):
        assert forbidden not in body_markdown


def test_build_local_tracked_article_draft_fallback_self_reliance_shared_burden_body_stays_distinct() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "没人能立刻搭把手的时候，先把自己从慌里带出来",
            "topic_angle": "从成年人想找人倾诉、想向外求助，却发现别人也各自承压切入，写外面的帮扶为什么未必总能及时赶上；也写一个人怎样在低谷里先把自己安顿住，先把情绪放稳，先把日子接回来，再一点点长出继续往前的力气。",
            "reference_article_body_markdown": "如果一味向外求，或许求而不得。只有向内求，才能自我疗愈，生生不息。",
            "strategy_card": {
                "structure_mode": "self_reliance_inward_support",
                "hook_trigger": "外面的帮扶一时赶不上，自己先要把今天接过去的那一下。",
            },
            "problem_brief": {
                "theme_axis": "主线是外面的帮扶并不总能刚好赶上，一个人怎样先把自己托住，再把日子一点点接回来。",
                "core_conflict": "越把希望全压在外面的安慰上，心就越容易一直悬着；真正让人慢慢站稳的，往往是先把今天过完，再把力气一点点收回自己身上。",
            },
        }
    )

    assert any(anchor in title for anchor in ("力气", "主心骨", "自己的光"))
    assert body_markdown.startswith(("有些难处不是不想说", "真正长大以后你会发现", "人最清醒的一刻"))
    assert "事情一多的时候，先把眼前能确定的一件事抓住。" not in body_markdown
    assert "真正的稳，不是把委屈都咽回去。" not in body_markdown
    assert "判断回来了、行动还在" in body_markdown
    assert "把力气重新回到自己手里" not in body_markdown
    assert "把桌面清出一块地方，把明天最先要用的东西放到手边" not in body_markdown
    assert "电话要不要回，事情先做哪件" not in body_markdown


def test_build_local_tracked_article_draft_fallback_shapes_self_worth_mode_away_from_generic_shell() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "总把自己往后让的人，迟早要学会把自己放回前面",
            "reference_article_body_markdown": "你越将就，别人越随便。把自己放回前面，关系才会重新长出分寸。",
            "outline": {
                "outline_body": (
                    "1. 总迁就的人，最后最容易先委屈自己\n"
                    "2. 位置一再往后让，关系也会慢慢顺着这个位置来\n"
                    "3. 那些被忽略后的感受，最后都会落进日常里\n"
                    "4. 最后还是要把自己放回前面"
                ),
            },
            "strategy_card": {
                "structure_mode": "self_worth_rebuild",
                "positive_direction": "最后回到把自己放回前面，不要写成训话。",
            },
            "problem_brief": {
                "theme_axis": "主线是一个人怎样把总往后退的位置慢慢收回来。",
                "core_conflict": "你总怕别人不高兴，最后最委屈的常常是自己。",
            },
        }
    )

    assert title == "总把自己往后让的人，迟早要学会把自己放回前面"
    assert body_markdown.startswith(
        (
            "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。",
            "你明明也有想法，可轮到自己时，还是习惯先说一句“算了，也行”。",
        )
    )
    assert "点菜时你想吃辣，最后还是说“都可以”。别人临时改约，你明明失落，也只回一句：没事。" in body_markdown
    assert "先把那个总被你放到最后的人找回来。" not in body_markdown
    assert "很多委屈都不是大事砸下来的。" in body_markdown
    assert "别再让委屈替你懂事收尾" in body_markdown
    assert "先在心里过一遍：这次我是真的愿意，还是又想赶紧把场面圆过去。" in body_markdown
    assert "把那点不舒服重新当回事，关系里的位置才会慢慢清楚。" not in body_markdown
    assert "认真对待自己以后，关系里的分寸会慢慢清楚。" not in body_markdown
    assert "很多情绪不是突然冒出来的" not in body_markdown
    for forbidden in ("把自己养贵一点", "门槛抬高一点", "自己的感受", "不是变得难相处", "贱卖", "愿你往后", "当你开始", "日子才"):
        assert forbidden not in body_markdown
    paragraphs = [paragraph.strip() for paragraph in body_markdown.split("\n\n") if paragraph.strip()]
    assert len(paragraphs) >= 11
    assert max(len(paragraph) for paragraph in paragraphs) <= 80
def test_build_local_tracked_article_outline_fallback_shapes_self_worth_mode_without_strategy_leak() -> None:
    outline = workbench._build_local_tracked_article_outline_fallback(
        {
            "topic_title": "很多答案，都是把日子过到眼前以后，才慢慢看清的",
            "topic_angle": "从一个人为什么总在将就、讨好和顺手退让里慢慢压低自己切入，也写她怎样重新尊重自己。",
            "reference_article_body_markdown": "你越将就，别人越随便。把自己放回前面，关系才会重新长出分寸。",
            "strategy_card": {
                "structure_mode": "self_worth_rebuild",
                "hook_trigger": "一句“都可以”“算了”“我没事”背后，自己其实已经不舒服的那一下。",
                "positive_direction": "结尾回到边界重新立住、标准慢慢收紧和人终于不再总把自己放轻，不要停在控诉、委屈或翻旧账上。",
            },
            "problem_brief": {
                "theme_axis": "主线是人为什么总在关系里先把自己放轻、把边界和标准往后撤，后来又怎样重新尊重自己，让体面和分量慢慢回到自己身上。",
                "core_conflict": "越怕失去、越急着证明自己值得被爱，越容易先把边界、标准和体面一点点让出去。",
            },
        }
    )

    assert outline["hook"] in {
        "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。",
        "你明明也有想法，可轮到自己时，还是习惯先说一句“算了，也行”。",
    }
    assert "主线是" not in outline["outline_body"]
    assert "为什么总在" not in outline["outline_body"]
    assert "结尾回到" not in outline["outline_body"]
    assert "很多人一开始并不是没脾气" in outline["outline_body"]
    assert "你总替别人圆场、替关系找补" in outline["outline_body"]
    assert "边界一退再退、委屈一忍再忍" in outline["outline_body"]


def test_build_local_tracked_article_draft_fallback_uses_mode_shaped_outline_for_self_worth_payload() -> None:
    payload = {
        "topic_title": "很多答案，都是把日子过到眼前以后，才慢慢看清的",
        "topic_angle": "从一个人为什么总在将就、讨好和顺手退让里慢慢压低自己切入，也写她怎样重新尊重自己。",
        "reference_article_body_markdown": "你越将就，别人越随便。把自己放回前面，关系才会重新长出分寸。",
        "strategy_card": {
            "structure_mode": "self_worth_rebuild",
            "hook_trigger": "一句“都可以”“算了”“我没事”背后，自己其实已经不舒服的那一下。",
            "positive_direction": "结尾回到边界重新立住、标准慢慢收紧和人终于不再总把自己放轻，不要停在控诉、委屈或翻旧账上。",
        },
        "problem_brief": {
            "theme_axis": "主线是人为什么总在关系里先把自己放轻、把边界和标准往后撤，后来又怎样重新尊重自己，让体面和分量慢慢回到自己身上。",
            "core_conflict": "越怕失去、越急着证明自己值得被爱，越容易先把边界、标准和体面一点点让出去。",
        },
    }
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            **payload,
            "outline": workbench._build_local_tracked_article_outline_fallback(payload),
        }
    )

    assert title == "很多答案，都是把日子过到眼前以后，才慢慢看清的"
    assert body_markdown.startswith(
        (
            "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。",
            "你明明也有想法，可轮到自己时，还是习惯先说一句“算了，也行”。",
        )
    )
    assert "主线是" not in body_markdown
    assert "很多答案，都是把日子过到眼前以后，才慢慢看清的" not in body_markdown
    assert body_markdown.startswith(
        (
            "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。",
            "你明明也有想法，可轮到自己时，还是习惯先说一句“算了，也行”。",
        )
    )
    assert "点菜时你想吃辣，最后还是说“都可以”。别人临时改约，你明明失落，也只回一句：没事。" in body_markdown
    assert "先把那个总被你放到最后的人找回来。" not in body_markdown
    assert "很多委屈都不是大事砸下来的。" in body_markdown
    assert "别再让委屈替你懂事收尾" in body_markdown
    assert "先在心里过一遍：这次我是真的愿意，还是又想赶紧把场面圆过去。" in body_markdown
    assert "把那点不舒服重新当回事，关系里的位置才会慢慢清楚。" not in body_markdown
    for forbidden in ("把自己养贵一点", "门槛抬高一点", "自己的感受", "不是变得难相处", "贱卖", "愿你往后", "当你开始", "日子才"):
        assert forbidden not in body_markdown


def test_build_local_tracked_article_draft_fallback_self_worth_uses_reference_position_opening() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "别让那句“都可以”，替你让掉自己的位置",
            "reference_article_body_markdown": (
                "总在委屈里迁就的人，会活成打折品；只在欢喜里停留的人，会活成奢侈品。"
                "你越将就，遇见的人就对你越随便；你越讲究，遇见的人对你越认真。"
                "从今天起，把门槛抬高一点，把标准收紧一点。"
            ),
            "outline": {
                "hook": "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。",
                "outline_body": "1. 总迁就的人，最后最容易先委屈自己\n2. 位置一再往后让，关系也会慢慢顺着这个位置来\n3. 那些被忽略后的感受，最后都会落进日常里\n4. 最后还是要把自己放回前面",
            },
            "strategy_card": {"structure_mode": "self_worth_rebuild"},
            "problem_brief": {
                "theme_axis": "主线是一个人怎样把总往后退的位置慢慢收回来。",
                "core_conflict": "你总怕别人不高兴，最后最委屈的常常是自己。",
            },
        }
    )

    assert title == "别让那句“都可以”，替你让掉自己的位置"
    assert body_markdown.startswith(("你其实有标准，只是太习惯先把场面让过去，连自己那点不舒服也跟着往后放了。", "很多关系里最先被压低的，不是身价，是你明明不想答应，嘴上还是先说了句“行”。"))
    assert "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。" not in body_markdown.split("\n\n")[0]


def test_build_local_publish_package_fallback_self_worth_uses_mode_lead_and_abstract() -> None:
    assets = SimpleNamespace(
        recommended_title="别让那句“都可以”，替你让掉自己的位置",
        title_options=["别让那句“都可以”，替你让掉自己的位置"],
        cover_copy="别让那句“都可以”，替你让掉自己的位置。",
        social_teaser="你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。别让那句“都可以”，替你让掉自己的位置。",
        social_teaser_options=["你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。别让那句“都可以”，替你让掉自己的位置。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="别让那句“都可以”，替你让掉自己的位置",
        draft_body_markdown=(
            "很多关系里最先被压低的，不是身价，是你明明不想答应，嘴上还是先说了句“行”。\n\n"
            "点菜时你想吃辣，最后还是说“都可以”。别人临时改约，你明明失落，也只回一句：没事。\n\n"
            "下次那句“都可以”到嘴边时，先停一下。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "你不是突然变了，只是慢慢发现，总把自己往后让，别人也会顺着这个位置来对待你。后来你才明白，关系里先要守住的，是自己的位置。"
    assert package["abstract"] == "总在将就里退半步的人，最容易先委屈自己。把真实想法说出来，不是难相处，是把自己慢慢放回前面。"


def test_build_local_tracked_article_draft_fallback_self_worth_uses_luxury_profile_variation() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "把自己看重一点，关系里的分寸才会回来",
            "reference_article_body_markdown": "你不贵重，就容易被忽略；你不自爱，就是会被辜负。总把时间贱卖给不值得的人和事，只会越忙越廉价。把自己养贵一点，日子才能过好一点。",
            "outline": {
                "hook": "很多关系里最先被压低的，不是身价，是你明明不想答应，嘴上还是先说了句“行”。",
                "outline_body": "1. 先把自己放低的人，最容易先丢掉分寸\n2. 门槛和标准为什么会慢慢退掉\n3. 重新看重自己以后，关系才会回来",
            },
            "strategy_card": {"structure_mode": "self_worth_rebuild"},
        }
    )

    assert title == "把自己看重一点，关系里的分寸才会回来"
    assert "所谓把自己养贵一点，说到底，就是开始知道什么关系值得花时间，什么要求不必硬着头皮接。" in body_markdown
    assert "门槛摆在那里，只是提醒自己：别再为了显得懂事，把尊重和体面一并让掉。" in body_markdown
    assert "点菜时你想吃辣，最后还是说“都可以”。" not in body_markdown


def test_build_local_tracked_article_topic_fallback_uses_self_worth_mode_seed() -> None:
    topic = workbench._build_local_tracked_article_topic_fallback(
        {
            "article_title": "把自己养贵一点，日子才能过好一点",
            "body_markdown": (
                "你总怕失去别人，就会常常弄丢自己。"
                "从今天起，把门槛抬高一点，把标准收紧一点，只要你不随意降低自己的身价，"
                "生活自然会给你配得上的回馈。"
            ),
            "summary": "",
            "structure_notes": "",
        }
    )

    assert topic["title"] == "把自己看重一点，关系里的分寸才会回来"
    assert "标准" in topic["angle"] or "边界" in topic["angle"] or "体面" in topic["angle"]
    assert topic["title"] != "很多答案，都是把日子过到眼前以后，才慢慢看清的"
    for forbidden in ("养贵", "高傲", "贱卖", "不是高傲"):
        assert forbidden not in topic["title"]
    for forbidden in ("养贵", "高傲", "贱卖", "不是高傲"):
        assert forbidden not in topic["title"]


def test_build_local_assets_fallback_uses_mode_shaped_cover_copy_for_self_worth_payload() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="很多答案，都是把日子过到眼前以后，才慢慢看清的",
        topic_title="很多答案，都是把日子过到眼前以后，才慢慢看清的",
        topic_angle="从一个人为什么总在将就、讨好和顺手退让里慢慢压低自己切入。",
        draft_title="很多答案，都是把日子过到眼前以后，才慢慢看清的",
        draft_body_markdown=(
            "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。\n\n"
            "先把那个总被你放到最后的人找回来。\n\n"
            "总在委屈里将就的人，看起来像是心软，实际上常常是先把自己摆得太轻。"
        ),
    )

    assert assets["cover_copy"] == "别让那句“都可以”，替你让掉自己的位置。"
    assert (
        assets["social_teaser"]
        == "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。别让那句“都可以”，替你让掉自己的位置。"
    )


def test_build_local_assets_fallback_self_worth_uses_luxury_profile_copy() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="把自己看重一点，关系里的分寸才会回来",
        topic_title="把自己看重一点，关系里的分寸才会回来",
        topic_angle="从把自己养贵一点、把门槛和标准收回来切入。",
        draft_title="把自己看重一点，关系里的分寸才会回来",
        draft_body_markdown=(
            "很多关系里最先被压低的，不是身价，是你明明不想答应，嘴上还是先说了句“行”。\n\n"
            "所谓把自己养贵一点，说到底，就是开始知道什么关系值得花时间，什么要求不必硬着头皮接。\n\n"
            "把自己放回前面，本身就是一种清醒。"
        ),
    )

    assert assets["cover_copy"] == "把自己看重一点，关系里的分寸才会回来。"
    assert "把自己看重一点，关系里的分寸才会慢慢回来。" in assets["social_teaser"]


def test_build_local_publish_package_fallback_self_worth_uses_luxury_profile_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="把自己看重一点，关系里的分寸才会回来",
        title_options=["把自己看重一点，关系里的分寸才会回来"],
        cover_copy="把自己看重一点，关系里的分寸才会回来。",
        social_teaser="很多关系里最先被压低的，不是身价，是你明明不想答应，嘴上还是先说了句“行”。把自己看重一点，关系里的分寸才会慢慢回来。",
        social_teaser_options=["很多关系里最先被压低的，不是身价，是你明明不想答应，嘴上还是先说了句“行”。把自己看重一点，关系里的分寸才会慢慢回来。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="把自己看重一点，关系里的分寸才会回来",
        draft_body_markdown=(
            "很多关系里最先被压低的，不是身价，是你明明不想答应，嘴上还是先说了句“行”。\n\n"
            "所谓把自己养贵一点，说到底，就是开始知道什么关系值得花时间，什么要求不必硬着头皮接。\n\n"
            "门槛摆在那里，只是提醒自己：别再为了显得懂事，把尊重和体面一并让掉。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "你越轻易把自己放低，别人越容易把你的体面当成可商量。后来你才懂，把自己看重，不是端着，而是不再拿委屈去换关系。"
    assert package["abstract"] == "门槛不是摆给别人看的，是用来提醒自己：什么该答应，什么不该将就。把标准收回来，真正珍惜你的人反而会更认真靠近。"



def test_build_local_assets_fallback_filters_generic_packaging_titles() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="很多人总在关系里慢慢失去自己",
        topic_title="很多人总在关系里慢慢失去自己",
        topic_angle="从一句都可以和边界一次次后退切入。",
        draft_title="很多人总在关系里慢慢失去自己",
        draft_body_markdown=(
            "那句都可以到了嘴边时，先问问自己是不是也被照顾到了。\n\n"
            "边界不是冷漠，是你终于开始尊重自己。\n\n"
            "标准收紧一点，关系反而会更清楚。"
        ),
    )

    assert assets["recommended_title"] == "别让那句“都可以”，替你让掉自己的位置"
    assert all(not workbench._starts_with_generic_packaging_openers(title) for title in assets["title_options"])


def test_build_local_assets_fallback_keeps_responsibility_theme_when_body_mentions_wo_meishi() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="很多人的那句我没事，背后都是责任",
        topic_title="很多人的那句我没事，背后都是责任",
        topic_angle="从中年人把辛苦先收起来切入，写责任怎样落回父母、孩子和家里的安稳。",
        draft_title="很多人的那句我没事，背后都是责任",
        draft_body_markdown=(
            "那句我没事说出口的时候，心里想的是父母的身体、孩子的安排和家里的日子。\n\n"
            "中年以后，责任会让人先把情绪放稳，再把重要的人护住。\n\n"
            "真正让人继续往前的，是看见家里的安稳一点点落下来。"
        ),
    )

    assert assets["recommended_title"] == "肩上有责任的人，心里也要留一盏灯"
    assert assets["recommended_title"] != "真正在意你的人，会把话接下去"
    assert assets["cover_copy"] == "肩上有责任，心里也要留一盏灯。"
    assert "回你" not in assets["social_teaser"]
    assert "话接下去" not in assets["social_teaser"]

def test_build_local_publish_package_fallback_filters_generic_asset_packaging_fields() -> None:
    assets = SimpleNamespace(
        recommended_title="很多人总在关系里慢慢失去自己",
        title_options=["很多人总在关系里慢慢失去自己", "有些人总在关系里先委屈自己"],
        cover_copy="把边界立回来",
        social_teaser="很多人会在一句都可以里，把边界一点点放低。",
        social_teaser_options=[
            "很多人会在一句都可以里，把边界一点点放低。",
            "那句都可以出口前，先把自己的感受放回桌面。",
        ],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="很多人总在关系里慢慢失去自己",
        draft_body_markdown=(
            "那句都可以到了嘴边时，先问问自己是不是也被照顾到了。\n\n"
            "边界不是冷漠，是你终于开始尊重自己。"
        ),
        assets=assets,
    )

    assert package["publish_title"] == "别让那句“都可以”，替你让掉自己的位置"
    assert package["publish_lead"] == "把边界立回来"
    assert all(not workbench._starts_with_generic_packaging_openers(item) for item in package["intro_options"])
    assert "那句都可以出口前，先把自己的感受放回桌面。" in package["intro_options"]


def test_resolve_local_generic_opening_skips_stale_inner_settlement_hook_trigger() -> None:
    opening = workbench._resolve_local_generic_opening(
        payload={"strategy_card": {"hook_trigger": "心明明还悬着，却被一个普通安排慢慢接回今天的那一下。"}},
        mode="inner_settlement",
        hook="心明明还悬着，却被一个普通安排慢慢接回今天的那一下。",
        theme_axis="",
        core_conflict="",
    )

    assert opening == "忙完一天回到家，把鞋摆好，给自己倒杯水；没有答案也没关系，心先有地方安静下来。"


def test_tracked_article_candidate_mode_keeps_inner_settlement_ahead_of_scene_first() -> None:
    mode = workbench._resolve_tracked_article_candidate_mode(
        title="把心放回今天，日子才会慢慢安稳",
        markdown=(
            "忙完一天回到家，先把鞋摆好，给自己倒杯水。\n\n"
            "心安不是把生活按停，是还能把今天过清楚。"
        ),
    )

    assert mode == "inner_settlement"

def test_resolve_local_generic_opening_skips_stale_self_reliance_hook_trigger() -> None:
    opening = workbench._resolve_local_generic_opening(
        payload={
            "strategy_card": {
                "hook_trigger": "外面的帮扶一时赶不上，自己先要把今天接过去的那一下。",
                "packaging_hook": "先抓想开口却发现别人也各自承压的那一下，再带回人怎样先把自己托住。",
            },
        },
        mode="self_reliance_inward_support",
        hook="外面的帮扶一时赶不上，自己先要把今天接过去的那一下。",
        theme_axis="",
        core_conflict="",
    )

    assert opening == "把一件小事做稳的时候，人会慢慢找回自己的主心骨。"

    default_opening = workbench._resolve_local_generic_opening(
        payload={},
        mode="self_reliance_inward_support",
        hook="",
        theme_axis="",
        core_conflict="",
    )

    assert default_opening == "把一件小事做稳的时候，人会慢慢找回自己的主心骨。"


def test_resolve_local_generic_opening_uses_concrete_resilience_scene() -> None:
    opening = workbench._resolve_local_generic_opening(
        payload={},
        mode="resilience_reconstruction",
        hook="",
        theme_axis="",
        core_conflict="",
    )

    assert opening == "训练没做完的那天，你坐在原地缓了一会儿；第二天，还是重新站回了起点。"


def test_resolve_local_generic_opening_uses_concrete_emotional_scene() -> None:
    opening = workbench._resolve_local_generic_opening(
        payload={},
        mode="emotional_engine_direct",
        hook="",
        theme_axis="",
        core_conflict="",
    )

    assert opening == "路过那家旧店时，你脚步慢了一下，才发现有些告别并不会在当天结束。"


def test_resolve_local_generic_opening_uses_concrete_supportive_scene() -> None:
    opening = workbench._resolve_local_generic_opening(
        payload={},
        mode="supportive_appreciation",
        hook="",
        theme_axis="",
        core_conflict="",
    )

    assert opening == "饭桌上她先问一句“还吃吗？”，像什么都没发生；可她把那口气咽下去的样子，只有熟悉她的人看得见。"


def test_resolve_local_generic_opening_uses_concrete_response_scene() -> None:
    opening = workbench._resolve_local_generic_opening(
        payload={},
        mode="response_priority",
        hook="",
        theme_axis="",
        core_conflict="",
    )

    assert opening == "晚霞照片发出去以后，点赞很快就铺满屏幕；真正让你停下来的，是有人问你今天是不是很累。"


def test_resolve_local_generic_opening_uses_concrete_aftercare_scene() -> None:
    opening = workbench._resolve_local_generic_opening(
        payload={},
        mode="relationship_aftercare",
        hook="",
        theme_axis="",
        core_conflict="",
    )

    assert opening == "门关上以后，屋里安静了几分钟；他去厨房倒了杯水，回来时没有继续争输赢，只问你刚才是不是难受。"


def test_build_local_tracked_article_draft_fallback_response_generic_avoids_time_template() -> None:
    _title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "评论的分量",
            "body_markdown": "有些回应只是路过，真正的在意会停下来。",
            "strategy_card": {"structure_mode": "response_priority"},
            "problem_brief": {
                "theme_axis": "主线是认真回应如何让人感到被重视。",
                "core_conflict": "互动很多，但耐心听完的人很少。",
            },
        }
    )

    assert "等电梯的半分钟" not in body_markdown
    assert "时间给了谁" not in body_markdown
    assert "记得你昨天说过的难处" in body_markdown
    assert "对方愿意在场" in body_markdown


def test_resolve_local_generic_outline_hook_skips_scene_first_meta_jargon() -> None:
    hook = workbench._resolve_local_generic_outline_hook(
        payload={
            "strategy_card": {
                "hook_trigger": "那个原本可以问一句、开一次口，却还是被当场顺过去的现场接口。",
                "packaging_hook": "先抓一个连续现场，再把真正卡住人的判断慢慢递出来。",
            }
        },
        mode="scene_first_progression",
        topic_title="",
        topic_angle="",
        theme_axis="",
        core_conflict="",
    )

    assert "接口" not in hook
    assert "先抓" not in hook
    assert hook == "那句话停在嘴边的时候，关系其实已经轻轻往后退了一步。"


def test_build_local_tracked_article_draft_fallback_uses_mode_shaped_outline_for_self_reliance_payload() -> None:
    payload = {
        "topic_title": "没人能立刻搭把手的时候，先把自己从慌里带出来",
        "topic_angle": "从成年人想找人倾诉、想向外求助，却发现别人也各自承压切入，写外面的帮扶为什么未必总能及时赶上；也写一个人怎样在低谷里先把自己安顿住，先把情绪放稳，先把日子接回来，再一点点长出继续往前的力气。",
        "reference_article_body_markdown": "如果一味向外求，或许求而不得。只有向内求，才能自我疗愈，生生不息。",
        "strategy_card": {
            "structure_mode": "self_reliance_inward_support",
            "hook_trigger": "外面的帮扶一时赶不上，自己先要把今天接过去的那一下。",
            "positive_direction": "结尾回到向内稳住、自我托底和把今天先撑过去，不要只写无人可依的失落。",
        },
        "problem_brief": {
            "theme_axis": "主线是外面的帮扶并不总能刚好赶上，一个人怎样先把自己托住，再把日子一点点接回来。",
            "core_conflict": "越把希望全压在外面的安慰上，心就越容易一直悬着；真正让人慢慢站稳的，往往是先把今天过完，再把力气一点点收回自己身上。",
        },
    }
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            **payload,
            "outline": workbench._build_local_tracked_article_outline_fallback(payload),
        }
    )

    assert any(anchor in title for anchor in ("力气", "主心骨", "自己的光"))
    assert body_markdown.startswith(("有些难处不是不想说", "真正长大以后你会发现", "人最清醒的一刻"))
    assert "事情一多的时候，先把眼前能确定的一件事抓住。" not in body_markdown
    assert "也写一个人怎样" not in body_markdown
    assert "分清轻重缓急" not in body_markdown
    assert "能有人同行当然很好。" not in body_markdown
    assert "判断回来了、行动还在" in body_markdown
    assert "并不是认输" not in body_markdown
    assert "不等于只能硬撑" not in body_markdown
    assert "并不是一个人把所有难处硬熬过去" not in body_markdown
    assert "愿你以后" not in body_markdown
    assert len([paragraph for paragraph in body_markdown.split("\n\n") if paragraph.strip()]) >= 8
    assert "不要只写" not in body_markdown
    for forbidden in ("磨钝", "睡眠", "胃口", "忍住不哭", "束手无策", "每个人都在", "孤立无援", "靠自己，", "。这不是", "很多时候，先把自己扶稳", "愿你以后", "无人可依"):
        assert forbidden not in body_markdown


def test_build_local_assets_fallback_uses_mode_shaped_social_teaser_for_self_reliance_payload() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="没人能立刻搭把手的时候，先把自己从慌里带出来",
        topic_title="没人能立刻搭把手的时候，先把自己从慌里带出来",
        topic_angle="从成年人想找人倾诉、想向外求助，却发现别人也各自承压切入。",
        draft_title="没人能立刻搭把手的时候，先把自己从慌里带出来",
        draft_body_markdown=(
            "先把眼前最要紧的一件事放稳，心里就有了顺序。\n\n"
            "别急着等谁来救场，把自己的力气一点点接回来。\n\n"
            "很多人不是不想开口，只是一回头，周围每个人手里都压着自己的事。"
        ),
    )

    assert any(anchor in assets["cover_copy"] for anchor in ("力气", "主心骨", "一件小事", "下一步", "落点"))
    assert assets["social_teaser"] == "先把眼前最要紧的一件事放稳，心里就有了顺序。主心骨回来以后，很多事就有了下一步。"
    assert "消息框开了又关" not in assets["social_teaser"]


def test_build_local_publish_package_fallback_uses_shared_burden_self_reliance_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="没人能立刻搭把手的时候，先把自己从慌里带出来",
        title_options=["没人能立刻搭把手的时候，先把自己从慌里带出来"],
        cover_copy="一时等不到人搭把手，也能先把自己安顿住。",
        social_teaser="有些夜里，你也想找个人说说。可一回头，大家也都在各自扛事。先把这一晚过稳，把自己安顿好，心里的乱会先退一点。",
        social_teaser_options=["有些夜里，你也想找个人说说。可一回头，大家也都在各自扛事。先把这一晚过稳，把自己安顿好，心里的乱会先退一点。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="没人能立刻搭把手的时候，先把自己从慌里带出来",
        draft_body_markdown=(
            "你不是不想开口，只是一回头，发现每个人都在各自扛事。\n\n"
            "先把情绪放稳，把今天接过去。\n\n"
            "等你把呼吸稳下来、把顺序理出来，这一晚就没有那么难过了。"
        ),
        assets=assets,
    )

    assert any(anchor in package["publish_lead"] for anchor in ("开口", "主心骨", "一小步", "一件小事", "判断"))
    assert any(anchor in package["abstract"] for anchor in ("力气", "主心骨", "往前走", "分担", "求助", "亮", "站稳"))
    assert any(any(anchor in item for anchor in ("力气", "主心骨", "一件小事", "方向")) for item in package["intro_options"])


def test_build_local_publish_package_fallback_self_reliance_generic_mode_uses_distinct_packaging() -> None:
    assets = SimpleNamespace(
        recommended_title="扛事久了的人，最后都要学会把自己慢慢接回来",
        title_options=["扛事久了的人，最后都要学会把自己慢慢接回来"],
        cover_copy="先把顺序理出来，这一晚就不会一直乱着。",
        social_teaser="事情一下撞到眼前、四周都腾不出空的时候，最先冒出来的往往是慌。先把顺序理出来，心就会慢慢稳一点。",
        social_teaser_options=["事情一下撞到眼前、四周都腾不出空的时候，最先冒出来的往往是慌。先把顺序理出来，心就会慢慢稳一点。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="扛事久了的人，最后都要学会把自己慢慢接回来",
        draft_body_markdown=(
            "事情一下撞到眼前、四周都腾不出空的时候，最先冒出来的往往是慌。\n\n"
            "想开口的那一秒，其实最难。\n\n"
            "先让自己缓下来，把散掉的力气一点点收回来。\n\n"
            "先把这一晚过稳，明天的事再一件件处理。"
        ),
        assets=assets,
    )

    assert any(anchor in package["publish_lead"] for anchor in ("力气", "主心骨", "一件小事", "今天这一点光"))
    assert any(anchor in package["abstract"] for anchor in ("下一步", "有了光", "方向", "路就会慢慢亮"))
    for stale in ("硬撑", "硬熬", "慌张"):
        assert stale not in package["publish_lead"]
        assert stale not in package["abstract"]
    assert package["publish_lead"] != assets.social_teaser
    assert package["abstract"] != assets.social_teaser
    assert any("把力气慢慢收回来" in item or "力气" in item for item in package["intro_options"])


def test_build_local_tracked_article_topic_fallback_uses_distinct_self_reliance_title() -> None:
    topic = workbench._build_local_tracked_article_topic_fallback(
        {
            "article_title": "即使没有帮助，也要学会自救自渡",
            "summary": "文章从想找人倾诉却发现身边人也自顾不暇切入，写成年人在低谷里怎样逐渐把依靠收回自己身上。",
            "body_markdown": (
                "只有向内求，才能自我疗愈，生生不息。"
                "只有靠自己，你才能有所顿悟、有所收获、有所改变。"
                "即使没有帮助，也不会孤立无援，而是能够自救自渡。"
            ),
            "structure_notes": "先写想倾诉却发现别人也各自承压的现实处境，中段再拆为什么外求未必总能接住人，结尾回到向内稳住、自救自渡和慢慢把自己托起来。",
        }
    )

    assert any(anchor in topic["title"] for anchor in ("力气", "主心骨", "自己的光"))
    assert topic["title"] != "即使没有帮助，也要学会自救自渡"
    assert "参考文章里的现实触发点" in topic["angle"]
    assert "具体判断、行动或选择" in topic["angle"]


def test_trust_boundary_structure_mode_and_local_topic_keep_trust_theme() -> None:
    body = (
        "信任很贵，请别辜负\n\n"
        "从前，他晚归，你不会多想；他手机响，你不会多看一眼。\n\n"
        "可是后来，一句谎言，一次隐瞒，那个叫信任的东西，就裂了一道缝。\n\n"
        "你再想说服自己没关系，心里却已经有了疙瘩。\n\n"
        "他不查你手机，是因为相信你；他不追问行踪，是因为不想给你压力。\n\n"
        "别把他的信任当成你任性的资本，更别辜负这份赤诚。"
    )

    assert (
        workbench.resolve_tracked_article_structure_mode(
            body_markdown=body,
            summary="文章讨论信任被隐瞒和谎言划出裂缝后，关系怎样靠坦诚和说到做到重新获得心安。",
            structure_notes="开头写放心，中段写信任裂缝，结尾回到坦诚、赤诚和守护。",
        )
        == "trust_boundary"
    )

    topic = workbench._build_local_tracked_article_topic_fallback(
        {
            "source_type": "tracked_article",
            "article_title": "信任很贵，请别辜负",
            "body_markdown": body,
            "summary": "文章讨论信任、隐瞒、谎言和坦诚。",
            "structure_notes": "开头写放心，中段写信任裂缝，结尾回到坦诚。",
        }
    )
    combined = f"{topic['title']} {topic['angle']}"

    assert topic["title"] == "愿意放心信你的人，别让他在细节里发慌"
    assert "信任" in combined
    assert "坦诚" in combined or "说到做到" in combined
    for forbidden in ("点赞", "评论", "读懂", "回消息", "没时间", "放下过去", "执念", "不是解释", "而是坦诚"):
        assert forbidden not in combined


def test_build_local_tracked_article_draft_fallback_trust_boundary_overrides_wrong_strategy_hint() -> None:
    body = (
        "从前，他晚归，你不会多想；他手机响，你不会多看一眼。\n\n"
        "可是后来，一句谎言，一次隐瞒，那个叫信任的东西，就裂了一道缝。\n\n"
        "他不查你手机，是因为相信你；他不追问行踪，是因为不想给你压力。\n\n"
        "别把他的信任当成你任性的资本，更别辜负这份赤诚。"
    )

    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "source_type": "tracked_article",
            "topic_title": "愿意信你的人，最需要被你好好守住",
            "topic_angle": "从一次隐瞒让信任裂开切入，写坦诚和说到做到怎样让关系重新有心安。",
            "reference_article_body_markdown": body,
            "strategy_card": {"structure_mode": "emotional_engine_direct"},
            "problem_brief": {
                "theme_axis": "不要写成放下过去或被读懂的关系稿。",
                "core_conflict": "信任被隐瞒划出裂缝以后，关系需要坦诚和交代重新托住。",
            },
        }
    )

    assert title == "愿意信你的人，最需要被你好好守住"
    assert body_markdown.startswith("听见前后两个版本时，手里的筷子会先停一下。")
    assert body_markdown.count("手里的筷子") == 1
    assert "听见两个版本时" not in body_markdown
    assert "信任最贵的地方" in body_markdown
    assert "信任的底气" in body_markdown
    assert "补全另一个故事" in body_markdown
    assert "有句话说得很轻，却很准" not in body_markdown
    assert "主动说一声" in body_markdown
    assert "准时兑现" in body_markdown
    assert len([paragraph for paragraph in body_markdown.split("\n\n") if paragraph.strip()]) >= 10
    for forbidden in ("点赞", "评论", "读懂", "回消息", "放下过去", "执念", "晚归", "手机响", "手机放在桌上", "对方却", "你的人。", "不是在吵架", "不是事情本身", "坦诚不是", "一句谎话、一次遮掩，让原本放心的关系突然松动的那一下"):
        assert forbidden not in body_markdown


def test_local_assets_and_tags_use_trust_boundary_packaging() -> None:
    draft_body = (
        "你愿意相信一个人的时候，其实已经把很重要的心安交了出去。\n\n"
        "信任最贵的地方，是它把自由交给你，也把心安交给你。\n\n"
        "坦诚不是事事报备，也不是把生活过成审问。该交代的时候交代，答应过的事尽量做到。"
    )

    assets = workbench._build_local_assets_fallback(
        project_title="愿意信你的人，最需要被你好好守住",
        topic_title="愿意信你的人，最需要被你好好守住",
        topic_angle="从一次隐瞒让信任裂开切入，写坦诚和说到做到怎样让关系重新有心安。",
        draft_title="愿意信你的人，最需要被你好好守住",
        draft_body_markdown=draft_body,
    )
    tags = workbench._build_local_publish_tags(
        title=str(assets["recommended_title"]),
        body_markdown=draft_body,
        publish_lead=str(assets["social_teaser"]),
        cover_copy=str(assets["cover_copy"]),
    )

    assert assets["cover_copy"] == "信任很贵，别让赤诚输给含糊。"
    assert assets["social_teaser"] == "你愿意相信一个人的时候，其实已经把很重要的心安交了出去。坦诚的分量，是把话说透，也把答应过的事做到。"
    assert "信任与坦诚" in tags


def test_build_local_publish_tags_prefers_scene_specific_labels_for_scene_first_cases() -> None:
    office_tags = workbench._build_local_publish_tags(
        title="散会后才开口，位置就会慢慢往后退",
        body_markdown="周一早会开始前，她站在投影幕布旁。散会以后，她还坐在原位。",
        publish_lead="人都起身了，你还坐在原位，在心里补刚才那句没说出口的话。",
        cover_copy="该在会上说的话，别总留到散会以后。",
    )
    transit_tags = workbench._build_local_publish_tags(
        title="没问出口的那句话，最容易把关系拖远",
        body_markdown="雨刚停，出站口外的摆渡车还没来。玻璃很快蒙起一层白气。",
        publish_lead="雨刚停，出站口外的摆渡车还没来。把那句该问的话留在当场，很多关系就不会绕那么远。",
        cover_copy="把那句真话早点说出口，很多关系就不会绕那么远。",
    )
    household_tags = workbench._build_local_publish_tags(
        title="家里的心事，最怕总被顺到明天",
        body_markdown="夜里回到家，餐桌上的检查单还没收。孩子已经睡了，水壶还是温的。",
        publish_lead="夜里回到家，餐桌上的检查单还没收。把话慢慢说开，家里的心事才不会一直压在沉默里。",
        cover_copy="家里的心事，还是要在来得及的时候慢慢说开。",
    )

    assert "职场表达" in office_tags
    assert "关系沟通" in transit_tags
    assert "家庭沟通" in household_tags


def test_build_local_publish_tags_prefers_responsibility_labels_for_responsibility_shelter_case() -> None:
    tags = workbench._build_local_publish_tags(
        title="肩上有责任的人，心里也要留一盏灯",
        body_markdown=(
            "请假申请还没点下去，你已经先把这个月的工作、父母和孩子的事排了一遍。\n\n"
            "账单被压在杯子下面，纸角微微卷起。父母少一点担心，孩子多一点底气，一家人的安稳，就是生活给你的回响。"
        ),
        publish_lead="家里一有事，你总是先把顺序理清的那个人。",
        cover_copy="肩上有责任，心里也要留一盏灯。",
    )

    assert tags == ["家庭责任", "家里踏实", "中年责任"]
    assert "职场表达" not in tags
    assert "开口时机" not in tags


def test_local_assets_and_publish_package_drop_strategy_placeholder_for_trust_boundary() -> None:
    draft_body = (
        "先抓一个具体入口，再把被点破的误判和回正落点收回来。\n\n"
        "从前对方晚一点回家，你不会立刻多想；手机放在桌上亮了一下，你也不会急着看。\n\n"
        "后来让人难受的，也许不是某件事本身有多大。是一句谎话、一次遮掩，让你突然发现：原来自己一直相信的地方，也会松动。\n\n"
        "信任最贵的地方，是它把自由交给你，也把心安交给你。\n\n"
        "坦诚不是事事报备，也不是把生活过成审问。该交代的时候交代，答应过的事尽量做到。"
    )

    assets_payload = workbench._build_local_assets_fallback(
        project_title="信任一旦裂开，最该补上的不是解释，而是坦诚",
        topic_title="信任一旦裂开，最该补上的不是解释，而是坦诚",
        topic_angle="从一次隐瞒让信任裂开切入，写坦诚和说到做到怎样让关系重新有心安。",
        draft_title="信任一旦裂开，最该补上的不是解释，而是坦诚",
        draft_body_markdown=draft_body,
    )
    assets = workbench.AssetItem(
        project_slug="trust-boundary-project",
        draft_version=1,
        version=1,
        title_options=list(assets_payload["title_options"]),
        recommended_title=str(assets_payload["recommended_title"]),
        cover_prompt=str(assets_payload["cover_prompt"]),
        cover_copy=str(assets_payload["cover_copy"]),
        social_teaser=str(assets_payload["social_teaser"]),
        social_teaser_options=list(assets_payload["social_teaser_options"]),
        cover_image_path="",
        cover_image_url="",
        created_at="2026-07-12T00:00:00Z",
    )
    package = workbench._build_local_publish_package_fallback(
        draft_title="信任一旦裂开，最该补上的不是解释，而是坦诚",
        draft_body_markdown=draft_body,
        assets=assets,
    )

    combined = "\n".join(
        [
            str(assets_payload["social_teaser"]),
            str(package["publish_lead"]),
            str(package["abstract"]),
            *[str(item) for item in package["intro_options"]],
        ]
    )
    assert "先抓一个具体入口" not in combined
    assert "被点破的误判" not in combined
    assert assets_payload["recommended_title"] == "那句没说清的话，后来要认真补回来"
    assert all("不是解释" not in str(title) and "而是坦诚" not in str(title) for title in assets_payload["title_options"])
    assert "信任" in combined
    assert "坦诚" in combined or "说到做到" in combined
    assert str(package["publish_lead"]) == "听见前后两个版本时，手里的筷子会先停一下。那一下不一定会让人立刻发火，却会让你忽然明白：原来心里那份放心，已经没有刚开始那么稳了。"
    assert str(package["abstract"]) == "信任最怕的，从来不是一句话没说漂亮，而是明明可以坦诚，却还是拿含糊去碰别人的真心。真正留住心安的，从来都是坦诚和说到做到。"
    assert str(package["abstract"]) != str(assets_payload["social_teaser"])
    assert "信任最怕的，不是争吵，是心里那一下忽然不敢再全信了。" in [str(item) for item in package["intro_options"]]


def test_local_publish_package_uses_distinct_trust_boundary_packaging() -> None:
    draft_title, draft_body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "source_type": "tracked_article",
            "topic_title": "愿意信你的人，最需要被你好好守住",
            "topic_angle": "从一次隐瞒让信任裂开切入，写坦诚和说到做到怎样让关系重新有心安。",
            "reference_article_body_markdown": (
                "从前，他晚归，你不会多想；他手机响，你不会多看一眼。"
                "可是后来，一句谎言，一次隐瞒，那个叫信任的东西，就裂了一道缝。"
                "别把他的信任当成你任性的资本，更别辜负这份赤诚。"
            ),
            "strategy_card": {"structure_mode": "trust_boundary"},
            "problem_brief": {
                "theme_axis": "主线是信任的代价和边界。",
                "core_conflict": "一句谎、一点隐瞒，会让原本笃定的人开始害怕。",
            },
        }
    )
    assets_payload = workbench._build_local_assets_fallback(
        project_title=draft_title,
        topic_title="愿意信你的人，最需要被你好好守住",
        topic_angle="从一次隐瞒让信任裂开切入，写坦诚和说到做到怎样让关系重新有心安。",
        draft_title=draft_title,
        draft_body_markdown=draft_body_markdown,
    )
    assets = workbench.AssetItem(
        project_slug="trust-boundary-package",
        draft_version=1,
        version=1,
        title_options=list(assets_payload["title_options"]),
        recommended_title=str(assets_payload["recommended_title"]),
        cover_prompt=str(assets_payload["cover_prompt"]),
        cover_copy=str(assets_payload["cover_copy"]),
        social_teaser=str(assets_payload["social_teaser"]),
        social_teaser_options=list(assets_payload["social_teaser_options"]),
        cover_image_path="",
        cover_image_url="",
        created_at="2026-07-14T00:00:00Z",
    )
    package = workbench._build_local_publish_package_fallback(
        draft_title=draft_title,
        draft_body_markdown=draft_body_markdown,
        assets=assets,
    )

    assert package["publish_title"] == "愿意信你的人，最需要被你好好守住"
    assert str(package["publish_lead"]).startswith("听见前后两个版本时，手里的筷子会先停一下。")
    assert "原来心里那份放心，已经没有刚开始那么稳了" in str(package["publish_lead"])
    assert str(package["abstract"]).startswith("信任最怕的，从来不是一句话没说漂亮")
    assert "坦诚和说到做到" in str(package["abstract"])
    assert str(package["abstract"]) != str(package["publish_lead"])
    assert str(package["abstract"]) != str(assets.social_teaser)

def test_build_local_tracked_article_draft_fallback_response_priority_avoids_theme_axis_strategy_leak() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "真正在意你的人，会读懂你的言外之意",
            "outline": {
                "hook": "一句轻描淡写的话，到底有没有被听懂、有没有人肯继续多问一句。",
                "outline_body": (
                    "### 1. 写为什么轻互动很多，人却还是会悬着；也写真正的关心，往往藏在一句追问、一次补问和被认真听懂的那一下。\n"
                    "### 2. 越把热闹互动误认成关心，越容易忽略真正让人踏实的，往往只是有人愿意停下来读懂你没说完的话。\n"
                    "### 3. 如果总靠你替对方找理由，那份失望就会在一次次等待里慢慢长大。\n"
                    "### 4. 看清顺序以后，最重要的不是再去追问，而是把时间和心力留给真正值得的人。"
                ),
            },
            "strategy_card": {
                "structure_mode": "response_priority",
                "positive_direction": "结尾回到被理解、被记得和真正被放在心上的安稳感，不要只停在比较谁更在乎。",
            },
            "problem_brief": {
                "theme_axis": "主线是轻互动为什么不等于真正的关心；真正让人踏实的，常常是有人愿意停下来读懂你、把你那句没说完的话接下去。",
                "core_conflict": "很多时候真正让人踏实的，不是互动不断，而是有人能从你轻描淡写的话里听出分量，并愿意把那句话接下去。",
            },
        }
    )

    assert title == "真正在意你的人，会读懂你的言外之意"
    assert "主线是" not in body_markdown
    assert body_markdown.startswith("很多回应都会路过你，难得的是有人真的停下来。")
    assert "他不会急着把话题带开，也不会只留一个表情就算回应。他只是多问一句：你是不是还有话没说完。" in body_markdown
    assert "真正的在意，更像一种注意力。" in body_markdown
    assert "被这样接住过一次，人就会知道什么样的关系值得珍惜。" in body_markdown
    assert "等电梯的半分钟，够不够回一句话？其实够的。" not in body_markdown
    assert "时间给了谁，心就会慢慢偏向谁。" not in body_markdown
    paragraphs = [part for part in body_markdown.split("\n\n") if part.strip()]
    assert len(paragraphs) <= 8
    assert max(len(part) for part in paragraphs) <= 150


def test_build_local_tracked_article_draft_fallback_response_priority_uses_reference_comment_scene_opening() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "真正在意你的人，会读懂你的言外之意",
            "article_title": "真正关心你的人，会从一句轻描淡写里听出分量",
            "reference_article_body_markdown": (
                "朋友圈里，是给你点赞的人更在意你，还是给你评论的人更在意你？"
                "我有个好友，曾经在朋友圈发了一张落日余晖的照片，配文是：今天的夕阳真美，终于下班了。"
                "底下一排整齐的点赞，唯独一条评论显得格格不入。她问：是不是项目又出岔子了？我随时在，想吐槽给我打电话。"
            ),
            "outline": {
                "hook": "一句轻描淡写的话，到底有没有被听懂、有没有人肯继续多问一句。",
                "outline_body": (
                    "### 1. 写为什么轻互动很多，人却还是会悬着。\n"
                    "### 2. 真正的关心，往往藏在一句追问里。\n"
                    "### 3. 被这样接住过一次，人才会记住。"
                ),
            },
            "strategy_card": {
                "structure_mode": "response_priority",
                "positive_direction": "结尾回到被理解、被记得和真正被放在心上的安稳感。",
            },
            "problem_brief": {
                "theme_axis": "主线是轻互动为什么不等于真正的关心。",
                "core_conflict": "让人踏实的，常常是有人愿意停下来读懂你、把你那句没说完的话接下去。",
            },
        }
    )

    assert title == "真正在意你的人，会读懂你的言外之意"
    assert body_markdown.startswith(("朋友圈那张晚霞发出去以后，最后留在心里的，常常是那句认真追问。", "你发了一张晚霞照，本来只想轻轻带过一天。可真正把你放在心上的人，还是会顺着那句配文多看一眼。"))
    assert "很多回应都会路过你，难得的是有人真的停下来。" not in body_markdown.split("\n\n")[0]
    assert "是不是项目又出岔子了？" in body_markdown


def test_build_local_assets_fallback_uses_mode_shaped_copy_for_response_priority_payload() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="真正在意你的人，会读懂你的言外之意",
        topic_title="真正在意你的人，会读懂你的言外之意",
        topic_angle="从轻互动为什么不等于真正的在乎切入。",
        draft_title="真正在意你的人，会读懂你的言外之意",
        draft_body_markdown=(
            "一句轻描淡写的话，到底有没有被听懂、有没有人肯继续多问一句。\n\n"
            "先看清谁只是路过一下，谁真的停下来听你说。\n\n"
            "一句轻描淡写的话，有没有人继续接下去，差别其实很大。"
        ),
    )

    assert assets["cover_copy"] == "一句轻描淡写的话，到底有没有被听懂、有没有人肯继续多问一句。"
    assert (
        assets["social_teaser"]
        == "一句轻描淡写的话，到底有没有被听懂、有没有人肯继续多问一句。那句顺着情绪接下去的话，往往比热闹互动更让人踏实。"
    )


def test_build_local_assets_fallback_uses_followup_variant_copy_for_response_priority_payload() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="你轻轻带过的话，真正在意的人会再问一句",
        topic_title="你轻轻带过的话，真正在意的人会再问一句",
        topic_angle="从点赞、评论和一句我没事背后的分量差别切入，写为什么轻互动很多，人却还是会悬着；也写真正的关心，往往藏在一句追问、一次补问和被认真听懂的那一下。",
        draft_title="你轻轻带过的话，真正在意的人会再问一句",
        draft_body_markdown=(
            "一张晚霞照发出去，真正让人心里一松的，往往不是那排点赞。\n\n"
            "他不会急着把话题带开，也不会只留一个表情就算回应。他只是多问一句：你是不是还有话没说完。\n\n"
            "被这样接住过一次，人就会知道什么样的关系值得珍惜。以后再看热闹不热闹、互动多不多，心里自然会分得清：谁只是路过，谁是真的把你放在心上。"
        ),
    )

    assert assets["recommended_title"] == "你轻轻带过的话，真正在意的人会再问一句"
    assert assets["cover_copy"] == "你轻轻带过的话，有人真的听进去了。"
    assert assets["social_teaser"] == "那张晚霞发出去以后，最暖的不是那排点赞，是那句看懂你疲惫的追问。"
    assert "晚霞余晖" in str(assets["cover_prompt"])
    assert "不要聊天界面" in str(assets["cover_prompt"])


def test_build_local_tracked_article_draft_fallback_response_priority_uses_time_priority_variation() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "愿意把时间留给你的人，才是真的把你放在心上",
            "reference_article_body_markdown": "红灯30秒，我喝了一口水，拍了张照片，回了条消息。忙不是借口，没时间也不是理由。一个人的时间在哪儿，他的心就在哪儿。",
            "outline": {
                "hook": "一句轻描淡写的话，到底有没有被听懂、有没有人肯继续多问一句。",
                "outline_body": "1. 忙不是结尾\n2. 时间给了谁，心里会有答案\n3. 愿意把回应补回来的人才在意",
            },
            "strategy_card": {"structure_mode": "response_priority"},
        }
    )

    assert title == "愿意把时间留给你的人，才是真的把你放在心上"
    assert body_markdown.startswith(
        (
            "他说自己很忙那一刻，你不是不理解，只是忽然明白了，时间留给谁，心里其实早就有答案。",
            "红灯的三十秒都能做很多事，所以后来你也慢慢懂了，所谓没时间，多半不是一点空都挤不出来。",
        )
    )
    assert "红灯的三十秒、排队的几分钟、到家换鞋前那会儿" in body_markdown
    assert "你一次次替对方解释" in body_markdown
    assert "一张晚霞照发出去" not in body_markdown


def test_build_local_tracked_article_draft_fallback_response_priority_time_priority_skips_summary_like_opening() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "愿意把时间分给你的人，心里早就给你留了位置",
            "topic_angle": "从“没时间”这句话为什么常常说的不是日程，而是顺序切入。",
            "reference_article_body_markdown": "红灯30秒，我喝了一口水，拍了张照片，回了条消息。一个人的时间在哪儿，他的心就在哪儿。",
            "outline": {
                "hook": "很多人不是在等一句秒回，而是在等那句后来有没有真的落下来。",
                "outline_body": "1. 忙不是问题，悬着才是\n2. 时间给了谁，心里会有答案\n3. 真正的安心，是后来没有被忘掉",
            },
            "strategy_card": {"structure_mode": "response_priority"},
            "problem_brief": {
                "theme_axis": "消息、评论或碎片时间被给出去的那一下，谁真正被排在了前面。",
                "core_conflict": "很多关系后来让人心里发空，不在于大家都忙，而在于你总是等着一句迟迟没落下来的回应。",
            },
        }
    )

    assert title == "愿意把时间分给你的人，心里早就给你留了位置"
    assert not body_markdown.startswith("消息、评论或碎片时间被给出去的那一下，谁真正被排在了前面。")
    assert body_markdown.startswith("他说自己很忙那一刻，你不是不理解，只是忽然明白了，时间留给谁，心里其实早就有答案。")


def test_build_local_assets_fallback_response_priority_uses_time_priority_copy() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="愿意把时间留给你的人，才是真的把你放在心上",
        topic_title="愿意把时间留给你的人，才是真的把你放在心上",
        topic_angle="从忙不是结尾、时间给了谁切入。",
        draft_title="愿意把时间留给你的人，才是真的把你放在心上",
        draft_body_markdown=(
            "他说自己很忙那一刻，你其实能理解。只是那句“回头再说”一直没落下来，心里还是会轻轻沉一下。\n\n"
            "红灯的三十秒、排队的几分钟、到家换鞋前那会儿，其实都够回一句。\n\n"
            "一个人把时间给谁，往往不是嘴上说出来的，是那些细小空当里先想到谁。"
        ),
    )

    assert assets["cover_copy"] == "忙完以后还记得回来找你的人，心里一直给你留着位置。"
    assert assets["social_teaser"] == "他说自己很忙那一刻，你其实能理解。真正让人安心的，是他忙完以后，还记得回来找你。"


def test_build_local_publish_package_fallback_response_priority_uses_time_priority_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="愿意把时间留给你的人，才是真的把你放在心上",
        title_options=["愿意把时间留给你的人，才是真的把你放在心上"],
        cover_copy="真正让人心安的，不是快，是后来没有被忘掉。",
        social_teaser="他说自己很忙那一刻，你其实能理解。忙不是问题，忙完还记得回来接话，人才会觉得自己一直被放在心上。",
        social_teaser_options=["他说自己很忙那一刻，你其实能理解。忙不是问题，忙完还记得回来接话，人才会觉得自己一直被放在心上。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="愿意把时间留给你的人，才是真的把你放在心上",
        draft_body_markdown=(
            "他说自己很忙那一刻，你其实能理解。只是那句“回头再说”一直没落下来，心里还是会轻轻沉一下。\n\n"
            "红灯的三十秒、排队的几分钟、到家换鞋前那会儿，其实都够回一句。\n\n"
            "一个人把时间给谁，往往不是嘴上说出来的，是那些细小空当里先想到谁。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "你当然知道大家都忙。可真把你放在心上的人，不会让一句话一直悬着。哪怕当下顾不上，他也会在忙完以后回来找你，把回应补上。"
    assert package["abstract"] == "忙不是问题，最怕的是你把在意递过去，后来像没落到实处。不是非要立刻回，只要那句“忙完找你”最后真的补回来了，心里悬着的那一下就会慢慢放下。"
    assert package["intro_options"][:2] == [
        "你当然知道大家都忙。可真把你放在心上的人，不会让一句话一直悬着。哪怕当下顾不上，他也会在忙完以后回来找你，把回应补上。",
        assets.social_teaser,
    ]


def test_build_local_publish_package_fallback_response_priority_uses_followup_scene_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="你轻轻带过的话，真正在意的人会再问一句",
        title_options=["你轻轻带过的话，真正在意的人会再问一句"],
        cover_copy="你轻轻带过的话，有人真的听进去了。",
        social_teaser="那条晚霞发出去以后，最暖的不是那排点赞，是有人从“终于下班了”里听出了你的累。",
        social_teaser_options=["那条晚霞发出去以后，最暖的不是那排点赞，是有人从“终于下班了”里听出了你的累。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="你轻轻带过的话，真正在意的人会再问一句",
        draft_body_markdown=(
            "你发了一张晚霞照，本来只想轻轻带过一天。\n\n"
            "别人顺手点了赞，只有一个人问你：是不是项目又出岔子了？\n\n"
            "被这样追问一次，人就会知道什么叫被放在心上。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "那条朋友圈发出去以后，别人看见的是晚霞，真正在意你的人，看见的却是你那句轻描淡写后面的疲惫。他不会只留个赞就走，而是会顺着那点情绪，多问一句。"
    assert package["abstract"] == "一条朋友圈下面热闹不难，难的是有人看懂你那句轻描淡写，追着问一句“是不是又扛着没说”。被这样惦记一次，人心里那根绷着的弦会先松一点。"
    assert package["intro_options"][:2] == [
        "那条朋友圈发出去以后，别人看见的是晚霞，真正在意你的人，看见的却是你那句轻描淡写后面的疲惫。他不会只留个赞就走，而是会顺着那点情绪，多问一句。",
        assets.social_teaser,
    ]


def test_build_local_assets_fallback_response_priority_title_beats_self_reliance_overlap() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="一个人的时间在哪儿，他的心就在哪儿",
        topic_title="一个人的时间在哪儿，他的心就在哪儿",
        topic_angle="从时间分配和回应动作怎样显出真实在乎程度切入。",
        draft_title="一个人的时间在哪儿，他的心就在哪儿",
        draft_body_markdown=(
            "消息、评论或碎片时间被给出去的那一下，谁真正被排在了前面。\n\n"
            "同样一条消息发出去，有人看过就算了，也有人会停下来，再问你一句“你是不是还没说完”。\n\n"
            "总替对方解释忙、累、没看见，心里的失落就会一点点往下压。热闹还在，不代表在乎也在。"
        ),
    )

    assert assets["cover_copy"] == "消息、评论或碎片时间被给出去的那一下，谁真正被排在了前面。"
    assert (
        assets["social_teaser"]
        == "消息、评论或碎片时间被给出去的那一下，谁真正被排在了前面。那句顺着情绪接下去的话，往往比热闹互动更让人踏实。"
    )


def test_build_local_tracked_article_draft_fallback_inner_settlement_uses_mode_voice() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "article_title": "此心安处是吾乡",
            "topic_title": "心安这件事，比什么都重要",
            "topic_angle": "从心为什么一直悬着，写一个人怎样把自己慢慢安顿回当下。",
            "reference_article_body_markdown": "心若不安，到哪里都是流浪。此心安处是吾乡。真正的心安，是于一餐一饮中品味生活。",
            "outline": {
                "hook": "屋里安静下来以后，你才听见，心里那点一直没落地的事，原来比外面更吵。",
                "outline_body": (
                    "### 1. 很多过不去的坎，后来回头看，难的往往不是事情本身，而是那颗一直没肯放下的心。\n"
                    "### 2. 越想一次把一切想透、想稳、想明白，人越容易把自己困在反复拉扯里。\n"
                    "### 3. 心里那口气一直拧着，外面的风吹得再小，也会让人觉得累。\n"
                    "### 4. 等你肯把心慢慢放平，很多路自然会顺着脚下展开。"
                ),
            },
            "strategy_card": {
                "structure_mode": "inner_settlement",
                "positive_direction": "结尾回到心落回当下、一餐一饭和稳定生活，不要写成自救苦撑。",
            },
            "problem_brief": {
                "theme_axis": "主线是一个人怎样把悬着的心安顿回当下。",
                "core_conflict": "心一直悬着时，外面一点风声都容易让人疲惫。",
            },
        }
    )

    assert title == "心安这件事，比什么都重要"
    assert "先把心里最拧的那一处慢慢松开。" not in body_markdown
    assert body_markdown.startswith(
        (
            "人到后来才明白，真正要找的归宿，不一定在远方，常常先在心里。",
            "外面的风景再热闹，心里若没有归处，人还是会觉得漂。",
            "心总往外悬着的时候，再热闹的地方也像借住。",
        )
    )
    assert "很多时候，真正让人累的，不一定是事情有多难，而是心里一直没有一个能安顿下来的地方。" in body_markdown
    assert any(
        fragment in body_markdown
        for fragment in (
            "你慢慢不再把自己交给外面的起伏，而是把重心一点点收回自己身上。",
            "你终于不再把自己交给外面的起伏，而是把重心一点点收回自己身上。",
        )
    )
    assert "所谓“此心安处”，未必是从此没有风浪，而是风浪还在，你已经不会被每一阵风都轻易带走。" in body_markdown
    assert "把那颗总往外追的心轻轻带回来，和今天相处，和自己和解。" in body_markdown
    assert "一呼一吸" not in body_markdown
    assert len([paragraph for paragraph in body_markdown.split("\n\n") if paragraph.strip()]) <= 7


def test_build_local_tracked_article_draft_fallback_inner_settlement_uses_reference_stillness_opening() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "article_title": "此心安处是吾乡",
            "topic_title": "心安这件事，比什么都重要",
            "reference_article_body_markdown": "心若不安，到哪里都是流浪。此心安处是吾乡。真正的心安，是于一餐一饮中品味生活。",
            "outline": {
                "hook": "屋里安静下来以后，你才听见，心里那点一直没落地的事，原来比外面更吵。",
                "outline_body": "1. 心为什么一直悬着\n2. 越急着想明白越难安稳\n3. 心回到今天以后，很多事会慢慢松开",
            },
            "strategy_card": {"structure_mode": "inner_settlement"},
        }
    )

    assert title == "心安这件事，比什么都重要"
    assert body_markdown.startswith(
        (
            "人到后来才明白，真正要找的归宿，不一定在远方，常常先在心里。",
            "外面的风景再热闹，心里若没有归处，人还是会觉得漂。",
            "心总往外悬着的时候，再热闹的地方也像借住。",
        )
    )
    assert "屋里安静下来以后，你才听见，心里那点一直没落地的事，原来比外面更吵。" not in body_markdown.split("\n\n")[0]


def test_build_local_assets_fallback_inner_settlement_uses_homecoming_cover_copy() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="心安这件事，比什么都重要",
        topic_title="心安这件事，比什么都重要",
        topic_angle="从心为什么一直悬着，写一个人怎样把自己慢慢安顿回当下。",
        draft_title="心安这件事，比什么都重要",
        draft_body_markdown=(
            "人到后来才明白，真正要找的归宿，不一定在远方，常常先在心里。\n\n"
            "很多时候，真正让人累的，不一定是事情有多难，而是心里一直没有一个能安顿下来的地方。\n\n"
            "所谓“此心安处”，未必是从此没有风浪，而是风浪还在，你已经不会被每一阵风都轻易带走。心里有了归处，脚下的路也会跟着慢慢稳下来。"
        ),
    )

    assert assets["cover_copy"] == "心里有了归处，日子就不会一直飘着。"
    assert (
        assets["social_teaser"]
        == "人到后来才明白，真正要找的归宿，不一定在远方，常常先在心里。心里有了归处，外面的风再大，也不至于把你轻易吹乱。"
    )


def test_build_local_assets_fallback_inner_settlement_title_beats_self_reliance_overlap() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="心安这件事，比什么都重要",
        topic_title="心安这件事，比什么都重要",
        topic_angle="从心为什么一直悬着，写一个人怎样把自己慢慢安顿回当下。",
        draft_title="心安这件事，比什么都重要",
        draft_body_markdown=(
            "屋里安静下来以后，你才听见，心里那点一直没落地的事，原来比外面更吵。\n\n"
            "白天忙的时候还顾不上。一安静下来，那句没接住的话、那个没想明白的决定，就又自己浮上来了。\n\n"
            "把水烧开，把饭吃完，人就已经在慢慢往安稳处走了。"
        ),
    )

    assert assets["cover_copy"] == "心慢慢落回今天，日子就会重新有安稳感。"
    assert assets["social_teaser"] == "屋里安静下来以后，你才听见，心里那点一直没落地的事，原来比外面更吵。先把今天过回今天，心才会慢慢有地方落下来。"
    assert "别让自己一直悬着" not in assets["social_teaser"]


def test_build_local_publish_package_fallback_inner_settlement_uses_mode_lead_and_abstract() -> None:
    assets = SimpleNamespace(
        recommended_title="心安这件事，比什么都重要",
        title_options=["心安这件事，比什么都重要"],
        cover_copy="心慢慢落回今天，日子就会重新有安稳感。",
        social_teaser="屋里安静下来以后，你才听见，心里那点一直没落地的事，原来比外面更吵。先把今天过回今天，心才会慢慢有地方落下来。",
        social_teaser_options=["屋里安静下来以后，你才听见，心里那点一直没落地的事，原来比外面更吵。先把今天过回今天，心才会慢慢有地方落下来。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="心安这件事，比什么都重要",
        draft_body_markdown=(
            "心一直悬着的时候，连很普通的一天，也像总差一点没真正落地。\n\n"
            "把水烧开，把饭吃完，把明天要穿的衣服放好，人就已经在慢慢往安稳处走了。\n\n"
            "很多想不通的事，不必都在今晚想明白。"
        ),
        assets=assets,
    )

    assert any(fragment in package["publish_lead"] for fragment in ("心里那点事", "心一直悬着", "心安"))
    assert any(fragment in package["publish_lead"] for fragment in ("今晚想明白", "今天", "饭吃好"))
    assert any(fragment in package["abstract"] for fragment in ("把水烧开", "把灯关好", "心先落回今天"))
    assert any(fragment in package["abstract"] for fragment in ("想不通", "没那么吵", "日常"))
    assert package["intro_options"][0] == package["publish_lead"]
    assert "先把今天过回今天，心才会慢慢有地方落下来。" in package["intro_options"]


def test_build_local_publish_package_fallback_inner_settlement_uses_homecoming_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="心安这件事，比什么都重要",
        title_options=["心安这件事，比什么都重要"],
        cover_copy="心里有了归处，日子就不会一直飘着。",
        social_teaser="人到后来才明白，真正要找的归宿，不一定在远方，常常先在心里。心里有了归处，外面的风再大，也不至于把你轻易吹乱。",
        social_teaser_options=["人到后来才明白，真正要找的归宿，不一定在远方，常常先在心里。心里有了归处，外面的风再大，也不至于把你轻易吹乱。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="心安这件事，比什么都重要",
        draft_body_markdown=(
            "人到后来才明白，真正要找的归宿，不一定在远方，常常先在心里。\n\n"
            "后来才会慢慢懂得，心安不是把世界按停，也不是让所有事情都照着你的期待发生。它更像是你终于不再把自己交给外面的起伏，而是把重心一点点收回自己身上。\n\n"
            "所谓“此心安处”，未必是从此没有风浪，而是风浪还在，你已经不会被每一阵风都轻易带走。心里有了归处，脚下的路也会跟着慢慢稳下来。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "忙完一天回到家，先把鞋摆好，给自己倒杯水，窗外再吵也由它去。人真正安稳下来的时候，往往不是所有事都有了答案，而是眼前这个普通的日子，终于又能好好过下去。"
    assert package["abstract"] == "心安不是把生活按停，是还能把一顿饭吃热，把一句话说慢，把今天过清楚。外面的风停不停由不得你，屋里的灯，却可以由你亲手打开。"
    assert "把鞋摆好，给自己倒杯水，普通的一天也能重新落稳。" in package["intro_options"]


def test_build_local_tracked_article_draft_fallback_inner_settlement_uses_future_release_variation() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "article_title": "今夜，把心放平，把事看淡",
            "topic_title": "真正的心安，是不再提前替明天发愁",
            "reference_article_body_markdown": "已经过去的事儿，既然改变不了，不如轻轻放下温柔落锁；还没发生的事儿，反正预测不到，不如不骄不躁静待花开。",
            "outline": {
                "hook": "心一直悬着的时候，连很普通的一天，也像总差一点没真正落地。",
                "outline_body": "1. 心为什么一直绷着\n2. 人为什么总替未来预支情绪\n3. 把今天过回今天，心就会慢慢安静",
            },
            "strategy_card": {"structure_mode": "inner_settlement"},
        }
    )

    assert title == "真正的心安，是不再提前替明天发愁"
    assert "已经过去的事，今天先别再一遍遍回头想；还没发生的事，也不必提前在心里演很多遍。" in body_markdown
    assert "很多答案不会今晚就来，但心会先慢慢安静下来。" in body_markdown


def test_build_local_publish_package_fallback_inner_settlement_uses_future_release_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="真正的心安，是不再提前替明天发愁",
        title_options=["真正的心安，是不再提前替明天发愁"],
        cover_copy="心慢慢落回今天，日子就会重新有安稳感。",
        social_teaser="心一直悬着的时候，连很普通的一天，也像总差一点没真正落地。把今天先过稳，很多答案不会今晚就来。",
        social_teaser_options=["心一直悬着的时候，连很普通的一天，也像总差一点没真正落地。把今天先过稳，很多答案不会今晚就来。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="真正的心安，是不再提前替明天发愁",
        draft_body_markdown=(
            "心一直悬着的时候，连很普通的一天，也像总差一点没真正落地。\n\n"
            "已经过去的事，今天先别再一遍遍回头想；还没发生的事，也不必提前在心里演很多遍。\n\n"
            "把今天先过稳，把这顿饭吃完，把灯关好。很多答案不会今晚就来，但心会先慢慢安静下来。"
        ),
        assets=assets,
    )

    assert package["publish_lead"].startswith("不是每件事都要今晚想通")
    assert "先把今天过完" in package["publish_lead"]
    assert any(fragment in package["abstract"] for fragment in ("已经过去", "还没发生", "把饭吃好", "把灯关好"))


def test_build_local_assets_fallback_inner_settlement_uses_bedtime_cover_copy() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="真正的心安，是不再提前替明天发愁",
        topic_title="真正的心安，是不再提前替明天发愁",
        topic_angle="从已经过去的事和还没发生的事都会牵着心走切入，写人怎样把心放回今天。",
        draft_title="真正的心安，是不再提前替明天发愁",
        draft_body_markdown=(
            "心一直悬着的时候，连很普通的一天，也像总差一点没真正落地。\n\n"
            "已经过去的事，今天先别再一遍遍回头想；还没发生的事，也不必提前在心里演很多遍。\n\n"
            "把今天先过稳，把这顿饭吃完，把灯关好。很多答案不会今晚就来，但心会先慢慢安静下来。"
        ),
    )

    assert assets["cover_copy"] == "别急着把所有事想通，今晚先把心放平一点。"
    assert assets["social_teaser"] == "心一直悬着的时候，连很普通的一天，也像总差一点没真正落地。很多答案不会今晚就来，先把心放回今天。"


def test_build_local_tracked_article_topic_fallback_supportive_appreciation_rewrites_away_from_reference_title() -> None:
    topic = workbench._build_local_tracked_article_topic_fallback(
        {
            "article_title": "如果你身边有这样一个心软的人，请一定要好好珍惜",
            "body_markdown": (
                "这样的人，心很软，也很重感情。"
                "他们不舍得让身边的人受伤，处处照顾着别人的感受。"
                "因为这样的人，一生难遇。"
            ),
            "summary": "",
            "structure_notes": "",
        }
    )

    assert topic["title"] == "总把别人感受放在前面的人，其实最该被人好好珍惜"
    assert topic["title"] != "如果你身边有这样一个心软的人，请一定要好好珍惜"
    assert "先顾别人感受" in topic["angle"]


def test_build_local_assets_fallback_supportive_appreciation_uses_mode_copy() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        topic_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        topic_angle="从一个人总会先把场面放软、先顾别人感受写起。",
        draft_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        draft_body_markdown=(
            "她顺手让了一步、先顾了别人感受，结果又被当成理所当然的那一下。\n\n"
            "先看看那份总替别人留余地的习惯，是怎么被当成理所当然的。\n\n"
            "有些人不是没脾气，只是每次都先把场面放软。"
        ),
    )

    assert assets["cover_copy"] == "会先顾别人感受的人，也该被认真接住。"
    assert assets["social_teaser"] == "她顺手让了一步、先顾了别人感受，结果又被当成理所当然的那一下。真正难得的，是有人看见这份退让背后的在乎。"


def test_build_local_assets_and_publish_fallback_supportive_appreciation_do_not_drift_to_aftercare() -> None:
    draft_body = (
        "她顺手让了一步、先顾了别人感受，结果又被当成理所当然的那一下。\n\n"
        "性子柔的人也会有脾气。只是话到嘴边，她会先想一想：这句话说重了，对方会不会难过。\n\n"
        "她肯体谅，不代表她什么都不懂；她愿意把话放软，也不代表她不会受伤。\n\n"
        "她还愿意温柔，是因为心里有情分。她愿意留台阶，是因为舍不得把一段关系推到更冷的地方。\n\n"
        "我很喜欢一句话：“温柔到最后，看的是分寸，也看回应。”\n\n"
        "柔软被珍惜以后，会长出更踏实的爱。"
    )
    focus_payload = {
        "source_type": "tracked_article",
        "topic_title": "总把别人感受放在前面的人，其实最该被人好好珍惜",
        "topic_angle": "从一个人总会先把场面放软、先顾别人感受写起。",
        "body_markdown": draft_body,
    }

    assert workbench._resolve_local_fallback_mode(focus_payload) == "supportive_appreciation"

    assets_payload = workbench._build_local_assets_fallback(
        project_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        topic_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        topic_angle="从一个人总会先把场面放软、先顾别人感受写起。",
        draft_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        draft_body_markdown=draft_body,
    )
    combined_assets = f"{assets_payload['cover_copy']}\n{assets_payload['social_teaser']}"

    assert assets_payload["cover_copy"] == "会先顾别人感受的人，也该被认真接住。"
    assert "真正难得的，是有人看见这份退让背后的在乎" in assets_payload["social_teaser"]
    assert "吵完" not in combined_assets
    assert "冷气" not in combined_assets

    assets = workbench.AssetItem(
        project_slug="supportive-appreciation-project",
        draft_version=1,
        version=1,
        title_options=list(assets_payload["title_options"]),
        recommended_title=str(assets_payload["recommended_title"]),
        cover_prompt=str(assets_payload["cover_prompt"]),
        cover_copy=str(assets_payload["cover_copy"]),
        social_teaser=str(assets_payload["social_teaser"]),
        social_teaser_options=list(assets_payload["social_teaser_options"]),
        cover_image_path="",
        cover_image_url="",
        created_at="2026-07-12T00:00:00Z",
    )
    package = workbench._build_local_publish_package_fallback(
        draft_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        draft_body_markdown=draft_body,
        assets=assets,
    )

    assert any(fragment in package["publish_lead"] for fragment in ("语气放软", "舍不得", "在乎的人"))
    assert any(fragment in package["abstract"] for fragment in ("关系", "误会", "往前走一步"))
    assert "吵完" not in package["publish_lead"]
    assert "冷气" not in package["publish_lead"]


def test_build_local_publish_package_fallback_supportive_appreciation_uses_mode_lead_and_abstract() -> None:
    assets = SimpleNamespace(
        recommended_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        title_options=["总把别人感受放在前面的人，其实最该被人好好珍惜"],
        cover_copy="会先顾别人感受的人，也该被认真接住。",
        social_teaser="她顺手让了一步、先顾了别人感受，结果又被当成理所当然的那一下。真正难得的，是有人看见这份退让背后的在乎。",
        social_teaser_options=["她顺手让了一步、先顾了别人感受，结果又被当成理所当然的那一下。真正难得的，是有人看见这份退让背后的在乎。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        draft_body_markdown=(
            "谁是真心，谁在敷衍，他其实都分得清。很多事他不是没看出来，只是关系摆在面前时，他总习惯先把语气放软。\n\n"
            "他愿意把那点难受先放一放，也想给关系留一次回来的机会。\n\n"
            "温柔拿出来了，就该被好好接住。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "他其实什么都懂，只是轮到在乎的人，还是会先把语气放软一点。看得清，却愿意把情分放在前面，这样的温柔最难得，也最该被认真珍惜。"
    assert package["abstract"] == "心软不是迟钝，退让也不是没分寸。真正难得的，是一个人明明看得清，还愿意给关系留一点暖意。若你身边有这样的人，请记得好好接住他的温柔。"
    assert package["intro_options"][0] == package["publish_lead"]
    assert "看得清，还愿意把语气放软的人，最该被认真珍惜。" in package["intro_options"]
    assert "心软不是迟钝，是明白以后还愿意留一点暖意。" in package["intro_options"]
    assert "敷衍" not in package["publish_lead"]
    assert "顺口应付" not in package["abstract"]


def test_build_local_publish_package_fallback_supportive_appreciation_uses_apology_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        title_options=["总把别人感受放在前面的人，其实最该被人好好珍惜"],
        cover_copy="会先顾别人感受的人，也该被认真接住。",
        social_teaser="明明已经有点难受了，对方把歉意说出口时，她还是先把语气放轻了。真正难得的，是有人看见这份退让背后的在乎。",
        social_teaser_options=["明明已经有点难受了，对方把歉意说出口时，她还是先把语气放轻了。真正难得的，是有人看见这份退让背后的在乎。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="总把别人感受放在前面的人，其实最该被人好好珍惜",
        draft_body_markdown=(
            "明明已经有点难受了，对方把歉意说出口时，她还是先把语气放轻了。\n\n"
            "对方若真心道了歉，她通常会把那点难受先放一放。\n\n"
            "她愿意把那点难受先放一放，也想给关系留一次回来的机会。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "那句“对不起”说完，她沉默了一会儿，还是把水杯往你这边推了推。刚才的话确实伤到了她，可这段关系在她心里，比当下那口气更重要，所以她愿意再把话接起来。"
    assert package["abstract"] == "道歉最有分量的部分，往往发生在下一次：你记得她为什么难过，也真的把那件事做得不一样。温柔被认真接住，才会一直是温柔。"
    assert "道歉最有分量的部分，发生在下一次真的做得不一样。" in package["intro_options"]
    assert "温柔被认真接住，才会一直是温柔。" in package["intro_options"]


def test_build_local_assets_fallback_supportive_appreciation_uses_apology_packaging() -> None:
    draft_body = (
        "明明已经有点难受了，对方把歉意说出口时，她还是先把语气放轻了。\n\n"
        "一句道歉真正有分量的地方，是有人看见她刚刚也难受了。\n\n"
        "会原谅的人，本来就难得。"
    )
    assets = workbench._build_local_assets_fallback(
        project_title="那个受了委屈还把语气放轻的人，更该被珍惜",
        topic_title="那个受了委屈还把语气放轻的人，更该被珍惜",
        topic_angle="从一个人明明已经有点难受，却还是先把语气放轻写起。",
        draft_title="那个受了委屈还把语气放轻的人，更该被珍惜",
        draft_body_markdown=draft_body,
    )

    assert assets["cover_copy"] == "那个受了委屈还把语气放轻的人，更该被珍惜。"
    assert assets["social_teaser"] == "明明已经有点难受了，对方把歉意说出口时，她还是先把语气放轻了。愿意留余地的人，更需要被认真回应。"


def test_build_local_publish_package_fallback_supportive_appreciation_uses_misread_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="别把一个人的体谅，当成他天生就该让着你",
        title_options=["别把一个人的体谅，当成他天生就该让着你"],
        cover_copy="别把他的体谅，当成你可以反复透支的东西。",
        social_teaser="太好说话久了，别人很容易忘了，她也会疼。体谅不是天生该让，能被珍惜，温柔才会一直留得住。",
        social_teaser_options=["太好说话久了，别人很容易忘了，她也会疼。体谅不是天生该让，能被珍惜，温柔才会一直留得住。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="别把一个人的体谅，当成他天生就该让着你",
        draft_body_markdown=(
            "太好说话久了，别人很容易忘了，她也会疼。\n\n"
            "一句对不起落下来，她愿意把这件事往后放一放，不代表她真的什么都不介意。\n\n"
            "她肯翻篇一次，是在给感情机会，不是在把自己交给你反复消耗。"
        ),
        assets=assets,
    )

    assert "好说话" in package["publish_lead"]
    assert "会疼" in package["publish_lead"]
    assert "情分" in package["publish_lead"]
    assert "理所当然" in package["publish_lead"]
    assert "同一件事再发生" in package["abstract"]
    assert "愿意翻篇，是在给关系一次机会，不是在允许同一件事重来。" in package["intro_options"]
    assert "道歉说完以后，真正重要的是把答应过的改变做到。" in package["intro_options"]


def test_build_local_tracked_article_fallback_supportive_appreciation_uses_pure_warmth_profile() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "心软的人，一生难遇",
        "topic_title": "心软的人，一生难遇，请一定好好珍惜",
        "topic_angle": "从那种总会先顾别人感受、把温暖回给别人、遇事也愿意留余地的人切入，写他们为什么值得被好好珍惜。",
        "reference_article_body_markdown": (
            "有一种人，习惯了燃烧自己，去照亮别人。"
            "你对他好，他会对你更好；你给他温暖，他会回馈给你更多的温暖。"
            "这样的人，心很软，也很重感情。"
            "如果你身边有这样一个心软的人，请你一定要牵紧他的手。"
        ),
        "strategy_card": {"structure_mode": "supportive_appreciation"},
    }

    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(payload)

    assert title == "心软的人，一生难遇，请一定好好珍惜"
    assert body_markdown.startswith("别人递来一点暖意，他常常会想办法再多还回去一点。")
    assert "你对他好一分，他会记在心里很久" in body_markdown
    assert "心软的人最难得的地方，从来不只是脾气好。" in body_markdown
    assert "一生那么长，真正愿意把温暖回给你的人并不多。" in body_markdown
    assert "一句道歉真正有分量的地方" not in body_markdown
    assert "太好说话久了" not in body_markdown
    assert "谁是真心，谁在敷衍" not in body_markdown


def test_build_local_publish_package_fallback_supportive_appreciation_uses_warmth_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="心软的人，一生难遇，请一定好好珍惜",
        title_options=["心软的人，一生难遇，请一定好好珍惜"],
        cover_copy="会先顾别人感受的人，也该被认真接住。",
        social_teaser="别人递来一点暖意，他常常会想办法再多还回去一点。真正难得的，是他把收到的暖意又慢慢还了回来。",
        social_teaser_options=["别人递来一点暖意，他常常会想办法再多还回去一点。真正难得的，是他把收到的暖意又慢慢还了回来。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="心软的人，一生难遇，请一定好好珍惜",
        draft_body_markdown=(
            "别人递来一点暖意，他常常会想办法再多还回去一点。\n\n"
            "心软的人最难得的地方，从来不只是脾气好。是他明明也会累、也会疼，却还是愿意把收到的善意，再往回递一点给身边的人。\n\n"
            "一生那么长，真正愿意把温暖回给你的人并不多。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "别人递来一点暖意，他常常会想办法再多还回去一点。这样的人，未必最会说，可你会在很多小事里看见他的认真：记得你的难处，也舍得把自己的好一遍遍落回来。被这样的人放在心上，日子会慢慢暖起来。"
    assert package["abstract"] == "真正稀缺的，不是说得多动听，而是把温柔一遍遍落进小事里的人。别等他把失望咽多了，才想起他的体谅有多珍贵。"
    assert package["abstract"] != assets.social_teaser
    assert "一句道歉不难" not in package["abstract"]
    assert "心软的人，一生难遇，也值得被人好好珍惜。" in package["intro_options"]
    assert "收到一点暖意，还愿意再慢慢还回来的人并不多。" in package["intro_options"]


def test_build_local_assets_fallback_supportive_appreciation_uses_warmth_copy() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="心软的人，一生难遇，请一定好好珍惜",
        topic_title="心软的人，一生难遇，请一定好好珍惜",
        topic_angle="从那种总会先顾别人感受、把温暖回给别人、遇事也愿意留余地的人切入，写他们为什么值得被好好珍惜。",
        draft_title="心软的人，一生难遇，请一定好好珍惜",
        draft_body_markdown=(
            "别人递来一点暖意，他常常会想办法再多还回去一点。\n\n"
            "你对他好一分，他会记在心里很久，转身又把这份好慢慢添一点还给你。\n\n"
            "心软的人最难得的地方，从来不只是脾气好。"
        ),
    )

    assert assets["cover_copy"] == "心软的人，一生难遇，也值得被人好好珍惜。"
    assert assets["social_teaser"] == "别人递来一点暖意，他常常会想办法再多还回去一点。真正难得的，是他把收到的暖意又慢慢还了回来。"


def test_resolve_local_generic_fallback_mode_keeps_supportive_apology_body_out_of_aftercare_lane() -> None:
    body_markdown = (
        "明明已经有点难受了，对方把歉意说出口时，她还是先把语气放轻了。很多人就是在这种时候，误会了他。\n\n"
        "他的分寸一直都在，只是总把在乎摆在了前面。对方若真心道了歉，他通常会把那点难受先放一放。\n\n"
        "别只记得他容易原谅。也要记得，在他把话放软以后，反过来问一句：“刚刚是不是让你难受了？”"
    )

    mode = workbench._resolve_local_generic_fallback_mode(
        {
            "source_type": "tracked_article",
            "topic_title": "总把别人感受放在前面的人，其实最该被人好好珍惜",
            "body_markdown": body_markdown,
        }
    )

    assert mode == "supportive_appreciation"


def test_build_local_tracked_article_topic_fallback_uses_endings_acceptance_mode_seed() -> None:
    topic = workbench._build_local_tracked_article_topic_fallback(
        {
            "article_title": "感谢相遇，不谈亏欠",
            "summary": "文章讨论关系结束后如何把失去从亏欠叙事里松开，重点不是劝人立刻忘记，而是接纳离开、保存相遇意义，并把留下来的温暖内化成继续往前的力量。",
            "body_markdown": (
                "成年人的关系，原本就是一段一段的。接纳离开，才是对这段关系最好的祝福。"
                "真正的成熟，不是变得麻木，而是允许一切发生，也允许一切结束。"
                "感谢相遇，不谈亏欠。带着这份从容与爱意，整理行囊，去拥抱下一场未知的山海。"
            ),
            "structure_notes": "开头先借引语点出聚散有时，中段拆为什么人会替一段关系追讨完整定义，结尾回到允许结束和继续前行。",
            "analysis_structure_mode": "emotional_engine_direct",
        }
    )

    assert topic["title"] == "有些相遇没能走到最后，却会悄悄成全后来的你"
    assert "一段关系的结束理解成白费" in topic["angle"]
    for forbidden in ("围绕《", "重建新的具体入口", "更贴近真人表达", "感谢相遇，不谈亏欠"):
        assert forbidden not in topic["angle"]


def test_build_local_tracked_article_draft_fallback_emotional_release_avoids_strategy_leak_and_reference_tail() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "source_type": "tracked_article",
            "topic_title": "有些相遇没能走到最后，却会悄悄成全后来的你",
            "topic_angle": "从人为什么总把一段关系的结束理解成白费切入，写真正让人难过的，常常不是离开本身，而是舍不得承认有些相遇本来就有阶段；也写人怎样把留下来的温暖、眼界和成长收回自己身上，带着感谢继续往前。",
            "body_markdown": (
                "成年人的关系，原本就是一段一段的。接纳离开，才是对这段关系最好的祝福。\n\n"
                "真正的成熟，不是变得麻木，而是允许一切发生，也允许一切结束。\n\n"
                "感谢相遇，不谈亏欠。带着这份从容与爱意，整理行囊，去拥抱下一场未知的山海。"
            ),
            "strategy_card": {"structure_mode": "emotional_engine_direct"},
        }
    )

    assert title == "有些相遇没能走到最后，却会悄悄成全后来的你"
    assert body_markdown.startswith("人最难放下的，常常不是离开，而是总想替一段认真过的关系要一个圆满结局。")
    assert "很多时候，人之所以迟迟不能释怀，不是因为那个人有多无可替代，而是总把“没走到最后”理解成那段路白走了。" in body_markdown
    assert "他后来没有留下，不等于那段陪伴是假的；这段路没走到最后，也不等于你当初爱错了。" in body_markdown
    assert "有些相遇没能走到最后，却真的成全了后来的你。" in body_markdown
    assert workbench.evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown).score == 0
    for forbidden in ("围绕《", "重建新的具体入口", "更贴近真人表达", "感谢相遇，不谈亏欠"):
        assert forbidden not in body_markdown


def test_build_local_tracked_article_draft_fallback_emotional_release_uses_reference_backview_opening() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "遗忘再长，也长不过明天和以后",
            "reference_article_body_markdown": (
                "可多少次灯火阑珊的街头，你久久伫立，因一个擦肩的背影有点像他，而蓦然回想起那年那天那一刻。"
                "又有多少个心绪翻涌的当下，你低眉叹息，因一点不起眼的小事，而不由自主地感慨，要是他还在就好了。"
            ),
            "outline": {
                "hook": "后来你才明白，真正难熬的，很多时候不是分开的那天。",
                "outline_body": "1. 反复想起不是因为没道理\n2. 真正挂住人的，是没收好的那段旧关系\n3. 把感谢留下，把今天过好",
            },
            "strategy_card": {"structure_mode": "emotional_engine_direct"},
        }
    )

    assert title == "遗忘再长，也长不过明天和以后"
    assert body_markdown.startswith(("很多想念都不是大张旗鼓的，只是在某个很普通的时刻，你忽然冒出一句：要是他还在就好了。", "街头一个像他的背影晃过去，你还是会下意识多看一眼。"))
    assert "后来你才明白，真正难熬的，很多时候不是分开的那天。" not in body_markdown.split("\n\n")[0]
    assert "你后来才懂，念念不忘的很多时候不只是某个人" in body_markdown
    assert "真正的释怀，也不是逼自己装作没事" in body_markdown
    assert "它最后不会一直把你拖回过去，只会变成心里一个安静的位置。" in body_markdown


def test_build_local_tracked_article_topic_fallback_uses_memory_presence_mode_seed() -> None:
    topic = workbench._build_local_tracked_article_topic_fallback(
        {
            "article_title": "遗忘再长，也长不过明天和以后",
            "summary": "文章写一个人为什么会在寻常日子里突然想起旧人，重点不是回头，而是承认那段相遇留下了痕迹。",
            "body_markdown": (
                "可多少次灯火阑珊的街头，你久久伫立，因一个擦肩的背影有点像他，而蓦然回想起那年那天那一刻。"
                "又有多少个心绪翻涌的当下，你低眉叹息，因一点不起眼的小事，而不由自主地感慨，要是他还在就好了。"
                "很多时候，他好像依然存在于你的世界里，随处可见，却又让你碰不到摸不着。"
            ),
            "structure_notes": "开头写普通时刻的突然想起，中段拆想念里混着什么，结尾回到那段痕迹如何慢慢变轻。",
            "analysis_structure_mode": "emotional_engine_direct",
        }
    )

    assert topic["title"] == "有些人走远了，还是会在你的日常里轻轻回来"
    assert "背影、擦肩和那句“要是他还在就好了”" in topic["angle"]
    assert "聊天记录" not in topic["angle"]
    assert "旧相册" not in topic["angle"]


def test_build_local_tracked_article_outline_fallback_emotional_acceptance_does_not_reuse_title_as_hook() -> None:
    payload = {
        "source_type": "tracked_article",
        "topic_title": "有些相遇没能走到最后，却会悄悄成全后来的你",
        "topic_angle": "从人为什么总把一段关系的结束理解成白费切入，写真正让人难过的，常常不是离开本身，而是舍不得承认有些相遇本来就有阶段；也写人怎样把留下来的温暖、眼界和成长收回自己身上，带着感谢继续往前。",
        "body_markdown": (
            "成年人的关系，原本就是一段一段的。接纳离开，才是对这段关系最好的祝福。"
            "真正的成熟，不是变得麻木，而是允许一切发生，也允许一切结束。"
            "感谢相遇，不谈亏欠。带着这份从容与爱意，整理行囊，去拥抱下一场未知的山海。"
        ),
        "strategy_card": {"structure_mode": "emotional_engine_direct"},
        "problem_brief": {
            "theme_axis": "主线是关系有阶段，不必把结束都理解成白费。",
            "core_conflict": "真正难的不是离开本身，而是人总想替一段认真过的关系讨一个圆满说法。",
        },
    }

    outline = workbench._build_local_tracked_article_outline_fallback(payload)

    assert outline["hook"] != "有些相遇没能走到最后，却会悄悄成全后来的你。"
    assert "圆满结局" in outline["hook"] or "成全过你" in outline["hook"]


def test_build_local_publish_package_fallback_emotional_release_uses_mode_lead_and_abstract() -> None:
    assets = SimpleNamespace(
        recommended_title="有些相遇没能走到最后，却会悄悄成全后来的你",
        title_options=["有些相遇没能走到最后，却会悄悄成全后来的你"],
        cover_copy="把那段路安放好，今天的日子才会重新朝前走。",
        social_teaser="后来你才明白，真正难熬的，很多时候不是分开的那天。回头看过、想明白过，然后把今天重新过好。",
        social_teaser_options=["后来你才明白，真正难熬的，很多时候不是分开的那天。回头看过、想明白过，然后把今天重新过好。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="有些相遇没能走到最后，却会悄悄成全后来的你",
        draft_body_markdown=(
            "街头一个像他的背影晃过去，你还是会下意识多看一眼。\n\n"
            "更多时候，只是舍不得把一段认真过的相遇，轻易算成白忙一场。\n\n"
            "把感谢收好，把关系放回过去，把今天认真过完。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "人最难放下的，往往不是离开本身，而是总想替一段认真过的关系讨一个圆满结局。可关系不是考试，不是每一次用力都要换来“走到最后”这四个字。它留下的眼界、分寸和成长，早就在悄悄成全后来的你。"
    assert package["abstract"] == "别再拿今天去补昨天的结局了。不是每段相遇都要圆满收场，才算来得值得。把舍不得交给时间，把成长收回自己身上，你会更轻一点，也会更坚定一点。"
    assert "不是每段相遇都要走到最后，才算来得值得。" in package["intro_options"]


def test_build_local_publish_package_fallback_emotional_release_uses_memory_reflux_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="那段旧关系没收好，往事就会在某个普通时刻回潮",
        title_options=["那段旧关系没收好，往事就会在某个普通时刻回潮"],
        cover_copy="想起不是回头，是心里那段旧关系还需要被轻轻安放。",
        social_teaser="你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉。真正反复回来的，不只是那个人，更是那段没说完的话和没被接住的自己。",
        social_teaser_options=["你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉。真正反复回来的，不只是那个人，更是那段没说完的话和没被接住的自己。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="那段旧关系没收好，往事就会在某个普通时刻回潮",
        draft_body_markdown=(
            "街头一个像他的背影晃过去，你还是会下意识多看一眼。\n\n"
            "你反复想起的，也不一定只是那个人。更多时候，是那句没说完的话，是当年没等到的回应，也是那个在关系里没有被好好接住的自己。\n\n"
            "等你不再拿今天去补昨天，心里的位置才会慢慢空出来。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "你以为自己早就放下了，直到街头一个像他的背影、深夜一页旧聊天记录，还是会让心里轻轻一沉。真正反复回来的，不只是那个人，更是那段没说完的话、没被接住的自己。"
    assert package["abstract"] == "想起并不丢人，舍不得也不代表你走不出来。把那段旧关系慢慢安放好，不再拿今天去补昨天，新的日子才会一点点亮起来。"
    assert "有些往事不是忘不掉" in package["intro_options"][1]


def test_build_local_assets_fallback_shapes_emotional_release_memory_presence_packaging() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="有些人走远了，还是会在你的日常里轻轻回来",
        topic_title="有些人走远了，还是会在你的日常里轻轻回来",
        topic_angle="从背影、擦肩和那句“要是他还在就好了”切入，写一个人为什么会在日常里突然想起旧人。",
        draft_title="有些人走远了，还是会在你的日常里轻轻回来",
        draft_body_markdown=(
            "很多想念都不是大张旗鼓的，只是在某个很普通的时刻，你忽然冒出一句：要是他还在就好了。\n\n"
            "很多时候，他好像依然存在于你的世界里，随处可见，却又让你碰不到摸不着。\n\n"
            "把那份想念安放好，你还是可以继续把今天过下去。"
        ),
    )

    assert assets["cover_copy"] == "有些人明明走远了，还是会在一个背影里轻轻回来。"
    assert assets["social_teaser"] == "很多想念都不是大张旗鼓的，只是在某个很普通的时刻，你忽然冒出一句：要是他还在就好了。有些人走远了，却还是会在你的日常缝隙里轻轻回来一下。"


def test_build_local_publish_package_fallback_emotional_release_uses_memory_presence_variant() -> None:
    assets = SimpleNamespace(
        recommended_title="有些人走远了，还是会在你的日常里轻轻回来",
        title_options=["有些人走远了，还是会在你的日常里轻轻回来"],
        cover_copy="有些人明明走远了，还是会在一个背影里轻轻回来。",
        social_teaser="很多想念都不是大张旗鼓的，只是在某个很普通的时刻，你忽然冒出一句：要是他还在就好了。有些人走远了，却还是会在你的日常缝隙里轻轻回来一下。",
        social_teaser_options=["很多想念都不是大张旗鼓的，只是在某个很普通的时刻，你忽然冒出一句：要是他还在就好了。有些人走远了，却还是会在你的日常缝隙里轻轻回来一下。"],
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="有些人走远了，还是会在你的日常里轻轻回来",
        draft_body_markdown=(
            "很多想念都不是大张旗鼓的，只是在某个很普通的时刻，你忽然冒出一句：要是他还在就好了。\n\n"
            "很多时候，他好像依然存在于你的世界里，随处可见，却又让你碰不到摸不着。\n\n"
            "把那份想念安放好，你还是可以继续把今天过下去。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "很多想起不是因为你走不出来，而是那个人曾经认真来过，所以哪怕走远了，也还是会在某个背影、一次擦肩、一个普通傍晚里，轻轻回来一下。"
    assert package["abstract"] == "不是要你回头重走那段路，只是承认有些相遇确实留下了痕迹。把那份想念安放好，你还是可以带着温柔，继续过眼前的日子。"
    assert "有些人明明走远了，还是会在你的日常缝隙里轻轻出现。" in package["intro_options"]


def test_build_local_tracked_article_draft_fallback_resilience_reconstruction_keeps_training_rebuild_lane() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "手术台下来以后，一个人是怎么靠重复训练把自己重新托住的",
            "topic_angle": "从伤痛、复健到泳池里多划出的每一下，拆开一个人在身体受限之后，怎样靠持续行动慢慢重建意志，而不把低谷当成自我定义。",
            "reference_article_body_markdown": (
                "3岁那年，一场车祸无情夺走了蒋裕燕的右臂与右腿。从3岁到8岁，她每一年都要被迫走上手术台，接受锯掉新生骨头的剧痛。\n\n"
                "为了康复，她走进了泳池。没有右臂维持平衡，没有右腿蹬水发力，她每一次划水都要比常人多划11下。\n\n"
                "疲惫与酸痛，肩伤反复发作、背痛缠扰不休、炎症如影随形，可她从未停下前进的脚步。命运以痛吻她，她却在破碎中重建自己，不让任何人定义她能做的事情。"
            ),
            "outline": {
                "hook": "手术台下来以后，真正难的不是疼那一下，而是第二天还要继续把身体重新练回来。",
                "outline_body": "1. 命运重击和手术台\n2. 泳池里的反复训练\n3. 疼痛和重复怎样慢慢把人重新立住\n4. 结尾回到不被定义和继续往前",
            },
            "strategy_card": {"structure_mode": "resilience_reconstruction"},
            "problem_brief": {
                "theme_axis": "主线是一个人怎样在破碎之后重新把自己练回来。",
                "core_conflict": "命运重击和长期疼痛没有结束她，反而逼着她一点点把自己重新托住。",
            },
        }
    )

    assert title == "手术台下来以后，一个人是怎么靠重复训练把自己重新托住的"
    assert "别人后来看到的是成绩，是名字被念出来的那一刻。" in body_markdown
    assert "没有右臂帮她稳住平衡，没有右腿替她把水蹬开" in body_markdown
    assert "愿你被生活打磨过以后" not in body_markdown
    assert workbench.evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown).score == 0


def test_build_local_tracked_article_draft_fallback_legacy_pressure_uses_pressure_interface_direct() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "那次体检被你改到第几回了",
            "topic_angle": "从顺延体检、推迟吃饭和整个人越来越钝切入，写自我照料被一再压后的时候，身体和情绪会怎样慢慢替你记账。",
            "reference_article_body_markdown": (
                "她先把体检往后改，又把回家吃饭这件事往后推。\n\n"
                "后来整个人越来越钝，连一句解释都懒得说。\n\n"
                "复查提醒弹出来，你顺手划掉，那句“建议复查”没有消失，只是又被往后放了一次。"
            ),
            "outline": {
                "hook": "复查提醒弹出来的时候，你只是顺手划掉，可那口一直绷着的气并没有跟着消失。",
                "outline_body": "1. 从体检和复查一再往后放写起\n2. 自我照料怎么被工作和体面不断往后挤\n3. 钝感、累和失序怎样一点点落进日常\n4. 结尾回到先把那口气松下来",
            },
            "strategy_card": {"structure_mode": "internal_pressure"},
            "problem_brief": {
                "theme_axis": "主线是自我照料被一再压后时，日子怎样慢慢失序。",
                "core_conflict": "外面看着还在照常运转，可身体和情绪已经先替人扛不住了。",
            },
        }
    )

    assert title == "那次体检被你改到第几回了"
    assert "复查提醒" in body_markdown
    assert "你把自己放回今天" in body_markdown
    assert "把复查约回日历" in body_markdown
    assert "把饭吃热" in body_markdown
    assert "预约确认好" in body_markdown
    assert all(
        token not in body_markdown
        for token in (
            "耗空",
            "身体先开始交代",
            "胃口",
            "睡眠变浅",
            "孤立无援",
            "外援",
            "先把那口气松下来",
            "先别急着再逼自己更能扛",
        )
    )
    assert "愿你把眼前的日子慢慢过顺" not in body_markdown
    assert workbench.evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown).score == 0


def test_build_local_tracked_article_draft_fallback_scene_first_progression_keeps_office_scene_flow() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "散会后才开口，位置就会慢慢往后退",
            "topic_angle": "从会议开始前翻方案、会上顺着气氛点头、散会后才把话在心里补完这一整段现场切入，写一个人怎样在权威和秩序面前一次次把关键表达往后放。",
            "reference_article_body_markdown": (
                "周一早会开始前，她站在投影幕布旁，把昨晚改好的方案又往后翻了一页。\n\n"
                "主管进门，随手把咖啡放在桌角，先说了一句“今天先按老方案过吧”，会议室里的人都低头去翻手里的资料。\n\n"
                "散会以后，她还坐在原位，看着屏幕上的最后一页，直到清洁阿姨来收水杯，才把那句本来该在会上说出来的话关掉。"
            ),
            "outline": {
                "hook": "周一早会开始前，她站在投影幕布旁，把昨晚改好的方案又往后翻了一页。",
                "outline_body": "1. 会议开始前翻方案\n2. 现场顺着气氛点头\n3. 散会后才把话在心里补完\n4. 结尾回到表达机会怎样一次次被让掉",
            },
            "strategy_card": {"structure_mode": "scene_first_progression"},
            "problem_brief": {
                "theme_axis": "主线是很多沉默不是没想法，而是在现场里先替秩序让了路。",
                "core_conflict": "明明知道有话该说，可一回到那个会议室里，人就先把更重要的话压后。",
            },
        }
    )

    assert title == "散会后才开口，位置就会慢慢往后退"
    assert "领导把杯子往桌边一放，话题就顺着旧方案往下走了。" in body_markdown
    assert "等人散得差不多了，你再去想刚才那几句话该怎么说，已经不像表达，更像一个人给自己补课。" in body_markdown
    assert "我也可以在这里说话" in body_markdown
    assert "我是不是本来就不该占那个位置" not in body_markdown
    assert "愿你以后遇到重要的人和事" not in body_markdown
    assert workbench.evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown).score == 0


def test_build_local_tracked_article_outline_fallback_scene_first_office_keeps_positive_recovery_direction() -> None:
    payload = {
        "source_type": "tracked_article",
        "topic_title": "散会后才开口，位置就会慢慢往后退",
        "topic_angle": "从会议开始前翻方案、会上顺着气氛点头、散会后才把话在心里补完这一整段现场切入，写一个人怎样在权威和秩序面前一次次把关键表达往后放。",
        "body_markdown": (
            "周一早会开始前，她站在投影幕布旁，把昨晚改好的方案又往后翻了一页。\n\n"
            "主管进门，随手把咖啡放在桌角，先说了一句“今天先按老方案过吧”，会议室里的人都低头去翻手里的资料。\n\n"
            "散会以后，她还坐在原位，看着屏幕上的最后一页，直到清洁阿姨来收水杯，才把那句本来该在会上说出来的话关掉。"
        ),
        "strategy_card": {
            "structure_mode": "scene_first_progression",
            "positive_direction": "下次再进会议室，别总把关键那句留到散会后。",
        },
    }

    outline = workbench._build_local_tracked_article_outline_fallback(payload)

    assert "怀疑也从这里慢慢长出来" not in outline["outline_body"]
    assert "话总留到这里，位置也会跟着一点点往后退。" in outline["outline_body"]
    assert "下次再进会议室，别总把关键那句留到散会后。" in outline["outline_body"]


def test_build_local_tracked_article_draft_fallback_scene_first_progression_keeps_transit_scene_flow() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "没问出口的那句话，最容易把关系拖远",
            "topic_angle": "从地铁口等车、看见不对劲却还是先没问、上车后话题彻底沉下去这一段连续现场切入，写关系怎样在一次次没追问里慢慢把靠近让掉。",
            "reference_article_body_markdown": (
                "雨停以后，她们站在地铁口等最后一班接驳车，手机屏幕上还停着那句没发出去的“你最近是不是不太开心”。\n\n"
                "朋友把围巾往上拉了拉，只说“最近有点忙”，然后低头去看脚边那滩还没干透的水。\n\n"
                "车来了，她们一前一后上去，坐定以后谁都没有再提刚才的话题，只剩窗户上被呵出来的一小团白雾。"
            ),
            "outline": {
                "hook": "明明就差一句，话到嘴边时，人还是先沉默了。",
                "outline_body": "1. 地铁口等车\n2. 看见不对劲却还是先没问\n3. 上车后话题彻底沉下去\n4. 结尾回到很多靠近是怎样被自己让掉的",
            },
            "strategy_card": {"structure_mode": "scene_first_progression"},
            "problem_brief": {
                "theme_axis": "主线是很多关系不是突然变淡，而是在一次次没追问里把靠近慢慢让掉。",
                "core_conflict": "明明看见了对方的不对劲，可一回到那个现场里，人还是先把更重要的话收了回去。",
            },
        }
    )

    assert title == "没问出口的那句话，最容易把关系拖远"
    assert body_markdown.startswith("雨停了，车还没进站。她盯着对话框里那句删了又停住的话，指尖一直没离开屏幕。")
    assert "她抬手拢了拢围巾，只说这阵子事多。" in body_markdown
    assert "嘴边那句真正想问的，还是被你自己按住了。" in body_markdown
    assert "玻璃很快蒙起一层白气，" in body_markdown
    assert "愿你以后遇到重要的人和事" not in body_markdown
    assert workbench.evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown).score == 0


def test_build_local_tracked_article_draft_fallback_scene_first_progression_keeps_household_scene_flow() -> None:
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(
        {
            "topic_title": "家里的心事，最怕总被顺到明天",
            "topic_angle": "从夜里回家、看见药盒和检查单、想问的话又往回收这一整段连续现场切入，写家里的重要话题怎样一次次输给先把场面维持住的本能。",
            "reference_article_body_markdown": (
                "夜里回到家，餐桌上的检查单还没收。她把包放下，先去摸了一下水壶外壁，还是温的。\n\n"
                "孩子已经睡了，灯还留着一盏。她原本想问一句今天复查到底怎么说，可看见对方揉了揉眉心，话又先收了回去。\n\n"
                "很多家里的心事，不是不能说，只是总被那句“明天再说吧”轻轻按住了。"
            ),
            "outline": {
                "hook": "夜里回到家，餐桌上的检查单还没收。",
                "outline_body": "1. 夜里回家看见检查单\n2. 想问的话又先收回去\n3. 第二天照常出门可那根线还悬着\n4. 结尾回到家里的心事要慢慢说开",
            },
            "strategy_card": {"structure_mode": "scene_first_progression"},
            "problem_brief": {
                "theme_axis": "主线是家里的重要话题怎样一次次输给先把场面维持住的本能。",
                "core_conflict": "明明想问也看见了对方的疲惫，可一回到那个晚上和那个家里的气氛里，人就先把更重要的话收回去。",
            },
        }
    )

    assert title == "家里的心事，最怕总被顺到明天"
    assert body_markdown.startswith("夜里进门时，餐桌只收了一半，壶身还有余温，那张单子正压在桌角。")
    assert "桌上的药盒还摆着，那张单子也没收起来。你站在那儿看了一会儿，还是先把那句想问的话咽了回去。" in body_markdown
    assert "家里最难的，往往是每个人都想等对方先缓一缓。" in body_markdown
    assert "第二天照常出门，消息照回，饭也照吃，表面上像什么都没发生。" in body_markdown
    assert "真正托住一个家的，是还能坐下来慢慢说" in body_markdown
    assert "很多重要的问题，不是没有机会谈" not in body_markdown
    assert "重要的话总被往后推，人也会在一次次体谅里" not in body_markdown
    assert "愿你以后遇到重要的人和事" not in body_markdown
    assert workbench.evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown).score == 0


def test_build_local_assets_fallback_shapes_emotional_release_packaging_without_reference_tail() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="有些相遇没能走到最后，却会悄悄成全后来的你",
        topic_title="有些相遇没能走到最后，却会悄悄成全后来的你",
        topic_angle="从人为什么总把一段关系的结束理解成白费切入，也写人怎样把留下来的温暖慢慢收回自己身上。",
        draft_title="有些相遇没能走到最后，却会悄悄成全后来的你",
        draft_body_markdown=(
            "后来你才明白，真正难熬的，很多时候不是分开的那天。\n\n"
            "那段路安放好了，今天的日子才不会总被昨天拽回去。\n\n"
            "愿你记得那些好，也接住那些疼。然后把这一页轻轻合上，去过眼前新的日子。"
        ),
    )

    assert assets["cover_copy"] == "有些关系停在半路，也会成全后来的你。"
    assert (
        assets["social_teaser"]
        == "人最难放下的，往往不是离开，而是总想替一段认真过的关系要一个圆满结局。可有些相遇就算停在半路，也已经把成长和勇气留在了你身上。"
    )
    combined = "\n".join([assets["cover_copy"], assets["social_teaser"]])
    assert "感谢相遇，不谈亏欠" not in combined


def test_build_local_assets_fallback_shapes_emotional_release_memory_reflux_packaging() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="那段旧关系没收好，往事就会在某个普通时刻回潮",
        topic_title="那段旧关系没收好，往事就会在某个普通时刻回潮",
        topic_angle="从街头背影、旧相册、聊天记录这些回潮瞬间切入，写人为什么会反复想起一个已经走远的人。",
        draft_title="那段旧关系没收好，往事就会在某个普通时刻回潮",
        draft_body_markdown=(
            "你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉。\n\n"
            "你反复想起的，也不一定只是那个人。更多时候，是那句没说完的话，是当年没等到的回应，也是那个在关系里没有被好好接住的自己。\n\n"
            "等你不再拿今天去补昨天，心里的位置才会慢慢空出来。"
        ),
    )

    assert assets["cover_copy"] == "想起不是回头，是心里那段旧关系还需要被轻轻安放。"
    assert assets["social_teaser"] == "你以为自己早就放下了，直到街头一个像他的背影，还是会让心里轻轻一沉。真正反复回来的，不只是那个人，更是那段没说完的话和没被接住的自己。"
    assert assets["recommended_title"] == "那段旧关系没收好，往事就会在某个普通时刻回潮"


def test_build_local_assets_fallback_scene_first_progression_transit_uses_theme_specific_packaging() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="没问出口的那句话，最容易把关系拖远",
        topic_title="没问出口的那句话，最容易把关系拖远",
        topic_angle="从地铁口等车、看见不对劲却还是先没问、上车后话题彻底沉下去这一段连续现场切入，写关系怎样在一次次没追问里慢慢把靠近让掉。",
        draft_title="没问出口的那句话，最容易把关系拖远",
        draft_body_markdown=(
            "雨刚停，出站口外的摆渡车还没来。她低头看着亮了又暗的手机，那句打到一半的话始终没有发出去。\n\n"
            "她抬手拢了拢围巾，只说这阵子事多。你听得出那句话后面还有东西，也看见她眼里的疲惫，可嘴边那句真正想问的，还是被你自己按住了。\n\n"
            "等摆渡车靠边，两个人跟着人群上去，各自看向窗外。玻璃很快蒙起一层白气，刚才那个话头也就这么断在了路上。"
        ),
    )

    assert assets["cover_copy"] == "那句该问的话，别总留到车开以后。"
    assert assets["social_teaser"].startswith("她那句“最近有点忙”刚落下去")
    assert "今晚最该问的那一句" in assets["social_teaser"]
    assert "雨后傍晚的出站口和摆渡车现场" in assets["cover_prompt"]
    assert "不要做纯色底大字卡" in assets["cover_prompt"]
    assert "左侧留标题安全区" in assets["cover_prompt"]


def test_build_local_assets_fallback_scene_first_progression_office_uses_positive_recovery_packaging() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="散会后才开口，位置就会慢慢往后退",
        topic_title="散会后才开口，位置就会慢慢往后退",
        topic_angle="从会议开始前翻方案、会上顺着气氛点头、散会后才把话在心里补完这一整段现场切入，写一个人怎样在权威和秩序面前一次次把关键表达往后放。",
        draft_title="散会后才开口，位置就会慢慢往后退",
        draft_body_markdown=(
            "周一早会开始前，她站在投影幕布旁，把昨晚改好的那页方案又往后翻了一遍。\n\n"
            "领导把杯子往桌边一放，话题就顺着旧方案往下走了。你昨晚改到很晚的那一页还停在屏幕上，可那个本来该接上的提醒，最后还是被你自己咽了回去。\n\n"
            "可很多位置，不是等谁来给的，是你肯把话留在当场，才会一点点站稳。下次再进那间会议室，别急着替所有人把场面圆好。"
        ),
    )

    assert assets["cover_copy"] == "该说的时候开口，才不会总在散会以后后悔。"
    assert assets["social_teaser"].startswith("会已经散了，那页改过的方案还亮在屏幕上。")
    assert "那句你明明该在当场说的话" in assets["social_teaser"]
    assert all("现场切入" not in item and "写一个人怎样" not in item for item in assets["social_teaser_options"])
    assert "清晨会议室或工位现场" in assets["cover_prompt"]
    assert "保留左下标题安全区" in assets["cover_prompt"]


def test_resolve_local_cover_scene_variant_prefers_scene_first_transit_markers() -> None:
    assert (
        workbench._resolve_local_cover_scene_variant(
            "没问出口的那句话，最容易把关系拖远",
            "雨刚停，出站口外的摆渡车还没来。",
            "有些距离，不是突然有的，是那句真话总被拖到最后。",
        )
        == "transit"
    )


def test_resolve_local_cover_scene_variant_prefers_scene_first_office_markers() -> None:
    assert (
        workbench._resolve_local_cover_scene_variant(
            "散会以后，真正让人难受的，往往不是那句重话",
            "散会以后，工位上的屏幕还亮着。",
            "很多委屈不是当场发作的，是回到工位后才一点点压上来。",
        )
        == "office"
    )


def test_resolve_local_cover_scene_variant_prefers_scene_first_household_markers() -> None:
    assert (
        workbench._resolve_local_cover_scene_variant(
            "那张检查单放在桌上时，她忽然不想再说自己没事",
            "夜里回到家，餐桌上的检查单还没收。",
            "有些撑着，不是因为真的不累，是怕家里的人跟着慌。",
        )
        == "household"
    )


def test_resolve_local_cover_scene_variant_recovers_household_from_household_title_and_copy() -> None:
    assert (
        workbench._resolve_local_cover_scene_variant(
            "家里的心事，最怕总被顺到明天",
            "家里的心事，最怕总被顺到明天",
            "家里的心事，还是要在来得及的时候慢慢说开。",
        )
        == "household"
    )


def test_resolve_local_cover_scene_variant_recovers_household_from_responsibility_homecoming_markers() -> None:
    assert (
        workbench._resolve_local_cover_scene_variant(
            "肩上有责任的人，心里也要留一盏灯",
            "横向宽画幅构图，主体位于画面中部安全区，16:9 横版公众号封面，傍晚家中暖灯，桌边有水杯、账单和一碗热饭，有人推门回家，画面温暖克制，不出现聊天界面、输入框、消息气泡或可读屏幕文字。",
            "肩上有责任，心里也要留一盏灯。",
        )
        == "household"
    )


def test_resolve_local_cover_scene_variant_keeps_household_when_responsibility_prompt_mentions_document_bag() -> None:
    assert (
        workbench._resolve_local_cover_scene_variant(
            "家里一有事，你总会先把家稳住",
            "把家稳住的人，也该有人给他留一口热饭。",
            "横向宽画幅构图，16:9 横版公众号封面，真实摄影感，中国家庭夜晚场景，家庭纪实摄影。"
            "右侧是暖灯下的餐桌和入户一角：桌上有一碗热饭、保温杯、缴费单、孩子书包，门口是刚回家的中年人，外套还没脱，手里拿着资料袋或检查单，屋里有人正要起身接一下。",
        )
        == "household"
    )


def test_build_local_assets_fallback_scene_first_progression_household_uses_positive_recovery_packaging() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="那张检查单放在桌上时，她忽然不想再说自己没事",
        topic_title="那张检查单放在桌上时，她忽然不想再说自己没事",
        topic_angle="从夜里回家看见检查单、想问的话又往回收、餐桌前还是先维持平静这一段现场切入，写家里很多沉默是怎样慢慢压住真实靠近的。",
        draft_title="那张检查单放在桌上时，她忽然不想再说自己没事",
        draft_body_markdown=(
            "夜里回到家，餐桌上的检查单还没收。她把包放下，先去摸了一下水壶外壁，还是温的。\n\n"
            "孩子已经睡了，灯还留着一盏。她原本想问一句今天复查到底怎么说，可看见对方揉了揉眉心，话又先收了回去。\n\n"
            "很多家里的心事，不是不能说，只是总被那句“明天再说吧”轻轻按住了。"
        ),
    )

    assert assets["cover_copy"] == "家里的难，不怕摊开说，就怕一直各自忍着。"
    assert assets["social_teaser"].startswith("药盒和检查单就在桌上，谁都看见了，谁都先没提。")
    assert "大家都怕一开口，这个晚上会更沉" in assets["social_teaser"]
    assert "夜里家中餐桌或窗边现场" in assets["cover_prompt"]


def test_build_local_assets_fallback_scene_first_progression_household_recovers_household_specific_title_from_generic_scene_title() -> None:
    assets = workbench._build_local_assets_fallback(
        project_title="很多重要的话，不是忘了说，是总在那个刚好能开口的晚上又被压回去了",
        topic_title="很多重要的话，不是忘了说，是总在那个刚好能开口的晚上又被压回去了",
        topic_angle="从夜里回家、看见药盒和检查单、想问的话又往回收这一整段连续现场切入，写家里的重要话题怎样一次次输给先把场面维持住的本能。",
        draft_title="很多重要的话，不是忘了说，是总在那个刚好能开口的晚上又被压回去了",
        draft_body_markdown=(
            "夜里回到家，餐桌上的检查单还没收。她把包放下，先去摸了一下水壶外壁，还是温的。\n\n"
            "孩子已经睡了，灯还留着一盏。她原本想问一句今天复查到底怎么说，可看见对方揉了揉眉心，话又先收了回去。\n\n"
            "很多家里的心事，不是不能说，只是总被那句“明天再说吧”轻轻按住了。"
        ),
    )

    assert assets["recommended_title"] == "家里的心事，最怕总被顺到明天"
    assert assets["title_options"][0] == "家里的心事，最怕总被顺到明天"
    assert assets["cover_copy"] == "家里的难，不怕摊开说，就怕一直各自忍着。"


def test_build_local_publish_package_fallback_scene_first_transit_uses_distinct_abstract() -> None:
    assets = workbench.AssetItem(
        project_slug="scene-first-transit-publish",
        draft_version=1,
        version=1,
        title_options=["没问出口的那句话，最容易把关系拖远"],
        recommended_title="没问出口的那句话，最容易把关系拖远",
        cover_prompt="16:9横版公众号封面，雨后傍晚的出站口和摆渡车现场。",
        cover_copy="那句该问的话，别总留到车开以后。",
        social_teaser="她那句“最近有点忙”刚落下去，你就知道她不止这一句话。可摆渡车一到，今晚最该问的那一句，还是跟着风一起被你按了回去。",
        social_teaser_options=[
            "她那句“最近有点忙”刚落下去，你就知道她不止这一句话。可摆渡车一到，今晚最该问的那一句，还是跟着风一起被你按了回去。",
            "那句该问的话，别总留到车开以后。",
        ],
        cover_image_path="",
        cover_image_url="",
        created_at="2026-07-13T00:00:00Z",
        origin="generate",
        tone_profile_id=3,
        tone_profile_name="女性成长克制陪伴风",
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="没问出口的那句话，最容易把关系拖远",
        draft_body_markdown=(
            "雨刚停，出站口外的摆渡车还没来。她低头看着亮了又暗的手机，那句打到一半的话始终没有发出去。\n\n"
            "她抬手拢了拢围巾，只说这阵子事多。你听得出那句话后面还有东西，也看见她眼里的疲惫，可嘴边那句真正想问的，还是被你自己按住了。"
        ),
        assets=assets,
    )

    assert package["publish_lead"] == "她那句“最近有点忙”刚落下去，你就知道她不止这一句话。可摆渡车一到，今晚最该问的那一句，还是跟着风一起被你按了回去。"
    assert package["abstract"] == "很多走远，不是因为不在乎，而是两个人都把那句真话往后放。你肯多问一句，关系就可能少绕一段路。"
    assert package["editor_note"] == "这版重点就在那句没问出口的话，发布时别补太多解释，留一点空白更有劲。"
    assert package["abstract"] != package["publish_lead"]


def test_build_local_publish_package_fallback_scene_first_office_uses_positive_recovery_abstract() -> None:
    assets = workbench.AssetItem(
        project_slug="scene-first-office-publish",
        draft_version=1,
        version=1,
        title_options=["散会后才开口，位置就会慢慢往后退"],
        recommended_title="散会后才开口，位置就会慢慢往后退",
        cover_prompt="16:9横版公众号封面，清晨会议室或工位现场。",
        cover_copy="该说的时候开口，才不会总在散会以后后悔。",
        social_teaser="会已经散了，那页改过的方案还亮在屏幕上。真正让人难受的，不是没人点你名，是那句你明明该在当场说的话，最后又留给了自己。",
        social_teaser_options=[
            "会已经散了，那页改过的方案还亮在屏幕上。真正让人难受的，不是没人点你名，是那句你明明该在当场说的话，最后又留给了自己。",
            "该说的时候开口，才不会总在散会以后后悔。",
        ],
        cover_image_path="",
        cover_image_url="",
        created_at="2026-07-13T00:00:00Z",
        origin="generate",
        tone_profile_id=3,
        tone_profile_name="女性成长克制陪伴风",
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="散会后才开口，位置就会慢慢往后退",
        draft_body_markdown=(
            "周一早会开始前，她站在投影幕布旁，把昨晚改好的那页方案又往后翻了一遍。\n\n"
            "领导把杯子往桌边一放，话题就顺着旧方案往下走了。你昨晚改到很晚的那一页还停在屏幕上，可那个本来该接上的提醒，最后还是被你自己咽了回去。"
        ),
        assets=assets,
    )

    assert package["publish_lead"].startswith("会已经散了，那页改过的方案还亮在屏幕上。")
    assert package["abstract"] == "你不是没判断，只是总把场面放在前面。关键时刻肯开口，不是逞强，是把自己放回该在的位置。"
    assert "那句你明明该在当场说的话" in package["publish_lead"]
    assert all("现场切入" not in item and "写一个人怎样" not in item for item in package["intro_options"])
    assert package["editor_note"] == "这版现场感已经够了，发布时别把导语写太满，留一点会后回味就行。"
    assert package["abstract"] != package["publish_lead"]


def test_build_local_publish_package_fallback_scene_first_household_uses_positive_recovery_abstract() -> None:
    assets = workbench.AssetItem(
        project_slug="scene-first-household-publish",
        draft_version=1,
        version=1,
        title_options=["那张检查单放在桌上时，她忽然不想再说自己没事"],
        recommended_title="那张检查单放在桌上时，她忽然不想再说自己没事",
        cover_prompt="16:9横版公众号封面，夜里家中餐桌或窗边现场。",
        cover_copy="家里的难，不怕摊开说，就怕一直各自忍着。",
        social_teaser="药盒和检查单就在桌上，谁都看见了，谁都先没提。家里很多心事，不是没人想说，是大家都怕一开口，这个晚上会更沉。",
        social_teaser_options=[
            "药盒和检查单就在桌上，谁都看见了，谁都先没提。家里很多心事，不是没人想说，是大家都怕一开口，这个晚上会更沉。",
            "家里的难，不怕摊开说，就怕一直各自忍着。",
        ],
        cover_image_path="",
        cover_image_url="",
        created_at="2026-07-13T00:00:00Z",
        origin="generate",
        tone_profile_id=3,
        tone_profile_name="女性成长克制陪伴风",
    )

    package = workbench._build_local_publish_package_fallback(
        draft_title="那张检查单放在桌上时，她忽然不想再说自己没事",
        draft_body_markdown=(
            "夜里回到家，餐桌上的检查单还没收。她把包放下，先去摸了一下水壶外壁，还是温的。\n\n"
            "孩子已经睡了，灯还留着一盏。她原本想问一句今天复查到底怎么说，可看见对方揉了揉眉心，话又先收了回去。"
        ),
        assets=assets,
    )

    assert package["publish_lead"].startswith("药盒和检查单就在桌上，谁都看见了，谁都先没提。")
    assert "大家都怕一开口，这个晚上会更沉" in package["publish_lead"]
    assert package["abstract"] == "家里最怕的，不是遇到事，是大家都想体谅，结果谁都不肯先说。把心事说开，日子才真的稳得住。"
    assert package["editor_note"] == "这版已经有夜里的那口气了，发布时别往大道理上拔，让这个家的沉默自己说话。"
    assert package["abstract"] != package["publish_lead"]


def test_normalize_cover_prompt_keeps_phone_screen_away_from_camera() -> None:
    normalized = workbench._normalize_cover_prompt_layout(
        "竖版手机聊天界面作为主视觉，人物在看手机，手机背面也有聊天界面，双面手机，温暖现实感。"
    )

    assert "16:9" in normalized
    assert "横版公众号封面" in normalized
    assert "普通单屏手机" in normalized
    assert "手机背面没有屏幕" in normalized
    assert "手机背面或侧面朝向镜头" in normalized
    assert "屏幕不朝向镜头" in normalized
    assert "不出现聊天界面、输入框、消息气泡或可读屏幕文字" in normalized
    assert "竖版" not in normalized
    assert "双面手机" in normalized
    assert "手机背面也有聊天界面" not in normalized


def test_cover_refresh_updates_project_publish_artifacts_with_new_cover_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    topic_slug = "scene-first-transit-cover-refresh-topic"
    project_slug = "scene-first-transit-cover-refresh-project"
    normalized_cover_prompt = workbench._normalize_cover_prompt_layout(
        "16:9横版公众号封面，雨后傍晚的出站口和摆渡车现场，不要做纯色底大字卡，左侧留标题安全区。"
    )

    class FakeGenerator:
        @property
        def uses_custom_base_url(self) -> bool:
            return False

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            return b"refreshed-cover-binary"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            raise AssertionError("cover refresh path should reuse the latest publish package content")

    monkeypatch.setattr(workbench, "GENERATED_ASSETS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_slug,
                "",
                "manual",
                "",
                "没问出口的那句话，最容易把关系拖远",
                "从地铁口等车、看见不对劲却还是先没问、上车后话题彻底沉下去这一段连续现场切入。",
                "approved",
            ),
        )
        connection.execute(
            """
            INSERT INTO projects (slug, topic_slug, title, stage, owner)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                topic_slug,
                "没问出口的那句话，最容易把关系拖远",
                "assets_ready",
                "ops",
            ),
        )
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                1,
                1,
                "没问出口的那句话，最容易把关系拖远",
                (
                    "雨刚停，出站口外的摆渡车还没来。她低头看着亮了又暗的手机，那句打到一半的话始终没有发出去。\n\n"
                    "她抬手拢了拢围巾，只说这阵子事多。你听得出那句话后面还有东西，也看见她眼里的疲惫，可嘴边那句真正想问的，还是被你自己按住了。"
                ),
                118,
                "2026-07-13T00:00:00Z",
                "generate",
                3,
                "女性成长克制陪伴风",
            ),
        )
        connection.execute(
            """
            INSERT INTO assets (
                project_slug, draft_version, version, title_options, recommended_title, cover_prompt, cover_copy, social_teaser, social_teaser_options,
                cover_image_path, cover_image_url, created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                1,
                1,
                json.dumps(["没问出口的那句话，最容易把关系拖远"], ensure_ascii=False),
                "没问出口的那句话，最容易把关系拖远",
                normalized_cover_prompt,
                "有些距离，不是突然有的，是那句真话总被拖到最后。",
                "雨刚停，出站口外的摆渡车还没来。有些距离，不是突然有的，是那句该问的话总被拖到转身以后。",
                json.dumps(
                    [
                        "雨刚停，出站口外的摆渡车还没来。有些距离，不是突然有的，是那句该问的话总被拖到转身以后。",
                        "有些距离，不是突然有的，是那句真话总被拖到最后。",
                    ],
                    ensure_ascii=False,
                ),
                "old-cover.png",
                "/generated-assets/old-cover.png",
                "2026-07-13T00:01:00Z",
                "generate",
                3,
                "女性成长克制陪伴风",
            ),
        )
        connection.execute(
            """
            INSERT INTO publish_packages (
                project_slug, draft_version, assets_version, version, abstract, tags, publish_checklist, editor_note,
                publish_title, publish_lead, intro_options, markdown_path, markdown_url, manifest_path, manifest_url,
                status, review_comment, reviewed_by, reviewed_at, created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                1,
                1,
                1,
                "写那些不是突然走远的关系：很多沉默看似体谅，最后都会把靠近一点点往后拖。",
                json.dumps(["情绪共鸣", "重新出发"], ensure_ascii=False),
                json.dumps(
                    [
                        "核对标题与封面文案是否同一情绪主线",
                        "确认摘要、标签、导语和正文结论一致",
                        "检查配图、错别字和发布时间建议后再发布",
                    ],
                    ensure_ascii=False,
                ),
                "标题和导语已沿用当前素材主线，建议发布前顺一下首段节奏与摘要长短。",
                "没问出口的那句话，最容易把关系拖远",
                "雨刚停，出站口外的摆渡车还没来。有些距离，不是突然有的，是那句该问的话总被拖到转身以后。",
                json.dumps(
                    [
                        "雨刚停，出站口外的摆渡车还没来。有些距离，不是突然有的，是那句该问的话总被拖到转身以后。",
                        "有些距离，不是突然有的，是那句真话总被拖到最后。",
                    ],
                    ensure_ascii=False,
                ),
                "publish-v1.md",
                "/generated-assets/publish-v1.md",
                "publish-v1.json",
                "/generated-assets/publish-v1.json",
                "ready",
                None,
                None,
                None,
                "2026-07-13T00:02:00Z",
                "generate",
                3,
                "女性成长克制陪伴风",
            ),
        )
        connection.commit()

    asset = workbench.regenerate_cover_image(project_slug)
    package = workbench.build_publish_package(project_slug)

    assert asset.version == 2
    assert asset.origin == "cover_regeneration"
    assert Path(asset.cover_image_path).exists()
    assert asset.cover_image_url.endswith("-assets-v2.png")
    assert Path(asset.cover_image_path).read_bytes() == b"refreshed-cover-binary"

    assert package.assets_version == 2
    manifest = json.loads(Path(package.manifest_path).read_text(encoding="utf-8"))
    markdown = Path(package.markdown_path).read_text(encoding="utf-8")
    assert manifest["cover_image_url"] == asset.cover_image_url
    assert manifest["publish_lead"] == "雨刚停，出站口外的摆渡车还没来。有些距离，不是突然有的，是那句该问的话总被拖到转身以后。"
    assert manifest["abstract"] == "写那些不是突然走远的关系：很多沉默看似体谅，最后都会把靠近一点点往后拖。"
    assert markdown.startswith("# 没问出口的那句话，最容易把关系拖远")
    assert "\n\n有些距离，不是突然有的，是那句该问的话总被拖到转身以后。\n\n" in markdown
    assert "## 发布导语" not in markdown
    assert "## 导语候选" not in markdown
    assert "## 标题备选" not in markdown
    assert "## 封面文案" not in markdown
    assert "## 发布前检查清单" not in markdown


def test_generate_cover_image_file_surfaces_api_failure_in_api_only_mode(
    tmp_path: Path,
) -> None:
    class FakeGenerator:
        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            raise RuntimeError("force API-only failure in test")

    cover_file_path = tmp_path / "responsibility-cover.png"
    normalized_cover_prompt = "16:9 横版公众号封面，傍晚家中暖灯，桌边有水杯、账单和一碗热饭，有人推门回家。"

    with pytest.raises(HTTPException) as excinfo:
        workbench._generate_cover_image_file(
            generator=FakeGenerator(),
            project_slug="responsibility-cover-project",
            project_title="肩上有责任的人，心里也要留一盏灯",
            normalized_cover_prompt=normalized_cover_prompt,
            cover_copy="肩上有责任，心里也要留一盏灯。",
            cover_file_path=cover_file_path,
        )

    assert excinfo.value.status_code == 502
    assert "当前封面保持 API-only" in str(excinfo.value.detail)
    assert not cover_file_path.exists()


def test_generate_cover_image_file_passes_configured_request_budget_to_generator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(workbench.settings, "openai_image_generation_max_attempts", 3, raising=False)

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls = 0
            self.payloads: list[dict[str, object]] = []

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            self.calls += 1
            self.payloads.append(dict(payload))
            return b"final-cover"

    cover_file_path = tmp_path / "responsibility-cover-retry.png"
    generator = FakeGenerator()

    cover_result = workbench._generate_cover_image_file(
        generator=generator,
        project_slug="responsibility-cover-retry-project",
        project_title="肩上有责任的人，心里也要留一盏灯",
        normalized_cover_prompt="16:9 横版公众号封面，傍晚家中暖灯，桌边有热饭和资料袋。",
        cover_copy="把家稳住的人，也该有人给他留一口热饭。",
        cover_file_path=cover_file_path,
    )

    assert generator.calls == 1
    assert generator.payloads[0]["image_generation_max_attempts"] == 3
    assert cover_result.path.endswith("responsibility-cover-retry.png")
    assert cover_result.url.endswith("/responsibility-cover-retry.png")
    assert cover_result.route_label is None
    assert cover_file_path.read_bytes() == b"final-cover"


def test_generate_cover_image_file_returns_route_diagnostics_when_generator_exposes_them(tmp_path: Path) -> None:
    class FakeGenerator:
        def generate_cover_image_with_route_info(self, payload: dict[str, object]):
            return (
                b"cover-binary",
                {
                    "label": "fallback",
                    "model": "fallback-image-model",
                    "base_url": "https://fallback-image.example/v1",
                },
            )

    cover_file_path = tmp_path / "route-diagnostics-cover.png"

    cover_result = workbench._generate_cover_image_file(
        generator=FakeGenerator(),
        project_slug="route-diagnostics-project",
        project_title="把家稳住的人，也该被好好接住",
        normalized_cover_prompt="16:9 横版公众号封面，真实家庭夜晚场景。",
        cover_copy="把家稳住的人，也该有人给他留一盏灯。",
        cover_file_path=cover_file_path,
    )

    assert cover_result.path.endswith("route-diagnostics-cover.png")
    assert cover_result.url.endswith("/route-diagnostics-cover.png")
    assert cover_result.route_label == "fallback"
    assert cover_result.route_model == "fallback-image-model"
    assert cover_result.route_base_url == "https://fallback-image.example/v1"
    assert cover_file_path.read_bytes() == b"cover-binary"


def test_generate_cover_image_file_surfaces_upstream_account_pool_failure_in_api_only_mode(
    tmp_path: Path,
) -> None:
    class FakeGenerator:
        last_cover_image_route_info = {
            "label": "primary",
            "model": "gpt-image-2",
            "base_url": "https://i.ixiu.one/v1",
        }

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            raise RuntimeError("503 upstream_error: No available compatible accounts")

    cover_file_path = tmp_path / "api-only-cover.png"
    with pytest.raises(HTTPException) as excinfo:
        workbench._generate_cover_image_file(
            generator=FakeGenerator(),
            project_slug="api-only-cover-project",
            project_title="把家稳住的人，也该被好好接住",
            normalized_cover_prompt="16:9 横版公众号封面，真实家庭夜晚场景，玄关暖灯，人物刚回到家。",
            cover_copy="别让真实封面，被一张本地图悄悄替掉。",
            cover_file_path=cover_file_path,
        )

    assert excinfo.value.status_code == 502
    assert "当前图片 API 暂无可用账号" in str(excinfo.value.detail)
    assert "不会改走本地兜底" in str(excinfo.value.detail)
    assert "No available compatible accounts" in str(excinfo.value.detail)
    assert getattr(excinfo.value, "cover_image_route_label", None) == "primary"
    assert getattr(excinfo.value, "cover_image_route_model", None) == "gpt-image-2"
    assert getattr(excinfo.value, "cover_image_route_base_url", None) == "https://i.ixiu.one/v1"
    assert not cover_file_path.exists()


def test_generate_assets_preserves_text_and_blocks_publish_when_api_only_cover_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    topic_response = client.post(
        "/api/topics",
        json={
            "slug": "api-only-cover-failure-topic",
            "title": "把家稳住的人，也该被好好接住",
            "angle": "从深夜回家、先看见灯亮着这一幕切入，写责任背后也需要被接住。",
            "source_type": "manual",
            "source_ref_slug": "",
        },
    )
    assert topic_response.status_code == 201

    project_response = client.post(
        "/api/topics/api-only-cover-failure-topic/create-project",
        json={
            "slug": "api-only-cover-failure-project",
            "title": "api only cover failure 项目",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201

    class FakeGenerator:
        image_uses_custom_base_url = True
        last_cover_image_route_info = {
            "label": "primary",
            "model": "gpt-image-2",
            "base_url": "https://i.ixiu.one/v1",
        }

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "那天夜里，他推门回家时，先看到的是餐桌上那盏还亮着的灯。",
                "outline_body": "1. 回家那一刻\n2. 责任怎样落在身上\n3. 被接住的意义",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {
                "title": "把家稳住的人，也该被好好接住",
                "body_markdown": "# 把家稳住的人，也该被好好接住\n\n他回到家时，灯还亮着，饭也还热着。",
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["把家稳住的人，也该被好好接住"],
                "recommended_title": "把家稳住的人，也该被好好接住",
                "cover_prompt": "16:9 横版公众号封面，真实家庭夜晚场景，人物刚回到家，暖灯，餐桌，生活抓拍感。",
                "cover_copy": "那个总说没事的人，也该有人给他留一盏灯。",
                "social_teaser": "很多时候，真正撑住一个家的，不只是责任，还有那个回到家后终于能松一口气的人。",
            }

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            raise RuntimeError("503 upstream_error: No available compatible accounts")

    monkeypatch.setattr(workbench, "GENERATED_ASSETS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    assert client.post("/api/projects/api-only-cover-failure-project/generate-outline").status_code == 201
    assert client.post("/api/projects/api-only-cover-failure-project/generate-draft").status_code == 201

    assets = workbench.generate_assets("api-only-cover-failure-project")

    assert assets.recommended_title == "把家稳住的人，也该被好好接住"
    assert assets.social_teaser.startswith("很多时候")
    assert assets.cover_image_path == ""
    assert assets.cover_image_url == ""
    assert assets.cover_image_status == "pending"
    assert "当前图片 API 暂无可用账号" in str(assets.cover_image_error)
    assert "不会改走本地兜底" in str(assets.cover_image_error)
    assert assets.cover_image_route_label == "primary"
    assert assets.cover_image_route_model == "gpt-image-2"
    assert assets.cover_image_route_base_url == "https://i.ixiu.one/v1"

    detail = workbench.get_project_detail("api-only-cover-failure-project")
    assert detail.assets is not None
    assert detail.assets.version == assets.version
    assert detail.assets.cover_image_status == "pending"
    assert detail.project.stage == "assets_pending_cover"
    assert detail.project.current_chain_state == "cover_pending"
    assert detail.project.next_required_step == "regenerate_cover_image"

    with pytest.raises(HTTPException) as excinfo:
        workbench.build_publish_package("api-only-cover-failure-project")
    assert excinfo.value.status_code == 409
    assert "封面图片仍待 API 补齐" in str(excinfo.value.detail)

    class RecoveredGenerator(FakeGenerator):
        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            return b"recovered-api-cover"

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: RecoveredGenerator(), raising=False)
    recovered_assets = workbench.regenerate_cover_image("api-only-cover-failure-project")
    assert recovered_assets.version == assets.version + 1
    assert recovered_assets.cover_image_status == "ready"
    assert recovered_assets.cover_image_error is None
    assert Path(recovered_assets.cover_image_path).read_bytes() == b"recovered-api-cover"

    recovered_detail = workbench.get_project_detail("api-only-cover-failure-project")
    assert recovered_detail.project.stage == "assets_ready"
    assert recovered_detail.project.current_chain_state == "assets_ready"
    assert recovered_detail.project.next_required_step == "build_publish_package"


def test_background_task_detail_surfaces_cover_route_error_context_for_failed_cover_regeneration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_slug = "background-cover-route-project"
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "background-cover-route-topic",
                "background-cover-route-topic",
                "manual",
                "",
                "别让封面失败变成一句模糊的报错",
                "从封面失败时的信息透明度切入，强调链路可见性。",
                "drafting",
            ),
        )
        connection.execute(
            """
            INSERT INTO projects (slug, topic_slug, title, stage, owner)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                "background-cover-route-topic",
                "别让封面失败变成一句模糊的报错",
                "assets_ready",
                "editorial",
            ),
        )
        connection.execute(
            """
            INSERT INTO assets (
                project_slug, draft_version, version, title_options, recommended_title, cover_prompt, cover_copy, social_teaser, social_teaser_options,
                cover_image_path, cover_image_url, created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                1,
                1,
                json.dumps(["别让封面失败变成一句模糊的报错"], ensure_ascii=False),
                "别让封面失败变成一句模糊的报错",
                "16:9 横版公众号封面，夜晚书桌，真实生活感。",
                "封面失败了，也该知道是哪条链路出了问题。",
                "当封面生成失败时，最好别只剩一句重试，而是把真正的链路说清楚。",
                json.dumps(["当封面生成失败时，最好别只剩一句重试，而是把真正的链路说清楚。"], ensure_ascii=False),
                "old-cover.png",
                "/generated-assets/old-cover.png",
                "2026-07-17T00:00:00Z",
                "generate",
                None,
                None,
            ),
        )
        connection.commit()

    class FakeGenerator:
        last_cover_image_route_info = {
            "label": "primary",
            "model": "gpt-image-2",
            "base_url": "https://i.ixiu.one/v1",
        }

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            raise RuntimeError("503 upstream_error: No available compatible accounts")

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)
    monkeypatch.setattr(workbench, "_should_retry_cover_image_generation_error", lambda exc: False, raising=False)

    submission_response = client.post(f"/api/projects/{project_slug}/regenerate-cover-image")
    assert submission_response.status_code == 202

    task_payload = wait_for_background_task(submission_response.json()["task_id"])

    assert task_payload["status"] == "failed"
    assert task_payload["result"] is None
    assert "当前图片 API 暂无可用账号" in task_payload["error"]
    assert task_payload["error_context"] == {
        "type": "HTTPException",
        "status_code": 502,
        "detail": task_payload["error"],
        "cover_image_route_label": "primary",
        "cover_image_route_model": "gpt-image-2",
        "cover_image_route_base_url": "https://i.ixiu.one/v1",
        "fallback_account_pool_diagnosis_status": "not_configured",
        "fallback_account_pool_diagnosis_label": "未形成第二套上游",
        "fallback_account_pool_diagnosis_note": "当前还没有配置 fallback，所以主路由一旦因为账号池问题失败，系统没有第二套图片上游可以尝试。",
    }


def test_generate_cover_image_file_shortens_retry_window_for_custom_image_provider(
    tmp_path: Path,
) -> None:
    class FakeGenerator:
        image_uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls = 0

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            self.calls += 1
            raise RuntimeError("503 upstream_error: image provider temporarily unavailable")

    cover_file_path = tmp_path / "custom-image-provider-cover.png"
    generator = FakeGenerator()

    with pytest.raises(HTTPException) as excinfo:
        workbench._generate_cover_image_file(
            generator=generator,
            project_slug="custom-image-provider-project",
            project_title="家里一有事，你总会先把家稳住",
            normalized_cover_prompt="16:9 横版公众号封面，真实摄影感，中国家庭夜晚场景，右侧是暖灯下的餐桌和入户一角。",
            cover_copy="把家稳住的人，也该有人给他留一口热饭。",
            cover_file_path=cover_file_path,
        )

    assert generator.calls == 1
    assert excinfo.value.status_code == 502
    assert "API-only" in str(excinfo.value.detail)
    assert not cover_file_path.exists()


def test_cover_image_deadline_respects_configured_image_timeout_for_custom_provider() -> None:
    class FakeGenerator:
        image_uses_custom_base_url = True
        _image_request_timeout_seconds = 240.0

    assert workbench._resolve_cover_image_call_deadline_seconds(FakeGenerator()) == 240.0


def test_generate_cover_image_file_surfaces_timeout_after_cover_call_deadline_exceeded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGenerator:
        image_uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls = 0

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            import time

            self.calls += 1
            time.sleep(0.2)
            return b"too-late"
    monkeypatch.setattr(workbench, "_resolve_cover_image_call_deadline_seconds", lambda _generator: 0.01)

    cover_file_path = tmp_path / "cover-call-deadline.png"
    generator = FakeGenerator()

    with pytest.raises(HTTPException) as excinfo:
        workbench._generate_cover_image_file(
            generator=generator,
            project_slug="cover-call-deadline-project",
            project_title="家里一有事，你总会先把家稳住",
            normalized_cover_prompt="16:9 横版公众号封面，真实摄影感，中国家庭夜晚场景。",
            cover_copy="把家稳住的人，也该有人给他留一口热饭。",
            cover_file_path=cover_file_path,
        )

    assert generator.calls == 1
    assert excinfo.value.status_code == 502
    assert "API-only" in str(excinfo.value.detail)
    assert not cover_file_path.exists()


def test_build_publish_markdown_filters_packaging_instruction_intro_candidates() -> None:
    assets = workbench.AssetItem(
        project_slug="household-publish-markdown-filter",
        draft_version=1,
        version=1,
        title_options=["家里的心事，最怕总被顺到明天"],
        recommended_title="家里的心事，最怕总被顺到明天",
        cover_prompt="16:9横版公众号封面，夜里家中餐桌或窗边现场。",
        cover_copy="家里的心事，还是要在来得及的时候慢慢说开。",
        social_teaser="夜里回到家，餐桌上的检查单还没收。你明明有话想问，最后还是先替这个晚上留了安静。",
        social_teaser_options=[
            "夜里回到家，餐桌上的检查单还没收。你明明有话想问，最后还是先替这个晚上留了安静。",
            "围绕《那张检查单放在桌上时，她忽然不想再说自己没事》对应的现实处境切入，重建新的具体入口，把主线不是忍耐，而是家里很多沉默，都是先想稳住这个晚上。说得更贴近真人表达。",
        ],
        cover_image_path="",
        cover_image_url="/generated-assets/demo-household.png",
        created_at="2026-07-14T00:00:00Z",
        origin="generate",
        tone_profile_id=3,
        tone_profile_name="女性成长克制陪伴风",
    )

    markdown = workbench._build_publish_markdown(
        project_title="家里的心事，最怕总被顺到明天",
        draft_title="家里的心事，最怕总被顺到明天",
        draft_body="夜里回到家，餐桌上的检查单还没收。",
        assets=assets,
        abstract="很多家里的事，不是不能说，是总被一句“以后再说”轻轻压回去。把心事慢慢说开，一个家才会真的稳下来。",
        tags=["家庭沟通", "家里心事"],
        publish_checklist=["核对情绪主线"],
        editor_note="这版已经有夜里的那口气了，发布时别往大道理上拔，让这个家的沉默自己说话。",
        publish_title="家里的心事，最怕总被顺到明天",
        publish_lead="夜里回到家，餐桌上的检查单还没收。你明明有话想问，最后还是先替这个晚上留了安静。",
        intro_options=list(assets.social_teaser_options),
        tone_profile_name="女性成长克制陪伴风",
    )

    assert "围绕《那张检查单放在桌上时，她忽然不想再说自己没事》" not in markdown
    assert "更贴近真人表达" not in markdown
    assert markdown.startswith("# 家里的心事，最怕总被顺到明天")
    assert "\n\n你明明有话想问，最后还是先替这个晚上留了安静。\n\n" in markdown
    assert "## 发布导语" not in markdown
    assert "## 导语候选" not in markdown


def test_build_local_tracked_article_fallback_supportive_appreciation_avoids_strategy_sentence_leak() -> None:
    payload = {
        "source_type": "tracked_article",
        "topic_title": "总把别人感受放在前面的人，其实最该被人好好珍惜",
        "topic_angle": "从一个人总会先把场面放软、先顾别人感受写起，写这份柔软为什么常被误读成没脾气；也写真正难得的，是有人看懂它、接住它，并认真回应。",
        "body_markdown": (
            "这样的人，心很软，也很重感情。"
            "他们不舍得让身边的人受伤，处处照顾着别人的感受。"
            "因为这样的人，一生难遇。"
        ),
        "strategy_card": {
            "structure_mode": "supportive_appreciation",
            "positive_direction": "结尾回到珍惜、被珍惜和关系里的尊重感，不要把柔软写成一味受委屈。",
        },
        "problem_brief": {
            "theme_axis": "主线是柔软为什么总被误读，又为什么真正愿意包容、珍惜和接住这份柔软的人格外难得。",
            "core_conflict": "真正容易被错过的，不是这样的人吃了点亏，而是很多人把这份明明拎得清、却还是愿意温柔待人的珍贵，当成了理所当然。",
        },
    }

    outline = workbench._build_local_tracked_article_outline_fallback(payload)
    assert "从一个人总会先把场面放软" not in outline["outline_body"]
    assert "真正容易被错过的，不是这样的人吃了点亏" not in outline["outline_body"]
    assert "有些人每次都会先把场面放软" in outline["outline_body"]
    assert "越是总替别人留余地的人" in outline["outline_body"]

    title, body_markdown = workbench._build_local_tracked_article_draft_fallback({**payload, "outline": outline})
    assert title == "总把别人感受放在前面的人，其实最该被人好好珍惜"
    assert "从一个人总会先把场面放软" not in body_markdown
    assert "真正容易被错过的，不是这样的人吃了点亏" not in body_markdown
    assert "好说话" not in body_markdown
    assert "先看看那份总替别人留余地的习惯" not in body_markdown
    assert "有些人每次都会先把场面放软，不想让在乎的人太难堪。" not in body_markdown
    assert "性子柔的人也会有脾气。" in body_markdown
    assert "只是话到嘴边，她会先想一想：这句话说重了，对方会不会难过。" in body_markdown
    assert "她肯体谅，不代表她什么都不懂；她愿意把话放软，也不代表她不会受伤。" in body_markdown
    assert "事情未必会当场闹大，可那份重量会一点点落进日常里。" not in body_markdown
    assert "可这份柔软一旦被当成理所当然，人就会慢慢失望。" in body_markdown
    assert "能看懂这份心软，本来就很难。" in body_markdown
    assert "柔软被珍惜以后，会长出更踏实的爱。" in body_markdown
    assert "温柔到最后，看的是分寸，也看回应。" in body_markdown
    paragraphs = [part for part in body_markdown.split("\n\n") if part.strip()]
    assert len(paragraphs) >= 11
    assert len(body_markdown) >= 650
    assert not re.search(r"不是[^。！？!?\n]{1,40}(?:而是|也不是)", body_markdown)
    for forbidden in ("耗空", "胃口", "睡眠", "磨钝", "长期亏空", "身体先开始交代"):
        assert forbidden not in body_markdown


def test_build_local_tracked_article_fallback_supportive_appreciation_uses_reference_warmth_profile() -> None:
    source_body = (
        "有一种人，习惯了燃烧自己，去照亮别人。"
        "你对他好，他会对你更好；你给他温暖，他会回馈给你更多的温暖。"
        "哪怕你无意中伤害了他，只要你真诚的道歉，他就会大方的原谅你。"
        "心软的人并不傻，他们的心里比谁都拎得清。不去计较，是因为心里在乎，不想与爱的人争辩输赢、对错和得失。"
        "心软的人，知道一生漫长，时有暴雨。而他们，愿意穿过无尽暴雨，去拥抱你。"
        "在他们的眼里，生活不需要太复杂，只要四季平凡，身边有你就好。"
        "如果你身边有这样一个心软的人，请你一定要牵紧他的手。因为这样的人，一生难遇。"
    )
    payload = {
        "source_type": "tracked_article",
        "article_title": "心软的人，一生难遇",
        "topic_title": "总把别人感受放在前面的人，其实最该被人好好珍惜",
        "topic_angle": "从心软的人总会回馈温暖、愿意包容写起，写这样的人为什么拎得清却仍值得被珍惜。",
        "body_markdown": source_body,
        "strategy_card": {
            "structure_mode": "supportive_appreciation",
            "positive_direction": "结尾回到珍惜、被珍惜和关系里的尊重感，不要把柔软写成一味受委屈。",
        },
    }

    outline = workbench._build_local_tracked_article_outline_fallback(payload)
    title, body_markdown = workbench._build_local_tracked_article_draft_fallback({**payload, "outline": outline})

    assert title == "总把别人感受放在前面的人，其实最该被人好好珍惜"
    assert body_markdown.startswith("他其实什么都懂，只是每次轮到在乎的人，还是会先把那点难受往回收一收。")
    assert "心软的人，往往反应更快。" in body_markdown
    assert "谁是真心，谁在敷衍" in body_markdown
    assert "他不急着计较，是因为心里有判断" in body_markdown
    assert "他递出来的，是一份有分寸的在乎，不是随手就会给谁的好脾气。" in body_markdown
    assert "明明已经有点难受了，对方把歉意说出口时" not in body_markdown
    assert "一句道歉真正有分量的地方" not in body_markdown
    assert not re.search(r"不是[^。！？!?\n]{1,40}(?:而是|也不是)", body_markdown)
    paragraphs = [part for part in body_markdown.split("\n\n") if part.strip()]
    assert len(paragraphs) >= 9
    assert max(len(part) for part in paragraphs) <= 90
    assert len(body_markdown) >= 450
    for forbidden in ("耗空", "胃口", "睡眠", "磨钝", "长期亏空", "身体先开始交代"):
        assert forbidden not in body_markdown


def test_build_local_tracked_article_fallback_supportive_appreciation_uses_reference_clear_eyed_opening() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "心软的人，一生难遇",
        "topic_title": "总把别人感受放在前面的人，其实最该被人好好珍惜",
        "topic_angle": "从心软的人并不傻、只是总把在乎摆在前面写起，写这份柔软为什么更该被珍惜。",
        "reference_article_body_markdown": (
            "心软的人并不傻，他们的心里比谁都拎得清。"
            "不去计较，是因为心里在乎，不想与爱的人争辩输赢、对错和得失。"
        ),
        "outline": {
            "hook": "她顺手让了一步、先顾了别人感受，结果又被当成理所当然的那一下。",
            "outline_body": "1. 柔软不是迟钝\n2. 真正在乎的人会先放软语气\n3. 被珍惜过的温柔会长成更稳的爱",
        },
        "strategy_card": {"structure_mode": "supportive_appreciation"},
    }

    title, body_markdown = workbench._build_local_tracked_article_draft_fallback(payload)

    assert title == "总把别人感受放在前面的人，其实最该被人好好珍惜"
    assert body_markdown.startswith(
        (
            "他其实什么都懂，只是每次轮到在乎的人，还是会先把那点难受往回收一收。",
            "很多事他不是没看出来，只是关系摆在面前时，他总习惯先把语气放软。",
        )
    )
    assert "她顺手让了一步、先顾了别人感受，结果又被当成理所当然的那一下。" not in body_markdown.split("\n\n")[0]

    assets_payload = workbench._build_local_assets_fallback(
        project_title=title,
        topic_title=title,
        topic_angle=str(payload["topic_angle"]),
        draft_title=title,
        draft_body_markdown=body_markdown,
    )
    assert assets_payload["cover_copy"] == "心软的人，往往看得很清，也把情分看得很重。"
    assert assets_payload["social_teaser"] in {
        "他其实什么都懂，只是每次轮到在乎的人，还是会先把那点难受往回收一收。他看得清，也愿意把情分放在前面。",
        "很多事他不是没看出来，只是关系摆在面前时，他总习惯先把语气放软。他看得清，也愿意把情分放在前面。",
    }
    assert "她看得清，也愿意把情分放在前面。" not in assets_payload["social_teaser"]

    assets = workbench.AssetItem(
        project_slug="supportive-warmth-project",
        draft_version=1,
        version=1,
        title_options=list(assets_payload["title_options"]),
        recommended_title=str(assets_payload["recommended_title"]),
        cover_prompt=str(assets_payload["cover_prompt"]),
        cover_copy=str(assets_payload["cover_copy"]),
        social_teaser=str(assets_payload["social_teaser"]),
        social_teaser_options=list(assets_payload["social_teaser_options"]),
        cover_image_path="",
        cover_image_url="",
        created_at="2026-07-12T00:00:00Z",
    )
    package = workbench._build_local_publish_package_fallback(
        draft_title=title,
        draft_body_markdown=body_markdown,
        assets=assets,
    )
    assert "看得清" in package["publish_lead"]
    assert "敷衍" not in package["publish_lead"]
    assert any(fragment in package["publish_lead"] for fragment in ("放软", "留一点余地", "关系"))
    assert "吵完" not in package["publish_lead"]
    assert "冷气" not in package["publish_lead"]


def test_assets_and_publish_generation_receive_strategy_bundle_for_tracked_article_project(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {
                "hook": "先从年中那一下想给自己打分的冲动切入",
                "outline_body": "1. 阶段回望里的自责\n2. 误把遗憾都算成失败\n3. 被支撑托住后继续往前",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {
                "title": "翻回年初那页计划时，先别忙着给这半年打分",
                "body_markdown": "# 标题\n\n很多人一到年中，不是在复盘，而是在清算自己。",
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("assets", payload))
            return {
                "title_options": ["翻到年中清单时，别把几种遗憾算成同一种失败"],
                "recommended_title": "翻到年中清单时，别把几种遗憾算成同一种失败",
                "cover_prompt": "21:9 横版公众号头图，年中回望，温暖现实感",
                "cover_copy": "这半年没按你想的那样来，也不代表你白走了一程",
                "social_teaser": "很多人一到年中，不是在复盘，而是在清算自己。",
                "social_teaser_options": ["导语一", "导语二", "导语三"],
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("publish", payload))
            return {
                "abstract": "写阶段回望里的误判，以及人怎样重新接纳自己。",
                "tags": ["阶段回望", "重新出发"],
                "editor_note": "重点是把年中自责拆开，不是继续放大失败感。",
                "publish_title": "翻到年中清单时，别把几种遗憾算成同一种失败",
                "publish_lead": "很多人一到年中，不是在复盘，而是在清算自己。",
                "intro_options": ["很多人一到年中，不是在复盘，而是在清算自己。"],
            }

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "halfyear-packaging-article",
            "source_name": "手动录入",
            "title": "下半年，愿你所有的努力不被辜负",
            "url": "https://example.com/halfyear-packaging-article",
            "author": "未知",
            "summary": "文章围绕半年节点上的回望、自责、遗憾安放和重新出发，不是泛心安稿。",
            "body_markdown": (
                "过去的这半年，你过得好吗？年初定下的目标又实现了多少呢？\n\n"
                "如果事与愿违，请一定相信是上天另有安排。\n\n"
                "做好眼前事，珍惜身边人。每一段人生，都值得全力以赴。"
            ),
            "structure_notes": "先写半年节点上的自我盘点，中段写遗憾与支撑，结尾回到接纳阶段和继续往前。",
            "tags": ["上半年", "下半年", "阶段回望", "重新出发"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/halfyear-packaging-article/to-topic",
        json={
            "slug": "halfyear-packaging-topic",
            "title": "这半年没按你想的那样来，也不代表你白走了一程",
            "angle": "从阶段节点上的自我清算切入，写人怎样重新安放遗憾、看见支撑，继续往前。",
        },
    )
    assert create_topic.status_code == 201

    create_project = client.post(
        "/api/topics/halfyear-packaging-topic/create-project",
        json={"slug": "halfyear-packaging-project", "title": "半年回望包装链路测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(
        workbench,
        "_should_use_tracked_article_strategy_first_draft_mode",
        lambda payload, *, is_polish_mode: False,
    )

    strategy_response = client.post("/api/projects/halfyear-packaging-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    adopt_response = client.post("/api/projects/halfyear-packaging-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200

    outline_response = client.post("/api/projects/halfyear-packaging-project/generate-outline")
    assert outline_response.status_code == 201
    draft_response = client.post("/api/projects/halfyear-packaging-project/generate-draft")
    assert draft_response.status_code == 201
    assets_response = client.post("/api/projects/halfyear-packaging-project/generate-assets")
    assert assets_response.status_code == 201
    publish_response = client.post("/api/projects/halfyear-packaging-project/build-publish-package")
    assert publish_response.status_code == 201

    assets_payload = next(payload for call_type, payload in fake_generator.calls if call_type == "assets")
    publish_payload = next(payload for call_type, payload in fake_generator.calls if call_type == "publish")

    assert assets_payload["source_type"] == "tracked_article"
    assert assets_payload["reference_article_hidden"] is True
    assert assets_payload["problem_brief"]["clarified_problem"]
    assert assets_payload["strategy_card"]["structure_mode"] == "inner_settlement"
    assert assets_payload["benchmarks"]
    assert assets_payload["benchmarks"][0]["borrow_focus"]

    assert publish_payload["source_type"] == "tracked_article"
    assert publish_payload["reference_article_hidden"] is True
    assert publish_payload["problem_brief"]["clarified_problem"]
    assert publish_payload["strategy_card"]["structure_mode"] == "inner_settlement"
    assert publish_payload["benchmarks"]
    assert publish_payload["assets"]["recommended_title"] == "翻到年中清单时，别把几种遗憾算成同一种失败"


def test_database_file_created_for_persistent_store() -> None:
    db_path = Path("C:/tmp/gankaigc-wechat-workbench.db")
    assert db_path.exists()
