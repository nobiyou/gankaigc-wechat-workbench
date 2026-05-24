from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.schemas.settings import PromptTemplateSummary


@dataclass(frozen=True)
class PromptTemplate:
    instructions: str
    prompt: str


@dataclass(frozen=True)
class DomainPromptPack:
    key: str
    label: str
    audience: str
    voice: str
    constraints: str


@dataclass(frozen=True)
class PromptTemplateDescriptor:
    key: str
    label: str
    role: str
    objective: str
    output_fields: list[str]
    supports_tone_profile: bool
    supports_domain_pack: bool
    supports_review_feedback: bool


DEFAULT_DOMAIN_PROMPT_PACK = DomainPromptPack(
    key="women-growth",
    label="女性情感成长",
    audience="女性情感成长",
    voice="语言要克制、真实、具体",
    constraints="避免空泛口号、说教感和鸡汤腔",
)

DOMAIN_PROMPT_PACKS: dict[str, DomainPromptPack] = {
    DEFAULT_DOMAIN_PROMPT_PACK.key: DEFAULT_DOMAIN_PROMPT_PACK,
    "workplace-growth": DomainPromptPack(
        key="workplace-growth",
        label="职场成长",
        audience="职场成长",
        voice="语言要冷静、务实、直接",
        constraints="避免抒情过度、泛心理化和悬浮表达",
    ),
    "relationship-repair": DomainPromptPack(
        key="relationship-repair",
        label="亲密关系修复",
        audience="亲密关系修复",
        voice="语言要稳定、克制、有承接感",
        constraints="避免情绪煽动、绝对化判断和简单站队",
    ),
}

PROMPT_TEMPLATE_DESCRIPTORS: list[PromptTemplateDescriptor] = [
    PromptTemplateDescriptor(
        key="topic",
        label="选题生成",
        role="选题编辑",
        objective="把热点或参考文章整理成可直接立项的选题标题和切入角度。",
        output_fields=["title", "angle"],
        supports_tone_profile=True,
        supports_domain_pack=True,
        supports_review_feedback=False,
    ),
    PromptTemplateDescriptor(
        key="outline",
        label="大纲生成",
        role="内容策划编辑",
        objective="根据选题产出开篇钩子与结构化 markdown 大纲。",
        output_fields=["hook", "outline_body"],
        supports_tone_profile=True,
        supports_domain_pack=True,
        supports_review_feedback=False,
    ),
    PromptTemplateDescriptor(
        key="draft",
        label="初稿生成",
        role="正文作者",
        objective="基于大纲扩写正文，并支持精修与审核意见回写。",
        output_fields=["title", "body_markdown"],
        supports_tone_profile=True,
        supports_domain_pack=True,
        supports_review_feedback=True,
    ),
    PromptTemplateDescriptor(
        key="assets",
        label="素材包生成",
        role="包装编辑",
        objective="围绕正文生成标题组选项、封面文案、配图提示词和分发导语。",
        output_fields=["title_options", "cover_prompt", "cover_copy", "social_teaser"],
        supports_tone_profile=True,
        supports_domain_pack=True,
        supports_review_feedback=True,
    ),
    PromptTemplateDescriptor(
        key="cover_image",
        label="封面图生成",
        role="图片生成器",
        objective="根据封面提示词生成 21:9 横版封面图。",
        output_fields=["image/png"],
        supports_tone_profile=False,
        supports_domain_pack=False,
        supports_review_feedback=False,
    ),
    PromptTemplateDescriptor(
        key="publish_package",
        label="发布包生成",
        role="发布编辑",
        objective="基于正文与素材输出摘要、标签和编辑备注。",
        output_fields=["abstract", "tags", "editor_note"],
        supports_tone_profile=True,
        supports_domain_pack=True,
        supports_review_feedback=True,
    ),
]


def _as_clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _render_forbidden_phrases(value: object) -> str:
    if not isinstance(value, list):
        return ""
    items = [_as_clean_text(item) for item in value]
    items = [item for item in items if item]
    return " / ".join(items)


