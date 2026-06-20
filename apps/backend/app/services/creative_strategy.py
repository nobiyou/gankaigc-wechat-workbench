from __future__ import annotations

from collections.abc import Mapping
import re

from app.schemas.creative_workflow import (
    BenchmarkReferenceItem,
    ProblemBriefItem,
    StrategyCardItem,
    StrategyPackageResult,
)
from app.services.dbskill_bridge import get_dbskill_rule_lines, merge_unique_lines


_PRESSURE_TOPIC_HARD_SIGNALS = (
    "体检",
    "复查",
    "透析",
    "尿毒症",
    "褥疮",
    "轮椅",
    "身体提醒",
    "身体信号",
    "求救信号",
)
_PRESSURE_TOPIC_BODY_SIGNALS = (
    "身体",
    "休息",
    "自我照料",
    "照顾自己",
    "生活排序",
    "生活接口",
    "身体代价",
    "情绪",
)
_PRESSURE_TOPIC_INTERFACE_SIGNALS = (
    "推迟",
    "往后放",
    "压后",
    "等有空",
    "等忙完",
    "拖延",
    "推后",
    "往后推",
    "往后排",
    "顺延",
    "还能扛",
    "该停了",
    "撤掉",
)
_PRESSURE_TOPIC_CONSEQUENCE_SIGNALS = (
    "胃口变差",
    "作息发乱",
    "没耐心",
    "负荷",
    "疲惫",
    "耗尽",
    "撑住",
    "稳住",
    "倦怠",
    "报警",
    "代价链",
    "坏一点",
    "失衡",
    "追债",
)
_PRESSURE_REFERENCE_HARD_SIGNALS = (
    "尿毒症",
    "褥疮",
    "透析",
    "轮椅",
    "体检",
    "复查",
    "身体提醒",
    "身体信号",
    "求救信号",
)
_PRESSURE_REFERENCE_SOFT_SIGNALS = (
    "身体",
    "疲惫",
    "耗尽",
    "报警",
    "推迟",
    "往后放",
    "照顾好自己",
    "自我照料",
    "休息",
    "工作",
    "家人",
    "失衡",
)
_PRESSURE_REFERENCE_CONSEQUENCE_MARKERS = ("后来", "又开始", "直到", "迟早", "怀念")
_EMOTIONAL_RELEASE_REFERENCE_KEYWORDS = (
    "放下",
    "放手",
    "知足",
    "珍惜",
    "珍惜当下",
    "幸福",
    "幸福是什么",
    "别无所求",
    "不再强求",
    "强求",
    "执念",
    "得不到",
    "不甘心",
    "停止拉扯",
)
_BROAD_EMOTIONAL_RELEASE_STRATEGY_KEYWORDS = (
    "幸福",
    "放下",
    "放手",
    "知足",
    "珍惜",
    "拥有",
    "得不到",
    "不甘心",
    "强求",
    "执念",
    "拉扯",
    "继续投入",
    "投入",
    "停下",
    "松手",
    "舍不得",
    "腾出位置",
    "心力",
)
_BROAD_EMOTIONAL_RELEASE_THESIS_MARKERS = (
    "幸福",
    "放下",
    "放手",
    "知足",
    "珍惜",
    "拥有",
    "误认成",
    "还有希望",
    "更接近幸福",
    "停下也是一种保护",
    "眼前拥有",
    "已经拥有",
    "放手不是失去",
    "不再强求",
    "别无所求",
)
_EVERYDAY_WARMTH_RETURN_ACHIEVEMENT_KEYWORDS = (
    "大事",
    "轰轰烈烈",
    "出人头地",
    "改变世界",
    "赚大钱",
    "住大房子",
    "大公司",
    "大名声",
    "成就",
    "成就叙事",
    "宏大叙事",
    "远大抱负",
    "高楼大厦",
    "灯火辉煌",
)
_EVERYDAY_WARMTH_RETURN_DAILY_KEYWORDS = (
    "人间烟火",
    "陪在爱的人身边",
    "陪爱人",
    "做了一顿晚饭",
    "接孩子",
    "一家老小",
    "热汤",
    "夜灯",
    "晚安",
    "父母",
    "爱人",
    "孩子",
    "回家",
    "小事",
    "微小",
    "细碎",
    "日常瞬间",
    "平淡的日常",
    "陪伴",
    "细水长流",
)
_EVERYDAY_WARMTH_RETURN_THESIS_MARKERS = (
    "最重要的事",
    "祛魅",
    "才属于你我",
    "才是我们的一生",
    "把“大事”放一放",
    "把“小事”捡起来",
    "被“宏大”绑架",
    "被“微小”治愈",
)
_RELATIONSHIP_AFTERCARE_CONFLICT_KEYWORDS = (
    "吵架",
    "争吵",
    "争执",
    "冷暴力",
    "冷战",
    "赌气",
    "闹完",
    "吵完",
    "失望",
    "委屈",
    "误解",
    "不理不睬",
    "情绪发酵",
    "针锋相对",
)
_RELATIONSHIP_AFTERCARE_REPAIR_KEYWORDS = (
    "修复",
    "沟通",
    "接住",
    "回来",
    "主动解决",
    "达成共识",
    "和好",
    "继续走下去",
    "温柔以待",
    "妥协",
    "理解",
    "包容",
    "顺序",
    "回归理性",
)
_RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS = (
    "关系",
    "爱不爱",
    "爱意",
    "两个人",
    "伴侣",
    "婚姻",
    "亲密",
    "安全感",
)
_RELATIONSHIP_AFTERCARE_THESIS_MARKERS = (
    "吵架后的态度",
    "检验爱情的试金石",
    "真正爱你的人",
    "不舍得让你一个人在坏情绪里",
    "不曾对你冷暴力",
    "用爱修复争吵中留下的伤口",
    "不是永远不吵架",
    "争吵以后还想要继续走下去",
    "谁先冷下来谁就算懂事",
    "回避修复",
    "回避税",
)
_RESILIENCE_RECONSTRUCTION_ADVERSITY_KEYWORDS = (
    "韧性",
    "命运",
    "重击",
    "淬炼",
    "凤凰涅槃",
    "车祸",
    "手术台",
    "剧痛",
    "伤痛",
    "残缺",
    "破碎",
    "疼痛",
)
_RESILIENCE_RECONSTRUCTION_TRAINING_KEYWORDS = (
    "残奥",
    "冠军",
    "泳池",
    "游泳",
    "划水",
    "多划11下",
    "11下",
    "训练",
    "肩伤",
    "背痛",
    "炎症",
    "反复重来",
)
_RESILIENCE_RECONSTRUCTION_IDENTITY_KEYWORDS = (
    "不要让任何人",
    "限制你",
    "破碎中重建",
    "不被定义",
    "自己的太阳",
    "破局而上",
    "重新站起来",
)
_RESILIENCE_RECONSTRUCTION_THESIS_MARKERS = (
    "百折不回",
    "真正的强大",
    "完整的人生",
    "一步步生长",
    "不必借光而行",
)
_SUPPORTIVE_HEALTHY_BODY_MARKERS = ("健康的身体", "爱你的家人", "三两好友", "一碗热饭")


def _read_project_value(project: Mapping[str, object], key: str, default: str = "") -> str:
    try:
        value = project[key]
    except (KeyError, IndexError, TypeError):
        value = default
    if value is None:
        return default
    return str(value)


