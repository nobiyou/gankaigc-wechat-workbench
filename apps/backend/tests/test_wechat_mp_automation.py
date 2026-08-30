from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

import app.services.wechat_mp_automation as automation
import app.services.workbench as workbench
import app.api.wechat_mp as wechat_mp_api
from app.main import app
from app.schemas.wechat_mp_automation import (
    AutomationRunSubmission,
    AutomationSubscriptionCreate,
    AutomationSubscriptionUpdate,
)
from app.services.wechat_mp_automation import (
    acquire_lease,
    calculate_next_run_at,
    claim_scheduled_run,
    create_manual_run,
    create_subscription,
    execute_run,
    get_run,
    get_subscription,
    is_schedule_due,
    list_runs,
    list_subscriptions,
    release_lease,
    run_due_cycle,
    retry_run,
    update_subscription,
)
from app.services.wechat_mp_client import WechatMpArticleFetchError


def _subscription(fakeid: str, *, nickname: str = "示例号", **overrides: object) -> AutomationSubscriptionCreate:
    payload: dict[str, object] = {
        "account_fakeid": fakeid,
        "account_nickname": nickname,
        "schedule_time": "21:00",
        "timezone": "Asia/Shanghai",
        "fetch_limit": 1,
        "automatic_draft": True,
    }
    payload.update(overrides)
    return AutomationSubscriptionCreate(**payload)


def _install_fake_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    articles: list[dict[str, object]],
    fail_on_repeated_fetch: bool = False,
) -> dict[str, object]:
    state: dict[str, object] = {
        "project_created": False,
        "outline": False,
        "draft": False,
        "assets": False,
        "package": None,
    }
    calls: dict[str, int] = {}

    def record(name: str) -> None:
        calls[name] = calls.get(name, 0) + 1

    def package(*, status: str, draft_status: str = "not_published", draft_id: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(
            version=3,
            status=status,
            html_url="/generated-assets/automation-article.html",
            markdown_url="/generated-assets/automation-article.md",
            wechat_html_style_name="杂志留白",
            wechat_mp_draft_status=draft_status,
            wechat_mp_draft_id=draft_id,
        )

    class FakeWechatClient:
        def get_session_status(self) -> dict[str, object]:
            return {"logged_in": True, "status_message": "已登录"}

        def list_articles(self, **_: object) -> list[dict[str, object]]:
            record("list_articles")
            if fail_on_repeated_fetch and calls["list_articles"] > 1:
                raise AssertionError("the persisted workflow should be used for a retry")
            return articles

        def fetch_article_body(self, _link: str, _digest: str) -> tuple[str, str]:
            record("fetch_article_body")
            return "# 改写后的文章\n\n正文内容", "dom"

    fake_client = FakeWechatClient()

    monkeypatch.setattr(automation, "get_wechat_mp_client", lambda: fake_client)
    monkeypatch.setattr(workbench, "list_tracked_articles", lambda: [])
    monkeypatch.setattr(
        workbench,
        "import_tracked_articles",
        lambda _payloads, source_kind=None: (
            record("import_tracked_articles"),
            {"created": [SimpleNamespace(slug="tracked-automation-1")]},
        )[1],
    )
    monkeypatch.setattr(
        workbench,
        "generate_topic_from_tracked_article",
        lambda _slug: (record("generate_topic"), SimpleNamespace(slug="topic-automation-1"))[1],
    )
    monkeypatch.setattr(
        workbench,
        "list_projects",
        lambda: [SimpleNamespace(topic_slug="topic-automation-1", slug="project-automation-1")]
        if state["project_created"]
        else [],
    )

    def create_project(_topic_slug: str, _payload: object) -> SimpleNamespace:
        record("create_project")
        state["project_created"] = True
        return SimpleNamespace(slug="project-automation-1")

    monkeypatch.setattr(workbench, "create_project_from_topic", create_project)

    def project_detail(_project_slug: str) -> SimpleNamespace:
        return SimpleNamespace(
            project=SimpleNamespace(next_required_step=""),
            outline=SimpleNamespace() if state["outline"] else None,
            draft=SimpleNamespace() if state["draft"] else None,
            assets=SimpleNamespace(cover_image_status="ready") if state["assets"] else None,
            publish_package=state["package"],
        )

    monkeypatch.setattr(workbench, "get_project_detail", project_detail)
    monkeypatch.setattr(workbench, "generate_outline", lambda _slug: (record("generate_outline"), state.update(outline=True))[1])
    monkeypatch.setattr(workbench, "generate_draft", lambda _slug: (record("generate_draft"), state.update(draft=True))[1])
    monkeypatch.setattr(workbench, "generate_assets", lambda _slug: (record("generate_assets"), state.update(assets=True))[1])

    def build_publish_package(_slug: str) -> SimpleNamespace:
        record("build_publish_package")
        state["package"] = package(status="ready")
        return state["package"]

    monkeypatch.setattr(workbench, "build_publish_package", build_publish_package)

    def approve_publish_package(*_args: object, **_kwargs: object) -> SimpleNamespace:
        record("approve_publish_package")
        state["package"] = package(status="approved")
        return state["package"]

    monkeypatch.setattr(workbench, "approve_publish_package", approve_publish_package)

    def publish_wechat_mp_draft(*_args: object, **_kwargs: object) -> SimpleNamespace:
        record("publish_wechat_mp_draft")
        state["package"] = package(status="approved", draft_status="published", draft_id="draft-automation-1")
        return state["package"]

    monkeypatch.setattr(workbench, "publish_wechat_mp_draft", publish_wechat_mp_draft)
    monkeypatch.setattr(
        workbench,
        "mark_publish_package_provenance",
        lambda *_args, **_kwargs: (record("mark_publish_package_provenance"), state["package"])[1],
        raising=False,
    )
    return {"calls": calls, "state": state}


def test_store_reset_creates_automation_tables() -> None:
    with workbench._get_connection() as connection:
        names = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'automation_%'"
            ).fetchall()
        }
    assert names == {
        "automation_locks",
        "automation_runs",
        "automation_subscriptions",
        "automation_workflows",
    }


