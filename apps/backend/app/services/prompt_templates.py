from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from app.services.content_skills import build_content_skill_instructions
from app.services.dbskill_bridge import get_dbskill_rule_lines, merge_unique_lines
from app.schemas.settings import PromptTemplateSummary
from app.services.tone_profile_presets import (
    JINWAN_YOUYU_INTERNAL_PRESSURE_CLOSING_STYLE,
    JINWAN_YOUYU_INTERNAL_PRESSURE_OPENING_STYLE,
    JINWAN_YOUYU_INTERNAL_PRESSURE_PARAGRAPH_RHYTHM,
    JINWAN_YOUYU_INTERNAL_PRESSURE_POLISH,
    JINWAN_YOUYU_INTERNAL_PRESSURE_VALUE_CONSTRAINTS,
    JINWAN_YOUYU_PRESET_KEY,
    resolve_tone_profile_preset_key,
)


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
_NEGATED_RELATIONSHIP_PATTERNS = (
    "不是关系修复",
    "不是亲密关系",
    "不是沟通修复",
    "不是关系摊牌",
    "不是关系摊牌或沟通修复",
    "不是关系摊牌或关系修复",
    "不是沟通修复主线",
    "不是关系摊牌或沟通修复主线",
    "不是关系摊牌或“怎么把话说清楚”的沟通修复主线",
    "不是冷战",
    "不是分手",
)
_RELATIONSHIP_NEGATION_PREFIXES = (
    "不是",
    "不写",
    "不要写成",
    "不要变成",
    "不要落成",
    "不要收窄成",
    "别写成",
    "别变成",
    "别落成",
    "不在",
)
_RELATIONSHIP_KEYWORD_PATTERN = "|".join(re.escape(keyword) for keyword in _RELATIONSHIP_PRESSURE_GUARD_KEYWORDS)

_GENERIC_TRACKED_ARTICLE_CUE_PREFIXES = (
    "其实",
    "人啊",
    "你每天",
    "人这一生",
    "生活从来",
    "生活，从来",
    "平日里",
    "我想",
    "如果生活",
)
_GENERIC_TRACKED_ARTICLE_CUE_PHRASES = (
    "这个世界上",
    "真正的完美",
    "所谓的完美人生",
    "生活本身",
    "真正的自己",
    "一生仅此一回",
    "一生，在一朝一夕",
)
_PRESSURE_BODY_CUE_KEYWORDS = (
    "体检",
    "身体",
    "疲惫",
    "耗尽",
    "透析",
    "尿毒症",
    "褥疮",
    "轮椅",
    "电话",
    "提醒",
    "复查",
    "休息",
    "工作",
    "家人",
    "推迟",
    "往后放",
    "再撑",
    "代价",
    "后果",
    "遗憾",
    "自己",
    "照顾好自己",
    "自我照料",
)

_INTERNAL_PRESSURE_BODY_HARD_SIGNALS = (
    "体检",
    "复查",
    "透析",
    "尿毒症",
    "褥疮",
    "轮椅",
    "身体提醒",
    "身体信号",
    "报警",
)
_INTERNAL_PRESSURE_BODY_SOFT_SIGNALS = (
    "身体",
    "疲惫",
    "耗尽",
    "休息",
    "工作",
    "家人",
    "推迟",
    "往后放",
    "再撑",
    "代价",
    "后果",
    "照顾好自己",
    "自我照料",
)
_EMOTIONAL_ENGINE_GUARD_KEYWORDS = (
    "放下",
    "放手",
    "知足",
    "珍惜",
    "珍惜当下",
    "幸福",
    "幸福是什么",
    "别无所求",
    "不再强求",
    "强求",
    "执念",
    "得不到",
    "不甘心",
    "停止拉扯",
)
_BROAD_EMOTIONAL_RELEASE_PRIORITY_KEYWORDS = (
    "幸福",
    "幸福是什么",
    "放下",
    "放手",
    "不再强求",
    "强求",
    "别无所求",
    "知足",
    "珍惜",
    "珍惜当下",
    "停止拉扯",
    "不甘心",
    "得不到",
    "拥有",
    "已经拥有",
    "腾出位置",
)
_BROAD_EMOTIONAL_RELEASE_THESIS_MARKERS = (
    "其实是",
    "真正的幸福",
    "该结束的时候",
    "该珍惜的时候",
    "看看你拥有的",
    "幸福的底座",
    "不是失去",
    "腾出位置",
    "终于不再",
)
_BROAD_EMOTIONAL_RELEASE_EXAMPLE_PREFIXES = (
    "你有没有过这样的时刻",
    "明明一段关系",
    "明明一个目标",
)
_EVERYDAY_WARMTH_RETURN_ACHIEVEMENT_KEYWORDS = (
    "大事",
    "轰轰烈烈",
    "出人头地",
    "改变世界",
    "赚大钱",
    "住大房子",
    "大公司",
    "大名声",
    "成就",
    "成就叙事",
    "宏大叙事",
    "远大抱负",
    "高楼大厦",
    "灯火辉煌",
)
_EVERYDAY_WARMTH_RETURN_DAILY_KEYWORDS = (
    "人间烟火",
    "陪在爱的人身边",
    "陪爱人",
    "爱人的话",
    "做了一顿晚饭",
    "接孩子",
    "一家老小",
    "热汤",
    "夜灯",
    "晚安",
    "父母",
    "爱人",
    "孩子",
    "回家",
    "小事",
    "微小",
    "细碎",
    "日常瞬间",
    "平淡的日常",
    "陪伴",
    "细水长流",
)
_EVERYDAY_WARMTH_RETURN_THESIS_MARKERS = (
    "最重要的事",
    "祛魅",
    "才属于你我",
    "才是我们的一生",
    "把“大事”放一放",
    "把“小事”捡起来",
    "被“宏大”绑架",
    "被“微小”治愈",
)
_RELATIONSHIP_EXAMPLE_NARROWING_MARKERS = (
    "一段关系",
    "关系已经烂了",
    "坏关系",
    "感情诚意",
    "沉没成本",
    "死死抓着不放",
    "再坚持一下",
)
_RELATIONSHIP_AFTERCARE_CONFLICT_KEYWORDS = (
    "吵架",
    "争吵",
    "争执",
    "冷暴力",
    "冷战",
    "赌气",
    "闹完",
    "吵完",
    "失望",
    "委屈",
    "误解",
    "不理不睬",
    "情绪发酵",
    "针锋相对",
)
_RELATIONSHIP_AFTERCARE_REPAIR_KEYWORDS = (
    "修复",
    "沟通",
    "接住",
    "回来",
    "主动解决",
    "达成共识",
    "和好",
    "继续走下去",
    "温柔以待",
    "妥协",
    "理解",
    "包容",
    "顺序",
    "回归理性",
)
_RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS = (
    "关系",
    "爱不爱",
    "爱意",
    "两个人",
    "伴侣",
    "婚姻",
    "亲密",
    "安全感",
)
_RELATIONSHIP_AFTERCARE_THESIS_MARKERS = (
    "吵架后的态度",
    "检验爱情的试金石",
    "真正爱你的人",
    "不舍得让你一个人在坏情绪里",
    "不曾对你冷暴力",
    "用爱修复争吵中留下的伤口",
    "不是永远不吵架",
    "争吵以后还想要继续走下去",
    "谁先冷下来谁就算懂事",
    "回避修复",
    "回避税",
)
_RESILIENCE_RECONSTRUCTION_ADVERSITY_KEYWORDS = (
    "韧性",
    "命运",
    "重击",
    "淬炼",
    "凤凰涅槃",
    "车祸",
    "右臂",
    "右腿",
    "残肢",
    "刺穿",
    "皮肤",
    "手术台",
    "剧痛",
    "伤痛",
    "残缺",
)
_RESILIENCE_RECONSTRUCTION_TRAINING_KEYWORDS = (
    "残奥",
    "冠军",
    "泳池",
    "游泳",
    "转身",
    "呛水",
    "蹬水",
    "划水",
    "多划11下",
    "11下",
    "训练",
    "万米训练",
    "肩伤",
    "背痛",
    "炎症",
    "风暴",
)
_RESILIENCE_RECONSTRUCTION_IDENTITY_KEYWORDS = (
    "不要让任何人",
    "限制你",
    "破碎中重建",
    "生命的裂痕",
    "命运的终章",
    "不被定义",
    "向阳而生",
    "自己的太阳",
    "破局而上",
)
_RESILIENCE_RECONSTRUCTION_THESIS_MARKERS = (
    "百折不回",
    "真正的强大",
    "完整的人生",
    "一寸寸拔节",
    "一步步生长",
    "心有山海",
    "静水流深",
    "不必借光而行",
)
_SUPPORTIVE_LIFE_BASE_MARKERS = (
    "健康的身体",
    "爱你的家人",
    "三两好友",
    "一碗热饭",
)


