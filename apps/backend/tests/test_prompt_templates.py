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
    assert "原创不是把现成观点换一批近义词，而是重新建立观察路径、场景重心和句子节奏" in draft_template.instructions
    assert "不要先复述题眼或给观点下定义" in draft_template.instructions
    assert "避免每段都写成“观点句 + 解释句”的模板结构" in draft_template.instructions
    assert "句子节奏要有长短变化和呼吸感" in draft_template.instructions


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
    assert "减少“第一步、第二步、第三步”式教程骨架" in template.instructions
    assert "不要为了显得完整而过度解释每一个判断" in template.instructions


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
    assert "避免机械扩写、刻意增肥和整篇统一修辞" in template.instructions
    assert "避免系统性把“和”改成“以及”、“并”改成“并且”" in template.instructions
    assert "不要把句子润成网文腔、鸡汤腔或文学仿写腔" in template.instructions


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
