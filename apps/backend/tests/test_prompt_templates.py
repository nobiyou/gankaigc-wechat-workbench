from __future__ import annotations

import json
from pathlib import Path

from app.services import dbskill_bridge
from app.services.content_skills import build_content_skill_instructions
from app.services.prompt_templates import (
    _extract_tracked_article_body_cues,
    _extract_tracked_article_emotional_cues,
    _extract_tracked_article_topic_cues,
    _infer_tracked_article_pressure_guard,
    _has_broad_emotional_release_focus,
    _has_everyday_warmth_return_focus,
    _has_inner_settlement_focus,
    _has_self_reliance_inward_support_focus,
    _has_supportive_appreciation_focus,
    _has_response_priority_focus,
    _has_resilience_reconstruction_focus,
    _has_relationship_aftercare_focus,
    build_assets_prompt,
    build_cover_image_prompt,
    build_draft_prompt,
    build_outline_prompt,
    build_publish_package_prompt,
    build_tracked_article_metadata_prompt,
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
    "opening_style": "直接问题、现实接口或一句共鸣判断切入，直接点破问题和答案入口",
    "paragraph_rhythm": "标准三段式直接推进，中段围绕 2 到 4 个明确判断展开；多数段落以 1 到 2 句为主，只有需要补机制、后果或情绪承接时才放到 3 句，遇到动作变化、转折或落点就拆段；每个判断都要给出处境、依据或行动落点，少铺氛围",
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
                "social_teaser_options": ["导语一", "导语二", "导语三"],
                "recommended_title": "真正有力量的人，都把人生主导权收回来了",
                "title_options": ["真正有力量的人，都把人生主导权收回来了"],
            },
        }
    )

    assert "标题长度控制在 10 到 20 个字" in topic_template.instructions
    assert "必须带钩子，不能只是情绪陈述" in topic_template.instructions
    assert "判断可以明确，但先把答案落在真实接口上，不要只剩抽象结论。" in topic_template.instructions

    assert "大纲按问题推进组织" in outline_template.instructions
    assert "这不是低成本三段式" in outline_template.instructions
    assert "中间部分展开 2 到 4 个论点" in outline_template.instructions
    assert "判断依据或行动落点" in outline_template.instructions
    assert "总字数目标控制在 1200 到 1800 字" in outline_template.instructions
    assert "大纲默认不规划整段场景描述" in outline_template.instructions
    assert "开头要点破真实问题，中段要给新观察，结尾要有明确方向感。" in outline_template.instructions
    assert "有判断功能的现实细节" in outline_template.instructions

    assert "开头优先用直接问题、现实接口或一句共鸣判断切入" in draft_template.instructions
    assert "不要只靠空问句、空引用或泛共鸣占住开头位置。" in draft_template.instructions
    assert "不是让读者自己猜，你要直接把判断说出来，但要落在真实接口上。" in draft_template.instructions
    assert "观点 + 依据/接口 + 推进" in draft_template.instructions
    assert "不能只重复标题情绪" in draft_template.instructions
    assert "多数段落控制在 1 到 2 句" in draft_template.instructions
    assert "如果单段超过 3 句，先拆段" in draft_template.instructions
    assert "情绪价值要落在被看见、被松绑或被轻轻推动上" in draft_template.instructions
    assert "正文不需要含蓄，默认不用整段场景描写" in draft_template.instructions
    assert "正文都要让读者获得情绪价值" in draft_template.instructions
    assert "不用生活场景冷启动" in draft_template.instructions
    assert "有情绪功能的现实细节" in draft_template.instructions
    assert "例证不要单独拖成长段" in draft_template.instructions
    assert "全文最好保住 1 处从具体处境里长出来、可以单独成段的可摘录短句或引用式表达" in draft_template.instructions
    assert "如果状态允许，可以再留 1 处" in draft_template.instructions
    assert "连续两篇不能用同一个人" in draft_template.instructions
    assert "不要使用这些词：不禁、心想、暗想、默念、琢磨、纠结、暗自、默默" in draft_template.instructions
    assert "少用“像……一样”“如同”“仿佛”“宛如”“好似”这类明喻" in draft_template.instructions
    assert "“不是A，是B”句式整篇最多使用 2 次" in draft_template.instructions
    assert "破折号整篇最多使用 2 处" in draft_template.instructions
    assert "不要写成逐条列举、逐项解释的导购式结构" in draft_template.instructions

    assert "导语要直接点破读者最在意的问题" in assets_template.instructions
    assert "不要写成空泛抒情 teaser" in assets_template.instructions
    assert "最好一眼能截住读者" in assets_template.instructions
    assert "主推标题 recommended_title" in assets_template.prompt
    assert "3 条导语候选 social_teaser_options" in assets_template.prompt

    assert "编辑备注要直接给出这篇稿子的核心答案和发布抓手" in publish_template.instructions
    assert "不要写成模糊抒情总结" in publish_template.instructions
    assert "最终发布标题 publish_title" in publish_template.prompt
    assert "最终发布导语 publish_lead" in publish_template.prompt
    assert "3 条导语候选 intro_options" in publish_template.prompt


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
    assert "原则上不规划空场景段，先规划现实承压点和情绪推进" in outline_instructions
    assert "有判断功能的现实细节" in outline_instructions
    assert "结尾要明确结论、边界或行动落点，不要含蓄留白" in outline_instructions
    assert "正文每个主要段落都要承担新的内容价值" in draft_instructions
    assert "不管风格多直接或多克制，正文都要让读者获得情绪价值" in draft_instructions
    assert "正文默认不用整段场景描写" in draft_instructions
    assert "如果单段超过 3 句，先拆段" in draft_instructions
    assert "不用生活场景冷启动" in draft_instructions
    assert "空动作残留" in draft_instructions
    assert "不要连续多段写环境、动作、光线、房间、夜晚等氛围" in draft_instructions
    assert "标题备选、封面文案和分发导语要准确呈现正文的信息增量或情绪价值" in assets_instructions
    assert "马上知道自己会被理解、被提醒或获得一个现实出口" in assets_instructions
    assert "尽量短句化，不要铺成长导语" in assets_instructions
    assert "不要用含蓄氛围、场景感文案或暧昧留白来包装正文" in assets_instructions
    assert "发布摘要和编辑备注必须点明这篇稿子的核心信息增量或情绪价值" in publish_instructions
    assert "提供的情绪承接是什么" in publish_instructions
    assert "发布摘要、标签和编辑备注直接写清核心结论" in publish_instructions


def test_content_skills_relax_direct_answer_for_tracked_article_strategy_package() -> None:
    payload = {
        "source_type": "tracked_article",
        "problem_brief": {"clarified_problem": "为什么总在等待里替对方找补。"},
        "strategy_card": {"structure_mode": "response_priority"},
    }

    outline_instructions = build_content_skill_instructions(stage="outline", payload=payload)
    draft_instructions = build_content_skill_instructions(stage="draft", payload=payload)

    assert "先把真实卡点钉住" in outline_instructions
    assert "段落快慢、推进顺序和结尾动作优先服从策略模式" in outline_instructions
    assert "不强行把话说成标准答案" in outline_instructions
    assert "不必第一句就把答案喊满" in draft_instructions
    assert "一句一段的人话短句或可摘录句" in draft_instructions
    assert "不必句句立刻落成结论" in draft_instructions
    assert "先讲结论、再展开讲解、最后完整收口" in draft_instructions
    assert "不强求口号式答案句" in draft_instructions


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
            "body_markdown": "她不是突然不想说话，只是把自己的疲惫一再往后放。\n\n后来连回家的力气都提不起来。",
            "structure_notes": "结构备注",
            "analysis_theme": "文章真正想讲的是，一个人不是突然变冷淡，而是被长期推迟的疲惫慢慢抽空了回应能力。",
            "analysis_core_conflict": "表面还在正常回应，心里的余量却已经被日常消耗和关系压力一点点磨没了。",
            "analysis_emotional_exit": "先认出自己的耗尽，再把回应和照顾自己重新排回生活顺序里。",
            "analysis_structure_mode": "pressure_interface_direct",
            "analysis_opening_pattern": "从疲惫和回家无力的现实接口起笔。",
            "analysis_do_not_turn_into": "不要写成泛关系评判或空泛自爱口号。",
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
    assert "如果参考文章正文里已经出现可用的现实接口、身体提醒、延迟代价或被反复往后放的动作" in template.instructions
    assert "先读懂参考文章在讲什么，再决定新选题怎么组织" in template.instructions
    assert "优先服从这些分析结论" in template.instructions
    assert "参考文章标题：听到伴侣说话就烦，不是你脾气差" in template.prompt
    assert "分析主题：文章真正想讲的是，一个人不是突然变冷淡，而是被长期推迟的疲惫慢慢抽空了回应能力。" in template.prompt
    assert "核心矛盾：表面还在正常回应，心里的余量却已经被日常消耗和关系压力一点点磨没了。" in template.prompt
    assert "情绪出口：先认出自己的耗尽，再把回应和照顾自己重新排回生活顺序里。" in template.prompt
    assert "结构模式：pressure_interface_direct" in template.prompt
    assert "开头方式：从疲惫和回家无力的现实接口起笔。" in template.prompt
    assert "不要写成：不要写成泛关系评判或空泛自爱口号。" in template.prompt
    assert "标签：wechat-mp / relationship" in template.prompt
    assert "参考文章正文抓手候选：" in template.prompt
    assert "她不是突然不想说话，只是把自己的疲惫一再往后放" in template.prompt
    assert "风格档案：女性成长克制陪伴风" in template.prompt
    assert "切入角度 angle（1 句话，控制在 40 到 80 个汉字）" in template.prompt