def _infer_tracked_article_pressure_guard(payload: Mapping[str, object]) -> str:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return ""
    if _has_everyday_warmth_return_focus(payload):
        return ""
    if _has_relationship_aftercare_focus(payload):
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
    field_corpus_parts = [_as_clean_text(value) for value in fields if _as_clean_text(value)]
    tag_corpus_parts: list[str] = []
    for tag_value in tag_values:
        if isinstance(tag_value, list):
            tag_corpus_parts.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))

    field_corpus = " ".join(field_corpus_parts)
    tag_corpus = " ".join(tag_corpus_parts)
    corpus = " ".join(part for part in (field_corpus, tag_corpus) if part)
    if not corpus:
        return ""

    internal_hits = sum(1 for keyword in _INTERNAL_PRESSURE_GUARD_KEYWORDS if keyword in corpus)
    relationship_field_corpus, field_has_negated_relationship_clause = _strip_negated_relationship_spans(field_corpus)
    relationship_hits = sum(1 for keyword in _RELATIONSHIP_PRESSURE_GUARD_KEYWORDS if keyword in relationship_field_corpus)
    if relationship_hits == 0 and not field_has_negated_relationship_clause:
        relationship_hits = sum(1 for keyword in _RELATIONSHIP_PRESSURE_GUARD_KEYWORDS if keyword in tag_corpus)
    elif relationship_hits > 0:
        relationship_hits += sum(1 for keyword in _RELATIONSHIP_PRESSURE_GUARD_KEYWORDS if keyword in tag_corpus)
    body_markdown = _as_clean_text(payload.get("body_markdown")) or _as_clean_text(payload.get("reference_article_body_markdown"))
    structure_notes = _as_clean_text(payload.get("structure_notes")) or _as_clean_text(payload.get("reference_article_structure_notes"))
    article_title = _as_clean_text(payload.get("article_title")) or _as_clean_text(payload.get("reference_article_title"))
    summary = _as_clean_text(payload.get("summary")) or _as_clean_text(payload.get("reference_article_summary"))
    body_corpus = " ".join(part for part in (article_title, summary, structure_notes, body_markdown) if part)
    current_topic_title = _as_clean_text(payload.get("topic_title"))
    current_topic_angle = _as_clean_text(payload.get("topic_angle"))
    outline_hook = _as_clean_text((payload.get("outline") or {}).get("hook")) if isinstance(payload.get("outline"), Mapping) else ""
    current_context_corpus = " ".join(part for part in (current_topic_title, current_topic_angle, outline_hook) if part)
    hard_signal_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in body_corpus)
    soft_signal_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_SOFT_SIGNALS if keyword in body_corpus)
    emotional_engine_hits = sum(1 for keyword in _EMOTIONAL_ENGINE_GUARD_KEYWORDS if keyword in body_corpus)
    contextual_hard_signal_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in current_context_corpus)
    has_pressure_body_signal = (
        hard_signal_hits >= 1
        or contextual_hard_signal_hits >= 1
        or (soft_signal_hits >= 2 and ("后来" in body_corpus or "直到" in body_corpus))
    )
    emotional_engine_dominant = emotional_engine_hits >= 3 and hard_signal_hits == 0
    if internal_hits >= 2 and relationship_hits == 0 and has_pressure_body_signal and not emotional_engine_dominant:
        return "internal_pressure"
    return ""


def _has_broad_emotional_release_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False

    fields = [
        payload.get("topic_title"),
        payload.get("topic_angle"),
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("body_markdown"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
        payload.get("reference_article_body_markdown"),
    ]
    problem_brief = payload.get("problem_brief")
    if isinstance(problem_brief, Mapping):
        fields.extend(
            [
                problem_brief.get("raw_goal"),
                problem_brief.get("clarified_problem"),
                problem_brief.get("observed_phenomenon"),
                problem_brief.get("writing_goal"),
                problem_brief.get("target_reader_situation"),
                problem_brief.get("core_conflict"),
                problem_brief.get("feedback_entry"),
            ]
        )
    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping):
        fields.extend(
            [
                strategy_card.get("reader_situation"),
                strategy_card.get("point_of_view"),
                strategy_card.get("conflict_frame"),
                strategy_card.get("emotional_path"),
                strategy_card.get("opening_move"),
                strategy_card.get("body_shift"),
                strategy_card.get("ending_move"),
                strategy_card.get("benchmark_summary"),
            ]
        )
    tag_values = [payload.get("tags"), payload.get("reference_article_tags")]
    corpus_parts = [_as_clean_text(value) for value in fields if _as_clean_text(value)]
    for tag_value in tag_values:
        if isinstance(tag_value, list):
            corpus_parts.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))
    corpus = " ".join(corpus_parts)
    if not corpus:
        return False

    emotional_hits = sum(1 for keyword in _BROAD_EMOTIONAL_RELEASE_PRIORITY_KEYWORDS if keyword in corpus)
    thesis_hits = sum(1 for marker in _BROAD_EMOTIONAL_RELEASE_THESIS_MARKERS if marker in corpus)
    hard_pressure_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in corpus)
    return emotional_hits >= 4 and thesis_hits >= 1 and hard_pressure_hits == 0


def _has_everyday_warmth_return_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False

    fields = [
        payload.get("topic_title"),
        payload.get("topic_angle"),
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("body_markdown"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
        payload.get("reference_article_body_markdown"),
    ]
    problem_brief = payload.get("problem_brief")
    if isinstance(problem_brief, Mapping):
        fields.extend(
            [
                problem_brief.get("raw_goal"),
                problem_brief.get("clarified_problem"),
                problem_brief.get("observed_phenomenon"),
                problem_brief.get("writing_goal"),
                problem_brief.get("target_reader_situation"),
                problem_brief.get("core_conflict"),
                problem_brief.get("feedback_entry"),
            ]
        )
    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping):
        fields.extend(
            [
                strategy_card.get("reader_situation"),
                strategy_card.get("point_of_view"),
                strategy_card.get("conflict_frame"),
                strategy_card.get("emotional_path"),
                strategy_card.get("opening_move"),
                strategy_card.get("body_shift"),
                strategy_card.get("ending_move"),
                strategy_card.get("benchmark_summary"),
            ]
        )
    corpus = " ".join(_as_clean_text(value) for value in fields if _as_clean_text(value))
    if not corpus:
        return False

    achievement_hits = sum(1 for keyword in _EVERYDAY_WARMTH_RETURN_ACHIEVEMENT_KEYWORDS if keyword in corpus)
    daily_hits = sum(1 for keyword in _EVERYDAY_WARMTH_RETURN_DAILY_KEYWORDS if keyword in corpus)
    thesis_hits = sum(1 for marker in _EVERYDAY_WARMTH_RETURN_THESIS_MARKERS if marker in corpus)
    return achievement_hits >= 2 and daily_hits >= 3 and thesis_hits >= 1


def _has_resilience_reconstruction_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if _has_everyday_warmth_return_focus(payload):
        return False
    if _has_relationship_aftercare_focus(payload):
        return False

    fields = [
        payload.get("topic_title"),
        payload.get("topic_angle"),
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("body_markdown"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
        payload.get("reference_article_body_markdown"),
    ]
    problem_brief = payload.get("problem_brief")
    if isinstance(problem_brief, Mapping):
        fields.extend(
            [
                problem_brief.get("raw_goal"),
                problem_brief.get("clarified_problem"),
                problem_brief.get("observed_phenomenon"),
                problem_brief.get("writing_goal"),
                problem_brief.get("target_reader_situation"),
                problem_brief.get("core_conflict"),
                problem_brief.get("feedback_entry"),
            ]
        )
    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping):
        fields.extend(
            [
                strategy_card.get("reader_situation"),
                strategy_card.get("point_of_view"),
                strategy_card.get("conflict_frame"),
                strategy_card.get("emotional_path"),
                strategy_card.get("opening_move"),
                strategy_card.get("body_shift"),
                strategy_card.get("ending_move"),
                strategy_card.get("benchmark_summary"),
            ]
        )
    tag_values = [payload.get("tags"), payload.get("reference_article_tags")]
    corpus_parts = [_as_clean_text(value) for value in fields if _as_clean_text(value)]
    for tag_value in tag_values:
        if isinstance(tag_value, list):
            corpus_parts.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))
    corpus = " ".join(corpus_parts)
    if not corpus:
        return False

    adversity_hits = sum(1 for keyword in _RESILIENCE_RECONSTRUCTION_ADVERSITY_KEYWORDS if keyword in corpus)
    training_hits = sum(1 for keyword in _RESILIENCE_RECONSTRUCTION_TRAINING_KEYWORDS if keyword in corpus)
    identity_hits = sum(1 for keyword in _RESILIENCE_RECONSTRUCTION_IDENTITY_KEYWORDS if keyword in corpus)
    thesis_hits = sum(1 for marker in _RESILIENCE_RECONSTRUCTION_THESIS_MARKERS if marker in corpus)
    return (
        adversity_hits >= 2
        and training_hits >= 2
        and (identity_hits >= 1 or thesis_hits >= 1)
    ) or (
        adversity_hits >= 3
        and training_hits >= 1
        and identity_hits >= 2
    )


