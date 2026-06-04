from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from app.services.dbskill_bridge import get_dbskill_rule_lines, merge_unique_lines
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


_INTERNAL_PRESSURE_GUARD_KEYWORDS = (
    "心事",
    "杂念",
    "释怀",
    "执念",
    "内耗",
    "烦恼",
    "平常心",
    "情绪",
    "情绪消耗",
    "生活节奏",
    "生活排序",
    "健康",
    "身体",
    "体检",
    "疲惫",
    "耗尽",
    "报警",
    "熬夜",
    "错过",
    "遗憾",
    "当下",
    "自我照料",
    "自我整理",
    "不纠缠",
)
_RELATIONSHIP_PRESSURE_GUARD_KEYWORDS = (
    "伴侣",
    "亲密关系",
    "关系修复",
    "分手",
    "冷战",
    "婚姻",
    "恋爱",
    "夫妻",
    "前任",
    "吵架",
    "赌气",
    "和好",
    "复合",
)


def _infer_tracked_article_pressure_guard(payload: Mapping[str, object]) -> str:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return ""

    fields = [
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
    ]
    tag_values = [payload.get("tags"), payload.get("reference_article_tags")]
    corpus_parts = [_as_clean_text(value) for value in fields if _as_clean_text(value)]
    for tag_value in tag_values:
        if isinstance(tag_value, list):
            corpus_parts.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))

    corpus = " ".join(corpus_parts)
    if not corpus:
        return ""

    internal_hits = sum(1 for keyword in _INTERNAL_PRESSURE_GUARD_KEYWORDS if keyword in corpus)
    relationship_hits = sum(1 for keyword in _RELATIONSHIP_PRESSURE_GUARD_KEYWORDS if keyword in corpus)
    if internal_hits >= 2 and relationship_hits == 0:
        return "internal_pressure"
    return ""


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
        "outline_body 只写段落职责和推进动作，尽量控制在 220 字以内。\n"
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


def _render_reference_article_section(payload: Mapping[str, object], *, stage: str) -> str:
    source_type = _as_clean_text(payload.get("source_type"))
    if source_type != "tracked_article":
        return ""
    if bool(payload.get("reference_article_hidden")):
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

    if stage == "topic":
        return (
            "参考文章信息：\n"
            f"参考文章标题：{title or '无'}\n"
            f"参考文章作者：{author or '未知'}\n"
            f"参考文章来源账号：{source_name or '手动录入'}\n"
            f"参考文章摘要：{summary or '无'}\n"
            f"参考文章结构备注：{structure_notes or '无'}\n"
            f"参考文章标签：{' / '.join(tags) or '无'}\n"
        )

    return (
        "参考文章来源线索（仅用于确认赛道与冲突，不得继续沿用原文骨架）：\n"
        f"来源账号：{source_name or '手动录入'}\n"
        f"作者：{author or '未知'}\n"
        f"主题标签：{' / '.join(tags) or '无'}\n"
        "原标题、原摘要措辞和结构备注已经在上游选题阶段消化完毕，这一阶段不要再沿着原文标题骨架、开头入口或段落顺序继续展开。\n"
    )


def _has_strategy_package(payload: Mapping[str, object]) -> bool:
    problem_brief = payload.get("problem_brief")
    strategy_card = payload.get("strategy_card")
    return isinstance(problem_brief, Mapping) and isinstance(strategy_card, Mapping)


def _render_post_strategy_reference_boundary(payload: Mapping[str, object], *, stage: str) -> str:
    if stage not in {"outline", "draft"}:
        return ""
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return ""
    if not (_has_strategy_package(payload) or bool(payload.get("reference_article_hidden"))):
        return ""
    return (
        "参考文章已在问题说明书和策略卡阶段完成消化。"
        "从这里开始，不再提供任何来源账号、标题、摘要、标签或结构线索。"
        "你只能依据当前选题、大纲任务和策略结论继续推进。"
    )


def _render_topic_angle_context(payload: Mapping[str, object], *, stage: str) -> str:
    topic_angle = _as_clean_text(payload.get("topic_angle")) or "未显式提供"
    source_type = _as_clean_text(payload.get("source_type")) or "trend"
    if stage in {"outline", "draft"} and source_type == "tracked_article" and _has_strategy_package(payload):
        return "切入角度：已在下方策略包中消化，执行时不要回收原始长说明。\n"
    return f"切入角度：{topic_angle}\n"


def _build_reference_article_instructions(*, stage: str) -> str:
    if stage == "outline":
        return (
            "参考文章已经在选题阶段被消化成当前选题和角度。"
            "这一阶段不要再回看原文标题、摘要措辞或结构备注来组织大纲。"
            "只允许借用赛道冲突，不允许借用原标题骨架、开头入口、段落顺序、小节职责或结尾论断。"
            "大纲必须同时拉开至少四处距离：标题骨架、开头对象、中段推进顺序、结尾收束方式。"
            "如果你发现自己仍在沿着原文先讲什么、后讲什么的顺序推进，立刻换一条新的观察路径。"
        )
    if stage == "draft":
        return (
            "参考文章已经在选题和大纲阶段被消化，这一阶段默认你看不到原文，只围绕当前选题、大纲和风格约束写新稿。"
            "不要再按原文标题、摘要措辞、结构备注或段落顺序组织正文。"
            "不要沿用参考文章的句子，不要做逐段近义改写。"
            "起笔对象、主段顺序、案例排列和收束动作都必须重新组织；只要还有一项在顺着原文走，就先重排再写。"
            "如果无法同时改掉标题骨架、开头入口、中段顺序和结尾论断，宁可删掉熟悉段落，也不要继续贴着原文改写。"
        )
    return ""


def _build_tracked_article_pressure_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    guard = _infer_tracked_article_pressure_guard(payload)
    if guard != "internal_pressure":
        return ""

    if stage == "topic":
        return (
            "如果参考文章重心是自我消耗、心绪整理、生活排序失衡、健康透支或身体提醒，"
            "不要把选题收窄成亲密关系摊牌、情侣冷战、深夜等回复或“怎么把话说清楚”的沟通修复主线。"
            "标题和切入角度优先围绕身体提醒、生活次序、工作/家人/自我照料的接口重建，不要让对话对象取代原文真正的压力来源。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是自我消耗、心绪整理或生活排序失衡，大纲不要自动改写成亲密关系冲突处理流程。"
            "即便出现他人，也只把他当成压力接口之一，不要让“深夜等回复 / 当晚说清楚 / 第二天再沟通”变成主线。"
            "优先把压力点落在身体提醒、生活排序、工作节奏、家人回应或自我照料被推迟的地方。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是自我消耗、心绪整理或生活排序失衡，正文不要自动收窄成亲密关系摊牌、深夜删消息、等回复或关系修复主线。"
            "即便出现他人，也只把他当成压力接口之一，不要把伴侣/对话对象写成唯一主场景。"
            "后半篇不要长篇回顾关系前史，不要写成“深夜卡住 -> 回想过去 -> 第二天沟通 -> 关系缓和”的完整修复弧线。"
            "优先把代价写在身体提醒、生活排序、家人回应、工作节奏或自我照料被推迟的地方。"
        )
    return ""