def test_build_tracked_article_metadata_prompt_requires_analysis_before_field_completion() -> None:
    template = build_tracked_article_metadata_prompt(
        {
            "source_kind": "manual",
            "source_name": "夜读关系实验室",
            "article_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "article_url": "https://example.com/slow-repair-template",
            "author": "",
            "summary": "",
            "structure_notes": "",
            "tags": [],
            "body_source": "manual",
            "body_markdown": "她那天没有继续解释，只是先停下来接住那一下失望。\n\n第二天才重新整理要说的话。",
        }
    )

    assert "公众号内容分析编辑" in template.instructions
    assert "先分析文章，再补字段；不要跳过分析直接写摘要。" in template.instructions
    assert "结构模式只能从这些值里选一个" in template.instructions
    assert "不要写成要明确提醒这篇参考文最不该被改写成什么主题或套路。" in template.instructions
    assert "4. 分析主题 analysis_theme" in template.prompt
    assert "7. 结构模式 analysis_structure_mode" in template.prompt
    assert "9. 不要写成 analysis_do_not_turn_into" in template.prompt


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
            "source_type": "trend",
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
            "source_type": "trend",
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
    assert "只有在全文真的被切成很多同职责匀称小段时，才合并相邻段落" in draft_template.instructions
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
    assert "结尾不要为了传播性硬设计空口号金句" in template.instructions
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
    assert "不要频繁宣布写作动作，比如“先说结论”“接下来我们来看”“真正的问题是”" in draft_template.instructions
    assert "不要把普通处境硬拔成时代缩影、重要转折或更宏大的意义" in draft_template.instructions
    assert "如果一句话读起来像现成金句或适合被单独截图传播" in draft_template.instructions
    assert "允许保留 1 处可摘录短句，最好单独成段，但不要把空结论单独抬成一段" in draft_template.instructions


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
    assert "如果要单独留一个短段，它应该像阻力线、动作残留，或一处从前文动作和代价里长出来的可摘录短句" in template.instructions
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
            "body_markdown": "后来得了尿毒症，又开始怀念当初长褥疮的时候。\n\n人这一生，不必取悦谁。",
            "structure_notes": "从心绪整理进入，再落到自我照料和生活排序。",
            "tags": ["self-care"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "不要把选题收窄成亲密关系摊牌、情侣冷战、深夜等回复或“怎么把话说清楚”的沟通修复主线。" in template.instructions
    assert "标题和切入角度优先围绕身体提醒、生活次序、工作/家人/自我照料的接口重建" in template.instructions
    assert "像体检改期、复查拖延、整个人越来越钝、连消息都不想回这类接口" in template.instructions
    assert "后来得了尿毒症，又开始怀念当初长褥疮的时候" in template.prompt
    assert "人这一生，不必取悦谁" not in template.prompt


def test_build_topic_prompt_keeps_internal_pressure_guard_when_summary_negates_relationship_repair() -> None:
    template = build_topic_prompt(
        {
            "source_type": "tracked_article",
            "source_ref_slug": "wechat-mp-demo-3",
            "source_name": "手动录入",
            "article_title": "善待自己，好好爱自己",
            "author": "未知",
            "summary": "文章重点是人生遗憾、内耗、自我照料缺位和身体代价，不是关系修复。",
            "body_markdown": "后来得了尿毒症，又开始怀念当初长褥疮的时候。",
            "structure_notes": "从遗憾反思和内耗进入，再落到身体代价、自我照料和生活排序。",
            "tags": ["自我关照", "人生遗憾", "自我照料", "生活排序"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "不要把选题收窄成亲密关系摊牌" in template.instructions


def test_build_topic_prompt_keeps_internal_pressure_guard_with_relationship_noise_tags_and_negated_mainline() -> None:
    template = build_topic_prompt(
        {
            "source_type": "tracked_article",
            "source_ref_slug": "wechat-mp-demo-3b",
            "source_name": "手动录入",
            "article_title": "总把自己放最后的人，身体会替你记账",
            "author": "未知",
            "summary": "文章重点是内耗、身体代价和生活排序失衡，不在亲密关系沟通里打转，也不要写成冷战复合流程。",
            "body_markdown": (
                "她先把体检往后改，又把回家吃饭这件事往后推。\n\n"
                "后来整个人越来越钝，连一句解释都懒得说。"
            ),
            "structure_notes": "从日常顺延和身体变钝切入，再落到自我照料缺位。",
            "tags": ["身体提醒", "关系修复", "生活排序"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "不要把选题收窄成亲密关系摊牌" in template.instructions
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
    assert "开头不要写成“你有没有过这种阶段”“你以为自己只是累吗”“人啊，总是这样”这类先分类、先下定义再讲理的讲稿起手。" in template.instructions
    assert "前两段至少有一段只让现实接口、动作后果或身体反应自己说话，不要连续两段都在对“你”解释为什么会这样。" in template.instructions
    assert "前屏两到四段里，至少留一处一句一段的现实接口、身体信号或动作残留" in template.instructions
    assert "如果情绪价值已经落在判断、后果或身体反应里，就直接推进，不必先补一段没有信息增量的氛围场景。" in template.instructions
    assert "如果要留可摘录短句，它必须从前文已经写出的代价、动作或没说出口的那一下里长出来" in template.instructions


def test_build_draft_prompt_adds_relationship_aftercare_guard_for_quarrel_repair_article() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "每次闹完都要你自己消化，这段关系已经在交“回避税”",
            "topic_angle": "把反复争执后“谁先冷下来谁就算懂事”的处境拆开，写清长期由一方自我消化、另一方回避修复时，亲密关系会怎样慢慢失去安全感。",
            "project_title": "一个人到底爱不爱你，吵一架就知道了",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "reference_article_title": "一个人到底爱不爱你，吵一架就知道了",
            "reference_article_summary": "文章把“爱不爱”放到争吵后的具体表现里观察：关键不在是否会吵，而在对方有没有主动沟通、安顿情绪、推动关系修复。",
            "reference_article_body_markdown": (
                "激烈地争吵过后，有人选择冷暴力，不理不睬，任由情绪发酵；有人选择及时妥协，回归理性，让爱化解矛盾。\n\n"
                "吵架后的态度，便是检验爱情的试金石。\n\n"
                "毕竟好的关系，不是永远不吵架，而是争吵以后还想要继续走下去。"
            ),
            "reference_article_structure_notes": "先看争执后的态度，再拆冷暴力和主动修复怎样把关系带向不同结果。",
            "reference_article_tags": ["亲密关系", "吵架后态度", "冷暴力", "关系修复"],
            "outline": {"hook": "吵完架，最累的常常不是当场，而是后面那段还得自己把日子接回去的时间。"},
        }
    )

    assert "正文不要自动改写成泛内耗、自我扛住、单人稳情绪或生活排序失衡主线。" in template.instructions
    assert "重点要落在：吵完以后谁回来沟通、谁把情绪和日常接回去" in template.instructions
    assert "整齐翻转句" in template.instructions
    assert "前五段至少要有 2 处能单独成段的短句" in template.instructions
    assert "第一屏最好压成 3 个短段" in template.instructions
    assert "前六段最好至少有 3 处能单独成段的短句" in template.instructions
    assert "前四段如果有解释性中长段，下一段就立刻换回一句一段的动作残留" in template.instructions
    assert "前半篇最好留 1 句把关系位置、委屈顺位或单人善后的代价压成一句的短句" in template.instructions
    assert "不要复用‘别人/旁人会觉得你……’这种外部评价壳子" in template.instructions
    assert "能拆成两段的长段就拆" in template.instructions
    assert "不要用“先把自己排回前面”这类泛自我成长结论收束。" in template.instructions
    assert "最后两段尽量一短一长" in template.instructions
    assert "尾段不要急着教人怎么成熟、怎么放下" in template.instructions


def test_build_topic_prompt_does_not_add_internal_pressure_guard_for_real_relationship_repair_article() -> None:
    template = build_topic_prompt(
        {
            "source_type": "tracked_article",
            "source_ref_slug": "wechat-mp-demo-relationship",
            "source_name": "手动录入",
            "article_title": "真正让关系缓回来，不是解释，是先接住那一下失望",
            "author": "未知",
            "summary": "文章重点是关系修复和表达顺序，不是输在不会说，而是输在没先接住失望。",
            "body_markdown": "她那天没有继续解释，只是先停下来接住那一下失望。\n\n第二天才重新整理要说的话。",
            "structure_notes": "先回到失望现场，再拆修复顺序和表达动作。",
            "tags": ["表达修复", "关系修复"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "不要把选题收窄成亲密关系摊牌" not in template.instructions


def test_build_topic_prompt_adds_relationship_aftercare_guard_for_quarrel_repair_article() -> None:
    template = build_topic_prompt(
        {
            "source_type": "tracked_article",
            "source_ref_slug": "wechat-mp-demo-quarrel-repair",
            "source_name": "手动录入",
            "article_title": "一个人到底爱不爱你，吵一架就知道了",
            "author": "未知",
            "summary": "文章把“爱不爱”放到争吵后的具体表现里观察：关键不在是否会吵，而在对方有没有主动沟通、安顿情绪、推动关系修复。",
            "body_markdown": (
                "激烈地争吵过后，有人选择冷暴力，不理不睬，任由情绪发酵；有人选择及时妥协，回归理性，让爱化解矛盾。\n\n"
                "吵架后的态度，便是检验爱情的试金石。\n\n"
                "毕竟好的关系，不是永远不吵架，而是争吵以后还想要继续走下去。"
            ),
            "structure_notes": "先看争执后的态度，再拆冷暴力和主动修复怎样把关系带向不同结果。",
            "tags": ["亲密关系", "吵架后态度", "冷暴力", "关系修复"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "不要把选题改写成泛内耗、自我稳住、生活排序失衡或抽象人生感悟。" in template.instructions
    assert "争执过后为什么总是没人回来修复" in template.instructions
    assert "切入角度尽量用直述句，不要写成“不是……而是……”式对照句。" in template.instructions
    assert "不要把标题写成“这段关系已经在……”式整句判决" in template.instructions


def test_response_priority_focus_adds_guardrails_across_topic_outline_and_draft() -> None:
    payload = {
        "source_type": "tracked_article",
        "source_ref_slug": "no-time-priority-reroute",
        "source_name": "手动录入",
        "article_title": "没时间，不一定是真的没时间",
        "author": "未知",
        "summary": "文章借日常联系里的“没时间”现象，讨论一段关系里真实的优先级排序。核心判断是：多数迟迟不回应并非真的抽不出空，而是投入意愿不足，时间分配往往比语言更能说明在乎程度。",
        "body_markdown": (
            "听过一句话：“红灯30秒，我喝了一口水，拍了张照片，回了条消息，连上蓝牙，放了一首喜欢的歌，所以你告诉我，什么是没时间？”\n\n"
            "真正的原因可能是，因为我们不够重要，所以对方漫不经心，爱搭不理。人对在乎的人，永远都有时间。\n\n"
            "没时间，是因为你不在他心里，或者顺序没那么优先。一个人的时间在哪儿，他的心就在哪儿。"
        ),
        "structure_notes": "开头借红灯30秒的细节切入，中段拆“忙”和“在乎”并不等价，结尾落到时间分配如何显出真实顺序。",
        "tags": ["关系优先级", "回应顺序", "时间分配"],
        "tone_profile": TONE_PROFILE,
    }
    topic_template = build_topic_prompt(payload)
    outline_template = build_outline_prompt(
        {
            **payload,
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "不是没时间，很多时候，是你根本没被排进他的优先级",
            "topic_angle": "从“没时间”为什么很多时候说的不是日程，而是顺序切入，写时间分配和回应动作怎样显出一个人的真实在乎程度。",
            "project_title": "回应优先级样稿",
        }
    )
    draft_template = build_draft_prompt(
        {
            **payload,
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "不是没时间，很多时候，是你根本没被排进他的优先级",
            "topic_angle": "从“没时间”为什么很多时候说的不是日程，而是顺序切入，写时间分配和回应动作怎样显出一个人的真实在乎程度。",
            "project_title": "回应优先级样稿",
            "outline": {
                "hook": "有些人不是抽不出空，只是一直没把你排到前面。",
                "outline_body": "1. 没时间这句托词为什么总让人迟迟不肯死心\n2. 时间投向怎样比解释更早给答案\n3. 该把时间慢慢收回谁那里",
            },
        }
    )

    assert "先根据参考文里“顺序、时间分配、在乎程度”这条主线重组新选题。" in topic_template.instructions
    assert "为什么“没时间”很多时候说的是顺序" in topic_template.instructions
    assert "大纲要继续顺着这条主线推进。" in outline_template.instructions
    assert "中段至少要把回应顺序、投入意愿和关系优先级之间的关系讲清" in outline_template.instructions
    assert "正文要继续守住这条主题主线。" in draft_template.instructions
    assert "时间分配本身就是答案的一部分" in draft_template.instructions
    assert "第一屏优先落一个回应接口、顺序落差或被安排先后的现实差别" in draft_template.instructions
    assert "把情绪从等待感拉回位置感" in draft_template.instructions


def test_response_priority_strategy_prompt_overrides_tone_profile_shape() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "总被放到最后才回复时，先看你的名字排在第几位",
            "topic_angle": "从回消息、回电话、临时想起你这些细节，拆开关系里的优先级怎么显形，也帮读者判断自己等的是忙碌结束，还是一个始终轮不到你的靠前位置。",
            "project_title": "回应优先级样稿",
            "source_type": "tracked_article",
            "reference_article_title": "听过一句话：什么是没时间",
            "reference_article_summary": "文章重点是时间分配、回应动作和优先顺序怎样显出在乎程度。",
            "reference_article_structure_notes": "从等待和找补切入，中段拆时间投向，结尾回到顺序。",
            "reference_article_tags": ["回应顺序", "时间投向"],
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "clarified_problem": "真正需要被看见的，不是替谁定罪，而是为什么很多人总把偶尔的回应当成例外、把长期的顺序当成误会。",
                "observed_phenomenon": "很多人不是看不懂“没时间”这句话，而是总想再等等看。",
                "writing_goal": "把人为什么总会替“没时间”找补讲清楚，也让读者把位置感重新放回自己手里。",
                "target_reader_situation": "总在等一个人回应，却慢慢意识到时间分配本身就是答案的人",
                "core_conflict": "越替“他只是忙”找理由，越容易忽略时间和顺序早就把自己放在了什么位置。",
            },
            "strategy_card": {
                "reader_situation": "总在等一个人回应，却慢慢意识到时间分配本身就是答案的人",
                "point_of_view": "不急着替谁下判决，先把“没时间”为什么常常说的是顺序讲清楚。",
                "conflict_frame": "真正让人清醒的，是时间和回应总把你排在后面。",
                "emotional_path": "先认出为什么总会替对方找补，再把情绪从等待感拉回位置感。",
                "structure_mode": "response_priority",
                "opening_move": "开头先落一个回应顺序里的小接口。",
                "body_shift": "中段写时间投向和回应动作怎样把真实位置慢慢暴露出来。",
                "ending_move": "结尾回到位置感回正和时间该留给谁。",
                "expression_constraints": ["不要用口号式收尾"],
                "benchmark_summary": "只借压力类型和情绪发动机，不借原文标题骨架和结尾动作。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "聊天框停在那儿很久没动的时候，人最容易先替对方找补。",
                "outline_body": "1. 等待和找补\n2. 时间投向比解释更早给答案\n3. 把位置感慢慢收回来",
            },
        }
    )

    assert "开篇方式：先从一个被放到后面的回应接口切入" in template.prompt
    assert "不急着把“你不重要”写成开场判词" in template.prompt
    assert "段落要有快慢差" in template.prompt
    assert "后半篇把情绪从等待感拉回位置感、选择感和时间回收感" in template.prompt
    assert "收束方式：结尾落在位置感回正" in template.prompt
    assert "给读者清醒后的轻一点" in template.prompt
    assert "不必第一句就把答案喊满" in template.instructions
    assert "不强求口号式答案句" in template.instructions


def test_everyday_warmth_return_focus_adds_guardrails_across_topic_outline_and_draft() -> None:
    payload = {
        "source_type": "tracked_article",
        "source_ref_slug": "small-things-reroute",
        "source_name": "手动录入",
        "article_title": "一生最重要的事，不是大事",
        "author": "未知",
        "summary": "文章把“做大事”的期待，与人在慢下来后重新确认的日常幸福放在一起比较，核心判断是普通陪伴和细碎日常才最能托住生活。",
        "body_markdown": (
            "年轻时，我们都想改变世界，觉得人生一定要轰轰烈烈，要做大事，要出人头地。可走过半生，才发现最重要的事，不过是活在人间烟火里，陪在爱的人身边。\n\n"
            "朋友因为身体不舒服做了个手术，在家休养。他终于陪爱人做了一顿晚饭，去接孩子放学，也陪父母慢慢散步。\n\n"
            "那些拼了命追求的大事，好像忽然祛魅了，剩下来的反而是一顿饭、一句晚安、一个陪伴动作。"
        ),
        "structure_notes": "先写大事叙事，再用手术后的慢下来做转折，中段回到晚饭、接孩子、陪父母这些普通日常，结尾回到小事才最重要。",
        "tags": ["人间烟火", "陪伴", "小事", "日常", "祛魅"],
        "tone_profile": TONE_PROFILE,
    }
    topic_template = build_topic_prompt(payload)
    outline_template = build_outline_prompt(
        {
            **payload,
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "原来一生里最重要的，常常都是那些不起眼的小事",
            "topic_angle": "从成就叙事为什么会在某个阶段突然祛魅切入，写人慢下来以后，怎样重新看见那些不起眼却最能托住生活的小事和陪伴。",
            "project_title": "小事回归样稿",
        }
    )
    draft_template = build_draft_prompt(
        {
            **payload,
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "原来一生里最重要的，常常都是那些不起眼的小事",
            "topic_angle": "从成就叙事为什么会在某个阶段突然祛魅切入，写人慢下来以后，怎样重新看见那些不起眼却最能托住生活的小事和陪伴。",
            "project_title": "小事回归样稿",
            "outline": {
                "hook": "很多人拼命往前赶，最后被留下来的，反而是一顿饭和一句晚安。",
                "outline_body": "1. 宏大目标祛魅\n2. 日常陪伴回归\n3. 结尾回到一个小动作",
            },
        }
    )

    assert _has_everyday_warmth_return_focus(payload) is True
    assert "不要把选题收窄成身体告警、自我照料积压或单一复查拖延主线。" in topic_template.instructions
    assert "也不要把题眼改写成“有人等你回应”“先把关系接住”或谁被排在回应顺序后面这类关系回应排序。" in topic_template.instructions
    assert "不要把它再抽象成“女性要重建生活托底感”“意义供给退潮后怎么办”这类泛成长标题。" in topic_template.instructions
    assert "不要写成“女人中年以后更需要重估哪些事”这类年龄阶段提问式抽象标题。" in topic_template.instructions
    assert "标题和切入角度优先围绕成就叙事为什么会祛魅、普通陪伴为什么反而最重要来重组" in topic_template.instructions
    assert "不要把题眼收缩成某个可直接映回原文的单一家庭场景或日常动作名词" in topic_template.instructions
    assert "被长期挪后的普通安排、低声量联系和在场动作" in topic_template.instructions
    assert "大纲不要自动缩成身体提醒追债稿。" in outline_template.instructions
    assert "中段至少留一段写普通陪伴和细小日常怎样托住生活" in outline_template.instructions
    assert "正文不要把手术、休养或身体提醒写成唯一主轴。" in draft_template.instructions
    assert "真正要写的是：那些被高估的大事为什么会慢慢祛魅" in draft_template.instructions
    assert "不要复述参考文现成家庭动作" in draft_template.instructions
    assert "不要把普通陪伴重新写成三四个轻小动作的并列清单或排比" in draft_template.instructions
    assert "不要用直给的顿悟提示句直接翻牌" in draft_template.instructions


def test_everyday_warmth_return_topic_prompt_abstracts_reference_daily_actions() -> None:
    template = build_topic_prompt(
        {
            "source_type": "tracked_article",
            "source_ref_slug": "small-things-reroute",
            "source_name": "手动录入",
            "article_title": "一生最重要的事，不是大事",
            "author": "未知",
            "summary": "文章把“做大事”的期待，与人在慢下来后重新确认的日常幸福放在一起比较，核心判断是普通陪伴和细碎日常才最能托住生活。",
            "body_markdown": (
                "年轻时，我们都想改变世界，觉得人生一定要轰轰烈烈，要做大事，要出人头地。可走过半生，才发现最重要的事，不过是活在人间烟火里，陪在爱的人身边。\n\n"
                "朋友因为身体不舒服做了个手术，在家休养。他终于陪爱人做了一顿晚饭，去接孩子放学，也陪父母慢慢散步。\n\n"
                "那些拼了命追求的大事，好像忽然祛魅了，剩下来的反而是一顿饭、一句晚安、一个陪伴动作。"
            ),
            "structure_notes": "先写大事叙事，再用手术后的慢下来做转折，中段回到晚饭、接孩子、陪父母这些普通日常，结尾回到小事才最重要。",
            "tags": ["人间烟火", "陪伴", "小事", "日常", "祛魅"],
            "tone_profile": TONE_PROFILE,
        }
    )

    assert "参考文章正文抓手候选：" in template.prompt
    assert "成就叙事为什么会在某个阶段突然失重" in template.prompt
    assert "被长期挪后的普通安排怎样慢慢暴露日子被挤空" in template.prompt
    assert "低声量联系和在场动作为什么重新显出分量" in template.prompt
    combined_text = f"{template.instructions}\n{template.prompt}"
    assert "他终于陪爱人做了一顿晚饭" not in template.prompt
    assert "晚饭" not in combined_text
    assert "接孩子" not in combined_text
    assert "陪父母" not in combined_text
    assert "一句晚安" not in combined_text
    assert "不要把题眼压回某个可直接映回原文的单一家庭场景" in template.prompt


def test_everyday_warmth_return_strategy_prompt_avoids_reference_daily_action_anchors() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "越会证明自己，越容易把日常过空",
            "topic_angle": "从成就叙事为什么会在某个阶段突然祛魅切入，写人慢下来以后，怎样重新看见那些被长期挪后的普通安排和低声量联系。",
            "project_title": "小事回归策略去锚点测试",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "problem_statement_markdown": "# 问题说明书\n\n## 现象\n- 很多人一路追着更大的目标往前跑，慢下来后才看见被自己长期挪后的普通安排。",
                "clarified_problem": "真正需要被看见的，不是该不该继续向上，而是为什么很多人总要慢下来以后，才肯重新给低声量联系应有的分量。",
                "observed_phenomenon": "很多人一路追着更大的目标往前跑，等真正慢下来以后，才慢慢认出那些最普通的陪伴和日常，其实一直在托住生活。",
                "writing_goal": "把人为什么总把重要感押在更大的目标上讲清楚，也把人慢下来以后，为什么反而会被最普通的陪伴和日常重新托住讲清楚。",
                "target_reader_situation": "一路追着更大的目标往前跑，慢下来后才意识到真正重要的东西一直没走远的人",
                "core_conflict": "越把重要感押在更大的目标上，越容易在一路往前赶的时候，错过那些真正托住自己的陪伴和日常。",
                "constraints": ["不要做近义词改写", "不要复用参考文顺序"],
                "feedback_entry": "读者会重新衡量那些不起眼的小事和普通陪伴的分量，认出它们不是附属品，而是这些年最该护住的生活底座。",
            },
            "strategy_card": {
                "reader_situation": "一路追着更大的目标往前跑，慢下来后才意识到真正重要的东西一直没走远的人",
                "point_of_view": "不急着把文章写成健康告诫或人生箴言，先把那些被高估的大事为什么会慢慢祛魅、普通陪伴为什么反而更重要讲清楚。",
                "conflict_frame": "真正让人后知后觉的，不是没做成更大的事，而是一路忙着往前赶的时候，把最能托住自己的日常和陪伴慢慢放轻了。",
                "emotional_path": "先认出人为什么总把重要感押在更大的目标上，再看那些普通陪伴和细小日常，是怎样在慢下来以后重新显出分量的。",
                "structure_mode": "everyday_warmth_return",
                "opening_move": "开头先点破“更大的事未必更重要”这种误认，再用一个被长期挪后的普通安排或低声量联系托住判断；不要复述参考文现成的家庭动作，也不要铺成长场景。",
                "body_shift": "中段先拆成就、体面、宏大目标为什么会在某个阶段突然祛魅，再把普通陪伴、微小日常和被重新看见的生活分量接回来，让被长期挪后的普通安排、低声量联系和在场动作承担分量回落。",
                "ending_move": "结尾回到一个还没完全处理完的普通安排、关系余波或延迟代价上，让分量自然落下来，不要写成小动作清单、身体告诫、口号总结或祝福式收束。",
                "recomposition_recipe": [
                    "标题和开头都换成新的现实入口：不用命令句，不直接复述题眼，先让一个具体接口、后果、身体提醒或当下卡点顶上来。",
                    "前半篇先守住“大事 / 成就 / 体面 / 向上奔跑”为什么会慢慢失重，不要一上来就滑进某段关系谁更委屈、谁在长期体谅的善后逻辑。",
                    "中段沿着“宏大叙事祛魅 -> 普通陪伴回到视野里 -> 被长期挪后的日常重新显出分量”推进，让低声量联系、普通安排和在场动作承担价值回落，不要回收参考文那组高识别度家庭动作。",
                ],
                "expression_constraints": [
                    "不要用口号式收尾",
                    "不要沿用参考文章的开头对象、推进顺序和结尾判断",
                ],
                "divergence_axes": [
                    "标题骨架要换成新的现实入口或处境入口",
                    "不要回收参考文里那组高识别度家庭动作，必须另建新的普通安排、低声量联系或在场接口",
                ],
                "execution_checklist": [
                    "标题是否已经换成新的现实入口，而不是复述题眼。",
                    "是否先拆成就祛魅，再把被长期挪后的普通安排、低声量联系和在场动作的分量接回来，而不是滑成长期体谅、关系排序或身体提醒告诫。",
                ],
                "benchmark_summary": "只借原文对应的生活压力类型和情绪发动机，不借原文标题、首段场景、推进顺序和结尾动作。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "第三次把固定安排往后挪时，她才发现真正变薄的不是日程，是自己在生活里的在场感。",
                "outline_body": "1. 成就叙事为什么会显得更响\n2. 被长期挪后的普通安排怎样慢慢失重\n3. 日常分量怎样重新回来",
            },
        }
    )

    assert "接孩子" not in template.prompt
    assert "陪父母" not in template.prompt
    assert "一句晚安" not in template.prompt
    assert "说句晚安" not in template.prompt
    assert "低声量联系" in template.prompt
    assert "普通安排" in template.prompt


def test_tracked_article_pressure_guard_does_not_misclassify_happiness_release_article() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "幸福是什么",
        "summary": "文章把幸福的定义从“不断获得”转向“适时放下”，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。核心判断是，幸福未必来自追到更多，而更可能来自停止拉扯、看见眼前已经拥有的部分。",
        "body_markdown": (
            "幸福是什么？我们总以为，幸福是“得到”：得到爱，得到钱，得到想要的一切。后来才懂，幸福其实是“放下”：放下强求，放下执念，放下那些得不到的东西。\n\n"
            "别再盯着自己没有的东西了，转过头，看看你拥有的。你无忧、无虑、无病、无灾，你有健康的身体，爱你的家人，三两好友，一碗热饭。\n\n"
            "愿你学会“不再强求”的放下，也学会“别无所求”的知足。"
        ),
        "structure_notes": "开头用“幸福是得到还是放下”的反差提问切入，中段转到“强求只会消耗自己”，结尾回收到“放手不是失去，而是腾出位置”。",
        "tags": ["幸福认知", "停止强求", "关系执念", "自我消耗", "珍惜当下"],
    }

    assert _infer_tracked_article_pressure_guard(payload) == ""


def test_resilience_reconstruction_focus_adds_topic_guardrails() -> None:
    payload = {
        "source_type": "tracked_article",
        "source_ref_slug": "jiang-yuyan-reroute",
        "source_name": "手动录入",
        "article_title": "一个人最大的底气，不是美貌，也不是金钱，而是韧性",
        "author": "未知",
        "summary": "文章以残奥会冠军蒋裕燕的人生为例，重点写命运重击、长期疼痛、泳池训练和不被定义后的重建，而不是女性把自己放最后的情绪照顾。",
        "body_markdown": (
            "3岁那年，一场车祸无情夺走了蒋裕燕的右臂与右腿。从3岁到8岁，她每一年都要被迫走上手术台，接受锯掉新生骨头的剧痛。\n\n"
            "为了康复，她走进了泳池。没有右臂维持平衡，没有右腿蹬水发力，她每一次划水都要比常人多划11下。\n\n"
            "肩伤反复发作、背痛缠扰不休、炎症如影随形，可她从未停下前进的脚步。命运以痛吻她，她却在破碎中重建自己，不让任何人定义她能做的事情。"
        ),
        "structure_notes": "先写命运重击和手术台，再转到泳池里的训练硬撑，结尾回到不被定义和韧性重建。",
        "tags": ["韧性", "残奥冠军", "命运重击", "训练", "不被定义"],
        "tone_profile": TONE_PROFILE,
    }

    template = build_topic_prompt(payload)

    assert _has_resilience_reconstruction_focus(payload) is True
    assert "不要把选题改写成泛女性自我照顾、把自己排回前面或先学会照顾自己这类轻量自助主线。" in template.instructions
    assert "像车祸、手术台、泳池里多划11下、肩伤背痛、不被定义这类抓手" in template.instructions
    assert "每一次划水都要比常人多划11下" in template.prompt


def test_resilience_reconstruction_focus_adds_outline_and_draft_guardrails() -> None:
    payload = {
        "source_type": "tracked_article",
        "source_ref_slug": "jiang-yuyan-reroute",
        "source_name": "手动录入",
        "article_title": "一个人最大的底气，不是美貌，也不是金钱，而是韧性",
        "author": "未知",
        "summary": "文章以残奥会冠军蒋裕燕的人生为例，重点写命运重击、长期疼痛、泳池训练和不被定义后的重建，而不是女性把自己放最后的情绪照顾。",
        "body_markdown": (
            "3岁那年，一场车祸无情夺走了蒋裕燕的右臂与右腿。从3岁到8岁，她每一年都要被迫走上手术台，接受锯掉新生骨头的剧痛。\n\n"
            "为了康复，她走进了泳池。没有右臂维持平衡，没有右腿蹬水发力，她每一次划水都要比常人多划11下。\n\n"
            "肩伤反复发作、背痛缠扰不休、炎症如影随形，可她从未停下前进的脚步。命运以痛吻她，她却在破碎中重建自己，不让任何人定义她能做的事情。"
        ),
        "structure_notes": "先写命运重击和手术台，再转到泳池里的训练硬撑，结尾回到不被定义和韧性重建。",
        "tags": ["韧性", "残奥冠军", "命运重击", "训练", "不被定义"],
        "tone_profile": TONE_PROFILE,
        "trend_title": "残奥冠军蒋裕燕的韧性重建",
        "topic_title": "手术台下来的人，后来为什么还要在水里多撑11下",
        "topic_angle": "从重伤、复健到反复加练这条代价线切入，拆开一个人如何在长期疼痛里把“我还能主动一点”重新练回身体和意志。",
        "project_title": "韧性交叉验证",
        "outline": {
            "hook": "拆线以后，人还是得回到水里。",
            "outline_body": "1. 命运重击后的身体代价\n2. 训练怎样一次次逼人重来\n3. 为什么她还是不肯被定义",
        },
    }

    outline_template = build_outline_prompt(payload)
    draft_template = build_draft_prompt(payload)

    assert "大纲不要滑成泛励志口号稿、术后恢复稿或轻量自助稿" in outline_template.instructions
    assert "宁可把代价、反应和判断拆成相邻短段，也不要在单段里堆满时间线、伤痛细节和高位总结" in outline_template.instructions
    assert "正文不要自动改写成泛励志样板文、术后恢复文或“先照顾自己”的情绪照料稿" in draft_template.instructions
    assert "人物事实密度高时，多用相邻短段推进" in draft_template.instructions
    assert "不要把手术、伤病、训练、恢复和价值判断全塞进一个长段里" in draft_template.instructions
    assert "只要一个段落里同时出现三类以上信息" in draft_template.instructions
    assert "凡是超过 4 句的人物事实段" in draft_template.instructions
    assert "结尾回到一个还在继续的训练动作、身体反应或没松掉的念头上" in draft_template.instructions


def test_extract_tracked_article_body_cues_skips_supportive_healthy_body_sentence() -> None:
    payload = {
        "source_type": "tracked_article",
        "body_markdown": (
            "我们都曾在“强求”里，耗尽了自己，以为努力争取，就能得到幸福。\n\n"
            "你无忧、无虑、无病、无灾，你有健康的身体，爱你的家人，三两好友，一碗热饭。\n\n"
            "把自己困在“不甘心”的牢笼里，一遍遍问：“为什么我付出了，却得不到？”"
        ),
    }

    cues = _extract_tracked_article_body_cues(payload)

    assert "你无忧、无虑、无病、无灾，你有健康的身体，爱你的家人，三两好友，一碗热饭" not in cues


def test_broad_emotional_release_focus_detects_happiness_release_article() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "幸福是什么",
        "summary": "文章把幸福的定义从“不断获得”转向“适时放下”，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。",
        "body_markdown": (
            "幸福是什么？我们总以为，幸福是“得到”。后来才懂，幸福其实是“放下”。\n\n"
            "可真正的幸福，恰恰是该结束的时候，不再强求，该珍惜的时候，别无所求。\n\n"
            "亲爱的，该放手的，就放手，那不是失去，是腾出位置。"
        ),
        "structure_notes": "开头从幸福定义反差切入，中段拆强求的代价，结尾回到珍惜已有和知足。",
        "tags": ["幸福认知", "停止强求", "珍惜当下"],
    }

    assert _has_broad_emotional_release_focus(payload) is True


def test_broad_emotional_release_focus_detects_hidden_reference_strategy_payload() -> None:
    payload = {
        "source_type": "tracked_article",
        "reference_article_hidden": True,
        "topic_title": "你以为幸福是得到，后来才懂有些幸福叫放下",
        "topic_angle": "从人为什么总把幸福误解成继续争取切入，写我们怎样在强求和不甘心里耗尽自己，又怎样在放手后重新看见已经拥有的部分。",
        "problem_brief": {
            "raw_goal": "你以为幸福是得到，后来才懂有些幸福叫放下",
            "clarified_problem": "真正需要被看见的，不是人人都懂却做不到的道理，而是人为什么明明已经很累了，还是会把不甘心、投入感和希望错当成继续消耗自己的理由。",
            "observed_phenomenon": "很多人把继续投入误认成还有希望，等到心力、睡眠和眼前拥有的东西一起被透支，才发现自己一直没舍得停下来",
            "writing_goal": "把人为什么会把继续投入误认成还有希望讲清楚，让读者看见停下不是认输，而是把心力收回来。",
            "target_reader_situation": "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人",
            "core_conflict": "越舍不得停下，越容易把继续消耗误认成认真，最后连眼前真正重要的东西也一起忽略掉。",
            "feedback_entry": "读者会意识到自己不是离幸福太远，而是一直把不肯停下误认成更接近幸福。",
        },
        "strategy_card": {
            "reader_situation": "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人",
            "point_of_view": "不急着讲知足、放下或清醒的大道理，先把人为什么明明很累却还是不肯松手讲清楚。",
            "conflict_frame": "真正把人困住的，不是没有答案，而是总把舍不得放手误认成还有希望。",
            "emotional_path": "先认出自己一直在和得不到的东西拉扯，再看为什么人总要等到透支之后才愿意停下。",
            "opening_move": "开头不要整段生活场景冷启动，先用一句会让人停一下的误认判断把读者拉进来。",
            "body_shift": "中段先拆情绪发动机：人为什么会把继续投入误认成还有希望，又为什么总要等到失去之后才看见已经拥有的部分。",
            "ending_move": "结尾给读者一个明确的价值赦免和现实答案：停下来不是失去，是把心力收回来。",
            "benchmark_summary": "只借原文对应的生活压力类型和情绪发动机，不借原文标题、首段场景、推进顺序和结尾动作。",
        },
    }

    assert _has_broad_emotional_release_focus(payload) is True


def test_broad_emotional_release_focus_detects_memory_reflux_article() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "遗忘再长，也长不过明天和以后",
        "summary": "文章围绕过去不会自动沉下去展开，重点不是复合，而是没收尾的关系为什么会在日常缝隙里反复回潮。",
        "body_markdown": (
            "又有多少个心绪翻涌的当下，你低眉叹息，因一点不起眼的小事，而不由自主地感慨，要是他还在就好了。\n\n"
            "有些情有些人，却只适合收藏。过去再美好，也终究是过去了。\n\n"
            "请相信，今日所有的错失、意难平，都将成为来日幸福与喜乐的铺垫。"
        ),
        "structure_notes": "先从旧事会回潮的判断切入，中段拆未完成关系如何反复触发想念，结尾回到带着遗憾往前走。",
        "tags": ["旧关系", "回忆回潮", "未完成"],
    }

    assert _has_broad_emotional_release_focus(payload) is True


def test_everyday_warmth_return_focus_detects_small_things_article() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "一生最重要的事，不是大事",
        "summary": "文章把“做大事”的社会期待，与人在身体受挫、生活放慢后重新确认的日常幸福放在一起比较，核心判断是：真正支撑一个人生活感受的，往往不是成就叙事，而是陪伴、相处和被看见的细碎时刻。",
        "body_markdown": (
            "年轻时，我们都想改变世界，觉得人生一定要轰轰烈烈，要做大事，要出人头地。可走过半生，才发现，这世界再喧嚣，最重要的事，不过是活在人间烟火里，陪在爱的人身边。\n\n"
            "那一刻，他突然觉得，那些拼了命追求的大事，好像瞬间祛魅了。\n\n"
            "其实，真正让人眼眶发热的，可能从来不是升职加薪、远大抱负，而是这些不起眼的、细碎的、平淡的日常瞬间。宏大叙事属于时代，属于历史书，而一碗热汤、一盏夜灯、一句晚安，才属于你我。\n\n"
            "我们很渺小，改变不了世界，但我们可以改变一个人的心情。让爱人笑一下，让孩子开心一下，让父母安心一下。见面、拥抱、吃饭、散步、晒太阳，这些微小的事堆叠起来，才是我们的一生。"
        ),
        "structure_notes": "开头先摆出追逐成就的大命题，再借慢下来后的家庭陪伴完成价值转向，结尾落到从宏大目标转向日常陪伴。",
        "tags": ["日常治愈", "家庭陪伴", "价值重估"],
    }

    assert _has_everyday_warmth_return_focus(payload) is True
    assert _infer_tracked_article_pressure_guard(payload) == ""


def test_inner_settlement_focus_detects_heart_settled_article() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "此心安处，才是一个人最好的归宿",
        "summary": "文章把外界起伏和内心安顿放在一起比较，重点不是某段关系有没有结果，也不是身体有没有告警，而是心为什么一直安不下来，人怎样把自己慢慢安顿回当下。",
        "body_markdown": (
            "杨绛先生说：人生最曼妙的风景，竟是内心的淡定与从容。心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
            "有时候，看似过不去的坎儿，其实是心结难解。把心抚平了，脚下自有坦途；把心看透了，郁结自会消散。\n\n"
            "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂，于岁岁年年中与内心相拥。此心安处是吾乡。"
        ),
        "structure_notes": "先写心为什么一直悬着，再拆人为什么总想把一切想明白，中段回到一餐一饮和一呼一吸怎样让生活重新有轻重。",
        "tags": ["心安", "内在归处", "与内心和解", "安顿自己"],
    }

    assert _has_inner_settlement_focus(payload) is True
    assert _has_broad_emotional_release_focus(payload) is False
    assert _infer_tracked_article_pressure_guard(payload) == ""


