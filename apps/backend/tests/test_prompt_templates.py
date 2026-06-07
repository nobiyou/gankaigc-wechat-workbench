from __future__ import annotations

import json
from pathlib import Path

from app.services import dbskill_bridge
from app.services.content_skills import build_content_skill_instructions
from app.services.prompt_templates import (
    build_assets_prompt,
    build_cover_image_prompt,
    build_draft_prompt,
    build_outline_prompt,
    build_publish_package_prompt,
    build_topic_prompt,
    render_tone_profile_section,
)
from app.services.tone_profile_presets import JINWAN_YOUYU_PRESET_KEY


TONE_PROFILE = {
    "preset_key": None,
    "name": "女性成长克制陪伴风",
    "opening_style": "从具体场景冷启动切入",
    "paragraph_rhythm": "短段落，慢推进",
    "closing_style": "留白式收束",
    "forbidden_phrases": ["你必须", "立刻改变"],
    "value_constraints": "不说教，不制造羞耻感，避免空泛鸡汤",
    "target_word_count": 1400,
    "default_polish_instruction": "重写开头和结尾，打散重复句式。",
}

LONG_TRACKED_TOPIC_ANGLE = (
    "从一个女性反复推迟见父母、体检、回复伴侣消息的日常场景切入，不先谈大道理，"
    "而是把重心放在“推迟”这个动作如何悄悄塑造一个人的生活质地。"
    "结尾不拔高，只落在几个很轻的自查瞬间：最近一次改期见的人是谁，"
    "最近一次忽略的身体信号是什么，最近一次觉得‘等有空再说’的事，"
    "是否其实已经在透支关系和自己。"
)

JINWAN_YOUYU_TONE_PROFILE = {
    "preset_key": JINWAN_YOUYU_PRESET_KEY,
    "name": "今晚有语",
    "opening_style": "问句、引用或共鸣开场，直接点破问题和答案入口",
    "paragraph_rhythm": "标准三段式直接推进，中段围绕 2 到 4 个明确判断展开；每个判断都要给出处境、依据或行动落点，少铺氛围",
    "closing_style": "直接结论或温暖祝福收束，给答案，不拖鸡汤尾音",
    "forbidden_phrases": ["你应该", "总之", "在当今社会"],
    "value_constraints": "面向25到45岁女性，直接有力，给出答案，温暖但不说教；必须带来信息增量或情绪价值，不含蓄收尾。",
    "target_word_count": 1500,
    "default_polish_instruction": "按今晚有语完整风格精修。",
}


def test_render_tone_profile_section_outputs_structured_style_lines() -> None:
    section = render_tone_profile_section(TONE_PROFILE)

    assert "风格要求：" in section
    assert "风格档案：女性成长克制陪伴风" in section
    assert "开篇方式：从具体场景冷启动切入" in section
    assert "段落节奏：短段落，慢推进" in section
    assert "收束方式：留白式收束" in section
    assert "禁用表达：你必须 / 立刻改变" in section
    assert "价值约束：不说教，不制造羞耻感，避免空泛鸡汤" in section


def test_jinwan_youyu_style_injects_full_stage_rules_across_prompts() -> None:
    topic_template = build_topic_prompt(
        {
            "source_type": "trend",
            "trend_slug": "night-growth",
            "trend_title": "真正成熟的人，不再把情绪交给别人",
            "source": "manual",
            "heat_score": 88,
            "status": "screening",
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
        }
    )
    outline_template = build_outline_prompt(
        {
            "trend_title": "真正成熟的人，不再把情绪交给别人",
            "topic_title": "真正有力量的人，都把人生主导权收回来了",
            "topic_angle": "从总在等别人理解、等别人救场的处境切入，直接告诉读者答案是把遥控器收回来。",
            "project_title": "今晚有语样稿",
            "source_type": "manual",
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
        }
    )
    draft_template = build_draft_prompt(
        {
            "trend_title": "真正成熟的人，不再把情绪交给别人",
            "topic_title": "真正有力量的人，都把人生主导权收回来了",
            "topic_angle": "从总在等别人理解、等别人救场的处境切入，直接告诉读者答案是把遥控器收回来。",
            "project_title": "今晚有语样稿",
            "source_type": "manual",
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
            "outline": {
                "hook": "你有没有过这种时刻，明明心里很委屈，却一直等别人先来懂你？",
                "outline_body": "1. 先点破等待被理解的无力\n2. 讲清把人生交给别人的代价\n3. 直接给出把主导权收回来的答案",
            },
        }
    )
    assets_template = build_assets_prompt(
        {
            "trend_title": "真正成熟的人，不再把情绪交给别人",
            "topic_title": "真正有力量的人，都把人生主导权收回来了",
            "topic_angle": "从总在等别人理解、等别人救场的处境切入，直接告诉读者答案是把遥控器收回来。",
            "project_title": "今晚有语样稿",
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
            "draft": {
                "title": "真正有力量的人，都把人生主导权收回来了",
                "body_markdown": "# 正文\n\n内容",
            },
        }
    )
    publish_template = build_publish_package_prompt(
        {
            "project_title": "今晚有语样稿",
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
            "draft": {
                "title": "真正有力量的人，都把人生主导权收回来了",
                "body_markdown": "# 正文\n\n内容",
            },
            "assets": {
                "cover_copy": "别再等别人救场",
                "social_teaser": "把人生遥控器收回来，你才会稳。",
                "title_options": ["真正有力量的人，都把人生主导权收回来了"],
            },
        }
    )

    assert "标题长度控制在 10 到 20 个字" in topic_template.instructions
    assert "必须带钩子，不能只是情绪陈述" in topic_template.instructions
    assert "先给答案，不要把结论藏到后面" in topic_template.instructions

    assert "按标准三段式组织" in outline_template.instructions
    assert "这不是低成本三段式" in outline_template.instructions
    assert "中间部分展开 2 到 4 个论点" in outline_template.instructions
    assert "判断依据或行动落点" in outline_template.instructions
    assert "总字数目标控制在 1200 到 1800 字" in outline_template.instructions
    assert "大纲默认不规划场景描述" in outline_template.instructions
    assert "先规划情绪发动机" in outline_template.instructions
    assert "不展开环境、动作、物件和氛围描写" in outline_template.instructions

    assert "开头优先使用问句、引用或共鸣开场" in draft_template.instructions
    assert "不是让读者自己领悟，你要直接告诉她答案" in draft_template.instructions
    assert "观点 + 例子 + 结论" in draft_template.instructions
    assert "不能只重复标题情绪" in draft_template.instructions
    assert "正文不需要含蓄，默认去掉场景描写" in draft_template.instructions
    assert "正文都要让读者获得情绪价值" in draft_template.instructions
    assert "不用生活场景冷启动" in draft_template.instructions
    assert "需要例证时只保留一句事实或结果" in draft_template.instructions
    assert "例证不能单独成段" in draft_template.instructions
    assert "连续两篇不能用同一个人" in draft_template.instructions
    assert "不要使用这些词：不禁、心想、暗想、默念、琢磨、纠结、暗自、默默" in draft_template.instructions
    assert "少用“像……一样”“如同”“仿佛”“宛如”“好似”这类明喻" in draft_template.instructions
    assert "“不是A，是B”句式整篇最多使用 2 次" in draft_template.instructions
    assert "破折号整篇最多使用 2 处" in draft_template.instructions
    assert "不要写成逐条列举、逐项解释的导购式结构" in draft_template.instructions

    assert "导语要直接点破读者最在意的问题" in assets_template.instructions
    assert "不要写成空泛抒情 teaser" in assets_template.instructions

    assert "编辑备注要直接给出这篇稿子的核心答案和发布抓手" in publish_template.instructions
    assert "不要写成模糊抒情总结" in publish_template.instructions


def test_content_skills_define_platform_value_and_direct_scene_budget_rules() -> None:
    topic_instructions = build_content_skill_instructions(stage="topic")
    outline_instructions = build_content_skill_instructions(stage="outline")
    draft_instructions = build_content_skill_instructions(stage="draft")
    assets_instructions = build_content_skill_instructions(stage="assets")
    publish_instructions = build_content_skill_instructions(stage="publish_package")

    assert "平台鼓励具有丰富信息含量、信息增量或情绪价值的内容" in topic_instructions
    assert "不管采用哪种风格，都必须明确给读者一层情绪价值" in topic_instructions
    assert "不要生产疑似投机的低创作度内容" in topic_instructions
    assert "表达要直接，不要含蓄绕弯" in topic_instructions
    assert "大纲必须规划清楚每一段给读者新增什么" in outline_instructions
    assert "原则上不规划场景段，先规划情绪发动机" in outline_instructions
    assert "需要例证时只保留一句事实或结果" in outline_instructions
    assert "结尾要明确结论、边界或行动落点，不要含蓄留白" in outline_instructions
    assert "正文每个主要段落都要承担新的内容价值" in draft_instructions
    assert "不管风格多直接或多克制，正文都要让读者获得情绪价值" in draft_instructions
    assert "正文默认去掉场景描写" in draft_instructions
    assert "不用生活场景冷启动" in draft_instructions
    assert "不写“手机亮一下”“电梯门开了”这类独立动作残留" in draft_instructions
    assert "不要连续多段写环境、动作、光线、房间、夜晚等氛围" in draft_instructions
    assert "标题备选、封面文案和分发导语要准确呈现正文的信息增量或情绪价值" in assets_instructions
    assert "马上知道自己会被理解、被提醒或获得一个现实出口" in assets_instructions
    assert "不要用含蓄氛围、场景感文案或暧昧留白来包装正文" in assets_instructions
    assert "发布摘要和编辑备注必须点明这篇稿子的核心信息增量或情绪价值" in publish_instructions
    assert "提供的情绪承接是什么" in publish_instructions
    assert "发布摘要、标签和编辑备注直接写清核心结论" in publish_instructions


