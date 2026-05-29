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
        objective="基于大纲扩写正文，并支持原创增强精修与审核意见回写。",
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


def _render_reference_article_section(payload: Mapping[str, object]) -> str:
    source_type = _as_clean_text(payload.get("source_type"))
    if source_type != "tracked_article":
        return ""

    title = _as_clean_text(payload.get("reference_article_title"))
    author = _as_clean_text(payload.get("reference_article_author"))
    source_name = _as_clean_text(payload.get("reference_article_source_name"))
    summary = _as_clean_text(payload.get("reference_article_summary"))
    structure_notes = _as_clean_text(payload.get("reference_article_structure_notes"))
    tags_value = payload.get("reference_article_tags")

    tags: list[str] = []
    if isinstance(tags_value, list):
        tags = [_as_clean_text(tag) for tag in tags_value if _as_clean_text(tag)]

    return (
        "参考文章信息：\n"
        f"参考文章标题：{title or '无'}\n"
        f"参考文章作者：{author or '未知'}\n"
        f"参考文章来源账号：{source_name or '手动录入'}\n"
        f"参考文章摘要：{summary or '无'}\n"
        f"参考文章结构备注：{structure_notes or '无'}\n"
        f"参考文章标签：{' / '.join(tags) or '无'}\n"
    )


def _build_reference_article_instructions(*, stage: str) -> str:
    if stage == "outline":
        return (
            "参考文章只用于提炼冲突、结构灵感和情绪线索。"
            "禁止复写参考文章的标题、开头句、段落顺序，必须改写成新的叙事路径和新的表达组织。"
        )
    if stage == "draft":
        return (
            "参考文章只用于提炼冲突、结构灵感和情绪线索。"
            "禁止复写参考文章的标题、开头句、段落顺序。"
            "不要沿用参考文章的句子，不要做逐段近义改写，正文必须形成新的场景组织和新的收束表达。"
        )
    return ""


def _build_original_expression_instructions(*, stage: str) -> str:
    if stage == "outline":
        return (
            "大纲不要直接罗列三四条抽象道理，先设计一个具体、可感知的开篇瞬间或动作入口。"
            "中段要写清视角如何从场景推进到情绪、再推进到判断或动作。"
            "结尾要回到人物处境或心绪余波，不要停在口号式总结。"
        )
    if stage == "draft":
        return (
            "原创不是把现成观点换一批近义词，而是重新建立观察路径、场景重心和句子节奏。"
            "优先从一个具体、可感知的瞬间起笔，让动作、环境、声音或身体感受先出现，再带出判断。"
            "不要先复述题眼或给观点下定义，先把读者带进一个可见、可听、可感的当下。"
            "把抽象情绪落到动作停顿、物件光线、空间距离或身体反应上，让情绪有抓手。"
            "正文不要写成标准答案式观点罗列，要让场景、情绪和判断自然推进。"
            "避免每段都写成“观点句 + 解释句”的模板结构，至少让一处段落先发生事情，再慢慢显出判断。"
            "少用“不是A，是B”这类过于整齐的判断句，尤其不要连续拿它做标题、开头或结尾。"
            "减少“第一步、第二步、第三步”式教程骨架，优先写成自然展开的叙事或观察推进。"
            "不要为了显得完整而过度解释每一个判断，允许留白，允许有些意思停在动作或场景里。"
            "避免反复用“一点、一下、一些、一个、一种”去切分感受和动作，同一种量词节奏不要整篇反复出现。"
            "多用具体细节承载观点，少写空泛抒情、万能道理和模板化金句。"
            "句子节奏要有长短变化和呼吸感，不要整篇都像统一模板口播稿。"
            "结尾回到人物处境或心绪余波，克制收束，不要用励志口号硬收。"
        )
    return ""


def _build_localized_ai_flavor_risk_instructions() -> str:
    return (
        "按 6 类中文公众号 AI 味风险检查表达："
        "套话风险，避免万能成长句、万能抒情和空泛金句；"
        "结构模板风险，避免整齐反转、教程分步和标准答案式段落；"
        "句式节奏风险，避免同一种量词、连接词和判断句反复起手；"
        "抽象空话风险，把感受落到动作、物件、空间、声音和身体反应上；"
        "过度解释风险，不要把每个判断都解释透，允许场景和停顿承载意思；"
        "结尾口号风险，结尾回到人物处境或心绪余波，不要喊话式收束。"
    )


