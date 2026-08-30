from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any
from collections.abc import Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "apps" / "backend"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
_QUIET_BACKEND_LOGGER_NAMES = (
    "app.services.workbench",
    "app.services.ai_generator",
)
AI_OVERRIDE_ENV_FIELDS: tuple[tuple[str, str], ...] = (
    ("openai_api_key", "OPENAI_API_KEY"),
    ("openai_base_url", "OPENAI_BASE_URL"),
    ("openai_model", "OPENAI_MODEL"),
    ("openai_reasoning_effort", "OPENAI_REASONING_EFFORT"),
    ("openai_request_timeout_seconds", "OPENAI_REQUEST_TIMEOUT_SECONDS"),
    ("openai_allow_local_creative_fallbacks", "OPENAI_ALLOW_LOCAL_CREATIVE_FALLBACKS"),
    ("openai_creative_quality_retry_max_attempts", "OPENAI_CREATIVE_QUALITY_RETRY_MAX_ATTEMPTS"),
    ("openai_image_api_key", "OPENAI_IMAGE_API_KEY"),
    ("openai_image_base_url", "OPENAI_IMAGE_BASE_URL"),
    ("openai_image_model", "OPENAI_IMAGE_MODEL"),
    ("openai_image_request_timeout_seconds", "OPENAI_IMAGE_REQUEST_TIMEOUT_SECONDS"),
    ("openai_image_generation_max_attempts", "OPENAI_IMAGE_GENERATION_MAX_ATTEMPTS"),
    ("openai_image_fallback_api_key", "OPENAI_IMAGE_FALLBACK_API_KEY"),
    ("openai_image_fallback_base_url", "OPENAI_IMAGE_FALLBACK_BASE_URL"),
    ("openai_image_fallback_model", "OPENAI_IMAGE_FALLBACK_MODEL"),
    ("openai_image_fallback_request_timeout_seconds", "OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS"),
)


def _safe_print_json(payload: Mapping[str, Any]) -> None:
    try:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    except OSError:
        return


