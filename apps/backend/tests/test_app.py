from __future__ import annotations

from pathlib import Path
import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

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

    response = client.post("/api/tracked-articles/happiness-release-reroute/generate-topic")
    assert response.status_code == 201
    payload = response.json()

    assert "坏关系" not in payload["title"]
    assert "沉没成本" not in payload["title"]
    assert "幸福" in payload["title"] or "放下" in payload["title"]
    assert "坏关系" not in payload["angle"]
    assert "沉没成本" not in payload["angle"]
    assert "放手" in payload["angle"] or "不再强求" in payload["angle"] or "已经拥有" in payload["angle"]


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
                "tags": ["关系修复", "沟通节奏", "饭桌场景"],
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    enrich_response = client.post("/api/tracked-articles/repair-over-dinner/enrich-metadata")
    assert enrich_response.status_code == 200
    payload = enrich_response.json()
    assert payload["slug"] == "repair-over-dinner"
    assert payload["author"] == "晚舟"
    assert payload["summary"] == "从一顿没说破的晚饭切入，拆开关系缓和时真正起作用的顺序。"
    assert payload["structure_notes"] == "生活场景起笔，接着回看情绪卡点，最后落到能执行的表达动作。"
    assert payload["tags"] == ["关系修复", "沟通节奏", "饭桌场景"]

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    tracked_article = next(article for article in list_response.json() if article["slug"] == "repair-over-dinner")
    assert tracked_article["author"] == "晚舟"
    assert tracked_article["summary"] == "从一顿没说破的晚饭切入，拆开关系缓和时真正起作用的顺序。"
    assert tracked_article["structure_notes"] == "生活场景起笔，接着回看情绪卡点，最后落到能执行的表达动作。"
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
                summary="原始摘要还比较粗。",
                body_markdown="先写无力感，再回到能量耗尽这件事本身。\n\n最后才谈能做的那一步。",
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
                "tags": ["关系修复", "能量耗尽", "公众号参考"],
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    enrich_response = client.post("/api/tracked-articles/wechat-import-enrich-target/enrich-metadata")
    assert enrich_response.status_code == 200
    payload = enrich_response.json()
    assert payload["source_kind"] == "wechat_mp_import"
    assert payload["author"] == "冷爱"
    assert payload["summary"] == "从关系里的无力感切入，把问题落到精力透支而非方法缺失。"
    assert payload["structure_notes"] == "先写卡住感，再拆能量缺口，最后回到现实动作。"
    assert payload["tags"] == ["关系修复", "能量耗尽", "公众号参考"]
    assert payload["body_source"] == "content_noencode"

    assert len(fake_generator.calls) == 1
    _, call_payload = fake_generator.calls[0]
    assert call_payload["source_kind"] == "wechat_mp_import"
    assert call_payload["author"] == "冷爱"
    assert call_payload["summary"] == "原始摘要还比较粗。"
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

    assert len(fake_generator.calls) == 2
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

    draft_call_type, draft_payload = fake_generator.calls[1]
    assert draft_call_type == "draft"
    assert draft_payload["source_type"] == "tracked_article"
    assert draft_payload["reference_article_hidden"] is True
    assert "reference_article_title" not in draft_payload
    assert "reference_article_summary" not in draft_payload
    assert "reference_article_structure_notes" not in draft_payload
    assert "reference_article_tags" not in draft_payload
    assert draft_payload["strategy_card"]["version"] == 1
    assert draft_payload["problem_brief"]["version"] == 1


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
    assert "低声量联系" in combined or "普通安排" in combined or "在场动作" in combined
    assert "关系余波" in combined or "延迟代价" in combined
    assert "长期体谅" not in combined
    assert "继续等你的心气" not in combined
    assert "关系坏在冲突" not in combined
    assert "长期体谅" in constraints_text
    assert "吃饭、散步" not in payload["problem_brief"]["problem_statement_markdown"]
    assert "陪伴家人的具体场景" not in payload["problem_brief"]["problem_statement_markdown"]
    assert "伴侣、孩子、父母" not in payload["problem_brief"]["problem_statement_markdown"]


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
    assert "关系余波" in combined or "延迟代价" in combined
    assert "没意思" not in combined
    assert "空心感" not in combined
    assert "情绪托底" not in combined
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
    assert "多数段落以 1 到 3 句为主" in jinwan_profile["paragraph_rhythm"]
    assert "行动落点" in jinwan_profile["paragraph_rhythm"]
    assert "开头用直接问题、现实接口或一句共鸣判断迅速点题" in jinwan_profile["default_polish_instruction"]
    assert "多数段落控制在 1 到 3 句" in jinwan_profile["default_polish_instruction"]
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
    assert "办公室倦怠后，先把自己的电量接回来" in markdown_text
    assert "风格：" in markdown_text
    assert "女性成长克制陪伴风" in markdown_text
    manifest_text = Path(publish_package["manifest_path"]).read_text(encoding="utf-8")
    assert "情绪恢复" in manifest_text
    assert "publish_checklist" in manifest_text
    assert "核对标题与封面文案是否同一情绪主线" in manifest_text
    assert "tone_profile_name" in manifest_text
    assert "女性成长克制陪伴风" in manifest_text

    publish_file_response = client.get(publish_package["markdown_url"])
    assert publish_file_response.status_code == 200
    assert "办公室倦怠后，先把自己的电量接回来" in publish_file_response.text
    assert "女性成长克制陪伴风" in publish_file_response.text

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
    assert "21:9" in fake_generator.calls[3][1]["cover_prompt"]
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
    assert "compact_polish_mode" not in polished_payload


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

    assert len(initial_payloads) >= 2
    assert polished_payloads

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
    assert compact_initial_payloads

    for payload in polished_payloads:
        assert_tracked_article_strategy_bundle(payload)
        assert payload["allow_structure_recomposition"] is True
        assert payload["preserve_structure_anchors"] is False
        assert "去模板化重写" in str(payload["polish_instruction"] or "")


def test_generate_draft_auto_polish_retries_when_ai_flavor_still_remains(monkeypatch) -> None:
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
            if not instruction and payload.get("compact_strategy_mode"):
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
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)

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


def test_generate_initial_draft_candidates_falls_back_to_full_branch_when_compact_branch_times_out(
    caplog,
) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(dict(payload))
            if payload.get("compact_strategy_mode"):
                if payload.get("timeout_recovery_mode"):
                    return {
                        "title": "救援分支稿",
                        "body_markdown": "救援分支正文",
                    }
                raise TimeoutError("Request timed out.")
            return {
                "title": "常规分支稿",
                "body_markdown": "常规分支正文",
            }

    caplog.set_level("WARNING")

    generator = FakeGenerator()
    candidates = workbench._generate_initial_draft_candidates(
        project={
            "source_type": "tracked_article",
            "slug": "compact-timeout-demo",
            "reference_article_title": "幸福是什么",
            "reference_article_author": "北岛",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "放下强求，珍惜已有。",
            "reference_article_body_markdown": "正文",
            "reference_article_structure_notes": "总论 + 例子 + 回到拥有",
            "reference_article_tags": "[]",
        },
        generator=generator,
        draft_payload={
            "problem_brief": {"clarified_problem": "旧策略包"},
            "strategy_card": {"point_of_view": "旧策略卡"},
            "benchmarks": [{"title": "旧基准"}],
            "reference_article_hidden": True,
        },
    )

    assert len(generator.calls) == 2
    assert candidates == [("救援分支稿", "救援分支正文")]
    assert generator.calls[0]["compact_strategy_mode"] is True
    assert "timeout_recovery_mode" not in generator.calls[0]
    assert generator.calls[1]["compact_strategy_mode"] is True
    assert generator.calls[1]["timeout_recovery_mode"] is True
    assert "problem_brief" not in generator.calls[1]
    assert "strategy_card" not in generator.calls[1]
    assert "benchmarks" not in generator.calls[1]
    assert "reference_article_hidden" not in generator.calls[1]
    assert generator.calls[1]["reference_article_title"] == "幸福是什么"
    assert "Compact strategy draft branch failed for project compact-timeout-demo" in caplog.text


def test_generate_draft_skips_full_branch_when_compact_candidate_matches_fragment_chain_shape(monkeypatch) -> None:
    fragment_chain_candidate = (
        "# 她把消息回完以后，才看见自己已经慢下来了\n\n"
        "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣。\n\n"
        "杯壁外侧已经结了一层薄薄的水，电脑右下角跳到 21:47，文档还开着，光标一闪一闪。那条消息很短：最近怎么样，要不要找天见一面？\n\n"
        "她点开语音，说了两个字，停住。删掉。又按住，说到“我最近……”就没声了。肩膀绷得很紧，像有人把两边往里拽。最后发出去的，还是那句最省力的话：这周有点满，下次一定。\n\n"
        "很多人就是从这种地方开始变慢的。\n\n"
        "不是什么大事，也没有戏剧性的崩塌。闹钟响了，按掉，再按掉。明明只差十分钟就能从容出门，还是在床边坐了很久。洗头这件事，要在心里过两遍流程。\n\n"
        "白天她照常开会、改东西、回邮件。谁来催，她都能接住，语气也稳。到了下班路上，地铁门一开，风吹进来，她忽然只想把耳机音量调大一点，谁都别找她。\n\n"
        "这里面有条很清楚的线。\n\n"
        "待办一项项堆上来，她最先做的，通常不是分辨自己累到哪了，而是把那点不舒服往里折，先做完再说。眼前这关要过，明天那项不能拖，周会材料还差最后两页。\n\n"
        "她不是突然不爱说话的。\n\n"
        "早上出门前，口红拿起来又放下，算了。午休时间，本来想去楼下走走，结果坐在工位上发呆。深夜洗漱，牙刷含在嘴里，眼睛看着镜子里的人，脑子却是空的。\n\n"
        "更麻烦的是，她常把这些信号当成“最近状态不太好”。\n\n"
        "醒来更累，胃口乱，有时下午三四点突然心慌；消息提示音一密集，太阳穴就跟着发紧。按理说，这些已经够明显了。可她对自己的解释总是很熟：忙完这阵就好了，周末补个觉就好了，最近事情多，谁不是这样。\n\n"
        "因为她还没有倒下。\n\n"
        "还能上班，能交差，能在别人问起时回一句“挺好的”。正是这种“还能”，最容易让人误判。像房间里有一盏灯开始忽明忽暗，但只要没彻底灭掉，大家就继续用。\n\n"
        "关系里的缺席，也不是某天忽然形成的。\n\n"
        "先是把见面改成改天。后来电话变成文字。再后来，长回复缩成表情，解释缩成“最近有点忙”。聊天框里的未读红点越来越多，她收藏过几条想认真回的话，后来也没再点开。\n\n"
        "这句话听上去很体谅，可听多了，人会更沉默。\n\n"
        "因为她慢慢适应了自己总在往后退。生活里有新变化，不太主动讲了；受了委屈，也觉得讲起来太费劲。别人伸手的时候，她先想到的不是“我可以说”，而是“我得赶紧恢复正常，再去见人”。\n\n"
        "有些代价是延迟出现的。\n\n"
        "回家的路上，手机又亮了一次。她站在电梯里，看着镜子里自己有点发白的脸，拇指在屏幕上停了停，没有再逼自己把所有消息都回完。她只给其中一个人发了句实话：我最近有点撑不动，可能会回得慢一点。"
    )

    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "她把消息回完以后，才看见自己已经慢下来了。",
                "outline_body": "1. 咖啡边的停顿\n2. 白天照常撑住\n3. 关系里的缺席\n4. 晚上终于说一句实话",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if not payload.get("polish_instruction") and payload.get("compact_strategy_mode"):
                return {
                    "title": "她把消息回完以后，才看见自己已经慢下来了",
                    "body_markdown": fragment_chain_candidate,
                }
            raise AssertionError("full strategy branch should not run when compact candidate matches fragment-chain shape")

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "fragment-chain-compact-source",
            "source_name": "夜读关系实验室",
            "title": "总在处理别人的消息，轮到自己时只剩深夜那一点空",
            "url": "https://example.com/fragment-chain-compact-source",
            "author": "北岛",
            "summary": "从深夜回消息的停顿切入，写人为什么会把自己的提醒一再往后放。",
            "structure_notes": "碎片起笔 + 观察回环 + 轻动作收尾。",
            "tags": ["深夜停顿", "身体提醒"],
        },
    )
    client.post(
        "/api/tracked-articles/fragment-chain-compact-source/to-topic",
        json={
            "slug": "fragment-chain-compact-topic",
            "title": "总在处理别人的消息，轮到自己时只剩深夜那一点空",
            "angle": "身体提醒",
        },
    )

    project_response = client.post(
        "/api/topics/fragment-chain-compact-topic/create-project",
        json={
            "slug": "fragment-chain-compact-project",
            "title": "fragment chain compact 优先稿",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201

    assert client.post("/api/projects/fragment-chain-compact-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/fragment-chain-compact-project/adopt-strategy-card/1").status_code == 200
    assert client.post("/api/projects/fragment-chain-compact-project/generate-outline").status_code == 201

    draft_response = client.post("/api/projects/fragment-chain-compact-project/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()

    assert draft["title"] == "她把消息回完以后，才看见自己已经慢下来了"
    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    assert len(draft_calls) == 1
    assert draft_calls[0][1]["compact_strategy_mode"] is True


def test_generate_draft_keeps_successful_branch_when_other_branch_auto_polish_fails(monkeypatch) -> None:
    class FakeGenerator:
        uses_custom_base_url = True

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "她盯着屏幕发了会儿呆。",
                "outline_body": "1. 电梯口的停顿\n2. 白天的硬撑\n3. 人际回应的变慢\n4. 夜里终于看见提醒",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            draft_payload = payload.get("draft")
            draft_title = ""
            if isinstance(draft_payload, dict):
                draft_title = str(draft_payload.get("title") or "")

            if not instruction:
                if payload.get("compact_strategy_mode"):
                    return {
                        "title": "预约页面停在最后一步",
                        "body_markdown": (
                            "# 预约页面停在最后一步\n\n"
                            "不是不想去，而是她总觉得还能再拖一拖。很多时候，人就是这样把自己的提醒压下去。\n\n"
                            "白天她照常回消息，晚上照常说服自己明天再看。\n\n"
                            "从今天开始，别再把身体往后放。"
                        ),
                    }
                return {
                    "title": "她把那句等会儿先放回去了",
                    "body_markdown": (
                        "# 她把那句等会儿先放回去了\n\n"
                        "不是不累，而是她还想先把眼前这点事做完。很多时候，人就是这样一点点把自己往后挪。\n\n"
                        "会议、消息、进度、解释，每一件都像比身体更急。\n\n"
                        "从今天开始，别再把该停下来的时候继续往前推。"
                    ),
                }

            if draft_title == "预约页面停在最后一步":
                raise RuntimeError("upstream temporarily unavailable")

            if payload.get("compact_polish_mode"):
                return {
                    "title": "她先回了消息，才看见自己已经慢下来了",
                    "body_markdown": (
                        "# 她先回了消息，才看见自己已经慢下来了\n\n"
                        "电梯门快合上的时候，她已经抬了脚，又收回来。\n\n"
                        "消息先回出去，身体那一下发空却被她顺手按了下去。\n\n"
                        "回到工位以后，文件还在往前推，人却像被什么轻轻拽住了。"
                    ),
                }

            return {
                "title": "她先把消息回完，才发现身体已经在往后拖",
                "body_markdown": (
                    "# 她先把消息回完，才发现身体已经在往后拖\n\n"
                    "电梯门快合上的时候，她已经抬了脚，又收回来。手指先把那句“能，稍等”发出去，胃里那阵发空却没有立刻过去。\n\n"
                    "到了工位，她照常开电脑、接电话、改表格。旁边的人只会觉得她今天话更少一点，看不出她连解释一句都嫌费劲。\n\n"
                    "真正麻烦的，不是某一次突然撑不住，而是身体已经在往后拖，人还在把每一件眼前事都排到它前面。"
                ),
            }

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "branch-failure-source",
            "source_name": "夜读关系实验室",
            "title": "真正让人慢下来的，不是某一天，而是一直把自己往后放",
            "url": "https://example.com/branch-failure-source",
            "author": "北岛",
            "summary": "从身体提醒和日常延后写人为什么会一点点耗尽。",
            "structure_notes": "动作入口 + 白天硬撑 + 夜里回看。",
            "tags": ["身体提醒", "关系修复"],
        },
    )
    client.post(
        "/api/tracked-articles/branch-failure-source/to-topic",
        json={
            "slug": "branch-failure-topic",
            "title": "真正让人慢下来的，不是某一天，而是一直把自己往后放",
            "angle": "身体提醒",
        },
    )

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    project_response = client.post(
        "/api/topics/branch-failure-topic/create-project",
        json={
            "slug": "branch-failure-project",
            "title": "分支失败兜底稿",
            "owner": "editorial",
        },
    )
    assert project_response.status_code == 201

    assert client.post("/api/projects/branch-failure-project/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/branch-failure-project/adopt-strategy-card/1").status_code == 200
    assert client.post("/api/projects/branch-failure-project/generate-outline").status_code == 201

    draft_response = client.post("/api/projects/branch-failure-project/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()

    assert draft["title"] == "她先把消息回完，才发现身体已经在往后拖"
    assert "电梯门快合上的时候" in draft["body_markdown"]

    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    assert len(draft_calls) == 4
    assert draft_calls[0][1]["compact_strategy_mode"] is True
    assert "compact_strategy_mode" not in draft_calls[2][1]
    assert "compact_polish_mode" not in draft_calls[1][1]
    assert "compact_polish_mode" not in draft_calls[3][1]


def test_finalize_initial_draft_candidate_prefers_branch_with_better_post_cleanup_state(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        workbench,
        "_maybe_compress_draft_output",
        lambda **kwargs: (kwargs["body_markdown"], kwargs["title"]),
    )
    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_structure_drift", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_over_smoothing", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_article_shell_cleanup", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_remaining_ai_flavor", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_final_ai_flavor_cleanup", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))

    score_map = {
        "source raw": 60,
        "regular raw": 30,
        "compact raw": 10,
        "regular cleaned": 0,
        "compact cleaned": 5,
    }

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        score = score_map[body_markdown]
        level = "高" if score >= 60 else "中" if score >= 30 else "低"
        return SimpleNamespace(score=score, level=level, hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)

    def fake_cleanup(*, title: str, body_markdown: str) -> str:
        if body_markdown == "regular raw":
            return "regular cleaned"
        if body_markdown == "compact raw":
            return "compact cleaned"
        return body_markdown

    monkeypatch.setattr(workbench, "_collapse_short_judgment_residue", fake_cleanup)
    monkeypatch.setattr(workbench, "_collapse_time_chain_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_embedded_banner_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(
        workbench,
        "_collapse_leading_short_long_cadence_residue",
        lambda **kwargs: kwargs["body_markdown"],
        raising=False,
    )
    monkeypatch.setattr(workbench, "_collapse_short_long_cadence_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_over_segmented_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_light_segmented_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_structural_ladder_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_not_ab_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_connector_residue", lambda **kwargs: kwargs["body_markdown"])

    class FakeGenerator:
        uses_custom_base_url = True

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            if payload.get("compact_polish_mode"):
                return {"title": "compact winner by raw", "body_markdown": "compact raw"}
            return {"title": "regular winner after cleanup", "body_markdown": "regular raw"}

    class FakeToneProfile:
        target_word_count = 0

        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    result = workbench._finalize_initial_draft_candidate(
        project_slug="demo",
        tone_profile=FakeToneProfile(),
        project={
            "source_type": "tracked_article",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
            "reference_article_body_markdown": "",
            "reference_article_title": "",
        },
        outline_row={"hook": "", "outline_body": ""},
        review_comment=None,
        reference_article_payload={},
        strategy_bundle_payload={},
        polish_instruction=None,
        generator=FakeGenerator(),
        title="source title",
        body_markdown="source raw",
    )

    assert result.title == "regular winner after cleanup"
    assert result.body_markdown == "regular cleaned"
    assert result.reference_body_markdown == "regular raw"


def test_apply_initial_draft_candidate_cleanups_strips_split_rebound_explainer_tails() -> None:
    raw_markdown = (
        "# 你已经很累了\n\n"
        "咖啡续到第三杯。真要把它算成没看见自己累了。更常见的情况，反而把事情说浅了。\n\n"
        "这一步看上去不激烈。真要把它算成立刻轻松，也未必马上甘心。你还，反而把事情说浅了。那股惯性还在。"
    )

    cleaned_markdown, changed_steps = workbench._apply_initial_draft_candidate_cleanups(
        title="你已经很累了",
        body_markdown=raw_markdown,
        source_type="tracked_article",
    )

    assert changed_steps >= 1
    assert "真要把它算成" not in cleaned_markdown
    assert "反而把事情说浅了" not in cleaned_markdown
    assert "更常见的情况" not in cleaned_markdown
    assert "你还，" not in cleaned_markdown
    assert "咖啡续到第三杯。" in cleaned_markdown
    assert "这一步看上去不激烈。" in cleaned_markdown
    assert "那股惯性还在。" in cleaned_markdown


def test_maybe_retry_polish_for_final_ai_flavor_cleanup_prefers_retry_after_cleanup_preview(
    monkeypatch,
) -> None:
    score_map = {
        "current raw": 4,
        "retry raw": 12,
        "current cleaned": 3,
        "retry cleaned": 0,
    }

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        score = score_map[body_markdown]
        level = "高" if score >= 60 else "中" if score >= 30 else "低"
        return SimpleNamespace(score=score, level=level, hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)

    def fake_cleanup(*, title: str, body_markdown: str) -> str:
        if body_markdown == "current raw":
            return "current cleaned"
        if body_markdown == "retry raw":
            return "retry cleaned"
        return body_markdown

    monkeypatch.setattr(workbench, "_collapse_short_judgment_residue", fake_cleanup)
    monkeypatch.setattr(workbench, "_collapse_time_chain_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_embedded_banner_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(
        workbench,
        "_collapse_leading_short_long_cadence_residue",
        lambda **kwargs: kwargs["body_markdown"],
        raising=False,
    )
    monkeypatch.setattr(workbench, "_collapse_short_long_cadence_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_over_segmented_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_light_segmented_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_structural_ladder_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_not_ab_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_connector_residue", lambda **kwargs: kwargs["body_markdown"])

    retry_flags = iter([True, False])
    monkeypatch.setattr(
        workbench,
        "_should_retry_for_final_ai_flavor_cleanup",
        lambda **_: next(retry_flags),
    )

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {"title": "retry title", "body_markdown": "retry raw"}

    result_markdown, result_title = workbench._maybe_retry_polish_for_final_ai_flavor_cleanup(
        project={
            "source_type": "tracked_article",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction="cleanup",
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=FakeGenerator(),
        source_draft_title="source title",
        source_draft_body_markdown="source raw",
        candidate_title="current title",
        candidate_body_markdown="current raw",
    )

    assert result_title == "retry title"
    assert result_markdown == "retry raw"


def test_maybe_retry_polish_for_over_smoothing_prefers_retry_after_cleanup_preview(
    monkeypatch,
) -> None:
    score_map = {
        "current raw": 4,
        "retry raw": 12,
        "current cleaned": 3,
        "retry cleaned": 0,
    }

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        score = score_map[body_markdown]
        level = "高" if score >= 60 else "中" if score >= 30 else "低"
        return SimpleNamespace(score=score, level=level, hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)

    def fake_cleanup(*, title: str, body_markdown: str) -> str:
        if body_markdown == "current raw":
            return "current cleaned"
        if body_markdown == "retry raw":
            return "retry cleaned"
        return body_markdown

    monkeypatch.setattr(workbench, "_collapse_short_judgment_residue", fake_cleanup)
    monkeypatch.setattr(workbench, "_find_excessive_generic_reflective_openers", lambda **_: ["很多时候"])
    monkeypatch.setattr(workbench, "_preserves_structure_headings", lambda **_: True)

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {"title": "retry title", "body_markdown": "retry raw"}

    result_markdown, result_title = workbench._maybe_retry_polish_for_over_smoothing(
        project={
            "source_type": "manual",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction="cleanup",
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=FakeGenerator(),
        source_draft_title="source title",
        source_draft_body_markdown="source raw",
        candidate_title="current title",
        candidate_body_markdown="current raw",
    )

    assert result_title == "retry title"
    assert result_markdown == "retry raw"


def test_maybe_retry_polish_for_remaining_ai_flavor_prefers_retry_after_cleanup_preview(
    monkeypatch,
) -> None:
    score_map = {
        "current raw": 4,
        "retry raw": 12,
        "current cleaned": 3,
        "retry cleaned": 0,
    }

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        score = score_map[body_markdown]
        level = "高" if score >= 60 else "中" if score >= 30 else "低"
        return SimpleNamespace(score=score, level=level, hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)

    def fake_cleanup(*, title: str, body_markdown: str) -> str:
        if body_markdown == "current raw":
            return "current cleaned"
        if body_markdown == "retry raw":
            return "retry cleaned"
        return body_markdown

    monkeypatch.setattr(workbench, "_collapse_short_judgment_residue", fake_cleanup)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: True)
    monkeypatch.setattr(workbench, "_preserves_structure_headings", lambda **_: True)

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {"title": "retry title", "body_markdown": "retry raw"}

    result_markdown, result_title = workbench._maybe_retry_polish_for_remaining_ai_flavor(
        project={
            "source_type": "manual",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction="cleanup",
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=FakeGenerator(),
        source_draft_title="source title",
        source_draft_body_markdown="source raw",
        candidate_title="current title",
        candidate_body_markdown="current raw",
    )

    assert result_title == "retry title"
    assert result_markdown == "retry raw"


def test_maybe_retry_polish_for_remaining_ai_flavor_skips_tracked_article_fragment_chain_candidate(
    monkeypatch,
) -> None:
    candidate_markdown = (
        "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣。\n\n"
        "杯壁外侧已经结了一层薄薄的水，电脑右下角跳到 21:47，文档还开着，光标一闪一闪。那条消息很短：最近怎么样，要不要找天见一面？\n\n"
        "她点开语音，说了两个字，停住。删掉。又按住，说到“我最近……”就没声了。肩膀绷得很紧，像有人把两边往里拽。最后发出去的，还是那句最省力的话：这周有点满，下次一定。\n\n"
        "很多人就是从这种地方开始变慢的。\n\n"
        "不是什么大事，也没有戏剧性的崩塌。闹钟响了，按掉，再按掉。明明只差十分钟就能从容出门，还是在床边坐了很久。洗头这件事，要在心里过两遍流程。\n\n"
        "白天她照常开会、改东西、回邮件。谁来催，她都能接住，语气也稳。到了下班路上，地铁门一开，风吹进来，她忽然只想把耳机音量调大一点，谁都别找她。\n\n"
        "这里面有条很清楚的线。\n\n"
        "待办一项项堆上来，她最先做的，通常不是分辨自己累到哪了，而是把那点不舒服往里折，先做完再说。眼前这关要过，明天那项不能拖，周会材料还差最后两页。\n\n"
        "她不是突然不爱说话的。\n\n"
        "早上出门前，口红拿起来又放下，算了。午休时间，本来想去楼下走走，结果坐在工位上发呆。深夜洗漱，牙刷含在嘴里，眼睛看着镜子里的人，脑子却是空的。\n\n"
        "更麻烦的是，她常把这些信号当成“最近状态不太好”。\n\n"
        "醒来更累，胃口乱，有时下午三四点突然心慌；消息提示音一密集，太阳穴就跟着发紧。按理说，这些已经够明显了。可她对自己的解释总是很熟：忙完这阵就好了，周末补个觉就好了，最近事情多，谁不是这样。\n\n"
        "因为她还没有倒下。\n\n"
        "还能上班，能交差，能在别人问起时回一句“挺好的”。正是这种“还能”，最容易让人误判。像房间里有一盏灯开始忽明忽暗，但只要没彻底灭掉，大家就继续用。\n\n"
        "关系里的缺席，也不是某天忽然形成的。\n\n"
        "先是把见面改成改天。后来电话变成文字。再后来，长回复缩成表情，解释缩成“最近有点忙”。聊天框里的未读红点越来越多，她收藏过几条想认真回的话，后来也没再点开。\n\n"
        "这句话听上去很体谅，可听多了，人会更沉默。\n\n"
        "因为她慢慢适应了自己总在往后退。生活里有新变化，不太主动讲了；受了委屈，也觉得讲起来太费劲。别人伸手的时候，她先想到的不是“我可以说”，而是“我得赶紧恢复正常，再去见人”。\n\n"
        "有些代价是延迟出现的。\n\n"
        "回家的路上，手机又亮了一次。她站在电梯里，看着镜子里自己有点发白的脸，拇指在屏幕上停了停，没有再逼自己把所有消息都回完。她只给其中一个人发了句实话：我最近有点撑不动，可能会回得慢一点。"
    )

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            raise AssertionError("fragment-chain tracked article candidate should not enter remaining ai flavor retry")

    result_markdown, result_title = workbench._maybe_retry_polish_for_remaining_ai_flavor(
        project={
            "source_type": "tracked_article",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction="cleanup",
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=FakeGenerator(),
        source_draft_title="source title",
        source_draft_body_markdown="source raw",
        candidate_title="tracked title",
        candidate_body_markdown=candidate_markdown,
    )

    assert result_title == "tracked title"
    assert result_markdown == candidate_markdown


def test_maybe_auto_polish_ai_flavor_draft_output_prefers_retry_chain_candidate_after_cleanup_preview(
    monkeypatch,
) -> None:
    score_map = {
        "source raw": 60,
        "best raw": 35,
        "retry raw": 42,
        "best cleaned": 3,
        "retry cleaned": 0,
    }

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        score = score_map[body_markdown]
        level = "高" if score >= 60 else "中" if score >= 30 else "低"
        return SimpleNamespace(score=score, level=level, hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)

    def fake_cleanup(*, title: str, body_markdown: str) -> str:
        if body_markdown == "best raw":
            return "best cleaned"
        if body_markdown == "retry raw":
            return "retry cleaned"
        return body_markdown

    monkeypatch.setattr(workbench, "_collapse_short_judgment_residue", fake_cleanup)
    monkeypatch.setattr(
        workbench,
        "_maybe_retry_polish_for_structure_drift",
        lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]),
    )
    monkeypatch.setattr(
        workbench,
        "_maybe_retry_polish_for_over_smoothing",
        lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]),
    )
    monkeypatch.setattr(
        workbench,
        "_maybe_retry_polish_for_article_shell_cleanup",
        lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]),
    )
    monkeypatch.setattr(
        workbench,
        "_maybe_retry_polish_for_remaining_ai_flavor",
        lambda **kwargs: ("retry raw", "retry title"),
    )
    monkeypatch.setattr(
        workbench,
        "_maybe_retry_polish_for_final_ai_flavor_cleanup",
        lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]),
    )

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        uses_custom_base_url = False

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            return {"title": "best title", "body_markdown": "best raw"}

    result_markdown, result_title = workbench._maybe_auto_polish_ai_flavor_draft_output(
        title="source title",
        body_markdown="source raw",
        project={
            "source_type": "manual",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction=None,
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=FakeGenerator(),
    )

    assert result_title == "retry title"
    assert result_markdown == "retry raw"


def test_maybe_auto_polish_ai_flavor_draft_output_skips_tracked_article_low_risk_without_shell_signals(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        workbench,
        "evaluate_ai_flavor_risk",
        lambda **_: SimpleNamespace(score=0, level="低", hits=[], suggestions=[]),
    )
    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False)

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        uses_custom_base_url = True

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            raise AssertionError("auto polish should short-circuit before retry generation")

    result_markdown, result_title = workbench._maybe_auto_polish_ai_flavor_draft_output(
        title="tracked title",
        body_markdown="tracked raw",
        project={
            "source_type": "tracked_article",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
            "reference_article_body_markdown": "reference raw",
            "reference_article_title": "reference title",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction=None,
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=FakeGenerator(),
    )

    assert result_title == "tracked title"
    assert result_markdown == "tracked raw"


def test_maybe_auto_polish_ai_flavor_draft_output_does_not_short_circuit_low_score_tracked_article_opening_explainer_shell(
    monkeypatch,
) -> None:
    summary = SimpleNamespace(
        score=18,
        level="低",
        hits=["命中：开头讲稿式先答后证 2/3"],
        suggestions=[
            "建议：开头不要先用“你以为……吗 / 有一类……”替读者分类下定义，直接把现实接口、后果或身体信号顶上来，再把判断慢一点递出来。"
        ],
    )
    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", lambda **_: summary)
    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False)
    monkeypatch.setattr(workbench, "_should_prefer_retried_candidate_after_cleanup_preview", lambda **_: True)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_structure_drift", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_over_smoothing", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_article_shell_cleanup", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_remaining_ai_flavor", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_final_ai_flavor_cleanup", lambda **kwargs: (kwargs["candidate_body_markdown"], kwargs["candidate_title"]))

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        uses_custom_base_url = False

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(payload)
            return {"title": "polished title", "body_markdown": "polished raw"}

    fake_generator = FakeGenerator()

    result_markdown, result_title = workbench._maybe_auto_polish_ai_flavor_draft_output(
        title="tracked title",
        body_markdown="tracked raw",
        project={
            "source_type": "tracked_article",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
            "reference_article_body_markdown": "reference raw",
            "reference_article_title": "reference title",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction=None,
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=fake_generator,
    )

    assert result_title == "polished title"
    assert result_markdown == "polished raw"
    assert len(fake_generator.calls) == 1
    assert "开头不要先用“你以为……吗 / 有一类……”替读者分类下定义" in str(
        fake_generator.calls[0]["polish_instruction"]
    )


def test_maybe_auto_polish_ai_flavor_draft_output_short_circuits_low_risk_tracked_article_after_polish_when_no_retry_signals(
    monkeypatch,
) -> None:
    score_map = {
        "tracked raw": 30,
        "polished raw": 8,
    }

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        score = score_map[body_markdown]
        level = "高" if score >= 60 else "中" if score >= 20 else "低"
        return SimpleNamespace(score=score, level=level, hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)
    monkeypatch.setattr(workbench, "_should_prefer_retried_candidate_after_cleanup_preview", lambda **_: True)
    monkeypatch.setattr(workbench, "_find_missing_structure_headings", lambda **_: [])
    monkeypatch.setattr(workbench, "_find_excessive_generic_reflective_openers", lambda **_: [])
    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False)

    def fail_retry(**_: object) -> tuple[str, str]:
        raise AssertionError("retry chain should short-circuit once tracked article candidate is low risk")

    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_structure_drift", fail_retry)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_over_smoothing", fail_retry)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_article_shell_cleanup", fail_retry)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_remaining_ai_flavor", fail_retry)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_final_ai_flavor_cleanup", fail_retry)

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        uses_custom_base_url = False

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(payload)
            return {"title": "polished title", "body_markdown": "polished raw"}

    fake_generator = FakeGenerator()

    result_markdown, result_title = workbench._maybe_auto_polish_ai_flavor_draft_output(
        title="tracked title",
        body_markdown="tracked raw",
        project={
            "source_type": "tracked_article",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
            "reference_article_body_markdown": "reference raw",
            "reference_article_title": "reference title",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction=None,
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=fake_generator,
    )

    assert result_title == "polished title"
    assert result_markdown == "polished raw"
    assert len(fake_generator.calls) == 1


def test_maybe_auto_polish_ai_flavor_draft_output_skips_tracked_article_fragment_chain_candidate(
    monkeypatch,
) -> None:
    candidate_markdown = (
        "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣。\n\n"
        "杯壁外侧已经结了一层薄薄的水，电脑右下角跳到 21:47，文档还开着，光标一闪一闪。那条消息很短：最近怎么样，要不要找天见一面？\n\n"
        "她点开语音，说了两个字，停住。删掉。又按住，说到“我最近……”就没声了。肩膀绷得很紧，像有人把两边往里拽。最后发出去的，还是那句最省力的话：这周有点满，下次一定。\n\n"
        "很多人就是从这种地方开始变慢的。\n\n"
        "不是什么大事，也没有戏剧性的崩塌。闹钟响了，按掉，再按掉。明明只差十分钟就能从容出门，还是在床边坐了很久。洗头这件事，要在心里过两遍流程。\n\n"
        "白天她照常开会、改东西、回邮件。谁来催，她都能接住，语气也稳。到了下班路上，地铁门一开，风吹进来，她忽然只想把耳机音量调大一点，谁都别找她。\n\n"
        "这里面有条很清楚的线。\n\n"
        "待办一项项堆上来，她最先做的，通常不是分辨自己累到哪了，而是把那点不舒服往里折，先做完再说。眼前这关要过，明天那项不能拖，周会材料还差最后两页。\n\n"
        "她不是突然不爱说话的。\n\n"
        "早上出门前，口红拿起来又放下，算了。午休时间，本来想去楼下走走，结果坐在工位上发呆。深夜洗漱，牙刷含在嘴里，眼睛看着镜子里的人，脑子却是空的。\n\n"
        "更麻烦的是，她常把这些信号当成“最近状态不太好”。\n\n"
        "醒来更累，胃口乱，有时下午三四点突然心慌；消息提示音一密集，太阳穴就跟着发紧。按理说，这些已经够明显了。可她对自己的解释总是很熟：忙完这阵就好了，周末补个觉就好了，最近事情多，谁不是这样。\n\n"
        "因为她还没有倒下。\n\n"
        "还能上班，能交差，能在别人问起时回一句“挺好的”。正是这种“还能”，最容易让人误判。像房间里有一盏灯开始忽明忽暗，但只要没彻底灭掉，大家就继续用。\n\n"
        "关系里的缺席，也不是某天忽然形成的。\n\n"
        "先是把见面改成改天。后来电话变成文字。再后来，长回复缩成表情，解释缩成“最近有点忙”。聊天框里的未读红点越来越多，她收藏过几条想认真回的话，后来也没再点开。\n\n"
        "这句话听上去很体谅，可听多了，人会更沉默。\n\n"
        "因为她慢慢适应了自己总在往后退。生活里有新变化，不太主动讲了；受了委屈，也觉得讲起来太费劲。别人伸手的时候，她先想到的不是“我可以说”，而是“我得赶紧恢复正常，再去见人”。\n\n"
        "有些代价是延迟出现的。\n\n"
        "回家的路上，手机又亮了一次。她站在电梯里，看着镜子里自己有点发白的脸，拇指在屏幕上停了停，没有再逼自己把所有消息都回完。她只给其中一个人发了句实话：我最近有点撑不动，可能会回得慢一点。"
    )

    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False)

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        uses_custom_base_url = True

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            raise AssertionError("fragment-chain tracked article candidate should not enter initial auto polish")

    result_markdown, result_title = workbench._maybe_auto_polish_ai_flavor_draft_output(
        title="tracked title",
        body_markdown=candidate_markdown,
        project={
            "source_type": "tracked_article",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
            "reference_article_body_markdown": "reference raw",
            "reference_article_title": "reference title",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction=None,
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=FakeGenerator(),
    )

    assert result_title == "tracked title"
    assert result_markdown == candidate_markdown


def test_maybe_auto_polish_ai_flavor_draft_output_skips_low_risk_single_window_tracked_article_candidate(
    monkeypatch,
) -> None:
    candidate_markdown = (
        "外卖袋勒得手指发白，她在玄关弯腰解结，汤盒烫得掌心换了两次位置。门在背后响了一下，他进来，手里空着，钥匙往柜子上一放，低头换鞋。\n\n"
        "下午六点多，她明明发过消息：家里纸巾没了，顺路带一提回来。聊天框里还停着他的“好”。人回来了，纸没回来。\n\n"
        "话其实已经到嘴边了。她原本想说“你又忘了”，舌尖抵了抵上颚，最后落下来，成了句很轻的：“先吃饭吧。”\n\n"
        "电视开着，综艺里的笑声一阵一阵飘出来。他走到餐桌边，看了眼外卖盒，随口问：“怎么还没吃？”\n\n"
        "肩膀就是那时绷起来的。这句问话不重，难受的地方也不在语气。它像把前面那串小事一起抹平了：下班绕路拿外卖，回家发现抽纸真没了，蹲在柜子前翻出半包旧纸巾，边角都压皱了。好像这些都不算事，所以也不用被提起。\n\n"
        "她把筷子抽出来，塑料套刮过桌面，声音有点干。本来还想接一句“我在等你，也在等那提纸”，可人坐下以后，嘴又收回去了，只剩“刚拆”。\n\n"
        "后来她蹲下去，把柜子底下那半包纸抽出来，里面只剩三张。她盯着那三张纸，看了一会儿。有些关系变味，不是靠一次大吵认出来的。更常见的情况是，家里还照常吃饭，消息也照常回，只是开口这件事，已经悄悄变贵了。"
    )

    class FakeSummary:
        score = 0
        level = "低"
        hits: list[str] = []
        suggestions: list[str] = []

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", lambda **_: FakeSummary())
    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False)

    class FakeToneProfile:
        def model_dump(self) -> dict[str, object]:
            return {"target_word_count": 0}

    class FakeGenerator:
        uses_custom_base_url = True

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            raise AssertionError("low-risk single-window tracked article candidate should not enter auto polish")

    result_markdown, result_title = workbench._maybe_auto_polish_ai_flavor_draft_output(
        title="tracked title",
        body_markdown=candidate_markdown,
        project={
            "source_type": "tracked_article",
            "trend_title": "trend",
            "topic_title": "topic",
            "topic_angle": "angle",
            "title": "project",
            "domain_pack_key": "",
            "reference_article_body_markdown": "reference raw",
            "reference_article_title": "reference title",
        },
        outline_row={"hook": "", "outline_body": ""},
        tone_profile=FakeToneProfile(),
        review_comment=None,
        polish_instruction=None,
        strategy_bundle_payload={},
        reference_article_payload={},
        generator=FakeGenerator(),
    )

    assert result_title == "tracked title"
    assert result_markdown == candidate_markdown