def _count_keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


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
    reference_title = _read_project_value(project, "reference_article_title")
    reference_source_name = _read_project_value(project, "reference_article_source_name", "手动录入")
    reference_summary = _read_project_value(project, "reference_article_summary")
    reference_structure_notes = _read_project_value(project, "reference_article_structure_notes")
    reference_body_markdown = _read_project_value(project, "reference_article_body_markdown")
    pressure_reference_cues = _extract_pressure_reference_cues(reference_body_markdown)
    primary_pressure_cue = _compact_pressure_reference_cue(pressure_reference_cues[0]) if pressure_reference_cues else ""
    secondary_pressure_cue = _compact_pressure_reference_cue(pressure_reference_cues[1]) if len(pressure_reference_cues) > 1 else ""
    tracked_article_scene = _extract_reference_scene(reference_body_markdown)
    reference_shell_signals = _extract_reference_shell_signals(reference_body_markdown)
    structure_mode = _build_structure_mode(
        source_mode=source_mode,
        topic_angle=topic_angle,
        tracked_article_scene=tracked_article_scene,
        reference_body_markdown=reference_body_markdown,
        reference_summary=reference_summary,
    )
    reader_situation = _build_reader_situation(topic_title, topic_angle, structure_mode=structure_mode)
    core_conflict = _build_core_conflict(
        topic_title,
        topic_angle,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
    )
    normalized_topic_angle = _normalize_topic_angle(
        topic_angle=topic_angle,
        topic_title=topic_title,
        source_mode=source_mode,
        structure_mode=structure_mode,
    )
    observed_phenomenon = _build_observed_phenomenon(
        topic_title=topic_title,
        topic_angle=topic_angle,
        trend_title=trend_title,
        source_mode=source_mode,
        tracked_article_scene=tracked_article_scene,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
    )
    writing_goal = _build_writing_goal(
        topic_title=topic_title,
        topic_angle=topic_angle,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
    )
    constraints = _build_problem_constraints(source_mode=source_mode)
    unknowns = _build_unknowns(
        topic_angle=topic_angle,
        source_mode=source_mode,
        tracked_article_scene=tracked_article_scene,
    )
    benchmark_borrow_focus = _build_benchmark_borrow_focus(source_mode, reference_structure_notes, tracked_article_scene)
    benchmark_avoid_focus = _build_benchmark_avoid_focus(source_mode)
    benchmark_summary = _build_benchmark_summary(
        source_mode,
        tracked_article_scene,
        reference_shell_signals,
    )
    point_of_view = _build_point_of_view(
        topic_angle,
        topic_title=topic_title,
        primary_pressure_cue=primary_pressure_cue,
        structure_mode=structure_mode,
    )
    conflict_frame = _build_conflict_frame(
        topic_title,
        topic_angle,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
    )
    emotional_path = _build_emotional_path(
        topic_angle=topic_angle,
        structure_mode=structure_mode,
        pressure_reference_cues=pressure_reference_cues,
    )
    opening_move = _build_opening_move(
        topic_title=topic_title,
        topic_angle=topic_angle,
        tracked_article_scene=tracked_article_scene,
        structure_mode=structure_mode,
        pressure_reference_cues=pressure_reference_cues,
    )
    body_shift = _build_body_shift(
        topic_angle=topic_angle,
        core_conflict=core_conflict,
        structure_mode=structure_mode,
        pressure_reference_cues=pressure_reference_cues,
    )
    ending_move = _build_ending_move(topic_angle=topic_angle, structure_mode=structure_mode)
    recomposition_recipe = _build_recomposition_recipe(
        structure_mode=structure_mode,
        topic_angle=topic_angle,
        reference_shell_signals=reference_shell_signals,
    )
    divergence_axes = _build_divergence_axes(source_mode=source_mode, structure_mode=structure_mode)
    execution_checklist = _build_execution_checklist(
        structure_mode=structure_mode,
        reference_shell_signals=reference_shell_signals,
    )
    expression_constraints = [
        "不要用口号式收尾",
        "不要复用不是A而是B的对称判断句",
        "不要沿用参考文章的开头对象、推进顺序和结尾判断",
    ]
    if structure_mode == "everyday_warmth_return":
        expression_constraints.append("不要把正文重心滑成“长期体谅”“别人继续等你的心气”或“关系坏在冲突之外”这类关系善后判断。")
        expression_constraints.append("不要把手术、停下来或身体受挫写成主要问题，它们只承担价值祛魅的转折证据。")
    if structure_mode == "relationship_aftercare":
        expression_constraints.append("少写“真正伤人的不是……”或“关系不是输在……而是输在……”这类整齐翻转句。")
    if structure_mode == "resilience_reconstruction":
        expression_constraints.append("不要把命运重击和训练重建稿改写成“把自己排回前面”“照顾自己”或“术后恢复”这类自我照料文。")
        expression_constraints.append("不要把人物写成被别人接住的关系稿，主线要留在疼痛、训练和不被定义的重建上。")
    expression_constraints = merge_unique_lines(
        expression_constraints,
        _build_reference_shell_expression_constraints(reference_shell_signals),
    )
    divergence_axes = merge_unique_lines(
        divergence_axes,
        _build_reference_shell_divergence_axes(reference_shell_signals),
    )
    feedback_entry = _build_feedback_entry(
        reader_situation=reader_situation,
        core_conflict=core_conflict,
        topic_title=topic_title,
        topic_angle=topic_angle,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
    )
    problem_explanation = _build_problem_explanation(
        topic_title=topic_title,
        topic_angle=topic_angle,
        observed_phenomenon=observed_phenomenon,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
    )
    problem_statement_markdown = _build_problem_statement_markdown(
        topic_title=topic_title,
        normalized_topic_angle=normalized_topic_angle,
        trend_title=trend_title,
        source_mode=source_mode,
        structure_mode=structure_mode,
        observed_phenomenon=observed_phenomenon,
        writing_goal=writing_goal,
        reader_situation=reader_situation,
        core_conflict=core_conflict,
        constraints=constraints,
        feedback_entry=feedback_entry,
        problem_explanation=problem_explanation,
        reference_title=reference_title,
        reference_source_name=reference_source_name,
        reference_summary=reference_summary,
        tracked_article_scene=tracked_article_scene,
    )
    strategy_markdown = _build_strategy_markdown(
        topic_title=topic_title,
        normalized_topic_angle=normalized_topic_angle,
        source_mode=source_mode,
        reader_situation=reader_situation,
        point_of_view=point_of_view,
        conflict_frame=conflict_frame,
        emotional_path=emotional_path,
        structure_mode=structure_mode,
        opening_move=opening_move,
        body_shift=body_shift,
        ending_move=ending_move,
        recomposition_recipe=recomposition_recipe,
        benchmark_summary=benchmark_summary,
        expression_constraints=expression_constraints,
        divergence_axes=divergence_axes,
        execution_checklist=execution_checklist,
        reference_title=reference_title,
        reference_source_name=reference_source_name,
        benchmark_borrow_focus=benchmark_borrow_focus,
        benchmark_avoid_focus=benchmark_avoid_focus,
        tracked_article_scene=tracked_article_scene,
        reference_shell_signals=reference_shell_signals,
    )
    clarified_problem = _build_clarified_problem(
        topic_title=topic_title,
        topic_angle=topic_angle,
        observed_phenomenon=observed_phenomenon,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
    )

    problem_brief = ProblemBriefItem(
        project_slug=project_slug,
        version=problem_brief_version,
        source_mode=source_mode,
        raw_goal=topic_title,
        clarified_problem=clarified_problem,
        observed_phenomenon=observed_phenomenon,
        writing_goal=writing_goal,
        target_reader_situation=reader_situation,
        core_conflict=core_conflict,
        unknowns=unknowns,
        constraints=constraints,
        feedback_entry=feedback_entry,
        problem_statement_markdown=problem_statement_markdown,
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
            borrow_focus=benchmark_borrow_focus,
            avoid_focus=benchmark_avoid_focus,
            rationale="只借观察路径、冲突组织和节奏职责，不借原标题、现成判断句和段落次序。",
            sort_order=1,
        )
    ]

    strategy_card = StrategyCardItem(
        project_slug=project_slug,
        version=strategy_version,
        problem_brief_version=problem_brief_version,
        reader_situation=reader_situation,
        point_of_view=point_of_view,
        conflict_frame=conflict_frame,
        emotional_path=emotional_path,
        structure_mode=structure_mode,
        opening_move=opening_move,
        body_shift=body_shift,
        ending_move=ending_move,
        recomposition_recipe=recomposition_recipe,
        expression_constraints=expression_constraints,
        divergence_axes=divergence_axes,
        execution_checklist=execution_checklist,
        benchmark_summary=benchmark_summary,
        strategy_markdown=strategy_markdown,
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


def _has_pressure_interface_topic(topic_angle: str) -> bool:
    normalized = topic_angle.strip()
    if not normalized:
        return False
    hard_hits = _count_keyword_hits(normalized, _PRESSURE_TOPIC_HARD_SIGNALS)
    body_hits = _count_keyword_hits(normalized, _PRESSURE_TOPIC_BODY_SIGNALS)
    interface_hits = _count_keyword_hits(normalized, _PRESSURE_TOPIC_INTERFACE_SIGNALS)
    consequence_hits = _count_keyword_hits(normalized, _PRESSURE_TOPIC_CONSEQUENCE_SIGNALS)
    return hard_hits >= 1 or (body_hits >= 1 and (interface_hits >= 1 or consequence_hits >= 1)) or (
        interface_hits >= 1 and consequence_hits >= 1
    )


def _uses_pressure_interface_mode(*, topic_angle: str, structure_mode: str = "") -> bool:
    if structure_mode:
        return structure_mode == "pressure_interface_direct"
    return _has_pressure_interface_topic(topic_angle)


def _has_pressure_interface_summary(reference_summary: str) -> bool:
    normalized = reference_summary.strip()
    if not normalized:
        return False
    pressure_keywords = (
        "身体代价",
        "身体提醒",
        "生活排序",
        "自我照料",
        "自我关照",
        "照顾好自己",
        "内耗",
        "耗尽",
        "疲惫",
        "体检",
        "报警",
    )
    relationship_negations = (
        "不是关系修复",
        "不是关系主线",
        "不在亲密关系沟通里打转",
        "不要写成冷战复合流程",
        "不是关系摊牌",
        "不是沟通修复",
    )
    return any(keyword in normalized for keyword in pressure_keywords) and any(
        phrase in normalized for phrase in relationship_negations
    )


def _has_pressure_interface_reference(reference_body_markdown: str) -> bool:
    normalized = reference_body_markdown.strip()
    if not normalized:
        return False
    hard_hits = _count_keyword_hits(normalized, _PRESSURE_REFERENCE_HARD_SIGNALS)
    soft_hits = _count_keyword_hits(normalized, _PRESSURE_REFERENCE_SOFT_SIGNALS)
    consequence_hits = _count_keyword_hits(normalized, _PRESSURE_REFERENCE_CONSEQUENCE_MARKERS)
    supportive_hits = _count_keyword_hits(normalized, _SUPPORTIVE_HEALTHY_BODY_MARKERS)
    if supportive_hits >= 2 and hard_hits == 0 and consequence_hits == 0:
        return False
    return hard_hits >= 2 or (hard_hits >= 1 and consequence_hits >= 1) or (
        hard_hits == 0 and soft_hits >= 3 and consequence_hits >= 2 and not _has_emotional_release_reference(normalized)
    )


def _has_emotional_release_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    keyword_hits = _count_keyword_hits(corpus, _EMOTIONAL_RELEASE_REFERENCE_KEYWORDS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    return keyword_hits >= 3 and hard_pressure_hits == 0


def _has_everyday_warmth_return_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    achievement_hits = _count_keyword_hits(corpus, _EVERYDAY_WARMTH_RETURN_ACHIEVEMENT_KEYWORDS)
    daily_hits = _count_keyword_hits(corpus, _EVERYDAY_WARMTH_RETURN_DAILY_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _EVERYDAY_WARMTH_RETURN_THESIS_MARKERS)
    return achievement_hits >= 2 and daily_hits >= 3 and thesis_hits >= 1


def _build_reference_summary_for_strategy(
    *,
    structure_mode: str,
    reference_summary: str,
) -> str:
    if structure_mode == "everyday_warmth_return":
        return (
            "参考文围绕成就叙事为什么会在某个阶段失重展开，重点不是复用某个家庭场景，"
            "而是确认：被长期挪后的普通安排、低声量联系和在场动作，为什么会在慢下来以后重新显出分量。"
        )
    return reference_summary


def _has_relationship_aftercare_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    conflict_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_CONFLICT_KEYWORDS)
    repair_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_REPAIR_KEYWORDS)
    relationship_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_THESIS_MARKERS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    return (
        relationship_hits >= 1
        and conflict_hits >= 1
        and repair_hits >= 2
        and (thesis_hits >= 1 or conflict_hits >= 2)
        and hard_pressure_hits == 0
    )


def _has_resilience_reconstruction_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    adversity_hits = _count_keyword_hits(corpus, _RESILIENCE_RECONSTRUCTION_ADVERSITY_KEYWORDS)
    training_hits = _count_keyword_hits(corpus, _RESILIENCE_RECONSTRUCTION_TRAINING_KEYWORDS)
    identity_hits = _count_keyword_hits(corpus, _RESILIENCE_RECONSTRUCTION_IDENTITY_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _RESILIENCE_RECONSTRUCTION_THESIS_MARKERS)
    return adversity_hits >= 2 and training_hits >= 2 and (identity_hits >= 1 or thesis_hits >= 1)


def _uses_broad_emotional_release_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    if structure_mode != "emotional_engine_direct":
        return False
    corpus = " ".join(part.strip() for part in (topic_title, topic_angle) if part and part.strip())
    if not corpus:
        return False
    if _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS) > 0:
        return False
    if any(marker in corpus for marker in ("边界", "开口", "修复", "冷战", "复合", "关系缓回来")):
        return False
    if _has_emotional_release_reference(corpus):
        return True
    keyword_hits = _count_keyword_hits(corpus, _BROAD_EMOTIONAL_RELEASE_STRATEGY_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _BROAD_EMOTIONAL_RELEASE_THESIS_MARKERS)
    return keyword_hits >= 2 and thesis_hits >= 1


def _uses_everyday_warmth_return_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return structure_mode == "everyday_warmth_return"


