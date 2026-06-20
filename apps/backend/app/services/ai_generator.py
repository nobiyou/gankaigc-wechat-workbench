from __future__ import annotations

import base64
from functools import lru_cache
import json
from json import JSONDecodeError
import re
import time
from typing import Any
from typing import TypeVar

import openai
from openai import APIConnectionError
from openai import APITimeoutError
from openai import OpenAI
from pydantic import BaseModel
from pydantic import ValidationError

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

        client_kwargs: dict[str, object] = {"api_key": config.openai_api_key}
        if config.openai_base_url:
            client_kwargs["base_url"] = config.openai_base_url
        client_kwargs["timeout"] = config.openai_request_timeout_seconds

        self._client = OpenAI(**client_kwargs)
        image_client_kwargs: dict[str, object] = {
            "api_key": config.effective_openai_image_api_key,
            "timeout": config.effective_openai_image_request_timeout_seconds,
        }
        effective_image_base_url = config.effective_openai_image_base_url
        if effective_image_base_url:
            image_client_kwargs["base_url"] = effective_image_base_url
        self._image_client = OpenAI(**image_client_kwargs)
        self._uses_custom_base_url = bool(config.openai_base_url)
        self._image_uses_custom_base_url = bool(effective_image_base_url)
        self._model = config.openai_model
        self._image_model = config.openai_image_model
        self._reasoning_effort = config.openai_reasoning_effort
        self._request_timeout_seconds = config.openai_request_timeout_seconds
        self._image_request_timeout_seconds = config.effective_openai_image_request_timeout_seconds
        self._prefer_chat_json_for_formats: set[type[BaseModel]] = set()

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
            timeout_seconds_override=self._resolve_draft_timeout_override(payload),
            max_attempts_override=self._resolve_draft_max_attempts(payload),
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
                return self._generate_cover_image_with_variant(prompt, variant)
            except APITimeoutError as exc:
                last_error = exc
                continue
            except openai.BadRequestError as exc:
                last_error = exc
                if not _is_image_size_validation_error(exc):
                    raise
                fallback_variant = _build_ratio_cover_image_variant(variant)
                if fallback_variant is None:
                    continue
                try:
                    return self._generate_cover_image_with_variant(prompt, fallback_variant)
                except APITimeoutError as retry_exc:
                    last_error = retry_exc
                    continue
                except openai.BadRequestError as retry_exc:
                    last_error = retry_exc
                    continue

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI image generation failed without a captured exception")

    def _generate_cover_image_with_variant(self, prompt: str, variant: dict[str, object]) -> bytes:
        request_kwargs = _build_cover_image_request_kwargs(
            model=self._image_model,
            prompt=prompt,
            variant=variant,
            timeout_seconds=self._image_request_timeout_seconds,
        )
        while True:
            response = None
            try:
                response = self._image_client.images.generate(**request_kwargs)
            except openai.BadRequestError as exc:
                unsupported_keys = _extract_unrecognized_image_request_keys(exc)
                if unsupported_keys:
                    changed = False
                    for key in unsupported_keys:
                        if key in request_kwargs:
                            del request_kwargs[key]
                            changed = True
                    if changed:
                        continue

                if _is_image_size_validation_error(exc):
                    fallback_size = _resolve_ratio_cover_image_size(request_kwargs.get("size"))
                    if fallback_size and str(request_kwargs.get("size")) != fallback_size:
                        request_kwargs["size"] = fallback_size
                        continue
                raise

            if not response.data:
                async_task = _extract_async_image_task_payload(response)
                if async_task is not None:
                    raise RuntimeError(
                        "Image provider accepted the request as an async task but did not expose a retrievable image result "
                        f"(task_id={async_task['id']}, status={async_task['status']})."
                    )
                raise RuntimeError("OpenAI returned no image data")

            image = response.data[0]
            if image.b64_json:
                return base64.b64decode(image.b64_json)
            raise RuntimeError("OpenAI returned no base64 image payload")

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
        timeout_seconds_override: float | None = None,
        max_attempts_override: int | None = None,
    ) -> ResponseModelT:
        timeout_seconds = timeout_seconds_override or self._resolve_text_request_timeout(response_format)
        max_attempts = max_attempts_override or 3
        if self._should_prefer_chat_json(response_format):
            return self._parse_response_with_chat_json_fallback(
                instructions=instructions,
                prompt=prompt,
                response_format=response_format,
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
            )

        request_kwargs: dict[str, object] = {
            "model": self._model,
            "instructions": instructions,
            "input": prompt,
            "text_format": response_format,
            "timeout": timeout_seconds,
        }
        if self._reasoning_effort:
            request_kwargs["reasoning"] = {"effort": self._reasoning_effort}

        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                response = self._client.responses.parse(**request_kwargs)
                parsed = response.output_parsed
                if parsed is not None:
                    return parsed

                parsed_from_text = self._parse_json_response_output(
                    response=response,
                    response_format=response_format,
                )
                if parsed_from_text is not None:
                    return parsed_from_text

                self._remember_chat_json_preference(response_format)
                return self._parse_response_with_chat_json_fallback(
                    instructions=instructions,
                    prompt=prompt,
                    response_format=response_format,
                    timeout_seconds=timeout_seconds,
                )
            except TypeError as exc:
                if "'NoneType' object is not iterable" not in str(exc):
                    raise
                self._remember_chat_json_preference(response_format)
                return self._parse_response_with_chat_json_fallback(
                    instructions=instructions,
                    prompt=prompt,
                    response_format=response_format,
                    timeout_seconds=timeout_seconds,
                )
            except APITimeoutError:
                return self._parse_response_with_chat_json_fallback(
                    instructions=instructions,
                    prompt=prompt,
                    response_format=response_format,
                    timeout_seconds=timeout_seconds,
                )
            except (openai.InternalServerError, openai.APIConnectionError) as exc:
                if self._should_fallback_to_chat_json_after_parse_error(
                    response_format=response_format,
                    error=exc,
                ):
                    self._remember_chat_json_preference(response_format)
                    return self._parse_response_with_chat_json_fallback(
                        instructions=instructions,
                        prompt=prompt,
                        response_format=response_format,
                        timeout_seconds=timeout_seconds,
                    )
                last_error = exc
                if attempt == max_attempts - 1:
                    raise
                time.sleep(1 + attempt)
            except openai.RateLimitError as exc:
                last_error = exc
                if attempt == max_attempts - 1:
                    raise
                time.sleep(1 + attempt)

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI response parsing failed without a captured exception")

    def _should_prefer_chat_json(self, response_format: type[ResponseModelT]) -> bool:
        return (
            response_format in self._prefer_chat_json_for_formats
            or self._should_default_to_chat_json(response_format)
        )

    def _remember_chat_json_preference(self, response_format: type[ResponseModelT]) -> None:
        if self._uses_custom_base_url and not self._supports_custom_base_url_chat_json(response_format):
            return
        self._prefer_chat_json_for_formats.add(response_format)

    def _should_default_to_chat_json(self, response_format: type[ResponseModelT]) -> bool:
        return self._uses_custom_base_url and response_format is DraftGenerationResult

    def _should_fallback_to_chat_json_after_parse_error(
        self,
        *,
        response_format: type[ResponseModelT],
        error: Exception,
    ) -> bool:
        if not self._uses_custom_base_url:
            return False
        if not self._supports_custom_base_url_chat_json(response_format):
            return False
        return isinstance(error, (openai.InternalServerError, openai.APIConnectionError))

    def _supports_custom_base_url_chat_json(self, response_format: type[ResponseModelT]) -> bool:
        return response_format in {
            OutlineGenerationResult,
            DraftGenerationResult,
            TopicGenerationResult,
            AssetGenerationResult,
            PublishPackageGenerationResult,
            TrackedArticleMetadataGenerationResult,
        }

    def _resolve_text_request_timeout(self, response_format: type[ResponseModelT]) -> float:
        if response_format is DraftGenerationResult:
            return max(self._request_timeout_seconds, 90.0)
        return self._request_timeout_seconds

    def _resolve_draft_timeout_override(self, payload: dict[str, object]) -> float | None:
        if any(
            bool(payload.get(flag))
            for flag in (
                "compact_strategy_mode",
                "compact_polish_mode",
                "timeout_recovery_mode",
                "full_fallback_single_attempt_mode",
            )
        ):
            return self._request_timeout_seconds
        return None

    def _resolve_draft_max_attempts(self, payload: dict[str, object]) -> int | None:
        if bool(payload.get("timeout_recovery_mode")):
            return 1
        if any(
            bool(payload.get(flag))
            for flag in (
                "compact_strategy_mode",
                "compact_polish_mode",
                "full_fallback_single_attempt_mode",
            )
        ):
            return 1
        return None

    def _parse_json_response_output(
        self,
        *,
        response: object,
        response_format: type[ResponseModelT],
    ) -> ResponseModelT | None:
        output_text = getattr(response, "output_text", None)
        if not isinstance(output_text, str) or not output_text.strip():
            return None
        try:
            payload = json.loads(output_text)
        except JSONDecodeError:
            return None
        return response_format.model_validate(payload)

    def _parse_response_with_chat_json_fallback(
        self,
        *,
        instructions: str,
        prompt: str,
        response_format: type[ResponseModelT],
        timeout_seconds: float,
        max_attempts: int = 3,
    ) -> ResponseModelT:
        request_kwargs: dict[str, object] = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        f"{instructions}\n"
                        "只返回一个 JSON 对象，不要 Markdown，不要解释；字段必须严格匹配任务要求。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "timeout": timeout_seconds,
        }
        if self._uses_custom_base_url:
            request_kwargs["extra_body"] = {
                "instructions": (
                    f"{instructions}\n"
                    "只返回一个 JSON 对象，不要 Markdown，不要解释；字段必须严格匹配任务要求。"
                )
            }

        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                response = self._client.chat.completions.create(**request_kwargs)
            except (APITimeoutError, openai.InternalServerError, openai.APIConnectionError, openai.RateLimitError) as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    time.sleep(0.5 + attempt * 0.5)
                continue
            output_text = response.choices[0].message.content
            if not output_text:
                last_error = RuntimeError("OpenAI chat fallback returned no output")
            else:
                try:
                    return response_format.model_validate(json.loads(output_text))
                except (JSONDecodeError, ValidationError) as exc:
                    last_error = exc
            if attempt < max_attempts - 1:
                time.sleep(0.5 + attempt * 0.5)

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI chat fallback failed without a captured exception")

    @property
    def uses_custom_base_url(self) -> bool:
        return self._uses_custom_base_url

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
        image_api_key_configured=bool(config.effective_openai_image_api_key),
        image_base_url=config.effective_openai_image_base_url,
        image_request_timeout_seconds=config.effective_openai_image_request_timeout_seconds,
        image_uses_dedicated_config=config.image_uses_dedicated_config,
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