def test_generate_assets_falls_back_when_cover_image_generation_is_unavailable(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            raise RuntimeError("image provider unavailable")

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-outline").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-draft").status_code == 201

    assets_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    assert assets_response.status_code == 201
    assets = assets_response.json()
    assert assets["cover_image_path"] == ""
    assert assets["cover_image_url"] == ""

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["project"]["stage"] == "assets_ready"
    assert detail["assets"]["cover_image_url"] == ""

    publish_response = client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    assert publish_response.status_code == 201
    publish_payload = publish_response.json()
    assert publish_payload["status"] == "ready"

    markdown = Path(publish_payload["markdown_path"]).read_text(encoding="utf-8")
    manifest = Path(publish_payload["manifest_path"]).read_text(encoding="utf-8")
    assert "封面图：未生成（图片服务暂时不可用）" in markdown
    assert '"cover_image_url": ""' in manifest


def test_generate_assets_normalizes_vertical_cover_prompt_before_image_generation(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("assets", payload))
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "办公室午后工位场景，人物疲惫但克制，适合公众号封面，竖版，9:16",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            self.calls.append(("cover_image", payload))
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-outline").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-draft").status_code == 201

    assets_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    assert assets_response.status_code == 201
    assets = assets_response.json()
    assert "21:9" in assets["cover_prompt"]
    assert "横版" in assets["cover_prompt"]
    assert "竖版" not in assets["cover_prompt"]
    assert "9:16" not in assets["cover_prompt"]

    cover_image_call = next(call for call in fake_generator.calls if call[0] == "cover_image")
    assert "21:9" in cover_image_call[1]["cover_prompt"]
    assert "横版" in cover_image_call[1]["cover_prompt"]
    assert "竖版" not in cover_image_call[1]["cover_prompt"]
    assert "9:16" not in cover_image_call[1]["cover_prompt"]

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert "21:9" in detail["assets"]["cover_prompt"]
    assert "竖版" not in detail["assets"]["cover_prompt"]


def test_generate_assets_serializes_versions_for_same_project(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            time.sleep(0.1)
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "办公室午后工位场景，人物疲惫但克制",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-outline").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-draft").status_code == 201

    responses: list[dict[str, object]] = []

    def run_generate_assets() -> None:
        response = client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
        assert response.status_code == 201
        responses.append(response.json())

    first = threading.Thread(target=run_generate_assets)
    second = threading.Thread(target=run_generate_assets)
    first.start()
    second.start()
    first.join()
    second.join()

    versions = sorted(item["version"] for item in responses)
    assert versions == [1, 2]

    payload = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in payload["assets"][:2]] == [2, 1]


def test_build_publish_package_serializes_versions_for_same_project(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "办公室午后工位场景，人物疲惫但克制",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            time.sleep(0.1)
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-outline").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-draft").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-assets").status_code == 201

    responses: list[dict[str, object]] = []

    def run_build_publish_package() -> None:
        response = client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
        assert response.status_code == 201
        responses.append(response.json())

    first = threading.Thread(target=run_build_publish_package)
    second = threading.Thread(target=run_build_publish_package)
    first.start()
    second.start()
    first.join()
    second.join()

    versions = sorted(item["version"] for item in responses)
    assert versions == [1, 2]

    payload = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in payload["publish_packages"][:2]] == [2, 1]


def test_build_publish_package_background_submits_task_and_refreshes_project(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "办公室午后工位场景，人物疲惫但克制",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            time.sleep(0.05)
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-outline").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-draft").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-assets").status_code == 201

    response = client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package/background")
    assert response.status_code == 202
    submit_payload = response.json()
    assert submit_payload["job_type"] == "build_publish_package"

    task_payload = wait_for_background_task(submit_payload["task_id"])
    assert task_payload["status"] == "done"
    assert task_payload["result"] is not None
    assert task_payload["result"]["version"] == 1
    assert task_payload["result"]["status"] == "ready"

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["project"]["stage"] == "publish_ready"
    assert detail["project"]["current_publish_package_version"] == 1
    assert detail["publish_package"]["status"] == "ready"


def test_build_publish_package_background_logs_as_project_task_not_pipeline_batch(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "办公室午后工位场景，人物疲惫但克制",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    project_slug = "office-burnout-recovery-weekly"
    assert client.post(f"/api/projects/{project_slug}/generate-outline").status_code == 201
    assert client.post(f"/api/projects/{project_slug}/generate-draft").status_code == 201
    assert client.post(f"/api/projects/{project_slug}/generate-assets").status_code == 201

    response = client.post(f"/api/projects/{project_slug}/build-publish-package/background")
    assert response.status_code == 202
    submit_payload = response.json()

    task_payload = wait_for_background_task(submit_payload["task_id"])
    assert task_payload["status"] == "done"

    summary_response = client.get("/api/dashboard/summary")
    assert summary_response.status_code == 200
    recent_tasks = summary_response.json()["recent_tasks"]

    workbench_task = next(
        (task for task in recent_tasks if task["background_task_id"] == submit_payload["task_id"]),
        None,
    )
    assert workbench_task is not None
    assert workbench_task["task_type"] == "build_publish_package"
    assert workbench_task["entity_type"] == "project"
    assert workbench_task["entity_slug"] == project_slug

    all_log_response = client.get("/api/background-tasks/logs?scope=all")
    assert all_log_response.status_code == 200
    all_task_logs = all_log_response.json()
    assert any(task["background_task_id"] == submit_payload["task_id"] for task in all_task_logs)

    pipeline_log_response = client.get("/api/background-tasks/logs?scope=pipeline")
    assert pipeline_log_response.status_code == 200
    pipeline_task_logs = pipeline_log_response.json()
    assert all(task["background_task_id"] != submit_payload["task_id"] for task in pipeline_task_logs)


def test_build_publish_package_background_can_polish_before_generating_publish_package(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                return {"title": "draft title polished", "body_markdown": "# polished\n\nbody polished"}
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("assets", payload))
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "办公室午后工位场景，人物疲惫但克制",
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

    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-outline").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-draft").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-assets").status_code == 201

    response = client.post(
        "/api/projects/office-burnout-recovery-weekly/build-publish-package/background",
        json={
            "polish_before_generate": True,
            "polish_instruction": "重写开头和结尾，减少模板感，更像真实公众号作者在写。",
        },
    )
    assert response.status_code == 202
    submit_payload = response.json()
    assert submit_payload["job_type"] == "polish_and_build_publish_package"

    task_payload = wait_for_background_task(submit_payload["task_id"])
    assert task_payload["status"] == "done"
    assert task_payload["result"] is not None
    assert task_payload["result"]["version"] == 1
    assert task_payload["result"]["draft_version"] == 2
    assert task_payload["result"]["assets_version"] == 2

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["draft"]["version"] == 2
    assert detail["draft"]["title"] == "draft title polished"
    assert detail["assets"]["version"] == 2
    assert detail["assets"]["draft_version"] == 2
    assert detail["publish_package"]["status"] == "ready"
    assert detail["project"]["stage"] == "publish_ready"
    assert detail["project"]["current_publish_package_version"] == 1

    polished_call = next(call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction"))
    assert polished_call[1]["polish_instruction"] == "重写开头和结尾，减少模板感，更像真实公众号作者在写。"

    assets_call = next(call for call in fake_generator.calls if call[0] == "assets" and call[1]["draft"]["title"] == "draft title polished")
    assert assets_call[1]["draft"]["title"] == "draft title polished"

    publish_call = next(call for call in fake_generator.calls if call[0] == "publish_package")
    assert publish_call[1]["draft"]["title"] == "draft title polished"
    assert publish_call[1]["assets"]["version"] == 2


def test_publish_package_review_flow_supports_revision_and_approval(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    revision_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/request-publish-revision",
        json={"reviewer": "ops", "comment": "封面文案太平，需要更强钩子。"},
    )
    assert revision_response.status_code == 200
    revision_payload = revision_response.json()
    assert revision_payload["status"] == "needs_revision"
    assert revision_payload["reviewed_by"] == "ops"
    assert revision_payload["review_comment"] == "封面文案太平，需要更强钩子。"
    assert revision_payload["reviewed_at"] is not None

    detail_after_revision = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail_after_revision["project"]["stage"] == "revision_requested"
    assert detail_after_revision["publish_package"]["status"] == "needs_revision"

    approve_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/approve-publish-package",
        json={"reviewer": "chief-editor", "comment": "可以发。"},
    )
    assert approve_response.status_code == 200
    approve_payload = approve_response.json()
    assert approve_payload["status"] == "approved"
    assert approve_payload["reviewed_by"] == "chief-editor"
    assert approve_payload["review_comment"] == "可以发。"

    detail_after_approval = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail_after_approval["project"]["stage"] == "published"
    assert detail_after_approval["publish_package"]["status"] == "approved"


def test_published_project_can_save_retro_and_detail_exposes_it(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    client.post(
        "/api/projects/office-burnout-recovery-weekly/approve-publish-package",
        json={"reviewer": "chief-editor", "comment": "可以发。"},
    )

    retro_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/retro",
        json={
            "performance_rating": 4,
            "summary": "标题和开头承接自然，评论区反馈聚焦共鸣。",
            "wins": ["开头钩子稳定", "结尾行动句克制"],
            "gaps": ["配图不够有记忆点"],
            "next_focus": "下一篇强化封面文案和金句抽取。",
        },
    )
    assert retro_response.status_code == 200
    retro_payload = retro_response.json()
    assert retro_payload["performance_rating"] == 4
    assert retro_payload["wins"] == ["开头钩子稳定", "结尾行动句克制"]
    assert retro_payload["next_focus"] == "下一篇强化封面文案和金句抽取。"
    assert retro_payload["recorded_at"] is not None

    detail_response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["project"]["stage"] == "published"
    assert detail["retro"]["summary"] == "标题和开头承接自然，评论区反馈聚焦共鸣。"
    assert detail["retro"]["gaps"] == ["配图不够有记忆点"]

    summary_response = client.get("/api/dashboard/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["recent_tasks"][0]["task_type"] == "project_retro_recorded"
    assert summary["recent_tasks"][0]["entity_slug"] == "office-burnout-recovery-weekly"


def test_regenerate_from_review_creates_new_versions_and_uses_review_comment(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            review_comment = payload.get("review_comment")
            if review_comment:
                return {
                    "title": "draft title v2",
                    "body_markdown": f"# draft v2\n\n{review_comment}",
                }
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("assets", payload))
            draft = payload["draft"]
            if payload.get("review_comment"):
                return {
                    "title_options": ["title revised", "title revised b"],
                    "cover_prompt": "prompt revised",
                    "cover_copy": f"cover for {draft['title']}",
                    "social_teaser": "teaser revised",
                }
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            self.calls.append(("cover_image", payload))
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.calls.append(("publish_package", payload))
            if payload.get("review_comment"):
                return {
                    "abstract": "abstract revised",
                    "tags": ["tag-revised"],
                    "editor_note": f"note with {payload['review_comment']}",
                }
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    client.post(
        "/api/projects/office-burnout-recovery-weekly/request-publish-revision",
        json={"reviewer": "ops", "comment": "封面文案太平，需要更强钩子。"},
    )

    regenerate_response = client.post("/api/projects/office-burnout-recovery-weekly/regenerate-from-review")
    assert regenerate_response.status_code == 202
    regenerate_submit = regenerate_response.json()
    assert regenerate_submit["job_type"] == "regenerate_from_review"
    regenerate_task = wait_for_background_task(regenerate_submit["task_id"])
    assert regenerate_task["status"] == "done"
    regenerate_payload = regenerate_task["result"]
    assert regenerate_payload["version"] == 2
    assert regenerate_payload["draft_version"] == 2
    assert regenerate_payload["assets_version"] == 2
    assert regenerate_payload["status"] == "ready"
    assert regenerate_payload["review_comment"] is None
    assert regenerate_payload["reviewed_by"] is None
    assert regenerate_payload["markdown_path"].endswith("office-burnout-recovery-weekly-publish-v2.md")
    assert regenerate_payload["manifest_path"].endswith("office-burnout-recovery-weekly-publish-v2.json")

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["project"]["stage"] == "publish_ready"
    assert detail["draft"]["version"] == 2
    assert detail["draft"]["title"] == "draft title v2"
    assert detail["assets"]["version"] == 2
    assert detail["assets"]["draft_version"] == 2
    assert detail["assets"]["cover_image_url"] == "/generated-assets/office-burnout-recovery-weekly-assets-v2.png"
    assert detail["publish_package"]["version"] == 2
    assert detail["publish_package"]["status"] == "ready"
    assert detail["publish_package"]["abstract"] == "abstract revised"

    markdown = Path(regenerate_payload["markdown_path"]).read_text(encoding="utf-8")
    manifest = Path(regenerate_payload["manifest_path"]).read_text(encoding="utf-8")
    assert "draft title v2" in markdown
    assert "tag-revised" in manifest

    revised_draft_call = next(call for call in fake_generator.calls if call[0] == "draft" and call[1].get("review_comment"))
    assert revised_draft_call[1]["review_comment"] == "封面文案太平，需要更强钩子。"


def test_retro_is_hidden_after_revision_regeneration_until_new_publish_is_approved(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            if payload.get("review_comment"):
                return {"title": "draft title v2", "body_markdown": "# draft v2\n\nbody"}
            return {"title": "draft title v1", "body_markdown": "# draft v1\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            if payload.get("review_comment"):
                return {
                    "title_options": ["title v2"],
                    "cover_prompt": "prompt v2",
                    "cover_copy": "cover copy v2",
                    "social_teaser": "teaser v2",
                }
            return {
                "title_options": ["title v1"],
                "cover_prompt": "prompt v1",
                "cover_copy": "cover copy v1",
                "social_teaser": "teaser v1",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            if payload.get("review_comment"):
                return {"abstract": "abstract v2", "tags": ["tag-v2"], "editor_note": "note v2"}
            return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    approve_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/approve-publish-package",
        json={"reviewer": "chief-editor", "comment": "首版可以发。"},
    )
    assert approve_response.status_code == 200

    retro_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/retro",
        json={
            "performance_rating": 4,
            "summary": "首版承接自然。",
            "wins": ["标题稳定"],
            "gaps": ["封面普通"],
            "next_focus": "下一版强化封面。",
        },
    )
    assert retro_response.status_code == 200

    before_revision = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert before_revision["project"]["current_chain_state"] == "published"
    assert before_revision["publish_package"]["version"] == 1
    assert before_revision["retro"]["summary"] == "首版承接自然。"

    revision_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/request-publish-revision",
        json={"reviewer": "ops", "comment": "封面钩子不够强。"},
    )
    assert revision_response.status_code == 200
    regenerate_response = client.post("/api/projects/office-burnout-recovery-weekly/regenerate-from-review")
    assert regenerate_response.status_code == 202
    regenerate_submit = regenerate_response.json()
    regenerate_task = wait_for_background_task(regenerate_submit["task_id"])
    assert regenerate_task["status"] == "done"
    assert regenerate_task["result"]["version"] == 2

    after_regenerate = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert after_regenerate["project"]["stage"] == "publish_ready"
    assert after_regenerate["project"]["current_chain_state"] == "publish_ready"
    assert after_regenerate["publish_package"]["version"] == 2
    assert after_regenerate["publish_package"]["status"] == "ready"
    assert after_regenerate["retro"] is None

    reapprove_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/approve-publish-package",
        json={"reviewer": "chief-editor", "comment": "二版可以发。"},
    )
    assert reapprove_response.status_code == 200

    after_reapprove = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert after_reapprove["project"]["current_chain_state"] == "published"
    assert after_reapprove["publish_package"]["version"] == 2
    assert after_reapprove["publish_package"]["status"] == "approved"
    assert after_reapprove["retro"] is None