def _build_original_expression_instructions(*, stage: str, compact: bool = False) -> str:
    if stage == "outline":
        lines = [
            "大纲不要直接罗列三四条抽象道理，先设计一个具体、可感知的开篇瞬间或动作入口。",
            "开篇钩子不要写成“很多关系不是……”或“真正让人难受的不是……”这类抽象判断起手。",
            "大纲标题和段落小标题不要使用“不是A，而是B”或“不是A，只是B”这类对称判断句。",
            "如果选题标题或参考文章标题已经含有这类句式，大纲必须先换成具体场景、动作或物件入口。",
            "中段要写清视角如何从场景推进到情绪、再推进到判断或动作。",
            "中段至少安排两处“触发 -> 当场反应 -> 后续影响”的推进链，不要只列情绪结论或抽象道理。",
            "每个核心段都要有稳定抓手：人物动作、物件、界面、空间位置、时间节点或身体信号，避免整节只剩概念。",
            "至少保留一节专门解释事情是怎样一步步变成现在这样的，让机制从细节里慢慢长出来。",
            "不要把每一节都规划成“场景一下 + 解释一下 + 单独敲一句总结”的同一节拍。",
            "至少保留一节只停在观察、动作或关系变化上，不要立刻补完整结论。",
            "结尾要回到人物处境或心绪余波，不要停在口号式总结。",
        ]
        lines = merge_unique_lines(lines, get_dbskill_rule_lines("outline", "extra_instructions"))
        return "".join(lines)
    if stage == "draft":
        if compact:
            lines = [
                "正文先落一个具体动作、界面、物件或身体反应，再慢慢带出判断，不要开头先解释题眼。",
                "把抽象情绪压回动作停顿、空间距离、环境声和身体反应，不要写成谁都能套用的万能感悟。",
                "至少写出两条可见推进：什么先触发，人当场怎么反应，后面留下什么代价、变化或延迟影响。",
                "不要沿用“不是A，而是B”的对称判断骨架，也不要把正文排成“观点句 + 解释句”的标准答案模板。",
                "不要按大纲顺手扩成并列分论点，允许段落先停在观察、动作残留、对话碎片或关系变化上。",
                "独立短段只保留真实动作残留、没接上的一句话或身体反应，不要拿来单独敲道理。",
                "不要把每个判断都解释透，至少留一处停顿、改口或没完全说满的地方。",
                "别把能证明人还在现场的毛边全修掉，保留少量更硬一点、更口语一点的真实阻力。",
                "默认优先保留单场景或窄场景，不要为了显得完整主动补成双线并跑或多案例铺开。",
                "不要把正文自动补齐成完整示范文，尤其不要主动补一个漂亮收束、万能总结或编辑态结尾。",
                "结尾回到人物处境、关系余波或一个很小的现实动作，不要口号式收束。",
            ]
            lines = merge_unique_lines(
                lines,
                get_dbskill_rule_lines("draft", "extra_instructions")[:3],
            )
            return "".join(lines)
        lines = [
            "原创不是把现成观点换一批近义词，而是重新建立观察路径、场景重心和句子节奏。",
            "优先从一个具体、可感知的瞬间起笔，让动作、环境、声音或身体感受先出现，再带出判断。",
            "不要先复述题眼或给观点下定义，先把读者带进一个可见、可听、可感的当下。",
            "把抽象情绪落到动作停顿、物件光线、空间距离或身体反应上，让情绪有抓手。",
            "正文至少完成两条看得见的因果链：什么先触发，人当场怎么反应，后面留下什么代价、变化或延迟影响。",
            "每 2 到 3 段至少复用一个稳定抓手：同一个物件、界面、空间位置、时间节点或身体信号，让文本像沿着同一现实表面推进。",
            "少用“生活、感情、成长、幸福、重要的事”这类对所有人都成立的大词，优先写这篇稿子内部能反复指认的小动作、小术语和局部流程。",
            "允许出现少量偏说明性的句子，把事情为什么会变成这样讲清楚，但说明必须贴着前文细节走，不要拔高成大道理。",
            "如果一个段落只剩观点，就把它改写成过程：谁先触发、当时怎么反应、后来留下什么后果。",
            "正文不要写成标准答案式观点罗列，要让场景、情绪和判断自然推进。",
            "避免每段都写成“观点句 + 解释句”的模板结构，至少让一处段落先发生事情，再慢慢显出判断。",
            "少用“不是A，是B”这类过于整齐的判断句，尤其不要连续拿它做标题、开头或结尾。",
            "标题禁止使用“不是A，而是B”或“不是A，只是B”这类对称判断句。",
            "如果选题标题或参考文章标题已经含有这类句式，正文标题必须改成具体处境入口，不要继续复用“不是、而是、只是”的判断骨架。",
            "正文主干也不要反复用“不是不爱，只是不知道”“不是不在意，只是不会表达”这类双重否定模板。",
            "全篇最多保留 1 处“不是……”判断，并且不要放在开头第一屏或结尾段；需要转折时改写成“更常见的情况是”“真正卡住的地方在”“她当时先感到的是”等自然表达。",
            "减少“第一步、第二步、第三步”式教程骨架，优先写成自然展开的叙事或观察推进。",
            "不要为了显得完整而过度解释每一个判断，允许留白，允许有些意思停在动作或场景里。",
            "避免反复用“一点、一下、一些、一个、一种”去切分感受和动作，同一种量词节奏不要整篇反复出现。",
            "“一点、一下、一些、一个、一种、一件、一句、一段”这类一字量词全篇尽量控制在 5 处以内；能写具体动作、时间、物件和空间距离时，不要用泛化量词。",
            "不要每隔一两段就单独插一个很短的判断段或敲钟段，全篇这类独立短判断段最多保留 1 处。",
            "如果某个短段只是为了提醒、点题、转折或抒情，优先并回前后场景段，让判断从细节里慢慢浮出来。",
            "允许保留 1 到 3 个很短的独立段，但前提是它们必须落在具体动作、物件、身体反应或一句没接上的话上，不是拿来单独敲道理。",
            "如果要单独留一个短段，它应该像阻力线或动作残留，而不是“很多人就是这样”“真正难的是……”这类万能判断。",
            "不要把一句消息、对话、短信或引用写成整篇反复出现的展示段；如果全文只保留一处且确实能增强现场感，可以留。",
            "不要把“解释也来得很快：……”这类独立解释短段写成固定排版习惯；如果全文只保留一处且确实承担心理跳转，可以留。",
            "不要反复使用“短句点一下，下一段再长解释”的固定节拍；连续出现两次以上就必须打散。",
            "不要把正文切成一串一两句的宣布式小段，除非是真实小标题，否则这类独立锚句全篇最多保留 1 处。",
            "像“这里面有条很清楚的线”“更麻烦的是”“有些代价是延迟出现的”这类负责宣布观点的过渡句，优先删掉，让后面的事实直接顶上来。",
            "避免连续三段以上都从同一个主语起手，尤其不要一段接一段都写“她……她……她……”。",
            "不要把“先是……后来……再后来……”写成整理得过于整齐的梳理链，宁可保留一点断裂感和回绕。",
            "至少留一段只停在观察、动作、关系变化或身体反应里，不要立刻把意义解释完整。",
            "不要把起因、机制、代价、转机一次性讲透，允许局部只写到人当时怎么卡住。",
            "不要把全文磨成同一种克制、平稳、过度完整的成熟散文腔；至少保留两处更硬一点、更口语一点或更突然的句子。",
            "避免连续多段都围绕同一个主语匀速起手，尤其不要一段接一段都用“她……她……她……”或“你……你……你……”往前推。",
            "至少安排一段只呈现对话、动作残留、物件或环境声，不要立刻补一句“这说明了什么”。",
            "至少安排一处说到一半又收回去、改口、停住或自我修正的表达，不要让每段都像一次性精修好的标准成稿。",
            "别把能证明人还在现场的毛边全修掉；比起段段圆满，少量具体停顿和动作残留更接近真实写作。",
            "不要让所有细节都过于听话地服务中心判断，允许一两个普通但真实的生活细节先落着，后面再慢慢显出意义。",
            "如果全文只有一条过于顺滑的情绪通道，就主动打断一次：换成短信、清单、动作残留或一句短对话，让段落职责不要完全对称。",
            "不要把正文自动补齐成完整示范文，尤其不要主动补一个漂亮收束、万能总结或编辑态结尾。",
            "结尾不要写成自查问卷、连续三连问或“最近一次……是谁 / 是什么 / 在什么时候”这类提问清单。",
            "如果需要留给读者动作，只保留一个很小的真实动作或余波，不要连续抛问题逼人对号入座。",
            "输出前静默做一次过度成稿自检：挑出最像 AI 成稿的 3 个位置，但不要展示；每个位置至少执行一种操作：删总括句、把判断改成过程、保留没说透的停顿、打断匀速节拍、把漂亮收尾改成普通动作。",
            "如果改完后仍然像一篇完整示范文，就继续删掉一个最会解释大道理的段落，不要补新的总括段。",
            "输出前必须做一次静默自检：统计“不是……”判断、解释连接词和一字量词；如果超过上述限制，先重写超标段落，再返回最终正文。",
            "不要在最终正文里写出自检过程、风险分或修改说明，只返回可发布的标题和正文。",
            "多用具体细节承载观点，少写空泛抒情、万能道理和模板化金句。",
            "句子节奏要有长短变化和呼吸感，不要整篇都像统一模板口播稿。",
            "结尾回到人物处境或心绪余波，克制收束，不要用励志口号硬收。",
        ]
        lines = merge_unique_lines(lines, get_dbskill_rule_lines("draft", "extra_instructions"))
        protocol = _build_dbskill_problem_execution_protocol(compact=False)
        if protocol:
            lines.append(protocol)
        return "".join(lines)
    return ""