def _has_relationship_aftercare_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False

    fields = [
        payload.get("topic_title"),
        payload.get("topic_angle"),
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("body_markdown"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
        payload.get("reference_article_body_markdown"),
    ]
    problem_brief = payload.get("problem_brief")
    if isinstance(problem_brief, Mapping):
        fields.extend(
            [
                problem_brief.get("raw_goal"),
                problem_brief.get("clarified_problem"),
                problem_brief.get("observed_phenomenon"),
                problem_brief.get("writing_goal"),
                problem_brief.get("target_reader_situation"),
                problem_brief.get("core_conflict"),
                problem_brief.get("feedback_entry"),
            ]
        )
    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping):
        fields.extend(
            [
                strategy_card.get("reader_situation"),
                strategy_card.get("point_of_view"),
                strategy_card.get("conflict_frame"),
                strategy_card.get("emotional_path"),
                strategy_card.get("opening_move"),
                strategy_card.get("body_shift"),
                strategy_card.get("ending_move"),
                strategy_card.get("benchmark_summary"),
            ]
        )
    tag_values = [payload.get("tags"), payload.get("reference_article_tags")]
    corpus_parts = [_as_clean_text(value) for value in fields if _as_clean_text(value)]
    for tag_value in tag_values:
        if isinstance(tag_value, list):
            corpus_parts.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))
    corpus = " ".join(corpus_parts)
    if not corpus:
        return False

    conflict_hits = sum(1 for keyword in _RELATIONSHIP_AFTERCARE_CONFLICT_KEYWORDS if keyword in corpus)
    repair_hits = sum(1 for keyword in _RELATIONSHIP_AFTERCARE_REPAIR_KEYWORDS if keyword in corpus)
    relationship_hits = sum(1 for keyword in _RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS if keyword in corpus)
    thesis_hits = sum(1 for marker in _RELATIONSHIP_AFTERCARE_THESIS_MARKERS if marker in corpus)
    hard_pressure_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in corpus)
    return (
        relationship_hits >= 1
        and conflict_hits >= 1
        and repair_hits >= 2
        and (thesis_hits >= 1 or conflict_hits >= 2)
        and hard_pressure_hits == 0
    )


def _render_forbidden_phrases(value: object) -> str:
    if not isinstance(value, list):
        return ""
    items = [_as_clean_text(item) for item in value]
    items = [item for item in items if item]
    return " / ".join(items)


def _split_text_sentences(text: str) -> list[str]:
    return [sentence.strip() for sentence in re.split(r"[。！？!?；;\n]", text) if sentence.strip()]


def _find_negated_relationship_clause_start(sentence: str) -> int | None:
    candidates: list[int] = []
    for pattern in _NEGATED_RELATIONSHIP_PATTERNS:
        index = sentence.find(pattern)
        if index >= 0:
            candidates.append(index)
    for prefix in _RELATIONSHIP_NEGATION_PREFIXES:
        match = re.search(rf"{re.escape(prefix)}.{{0,16}}(?:{_RELATIONSHIP_KEYWORD_PATTERN})", sentence)
        if match:
            candidates.append(match.start())
    return min(candidates) if candidates else None


def _strip_negated_relationship_spans(text: str) -> tuple[str, bool]:
    kept_sentences: list[str] = []
    has_negated_clause = False
    for sentence in _split_text_sentences(text):
        normalized = re.sub(r"\s+", "", sentence)
        if not normalized:
            continue
        clause_start = _find_negated_relationship_clause_start(normalized)
        if clause_start is not None:
            has_negated_clause = True
            normalized = normalized[:clause_start]
        if normalized:
            kept_sentences.append(normalized)
    return "".join(kept_sentences), has_negated_clause


def _is_generic_tracked_article_cue(sentence: str) -> bool:
    normalized = re.sub(r"\s+", "", sentence).strip()
    if not normalized:
        return True
    if any(normalized.startswith(prefix) for prefix in _GENERIC_TRACKED_ARTICLE_CUE_PREFIXES):
        return True
    return any(phrase in normalized for phrase in _GENERIC_TRACKED_ARTICLE_CUE_PHRASES)


def _score_tracked_article_pressure_cue(sentence: str) -> int:
    score = 0
    compact = re.sub(r"\s+", "", sentence)
    for keyword in _PRESSURE_BODY_CUE_KEYWORDS:
        if keyword in compact:
            score += 2
    if any(token in compact for token in ("后来", "直到", "迟早", "开始", "又")):
        score += 1
    if "“" in sentence or "\"" in sentence:
        score += 1
    if _is_generic_tracked_article_cue(sentence):
        score -= 4
    if len(compact) < 10:
        score -= 2
    return score


def _score_tracked_article_emotional_cue(sentence: str, *, broad_scope: bool) -> int:
    score = 0
    compact = re.sub(r"\s+", "", sentence)
    for keyword in _BROAD_EMOTIONAL_RELEASE_PRIORITY_KEYWORDS:
        if keyword in compact:
            score += 2
    for marker in _BROAD_EMOTIONAL_RELEASE_THESIS_MARKERS:
        if marker in compact:
            score += 2
    if "“" in sentence or "\"" in sentence:
        score += 1
    if _is_generic_tracked_article_cue(sentence):
        score -= 4
    if broad_scope and any(compact.startswith(prefix) for prefix in _BROAD_EMOTIONAL_RELEASE_EXAMPLE_PREFIXES):
        score -= 5
    if broad_scope and any(marker in compact for marker in _RELATIONSHIP_EXAMPLE_NARROWING_MARKERS):
        score -= 4
    if len(compact) < 10:
        score -= 2
    return score


def _score_tracked_article_everyday_warmth_cue(sentence: str) -> int:
    score = 0
    compact = re.sub(r"\s+", "", sentence)
    for keyword in _EVERYDAY_WARMTH_RETURN_ACHIEVEMENT_KEYWORDS:
        if keyword in compact:
            score += 2
    for keyword in _EVERYDAY_WARMTH_RETURN_DAILY_KEYWORDS:
        if keyword in compact:
            score += 2
    for marker in _EVERYDAY_WARMTH_RETURN_THESIS_MARKERS:
        if marker in compact:
            score += 2
    if "“" in sentence or "\"" in sentence:
        score += 1
    if _is_generic_tracked_article_cue(sentence):
        score -= 4
    if any(keyword in compact for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS):
        score -= 2
    if len(compact) < 10:
        score -= 2
    return score


def _score_tracked_article_resilience_cue(sentence: str) -> int:
    score = 0
    compact = re.sub(r"\s+", "", sentence)
    for keyword in _RESILIENCE_RECONSTRUCTION_ADVERSITY_KEYWORDS:
        if keyword in compact:
            score += 2
    for keyword in _RESILIENCE_RECONSTRUCTION_TRAINING_KEYWORDS:
        if keyword in compact:
            score += 2
    for keyword in _RESILIENCE_RECONSTRUCTION_IDENTITY_KEYWORDS:
        if keyword in compact:
            score += 2
    for marker in _RESILIENCE_RECONSTRUCTION_THESIS_MARKERS:
        if marker in compact:
            score += 2
    if "“" in sentence or "\"" in sentence:
        score += 1
    if _is_generic_tracked_article_cue(sentence):
        score -= 4
    if len(compact) < 10:
        score -= 2
    return score


def _score_tracked_article_relationship_aftercare_cue(sentence: str) -> int:
    score = 0
    compact = re.sub(r"\s+", "", sentence)
    for keyword in _RELATIONSHIP_AFTERCARE_CONFLICT_KEYWORDS:
        if keyword in compact:
            score += 2
    for keyword in _RELATIONSHIP_AFTERCARE_REPAIR_KEYWORDS:
        if keyword in compact:
            score += 2
    for keyword in _RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS:
        if keyword in compact:
            score += 1
    for marker in _RELATIONSHIP_AFTERCARE_THESIS_MARKERS:
        if marker in compact:
            score += 2
    if "“" in sentence or "\"" in sentence:
        score += 1
    if _is_generic_tracked_article_cue(sentence):
        score -= 4
    if len(compact) < 10:
        score -= 2
    return score


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


def _is_jinwan_youyu_style(tone_profile: Mapping[str, object] | None) -> bool:
    return resolve_tone_profile_preset_key(tone_profile) == JINWAN_YOUYU_PRESET_KEY


def _should_apply_jinwan_youyu_internal_pressure_overrides(
    *,
    tone_profile: Mapping[str, object] | None,
    payload: Mapping[str, object] | None,
) -> bool:
    return bool(
        payload
        and _is_jinwan_youyu_style(tone_profile)
        and _infer_tracked_article_pressure_guard(payload) == "internal_pressure"
    )


def _merge_tone_profile_text(base: str, extra: str) -> str:
    base_text = base.strip()
    extra_text = extra.strip()
    if not base_text:
        return extra_text
    if not extra_text:
        return base_text
    if extra_text in base_text:
        return base_text
    if base_text.endswith(("。", "；")):
        return f"{base_text}{extra_text}"
    return f"{base_text}；{extra_text}"


def _build_effective_tone_profile(
    tone_profile: Mapping[str, object] | None,
    *,
    payload: Mapping[str, object] | None,
) -> Mapping[str, object] | None:
    if not tone_profile:
        return tone_profile
    if not _should_apply_jinwan_youyu_internal_pressure_overrides(
        tone_profile=tone_profile,
        payload=payload,
    ):
        return tone_profile

    effective = dict(tone_profile)
    effective["opening_style"] = JINWAN_YOUYU_INTERNAL_PRESSURE_OPENING_STYLE
    effective["paragraph_rhythm"] = JINWAN_YOUYU_INTERNAL_PRESSURE_PARAGRAPH_RHYTHM
    effective["closing_style"] = JINWAN_YOUYU_INTERNAL_PRESSURE_CLOSING_STYLE
    effective["value_constraints"] = _merge_tone_profile_text(
        _as_clean_text(tone_profile.get("value_constraints")),
        JINWAN_YOUYU_INTERNAL_PRESSURE_VALUE_CONSTRAINTS,
    )
    effective["default_polish_instruction"] = _merge_tone_profile_text(
        _as_clean_text(tone_profile.get("default_polish_instruction")),
        JINWAN_YOUYU_INTERNAL_PRESSURE_POLISH,
    )
    return effective


