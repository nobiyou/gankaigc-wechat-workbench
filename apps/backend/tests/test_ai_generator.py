from __future__ import annotations

import base64
import httpx
import openai
import pytest

from app.core.settings import Settings
import app.services.ai_generator as ai_generator_module
from app.services.ai_generator import (
    DraftGenerationResult,
    OpenAIWorkbenchGenerator,
    OutlineGenerationResult,
    TrackedArticleMetadataGenerationResult,
    TopicGenerationResult,
    get_ai_config_summary,
    run_ai_config_check,
)


def build_generator() -> OpenAIWorkbenchGenerator:
    return OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="",
            openai_model="test-model",
            openai_image_model="test-image-model",
        )
    )


def build_custom_base_url_generator() -> OpenAIWorkbenchGenerator:
    return OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
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
                "default_polish_instruction": "重写开头和结尾，打散重复句式。",
            },
        }
    )

    assert "目标字数：1400" in captured["prompt"]
    assert "按目标字数规划篇幅" in captured["prompt"]
    assert "避免在大纲阶段写得过满" in captured["prompt"]
    assert "风格档案：女性成长克制陪伴风" in captured["prompt"]
    assert "开篇方式：从具体场景冷启动切入" in captured["prompt"]
    assert "禁用表达：你必须 / 立刻改变" in captured["prompt"]
    assert "先设计一个具体、可感知的开篇瞬间或动作入口" in captured["instructions"]
    assert "结尾要回到人物处境或心绪余波" in captured["instructions"]


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
                "default_polish_instruction": "重写开头和结尾，打散重复句式。",
            },
        }
    )

    assert "目标字数：1400" in captured["prompt"]
    assert "上下浮动 10% 到 15%" in captured["prompt"]
    assert "如果明显超出目标字数" in captured["prompt"]
    assert "段落节奏：短段落，慢推进" in captured["prompt"]
    assert "收束方式：留白式收束" in captured["prompt"]
    assert "价值约束：不说教，不制造羞耻感，避免空泛鸡汤" in captured["prompt"]
    assert "原创不是把现成观点换一批近义词，而是重新建立观察路径、场景重心和句子节奏" in captured["instructions"]
    assert "优先从一个具体、可感知的瞬间起笔" in captured["instructions"]
    assert "不要先复述题眼或给观点下定义" in captured["instructions"]
    assert "把抽象情绪落到动作停顿、物件光线、空间距离或身体反应上" in captured["instructions"]
    assert "避免每段都写成“观点句 + 解释句”" in captured["instructions"]
    assert "避免反复用“一点、一下、一些、一个、一种”去切分感受和动作" in captured["instructions"]
    assert "不要每隔一两段就单独插一个很短的判断段或敲钟段" in captured["instructions"]
    assert "不要反复使用“短句点一下，下一段再长解释”的固定节拍" in captured["instructions"]
    assert "不要把起因、机制、代价、转机一次性讲透" in captured["instructions"]
    assert "结尾回到人物处境或心绪余波" in captured["instructions"]


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
                "default_polish_instruction": "重写开头和结尾，打散重复句式。",
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
    assert "这不是局部润色任务，而是原创增强精修任务" in captured["instructions"]
    assert "必须重写开头段和结尾段" in captured["instructions"]
    assert "必须改写场景入口段、中段关键推进段和收束段" in captured["instructions"]
    assert "如果原稿一上来就在讲道理，优先前置原稿里本来已有的例子、动作或处境" in captured["instructions"]
    assert "先判断原稿哪些段落最像模板话，再优先拆掉这些段落的原顺序重写" in captured["instructions"]
    assert "至少把一个抽象判断段改写成更可感知的表达" in captured["instructions"]
    assert "如果原稿里有很多独立短判断段、敲钟段或一句话小结，至少合并掉一半" in captured["instructions"]
    assert "不要按“短句点一下 + 下一段长解释”的节拍反复排版" in captured["instructions"]
    assert "允许某些段落只停在动作、停顿、关系变化或身体反应" in captured["instructions"]
    assert "如果“一点、一下、一个、一种、一件”这类量词起手过密，主动改掉一半以上" in captured["instructions"]
    assert "不要只做同义词替换、语序微调或局部句子抛光" in captured["instructions"]


