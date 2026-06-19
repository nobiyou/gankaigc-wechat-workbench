from __future__ import annotations

from app.schemas.creative_workflow import PromoteCreativePatternAction, RetainedLessonItem
from app.services.creative_patterns import build_reusable_pattern_from_lesson, build_reusable_pattern_id


def test_build_reusable_pattern_from_lesson_uses_operator_overrides_without_copying_caution() -> None:
    retained_lessons = [
        RetainedLessonItem(
            title="开头先落到动作",
            pattern_type="opening",
            intended_use="适合同类关系稿。",
            pattern_content="先写一个动作，再给判断。",
            caution_notes="不要复用旧句子。",
        )
    ]
    pattern_id = build_reusable_pattern_id(
        source_project_slug="demo-project",
        source_report_version=2,
        lesson_index=0,
        title="饭桌开头模式",
    )

    pattern = build_reusable_pattern_from_lesson(
        pattern_id=pattern_id,
        source_project_slug="demo-project",
        source_report_version=2,
        retained_lessons=retained_lessons,
        payload=PromoteCreativePatternAction(
            report_version=2,
            lesson_index=0,
            title="饭桌开头模式",
            pattern_type="benchmark-opening",
            intended_use="适合微妙关系修复稿。",
            caution_notes="只复用方法，不复用旧案例。",
        ),
        created_at="2026-06-19T00:00:00+00:00",
    )

    assert pattern.id.startswith("demo-project-r2-l1")
    assert pattern.source_project_slug == "demo-project"
    assert pattern.source_report_version == 2
    assert pattern.title == "饭桌开头模式"
    assert pattern.pattern_type == "benchmark-opening"
    assert pattern.intended_use == "适合微妙关系修复稿。"
    assert pattern.pattern_content == "先写一个动作，再给判断。"
    assert pattern.caution_notes == "只复用方法，不复用旧案例。"
    assert pattern.status == "active"
