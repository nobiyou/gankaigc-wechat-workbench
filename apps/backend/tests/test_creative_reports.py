from __future__ import annotations

from app.services.creative_reports import build_creative_review_report


def test_creative_review_report_summarizes_strategy_diagnosis_and_revision_trace() -> None:
    report = build_creative_review_report(
        project_slug="demo-project",
        version=1,
        created_at="2026-06-19T00:00:00+00:00",
        project={
            "slug": "demo-project",
            "title": "关系修复稿",
            "stage": "draft_ready",
            "current_chain_state": "draft_ready",
        },
        problem_brief={
            "version": 1,
            "status": "ready",
            "clarified_problem": "解释为什么修复关系时先接住情绪，而不是先讲道理。",
            "target_reader_situation": "想解释但越解释越累的人",
        },
        benchmarks=[
            {
                "reference_label": "饭桌场景参考",
                "borrow_focus": "生活场景进入",
                "avoid_focus": "不复用判断句",
            }
        ],
        strategy_card={
            "version": 1,
            "status": "ready",
            "point_of_view": "不教训，只把关系里的错位讲清楚",
            "conflict_frame": "想修复的人先被没接住的情绪卡住",
            "emotional_path": "从沉默到被看见",
            "opening_move": "先写饭桌上那一下停顿。",
        },
        diagnosis_reports=[
            {
                "version": 2,
                "draft_version": 3,
                "objective_summary": "先重写开头和中段推进",
                "recommended_next_action": "strengthen_opening_and_progression",
                "upstream_findings": ["开头切口偏弱"],
                "downstream_findings": ["推进效率偏低"],
            }
        ],
        directional_polish_links=[
            {
                "source_draft_version": 3,
                "target_draft_version": 4,
                "diagnosis_version": 2,
                "objective_key": "strengthen_opening_and_progression",
                "objective_summary": "先重写开头和中段推进",
            }
        ],
        drafts=[
            {"version": 3, "title": "旧稿", "word_count": 100},
            {"version": 4, "title": "新稿", "word_count": 110},
        ],
        publish_package={
            "version": 1,
            "status": "ready",
            "abstract": "写给想修复关系却越解释越累的人。",
        },
        retro={"summary": "一版修好了开头。", "next_focus": "下一版强化标题。", "wins": ["饭桌切入有效"]},
    )

    assert report.project_slug == "demo-project"
    assert report.strategy_version == 1
    assert report.draft_version == 4
    assert "## 前写作策略" in report.summary_markdown
    assert "饭桌场景参考" in report.summary_markdown
    assert "草稿 v3 -> v4" in report.summary_markdown
    assert "先重写开头和中段推进" in report.summary_markdown
    assert any(lesson.pattern_type == "opening" for lesson in report.retained_lessons)
    assert any(lesson.pattern_type == "revision_trace" for lesson in report.retained_lessons)


def test_creative_review_report_handles_legacy_partial_history() -> None:
    report = build_creative_review_report(
        project_slug="legacy-project",
        version=1,
        created_at="2026-06-19T00:00:00+00:00",
        project={
            "slug": "legacy-project",
            "title": "旧项目",
            "stage": "draft_ready",
            "current_chain_state": "draft_ready",
        },
        drafts=[{"version": 1, "title": "旧项目初稿", "word_count": 100}],
    )

    assert report.strategy_version is None
    assert report.draft_version == 1
    assert "暂无记录，本报告只汇总当前项目已有事实" in report.summary_markdown
    assert report.retained_lessons[0].pattern_type == "review_note"
    assert "旧项目初稿" in report.retained_lessons[0].pattern_content