def test_content_skill_instructions_are_injected_across_public_account_prompts() -> None:
    topic_template = build_topic_prompt(
        {
            "source_type": "trend",
            "trend_slug": "night-growth",
            "trend_title": "真正成熟的人，不再把情绪交给别人",
            "source": "manual",
            "heat_score": 88,
            "status": "screening",
            "tone_profile": TONE_PROFILE,
        }
    )
    outline_template = build_outline_prompt(
        {
            "trend_title": "真正成熟的人，不再把情绪交给别人",
            "topic_title": "把人生主导权收回来",
            "topic_angle": "从总在等别人理解的处境切入，拆开把安全感交出去的代价。",
            "project_title": "平台价值守门样稿",
            "source_type": "manual",
            "tone_profile": TONE_PROFILE,
        }
    )
    draft_template = build_draft_prompt(
        {
            "trend_title": "真正成熟的人，不再把情绪交给别人",
            "topic_title": "把人生主导权收回来",
            "topic_angle": "从总在等别人理解的处境切入，拆开把安全感交出去的代价。",
            "project_title": "平台价值守门样稿",
            "source_type": "manual",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "她又一次等到凌晨，才发现自己一直在等别人先给答案。",
                "outline_body": "1. 等待被理解的现场\n2. 把安全感交出去的代价\n3. 收回主导权的动作",
            },
        }
    )
    assets_template = build_assets_prompt(
        {
            "trend_title": "真正成熟的人，不再把情绪交给别人",
            "topic_title": "把人生主导权收回来",
            "topic_angle": "从总在等别人理解的处境切入，拆开把安全感交出去的代价。",
            "project_title": "平台价值守门样稿",
            "tone_profile": TONE_PROFILE,
            "draft": {
                "title": "把人生主导权收回来",
                "body_markdown": "# 正文\n\n内容",
            },
        }
    )
    publish_template = build_publish_package_prompt(
        {
            "project_title": "平台价值守门样稿",
            "tone_profile": TONE_PROFILE,
            "draft": {
                "title": "把人生主导权收回来",
                "body_markdown": "# 正文\n\n内容",
            },
            "assets": {
                "cover_copy": "别再等别人救场",
                "social_teaser": "把安全感收回来。",
                "title_options": ["把人生主导权收回来"],
            },
        }
    )

    assert build_content_skill_instructions(stage="topic") in topic_template.instructions
    assert build_content_skill_instructions(stage="outline") in outline_template.instructions
    assert build_content_skill_instructions(stage="draft") in draft_template.instructions
    assert build_content_skill_instructions(stage="assets") in assets_template.instructions
    assert build_content_skill_instructions(stage="publish_package") in publish_template.instructions


def test_build_topic_prompt_includes_source_specific_context_and_style_section() -> None:
    template = build_topic_prompt(
        {
            "source_type": "tracked_article",
            "source_ref_slug": "wechat-mp-demo-1",
            "source_name": "一凡一尘",
            "article_title": "听到伴侣说话就烦，不是你脾气差",
            "author": "一凡一尘",
            "summary": "摘要内容",
            "structure_notes": "结构备注",
            "tags": ["wechat-mp", "relationship"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "基于参考文章提炼出一个可直接立项的女性情感成长类原创选题" in template.instructions
    assert "不要使用“不是A，而是B”" in template.instructions
    assert "不要把参考文章里的高频词直接放进标题主干" in template.instructions
    assert "不要沿用参考文章默认的矛盾顺序或段落重心" in template.instructions
    assert "至少要同时改掉原标题骨架、观察视角和情绪推进顺序中的两项" in template.instructions
    assert "切入角度只写 1 句话，控制在 40 到 80 个汉字" in template.instructions
    assert "参考文章标题：听到伴侣说话就烦，不是你脾气差" in template.prompt
    assert "标签：wechat-mp / relationship" in template.prompt
    assert "风格档案：女性成长克制陪伴风" in template.prompt
    assert "切入角度 angle（1 句话，控制在 40 到 80 个汉字）" in template.prompt


def test_outline_and_draft_prompts_consume_generated_dbskill_rules(monkeypatch, tmp_path: Path) -> None:
    generated_path = tmp_path / "tracked_article_rules.json"
    generated_path.write_text(
        json.dumps(
            {
                "source": {"version": "2.12.0", "origin": "dontbesilent2025/dbskill"},
                "outline": {
                    "extra_instructions": ["大纲先把事情讲清楚，再考虑怎么讲得更好看。"],
                },
                "draft": {
                    "extra_instructions": ["允许局部停顿、犹豫和没完全说透的地方，不要把情绪修得过于平整。"],
                },
                "diagnosis": {
                    "signals": ["如果“不是 X 是 Y”密度过高，说明认知翻转正在替代真正的推进。"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dbskill_bridge, "GENERATED_RULES_PATH", generated_path)
    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()

    outline_template = build_outline_prompt(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "先接住失望，再谈道理",
            "topic_angle": "关系修复",
            "project_title": "慢修复关系稿",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "clarified_problem": "这篇文章要解释，为什么很多关系修复不是输在不会说，而是输在没先接住失望。",
                "target_reader_situation": "总想解释却把时机越拖越晚的人",
                "core_conflict": "越急着说明白，越容易错过真正该接住的那一下。",
            },
            "strategy_card": {
                "reader_situation": "总想解释却把时机越拖越晚的人",
                "point_of_view": "先把失望怎么积出来讲清楚，不急着给答案",
                "conflict_frame": "不是缺道理，而是总在该接住的时候先去解释",
                "emotional_path": "从停顿和收回动作进入，再慢慢走到能重新开口",
                "expression_constraints": ["不要用口号式收尾"],
                "benchmark_summary": "只借处境类型，不借标题骨架和推进顺序。",
            },
            "benchmarks": [],
        }
    )
    draft_template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "先接住失望，再谈道理",
            "topic_angle": "关系修复",
            "project_title": "慢修复关系稿",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "clarified_problem": "这篇文章要解释，为什么很多关系修复不是输在不会说，而是输在没先接住失望。",
                "target_reader_situation": "总想解释却把时机越拖越晚的人",
                "core_conflict": "越急着说明白，越容易错过真正该接住的那一下。",
            },
            "strategy_card": {
                "reader_situation": "总想解释却把时机越拖越晚的人",
                "point_of_view": "先把失望怎么积出来讲清楚，不急着给答案",
                "conflict_frame": "不是缺道理，而是总在该接住的时候先去解释",
                "emotional_path": "从停顿和收回动作进入，再慢慢走到能重新开口",
                "expression_constraints": ["不要用口号式收尾"],
                "benchmark_summary": "只借处境类型，不借标题骨架和推进顺序。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "她盯着那条消息，半天没按发送。",
                "outline_body": "1. 那一下没被接住\n2. 解释为什么越说越乱\n3. 重新开口前先做什么",
            },
        }
    )

    assert "大纲先把事情讲清楚，再考虑怎么讲得更好看。" in outline_template.instructions
    assert "允许局部停顿、犹豫和没完全说透的地方，不要把情绪修得过于平整。" in draft_template.instructions
    assert "如果“不是 X 是 Y”密度过高，说明认知翻转正在替代真正的推进。" in draft_template.instructions

    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()


def test_assets_and_publish_prompts_consume_generated_dbskill_rules(monkeypatch, tmp_path: Path) -> None:
    generated_path = tmp_path / "tracked_article_rules.json"
    generated_path.write_text(
        json.dumps(
            {
                "source": {"version": "2.14.2", "origin": "dontbesilent2025/dbskill"},
                "assets": {
                    "extra_instructions": ["标题不要只套公式，要写清信息增量、情绪入口或现实损失。"],
                },
                "publish_package": {
                    "extra_instructions": ["编辑备注要写清核心主诉、已确认结论、已否决方向和保留经验。"],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dbskill_bridge, "GENERATED_RULES_PATH", generated_path)
    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()

    assets_template = build_assets_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "别等失去后才想起照顾自己",
            "topic_angle": "从一生只有一次切入，提醒读者别把自己永远排到最后。",
            "project_title": "善待自己稿",
            "tone_profile": TONE_PROFILE,
            "draft": {
                "title": "别等失去后才想起照顾自己",
                "body_markdown": "这一生最容易被推迟的，常常是自己。",
            },
        }
    )
    publish_template = build_publish_package_prompt(
        {
            "project_title": "善待自己稿",
            "tone_profile": TONE_PROFILE,
            "draft": {
                "title": "别等失去后才想起照顾自己",
                "body_markdown": "这一生最容易被推迟的，常常是自己。",
            },
            "assets": {
                "cover_copy": "别把自己放到最后",
                "social_teaser": "给总在硬撑的人一个出口。",
                "title_options": ["别等失去后才想起照顾自己"],
            },
        }
    )

    assert "标题不要只套公式，要写清信息增量、情绪入口或现实损失。" in assets_template.instructions
    assert "编辑备注要写清核心主诉、已确认结论、已否决方向和保留经验。" in publish_template.instructions

    dbskill_bridge.load_dbskill_tracked_article_rules.cache_clear()


def test_build_draft_prompt_includes_uniformity_break_rules() -> None:
    draft_template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 深夜关系观察",
            "topic_title": "回完所有人的消息，轮到自己时却开不了口",
            "topic_angle": "情绪耗尽",
            "project_title": "深夜耗尽稿",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "她盯着输入框，手指停在发送键上方。",
                "outline_body": "1. 夜里的卡顿\n2. 白天为什么一直在往外送\n3. 最后只剩一点点能留给自己",
            },
        }
    )

    assert "不要把全文磨成同一种克制、平稳、过度完整的成熟散文腔" in draft_template.instructions
    assert "不要把正文写成段落数刚好、段段职责单一、每段都像只负责一个结论的完整成稿" in draft_template.instructions
    assert "如果全文已经被切成很多匀称小段，优先合并成更长的自然段" in draft_template.instructions
    assert "避免连续多段都围绕同一个主语匀速起手" in draft_template.instructions
    assert "至少安排一段只呈现对话、动作残留、物件或环境声" in draft_template.instructions
    assert "至少安排一处说到一半又收回去、改口、停住或自我修正的表达" in draft_template.instructions
    assert "如果全文只有一条过于顺滑的情绪通道，就主动打断一次" in draft_template.instructions
    assert "输出前静默做一次过度成稿自检" in draft_template.instructions
    assert "继续删掉一个最会解释大道理的段落" in draft_template.instructions
    assert "不要把正文自动补齐成完整示范文" in draft_template.instructions