def test_subscription_schema_rejects_invalid_schedule_timezone_and_limit() -> None:
    with pytest.raises(ValidationError):
        _subscription("bad-time", schedule_time="9:00")
    with pytest.raises(ValidationError):
        _subscription("bad-zone", timezone="Not/AZone")
    with pytest.raises(ValidationError):
        _subscription("bad-limit", fetch_limit=11)
    with pytest.raises(ValidationError):
        _subscription("missing-biz", article_source="wx_channel")


def test_wx_channel_subscription_persists_biz_and_source() -> None:
    subscription = create_subscription(
        _subscription(
            "MzA4-example",
            nickname="Example Account",
            account_biz="MzA4-example",
            article_source="wx_channel",
        )
    )

    assert subscription.account_fakeid == "MzA4-example"
    assert subscription.account_biz == "MzA4-example"
    assert subscription.article_source == "wx_channel"


def test_wx_channel_account_search_api_returns_captured_account(monkeypatch: pytest.MonkeyPatch) -> None:
    class Directory:
        def list_accounts(self, keyword: str, *, page: int, page_size: int) -> list[dict[str, object]]:
            assert keyword == "example"
            assert page == 1
            assert page_size == 20
            return [
                {
                    "source": "wx_channel",
                    "biz": "MzA4-example",
                    "nickname": "Example Account",
                    "avatar_url": "",
                }
            ]

    monkeypatch.setattr(wechat_mp_api, "get_wx_channel_client", lambda: Directory())
    response = TestClient(app).get("/api/wechat-mp/accounts/wx-channel?keyword=example")

    assert response.status_code == 200
    assert response.json()[0]["biz"] == "MzA4-example"
    assert response.json()[0]["source"] == "wx_channel"


def test_wx_channel_article_api_returns_article_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    class ArticleSource:
        def list_articles(self, *, biz: str, offset: int, limit: int) -> list[dict[str, object]]:
            assert (biz, offset, limit) == ("MzA4-example", 0, 10)
            return [
                {
                    "article_id": "mid:1:idx:1",
                    "account_biz": biz,
                    "title": "New article",
                    "link": "https://mp.weixin.qq.com/s/article-1",
                }
            ]

    monkeypatch.setattr(wechat_mp_api, "get_wx_channel_client", lambda: ArticleSource())
    response = TestClient(app).get("/api/wechat-mp/accounts/wx-channel/MzA4-example/articles")

    assert response.status_code == 200
    assert response.json()[0]["article_id"] == "mid:1:idx:1"


def test_due_check_uses_subscription_timezone_and_only_current_local_date() -> None:
    before = datetime(2026, 8, 26, 12, 59, tzinfo=timezone.utc)
    after = datetime(2026, 8, 26, 13, 0, tzinfo=timezone.utc)
    assert not is_schedule_due(
        schedule_time="21:00",
        timezone_name="Asia/Shanghai",
        last_scheduled_local_date=None,
        now=before,
    )
    assert is_schedule_due(
        schedule_time="21:00",
        timezone_name="Asia/Shanghai",
        last_scheduled_local_date=None,
        now=after,
    )
    assert not is_schedule_due(
        schedule_time="21:00",
        timezone_name="Asia/Shanghai",
        last_scheduled_local_date="2026-08-26",
        now=after,
    )
    next_run = calculate_next_run_at(
        schedule_time="21:00",
        timezone_name="Asia/Shanghai",
        last_scheduled_local_date="2026-08-26",
        now=after,
    )
    assert next_run == "2026-08-27T13:00:00+00:00"


def test_subscription_crud_keeps_same_nickname_accounts_separate_and_disables_one() -> None:
    first = create_subscription(_subscription("fakeid-a"))
    second = create_subscription(_subscription("fakeid-b"))
    assert [item.account_fakeid for item in list_subscriptions()] == ["fakeid-b", "fakeid-a"]
    with pytest.raises(Exception):
        create_subscription(_subscription("fakeid-a", nickname="另一个显示名"))

    updated = update_subscription(
        first.id,
        AutomationSubscriptionUpdate(schedule_time="20:30", enabled=False),
    )
    assert updated.enabled is False
    assert updated.schedule_time == "20:30"
    assert get_subscription(second.id).enabled is True


def test_disabled_subscription_can_be_run_manually() -> None:
    subscription = create_subscription(_subscription("manual-disabled-fakeid"))
    update_subscription(subscription.id, AutomationSubscriptionUpdate(enabled=False))

    submission = create_manual_run(subscription.id)

    assert submission.subscription_id == subscription.id
    assert submission.trigger == "manual"
    assert submission.status == "queued"


def test_scan_and_wx_channel_identity_cannot_create_two_subscriptions() -> None:
    first = create_subscription(_subscription("scan-fakeid", nickname="跨来源公众号"))

    with pytest.raises(HTTPException) as error:
        create_subscription(
            _subscription(
                "capture-fakeid",
                nickname="跨来源公众号",
                account_biz="scan-fakeid",
                article_source="wx_channel",
            )
        )

    assert error.value.status_code == 409
    assert "ID" in str(error.value.detail)
    assert len(list_subscriptions()) == 1
    assert get_subscription(first.id).article_source == "wechat_mp"


def test_existing_subscription_can_switch_article_source_without_changing_id() -> None:
    first = create_subscription(_subscription("scan-fakeid", nickname="跨来源公众号"))

    updated = update_subscription(
        first.id,
        AutomationSubscriptionUpdate(
            account_fakeid="capture-fakeid",
            account_biz="capture-biz",
            article_source="wx_channel",
        ),
    )

    assert updated.id == first.id
    assert updated.account_fakeid == "capture-fakeid"
    assert updated.account_biz == "capture-biz"
    assert updated.article_source == "wx_channel"
    assert len(list_subscriptions()) == 1