def test_generate_draft_prompt_allows_tone_profile_default_polish_instruction(monkeypatch) -> None:
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
                "default_polish_instruction": "重写开头和结尾，打散重复句式。",
            },
            "polish_instruction": "重写开头和结尾，打散重复句式。",
            "draft": {
                "title": "draft title",
                "body_markdown": "# draft\n\nbody",
            },
        }
    )

    assert "精修要求：重写开头和结尾，打散重复句式。" in captured["prompt"]


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


def test_parse_response_falls_back_to_chat_json_when_responses_parse_shape_is_invalid(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            raise TypeError("'NoneType' object is not iterable")

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)

            class FakeMessage:
                content = '{"title": "先把话说清楚", "angle": "关系修复里的表达入口"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    result = generator.generate_topic(
        {
            "trend_slug": "relationship-bet",
            "trend_title": "关系里的赌气",
            "source": "manual",
            "heat_score": 80,
            "status": "screening",
        }
    )

    assert result == {
        "title": "先把话说清楚",
        "angle": "关系修复里的表达入口",
    }
    assert captured["model"] == "test-model"
    assert captured["response_format"] == {"type": "json_object"}
    assert "只返回一个 JSON 对象" in captured["messages"][0]["content"]
    assert captured["messages"][1]["content"]


def test_parse_response_falls_back_to_chat_json_when_output_parsed_is_none(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            class FakeParsedResponse:
                output_parsed = None

            return FakeParsedResponse()

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)

            class FakeMessage:
                content = '{"title": "先说清正在发生什么", "angle": "从具体卡点重建表达入口"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    result = generator.generate_topic(
        {
            "trend_slug": "relationship-bet",
            "trend_title": "关系里的赌气",
            "source": "manual",
            "heat_score": 80,
            "status": "screening",
        }
    )

    assert result == {
        "title": "先说清正在发生什么",
        "angle": "从具体卡点重建表达入口",
    }
    assert captured["model"] == "test-model"
    assert captured["response_format"] == {"type": "json_object"}
    assert "只返回一个 JSON 对象" in captured["messages"][0]["content"]
    assert captured["messages"][1]["content"]


def test_parse_response_chat_json_fallback_retries_on_malformed_json(monkeypatch) -> None:
    generator = build_generator()
    chat_calls = {"count": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            class FakeParsedResponse:
                output_parsed = None
                output_text = ""
                output = []

            return FakeParsedResponse()

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1

            class FakeMessage:
                content = (
                    '{"title": "坏 JSON", "angle": "没收口}'
                    if chat_calls["count"] == 1
                    else '{"title": "先说清正在发生什么", "angle": "从具体卡点重建表达入口"}'
                )

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    result = generator.generate_topic(
        {
            "trend_slug": "relationship-bet",
            "trend_title": "关系里的赌气",
            "source": "manual",
            "heat_score": 80,
            "status": "screening",
        }
    )

    assert result == {
        "title": "先说清正在发生什么",
        "angle": "从具体卡点重建表达入口",
    }
    assert chat_calls["count"] == 2


def test_parse_response_uses_output_text_json_without_chat_fallback(monkeypatch) -> None:
    generator = build_generator()

    class FakeResponses:
        def parse(self, **kwargs):
            class FakeParsedResponse:
                output_parsed = None
                output_text = '{"title": "先接住身体发出的报警", "angle": "从具体卡顿切入"}'
                output = []

            return FakeParsedResponse()

    class FakeChatCompletions:
        def create(self, **kwargs):
            raise AssertionError("chat fallback should not be called when output_text already contains JSON")

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    result = generator.generate_topic(
        {
            "trend_slug": "body-alarm",
            "trend_title": "身体报警时的迟钝感",
            "source": "manual",
            "heat_score": 80,
            "status": "screening",
        }
    )

    assert result == {
        "title": "先接住身体发出的报警",
        "angle": "从具体卡顿切入",
    }


def test_parse_response_switches_to_chat_after_empty_completed_response(monkeypatch) -> None:
    generator = build_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1

            class FakeParsedResponse:
                output_parsed = None
                output_text = ""
                output = []

            return FakeParsedResponse()

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1

            class FakeMessage:
                content = '{"title": "先说清正在发生什么", "angle": "把空转状态钉成可见现象"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    first = generator.generate_topic(
        {
            "trend_slug": "body-alarm",
            "trend_title": "身体报警时的迟钝感",
            "source": "manual",
            "heat_score": 80,
            "status": "screening",
        }
    )
    second = generator.generate_topic(
        {
            "trend_slug": "body-alarm-2",
            "trend_title": "关系里的无力感",
            "source": "manual",
            "heat_score": 82,
            "status": "screening",
        }
    )

    assert first["title"] == "先说清正在发生什么"
    assert second["angle"] == "把空转状态钉成可见现象"
    assert parse_calls["count"] == 1
    assert chat_calls["count"] == 2