def test_relationship_aftercare_focus_detects_quarrel_repair_article() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "一个人到底爱不爱你，吵一架就知道了",
        "summary": "文章把“爱不爱”放到争吵后的具体表现里观察：关键不在是否会吵，而在对方有没有主动沟通、安顿情绪、推动关系修复。",
        "body_markdown": (
            "激烈地争吵过后，有人选择冷暴力，不理不睬，任由情绪发酵；有人选择及时妥协，回归理性，让爱化解矛盾。\n\n"
            "吵架后的态度，便是检验爱情的试金石。\n\n"
            "人生在世，遇到一个吵完架还对你温柔以待的人不容易。毕竟好的关系，不是永远不吵架，而是争吵以后还想要继续走下去。"
        ),
        "structure_notes": "先看争执后的态度，再拆冷暴力和主动修复怎样把关系带向不同结果。",
        "tags": ["亲密关系", "吵架后态度", "冷暴力", "关系修复"],
    }

    assert _has_relationship_aftercare_focus(payload) is True
    assert _infer_tracked_article_pressure_guard(payload) == ""


def test_relationship_aftercare_focus_detects_pushed_away_vulnerability_article() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "你推开我的那一刻，我就学会不再示弱",
        "summary": "文章借“情绪很累却不被理解”的时刻，写亲密关系里最伤人的并不是争吵，而是在脆弱时被嫌烦、被推开。它的判断很明确：一个人不是突然冷下来，而是在多次求助落空后，慢慢学会不再向你袒露软弱。",
        "body_markdown": (
            "有时候，会莫名其妙地觉得累。\n\n"
            "可真正让人寒心的，不是生活本身的压力，而是在求助和示弱时，被最亲近的人嫌烦、推开。\n\n"
            "当你在一个人最无助的时候选择推开他，下一次，他就不会再在你面前脆弱了。"
        ),
        "structure_notes": "开头先从成年人常见的情绪透支感切入，写出表面正常、内里耗尽的状态；中段把这种疲惫放进亲密关系里，转向“对方把脆弱误判成无理取闹”的具体场景；结尾落在一次被推开的后果上，强调失望积累后，人会主动收起依赖和示弱。",
        "tags": ["亲密关系", "脆弱误读", "求助落空", "不再示弱"],
    }

    assert _has_relationship_aftercare_focus(payload) is True
    assert _infer_tracked_article_pressure_guard(payload) == ""