def _configure_utf8_stdio() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a minimal live AI smoke for the current workbench config.")
    parser.add_argument("--trend-slug", default="office-burnout-recovery", help="Trend slug used for the smoke run.")
    parser.add_argument("--owner", default="live-smoke", help="Project owner label for the smoke run.")
    parser.add_argument("--project-slug", default=None, help="Optional fixed project slug.")
    parser.add_argument("--project-title", default=None, help="Optional fixed project title.")
    parser.add_argument("--skip-reset", action="store_true", help="Reuse the current store instead of resetting it first.")
    parser.add_argument(
        "--verbose-backend-logs",
        action="store_true",
        help="Keep backend warning logs visible during the smoke run. Default behavior keeps structured JSON output quieter.",
    )
    parser.add_argument("--db-path", default=None, help="Optional DB_PATH override for this run only.")
    parser.add_argument(
        "--generated-assets-dir",
        default=None,
        help="Optional GENERATED_ASSETS_DIR override for this run only.",
    )
    parser.add_argument(
        "--assets-only",
        action="store_true",
        help="Stop after generate_assets so this run verifies the real cover-generation stage without building a publish package.",
    )
    parser.add_argument(
        "--cover-regeneration-only",
        action="store_true",
        help="Seed a minimal project/draft/assets record, then hit regenerate_cover_image directly to verify the business cover path.",
    )
    parser.add_argument("--summary-only", action="store_true", help="Only print the current effective AI config summary without calling any live model route.")
    parser.add_argument("--check-only", action="store_true", help="Only run the AI config check without creating content.")
    parser.add_argument("--check-text-only", action="store_true", help="Only run the live text-model connectivity check.")
    parser.add_argument("--check-image-only", action="store_true", help="Only run the live image-model connectivity check.")
    parser.add_argument(
        "--skip-ai-preflight",
        action="store_true",
        help="Skip the text-generation probe, but keep the zero-token model compatibility check before the smoke pipeline.",
    )
    parser.add_argument(
        "--probe-text-routes",
        action="store_true",
        help="Probe responses.create / responses.parse / chat.completions directly before running the full smoke chain.",
    )
    parser.add_argument(
        "--probe-image-routes",
        action="store_true",
        help="Probe each configured image route directly before running the full smoke chain.",
    )
    parser.add_argument("--openai-api-key", default=None, help="Optional OPENAI_API_KEY override for this run only.")
    parser.add_argument("--openai-base-url", default=None, help="Optional OPENAI_BASE_URL override for this run only.")
    parser.add_argument(
        "--clear-openai-base-url",
        action="store_true",
        help="Clear OPENAI_BASE_URL for this run only, useful when temporarily switching off a proxy.",
    )
    parser.add_argument("--openai-model", default=None, help="Optional OPENAI_MODEL override for this run only.")
    parser.add_argument(
        "--openai-reasoning-effort",
        default=None,
        help="Optional OPENAI_REASONING_EFFORT override for this run only.",
    )
    parser.add_argument(
        "--openai-request-timeout-seconds",
        type=float,
        default=None,
        help="Optional OPENAI_REQUEST_TIMEOUT_SECONDS override for this run only.",
    )
    parser.add_argument(
        "--openai-allow-local-creative-fallbacks",
        choices=("true", "false"),
        default=None,
        help="Optional OPENAI_ALLOW_LOCAL_CREATIVE_FALLBACKS override for this run only.",
    )
    parser.add_argument(
        "--openai-creative-quality-retry-max-attempts",
        type=int,
        default=None,
        help="Optional OPENAI_CREATIVE_QUALITY_RETRY_MAX_ATTEMPTS override for this run only.",
    )
    parser.add_argument("--openai-image-api-key", default=None, help="Optional OPENAI_IMAGE_API_KEY override for this run only.")
    parser.add_argument("--openai-image-base-url", default=None, help="Optional OPENAI_IMAGE_BASE_URL override for this run only.")
    parser.add_argument(
        "--clear-openai-image-base-url",
        action="store_true",
        help="Clear OPENAI_IMAGE_BASE_URL for this run only, so image requests inherit the current text base URL.",
    )
    parser.add_argument("--openai-image-model", default=None, help="Optional OPENAI_IMAGE_MODEL override for this run only.")
    parser.add_argument(
        "--openai-image-request-timeout-seconds",
        type=float,
        default=None,
        help="Optional OPENAI_IMAGE_REQUEST_TIMEOUT_SECONDS override for this run only.",
    )
    parser.add_argument(
        "--openai-image-generation-max-attempts",
        type=int,
        default=None,
        help="Optional OPENAI_IMAGE_GENERATION_MAX_ATTEMPTS override for this run only.",
    )
    parser.add_argument("--openai-image-fallback-api-key", default=None, help="Optional OPENAI_IMAGE_FALLBACK_API_KEY override for this run only.")
    parser.add_argument("--openai-image-fallback-base-url", default=None, help="Optional OPENAI_IMAGE_FALLBACK_BASE_URL override for this run only.")
    parser.add_argument(
        "--clear-openai-image-fallback-base-url",
        action="store_true",
        help="Clear OPENAI_IMAGE_FALLBACK_BASE_URL for this run only, so the fallback image route inherits the current image base URL.",
    )
    parser.add_argument("--openai-image-fallback-model", default=None, help="Optional OPENAI_IMAGE_FALLBACK_MODEL override for this run only.")
    parser.add_argument(
        "--openai-image-fallback-request-timeout-seconds",
        type=float,
        default=None,
        help="Optional OPENAI_IMAGE_FALLBACK_REQUEST_TIMEOUT_SECONDS override for this run only.",
    )
    return parser


def _normalize_ai_override_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return str(value)
    text = str(value).strip()
    return text or None


def _collect_ai_override_env(args: argparse.Namespace) -> tuple[dict[str, str], set[str]]:
    overrides: dict[str, str] = {}
    cleared_env_names: set[str] = set()
    if getattr(args, "clear_openai_base_url", False):
        overrides["OPENAI_BASE_URL"] = DEFAULT_OPENAI_BASE_URL
    if getattr(args, "clear_openai_image_base_url", False):
        overrides["OPENAI_IMAGE_BASE_URL"] = ""
    if getattr(args, "clear_openai_image_fallback_base_url", False):
        overrides["OPENAI_IMAGE_FALLBACK_BASE_URL"] = ""
    for field_name, env_name in AI_OVERRIDE_ENV_FIELDS:
        normalized = _normalize_ai_override_value(getattr(args, field_name, None))
        if normalized is not None:
            overrides[env_name] = normalized
            cleared_env_names.discard(env_name)
    return overrides, cleared_env_names


def _apply_ai_overrides(args: argparse.Namespace) -> dict[str, str]:
    overrides, cleared_env_names = _collect_ai_override_env(args)
    for env_name in cleared_env_names:
        os.environ.pop(env_name, None)
    for env_name, value in overrides.items():
        os.environ[env_name] = value
    return overrides


