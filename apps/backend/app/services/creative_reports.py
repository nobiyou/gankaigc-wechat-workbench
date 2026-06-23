from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.schemas.creative_workflow import CreativeReviewReportItem, RetainedLessonItem


def build_creative_review_report(
    *,
    project_slug: str,
    version: int,
    created_at: str,
    project: Mapping[str, Any],
    problem_brief: Mapping[str, Any] | None = None,
    benchmarks: Sequence[Mapping[str, Any]] = (),
    strategy_card: Mapping[str, Any] | None = None,
    diagnosis_reports: Sequence[Mapping[str, Any]] = (),
    directional_polish_links: Sequence[Mapping[str, Any]] = (),
    drafts: Sequence[Mapping[str, Any]] = (),
    publish_package: Mapping[str, Any] | None = None,
    retro: Mapping[str, Any] | None = None,
) -> CreativeReviewReportItem:
    latest_draft = _latest_by_version(drafts)
    latest_diagnosis = _latest_by_version(diagnosis_reports)
    strategy_version = _safe_int(strategy_card.get("version")) if strategy_card else None
    draft_version = _safe_int(latest_draft.get("version")) if latest_draft else None
    retained_lessons = _build_retained_lessons(
        project=project,
        strategy_card=strategy_card,
        latest_diagnosis=latest_diagnosis,
        directional_polish_links=directional_polish_links,
        latest_draft=latest_draft,
        publish_package=publish_package,
        retro=retro,
    )
    summary_markdown = _build_summary_markdown(
        project=project,
        problem_brief=problem_brief,
        benchmarks=benchmarks,
        strategy_card=strategy_card,
        latest_diagnosis=latest_diagnosis,
        directional_polish_links=directional_polish_links,
        drafts=drafts,
        publish_package=publish_package,
        retro=retro,
        retained_lessons=retained_lessons,
    )

    return CreativeReviewReportItem(
        project_slug=project_slug,
        version=version,
        strategy_version=strategy_version,
        draft_version=draft_version,
        summary_markdown=summary_markdown,
        retained_lessons=retained_lessons,
        created_at=created_at,
    )


