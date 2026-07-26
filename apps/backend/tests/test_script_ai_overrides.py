from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[3]
ORIGINALITY_SCRIPT_PATH = REPO_ROOT / "scripts" / "run_originality_case.py"
LIVE_SMOKE_SCRIPT_PATH = REPO_ROOT / "scripts" / "run_live_ai_smoke.py"


def _load_script_module(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_originality_case_main_applies_ai_override_before_dispatch(monkeypatch) -> None:
    script = _load_script_module(ORIGINALITY_SCRIPT_PATH, "run_originality_case_override_test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_ALLOW_LOCAL_CREATIVE_FALLBACKS", raising=False)
    monkeypatch.delenv("OPENAI_CREATIVE_QUALITY_RETRY_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_GENERATION_MAX_ATTEMPTS", raising=False)
    captured: dict[str, object] = {}

    def fake_run_compare_mode(args):
        captured["base_url"] = os.environ.get("OPENAI_BASE_URL")
        captured["image_base_url"] = os.environ.get("OPENAI_IMAGE_BASE_URL")
        captured["image_fallback_base_url"] = os.environ.get("OPENAI_IMAGE_FALLBACK_BASE_URL")
        captured["model"] = os.environ.get("OPENAI_MODEL")
        captured["local_fallbacks"] = os.environ.get("OPENAI_ALLOW_LOCAL_CREATIVE_FALLBACKS")
        captured["quality_retry_attempts"] = os.environ.get("OPENAI_CREATIVE_QUALITY_RETRY_MAX_ATTEMPTS")
        captured["image_attempts"] = os.environ.get("OPENAI_IMAGE_GENERATION_MAX_ATTEMPTS")
        captured["args_model"] = args.openai_model
        return 0

    monkeypatch.setattr(script, "_run_compare_mode", fake_run_compare_mode)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(ORIGINALITY_SCRIPT_PATH),
            "--compare-source-file",
            "source.md",
            "--compare-draft-file",
            "draft.md",
            "--clear-openai-base-url",
            "--clear-openai-image-base-url",
            "--clear-openai-image-fallback-base-url",
            "--openai-model",
            "gpt-5.4-mini",
            "--openai-allow-local-creative-fallbacks",
            "false",
            "--openai-creative-quality-retry-max-attempts",
            "1",
            "--openai-image-generation-max-attempts",
            "1",
        ],
    )

    exit_code = script.main()

    assert exit_code == 0
    assert captured["base_url"] == "https://api.openai.com/v1"
    assert captured["image_base_url"] == ""
    assert captured["image_fallback_base_url"] == ""
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["local_fallbacks"] == "false"
    assert captured["quality_retry_attempts"] == "1"
    assert captured["image_attempts"] == "1"
    assert captured["args_model"] == "gpt-5.4-mini"


def test_run_originality_case_summary_only_reports_runtime_summary_without_pipeline_work(monkeypatch, capsys) -> None:
    script = _load_script_module(ORIGINALITY_SCRIPT_PATH, "run_originality_case_summary_test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_FALLBACK_BASE_URL", raising=False)

    def fake_collect_ai_config_summary_payload():
        assert os.environ.get("OPENAI_BASE_URL") == "https://api.openai.com/v1"
        assert os.environ.get("OPENAI_IMAGE_BASE_URL") == ""
        assert os.environ.get("OPENAI_IMAGE_FALLBACK_BASE_URL") == ""
        return {
            "ai_config": {
                "api_key_configured": True,
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-5.4-mini",
                "trust_env": False,
                "image_model": "gpt-image-2",
                "image_api_key_configured": True,
                "image_base_url": "https://api.openai.com/v1",
                "image_request_timeout_seconds": 12.0,
                "image_uses_dedicated_config": False,
                "image_fallback_route_configured": False,
                "image_fallback_route_active": False,
                "image_fallback_model": None,
                "image_fallback_base_url": None,
                "image_fallback_route_difference_labels": [],
                "image_fallback_route_note": "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。",
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }
        }

    monkeypatch.setattr(script, "_collect_ai_config_summary_payload", fake_collect_ai_config_summary_payload)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(ORIGINALITY_SCRIPT_PATH),
            "--summary-only",
            "--clear-openai-base-url",
            "--clear-openai-image-base-url",
            "--clear-openai-image-fallback-base-url",
        ],
    )

    exit_code = script.main()

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ai_config"]["base_url"] == "https://api.openai.com/v1"
    assert payload["ai_config"]["image_base_url"] == "https://api.openai.com/v1"
    assert payload["ai_config"]["image_fallback_route_note"] == "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。"