def test_supportive_appreciation_focus_detects_soft_hearted_article() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "如果你身边有这样一个心软的人，请一定要牵紧他的手",
        "summary": "文章重点不是谁在关系里耗空自己，而是心软为什么常被误解，以及那些明明拎得清、却还是愿意包容和体谅别人的人，为什么最值得被珍惜。",
        "body_markdown": (
            "有一种人，习惯了燃烧自己，去照亮别人。你对他好，他会对你更好；你给他温暖，他会回馈给你更多的温暖。\n\n"
            "心软的人并不傻，他们的心里比谁都拎得清。不去计较，是因为心里在乎，不想与爱的人争辩输赢、对错和得失。\n\n"
            "那些愿意包容你的人，一定很爱你。如果你身边有这样一个心软的人，请你一定要牵紧他的手。"
        ),
        "structure_notes": "先写心软的人总会先替别人着想，再拆这种柔软为什么常被误读，结尾回到这样的人最值得被珍惜。",
        "tags": ["心软", "包容", "体谅", "值得珍惜"],
    }

    assert _has_supportive_appreciation_focus(payload) is True
    assert _has_relationship_aftercare_focus(payload) is False


def test_supportive_appreciation_focus_adds_guardrails_across_topic_outline_and_draft() -> None:
    payload = {
        "source_type": "tracked_article",
        "source_ref_slug": "soft-hearted-reroute",
        "source_name": "手动录入",
        "article_title": "如果你身边有这样一个心软的人，请一定要牵紧他的手",
        "author": "未知",
        "summary": "文章重点不是谁在关系里耗空自己，而是心软为什么常被误解，以及那些明明拎得清、却还是愿意包容和体谅别人的人，为什么最值得被珍惜。",
        "body_markdown": (
            "有一种人，习惯了燃烧自己，去照亮别人。\n\n"
            "心软的人并不傻，他们的心里比谁都拎得清。\n\n"
            "那些愿意包容你的人，一定很爱你。如果你身边有这样一个心软的人，请你一定要牵紧他的手。"
        ),
        "structure_notes": "先写心软的人总会先替别人着想，再拆这种柔软为什么常被误读，结尾回到这样的人最值得被珍惜。",
        "tags": ["心软", "包容", "体谅", "值得珍惜"],
        "tone_profile": TONE_PROFILE,
        "trend_title": "参考文章 / 手动录入",
        "topic_title": "那些明明拎得清、却还是愿意包容你的人，最值得被珍惜",
        "topic_angle": "从人为什么总把心软误认成好说话切入，写那些明明拎得清、却还是愿意体谅和包容别人的人，为什么反而最值得被认真珍惜。",
        "project_title": "心软的人",
        "outline": {"hook": "有些人不是不懂分寸，只是总把体谅放在了自己前面。"},
    }

    topic_template = build_topic_prompt(payload)
    outline_template = build_outline_prompt(payload)
    draft_template = build_draft_prompt(payload)

    assert "标题和切入角度优先围绕：心软为什么不是傻、柔软为什么常被误读、真正稀缺的为什么是温柔却不糊涂的人。" in topic_template.instructions
    assert "先根据参考文的主题和矛盾组织新选题，不要跳开原文主线另起一个新问题。" in topic_template.instructions
    assert "大纲要继续围绕这条主线推进。" in outline_template.instructions
    assert "结尾回到被认真回应、被珍惜或被牵紧的方向" in outline_template.instructions
    assert "正文要继续守住这条主题主线。" in draft_template.instructions
    assert "第一屏优先把那个先放软、先让一步、先照顾别人感受的小接口顶上来，让读者先看见柔软本身" in draft_template.instructions
    assert "明明拎得清为什么还愿意体谅和包容" in draft_template.instructions


def test_response_priority_focus_detects_no_time_article() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "没时间，不一定是真的没时间",
        "summary": "文章借日常联系里的“没时间”现象，讨论一段关系里真实的优先级排序。核心判断是：多数迟迟不回应并非真的抽不出空，而是投入意愿不足，时间分配往往比语言更能说明在乎程度。",
        "body_markdown": (
            "听过一句话：“红灯30秒，我喝了一口水，拍了张照片，回了条消息，连上蓝牙，放了一首喜欢的歌，所以你告诉我，什么是没时间？”\n\n"
            "真正的原因可能是，因为我们不够重要，所以对方漫不经心，爱搭不理。人对在乎的人，永远都有时间。\n\n"
            "没时间，是因为你不在他心里，或者顺序没那么优先。俗话说，一个人的时间在哪儿，他的心就在哪儿。"
        ),
        "structure_notes": "开头借红灯30秒的细节切入，中段拆“忙”和“在乎”并不等价，结尾落到时间分配如何显出真实顺序。",
        "tags": ["关系优先级", "回应顺序", "时间分配"],
    }

    assert _has_response_priority_focus(payload) is True
    assert _has_relationship_aftercare_focus(payload) is False


