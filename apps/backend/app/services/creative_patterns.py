from __future__ import annotations

import re
from typing import Sequence

from fastapi import HTTPException

from app.schemas.creative_workflow import (
    PromoteCreativePatternAction,
    RetainedLessonItem,
    ReusablePatternItem,
)


def build_reusable_pattern_from_lesson(
    *,
    pattern_id: str,
    source_project_slug: str,
    source_report_version: int,
    retained_lessons: Sequence[RetainedLessonItem],
    payload: PromoteCreativePatternAction,
    created_at: str,
) -> ReusablePatternItem:
    if payload.lesson_index < 0 or payload.lesson_index >= len(retained_lessons):
        raise HTTPException(status_code=400, detail="Lesson index is out of range")

    lesson = retained_lessons[payload.lesson_index]
    return ReusablePatternItem(
        id=pattern_id,
        source_project_slug=source_project_slug,
        source_report_version=source_report_version,
        pattern_type=_trim_or_default(payload.pattern_type, lesson.pattern_type),
        title=_trim_or_default(payload.title, lesson.title),
        intended_use=_trim_or_default(payload.intended_use, lesson.intended_use),
        pattern_content=lesson.pattern_content,
        caution_notes=_trim_or_default(payload.caution_notes, lesson.caution_notes),
        status="active",
        created_at=created_at,
    )


def build_reusable_pattern_id(
    *,
    source_project_slug: str,
    source_report_version: int,
    lesson_index: int,
    title: str,
) -> str:
    slug = _slugify(title) or "pattern"
    return f"{_slugify(source_project_slug)}-r{source_report_version}-l{lesson_index + 1}-{slug}"[:120]


def _trim_or_default(value: str | None, fallback: str) -> str:
    normalized = (value or "").strip()
    return normalized or fallback


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", value.strip().lower())
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized
