from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
import app.services.workbench as workbench
from app.services.wechat_mp_styles import BUILTIN_WECHAT_MP_HTML_STYLES, recommend_wechat_mp_html_style


client = TestClient(app)


def test_wechat_html_style_registry_exposes_all_builtin_styles_and_previews() -> None:
    response = client.get("/api/wechat-mp-html-styles")

    assert response.status_code == 200
    styles = response.json()
    assert len(styles) == len(BUILTIN_WECHAT_MP_HTML_STYLES) == 15
    assert styles[0]["key"] == "minimal"
    assert styles[0]["is_default"] is True
    assert all(item["is_builtin"] is True for item in styles)

    preview_response = client.get("/api/wechat-mp-html-styles/event/preview")

    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["key"] == "event"
    assert preview["name"] == "活动公告"
    assert preview["html"].startswith("<!doctype html>")
    assert '<body style="' in preview["html"]
    assert '<h2 style="' in preview["html"]


def test_wechat_html_style_management_keeps_one_active_default() -> None:
    disable_default = client.patch(
        "/api/wechat-mp-html-styles/minimal",
        json={"is_active": False},
    )

    assert disable_default.status_code == 200
    assert disable_default.json()["is_active"] is False

    styles_after_disable = client.get("/api/wechat-mp-html-styles").json()
    defaults_after_disable = [item for item in styles_after_disable if item["is_default"]]
    assert len(defaults_after_disable) == 1
    assert defaults_after_disable[0]["key"] == "medium"

    set_event_default = client.post("/api/wechat-mp-html-styles/event/default")

    assert set_event_default.status_code == 200
    assert set_event_default.json()["is_active"] is True
    assert set_event_default.json()["is_default"] is True

    styles_after_default = client.get("/api/wechat-mp-html-styles").json()
    assert [item["key"] for item in styles_after_default if item["is_default"]] == ["event"]


def test_smart_style_recommendation_uses_active_style_set() -> None:
    recommendation = recommend_wechat_mp_html_style(
        title="春季活动报名通知",
        body_markdown="本周开放报名，欢迎参加线下活动。",
        active_style_keys={"minimal", "event"},
        default_style_key="minimal",
    )

    assert recommendation.key == "event"
    assert recommendation.score > 0
    assert "活动" in recommendation.matched_terms

    with workbench._get_connection() as connection:
        project = connection.execute(
            """
            SELECT p.*, t.title AS topic_title, t.angle AS topic_angle
            FROM projects AS p
            LEFT JOIN topics AS t ON t.slug = p.topic_slug
            WHERE p.slug = ?
            """,
            ("office-burnout-recovery-weekly",),
        ).fetchone()

    assert project is not None
    selected, source, reason = workbench._resolve_wechat_mp_html_style_for_package(
        project=project,
        draft_title="活动报名通知",
        draft_body_markdown="本周开放报名，欢迎参加活动。",
        package_override=None,
    )

    assert selected.key == "event"
    assert source == "smart"
    assert "活动" in reason
