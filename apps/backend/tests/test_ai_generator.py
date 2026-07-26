from __future__ import annotations

import base64
import httpx
import openai
import pytest

from app.core.settings import Settings
import app.services.ai_generator as ai_generator_module
from app.services.ai_generator import (
    AssetGenerationResult,
    DraftGenerationResult,
    OpenAIWorkbenchGenerator,
    OutlineGenerationResult,
    PublishPackageGenerationResult,
    TrackedArticleMetadataGenerationResult,
    TopicGenerationResult,
    get_ai_config_summary,
    run_ai_config_check,
    run_ai_image_config_check,
    run_ai_image_route_probe,
)


def build_generator() -> OpenAIWorkbenchGenerator:
    return OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="",
            openai_model="test-model",
            openai_image_base_url="",
            openai_image_model="test-image-model",
        )
    )


def build_custom_base_url_generator() -> OpenAIWorkbenchGenerator:
    return OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_base_url="https://proxy.example/v1",
            openai_image_model="test-image-model",
        )
    )


def test_outline_generation_result_accepts_outline_body_list() -> None:
    result = OutlineGenerationResult.model_validate(
        {"hook": "先落一个电话", "outline_body": ["1. 电话这头", "2. 家里的灯"]}
    )

    assert result.outline_body == "1. 电话这头\n2. 家里的灯"


def test_normalize_draft_generation_result_removes_leaked_field_labels() -> None:
    result = ai_generator_module._normalize_draft_generation_result(
        DraftGenerationResult(
            title="1. 标题 title",
            body_markdown=(
                "家里一有事，总是你先把顺序理出来"
                "2. 正文 markdown body_markdown"
                "电话响起来的时候，她先看了眼月底的日历。"
            ),
        )
    )

    assert result.title == "家里一有事，总是你先把顺序理出来"
    assert result.body_markdown == "电话响起来的时候，她先看了眼月底的日历。"


def test_normalize_draft_generation_result_removes_markdown_code_fences() -> None:
    result = ai_generator_module._normalize_draft_generation_result(
        DraftGenerationResult(
            title="家里一有事，总要有人先把顺序理出来",
            body_markdown="```markdown电话响起来的时候，家里的安排就变了。\n\n有人把饭热上，等你回家。```",
        )
    )

    assert result.body_markdown == "电话响起来的时候，家里的安排就变了。\n\n有人把饭热上，等你回家。"

def test_generator_clients_disable_sdk_internal_retries() -> None:
    generator = build_generator()

    assert generator._client.max_retries == 0
    assert generator._image_client.max_retries == 0
    assert generator._client._client._trust_env is False
    assert generator._image_client._client._trust_env is False


def test_generator_can_opt_into_proxy_env() -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_base_url="https://proxy.example/v1",
            openai_image_model="test-image-model",
            openai_trust_env=True,
        )
    )

    assert generator._client._client._trust_env is True
    assert generator._image_client._client._trust_env is True


def test_generate_outline_prompt_mentions_target_word_count(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds_override=None,
        max_attempts_override=None,
    ):
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

    def fake_parse_response(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds_override=None,
        max_attempts_override=None,
    ):
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
    assert "把抽象情绪落到动作停顿、物件光线、空间距离、关系变化或现实余波上" in captured["instructions"]
    assert "避免每段都写成“观点句 + 解释句”" in captured["instructions"]
    assert "避免反复用“一点、一下、一些、一个、一种”去切分感受和动作" in captured["instructions"]
    assert "不要每隔一两段就单独插一个很短的判断段或敲钟段" in captured["instructions"]
    assert "不要反复使用“短句点一下，下一段再长解释”的固定节拍" in captured["instructions"]
    assert "不要把起因、机制、代价、转机一次性讲透" in captured["instructions"]
    assert "结尾回到人物处境或心绪余波" in captured["instructions"]


def test_generate_draft_prompt_includes_polish_instruction_and_existing_draft(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds_override=None,
        max_attempts_override=None,
    ):
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

    def fake_parse_response(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds_override=None,
        max_attempts_override=None,
    ):
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


def test_generate_draft_compact_mode_preserves_single_attempt_budget_in_chat_fallback(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, object] = {"chat_calls": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/responses"))

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["chat_calls"] += 1
            captured["last_chat_kwargs"] = kwargs
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/chat/completions"))

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    with pytest.raises(openai.APITimeoutError):
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
                "compact_strategy_mode": True,
            }
        )

    assert captured["chat_calls"] == 1
    assert captured["last_chat_kwargs"]["timeout"] == 60.0


