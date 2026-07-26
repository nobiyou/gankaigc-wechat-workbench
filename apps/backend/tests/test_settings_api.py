from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.schemas.settings import AIConfigCheckResult, AIConfigSummary, AIImageRouteProbeItem, AIImageRouteProbeResult, DomainPackSummary, PromptTemplateSummary
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
            trust_env=False,
            image_model="test-image-model",
            image_api_key_configured=True,
            image_base_url="https://images.example.com/v1",
            image_request_timeout_seconds=90.0,
            image_generation_max_attempts=2,
            image_uses_dedicated_config=True,
            creative_quality_retry_max_attempts=1,
            allow_local_creative_fallbacks=False,
            image_fallback_route_configured=True,
            image_fallback_route_active=True,
            image_fallback_model="backup-image-model",
            image_fallback_base_url="https://backup-images.example.com/v1",
            image_fallback_effective_model="backup-image-model",
            image_fallback_effective_base_url="https://backup-images.example.com/v1",
            image_fallback_effective_request_timeout_seconds=75.0,
            image_fallback_effective_api_key_configured=True,
            image_fallback_uses_inherited_model=False,
            image_fallback_uses_inherited_api_key=True,
            image_fallback_uses_inherited_base_url=False,
            image_fallback_uses_inherited_request_timeout=True,
            image_fallback_route_difference_labels=["模型", "接口"],
            image_fallback_route_note="备用图片链路已生效；它与主出图链路的差异项：模型、接口。",
            image_fallback_route_recovery_actions=[
                "当前备用图片链路已经形成第二条图片 API；建议点一次“探测主/备路由”，确认它能独立返回图片。",
                "只有出图请求预算大于 1 时，正式出封面才会在主链路失败后尝试切到这条备用图片链路。",
            ],
            image_fallback_route_config_hints=[
                "OPENAI_IMAGE_FALLBACK_MODEL：已填写 backup-image-model",
                "OPENAI_IMAGE_FALLBACK_BASE_URL：已填写 https://backup-images.example.com/v1",
                "OPENAI_IMAGE_FALLBACK_API_KEY：未填写；当前会继承主出图链路 Key（已配置）",
                "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS：未填写；当前会继承主出图超时 90 秒",
            ],
            image_fallback_route_env_example=[
                "OPENAI_IMAGE_FALLBACK_MODEL=<与主出图不同的图片模型>",
                "OPENAI_IMAGE_FALLBACK_BASE_URL=<可选：独立图片接口；想绕开当前主链路账号池时优先填写>",
                "OPENAI_IMAGE_FALLBACK_API_KEY=<可选：独立图片 Key；想绕开当前主链路账号池时优先填写>",
                "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS=90",
            ],
            image_fallback_route_env_example_note=(
                "想让系统识别第二条图片 API，以上四项里只要有一项与主链路不同即可；"
                "但如果你是想绕开当前主出图账号池，优先单独提供 fallback Base URL 或 fallback Key。"
            ),
            image_fallback_account_pool_diagnosis_status="independent_hint",
            image_fallback_account_pool_diagnosis_label="更有机会绕开主账号池",
            image_fallback_account_pool_diagnosis_note="fallback 仍走主接口，但已经切到独立 Key；如果上游账号池按 Key 隔离，这条路由通常更有机会绕开主账号池。",
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
        "trust_env": False,
        "image_model": "test-image-model",
        "image_api_key_configured": True,
        "image_base_url": "https://images.example.com/v1",
        "image_request_timeout_seconds": 90.0,
        "image_generation_max_attempts": 2,
        "image_uses_dedicated_config": True,
        "creative_quality_retry_max_attempts": 1,
        "allow_local_creative_fallbacks": False,
        "image_fallback_route_configured": True,
        "image_fallback_route_active": True,
        "image_fallback_model": "backup-image-model",
        "image_fallback_base_url": "https://backup-images.example.com/v1",
        "image_fallback_effective_model": "backup-image-model",
        "image_fallback_effective_base_url": "https://backup-images.example.com/v1",
        "image_fallback_effective_request_timeout_seconds": 75.0,
        "image_fallback_effective_api_key_configured": True,
        "image_fallback_uses_inherited_model": False,
        "image_fallback_uses_inherited_api_key": True,
        "image_fallback_uses_inherited_base_url": False,
        "image_fallback_uses_inherited_request_timeout": True,
        "image_fallback_route_difference_labels": ["模型", "接口"],
        "image_fallback_route_note": "备用图片链路已生效；它与主出图链路的差异项：模型、接口。",
        "image_fallback_route_recovery_actions": [
            "当前备用图片链路已经形成第二条图片 API；建议点一次“探测主/备路由”，确认它能独立返回图片。",
            "只有出图请求预算大于 1 时，正式出封面才会在主链路失败后尝试切到这条备用图片链路。",
        ],
        "image_fallback_route_config_hints": [
            "OPENAI_IMAGE_FALLBACK_MODEL：已填写 backup-image-model",
            "OPENAI_IMAGE_FALLBACK_BASE_URL：已填写 https://backup-images.example.com/v1",
            "OPENAI_IMAGE_FALLBACK_API_KEY：未填写；当前会继承主出图链路 Key（已配置）",
            "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS：未填写；当前会继承主出图超时 90 秒",
        ],
        "image_fallback_route_env_example": [
            "OPENAI_IMAGE_FALLBACK_MODEL=<与主出图不同的图片模型>",
            "OPENAI_IMAGE_FALLBACK_BASE_URL=<可选：独立图片接口；想绕开当前主链路账号池时优先填写>",
            "OPENAI_IMAGE_FALLBACK_API_KEY=<可选：独立图片 Key；想绕开当前主链路账号池时优先填写>",
            "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS=90",
        ],
        "image_fallback_route_env_example_note": "想让系统识别第二条图片 API，以上四项里只要有一项与主链路不同即可；但如果你是想绕开当前主出图账号池，优先单独提供 fallback Base URL 或 fallback Key。",
        "image_fallback_account_pool_diagnosis_status": "independent_hint",
        "image_fallback_account_pool_diagnosis_label": "更有机会绕开主账号池",
        "image_fallback_account_pool_diagnosis_note": "fallback 仍走主接口，但已经切到独立 Key；如果上游账号池按 Key 隔离，这条路由通常更有机会绕开主账号池。",
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
        "route_label": None,
        "recovery_actions": [],
    }