def render_tone_profile_section(tone_profile: Mapping[str, object] | None) -> str:
    if not tone_profile:
        return ""

    lines: list[str] = []
    name = _as_clean_text(tone_profile.get("name"))
    opening_style = _as_clean_text(tone_profile.get("opening_style"))
    paragraph_rhythm = _as_clean_text(tone_profile.get("paragraph_rhythm"))
    closing_style = _as_clean_text(tone_profile.get("closing_style"))
    forbidden_phrases = _render_forbidden_phrases(tone_profile.get("forbidden_phrases"))
    value_constraints = _as_clean_text(tone_profile.get("value_constraints"))

    if name:
        lines.append(f"风格档案：{name}")
    if opening_style:
        lines.append(f"开篇方式：{opening_style}")
    if paragraph_rhythm:
        lines.append(f"段落节奏：{paragraph_rhythm}")
    if closing_style:
        lines.append(f"收束方式：{closing_style}")
    if forbidden_phrases:
        lines.append(f"禁用表达：{forbidden_phrases}")
    if value_constraints:
        lines.append(f"价值约束：{value_constraints}")

    if not lines:
        return ""

    return "风格要求：\n" + "\n".join(lines) + "\n"


def _render_outline_target_wording(tone_profile: Mapping[str, object] | None) -> str:
    target_word_count = tone_profile.get("target_word_count") if tone_profile else None
    if not target_word_count:
        return ""
    return (
        f"目标字数：{target_word_count}\n"
        "请按目标字数规划篇幅，保证 4 到 6 段的大纲能自然支撑正文长度。\n"
        "避免在大纲阶段写得过满，每一段只保留核心推进点，不要预写过多案例、分叉解释和重复论述。\n"
    )


def _render_draft_target_wording(tone_profile: Mapping[str, object] | None) -> str:
    target_word_count = tone_profile.get("target_word_count") if tone_profile else None
    if not target_word_count:
        return ""
    return (
        f"目标字数：{target_word_count}\n"
        "正文篇幅请严格贴近目标字数，允许上下浮动 10% 到 15%。\n"
        "如果明显超出目标字数，请主动压缩场景、避免重复抒情和重复论述。\n"
    )


def _resolve_domain_pack(domain_pack: Mapping[str, object] | DomainPromptPack | None) -> DomainPromptPack:
    if isinstance(domain_pack, DomainPromptPack):
        return domain_pack
    if not isinstance(domain_pack, Mapping):
        return DEFAULT_DOMAIN_PROMPT_PACK

    key = _as_clean_text(domain_pack.get("key"))
    if key and key in DOMAIN_PROMPT_PACKS:
        return DOMAIN_PROMPT_PACKS[key]

    audience = _as_clean_text(domain_pack.get("audience")) or DEFAULT_DOMAIN_PROMPT_PACK.audience
    voice = _as_clean_text(domain_pack.get("voice")) or DEFAULT_DOMAIN_PROMPT_PACK.voice
    constraints = _as_clean_text(domain_pack.get("constraints")) or DEFAULT_DOMAIN_PROMPT_PACK.constraints
    label = _as_clean_text(domain_pack.get("label")) or audience
    return DomainPromptPack(key=key or "custom", label=label, audience=audience, voice=voice, constraints=constraints)


def get_domain_prompt_pack(key: str | None) -> DomainPromptPack | None:
    normalized_key = _as_clean_text(key)
    if not normalized_key:
        return None
    return DOMAIN_PROMPT_PACKS.get(normalized_key)


def list_domain_prompt_packs() -> list[DomainPromptPack]:
    return list(DOMAIN_PROMPT_PACKS.values())


def list_prompt_template_summaries() -> list[PromptTemplateSummary]:
    return [
        PromptTemplateSummary(
            key=descriptor.key,
            label=descriptor.label,
            role=descriptor.role,
            objective=descriptor.objective,
            output_fields=descriptor.output_fields,
            supports_tone_profile=descriptor.supports_tone_profile,
            supports_domain_pack=descriptor.supports_domain_pack,
            supports_review_feedback=descriptor.supports_review_feedback,
        )
        for descriptor in PROMPT_TEMPLATE_DESCRIPTORS
    ]


