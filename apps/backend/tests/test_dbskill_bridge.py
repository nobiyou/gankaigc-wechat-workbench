from __future__ import annotations

import json
from pathlib import Path

from app.services import dbskill_bridge
from app.services.creative_strategy import build_strategy_package


def test_dbskill_bridge_falls_back_to_embedded_defaults_when_generated_rules_missing(monkeypatch, tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"
    monkeypatch.setattr(dbskill_bridge, "GENERATED_RULES_PATH", missing_path)
    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()

    rules = dbskill_bridge.load_dbskill_tracked_article_rules()

    assert rules["source"]["version"] == "embedded-default"
    assert any("先把事情搞清楚" in item for item in rules["strategy"]["problem_constraints"])
    assert any("标题组可以参考公式意识" in item for item in rules["assets"]["extra_instructions"])
    assert any("小型复盘" in item for item in rules["publish_package"]["extra_instructions"])


def test_dbskill_bridge_reads_generated_rules_when_present(monkeypatch, tmp_path: Path) -> None:
    generated_path = tmp_path / "tracked_article_rules.json"
    generated_path.write_text(
        json.dumps(
            {
                "source": {"version": "2.12.0", "origin": "dontbesilent2025/dbskill"},
                "strategy": {
                    "problem_constraints": ["问题说明书先去掉关于作者自己的噪音。"],
                    "problem_brief_steps": ["先把问题钉成现象。"],
                    "divergence_axes": ["模仿的颗粒度要落到段落职责，而不是只模仿观点。"],
                    "divergence_checks": ["先确认标题骨架和结尾动作都已经换掉。"],
                    "execution_checklist": ["先确认事情已经被说清楚，再考虑包装。"],
                },
                "draft": {
                    "extra_instructions": ["不要把实操问题一路升维成更大的哲学判断。"],
                    "execution_protocol": ["先落动作，再带判断。"],
                    "self_checklist": ["删掉最后一段祝福后如果全文还成立，就不要补回去。"],
                },
                "diagnosis": {
                    "signals": ["如果文本太光滑、太均匀，要怀疑它更像 AI 成稿。"],
                },
                "assets": {
                    "extra_instructions": ["标题不要只套公式，要写清读者收益。"],
                },
                "publish_package": {
                    "extra_instructions": ["编辑备注要写清已确认结论和已否决方向。"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dbskill_bridge, "GENERATED_RULES_PATH", generated_path)
    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()

    rules = dbskill_bridge.load_dbskill_tracked_article_rules()

    assert rules["source"]["version"] == "2.12.0"
    assert rules["strategy"]["problem_constraints"] == ["问题说明书先去掉关于作者自己的噪音。"]
    assert rules["strategy"]["problem_brief_steps"] == ["先把问题钉成现象。"]
    assert rules["strategy"]["divergence_checks"] == ["先确认标题骨架和结尾动作都已经换掉。"]
    assert rules["draft"]["extra_instructions"] == ["不要把实操问题一路升维成更大的哲学判断。"]
    assert rules["draft"]["execution_protocol"] == ["先落动作，再带判断。"]
    assert rules["draft"]["self_checklist"] == ["删掉最后一段祝福后如果全文还成立，就不要补回去。"]
    assert rules["assets"]["extra_instructions"] == ["标题不要只套公式，要写清读者收益。"]
    assert rules["publish_package"]["extra_instructions"] == ["编辑备注要写清已确认结论和已否决方向。"]


def test_dbskill_bridge_localizes_scene_first_generated_rules(monkeypatch, tmp_path: Path) -> None:
    generated_path = tmp_path / "tracked_article_rules.json"
    generated_path.write_text(
        json.dumps(
            {
                "source": {"version": "2.12.0", "origin": "dontbesilent2025/dbskill"},
                "strategy": {
                    "problem_constraints": ["如果一句话还说不清楚，先退回到具体场景、动作和顺序，不要急着下结论。"],
                },
                "outline": {
                    "extra_instructions": ["每一节都要能落到具体场景、动作或关系变化，不能只摆概念。"],
                },
                "draft": {
                    "extra_instructions": ["遇到匀速排比和整齐翻转时，优先把句子拉回动作、停顿和关系变化。"],
                    "execution_protocol": ["开头先给一个抓手：动作、界面、物件、空间距离或身体反应，先别下总判断。"],
                    "self_checklist": ["结尾回到一个小动作、关系余波或现实阻力，不要祝福式收尾。"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dbskill_bridge, "GENERATED_RULES_PATH", generated_path)
    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()

    rules = dbskill_bridge.load_dbskill_tracked_article_rules()

    flattened = json.dumps(rules, ensure_ascii=False)
    assert "具体场景、动作和顺序" not in flattened
    assert "小动作、关系余波" not in flattened
    assert "开头先给一个情绪发动机" in flattened
    assert "不能用场景描写凑篇幅" in flattened
    assert "不要另补小动作" in flattened

    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()


def test_build_strategy_package_consumes_generated_dbskill_rules(monkeypatch, tmp_path: Path) -> None:
    generated_path = tmp_path / "tracked_article_rules.json"
    generated_path.write_text(
        json.dumps(
            {
                "source": {"version": "2.12.0", "origin": "dontbesilent2025/dbskill"},
                "strategy": {
                    "problem_constraints": ["问题说明书先去掉关于作者自己的噪音。"],
                    "divergence_axes": ["模仿的颗粒度要落到段落职责，而不是只模仿观点。"],
                    "execution_checklist": ["先确认事情已经被说清楚，再考虑包装。"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dbskill_bridge, "GENERATED_RULES_PATH", generated_path)
    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()

    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "别把日子过反了",
            "topic_angle": "从推迟和顺延的日常动作切入，解释生活排序为什么会慢慢倒过来。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "别把日子过反了",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": "# 别把日子过反了\n\n第一段：消息停住。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-01T00:00:00Z",
    )

    assert "问题说明书先去掉关于作者自己的噪音。" in result.problem_brief.constraints
    assert "模仿的颗粒度要落到段落职责，而不是只模仿观点。" in result.strategy_card.divergence_axes
    assert "先确认事情已经被说清楚，再考虑包装。" in result.strategy_card.execution_checklist

    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()


def test_build_strategy_package_uses_fragment_chain_mode_for_banner_heavy_tracked_source() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "别把日子过反了",
            "topic_angle": "从推迟和顺延的日常动作切入，解释生活排序为什么会慢慢倒过来。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "别把日子过反了",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": (
                "# 别把日子过反了\n\n"
                "别用健康换明天\n\n"
                "朋友阿杰总说等忙完再休息。\n\n"
                "别等失去才懂珍惜\n\n"
                "外婆离世后，我才发现连合照都没留下。\n\n"
                "别把幸福寄托在“等以后”\n\n"
                "我们总习惯把想做的事往后推。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-01T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "fragment_chain_observation"
    assert "现实接口" in result.strategy_card.body_shift
    assert any("连续主角场景" in item for item in result.strategy_card.divergence_axes)


def test_build_strategy_package_adds_reference_shell_avoidance_for_banner_case_source() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "别把日子过反了",
            "topic_angle": "从推迟和顺延的日常动作切入，解释生活排序为什么会慢慢倒过来。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "别把日子过反了",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": (
                "# 别把日子过反了\n\n"
                "深夜独处时，那些如果当初的念头总会冒出来。\n\n"
                "别用健康换明天\n\n"
                "朋友阿杰总说等忙完再休息。\n\n"
                "真正的聪明人，懂得在该休息时休息。\n\n"
                "别等失去才懂珍惜\n\n"
                "外婆离世后，我才发现连一张像样的合照都没有。\n\n"
                "有些东西，失去了就再也找不回来。\n\n"
                "别把幸福寄托在等以后\n\n"
                "等有钱了，就去旅行。等忙完这阵，就好好陪家人。等退休了，就去做喜欢的事。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-02T00:00:00Z",
    )

    assert any("命令式小标题" in item for item in result.strategy_card.divergence_axes)
    assert any("分节标题 - 单个案例 - 独立结论段" in item for item in result.strategy_card.divergence_axes)
    assert any("不要沿用“深夜独处时" in item for item in result.strategy_card.expression_constraints)
    assert any("不要把正文切成一串“别…… / 不要……”式命令型小标题" in item for item in result.strategy_card.expression_constraints)
    assert any("命令型小标题串联" in item for item in result.strategy_card.execution_checklist)
    assert any("排队式引语" in item for item in result.strategy_card.execution_checklist)
    assert "命令式分节和案例轮转壳子" in result.strategy_card.benchmark_summary


def test_build_strategy_package_adds_recomposition_recipe_for_shell_heavy_source() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "别把日子过反了",
            "topic_angle": "从推迟和顺延的日常动作切入，解释生活排序为什么会慢慢倒过来。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "别把日子过反了",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": (
                "# 别把日子过反了\n\n"
                "深夜独处时，那些如果当初的念头总会冒出来。\n\n"
                "别用健康换明天\n\n"
                "朋友阿杰总说等忙完再休息。\n\n"
                "真正的聪明人，懂得在该休息时休息。\n\n"
                "别等失去才懂珍惜\n\n"
                "外婆离世后，我才发现连一张像样的合照都没有。\n\n"
                "有些东西，失去了就再也找不回来。\n\n"
                "别把幸福寄托在等以后\n\n"
                "最近一次改期见的人是谁，最近一次忽略的身体信号是什么，最近一次觉得等有空再说的事是什么。\n\n"
                "愿我们都能不再把重要的事一拖再拖。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-02T00:00:00Z",
    )

    assert any("标题和开头都改成情绪发动机入口" in item for item in result.strategy_card.recomposition_recipe)
    assert any("正文默认不用分节小标题" in item for item in result.strategy_card.recomposition_recipe)
    assert any("最后一句不要写成“愿你 / 愿我们 / 希望你”式抚慰总结" in item for item in result.strategy_card.recomposition_recipe)


def test_build_strategy_package_avoids_not_ab_skeleton_in_strategy_copy() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "别把日子过反了",
            "topic_angle": "从推迟和顺延的日常动作切入，解释生活排序为什么会慢慢倒过来。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "别把日子过反了",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": "# 别把日子过反了\n\n第一段：消息停住。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-02T00:00:00Z",
    )

    strategy_text = "\n".join(
        [
            result.problem_brief.observed_phenomenon,
            result.problem_brief.writing_goal,
            result.strategy_card.conflict_frame,
            result.strategy_card.strategy_markdown,
        ]
    )

    assert "不是" not in result.strategy_card.conflict_frame
    assert "而是" not in result.strategy_card.conflict_frame
    assert "不是一个抽象观点" not in strategy_text


def test_build_strategy_package_keeps_internal_pressure_topic_out_of_boundary_cut_in() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "不纠缠，是成年人最好的治愈",
            "topic_angle": "从总想把每件事都安顿好的人写起：当胃口变差、作息发乱、对小事越来越没耐心，先要调整的往往不是情绪解释，而是生活接口的负荷。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "不纠缠，是成年人最好的治愈",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": "# 不纠缠，是成年人最好的治愈\n\n心事一重，就会感觉遇事不顺。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-03T00:00:00Z",
    )

    assert "想开口又收回去" not in result.problem_brief.problem_statement_markdown
    assert "失望和误解" not in result.problem_brief.problem_statement_markdown
    assert "生活接口的长期负荷" in result.problem_brief.problem_statement_markdown
    assert "长期超负荷" in result.strategy_card.body_shift
    assert "身体提醒" in result.strategy_card.body_shift