def test_post_ai_image_config_check_returns_live_check_result(monkeypatch) -> None:
    monkeypatch.setattr(
        settings_api,
        "run_ai_image_config_check",
        lambda: AIConfigCheckResult(
            ok=False,
            status="upstream_error",
            message="图片上游服务异常：No available compatible accounts",
            checked_at="2026-05-21T10:00:00Z",
        ),
    )

    response = client.post("/api/settings/ai-config/check-image")

    assert response.status_code == 200
    assert response.json() == {
        "ok": False,
        "status": "upstream_error",
        "message": "图片上游服务异常：No available compatible accounts",
        "checked_at": "2026-05-21T10:00:00Z",
        "route_label": None,
        "recovery_actions": [],
    }


def test_post_ai_image_route_probe_returns_route_probe_result(monkeypatch) -> None:
    monkeypatch.setattr(
        settings_api,
        "run_ai_image_route_probe",
        lambda: AIImageRouteProbeResult(
            any_ok=True,
            checked_at="2026-07-17T10:00:00Z",
            routes=[
                AIImageRouteProbeItem(
                    route_label="primary",
                    configured_model="gpt-image-2",
                    configured_base_url="https://images.example.com/v1",
                    ok=True,
                    status="ok",
                    message="图片配置检测通过，当前图像模型可以正常返回图片。",
                    checked_at="2026-07-17T10:00:00Z",
                    recovery_actions=[],
                ),
                AIImageRouteProbeItem(
                    route_label="fallback",
                    configured_model="fallback-image-model",
                    configured_base_url="https://fallback-images.example.com/v1",
                    ok=False,
                    status="bad_request",
                    message='图片请求参数错误：images endpoint requires an image model, got "fallback-image-model"',
                    checked_at="2026-07-17T10:00:00Z",
                    recovery_actions=["这次报错发生在 fallback 路由，优先检查 OPENAI_IMAGE_FALLBACK_MODEL 是否真的是图片模型。"],
                ),
            ],
        ),
    )

    response = client.post("/api/settings/ai-config/probe-image-routes")

    assert response.status_code == 200
    assert response.json() == {
        "any_ok": True,
        "checked_at": "2026-07-17T10:00:00Z",
        "routes": [
            {
                "route_label": "primary",
                "configured_model": "gpt-image-2",
                "configured_base_url": "https://images.example.com/v1",
                "ok": True,
                "status": "ok",
                "message": "图片配置检测通过，当前图像模型可以正常返回图片。",
                "checked_at": "2026-07-17T10:00:00Z",
                "recovery_actions": [],
            },
            {
                "route_label": "fallback",
                "configured_model": "fallback-image-model",
                "configured_base_url": "https://fallback-images.example.com/v1",
                "ok": False,
                "status": "bad_request",
                "message": '图片请求参数错误：images endpoint requires an image model, got "fallback-image-model"',
                "checked_at": "2026-07-17T10:00:00Z",
                "recovery_actions": ["这次报错发生在 fallback 路由，优先检查 OPENAI_IMAGE_FALLBACK_MODEL 是否真的是图片模型。"],
            },
        ],
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
                objective="基于大纲扩写正文，并支持原创增强精修。",
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
            "objective": "基于大纲扩写正文，并支持原创增强精修。",
            "output_fields": ["title", "body_markdown"],
            "supports_tone_profile": True,
            "supports_domain_pack": True,
            "supports_review_feedback": True,
        },
    ]