def _latest_by_version(items: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not items:
        return None
    return max(items, key=lambda item: _safe_int(item.get("version")) or 0)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _format_missing(label: str) -> str:
    return f"- {label}：暂无记录，本报告只汇总当前项目已有事实。"


def _build_summary_markdown(
    *,
    project: Mapping[str, Any],
    problem_brief: Mapping[str, Any] | None,
    benchmarks: Sequence[Mapping[str, Any]],
    strategy_card: Mapping[str, Any] | None,
    latest_diagnosis: Mapping[str, Any] | None,
    directional_polish_links: Sequence[Mapping[str, Any]],
    drafts: Sequence[Mapping[str, Any]],
    publish_package: Mapping[str, Any] | None,
    retro: Mapping[str, Any] | None,
    retained_lessons: list[RetainedLessonItem],
) -> str:
    lines = [
        "# 创作复盘报告",
        "",
        "## 项目概览",
        f"- 项目：{_text(project.get('title')) or _text(project.get('slug'))}",
        f"- 当前阶段：{_text(project.get('stage')) or '未知'}",
        f"- 当前链路状态：{_text(project.get('current_chain_state')) or '未知'}",
        f"- 草稿版本数：{len(drafts)}",
        "",
        "## 前写作策略",
    ]

    if problem_brief:
        lines.extend(
            [
                f"- 说明书：v{_text(problem_brief.get('version'))} / {_text(problem_brief.get('status')) or 'unknown'}",
                f"- 写作问题：{_text(problem_brief.get('clarified_problem')) or '未记录'}",
                f"- 目标读者：{_text(problem_brief.get('target_reader_situation')) or '未记录'}",
            ]
        )
    else:
        lines.append(_format_missing("问题说明书"))

    if strategy_card:
        lines.extend(
            [
                f"- 策略卡：v{_text(strategy_card.get('version'))} / {_text(strategy_card.get('status')) or 'unknown'}",
                f"- 观点姿态：{_text(strategy_card.get('point_of_view')) or '未记录'}",
                f"- 冲突框架：{_text(strategy_card.get('conflict_frame')) or '未记录'}",
                f"- 情绪路径：{_text(strategy_card.get('emotional_path')) or '未记录'}",
            ]
        )
    else:
        lines.append(_format_missing("策略卡"))

    if benchmarks:
        lines.append("- 对标边界：")
        for benchmark in benchmarks[:5]:
            lines.append(
                f"  - {_text(benchmark.get('reference_label')) or '未命名对标'}：借鉴"
                f"{_text(benchmark.get('borrow_focus')) or '未记录'}；避免"
                f"{_text(benchmark.get('avoid_focus')) or '未记录'}"
            )
    else:
        lines.append(_format_missing("对标参考"))

    lines.extend(["", "## 诊断与修订"])
    if latest_diagnosis:
        lines.extend(
            [
                f"- 最新诊断：v{_text(latest_diagnosis.get('version'))} / 草稿 v{_text(latest_diagnosis.get('draft_version'))}",
                f"- 推荐动作：{_text(latest_diagnosis.get('objective_summary')) or _text(latest_diagnosis.get('recommended_next_action')) or '未记录'}",
                f"- 上游问题：{' / '.join(_string_list(latest_diagnosis.get('upstream_findings'))[:3]) or '暂无明显阻塞'}",
                f"- 表达问题：{' / '.join(_string_list(latest_diagnosis.get('downstream_findings'))[:3]) or '暂无明显阻塞'}",
            ]
        )
    else:
        lines.append(_format_missing("内容诊断"))

    if directional_polish_links:
        lines.append("- 定向精修链路：")
        for link in directional_polish_links[:5]:
            lines.append(
                f"  - 草稿 v{_text(link.get('source_draft_version'))} -> v{_text(link.get('target_draft_version'))}："
                f"{_text(link.get('objective_summary')) or _text(link.get('objective_key')) or '未记录目标'}"
            )
    else:
        lines.append(_format_missing("定向精修链路"))

    lines.extend(["", "## 交付状态"])
    if publish_package:
        lines.extend(
            [
                f"- 发布包：v{_text(publish_package.get('version'))} / {_text(publish_package.get('status')) or 'unknown'}",
                f"- 摘要：{_text(publish_package.get('abstract')) or '未记录'}",
            ]
        )
    else:
        lines.append(_format_missing("发布包"))

    if retro:
        lines.extend(
            [
                f"- 项目复盘：{_text(retro.get('summary')) or '未记录'}",
                f"- 下次重点：{_text(retro.get('next_focus')) or '未记录'}",
            ]
        )
    else:
        lines.append(_format_missing("项目复盘"))

    lines.extend(["", "## 保留经验"])
    for index, lesson in enumerate(retained_lessons, start=1):
        lines.extend(
            [
                f"{index}. {lesson.title}",
                f"   - 类型：{lesson.pattern_type}",
                f"   - 用法：{lesson.intended_use}",
                f"   - 内容：{lesson.pattern_content}",
                f"   - 注意：{lesson.caution_notes}",
            ]
        )

    return "\n".join(lines).strip()


def _build_retained_lessons(
    *,
    project: Mapping[str, Any],
    strategy_card: Mapping[str, Any] | None,
    latest_diagnosis: Mapping[str, Any] | None,
    directional_polish_links: Sequence[Mapping[str, Any]],
    latest_draft: Mapping[str, Any] | None,
    publish_package: Mapping[str, Any] | None,
    retro: Mapping[str, Any] | None,
) -> list[RetainedLessonItem]:
    lessons: list[RetainedLessonItem] = []

    if strategy_card and _text(strategy_card.get("opening_move")):
        lessons.append(
            RetainedLessonItem(
                title="开头动作先于结论",
                pattern_type="opening",
                intended_use="适合下一次处理同类读者处境时，先用动作或场面把读者放进文章。",
                pattern_content=_text(strategy_card.get("opening_move")),
                caution_notes="只复用开头策略，不复用旧稿具体句子。",
            )
        )
    elif strategy_card and _text(strategy_card.get("point_of_view")):
        lessons.append(
            RetainedLessonItem(
                title="先确定观点姿态",
                pattern_type="point_of_view",
                intended_use="适合相近主题进入大纲前，先确定作者站位和叙述姿态。",
                pattern_content=_text(strategy_card.get("point_of_view")),
                caution_notes="姿态可以复用，具体标题、段落和案例需要重新生成。",
            )
        )

    if latest_diagnosis and _text(latest_diagnosis.get("objective_summary")):
        lessons.append(
            RetainedLessonItem(
                title="诊断先定主修方向",
                pattern_type="revision_objective",
                intended_use="适合有初稿但修改发散时，先确定一个最高优先级目标。",
                pattern_content=_text(latest_diagnosis.get("objective_summary")),
                caution_notes="不要把所有问题塞进同一轮精修，先修最影响读者进入和推进的项。",
            )
        )

    latest_link = _latest_directional_link(directional_polish_links)
    if latest_link:
        lessons.append(
            RetainedLessonItem(
                title="保留定向精修链路",
                pattern_type="revision_trace",
                intended_use="适合复盘改稿是否真的服务于诊断目标，而不是只看新稿更顺。",
                pattern_content=(
                    f"草稿 v{_text(latest_link.get('source_draft_version'))} -> "
                    f"v{_text(latest_link.get('target_draft_version'))}："
                    f"{_text(latest_link.get('objective_summary')) or _text(latest_link.get('objective_key'))}"
                ),
                caution_notes="链路用于复盘目标一致性，不代表该表达可跨项目复制。",
            )
        )

    if retro and _string_list(retro.get("wins")):
        lessons.append(
            RetainedLessonItem(
                title="沿用本轮有效做法",
                pattern_type="delivery_win",
                intended_use="适合下次同类项目启动时作为经验提醒。",
                pattern_content=" / ".join(_string_list(retro.get("wins"))[:3]),
                caution_notes="只沿用做法，不沿用旧项目的素材和句子。",
            )
        )

    if not lessons:
        lessons.append(
            RetainedLessonItem(
                title="保留当前项目的复盘入口",
                pattern_type="review_note",
                intended_use="适合旧项目或资料不完整项目，先把已有链路整理出来再判断能否沉淀。",
                pattern_content=(
                    _text(publish_package.get("abstract"))
                    if publish_package
                    else _text(latest_draft.get("title"))
                    if latest_draft
                    else _text(project.get("title"))
                ),
                caution_notes="该条只是复盘入口，不应直接进入可复用模式库。",
            )
        )

    return lessons[:5]


def _latest_directional_link(items: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    if not items:
        return None
    return max(
        items,
        key=lambda item: (
            _safe_int(item.get("target_draft_version")) or 0,
            _safe_int(item.get("diagnosis_version")) or 0,
        ),
    )