def test_extract_tracked_article_topic_cues_prioritizes_response_priority_thesis() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "没时间，不一定是真的没时间",
        "summary": "文章借日常联系里的“没时间”现象，讨论一段关系里真实的优先级排序。",
        "body_markdown": (
            "听过一句话：“红灯30秒，我喝了一口水，拍了张照片，回了条消息，连上蓝牙，放了一首喜欢的歌，所以你告诉我，什么是没时间？”\n\n"
            "人对在乎的人，永远都有时间。即便这会儿真没时间，过会儿也要挤出时间。\n\n"
            "一个人的时间在哪儿，他的心就在哪儿。"
        ),
        "structure_notes": "从没时间这句托词切入，拆顺序和在乎程度之间的关系。",
        "tags": ["关系优先级", "回应顺序", "时间分配"],
    }

    topic_cues = _extract_tracked_article_topic_cues(payload)

    assert any("红灯30秒" in cue or "永远都有时间" in cue or "时间在哪儿" in cue for cue in topic_cues)


def test_extract_tracked_article_topic_cues_prioritizes_relationship_aftercare_thesis() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "一个人到底爱不爱你，吵一架就知道了",
        "summary": "文章把“爱不爱”放到争吵后的具体表现里观察：关键不在是否会吵，而在对方有没有主动沟通、安顿情绪、推动关系修复。",
        "body_markdown": (
            "激烈地争吵过后，有人选择冷暴力，不理不睬，任由情绪发酵；有人选择及时妥协，回归理性，让爱化解矛盾。\n\n"
            "吵架后的态度，便是检验爱情的试金石。\n\n"
            "人生在世，遇到一个吵完架还对你温柔以待的人不容易。毕竟好的关系，不是永远不吵架，而是争吵以后还想要继续走下去。"
        ),
        "structure_notes": "先看争执后的态度，再拆冷暴力和主动修复怎样把关系带向不同结果。",
        "tags": ["亲密关系", "吵架后态度", "冷暴力", "关系修复"],
    }

    topic_cues = _extract_tracked_article_topic_cues(payload)

    assert any("冷暴力" in cue or "吵架后的态度" in cue or "继续走下去" in cue for cue in topic_cues)


def test_extract_tracked_article_topic_cues_prioritizes_supportive_appreciation_thesis() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "如果你身边有这样一个心软的人，请一定要牵紧他的手",
        "summary": "文章重点不是谁在关系里耗空自己，而是心软为什么常被误解，以及那些明明拎得清、却还是愿意包容和体谅别人的人，为什么最值得被珍惜。",
        "body_markdown": (
            "心软的人并不傻，他们的心里比谁都拎得清。\n\n"
            "那些愿意包容你的人，一定很爱你。\n\n"
            "如果你身边有这样一个心软的人，请你一定要牵紧他的手。"
        ),
        "structure_notes": "先写心软的人总会先替别人着想，再拆这种柔软为什么常被误读，结尾回到这样的人最值得被珍惜。",
        "tags": ["心软", "包容", "体谅", "值得珍惜"],
    }

    topic_cues = _extract_tracked_article_topic_cues(payload)

    assert any("心软不是傻" in cue or "值得被认真珍惜" in cue or "温柔却不糊涂" in cue for cue in topic_cues)


def test_extract_tracked_article_topic_cues_prioritizes_everyday_warmth_return_thesis() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "一生最重要的事，不是大事",
        "summary": "文章把“做大事”的社会期待，与人在身体受挫、生活放慢后重新确认的日常幸福放在一起比较。",
        "body_markdown": (
            "朋友是上市公司的高管，最近因为身体不舒服做了个手术，在家休养。\n\n"
            "那一刻，他突然觉得，那些拼了命追求的大事，好像瞬间祛魅了。\n\n"
            "其实，真正让人眼眶发热的，可能从来不是升职加薪、远大抱负，而是这些不起眼的、细碎的、平淡的日常瞬间。宏大叙事属于时代，属于历史书，而一碗热汤、一盏夜灯、一句晚安，才属于你我。"
        ),
        "structure_notes": "从成就追逐转向日常陪伴的价值重估。",
        "tags": ["日常治愈", "家庭陪伴", "价值重估"],
    }

    topic_cues = _extract_tracked_article_topic_cues(payload)

    assert any("大事" in cue or "宏大叙事" in cue or "日常瞬间" in cue for cue in topic_cues)
    assert all("手术" not in cue for cue in topic_cues[:1])


def test_extract_tracked_article_topic_cues_prioritizes_inner_settlement_thesis() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "此心安处，才是一个人最好的归宿",
        "summary": "文章把外界起伏和内心安顿放在一起比较，重点不是放手某段关系，而是心为什么一直安不下来。",
        "body_markdown": (
            "心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
            "已经过去的事儿，既然改变不了，不如轻轻放下温柔落锁；还没发生的事儿，反正预测不到，不如不骄不躁静待花开。\n\n"
            "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂。"
        ),
        "structure_notes": "先写心为什么一直悬着，再转到如何慢慢安顿回来。",
        "tags": ["心安", "内心归处", "安顿自己"],
    }

    topic_cues = _extract_tracked_article_topic_cues(payload)

    assert any("心若不安" in cue or "真正的心安" in cue or "一餐一饮" in cue for cue in topic_cues)
    assert all("放手" not in cue for cue in topic_cues)


def test_extract_tracked_article_topic_cues_prioritizes_broad_emotional_release_thesis_over_relationship_example() -> None:
    payload = {
        "source_type": "tracked_article",
        "article_title": "幸福是什么",
        "summary": "文章把幸福的定义从“不断获得”转向“适时放下”，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。",
        "body_markdown": (
            "明明一段关系已经烂了，你还死死抓着不放，安慰自己“再坚持一下就好了”。\n\n"
            "可真正的幸福，恰恰是该结束的时候，不再强求，该珍惜的时候，别无所求。\n\n"
            "亲爱的，该放手的，就放手，那不是失去，是腾出位置。"
        ),
        "structure_notes": "开头从幸福定义反差切入，中段拆强求的代价，结尾回到珍惜已有和知足。",
        "tags": ["幸福认知", "停止强求", "关系执念", "珍惜当下"],
    }

    topic_cues = _extract_tracked_article_topic_cues(payload)
    emotional_cues = _extract_tracked_article_emotional_cues(payload)

    assert topic_cues == emotional_cues
    assert any("真正的幸福" in cue or "不再强求" in cue for cue in topic_cues)
    assert all("关系已经烂了" not in cue for cue in topic_cues)


def test_build_outline_prompt_includes_broad_emotional_release_guard() -> None:
    template = build_outline_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "你以为幸福是得到，后来才懂有些幸福叫放下",
            "topic_angle": "从人为什么总把幸福误解成继续争取切入，写我们怎样在强求和不甘心里耗尽自己，又怎样在放手后重新看见已经拥有的部分。",
            "project_title": "幸福是什么",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "article_title": "幸福是什么",
            "author": "未知",
            "source_name": "手动录入",
            "summary": "文章把幸福的定义从“不断获得”转向“适时放下”，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。",
            "body_markdown": (
                "幸福是什么？我们总以为，幸福是“得到”。后来才懂，幸福其实是“放下”。\n\n"
                "明明一段关系已经烂了，你还死死抓着不放。\n\n"
                "可真正的幸福，恰恰是该结束的时候，不再强求，该珍惜的时候，别无所求。"
            ),
            "structure_notes": "开头从幸福定义反差切入，中段拆强求的代价，结尾回到珍惜已有和知足。",
            "tags": ["幸福认知", "停止强求", "珍惜当下"],
        }
    )

    assert "大纲不要自动缩成坏关系止损手册或单一关系复盘。" in template.instructions
    assert "不要把整篇大纲压成“等回复 / 看聊天框 / 一段关系怎么收场”这类单一样本" in template.instructions
    assert "开头钩子不要只拿聊天框、消息提醒、对方回没回来做唯一现实接口" in template.instructions


def test_build_outline_prompt_keeps_broad_emotional_release_guard_when_reference_is_hidden() -> None:
    template = build_outline_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "你以为幸福是得到，后来才懂有些幸福叫放下",
            "topic_angle": "从人为什么总把幸福误解成继续争取切入，写我们怎样在强求和不甘心里耗尽自己，又怎样在放手后重新看见已经拥有的部分。",
            "project_title": "幸福是什么",
            "source_type": "tracked_article",
            "reference_article_hidden": True,
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "raw_goal": "你以为幸福是得到，后来才懂有些幸福叫放下",
                "clarified_problem": "真正需要被看见的，不是人人都懂却做不到的道理，而是人为什么明明已经很累了，还是会把不甘心、投入感和希望错当成继续消耗自己的理由。",
                "observed_phenomenon": "很多人把继续投入误认成还有希望，等到心力、睡眠和眼前拥有的东西一起被透支，才发现自己一直没舍得停下来",
                "writing_goal": "把人为什么会把继续投入误认成还有希望讲清楚，让读者看见停下不是认输，而是把心力收回来。",
                "target_reader_situation": "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人",
                "core_conflict": "越舍不得停下，越容易把继续消耗误认成认真，最后连眼前真正重要的东西也一起忽略掉。",
                "constraints": ["不要写成口号文"],
                "feedback_entry": "读者会意识到自己不是离幸福太远，而是一直把不肯停下误认成更接近幸福。",
            },
            "strategy_card": {
                "reader_situation": "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人",
                "point_of_view": "不急着讲知足、放下或清醒的大道理，先把人为什么明明很累却还是不肯松手讲清楚。",
                "conflict_frame": "真正把人困住的，不是没有答案，而是总把舍不得放手误认成还有希望。",
                "emotional_path": "先认出自己一直在和得不到的东西拉扯，再看为什么人总要等到透支之后才愿意停下。",
                "structure_mode": "emotional_engine_direct",
                "opening_move": "开头不要整段生活场景冷启动，先用一句会让人停一下的误认判断把读者拉进来。",
                "body_shift": "中段先拆情绪发动机：人为什么会把继续投入误认成还有希望，又为什么总要等到失去之后才看见已经拥有的部分。",
                "ending_move": "结尾给读者一个明确的价值赦免和现实答案：停下来不是失去，是把心力收回来。",
                "expression_constraints": ["不要用口号式收尾"],
                "divergence_axes": ["标题骨架要换成新的现实入口或处境入口"],
                "execution_checklist": ["标题是否已经换成新的现实入口，而不是复述题眼。"],
                "benchmark_summary": "只借原文对应的生活压力类型和情绪发动机，不借原文标题、首段场景、推进顺序和结尾动作。",
            },
        }
    )

    assert "大纲不要自动缩成坏关系止损手册或单一关系复盘。" in template.instructions
    assert "至少要给关系之外的生活代价或已拥有部分留出段落职责。" in template.instructions
    assert "前两段里至少有一段主职责必须落在关系之外的生活秩序、身体代价或已经拥有却被忽略的部分" in template.instructions


