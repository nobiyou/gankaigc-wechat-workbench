from __future__ import annotations

import base64
from functools import lru_cache
import json
import time
from typing import TypeVar

import openai
from openai import APIConnectionError
from openai import APITimeoutError
from openai import OpenAI
from pydantic import BaseModel

from app.core.settings import Settings, settings
from app.schemas.settings import AIConfigCheckResult, AIConfigSummary
from app.services.prompt_templates import (
    build_assets_prompt,
    build_cover_image_prompt,
    build_draft_prompt,
    build_outline_prompt,
    build_publish_package_prompt,
    build_tracked_article_metadata_prompt,
    build_topic_prompt,
)


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


class TrackedArticleMetadataGenerationResult(BaseModel):
    author: str
    summary: str
    structure_notes: str
    tags: list[str]


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
        prompt_template = build_outline_prompt(payload)
        result = self._parse_response(
            instructions=prompt_template.instructions,
            prompt=prompt_template.prompt,
            response_format=OutlineGenerationResult,
        )
        return result.model_dump()

    def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
        prompt_template = build_topic_prompt(payload)
        result = self._parse_response(
            instructions=prompt_template.instructions,
            prompt=prompt_template.prompt,
            response_format=TopicGenerationResult,
        )
        return result.model_dump()

    def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
        prompt_template = build_draft_prompt(payload)
        result = self._parse_response(
            instructions=prompt_template.instructions,
            prompt=prompt_template.prompt,
            response_format=DraftGenerationResult,
        )
        return result.model_dump()

    def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
        prompt_template = build_assets_prompt(payload)
        result = self._parse_response(
            instructions=prompt_template.instructions,
            prompt=prompt_template.prompt,
            response_format=AssetGenerationResult,
        )
        return result.model_dump()

    def generate_cover_image(self, payload: dict[str, object]) -> bytes:
        prompt = build_cover_image_prompt(payload)
        request_variants = [
            {
                "size": "1536x1024",
                "quality": "low",
                "timeout": max(self._request_timeout_seconds, 180.0),
            },
            {
                "size": "1024x1024",
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
        prompt_template = build_publish_package_prompt(payload)
        result = self._parse_response(
            instructions=prompt_template.instructions,
            prompt=prompt_template.prompt,
            response_format=PublishPackageGenerationResult,
        )
        return result.model_dump()

    def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
        prompt_template = build_tracked_article_metadata_prompt(payload)
        result = self._parse_response(
            instructions=prompt_template.instructions,
            prompt=prompt_template.prompt,
            response_format=TrackedArticleMetadataGenerationResult,
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
            except TypeError as exc:
                if "'NoneType' object is not iterable" not in str(exc):
                    raise
                return self._parse_response_with_chat_json_fallback(
                    instructions=instructions,
                    prompt=prompt,
                    response_format=response_format,
                )
            except (openai.InternalServerError, openai.RateLimitError, openai.APIConnectionError) as exc:
                last_error = exc
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI response parsing failed without a captured exception")

    def _parse_response_with_chat_json_fallback(
        self,
        *,
        instructions: str,
        prompt: str,
        response_format: type[ResponseModelT],
    ) -> ResponseModelT:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        f"{instructions}\n"
                        "只返回一个 JSON 对象，不要 Markdown，不要解释；字段必须严格匹配任务要求。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            timeout=self._request_timeout_seconds,
        )
        output_text = response.choices[0].message.content
        if not output_text:
            raise RuntimeError("OpenAI chat fallback returned no output")
        return response_format.model_validate(json.loads(output_text))

    def check_connection(self) -> None:
        request_kwargs: dict[str, object] = {
            "model": self._model,
            "input": "Reply with exactly OK.",
            "max_output_tokens": 8,
        }
        if self._reasoning_effort:
            request_kwargs["reasoning"] = {"effort": self._reasoning_effort}

        response = self._client.responses.create(**request_kwargs)
        output_text = getattr(response, "output_text", None)
        if isinstance(output_text, str) and output_text.strip():
            return
        raise RuntimeError("AI config check returned an empty response")


def get_ai_config_summary(config: Settings = settings) -> AIConfigSummary:
    return AIConfigSummary(
        api_key_configured=bool(config.openai_api_key),
        base_url=config.openai_base_url,
        model=config.openai_model,
        image_model=config.openai_image_model,
        reasoning_effort=config.openai_reasoning_effort,
        request_timeout_seconds=config.openai_request_timeout_seconds,
    )


def _extract_openai_error_message(error: Exception) -> str:
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        payload = body.get("error")
        if isinstance(payload, dict):
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()

    message = str(error).strip()
    if message:
        return message
    return error.__class__.__name__


def run_ai_config_check(config: Settings = settings) -> AIConfigCheckResult:
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if not config.openai_api_key:
        return AIConfigCheckResult(
            ok=False,
            status="missing_key",
            message="OPENAI_API_KEY 未配置，当前无法发起模型请求。",
            checked_at=checked_at,
        )

    try:
        OpenAIWorkbenchGenerator(config).check_connection()
        return AIConfigCheckResult(
            ok=True,
            status="ok",
            message="AI 配置检测通过，当前文本模型可以正常响应。",
            checked_at=checked_at,
        )
    except openai.AuthenticationError as exc:
        return AIConfigCheckResult(
            ok=False,
            status="auth_error",
            message=f"认证失败：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
        )
    except openai.PermissionDeniedError as exc:
        return AIConfigCheckResult(
            ok=False,
            status="permission_error",
            message=f"权限不足：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
        )
    except openai.NotFoundError as exc:
        return AIConfigCheckResult(
            ok=False,
            status="not_found",
            message=f"模型或接口不存在：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
        )
    except openai.BadRequestError as exc:
        return AIConfigCheckResult(
            ok=False,
            status="bad_request",
            message=f"请求参数错误：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
        )
    except openai.RateLimitError as exc:
        return AIConfigCheckResult(
            ok=False,
            status="rate_limited",
            message=f"请求频率受限：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
        )
    except (openai.InternalServerError, APIConnectionError, APITimeoutError) as exc:
        return AIConfigCheckResult(
            ok=False,
            status="upstream_error",
            message=f"上游服务异常：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
        )
    except Exception as exc:
        return AIConfigCheckResult(
            ok=False,
            status="unexpected_error",
            message=f"检测失败：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
        )


@lru_cache(maxsize=1)
def get_default_generator() -> OpenAIWorkbenchGenerator:
    return OpenAIWorkbenchGenerator(settings)