def test_generate_draft_strategy_first_mode_preserves_single_attempt_budget_in_chat_fallback(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, object] = {"chat_calls": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/responses"))

    class FakeChatCompletions:
        def create(self, **kwargs):
            captured["chat_calls"] += 1
            captured["last_chat_kwargs"] = kwargs
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/chat/completions"))

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    with pytest.raises(openai.APITimeoutError):
        generator.generate_draft(
            {
                "trend_title": "参考文章 / 手动录入",
                "topic_title": "外部支撑不稳时，最该补的，是把自己托住的能力",
                "topic_angle": "当外部回应常常慢半拍、别人也各自承压时，低谷里最难的不是指望谁接住，而是把恢复权从等待里收回来。",
                "project_title": "自救自渡主题验收",
                "outline": {
                    "hook": "你想找人说说的时候，手机那头常常只剩一句“我也快忙不过来了”。",
                    "outline_body": "1. 外求落空\n2. 先把自己拉回可运转\n3. 再谈怎么往下过",
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
                "source_type": "tracked_article",
                "problem_brief": {"clarified_problem": "x"},
                "strategy_card": {"structure_mode": "self_reliance_inward_support"},
                "strategy_first_draft_mode": True,
            }
        )

    assert captured["chat_calls"] == 1
    assert captured["last_chat_kwargs"]["timeout"] == 60.0


def test_generate_outline_falls_back_to_chat_json_when_responses_parse_returns_markdown(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            OutlineGenerationResult.model_validate_json("**hook**\\n你撤回的求助，往往不是情绪消失了。")

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
            captured.update(kwargs)

            class FakeMessage:
                content = '{"hook":"先写那个把情绪收回去的瞬间","outline_body":"1. 为什么会先说没事\\n2. 被推开以后会撤回什么\\n3. 关系怎么一点点降温"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    result = generator.generate_outline(
        {
            "trend_title": "被推开的那一刻",
            "topic_title": "总在天亮前把自己缝好的人，最后会先撤回求助",
            "topic_angle": "把一次次说没事之后的代价拆开",
            "project_title": "被推开的那一刻",
            "tone_profile": {
                "name": "今晚有语",
                "target_word_count": 1400,
            },
        }
    )

    assert result == {
        "hook": "先写那个把情绪收回去的瞬间",
        "outline_body": "1. 为什么会先说没事\n2. 被推开以后会撤回什么\n3. 关系怎么一点点降温",
    }
    assert parse_calls["count"] == 1
    assert chat_calls["count"] == 1
    assert "只返回一个 JSON 对象" in str(captured["extra_body"]["instructions"])


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


def test_parse_response_chat_json_fallback_retries_on_transient_connection_errors(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
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
            if chat_calls["count"] == 1:
                raise openai.APIConnectionError(request=httpx.Request("POST", "https://proxy.example/v1/chat/completions"))
            if chat_calls["count"] == 2:
                raise openai.APITimeoutError(request=httpx.Request("POST", "https://proxy.example/v1/chat/completions"))

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
    assert chat_calls["count"] == 3


def test_parse_response_chat_json_fallback_grants_extra_transport_recovery_for_custom_base_url(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
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
            if chat_calls["count"] <= 3:
                raise openai.APIConnectionError(
                    request=httpx.Request("POST", "https://proxy.example/v1/chat/completions")
                )

            class FakeMessage:
                content = '{"title": "第四次把结构化结果接回来了", "body_markdown": "# 标题\\n\\n正文"}'

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
        "title": "第四次把结构化结果接回来了",
        "body_markdown": "# 标题\n\n正文",
    }
    assert parse_calls["count"] == 1
    assert chat_calls["count"] == 4


def test_parse_response_chat_json_fallback_respects_explicit_attempt_budget_for_custom_base_url(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
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
            raise openai.APIConnectionError(
                request=httpx.Request("POST", "https://proxy.example/v1/chat/completions")
            )

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    with pytest.raises(openai.APIConnectionError):
        generator._parse_response(
            instructions="只返回 JSON。",
            prompt="输出大纲",
            response_format=OutlineGenerationResult,
            max_attempts_override=1,
        )

    assert parse_calls["count"] == 1
    assert chat_calls["count"] == 1


def test_generate_outline_uses_bounded_timeout_profile_for_strategy_first_payload(monkeypatch) -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=60,
        )
    )
    captured: list[tuple[float | None, int | None]] = []

    def fake_parse_response(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds_override=None,
        max_attempts_override=None,
    ):
        captured.append((timeout_seconds_override, max_attempts_override))
        return OutlineGenerationResult(hook="hook", outline_body="1. a\n2. b")

    monkeypatch.setattr(generator, "_parse_response", fake_parse_response)

    base_payload = {
        "trend_title": "参考文章 / 夜读关系实验室",
        "topic_title": "总在照顾别人情绪的人，也需要有人接住",
        "topic_angle": "关系负重",
        "project_title": "outline bounded timeout",
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

    generator.generate_outline({**base_payload, "strategy_first_outline_mode": True})
    generator.generate_outline(base_payload)

    assert captured == [(60, 1), (None, None)]


def test_generate_outline_custom_base_url_does_not_cache_chat_json_preference(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
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
                content = '{"hook": "她把那句没事放轻了", "outline_body": "1. a\\n2. b"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    payload = {
        "trend_title": "参考文章 / 夜读关系实验室",
        "topic_title": "总在照顾别人情绪的人，也需要有人接住",
        "topic_angle": "关系负重",
        "project_title": "outline preference cache",
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
        "strategy_first_outline_mode": True,
    }

    generator.generate_outline(payload)
    generator.generate_outline(payload)

    assert parse_calls["count"] == 2
    assert chat_calls["count"] == 2



def test_custom_base_url_recovery_honors_configured_timeout_and_retry_budget() -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=120,
        )
    )

    assert generator._resolve_outline_timeout_override({"outline_timeout_recovery_mode": True}) == 120
    assert generator._resolve_outline_timeout_override({"strategy_first_outline_mode": True}) == 120
    assert generator._resolve_assets_timeout_override({"assets_timeout_recovery_mode": True}) == 120
    assert generator._resolve_publish_timeout_override({"publish_timeout_recovery_mode": True}) == 120
    assert generator._resolve_draft_timeout_override(
        {"timeout_recovery_mode": True, "source_type": "tracked_article"}
    ) == 120
    assert generator._resolve_draft_timeout_override(
        {"strategy_first_draft_mode": True, "source_type": "tracked_article"}
    ) == 120
    assert generator._resolve_topic_timeout_override({"source_type": "tracked_article"}) == 120
    assert generator._resolve_tracked_article_metadata_timeout_override({"body_markdown": "x"}) == 120
    assert generator._resolve_outline_max_attempts({"outline_timeout_recovery_mode": True}) == 1
    assert generator._resolve_assets_max_attempts({"assets_timeout_recovery_mode": True}) == 1
    assert generator._resolve_assets_max_attempts({"source_type": "tracked_article"}) == 1
    assert generator._resolve_assets_max_attempts({"source_type": "manual"}) is None
    assert generator._resolve_publish_max_attempts({"publish_timeout_recovery_mode": True}) == 1
    assert generator._resolve_publish_max_attempts({"source_type": "tracked_article"}) == 1
    assert generator._resolve_publish_max_attempts({"source_type": "manual"}) is None
    assert generator._resolve_draft_max_attempts(
        {"timeout_recovery_mode": True, "source_type": "tracked_article"}
    ) == 1
    assert generator._resolve_topic_max_attempts({"source_type": "tracked_article"}) == 1
    assert generator._resolve_tracked_article_metadata_max_attempts({"body_markdown": "x"}) == 1

def test_generate_outline_timeout_recovery_mode_uses_plain_chat_json_without_extra_body(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise AssertionError("outline timeout recovery should bypass responses.parse")

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
            captured.update(kwargs)

            class FakeMessage:
                content = '{"hook":"先写那句没事背后的发紧","outline_body":"1. 电话和账单\\n2. 为什么先把自己往后放\\n3. 家里安稳怎么把辛苦说成值得\\n4. 结尾回到被护住的日常"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())

    result = generator.generate_outline(
        {
            "trend_title": "参考文章 / manual-originality-check",
            "topic_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "topic_angle": "从成年人为什么总把“我没事”说得很轻切入",
            "project_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "outline_timeout_recovery_mode": True,
            "strategy_first_outline_mode": True,
            "tone_profile": {
                "name": "女性成长克制陪伴风",
                "target_word_count": 1400,
            },
            "problem_brief": {
                "theme_axis": "很多成年人为什么会把“我没事”顶在前面，把辛苦和委屈先往后收。",
                "core_conflict": "明明已经很疲惫了，还是要把那句有我稳稳顶在前面。",
                "emotional_value_goal": "让读者知道这些硬撑最后都在把家里的人和日子托住。",
                "anti_drift_axis": "不要漂成泛幸福定义或空泛鸡汤。",
            },
            "strategy_card": {
                "hook_trigger": "一句“没事，有我”背后那点喉咙发紧。",
                "progression_drive": "责任先把人往前推，再让家里的安稳把这些辛苦一点点说成值得。",
                "positive_direction": "结尾回到家里仍被护住的安稳。",
                "scene_anchor_requirements": ["电话", "账单"],
            },
        }
    )

    assert result["hook"] == "先写那句没事背后的发紧"
    assert parse_calls["count"] == 0
    assert chat_calls["count"] == 1
    assert captured.get("extra_body") is None


def test_generate_outline_timeout_recovery_mode_uses_bounded_custom_timeout_and_retry(monkeypatch) -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=60,
        )
    )
    captured: list[tuple[float, int, bool, bool, bool]] = []

    def fake_parse_response_with_chat_json_fallback(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds: float,
        max_attempts: int,
        enforce_custom_base_url_retry_floor: bool = True,
        include_custom_base_url_extra_body: bool = True,
        include_response_format: bool = True,
    ):
        captured.append(
            (
                timeout_seconds,
                max_attempts,
                enforce_custom_base_url_retry_floor,
                include_custom_base_url_extra_body,
                include_response_format,
            )
        )
        return OutlineGenerationResult(hook="hook", outline_body="1. a\n2. b")

    monkeypatch.setattr(
        generator,
        "_parse_response_with_chat_json_fallback",
        fake_parse_response_with_chat_json_fallback,
    )

    result = generator.generate_outline(
        {
            "trend_title": "参考文章 / manual-originality-check",
            "topic_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "topic_angle": "从成年人为什么总把“我没事”说得很轻切入",
            "project_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "outline_timeout_recovery_mode": True,
            "strategy_first_outline_mode": True,
            "tone_profile": {
                "name": "女性成长克制陪伴风",
                "target_word_count": 1400,
            },
        }
    )

    assert result == {"hook": "hook", "outline_body": "1. a\n2. b"}
    assert captured == [(60, 1, False, False, False)]


def test_generate_assets_timeout_recovery_mode_uses_plain_chat_json_without_extra_body(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise AssertionError("assets timeout recovery should bypass responses.parse")

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
            captured.update(kwargs)

            class FakeMessage:
                content = (
                    '{"title_options":["标题一","标题二","标题三"],'
                    '"recommended_title":"标题二",'
                    '"cover_prompt":"16:9 横版公众号头图，夜里灯还亮着，克制现实感",'
                    '"cover_copy":"很多辛苦，最后都在把家稳住。",'
                    '"social_teaser":"那句没事，有我，背后压着的是整屋子的秩序。",'
                    '"social_teaser_options":["导语一","导语二","导语三"]}'
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

    result = generator.generate_assets(
        {
            "trend_title": "参考文章 / manual-originality-check",
            "topic_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "topic_angle": "从成年人为什么总把“我没事”说得很轻切入",
            "project_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "assets_timeout_recovery_mode": True,
            "draft": {
                "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
                "body_markdown": "很多时候，说这句话的人并不轻松。",
            },
            "problem_brief": {
                "theme_axis": "很多成年人为什么会把“我没事”顶在前面。",
                "core_conflict": "明明已经很疲惫了，还是要把那句有我稳稳顶在前面。",
                "emotional_value_goal": "让读者知道这些硬撑最后都在把家里的人和日子托住。",
            },
            "strategy_card": {
                "packaging_focus": "先抓现实重量，再回到家里的安稳。",
                "packaging_hook": "先抓那点发紧和还得继续撑住。",
                "positive_direction": "落回家里仍被护住的安稳。",
            },
        }
    )

    assert result["recommended_title"] == "标题二"
    assert parse_calls["count"] == 0
    assert chat_calls["count"] == 1
    assert captured.get("extra_body") is None
    assert "response_format" not in captured


def test_generate_assets_timeout_recovery_mode_uses_bounded_custom_timeout_and_retry(monkeypatch) -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=60,
        )
    )
    captured: list[tuple[float, int, bool, bool, bool]] = []

    def fake_parse_response_with_chat_json_fallback(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds: float,
        max_attempts: int,
        enforce_custom_base_url_retry_floor: bool = True,
        include_custom_base_url_extra_body: bool = True,
        include_response_format: bool = True,
    ):
        captured.append(
            (
                timeout_seconds,
                max_attempts,
                enforce_custom_base_url_retry_floor,
                include_custom_base_url_extra_body,
                include_response_format,
            )
        )
        return AssetGenerationResult(
            title_options=["标题一", "标题二", "标题三"],
            recommended_title="标题二",
            cover_prompt="16:9 横版公众号头图，夜里灯还亮着，克制现实感",
            cover_copy="很多辛苦，最后都在把家稳住。",
            social_teaser="那句没事，有我，背后压着的是整屋子的秩序。",
            social_teaser_options=["导语一", "导语二", "导语三"],
        )

    monkeypatch.setattr(
        generator,
        "_parse_response_with_chat_json_fallback",
        fake_parse_response_with_chat_json_fallback,
    )

    result = generator.generate_assets(
        {
            "trend_title": "参考文章 / manual-originality-check",
            "topic_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "topic_angle": "从成年人为什么总把“我没事”说得很轻切入",
            "project_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "assets_timeout_recovery_mode": True,
            "draft": {
                "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
                "body_markdown": "很多时候，说这句话的人并不轻松。",
            },
        }
    )

    assert result["recommended_title"] == "标题二"
    assert captured == [(60, 1, False, False, False)]