def test_expired_lease_can_be_replaced_but_live_lease_cannot() -> None:
    lock_key = "test-lock"
    first_now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    assert acquire_lease(lock_key, "owner-a", lease_seconds=30, now=first_now)
    assert not acquire_lease(
        lock_key,
        "owner-b",
        lease_seconds=30,
        now=datetime(2026, 8, 26, 12, 0, 1, tzinfo=timezone.utc),
    )
    assert acquire_lease(
        lock_key,
        "owner-b",
        lease_seconds=30,
        now=datetime(2026, 8, 26, 12, 0, 31, tzinfo=timezone.utc),
    )
    assert not release_lease(lock_key, "owner-a")
    assert release_lease(lock_key, "owner-b")


def test_concurrent_scheduled_claims_create_one_run() -> None:
    subscription = create_subscription(_subscription("claim-fakeid"))

    def claim() -> int | None:
        return claim_scheduled_run(subscription.id, "2026-08-26")

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _item: claim(), range(6)))
    claimed = [run_id for run_id in results if run_id is not None]
    assert len(claimed) == 1
    assert len(list_runs(subscription_id=subscription.id)) == 1
    assert get_subscription(subscription.id).last_scheduled_local_date == "2026-08-26"


def test_execute_run_completes_pipeline_and_writes_only_draft(monkeypatch: pytest.MonkeyPatch) -> None:
    article = {
        "article_id": "article-1",
        "link": "https://mp.weixin.qq.com/s/article-1",
        "title": "原始文章",
        "author": "作者",
        "digest": "摘要",
        "update_time": 10,
    }
    fake = _install_fake_pipeline(monkeypatch, articles=[article])
    subscription = create_subscription(_subscription("pipeline-fakeid"))
    submission = create_manual_run(subscription.id)

    result = execute_run(submission.run_id)

    assert result.status == "completed"
    assert result.stage == "draft_written"
    assert result.tracked_article_slug == "tracked-automation-1"
    assert result.topic_slug == "topic-automation-1"
    assert result.project_slug == "topic-automation-1-automation-project"
    assert result.publish_package_version == 3
    assert result.draft_status == "published"
    assert result.draft_id == "draft-automation-1"
    assert result.preview_url == "/generated-assets/automation-article.html"
    assert result.style_name == "杂志留白"
    assert result.provenance == automation.AUTOMATION_PROVENANCE
    assert fake["calls"]["approve_publish_package"] == 1
    assert fake["calls"]["publish_wechat_mp_draft"] == 1
    assert fake["calls"].get("group_send", 0) == 0


def test_automatic_draft_disabled_stops_after_approved_package(monkeypatch: pytest.MonkeyPatch) -> None:
    article = {
        "article_id": "article-no-draft",
        "link": "https://mp.weixin.qq.com/s/article-no-draft",
        "title": "只生成发布包",
        "digest": "摘要",
        "update_time": 11,
    }
    fake = _install_fake_pipeline(monkeypatch, articles=[article])
    subscription = create_subscription(_subscription("package-only-fakeid", automatic_draft=False))
    submission = create_manual_run(subscription.id)

    result = execute_run(submission.run_id)

    assert result.status == "completed"
    assert result.stage == "package_approved"
    assert result.draft_status == "not_published"
    assert result.draft_id is None
    assert result.result is not None
    assert result.result["items"][0]["automatic_draft"] is False
    assert fake["calls"]["approve_publish_package"] == 1
    assert fake["calls"].get("publish_wechat_mp_draft", 0) == 0