def _uses_relationship_aftercare_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return structure_mode == "relationship_aftercare"


def _uses_resilience_reconstruction_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return structure_mode == "resilience_reconstruction"


def _extract_pressure_reference_cues(reference_body_markdown: str, *, max_items: int = 3) -> list[str]:
    if not reference_body_markdown.strip():
        return []

    generic_prefixes = ("其实", "人啊", "你每天", "人这一生", "生活从来", "生活，从来", "平日里", "我想", "如果生活")
    generic_phrases = ("这个世界上", "真正的完美", "所谓的完美人生", "生活本身", "真正的自己")

    cues: list[tuple[int, str]] = []
    for block in _extract_reference_blocks(reference_body_markdown):
        sentences = [item.strip() for item in re.split(r"[。！？!?；;\n]", block) if item.strip()]
        for raw_sentence in sentences:
            compact = re.sub(r"\s+", "", raw_sentence).strip()
            if not compact:
                continue
            if any(compact.startswith(prefix) for prefix in generic_prefixes):
                continue
            if any(phrase in compact for phrase in generic_phrases):
                continue
            hard_hits = _count_keyword_hits(compact, _PRESSURE_REFERENCE_HARD_SIGNALS)
            soft_hits = _count_keyword_hits(compact, _PRESSURE_REFERENCE_SOFT_SIGNALS)
            consequence_hits = _count_keyword_hits(compact, _PRESSURE_REFERENCE_CONSEQUENCE_MARKERS)
            if (
                "健康的身体" in compact
                and hard_hits == 0
                and not any(marker in compact for marker in ("改", "拖", "推", "往后", "报警", "提醒", "怀念", "后来", "直到"))
            ):
                continue
            if _has_emotional_release_reference(compact) and hard_hits == 0:
                continue
            if hard_hits == 0 and soft_hits == 0:
                continue
            if hard_hits == 0 and (soft_hits < 2 or consequence_hits == 0):
                continue
            sentence = compact
            if len(sentence) > 42:
                sentence = sentence[:42].rstrip() + "..."
            score = hard_hits * 3 + soft_hits + consequence_hits
            cues.append((score, sentence))

    selected: list[str] = []
    for _, cue in sorted(cues, key=lambda item: (-item[0], len(item[1]))):
        if cue in selected:
            continue
        selected.append(cue)
        if len(selected) >= max_items:
            break
    return selected


def _compact_pressure_reference_cue(cue: str) -> str:
    if not cue:
        return ""
    for part in re.split(r"[，,、]", cue):
        normalized = part.strip()
        if not normalized:
            continue
        if any(keyword in normalized for keyword in ("尿毒症", "褥疮", "透析", "轮椅", "体检", "身体", "疲惫", "耗尽")):
            normalized = re.sub(r"^(后来|几年后|又过了一些年|又过了几年|又过些年|前两年|当初|刚得|要|便|又开始|开始)+", "", normalized)
            return normalized or part.strip()
    return cue[:18].rstrip() + ("..." if len(cue) > 18 else "")


def _build_reader_situation(topic_title: str, topic_angle: str, *, structure_mode: str = "") -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        return "总把休息、体检、吃饭、回复和自己顺手往后挪的人"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "一路追着更大的目标往前跑，后来才发现真正重要的东西一直在身边的人"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "每次吵完都要自己消化情绪、把日子接回去的人"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "被命运或身体限制迎头打过，却还得一次次把自己重新托住的人"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人"
    if "边界" in topic_angle:
        return "在关系里想解释，却越来越不想开口的人"
    if "情绪" in topic_angle:
        return "已经开始耗尽，却还在逼自己继续撑住的人"
    if "自我" in topic_angle:
        return "总觉得应该先把自己稳住，却越稳越累的人"
    return f"正在为“{topic_title}”这类处境反复卡住的人"


def _build_core_conflict(
    topic_title: str,
    topic_angle: str,
    *,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
) -> str:
    if primary_pressure_cue and secondary_pressure_cue and _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        return f"越觉得 `{primary_pressure_cue}` 还能再拖一拖，后面就越容易一路追到 `{secondary_pressure_cue}` 这种更重的代价。"
    if primary_pressure_cue and _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        return f"越觉得 `{primary_pressure_cue}` 还能先压一压，后面越容易把身体和生活一起拖乱。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "越把重要感押在更大的目标上，越容易在一路往前赶的时候，错过那些真正托住自己的陪伴和日常。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "冲突本身未必会让关系散掉，可如果每次吵完都只有一方在善后，安全感就会被一点点磨掉。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正难的，不只是命运下手太重，而是长期疼痛、重复训练和外界定义都在往下拽，人还是得决定不把残缺和低谷收成自己的结论。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "越舍不得停下，越容易把继续消耗误认成认真，最后连眼前真正重要的东西也一起忽略掉。"
    if "边界" in topic_angle:
        return "越想被理解，越容易把真正想说的话咽回去。"
    if "情绪" in topic_angle:
        if primary_pressure_cue:
            return f"越想把 `{primary_pressure_cue}` 这类信号压回去，后面越容易追出更大的身体和生活代价。"
        return "越想赶快恢复正常，越容易忽略身体和情绪已经在报警。"
    if "自我" in topic_angle:
        return "越想证明自己能扛住，越容易把真正的疲惫藏得更深。"
    return f"{topic_title}里最难的是把心里明白的事落回当下，真的动到自己的生活顺序。"