def test_run_live_ai_smoke_check_only_uses_overrides_before_backend_load(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_override_test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_REQUEST_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("OPENAI_ALLOW_LOCAL_CREATIVE_FALLBACKS", raising=False)
    monkeypatch.delenv("OPENAI_CREATIVE_QUALITY_RETRY_MAX_ATTEMPTS", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_GENERATION_MAX_ATTEMPTS", raising=False)

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": None,
                "model": "gpt-5.4-mini",
                "image_model": "gpt-image-2",
                "image_api_key_configured": True,
                "image_base_url": None,
                "image_request_timeout_seconds": 12.0,
                "image_uses_dedicated_config": False,
                "image_fallback_route_configured": False,
                "image_fallback_route_active": False,
                "image_fallback_model": None,
                "image_fallback_base_url": None,
                "image_fallback_route_difference_labels": [],
                "image_fallback_route_note": "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。",
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }

    class FakeCheck:
        ok = True

        def model_dump(self) -> dict[str, object]:
            return {
                "ok": True,
                "status": "ok",
                "message": "AI 配置检测通过，当前文本模型可以正常响应。",
                "checked_at": "2026-06-03T00:00:00Z",
            }

    class FakeSettings:
        openai_api_key = "test-key"

    def fake_load_backend_bindings():
        assert os.environ.get("OPENAI_BASE_URL") == "https://api.openai.com/v1"
        assert os.environ.get("OPENAI_IMAGE_BASE_URL") == ""
        assert os.environ.get("OPENAI_IMAGE_FALLBACK_BASE_URL") == ""
        assert os.environ.get("OPENAI_MODEL") == "gpt-5.4-mini"
        assert os.environ.get("OPENAI_REQUEST_TIMEOUT_SECONDS") == "12.0"
        assert os.environ.get("OPENAI_ALLOW_LOCAL_CREATIVE_FALLBACKS") == "false"
        assert os.environ.get("OPENAI_CREATIVE_QUALITY_RETRY_MAX_ATTEMPTS") == "1"
        assert os.environ.get("OPENAI_IMAGE_GENERATION_MAX_ATTEMPTS") == "1"
        return {
            "settings": FakeSettings(),
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: FakeCheck(),
            "run_ai_image_config_check": lambda: FakeCheck(),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(
        [
            "--check-only",
            "--clear-openai-base-url",
            "--clear-openai-image-base-url",
            "--clear-openai-image-fallback-base-url",
            "--openai-model",
            "gpt-5.4-mini",
            "--openai-request-timeout-seconds",
            "12",
            "--openai-allow-local-creative-fallbacks",
            "false",
            "--openai-creative-quality-retry-max-attempts",
            "1",
            "--openai-image-generation-max-attempts",
            "1",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ai_config"]["model"] == "gpt-5.4-mini"
    assert payload["check"]["status"] == "ok"
    assert payload["image_check"]["status"] == "ok"


def test_run_live_ai_smoke_runtime_path_overrides_apply_before_backend_load(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_runtime_path_override_test")
    monkeypatch.delenv("DB_PATH", raising=False)
    monkeypatch.delenv("GENERATED_ASSETS_DIR", raising=False)

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": None,
                "model": "gpt-5.4-mini",
            }

    class FakeCheck:
        ok = True

        def model_dump(self) -> dict[str, object]:
            return {
                "ok": True,
                "status": "ok",
                "message": "AI 配置检测通过。",
                "checked_at": "2026-07-17T00:00:00Z",
            }

    class FakeSettings:
        openai_api_key = "test-key"

    def fake_load_backend_bindings():
        assert os.environ.get("DB_PATH") == "E:/tmp/smoke/live.db"
        assert os.environ.get("GENERATED_ASSETS_DIR") == "E:/tmp/smoke/assets"
        return {
            "settings": FakeSettings(),
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: FakeCheck(),
            "run_ai_image_config_check": lambda: FakeCheck(),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(
        [
            "--check-only",
            "--db-path",
            "E:/tmp/smoke/live.db",
            "--generated-assets-dir",
            "E:/tmp/smoke/assets",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["check"]["status"] == "ok"
    assert payload["image_check"]["status"] == "ok"


def test_run_live_ai_smoke_quiets_backend_loggers_by_default(monkeypatch) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_log_level_test")
    workbench_logger = script.logging.getLogger("app.services.workbench")
    ai_generator_logger = script.logging.getLogger("app.services.ai_generator")
    original_levels = (workbench_logger.level, ai_generator_logger.level)

    try:
        workbench_logger.setLevel(script.logging.NOTSET)
        ai_generator_logger.setLevel(script.logging.NOTSET)

        script._configure_backend_log_verbosity(SimpleNamespace(verbose_backend_logs=False))

        assert workbench_logger.level == script.logging.ERROR
        assert ai_generator_logger.level == script.logging.ERROR
    finally:
        workbench_logger.setLevel(original_levels[0])
        ai_generator_logger.setLevel(original_levels[1])


def test_run_live_ai_smoke_check_image_only_skips_text_check(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_check_image_only_test")

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-5.4-mini",
                "trust_env": False,
                "image_model": "gpt-image-2",
                "image_api_key_configured": True,
                "image_base_url": "https://api.openai.com/v1",
                "image_request_timeout_seconds": 12.0,
                "image_uses_dedicated_config": False,
                "image_fallback_route_configured": False,
                "image_fallback_route_active": False,
                "image_fallback_model": None,
                "image_fallback_base_url": None,
                "image_fallback_route_difference_labels": [],
                "image_fallback_route_note": "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。",
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }

    class FakeCheck:
        ok = True

        def model_dump(self) -> dict[str, object]:
            return {
                "ok": True,
                "status": "ok",
                "message": "图片配置检测通过，当前图像模型可以正常返回图片。",
                "checked_at": "2026-06-03T00:00:00Z",
                "route_label": "primary",
                "recovery_actions": [],
            }

    class FakeSettings:
        openai_api_key = "test-key"

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: (_ for _ in ()).throw(AssertionError("text check should not run")),
            "run_ai_image_config_check": lambda: FakeCheck(),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(["--check-image-only"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert "check" not in payload
    assert payload["image_check"]["status"] == "ok"


def test_run_live_ai_smoke_check_text_only_skips_image_check(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_check_text_only_test")

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-5.4-mini",
                "trust_env": False,
                "image_model": "gpt-image-2",
                "image_api_key_configured": True,
                "image_base_url": "https://api.openai.com/v1",
                "image_request_timeout_seconds": 12.0,
                "image_uses_dedicated_config": False,
                "image_fallback_route_configured": False,
                "image_fallback_route_active": False,
                "image_fallback_model": None,
                "image_fallback_base_url": None,
                "image_fallback_route_difference_labels": [],
                "image_fallback_route_note": "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。",
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }

    class FakeCheck:
        ok = True

        def model_dump(self) -> dict[str, object]:
            return {
                "ok": True,
                "status": "ok",
                "message": "AI 配置检测通过，当前文本模型可以正常响应。",
                "checked_at": "2026-06-03T00:00:00Z",
                "route_label": None,
                "recovery_actions": [],
            }

    class FakeSettings:
        openai_api_key = "test-key"

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: FakeCheck(),
            "run_ai_image_config_check": lambda: (_ for _ in ()).throw(AssertionError("image check should not run")),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(["--check-text-only"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["check"]["status"] == "ok"
    assert "image_check" not in payload


def test_run_live_ai_smoke_summary_only_reports_runtime_summary_without_network_calls(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_summary_test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_IMAGE_FALLBACK_BASE_URL", raising=False)

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-5.4-mini",
                "trust_env": False,
                "image_model": "gpt-image-2",
                "image_api_key_configured": True,
                "image_base_url": "https://api.openai.com/v1",
                "image_request_timeout_seconds": 12.0,
                "image_uses_dedicated_config": False,
                "image_fallback_route_configured": False,
                "image_fallback_route_active": False,
                "image_fallback_model": None,
                "image_fallback_base_url": None,
                "image_fallback_route_difference_labels": [],
                "image_fallback_route_note": "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。",
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }

    class FakeSettings:
        openai_api_key = "test-key"

    def fake_load_backend_bindings():
        assert os.environ.get("OPENAI_BASE_URL") == "https://api.openai.com/v1"
        assert os.environ.get("OPENAI_IMAGE_BASE_URL") == ""
        assert os.environ.get("OPENAI_IMAGE_FALLBACK_BASE_URL") == ""
        return {
            "settings": FakeSettings(),
            "get_ai_config_summary": lambda: FakeSummary(),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(
        [
            "--summary-only",
            "--clear-openai-base-url",
            "--clear-openai-image-base-url",
            "--clear-openai-image-fallback-base-url",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "ai_config": {
            "api_key_configured": True,
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-5.4-mini",
            "trust_env": False,
            "image_model": "gpt-image-2",
            "image_api_key_configured": True,
            "image_base_url": "https://api.openai.com/v1",
            "image_request_timeout_seconds": 12.0,
            "image_uses_dedicated_config": False,
            "image_fallback_route_configured": False,
            "image_fallback_route_active": False,
            "image_fallback_model": None,
            "image_fallback_base_url": None,
            "image_fallback_route_difference_labels": [],
            "image_fallback_route_note": "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。",
            "reasoning_effort": "medium",
            "request_timeout_seconds": 12.0,
        }
    }


def test_run_live_ai_smoke_probe_text_routes_reports_route_results(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_probe_test")

    class FakeResponses:
        def create(self, **kwargs):
            if kwargs.get("input") == "Reply with exactly OK.":
                class FakeResponse:
                    output_text = "OK"

                return FakeResponse()

            class FakeJsonResponse:
                output_text = '{"title":"ok","angle":"ok"}'

            return FakeJsonResponse()

        def parse(self, **kwargs):
            class FakeParsedResponse:
                output_parsed = FakeTopicGenerationResult(title="ok", angle="ok")
                output_text = '{"title":"ok","angle":"ok"}'

            return FakeParsedResponse()

    class FakeChatCompletions:
        def create(self, **kwargs):
            class FakeMessage:
                content = '{"title":"ok","angle":"ok"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    class FakeClient:
        responses = FakeResponses()
        chat = FakeChat()

    class FakeGenerator:
        def __init__(self, _settings) -> None:
            self._client = FakeClient()

    class FakeTopicGenerationResult:
        def __init__(self, title: str, angle: str) -> None:
            self.title = title
            self.angle = angle

        def model_dump(self) -> dict[str, str]:
            return {"title": self.title, "angle": self.angle}

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://proxy.example/v1",
                "model": "gpt-5.4-mini",
                "image_model": "gpt-image-2",
                "image_api_key_configured": True,
                "image_base_url": "https://proxy.example/v1",
                "image_request_timeout_seconds": 12.0,
                "image_uses_dedicated_config": False,
                "image_fallback_route_configured": False,
                "image_fallback_route_active": False,
                "image_fallback_model": None,
                "image_fallback_base_url": None,
                "image_fallback_route_difference_labels": [],
                "image_fallback_route_note": "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。",
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }

    class FakeSettings:
        openai_api_key = "test-key"
        openai_model = "gpt-5.4-mini"
        openai_request_timeout_seconds = 12.0

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "OpenAIWorkbenchGenerator": FakeGenerator,
            "TopicGenerationResult": FakeTopicGenerationResult,
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: None,
            "run_ai_image_config_check": lambda: None,
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(["--probe-text-routes"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["routes"]["responses_create_text"]["ok"] is True
    assert payload["routes"]["responses_create_json_text"]["ok"] is True
    assert payload["routes"]["responses_parse_topic"]["ok"] is True
    assert payload["routes"]["chat_completions_json"]["ok"] is True


def test_run_live_ai_smoke_probe_image_routes_reports_each_route(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_probe_image_test")

    class FakeGenerator:
        def __init__(self, _settings) -> None:
            self._image_routes = [
                {"label": "primary", "model": "primary-image-model", "base_url": "https://primary.example/v1"},
                {"label": "fallback", "model": "fallback-image-model", "base_url": "https://fallback.example/v1"},
            ]

        def _generate_cover_image_with_route(self, prompt: str):
            assert "16:9" in prompt
            only_route = self._image_routes[0]
            if only_route["label"] == "primary":
                raise RuntimeError("primary image route unavailable")
            return (b"fallback-cover", "fallback")

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://proxy.example/v1",
                "model": "gpt-5.4-mini",
                "image_model": "primary-image-model",
                "image_api_key_configured": True,
                "image_base_url": "https://primary.example/v1",
                "image_request_timeout_seconds": 12.0,
                "image_uses_dedicated_config": True,
                "image_fallback_route_configured": True,
                "image_fallback_route_active": True,
                "image_fallback_model": "fallback-image-model",
                "image_fallback_base_url": "https://fallback.example/v1",
                "image_fallback_route_difference_labels": ["模型", "接口"],
                "image_fallback_route_note": "备用图片链路已生效；它与主出图链路的差异项：模型、接口。",
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }

    class FakeSettings:
        openai_api_key = "test-key"

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "OpenAIWorkbenchGenerator": FakeGenerator,
            "TopicGenerationResult": object,
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: None,
            "run_ai_image_config_check": lambda: None,
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(["--probe-image-routes"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["routes"]["primary"]["ok"] is False
    assert payload["routes"]["primary"]["configured_model"] == "primary-image-model"
    assert payload["routes"]["fallback"]["ok"] is True
    assert payload["routes"]["fallback"]["used_route_label"] == "fallback"
    assert payload["routes"]["fallback"]["byte_length"] == len(b"fallback-cover")


def test_run_live_ai_smoke_assets_only_stops_after_assets(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_assets_only_test")
    calls: list[tuple[str, object]] = []

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://proxy.example/v1",
                "model": "gpt-5.4-mini",
            }

    class FakeRecord:
        def __init__(self, payload: dict[str, object], *, slug: str | None = None) -> None:
            self._payload = payload
            if slug is not None:
                self.slug = slug
            self.title = str(payload.get("title") or "")

        def model_dump(self) -> dict[str, object]:
            return self._payload

    class FakeDraft:
        project_slug = "topic-live-project"
        version = 2
        title = "draft title"
        word_count = 888

    class FakeAssets:
        project_slug = "topic-live-project"
        version = 3
        title_options = ["title-a", "title-b"]
        cover_copy = "cover copy"
        cover_image_url = "/generated-assets/topic-live-project-cover.png"
        cover_image_route_label = "primary"
        cover_image_route_model = "gpt-image-2"
        cover_image_route_base_url = "https://primary.example/v1"

    class FakeProjectCreate:
        def __init__(self, slug: str, title: str, owner: str, preferred_tone_profile_id: object) -> None:
            self.slug = slug
            self.title = title
            self.owner = owner
            self.preferred_tone_profile_id = preferred_tone_profile_id

    class FakeSettings:
        openai_api_key = "test-key"

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "ProjectCreate": FakeProjectCreate,
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: None,
            "run_ai_image_config_check": lambda: None,
            "initialize_store": lambda reset=True: calls.append(("initialize_store", reset)),
            "generate_topic_from_trend": lambda slug: FakeRecord({"slug": slug, "title": "topic title"}, slug=slug),
            "create_project_from_topic": lambda _topic_slug, project_create: FakeRecord(
                {"slug": project_create.slug, "title": project_create.title, "owner": project_create.owner},
                slug=project_create.slug,
            ),
            "generate_outline": lambda _project_slug: FakeRecord({"hook": "hook", "outline_body": "1. a\n2. b"}),
            "generate_draft": lambda _project_slug: FakeDraft(),
            "generate_assets": lambda _project_slug: FakeAssets(),
            "build_publish_package": lambda _project_slug: (_ for _ in ()).throw(
                AssertionError("publish package should not run in --assets-only mode")
            ),
            "get_project_detail": lambda _project_slug: (_ for _ in ()).throw(
                AssertionError("project detail should not run in --assets-only mode")
            ),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(["--assets-only"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["topic"]["slug"] == "office-burnout-recovery"
    assert payload["project"]["slug"] == "office-burnout-recovery-live-project"
    assert payload["assets"]["cover_image_url"] == "/generated-assets/topic-live-project-cover.png"
    assert payload["assets"]["cover_image_route_label"] == "primary"
    assert payload["assets"]["cover_image_route_model"] == "gpt-image-2"
    assert payload["assets"]["cover_image_route_base_url"] == "https://primary.example/v1"
    assert "publish_package" not in payload
    assert "detail" not in payload


def test_run_live_ai_smoke_surfaces_structured_stage_error_for_assets(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_stage_error_test")

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://proxy.example/v1",
                "model": "gpt-5.4-mini",
            }

    class FakeRecord:
        def __init__(self, payload: dict[str, object], *, slug: str | None = None) -> None:
            self._payload = payload
            if slug is not None:
                self.slug = slug
            self.title = str(payload.get("title") or "")

        def model_dump(self) -> dict[str, object]:
            return self._payload

    class FakeDraft:
        project_slug = "topic-live-project"
        version = 2
        title = "draft title"
        word_count = 888

    class FakeProjectCreate:
        def __init__(self, slug: str, title: str, owner: str, preferred_tone_profile_id: object) -> None:
            self.slug = slug
            self.title = title
            self.owner = owner
            self.preferred_tone_profile_id = preferred_tone_profile_id

    class FakeStageError(Exception):
        def __init__(self) -> None:
            super().__init__("cover provider failed")
            self.status_code = 502
            self.detail = "封面生成失败：当前封面保持 API-only，不会改走本地兜底。"

    class FakeSettings:
        openai_api_key = "test-key"

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "ProjectCreate": FakeProjectCreate,
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: None,
            "run_ai_image_config_check": lambda: None,
            "initialize_store": lambda reset=True: None,
            "generate_topic_from_trend": lambda slug: FakeRecord({"slug": slug, "title": "topic title"}, slug=slug),
            "create_project_from_topic": lambda _topic_slug, project_create: FakeRecord(
                {"slug": project_create.slug, "title": project_create.title, "owner": project_create.owner},
                slug=project_create.slug,
            ),
            "generate_outline": lambda _project_slug: FakeRecord({"hook": "hook", "outline_body": "1. a\n2. b"}),
            "generate_draft": lambda _project_slug: FakeDraft(),
            "generate_assets": lambda _project_slug: (_ for _ in ()).throw(FakeStageError()),
            "build_publish_package": lambda _project_slug: (_ for _ in ()).throw(
                AssertionError("publish package should not run after assets failure")
            ),
            "get_project_detail": lambda _project_slug: (_ for _ in ()).throw(
                AssertionError("project detail should not run after assets failure")
            ),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(["--assets-only"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage_error"]["stage"] == "generate_assets"
    assert payload["stage_error"]["error"]["type"] == "FakeStageError"
    assert payload["stage_error"]["error"]["status_code"] == 502
    assert payload["stage_error"]["error"]["detail"] == "封面生成失败：当前封面保持 API-only，不会改走本地兜底。"
    assert payload["draft"]["title"] == "draft title"
    assert "assets" not in payload


def test_run_live_ai_smoke_surfaces_structured_stage_error_for_topic_generation(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_topic_stage_error_test")

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://proxy.example/v1",
                "model": "gpt-5.4-mini",
            }

    class FakeStageError(Exception):
        def __init__(self) -> None:
            super().__init__("topic provider failed")
            self.status_code = 503
            self.detail = "话题生成失败：上游暂时不可用。"

    class FakeProjectCreate:
        def __init__(self, slug: str, title: str, owner: str, preferred_tone_profile_id: object) -> None:
            self.slug = slug
            self.title = title
            self.owner = owner
            self.preferred_tone_profile_id = preferred_tone_profile_id

    class FakeSettings:
        openai_api_key = "test-key"

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "ProjectCreate": FakeProjectCreate,
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: None,
            "run_ai_image_config_check": lambda: None,
            "initialize_store": lambda reset=True: None,
            "generate_topic_from_trend": lambda _slug: (_ for _ in ()).throw(FakeStageError()),
            "create_project_from_topic": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("project creation should not run after topic failure")
            ),
            "generate_outline": lambda _project_slug: (_ for _ in ()).throw(
                AssertionError("outline should not run after topic failure")
            ),
            "generate_draft": lambda _project_slug: (_ for _ in ()).throw(
                AssertionError("draft should not run after topic failure")
            ),
            "generate_assets": lambda _project_slug: (_ for _ in ()).throw(
                AssertionError("assets should not run after topic failure")
            ),
            "build_publish_package": lambda _project_slug: (_ for _ in ()).throw(
                AssertionError("publish package should not run after topic failure")
            ),
            "get_project_detail": lambda _project_slug: (_ for _ in ()).throw(
                AssertionError("project detail should not run after topic failure")
            ),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(["--assets-only"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage_error"]["stage"] == "generate_topic_from_trend"
    assert payload["stage_error"]["error"]["status_code"] == 503
    assert payload["stage_error"]["error"]["detail"] == "话题生成失败：上游暂时不可用。"
    assert "topic" not in payload


def test_run_live_ai_smoke_cover_regeneration_only_hits_business_cover_path(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_cover_regeneration_only_test")
    captured: dict[str, object] = {}

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://proxy.example/v1",
                "model": "gpt-5.4-mini",
            }

    class FakeAsset:
        project_slug = "api-only-cover-regeneration-live-project"
        draft_version = 1
        version = 2
        cover_prompt = "16:9 横版公众号封面，真实家庭夜晚场景。"
        cover_copy = "把家稳住的人，也该有人给他留一盏灯。"
        cover_image_path = "E:/tmp/gankaigc-live-smoke/cover-v2.png"
        cover_image_url = "/generated-assets/cover-v2.png"
        cover_image_route_label = "fallback"
        cover_image_route_model = "fallback-image-model"
        cover_image_route_base_url = "https://fallback-image.example/v1"
        origin = "cover_regeneration"

    class FakeSettings:
        openai_api_key = "test-key"
        db_path = "E:/tmp/gankaigc-live-smoke/live.db"

    def fake_seed_cover_regeneration_smoke_project(*, settings: object, project_slug: str, owner: str) -> None:
        captured["seed"] = {
            "db_path": getattr(settings, "db_path"),
            "project_slug": project_slug,
            "owner": owner,
        }

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: None,
            "run_ai_image_config_check": lambda: None,
            "initialize_store": lambda reset=True: captured.setdefault("initialize_store", reset),
            "regenerate_cover_image": lambda project_slug: (
                captured.setdefault("regenerate_cover_image", project_slug),
                FakeAsset(),
            )[1],
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)
    monkeypatch.setattr(script, "_seed_cover_regeneration_smoke_project", fake_seed_cover_regeneration_smoke_project)

    exit_code = script.main(["--cover-regeneration-only"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert captured["seed"] == {
        "db_path": "E:/tmp/gankaigc-live-smoke/live.db",
        "project_slug": "api-only-cover-regeneration-live-project",
        "owner": "live-smoke",
    }
    assert captured["regenerate_cover_image"] == "api-only-cover-regeneration-live-project"
    assert payload["cover_regeneration"]["origin"] == "cover_regeneration"
    assert payload["cover_regeneration"]["cover_image_url"] == "/generated-assets/cover-v2.png"
    assert payload["cover_regeneration"]["cover_image_route_label"] == "fallback"
    assert payload["cover_regeneration"]["cover_image_route_model"] == "fallback-image-model"
    assert payload["cover_regeneration"]["cover_image_route_base_url"] == "https://fallback-image.example/v1"


def test_run_live_ai_smoke_cover_regeneration_only_surfaces_route_info_in_stage_error(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_cover_regeneration_only_error_test")

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": "https://proxy.example/v1",
                "model": "gpt-5.4-mini",
            }

    class FakeStageError(Exception):
        def __init__(self) -> None:
            super().__init__("cover provider failed")
            self.status_code = 502
            self.detail = "封面生成失败：当前封面保持 API-only，不会改走本地兜底。"
            self.cover_image_route_label = "primary"
            self.cover_image_route_model = "gpt-image-2"
            self.cover_image_route_base_url = "https://primary.example/v1"

    class FakeSettings:
        openai_api_key = "test-key"
        db_path = "E:/tmp/gankaigc-live-smoke/live.db"

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: None,
            "run_ai_image_config_check": lambda: None,
            "initialize_store": lambda reset=True: None,
            "regenerate_cover_image": lambda _project_slug: (_ for _ in ()).throw(FakeStageError()),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)
    monkeypatch.setattr(script, "_seed_cover_regeneration_smoke_project", lambda **_kwargs: None)

    exit_code = script.main(["--cover-regeneration-only"])

    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage_error"]["stage"] == "regenerate_cover_image"
    assert payload["stage_error"]["error"]["status_code"] == 502
    assert payload["stage_error"]["error"]["cover_image_route_label"] == "primary"
    assert payload["stage_error"]["error"]["cover_image_route_model"] == "gpt-image-2"
    assert payload["stage_error"]["error"]["cover_image_route_base_url"] == "https://primary.example/v1"