_NUMERIC_IMAGE_SIZE_PATTERN = re.compile(r"^\d+x\d+$")
_IMAGE_RATIO_FALLBACKS = {
    "1536x1024": "3:2",
    "1024x1024": "1:1",
}
_UNRECOGNIZED_IMAGE_KEYS_PATTERN = re.compile(r'Unrecognized keys:\s*"?([^"]+)"?(.*)$', re.IGNORECASE)


def _is_image_size_validation_error(error: Exception) -> bool:
    message = _extract_openai_error_message(error)
    if not message:
        return False
    normalized = message.lower()
    return "size" in normalized and "expected one of" in normalized


def _build_ratio_cover_image_variant(variant: dict[str, object]) -> dict[str, object] | None:
    size = str(variant.get("size") or "").strip()
    fallback_size = _resolve_ratio_cover_image_size(size)
    if not fallback_size:
        return None
    return {
        **variant,
        "size": fallback_size,
    }


def _resolve_ratio_cover_image_size(size: object) -> str | None:
    normalized_size = str(size or "").strip()
    if not normalized_size or not _NUMERIC_IMAGE_SIZE_PATTERN.match(normalized_size):
        return None
    return _IMAGE_RATIO_FALLBACKS.get(normalized_size)


def _extract_unrecognized_image_request_keys(error: Exception) -> list[str]:
    message = _extract_openai_error_message(error)
    if not message:
        return []
    match = _UNRECOGNIZED_IMAGE_KEYS_PATTERN.search(message)
    if not match:
        return []
    tail = "".join(part for part in match.groups() if part)
    keys = re.findall(r'"([^"]+)"', tail)
    first_key = match.group(1).strip().strip('"')
    all_keys = [first_key, *keys]
    normalized_keys: list[str] = []
    for key in all_keys:
        cleaned = key.strip()
        if cleaned and cleaned not in normalized_keys:
            normalized_keys.append(cleaned)
    return normalized_keys


def _build_cover_image_request_kwargs(
    *,
    model: str,
    prompt: str,
    variant: dict[str, object],
    timeout_seconds: float,
) -> dict[str, object]:
    request_kwargs: dict[str, object] = {
        "model": model,
        "prompt": prompt,
        "size": str(variant["size"]),
        "timeout": max(timeout_seconds, float(variant["timeout"])),
    }
    quality = variant.get("quality")
    if quality is not None:
        request_kwargs["quality"] = str(quality)
    request_kwargs["output_format"] = "png"
    return request_kwargs


def _extract_async_image_task_payload(response: object) -> dict[str, str] | None:
    response_id = getattr(response, "id", None)
    status = getattr(response, "status", None)
    if not isinstance(response_id, str) or not response_id.strip():
        return None
    if not response_id.startswith("task_"):
        return None
    normalized_status = str(status or "").strip()
    if not normalized_status:
        return None
    return {
        "id": response_id.strip(),
        "status": normalized_status,
    }


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