def _build_observed_phenomenon(
    *,
    topic_title: str,
    topic_angle: str,
    trend_title: str,
    source_mode: str,
    tracked_article_scene: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        normalized = f"{topic_title} {topic_angle}"
        if primary_pressure_cue and any(marker in normalized for marker in ("复查", "体检", "拖延", "推后", "还能扛", "该停了", "判断", "求救")):
            return f"`{primary_pressure_cue}` 这种信号已经冒出来了，人却还在把复查、休息和身体判断一次次往后推。"
        if primary_pressure_cue and ("透析" in normalized or secondary_pressure_cue):
            return f"`{primary_pressure_cue}` 这种信号已经冒出来了，人却还在把复查、休息和判断一次次往后压。"
        if primary_pressure_cue:
            return f"`{primary_pressure_cue}` 这种信号已经冒出来了，人却还在把该停下来的那一步继续往后拖。"
        return "很多事会被一次次往后顺延，顺延久了，连该不该停下来都会慢慢判断不准"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多人一路追着更大的目标往前跑，等真正慢下来以后，才突然看见那些最普通的陪伴和日常，原来才是最难被替代的部分"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多关系表面还能照常过下去，可每次争执后的安抚、解释和修复都落在同一个人身上，久了连开口都变得很累"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "有些人不是没有被命运打碎过，而是被打碎以后，还得在长期疼痛、重复训练和别人想替她下定义的目光里，一次次把自己重新托起来"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多人把继续投入误认成还有希望，等到心力、睡眠和眼前拥有的东西一起被透支，才发现自己一直没舍得停下来"
    if source_mode == "tracked_article":
        if "推迟" in topic_angle or "往后放" in topic_angle or "等有空再说" in topic_angle:
            return "很多事会被一次次往后顺延，顺延久了，生活的轻重顺序也会慢慢倒过来"
        if "边界" in topic_angle:
            return "很多人每次想开口时，先想到的都是自己又要被误解，于是那句话就这么收了回去"
        if "情绪" in topic_angle:
            if primary_pressure_cue:
                return f"`{primary_pressure_cue}` 这种信号已经冒出来了，人却还在逼自己装作一切正常"
            return "人已经在日常里明显变慢、变钝、变得不想说话，却还在逼自己装作没事"
        if "自我" in topic_angle:
            return "表面看起来还在正常生活，心里却一直绷着，不敢承认自己已经快撑不住了"
        return f"{topic_title}会在日常里反复出现，像一种总也绕不过去的卡住状态"
    if tracked_article_scene:
        return tracked_article_scene
    if "边界" in topic_angle:
        return "很多人每次想开口时，先想到的都是自己又要被误解，于是那句话就这么收了回去"
    if "情绪" in topic_angle:
        return "人已经在日常里明显变慢、变钝、变得不想说话，却还在逼自己装作没事"
    if "自我" in topic_angle:
        return "表面看起来还在正常生活，心里却一直绷着，不敢承认自己已经快撑不住了"
    if source_mode == "trend":
        return f"{trend_title}这一类处境正在被很多人反复经历，但大多数表达只停在道理层"
    return f"{topic_title}会在日常里反复出现，像一种总也绕不过去的卡住状态"


def _normalize_topic_angle(*, topic_angle: str, topic_title: str, source_mode: str, structure_mode: str = "") -> str:
    normalized = re.sub(r"\s+", " ", topic_angle).strip()
    if not normalized:
        return "未显式提供"
    if source_mode != "tracked_article":
        return normalized
    if structure_mode == "everyday_warmth_return":
        return normalized
    if structure_mode == "relationship_aftercare":
        return normalized
    if structure_mode == "resilience_reconstruction":
        return "从命运重击、长期疼痛和重复训练切入，重点写一个人怎样在反复重来里把身体与意志重新托住，而不是被残缺、低谷和外界定义收走人生。"
    if structure_mode == "emotional_engine_direct":
        return normalized
    if structure_mode == "pressure_interface_direct":
        joined = f"{topic_title} {normalized}"
        if any(keyword in joined for keyword in ("复查", "体检", "拖延", "推后", "还能扛", "该停了", "判断", "求救")):
            return "从已经开始往坏处走的身体提醒切入，重点写复查、休息和自我判断怎样被一再往后推。"
        if "透析" in joined or "尿毒症" in joined or "求救信号" in joined or "压后" in joined:
            return "从已经拖到更重代价的身体信号切入，重点写复查、休息和自我判断是怎样被一再压后的。"
        if "胃口变差" in joined or "作息发乱" in joined or "没耐心" in joined or "负荷" in joined:
            return "从生活接口的长期负荷切入，重点写人为什么会把身体提醒放到所有事情后面。"
        return "从那些已经开始出代价的身体提醒和生活接口切入，重点写人为什么总把该先顾自己的事一再压后。"
    if "透析" in normalized or "尿毒症" in normalized or "求救信号" in normalized or "压后" in normalized:
        return "从已经拖到更重代价的身体信号切入，重点写复查、休息和自我判断是怎样被一再压后的。"
    if any(keyword in normalized for keyword in ("复查", "体检", "拖延", "推后", "还能扛", "该停了")):
        return "从已经开始往坏处走的身体提醒切入，重点写复查、休息和自我判断怎样被一再往后推。"
    if "推迟" in normalized or "往后放" in normalized or "等有空再说" in normalized:
        return "从一再被顺手往后挪开的接口切入，重点写生活顺序怎样被慢慢改写、代价怎样一点点堆出来。"
    if "胃口变差" in normalized or "作息发乱" in normalized or "没耐心" in normalized or "负荷" in normalized:
        return "从生活接口的长期负荷切入，重点写人为什么会把身体提醒放到所有事情后面。"
    if "情绪" in normalized or "报警" in normalized or "耗尽" in normalized:
        return "从身体和日常节奏已经开始变钝的迹象切入，重点写这些提醒怎样被一再压后。"
    if "边界" in normalized or "开口" in normalized or "误解" in normalized or "沟通" in normalized:
        return "从长期失望后的表达退缩切入，重点写人为什么越想被理解越不敢再开口。"
    if "自我" in normalized or "撑住" in normalized or "稳住" in normalized:
        return "从总想把自己绷住的日常代价切入，重点写人为什么越想稳住越累。"
    return f"围绕 `{topic_title}` 重建新的现实入口和推进顺序，不沿用原始说明书的句式、顺序和收束动作。"


def _build_writing_goal(
    *,
    topic_title: str,
    topic_angle: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue and secondary_pressure_cue:
            return f"把 `{primary_pressure_cue}` 怎样一路追到 `{secondary_pressure_cue}` 这种更重代价讲清楚，让读者先认出自己已经在透支什么。"
        if primary_pressure_cue:
            return f"把 `{primary_pressure_cue}` 这种信号为什么会越压越重讲清楚，让读者先认出自己已经在透支什么。"
        return "把那些被顺手往后挪开的接口怎样一步步堆出代价讲清楚，让读者先认出自己已经在透支什么。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把人为什么总把重要感押在更大的目标上讲清楚，也把人慢下来以后，为什么反而会被最普通的陪伴和日常重新托住讲清楚。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把为什么吵架不可怕、吵完以后没人回来接住你才最伤人讲清楚，让读者看见一段关系的分量其实藏在善后态度里。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把人为什么能在命运重击、长期疼痛和重复训练里，一点点把自己重新托住讲清楚，让读者看到韧性不是口号，而是拒绝被残缺和低谷定义。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把人为什么会把继续投入误认成还有希望讲清楚，让读者看见停下不是认输，而是把心力收回来。"
    if "边界" in topic_angle:
        return "把“为什么越想解释越说不出口”讲清楚，让读者看到那种长期失望后的收缩，不再把它误认成矫情。"
    if "情绪" in topic_angle:
        if primary_pressure_cue and secondary_pressure_cue:
            return f"把 `{primary_pressure_cue}` 为什么会一路追到 `{secondary_pressure_cue}` 这种更重代价讲清楚，让读者先意识到这不是一时状态差。"
        if primary_pressure_cue:
            return f"把 `{primary_pressure_cue}` 这种信号为什么不能再当成小事讲清楚，让读者先意识到这已经不是普通疲惫。"
        return "把“为什么人会一点点耗尽”讲清楚，让读者先意识到这已经是身体和情绪在报警，不必再把它误认成偷懒。"
    if "自我" in topic_angle:
        return "把“为什么越想稳住自己越累”讲清楚，让读者愿意先承认疲惫，再谈修复。"
    return f"把 `{topic_title}` 从抽象判断改写成能让读者认出处境、看到代价并获得情绪承接的现实推进。"


def _build_problem_constraints(*, source_mode: str) -> list[str]:
    constraints = [
        "不要写成口号文、模板鸡汤文或标准答案式议论文。",
        "不要做近义词改写，要换观察路径和情绪发动机。",
        "优先把情绪价值落在具体代价、压力接口、触发反应和后续影响上，不要先抽成终局问题或万能答案。",
        "不要靠整段场景描写起稿或凑篇幅，但允许保留 1 到 2 个有情绪功能的动作、物件或现实接口。",
    ]
    if source_mode == "tracked_article":
        constraints.append("参考材料只用于确认赛道和冲突，不得沿用原标题骨架、段落顺序和结尾动作。")
        constraints = merge_unique_lines(
            constraints,
            get_dbskill_rule_lines("strategy", "problem_constraints"),
        )
    return constraints


def _build_clarified_problem(
    *,
    topic_title: str,
    topic_angle: str,
    observed_phenomenon: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue and secondary_pressure_cue:
            return (
                f"真正需要被看见的，是 `{primary_pressure_cue}` 这样的信号为什么会一路拖到 `{secondary_pressure_cue}`，"
                f"中间那些已经开始失衡的生活接口又是怎么被一次次压过去的。"
            )
        if primary_pressure_cue:
            return (
                f"真正需要被看见的，是 `{primary_pressure_cue}` 这样的信号已经冒出来了，"
                f"人却还在把它往后顺延，最后让{observed_phenomenon}慢慢变成日常。"
            )
        return f"真正需要被看见的，是{observed_phenomenon}背后那些被顺手往后挪开的接口，怎样一点点把压力和失衡堆了出来。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正需要被看见的，不是人该不该追求更大的目标，而是为什么很多人要等到慢下来甚至差点错过的时候，才重新承认那些微小陪伴和普通日常才是生活的底座。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正需要被看见的，是为什么一次次争执之后，总是只有一方在回收情绪、重建秩序，关系也就从这里开始慢慢失温。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正需要被看见的，不是一个励志标签，而是为什么有些人明明被命运重击、长期疼痛和训练代价反复碾过，还是会在一次次重来里拒绝把残缺和低谷收成自我定义。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正需要被看见的，不是人人都懂却做不到的道理，而是人为什么明明已经很累了，还是会把不甘心、投入感和希望错当成继续消耗自己的理由。"
    return f"{topic_title}真正需要被看见的，是{observed_phenomenon}里一点点累积出来的压力和失衡。"


def _build_feedback_entry(
    *,
    reader_situation: str,
    core_conflict: str,
    topic_title: str,
    topic_angle: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        anchor = f"`{primary_pressure_cue}` 这样的信号" if primary_pressure_cue else "这些已经被顺手往后挪开的接口"
        consequence = _build_pressure_feedback_consequence(
            topic_title=topic_title,
            topic_angle=topic_angle,
            secondary_pressure_cue=secondary_pressure_cue,
        )
        return (
            f"如果这篇稿子成立，{reader_situation}会先认出“这说的就是我现在的卡点”，"
            f"也会顺着{anchor}看到，自己为什么总把该先顾自己的事拖到更后面，"
            f"{consequence}。"
        )
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"如果这篇稿子成立，{reader_situation}会先认出“这说的就是我现在的卡点”，"
            "也会重新看见，那些不起眼的小事和普通陪伴，并不是附属品，而是自己这些年最该护住的生活底座。"
        )
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"如果这篇稿子成立，{reader_situation}会先认出“这说的就是我现在的卡点”，"
            "也会认出，关系发冷常常就是从每次架后都没人回来接住她开始的。"
        )
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"如果这篇稿子成立，{reader_situation}会先认出“这说的就是我现在的卡点”，"
            "也会认出，真正托住一个人的往往不是一句励志话，而是那些没人替她完成的重复训练和不肯被定义的那股劲。"
        )
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"如果这篇稿子成立，{reader_situation}会先认出“这说的就是我现在的卡点”，"
            "也会意识到自己不是离幸福太远，而是一直把不肯停下误认成更接近幸福。"
        )
    return (
        f"如果这篇稿子成立，{reader_situation}会先认出“这说的就是我现在的卡点”，"
        f"并且能从 `{core_conflict}` 里看到自己为什么一直没能往前走。"
    )


def _build_pressure_feedback_consequence(
    *,
    topic_title: str,
    topic_angle: str,
    secondary_pressure_cue: str = "",
) -> str:
    normalized = f"{topic_title} {topic_angle}"
    if any(marker in normalized for marker in ("判断力", "判断", "求救", "该停了")):
        if secondary_pressure_cue:
            return f"最后连该不该停下来都越来越判断不准，等回过神来，已经拖到 `{secondary_pressure_cue}` 这一步了"
        return "最后连该不该停下来都越来越判断不准"
    if secondary_pressure_cue:
        return f"最后把原本还来得及回头的提醒，一路拖到 `{secondary_pressure_cue}` 这种更难收拾的后果"
    return "最后把原本该早点处理的提醒拖成更难收拾的麻烦"