def test_build_outline_prompt_includes_detector_originality_rules() -> None:
    template = build_outline_prompt(
        {
            "trend_title": "参考文章 / 深夜关系观察",
            "topic_title": "回完所有人的消息，轮到自己时却开不了口",
            "topic_angle": "情绪耗尽",
            "project_title": "深夜耗尽稿",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "中段至少安排两处“触发 -> 当场反应 -> 后续影响”的推进链" in template.instructions
    assert "每个核心段都要有稳定抓手" in template.instructions
    assert "至少保留一节专门解释事情是怎样一步步变成现在这样的" in template.instructions
    assert "不要先写“这件事说明了什么时代症候”或“折射了更大的趋势”" in template.instructions
    assert "大纲里能合成两段职责的，不要机械拆成三段并列分论点" in template.instructions
    assert "不要安排“有人这样说”“很多人以为”“专家认为”这种模糊归因段" in template.instructions
    assert "结尾不要设计成一句适合截图传播的金句" in template.instructions
    assert "大纲只写段落职责和推进动作" in template.instructions
    assert "outline_body 只写段落职责和推进动作，尽量控制在 220 字以内。" in template.prompt
    assert "outline_body（每段 1 行，单段尽量不超过 40 字）" in template.prompt


def test_build_draft_prompt_includes_humanizer_zh_review_rules() -> None:
    draft_template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 深夜关系观察",
            "topic_title": "回完所有人的消息，轮到自己时却开不了口",
            "topic_angle": "情绪耗尽",
            "project_title": "深夜耗尽稿",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "她盯着输入框，手指停在发送键上方。",
                "outline_body": "1. 夜里的卡顿\n2. 白天为什么一直在往外送\n3. 最后只剩一点点能留给自己",
            },
        }
    )

    assert "删掉“说到底”“归根结底”“某种程度上”“很多时候”这类填充短语" in draft_template.instructions
    assert "能写两项就不要硬凑三项并列" in draft_template.instructions
    assert "不要用“有人说”“有人认为”“专家指出”“很多人都会”这类模糊归因" in draft_template.instructions
    assert "不要把普通处境硬拔成时代缩影、重要转折或更宏大的意义" in draft_template.instructions
    assert "如果一句话读起来像现成金句或适合被单独截图传播" in draft_template.instructions


def test_build_outline_and_draft_prompt_surface_recomposition_recipe() -> None:
    payload = {
        "trend_title": "参考文章 / 深夜关系观察",
        "topic_title": "回完所有人的消息，轮到自己时却开不了口",
        "topic_angle": "情绪耗尽",
        "project_title": "深夜耗尽稿",
        "source_type": "tracked_article",
        "tone_profile": TONE_PROFILE,
        "problem_brief": {
            "clarified_problem": "这篇文章要解释，为什么很多人白天忙着回应别人，轮到自己时反而一句都说不出来。",
            "target_reader_situation": "总在处理别人情绪，留给自己的空间越来越少的人",
            "core_conflict": "越想把所有关系都稳住，越容易把自己那一点点真实反应压掉。",
        },
        "strategy_card": {
            "reader_situation": "总在处理别人情绪，留给自己的空间越来越少的人",
            "point_of_view": "先把人是怎么被一点点掏空的讲清楚，不急着给方法",
            "conflict_frame": "不是不会表达，而是轮到自己时已经没电了",
            "emotional_path": "从一个停住的动作进去，再慢慢带出后劲",
            "structure_mode": "fragment_chain_observation",
            "opening_move": "先落一个停在发送键上的动作。",
            "body_shift": "围绕同一个问题串起几个不同接口。",
            "ending_move": "收在一个没发出去的动作上。",
            "recomposition_recipe": [
                "标题和开头都改成具体处境入口：标题不用命令句或判断句，首段先落一个能摸到的动作。",
                "正文默认不用分节小标题，整篇靠自然段推进。",
                "结尾只收在一个还没完全处理完的小动作上，不提问、不祝福、不列清单。",
            ],
            "expression_constraints": ["不要用口号式收尾"],
            "benchmark_summary": "只借处境类型，不借标题骨架和推进顺序。",
        },
        "benchmarks": [],
        "outline": {
            "hook": "她盯着输入框，手指停在发送键上方。",
            "outline_body": "1. 夜里的卡顿\n2. 白天为什么一直在往外送\n3. 最后只剩一点点能留给自己",
        },
    }

    outline_template = build_outline_prompt(payload)
    draft_template = build_draft_prompt(payload)

    assert "如果策略包已经给出替代骨架，大纲必须优先服从这套新骨架" in outline_template.instructions
    assert "替代骨架：" in outline_template.prompt
    assert "正文默认不用分节小标题" in outline_template.prompt
    assert "如果策略包已经给出替代骨架，正文必须沿着这套新骨架推进" in draft_template.instructions
    assert "不要回到参考文常见的标题、小节和收尾节拍" in draft_template.instructions
    assert "结尾只收在一个还没完全处理完的小动作上，不提问、不祝福、不列清单。" in draft_template.prompt


def test_build_draft_prompt_includes_detector_originality_rules() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 深夜关系观察",
            "topic_title": "回完所有人的消息，轮到自己时却开不了口",
            "topic_angle": "情绪耗尽",
            "project_title": "深夜耗尽稿",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "她盯着输入框，手指停在发送键上方。",
                "outline_body": "1. 夜里的卡顿\n2. 白天为什么一直在往外送\n3. 最后只剩一点点能留给自己",
            },
        }
    )

    assert "正文至少完成两条看得见的因果链" in template.instructions
    assert "每 2 到 3 段至少复用一个稳定抓手" in template.instructions
    assert "少用“生活、感情、成长、幸福、重要的事”这类对所有人都成立的大词" in template.instructions
    assert "允许出现少量偏说明性的句子，把事情为什么会变成这样讲清楚" in template.instructions
    assert "如果一个段落只剩观点，就把它改写成过程" in template.instructions
    assert "不要把正文切成一串一两句的宣布式小段" in template.instructions
    assert "允许保留 1 到 3 个很短的独立段" in template.instructions
    assert "如果要单独留一个短段，它应该像阻力线或动作残留" in template.instructions
    assert "像“这里面有条很清楚的线”“更麻烦的是”“有些代价是延迟出现的”这类负责宣布观点的过渡句" in template.instructions
    assert "不要把一句消息、对话、短信或引用写成整篇反复出现的展示段" in template.instructions
    assert "不要把“解释也来得很快：……”这类独立解释短段写成固定排版习惯" in template.instructions
    assert "避免连续三段以上都从同一个主语起手" in template.instructions
    assert "不要把“先是……后来……再后来……”写成整理得过于整齐的梳理链" in template.instructions
    assert "别把能证明人还在现场的毛边全修掉" in template.instructions