def _harmonize_polish_instruction_for_effective_tone_profile(
    polish_instruction: str,
    *,
    tone_profile: Mapping[str, object] | None,
    payload: Mapping[str, object] | None,
) -> str:
    normalized = polish_instruction.strip()
    if not normalized:
        return normalized
    if not _should_apply_jinwan_youyu_internal_pressure_overrides(
        tone_profile=tone_profile,
        payload=payload,
    ):
        return normalized

    harmonized = normalized.replace(
        "开头用问句、引用或共鸣迅速点题，",
        "开头先落一个现实接口、后果或身体信号，不要先用问句、引用或共鸣替读者下定义，",
    )
    harmonized = harmonized.replace(
        "开头用直接问题、现实接口或一句共鸣判断迅速点题，",
        "开头先落一个现实接口、后果或身体信号，不要先用问句、引用或共鸣替读者下定义，",
    )
    harmonized = harmonized.replace(
        "开头优先使用问句、引用或共鸣开场，尽快把读者代入她熟悉的处境。",
        "开头先落一个现实接口、后果或身体信号，不要先用问句、引用或共鸣替读者下定义。",
    )
    return _merge_tone_profile_text(harmonized, JINWAN_YOUYU_INTERNAL_PRESSURE_POLISH)


def _build_jinwan_youyu_stage_instructions(
    *,
    stage: str,
    tone_profile: Mapping[str, object] | None,
    payload: Mapping[str, object] | None = None,
) -> str:
    if not _is_jinwan_youyu_style(tone_profile):
        return ""

    if stage == "topic":
        return (
            "这篇内容采用“今晚有语”风格。"
            "标题长度控制在 10 到 20 个字，必须带钩子，不能只是情绪陈述。"
            "选题要直接点出读者最在意的问题、反差或现实入口。"
            "判断可以明确，但先把答案落在真实接口上，不要只剩抽象结论。"
            "不要写成泛情绪、泛疗愈、泛人生感悟标题。"
        )
    if stage == "outline":
        return (
            "这篇内容采用“今晚有语”风格。"
            "大纲按标准三段式组织：开头引出问题，中间展开判断，结尾直接落结论。"
            "这不是低成本三段式，开头要点破真实问题，中段要给新观察，结尾要有明确答案。"
            "中间部分展开 2 到 4 个论点，每个论点都要能挂具体处境、判断依据或行动落点。"
            "总字数目标控制在 1200 到 1800 字。"
            "不要写成清单攻略、步骤教程或逐条说教。"
        )
    if stage == "draft":
        if _should_apply_jinwan_youyu_internal_pressure_overrides(
            tone_profile=tone_profile,
            payload=payload,
        ):
            return (
                "这篇内容采用“今晚有语”风格。"
                "开头先落一个现实接口、后果或身体信号，不要先用问句、引用或共鸣替读者下定义。"
                "判断可以直接，但不要一上来就把答案说成空泛结论，要让读者先认出自己正在付出的代价。"
                "正文中段按“现实接口 + 判断推进 + 行动落点”展开，但不要写成机械分条。"
                "每个判断都要多给一层判断依据、现实机制、情绪承接或行动落点，不能只重复标题情绪。"
                "读者默认是 25 到 45 岁女性，语言要直接有力、温暖但有边界。"
                "可以适度使用排比和对仗，但不要把句子排成整齐口号。"
                "引用名人、影视台词或理论时，全篇最多 1 到 2 处；连续两篇不能用同一个人。"
                "不要使用这些词：不禁、心想、暗想、默念、琢磨、纠结、暗自、默默。"
                "少用“像……一样”“如同”“仿佛”“宛如”“好似”这类明喻。"
                "避免“因为……所以……”“因此”“于是”“结果”这类显性因果串联。"
                "删掉“总之”“说到底”“归根结底”“值得一提的是”“不可否认”“在当今社会”这类套话。"
                "不要写“以后会好的”“明天又是新的一天”“一切都会过去”这类未来安慰句。"
                "“不是A，是B”句式整篇最多使用 2 次。"
                "破折号整篇最多使用 2 处。"
                "不要写成逐条列举、逐项解释的导购式结构。"
                "删掉没有它也不影响前后文的空段、虚段和泛感慨段。"
                "结尾优先落在一个现实动作、后果余波或轻微决定上，不要把答案写成空泛总结。"
            )
        return (
            "这篇内容采用“今晚有语”风格。"
            "开头优先用直接问题、现实接口或一句共鸣判断切入，尽快把问题和答案入口一起顶出来。"
            "不要只靠空问句、空引用或泛共鸣占住开头位置。"
            "不是让读者自己猜，你要直接把判断说出来，但要落在真实接口上。"
            "正文中段按“观点 + 例子 + 结论”推进，但不要写成机械分条。"
            "每个观点都要多给一层判断依据、现实机制、情绪承接或行动落点，不能只重复标题情绪。"
            "读者默认是 25 到 45 岁女性，语言要直接有力、温暖但有边界。"
            "可以适度使用排比和对仗，但不要把句子排成整齐口号。"
            "引用名人、影视台词或理论时，全篇最多 1 到 2 处；连续两篇不能用同一个人。"
            "不要使用这些词：不禁、心想、暗想、默念、琢磨、纠结、暗自、默默。"
            "少用“像……一样”“如同”“仿佛”“宛如”“好似”这类明喻。"
            "避免“因为……所以……”“因此”“于是”“结果”这类显性因果串联。"
            "删掉“总之”“说到底”“归根结底”“值得一提的是”“不可否认”“在当今社会”这类套话。"
            "不要写“以后会好的”“明天又是新的一天”“一切都会过去”这类未来安慰句。"
            "“不是A，是B”句式整篇最多使用 2 次。"
            "破折号整篇最多使用 2 处。"
            "不要写成逐条列举、逐项解释的导购式结构。"
            "删掉没有它也不影响前后文的空段、虚段和泛感慨段。"
            "结尾可以直接下结论、给温暖祝福、给行动落点或做简洁排比收束，但不要喊口号，也不要把答案写成空泛总结。"
        )
    if stage == "assets":
        return (
            "这篇内容采用“今晚有语”风格。"
            "标题备选和导语要直接点破读者最在意的问题，给出明确判断或答案入口。"
            "不要写成空泛抒情 teaser，不要只剩情绪氛围。"
            "封面文案要短、准、有抓手，保留女性成长内容的力量感。"
        )
    if stage == "publish_package":
        return (
            "这篇内容采用“今晚有语”风格。"
            "摘要、标签和编辑备注都要服务于“直接给答案”的发布表达。"
            "编辑备注要直接给出这篇稿子的核心答案和发布抓手，不要写成模糊抒情总结。"
        )
    return ""


def _build_jinwan_youyu_pressure_topic_tweak(
    *,
    stage: str,
    payload: Mapping[str, object],
) -> str:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return ""

    topic_angle = _as_clean_text(payload.get("topic_angle"))
    topic_title = _as_clean_text(payload.get("topic_title"))
    corpus = " ".join([topic_title, topic_angle, _as_clean_text(payload.get("summary")), _as_clean_text(payload.get("structure_notes"))])
    pressure_signals = (
        "推迟",
        "往后放",
        "等有空",
        "体检",
        "身体",
        "疲惫",
        "耗尽",
        "生活排序",
        "自我照料",
    )
    if not any(signal in corpus for signal in pressure_signals):
        return ""

    if stage == "topic":
        return (
            "这类题材不要把答案直接抽成概念词，标题先抓住一个现实接口、后果或身体信号。"
            "可以直接，但不要先把结论写成空泛判断句。"
        )
    if stage == "outline":
        return (
            "这类题材的大纲先压住一个现实接口或身体提醒，再展开判断；不要把问题先写成通用讲解稿。"
        )
    if stage == "draft":
        return (
            "这类题材的正文先落一个现实接口、后果或身体信号，再给判断和落点；不要让开头和收束都先端出空泛答案。"
        )
    if stage == "assets":
        return (
            "这类题材的标题备选、导语和封面文案都要先抓现实接口或身体信号，不要只剩抽象答案句。"
        )
    if stage == "publish_package":
        return (
            "这类题材的摘要和编辑备注先写现实接口、后果或身体信号，再写结论，不要只剩抽象总结。"
        )
    return ""