def test_legacy_retro_without_bound_publish_package_version_is_hidden_after_new_package_replaces_it(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            if payload.get("review_comment"):
                return {"title": "draft title v2", "body_markdown": "# draft v2\n\nbody"}
            return {"title": "draft title v1", "body_markdown": "# draft v1\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            if payload.get("review_comment"):
                return {
                    "title_options": ["title v2"],
                    "cover_prompt": "prompt v2",
                    "cover_copy": "cover copy v2",
                    "social_teaser": "teaser v2",
                }
            return {
                "title_options": ["title v1"],
                "cover_prompt": "prompt v1",
                "cover_copy": "cover copy v1",
                "social_teaser": "teaser v1",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            if payload.get("review_comment"):
                return {"abstract": "abstract v2", "tags": ["tag-v2"], "editor_note": "note v2"}
            return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    approve_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/approve-publish-package",
        json={"reviewer": "chief-editor", "comment": "首版可以发。"},
    )
    assert approve_response.status_code == 200

    with workbench._get_connection() as connection:
        recorded_at = workbench._utc_now_iso()
        connection.execute(
            """
            INSERT INTO project_retros (
                project_slug,
                publish_package_version,
                performance_rating,
                summary,
                wins,
                gaps,
                next_focus,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                None,
                4,
                "旧版复盘",
                '["标题稳定"]',
                '["封面普通"]',
                "下一版强化封面。",
                recorded_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO task_logs (task_type, status, entity_slug, entity_type, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "project_retro_recorded",
                "done",
                "office-burnout-recovery-weekly",
                "project",
                recorded_at,
            ),
        )
        connection.commit()

    published_detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert published_detail["retro"]["summary"] == "旧版复盘"

    client.post(
        "/api/projects/office-burnout-recovery-weekly/request-publish-revision",
        json={"reviewer": "ops", "comment": "封面钩子不够强。"},
    )
    regenerate_response = client.post("/api/projects/office-burnout-recovery-weekly/regenerate-from-review")
    assert regenerate_response.status_code == 202
    regenerate_submit = regenerate_response.json()
    regenerate_task = wait_for_background_task(regenerate_submit["task_id"])
    assert regenerate_task["status"] == "done"
    client.post(
        "/api/projects/office-burnout-recovery-weekly/approve-publish-package",
        json={"reviewer": "chief-editor", "comment": "二版可以发。"},
    )

    latest_detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert latest_detail["project"]["current_chain_state"] == "published"
    assert latest_detail["publish_package"]["version"] == 2
    assert latest_detail["retro"] is None


def test_polish_draft_creates_new_draft_version_and_invalidates_downstream(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                return {
                    "title": "draft title polished",
                    "body_markdown": "# polished\n\n更柔和，也更有观点。",
                }
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "统一语气，提炼观点，结尾更克制。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()
    assert polished["project_slug"] == "office-burnout-recovery-weekly"
    assert polished["version"] == 2
    assert polished["outline_version"] == 1
    assert polished["title"] == "draft title polished"

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["project"]["stage"] == "draft_ready"
    assert detail["project"]["current_chain_state"] == "draft_ready"
    assert detail["project"]["next_required_step"] == "generate_assets"
    assert detail["draft"]["version"] == 2
    assert detail["draft"]["title"] == "draft title polished"
    assert detail["assets"] is None
    assert detail["publish_package"] is None

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in versions["drafts"]] == [2, 1]
    assert [item["version"] for item in versions["assets"]] == [1]
    assert [item["version"] for item in versions["publish_packages"]] == [1]

    polished_call = next(call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction"))
    assert polished_call[1]["polish_instruction"] == "统一语气，提炼观点，结尾更克制。"
    assert polished_call[1]["draft"]["title"] == "draft title"


def test_polish_draft_falls_back_to_tone_profile_default_instruction(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {"title": "draft title polished", "body_markdown": "# polished\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    profiles = client.get("/api/tone-profiles").json()
    profile_id = profiles[0]["id"]
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
            "default_polish_instruction": "重写开头和结尾，调整段落连接。",
        },
    )
    assert update_response.status_code == 200

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "   "},
    )
    assert polish_response.status_code == 201

    polished_call = next(call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction"))
    assert polished_call[1]["polish_instruction"] == "重写开头和结尾，调整段落连接。"


def test_diagnose_draft_persists_report_without_mutating_draft(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            if payload.get("polish_instruction"):
                return {
                    "title": "先把身体放回日程里",
                    "body_markdown": "# 先把身体放回日程里\n\n她站在电梯里，先把手机扣回口袋。",
                }
            return {
                "title": "先把身体放回日程里",
                "body_markdown": (
                    "# 先把身体放回日程里\n\n"
                    "她站在电梯里，手机又亮了一下。\n\n"
                    "很多时候，我们总是把自己放在最后。\n\n"
                    "愿你从今天开始，好好爱自己。"
                ),
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a"],
                "cover_prompt": "prompt",
                "cover_copy": "copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {"abstract": "abstract", "tags": ["tag"], "editor_note": "note"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    draft_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    assert draft_response.status_code == 201
    assert draft_response.json()["version"] == 1

    initial_detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert initial_detail["diagnosis_report"] is None
    assert initial_detail["draft"]["version"] == 1
    assert initial_detail["draft_quality_summary"]["draft_version"] == 1
    assert initial_detail["draft_quality_summary"]["diagnosis_version"] is None

    diagnosis_response = client.post("/api/projects/office-burnout-recovery-weekly/diagnose-draft")
    assert diagnosis_response.status_code == 201
    diagnosis = diagnosis_response.json()
    assert diagnosis["project_slug"] == "office-burnout-recovery-weekly"
    assert diagnosis["draft_version"] == 1
    assert diagnosis["version"] == 1
    assert diagnosis["opening_strength"] in {"weak", "medium", "strong"}
    assert diagnosis["scene_specificity"] in {"weak", "medium", "strong"}
    assert diagnosis["ai_fingerprint_level"] in {"low", "medium", "high"}
    assert diagnosis["upstream_findings"]
    assert diagnosis["downstream_findings"]
    assert diagnosis["recommended_next_action"]
    assert "内容诊断目标精修" in diagnosis["recommended_polish_instruction"]

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["draft"]["version"] == 1
    assert detail["diagnosis_report"]["version"] == 1
    assert detail["diagnosis_report"]["draft_version"] == 1
    assert detail["draft_quality_summary"]["draft_version"] == 1
    assert detail["draft_quality_summary"]["diagnosis_version"] == 1
    assert detail["draft_quality_summary"]["recommended_next_action"] == diagnosis["recommended_next_action"]
    assert detail["draft_quality_summary"]["recommended_polish_instruction"] == diagnosis["recommended_polish_instruction"]

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in versions["diagnosis_reports"]] == [1]
    assert versions["directional_polish_links"] == []


def test_polish_draft_can_use_diagnosis_objective_and_records_link(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                return {
                    "title": "身体会替你重新排序",
                    "body_markdown": "# 身体会替你重新排序\n\n她把手机扣在桌上，先给自己倒了一杯水。",
                }
            return {
                "title": "先把身体放回日程里",
                "body_markdown": (
                    "# 先把身体放回日程里\n\n"
                    "她站在电梯里，手机又亮了一下。\n\n"
                    "她没有马上回消息，而是先把复查提醒重新置顶。\n\n"
                    "那一刻她才发现，身体已经替她把事情重新排了一次顺序。"
                ),
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a"],
                "cover_prompt": "prompt",
                "cover_copy": "copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {"abstract": "abstract", "tags": ["tag"], "editor_note": "note"}

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    diagnosis = client.post("/api/projects/office-burnout-recovery-weekly/diagnose-draft").json()

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={
            "instruction": None,
            "diagnosis_report_version": diagnosis["version"],
            "objective_key": diagnosis["recommended_next_action"],
        },
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()
    assert polished["version"] == 2
    assert polished["title"] == "身体会替你重新排序"

    polished_call = next(call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction"))
    assert "内容诊断目标精修" in polished_call[1]["polish_instruction"]
    assert polished_call[1]["draft"]["title"] == "先把身体放回日程里"

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in versions["drafts"]] == [2, 1]
    assert versions["diagnosis_reports"][0]["version"] == diagnosis["version"]
    assert versions["directional_polish_links"] == [
        {
            "project_slug": "office-burnout-recovery-weekly",
            "source_draft_version": 1,
            "target_draft_version": 2,
            "diagnosis_version": diagnosis["version"],
            "objective_key": diagnosis["recommended_next_action"],
            "objective_summary": diagnosis["objective_summary"],
            "created_at": polished["created_at"],
        }
    ]


def test_generate_creative_review_report_works_for_legacy_project() -> None:
    detail_response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert detail_response.status_code == 200
    assert detail_response.json()["creative_review_report"] is None

    report_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-creative-review-report")
    assert report_response.status_code == 201
    report = report_response.json()
    assert report["project_slug"] == "office-burnout-recovery-weekly"
    assert report["version"] == 1
    assert report["strategy_version"] is None
    assert report["draft_version"] is None
    assert "暂无记录，本报告只汇总当前项目已有事实" in report["summary_markdown"]
    assert report["retained_lessons"][0]["pattern_type"] == "review_note"

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["creative_review_report"]["version"] == 1

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in versions["creative_review_reports"]] == [1]


def test_generate_creative_review_report_summarizes_strategy_diagnosis_and_revision(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            if payload.get("polish_instruction"):
                return {
                    "title": "身体会替你重新排序",
                    "body_markdown": (
                        "# 身体会替你重新排序\n\n"
                        "她把手机扣在桌上，先给自己倒了一杯水。\n\n"
                        "这一次，她没有把复查提醒往后拖。"
                    ),
                }
            return {
                "title": "先把身体放回日程里",
                "body_markdown": (
                    "# 先把身体放回日程里\n\n"
                    "她站在电梯里，手机又亮了一下。\n\n"
                    "她没有马上回消息，而是先把复查提醒重新置顶。"
                ),
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a"],
                "cover_prompt": "prompt",
                "cover_copy": "copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {"abstract": "abstract", "tags": ["tag"], "editor_note": "note"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-strategy-package").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/adopt-strategy-card/1").status_code == 200
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-outline").status_code == 201
    assert client.post("/api/projects/office-burnout-recovery-weekly/generate-draft").status_code == 201
    diagnosis = client.post("/api/projects/office-burnout-recovery-weekly/diagnose-draft").json()
    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={
            "instruction": None,
            "diagnosis_report_version": diagnosis["version"],
            "objective_key": diagnosis["recommended_next_action"],
        },
    )
    assert polish_response.status_code == 201
    assert polish_response.json()["version"] == 2

    report_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-creative-review-report")
    assert report_response.status_code == 201
    report = report_response.json()
    assert report["strategy_version"] == 1
    assert report["draft_version"] == 2
    assert "## 前写作策略" in report["summary_markdown"]
    assert "## 诊断与修订" in report["summary_markdown"]
    assert "草稿 v1 -> v2" in report["summary_markdown"]
    assert diagnosis["objective_summary"] in report["summary_markdown"]
    lesson_types = {lesson["pattern_type"] for lesson in report["retained_lessons"]}
    assert "opening" in lesson_types
    assert "revision_objective" in lesson_types
    assert "revision_trace" in lesson_types

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["creative_review_report"]["version"] == 1
    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert versions["creative_review_reports"][0]["version"] == 1


def test_promote_creative_pattern_from_review_report_and_list_library() -> None:
    report = client.post("/api/projects/office-burnout-recovery-weekly/generate-creative-review-report").json()
    assert report["retained_lessons"]

    promote_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/promote-creative-pattern",
        json={
            "report_version": report["version"],
            "lesson_index": 0,
            "title": "旧项目复盘入口",
            "pattern_type": "review-note",
            "intended_use": "适合资料不完整的旧项目先整理事实。",
            "caution_notes": "不要直接复用旧稿内容。",
        },
    )
    assert promote_response.status_code == 201
    promoted = promote_response.json()
    assert promoted["source_project_slug"] == "office-burnout-recovery-weekly"
    assert promoted["source_report_version"] == report["version"]
    assert promoted["title"] == "旧项目复盘入口"
    assert promoted["pattern_type"] == "review-note"
    assert promoted["status"] == "active"

    duplicate_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/promote-creative-pattern",
        json={
            "report_version": report["version"],
            "lesson_index": 0,
            "title": "旧项目复盘入口",
            "pattern_type": "review-note",
            "intended_use": "适合资料不完整的旧项目先整理事实。",
            "caution_notes": "不要直接复用旧稿内容。",
        },
    )
    assert duplicate_response.status_code == 201
    assert duplicate_response.json()["id"] == promoted["id"]

    list_response = client.get("/api/creative-patterns")
    assert list_response.status_code == 200
    patterns = list_response.json()
    assert [item["id"] for item in patterns] == [promoted["id"]]

    detail_response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert [item["id"] for item in detail["reusable_patterns"]] == [promoted["id"]]

    filtered_response = client.get("/api/creative-patterns?pattern_type=review-note")
    assert filtered_response.status_code == 200
    assert [item["id"] for item in filtered_response.json()] == [promoted["id"]]

    missing_filter_response = client.get("/api/creative-patterns?pattern_type=opening")
    assert missing_filter_response.status_code == 200
    assert missing_filter_response.json() == []


def test_promote_creative_pattern_rejects_invalid_lesson_index() -> None:
    report = client.post("/api/projects/office-burnout-recovery-weekly/generate-creative-review-report").json()

    promote_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/promote-creative-pattern",
        json={"report_version": report["version"], "lesson_index": 99},
    )
    assert promote_response.status_code == 400
    assert promote_response.json()["detail"] == "Lesson index is out of range"


def test_polish_draft_retries_when_structure_headings_are_lost(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                instruction = str(payload["polish_instruction"])
                if "上一次改写发生了结构漂移" in instruction:
                    return {
                        "title": "别把日子过反了",
                        "body_markdown": (
                            "# 别把日子过反了\n\n"
                            "很多事情，都是后来才知道代价。\n\n"
                            "别用健康换明天\n\n"
                            "朋友阿杰曾是个工作狂，后来才知道身体停下来，别的安排也会一起停。\n\n"
                            "别等失去才懂珍惜\n\n"
                            "外婆突然离世后，我翻遍手机，才发现很多平常时刻都没留下来。\n\n"
                            "别把幸福寄托在“等以后”\n\n"
                            "有人攒了半辈子钱，等到退休却已经没有力气按原计划生活。"
                        ),
                    }
                return {
                    "title": "很多代价，都是后来才知道的",
                    "body_markdown": (
                        "# 很多代价，都是后来才知道的\n\n"
                        "先写一段泛感慨。\n\n"
                        "再写一段泛感慨。\n\n"
                        "最后写一段泛感慨。"
                    ),
                }
            return {
                "title": "别把日子过反了",
                "body_markdown": (
                    "# 别把日子过反了\n\n"
                    "开头总述。\n\n"
                    "别用健康换明天\n\n"
                    "朋友阿杰曾是个工作狂。\n\n"
                    "别等失去才懂珍惜\n\n"
                    "外婆突然离世后，我翻遍手机。\n\n"
                    "别把幸福寄托在“等以后”\n\n"
                    "有人攒了半辈子钱。"
                ),
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    calls_before_manual_polish = len(fake_generator.calls)

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert polished["title"] == "别把日子过反了"
    assert "别用健康换明天" in polished["body_markdown"]
    assert "别等失去才懂珍惜" in polished["body_markdown"]
    assert "别把幸福寄托在“等以后”" in polished["body_markdown"]

    manual_polish_calls = fake_generator.calls[calls_before_manual_polish:]
    polish_calls = [
        call for call in manual_polish_calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    instructions = [str(call[1]["polish_instruction"]) for call in polish_calls]
    assert len(polish_calls) >= 2
    assert instructions[0] == "降低模板感，但保留原稿结构。"
    assert any("上一次改写发生了结构漂移" in instruction for instruction in instructions[1:])
    assert any("这次必须原样保留以下小节标题" in instruction for instruction in instructions[1:])


def test_polish_draft_retries_when_result_is_over_smoothed(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                instruction = str(payload["polish_instruction"])
                if "上一次改写虽然保住了结构，但把原稿磨得太顺" in instruction:
                    return {
                        "title": "别把日子过反了",
                        "body_markdown": (
                            "# 别把日子过反了\n\n"
                            "有些代价，是后来才慢慢认出来的。\n\n"
                            "别用健康换明天\n\n"
                            "朋友阿杰曾是个工作狂，总觉得这阵子先熬过去，身体的账以后再补。\n\n"
                            "别等失去才懂珍惜\n\n"
                            "外婆突然离世后，我翻遍手机，才发现连一张像样的合照都没有。\n\n"
                            "别把幸福寄托在“等以后”\n\n"
                            "有人攒了半辈子钱，等到退休却已经没有力气按原计划生活。"
                        ),
                    }
                return {
                    "title": "别把日子过反了",
                    "body_markdown": (
                        "# 别把日子过反了\n\n"
                        "有些代价，往往都是后来才看清。\n\n"
                        "别用健康换明天\n\n"
                        "很多时候，我们总以为先扛过这一阵，身体会自己原谅我们。阿杰也是这么想的。\n\n"
                        "别等失去才懂珍惜\n\n"
                        "说到底，人最容易高估的，就是来日方长。外婆走后，我翻遍手机，才发现很多时刻没留下来。\n\n"
                        "别把幸福寄托在“等以后”\n\n"
                        "很多时候，我们把想做的事一直往后放，最后连原本的心气也一起放没了。"
                    ),
                }
            return {
                "title": "别把日子过反了",
                "body_markdown": (
                    "# 别把日子过反了\n\n"
                    "开头总述。\n\n"
                    "别用健康换明天\n\n"
                    "朋友阿杰曾是个工作狂，总说等这个项目结束就休息。\n\n"
                    "别等失去才懂珍惜\n\n"
                    "外婆突然离世后，我翻遍手机，才发现连一张像样的合照都没有。\n\n"
                    "别把幸福寄托在“等以后”\n\n"
                    "有人攒了半辈子钱，等到退休却已经没有力气按原计划生活。"
                ),
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    tone_profile = workbench.get_active_tone_profile()
    seeded_body = (
        "# 别把日子过反了\n\n"
        "夜里静下来时，人会知道什么该先顾住。\n\n"
        "阿杰在医院醒来后，第一次把手机扣在了床头柜上。\n\n"
        "外婆走后，我才明白有些日常一旦错过去，就补不回来了。\n\n"
        "想做的事，别全留给以后。"
    )
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count,
                created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                1,
                1,
                "别把日子过反了",
                seeded_body,
                len(seeded_body),
                workbench._utc_now_iso(),
                "manual_seed",
                tone_profile.id,
                tone_profile.name,
            ),
        )
        connection.commit()

    calls_before_manual_polish = len(fake_generator.calls)

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构和案例。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert polished["title"] == "别把日子过反了"
    assert "很多时候，我们总以为先扛过这一阵" not in polished["body_markdown"]
    assert "说到底" not in polished["body_markdown"]
    assert "阿杰" in polished["body_markdown"]
    assert "外婆" in polished["body_markdown"]

    polish_calls = [call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")]
    instructions = [str(call[1]["polish_instruction"]) for call in polish_calls]
    assert len(polish_calls) >= 2
    assert instructions[0] == "降低模板感，但保留原稿结构和案例。"
    assert any("上一次改写虽然保住了结构，但把原稿磨得太顺" in instruction for instruction in instructions[1:])
    assert any("很多时候 / 说到底" in instruction for instruction in instructions[1:])


def test_polish_draft_retries_when_ai_flavor_still_remains(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "去模板化重写" in instruction:
                    return {
                        "title": "别把日子过反了",
                        "body_markdown": (
                            "# 别把日子过反了\n\n"
                            "夜里静下来时，人会知道什么该先顾住。\n\n"
                            "阿杰在医院醒来后，第一次把手机扣在了床头柜上。\n\n"
                            "外婆走后，我才明白有些日常一旦错过去，就补不回来了。\n\n"
                            "想做的事，别全留给以后。"
                        ),
                    }
                if "上一次精修后，模板风险还没压够" in instruction:
                    return {
                        "title": "别把日子过反了",
                        "body_markdown": (
                            "# 别把日子过反了\n\n"
                            "夜里静下来时，人最容易看见自己把哪些东西一直往后拖。\n\n"
                            "阿杰总说忙完这阵再休息，可身体不会替人无限期垫账。\n\n"
                            "外婆走后，我翻手机才知道，有些当时没留住的时刻，后来就再也补不上了。\n\n"
                            "想做的事，能今天做一点，就别全放到以后。"
                        ),
                    }
                return {
                    "title": "别把日子过反了",
                    "body_markdown": (
                        "# 别把日子过反了\n\n"
                        "日子真正难的，不是忙，而是总把重要的东西放到最后面。\n\n"
                        "不是你不想停下来，而是你总觉得还能再撑一阵。阿杰也是这样。\n\n"
                        "外婆走后，我才知道那些平常时刻一旦过去，就不会重新回来。\n\n"
                        "从今天开始，别再把重要的东西推到以后。"
                    ),
                }
            return {
                "title": "别把日子过反了",
                "body_markdown": (
                    "# 别把日子过反了\n\n"
                    "不是等失去才懂痛，而是很多重要的东西，早就在日常里被慢慢放后了。\n\n"
                    "阿杰总说等这个项目结束就休息。\n\n"
                    "外婆突然离世后，我翻遍手机，才发现连一张像样的合照都没有。\n\n"
                    "从今天开始，别把最重要的东西押给以后。"
                ),
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    calls_before_manual_polish = len(fake_generator.calls)

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构和案例。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert polished["title"] == "别把日子过反了"
    assert "从今天开始" not in polished["body_markdown"]
    assert "不是你不想停下来" not in polished["body_markdown"]
    assert "阿杰" in polished["body_markdown"]
    assert "外婆" in polished["body_markdown"]

    manual_polish_calls = fake_generator.calls[calls_before_manual_polish:]
    polish_calls = [
        call for call in manual_polish_calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) == 3
    assert polish_calls[0][1]["polish_instruction"] == "降低模板感，但保留原稿结构和案例。"
    instructions = [str(call[1]["polish_instruction"]) for call in polish_calls[1:]]
    assert any("上一次精修后，模板风险还没压够" in instruction for instruction in instructions)
    assert any("最后一轮局部清理" in instruction for instruction in instructions)
    assert any("不要把开头第一屏和各小节首段统一扩成新的氛围场景" in instruction for instruction in instructions)


def test_remaining_ai_flavor_retry_triggers_for_low_score_not_ab_residue() -> None:
    source_body = (
        "# 别把日子过反了\n\n"
        "阿杰晕倒之后，才肯承认自己已经很久没有认真休息。\n\n"
        "外婆走后，我翻手机时才知道，很多平常时刻原来并不会重来。\n\n"
        "想做的事，别一直往后拖。"
    )
    candidate_body = (
        "# 别把日子过反了\n\n"
        "朋友阿杰总说等这个项目结束就休息。后来他躺在病床上才意识到，不是不累，是一直没给自己停下来的机会。\n\n"
        "外婆走后，我翻手机才知道，有些想留下来的时刻，当时并没有认真接住。不是不在意，是总把以后想得太宽。\n\n"
        "很多事看着都能往后放，可真正先被拖走的，往往是身体和关系。"
    )

    assert workbench._should_retry_for_remaining_ai_flavor(
        source_title="别把日子过反了",
        source_markdown=source_body,
        candidate_title="别把日子过反了",
        candidate_markdown=candidate_body,
    )


def test_remaining_ai_flavor_retry_triggers_for_moderate_score_heavy_not_ab_residue() -> None:
    source_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "你以为自己缺的是技巧，后来才发现，不是不懂，而是根本没有能量。\n\n"
        "很多关系迟迟没有转机，不是因为谁完全不在乎，也不是因为道理讲不明白，而是两个人都太累了。\n\n"
        "所以，关系里最麻烦的，往往不是没有爱，而是没有余力。\n\n"
        "不是不想靠近，而是连自己都快顾不上。\n\n"
        "不是不愿意改变，而是身体和情绪已经长期处在透支里。\n\n"
        "这时候最先要补的，常常不是沟通术，而是能量。"
    )
    candidate_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "看到这里，很多人会先把问题归到“不会沟通”上。可真落到自己身上，卡住的往往不是方法有没有学过，而是那口气提不上来。\n\n"
        "关系推不动的时候，最常见的不是完全不在乎，而是人已经累得没有多余的心力。\n\n"
        "你会发现，关系卡住时，常常是三件事叠在一起：\n\n"
        "✔ 意愿有\n\n"
        "✔ 方法也知道\n\n"
        "✔ 但没有能量\n\n"
        "意愿有，意味着你不是不想好。\n\n"
        "方法也知道，意味着你不是没学过。\n\n"
        "所以，关系里最麻烦的，往往不是没有爱，而是没有余力。不是不想靠近，而是连自己都快顾不上。不是不愿意改变，而是身体和情绪已经长期处在透支里。\n\n"
        "这时候最先要补的，常常不是沟通术，而是能量。"
    )

    assert workbench._should_retry_for_remaining_ai_flavor(
        source_title="关系卡住的本质：意愿有、懂方法、但无能量",
        source_markdown=source_body,
        candidate_title="关系卡住的本质：意愿有、懂方法、但无能量",
        candidate_markdown=candidate_body,
    )


def test_remaining_ai_flavor_retry_triggers_for_internal_pressure_explainer_shell_without_not_ab_residue() -> None:
    source_body = (
        "# 等到身体先报警，才发现自己一直排在最后\n\n"
        "体检提醒亮起时，她先划掉页面，想着这周忙完再说。\n\n"
        "那阵子她照常回消息、照常交东西，也照常把饭和觉往后挪。\n\n"
        "真正先被拖走的，不是待办，而是她自己。"
    )
    candidate_body = (
        "# 等到身体先报警，才发现自己一直排在最后\n\n"
        "你以为自己只是累吗？有一类疲惫，休息一天也缓不过来。别人一有需要，你立刻接住；轮到自己的睡眠、情绪、体检和那顿该好好吃的饭，你总能往后再挪一点。\n\n"
        "它一开始并不惊人，甚至很像负责。工作临时加项，你先改；家里有人要你搭把手，你先去；关系里气氛不对，你先安抚。短时间里，事情被处理了，场面也稳住了，后面留下来的，是睡眠被切碎，身体信号被拖延，情绪越来越晚才轮到被照顾。\n\n"
        "成年人的生活里，最会抢位置的，几乎都是紧急的东西。消息要回，节点要赶，孩子和父母的问题要接，伴侣的情绪也需要回应。你的需要通常没有那么大的声量，它不敲门，只是在肩颈发紧、经期紊乱、胃口变差、耐心变短时提醒你。\n\n"
        "很多亏空，不是一天形成的。你只是一次次把那句“我现在也不太行”压回去，久了，身体和情绪就先替你停下来。"
    )

    assert workbench._should_retry_for_remaining_ai_flavor(
        source_title="等到身体先报警，才发现自己一直排在最后",
        source_markdown=source_body,
        candidate_title="等到身体先报警，才发现自己一直排在最后",
        candidate_markdown=candidate_body,
    )


def test_remaining_ai_flavor_retry_triggers_for_short_judgment_cadence_residue() -> None:
    source_body = (
        "# 她后来没再把真心话都留到夜里\n\n"
        "她一整天都很忙，真正想回的人，总被她拖到最后。\n\n"
        "后来她试着在白天先回一条消息。"
    )
    candidate_body = (
        "# 她后来没再把真心话都留到夜里\n\n"
        "电梯快合上的时候，她低头看了眼手机。\n\n"
        "置顶对话里躺着两条昨晚没回完的消息。朋友问她这周要不要见面，妈妈发来一张家里阳台新开的花。她的手指停在屏幕上方，楼层往下跳，她先回了工作群里的“收到”，又把那两个对话按灭。\n\n"
        "白天的她并没有闲着。\n\n"
        "消息很多，页面一直在跳。确认排期、对接流程、改表格、补一句“辛苦了”、再接住新的安排。她能回的大多是这种话：明确，简短，不需要情绪，也不需要把自己放进去。\n\n"
        "聊天框也会变得很难打开。\n\n"
        "她不是没话说，是那种要把心思拿出来、把语气放软、把一句普通回复变成真正的交流，这件事忽然很重。光是想一想，就已经觉得累。\n\n"
        "后来她有过个很小的变化。\n\n"
        "午休快结束时，她没有先去刷工作群，而是靠在茶水间窗边，回了朋友那条约见面的消息。没写很多，只是认真定了个周六下午。\n\n"
        "这一步很难。\n\n"
        "因为她清楚，一旦停下来，很多被压着的东西会一起冒头。委屈、烦躁、亏空感，还有那种说不出口的失望。"
    )

    assert workbench._should_retry_for_remaining_ai_flavor(
        source_title="她后来没再把真心话都留到夜里",
        source_markdown=source_body,
        candidate_title="她后来没再把真心话都留到夜里",
        candidate_markdown=candidate_body,
    )


def test_remaining_ai_flavor_retry_triggers_for_embedded_banner_residue() -> None:
    source_body = (
        "# 别把日子过反了\n\n"
        "阿杰晕倒之后，才肯承认自己已经很久没有认真休息。\n\n"
        "外婆走后，我翻手机时才知道，很多平常时刻原来并不会重来。\n\n"
        "想做的事，别一直往后拖。"
    )
    candidate_body = (
        "# 别把日子过反了\n\n"
        "电梯门快合上时，她抬手挡了下。门弹开，白光照着空空的轿厢。手机在掌心震了两次，聊天框停在那句没发出去的话上：这阵子有点忙，忙完再联系。\n\n"
        "这条线常常就是这么出来的。休息往后挪，情绪往后挪，身体给的提醒也往后挪。困了，先把表格做完；胃空着，先把会开完；体检预约改了又改，心里想着下周总能腾出空。\n\n"
        "关系也是这样淡下去的。朋友问近况，本来只是想听你说两句真的；家里来消息，也未必是催你做什么。可聊天框停在“改天见”后面太久，下一次点开时，里面会多出层生分。\n\n"
        "真正磨人的，往往不在最忙的那几天。忙的时候，人是被推着走的，顾不上细想。后面反复冒出来的，是那些原本能当时回掉、当时照顾、当时在场的时刻，被自己轻轻推开了。"
    )

    assert workbench._should_retry_for_remaining_ai_flavor(
        source_title="别把日子过反了",
        source_markdown=source_body,
        candidate_title="别把日子过反了",
        candidate_markdown=candidate_body,
    )


def test_remaining_ai_flavor_retry_triggers_for_explainer_shell_residue_only() -> None:
    candidate_body = (
        "# 等到身体先报警，才发现自己一直排在最后\n\n"
        "体检单上多了一行红字，你盯着下周那场会，想的还是能不能照常开。情绪忽然失控那次，你也没把它当回事，只当自己这阵子没休息好。连休息都变成任务的人，最容易把“累”理解成忙，把“撑不住”理解成自己还不够能扛。成年后的很多疲惫，起点往往更早：你已经习惯了，谁都可以排在你前面，只有你自己，总往后挪。\n\n"
        "这个顺序，不是一夜之间改掉的。通常是从很小的地方开始。消息先回，工作先交，家里的事先补上，朋友的请求先答应。轮到自己，复查可以下周再去，饭晚一点吃也行，睡眠先欠着，衣服鞋子还能将就。外面给你的反馈很直接，回得快、做得多、顶得住，就会被夸靠谱、懂事、顾全大局。照顾自己没那么立刻，少休一次，不会马上出大事；少吃一顿，也还能撑完今天。人就是在这种“暂时没问题”里，把自己一点点放到了最后。\n\n"
        "最难受的地方还不在忙。忙有时是阶段性的，过去就过去了。真正消耗人的，是你慢慢默认了：自己的不舒服可以先放一放，自己的需要可以再等等，自己的委屈没那么要紧。这个默认，会把人训练得很麻木。你明明已经发烧，还在改方案；经期疼得站不久，还在说没事；一句话已经冒犯了你，你先顾的是别把气氛弄僵。你一次次退后，不全是善良，也夹着一种很深的熟悉感：只要我还能扛，我就先扛。久了，连你自己都开始把这件事当成理所当然。\n\n"
        "很多女人的亏欠感，就是在这里长出来的。你总觉得自己还不够好，休息像偷懒，拒绝像亏待别人，花时间在自己身上，还要先补一句“我最近真的有点累”。这背后常常是一种价值感绑定：你把自己有没有用，看得比自己舒不舒服更重要。别人需要你，你会有存在感；轮到你需要被照顾，第一反应却常常是收回去。你怕麻烦人，怕显得矫情，怕一停下来，别人会失望。可身体不会配合这套逻辑。它只会在你长期忽略它的时候，用失眠、暴躁、心慌、内耗把账一点点送回来。\n\n"
        "人往往要等到真出问题，才承认自己丢了东西。请假住院那几天，你会忽然发现，少了你，很多事也还能转；一段一直靠你兜底的关系，一旦你不再提供情绪劳动，对方未必真会站出来接住你。那一刻你才看清，过去那些被你牺牲掉的睡眠、体力、兴趣、体面，都是从自己身上硬扣出去的。失去感会疼，疼也有用。它逼你承认，你早就欠了自己很多。\n\n"
        "还有一种失衡，表面看很小，拖久了最伤。医生让你三个月后复查，你拖成了八个月；牙疼一阵一阵，你总说过两天再去；心里已经很压抑了，还是把假期让给“更重要的安排”；一段关系里你总负责理解、安抚、兜底，轮到你难受，对方只回一句“你别想太多”。这些都容易被归进“小事不算事”。可小事重复得够久，就会改写一个人对自己的态度。你会越来越难分清，自己到底是在体谅别人，还是已经习惯亏待自己。\n\n"
        "把自己往前放，不用等到辞职、搬家、彻底翻篇那种大动作。成年人的止损，常常先从顺序改起。身体不舒服，就先去看；已经累到说话带火气，就先停一停；不属于你的额外责任，少接一点；能晚回的消息，晚回；周末留半天给自己，不拿来补所有人的需求。关键在于让自己看见：我的事也有名字，我的感受也占位置。我可以照顾人，也可以先照顾我自己。\n\n"
        "这件事刚开始，常常会有阻力。你会不习惯，会想把刚留出来的时间再让出去，会在拒绝别人之后冒出一点歉意。这不代表你做错了，只是旧顺序还在往回拽。你以前总把自己垫在最下面，大家都站稳了，只有你一直悬着。现在只是把那块垫子抽回来一点，让自己能落地。\n\n"
        "成年后最该补上的，是别再拿自己垫底。先去复查，先把晚饭吃完，先把那句“这次我来不了”发出去。做一件就够了。你会慢慢认出来，善待自己不是附加项，它本来就该在你的生活里面。"
    )

    assert workbench._should_retry_for_remaining_ai_flavor(
        source_title="善待自己，好好爱自己",
        source_markdown="原文",
        candidate_title="等到身体先报警，才发现自己一直排在最后",
        candidate_markdown=candidate_body,
    )


def test_pick_better_ai_flavor_candidate_prefers_lower_residual_burden_on_tied_score() -> None:
    current_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "你以为自己缺的是技巧，后来才发现，不是不懂，而是根本没有能量。\n\n"
        "很多关系真正难的，不是突然变了心，是之前压下去的委屈、疲惫、防备，慢慢把人拖住了。\n\n"
        "关系卡住时，最常见的样子往往是三件事同时存在：\n\n"
        "意愿有。\n\n"
        "方法也知道。\n\n"
        "但人已经空了。\n\n"
        "你会发现，很多时候不是判断失灵，而是整个人都在防守；不是你突然变得尖锐，而是神经已经很薄。\n\n"
        "这时候最先该补的，常常不是沟通术，而是余力。"
    )
    retried_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "很多人一遇到关系卡住，就先去找沟通方法。可真到自己身上，最先掉线的，常常不是技巧，而是余力。\n\n"
        "人累的时候，心会变窄，话也会变硬。你不是没学过，是当下已经没有多余的稳定；不是失望，而是疲惫在前面顶着。\n\n"
        "关系推不动时，常见的不是谁彻底不在乎，而是两个人都已经没剩多少缓冲。\n\n"
        "意愿还在。\n\n"
        "方法也懂。\n\n"
        "可人已经快空了。\n\n"
        "所以这时候最先要补的，不该只是沟通术，还得先把睡眠、情绪和身体那点底子慢慢接回来。"
    )

    current_summary = workbench.evaluate_ai_flavor_risk(
        title="关系卡住的本质：意愿有、懂方法、但无能量",
        body_markdown=current_body,
    )
    retried_summary = workbench.evaluate_ai_flavor_risk(
        title="关系卡住的本质：意愿有、懂方法、但无能量",
        body_markdown=retried_body,
    )
    assert current_summary.score == retried_summary.score
    assert len(current_summary.hits) == len(retried_summary.hits)

    chosen_markdown, chosen_title = workbench._pick_better_ai_flavor_candidate(
        current_title="关系卡住的本质：意愿有、懂方法、但无能量",
        current_markdown=current_body,
        retried_title="关系卡住的本质：意愿有、懂方法、但无能量",
        retried_markdown=retried_body,
    )

    assert chosen_title == "关系卡住的本质：意愿有、懂方法、但无能量"
    assert chosen_markdown == retried_body


def test_pick_better_ai_flavor_candidate_prefers_lower_reference_score_when_cleaned_scores_tie(
    monkeypatch,
) -> None:
    current_body = "# 当前候选\n\n她看着消息，没有立刻回。"
    retried_body = "# 重试候选\n\n她看着消息，先把手机扣在桌上。"
    current_reference_body = "# 当前原始候选\n\n很多时候，人会先把话收回去。"
    retried_reference_body = "# 重试原始候选\n\n电梯快合上的时候，她先按住了那口气。"

    score_map = {
        current_body: 0,
        retried_body: 0,
        current_reference_body: 28,
        retried_reference_body: 10,
    }

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        return SimpleNamespace(
            score=score_map[body_markdown],
            level="低",
            hits=[],
            suggestions=[],
        )

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)

    chosen_markdown, chosen_title = workbench._pick_better_ai_flavor_candidate(
        current_title="当前候选",
        current_markdown=current_body,
        retried_title="重试候选",
        retried_markdown=retried_body,
        current_reference_title="当前原始候选",
        current_reference_markdown=current_reference_body,
        retried_reference_title="重试原始候选",
        retried_reference_markdown=retried_reference_body,
    )

    assert chosen_title == "重试候选"
    assert chosen_markdown == retried_body


def test_pick_better_ai_flavor_candidate_prefers_lower_cleanup_cost_when_scores_tie(
    monkeypatch,
) -> None:
    current_body = "# 当前候选\n\n她把消息先按灭了。"
    retried_body = "# 重试候选\n\n她把消息扣在桌上。"
    reference_body = "# 共同参考候选\n\n她先没有开口。"

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        return SimpleNamespace(
            score=0 if body_markdown in {current_body, retried_body, reference_body} else 0,
            level="低",
            hits=[],
            suggestions=[],
        )

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)

    chosen_markdown, chosen_title = workbench._pick_better_ai_flavor_candidate(
        current_title="当前候选",
        current_markdown=current_body,
        retried_title="重试候选",
        retried_markdown=retried_body,
        current_reference_title="共同参考候选",
        current_reference_markdown=reference_body,
        retried_reference_title="共同参考候选",
        retried_reference_markdown=reference_body,
        current_cleanup_applied=True,
        current_cleanup_changed_steps=3,
        retried_cleanup_applied=True,
        retried_cleanup_changed_steps=1,
    )

    assert chosen_title == "重试候选"
    assert chosen_markdown == retried_body


def test_pick_better_ai_flavor_candidate_prefers_non_over_smoothed_branch_for_tracked_article(
    monkeypatch,
) -> None:
    current_body = "# 当前候选\n\n过度顺滑正文"
    retried_body = "# 重试候选\n\n保留一点毛边的正文"

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        return SimpleNamespace(score=0, level="低", hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)
    monkeypatch.setattr(
        workbench,
        "_looks_like_over_smoothed_tracked_article_candidate",
        lambda markdown: markdown == current_body,
    )

    chosen_markdown, chosen_title = workbench._pick_better_ai_flavor_candidate(
        current_title="当前候选",
        current_markdown=current_body,
        retried_title="重试候选",
        retried_markdown=retried_body,
        source_type="tracked_article",
    )

    assert chosen_title == "重试候选"
    assert chosen_markdown == retried_body


def test_pick_better_article_shell_candidate_prefers_non_over_smoothed_retry(
    monkeypatch,
) -> None:
    current_body = "# 当前候选\n\n过度顺滑正文"
    retried_body = "# 重试候选\n\n保留一点毛边的正文"

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        return SimpleNamespace(score=0, level="低", hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)
    monkeypatch.setattr(
        workbench,
        "_looks_like_over_smoothed_tracked_article_candidate",
        lambda markdown: markdown == current_body,
    )

    chosen_markdown, chosen_title = workbench._pick_better_article_shell_candidate(
        current_title="当前候选",
        current_markdown=current_body,
        retried_title="重试候选",
        retried_markdown=retried_body,
    )

    assert chosen_title == "重试候选"
    assert chosen_markdown == retried_body


def test_finalize_initial_draft_candidate_exposes_pre_cleanup_reference_and_cleanup_cost(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        workbench,
        "_maybe_compress_draft_output",
        lambda **kwargs: (kwargs["body_markdown"], kwargs["title"]),
    )
    monkeypatch.setattr(
        workbench,
        "_maybe_auto_polish_ai_flavor_draft_output",
        lambda **kwargs: (kwargs["body_markdown"], kwargs["title"]),
    )

    candidate_title = "她在电梯镜子里补了口红，却把胸口那阵闷意按了回去"
    candidate_body = (
        "电梯门快合上的时候，她抬手拦了一下，另一只手还拿着口红。镜子里那张脸被顶灯照得有点白，她抿了抿唇，把颜色补匀，顺手按住胸口那阵发闷。不是很疼，更像有块东西横在那里，气吸不满。手机屏幕亮着，待办列表最上面那行写着：10:00 周会。\n\n"
        "门开了，会议室在走廊尽头。她边走边把口红塞回包里，心里想的是，今天先把会开完再说。\n\n"
        "很多提醒，最早都长得不吓人。\n\n"
        "先是动作变慢。群消息弹出来，她看完，没有立刻回，过了几分钟再点开，又从头看了一遍，还是没想好怎么接。明明字都认识，脑子却像隔着层雾。对面催了一句“在吗”，她才赶紧回过去，手指打字很快，内容却比平时更短，像在补交作业。\n\n"
        "这样的停顿一多，周围人先感到的是不顺。工作对接的人会追问，家里人会说她最近老走神。她自己也察觉到了，于是开始补：白天加一杯冰美式，晚上把没做完的事往后挪，想着再熬两个小时，节奏就能拉回来。胸口闷、回消息慢、说话要想半秒，都被她归到同一类——这阵子太忙了。\n\n"
        "可身体不太认这个说法。\n\n"
        "咖啡把人往上拎，晚上却更难真正睡沉。第二天起床更钝，洗脸时盯着镜子发会儿呆，才想起来护肤做到哪步。越想把效率补回去，白天那层迟缓越明显，像橡皮筋被拉过头，弹不回原来的位置。\n\n"
        "胸口那阵闷意又上来了。\n\n"
        "这次她没有去拿口红。"
    )

    result = workbench._finalize_initial_draft_candidate(
        project_slug="demo",
        tone_profile=SimpleNamespace(target_word_count=0),
        project={"source_type": "tracked_article"},
        outline_row={"hook": "", "outline_body": ""},
        review_comment=None,
        reference_article_payload={},
        strategy_bundle_payload={},
        polish_instruction=None,
        generator=object(),
        title=candidate_title,
        body_markdown=candidate_body,
    )

    assert result.reference_title == candidate_title
    assert result.reference_body_markdown == candidate_body
    assert result.cleanup_applied is True
    assert result.cleanup_changed_steps >= 1
    assert result.body_markdown != candidate_body


def test_build_initial_draft_candidate_result_reverts_cleanup_that_over_smooths_tracked_article(
    monkeypatch,
) -> None:
    source_body = "# 原稿\n\n保留一点毛边的正文"
    over_smoothed_body = "# 原稿\n\n过度顺滑正文"

    monkeypatch.setattr(workbench, "_collapse_short_judgment_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_time_chain_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_embedded_banner_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_leading_short_long_cadence_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_short_long_cadence_residue", lambda **kwargs: over_smoothed_body)
    monkeypatch.setattr(workbench, "_collapse_over_segmented_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_light_segmented_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_structural_ladder_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_direct_address_lecture_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_not_ab_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_connector_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(
        workbench,
        "_looks_like_over_smoothed_tracked_article_candidate",
        lambda markdown: markdown == over_smoothed_body,
    )

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        score_map = {
            source_body: 18,
            over_smoothed_body: 0,
        }
        return SimpleNamespace(score=score_map[body_markdown], level="低", hits=[], suggestions=[])

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)

    result = workbench._build_initial_draft_candidate_result(
        title="原稿",
        body_markdown=source_body,
        source_type="tracked_article",
    )

    assert result.reference_body_markdown == source_body
    assert result.body_markdown == source_body
    assert result.cleanup_applied is False
    assert result.cleanup_changed_steps == 0


def test_build_initial_draft_candidate_result_applies_direct_address_lecture_cleanup(
    monkeypatch,
) -> None:
    source_body = "lecture raw"

    monkeypatch.setattr(workbench, "_collapse_short_judgment_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_time_chain_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_embedded_banner_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(
        workbench,
        "_collapse_leading_short_long_cadence_residue",
        lambda **kwargs: kwargs["body_markdown"],
        raising=False,
    )
    monkeypatch.setattr(workbench, "_collapse_short_long_cadence_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_over_segmented_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_collapse_light_segmented_shell_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_structural_ladder_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_direct_address_lecture_residue", lambda **kwargs: "lecture cleaned")
    monkeypatch.setattr(workbench, "_soften_not_ab_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(workbench, "_soften_connector_residue", lambda **kwargs: kwargs["body_markdown"])
    monkeypatch.setattr(
        workbench,
        "_prefer_less_smoothed_tracked_article_variant",
        lambda **kwargs: (kwargs["preferred_markdown"], kwargs["preferred_title"]),
    )

    result = workbench._build_initial_draft_candidate_result(
        title="原稿",
        body_markdown=source_body,
        source_type="tracked_article",
    )

    assert result.reference_body_markdown == source_body
    assert result.body_markdown == "lecture cleaned"
    assert result.cleanup_applied is True
    assert result.cleanup_changed_steps == 1


def test_collapse_explanatory_bridge_residue_merges_short_bridge_into_process_block() -> None:
    markdown = (
        "# 标题\n\n"
        "包底那张单子还在，纸边已经卷了。\n\n"
        "更磨人的是，人会慢慢适应这种状态。\n\n"
        "复查往后放，休息往后放，规律吃药往后放，连“不舒服”本身都往后放。表面上日子还在照常走，工作没停，家里那摊事也没停。"
    )

    collapsed = workbench._collapse_explanatory_bridge_residue(
        title="标题",
        body_markdown=markdown,
    )

    assert "更磨人的是，人会慢慢适应这种状态。\n\n" not in collapsed
    assert "更磨人的是，人会慢慢适应这种状态，复查往后放" in collapsed


def test_soften_not_ab_residue_breaks_symmetric_answer_shell() -> None:
    markdown = "不是轻视身体，是没有空位处理后果。"

    softened = workbench._soften_not_ab_residue(
        title="标题",
        body_markdown=markdown,
    )

    assert "不是轻视身体，是没有空位处理后果" not in softened
    assert "没有空位处理后果" in softened
    assert "真要把它算成轻视身体，反而把事情说浅了" in softened


def test_prefer_less_smoothed_tracked_article_variant_keeps_cleanup_that_clears_lecture_lines(
    monkeypatch,
) -> None:
    fallback_body = "fallback lecture shell"
    preferred_body = "preferred smooth but lecture-free"

    monkeypatch.setattr(
        workbench,
        "_looks_like_over_smoothed_tracked_article_candidate",
        lambda markdown: markdown == preferred_body,
    )

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        if body_markdown == fallback_body:
            return SimpleNamespace(
                score=18,
                level="低",
                hits=["命中：第二人称讲解台词偏显眼 x5"],
                suggestions=[],
            )
        if body_markdown == preferred_body:
            return SimpleNamespace(score=0, level="低", hits=[], suggestions=[])
        raise AssertionError(body_markdown)

    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)

    chosen_markdown, chosen_title = workbench._prefer_less_smoothed_tracked_article_variant(
        preferred_title="preferred",
        preferred_markdown=preferred_body,
        fallback_title="fallback",
        fallback_markdown=fallback_body,
    )

    assert chosen_markdown == preferred_body
    assert chosen_title == "preferred"


def test_final_ai_flavor_cleanup_triggers_for_low_score_residue() -> None:
    candidate_body = (
        "# 别把日子过反了\n\n"
        "我们总以为以后还有机会，可真正卡住人的，不是没时间，是把“重要”长期排在“紧急”后面。\n\n"
        "阿杰后来还是去做了体检。\n\n"
        "外婆走后，我才知道有些时刻不会重来。"
    )

    assert workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="别把日子过反了",
        candidate_markdown=candidate_body,
    )


def test_final_ai_flavor_cleanup_triggers_for_moderate_score_small_residue() -> None:
    candidate_body = (
        "# 别让赌气毁掉关系\n\n"
        "很多时候，手指停在输入框上，一下删掉，一遍重写，一个字一个字往回吞。\n\n"
        "其实你不是不想说，而是那口气一直卡着，所以一句软话也递不出去。\n\n"
        "你等他来问，他等你自己说。然后消息停着，后来沉默也跟着变重。\n\n"
        "说到底，真正先累垮的往往还是彼此的心。"
    )

    assert workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="别让赌气毁掉关系",
        candidate_markdown=candidate_body,
    )


def test_final_ai_flavor_cleanup_triggers_for_four_not_ab_only_residue() -> None:
    candidate_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "不是不懂，而是根本没有能量。不是你故意要把话说坏，而是防御比表达跑得更快。"
        "不是没有感觉，是已经不想再组织语言。不是坏在某个原则上，而是耗在长期亏空里。"
    )

    assert workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="关系卡住的本质：意愿有、懂方法、但无能量",
        candidate_markdown=candidate_body,
    )


def test_final_ai_flavor_cleanup_triggers_for_five_not_ab_only_residue() -> None:
    candidate_body = (
        "# 那张化验单上的箭头，你别再替它找理由了\n\n"
        "体检单上有箭头，脚踝开始肿，早上起床脸发胀，伤口比以前好得慢。身体最开始给的，不是轰动性的警报，是一串很容易被日常吞掉的小信号。\n\n"
        "医生建议复查，先看手机里的日程表。上午请假要跟同事协调，下午老人要去复诊，孩子晚上还要辅导作业。最常见的卡点不是不知道要重视，是知道，但排不进去。\n\n"
        "很多女人一生病，先担心的是别给别人添麻烦。她会把“去确认”改成“再观察观察”，把“该休息”改成“我还能扛”。前面省下来的，不是时间，是眼前那点不愿面对的慌。\n\n"
        "很多恶化，看着突然，过程并不突然。不是某一天毫无征兆地变坏，是前面每次都有提醒，每次都被让给了更紧急的事。\n\n"
        "当然，具体病情要交给医生判断。这里要说的不是制造恐慌，是别替明显的提醒找太多生活化的解释。"
    )

    assert workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="那张化验单上的箭头，你别再替它找理由了",
        candidate_markdown=candidate_body,
    )


def test_final_ai_flavor_cleanup_triggers_for_short_judgment_residue() -> None:
    candidate_body = (
        "# 她后来没再把真心话都留到夜里\n\n"
        "电梯快合上的时候，她低头看了眼手机。\n\n"
        "置顶对话里躺着两条昨晚没回完的消息。朋友问她这周要不要见面，妈妈发来一张家里阳台新开的花。她的手指停在屏幕上方，楼层往下跳，她先回了工作群里的“收到”，又把那两个对话按灭。\n\n"
        "白天的她并没有闲着。\n\n"
        "消息很多，页面一直在跳。确认排期、对接流程、改表格、补一句“辛苦了”、再接住新的安排。她能回的大多是这种话：明确，简短，不需要情绪，也不需要把自己放进去。\n\n"
        "后来她有过个很小的变化。\n\n"
        "午休快结束时，她没有先去刷工作群，而是靠在茶水间窗边，回了朋友那条约见面的消息。没写很多，只是认真定了个周六下午。"
    )

    assert workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="她后来没再把真心话都留到夜里",
        candidate_markdown=candidate_body,
    )


def test_collapse_short_judgment_residue_merges_tail_short_paragraphs() -> None:
    candidate_body = (
        "# 她在电梯镜子里补了口红，却把胸口那阵闷意按了回去\n\n"
        "电梯门快合上的时候，她抬手拦了一下，另一只手还拿着口红。镜子里那张脸被顶灯照得有点白，她抿了抿唇，把颜色补匀，顺手按住胸口那阵发闷。不是很疼，更像有块东西横在那里，气吸不满。手机屏幕亮着，待办列表最上面那行写着：10:00 周会。\n\n"
        "门开了，会议室在走廊尽头。她边走边把口红塞回包里，心里想的是，今天先把会开完再说。\n\n"
        "很多提醒，最早都长得不吓人。\n\n"
        "先是动作变慢。群消息弹出来，她看完，没有立刻回，过了几分钟再点开，又从头看了一遍，还是没想好怎么接。明明字都认识，脑子却像隔着层雾。对面催了一句“在吗”，她才赶紧回过去，手指打字很快，内容却比平时更短，像在补交作业。\n\n"
        "这样的停顿一多，周围人先感到的是不顺。工作对接的人会追问，家里人会说她最近老走神。她自己也察觉到了，于是开始补：白天加一杯冰美式，晚上把没做完的事往后挪，想着再熬两个小时，节奏就能拉回来。胸口闷、回消息慢、说话要想半秒，都被她归到同一类——这阵子太忙了。\n\n"
        "可身体不太认这个说法。\n\n"
        "咖啡把人往上拎，晚上却更难真正睡沉。第二天起床更钝，洗脸时盯着镜子发会儿呆，才想起来护肤做到哪步。越想把效率补回去，白天那层迟缓越明显，像橡皮筋被拉过头，弹不回原来的位置。\n\n"
        "胸口那阵闷意又上来了。\n\n"
        "这次她没有去拿口红。"
    )

    collapsed = workbench._collapse_short_judgment_residue(
        title="她在电梯镜子里补了口红，却把胸口那阵闷意按了回去",
        body_markdown=candidate_body,
    )
    summary = workbench.evaluate_ai_flavor_risk(
        title="她在电梯镜子里补了口红，却把胸口那阵闷意按了回去",
        body_markdown=collapsed,
    )

    assert "胸口那阵闷意又上来了。这次她没有去拿口红。" in collapsed
    assert len(workbench.extract_short_judgment_paragraphs(collapsed)) == 2
    assert not any("单句敲钟段偏多" in hit for hit in summary.hits)


def test_collapse_time_chain_shell_residue_reduces_retry44_like_shell_burden() -> None:
    candidate_body = (
        "电梯快到楼层，她对着镜面补了口红。手机震了下，屏幕顶端跳出一行字：体检改期成功。\n\n"
        "手指往上一划，门开了，外面已经有人在喊投屏连不上。高跟鞋踩在地砖上，声响空空的。那条短信很快被新的通知压下去，和群消息、日程提醒叠在一起。\n\n"
        "楼梯口那次也很直白。同事走了两级，回头看见她扶着栏杆，问今天怎么这么慢。她笑了笑，只接了句，昨晚没睡好。中午群里催文件，光标在对话框里闪了很久，最后发出去的还是“收到”。她不是想省字，当时先冒出来的感觉是钝，像脑子外面糊着层湿布，句子要往外拽，半天也拽不整齐。\n\n"
        "这种时候，人往往不会停，反而会往前补。咖啡换大杯，午休先撤掉，晚上回家再开电脑，把白天掉下去的进度补回来。她也这么做。因为一旦慢下来，麻烦立刻就有了形：请假要重排，答应过的事得往后挪，还要自己开口承认，这会儿确实撑不太住。\n\n"
        "于是“最近有点累”成了最顺手的说法。轻，薄，像拿手掌把桌上的纸压平，底下那层褶还在。\n\n"
        "饭局那回，声音更吵。杯子碰杯子，勺子刮盘子，过道上来回有人走。她坐在靠外侧的位置，菜转到面前，夹了口南瓜，就停那儿了。朋友问项目是不是很麻烦，她点头，没接下去。等旁边的人聊到周末去哪儿，她还低头看着碗里那块凉掉的南瓜。\n\n"
        "回家路上，朋友发来语音。她点开，听完，退出来。过两站，又点开一遍，还是没回。后来屏幕上跳出一句：你最近是不是有点怪。\n\n"
        "她按灭了手机。\n\n"
        "安静落在别人耳朵里，很容易被听成冷淡。可她那会儿更像是空了。回应别人要组织词，接住情绪也要力气，连“我最近不太好”这几个字，都显得重。前面那次没说，后面就更难说；消息拖着拖着，误会也会跟着长出来。人际上的消耗，常常不是争吵出来的，很多时候是回复框亮着，你看着它，身体先往后缩了半步。\n\n"
        "第三次提醒更碎，也更容易被她往后放。洗完澡出来，胸口发紧，像内衣肩带勒久了，摘掉以后那道印子还留着。她坐到床边，头发没吹干，先把第二天的待办往下拉，又把闹钟从7点10分改到6点40分。周末本来约了散步，临出门前又把电脑掀开，说先改完这版。收件箱里那条复诊改期短信一直躺着，没删，也没点。\n\n"
        "给自己的解释倒是很顺：项目特殊，交付完再说，忙过这阵应该就好了。可人一旦急着把自己拨回“正常”，最先被压下去的，偏偏就是这些已经冒头的信号。楼梯走慢了，她往睡眠上归；不想回话，她往情绪上轻轻带过去；胸口发紧，就先改闹钟，先开电脑。每次都像只推迟了一小会儿，后面却要用更多力气去装作没有那回事。\n\n"
        "所以代价看起来并不响。工作群还在回，饭局也照常去，第二天甚至起得更早。表面没断，里面已经开始掉速。最磨人的地方就在这儿：她不是突然垮掉的，是在一次次“先把眼前做完”里，慢慢变钝，慢慢变沉，连察觉自己不对劲都比从前晚了半拍。\n\n"
        "夜里十一点多，洗完澡的发尾还在滴水，睡衣领口湿了一小片。手机又亮了，还是那个朋友：你最近还好吗？\n\n"
        "她把输入框点开，打了两个字，又删掉。屏幕白着，下面压着那条复诊改期的确认短信。"
    )

    before_burden = workbench._article_shell_burden(candidate_body)
    before_summary = workbench.evaluate_ai_flavor_risk(
        title="收件箱里那条改期短信，她一直没点开",
        body_markdown=candidate_body,
    )

    collapsed = workbench._collapse_time_chain_shell_residue(
        title="收件箱里那条改期短信，她一直没点开",
        body_markdown=candidate_body,
    )

    after_burden = workbench._article_shell_burden(collapsed)
    after_summary = workbench.evaluate_ai_flavor_risk(
        title="收件箱里那条改期短信，她一直没点开",
        body_markdown=collapsed,
    )

    assert collapsed != candidate_body
    assert after_burden[0] < before_burden[0]
    assert after_burden[1] < before_burden[1]
    assert after_burden[6] < before_burden[6]
    assert after_summary.score < before_summary.score
    assert "\n\n她按灭了手机。\n\n" not in collapsed
    assert "你最近是不是有点怪。她按灭了手机。" in collapsed
    assert "夜里十一点多" in collapsed


def test_collapse_embedded_banner_shell_residue_reduces_anchor_step_shell() -> None:
    candidate_body = (
        "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣。\n\n"
        "杯壁外侧已经结了一层薄薄的水，电脑右下角跳到 21:47，文档还开着，光标一闪一闪。那条消息很短：最近怎么样，要不要找天见一面？\n\n"
        "人很多时候就是从这里开始慢下来的。没出什么大事，也谈不上垮。只是闹钟响了，按掉，再按掉；明明只差十分钟就能从容出门，还是在床边坐了很久。\n\n"
        "麻烦就麻烦在，这些信号太容易被她自己轻轻带过去。醒来更累，胃口乱，下午三四点会突然心慌；消息提示音一密集，太阳穴就跟着发紧。可熟悉的话也会立刻跟上来：忙完这阵就好了，周末补个觉就好了。\n\n"
        "身体先亮红灯，人却还照着原来的效率和礼貌往前走。该交的照交，该回的照回，见了人也还能笑，说自己没事。\n\n"
        "她还没倒下。还能上班，能交差，能在别人问起时回一句“挺好的”。偏偏就是这种“还能”，最容易让人误判。\n\n"
        "关系里的缺席，也是在这些时候一点点长出来的。见面改成改天，电话换成文字，长回复缩成表情，解释缩成“最近有点忙”。\n\n"
        "这句话很体谅，可听久了，人会更沉。因为她慢慢也默认了自己总在往后退。生活里有变化，不太主动讲了；受了委屈，也觉得讲起来太费劲。\n\n"
        "难的地方就在这儿。不是因为太久没见，也不全是因为之前推掉太多次。更常见的情况是，人已经在长时间硬撑里，跟自己的感受脱了节。\n\n"
        "回家的路上，手机又亮了一次。她站在电梯里，看着镜子里自己有点发白的脸，拇指在屏幕上停了停，没有再逼自己把所有消息都回完。"
    )

    before_banners = workbench.extract_embedded_banner_paragraphs(candidate_body)
    before_burden = workbench._article_shell_burden(candidate_body)
    before_summary = workbench.evaluate_ai_flavor_risk(
        title="朋友的消息弹出来时，她正对着桌上那杯咖啡发愣",
        body_markdown=candidate_body,
    )

    collapsed = workbench._collapse_embedded_banner_shell_residue(
        title="朋友的消息弹出来时，她正对着桌上那杯咖啡发愣",
        body_markdown=candidate_body,
    )

    after_banners = workbench.extract_embedded_banner_paragraphs(collapsed)
    after_burden = workbench._article_shell_burden(collapsed)
    after_summary = workbench.evaluate_ai_flavor_risk(
        title="朋友的消息弹出来时，她正对着桌上那杯咖啡发愣",
        body_markdown=collapsed,
    )

    assert len(before_banners) >= 4
    assert collapsed != candidate_body
    assert len(after_banners) == 0
    assert after_burden[0] < before_burden[0]
    assert after_summary.score < before_summary.score
    assert "人很多时候就是从这里开始慢下来的，没出什么大事，也谈不上垮。" in collapsed
    assert "她还没倒下。" in collapsed
    assert "能上班，能交差，能在别人问起时回一句“挺好的”" in collapsed


def test_collapse_short_long_cadence_residue_merges_middle_anchor_step_pairs() -> None:
    candidate_body = (
        "包带还挂在肩上，勒得锁骨发酸。她站在洗手台前，把牙膏挤到牙刷上，白色膏体歪歪地停在刷毛边缘，快要掉下来。镜子里那张脸有点灰，额前碎发贴着，耳边像还残留着消息提示音。\n\n"
        "她没动。\n\n"
        "水龙头没有开，手也没抬起来。就那么站了十几秒，脑子里先冒出来的是：明天不能再这样了。接着，空了。后面该想什么，怎么改，先处理哪件事，她都接不上。像走到楼梯口，突然忘了自己是上楼还是下楼。\n\n"
        "很多人的累，不是那种轰一下压下来的累。更像这类时刻：睡前流程还在继续，身体会自动去做那些熟悉的动作，人却没有真正收回来。肩膀沉，后槽牙咬得发紧，眼睛盯着镜子，又像什么都没看见。情绪也不算大，甚至没有力气委屈。连崩溃都得往后排。\n\n"
        "真往前倒，不是从凌晨开始的。\n\n"
        "白天就已经有痕迹了。回同事消息时，她把打好的那行字删掉重来，来回看两遍，还是觉得哪里不对。会议里有人问到她，她明明听见了，反应却慢半拍，先是心里空白，接着才仓促补上几句。午饭摆在工位边上，饭吃了大半，才发现自己没尝出味道，嘴里只有温热和咀嚼。\n\n"
        "还有些更小的地方，零碎得不值得专门拿出来说。电梯到了她常去的楼层，她晚了半秒才迈腿；下楼取外卖，站在门口想了会儿，忘记自己拿没拿钥匙；朋友发来语音，她点开听完，没有不高兴，也没有想回，手机屏幕暗下去，她就让它那么躺着。\n\n"
        "她坐了会儿，把第二天最早的提醒关掉了。\n\n"
        "屋里安静下来以后，很多事并不会马上变轻，工作还在，消息明天还会继续来，人际里的牵扯也不会自己消失。但至少那一晚，她不用再一边难受，一边把这件事说得很小。她先承认了：自己确实已经撑了太久。"
    )

    before_summary = workbench.evaluate_ai_flavor_risk(
        title="她把第二天最早的提醒关掉了",
        body_markdown=candidate_body,
    )

    collapsed = workbench._collapse_short_long_cadence_residue(
        title="她把第二天最早的提醒关掉了",
        body_markdown=candidate_body,
    )

    after_summary = workbench.evaluate_ai_flavor_risk(
        title="她把第二天最早的提醒关掉了",
        body_markdown=collapsed,
    )

    assert collapsed != candidate_body
    assert "连崩溃都得往后排。真往前倒，不是从凌晨开始的。" in collapsed
    assert "她就让它那么躺着。她坐了会儿，把第二天最早的提醒关掉了。" in collapsed
    assert workbench.count_short_long_cadence_pairs(collapsed) < workbench.count_short_long_cadence_pairs(candidate_body)
    assert after_summary.score < before_summary.score
    assert not any("短句敲钟后接长解释的固定节拍" in hit for hit in after_summary.hits)


def test_collapse_leading_short_long_cadence_residue_reflows_retry42_like_opening_pair() -> None:
    candidate_body = (
        "电梯门快要合上的时候，她伸手挡了一下。\n\n"
        "金属门沿碰到手背，凉了一瞬。人是进来了，心口却突然空了一拍，像踩空楼梯那种短促的失重。她站稳，先低头看手机，聊天框顶着一句：文件到了吗。拇指飞快敲了两个字：马上。\n\n"
        "电梯往上走，镜面里的人脸色有点白。她盯着数字跳，没把那口气补完整。刚才那下心慌，按理说该停一停，至少靠着轿厢站会儿，等胸口缓过来。可屏幕亮着，红点还在，她下意识先把身体往后排。\n\n"
        "这时候最容易发生的误认，是把报警当偷懒。\n\n"
        "明明已经开始耗了，她还会拿“别人也这么忙”压自己，拿“就这几天”拖自己，拿“先把这件做完”借自己。每回只借走一小截体力，借走一点耐心，借走一次好好吃饭和好好说话的机会。表面看都不算大事，拼在一起，人才会慢慢变成现在这样：反应迟，睡不好，不想回消息，不想解释，坐着都像在咬牙。"
    )

    before_summary = workbench.evaluate_ai_flavor_risk(
        title="她在电梯口扶住门的那一秒，身体已经先开口了",
        body_markdown=candidate_body,
    )

    collapsed = workbench._collapse_leading_short_long_cadence_residue(
        title="她在电梯口扶住门的那一秒，身体已经先开口了",
        body_markdown=candidate_body,
    )

    after_summary = workbench.evaluate_ai_flavor_risk(
        title="她在电梯口扶住门的那一秒，身体已经先开口了",
        body_markdown=collapsed,
    )

    assert collapsed != candidate_body
    assert "电梯门快要合上的时候，她伸手挡了一下。金属门沿碰到手背，凉了一瞬。" in collapsed
    assert "\n\n人是进来了，心口却突然空了一拍" in collapsed
    assert workbench.count_short_long_cadence_pairs(collapsed) < workbench.count_short_long_cadence_pairs(candidate_body)
    assert after_summary.score < before_summary.score
    assert not any("短句敲钟后接长解释的固定节拍" in hit for hit in after_summary.hits)


def test_collapse_over_segmented_shell_residue_merges_hinge_blocks_in_retry8_shape() -> None:
    candidate_body = (
        "包带还挂在肩上，勒得锁骨发酸。她站在洗手台前，把牙膏挤到牙刷上，白色膏体歪歪地停在刷毛边缘，快要掉下来。镜子里那张脸有点灰，额前碎发贴着，耳边像还残留着消息提示音。\n\n"
        "她没动。\n\n"
        "水龙头没有开，手也没抬起来。就那么站了十几秒，脑子里先冒出来的是：明天不能再这样了。接着，空了。后面该想什么，怎么改，先处理哪件事，她都接不上。像走到楼梯口，突然忘了自己是上楼还是下楼。\n\n"
        "很多人的累，不是那种轰一下压下来的累。更像这类时刻：睡前流程还在继续，身体会自动去做那些熟悉的动作，人却没有真正收回来。肩膀沉，后槽牙咬得发紧，眼睛盯着镜子，又像什么都没看见。情绪也不算大，甚至没有力气委屈。连崩溃都得往后排。真往前倒，不是从凌晨开始的。\n\n"
        "白天就已经有痕迹了。回同事消息时，她把打好的那行字删掉重来，来回看两遍，还是觉得哪里不对。会议里有人问到她，她明明听见了，反应却慢半拍，先是心里空白，接着才仓促补上几句。午饭摆在工位边上，饭吃了大半，才发现自己没尝出味道，嘴里只有温热和咀嚼。\n\n"
        "还有些更小的地方，零碎得不值得专门拿出来说。电梯到了她常去的楼层，她晚了半秒才迈腿；下楼取外卖，站在门口想了会儿，忘记自己拿没拿钥匙；朋友发来语音，她点开听完，没有不高兴，也没有想回，手机屏幕暗下去，她就让它那么躺着。\n\n"
        "那天开会前，同事问她要不要喝咖啡，她说，都行。中午订餐，别人问你吃什么，她还是那句，都行。晚上家里人发来消息，说周末怎么安排，她盯着对话框看了会儿，回：先这样吧。\n\n"
        "“我想吃什么”“我想休息”“我现在不太行”，这些话没有突然消失。只是慢慢地，很少再从嘴里出来了。\n\n"
        "她也没请假，没哭，没跟谁吵起来。工作照常交，消息照常回，见到人也会笑。表面看不出什么大问题，她自己也更容易把这些小卡顿压成一句：最近状态不好。\n\n"
        "这句解释太顺手了，没睡好，过两天就好了；这阵子忙完，应该能缓过来；周末多睡会儿，别多想。她拿这些话安顿自己，也拿它们把那些更细的感觉挡回去。毕竟待办还在往上跳，群里有人艾特，家里还有人等回复，连下班路上都塞着“顺手处理一下”的事。一个人被推着往前走时，能留给自己分辨的空间其实很窄。\n\n"
        "有时她也会察觉到不对。原来十分钟能做完的表格，现在坐了半小时还没进入状态；以前能接住的话题，现在听别人说话都觉得费劲；有人关心她一句“你最近还好吗”，她喉咙发紧，差点就想说实话了，到头来还是习惯性回：挺好的。\n\n"
        "先别问为什么。很多时候，那句“挺好的”几乎是弹出来的。\n\n"
        "因为停下来很麻烦。工作会乱，别人会等，答应过的事要重新解释。更麻烦的是，她得承认自己已经不像平时那样了。那个原本利落、能扛、反应快的人，现在做什么都发沉，说两句话都嫌累。这件事不好受。甚至有点刺人。\n\n"
        "她更容易用力把自己往“正常”里推。困了就灌咖啡，迟钝了就逼自己集中，想安静会儿又怕显得消极。明明已经拧巴得厉害，脸上还得维持平常的表情。该回的话照回，该笑的时候照笑，该出现的场合照出现。\n\n"
        "真正耗人的，常常不是事情本身有多大，而是人已经听见身体里的报警声，还要假装办公室里什么都没响。\n\n"
        "这种消耗有点阴，它不壮烈，也不戏剧化，不会给你一个明确的瞬间，告诉你“好，你现在撑不住了”。它更像电量被很多后台程序慢慢拖走。你照旧开着页面，照旧切任务，照旧回复别人，直到夜里站在洗手台前，才发现自己连“我现在到底怎么了”都组织不出来。\n\n"
        "这也是为什么，越着急恢复成原来那个样子，越容易看不见自己已经透支。她想赶快追平进度，赶快找回效率，赶快证明自己没事，于是那些变慢、变钝、不想说话的信号，就又被归到“短期失控”里。忍忍，顶顶，睡一觉再说。\n\n"
        "可身体有时不按这套来。你越催，它越迟。\n\n"
        "能让人往回退半步的，通常也不是什么大动作，可能只是第二天通勤路上，她没有一上车就点开工作群，而是把手机切到备忘录，记下最近最明显的三个变化：回消息变慢；越来越怕说话；做什么都像拖着一截湿衣服。写完那三行，事情不会立刻变少，人也不会立刻轻松，但模糊的自责会松开一条缝。\n\n"
        "原来不是自己突然变懒了，真正卡住的地方在，她已经耗到需要分辨：哪些是必须做的，哪些可以晚点回；哪些是责任，哪些只是习惯性逞强。\n\n"
        "后面的事，也许只是先减掉一项没那么要紧的安排，先让某条无关紧要的消息晚回半天，先别逼自己今天就恢复利落。不是每次都要搞出完整方案。有时候，能把“我得赶紧正常起来”改成“我今天少撑一会儿”，已经很难了，也很有用。\n\n"
        "夜里那面镜子还在，灯光照下来，脸色还是疲惫的。她没有突然想通，也没有瞬间好起来。牙刷还在手里，包终于从肩上滑下来，落到门边的凳子上，发出一声很轻的闷响。她坐了会儿，把第二天最早的提醒关掉了。\n\n"
        "屋里安静下来以后，很多事并不会马上变轻，工作还在，消息明天还会继续来，人际里的牵扯也不会自己消失。但至少那一晚，她不用再一边难受，一边把这件事说得很小。她先承认了：自己确实已经撑了太久。"
    )

    before_burden = workbench._article_shell_burden(candidate_body)
    before_summary = workbench.evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=candidate_body,
    )

    collapsed = workbench._collapse_over_segmented_shell_residue(
        title="别把日子过反了",
        body_markdown=candidate_body,
    )

    after_burden = workbench._article_shell_burden(collapsed)
    after_summary = workbench.evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=collapsed,
    )

    assert collapsed != candidate_body
    assert after_burden[0] < before_burden[0]
    assert after_burden[1] <= 15
    assert after_summary.score < before_summary.score
    assert "\n\n她没动。\n\n" not in collapsed
    assert "先别问为什么。很多时候，那句“挺好的”几乎是弹出来的。" in collapsed
    assert "原来不是自己突然变懒了，真正卡住的地方在，她已经耗到需要分辨" in collapsed
    assert "后面的事，也许只是先减掉一项没那么要紧的安排" in collapsed
    assert not any("段落职责切分过细" in hit for hit in after_summary.hits)


def test_collapse_light_segmented_shell_residue_merges_residual_anchor_and_tail_blocks() -> None:
    candidate_body = (
        "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣。\n\n"
        "杯壁外侧已经结了一层薄薄的水，电脑右下角跳到 21:47，文档还开着，光标一闪一闪。那条消息很短：最近怎么样，要不要找天见一面？\n\n"
        "她点开语音，说了两个字，停住。删掉。又按住，说到“我最近……”就没声了。肩膀绷得很紧，像有人把两边往里拽。最后发出去的，还是那句最省力的话：这周有点满，下次一定。\n\n"
        "消息发完，手机被她扣在桌上。屋里很安静，只有冰箱压缩机时不时响一声。她坐着没动，连起身去洗那个杯子都像要先攒一会儿力气。很多人就是从这种地方开始变慢的。\n\n"
        "不是什么大事，也没有戏剧性的崩塌。闹钟响了，按掉，再按掉。明明只差十分钟就能从容出门，还是在床边坐了很久。洗头这件事，要在心里过两遍流程。工作群里的消息回得很快，私人聊天框一排红点，看见了，也知道该回，手指却悬在那儿，不太想点开。\n\n"
        "白天她照常开会、改东西、回邮件。谁来催，她都能接住，语气也稳。到了下班路上，地铁门一开，风吹进来，她忽然只想把耳机音量调大一点，谁都别找她。回家以后，包放在门口，外套搭上椅背，人靠着沙发坐下去，盯着墙，或者盯着短视频往下滑。不是在看什么，就是不想动。\n\n"
        "这里面有条很清楚的线。\n\n"
        "待办一项项堆上来，她最先做的，通常与其说是分辨自己累到哪了，不如说是把那点不舒服往里折，先做完再说。眼前这关要过，明天那项不能拖，周会材料还差最后两页。情绪先收起来，困和烦也先收起来。这样撑过去几次，表面看着没出事，代价却会留在别处：越晚处理自己，恢复的门槛越高，到后来，连见朋友、回电话、认真聊近况这种原本能让人松口气的事，也开始带着任务感。\n\n"
        "她不是突然不爱说话的。早上出门前，口红拿起来又放下，算了。午休时间，本来想去楼下走走，结果坐在工位上发呆。深夜洗漱，牙刷含在嘴里，眼睛看着镜子里的人，脑子却是空的。第二天继续。你会发现她还在运转，但速度不一样了，钝感也出来了，像手机进入了省电模式，屏幕亮着，后台却关掉了很多东西。\n\n"
        "更麻烦的是，她常把这些信号当成“最近状态不太好”。\n\n"
        "醒来更累，胃口乱，有时下午三四点突然心慌；消息提示音一密集，太阳穴就跟着发紧。按理说，这些已经够明显了。可她对自己的解释总是很熟：忙完这阵就好了，周末补个觉就好了，最近事情多，谁不是这样。\n\n"
        "她不是没感觉到，只是太习惯“撑一下”。\n\n"
        "身体先给信号，她的反应却往往还是维持原来的效率和礼貌。该交的照交，该回的照回，见了人也还能笑，说自己没事。这样做短期确实管用，能让日子继续往前推；可后续的空，会越来越实。最先被取消的，常常不是工作，不是合作，也与其说是那些明确有后果的安排，不如说是朋友约饭、回家人的电话、好好讲一遍自己这阵子到底怎么了。\n\n"
        "因为她还没有倒下。还能上班，能交差，能在别人问起时回一句“挺好的”。正是这种“还能”，最容易让人误判。像房间里有一盏灯开始忽明忽暗，但只要没彻底灭掉，大家就继续用。她自己也继续用，直到连换个灯泡都嫌麻烦。\n\n"
        "关系里的缺席，也不是某天忽然形成的。先是把见面改成改天，接着电话变成文字，最后长回复缩成表情，解释缩成“最近有点忙”。聊天框里的未读红点越来越多，她收藏过几条想认真回的话，后来也没再点开。朋友起初还会追问两句，发生了什么，忙成这样？再往后，大家学会了顺着她：行，等你忙完。\n\n"
        "这句话听上去很体谅，可听多了，人会更沉默。因为她慢慢适应了自己总在往后退。生活里有新变化，不太主动讲了；受了委屈，也觉得讲起来太费劲。别人伸手的时候，她先想到的与其说是“我可以说”，不如说是“我得赶紧恢复正常，再去见人”。真正卡住的地方就在这儿：她越想尽快回到从前那个利落、能聊、能接住一切的自己，就越容易忽略现在这个已经很累的人。\n\n"
        "有些代价是延迟出现的。\n\n"
        "过了很久，终于约出来吃饭。餐厅里灯偏黄，汤上来时还冒着热气，对面的人问她，最近还好吗。她先笑了一下，下意识说“还行”。筷子碰到碗沿，轻轻响了一声。后半句卡住了。与其说是故意藏着不说，不如说是她真的一时不知道从哪里讲起。\n\n"
        "那种难，不只在于太久没见，不只在于之前推掉了太多次。更常见的情况是，人已经在长期硬撑里跟自己的感受脱了节。她知道自己累，知道自己变了，可要把这段日子重新接起来，像把散在地上的线头重新找出来，光找开头就要坐很久。\n\n"
        "所以后来很多女人补的，根本不只是几顿饭、几次见面、几条没回的消息。她在补的是一段长时间的缺席：没在最难的时候承认自己难，没在身体已经开始报警时停下来，也没在关系还松动得开的时刻，把真实情况递出去。\n\n"
        "回家的路上，手机又亮了一次。她站在电梯里，看着镜子里自己有点发白的脸，拇指在屏幕上停了停，没有再逼自己把所有消息都回完。\n\n"
        "她只给其中一个人发了句实话：我最近有点撑不动，可能会回得慢一点。\n\n"
        "发完以后，电梯门开了。她把手机放回口袋，先去把那只杯子洗了。"
    )

    before_burden = workbench._article_shell_burden(candidate_body)
    before_summary = workbench.evaluate_ai_flavor_risk(
        title="朋友的消息弹出来时，她正对着桌上那杯咖啡发愣",
        body_markdown=candidate_body,
    )

    collapsed = workbench._collapse_light_segmented_shell_residue(
        title="朋友的消息弹出来时，她正对着桌上那杯咖啡发愣",
        body_markdown=candidate_body,
    )

    after_burden = workbench._article_shell_burden(collapsed)
    after_summary = workbench.evaluate_ai_flavor_risk(
        title="朋友的消息弹出来时，她正对着桌上那杯咖啡发愣",
        body_markdown=collapsed,
    )

    assert collapsed != candidate_body
    assert after_burden[0] < before_burden[0]
    assert after_burden[1] < before_burden[1]
    assert after_summary.score <= before_summary.score
    assert after_burden[1] <= before_burden[1] - 2


def test_collapse_light_segmented_shell_residue_merges_adjacent_scene_shell_blocks() -> None:
    candidate_body = (
        "凌晨一点多，手机屏幕还亮着。最后一个工作群安静下来，家族群那条六十秒语音也听完了，朋友发来的“你睡了吗”被她回成“刚忙完”。她把输入框切到置顶的那个聊天框，停了几秒，打下：我最近有点撑不住。\n\n"
        "光标在句尾一闪一闪，像在催。手指悬在发送键上，肩膀先松了，整个人往床边陷。洗手台上还摆着没收的护肤品，头发扎了一整天，发根发紧。她原本想趁终于没人找的时候洗个头，或者把垃圾带下楼，结果只是背靠着衣柜门坐着，半天没动。\n\n"
        "外面的声响退下去以后，身体里的钝重才慢慢浮上来。白天像被推着往前走，回消息、接话、安抚、解释，做得太熟了，熟到很难立刻察觉自己已经空了。等轮到自己，话却卡在喉咙口，连发出去都嫌费劲。这种耗尽，未必会闹出很大的动静。更多时候，它只是把人往慢里拽。\n\n"
        "早上站在衣柜前，常穿的几套衣服都认得，还是会多站一会儿。电梯门合上，镜面里照出脸，她把视线移开，去盯跳动的楼层数字。到了公司，同事问要不要带咖啡，她照旧说好，声音听不出什么问题。\n\n"
        "午休时困得眼睛发涩，趴下也睡不着，手机拿起来就往下滑。视频一条条过去，内容没留下什么，手指倒一直在动。别人叫她名字，她还是会立刻应；轮到私人消息，常常只回“收到”“好”“晚点说”。\n\n"
        "原本顺手的事也开始停在半路。洗完澡，护发素搁在洗手台边，隔天才想起。外卖吃到一半凉在桌上。备忘录里记着体检、朋友那条拖了很久的长消息、要给自己换双舒服点的鞋，字都在，事情悬着，像总差最后那口气。\n\n"
        "她也会替自己找理由。最近太忙。睡够就能缓过来。等这阵子过去再说。表面上看，这些话并不离谱：工作没耽误，开会能接话，见人有礼貌，饭也按顿在吃。正因为日子还在照常往前，她更容易把那些发紧、发空、提不起劲，压成“先放放”。\n\n"
        "身体给提醒的时候，通常很轻。先是速度慢下来，接着话变短，耐心变薄，原来愿意伸出去的那部分热情也缩回去。她以为自己只是累，只是懒得动，直到连喜欢的人发来消息，她都要先把手机扣在桌上，缓几分钟，才有力气点开。\n\n"
        "她很会处理别人的情绪。工作上有误会，她习惯把话理顺，尽量别让场面僵住；朋友夜里发来长长的倾诉，她会认真看完，再慢慢回；家里有琐事，也总有人先来问她。哪怕只是回个表情，别人也知道，她在，她看见了。\n\n"
        "时间久了，周围的人会把这种在场当成默认设置。临时改方案先找她，家里有事先问她，朋友情绪下来了也先敲她。她未必没边界，只是先响应外面，已经成了反应。手机一震，她先低头；别人语气有点不对，她先想是不是自己哪里没顾到。\n\n"
        "于是白天她总在往外送：注意力送出去，耐心送出去，话送出去。到了夜里，屋子安静了，那些被她暂时压住的疲惫才回来。不是突然袭来的崩塌，更像水退下去，露出一直在那里的沙地。她对别人其实很敏感。谁情绪不对，谁说话变快了，谁沉默得反常，她常常看得出来。\n\n"
        "听见了，也不等于马上停下。第二天还是照常起床，照常打卡，照常把语气放软，照常说“没事”。她熟悉的是继续运转，不太熟悉承认自己已经掉电。那个念头总被往后挪：等忙完，等周末，等别人先稳定下来。挪到最后，留给自己的，只剩这点夜深人静的空。\n\n"
        "可人在这个时段往往已经见底了。脑子钝，心口也闷，连难过都没什么声响。聊天框开着，想说的话在里面转了几圈，还是删掉。她不是想隐瞒，只是那时候连解释自己怎么了，都显得太耗神。\n\n"
        "有些累，就长在这些看上去还算体面的日常里。你照样把事情做完，照样回复消息，照样跟人说笑，甚至照样关心别人。只是回到自己这里，像一扇门慢慢合上了。外面的人未必看得见，她自己也常常要过很久才反应过来。\n\n"
        "后来有个夜里，她没再逼着自己把空白填满。聊天框关掉，屏幕暗下去。她去厨房倒了半杯温水，站着喝完，没有顺手去看新的红点。回到床边，还是没立刻想通什么，屋里也没突然变得轻松。\n\n"
        "她只是把第二天答应下来的安排往后挪了挪，又给常联系的人发了句：这两天我回得会慢些。做完这些，生活并没有马上整齐起来。房间还是那间房，洗手台上的瓶瓶罐罐还在，明早该响的闹钟也不会放过她。只是那天晚上，她没有再把自己塞回“正常”里。头发解开后落下来，勒了一整天的发根终于松开，她也跟着安静了些。"
    )

    before_burden = workbench._article_shell_burden(candidate_body)
    before_summary = workbench.evaluate_ai_flavor_risk(
        title="凌晨一点多，手机屏幕还亮着",
        body_markdown=candidate_body,
    )

    collapsed = workbench._collapse_light_segmented_shell_residue(
        title="凌晨一点多，手机屏幕还亮着",
        body_markdown=candidate_body,
    )

    after_burden = workbench._article_shell_burden(collapsed)
    after_summary = workbench.evaluate_ai_flavor_risk(
        title="凌晨一点多，手机屏幕还亮着",
        body_markdown=collapsed,
    )

    assert collapsed != candidate_body
    assert "我最近有点撑不住。光标在句尾一闪一闪，像在催。" in collapsed
    assert after_burden[0] < before_burden[0]
    assert after_burden[1] <= before_burden[1] - 2
    assert after_burden[5] < before_burden[5]
    assert after_summary.score <= before_summary.score


def test_collapse_light_segmented_shell_residue_merges_dense_explainer_shell_blocks() -> None:
    candidate_body = (
        "# 等到话越来越少，很多亏欠已经落在自己身上了\n\n"
        "消息看见了，不想回；别人多问两句，胸口就发闷；明明没出什么大事，人却像被抽掉了反应。你已经很久没把自己放进日程里，身体和情绪先替你停了下来。很多人以为，生活失序会先出现在大地方，工作垮掉了，关系闹僵了，体检单亮红灯了。真到那一步，往往已经拖了很久。更早出现的，是话变短，记性变差，耐心越来越薄，坐着也像在赶路。你还在照常开会、回家、处理孩子的事、接住家里的安排，外面看不出太大问题，里面已经开始发钝。\n\n"
        "这份发钝最容易被误解。旁人会说你只是最近太累，休息两天就好；你自己也会拿“先把今天过完”压过去。可很多亏空，根本不是两天形成的。饭总在后面吃，觉总往后挪，不舒服先忍，体检改下个月，情绪等忙完再整理。每次都只是往后推一点，推到最后，被挪走的就是你自己。\n\n"
        "先出问题的，常常是睡眠和吃饭。它们最容易牺牲，也最容易被轻视。少睡一晚，第二天确实还能出门；午饭凑合过去，下午也还能撑着做事。可身体不会按你的待办表运行。睡眠一碎，注意力先散；吃饭长期凑合，反应就会慢，火气却更快。别人第二句话说完了，你前面那句还没接稳；流程临时改动，整天节奏都乱；孩子多问两遍，语气先硬起来。与其说是你突然不会好好说话，不如说是你已经没多少余量了。\n\n"
        "手机界面还亮着，消息一排排挂在那里。先点掉，又退出来。\n\n"
        "这种状态磨人的地方，不在于事情有多大，在于它会慢慢改写关系。最亲近的人，最先接住的未必是你的辛苦，往往是你的走神、敷衍、不耐烦。你也会难受，会怪自己，觉得连好好回应都做不到。可愧疚一上来，人常常更想赶紧把眼前应付完，更舍不得停。前面没补上的觉，没吃完整的那顿饭，没说出口的委屈，最后都会绕回来，落到关系里。\n\n"
        "还有个信号，很多女人太熟了，熟到不把它当回事：不想说话。与其说是没感受，不如说是连把感受翻出来都嫌费力。解释很累，沟通很慢，别人问“怎么了”，你回“没事”；让你选，你说“都行”；轮到你开口，反而退后。外人容易把这看成懂事、稳定、不添麻烦。可安静也分很多种。有一种安静，是人已经快没电了，连表达自己都嫌重。\n\n"
        "很多人总在失去后才承认，原来早就不对了。病倒一场，才肯承认身体不是机器；关系冷下去，才看见自己很久没认真听人说话；崩一次，才把那些旧信号对上号：懒得回消息，话越来越短，记性变差，对原本喜欢的事提不起劲。这些都不是突然发生的，它们早就在提醒，只是提醒不够响，不像工作催办那样立刻找上门。\n\n"
        "真正卡住人的，是紧急和重要的顺序被拧反了。工作上的临时需求、家里的突发状况、孩子的作业、父母的安排，都有当场反馈，你处理了，事情就往前走；你停下来，麻烦马上堆着看你。照顾自己没有这种即时催促。少睡一晚，表面没塌；情绪不整理，会也照开，饭也能继续做。久了，人会越来越擅长维持外面的秩序，越来越迟钝于里面的失衡。家里看着没乱，工作也还推得动，只有你自己一点点散掉。\n\n"
        "更难的是，很多人会把这叫成“我还行”“我再撑撑”。这几个字很硬，也很危险。撑住不等于没代价。你做事开始反复确认，效率却没高多少；别人一句普通的话，你听着都刺；忙了整天，晚上躺下却没完成感。连身体给出的信号也被压成背景音：累了不敢停，烦了不敢说，不舒服先忍，想休息先内疚。拖久了，人会连自己的需要都认不准。谁着急，哪件事不能出错，哪个时间点必须出现，你都知道；你缺觉，缺安静，缺半小时不被打断，反而总排到最后。\n\n"
        "到这里，最该补的不是更强的执行力，也不是再学几条时间管理。先把一件事认下来：照顾自己，不该是忙完以后才轮到的奖励，它本来就是日常秩序的一部分。睡觉要往前放，吃饭要往前放，身体已经发出的信号要往前放。那句“我现在没力气，晚点再说”，也该被允许出现。\n\n"
        "变慢、变钝、变得不想说话的时候，就别再拿“还能撑”安慰自己了。把无效熬夜停掉，把那顿饭完整吃完，把原本准备硬接的请求往后放。日子能不能重新稳住，往往就从这里开始。不是先把所有人都安顿好，才轮得到你，是你先别继续亏欠自己。"
    )

    before_burden = workbench._article_shell_burden(candidate_body)
    before_summary = workbench.evaluate_ai_flavor_risk(
        title="等到话越来越少，很多亏欠已经落在自己身上了",
        body_markdown=candidate_body,
    )

    collapsed = workbench._collapse_light_segmented_shell_residue(
        title="等到话越来越少，很多亏欠已经落在自己身上了",
        body_markdown=candidate_body,
    )

    after_burden = workbench._article_shell_burden(collapsed)
    after_summary = workbench.evaluate_ai_flavor_risk(
        title="等到话越来越少，很多亏欠已经落在自己身上了",
        body_markdown=collapsed,
    )

    assert collapsed != candidate_body
    assert after_burden[1] <= before_burden[1] - 1
    assert after_burden[0] < before_burden[0]
    assert after_summary.score <= before_summary.score
    assert "这份发钝最容易被误解。旁人会说你只是最近太累" in collapsed
    assert "手机界面还亮着，消息一排排挂在那里。先点掉，又退出来。这种状态磨人的地方" in collapsed


def test_soften_structural_ladder_residue_breaks_orderly_ladder_shell() -> None:
    candidate_body = (
        "关系里的缺席，也不是某天忽然形成的。先是把见面改成改天。后来电话变成文字。再后来，长回复缩成表情，解释缩成“最近有点忙”。聊天框里的未读红点越来越多，她收藏过几条想认真回的话，后来也没再点开。"
    )

    before_summary = workbench.evaluate_ai_flavor_risk(
        title="关系里的缺席，也不是某天忽然形成的",
        body_markdown=candidate_body,
    )

    softened = workbench._soften_structural_ladder_residue(
        title="关系里的缺席，也不是某天忽然形成的",
        body_markdown=candidate_body,
    )

    after_summary = workbench.evaluate_ai_flavor_risk(
        title="关系里的缺席，也不是某天忽然形成的",
        body_markdown=softened,
    )

    assert softened != candidate_body
    assert "先是把见面改成改天，接着电话变成文字，最后长回复缩成表情，解释缩成“最近有点忙”。" in softened
    assert after_summary.score < before_summary.score
    assert not any("先是后来再后来的整齐梳理" in hit for hit in after_summary.hits)


def test_soften_not_ab_residue_rewrites_balanced_reversal_shell() -> None:
    candidate_body = (
        "筷子碰到碗沿，轻轻响了一声。后半句卡住了。不是故意藏着不说，是她真的一时不知道从哪里讲起。"
    )

    before_summary = workbench.evaluate_ai_flavor_risk(
        title="她一时不知道从哪里讲起",
        body_markdown=candidate_body,
    )

    softened = workbench._soften_not_ab_residue(
        title="她一时不知道从哪里讲起",
        body_markdown=candidate_body,
    )

    after_summary = workbench.evaluate_ai_flavor_risk(
        title="她一时不知道从哪里讲起",
        body_markdown=softened,
    )

    assert softened != candidate_body
    assert "她真的一时不知道从哪里讲起" in softened
    assert "先说成故意藏着不说，反而太轻了" in softened
    assert after_summary.score < before_summary.score
    assert not any("不是A，是B" in hit for hit in after_summary.hits)


def test_soften_not_ab_residue_rewrites_three_residual_reversals() -> None:
    candidate_body = (
        "有些变化很难在当场被承认。不是因为她真的觉得自己没事，而是“我最近不太对劲”这句话一旦说出口，就像要连带承认很多事。\n\n"
        "都行有时不是体贴，是脑子已经不想再做选择。\n\n"
        "真正卡住的地方，常常不是她没发现，而是她发现了也不敢认。"
    )

    before_summary = workbench.evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=candidate_body,
    )

    softened = workbench._soften_not_ab_residue(
        title="别把日子过反了",
        body_markdown=candidate_body,
    )

    after_summary = workbench.evaluate_ai_flavor_risk(
        title="别把日子过反了",
        body_markdown=softened,
    )

    assert softened != candidate_body
    assert "“我最近不太对劲”这句话一旦说出口" in softened
    assert "真要把它当成没事，后面那点拖延和硬撑反而更难解释" in softened
    assert "脑子已经不想再做选择" in softened
    assert "先说成体贴，反而太轻了" in softened
    assert "她发现了也不敢认" in softened
    assert "真要这么说，也把事情说浅了" in softened
    assert "只是更容易先被人拿来安慰自己" not in softened
    assert after_summary.score < before_summary.score
    assert not any("不是A，是B" in hit for hit in after_summary.hits)


def test_soften_not_ab_residue_keeps_long_right_clause_without_mass_producing_rebound_tails() -> None:
    candidate_body = (
        "不是突然一下到了重症那一步，而是把请假难、孩子的事、工作节点、家里老人、这个月不能停，排在自己前面。\n\n"
        "不是没感觉，而是请假要解释，家里要重新协调，工作要有人接。\n\n"
        "不是病名本身，而是前面明明有过好几次能停下来的机会。"
    )

    softened = workbench._soften_not_ab_residue(
        title="把复查一拖再拖的人，生活会慢慢缩到只剩先扛着",
        body_markdown=candidate_body,
    )

    assert "不是突然一下到了重症那一步" not in softened
    assert "把请假难、孩子的事、工作节点、家里老人、这个月不能停，排在自己前面" in softened
    assert "请假要解释，家里要重新协调，工作要有人接" in softened
    assert softened.count("反而把事情说浅了") <= 1
    assert "真要把它算成突然一下到了重症那一步" not in softened
    assert "真要把它算成没感觉" not in softened
    assert "真要把它算成病名本身" not in softened


def test_strip_rebound_explainer_tail_residue_removes_repeated_rebound_tails() -> None:
    candidate_body = (
        "# 复查一拖再拖，身体就会替你把账记到后面\n\n"
        "鞋变紧了，先当盐吃多了。总觉得虚，就归到工作太满。吃不下饭，也拿天气热压过去。解释一顺手，复查就更容易往后拖。拖久了，最先被拖钝的还判断力。真要把它算成病情这两个字，反而把事情说浅了。人会慢慢分不清，什么是熬两天就能缓过来的累，什么已经到了该停下来的程度。\n\n"
        "等到尿毒症，会怀念曾经只是浮肿和乏力；等到透析，又会怀念刚查出尿毒症的时候。人每一次都觉得还能往后让一让。真要把它算成完全没被提醒过，前面有过好几个路口，只，反而把事情说浅了。让到最后，代价就整段压过来了。\n\n"
        "抽屉里的那张单子，今天拿不拿出来，差别很大。很多更重的代价，并从这类看上去还能往后放的小事，一点点追到账上。真要把它算成突然落下来的，都，反而把事情说浅了。"
    )

    cleaned = workbench._strip_rebound_explainer_tail_residue(
        title="复查一拖再拖，身体就会替你把账记到后面",
        body_markdown=candidate_body,
    )

    assert "真要把它算成病情这两个字" not in cleaned
    assert "真要把它算成完全没被提醒过" not in cleaned
    assert "真要把它算成突然落下来的" not in cleaned
    assert "只，" not in cleaned
    assert "都，" not in cleaned
    assert "人会慢慢分不清" in cleaned
    assert "让到最后，代价就整段压过来了" in cleaned
    assert "很多更重的代价" in cleaned


def test_strip_orphaned_rebound_tail_residue_removes_broken_tail_fragments() -> None:
    candidate_body = (
        "# 那张没去复查的单子，通常比诊断书更早知道你扛不住了\n\n"
        "它，你已经收到了提醒，但生活里没有给自己留处理提醒的位置。它代表的，反而把事情说浅了。"
        "你可以把很多人很多事安排进去，却没有把自己的复查、睡觉、吃饭、休息排进同等优先级。"
    )

    cleaned = workbench._strip_orphaned_rebound_tail_residue(
        title="那张没去复查的单子，通常比诊断书更早知道你扛不住了",
        body_markdown=candidate_body,
    )

    assert "它代表的，反而把事情说浅了" not in cleaned
    assert "它，你已经收到了提醒" not in cleaned
    assert "你已经收到了提醒，但生活里没有给自己留处理提醒的位置" in cleaned
    assert "你可以把很多人很多事安排进去" in cleaned


def test_strip_orphaned_rebound_tail_residue_removes_mid_sentence_tail_fragment() -> None:
    candidate_body = (
        "# 消息改了三遍还发不出\n\n"
        "很多人的收口，几次认真开口，换来轻飘飘的回应。真要把它算成突然发生的。，反而把事情说浅了；"
        "是明明在说委屈，对方只盯着语气；是你把边界提出来，场面立刻变得尴尬，最后还是你先圆回来。"
    )

    cleaned = workbench._strip_orphaned_rebound_tail_residue(
        title="消息改了三遍还发不出",
        body_markdown=candidate_body,
    )

    assert "真要把它算成突然发生的" not in cleaned
    assert "反而把事情说浅了" not in cleaned
    assert "是明明在说委屈" not in cleaned
    assert "明明在说委屈，对方只盯着语气" in cleaned
    assert "你把边界提出来，场面立刻变得尴尬" in cleaned


def test_strip_orphaned_rebound_tail_residue_removes_broken_common_shape_fragment() -> None:
    candidate_body = (
        "# 总在半夜翻旧账的关系，已经耗到你了\n\n"
        "很多消耗，你明明已经不舒服，还在维持体面，维持理解，维持那句“再看看”。"
        "真要把它算成从一次争吵开始的。它更常见的样子。"
        "白天照常上班，照常说笑，事情也在做，节奏却乱了。"
    )

    cleaned = workbench._strip_orphaned_rebound_tail_residue(
        title="总在半夜翻旧账的关系，已经耗到你了",
        body_markdown=candidate_body,
    )

    assert "真要把它算成从一次争吵开始的" not in cleaned
    assert "它更常见的样子" not in cleaned
    assert "白天照常上班，照常说笑，事情也在做，节奏却乱了" in cleaned


def test_collapse_isolated_quote_example_residue_merges_quote_run() -> None:
    candidate_body = (
        "# 标题\n\n"
        "真要往回拿，先别急着追求“会说话”。\n\n"
        "比如：“刚才那样说，我不舒服。”。\n\n"
        "“这件事我做不到。”。\n\n"
        "“这个问题你得回应我。”。\n\n"
        "发出去，先停在这里。"
    )

    cleaned = workbench._collapse_isolated_quote_example_residue(
        title="标题",
        body_markdown=candidate_body,
    )

    assert "比如：“刚才那样说，我不舒服。”“这件事我做不到。”“这个问题你得回应我。”" in cleaned
    assert "\n\n“这件事我做不到。”" not in cleaned
    assert "\n\n“这个问题你得回应我。”" not in cleaned
    assert "发出去，先停在这里。" in cleaned


def test_soften_direct_address_lecture_residue_rewrites_low_score_lecture_shell() -> None:
    candidate_body = (
        "# 等到话越来越少，很多亏欠已经落在自己身上了\n\n"
        "你有没有过这种阶段：消息看见了，不想回；别人多问两句，胸口就发闷；明明没出什么大事，人却像被抽掉了反应。答案我先直接告诉你，这通常不是懒，也不是你忽然变脆弱了。更常见的情况是，你已经很久没把自己放进日程里，身体和情绪先替你停了下来。\n\n"
        "手机界面还亮着，消息一排排挂在那里。\n\n"
        "你看见了，也知道该回谁，先点掉，又退出来。\n\n"
        "如果你这段时间已经开始变慢、变钝、变得不想说话，就别再拿“还能撑”安慰自己了。先把自己算进去。"
    )

    before_summary = workbench.evaluate_ai_flavor_risk(
        title="等到话越来越少，很多亏欠已经落在自己身上了",
        body_markdown=candidate_body,
    )

    softened = workbench._soften_direct_address_lecture_residue(
        title="等到话越来越少，很多亏欠已经落在自己身上了",
        body_markdown=candidate_body,
    )

    after_summary = workbench.evaluate_ai_flavor_risk(
        title="等到话越来越少，很多亏欠已经落在自己身上了",
        body_markdown=softened,
    )

    assert softened != candidate_body
    assert "你有没有过这种阶段" not in softened
    assert "答案我先直接告诉你" not in softened
    assert "你看见了，也知道该回谁" not in softened
    assert "如果你这段时间已经开始" not in softened
    assert "\n\n先点掉，又退出来。" not in softened
    assert "变慢、变钝、变得不想说话的时候" in softened
    assert "不是……而是" not in softened
    assert after_summary.score < before_summary.score
    assert not any("第二人称讲解台词偏显眼" in hit for hit in after_summary.hits)
    assert not any("不是A，是B" in hit for hit in after_summary.hits)
    assert not any("解释连接词偏多" in hit for hit in after_summary.hits)


def test_soften_connector_residue_clears_minor_explanatory_connector_shell() -> None:
    candidate_body = (
        "她也没请假，没哭，没跟谁吵起来。工作照常交，消息照常回，见到人也会笑。表面看不出什么大问题，所以她自己也更容易把这些小卡顿压成一句：最近状态不好。\n\n"
        "有时她也会察觉到不对。比如原来十分钟能做完的表格，现在坐了半小时还没进入状态；比如以前能接住的话题，现在听别人说话都觉得费劲；比如有人关心她一句“你最近还好吗”，她喉咙发紧，差点就想说实话了，最后还是习惯性回：挺好的。\n\n"
        "所以她更容易用力把自己往“正常”里推。困了就灌咖啡，迟钝了就逼自己集中，想安静会儿又怕显得消极。"
    )

    before_summary = workbench.evaluate_ai_flavor_risk(
        title="她还是习惯性回了句挺好的",
        body_markdown=candidate_body,
    )

    softened = workbench._soften_connector_residue(
        title="她还是习惯性回了句挺好的",
        body_markdown=candidate_body,
    )

    after_summary = workbench.evaluate_ai_flavor_risk(
        title="她还是习惯性回了句挺好的",
        body_markdown=softened,
    )

    assert softened != candidate_body
    assert "表面看不出什么大问题，她自己也更容易" in softened
    assert "。原来十分钟能做完的表格" in softened
    assert "；以前能接住的话题" in softened
    assert "；有人关心她一句“你最近还好吗”" in softened
    assert "所以她更容易用力把自己往“正常”里推" not in softened
    assert after_summary.score < before_summary.score
    assert not any("解释连接词偏多" in hit for hit in after_summary.hits)


def test_final_ai_flavor_cleanup_triggers_for_embedded_banner_residue() -> None:
    candidate_body = (
        "# 别把日子过反了\n\n"
        "她回工作消息还是很快，真正拖着不想点开的，反而是那些要带情绪、要接回应的话。\n\n"
        "这条线常常就是这么出来的。休息往后挪，情绪往后挪，身体给的提醒也往后挪。困了，先把表格做完；胃空着，先把会开完；体检预约改了又改，心里想着下周总能腾出空。\n\n"
        "关系也是这样淡下去的。朋友问近况，本来只是想听你说两句真的；家里来消息，也未必是催你做什么。可聊天框停在“改天见”后面太久，下一次点开时，里面会多出层生分。"
    )

    assert workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="别把日子过反了",
        candidate_markdown=candidate_body,
    )


def test_final_ai_flavor_cleanup_triggers_for_explainer_shell_residue_only() -> None:
    candidate_body = (
        "# 等到身体先报警，才发现自己一直排在最后\n\n"
        "体检单上多了一行红字，你盯着下周那场会，想的还是能不能照常开。情绪忽然失控那次，你也没把它当回事，只当自己这阵子没休息好。连休息都变成任务的人，最容易把“累”理解成忙，把“撑不住”理解成自己还不够能扛。成年后的很多疲惫，起点往往更早：你已经习惯了，谁都可以排在你前面，只有你自己，总往后挪。\n\n"
        "这个顺序，不是一夜之间改掉的。通常是从很小的地方开始。消息先回，工作先交，家里的事先补上，朋友的请求先答应。轮到自己，复查可以下周再去，饭晚一点吃也行，睡眠先欠着，衣服鞋子还能将就。外面给你的反馈很直接，回得快、做得多、顶得住，就会被夸靠谱、懂事、顾全大局。照顾自己没那么立刻，少休一次，不会马上出大事；少吃一顿，也还能撑完今天。人就是在这种“暂时没问题”里，把自己一点点放到了最后。\n\n"
        "最难受的地方还不在忙。忙有时是阶段性的，过去就过去了。真正消耗人的，是你慢慢默认了：自己的不舒服可以先放一放，自己的需要可以再等等，自己的委屈没那么要紧。这个默认，会把人训练得很麻木。你明明已经发烧，还在改方案；经期疼得站不久，还在说没事；一句话已经冒犯了你，你先顾的是别把气氛弄僵。你一次次退后，不全是善良，也夹着一种很深的熟悉感：只要我还能扛，我就先扛。久了，连你自己都开始把这件事当成理所当然。\n\n"
        "很多女人的亏欠感，就是在这里长出来的。你总觉得自己还不够好，休息像偷懒，拒绝像亏待别人，花时间在自己身上，还要先补一句“我最近真的有点累”。这背后常常是一种价值感绑定：你把自己有没有用，看得比自己舒不舒服更重要。别人需要你，你会有存在感；轮到你需要被照顾，第一反应却常常是收回去。你怕麻烦人，怕显得矫情，怕一停下来，别人会失望。可身体不会配合这套逻辑。它只会在你长期忽略它的时候，用失眠、暴躁、心慌、内耗把账一点点送回来。\n\n"
        "人往往要等到真出问题，才承认自己丢了东西。请假住院那几天，你会忽然发现，少了你，很多事也还能转；一段一直靠你兜底的关系，一旦你不再提供情绪劳动，对方未必真会站出来接住你。那一刻你才看清，过去那些被你牺牲掉的睡眠、体力、兴趣、体面，都是从自己身上硬扣出去的。失去感会疼，疼也有用。它逼你承认，你早就欠了自己很多。\n\n"
        "还有一种失衡，表面看很小，拖久了最伤。医生让你三个月后复查，你拖成了八个月；牙疼一阵一阵，你总说过两天再去；心里已经很压抑了，还是把假期让给“更重要的安排”；一段关系里你总负责理解、安抚、兜底，轮到你难受，对方只回一句“你别想太多”。这些都容易被归进“小事不算事”。可小事重复得够久，就会改写一个人对自己的态度。你会越来越难分清，自己到底是在体谅别人，还是已经习惯亏待自己。\n\n"
        "把自己往前放，不用等到辞职、搬家、彻底翻篇那种大动作。成年人的止损，常常先从顺序改起。身体不舒服，就先去看；已经累到说话带火气，就先停一停；不属于你的额外责任，少接一点；能晚回的消息，晚回；周末留半天给自己，不拿来补所有人的需求。关键在于让自己看见：我的事也有名字，我的感受也占位置。我可以照顾人，也可以先照顾我自己。\n\n"
        "这件事刚开始，常常会有阻力。你会不习惯，会想把刚留出来的时间再让出去，会在拒绝别人之后冒出一点歉意。这不代表你做错了，只是旧顺序还在往回拽。你以前总把自己垫在最下面，大家都站稳了，只有你一直悬着。现在只是把那块垫子抽回来一点，让自己能落地。\n\n"
        "成年后最该补上的，是别再拿自己垫底。先去复查，先把晚饭吃完，先把那句“这次我来不了”发出去。做一件就够了。你会慢慢认出来，善待自己不是附加项，它本来就该在你的生活里面。"
    )

    assert workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="等到身体先报警，才发现自己一直排在最后",
        candidate_markdown=candidate_body,
    )


def test_final_ai_flavor_cleanup_triggers_for_lecture_line_residue_only() -> None:
    candidate_body = (
        "# 等到话越来越少，很多亏欠已经落在自己身上了\n\n"
        "你有没有过这种阶段：消息看见了，不想回；别人多问两句，胸口就发闷；明明没出什么大事，人却像被抽掉了反应。答案我先直接告诉你，这通常不是懒，也不是你忽然变脆弱了。更常见的情况是，你已经很久没把自己放进日程里，身体和情绪先替你停了下来。\n\n"
        "这份发钝最容易被误解。旁人会说你只是最近太累，休息两天就好；你自己也会拿“先把今天过完”压过去。可很多亏空，根本不是两天形成的。饭总在后面吃，觉总往后挪，不舒服先忍，体检改下个月，情绪等忙完再整理。每次都只是往后推一点，推到最后，被挪走的就是你自己。\n\n"
        "手机界面还亮着，消息一排排挂在那里。\n\n"
        "你看见了，也知道该回谁，先点掉，又退出来。\n\n"
        "如果你这段时间已经开始变慢、变钝、变得不想说话，就别再拿“还能撑”安慰自己了。先把自己算进去。"
    )

    assert workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="等到话越来越少，很多亏欠已经落在自己身上了",
        candidate_markdown=candidate_body,
    )


def test_final_ai_flavor_cleanup_triggers_for_opening_explainer_shell_only() -> None:
    candidate_body = (
        "# 等到身体先报警，才发现自己一直排在最后\n\n"
        "你以为自己只是累吗？有一类疲惫，休息一天也缓不过来。别人一有需要，你立刻接住；轮到自己的睡眠、情绪、体检和那顿该好好吃的饭，你总能往后再挪一点。\n\n"
        "它一开始并不惊人，甚至很像负责。工作临时加项，你先改；家里有人要你搭把手，你先去；关系里气氛不对，你先安抚。短时间里，事情被处理了，场面也稳住了，后面留下来的，是睡眠被切碎，身体信号被拖延，情绪越来越晚才轮到被照顾。\n\n"
        "成年人的生活里，最会抢位置的，几乎都是紧急的东西。消息要回，节点要赶，孩子和父母的问题要接，伴侣的情绪也需要回应。你的需要通常没有那么大的声量，它不敲门，只是在肩颈发紧、经期紊乱、胃口变差、耐心变短时提醒你。\n\n"
        "很多亏空，不是一天形成的。你只是一次次把那句“我现在也不太行”压回去，久了，身体和情绪就先替你停下来。"
    )

    assert workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="等到身体先报警，才发现自己一直排在最后",
        candidate_markdown=candidate_body,
    )


def test_final_ai_flavor_cleanup_skips_for_connector_only_residue() -> None:
    candidate_body = (
        "# 门关上之后，她才意识到自己已经转不动了\n\n"
        "门合上的声音很轻，她把包丢在玄关砖上，没开灯，也没弯腰换鞋。\n\n"
        "她盯着手机屏幕看了两秒，所以原本要回的消息还是没点开。然后她把手机按灭，还是没有往里走。\n\n"
        "其实她知道自己不是不想动，只是脑子和身体都慢了半拍。最后连去烧壶水这件事，也像要重新发动一次。"
    )

    assert not workbench._should_retry_for_final_ai_flavor_cleanup(
        candidate_title="门关上之后，她才意识到自己已经转不动了",
        candidate_markdown=candidate_body,
    )


def test_pick_better_ai_flavor_candidate_preserves_minor_human_roughness() -> None:
    current_body = (
        "# 别把日子过反了\n\n"
        "包带还挂在肩上，勒得锁骨发酸。她站在洗手台前，把牙膏挤到牙刷上，白色膏体歪歪地停在刷毛边缘，快要掉下来。\n\n"
        "她没动。\n\n"
        "水龙头没有开，手也没抬起来。就那么站了十几秒，脑子里先冒出来的是：明天不能再这样了。接着，空了。\n\n"
        "可身体有时不按这套来。你越催，它越迟。"
    )
    retried_body = (
        "# 别把日子过反了\n\n"
        "她站在洗手台前，忽然意识到自己已经累过头了。那些被往后推的安排、身体信号和没回完的关系，都在这个时刻一起浮上来。\n\n"
        "她知道自己该慢下来，也知道有些事不能再一直往后排。"
    )

    chosen_markdown, chosen_title = workbench._pick_better_ai_flavor_candidate(
        current_title="别把日子过反了",
        current_markdown=current_body,
        retried_title="别把日子过反了",
        retried_markdown=retried_body,
    )

    assert chosen_title == "别把日子过反了"
    assert chosen_markdown == current_body


def test_pick_better_ai_flavor_candidate_rejects_over_smoothed_cleanup_even_if_score_drops() -> None:
    current_body = (
        "# 标题\n\n"
        "中午十二点多，桌角那杯水还是满的。\n\n"
        "她刚从会议室出来，电脑还夹在臂弯里，群消息一层层往上顶，手机屏幕亮了又暗。旁边有人问文件放哪儿，她说“我发你”，声音听着还稳，手却先去按了按桌沿。指尖有点凉，后颈发紧，像有块硬东西贴在那儿。\n\n"
        "水就在手边，她没喝。想着把这页改完再去吃，邮件发完再说，等对方回了再说。这样往后挪，挪着挪着，饿意先没了，只剩胃里发空。\n\n"
        "早上出门前，速度就已经不对了。闹钟六点四十响，她按掉。七点整又响，手机被塞进枕头下面。第三次睁眼时，窗帘缝里的光已经发白，牙刷含在嘴里，人却对着镜子站了很久，泡沫快落到手背上，才想起来漱口。洗脸巾拧到一半，动作停住了，像脑子还没接上今天。\n\n"
        "到电梯口时，她伸手挡了下快要合上的门。明明只走了半层楼，胸口却先紧起来，那口气卡在喉咙口，上不去，也下不来。金属扶手有点凉，她低头盯了两秒鞋尖，等那阵发虚过去，再把手机翻过来。屏幕上已经跳出三条工作消息。她先回“收到”，又补了个表情，像这样，早晨才算接上轨。\n\n"
        "人开始耗的时候，常常不是先崩掉，也不是先哭出来。更常见的是动作变慢，脑子发木，站在水池前发愣，拿着杯子走到饮水机旁边，忽然忘了自己要做什么。可她当下最先催自己的，往往还是那句：快点，别磨蹭。\n\n"
        "这句催促很有用，至少在白天有用。它能把不舒服暂时压平，让人继续开会、记笔记、回消息、接任务，也能让那杯水一直放在桌角，像个没人顾得上的旁证。\n\n"
        "下午三点多，身体给了次更直接的提醒。心跳突然快了一拍，太阳穴往里收，椅背贴着后背也不舒服。她把手放在桌沿上，缓了缓。旁边同事还在等文件，她照常接话，照常把事情往下接，转身去茶水间买了杯冰美式。\n\n"
        "解释也来得很快：昨晚睡少了，今天会多，喝点咖啡就过去了。\n\n"
        "人一旦先替不适找好了理由，后面的动作就会很顺。回工位，盯屏幕，继续把自己往下一格日程里塞。问题不在那一刻有没有忍住，问题在于这种处理会留下尾巴。晚上回家，人已经空了，却说不清是累，还是哪里真的出了状况。第二天起床，速度更慢，再逼自己追上去。\n\n"
        "傍晚，朋友发来一条消息：\n\n"
        "“你最近怎么都不说话了？”\n\n"
        "她看见了，点进去，又退出来。过了十几分钟，回了个捂脸表情。对方又问：“忙成这样？”她盯着那四个字看了几秒，最后发过去一句：“这阵子有点满。”\n\n"
        "其实手机这头并不是真的没话。耳边那阵嗡嗡的底噪，午饭拖到两点半，开完会站起来时眼前黑了一下，回家后不想开灯，也不想把今天从头讲一遍——这些都在。只是要把它们组织成一句完整的话，也挺费劲的。更麻烦的不是没人问，是有人问了，她也知道自己该回，但身体已经先把沉默当成省力模式了。"
    )
    retried_body = (
        "# 标题\n\n"
        "中午十二点多，桌角那杯水还是满的。\n\n"
        "她刚从会议室出来，电脑还夹在臂弯里，群消息一层层往上顶，手机屏幕亮了又暗。旁边有人问文件放哪儿，她说“我发你”，声音还稳，手先去按了按桌沿。指尖发凉，后颈那块筋绷着，像从早上一直没松开。\n\n"
        "水就在手边，她看见了，没喝。脑子里想的是把这页改完再去吃，邮件发完再说，等对方回了再说。事情被这样一格格往后挪，挪到后来，饿意先退了，胃里只剩空。\n\n"
        "早上出门前，速度就已经乱了。闹钟六点四十响过一次，七点整又响，手机被她塞进枕头下面。第三回睁眼，窗帘缝里的光已经发白。牙刷含在嘴里，人却对着镜子站了会儿，泡沫快落到手背上，才想起来漱口。洗脸巾拧到半截，动作停住，像脑子还没跟上今天。\n\n"
        "到电梯口，她伸手去挡快合上的门。明明只走了半层楼，胸口却先紧起来，那口气卡在喉咙口，上不去，也下不来。金属扶手有点凉，她低头盯着鞋尖，等那阵发虚过去，再把手机翻过来。三条工作消息已经跳出来了，她回了两个“收到”，早晨像是这时候才硬接上。\n\n"
        "人耗下去，常常就是从这些地方开始的：动作慢半拍，站在水池前发愣，拿着杯子走到饮水机旁边，又忘了自己过来干什么。可当场最先冒出来的，往往不是“我得歇会儿”，而是另一句更熟的催促——快点，别卡着。"
    )

    chosen_markdown, chosen_title = workbench._pick_better_ai_flavor_candidate(
        current_title="标题",
        current_markdown=current_body,
        retried_title="标题",
        retried_markdown=retried_body,
    )

    assert chosen_title == "标题"
    assert chosen_markdown == current_body


def test_remaining_ai_flavor_retry_instruction_bans_new_not_ab_for_analytic_prose() -> None:
    candidate_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "你以为自己缺的是技巧，后来才发现，不是不懂，而是根本没有能量。\n\n"
        "很多关系真正难的，不是一下子散掉，而是长期的亏空把耐心、注意力和柔软都磨薄了。\n\n"
        "不是你故意要把话说坏，而是防御比表达跑得更快。不是没有感觉，是已经不想再组织语言。"
        "不是坏在某个原则上，而是耗在长期亏空里。\n\n"
        "关系卡住时，最常见的样子往往是三件事同时存在：\n\n"
        "✔ 意愿有\n\n"
        "✔ 方法也知道\n\n"
        "✔ 但人已经空了。"
    )

    instruction = workbench._build_remaining_ai_flavor_retry_instruction(
        base_instruction="降低模板感，但保留原稿结构和判断路径。",
        source_markdown=candidate_body,
        candidate_title="关系卡住的本质：意愿有、懂方法、但无能量",
        candidate_markdown=candidate_body,
    )

    assert "分析型或并列展开的段落" in instruction
    assert "全文不要新增任何新的“不是……而是/是……”骨架" in instruction


def test_remaining_ai_flavor_retry_instruction_calls_out_short_judgment_cadence() -> None:
    candidate_body = (
        "# 她后来没再把真心话都留到夜里\n\n"
        "电梯快合上的时候，她低头看了眼手机。\n\n"
        "置顶对话里躺着两条昨晚没回完的消息。朋友问她这周要不要见面，妈妈发来一张家里阳台新开的花。她的手指停在屏幕上方，楼层往下跳，她先回了工作群里的“收到”，又把那两个对话按灭。\n\n"
        "白天的她并没有闲着。\n\n"
        "消息很多，页面一直在跳。确认排期、对接流程、改表格、补一句“辛苦了”、再接住新的安排。她能回的大多是这种话：明确，简短，不需要情绪，也不需要把自己放进去。\n\n"
        "聊天框也会变得很难打开。\n\n"
        "她不是没话说，是那种要把心思拿出来、把语气放软、把一句普通回复变成真正的交流，这件事忽然很重。光是想一想，就已经觉得累。\n\n"
        "后来她有过个很小的变化。\n\n"
        "午休快结束时，她没有先去刷工作群，而是靠在茶水间窗边，回了朋友那条约见面的消息。没写很多，只是认真定了个周六下午。\n\n"
        "这一步很难。\n\n"
        "因为她清楚，一旦停下来，很多被压着的东西会一起冒头。委屈、烦躁、亏空感，还有那种说不出口的失望。"
    )

    instruction = workbench._build_remaining_ai_flavor_retry_instruction(
        base_instruction="降低模板感，但保留原稿结构和判断路径。",
        source_markdown=candidate_body,
        candidate_title="她后来没再把真心话都留到夜里",
        candidate_markdown=candidate_body,
    )

    assert "这些独立短判断段要处理掉或并回前后段" in instruction
    assert "固定节拍" in instruction


def test_remaining_ai_flavor_retry_instruction_calls_out_embedded_banners() -> None:
    candidate_body = (
        "# 别把日子过反了\n\n"
        "电梯门快合上时，她抬手挡了下。门弹开，白光照着空空的轿厢。手机在掌心震了两次，聊天框停在那句没发出去的话上：这阵子有点忙，忙完再联系。\n\n"
        "这条线常常就是这么出来的。休息往后挪，情绪往后挪，身体给的提醒也往后挪。困了，先把表格做完；胃空着，先把会开完；体检预约改了又改，心里想着下周总能腾出空。\n\n"
        "关系也是这样淡下去的。朋友问近况，本来只是想听你说两句真的；家里来消息，也未必是催你做什么。可聊天框停在“改天见”后面太久，下一次点开时，里面会多出层生分。"
    )

    instruction = workbench._build_remaining_ai_flavor_retry_instruction(
        base_instruction="降低模板感，但保留原稿结构和判断路径。",
        source_markdown=candidate_body,
        candidate_title="别把日子过反了",
        candidate_markdown=candidate_body,
    )

    assert "这些先总括再展开的长段起手要拆掉" in instruction
    assert "这条线常常就是这么出来的。" in instruction


def test_final_ai_flavor_cleanup_instruction_calls_out_connector_and_yi_cadence() -> None:
    candidate_body = (
        "# 别让赌气毁掉关系\n\n"
        "很多时候，手指停在输入框上，一下删掉，一遍重写。\n\n"
        "其实你不是不想说，而是那口气一直卡着，所以一句软话也递不出去。\n\n"
        "你等他来问，他等你自己说。然后消息停着，一个字一个字往回吞。\n\n"
        "一会儿想解释，一会儿又后悔。最后连原本要说的话，也被一句算了带过去。\n\n"
        "说到底，真正先累垮的往往还是彼此的心。"
    )

    instruction = workbench._build_final_ai_flavor_cleanup_instruction(
        base_instruction="降低模板感，但保留原稿结构和案例。",
        source_markdown=candidate_body,
        candidate_title="别让赌气毁掉关系",
        candidate_markdown=candidate_body,
    )

    assert "删掉部分解释连接词" in instruction
    assert "一字量词起手" in instruction


def test_polish_draft_runs_final_ai_flavor_cleanup_for_low_score_residue(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "最后一轮局部清理" in instruction:
                    return {
                        "title": "别把日子过反了",
                        "body_markdown": (
                            "# 别把日子过反了\n\n"
                            "白天忙的时候，很多事都会被往后推。等真正安静下来，人才会发现，最容易被省掉的总是身体、关系和自己真正想顾住的部分。\n\n"
                            "朋友阿杰总说等这个项目结束就休息。后来躺在病床上，他才承认自己早就累过头了，只是一直没肯停下来。\n\n"
                            "外婆走后，我翻手机才知道，有些想留下来的时刻，当时并没有认真接住。很多话拖过那个时候，再说就不对了。\n\n"
                            "很多事看着都能往后放，可真正先被拖走的，往往是身体和关系。"
                        ),
                    }
                if "上一次精修后，模板风险还没压够" in instruction:
                    return {
                        "title": "别把日子过反了",
                        "body_markdown": (
                            "# 别把日子过反了\n\n"
                            "白天忙的时候，很多事都会被往后推。等真正安静下来，人总会回头想想自己把什么排到了后面。\n\n"
                            "朋友阿杰总说等这个项目结束就休息。后来躺在病床上，他才承认自己早就累过头了，只是一直没肯停下来。\n\n"
                            "外婆走后，我翻手机才知道，有些想留下来的时刻，当时并没有认真接住。很多话拖过那个时候，再说就不对了。\n\n"
                            "我们总以为以后还有机会。\n\n"
                            "不是没时间，是总把重要的事往后排。"
                        ),
                    }
                return {
                    "title": "别把日子过反了",
                    "body_markdown": (
                        "# 别把日子过反了\n\n"
                        "朋友阿杰总说等这个项目结束就休息。后来他躺在病床上才意识到，不是不累，是一直没给自己停下来的机会。\n\n"
                        "外婆走后，我翻手机才知道，有些想留下来的时刻，当时并没有认真接住。不是不在意，是总把以后想得太宽。\n\n"
                        "很多事看着都能往后放，可真正先被拖走的，往往是身体和关系。"
                    ),
                }
            return {
                "title": "别把日子过反了",
                "body_markdown": "# 别把日子过反了\n\n草稿",
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    tone_profile = workbench.get_active_tone_profile()
    seeded_body = (
        "# 别把日子过反了\n\n"
        "阿杰晕倒之后，才肯承认自己已经很久没有认真休息。\n\n"
        "外婆走后，我翻手机时才知道，很多平常时刻原来并不会重来。\n\n"
        "想做的事，别一直往后拖。"
    )
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count,
                created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                1,
                1,
                "别把日子过反了",
                seeded_body,
                len(seeded_body),
                workbench._utc_now_iso(),
                "manual_seed",
                tone_profile.id,
                tone_profile.name,
            ),
        )
        connection.commit()

    calls_before_manual_polish = len(fake_generator.calls)
    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构和案例。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert "不是没时间" not in polished["body_markdown"]
    assert "我们总以为" not in polished["body_markdown"]
    assert "朋友阿杰总说等这个项目结束就休息" in polished["body_markdown"]

    manual_polish_calls = fake_generator.calls[calls_before_manual_polish:]
    polish_calls = [
        call for call in manual_polish_calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) == 3
    instructions = [str(call[1]["polish_instruction"]) for call in polish_calls[1:]]
    assert any("上一次精修后，模板风险还没压够" in instruction for instruction in instructions)
    assert any("最后一轮局部清理" in instruction for instruction in instructions)


def test_polish_draft_runs_final_ai_flavor_cleanup_for_moderate_score_small_residue(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "最后一轮局部清理" in instruction:
                    return {
                        "title": "别让赌气毁掉关系",
                        "body_markdown": (
                            "# 别让赌气毁掉关系\n\n"
                            "聊天框停在那儿，输入了几行，又删掉。手指悬着，最后只回了个句号，或者干脆把手机扣在桌上，等着对方先来找你。\n\n"
                            "关系变坏，常常不是从大吵大闹开始。往前倒，往往能看到某次赌气：谁都不愿先服软，谁都想等对方先低头。\n\n"
                            "你等他来问，他等你自己说。表面上风平浪静，实际每次沉默都在往中间添块砖。后来再看，压垮关系的未必是某件大事，反而常常是这些没说出口的瞬间。\n\n"
                            "但感情里很多僵住的时刻，真正卡住的，是那口咽不下去的气。你明明想要安慰，开口却成了反话；明明舍不得，转身时偏偏把脚步放得很重。\n\n"
                            "先耗掉的，往往还是彼此的心。"
                        ),
                    }
                return {
                    "title": "别让赌气毁掉关系",
                    "body_markdown": (
                        "# 别让赌气毁掉关系\n\n"
                        "很多时候，手指停在输入框上，一下删掉，一遍重写，一个字一个字往回吞。\n\n"
                        "其实你不是不想说，而是那口气一直卡着，所以一句软话也递不出去。\n\n"
                        "你等他来问，他等你自己说。然后消息停着，后来沉默也跟着变重。\n\n"
                        "说到底，真正先累垮的往往还是彼此的心。"
                    ),
                }
            return {
                "title": "别让赌气毁掉关系",
                "body_markdown": "# 别让赌气毁掉关系\n\n草稿",
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    tone_profile = workbench.get_active_tone_profile()
    seeded_body = (
        "# 别让赌气毁掉关系\n\n"
        "你等他来问，他等你自己说。\n\n"
        "赌气最怕的，是谁都不肯先开口。"
    )
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count,
                created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                1,
                1,
                "别让赌气毁掉关系",
                seeded_body,
                len(seeded_body),
                workbench._utc_now_iso(),
                "manual_seed",
                tone_profile.id,
                tone_profile.name,
            ),
        )
        connection.commit()

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构和案例。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert "很多时候" not in polished["body_markdown"]
    assert "说到底" not in polished["body_markdown"]
    assert "不是不想说，而是那口气一直卡着" not in polished["body_markdown"]

    polish_calls = [
        call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) >= 2
    assert any("最后一轮局部清理" in str(call[1]["polish_instruction"]) for call in polish_calls)


def test_polish_draft_retries_when_moderate_not_ab_residue_still_heavy(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "上一次精修后，模板风险还没压够" in instruction:
                    return {
                        "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                        "body_markdown": (
                            "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
                            "看到这里，很多人会先把问题归到“不会沟通”上。可真落到自己身上，真正卡住的，不全是方法。\n\n"
                            "关系推不动的时候，更常见的是人已经累了，心力先见底。\n\n"
                            "你会发现，关系卡住时，常常是三件事叠在一起：\n\n"
                            "✔ 意愿有\n\n"
                            "✔ 方法也知道\n\n"
                            "✔ 但没有能量\n\n"
                            "意愿有，说明她心里还想把这段关系往回带。\n\n"
                            "方法也知道，说明那些表达和边界的道理她并非没看过。\n\n"
                            "先补能量，关系才转得动。"
                        ),
                    }
                return {
                    "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                    "body_markdown": (
                        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
                        "看到这里，很多人会先把问题归到“不会沟通”上。可真落到自己身上，卡住的往往不是方法有没有学过，而是那口气提不上来。\n\n"
                        "关系推不动的时候，最常见的不是完全不在乎，而是人已经累得没有多余的心力。\n\n"
                        "你会发现，关系卡住时，常常是三件事叠在一起：\n\n"
                        "✔ 意愿有\n\n"
                        "✔ 方法也知道\n\n"
                        "✔ 但没有能量\n\n"
                        "意愿有，意味着你不是不想好。\n\n"
                        "方法也知道，意味着你不是没学过。\n\n"
                        "所以，关系里最麻烦的，往往不是没有爱，而是没有余力。不是不想靠近，而是连自己都快顾不上。不是不愿意改变，而是身体和情绪已经长期处在透支里。\n\n"
                        "这时候最先要补的，常常不是沟通术，而是能量。"
                    ),
                }
            return {
                "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                "body_markdown": "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n草稿",
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    tone_profile = workbench.get_active_tone_profile()
    seeded_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "你会发现，关系卡住的时候，常常是意愿有、方法也知道、但没有能量。\n\n"
        "先承认自己很累。"
    )
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count,
                created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                1,
                1,
                "关系卡住的本质：意愿有、懂方法、但无能量",
                seeded_body,
                len(seeded_body),
                workbench._utc_now_iso(),
                "manual_seed",
                tone_profile.id,
                tone_profile.name,
            ),
        )
        connection.commit()

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构和案例。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert "不是没有爱，而是没有余力" not in polished["body_markdown"]
    assert "不是不想靠近，而是连自己都快顾不上" not in polished["body_markdown"]

    polish_calls = [
        call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) >= 2
    assert any("上一次精修后，模板风险还没压够" in str(call[1]["polish_instruction"]) for call in polish_calls)


def test_polish_draft_keeps_better_candidate_when_remaining_ai_flavor_retry_is_worse(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "上一次精修后，模板风险还没压够" in instruction:
                    return {
                        "title": "别把日子过反了",
                        "body_markdown": (
                            "# 别把日子过反了\n\n"
                            "很多遗憾，回头看都不是小事，而是当时没肯停一下。\n\n"
                            "阿杰后来才知道，不是工作本身，是那种总把自己往后放的习惯。\n\n"
                            "我们总以为还来得及。\n\n"
                            "我们总习惯说等以后。\n\n"
                            "说到底，最后不是没有惦记，是总觉得来得及。"
                        ),
                    }
                return {
                    "title": "别把日子过反了",
                    "body_markdown": (
                        "# 别把日子过反了\n\n"
                        "夜里安静下来时，人会重新掂量什么该先顾住。\n\n"
                        "阿杰在医院醒来时，先摸到的是手背上的针。\n\n"
                        "不是发狠撑住，而是先让身体喘口气。\n\n"
                        "从今天开始，别再把最该留给自己的力气往后挪。"
                    ),
                }
            return {
                "title": "别把日子过反了",
                "body_markdown": (
                    "# 别把日子过反了\n\n"
                    "不是等失去才懂痛，而是很多重要的东西，早就在日常里被慢慢放后了。\n\n"
                    "阿杰总说等这个项目结束就休息。\n\n"
                    "外婆突然离世后，我翻遍手机，才发现连一张像样的合照都没有。\n\n"
                    "从今天开始，别把最重要的东西押给以后。"
                ),
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    tone_profile = workbench.get_active_tone_profile()
    seeded_body = (
        "# 别把日子过反了\n\n"
        "夜里静下来时，人会重新掂量什么该先顾住。\n\n"
        "阿杰在医院醒来后，先把手机扣在了床头柜上。\n\n"
        "外婆走后，我才明白有些日常一旦错过去，就补不回来了。\n\n"
        "想做的事，别全留给以后。"
    )
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count,
                created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                1,
                1,
                "别把日子过反了",
                seeded_body,
                len(seeded_body),
                workbench._utc_now_iso(),
                "manual_seed",
                tone_profile.id,
                tone_profile.name,
            ),
        )
        connection.commit()
    calls_before_manual_polish = len(fake_generator.calls)

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构和案例。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert polished["title"] == "别把日子过反了"
    assert "阿杰在医院醒来时" in polished["body_markdown"]
    assert "不是工作本身" not in polished["body_markdown"]
    assert "说到底" not in polished["body_markdown"]

    manual_polish_calls = fake_generator.calls[calls_before_manual_polish:]
    polish_calls = [
        call for call in manual_polish_calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) == 2
    assert "上一次精修后，模板风险还没压够" in str(polish_calls[1][1]["polish_instruction"])


def test_polish_draft_runs_final_cleanup_for_four_not_ab_only_residue(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "最后一轮局部清理" in instruction:
                    return {
                        "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                        "body_markdown": (
                            "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
                            "很多人以为问题出在不会说。可真卡住的时候，更常见的是人已经累得没有余力。\n\n"
                            "身体先绷起来，语气就会变硬；话还没出口，防备已经先到了前面。\n\n"
                            "等能量慢慢接回来，关系才有空间往前走。"
                        ),
                    }
                return {
                    "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                    "body_markdown": (
                        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
                        "不是不懂，而是根本没有能量。不是你故意要把话说坏，而是防御比表达跑得更快。"
                        "不是没有感觉，是已经不想再组织语言。不是坏在某个原则上，而是耗在长期亏空里。"
                    ),
                }
            return {
                "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                "body_markdown": "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n草稿",
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    tone_profile = workbench.get_active_tone_profile()
    seeded_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "先承认人已经累了，再决定下一步怎么靠近。"
    )
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count,
                created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                1,
                1,
                "关系卡住的本质：意愿有、懂方法、但无能量",
                seeded_body,
                len(seeded_body),
                workbench._utc_now_iso(),
                "manual_seed",
                tone_profile.id,
                tone_profile.name,
            ),
        )
        connection.commit()

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构和判断路径。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert "不是不懂，而是根本没有能量" not in polished["body_markdown"]
    assert "更常见的是人已经累得没有余力" in polished["body_markdown"]

    polish_calls = [
        call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) == 2
    assert "最后一轮局部清理" in str(polish_calls[1][1]["polish_instruction"])


def test_polish_draft_runs_second_final_cleanup_when_single_not_ab_residue_remains(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []
            self.final_cleanup_calls = 0

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "最后一轮局部清理" in instruction:
                    self.final_cleanup_calls += 1
                    if self.final_cleanup_calls == 1:
                        return {
                            "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                            "body_markdown": (
                                "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
                                "午休快结束了，茶水间的微波炉叮了一声。你盯着手机里那条没回完的消息，"
                                "手指停在输入框上，删了又打，打了又删。\n\n"
                                "表面看，是回消息慢了，是话题又绕开了，是本来想说软话，出口还是带刺。"
                                "可真正卡住人的，常常不在句子本身。\n\n"
                                "关系不是一下坏掉的，是在长期亏空里慢慢失去弹性。"
                            ),
                        }
                    return {
                        "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                        "body_markdown": (
                            "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
                            "午休快结束了，茶水间的微波炉叮了一声。你盯着手机里那条没回完的消息，"
                            "手指停在输入框上，删了又打，打了又删。\n\n"
                            "表面看，是回消息慢了，是话题又绕开了，是本来想说软话，出口还是带刺。"
                            "可真正卡住人的，常常不在句子本身。\n\n"
                            "关系是在长期亏空里，一点点失去弹性。"
                        ),
                    }
                return {
                    "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                    "body_markdown": (
                        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
                        "不是不懂，而是根本没有能量。不是表达，而是自保。"
                        "不是不珍惜关系，是连呼吸都想省着用。不是一下坏掉的，是在长期亏空里慢慢失去弹性。"
                    ),
                }
            return {
                "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                "body_markdown": "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n草稿",
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    tone_profile = workbench.get_active_tone_profile()
    seeded_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "先承认人已经累了，再决定下一步怎么靠近。"
    )
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count,
                created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                1,
                1,
                "关系卡住的本质：意愿有、懂方法、但无能量",
                seeded_body,
                len(seeded_body),
                workbench._utc_now_iso(),
                "manual_seed",
                tone_profile.id,
                tone_profile.name,
            ),
        )
        connection.commit()

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构和判断路径。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert "关系是在长期亏空里，一点点失去弹性。" in polished["body_markdown"]
    assert "关系不是一下坏掉的，是在长期亏空里慢慢失去弹性。" not in polished["body_markdown"]

    polish_calls = [
        call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) == 3
    assert "最后一轮局部清理" in str(polish_calls[1][1]["polish_instruction"])
    assert "最后一轮局部清理" in str(polish_calls[2][1]["polish_instruction"])


def test_polish_draft_prefers_remaining_retry_when_score_ties_but_residue_drops(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction:
                if "上一次精修后，模板风险还没压够" in instruction:
                    return {
                        "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                        "body_markdown": (
                            "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
                            "很多人一遇到关系卡住，就先去找沟通方法。可真到自己身上，最先掉线的，常常不是技巧，而是余力。\n\n"
                            "人累的时候，心会变窄，话也会变硬。你不是没学过，是当下已经没有多余的稳定；不是失望，而是疲惫在前面顶着。\n\n"
                            "关系推不动时，常见的不是谁彻底不在乎，而是两个人都已经没剩多少缓冲。\n\n"
                            "意愿还在。\n\n"
                            "方法也懂。\n\n"
                            "可人已经快空了。\n\n"
                            "所以这时候最先要补的，不该只是沟通术，还得先把睡眠、情绪和身体那点底子慢慢接回来。"
                        ),
                    }
                return {
                    "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                    "body_markdown": (
                        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
                        "你以为自己缺的是技巧，后来才发现，不是不懂，而是根本没有能量。\n\n"
                        "很多关系真正难的，不是突然变了心，是之前压下去的委屈、疲惫、防备，慢慢把人拖住了。\n\n"
                        "关系卡住时，最常见的样子往往是三件事同时存在：\n\n"
                        "意愿有。\n\n"
                        "方法也知道。\n\n"
                        "但人已经空了。\n\n"
                        "你会发现，很多时候不是判断失灵，而是整个人都在防守；不是你突然变得尖锐，而是神经已经很薄。\n\n"
                        "这时候最先该补的，常常不是沟通术，而是余力。"
                    ),
                }
            return {
                "title": "关系卡住的本质：意愿有、懂方法、但无能量",
                "body_markdown": "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n草稿",
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    tone_profile = workbench.get_active_tone_profile()
    seeded_body = (
        "# 关系卡住的本质：意愿有、懂方法、但无能量\n\n"
        "你会发现，关系卡住的时候，常常是意愿有、方法也知道、但没有能量。\n\n"
        "先承认自己很累，再决定下一步怎么靠近。"
    )
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count,
                created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "office-burnout-recovery-weekly",
                1,
                1,
                "关系卡住的本质：意愿有、懂方法、但无能量",
                seeded_body,
                len(seeded_body),
                workbench._utc_now_iso(),
                "manual_seed",
                tone_profile.id,
                tone_profile.name,
            ),
        )
        connection.commit()

    polish_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/polish-draft",
        json={"instruction": "降低模板感，但保留原稿结构和判断路径。"},
    )
    assert polish_response.status_code == 201
    polished = polish_response.json()

    assert "不是失望，而是疲惫在前面顶着" in polished["body_markdown"]
    assert "不是判断失灵，而是整个人都在防守" not in polished["body_markdown"]

    polish_calls = [
        call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) >= 2
    assert "上一次精修后，模板风险还没压够" in str(polish_calls[1][1]["polish_instruction"])


def test_remaining_ai_flavor_retry_uses_candidate_draft_for_tracked_article(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if instruction and "上一次精修后，模板风险还没压够" in instruction:
                draft_payload = payload.get("draft") or {}
                return {
                    "title": str(draft_payload.get("title") or "新标题"),
                    "body_markdown": str(draft_payload.get("body_markdown") or "") + "\n\n后续继续压残留。",
                }
            if instruction:
                return {
                    "title": "厨房里先亮的不是灯，是那条消息",
                    "body_markdown": (
                        "锅里余温还在，抽油烟机停了，厨房突然安静下来。\n\n"
                        "她把手机拿起来，又放下。\n\n"
                        "很多时候，人不是没话说，只是还没力气把那段解释再走一遍。"
                    ),
                }
            return {
                "title": "别把日子过反了",
                "body_markdown": (
                    "很多时候，人不是不想休息，而是不敢停下来。\n\n"
                    "不是工作本身，而是长期紧绷。\n\n"
                    "不是不累，而是一直往后放。\n\n"
                    "说到底，她只是把自己排到了最后。"
                ),
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_article_shell_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: True, raising=False)
    monkeypatch.setattr(workbench, "_preserves_structure_headings", lambda **_: True, raising=False)

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "candidate-retry-article",
            "source_kind": "manual",
            "source_name": "手动录入",
            "title": "别把日子过反了",
            "url": "https://example.com/candidate-retry",
            "author": "测试",
            "summary": "摘要",
            "body_markdown": "原文第一段\n\n原文第二段",
            "structure_notes": "",
            "tags": ["测试"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/candidate-retry-article/to-topic",
        json={
            "slug": "candidate-retry-topic",
            "title": "把最后那点力气留给自己",
            "angle": "情绪耗尽",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "candidate-retry-project", "title": "候选稿回炉测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/candidate-retry-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    adopt_response = client.post("/api/projects/candidate-retry-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200
    outline_response = client.post("/api/projects/candidate-retry-project/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/candidate-retry-project/generate-draft")
    assert draft_response.status_code == 201

    polish_calls = [
        call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) >= 2
    first_polish_payload = polish_calls[0][1]
    second_polish_payload = polish_calls[1][1]
    assert first_polish_payload["allow_structure_recomposition"] is True
    assert first_polish_payload["preserve_structure_anchors"] is False
    assert second_polish_payload["allow_structure_recomposition"] is True
    assert second_polish_payload["preserve_structure_anchors"] is False
    assert second_polish_payload["draft"]["title"] == "厨房里先亮的不是灯，是那条消息"
    assert "锅里余温还在" in str(second_polish_payload["draft"]["body_markdown"])


def test_article_shell_cleanup_triggers_for_time_chained_tracked_article_shell() -> None:
    source_markdown = (
        "# 别把日子过反了\n\n"
        "别用健康换明天\n\n"
        "朋友阿杰总说等忙完再休息。\n\n"
        "别等失去才懂珍惜\n\n"
        "外婆离世后，我翻遍手机。\n\n"
        "别把幸福寄托在等以后\n\n"
        "我们总习惯把想做的事往后推。"
    )
    candidate_markdown = (
        "电梯快到楼层，她对着镜面补了口红。手机震了下，屏幕顶端跳出一行字：体检改期成功。\n\n"
        "手指往上一划，门开了，外面已经有人在喊投屏连不上。那条短信很快被新的通知压下去。\n\n"
        "楼梯口那次也很直白。同事回头问她今天怎么这么慢，她笑了笑，只接了句昨晚没睡好。\n\n"
        "这种时候，人往往不会停，反而会往前补。咖啡换大杯，午休先撤掉，晚上回家再开电脑。\n\n"
        "饭局那回，声音更吵。她坐在靠外侧的位置，夹了口南瓜，就停那儿了。\n\n"
        "回家路上，朋友发来语音。她点开，听完，退出来。过两站，又点开一遍，还是没回。\n\n"
        "第三次提醒更碎，也更容易被她往后放。洗完澡出来，胸口发紧，她先把第二天的待办往下拉。\n\n"
        "给自己的解释倒是很顺：项目特殊，交付完再说，忙过这阵应该就好了。\n\n"
        "所以代价看起来并不响。工作群还在回，饭局也照常去，第二天甚至起得更早。\n\n"
        "夜里十一点多，手机又亮了，还是那个朋友：你最近还好吗？\n\n"
        "她把输入框点开，打了两个字，又删掉。"
    )

    assert workbench._should_retry_for_article_shell_cleanup(
        source_markdown=source_markdown,
        candidate_title="收件箱里那条改期短信，她一直没点开",
        candidate_markdown=candidate_markdown,
    )


def test_broad_happiness_release_auto_polish_stops_after_first_retry(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {
                "hook": "你以为自己是在等一个答案，其实是在把心力一直挂在得不到的地方。",
                "outline_body": "1. 先拆人为什么总把继续投入误认成更接近幸福\n2. 再写强求怎么一点点掏空自己\n3. 最后收回到已经拥有却被忽略的部分",
            }

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                return {
                    "title": "消息还没等来，你先把自己耗空了",
                    "body_markdown": (
                        "消息还是没回。聊天框停在昨天，对方那句晚点说后面再没下文。她一会儿看手机，一会儿看对话框，连回复草稿都改了三遍。\n\n"
                        "她以为再等一句解释，关系就会回温。可每次手机一亮，她先看是不是对方，不是，就继续把注意力挂在那条没回的消息上。\n\n"
                        "朋友问她要不要见面，她说改天。桌上的饭凉了，手机却一直握在手里。她不是不知道自己累，只是总想等那句回应。\n\n"
                        "真正拖住她的，不只是没回消息，而是那段关系迟迟没有交代。她怕自己先松手，就等于承认这段关系没有结果。\n\n"
                        "于是白天上班，夜里还是盯着聊天框。对方的冷淡、敷衍、回得慢，都被她翻来覆去地想。"
                    ),
                }
            return {
                "title": "幸福不是得到，是继续争取到最后",
                "body_markdown": (
                    "很多时候，我们以为幸福靠得到更多。\n\n"
                    "不是已经太累了，而是还不肯停。\n\n"
                    "说到底，人只是把不甘心误认成了更接近幸福。"
                ),
            }

    def keep_candidate(**kwargs):
        return kwargs["candidate_body_markdown"], kwargs["candidate_title"]

    def fake_evaluate_ai_flavor_risk(*, title: str, body_markdown: str):
        if "继续争取到最后" in title or "说到底" in body_markdown:
            return SimpleNamespace(
                score=64,
                level="高",
                hits=["命中：标题判断句模板", "命中：整篇解释壳偏密"],
                suggestions=["把抽象判断拆回具体人和具体代价。"],
            )
        return SimpleNamespace(score=18, level="低", hits=[], suggestions=[])

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "evaluate_ai_flavor_risk", fake_evaluate_ai_flavor_risk)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_structure_drift", keep_candidate, raising=False)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_over_smoothing", keep_candidate, raising=False)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_article_shell_cleanup", keep_candidate, raising=False)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_remaining_ai_flavor", keep_candidate, raising=False)
    monkeypatch.setattr(workbench, "_maybe_retry_polish_for_final_ai_flavor_cleanup", keep_candidate, raising=False)

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "happiness-broad-release-auto-polish-article",
            "source_kind": "manual",
            "source_name": "手动录入",
            "title": "幸福是什么",
            "url": "https://example.com/happiness-broad-release-auto-polish",
            "author": "测试",
            "summary": "文章把幸福的定义从不断获得转向适时放下，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。",
            "body_markdown": (
                "# 幸福是什么\n\n"
                "幸福是什么？我们总以为，幸福是得到。后来才懂，幸福其实也是放下。\n\n"
                "你有没有过这样的时刻？明明一段关系已经烂了，你还死死抓着不放；明明一个目标根本不合适你，你还拼命往前冲。\n\n"
                "我们都曾在强求里，耗尽了自己，以为努力争取，就能得到幸福。可真正的幸福，恰恰是该结束的时候，不再强求，该珍惜的时候，别无所求。\n\n"
                "别再盯着自己没有的东西了，转过头，看看你已经拥有的。你有健康的身体，爱你的家人，三两好友，一碗热饭。\n\n"
                "幸福从来不在别处，就在你放手后的轻松里，在你珍惜时的微笑里。"
            ),
            "structure_notes": "开头用幸福是得到还是放下的反差提问切入，中段拆强求的代价，结尾回到珍惜已经拥有的部分。",
            "tags": ["幸福认知", "停止强求", "珍惜当下"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/happiness-broad-release-auto-polish-article/to-topic",
        json={
            "slug": "happiness-broad-release-auto-polish-topic",
            "title": "你以为幸福是得到，后来才懂有些幸福叫放下",
            "angle": "从人为什么总把幸福误解成继续争取切入，写我们怎样在强求和不甘心里耗尽自己，又怎样在放手后重新看见已经拥有的部分。",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={
            "slug": "happiness-broad-release-auto-polish-project",
            "title": "幸福广义情绪文自动精修测试",
            "owner": "editorial",
        },
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/happiness-broad-release-auto-polish-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    adopt_response = client.post("/api/projects/happiness-broad-release-auto-polish-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200
    outline_response = client.post("/api/projects/happiness-broad-release-auto-polish-project/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/happiness-broad-release-auto-polish-project/generate-draft")
    assert draft_response.status_code == 201
    assert draft_response.json()["title"] == "消息还没等来，你先把自己耗空了"

    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    polish_calls = [call for call in draft_calls if call[1].get("polish_instruction")]
    assert len(draft_calls) == 2
    assert len(polish_calls) == 1
    assert polish_calls[0][1]["draft"]["title"] == "幸福不是得到，是继续争取到最后"


def test_article_shell_cleanup_triggers_for_high_paragraph_shell_burden_candidates() -> None:
    source_markdown = (
        "# 别把日子过反了\n\n"
        "别用健康换明天\n\n"
        "朋友阿杰总说等忙完再休息。\n\n"
        "别等失去才懂珍惜\n\n"
        "外婆离世后，我翻遍手机。\n\n"
        "别把幸福寄托在等以后\n\n"
        "我们总习惯把想做的事往后推。"
    )
    candidate_markdown = (
        "包带还挂在肩上，勒得锁骨发酸。她站在洗手台前，把牙膏挤到牙刷上，白色膏体歪歪地停在刷毛边缘，镜子里那张脸有点灰，耳边像还残留着消息提示音。\n\n"
        "水龙头没有开，手也没抬起来。就那么站了十几秒，脑子里先冒出来的是明天不能再这样了，可后面该怎么改、先处理哪件事，她一时全都接不上。\n\n"
        "白天就已经有痕迹了。回同事消息时，她把打好的那行字删掉重来，来回看两遍，还是觉得哪里不对，像脑子里总有一层雾压着。\n\n"
        "会议里有人问到她，她明明听见了，反应却慢半拍，先是心里空白，接着才仓促补上几句。等话说完，她自己也不知道刚才到底回了什么。\n\n"
        "午饭摆在工位边上，饭吃了大半，才发现自己没尝出味道，嘴里只有温热和咀嚼。叉子放下去的时候，她甚至想不起上一次认真吃完一顿饭是什么时候。\n\n"
        "还有些更小的地方，零碎得不值得专门拿出来说。电梯到了常去的楼层，她晚了半秒才迈腿；下楼取外卖，站在门口想了会儿，忘记自己拿没拿钥匙。\n\n"
        "朋友发来语音，她点开听完，没有不高兴，也没有想回，手机屏幕暗下去，她就让它那么躺着。消息并不凶，也没人催，她只是提不起那口气。\n\n"
        "那天开会前，同事问她要不要喝咖啡，她说，都行。中午订餐，别人问你吃什么，她还是那句，都行。晚上家里人发来消息，她盯着对话框看了会儿，回了句先这样吧。\n\n"
        "她也没请假，没哭，没跟谁吵起来。工作照常交，消息照常回，见到人也会笑，表面看不出什么大问题，连她自己都更容易把这些小卡顿压成一句最近状态不好。\n\n"
        "这句解释太顺手了，没睡好，过两天就好了；这阵子忙完，应该能缓过来；周末多睡会儿，别多想。她拿这些话安顿自己，也拿它们把那些更细的感觉挡回去。\n\n"
        "有时她也会察觉到不对。原来十分钟能做完的表格，现在坐了半小时还没进入状态；以前能接住的话题，现在听别人说话都觉得费劲。\n\n"
        "有人关心她一句你最近还好吗，她喉咙发紧，差点就想说实话了，到头来还是习惯性回挺好的。那几个字发出去的时候，她自己都觉得空。\n\n"
        "因为停下来很麻烦。工作会乱，别人会等，答应过的事要重新解释。更麻烦的是，她得承认自己已经不像平时那样利落、能扛、反应快了。\n\n"
        "她更容易用力把自己往正常里推。困了就灌咖啡，迟钝了就逼自己集中，想安静会儿又怕显得消极，脸上还得维持平常的表情和礼貌。\n\n"
        "这种消耗有点阴，它不壮烈，也不戏剧化，不会给你一个明确的瞬间，告诉你现在真的撑不住了。它更像很多后台程序一起开着，把力气一点点拖走。\n\n"
        "能让人往回退半步的，通常也不是什么大动作。可能只是某天通勤路上，她没有一上车就点开工作群，而是先把最近最明显的变化写进备忘录，免得又被自己糊弄过去。\n\n"
        "夜里那面镜子还在，灯光照下来，脸色还是疲惫的。她没有突然想通，也没有瞬间好起来，只是先把第二天最早的提醒关掉，承认自己确实已经撑了太久。"
    )

    assert workbench._article_shell_burden(candidate_markdown)[0] >= 12
    assert len(workbench._extract_non_heading_paragraphs(candidate_markdown)) > 14
    assert workbench._should_retry_for_article_shell_cleanup(
        source_markdown=source_markdown,
        candidate_title="她没有突然垮掉，只是把自己排到了最后",
        candidate_markdown=candidate_markdown,
    )


def test_article_shell_cleanup_triggers_for_low_risk_over_smoothed_tracked_article_candidate(
    monkeypatch,
) -> None:
    source_markdown = "# 不纠缠，是成年人最好的治愈\n\n原文是分段议论，不是单线成稿。"
    candidate_markdown = (
        "微波炉转到第二圈，玻璃门里那盒饭已经冒了白气，塑料盖微微鼓起。她站在厨房门口，包还挂在手肘上，拇指悬在聊天框上面。\n\n"
        "铃声停过三回，屋里更静了。等到那声提示音落下去，她还是没把饭拿出来。屏幕灭掉以后，黑色玻璃门里照出她半张脸，肩膀塌着，像人已经到家，脑子还卡在别处。\n\n"
        "下班后的十来分钟，本来该很快过去。换鞋，洗手，吃饭，回消息。以前这套顺序不需要想，手脚自己会接上。那天却卡在料理台边上，筷子压着盒盖，水杯放在旁边，包还靠着门，哪样都碰过，哪样都没往前走。\n\n"
        "她坐到沙发边，想先把饭吃完再回。屏幕一解锁，未读跳出来，脑子先空了几秒。也不是没话讲。卡住她的，是后面那截，要补一句为什么现在才回，要接住别人那点担心，光想到这儿，肩膀就往下沉。\n\n"
        "厨房和沙发隔着几步，她来回走了两趟，倒了水，喝了两口，又把杯子放回原位。饭明明就在微波炉里，胃里也空着，人却像忽然弄丢了最基本的次序感。\n\n"
        "苗头白天就有了。原定中午前交的表格，十一点二十临时改版；刚准备吃饭，工作群又跳出新的确认。手头的事被拦腰截断，后面的安排就一起往后滑。那顿午饭拖到两点多，盒子打开时米饭已经结块。\n\n"
        "这种积压当场看不出什么。午饭晚点吃，消息先放着，会议结束再处理，表面都还能撑住。可白天压下去的动作，到了晚上会一起回来。人坐进家里，脑子却还留在工位上，发热，转得慢，像用了很多年的旧风扇，叶片还在动，风已经很弱了。\n\n"
        "她先打出一句对不起，删掉。又换成我没事，就是事情有点多。停住。她盯着那几个字看了片刻，最后还是只发了句这两天有点慢。\n\n"
        "她看着那行字，没有松下来。饭那时已经凉了，盒盖上的白汽也散干净了。她后来回想，自己那晚先感到的与其说是烦，不如说是钝。像手机快没电时，屏幕还亮着，页面却总要隔半拍才动。\n\n"
        "关系往后缩，常常就是这么缩的。不是出了什么大事，也没有谁故意冷下来。人累到发钝时，最先被砍掉的，往往是解释成本高的部分。她没力气把这几天怎么过的从头讲完，也顾不上安顿对方那点担心，于是挑最快的话发出去。\n\n"
        "于是回消息越来越像搬重物。白天把吃饭和喘口气往后挪，到了晚上，连组织语言都费劲；回得慢，会生出愧疚，愧疚又把对话框压得更沉。前面少吃的那顿饭，后面没接住的话，慢慢缠到同一处去。\n\n"
        "她那晚一直站在微波炉旁边，第三次启动前，把在忙晚点回删掉，重新打了一句更认真的解释。发出去以后，厨房台面还是乱的，杯子没洗，包还斜靠在门边，饭也得重新热。她只是没再急着把自己拨回原来的样子。"
    )

    monkeypatch.setattr(
        workbench,
        "_looks_like_over_smoothed_tracked_article_candidate",
        lambda markdown: markdown == candidate_markdown,
    )

    assert workbench._should_retry_for_article_shell_cleanup(
        source_markdown=source_markdown,
        candidate_title="微波炉转到第二圈，她才发现自己整晚都没真正停下来",
        candidate_markdown=candidate_markdown,
    )


def test_article_shell_cleanup_skips_low_risk_high_paragraph_candidates_without_shell_signals() -> None:
    source_markdown = (
        "# 别把日子过反了\n\n"
        "别用健康换明天\n\n"
        "朋友阿杰总说等忙完再休息。\n\n"
        "别等失去才懂珍惜\n\n"
        "外婆离世后，我翻遍手机。\n\n"
        "别把幸福寄托在等以后\n\n"
        "我们总习惯把想做的事往后推。"
    )
    candidate_markdown = (
        "凌晨一点多，手机屏幕还亮着。最后一个工作群安静下来，家族群那条六十秒语音也听完了，朋友发来的“你睡了吗”被她回成“刚忙完”。她把输入框切到置顶的那个聊天框，停了几秒，打下：我最近有点撑不住。\n\n"
        "光标在句尾一闪一闪，像在催。手指悬在发送键上，肩膀先松了，整个人往床边陷。洗手台上还摆着没收的护肤品，头发扎了一整天，发根发紧。她原本想趁终于没人找的时候洗个头，或者把垃圾带下楼，结果只是背靠着衣柜门坐着，半天没动。\n\n"
        "外面的声响退下去以后，身体里的钝重才慢慢浮上来。白天像被推着往前走，回消息、接话、安抚、解释，做得太熟了，熟到很难立刻察觉自己已经空了。等轮到自己，话却卡在喉咙口，连发出去都嫌费劲。\n\n"
        "这种耗尽，未必会闹出很大的动静。更多时候，它只是把人往慢里拽。\n\n"
        "早上站在衣柜前，常穿的几套衣服都认得，还是会多站一会儿。电梯门合上，镜面里照出脸，她把视线移开，去盯跳动的楼层数字。到了公司，同事问要不要带咖啡，她照旧说好，声音听不出什么问题。\n\n"
        "午休时困得眼睛发涩，趴下也睡不着，手机拿起来就往下滑。视频一条条过去，内容没留下什么，手指倒一直在动。别人叫她名字，她还是会立刻应；轮到私人消息，常常只回“收到”“好”“晚点说”。\n\n"
        "原本顺手的事也开始停在半路。洗完澡，护发素搁在洗手台边，隔天才想起。外卖吃到一半凉在桌上。备忘录里记着体检、朋友那条拖了很久的长消息、要给自己换双舒服点的鞋，字都在，事情悬着，像总差最后那口气。\n\n"
        "她也会替自己找理由。最近太忙。睡够就能缓过来。等这阵子过去再说。表面上看，这些话并不离谱：工作没耽误，开会能接话，见人有礼貌，饭也按顿在吃。正因为日子还在照常往前，她更容易把那些发紧、发空、提不起劲，压成“先放放”。\n\n"
        "身体给提醒的时候，通常很轻。先是速度慢下来，接着话变短，耐心变薄，原来愿意伸出去的那部分热情也缩回去。她以为自己只是累，只是懒得动，直到连喜欢的人发来消息，她都要先把手机扣在桌上，缓几分钟，才有力气点开。\n\n"
        "她很会处理别人的情绪。工作上有误会，她习惯把话理顺，尽量别让场面僵住；朋友夜里发来长长的倾诉，她会认真看完，再慢慢回；家里有琐事，也总有人先来问她。哪怕只是回个表情，别人也知道，她在，她看见了。\n\n"
        "时间久了，周围的人会把这种在场当成默认设置。临时改方案先找她，家里有事先问她，朋友情绪下来了也先敲她。她未必没边界，只是先响应外面，已经成了反应。手机一震，她先低头；别人语气有点不对，她先想是不是自己哪里没顾到。\n\n"
        "于是白天她总在往外送：注意力送出去，耐心送出去，话送出去。到了夜里，屋子安静了，那些被她暂时压住的疲惫才回来。不是突然袭来的崩塌，更像水退下去，露出一直在那里的沙地。\n\n"
        "她对别人其实很敏感。谁情绪不对，谁说话变快了，谁沉默得反常，她常常看得出来。轮到自己，却总要拖到深夜，拖到四周都安静，才勉强听见心里那句很轻的话：我好像不太行了。\n\n"
        "听见了，也不等于马上停下。第二天还是照常起床，照常打卡，照常把语气放软，照常说“没事”。她熟悉的是继续运转，不太熟悉承认自己已经掉电。那个念头总被往后挪：等忙完，等周末，等别人先稳定下来。挪到最后，留给自己的，只剩这点夜深人静的空。\n\n"
        "可人在这个时段往往已经见底了。脑子钝，心口也闷，连难过都没什么声响。聊天框开着，想说的话在里面转了几圈，还是删掉。她不是想隐瞒，只是那时候连解释自己怎么了，都显得太耗神。\n\n"
        "有些累，就长在这些看上去还算体面的日常里。你照样把事情做完，照样回复消息，照样跟人说笑，甚至照样关心别人。只是回到自己这里，像一扇门慢慢合上了。外面的人未必看得见，她自己也常常要过很久才反应过来。\n\n"
        "后来有个夜里，她没再逼着自己把空白填满。聊天框关掉，屏幕暗下去。她去厨房倒了半杯温水，站着喝完，没有顺手去看新的红点。回到床边，还是没立刻想通什么，屋里也没突然变得轻松。\n\n"
        "她只是把第二天答应下来的安排往后挪了挪，又给常联系的人发了句：这两天我回得会慢些。\n\n"
        "做完这些，生活并没有马上整齐起来。房间还是那间房，洗手台上的瓶瓶罐罐还在，明早该响的闹钟也不会放过她。只是那天晚上，她没有再把自己塞回“正常”里。头发解开后落下来，勒了一整天的发根终于松开，她也跟着安静了些。"
    )

    assert len(workbench._extract_non_heading_paragraphs(candidate_markdown)) > 14
    assert not workbench.extract_bridging_summary_paragraphs(candidate_markdown)
    assert not workbench.extract_embedded_banner_paragraphs(candidate_markdown)
    assert not workbench.extract_generic_reflective_openers(candidate_markdown)
    assert workbench._count_time_chain_leads(candidate_markdown) < 4
    assert workbench._article_shell_burden(candidate_markdown)[0] >= 12
    assert not workbench._should_retry_for_article_shell_cleanup(
        source_markdown=source_markdown,
        candidate_title="总在处理别人的消息，轮到自己时只剩深夜那一点空",
        candidate_markdown=candidate_markdown,
    )


def test_tracked_article_low_ai_flavor_still_runs_article_shell_cleanup(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if "不要把多个现实接口顺着时间缝成一个人从早到晚一路推进的完整日程线" in instruction:
                return {
                    "title": "她把提醒划走了三次",
                    "body_markdown": (
                        "她把预约提醒划掉时，咖啡刚接满。\n\n"
                        "消息没有回，体检也没改回去。\n\n"
                        "晚上回家，她站在门口，先把包放在地上。"
                    ),
                }
            if instruction:
                return {
                    "title": "收件箱里那条改期短信，她一直没点开",
                    "body_markdown": (
                        "电梯快到楼层，她对着镜面补了口红。手机震了下，屏幕顶端跳出一行字：体检改期成功。\n\n"
                        "手指往上一划，门开了，外面已经有人在喊投屏连不上。那条短信很快被新的通知压下去。\n\n"
                        "楼梯口那次也很直白。同事回头问她今天怎么这么慢，她笑了笑，只接了句昨晚没睡好。\n\n"
                        "这种时候，人往往不会停，反而会往前补。咖啡换大杯，午休先撤掉，晚上回家再开电脑。\n\n"
                        "饭局那回，声音更吵。她坐在靠外侧的位置，夹了口南瓜，就停那儿了。\n\n"
                        "回家路上，朋友发来语音。她点开，听完，退出来。过两站，又点开一遍，还是没回。\n\n"
                        "第三次提醒更碎，也更容易被她往后放。洗完澡出来，胸口发紧，她先把第二天的待办往下拉。\n\n"
                        "给自己的解释倒是很顺：项目特殊，交付完再说，忙过这阵应该就好了。\n\n"
                        "所以代价看起来并不响。工作群还在回，饭局也照常去，第二天甚至起得更早。\n\n"
                        "夜里十一点多，手机又亮了，还是那个朋友：你最近还好吗？\n\n"
                        "她把输入框点开，打了两个字，又删掉。"
                    ),
                }
            return {
                "title": "别把日子过反了",
                "body_markdown": (
                    "很多时候，人不是不想停下来，而是不敢承认自己已经撑不住了。\n\n"
                    "不是工作本身，而是那种一直把自己往后排的习惯。\n\n"
                    "不是身体突然垮掉，而是很多提醒都被她顺手划过去了。\n\n"
                    "说到底，她只是又一次把自己放到了最后。"
                ),
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_preserves_structure_headings", lambda **_: True, raising=False)

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "article-shell-low-score-article",
            "source_kind": "manual",
            "source_name": "手动录入",
            "title": "别把日子过反了",
            "url": "https://example.com/article-shell-low-score",
            "author": "测试",
            "summary": "摘要",
            "body_markdown": (
                "# 别把日子过反了\n\n"
                "别用健康换明天\n\n"
                "朋友阿杰总说等忙完再休息。\n\n"
                "别等失去才懂珍惜\n\n"
                "外婆离世后，我翻遍手机。\n\n"
                "别把幸福寄托在等以后\n\n"
                "我们总习惯把想做的事往后推。"
            ),
            "structure_notes": "",
            "tags": ["测试"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/article-shell-low-score-article/to-topic",
        json={
            "slug": "article-shell-low-score-topic",
            "title": "她总说等忙完这一阵",
            "angle": "身体提醒被往后推",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "article-shell-low-score-project", "title": "文章壳回炉测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/article-shell-low-score-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    adopt_response = client.post("/api/projects/article-shell-low-score-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200
    outline_response = client.post("/api/projects/article-shell-low-score-project/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/article-shell-low-score-project/generate-draft")
    assert draft_response.status_code == 201

    polish_calls = [
        call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) >= 2
    first_polish_payload = polish_calls[0][1]
    second_polish_payload = polish_calls[1][1]
    assert first_polish_payload["draft"]["title"] == "别把日子过反了"
    assert second_polish_payload["draft"]["title"] == "收件箱里那条改期短信，她一直没点开"
    assert second_polish_payload["allow_structure_recomposition"] is True
    assert second_polish_payload["preserve_structure_anchors"] is False
    assert "不要把多个现实接口顺着时间缝成一个人从早到晚一路推进的完整日程线" in str(
        second_polish_payload["polish_instruction"]
    )


def test_tracked_article_shell_like_draft_enters_auto_polish_with_shell_instruction(monkeypatch) -> None:
    shell_like_draft = (
        "电梯快到楼层，她对着镜面补了口红。手机震了下，屏幕顶端跳出一行字：体检改期成功。\n\n"
        "手指往上一划，门开了，外面已经有人在喊投屏连不上。那条短信很快被新的通知压下去，和群消息、日程提醒叠在一起。\n\n"
        "楼梯口那次也很直白。同事走了两级，回头看见她扶着栏杆，问今天怎么这么慢。她笑了笑，只接了句，昨晚没睡好。\n\n"
        "这种时候，人往往不会停，反而会往前补。咖啡换大杯，午休先撤掉，晚上回家再开电脑，把白天掉下去的进度补回来。\n\n"
        "饭局那回，声音更吵。杯子碰杯子，勺子刮盘子，过道上来回有人走。她坐在靠外侧的位置，菜转到面前，夹了口南瓜，就停那儿了。\n\n"
        "回家路上，朋友发来语音。她点开，听完，退出来。过两站，又点开一遍，还是没回。\n\n"
        "第三次提醒更碎，也更容易被她往后放。洗完澡出来，胸口发紧，像内衣肩带勒久了，摘掉以后那道印子还留着。\n\n"
        "给自己的解释倒是很顺：项目特殊，交付完再说，忙过这阵应该就好了。\n\n"
        "所以代价看起来并不响。工作群还在回，饭局也照常去，第二天甚至起得更早。\n\n"
        "夜里十一点多，洗完澡的发尾还在滴水，睡衣领口湿了一小片。手机又亮了，还是那个朋友：你最近还好吗？\n\n"
        "她把输入框点开，打了两个字，又删掉。屏幕白着，下面压着那条复诊改期的确认短信。"
    )
    assert workbench.evaluate_ai_flavor_risk(
        title="收件箱里那条改期短信，她一直没点开",
        body_markdown=shell_like_draft,
    ).level == "中"

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if "不要把多个现实接口顺着时间缝成一个人从早到晚一路推进的完整日程线" in instruction:
                return {
                    "title": "她把提醒划走了三次",
                    "body_markdown": (
                        "她把预约提醒划掉时，咖啡刚接满。\n\n"
                        "消息没有回，体检也没改回去。\n\n"
                        "屏幕暗下去以后，她站在门口，没有立刻进屋。"
                    ),
                }
            return {
                "title": "收件箱里那条改期短信，她一直没点开",
                "body_markdown": shell_like_draft,
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_preserves_structure_headings", lambda **_: True, raising=False)

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "article-shell-entry-article",
            "source_kind": "manual",
            "source_name": "手动录入",
            "title": "别把日子过反了",
            "url": "https://example.com/article-shell-entry",
            "author": "测试",
            "summary": "摘要",
            "body_markdown": (
                "# 别把日子过反了\n\n"
                "别用健康换明天\n\n"
                "朋友阿杰总说等忙完再休息。\n\n"
                "别等失去才懂珍惜\n\n"
                "外婆离世后，我翻遍手机。\n\n"
                "别把幸福寄托在等以后\n\n"
                "我们总习惯把想做的事往后推。"
            ),
            "structure_notes": "",
            "tags": ["测试"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/article-shell-entry-article/to-topic",
        json={
            "slug": "article-shell-entry-topic",
            "title": "她总说等忙完这一阵",
            "angle": "身体提醒被往后推",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "article-shell-entry-project", "title": "入口壳层回炉测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/article-shell-entry-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    adopt_response = client.post("/api/projects/article-shell-entry-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200
    outline_response = client.post("/api/projects/article-shell-entry-project/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/article-shell-entry-project/generate-draft")
    assert draft_response.status_code == 201

    polish_calls = [
        call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) >= 1
    assert "不要把多个现实接口顺着时间缝成一个人从早到晚一路推进的完整日程线" in str(
        polish_calls[0][1]["polish_instruction"]
    )
    assert polish_calls[0][1]["allow_structure_recomposition"] is True
    assert polish_calls[0][1]["preserve_structure_anchors"] is False


def test_tracked_article_initial_shell_instruction_uses_reference_article_anchors(monkeypatch) -> None:
    shell_like_draft = (
        "电梯快到楼层，她对着镜面补了口红。手机震了下，屏幕顶端跳出一行字：体检改期成功。\n\n"
        "手指往上一划，门开了，外面已经有人在喊投屏连不上。那条短信很快被新的通知压下去。\n\n"
        "楼梯口那次也很直白。同事回头问她今天怎么这么慢，她笑了笑，只接了句昨晚没睡好。\n\n"
        "这种时候，人往往不会停，反而会往前补。咖啡换大杯，午休先撤掉，晚上回家再开电脑。\n\n"
        "饭局那回，声音更吵。她坐在靠外侧的位置，夹了口南瓜，就停那儿了。\n\n"
        "回家路上，朋友发来语音。她点开，听完，退出来。过两站，又点开一遍，还是没回。\n\n"
        "第三次提醒更碎，也更容易被她往后放。洗完澡出来，胸口发紧，她先把第二天的待办往下拉。\n\n"
        "给自己的解释倒是很顺：项目特殊，交付完再说，忙过这阵应该就好了。\n\n"
        "所以代价看起来并不响。工作群还在回，饭局也照常去，第二天甚至起得更早。\n\n"
        "夜里十一点多，手机又亮了，还是那个朋友：你最近还好吗？\n\n"
        "她把输入框点开，打了两个字，又删掉。"
    )

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            instruction = str(payload.get("polish_instruction") or "")
            if "不要把多个现实接口顺着时间缝成一个人从早到晚一路推进的完整日程线" in instruction:
                return {
                    "title": "她把提醒划走了三次",
                    "body_markdown": (
                        "她把预约提醒划掉时，咖啡刚接满。\n\n"
                        "消息没有回，体检也没改回去。\n\n"
                        "晚上回家，她站在门口，先把包放在地上。"
                    ),
                }
            return {
                "title": "收件箱里那条改期短信，她一直没点开",
                "body_markdown": shell_like_draft,
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_preserves_structure_headings", lambda **_: True, raising=False)

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "article-shell-anchor-article",
            "source_kind": "manual",
            "source_name": "手动录入",
            "title": "别把日子过反了",
            "url": "https://example.com/article-shell-anchor",
            "author": "测试",
            "summary": "摘要",
            "body_markdown": (
                "# 别把日子过反了\n\n"
                "别用健康换明天\n\n"
                "朋友阿杰总说等忙完再休息。\n\n"
                "别等失去才懂珍惜\n\n"
                "外婆离世后，我翻遍手机。\n\n"
                "别把幸福寄托在等以后\n\n"
                "我们总习惯把想做的事往后推。"
            ),
            "structure_notes": "",
            "tags": ["测试"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/article-shell-anchor-article/to-topic",
        json={
            "slug": "article-shell-anchor-topic",
            "title": "她总说等忙完这一阵",
            "angle": "身体提醒被往后推",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "article-shell-anchor-project", "title": "壳层锚点测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/article-shell-anchor-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    adopt_response = client.post("/api/projects/article-shell-anchor-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200
    outline_response = client.post("/api/projects/article-shell-anchor-project/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/article-shell-anchor-project/generate-draft")
    assert draft_response.status_code == 201

    polish_calls = [
        call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")
    ]
    assert len(polish_calls) >= 1
    instruction = str(polish_calls[0][1]["polish_instruction"])
    assert "别用健康换明天 -> 朋友阿杰总说等忙完再休息" in instruction
    assert "别等失去才懂珍惜 -> 外婆离世后，我翻遍手机" in instruction


def test_tracked_article_finalize_collapses_time_chain_shell_when_model_stalls(monkeypatch) -> None:
    shell_like_draft = (
        "电梯快到楼层，她对着镜面补了口红。手机震了下，屏幕顶端跳出一行字：体检改期成功。\n\n"
        "手指往上一划，门开了，外面已经有人在喊投屏连不上。高跟鞋踩在地砖上，声响空空的。那条短信很快被新的通知压下去，和群消息、日程提醒叠在一起。\n\n"
        "楼梯口那次也很直白。同事走了两级，回头看见她扶着栏杆，问今天怎么这么慢。她笑了笑，只接了句，昨晚没睡好。中午群里催文件，光标在对话框里闪了很久，最后发出去的还是“收到”。她不是想省字，当时先冒出来的感觉是钝，像脑子外面糊着层湿布，句子要往外拽，半天也拽不整齐。\n\n"
        "这种时候，人往往不会停，反而会往前补。咖啡换大杯，午休先撤掉，晚上回家再开电脑，把白天掉下去的进度补回来。她也这么做。因为一旦慢下来，麻烦立刻就有了形：请假要重排，答应过的事得往后挪，还要自己开口承认，这会儿确实撑不太住。\n\n"
        "于是“最近有点累”成了最顺手的说法。轻，薄，像拿手掌把桌上的纸压平，底下那层褶还在。\n\n"
        "饭局那回，声音更吵。杯子碰杯子，勺子刮盘子，过道上来回有人走。她坐在靠外侧的位置，菜转到面前，夹了口南瓜，就停那儿了。朋友问项目是不是很麻烦，她点头，没接下去。等旁边的人聊到周末去哪儿，她还低头看着碗里那块凉掉的南瓜。\n\n"
        "回家路上，朋友发来语音。她点开，听完，退出来。过两站，又点开一遍，还是没回。后来屏幕上跳出一句：你最近是不是有点怪。\n\n"
        "她按灭了手机。\n\n"
        "安静落在别人耳朵里，很容易被听成冷淡。可她那会儿更像是空了。回应别人要组织词，接住情绪也要力气，连“我最近不太好”这几个字，都显得重。前面那次没说，后面就更难说；消息拖着拖着，误会也会跟着长出来。人际上的消耗，常常不是争吵出来的，很多时候是回复框亮着，你看着它，身体先往后缩了半步。\n\n"
        "第三次提醒更碎，也更容易被她往后放。洗完澡出来，胸口发紧，像内衣肩带勒久了，摘掉以后那道印子还留着。她坐到床边，头发没吹干，先把第二天的待办往下拉，又把闹钟从7点10分改到6点40分。周末本来约了散步，临出门前又把电脑掀开，说先改完这版。收件箱里那条复诊改期短信一直躺着，没删，也没点。\n\n"
        "给自己的解释倒是很顺：项目特殊，交付完再说，忙过这阵应该就好了。可人一旦急着把自己拨回“正常”，最先被压下去的，偏偏就是这些已经冒头的信号。楼梯走慢了，她往睡眠上归；不想回话，她往情绪上轻轻带过去；胸口发紧，就先改闹钟，先开电脑。每次都像只推迟了一小会儿，后面却要用更多力气去装作没有那回事。\n\n"
        "所以代价看起来并不响。工作群还在回，饭局也照常去，第二天甚至起得更早。表面没断，里面已经开始掉速。最磨人的地方就在这儿：她不是突然垮掉的，是在一次次“先把眼前做完”里，慢慢变钝，慢慢变沉，连察觉自己不对劲都比从前晚了半拍。\n\n"
        "夜里十一点多，洗完澡的发尾还在滴水，睡衣领口湿了一小片。手机又亮了，还是那个朋友：你最近还好吗？\n\n"
        "她把输入框点开，打了两个字，又删掉。屏幕白着，下面压着那条复诊改期的确认短信。"
    )

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {
                "title": "收件箱里那条改期短信，她一直没点开",
                "body_markdown": shell_like_draft,
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_preserves_structure_headings", lambda **_: True, raising=False)

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "article-shell-fallback-article",
            "source_kind": "manual",
            "source_name": "手动录入",
            "title": "别把日子过反了",
            "url": "https://example.com/article-shell-fallback",
            "author": "测试",
            "summary": "摘要",
            "body_markdown": (
                "# 别把日子过反了\n\n"
                "别用健康换明天\n\n"
                "朋友阿杰总说等忙完再休息。\n\n"
                "别等失去才懂珍惜\n\n"
                "外婆离世后，我翻遍手机。\n\n"
                "别把幸福寄托在等以后\n\n"
                "我们总习惯把想做的事往后推。"
            ),
            "structure_notes": "",
            "tags": ["测试"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/article-shell-fallback-article/to-topic",
        json={
            "slug": "article-shell-fallback-topic",
            "title": "她总说等忙完这一阵",
            "angle": "身体提醒被往后推",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "article-shell-fallback-project", "title": "壳层兜底测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/article-shell-fallback-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    adopt_response = client.post("/api/projects/article-shell-fallback-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200
    outline_response = client.post("/api/projects/article-shell-fallback-project/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/article-shell-fallback-project/generate-draft")
    assert draft_response.status_code == 201

    result = draft_response.json()
    assert result["body_markdown"] != shell_like_draft
    assert workbench._article_shell_burden(result["body_markdown"]) < workbench._article_shell_burden(shell_like_draft)
    assert (
        workbench.evaluate_ai_flavor_risk(
            title=result["title"],
            body_markdown=result["body_markdown"],
        ).score
        < workbench.evaluate_ai_flavor_risk(
            title="收件箱里那条改期短信，她一直没点开",
            body_markdown=shell_like_draft,
        ).score
    )


def test_tracked_article_finalize_collapses_embedded_banner_shell_when_model_stalls(monkeypatch) -> None:
    shell_like_draft = (
        "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣。\n\n"
        "杯壁外侧已经结了一层薄薄的水，电脑右下角跳到 21:47，文档还开着，光标一闪一闪。那条消息很短：最近怎么样，要不要找天见一面？\n\n"
        "人很多时候就是从这里开始慢下来的。没出什么大事，也谈不上垮。只是闹钟响了，按掉，再按掉；明明只差十分钟就能从容出门，还是在床边坐了很久。\n\n"
        "麻烦就麻烦在，这些信号太容易被她自己轻轻带过去。醒来更累，胃口乱，下午三四点会突然心慌；消息提示音一密集，太阳穴就跟着发紧。可熟悉的话也会立刻跟上来：忙完这阵就好了，周末补个觉就好了。\n\n"
        "身体先亮红灯，人却还照着原来的效率和礼貌往前走。该交的照交，该回的照回，见了人也还能笑，说自己没事。\n\n"
        "她还没倒下。还能上班，能交差，能在别人问起时回一句“挺好的”。偏偏就是这种“还能”，最容易让人误判。\n\n"
        "关系里的缺席，也是在这些时候一点点长出来的。见面改成改天，电话换成文字，长回复缩成表情，解释缩成“最近有点忙”。\n\n"
        "这句话很体谅，可听久了，人会更沉。因为她慢慢也默认了自己总在往后退。生活里有变化，不太主动讲了；受了委屈，也觉得讲起来太费劲。\n\n"
        "难的地方就在这儿。不是因为太久没见，也不全是因为之前推掉太多次。更常见的情况是，人已经在长时间硬撑里，跟自己的感受脱了节。\n\n"
        "回家的路上，手机又亮了一次。她站在电梯里，看着镜子里自己有点发白的脸，拇指在屏幕上停了停，没有再逼自己把所有消息都回完。"
    )

    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b\n3. c"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            return {
                "title": "朋友的消息弹出来时，她正对着桌上那杯咖啡发愣",
                "body_markdown": shell_like_draft,
            }

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_over_smoothing", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_remaining_ai_flavor", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_should_retry_for_final_ai_flavor_cleanup", lambda **_: False, raising=False)
    monkeypatch.setattr(workbench, "_preserves_structure_headings", lambda **_: True, raising=False)

    create_article = client.post(
        "/api/tracked-articles",
        json={
            "slug": "article-banner-fallback-article",
            "source_kind": "manual",
            "source_name": "手动录入",
            "title": "别把日子过反了",
            "url": "https://example.com/article-banner-fallback",
            "author": "测试",
            "summary": "摘要",
            "body_markdown": (
                "# 别把日子过反了\n\n"
                "别用健康换明天\n\n"
                "朋友阿杰总说等忙完再休息。\n\n"
                "别等失去才懂珍惜\n\n"
                "外婆离世后，我翻遍手机。"
            ),
            "structure_notes": "",
            "tags": ["测试"],
        },
    )
    assert create_article.status_code == 201

    create_topic = client.post(
        "/api/tracked-articles/article-banner-fallback-article/to-topic",
        json={
            "slug": "article-banner-fallback-topic",
            "title": "她总说等忙完这一阵",
            "angle": "关系里的缺席是怎么慢慢长出来的",
        },
    )
    assert create_topic.status_code == 201
    topic_slug = create_topic.json()["slug"]

    create_project = client.post(
        f"/api/topics/{topic_slug}/create-project",
        json={"slug": "article-banner-fallback-project", "title": "锚句壳层兜底测试", "owner": "editorial"},
    )
    assert create_project.status_code == 201

    strategy_response = client.post("/api/projects/article-banner-fallback-project/generate-strategy-package")
    assert strategy_response.status_code == 201
    adopt_response = client.post("/api/projects/article-banner-fallback-project/adopt-strategy-card/1")
    assert adopt_response.status_code == 200
    outline_response = client.post("/api/projects/article-banner-fallback-project/generate-outline")
    assert outline_response.status_code == 201

    draft_response = client.post("/api/projects/article-banner-fallback-project/generate-draft")
    assert draft_response.status_code == 201

    result = draft_response.json()
    assert result["body_markdown"] != shell_like_draft
    assert not workbench.extract_embedded_banner_paragraphs(result["body_markdown"])
    assert (
        workbench.evaluate_ai_flavor_risk(
            title=result["title"],
            body_markdown=result["body_markdown"],
        ).score
        < workbench.evaluate_ai_flavor_risk(
            title="朋友的消息弹出来时，她正对着桌上那杯咖啡发愣",
            body_markdown=shell_like_draft,
        ).score
    )
    assert "人很多时候就是从这里开始慢下来的，没出什么大事，也谈不上垮。" in result["body_markdown"]


def test_article_shell_retry_instruction_calls_out_single_dayline_stitching() -> None:
    instruction = workbench._build_article_shell_retry_instruction(
        base_instruction="请基于现有正文做一轮原创增强精修。",
        source_markdown=(
            "# 别把日子过反了\n\n"
            "别用健康换明天\n\n"
            "朋友阿杰总说等忙完再休息。\n\n"
            "别等失去才懂珍惜\n\n"
            "外婆离世后，我翻遍手机。"
        ),
        candidate_markdown=(
            "电梯快到楼层，她对着镜面补了口红。\n\n"
            "楼梯口那次也很直白。\n\n"
            "中午群里催文件，光标在对话框里闪了很久。\n\n"
            "饭局那回，声音更吵。\n\n"
            "回家路上，朋友发来语音。\n\n"
            "洗完澡出来，胸口发紧。\n\n"
            "夜里十一点多，手机又亮了。"
        ),
    )

    assert "不要把多个现实接口顺着时间缝成一个人从早到晚一路推进的完整日程线" in instruction
    assert "不要让电梯、楼梯、午休、饭局、回家、洗澡、深夜这些节点按时间表整齐排队" in instruction


def test_generate_assets_can_polish_draft_before_generating_assets(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                return {"title": "draft title polished", "body_markdown": "# polished\n\nbody polished"}
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

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")

    assets_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/generate-assets",
        json={
            "polish_before_generate": True,
            "polish_instruction": "重写开头和结尾，减少重复解释感，更像真实公众号作者。",
        },
    )
    assert assets_response.status_code == 201
    assets = assets_response.json()
    assert assets["draft_version"] == 2

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["draft"]["version"] == 2
    assert detail["draft"]["title"] == "draft title polished"
    assert detail["assets"]["draft_version"] == 2
    assert detail["project"]["stage"] == "assets_ready"
    assert detail["project"]["next_required_step"] == "build_publish_package"

    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    assert len(draft_calls) == 2
    assert draft_calls[1][1]["polish_instruction"] == "重写开头和结尾，减少重复解释感，更像真实公众号作者。"

    assets_call = next(call for call in fake_generator.calls if call[0] == "assets")
    assert assets_call[1]["draft"]["title"] == "draft title polished"


def test_generate_assets_can_fall_back_to_default_polish_instruction_before_generating_assets(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            if payload.get("polish_instruction"):
                return {"title": "draft title polished", "body_markdown": "# polished\n\nbody polished"}
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

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    profiles = client.get("/api/tone-profiles").json()
    profile_id = profiles[0]["id"]
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
            "default_polish_instruction": "重写开头和结尾，压掉模板感，更像真实公众号作者在写。",
        },
    )
    assert update_response.status_code == 200

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")

    assets_response = client.post(
        "/api/projects/office-burnout-recovery-weekly/generate-assets",
        json={
            "polish_before_generate": True,
            "polish_instruction": "   ",
        },
    )
    assert assets_response.status_code == 201

    polished_call = next(call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction"))
    assert polished_call[1]["polish_instruction"] == "重写开头和结尾，压掉模板感，更像真实公众号作者在写。"


def test_generate_draft_auto_compresses_when_far_above_target_word_count(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []
            self.draft_calls = 0

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("draft", payload))
            self.draft_calls += 1
            if self.draft_calls == 1:
                return {"title": "draft title long", "body_markdown": "很长" * 1200}
            return {"title": "draft title compressed", "body_markdown": "精简后正文" * 120}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")

    draft_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    assert draft_response.status_code == 201
    payload = draft_response.json()
    assert payload["title"] == "draft title compressed"
    assert payload["word_count"] == len("精简后正文" * 120)

    draft_calls = [call for call in fake_generator.calls if call[0] == "draft"]
    assert len(draft_calls) == 2
    assert draft_calls[0][1]["polish_instruction"] is None
    assert draft_calls[1][1]["polish_instruction"] == "请在不改变核心观点和结构顺序的前提下，压缩这篇草稿，删除重复表达与重复场景，把正文控制回目标字数附近。"
    assert draft_calls[1][1]["draft"]["title"] == "draft title long"


def test_maybe_compress_draft_output_falls_back_to_original_when_compression_fails(caplog) -> None:
    class FailingGenerator:
        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            raise RuntimeError("OpenAI chat fallback returned no output")

    class ToneProfileStub:
        target_word_count = 100

        @staticmethod
        def model_dump() -> dict[str, object]:
            return {"target_word_count": 100}

    caplog.set_level("WARNING")

    original_body = "很长" * 200
    original_title = "原始标题"
    compressed_body, compressed_title = workbench._maybe_compress_draft_output(
        project_slug="compression-fallback-demo",
        tone_profile=ToneProfileStub(),
        title=original_title,
        body_markdown=original_body,
        project={
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "总把自己往后放的人，生活为什么会慢慢失序",
            "topic_angle": "从推迟和顺延的日常动作切入，解释生活排序为什么会慢慢倒过来。",
            "title": "压缩失败兜底稿",
            "domain_pack_key": None,
        },
        outline_row={"hook": "hook", "outline_body": "1. a\n2. b"},
        review_comment=None,
        reference_article_payload={},
        generator=FailingGenerator(),
    )

    assert compressed_body == original_body
    assert compressed_title == original_title
    assert "Draft compression failed for project compression-fallback-demo" in caplog.text


def test_topics_and_projects_list_reflect_stateful_changes() -> None:
    client.post(
        "/api/trends/office-burnout-recovery/to-topic",
        json={
            "slug": "office-burnout-recovery-checklist",
            "title": "办公室倦怠后的恢复清单",
            "angle": "恢复节奏",
        },
    )
    client.post(
        "/api/topics/relationship-boundary-reset-playbook/create-project",
        json={
            "slug": "relationship-boundary-reset-delivery",
            "title": "关系边界重设交付稿",
            "owner": "editorial",
        },
    )
    client.patch(
        "/api/projects/relationship-boundary-reset-delivery",
        json={"stage": "draft_ready"},
    )

    topics_response = client.get("/api/topics")
    assert topics_response.status_code == 200
    topics = topics_response.json()
    assert len(topics) == 4
    assert topics[0]["status"] == "pending"

    projects_response = client.get("/api/projects")
    assert projects_response.status_code == 200
    projects = projects_response.json()
    assert len(projects) == 4
    assert projects[0]["slug"] == "relationship-boundary-reset-delivery"
    assert projects[0]["stage"] == "draft_ready"


def test_trends_and_topics_support_updates_and_recent_tasks_capture_status_flow() -> None:
    trend_update_response = client.patch(
        "/api/trends/office-burnout-recovery",
        json={
            "title": "办公室情绪恢复观察",
            "heat_score": 95,
            "status": "selected",
        },
    )
    assert trend_update_response.status_code == 200
    updated_trend = trend_update_response.json()
    assert updated_trend["title"] == "办公室情绪恢复观察"
    assert updated_trend["heat_score"] == 95
    assert updated_trend["status"] == "selected"

    topic_update_response = client.patch(
        "/api/topics/relationship-boundary-reset-playbook",
        json={
            "title": "关系边界重设实战清单",
            "angle": "边界表达",
            "status": "approved",
        },
    )
    assert topic_update_response.status_code == 200
    updated_topic = topic_update_response.json()
    assert updated_topic["title"] == "关系边界重设实战清单"
    assert updated_topic["angle"] == "边界表达"
    assert updated_topic["status"] == "approved"

    trends_response = client.get("/api/trends")
    assert trends_response.status_code == 200
    trends = trends_response.json()
    office_trend = next(trend for trend in trends if trend["slug"] == "office-burnout-recovery")
    assert office_trend["title"] == "办公室情绪恢复观察"
    assert office_trend["status"] == "selected"

    topics_response = client.get("/api/topics")
    assert topics_response.status_code == 200
    topics = topics_response.json()
    boundary_topic = next(topic for topic in topics if topic["slug"] == "relationship-boundary-reset-playbook")
    assert boundary_topic["title"] == "关系边界重设实战清单"
    assert boundary_topic["status"] == "approved"

    dashboard_response = client.get("/api/dashboard/summary")
    assert dashboard_response.status_code == 200
    dashboard = dashboard_response.json()
    assert dashboard["pending_topics"] == 1
    assert [task["task_type"] for task in dashboard["recent_tasks"]] == [
        "topic_updated",
        "trend_updated",
    ]
    assert dashboard["recent_tasks"][0]["entity_slug"] == "relationship-boundary-reset-playbook"
    assert dashboard["recent_tasks"][1]["entity_slug"] == "office-burnout-recovery"


def test_projects_list_exposes_visible_chain_state_after_restore(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.outline_calls = 0

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            self.outline_calls += 1
            if self.outline_calls == 1:
                return {"hook": "hook v1", "outline_body": "1. a\n2. b"}
            return {"hook": "hook v2", "outline_body": "1. c\n2. d"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            if payload["outline"]["hook"] == "hook v2":
                return {"title": "draft title v2", "body_markdown": "# draft v2\n\nbody"}
            return {"title": "draft title v1", "body_markdown": "# draft v1\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            if payload["draft"]["title"] == "draft title v2":
                return {
                    "title_options": ["title v2"],
                    "cover_prompt": "prompt v2",
                    "cover_copy": "cover copy v2",
                    "social_teaser": "teaser v2",
                }
            return {
                "title_options": ["title v1"],
                "cover_prompt": "prompt v1",
                "cover_copy": "cover copy v1",
                "social_teaser": "teaser v1",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            if payload["assets"]["cover_copy"] == "cover copy v2":
                return {"abstract": "abstract v2", "tags": ["tag-v2"], "editor_note": "note v2"}
            return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    initial_projects = client.get("/api/projects")
    assert initial_projects.status_code == 200
    initial_office_project = next(
        project
        for project in initial_projects.json()
        if project["slug"] == "office-burnout-recovery-weekly"
    )
    assert initial_office_project["stage"] == "draft_ready"
    assert initial_office_project["chain_status"] == "missing"
    assert initial_office_project["current_chain_state"] == "missing_outline"
    assert initial_office_project["next_required_step"] == "generate_outline"
    assert initial_office_project["current_outline_version"] is None
    assert initial_office_project["current_draft_version"] is None
    assert initial_office_project["current_assets_version"] is None
    assert initial_office_project["current_publish_package_version"] is None

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    client.post("/api/projects/office-burnout-recovery-weekly/restore-outline/1")

    projects_response = client.get("/api/projects")
    assert projects_response.status_code == 200
    office_project = next(
        project
        for project in projects_response.json()
        if project["slug"] == "office-burnout-recovery-weekly"
    )
    assert office_project["stage"] == "outline_ready"
    assert office_project["chain_status"] == "stale"
    assert office_project["current_chain_state"] == "outline_ready"
    assert office_project["next_required_step"] == "generate_draft"
    assert office_project["current_outline_version"] == 3
    assert office_project["current_draft_version"] is None
    assert office_project["current_assets_version"] is None
    assert office_project["current_publish_package_version"] is None


def test_projects_list_marks_publish_ready_chain_as_ready(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    projects_response = client.get("/api/projects")
    assert projects_response.status_code == 200
    office_project = next(
        project
        for project in projects_response.json()
        if project["slug"] == "office-burnout-recovery-weekly"
    )
    assert office_project["stage"] == "publish_ready"
    assert office_project["chain_status"] == "ready"
    assert office_project["current_chain_state"] == "publish_ready"
    assert office_project["next_required_step"] is None
    assert office_project["current_outline_version"] == 1
    assert office_project["current_draft_version"] == 1
    assert office_project["current_assets_version"] == 1
    assert office_project["current_publish_package_version"] == 1


def test_dashboard_summary_tracks_real_chain_health(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "title_options": ["title a", "title b"],
                "cover_prompt": "prompt",
                "cover_copy": "cover copy",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {
                "abstract": "abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    initial_summary = client.get("/api/dashboard/summary")
    assert initial_summary.status_code == 200
    assert initial_summary.json()["draft_ready_projects"] == 3
    assert initial_summary.json()["publish_ready_projects"] == 0

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    ready_summary = client.get("/api/dashboard/summary")
    assert ready_summary.status_code == 200
    assert ready_summary.json()["draft_ready_projects"] == 2
    assert ready_summary.json()["publish_ready_projects"] == 1

    client.post("/api/projects/office-burnout-recovery-weekly/restore-outline/1")

    restored_summary = client.get("/api/dashboard/summary")
    assert restored_summary.status_code == 200
    assert restored_summary.json()["draft_ready_projects"] == 3
    assert restored_summary.json()["publish_ready_projects"] == 0


def test_batch_continue_projects_completes_pending_chains(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            project_title = str(payload["project_title"])
            return {"hook": f"{project_title} hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            project_title = str(payload["project_title"])
            return {
                "title": f"{project_title} title",
                "body_markdown": f"# {project_title}\n\nbody",
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            draft = payload["draft"]
            return {
                "title_options": [f"{draft['title']} option a", f"{draft['title']} option b"],
                "cover_prompt": "prompt",
                "cover_copy": f"{draft['title']} cover",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            draft = payload["draft"]
            return {
                "abstract": f"{draft['title']} abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    response = client.post("/api/projects/batch-continue", json={})
    assert response.status_code == 202
    submit_payload = response.json()
    assert submit_payload["job_type"] == "batch_continue_projects"
    assert submit_payload["status"] in {"queued", "running", "done"}

    task_payload = wait_for_background_task(submit_payload["task_id"])
    assert task_payload["status"] == "done"
    assert task_payload["result"] is not None
    payload = task_payload["result"]

    assert payload["requested_count"] == 3
    assert payload["processed_count"] == 3
    assert payload["skipped_count"] == 0
    assert payload["failed_count"] == 0
    assert {item["slug"] for item in payload["results"]} == {
        "office-burnout-recovery-weekly",
        "relationship-boundary-reset-series",
        "high-sensitivity-restoration-notes",
    }

    office_result = next(item for item in payload["results"] if item["slug"] == "office-burnout-recovery-weekly")
    assert office_result["status"] == "done"
    assert office_result["started_next_step"] == "generate_outline"
    assert office_result["completed_steps"] == [
        "generate_outline",
        "generate_draft",
        "generate_assets",
        "build_publish_package",
    ]
    assert office_result["project"]["chain_status"] == "ready"
    assert office_result["project"]["current_chain_state"] == "publish_ready"
    assert office_result["project"]["next_required_step"] is None
    assert office_result["project"]["current_publish_package_version"] == 1

    summary = client.get("/api/dashboard/summary")
    assert summary.status_code == 200
    assert summary.json()["draft_ready_projects"] == 0
    assert summary.json()["publish_ready_projects"] == 3

    detail = client.get("/api/projects/office-burnout-recovery-weekly")
    assert detail.status_code == 200
    assert detail.json()["publish_package"]["status"] == "ready"


def test_batch_continue_projects_can_limit_to_selected_slugs(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            project_title = str(payload["project_title"])
            return {"hook": f"{project_title} hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            project_title = str(payload["project_title"])
            return {
                "title": f"{project_title} title",
                "body_markdown": f"# {project_title}\n\nbody",
            }

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            draft = payload["draft"]
            return {
                "title_options": [f"{draft['title']} option a", f"{draft['title']} option b"],
                "cover_prompt": "prompt",
                "cover_copy": f"{draft['title']} cover",
                "social_teaser": "teaser",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            draft = payload["draft"]
            return {
                "abstract": f"{draft['title']} abstract",
                "tags": ["tag-a", "tag-b"],
                "editor_note": "note",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    response = client.post(
        "/api/projects/batch-continue",
        json={"project_slugs": ["office-burnout-recovery-weekly", "high-sensitivity-restoration-notes"]},
    )
    assert response.status_code == 202
    submit_payload = response.json()
    task_payload = wait_for_background_task(submit_payload["task_id"])
    assert task_payload["status"] == "done"
    assert task_payload["result"] is not None
    payload = task_payload["result"]

    assert payload["requested_count"] == 2
    assert payload["processed_count"] == 2
    assert payload["skipped_count"] == 0
    assert payload["failed_count"] == 0
    assert [item["slug"] for item in payload["results"]] == [
        "office-burnout-recovery-weekly",
        "high-sensitivity-restoration-notes",
    ]

    office_detail = client.get("/api/projects/office-burnout-recovery-weekly")
    assert office_detail.status_code == 200
    assert office_detail.json()["publish_package"]["status"] == "ready"

    high_detail = client.get("/api/projects/high-sensitivity-restoration-notes")
    assert high_detail.status_code == 200
    assert high_detail.json()["publish_package"]["status"] == "ready"

    untouched_detail = client.get("/api/projects/relationship-boundary-reset-series")
    assert untouched_detail.status_code == 200
    assert untouched_detail.json()["outline"] is None
    assert untouched_detail.json()["publish_package"] is None


def test_background_task_detail_returns_not_found_for_unknown_task() -> None:
    response = client.get("/api/background-tasks/non-existent-task")
    assert response.status_code == 404
    assert response.json()["detail"] == "Background task not found"


def test_batch_generate_topics_uses_queue_by_default_and_can_limit_to_selected_trends(monkeypatch) -> None:
    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            trend_title = str(payload["trend_title"])
            return {
                "title": f"{trend_title} AI 选题",
                "angle": "情绪识别",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post(
        "/api/trends",
        json={
            "slug": "late-night-recovery",
            "title": "深夜情绪恢复观察",
            "source": "manual",
            "heat_score": 73,
            "status": "screening",
        },
    )

    queue_response = client.post("/api/trends/batch-generate-topics", json={})
    assert queue_response.status_code == 202
    queue_submit = queue_response.json()
    queue_task = wait_for_background_task(queue_submit["task_id"])
    assert queue_task["status"] == "done"
    queue_payload = queue_task["result"]
    assert queue_payload["requested_count"] == 1
    assert queue_payload["processed_count"] == 1
    assert queue_payload["skipped_count"] == 0
    assert queue_payload["failed_count"] == 0
    assert queue_payload["results"][0]["trend_slug"] == "late-night-recovery"
    assert queue_payload["results"][0]["status"] == "done"
    assert queue_payload["results"][0]["topic"]["slug"] == "late-night-recovery-ai-topic-1"

    selected_response = client.post(
        "/api/trends/batch-generate-topics",
        json={"trend_slugs": ["office-burnout-recovery", "self-worth-rebuild"]},
    )
    assert selected_response.status_code == 202
    selected_submit = selected_response.json()
    selected_task = wait_for_background_task(selected_submit["task_id"])
    assert selected_task["status"] == "done"
    selected_payload = selected_task["result"]
    assert selected_payload["requested_count"] == 2
    assert selected_payload["processed_count"] == 1
    assert selected_payload["skipped_count"] == 1
    assert selected_payload["failed_count"] == 0
    assert [item["trend_slug"] for item in selected_payload["results"]] == [
        "office-burnout-recovery",
        "self-worth-rebuild",
    ]
    assert selected_payload["results"][0]["status"] == "skipped"
    assert selected_payload["results"][0]["error"] == "Topic already exists for this trend"
    assert selected_payload["results"][1]["status"] == "done"
    assert selected_payload["results"][1]["topic"]["slug"] == "self-worth-rebuild-ai-topic-1"


def test_dashboard_recent_tasks_include_batch_history_linkage_for_pipeline_views(monkeypatch) -> None:
    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            trend_title = str(payload["trend_title"])
            return {
                "title": f"{trend_title} AI 选题",
                "angle": "情绪识别",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post(
        "/api/trends",
        json={
            "slug": "late-night-recovery",
            "title": "深夜情绪恢复观察",
            "source": "manual",
            "heat_score": 73,
            "status": "screening",
        },
    )

    queue_response = client.post("/api/trends/batch-generate-topics", json={})
    assert queue_response.status_code == 202
    queue_submit = queue_response.json()

    task_payload = wait_for_background_task(queue_submit["task_id"])
    assert task_payload["status"] == "done"

    summary_response = client.get("/api/dashboard/summary")
    assert summary_response.status_code == 200
    recent_tasks = summary_response.json()["recent_tasks"]

    batch_task = next((task for task in recent_tasks if task["task_type"] == "batch_generate_topics"), None)
    assert batch_task is not None
    assert batch_task["entity_type"] == "batch"
    assert batch_task["status"] == "done"
    assert batch_task["background_task_id"] == queue_submit["task_id"]


def test_background_task_logs_pipeline_scope_keeps_batch_history_after_newer_non_batch_actions(monkeypatch) -> None:
    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            trend_title = str(payload["trend_title"])
            return {
                "title": f"{trend_title} AI 选题",
                "angle": "情绪识别",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post(
        "/api/trends",
        json={
            "slug": "pipeline-history-window",
            "title": "批量任务历史窗口验证",
            "source": "manual",
            "heat_score": 66,
            "status": "screening",
        },
    )

    queue_response = client.post("/api/trends/batch-generate-topics", json={})
    assert queue_response.status_code == 202
    queue_submit = queue_response.json()

    task_payload = wait_for_background_task(queue_submit["task_id"])
    assert task_payload["status"] == "done"

    client.post(
        "/api/topics",
        json={
            "slug": "pipeline-manual-topic",
            "title": "后续非批量动作 1",
            "angle": "原创",
        },
    )
    client.post(
        "/api/topics/pipeline-manual-topic/create-project",
        json={
            "slug": "pipeline-manual-topic-project",
            "title": "后续非批量动作 2",
            "owner": "editorial",
        },
    )
    client.post(
        "/api/topics",
        json={
            "slug": "pipeline-manual-topic-2",
            "title": "后续非批量动作 3",
            "angle": "原创",
        },
    )

    summary_response = client.get("/api/dashboard/summary")
    assert summary_response.status_code == 200
    assert all(
        task["background_task_id"] != queue_submit["task_id"] for task in summary_response.json()["recent_tasks"]
    )

    task_log_response = client.get("/api/background-tasks/logs?scope=pipeline")
    assert task_log_response.status_code == 200
    task_logs = task_log_response.json()

    batch_task = next((task for task in task_logs if task["background_task_id"] == queue_submit["task_id"]), None)
    assert batch_task is not None
    assert batch_task["task_type"] == "batch_generate_topics"
    assert batch_task["entity_type"] == "batch"
    assert batch_task["status"] == "done"


def test_batch_generate_topics_from_tracked_articles_uses_queue_by_default_and_can_limit_to_selected_articles(
    monkeypatch,
) -> None:
    class FakeGenerator:
        def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
            article_title = str(payload["article_title"])
            return {
                "title": f"{article_title} AI 选题",
                "angle": "结构提炼",
            }

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post(
        "/api/tracked-articles",
        json={
            "slug": "repair-queue-default",
            "source_name": "关系样本库",
            "title": "把一次误解修复写成可复用动作",
            "url": "https://example.com/repair-queue-default",
            "author": "编辑部",
            "summary": "适合作为默认排队生成的参考文章。",
            "structure_notes": "场景切入 + 情绪拆解 + 修复动作。",
            "tags": ["关系修复"],
        },
    )
    client.post(
        "/api/tracked-articles",
        json={
            "slug": "repair-selected-repeat",
            "source_name": "夜读关系实验室",
            "title": "先接住失望，再进入解释",
            "url": "https://example.com/repair-selected-repeat",
            "author": "北岛",
            "summary": "适合作为重复生成候选的参考文章。",
            "structure_notes": "情绪现场 + 表达顺序 + 动作建议。",
            "tags": ["表达修复"],
        },
    )

    first_generation_response = client.post("/api/tracked-articles/repair-selected-repeat/generate-topic")
    assert first_generation_response.status_code == 201
    assert first_generation_response.json()["slug"] == "repair-selected-repeat-ai-topic-1"

    queue_response = client.post("/api/tracked-articles/batch-generate-topics", json={})
    assert queue_response.status_code == 202
    queue_submit = queue_response.json()
    queue_task = wait_for_background_task(queue_submit["task_id"])
    assert queue_task["status"] == "done"
    queue_payload = queue_task["result"]
    assert queue_payload["requested_count"] == 1
    assert queue_payload["processed_count"] == 1
    assert queue_payload["skipped_count"] == 0
    assert queue_payload["failed_count"] == 0
    assert queue_payload["results"][0]["article_slug"] == "repair-queue-default"
    assert queue_payload["results"][0]["status"] == "done"
    assert queue_payload["results"][0]["topic"]["slug"] == "repair-queue-default-ai-topic-1"

    selected_response = client.post(
        "/api/tracked-articles/batch-generate-topics",
        json={"article_slugs": ["repair-selected-repeat", "repair-queue-default"]},
    )
    assert selected_response.status_code == 202
    selected_submit = selected_response.json()
    selected_task = wait_for_background_task(selected_submit["task_id"])
    assert selected_task["status"] == "done"
    selected_payload = selected_task["result"]
    assert selected_payload["requested_count"] == 2
    assert selected_payload["processed_count"] == 0
    assert selected_payload["skipped_count"] == 2
    assert selected_payload["failed_count"] == 0
    assert [item["article_slug"] for item in selected_payload["results"]] == [
        "repair-selected-repeat",
        "repair-queue-default",
    ]
    assert [item["status"] for item in selected_payload["results"]] == ["skipped", "skipped"]
    assert selected_payload["results"][0]["error"] == "Topic already exists for this tracked article"
    assert selected_payload["results"][1]["error"] == "Topic already exists for this tracked article"


def test_batch_create_projects_uses_queue_by_default_and_skips_topics_with_existing_projects() -> None:
    client.post(
        "/api/trends/self-worth-rebuild/to-topic",
        json={
            "slug": "self-worth-rebuild-topic",
            "title": "自我价值重建可写角度",
            "angle": "自我和解",
        },
    )

    queue_response = client.post("/api/topics/batch-create-projects", json={})
    assert queue_response.status_code == 202
    queue_submit = queue_response.json()
    queue_task = wait_for_background_task(queue_submit["task_id"])
    assert queue_task["status"] == "done"
    queue_payload = queue_task["result"]
    assert queue_payload["requested_count"] == 1
    assert queue_payload["processed_count"] == 1
    assert queue_payload["skipped_count"] == 0
    assert queue_payload["failed_count"] == 0
    assert queue_payload["results"][0]["topic_slug"] == "self-worth-rebuild-topic"
    assert queue_payload["results"][0]["status"] == "done"
    assert queue_payload["results"][0]["project"]["slug"] == "self-worth-rebuild-topic-project"

    client.post(
        "/api/trends/relationship-boundary-reset/to-topic",
        json={
            "slug": "relationship-boundary-reset-extra-topic",
            "title": "关系边界重设补充选题",
            "angle": "边界表达",
        },
    )

    selected_response = client.post(
        "/api/topics/batch-create-projects",
        json={"topic_slugs": ["office-burnout-recovery-for-girls", "relationship-boundary-reset-extra-topic"]},
    )
    assert selected_response.status_code == 202
    selected_submit = selected_response.json()
    selected_task = wait_for_background_task(selected_submit["task_id"])
    assert selected_task["status"] == "done"
    selected_payload = selected_task["result"]
    assert selected_payload["requested_count"] == 2
    assert selected_payload["processed_count"] == 1
    assert selected_payload["skipped_count"] == 1
    assert selected_payload["failed_count"] == 0
    assert [item["topic_slug"] for item in selected_payload["results"]] == [
        "office-burnout-recovery-for-girls",
        "relationship-boundary-reset-extra-topic",
    ]

    skipped_result = selected_payload["results"][0]
    assert skipped_result["status"] == "skipped"
    assert skipped_result["project"] is None
    assert skipped_result["error"] == "Project already exists"

    created_result = selected_payload["results"][1]
    assert created_result["status"] == "done"
    assert created_result["project"]["slug"] == "relationship-boundary-reset-extra-topic-project"


def test_dashboard_recent_tasks_reflect_live_business_actions(monkeypatch) -> None:
    class FakeGenerator:
        def generate_topic(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "办公室倦怠预警信号", "angle": "情绪识别"}

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post(
        "/api/trends",
        json={
            "slug": "late-night-recovery",
            "title": "深夜情绪恢复观察",
            "source": "manual",
            "heat_score": 73,
            "status": "screening",
        },
    )
    client.post("/api/trends/office-burnout-recovery/generate-topic")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")

    summary_response = client.get("/api/dashboard/summary")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    recent_tasks = summary["recent_tasks"]

    assert len(recent_tasks) == 3
    assert [task["task_type"] for task in recent_tasks] == [
        "outline_generation",
        "topic_generation",
        "trend_created",
    ]
    assert recent_tasks[0]["status"] == "done"
    assert recent_tasks[0]["entity_slug"] == "office-burnout-recovery-weekly"
    assert recent_tasks[1]["entity_slug"] == "office-burnout-recovery-ai-topic-1"
    assert recent_tasks[2]["entity_slug"] == "late-night-recovery"


def test_project_versions_endpoint_returns_history_for_generated_content(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            review_comment = payload.get("review_comment")
            if review_comment:
                return {"title": "draft title v2", "body_markdown": "# draft v2\n\nbody"}
            return {"title": "draft title v1", "body_markdown": "# draft v1\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            review_comment = payload.get("review_comment")
            if review_comment:
                return {
                    "title_options": ["title revised"],
                    "cover_prompt": "prompt revised",
                    "cover_copy": "cover copy revised",
                    "social_teaser": "teaser revised",
                }
            return {
                "title_options": ["title v1"],
                "cover_prompt": "prompt v1",
                "cover_copy": "cover copy v1",
                "social_teaser": "teaser v1",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            review_comment = payload.get("review_comment")
            if review_comment:
                return {"abstract": "abstract v2", "tags": ["tag-v2"], "editor_note": "note v2"}
            return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    client.post(
        "/api/projects/office-burnout-recovery-weekly/request-publish-revision",
        json={"reviewer": "ops", "comment": "封面文案太平，需要更强钩子。"},
    )
    regenerate_response = client.post("/api/projects/office-burnout-recovery-weekly/regenerate-from-review")
    assert regenerate_response.status_code == 202
    regenerate_submit = regenerate_response.json()
    regenerate_task = wait_for_background_task(regenerate_submit["task_id"])
    assert regenerate_task["status"] == "done"

    versions_response = client.get("/api/projects/office-burnout-recovery-weekly/versions")
    assert versions_response.status_code == 200
    payload = versions_response.json()

    assert payload["project_slug"] == "office-burnout-recovery-weekly"
    assert [item["version"] for item in payload["outlines"]] == [1]
    assert [item["version"] for item in payload["drafts"]] == [2, 1]
    assert [item["title"] for item in payload["drafts"]] == ["draft title v2", "draft title v1"]
    assert [item["version"] for item in payload["assets"]] == [2, 1]
    assert payload["assets"][0]["cover_copy"] == "cover copy revised"
    assert [item["version"] for item in payload["publish_packages"]] == [2, 1]
    assert payload["publish_packages"][0]["status"] == "ready"
    assert payload["publish_packages"][1]["status"] == "needs_revision"


def test_restore_draft_version_creates_new_current_draft_and_invalidates_downstream(monkeypatch) -> None:
    class FakeGenerator:
        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            review_comment = payload.get("review_comment")
            if review_comment:
                return {"title": "draft title v2", "body_markdown": "# draft v2\n\nbody"}
            return {"title": "draft title v1", "body_markdown": "# draft v1\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            review_comment = payload.get("review_comment")
            if review_comment:
                return {
                    "title_options": ["title v2"],
                    "cover_prompt": "prompt v2",
                    "cover_copy": "cover copy v2",
                    "social_teaser": "teaser v2",
                }
            return {
                "title_options": ["title v1"],
                "cover_prompt": "prompt v1",
                "cover_copy": "cover copy v1",
                "social_teaser": "teaser v1",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            review_comment = payload.get("review_comment")
            if review_comment:
                return {"abstract": "abstract v2", "tags": ["tag-v2"], "editor_note": "note v2"}
            return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    client.post(
        "/api/projects/office-burnout-recovery-weekly/request-publish-revision",
        json={"reviewer": "ops", "comment": "封面文案太平，需要更强钩子。"},
    )
    regenerate_response = client.post("/api/projects/office-burnout-recovery-weekly/regenerate-from-review")
    assert regenerate_response.status_code == 202
    regenerate_submit = regenerate_response.json()
    regenerate_task = wait_for_background_task(regenerate_submit["task_id"])
    assert regenerate_task["status"] == "done"

    restore_response = client.post("/api/projects/office-burnout-recovery-weekly/restore-draft/1")
    assert restore_response.status_code == 201
    restored = restore_response.json()
    assert restored["version"] == 3
    assert restored["title"] == "draft title v1"
    assert restored["outline_version"] == 1

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["project"]["stage"] == "draft_ready"
    assert detail["draft"]["version"] == 3
    assert detail["draft"]["title"] == "draft title v1"
    assert detail["assets"] is None
    assert detail["publish_package"] is None

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in versions["drafts"]] == [3, 2, 1]
    assert [item["version"] for item in versions["assets"]] == [2, 1]
    assert [item["version"] for item in versions["publish_packages"]] == [2, 1]


def test_regenerate_from_review_keeps_publish_package_versions_unique_across_repeated_runs(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.publish_call_count = 0

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            review_comment = payload.get("review_comment")
            if review_comment:
                return {
                    "title": f"draft title regenerated {review_comment}",
                    "body_markdown": f"# regenerated\n\n{review_comment}",
                }
            return {"title": "draft title v1", "body_markdown": "# draft v1\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            review_comment = payload.get("review_comment")
            if review_comment:
                return {
                    "title_options": [f"title regenerated {review_comment}"],
                    "cover_prompt": f"prompt {review_comment}",
                    "cover_copy": f"copy {review_comment}",
                    "social_teaser": f"teaser {review_comment}",
                }
            return {
                "title_options": ["title v1"],
                "cover_prompt": "prompt v1",
                "cover_copy": "cover copy v1",
                "social_teaser": "teaser v1",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.publish_call_count += 1
            review_comment = payload.get("review_comment")
            if review_comment:
                return {
                    "abstract": f"abstract regenerated {self.publish_call_count}",
                    "tags": [f"tag-{self.publish_call_count}"],
                    "editor_note": f"note {review_comment}",
                }
            return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    client.post(
        "/api/projects/office-burnout-recovery-weekly/request-publish-revision",
        json={"reviewer": "ops", "comment": "review-a"},
    )
    first_submit = client.post("/api/projects/office-burnout-recovery-weekly/regenerate-from-review")
    assert first_submit.status_code == 202
    assert wait_for_background_task(first_submit.json()["task_id"])["status"] == "done"

    client.post(
        "/api/projects/office-burnout-recovery-weekly/request-publish-revision",
        json={"reviewer": "ops", "comment": "review-b"},
    )
    second_submit = client.post("/api/projects/office-burnout-recovery-weekly/regenerate-from-review")
    assert second_submit.status_code == 202
    assert wait_for_background_task(second_submit.json()["task_id"])["status"] == "done"

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    publish_versions = [item["version"] for item in versions["publish_packages"]]

    assert publish_versions == [3, 2, 1]
    assert len(publish_versions) == len(set(publish_versions))


def test_restore_outline_version_creates_new_current_outline_and_invalidates_downstream(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.outline_calls = 0

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            self.outline_calls += 1
            if self.outline_calls == 1:
                return {"hook": "hook v1", "outline_body": "1. a\n2. b"}
            return {"hook": "hook v2", "outline_body": "1. c\n2. d"}

        def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
            if payload["outline"]["hook"] == "hook v2":
                return {"title": "draft title v2", "body_markdown": "# draft v2\n\nbody"}
            return {"title": "draft title v1", "body_markdown": "# draft v1\n\nbody"}

        def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
            if payload["draft"]["title"] == "draft title v2":
                return {
                    "title_options": ["title v2"],
                    "cover_prompt": "prompt v2",
                    "cover_copy": "cover copy v2",
                    "social_teaser": "teaser v2",
                }
            return {
                "title_options": ["title v1"],
                "cover_prompt": "prompt v1",
                "cover_copy": "cover copy v1",
                "social_teaser": "teaser v1",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            if payload["draft"]["title"] == "draft title v2":
                return {"abstract": "abstract v2", "tags": ["tag-v2"], "editor_note": "note v2"}
            return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    restore_response = client.post("/api/projects/office-burnout-recovery-weekly/restore-outline/1")
    assert restore_response.status_code == 201
    restored = restore_response.json()
    assert restored["version"] == 3
    assert restored["hook"] == "hook v1"

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["project"]["stage"] == "outline_ready"
    assert detail["outline"]["version"] == 3
    assert detail["outline"]["hook"] == "hook v1"
    assert detail["draft"] is None
    assert detail["assets"] is None
    assert detail["publish_package"] is None

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in versions["outlines"]] == [3, 2, 1]
    assert [item["version"] for item in versions["drafts"]] == [2, 1]
    assert [item["version"] for item in versions["assets"]] == [2, 1]
    assert [item["version"] for item in versions["publish_packages"]] == [2, 1]


def test_restore_assets_version_creates_new_current_assets_and_invalidates_publish_package(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.assets_calls = 0

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            self.assets_calls += 1
            if self.assets_calls == 1:
                return {
                    "title_options": ["title v1"],
                    "cover_prompt": "prompt v1",
                    "cover_copy": "cover copy v1",
                    "social_teaser": "teaser v1",
                }
            return {
                "title_options": ["title v2"],
                "cover_prompt": "prompt v2",
                "cover_copy": "cover copy v2",
                "social_teaser": "teaser v2",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            if payload["assets"]["cover_copy"] == "cover copy v2":
                return {"abstract": "abstract v2", "tags": ["tag-v2"], "editor_note": "note v2"}
            return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    restore_response = client.post("/api/projects/office-burnout-recovery-weekly/restore-assets/1")
    assert restore_response.status_code == 201
    restored = restore_response.json()
    assert restored["version"] == 3
    assert restored["draft_version"] == 1
    assert restored["cover_copy"] == "cover copy v1"

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["project"]["stage"] == "assets_ready"
    assert detail["draft"]["version"] == 1
    assert detail["assets"]["version"] == 3
    assert detail["assets"]["cover_copy"] == "cover copy v1"
    assert detail["publish_package"] is None

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in versions["assets"]] == [3, 2, 1]
    assert [item["version"] for item in versions["publish_packages"]] == [2, 1]


def test_regenerate_cover_image_creates_new_assets_version_without_regenerating_asset_text(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.assets_calls = 0
            self.cover_calls = 0

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            self.assets_calls += 1
            return {
                "title_options": ["title v1", "title v1 alt"],
                "cover_prompt": "prompt v1",
                "cover_copy": "cover copy v1",
                "social_teaser": "teaser v1",
            }

        def generate_cover_image(self, payload: dict[str, object]) -> bytes:
            self.cover_calls += 1
            assert "21:9" in str(payload["cover_prompt"])
            return f"img-{self.cover_calls}".encode("utf-8")

        def generate_publish_package(self, _: dict[str, object]) -> dict[str, object]:
            return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}

    fake_generator = FakeGenerator()
    monkeypatch.setattr(workbench, "get_ai_generator", lambda: fake_generator, raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    first_assets_response = client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    assert first_assets_response.status_code == 201
    first_assets = first_assets_response.json()
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    regenerate_response = client.post("/api/projects/office-burnout-recovery-weekly/regenerate-cover-image")
    assert regenerate_response.status_code == 202
    regenerate_submit = regenerate_response.json()
    assert regenerate_submit["job_type"] == "regenerate_cover_image"
    regenerate_task = wait_for_background_task(regenerate_submit["task_id"])
    assert regenerate_task["status"] == "done"
    regenerated_assets = regenerate_task["result"]

    assert regenerated_assets["version"] == 2
    assert regenerated_assets["draft_version"] == first_assets["draft_version"]
    assert regenerated_assets["title_options"] == ["title v1", "title v1 alt"]
    assert regenerated_assets["cover_prompt"] == first_assets["cover_prompt"]
    assert regenerated_assets["cover_copy"] == "cover copy v1"
    assert regenerated_assets["social_teaser"] == "teaser v1"
    assert regenerated_assets["cover_image_url"] == "/generated-assets/office-burnout-recovery-weekly-assets-v2.png"
    assert Path(regenerated_assets["cover_image_path"]).read_bytes() == b"img-2"

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["project"]["stage"] == "assets_ready"
    assert detail["project"]["current_assets_version"] == 2
    assert detail["project"]["next_required_step"] == "build_publish_package"
    assert detail["assets"]["version"] == 2
    assert detail["assets"]["origin"] == "cover_regeneration"
    assert detail["publish_package"] is None

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in versions["assets"]] == [2, 1]
    assert versions["assets"][0]["origin"] == "cover_regeneration"
    assert [item["version"] for item in versions["publish_packages"]] == [1]

    assert fake_generator.assets_calls == 1
    assert fake_generator.cover_calls == 2


def test_restore_publish_package_version_reapplies_historical_package_to_current_chain(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.assets_calls = 0
            self.publish_calls = 0

        def generate_outline(self, _: dict[str, object]) -> dict[str, str]:
            return {"hook": "hook", "outline_body": "1. a\n2. b"}

        def generate_draft(self, _: dict[str, object]) -> dict[str, str]:
            return {"title": "draft title", "body_markdown": "# draft\n\nbody"}

        def generate_assets(self, _: dict[str, object]) -> dict[str, object]:
            self.assets_calls += 1
            if self.assets_calls == 1:
                return {
                    "title_options": ["title v1"],
                    "cover_prompt": "prompt v1",
                    "cover_copy": "cover copy v1",
                    "social_teaser": "teaser v1",
                }
            return {
                "title_options": ["title v2"],
                "cover_prompt": "prompt v2",
                "cover_copy": "cover copy v2",
                "social_teaser": "teaser v2",
            }

        def generate_cover_image(self, _: dict[str, object]) -> bytes:
            return b"img"

        def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
            self.publish_calls += 1
            if self.publish_calls == 1:
                return {"abstract": "abstract v1", "tags": ["tag-v1"], "editor_note": "note v1"}
            return {"abstract": "abstract v2", "tags": ["tag-v2"], "editor_note": "note v2"}

    monkeypatch.setattr(workbench, "get_ai_generator", lambda: FakeGenerator(), raising=False)

    client.post("/api/projects/office-burnout-recovery-weekly/generate-outline")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-draft")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")
    client.post("/api/projects/office-burnout-recovery-weekly/generate-assets")
    client.post("/api/projects/office-burnout-recovery-weekly/build-publish-package")

    restore_response = client.post("/api/projects/office-burnout-recovery-weekly/restore-publish-package/1")
    assert restore_response.status_code == 201
    restored = restore_response.json()
    assert restored["version"] == 3
    assert restored["draft_version"] == 1
    assert restored["assets_version"] == 2
    assert restored["abstract"] == "abstract v1"
    assert restored["tags"] == ["tag-v1"]
    assert restored["editor_note"] == "note v1"

    detail = client.get("/api/projects/office-burnout-recovery-weekly").json()
    assert detail["project"]["stage"] == "publish_ready"
    assert detail["publish_package"]["version"] == 3
    assert detail["publish_package"]["assets_version"] == 2
    assert detail["publish_package"]["abstract"] == "abstract v1"
    assert detail["assets"]["version"] == 2

    versions = client.get("/api/projects/office-burnout-recovery-weekly/versions").json()
    assert [item["version"] for item in versions["publish_packages"]] == [3, 2, 1]


def test_database_file_created_for_persistent_store() -> None:
    db_path = Path("C:/tmp/gankaigc-wechat-workbench.db")
    assert db_path.exists()
