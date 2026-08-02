from __future__ import annotations

import base64
from contextvars import ContextVar
from collections.abc import Mapping
from functools import lru_cache
import httpx
import json
from json import JSONDecodeError
import logging
import re
import time
from typing import Any
from typing import TypeVar

import openai
from openai import APIConnectionError
from openai import APITimeoutError
from openai import OpenAI
from pydantic import BaseModel
from pydantic import field_validator
from pydantic import ValidationError

from app.core.settings import Settings, settings
from app.schemas.settings import AIConfigCheckResult, AIConfigSummary, AIImageRouteProbeItem, AIImageRouteProbeResult
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

    @field_validator('outline_body', mode='before')
    @classmethod
    def normalize_outline_body(cls, value: object) -> object:
        if isinstance(value, list):
            return "\n".join(str(item).strip() for item in value if str(item).strip())
        return value


class TopicGenerationResult(BaseModel):
    title: str
    angle: str


class DraftGenerationResult(BaseModel):
    title: str
    body_markdown: str


class AssetGenerationResult(BaseModel):
    title_options: list[str]
    recommended_title: str = ""
    cover_prompt: str
    cover_copy: str
    social_teaser: str
    social_teaser_options: list[str] = []


class PublishPackageGenerationResult(BaseModel):
    abstract: str
    tags: list[str]
    editor_note: str
    publish_title: str = ""
    publish_lead: str = ""
    intro_options: list[str] = []


class TrackedArticleMetadataGenerationResult(BaseModel):
    author: str
    summary: str
    structure_notes: str
    tags: list[str]
    analysis_theme: str = ""
    analysis_core_conflict: str = ""
    analysis_emotional_exit: str = ""
    analysis_structure_mode: str = ""
    analysis_opening_pattern: str = ""
    analysis_hook_trigger: str = ""
    analysis_progression_drive: str = ""
    analysis_share_reason: str = ""
    analysis_do_not_turn_into: str = ""
    analysis_content_pillars: list[str] = []


ResponseModelT = TypeVar("ResponseModelT", bound=BaseModel)


_REQUEST_TELEMETRY: ContextVar[dict[str, int] | None] = ContextVar(
    "ai_request_telemetry",
    default=None,
)


def begin_request_telemetry() -> dict[str, int]:
    telemetry = {"total": 0}
    _REQUEST_TELEMETRY.set(telemetry)
    return telemetry


def get_request_telemetry() -> dict[str, int]:
    telemetry = _REQUEST_TELEMETRY.get()
    return dict(telemetry) if telemetry is not None else {"total": 0}


def clear_request_telemetry() -> None:
    _REQUEST_TELEMETRY.set(None)


def _record_request(stage: str) -> None:
    telemetry = _REQUEST_TELEMETRY.get()
    if telemetry is None:
        return
    normalized_stage = stage.strip() or "unknown"
    telemetry["total"] = telemetry.get("total", 0) + 1
    telemetry[normalized_stage] = telemetry.get(normalized_stage, 0) + 1


def _request_stage(response_format: type[BaseModel], *, payload: Mapping[str, object] | None = None) -> str:
    if payload is not None:
        explicit = str(payload.get("request_stage") or "").strip()
        if explicit:
            return explicit
    stage_by_type = {
        TrackedArticleMetadataGenerationResult: "metadata",
        TopicGenerationResult: "topic",
        OutlineGenerationResult: "outline",
        DraftGenerationResult: "draft",
        AssetGenerationResult: "assets",
        PublishPackageGenerationResult: "publish_package",
    }
    return stage_by_type.get(response_format, "text")
logger = logging.getLogger(__name__)


def _normalize_draft_generation_result(result: DraftGenerationResult) -> DraftGenerationResult:
    """Remove explicit response-field labels that leak from non-structured providers."""
    title = result.title.strip()
    body = result.body_markdown.strip()
    title = re.sub(r"^\s*```(?:markdown|md|text)?\s*", "", title, flags=re.IGNORECASE)
    body = re.sub(r"^\s*```(?:markdown|md|text)?\s*", "", body, flags=re.IGNORECASE)
    body = re.sub(r"\s*```\s*$", "", body)
    title = re.sub(r"^\s*\d+\s*[.)、:：]?\s*(?:标题|title)\s*[:：]?\s*", "", title, flags=re.IGNORECASE)
    normalized_title = title.strip().casefold()
    placeholder_title = normalized_title in {"", "标题", "title", "标题 title", "title title"}

    marker_match = re.search(
        r"\d+\s*[.)、:：]\s*(?:正文|body(?:_markdown)?|markdown)"
        r"(?:\s+(?:markdown\s+body_markdown|body_markdown|markdown))?\s*[:：]?\s*",
        body[:400],
        flags=re.IGNORECASE,
    )
    if marker_match:
        prefix = body[: marker_match.start()].strip()
        body_after_marker = body[marker_match.end() :].strip()
        if placeholder_title and prefix:
            title = prefix
        body = body_after_marker

    return DraftGenerationResult(title=title.strip(), body_markdown=body.strip())

def _build_openai_http_client(*, timeout_seconds: float, trust_env: bool) -> httpx.Client:
    return httpx.Client(timeout=timeout_seconds, trust_env=trust_env)


def _normalize_optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _coerce_non_negative_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = default
    return max(0, parsed)


