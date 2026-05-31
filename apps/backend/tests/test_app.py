from __future__ import annotations

from pathlib import Path
import threading
import time

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
    assert call_payload["tone_profile"]["opening_style"] == "从具体场景冷启动切入"
    assert call_payload["tone_profile"]["paragraph_rhythm"] == "短段落，慢推进"
    assert call_payload["tone_profile"]["closing_style"] == "留白式收束"
    assert call_payload["tone_profile"]["forbidden_phrases"] == ["你必须", "立刻改变"]
    assert call_payload["tone_profile"]["value_constraints"] == "不说教，不制造羞耻感，避免空泛鸡汤"
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
    assert call_payload["structure_notes"] == "案例开头 + 情绪拆解 + 动作建议。"
    assert call_payload["tags"] == ["表达修复", "关系修复"]


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
                "body_markdown": "# 别急着解释，先把那一下失望接住\n\n先写失望现场。",
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

    outline_response = client.post("/api/projects/slow-repair-project/generate-outline")
    assert outline_response.status_code == 201
    outline = outline_response.json()
    assert outline["hook"] == "从一次沉默后的回头动作切入"

    draft_response = client.post("/api/projects/slow-repair-project/generate-draft")
    assert draft_response.status_code == 201
    draft = draft_response.json()
    assert draft["title"] == "别急着解释，先把那一下失望接住"

    assert len(fake_generator.calls) == 2
    outline_call_type, outline_payload = fake_generator.calls[0]
    assert outline_call_type == "outline"
    assert outline_payload["trend_title"] == "参考文章 / 夜读关系实验室"
    assert outline_payload["topic_title"] == "先接住失望，再谈道理"
    assert outline_payload["topic_angle"] == "关系修复"
    assert outline_payload["source_type"] == "tracked_article"
    assert outline_payload["reference_article_title"] == "真正让关系缓回来，不是解释，是先接住那一下失望"
    assert outline_payload["reference_article_author"] == "北岛"
    assert outline_payload["reference_article_source_name"] == "夜读关系实验室"
    assert outline_payload["reference_article_summary"] == "从关系修复案例提炼表达顺序。"
    assert outline_payload["reference_article_structure_notes"] == "案例开头 + 情绪拆解 + 动作建议。"
    assert outline_payload["reference_article_tags"] == ["表达修复"]

    draft_call_type, draft_payload = fake_generator.calls[1]
    assert draft_call_type == "draft"
    assert draft_payload["source_type"] == "tracked_article"
    assert draft_payload["reference_article_title"] == "真正让关系缓回来，不是解释，是先接住那一下失望"
    assert draft_payload["reference_article_summary"] == "从关系修复案例提炼表达顺序。"
    assert draft_payload["reference_article_structure_notes"] == "案例开头 + 情绪拆解 + 动作建议。"
    assert draft_payload["reference_article_tags"] == ["表达修复"]


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
    assert len(profiles) == 1
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
    assert len(profiles) == 1
    assert profiles[0]["is_active"] is True
    default_profile_id = profiles[0]["id"]

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
    assert len(refreshed_profiles) == 2
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
    assert len(default_profiles) == 1
    default_profile = default_profiles[0]

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
    assert copied_profile["is_active"] is False

    reorder_response = client.post(
        "/api/tone-profiles/reorder",
        json={"profile_ids": [copied_profile["id"], default_profile["id"], second_profile["id"]]},
    )
    assert reorder_response.status_code == 200
    reordered_profiles = reorder_response.json()
    assert [profile["id"] for profile in reordered_profiles] == [
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
    assert len(profiles_after_delete) == 2
    active_profiles = [profile for profile in profiles_after_delete if profile["is_active"]]
    assert len(active_profiles) == 1
    assert active_profiles[0]["id"] == default_profile["id"]

    delete_last_guard_response = client.request("DELETE", f"/api/tone-profiles/{default_profile['id']}")
    assert delete_last_guard_response.status_code == 200
    delete_second_guard_response = client.request("DELETE", f"/api/tone-profiles/{second_profile['id']}")
    assert delete_second_guard_response.status_code == 409


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
    assert generated["benchmarks"][0]["strategy_version"] == 1
    assert generated["benchmarks"][0]["reference_kind"] == "trend"
    assert generated["benchmarks"][0]["reference_label"] == "办公室倦怠修复"
    assert generated["strategy_card"]["project_slug"] == "office-burnout-recovery-weekly"
    assert generated["strategy_card"]["version"] == 1
    assert generated["strategy_card"]["problem_brief_version"] == 1
    assert generated["strategy_card"]["status"] == "ready"
    assert generated["strategy_card"]["adopted_at"] is None

    detail_response = client.get("/api/projects/office-burnout-recovery-weekly")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["problem_brief"]["version"] == 1
    assert detail["strategy_card"]["version"] == 1
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
    assert second_payload["problem_brief"]["version"] == 1
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
    assert "去模板化重写" in str(draft_calls[1][1]["polish_instruction"])
    assert "上一次精修后，模板风险还没压够" in str(draft_calls[2][1]["polish_instruction"])
    assert "当前仍命中" in str(draft_calls[2][1]["polish_instruction"])


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

    polish_calls = [call for call in fake_generator.calls if call[0] == "draft" and call[1].get("polish_instruction")]
    assert len(polish_calls) == 2
    assert polish_calls[0][1]["polish_instruction"] == "降低模板感，但保留原稿结构。"
    assert "上一次改写发生了结构漂移" in str(polish_calls[1][1]["polish_instruction"])
    assert "这次必须原样保留以下小节标题" in str(polish_calls[1][1]["polish_instruction"])


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
    assert len(polish_calls) == 2
    assert polish_calls[0][1]["polish_instruction"] == "降低模板感，但保留原稿结构和案例。"
    assert "上一次改写虽然保住了结构，但把原稿磨得太顺" in str(polish_calls[1][1]["polish_instruction"])
    assert "很多时候 / 说到底" in str(polish_calls[1][1]["polish_instruction"])


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
    assert len(polish_calls) == 2
    assert polish_calls[0][1]["polish_instruction"] == "降低模板感，但保留原稿结构和案例。"
    assert "上一次精修后，模板风险还没压够" in str(polish_calls[1][1]["polish_instruction"])
    assert "当前仍命中" in str(polish_calls[1][1]["polish_instruction"])
    assert "不要把开头第一屏和各小节首段统一扩成新的氛围场景" in str(polish_calls[1][1]["polish_instruction"])


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
    assert "上一次精修后，模板风险还没压够" in str(polish_calls[1][1]["polish_instruction"])
    assert "最后一轮局部清理" in str(polish_calls[2][1]["polish_instruction"])


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
    assert len(polish_calls) == 3
    assert "上一次精修后，模板风险还没压够" in str(polish_calls[1][1]["polish_instruction"])
    assert "最后一轮局部清理" in str(polish_calls[2][1]["polish_instruction"])


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