def _extract_tracked_article_body_cues(
    payload: Mapping[str, object],
    *,
    max_items: int = 3,
) -> list[str]:
    body_markdown = _as_clean_text(payload.get("body_markdown"))
    if not body_markdown:
        return []

    candidates: list[tuple[int, str]] = []
    for sentence in _split_text_sentences(body_markdown):
        normalized = re.sub(r"\s+", " ", sentence).strip(" -#>*")
        if not normalized:
            continue
        compact = re.sub(r"\s+", "", normalized)
        if (
            "健康的身体" in compact
            and not any(signal in compact for signal in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS)
            and not any(marker in compact for marker in ("改", "拖", "推", "往后", "报警", "提醒"))
        ):
            continue
        truncated = _truncate_text(normalized, max_length=64)
        score = _score_tracked_article_pressure_cue(truncated)
        if score <= 0:
            continue
        candidates.append((score, truncated))

    if not candidates:
        return []

    selected: list[str] = []
    for _, sentence in sorted(candidates, key=lambda item: (-item[0], len(item[1]))):
        if sentence in selected:
            continue
        selected.append(sentence)
        if len(selected) >= max_items:
            break
    return selected


def _extract_tracked_article_emotional_cues(
    payload: Mapping[str, object],
    *,
    max_items: int = 3,
) -> list[str]:
    body_markdown = _as_clean_text(payload.get("body_markdown"))
    if not body_markdown:
        return []

    broad_scope = _has_broad_emotional_release_focus(payload)
    candidates: list[tuple[int, str]] = []
    for sentence in _split_text_sentences(body_markdown):
        normalized = re.sub(r"\s+", " ", sentence).strip(" -#>*")
        if not normalized:
            continue
        compact = re.sub(r"\s+", "", normalized)
        if any(marker in compact for marker in _SUPPORTIVE_LIFE_BASE_MARKERS):
            continue
        score = _score_tracked_article_emotional_cue(normalized, broad_scope=broad_scope)
        if score <= 0:
            continue
        candidates.append((score, _truncate_text(normalized, max_length=64)))

    selected: list[str] = []
    for _, sentence in sorted(candidates, key=lambda item: (-item[0], len(item[1]))):
        if sentence in selected:
            continue
        selected.append(sentence)
        if len(selected) >= max_items:
            break
    return selected


def _extract_tracked_article_everyday_warmth_cues(
    payload: Mapping[str, object],
    *,
    max_items: int = 3,
) -> list[str]:
    body_markdown = _as_clean_text(payload.get("body_markdown"))
    if not body_markdown:
        return []

    candidates: list[tuple[int, str]] = []
    for sentence in _split_text_sentences(body_markdown):
        normalized = re.sub(r"\s+", " ", sentence).strip(" -#>*")
        if not normalized:
            continue
        score = _score_tracked_article_everyday_warmth_cue(normalized)
        if score <= 0:
            continue
        candidates.append((score, _truncate_text(normalized, max_length=64)))

    selected: list[str] = []
    for _, sentence in sorted(candidates, key=lambda item: (-item[0], len(item[1]))):
        if sentence in selected:
            continue
        selected.append(sentence)
        if len(selected) >= max_items:
            break
    return selected


def _extract_tracked_article_resilience_cues(
    payload: Mapping[str, object],
    *,
    max_items: int = 3,
) -> list[str]:
    body_markdown = _as_clean_text(payload.get("body_markdown"))
    if not body_markdown:
        return []

    candidates: list[tuple[int, str]] = []
    for sentence in _split_text_sentences(body_markdown):
        normalized = re.sub(r"\s+", " ", sentence).strip(" -#>*")
        if not normalized:
            continue
        score = _score_tracked_article_resilience_cue(normalized)
        if score <= 0:
            continue
        candidates.append((score, _truncate_text(normalized, max_length=64)))

    selected: list[str] = []
    for _, sentence in sorted(candidates, key=lambda item: (-item[0], len(item[1]))):
        if sentence in selected:
            continue
        selected.append(sentence)
        if len(selected) >= max_items:
            break
    return selected


def _extract_tracked_article_relationship_aftercare_cues(
    payload: Mapping[str, object],
    *,
    max_items: int = 3,
) -> list[str]:
    body_markdown = _as_clean_text(payload.get("body_markdown"))
    if not body_markdown:
        return []

    candidates: list[tuple[int, str]] = []
    for sentence in _split_text_sentences(body_markdown):
        normalized = re.sub(r"\s+", " ", sentence).strip(" -#>*")
        if not normalized:
            continue
        score = _score_tracked_article_relationship_aftercare_cue(normalized)
        if score <= 0:
            continue
        candidates.append((score, _truncate_text(normalized, max_length=64)))

    selected: list[str] = []
    for _, sentence in sorted(candidates, key=lambda item: (-item[0], len(item[1]))):
        if sentence in selected:
            continue
        selected.append(sentence)
        if len(selected) >= max_items:
            break
    return selected


def _extract_tracked_article_topic_cues(
    payload: Mapping[str, object],
    *,
    max_items: int = 3,
) -> list[str]:
    if _has_relationship_aftercare_focus(payload):
        relationship_aftercare_cues = _extract_tracked_article_relationship_aftercare_cues(payload, max_items=max_items)
        if relationship_aftercare_cues:
            return relationship_aftercare_cues
    if _has_everyday_warmth_return_focus(payload):
        warmth_cues = _extract_tracked_article_everyday_warmth_cues(payload, max_items=max_items)
        if warmth_cues:
            return warmth_cues
    if _has_resilience_reconstruction_focus(payload):
        resilience_cues = _extract_tracked_article_resilience_cues(payload, max_items=max_items)
        if resilience_cues:
            return resilience_cues
    if _has_broad_emotional_release_focus(payload):
        emotional_cues = _extract_tracked_article_emotional_cues(payload, max_items=max_items)
        if emotional_cues:
            return emotional_cues
    return _extract_tracked_article_body_cues(payload, max_items=max_items)


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
            "不要把标题写成先给结论的空泛判断句，尽量先落到一个真实接口、后果或身体信号上。"
            "像体检改期、复查拖延、整个人越来越钝、连消息都不想回这类接口，比“人生遗憾”“生活失序”更适合放进标题。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是自我消耗、心绪整理或生活排序失衡，大纲不要自动改写成亲密关系冲突处理流程。"
            "即便出现他人，也只把他当成压力接口之一，不要让“深夜等回复 / 当晚说清楚 / 第二天再沟通”变成主线。"
            "优先把压力点落在身体提醒、生活排序、工作节奏、家人回应或自我照料被推迟的地方。"
            "不要把大纲写成通用讲解稿，答案也要落回一个真实接口、后果或身体信号。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是自我消耗、心绪整理或生活排序失衡，正文不要自动收窄成亲密关系摊牌、深夜删消息、等回复或关系修复主线。"
            "即便出现他人，也只把他当成压力接口之一，不要把伴侣/对话对象写成唯一主场景。"
            "后半篇不要长篇回顾关系前史，不要写成“深夜卡住 -> 回想过去 -> 第二天沟通 -> 关系缓和”的完整修复弧线。"
            "优先把代价写在身体提醒、生活排序、家人回应、工作节奏或自我照料被推迟的地方。"
            "不要先端出抽象人生答案，先把一个现实接口、后果或身体信号讲明白，再给判断和行动落点。"
            "开头不要写成“你有没有过这种阶段”“你以为自己只是累吗”“人啊，总是这样”这类先分类、先下定义再讲理的讲稿起手。"
            "前两段至少有一段只让现实接口、动作后果或身体反应自己说话，不要连续两段都在对“你”解释为什么会这样。"
            "如果情绪价值已经落在判断、后果或身体反应里，就直接推进，不必先补一段没有信息增量的氛围场景。"
        )
    return ""


def _build_tracked_article_emotional_release_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_broad_emotional_release_focus(payload):
        return ""

    if stage == "topic":
        return (
            "如果参考文章重心是放下强求、停止拉扯、珍惜已有或知足感，不要把选题收窄成某一段坏关系、某一次分手止损或单一亲密关系样本。"
            "正文里的关系例子、目标例子都只是共鸣入口之一，不能越权变成整篇唯一主轴。"
            "标题和切入角度优先围绕“人为什么总把幸福误认成继续争取”“人为什么总在失去后才看见拥有”“放手怎样腾出位置”这类更大的情绪命题重组。"
            "不要把题眼改写成沉没成本、输赢感、关系摊牌或感情诚意这类更窄的关系博弈词。"
            "如果原文同时举了关系和目标两个例子，新选题也要保留这种更大的普遍性，不要只抓其中一个例子单飞。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是放下强求、珍惜已有或知足感，大纲不要自动缩成坏关系止损手册或单一关系复盘。"
            "关系、目标、自我亏欠都可以作为例子出现，但主线必须回到“为什么人总把幸福误解成继续争取”这个更大的情绪命题。"
            "不要把整篇大纲压成“等回复 / 看聊天框 / 一段关系怎么收场”这类单一样本，至少要给关系之外的生活代价或已拥有部分留出段落职责。"
            "开头钩子不要只拿聊天框、消息提醒、对方回没回来做唯一现实接口；如果保留关系接口，至少并列一个关系之外的抓手，比如项目进度、睡眠、吃饭、身体信号或家里日常。"
            "前两段里至少有一段主职责必须落在关系之外的生活秩序、身体代价或已经拥有却被忽略的部分，不要把前半篇全部交给关系拉扯。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是放下强求、珍惜已有或知足感，正文不要自动收窄成坏关系止损、分手复盘或单一关系博弈。"
            "即便出现关系例子，也只把它当成共鸣入口之一，不要让它取代“放下强求 / 停止拉扯 / 珍惜已有”的真正主线。"
            "不要把幸福写成输赢、诚意、沉没成本或关系谈判问题；要把重点落回人为什么总在失去后才看见已经拥有的部分。"
            "不要把正文压成聊天框、等回复、试探态度这一类单一关系等待戏；如果用了关系例子，后文必须把代价写回睡眠、注意力、生活节奏、朋友家人或已经拥有却被忽略的部分。"
            "至少留一段专门写“人原本已经拥有、后来却在拉扯中慢慢忽略掉的东西”，不要从头到尾只盯着那段关系有没有结果。"
            "开头第一屏不要只剩消息框、对话框、回没回这类关系界面；如果保留关系接口，同段必须并列一个已经被挪走的现实抓手，比如睡眠、吃饭、工作判断、身体信号或家里日常。"
            "正文至少要有两段不以消息、回复、对方、关系这些词为主抓手，而是直接写生活秩序、身体代价和已经到手却被拿去垫付的安稳。"
        )
    return ""