def test_build_topic_prompt_adds_internal_pressure_guard_for_tracked_article() -> None:
    template = build_topic_prompt(
        {
            "source_type": "tracked_article",
            "source_ref_slug": "wechat-mp-demo-2",
            "source_name": "手动录入",
            "article_title": "不纠缠，是成年人最好的治愈",
            "author": "未知",
            "summary": "文章重点是心事、执念、内耗和生活节奏失衡，不是关系摊牌或沟通修复。",
            "structure_notes": "从心绪整理进入，再落到自我照料和生活排序。",
            "tags": ["self-care"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "不要把选题收窄成亲密关系摊牌、情侣冷战、深夜等回复或“怎么把话说清楚”的沟通修复主线。" in template.instructions
    assert "标题和切入角度优先围绕身体提醒、生活次序、工作/家人/自我照料的接口重建" in template.instructions


def test_build_outline_prompt_adds_internal_pressure_guard_for_tracked_article() -> None:
    template = build_outline_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "心里事情太多的时候，人为什么会先把自己往后放",
            "topic_angle": "从一次把体检和回电话都顺手往后推的瞬间切入，写生活排序如何慢慢失衡。",
            "project_title": "心事排序稿",
            "source_type": "tracked_article",
            "reference_article_title": "不纠缠，是成年人最好的治愈",
            "reference_article_summary": "文章重点是心事、执念、内耗和生活节奏失衡，不是关系摊牌或沟通修复。",
            "reference_article_structure_notes": "从心绪整理进入，再落到自我照料和生活排序。",
            "reference_article_tags": ["self-care"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "大纲不要自动改写成亲密关系冲突处理流程。" in template.instructions
    assert "不要让“深夜等回复 / 当晚说清楚 / 第二天再沟通”变成主线。" in template.instructions
    assert "优先把压力点落在身体提醒、生活排序、工作节奏、家人回应或自我照料被推迟的地方。" in template.instructions


def test_build_draft_prompt_adds_internal_pressure_guard_for_tracked_article() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "心里事情太多的时候，人为什么会先把自己往后放",
            "topic_angle": "从一次把体检和回电话都顺手往后推的瞬间切入，写生活排序如何慢慢失衡。",
            "project_title": "心事排序稿",
            "source_type": "tracked_article",
            "reference_article_title": "不纠缠，是成年人最好的治愈",
            "reference_article_summary": "文章重点是心事、执念、内耗和生活节奏失衡，不是关系摊牌或沟通修复。",
            "reference_article_structure_notes": "从心绪整理进入，再落到自我照料和生活排序。",
            "reference_article_tags": ["self-care"],
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "体检提醒亮了一下，她先把页面划掉。",
                "outline_body": "1. 被顺手往后放的接口\n2. 为什么总轮不到自己\n3. 日常排序怎么慢慢歪掉",
            },
        }
    )

    assert "正文不要自动收窄成亲密关系摊牌、深夜删消息、等回复或关系修复主线。" in template.instructions
    assert "不要把伴侣/对话对象写成唯一主场景。" in template.instructions
    assert "不要写成“深夜卡住 -> 回想过去 -> 第二天沟通 -> 关系缓和”的完整修复弧线。" in template.instructions


def test_build_assets_prompt_includes_style_and_review_feedback() -> None:
    template = build_assets_prompt(
        {
            "trend_title": "办公室倦怠修复",
            "topic_title": "办公室倦怠不是懒，是你的身心在报警",
            "topic_angle": "情绪识别",
            "project_title": "办公室倦怠修复周更",
            "tone_profile": TONE_PROFILE,
            "review_comment": "封面文案太满，收一点。",
            "draft": {
                "title": "越在乎的人，为什么越想在关系里反复确认",
                "body_markdown": "# 标题\n\n正文",
            },
        }
    )

    assert "风格档案：女性成长克制陪伴风" in template.prompt
    assert "审核修改意见：封面文案太满，收一点。" in template.prompt
    assert "正文标题：越在乎的人，为什么越想在关系里反复确认" in template.prompt
    assert "21:9 横版公众号头图" in template.instructions
    assert "禁止输出竖版、9:16、手机海报、竖构图" in template.instructions
    assert "明确写成 21:9 横版公众号头图或横向宽画幅构图" in template.prompt
    assert "禁止出现竖版、9:16、手机海报、竖构图等冲突词" in template.prompt


def test_build_publish_package_prompt_includes_style_and_asset_context() -> None:
    template = build_publish_package_prompt(
        {
            "project_title": "办公室倦怠修复周更",
            "tone_profile": TONE_PROFILE,
            "review_comment": "摘要需要更克制。",
            "draft": {
                "title": "越在乎的人，为什么越想在关系里反复确认",
                "body_markdown": "# 标题\n\n正文",
            },
            "assets": {
                "cover_copy": "越在乎，越想确认",
                "social_teaser": "真正让人反复确认的，不只是一句话。",
                "title_options": ["标题一", "标题二", "标题三"],
            },
        }
    )

    assert "项目标题：办公室倦怠修复周更" in template.prompt
    assert "风格档案：女性成长克制陪伴风" in template.prompt
    assert "标题备选：标题一 / 标题二 / 标题三" in template.prompt
    assert "审核修改意见：摘要需要更克制。" in template.prompt


def test_build_cover_image_prompt_mentions_wide_ratio_and_original_idea() -> None:
    prompt = build_cover_image_prompt({"cover_prompt": "close-up portrait, soft light, emotional realism"})

    assert "21:9" in prompt
    assert "横版封面图" in prompt
    assert "原始创意提示词：close-up portrait, soft light, emotional realism" in prompt


def test_stage_templates_share_domain_pack_but_keep_stage_specific_roles() -> None:
    outline_template = build_outline_prompt(
        {
            "trend_title": "办公室倦怠修复",
            "topic_title": "办公室倦怠不是懒，是你的身心在报警",
            "topic_angle": "情绪识别",
            "project_title": "办公室倦怠修复周更",
            "tone_profile": TONE_PROFILE,
        }
    )
    draft_template = build_draft_prompt(
        {
            "trend_title": "办公室倦怠修复",
            "topic_title": "办公室倦怠不是懒，是你的身心在报警",
            "topic_angle": "情绪识别",
            "project_title": "办公室倦怠修复周更",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "先接住身体发出的报警",
                "outline_body": "1. 崩住的日常\n2. 被忽略的疲惫\n3. 慢慢恢复秩序",
            },
        }
    )
    publish_template = build_publish_package_prompt(
        {
            "project_title": "办公室倦怠修复周更",
            "tone_profile": TONE_PROFILE,
            "draft": {
                "title": "越在乎的人，为什么越想在关系里反复确认",
                "body_markdown": "# 标题\n\n正文",
            },
            "assets": {
                "cover_copy": "越在乎，越想确认",
                "social_teaser": "真正让人反复确认的，不只是一句话。",
                "title_options": ["标题一", "标题二", "标题三"],
            },
        }
    )

    for instructions in (outline_template.instructions, draft_template.instructions, publish_template.instructions):
        assert "女性情感成长" in instructions
        assert "克制" in instructions

    assert "内容策划编辑" in outline_template.instructions
    assert "正文作者" in draft_template.instructions
    assert "发布编辑" in publish_template.instructions
    assert "先设计一个具体、可感知的开篇瞬间或动作入口" in outline_template.instructions
    assert "开篇钩子不要写成“很多关系不是……”" in outline_template.instructions
    assert "大纲标题和段落小标题不要使用“不是A，而是B”" in outline_template.instructions
    assert "原创不是把现成观点换一批近义词，而是重新建立观察路径、场景重心和句子节奏" in draft_template.instructions
    assert "不要先复述题眼或给观点下定义" in draft_template.instructions
    assert "避免每段都写成“观点句 + 解释句”的模板结构" in draft_template.instructions
    assert "句子节奏要有长短变化和呼吸感" in draft_template.instructions


def test_build_outline_prompt_includes_adopted_strategy_context_when_present() -> None:
    template = build_outline_prompt(
        {
            "trend_title": "关系边界重设",
            "topic_title": "总想解释的人，为什么最后越来越不想开口",
            "topic_angle": "边界表达",
            "project_title": "关系边界重设系列",
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "problem_statement_markdown": "# 问题说明书\n\n## 现象\n- 小失望不断积累。",
                "clarified_problem": "这篇文章要解释，为什么很多关系不是毁在大冲突，而是毁在一次次没被接住的小失望。",
                "observed_phenomenon": "她明明有很多话想说，最后却总在对话框里删掉。",
                "writing_goal": "把“为什么越想解释越不想开口”讲清楚。",
                "target_reader_situation": "在关系里想解释，却越来越不想开口的人",
                "core_conflict": "越想被理解，越容易把话咽回去。",
                "constraints": [
                    "不要写成标准答案式议论文",
                    "不要复用参考文章的段落顺序",
                ],
                "feedback_entry": "读者看完后，应该先认出自己不是矫情，而是长期失望后的收缩。",
            },
            "strategy_card": {
                "reader_situation": "在关系里想解释，却越来越不想开口的人",
                "point_of_view": "不教训，不站高位，只把失望是怎么累出来的讲清楚",
                "conflict_frame": "不是大吵一架，而是一次次想开口又收回去",
                "emotional_path": "从委屈和停顿进入，慢慢走到能重新开口",
                "structure_mode": "single_window_scene",
                "opening_move": "先写删掉又重打的一次对话瞬间。",
                "body_shift": "先拆想说又收回去的机制，再讲失望如何积累。",
                "ending_move": "结尾回到一次更小但真实的开口动作。",
                "expression_constraints": [
                    "不要用口号式收尾",
                    "不要复用不是A而是B的对称判断句",
                ],
                "divergence_axes": [
                    "标题骨架要换",
                    "中段推进顺序必须重排",
                ],
                "execution_checklist": [
                    "标题不要复述题眼",
                    "开头先出现动作",
                    "结尾不要喊话",
                ],
                "benchmark_summary": "开头先落动作和停顿，中段再进入判断。",
                "strategy_markdown": "# 创作策略卡\n\n## 写给谁\n- 在关系里想解释的人",
            },
            "benchmarks": [
                {
                    "reference_label": "深夜关系观察",
                    "borrow_focus": "开头的处境进入和中段停顿节奏",
                    "avoid_focus": "不要复用对方的判断句和结尾收束",
                }
            ],
        }
    )

    assert "创作策略包（执行摘要）：" in template.prompt
    assert "问题澄清：这篇文章要解释，为什么很多关系不是毁在大冲突，而是毁在一次次没被接住的小失望。" in template.prompt
    assert "观察到的现象：她明明有很多话想说，最后却总在对话框里删掉。" in template.prompt
    assert "写作目标：把“为什么越想解释越不想开口”讲清楚。" in template.prompt
    assert "读者处境：在关系里想解释，却越来越不想开口的人" in template.prompt
    assert "硬约束：不要写成标准答案式议论文 / 不要复用参考文章的段落顺序" in template.prompt
    assert "反馈入口：读者看完后，应该先认出自己不是矫情，而是长期失望后的收缩。" in template.prompt
    assert "叙述视角：不教训，不站高位，只把失望是怎么累出来的讲清楚" in template.prompt
    assert "冲突框架：不是大吵一架，而是一次次想开口又收回去" in template.prompt
    assert "情绪路径：从委屈和停顿进入，慢慢走到能重新开口" in template.prompt
    assert "结构模式：单场景窄时窗推进" in template.prompt
    assert "结构执行：前半篇尽量守住同一段时间和同一处境现场，不要均匀拆成几个并列观点段。" in template.prompt
    assert "开头动作：先写删掉又重打的一次对话瞬间。" in template.prompt
    assert "中段推进：先拆想说又收回去的机制，再讲失望如何积累。" in template.prompt
    assert "结尾动作：结尾回到一次更小但真实的开口动作。" in template.prompt
    assert "表达约束：不要用口号式收尾 / 不要复用不是A而是B的对称判断句" in template.prompt
    assert "主动拉开距离：标题骨架要换 / 中段推进顺序必须重排" in template.prompt
    assert "执行检查：标题不要复述题眼 / 开头先出现动作 / 结尾不要喊话" in template.prompt
    assert "参考基准：开头先落动作和停顿，中段再进入判断。" in template.prompt
    assert "可借动作：开头的处境进入和中段停顿节奏" in template.prompt
    assert "避开项：不要复用对方的判断句和结尾收束" in template.prompt
    assert "原创距离最低要求：同时改掉标题骨架、开头入口、中段推进顺序和结尾动作，缺一项就继续重写。" in template.prompt
    assert "策略卡全文：" not in template.prompt
    assert "# 创作策略卡" not in template.prompt
    assert "# 问题说明书" not in template.prompt
    assert "基准参考 1：深夜关系观察" not in template.prompt
    assert "执行时只保留这些策略结论" in template.prompt