def test_execute_run_uses_wx_channel_source_by_biz_without_scan_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = {
        "article_id": "wx-channel-article",
        "account_biz": "MzA4-example",
        "link": "https://mp.weixin.qq.com/s/wx-channel-article",
        "title": "wx_channel article",
        "digest": "summary",
        "update_time": 17,
    }
    fake = _install_fake_pipeline(monkeypatch, articles=[])

    class WxChannelSource:
        def list_articles(self, *, biz: str, offset: int, limit: int) -> list[dict[str, object]]:
            assert biz == "MzA4-example"
            assert offset == 0
            assert limit == 10
            return [article]

        def fetch_article_body(
            self,
            _link: str,
            _digest: str,
            *,
            biz: str,
        ) -> tuple[str, str]:
            assert biz == "MzA4-example"
            return "# Body from wx_channel", "wx_channel_rss"

    monkeypatch.setattr(automation, "get_wx_channel_client", lambda: WxChannelSource())

    def fail_if_scan_session_used():
        raise AssertionError("wx_channel subscriptions must not require the local scan session")

    monkeypatch.setattr(automation, "get_wechat_mp_client", fail_if_scan_session_used)
    subscription = create_subscription(
        _subscription(
            "MzA4-example",
            nickname="Example Account",
            account_biz="MzA4-example",
            article_source="wx_channel",
        )
    )

    result = execute_run(create_manual_run(subscription.id).run_id)

    assert result.status == "completed"
    assert result.source_article_title == "wx_channel article"
    assert fake["calls"]["import_tracked_articles"] == 1


def test_retry_uses_persisted_workflow_without_fetching_latest_articles(monkeypatch: pytest.MonkeyPatch) -> None:
    article = {
        "article_id": "persisted-article",
        "link": "https://mp.weixin.qq.com/s/persisted-article",
        "title": "持久化来源",
        "update_time": 12,
    }
    subscription = create_subscription(_subscription("retry-fakeid"))
    workflow = automation._get_or_create_workflow(subscription.id, article)
    submission = create_manual_run(subscription.id, trigger="retry", workflow_id=int(workflow["id"]))
    seen: dict[str, object] = {}

    class RetryClient:
        def get_session_status(self) -> dict[str, object]:
            return {"logged_in": True}

        def list_articles(self, **_: object) -> list[dict[str, object]]:
            raise AssertionError("a retry must not depend on the latest article list")

    def resume_stage(
        run_id: int,
        workflow_id: int,
        subscription_id: int,
        retry_article: dict[str, object],
        *,
        automatic_draft: bool,
    ) -> dict[str, object]:
        seen.update(
            {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "subscription_id": subscription_id,
                "article": retry_article,
                "automatic_draft": automatic_draft,
            }
        )
        return {
            "status": "completed",
            "source_article_link": retry_article["link"],
            "tracked_article_slug": "tracked-retry",
            "topic_slug": "topic-retry",
            "project_slug": "project-retry",
            "publish_package_version": 1,
            "draft_status": "published",
            "draft_id": "draft-retry",
            "completion_stage": "draft_written",
            "provenance": automation.AUTOMATION_PROVENANCE,
        }

    monkeypatch.setattr(automation, "get_wechat_mp_client", lambda: RetryClient())
    monkeypatch.setattr(automation, "_run_workflow_stages", resume_stage)

    result = execute_run(submission.run_id)

    assert result.status == "completed"
    assert seen["workflow_id"] == int(workflow["id"])
    assert seen["article"]["link"] == article["link"]
    assert seen["article"]["title"] == article["title"]
    assert seen["automatic_draft"] is True