def _build_humanizer_zh_review_instructions(*, stage: str, compact: bool = False) -> str:
    if stage == "outline":
        if compact:
            return (
                "大纲不要先写宏大意义、时代症候或更大趋势，先把眼前处境钉住。"
                "能合成两段职责就不要硬拆三段并列，也不要安排模糊归因段。"
                "结尾别预设成适合截图传播的金句，收在动作、余波或没说满的感受上。"
            )
        return "".join(
            [
                "不要先写“这件事说明了什么时代症候”或“折射了更大的趋势”，先把具体处境、动作断点和现实阻力钉住。",
                "大纲里能合成两段职责的，不要机械拆成三段并列分论点；两段够用就用两段，不要为了完整感硬凑第三项。",
                "不要安排“有人这样说”“很多人以为”“专家认为”这种模糊归因段，优先让事实、场景和人物动作自己承担说明压力。",
                "结尾不要设计成一句适合截图传播的金句，优先收在一个普通动作、关系余波或还没完全说满的感受上。",
            ]
        )
    if stage == "draft":
        if compact:
            return (
                "删掉“说到底”“归根结底”“某种程度上”“很多时候”这类填充短语，让动作和事实直接顶上来。"
                "能写两项就不要硬凑三项并列；不要用模糊归因和宏大意义替代具体处境。"
                "如果一句话太像现成金句，就拆回动作、场景或后果，不要单独抬成结论段。"
            )
        return "".join(
            [
                "删掉“说到底”“归根结底”“某种程度上”“很多时候”这类填充短语，让动作、事实和后果直接出现，不要先垫一个万能过渡再说正题。",
                "能写两项就不要硬凑三项并列；如果一句话里只是为了显得完整才排出三个近义判断，优先删掉最像装饰的那一项。",
                "不要用“有人说”“有人认为”“专家指出”“很多人都会”这类模糊归因替代具体处境，能落回人物动作、对话、时间节点和现实反馈时，就不要拿抽象权威兜底。",
                "不要把普通处境硬拔成时代缩影、重要转折或更宏大的意义，先把这一个人、这一个动作、这一次延迟写清楚。",
                "如果一句话读起来像现成金句或适合被单独截图传播，优先把它拆回动作、场景、反应或后果，不要单独抬成结论段。",
            ]
        )
    return ""


def _build_localized_ai_flavor_risk_instructions(*, compact: bool = False) -> str:
    if compact:
        diagnosis_signals = get_dbskill_rule_lines("diagnosis", "signals")
        compact_signals = "".join(diagnosis_signals[:2]) if diagnosis_signals else ""
        return (
            "静默排查中文公众号高风险 AI 味：不要匀速排比、段段收束、万能抒情、教程分步、连续短判断或过度解释。"
            "如果某处太像一次性写完的标准成稿，优先删总括、降结论、改成过程或普通动作。"
            + compact_signals
        )
    base = (
        "按 6 类中文公众号 AI 味风险检查表达："
        "套话风险，避免万能成长句、万能抒情和空泛金句；"
        "结构模板风险，避免整齐反转、教程分步、总括式泛感慨过渡句、单句敲钟段和标准答案式段落；"
        "句式节奏风险，避免同一种量词、连接词和判断句反复起手；"
        "段落节拍风险，避免“短句点一下 + 下一段长解释”反复交替，避免每段都解释到位；"
        "机制空心风险，不要只给情绪结论，要交代触发、反应和后续影响之间怎么连起来；"
        "抽象空话风险，把感受落到动作、物件、空间、声音和身体反应上；"
        "过度解释风险，不要把每个判断都解释透，允许场景和停顿承载意思；"
        "结尾口号风险，结尾回到人物处境或心绪余波，不要喊话式收束。"
    )
    diagnosis_signals = get_dbskill_rule_lines("diagnosis", "signals")
    if not diagnosis_signals:
        return base
    return base + "".join(diagnosis_signals)


def _build_dbskill_problem_execution_protocol(*, compact: bool = False) -> str:
    brief_steps = get_dbskill_rule_lines("strategy", "problem_brief_steps")
    divergence_checks = get_dbskill_rule_lines("strategy", "divergence_checks")
    execution_protocol = get_dbskill_rule_lines("draft", "execution_protocol")
    self_checklist = get_dbskill_rule_lines("draft", "self_checklist")

    if compact:
        lines = merge_unique_lines(
            brief_steps[:2],
            divergence_checks[:2],
            execution_protocol[:3],
            self_checklist[:3],
        )
        if not lines:
            return ""
        return "执行协议：" + "；".join(lines) + "。"

    parts: list[str] = []
    if brief_steps:
        parts.append("写前约束：" + "；".join(brief_steps) + "。")
    if divergence_checks:
        parts.append("拉开距离检查：" + "；".join(divergence_checks) + "。")
    if execution_protocol:
        parts.append("写作执行：" + "；".join(execution_protocol) + "。")
    if self_checklist:
        parts.append("返回前自检：" + "；".join(self_checklist) + "。")
    return "".join(parts)


