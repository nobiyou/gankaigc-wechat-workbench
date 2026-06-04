from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "apps" / "backend"
AI_OVERRIDE_ENV_FIELDS: tuple[tuple[str, str], ...] = (
    ("openai_api_key", "OPENAI_API_KEY"),
    ("openai_base_url", "OPENAI_BASE_URL"),
    ("openai_model", "OPENAI_MODEL"),
    ("openai_reasoning_effort", "OPENAI_REASONING_EFFORT"),
    ("openai_request_timeout_seconds", "OPENAI_REQUEST_TIMEOUT_SECONDS"),
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a minimal live AI smoke for the current workbench config.")
    parser.add_argument("--trend-slug", default="office-burnout-recovery", help="Trend slug used for the smoke run.")
    parser.add_argument("--owner", default="live-smoke", help="Project owner label for the smoke run.")
    parser.add_argument("--project-slug", default=None, help="Optional fixed project slug.")
    parser.add_argument("--project-title", default=None, help="Optional fixed project title.")
    parser.add_argument("--skip-reset", action="store_true", help="Reuse the current store instead of resetting it first.")
    parser.add_argument("--check-only", action="store_true", help="Only run the AI config check without creating content.")
    parser.add_argument(
        "--probe-text-routes",
        action="store_true",
        help="Probe responses.create / responses.parse / chat.completions directly before running the full smoke chain.",
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
    return parser


def _normalize_ai_override_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return str(value)
    text = str(value).strip()
    return text or None


def _collect_ai_override_env(args: argparse.Namespace) -> dict[str, str]:
    overrides: dict[str, str] = {}
    if getattr(args, "clear_openai_base_url", False):
        overrides["OPENAI_BASE_URL"] = ""
    for field_name, env_name in AI_OVERRIDE_ENV_FIELDS:
        normalized = _normalize_ai_override_value(getattr(args, field_name, None))
        if normalized is not None:
            overrides[env_name] = normalized
    return overrides


def _apply_ai_overrides(args: argparse.Namespace) -> dict[str, str]:
    overrides = _collect_ai_override_env(args)
    for env_name, value in overrides.items():
        os.environ[env_name] = value
    return overrides


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
    )

    return {
        "settings": settings,
        "ProjectCreate": ProjectCreate,
        "OpenAIWorkbenchGenerator": OpenAIWorkbenchGenerator,
        "TopicGenerationResult": TopicGenerationResult,
        "get_ai_config_summary": get_ai_config_summary,
        "run_ai_config_check": run_ai_config_check,
        "initialize_store": initialize_store,
        "generate_topic_from_trend": generate_topic_from_trend,
        "create_project_from_topic": create_project_from_topic,
        "generate_outline": generate_outline,
        "generate_draft": generate_draft,
        "generate_assets": generate_assets,
        "build_publish_package": build_publish_package,
        "get_project_detail": get_project_detail,
    }


def _build_error_payload(exc: Exception) -> dict[str, object]:
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
        "body": getattr(exc, "body", None),
    }


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


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _apply_ai_overrides(args)
    backend = _load_backend_bindings()
    settings = backend["settings"]
    get_ai_config_summary = backend["get_ai_config_summary"]
    run_ai_config_check = backend["run_ai_config_check"]

    if args.probe_text_routes:
        payload, any_ok = _run_text_route_probe(backend)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if any_ok else 1

    if args.check_only:
        check_result = run_ai_config_check()
        result = {
            "ai_config": get_ai_config_summary().model_dump(),
            "check": check_result.model_dump(),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if check_result.ok else 1

    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    if not args.skip_reset:
        backend["initialize_store"](reset=True)

    topic = backend["generate_topic_from_trend"](args.trend_slug)
    ProjectCreate = backend["ProjectCreate"]
    project_slug = args.project_slug or f"{topic.slug}-live-project"
    project_title = args.project_title or f"{topic.title} Live Smoke Project"
    project = backend["create_project_from_topic"](
        topic.slug,
        ProjectCreate(
            slug=project_slug,
            title=project_title,
            owner=args.owner,
            preferred_tone_profile_id=None,
        ),
    )
    outline = backend["generate_outline"](project.slug)
    draft = backend["generate_draft"](project.slug)
    assets = backend["generate_assets"](project.slug)
    publish_package = backend["build_publish_package"](project.slug)
    detail = backend["get_project_detail"](project.slug)

    result = {
        "ai_config": get_ai_config_summary().model_dump(),
        "topic": topic.model_dump(),
        "project": project.model_dump(),
        "outline": outline.model_dump(),
        "draft": {
            "project_slug": draft.project_slug,
            "version": draft.version,
            "title": draft.title,
            "word_count": draft.word_count,
        },
        "assets": {
            "project_slug": assets.project_slug,
            "version": assets.version,
            "title_options": assets.title_options,
            "cover_copy": assets.cover_copy,
            "cover_image_url": assets.cover_image_url,
        },
        "publish_package": {
            "project_slug": publish_package.project_slug,
            "version": publish_package.version,
            "abstract": publish_package.abstract,
            "tags": publish_package.tags,
            "manifest_url": publish_package.manifest_url,
            "markdown_url": publish_package.markdown_url,
        },
        "detail": detail.model_dump(),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