def test_parse_response_chat_preference_is_scoped_to_response_format(monkeypatch) -> None:
    generator = build_generator()
    parse_formats: list[type[object]] = []
    chat_calls = {"count": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            response_format = kwargs["text_format"]
            parse_formats.append(response_format)

            if response_format is DraftGenerationResult:
                class FakeParsedResponse:
                    output_parsed = None
                    output_text = ""
                    output = []

                return FakeParsedResponse()

            class FakeParsedResponse:
                output_parsed = TopicGenerationResult(
                    title="先把眼前那一下不舒服说清楚",
                    angle="从关系里的即时反应切入",
                )

            return FakeParsedResponse()

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1

            class FakeMessage:
                content = '{"title": "先把卡住的那一下写出来", "body_markdown": "# 标题\\n\\n正文"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    draft_result = generator.generate_draft(
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
                "default_polish_instruction": "重写开头和结尾，打散重复句式。",
            },
        }
    )
    topic_result = generator.generate_topic(
        {
            "trend_slug": "relationship-bet",
            "trend_title": "关系里的赌气",
            "source": "manual",
            "heat_score": 80,
            "status": "screening",
        }
    )

    assert draft_result == {
        "title": "先把卡住的那一下写出来",
        "body_markdown": "# 标题\n\n正文",
    }
    assert topic_result == {
        "title": "先把眼前那一下不舒服说清楚",
        "angle": "从关系里的即时反应切入",
    }
    assert parse_formats == [DraftGenerationResult, TopicGenerationResult]
    assert chat_calls["count"] == 1


def test_parse_response_falls_back_immediately_on_timeout(monkeypatch) -> None:
    generator = build_generator()
    parse_calls = {"count": 0}
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/responses"))

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)

            class FakeMessage:
                content = '{"title": "先把卡住的那一刻写出来", "body_markdown": "# 标题\\n\\n正文"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    result = generator.generate_draft(
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
                "default_polish_instruction": "重写开头和结尾，打散重复句式。",
            },
        }
    )

    assert result == {
        "title": "先把卡住的那一刻写出来",
        "body_markdown": "# 标题\n\n正文",
    }
    assert parse_calls["count"] == 1
    assert captured["timeout"] == 90.0


def test_parse_response_timeout_fallback_does_not_stick_for_future_calls(monkeypatch) -> None:
    generator = build_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            if parse_calls["count"] == 1:
                raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/responses"))

            class FakeParsedResponse:
                output_parsed = DraftGenerationResult(
                    title="第二次直接走结构化响应",
                    body_markdown="# 标题\n\n第二版正文",
                )

            return FakeParsedResponse()

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1

            class FakeMessage:
                content = '{"title": "第一次先用回退兜住", "body_markdown": "# 标题\\n\\n第一版正文"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    first = generator.generate_draft(
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
                "default_polish_instruction": "重写开头和结尾，打散重复句式。",
            },
        }
    )
    second = generator.generate_draft(
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
                "default_polish_instruction": "重写开头和结尾，打散重复句式。",
            },
        }
    )

    assert first == {
        "title": "第一次先用回退兜住",
        "body_markdown": "# 标题\n\n第一版正文",
    }
    assert second == {
        "title": "第二次直接走结构化响应",
        "body_markdown": "# 标题\n\n第二版正文",
    }
    assert parse_calls["count"] == 2
    assert chat_calls["count"] == 1


def test_generate_draft_prefers_chat_json_first_for_custom_base_url(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    chat_calls = {"count": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            raise AssertionError("responses.parse should be skipped for draft generation on custom base URLs")

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1

            class FakeMessage:
                content = '{"title": "先把卡住的那一刻写出来", "body_markdown": "# 标题\\n\\n正文"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    result = generator.generate_draft(
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
                "default_polish_instruction": "重写开头和结尾，打散重复句式。",
            },
        }
    )

    assert result == {
        "title": "先把卡住的那一刻写出来",
        "body_markdown": "# 标题\n\n正文",
    }
    assert chat_calls["count"] == 1