def _apply_runtime_path_overrides(args: argparse.Namespace) -> None:
    db_path = str(getattr(args, "db_path", "") or "").strip()
    if db_path:
        os.environ["DB_PATH"] = db_path
    generated_assets_dir = str(getattr(args, "generated_assets_dir", "") or "").strip()
    if generated_assets_dir:
        os.environ["GENERATED_ASSETS_DIR"] = generated_assets_dir


def _configure_backend_log_verbosity(args: argparse.Namespace) -> None:
    if getattr(args, "verbose_backend_logs", False):
        return
    for logger_name in _QUIET_BACKEND_LOGGER_NAMES:
        logging.getLogger(logger_name).setLevel(logging.ERROR)


def _load_backend_bindings() -> dict[str, Any]:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.core.settings import settings
    from app.schemas.projects import ProjectCreate
    from app.services.ai_generator import (
        OpenAIWorkbenchGenerator,
        TopicGenerationResult,
        get_ai_config_summary,
        run_ai_config_check,
        run_ai_model_compatibility_check,
        run_ai_image_config_check,
    )
    from app.services.workbench import (
        build_publish_package,
        create_project_from_topic,
        generate_assets,
        generate_draft,
        generate_outline,
        generate_topic_from_trend,
        get_project_detail,
        initialize_store,
        regenerate_cover_image,
    )

    return {
        "settings": settings,
        "ProjectCreate": ProjectCreate,
        "OpenAIWorkbenchGenerator": OpenAIWorkbenchGenerator,
        "TopicGenerationResult": TopicGenerationResult,
        "get_ai_config_summary": get_ai_config_summary,
        "run_ai_config_check": run_ai_config_check,
        "run_ai_model_compatibility_check": run_ai_model_compatibility_check,
        "run_ai_image_config_check": run_ai_image_config_check,
        "initialize_store": initialize_store,
        "generate_topic_from_trend": generate_topic_from_trend,
        "create_project_from_topic": create_project_from_topic,
        "generate_outline": generate_outline,
        "generate_draft": generate_draft,
        "generate_assets": generate_assets,
        "build_publish_package": build_publish_package,
        "get_project_detail": get_project_detail,
        "regenerate_cover_image": regenerate_cover_image,
    }


def _build_error_payload(exc: Exception) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": exc.__class__.__name__,
        "message": str(exc),
        "body": getattr(exc, "body", None),
    }
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int):
        payload["status_code"] = status_code
    detail = getattr(exc, "detail", None)
    if detail is not None:
        payload["detail"] = detail
    for attr_name in ("cover_image_route_label", "cover_image_route_model", "cover_image_route_base_url"):
        attr_value = getattr(exc, attr_name, None)
        if attr_value is not None:
            payload[attr_name] = attr_value
    return payload


def _build_partial_pipeline_payload(
    *,
    get_ai_config_summary,
    topic: object | None = None,
    project: object | None = None,
    outline: object | None = None,
    draft: object | None = None,
    assets: object | None = None,
    publish_package: object | None = None,
    detail: object | None = None,
    stage_error: dict[str, object] | None = None,
) -> dict[str, object]:
    result: dict[str, object] = {
        "ai_config": get_ai_config_summary().model_dump(),
    }
    if topic is not None:
        result["topic"] = topic.model_dump()
    if project is not None:
        result["project"] = project.model_dump()
    if outline is not None:
        result["outline"] = outline.model_dump()
    if draft is not None:
        result["draft"] = {
            "project_slug": draft.project_slug,
            "version": draft.version,
            "title": draft.title,
            "word_count": draft.word_count,
        }
    if assets is not None:
        result["assets"] = {
            "project_slug": assets.project_slug,
            "version": assets.version,
            "title_options": assets.title_options,
            "cover_copy": assets.cover_copy,
            "cover_image_url": assets.cover_image_url,
            "cover_image_status": getattr(assets, "cover_image_status", None),
            "cover_image_error": getattr(assets, "cover_image_error", None),
            "cover_image_route_label": getattr(assets, "cover_image_route_label", None),
            "cover_image_route_model": getattr(assets, "cover_image_route_model", None),
            "cover_image_route_base_url": getattr(assets, "cover_image_route_base_url", None),
        }
    if publish_package is not None:
        result["publish_package"] = {
            "project_slug": publish_package.project_slug,
            "version": publish_package.version,
            "abstract": publish_package.abstract,
            "tags": publish_package.tags,
            "manifest_url": publish_package.manifest_url,
            "markdown_url": publish_package.markdown_url,
        }
    if detail is not None:
        result["detail"] = detail.model_dump()
    if stage_error is not None:
        result["stage_error"] = stage_error
    return result