def _build_problem_explanation(
    *,
    topic_title: str,
    topic_angle: str,
    observed_phenomenon: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue and secondary_pressure_cue:
            return (
                f"这篇稿子要解释的，是为什么 `{primary_pressure_cue}` 这类提醒已经冒头了，"
                f"人还是会继续往后拖，最后一路拖到 `{secondary_pressure_cue}` 这种更重后果。"
            )
        if primary_pressure_cue:
            return (
                f"这篇稿子要解释的，是为什么 `{primary_pressure_cue}` 这类提醒已经出来了，"
                "人还是会把该停下来的那一步继续往后推。"
            )
        return f"这篇稿子要解释的，是为什么{observed_phenomenon}会一遍遍重演。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "这篇稿子要解释的，是为什么很多人明明已经拥有最重要的陪伴和日常，却总要在一路往前赶、差点错过之后，才承认它们才是生活里最难替代的部分。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "这篇稿子要解释的，是为什么在有些关系里，架一吵完，总是同一个人先把话咽回去、把日常接回去，久了以后先退掉的往往是安全感和表达欲。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "这篇稿子要解释的，是为什么人明明已经被命运和疼痛打得很重，还是会在重复训练和反复重来里，不肯把自己交给残缺、低谷和外界定义。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "这篇稿子要解释的，是为什么人明明已经被拖得很累了，还是会把继续投入误认成更接近幸福。"
    return f"这篇稿子要解释的，是为什么{observed_phenomenon}会一遍遍重演，读者真正卡住的那一步到底在哪。"


def _build_unknowns(*, topic_angle: str, source_mode: str, tracked_article_scene: str) -> list[str]:
    unknowns: list[str] = []
    if not topic_angle.strip():
        unknowns.append("切口仍偏泛，大纲阶段要主动收窄到一个更具体的处境。")
    if source_mode == "tracked_article" and not tracked_article_scene:
        unknowns.append("参考材料缺少足够清晰的现实锚点，开头需要自行补出一个更具体的压力接口、后果或身体提醒。")
    return unknowns


def _build_point_of_view(topic_angle: str, *, topic_title: str = "", primary_pressure_cue: str = "", structure_mode: str = "") -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue:
            return f"不急着端出答案，先把 `{primary_pressure_cue}` 这种信号为什么会被一路压后讲清楚。"
        return "不急着端出答案，先把人是怎么一步步把自己往后放讲清楚。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着把文章写成健康告诫或人生箴言，先把那些被高估的大事为什么会慢慢祛魅、普通陪伴为什么反而更重要讲清楚。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着给争吵贴对错，先把吵完以后谁在善后、谁在回避、谁愿不愿意回来修复讲清楚。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着把人物写成励志样板或术后恢复案例，先把命运下手有多重、训练怎样一点点把身体与意志重新托住讲清楚。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着讲知足、放下或清醒的大道理，先把人为什么明明很累却还是不肯松手讲清楚。"
    if "边界" in topic_angle:
        return "不教训，不站高位，只把话为什么越想说越说不出来讲清楚。"
    if "情绪" in topic_angle:
        if primary_pressure_cue:
            return f"不急着给解决方案，先把 `{primary_pressure_cue}` 这种信号为什么会被继续压下去讲清楚。"
        return "不急着给解决方案，先把人为什么会一点点耗尽讲清楚。"
    return "不说教，不站高位，先把读者当下真正卡住的地方讲清楚。"


def _build_conflict_frame(
    topic_title: str,
    topic_angle: str,
    *,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue and secondary_pressure_cue:
            return f"很多失序，都是从 `{primary_pressure_cue}` 被压过去，最后一路追到 `{secondary_pressure_cue}` 这种更重后果开始堆出来的。"
        if primary_pressure_cue:
            return f"很多失序，都是从 `{primary_pressure_cue}` 这种已经冒头的信号被继续压过去开始堆出来的。"
        return "很多失序，都是从那些被反复往后挪开的接口开始堆出来的。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正让人后知后觉的，不是没做成更大的事，而是一路忙着往前赶的时候，把最能托住自己的日常和陪伴慢慢放轻了。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "一段关系会慢慢变冷，常常是因为争执过后，总是同一个人留在原地处理沉默、试探气氛，再把情绪和日常接回去。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正难的，不只是命运下手太重，而是长期疼痛、训练消耗和外界定义都在往下拽，人还得决定自己不被它们收走。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正把人困住的，不是没有答案，而是总把舍不得放手误认成还有希望。"
    if "边界" in topic_angle:
        return "真正把关系拖住的，是一次次想开口又收回去。"
    if "情绪" in topic_angle:
        if primary_pressure_cue and secondary_pressure_cue:
            return f"真正麻烦的，不是人一时状态差，而是 `{primary_pressure_cue}` 已经冒出来了，却还会一路拖到 `{secondary_pressure_cue}` 这种更重后果。"
        if primary_pressure_cue:
            return f"真正麻烦的，不是人一时状态差，而是 `{primary_pressure_cue}` 这种信号已经冒出来了，却还在被继续压下去。"
        return "那些失去电量的迹象，往往很早就开始一点点积着。"
    return f"把 {topic_title} 背后的自我亏欠、失去感和现实压力讲清楚。"


def _build_emotional_path(
    *,
    topic_angle: str,
    structure_mode: str,
    pressure_reference_cues: list[str] | None = None,
) -> str:
    if structure_mode == "pressure_interface_direct":
        cue = (pressure_reference_cues or [None])[0]
        if cue:
            return f"先让读者认出 `{cue}` 这种已经在出代价的信号，再看类似接口怎样一点点堆出更大的失序。"
        return "先让读者认出哪些事被顺手往后挪，再看这些小接口怎样一点点堆出更大的代价。"
    if structure_mode == "everyday_warmth_return":
        return "先认出人为什么总把重要感押在更大的目标上，再看那些普通陪伴和细小日常，是怎样在慢下来以后重新显出分量的。"
    if structure_mode == "relationship_aftercare":
        return "先认出每次吵完最累的地方，其实落在后面那段总要自己把日常接回去的善后，再看人怎样从还想沟通，慢慢退到不想再开口。"
    if structure_mode == "resilience_reconstruction":
        return "先认出命运怎样把人逼到极限，再看她怎样在训练、疼痛和反复重来里一点点把自己重新托住，最后落到不肯被定义上。"
    if structure_mode == "fragment_chain_observation":
        return "先让不同接口里的压力互相照见，再慢慢显出真正被牺牲掉的部分。"
    if _uses_broad_emotional_release_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        return "先认出自己一直在和得不到的东西拉扯，再看为什么人总要等到透支之后才愿意停下。"
    if "边界" in topic_angle:
        return "先认出话为什么总咽回去，再看误解和退缩是怎么积起来的。"
    if "情绪" in topic_angle:
        return "先认出身体和日常节奏已经在变慢，再看这些提醒为什么总被继续往后放。"
    if "自我" in topic_angle:
        return "先认出撑住的代价，再看为什么越想稳住越累。"
    return "先把当下卡点钉住，再顺着触发、反应和后续影响往前推进。"


def _build_opening_move(
    *,
    topic_title: str,
    topic_angle: str,
    tracked_article_scene: str,
    structure_mode: str,
    pressure_reference_cues: list[str] | None = None,
) -> str:
    if structure_mode == "pressure_interface_direct":
        cue = (pressure_reference_cues or [None])[0]
        if cue:
            return f"开头先落 `{cue}` 这种已经开始出代价的接口或身体后果，不要先抛终局问题或价值赦免。"
        return "开头先落一个已经开始出代价的接口：被改期的体检、没吃完的饭、没回的消息，或突然发钝的身体提醒；不要先抛终局问题或价值赦免。"
    if structure_mode == "everyday_warmth_return":
        return "开头先点破“更大的事未必更重要”这种误认，再用一个被长期挪后的普通安排或低声量联系托住判断；不要复述参考文现成的家庭动作，也不要铺成长场景。"
    if structure_mode == "relationship_aftercare":
        return "开头先落一个吵完之后还得照常上班、做饭、回消息，但胸口还紧着的小接口，不要先抽象讲“爱不爱”或“成熟关系”。"
    if structure_mode == "resilience_reconstruction":
        return "开头先落一个命运重击后的硬事实：手术台、泳池里多划11下、肩伤背痛这类抓手，不要先讲励志大道理，也不要滑成术后恢复稿。"
    if structure_mode == "emotional_engine_direct":
        if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
            return "开头不要整段生活场景冷启动，先用一句会让人停一下的误认判断把读者拉进来；需要细节时，只留一个能挂住“继续投入”或“不肯松手”的小接口。"
        return "开头不要整段生活场景冷启动，先用终局问题、反常识判断、情绪命名或价值赦免把读者拉进来；需要细节时，只留能挂住判断的一个小接口。"
    if structure_mode == "fragment_chain_observation":
        if "推迟" in topic_angle or "往后放" in topic_angle or "等有空再说" in topic_angle:
            return "开头先落一个被顺手往后挪开的普通接口：没回的消息、改掉的预约、没吃完的饭或被推迟的电话，不要铺成完整小说场景。"
        return "开头先落一个最小但真实的生活碎片，不要先总括题眼，也不要把场景铺成完整短篇小说。"
    if "推迟" in topic_angle or "往后放" in topic_angle or "等有空再说" in topic_angle:
        return "开头先写一次消息停住、日程改期或身体提醒被顺手往后挪开的瞬间，不要先讲生活排序的大道理。"
    if tracked_article_scene:
        return "开头不要概括主题，先从一个新的生活瞬间切入，但不要复述参考文章现成处境。"
    if "边界" in topic_angle:
        return "开头先写一次想发消息、又删掉重写的瞬间，不要先讲沟通道理。"
    if "情绪" in topic_angle:
        return "开头先写身体或日常节奏出问题的一个小瞬间，不要先给“倦怠”下定义。"
    if "自我" in topic_angle:
        return "开头先写一个人表面平静、心里已经开始发紧的瞬间，不要先讲成长观点。"
    return f"开头先落一个能承住 `{topic_title}` 的具体动作入口。"


def _build_body_shift(
    *,
    topic_angle: str,
    core_conflict: str,
    structure_mode: str,
    pressure_reference_cues: list[str] | None = None,
) -> str:
    if "胃口变差" in topic_angle or "作息发乱" in topic_angle or "没耐心" in topic_angle or "负荷" in topic_angle:
        return "中段先拆生活接口为什么长期超负荷，再讲人为什么会把身体提醒放到所有事情后面。"
    if structure_mode == "pressure_interface_direct":
        cues = pressure_reference_cues or []
        if len(cues) >= 2:
            return f"中段沿着 `{cues[0]}` 到 `{cues[1]}` 这类代价链推进：哪件事先被顺手往后挪，当时怎么处理，后面又怎样追到账上。"
        if cues:
            return f"中段沿着 `{cues[0]}` 这条代价线推进：哪件事先被顺手往后挪，当时怎么处理，后面又留下什么新的失序。"
        return "中段沿着 1 到 2 条压力链推进：哪件事先被顺手往后挪，当时怎么处理，后面又留下什么代价、误差或新的失序。"
    if structure_mode == "everyday_warmth_return":
        return "中段先拆成就、体面、宏大目标为什么会在某个阶段突然祛魅，再把普通陪伴、微小日常和被重新看见的生活分量接回来，让被长期挪后的普通安排、低声量联系和在场动作承担分量回落。"
    if structure_mode == "relationship_aftercare":
        return "中段先写每次吵完谁先把话咽回去、谁先恢复正常、谁先试探气氛，再写长期单人善后怎样让表达欲、期待感和安全感一点点退掉。"
    if structure_mode == "resilience_reconstruction":
        return "中段先拆长期疼痛和训练代价怎样一遍遍逼人重来，再写她为什么没有把残缺、低谷或外界定义收成自我结论。"
    if structure_mode == "emotional_engine_direct":
        if _uses_broad_emotional_release_mode(topic_angle=topic_angle, structure_mode=structure_mode):
            return "中段先拆情绪发动机：人为什么会把继续投入误认成还有希望，又为什么总要等到失去之后才看见已经拥有的部分。"
        return "中段先拆情绪发动机：人为什么总在失去后才懂得拥有，又为什么会把照顾自己放到最后。"
    if structure_mode == "fragment_chain_observation":
        return "中段围绕同一个问题串起 2 到 4 个现实接口，让每个碎片各自承担不同压力：有人际回应，有身体提醒，也有被往后挪开的日常动作，不要平均写成并列分论点。"
    if "边界" in topic_angle:
        return "中段先拆“为什么每次要开口前都先收回去”，再进入关系里的误解是怎么积累的。"
    if "情绪" in topic_angle:
        return "中段先写人是怎么一点点变慢的，再讲为什么她还会误以为自己只是状态不好。"
    if "自我" in topic_angle:
        return "中段先写撑住这件事的代价，再转到为什么这种用力方式会把人拖得更累。"
    return f"中段不要平铺讲道理，要围绕 `{core_conflict}` 完成一次从场景到判断的推进。"


def _build_ending_move(topic_angle: str, structure_mode: str) -> str:
    if structure_mode == "pressure_interface_direct":
        return "结尾回到一个还没完全处理完的普通接口或轻微决定，不抛万能答案，也不写祝福式收束。"
    if structure_mode == "everyday_warmth_return":
        return "结尾回到一个还没完全处理完的普通安排、关系余波或延迟代价上，让分量自然落下来，不要写成小动作清单、身体告诫、口号总结或祝福式收束。"
    if structure_mode == "relationship_aftercare":
        return "结尾回到一个还没被接住的小动作、沉默或没等来的回应上，不要写成万能关系鸡汤。"
    if structure_mode == "resilience_reconstruction":
        return "结尾回到一个还在继续的训练动作、身体余波或不肯松掉的念头上，不写成励志口号，也不写成自我照料宣言。"
    if structure_mode == "emotional_engine_direct":
        if _uses_broad_emotional_release_mode(topic_angle=topic_angle, structure_mode=structure_mode):
            return "结尾给读者一个明确的价值赦免和现实答案：停下来不是失去，是把心力收回来。"
        return "结尾给读者一个明确的价值赦免和现实答案：不必再把自己排到最后。"
    if structure_mode == "fragment_chain_observation":
        return "结尾回到其中一个还没完全处理完的小动作或未回的接口，停在那里，不要写成总结清单、三连问或温柔祝福。"
    if "边界" in topic_angle:
        return "结尾回到一次更小但真实的开口动作，不要写成关系励志口号。"
    if "情绪" in topic_angle:
        return "结尾回到一个允许自己慢下来的动作，不要写成瞬间满血复活。"
    if "自我" in topic_angle:
        return "结尾回到承认疲惫后的一个轻动作，不要写成重新变强的宣言。"
    return "结尾回到人物处境里的一个更小动作，不要口号式升华。"


def _extract_reference_blocks(reference_body_markdown: str) -> list[str]:
    text = reference_body_markdown.strip()
    if not text:
        return []
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        normalized = re.sub(r"^\s{0,3}#{1,6}\s*", "", block).strip()
        if normalized:
            blocks.append(normalized)
    return blocks


def _looks_like_short_banner_block(block: str) -> bool:
    normalized = re.sub(r"\s+", "", block)
    if not (4 <= len(normalized) <= 18):
        return False
    if re.search(r"[。！？!?；;：:，,]", normalized):
        return False
    if normalized.startswith(("“", "\"", "'")):
        return False
    return True


def _has_fragment_chain_source(reference_body_markdown: str) -> bool:
    blocks = _extract_reference_blocks(reference_body_markdown)
    if not blocks:
        return False
    short_banners = sum(1 for block in blocks if _looks_like_short_banner_block(block))
    quoted_lines = sum(
        1
        for line in reference_body_markdown.splitlines()
        if re.match(r"^\s*[\"“].+[\"”]\s*$", line.strip())
    )
    return short_banners >= 3 or (short_banners >= 2 and quoted_lines >= 2)


def _build_structure_mode(
    *,
    source_mode: str,
    topic_angle: str,
    tracked_article_scene: str,
    reference_body_markdown: str,
    reference_summary: str = "",
) -> str:
    normalized = topic_angle.strip()
    if source_mode == "tracked_article":
        shell_signals = _extract_reference_shell_signals(reference_body_markdown)
        reference_has_pressure = _has_pressure_interface_summary(reference_summary) or _has_pressure_interface_reference(
            reference_body_markdown
        )
        reference_is_everyday_warmth_return = _has_everyday_warmth_return_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_body_markdown,
        )
        reference_is_relationship_aftercare = _has_relationship_aftercare_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_body_markdown,
        )
        reference_is_resilience_reconstruction = _has_resilience_reconstruction_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_body_markdown,
        )
        reference_is_emotional_release = _has_emotional_release_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_body_markdown,
        )
        if _has_fragment_chain_source(reference_body_markdown):
            return "fragment_chain_observation"
        if reference_is_everyday_warmth_return:
            return "everyday_warmth_return"
        if reference_is_relationship_aftercare:
            return "relationship_aftercare"
        if reference_is_resilience_reconstruction:
            return "resilience_reconstruction"
        if reference_is_emotional_release and not reference_has_pressure:
            return "emotional_engine_direct"
        if _has_pressure_interface_topic(normalized) or reference_has_pressure or any(
            signal in shell_signals
            for signal in (
                "abstract_reflection_opening",
                "dense_short_conclusion_chain",
                "push_then_moral_chain",
                "quoted_waiting_list",
                "self_check_triplet_closing",
                "blessing_close",
            )
        ):
            return "pressure_interface_direct"
        return "emotional_engine_direct"
    scene_first_keywords = (
        "情绪",
        "耗尽",
        "报警",
        "开口",
        "解释",
        "边界",
        "失望",
        "推迟",
        "往后放",
        "等有空",
        "疲惫",
        "撑住",
        "稳住",
        "倦怠",
    )
    if tracked_article_scene or any(keyword in normalized for keyword in scene_first_keywords):
        return "emotional_engine_direct"
    return "emotional_engine_direct"