def test_build_draft_prompt_includes_strategy_package_section_when_present() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "关系边界重设",
            "topic_title": "总想解释的人，为什么最后越来越不想开口",
            "topic_angle": "边界表达",
            "project_title": "关系边界重设系列",
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "problem_statement_markdown": "# 问题说明书\n\n## 现象\n- 读者不是不知道道理，而是开不了口。",
                "clarified_problem": "这篇文章要解释，为什么很多关系最后耗在一次次没说出口的失望里。",
                "observed_phenomenon": "她看到消息提醒时，先想到的不是回复，而是又要不要解释。",
                "writing_goal": "把“失望是怎么一点点把人变沉默的”讲清楚。",
                "target_reader_situation": "在关系里想解释，却越来越不想开口的人",
                "core_conflict": "越想被理解，越容易把真正想说的话咽回去。",
                "constraints": [
                    "不要做近义词改写",
                    "不要写成情感鸡汤",
                ],
                "feedback_entry": "读者看完后，应该先认出自己为什么一直卡在解释门口。",
            },
            "strategy_card": {
                "reader_situation": "在关系里想解释，却越来越不想开口的人",
                "point_of_view": "不教训，只把失望怎么累出来讲清楚",
                "conflict_frame": "不是突然爆炸，而是一次次想开口又收回去",
                "emotional_path": "从停顿进入，慢慢走到能重新开口",
                "structure_mode": "single_window_scene",
                "opening_move": "开头先写删了又重打的一次消息。",
                "body_shift": "中段先写为什么越来越不想说，再讲失望如何叠起来。",
                "ending_move": "结尾回到一次更小但真实的开口动作。",
                "expression_constraints": [
                    "不要用口号式收尾",
                    "不要复用不是A而是B的对称判断句",
                ],
                "divergence_axes": [
                    "标题骨架要换",
                    "结尾动作要换",
                ],
                "execution_checklist": [
                    "标题换成新处境",
                    "开头先落动作",
                    "结尾不要升华",
                ],
                "benchmark_summary": "先借处境类型，再换掉推进顺序和结尾动作。",
                "strategy_markdown": "# 创作策略卡\n\n## 写作动作\n- 开头先写动作，再进入判断。",
            },
            "benchmarks": [
                {
                    "reference_label": "深夜关系观察",
                    "borrow_focus": "具体处境入口 / 中段从场景转判断的节奏",
                    "avoid_focus": "不要复用原标题骨架、原文判断句和段落顺序",
                }
            ],
            "outline": {
                "hook": "她把消息删了又重打。",
                "outline_body": "1. 停顿\n2. 为什么越来越不想说\n3. 重新开口",
            },
        }
    )

    assert "创作策略包（执行摘要）：" in template.prompt
    assert "问题澄清：这篇文章要解释，为什么很多关系最后耗在一次次没说出口的失望里。" in template.prompt
    assert "观察到的现象：她看到消息提醒时，先想到的不是回复，而是又要不要解释。" in template.prompt
    assert "写作目标：把“失望是怎么一点点把人变沉默的”讲清楚。" in template.prompt
    assert "读者处境：在关系里想解释，却越来越不想开口的人" in template.prompt
    assert "硬约束：不要做近义词改写 / 不要写成情感鸡汤" in template.prompt
    assert "反馈入口：读者看完后，应该先认出自己为什么一直卡在解释门口。" in template.prompt
    assert "结构模式：单场景窄时窗推进" in template.prompt
    assert "结构执行：前半篇尽量守住同一段时间和同一处境现场，不要均匀拆成几个并列观点段。" in template.prompt
    assert "开头动作：开头先写删了又重打的一次消息。" in template.prompt
    assert "中段推进：中段先写为什么越来越不想说，再讲失望如何叠起来。" in template.prompt
    assert "结尾动作：结尾回到一次更小但真实的开口动作。" in template.prompt
    assert "主动拉开距离：标题骨架要换 / 结尾动作要换" in template.prompt
    assert "执行检查：标题换成新处境 / 开头先落动作 / 结尾不要升华" in template.prompt
    assert "可借动作：具体处境入口 / 中段从场景转判断的节奏" in template.prompt
    assert "避开项：不要复用原标题骨架、原文判断句和段落顺序" in template.prompt
    assert "原创距离最低要求：同时改掉标题骨架、开头入口、中段推进顺序和结尾动作，缺一项就继续重写。" in template.prompt
    assert "策略卡全文：" not in template.prompt
    assert "# 创作策略卡" not in template.prompt
    assert "# 问题说明书" not in template.prompt
    assert "基准参考 1：深夜关系观察" not in template.prompt
    assert "若策略包要求单场景窄时窗推进，前半篇尽量守住同一段时间和同一处境现场，不要平均分成几个对称分论点。" in template.instructions
    assert "第一屏先落到能摸到的物件、界面、动作或身体反应，不要先下抽象判断。" in template.instructions
    assert "结尾只收在一个更小的动作、余波或没完全处理完的现实阻力上，不要急着升华。" in template.instructions


def test_build_draft_prompt_describes_fragment_chain_structure_mode() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "总把自己往后放的人，生活为什么会慢慢失序",
            "topic_angle": "从推迟和顺延的日常动作切入，解释生活排序为什么会慢慢倒过来。",
            "project_title": "别把日子过反了",
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "problem_statement_markdown": "# 问题说明书\n\n## 现象\n- 她总把照顾自己这件事顺手往后挪。",
                "clarified_problem": "这篇文章要解释，为什么一个人会把真正重要的事不断往后放。",
                "observed_phenomenon": "消息能回，文件能补，饭和体检却总往后挪。",
                "writing_goal": "把“推迟”是怎么慢慢改写生活排序的讲清楚。",
                "target_reader_situation": "总把自己往后排的人",
                "core_conflict": "越想先把外面的事处理完，越容易把自己的余量耗空。",
                "constraints": ["不要写成励志鸡汤"],
                "feedback_entry": "读者应该先认出自己一直在顺手推迟什么。",
            },
            "strategy_card": {
                "reader_situation": "总把自己往后排的人",
                "point_of_view": "不急着劝人改变，先把推迟是怎么发生的讲清楚。",
                "conflict_frame": "不是突然失控，而是一次次顺手往后挪。",
                "emotional_path": "从普通小事进入，慢慢看到真正被牺牲掉的部分。",
                "structure_mode": "fragment_chain_observation",
                "opening_move": "开头先落一个被顺手往后挪开的普通接口。",
                "body_shift": "中段串起 2 到 4 个现实接口，让每个碎片承担不同压力。",
                "ending_move": "结尾回到一个还没完全处理完的小动作上。",
                "expression_constraints": ["不要用口号式收尾"],
                "divergence_axes": ["不要把原文压成一个连续主角场景"],
                "execution_checklist": ["是否串起了 2 到 4 个现实接口"],
                "benchmark_summary": "借处境类型，不借原文段落顺序。",
                "strategy_markdown": "# 创作策略卡\n\n## 写作动作\n- 先写普通接口，再慢慢显出代价。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "体检预约又被她顺手改了时间。",
                "outline_body": "1. 被顺手往后挪开的事\n2. 为什么总轮不到自己\n3. 最后留下来的代价",
            },
        }
    )

    assert "结构模式：碎片回环观察推进" in template.prompt
    assert "结构执行：围绕同一个问题串起 2 到 4 个现实接口" in template.prompt
    assert "若策略包要求碎片回环观察推进，正文围绕同一个问题串起 2 到 4 个现实接口" in template.instructions
    assert "不要把这 2 到 4 个接口顺着时间缝成一个人从早到晚一路推进的完整日程线" in template.instructions