def test_duplicate_manual_import_is_skipped_without_project_or_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    article = {
        "article_id": "duplicate-article",
        "link": "https://mp.weixin.qq.com/s/duplicate-article",
        "title": "已经手动导入",
        "digest": "摘要",
        "update_time": 13,
    }
    subscription = create_subscription(_subscription("duplicate-fakeid"))
    project_calls: list[str] = []

    class DuplicateClient:
        def get_session_status(self) -> dict[str, object]:
            return {"logged_in": True}

        def list_articles(self, **_: object) -> list[dict[str, object]]:
            return [article]

    monkeypatch.setattr(automation, "get_wechat_mp_client", lambda: DuplicateClient())
    monkeypatch.setattr(
        workbench,
        "list_tracked_articles",
        lambda: [SimpleNamespace(url=article["link"], slug="manual-existing")],
    )
    monkeypatch.setattr(
        workbench,
        "create_project_from_topic",
        lambda *_args, **_kwargs: project_calls.append("created"),
    )

    result = execute_run(create_manual_run(subscription.id).run_id)

    assert result.status == "skipped"
    assert result.stage == "skipped"
    assert result.tracked_article_slug == "manual-existing"
    assert result.result is not None
    assert result.result["items"][0]["reason"] == "manual_import_duplicate"
    assert result.retryable is False
    assert project_calls == []
    with pytest.raises(HTTPException) as exc_info:
        automation.retry_run(result.id)
    assert exc_info.value.status_code == 409


def test_multi_article_result_projects_first_item_into_run_detail() -> None:
    subscription = create_subscription(_subscription("multi-result-fakeid"))
    first = {
        "status": "completed",
        "source_article_id": "first-id",
        "source_article_link": "https://example.com/first",
        "source_article_title": "第一篇",
        "tracked_article_slug": "tracked-first",
        "topic_slug": "topic-first",
        "project_slug": "project-first",
        "publish_package_version": 7,
        "draft_status": "published",
        "draft_id": "draft-first",
        "preview_url": "/generated-assets/first.html",
        "style_name": "杂志留白",
        "provenance": automation.AUTOMATION_PROVENANCE,
    }
    second = {
        "status": "completed",
        "source_article_id": "second-id",
        "source_article_link": "https://example.com/second",
        "source_article_title": "第二篇",
        "project_slug": "project-second",
        "publish_package_version": 8,
        "draft_status": "published",
        "draft_id": "draft-second",
        "preview_url": "/generated-assets/second.html",
        "style_name": "报纸专栏",
        "provenance": automation.AUTOMATION_PROVENANCE,
    }
    with workbench._get_connection() as connection:
        connection.execute(
            """
            INSERT INTO automation_runs (
                subscription_id, trigger, status, stage, result_json, created_at
            ) VALUES (?, 'manual', 'completed', 'completed', ?, ?)
            """,
            (
                subscription.id,
                json.dumps({"items": [first, second], "provenance": automation.AUTOMATION_PROVENANCE}, ensure_ascii=False),
                "2026-08-26T13:00:00+00:00",
            ),
        )
        run_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
        connection.commit()

    result = get_run(run_id)

    assert result.source_article_id == "first-id"
    assert result.source_url == "https://example.com/first"
    assert result.project_slug == "project-first"
    assert result.project_url == "/projects/project-first/workbench/publish"
    assert result.preview_url == "/generated-assets/first.html"
    assert result.style_name == "杂志留白"
    assert result.publish_package_version == 7
    assert result.draft_id == "draft-first"


def test_failed_workflow_retry_resumes_without_duplicate_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    article = {
        "article_id": "resume-article",
        "link": "https://mp.weixin.qq.com/s/resume-article",
        "title": "失败后恢复",
        "digest": "摘要",
        "update_time": 14,
    }
    fake = _install_fake_pipeline(
        monkeypatch,
        articles=[article],
        fail_on_repeated_fetch=True,
    )
    original_generate_outline = workbench.generate_outline
    first_attempt = {"value": True}

    def fail_once(project_slug: str) -> object:
        if first_attempt["value"]:
            first_attempt["value"] = False
            raise RuntimeError("模拟大纲生成失败")
        return original_generate_outline(project_slug)

    monkeypatch.setattr(workbench, "generate_outline", fail_once)
    subscription = create_subscription(_subscription("resume-fakeid"))
    first_submission = create_manual_run(subscription.id)

    first_result = execute_run(first_submission.run_id)

    assert first_result.status == "failed"
    assert first_result.stage == "generating_outline"
    with workbench._get_connection() as connection:
        workflow_row = connection.execute(
            "SELECT id, status FROM automation_workflows WHERE subscription_id = ?",
            (subscription.id,),
        ).fetchone()
    assert workflow_row is not None
    assert workflow_row["status"] == "failed"

    retry_submission = create_manual_run(
        subscription.id,
        trigger="retry",
        workflow_id=int(workflow_row["id"]),
    )
    retry_result = execute_run(retry_submission.run_id)

    assert retry_result.status == "completed"
    assert retry_result.stage == "draft_written"
    assert fake["calls"]["list_articles"] == 1
    assert fake["calls"]["import_tracked_articles"] == 1
    assert fake["calls"]["generate_topic"] == 1
    assert fake["calls"]["create_project"] == 1
    assert fake["calls"]["publish_wechat_mp_draft"] == 1