def _build_wechat_public_account_draft_instructions(*, compact: bool = False) -> str:
    if compact:
        return (
            "正文要像真实公众号作者现场写出来的稿子，不要像一次性生成的标准范文。"
            "少写万能道理，多写日常接口、局部机制和现实阻力，不要把每段都补成完整示范。"
            "不要连续宣布观点，不要系统性补氛围场景，也不要机械扩句增肥。"
            "如果正文不是从场景起笔，就沿着判断、人物或案例入口继续推进，不必强行每段先铺画面。"
            "段落可以有长有短，但不要切成一排匀称小段。"
            "不要把稿子收成已经准备进编辑排版的完整示范文，宁可停在还没完全处理完的动作、接口或关系余波上。"
            "不要主动补齐漂亮标题、对称段落职责和过度完整的最后一段。"
            "人物关系、项目标题和核心事实不能改。"
        )
    return (
        "正文要更贴近真实公众号作者写作，而不是模型一次性生成的标准成品。"
        "允许局部段落更松一点、更口语一点，但整体仍然要干净、可读、适合公众号排版。"
        "多写人是怎么感到累、怎么停一下、怎么把情绪往回压，少写完整方法论和对所有人的通用结论。"
        "好的原创稿往往不只是情绪更自然，而是有稳定的现实抓手和局部机制说明。"
        "把“为什么会这样”拆成触发、反应和后续影响，少写悬空的人生判断。"
        "不要把每个判断都解释透，留一点空白给读者自己接上。"
        "不要为了显得成熟顺滑，给每一段都补“很多时候”“说到底”“人总是这样”这类总括过渡句。"
        "不要反复插入只负责点题或敲一下的独立短段，也不要固定一段短句后一段长解释地轮着写。"
        "不要频繁单独起一段宣布下一个观点，像“更麻烦的是”“有些代价是延迟出现的”这种段落，优先并回前后过程里。"
        "不要连续几段都从同一个主语起手，让动作、时间点、物件或环境声替你打开句子。"
        "允许有一两段只停在动作、关系变化或身体反应上，不必每段都补齐判断。"
        "不要系统性在开头第一屏、各小节首段或段落转场前补新的氛围场景；如果原稿不是从场景起笔，就继续沿用原稿已有的判断、人物或案例入口。"
        "避免机械扩写、刻意增肥和整篇统一修辞，不要为了像人写而堆砌“了、的、地、一下、一点、一阵”这类填充。"
        "避免系统性把“和”改成“以及”、“并”改成“并且”、“为了”改成“为了能够”这类生硬替换。"
        "不要把句子润成网文腔、鸡汤腔或文学仿写腔，仍然保持当代中文公众号的自然表达。"
        "如果原稿主体是议论、感悟或并列展开，不要统一扩写成每段都先铺场景再抒情的散文稿。"
        "不要把正文写成段落数刚好、段段职责单一、每段都像只负责一个结论的完整成稿。"
        "如果全文已经被切成很多匀称小段，优先合并成更长的自然段，让现象、动作和解释在同一段里共存。"
        "不要把原稿整体磨成统一的成熟公众号成稿腔，允许局部保留更直一点、更硬一点的表达。"
        "专有名词、项目标题、人物关系和核心事实不能改，不能为了润色改掉原本的因果和立场。"
        "如果需要增强原创感，优先更换叙述重心、段落重音和细节抓手，而不是把原句拖长。"
    )


def _build_polish_protocol(*, allow_structure_recomposition: bool = False, compact: bool = False) -> str:
    if compact:
        recomposition_notes = (
            "必要时允许合并、拆分或调换段落，但只能重组现有事实和关系，不能虚构新人物、新职业、新病症或新剧情。"
            if allow_structure_recomposition
            else ""
        )
        return (
            "这不是局部润色，而是去模板化精修。"
            "优先拆掉最像标准成稿的段落顺序、单句敲钟段和“短句点一下 + 下一段长解释”的固定节拍。"
            f"{recomposition_notes}"
            "开头和结尾必须重写成更贴近现有事实与动作的版本。"
            "纯判断段优先改成过程段：补出触发动作、当场反应和后续影响。"
            "如果一段只是宣布观点、抒情或总结，优先并回前后过程，不要再单独站出来。"
            "如果当前草稿已经是单场景或窄场景低风险基线，不要为了显得更完整主动扩成双线并跑、多案例铺开或更成熟的示范文。"
            "优先做窄修：只调整局部判断句、过顺的连接、过满的结尾和少数模板化句子。"
            "不追求段段完整，允许保留停顿、改口和局部没说满。"
            "宁可停在还没完全处理完的小动作、现实阻力或关系余波上，也不要主动补一个漂亮收束段。"
            "不要只做同义词替换或语序微调，输出要像基于原稿重新写出的一版新正文。"
        )
    recomposition_notes = (
        "如果当前稿子的骨架本身还带着参考文顺序、标准成稿壳子或过于整齐的段落职责，允许直接合并、拆分、重排段落。"
        "可以改标题，可以改小节标题，也可以调换中段推进顺序。"
        "这类重组只服务于原创距离和表达自然度，不是让你另起一个新主题。"
        "保留核心事实、人物关系、冲突边界和现实约束，不要虚构新人物、新职业、新病症、新城市或完整新剧情。"
        if allow_structure_recomposition
        else ""
    )
    return (
        "这不是局部润色任务，而是原创增强精修任务。"
        "按 6 类中文公众号 AI 味风险逐项检查原稿。"
        "先删掉万能抒情、整齐反转、教程分步和口号式结尾。"
        f"{recomposition_notes}"
        "不要把原稿修成段落数匀称、段段职责分明、每段只承担一个结论的完整成稿。"
        "如果正文已经被切成太多匀称小段，主动合并成更长的自然段，让现象、动作、局部解释和后续影响在同一段里共存。"
        "必须重写开头段和结尾段，优先调整段落连接、场景组织和观点推进顺序。"
        "开头第一屏和每个保留小节的首段，优先沿用原稿已经出现的人物、案例、问题或判断进入，不要另起一段新的泛感慨或氛围描写。"
        "必须改写场景入口段、中段关键推进段和收束段。"
        "先判断原稿哪些段落最像模板话，再优先拆掉这些段落的原顺序重写。"
        "至少把一个抽象判断段改写成更可感知的表达，把一个平铺说理段改写成更自然的情绪推进段。"
        "把那些单独站出来宣布观点的小段并回前后过程段，尤其是“更麻烦的是”“有些代价是延迟出现的”“关系里的缺席”这类段落。"
        "如果连续几段都从“她”或“你”起手，至少改掉其中一半，换成动作、物件、时间节点或环境先起句。"
        "如果出现“先是……后来……再后来……”这种整理过度的梳理链，把它拆开，改成更自然的时间推进。"
        "优先把纯判断段改成机制段：补出触发动作、当场反应和后续影响，让读者看到事情是怎么一步步变成现在这样的。"
        "每 2 到 3 段至少保住一个稳定抓手：同一个物件、界面、空间位置、时间节点或身体信号，不要把全文写成漂浮感慨。"
        "允许少量说明性句子把机制讲明白，但说明必须贴着原稿已有细节，不要升空成大道理。"
        "如果原稿里有很多独立短判断段、敲钟段或一句话小结，至少合并掉一半，不要保留一串单句提醒。"
        "独立短段尽量压到 2 处以内，确实要留的短段只留动作残留、身体反应或没接上的一句话。"
        "不要把一句消息、对话、短信或引用写成整篇反复出现的展示段；如果全文只保留一处且确实能增强现场感，可以留。"
        "不要把“解释也来得很快：……”这类独立解释短段写成固定排版习惯；如果全文只保留一处且确实承担心理跳转，可以留。"
        "不要按“短句点一下 + 下一段长解释”的节拍反复排版；至少打散其中两处，让判断埋进具体段落里。"
        "允许某些段落只停在动作、停顿、关系变化或身体反应，不必每段都补一句总结。"
        "如果“一点、一下、一个、一种、一件”这类量词起手过密，主动改掉一半以上，不要整篇都靠同一节奏往下写。"
        "如果原稿一上来就在讲道理，优先前置原稿里本来已有的例子、动作或处境；如果原稿没有这些材料，只压缩说理密度，不要额外虚构新场景。"
        "如果原稿某一节本来直接进入人物案例、直接判断或一组并列例子，就保留这种直入方式，不要先补深夜、房间、工位、窗边这类陌生环境起手。"
        "必要时可以删除过熟的总结句和万能结论，不必把原稿每个判断都保留下来。"
        "精修优先使用原稿已经出现的事实、人物、关系、例子和论证顺序，不要为了显得自然而额外虚构新人物、新职业、新病症、新城市、新道具或完整新剧情。"
        "如果原稿本质上是一篇议论文或感悟文，允许增强画面感，但不要整体改写成小说化叙事。"
        "不要把每个小节都扩成篇幅整齐、节奏相似的场景散文段；议论段可以继续是议论段，只把模板句拆开。"
        "保留原稿的核心论点结构，不要把原稿中的主线改写成新的主题。"
        "原稿里已经出现的人物、亲属称谓、关系对象和案例应优先保留并重写表达，不要随意换成新的陌生案例。"
        "不要为了把段落接顺，额外补“很多时候”“说到底”“人总是这样”“我们总以为”这类泛感慨过渡句。"
        "如果原稿本来更朴素、更直给，就保留这股劲，不要统一磨成成熟公众号标准成稿。"
        "输出前再做一次过度成稿排查：找出最像模板成稿的 3 个位置，但不要展示；分别执行删总括、改过程、留停顿、降结论、打断匀速节拍中的至少一种。"
        "如果删掉一个总结段后全文依然成立，就删掉它，不要补一个新的总结段。"
        "不要只做同义词替换、语序微调或局部句子抛光，输出结果要像基于原稿重新写出的一版新正文。"
        "优先更换观察角度、细节选择、段落重心和句子节奏，而不是只修饰原句表面。"
        "输出前自查：场景具体度、句式重复度、模板风险、情绪自然度、改写幅度。"
    )