def test_generate_publish_timeout_recovery_mode_uses_plain_chat_json_without_extra_body(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise AssertionError("publish timeout recovery should bypass responses.parse")

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
            captured.update(kwargs)

            class FakeMessage:
                content = (
                    '{"abstract":"写成年人先把慌乱压回去，再把辛苦落到家里安稳上。",'
                    '"tags":["中年责任","家庭安稳","夜里硬撑"],'
                    '"editor_note":"发布时主打那句没事有我背后的现实重量。",'
                    '"publish_title":"一句“没事，有我”，先扛住了账单电话，也扛住了这个家",'
                    '"publish_lead":"那句“没事，有我”最重的时候，常常不是说给别人听。",'
                    '"intro_options":["导语一","导语二","导语三"]}'
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

    result = generator.generate_publish_package(
        {
            "project_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "publish_timeout_recovery_mode": True,
            "draft": {
                "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
                "body_markdown": "很多时候，说这句话的人并不轻松。",
            },
            "assets": {
                "recommended_title": "一句“没事，有我”，先扛住了账单电话，也扛住了这个家",
                "cover_copy": "先把慌乱咽下去，把家里稳住",
                "social_teaser": "那句“没事，有我”最重的时候，常常不是说给别人听。",
                "title_options": ["标题一", "标题二"],
                "social_teaser_options": ["导语一", "导语二"],
            },
            "problem_brief": {
                "theme_axis": "很多成年人为什么会把“我没事”顶在前面。",
                "core_conflict": "明明已经很疲惫了，还是要把那句有我稳稳顶在前面。",
                "emotional_value_goal": "让读者知道这些硬撑最后都在把家里的人和日子托住。",
            },
            "strategy_card": {
                "packaging_focus": "先抓现实重量，再回到家里的安稳。",
                "packaging_hook": "先抓那点发紧和还得继续撑住。",
                "positive_direction": "落回家里仍被护住的安稳。",
            },
        }
    )

    assert result["publish_title"] == "一句“没事，有我”，先扛住了账单电话，也扛住了这个家"
    assert parse_calls["count"] == 0
    assert chat_calls["count"] == 1
    assert captured.get("extra_body") is None
    assert "response_format" not in captured


def test_generate_publish_timeout_recovery_mode_uses_bounded_custom_timeout_and_retry(monkeypatch) -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=60,
        )
    )
    captured: list[tuple[float, int, bool, bool, bool]] = []

    def fake_parse_response_with_chat_json_fallback(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds: float,
        max_attempts: int,
        enforce_custom_base_url_retry_floor: bool = True,
        include_custom_base_url_extra_body: bool = True,
        include_response_format: bool = True,
    ):
        captured.append(
            (
                timeout_seconds,
                max_attempts,
                enforce_custom_base_url_retry_floor,
                include_custom_base_url_extra_body,
                include_response_format,
            )
        )
        return PublishPackageGenerationResult(
            abstract="写成年人先把慌乱压回去，再把辛苦落到家里安稳上。",
            tags=["中年责任", "家庭安稳", "夜里硬撑"],
            editor_note="发布时主打那句没事有我背后的现实重量。",
            publish_title="一句“没事，有我”，先扛住了账单电话，也扛住了这个家",
            publish_lead="那句“没事，有我”最重的时候，常常不是说给别人听。",
            intro_options=["导语一", "导语二", "导语三"],
        )

    monkeypatch.setattr(
        generator,
        "_parse_response_with_chat_json_fallback",
        fake_parse_response_with_chat_json_fallback,
    )

    result = generator.generate_publish_package(
        {
            "project_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "publish_timeout_recovery_mode": True,
            "draft": {
                "title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
                "body_markdown": "很多时候，说这句话的人并不轻松。",
            },
            "assets": {
                "recommended_title": "一句“没事，有我”，先扛住了账单电话，也扛住了这个家",
                "cover_copy": "先把慌乱咽下去，把家里稳住",
                "social_teaser": "那句“没事，有我”最重的时候，常常不是说给别人听。",
                "title_options": ["标题一", "标题二"],
                "social_teaser_options": ["导语一", "导语二"],
            },
        }
    )

    assert result["publish_title"] == "一句“没事，有我”，先扛住了账单电话，也扛住了这个家"
    assert captured == [(60, 1, False, False, False)]


def test_generate_draft_timeout_recovery_mode_uses_plain_text_chat_without_extra_body(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise AssertionError("draft timeout recovery should bypass responses.parse")

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
            captured.update(kwargs)

            class FakeMessage:
                content = '{"title":"那句我没事后面，藏着多少不敢倒下","body_markdown":"第一段\\n\\n第二段"}'

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
            "trend_title": "参考文章 / manual-originality-check",
            "topic_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "topic_angle": "从成年人为什么总把“我没事”说得很轻切入。",
            "project_title": "夜里那句“没事，有我”，撑着的从来不只是一张账单",
            "source_type": "tracked_article",
            "timeout_recovery_mode": True,
            "outline": {
                "hook": "一句“没事，有我”背后那点喉咙发紧。",
                "outline_body": "1. 先写硬撑\n2. 再写代价\n3. 最后回到安稳",
            },
            "problem_brief": {
                "theme_axis": "很多成年人为什么会把“我没事”顶在前面，把辛苦和委屈先往后收。",
                "core_conflict": "明明已经很疲惫了，还是要把那句有我稳稳顶在前面。",
            },
            "strategy_card": {
                "positive_direction": "结尾回到家里仍被护住的安稳。",
            },
        }
    )

    assert result["title"] == "那句我没事后面，藏着多少不敢倒下"
    assert parse_calls["count"] == 0
    assert chat_calls["count"] == 1
    assert captured.get("extra_body") is None
    assert "response_format" not in captured
    assert captured["timeout"] == 60.0


def test_generate_draft_strategy_first_tracked_article_uses_bounded_plain_text_chat_on_custom_base_url(
    monkeypatch,
) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    captured: dict[str, object] = {}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise AssertionError("strategy-first tracked article draft should bypass responses.parse on custom base url")

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
            captured.update(kwargs)

            class FakeMessage:
                content = '{"title":"家里一有事，你总会先把家稳住","body_markdown":"第一段\\n\\n第二段"}'

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
            "trend_title": "参考文章 / manual-originality-check",
            "topic_title": "家里一有事，你总会先把家稳住",
            "topic_angle": "从成年人先把家里顺序理清这件事切入。",
            "project_title": "真实链路验证-责任",
            "source_type": "tracked_article",
            "strategy_first_draft_mode": True,
            "outline": {
                "hook": "很多中年人的一通来电，听着只是家里有事，心里却已经开始替所有人排顺序。",
                "outline_body": "1. 先写现实接口\n2. 再写多想一步\n3. 最后回到家里安稳",
            },
            "problem_brief": {
                "theme_axis": "很多成年人为什么会先把家里顺序理清。",
                "core_conflict": "责任最重的地方，不是一个人有多厉害，而是他心里一直装着想守护的人。",
            },
            "strategy_card": {
                "positive_direction": "结尾回到家里被托住的安稳，不要写成空泛吃苦叙事。",
            },
        }
    )

    assert result["title"] == "家里一有事，你总会先把家稳住"
    assert parse_calls["count"] == 0
    assert chat_calls["count"] == 1
    assert captured.get("extra_body") is None
    assert "response_format" not in captured
    assert captured["timeout"] == 60.0