def build_stage_instructions(
    *,
    role: str,
    task_brief: str,
    domain_pack: Mapping[str, object] | DomainPromptPack | None = None,
) -> str:
    resolved_pack = _resolve_domain_pack(domain_pack)
    return (
        f"你是公众号{role}。"
        f"{task_brief}"
        f"内容面向{resolved_pack.audience}赛道。"
        f"{resolved_pack.voice}。"
        f"{resolved_pack.constraints}。"
    )


def build_outline_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    tone_profile = payload.get("tone_profile")
    style_section = render_tone_profile_section(tone_profile if isinstance(tone_profile, Mapping) else None)
    target_wording = _render_outline_target_wording(tone_profile if isinstance(tone_profile, Mapping) else None)
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="内容策划编辑",
            task_brief="请基于给定选题，输出一个适合女性情感成长公众号的文章大纲。",
            domain_pack=payload.get("domain_pack"),
        ),
        prompt=(
            f"趋势标题：{payload['trend_title']}\n"
            f"选题标题：{payload['topic_title']}\n"
            f"切入角度：{payload['topic_angle']}\n"
            f"项目标题：{payload['project_title']}\n\n"
            f"{style_section}"
            f"{target_wording}"
            "返回：\n"
            "1. 一个 1 句话的情绪钩子 hook\n"
            "2. 一个 4 到 6 段的 markdown 大纲 outline_body"
        ),
    )


def build_topic_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    source_type = _as_clean_text(payload.get("source_type")) or "trend"
    tone_profile = payload.get("tone_profile")
    style_section = render_tone_profile_section(tone_profile if isinstance(tone_profile, Mapping) else None)
    if source_type == "tracked_article":
        source_prompt = (
            f"来源类型：{source_type}\n"
            f"参考文章 slug：{payload['source_ref_slug']}\n"
            f"参考文章标题：{payload['article_title']}\n"
            f"作者：{payload['author']}\n"
            f"来源账号：{payload['source_name'] or '未知公众号'}\n"
            f"摘要：{payload['summary']}\n"
            f"结构备注：{payload['structure_notes']}\n"
            f"标签：{' / '.join(payload.get('tags') or []) or '无'}\n"
        )
        instructions = (
            build_stage_instructions(
                role="选题编辑",
                task_brief="请基于参考文章提炼出一个可直接立项的女性情感成长类原创选题。",
                domain_pack=payload.get("domain_pack"),
            )
            + "不要复述原标题，要重新组织成更适合继续创作的选题。"
        )
    else:
        source_prompt = (
            f"趋势 slug：{payload['trend_slug']}\n"
            f"趋势标题：{payload['trend_title']}\n"
            f"来源：{payload['source']}\n"
            f"热度：{payload['heat_score']}\n"
            f"当前状态：{payload['status']}\n"
        )
        instructions = (
            build_stage_instructions(
                role="选题编辑",
                task_brief="请基于热点线索提炼成一个可直接立项的女性情感成长类选题。",
                domain_pack=payload.get("domain_pack"),
            )
            + "标题要像真实选题，不要写成平台标题党。"
        )

    return PromptTemplate(
        instructions=instructions,
        prompt=(
            f"{source_prompt}\n"
            f"{style_section}"
            "返回：\n"
            "1. 选题标题 title\n"
            "2. 切入角度 angle"
        ),
    )