def _build_polish_mode_instructions(*, compact: bool = False) -> str:
    if compact:
        return (
            "当前任务是基于现有正文精修，不是按大纲重写一篇新稿。"
            "以现有正文为主，大纲只负责防止跑题。"
            "尽量保住原稿的文体类型、核心论点顺序、人物关系和主要案例。"
            "如果原稿本来就直给、朴素或偏议论，不要强行改成小说化场景散文。"
            "原稿已有的小节职责、案例入口和判断顺序，能保的尽量保，只拆模板感最重的部分。"
        )
    return (
        "当前任务是基于现有正文精修，不是根据大纲重新生成一篇新稿。"
        "现有正文是本次改写的唯一正文输入，大纲如果出现，也只用于防止跑题，不是要求你按大纲重写结构。"
        "如果原稿标题本身成立，优先保留原标题，只在明显模板感过重时做小幅调整，不要改成宽泛的人生感慨标题。"
        "精修后要保留原稿的文体类型、核心论点顺序、人物关系和主要案例。"
        "如果原稿是议论/感悟文，就继续写成议论/感悟文；如果原稿是经验文或案例文，就继续保留原有表达重心。"
        "开头第一屏和各小节首段，要优先保住原稿原本的切入对象，不要为了像人写就统一换成新的深夜、办公室、窗边、路上这类环境起笔。"
        "如果原稿已经有短小节标题或明显分段，精修后必须保留这些分段职责，不要另起一套新的总分总结构。"
        "如果原稿中的短小节标题本身成立，请在精修结果中原样保留这些标题，不要改写成新的标题组。"
        "如果原稿主体是并列展开的三到四个主题段，精修后仍然保持并列展开，不要压成单线抒情散文。"
        "如果原稿某节原本一上来就是人物案例、直接判断或一组并列例子，精修后也优先从那里进入，不要先垫一层总括感慨。"
        "优先沿用原稿已经存在的小标题、段落功能和论证顺序，不要额外新开一条更长的叙事线。"
        "不要因为想显得更完整，就把原稿统一改成总括判断句加解释句的成熟公众号腔。"
        "如果原稿里有更直、更硬、更不圆滑的句子重心，精修后也要尽量保住，不要全部磨平。"
        "如果现有正文和大纲存在轻微不一致，以现有正文为准，只要主题没有跑偏即可。"
    )


def _build_polish_recomposition_mode_instructions(*, compact: bool = False) -> str:
    if compact:
        return (
            "这次允许更大幅度地调换中段顺序、合并段落和改小节职责。"
            "但只重组现有主题、事实和关系，不换题、不换人、不换因果。"
            "如果策略结论和原稿骨架冲突，优先保主题边界和事实边界，再决定怎么重排。"
        )
    return (
        "当前任务仍然是基于现有正文精修，但这次允许更大幅度的结构重组。"
        "如果原稿骨架本身太像参考文延长版、太像标准成稿模板，允许直接合并段落、拆分段落、改写小节标题和调换中段推进顺序。"
        "不需要保住原标题、原小节标题或原段落职责，只要主题边界、人物关系、关键事实和核心冲突不跑掉即可。"
        "如果策略包已经给出新的开头动作、中段推进和结尾动作，优先服从策略包，不必继续保守原稿原有段落顺序。"
        "重组时先保事实边界，再保文体类型，最后才考虑原稿旧骨架。"
        "独立短段尽量压到 2 处以内，确实要留的短段只保留动作残留、身体反应或没接上的一句话。"
        "不要为了重组而发明陌生事实；你可以换组织方式，但不要换题、换人、换关系、换因果。"
    )