def test_build_draft_prompt_compacts_tracked_article_strategy_payload() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "总把自己往后放的人，生活为什么会慢慢失序",
            "topic_angle": LONG_TRACKED_TOPIC_ANGLE,
            "project_title": "别把日子过反了",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "compact_strategy_mode": True,
            "problem_brief": {
                "clarified_problem": "这篇文章要解释，为什么一个人会把真正重要的事不断往后放，直到生活排序和情绪余量都被慢慢改写。",
                "observed_phenomenon": "消息能回、文件能补、工作能顶，饭和体检却总被顺手往后挪，最后连关系里的回应都开始拖延。",
                "writing_goal": "把“推迟”是怎么慢慢改写生活排序的讲清楚。",
                "target_reader_situation": "总把自己往后排、总说等有空再处理的人。",
                "core_conflict": "越想先把外面的事处理完，越容易把自己的余量耗空。",
                "constraints": ["不要写成励志鸡汤", "不要复制参考文顺序"],
                "feedback_entry": "读者应该先认出自己一直在顺手推迟什么。",
            },
            "strategy_card": {
                "reader_situation": "总把自己往后排、总说等有空再处理的人。",
                "point_of_view": "不急着劝人改变，先把推迟是怎么发生的讲清楚。",
                "conflict_frame": "不是突然失控，而是一次次顺手往后挪。",
                "emotional_path": "从普通小事进入，慢慢看到真正被牺牲掉的部分。",
                "structure_mode": "fragment_chain_observation",
                "opening_move": "开头先落一个被顺手往后挪开的普通接口。",
                "body_shift": "中段串起 2 到 4 个现实接口，让每个碎片承担不同压力，并且不要压成标准答案式并列分论点。",
                "ending_move": "结尾回到一个还没完全处理完的小动作上。",
                "expression_constraints": ["不要用口号式收尾", "不要复用不是A而是B的对称判断句"],
                "divergence_axes": ["不要把原文压成一个连续主角场景", "开头入口和结尾动作都要换"],
                "execution_checklist": ["是否串起了 2 到 4 个现实接口", "是否保留现实阻力", "是否避免整齐分论点"],
                "benchmark_summary": "只借处境类型，不借原文标题骨架、段落顺序和结尾判断。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "体检预约又被她顺手改了时间，手机屏亮了一下，她看见提醒，却先把页面滑掉。",
                "outline_body": (
                    "1. 先落一个被顺手往后挪开的普通接口，不急着解释大道理，只让那一下停顿先出现。\n"
                    "2. 串起消息、体检、关系回应这几个现实接口，让每个碎片承担不同压力，不要平均写成并列道理。\n"
                    "3. 解释为什么一个人会习惯先处理外面的要求，再把自己的身体和关系往后顺延。\n"
                    "4. 回到一个还没完全解决的小动作上，停在那里，不做口号式总结。"
                ),
            },
        }
    )

    assert "切入角度：已在下方策略包中消化" in template.prompt
    assert "大纲锚点：" in template.prompt
    assert "大纲内容：" not in template.prompt
    assert "执行原则：沿着这些策略结论写，不回收参考文原句、原顺序和原结尾。" in template.prompt
    assert "执行协议：" in template.prompt
    assert LONG_TRACKED_TOPIC_ANGLE not in template.prompt
    assert "少写万能道理，多写日常接口、局部机制和现实阻力" in template.instructions
    assert "不要连续宣布观点，不要系统性补氛围场景，也不要机械扩句增肥。" in template.instructions
    assert "默认优先保留单场景或窄场景，不要为了显得完整主动补成双线并跑或多案例铺开。" in template.instructions
    assert "不要把稿子收成已经准备进编辑排版的完整示范文" in template.instructions
    assert "它应该像作者仍在推进中的一版，不是已经准备进编辑排版的完整示范文。" in template.instructions
    assert len(template.instructions) < 3200
    assert len(template.prompt) < 2600


def test_build_draft_prompt_uses_full_strategy_payload_by_default_for_tracked_article() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "总把自己往后放的人，生活为什么会慢慢失序",
            "topic_angle": LONG_TRACKED_TOPIC_ANGLE,
            "project_title": "别把日子过反了",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "clarified_problem": "这篇文章要解释，为什么一个人会把真正重要的事不断往后放，直到生活排序和情绪余量都被慢慢改写。",
                "observed_phenomenon": "消息能回、文件能补、工作能顶，饭和体检却总被顺手往后挪，最后连关系里的回应都开始拖延。",
                "writing_goal": "把“推迟”是怎么慢慢改写生活排序的讲清楚。",
                "target_reader_situation": "总把自己往后排、总说等有空再处理的人。",
                "core_conflict": "越想先把外面的事处理完，越容易把自己的余量耗空。",
                "constraints": ["不要写成励志鸡汤", "不要复制参考文顺序"],
                "feedback_entry": "读者应该先认出自己一直在顺手推迟什么。",
            },
            "strategy_card": {
                "reader_situation": "总把自己往后排、总说等有空再处理的人。",
                "point_of_view": "不急着劝人改变，先把推迟是怎么发生的讲清楚。",
                "conflict_frame": "不是突然失控，而是一次次顺手往后挪。",
                "emotional_path": "从普通小事进入，慢慢看到真正被牺牲掉的部分。",
                "structure_mode": "fragment_chain_observation",
                "opening_move": "开头先落一个被顺手往后挪开的普通接口。",
                "body_shift": "中段串起 2 到 4 个现实接口，让每个碎片承担不同压力，并且不要压成标准答案式并列分论点。",
                "ending_move": "结尾回到一个还没完全处理完的小动作上。",
                "expression_constraints": ["不要用口号式收尾", "不要复用不是A而是B的对称判断句"],
                "divergence_axes": ["不要把原文压成一个连续主角场景", "开头入口和结尾动作都要换"],
                "execution_checklist": ["是否串起了 2 到 4 个现实接口", "是否保留现实阻力", "是否避免整齐分论点"],
                "benchmark_summary": "只借处境类型，不借原文标题骨架、段落顺序和结尾判断。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "体检预约又被她顺手改了时间，手机屏亮了一下，她看见提醒，却先把页面滑掉。",
                "outline_body": (
                    "1. 先落一个被顺手往后挪开的普通接口，不急着解释大道理，只让那一下停顿先出现。\n"
                    "2. 串起消息、体检、关系回应这几个现实接口，让每个碎片承担不同压力，不要平均写成并列道理。\n"
                    "3. 解释为什么一个人会习惯先处理外面的要求，再把自己的身体和关系往后顺延。\n"
                    "4. 回到一个还没完全解决的小动作上，停在那里，不做口号式总结。"
                ),
            },
        }
    )

    assert "大纲内容：" in template.prompt
    assert "大纲锚点：" not in template.prompt
    assert "观察到的现象：" in template.prompt
    assert "观察焦点：" not in template.prompt
    assert "原创距离最低要求：同时改掉标题骨架、开头入口、中段推进顺序和结尾动作，缺一项就继续重写。" in template.prompt
    assert "执行时只保留这些策略结论，不回看参考文章原始标题、摘要、段落顺序或问题说明书全文。" in template.prompt
    assert "写前约束：" in template.prompt
    assert "拉开距离检查：" in template.prompt
    assert "写作执行：" in template.prompt
    assert "返回前自检：" in template.prompt
    assert "原创不是把现成观点换一批近义词，而是重新建立观察路径、场景重心和句子节奏。" in template.instructions
    assert "输出前必须做一次静默自检" in template.instructions
    assert len(template.instructions) > 3200


def test_build_draft_prompt_compacts_tracked_article_polish_payload() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "总说等忙完这一阵，却开始看见身体发出的提醒",
            "topic_angle": LONG_TRACKED_TOPIC_ANGLE,
            "project_title": "别把日子过反了",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "compact_polish_mode": True,
            "polish_instruction": "把单句敲钟段并回过程段，重写开头和结尾，避免固定短长节拍。",
            "allow_structure_recomposition": True,
            "preserve_structure_anchors": False,
            "problem_brief": {
                "clarified_problem": "这篇文章要解释，为什么一个人会把真正重要的事不断往后放。",
                "observed_phenomenon": "消息能回、文件能补、工作能顶，饭和体检却总被顺手往后挪。",
                "writing_goal": "把“推迟”是怎么慢慢改写生活排序的讲清楚。",
                "target_reader_situation": "总把自己往后排的人",
                "core_conflict": "越想先把外面的事处理完，越容易把自己的余量耗空。",
                "constraints": ["不要写成励志鸡汤"],
                "feedback_entry": "读者应该先认出自己一直在顺手推迟什么。",
            },
            "strategy_card": {
                "reader_situation": "总把自己往后排的人",
                "point_of_view": "不急着劝人改变，先把推迟是怎么发生的讲清楚。",
                "conflict_frame": "不是突然失控，而是一次次顺手往后挪。",
                "emotional_path": "从普通小事进入，慢慢看到真正被牺牲掉的部分。",
                "structure_mode": "fragment_chain_observation",
                "opening_move": "开头先落一个被顺手往后挪开的普通接口。",
                "body_shift": "中段串起 2 到 4 个现实接口，让每个碎片承担不同压力。",
                "ending_move": "结尾回到一个还没完全处理完的小动作上。",
                "expression_constraints": ["不要用口号式收尾"],
                "divergence_axes": ["不要把原文压成一个连续主角场景"],
                "execution_checklist": ["是否串起了 2 到 4 个现实接口"],
                "benchmark_summary": "只借处境类型，不借原文段落顺序。",
            },
            "benchmarks": [],
            "draft": {
                "title": "等忙完这一阵的人，为什么最后先看见的是身体在变慢",
                "body_markdown": (
                    "电梯门快合上的时候，她抬了脚，又收回来。\n\n"
                    "电脑包勒着手指，手机上那句上午会别迟到还亮着。她脑子里冒出来的还是那句老话：等忙完这阵。\n\n"
                    "泡沫刚碰到舌根，胃里忽然往上一顶。她扶着洗手台，还是把请假那个念头压了回去。\n\n"
                    "后面几天，钥匙忘带、时间看错、回到家以后不想说话，全都被她归进同一句：最近太累。\n\n"
                    "真正让人难受的，不是忙，而是已经慢下来很久，却还在逼自己照常运转。"
                ),
            },
            "outline": {
                "hook": "体检预约又被她顺手改了时间。",
                "outline_body": "1. 被顺手往后挪开的事\n2. 为什么总轮不到自己\n3. 最后留下来的代价",
            },
        }
    )

    assert "创作策略包（执行摘要）：" in template.prompt
    assert "执行原则：沿着这些策略结论写，不回收参考文原句、原顺序和原结尾。" in template.prompt
    assert "这不是局部润色，而是去模板化精修。" in template.instructions
    assert "宁可停在还没完全处理完的小动作、现实阻力或关系余波上，也不要主动补一个漂亮收束段。" in template.instructions
    assert "当前任务是基于现有正文精修，不是按大纲重写一篇新稿。" in template.instructions
    assert "这次允许更大幅度地调换中段顺序、合并段落和改小节职责。" in template.instructions
    assert "如果当前草稿已经是单场景或窄场景低风险基线，不要为了显得更完整主动扩成双线并跑、多案例铺开或更成熟的示范文。" in template.instructions
    assert "优先做窄修：只调整局部判断句、过顺的连接、过满的结尾和少数模板化句子。" in template.instructions
    assert len(template.instructions) < 5200
    assert len(template.prompt) < 3600


