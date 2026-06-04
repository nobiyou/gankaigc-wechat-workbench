from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


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
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    captured: dict[str, object] = {}

    def fake_run_compare_mode(args):
        captured["base_url"] = os.environ.get("OPENAI_BASE_URL")
        captured["model"] = os.environ.get("OPENAI_MODEL")
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
            "--openai-model",
            "gpt-5-mini",
        ],
    )

    exit_code = script.main()

    assert exit_code == 0
    assert captured["base_url"] == ""
    assert captured["model"] == "gpt-5-mini"
    assert captured["args_model"] == "gpt-5-mini"


def test_run_live_ai_smoke_check_only_uses_overrides_before_backend_load(monkeypatch, capsys) -> None:
    script = _load_script_module(LIVE_SMOKE_SCRIPT_PATH, "run_live_ai_smoke_override_test")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_REQUEST_TIMEOUT_SECONDS", raising=False)

    class FakeSummary:
        def model_dump(self) -> dict[str, object]:
            return {
                "api_key_configured": True,
                "base_url": None,
                "model": "gpt-5-mini",
                "image_model": "gpt-image-2",
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
        assert os.environ.get("OPENAI_BASE_URL") == ""
        assert os.environ.get("OPENAI_MODEL") == "gpt-5-mini"
        assert os.environ.get("OPENAI_REQUEST_TIMEOUT_SECONDS") == "12.0"
        return {
            "settings": FakeSettings(),
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: FakeCheck(),
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(
        [
            "--check-only",
            "--clear-openai-base-url",
            "--openai-model",
            "gpt-5-mini",
            "--openai-request-timeout-seconds",
            "12",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ai_config"]["model"] == "gpt-5-mini"
    assert payload["check"]["status"] == "ok"


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
                "model": "gpt-5-mini",
                "image_model": "gpt-image-2",
                "reasoning_effort": "medium",
                "request_timeout_seconds": 12.0,
            }

    class FakeSettings:
        openai_api_key = "test-key"
        openai_model = "gpt-5-mini"
        openai_request_timeout_seconds = 12.0

    def fake_load_backend_bindings():
        return {
            "settings": FakeSettings(),
            "OpenAIWorkbenchGenerator": FakeGenerator,
            "TopicGenerationResult": FakeTopicGenerationResult,
            "get_ai_config_summary": lambda: FakeSummary(),
            "run_ai_config_check": lambda: None,
        }

    monkeypatch.setattr(script, "_load_backend_bindings", fake_load_backend_bindings)

    exit_code = script.main(["--probe-text-routes"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["routes"]["responses_create_text"]["ok"] is True
    assert payload["routes"]["responses_create_json_text"]["ok"] is True
    assert payload["routes"]["responses_parse_topic"]["ok"] is True
    assert payload["routes"]["chat_completions_json"]["ok"] is True