def _split_markdown_blocks(markdown: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", markdown) if block.strip()]


def _strip_markdown_heading(block: str) -> str:
    return re.sub(r"^\s{0,3}#{1,6}\s*", "", block.strip())


def _looks_like_short_section_heading(block: str) -> bool:
    raw = _strip_markdown_heading(block).replace("\n", " ").strip()
    normalized = raw
    if not normalized:
        return False
    candidate = normalized.strip().rstrip("。！？!?；;：:")
    if not candidate:
        return False
    if len(candidate) > 24:
        return False
    if re.search(r"[，,]", candidate):
        return False
    if re.search(r"[。！？!?；;：:]", candidate):
        return False
    if re.match(r"^\d+[.)、]\s*", candidate):
        return False
    if raw.endswith(("。", "！", "？", "!", "?", "；", ";", "：", ":")):
        return candidate.startswith(("别", "不要", "先", "学会", "记得", "关于", "停止", "少", "多", "把"))
    return True


def _extract_first_sentence(block: str, *, max_length: int = 48) -> str:
    normalized = _strip_markdown_heading(block).replace("\n", " ").strip()
    if not normalized:
        return ""
    parts = re.split(r"[。！？!?；;\n]", normalized, maxsplit=1)
    sentence = parts[0].strip()
    if len(sentence) > max_length:
        return sentence[:max_length].rstrip() + "..."
    return sentence


def _truncate_text(text: str, *, max_length: int = 72) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= max_length:
        return normalized
    sentence = _extract_first_sentence(normalized, max_length=max_length)
    if sentence:
        return sentence
    return normalized[:max_length].rstrip() + "..."


def _extract_outline_anchor_lines(outline_body: str, *, max_items: int = 6, max_length: int = 42) -> list[str]:
    anchors: list[str] = []
    for raw_line in outline_body.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", raw_line).strip()
        line = re.sub(r"^\s*[-*+]\s*", "", line)
        line = re.sub(r"^\s*\d+[.)、]\s*", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        compact_line = _truncate_text(line, max_length=max_length)
        if compact_line in anchors:
            continue
        anchors.append(compact_line)
        if len(anchors) >= max_items:
            break
    return anchors


def _render_draft_outline_section(outline: Mapping[str, object], *, compact: bool = False) -> str:
    hook = _as_clean_text(outline.get("hook"))
    outline_body = _as_clean_text(outline.get("outline_body"))
    if not compact:
        return f"大纲钩子：{hook}\n大纲内容：\n{outline_body}\n"

    lines: list[str] = []
    if hook:
        lines.append(f"大纲钩子：{_truncate_text(hook, max_length=60)}")
    anchors = _extract_outline_anchor_lines(outline_body)
    if anchors:
        lines.append("大纲锚点：")
        lines.extend(f"- {anchor}" for anchor in anchors)
    elif outline_body:
        lines.append(f"大纲锚点：{_truncate_text(outline_body, max_length=180)}")
    return "\n".join(lines) + "\n"


def _render_polish_structure_anchor_section(current_draft: Mapping[str, object] | None) -> str:
    if not isinstance(current_draft, Mapping):
        return ""

    markdown = _as_clean_text(current_draft.get("body_markdown"))
    if not markdown:
        return ""

    blocks = _split_markdown_blocks(markdown)
    if blocks and blocks[0].lstrip().startswith("#"):
        blocks = blocks[1:]

    lines: list[str] = []
    draft_title = _as_clean_text(current_draft.get("title"))
    if draft_title:
        lines.append(f"原标题锚点：{draft_title}")
    pending_heading: str | None = None
    general_count = 0

    for block in blocks:
        normalized = _strip_markdown_heading(block)
        if not normalized:
            continue

        if _looks_like_short_section_heading(normalized):
            heading = normalized
            if f"保留小节：{heading}" not in lines:
                lines.append(f"必须保留小节标题：{heading}")
            pending_heading = heading
            continue

        sentence = _extract_first_sentence(normalized)
        if not sentence:
            continue

        if pending_heading:
            lines.append(f"{pending_heading}下必须继续围绕这个原稿锚点推进：{sentence}")
            pending_heading = None
            continue

        if general_count < 2:
            lines.append(f"必须保留的原稿关键句：{sentence}")
            general_count += 1

        if len(lines) >= 8:
            break

    if not lines:
        return ""

    return (
        "原稿结构锚点（精修后应尽量保留这些顺序与案例，不要求逐字复用）：\n"
        + "\n".join(lines)
        + "\n"
    )


def _render_strategy_package_section(payload: Mapping[str, object], *, compact: bool = False) -> str:
    problem_brief = payload.get("problem_brief")
    strategy_card = payload.get("strategy_card")
    benchmarks = payload.get("benchmarks")

    if not isinstance(problem_brief, Mapping) or not isinstance(strategy_card, Mapping):
        return ""

    clarified_problem = _as_clean_text(problem_brief.get("clarified_problem"))
    observed_phenomenon = _as_clean_text(problem_brief.get("observed_phenomenon"))
    writing_goal = _as_clean_text(problem_brief.get("writing_goal"))
    target_reader_situation = _as_clean_text(problem_brief.get("target_reader_situation"))
    core_conflict = _as_clean_text(problem_brief.get("core_conflict"))
    feedback_entry = _as_clean_text(problem_brief.get("feedback_entry"))
    constraints_value = problem_brief.get("constraints")
    constraints: list[str] = []
    if isinstance(constraints_value, list):
        constraints = [_as_clean_text(item) for item in constraints_value if _as_clean_text(item)]

    reader_situation = _as_clean_text(strategy_card.get("reader_situation"))
    point_of_view = _as_clean_text(strategy_card.get("point_of_view"))
    conflict_frame = _as_clean_text(strategy_card.get("conflict_frame"))
    emotional_path = _as_clean_text(strategy_card.get("emotional_path"))
    structure_mode = _as_clean_text(strategy_card.get("structure_mode"))
    opening_move = _as_clean_text(strategy_card.get("opening_move"))
    body_shift = _as_clean_text(strategy_card.get("body_shift"))
    ending_move = _as_clean_text(strategy_card.get("ending_move"))
    recomposition_recipe_value = strategy_card.get("recomposition_recipe")
    benchmark_summary = _as_clean_text(strategy_card.get("benchmark_summary"))
    expression_constraints_value = strategy_card.get("expression_constraints")
    divergence_axes_value = strategy_card.get("divergence_axes")
    execution_checklist_value = strategy_card.get("execution_checklist")
    recomposition_recipe: list[str] = []
    expression_constraints: list[str] = []
    divergence_axes: list[str] = []
    execution_checklist: list[str] = []
    if isinstance(recomposition_recipe_value, list):
        recomposition_recipe = [_as_clean_text(item) for item in recomposition_recipe_value if _as_clean_text(item)]
    if isinstance(expression_constraints_value, list):
        expression_constraints = [_as_clean_text(item) for item in expression_constraints_value if _as_clean_text(item)]
    if isinstance(divergence_axes_value, list):
        divergence_axes = [_as_clean_text(item) for item in divergence_axes_value if _as_clean_text(item)]
    if isinstance(execution_checklist_value, list):
        execution_checklist = [_as_clean_text(item) for item in execution_checklist_value if _as_clean_text(item)]

    if compact:
        lines = ["创作策略包（执行摘要）："]
        if clarified_problem:
            lines.append(f"问题澄清：{_truncate_text(clarified_problem)}")
        if observed_phenomenon:
            lines.append(f"观察焦点：{_truncate_text(observed_phenomenon)}")
        elif writing_goal:
            lines.append(f"写作目标：{_truncate_text(writing_goal)}")
        if target_reader_situation:
            lines.append(f"读者定位：{_truncate_text(target_reader_situation)}")
        if conflict_frame:
            lines.append(f"冲突框架：{_truncate_text(conflict_frame)}")
        if emotional_path:
            lines.append(f"情绪路径：{_truncate_text(emotional_path)}")
        structure_mode_label, structure_mode_execution = _describe_structure_mode(structure_mode)
        if structure_mode_label:
            lines.append(f"结构模式：{structure_mode_label}")
            lines.append(f"结构执行：{_truncate_text(structure_mode_execution)}")
        if opening_move:
            lines.append(f"开头动作：{_truncate_text(opening_move)}")
        if body_shift:
            lines.append(f"中段推进：{_truncate_text(body_shift)}")
        if ending_move:
            lines.append(f"结尾动作：{_truncate_text(ending_move)}")
        if recomposition_recipe:
            lines.append(f"替代骨架：{' / '.join(recomposition_recipe[:3])}")
        if expression_constraints:
            lines.append(f"表达约束：{' / '.join(expression_constraints[:3])}")
        if divergence_axes:
            lines.append(f"主动拉开距离：{' / '.join(divergence_axes[:3])}")
        if execution_checklist:
            lines.append(f"执行检查：{' / '.join(execution_checklist[:3])}")
        if benchmark_summary:
            lines.append(f"参考基准：{_truncate_text(benchmark_summary)}")
        compact_protocol = _build_dbskill_problem_execution_protocol(compact=True)
        if compact_protocol:
            lines.append(compact_protocol)
        lines.append("执行原则：沿着这些策略结论写，不回收参考文原句、原顺序和原结尾。")
        return "\n".join(lines) + "\n\n"

    lines = ["创作策略包（执行摘要）："]
    if clarified_problem:
        lines.append(f"问题澄清：{clarified_problem}")
    if observed_phenomenon:
        lines.append(f"观察到的现象：{observed_phenomenon}")
    if writing_goal:
        lines.append(f"写作目标：{writing_goal}")
    if target_reader_situation:
        lines.append(f"读者处境：{target_reader_situation}")
    if core_conflict:
        lines.append(f"核心冲突：{core_conflict}")
    if constraints:
        lines.append(f"硬约束：{' / '.join(constraints)}")
    if feedback_entry:
        lines.append(f"反馈入口：{feedback_entry}")
    if reader_situation:
        lines.append(f"读者定位：{reader_situation}")
    if point_of_view:
        lines.append(f"叙述视角：{point_of_view}")
    if conflict_frame:
        lines.append(f"冲突框架：{conflict_frame}")
    if emotional_path:
        lines.append(f"情绪路径：{emotional_path}")
    structure_mode_label, structure_mode_execution = _describe_structure_mode(structure_mode)
    if structure_mode_label:
        lines.append(f"结构模式：{structure_mode_label}")
        lines.append(f"结构执行：{structure_mode_execution}")
    if opening_move:
        lines.append(f"开头动作：{opening_move}")
    if body_shift:
        lines.append(f"中段推进：{body_shift}")
    if ending_move:
        lines.append(f"结尾动作：{ending_move}")
    if recomposition_recipe:
        lines.append(f"替代骨架：{' / '.join(recomposition_recipe)}")
    if expression_constraints:
        lines.append(f"表达约束：{' / '.join(expression_constraints)}")
    if divergence_axes:
        lines.append(f"主动拉开距离：{' / '.join(divergence_axes)}")
    if execution_checklist:
        lines.append(f"执行检查：{' / '.join(execution_checklist[:3])}")
    if benchmark_summary:
        lines.append(f"参考基准：{benchmark_summary}")
    full_protocol = _build_dbskill_problem_execution_protocol(compact=False)
    if full_protocol:
        lines.append(full_protocol)

    borrow_focuses: list[str] = []
    avoid_focuses: list[str] = []
    if isinstance(benchmarks, list):
        for benchmark in benchmarks:
            if not isinstance(benchmark, Mapping):
                continue
            borrow_focus = _as_clean_text(benchmark.get("borrow_focus"))
            avoid_focus = _as_clean_text(benchmark.get("avoid_focus"))
            if borrow_focus:
                borrow_focuses.append(borrow_focus)
            if avoid_focus:
                avoid_focuses.append(avoid_focus)

    if borrow_focuses:
        lines.append(f"可借动作：{' / '.join(dict.fromkeys(borrow_focuses))}")
    if avoid_focuses:
        lines.append(f"避开项：{' / '.join(dict.fromkeys(avoid_focuses))}")

    lines.append("原创距离最低要求：同时改掉标题骨架、开头入口、中段推进顺序和结尾动作，缺一项就继续重写。")
    lines.append("执行时只保留这些策略结论，不回看参考文章原始标题、摘要、段落顺序或问题说明书全文。")

    return "\n".join(lines) + "\n\n"


def _describe_structure_mode(structure_mode: str) -> tuple[str, str]:
    if structure_mode == "fragment_chain_observation":
        return (
            "碎片回环观察推进",
            "围绕同一个问题串起 2 到 4 个现实接口，让每个碎片承担不同压力；不要压成单主角完整短篇，也不要平均拆成对称分论点。",
        )
    if structure_mode == "single_window_scene":
        return (
            "单场景窄时窗推进",
            "前半篇尽量守住同一段时间和同一处境现场，不要均匀拆成几个并列观点段。",
        )
    if structure_mode == "scene_first_progression":
        return (
            "场景优先推进",
            "先让一到两个连续场景带路，再逐步展开判断，不要直接平铺成并列观点段。",
        )
    return ("", "")


def _build_structure_mode_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    strategy_card = payload.get("strategy_card")
    if not isinstance(strategy_card, Mapping):
        return ""
    structure_mode = _as_clean_text(strategy_card.get("structure_mode"))
    if structure_mode == "fragment_chain_observation":
        if stage == "outline":
            return (
                "若策略包要求碎片回环观察推进，大纲围绕同一个问题串起 2 到 4 个现实接口，"
                "让每个碎片承担不同压力，不要平均排成几个对称分论点，也不要压成一个完整连续场景。"
                "不要把这 2 到 4 个接口顺着时间缝成一个人从早到晚一路推进的完整日程线，"
                "接口之间允许跳接、回看和留白，不必把所有转场都补齐。"
            )
        if stage == "draft":
            return (
                "若策略包要求碎片回环观察推进，正文围绕同一个问题串起 2 到 4 个现实接口，"
                "让每个碎片承担不同压力，不要平均排成几个对称分论点，也不要压成一个完整连续场景。"
                "不要把这 2 到 4 个接口顺着时间缝成一个人从早到晚一路推进的完整日程线，"
                "接口之间允许跳接、回看和留白，不必把所有转场都补齐。"
            )
    if structure_mode == "single_window_scene":
        if stage == "outline":
            return (
                "若策略包要求单场景窄时窗推进，大纲前半段优先围绕同一段时间和同一处境现场推进，"
                "不要平均分成几个对称分论点。"
                "开头锚点优先落到能摸到的物件、界面、动作或身体反应上，先不要抽象概括主题。"
            )
        if stage == "draft":
            return (
                "若策略包要求单场景窄时窗推进，前半篇尽量守住同一段时间和同一处境现场，"
                "不要平均分成几个对称分论点。"
                "第一屏先落到能摸到的物件、界面、动作或身体反应，不要先下抽象判断。"
                "结尾只收在一个更小的动作、余波或没完全处理完的现实阻力上，不要急着升华。"
            )
    if structure_mode == "scene_first_progression":
        if stage == "outline":
            return "若策略包强调场景优先推进，大纲先让连续场景带路，再安排判断，不要直接平铺观点。"
        if stage == "draft":
            return "若策略包强调场景优先推进，正文先让连续场景带路，再逐步展开判断，不要直接平铺观点。"
    return ""


def _build_recomposition_recipe_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    strategy_card = payload.get("strategy_card")
    if not isinstance(strategy_card, Mapping):
        return ""
    recipe_value = strategy_card.get("recomposition_recipe")
    if not isinstance(recipe_value, list):
        return ""
    recipe = [_as_clean_text(item) for item in recipe_value if _as_clean_text(item)]
    if not recipe:
        return ""
    joined = "；".join(recipe[:4])
    if stage == "outline":
        return f"如果策略包已经给出替代骨架，大纲必须优先服从这套新骨架：{joined}。"
    if stage == "draft":
        return f"如果策略包已经给出替代骨架，正文必须沿着这套新骨架推进：{joined}。不要回到参考文常见的标题、小节和收尾节拍。"
    return ""


def _should_use_compact_strategy_draft_mode(
    payload: Mapping[str, object],
    *,
    is_polish_mode: bool,
) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if is_polish_mode:
        return bool(payload.get("compact_polish_mode"))
    return bool(payload.get("compact_strategy_mode"))


def build_outline_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    tone_profile = payload.get("tone_profile")
    style_section = render_tone_profile_section(tone_profile if isinstance(tone_profile, Mapping) else None)
    target_wording = _render_outline_target_wording(tone_profile if isinstance(tone_profile, Mapping) else None)
    reference_article_section = (
        ""
        if _has_strategy_package(payload)
        else _render_reference_article_section(payload, stage="outline")
    )
    post_strategy_reference_boundary = _render_post_strategy_reference_boundary(payload, stage="outline")
    strategy_package_section = _render_strategy_package_section(payload)
    reference_article_instructions = _build_reference_article_instructions(stage="outline")
    original_expression_instructions = _build_original_expression_instructions(stage="outline")
    humanizer_zh_review_instructions = _build_humanizer_zh_review_instructions(stage="outline")
    structure_mode_instructions = _build_structure_mode_instructions(payload, stage="outline")
    recomposition_recipe_instructions = _build_recomposition_recipe_instructions(payload, stage="outline")
    pressure_guard_instructions = _build_tracked_article_pressure_guard_instructions(payload, stage="outline")
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="内容策划编辑",
            task_brief="请基于给定选题，输出一个适合女性情感成长公众号的文章大纲。",
            domain_pack=payload.get("domain_pack"),
        )
        + original_expression_instructions
        + humanizer_zh_review_instructions
        + "大纲只写段落职责和推进动作，不要把任何一段提前扩写成完整正文；每段尽量控制在 1 行。"
        + pressure_guard_instructions
        + structure_mode_instructions
        + recomposition_recipe_instructions
        + reference_article_instructions,
        prompt=(
            f"趋势标题：{payload['trend_title']}\n"
            f"选题标题：{payload['topic_title']}\n"
            f"{_render_topic_angle_context(payload, stage='outline')}"
            f"项目标题：{payload['project_title']}\n\n"
            f"{reference_article_section}"
            f"{post_strategy_reference_boundary}\n"
            f"{strategy_package_section}"
            f"{style_section}"
            f"{target_wording}"
            "返回：\n"
            "1. 一个 1 句话的情绪钩子 hook\n"
            "2. 一个 4 到 6 段的 markdown 大纲 outline_body（每段 1 行，单段尽量不超过 40 字）"
        ),
    )


