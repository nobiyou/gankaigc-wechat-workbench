from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import uuid
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "apps" / "backend"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "tmp" / "article-runs"
RUNTIME_DB_TEMP_DIRNAME = "gankaigc-originality-case-db"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
AI_OVERRIDE_ENV_FIELDS: tuple[tuple[str, str], ...] = (
    ("openai_api_key", "OPENAI_API_KEY"),
    ("openai_base_url", "OPENAI_BASE_URL"),
    ("openai_model", "OPENAI_MODEL"),
    ("openai_reasoning_effort", "OPENAI_REASONING_EFFORT"),
    ("openai_request_timeout_seconds", "OPENAI_REQUEST_TIMEOUT_SECONDS"),
    ("openai_image_api_key", "OPENAI_IMAGE_API_KEY"),
    ("openai_image_base_url", "OPENAI_IMAGE_BASE_URL"),
    ("openai_image_model", "OPENAI_IMAGE_MODEL"),
    ("openai_image_request_timeout_seconds", "OPENAI_IMAGE_REQUEST_TIMEOUT_SECONDS"),
)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _read_clipboard_text() -> str:
    attempts: list[list[str]]
    if sys.platform == "win32":
        attempts = [["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]]
    elif sys.platform == "darwin":
        attempts = [["pbpaste"]]
    else:
        attempts = [
            ["wl-paste", "-n"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"],
        ]

    last_error: Exception | None = None
    for command in attempts:
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
        except Exception as exc:  # pragma: no cover - platform/tool availability dependent
            last_error = exc
            continue
        text = completed.stdout
        if text.strip():
            return text

    raise RuntimeError(
        "Could not read clipboard text"
        if last_error is None
        else f"Could not read clipboard text: {last_error}"
    )


def _normalize_ai_override_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float):
        return str(value)
    text = str(value).strip()
    return text or None


def _normalize_cli_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_preferred_tone_profile_id(
    *,
    args: argparse.Namespace,
    backend: Mapping[str, Any] | None = None,
) -> int | None:
    explicit_id = getattr(args, "tone_profile_id", None)
    if explicit_id is not None:
        return int(explicit_id)

    profile_name = _normalize_cli_text(getattr(args, "tone_profile_name", None))
    if not profile_name:
        return None

    if backend is None:
        if str(BACKEND_ROOT) not in sys.path:
            sys.path.insert(0, str(BACKEND_ROOT))

        from app.services.workbench import list_tone_profiles

        backend = {
            "list_tone_profiles": list_tone_profiles,
        }

    profiles = backend["list_tone_profiles"]()
    for profile in profiles:
        if getattr(profile, "name", None) == profile_name:
            return int(profile.id)

    raise RuntimeError(f"Tone profile not found: {profile_name}")


def _describe_selected_tone_profile(
    *,
    profile_id: int | None,
    backend: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if profile_id is None:
        return None

    if backend is None:
        if str(BACKEND_ROOT) not in sys.path:
            sys.path.insert(0, str(BACKEND_ROOT))

        from app.services.workbench import list_tone_profiles

        backend = {
            "list_tone_profiles": list_tone_profiles,
        }

    profiles = backend["list_tone_profiles"]()
    for profile in profiles:
        if int(getattr(profile, "id")) == int(profile_id):
            preset_key = getattr(profile, "preset_key", None)
            return {
                "id": int(profile.id),
                "name": getattr(profile, "name", None),
                "preset_key": preset_key,
                "is_builtin": bool(preset_key),
            }
    return {"id": int(profile_id)}


def _collect_ai_override_env(args: argparse.Namespace) -> tuple[dict[str, str], set[str]]:
    overrides: dict[str, str] = {}
    cleared_env_names: set[str] = set()
    if getattr(args, "clear_openai_base_url", False):
        overrides["OPENAI_BASE_URL"] = DEFAULT_OPENAI_BASE_URL
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


def _build_ai_route_probe_error_payload(exc: Exception) -> dict[str, object]:
    return {
        "type": exc.__class__.__name__,
        "message": str(exc),
        "body": getattr(exc, "body", None),
    }


def _probe_ai_text_routes(backend: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if backend is None:
        if str(BACKEND_ROOT) not in sys.path:
            sys.path.insert(0, str(BACKEND_ROOT))

        from app.core.settings import settings
        from app.services.ai_generator import OpenAIWorkbenchGenerator, TopicGenerationResult, get_ai_config_summary

        backend = {
            "settings": settings,
            "OpenAIWorkbenchGenerator": OpenAIWorkbenchGenerator,
            "TopicGenerationResult": TopicGenerationResult,
            "get_ai_config_summary": get_ai_config_summary,
        }

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
        routes["responses_create_text"] = {"ok": False, "error": _build_ai_route_probe_error_payload(exc)}

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
        routes["responses_create_json_text"] = {"ok": False, "error": _build_ai_route_probe_error_payload(exc)}

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
        routes["responses_parse_topic"] = {"ok": False, "error": _build_ai_route_probe_error_payload(exc)}

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
        routes["chat_completions_json"] = {"ok": False, "error": _build_ai_route_probe_error_payload(exc)}

    return {
        "ai_config": get_ai_config_summary().model_dump(),
        "routes": routes,
    }


def _normalize_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    for item in value:
        candidate = str(item).strip()
        if candidate and candidate not in normalized:
            normalized.append(candidate)
    return normalized


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_reuse_scene_title(value: object, *, max_length: int = 40) -> str:
    text = _normalize_whitespace(str(value or "").strip())
    if not text:
        return ""
    if 6 <= len(text) <= max_length:
        return text

    for candidate in re.split(r"[。！？!?；;]", text):
        normalized = _normalize_whitespace(candidate)
        if 6 <= len(normalized) <= max_length:
            return normalized

    compact = text[:max_length].rstrip("，,；;。.!?？、 ")
    return compact if len(compact) >= 6 else ""


def _strip_markdown(markdown: str) -> str:
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"[*`>_-]+", " ", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _compact_text(markdown: str) -> str:
    return re.sub(r"\s+", "", _strip_markdown(markdown))


def _to_detector_text(markdown: str) -> str:
    return _strip_markdown(markdown)


def _infer_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        candidate = line.strip().lstrip("#").strip()
        if candidate:
            return candidate[:48]
    compact = _compact_text(markdown)
    return compact[:48] or fallback


def _build_overlap_report(
    *,
    source_title: str,
    source_markdown: str,
    draft_title: str,
    draft_markdown: str,
) -> dict[str, Any]:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.services.content_diagnosis import build_reference_originality_report

    return build_reference_originality_report(
        source_title=source_title,
        source_markdown=source_markdown,
        draft_title=draft_title,
        draft_markdown=draft_markdown,
    ).to_overlap_report_dict()


def _build_output_dir(root: Path, label: str | None) -> Path:
    run_id = label or uuid.uuid4().hex[:8]
    output_dir = root / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _build_runtime_db_path(output_dir: Path) -> Path:
    runtime_root = Path(tempfile.gettempdir()) / RUNTIME_DB_TEMP_DIRNAME
    runtime_root.mkdir(parents=True, exist_ok=True)
    return runtime_root / f"{output_dir.name}.db"


def _sync_runtime_db_to_bundle(*, runtime_db_path: Path, bundle_db_path: Path) -> None:
    if not runtime_db_path.exists():
        return
    bundle_db_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(runtime_db_path, bundle_db_path)


def _ai_flavor_summary_to_dict(summary: Any) -> dict[str, Any]:
    return {
        "score": int(getattr(summary, "score", 0)),
        "level": str(getattr(summary, "level", "")),
        "hits": list(getattr(summary, "hits", [])),
        "suggestions": list(getattr(summary, "suggestions", [])),
    }


def _build_structural_residue(markdown: str) -> dict[str, int]:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.services.content_diagnosis import build_structural_residue_report

    return build_structural_residue_report(markdown)


def _build_paragraph_sentence_stats(markdown: str) -> dict[str, Any]:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.services.workbench import _extract_non_heading_paragraphs, _split_block_sentences

    paragraphs = _extract_non_heading_paragraphs(markdown)
    sentence_counts = [len(_split_block_sentences(paragraph)) for paragraph in paragraphs]
    return {
        "paragraph_count": len(paragraphs),
        "sentence_counts": sentence_counts,
        "max_sentences": max(sentence_counts) if sentence_counts else 0,
        "paragraphs_over_2_sentences": sum(1 for count in sentence_counts if count > 2),
        "paragraphs_over_3_sentences": sum(1 for count in sentence_counts if count > 3),
        "paragraphs_over_4_sentences": sum(1 for count in sentence_counts if count > 4),
    }


def _apply_current_compare_cleanups(*, title: str, draft_markdown: str) -> tuple[str, dict[str, Any]]:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.services.ai_flavor import evaluate_ai_flavor_risk, extract_embedded_banner_paragraphs
    from app.services.workbench import (
        _get_initial_draft_candidate_cleanup_steps,
    )

    original_summary = evaluate_ai_flavor_risk(title=title, body_markdown=draft_markdown)
    current_markdown = draft_markdown
    changed_steps = 0
    step_changes: list[dict[str, Any]] = []
    for step_name, step_fn in _get_initial_draft_candidate_cleanup_steps(source_type="tracked_article"):
        next_markdown = step_fn(title=title, body_markdown=current_markdown)
        changed = next_markdown != current_markdown
        if changed:
            changed_steps += 1
        step_changes.append({"name": step_name, "changed": changed})
        current_markdown = next_markdown

    cleaned_summary = evaluate_ai_flavor_risk(title=title, body_markdown=current_markdown)
    cleanup_report = {
        "enabled": True,
        "applied": current_markdown != draft_markdown,
        "steps": step_changes,
        "changed_steps": changed_steps,
        "original_ai_flavor": _ai_flavor_summary_to_dict(original_summary),
        "cleaned_ai_flavor": _ai_flavor_summary_to_dict(cleaned_summary),
        "original_structural_residue": _build_structural_residue(draft_markdown),
        "cleaned_structural_residue": _build_structural_residue(current_markdown),
        "original_paragraph_sentence_stats": _build_paragraph_sentence_stats(draft_markdown),
        "cleaned_paragraph_sentence_stats": _build_paragraph_sentence_stats(current_markdown),
        "original_embedded_banner_count": len(extract_embedded_banner_paragraphs(draft_markdown)),
        "cleaned_embedded_banner_count": len(extract_embedded_banner_paragraphs(current_markdown)),
    }
    return current_markdown, cleanup_report


def _evaluate_compare_pair(
    *,
    source_title: str,
    source_markdown: str,
    draft_title: str,
    draft_markdown: str,
    apply_current_cleanups: bool,
) -> dict[str, Any]:
    compare_cleanup: dict[str, Any] | None = None
    output_draft_markdown = draft_markdown
    if apply_current_cleanups:
        output_draft_markdown, compare_cleanup = _apply_current_compare_cleanups(
            title=draft_title,
            draft_markdown=draft_markdown,
        )

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.services.ai_flavor import evaluate_ai_flavor_risk

    return {
        "draft_title": draft_title,
        "draft_markdown": output_draft_markdown,
        "compare_cleanup": compare_cleanup,
        "structural_residue": _build_structural_residue(output_draft_markdown),
        "overlap_report": _build_overlap_report(
            source_title=source_title,
            source_markdown=source_markdown,
            draft_title=draft_title,
            draft_markdown=output_draft_markdown,
        ),
        "ai_flavor": {
            "source": evaluate_ai_flavor_risk(title=source_title, body_markdown=source_markdown).__dict__,
            "draft": evaluate_ai_flavor_risk(title=draft_title, body_markdown=output_draft_markdown).__dict__,
        },
    }


def _sanitize_label(value: str) -> str:
    compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "-", value).strip("-_")
    return compact or "candidate"


def _resolve_candidate_label(path: Path, provided_label: str | None) -> str:
    if provided_label:
        normalized = str(provided_label).strip()
        if normalized:
            return normalized
    parent_name = path.parent.name.strip()
    if parent_name:
        return parent_name
    return path.stem


_RANKING_PRIORITY = [
    "cleaned_ai_flavor_score",
    "original_ai_flavor_score",
    "cleaned_structural_residue_score",
    "cleanup_applied_flag",
    "cleanup_changed_steps",
    "char_12gram_jaccard",
    "char_8gram_jaccard",
    "exact_long_sentence_overlap_count",
    "title_same_flag",
    "label_lexicographic",
]


def _as_float(value: object, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return float(default)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return float(default)
        try:
            return float(candidate)
        except ValueError:
            return float(default)
    return float(default)


def _as_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return default
        try:
            return int(float(candidate))
        except ValueError:
            return default
    return default


def _get_candidate_cleanup(candidate: Mapping[str, Any]) -> Mapping[str, Any]:
    cleanup = candidate.get("compare_cleanup")
    return cleanup if isinstance(cleanup, Mapping) else {}


def _candidate_cleaned_ai_flavor_score(candidate: Mapping[str, Any]) -> float:
    ai_flavor = candidate.get("ai_flavor")
    if isinstance(ai_flavor, Mapping):
        draft = ai_flavor.get("draft")
        if isinstance(draft, Mapping):
            return _as_float(draft.get("score"), default=100.0)
    return 100.0


def _candidate_original_ai_flavor_score(candidate: Mapping[str, Any]) -> float:
    cleanup = _get_candidate_cleanup(candidate)
    original_ai_flavor = cleanup.get("original_ai_flavor")
    if isinstance(original_ai_flavor, Mapping) and "score" in original_ai_flavor:
        return _as_float(original_ai_flavor.get("score"), default=100.0)
    return _candidate_cleaned_ai_flavor_score(candidate)


def _candidate_cleanup_applied_flag(candidate: Mapping[str, Any]) -> int:
    cleanup = _get_candidate_cleanup(candidate)
    return 1 if bool(cleanup.get("applied")) else 0


def _candidate_cleanup_changed_steps(candidate: Mapping[str, Any]) -> int:
    cleanup = _get_candidate_cleanup(candidate)
    steps = cleanup.get("steps")
    if not isinstance(steps, list):
        return 0
    return sum(1 for step in steps if isinstance(step, Mapping) and bool(step.get("changed")))


def _candidate_cleaned_structural_residue_score(candidate: Mapping[str, Any]) -> int:
    cleanup = _get_candidate_cleanup(candidate)
    cleaned_residue = cleanup.get("cleaned_structural_residue")
    if isinstance(cleaned_residue, Mapping):
        if "residue_score" in cleaned_residue:
            return _as_int(cleaned_residue.get("residue_score"), default=999)
        if "paragraph_shell_burden" in cleaned_residue:
            return _as_int(cleaned_residue.get("paragraph_shell_burden"), default=999)
    residue = candidate.get("structural_residue")
    if isinstance(residue, Mapping):
        if "residue_score" in residue:
            return _as_int(residue.get("residue_score"), default=999)
        if "paragraph_shell_burden" in residue:
            return _as_int(residue.get("paragraph_shell_burden"), default=999)
    return 999


def _candidate_rank_tuple(candidate: Mapping[str, Any]) -> tuple[float, float, int, int, int, float, float, int, int, str]:
    overlap = candidate.get("overlap_report")
    overlap_payload = overlap if isinstance(overlap, Mapping) else {}
    label = str(candidate.get("label") or "").strip().casefold()
    return (
        _candidate_cleaned_ai_flavor_score(candidate),
        _candidate_original_ai_flavor_score(candidate),
        _candidate_cleaned_structural_residue_score(candidate),
        _candidate_cleanup_applied_flag(candidate),
        _candidate_cleanup_changed_steps(candidate),
        _as_float(overlap_payload.get("char_12gram_jaccard"), default=1.0),
        _as_float(overlap_payload.get("char_8gram_jaccard"), default=1.0),
        _as_int(overlap_payload.get("exact_long_sentence_overlap_count"), default=0),
        1 if bool(overlap_payload.get("title_same")) else 0,
        label,
    )


def _parse_rank_candidate_specs(values: list[str] | None) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []
    for raw in values or []:
        spec = str(raw).strip()
        if not spec:
            continue
        label: str | None = None
        path_text = spec
        if "::" in spec:
            maybe_label, maybe_path = spec.split("::", 1)
            if maybe_path.strip():
                label = maybe_label.strip() or None
                path_text = maybe_path.strip()
        path = Path(path_text).resolve()
        if path.is_dir():
            path = path / "draft.md"
        if not path.exists():
            raise FileNotFoundError(f"Rank draft file not found: {path}")
        candidates.append(
            {
                "label": _resolve_candidate_label(path, label),
                "draft_file": str(path),
            }
        )
    return candidates


def _build_candidate_artifact_dir(base_dir: Path, index: int, label: str) -> Path:
    artifact_dir = base_dir / f"{index:02d}-{_sanitize_label(label)}"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    return artifact_dir


def _build_external_detector_templates(
    *,
    output_dir: Path,
    source_file: str,
    draft_file: str,
    result_json_path: Path,
) -> dict[str, str]:
    source_template_path = output_dir / "external-detector-source-template.json"
    draft_template_path = output_dir / "external-detector-draft-template.json"
    instructions_path = output_dir / "external-detector-instructions.md"

    source_template = {
        "confidence": None,
        "source_file": source_file,
        "detector_url": "",
        "captured_at": "",
        "notes": "",
        "raw_result": {},
    }
    draft_template = {
        "confidence": None,
        "draft_file": draft_file,
        "detector_url": "",
        "captured_at": "",
        "notes": "",
        "raw_result": {},
    }
    instructions = "\n".join(
        [
            "# External detector attach guide",
            "",
            "1. Paste the source text into the external detector and record the result in",
            f"   `{source_template_path.name}`.",
            "2. Paste the generated draft into the same detector and record the result in",
            f"   `{draft_template_path.name}`.",
            "3. Fill `confidence` with the detector score if only a number is available.",
            "4. Put any screenshots, copied JSON, or notes into `raw_result` or `notes`.",
            "5. Attach both files back into the result bundle with:",
            "",
            "```bash",
            "python scripts/run_originality_case.py \\",
            f"  --attach-result-json \"{result_json_path}\" \\",
            "  --external-detector-name <detector_name> \\",
            f"  --source-detector-json \"{source_template_path}\" \\",
            f"  --draft-detector-json \"{draft_template_path}\"",
            "```",
            "",
            "## Zhuque text detector helper",
            "",
            "If you are using Tencent Zhuque text detection, you can preflight and capture",
            "the detector payload with the helper script in this repository:",
            "",
            "```bash",
            "node scripts/run_zhuque_text_detector.js \\",
            f"  --input-file \"{source_file}\" \\",
            f"  --template-json \"{source_template_path}\" \\",
            f"  --bundle-result-json \"{result_json_path}\" \\",
            "  --bundle-slot source",
            "```",
            "",
            "The first run will confirm the WebSocket handshake and tell you how to capture a",
            "real TencentCaptcha payload. If Zhuque rejects the anonymous handshake, the helper",
            "will also tell you how to capture `aiGenAccessToken` / `fp` from the browser console.",
            "The shortest handoff path is to copy the console line that starts with",
            "`ZHUQUE_COMBINED_PAYLOAD` into a text file, then rerun with:",
            "",
            "```bash",
            "node scripts/run_zhuque_text_detector.js \\",
            f"  --input-file \"{source_file}\" \\",
            f"  --template-json \"{source_template_path}\" \\",
            f"  --bundle-result-json \"{result_json_path}\" \\",
            "  --bundle-slot source \\",
            "  --capture-payload-file <source-capture.txt>",
            "```",
            "",
            "If you prefer separate files, the helper still accepts explicit auth/captcha JSON:",
            "",
            "```bash",
            "node scripts/run_zhuque_text_detector.js \\",
            f"  --input-file \"{source_file}\" \\",
            f"  --template-json \"{source_template_path}\" \\",
            f"  --bundle-result-json \"{result_json_path}\" \\",
            "  --bundle-slot source \\",
            "  --auth-payload-file <source-auth.json> \\",
            "  --captcha-payload-file <source-captcha.json>",
            "```",
            "",
            "Repeat the same command for the draft text by swapping the input file and template:",
            "",
            "```bash",
            "node scripts/run_zhuque_text_detector.js \\",
            f"  --input-file \"{draft_file}\" \\",
            f"  --template-json \"{draft_template_path}\" \\",
            f"  --bundle-result-json \"{result_json_path}\" \\",
            "  --bundle-slot draft \\",
            "  --capture-payload-file <draft-capture.txt>",
            "```",
            "",
            "The same `--auth-payload-file` option works for the draft run too when anonymous",
            "handshake is rejected and you are not using a combined capture line.",
            "",
            "If you only have numeric scores, you can skip the JSON files and use:",
            "",
            "```bash",
            "python scripts/run_originality_case.py \\",
            f"  --attach-result-json \"{result_json_path}\" \\",
            "  --external-detector-name <detector_name> \\",
            "  --source-detector-score <source_score> \\",
            "  --draft-detector-score <draft_score>",
            "```",
            "",
            "If you already copied the visible Zhuque report text into files, you can let",
            "this script parse the report and fill the detector payload automatically:",
            "",
            "```bash",
            "python scripts/run_originality_case.py \\",
            f"  --attach-result-json \"{result_json_path}\" \\",
            "  --external-detector-name zhuque_tencent_text \\",
            "  --source-zhuque-report-file <source-report.txt> \\",
            "  --draft-zhuque-report-file <draft-report.txt>",
            "```",
            "",
            "If you prefer clipboard-only attach with no temp files, copy the visible Zhuque",
            "report text for one side and run attach twice. First for the source report:",
            "",
            "```bash",
            "python scripts/run_originality_case.py \\",
            f"  --attach-result-json \"{result_json_path}\" \\",
            "  --external-detector-name zhuque_tencent_text \\",
            "  --source-zhuque-report-clipboard",
            "```",
            "",
            "Then copy the draft report text and run:",
            "",
            "```bash",
            "python scripts/run_originality_case.py \\",
            f"  --attach-result-json \"{result_json_path}\" \\",
            "  --external-detector-name zhuque_tencent_text \\",
            "  --draft-zhuque-report-clipboard",
            "```",
        ]
    )

    _write_json(source_template_path, source_template)
    _write_json(draft_template_path, draft_template)
    _write_text(instructions_path, instructions)

    return {
        "source_template_json": str(source_template_path),
        "draft_template_json": str(draft_template_path),
        "instructions_md": str(instructions_path),
    }


def _load_reuse_bundle_payload(bundle_json_path: str | None) -> dict[str, Any] | None:
    if not bundle_json_path:
        return None
    payload = _read_json(Path(bundle_json_path).resolve())
    if not isinstance(payload, dict):
        raise ValueError(f"Reuse bundle must be a JSON object: {bundle_json_path}")
    return payload


def _build_tracked_article_seed(
    *,
    article_slug: str,
    article_title: str,
    source_markdown: str,
    source_name: str,
    reuse_bundle_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    seed: dict[str, Any] = {
        "slug": article_slug,
        "source_kind": "manual",
        "source_name": source_name,
        "title": article_title,
        "url": f"local://{article_slug}",
        "author": "",
        "summary": "",
        "body_markdown": source_markdown,
        "body_source": "manual_input",
        "structure_notes": "",
        "created_at": None,
        "tags": [],
    }
    if not isinstance(reuse_bundle_payload, Mapping):
        return seed

    tracked_article = reuse_bundle_payload.get("tracked_article")
    if not isinstance(tracked_article, Mapping):
        return seed

    author = str(tracked_article.get("author") or "").strip()
    summary = str(tracked_article.get("summary") or "").strip()
    structure_notes = str(tracked_article.get("structure_notes") or "").strip()
    tracked_source_name = str(tracked_article.get("source_name") or "").strip()
    tags = _normalize_string_list(tracked_article.get("tags"))

    if author:
        seed["author"] = author
    if summary:
        seed["summary"] = summary
    if structure_notes:
        seed["structure_notes"] = structure_notes
    if tracked_source_name:
        seed["source_name"] = tracked_source_name
    if tags:
        seed["tags"] = tags
    return seed


def _should_skip_tracked_article_enrichment(
    *,
    args: argparse.Namespace,
    reuse_bundle_payload: Mapping[str, Any] | None,
) -> bool:
    if getattr(args, "skip_enrich", False):
        return True
    if not isinstance(reuse_bundle_payload, Mapping):
        return False
    tracked_article = reuse_bundle_payload.get("tracked_article")
    return isinstance(tracked_article, Mapping)


def _build_tracked_article_enrichment_warning(*, article_slug: str, exc: Exception) -> dict[str, object]:
    return {
        "type": "tracked_article_metadata_enrichment_failed",
        "article_slug": article_slug,
        "message": str(exc),
        "error_type": exc.__class__.__name__,
    }


def _best_effort_enrich_tracked_article(
    *,
    article_slug: str,
    article_payload: Any,
    enrich_tracked_article_metadata: Any,
    should_skip: bool,
    partial: dict[str, Any],
) -> None:
    if should_skip:
        partial["tracked_article"] = article_payload.model_dump()
        return

    try:
        enriched = enrich_tracked_article_metadata(article_slug)
    except Exception as exc:
        partial["tracked_article"] = article_payload.model_dump()
        partial.setdefault("warnings", []).append(
            _build_tracked_article_enrichment_warning(article_slug=article_slug, exc=exc)
        )
        return

    partial["tracked_article"] = enriched.model_dump()


def _extract_reuse_strategy_card(
    reuse_bundle_payload: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    if not isinstance(reuse_bundle_payload, Mapping):
        return None
    for key in ("adopted_strategy", "strategy"):
        candidate = reuse_bundle_payload.get(key)
        if not isinstance(candidate, Mapping):
            continue
        strategy_card = candidate.get("strategy_card")
        if isinstance(strategy_card, Mapping):
            return strategy_card
    return None


def _trim_reuse_angle_fragment(value: object, *, limit: int = 56) -> str:
    candidate = _normalize_whitespace(str(value or "").strip())
    if not candidate:
        return ""
    if len(candidate) <= limit:
        return candidate
    return candidate[: limit - 1].rstrip("，,；;。.!?？、 ") + "…"


def _build_reuse_angle_from_strategy_card(
    strategy_card: Mapping[str, Any] | None,
    *,
    source_title: str,
    fallback_title: str,
) -> str:
    if not isinstance(strategy_card, Mapping):
        return ""

    reader_situation = _trim_reuse_angle_fragment(strategy_card.get("reader_situation"))
    conflict_frame = _trim_reuse_angle_fragment(strategy_card.get("conflict_frame"))
    benchmark_summary = _trim_reuse_angle_fragment(strategy_card.get("benchmark_summary"), limit=72)

    fragments = [fragment for fragment in (reader_situation, conflict_frame) if fragment]
    if benchmark_summary:
        fragments.append(f"写法上避开{benchmark_summary}")
    if not fragments:
        return ""

    anchor = source_title or fallback_title[:32]
    if anchor:
        return f"围绕《{anchor}》对应的现实处境重建新的具体入口，重点抓住{'；'.join(fragments)}。"
    return f"围绕当前参考文章对应的现实处境重建新的具体入口，重点抓住{'；'.join(fragments)}。"


def _extract_reuse_topic_seed(
    reuse_bundle_payload: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    if not isinstance(reuse_bundle_payload, Mapping):
        return None
    topic = reuse_bundle_payload.get("topic")
    if not isinstance(topic, Mapping):
        topic = None

    title = str(topic.get("title") or "").strip() if isinstance(topic, Mapping) else ""
    angle = str(topic.get("angle") or "").strip() if isinstance(topic, Mapping) else ""
    if not title or not angle:
        fallback_title = _normalize_whitespace(str(reuse_bundle_payload.get("draft_title") or "").strip())
        source_title = _normalize_whitespace(str(reuse_bundle_payload.get("source_title") or "").strip())
        strategy_card = _extract_reuse_strategy_card(reuse_bundle_payload)
        fallback_scene_title = _extract_reuse_scene_title(fallback_title)

        if not title:
            if fallback_scene_title:
                title = fallback_scene_title
            elif source_title:
                title = source_title[:48]

        if not angle:
            strategy_angle = _build_reuse_angle_from_strategy_card(
                strategy_card,
                source_title=source_title,
                fallback_title=fallback_title,
            )
            if strategy_angle:
                angle = strategy_angle
            elif source_title:
                angle = (
                    f"围绕《{source_title}》对应的现实处境重建一个新的具体入口，"
                    + (f"从“{fallback_scene_title}”这个现场片段开口，" if fallback_scene_title else "")
                    + "重点改掉原文标题骨架、推进顺序和结尾动作。"
                )
            elif fallback_title:
                angle = (
                    f"围绕“{(fallback_scene_title or fallback_title[:32])}”所指向的生活处境重建一个新的具体入口，"
                    "重点改掉原文标题骨架、推进顺序和结尾动作。"
                )

    if not title or not angle:
        return None
    return {"title": title, "angle": angle}


def _coerce_detector_score(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        candidate = value.strip()
        if not candidate:
            return None
        try:
            return float(candidate)
        except ValueError:
            return None
    return None


def _extract_detector_score(payload: dict[str, Any]) -> float | None:
    candidate_keys = (
        "confidence",
        "aiGenerated",
        "ai_generated",
        "ai_score",
        "score",
        "ratio",
        "percent",
    )
    for key in candidate_keys:
        score = _coerce_detector_score(payload.get(key))
        if score is not None:
            return score
    return None


def _build_detector_input_meta(detector_text: str) -> dict[str, Any]:
    return {
        "detector_text_chars": len(detector_text),
        "detector_text_sha256": hashlib.sha256(detector_text.encode("utf-8")).hexdigest(),
    }


def _attach_detector_input_meta(
    payload: dict[str, Any] | None,
    *,
    detector_text: str | None,
) -> dict[str, Any] | None:
    if payload is None or detector_text is None:
        return payload

    enriched = dict(payload)
    input_meta = _build_detector_input_meta(detector_text)
    raw_result = enriched.get("raw_result")
    if isinstance(raw_result, Mapping):
        segment_chars = raw_result.get("segment_chars")
        if isinstance(segment_chars, int):
            input_meta["segment_chars_match"] = segment_chars == input_meta["detector_text_chars"]
            input_meta["segment_chars_delta"] = input_meta["detector_text_chars"] - segment_chars
    enriched["input_meta"] = input_meta
    return enriched


def _extract_detector_binding_ok(payload: Mapping[str, Any] | None) -> bool | None:
    if not isinstance(payload, Mapping):
        return None
    input_meta = payload.get("input_meta")
    if not isinstance(input_meta, Mapping):
        return None
    segment_chars_match = input_meta.get("segment_chars_match")
    if isinstance(segment_chars_match, bool):
        return segment_chars_match
    return None


def _build_detector_binding_verdict(
    *,
    source_binding_ok: bool | None,
    draft_binding_ok: bool | None,
) -> str | None:
    if source_binding_ok is True and draft_binding_ok is True:
        return "source_and_draft_bound"
    if source_binding_ok is False and draft_binding_ok is False:
        return "source_and_draft_mismatch"
    if source_binding_ok is False:
        return "source_mismatch"
    if draft_binding_ok is False:
        return "draft_mismatch"
    if source_binding_ok is True:
        return "source_bound_only"
    if draft_binding_ok is True:
        return "draft_bound_only"
    return None


def _infer_zhuque_classification(score: float) -> tuple[str, str]:
    if score < 0.5:
        return ("人工特征", "0-0.5")
    if score < 0.99:
        return ("疑似AI", "0.5-0.99")
    return ("AI特征", "0.99-1")


def _extract_zhuque_verdict(text: str) -> str:
    verdicts = (
        "未发现明显的人工创作特征",
        "存在疑似AI生成特征",
        "存在AI生成特征",
        "人工创作特征明显",
    )
    for verdict in verdicts:
        if verdict in text:
            return verdict
    return ""


def _parse_zhuque_report_text(report_text: str) -> dict[str, Any]:
    normalized = _normalize_whitespace(report_text)
    if "朱雀AI生成检测报告单" not in report_text and "AIGC值" not in report_text:
        raise ValueError("Report text does not look like a Zhuque report")

    segment_match = re.search(
        r"片段1\s+(\d+(?:\.\d+)?%)\s+(\d{2,6})\s+(\d+(?:\.\d+)?)",
        normalized,
    )
    segment_score = float(segment_match.group(3)) if segment_match else None

    score_matches = [
        float(match)
        for match in re.findall(r"AIGC值\s*[:：]?\s*(\d+(?:\.\d+)?)(?!\s*-)", normalized)
    ]
    if segment_score is not None:
        score = segment_score
    elif score_matches:
        score = score_matches[-1]
    else:
        raise ValueError("Could not extract AIGC值 from Zhuque report text")

    classification_band, classification_range = _infer_zhuque_classification(score)
    verdict_text = _extract_zhuque_verdict(report_text)
    detected_at_match = re.search(r"检测时间[:：]\s*([0-9]{4}/[0-9]{1,2}/[0-9]{1,2}\s+[0-9]{2}:[0-9]{2}:[0-9]{2})", normalized)

    raw_result: dict[str, Any] = {
        "verdict_text": verdict_text,
        "report_title": "朱雀AI生成检测报告单",
        "detected_at": detected_at_match.group(1) if detected_at_match else "",
        "classification_band": classification_band,
        "classification_range": classification_range,
        "aigc_value": score,
    }
    if segment_match:
        raw_result["segment_ratio"] = segment_match.group(1)
        raw_result["segment_chars"] = int(segment_match.group(2))
        raw_result["report_excerpt"] = (
            f"片段1 占全文比例 {segment_match.group(1)} "
            f"占字符数 {segment_match.group(2)} "
            f"AIGC值 {segment_match.group(3)}"
        )

    notes = (
        "Parsed from visible Zhuque report text. "
        f"Verdict text: {verdict_text or '未提取到判定语'}。"
        f" Classification band: {classification_band} (AIGC值 {classification_range})."
    )

    return {
        "confidence": score,
        "detector_url": "https://matrix.tencent.com/ai-detect/ai_gen_txt",
        "captured_at": "",
        "notes": notes,
        "raw_result": raw_result,
    }


def _read_detector_payload(
    *,
    json_file: str | None,
    score: float | None,
    zhuque_report_file: str | None = None,
    zhuque_report_clipboard: bool = False,
) -> dict[str, Any] | None:
    payload: dict[str, Any] = {}
    if json_file:
        loaded = _read_json(Path(json_file).resolve())
        if not isinstance(loaded, dict):
            raise ValueError(f"Detector json must be an object: {json_file}")
        payload.update(loaded)
    if zhuque_report_file:
        parsed = _parse_zhuque_report_text(_read_text(Path(zhuque_report_file).resolve()))
        payload.update(parsed)
    if zhuque_report_clipboard:
        parsed = _parse_zhuque_report_text(_read_clipboard_text())
        payload.update(parsed)
    if score is not None:
        payload["confidence"] = score
    return payload or None


def _build_external_detector_report(
    *,
    detector_name: str,
    source_payload: dict[str, Any] | None,
    draft_payload: dict[str, Any] | None,
    source_detector_text: str | None = None,
    draft_detector_text: str | None = None,
) -> dict[str, Any]:
    source_payload = _attach_detector_input_meta(
        source_payload,
        detector_text=source_detector_text,
    )
    draft_payload = _attach_detector_input_meta(
        draft_payload,
        detector_text=draft_detector_text,
    )
    source_score = _extract_detector_score(source_payload) if source_payload is not None else None
    draft_score = _extract_detector_score(draft_payload) if draft_payload is not None else None
    summary: dict[str, Any] = {}
    if source_score is not None:
        summary["source_score"] = source_score
    if draft_score is not None:
        summary["draft_score"] = draft_score
    source_binding_ok = _extract_detector_binding_ok(source_payload)
    if source_binding_ok is not None:
        summary["source_binding_ok"] = source_binding_ok
    draft_binding_ok = _extract_detector_binding_ok(draft_payload)
    if draft_binding_ok is not None:
        summary["draft_binding_ok"] = draft_binding_ok
    binding_verdict = _build_detector_binding_verdict(
        source_binding_ok=source_binding_ok,
        draft_binding_ok=draft_binding_ok,
    )
    if binding_verdict is not None:
        summary["binding_verdict"] = binding_verdict
    if source_score is not None and draft_score is not None:
        delta = round(draft_score - source_score, 6)
        summary["delta"] = delta
        if draft_score < source_score:
            summary["verdict"] = "draft_lower_than_source"
        elif draft_score > source_score:
            summary["verdict"] = "draft_higher_than_source"
        else:
            summary["verdict"] = "draft_equal_source"

    report = {
        "name": detector_name,
        "summary": summary,
    }
    if source_payload is not None:
        report["source"] = source_payload
    if draft_payload is not None:
        report["draft"] = draft_payload
    return report


def _audit_external_detector_report(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = report.get("summary")
    summary_mapping = summary if isinstance(summary, Mapping) else {}
    detector_name = str(report.get("name") or "")

    source_binding_ok = summary_mapping.get("source_binding_ok")
    if not isinstance(source_binding_ok, bool):
        source_binding_ok = _extract_detector_binding_ok(
            report.get("source") if isinstance(report.get("source"), Mapping) else None
        )

    draft_binding_ok = summary_mapping.get("draft_binding_ok")
    if not isinstance(draft_binding_ok, bool):
        draft_binding_ok = _extract_detector_binding_ok(
            report.get("draft") if isinstance(report.get("draft"), Mapping) else None
        )

    binding_verdict = summary_mapping.get("binding_verdict")
    if not isinstance(binding_verdict, str) or not binding_verdict.strip():
        binding_verdict = _build_detector_binding_verdict(
            source_binding_ok=source_binding_ok,
            draft_binding_ok=draft_binding_ok,
        )

    if source_binding_ok is True and draft_binding_ok is True:
        trust_status = "trusted"
    elif source_binding_ok is False or draft_binding_ok is False:
        trust_status = "untrusted"
    else:
        trust_status = "unverified"

    audit: dict[str, Any] = {
        "detector_name": detector_name,
        "source_binding_ok": source_binding_ok,
        "draft_binding_ok": draft_binding_ok,
        "binding_verdict": binding_verdict,
        "trust_status": trust_status,
    }

    for key in ("source_score", "draft_score", "delta", "verdict"):
        value = summary_mapping.get(key)
        if value is not None:
            audit[key] = value
    return audit


def _audit_bundle_draft_consistency(
    bundle_payload: Mapping[str, Any],
    *,
    bundle_dir: Path,
) -> dict[str, Any]:
    draft_payload = bundle_payload.get("draft")
    result_draft_markdown = None
    if isinstance(draft_payload, Mapping):
        candidate = draft_payload.get("body_markdown")
        if isinstance(candidate, str):
            result_draft_markdown = candidate

    draft_artifact_path = None
    artifacts = bundle_payload.get("artifacts")
    if isinstance(artifacts, Mapping):
        candidate = artifacts.get("draft_md") or artifacts.get("draft_copy")
        if candidate:
            resolved = Path(str(candidate)).resolve()
            if resolved.exists():
                draft_artifact_path = resolved
    if draft_artifact_path is None:
        fallback = (bundle_dir / "draft.md").resolve()
        if fallback.exists():
            draft_artifact_path = fallback

    artifact_draft_markdown = None
    if draft_artifact_path is not None:
        artifact_draft_markdown = _read_text(draft_artifact_path)

    if result_draft_markdown is None and artifact_draft_markdown is None:
        return {
            "draft_bundle_consistent": None,
            "draft_bundle_verdict": "bundle_missing_comparable_draft",
            "result_draft_chars": None,
            "artifact_draft_chars": None,
            "draft_artifact_path": str(draft_artifact_path) if draft_artifact_path is not None else None,
        }

    if result_draft_markdown is None:
        return {
            "draft_bundle_consistent": None,
            "draft_bundle_verdict": "result_missing_draft_body",
            "result_draft_chars": None,
            "artifact_draft_chars": len(artifact_draft_markdown or ""),
            "draft_artifact_path": str(draft_artifact_path) if draft_artifact_path is not None else None,
        }

    if artifact_draft_markdown is None:
        return {
            "draft_bundle_consistent": None,
            "draft_bundle_verdict": "artifact_missing_draft_md",
            "result_draft_chars": len(result_draft_markdown),
            "artifact_draft_chars": None,
            "draft_artifact_path": None,
        }

    consistent = result_draft_markdown == artifact_draft_markdown
    return {
        "draft_bundle_consistent": consistent,
        "draft_bundle_verdict": "bundle_and_artifact_match" if consistent else "bundle_and_artifact_mismatch",
        "result_draft_chars": len(result_draft_markdown),
        "artifact_draft_chars": len(artifact_draft_markdown),
        "draft_artifact_path": str(draft_artifact_path),
    }


def _audit_bundle_current_cleanup_preview(
    bundle_payload: Mapping[str, Any],
    *,
    bundle_dir: Path,
) -> dict[str, Any]:
    draft_title = ""
    draft_payload = bundle_payload.get("draft")
    if isinstance(draft_payload, Mapping):
        title_candidate = draft_payload.get("title")
        if isinstance(title_candidate, str):
            draft_title = title_candidate.strip()
    if not draft_title:
        title_candidate = bundle_payload.get("draft_title")
        if isinstance(title_candidate, str):
            draft_title = title_candidate.strip()

    draft_artifact_path = None
    artifacts = bundle_payload.get("artifacts")
    if isinstance(artifacts, Mapping):
        candidate = artifacts.get("draft_md") or artifacts.get("draft_copy")
        if candidate:
            resolved = Path(str(candidate)).resolve()
            if resolved.exists():
                draft_artifact_path = resolved
    if draft_artifact_path is None:
        fallback = (bundle_dir / "draft.md").resolve()
        if fallback.exists():
            draft_artifact_path = fallback

    draft_markdown = None
    draft_source = None
    if draft_artifact_path is not None:
        artifact_markdown = _read_text(draft_artifact_path)
        if artifact_markdown.strip():
            draft_markdown = artifact_markdown
            draft_source = "artifact_draft_md"

    if draft_markdown is None and isinstance(draft_payload, Mapping):
        markdown_candidate = draft_payload.get("body_markdown")
        if isinstance(markdown_candidate, str) and markdown_candidate.strip():
            draft_markdown = markdown_candidate
            draft_source = "result_draft_body"

    if draft_markdown is None:
        return {
            "current_cleanup_available": False,
            "current_cleanup_source": None,
            "current_cleanup_applied": None,
            "current_cleanup_improved": None,
            "current_cleanup_original_score": None,
            "current_cleanup_cleaned_score": None,
            "current_cleanup_changed_steps": [],
        }

    effective_title = draft_title or _infer_title(draft_markdown, "draft")
    _, cleanup_report = _apply_current_compare_cleanups(
        title=effective_title,
        draft_markdown=draft_markdown,
    )
    original_ai_flavor = cleanup_report.get("original_ai_flavor") if isinstance(cleanup_report, Mapping) else None
    cleaned_ai_flavor = cleanup_report.get("cleaned_ai_flavor") if isinstance(cleanup_report, Mapping) else None
    original_score = (
        int(original_ai_flavor.get("score"))
        if isinstance(original_ai_flavor, Mapping) and original_ai_flavor.get("score") is not None
        else None
    )
    cleaned_score = (
        int(cleaned_ai_flavor.get("score"))
        if isinstance(cleaned_ai_flavor, Mapping) and cleaned_ai_flavor.get("score") is not None
        else None
    )
    original_structural_residue = (
        cleanup_report.get("original_structural_residue") if isinstance(cleanup_report, Mapping) else None
    )
    cleaned_structural_residue = (
        cleanup_report.get("cleaned_structural_residue") if isinstance(cleanup_report, Mapping) else None
    )
    original_residue_score = (
        int(original_structural_residue.get("residue_score"))
        if isinstance(original_structural_residue, Mapping) and original_structural_residue.get("residue_score") is not None
        else None
    )
    cleaned_residue_score = (
        int(cleaned_structural_residue.get("residue_score"))
        if isinstance(cleaned_structural_residue, Mapping) and cleaned_structural_residue.get("residue_score") is not None
        else None
    )
    score_delta = (
        original_score - cleaned_score
        if original_score is not None and cleaned_score is not None
        else None
    )
    structural_residue_delta = (
        original_residue_score - cleaned_residue_score
        if original_residue_score is not None and cleaned_residue_score is not None
        else None
    )
    score_improved = cleaned_score is not None and original_score is not None and cleaned_score < original_score
    structural_improved = (
        cleaned_residue_score is not None
        and original_residue_score is not None
        and cleaned_residue_score < original_residue_score
    )
    improvement_axes: list[str] = []
    if score_improved:
        improvement_axes.append("ai_flavor_score")
    if structural_improved:
        improvement_axes.append("structural_residue")
    changed_steps = [
        str(step.get("name"))
        for step in cleanup_report.get("steps", [])
        if isinstance(step, Mapping) and step.get("changed") and step.get("name")
    ]
    return {
        "current_cleanup_available": True,
        "current_cleanup_source": draft_source,
        "current_cleanup_applied": bool(cleanup_report.get("applied")),
        "current_cleanup_improved": bool(improvement_axes),
        "current_cleanup_score_improved": score_improved,
        "current_cleanup_structural_improved": structural_improved,
        "current_cleanup_original_score": original_score,
        "current_cleanup_cleaned_score": cleaned_score,
        "current_cleanup_score_delta": score_delta,
        "current_cleanup_original_residue_score": original_residue_score,
        "current_cleanup_cleaned_residue_score": cleaned_residue_score,
        "current_cleanup_structural_residue_delta": structural_residue_delta,
        "current_cleanup_improvement_axes": improvement_axes,
        "current_cleanup_changed_steps": changed_steps,
    }


def _annotate_cleanup_replay_candidate(audit: dict[str, Any]) -> dict[str, Any]:
    audit["current_cleanup_replay_candidate"] = bool(
        audit.get("trust_status") == "trusted" and audit.get("current_cleanup_improved") is True
    )
    return audit


def _cleanup_replay_priority_key(item: Mapping[str, Any]) -> tuple[float, float, float, float, str]:
    label = str(item.get("label") or "").strip().casefold()
    return (
        _as_float(item.get("current_cleanup_cleaned_score"), default=999.0),
        _as_float(item.get("current_cleanup_cleaned_residue_score"), default=999.0),
        -_as_float(item.get("current_cleanup_score_delta"), default=0.0),
        -_as_float(item.get("current_cleanup_structural_residue_delta"), default=0.0),
        label,
    )


def _annotate_cleanup_replay_priorities(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidate_items = sorted(
        [
            item
            for item in results
            if item.get("current_cleanup_replay_candidate") is True
        ],
        key=_cleanup_replay_priority_key,
    )

    for rank, item in enumerate(candidate_items, start=1):
        item["current_cleanup_priority_rank"] = rank
        item["current_cleanup_priority_key"] = list(_cleanup_replay_priority_key(item))
        item["current_cleanup_priority_reason"] = {
            "cleaned_ai_flavor_score": item.get("current_cleanup_cleaned_score"),
            "cleaned_structural_residue_score": item.get("current_cleanup_cleaned_residue_score"),
            "ai_flavor_score_delta": item.get("current_cleanup_score_delta"),
            "structural_residue_delta": item.get("current_cleanup_structural_residue_delta"),
        }

    return candidate_items


def _build_cleanup_retest_manifest_payload(
    *,
    replay_result_root: Path,
    output_root: Path,
    candidate_items: list[dict[str, Any]],
    replayed: list[dict[str, Any]],
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    replayed_by_label = {
        str(item.get("label") or ""): item
        for item in replayed
        if str(item.get("label") or "").strip()
    }

    manifest_candidates: list[dict[str, Any]] = []
    for item in candidate_items:
        label = str(item.get("label") or "")
        replay_item = replayed_by_label.get(label, {})
        manifest_candidates.append(
            {
                "label": label,
                "priority_rank": item.get("current_cleanup_priority_rank"),
                "priority_reason": item.get("current_cleanup_priority_reason"),
                "source_result_json": item.get("result_json"),
                "replayed_result_json": replay_item.get("output_result_json"),
                "replayed_output_dir": replay_item.get("output_dir"),
                "source_copy": replay_item.get("source_copy"),
                "draft_copy": replay_item.get("draft_copy"),
                "draft_original_copy": replay_item.get("draft_original_copy"),
                "source_detector_text": replay_item.get("source_detector_text"),
                "draft_detector_text": replay_item.get("draft_detector_text"),
                "instructions_md": replay_item.get("instructions_md"),
                "source_template_json": replay_item.get("source_template_json"),
                "draft_template_json": replay_item.get("draft_template_json"),
                "cleaned_ai_flavor_score": replay_item.get("cleaned_ai_flavor_score"),
                "original_ai_flavor_score": replay_item.get("original_ai_flavor_score"),
                "ai_flavor_score_delta": replay_item.get("ai_flavor_score_delta"),
                "cleaned_structural_residue_score": replay_item.get("cleaned_structural_residue_score"),
                "original_structural_residue_score": replay_item.get("original_structural_residue_score"),
                "structural_residue_delta": replay_item.get("structural_residue_delta"),
                "structural_residue_improved": replay_item.get("structural_residue_improved"),
                "next_step": "Run Zhuque against draft_detector_text, then attach the detector report back to replayed_result_json.",
            }
        )

    return {
        "mode": "cleanup_retest_manifest",
        "status": "done",
        "replay_result_root": str(replay_result_root),
        "output_root": str(output_root),
        "summary": {
            "selected_candidates": len(candidate_items),
            "replayed_candidates": len(replayed),
            "error_candidates": len(errors),
            "selected_candidate_labels": [str(item.get("label") or "") for item in candidate_items],
        },
        "candidates": manifest_candidates,
        "errors": errors,
    }


def _render_cleanup_retest_manifest_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Cleanup Retest Manifest",
        "",
        f"- replay_result_root: `{payload.get('replay_result_root')}`",
        f"- output_root: `{payload.get('output_root')}`",
    ]

    summary = payload.get("summary")
    if isinstance(summary, Mapping):
        lines.extend(
            [
                f"- selected_candidates: `{summary.get('selected_candidates')}`",
                f"- replayed_candidates: `{summary.get('replayed_candidates')}`",
                f"- error_candidates: `{summary.get('error_candidates')}`",
            ]
        )

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        lines.extend(["", "No replay candidates were exported."])
        return "\n".join(lines) + "\n"

    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        label = str(candidate.get("label") or "")
        lines.extend(
            [
                "",
                f"## {label}",
                "",
                f"- priority_rank: `{candidate.get('priority_rank')}`",
                f"- cleaned_ai_flavor_score: `{candidate.get('cleaned_ai_flavor_score')}`",
                f"- ai_flavor_score_delta: `{candidate.get('ai_flavor_score_delta')}`",
                f"- cleaned_structural_residue_score: `{candidate.get('cleaned_structural_residue_score')}`",
                f"- structural_residue_delta: `{candidate.get('structural_residue_delta')}`",
                f"- replayed_result_json: `{candidate.get('replayed_result_json')}`",
                f"- draft_detector_text: `{candidate.get('draft_detector_text')}`",
                f"- instructions_md: `{candidate.get('instructions_md')}`",
                f"- next_step: {candidate.get('next_step')}",
            ]
        )

    return "\n".join(lines) + "\n"


def _audit_external_detector_result_root(root_path: Path) -> dict[str, Any]:
    resolved_root = root_path.resolve()
    results: list[dict[str, Any]] = []
    total_result_files = 0

    for result_path in sorted(resolved_root.rglob("result.json")):
        total_result_files += 1
        try:
            payload = _read_json(result_path)
        except Exception as exc:
            results.append(
                {
                    "label": result_path.parent.name,
                    "result_json": str(result_path),
                    "trust_status": "unverified",
                    "error": {
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                    },
                }
            )
            continue

        if not isinstance(payload, Mapping):
            continue

        report = payload.get("external_detector")
        if not isinstance(report, Mapping):
            continue

        audit = _audit_external_detector_report(report)
        audit.update(_audit_bundle_draft_consistency(payload, bundle_dir=result_path.parent))
        audit.update(_audit_bundle_current_cleanup_preview(payload, bundle_dir=result_path.parent))
        _annotate_cleanup_replay_candidate(audit)
        audit["label"] = result_path.parent.name
        audit["result_json"] = str(result_path)
        results.append(audit)

    status_counts = {
        "trusted": 0,
        "untrusted": 0,
        "unverified": 0,
    }
    consistency_counts = {
        "consistent": 0,
        "mismatch": 0,
        "unknown": 0,
    }
    cleanup_preview_counts = {
        "improved": 0,
        "unchanged": 0,
        "unavailable": 0,
        "score_improved": 0,
        "structural_improved": 0,
        "score_delta_total": 0,
        "structural_delta_total": 0,
        "trusted_replay_candidates": 0,
    }
    for item in results:
        trust_status = item.get("trust_status")
        if trust_status in status_counts:
            status_counts[trust_status] += 1
        draft_bundle_consistent = item.get("draft_bundle_consistent")
        if draft_bundle_consistent is True:
            consistency_counts["consistent"] += 1
        elif draft_bundle_consistent is False:
            consistency_counts["mismatch"] += 1
        else:
            consistency_counts["unknown"] += 1
        current_cleanup_improved = item.get("current_cleanup_improved")
        if current_cleanup_improved is True:
            cleanup_preview_counts["improved"] += 1
        elif current_cleanup_improved is False:
            cleanup_preview_counts["unchanged"] += 1
        else:
            cleanup_preview_counts["unavailable"] += 1
        if item.get("current_cleanup_score_improved") is True:
            cleanup_preview_counts["score_improved"] += 1
        if item.get("current_cleanup_structural_improved") is True:
            cleanup_preview_counts["structural_improved"] += 1
        cleanup_preview_counts["score_delta_total"] += _as_int(item.get("current_cleanup_score_delta"), default=0)
        cleanup_preview_counts["structural_delta_total"] += _as_int(
            item.get("current_cleanup_structural_residue_delta"),
            default=0,
        )
        if item.get("current_cleanup_replay_candidate") is True:
            cleanup_preview_counts["trusted_replay_candidates"] += 1

    priority_candidates = _annotate_cleanup_replay_priorities(results)
    results.sort(key=lambda item: (str(item.get("label") or ""), str(item.get("result_json") or "")))
    return {
        "root": str(resolved_root),
        "summary": {
            "total_result_files": total_result_files,
            "audited_reports": len(results),
            "trusted_reports": status_counts["trusted"],
            "untrusted_reports": status_counts["untrusted"],
            "unverified_reports": status_counts["unverified"],
            "consistent_draft_bundles": consistency_counts["consistent"],
            "drifted_draft_bundles": consistency_counts["mismatch"],
            "unknown_draft_bundles": consistency_counts["unknown"],
            "cleanup_preview_improved_bundles": cleanup_preview_counts["improved"],
            "cleanup_preview_unchanged_bundles": cleanup_preview_counts["unchanged"],
            "cleanup_preview_unavailable_bundles": cleanup_preview_counts["unavailable"],
            "cleanup_preview_score_improved_bundles": cleanup_preview_counts["score_improved"],
            "cleanup_preview_structural_improved_bundles": cleanup_preview_counts["structural_improved"],
            "cleanup_preview_score_delta_total": cleanup_preview_counts["score_delta_total"],
            "cleanup_preview_structural_residue_delta_total": cleanup_preview_counts["structural_delta_total"],
            "trusted_cleanup_replay_candidates": cleanup_preview_counts["trusted_replay_candidates"],
            "trusted_cleanup_replay_top_labels": [str(item.get("label") or "") for item in priority_candidates[:3]],
            "trusted_cleanup_replay_top_candidates": [
                {
                    "label": str(item.get("label") or ""),
                    "priority_rank": item.get("current_cleanup_priority_rank"),
                    "cleaned_ai_flavor_score": item.get("current_cleanup_cleaned_score"),
                    "cleaned_structural_residue_score": item.get("current_cleanup_cleaned_residue_score"),
                    "ai_flavor_score_delta": item.get("current_cleanup_score_delta"),
                    "structural_residue_delta": item.get("current_cleanup_structural_residue_delta"),
                }
                for item in priority_candidates[:3]
            ],
        },
        "results": results,
    }


def _maybe_build_external_detector_report(
    args: argparse.Namespace,
    *,
    existing_report: Mapping[str, Any] | None = None,
    allow_partial: bool = False,
    source_detector_text: str | None = None,
    draft_detector_text: str | None = None,
) -> dict[str, Any] | None:
    detector_name = (args.external_detector_name or "").strip()
    if not detector_name:
        return None

    source_input_present = any(
        (
            args.source_detector_json,
            args.source_detector_score is not None,
            args.source_zhuque_report_file,
            getattr(args, "source_zhuque_report_clipboard", False),
        )
    )
    draft_input_present = any(
        (
            args.draft_detector_json,
            args.draft_detector_score is not None,
            args.draft_zhuque_report_file,
            getattr(args, "draft_zhuque_report_clipboard", False),
        )
    )

    source_payload = (
        _read_detector_payload(
            json_file=args.source_detector_json,
            score=args.source_detector_score,
            zhuque_report_file=args.source_zhuque_report_file,
            zhuque_report_clipboard=getattr(args, "source_zhuque_report_clipboard", False),
        )
        if source_input_present
        else None
    )
    draft_payload = (
        _read_detector_payload(
            json_file=args.draft_detector_json,
            score=args.draft_detector_score,
            zhuque_report_file=args.draft_zhuque_report_file,
            zhuque_report_clipboard=getattr(args, "draft_zhuque_report_clipboard", False),
        )
        if draft_input_present
        else None
    )

    existing_detector_report = (
        existing_report
        if isinstance(existing_report, Mapping) and str(existing_report.get("name") or "") == detector_name
        else None
    )
    if allow_partial and existing_detector_report is not None:
        if source_payload is None and isinstance(existing_detector_report.get("source"), Mapping):
            source_payload = dict(existing_detector_report["source"])
        if draft_payload is None and isinstance(existing_detector_report.get("draft"), Mapping):
            draft_payload = dict(existing_detector_report["draft"])

    if not allow_partial and (source_payload is None or draft_payload is None):
        raise ValueError(
            "When --external-detector-name is provided, both source and draft detector inputs must be set."
        )
    if allow_partial and source_payload is None and draft_payload is None:
        raise ValueError(
            "Attach mode requires at least one source or draft detector input, or an existing matching detector report."
        )
    return _build_external_detector_report(
        detector_name=detector_name,
        source_payload=source_payload,
        draft_payload=draft_payload,
        source_detector_text=source_detector_text,
        draft_detector_text=draft_detector_text,
    )


def _run_attach_detector_mode(args: argparse.Namespace) -> int:
    result_path = Path(args.attach_result_json).resolve()
    if not result_path.exists():
        raise FileNotFoundError(f"Result bundle not found: {result_path}")
    payload = _read_json(result_path)
    if not isinstance(payload, dict):
        raise ValueError(f"Result bundle must be a JSON object: {result_path}")

    artifacts = payload.get("artifacts")
    source_detector_text = None
    draft_detector_text = None
    if isinstance(artifacts, Mapping):
        source_detector_path = artifacts.get("source_detector_text")
        if source_detector_path:
            candidate_path = Path(str(source_detector_path)).resolve()
            if candidate_path.exists():
                source_detector_text = _read_text(candidate_path)
        draft_detector_path = artifacts.get("draft_detector_text")
        if draft_detector_path:
            candidate_path = Path(str(draft_detector_path)).resolve()
            if candidate_path.exists():
                draft_detector_text = _read_text(candidate_path)

    detector_report = _maybe_build_external_detector_report(
        args,
        existing_report=payload.get("external_detector") if isinstance(payload.get("external_detector"), Mapping) else None,
        allow_partial=True,
        source_detector_text=source_detector_text,
        draft_detector_text=draft_detector_text,
    )
    if detector_report is None:
        raise ValueError("Attach mode requires --external-detector-name and detector inputs.")

    payload["external_detector"] = detector_report
    _write_json(result_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_audit_detector_mode(args: argparse.Namespace) -> int:
    if args.audit_result_json:
        result_path = Path(args.audit_result_json).resolve()
        payload = _read_json(result_path)
        if not isinstance(payload, Mapping):
            raise ValueError(f"Result bundle must be a JSON object: {result_path}")
        report = payload.get("external_detector")
        if not isinstance(report, Mapping):
            raise ValueError(f"Result bundle has no external_detector report: {result_path}")
        audit = _audit_external_detector_report(report)
        audit.update(_audit_bundle_draft_consistency(payload, bundle_dir=result_path.parent))
        audit.update(_audit_bundle_current_cleanup_preview(payload, bundle_dir=result_path.parent))
        _annotate_cleanup_replay_candidate(audit)
        audit["label"] = result_path.parent.name
        audit["result_json"] = str(result_path)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 0

    if args.audit_result_root:
        root_path = Path(args.audit_result_root).resolve()
        if not root_path.exists():
            raise FileNotFoundError(f"Audit root not found: {root_path}")
        audit = _audit_external_detector_result_root(root_path)
        print(json.dumps(audit, ensure_ascii=False, indent=2))
        return 0

    raise ValueError("Audit mode requires --audit-result-json or --audit-result-root.")


def _resolve_bundle_artifact_path(
    bundle_payload: Mapping[str, Any],
    *,
    bundle_dir: Path,
    artifact_keys: tuple[str, ...],
    fallback_name: str,
) -> Path:
    artifacts = bundle_payload.get("artifacts")
    if isinstance(artifacts, Mapping):
        for key in artifact_keys:
            candidate = artifacts.get(key)
            if candidate:
                candidate_path = Path(str(candidate)).resolve()
                if candidate_path.exists():
                    return candidate_path

    fallback_path = (bundle_dir / fallback_name).resolve()
    if fallback_path.exists():
        return fallback_path
    raise FileNotFoundError(
        f"Could not resolve bundle artifact {artifact_keys!r} or fallback {fallback_name} under {bundle_dir}"
    )


def _build_replay_result_bundle(
    *,
    result_path: Path,
    output_root: Path,
    label: str | None,
    probe_ai_routes: bool,
) -> dict[str, Any]:
    if not result_path.exists():
        raise FileNotFoundError(f"Replay source bundle not found: {result_path}")
    payload = _read_json(result_path)
    if not isinstance(payload, Mapping):
        raise ValueError(f"Replay source bundle must be a JSON object: {result_path}")

    bundle_dir = result_path.parent
    source_path = _resolve_bundle_artifact_path(
        payload,
        bundle_dir=bundle_dir,
        artifact_keys=("source_md", "source_copy"),
        fallback_name="source.md",
    )
    draft_path = _resolve_bundle_artifact_path(
        payload,
        bundle_dir=bundle_dir,
        artifact_keys=("draft_md", "draft_copy"),
        fallback_name="draft.md",
    )

    source_markdown = _read_text(source_path)
    draft_markdown = _read_text(draft_path)
    source_title = str(payload.get("source_title") or _infer_title(source_markdown, "source"))

    draft_title = str(payload.get("draft_title") or "")
    draft_payload = payload.get("draft")
    if (not draft_title.strip()) and isinstance(draft_payload, Mapping):
        draft_title = str(draft_payload.get("title") or "")
    draft_title = draft_title.strip() or _infer_title(draft_markdown, "draft")

    output_label = label or f"{bundle_dir.name}-current-cleanup"
    output_dir = _build_output_dir(output_root.resolve(), output_label)
    evaluation = _evaluate_compare_pair(
        source_title=source_title,
        source_markdown=source_markdown,
        draft_title=draft_title,
        draft_markdown=draft_markdown,
        apply_current_cleanups=True,
    )
    compare_cleanup = evaluation["compare_cleanup"]
    output_draft_markdown = evaluation["draft_markdown"]
    source_detector_text = _to_detector_text(source_markdown)
    draft_detector_text = _to_detector_text(output_draft_markdown)

    result = {
        "mode": "replay_result_cleanup",
        "status": "done",
        "replayed_from_result_json": str(result_path),
        "source_file": str(source_path),
        "draft_file": str(draft_path),
        "source_title": source_title,
        "draft_title": draft_title,
        "overlap_report": evaluation["overlap_report"],
        "ai_flavor": evaluation["ai_flavor"],
        "artifacts": {
            "output_dir": str(output_dir),
            "source_copy": str(output_dir / "source.md"),
            "draft_copy": str(output_dir / "draft.md"),
            "source_detector_text": str(output_dir / "source.txt"),
            "draft_detector_text": str(output_dir / "draft.txt"),
            "result_json": str(output_dir / "result.json"),
        },
    }
    if probe_ai_routes:
        result["ai_text_routes_probe"] = _probe_ai_text_routes()
    result["artifacts"]["external_detector_templates"] = _build_external_detector_templates(
        output_dir=output_dir,
        source_file=str(output_dir / "source.txt"),
        draft_file=str(output_dir / "draft.txt"),
        result_json_path=output_dir / "result.json",
    )
    if compare_cleanup is not None:
        result["compare_cleanup"] = compare_cleanup
        result["artifacts"]["draft_original_copy"] = str(output_dir / "draft.original.md")
    _write_text(output_dir / "source.md", source_markdown)
    _write_text(output_dir / "draft.md", output_draft_markdown)
    if compare_cleanup is not None:
        _write_text(output_dir / "draft.original.md", draft_markdown)
    _write_text(output_dir / "source.txt", source_detector_text)
    _write_text(output_dir / "draft.txt", draft_detector_text)
    _write_json(output_dir / "result.json", result)
    return result


def _run_replay_result_mode(args: argparse.Namespace) -> int:
    result = _build_replay_result_bundle(
        result_path=Path(args.replay_result_json).resolve(),
        output_root=Path(args.output_root).resolve(),
        label=args.label,
        probe_ai_routes=args.probe_ai_routes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_replay_result_root_mode(args: argparse.Namespace) -> int:
    root_path = Path(args.replay_result_root).resolve()
    if not root_path.exists():
        raise FileNotFoundError(f"Replay root not found: {root_path}")

    audit = _audit_external_detector_result_root(root_path)
    results = audit.get("results")
    if not isinstance(results, list):
        results = []
    candidate_items = _annotate_cleanup_replay_priorities(
        [item for item in results if isinstance(item, dict)]
    )

    replayed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    output_root = Path(args.output_root).resolve()
    for item in candidate_items:
        result_json = item.get("result_json")
        if not isinstance(result_json, str) or not result_json.strip():
            errors.append(
                {
                    "label": item.get("label"),
                    "error": {
                        "type": "ValueError",
                        "message": "Candidate audit item is missing result_json",
                    },
                }
            )
            continue
        label = f"{str(item.get('label') or 'bundle')}-current-cleanup"
        try:
            replay_result = _build_replay_result_bundle(
                result_path=Path(result_json).resolve(),
                output_root=output_root,
                label=label,
                probe_ai_routes=args.probe_ai_routes,
            )
        except Exception as exc:
            errors.append(
                {
                    "label": item.get("label"),
                    "result_json": result_json,
                    "error": {
                        "type": exc.__class__.__name__,
                        "message": str(exc),
                    },
                }
            )
            continue

        compare_cleanup = replay_result.get("compare_cleanup")
        replayed.append(
            {
                "label": item.get("label"),
                "priority_rank": item.get("current_cleanup_priority_rank"),
                "priority_key": item.get("current_cleanup_priority_key"),
                "source_result_json": result_json,
                "output_result_json": replay_result["artifacts"]["result_json"],
                "output_dir": replay_result["artifacts"]["output_dir"],
                "source_copy": replay_result["artifacts"].get("source_copy"),
                "draft_copy": replay_result["artifacts"].get("draft_copy"),
                "draft_original_copy": replay_result["artifacts"].get("draft_original_copy"),
                "source_detector_text": replay_result["artifacts"].get("source_detector_text"),
                "draft_detector_text": replay_result["artifacts"].get("draft_detector_text"),
                "instructions_md": (
                    replay_result["artifacts"].get("external_detector_templates", {}).get("instructions_md")
                    if isinstance(replay_result["artifacts"].get("external_detector_templates"), Mapping)
                    else None
                ),
                "source_template_json": (
                    replay_result["artifacts"].get("external_detector_templates", {}).get("source_template_json")
                    if isinstance(replay_result["artifacts"].get("external_detector_templates"), Mapping)
                    else None
                ),
                "draft_template_json": (
                    replay_result["artifacts"].get("external_detector_templates", {}).get("draft_template_json")
                    if isinstance(replay_result["artifacts"].get("external_detector_templates"), Mapping)
                    else None
                ),
                "cleaned_ai_flavor_score": (
                    compare_cleanup.get("cleaned_ai_flavor", {}).get("score")
                    if isinstance(compare_cleanup, Mapping)
                    else None
                ),
                "original_ai_flavor_score": (
                    compare_cleanup.get("original_ai_flavor", {}).get("score")
                    if isinstance(compare_cleanup, Mapping)
                    else None
                ),
                "ai_flavor_score_delta": (
                    compare_cleanup.get("original_ai_flavor", {}).get("score")
                    - compare_cleanup.get("cleaned_ai_flavor", {}).get("score")
                    if isinstance(compare_cleanup, Mapping)
                    and compare_cleanup.get("original_ai_flavor", {}).get("score") is not None
                    and compare_cleanup.get("cleaned_ai_flavor", {}).get("score") is not None
                    else None
                ),
                "original_structural_residue_score": (
                    compare_cleanup.get("original_structural_residue", {}).get("residue_score")
                    if isinstance(compare_cleanup, Mapping)
                    else None
                ),
                "cleaned_structural_residue_score": (
                    compare_cleanup.get("cleaned_structural_residue", {}).get("residue_score")
                    if isinstance(compare_cleanup, Mapping)
                    else None
                ),
                "structural_residue_delta": (
                    compare_cleanup.get("original_structural_residue", {}).get("residue_score")
                    - compare_cleanup.get("cleaned_structural_residue", {}).get("residue_score")
                    if isinstance(compare_cleanup, Mapping)
                    and compare_cleanup.get("original_structural_residue", {}).get("residue_score") is not None
                    and compare_cleanup.get("cleaned_structural_residue", {}).get("residue_score") is not None
                    else None
                ),
                "structural_residue_improved": (
                    isinstance(compare_cleanup, Mapping)
                    and compare_cleanup.get("original_structural_residue", {}).get("residue_score") is not None
                    and compare_cleanup.get("cleaned_structural_residue", {}).get("residue_score") is not None
                    and compare_cleanup.get("cleaned_structural_residue", {}).get("residue_score")
                    < compare_cleanup.get("original_structural_residue", {}).get("residue_score")
                ),
            }
        )

    cleanup_retest_manifest = _build_cleanup_retest_manifest_payload(
        replay_result_root=root_path,
        output_root=output_root,
        candidate_items=candidate_items,
        replayed=replayed,
        errors=errors,
    )
    cleanup_retest_manifest_json = output_root / "cleanup-retest-manifest.json"
    cleanup_retest_manifest_md = output_root / "cleanup-retest-manifest.md"
    _write_json(cleanup_retest_manifest_json, cleanup_retest_manifest)
    _write_text(cleanup_retest_manifest_md, _render_cleanup_retest_manifest_markdown(cleanup_retest_manifest))

    payload = {
        "mode": "replay_result_root_cleanup",
        "status": "done",
        "replay_result_root": str(root_path),
        "artifacts": {
            "cleanup_retest_manifest_json": str(cleanup_retest_manifest_json),
            "cleanup_retest_manifest_md": str(cleanup_retest_manifest_md),
        },
        "summary": {
            "audited_reports": audit["summary"]["audited_reports"],
            "trusted_cleanup_replay_candidates": audit["summary"]["trusted_cleanup_replay_candidates"],
            "selected_candidates": len(candidate_items),
            "replayed_candidates": len(replayed),
            "error_candidates": len(errors),
            "ai_flavor_score_delta_total": sum(
                _as_int(item.get("ai_flavor_score_delta"), default=0) for item in replayed
            ),
            "structural_residue_delta_total": sum(
                _as_int(item.get("structural_residue_delta"), default=0) for item in replayed
            ),
            "selected_candidate_labels": [str(item.get("label") or "") for item in candidate_items],
        },
        "replayed": replayed,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_compare_mode(args: argparse.Namespace) -> int:
    source_path = Path(args.compare_source_file).resolve()
    draft_path = Path(args.compare_draft_file).resolve()
    output_dir = _build_output_dir(Path(args.output_root).resolve(), args.label)

    source_markdown = _read_text(source_path)
    draft_markdown = _read_text(draft_path)
    source_title = args.source_title or _infer_title(source_markdown, "source")
    draft_title = args.draft_title or _infer_title(draft_markdown, "draft")
    evaluation = _evaluate_compare_pair(
        source_title=source_title,
        source_markdown=source_markdown,
        draft_title=draft_title,
        draft_markdown=draft_markdown,
        apply_current_cleanups=args.apply_current_cleanups,
    )
    compare_cleanup = evaluation["compare_cleanup"]
    output_draft_markdown = evaluation["draft_markdown"]
    source_detector_text = _to_detector_text(source_markdown)
    draft_detector_text = _to_detector_text(output_draft_markdown)

    result = {
        "mode": "compare",
        "status": "done",
        "source_file": str(source_path),
        "draft_file": str(draft_path),
        "source_title": source_title,
        "draft_title": draft_title,
        "structural_residue": evaluation["structural_residue"],
        "overlap_report": evaluation["overlap_report"],
        "ai_flavor": evaluation["ai_flavor"],
        "artifacts": {
            "output_dir": str(output_dir),
            "source_copy": str(output_dir / "source.md"),
            "draft_copy": str(output_dir / "draft.md"),
            "source_detector_text": str(output_dir / "source.txt"),
            "draft_detector_text": str(output_dir / "draft.txt"),
            "result_json": str(output_dir / "result.json"),
        },
    }
    if args.probe_ai_routes:
        result["ai_text_routes_probe"] = _probe_ai_text_routes()
    result["artifacts"]["external_detector_templates"] = _build_external_detector_templates(
        output_dir=output_dir,
        source_file=str(output_dir / "source.txt"),
        draft_file=str(output_dir / "draft.txt"),
        result_json_path=output_dir / "result.json",
    )
    detector_report = _maybe_build_external_detector_report(
        args,
        source_detector_text=source_detector_text,
        draft_detector_text=draft_detector_text,
    )
    if detector_report is not None:
        result["external_detector"] = detector_report
    if compare_cleanup is not None:
        result["compare_cleanup"] = compare_cleanup
        result["artifacts"]["draft_original_copy"] = str(output_dir / "draft.original.md")
    _write_text(output_dir / "source.md", source_markdown)
    _write_text(output_dir / "draft.md", output_draft_markdown)
    if compare_cleanup is not None:
        _write_text(output_dir / "draft.original.md", draft_markdown)
    _write_text(output_dir / "source.txt", source_detector_text)
    _write_text(output_dir / "draft.txt", draft_detector_text)
    _write_json(output_dir / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_rank_candidates_mode(args: argparse.Namespace) -> int:
    source_path = Path(args.rank_source_file).resolve()
    output_dir = _build_output_dir(Path(args.output_root).resolve(), args.label)
    source_markdown = _read_text(source_path)
    source_title = args.rank_source_title or _infer_title(source_markdown, "source")
    candidate_specs = _parse_rank_candidate_specs(args.rank_candidate)
    if not candidate_specs:
        raise ValueError("Rank mode requires at least one --rank-candidate value.")

    source_copy_path = output_dir / "source.md"
    source_detector_text_path = output_dir / "source.txt"
    result_path = output_dir / "result.json"
    candidates_root = output_dir / "candidates"
    _write_text(source_copy_path, source_markdown)
    _write_text(source_detector_text_path, _to_detector_text(source_markdown))

    result: dict[str, Any] = {
        "mode": "rank_candidates",
        "status": "done",
        "source_file": str(source_path),
        "source_title": source_title,
        "candidate_count": len(candidate_specs),
        "ranking_policy": {
            "priority": list(_RANKING_PRIORITY),
            "notes": "Lower rank_key values are better. Cleaned AI flavor score wins first, then original AI flavor score, then cleaned structural residue, cleanup cost, overlap, and final stable label order.",
        },
        "artifacts": {
            "output_dir": str(output_dir),
            "source_copy": str(source_copy_path),
            "source_detector_text": str(source_detector_text_path),
            "candidates_dir": str(candidates_root),
            "result_json": str(result_path),
        },
        "candidates": [],
    }
    if args.probe_ai_routes:
        result["ai_text_routes_probe"] = _probe_ai_text_routes()

    for index, candidate_spec in enumerate(candidate_specs, start=1):
        draft_path = Path(candidate_spec["draft_file"]).resolve()
        draft_markdown = _read_text(draft_path)
        label = candidate_spec["label"]
        draft_title = _infer_title(draft_markdown, label)
        evaluation = _evaluate_compare_pair(
            source_title=source_title,
            source_markdown=source_markdown,
            draft_title=draft_title,
            draft_markdown=draft_markdown,
            apply_current_cleanups=args.apply_current_cleanups,
        )
        structural_residue = evaluation.get("structural_residue")
        if not isinstance(structural_residue, Mapping):
            structural_residue = _build_structural_residue(evaluation["draft_markdown"])
        artifact_dir = _build_candidate_artifact_dir(candidates_root, index, label)
        draft_copy_path = artifact_dir / "draft.md"
        draft_detector_text_path = artifact_dir / "draft.txt"
        _write_text(draft_copy_path, evaluation["draft_markdown"])
        _write_text(draft_detector_text_path, _to_detector_text(evaluation["draft_markdown"]))

        candidate_payload: dict[str, Any] = {
            "label": label,
            "draft_file": str(draft_path),
            "draft_title": evaluation["draft_title"],
            "structural_residue": dict(structural_residue),
            "overlap_report": evaluation["overlap_report"],
            "ai_flavor": evaluation["ai_flavor"],
            "artifacts": {
                "candidate_dir": str(artifact_dir),
                "draft_copy": str(draft_copy_path),
                "draft_detector_text": str(draft_detector_text_path),
            },
        }
        if evaluation["compare_cleanup"] is not None:
            original_copy_path = artifact_dir / "draft.original.md"
            _write_text(original_copy_path, draft_markdown)
            candidate_payload["compare_cleanup"] = evaluation["compare_cleanup"]
            candidate_payload["artifacts"]["draft_original_copy"] = str(original_copy_path)
        candidate_payload["rank_key"] = list(_candidate_rank_tuple(candidate_payload))
        result["candidates"].append(candidate_payload)

    ranked_candidates = sorted(result["candidates"], key=_candidate_rank_tuple)
    for rank, candidate in enumerate(ranked_candidates, start=1):
        candidate["rank"] = rank
    result["candidates"] = ranked_candidates
    result["best_candidate"] = {
        "label": ranked_candidates[0]["label"],
        "draft_title": ranked_candidates[0]["draft_title"],
        "rank": 1,
        "rank_key": ranked_candidates[0]["rank_key"],
    }

    _write_json(result_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_export_prompts_mode(args: argparse.Namespace) -> int:
    input_path = Path(args.input_file).resolve()
    source_markdown = _read_text(input_path)
    output_dir = _build_output_dir(Path(args.output_root).resolve(), args.label)
    bundle_db_path = output_dir / "workbench.db"
    runtime_db_path = _build_runtime_db_path(output_dir)
    source_copy_path = output_dir / "source.md"
    source_detector_text_path = output_dir / "source.txt"
    result_path = output_dir / "result.json"
    _write_text(source_copy_path, source_markdown)
    _write_text(source_detector_text_path, _to_detector_text(source_markdown))

    os.environ["DB_PATH"] = str(runtime_db_path)
    os.environ["GENERATED_ASSETS_DIR"] = str(output_dir / "assets")

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.schemas.projects import ProjectCreate
    from app.schemas.topics import TopicCreateFromTrend
    from app.schemas.tracked_articles import TrackedArticleCreate
    from app.services.ai_generator import get_ai_config_summary
    from app.services.prompt_templates import build_draft_prompt, build_outline_prompt
    from app.services.workbench import (
        _build_reference_article_payload,
        _build_strategy_bundle_payload,
        _get_connection,
        _get_project_context,
        _load_project_strategy_bundle,
        adopt_strategy_card,
        create_project_from_topic,
        create_topic_from_tracked_article,
        enrich_tracked_article_metadata,
        generate_strategy_package,
        generate_topic_from_tracked_article,
        get_project_domain_pack,
        get_project_tone_profile,
        import_tracked_articles,
        initialize_store,
        list_tone_profiles,
    )

    run_id = output_dir.name
    article_slug = f"article-{run_id}"
    project_slug = f"{article_slug}-project"
    article_title = args.article_title or _infer_title(source_markdown, article_slug)
    reuse_bundle_payload = _load_reuse_bundle_payload(args.reuse_bundle_json)
    tracked_article_seed = _build_tracked_article_seed(
        article_slug=article_slug,
        article_title=article_title,
        source_markdown=source_markdown,
        source_name=args.source_name,
        reuse_bundle_payload=reuse_bundle_payload,
    )
    article_payload = TrackedArticleCreate(**tracked_article_seed)

    partial: dict[str, Any] = {
        "mode": "export_prompts",
        "status": "running",
        "input_file": str(input_path),
        "source_title": article_title,
        "artifacts": {
            "output_dir": str(output_dir),
            "db_path": str(bundle_db_path),
            "runtime_db_path": str(runtime_db_path),
            "source_md": str(source_copy_path),
            "source_detector_text": str(source_detector_text_path),
            "outline_prompt_json": str(output_dir / "outline-prompt.json"),
            "draft_prompt_json": str(output_dir / "draft-prompt.json"),
            "result_json": str(result_path),
        },
        "ai_config": get_ai_config_summary().model_dump(),
    }
    if args.probe_ai_routes:
        partial["ai_text_routes_probe"] = _probe_ai_text_routes()
    _write_json(result_path, partial)

    try:
        initialize_store(reset=True)
        tone_profile_backend = {
            "list_tone_profiles": list_tone_profiles,
        }
        selected_tone_profile_id = _resolve_preferred_tone_profile_id(
            args=args,
            backend=tone_profile_backend,
        )
        selected_tone_profile = _describe_selected_tone_profile(
            profile_id=selected_tone_profile_id,
            backend=tone_profile_backend,
        )
        if selected_tone_profile is not None:
            partial["selected_tone_profile"] = selected_tone_profile
        import_result = import_tracked_articles([article_payload], source_kind="manual")
        partial["import_result"] = import_result

        _best_effort_enrich_tracked_article(
            article_slug=article_slug,
            article_payload=article_payload,
            enrich_tracked_article_metadata=enrich_tracked_article_metadata,
            should_skip=_should_skip_tracked_article_enrichment(args=args, reuse_bundle_payload=reuse_bundle_payload),
            partial=partial,
        )

        reuse_topic_seed = (
            _extract_reuse_topic_seed(reuse_bundle_payload)
            if args.reuse_topic_from_bundle
            else None
        )
        if reuse_topic_seed:
            topic = create_topic_from_tracked_article(
                article_slug,
                TopicCreateFromTrend(
                    slug=f"{article_slug}-ai-topic-1",
                    title=reuse_topic_seed["title"],
                    angle=reuse_topic_seed["angle"],
                ),
            )
            partial["topic_seed"] = reuse_topic_seed
        else:
            topic = generate_topic_from_tracked_article(article_slug)
        partial["topic"] = topic.model_dump()

        project = create_project_from_topic(
            topic.slug,
            ProjectCreate(
                slug=project_slug,
                title=args.project_title or topic.title,
                owner=args.owner,
                preferred_tone_profile_id=selected_tone_profile_id,
                domain_pack_key=None,
            ),
        )
        partial["project"] = project.model_dump()

        strategy = generate_strategy_package(project.slug)
        partial["strategy"] = strategy.model_dump()
        adopted = adopt_strategy_card(project.slug, strategy.strategy_card.version)
        partial["adopted_strategy"] = adopted.model_dump()

        project_context = _get_project_context(project.slug)
        tone_profile = get_project_tone_profile(project_context)
        domain_pack = get_project_domain_pack(project_context)
        with _get_connection() as connection:
            problem_brief, benchmarks, strategy_card = _load_project_strategy_bundle(
                connection,
                project.slug,
                adopted_only=True,
            )

        reference_article_payload = _build_reference_article_payload(
            project_context,
            hide_details=str(project_context["source_type"]) == "tracked_article" and bool(problem_brief and strategy_card),
        )
        strategy_bundle_payload = _build_strategy_bundle_payload(
            problem_brief=problem_brief,
            strategy_card=strategy_card,
            benchmarks=benchmarks,
        )

        outline_payload: dict[str, object] = {
            "trend_title": project_context["trend_title"],
            "topic_title": project_context["topic_title"],
            "topic_angle": project_context["topic_angle"],
            "project_title": project_context["title"],
            "tone_profile": tone_profile.model_dump(),
            "domain_pack": domain_pack,
            **reference_article_payload,
            **strategy_bundle_payload,
        }
        outline_template = build_outline_prompt(outline_payload)
        placeholder_outline = {
            "hook": "占位钩子，用于导出 draft prompt，不代表模型输出。",
            "outline_body": "1. 占位大纲\n2. 这里只导出当前 prompt bundle\n3. 不触发实际模型调用",
        }
        draft_payload: dict[str, object] = {
            "trend_title": project_context["trend_title"],
            "topic_title": project_context["topic_title"],
            "topic_angle": project_context["topic_angle"],
            "project_title": project_context["title"],
            "outline": placeholder_outline,
            "tone_profile": tone_profile.model_dump(),
            "domain_pack": domain_pack,
            **reference_article_payload,
            **strategy_bundle_payload,
        }
        draft_template = build_draft_prompt(draft_payload)

        outline_prompt_payload = {
            "instructions": outline_template.instructions,
            "prompt": outline_template.prompt,
            "payload": outline_payload,
        }
        draft_prompt_payload = {
            "instructions": draft_template.instructions,
            "prompt": draft_template.prompt,
            "payload": draft_payload,
        }
        _write_json(Path(partial["artifacts"]["outline_prompt_json"]), outline_prompt_payload)
        _write_json(Path(partial["artifacts"]["draft_prompt_json"]), draft_prompt_payload)

        partial["outline_prompt"] = {
            "instructions_chars": len(outline_template.instructions),
            "prompt_chars": len(outline_template.prompt),
        }
        partial["draft_prompt"] = {
            "instructions_chars": len(draft_template.instructions),
            "prompt_chars": len(draft_template.prompt),
        }
        _sync_runtime_db_to_bundle(runtime_db_path=runtime_db_path, bundle_db_path=bundle_db_path)
        partial["status"] = "done"
        _write_json(result_path, partial)
        _safe_print_json(partial)
        return 0
    except Exception as exc:  # pragma: no cover - exercised by live runs
        _sync_runtime_db_to_bundle(runtime_db_path=runtime_db_path, bundle_db_path=bundle_db_path)
        partial["status"] = "failed"
        partial["error"] = {"message": str(exc), "traceback": traceback.format_exc()}
        _write_json(result_path, partial)
        _safe_print_json(partial)
        return 1


def _run_pipeline_mode(args: argparse.Namespace) -> int:
    input_path = Path(args.input_file).resolve()
    source_markdown = _read_text(input_path)
    output_dir = _build_output_dir(Path(args.output_root).resolve(), args.label)
    bundle_db_path = output_dir / "workbench.db"
    runtime_db_path = _build_runtime_db_path(output_dir)
    source_copy_path = output_dir / "source.md"
    source_detector_text_path = output_dir / "source.txt"
    result_path = output_dir / "result.json"
    _write_text(source_copy_path, source_markdown)
    _write_text(source_detector_text_path, _to_detector_text(source_markdown))

    os.environ["DB_PATH"] = str(runtime_db_path)
    os.environ["GENERATED_ASSETS_DIR"] = str(output_dir / "assets")

    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))

    from app.schemas.projects import ProjectCreate
    from app.schemas.topics import TopicCreateFromTrend
    from app.schemas.tracked_articles import TrackedArticleCreate
    from app.services.ai_flavor import evaluate_ai_flavor_risk
    from app.services.ai_generator import get_ai_config_summary
    from app.services.workbench import (
        adopt_strategy_card,
        create_project_from_topic,
        create_topic_from_tracked_article,
        enrich_tracked_article_metadata,
        generate_draft,
        generate_outline,
        generate_strategy_package,
        generate_topic_from_tracked_article,
        get_project_detail,
        initialize_store,
        import_tracked_articles,
        list_tone_profiles,
    )

    run_id = output_dir.name
    article_slug = f"article-{run_id}"
    project_slug = f"{article_slug}-project"
    article_title = args.article_title or _infer_title(source_markdown, article_slug)
    reuse_bundle_payload = _load_reuse_bundle_payload(args.reuse_bundle_json)
    tracked_article_seed = _build_tracked_article_seed(
        article_slug=article_slug,
        article_title=article_title,
        source_markdown=source_markdown,
        source_name=args.source_name,
        reuse_bundle_payload=reuse_bundle_payload,
    )
    article_payload = TrackedArticleCreate(**tracked_article_seed)

    partial: dict[str, Any] = {
        "mode": "pipeline",
        "status": "running",
        "input_file": str(input_path),
        "source_title": article_title,
        "artifacts": {
            "output_dir": str(output_dir),
            "db_path": str(bundle_db_path),
            "runtime_db_path": str(runtime_db_path),
            "source_md": str(source_copy_path),
            "source_detector_text": str(source_detector_text_path),
            "draft_md": str(output_dir / "draft.md"),
            "draft_detector_text": str(output_dir / "draft.txt"),
            "result_json": str(result_path),
        },
        "ai_config": get_ai_config_summary().model_dump(),
    }
    if args.probe_ai_routes:
        partial["ai_text_routes_probe"] = _probe_ai_text_routes()
    partial["artifacts"]["external_detector_templates"] = _build_external_detector_templates(
        output_dir=output_dir,
        source_file=str(source_detector_text_path),
        draft_file=str(output_dir / "draft.txt"),
        result_json_path=result_path,
    )
    _write_json(result_path, partial)

    try:
        initialize_store(reset=True)
        tone_profile_backend = {
            "list_tone_profiles": list_tone_profiles,
        }
        selected_tone_profile_id = _resolve_preferred_tone_profile_id(
            args=args,
            backend=tone_profile_backend,
        )
        selected_tone_profile = _describe_selected_tone_profile(
            profile_id=selected_tone_profile_id,
            backend=tone_profile_backend,
        )
        if selected_tone_profile is not None:
            partial["selected_tone_profile"] = selected_tone_profile
        import_result = import_tracked_articles([article_payload], source_kind="manual")
        partial["import_result"] = import_result

        _best_effort_enrich_tracked_article(
            article_slug=article_slug,
            article_payload=article_payload,
            enrich_tracked_article_metadata=enrich_tracked_article_metadata,
            should_skip=_should_skip_tracked_article_enrichment(args=args, reuse_bundle_payload=reuse_bundle_payload),
            partial=partial,
        )

        reuse_topic_seed = (
            _extract_reuse_topic_seed(reuse_bundle_payload)
            if args.reuse_topic_from_bundle
            else None
        )
        if reuse_topic_seed:
            topic = create_topic_from_tracked_article(
                article_slug,
                TopicCreateFromTrend(
                    slug=f"{article_slug}-ai-topic-1",
                    title=reuse_topic_seed["title"],
                    angle=reuse_topic_seed["angle"],
                ),
            )
            partial["topic_seed"] = reuse_topic_seed
        else:
            topic = generate_topic_from_tracked_article(article_slug)
        partial["topic"] = topic.model_dump()

        project = create_project_from_topic(
            topic.slug,
            ProjectCreate(
                slug=project_slug,
                title=args.project_title or topic.title,
                owner=args.owner,
                preferred_tone_profile_id=selected_tone_profile_id,
                domain_pack_key=None,
            ),
        )
        partial["project"] = project.model_dump()

        strategy = generate_strategy_package(project.slug)
        partial["strategy"] = strategy.model_dump()
        adopted = adopt_strategy_card(project.slug, strategy.strategy_card.version)
        partial["adopted_strategy"] = adopted.model_dump()

        outline = generate_outline(project.slug)
        draft = generate_draft(project.slug)
        detail = get_project_detail(project.slug)

        draft_path = output_dir / "draft.md"
        _write_text(draft_path, draft.body_markdown)
        _write_text(output_dir / "draft.txt", _to_detector_text(draft.body_markdown))

        partial["outline"] = outline.model_dump()
        partial["draft"] = draft.model_dump()
        partial["project_detail"] = detail.model_dump()
        partial["overlap_report"] = _build_overlap_report(
            source_title=article_title,
            source_markdown=source_markdown,
            draft_title=draft.title,
            draft_markdown=draft.body_markdown,
        )
        partial["ai_flavor"] = {
            "source": evaluate_ai_flavor_risk(title=article_title, body_markdown=source_markdown).__dict__,
            "draft": evaluate_ai_flavor_risk(title=draft.title, body_markdown=draft.body_markdown).__dict__,
        }
        detector_report = _maybe_build_external_detector_report(
            args,
            source_detector_text=_to_detector_text(source_markdown),
            draft_detector_text=_to_detector_text(draft.body_markdown),
        )
        if detector_report is not None:
            partial["external_detector"] = detector_report
        _sync_runtime_db_to_bundle(runtime_db_path=runtime_db_path, bundle_db_path=bundle_db_path)
        partial["status"] = "done"
        _write_json(result_path, partial)
        _safe_print_json(partial)
        return 0
    except Exception as exc:  # pragma: no cover - exercised by live runs
        _sync_runtime_db_to_bundle(runtime_db_path=runtime_db_path, bundle_db_path=bundle_db_path)
        partial["status"] = "failed"
        partial["error"] = {"message": str(exc), "traceback": traceback.format_exc()}
        _write_json(result_path, partial)
        _safe_print_json(partial)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a tracked-article originality case or compare an existing source/draft pair."
    )
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="Directory used for result bundles.")
    parser.add_argument("--label", default=None, help="Optional fixed output directory name.")

    parser.add_argument("--input-file", default=None, help="Source article markdown/text file for pipeline mode.")
    parser.add_argument("--article-title", default=None, help="Optional source article title for pipeline mode.")
    parser.add_argument("--project-title", default=None, help="Optional project title override for pipeline mode.")
    parser.add_argument("--source-name", default="manual-originality-check", help="Tracked article source label.")
    parser.add_argument("--owner", default="originality-check", help="Project owner for pipeline mode.")
    parser.add_argument(
        "--tone-profile-name",
        default=None,
        help="Optional tone profile name to bind on project creation, for example 今晚有语.",
    )
    parser.add_argument(
        "--tone-profile-id",
        type=int,
        default=None,
        help="Optional tone profile id to bind on project creation. Overrides --tone-profile-name when both are provided.",
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
    parser.add_argument("--openai-image-api-key", default=None, help="Optional OPENAI_IMAGE_API_KEY override for this run only.")
    parser.add_argument("--openai-image-base-url", default=None, help="Optional OPENAI_IMAGE_BASE_URL override for this run only.")
    parser.add_argument("--openai-image-model", default=None, help="Optional OPENAI_IMAGE_MODEL override for this run only.")
    parser.add_argument(
        "--openai-image-request-timeout-seconds",
        type=float,
        default=None,
        help="Optional OPENAI_IMAGE_REQUEST_TIMEOUT_SECONDS override for this run only.",
    )
    parser.add_argument(
        "--probe-ai-routes",
        action="store_true",
        help="Probe responses.create / responses.parse / chat.completions and persist the route status into result.json.",
    )
    parser.add_argument(
        "--skip-enrich",
        action="store_true",
        help="Skip tracked article metadata enrichment before topic generation.",
    )
    parser.add_argument(
        "--reuse-bundle-json",
        default=None,
        help="Optional previous result.json used to seed tracked article metadata fields such as summary and tags.",
    )
    parser.add_argument(
        "--reuse-topic-from-bundle",
        action="store_true",
        help="Reuse the topic title and angle from --reuse-bundle-json instead of calling topic generation.",
    )

    parser.add_argument("--compare-source-file", default=None, help="Existing source markdown file for compare mode.")
    parser.add_argument("--compare-draft-file", default=None, help="Existing draft markdown file for compare mode.")
    parser.add_argument("--rank-source-file", default=None, help="Source markdown file for multi-candidate local ranking mode.")
    parser.add_argument("--rank-source-title", default=None, help="Optional source title for ranking mode.")
    parser.add_argument(
        "--rank-candidate",
        action="append",
        default=None,
        help="Repeatable candidate spec for ranking mode. Use [label::]draft.md or [label::]directory-containing-draft.",
    )
    parser.add_argument(
        "--apply-current-cleanups",
        action="store_true",
        help="Apply the current deterministic draft cleanup chain before exporting compare artifacts.",
    )
    parser.add_argument(
        "--export-prompts-only",
        action="store_true",
        help="Build the tracked-article project context and export outline/draft prompt bundles without calling the model.",
    )
    parser.add_argument("--source-title", default=None, help="Optional source title for compare mode.")
    parser.add_argument("--draft-title", default=None, help="Optional draft title for compare mode.")
    parser.add_argument(
        "--attach-result-json",
        default=None,
        help="Existing result.json to update with external detector output.",
    )
    parser.add_argument(
        "--replay-result-json",
        default=None,
        help="Replay an existing result.json through the current deterministic cleanup chain and export a new compare bundle.",
    )
    parser.add_argument(
        "--replay-result-root",
        default=None,
        help="Replay all audited bundles under a root that are trusted and still improve under the current deterministic cleanup chain.",
    )
    parser.add_argument(
        "--audit-result-json",
        default=None,
        help="Audit a single result.json external detector report and print trust classification.",
    )
    parser.add_argument(
        "--audit-result-root",
        default=None,
        help="Audit all result.json files under a root directory and summarize trusted/untrusted/unverified bundles.",
    )
    parser.add_argument(
        "--external-detector-name",
        default=None,
        help="Optional external detector label, for example zhuque_tencent.",
    )
    parser.add_argument(
        "--source-detector-json",
        default=None,
        help="Optional JSON file containing the detector result for the source text.",
    )
    parser.add_argument(
        "--draft-detector-json",
        default=None,
        help="Optional JSON file containing the detector result for the draft text.",
    )
    parser.add_argument(
        "--source-detector-score",
        type=float,
        default=None,
        help="Optional detector score for the source text when only a numeric result is available.",
    )
    parser.add_argument(
        "--draft-detector-score",
        type=float,
        default=None,
        help="Optional detector score for the draft text when only a numeric result is available.",
    )
    parser.add_argument(
        "--source-zhuque-report-file",
        default=None,
        help="Optional text file containing copied visible Zhuque report text for the source text.",
    )
    parser.add_argument(
        "--source-zhuque-report-clipboard",
        action="store_true",
        help="Read the copied visible Zhuque report text for the source text from the system clipboard.",
    )
    parser.add_argument(
        "--draft-zhuque-report-file",
        default=None,
        help="Optional text file containing copied visible Zhuque report text for the draft text.",
    )
    parser.add_argument(
        "--draft-zhuque-report-clipboard",
        action="store_true",
        help="Read the copied visible Zhuque report text for the draft text from the system clipboard.",
    )
    return parser


def main() -> int:
    _configure_utf8_stdio()
    parser = _build_parser()
    args = parser.parse_args()
    _apply_ai_overrides(args)

    if args.audit_result_json or args.audit_result_root:
        if args.audit_result_json and args.audit_result_root:
            parser.error("--audit-result-json and --audit-result-root cannot be provided together.")
        return _run_audit_detector_mode(args)

    if args.replay_result_json and args.replay_result_root:
        parser.error("--replay-result-json and --replay-result-root cannot be provided together.")

    if args.replay_result_json:
        return _run_replay_result_mode(args)

    if args.replay_result_root:
        return _run_replay_result_root_mode(args)

    if args.attach_result_json:
        return _run_attach_detector_mode(args)

    if args.compare_source_file or args.compare_draft_file:
        if not args.compare_source_file or not args.compare_draft_file:
            parser.error("--compare-source-file and --compare-draft-file must be provided together.")
        return _run_compare_mode(args)

    if args.rank_source_file or args.rank_candidate:
        if not args.rank_source_file or not args.rank_candidate:
            parser.error("--rank-source-file and at least one --rank-candidate must be provided together.")
        return _run_rank_candidates_mode(args)

    if not args.input_file:
        parser.error("Provide --input-file for pipeline mode, or --compare-source-file with --compare-draft-file.")
    if args.export_prompts_only:
        return _run_export_prompts_mode(args)
    return _run_pipeline_mode(args)


if __name__ == "__main__":
    raise SystemExit(main())