def test_outline_prompt_hides_reference_article_copy_surface_after_topic_stage() -> None:
    template = build_outline_prompt(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "先接住失望，再谈道理",
            "topic_angle": "关系修复",
            "project_title": "慢修复关系稿",
            "source_type": "tracked_article",
            "reference_article_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "reference_article_author": "北岛",
            "reference_article_source_name": "夜读关系实验室",
            "reference_article_summary": "从关系修复案例提炼表达顺序。",
            "reference_article_structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "reference_article_tags": ["表达修复", "关系修复"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "参考文章来源线索（仅用于确认赛道与冲突，不得继续沿用原文骨架）：" in template.prompt
    assert "来源账号：夜读关系实验室" in template.prompt
    assert "主题标签：表达修复 / 关系修复" in template.prompt
    assert "参考文章标题：" not in template.prompt
    assert "参考文章摘要：" not in template.prompt
    assert "参考文章结构备注：" not in template.prompt
    assert "参考文章已经在选题阶段被消化成当前选题和角度" in template.instructions
    assert "大纲必须同时拉开至少四处距离" in template.instructions


def test_outline_prompt_hides_reference_article_surface_once_strategy_package_exists() -> None:
    template = build_outline_prompt(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "先接住失望，再谈道理",
            "topic_angle": LONG_TRACKED_TOPIC_ANGLE,
            "project_title": "慢修复关系稿",
            "source_type": "tracked_article",
            "reference_article_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "reference_article_author": "北岛",
            "reference_article_source_name": "夜读关系实验室",
            "reference_article_summary": "从关系修复案例提炼表达顺序。",
            "reference_article_structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "reference_article_tags": ["表达修复", "关系修复"],
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "clarified_problem": "这篇文章要解释，为什么很多关系修复不是输在不会说，而是输在没先接住失望。",
                "target_reader_situation": "总想解释却把时机越拖越晚的人",
                "core_conflict": "越急着说明白，越容易错过真正该接住的那一下。",
            },
            "strategy_card": {
                "reader_situation": "总想解释却把时机越拖越晚的人",
                "point_of_view": "先把失望怎么积出来讲清楚，不急着给答案",
                "conflict_frame": "不是缺道理，而是总在该接住的时候先去解释",
                "emotional_path": "从停顿和收回动作进入，再慢慢走到能重新开口",
                "expression_constraints": [
                    "不要用口号式收尾",
                ],
                "benchmark_summary": "只借处境类型，不借标题骨架和推进顺序。",
            },
            "benchmarks": [],
        }
    )

    assert "参考文章来源线索（仅用于确认赛道与冲突，不得继续沿用原文骨架）：" not in template.prompt
    assert "来源账号：夜读关系实验室" not in template.prompt
    assert "作者：北岛" not in template.prompt
    assert "主题标签：表达修复 / 关系修复" not in template.prompt
    assert "参考文章已在问题说明书和策略卡阶段完成消化。" in template.prompt
    assert "从这里开始，不再提供任何来源账号、标题、摘要、标签或结构线索。" in template.prompt
    assert "切入角度：已在下方策略包中消化，执行时不要回收原始长说明。" in template.prompt
    assert LONG_TRACKED_TOPIC_ANGLE not in template.prompt
    assert "最近一次改期见的人是谁" not in template.prompt


def test_draft_prompt_hides_reference_article_surface_once_strategy_package_exists() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "先接住失望，再谈道理",
            "topic_angle": LONG_TRACKED_TOPIC_ANGLE,
            "project_title": "慢修复关系稿",
            "source_type": "tracked_article",
            "reference_article_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "reference_article_author": "北岛",
            "reference_article_source_name": "夜读关系实验室",
            "reference_article_summary": "从关系修复案例提炼表达顺序。",
            "reference_article_structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "reference_article_tags": ["表达修复", "关系修复"],
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "clarified_problem": "这篇文章要解释，为什么很多关系修复不是输在不会说，而是输在没先接住失望。",
                "target_reader_situation": "总想解释却把时机越拖越晚的人",
                "core_conflict": "越急着说明白，越容易错过真正该接住的那一下。",
            },
            "strategy_card": {
                "reader_situation": "总想解释却把时机越拖越晚的人",
                "point_of_view": "先把失望怎么积出来讲清楚，不急着给答案",
                "conflict_frame": "不是缺道理，而是总在该接住的时候先去解释",
                "emotional_path": "从停顿和收回动作进入，再慢慢走到能重新开口",
                "expression_constraints": [
                    "不要用口号式收尾",
                ],
                "benchmark_summary": "只借处境类型，不借标题骨架和推进顺序。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "她盯着那条消息，半天没按发送。",
                "outline_body": "1. 那一下没被接住\n2. 解释为什么越说越乱\n3. 重新开口前先做什么",
            },
        }
    )

    assert "参考文章来源线索（仅用于确认赛道与冲突，不得继续沿用原文骨架）：" not in template.prompt
    assert "来源账号：夜读关系实验室" not in template.prompt
    assert "作者：北岛" not in template.prompt
    assert "主题标签：表达修复 / 关系修复" not in template.prompt
    assert "参考文章已在问题说明书和策略卡阶段完成消化。" in template.prompt
    assert "从这里开始，不再提供任何来源账号、标题、摘要、标签或结构线索。" in template.prompt
    assert "切入角度：已在下方策略包中消化，执行时不要回收原始长说明。" in template.prompt
    assert LONG_TRACKED_TOPIC_ANGLE not in template.prompt
    assert "最近一次改期见的人是谁" not in template.prompt


def test_draft_prompt_includes_anti_ai_flavor_guardrails() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "办公室倦怠修复",
            "topic_title": "办公室倦怠不是懒，是你的身心在报警",
            "topic_angle": "情绪识别",
            "project_title": "办公室倦怠修复周更",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "先接住身体发出的报警",
                "outline_body": "1. 崩住的日常\n2. 被忽略的疲惫\n3. 慢慢恢复秩序",
            },
        }
    )

    assert "少用“不是A，是B”这类过于整齐的判断句" in template.instructions
    assert "标题禁止使用“不是A，而是B”或“不是A，只是B”这类对称判断句" in template.instructions
    assert "如果选题标题或参考文章标题已经含有这类句式，正文标题必须改成具体处境入口" in template.instructions
    assert "全篇最多保留 1 处“不是……”判断" in template.instructions
    assert "减少“第一步、第二步、第三步”式教程骨架" in template.instructions
    assert "不要为了显得完整而过度解释每一个判断" in template.instructions
    assert "这类一字量词全篇尽量控制在 5 处以内" in template.instructions
    assert "不要每隔一两段就单独插一个很短的判断段或敲钟段" in template.instructions
    assert "不要反复使用“短句点一下，下一段再长解释”的固定节拍" in template.instructions
    assert "至少留一段只停在观察、动作、关系变化或身体反应里" in template.instructions
    assert "不要把起因、机制、代价、转机一次性讲透" in template.instructions
    assert "结尾不要写成自查问卷、连续三连问" in template.instructions
    assert "如果需要留给读者动作，只保留一个很小的真实动作或余波" in template.instructions
    assert "输出前必须做一次静默自检" in template.instructions
    assert "如果超过上述限制，先重写超标段落" in template.instructions
    assert "不要在最终正文里写出自检过程" in template.instructions
    assert "套话风险" in template.instructions
    assert "结构模板风险" in template.instructions
    assert "句式节奏风险" in template.instructions
    assert "段落节拍风险" in template.instructions
    assert "解释型公众号 AI 腔" in template.instructions
    assert "答案先放这儿" in template.instructions
    assert "不要每段都写成“判断 + 解释 + 小结”" in template.instructions
    assert "抽象空话风险" in template.instructions
    assert "过度解释风险" in template.instructions
    assert "结尾口号风险" in template.instructions