def _build_wechat_public_account_draft_instructions() -> str:
    return (
        "正文要更贴近真实公众号作者写作，而不是模型一次性生成的标准成品。"
        "允许局部段落更松一点、更口语一点，但整体仍然要干净、可读、适合公众号排版。"
        "多写人是怎么感到累、怎么停一下、怎么把情绪往回压，少写完整方法论和对所有人的通用结论。"
        "不要把每个判断都解释透，留一点空白给读者自己接上。"
        "避免机械扩写、刻意增肥和整篇统一修辞，不要为了像人写而堆砌“了、的、地、一下、一点、一阵”这类填充。"
        "避免系统性把“和”改成“以及”、“并”改成“并且”、“为了”改成“为了能够”这类生硬替换。"
        "不要把句子润成网文腔、鸡汤腔或文学仿写腔，仍然保持当代中文公众号的自然表达。"
        "专有名词、项目标题、人物关系和核心事实不能改，不能为了润色改掉原本的因果和立场。"
        "如果需要增强原创感，优先更换叙述重心、段落重音和细节抓手，而不是把原句拖长。"
    )


def _build_polish_protocol() -> str:
    return (
        "这不是局部润色任务，而是原创增强精修任务。"
        "按 6 类中文公众号 AI 味风险逐项检查原稿。"
        "先删掉万能抒情、整齐反转、教程分步和口号式结尾。"
        "必须重写开头段和结尾段，优先调整段落连接、场景组织和观点推进顺序。"
        "必须改写场景入口段、中段关键推进段和收束段。"
        "先判断原稿哪些段落最像模板话，再优先拆掉这些段落的原顺序重写。"
        "至少把一个抽象判断段改写成可见场景段，把一个平铺说理段改写成情绪推进段。"
        "如果“一点、一下、一个、一种、一件”这类量词起手过密，主动改掉一半以上，不要整篇都靠同一节奏往下写。"
        "如果原稿一上来就在讲道理，请改成先落画面再带判断。"
        "必要时可以删除过熟的总结句和万能结论，不必把原稿每个判断都保留下来。"
        "不要只做同义词替换、语序微调或局部句子抛光，输出结果要像基于原稿重新写出的一版新正文。"
        "优先更换观察角度、细节选择、段落重心和句子节奏，而不是只修饰原句表面。"
        "输出前自查：场景具体度、句式重复度、模板风险、情绪自然度、改写幅度。"
    )


