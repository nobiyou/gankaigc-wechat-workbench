from __future__ import annotations

from pathlib import Path
import time

from fastapi.testclient import TestClient

from app.main import app
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


def test_create_trend_persists_and_updates_dashboard() -> None:
    create_response = client.post(
        "/api/trends",
        json={
            "slug": "midlife-reset-notes",
            "title": "中年关系重启观察",
            "source": "manual",
            "heat_score": 77,
            "status": "screening",
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["slug"] == "midlife-reset-notes"

    list_response = client.get("/api/trends")
    assert list_response.status_code == 200
    payload = list_response.json()
    assert len(payload) == 4
    assert any(item["slug"] == "midlife-reset-notes" for item in payload)

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
            "structure_notes": "先回到现场，再拆动作，最后落到可执行表达。",
            "tags": ["关系修复", "冲突沟通"],
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["slug"] == "accountability-repair-notes"
    assert created["source_name"] == "关系练习手册"
    assert created["tags"] == ["关系修复", "冲突沟通"]

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    tracked_articles = list_response.json()
    assert tracked_articles[0]["slug"] == "accountability-repair-notes"

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
            "structure_notes": "场景切入 + 兜底校验。",
            "tags": ["兜底"],
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    assert created["source_name"] == "手动录入"

    list_response = client.get("/api/tracked-articles")
    assert list_response.status_code == 200
    tracked_articles = list_response.json()
    assert tracked_articles[0]["slug"] == "blank-source-article"
    assert tracked_articles[0]["source_name"] == "手动录入"


def test_project_generation_works_for_topics_created_from_tracked_articles(monkeypatch) -> None:
    class FakeGenerator:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, object]]] = []

        def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
            self.calls.append(("outline", payload))
            return {"hook": "从一次沉默后的回头动作切入", "outline_body": "1. 冲突现场\n2. 错位感受\n3. 修复动作"}

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

    assert len(fake_generator.calls) == 1
    call_type, payload = fake_generator.calls[0]
    assert call_type == "outline"
    assert payload["trend_title"] == "参考文章 / 夜读关系实验室"
    assert payload["topic_title"] == "先接住失望，再谈道理"
    assert payload["topic_angle"] == "关系修复"


def test_create_project_from_topic_and_advance_stage() -> None:
    create_response = client.post(
        "/api/topics/relationship-boundary-reset-playbook/create-project",
        json={
            "slug": "relationship-boundary-reset-delivery",
            "title": "关系边界重设交付稿",
            "owner": "editorial",
        },
    )
    assert create_response.status_code == 201
    project = create_response.json()
    assert project["topic_slug"] == "relationship-boundary-reset-playbook"
    assert project["stage"] == "outline"

    update_response = client.patch(
        "/api/projects/relationship-boundary-reset-delivery",
        json={"stage": "draft_ready"},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["stage"] == "draft_ready"

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
        },
    )
    assert project_create_response.status_code == 201
    created_project = project_create_response.json()
    assert created_project["preferred_tone_profile_id"] == bound_profile["id"]
    assert created_project["preferred_tone_profile_name"] == "项目专属纪实风"

    outline_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-outline")
    assert outline_response.status_code == 201
    first_outline_call = fake_generator.calls[0]
    assert first_outline_call[1]["tone_profile"]["name"] == "项目专属纪实风"

    draft_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-draft")
    assert draft_response.status_code == 201
    first_draft_call = next(call for call in fake_generator.calls if call[0] == "draft")
    assert first_draft_call[1]["tone_profile"]["name"] == "项目专属纪实风"

    assets_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-assets")
    assert assets_response.status_code == 201
    first_assets_call = next(call for call in fake_generator.calls if call[0] == "assets")
    assert first_assets_call[1]["tone_profile"]["name"] == "项目专属纪实风"

    publish_package_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/build-publish-package")
    assert publish_package_response.status_code == 201
    first_publish_package_call = next(call for call in fake_generator.calls if call[0] == "publish_package")
    assert first_publish_package_call[1]["tone_profile"]["name"] == "项目专属纪实风"

    patch_response = client.patch(
        "/api/projects/relationship-boundary-reset-bound-tone",
        json={"stage": "outline", "preferred_tone_profile_id": None},
    )
    assert patch_response.status_code == 200
    patched_project = patch_response.json()
    assert patched_project["preferred_tone_profile_id"] is None
    assert patched_project["preferred_tone_profile_name"] is None

    second_outline_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-outline")
    assert second_outline_response.status_code == 201
    second_outline_call = [call for call in fake_generator.calls if call[0] == "outline"][-1]
    assert second_outline_call[1]["tone_profile"]["name"] == "女性成长克制陪伴风"

    second_draft_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-draft")
    assert second_draft_response.status_code == 201
    second_draft_call = [call for call in fake_generator.calls if call[0] == "draft"][-1]
    assert second_draft_call[1]["tone_profile"]["name"] == "女性成长克制陪伴风"

    second_assets_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/generate-assets")
    assert second_assets_response.status_code == 201
    second_assets_call = [call for call in fake_generator.calls if call[0] == "assets"][-1]
    assert second_assets_call[1]["tone_profile"]["name"] == "女性成长克制陪伴风"

    second_publish_package_response = client.post("/api/projects/relationship-boundary-reset-bound-tone/build-publish-package")
    assert second_publish_package_response.status_code == 201
    second_publish_package_call = [call for call in fake_generator.calls if call[0] == "publish_package"][-1]
    assert second_publish_package_call[1]["tone_profile"]["name"] == "女性成长克制陪伴风"


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
    assert versions["outlines"][0]["tone_profile_name"] == "纪实关系复盘风"
    assert versions["drafts"][0]["tone_profile_name"] == "纪实关系复盘风"
    assert versions["assets"][0]["tone_profile_name"] == "纪实关系复盘风"
    assert versions["publish_packages"][0]["tone_profile_name"] == "纪实关系复盘风"

    default_profile = next(profile for profile in client.get("/api/tone-profiles").json() if profile["name"] == "女性成长克制陪伴风")
    deactivate_response = client.post(f"/api/tone-profiles/{default_profile['id']}/activate")
    assert deactivate_response.status_code == 200

    restored_outline_response = client.post("/api/projects/office-burnout-recovery-weekly/restore-outline/1")
    assert restored_outline_response.status_code == 201
    restored_outline = restored_outline_response.json()
    assert restored_outline["tone_profile_id"] == created_profile["id"]
    assert restored_outline["tone_profile_name"] == "纪实关系复盘风"


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
    assert fake_generator.calls[3][1]["cover_prompt"] == "夜晚办公室，一个女生独自坐在工位前，暖黄灯光，情绪克制写实风"
    assert fake_generator.calls[4][1]["assets"]["cover_image_url"] == "/generated-assets/office-burnout-recovery-weekly-assets-v1.png"


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