def test_draft_prompt_hides_reference_article_copy_surface_after_outline_stage() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "先接住失望，再谈道理",
            "topic_angle": "关系修复",
            "project_title": "慢修复关系稿",
            "source_type": "tracked_article",
            "reference_article_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "reference_article_author": "北岛",
            "reference_article_source_name": "夜读关系实验室",
            "reference_article_summary": "从关系修复案例提炼表达顺序。",
            "reference_article_structure_notes": "案例开头 + 情绪拆解 + 动作建议。",
            "reference_article_tags": ["表达修复", "关系修复"],
            "outline": {
                "hook": "先接住情绪，不要急着摆道理",
                "outline_body": "1. 失望现场\n2. 常见误区\n3. 修复动作",
            },
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "参考文章来源线索（仅用于确认赛道与冲突，不得继续沿用原文骨架）：" in template.prompt
    assert "来源账号：夜读关系实验室" in template.prompt
    assert "主题标签：表达修复 / 关系修复" in template.prompt
    assert "参考文章标题：" not in template.prompt
    assert "参考文章摘要：" not in template.prompt
    assert "参考文章结构备注：" not in template.prompt
    assert "参考文章已经在选题和大纲阶段被消化" in template.instructions
    assert "起笔对象、主段顺序、案例排列和收束动作都必须重新组织" in template.instructions


def test_polish_prompt_includes_localized_stop_slop_rewrite_checklist() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "办公室倦怠修复",
            "topic_title": "工位上的那种累，先别急着怪自己",
            "topic_angle": "情绪识别",
            "project_title": "办公室倦怠修复周更",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "午休刚过，屏幕又亮了。",
                "outline_body": "1. 提示音\n2. 累从哪里来\n3. 怎么慢慢往回收",
            },
            "polish_instruction": "重写开头和结尾，降低模板感。",
            "draft": {
                "title": "旧标题",
                "body_markdown": "# 旧标题\n\n不是你太累，而是你一直没有停下来。",
            },
        }
    )

    assert "按 6 类中文公众号 AI 味风险逐项检查原稿" in template.instructions
    assert "先删掉万能抒情、整齐反转、教程分步和口号式结尾" in template.instructions
    assert "开头第一屏和每个保留小节的首段，优先沿用原稿已经出现的人物、案例、问题或判断进入" in template.instructions
    assert "如果原稿某一节本来直接进入人物案例、直接判断或一组并列例子，就保留这种直入方式" in template.instructions
    assert "不要为了显得自然而额外虚构新人物、新职业、新病症、新城市、新道具或完整新剧情" in template.instructions
    assert "如果原稿本质上是一篇议论文或感悟文，允许增强画面感，但不要整体改写成小说化叙事" in template.instructions
    assert "不要把每个小节都扩成篇幅整齐、节奏相似的场景散文段" in template.instructions
    assert "保留原稿的核心论点结构" in template.instructions
    assert "原稿里已经出现的人物、亲属称谓、关系对象和案例应优先保留并重写表达" in template.instructions
    assert "不要为了把段落接顺，额外补“很多时候”“说到底”“人总是这样”“我们总以为”这类泛感慨过渡句" in template.instructions
    assert "如果原稿本来更朴素、更直给，就保留这股劲，不要统一磨成成熟公众号标准成稿" in template.instructions
    assert "当前任务是基于现有正文精修，不是根据大纲重新生成一篇新稿" in template.instructions
    assert "现有正文是本次改写的唯一正文输入" in template.instructions
    assert "如果原稿标题本身成立，优先保留原标题" in template.instructions
    assert "开头第一屏和各小节首段，要优先保住原稿原本的切入对象" in template.instructions
    assert "如果原稿主体是并列展开的三到四个主题段，精修后仍然保持并列展开" in template.instructions
    assert "如果原稿某节原本一上来就是人物案例、直接判断或一组并列例子，精修后也优先从那里进入" in template.instructions
    assert "不要因为想显得更完整，就把原稿统一改成总括判断句加解释句的成熟公众号腔" in template.instructions
    assert "如果原稿里有更直、更硬、更不圆滑的句子重心，精修后也要尽量保住" in template.instructions
    assert "如果现有正文和大纲存在轻微不一致，以现有正文为准" in template.instructions
    assert "原稿结构锚点（精修后应尽量保留这些顺序与案例，不要求逐字复用）：" in template.prompt
    assert "原标题锚点：旧标题" in template.prompt
    assert "必须保留的原稿关键句：不是你太累，而是你一直没有停下来" in template.prompt
    assert "输出前自查：场景具体度、句式重复度、模板风险、情绪自然度、改写幅度" in template.instructions


def test_polish_prompt_surfaces_existing_section_headings_as_structure_anchors() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "用户原文改写测试",
            "topic_title": "别把日子过反了",
            "topic_angle": "人生反向消耗",
            "project_title": "原文精修测试",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "hook",
                "outline_body": "1. a\n2. b",
            },
            "polish_instruction": "降低模板感。",
            "draft": {
                "title": "别把日子过反了",
                "body_markdown": (
                    "# 别把日子过反了\n\n"
                    "开头总述。\n\n"
                    "别用健康换明天\n\n"
                    "朋友阿杰曾是个工作狂。\n\n"
                    "别等失去才懂珍惜\n\n"
                    "外婆突然离世后，我翻遍手机。\n\n"
                    "别把幸福寄托在“等以后”\n\n"
                    "有人攒了半辈子钱。"
                ),
            },
        }
    )

    assert "必须保留小节标题：别用健康换明天" in template.prompt
    assert "别用健康换明天下必须继续围绕这个原稿锚点推进：朋友阿杰曾是个工作狂" in template.prompt
    assert "必须保留小节标题：别等失去才懂珍惜" in template.prompt
    assert "别等失去才懂珍惜下必须继续围绕这个原稿锚点推进：外婆突然离世后，我翻遍手机" in template.prompt
    assert "必须保留小节标题：别把幸福寄托在“等以后”" in template.prompt


def test_polish_prompt_allows_structure_recomposition_without_old_anchors() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "总把自己往后放的人，为什么连休息都像在申请",
            "topic_angle": "情绪耗尽",
            "project_title": "原创增强重组测试",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "锅里余温还在，手机先亮了。",
                "outline_body": "1. 亮屏\n2. 人为什么先缩回去\n3. 留一点力给自己",
            },
            "polish_instruction": "重写成更像人手写的版本，主动拉开与参考文的距离。",
            "allow_structure_recomposition": True,
            "preserve_structure_anchors": False,
            "draft": {
                "title": "别把日子过反了",
                "body_markdown": (
                    "# 别把日子过反了\n\n"
                    "别用健康换明天\n\n"
                    "朋友阿杰曾是个工作狂。\n\n"
                    "别等失去才懂珍惜\n\n"
                    "外婆突然离世后，我翻遍手机。"
                ),
            },
        }
    )

    assert "当前任务仍然是基于现有正文精修，但这次允许更大幅度的结构重组" in template.instructions
    assert "不需要保住原标题、原小节标题或原段落职责" in template.instructions
    assert "你可以重组标题、段落顺序、小节职责和结尾动作" in template.prompt
    assert "原稿结构锚点（精修后应尽量保留这些顺序与案例，不要求逐字复用）：" not in template.prompt
    assert "必须保留小节标题：别用健康换明天" not in template.prompt
    assert "独立短段尽量压到 2 处以内" in template.instructions
    assert "不要把一句消息、对话、短信或引用写成整篇反复出现的展示段" in template.instructions


def test_draft_prompt_includes_wechat_public_account_naturalness_rules() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "办公室倦怠修复",
            "topic_title": "工位上的那种累，先别急着怪自己",
            "topic_angle": "情绪识别",
            "project_title": "办公室倦怠修复周更",
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "午休刚过，屏幕又亮了。",
                "outline_body": "1. 提示音\n2. 累从哪里来\n3. 怎么慢慢往回收",
            },
        }
    )

    assert "正文要更贴近真实公众号作者写作" in template.instructions
    assert "不要把每个判断都解释透，留一点空白给读者自己接上" in template.instructions
    assert "不要系统性在开头第一屏、各小节首段或段落转场前补新的氛围场景" in template.instructions
    assert "避免机械扩写、刻意增肥和整篇统一修辞" in template.instructions
    assert "避免系统性把“和”改成“以及”、“并”改成“并且”" in template.instructions
    assert "不要把句子润成网文腔、鸡汤腔或文学仿写腔" in template.instructions
    assert "如果原稿主体是议论、感悟或并列展开，不要统一扩写成每段都先铺场景再抒情的散文稿" in template.instructions


def test_stage_templates_allow_domain_pack_override_without_touching_tone_profile() -> None:
    custom_domain_pack = {
        "audience": "职场成长",
        "voice": "语言要冷静、务实、直接",
        "constraints": "避免抒情过度、泛心理化和悬浮表达",
    }

    template = build_draft_prompt(
        {
            "trend_title": "新人汇报总是紧张",
            "topic_title": "一开口就慌，不是能力差，是汇报结构没站稳",
            "topic_angle": "职场表达",
            "project_title": "职场表达修复周更",
            "tone_profile": TONE_PROFILE,
            "domain_pack": custom_domain_pack,
            "outline": {
                "hook": "很多人不是不会说，而是一站到人前就断掉节奏。",
                "outline_body": "1. 紧张不是根因\n2. 结构先于表达\n3. 先稳再准",
            },
        }
    )

    assert "内容面向职场成长赛道" in template.instructions
    assert "语言要冷静、务实、直接" in template.instructions
    assert "避免抒情过度、泛心理化和悬浮表达" in template.instructions
    assert "风格档案：女性成长克制陪伴风" in template.prompt