def test_session_expiry_is_recorded_at_session_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    subscription = create_subscription(_subscription("expired-session-fakeid"))

    class ExpiredClient:
        def get_session_status(self) -> dict[str, object]:
            return {"logged_in": False, "status_message": "公众号登录已过期，请重新扫码登录"}

        def list_articles(self, **_: object) -> list[dict[str, object]]:
            raise AssertionError("expired sessions must fail before article fetch")

    monkeypatch.setattr(automation, "get_wechat_mp_client", lambda: ExpiredClient())

    result = execute_run(create_manual_run(subscription.id).run_id)

    assert result.status == "failed"
    assert result.stage == "session"
    assert result.error == "公众号登录已过期，请重新扫码登录"
    assert result.retryable is True


def test_article_fetch_business_error_is_failed_at_fetching_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    subscription = create_subscription(_subscription("fetch-error-fakeid"))

    class FailingClient:
        def get_session_status(self) -> dict[str, object]:
            return {"logged_in": True, "nickname": "示例号"}

        def list_articles(self, **_: object) -> list[dict[str, object]]:
            raise WechatMpArticleFetchError(code=200013, err_msg="freq control")

    monkeypatch.setattr(automation, "get_wechat_mp_client", lambda: FailingClient())

    result = execute_run(create_manual_run(subscription.id).run_id)

    assert result.status == "failed"
    assert result.stage == "fetching_articles"
    assert "200013" in str(result.error)
    assert result.result == {"provenance": automation.AUTOMATION_PROVENANCE}


def test_article_fetch_rejects_subscription_for_different_logged_in_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subscription = create_subscription(_subscription("other-account-fakeid", nickname="夜听"))

    class DifferentAccountClient:
        def get_cached_session_status(self) -> dict[str, object]:
            return {"logged_in": True, "nickname": "今晚有语"}

        def get_session_status(self) -> dict[str, object]:
            raise AssertionError("account guard should use the cached session status")

        def list_articles(self, **_: object) -> list[dict[str, object]]:
            raise AssertionError("a different logged-in account must fail before article fetch")

    monkeypatch.setattr(automation, "get_wechat_mp_client", lambda: DifferentAccountClient())

    result = execute_run(create_manual_run(subscription.id).run_id)

    assert result.status == "failed"
    assert result.stage == "fetching_articles"
    assert "今晚有语" in str(result.error)
    assert "夜听" in str(result.error)


