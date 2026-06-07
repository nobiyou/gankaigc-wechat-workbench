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
    reference_title = _read_project_value(project, "reference_article_title")
    reference_source_name = _read_project_value(project, "reference_article_source_name", "手动录入")
    reference_summary = _read_project_value(project, "reference_article_summary")
    reference_structure_notes = _read_project_value(project, "reference_article_structure_notes")
    reference_body_markdown = _read_project_value(project, "reference_article_body_markdown")
    reader_situation = _build_reader_situation(topic_title, topic_angle)
    core_conflict = _build_core_conflict(topic_title, topic_angle)
    tracked_article_scene = _extract_reference_scene(reference_body_markdown)
    reference_shell_signals = _extract_reference_shell_signals(reference_body_markdown)
    normalized_topic_angle = _normalize_topic_angle(
        topic_angle=topic_angle,
        topic_title=topic_title,
        source_mode=source_mode,
    )
    observed_phenomenon = _build_observed_phenomenon(
        topic_title=topic_title,
        topic_angle=topic_angle,
        trend_title=trend_title,
        source_mode=source_mode,
        tracked_article_scene=tracked_article_scene,
    )
    writing_goal = _build_writing_goal(topic_title=topic_title, topic_angle=topic_angle)
    constraints = _build_problem_constraints(source_mode=source_mode)
    feedback_entry = _build_feedback_entry(reader_situation=reader_situation, core_conflict=core_conflict)
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
    point_of_view = _build_point_of_view(topic_angle)
    conflict_frame = _build_conflict_frame(topic_title, topic_angle)
    emotional_path = "先建立终局感或亏欠感，再给读者一个被理解、被松绑、被允许照顾自己的出口。"
    structure_mode = _build_structure_mode(
        source_mode=source_mode,
        topic_angle=topic_angle,
        tracked_article_scene=tracked_article_scene,
        reference_body_markdown=reference_body_markdown,
    )
    opening_move = _build_opening_move(
        topic_title=topic_title,
        topic_angle=topic_angle,
        tracked_article_scene=tracked_article_scene,
        structure_mode=structure_mode,
    )
    body_shift = _build_body_shift(
        topic_angle=topic_angle,
        core_conflict=core_conflict,
        structure_mode=structure_mode,
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
    expression_constraints = merge_unique_lines(
        expression_constraints,
        _build_reference_shell_expression_constraints(reference_shell_signals),
    )
    divergence_axes = merge_unique_lines(
        divergence_axes,
        _build_reference_shell_divergence_axes(reference_shell_signals),
    )
    problem_statement_markdown = _build_problem_statement_markdown(
        topic_title=topic_title,
        normalized_topic_angle=normalized_topic_angle,
        trend_title=trend_title,
        source_mode=source_mode,
        observed_phenomenon=observed_phenomenon,
        writing_goal=writing_goal,
        reader_situation=reader_situation,
        core_conflict=core_conflict,
        constraints=constraints,
        feedback_entry=feedback_entry,
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

    problem_brief = ProblemBriefItem(
        project_slug=project_slug,
        version=problem_brief_version,
        source_mode=source_mode,
        raw_goal=topic_title,
        clarified_problem=(
            f"这篇文章要解释，{topic_title}背后真正需要被看见的，"
            f"是{observed_phenomenon}里一点点累积出来的压力和失衡。"
        ),
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
    return f"{topic_title}里最难的是把心里明白的事落回当下，真的动到自己的生活顺序。"


def _build_observed_phenomenon(
    *,
    topic_title: str,
    topic_angle: str,
    trend_title: str,
    source_mode: str,
    tracked_article_scene: str,
) -> str:
    if source_mode == "tracked_article":
        if "推迟" in topic_angle or "往后放" in topic_angle or "等有空再说" in topic_angle:
            return "很多事会被一次次往后顺延，顺延久了，生活的轻重顺序也会慢慢倒过来"
        if "边界" in topic_angle:
            return "很多人每次想开口时，先想到的都是自己又要被误解，于是那句话就这么收了回去"
        if "情绪" in topic_angle:
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


def _normalize_topic_angle(*, topic_angle: str, topic_title: str, source_mode: str) -> str:
    normalized = re.sub(r"\s+", " ", topic_angle).strip()
    if not normalized:
        return "未显式提供"
    if source_mode != "tracked_article":
        return normalized
    if "推迟" in normalized or "往后放" in normalized or "等有空再说" in normalized:
        return "从人生有限和长期亏欠自己的矛盾切入，重点写“推迟”怎样慢慢改写一个人的生活排序。"
    if "胃口变差" in normalized or "作息发乱" in normalized or "没耐心" in normalized or "负荷" in normalized:
        return "从生活接口的长期负荷切入，重点写人为什么会把身体提醒放到所有事情后面。"
    if "情绪" in normalized or "报警" in normalized or "耗尽" in normalized:
        return "从身体报警背后的自我亏欠感切入，重点写人为什么会把长期透支误认成暂时状态不好。"
    if "边界" in normalized or "开口" in normalized or "误解" in normalized or "沟通" in normalized:
        return "从长期失望后的表达退缩切入，重点写人为什么越想被理解越不敢再开口。"
    if "自我" in normalized or "撑住" in normalized or "稳住" in normalized:
        return "从总想撑住自己背后的亏欠感切入，重点写人为什么越想稳住越累。"
    return f"围绕 `{topic_title}` 重建新的情绪发动机，不沿用原始说明书的句式、顺序和收束动作。"


def _build_writing_goal(*, topic_title: str, topic_angle: str) -> str:
    if "边界" in topic_angle:
        return "把“为什么越想解释越说不出口”讲清楚，让读者看到那种长期失望后的收缩，不再把它误认成矫情。"
    if "情绪" in topic_angle:
        return "把“为什么人会一点点耗尽”讲清楚，让读者先意识到这已经是身体和情绪在报警，不必再把它误认成偷懒。"
    if "自我" in topic_angle:
        return "把“为什么越想稳住自己越累”讲清楚，让读者愿意先承认疲惫，再谈修复。"
    return f"把 `{topic_title}` 从抽象判断改写成能让读者被看见、被松绑或被提醒的情绪发动机。"


def _build_problem_constraints(*, source_mode: str) -> list[str]:
    constraints = [
        "不要写成口号文、模板鸡汤文或标准答案式议论文。",
        "不要做近义词改写，要换观察路径和情绪发动机。",
        "优先提炼终局感、亏欠感、失去后的反省、被允许的松绑或现实答案。",
        "原则上删除场景描写，不把动作、空间、物件或生活表面当成正文入口。",
    ]
    if source_mode == "tracked_article":
        constraints.append("参考材料只用于确认赛道和冲突，不得沿用原标题骨架、段落顺序和结尾动作。")
        constraints = merge_unique_lines(
            constraints,
            get_dbskill_rule_lines("strategy", "problem_constraints"),
        )
    return constraints


def _build_feedback_entry(*, reader_situation: str, core_conflict: str) -> str:
    return (
        f"如果这篇稿子成立，{reader_situation}会先认出“这说的就是我现在的卡点”，"
        f"并且能从 `{core_conflict}` 里看到自己为什么一直没能往前走。"
    )


def _build_unknowns(*, topic_angle: str, source_mode: str, tracked_article_scene: str) -> list[str]:
    unknowns: list[str] = []
    if not topic_angle.strip():
        unknowns.append("切口仍偏泛，大纲阶段要主动收窄到一个更具体的处境。")
    if source_mode == "tracked_article" and not tracked_article_scene:
        unknowns.append("参考材料缺少足够清晰的情绪发动机，开头需要自行重建终局问题、亏欠感或价值赦免。")
    return unknowns


def _build_point_of_view(topic_angle: str) -> str:
    if "边界" in topic_angle:
        return "不教训，不站高位，只把话为什么越想说越说不出来讲清楚。"
    if "情绪" in topic_angle:
        return "不急着给解决方案，先把人为什么会一点点耗尽讲清楚。"
    return "不说教，不站高位，先把读者当下真正卡住的地方讲清楚。"


def _build_conflict_frame(topic_title: str, topic_angle: str) -> str:
    if "边界" in topic_angle:
        return "真正把关系拖住的，是一次次想开口又收回去。"
    if "情绪" in topic_angle:
        return "那些失去电量的迹象，往往很早就开始一点点积着。"
    return f"把 {topic_title} 背后的自我亏欠、失去感和现实压力讲清楚。"


def _build_opening_move(*, topic_title: str, topic_angle: str, tracked_article_scene: str, structure_mode: str) -> str:
    if structure_mode == "emotional_engine_direct":
        return "开头不要生活场景冷启动，先用终局问题、反常识判断、情绪命名或价值赦免把读者拉进来。"
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


def _build_body_shift(*, topic_angle: str, core_conflict: str, structure_mode: str) -> str:
    if "胃口变差" in topic_angle or "作息发乱" in topic_angle or "没耐心" in topic_angle or "负荷" in topic_angle:
        return "中段先拆生活接口为什么长期超负荷，再讲人为什么会把身体提醒放到所有事情后面。"
    if structure_mode == "emotional_engine_direct":
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
    if structure_mode == "emotional_engine_direct":
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
) -> str:
    normalized = topic_angle.strip()
    if source_mode == "tracked_article":
        if _has_fragment_chain_source(reference_body_markdown):
            return "fragment_chain_observation"
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
    if structure_mode == "single_window_scene":
        return (
            "单场景窄时窗推进",
            "前半篇尽量守住同一段时间和同一处境现场，不要均匀拆成几个并列观点段。",
        )
    if structure_mode == "emotional_engine_direct":
        return (
            "情绪发动机直接推进",
            "先抽出终局感、亏欠感、失去后的反省和价值赦免，再展开判断与现实答案；默认不铺生活场景。",
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
    opening_step = "标题和开头都改成情绪发动机入口：不用命令句，不用生活场景冷启动，先给终局问题、反常识判断或情绪命名。"
    middle_step = "中段先拆为什么会亏欠自己、为什么会失去后才懂得拥有，再补现实机制；不要按“观点一句 + 解释一句”的标准答案节拍平推。"
    ending_step = "结尾给明确的价值赦免和现实答案，不提问、不列清单，也不要靠生活小动作收束。"

    if structure_mode == "fragment_chain_observation":
        recipe = [
            opening_step,
            "前两段只守住一个被顺手推迟、取消、压下去或没接住的现实接口，不要立刻抬升成总论。",
            "中段改成“主接口继续发酵 + 两到三个回绕碎片补压力”的回环结构，不设并列小标题，不平均分三段讲道理。",
            "只在后半篇补一次机制说明，把为什么会这样贴着前文细节讲透一点，不要每个碎片后都单独补结论。",
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
            "需要例子时只保留一句事实或引用，并并入判断段；不展开动作、物件、环境和氛围描写，也不单独保留动作残留段。",
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
        "标题骨架要换成新的情绪发动机入口",
        "开头不能换成新的动作、空间或物件，要换成终局问题、反常识判断或情绪命名",
        "中段推进顺序必须重排，不能照着原文先后关系走",
        "结尾要改成新的价值赦免或现实答案，不能只换一个小动作收束",
    ]
    if structure_mode == "fragment_chain_observation":
        axes.append("不要把原文压成一个连续主角场景，要保留多个现实接口之间的散落感和错位感")
    if structure_mode == "single_window_scene":
        axes.append("前半篇尽量守住同一段时间和同一处境现场，不要平均铺开多个平行案例")
    if structure_mode == "emotional_engine_direct":
        axes.append("不要把原创距离理解成换场景，必须换情绪发动机、判断顺序和价值赦免方式")
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
            "标题是否已经换成新的情绪发动机入口，而不是复述题眼。",
            "开头是否先给终局问题、反常识判断或情绪命名，而不是生活场景。",
            "中段是否讲清了亏欠自己、失去后才懂得拥有或被允许松绑的情绪机制。",
            "结尾是否给出价值赦免或现实答案，而不是只换一个小动作收束。",
        ]
        + (
            [
                "前半篇是否基本守住同一段时间和同一处境现场，没有平均拆成几个并列观点段。",
            ]
            if structure_mode == "single_window_scene"
            else [
                "是否默认删除场景描写，没有连续铺动作、物件、环境和氛围。",
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
    observed_phenomenon: str,
    writing_goal: str,
    reader_situation: str,
    core_conflict: str,
    constraints: list[str],
    feedback_entry: str,
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
        f"- 不是再讲一遍大家都知道的正确道理，而是讲清楚：`{topic_title}` 为什么会慢慢发生，读者当下到底卡在什么地方。",
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
        lines.extend(
            [
                "",
                "## 参考材料只承担什么作用",
                f"- 来源：{reference_source_name or '手动录入'}",
                f"- 原文标题：{reference_title or '无'}",
                f"- 原文摘要线索：{reference_summary or '无'}",
                f"- 可借的情绪线索：{tracked_article_scene or '无'}",
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
                f"- 可借的原文情绪线索：{tracked_article_scene or '无'}",
                "- 必须主动拉开距离的维度：标题骨架、开头情绪发动机、中段顺序、结尾价值赦免。",
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
                f"- 把 `{normalized_topic_angle}` 做成读者能被看见、被松绑或被提醒的情绪发动机，而不是停在场景替换上。",
            ]
        )
    return "\n".join(lines)