def build_topic_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    source_type = _as_clean_text(payload.get("source_type")) or "trend"
    tone_profile = payload.get("tone_profile")
    style_section = render_tone_profile_section(tone_profile if isinstance(tone_profile, Mapping) else None)
    pressure_guard_instructions = _build_tracked_article_pressure_guard_instructions(payload, stage="topic")
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
            + "不要使用“不是A，而是B”或“不是A，只是B”这类对称判断句做选题标题。"
            + "不要把参考文章里的高频词直接放进标题主干，要改成新的具体处境、动作或情绪入口。"
            + "不要沿用参考文章默认的矛盾顺序或段落重心，要重新换一个更适合继续原创扩写的组织焦点。"
            + "标题和切入角度至少要同时改掉原标题骨架、观察视角和情绪推进顺序中的两项。"
            + "切入角度只写 1 句话，控制在 40 到 80 个汉字，不要扩成整段方案说明。"
            + pressure_guard_instructions
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
            + "切入角度只写 1 句话，控制在 40 到 80 个汉字，不要扩成整段方案说明。"
        )

    return PromptTemplate(
        instructions=instructions,
        prompt=(
            f"{source_prompt}\n"
            f"{style_section}"
            "返回：\n"
            "1. 选题标题 title\n"
            "2. 切入角度 angle（1 句话，控制在 40 到 80 个汉字）"
        ),
    )


