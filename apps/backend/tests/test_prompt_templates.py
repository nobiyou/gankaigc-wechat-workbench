from __future__ import annotations

from app.services.prompt_templates import (
    build_assets_prompt,
    build_cover_image_prompt,
    build_draft_prompt,
    build_outline_prompt,
    build_publish_package_prompt,
    build_topic_prompt,
    render_tone_profile_section,
)


TONE_PROFILE = {
    "name": "女性成长克制陪伴风",
    "opening_style": "从具体场景冷启动切入",
    "paragraph_rhythm": "短段落，慢推进",
    "closing_style": "留白式收束",
    "forbidden_phrases": ["你必须", "立刻改变"],
    "value_constraints": "不说教，不制造羞耻感，避免空泛鸡汤",
    "target_word_count": 1400,
    "default_polish_instruction": "重写开头和结尾，打散重复句式。",
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
    assert "参考文章标题：听到伴侣说话就烦，不是你脾气差" in template.prompt
    assert "标签：wechat-mp / relationship" in template.prompt
    assert "风格档案：女性成长克制陪伴风" in template.prompt


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
                "clarified_problem": "这篇文章要解释，为什么很多关系不是毁在大冲突，而是毁在一次次没被接住的小失望。",
                "target_reader_situation": "在关系里想解释，却越来越不想开口的人",
                "core_conflict": "越想被理解，越容易把话咽回去。",
            },
            "strategy_card": {
                "reader_situation": "在关系里想解释，却越来越不想开口的人",
                "point_of_view": "不教训，不站高位，只把失望是怎么累出来的讲清楚",
                "conflict_frame": "不是大吵一架，而是一次次想开口又收回去",
                "emotional_path": "从委屈和停顿进入，慢慢走到能重新开口",
                "expression_constraints": [
                    "不要用口号式收尾",
                    "不要复用不是A而是B的对称判断句",
                ],
                "benchmark_summary": "开头先落动作和停顿，中段再进入判断。",
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

    assert "创作策略包：" in template.prompt
    assert "问题澄清：这篇文章要解释，为什么很多关系不是毁在大冲突，而是毁在一次次没被接住的小失望。" in template.prompt
    assert "读者处境：在关系里想解释，却越来越不想开口的人" in template.prompt
    assert "叙述视角：不教训，不站高位，只把失望是怎么累出来的讲清楚" in template.prompt
    assert "冲突框架：不是大吵一架，而是一次次想开口又收回去" in template.prompt
    assert "情绪路径：从委屈和停顿进入，慢慢走到能重新开口" in template.prompt
    assert "表达约束：不要用口号式收尾 / 不要复用不是A而是B的对称判断句" in template.prompt
    assert "参考基准：开头先落动作和停顿，中段再进入判断。" in template.prompt
    assert "基准参考 1：深夜关系观察" in template.prompt
    assert "可借用：开头的处境进入和中段停顿节奏" in template.prompt
    assert "避免：不要复用对方的判断句和结尾收束" in template.prompt


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
    assert "输出前必须做一次静默自检" in template.instructions
    assert "如果超过上述限制，先重写超标段落" in template.instructions
    assert "不要在最终正文里写出自检过程" in template.instructions
    assert "套话风险" in template.instructions
    assert "结构模板风险" in template.instructions
    assert "句式节奏风险" in template.instructions
    assert "抽象空话风险" in template.instructions
    assert "过度解释风险" in template.instructions
    assert "结尾口号风险" in template.instructions


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