class OpenAIWorkbenchGenerator:
    def __init__(self, config: Settings) -> None:
        if not config.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")

        client_kwargs: dict[str, object] = {"api_key": config.openai_api_key}
        if config.openai_base_url:
            client_kwargs["base_url"] = config.openai_base_url
        client_kwargs["timeout"] = config.openai_request_timeout_seconds
        client_kwargs["max_retries"] = 0
        client_kwargs["http_client"] = _build_openai_http_client(
            timeout_seconds=config.openai_request_timeout_seconds,
            trust_env=config.openai_trust_env,
        )

        self._client = OpenAI(**client_kwargs)
        primary_image_route = self._build_image_route(
            label="primary",
            api_key=config.effective_openai_image_api_key,
            base_url=config.effective_openai_image_base_url,
            timeout_seconds=config.effective_openai_image_request_timeout_seconds,
            model=config.openai_image_model,
            trust_env=config.openai_trust_env,
        )
        self._image_routes: list[dict[str, object]] = [primary_image_route]
        fallback_image_route = self._build_fallback_image_route(config, primary_route=primary_image_route)
        if fallback_image_route is not None:
            self._image_routes.append(fallback_image_route)

        self._image_client = primary_image_route["client"]
        self._uses_custom_base_url = bool(config.openai_base_url)
        self._image_uses_custom_base_url = bool(primary_image_route["uses_custom_base_url"])
        self._model = config.openai_model
        self._image_model = str(primary_image_route["model"])
        self._reasoning_effort = config.openai_reasoning_effort
        self._request_timeout_seconds = config.openai_request_timeout_seconds
        self._image_request_timeout_seconds = float(primary_image_route["request_timeout_seconds"])
        self._image_fallback_route = fallback_image_route
        self._last_cover_image_route_info: dict[str, object] | None = None
        self._prefer_chat_json_for_formats: set[type[BaseModel]] = set()

    def _build_image_route(
        self,
        *,
        label: str,
        api_key: str,
        base_url: str | None,
        timeout_seconds: float,
        model: str,
        trust_env: bool,
    ) -> dict[str, object]:
        client_kwargs: dict[str, object] = {
            "api_key": api_key,
            "timeout": timeout_seconds,
            "max_retries": 0,
            "http_client": _build_openai_http_client(
                timeout_seconds=timeout_seconds,
                trust_env=trust_env,
            ),
        }
        if base_url:
            client_kwargs["base_url"] = base_url
        return {
            "label": label,
            "client": OpenAI(**client_kwargs),
            "api_key": api_key,
            "base_url": base_url,
            "uses_custom_base_url": bool(base_url),
            "model": model,
            "request_timeout_seconds": timeout_seconds,
        }

    def _build_fallback_image_route(
        self,
        config: Settings,
        *,
        primary_route: dict[str, object],
    ) -> dict[str, object] | None:
        if not config.image_fallback_route_active:
            return None

        fallback_model = config.effective_openai_image_fallback_model
        fallback_api_key = config.effective_openai_image_fallback_api_key
        fallback_base_url = config.effective_openai_image_fallback_base_url
        fallback_timeout_seconds = config.effective_openai_image_fallback_request_timeout_seconds

        return self._build_image_route(
            label="fallback",
            api_key=fallback_api_key,
            base_url=fallback_base_url,
            timeout_seconds=fallback_timeout_seconds,
            model=fallback_model,
            trust_env=config.openai_trust_env,
        )

    def generate_outline(self, payload: dict[str, object]) -> dict[str, str]:
        prompt_template = build_outline_prompt(payload)
        timeout_seconds_override = self._resolve_outline_timeout_override(payload)
        max_attempts_override = self._resolve_outline_max_attempts(payload)
        if bool(payload.get("outline_timeout_recovery_mode")):
            result = self._parse_response_with_chat_json_fallback(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=OutlineGenerationResult,
                timeout_seconds=timeout_seconds_override or self._resolve_text_request_timeout(OutlineGenerationResult),
                max_attempts=max_attempts_override or 1,
                enforce_custom_base_url_retry_floor=False,
                include_custom_base_url_extra_body=False,
                include_response_format=False,
            )
        else:
            result = self._parse_response(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=OutlineGenerationResult,
                timeout_seconds_override=timeout_seconds_override,
                max_attempts_override=max_attempts_override,
            )
        return result.model_dump()

    def generate_topic(self, payload: dict[str, object]) -> dict[str, str]:
        prompt_template = build_topic_prompt(payload)
        timeout_seconds_override = self._resolve_topic_timeout_override(payload)
        max_attempts_override = self._resolve_topic_max_attempts(payload)
        if self._uses_custom_base_url and str(payload.get("source_type") or "") == "tracked_article":
            result = self._parse_response_with_chat_json_fallback(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=TopicGenerationResult,
                timeout_seconds=timeout_seconds_override or self._resolve_text_request_timeout(TopicGenerationResult),
                max_attempts=max_attempts_override or 2,
                enforce_custom_base_url_retry_floor=False,
                include_custom_base_url_extra_body=False,
                retry_on_output_error=False,
            )
        else:
            result = self._parse_response(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=TopicGenerationResult,
                timeout_seconds_override=timeout_seconds_override,
                max_attempts_override=max_attempts_override,
            )
        return result.model_dump()

    def generate_draft(self, payload: dict[str, object]) -> dict[str, str]:
        prompt_template = build_draft_prompt(payload)
        timeout_seconds_override = self._resolve_draft_timeout_override(payload)
        max_attempts_override = self._resolve_draft_max_attempts(payload)
        if bool(payload.get("timeout_recovery_mode")) and str(payload.get("source_type") or "") == "tracked_article":
            result = self._parse_tracked_article_timeout_recovery_draft(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                timeout_seconds=timeout_seconds_override or self._resolve_text_request_timeout(DraftGenerationResult),
                max_attempts=max_attempts_override or 1,
            )
        elif self._should_use_tracked_article_bounded_draft_chat_path(payload):
            result = self._parse_tracked_article_timeout_recovery_draft(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                timeout_seconds=timeout_seconds_override or self._resolve_text_request_timeout(DraftGenerationResult),
                max_attempts=max_attempts_override or 1,
            )
        else:
            result = self._parse_response(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=DraftGenerationResult,
                timeout_seconds_override=timeout_seconds_override,
                max_attempts_override=max_attempts_override,
            )
        return _normalize_draft_generation_result(result).model_dump()

    def generate_assets(self, payload: dict[str, object]) -> dict[str, object]:
        prompt_template = build_assets_prompt(payload)
        timeout_seconds_override = self._resolve_assets_timeout_override(payload)
        max_attempts_override = self._resolve_assets_max_attempts(payload)
        if bool(payload.get("assets_timeout_recovery_mode")):
            result = self._parse_response_with_chat_json_fallback(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=AssetGenerationResult,
                timeout_seconds=timeout_seconds_override or self._resolve_text_request_timeout(AssetGenerationResult),
                max_attempts=max_attempts_override or 1,
                enforce_custom_base_url_retry_floor=False,
                include_custom_base_url_extra_body=False,
                include_response_format=False,
            )
        else:
            result = self._parse_response(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=AssetGenerationResult,
                timeout_seconds_override=timeout_seconds_override,
                max_attempts_override=max_attempts_override,
            )
        return result.model_dump()

    def generate_cover_image(self, payload: dict[str, object]) -> bytes:
        image_bytes, _route_info = self.generate_cover_image_with_route_info(payload)
        return image_bytes

    def generate_cover_image_with_route_info(self, payload: dict[str, object]) -> tuple[bytes, dict[str, object]]:
        prompt = build_cover_image_prompt(payload)
        max_request_attempts = _coerce_positive_int(payload.get("image_generation_max_attempts"), default=1)
        self._last_cover_image_route_info = None
        image_bytes, route_label = self._generate_cover_image_with_route(
            prompt,
            max_request_attempts=max_request_attempts,
        )
        route_info = self._build_cover_image_route_info(route_label)
        self._last_cover_image_route_info = route_info
        return image_bytes, route_info

    @property
    def last_cover_image_route_info(self) -> dict[str, object] | None:
        return dict(self._last_cover_image_route_info) if self._last_cover_image_route_info is not None else None

    def _build_cover_image_route_info(self, route_label: str) -> dict[str, object]:
        for route in self._image_routes:
            if str(route.get("label") or "") != route_label:
                continue
            return {
                "label": route_label,
                "model": str(route.get("model") or ""),
                "base_url": route.get("base_url"),
            }
        return {
            "label": route_label,
            "model": "",
            "base_url": None,
        }

    def _attach_cover_image_route_info_to_error(self, error: Exception, route: Mapping[str, object]) -> None:
        route_label = str(route.get("label") or "").strip() or None
        route_model = str(route.get("model") or "").strip() or None
        route_base_url = str(route.get("base_url") or "").strip() or None
        if route_label is not None:
            setattr(error, "cover_image_route_label", route_label)
        if route_model is not None:
            setattr(error, "cover_image_route_model", route_model)
        if route_base_url is not None:
            setattr(error, "cover_image_route_base_url", route_base_url)

    def _build_cover_image_variants(self, route: Mapping[str, object]) -> list[dict[str, object]]:
        request_timeout_seconds = float(route["request_timeout_seconds"])
        if bool(route["uses_custom_base_url"]):
            ratio_timeout = min(max(request_timeout_seconds * 6, 90.0), 180.0)
            primary_timeout = min(max(request_timeout_seconds * 4, 60.0), 120.0)
            return [
                {
                    "size": "16:9",
                    "timeout": ratio_timeout,
                },
                {
                    "size": "1536x864",
                    "timeout": primary_timeout,
                },
            ]

        ratio_timeout = max(request_timeout_seconds, 240.0)
        primary_timeout = max(request_timeout_seconds, 180.0)
        return [
            {
                "size": "16:9",
                "quality": "low",
                "timeout": ratio_timeout,
            },
            {
                "size": "1536x864",
                "quality": "low",
                "timeout": primary_timeout,
            },
        ]

    def _generate_cover_image_with_route(self, prompt: str, *, max_request_attempts: int = 1) -> tuple[bytes, str]:
        last_error: Exception | None = None
        request_attempts_remaining = max(1, int(max_request_attempts or 1))
        for route_index, route in enumerate(self._image_routes):
            self._last_cover_image_route_info = self._build_cover_image_route_info(str(route["label"]))
            request_variants = self._build_cover_image_variants(route)
            for variant in request_variants:
                if request_attempts_remaining <= 0:
                    break
                try:
                    image_bytes, consumed_attempts = self._generate_cover_image_with_variant(
                        prompt,
                        variant,
                        route=route,
                        max_request_attempts=request_attempts_remaining,
                    )
                    return image_bytes, str(route["label"])
                except (APITimeoutError, openai.InternalServerError, openai.APIConnectionError, openai.BadRequestError) as exc:
                    self._attach_cover_image_route_info_to_error(exc, route)
                    last_error = exc
                    request_attempts_remaining -= int(getattr(exc, "image_request_attempts_consumed", 1) or 1)
                    if request_attempts_remaining <= 0:
                        break
                    if route_index < len(self._image_routes) - 1 and _should_try_next_cover_image_route(exc):
                        break
                    continue
                except Exception as exc:
                    self._attach_cover_image_route_info_to_error(exc, route)
                    raise
            if request_attempts_remaining <= 0:
                break
            if route_index < len(self._image_routes) - 1 and last_error is not None:
                logger.warning(
                    "Primary image route failed for model %s via %s; retrying fallback image route.",
                    route["model"],
                    route["base_url"] or "default-openai",
                )
                continue

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI image generation failed without a captured exception")

    def _generate_cover_image_with_variant(
        self,
        prompt: str,
        variant: dict[str, object],
        *,
        route: Mapping[str, object],
        max_request_attempts: int,
    ) -> tuple[bytes, int]:
        request_kwargs = _build_cover_image_request_kwargs(
            model=str(route["model"]),
            prompt=prompt,
            variant=variant,
            timeout_seconds=float(route["request_timeout_seconds"]),
        )
        attempts_consumed = 0
        while attempts_consumed < max(1, int(max_request_attempts or 1)):
            response = None
            try:
                image_client = route["client"]
                attempts_consumed += 1
                _record_request("cover_image")
                response = image_client.images.generate(**request_kwargs)
            except openai.BadRequestError as exc:
                unsupported_keys = _extract_unrecognized_image_request_keys(exc)
                if unsupported_keys:
                    changed = False
                    for key in unsupported_keys:
                        if key in request_kwargs:
                            del request_kwargs[key]
                            changed = True
                    if changed and attempts_consumed < max_request_attempts:
                        continue

                if _is_image_size_validation_error(exc):
                    fallback_size = _resolve_ratio_cover_image_size(request_kwargs.get("size"))
                    if fallback_size and str(request_kwargs.get("size")) != fallback_size and attempts_consumed < max_request_attempts:
                        request_kwargs["size"] = fallback_size
                        continue
                setattr(exc, "image_request_attempts_consumed", attempts_consumed)
                raise
            except (APITimeoutError, openai.InternalServerError, openai.APIConnectionError) as exc:
                setattr(exc, "image_request_attempts_consumed", attempts_consumed)
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
                return base64.b64decode(image.b64_json), attempts_consumed
            raise RuntimeError("OpenAI returned no base64 image payload")
        raise RuntimeError("OpenAI image generation exhausted the configured request budget")

    def generate_publish_package(self, payload: dict[str, object]) -> dict[str, object]:
        prompt_template = build_publish_package_prompt(payload)
        timeout_seconds_override = self._resolve_publish_timeout_override(payload)
        max_attempts_override = self._resolve_publish_max_attempts(payload)
        if bool(payload.get("publish_timeout_recovery_mode")):
            result = self._parse_response_with_chat_json_fallback(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=PublishPackageGenerationResult,
                timeout_seconds=timeout_seconds_override or self._resolve_text_request_timeout(PublishPackageGenerationResult),
                max_attempts=max_attempts_override or 1,
                enforce_custom_base_url_retry_floor=False,
                include_custom_base_url_extra_body=False,
                include_response_format=False,
            )
        else:
            result = self._parse_response(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=PublishPackageGenerationResult,
                timeout_seconds_override=timeout_seconds_override,
                max_attempts_override=max_attempts_override,
            )
        return result.model_dump()

    def generate_tracked_article_metadata(self, payload: dict[str, object]) -> dict[str, object]:
        prompt_template = build_tracked_article_metadata_prompt(payload)
        timeout_seconds_override = self._resolve_tracked_article_metadata_timeout_override(payload)
        max_attempts_override = self._resolve_tracked_article_metadata_max_attempts(payload)
        if self._uses_custom_base_url:
            result = self._parse_response_with_chat_json_fallback(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=TrackedArticleMetadataGenerationResult,
                timeout_seconds=timeout_seconds_override or self._resolve_text_request_timeout(TrackedArticleMetadataGenerationResult),
                max_attempts=max_attempts_override or 1,
                enforce_custom_base_url_retry_floor=False,
                include_custom_base_url_extra_body=False,
                retry_on_output_error=False,
            )
        else:
            result = self._parse_response(
                instructions=prompt_template.instructions,
                prompt=prompt_template.prompt,
                response_format=TrackedArticleMetadataGenerationResult,
                timeout_seconds_override=timeout_seconds_override,
                max_attempts_override=max_attempts_override,
            )
        return result.model_dump(exclude_defaults=True)

    def _parse_response(
        self,
        *,
        instructions: str,
        prompt: str,
        response_format: type[ResponseModelT],
        timeout_seconds_override: float | None = None,
        max_attempts_override: int | None = None,
        request_stage: str | None = None,
    ) -> ResponseModelT:
        timeout_seconds = timeout_seconds_override or self._resolve_text_request_timeout(response_format)
        max_attempts = max_attempts_override or 3
        enforce_custom_base_url_retry_floor = max_attempts_override is None
        if self._should_prefer_chat_json(response_format):
            return self._parse_response_with_chat_json_fallback(
                instructions=instructions,
                prompt=prompt,
                response_format=response_format,
                timeout_seconds=timeout_seconds,
                max_attempts=max_attempts,
                enforce_custom_base_url_retry_floor=enforce_custom_base_url_retry_floor,
                request_stage=request_stage or _request_stage(response_format),
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
            chat_json_fallback_started = False
            try:
                _record_request(request_stage or _request_stage(response_format))
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
                chat_json_fallback_started = True
                return self._parse_response_with_chat_json_fallback(
                    instructions=instructions,
                    prompt=prompt,
                    response_format=response_format,
                    timeout_seconds=timeout_seconds,
                    max_attempts=max_attempts,
                    enforce_custom_base_url_retry_floor=enforce_custom_base_url_retry_floor,
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
                    max_attempts=max_attempts,
                    enforce_custom_base_url_retry_floor=enforce_custom_base_url_retry_floor,
                )
            except ValidationError:
                self._remember_chat_json_preference(response_format)
                return self._parse_response_with_chat_json_fallback(
                    instructions=instructions,
                    prompt=prompt,
                    response_format=response_format,
                    timeout_seconds=timeout_seconds,
                    max_attempts=max_attempts,
                    enforce_custom_base_url_retry_floor=enforce_custom_base_url_retry_floor,
                )
            except APITimeoutError:
                return self._parse_response_with_chat_json_fallback(
                    instructions=instructions,
                    prompt=prompt,
                    response_format=response_format,
                    timeout_seconds=timeout_seconds,
                    max_attempts=max_attempts,
                    enforce_custom_base_url_retry_floor=enforce_custom_base_url_retry_floor,
                )
            except (openai.InternalServerError, openai.APIConnectionError) as exc:
                if chat_json_fallback_started:
                    raise
                if response_format in self._prefer_chat_json_for_formats:
                    raise
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
                        max_attempts=max_attempts,
                        enforce_custom_base_url_retry_floor=enforce_custom_base_url_retry_floor,
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
        if self._uses_custom_base_url:
            return
        self._prefer_chat_json_for_formats.add(response_format)

    def _should_default_to_chat_json(self, response_format: type[ResponseModelT]) -> bool:
        return False

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
        # A provider 5xx means the upstream request failed, not that the
        # Responses protocol is unsupported. Retrying through chat here would
        # duplicate a long prompt and can change the generated result.
        return isinstance(error, openai.APIConnectionError)

    def _supports_custom_base_url_chat_json(self, response_format: type[ResponseModelT]) -> bool:
        return response_format in {
            OutlineGenerationResult,
            DraftGenerationResult,
            TopicGenerationResult,
            AssetGenerationResult,
            PublishPackageGenerationResult,
            TrackedArticleMetadataGenerationResult,
        }

    def _ensure_custom_base_url_retry_attempts(self, max_attempts: int) -> int:
        if not self._uses_custom_base_url:
            return max_attempts
        return max(max_attempts, 2)

    def _resolve_text_request_timeout(self, response_format: type[ResponseModelT]) -> float:
        if response_format is DraftGenerationResult:
            return max(self._request_timeout_seconds, 90.0)
        return self._request_timeout_seconds

    def _resolve_outline_timeout_override(self, payload: dict[str, object]) -> float | None:
        if self._uses_custom_base_url and bool(payload.get("outline_timeout_recovery_mode")):
            return max(self._request_timeout_seconds, 30.0)
        if self._uses_custom_base_url and bool(payload.get("strategy_first_outline_mode")):
            return max(self._request_timeout_seconds, 30.0)
        return None

    def _resolve_outline_max_attempts(self, payload: dict[str, object]) -> int | None:
        if self._uses_custom_base_url and bool(payload.get("outline_timeout_recovery_mode")):
            return 1
        if self._uses_custom_base_url and bool(payload.get("strategy_first_outline_mode")):
            return 1
        return None

    def _resolve_topic_timeout_override(self, payload: dict[str, object]) -> float | None:
        if self._uses_custom_base_url and str(payload.get("source_type") or "") == "tracked_article":
            return max(self._request_timeout_seconds, 30.0)
        return None

    def _resolve_topic_max_attempts(self, payload: dict[str, object]) -> int | None:
        if self._uses_custom_base_url and str(payload.get("source_type") or "") == "tracked_article":
            # The topic request is lightweight, but a proxy 502/503 should not
            # turn a transient upstream outage into an immediate workflow 503.
            return 2
        return None

    def _resolve_draft_timeout_override(self, payload: dict[str, object]) -> float | None:
        if bool(payload.get("timeout_recovery_mode")):
            if self._uses_custom_base_url and str(payload.get("source_type") or "") == "tracked_article":
                return max(self._request_timeout_seconds, 30.0)
            return self._request_timeout_seconds
        if any(
            bool(payload.get(flag))
            for flag in (
                "strategy_first_draft_mode",
                "compact_strategy_mode",
                "compact_polish_mode",
                "full_fallback_single_attempt_mode",
            )
        ):
            if self._uses_custom_base_url and str(payload.get("source_type") or "") == "tracked_article":
                return max(self._request_timeout_seconds, 30.0)
            return self._request_timeout_seconds
        return None

    def _resolve_draft_max_attempts(self, payload: dict[str, object]) -> int | None:
        if bool(payload.get("timeout_recovery_mode")):
            if self._uses_custom_base_url and str(payload.get("source_type") or "") == "tracked_article":
                return 1
            return 1
        if self._uses_custom_base_url and str(payload.get("source_type") or "") == "tracked_article":
            # Workbench owns the single same-prompt retry. Keep this layer to
            # one request so transient failures do not multiply across layers.
            return 1
        if any(
            bool(payload.get(flag))
            for flag in (
                "strategy_first_draft_mode",
                "compact_strategy_mode",
                "compact_polish_mode",
                "full_fallback_single_attempt_mode",
            )
        ):
            return 1
        return None

    def _resolve_assets_timeout_override(self, payload: dict[str, object]) -> float | None:
        if self._uses_custom_base_url and bool(payload.get("assets_timeout_recovery_mode")):
            return max(self._request_timeout_seconds, 30.0)
        return None

    def _resolve_assets_max_attempts(self, payload: dict[str, object]) -> int | None:
        if self._uses_custom_base_url and bool(payload.get("assets_timeout_recovery_mode")):
            return 1
        if self._uses_custom_base_url and str(payload.get("source_type") or "") == "tracked_article":
            return 1
        return None

    def _resolve_publish_timeout_override(self, payload: dict[str, object]) -> float | None:
        if self._uses_custom_base_url and bool(payload.get("publish_timeout_recovery_mode")):
            return max(self._request_timeout_seconds, 30.0)
        return None

    def _resolve_publish_max_attempts(self, payload: dict[str, object]) -> int | None:
        if self._uses_custom_base_url and bool(payload.get("publish_timeout_recovery_mode")):
            return 1
        if self._uses_custom_base_url and str(payload.get("source_type") or "") == "tracked_article":
            return 1
        return None

    def _resolve_tracked_article_metadata_timeout_override(self, payload: dict[str, object]) -> float | None:
        if self._uses_custom_base_url and str(payload.get("body_markdown") or "").strip():
            return max(self._request_timeout_seconds, 30.0)
        return None

    def _resolve_tracked_article_metadata_max_attempts(self, payload: dict[str, object]) -> int | None:
        if self._uses_custom_base_url and str(payload.get("body_markdown") or "").strip():
            # A transient 502/503 must not be mistaken for an incomplete
            # analysis contract. One same-prompt retry is cheap on success
            # (it is never used) and prevents the workflow from stopping on a
            # single upstream blip.
            return 2
        return None

    def _should_use_tracked_article_bounded_draft_chat_path(self, payload: dict[str, object]) -> bool:
        if not self._uses_custom_base_url:
            return False
        if str(payload.get("source_type") or "") != "tracked_article":
            return False
        return any(
            bool(payload.get(flag))
            for flag in (
                "strategy_first_draft_mode",
                "compact_strategy_mode",
                "compact_polish_mode",
                "full_fallback_single_attempt_mode",
            )
        )

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
        enforce_custom_base_url_retry_floor: bool = True,
        include_custom_base_url_extra_body: bool = True,
        include_response_format: bool = True,
        request_stage: str | None = None,
        retry_on_output_error: bool = True,
    ) -> ResponseModelT:
        system_content = instructions
        if include_response_format:
            system_content = (
                f"{instructions}\n"
                "只返回一个 JSON 对象，不要 Markdown，不要解释；字段必须严格匹配任务要求。"
            )
        request_kwargs: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt},
            ],
            "timeout": timeout_seconds,
        }
        if include_response_format:
            request_kwargs["response_format"] = {"type": "json_object"}
        if self._uses_custom_base_url and include_custom_base_url_extra_body:
            request_kwargs["extra_body"] = {"instructions": system_content}

        last_error: Exception | None = None
        effective_max_attempts = max_attempts
        if self._uses_custom_base_url and enforce_custom_base_url_retry_floor:
            # Do not silently expand a caller's retry budget on a long prompt.
            # The stage resolver owns the budget; this layer only executes it.
            effective_max_attempts = max(1, max_attempts)

        for attempt in range(effective_max_attempts):
            try:
                _record_request(request_stage or _request_stage(response_format))
                response = self._client.chat.completions.create(**request_kwargs)
            except (APITimeoutError, openai.InternalServerError, openai.APIConnectionError, openai.RateLimitError) as exc:
                last_error = exc
                if attempt < effective_max_attempts - 1:
                    time.sleep(0.5 + attempt * 0.5)
                continue
            output_text = response.choices[0].message.content
            if not output_text:
                last_error = RuntimeError("OpenAI chat fallback returned no output")
                if not retry_on_output_error:
                    raise last_error
            else:
                try:
                    return response_format.model_validate(json.loads(output_text))
                except (JSONDecodeError, ValidationError) as exc:
                    last_error = exc
                    if not retry_on_output_error:
                        raise
            if attempt < effective_max_attempts - 1:
                time.sleep(0.5 + attempt * 0.5)

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI chat fallback failed without a captured exception")

    def _parse_tracked_article_timeout_recovery_draft(
        self,
        *,
        instructions: str,
        prompt: str,
        timeout_seconds: float,
        max_attempts: int,
    ) -> DraftGenerationResult:
        request_kwargs: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": prompt},
            ],
            "timeout": timeout_seconds,
        }
        last_error: Exception | None = None
        for attempt in range(max_attempts):
            try:
                _record_request("draft")
                response = self._client.chat.completions.create(**request_kwargs)
            except (APITimeoutError, openai.InternalServerError, openai.APIConnectionError, openai.RateLimitError) as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    time.sleep(0.5 + attempt * 0.5)
                continue

            output_text = response.choices[0].message.content
            if not output_text:
                last_error = RuntimeError("OpenAI draft timeout recovery returned no output")
            else:
                try:
                    return self._parse_tracked_article_timeout_recovery_draft_text(output_text)
                except ValueError as exc:
                    last_error = exc
            if attempt < max_attempts - 1:
                time.sleep(0.5 + attempt * 0.5)

        if last_error is not None:
            raise last_error
        raise RuntimeError("OpenAI tracked article draft timeout recovery failed without a captured exception")

    def _parse_tracked_article_timeout_recovery_draft_text(self, output_text: str) -> DraftGenerationResult:
        text = output_text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
            text = re.sub(r"\s*```$", "", text).strip()

        if text.startswith("{"):
            try:
                payload = json.loads(text)
            except JSONDecodeError:
                payload = None
            if isinstance(payload, dict):
                title = str(payload.get("title") or "").strip()
                body_markdown = str(payload.get("body_markdown") or "").strip()
                if title and body_markdown:
                    return DraftGenerationResult(title=title, body_markdown=body_markdown)

        title_match = re.search(r"【标题】\s*(.+)", text)
        body_match = re.search(r"【正文】\s*([\s\S]+)", text)
        if title_match and body_match:
            return DraftGenerationResult(
                title=title_match.group(1).strip(),
                body_markdown=body_match.group(1).strip(),
            )

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) >= 2:
            return DraftGenerationResult(
                title=re.sub(r"^[【\\[]?标题[】\\]]?\s*", "", lines[0]).strip(),
                body_markdown="\n\n".join(lines[1:]).strip(),
            )
        raise ValueError("tracked article draft timeout recovery output missing title/body markers")

    @property
    def uses_custom_base_url(self) -> bool:
        return self._uses_custom_base_url

    @property
    def image_uses_custom_base_url(self) -> bool:
        return self._image_uses_custom_base_url

    def check_connection(self) -> None:
        request_kwargs: dict[str, object] = {
            "model": self._model,
            "input": "Reply with exactly OK.",
            "max_output_tokens": 8,
        }
        if self._reasoning_effort:
            request_kwargs["reasoning"] = {"effort": self._reasoning_effort}

        last_error: Exception | None = None
        max_attempts = self._ensure_custom_base_url_retry_attempts(1)
        for attempt in range(max_attempts):
            try:
                response = self._client.responses.create(**request_kwargs)
            except (openai.InternalServerError, openai.APIConnectionError, openai.RateLimitError, APITimeoutError) as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    time.sleep(0.5 + attempt * 0.5)
                    continue
                raise
            output_text = getattr(response, "output_text", None)
            if isinstance(output_text, str) and output_text.strip():
                return
            last_error = RuntimeError("AI config check returned an empty response")
            if attempt < max_attempts - 1:
                time.sleep(0.5 + attempt * 0.5)
                continue
            raise last_error

        if last_error is not None:
            raise last_error
        raise RuntimeError("AI config check failed without a captured exception")

    def check_image_connection(self) -> str:
        _bytes, route_label = self._generate_cover_image_with_route(
            "16:9 横版公众号头图，暖灯下的室内场景，真实摄影感，不要文字。",
            max_request_attempts=1,
        )
        return route_label