def test_next_due_cycle_resumes_failed_workflow_without_duplicate_artifacts(monkeypatch: pytest.MonkeyPatch) -> None:
    article = {
        "article_id": "next-cycle-article",
        "link": "https://mp.weixin.qq.com/s/next-cycle-article",
        "title": "次日恢复",
        "digest": "摘要",
        "update_time": 15,
    }
    fake = _install_fake_pipeline(monkeypatch, articles=[article])
    original_generate_outline = workbench.generate_outline
    first_attempt = {"value": True}

    def fail_once(project_slug: str) -> object:
        if first_attempt["value"]:
            first_attempt["value"] = False
            raise RuntimeError("模拟次日恢复前失败")
        return original_generate_outline(project_slug)

    monkeypatch.setattr(workbench, "generate_outline", fail_once)
    subscription = create_subscription(_subscription("next-cycle-fakeid"))

    first_cycle = run_due_cycle(now=datetime(2026, 8, 26, 13, 0, tzinfo=timezone.utc))
    second_cycle = run_due_cycle(now=datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc))

    assert first_cycle.claimed_count == 1
    assert first_cycle.failed_count == 1
    assert second_cycle.claimed_count == 1
    assert second_cycle.failed_count == 0
    assert get_run(first_cycle.run_ids[0]).status == "failed"
    assert get_run(second_cycle.run_ids[0]).status == "completed"
    assert fake["calls"]["list_articles"] == 2
    assert fake["calls"]["import_tracked_articles"] == 1
    assert fake["calls"]["generate_topic"] == 1
    assert fake["calls"]["create_project"] == 1
    assert fake["calls"]["publish_wechat_mp_draft"] == 1


def test_manual_retry_keeps_failed_run_workflow_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    article = {
        "article_id": "manual-retry-article",
        "link": "https://mp.weixin.qq.com/s/manual-retry-article",
        "title": "手动重试",
        "update_time": 16,
    }
    subscription = create_subscription(_subscription("manual-retry-fakeid"))
    workflow = automation._get_or_create_workflow(subscription.id, article)
    failed_submission = create_manual_run(subscription.id, workflow_id=int(workflow["id"]))
    with workbench._get_connection() as connection:
        connection.execute(
            "UPDATE automation_runs SET status = 'failed', stage = 'generating_draft', error = ? WHERE id = ?",
            ("模拟失败", failed_submission.run_id),
        )
        connection.commit()
    captured: dict[str, object] = {}

    def fake_submit(
        subscription_id: int,
        *,
        trigger: str,
        workflow_id: int | None,
    ) -> AutomationRunSubmission:
        captured.update(
            {
                "subscription_id": subscription_id,
                "trigger": trigger,
                "workflow_id": workflow_id,
            }
        )
        return AutomationRunSubmission(
            run_id=999,
            subscription_id=subscription_id,
            trigger="retry",
            status="queued",
            created_at="2026-08-26T13:00:00+00:00",
        )

    monkeypatch.setattr(automation, "submit_run_in_background", fake_submit)

    retry_submission = retry_run(failed_submission.run_id)

    assert retry_submission.run_id == 999
    assert captured == {
        "subscription_id": subscription.id,
        "trigger": "retry",
        "workflow_id": int(workflow["id"]),
    }


def test_automation_api_returns_submission_and_pollable_run(monkeypatch: pytest.MonkeyPatch) -> None:
    api_client = TestClient(app)
    response = api_client.post(
        "/api/wechat-mp/automation/subscriptions",
        json={
            "account_fakeid": "api-fakeid",
            "account_nickname": "API 示例号",
        },
    )
    assert response.status_code == 201
    subscription_id = response.json()["id"]
    monkeypatch.setattr(automation, "execute_run", lambda _run_id: None)

    submit_response = api_client.post(
        f"/api/wechat-mp/automation/subscriptions/{subscription_id}/runs"
    )

    assert submit_response.status_code == 202
    submission = submit_response.json()
    assert submission["subscription_id"] == subscription_id
    assert submission["trigger"] == "manual"
    assert submission["status"] == "queued"
    poll_response = api_client.get(f"/api/wechat-mp/automation/runs/{submission['run_id']}")
    assert poll_response.status_code == 200
    assert poll_response.json()["id"] == submission["run_id"]
    assert poll_response.json()["subscription_id"] == subscription_id

    update_response = api_client.patch(
        f"/api/wechat-mp/automation/subscriptions/{subscription_id}",
        json={"schedule_time": "20:30", "automatic_draft": False},
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["id"] == subscription_id
    assert updated["account_fakeid"] == "api-fakeid"
    assert updated["schedule_time"] == "20:30"
    assert updated["automatic_draft"] is False
    assert len(api_client.get("/api/wechat-mp/automation/subscriptions").json()) == 1