def test_generate_draft_uses_configured_timeout_for_compact_or_full_fallback_payload(monkeypatch) -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=60,
        )
    )
    captured: list[tuple[float | None, int | None]] = []

    def fake_parse_response(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds_override=None,
        max_attempts_override=None,
    ):
        captured.append((timeout_seconds_override, max_attempts_override))
        return DraftGenerationResult(title="title", body_markdown="# draft")

    monkeypatch.setattr(generator, "_parse_response", fake_parse_response)

    base_payload = {
        "trend_title": "幸福是什么",
        "topic_title": "幸福不是继续强求，而是看见自己已经拥有的东西",
        "topic_angle": "从放手以后重新看见已拥有的部分切入",
        "project_title": "幸福是什么",
        "outline": {
            "hook": "她把消息框关掉以后，才看见晚饭已经凉了。",
            "outline_body": "1. 已拥有被忽略\n2. 幸福被误认成继续争取\n3. 生活秩序被拖空\n4. 放手以后空出来",
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

    generator.generate_draft({**base_payload, "compact_strategy_mode": True})
    generator.generate_draft({**base_payload, "full_fallback_single_attempt_mode": True})
    generator.generate_draft(base_payload)

    assert captured == [(60, 1), (60, 1), (None, None)]


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


def test_generate_draft_keeps_responses_parse_first_for_custom_base_url(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1

            class FakeParsedResponse:
                output_parsed = DraftGenerationResult(
                    title="先把卡住的那一刻写出来",
                    body_markdown="# 标题\n\n正文",
                )

            return FakeParsedResponse()

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
    assert parse_calls["count"] == 1
    assert chat_calls["count"] == 0


def test_generate_draft_falls_back_after_internal_server_error_on_custom_base_url(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    captured: dict[str, object] = {}
    request = httpx.Request("POST", "https://proxy.example/v1/responses")
    response = httpx.Response(
        502,
        request=request,
        json={"error": {"message": "Upstream request failed"}},
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise openai.InternalServerError(
                "Upstream request failed",
                response=response,
                body={"error": {"message": "Upstream request failed"}},
            )

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
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
    monkeypatch.setattr(ai_generator_module.time, "sleep", lambda *_args: None)

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
    assert chat_calls["count"] == 1
    assert captured["response_format"] == {"type": "json_object"}


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
    captured: dict[str, object] = {}
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
            captured.update(kwargs)

            class FakeMessage:
                content = '{"title": "先把拧着的那口气放下来", "angle": "从内耗关系里退一步，先把自己救出来"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())
    monkeypatch.setattr(ai_generator_module.time, "sleep", lambda *_args: None)

    result = generator.generate_topic(
        {
            "trend_slug": "life-order-drift",
            "trend_title": "别把日子过反了",
            "source": "manual",
            "heat_score": 83,
            "status": "screening",
        }
    )

    assert result == {
        "title": "先把拧着的那口气放下来",
        "angle": "从内耗关系里退一步，先把自己救出来",
    }
    assert parse_calls["count"] == 1
    assert chat_calls["count"] == 1
    assert "只返回一个 JSON 对象" in str(captured["extra_body"]["instructions"])
    assert "公众号选题编辑" in str(captured["extra_body"]["instructions"])


def test_generate_topic_supports_tracked_article_payload(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds_override=None,
        max_attempts_override=None,
    ):
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


def test_generate_topic_uses_chat_json_fast_path_for_tracked_article_on_custom_base_url(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    captured: dict[str, object] = {}

    def fail_parse_response(*_args, **_kwargs):
        raise AssertionError("tracked article topic generation should use chat-json fast path on custom base url")

    def fake_chat_json_fallback(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds: float,
        max_attempts: int = 3,
        enforce_custom_base_url_retry_floor: bool = True,
        include_custom_base_url_extra_body: bool = True,
        include_response_format: bool = True,
    ):
        captured["instructions"] = instructions
        captured["prompt"] = prompt
        captured["response_format"] = response_format
        captured["timeout_seconds"] = timeout_seconds
        captured["max_attempts"] = max_attempts
        captured["enforce_custom_base_url_retry_floor"] = enforce_custom_base_url_retry_floor
        captured["include_custom_base_url_extra_body"] = include_custom_base_url_extra_body
        return TopicGenerationResult(
            title="先把那句压回去的话说清楚",
            angle="从参考文章提炼新的现实入口",
        )

    monkeypatch.setattr(generator, "_parse_response", fail_parse_response)
    monkeypatch.setattr(generator, "_parse_response_with_chat_json_fallback", fake_chat_json_fallback)

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
        "title": "先把那句压回去的话说清楚",
        "angle": "从参考文章提炼新的现实入口",
    }
    assert captured["response_format"] is TopicGenerationResult
    assert captured["timeout_seconds"] == 60.0
    assert captured["max_attempts"] == 1
    assert captured["enforce_custom_base_url_retry_floor"] is False
    assert captured["include_custom_base_url_extra_body"] is False
    assert "基于参考文章提炼出一个可直接立项的女性情感成长类原创选题" in str(captured["instructions"])


def test_generate_outline_falls_back_after_internal_server_error_on_custom_base_url(monkeypatch) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    captured: dict[str, object] = {}
    request = httpx.Request("POST", "https://proxy.example/v1/responses")
    response = httpx.Response(
        502,
        request=request,
        json={"error": {"message": "Upstream request failed"}},
    )

    class FakeResponses:
        def parse(self, **kwargs):
            parse_calls["count"] += 1
            raise openai.InternalServerError(
                "Upstream request failed",
                response=response,
                body={"error": {"message": "Upstream request failed"}},
            )

    class FakeChatCompletions:
        def create(self, **kwargs):
            chat_calls["count"] += 1
            captured.update(kwargs)

            class FakeMessage:
                content = '{"hook":"先写那种夜里停不下来的脑内追责","outline_body":"1. 为什么停不下来\\n2. 情绪怎样占满日常\\n3. 放下不是为谁开脱"}'

            class FakeChoice:
                message = FakeMessage()

            class FakeResponse:
                choices = [FakeChoice()]

            return FakeResponse()

    class FakeChat:
        completions = FakeChatCompletions()

    monkeypatch.setattr(generator._client, "responses", FakeResponses())
    monkeypatch.setattr(generator._client, "chat", FakeChat())
    monkeypatch.setattr(ai_generator_module.time, "sleep", lambda *_args: None)

    result = generator.generate_outline(
        {
            "trend_title": "原谅别人，也是放过自己",
            "topic_title": "总在夜里反复翻旧账的人，该先处理的不是关系，是大脑停不下来的追责",
            "topic_angle": "把“睡不好、想不停、身体一直绷着”当成情绪损耗的现实接口",
            "project_title": "原谅别人，也是放过自己",
            "tone_profile": {
                "name": "今晚有语",
                "target_word_count": 1400,
            },
        }
    )

    assert result == {
        "hook": "先写那种夜里停不下来的脑内追责",
        "outline_body": "1. 为什么停不下来\n2. 情绪怎样占满日常\n3. 放下不是为谁开脱",
    }
    assert parse_calls["count"] == 1
    assert chat_calls["count"] == 1
    assert "只返回一个 JSON 对象" in str(captured["extra_body"]["instructions"])
    assert "公众号内容策划编辑" in str(captured["extra_body"]["instructions"])


def test_generate_outline_prompt_includes_reference_article_guardrails(monkeypatch) -> None:
    generator = build_generator()
    captured: dict[str, str] = {}

    def fake_parse_response(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds_override=None,
        max_attempts_override=None,
    ):
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

    def fake_parse_response(
        *,
        instructions: str,
        prompt: str,
        response_format,
        timeout_seconds_override=None,
        max_attempts_override=None,
    ):
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


def test_generate_tracked_article_metadata_uses_chat_json_fast_path_on_custom_base_url(
    monkeypatch,
) -> None:
    generator = build_custom_base_url_generator()
    parse_calls = {"count": 0}
    chat_calls = {"count": 0}
    captured: dict[str, object] = {}
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
            captured.update(kwargs)

            class FakeMessage:
                content = (
                    '{"author":"毛姆摘引","summary":"文章围绕原谅与释怀展开，重点提醒人别让反复计较毁掉自己的心境。",'
                    '"structure_notes":"名言起手 + 情绪后果拆解 + 释怀落点。",'
                    '"analysis_theme":"文章真正想讲的是，人要学会把反复计较和恩怨纠缠放下，才能把自己从消耗里解救出来。",'
                    '"analysis_core_conflict":"越想抓着那些让自己不痛快的人和事不放，越容易让内心一直被旧情绪啃食。",'
                    '"analysis_emotional_exit":"从计较和怨怼里松手，把心腾出来重新装进轻松和希望。",'
                    '"analysis_structure_mode":"emotional_engine_direct",'
                    '"analysis_opening_pattern":"从名言和价值判断直接起笔。",'
                    '"analysis_do_not_turn_into":"不要写成关系修复教程或身体告警提醒稿。",'
                    '"tags":["释怀","自我和解"]}'
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
    monkeypatch.setattr(ai_generator_module.time, "sleep", lambda *_args: None)

    result = generator.generate_tracked_article_metadata(
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

    assert result == {
        "author": "毛姆摘引",
        "summary": "文章围绕原谅与释怀展开，重点提醒人别让反复计较毁掉自己的心境。",
        "structure_notes": "名言起手 + 情绪后果拆解 + 释怀落点。",
        "analysis_theme": "文章真正想讲的是，人要学会把反复计较和恩怨纠缠放下，才能把自己从消耗里解救出来。",
        "analysis_core_conflict": "越想抓着那些让自己不痛快的人和事不放，越容易让内心一直被旧情绪啃食。",
        "analysis_emotional_exit": "从计较和怨怼里松手，把心腾出来重新装进轻松和希望。",
        "analysis_structure_mode": "emotional_engine_direct",
        "analysis_opening_pattern": "从名言和价值判断直接起笔。",
        "analysis_do_not_turn_into": "不要写成关系修复教程或身体告警提醒稿。",
        "tags": ["释怀", "自我和解"],
    }
    assert parse_calls["count"] == 0
    assert chat_calls["count"] == 1
    assert "extra_body" not in captured
    assert captured["timeout"] == 60.0


def test_generator_passes_configured_timeout_to_openai_client(monkeypatch) -> None:
    captured_calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self) -> None:
            self.responses = object()

    def fake_openai(**kwargs):
        captured_calls.append(dict(kwargs))
        return FakeClient()

    monkeypatch.setattr(ai_generator_module, "OpenAI", fake_openai)

    OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=45.0,
            openai_image_api_key="",
            openai_image_base_url=None,
            openai_image_request_timeout_seconds=None,
        )
    )

    assert len(captured_calls) == 2
    assert captured_calls[0]["api_key"] == "test-key"
    assert captured_calls[0]["timeout"] == 45.0
    assert captured_calls[1]["api_key"] == "test-key"
    assert captured_calls[1]["timeout"] == 45.0


def test_generator_uses_dedicated_image_client_config_when_present(monkeypatch) -> None:
    captured_calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self) -> None:
            self.responses = object()
            self.images = object()

    def fake_openai(**kwargs):
        captured_calls.append(dict(kwargs))
        return FakeClient()

    monkeypatch.setattr(ai_generator_module, "OpenAI", fake_openai)

    OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="text-key",
            openai_base_url="https://text.example/v1",
            openai_model="test-model",
            openai_request_timeout_seconds=45.0,
            openai_image_api_key="image-key",
            openai_image_base_url="https://image.example/v1",
            openai_image_request_timeout_seconds=120.0,
            openai_image_model="test-image-model",
        )
    )

    assert len(captured_calls) == 2
    assert captured_calls[0] == {
        "api_key": "text-key",
        "base_url": "https://text.example/v1",
        "timeout": 45.0,
        "max_retries": 0,
    }
    assert captured_calls[1] == {
        "api_key": "image-key",
        "base_url": "https://image.example/v1",
        "timeout": 120.0,
        "max_retries": 0,
    }


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

    monkeypatch.setattr(generator._image_client, "images", FakeImages())

    result = generator.generate_cover_image(
        {
            "cover_prompt": "一位中年人低头看手机聊天界面，暖色灯光",
        }
    )

    assert result == b"fake-png-bytes"
    assert captured["size"] == "16:9"
    assert captured["quality"] == "low"
    assert captured["output_format"] == "png"
    assert captured["timeout"] == 240.0
    prompt = str(captured["prompt"])
    assert "16:9" in prompt
    assert "横版封面图" in prompt
    assert "不要把画面做成整张雾化、过度柔焦" in prompt
    assert "封面默认不要手机聊天界面" in prompt
    assert "只画人在看手机" in prompt
    assert "即使原始创意提示词提到聊天界面，也要改成无可读屏幕内容的看手机场景" in prompt
    assert "不要生成双面手机、前后双屏手机或背面屏幕" in prompt
    assert "只保留真实、克制的聊天界面轮廓" not in prompt


def test_generate_cover_image_uses_single_request_budget_by_default_after_timeout(monkeypatch) -> None:
    generator = build_generator()
    calls: list[dict[str, object]] = []

    class FakeImages:
        def generate(self, **kwargs):
            calls.append(kwargs)
            raise openai.APITimeoutError(request=httpx.Request("POST", "https://example.com/v1/images"))

    monkeypatch.setattr(generator._image_client, "images", FakeImages())

    with pytest.raises(openai.APITimeoutError):
        generator.generate_cover_image(
            {
                "cover_prompt": "prompt",
            }
        )

    assert len(calls) == 1
    assert calls[0]["size"] == "16:9"
    assert calls[0]["quality"] == "low"
    assert calls[0]["timeout"] == 240.0


def test_generate_cover_image_can_use_second_variant_when_request_budget_allows(monkeypatch) -> None:
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

    monkeypatch.setattr(generator._image_client, "images", FakeImages())

    result = generator.generate_cover_image(
        {
            "cover_prompt": "prompt",
            "image_generation_max_attempts": 2,
        }
    )

    assert result == b"second-variant"
    assert len(calls) == 2
    assert calls[0]["size"] == "16:9"
    assert calls[0]["quality"] == "low"
    assert calls[0]["timeout"] == 240.0
    assert calls[1]["size"] == "1536x864"
    assert calls[1]["quality"] == "low"
    assert calls[1]["timeout"] == 180.0


def test_generate_cover_image_does_not_retry_transient_provider_errors_for_custom_base_url_by_default(monkeypatch) -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_base_url="https://proxy.example/v1",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=15,
        )
    )
    calls: list[dict[str, object]] = []

    class FakeImages:
        def generate(self, **kwargs):
            calls.append(kwargs)
            raise openai.APIConnectionError(request=httpx.Request("POST", "https://proxy.example/v1/images"))

    monkeypatch.setattr(generator._image_client, "images", FakeImages())
    monkeypatch.setattr(ai_generator_module.time, "sleep", lambda *_args, **_kwargs: None)

    with pytest.raises(openai.APIConnectionError):
        generator.generate_cover_image({"cover_prompt": "prompt"})

    assert len(calls) == 1
    assert calls[0]["size"] == "16:9"
    assert calls[0]["timeout"] == 90.0
    assert "quality" not in calls[0]


