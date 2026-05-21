from __future__ import annotations

import base64
import httpx
import openai

from app.core.settings import Settings
import app.services.ai_generator as ai_generator_module
from app.services.ai_generator import (
    DraftGenerationResult,
    OpenAIWorkbenchGenerator,
    OutlineGenerationResult,
    TopicGenerationResult,
)


def build_generator() -> OpenAIWorkbenchGenerator:
    return OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_model="test-model",
            openai_image_model="test-image-model",
        )
    )


def test_generate_outline_prompt_mentions_target_word_count(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(*, instructions: str, prompt: str, response_format):
        captured["instructions"] = instructions
        captured["prompt"] = prompt
        return OutlineGenerationResult(hook="hook", outline_body="1. a\n2. b")

    monkeypatch.setattr(generator, "_parse_response", fake_parse_response)

    generator.generate_outline(
        {
            "trend_title": "办公室倦怠修复",
            "topic_title": "办公室倦怠不是懒，是你的身心在报警",
            "topic_angle": "情绪识别",
            "project_title": "办公室倦怠修复周更",
            "tone_profile": {
                "name": "女性成长克制陪伴风",
                "opening_style": "从具体场景冷启动切入",
                "paragraph_rhythm": "短段落，慢推进",
                "closing_style": "留白式收束",
                "forbidden_phrases": ["你必须", "立刻改变"],
                "value_constraints": "不说教，不制造羞耻感，避免空泛鸡汤",
                "target_word_count": 1400,
            },
        }
    )

    assert "目标字数：1400" in captured["prompt"]
    assert "按目标字数规划篇幅" in captured["prompt"]
    assert "避免在大纲阶段写得过满" in captured["prompt"]


def test_generate_draft_prompt_mentions_target_word_count_with_tolerance(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(*, instructions: str, prompt: str, response_format):
        captured["instructions"] = instructions
        captured["prompt"] = prompt
        return DraftGenerationResult(title="title", body_markdown="# draft")

    monkeypatch.setattr(generator, "_parse_response", fake_parse_response)

    generator.generate_draft(
        {
            "trend_title": "办公室倦怠修复",
            "topic_title": "办公室倦怠不是懒，是你的身心在报警",
            "topic_angle": "情绪识别",
            "project_title": "办公室倦怠修复周更",
            "outline": {
                "hook": "先接住身体发出的报警",
                "outline_body": "1. 崩住的日常\n2. 被忽略的疲惫\n3. 慢慢恢复秩序",
            },
            "tone_profile": {
                "name": "女性成长克制陪伴风",
                "opening_style": "从具体场景冷启动切入",
                "paragraph_rhythm": "短段落，慢推进",
                "closing_style": "留白式收束",
                "forbidden_phrases": ["你必须", "立刻改变"],
                "value_constraints": "不说教，不制造羞耻感，避免空泛鸡汤",
                "target_word_count": 1400,
            },
        }
    )

    assert "目标字数：1400" in captured["prompt"]
    assert "上下浮动 10% 到 15%" in captured["prompt"]
    assert "如果明显超出目标字数" in captured["prompt"]


def test_generate_draft_prompt_includes_polish_instruction_and_existing_draft(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(*, instructions: str, prompt: str, response_format):
        captured["instructions"] = instructions
        captured["prompt"] = prompt
        return DraftGenerationResult(title="title", body_markdown="# polished")

    monkeypatch.setattr(generator, "_parse_response", fake_parse_response)

    generator.generate_draft(
        {
            "trend_title": "办公室倦怠修复",
            "topic_title": "办公室倦怠不是懒，是你的身心在报警",
            "topic_angle": "情绪识别",
            "project_title": "办公室倦怠修复周更",
            "outline": {
                "hook": "先接住身体发出的报警",
                "outline_body": "1. 崩住的日常\n2. 被忽略的疲惫\n3. 慢慢恢复秩序",
            },
            "tone_profile": {
                "name": "女性成长克制陪伴风",
                "opening_style": "从具体场景冷启动切入",
                "paragraph_rhythm": "短段落，慢推进",
                "closing_style": "留白式收束",
                "forbidden_phrases": ["你必须", "立刻改变"],
                "value_constraints": "不说教，不制造羞耻感，避免空泛鸡汤",
                "target_word_count": 1400,
            },
            "polish_instruction": "统一语气，提炼观点，结尾更克制。",
            "draft": {
                "title": "draft title",
                "body_markdown": "# draft\n\nbody",
            },
        }
    )

    assert "精修要求：统一语气，提炼观点，结尾更克制。" in captured["prompt"]
    assert "当前草稿标题：draft title" in captured["prompt"]
    assert "请基于现有草稿精修" in captured["prompt"]


def test_parse_response_retries_transient_openai_failures(monkeypatch) -> None:
    generator = build_generator()
    attempts = {"count": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                request = httpx.Request("POST", "https://example.com/v1/responses")
                response = httpx.Response(503, request=request, json={"error": {"message": "Service temporarily unavailable"}})
                raise openai.InternalServerError(
                    "Service temporarily unavailable",
                    response=response,
                    body={"error": {"message": "Service temporarily unavailable"}},
                )

            class FakeParsedResponse:
                output_parsed = TopicGenerationResult(
                    title="先照顾情绪，再谈关系修复",
                    angle="关系修复顺序",
                )

            return FakeParsedResponse()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())

    result = generator.generate_topic(
        {
            "trend_slug": "office-burnout-recovery",
            "trend_title": "办公室倦怠修复",
            "source": "xiaohongshu",
            "heat_score": 88,
            "status": "screening",
        }
    )

    assert result == {
        "title": "先照顾情绪，再谈关系修复",
        "angle": "关系修复顺序",
    }
    assert attempts["count"] == 2


def test_generate_topic_supports_tracked_article_payload(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(*, instructions: str, prompt: str, response_format):
        captured["instructions"] = instructions
        captured["prompt"] = prompt
        return TopicGenerationResult(
            title="先接住情绪，再重建关系里的安全感",
            angle="从参考文章提炼新的关系修复切口",
        )

    monkeypatch.setattr(generator, "_parse_response", fake_parse_response)

    result = generator.generate_topic(
        {
            "source_type": "tracked_article",
            "source_ref_slug": "wechat-mp-wechat-mp-2247538175-1",
            "source_name": "",
            "article_title": "听到伴侣说话就烦，不是你讨厌他，也不是你脾气不好，而是你忽略了这个危机",
            "author": "一凡一尘",
            "summary": "很多人认为对伴侣没耐心就是感情变淡了，其实并不全是对的。",
            "structure_notes": "Imported from WeChat MP article list; structure notes pending review.",
            "tags": ["wechat-mp"],
            "tone_profile": {
                "name": "女性成长克制陪伴风",
            },
        }
    )

    assert result == {
        "title": "先接住情绪，再重建关系里的安全感",
        "angle": "从参考文章提炼新的关系修复切口",
    }
    assert "基于参考文章提炼出一个可直接立项的女性情感成长类原创选题" in captured["instructions"]
    assert "参考文章标题：听到伴侣说话就烦" in captured["prompt"]
    assert "来源账号：未知公众号" in captured["prompt"]


def test_generator_passes_configured_timeout_to_openai_client(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self) -> None:
            self.responses = object()

    def fake_openai(**kwargs):
        captured.update(kwargs)
        return FakeClient()

    monkeypatch.setattr(ai_generator_module, "OpenAI", fake_openai)

    OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=45.0,
        )
    )

    assert captured["api_key"] == "test-key"
    assert captured["timeout"] == 45.0


def test_generate_cover_image_uses_low_quality_variant_first(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, object] = {}

    class FakeImages:
        def generate(self, **kwargs):
            captured.update(kwargs)

            class FakeImage:
                b64_json = base64.b64encode(b"fake-png-bytes").decode("utf-8")

            class FakeResponse:
                data = [FakeImage()]

            return FakeResponse()

    monkeypatch.setattr(generator._client, "images", FakeImages())

    result = generator.generate_cover_image(
        {
            "cover_prompt": "prompt",
        }
    )

    assert result == b"fake-png-bytes"
    assert captured["size"] == "1024x1024"
    assert captured["quality"] == "low"
    assert captured["output_format"] == "png"
    assert captured["timeout"] == 180.0


def test_generate_cover_image_retries_with_second_variant_after_timeout(monkeypatch) -> None:
    generator = build_generator()
    calls: list[dict[str, object]] = []

    class FakeImages:
        def generate(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/images"))

            class FakeImage:
                b64_json = base64.b64encode(b"second-variant").decode("utf-8")

            class FakeResponse:
                data = [FakeImage()]

            return FakeResponse()

    monkeypatch.setattr(generator._client, "images", FakeImages())

    result = generator.generate_cover_image(
        {
            "cover_prompt": "prompt",
        }
    )

    assert result == b"second-variant"
    assert len(calls) == 2
    assert calls[0]["size"] == "1024x1024"
    assert calls[0]["quality"] == "low"
    assert calls[0]["timeout"] == 180.0
    assert calls[1]["size"] == "1536x1024"
    assert calls[1]["quality"] == "low"
    assert calls[1]["timeout"] == 240.0