def build_draft_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    outline = payload["outline"]
    tone_profile = payload.get("tone_profile")
    style_section = render_tone_profile_section(tone_profile if isinstance(tone_profile, Mapping) else None)
    target_wording = _render_draft_target_wording(tone_profile if isinstance(tone_profile, Mapping) else None)
    review_comment = _as_clean_text(payload.get("review_comment"))
    polish_instruction = _as_clean_text(payload.get("polish_instruction"))
    current_draft = payload.get("draft")

    review_section = (
        f"\n审核修改意见：{review_comment}\n"
        "请保留原选题和大纲方向，重点根据这条意见重写正文。"
        if review_comment
        else ""
    )
    polish_section = (
        f"\n精修要求：{polish_instruction}\n"
        f"当前草稿标题：{current_draft['title']}\n"
        f"当前草稿内容：\n{current_draft['body_markdown']}\n"
        "请基于现有草稿精修，不要偏离原有主题与结构主线。\n"
        if polish_instruction and isinstance(current_draft, Mapping)
        else ""
    )
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="正文作者",
            task_brief="请把选题和大纲扩写成一篇可直接进入编辑流程的中文初稿。要求有清晰标题、自然分段、具体场景和收束段。",
            domain_pack=payload.get("domain_pack"),
        ),
        prompt=(
            f"趋势标题：{payload['trend_title']}\n"
            f"选题标题：{payload['topic_title']}\n"
            f"切入角度：{payload['topic_angle']}\n"
            f"项目标题：{payload['project_title']}\n"
            f"{style_section}"
            f"{target_wording}"
            f"大纲钩子：{outline['hook']}\n"
            f"大纲内容：\n{outline['outline_body']}\n"
            f"{review_section}\n"
            f"{polish_section}\n"
            "返回：\n"
            "1. 标题 title\n"
            "2. 正文 markdown body_markdown"
        ),
    )


def build_assets_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    draft = payload["draft"]
    tone_profile = payload.get("tone_profile")
    style_section = render_tone_profile_section(tone_profile if isinstance(tone_profile, Mapping) else None)
    review_comment = _as_clean_text(payload.get("review_comment"))
    review_section = (
        f"\n审核修改意见：{review_comment}\n"
        "请根据这条意见调整封面文案、标题备选和分发导语。"
        if review_comment
        else ""
    )
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="包装编辑",
            task_brief="请围绕正文产出封面和分发素材。",
            domain_pack=payload.get("domain_pack"),
        ),
        prompt=(
            f"趋势标题：{payload['trend_title']}\n"
            f"选题标题：{payload['topic_title']}\n"
            f"切入角度：{payload['topic_angle']}\n"
            f"项目标题：{payload['project_title']}\n"
            f"{style_section}"
            f"正文标题：{draft['title']}\n"
            f"正文内容：\n{draft['body_markdown']}\n"
            f"{review_section}\n"
            "返回：\n"
            "1. 3 个标题备选 title_options\n"
            "2. 1 条封面图提示词 cover_prompt\n"
            "3. 1 条封面文案 cover_copy\n"
            "4. 1 条社媒导语 social_teaser"
        ),
    )


def build_cover_image_prompt(payload: Mapping[str, object]) -> str:
    return (
        "请生成适合公众号头图的横版封面图，目标视觉比例为 21:9。"
        "主体信息放在画面中部安全区，避免关键人物或文字落在上下裁切边缘。"
        f"\n原始创意提示词：{payload['cover_prompt']}"
    )


def build_publish_package_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    tone_profile = payload.get("tone_profile")
    style_section = render_tone_profile_section(tone_profile if isinstance(tone_profile, Mapping) else None)
    review_comment = _as_clean_text(payload.get("review_comment"))
    review_section = (
        f"\n审核修改意见：{review_comment}\n"
        "请确认摘要、标签和编辑备注已经响应这条意见。"
        if review_comment
        else ""
    )
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="发布编辑",
            task_brief="请基于正文和素材，为公众号发布环节输出摘要、标签和编辑备注。内容要简洁、可执行，不要空话。",
            domain_pack=payload.get("domain_pack"),
        ),
        prompt=(
            f"项目标题：{payload['project_title']}\n"
            f"{style_section}"
            f"正文标题：{payload['draft']['title']}\n"
            f"正文内容：\n{payload['draft']['body_markdown']}\n\n"
            f"封面文案：{payload['assets']['cover_copy']}\n"
            f"分发导语：{payload['assets']['social_teaser']}\n"
            f"标题备选：{' / '.join(payload['assets']['title_options'])}\n"
            f"{review_section}\n"
            "返回：\n"
            "1. 发布摘要 abstract\n"
            "2. 3 到 5 个标签 tags\n"
            "3. 编辑备注 editor_note"
        ),
    )