def _build_tracked_article_everyday_warmth_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_everyday_warmth_return_focus(payload):
        return ""

    if stage == "topic":
        return (
            "如果参考文章重心是“大事祛魅”、日常陪伴回归和普通生活重新变重要，"
            "不要把选题收窄成身体告警、自我照料积压或单一复查拖延主线。"
            "也不要把题眼改写成“有人等你回应”“先把关系接住”或谁被排在回应顺序后面这类关系回应排序。"
            "不要把它再抽象成“女性要重建生活托底感”“意义供给退潮后怎么办”这类泛成长标题。"
            "不要写成“女人中年以后更需要重估哪些事”这类年龄阶段提问式抽象标题。"
            "文中的手术、停下来和休养只是价值转向的触发点，不是整篇唯一主命题。"
            "标题和切入角度优先围绕成就叙事为什么会祛魅、普通陪伴为什么反而最重要来重组；"
            "尽量把晚饭、回家、接孩子、陪父母、说晚安这类日常接口当成情绪证明，而不是把重点压回体检、复查和身体追债。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是“大事祛魅”和日常陪伴回归，大纲不要自动缩成身体提醒追债稿。"
            "手术、停下来和休养只能承担转折证据，主线必须回到：人为什么总把重要感押在更大的目标上，又为什么总要慢下来后才看见身边这些小事。"
            "中段至少留一段写普通陪伴和细小日常怎样托住生活，不要整篇都围着身体提醒转。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是“大事祛魅”和日常陪伴回归，正文不要把手术、休养或身体提醒写成唯一主轴。"
            "它们只是价值转向的触发点，真正要写的是：那些被高估的大事为什么会慢慢祛魅，普通陪伴和微小日常为什么反而最能托住一个人。"
            "开头可以直接点破这种误认，但需要留 1 到 2 个普通日常接口作情绪证明，比如一顿晚饭、一次接孩子、陪父母散步、说句晚安；不要把它们铺成大段场景。"
            "结尾回到一个很小的陪伴动作或日常决定上，不要又拐回身体告警、自我责备或万能祝福。"
        )
    return ""


def _build_tracked_article_resilience_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_resilience_reconstruction_focus(payload):
        return ""

    if stage == "topic":
        return (
            "如果参考文章重心是命运重击、长期疼痛、训练硬撑和不被定义后的重建，"
            "不要把选题改写成泛女性自我照顾、把自己排回前面或先学会照顾自己这类轻量自助主线。"
            "标题和切入角度优先围绕命运怎样把人逼到极限、训练怎样一点点重建身体与意志、一个人怎样拒绝被残缺或低谷定义来重组。"
            "不要把题眼压成提醒列表、待办顺位、谁先照顾谁或情绪兜底。"
            "像车祸、手术台、泳池里多划11下、肩伤背痛、不被定义这类抓手，比“先把自己放回前面”更接近原文真正的冲突。"
        )
    return ""