def _describe_structure_mode(structure_mode: str) -> tuple[str, str]:
    if structure_mode == "fragment_chain_observation":
        return (
            "碎片回环观察推进",
            "围绕同一个问题串起 2 到 4 个现实接口，让每个碎片承担不同压力，不要压成单主角完整短篇，也不要平均拆成对称分论点。",
        )
    if structure_mode == "everyday_warmth_return":
        return (
            "日常价值回归推进",
            "先拆更大目标为什么会祛魅，再把普通陪伴和细小日常的分量接回来；手术、停下来或身体受挫只承担转折证据，不抢主线。",
        )
    if structure_mode == "relationship_aftercare":
        return (
            "争吵后善后推进",
            "先守住争执过后的空白、沉默或回避接口，再顺着谁先把话咽回去、谁先恢复正常、谁先把场面接回去推进，让安全感变薄这件事从动作里自己显出来。",
        )
    if structure_mode == "resilience_reconstruction":
        return (
            "逆境重建推进",
            "先守住命运重击、身体限制或训练代价，再沿着疼痛、重复训练和拒绝被定义的反抗往前推，不写成术后恢复、自我照料或泛励志鸡汤。",
        )
    if structure_mode == "pressure_interface_direct":
        return (
            "压力接口直推",
            "先压住一个已经开始出代价的现实接口或身体提醒，再沿着触发、当场反应和后续影响推进，不先抛终局判断，也不补万能答案。",
        )
    if structure_mode == "single_window_scene":
        return (
            "单场景窄时窗推进",
            "前半篇尽量守住同一段时间和同一处境现场，不要均匀拆成几个并列观点段。",
        )
    if structure_mode == "emotional_engine_direct":
        return (
            "情绪发动机直接推进",
            "先抽出终局感、亏欠感、失去后的反省和价值赦免，再展开判断与现实答案；默认不靠整段生活场景带路，但允许点状现实细节承重。",
        )
    if structure_mode == "scene_first_progression":
        return (
            "场景优先推进",
            "先让一到两个连续场景带路，再逐步展开判断，不要直接平铺成对称分论点。",
        )
    return ("", "")


def _build_recomposition_recipe(
    *,
    structure_mode: str,
    topic_angle: str,
    reference_shell_signals: list[str] | None = None,
) -> list[str]:
    opening_step = "标题和开头都换成新的现实入口：不用命令句，不直接复述题眼，先让一个具体接口、后果、身体提醒或当下卡点顶上来。"
    middle_step = "中段先把压力是怎么一点点堆起来的讲清楚，再补局部机制；不要按“观点一句 + 解释一句”的标准答案节拍平推。"
    ending_step = "结尾换成新的处境落点：可以停在余波、阻力或还没处理完的接口上，不提问、不列清单，也不要抛万能答案。"

    if structure_mode == "fragment_chain_observation":
        recipe = [
            opening_step,
            "前两段只守住一个被顺手推迟、取消、压下去或没接住的现实接口，不要立刻抬升成总论。",
            "中段改成“主接口继续发酵 + 两到三个回绕碎片补压力”的回环结构，不设并列小标题，不平均分三段讲道理。",
            "只在后半篇补一次机制说明，把为什么会这样贴着前文细节讲透一点，不要每个碎片后都单独补结论。",
            ending_step,
        ]
    elif structure_mode == "pressure_interface_direct":
        recipe = [
            opening_step,
            "前半篇先守住一个已经开始出代价的接口：被改期的体检、没回的消息、被压后的身体提醒，不要立刻抬成整篇总论。",
            "中段沿着 1 到 2 条压力链推进：哪件事先被往后放、当时怎样处理、后来又留下什么新的失序或代价。",
            "需要判断时，把判断压回事实、后果和当场反应里，不要排成“先摆现象，再补道理，再给答案”的成熟讲解稿。",
            ending_step,
        ]
    elif structure_mode == "everyday_warmth_return":
        recipe = [
            opening_step,
            "前半篇先守住“大事 / 成就 / 体面 / 向上奔跑”为什么会慢慢失重，不要一上来就滑进某段关系谁更委屈、谁在长期体谅的善后逻辑。",
            "中段沿着“宏大叙事祛魅 -> 普通陪伴回到视野里 -> 被长期挪后的日常重新显出分量”推进，让低声量联系、普通安排和在场动作承担价值回落，不要回收参考文那组高识别度家庭动作。",
            "不要把身体不适、手术或停下来写成主要问题，它们只负责提供转折证据；也不要把正文改写成“别人还在等你回应”的关系排序稿。",
            ending_step,
        ]
    elif structure_mode == "relationship_aftercare":
        recipe = [
            opening_step,
            "前半篇先守住一次吵完之后的空白、沉默或回避接口，不要立刻抬成“爱不爱”的整篇总论。",
            "中段沿着“谁先把话咽回去 / 谁先恢复正常 / 谁先试探气氛 / 谁把情绪和日常接回去”这条关系代价线推进。",
            "少写“真正伤人的不是……”或“关系不是输在……而是输在……”这类整齐翻转句，判断要压回动作、回避、回应顺序和后续失温里自己长出来。",
            ending_step,
        ]
    elif structure_mode == "resilience_reconstruction":
        recipe = [
            opening_step,
            "前半篇先守住命运重击后的硬事实：手术台、身体限制、训练动作或长期疼痛，不要一上来就抬成励志总论，也不要转成术后恢复或自我照料提醒。",
            "中段沿着“重击留下的代价 -> 重复训练怎样逼人重来 -> 为什么她还是不肯被定义”推进，让疼痛、训练和意志重建彼此咬住。",
            "判断要压回训练动作、身体余波和被命运逼到极限后的选择里，不要写成高位赞美、女性成长口号或万能鼓劲话。",
            ending_step,
        ]
    elif structure_mode == "single_window_scene":
        recipe = [
            opening_step,
            "前半篇尽量守住同一段时间和同一处境现场，只把人物当下怎么卡住写扎实，不急着换第二个案例。",
            "中后段再回看一到两个更早的动作或后续影响，让判断从同一现场里慢慢长出来，不要直接切成并列分论点。",
            "机制说明集中在一次回看或停顿里，不要每推进一段就补一个抽象判断段。",
            ending_step,
        ]
    elif structure_mode == "emotional_engine_direct":
        recipe = [
            opening_step,
            "前半篇不要守生活场景，先守住一个情绪问题：人为什么总把自己放到最后，又为什么失去后才看见当下。",
            "中段用 2 到 4 层推进：终局感、失去链条、自我亏欠、被允许的松绑；每层都要给读者情绪价值。",
            "需要例子时优先保留一句事实、一个后果，或 1 到 2 个有情绪功能的现实细节，并并入判断段；不要展开整段环境和氛围描写，也不要保留只负责摆拍的动作残留段。",
            ending_step,
        ]
    else:
        recipe = [
            opening_step,
            "前半篇先让连续场景带路，再顺着动作、停顿和关系变化带出判断，不要开头第一屏就把道理讲完。",
            middle_step,
            "至少保留一段只停在观察、动作残留、对话碎片或身体反应上，不要让所有段落职责都完全对称。",
            ending_step,
        ]

    shell_signals = reference_shell_signals or []
    if "imperative_title_banner" in shell_signals:
        recipe.append("如果参考标题本身是“别…… / 不要……”式提醒句，你的新标题必须改成情绪发动机入口，不能再像劝告。")
    if "banner_case_banner_case_banner" in shell_signals or "imperative_heading_chain" in shell_signals:
        recipe.append("正文默认不用分节小标题，整篇靠自然段推进；如果出现小标题，必须确保它不是命令句，也不负责替段落下结论。")
    if "self_check_triplet_closing" in shell_signals or "quoted_waiting_list" in shell_signals:
        recipe.append("尾段不要做三连问、三连引语或自查清单；只留一个最小但真实的余波动作。")
    if "blessing_close" in shell_signals:
        recipe.append("最后一句不要写成“愿你 / 愿我们 / 希望你”式抚慰总结，宁可停在普通动作上。")
    if "push_then_moral_chain" in shell_signals:
        recipe.append("不要把整篇排成“先摆现象，再补道理，再给结论”的匀速阶梯，至少打断一次既定节拍。")
    if "推迟" in topic_angle or "往后放" in topic_angle or "等有空再说" in topic_angle:
        recipe.append("如果题眼是推迟或顺延，优先围绕一个被改期、没处理、先放着的接口反复推进，不要扩大成泛人生感悟。")
    return merge_unique_lines(recipe)