def build_draft_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    outline = payload["outline"]
    review_comment = _as_clean_text(payload.get("review_comment"))
    polish_instruction = _as_clean_text(payload.get("polish_instruction"))
    current_draft = payload.get("draft")
    is_polish_mode = bool(polish_instruction and isinstance(current_draft, Mapping))
    compact_strategy_mode = _should_use_compact_strategy_draft_mode(
        payload,
        is_polish_mode=is_polish_mode,
    )
    tone_profile = payload.get("tone_profile")
    style_section = render_tone_profile_section(tone_profile if isinstance(tone_profile, Mapping) else None)
    target_wording = _render_draft_target_wording(tone_profile if isinstance(tone_profile, Mapping) else None)
    reference_article_section = (
        ""
        if _has_strategy_package(payload)
        else _render_reference_article_section(payload, stage="draft")
    )
    post_strategy_reference_boundary = _render_post_strategy_reference_boundary(payload, stage="draft")
    strategy_package_section = _render_strategy_package_section(payload, compact=compact_strategy_mode)
    reference_article_instructions = _build_reference_article_instructions(stage="draft")
    original_expression_instructions = _build_original_expression_instructions(
        stage="draft",
        compact=compact_strategy_mode,
    )
    humanizer_zh_review_instructions = _build_humanizer_zh_review_instructions(
        stage="draft",
        compact=compact_strategy_mode and not is_polish_mode,
    )
    ai_flavor_risk_instructions = _build_localized_ai_flavor_risk_instructions(
        compact=compact_strategy_mode and not is_polish_mode
    )
    wechat_public_account_instructions = _build_wechat_public_account_draft_instructions(
        compact=compact_strategy_mode
    )
    pressure_guard_instructions = _build_tracked_article_pressure_guard_instructions(payload, stage="draft")
    structure_mode_instructions = _build_structure_mode_instructions(payload, stage="draft")
    recomposition_recipe_instructions = _build_recomposition_recipe_instructions(payload, stage="draft")
    allow_structure_recomposition = bool(payload.get("allow_structure_recomposition"))
    preserve_structure_anchors_value = payload.get("preserve_structure_anchors")
    preserve_structure_anchors = (
        not allow_structure_recomposition
        if preserve_structure_anchors_value is None
        else bool(preserve_structure_anchors_value)
    )
    structure_anchor_section = _render_polish_structure_anchor_section(
        current_draft if is_polish_mode and preserve_structure_anchors else None
    )
    task_brief = (
        (
            "请基于现有正文做一轮原创增强精修。保留主题、人物关系和事实边界，但允许重组标题、段落顺序和收束方式，直接拆掉过于贴近参考文或过于完整成稿的骨架。"
            if allow_structure_recomposition
            else "请基于现有正文做一轮原创增强精修。要求保留原文主线和文体，只重写模板感重、说理过满或口号感明显的段落。"
        )
        if is_polish_mode
        else (
            "请把选题和大纲扩写成一篇中文初稿。"
            "它应该像作者仍在推进中的一版，不是已经准备进编辑排版的完整示范文。"
            "要求有标题、自然分段和具体抓手，但不要求把每一段都补满，也不要求把结尾收得很完整。"
            "如果来源是参考文章改写，不要自动把多个现实接口缝成一个人从早到晚一路推进的完整成稿，"
            "允许局部停顿、回看和不完全收束。"
            if _as_clean_text(payload.get("source_type")) == "tracked_article"
            else "请把选题和大纲扩写成一篇可直接进入编辑流程的中文初稿。要求有清晰标题、自然分段、具体场景和收束段。"
        )
    )

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
        +
        (
            "请基于现有草稿精修。你可以重组标题、段落顺序、小节职责和结尾动作，但不要偏离原有主题，不要虚构新事实。\n"
            if allow_structure_recomposition
            else "请基于现有草稿精修，不要偏离原有主题与结构主线。\n"
        )
        if is_polish_mode
        else ""
    )
    polish_protocol = (
        _build_polish_protocol(
            allow_structure_recomposition=allow_structure_recomposition,
            compact=compact_strategy_mode and is_polish_mode,
        )
        if is_polish_mode
        else ""
    )
    polish_mode_instructions = (
        _build_polish_mode_instructions(compact=compact_strategy_mode and is_polish_mode)
        if is_polish_mode
        else ""
    )
    polish_recomposition_mode_instructions = (
        _build_polish_recomposition_mode_instructions(compact=compact_strategy_mode and is_polish_mode)
        if is_polish_mode and allow_structure_recomposition
        else ""
    )
    outline_section = "" if is_polish_mode else _render_draft_outline_section(
        outline,
        compact=compact_strategy_mode,
    )
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="正文作者",
            task_brief=task_brief,
            domain_pack=payload.get("domain_pack"),
        )
        + original_expression_instructions
        + humanizer_zh_review_instructions
        + ai_flavor_risk_instructions
        + wechat_public_account_instructions
        + pressure_guard_instructions
        + structure_mode_instructions
        + recomposition_recipe_instructions
        + polish_mode_instructions
        + polish_recomposition_mode_instructions
        + polish_protocol
        + reference_article_instructions,
        prompt=(
            f"趋势标题：{payload['trend_title']}\n"
            f"选题标题：{payload['topic_title']}\n"
            f"{_render_topic_angle_context(payload, stage='draft')}"
            f"项目标题：{payload['project_title']}\n"
            f"{reference_article_section}"
            f"{post_strategy_reference_boundary}\n"
            f"{strategy_package_section}"
            f"{style_section}"
            f"{target_wording}"
            f"{structure_anchor_section}"
            f"{review_section}\n"
            f"{polish_section}\n"
            f"{outline_section}"
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
