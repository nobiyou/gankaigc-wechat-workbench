from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.settings import AIConfigCheckResult, AIConfigSummary, DomainPackSummary, PromptTemplateSummary
import app.api.settings as settings_api

client = TestClient(app)


def test_get_ai_config_returns_runtime_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        settings_api,
        "get_ai_config_summary",
        lambda: AIConfigSummary(
            api_key_configured=True,
            base_url="https://example.com/v1",
            model="test-model",
            image_model="test-image-model",
            reasoning_effort="medium",
            request_timeout_seconds=45.0,
        ),
    )

    response = client.get("/api/settings/ai-config")

    assert response.status_code == 200
    assert response.json() == {
        "api_key_configured": True,
        "base_url": "https://example.com/v1",
        "model": "test-model",
        "image_model": "test-image-model",
        "reasoning_effort": "medium",
        "request_timeout_seconds": 45.0,
    }


def test_post_ai_config_check_returns_live_check_result(monkeypatch) -> None:
    monkeypatch.setattr(
        settings_api,
        "run_ai_config_check",
        lambda: AIConfigCheckResult(
            ok=False,
            status="upstream_error",
            message="上游服务异常：temporary unavailable",
            checked_at="2026-05-21T10:00:00Z",
        ),
    )

    response = client.post("/api/settings/ai-config/check")

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "status": "upstream_error",
        "message": "上游服务异常：temporary unavailable",
        "checked_at": "2026-05-21T10:00:00Z",
    }


def test_get_domain_packs_returns_registered_options(monkeypatch) -> None:
    monkeypatch.setattr(
        settings_api,
        "list_domain_prompt_packs",
        lambda: [
            type(
                "Pack",
                (),
                {
                    "key": "women-growth",
                    "label": "女性情感成长",
                    "audience": "女性情感成长",
                    "voice": "语言要克制、真实、具体",
                    "constraints": "避免空泛口号、说教感和鸡汤腔",
                },
            )(),
            type(
                "Pack",
                (),
                {
                    "key": "workplace-growth",
                    "label": "职场成长",
                    "audience": "职场成长",
                    "voice": "语言要冷静、务实、直接",
                    "constraints": "避免抒情过度、泛心理化和悬浮表达",
                },
            )(),
        ],
    )
    monkeypatch.setattr(
        settings_api,
        "DEFAULT_DOMAIN_PROMPT_PACK",
        DomainPackSummary(
            key="women-growth",
            label="女性情感成长",
            audience="女性情感成长",
            voice="语言要克制、真实、具体",
            constraints="避免空泛口号、说教感和鸡汤腔",
            is_default=True,
        ),
    )

    response = client.get("/api/settings/domain-packs")

    assert response.status_code == 200
    assert response.json()[0]["key"] == "women-growth"
    assert response.json()[0]["is_default"] is True
    assert response.json()[1]["key"] == "workplace-growth"
    assert response.json()[1]["is_default"] is False


def test_get_prompt_templates_returns_registered_stage_summaries(monkeypatch) -> None:
    monkeypatch.setattr(
        settings_api,
        "list_prompt_template_summaries",
        lambda: [
            PromptTemplateSummary(
                key="topic",
                label="选题生成",
                role="选题编辑",
                objective="把热点或参考文章整理成可立项选题。",
                output_fields=["title", "angle"],
                supports_tone_profile=True,
                supports_domain_pack=True,
                supports_review_feedback=False,
            ),
            PromptTemplateSummary(
                key="draft",
                label="初稿生成",
                role="正文作者",
                objective="基于大纲扩写正文，并支持精修。",
                output_fields=["title", "body_markdown"],
                supports_tone_profile=True,
                supports_domain_pack=True,
                supports_review_feedback=True,
            ),
        ],
    )

    response = client.get("/api/settings/prompt-templates")

    assert response.status_code == 200
    assert response.json() == [
        {
            "key": "topic",
            "label": "选题生成",
            "role": "选题编辑",
            "objective": "把热点或参考文章整理成可立项选题。",
            "output_fields": ["title", "angle"],
            "supports_tone_profile": True,
            "supports_domain_pack": True,
            "supports_review_feedback": False,
        },
        {
            "key": "draft",
            "label": "初稿生成",
            "role": "正文作者",
            "objective": "基于大纲扩写正文，并支持精修。",
            "output_fields": ["title", "body_markdown"],
            "supports_tone_profile": True,
            "supports_domain_pack": True,
            "supports_review_feedback": True,
        },
    ]