def _build_divergence_axes(*, source_mode: str, structure_mode: str) -> list[str]:
    axes = [
        "标题骨架要换成新的现实入口或处境入口",
        "开头入口必须重建，不能复用原文现成判断、反问节拍或命名句",
        "中段推进顺序必须重排，不能照着原文先后关系走",
        "结尾要换成新的处境落点，不能回到原文那种万能答案、祝福或劝告收束",
    ]
    if structure_mode == "fragment_chain_observation":
        axes.append("不要把原文压成一个连续主角场景，要保留多个现实接口之间的散落感和错位感")
    if structure_mode == "single_window_scene":
        axes.append("前半篇尽量守住同一段时间和同一处境现场，不要平均铺开多个平行案例")
    if structure_mode == "emotional_engine_direct":
        axes.append("不要把原创距离理解成换场景，必须换情绪发动机、判断顺序和价值赦免方式")
    if structure_mode == "pressure_interface_direct":
        axes.append("不要把普通接口重新抬成终局问题、人生总结或价值赦免台词，要让代价从过程里自己长出来")
    if structure_mode == "everyday_warmth_return":
        axes.append("不要把小事回归文改写成长期体谅、关系善后或术后恢复自我照料稿，主线必须留在成就祛魅和日常分量回归上")
        axes.append("不要回收参考文里那组高识别度家庭动作，必须另建新的普通安排、低声量联系或在场接口")
    if structure_mode == "relationship_aftercare":
        axes.append("不要把关系修复文改写成泛内耗、自我成长或单人稳情绪稿，主线必须留在吵后谁来善后和谁在回避修复")
    if structure_mode == "resilience_reconstruction":
        axes.append("不要把命运重击和训练重建稿改写成术后恢复、自我照料或泛励志样板文，主线必须留在疼痛、重复训练和不被定义的重建上")
    if source_mode == "tracked_article":
        axes.append("判断句的措辞和情绪转折不能复用参考文章现成表达")
        axes = merge_unique_lines(
            axes,
            get_dbskill_rule_lines("strategy", "divergence_axes"),
        )
    return axes


def _build_execution_checklist(*, structure_mode: str, reference_shell_signals: list[str] | None = None) -> list[str]:
    shell_checks: list[str] = []
    for signal in reference_shell_signals or []:
        if signal == "abstract_reflection_opening":
            shell_checks.append("开头是否避开了抽象反思总论起手，而是真从一个小接口或动作进入。")
        elif signal == "imperative_title_banner":
            shell_checks.append("标题是否已经离开“别…… / 不要……”式提醒句骨架，换成新的处境入口。")
        elif signal == "imperative_heading_chain":
            shell_checks.append("是否拆掉了“别…… / 不要……”式命令型小标题串联，没有照着原文节拍分节。")
        elif signal == "quoted_waiting_list":
            shell_checks.append("是否没有复用原文那种排队式引语或愿望清单。")
        elif signal == "dense_short_conclusion_chain":
            shell_checks.append("是否没有在每个案例后都单独补一句短判断或金句结论。")
        elif signal == "banner_case_banner_case_banner":
            shell_checks.append("是否已经打散“分节标题 - 单个案例 - 独立结论段”的循环骨架。")
        elif signal == "self_check_triplet_closing":
            shell_checks.append("结尾是否没有写成“最近一次……”式自查问卷、三连追问或对号入座清单。")
        elif signal == "blessing_close":
            shell_checks.append("最后一两段是否没有滑回“愿你 / 愿我们 / 希望你”式祝福总结。")
        elif signal == "push_then_moral_chain":
            shell_checks.append("是否没有继续按“摆现象 - 补道理 - 下结论”的匀速阶梯推进。")

    return merge_unique_lines(
        [
            "标题是否已经换成新的现实入口，而不是复述题眼。",
            "开头是否先给一个真实接口、后果或身体提醒，而不是抽象总论起手。",
            "中段是否讲清了哪件事先被往后放、当场怎么处理、后面又留下什么代价。",
            "结尾是否换成新的处境落点，而不是滑回万能答案、劝告或祝福。",
        ]
        + (
            [
                "前半篇是否基本守住同一段时间和同一处境现场，没有平均拆成几个并列观点段。",
            ]
            if structure_mode == "single_window_scene"
            else [
                "是否先压住一个已经开始出代价的接口，再沿着触发、反应和后果推进，而不是一上来就宣布终局道理。",
            ]
            if structure_mode == "pressure_interface_direct"
            else [
                "是否先拆成就祛魅，再把被长期挪后的普通安排、低声量联系和在场动作的分量接回来，而不是滑成长期体谅、关系排序或身体提醒告诫。",
            ]
            if structure_mode == "everyday_warmth_return"
            else [
                "是否先守住吵后空白、沉默或回避接口，再推进谁先把话咽回去、谁先恢复正常、谁在善后，而不是滑成泛自我成长结论或整齐翻转句。",
            ]
            if structure_mode == "relationship_aftercare"
            else [
                "是否先守住命运重击、身体限制或训练代价，再推进重复训练和拒绝被定义，而不是滑成术后恢复、自我照料或泛励志口号。",
            ]
            if structure_mode == "resilience_reconstruction"
            else [
                "是否避开了整段空场景铺陈，同时保留了 1 到 2 个能挂住判断的真实接口，而不是把事实全蒸发成抽象判断。",
            ]
            if structure_mode == "emotional_engine_direct"
            else [
                "是否串起了 2 到 4 个现实接口，并让每个碎片承担不同压力，而不是平均排成几条并列观点。"
            ]
            if structure_mode == "fragment_chain_observation"
            else []
        )
        + shell_checks,
        get_dbskill_rule_lines("strategy", "execution_checklist"),
    )


def _extract_reference_scene(reference_body_markdown: str) -> str:
    text = reference_body_markdown.strip()
    if not text:
        return ""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    for block in blocks:
        normalized = re.sub(r"^\s{0,3}#{1,6}\s*", "", block).strip()
        if not normalized:
            continue
        if len(normalized) <= 80:
            return normalized
        return normalized[:80].rstrip() + "..."
    return ""


def _extract_reference_shell_signals(reference_body_markdown: str) -> list[str]:
    text = reference_body_markdown.strip()
    if not text:
        return []

    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    normalized_blocks = [_strip_markdown_label(block) for block in blocks if _strip_markdown_label(block)]
    signals: list[str] = []
    title_match = re.search(r"^\s{0,3}#\s*(.+?)\s*$", reference_body_markdown, re.MULTILINE)
    title_text = title_match.group(1).strip() if title_match else ""

    first_substantive_block = next(
        (
            block
            for block in normalized_blocks
            if len(block) >= 16 or any(token in block for token in ("。", "，", "？", "！", "“", "”"))
        ),
        "",
    )
    if first_substantive_block:
        first_block = first_substantive_block
        if len(first_block) >= 10 and any(token in first_block for token in ("如果当初", "总在", "才懂得", "才想起", "才明白")):
            signals.append("abstract_reflection_opening")
    if title_text and title_text.startswith(("别", "不要", "别把", "别用", "别等")):
        signals.append("imperative_title_banner")

    short_heading_blocks = [block for block in normalized_blocks if 4 <= len(block) <= 12 and "。" not in block and "，" not in block]
    imperative_headings = [
        block for block in short_heading_blocks if any(block.startswith(prefix) for prefix in ("别", "不要", "别把", "别用", "别等"))
    ]
    if len(imperative_headings) >= 2:
        signals.append("imperative_heading_chain")

    quote_like_lines = 0
    for block in normalized_blocks:
        if "“等" in block or "等有钱了" in block or "等忙完" in block or "等退休了" in block:
            quote_like_lines += 1
    if quote_like_lines >= 2:
        signals.append("quoted_waiting_list")

    short_conclusion_blocks = [
        block
        for block in normalized_blocks
        if len(block) <= 26 and any(token in block for token in ("最", "真正", "有些", "人生", "生活", "幸福", "遗憾"))
    ]
    if len(short_conclusion_blocks) >= 3:
        signals.append("dense_short_conclusion_chain")

    if len(imperative_headings) >= 3 and len(short_conclusion_blocks) >= 2:
        signals.append("banner_case_banner_case_banner")
    if text.count("最近一次") >= 2 or ("想看的风景" in text and "想见的人" in text):
        signals.append("self_check_triplet_closing")
    if re.search(r"(愿你|愿我们|希望你|希望我们).{0,18}(都能|不再|可以)", text):
        signals.append("blessing_close")
    if len(short_conclusion_blocks) >= 2 and len(normalized_blocks) >= 7:
        signals.append("push_then_moral_chain")

    return signals


def _strip_markdown_label(block: str) -> str:
    return re.sub(r"^\s{0,3}#{1,6}\s*", "", block).replace("\n", " ").strip()