def _seed_cover_regeneration_smoke_project(*, settings: object, project_slug: str, owner: str) -> None:
    db_path = Path(str(getattr(settings, "db_path")))
    topic_slug = f"{project_slug}-cover-topic"
    project_title = "把家稳住的人，也该被好好接住"
    cover_prompt = "16:9 横版公众号封面，真实家庭夜晚场景，玄关暖灯，人物刚回到家。"
    draft_body = (
        "夜里推门回家时，桌上那碗热饭还冒着一点热气，旁边压着今天的单据和一支没盖帽的笔。\n\n"
        "很多辛苦不是没人看见，只是大家都先把那句心疼压住了。直到灯还亮着、饭还热着，人才突然明白，"
        "原来真正能托住一个人的，从来不是硬扛，而是回到家时还有一盏灯在等。"
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM assets WHERE project_slug = ?", (project_slug,))
        connection.execute("DELETE FROM drafts WHERE project_slug = ?", (project_slug,))
        connection.execute("DELETE FROM projects WHERE slug = ?", (project_slug,))
        connection.execute("DELETE FROM topics WHERE slug = ?", (topic_slug,))
        connection.execute(
            """
            INSERT INTO topics (slug, trend_slug, source_type, source_ref_slug, title, angle, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                topic_slug,
                "",
                "manual",
                "",
                project_title,
                "从回家时那盏灯和一碗热饭切入，写被接住的人间感。",
                "approved",
            ),
        )
        connection.execute(
            """
            INSERT INTO projects (slug, topic_slug, title, stage, owner)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                topic_slug,
                project_title,
                "assets_ready",
                owner,
            ),
        )
        connection.execute(
            """
            INSERT INTO drafts (
                project_slug, outline_version, version, title, body_markdown, word_count, created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                1,
                1,
                project_title,
                draft_body,
                114,
                "2026-07-17T00:00:00Z",
                "generate",
                None,
                None,
            ),
        )
        connection.execute(
            """
            INSERT INTO assets (
                project_slug, draft_version, version, title_options, recommended_title, cover_prompt, cover_copy, social_teaser, social_teaser_options,
                cover_image_path, cover_image_url, created_at, origin, tone_profile_id, tone_profile_name
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_slug,
                1,
                1,
                json.dumps([project_title], ensure_ascii=False),
                project_title,
                cover_prompt,
                "把家稳住的人，也该有人给他留一盏灯。",
                "有时候托住一个人的，不是大道理，是夜里回家时那盏还亮着的灯。",
                json.dumps(
                    [
                        "有时候托住一个人的，不是大道理，是夜里回家时那盏还亮着的灯。",
                        "很多辛苦不需要被歌颂，但需要被接住。",
                    ],
                    ensure_ascii=False,
                ),
                "seed-cover.png",
                "/generated-assets/seed-cover.png",
                "2026-07-17T00:01:00Z",
                "generate",
                None,
                None,
            ),
        )
        connection.commit()