def get_ai_config_summary(config: Settings = settings) -> AIConfigSummary:
    fallback_route_configured = config.image_fallback_route_configured
    fallback_account_pool_diagnosis = _build_image_fallback_account_pool_diagnosis(config)
    image_generation_max_attempts = _coerce_positive_int(
        getattr(config, "openai_image_generation_max_attempts", 1),
        default=1,
    )
    creative_quality_retry_max_attempts = _coerce_non_negative_int(
        getattr(config, "openai_creative_quality_retry_max_attempts", 0),
        default=0,
    )
    if not fallback_route_configured:
        fallback_route_recovery_actions = _build_image_check_recovery_actions(config=config, status="not_configured")
    elif not config.image_fallback_route_active:
        fallback_route_recovery_actions = _build_image_check_recovery_actions(config=config, status="inactive")
    else:
        fallback_route_recovery_actions = [
            "当前备用图片链路已经形成第二条图片 API；建议点一次“探测主/备路由”，确认它能独立返回图片。",
            "只有出图请求预算大于 1 时，正式出封面才会在主链路失败后尝试切到这条备用图片链路。",
        ]
    fallback_route_config_hints = _build_image_fallback_config_hints(config)
    fallback_route_env_example, fallback_route_env_example_note = _build_image_fallback_env_example(config)
    return AIConfigSummary(
        api_key_configured=bool(config.openai_api_key),
        base_url=config.openai_base_url,
        model=config.openai_model,
        trust_env=config.openai_trust_env,
        image_model=config.openai_image_model,
        image_api_key_configured=bool(config.effective_openai_image_api_key),
        image_base_url=config.effective_openai_image_base_url,
        image_request_timeout_seconds=config.effective_openai_image_request_timeout_seconds,
        image_generation_max_attempts=image_generation_max_attempts,
        image_uses_dedicated_config=config.image_uses_dedicated_config,
        creative_quality_retry_max_attempts=creative_quality_retry_max_attempts,
        allow_local_creative_fallbacks=bool(getattr(config, "openai_allow_local_creative_fallbacks", False)),
        image_fallback_route_configured=fallback_route_configured,
        image_fallback_route_active=config.image_fallback_route_active,
        image_fallback_model=config.effective_openai_image_fallback_model if config.image_fallback_route_active else None,
        image_fallback_base_url=config.effective_openai_image_fallback_base_url if config.image_fallback_route_active else None,
        image_fallback_effective_model=config.effective_openai_image_fallback_model if fallback_route_configured else None,
        image_fallback_effective_base_url=config.effective_openai_image_fallback_base_url if fallback_route_configured else None,
        image_fallback_effective_request_timeout_seconds=(
            config.effective_openai_image_fallback_request_timeout_seconds if fallback_route_configured else None
        ),
        image_fallback_effective_api_key_configured=bool(config.effective_openai_image_fallback_api_key)
        if fallback_route_configured
        else False,
        image_fallback_uses_inherited_model=(not bool((config.openai_image_fallback_model or "").strip()))
        if fallback_route_configured
        else None,
        image_fallback_uses_inherited_api_key=(not bool(config.openai_image_fallback_api_key))
        if fallback_route_configured
        else None,
        image_fallback_uses_inherited_base_url=(config.openai_image_fallback_base_url in (None, ""))
        if fallback_route_configured
        else None,
        image_fallback_uses_inherited_request_timeout=(config.openai_image_fallback_request_timeout_seconds is None)
        if fallback_route_configured
        else None,
        image_fallback_route_difference_labels=list(config.image_fallback_route_difference_labels),
        image_fallback_route_note=config.image_fallback_route_note,
        image_fallback_route_recovery_actions=fallback_route_recovery_actions,
        image_fallback_route_config_hints=fallback_route_config_hints,
        image_fallback_route_env_example=fallback_route_env_example,
        image_fallback_route_env_example_note=fallback_route_env_example_note,
        image_fallback_account_pool_diagnosis_status=fallback_account_pool_diagnosis["status"],
        image_fallback_account_pool_diagnosis_label=fallback_account_pool_diagnosis["label"],
        image_fallback_account_pool_diagnosis_note=fallback_account_pool_diagnosis["note"],
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


def format_image_upstream_failure_message(
    error: Exception,
    *,
    prefix: str = "图片上游服务异常",
    api_only: bool = False,
) -> str:
    raw_message = _extract_openai_error_message(error)
    normalized = raw_message.lower()
    api_only_note = " 当前封面保持 API-only，不会改走本地兜底。" if api_only else ""

    if "no available compatible accounts" in normalized:
        return (
            f"{prefix}：当前图片 API 暂无可用账号，请稍后重试，或配置备用图片链路。"
            f"{api_only_note} 原始返回：{raw_message}"
        )

    transient_markers = (
        "temporarily unavailable",
        "service unavailable",
        "upstream",
        "timeout",
        "timed out",
        "connection reset",
        "connection aborted",
    )
    if any(marker in normalized for marker in transient_markers):
        return (
            f"{prefix}：当前图片 API 暂时不可用，请稍后重试。"
            f"{api_only_note} 原始返回：{raw_message}"
        )

    return f"{prefix}：{raw_message}{api_only_note}"


def _is_image_model_capability_error(error: Exception | None) -> bool:
    if error is None:
        return False
    normalized = _extract_openai_error_message(error).lower()
    return "requires an image model" in normalized


def _should_try_next_cover_image_route(error: Exception) -> bool:
    if isinstance(error, (APITimeoutError, openai.InternalServerError, openai.APIConnectionError)):
        return True
    if isinstance(error, openai.BadRequestError):
        return _is_image_model_capability_error(error)
    return False


def _build_image_check_recovery_actions(
    *,
    config: Settings,
    status: str,
    route_label: str | None = None,
    error: Exception | None = None,
) -> list[str]:
    actions: list[str] = []
    fallback_account_pool_diagnosis = _build_image_fallback_account_pool_diagnosis(config)
    if status == "missing_key":
        return [
            "先补齐图片链路可用的 Key；如果图片接口准备继承文本配置，至少要保证文本 Key 已经可用。",
            "补完后再点一次“检测出图”，确认图片请求能真实返回结果。",
        ]
    if status == "not_configured":
        return [
            "当前还没有备用图片链路；可补充 OPENAI_IMAGE_FALLBACK_MODEL、OPENAI_IMAGE_FALLBACK_BASE_URL、OPENAI_IMAGE_FALLBACK_API_KEY 后再试。",
            "只要 fallback 与主出图链路至少有一项不同，系统才会把它当成第二条图片 API。",
        ]
    if status == "inactive":
        return [
            "当前 fallback 字段已经填写，但它与主出图链路完全重合，还没有形成第二条图片 API。",
            "至少让 OPENAI_IMAGE_FALLBACK_MODEL、OPENAI_IMAGE_FALLBACK_BASE_URL、OPENAI_IMAGE_FALLBACK_API_KEY 或超时配置中的一项与主链路不同。",
        ]
    if status == "auth_error":
        return [
            "先核对图片 API Key 是否有效、是否过期，以及它是否对应当前图片接口。",
            "如果图片链路走的是独立配置，还要一起检查图片接口 Base URL 和模型名。",
        ]
    if status == "permission_error":
        return [
            "当前账号能连上接口，但没有足够的图片权限；先到上游服务确认图片模型授权范围。",
            "如果主链路权限暂时不足，可以改配一条有权限的备用图片链路再重试。",
        ]
    if status == "not_found":
        return [
            "先检查图片模型名和图片接口地址是否写对，尤其是自定义 Base URL 场景。",
            "如果这是兼容层接口，确认它实际支持当前这条图片生成协议。",
        ]
    if status == "bad_request":
        if _is_image_model_capability_error(error):
            target_label = "备用图片链路" if route_label == "fallback" else "当前图片链路"
            actions.append(f"{target_label}已经打到了图片接口，但所填模型不是图片模型；请改成上游支持的图片模型名。")
            if route_label == "fallback":
                actions.append("这次报错发生在 fallback 路由，优先检查 OPENAI_IMAGE_FALLBACK_MODEL 是否真的是图片模型。")
            else:
                actions.append("优先检查 OPENAI_IMAGE_MODEL 是否是图片模型；如果主链路没问题，再看备用链路配置。")
            return actions
        return [
            "当前请求已经打到上游，但接口不接受这组参数；优先检查图片模型、兼容层能力和接口文档。",
        ]
    if status == "rate_limited":
        return [
            "这是上游限流，先间隔一会再重试。",
            "如果图片任务比较多，建议补一条备用图片链路分流。",
        ]
    if status == "upstream_error":
        if error is not None and "no available compatible accounts" in _extract_openai_error_message(error).lower():
            actions.append("这次更像是上游账号池暂时不可用，不是本地封面逻辑回退。")
        actions.append("先稍后重试一次，很多 503 都是上游短时波动。")
        if config.image_fallback_route_active:
            if fallback_account_pool_diagnosis["status"] == "independent_hint":
                actions.append("当前已经配置备用图片链路，而且它不是完全复用主账号池；出图请求预算大于 1 时，正式出封面才会在主链路失败后尝试切到备用链路。")
            else:
                actions.append("当前虽然已经配置 fallback，但它仍沿用主出图接口和主 Key；如果主账号池出问题，这条 fallback 大概率也会一起失败。")
                actions.append("想真正绕开主账号池，优先单独提供 OPENAI_IMAGE_FALLBACK_BASE_URL 或 OPENAI_IMAGE_FALLBACK_API_KEY。")
        elif config.image_fallback_route_configured:
            actions.append("当前 fallback 字段已经填写，但它与主出图链路完全重合，还没有形成第二条图片 API。")
            actions.append("要让备用链路真正生效，至少需要让 OPENAI_IMAGE_FALLBACK_MODEL、OPENAI_IMAGE_FALLBACK_BASE_URL、OPENAI_IMAGE_FALLBACK_API_KEY 或超时配置中的一项与主链路不同。")
        else:
            actions.append("当前还没有备用图片链路；可补充 OPENAI_IMAGE_FALLBACK_MODEL、OPENAI_IMAGE_FALLBACK_BASE_URL、OPENAI_IMAGE_FALLBACK_API_KEY 后再试。")
        actions.append("当前封面保持 API-only，不会改走本地兜底。")
        return actions
    if status == "ok" and route_label == "fallback":
        return [
            "这次检测已经命中备用图片链路，说明第二条图片 API 可用；正式出封面是否切到备用链路，还取决于出图请求预算是否大于 1。",
        ]
    return actions


def _build_image_fallback_config_hints(config: Settings) -> list[str]:
    def _format_base_url(value: str | None) -> str:
        text = str(value or "").strip()
        return text or "OpenAI 默认"

    def _format_timeout(value: float) -> str:
        return f"{value:g} 秒"

    hints: list[str] = []

    fallback_model = (config.openai_image_fallback_model or "").strip()
    if fallback_model:
        hints.append(f"OPENAI_IMAGE_FALLBACK_MODEL：已填写 {fallback_model}")
    else:
        hints.append(f"OPENAI_IMAGE_FALLBACK_MODEL：未填写；当前会继承主出图模型 {config.openai_image_model}")

    if config.openai_image_fallback_base_url not in (None, ""):
        hints.append(f"OPENAI_IMAGE_FALLBACK_BASE_URL：已填写 {_format_base_url(config.openai_image_fallback_base_url)}")
    else:
        hints.append(
            f"OPENAI_IMAGE_FALLBACK_BASE_URL：未填写；当前会继承主出图接口 {_format_base_url(config.effective_openai_image_base_url)}"
        )

    if config.openai_image_fallback_api_key:
        hints.append("OPENAI_IMAGE_FALLBACK_API_KEY：已填写独立 fallback Key")
    else:
        primary_key_label = "已配置" if config.effective_openai_image_api_key else "未配置"
        hints.append(f"OPENAI_IMAGE_FALLBACK_API_KEY：未填写；当前会继承主出图链路 Key（{primary_key_label}）")

    if config.openai_image_fallback_request_timeout_seconds is not None:
        hints.append(
            "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS：已填写 "
            f"{_format_timeout(config.openai_image_fallback_request_timeout_seconds)}"
        )
    else:
        hints.append(
            "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS：未填写；当前会继承主出图超时 "
            f"{_format_timeout(config.effective_openai_image_request_timeout_seconds)}"
        )

    return hints


def _build_image_fallback_env_example(config: Settings) -> tuple[list[str], str]:
    timeout_hint = f"{config.effective_openai_image_request_timeout_seconds:g}"
    lines = [
        "OPENAI_IMAGE_FALLBACK_MODEL=<与主出图不同的图片模型>",
        "OPENAI_IMAGE_FALLBACK_BASE_URL=<可选：独立图片接口；想绕开当前主链路账号池时优先填写>",
        "OPENAI_IMAGE_FALLBACK_API_KEY=<可选：独立图片 Key；想绕开当前主链路账号池时优先填写>",
        f"OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS={timeout_hint}",
    ]
    note = (
        "想让系统识别第二条图片 API，以上四项里只要有一项与主链路不同即可；"
        "但如果你是想绕开当前主出图账号池，优先单独提供 fallback Base URL 或 fallback Key。"
    )
    return lines, note


def _build_image_fallback_account_pool_diagnosis(config: Settings) -> dict[str, str]:
    if not config.image_fallback_route_configured:
        return {
            "status": "not_configured",
            "label": "未形成第二套上游",
            "note": "当前还没有配置 fallback，所以主路由一旦因为账号池问题失败，系统没有第二套图片上游可以尝试。",
        }
    if not config.image_fallback_route_active:
        return {
            "status": "inactive",
            "label": "还没形成第二条图片 API",
            "note": "fallback 字段虽然填写了，但它与主链路还没有拉开差异，因此也谈不上绕开主账号池。",
        }

    has_distinct_key = bool(config.openai_image_fallback_api_key)
    has_distinct_base_url = config.openai_image_fallback_base_url not in (None, "")

    if has_distinct_key and has_distinct_base_url:
        return {
            "status": "independent_hint",
            "label": "大概率可绕开主账号池",
            "note": "fallback 同时使用了独立接口和独立 Key，不再完全复用主路由；出图请求预算大于 1 时，它更有机会在主路由账号池失败后接住封面生成。",
        }
    if has_distinct_key:
        return {
            "status": "independent_hint",
            "label": "更有机会绕开主账号池",
            "note": "fallback 仍走主接口，但已经切到独立 Key；如果上游账号池按 Key 隔离，这条路由通常更有机会绕开主账号池。",
        }
    if has_distinct_base_url:
        return {
            "status": "independent_hint",
            "label": "有机会绕开主账号池",
            "note": "fallback 已切到独立接口，但仍沿用主 Key；它是否能绕开主账号池，取决于这个接口背后的账号池是否独立。",
        }
    return {
        "status": "shared_pool",
        "label": "仍可能共用主账号池",
        "note": "这条 fallback 目前只改了模型或超时，仍沿用主出图接口和主 Key；如果主账号池出问题，它大概率也会一起失败。",
    }


def _build_ai_image_check_success_message(route_label: str | None) -> str:
    if route_label == "fallback":
        return "图片配置检测通过，主出图链路失败时已切到备用图片链路。"
    return "图片配置检测通过，当前图像模型可以正常返回图片。"


def _build_ai_image_check_failure_result(
    *,
    config: Settings,
    checked_at: str,
    exc: Exception,
) -> AIConfigCheckResult:
    route_label = getattr(exc, "cover_image_route_label", None)
    normalized_route_label = str(route_label) if route_label is not None else None

    if isinstance(exc, openai.AuthenticationError):
        return AIConfigCheckResult(
            ok=False,
            status="auth_error",
            message=f"图片认证失败：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
            route_label=normalized_route_label,
            recovery_actions=_build_image_check_recovery_actions(
                config=config,
                status="auth_error",
                route_label=normalized_route_label,
                error=exc,
            ),
        )
    if isinstance(exc, openai.PermissionDeniedError):
        return AIConfigCheckResult(
            ok=False,
            status="permission_error",
            message=f"图片权限不足：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
            route_label=normalized_route_label,
            recovery_actions=_build_image_check_recovery_actions(
                config=config,
                status="permission_error",
                route_label=normalized_route_label,
                error=exc,
            ),
        )
    if isinstance(exc, openai.NotFoundError):
        return AIConfigCheckResult(
            ok=False,
            status="not_found",
            message=f"图片模型或接口不存在：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
            route_label=normalized_route_label,
            recovery_actions=_build_image_check_recovery_actions(
                config=config,
                status="not_found",
                route_label=normalized_route_label,
                error=exc,
            ),
        )
    if isinstance(exc, openai.BadRequestError):
        return AIConfigCheckResult(
            ok=False,
            status="bad_request",
            message=f"图片请求参数错误：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
            route_label=normalized_route_label,
            recovery_actions=_build_image_check_recovery_actions(
                config=config,
                status="bad_request",
                route_label=normalized_route_label,
                error=exc,
            ),
        )
    if isinstance(exc, openai.RateLimitError):
        return AIConfigCheckResult(
            ok=False,
            status="rate_limited",
            message=f"图片请求频率受限：{_extract_openai_error_message(exc)}",
            checked_at=checked_at,
            route_label=normalized_route_label,
            recovery_actions=_build_image_check_recovery_actions(
                config=config,
                status="rate_limited",
                route_label=normalized_route_label,
                error=exc,
            ),
        )
    if isinstance(exc, (openai.InternalServerError, APIConnectionError, APITimeoutError)):
        return AIConfigCheckResult(
            ok=False,
            status="upstream_error",
            message=format_image_upstream_failure_message(
                exc,
                api_only=True,
            ),
            checked_at=checked_at,
            route_label=normalized_route_label,
            recovery_actions=_build_image_check_recovery_actions(
                config=config,
                status="upstream_error",
                route_label=normalized_route_label,
                error=exc,
            ),
        )
    return AIConfigCheckResult(
        ok=False,
        status="unexpected_error",
        message=f"图片检测失败：{_extract_openai_error_message(exc)}",
        checked_at=checked_at,
        route_label=normalized_route_label,
    )


_NUMERIC_IMAGE_SIZE_PATTERN = re.compile(r"^\d+x\d+$")
_IMAGE_RATIO_FALLBACKS = {
    "1536x864": "16:9",
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


def run_ai_image_config_check(config: Settings = settings) -> AIConfigCheckResult:
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    effective_image_api_key = config.effective_openai_image_api_key
    if not effective_image_api_key:
        return AIConfigCheckResult(
            ok=False,
            status="missing_key",
            message="图片模型 Key 未配置，当前无法发起出图请求。",
            checked_at=checked_at,
            recovery_actions=_build_image_check_recovery_actions(
                config=config,
                status="missing_key",
            ),
        )

    image_probe_config = config.model_copy(
        update={
            "openai_api_key": config.openai_api_key or effective_image_api_key,
        }
    )

    try:
        route_label = OpenAIWorkbenchGenerator(image_probe_config).check_image_connection()
        return AIConfigCheckResult(
            ok=True,
            status="ok",
            message=_build_ai_image_check_success_message(route_label),
            checked_at=checked_at,
            route_label=route_label,
            recovery_actions=_build_image_check_recovery_actions(
                config=config,
                status="ok",
                route_label=route_label,
            ),
        )
    except Exception as exc:
        return _build_ai_image_check_failure_result(
            config=config,
            checked_at=checked_at,
            exc=exc,
        )


def run_ai_image_route_probe(config: Settings = settings) -> AIImageRouteProbeResult:
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    effective_image_api_key = config.effective_openai_image_api_key
    if not effective_image_api_key:
        return AIImageRouteProbeResult(
            any_ok=False,
            checked_at=checked_at,
            routes=[
                AIImageRouteProbeItem(
                    route_label="primary",
                    configured_model=config.openai_image_model,
                    configured_base_url=config.effective_openai_image_base_url,
                    ok=False,
                    status="missing_key",
                    message="图片模型 Key 未配置，当前无法发起出图请求。",
                    checked_at=checked_at,
                    recovery_actions=_build_image_check_recovery_actions(
                        config=config,
                        status="missing_key",
                    ),
                )
            ],
        )

    image_probe_config = config.model_copy(
        update={
            "openai_api_key": config.openai_api_key or effective_image_api_key,
        }
    )
    generator = OpenAIWorkbenchGenerator(image_probe_config)
    prompt = "16:9 横版公众号头图，暖灯下的室内场景，真实摄影感，不要文字。"
    original_routes = list(generator._image_routes)
    route_results: list[AIImageRouteProbeItem] = []

    for route in original_routes:
        route_label = str(route.get("label") or "unknown")
        configured_model = str(route.get("model") or "").strip() or None
        configured_base_url = str(route.get("base_url") or "").strip() or None
        try:
            generator._image_routes = [route]
            try:
                _image_bytes, used_route_label = generator._generate_cover_image_with_route(
                    prompt,
                    max_request_attempts=1,
                )
            except TypeError as exc:
                if "max_request_attempts" not in str(exc):
                    raise
                _image_bytes, used_route_label = generator._generate_cover_image_with_route(prompt)
            route_results.append(
                AIImageRouteProbeItem(
                    route_label=route_label,
                    configured_model=configured_model,
                    configured_base_url=configured_base_url,
                    ok=True,
                    status="ok",
                    message=_build_ai_image_check_success_message(used_route_label),
                    checked_at=checked_at,
                    recovery_actions=_build_image_check_recovery_actions(
                        config=config,
                        status="ok",
                        route_label=used_route_label,
                    ),
                )
            )
        except Exception as exc:
            failure = _build_ai_image_check_failure_result(
                config=config,
                checked_at=checked_at,
                exc=exc,
            )
            route_results.append(
                AIImageRouteProbeItem(
                    route_label=route_label,
                    configured_model=configured_model,
                    configured_base_url=configured_base_url,
                    ok=False,
                    status=failure.status,
                    message=failure.message,
                    checked_at=checked_at,
                    recovery_actions=list(failure.recovery_actions),
                )
            )
        finally:
            generator._image_routes = list(original_routes)

    if not any(item.route_label == "fallback" for item in route_results):
        if config.image_fallback_route_configured and not config.image_fallback_route_active:
            route_results.append(
                AIImageRouteProbeItem(
                    route_label="fallback",
                    configured_model=config.effective_openai_image_fallback_model,
                    configured_base_url=config.effective_openai_image_fallback_base_url,
                    ok=False,
                    status="inactive",
                    message=config.image_fallback_route_note or "已填写 fallback 字段，但当前还没有形成第二条图片 API。",
                    checked_at=checked_at,
                    recovery_actions=_build_image_check_recovery_actions(
                        config=config,
                        status="inactive",
                    ),
                )
            )
        elif not config.image_fallback_route_configured:
            route_results.append(
                AIImageRouteProbeItem(
                    route_label="fallback",
                    configured_model=None,
                    configured_base_url=None,
                    ok=False,
                    status="not_configured",
                    message=config.image_fallback_route_note or "当前未配置备用图片链路。",
                    checked_at=checked_at,
                    recovery_actions=_build_image_check_recovery_actions(
                        config=config,
                        status="not_configured",
                    ),
                )
            )

    return AIImageRouteProbeResult(
        any_ok=any(item.ok for item in route_results),
        checked_at=checked_at,
        routes=route_results,
    )


@lru_cache(maxsize=1)
def get_default_generator() -> OpenAIWorkbenchGenerator:
    return OpenAIWorkbenchGenerator(settings)