def test_generate_cover_image_custom_provider_moves_to_second_variant_after_timeout(monkeypatch) -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://proxy.example/v1",
            openai_model="test-model",
            openai_image_base_url="https://proxy.example/v1",
            openai_image_model="test-image-model",
            openai_request_timeout_seconds=15,
        )
    )
    calls: list[dict[str, object]] = []

    class FakeImages:
        def generate(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise openai.APITimeoutError(request=httpx.Request("POST", "https://proxy.example/v1/images"))

            class FakeImage:
                b64_json = base64.b64encode(b"second-variant-custom").decode("utf-8")

            class FakeResponse:
                data = [FakeImage()]

            return FakeResponse()

    monkeypatch.setattr(generator._image_client, "images", FakeImages())

    result = generator.generate_cover_image({"cover_prompt": "prompt", "image_generation_max_attempts": 2})

    assert result == b"second-variant-custom"
    assert len(calls) == 2
    assert calls[0]["size"] == "16:9"
    assert calls[0]["timeout"] == 90.0
    assert "quality" not in calls[0]
    assert calls[1]["size"] == "1536x864"
    assert calls[1]["timeout"] == 60.0
    assert "quality" not in calls[1]


def test_generate_cover_image_retries_with_ratio_size_after_numeric_size_rejected(monkeypatch) -> None:
    generator = build_generator()
    calls: list[dict[str, object]] = []
    request = httpx.Request("POST", "https://example.com/v1/images")
    response = httpx.Response(
        400,
        request=request,
        json={
            "error": {
                "message": 'Invalid option: expected one of "auto"|"1:1"|"16:9"|"9:16"|"4:3"|"3:4"|"3:2"|"2:3"|"5:4"|"4:5"|"2:1"|"1:2"|"21:9"|"9:21"'
            }
        },
    )

    class FakeImages:
        def generate(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise openai.BadRequestError(
                    "Invalid image size",
                    response=response,
                    body={
                        "error": {
                            "message": 'size: Invalid option: expected one of "auto"|"1:1"|"16:9"|"9:16"|"4:3"|"3:4"|"3:2"|"2:3"|"5:4"|"4:5"|"2:1"|"1:2"|"21:9"|"9:21"'
                        }
                    },
                )

            class FakeImage:
                b64_json = base64.b64encode(b"ratio-variant").decode("utf-8")

            class FakeResponse:
                data = [FakeImage()]

            return FakeResponse()

    monkeypatch.setattr(generator._image_client, "images", FakeImages())

    with pytest.raises(openai.BadRequestError):
        generator.generate_cover_image({"cover_prompt": "prompt"})

    assert len(calls) == 1
    assert calls[0]["size"] == "16:9"


def test_generate_cover_image_retries_without_unrecognized_output_keys(monkeypatch) -> None:
    generator = build_generator()
    calls: list[dict[str, object]] = []
    request = httpx.Request("POST", "https://example.com/v1/images")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": 'Unrecognized keys: "output_format", "quality"'}},
    )

    class FakeImages:
        def generate(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise openai.BadRequestError(
                    "Unsupported request keys",
                    response=response,
                    body={"error": {"message": 'Unrecognized keys: "output_format", "quality"'}},
                )

            class FakeImage:
                b64_json = base64.b64encode(b"provider-compatible").decode("utf-8")

            class FakeResponse:
                data = [FakeImage()]

            return FakeResponse()

    monkeypatch.setattr(generator._image_client, "images", FakeImages())

    result = generator.generate_cover_image({"cover_prompt": "prompt", "image_generation_max_attempts": 2})

    assert result == b"provider-compatible"
    assert len(calls) == 2
    assert calls[0]["output_format"] == "png"
    assert calls[0]["quality"] == "low"
    assert "output_format" not in calls[1]
    assert "quality" not in calls[1]
    assert calls[1]["size"] == "16:9"


def test_generate_cover_image_surfaces_async_task_provider_response(monkeypatch) -> None:
    generator = build_generator()

    class FakeResponse:
        id = "task_123"
        status = "processing"
        data = None

    class FakeImages:
        def generate(self, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(generator._image_client, "images", FakeImages())

    with pytest.raises(RuntimeError) as excinfo:
        generator.generate_cover_image({"cover_prompt": "prompt"})

    assert "async task" in str(excinfo.value)
    assert "task_id=task_123" in str(excinfo.value)
    assert "status=processing" in str(excinfo.value)


def test_get_ai_config_summary_masks_secret_but_reports_runtime_fields() -> None:
    summary = get_ai_config_summary(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://example.com/v1",
            openai_model="test-model",
            openai_trust_env=True,
            openai_image_api_key="image-key",
            openai_image_base_url="https://images.example.com/v1",
            openai_image_model="test-image-model",
            openai_reasoning_effort="medium",
            openai_allow_local_creative_fallbacks=False,
            openai_creative_quality_retry_max_attempts=2,
            openai_image_generation_max_attempts=3,
            openai_request_timeout_seconds=45.0,
            openai_image_request_timeout_seconds=90.0,
        )
    )

    assert summary.api_key_configured is True
    assert summary.base_url == "https://example.com/v1"
    assert summary.model == "test-model"
    assert summary.trust_env is True
    assert summary.image_model == "test-image-model"
    assert summary.image_api_key_configured is True
    assert summary.image_base_url == "https://images.example.com/v1"
    assert summary.image_request_timeout_seconds == 90.0
    assert summary.image_generation_max_attempts == 3
    assert summary.image_uses_dedicated_config is True
    assert summary.creative_quality_retry_max_attempts == 2
    assert summary.allow_local_creative_fallbacks is False
    assert summary.image_fallback_route_configured is False
    assert summary.image_fallback_route_active is False
    assert summary.image_fallback_model is None
    assert summary.image_fallback_base_url is None
    assert summary.image_fallback_effective_model is None
    assert summary.image_fallback_effective_base_url is None
    assert summary.image_fallback_effective_request_timeout_seconds is None
    assert summary.image_fallback_effective_api_key_configured is False
    assert summary.image_fallback_uses_inherited_model is None
    assert summary.image_fallback_uses_inherited_api_key is None
    assert summary.image_fallback_uses_inherited_base_url is None
    assert summary.image_fallback_uses_inherited_request_timeout is None
    assert summary.image_fallback_route_difference_labels == []
    assert summary.image_fallback_route_note == "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。"
    assert summary.image_fallback_route_recovery_actions == [
        "当前还没有备用图片链路；可补充 OPENAI_IMAGE_FALLBACK_MODEL、OPENAI_IMAGE_FALLBACK_BASE_URL、OPENAI_IMAGE_FALLBACK_API_KEY 后再试。",
        "只要 fallback 与主出图链路至少有一项不同，系统才会把它当成第二条图片 API。",
    ]
    assert summary.image_fallback_route_config_hints == [
        "OPENAI_IMAGE_FALLBACK_MODEL：未填写；当前会继承主出图模型 test-image-model",
        "OPENAI_IMAGE_FALLBACK_BASE_URL：未填写；当前会继承主出图接口 https://images.example.com/v1",
        "OPENAI_IMAGE_FALLBACK_API_KEY：未填写；当前会继承主出图链路 Key（已配置）",
        "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS：未填写；当前会继承主出图超时 90 秒",
    ]
    assert summary.image_fallback_route_env_example == [
        "OPENAI_IMAGE_FALLBACK_MODEL=<与主出图不同的图片模型>",
        "OPENAI_IMAGE_FALLBACK_BASE_URL=<可选：独立图片接口；想绕开当前主链路账号池时优先填写>",
        "OPENAI_IMAGE_FALLBACK_API_KEY=<可选：独立图片 Key；想绕开当前主链路账号池时优先填写>",
        "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS=90",
    ]
    assert (
        summary.image_fallback_route_env_example_note
        == "想让系统识别第二条图片 API，以上四项里只要有一项与主链路不同即可；但如果你是想绕开当前主出图账号池，优先单独提供 fallback Base URL 或 fallback Key。"
    )
    assert summary.image_fallback_account_pool_diagnosis_status == "not_configured"
    assert summary.image_fallback_account_pool_diagnosis_label == "未形成第二套上游"
    assert summary.image_fallback_account_pool_diagnosis_note == "当前还没有配置 fallback，所以主路由一旦因为账号池问题失败，系统没有第二套图片上游可以尝试。"
    assert summary.reasoning_effort == "medium"
    assert summary.request_timeout_seconds == 45.0


def test_get_ai_config_summary_falls_back_to_text_config_for_image_chain() -> None:
    summary = get_ai_config_summary(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://example.com/v1",
            openai_model="test-model",
            openai_image_model="test-image-model",
            openai_reasoning_effort="medium",
            openai_request_timeout_seconds=45.0,
            openai_image_api_key="",
            openai_image_base_url=None,
            openai_image_request_timeout_seconds=None,
        )
    )

    assert summary.image_api_key_configured is True
    assert summary.image_base_url == "https://example.com/v1"
    assert summary.image_request_timeout_seconds == 45.0
    assert summary.image_uses_dedicated_config is False
    assert summary.image_fallback_route_configured is False
    assert summary.image_fallback_route_active is False
    assert summary.image_fallback_model is None
    assert summary.image_fallback_base_url is None
    assert summary.image_fallback_effective_model is None
    assert summary.image_fallback_effective_base_url is None
    assert summary.image_fallback_effective_request_timeout_seconds is None
    assert summary.image_fallback_effective_api_key_configured is False
    assert summary.image_fallback_uses_inherited_model is None
    assert summary.image_fallback_uses_inherited_api_key is None
    assert summary.image_fallback_uses_inherited_base_url is None
    assert summary.image_fallback_uses_inherited_request_timeout is None
    assert summary.image_fallback_route_difference_labels == []
    assert summary.image_fallback_route_note == "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。"
    assert summary.image_fallback_route_recovery_actions == [
        "当前还没有备用图片链路；可补充 OPENAI_IMAGE_FALLBACK_MODEL、OPENAI_IMAGE_FALLBACK_BASE_URL、OPENAI_IMAGE_FALLBACK_API_KEY 后再试。",
        "只要 fallback 与主出图链路至少有一项不同，系统才会把它当成第二条图片 API。",
    ]
    assert summary.image_fallback_route_config_hints == [
        "OPENAI_IMAGE_FALLBACK_MODEL：未填写；当前会继承主出图模型 test-image-model",
        "OPENAI_IMAGE_FALLBACK_BASE_URL：未填写；当前会继承主出图接口 https://example.com/v1",
        "OPENAI_IMAGE_FALLBACK_API_KEY：未填写；当前会继承主出图链路 Key（已配置）",
        "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS：未填写；当前会继承主出图超时 45 秒",
    ]
    assert summary.image_fallback_route_env_example == [
        "OPENAI_IMAGE_FALLBACK_MODEL=<与主出图不同的图片模型>",
        "OPENAI_IMAGE_FALLBACK_BASE_URL=<可选：独立图片接口；想绕开当前主链路账号池时优先填写>",
        "OPENAI_IMAGE_FALLBACK_API_KEY=<可选：独立图片 Key；想绕开当前主链路账号池时优先填写>",
        "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS=45",
    ]
    assert (
        summary.image_fallback_route_env_example_note
        == "想让系统识别第二条图片 API，以上四项里只要有一项与主链路不同即可；但如果你是想绕开当前主出图账号池，优先单独提供 fallback Base URL 或 fallback Key。"
    )
    assert summary.image_fallback_account_pool_diagnosis_status == "not_configured"
    assert summary.image_fallback_account_pool_diagnosis_label == "未形成第二套上游"
    assert summary.image_fallback_account_pool_diagnosis_note == "当前还没有配置 fallback，所以主路由一旦因为账号池问题失败，系统没有第二套图片上游可以尝试。"
    assert summary.trust_env is False


def test_get_ai_config_summary_marks_duplicate_fallback_settings_as_inactive() -> None:
    summary = get_ai_config_summary(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://example.com/v1",
            openai_model="test-model",
            openai_image_model="gpt-image-2",
            openai_image_base_url=None,
            openai_image_request_timeout_seconds=None,
            openai_image_fallback_model="gpt-image-2",
            openai_reasoning_effort="medium",
            openai_request_timeout_seconds=45.0,
        )
    )

    assert summary.image_fallback_route_configured is True
    assert summary.image_fallback_route_active is False
    assert summary.image_fallback_model is None
    assert summary.image_fallback_base_url is None
    assert summary.image_fallback_effective_model == "gpt-image-2"
    assert summary.image_fallback_effective_base_url == "https://example.com/v1"
    assert summary.image_fallback_effective_request_timeout_seconds == 45.0
    assert summary.image_fallback_effective_api_key_configured is True
    assert summary.image_fallback_uses_inherited_model is False
    assert summary.image_fallback_uses_inherited_api_key is True
    assert summary.image_fallback_uses_inherited_base_url is True
    assert summary.image_fallback_uses_inherited_request_timeout is True
    assert summary.image_fallback_route_difference_labels == []
    assert summary.image_fallback_route_note == "已填写 fallback 字段，但生效后与主出图链路完全一致，所以当前还没有形成第二条图片 API。"
    assert summary.image_fallback_route_recovery_actions == [
        "当前 fallback 字段已经填写，但它与主出图链路完全重合，还没有形成第二条图片 API。",
        "至少让 OPENAI_IMAGE_FALLBACK_MODEL、OPENAI_IMAGE_FALLBACK_BASE_URL、OPENAI_IMAGE_FALLBACK_API_KEY 或超时配置中的一项与主链路不同。",
    ]
    assert summary.image_fallback_route_config_hints == [
        "OPENAI_IMAGE_FALLBACK_MODEL：已填写 gpt-image-2",
        "OPENAI_IMAGE_FALLBACK_BASE_URL：未填写；当前会继承主出图接口 https://example.com/v1",
        "OPENAI_IMAGE_FALLBACK_API_KEY：未填写；当前会继承主出图链路 Key（已配置）",
        "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS：未填写；当前会继承主出图超时 45 秒",
    ]
    assert summary.image_fallback_route_env_example == [
        "OPENAI_IMAGE_FALLBACK_MODEL=<与主出图不同的图片模型>",
        "OPENAI_IMAGE_FALLBACK_BASE_URL=<可选：独立图片接口；想绕开当前主链路账号池时优先填写>",
        "OPENAI_IMAGE_FALLBACK_API_KEY=<可选：独立图片 Key；想绕开当前主链路账号池时优先填写>",
        "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS=45",
    ]
    assert (
        summary.image_fallback_route_env_example_note
        == "想让系统识别第二条图片 API，以上四项里只要有一项与主链路不同即可；但如果你是想绕开当前主出图账号池，优先单独提供 fallback Base URL 或 fallback Key。"
    )
    assert summary.image_fallback_account_pool_diagnosis_status == "inactive"
    assert summary.image_fallback_account_pool_diagnosis_label == "还没形成第二条图片 API"
    assert summary.image_fallback_account_pool_diagnosis_note == "fallback 字段虽然填写了，但它与主链路还没有拉开差异，因此也谈不上绕开主账号池。"


