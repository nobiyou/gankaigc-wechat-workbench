from app.services.creative_strategy import build_strategy_package


def test_build_strategy_package_supports_manual_original_idea_source() -> None:
    result = build_strategy_package(
        project={
            "slug": "manual-original-project",
            "topic_title": "为什么总在深夜反复确认一段关系",
            "topic_angle": "从反复点开聊天框但迟迟不敢发消息的动作切入，解释不安怎样把表达变成试探。",
            "trend_title": "",
            "source_type": "manual",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-19T00:00:00Z",
    )

    assert result.problem_brief.source_mode == "manual"
    assert result.problem_brief.raw_goal == "为什么总在深夜反复确认一段关系"
    assert result.problem_brief.status == "ready"
    assert result.benchmarks[0].reference_kind == "operator_reference"
    assert result.benchmarks[0].reference_label == "为什么总在深夜反复确认一段关系"
    assert "不要复用现成判断句" in result.benchmarks[0].avoid_focus


def test_build_strategy_package_marks_vague_upstream_input_as_unknown() -> None:
    result = build_strategy_package(
        project={
            "slug": "vague-topic-project",
            "topic_title": "女性成长",
            "topic_angle": "",
            "trend_title": "女性成长",
            "source_type": "trend",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-19T00:00:00Z",
    )

    assert "切口仍偏泛，大纲阶段要主动收窄到一个更具体的处境。" in result.problem_brief.unknowns
    assert "女性成长" in result.problem_brief.raw_goal
    assert result.strategy_card.status == "ready"


def test_build_strategy_package_records_benchmark_borrow_and_avoid_boundaries() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-reference-project",
            "topic_title": "别把日子过反了",
            "topic_angle": "从推迟复查和总说等忙完的日常动作切入，解释生活排序为什么会慢慢倒过来。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "别把日子过反了",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "开头先给身体提醒，中段写一次次顺延，结尾回到生活排序。",
            "reference_article_body_markdown": (
                "# 别把日子过反了\n\n"
                "朋友阿杰总说等忙完再体检，后来连复查也一次次往后推。\n\n"
                "直到医生说要透析，他才发现身体提醒早就出现过。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-19T00:00:00Z",
    )

    benchmark = result.benchmarks[0]
    assert benchmark.reference_kind == "tracked_article"
    assert benchmark.reference_label == "别把日子过反了"
    assert "原文压力类型和情绪发动机" in benchmark.borrow_focus
    assert "段落职责分配" in benchmark.borrow_focus
    assert "不要复用原标题骨架" in benchmark.avoid_focus
    assert "只借观察路径、冲突组织和节奏职责" in benchmark.rationale
    assert any("不得沿用原标题骨架" in constraint for constraint in result.problem_brief.constraints)
