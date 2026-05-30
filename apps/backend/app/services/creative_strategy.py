from __future__ import annotations

from collections.abc import Mapping

from app.schemas.creative_workflow import (
    BenchmarkReferenceItem,
    ProblemBriefItem,
    StrategyCardItem,
    StrategyPackageResult,
)


def _read_project_value(project: Mapping[str, object], key: str, default: str = "") -> str:
    try:
        value = project[key]
    except (KeyError, IndexError, TypeError):
        value = default
    if value is None:
        return default
    return str(value)


def build_strategy_package(
    *,
    project: Mapping[str, object],
    problem_brief_version: int,
    strategy_version: int,
    created_at: str,
) -> StrategyPackageResult:
    topic_title = _read_project_value(project, "topic_title")
    topic_angle = _read_project_value(project, "topic_angle")
    trend_title = _read_project_value(project, "trend_title")
    project_slug = _read_project_value(project, "slug")
    source_mode = _read_project_value(project, "source_type", "trend") or "trend"
    reader_situation = _build_reader_situation(topic_title, topic_angle)
    core_conflict = _build_core_conflict(topic_title, topic_angle)

    problem_brief = ProblemBriefItem(
        project_slug=project_slug,
        version=problem_brief_version,
        source_mode=source_mode,
        raw_goal=topic_title,
        clarified_problem=(
            f"这篇文章要解释，{topic_title}背后真正需要被看见的，"
            f"是{trend_title}这类处境里一点点累积出来的压力和失衡。"
        ),
        target_reader_situation=reader_situation,
        core_conflict=core_conflict,
        unknowns=[],
        status="ready",
        created_at=created_at,
    )

    benchmarks = [
        BenchmarkReferenceItem(
            project_slug=project_slug,
            strategy_version=strategy_version,
            reference_kind=_resolve_reference_kind(source_mode),
            reference_label=_resolve_reference_label(project, source_mode),
            reference_pointer=_read_project_value(project, "source_ref_slug", project_slug) or project_slug,
            borrow_focus="开头的处境进入和中段停顿节奏",
            avoid_focus="不要复用现成判断句和口号式结尾",
            rationale="先借节奏和观察角度，不借现成表达。",
            sort_order=1,
        )
    ]

    strategy_card = StrategyCardItem(
        project_slug=project_slug,
        version=strategy_version,
        problem_brief_version=problem_brief_version,
        reader_situation=reader_situation,
        point_of_view=_build_point_of_view(topic_angle),
        conflict_frame=_build_conflict_frame(topic_title, topic_angle),
        emotional_path="从具体处境进入，先让委屈和停顿出现，再慢慢推进到能开口或能自救的动作。",
        expression_constraints=[
            "不要用口号式收尾",
            "不要复用不是A而是B的对称判断句",
        ],
        benchmark_summary="开头先落动作和停顿，中段再进入判断。",
        status="ready",
        created_at=created_at,
        adopted_at=None,
    )

    return StrategyPackageResult(
        project_slug=project_slug,
        problem_brief=problem_brief,
        benchmarks=benchmarks,
        strategy_card=strategy_card,
    )


def _resolve_reference_kind(source_mode: str) -> str:
    if source_mode == "tracked_article":
        return "tracked_article"
    if source_mode == "manual":
        return "operator_reference"
    return "trend"


def _resolve_reference_label(project: Mapping[str, object], source_mode: str) -> str:
    if source_mode == "tracked_article":
        title = _read_project_value(project, "reference_article_title").strip()
        if title:
            return title
    if source_mode == "manual":
        return _read_project_value(project, "topic_title")
    return _read_project_value(project, "trend_title")


def _build_reader_situation(topic_title: str, topic_angle: str) -> str:
    if "边界" in topic_angle:
        return "在关系里想解释，却越来越不想开口的人"
    if "情绪" in topic_angle:
        return "已经开始耗尽，却还在逼自己继续撑住的人"
    if "自我" in topic_angle:
        return "总觉得应该先把自己稳住，却越稳越累的人"
    return f"正在为“{topic_title}”这类处境反复卡住的人"


def _build_core_conflict(topic_title: str, topic_angle: str) -> str:
    if "边界" in topic_angle:
        return "越想被理解，越容易把真正想说的话咽回去。"
    if "情绪" in topic_angle:
        return "越想赶快恢复正常，越容易忽略身体和情绪已经在报警。"
    if "自我" in topic_angle:
        return "越想证明自己能扛住，越容易把真正的疲惫藏得更深。"
    return f"{topic_title}里最难的，不是知道道理，而是怎么在当下真的做到。"


def _build_point_of_view(topic_angle: str) -> str:
    if "边界" in topic_angle:
        return "不教训，不站高位，只把话为什么越想说越说不出来讲清楚。"
    if "情绪" in topic_angle:
        return "不急着给解决方案，先把人为什么会一点点耗尽讲清楚。"
    return "不说教，不站高位，先把读者当下真正卡住的地方讲清楚。"


def _build_conflict_frame(topic_title: str, topic_angle: str) -> str:
    if "边界" in topic_angle:
        return "不是一次大冲突，而是一次次想开口又收回去。"
    if "情绪" in topic_angle:
        return "不是突然垮掉，而是很久以前就开始慢慢失去电量。"
    return f"不是把{topic_title}说成道理，而是把它还原成一个人是怎么慢慢被推到这里的。"