def test_inner_settlement_focus_adds_guardrails_across_topic_outline_and_draft() -> None:
    payload = {
        "source_type": "tracked_article",
        "source_ref_slug": "heart-settled-reroute",
        "source_name": "手动录入",
        "article_title": "此心安处，才是一个人最好的归宿",
        "author": "未知",
        "summary": "文章把外界起伏和内心安顿放在一起比较，重点不是某段关系有没有结果，也不是身体有没有告警，而是心为什么一直安不下来，人怎样把自己慢慢安顿回当下。",
        "body_markdown": (
            "杨绛先生说：人生最曼妙的风景，竟是内心的淡定与从容。心若不安，到哪里都是流浪；心若不定，遇见谁都是过客。\n\n"
            "有时候，看似过不去的坎儿，其实是心结难解。把心抚平了，脚下自有坦途；把心看透了，郁结自会消散。\n\n"
            "真正的心安，是于一餐一饮中品味生活，于一呼一吸间安顿灵魂，于岁岁年年中与内心相拥。此心安处是吾乡。"
        ),
        "structure_notes": "先写心为什么一直悬着，再拆人为什么总想把一切想明白，中段回到一餐一饮和一呼一吸怎样让生活重新有轻重。",
        "tags": ["心安", "内在归处", "与内心和解", "安顿自己"],
        "tone_profile": TONE_PROFILE,
    }
    topic_template = build_topic_prompt(payload)
    outline_template = build_outline_prompt(
        {
            **payload,
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "很多事迟迟过不去，往往不是事情本身，而是那颗一直没松下来的心",
            "topic_angle": "从人为什么总想把过去想透、把未来想明白切入，写很多时候外界未必最糟，真正拖住人的，是那颗一直悬着的心；也写人怎样慢慢把自己安顿回当下。",
            "project_title": "心安归位样稿",
            "problem_brief": {
                "clarified_problem": "真正需要被看见的，不是事情到底有没有标准答案，而是为什么很多人总把心放在悬空处，忘了先让自己落地；也要让读者看见，当那颗心慢慢安顿下来，很多事会重新有了轻重。",
                "observed_phenomenon": "很多人明明没有被某件大事彻底压垮，心里却一直松不下来，白天装没事，夜里还在反复琢磨。",
                "writing_goal": "把人为什么总在事情未必最糟的时候，先把自己困在那颗一直绷着的心里讲清楚，也让读者看见心安不是放弃，而是把自己慢慢安放回生活。",
                "target_reader_situation": "明明事情不算最糟，却一直被心里的拉扯拖住，怎么也松不下来的人",
                "core_conflict": "真正把人拖累的，很多时候不是事情本身，而是那颗一直绷着、总想把一切想明白却迟迟不肯松下来的心。",
                "constraints": ["不要写成口号文"],
                "feedback_entry": "读者会松一口气，知道自己不是非得把一切想透，才有资格慢慢松下来。",
            },
            "strategy_card": {
                "reader_situation": "明明事情不算最糟，却一直被心里的拉扯拖住，怎么也松不下来的人",
                "point_of_view": "不急着劝人立刻看开，先把那颗心为什么一直落不下来讲清楚，再把读者慢慢带回她真正想安顿的地方。",
                "conflict_frame": "真正把人拖累的，很多时候不是事情本身，而是那颗一直绷着、总想把一切想明白却迟迟不肯松下来的心。",
                "emotional_path": "先认出那颗心为什么总悬着、总想先把一切想稳，再看人怎样从反复较劲里慢慢松下来，重新住回一餐一饮和眼前的日常。",
                "structure_mode": "inner_settlement",
                "opening_move": "开头先落一个心还没完全跟上日子的现实接口：事情过去了，心还留在原地；人已经坐下来了，脑子还在回放。第一屏以短段为主，不要先讲大道理、关系结果、身体告警或幸福定义。",
                "body_shift": "中段先拆那颗心为什么总想把一切想稳、想透或想明白，结果越想越难放下；再写人怎样从现实余波里慢慢回稳，把心一点点放回眼前正在过的生活。",
                "ending_move": "结尾回到一个心终于稍微放平下来的轻动作，不要写成关系结果、身体提醒或祝福收束。",
                "recomposition_recipe": [
                    "前半篇先守住一个心没安下来带出的现实卡点，不要一上来就滑去关系等待、身体告警或幸福公式。",
                    "中段沿着“外界未必最糟 -> 心里一直在拧 -> 人怎样把自己慢慢放回日常”推进。",
                ],
                "expression_constraints": ["不要用名言抚慰直接翻牌"],
                "divergence_axes": ["不要回收参考文里的名言、祝福口吻或现成心灵判断"],
                "execution_checklist": ["是否先守住心没安下来带出的现实卡点，再推进把自己放回一餐一饮和一呼一吸。"],
                "benchmark_summary": "只借原文对应的内在拉扯类型和心安归位主线，不借原文标题、名言排布和结尾动作。",
            },
        }
    )
    draft_template = build_draft_prompt(
        {
            **payload,
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "很多事迟迟过不去，往往不是事情本身，而是那颗一直没松下来的心",
            "topic_angle": "从人为什么总想把过去想透、把未来想明白切入，写很多时候外界未必最糟，真正拖住人的，是那颗一直悬着的心；也写人怎样慢慢把自己安顿回当下。",
            "project_title": "心安归位样稿",
            "problem_brief": {
                "clarified_problem": "真正需要被看见的，不是事情到底有没有标准答案，而是为什么很多人总把心放在悬空处，忘了先让自己落地；也要让读者看见，当那颗心慢慢安顿下来，很多事会重新有了轻重。",
                "observed_phenomenon": "很多人明明没有被某件大事彻底压垮，心里却一直松不下来，白天装没事，夜里还在反复琢磨。",
                "writing_goal": "把人为什么总在事情未必最糟的时候，先把自己困在那颗一直绷着的心里讲清楚，也让读者看见心安不是放弃，而是把自己慢慢安放回生活。",
                "target_reader_situation": "明明事情不算最糟，却一直被心里的拉扯拖住，怎么也松不下来的人",
                "core_conflict": "真正把人拖累的，很多时候不是事情本身，而是那颗一直绷着、总想把一切想明白却迟迟不肯松下来的心。",
                "constraints": ["不要写成口号文"],
                "feedback_entry": "读者会松一口气，知道自己不是非得把一切想透，才有资格慢慢松下来。",
            },
            "strategy_card": {
                "reader_situation": "明明事情不算最糟，却一直被心里的拉扯拖住，怎么也松不下来的人",
                "point_of_view": "不急着劝人立刻看开，先把那颗心为什么一直落不下来讲清楚，再把读者慢慢带回她真正想安顿的地方。",
                "conflict_frame": "真正把人拖累的，很多时候不是事情本身，而是那颗一直绷着、总想把一切想明白却迟迟不肯松下来的心。",
                "emotional_path": "先认出那颗心为什么总悬着、总想先把一切想稳，再看人怎样从反复较劲里慢慢松下来，重新住回一餐一饮和眼前的日常。",
                "structure_mode": "inner_settlement",
                "opening_move": "开头先落一个心还没完全跟上日子的现实接口：事情过去了，心还留在原地；人已经坐下来了，脑子还在回放。第一屏以短段为主，不要先讲大道理、关系结果、身体告警或幸福定义。",
                "body_shift": "中段先拆那颗心为什么总想把一切想稳、想透或想明白，结果越想越难放下；再写人怎样从现实余波里慢慢回稳，把心一点点放回眼前正在过的生活。",
                "ending_move": "结尾回到一个心终于稍微放平下来的轻动作，不要写成关系结果、身体提醒或祝福收束。",
                "recomposition_recipe": [
                    "前半篇先守住一个心没安下来带出的现实卡点，不要一上来就滑去关系等待、身体告警或幸福公式。",
                    "中段沿着“外界未必最糟 -> 心里一直在拧 -> 人怎样把自己慢慢放回日常”推进。",
                ],
                "expression_constraints": ["不要用名言抚慰直接翻牌"],
                "divergence_axes": ["不要回收参考文里的名言、祝福口吻或现成心灵判断"],
                "execution_checklist": ["是否先守住心没安下来带出的现实卡点，再推进把自己放回一餐一饮和一呼一吸。"],
                "benchmark_summary": "只借原文对应的内在拉扯类型和心安归位主线，不借原文标题、名言排布和结尾动作。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "很多事没有真的压垮你，只是那颗心一直没肯松下来。",
                "outline_body": "1. 心为什么一直悬着\n2. 总想把一切想明白的人，先被自己拖住\n3. 一餐一饮怎样把人慢慢放回当下",
            },
        }
    )

    assert _has_inner_settlement_focus(payload) is True
    assert "先根据参考文里“心为什么一直安不下来、又怎样慢慢放回日常”这条主线重组新选题。" in topic_template.instructions
    assert "标题尽量给出回稳、回到日子里、有地方放的方向感" in topic_template.instructions
    assert "外界未必最糟时，人为什么还是会先把自己留在悬着的状态里" in topic_template.prompt
    assert "标题和切入角度优先围绕心为什么一直安不下来、人为什么总想先把自己说服明白或把日子安排妥帖、又怎样慢慢把自己安放回当下来重组。" in topic_template.instructions
    assert "若策略包要求心安归位推进，大纲先守住一个外界未必最糟、心却一直没松下来的时刻" in outline_template.instructions
    assert "前半篇尽量早点给读者一个被理解、被接住的落点。" in outline_template.instructions
    assert "大纲要继续顺着这条主线推进。" in outline_template.instructions
    assert "开头第一屏先落一个还没被安放好、却已经想慢慢回位的现实接口" in draft_template.instructions
    assert "不要顺手排成胸口发紧、胃口变浅、睡不沉这类症状化句群。" in draft_template.instructions
    assert "不要顺手排成胸口、胃口、睡眠这类症状清单。" in draft_template.instructions
    assert "若策略包要求心安归位推进，正文第一屏先落一个还没被安放好的现实接口" in draft_template.instructions
    assert "开头第一屏先落一个还没被安放好、却已经想慢慢回位的现实接口" in draft_template.instructions
    assert "开篇方式：先从那颗心还没完全落回今天的现实接口起笔" in draft_template.prompt
    assert "至少保住 2 处可摘录短句" in draft_template.prompt
    assert "收束方式：结尾回到一个心终于稍微放平下来的轻动作、现实余波或继续生活的安排" in draft_template.prompt
    assert "不要固定滑向灯光、饭点、水杯、房间这组物件" in draft_template.instructions
    assert "第一屏最好压成 3 到 4 个短段" in draft_template.instructions
    assert "第 2 到第 4 段之间，至少要有一句直接把读者从自责、僵着或反复较劲里接住" in draft_template.instructions
    assert "前六段至少留 2 处能单独成段的短句" in draft_template.instructions
    assert "不要反复复用同一句骨架" in draft_template.instructions
    assert "中后段多写松下来、落地、重新住回日子、终于有地方放这类回暖感" in draft_template.instructions
    assert "最后两段至少有一段要明显比前文更暖" in draft_template.instructions
    assert "灯还亮着、人已经很困" not in draft_template.instructions
    assert "你不是有问题，你只是太久没歇下来" not in outline_template.instructions
    assert "人想休息，心不批准" not in draft_template.instructions


def test_build_draft_prompt_includes_broad_emotional_release_guard() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "你以为幸福是得到，后来才懂有些幸福叫放下",
            "topic_angle": "从人为什么总把幸福误解成继续争取切入，写我们怎样在强求和不甘心里耗尽自己，又怎样在放手后重新看见已经拥有的部分。",
            "project_title": "幸福是什么",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "article_title": "幸福是什么",
            "author": "未知",
            "source_name": "手动录入",
            "summary": "文章把幸福的定义从“不断获得”转向“适时放下”，重点讨论人在关系和目标里因不甘心而持续强求的自我消耗。",
            "body_markdown": (
                "幸福是什么？我们总以为，幸福是“得到”。后来才懂，幸福其实是“放下”。\n\n"
                "明明一段关系已经烂了，你还死死抓着不放。\n\n"
                "可真正的幸福，恰恰是该结束的时候，不再强求，该珍惜的时候，别无所求。"
            ),
            "structure_notes": "开头从幸福定义反差切入，中段拆强求的代价，结尾回到珍惜已有和知足。",
            "tags": ["幸福认知", "停止强求", "珍惜当下"],
            "problem_brief": {
                "clarified_problem": "真正需要被看见的，不是人人都懂却做不到的道理，而是人为什么明明已经很累了，还是会把不甘心、投入感和希望错当成继续消耗自己的理由。",
                "observed_phenomenon": "很多人把继续投入误认成还有希望，等到心力、睡眠和眼前拥有的东西一起被透支，才发现自己一直没舍得停下来",
                "writing_goal": "把人为什么会把继续投入误认成还有希望讲清楚，让读者看见停下不是认输，而是把心力收回来。",
                "target_reader_situation": "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人",
                "core_conflict": "越舍不得停下，越容易把继续消耗误认成认真，最后连眼前真正重要的东西也一起忽略掉。",
                "constraints": ["不要写成口号文"],
                "feedback_entry": "读者会意识到自己不是离幸福太远，而是一直把不肯停下误认成更接近幸福。",
            },
            "strategy_card": {
                "reader_situation": "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人",
                "point_of_view": "不急着讲知足、放下或清醒的大道理，先把人为什么明明很累却还是不肯松手讲清楚。",
                "conflict_frame": "真正把人困住的，不是没有答案，而是总把舍不得放手误认成还有希望。",
                "emotional_path": "先认出自己一直在和得不到的东西拉扯，再看为什么人总要等到透支之后才愿意停下。",
                "structure_mode": "emotional_engine_direct",
                "opening_move": "开头不要整段生活场景冷启动，先用一句会让人停一下的误认判断把读者拉进来。",
                "body_shift": "中段先拆情绪发动机：人为什么会把继续投入误认成还有希望，又为什么总要等到失去之后才看见已经拥有的部分。",
                "ending_move": "结尾给读者一个明确的价值赦免和现实答案：停下来不是失去，是把心力收回来。",
                "expression_constraints": ["不要用口号式收尾"],
                "divergence_axes": ["标题骨架要换成新的现实入口或处境入口"],
                "execution_checklist": ["标题是否已经换成新的现实入口，而不是复述题眼。"],
                "benchmark_summary": "只借原文对应的生活压力类型和情绪发动机，不借原文标题、首段场景、推进顺序和结尾动作。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "你以为自己还在争取，其实很多东西已经先被你拿去垫这场拉扯。",
                "outline_body": "1. 误认从哪里开始\n2. 拉扯怎样搬空日常\n3. 为什么总要失去后才看见拥有\n4. 停下不是认输",
            },
        }
    )

    assert "正文不要自动收窄成坏关系止损、分手复盘或单一关系博弈。" in template.instructions
    assert "不要把正文压成聊天框、等回复、试探态度这一类单一关系等待戏" in template.instructions
    assert "至少留一段专门写“人原本已经拥有、后来却在拉扯中慢慢忽略掉的东西”" in template.instructions
    assert "开头第一屏不要只剩消息框、对话框、回没回这类关系界面" in template.instructions