def _build_tracked_article_relationship_aftercare_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_relationship_aftercare_focus(payload):
        return ""

    if stage == "topic":
        return (
            "如果参考文章重心是争吵后的态度、冷暴力留下的后果和关系修复有没有人回来承担，"
            "不要把选题改写成泛内耗、自我稳住、生活排序失衡或抽象人生感悟。"
            "标题和切入角度优先围绕“吵完以后谁在善后”“冷暴力怎样磨掉安全感”“争执过后为什么总是没人回来修复”来重组。"
            "切入角度尽量用直述句，不要写成“不是……而是……”式对照句。"
            "可以把冷暴力、自己消化、回避修复、温柔以待、继续走下去这类接口当成题眼，不要把标题写成“这段关系已经在……”式整句判决，也不要把重点压回自我调节或单人心绪整理。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是争吵后的修复态度，大纲不要自动滑成自我疗愈稿、泛成长稿或“越稳住自己越累”的单人内耗主线。"
            "前半篇至少要守住一次争执后的空白、沉默或回避接口，中段必须顺着谁先沉默、谁先恢复正常、谁先把场面接回去往下推，让读者自己看见长期单人善后怎样慢慢磨掉关系里的安全感。"
            "结尾要回到关系有没有人回来承担、有没有人接住你的情绪，不要只给“先照顾好自己”的抽象答案。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是争吵后的修复态度，正文不要自动改写成泛内耗、自我扛住、单人稳情绪或生活排序失衡主线。"
            "重点要落在：吵完以后谁回来沟通、谁把情绪和日常接回去、冷暴力和回避修复怎样一点点磨掉安全感。"
            "少写“真正伤人的不是……”或“关系不是输在……而是输在……”这类整齐翻转句，让判断从谁先把话咽回去、谁先试探、谁装作没事这些动作里自己长出来。"
            "如果选题标题或切入角度本身还带着“不是……而是……”式对照句，正文标题、开头和中段判断都要主动改写，不要顺手沿用。"
            "可以保留 1 到 2 个日常接口，比如第二天照常上班、做饭、回消息，但这些接口只用来证明“善后长期落在一个人身上”，不要把主线改成自我照料提醒。"
            "结尾回到一个没被接住的动作、沉默或没等来的回应上，不要用“先把自己排回前面”这类泛自我成长结论收束。"
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
                "少写“先说结论”“接下来我们来看”“真正的问题是”这类结构路标。"
                "如果一句话太像现成金句，就拆回动作、场景或后果，不要单独抬成结论段。"
            )
        return "".join(
            [
                "删掉“说到底”“归根结底”“某种程度上”“很多时候”这类填充短语，让动作、事实和后果直接出现，不要先垫一个万能过渡再说正题。",
                "能写两项就不要硬凑三项并列；如果一句话里只是为了显得完整才排出三个近义判断，优先删掉最像装饰的那一项。",
                "不要用“有人说”“有人认为”“专家指出”“很多人都会”这类模糊归因替代具体处境，能落回人物动作、对话、时间节点和现实反馈时，就不要拿抽象权威兜底。",
                "不要频繁宣布写作动作，比如“先说结论”“接下来我们来看”“真正的问题是”“说句实话”；少解释你要怎么讲，多直接把事实和后果推上来。",
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
            "额外排查解释型公众号 AI 腔：不要写“答案先放这儿”“更麻烦的地方在这儿”“有一类……”这类讲解台词。"
            "不要频繁写“先说结论”“接下来我们来看”“真正的问题是”这类结构路标，也不要用“有人说”“专家指出”偷懒兜底。"
            "如果某处太像一次性写完的标准成稿，优先删总括、降结论、改成过程或普通动作。"
            + compact_signals
        )
    base = (
        "按中文公众号 AI 味风险检查表达："
        "套话风险，避免万能成长句、万能抒情和空泛金句；"
        "结构模板风险，避免整齐反转、教程分步、总括式泛感慨过渡句、单句敲钟段和标准答案式段落；"
        "句式节奏风险，避免同一种量词、连接词和判断句反复起手；"
        "段落节拍风险，避免“短句点一下 + 下一段长解释”反复交替，避免每段都解释到位；"
        "解释型公众号 AI 腔风险，避免“答案先放这儿”“更麻烦的地方在这儿”“有一类……”这类讲解台词，降低第二人称讲理密度；"
        "结构路标风险，避免“先说结论”“接下来我们来看”“真正的问题是”“说句实话”这类先宣布写作动作的路标句；"
        "模糊归因风险，避免“有人说”“有人认为”“专家指出”“很多人都会”这类泛泛权威和空归因；"
        "机制空心风险，不要只给情绪结论，要交代触发、反应和后续影响之间怎么连起来；"
        "抽象空话风险，把感受落到动作、物件、空间、声音和身体反应上；"
        "抽象机制标签风险，少抛“次序失衡”“自我亏欠”“长期透支”这类概念，改写成具体压力、代价和反应；"
        "过度解释风险，不要把每个判断都解释透，允许场景和停顿承载意思；"
        "标准讲理排布风险，不要每段都写成“判断 + 解释 + 小结”，段落长度和职责要有松紧；"
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
            "不要用“答案先放这儿”“更麻烦的地方在这儿”“你也不用”这类讲解台词。"
            "如果情绪价值已经在判断、后果或身体反应里，就直接推进，不要额外补一段没有信息增量的氛围场景。"
            "不要连续宣布观点，不要系统性补氛围场景，也不要机械扩句增肥。"
            "如果正文不是从场景起笔，就沿着判断、人物或案例入口继续推进，不必强行每段先铺画面。"
            "段落可以有长有短，但多数段落以 1 到 3 句为主；不要切成一排匀称小段，也不要把几层意思硬压成一个大长段。"
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
        "不要写成解释型公众号 AI 腔：开头不要“你以为……吗”，中段不要“答案先放这儿”“更麻烦的地方在这儿”，后段不要“你也不用把这理解成……”。"
        "降低第二人称讲理密度，能换成作者判断、局部事实或更短承接时，不要连续对“你”解释。"
        "开头如果已经有现实接口、后果或身体信号，就直接从那里推进，不要先用“你以为自己只是累吗”“有一类……”这类分类讲稿替读者总结。"
        "少抛“次序失衡”“自我亏欠”“长期透支”这类抽象机制标签，让压力、代价和身体反应自己说明问题。"
        "如果情绪价值已经落在判断、动作后果或身体反应里，就不要额外补大段没有信息增量的氛围场景。"
        "不要每段都写成“判断 + 解释 + 小结”，也不要让 8 到 14 个中长段看起来像同一套讲理模板。"
        "多数段落以 1 到 3 句为主；如果一段里同时塞了现象、解释、转折和落点，优先拆开，不要压成一整块。"
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
        "只有在全文真的被切成很多同职责匀称小段时，才合并相邻段落；不要为了反模板，把现象、动作、解释和后果全压进一个大长段。"
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
            "多数段落以 1 到 3 句为主；如果一段里已经塞了现象、解释、转折和落点，就主动拆开。"
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
        "多数段落以 1 到 3 句为主；如果单段同时塞了现象、动作、局部解释和后续影响，就主动拆开。"
        "如果正文已经被切成太多同职责匀称小段，才合并相邻段落；不要为了反模板，把半页内容压成一个大长段。"
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


def _normalize_clarified_problem(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    normalized = re.sub(r"^(这篇文章|这篇稿子)要解释[，,:：]?\s*", "", normalized)
    return normalized.strip()


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

    clarified_problem = _normalize_clarified_problem(_as_clean_text(problem_brief.get("clarified_problem")))
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
    if structure_mode == "pressure_interface_direct":
        return (
            "压力接口直推",
            "先压住一个已经开始出代价的现实接口或身体提醒，再沿着触发、当场反应和后续影响推进，不先抛终局判断，也不补万能答案。",
        )
    if structure_mode == "single_window_scene":
        return (
            "单场景窄时窗推进",
            "前半篇尽量守住同一段时间和同一处境现场，不要均匀拆成几个并列观点段。",
        )
    if structure_mode == "emotional_engine_direct":
        return (
            "情绪发动机直接推进",
            "先抽出终局感、亏欠感、失去后的反省和价值赦免，再展开判断与现实答案；默认不铺生活场景。",
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
    if structure_mode == "pressure_interface_direct":
        if stage == "outline":
            return (
                "若策略包要求压力接口直推，大纲先压住一个已经开始出代价的现实接口或身体提醒，"
                "再顺着触发、当场反应和后续影响往前推。"
                "不要先把问题抬成终局感、价值赦免或整篇总论。"
            )
        if stage == "draft":
            return (
                "若策略包要求压力接口直推，正文第一屏先给一个真实接口、后果或身体提醒，"
                "不要先抛终局问题、反常识判断或价值赦免。"
                "中段围绕哪件事先被往后放、当时怎么处理、后来又留下什么代价推进；"
                "判断尽量压回事实和反应里，不要排成成熟讲解稿。"
            )
    if structure_mode == "relationship_aftercare":
        if stage == "outline":
            return (
                "若策略包要求争吵后善后推进，大纲先守住一次争执后的空白、沉默或回避接口，"
                "再顺着谁先把话咽回去、谁先恢复正常、谁先把场面接回去往下推，让安全感变薄这件事从动作里自己显出来。"
                "不要把大纲改写成泛自我成长稿，也不要写成两边都有道理的平均讲解稿。"
            )
        if stage == "draft":
            return (
                "若策略包要求争吵后善后推进，正文第一屏先落一个吵完之后还得照常把日子接回去的小接口，"
                "不要先抽象讲“爱不爱”或“成熟关系”。"
                "中段围绕谁先把话咽回去、谁先恢复正常、谁先试探气氛、谁在善后推进；"
                "少写“真正伤人的不是……”这类整齐翻转句，让判断从动作里自己显出来；"
                "结尾只收在一个没被接住的动作、沉默或回应上，不要写成泛自我疗愈答案。"
            )
    if structure_mode == "emotional_engine_direct":
        if stage == "outline":
            return (
                "若策略包要求情绪发动机直接推进，大纲默认不规划场景段，"
                "先拆终局感、亏欠感、失去后的反省、被允许的松绑和现实答案。"
                "需要例证时只保留一句事实或引用，并并入判断段；不展开动作、物件、环境和氛围描写，也不单独保留动作残留段。"
            )
        if stage == "draft":
            return (
                "若策略包要求情绪发动机直接推进，正文不要用生活场景冷启动，"
                "第一屏先给终局问题、反常识判断、情绪命名或价值赦免。"
                "中段围绕亏欠自己、失去后才懂得拥有、被允许松绑这些情绪机制推进；"
                "需要例证时只保留一句事实或引用，并并入判断段；不展开动作、物件、环境和氛围描写，也不单独保留动作残留段。"
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
    if bool(payload.get("timeout_recovery_mode")):
        return True
    if is_polish_mode:
        return bool(payload.get("compact_polish_mode"))
    return bool(payload.get("compact_strategy_mode"))


def _is_timeout_recovery_draft_mode(payload: Mapping[str, object], *, is_polish_mode: bool) -> bool:
    if is_polish_mode:
        return False
    return bool(payload.get("timeout_recovery_mode"))


def _build_timeout_recovery_draft_instructions(payload: Mapping[str, object]) -> str:
    if not bool(payload.get("timeout_recovery_mode")):
        return ""
    return (
        "当前任务处于草稿超时救援模式。"
        "请只抓住现有选题、大纲锚点和参考文章里的核心冲突，先写出一版能成立的正文，不要补全所有层次。"
        "优先保留情绪价值和现实接口，直接进入真正卡人的那一下，不要先铺一段没有信息增量的氛围场景。"
        "不要写成模板鸡汤，不要用“不是A，而是B”或“不是A，只是B”的对称判断句反复搭骨架。"
        "不要为了显得完整主动补双线并跑、多人物并列、标准答案式三段论或祝福式收尾。"
        "如果主题本来是放下强求、珍惜已有、停止拉扯，就继续守住这个更大的情绪命题，不要缩成单一坏关系复盘。"
        "如果主题本来是自我消耗、生活排序、身体提醒，就把代价写回身体、节奏、家人回应或已经被挪走的日常，不要拐去关系摊牌。"
        "正文宁可少一点，也要像真人在推进一篇有感受、有判断、有现实摩擦的稿子。"
    )


def build_outline_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    raw_tone_profile = payload.get("tone_profile")
    tone_profile = (
        _build_effective_tone_profile(raw_tone_profile, payload=payload)
        if isinstance(raw_tone_profile, Mapping)
        else None
    )
    style_section = render_tone_profile_section(tone_profile)
    preset_stage_instructions = _build_jinwan_youyu_stage_instructions(
        stage="outline",
        tone_profile=tone_profile,
        payload=payload,
    )
    pressure_topic_tweak = _build_jinwan_youyu_pressure_topic_tweak(stage="outline", payload=payload)
    content_skill_instructions = build_content_skill_instructions(stage="outline")
    target_wording = _render_outline_target_wording(tone_profile)
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
    emotional_release_guard_instructions = _build_tracked_article_emotional_release_guard_instructions(payload, stage="outline")
    everyday_warmth_guard_instructions = _build_tracked_article_everyday_warmth_guard_instructions(
        payload, stage="outline"
    )
    relationship_aftercare_guard_instructions = _build_tracked_article_relationship_aftercare_guard_instructions(payload, stage="outline")
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="内容策划编辑",
            task_brief="请基于给定选题，输出一个适合女性情感成长公众号的文章大纲。",
            domain_pack=payload.get("domain_pack"),
        )
        + preset_stage_instructions
        + pressure_topic_tweak
        + content_skill_instructions
        + original_expression_instructions
        + humanizer_zh_review_instructions
        + "大纲只写段落职责和推进动作，不要把任何一段提前扩写成完整正文；每段尽量控制在 1 行。"
        + pressure_guard_instructions
        + emotional_release_guard_instructions
        + everyday_warmth_guard_instructions
        + relationship_aftercare_guard_instructions
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
    raw_tone_profile = payload.get("tone_profile")
    tone_profile = (
        _build_effective_tone_profile(raw_tone_profile, payload=payload)
        if isinstance(raw_tone_profile, Mapping)
        else None
    )
    style_section = render_tone_profile_section(tone_profile)
    preset_stage_instructions = _build_jinwan_youyu_stage_instructions(
        stage="topic",
        tone_profile=tone_profile,
        payload=payload,
    )
    pressure_topic_tweak = _build_jinwan_youyu_pressure_topic_tweak(stage="topic", payload=payload)
    content_skill_instructions = build_content_skill_instructions(stage="topic")
    pressure_guard_instructions = _build_tracked_article_pressure_guard_instructions(payload, stage="topic")
    emotional_release_guard_instructions = _build_tracked_article_emotional_release_guard_instructions(payload, stage="topic")
    everyday_warmth_guard_instructions = _build_tracked_article_everyday_warmth_guard_instructions(
        payload, stage="topic"
    )
    resilience_guard_instructions = _build_tracked_article_resilience_guard_instructions(payload, stage="topic")
    relationship_aftercare_guard_instructions = _build_tracked_article_relationship_aftercare_guard_instructions(payload, stage="topic")
    if source_type == "tracked_article":
        body_cues = _extract_tracked_article_topic_cues(payload)
        body_cue_section = ""
        if body_cues:
            cue_lines = "\n".join(f"- {cue}" for cue in body_cues)
            body_cue_section = (
                "参考文章正文抓手候选：\n"
                f"{cue_lines}\n"
                "优先围绕这些现实接口、身体提醒或代价线索重组新选题，不要再把它们抹平成抽象人生判断。\n"
            )
        source_prompt = (
            f"来源类型：{source_type}\n"
            f"参考文章 slug：{payload['source_ref_slug']}\n"
            f"参考文章标题：{payload['article_title']}\n"
            f"作者：{payload['author']}\n"
            f"来源账号：{payload['source_name'] or '未知公众号'}\n"
            f"摘要：{payload['summary']}\n"
            f"结构备注：{payload['structure_notes']}\n"
            f"标签：{' / '.join(payload.get('tags') or []) or '无'}\n"
            f"{body_cue_section}"
        )
        instructions = (
            build_stage_instructions(
                role="选题编辑",
                task_brief="请基于参考文章提炼出一个可直接立项的女性情感成长类原创选题。",
                domain_pack=payload.get("domain_pack"),
            )
            + preset_stage_instructions
            + pressure_topic_tweak
            + content_skill_instructions
            + "不要复述原标题，要重新组织成更适合继续创作的选题。"
            + "不要使用“不是A，而是B”或“不是A，只是B”这类对称判断句做选题标题。"
            + "不要把参考文章里的高频词直接放进标题主干，要改成新的具体处境、动作或情绪入口。"
            + "不要沿用参考文章默认的矛盾顺序或段落重心，要重新换一个更适合继续原创扩写的组织焦点。"
            + "标题和切入角度至少要同时改掉原标题骨架、观察视角和情绪推进顺序中的两项。"
            + "切入角度只写 1 句话，控制在 40 到 80 个汉字，不要扩成整段方案说明。"
            + "如果参考文章正文里已经出现可用的现实接口、身体提醒、延迟代价或被反复往后放的动作，优先拿这些抓手重新组织选题，不要只围着摘要里的大道理换说法。"
            + pressure_guard_instructions
            + emotional_release_guard_instructions
            + everyday_warmth_guard_instructions
            + resilience_guard_instructions
            + relationship_aftercare_guard_instructions
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
            + preset_stage_instructions
            + content_skill_instructions
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
    raw_polish_instruction = _as_clean_text(payload.get("polish_instruction"))
    current_draft = payload.get("draft")
    is_polish_mode = bool(raw_polish_instruction and isinstance(current_draft, Mapping))
    timeout_recovery_mode = _is_timeout_recovery_draft_mode(payload, is_polish_mode=is_polish_mode)
    compact_strategy_mode = _should_use_compact_strategy_draft_mode(
        payload,
        is_polish_mode=is_polish_mode,
    )
    raw_tone_profile = payload.get("tone_profile")
    tone_profile = (
        _build_effective_tone_profile(raw_tone_profile, payload=payload)
        if isinstance(raw_tone_profile, Mapping)
        else None
    )
    polish_instruction = _harmonize_polish_instruction_for_effective_tone_profile(
        raw_polish_instruction,
        tone_profile=tone_profile,
        payload=payload,
    )
    style_section = render_tone_profile_section(tone_profile)
    preset_stage_instructions = (
        ""
        if timeout_recovery_mode
        else _build_jinwan_youyu_stage_instructions(
            stage="draft",
            tone_profile=tone_profile,
            payload=payload,
        )
    )
    pressure_topic_tweak = _build_jinwan_youyu_pressure_topic_tweak(stage="draft", payload=payload)
    content_skill_instructions = "" if timeout_recovery_mode else build_content_skill_instructions(stage="draft")
    target_wording = _render_draft_target_wording(tone_profile)
    reference_article_section = (
        ""
        if _has_strategy_package(payload)
        else _render_reference_article_section(payload, stage="draft")
    )
    post_strategy_reference_boundary = _render_post_strategy_reference_boundary(payload, stage="draft")
    strategy_package_section = (
        ""
        if timeout_recovery_mode
        else _render_strategy_package_section(payload, compact=compact_strategy_mode)
    )
    reference_article_instructions = (
        ""
        if timeout_recovery_mode
        else _build_reference_article_instructions(stage="draft")
    )
    original_expression_instructions = (
        ""
        if timeout_recovery_mode
        else _build_original_expression_instructions(
            stage="draft",
            compact=compact_strategy_mode,
        )
    )
    humanizer_zh_review_instructions = (
        ""
        if timeout_recovery_mode
        else _build_humanizer_zh_review_instructions(
            stage="draft",
            compact=compact_strategy_mode and not is_polish_mode,
        )
    )
    ai_flavor_risk_instructions = (
        ""
        if timeout_recovery_mode
        else _build_localized_ai_flavor_risk_instructions(
            compact=compact_strategy_mode and not is_polish_mode
        )
    )
    wechat_public_account_instructions = (
        ""
        if timeout_recovery_mode
        else _build_wechat_public_account_draft_instructions(
            compact=compact_strategy_mode
        )
    )
    timeout_recovery_instructions = _build_timeout_recovery_draft_instructions(payload)
    pressure_guard_instructions = _build_tracked_article_pressure_guard_instructions(payload, stage="draft")
    emotional_release_guard_instructions = _build_tracked_article_emotional_release_guard_instructions(payload, stage="draft")
    everyday_warmth_guard_instructions = _build_tracked_article_everyday_warmth_guard_instructions(
        payload, stage="draft"
    )
    relationship_aftercare_guard_instructions = _build_tracked_article_relationship_aftercare_guard_instructions(payload, stage="draft")
    structure_mode_instructions = (
        ""
        if timeout_recovery_mode
        else _build_structure_mode_instructions(payload, stage="draft")
    )
    recomposition_recipe_instructions = (
        ""
        if timeout_recovery_mode
        else _build_recomposition_recipe_instructions(payload, stage="draft")
    )
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
    if timeout_recovery_mode:
        task_brief = (
            "请基于当前选题、大纲和参考文章核心冲突，快速写出一版可用初稿。"
            "先保住主题、情绪力度和现实抓手，不追求把每一层都写满。"
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
        + preset_stage_instructions
        + pressure_topic_tweak
        + content_skill_instructions
        + timeout_recovery_instructions
        + original_expression_instructions
        + humanizer_zh_review_instructions
        + ai_flavor_risk_instructions
        + wechat_public_account_instructions
        + pressure_guard_instructions
        + emotional_release_guard_instructions
        + everyday_warmth_guard_instructions
        + relationship_aftercare_guard_instructions
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
    raw_tone_profile = payload.get("tone_profile")
    tone_profile = (
        _build_effective_tone_profile(raw_tone_profile, payload=payload)
        if isinstance(raw_tone_profile, Mapping)
        else None
    )
    style_section = render_tone_profile_section(tone_profile)
    preset_stage_instructions = _build_jinwan_youyu_stage_instructions(
        stage="assets",
        tone_profile=tone_profile,
        payload=payload,
    )
    pressure_topic_tweak = _build_jinwan_youyu_pressure_topic_tweak(stage="assets", payload=payload)
    content_skill_instructions = build_content_skill_instructions(stage="assets")
    dbskill_assets_instructions = "".join(get_dbskill_rule_lines("assets", "extra_instructions"))
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
        + preset_stage_instructions
        + pressure_topic_tweak
        + content_skill_instructions
        + dbskill_assets_instructions
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
    raw_tone_profile = payload.get("tone_profile")
    tone_profile = (
        _build_effective_tone_profile(raw_tone_profile, payload=payload)
        if isinstance(raw_tone_profile, Mapping)
        else None
    )
    style_section = render_tone_profile_section(tone_profile)
    preset_stage_instructions = _build_jinwan_youyu_stage_instructions(
        stage="publish_package",
        tone_profile=tone_profile,
        payload=payload,
    )
    pressure_topic_tweak = _build_jinwan_youyu_pressure_topic_tweak(stage="publish_package", payload=payload)
    content_skill_instructions = build_content_skill_instructions(stage="publish_package")
    dbskill_publish_instructions = "".join(get_dbskill_rule_lines("publish_package", "extra_instructions"))
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
        )
        + preset_stage_instructions
        + pressure_topic_tweak
        + content_skill_instructions
        + dbskill_publish_instructions,
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
