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
    assert "开头先给一个现实抓手" in flattened
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

    assert any("标题和开头都换成新的现实入口" in item for item in result.strategy_card.recomposition_recipe)
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


def test_build_strategy_package_uses_pressure_interface_mode_for_shell_heavy_internal_pressure_source() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "善待自己，好好爱自己",
            "topic_angle": "从总把休息、体检和身体提醒往后放的人写起，解释生活顺序怎样慢慢失衡。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "善待自己，好好爱自己",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": (
                "# 善待自己，好好爱自己\n\n"
                "花儿谢了，还有再开的时候。\n\n"
                "很多人总以为，最大的遗憾是没赚到更多的钱。\n\n"
                "真正卡住人的，是一路太匆忙，却没有照顾好自己。\n\n"
                "如果生活没有净土，那我们可以选择静心。\n\n"
                "所以，善待自己，好好爱自己。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-07T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "pressure_interface_direct"
    assert "现实接口" in result.strategy_card.opening_move or "身体提醒" in result.strategy_card.opening_move
    assert "压力链" in result.strategy_card.body_shift
    assert "万能答案" in result.strategy_card.ending_move or "祝福式收束" in result.strategy_card.ending_move


def test_build_strategy_package_uses_pressure_interface_mode_when_summary_rules_out_relationship_mainline() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "身体先发出的那些钝感，往往不是累一阵就会过去",
            "topic_angle": "从很多女性在关系、工作和体面之间不断撤掉自我照料写起，解释身体和情绪为什么会一起追债。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "总把自己放最后的人，身体会替你记账",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "文章重点是内耗、身体代价和生活排序失衡，不在亲密关系沟通里打转，也不要写成冷战复合流程。",
            "reference_article_structure_notes": "从日常顺延和身体变钝切入，再落到自我照料缺位。",
            "reference_article_body_markdown": "# 总把自己放最后的人，身体会替你记账\n\n她先把体检往后改，又把回家吃饭这件事往后推。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-08T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "pressure_interface_direct"
    assert "开始出代价" in result.strategy_card.opening_move
    assert "身体提醒" in result.strategy_card.opening_move or "接口" in result.strategy_card.opening_move


def test_build_strategy_package_uses_pressure_interface_mode_for_body_consequence_chain_source() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "总把自己排到最后的人，迟早要为失序的生活付账",
            "topic_angle": "从“总能再撑一下”的自我调度入手，拆开很多女性怎样在工作、家人和体面之间持续撤掉自我照料，直到身体和情绪一起追债。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "善待自己，好好爱自己",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": (
                "# 善待自己，好好爱自己\n\n"
                "后来得了尿毒症，又开始怀念当初长褥疮的时候。\n\n"
                "又过了一些年，要透析，清醒的时间很少，便又开始怀念起刚得尿毒症的时候。\n\n"
                "是这一生，走得太过匆忙，太过疲累，一路跌跌撞撞地前行，却没有照顾好自己。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-08T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "pressure_interface_direct"
    assert "尿毒症" in result.strategy_card.opening_move
    assert "褥疮" in result.strategy_card.body_shift or "尿毒症" in result.strategy_card.body_shift
    assert "代价链" in result.strategy_card.body_shift or "追到账上" in result.strategy_card.body_shift


def test_build_strategy_package_does_not_amplify_long_pressure_title_into_problem_brief() -> None:
    long_title = "总把休息和复查排在最后的人，最后会怀念那个“只是有点累”的自己"
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": long_title,
            "topic_angle": "从尿毒症一路拖到透析的身体代价链切入，写人为什么总把自己的求救信号继续压后，不先抛人生答案。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "善待自己，好好爱自己",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": (
                "# 善待自己，好好爱自己\n\n"
                "后来得了尿毒症，又开始怀念当初长褥疮的时候。\n\n"
                "又过了一些年，要透析，清醒的时间很少，便又开始怀念起刚得尿毒症的时候。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-09T00:00:00Z",
    )

    assert result.problem_brief.clarified_problem.startswith("真正需要被看见的")
    assert long_title not in result.problem_brief.clarified_problem
    assert "尿毒症" in result.problem_brief.clarified_problem
    assert "透析" in result.problem_brief.clarified_problem
    assert long_title not in result.problem_brief.feedback_entry
    assert "先顾自己" in result.problem_brief.feedback_entry
    assert "越觉得" not in result.problem_brief.feedback_entry
    assert "这篇稿子要解释的，是为什么 `得了尿毒症` 这类提醒已经冒头了" in result.problem_brief.problem_statement_markdown


def test_build_strategy_package_keeps_pressure_problem_statement_off_title_echo_for_rerun_g_shape() -> None:
    long_title = "从尿毒症到透析，身体到底替你扛了多少"
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": long_title,
            "topic_angle": "从“还能扛”到复查拖延、休息推后，很多女人都是在身体每次更坏一点时，才承认上一个阶段其实已经在提醒自己该停了。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "善待自己，好好爱自己",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": (
                "# 善待自己，好好爱自己\n\n"
                "后来得了尿毒症，又开始怀念当初长褥疮的时候。\n\n"
                "又过了一些年，要透析，清醒的时间很少，便又开始怀念起刚得尿毒症的时候。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-09T00:00:00Z",
    )

    assert "身体判断一次次往后推" in result.problem_brief.observed_phenomenon
    assert "复查、休息和自我判断怎样被一再往后推" in result.problem_brief.problem_statement_markdown
    assert "要讲清的，是 `从尿毒症到透析，身体到底替你扛了多少` 为什么会慢慢发生" not in result.problem_brief.problem_statement_markdown
    assert "最后连该不该停下来都越来越判断不准" in result.problem_brief.feedback_entry


def test_build_strategy_package_keeps_medical_pressure_strategy_when_angle_drifts_to_self_stabilizing() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "从尿毒症到透析，身体到底替你扛了多少",
            "topic_angle": "拆开一种常见自我消耗：很多女人不是突然垮掉，而是在每次恶化后才后知后觉地怀念上一个还能撑的阶段。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "善待自己，好好爱自己",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "文章重点是一路硬撑、忽略身体提醒，最后才意识到自己把照顾自己这件事放到了最后。",
            "reference_article_structure_notes": "",
            "reference_article_body_markdown": (
                "# 善待自己，好好爱自己\n\n"
                "后来得了尿毒症，又开始怀念当初长褥疮的时候。\n\n"
                "又过了一些年，要透析，清醒的时间很少，便又开始怀念起刚得尿毒症的时候。\n\n"
                "是这一生，走得太过匆忙，太过疲累，一路跌跌撞撞地前行，却没有照顾好自己。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-09T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "pressure_interface_direct"
    assert result.problem_brief.target_reader_situation == "总把休息、体检、吃饭、回复和自己顺手往后挪的人"
    assert "越想稳住自己越累" not in result.problem_brief.writing_goal
    assert "认出自己已经在透支什么" in result.problem_brief.writing_goal
    assert result.problem_brief.clarified_problem.startswith("真正需要被看见的，是 `得了尿毒症`")
    assert "总把该先顾自己的事拖到更后面" in result.problem_brief.feedback_entry
    assert "并且能从 `" not in result.problem_brief.feedback_entry
    assert "复查、休息和自我判断是怎样被一再压后的" in result.problem_brief.problem_statement_markdown
    assert "从总想把自己绷住的日常代价切入" not in result.problem_brief.problem_statement_markdown


def test_build_strategy_package_keeps_relationship_repair_summary_on_emotional_engine_mode() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "topic_angle": "从冲突过后最容易失控的解释冲动写起，拆开关系修复为什么总输在顺序。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "文章重点是关系修复和表达顺序，不是输在不会说，而是输在没先接住失望。",
            "reference_article_structure_notes": "先回到失望现场，再拆修复顺序和表达动作。",
            "reference_article_body_markdown": "# 真正让关系缓回来，不是解释，是先接住那一下失望\n\n她那天没有继续解释，只是先停下来接住那一下失望。",
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-08T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "emotional_engine_direct"


def test_build_strategy_package_uses_relationship_aftercare_mode_for_quarrel_repair_article() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "每次闹完都要你自己消化，这段关系已经在交“回避税”",
            "topic_angle": "把反复争执后“谁先冷下来谁就算懂事”的处境拆开，写清长期由一方自我消化、另一方回避修复时，亲密关系会怎样慢慢失去安全感。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "一个人到底爱不爱你，吵一架就知道了",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "文章把“爱不爱”放到争吵后的具体表现里观察：关键不在是否会吵，而在对方有没有主动沟通、安顿情绪、推动关系修复。",
            "reference_article_structure_notes": "先看争执后的态度，再拆冷暴力和主动修复怎样把关系带向不同结果。",
            "reference_article_body_markdown": (
                "# 一个人到底爱不爱你，吵一架就知道了\n\n"
                "激烈地争吵过后，有人选择冷暴力，不理不睬，任由情绪发酵；有人选择及时妥协，回归理性，让爱化解矛盾。\n\n"
                "吵架后的态度，便是检验爱情的试金石。\n\n"
                "人生在世，遇到一个吵完架还对你温柔以待的人不容易。毕竟好的关系，不是永远不吵架，而是争吵以后还想要继续走下去。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-15T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "relationship_aftercare"
    assert result.problem_brief.target_reader_situation == "每次吵完都要自己消化情绪、把日子接回去的人"
    assert "吵架不可怕" in result.problem_brief.writing_goal
    assert "真正需要被看见的，是为什么一次次争执之后，总是只有一方在回收情绪、重建秩序" in result.problem_brief.clarified_problem
    assert "争执后的安抚、解释和修复都落在同一个人身上" in result.problem_brief.problem_statement_markdown
    assert "谁在善后" in result.strategy_card.point_of_view
    assert "谁先把话咽回去" in result.strategy_card.body_shift
    assert "长期单人善后" in result.strategy_card.body_shift
    assert "没被接住的小动作" in result.strategy_card.ending_move
    assert any("整齐翻转句" in item for item in result.strategy_card.expression_constraints)


def test_build_strategy_package_keeps_happiness_release_article_on_emotional_engine_mode() -> None:
    topic_title = "总想再撑一下的人，容易把沉没成本误认成感情诚意"
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": topic_title,
            "topic_angle": "从“再坚持一下”这句自我安慰切入，拆开女人迟迟不肯松手时真正抓住的，往往是沉没成本、输不起感和被反复推迟的自我止损。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "幸福是什么",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "文章把幸福的定义从“不断获得”转向“适时放下”，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。核心判断是，幸福未必来自追到更多，而更可能来自停止拉扯、看见眼前已经拥有的部分。",
            "reference_article_structure_notes": "开头用“幸福是得到还是放下”的反差提问切入，中段转到“强求只会消耗自己”，结尾回收到“放手不是失去，而是腾出位置”。",
            "reference_article_body_markdown": (
                "# 幸福是什么\n\n"
                "幸福是什么？我们总以为，幸福是“得到”：得到爱，得到钱，得到想要的一切。后来才懂，幸福其实是“放下”：放下强求，放下执念，放下那些得不到的东西。\n\n"
                "你有没有过这样的时刻？明明一段关系已经烂了，你还死死抓着不放，安慰自己“再坚持一下就好了”；明明一个目标根本不合适你，你还拼命往前冲，骗自己“只要够努力就能成功”；把自己困在“不甘心”的牢笼里，一遍遍问：“为什么我付出了，却得不到？”\n\n"
                "我们都曾在“强求”里，耗尽了自己，以为努力争取，就能得到幸福。可真正的幸福，恰恰是该结束的时候，不再强求，该珍惜的时候，别无所求。\n\n"
                "别再盯着自己没有的东西了，转过头，看看你拥有的。你无忧、无虑、无病、无灾，你有健康的身体，爱你的家人，三两好友，一碗热饭。\n\n"
                "亲爱的，该放手的，就放手，那不是失去，是腾出位置。该珍惜的，就好好珍惜，别等到来不及，别等到失去了，才意识到自己曾经就在幸福里。\n\n"
                "愿你学会“不再强求”的放下，也学会“别无所求”的知足。幸福从来不在别处，就在你放手后的轻松里，在你珍惜时的微笑里。别再追问“幸福是什么”了，你已经拥有它了。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-09T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "emotional_engine_direct"
    assert result.problem_brief.target_reader_situation != "总把休息、体检、吃饭、回复和自己顺手往后挪的人"
    assert "健康的身体" not in result.strategy_card.opening_move
    assert "体检" not in result.strategy_card.opening_move
    assert "情绪发动机" in result.strategy_card.body_shift
    assert "放到最后" in result.strategy_card.body_shift
    assert result.problem_brief.problem_statement_markdown.count("从身体和日常节奏已经开始变钝的迹象切入") == 0


def test_build_strategy_package_avoids_title_echo_for_broad_happiness_release_article() -> None:
    topic_title = "把心力收回来：人为什么总把继续投入误认成更接近幸福"
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": topic_title,
            "topic_angle": "这篇想拆开一种常见误认：我们常把继续投入当成认真和有希望，直到精力、睡眠和眼前拥有都被透支，才发现停下也是一种保护。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "幸福是什么",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "文章把幸福的定义从“不断获得”转向“适时放下”，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。核心判断是，幸福未必来自追到更多，而更可能来自停止拉扯、看见眼前已经拥有的部分。",
            "reference_article_structure_notes": "开头用“幸福是得到还是放下”的反差提问切入，中段转到“强求只会消耗自己”，结尾回收到“放手不是失去，而是腾出位置”。",
            "reference_article_body_markdown": (
                "# 幸福是什么\n\n"
                "幸福是什么？我们总以为，幸福是“得到”：得到爱，得到钱，得到想要的一切。后来才懂，幸福其实是“放下”：放下强求，放下执念，放下那些得不到的东西。\n\n"
                "你有没有过这样的时刻？明明一段关系已经烂了，你还死死抓着不放，安慰自己“再坚持一下就好了”；明明一个目标根本不合适你，你还拼命往前冲，骗自己“只要够努力就能成功”；把自己困在“不甘心”的牢笼里，一遍遍问：“为什么我付出了，却得不到？”\n\n"
                "我们都曾在“强求”里，耗尽了自己，以为努力争取，就能得到幸福。可真正的幸福，恰恰是该结束的时候，不再强求，该珍惜的时候，别无所求。\n\n"
                "别再盯着自己没有的东西了，转过头，看看你拥有的。你无忧、无虑、无病、无灾，你有健康的身体，爱你的家人，三两好友，一碗热饭。\n\n"
                "亲爱的，该放手的，就放手，那不是失去，是腾出位置。该珍惜的，就好好珍惜，别等到来不及，别等到失去了，才意识到自己曾经就在幸福里。\n\n"
                "愿你学会“不再强求”的放下，也学会“别无所求”的知足。幸福从来不在别处，就在你放手后的轻松里，在你珍惜时的微笑里。别再追问“幸福是什么”了，你已经拥有它了。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-10T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "emotional_engine_direct"
    assert result.problem_brief.target_reader_situation == "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人"
    assert topic_title not in result.problem_brief.observed_phenomenon
    assert "继续投入误认成还有希望" in result.problem_brief.observed_phenomenon
    assert topic_title not in result.problem_brief.writing_goal
    assert "停下不是认输" in result.problem_brief.writing_goal
    assert topic_title not in result.problem_brief.clarified_problem
    assert "不甘心、投入感和希望" in result.problem_brief.clarified_problem
    assert topic_title not in result.problem_brief.feedback_entry
    assert "不是离幸福太远" in result.problem_brief.feedback_entry
    assert topic_title not in result.strategy_card.conflict_frame
    assert "舍不得放手" in result.strategy_card.conflict_frame


def test_build_strategy_package_uses_everyday_warmth_return_mode_for_small_things_article() -> None:
    result = build_strategy_package(
        project={
            "slug": "tracked-project",
            "topic_title": "很多“大事”最后都会祛魅，留下你的反而是这些小事",
            "topic_angle": "从成就叙事为什么总会在某个阶段突然祛魅切入，写人慢下来以后，怎样重新看见那些不起眼却最能托住生活的小事和陪伴。",
            "trend_title": "参考文章 / 手动录入",
            "source_type": "tracked_article",
            "reference_article_title": "一生最重要的事，不是大事",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "文章把“做大事”的社会期待，与人在身体受挫、生活放慢后重新确认的日常幸福放在一起比较，核心判断是：真正支撑一个人生活感受的，往往不是成就叙事，而是陪伴、相处和被看见的细碎时刻。",
            "reference_article_structure_notes": "开头先摆出追逐成就的大命题，中段借手术停下来后的家庭陪伴完成价值转向，结尾回到普通日常和陪伴。",
            "reference_article_body_markdown": (
                "# 一生最重要的事，不是大事\n\n"
                "年轻时，我们都想改变世界，觉得人生一定要轰轰烈烈，要做大事，要出人头地。可走过半生，才发现，这世界再喧嚣，最重要的事，不过是活在人间烟火里，陪在爱的人身边。\n\n"
                "朋友是上市公司的高管，最近因为身体不舒服做了个手术，在家休养。\n\n"
                "他终于在日落之前，陪爱人做了一顿晚饭。他久违地去接孩子放学。那一刻，他突然觉得，那些拼了命追求的大事，好像瞬间祛魅了。\n\n"
                "其实，真正让人眼眶发热的，可能从来不是升职加薪、远大抱负，而是这些不起眼的、细碎的、平淡的日常瞬间。宏大叙事属于时代，属于历史书，而一碗热汤、一盏夜灯、一句晚安，才属于你我。"
            ),
        },
        problem_brief_version=1,
        strategy_version=1,
        created_at="2026-06-14T00:00:00Z",
    )

    assert result.strategy_card.structure_mode == "everyday_warmth_return"
    assert "更大的目标" in result.problem_brief.writing_goal
    assert "陪伴和日常" in result.problem_brief.problem_statement_markdown
    assert "普通陪伴" in result.strategy_card.body_shift or "细小日常" in result.strategy_card.body_shift
    assert "很小的陪伴动作" in result.strategy_card.ending_move