def test_self_reliance_focus_detector_and_prompt_guards() -> None:
    payload = {
        "trend_title": "参考文章 / 手动录入",
        "topic_title": "即使没有帮助，也要学会自救自渡",
        "topic_angle": "从成年人想向外找安慰却发现别人也各自承压切入，写一个人怎样慢慢把自己托过去。",
        "project_title": "自救自渡样稿",
        "source_type": "tracked_article",
        "source_ref_slug": "self-reliance-guard-demo",
        "tone_profile": TONE_PROFILE,
        "article_title": "即使没有帮助，也要学会自救自渡",
        "author": "未知",
        "source_name": "手动录入",
        "summary": "文章从想找人倾诉却发现身边人也自顾不暇的场景切入，写成年人在低谷里对外求助常常得不到及时回应，于是逐渐学会收起委屈、转向自我消化和自我修复。核心落点不是拒绝他人，而是提醒人在不被接住的时候，也要有把自己托起来的能力。",
        "body_markdown": (
            "相信你也有过这样的时刻：心情不好的时候想找朋友倾诉，却发现朋友也愁眉不展。\n\n"
            "只有向内求，才能自我疗愈，生生不息。只有靠自己，你才能有所顿悟、有所收获、有所改变。\n\n"
            "即使没有帮助，也不会孤立无援，而是能够自救自渡。"
        ),
        "structure_notes": "先写想倾诉却发现别人也各自承压的现实处境，中段再拆为什么外求未必总能接住人，结尾回到向内稳住、自救自渡和慢慢把自己托起来。",
        "tags": ["自我疗愈", "情绪自救", "成年人压力", "低谷时刻", "自我支撑"],
    }

    assert _has_self_reliance_inward_support_focus(payload) is True

    topic_template = build_topic_prompt(payload)
    outline_template = build_outline_prompt(payload)
    draft_template = build_draft_prompt(
        {
            **payload,
            "problem_brief": {
                "clarified_problem": "真正需要被看见的，不是为什么没人总能立刻来帮你，而是为什么人在外求落空以后，仍然要学会把自己慢慢托过去。",
                "observed_phenomenon": "很多人想找人倾诉时，先看到的却是别人也各自承压，于是只好把委屈收回来。",
                "writing_goal": "把成年人为什么会从向外等安慰，慢慢转向向内求冷静、沉淀和成长讲清楚。",
                "target_reader_situation": "在低谷里想找支撑，却慢慢发现真正能长期托住自己的还是自己的人",
                "core_conflict": "外部支撑未必总能及时到位，可人又不能永远停在原地等谁来救。",
                "constraints": ["不要写成口号文"],
                "feedback_entry": "读者会意识到，自救自渡不是逞强，而是把自己慢慢托过去。",
            },
            "strategy_card": {
                "reader_situation": "在低谷里想找支撑，却慢慢发现真正能长期托住自己的还是自己的人",
                "point_of_view": "不急着劝人硬扛，先把外面的帮扶为什么未必总能及时赶上讲清楚。",
                "conflict_frame": "真正难的，不是承认自己需要帮助，而是当帮助没有及时到位时，怎样不让自己一直塌下去。",
                "emotional_path": "先认出外求落空的失落，再看一个人怎样一点点把依靠收回自己身上。",
                "structure_mode": "self_reliance_inward_support",
                "opening_move": "先落一个想找人说说，却发现别人也各自承压的现实接口。",
                "body_shift": "中段先拆为什么外面的帮扶未必总能及时赶上一个人，再写向内求冷静、沉淀和成长。",
                "ending_move": "结尾回到自救自渡和慢慢把自己托过去。",
                "expression_constraints": ["不要用口号式收尾"],
                "divergence_axes": ["标题骨架要换成新的现实入口或处境入口"],
                "execution_checklist": ["是否守住了外求未必及时和向内求这条主线。"],
                "benchmark_summary": "只借原文对应的低谷压力和向内支撑主线，不借标题骨架和关系沟通外壳。",
            },
            "outline": {
                "hook": "不是每一次难过，都能刚好等到一个有空的人。",
                "outline_body": "1. 外求落空的现实感\n2. 为什么别人也接不住你\n3. 把依靠收回自己身上\n4. 自救自渡不是硬扛",
            },
        }
    )

    assert "不要把选题收窄成关系里说不出口、边界表达、误解修复" in topic_template.instructions
    assert "不要把题眼改写成“需要说得很轻”" in topic_template.instructions
    assert "标题尽量带一点把自己安顿住、把日子接回来的温度" in topic_template.instructions
    assert "大纲不要自动滑成关系误会、表达退缩或求助技巧稿" in outline_template.instructions
    assert "开头钩子不要默认写成界面细节或等一句表态" in outline_template.instructions
    assert "不要复用“连借一只手都要排队”这类把注意力钉回求援姿态的旧钩子" in outline_template.instructions
    assert "前四段附近就要给出第一个回稳动作" in outline_template.instructions
    assert "正文不要自动改写成关系误会、表达退缩或求助技巧稿" in draft_template.instructions
    assert "第一屏优先写现实承压和外援来不及" in draft_template.instructions
    assert "第一屏不要把界面细节、输入状态或等一句表态这类旧镜头当主画面" in draft_template.instructions
    assert "不要把主题偷换成谁回没回、谁听没听见" in draft_template.instructions
    assert "不要把一句悬着没落地的话当成开头主镜头或结尾收束" in draft_template.instructions
    assert "不要复用“谁都没法分神来接你一下”“消息还在往前推”“我快撑不住了”“说出口也未必有人接得住”“身边的人也都在”“大家都在忙”这类旧骨架" in draft_template.instructions
    assert "不要把电话打出去一圈、回得慢一点、语气短一点、等回音、随叫随到这类回应戏写成主推进" in draft_template.instructions
    assert "不要把“等消息、等回音、等什么时候轮到我”这类等待戏重新带回来" in draft_template.instructions
    assert "前六段至少留 2 处能单独成段的短句" in draft_template.instructions
    assert "不要连续两段都在解释“为什么最后还是得靠自己”" in draft_template.instructions
    assert "最迟从第 4 到第 6 段之间开始转向可运转状态、顺序恢复和自我托底" in draft_template.instructions
    assert "不要写成“第一步往往很小”“方法也不复杂”“你能做的，是”这类教程口吻" in draft_template.instructions
    assert "只挑 1 到 2 个贴着处境的动作" in draft_template.instructions
    assert "不要连续三句都用“先”起手" in draft_template.instructions
    assert "同一段里如果前一句已经用了“先”，后一句尽量改成直接动作或结果" in draft_template.instructions
    assert "不要把“等……等……等……”排成三拍等待句" in draft_template.instructions
    assert "少用“一点、一下、一件、一条”这类泛量词去托节奏" in draft_template.instructions
    assert "一句一段也要保持句子完整，不要留下半截句" in draft_template.instructions
    assert "不要顺手排成胸口发紧、胃口变浅、睡不沉这类症状串" in draft_template.instructions
    assert "如果要留可摘录短句，优先写成贴着现实压力长出来的人话" in draft_template.instructions
    assert "最后两段至少有一段要比前文更暖一点" in draft_template.instructions
    assert "结尾要给人被稳住的感觉" in draft_template.instructions

    effective_tone_profile = draft_template.prompt
    assert "先从一个现实阻力已经顶上来的接口切入" in effective_tone_profile
    assert "不要把主镜头钉在聊天界面、输入状态或一句悬着没落地的话上" in effective_tone_profile
    assert "段落要短，前六段至少留 2 处一句一段的人话短句" in effective_tone_profile
    assert "不要连续两段都在解释机制" in effective_tone_profile
    assert "最迟到第 4 段附近就要给出第一个自我托底动作或顺序恢复动作" in effective_tone_profile
    assert "独立短句也要是完整人话，不要为了停顿感留下半截句" in effective_tone_profile
    assert "不要顺手排成胸口、胃口、睡眠这类症状句群" in effective_tone_profile
    assert "结尾落在一个把自己托住的普通动作上" in effective_tone_profile
    assert "最后不要收在悬着的情绪上" in effective_tone_profile
    assert "标题、首屏和短句尽量写得温一点" in effective_tone_profile


def test_build_draft_prompt_keeps_broad_emotional_release_guard_when_reference_is_hidden() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "你以为幸福是得到，后来才懂有些幸福叫放下",
            "topic_angle": "从人为什么总把幸福误解成继续争取切入，写我们怎样在强求和不甘心里耗尽自己，又怎样在放手后重新看见已经拥有的部分。",
            "project_title": "幸福是什么",
            "source_type": "tracked_article",
            "reference_article_hidden": True,
            "tone_profile": TONE_PROFILE,
            "outline": {
                "hook": "你以为自己还在争取，其实很多东西已经先被你拿去垫这场拉扯。",
                "outline_body": "1. 误认从哪里开始\n2. 拉扯怎样搬空日常\n3. 为什么总要失去后才看见拥有\n4. 停下不是认输",
            },
            "problem_brief": {
                "raw_goal": "你以为幸福是得到，后来才懂有些幸福叫放下",
                "clarified_problem": "真正需要被看见的，不是人人都懂却做不到的道理，而是人为什么明明已经很累了，还是会把不甘心、投入感和希望错当成继续消耗自己的理由。",
                "observed_phenomenon": "很多人把继续投入误认成还有希望，等到心力、睡眠和眼前拥有的东西一起被透支，才发现自己一直没舍得停下来",
                "writing_goal": "把人为什么会把继续投入误认成还有希望讲清楚，让读者看见停下不是认输，而是把心力收回来。",
                "target_reader_situation": "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人",
                "core_conflict": "越舍不得停下，越容易把继续消耗误认成认真，最后连眼前真正重要的东西也一起忽略掉。",
                "constraints": ["不要写成口号文"],
                "feedback_entry": "读者会意识到自己不是离幸福太远，而是一直把不肯停下误认成更接近幸福。",
            },
            "strategy_card": {
                "reader_situation": "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人",
                "point_of_view": "不急着讲知足、放下或清醒的大道理，先把人为什么明明很累却还是不肯松手讲清楚。",
                "conflict_frame": "真正把人困住的，不是没有答案，而是总把舍不得放手误认成还有希望。",
                "emotional_path": "先认出自己一直在和得不到的东西拉扯，再看为什么人总要等到透支之后才愿意停下。",
                "structure_mode": "emotional_engine_direct",
                "opening_move": "开头不要整段生活场景冷启动，先用一句会让人停一下的误认判断把读者拉进来。",
                "body_shift": "中段先拆情绪发动机：人为什么会把继续投入误认成还有希望，又为什么总要等到失去之后才看见已经拥有的部分。",
                "ending_move": "结尾给读者一个明确的价值赦免和现实答案：停下来不是失去，是把心力收回来。",
                "expression_constraints": ["不要用口号式收尾"],
                "divergence_axes": ["标题骨架要换成新的现实入口或处境入口"],
                "execution_checklist": ["标题是否已经换成新的现实入口，而不是复述题眼。"],
                "benchmark_summary": "只借原文对应的生活压力类型和情绪发动机，不借原文标题、首段场景、推进顺序和结尾动作。",
            },
            "benchmarks": [],
        }
    )

    assert "正文不要自动收窄成坏关系止损、分手复盘或单一关系博弈。" in template.instructions
    assert "不要把正文压成聊天框、等回复、试探态度这一类单一关系等待戏" in template.instructions
    assert "后文必须把代价写回睡眠、注意力、生活节奏、朋友家人或已经拥有却被忽略的部分。" in template.instructions
    assert "正文至少要有两段不以消息、回复、对方、关系这些词为主抓手" in template.instructions


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
                "social_teaser_options": ["导语一", "导语二", "导语三"],
                "recommended_title": "标题二",
                "title_options": ["标题一", "标题二", "标题三"],
            },
        }
    )

    assert "项目标题：办公室倦怠修复周更" in template.prompt
    assert "风格档案：女性成长克制陪伴风" in template.prompt
    assert "标题备选：标题一 / 标题二 / 标题三" in template.prompt
    assert "导语候选：导语一 / 导语二 / 导语三" in template.prompt
    assert "主推标题：标题二" in template.prompt
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
    assert "问题澄清：为什么很多关系不是毁在大冲突，而是毁在一次次没被接住的小失望。" in template.prompt
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
    assert "主动拉开距离：" in template.prompt
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
    assert "问题澄清：为什么很多关系最后耗在一次次没说出口的失望里。" in template.prompt
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
    assert "主动拉开距离：" in template.prompt
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


def test_build_scene_first_prompts_hold_first_two_to_three_beats_inside_the_scene() -> None:
    payload = {
        "trend_title": "参考文章 / 手动录入",
        "topic_title": "很多关系真正远掉，不是吵散了，是那句该问的话总被留在现场后面",
        "topic_angle": "从接驳车、地铁口和没发出去的话切入，写关系怎样在一次次先算了里慢慢变轻。",
        "project_title": "场景优先推进验证稿",
        "tone_profile": TONE_PROFILE,
        "problem_brief": {
            "clarified_problem": "这篇文章要解释，为什么很多关系不是突然变淡，而是在一次次没问出口里慢慢拉远。",
            "target_reader_situation": "总在该问时先算了的人",
            "core_conflict": "明明察觉到了变化，却总在现场里先把更重要的话压回去。",
        },
        "strategy_card": {
            "reader_situation": "总在该问时先算了的人",
            "point_of_view": "先让读者跟着现场进去，再把那句没问出口的话讲明白。",
            "conflict_frame": "不是吵散了，而是每次想问的时候都先算了。",
            "emotional_path": "从现场停顿进入，再慢慢走到敢开口面对真实。",
            "structure_mode": "scene_first_progression",
            "opening_move": "开头先落地铁口和没发出去的话。",
            "body_shift": "中段再拆为什么那句话总被压回去。",
            "ending_move": "结尾回到一次更小但真实的开口动作。",
            "expression_constraints": ["不要一上来平铺道理"],
            "divergence_axes": ["不要把第二段改成抽象总括"],
            "execution_checklist": ["前两到三段先守住现场"],
            "benchmark_summary": "先让动作、停顿和位置变化带路，再让判断长出来。",
        },
        "benchmarks": [],
    }

    outline_template = build_outline_prompt(payload)
    draft_template = build_draft_prompt(
        {
            **payload,
            "outline": {
                "hook": "车门快关上的时候，她还是没把那句话发出去。",
                "outline_body": "1. 现场停顿\n2. 关系怎么慢慢变轻\n3. 重新开口",
            },
        }
    )

    assert "若策略包强调场景优先推进，大纲前两到三行先沿同一个现场顺着动作、停顿、物件或位置变化往前走，" in outline_template.instructions
    assert "判断必须从现场里自己长出来，不要第二行就改成泛关系结论，也不要直接平铺观点。" in outline_template.instructions
    assert "若策略包强调场景优先推进，正文前两到三段必须继续沿同一个现场顺着动作、停顿、物件、界面或位置变化往前走，" in draft_template.instructions
    assert "不要第一段给场景、第二段立刻抽象讲“很多人”“关系里”“其实”。" in draft_template.instructions
    assert "判断要从当场没说出口、没继续做下去或被压回去的那一下里慢慢长出来，再逐步展开，" in draft_template.instructions
    assert "不要直接平铺观点，也不要写成标准答案讲解稿。" in draft_template.instructions


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


def test_build_draft_prompt_uses_strategy_first_draft_mode_by_default_for_tracked_article() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "总把自己往后放的人，生活为什么会慢慢失序",
            "topic_angle": "从人为什么总把幸福误认成继续争取切入，写清放手以后才重新看见已拥有的那部分安稳。",
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

    assert "当前任务是参考文章策略稿的首稿阶段。" in template.instructions
    assert "不要抢着把去 AI 味、平台包装、漂亮收尾和完整示范文腔一次做满" in template.instructions
    assert "大纲锚点：" in template.prompt
    assert "大纲内容：" not in template.prompt
    assert "观察焦点：" in template.prompt
    assert "观察到的现象：" not in template.prompt
    assert "执行原则：沿着这些策略结论写，不回收参考文原句、原顺序和原结尾。" in template.prompt
    assert "写前约束：" not in template.prompt
    assert "拉开距离检查：" not in template.prompt
    assert "写作执行：" not in template.prompt
    assert "返回前自检：" not in template.prompt
    assert "原创不是把现成观点换一批近义词，而是重新建立观察路径、场景重心和句子节奏。" not in template.instructions
    assert "按中文公众号 AI 味风险检查表达：" not in template.instructions
    assert "正文要更贴近真实公众号作者写作，而不是模型一次性生成的标准成品。" not in template.instructions
    assert "请把选题和大纲扩写成一篇中文首稿。" in template.instructions
    assert len(template.instructions) < 2600
    assert len(template.prompt) < 2600