def build_outline_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    tone_profile = payload.get("tone_profile")
    style_section = render_tone_profile_section(tone_profile if isinstance(tone_profile, Mapping) else None)
    target_wording = _render_outline_target_wording(tone_profile if isinstance(tone_profile, Mapping) else None)
    reference_article_section = _render_reference_article_section(payload)
    reference_article_instructions = _build_reference_article_instructions(stage="outline")
    original_expression_instructions = _build_original_expression_instructions(stage="outline")
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="内容策划编辑",
            task_brief="请基于给定选题，输出一个适合女性情感成长公众号的文章大纲。",
            domain_pack=payload.get("domain_pack"),
        )
        + original_expression_instructions
        + reference_article_instructions,
        prompt=(
            f"趋势标题：{payload['trend_title']}\n"
            f"选题标题：{payload['topic_title']}\n"
            f"切入角度：{payload['topic_angle']}\n"
            f"项目标题：{payload['project_title']}\n\n"
            f"{reference_article_section}"
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
    reference_article_section = _render_reference_article_section(payload)
    reference_article_instructions = _build_reference_article_instructions(stage="draft")
    original_expression_instructions = _build_original_expression_instructions(stage="draft")
    ai_flavor_risk_instructions = _build_localized_ai_flavor_risk_instructions()
    wechat_public_account_instructions = _build_wechat_public_account_draft_instructions()
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
    polish_protocol = _build_polish_protocol() if polish_instruction and isinstance(current_draft, Mapping) else ""
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="正文作者",
            task_brief="请把选题和大纲扩写成一篇可直接进入编辑流程的中文初稿。要求有清晰标题、自然分段、具体场景和收束段。",
            domain_pack=payload.get("domain_pack"),
        )
        + original_expression_instructions
        + ai_flavor_risk_instructions
        + wechat_public_account_instructions
        + polish_protocol
        + reference_article_instructions,
        prompt=(
            f"趋势标题：{payload['trend_title']}\n"
            f"选题标题：{payload['topic_title']}\n"
            f"切入角度：{payload['topic_angle']}\n"
            f"项目标题：{payload['project_title']}\n"
            f"{reference_article_section}"
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
        )
        + "封面图提示词必须服务于 21:9 横版公众号头图。"
        + "禁止输出竖版、9:16、手机海报、竖构图或会导致上下裁切的画幅描述。",
        prompt=(
            f"趋势标题：{payload['trend_title']}\n"
            f"选题标题：{payload['topic_title']}\n"
            f"切入角度：{payload['topic_angle']}\n"
            f"项目标题：{payload['project_title']}\n"
            f"{style_section}"
            f"正文标题：{draft['title']}\n"
            f"正文内容：\n{draft['body_markdown']}\n"
            f"{review_section}\n"
            "封面图提示词要求：\n"
            "1. 明确写成 21:9 横版公众号头图或横向宽画幅构图\n"
            "2. 主体位于画面中部安全区，避免关键元素贴近上下边缘\n"
            "3. 禁止出现竖版、9:16、手机海报、竖构图等冲突词\n"
            "4. 用场景、人物状态、光线和留白描述画面，不要把长文案直接写进图里\n"
            "返回：\n"
            "1. 3 个标题备选 title_options\n"
            "2. 1 条封面图提示词 cover_prompt\n"
            "3. 1 条封面文案 cover_copy\n"
            "4. 1 条社媒导语 social_teaser"
        ),
    )


def build_tracked_article_metadata_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    summary = _as_clean_text(payload.get("summary"))
    body_markdown = _as_clean_text(payload.get("body_markdown"))
    structure_notes = _as_clean_text(payload.get("structure_notes"))
    author = _as_clean_text(payload.get("author"))
    tags_value = payload.get("tags")
    tags: list[str] = []
    if isinstance(tags_value, list):
        tags = [_as_clean_text(tag) for tag in tags_value if _as_clean_text(tag)]

    return PromptTemplate(
        instructions=build_stage_instructions(
            role="内容分析编辑",
            task_brief="请基于参考文章现有信息，补全适合来源池审核的摘要、结构备注和标签。",
            domain_pack=payload.get("domain_pack"),
        )
        + "这是来源池字段补全，不是正文改写。"
        + "不要照搬原标题、摘要或正文原句。"
        + "摘要要像人工写的来源备注，1 到 2 句话，写清核心冲突、观察角度或主要判断。"
        + "结构备注要说明开头如何切入、中段如何推进、结尾如何收束，保持简洁具体。"
        + "标签输出 3 到 6 个短标签，优先主题、情绪线、关系场景和写法特征。"
        + "如果作者名已经明确，就按文中已有作者输出；如果无法判断作者，author 留空字符串。"
        + "禁止编造链接、平台、数据或原文没有出现的具体事实。",
        prompt=(
            f"来源类型：{_as_clean_text(payload.get('source_kind')) or 'manual'}\n"
            f"来源账号：{_as_clean_text(payload.get('source_name')) or '手动录入'}\n"
            f"文章标题：{_as_clean_text(payload.get('article_title'))}\n"
            f"文章链接：{_as_clean_text(payload.get('article_url'))}\n"
            f"当前作者：{author or '空'}\n"
            f"当前摘要：{summary or '空'}\n"
            f"当前结构备注：{structure_notes or '空'}\n"
            f"当前标签：{' / '.join(tags) or '空'}\n"
            f"正文来源：{_as_clean_text(payload.get('body_source')) or 'missing'}\n"
            f"正文内容：\n{body_markdown or '空'}\n\n"
            "返回：\n"
            "1. 作者 author\n"
            "2. 摘要 summary\n"
            "3. 结构备注 structure_notes\n"
            "4. 标签 tags"
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