def _build_reference_shell_expression_constraints(reference_shell_signals: list[str]) -> list[str]:
    constraints: list[str] = []
    if "abstract_reflection_opening" in reference_shell_signals:
        constraints.append("不要沿用“深夜独处时 / 如果当初 / 我们总在……”这类抽象反思开头，直接从当下接口或动作切入。")
    if "imperative_title_banner" in reference_shell_signals:
        constraints.append("标题不要沿用“别…… / 不要……”式提醒句或训诫句，换成具体处境、动作断面或现实接口。")
    if "imperative_heading_chain" in reference_shell_signals:
        constraints.append("不要把正文切成一串“别…… / 不要……”式命令型小标题，章节关系要换成新的处境推进。")
    if "quoted_waiting_list" in reference_shell_signals:
        constraints.append("不要复用“等有钱了 / 等忙完 / 等退休了”这类排队式引语清单，换成新的现实接口。")
    if "dense_short_conclusion_chain" in reference_shell_signals:
        constraints.append("不要连续插入很多 1 到 2 句的价值判断小段，尤其不要每写完一个案例就单独敲一句结论。")
    if "banner_case_banner_case_banner" in reference_shell_signals:
        constraints.append("不要沿用“标题式分节 + 案例 + 总结句”三连壳子，至少拆掉其中两层。")
    if "self_check_triplet_closing" in reference_shell_signals:
        constraints.append("结尾不要写成“最近一次……”式自查问卷、三连追问或对号入座清单。")
    if "blessing_close" in reference_shell_signals:
        constraints.append("结尾不要再补“愿你 / 愿我们 / 希望你”式祝福或抚慰总结。")
    if "push_then_moral_chain" in reference_shell_signals:
        constraints.append("不要把整篇推进写成“摆现象 - 补道理 - 下结论”的匀速阶梯，至少打断一次节拍。")
    return constraints


def _build_reference_shell_divergence_axes(reference_shell_signals: list[str]) -> list[str]:
    axes: list[str] = []
    if "abstract_reflection_opening" in reference_shell_signals:
        axes.append("开头入口不能继续走抽象反思 + 普遍感慨，要改成更小、更近、更当下的动作入口")
    if "imperative_title_banner" in reference_shell_signals:
        axes.append("标题不能继续沿用提醒句或训诫句骨架，要换成新的情绪发动机入口")
    if "imperative_heading_chain" in reference_shell_signals:
        axes.append("中段结构不能照搬命令式小标题串联，要改成新的问题推进或接口回环")
    if "quoted_waiting_list" in reference_shell_signals:
        axes.append("不要复用原文那种三连引语或愿望清单壳子，引用型排队结构必须换掉")
    if "dense_short_conclusion_chain" in reference_shell_signals:
        axes.append("不能每推进一节就补一个短判断段，结论密度要明显低于原文")
    if "banner_case_banner_case_banner" in reference_shell_signals:
        axes.append("整篇不能再走“分节标题 - 单个案例 - 独立结论段”的循环骨架")
    if "self_check_triplet_closing" in reference_shell_signals:
        axes.append("尾段不能再走三连追问或自查清单壳子，要收在一个单独动作或余波上")
    if "blessing_close" in reference_shell_signals:
        axes.append("最后一段不能靠祝福或抚慰总结收尾，要改成普通动作留下的余波")
    if "push_then_moral_chain" in reference_shell_signals:
        axes.append("中后段不要继续按“摆现象 - 补道理 - 下结论”的匀速台阶推进")
    return axes


def _build_benchmark_borrow_focus(source_mode: str, structure_notes: str, tracked_article_scene: str) -> str:
    parts: list[str] = []
    if tracked_article_scene:
        parts.append("原文压力类型和情绪发动机")
    if structure_notes:
        parts.append("段落职责分配")
    if source_mode == "tracked_article":
        parts.append("中段情绪推进和价值赦免节奏")
    else:
        parts.append("开头先给问题再推进判断的节奏")
    return " / ".join(parts) if parts else "观察路径和段落职责"


def _build_benchmark_avoid_focus(source_mode: str) -> str:
    if source_mode == "tracked_article":
        return "不要复用原标题骨架、原文判断句、段落顺序和结尾收束"
    return "不要复用现成判断句、整齐反转和口号式结尾"


def _build_benchmark_summary(source_mode: str, tracked_article_scene: str, reference_shell_signals: list[str] | None = None) -> str:
    if source_mode == "tracked_article" and tracked_article_scene:
        summary = "只借原文对应的生活压力类型和情绪发动机，不借原文标题、首段场景、推进顺序和结尾动作。"
    elif source_mode == "tracked_article":
        summary = "只借赛道冲突和观察路径，不借现成表达和段落次序。"
    else:
        return "开头先落动作和停顿，中段再进入判断。"

    shell_signals = reference_shell_signals or []
    if "banner_case_banner_case_banner" in shell_signals or "imperative_heading_chain" in shell_signals:
        summary += " 原文如果自带命令式分节和案例轮转壳子，也只借压力类型，不借那套外壳。"
    if "abstract_reflection_opening" in shell_signals:
        summary += " 原文开头如果先抽象反思，也不能继续沿用那种总论起手。"
    if "quoted_waiting_list" in shell_signals:
        summary += " 原文如果用了排队式引语清单，也必须整体换掉。"
    if "imperative_title_banner" in shell_signals:
        summary += " 原文标题如果本身像提醒句，新标题也必须换掉那层训诫骨架。"
    if "self_check_triplet_closing" in shell_signals:
        summary += " 原文如果用三连追问或自查问卷收尾，尾段也不能再走那条路。"
    if "blessing_close" in shell_signals:
        summary += " 原文如果以祝福式抚慰收束，新稿必须改成普通动作或余波式结尾。"
    return summary


def _build_problem_statement_markdown(
    *,
    topic_title: str,
    normalized_topic_angle: str,
    trend_title: str,
    source_mode: str,
    structure_mode: str,
    observed_phenomenon: str,
    writing_goal: str,
    reader_situation: str,
    core_conflict: str,
    constraints: list[str],
    feedback_entry: str,
    problem_explanation: str,
    reference_title: str,
    reference_source_name: str,
    reference_summary: str,
    tracked_article_scene: str,
) -> str:
    lines = [
        "# 问题说明书",
        "",
        f"## 原始目标",
        f"- 选题：{topic_title}",
        f"- 切口：{normalized_topic_angle}",
        "",
        "## 现象",
        f"- {observed_phenomenon}",
        f"- 目标读者：{reader_situation}",
        "",
        "## 目标",
        f"- {writing_goal}",
        "",
        "## 核心冲突",
        f"- {core_conflict}",
        "",
        "## 这篇稿子真正要解释什么",
        f"- {problem_explanation}",
        "",
        "## 约束",
    ]
    for constraint in constraints:
        lines.append(f"- {constraint}")
    lines.extend(
        [
            "",
            "## 反馈入口",
            f"- {feedback_entry}",
        ]
    )
    if source_mode == "tracked_article":
        reference_summary_for_strategy = _build_reference_summary_for_strategy(
            structure_mode=structure_mode,
            reference_summary=reference_summary,
        )
        lines.extend(
            [
                "",
                "## 参考材料只承担什么作用",
                f"- 来源：{reference_source_name or '手动录入'}",
                f"- 原文标题：{reference_title or '无'}",
                f"- 原文摘要线索：{reference_summary_for_strategy or '无'}",
                "- 可借的情绪线索：只借原文的压力类型、价值转向和情绪发动机，不借可识别的现成场景或家庭动作。",
                "- 参考材料只用于确认赛道、冲突和读者处境，不得沿用原标题骨架、段落顺序、论断次序和结尾动作。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## 来源线索",
                f"- 当前来源主题：{trend_title}",
                "- 来源线索只用于确认现实处境，不自动决定标题骨架和段落顺序。",
            ]
        )
    return "\n".join(lines)


def _build_strategy_markdown(
    *,
    topic_title: str,
    normalized_topic_angle: str,
    source_mode: str,
    reader_situation: str,
    point_of_view: str,
    conflict_frame: str,
    emotional_path: str,
    structure_mode: str,
    opening_move: str,
    body_shift: str,
    ending_move: str,
    recomposition_recipe: list[str],
    benchmark_summary: str,
    expression_constraints: list[str],
    divergence_axes: list[str],
    execution_checklist: list[str],
    reference_title: str,
    reference_source_name: str,
    benchmark_borrow_focus: str,
    benchmark_avoid_focus: str,
    tracked_article_scene: str,
    reference_shell_signals: list[str],
) -> str:
    structure_label, structure_execution = _describe_structure_mode(structure_mode)
    lines = [
        "# 创作策略卡",
        "",
        "## 写给谁",
        f"- {reader_situation}",
        "",
        "## 这篇稿子站在什么位置说话",
        f"- {point_of_view}",
        "",
        "## 冲突怎么立",
        f"- {conflict_frame}",
        "",
        "## 情绪推进",
        f"- {emotional_path}",
        "",
    ]
    if structure_label:
        lines.extend(
            [
                "## 结构模式",
                f"- {structure_label}",
                f"- 结构执行：{structure_execution}",
                "",
            ]
        )
    lines.extend(
        [
            "## 开头 / 中段 / 结尾动作",
            f"- 开头：{opening_move}",
            f"- 中段：{body_shift}",
            f"- 结尾：{ending_move}",
            "",
            "## 替代骨架",
        ]
    )
    for item in recomposition_recipe:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 表达约束",
        ]
    )
    for item in expression_constraints:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 对标与借用边界",
            f"- 可借：{benchmark_borrow_focus}",
            f"- 不借：{benchmark_avoid_focus}",
            f"- 基准总结：{benchmark_summary}",
            "",
            "## 主动拉开距离的维度",
        ]
    )
    for axis in divergence_axes:
        lines.append(f"- {axis}")
    lines.extend(
        [
            "",
            "## 执行检查清单",
        ]
    )
    for item in execution_checklist:
        lines.append(f"- {item}")
    if source_mode == "tracked_article":
        lines.extend(
            [
                "",
                "## 参考文章消化说明",
                f"- 来源账号：{reference_source_name or '手动录入'}",
                f"- 参考标题：{reference_title or '无'}",
                "- 可借的原文情绪线索：只借原文的压力类型、价值转向和情绪发动机，不借可识别的现成场景或家庭动作。",
                "- 必须主动拉开距离的维度：标题骨架、开头入口、中段顺序、结尾落点。",
            ]
        )
        if reference_shell_signals:
            lines.append(
                "- 这篇参考文自带的高风险外壳也不能复用："
                + " / ".join(_build_reference_shell_divergence_axes(reference_shell_signals)[:3])
            )
    if normalized_topic_angle and normalized_topic_angle != "未显式提供":
        lines.extend(
            [
                "",
                "## 本次优先强化",
                f"- 把 `{normalized_topic_angle}` 做成读者能认出处境、看到代价并获得情绪承接的现实推进，而不是停在句式替换上。",
            ]
        )
    return "\n".join(lines)