def test_build_draft_prompt_keeps_full_owner_stack_for_non_tracked_article_strategy_payload() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "热点 / 夜读观察",
            "topic_title": "关系里总在解释的人，后来都学会了沉默",
            "topic_angle": "从一次次解释无效的处境切入，拆开人为什么会慢慢收声。",
            "project_title": "解释疲惫观察",
            "source_type": "trend",
            "tone_profile": TONE_PROFILE,
            "problem_brief": {
                "clarified_problem": "这篇文章要解释，为什么很多人会在关系里越解释越沉默。",
                "observed_phenomenon": "每次想说清楚，最后都变成一场自我消耗。",
                "writing_goal": "把解释疲惫是怎么堆起来的讲清楚。",
                "target_reader_situation": "总在关系里解释自己的人。",
                "core_conflict": "越想被理解，越容易先把力气耗光。",
                "constraints": ["不要写成鸡汤"],
                "feedback_entry": "让读者先认出自己为什么越来越不想说话。",
            },
            "strategy_card": {
                "reader_situation": "总在关系里解释自己的人。",
                "point_of_view": "先写解释为什么失效，再写沉默怎么长出来。",
                "conflict_frame": "不是一次闭嘴，而是很多次解释以后慢慢收回去。",
                "emotional_path": "从解释无效，到承认心累。",
                "structure_mode": "single_window_scene",
                "opening_move": "先落一次解释到一半又停下来的现场。",
                "body_shift": "中段拆开失效和疲惫。",
                "ending_move": "结尾收在一次没继续解释的小动作。",
            },
            "outline": {
                "hook": "她把打好的那段话又删掉了。",
                "outline_body": "1. 解释到一半停下\n2. 为什么越解释越累\n3. 沉默是怎么长出来的",
            },
        }
    )

    assert "当前任务是参考文章策略稿的首稿阶段。" not in template.instructions
    assert "原创不是把现成观点换一批近义词，而是重新建立观察路径、场景重心和句子节奏。" in template.instructions
    assert "按中文公众号 AI 味风险检查表达：" in template.instructions
    assert "正文要更贴近真实公众号作者写作，而不是模型一次性生成的标准成品。" in template.instructions


def test_build_draft_prompt_compacts_tracked_article_polish_payload() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "总说等忙完这一阵，却开始看见身体发出的提醒",
            "topic_angle": "从人为什么总把幸福误认成继续争取切入，写清放手以后才重新看见已拥有的那部分安稳。",
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


def test_build_draft_prompt_uses_timeout_recovery_mode_for_tracked_article() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "幸福不是继续强求，而是看见自己已经拥有的东西",
            "topic_angle": "从人为什么总把幸福误认成继续争取切入，写清放手以后才重新看见已拥有的那部分安稳。",
            "project_title": "幸福是什么",
            "source_type": "tracked_article",
            "tone_profile": TONE_PROFILE,
            "compact_strategy_mode": True,
            "timeout_recovery_mode": True,
            "reference_article_title": "幸福是什么",
            "reference_article_author": "北岛",
            "reference_article_source_name": "手动录入",
            "reference_article_summary": "幸福不是一味得到，而是学会放下执念，重新看见已经拥有的部分。",
            "reference_article_body_markdown": (
                "别再追问幸福是什么了。真正的幸福，不是继续强求得不到的东西，"
                "而是该结束的时候放下，该珍惜的时候看见自己已经拥有的部分。"
            ),
            "reference_article_structure_notes": "总论 + 关系例子 + 目标例子 + 回到已拥有",
            "reference_article_tags": ["幸福", "放下", "珍惜已有"],
            "outline": {
                "hook": "她把消息框关掉以后，才看见晚饭已经凉了。",
                "outline_body": (
                    "1. 先写一个已经拥有却被顺手忽略的现实抓手。\n"
                    "2. 解释人为什么总把幸福误认成继续争取。\n"
                    "3. 把代价写回生活秩序、身体和已经拥有的人。\n"
                    "4. 收在放手以后终于空出来的那一下。"
                ),
            },
        }
    )

    assert "草稿超时救援模式" in template.instructions
    assert "不要先铺一段没有信息增量的氛围场景" in template.instructions
    assert "不要缩成单一坏关系复盘" in template.instructions
    assert "参考文章来源线索" in template.prompt
    assert "创作策略包（执行摘要）：" not in template.prompt
    assert "参考文章已经在选题和大纲阶段被消化" not in template.instructions
    assert "不要把幸福写成输赢、诚意、沉没成本或关系谈判问题" in template.instructions
    assert len(template.instructions) < 2600
    assert len(template.prompt) < 2200


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


def test_jinwan_youyu_pressure_tweak_replaces_empty_answer_with_real_interface() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 夜读关系实验室",
            "topic_title": "别把日子过反了",
            "topic_angle": "从体检、回电话和生活排序被往后放的处境切入。",
            "project_title": "慢修复关系稿",
            "source_type": "tracked_article",
            "summary": "文章重点是生活排序失衡和自我照料被推迟。",
            "structure_notes": "从身体提醒进入，再落到生活顺序。",
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
            "problem_brief": {
                "clarified_problem": "这篇文章要解释，为什么一个人会把真正重要的事不断往后放。",
                "target_reader_situation": "总把自己往后排的人",
                "core_conflict": "越想先把外面的事处理完，越容易把自己的余量耗空。",
            },
            "strategy_card": {
                "reader_situation": "总把自己往后排的人",
                "point_of_view": "先把推迟是怎么发生的讲清楚。",
                "conflict_frame": "不是突然失控，而是一次次顺手往后挪。",
                "emotional_path": "先认出身体和生活里的提醒，再慢慢看到代价。",
                "structure_mode": "pressure_interface_direct",
                "opening_move": "开头先落一个已经开始出代价的现实接口。",
                "body_shift": "中段沿着压力链推进。",
                "ending_move": "结尾回到一个还没完全处理完的小动作上。",
                "expression_constraints": ["不要用口号式收尾"],
                "divergence_axes": ["不要把原文压成一个连续主角场景"],
                "execution_checklist": ["是否串起了 2 到 4 个现实接口"],
                "benchmark_summary": "只借处境类型，不借原文骨架。",
            },
            "benchmarks": [],
            "outline": {
                "hook": "体检预约又被她顺手改了时间。",
                "outline_body": "1. 先落一个被顺手往后挪开的普通接口\n2. 串起消息、体检、关系回应\n3. 解释为什么总轮不到自己\n4. 回到一个还没完全解决的小动作上",
            },
        }
    )

    assert "不要先端出抽象人生答案" in template.instructions
    assert "先落一个现实接口、后果或身体信号" in template.instructions
    assert "不要让开头和收束都先端出空泛答案" in template.instructions


def test_jinwan_youyu_pressure_tweak_keeps_internal_pressure_guard_on_tracked_article() -> None:
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
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
            "outline": {
                "hook": "体检提醒亮了一下，她先把页面划掉。",
                "outline_body": "1. 被顺手往后放的接口\n2. 为什么总轮不到自己\n3. 日常排序怎么慢慢歪掉",
            },
        }
    )

    assert "正文不要自动收窄成亲密关系摊牌、深夜删消息、等回复或关系修复主线。" in template.instructions
    assert "不要把伴侣/对话对象写成唯一主场景。" in template.instructions
    assert "不要先端出抽象人生答案" in template.instructions


def test_jinwan_youyu_internal_pressure_overrides_opening_style_in_prompt_section() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "从尿毒症到透析，人为什么总把自己拖到最后",
            "topic_angle": "不是你不想好好活，而是你总把自己的求救信号排到最后。",
            "project_title": "善待自己，好好爱自己",
            "source_type": "tracked_article",
            "reference_article_title": "善待自己，好好爱自己",
            "reference_article_summary": "文章重点是人总把自己的身体提醒和自我照料拖到最后。",
            "reference_article_structure_notes": "从身体变化进入，再落到人总把自己排在最后。",
            "reference_article_tags": ["身体提醒", "自我照料"],
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
            "outline": {
                "hook": "复查提醒弹出来时，她先点了稍后再说。",
                "outline_body": "1. 复查被往后放\n2. 身体提醒怎么一步步变重\n3. 为什么总轮不到自己",
            },
        }
    )

    assert "开篇方式：如果题材是自我消耗、生活排序失衡、健康透支或身体提醒，开头先落到一个真实接口、被顺手往后放的安排或已经露出的代价，不要先写成空泛答案句；可以直接，但不要把答案先钉死在抽象判断上。" in template.prompt
    assert "段落节奏：先用真实接口带路，再给判断与落点；多数段落以 1 到 2 句为主" in template.prompt
    assert "每段都要能让读者认出自己当下正在经历的那一下" in template.prompt
    assert "收束方式：收束时优先落在一个现实动作、后果余波或轻微决定上，可以给判断，但不要把结尾写成已经讲完题的标准答案。" in template.prompt


def test_jinwan_youyu_internal_pressure_draft_rules_do_not_prioritize_question_opening() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "从尿毒症到透析，人为什么总把自己拖到最后",
            "topic_angle": "不是你不想好好活，而是你总把自己的求救信号排到最后。",
            "project_title": "善待自己，好好爱自己",
            "source_type": "tracked_article",
            "reference_article_title": "善待自己，好好爱自己",
            "reference_article_summary": "文章重点是人总把自己的身体提醒和自我照料拖到最后。",
            "reference_article_structure_notes": "从身体变化进入，再落到人总把自己排在最后。",
            "reference_article_tags": ["身体提醒", "自我照料"],
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
            "outline": {
                "hook": "复查提醒弹出来时，她先点了稍后再说。",
                "outline_body": "1. 复查被往后放\n2. 身体提醒怎么一步步变重\n3. 为什么总轮不到自己",
            },
        }
    )

    assert "开头先落一个现实接口、被顺手往后放的安排或已经露出的代价，不要先用问句、引用或共鸣替读者下定义。" in template.instructions
    assert "判断可以直接，但不要一上来就把答案说成空泛结论，要让读者先认出自己正在付出的代价。" in template.instructions
    assert "前两到三段里，至少有一段只让动作、后果或现实余波自己说话，不要句句都抢着解释。" in template.instructions
    assert "前四段里，至少保住 1 处一句一段的现实接口、动作后果或被挪走的安排" in template.instructions
    assert "多数段落控制在 1 到 2 句" in template.instructions
    assert "但每个判断最多只补一层解释" in template.instructions
    assert "不要连续两个中长解释段挨着出现" in template.instructions
    assert "除非参考文主冲突本来就建立在身体代价上，否则不要把正文排成胸口、胃口、睡眠这类症状清单。" in template.instructions
    assert "前半篇至少保住 1 句从真实代价里长出来、可以单独成段的可摘录短句或引用式短句" in template.instructions
    assert "如果状态允许，可以再留 1 句，但要把关系位置、代价排序或没被接住的事实压进去，不要连发口号。" in template.instructions
    assert "结尾优先落在一个现实动作、后果余波、没等来的回应或轻微决定上，不要把答案写成空泛总结。" in template.instructions
    assert "尾段不要替读者把情绪讲完，尽量留一点没说满的关系余波" in template.instructions
    assert "开头优先使用问句、引用或共鸣开场" not in template.instructions


def test_jinwan_youyu_internal_pressure_polish_instruction_is_harmonized() -> None:
    template = build_draft_prompt(
        {
            "trend_title": "参考文章 / 手动录入",
            "topic_title": "从尿毒症到透析，人为什么总把自己拖到最后",
            "topic_angle": "不是你不想好好活，而是你总把自己的求救信号排到最后。",
            "project_title": "善待自己，好好爱自己",
            "source_type": "tracked_article",
            "reference_article_title": "善待自己，好好爱自己",
            "reference_article_summary": "文章重点是人总把自己的身体提醒和自我照料拖到最后。",
            "reference_article_structure_notes": "从身体变化进入，再落到人总把自己排在最后。",
            "reference_article_tags": ["身体提醒", "自我照料"],
            "tone_profile": JINWAN_YOUYU_TONE_PROFILE,
            "polish_instruction": "请把正文改成“今晚有语”完整风格：开头用直接问题、现实接口或一句共鸣判断迅速点题，中段围绕 2 到 4 个明确判断展开。",
            "draft": {
                "title": "旧标题",
                "body_markdown": "# 旧标题\n\n旧正文",
            },
            "outline": {
                "hook": "复查提醒弹出来时，她先点了稍后再说。",
                "outline_body": "1. 复查被往后放\n2. 身体提醒怎么一步步变重\n3. 为什么总轮不到自己",
            },
        }
    )

    assert "开头用问句、引用或共鸣迅速点题" not in template.prompt
    assert "开头用直接问题、现实接口或一句共鸣判断迅速点题" not in template.prompt
    assert "开头先落一个现实接口、被顺手往后放的安排或已经露出的代价，不要先用问句、引用或共鸣替读者下定义" in template.prompt
    assert "请保留直接感，但把空泛答案句改成真实接口、被顺手往后放的安排或已经露出的代价" in template.prompt


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
    assert "结构路标风险" in template.instructions
    assert "模糊归因风险" in template.instructions
    assert "不要每段都写成“判断 + 解释 + 小结”" in template.instructions
    assert "多数段落以 1 到 3 句为主" in template.instructions
    assert "不要为了反模板，把现象、动作、解释和后果全压进一个大长段" in template.instructions
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
    assert "如果要保留 1 处可摘录短句，必须来自前文已有动作、代价或关系余波，优先单独成段" in template.instructions
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