def test_generate_topic_keeps_responses_parse_first_for_custom_base_url(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1

            class FakeParsedResponse:
                output_parsed = TopicGenerationResult(
                    title="先照顾情绪，再谈关系修复",
                    angle="关系修复顺序",
                )

            return FakeParsedResponse()

    class FakeChatCompletions:
        def create(self, **kwargs):
            raise AssertionError("chat fallback should not be called for topic generation when responses.parse succeeds")

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

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
    assert parse_calls["count"] == 1


def test_generate_topic_retries_responses_parse_after_internal_server_error_on_custom_base_url(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    request = httpx.Request("POST", "https://proxy.example/v1/responses")
    response = httpx.Response(
        502,
        request=request,
        json={"error": {"message": "Upstream access forbidden, please contact administrator"}},
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise openai.InternalServerError(
                "Upstream access forbidden, please contact administrator",
                response=response,
                body={"error": {"message": "Upstream access forbidden, please contact administrator"}},
            )

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
            raise AssertionError("chat fallback should stay disabled for topic generation on custom base URLs")

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())
    monkeypatch.setattr(ai_generator_module.time, "sleep", lambda *_args: None)

    with pytest.raises(openai.InternalServerError, match="Upstream access forbidden"):
        generator.generate_topic(
            {
                "trend_slug": "life-order-drift",
                "trend_title": "别把日子过反了",
                "source": "manual",
                "heat_score": 83,
                "status": "screening",
            }
        )

    assert parse_calls["count"] == 3
    assert chat_calls["count"] == 0


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
            "body_markdown": "她不是突然没耐心，只是先把自己的疲惫往后放了太久。",
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
    assert "风格档案：女性成长克制陪伴风" in captured["prompt"]
    assert "参考文章正文抓手候选：" in captured["prompt"]


def test_generate_outline_prompt_includes_reference_article_guardrails(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(*, instructions: str, prompt: str, response_format):
        captured["instructions"] = instructions
        captured["prompt"] = prompt
        return OutlineGenerationResult(hook="hook", outline_body="1. a\n2. b")

    monkeypatch.setattr(generator, "_parse_response", fake_parse_response)

    generator.generate_outline(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "先接住失望，再谈道理",
            "topic_angle": "关系修复",
            "project_title": "慢修复关系稿",
            "source_type": "tracked_article",
            "reference_article_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "reference_article_author": "北岛",
            "reference_article_source_name": "夜读关系实验室",
            "reference_article_summary": "从关系修复案例提炼表达顺序。",
            "reference_article_structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "reference_article_tags": ["表达修复", "关系修复"],
            "tone_profile": {
                "name": "女性成长克制陪伴风",
                "target_word_count": 1400,
            },
        }
    )

    assert "参考文章已经在选题阶段被消化成当前选题和角度" in captured["instructions"]
    assert "只允许借用赛道冲突，不允许借用原标题骨架、开头入口、段落顺序、小节职责或结尾论断" in captured["instructions"]
    assert "大纲必须同时拉开至少四处距离" in captured["instructions"]
    assert "参考文章来源线索（仅用于确认赛道与冲突，不得继续沿用原文骨架）：" in captured["prompt"]
    assert "来源账号：夜读关系实验室" in captured["prompt"]
    assert "主题标签：表达修复 / 关系修复" in captured["prompt"]
    assert "参考文章标题：" not in captured["prompt"]
    assert "参考文章结构备注：" not in captured["prompt"]


def test_generate_draft_prompt_includes_reference_article_guardrails(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(*, instructions: str, prompt: str, response_format):
        captured["instructions"] = instructions
        captured["prompt"] = prompt
        return DraftGenerationResult(title="title", body_markdown="# draft")

    monkeypatch.setattr(generator, "_parse_response", fake_parse_response)

    generator.generate_draft(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "先接住失望，再谈道理",
            "topic_angle": "关系修复",
            "project_title": "慢修复关系稿",
            "source_type": "tracked_article",
            "reference_article_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "reference_article_author": "北岛",
            "reference_article_source_name": "夜读关系实验室",
            "reference_article_summary": "从关系修复案例提炼表达顺序。",
            "reference_article_structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "reference_article_tags": ["表达修复", "关系修复"],
            "outline": {
                "hook": "先接住情绪，不要急着摆道理",
                "outline_body": "1. 失望现场\n2. 常见误区\n3. 修复动作",
            },
            "tone_profile": {
                "name": "女性成长克制陪伴风",
                "target_word_count": 1400,
            },
        }
    )

    assert "参考文章已经在选题和大纲阶段被消化，这一阶段默认你看不到原文" in captured["instructions"]
    assert "不要再按原文标题、摘要措辞、结构备注或段落顺序组织正文" in captured["instructions"]
    assert "起笔对象、主段顺序、案例排列和收束动作都必须重新组织" in captured["instructions"]
    assert "参考文章来源线索（仅用于确认赛道与冲突，不得继续沿用原文骨架）：" in captured["prompt"]
    assert "来源账号：夜读关系实验室" in captured["prompt"]
    assert "主题标签：表达修复 / 关系修复" in captured["prompt"]
    assert "参考文章摘要：" not in captured["prompt"]
    assert "参考文章结构备注：" not in captured["prompt"]


def test_generate_tracked_article_metadata_retries_responses_parse_after_internal_server_error_on_custom_base_url(
    monkeypatch,
) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    request = httpx.Request("POST", "https://proxy.example/v1/responses")
    response = httpx.Response(
        502,
        request=request,
        json={"error": {"message": "Upstream access forbidden, please contact administrator"}},
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise openai.InternalServerError(
                "Upstream access forbidden, please contact administrator",
                response=response,
                body={"error": {"message": "Upstream access forbidden, please contact administrator"}},
            )

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
            raise AssertionError(
                "chat fallback should stay disabled for tracked-article metadata on custom base URLs"
            )

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())
    monkeypatch.setattr(ai_generator_module.time, "sleep", lambda *_args: None)

    with pytest.raises(openai.InternalServerError, match="Upstream access forbidden"):
        generator.generate_tracked_article_metadata(
            {
                "source_kind": "manual",
                "source_name": "手动录入",
                "article_title": "别把日子过反了",
                "article_url": "https://example.com/article",
                "author": "",
                "summary": "",
                "structure_notes": "",
                "tags": [],
                "body_source": "manual",
                "body_markdown": "她总说等忙完这阵，再去做那些真正重要的事。",
            }
        )

    assert parse_calls["count"] == 3
    assert chat_calls["count"] == 0


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
    assert captured["size"] == "1536x1024"
    assert captured["quality"] == "low"
    assert captured["output_format"] == "png"
    assert captured["timeout"] == 180.0
    assert "21:9" in str(captured["prompt"])
    assert "横版封面图" in str(captured["prompt"])


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
    assert calls[0]["size"] == "1536x1024"
    assert calls[0]["quality"] == "low"
    assert calls[0]["timeout"] == 180.0
    assert calls[1]["size"] == "1024x1024"
    assert calls[1]["quality"] == "low"
    assert calls[1]["timeout"] == 240.0


def test_get_ai_config_summary_masks_secret_but_reports_runtime_fields() -> None:
    summary = get_ai_config_summary(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://example.com/v1",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_reasoning_effort="medium",
            openai_request_timeout_seconds=45.0,
        )
    )

    assert summary.api_key_configured is True
    assert summary.base_url == "https://example.com/v1"
    assert summary.model == "test-model"
    assert summary.image_model == "test-image-model"
    assert summary.reasoning_effort == "medium"
    assert summary.request_timeout_seconds == 45.0


def test_run_ai_config_check_returns_success_when_probe_passes(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)

            class FakeResponse:
                output_text = "OK"

            return FakeResponse()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", lambda config: generator)

    result = run_ai_config_check(
        Settings(
            openai_api_key="test-key",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_reasoning_effort="medium",
        )
    )

    assert result.ok is True
    assert result.status == "ok"
    assert "检测通过" in result.message
    assert captured["model"] == "test-model"
    assert captured["input"] == "Reply with exactly OK."
    assert captured["max_output_tokens"] == 8
    assert captured["reasoning"] == {"effort": "medium"}


def test_run_ai_config_check_surfaces_upstream_failures(monkeypatch) -> None:
    request = httpx.Request("POST", "https://example.com/v1/responses")
    response = httpx.Response(502, request=request, json={"error": {"message": "Upstream service temporarily unavailable"}})

    class FailingGenerator:
        def __init__(self, _config) -> None:
            pass

        def check_connection(self) -> None:
            raise openai.InternalServerError(
                "Upstream service temporarily unavailable",
                response=response,
                body={"error": {"message": "Upstream service temporarily unavailable"}},
            )

    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", FailingGenerator)

    result = run_ai_config_check(
        Settings(
            openai_api_key="test-key",
            openai_model="test-model",
            openai_image_model="test-image-model",
        )
    )

    assert result.ok is False
    assert result.status == "upstream_error"
    assert "上游服务异常" in result.message
    assert "Upstream service temporarily unavailable" in result.message