def _run_text_route_probe(backend: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    settings = backend["settings"]
    generator = backend["OpenAIWorkbenchGenerator"](settings)
    TopicGenerationResult = backend["TopicGenerationResult"]
    get_ai_config_summary = backend["get_ai_config_summary"]
    client = generator._client
    model = settings.openai_model
    timeout = min(max(float(settings.openai_request_timeout_seconds), 1.0), 30.0)
    routes: dict[str, dict[str, object]] = {}

    try:
        response = client.responses.create(
            model=model,
            input="Reply with exactly OK.",
            max_output_tokens=8,
            timeout=timeout,
        )
        routes["responses_create_text"] = {
            "ok": True,
            "output_text": getattr(response, "output_text", None),
        }
    except Exception as exc:  # pragma: no cover - exercised in live use
        routes["responses_create_text"] = {"ok": False, "error": _build_error_payload(exc)}

    try:
        response = client.responses.create(
            model=model,
            instructions="只返回一个 JSON 对象，不要解释。",
            input='返回 {"title":"ok","angle":"ok"}',
            timeout=timeout,
        )
        routes["responses_create_json_text"] = {
            "ok": True,
            "output_text": getattr(response, "output_text", None),
        }
    except Exception as exc:  # pragma: no cover - exercised in live use
        routes["responses_create_json_text"] = {"ok": False, "error": _build_error_payload(exc)}

    try:
        response = client.responses.parse(
            model=model,
            instructions="只返回 JSON。",
            input="返回 title=ok, angle=ok",
            text_format=TopicGenerationResult,
            timeout=timeout,
        )
        parsed = getattr(response, "output_parsed", None)
        routes["responses_parse_topic"] = {
            "ok": parsed is not None,
            "parsed": parsed.model_dump() if parsed is not None else None,
            "output_text": getattr(response, "output_text", None),
        }
    except Exception as exc:  # pragma: no cover - exercised in live use
        routes["responses_parse_topic"] = {"ok": False, "error": _build_error_payload(exc)}

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "只返回一个 JSON 对象，不要解释。"},
                {"role": "user", "content": '返回 {"title":"ok","angle":"ok"}'},
            ],
            response_format={"type": "json_object"},
            timeout=timeout,
        )
        routes["chat_completions_json"] = {
            "ok": True,
            "content": response.choices[0].message.content,
        }
    except Exception as exc:  # pragma: no cover - exercised in live use
        routes["chat_completions_json"] = {"ok": False, "error": _build_error_payload(exc)}

    any_ok = any(bool(route.get("ok")) for route in routes.values())
    payload = {
        "ai_config": get_ai_config_summary().model_dump(),
        "routes": routes,
    }
    return payload, any_ok