def test_get_ai_config_summary_reports_active_fallback_difference_labels() -> None:
    summary = get_ai_config_summary(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://example.com/v1",
            openai_model="test-model",
            openai_image_model="gpt-image-2",
            openai_image_base_url=None,
            openai_image_request_timeout_seconds=None,
            openai_image_fallback_model="fallback-image-model",
            openai_reasoning_effort="medium",
            openai_request_timeout_seconds=45.0,
        )
    )

    assert summary.image_fallback_route_configured is True
    assert summary.image_fallback_route_active is True
    assert summary.image_fallback_model == "fallback-image-model"
    assert summary.image_fallback_base_url == summary.image_base_url
    assert summary.image_fallback_effective_model == "fallback-image-model"
    assert summary.image_fallback_effective_base_url == summary.image_base_url
    assert summary.image_fallback_effective_request_timeout_seconds == 45.0
    assert summary.image_fallback_effective_api_key_configured is True
    assert summary.image_fallback_uses_inherited_model is False
    assert summary.image_fallback_uses_inherited_api_key is True
    assert summary.image_fallback_uses_inherited_base_url is True
    assert summary.image_fallback_uses_inherited_request_timeout is True
    assert summary.image_fallback_route_difference_labels == ["模型"]
    assert summary.image_fallback_route_note == "备用图片链路已生效；它与主出图链路的差异项：模型。"
    assert summary.image_fallback_route_recovery_actions == [
        "当前备用图片链路已经形成第二条图片 API；建议点一次“探测主/备路由”，确认它能独立返回图片。",
        "只有出图请求预算大于 1 时，正式出封面才会在主链路失败后尝试切到这条备用图片链路。",
    ]
    assert summary.image_fallback_route_config_hints == [
        "OPENAI_IMAGE_FALLBACK_MODEL：已填写 fallback-image-model",
        "OPENAI_IMAGE_FALLBACK_BASE_URL：未填写；当前会继承主出图接口 https://example.com/v1",
        "OPENAI_IMAGE_FALLBACK_API_KEY：未填写；当前会继承主出图链路 Key（已配置）",
        "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS：未填写；当前会继承主出图超时 45 秒",
    ]
    assert summary.image_fallback_route_env_example == [
        "OPENAI_IMAGE_FALLBACK_MODEL=<与主出图不同的图片模型>",
        "OPENAI_IMAGE_FALLBACK_BASE_URL=<可选：独立图片接口；想绕开当前主链路账号池时优先填写>",
        "OPENAI_IMAGE_FALLBACK_API_KEY=<可选：独立图片 Key；想绕开当前主链路账号池时优先填写>",
        "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS=45",
    ]
    assert (
        summary.image_fallback_route_env_example_note
        == "想让系统识别第二条图片 API，以上四项里只要有一项与主链路不同即可；但如果你是想绕开当前主出图账号池，优先单独提供 fallback Base URL 或 fallback Key。"
    )
    assert summary.image_fallback_account_pool_diagnosis_status == "shared_pool"
    assert summary.image_fallback_account_pool_diagnosis_label == "仍可能共用主账号池"
    assert summary.image_fallback_account_pool_diagnosis_note == "这条 fallback 目前只改了模型或超时，仍沿用主出图接口和主 Key；如果主账号池出问题，它大概率也会一起失败。"


