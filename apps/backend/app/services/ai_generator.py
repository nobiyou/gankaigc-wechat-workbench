from __future__ import annotations

import base64
from functools import lru_cache
import time
from typing import TypeVar

import openai
from openai import APITimeoutError
from openai import OpenAI
from pydantic import BaseModel

from app.core.settings import Settings, settings


class OutlineGenerationResult(BaseModel):
    hook: str
    outline_body: str


class TopicGenerationResult(BaseModel):
    title: str
    angle: str


class DraftGenerationResult(BaseModel):
    title: str
    body_markdown: str


class AssetGenerationResult(BaseModel):
    title_options: list[str]
    cover_prompt: str
    cover_copy: str
    social_teaser: str


class PublishPackageGenerationResult(BaseModel):
    abstract: str
    tags: list[str]
    editor_note: str


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


class OpenAIWorkbenchGenerator:
    def __init__(self, config: Settings) -> None:
        if not config.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        client_kwargs: dict[str, str] = {"api_key": config.openai_api_key}
        if config.openai_base_url:
            client_kwargs["base_url"] = config.openai_base_url
        client_kwargs["timeout"] = config.openai_request_timeout_seconds

        self._client = OpenAI(**client_kwargs)
        self._model = config.openai_model
        self._image_model = config.openai_image_model
        self._reasoning_effort = config.openai_reasoning_effort
        self._request_timeout_seconds = config.openai_request_timeout_seconds

    def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
        tone_profile = payload.get("tone_profile") or {}
        target_word_count = tone_profile.get("target_word_count")
        target_wording = (
            f"目标字数：{target_word_count}\n"
            "请按目标字数规划篇幅，保证 4 到 6 段的大纲能自然支撑正文长度。\n"
            "避免在大纲阶段写得过满，每一段只保留核心推进点，不要预写过多案例、分叉解释和重复论述。\n"
            if target_word_count
            else ""
        )
        result = self._parse_response(
            instructions=(
                "你是公众号内容策划编辑。"
                "请基于给定选题，输出一个适合女性情感成长公众号的文章大纲。"
                "语言要克制、具体、可写，避免空泛口号。"
            ),
            prompt=(
                f"趋势标题：{payload['trend_title']}\n"
                f"选题标题：{payload['topic_title']}\n"
                f"切入角度：{payload['topic_angle']}\n"
                f"项目标题：{payload['project_title']}\n\n"
                f"{target_wording}"
                "返回：\n"
                "1. 一个 1 句话的情绪钩子 hook\n"
                "2. 一个 4 到 6 段的 markdown 大纲 outline_body"
            ),
            response_format=OutlineGenerationResult,
        )
        return result.model_dump()

    def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
        source_type = str(payload.get("source_type") or "trend")
        if source_type == "tracked_article":
            source_prompt = (
                f"来源类型：{source_type}\n"
                f"参考文章 slug：{payload['source_ref_slug']}\n"
                f"参考文章标题：{payload['article_title']}\n"
                f"作者：{payload['author']}\n"
                f"来源账号：{payload['source_name'] or '未知公众号'}\n"
                f"摘要：{payload['summary']}\n"
                f"结构备注：{payload['structure_notes']}\n"
                f"标签：{' / '.join(payload.get('tags') or []) or '无'}\n"
            )
            instructions = (
                "你是公众号选题编辑。"
                "请基于参考文章提炼出一个可直接立项的女性情感成长类原创选题。"
                "不要复述原标题，要重新组织成更适合继续创作的选题。"
            )
        else:
            source_prompt = (
                f"趋势 slug：{payload['trend_slug']}\n"
                f"趋势标题：{payload['trend_title']}\n"
                f"来源：{payload['source']}\n"
                f"热度：{payload['heat_score']}\n"
                f"当前状态：{payload['status']}\n"
            )
            instructions = (
                "你是公众号选题编辑。"
                "请基于热点线索提炼成一个可直接立项的女性情感成长类选题。"
                "标题要像真实选题，不要写成平台标题党。"
            )
        result = self._parse_response(
            instructions=instructions,
            prompt=(
                f"{source_prompt}\n"
                "返回：\n"
                "1. 选题标题 title\n"
                "2. 切入角度 angle"
            ),
            response_format=TopicGenerationResult,
        )
        return result.model_dump()

    def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
        outline = payload["outline"]
        tone_profile = payload.get("tone_profile") or {}
        target_word_count = tone_profile.get("target_word_count")
        review_comment = str(payload.get("review_comment") or "").strip()
        polish_instruction = str(payload.get("polish_instruction") or "").strip()
        current_draft = payload.get("draft") or {}
        review_section = (
            f"\n审核修改意见：{review_comment}\n"
            "请保留原选题和大纲方向，重点根据这条意见重写正文。"
            if review_comment
            else ""
        )
        polish_section = (
            f"\n精修要求：{polish_instruction}\n"
            f"当前草稿标题：{current_draft['title']}\n"
            f"当前草稿内容：\n{current_draft['body_markdown']}\n"
            "请基于现有草稿精修，不要偏离原有主题与结构主线。\n"
            if polish_instruction and current_draft
            else ""
        )
        target_wording = (
            f"目标字数：{target_word_count}\n"
            "正文篇幅请严格贴近目标字数，允许上下浮动 10% 到 15%。\n"
            "如果明显超出目标字数，请主动压缩场景、避免重复抒情和重复论述。\n"
            if target_word_count
            else ""
        )
        result = self._parse_response(
            instructions=(
                "你是公众号正文作者。"
                "请把选题和大纲扩写成一篇可直接进入编辑流程的中文初稿。"
                "要求有清晰标题、自然分段、具体场景和收束段。"
            ),
            prompt=(
                f"趋势标题：{payload['trend_title']}\n"
                f"选题标题：{payload['topic_title']}\n"
                f"切入角度：{payload['topic_angle']}\n"
                f"项目标题：{payload['project_title']}\n"
                f"{target_wording}"
                f"大纲钩子：{outline['hook']}\n"
                f"大纲内容：\n{outline['outline_body']}\n"
                f"{review_section}\n"
                f"{polish_section}\n"
                "返回：\n"
                "1. 标题 title\n"
                "2. 正文 markdown body_markdown"
            ),
            response_format=DraftGenerationResult,
        )
        return result.model_dump()

    def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
        draft = payload["draft"]
        review_comment = str(payload.get("review_comment") or "").strip()
        review_section = (
            f"\n审核修改意见：{review_comment}\n"
            "请根据这条意见调整封面文案、标题备选和分发导语。"
            if review_comment
            else ""
        )
        result = self._parse_response(
            instructions=(
                "你是公众号包装编辑。"
                "请围绕正文产出封面和分发素材，保持克制、真实、不鸡汤。"
            ),
            prompt=(
                f"趋势标题：{payload['trend_title']}\n"
                f"选题标题：{payload['topic_title']}\n"
                f"切入角度：{payload['topic_angle']}\n"
                f"项目标题：{payload['project_title']}\n"
                f"正文标题：{draft['title']}\n"
                f"正文内容：\n{draft['body_markdown']}\n"
                f"{review_section}\n"
                "返回：\n"
                "1. 3 个标题备选 title_options\n"
                "2. 1 条封面图提示词 cover_prompt\n"
                "3. 1 条封面文案 cover_copy\n"
                "4. 1 条社媒导语 social_teaser"
            ),
            response_format=AssetGenerationResult,
        )
        return result.model_dump()

    def generate_cover_image(self, payload: dict[str, object]) -> bytes:
        prompt = str(payload["cover_prompt"])
        request_variants = [
            {
                "size": "1024x1024",
                "quality": "low",
                "timeout": max(self._request_timeout_seconds, 180.0),
            },
            {
                "size": "1536x1024",
                "quality": "low",
                "timeout": max(self._request_timeout_seconds, 240.0),
            },
        ]
        last_error: Exception | None = None
        for variant in request_variants:
            try:
                response = self._client.images.generate(
                    model=self._image_model,
                    prompt=prompt,
                    output_format="png",
                    size=variant["size"],
                    quality=variant["quality"],
                    timeout=variant["timeout"],
                )
                if not response.data:
                    raise RuntimeError("OpenAI returned no image data")

                image = response.data[0]
                if image.b64_json:
                    return base64.b64decode(image.b64_json)
                raise RuntimeError("OpenAI returned no base64 image payload")
            except APITimeoutError as exc:
                last_error = exc
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI image generation failed without a captured exception")

    def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
        review_comment = str(payload.get("review_comment") or "").strip()
        review_section = (
            f"\n审核修改意见：{review_comment}\n"
            "请确认摘要、标签和编辑备注已经响应这条意见。"
            if review_comment
            else ""
        )
        result = self._parse_response(
            instructions=(
                "你是公众号发布编辑。"
                "请基于正文和素材，为公众号发布环节输出摘要、标签和编辑备注。"
                "内容要简洁、可执行，不要空话。"
            ),
            prompt=(
                f"项目标题：{payload['project_title']}\n"
                f"正文标题：{payload['draft']['title']}\n"
                f"正文内容：\n{payload['draft']['body_markdown']}\n\n"
                f"封面文案：{payload['assets']['cover_copy']}\n"
                f"分发导语：{payload['assets']['social_teaser']}\n"
                f"标题备选：{' / '.join(payload['assets']['title_options'])}\n"
                f"{review_section}\n"
                "返回：\n"
                "1. 发布摘要 abstract\n"
                "2. 3 到 5 个标签 tags\n"
                "3. 编辑备注 editor_note"
            ),
            response_format=PublishPackageGenerationResult,
        )
        return result.model_dump()

    def _parse_response(
        self,
        *,
        instructions: str,
        prompt: str,
        response_format: type[ResponseModelT],
    ) -> ResponseModelT:
        request_kwargs: dict[str, object] = {
            "model": self._model,
            "instructions": instructions,
            "input": prompt,
            "text_format": response_format,
        }
        if self._reasoning_effort:
            request_kwargs["reasoning"] = {"effort": self._reasoning_effort}

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = self._client.responses.parse(**request_kwargs)
                parsed = response.output_parsed
                if parsed is None:
                    raise RuntimeError("OpenAI returned no structured output")
                return parsed
            except (openai.InternalServerError, openai.RateLimitError, openai.APIConnectionError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI response parsing failed without a captured exception")


@lru_cache(maxsize=1)
def get_default_generator() -> OpenAIWorkbenchGenerator:
    return OpenAIWorkbenchGenerator(settings)