def _run_image_route_probe(backend: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    settings = backend["settings"]
    generator = backend["OpenAIWorkbenchGenerator"](settings)
    get_ai_config_summary = backend["get_ai_config_summary"]
    prompt = "16:9 横版公众号头图，真实摄影感，暖灯下的室内生活场景，不要文字。"
    routes: dict[str, dict[str, object]] = {}
    original_routes = list(generator._image_routes)

    for route in original_routes:
        route_label = str(route.get("label") or "unknown")
        route_base_url = route.get("base_url") or "default-openai"
        try:
            generator._image_routes = [route]
            image_bytes, used_route_label = generator._generate_cover_image_with_route(prompt)
            routes[route_label] = {
                "ok": True,
                "configured_model": route.get("model"),
                "configured_base_url": route_base_url,
                "used_route_label": used_route_label,
                "byte_length": len(image_bytes),
            }
        except Exception as exc:  # pragma: no cover - exercised in live use
            routes[route_label] = {
                "ok": False,
                "configured_model": route.get("model"),
                "configured_base_url": route_base_url,
                "error": _build_error_payload(exc),
            }
        finally:
            generator._image_routes = list(original_routes)

    any_ok = any(bool(route.get("ok")) for route in routes.values())
    payload = {
        "ai_config": get_ai_config_summary().model_dump(),
        "routes": routes,
    }
    return payload, any_ok


def main(argv: list[str] | None = None) -> int:
    _configure_utf8_stdio()
    args = _build_parser().parse_args(argv)
    _apply_ai_overrides(args)
    _apply_runtime_path_overrides(args)
    _configure_backend_log_verbosity(args)
    backend = _load_backend_bindings()
    settings = backend["settings"]
    get_ai_config_summary = backend["get_ai_config_summary"]

    if args.summary_only:
        _safe_print_json({"ai_config": get_ai_config_summary().model_dump()})
        return 0

    run_ai_config_check = backend["run_ai_config_check"]
    run_ai_model_compatibility_check = backend.get(
        "run_ai_model_compatibility_check",
        run_ai_config_check,
    )
    run_ai_image_config_check = backend["run_ai_image_config_check"]

    if args.probe_text_routes:
        payload, any_ok = _run_text_route_probe(backend)
        _safe_print_json(payload)
        return 0 if any_ok else 1

    if args.probe_image_routes:
        payload, any_ok = _run_image_route_probe(backend)
        _safe_print_json(payload)
        return 0 if any_ok else 1

    if args.check_only or args.check_text_only or args.check_image_only:
        run_text_check = args.check_only or args.check_text_only
        run_image_check = args.check_only or args.check_image_only
        result: dict[str, object] = {
            "ai_config": get_ai_config_summary().model_dump(),
        }
        ok = True
        if run_text_check:
            check_result = run_ai_config_check()
            result["check"] = check_result.model_dump()
            ok = ok and bool(check_result.ok)
        if run_image_check:
            image_check_result = run_ai_image_config_check()
            result["image_check"] = image_check_result.model_dump()
            ok = ok and bool(image_check_result.ok)
        _safe_print_json(result)
        return 0 if ok else 1

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    if not args.cover_regeneration_only:
        preflight = (
            run_ai_model_compatibility_check()
            if args.skip_ai_preflight
            else run_ai_config_check()
        )
        if preflight is not None and not preflight.ok:
            _safe_print_json(
                {
                    "ai_config": get_ai_config_summary().model_dump(),
                    "ai_preflight": preflight.model_dump(),
                    "stage_error": {
                        "stage": "ai_model_compatibility" if args.skip_ai_preflight else "ai_preflight",
                        "error": {
                            "type": "AIConfigPreflightError",
                            "message": preflight.message,
                        },
                    },
                }
            )
            return 1

    if not args.skip_reset:
        backend["initialize_store"](reset=True)

    if args.cover_regeneration_only:
        project_slug = args.project_slug or "api-only-cover-regeneration-live-project"
        current_stage = "seed_cover_regeneration_project"
        try:
            _seed_cover_regeneration_smoke_project(
                settings=settings,
                project_slug=project_slug,
                owner=args.owner,
            )
            current_stage = "regenerate_cover_image"
            asset = backend["regenerate_cover_image"](project_slug)
        except Exception as exc:
            _safe_print_json(
                {
                    "ai_config": get_ai_config_summary().model_dump(),
                    "project_slug": project_slug,
                    "stage_error": {
                        "stage": current_stage,
                        "error": _build_error_payload(exc),
                    },
                }
            )
            return 1

        _safe_print_json(
            {
                "ai_config": get_ai_config_summary().model_dump(),
                "project_slug": project_slug,
                "cover_regeneration": {
                    "project_slug": asset.project_slug,
                    "draft_version": asset.draft_version,
                    "version": asset.version,
                    "cover_prompt": asset.cover_prompt,
                    "cover_copy": asset.cover_copy,
                    "cover_image_path": asset.cover_image_path,
                    "cover_image_url": asset.cover_image_url,
                    "cover_image_status": getattr(asset, "cover_image_status", None),
                    "cover_image_error": getattr(asset, "cover_image_error", None),
                    "cover_image_route_label": getattr(asset, "cover_image_route_label", None),
                    "cover_image_route_model": getattr(asset, "cover_image_route_model", None),
                    "cover_image_route_base_url": getattr(asset, "cover_image_route_base_url", None),
                    "origin": asset.origin,
                },
            }
        )
        return 0

    topic = None
    project = None
    outline = None
    draft = None
    assets = None
    publish_package = None
    detail = None
    current_stage = "generate_topic_from_trend"
    try:
        topic = backend["generate_topic_from_trend"](args.trend_slug)
        ProjectCreate = backend["ProjectCreate"]
        project_slug = args.project_slug or f"{topic.slug}-live-project"
        project_title = args.project_title or f"{topic.title} Live Smoke Project"
        current_stage = "create_project_from_topic"
        project = backend["create_project_from_topic"](
            topic.slug,
            ProjectCreate(
                slug=project_slug,
                title=project_title,
                owner=args.owner,
                preferred_tone_profile_id=None,
            ),
        )
        current_stage = "generate_outline"
        outline = backend["generate_outline"](project.slug)
        current_stage = "generate_draft"
        draft = backend["generate_draft"](project.slug)
        current_stage = "generate_assets"
        assets = backend["generate_assets"](project.slug)
        if args.assets_only:
            result = _build_partial_pipeline_payload(
                get_ai_config_summary=get_ai_config_summary,
                topic=topic,
                project=project,
                outline=outline,
                draft=draft,
                assets=assets,
            )
            _safe_print_json(result)
            return 0
        current_stage = "build_publish_package"
        publish_package = backend["build_publish_package"](project.slug)
        current_stage = "get_project_detail"
        detail = backend["get_project_detail"](project.slug)
    except Exception as exc:
        result = _build_partial_pipeline_payload(
            get_ai_config_summary=get_ai_config_summary,
            topic=topic,
            project=project,
            outline=outline,
            draft=draft,
            assets=assets,
            publish_package=publish_package,
            detail=detail,
            stage_error={
                "stage": current_stage,
                "error": _build_error_payload(exc),
            },
        )
        _safe_print_json(result)
        return 1

    result = _build_partial_pipeline_payload(
        get_ai_config_summary=get_ai_config_summary,
        topic=topic,
        project=project,
        outline=outline,
        draft=draft,
        assets=assets,
        publish_package=publish_package,
        detail=detail,
    )
    _safe_print_json(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