def test_get_ai_config_summary_marks_distinct_fallback_base_url_as_more_likely_to_bypass_primary_pool() -> None:
    summary = get_ai_config_summary(
        Settings(
            openai_api_key="test-key",
            openai_base_url="https://example.com/v1",
            openai_model="test-model",
            openai_image_model="gpt-image-2",
            openai_image_base_url="https://primary-image.example/v1",
            openai_image_fallback_model="fallback-image-model",
            openai_image_fallback_base_url="https://fallback-image.example/v1",
            openai_reasoning_effort="medium",
            openai_request_timeout_seconds=45.0,
            openai_image_request_timeout_seconds=45.0,
        )
    )

    assert summary.image_fallback_account_pool_diagnosis_status == "independent_hint"
    assert summary.image_fallback_account_pool_diagnosis_label == "有机会绕开主账号池"
    assert summary.image_fallback_account_pool_diagnosis_note == "fallback 已切到独立接口，但仍沿用主 Key；它是否能绕开主账号池，取决于这个接口背后的账号池是否独立。"


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


def test_check_connection_retries_transient_upstream_errors() -> None:
    generator = build_custom_base_url_generator()
    attempts = {"count": 0}
    request = httpx.Request("POST", "https://proxy.example/v1/responses")
    response = httpx.Response(503, request=request, json={"error": {"message": "Service temporarily unavailable"}})

    class FlakyResponses:
        def create(self, **kwargs):
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise openai.InternalServerError(
                    "Service temporarily unavailable",
                    response=response,
                    body={"error": {"message": "Service temporarily unavailable"}},
                )

            class FakeResponse:
                output_text = "OK"

            return FakeResponse()

    generator._client.responses = FlakyResponses()

    generator.check_connection()

    assert attempts["count"] == 2


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


def test_run_ai_image_config_check_returns_success_when_probe_passes(monkeypatch) -> None:
    class PassingGenerator:
        def __init__(self, config) -> None:
            self.config = config

        def check_image_connection(self) -> str:
            return "primary"

    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", PassingGenerator)

    result = run_ai_image_config_check(
        Settings(
            openai_api_key="",
            openai_image_api_key="image-key",
            openai_image_model="test-image-model",
        )
    )

    assert result.ok is True
    assert result.status == "ok"
    assert "图片配置检测通过" in result.message
    assert result.route_label == "primary"
    assert result.recovery_actions == []


def test_run_ai_image_config_check_reports_fallback_route_success(monkeypatch) -> None:
    class FallbackPassingGenerator:
        def __init__(self, config) -> None:
            self.config = config

        def check_image_connection(self) -> str:
            return "fallback"

    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", FallbackPassingGenerator)

    result = run_ai_image_config_check(
        Settings(
            openai_api_key="test-key",
            openai_image_model="test-image-model",
            openai_image_fallback_model="fallback-image-model",
        )
    )

    assert result.ok is True
    assert result.status == "ok"
    assert "备用图片链路" in result.message
    assert result.route_label == "fallback"
    assert result.recovery_actions == [
        "这次检测已经命中备用图片链路，说明第二条图片 API 可用；正式出封面是否切到备用链路，还取决于出图请求预算是否大于 1。",
    ]


def test_run_ai_image_config_check_surfaces_upstream_failures(monkeypatch) -> None:
    request = httpx.Request("POST", "https://example.com/v1/images")
    response = httpx.Response(503, request=request, json={"error": {"message": "No available compatible accounts"}})

    class FailingGenerator:
        def __init__(self, _config) -> None:
            pass

        def check_image_connection(self) -> None:
            raise openai.InternalServerError(
                "No available compatible accounts",
                response=response,
                body={"error": {"message": "No available compatible accounts"}},
            )

    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", FailingGenerator)

    result = run_ai_image_config_check(
        Settings(
            openai_api_key="test-key",
            openai_image_model="test-image-model",
        )
    )

    assert result.ok is False
    assert result.status == "upstream_error"
    assert "当前图片 API 暂无可用账号" in result.message
    assert "不会改走本地兜底" in result.message
    assert "No available compatible accounts" in result.message
    assert result.route_label is None
    assert "这次更像是上游账号池暂时不可用，不是本地封面逻辑回退。" in result.recovery_actions
    assert "当前封面保持 API-only，不会改走本地兜底。" in result.recovery_actions


def test_run_ai_image_config_check_does_not_pretend_duplicate_fallback_settings_are_active(monkeypatch) -> None:
    request = httpx.Request("POST", "https://example.com/v1/images")
    response = httpx.Response(503, request=request, json={"error": {"message": "No available compatible accounts"}})

    class FailingGenerator:
        def __init__(self, _config) -> None:
            pass

        def check_image_connection(self) -> None:
            raise openai.InternalServerError(
                "No available compatible accounts",
                response=response,
                body={"error": {"message": "No available compatible accounts"}},
            )

    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", FailingGenerator)

    result = run_ai_image_config_check(
        Settings(
            openai_api_key="test-key",
            openai_image_model="gpt-image-2",
            openai_image_fallback_model="gpt-image-2",
        )
    )

    assert result.ok is False
    assert result.status == "upstream_error"
    assert "当前 fallback 字段已经填写，但它与主出图链路完全重合，还没有形成第二条图片 API。" in result.recovery_actions


def test_run_ai_image_config_check_reports_invalid_fallback_model_as_image_model_mismatch(monkeypatch) -> None:
    request = httpx.Request("POST", "https://example.com/v1/images")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": 'images endpoint requires an image model, got "fallback-image-model"'}},
    )

    class FailingGenerator:
        def __init__(self, _config) -> None:
            pass

        def check_image_connection(self) -> None:
            error = openai.BadRequestError(
                "invalid image model",
                response=response,
                body={"error": {"message": 'images endpoint requires an image model, got "fallback-image-model"'}},
            )
            error.cover_image_route_label = "fallback"
            error.cover_image_route_model = "fallback-image-model"
            error.cover_image_route_base_url = "https://example.com/v1"
            raise error

    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", FailingGenerator)

    result = run_ai_image_config_check(
        Settings(
            openai_api_key="test-key",
            openai_image_model="gpt-image-2",
            openai_image_fallback_model="fallback-image-model",
        )
    )

    assert result.ok is False
    assert result.status == "bad_request"
    assert result.route_label == "fallback"
    assert 'requires an image model' in result.message
    assert result.recovery_actions == [
        "备用图片链路已经打到了图片接口，但所填模型不是图片模型；请改成上游支持的图片模型名。",
        "这次报错发生在 fallback 路由，优先检查 OPENAI_IMAGE_FALLBACK_MODEL 是否真的是图片模型。",
    ]


def test_run_ai_image_route_probe_reports_each_route(monkeypatch) -> None:
    request = httpx.Request("POST", "https://fallback-image.example/v1/images")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": 'images endpoint requires an image model, got "fallback-image-model"'}},
    )

    class ProbeGenerator:
        def __init__(self, _config) -> None:
            self._image_routes = [
                {
                    "label": "primary",
                    "model": "gpt-image-2",
                    "base_url": "https://primary-image.example/v1",
                },
                {
                    "label": "fallback",
                    "model": "fallback-image-model",
                    "base_url": "https://fallback-image.example/v1",
                },
            ]

        def _generate_cover_image_with_route(self, _prompt: str) -> tuple[bytes, str]:
            only_route = self._image_routes[0]
            route_label = str(only_route["label"])
            if route_label == "primary":
                return b"cover-bytes", route_label
            error = openai.BadRequestError(
                "invalid image model",
                response=response,
                body={"error": {"message": 'images endpoint requires an image model, got "fallback-image-model"'}},
            )
            error.cover_image_route_label = "fallback"
            error.cover_image_route_model = "fallback-image-model"
            error.cover_image_route_base_url = "https://fallback-image.example/v1"
            raise error

    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", ProbeGenerator)

    result = run_ai_image_route_probe(
        Settings(
            openai_api_key="test-key",
            openai_image_model="gpt-image-2",
            openai_image_fallback_model="fallback-image-model",
            openai_image_fallback_base_url="https://fallback-image.example/v1",
        )
    )

    assert result.any_ok is True
    assert [route.route_label for route in result.routes] == ["primary", "fallback"]
    assert result.routes[0].ok is True
    assert result.routes[0].status == "ok"
    assert "图片配置检测通过" in result.routes[0].message
    assert result.routes[1].ok is False
    assert result.routes[1].status == "bad_request"
    assert 'requires an image model' in result.routes[1].message
    assert result.routes[1].recovery_actions == [
        "备用图片链路已经打到了图片接口，但所填模型不是图片模型；请改成上游支持的图片模型名。",
        "这次报错发生在 fallback 路由，优先检查 OPENAI_IMAGE_FALLBACK_MODEL 是否真的是图片模型。",
    ]


def test_run_ai_image_route_probe_adds_not_configured_fallback_placeholder(monkeypatch) -> None:
    class PrimaryOnlyProbeGenerator:
        def __init__(self, _config) -> None:
            self._image_routes = [
                {
                    "label": "primary",
                    "model": "gpt-image-2",
                    "base_url": "https://primary-image.example/v1",
                }
            ]

        def _generate_cover_image_with_route(self, _prompt: str) -> tuple[bytes, str]:
            return b"cover-bytes", "primary"

    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", PrimaryOnlyProbeGenerator)

    result = run_ai_image_route_probe(
        Settings(
            openai_api_key="test-key",
            openai_image_model="gpt-image-2",
        )
    )

    assert [route.route_label for route in result.routes] == ["primary", "fallback"]
    fallback_route = result.routes[1]
    assert fallback_route.ok is False
    assert fallback_route.status == "not_configured"
    assert fallback_route.message == "当前未配置备用图片链路；主出图链路出错时，不会自动切到第二条图片 API。"
    assert fallback_route.recovery_actions == [
        "当前还没有备用图片链路；可补充 OPENAI_IMAGE_FALLBACK_MODEL、OPENAI_IMAGE_FALLBACK_BASE_URL、OPENAI_IMAGE_FALLBACK_API_KEY 后再试。",
        "只要 fallback 与主出图链路至少有一项不同，系统才会把它当成第二条图片 API。",
    ]


def test_run_ai_image_route_probe_adds_inactive_fallback_placeholder(monkeypatch) -> None:
    class PrimaryOnlyProbeGenerator:
        def __init__(self, _config) -> None:
            self._image_routes = [
                {
                    "label": "primary",
                    "model": "gpt-image-2",
                    "base_url": "https://primary-image.example/v1",
                }
            ]

        def _generate_cover_image_with_route(self, _prompt: str) -> tuple[bytes, str]:
            return b"cover-bytes", "primary"

    monkeypatch.setattr(ai_generator_module, "OpenAIWorkbenchGenerator", PrimaryOnlyProbeGenerator)

    result = run_ai_image_route_probe(
        Settings(
            openai_api_key="test-key",
            openai_image_model="gpt-image-2",
            openai_image_fallback_model="gpt-image-2",
        )
    )

    assert [route.route_label for route in result.routes] == ["primary", "fallback"]
    fallback_route = result.routes[1]
    assert fallback_route.ok is False
    assert fallback_route.status == "inactive"
    assert fallback_route.configured_model == "gpt-image-2"
    assert fallback_route.message == "已填写 fallback 字段，但生效后与主出图链路完全一致，所以当前还没有形成第二条图片 API。"
    assert fallback_route.recovery_actions == [
        "当前 fallback 字段已经填写，但它与主出图链路完全重合，还没有形成第二条图片 API。",
        "至少让 OPENAI_IMAGE_FALLBACK_MODEL、OPENAI_IMAGE_FALLBACK_BASE_URL、OPENAI_IMAGE_FALLBACK_API_KEY 或超时配置中的一项与主链路不同。",
    ]


def test_generate_cover_image_uses_fallback_route_when_primary_provider_has_no_compatible_accounts(monkeypatch) -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_image_api_key="image-key",
            openai_image_base_url="https://primary-image.example/v1",
            openai_image_model="primary-image-model",
            openai_image_fallback_base_url="https://fallback-image.example/v1",
            openai_image_fallback_model="fallback-image-model",
        )
    )

    request = httpx.Request("POST", "https://primary-image.example/v1/images")
    response = httpx.Response(503, request=request, json={"error": {"message": "No available compatible accounts"}})
    calls: list[tuple[str, dict[str, object]]] = []

    class PrimaryImages:
        def generate(self, **kwargs):
            calls.append(("primary", kwargs))
            raise openai.InternalServerError(
                "No available compatible accounts",
                response=response,
                body={"error": {"message": "No available compatible accounts"}},
            )

    class FakeImage:
        b64_json = base64.b64encode(b"fallback-cover-bytes").decode("utf-8")

    class FallbackResponse:
        data = [FakeImage()]

    class FallbackImages:
        def generate(self, **kwargs):
            calls.append(("fallback", kwargs))
            return FallbackResponse()

    monkeypatch.setattr(generator._image_client, "images", PrimaryImages())
    monkeypatch.setattr(generator._image_routes[1]["client"], "images", FallbackImages())

    result = generator.generate_cover_image({"cover_prompt": "prompt", "image_generation_max_attempts": 2})

    assert result == b"fallback-cover-bytes"
    assert calls[0][0] == "primary"
    assert calls[0][1]["model"] == "primary-image-model"
    assert any(name == "fallback" for name, _kwargs in calls)
    fallback_call = next(kwargs for name, kwargs in calls if name == "fallback")
    assert fallback_call["model"] == "fallback-image-model"


def test_generate_cover_image_with_route_info_reports_used_route(monkeypatch) -> None:
    generator = OpenAIWorkbenchGenerator(
        Settings(
            openai_api_key="test-key",
            openai_image_api_key="image-key",
            openai_image_base_url="https://primary-image.example/v1",
            openai_image_model="primary-image-model",
            openai_image_fallback_base_url="https://fallback-image.example/v1",
            openai_image_fallback_model="fallback-image-model",
        )
    )

    request = httpx.Request("POST", "https://primary-image.example/v1/images")
    response = httpx.Response(503, request=request, json={"error": {"message": "No available compatible accounts"}})

    class PrimaryImages:
        def generate(self, **kwargs):
            raise openai.InternalServerError(
                "No available compatible accounts",
                response=response,
                body={"error": {"message": "No available compatible accounts"}},
            )

    class FakeImage:
        b64_json = base64.b64encode(b"fallback-cover-bytes").decode("utf-8")

    class FallbackResponse:
        data = [FakeImage()]

    class FallbackImages:
        def generate(self, **kwargs):
            return FallbackResponse()

    monkeypatch.setattr(generator._image_client, "images", PrimaryImages())
    monkeypatch.setattr(generator._image_routes[1]["client"], "images", FallbackImages())

    image_bytes, route_info = generator.generate_cover_image_with_route_info(
        {"cover_prompt": "prompt", "image_generation_max_attempts": 2}
    )

    assert image_bytes == b"fallback-cover-bytes"
    assert route_info == {
        "label": "fallback",
        "model": "fallback-image-model",
        "base_url": "https://fallback-image.example/v1",
    }
    assert generator.last_cover_image_route_info == route_info
