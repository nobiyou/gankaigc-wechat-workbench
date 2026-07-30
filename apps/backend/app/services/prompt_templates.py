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
        objective="围绕正文生成标题组选项、封面文案、配图提示词和分发导语候选。",
        output_fields=["title_options", "recommended_title", "cover_prompt", "cover_copy", "social_teaser", "social_teaser_options"],
        supports_tone_profile=True,
        supports_domain_pack=True,
        supports_review_feedback=True,
    ),
    PromptTemplateDescriptor(
        key="cover_image",
        label="封面图生成",
        role="图片生成器",
        objective="根据封面提示词生成 16:9 横版封面图。",
        output_fields=["image/png"],
        supports_tone_profile=False,
        supports_domain_pack=False,
        supports_review_feedback=False,
    ),
    PromptTemplateDescriptor(
        key="publish_package",
        label="发布包生成",
        role="发布编辑",
        objective="基于正文与素材输出摘要、最终发布标题、导语、标签和编辑备注。",
        output_fields=["abstract", "publish_title", "publish_lead", "intro_options", "tags", "editor_note"],
        supports_tone_profile=True,
        supports_domain_pack=True,
        supports_review_feedback=True,
    ),
]


def _as_clean_text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


_RESPONSIBILITY_SHELTER_PROMPT_REPLACEMENTS = (
    ("撑不撑得住", "怎样把顺序理清"),
    ("撑不住", "想歇一歇"),
    ("长期扛压", "长期把家里的事放在心上"),
    ("扛住压力", "先把事情接住"),
    ("一路忍着、扛着", "一步步安排、一件件接住"),
    ("忍着、扛着", "安排着、接住着"),
    ("成年人扛着的那些压力", "成年人放在心上的那些责任"),
    ("真正扛着压力往前走", "把责任放在心上认真往前走"),
    ("扛着压力", "带着责任"),
    ("白天扛事晚上崩一下", "白天把事情理顺、晚上才松一口气"),
    ("扛事", "接事"),
    ("长期在家庭里当支柱", "长期把家里的事放在心上"),
    ("天生坚强", "没有自己的难处"),
    ("崩一下", "松一口气"),
    ("这些辛苦没有白扛", "这些认真没有白费"),
    ("辛苦没有白扛", "认真没有白费"),
    ("辛苦未必值得歌颂，但也没有白扛", "这些认真不必夸大，也没有白费"),
    ("辛苦未必值得歌颂", "这些认真不必夸大"),
    ("苦情赞歌", "吃苦叙事"),
    ("没有白扛", "没有白忙"),
    ("没白扛", "没有白忙"),
    ("白扛", "白忙"),
    ("暂时不能倒", "还要先把事情理顺"),
    ("不能倒下", "还要把顺序理清"),
    ("不能倒", "还要把顺序理清"),
    ("这么苦还要撑", "这么不容易还要把家里理顺"),
    ("吞下去的辛苦", "一路走来的认真"),
    ("把慌乱咽下去", "把顺序理清楚"),
    ("身体报警", "身体提醒"),
    ("身体告警", "身体提醒"),
    ("那句“有我”", "那份先把家里稳住的责任"),
    ("那句有我", "那份先把家里稳住的责任"),
    ("有我", "先稳住"),
    ("先稳住场面", "先把家里理顺"),
    ("喉咙发紧", "心里开始排顺序"),
    ("却还得继续撑住", "也要先让家里稳下来"),
    ("继续撑下去", "继续认真往前走"),
    ("撑下去", "继续往前走"),
    ("硬扛压力", "认真托住家里的事"),
    ("硬扛", "先把事情接住"),
    ("长期硬撑", "长时间不容易"),
    ("夜里硬撑", "夜里不容易"),
    ("硬撑", "认真托住日子"),
    ("多能扛", "多厉害"),
    ("不是天生能把事情接住，而是很多责任都赶在同一段日子里压了上来", "很多责任常常赶在同一段日子里压上来，你就习惯先把顺序理清"),
    ("不是天生能扛，而是很多责任都赶在同一段日子里压了上来", "很多责任常常赶在同一段日子里压上来，你就习惯先把顺序理清"),
    ("不是天生能把事情接住", "很多责任常常赶在同一段日子里压上来"),
    ("不是天生能扛", "很多责任常常赶在同一段日子里压上来"),
    ("能扛", "能把事情接住"),
    ("强撑", "先把事情稳住"),
    ("或倒下", "或停下"),
    ("倒下", "停下"),
    ("沉默疲惫", "不张扬的责任感"),
    ("长期疲惫、委屈、想停下却不敢停的内在消耗", "现实责任和自己也需要被照顾之间的拉扯"),
    ("长期疲惫", "长时间不容易"),
    ("疲惫", "不容易"),
    ("内在消耗", "心里的不容易"),
    ("孤撑感", "被理解的责任感"),
    ("孤立无援", "有人一起分担"),
    ("苦难必有回报", "认真走过的日子会慢慢有回响"),
    ("苦难勋章", "日子回响"),
    ("苦难赞歌", "空泛吃苦叙事"),
    ("苦难", "难处"),
    ("苦水", "不容易"),
    ("风浪", "忙乱"),
    ("白熬", "白费"),
    ("苦熬", "认真走过"),
    ("一句“先把家里理顺”背后那点心里开始排顺序、也要先让家里稳下来的当场", "家里临时有事时，自己先把顺序理清、让所有人安心的当场"),
    ("账单", "现实开销"),
    ("补习费用", "孩子的安排"),
    ("缴费窗口", "办事窗口"),
    ("这个月的绩效", "手头的工作考核"),
    ("这个月的", "眼下这段时间的"),
    ("万般辛苦", "那些认真托住日子的时刻"),
    ("人间安稳", "家里的踏实"),
    ("回到家那一刻", "推门听见回应时"),
    ("有人在门口等你", "有人还在惦记你"),
    ("小安稳", "细小踏实"),
)


def _sanitize_responsibility_shelter_prompt_text(value: object) -> str:
    sanitized = re.sub(r"\s+", " ", _as_clean_text(value)).strip()
    for source, replacement in sorted(
        _RESPONSIBILITY_SHELTER_PROMPT_REPLACEMENTS,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        sanitized = sanitized.replace(source, replacement)
    return sanitized.strip()


def _sanitize_responsibility_shelter_analysis_contract(
    contract: "TrackedArticleAnalysisContract",
) -> "TrackedArticleAnalysisContract":
    return TrackedArticleAnalysisContract(
        theme=_sanitize_responsibility_shelter_prompt_text(contract.theme),
        core_conflict=_sanitize_responsibility_shelter_prompt_text(contract.core_conflict),
        emotional_exit=_sanitize_responsibility_shelter_prompt_text(contract.emotional_exit),
        opening_pattern=_sanitize_responsibility_shelter_prompt_text(contract.opening_pattern),
        hook_trigger=_sanitize_responsibility_shelter_prompt_text(contract.hook_trigger),
        progression_drive=_sanitize_responsibility_shelter_prompt_text(contract.progression_drive),
        share_reason=_sanitize_responsibility_shelter_prompt_text(contract.share_reason),
        do_not_turn_into=_sanitize_responsibility_shelter_prompt_text(contract.do_not_turn_into),
        structure_mode=contract.structure_mode,
    )


@dataclass(frozen=True)
class TrackedArticleAnalysisContract:
    theme: str = ""
    core_conflict: str = ""
    emotional_exit: str = ""
    opening_pattern: str = ""
    hook_trigger: str = ""
    progression_drive: str = ""
    share_reason: str = ""
    do_not_turn_into: str = ""
    structure_mode: str = ""


def _normalize_analysis_contract_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \n\t。；;，,")


def _strip_analysis_leadin(text: str) -> str:
    normalized = _normalize_analysis_contract_text(text)
    if not normalized:
        return ""
    prefixes = (
        "这篇文章真正想讨论的是：",
        "这篇文章真正讨论的是：",
        "这篇文章真正想谈的是：",
        "这篇文章想谈的是：",
        "文章真正想讨论的是：",
        "文章真正讨论的是：",
        "文章真正想谈的是：",
        "文章重点不是：",
        "文章重点是：",
        "主线是",
    )
    for prefix in prefixes:
        if normalized.startswith(prefix):
            stripped = normalized[len(prefix) :].lstrip("：:，, ")
            return stripped or normalized
    return normalized


def _build_tracked_article_analysis_contract(payload: Mapping[str, object]) -> TrackedArticleAnalysisContract:
    contract = TrackedArticleAnalysisContract(
        theme=_normalize_analysis_contract_text(
            _as_clean_text(payload.get("analysis_theme") or payload.get("reference_article_analysis_theme"))
        ),
        core_conflict=_normalize_analysis_contract_text(
            _as_clean_text(payload.get("analysis_core_conflict") or payload.get("reference_article_analysis_core_conflict"))
        ),
        emotional_exit=_normalize_analysis_contract_text(
            _as_clean_text(payload.get("analysis_emotional_exit") or payload.get("reference_article_analysis_emotional_exit"))
        ),
        opening_pattern=_normalize_analysis_contract_text(
            _as_clean_text(payload.get("analysis_opening_pattern") or payload.get("reference_article_analysis_opening_pattern"))
        ),
        hook_trigger=_normalize_analysis_contract_text(
            _as_clean_text(payload.get("analysis_hook_trigger") or payload.get("reference_article_analysis_hook_trigger"))
        ),
        progression_drive=_normalize_analysis_contract_text(
            _as_clean_text(
                payload.get("analysis_progression_drive") or payload.get("reference_article_analysis_progression_drive")
            )
        ),
        share_reason=_normalize_analysis_contract_text(
            _as_clean_text(payload.get("analysis_share_reason") or payload.get("reference_article_analysis_share_reason"))
        ),
        do_not_turn_into=_normalize_analysis_contract_text(
            _as_clean_text(payload.get("analysis_do_not_turn_into") or payload.get("reference_article_analysis_do_not_turn_into"))
        ),
        structure_mode=_normalize_analysis_contract_text(
            _as_clean_text(payload.get("analysis_structure_mode") or payload.get("reference_article_analysis_structure_mode"))
        ),
    )
    if _has_everyday_warmth_responsibility_shelter_focus(payload):
        return _sanitize_responsibility_shelter_analysis_contract(contract)
    return contract


def _build_analysis_first_topic_summary(contract: TrackedArticleAnalysisContract) -> str:
    parts: list[str] = []
    theme = _strip_analysis_leadin(contract.theme)
    core_conflict = _strip_analysis_leadin(contract.core_conflict)
    emotional_exit = _strip_analysis_leadin(contract.emotional_exit)
    share_reason = _strip_analysis_leadin(contract.share_reason)
    if theme:
        parts.append(f"文章真正要谈的是：{theme}。")
    if core_conflict:
        parts.append(f"真正卡人的那层矛盾是：{core_conflict}。")
    if emotional_exit:
        parts.append(f"最后要把人带回：{emotional_exit}。")
    if share_reason:
        parts.append(f"它之所以容易让人想转发，是因为：{share_reason}。")
    return "".join(parts)


def _build_analysis_first_topic_structure_notes(contract: TrackedArticleAnalysisContract) -> str:
    parts: list[str] = []
    opening_pattern = _strip_analysis_leadin(contract.opening_pattern)
    hook_trigger = _strip_analysis_leadin(contract.hook_trigger)
    core_conflict = _strip_analysis_leadin(contract.core_conflict)
    progression_drive = _strip_analysis_leadin(contract.progression_drive)
    emotional_exit = _strip_analysis_leadin(contract.emotional_exit)
    do_not_turn_into = _strip_analysis_leadin(contract.do_not_turn_into)
    if opening_pattern:
        parts.append(f"先按这个起笔方式进入：{opening_pattern}。")
    if hook_trigger:
        parts.append(f"开头第一下先让读者停在：{hook_trigger}。")
    if core_conflict:
        parts.append(f"中段重点拆开：{core_conflict}。")
    if progression_drive:
        parts.append(f"中段主要靠这股力往前推：{progression_drive}。")
    if emotional_exit:
        parts.append(f"结尾回到：{emotional_exit}。")
    if do_not_turn_into:
        parts.append(f"全程不要写成：{do_not_turn_into}。")
    return "".join(parts)


def _build_analysis_first_topic_body_cue_section(contract: TrackedArticleAnalysisContract) -> str:
    cue_lines: list[str] = []
    opening_pattern = _strip_analysis_leadin(contract.opening_pattern)
    hook_trigger = _strip_analysis_leadin(contract.hook_trigger)
    theme = _strip_analysis_leadin(contract.theme)
    core_conflict = _strip_analysis_leadin(contract.core_conflict)
    progression_drive = _strip_analysis_leadin(contract.progression_drive)
    emotional_exit = _strip_analysis_leadin(contract.emotional_exit)
    share_reason = _strip_analysis_leadin(contract.share_reason)
    do_not_turn_into = _strip_analysis_leadin(contract.do_not_turn_into)
    if opening_pattern:
        cue_lines.append(f"- 起笔入口：{opening_pattern}")
    if hook_trigger:
        cue_lines.append(f"- 开头触发点：{hook_trigger}")
    if theme:
        cue_lines.append(f"- 主题主线：{theme}")
    if core_conflict:
        cue_lines.append(f"- 真正矛盾：{core_conflict}")
    if progression_drive:
        cue_lines.append(f"- 中段推进力：{progression_drive}")
    if emotional_exit:
        cue_lines.append(f"- 情绪出口：{emotional_exit}")
    if share_reason:
        cue_lines.append(f"- 容易被转发的原因：{share_reason}")
    if do_not_turn_into:
        cue_lines.append(f"- 跑偏提醒：{do_not_turn_into}")
    if not cue_lines:
        return ""
    return (
        "参考文章分析抓手候选：\n"
        + "\n".join(cue_lines)
        + "\n优先围绕这些分析结论重组新选题，不要因为结构模式相近，就回收另一篇更顺手的旧骨架。\n"
    )


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
    "复查",
    "疲惫",
    "紧绷",
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
    "不借",
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
    "要是他还在",
    "他还在就好了",
    "没说完的话",
    "没兑现的承诺",
    "没被接住",
    "未完成",
    "回潮",
    "意难平",
    "感谢相遇",
    "不谈亏欠",
    "允许一切发生",
    "允许一切结束",
    "接纳离开",
    "接纳结束",
    "关系结束",
    "离别",
    "过客",
    "聚散终有时",
    "相遇",
    "退场",
    "最好的祝福",
    "变成了你自己",
    "整理行囊",
    "未知的山海",
)
_SELF_RELIANCE_INWARD_SUPPORT_KEYWORDS = (
    "向内求",
    "向外求",
    "自救",
    "自渡",
    "靠自己",
    "自己熬过",
    "自扫门前雪",
    "自我疗愈",
    "自我修复",
    "自我支撑",
    "自我托住",
    "自己扛",
    "自己撑",
    "自己稳住",
    "自己向上爬",
    "收起委屈",
    "藏好失望",
    "不再向别人哭诉",
    "不再向别人索求",
    "默默承受",
    "默默向内求",
    "求自身的冷静",
    "求自身的沉淀",
    "求自身的成长",
    "不再逢人就提",
    "不再哭诉",
    "外求未必可靠",
    "别人也都在负重前行",
    "每个人都得自扫门前雪",
    "等待救赎",
    "靠不到",
    "靠不住",
    "足以扛事儿",
    "自救自渡",
)
_SELF_RELIANCE_INWARD_SUPPORT_THESIS_MARKERS = (
    "只有向内求",
    "只有靠自己",
    "即使没有帮助",
    "也要学会自救自渡",
    "不是把哭声调成静音",
    "最累最难的时候可以忍住不哭",
    "别人再好再强大",
    "终有靠不到",
    "终有靠不住",
    "自己也有能力",
    "试着向上爬",
    "能够自救自渡",
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
    "只适合收藏",
    "带着遗憾往前走",
    "不会自动沉下去",
    "感谢相遇",
    "不谈亏欠",
    "允许一切发生",
    "允许一切结束",
    "接纳离开",
    "接纳结束",
    "聚散终有时",
    "最好的祝福",
)
_BROAD_EMOTIONAL_RELEASE_EXAMPLE_PREFIXES = (
    "你有没有过这样的时刻",
    "明明一段关系",
    "明明一个目标",
)
_INNER_SETTLEMENT_REFERENCE_KEYWORDS = (
    "心安",
    "安顿",
    "归处",
    "淡定",
    "从容",
    "内心",
    "内在的心安",
    "与内心和解",
    "此心安处",
    "心有归处",
    "心无挂碍",
    "把心放平",
    "把事看淡",
    "不骄不躁",
    "静待花开",
    "一餐一饮",
    "一呼一吸",
    "安顿灵魂",
    "心平",
    "心若不安",
    "心若不定",
    "不生执念",
    "心中澄明",
)
_INNER_SETTLEMENT_THESIS_MARKERS = (
    "此心安处是吾乡",
    "心安，则事顺",
    "心平，则气和",
    "心有归处",
    "心无挂碍",
    "真正的心安",
    "内在的心安",
    "与内心和解",
    "把心放平",
    "把事看淡",
    "不骄不躁",
    "静待花开",
)
_INNER_SETTLEMENT_DAILY_GROUNDING_KEYWORDS = (
    "一餐一饮",
    "一呼一吸",
    "岁岁年年",
    "安顿灵魂",
    "与内心相拥",
)
_INNER_SETTLEMENT_DAILY_RETURN_KEYWORDS = (
    "回到当下",
    "回到日常",
    "继续生活",
    "继续往前",
    "今天",
    "眼前的生活",
    "日常",
    "回稳",
    "落地",
    "放平",
    "归位",
    "重新有了轻重",
    "安顿自己",
    "安放回当下",
    "住回日子里",
    "有归处",
    "有地方放",
)
_INNER_SETTLEMENT_STAGE_RESTART_KEYWORDS = (
    "上半年",
    "下半年",
    "半年",
    "年中",
    "阶段节点",
    "阶段回望",
    "阶段误判",
    "年中清单",
    "清单",
    "这一年过半",
    "年初定下的目标",
    "目标又实现了多少",
    "事与愿违",
    "另有安排",
    "做好眼前事",
    "珍惜身边人",
    "珍惜身边所爱之人",
    "每一段人生",
    "这个年龄真好",
    "我在哪个年龄段",
    "所有的努力不被辜负",
    "所有的幸运不期而遇",
    "所有的快乐无需假装",
    "重新等待",
    "重新出发",
    "接受每一个阶段的自己",
    "过好每一个阶段的人生",
    "迎接新的美好",
    "继续往前",
    "努力不被辜负",
    "不期而遇",
)
_EVERYDAY_WARMTH_RETURN_ACHIEVEMENT_KEYWORDS = (
    "大事",
    "轰轰烈烈",
    "出人头地",
    "改变世界",
    "大富大贵",
    "赚大钱",
    "住大房子",
    "香车美宅",
    "高朋满座",
    "大公司",
    "大名声",
    "排场",
    "热闹",
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
    "家人安康",
    "吃穿不愁",
    "知己二三",
    "四季平安",
    "简单快乐",
    "一家温暖",
    "平安健康",
    "有家可回",
    "有人可爱",
    "陪爱人",
    "爱人的话",
    "做了一顿晚饭",
    "接孩子",
    "一家老小",
    "热腾腾的饭",
    "一盏灯",
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
_EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_KEYWORDS = (
    "没事，有我",
    "没事有我",
    "父母",
    "孩子",
    "伴侣",
    "账单",
    "补习费用",
    "绩效",
    "辞职",
    "扛住压力",
    "喉咙发紧",
    "撑起一个家",
    "父母的拐杖",
    "孩子的雨伞",
    "伴侣的靠山",
    "缴费窗口",
    "风雨来临",
    "家在哪里",
    "有人在爱你",
    "羹汤",
)
_EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_MARKERS = (
    "人间安稳",
    "万般辛苦",
    "终会如愿",
    "值不值得",
    "撑起一片晴空",
    "生活给你最好的补偿",
    "天一定会亮",
    "感谢那个熬过了苦难的自己",
)
_EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_STRONG_ANCHORS = (
    "没事，有我",
    "没事有我",
    "账单",
    "补习费用",
    "绩效",
    "辞职",
    "扛住压力",
    "喉咙发紧",
    "撑起一个家",
    "缴费窗口",
    "安稳",
)
_EVERYDAY_WARMTH_RETURN_THESIS_MARKERS = (
    "最重要的事",
    "祛魅",
    "人生不求大富大贵",
    "人生不求高朋满座",
    "人生不求香车美宅",
    "知足最幸福",
    "才属于你我",
    "才是我们的一生",
    "把“大事”放一放",
    "把“小事”捡起来",
    "被“宏大”绑架",
    "被“微小”治愈",
)
_SUPPORTIVE_APPRECIATION_SOFTNESS_KEYWORDS = (
    "心软",
    "柔软",
    "重感情",
    "太好说话",
    "不计较",
    "不去计较",
    "包容",
    "体谅",
    "原谅",
    "照顾着别人的感受",
    "照顾别人的感受",
    "不舍得让身边的人受伤",
    "心里在乎",
    "和好如初",
)
_SUPPORTIVE_APPRECIATION_CHERISH_KEYWORDS = (
    "心软的人并不傻",
    "并不傻",
    "比谁都拎得清",
    "值得被珍惜",
    "被珍惜",
    "认真珍惜",
    "珍惜",
    "温柔有分寸",
    "看懂这份柔软",
    "舍不得轻慢",
    "认真回应",
    "柔软被珍惜",
    "看的是分寸，也看回应",
    "明明拎得清",
    "珍贵",
    "请你一定要牵紧",
    "一定要牵紧他的手",
    "一生难遇",
    "那些愿意包容你的人",
    "一定很爱你",
    "愿意穿过无尽暴雨",
    "去拥抱你",
)
_SUPPORTIVE_APPRECIATION_NEGATIVE_EXCLUSION_KEYWORDS = (
    "冷暴力",
    "吵架后的态度",
    "检验爱情的试金石",
    "争吵以后还想要继续走下去",
    "回避修复",
    "把日子接回去",
)
_SELF_WORTH_REBUILD_KEYWORDS = (
    "爱自己",
    "自爱",
    "自尊",
    "自我价值",
    "价值感",
    "养贵",
    "把自己养贵",
    "打折品",
    "奢侈品",
    "活成打折品",
    "活成奢侈品",
    "你不贵重",
    "不自爱",
    "被辜负",
    "将就",
    "降级",
    "贬值",
    "配得上",
    "关系里的分寸",
    "认真对待自己",
    "位置摆正",
    "尊重这两秒",
    "身价",
    "抬高门槛",
    "标准收紧",
    "树边界",
    "重新定义",
    "别低到尘埃里",
    "把自己放在心上",
    "都可以",
    "把自己放轻",
    "往后退",
    "退让",
    "位置摆正",
    "关系里的分寸",
    "不舒服",
)
_SELF_WORTH_REBUILD_THESIS_MARKERS = (
    "你爱自己的程度，决定了谁能走进你的人生",
    "别人怎么对你，其实都是你教的",
    "人必自爱，然后人爱之",
    "当你开始爱自己，世界才会开始爱你",
    "把自己养贵一点",
    "你越将就",
    "你越讲究",
    "你对自己大方",
    "只要你不随意降低自己的身价",
    "别总把那句“都可以”说得太顺口",
    "那句“都可以”",
    "把那点不舒服重新当回事",
)
_SELF_WORTH_REBUILD_POSITIVE_MARKERS = (
    "尊重自己",
    "守住边界",
    "把精力留给自己",
    "把门槛抬高一点",
    "把标准收紧一点",
    "托举自己",
    "活得体面",
    "值得",
    "配得上",
    "关系里的分寸",
    "认真对待自己",
    "位置摆正",
    "尊重这两秒",
)
_SELF_WORTH_REBUILD_RESPONSE_PRIORITY_EXCLUSION_KEYWORDS = (
    "没时间",
    "回信息",
    "回消息",
    "回电话",
    "红灯30秒",
    "24小时在线",
    "时间在哪儿",
    "心就在哪儿",
)
_RESPONSE_PRIORITY_TIME_KEYWORDS = (
    "没时间",
    "很忙",
    "红灯30秒",
    "回信息",
    "回消息",
    "回电话",
    "回应",
    "等红绿灯",
    "发语音",
    "蓝牙",
    "24小时在线",
    "朋友圈",
    "点赞",
    "拍了张照片",
)
_RESPONSE_PRIORITY_PRIORITY_KEYWORDS = (
    "优先",
    "优先级",
    "顺序",
    "排序",
    "时间在哪儿",
    "心就在哪儿",
    "花在你身上",
    "在乎的人",
    "有时间",
    "忙不是借口",
    "没时间也不是理由",
)
_RESPONSE_PRIORITY_THESIS_MARKERS = (
    "不是没时间",
    "忙不是借口",
    "没时间也不是理由",
    "人对在乎的人，永远都有时间",
    "一个人的时间在哪儿，他的心就在哪儿",
    "真正的原因",
    "不够重要",
    "顺序没那么优先",
)
_RESPONSE_PRIORITY_INTERACTION_KEYWORDS = (
    "消息",
    "回复",
    "回应",
    "朋友圈",
    "点赞",
    "评论",
    "追问",
    "多问一句",
    "回头",
)
_RESPONSE_PRIORITY_FOLLOWUP_KEYWORDS = (
    "评论的人",
    "给你评论",
    "多问一句",
    "追问",
    "愿意停下来",
    "言外之意",
    "读懂",
    "没说完",
    "接住",
    "注意力分给你",
    "我没事",
    "我有点累",
    "飞得累不累",
)
_RESPONSE_PRIORITY_RELATIONSHIP_EXCLUSION_KEYWORDS = (
    "吵架",
    "冷战",
    "和好",
    "修复",
    "善后",
    "冷暴力",
    "复合",
    "争执",
    "推开",
    "示弱",
)
_TRUST_BOUNDARY_CORE_KEYWORDS = (
    "信任",
    "相信",
    "信任感",
)
_TRUST_BOUNDARY_BREACH_KEYWORDS = (
    "谎言",
    "谎话",
    "隐瞒",
    "遮掩",
    "撒谎",
    "说谎",
    "欺骗",
    "欺瞒",
    "辜负",
    "裂缝",
    "裂了一道缝",
    "疙瘩",
    "出轨",
    "怀疑",
    "敏感多疑",
    "不敢再信",
)
_TRUST_BOUNDARY_REPAIR_KEYWORDS = (
    "坦诚",
    "真诚",
    "诚实",
    "赤诚",
    "透明",
    "说到做到",
    "交代",
    "心安",
    "安全感",
    "不查手机",
    "不追问行踪",
    "给你自由",
    "把心交出来",
    "守护",
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
    "敷衍",
    "忽视",
    "轻视",
    "没接住",
    "接不住",
    "被晾着",
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
    "求助",
    "示弱",
    "推开",
    "嫌烦",
    "不再示弱",
    "最晚被接住",
)
_RELATIONSHIP_AFTERCARE_VULNERABILITY_KEYWORDS = (
    "求助",
    "示弱",
    "脆弱",
    "推开",
    "嫌烦",
    "落空",
    "不被理解",
    "误读",
    "无理取闹",
    "袒露软弱",
    "收起依赖",
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
    if _has_supportive_appreciation_focus(payload):
        return ""
    if _has_inner_settlement_focus(payload):
        return ""
    if _has_relationship_aftercare_focus(payload):
        return ""
    if _has_trust_boundary_focus(payload):
        return ""

    fields = [
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("analysis_theme"),
        payload.get("analysis_core_conflict"),
        payload.get("analysis_emotional_exit"),
        payload.get("analysis_do_not_turn_into"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
        payload.get("reference_article_analysis_theme"),
        payload.get("reference_article_analysis_core_conflict"),
        payload.get("reference_article_analysis_emotional_exit"),
        payload.get("reference_article_analysis_do_not_turn_into"),
    ]
    tag_values = [payload.get("tags"), payload.get("reference_article_tags")]
    field_corpus_parts = [_as_clean_text(value) for value in fields if _as_clean_text(value)]
    tag_corpus_parts: list[str] = []
    for tag_value in tag_values:
        if isinstance(tag_value, list):
            tag_corpus_parts.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))
    if not field_corpus_parts:
        field_corpus_parts.extend(
            [
                _as_clean_text(payload.get("topic_title")),
                _as_clean_text(payload.get("topic_angle")),
                _as_clean_text(payload.get("body_markdown")),
            ]
        )
        field_corpus_parts = [part for part in field_corpus_parts if part]

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
    analysis_theme = _as_clean_text(payload.get("analysis_theme")) or _as_clean_text(payload.get("reference_article_analysis_theme"))
    analysis_core_conflict = _as_clean_text(payload.get("analysis_core_conflict")) or _as_clean_text(payload.get("reference_article_analysis_core_conflict"))
    analysis_emotional_exit = _as_clean_text(payload.get("analysis_emotional_exit")) or _as_clean_text(payload.get("reference_article_analysis_emotional_exit"))
    analysis_do_not_turn_into = _as_clean_text(payload.get("analysis_do_not_turn_into")) or _as_clean_text(payload.get("reference_article_analysis_do_not_turn_into"))
    article_title = _as_clean_text(payload.get("article_title")) or _as_clean_text(payload.get("reference_article_title"))
    summary = _as_clean_text(payload.get("summary")) or _as_clean_text(payload.get("reference_article_summary"))
    body_corpus = " ".join(
        part
        for part in (
            article_title,
            summary,
            structure_notes,
            analysis_theme,
            analysis_core_conflict,
            analysis_emotional_exit,
            analysis_do_not_turn_into,
            body_markdown,
        )
        if part
    )
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
    if _has_everyday_warmth_return_focus(payload):
        return False
    if _has_inner_settlement_focus(payload):
        return False
    if _has_self_reliance_inward_support_focus(payload):
        return False
    if _has_trust_boundary_focus(payload):
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


def _has_self_reliance_inward_support_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if _has_everyday_warmth_return_focus(payload):
        return False
    if _has_inner_settlement_focus(payload):
        return False
    if _has_response_priority_focus(payload):
        return False
    if _has_relationship_aftercare_focus(payload):
        return False
    if _has_supportive_appreciation_focus(payload):
        return False
    if _has_resilience_reconstruction_focus(payload):
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

    support_hits = sum(1 for keyword in _SELF_RELIANCE_INWARD_SUPPORT_KEYWORDS if keyword in corpus)
    thesis_hits = sum(1 for marker in _SELF_RELIANCE_INWARD_SUPPORT_THESIS_MARKERS if marker in corpus)
    hard_pressure_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in corpus)
    relationship_hits = sum(1 for keyword in _RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS if keyword in corpus)
    return (
        support_hits >= 5
        and thesis_hits >= 1
        and hard_pressure_hits == 0
        and relationship_hits <= 3
    ) or (
        support_hits >= 4
        and thesis_hits >= 2
        and hard_pressure_hits == 0
        and relationship_hits <= 3
    )


def _has_inner_settlement_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if _has_everyday_warmth_return_focus(payload):
        return False
    if _has_response_priority_focus(payload):
        return False
    if _has_relationship_aftercare_focus(payload):
        return False
    if _has_resilience_reconstruction_focus(payload):
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
    source_corpus_parts = [_as_clean_text(value) for value in fields if _as_clean_text(value)]
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
    source_tag_parts: list[str] = []
    for tag_value in tag_values:
        if isinstance(tag_value, list):
            normalized_tags = [_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag)]
            corpus_parts.extend(normalized_tags)
            source_tag_parts.extend(normalized_tags)
    corpus = " ".join(corpus_parts)
    source_corpus = " ".join(source_corpus_parts + source_tag_parts)
    if not corpus:
        return False

    reference_hits = sum(1 for keyword in _INNER_SETTLEMENT_REFERENCE_KEYWORDS if keyword in corpus)
    thesis_hits = sum(1 for marker in _INNER_SETTLEMENT_THESIS_MARKERS if marker in corpus)
    grounding_hits = sum(1 for keyword in _INNER_SETTLEMENT_DAILY_GROUNDING_KEYWORDS if keyword in corpus)
    daily_return_hits = sum(1 for keyword in _INNER_SETTLEMENT_DAILY_RETURN_KEYWORDS if keyword in corpus)
    stage_restart_hits = sum(1 for keyword in _INNER_SETTLEMENT_STAGE_RESTART_KEYWORDS if keyword in corpus)
    hard_pressure_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in source_corpus)
    return (
        (
            (reference_hits >= 5 and thesis_hits >= 1)
            or (reference_hits >= 4 and thesis_hits >= 2)
            or (reference_hits >= 3 and thesis_hits >= 1 and grounding_hits >= 1)
            or (
                stage_restart_hits >= 4
                and (
                    thesis_hits >= 1
                    or grounding_hits >= 1
                    or daily_return_hits >= 1
                    or stage_restart_hits >= 8
                )
            )
        )
        and hard_pressure_hits == 0
    )


def _has_everyday_warmth_return_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping) and _as_clean_text(strategy_card.get("structure_mode")) in {
        "everyday_warmth_return",
        "responsibility_shelter",
    }:
        return True
    if any(
        _as_clean_text(value) == "everyday_warmth_return"
        for value in (
            payload.get("analysis_structure_mode"),
            payload.get("reference_article_analysis_structure_mode"),
        )
    ):
        return True

    fields = [
        payload.get("topic_title"),
        payload.get("topic_angle"),
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("body_markdown"),
        payload.get("analysis_theme"),
        payload.get("analysis_core_conflict"),
        payload.get("analysis_emotional_exit"),
        payload.get("analysis_opening_pattern"),
        payload.get("analysis_hook_trigger"),
        payload.get("analysis_progression_drive"),
        payload.get("analysis_share_reason"),
        payload.get("analysis_do_not_turn_into"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
        payload.get("reference_article_body_markdown"),
        payload.get("reference_article_analysis_theme"),
        payload.get("reference_article_analysis_core_conflict"),
        payload.get("reference_article_analysis_emotional_exit"),
        payload.get("reference_article_analysis_opening_pattern"),
        payload.get("reference_article_analysis_hook_trigger"),
        payload.get("reference_article_analysis_progression_drive"),
        payload.get("reference_article_analysis_share_reason"),
        payload.get("reference_article_analysis_do_not_turn_into"),
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
    for tag_value in (payload.get("tags"), payload.get("reference_article_tags")):
        if isinstance(tag_value, list):
            fields.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))
    corpus = " ".join(_as_clean_text(value) for value in fields if _as_clean_text(value))
    if not corpus:
        return False

    achievement_hits = sum(1 for keyword in _EVERYDAY_WARMTH_RETURN_ACHIEVEMENT_KEYWORDS if keyword in corpus)
    daily_hits = sum(1 for keyword in _EVERYDAY_WARMTH_RETURN_DAILY_KEYWORDS if keyword in corpus)
    thesis_hits = sum(1 for marker in _EVERYDAY_WARMTH_RETURN_THESIS_MARKERS if marker in corpus)
    simple_happiness_hits = sum(
        1
        for keyword in (
            "大富大贵",
            "简单快乐",
            "知己二三",
            "家人安康",
            "四季平安",
            "一家温暖",
            "知足最幸福",
        )
        if keyword in corpus
    )
    responsibility_hits = sum(1 for keyword in _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_KEYWORDS if keyword in corpus)
    responsibility_marker_hits = sum(
        1 for marker in _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_MARKERS if marker in corpus
    )
    responsibility_strong_hits = sum(
        1 for keyword in _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_STRONG_ANCHORS if keyword in corpus
    )
    return (achievement_hits >= 2 and daily_hits >= 3 and thesis_hits >= 1) or (
        simple_happiness_hits >= 3 and daily_hits >= 4 and thesis_hits >= 1
    ) or (
        responsibility_hits >= 5 and daily_hits >= 2 and responsibility_marker_hits >= 1
    ) or (
        responsibility_hits >= 4 and daily_hits >= 2 and responsibility_marker_hits >= 2
    ) or (
        responsibility_hits >= 6
        and daily_hits >= 2
        and responsibility_strong_hits >= 3
        and any(token in corpus for token in ("安稳", "一个家", "家里", "有我"))
    )


def _has_everyday_warmth_responsibility_shelter_focus(payload: Mapping[str, object]) -> bool:
    if not _has_everyday_warmth_return_focus(payload):
        return False
    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping) and _as_clean_text(strategy_card.get("structure_mode")) == "responsibility_shelter":
        return True

    fields = [
        payload.get("topic_title"),
        payload.get("topic_angle"),
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("body_markdown"),
        payload.get("analysis_theme"),
        payload.get("analysis_core_conflict"),
        payload.get("analysis_emotional_exit"),
        payload.get("analysis_opening_pattern"),
        payload.get("analysis_hook_trigger"),
        payload.get("analysis_progression_drive"),
        payload.get("analysis_share_reason"),
        payload.get("analysis_do_not_turn_into"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
        payload.get("reference_article_body_markdown"),
        payload.get("reference_article_analysis_theme"),
        payload.get("reference_article_analysis_core_conflict"),
        payload.get("reference_article_analysis_emotional_exit"),
        payload.get("reference_article_analysis_opening_pattern"),
        payload.get("reference_article_analysis_hook_trigger"),
        payload.get("reference_article_analysis_progression_drive"),
        payload.get("reference_article_analysis_share_reason"),
        payload.get("reference_article_analysis_do_not_turn_into"),
    ]
    for tag_value in (payload.get("tags"), payload.get("reference_article_tags")):
        if isinstance(tag_value, list):
            fields.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))
    corpus = " ".join(_as_clean_text(value) for value in fields if _as_clean_text(value))
    if not corpus:
        return False

    analysis_mode_locked = any(
        _as_clean_text(value) == "everyday_warmth_return"
        for value in (
            payload.get("analysis_structure_mode"),
            payload.get("reference_article_analysis_structure_mode"),
        )
    )
    responsibility_hits = sum(1 for keyword in _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_KEYWORDS if keyword in corpus)
    responsibility_marker_hits = sum(
        1 for marker in _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_MARKERS if marker in corpus
    )
    daily_hits = sum(1 for keyword in _EVERYDAY_WARMTH_RETURN_DAILY_KEYWORDS if keyword in corpus)
    responsibility_strong_hits = sum(
        1 for keyword in _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_STRONG_ANCHORS if keyword in corpus
    )
    if analysis_mode_locked and responsibility_hits >= 4 and (
        "责任" in corpus or "安稳" in corpus or "一个家" in corpus or "家里" in corpus
    ):
        return True
    if (
        responsibility_hits >= 6
        and daily_hits >= 2
        and responsibility_strong_hits >= 3
        and any(token in corpus for token in ("安稳", "一个家", "家里", "有我"))
    ):
        return True
    return (responsibility_hits >= 4 and daily_hits >= 2 and responsibility_marker_hits >= 1) or (
        responsibility_hits >= 3 and responsibility_marker_hits >= 2
    )


def _has_everyday_warmth_simple_happiness_focus(payload: Mapping[str, object]) -> bool:
    if not _has_everyday_warmth_return_focus(payload):
        return False
    if _has_everyday_warmth_responsibility_shelter_focus(payload):
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
    corpus_parts = [_as_clean_text(value) for value in fields if _as_clean_text(value)]
    tag_values = [payload.get("tags"), payload.get("reference_article_tags")]
    for tag_value in tag_values:
        if isinstance(tag_value, list):
            corpus_parts.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))
    corpus = " ".join(corpus_parts)
    if not corpus:
        return False

    happiness_hits = sum(
        1
        for keyword in ("大富大贵", "简单快乐", "知足最幸福", "高朋满座", "香车美宅")
        if keyword in corpus
    )
    grounding_hits = sum(
        1
        for keyword in ("家人安康", "知己二三", "一家温暖", "平安健康", "有家可回", "有人可爱", "四季平安")
        if keyword in corpus
    )
    return happiness_hits >= 2 and grounding_hits >= 2


def _has_resilience_reconstruction_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if _has_everyday_warmth_return_focus(payload):
        return False
    if _has_response_priority_focus(payload):
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


def _has_supportive_appreciation_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if _has_everyday_warmth_return_focus(payload):
        return False
    if _has_response_priority_focus(payload):
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

    softness_hits = sum(1 for keyword in _SUPPORTIVE_APPRECIATION_SOFTNESS_KEYWORDS if keyword in corpus)
    cherish_hits = sum(1 for keyword in _SUPPORTIVE_APPRECIATION_CHERISH_KEYWORDS if keyword in corpus)
    hard_pressure_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in corpus)
    negative_aftercare_hits = sum(1 for keyword in _SUPPORTIVE_APPRECIATION_NEGATIVE_EXCLUSION_KEYWORDS if keyword in corpus)
    return softness_hits >= 3 and cherish_hits >= 1 and hard_pressure_hits == 0 and negative_aftercare_hits == 0


def _has_self_worth_rebuild_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if _has_everyday_warmth_return_focus(payload):
        return False

    fields = [
        payload.get("topic_title"),
        payload.get("topic_angle"),
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("body_markdown"),
        payload.get("analysis_theme"),
        payload.get("analysis_core_conflict"),
        payload.get("analysis_emotional_exit"),
        payload.get("analysis_do_not_turn_into"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
        payload.get("reference_article_body_markdown"),
        payload.get("reference_article_analysis_theme"),
        payload.get("reference_article_analysis_core_conflict"),
        payload.get("reference_article_analysis_emotional_exit"),
        payload.get("reference_article_analysis_do_not_turn_into"),
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

    theme_hits = sum(1 for keyword in _SELF_WORTH_REBUILD_KEYWORDS if keyword in corpus)
    thesis_hits = sum(1 for marker in _SELF_WORTH_REBUILD_THESIS_MARKERS if marker in corpus)
    positive_hits = sum(1 for marker in _SELF_WORTH_REBUILD_POSITIVE_MARKERS if marker in corpus)
    response_priority_hits = sum(1 for keyword in _SELF_WORTH_REBUILD_RESPONSE_PRIORITY_EXCLUSION_KEYWORDS if keyword in corpus)
    hard_pressure_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in corpus)
    return (
        theme_hits >= 5
        and thesis_hits >= 1
        and positive_hits >= 2
        and response_priority_hits <= 2
        and hard_pressure_hits == 0
    ) or (
        theme_hits >= 4
        and thesis_hits >= 2
        and positive_hits >= 1
        and response_priority_hits <= 2
        and hard_pressure_hits == 0
    )


def _has_relationship_aftercare_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if _has_supportive_appreciation_focus(payload):
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

    relationship_corpus, _ = _strip_negated_relationship_spans(corpus)
    if not relationship_corpus:
        relationship_corpus = corpus

    conflict_hits = sum(1 for keyword in _RELATIONSHIP_AFTERCARE_CONFLICT_KEYWORDS if keyword in relationship_corpus)
    repair_hits = sum(1 for keyword in _RELATIONSHIP_AFTERCARE_REPAIR_KEYWORDS if keyword in relationship_corpus)
    relationship_hits = sum(1 for keyword in _RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS if keyword in relationship_corpus)
    thesis_hits = sum(1 for marker in _RELATIONSHIP_AFTERCARE_THESIS_MARKERS if marker in relationship_corpus)
    vulnerability_hits = sum(1 for keyword in _RELATIONSHIP_AFTERCARE_VULNERABILITY_KEYWORDS if keyword in relationship_corpus)
    hard_pressure_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in corpus)
    self_reliance_support_hits = sum(1 for keyword in _SELF_RELIANCE_INWARD_SUPPORT_KEYWORDS if keyword in corpus)
    self_reliance_thesis_hits = sum(1 for marker in _SELF_RELIANCE_INWARD_SUPPORT_THESIS_MARKERS if marker in corpus)
    if self_reliance_support_hits >= 5 and self_reliance_thesis_hits >= 1 and relationship_hits <= 1:
        return False
    classic_aftercare = (
        relationship_hits >= 1
        and conflict_hits >= 1
        and repair_hits >= 2
        and (thesis_hits >= 1 or conflict_hits >= 2)
    )
    withdrawn_aftercare = (
        relationship_hits >= 1
        and conflict_hits >= 1
        and thesis_hits >= 1
        and vulnerability_hits >= 2
    )
    return (classic_aftercare or withdrawn_aftercare) and hard_pressure_hits == 0


def _has_trust_boundary_focus(payload: Mapping[str, object]) -> bool:
    source_type = _as_clean_text(payload.get("source_type"))
    if source_type and source_type != "tracked_article":
        return False
    corpus = _build_trust_boundary_corpus(payload)
    if not corpus:
        return False
    core_hits = sum(1 for keyword in _TRUST_BOUNDARY_CORE_KEYWORDS if keyword in corpus)
    breach_hits = sum(1 for keyword in _TRUST_BOUNDARY_BREACH_KEYWORDS if keyword in corpus)
    repair_hits = sum(1 for keyword in _TRUST_BOUNDARY_REPAIR_KEYWORDS if keyword in corpus)
    pressure_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in corpus)
    return core_hits >= 2 and pressure_hits == 0 and (breach_hits >= 2 or (breach_hits >= 1 and repair_hits >= 2))


def _build_trust_boundary_corpus(payload: Mapping[str, object]) -> str:
    fields = [
        payload.get("topic_title"),
        payload.get("topic_angle"),
        payload.get("article_title"),
        payload.get("summary"),
        payload.get("structure_notes"),
        payload.get("body_markdown"),
        payload.get("analysis_theme"),
        payload.get("analysis_core_conflict"),
        payload.get("analysis_emotional_exit"),
        payload.get("analysis_do_not_turn_into"),
        payload.get("reference_article_title"),
        payload.get("reference_article_summary"),
        payload.get("reference_article_structure_notes"),
        payload.get("reference_article_body_markdown"),
        payload.get("reference_article_analysis_theme"),
        payload.get("reference_article_analysis_core_conflict"),
        payload.get("reference_article_analysis_emotional_exit"),
        payload.get("reference_article_analysis_do_not_turn_into"),
    ]
    tag_values = [payload.get("tags"), payload.get("reference_article_tags")]
    corpus_parts = [_as_clean_text(value) for value in fields if _as_clean_text(value)]
    for tag_value in tag_values:
        if isinstance(tag_value, list):
            corpus_parts.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))
    return " ".join(corpus_parts)


def _has_response_priority_focus(payload: Mapping[str, object]) -> bool:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if _has_everyday_warmth_return_focus(payload):
        return False
    if _has_self_worth_rebuild_focus(payload):
        return False
    if _has_trust_boundary_focus(payload):
        return False

    corpus = _build_response_priority_corpus(payload)
    if not corpus:
        return False

    time_hits = sum(1 for keyword in _RESPONSE_PRIORITY_TIME_KEYWORDS if keyword in corpus)
    priority_hits = sum(1 for keyword in _RESPONSE_PRIORITY_PRIORITY_KEYWORDS if keyword in corpus)
    thesis_hits = sum(1 for marker in _RESPONSE_PRIORITY_THESIS_MARKERS if marker in corpus)
    interaction_hits = sum(1 for keyword in _RESPONSE_PRIORITY_INTERACTION_KEYWORDS if keyword in corpus)
    followup_hits = sum(1 for keyword in _RESPONSE_PRIORITY_FOLLOWUP_KEYWORDS if keyword in corpus)
    care_hits = sum(1 for keyword in ("在意", "在乎", "关心", "注意力") if keyword in corpus)
    relationship_conflict_hits = sum(
        1 for keyword in _RESPONSE_PRIORITY_RELATIONSHIP_EXCLUSION_KEYWORDS if keyword in corpus
    )
    hard_pressure_hits = sum(1 for keyword in _INTERNAL_PRESSURE_BODY_HARD_SIGNALS if keyword in corpus)
    classic_branch = time_hits >= 4 and priority_hits >= 2 and thesis_hits >= 1
    followup_branch = interaction_hits >= 3 and followup_hits >= 3 and (care_hits >= 1 or priority_hits >= 1)
    return (
        (classic_branch or followup_branch)
        and relationship_conflict_hits <= 2
        and hard_pressure_hits == 0
    )


def _build_response_priority_corpus(payload: Mapping[str, object]) -> str:
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return ""

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
    return " ".join(corpus_parts)


def _uses_response_priority_followup_variant(payload: Mapping[str, object]) -> bool:
    if not _has_response_priority_focus(payload):
        return False
    corpus = _build_response_priority_corpus(payload)
    if not corpus:
        return False

    followup_hits = sum(1 for keyword in _RESPONSE_PRIORITY_FOLLOWUP_KEYWORDS if keyword in corpus)
    interaction_hits = sum(
        1 for keyword in ("评论", "追问", "多问一句", "读懂", "没说完", "停下来", "我没事", "我有点累", "注意力")
        if keyword in corpus
    )
    care_hits = sum(1 for keyword in ("在意", "在乎", "关心", "理解", "珍惜") if keyword in corpus)
    classic_hits = sum(
        1
        for keyword in (
            "没时间",
            "很忙",
            "红灯30秒",
            "等红绿灯",
            "24小时在线",
            "优先",
            "优先级",
            "顺序",
            "时间在哪儿",
            "心就在哪儿",
            "不够重要",
            "忙不是借口",
            "没时间也不是理由",
        )
        if keyword in corpus
    )
    return followup_hits >= 3 and interaction_hits >= 4 and care_hits >= 1 and (followup_hits + interaction_hits) >= classic_hits + 2


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
    for keyword in _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_KEYWORDS:
        if keyword in compact:
            score += 2
    for marker in _EVERYDAY_WARMTH_RETURN_THESIS_MARKERS:
        if marker in compact:
            score += 2
    for marker in _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_MARKERS:
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


def _score_tracked_article_inner_settlement_cue(sentence: str) -> int:
    score = 0
    compact = re.sub(r"\s+", "", sentence)
    for keyword in _INNER_SETTLEMENT_REFERENCE_KEYWORDS:
        if keyword in compact:
            score += 2
    for marker in _INNER_SETTLEMENT_THESIS_MARKERS:
        if marker in compact:
            score += 2
    for keyword in _INNER_SETTLEMENT_DAILY_GROUNDING_KEYWORDS:
        if keyword in compact:
            score += 2
    for keyword in _INNER_SETTLEMENT_STAGE_RESTART_KEYWORDS:
        if keyword in compact:
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


def _score_tracked_article_response_priority_cue(sentence: str) -> int:
    score = 0
    compact = re.sub(r"\s+", "", sentence)
    for keyword in _RESPONSE_PRIORITY_TIME_KEYWORDS:
        if keyword in compact:
            score += 2
    for keyword in _RESPONSE_PRIORITY_INTERACTION_KEYWORDS:
        if keyword in compact:
            score += 2
    for keyword in _RESPONSE_PRIORITY_FOLLOWUP_KEYWORDS:
        if keyword in compact:
            score += 2
    for keyword in _RESPONSE_PRIORITY_PRIORITY_KEYWORDS:
        if keyword in compact:
            score += 2
    for marker in _RESPONSE_PRIORITY_THESIS_MARKERS:
        if marker in compact:
            score += 2
    if "“" in sentence or "\"" in sentence:
        score += 1
    if any(keyword in compact for keyword in _RESPONSE_PRIORITY_RELATIONSHIP_EXCLUSION_KEYWORDS):
        score -= 2
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


def _should_relax_direct_answer_rules_for_tracked_article(payload: Mapping[str, object] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    if not _has_strategy_package(payload):
        return False
    return True


def _build_inner_settlement_variant_corpus(payload: Mapping[str, object]) -> str:
    problem_brief = payload.get("problem_brief")
    strategy_card = payload.get("strategy_card")
    parts: list[str] = [
        _as_clean_text(payload.get("topic_title")),
        _as_clean_text(payload.get("topic_angle")),
        _as_clean_text(payload.get("article_title")),
        _as_clean_text(payload.get("summary")),
        _as_clean_text(payload.get("structure_notes")),
        _as_clean_text(payload.get("body_markdown")),
    ]
    draft = payload.get("draft")
    assets = payload.get("assets")
    if isinstance(draft, Mapping):
        parts.extend(
            [
                _as_clean_text(draft.get("title")),
                _as_clean_text(draft.get("body_markdown")),
            ]
        )
    if isinstance(assets, Mapping):
        parts.extend(
            [
                _as_clean_text(assets.get("cover_copy")),
                _as_clean_text(assets.get("social_teaser")),
                _as_clean_text(assets.get("recommended_title")),
            ]
        )
        for list_key in ("social_teaser_options", "title_options"):
            list_value = assets.get(list_key)
            if isinstance(list_value, list):
                parts.extend(_as_clean_text(item) for item in list_value if _as_clean_text(item))
    if isinstance(problem_brief, Mapping):
        parts.extend(
            [
                _as_clean_text(problem_brief.get("clarified_problem")),
                _as_clean_text(problem_brief.get("observed_phenomenon")),
                _as_clean_text(problem_brief.get("writing_goal")),
                _as_clean_text(problem_brief.get("emotional_value_goal")),
                _as_clean_text(problem_brief.get("theme_axis")),
                _as_clean_text(problem_brief.get("anti_drift_axis")),
                _as_clean_text(problem_brief.get("target_reader_situation")),
                _as_clean_text(problem_brief.get("core_conflict")),
            ]
        )
    if isinstance(strategy_card, Mapping):
        parts.extend(
            [
                _as_clean_text(strategy_card.get("reader_situation")),
                _as_clean_text(strategy_card.get("point_of_view")),
                _as_clean_text(strategy_card.get("conflict_frame")),
                _as_clean_text(strategy_card.get("emotional_path")),
                _as_clean_text(strategy_card.get("positive_direction")),
                _as_clean_text(strategy_card.get("quotable_line_goal")),
                _as_clean_text(strategy_card.get("packaging_focus")),
                _as_clean_text(strategy_card.get("packaging_hook")),
                _as_clean_text(strategy_card.get("opening_move")),
                _as_clean_text(strategy_card.get("body_shift")),
                _as_clean_text(strategy_card.get("ending_move")),
                _as_clean_text(strategy_card.get("benchmark_summary")),
            ]
        )
        for list_key in ("scene_anchor_requirements", "quotable_line_seeds"):
            list_value = strategy_card.get(list_key)
            if isinstance(list_value, list):
                parts.extend(_as_clean_text(item) for item in list_value if _as_clean_text(item))
    for tag_key in ("tags", "reference_article_tags"):
        tag_value = payload.get(tag_key)
        if isinstance(tag_value, list):
            parts.extend(_as_clean_text(tag) for tag in tag_value if _as_clean_text(tag))
    return " ".join(part for part in parts if part)


def _resolve_inner_settlement_variant(payload: Mapping[str, object]) -> str:
    strategy_card = payload.get("strategy_card")
    structure_mode = ""
    if isinstance(strategy_card, Mapping):
        structure_mode = _as_clean_text(strategy_card.get("structure_mode"))
    if structure_mode != "inner_settlement" and not _has_inner_settlement_focus(payload):
        return ""
    corpus = _build_inner_settlement_variant_corpus(payload)
    stage_restart_hits = sum(1 for keyword in _INNER_SETTLEMENT_STAGE_RESTART_KEYWORDS if keyword in corpus)
    theme_hits = sum(1 for marker in _INNER_SETTLEMENT_THESIS_MARKERS if marker in corpus)
    daily_hits = sum(1 for keyword in _INNER_SETTLEMENT_DAILY_GROUNDING_KEYWORDS if keyword in corpus)
    daily_return_hits = sum(1 for keyword in _INNER_SETTLEMENT_DAILY_RETURN_KEYWORDS if keyword in corpus)
    if stage_restart_hits >= 4 or (stage_restart_hits >= 2 and (theme_hits >= 1 or daily_hits >= 1 or daily_return_hits >= 1)):
        return "stage_restart"
    return ""


TRACKED_ARTICLE_STRUCTURE_TONE_OVERRIDES: dict[str, dict[str, str]] = {
    "response_priority": {
        "opening_style": (
            "先从一个被放到后面的回应接口切入：没回的消息、迟到的电话、临时才想起你的安排。"
            "先让读者认出等待和找补，再给判断，不急着把“你不重要”写成开场判词。"
        ),
        "paragraph_rhythm": (
            "前半篇先写顺序落差怎样消耗人，再写时间投向和回应动作怎样把位置感显出来。"
            "段落要有快慢差，允许 1 到 2 处一句一段的人话短句，不要把每段都写成匀速讲解。"
            "后半篇把情绪从等待感拉回位置感、选择感和时间回收感。"
        ),
        "closing_style": (
            "结尾落在位置感回正、时间慢慢收回自己和愿意回应的人身上，"
            "给读者清醒后的轻一点，不写苦情控诉，也不强行判死。"
        ),
        "value_constraints": (
            "这类稿子的情绪价值，不只是认清受伤，更是认清之后的松绑、回正和提气；"
            "前半篇至少留 1 到 2 处能单独成段的人话短句，其中至少 1 处要从真实代价或顺序落差里长出来。"
        ),
        "default_polish_instruction": (
            "如果是回应顺序题材，先把“你不重要”“别等了”这类一锤定音句降下来，"
            "改成顺序、动作和时间投向自己把答案显出来；"
            "同时补足位置感回正和时间回收到自己手里的轻一点，不要把全文修成苦情控诉。"
        ),
    },
    "supportive_appreciation": {
        "opening_style": (
            "先从一个她明明受了委屈，却还是先把话放软、先照顾别人感受的小接口切入。"
            "重点是让读者先看见那份柔软和分寸，不急着下诊断。"
        ),
        "paragraph_rhythm": (
            "前半篇先写柔软为什么常被误读，中段再写明明拎得清却仍愿意体谅和包容的分量。"
            "段落要有快慢差，允许 1 到 2 处一句一段的真话短句，但不要排成匀速诊断稿。"
        ),
        "closing_style": (
            "结尾落在一次认真回应、牵紧或终于没有把这份柔软当成理所当然的轻动作上，"
            "让人感觉温柔被看见了，也被认真放在心上。"
        ),
        "value_constraints": (
            "这类稿子的情绪价值，要落在柔软被正名、被看见和被珍惜上；"
            "重点是让读者感到被理解、被珍惜，而不是被分析。"
        ),
        "default_polish_instruction": (
            "如果是柔软珍惜题材，把重点写回柔软为什么珍贵、为什么值得被认真回应，"
            "让开头、中段和结尾都服从这个正向主题。"
        ),
    },
    "everyday_warmth_return": {
        "opening_style": (
            "先从重要感为什么总被押在更大的目标上切入，或者先落一个总被略过去、后来突然舍不得再错过的小日常。"
            "不要一上来就端出顿悟，也不要把家庭动作清单摆成开场。"
        ),
        "paragraph_rhythm": (
            "前半篇写大事叙事为什么慢慢失重，后半篇写饭桌、回家、有人惦记这些小日常怎样重新回到眼前。"
            "段落长短要有快慢，允许 1 到 2 处一句一段的温热短句，但不要排成并列清单或整齐排比。"
        ),
        "closing_style": (
            "结尾落在一顿饭、一次散步、一次接送、一次回家或一句终于说出口的家常话上，"
            "让人感觉生活重新有了轻重，不靠顿悟翻牌。"
        ),
        "value_constraints": (
            "情绪价值优先落在被生活接住、被关系轻轻回温和重新看见日常分量上，"
            "不要把暖意写成大面积抒情，也不要把日常温度写成三四个并列动作。"
        ),
        "default_polish_instruction": (
            "如果是小事回归题材，删掉宏大顿悟和并列家庭动作清单，"
            "改成成就叙事慢慢失重、眼前日子重新有分量的推进。"
        ),
    },
    "inner_settlement": {
        "opening_style": (
            "先从那颗心还没完全落回今天的现实接口起笔。"
            "不要先讲大道理，也不要先把不同主题硬拽成关系等待、身体提醒或固定夜深小失序。"
        ),
        "paragraph_rhythm": (
            "第一屏尽量拆成 3 到 4 个短段，先让人认出那颗一直悬着的心。"
            "中段从真正拖住人的牵挂或反复较劲，慢慢走回眼前正在过的生活；至少保住 2 处可摘录短句，"
            "其中 1 处要像从处境里自己冒出来的人话。"
        ),
        "closing_style": (
            "结尾回到一个心终于稍微放平下来的轻动作、现实余波或继续生活的安排，"
            "给人安顿感，不写幸福定义，也不写空祝福。"
        ),
        "value_constraints": (
            "这类稿子的情绪价值，要先让读者觉得自己被理解，不必再跟自己较劲，"
            "再慢慢被安放回生活；不要一路写成自我分析稿。"
        ),
        "default_polish_instruction": (
            "如果是心安归位题材，先拆掉空泛看开和幸福大道理，"
            "把开头和结尾都压回参考文真正的牵挂接口、回稳动作和回到当下的现实落点。"
        ),
    },
    "self_reliance_inward_support": {
        "opening_style": (
            "先服从参考文章分析中的主题、起笔方式和触发点，不为结构模式另造一套开场。"
            "自我支撑题材优先从一个人开始理清顺序、作出决定、恢复行动或重新找回节奏的现实接口切入。"
            "外部压力只保留为理解处境所必需的背景，开场主镜头要落在当前文章独有的行动、判断或回稳细节上。"
            "第一屏让读者看见人开始把注意力、秩序和选择权收回自己手里。"
        ),
        "paragraph_rhythm": (
            "前半篇就让自我支撑的能力出现：一个动作、一个判断或一次重新安排，都可以把主题带起来。"
            "段落要短，前六段至少留 2 处一句一段的人话短句，其中 1 处要从参考文的具体处境里自然长出来。"
            "不要连续两段都在解释困境，也不要把全文排成均匀的自助步骤清单。"
            "不要写成固定教程开场或自助说明口吻。"
            "如果要写托底动作，选 1 到 2 个贴着当前处境的动作就够了，不要排成连续自助步骤。"
            "少用“先……先……先……”往下推整段，尤其不要连续三句都用“先”起手。"
            "少用“一点、一下、一件、一条”这类泛量词去托节奏，能直接写动作、物件、时间点时就直接写。"
            "自我支撑的动作、判断或能力最迟在第 3 段出现，不让负面处境占满第一屏。"
            "独立短句也要是完整人话，不要为了停顿感留下半截句、悬空转折或没接上的句头。"
            "除非原文主冲突本来就建在身体代价上，否则不要顺手排成身体不适清单。"
            "可以出现他人，但镜头最终要回到当事人的判断、行动和恢复力上。"
            "全文始终围绕参考文真正讨论的那种力量，不把自我支撑统一写成熬过一个夜晚。"
        ),
        "closing_style": (
            "结尾服从分析合同里的情绪出口，可以落在已经作出的选择、恢复的行动、重新确认的能力或继续生活的具体安排上。"
            "给读者清醒、温暖和向前的力量，不写硬扛口号，也不把每篇都收成今晚先睡、明天再说。"
            "最后要让正向变化已经发生，而不是仍停在等待、失落或自我安慰里。"
        ),
        "value_constraints": (
            "这类稿子的情绪价值，要让读者看见自己已经拥有的判断力、行动力和恢复力。"
            "至少保住 1 到 2 处贴着当前处境长出来、能单独成段的可摘录短句，不要把全文写成匀速说明文。"
            "重点是正向能力怎样在现实里发生，不再诊断失落，也不靠贬低外界关系来抬高自救。"
            "标题、首屏和短句尽量温暖、有力、具体，表达应随参考文主题变化，不固定复用‘安顿自己’‘把今天过完’或‘把日子接回来’。"
        ),
        "default_polish_instruction": (
            "如果是向内求或自我支撑题材，先删掉平均讲解、负面诊断和万能自助步骤，优先补 1 到 2 处从参考文具体处境里长出来的人话短句；"
            "开头就让读者看见一种正在发生的正向能力，再按分析合同把主题写实。"
            "如果前半篇仍在扩写外部缺席、求援落空或等待救场，直接删掉这条自造前提。"
            "如果出现症状化句群，优先拆回动作、顺序和当场反应。"
            "把过于管理化、诊断化的词换成更接近现实的人话，让读者得到力量，而不是被分析。"
        ),
    },
    "relationship_aftercare": {
        "opening_style": (
            "先从争执后留下的小接口切入：那句没说的话、照常做完的事、迟迟没有回来的沟通。"
            "不要先把整篇抬成成熟关系总论。"
        ),
        "paragraph_rhythm": (
            "前半篇守住空白、沉默和失望落地的那一刻，中段再写有没有人回来沟通、接住情绪怎样慢慢决定关系的走向。"
            "段落要有停顿和余波，不要写成平均讲解稿，也不要只顾算委屈。"
        ),
        "closing_style": (
            "结尾落在一次被接住、一次没接住，或一个还没完全补上的小缺口上，"
            "给读者被理解和能继续往前的感觉，不写高位宣判。"
        ),
        "value_constraints": (
            "这类稿子的情绪价值优先落在被接住、被理解和看清修复成本上，"
            "不要把全文修成争输赢或道理均分稿。"
        ),
        "default_polish_instruction": (
            "如果是争执后修复题材，先删掉平均讲解和成熟关系套话，"
            "让谁愿意回头沟通、谁愿意接住失望、谁愿意把关系往前带自己把问题显出来。"
        ),
    },
    "resilience_reconstruction": {
        "opening_style": (
            "先从重击、疼痛、训练代价或被迫重来的现实接口切入。"
            "不要先拔成励志口号，也不要把人物直接写成已经赢了的人。"
        ),
        "paragraph_rhythm": (
            "前半篇压住伤口、代价和重复重来，中后段再写人怎样一点点把自己重新托起来。"
            "允许 1 到 2 处一句一段的硬短句，但不要把全文排成励志标语。"
        ),
        "closing_style": (
            "结尾落在继续训练、继续站稳、继续命名自己的一小步上，"
            "给人力量感，不写苦难神化，也不写万能鸡汤。"
        ),
        "value_constraints": (
            "这类稿子的情绪价值，要让读者看见韧性是怎样在代价里一点点长出来的，"
            "不是靠喊口号突然完成逆袭。"
        ),
        "default_polish_instruction": (
            "如果是重建韧性题材，先降掉空励志和一键涅槃句，"
            "把人物写回疼痛、训练、重复重来和继续站稳的现实推进里。"
        ),
    },
}

TRACKED_ARTICLE_EVERYDAY_WARMTH_RESPONSIBILITY_TONE_OVERRIDE: dict[str, str] = {
    "opening_style": (
        "先从肩上责任带来的现实重量切入：来电、日历安排、复查预约、请假前协调，"
        "或者那种自己先把顺序理清、让家里跟着稳下来的当场。"
        "不要先空讲成年人都不容易，也不要一上来就套“更大的目标慢慢失重”那层总论。"
    ),
    "paragraph_rhythm": (
        "前半篇先让责任为什么会让人多想一步落地，中段再写父母、孩子、伴侣和一个家为什么会让人愿意认真把日子托稳。"
        "段落要短，前四段至少 2 段先给动作、停顿、回话或物件接口，不要每段都立刻作者总结。"
        "允许 1 到 2 处一句一段的人话短句，但短句要从责任、顺序和回温里自己长出来，不要排成匀速励志句墙。"
        "后半篇把情绪带回家里被护住的安稳感，以及那个一直用心的人也值得被照顾，不要一路只数苦、只喊值。"
    ),
    "closing_style": (
        "结尾落在一盏灯、一碗热汤、校门口一张画、或一句终于能松下来的回话上，"
        "让人感觉这些辛苦最后真的托住了家里的安稳，不写成苦难勋章或万能鸡汤。"
    ),
    "value_constraints": (
        "这类稿子的情绪价值，要落在“原来我的辛苦有人懂，而且它真的护住了我在意的人”这层安稳感上；"
        "重点不是歌颂吃苦，也不是写消耗诊断，而是让责任、安稳、分担和回温之间的关系被看见。"
    ),
    "default_polish_instruction": (
        "如果是责任托家题材，先删掉泛中年感慨、苦难勋章和“更大目标祛魅”的通用空话，"
        "把现实接口、动作停顿、先把家里理顺的顺序、有人一起分担和家里被护住的安稳写实。"
    ),
}

TRACKED_ARTICLE_RESPONSE_PRIORITY_FOLLOWUP_TONE_OVERRIDE: dict[str, str] = {
    "opening_style": (
        "先从一句轻描淡写的话有没有被听懂切入：一张随手发的照片、一句“我没事”、一次看似平常的状态更新。"
        "先让读者认出被路过和被真正停下来理解之间的差别，不要先把镜头压成等回复、回没回或关系排位审判。"
    ),
    "paragraph_rhythm": (
        "前半篇先写点赞、表情、路过式评论这些回应为什么会让人误以为自己已经被在意，再写一句追问、一次补问、一次认真停下来怎样把人轻轻接住。"
        "段落要有松紧差，允许 2 到 3 处一句一段的人话短句，让“被读懂”的那一下自己发亮。"
        "少把“轻互动”“真正的关心”“很多时候”“其实”这类概念词放在段首做总结，前四段至少 2 段先给动作、对话或停顿，再让判断慢慢冒出来。"
        "后半篇把情绪带回安稳、珍惜和双向在乎，不要一路写成判断谁更靠前。"
    ),
    "closing_style": (
        "结尾落在被理解、被记得、被认真放在心上的安稳感上，"
        "让读者读完更暖一点、更松一点，不写成关系排名或清醒判词。"
    ),
    "value_constraints": (
        "这类稿子的情绪价值，不是教读者认清谁不值得，而是让读者重新认出真正的关心长什么样；"
        "前半篇至少留 1 到 2 处能单独成段的人话短句，其中至少 1 处要像被轻轻读懂后的松口气。"
    ),
    "default_polish_instruction": (
        "如果是评论、追问、被读懂这一类回应差别题材，先把“谁把你排在前面”“别再等了”这类关系排序句降下来，"
        "改成让被看见、被读懂、被认真追问的差别自己长出来；"
        "同时补足被理解后的安稳、珍惜和双向在乎，不要把全文修成回复等待稿。"
    ),
}


def _get_tracked_article_structure_mode(payload: Mapping[str, object] | None) -> str:
    if not isinstance(payload, Mapping):
        return ""
    strategy_card = payload.get("strategy_card")
    if not isinstance(strategy_card, Mapping):
        return ""
    return _as_clean_text(strategy_card.get("structure_mode"))


def _get_tracked_article_structure_tone_override(payload: Mapping[str, object] | None) -> Mapping[str, str] | None:
    if not _should_relax_direct_answer_rules_for_tracked_article(payload):
        return None
    structure_mode = _get_tracked_article_structure_mode(payload)
    if not structure_mode:
        return None
    if structure_mode == "responsibility_shelter" or (
        structure_mode == "everyday_warmth_return" and payload and _has_everyday_warmth_responsibility_shelter_focus(payload)
    ):
        return dict(TRACKED_ARTICLE_EVERYDAY_WARMTH_RESPONSIBILITY_TONE_OVERRIDE)
    if structure_mode == "response_priority" and payload and _uses_response_priority_followup_variant(payload):
        return dict(TRACKED_ARTICLE_RESPONSE_PRIORITY_FOLLOWUP_TONE_OVERRIDE)
    override = TRACKED_ARTICLE_STRUCTURE_TONE_OVERRIDES.get(structure_mode)
    if not override:
        return None
    return dict(override)


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

    effective = dict(tone_profile)
    changed = False

    tracked_article_tone_override = _get_tracked_article_structure_tone_override(payload)
    if tracked_article_tone_override:
        for key in ("opening_style", "paragraph_rhythm", "closing_style"):
            value = _as_clean_text(tracked_article_tone_override.get(key))
            if value:
                effective[key] = value
                changed = True
        value_constraints_override = _as_clean_text(tracked_article_tone_override.get("value_constraints"))
        if value_constraints_override:
            effective["value_constraints"] = _merge_tone_profile_text(
                _as_clean_text(effective.get("value_constraints")),
                value_constraints_override,
            )
            changed = True
        polish_override = _as_clean_text(tracked_article_tone_override.get("default_polish_instruction"))
        if polish_override:
            effective["default_polish_instruction"] = _merge_tone_profile_text(
                _as_clean_text(effective.get("default_polish_instruction")),
                polish_override,
            )
            changed = True

    if _should_apply_jinwan_youyu_internal_pressure_overrides(
        tone_profile=tone_profile,
        payload=payload,
    ):
        effective["opening_style"] = JINWAN_YOUYU_INTERNAL_PRESSURE_OPENING_STYLE
        effective["paragraph_rhythm"] = JINWAN_YOUYU_INTERNAL_PRESSURE_PARAGRAPH_RHYTHM
        effective["closing_style"] = JINWAN_YOUYU_INTERNAL_PRESSURE_CLOSING_STYLE
        effective["value_constraints"] = _merge_tone_profile_text(
            _as_clean_text(effective.get("value_constraints")),
            JINWAN_YOUYU_INTERNAL_PRESSURE_VALUE_CONSTRAINTS,
        )
        effective["default_polish_instruction"] = _merge_tone_profile_text(
            _as_clean_text(effective.get("default_polish_instruction")),
            JINWAN_YOUYU_INTERNAL_PRESSURE_POLISH,
        )
        changed = True

    return effective if changed else tone_profile


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
        "开头先落一个现实接口、被顺手往后放的安排或已经露出的代价，不要先用问句、引用或共鸣替读者下定义，",
    )
    harmonized = harmonized.replace(
        "开头用直接问题、现实接口或一句共鸣判断迅速点题，",
        "开头先落一个现实接口、被顺手往后放的安排或已经露出的代价，不要先用问句、引用或共鸣替读者下定义，",
    )
    harmonized = harmonized.replace(
        "开头优先使用问句、引用或共鸣开场，尽快把读者代入她熟悉的处境。",
        "开头先落一个现实接口、被顺手往后放的安排或已经露出的代价，不要先用问句、引用或共鸣替读者下定义。",
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
            "大纲按问题推进组织：开头引出真实卡点，中间展开判断，结尾落到新的位置感、边界或现实落点。"
            "这不是低成本三段式，开头要点破真实问题，中段要给新观察，结尾要有明确方向感。"
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
                "开头先落一个现实接口、被顺手往后放的安排或已经露出的代价，不要先用问句、引用或共鸣替读者下定义。"
                "判断可以直接，但不要一上来就把答案说成空泛结论，要让读者先认出自己正在付出的代价。"
                "前两到三段里，至少有一段只让动作、后果或现实余波自己说话，不要句句都抢着解释。"
                "前四段里，至少保住 1 处一句一段的现实接口、动作后果或被挪走的安排，让读者先被戳中，再接判断。"
                "正文中段按“现实接口 + 判断推进 + 行动落点”展开，但不要写成机械分条。"
                "每个判断都要多给一层判断依据、现实机制、情绪承接或行动落点，不能只重复标题情绪。"
                "但每个判断最多只补一层解释，解释一多就换成下一段的动作、关系变化、现实余波或现实后果。"
                "多数段落控制在 1 到 2 句，只有需要补代价、机制或现实余波时才放到 3 句；一段里只要职责变了就拆开。"
                "如果单段超过 3 句，先拆段，不要让解释盖住情绪价值。"
                "不要连续两个中长解释段挨着出现；一段偏解释，下一段就回到动作、关系余波、现实后果或现实接口。"
                "除非参考文主冲突本来就建立在身体代价上，否则不要把正文排成身体不适清单。"
                "情绪价值要落在被看见、被松绑或被轻轻推动上，不要只剩安慰话。"
                "读者默认是 25 到 45 岁女性，语言要直接有力、温暖但有边界。"
                "可以适度使用排比和对仗，但不要把句子排成整齐口号。"
                "前半篇至少保住 1 句从真实代价里长出来、可以单独成段的可摘录短句或引用式短句，但不要写成悬空口号。"
                "如果状态允许，可以再留 1 句，但要把关系位置、代价排序或没被接住的事实压进去，不要连发口号。"
                "引用名人、影视台词或理论时，全篇最多 1 到 2 处；连续两篇不能用同一个人。"
                "不要使用这些词：不禁、心想、暗想、默念、琢磨、纠结、暗自、默默。"
                "少用“像……一样”“如同”“仿佛”“宛如”“好似”这类明喻。"
                "避免“因为……所以……”“因此”“于是”“结果”这类显性因果串联。"
                "删掉“总之”“说到底”“归根结底”“值得一提的是”“不可否认”“在当今社会”这类套话。"
                "不要写“以后会好的”“明天又是新的一天”“一切都会过去”这类未来安慰句。"
                "默认不要使用“不是A，是B”句式；只有参考文核心金句本身依赖这种对照时，正文最多保留 1 次，且不能放在标题、开头或结尾。"
                "破折号整篇最多使用 2 处。"
                "不要写成逐条列举、逐项解释的导购式结构。"
                "删掉没有它也不影响前后文的空段、虚段和泛感慨段。"
                "结尾优先落在一个现实动作、后果余波、没等来的回应或轻微决定上，不要把答案写成空泛总结。"
                "尾段不要替读者把情绪讲完，尽量留一点没说满的关系余波，让人读完还想接一句“对，我那次也是这样”。"
            )
        return (
            "这篇内容采用“今晚有语”风格。"
            "开头优先用直接问题、现实接口或一句共鸣判断切入，尽快把问题和答案入口一起顶出来。"
            "不要只靠空问句、空引用或泛共鸣占住开头位置。"
            "不是让读者自己猜，你要直接把判断说出来，但要落在真实接口上。"
            "正文中段按“观点 + 依据/接口 + 推进”展开，但不要写成机械分条。"
            "每个观点都要多给一层判断依据、现实机制、情绪承接或行动落点，不能只重复标题情绪。"
            "多数段落控制在 1 到 2 句，只有需要补机制、代价或情绪承接时才放到 3 句；一段里只要职责变了就拆开。"
            "如果单段超过 3 句，先拆段，不要让解释盖住情绪价值。"
            "情绪价值要落在被看见、被松绑或被轻轻推动上，不要只剩安慰话。"
            "读者默认是 25 到 45 岁女性，语言要直接有力、温暖但有边界。"
            "可以适度使用排比和对仗，但不要把句子排成整齐口号。"
            "全文最好保住 1 处从具体处境里长出来、可以单独成段的可摘录短句或引用式表达，但不要把整篇排成截图口号合集。"
            "如果状态允许，可以再留 1 处，但不要把整篇堆成截图文案。"
            "引用名人、影视台词或理论时，全篇最多 1 到 2 处；连续两篇不能用同一个人。"
            "不要使用这些词：不禁、心想、暗想、默念、琢磨、纠结、暗自、默默。"
            "少用“像……一样”“如同”“仿佛”“宛如”“好似”这类明喻。"
            "避免“因为……所以……”“因此”“于是”“结果”这类显性因果串联。"
            "删掉“总之”“说到底”“归根结底”“值得一提的是”“不可否认”“在当今社会”这类套话。"
            "不要写“以后会好的”“明天又是新的一天”“一切都会过去”这类未来安慰句。"
            "默认不要使用“不是A，是B”句式；只有参考文核心金句本身依赖这种对照时，正文最多保留 1 次，且不能放在标题、开头或结尾。"
            "破折号整篇最多使用 2 处。"
            "不要写成逐条列举、逐项解释的导购式结构。"
            "删掉没有它也不影响前后文的空段、虚段和泛感慨段。"
            "结尾可以直接落到边界、位置感、现实落点或轻微余波上，但不要喊口号，也不要把答案写成空泛总结。"
        )
    if stage == "assets":
        return (
            "这篇内容采用“今晚有语”风格。"
            "标题备选和导语要直接点破读者最在意的问题，给出明确判断或答案入口。"
            "不要写成空泛抒情 teaser，不要只剩情绪氛围。"
            "封面文案要短、准、有抓手，最好一眼能截住读者，不要铺成小段落；保留女性成长内容的力量感。"
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


def _extract_tracked_article_response_priority_cues(
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
        score = _score_tracked_article_response_priority_cue(normalized)
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


def _extract_tracked_article_inner_settlement_cues(
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
        score = _score_tracked_article_inner_settlement_cue(normalized)
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
    if _has_response_priority_focus(payload):
        response_priority_cues = _extract_tracked_article_response_priority_cues(payload, max_items=max_items)
        if response_priority_cues:
            return response_priority_cues
    if _has_supportive_appreciation_focus(payload):
        return [
            "心软不是傻，而是明明拎得清还愿意体谅和包容",
            "那些愿意包容你的人，往往也最值得被认真珍惜",
            "真正稀缺的，不是会说漂亮话的人，而是温柔却不糊涂的人",
        ][:max_items]
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
    if _has_inner_settlement_focus(payload):
        inner_settlement_cues = _extract_tracked_article_inner_settlement_cues(payload, max_items=max_items)
        if inner_settlement_cues:
            return inner_settlement_cues
    if _has_broad_emotional_release_focus(payload):
        emotional_cues = _extract_tracked_article_emotional_cues(payload, max_items=max_items)
        if emotional_cues:
            return emotional_cues
    return _extract_tracked_article_body_cues(payload, max_items=max_items)


def _build_tracked_article_topic_summary(payload: Mapping[str, object]) -> str:
    analysis_contract = _build_tracked_article_analysis_contract(payload)
    analysis_summary = _build_analysis_first_topic_summary(analysis_contract)
    if analysis_summary:
        return analysis_summary
    if _has_response_priority_focus(payload):
        if _uses_response_priority_followup_variant(payload):
            return (
                "文章借点赞、评论和追问这些轻互动差别，讨论真正的在乎为什么不在热闹，而在有没有人愿意停下来读懂你。"
                "主线落在被看见、被读懂和被认真放在心上的安稳感上。"
            )
        return (
            "文章借日常联系里的“没时间”现象，讨论回应顺序和时间投向如何显出一个人的真实在乎程度。"
            "主线落在时间分配、回应动作和位置感判断上。"
        )
    if _has_supportive_appreciation_focus(payload):
        return (
            "文章围绕一种常被误读的柔软展开，"
            "而是那些明明拎得清、却仍愿意体谅和包容别人的人，为什么反而最值得被认真珍惜。"
        )
    if _as_clean_text(payload.get("analysis_structure_mode")) == "scene_first_progression":
        return (
            "文章重点不是先下判断，而是让读者先跟着前几段连续现场走进去，"
            "再意识到真正被压后、被带过或被撤回的那句话、那个动作或那次靠近。"
        )
    if _has_inner_settlement_focus(payload):
        if _resolve_inner_settlement_variant(payload) == "stage_restart":
            return (
                "文章借半年节点、事与愿违和身边仍在的牵挂，讨论人为什么总会在阶段回望里先否定自己。"
                "主线落在遗憾怎样被安放、眼前的人怎样把人托住，以及怎样重新接纳这个阶段的自己。"
            )
        return (
            "文章把外界起伏和内在安顿放在一起比较，"
            "主线落在心为什么一直安不下来，以及人怎样慢慢把自己放回当下。"
        )
    if _has_self_reliance_inward_support_focus(payload):
        return (
            "文章把成年人低谷里的承压感和自我支撑方式放在一起写，"
            "主线落在一个人怎样从慌乱里回神，用具体判断、行动或选择把日子一点点接回来。"
        )
    if _has_everyday_warmth_return_focus(payload):
        if _has_everyday_warmth_simple_happiness_focus(payload):
            return (
                "文章不是在反对努力，而是在重估幸福的坐标：比起不断加码财富、排场和热闹，"
                "真正让人踏实的常常是家人平安、知己仍在和日子简单。"
                "主线落在幸福为什么会被误判，以及一个人怎样把生活重心慢慢收回到眼前。"
            )
        return (
            "文章把成就叙事与慢下来后的价值重估放在一起比较，重点不是某一个具体家庭动作，"
            "而是更大的目标为什么会失重，那些总被放轻的吃饭、回家和有人惦记为什么重新显出分量。"
        )
    return _as_clean_text(payload.get("summary"))


def _build_tracked_article_topic_structure_notes(payload: Mapping[str, object]) -> str:
    analysis_contract = _build_tracked_article_analysis_contract(payload)
    analysis_structure_notes = _build_analysis_first_topic_structure_notes(analysis_contract)
    if analysis_structure_notes:
        return analysis_structure_notes
    if _has_response_priority_focus(payload):
        if _uses_response_priority_followup_variant(payload):
            return "先从点赞、评论或一句轻描淡写的话有没有被听懂切入，再拆轻互动为什么不等于真正的关心，中段把读懂、追问和补问怎样把人轻轻接住讲清，结尾回到被理解带来的踏实和珍惜。"
        return "先从“忙到没时间回应”这句常见托词切入，再拆时间为什么总会投向更在乎的人，中段把回应顺序、投入意愿和关系优先级一步步讲清。"
    if _has_supportive_appreciation_focus(payload):
        return "先写柔软为什么常被误读成好说话，中段再拆明明拎得清却仍愿意体谅和包容的分量，结尾回到这样的人为什么最值得被认真珍惜。"
    if _as_clean_text(payload.get("analysis_structure_mode")) == "scene_first_progression":
        return "先守住前两到三段连续现场，让动作、停顿和气氛带路，中段再把真正被压后的话或被撤回的表达讲明白，不要一上来平铺道理。"
    if _has_inner_settlement_focus(payload):
        if _resolve_inner_settlement_variant(payload) == "stage_restart":
            return (
                "先写阶段节点上最容易冒出来的自责和比较，再拆人为什么总会把没完成、没拥有和没赶上一起算成失败，"
                "中段回到眼前仍在身边的人、普通支撑和每个阶段自己的分量，结尾落到重新接纳此刻、带着期待继续往前。"
            )
        return "先写心为什么在阶段回望里容易悬着、自责或不甘，再拆人为什么总想把遗憾和未完成一起算成失败，中段回到当下、眼前的人和每个阶段的自己怎样重新有了位置和轻重。"
    if _has_self_reliance_inward_support_focus(payload):
        return "先服从参考文章分析出的真实入口和核心冲突，前三段内就让判断力、行动力、恢复力或主动选择出现；中段写具体自我支撑方式怎样发生，结尾回到分析合同里的正向出口，不固定补写外部缺席或求援落空。"
    if _has_everyday_warmth_return_focus(payload):
        if _has_everyday_warmth_simple_happiness_focus(payload):
            return "先写人为什么总把幸福押在更大的拥有上，再拆财富、圈子和房子为什么替代不了踏实感；中段回到知己、家人和平安日常怎样重新显出分量，结尾落到简单快乐为什么反而更难被真正守住。"
        return "先写成就叙事，再用慢下来后的价值转向做转折，中段回到眼前陪伴和日常分量，结尾回到小事为什么更重要。"
    return _as_clean_text(payload.get("structure_notes"))


def _build_tracked_article_topic_body_cue_section(payload: Mapping[str, object]) -> str:
    analysis_contract = _build_tracked_article_analysis_contract(payload)
    analysis_body_cues = _build_analysis_first_topic_body_cue_section(analysis_contract)
    if analysis_body_cues:
        return analysis_body_cues
    if _has_response_priority_focus(payload):
        if _uses_response_priority_followup_variant(payload):
            return (
                "参考文章正文抓手候选：\n"
                "- 为什么热闹互动很多，人却还是会因为少了一句追问而心里发空\n"
                "- 一个人愿不愿意停下来读懂你的言外之意，为什么比表面热络更能说明关心\n"
                "- 被看见、被读懂、被认真放在心上，为什么会把人从硬撑里轻轻放回生活\n"
                "优先围绕这些抓手类型重组新选题，让标题、角度和后续正文都继续停留在被理解、被接住和双向珍惜上。\n"
            )
        return (
            "参考文章正文抓手候选：\n"
            "- “没时间”这句话，为什么很多时候说的不是日程，而是顺序\n"
            "- 一个人把时间投向哪里，为什么比嘴上的解释更能说明在乎程度\n"
            "- 该不该继续等一个总说很忙的人，判断依据到底落在哪里\n"
            "优先围绕这些抓手类型重组新选题，让标题、角度和后续正文都继续停留在顺序、时间投向和位置感判断上。\n"
        )
    if _has_supportive_appreciation_focus(payload):
        return (
            "参考文章正文抓手候选：\n"
            "- 心软为什么不是傻，而是明明拎得清还愿意体谅和包容\n"
            "- 真正稀缺的，为什么是温柔却不糊涂、柔软却有分量的人\n"
            "- 这样的人为什么不该被误读成好说话，而更值得被认真珍惜\n"
            "优先围绕这些抓手类型重组新选题，让标题、角度和后续正文都继续停留在这个正向主题上。\n"
        )
    if _as_clean_text(payload.get("analysis_structure_mode")) == "scene_first_progression":
        return (
            "参考文章正文抓手候选：\n"
            "- 前两到三段里，哪个具体现场最能带读者走进去\n"
            "- 哪句本来该说出口的话、哪个本来可以继续的动作，被当场压回去了\n"
            "- 后面那个判断，究竟是从哪一段现场里自己长出来的\n"
            "优先围绕连续现场、动作停顿和当场撤回来重组新选题，不要把题眼先抬成抽象关系判断、人生道理或万能解释。\n"
        )
    if _has_inner_settlement_focus(payload):
        if _resolve_inner_settlement_variant(payload) == "stage_restart":
            return (
                "参考文章正文抓手候选：\n"
                "- 一到半年、年中或阶段节点，人为什么总会先清算自己，而不是先看见自己已经走了多远\n"
                "- 事与愿违、没完成和没留住，为什么常常会被一起误算成“我这段时间白过了”\n"
                "- 身边仍在的牵挂、普通支撑和被爱感，为什么会在这种时候重新把人托回生活里\n"
                "- 接纳每个阶段的自己，为什么不是认输，而是把力气还给接下来的日子\n"
                "优先围绕这些抓手类型重组新选题，让标题、角度和后续正文都继续停留在阶段回望、遗憾安放和重新出发这条主线上。\n"
            )
        return (
            "参考文章正文抓手候选：\n"
            "- 外界未必最糟时，人为什么还是会先把自己留在悬着的状态里\n"
            "- 人为什么总想先把一切想稳、想透、想明白，却忘了先把自己安放回当下\n"
            "- 一餐一饮和一呼一吸，为什么比继续拧着更能让心慢慢落地\n"
            "- 阶段性回望里，那些没完成、没赶上和事与愿违，为什么不该被一起算成“我不够好”\n"
            "优先围绕这些抓手类型重组新选题，让标题、角度和后续正文都继续停留在心安归位这条主线上。\n"
        )
    if _has_self_reliance_inward_support_focus(payload):
        return (
            "参考文章正文抓手候选：\n"
            "- 参考文里的现实触发点，究竟怎样让人一下子乱了顺序\n"
            "- 人为什么会从慌乱、承压或低谷里，慢慢找到一个能先稳住自己的动作\n"
            "- 真正把人托过去的，为什么常常是具体判断、主动选择和把日子继续接回来的能力\n"
            "优先围绕这些抓手类型重组新选题，让标题、角度和后续正文都继续停留在自我支撑、自救自渡这条主线上。\n"
        )
    if _has_everyday_warmth_return_focus(payload):
        if _has_everyday_warmth_simple_happiness_focus(payload):
            return (
                "参考文章正文抓手候选：\n"
                "- 人为什么总把好日子押在更大的拥有、更体面的配置和更热闹的人生上\n"
                "- 走到后来，真正让人踏实的为什么反而变成家人平安、知己仍在和日子简单\n"
                "- 财富、排场和热闹，为什么替代不了被记挂、被惦记和有家可回的安稳\n"
                "优先围绕这些抓手类型重组新选题，让标题、角度和后续正文继续停留在幸福观重估、生活排序回正和踏实感回归这条主线上。\n"
            )
        return (
            "参考文章正文抓手候选：\n"
            "- 成就叙事为什么会在某个阶段突然失重\n"
            "- 那些总被往后放的小日常，为什么会让人后知后觉地觉得心里空了一块\n"
            "- 慢下来以后，一顿饭、一次回家、有人惦记为什么会重新显出分量\n"
            "优先围绕这些抓手类型重组新选题，不要把题眼压回某个可直接映回原文的单一家庭场景，"
            "优先把它上提成一类真正托住人的日常分量，而不是复述参考文现成动作。\n"
        )

    body_cues = _extract_tracked_article_topic_cues(payload)
    if not body_cues:
        return ""

    cue_lines = "\n".join(f"- {cue}" for cue in body_cues)
    return (
        "参考文章正文抓手候选：\n"
        f"{cue_lines}\n"
        "优先围绕这些现实接口、身体提醒或代价线索重组新选题，不要再把它们抹平成抽象人生判断。\n"
    )


def _render_outline_target_wording(tone_profile: Mapping[str, object] | None) -> str:
    target_word_count = tone_profile.get("target_word_count") if tone_profile else None
    if not target_word_count:
        return ""
    return (
        f"目标字数：{target_word_count}\n"
        "请按目标字数规划篇幅，保证 4 到 6 段的大纲能自然支撑正文长度。\n"
        "避免在大纲阶段写得过满，每一段只保留核心推进点，不要预写过多案例、分叉解释和重复论述。\n"
        "不要写“开头/中段/结尾”标签，也不要写给作者看的命令句。\n"
        "outline_body 只写段落职责和推进动作，尽量控制在 220 字以内。\n"
    )


def _render_draft_target_wording(
    tone_profile: Mapping[str, object] | None,
    *,
    payload: Mapping[str, object] | None = None,
) -> str:
    target_word_count = tone_profile.get("target_word_count") if tone_profile else None
    if not target_word_count:
        return ""
    if payload is not None and _as_clean_text(payload.get("source_type")) == "tracked_article":
        stable_target = min(int(target_word_count), 900)
        return (
            f"目标字数：{stable_target}\n"
            "这是参考文章链路的稳定首稿目标，先写成短句清晰、情绪价值集中的发布基础稿。\n"
            "正文篇幅请严格贴近目标字数，允许上下浮动 10% 到 15%。\n"
            "如果明显超出目标字数，请主动压缩场景、避免重复抒情和重复论述。\n"
        )
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
    analysis_theme = _as_clean_text(payload.get("reference_article_analysis_theme"))
    analysis_core_conflict = _as_clean_text(payload.get("reference_article_analysis_core_conflict"))
    analysis_emotional_exit = _as_clean_text(payload.get("reference_article_analysis_emotional_exit"))
    analysis_structure_mode = _as_clean_text(payload.get("reference_article_analysis_structure_mode"))
    analysis_opening_pattern = _as_clean_text(payload.get("reference_article_analysis_opening_pattern"))
    analysis_hook_trigger = _as_clean_text(payload.get("reference_article_analysis_hook_trigger"))
    analysis_progression_drive = _as_clean_text(payload.get("reference_article_analysis_progression_drive"))
    analysis_share_reason = _as_clean_text(payload.get("reference_article_analysis_share_reason"))
    analysis_do_not_turn_into = _as_clean_text(payload.get("reference_article_analysis_do_not_turn_into"))
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
            f"参考文章分析主题：{analysis_theme or '无'}\n"
            f"参考文章核心矛盾：{analysis_core_conflict or '无'}\n"
            f"参考文章情绪出口：{analysis_emotional_exit or '无'}\n"
            f"参考文章结构模式：{analysis_structure_mode or '无'}\n"
            f"参考文章开头方式：{analysis_opening_pattern or '无'}\n"
            f"参考文章开头触发点：{analysis_hook_trigger or '无'}\n"
            f"参考文章中段推进力：{analysis_progression_drive or '无'}\n"
            f"参考文章转发理由：{analysis_share_reason or '无'}\n"
            f"参考文章不要写成：{analysis_do_not_turn_into or '无'}\n"
            f"参考文章标签：{' / '.join(tags) or '无'}\n"
        )

    return (
        "参考文章来源线索（仅用于确认赛道与冲突，不得继续沿用原文骨架）：\n"
        f"来源账号：{source_name or '手动录入'}\n"
        f"作者：{author or '未知'}\n"
        f"主题标签：{' / '.join(tags) or '无'}\n"
        f"上游分析主题：{analysis_theme or '无'}\n"
        f"上游核心矛盾：{analysis_core_conflict or '无'}\n"
        f"上游情绪出口：{analysis_emotional_exit or '无'}\n"
        f"上游结构模式：{analysis_structure_mode or '无'}\n"
        f"上游开头方式：{analysis_opening_pattern or '无'}\n"
        f"上游开头触发点：{analysis_hook_trigger or '无'}\n"
        f"上游中段推进力：{analysis_progression_drive or '无'}\n"
        f"上游转发理由：{analysis_share_reason or '无'}\n"
        f"上游不要写成：{analysis_do_not_turn_into or '无'}\n"
        "原标题、原摘要措辞和结构备注已经在上游选题阶段消化完毕，这一阶段不要再沿着原文标题骨架、开头入口或段落顺序继续展开。\n"
    )


def _has_strategy_package(payload: Mapping[str, object]) -> bool:
    problem_brief = payload.get("problem_brief")
    strategy_card = payload.get("strategy_card")
    return isinstance(problem_brief, Mapping) and isinstance(strategy_card, Mapping)


def _render_post_strategy_reference_boundary(payload: Mapping[str, object], *, stage: str) -> str:
    if stage not in {"outline", "draft", "assets", "publish_package"}:
        return ""
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return ""
    if not (_has_strategy_package(payload) or bool(payload.get("reference_article_hidden"))):
        return ""
    return (
        "参考文章已在问题说明书和策略卡阶段完成消化。"
        "从这里开始，不再提供任何来源账号、标题、摘要、标签或结构线索。"
        "你只能依据当前选题、正文任务和策略结论继续推进。"
    )


def _should_use_tracked_article_theme_first_strategy(payload: Mapping[str, object]) -> bool:
    return _as_clean_text(payload.get("source_type")) == "tracked_article" and _has_strategy_package(payload)


def _build_theme_first_execution_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _should_use_tracked_article_theme_first_strategy(payload):
        return ""

    if stage in {"outline", "draft"}:
        return (
            "先根据主题锚点卡判断这篇更适合从场景、判断、引用还是关系接口开，不要先挑一个熟悉模板再往里装内容。"
            "段落节奏、短句位置和现实抓手优先服从这篇文章自己的主题主线与正向落点。"
            "结构模式只是一层弱提示，用来防止明显跑偏，不负责把同类文章压成同一个骨架。"
            "如果通用写法习惯、平台规则或局部顺手表达和主题锚点卡冲突，以主题锚点卡、策略包和主题守卫为准，不要换题。"
        )
    if stage in {"assets", "publish_package"}:
        return (
            "包装先认主题锚点卡，再决定标题、导语、封面和摘要怎么截住读者。"
            "可摘录短句和钩子都要从正文已经成立的主线里长出来，不要为了抓眼另起一篇更顺手的泛情绪稿；不要在输出里标注“金句”。"
            "结构模式只是一层弱提示，用来防止明显跑偏，不负责把同类文章压成同一个包装骨架。"
            "如果平台包装习惯和包装锚点卡冲突，以正文主线、正向落点和包装主题守卫为准，不要为了抓眼换题。"
        )
    return ""


def _render_theme_first_execution_card(
    payload: Mapping[str, object],
    *,
    stage: str,
    compact: bool = False,
) -> str:
    if stage not in {"outline", "draft", "assets", "publish_package"}:
        return ""
    if not _should_use_tracked_article_theme_first_strategy(payload):
        return ""

    problem_brief = payload.get("problem_brief")
    strategy_card = payload.get("strategy_card")
    if not isinstance(problem_brief, Mapping) or not isinstance(strategy_card, Mapping):
        return ""

    clarified_problem = _normalize_clarified_problem(_as_clean_text(problem_brief.get("clarified_problem")))
    theme_axis = _as_clean_text(problem_brief.get("theme_axis"))
    core_conflict = _as_clean_text(problem_brief.get("core_conflict"))
    emotional_value_goal = _as_clean_text(problem_brief.get("emotional_value_goal"))
    positive_direction = _as_clean_text(strategy_card.get("positive_direction"))
    hook_trigger = _as_clean_text(strategy_card.get("hook_trigger"))
    progression_drive = _as_clean_text(strategy_card.get("progression_drive"))
    share_reason = _as_clean_text(strategy_card.get("share_reason"))
    packaging_focus = _as_clean_text(strategy_card.get("packaging_focus"))
    packaging_hook = _as_clean_text(strategy_card.get("packaging_hook"))
    opening_move = _as_clean_text(strategy_card.get("opening_move"))
    ending_move = _as_clean_text(strategy_card.get("ending_move"))
    scene_anchor_requirements_value = strategy_card.get("scene_anchor_requirements")
    quotable_line_seeds_value = strategy_card.get("quotable_line_seeds")
    scene_anchor_requirements = (
        [_as_clean_text(item) for item in scene_anchor_requirements_value if _as_clean_text(item)]
        if isinstance(scene_anchor_requirements_value, list)
        else []
    )
    quotable_line_seeds = (
        [_as_clean_text(item) for item in quotable_line_seeds_value if _as_clean_text(item)]
        if isinstance(quotable_line_seeds_value, list)
        else []
    )
    if _has_everyday_warmth_responsibility_shelter_focus(payload):
        clarified_problem = _sanitize_responsibility_shelter_prompt_text(clarified_problem)
        theme_axis = _sanitize_responsibility_shelter_prompt_text(theme_axis)
        core_conflict = _sanitize_responsibility_shelter_prompt_text(core_conflict)
        emotional_value_goal = _sanitize_responsibility_shelter_prompt_text(emotional_value_goal)
        positive_direction = _sanitize_responsibility_shelter_prompt_text(positive_direction)
        hook_trigger = _sanitize_responsibility_shelter_prompt_text(hook_trigger)
        progression_drive = _sanitize_responsibility_shelter_prompt_text(progression_drive)
        share_reason = _sanitize_responsibility_shelter_prompt_text(share_reason)
        packaging_focus = _sanitize_responsibility_shelter_prompt_text(packaging_focus)
        packaging_hook = _sanitize_responsibility_shelter_prompt_text(packaging_hook)
        opening_move = _sanitize_responsibility_shelter_prompt_text(opening_move)
        ending_move = _sanitize_responsibility_shelter_prompt_text(ending_move)
        scene_anchor_requirements = [
            _sanitize_responsibility_shelter_prompt_text(item) for item in scene_anchor_requirements
        ]
        quotable_line_seeds = [
            _sanitize_responsibility_shelter_prompt_text(item) for item in quotable_line_seeds
        ]

    if stage in {"outline", "draft"}:
        lines = ["主题锚点卡："]
        if theme_axis:
            lines.append(f"这篇真正要写的是：{_truncate_text(theme_axis)}")
        elif clarified_problem:
            lines.append(f"这篇真正要写的是：{_truncate_text(clarified_problem)}")
        if core_conflict:
            lines.append(f"真正要拆开的矛盾：{_truncate_text(core_conflict)}")
        if emotional_value_goal:
            lines.append(f"读者最后要得到：{_truncate_text(emotional_value_goal)}")
        if positive_direction:
            lines.append(f"后半篇回正到：{_truncate_text(positive_direction)}")
        if hook_trigger:
            lines.append(f"开头先停在：{_truncate_text(hook_trigger)}")
        if progression_drive:
            lines.append(f"中段主要靠这股力往前推：{_truncate_text(progression_drive)}")
        if scene_anchor_requirements:
            max_anchor_items = 2 if compact else 3
            lines.append(f"优先写出的现实抓手：{' / '.join(scene_anchor_requirements[:max_anchor_items])}")
        if quotable_line_seeds:
            lines.append(f"短句尽量从这里长出来：{' / '.join(quotable_line_seeds[:2])}")
        if opening_move:
            lines.append(f"开头先守：{_truncate_text(opening_move)}")
        if ending_move:
            lines.append(f"结尾回到：{_truncate_text(ending_move)}")
        lines.append("执行顺序：先守主题和情绪出口，再决定场景、判断和短句怎么展开，不要反过来先找一个熟悉模板往里装。")
        return "\n".join(lines) + "\n\n"

    lines = ["包装锚点卡："]
    if theme_axis:
        lines.append(f"正文主线：{_truncate_text(theme_axis)}")
    elif clarified_problem:
        lines.append(f"正文主线：{_truncate_text(clarified_problem)}")
    if core_conflict:
        lines.append(f"正文矛盾：{_truncate_text(core_conflict)}")
    if positive_direction:
        lines.append(f"最后把人带回：{_truncate_text(positive_direction)}")
    if share_reason:
        lines.append(f"这类包装之所以容易截住人，是因为：{_truncate_text(share_reason)}")
    if packaging_focus:
        lines.append(f"包装先抓：{_truncate_text(packaging_focus)}")
    elif packaging_hook:
        lines.append(f"包装先抓：{_truncate_text(packaging_hook)}")
    if quotable_line_seeds:
        lines.append(f"能截住人的真话优先从这里长出来：{' / '.join(quotable_line_seeds[:2])}")
    if ending_move:
        lines.append(f"收束气口：{_truncate_text(ending_move)}")
    lines.append("包装顺序：先守正文主线，再挑最能截住人的入口，不为抓眼再换题。")
    return "\n".join(lines) + "\n\n"


def _build_packaging_theme_alignment_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if stage not in {"assets", "publish_package"}:
        return ""
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return ""
    if not _has_strategy_package(payload):
        return ""

    strategy_card = payload.get("strategy_card")
    problem_brief = payload.get("problem_brief")
    if not isinstance(strategy_card, Mapping) or not isinstance(problem_brief, Mapping):
        return ""

    structure_mode = _as_clean_text(strategy_card.get("structure_mode"))
    clarified_problem = _as_clean_text(problem_brief.get("clarified_problem"))
    theme_axis = _as_clean_text(problem_brief.get("theme_axis"))
    writing_goal = _as_clean_text(problem_brief.get("writing_goal"))
    conflict_frame = _as_clean_text(strategy_card.get("conflict_frame"))
    ending_move = _as_clean_text(strategy_card.get("ending_move"))
    positive_direction = _as_clean_text(strategy_card.get("positive_direction"))
    share_reason = _as_clean_text(strategy_card.get("share_reason"))
    packaging_focus = _as_clean_text(strategy_card.get("packaging_focus"))
    packaging_hook = _as_clean_text(strategy_card.get("packaging_hook"))
    quotable_line_seeds_value = strategy_card.get("quotable_line_seeds")
    quotable_line_seeds = (
        [_as_clean_text(item) for item in quotable_line_seeds_value if _as_clean_text(item)]
        if isinstance(quotable_line_seeds_value, list)
        else []
    )

    base_lines = [
        "包装必须继续服务当前正文主题，不允许在标题、导语、封面文案或编辑备注阶段二次换题。",
        "先根据正文主线、正向落点和包装抓手决定标题、导语、封面和摘要，不要先挑一个更顺手的流量模板。",
    ]

    if clarified_problem:
        base_lines.append(f"当前主题问题：{clarified_problem}")
    if theme_axis:
        base_lines.append(f"当前主题主线：{theme_axis}")
    if writing_goal:
        base_lines.append(f"当前写作目标：{writing_goal}")
    if conflict_frame:
        base_lines.append(f"当前冲突主线：{conflict_frame}")
    if positive_direction:
        base_lines.append(f"标题、导语和封面最终都要把人带回这个落点：{positive_direction}")
    if share_reason:
        base_lines.append(f"这篇之所以容易让人想转发，主要因为：{share_reason}")
    if packaging_focus:
        base_lines.append(f"包装必须优先抓这个入口：{packaging_focus}")
    elif packaging_hook:
        base_lines.append(f"包装主钩子：{packaging_hook}")
    if quotable_line_seeds:
        base_lines.append(f"优先从这些真话入口起题：{' / '.join(quotable_line_seeds[:2])}")
    if ending_move:
        base_lines.append(f"当前收束方向：{ending_move}")
    base_lines.append("标题和导语要像真人会转发时写下的开口，不要写成编辑说明、万能安慰句或空泛抒情。")

    if structure_mode == "inner_settlement":
        base_lines.append(
            "如果当前正文属于心安归位、阶段回望或重新出发这条线，优先抓阶段误判、回神瞬间、继续生活和被眼前托住的分量。"
        )
    elif structure_mode == "responsibility_shelter":
        base_lines.append(
            "如果当前正文属于责任托家、先把顺序理清再把家稳住这条线，优先抓来电、安排、有人被护住和家里慢慢踏实下来的回温感。"
        )
    elif structure_mode == "everyday_warmth_return":
        base_lines.append(
            "如果当前正文属于大事祛魅、小事回归这条线，优先抓重要感失重、眼前日常回温和生活重新有分量。"
        )
    elif structure_mode == "response_priority":
        if _uses_response_priority_followup_variant(payload):
            base_lines.append(
                "如果当前正文属于轻互动里的被看见、被读懂这条线，优先抓一句追问、一次补问、一次认真停下来和被理解后的安稳感。"
            )
        else:
            base_lines.append(
                "如果当前正文属于回应顺序和时间投向这条线，优先抓顺序、时间分配、投入意愿和位置感回正。"
            )
    elif structure_mode == "supportive_appreciation":
        base_lines.append(
            "如果当前正文属于柔软被误读和值得被珍惜这条线，优先抓柔软的分量、被误读的代价和被认真珍惜的方向。"
        )
    elif structure_mode == "self_reliance_inward_support":
        base_lines.append(
            "如果当前正文属于向内求、自我支撑和自救自渡这条线，优先抓参考文自己的现实触发点、正向能力或具体行动，以及人怎样把日子接回来。"
        )
    elif structure_mode == "relationship_aftercare":
        base_lines.append(
            "如果当前正文属于争执后修复态度这条线，优先抓谁回来善后、谁接住情绪和关系有没有被继续往前带。"
        )
    elif structure_mode == "resilience_reconstruction":
        base_lines.append(
            "如果当前正文属于命运重击后的重建这条线，优先抓重击、训练、重建和不被定义。"
        )

    if stage == "assets":
        base_lines.append("标题不要套反问翻转、痛点翻转或双重否定翻转这类模板标题骨架。")
        base_lines.append("标题不要用“很多人”“有些人”“总有人”这类泛主语起手；如果原文主题必须群体概括，只能放到正文中段，不能放在交付字段开头。")
        base_lines.append("社媒导语要像真人转发前顺手写下的开场，不要写成编辑说明或空泛概述。")
        base_lines.append("社媒导语不要写成作者说明句或编辑说明句。")
        base_lines.append("社媒导语不要用群体概括句起手；先给具体入口、动作或一句能落地的回神话。")
        base_lines.append("封面文案和社媒导语只允许提炼正文已经成立的题眼，不要额外发明更抓眼但偏题的新论点。")
    if stage == "publish_package":
        base_lines.append("发布导语和导语候选要像真人转发前顺手写下的开场，不要写成编辑说明或复述正文。")
        base_lines.append("发布标题不要套反问翻转、痛点翻转或双重否定翻转这类模板标题骨架。")
        base_lines.append("发布标题不要用“很多人”“有些人”“总有人”这类泛主语起手；如果原文主题必须群体概括，只能放到正文中段，不能放在交付字段开头。")
        base_lines.append("发布导语不要用群体概括句起手；先给具体入口、动作或一句能落地的回神话。")
        base_lines.append("发布标题、发布导语、摘要和编辑备注只允许压缩正文主线，不要为了顺口把主题偷换成别的情绪赛道。")

    return "".join(base_lines)


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
            "前屏两到四段里，至少留一处一句一段的现实接口、身体信号或动作残留，不要开头就把场景、解释和答案挤在同一段。"
            "如果情绪价值已经落在判断、后果或身体反应里，就直接推进，不必先补一段没有信息增量的氛围场景。"
            "如果要留可摘录短句，它必须从前文已经写出的代价、动作或没说出口的那一下里长出来，不要凭空升空。"
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
            "开头钩子不要只拿单一关系界面做现实接口；如果保留关系接口，至少并列一个关系之外的现实抓手。"
            "前两段里至少有一段主职责必须落在关系之外的生活秩序、身体代价或已经拥有却被忽略的部分，不要把前半篇全部交给关系拉扯。"
        )
    if stage == "draft":
        base = (
            "如果参考文章重心是放下强求、珍惜已有或知足感，正文不要自动收窄成坏关系止损、分手复盘或单一关系博弈。"
            "即便出现关系例子，也只把它当成共鸣入口之一，不要让它取代“放下强求 / 停止拉扯 / 珍惜已有”的真正主线。"
            "不要把幸福写成输赢、诚意、沉没成本或关系谈判问题；要把重点落回人为什么总在失去后才看见已经拥有的部分。"
            "不要把正文压成聊天框、等回复、试探态度这一类单一关系等待戏；如果用了关系例子，后文必须把代价写回睡眠、注意力、生活节奏、朋友家人或已经拥有却被忽略的部分。"
            "至少留一段专门写“人原本已经拥有、后来却在拉扯中慢慢忽略掉的东西”，不要从头到尾只盯着那段关系有没有结果。"
            "开头第一屏不要只剩关系界面；如果保留关系接口，同段必须并列一个已经被挪走的现实抓手。"
            "正文至少要有两段不以消息、回复、对方、关系这些词为主抓手，而是直接写生活秩序、身体代价和已经到手却被拿去垫付的安稳。"
        )
        corpus = " ".join(
            part
            for part in (
                _as_clean_text(payload.get("topic_title")),
                _as_clean_text(payload.get("topic_angle")),
                _as_clean_text(payload.get("article_title")),
                _as_clean_text(payload.get("summary")),
                _as_clean_text(payload.get("structure_notes")),
                _as_clean_text(payload.get("body_markdown")),
                _as_clean_text(payload.get("reference_article_title")),
                _as_clean_text(payload.get("reference_article_summary")),
                _as_clean_text(payload.get("reference_article_structure_notes")),
                _as_clean_text(payload.get("reference_article_body_markdown")),
            )
            if part
        )
        if any(
            token in corpus
            for token in (
                "感谢相遇",
                "不谈亏欠",
                "允许一切结束",
                "接纳离开",
                "接纳结束",
                "聚散终有时",
                "关系结束",
            )
        ):
            base += (
                "如果当前题材属于关系结束后的接纳与释怀，少用“白费”“亏了”“算账”“审判自己值不值”这类过重的核账词。"
                "即便要写舍不得，也优先把重心落在相遇留下来的温暖、边界、眼界和成长怎样继续留在一个人身上。"
                "让语气更像把一段相遇轻轻安放回心里，而不是拿着结局反复给自己下判词。"
            )
        return base
    return ""


def _build_tracked_article_everyday_warmth_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_everyday_warmth_return_focus(payload):
        return ""
    simple_happiness_focus = _has_everyday_warmth_simple_happiness_focus(payload)
    responsibility_shelter_focus = _has_everyday_warmth_responsibility_shelter_focus(payload)

    if stage == "topic":
        if responsibility_shelter_focus:
            return (
                "如果参考文章重心是成年人把一家人的安稳放在心上，选题不要滑成放下执念、感谢相遇、关系回应排序或泛中年励志。"
                "标题和切入角度优先围绕：为什么很多人会先把家里理顺、责任为什么会让人多想一步、这些辛苦后来又为什么会变成家里安稳和继续往前的底气。"
                "不要把题眼压成单一苦情控诉、身体提醒复盘或“中年人有多难”的大概括，也不要只剩开销、孩子、父母这些标签堆砌。"
                "标题、切入角度和后续正文尽量贴着第二人称“你”写，少把读者推远成“她/他/他们”的旁观叙述。"
            )
        if simple_happiness_focus:
            return (
                "如果参考文章重心是幸福观重估、家人平安、知己仍在和简单快乐，"
                "不要把选题改写成哪顿饭又没吃成、哪次回家又往后放这种单点机制稿。"
                "也不要缩成“怎么安排时间”“怎么平衡工作和生活”这类工具型题目。"
                "标题和切入角度优先围绕：人为什么总把好日子押在更大的拥有上、为什么到了后来才明白家人平安和知己仍在更贵、为什么简单快乐反而最容易被忽略。"
                "可以写财富、体面、圈子、房子和热闹怎样失重，但不要把题眼再降成某一顿饭、某条消息或某个待办被改期。"
            )
        return (
            "如果参考文章重心是“大事祛魅”、日常陪伴回归和普通生活重新变重要，"
            "不要把选题收窄成身体提醒、自我照料积压或单一复查拖延主线。"
            "也不要把题眼改写成“有人等你回应”“先把关系接住”或谁被排在回应顺序后面这类关系回应排序。"
            "不要把它再抽象成“女性要重建生活托底感”“意义供给退潮后怎么办”这类泛成长标题。"
            "不要写成“女人中年以后更需要重估哪些事”这类年龄阶段提问式抽象标题。"
            "文中的手术、停下来和休养只是价值转向的触发点，不是整篇唯一主命题。"
            "标题和切入角度优先围绕成就叙事为什么会祛魅、普通陪伴为什么反而最重要来重组；"
            "不要把题眼收缩成某个可直接映回原文的单一家庭场景或日常动作名词，"
            "优先把它上提成一类真正托住人的日常分量，比如吃饭、回家、有人惦记和有人说话。"
            "尽量把这些被放轻的日常分量当成情绪证明，而不是把重点压回体检、复查和身体追债。"
        )
    if stage == "outline":
        if responsibility_shelter_focus:
            return (
                "如果参考文章重心是成年人把一家人的安稳放在心上，大纲不要缩成泛中年感慨、苦难励志或单一身体追债稿。"
                "前半篇先守住先把家里理顺的现实重量，比如来电、日历安排、请假前协调、家里要稳住的那一下；中段再写责任为什么会让人多想一步，以及这些辛苦怎样慢慢变成父母、孩子、伴侣和家里的安稳。"
                "结尾回到家还亮着、有人被护住或人终于松下一口气的回温动作，不要收成空泛正能量。"
                "整体尽量贴着第二人称“你”来推进，不要把读者写成隔着一层看的她/他/他们。"
            )
        if simple_happiness_focus:
            return (
                "如果参考文章重心是幸福观重估、家人平安和知己仍在，大纲不要自动缩成“哪件小事又被往后放了”的机制稿。"
                "前半篇先守住外在拥有为什么会慢慢失重，中段再把知己、家人和平安日常怎样托住一个人讲清。"
                "不要把主线压成消息改期、饭局取消或联系变稀的后效分析，那些最多只能做例子。"
            )
        return (
            "如果参考文章重心是“大事祛魅”和日常陪伴回归，大纲不要自动缩成身体提醒追债稿。"
            "手术、停下来和休养只能承担转折证据，主线必须回到：人为什么总把重要感押在更大的目标上，又为什么总要慢下来后才看见身边这些小事。"
            "中段至少留一段写吃饭、回家、有人惦记这些小日常怎样托住生活，不要整篇都围着身体提醒转。"
        )
    if stage == "draft":
        if responsibility_shelter_focus:
            return (
                "如果参考文章重心是成年人把一家人的安稳放在心上，正文不要滑成放下执念稿、关系回应排序稿、苦难歌颂稿或泛中年励志。"
                "真正要写的是：责任为什么会让人先把家里理顺、多想一步，以及那些认真走过的夜，后来为什么会在父母、孩子、伴侣和家里的安稳里慢慢显出意义。"
                "开头优先落先把家里稳住的现实重量：来电、日历安排、请假前协调或一次先让家人安心的回话，不要先空讲成年人都不容易。"
                "中段要把“我为什么愿意认真过好这个家”写出来，让父母变老、孩子长大、伴侣一起过日子这些现实分量自己长出来，不要只数苦，也不要只喊值。"
                "结尾回到一盏灯、一碗热汤、家里有人被护住或一句终于能松下来的回温动作，不要收成苦难勋章、万能鸡汤或自我感动。"
                "正文尽量用第二人称“你”贴住读者，除非必须保留源文语境，否则少写成第三人称旁观口吻。"
            )
        if simple_happiness_focus:
            return (
                "如果参考文章重心是幸福观重估、家人平安、知己仍在和简单快乐，正文不要滑成“被推迟的小安排”“联系慢慢变稀”或“消息没回”的机制分析。"
                "真正要写的是：为什么人总把幸福押在更多财富、更大圈子和更体面的拥有上，后来又为什么会被家人平安、知己仍在和日子踏实重新接住。"
                "开头可以用外在标准失重的那一下切入，也可以用一句朴素愿望切入，但不要再落回聊天框、待办清单或某个被改期的约。"
                "中段至少留一段专门写知己、家人或有家可回这类东西为什么比排场更能托住人，不要把它们抽成“轻联系”“小安排”这种发虚概念。"
                "结尾回到简单快乐、日子踏实、家人平安或知己仍在这类更贴近原主题的落点，不要收成冷冰冰的机制结论、关系余波或任务回填。"
            )
        return (
            "如果参考文章重心是“大事祛魅”和日常陪伴回归，正文不要把手术、休养或身体提醒写成唯一主轴。"
            "它们只是价值转向的触发点，真正要写的是：那些被高估的大事为什么会慢慢祛魅，饭桌、回家、有人惦记这些小日常为什么反而最能托住一个人。"
            "开头可以直接点破这种误认，但需要留 1 到 2 个被放轻的饭桌、回家、有人惦记或有人说话作情绪证明；不要复述参考文现成家庭动作，也不要把它们铺成大段场景。"
            "不要把这些日常温度重新写成三四个轻小动作的并列清单或排比，优先挑一个新的现实接口，把分量落在位置变化和后续影响上。"
            "不要用直给的顿悟提示句直接翻牌，让价值转向贴着前后反应、心里那一下松动和眼前日常重新被看见自己长出来。"
            "结尾回到一个还在发热的日常动作或日常决定上，不要又拐回身体提醒、自我责备或万能祝福。"
        )
    return ""


def _build_tracked_article_supportive_appreciation_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_supportive_appreciation_focus(payload):
        return ""

    if stage == "topic":
        return (
            "如果参考文章重心是柔软被误读、心软被正名和值得被珍惜，"
            "标题和切入角度优先围绕：心软为什么不是傻、柔软为什么常被误读、真正稀缺的为什么是温柔却不糊涂的人。"
            "先根据参考文的主题和矛盾组织新选题，不要跳开原文主线另起一个新问题。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是柔软被误读和被珍惜，大纲要继续围绕这条主线推进。"
            "前半篇先守住一次明明受了委屈、却还是先把话放软、先照顾别人感受的小接口，"
            "中段再写柔软为什么常被误读，以及这种明明拎得清却仍愿意体谅和包容的分量为什么最难得。"
            "结尾回到被认真回应、被珍惜或被牵紧的方向。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是柔软被误读和被珍惜，正文要继续守住这条主题主线。"
            "重点要落在：柔软为什么常被误读、明明拎得清为什么还愿意体谅和包容、这样的人为什么最值得被认真珍惜。"
            "第一屏优先把那个先放软、先让一步、先照顾别人感受的小接口顶上来，让读者先看见柔软本身，不要急着先写受伤和委屈。"
            "中段继续写柔软被误读和被重新看见的过程，结尾收在被回应、被珍惜和被看见的方向。"
        )
    return ""


def _build_tracked_article_response_priority_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_response_priority_focus(payload):
        return ""

    followup_variant = _uses_response_priority_followup_variant(payload)

    if followup_variant and stage == "topic":
        return (
            "如果参考文章重心是评论、追问、被读懂和被认真放在心上，"
            "先根据参考文里“轻互动很多，但真正让人踏实的是有人愿意停下来理解你”这条主线重组新选题。"
            "标题和切入角度优先围绕：为什么有人会路过式回应、为什么有人愿意多问一句、被读懂为什么比热闹互动更让人安稳。"
            "主线留在被看见、被理解和双向珍惜上，不转去顺序排名、关系排位判断或谁回消息更快。"
            "可以把评论、追问、读懂言外之意、一句“我没事”、一张随手发的照片这些接口当成抓手，但不要把题眼改成等回复或关系排序。"
        )
    if followup_variant and stage == "outline":
        return (
            "如果参考文章重心是评论、追问、被读懂和被认真放在心上，大纲要继续顺着这条主线推进。"
            "前半篇先守住一个轻互动差别接口，比如一句“我没事”有没有被听懂、点赞路过和认真评论的差别，或有没有人在忙完以后回来多问一句。"
            "中段至少要把“表面热闹”和“真正理解”之间的分量差别讲清。"
            "后半篇把重心带回被理解后的安稳、被认真放在心上的踏实，以及为什么要珍惜那些愿意停下来理解你的人。"
            "结尾回到被看见、被接住或双向珍惜，不要收成谁更靠前的判断题。"
        )
    if followup_variant and stage == "draft":
        return (
            "如果参考文章重心是评论、追问、被读懂和被认真放在心上，正文要继续守住这条主题主线。"
            "重点要落在：为什么点赞、表情、路过式评论都不算冷清，人还是会悬着；为什么一句追问、一次补问、一次认真听懂，会比表面热络更让人安稳。"
            "第一屏优先落一个轻描淡写的话有没有被听懂的现实差别，先让“被路过”和“被读懂”显形，不要先把镜头压成等回复、回没回或关系排位判断。"
            "可以保留 1 到 2 个现实接口，比如评论、追问、一句“我没事”、一张随手发的照片、忙完以后补回来的一句确认，但这些接口要服务于“那句没说完的话有没有被接住”，不要滑成关系排序戏。"
            "中段至少留一段把“表面互动”和“真正理解”拆开，但少下总括句，多让读者从补问、停顿、记得和回头确认里自己感觉到差别。"
            "少写“谁更在乎你”“谁把你排在前面”这种定胜负句，多让判断从追问、补问、记得和读懂这些动作里自己长出来。"
            "后半篇把情绪带回被理解后的安稳和双向珍惜：主线要稳稳落在被看见、被理解和双向珍惜上，让读者读完更暖一点，也更松一点。"
            "少用把两种互动形式硬排成高低胜负的整齐对照句；能直接写谁停下来、谁多问了一句、谁听懂了那句轻描淡写的话，就直接写。"
            "少用“一个 / 一下 / 一点 / 一些”去敲节奏，尤其不要连续几句都拿这种一字量词起手。"
            "少用“很多人”“很多女生”“很多时候”“其实”这种成熟讲解词顶段首，前四段至少 2 段先写动作或对话，再让判断出现。"
            "结尾回到被理解以后那种不用反复猜的安稳感。"
            "前六段至少留 2 处能单独成段的短句，其中 1 处最好像从现实接口里突然冒出来的真话，不要空降大道理。"
        )

    if stage == "topic":
        return (
            "如果参考文章重心是回应顺序、表层互动背后的真实在乎，"
            "先根据参考文里“顺序、追问、回应动作、在乎程度”这条主线重组新选题。"
            "标题和切入角度优先围绕：为什么表层回应常被误认成在乎、追问和回头动作怎样显出真实分量、一个人该凭什么判断自己有没有被真正放在心上。"
            "主线留在回应差别和位置感判断上，不转去争执修复或关系冷暖总论。"
            "可以把红灯30秒、回信息、回电话、点赞、评论、追问、时间在哪儿心就在哪儿这些接口当成抓手，但不要照抄原文句子。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是回应顺序、表层互动和真实在乎，大纲要继续顺着这条主线推进。"
            "前半篇先守住一个回应差别接口，比如忙到没空回应、点赞路过、评论只停在表层或有没有继续追问。"
            "中段至少要把回应顺序、追问动作、投入意愿和关系位置之间的关系讲清。"
            "后半篇把重心从等回复慢慢收回到位置感判断上，写人怎样认清顺序和分量，再把心力留给真正愿意回应的人。"
            "结尾回到判断标准或自我位置感。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是回应顺序、表层互动和真实在乎，正文要继续守住这条主题主线。"
            "重点要落在：为什么表层回应常被误认成在乎、一个人把时间和心力给了谁、追问和回头动作怎样比语言更早暴露分量。"
            "第一屏优先落一个回应接口、顺序落差或被轻轻带过的现实差别，先让回应显形，不要先把重心压成受伤诊断。"
            "可以保留 1 到 2 个现实接口，比如回消息、回电话、点赞、评论、追问、等红灯时的碎片时间，但这些接口要服务于“在乎程度如何显形”，不要滑成关系修复戏。"
            "中段至少留一段把“表层回应”和“真正愿意回应”拆开，让读者看见顺序、投入和追问本身就是答案的一部分。"
            "少写“你不重要”“他不爱你”这种一锤定音式判词，多让判断从顺序、投入、追问和回应动作里自己长出来。"
            "后半篇把情绪从等待感慢慢收回位置感：把重心落在“我以后把心力留给谁”，让读者读完更清醒，也更轻一点。"
            "少写把忙不忙和重不重要硬拧成二选一的整齐对照句；能直接写先回了谁、有没有追问、哪条消息一直挂着、哪句评论只停在表层，就直接写。"
            "少用“一个 / 一下 / 一点 / 一些”去敲节奏，尤其不要连续几句都拿这种一字量词起手。"
            "结尾回到心力该留给谁、自己该怎么认清顺序。"
            "前六段至少留 2 处能单独成段的短句，其中 1 处最好像从现实接口里突然冒出来的真话，不要空降大道理。"
        )
    return ""


def _build_tracked_article_self_worth_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_self_worth_rebuild_focus(payload):
        return ""

    if stage == "topic":
        return (
            "如果参考文章重心是自爱、自尊、自我价值和边界重新立住，"
            "标题和切入角度优先围绕：一个人怎样在关系和生活里重新尊重自己、为什么总在将就里把自己放轻、分寸重新回来后生活为什么会慢慢变稳。"
            "不要把主线改写成关系优先级审判、被敷衍控诉或回应顺序判断稿，也不要写成教人冷漠抬价的爽文套路。"
            "主线要留在自我价值感、边界、标准和自我尊重上。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是自我价值感和边界重新立住，大纲要继续顺着这条主线推进。"
            "前半篇先守住一个总在将就、讨好、顺手答应或先把自己往后放的小接口，"
            "不要把大纲自动滑成消息框、解释、善后、谁先回头沟通这类关系表达稿。"
            "中段再拆为什么一个人被怎样对待，常常和她是否尊重自己、是否守住边界有关。"
            "后半篇要把文章从受委屈感拉回自我定义：不要只问别人为什么轻慢你，要写一个人怎样把分寸放回自己手里、把精力收回自己身上。"
            "结尾回到体面、边界和自我尊重，不要滑成关系优先级判断稿。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是自爱、自尊和自我价值重建，正文要继续守住这条主题主线。"
            "重点要落在：一个人怎样在将就、讨好和自我压低里慢慢弄丢分寸，又怎样重新尊重自己的感受，让边界和标准回到自己手里。"
            "第一屏优先落一个总把自己顺手放后面的现实接口，比如一句‘都行’、一次明明不舒服却还是答应、一次明明该拒绝却先怕别人失望。"
            "第一屏不要写消息框、聊天框、打了又删、解释、善后、怕对方嫌烦这类关系沟通外壳。"
            "不要把第一屏改成‘没时间’‘回消息慢’‘优先级’这类回应顺序稿，也不要滑成谁爱不爱你的情感审判。"
            "不要把主线收窄成‘这句话要不要说’‘谁先回头沟通’‘谁先递台阶’这类关系表达稿。"
            "中段至少留一段把‘别人怎么对你，常常和你怎样对自己有关’讲透，但不要写成高位口号，要贴着原文里的将就、降级、贬值、边界让渡这些现实动作。"
            "后半篇要把情绪从受委屈感拉回自我抬升：把分寸放回自己手里，把精力留给自己和真正值得的人。"
            "结尾回到体面、边界、自我尊重和配得上，不要收成冷漠断联，也不要收成‘优先级’判断。"
        )
    return ""


def _build_tracked_article_inner_settlement_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_inner_settlement_focus(payload):
        return ""

    corpus = " ".join(
        part
        for part in (
            _as_clean_text(payload.get("article_title")),
            _as_clean_text(payload.get("summary")),
            _as_clean_text(payload.get("structure_notes")),
            _as_clean_text(payload.get("body_markdown")),
            " ".join(_as_clean_text(tag) for tag in payload.get("tags") or [] if _as_clean_text(tag)),
        )
        if part
    )
    stage_restart_hits = sum(1 for keyword in _INNER_SETTLEMENT_STAGE_RESTART_KEYWORDS if keyword in corpus)
    if stage_restart_hits >= 4:
        if stage == "topic":
            return (
                "如果参考文章重心是半年节点、阶段回望、事与愿违另有安排和重新出发，"
                "先根据参考文里“人为什么总会在阶段节点先否定自己、又怎样被身边的爱和阶段积累慢慢托住”这条主线重组新选题。"
                "标题和切入角度优先围绕阶段回望、自责误判、遗憾安放、珍惜眼前和继续往前来重组。"
                "不要把题眼改写成泛泛的心安归位、日常落地、深夜自责、关系等待或失恋复盘。"
                "标题尽量带一点“这段路没有白走”“这个阶段也有它的分量”“还能继续往前”的方向感，不要只剩诊断和悬置。"
            )
        if stage == "outline":
            return (
                "如果参考文章重心是阶段回望和重新出发，大纲要继续顺着这条主线推进。"
                "前半篇先守住阶段节点上的自我盘点、自责或比较，不要一上来缩成泛心安稿或单一关系稿。"
                "中段至少留一段写事与愿违、没完成和没留住，为什么不该被一起算成失败；也要留一段写身边仍在的爱、普通支撑或阶段积累怎样把人接回来。"
                "结尾回到接纳这个阶段的自己、继续生活和继续往前，不要落成祝福模板或逆袭宣言。"
            )
        if stage == "draft":
            return (
                "如果参考文章重心是阶段回望和重新出发，正文要继续守住这条主题主线。"
                "重点要落在：人为什么一到阶段节点就容易先否定自己，为什么总会把没完成、没拥有和没赶上一起误算成失败；又怎样被眼前仍在的人、普通支撑和阶段积累慢慢托回来。"
                "开头第一屏先落一个阶段节点上的现实接口：年初目标、这半年过得怎样、某个人还在不在、自己是不是又慢了一点。"
                "第一屏不要写成深夜翻消息、等一个回应、聊不聊得来这类关系界面，也不要滑成抽象心灵总论。"
                "前四段不要急着排成现象总结、原因拆解、结论落点都齐了的成熟讲解稿，先让那一下自我盘点、自责误判或心里发沉的现实感自己顶上来。"
                "前六段里至少留一处像人正在心里改口、停一下，或忽然意识到自己又在先怪自己的人话，不要每句都像整理好的复盘结论。"
                "不要连续两段都用“很多人”“人一到”“有些人”这类泛主体起手；群体概括用过一次后，下一段就换成你眼前的动作、当时的后果或后面留下的余波。"
                "正文标题也尽量别用“很多人”“有些人”“总有人”起手；比起总结别人，先把六月那一页、那张没勾完的清单、那句冒出来的自责写上来。"
                "中段不要连续三段都在解释为什么会这样、真正卡在哪里、所以该怎么想；讲完一个判断后，至少换一次普通动作、关系余波或生活后果。"
                "中段至少留一段把“事与愿违不等于白走一程”这件事讲透，再留一段把珍惜眼前的人和每个阶段的自己写出分量。"
                "最后两段要明显往更暖、更有力的方向走，写出继续生活、继续珍惜和继续往前的感觉，不要收成空泛祝福。"
            )
        return ""

    if stage == "topic":
        return (
            "如果参考文章重心是心安、内在归处和把自己安顿回当下，"
            "先根据参考文里“心为什么一直安不下来、又怎样慢慢放回日常”这条主线重组新选题。"
            "标题和切入角度优先围绕心为什么一直安不下来、人为什么总想先把自己说服明白或把日子安排妥帖、又怎样慢慢把自己安放回当下来重组。"
            "可以把心里慢慢落地、把心放平、与内心和解、一餐一饮、一呼一吸这些抓手当成题眼，让标题带一点回稳、回到日子里、有地方放的方向感。"
            "标题尽量给出回稳、回到日子里、有地方放的方向感，不要只剩“更难”“卡住”“悬着”这类诊断词。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是心安和内在归处，大纲要继续顺着这条主线推进。"
            "前半篇至少要守住一次“外界未必最糟，但总有一下还没被安放好”的现实卡点，再顺着为什么总想把一切想明白往下推。"
            "开头钩子不要默认写成消息没回、等一个表态、聊天框亮着、回音没来这类关系界面；如果要提外部结果，也只能当次级压力，主钩子仍要落在日常被悬置的当下接口，比如坐下来吃饭、准备睡下、收拾东西或出门前那一下心还没回来。"
            "中段必须留一段写人怎样从反复较劲、反复琢磨，慢慢回到一餐一饮和一呼一吸。"
            "前半篇尽早给读者一个被理解的落点，让读者先被接住，而不是先被分析。"
            "结尾回到心有没有放平、生活有没有重新有轻重，也要让读者感觉自己被安放回来。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是心安和内在归处，正文要继续守住这条主题主线。"
            "重点要落在：人为什么总想先把一切想稳、想透、想明白，结果反而让自己迟迟安不下来；又怎样慢慢把自己安放回当下。"
            "开头第一屏先落一个还没被安放好、却已经想慢慢回位的现实接口：终于慢下来才发现心还没坐稳、一次普通日常忽然重新有了分量，或外面热闹散了以后那颗心还没真正安顿下来的瞬间。"
            "开头优先从参考文真正的牵挂接口、回稳动作、日常归位、旧念头或仍在继续的生活入口里找等价新接口，不要固定滑向同一组室内物件，也不要固定写成没说完的话模板。"
            "第一屏不要把消息、回复、聊天框、对方回没回、等一个表态这类关系界面写成主镜头；即便正文里出现外部回应，也只能当成次级压力，不要盖过日常归位和心慢慢落回当下这条主线。"
            "第一屏最好压成 3 到 4 个短段；如果前一段已经偏长，下一段就换回一句一段的动作残留或扎心判断。"
            "前四段不要排成“先总结现象、再解释原因、再给正确答案”的匀整三步走；先让那一下误判自己、心里发紧或忽然沉下去的感觉出现。"
            "第 2 到第 4 段之间，至少要有一句直接把读者从自责、僵着或反复较劲里接住，但不要把这句写成固定安抚模板。"
            "前六段至少留 2 处能单独成段的短句，其中 1 处最好像从前文动作里突然冒出来的真话，长度尽量压在 8 到 18 个字。"
            "前六段里至少有 1 处句子要像真人写作时的停顿、改口或心里一沉，不要每句都抛光到同一种顺滑力度。"
            "不要连续两段都用“很多人”“人总是”“有些人”这类泛主体起手；群体概括用过一次后，下一段就换成动作、余波或当下接口。"
            "正文标题也尽量别用“很多人”“有些人”“总有人”起手；比起总结别人，先把那颗没放平的心、那顿没吃安稳的饭，或那一下忽然沉下去的当下写上来。"
            "中段不要连续三段都在解释为什么会这样、真正卡在哪里、所以该怎么想；讲完一个判断后，至少换一次普通动作、关系余波或生活后果。"
            "如果要留可摘录短句，优先写成贴着当前处境长出来的人话，不要空降万能金句，也不要反复复用同一句骨架。"
            "少用“很多时候”“其实”“真正”“所以”连着把句子抬成成熟讲解稿，尤其前六段不要连续三段都靠判断句往前推。"
            "正文至少留一段把心安落回一餐一饮、一呼一吸、把心放平这类日常归位，不要只写抽象豁达。"
            "中后段多写松下来、落地、重新住回日子、终于有地方放这类回暖感，少写待命、警报、被借走、拖累这类诊断口吻。"
            "除非参考文本身就把身体代价当成主冲突，否则不要顺手排成身体不适清单。"
            "最后两段至少有一段要明显比前文更暖，写出日子重新能住进去的感觉，不要继续扩写最坏后果。"
            "不要用名言抚慰、祝福收束或万能看开句直接翻牌，让“安顿回来”从现实余波和轻动作里自己长出来。"
        )
    return ""


def _build_tracked_article_self_reliance_guard_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if not _has_self_reliance_inward_support_focus(payload):
        return ""

    if stage == "topic":
        return (
            "如果参考文章重心是向内求、自我支撑、自救自渡和成年人在低谷里怎样找回判断、行动和恢复力，"
            "选题先服从参考文章分析出的主题、核心冲突和正向出口，优先写一个人已经在使用的判断力、行动力或恢复力。"
            "如果参考文确实写到外部支持缺席，也只把它当作背景压力；题眼仍要回到人怎样把力量、秩序和希望重新收回自己手里。"
            "标题和切入角度要带现实抓手，也要让读者看到主动性正在发生。"
            "标题要正向、有现实抓手，也要随参考文章变化，不固定套用安顿自己、撑过今天或把日子接回来。"
            "重点留在参考文真正讨论的自我支撑方式，不让关系表达或统一自救模板取代原文主题。"
        )
    if stage == "outline":
        return (
            "如果参考文章重心是向内求、自我支撑和自救自渡，大纲先服从分析合同中的起笔方式和推进逻辑。"
            "第一部分就让参考文对应的正向能力、选择或行动出现，把外部压力压成必要背景。"
            "开头钩子要从参考文真实入口长出来，可以是一次自我整理、一个继续行动的决定、一个把生活重新接稳的现实接口。"
            "中段重点写人怎样从被动承受走向主动处理，让冷静、沉淀、判断或行动一步步显形。"
            "正向变化最迟在第二个结构节点发生，可以是决定、行动、认知转向或关系中的主动选择，不限定为吃饭、睡觉、列清单。"
            "结尾回到分析合同指定的情绪出口，不写成关系误解、沟通边界或统一的安顿自己路线。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是向内求、自我支撑和自救自渡，正文必须先守住分析合同里的主题、起笔方式、推进驱动力和情绪出口。"
            "正文先服从参考文章分析出的主题、起笔方式、推进驱动力和情绪出口，不为自我支撑模式补写固定前史。"
            "即便出现朋友、同事或家人，也只按参考文需要安排，让人物和关系服务自我支撑这条主线。"
            "第一屏必须服从参考文章分析里的起笔方式和触发点，并在前三段内让正向能力、选择或行动出现。"
            "第一屏优先写当前文章独有的现实接口：一个决定、一个动作、一次把心绪收回来的瞬间，或一个开始重新处理生活的细节。"
            "前三段不要只陈列低谷，要让读者看见人已经开始把注意力、秩序或行动拿回来。"
            "推进时多写判断、动作、选择和现实结果怎样轮换出现，少把注意力停在等待别人回应上。"
            "每篇都要从参考文生成新的开头路径，不沿用旧的等待、求援或沟通外壳。"
            "前六段至少留 2 处能单独成段的短句，其中 1 处最好像从当前处境里突然冒出来的人话，长度尽量压在 8 到 18 个字。"
            "不要连续两段都在解释困境；动作、判断、选择和现实结果要轮换出现。"
            "自我支撑的动作、判断或能力最迟在第 3 段出现，不让负面处境占满第一屏。"
            "不要写成固定教程开场或自助说明口吻。"
            "如果要写托底动作，只挑 1 到 2 个贴着处境的动作，不要排成连续自助步骤。"
            "少用“先……先……先……”往下推整段，尤其不要连续三句都用“先”起手。"
            "同一段里如果前一句已经用了“先”，后一句尽量改成直接动作或结果，不要继续拿“先”顶着走。"
            "不要把“等……等……等……”排成三拍等待句，等待感够了就尽快切回现实阻力或回稳动作。"
            "少用“一点、一下、一件、一条”这类泛量词去托节奏，能直接写动作、物件、时间点时就直接写。"
            "一句一段也要保持句子完整，不要留下半截句、悬空转折或只起了个句头就断掉。"
            "除非参考文本身把身体代价当成主冲突，否则不要顺手排成身体不适清单。"
            "如果要留可摘录短句，优先写成贴着参考文具体处境长出来的人话，不要空降万能金句。"
            "结尾回到分析合同里的正向出口，不收成关系修复、重新开口或统一的撑过今天。"
            "最后两段要比前文更暖、更有力，让变化落实在选择、行动或正在形成的新生活里。"
            "结尾要给读者真实的力量，不只给操作建议，也不要每次都收在一个普通动作或明天再继续。"
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
    if stage == "outline":
        return (
            "如果参考文章重心是命运重击、长期疼痛、训练硬撑和不被定义后的重建，大纲不要滑成泛励志口号稿、术后恢复稿或轻量自助稿。"
            "开头先落手术台、伤口、训练动作、肩背反应或多出来的代价，不要先抬“韧性是什么”这种总论。"
            "中段至少拆两条推进：一条写身体和训练怎样一次次逼人重来，一条写她为什么没有把残缺、低谷或外界定义收成自我结论。"
            "人物事实密度高时，宁可把代价、反应和判断拆成相邻短段，也不要在单段里堆满时间线、伤痛细节和高位总结。"
            "结尾回到一个还在继续的训练动作、身体余波或没松掉的念头，不要写成赢了全世界的励志口号。"
        )
    if stage == "draft":
        return (
            "如果参考文章重心是命运重击、长期疼痛、训练硬撑和不被定义后的重建，正文不要自动改写成泛励志样板文、术后恢复文或“先照顾自己”的情绪照料稿。"
            "重点要落在：命运怎样把身体改掉，训练怎样一次次逼人重来，人又怎样在疼痛、失手和反复校正里拒绝被定义。"
            "人物事实密度高时，多用相邻短段推进：一段只守动作或代价，一段再补反应或判断；多数段落尽量压在 1 到 2 句，确实要补机制时再到 3 句。"
            "不要把手术、伤病、训练、恢复和价值判断全塞进一个长段里；一段里只要同时出现时间跳跃、身体代价和结论，就主动拆开。"
            "只要一个段落里同时出现三类以上信息，比如手术/伤病事实、训练动作、身体反应、心理判断、价值结论，就必须拆成至少两个相邻短段。"
            "凡是超过 4 句的人物事实段，先检查能不能在第 2 句或第 3 句后直接断开，把动作和代价留前面，把判断和余波放后面。"
            "像“多划11下”这类辨识度很高的数字抓手，全文原样最多出现 1 次；后文再提，改成“那11下”“那组补回来的动作”这类就地指代。"
            "可以保留 1 处从训练动作、身体余波或不被定义里长出来的短句，但不要连发励志口号。"
            "结尾回到一个还在继续的训练动作、身体反应或没松掉的念头上，不要写成“你也是自己的太阳”这类高位鼓劲句。"
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
            "标题和第一屏都不要写成稳妥复述或解释性总括，优先把“吵完以后还得自己把日子接回去”“一句别闹了把人说哑了”这类会扎人的关系代价顶上来。"
            "第一屏最好压成 3 个短段：先抛现实动作，再给一句扎人的判断，最后补一个关系后果，不要让开头连续两段都在解释。"
            "少写“真正伤人的不是……”或“关系不是输在……而是输在……”这类整齐翻转句，让判断从谁先把话咽回去、谁先试探、谁装作没事这些动作里自己长出来。"
            "如果选题标题或切入角度本身还带着“不是……而是……”式对照句，正文标题、开头和中段判断都要主动改写，不要顺手沿用。"
            "可以保留 1 到 2 个日常接口，比如第二天照常上班、做饭、回消息，但这些接口只用来证明“善后长期落在一个人身上”，不要把主线改成自我照料提醒。"
            "前五段至少要有 2 处能单独成段的短句，其中 1 处最好像关系里的实话或心里弹出来的一句人话，长度尽量压在 8 到 20 个字。"
            "前六段最好至少有 3 处能单独成段的短句，其中 1 处要像截图里能单独被记住的那句真话。"
            "前四段如果有解释性中长段，下一段就立刻换回一句一段的动作残留、关系判断或没被接住的后果，不要让第一屏连续两段都在平铺讲理。"
            "前半篇最好留 1 句把关系位置、委屈顺位或单人善后的代价压成一句的短句，但这句话必须从前文动作里长出来，不要空降金句。"
            "不要复用‘别人/旁人会觉得你……’这种外部评价壳子，尤其不要顺着‘会觉得你’去接人格判断；需要写外界误读时，改成具体反应、脸色、误判动作或一句现实回应。"
            "能拆成两段的长段就拆，尤其是首屏和中段转折位；多数段落优先守 1 到 2 句，单段一旦同时在做场景、解释、判断三件事，就直接拆开。"
            "结尾回到一个没被接住的动作、沉默或没等来的回应上，不要用“先把自己排回前面”这类泛自我成长结论收束。"
            "最后两段尽量一短一长，最后一句落在没等来的回应、没接住的动作或一句偏冷的真话上，不要把尾声收得太软。"
            "尾段不要急着教人怎么成熟、怎么放下，宁可收在一句没说完的话、一个没等来的回应，或还在继续装作没事的小动作上。"
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
                "正文先落一个具体动作、关系界面、物件、场景或当下卡点，再慢慢带出判断，不要开头先解释题眼。",
                "把抽象情绪压回动作停顿、空间距离、环境声、关系张力和现实余波，不要写成谁都能套用的万能感悟。",
                "至少写出两条可见推进：什么先触发，人当场怎么反应，后面留下什么变化、牵挂或延迟影响。",
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
            "优先从一个具体、可感知的瞬间起笔，让动作、环境、声音、关系张力或当下卡点先出现，再带出判断。",
            "不要先复述题眼或给观点下定义，先把读者带进一个可见、可听、可感的当下。",
            "把抽象情绪落到动作停顿、物件光线、空间距离、关系变化或现实余波上，让情绪有抓手。",
            "正文至少完成两条看得见的因果链：什么先触发，人当场怎么反应，后面留下什么变化、牵挂或延迟影响。",
            "每 2 到 3 段至少复用一个稳定抓手：同一个物件、界面、空间位置、时间节点或身体信号，让文本像沿着同一现实表面推进。",
            "少用“生活、感情、成长、幸福、重要的事”这类对所有人都成立的大词，优先写这篇稿子内部能反复指认的小动作、小术语和局部流程。",
            "允许出现少量偏说明性的句子，把事情为什么会变成这样讲清楚，但说明必须贴着前文细节走，不要拔高成大道理。",
            "如果一个段落只剩观点，就把它改写成过程：谁先触发、当时怎么反应、后来留下什么后果。",
            "正文不要写成标准答案式观点罗列，要让场景、情绪和判断自然推进。",
            "避免每段都写成“观点句 + 解释句”的模板结构，至少让一处段落先发生事情，再慢慢显出判断。",
            "默认拆掉“不是A，是B”这类过于整齐的判断句，改成具体处境、动作、停顿或后果；不要拿它做标题、开头或结尾。",
            "标题禁止使用“不是A，而是B”或“不是A，只是B”这类对称判断句。",
            "如果选题标题或参考文章标题已经含有这类句式，正文标题必须改成具体处境入口，不要继续复用“不是、而是、只是”的判断骨架。",
            "正文主干也不要反复用双重否定替关系行为找圆场。",
            "全篇最多保留 1 处“不是……”判断，并且不要放在开头第一屏或结尾段；需要转折时改写成“更常见的情况是”“真正卡住的地方在”“她当时先感到的是”等自然表达。",
            "减少“第一步、第二步、第三步”式教程骨架，优先写成自然展开的叙事或观察推进。",
            "不要为了显得完整而过度解释每一个判断，允许留白，允许有些意思停在动作或场景里。",
            "避免反复用“一点、一下、一些、一个、一种”去切分感受和动作，同一种量词节奏不要整篇反复出现。",
            "“一点、一下、一些、一个、一种、一件、一句、一段”这类一字量词全篇尽量控制在 5 处以内；能写具体动作、时间、物件和空间距离时，不要用泛化量词。",
            "不要每隔一两段就单独插一个很短的判断段或敲钟段，全篇这类独立短判断段最多保留 1 处；如果某句确实能把前文代价压成一句可摘录短句，优先让它单独成段，但前后必须有具体处境支撑。",
            "如果某个短段只是为了提醒、点题、转折或抒情，优先并回前后场景段，让判断从细节里慢慢浮出来。",
            "允许保留 1 到 3 个很短的独立段，但前提是它们必须落在具体动作、物件、身体反应或一句没接上的话上，不是拿来单独敲道理。",
            "如果要单独留一个短段，它应该像阻力线、动作残留，或一处从前文动作和代价里长出来的可摘录短句，而不是“很多人就是这样”“真正难的是……”这类万能判断。",
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
                "结尾不要为了传播性硬设计空口号金句，优先收在一个普通动作、关系余波或还没完全说满的感受上；如果要留一句能被记住的话，也必须贴着前文处境长出来。",
            ]
        )
    if stage == "draft":
        if compact:
            return (
                "删掉“说到底”“归根结底”“某种程度上”“很多时候”这类填充短语，让动作和事实直接顶上来。"
                "能写两项就不要硬凑三项并列；不要用模糊归因和宏大意义替代具体处境。"
                "少写“先说结论”“接下来我们来看”“真正的问题是”这类结构路标。"
                "如果一句话太像现成金句，先确认它是不是贴着前文动作或后果长出来的；如果不是，就拆回动作、场景或后果，不要单独抬成结论段。"
            )
        return "".join(
            [
                "删掉“说到底”“归根结底”“某种程度上”“很多时候”这类填充短语，让动作、事实和后果直接出现，不要先垫一个万能过渡再说正题。",
                "能写两项就不要硬凑三项并列；如果一句话里只是为了显得完整才排出三个近义判断，优先删掉最像装饰的那一项。",
                "不要用模糊归因、泛泛权威或空归因替代具体处境，能落回人物动作、对话、时间节点和现实反馈时，就不要拿抽象权威兜底。",
                "不要频繁宣布写作动作，比如“先说结论”“接下来我们来看”“真正的问题是”“说句实话”；少解释你要怎么讲，多直接把事实和后果推上来。",
                "不要把普通处境硬拔成时代缩影、重要转折或更宏大的意义，先把这一个人、这一个动作、这一次延迟写清楚。",
                "如果一句话读起来像现成金句或适合被单独截图传播，先判断它是不是从具体处境里长出来的；如果不是，就拆回动作、场景、反应或后果。允许保留 1 处可摘录短句，最好单独成段，但不要把空结论单独抬成一段。",
            ]
        )
    return ""


def _build_localized_ai_flavor_risk_instructions(*, compact: bool = False) -> str:
    if compact:
        diagnosis_signals = get_dbskill_rule_lines("diagnosis", "signals")
        compact_signals = "".join(diagnosis_signals[:2]) if diagnosis_signals else ""
        return (
            "静默排查中文公众号高风险 AI 味：不要匀速排比、段段收束、万能抒情、教程分步、连续短判断或过度解释。"
            "额外排查解释型公众号 AI 腔：不要写先宣布答案、先标注难点或先替读者分类的讲解台词。"
            "不要频繁写结构路标，也不要用模糊归因或泛泛权威偷懒兜底。"
            "如果某处太像一次性写完的标准成稿，优先删总括、降结论、改成过程或普通动作。"
            + compact_signals
        )
    base = (
        "按中文公众号 AI 味风险检查表达："
        "套话风险，避免万能成长句、万能抒情和空泛金句；"
        "结构模板风险，避免整齐反转、教程分步、总括式泛感慨过渡句、单句敲钟段和标准答案式段落；"
        "句式节奏风险，避免同一种量词、连接词和判断句反复起手；"
        "段落节拍风险，避免“短句点一下 + 下一段长解释”反复交替，避免每段都解释到位；"
        "解释型公众号 AI 腔风险，避免先宣布答案、先标注难点或先替读者分类的讲解台词，降低第二人称讲理密度；"
        "结构路标风险，避免先宣布写作动作的路标句；"
        "模糊归因风险，避免泛泛权威和空归因；"
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
            brief_steps[:1],
            divergence_checks[:1],
            execution_protocol[:2],
            self_checklist[:2],
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
            "不要用先宣布答案、先标注难点或先替读者降调的讲解台词。"
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
        "不要写成解释型公众号 AI 腔：开头不要先反问替读者分类，中段不要先宣布答案或标注难点，后段不要先替读者降调。"
        "降低第二人称讲理密度，能换成作者判断、局部事实或更短承接时，不要连续对“你”解释。"
        "开头如果已经有现实接口、后果或身体信号，就直接从那里推进，不要先用分类讲稿替读者总结。"
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


def _build_tracked_article_structure_priority_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    if stage not in {"outline", "draft"}:
        return ""
    if not _should_relax_direct_answer_rules_for_tracked_article(payload):
        return ""

    strategy_card = payload.get("strategy_card")
    if not isinstance(strategy_card, Mapping):
        return ""

    structure_mode = _as_clean_text(strategy_card.get("structure_mode"))
    if not structure_mode:
        return ""

    if stage == "outline":
        return (
            "这是一篇参考文章改写稿，而且当前已经有策略包。"
            "主题主线、核心矛盾、情绪出口和现实接口的优先级，高于通用的厂牌风格惯性。"
            "结构模式只负责兜底防跑偏，不负责把所有同类文章写成同一个模板。"
            "如果通用风格里的“直接给答案”“标准三段式”“结尾落结论”与当前策略冲突，优先服从策略包。"
            "不同主题可以用不同推进法，不要把所有稿子都压回同一套判断节拍。"
        )
    return (
        "这是一篇参考文章改写稿，而且当前已经有策略包。"
        "主题主线、核心矛盾、情绪出口和现实接口的优先级，高于通用的厂牌风格惯性。"
        "结构模式只负责兜底防跑偏，不负责把所有同类文章写成同一个模板。"
        "如果通用风格里的“直接给答案”“标准三段式”“结尾落结论”与当前策略冲突，优先服从策略包。"
        "允许不同主题保留不同的推进速度、段落形状和情绪落点，不要把所有稿子都压回同一种成熟讲解腔。"
        "责任托家这类稿子优先用第二人称“你”贴住读者，少把正文写成第三人称旁观叙述。"
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
        "独立短段尽量压到 2 处以内；如果要保留 1 处可摘录短句，必须来自前文已有动作、代价或关系余波，优先单独成段，其余短判断段照并。"
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
        "独立短段尽量压到 2 处以内，确实要留的短段只保留动作残留、身体反应、没接上的一句话，或 1 处从前文代价里长出来的可摘录短句。"
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


def _looks_like_outline_instruction_fragment(text: str) -> bool:
    candidate = re.sub(r"\s+", " ", str(text or "")).strip()
    if not candidate:
        return False
    if re.match(r"^(?:开头|中段(?:[一二三四五六七八九十\d]+)?|前半篇|后半篇|结尾|尾段|标题|导语|正文)(?:[：:]\s*|$)", candidate):
        return True
    return bool(
        re.search(
            r"(?:写清楚|点出|说明|交代|拆开|收束到|不要(?:先)?(?:写成|复用|回收|直接|安排|把|用)|不写成|不要在)",
            candidate,
        )
    )


def _extract_outline_anchor_lines(outline_body: str, *, max_items: int = 6, max_length: int = 42) -> list[str]:
    anchors: list[str] = []
    for raw_line in outline_body.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", raw_line).strip()
        line = re.sub(r"^\s*[-*+]\s*", "", line)
        line = re.sub(r"^\s*\d+[.)、]\s*", "", line)
        line = re.sub(r"\s+", " ", line).strip()
        if not line:
            continue
        section_match = re.match(r"^(?:开头|中段(?:[一二三四五六七八九十\d]+)?|前半篇|后半篇|结尾|尾段|标题|导语|正文)(?:[：:]\s*(.*))?$", line)
        if section_match:
            line = re.sub(r"^(?:开头|中段(?:[一二三四五六七八九十\d]+)?|前半篇|后半篇|结尾|尾段|标题|导语|正文)[：:]\s*", "", line).strip()
            if not line:
                continue
        if _looks_like_outline_instruction_fragment(line):
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


def _render_strategy_package_section(
    payload: Mapping[str, object],
    *,
    compact: bool = False,
    extra_compact: bool = False,
    minimal_compact: bool = False,
) -> str:
    problem_brief = payload.get("problem_brief")
    strategy_card = payload.get("strategy_card")
    benchmarks = payload.get("benchmarks")

    if not isinstance(problem_brief, Mapping) or not isinstance(strategy_card, Mapping):
        return ""

    clarified_problem = _normalize_clarified_problem(_as_clean_text(problem_brief.get("clarified_problem")))
    observed_phenomenon = _as_clean_text(problem_brief.get("observed_phenomenon"))
    writing_goal = _as_clean_text(problem_brief.get("writing_goal"))
    emotional_value_goal = _as_clean_text(problem_brief.get("emotional_value_goal"))
    theme_axis = _as_clean_text(problem_brief.get("theme_axis"))
    anti_drift_axis = _as_clean_text(problem_brief.get("anti_drift_axis"))
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
    positive_direction = _as_clean_text(strategy_card.get("positive_direction"))
    hook_trigger = _as_clean_text(strategy_card.get("hook_trigger"))
    progression_drive = _as_clean_text(strategy_card.get("progression_drive"))
    share_reason = _as_clean_text(strategy_card.get("share_reason"))
    quotable_line_goal = _as_clean_text(strategy_card.get("quotable_line_goal"))
    packaging_focus = _as_clean_text(strategy_card.get("packaging_focus"))
    packaging_hook = _as_clean_text(strategy_card.get("packaging_hook"))
    realism_texture_goal = _as_clean_text(strategy_card.get("realism_texture_goal"))
    structure_mode = _as_clean_text(strategy_card.get("structure_mode"))
    opening_move = _as_clean_text(strategy_card.get("opening_move"))
    body_shift = _as_clean_text(strategy_card.get("body_shift"))
    ending_move = _as_clean_text(strategy_card.get("ending_move"))
    recomposition_recipe_value = strategy_card.get("recomposition_recipe")
    benchmark_summary = _as_clean_text(strategy_card.get("benchmark_summary"))
    expression_constraints_value = strategy_card.get("expression_constraints")
    divergence_axes_value = strategy_card.get("divergence_axes")
    execution_checklist_value = strategy_card.get("execution_checklist")
    scene_anchor_requirements_value = strategy_card.get("scene_anchor_requirements")
    quotable_line_seeds_value = strategy_card.get("quotable_line_seeds")
    writing_texture_notes_value = strategy_card.get("writing_texture_notes")
    recomposition_recipe: list[str] = []
    expression_constraints: list[str] = []
    divergence_axes: list[str] = []
    execution_checklist: list[str] = []
    scene_anchor_requirements: list[str] = []
    quotable_line_seeds: list[str] = []
    writing_texture_notes: list[str] = []
    if isinstance(recomposition_recipe_value, list):
        recomposition_recipe = [_as_clean_text(item) for item in recomposition_recipe_value if _as_clean_text(item)]
    if isinstance(expression_constraints_value, list):
        expression_constraints = [_as_clean_text(item) for item in expression_constraints_value if _as_clean_text(item)]
    if isinstance(divergence_axes_value, list):
        divergence_axes = [_as_clean_text(item) for item in divergence_axes_value if _as_clean_text(item)]
    if isinstance(execution_checklist_value, list):
        execution_checklist = [_as_clean_text(item) for item in execution_checklist_value if _as_clean_text(item)]
    if isinstance(scene_anchor_requirements_value, list):
        scene_anchor_requirements = [
            _as_clean_text(item) for item in scene_anchor_requirements_value if _as_clean_text(item)
        ]
    if isinstance(quotable_line_seeds_value, list):
        quotable_line_seeds = [_as_clean_text(item) for item in quotable_line_seeds_value if _as_clean_text(item)]
    if isinstance(writing_texture_notes_value, list):
        writing_texture_notes = [_as_clean_text(item) for item in writing_texture_notes_value if _as_clean_text(item)]
    if _has_everyday_warmth_responsibility_shelter_focus(payload):
        clarified_problem = _sanitize_responsibility_shelter_prompt_text(clarified_problem)
        observed_phenomenon = _sanitize_responsibility_shelter_prompt_text(observed_phenomenon)
        writing_goal = _sanitize_responsibility_shelter_prompt_text(writing_goal)
        emotional_value_goal = _sanitize_responsibility_shelter_prompt_text(emotional_value_goal)
        theme_axis = _sanitize_responsibility_shelter_prompt_text(theme_axis)
        target_reader_situation = _sanitize_responsibility_shelter_prompt_text(target_reader_situation)
        core_conflict = _sanitize_responsibility_shelter_prompt_text(core_conflict)
        feedback_entry = _sanitize_responsibility_shelter_prompt_text(feedback_entry)
        reader_situation = _sanitize_responsibility_shelter_prompt_text(reader_situation)
        point_of_view = _sanitize_responsibility_shelter_prompt_text(point_of_view)
        conflict_frame = _sanitize_responsibility_shelter_prompt_text(conflict_frame)
        emotional_path = _sanitize_responsibility_shelter_prompt_text(emotional_path)
        positive_direction = _sanitize_responsibility_shelter_prompt_text(positive_direction)
        hook_trigger = _sanitize_responsibility_shelter_prompt_text(hook_trigger)
        progression_drive = _sanitize_responsibility_shelter_prompt_text(progression_drive)
        share_reason = _sanitize_responsibility_shelter_prompt_text(share_reason)
        quotable_line_goal = _sanitize_responsibility_shelter_prompt_text(quotable_line_goal)
        packaging_focus = _sanitize_responsibility_shelter_prompt_text(packaging_focus)
        packaging_hook = _sanitize_responsibility_shelter_prompt_text(packaging_hook)
        realism_texture_goal = _sanitize_responsibility_shelter_prompt_text(realism_texture_goal)
        opening_move = _sanitize_responsibility_shelter_prompt_text(opening_move)
        body_shift = _sanitize_responsibility_shelter_prompt_text(body_shift)
        ending_move = _sanitize_responsibility_shelter_prompt_text(ending_move)
        benchmark_summary = _sanitize_responsibility_shelter_prompt_text(benchmark_summary)
        constraints = [_sanitize_responsibility_shelter_prompt_text(item) for item in constraints]
        recomposition_recipe = [_sanitize_responsibility_shelter_prompt_text(item) for item in recomposition_recipe]
        expression_constraints = [_sanitize_responsibility_shelter_prompt_text(item) for item in expression_constraints]
        divergence_axes = [_sanitize_responsibility_shelter_prompt_text(item) for item in divergence_axes]
        execution_checklist = [_sanitize_responsibility_shelter_prompt_text(item) for item in execution_checklist]
        scene_anchor_requirements = [
            _sanitize_responsibility_shelter_prompt_text(item) for item in scene_anchor_requirements
        ]
        quotable_line_seeds = [
            _sanitize_responsibility_shelter_prompt_text(item) for item in quotable_line_seeds
        ]
        writing_texture_notes = [
            _sanitize_responsibility_shelter_prompt_text(item) for item in writing_texture_notes
        ]

    inner_settlement_variant = _resolve_inner_settlement_variant(payload)

    if compact:
        lines = ["创作策略包（执行摘要）："]
        if clarified_problem:
            lines.append(f"问题澄清：{_truncate_text(clarified_problem)}")
        if observed_phenomenon:
            lines.append(f"观察焦点：{_truncate_text(observed_phenomenon)}")
        elif writing_goal:
            lines.append(f"写作目标：{_truncate_text(writing_goal)}")
        if theme_axis:
            lines.append(f"主题主线：{_truncate_text(theme_axis)}")
        if emotional_value_goal:
            lines.append(f"情绪回报：{_truncate_text(emotional_value_goal)}")
        if positive_direction:
            lines.append(f"正向落点：{_truncate_text(positive_direction)}")
        if share_reason and not minimal_compact:
            lines.append(f"转发理由：{_truncate_text(share_reason)}")
        if target_reader_situation and not extra_compact:
            lines.append(f"读者定位：{_truncate_text(target_reader_situation)}")
        if conflict_frame and not extra_compact:
            lines.append(f"冲突框架：{_truncate_text(conflict_frame)}")
        if emotional_path and not extra_compact:
            lines.append(f"情绪路径：{_truncate_text(emotional_path)}")
        if anti_drift_axis:
            lines.append(f"漂移禁区：{_truncate_text(anti_drift_axis)}")
        if quotable_line_goal and not extra_compact:
            lines.append(f"短句目标：{_truncate_text(quotable_line_goal)}")
        if packaging_focus and not extra_compact:
            lines.append(f"包装抓手：{_truncate_text(packaging_focus)}")
        if packaging_hook and not minimal_compact:
            lines.append(f"包装主钩子：{_truncate_text(packaging_hook)}")
        if writing_texture_notes:
            lines.append(f"写法纹理：{' / '.join(writing_texture_notes[:2])}")
        if scene_anchor_requirements:
            lines.append(f"现实接口：{' / '.join(scene_anchor_requirements[:2])}")
        if realism_texture_goal and not extra_compact:
            lines.append(f"真实质感：{_truncate_text(realism_texture_goal)}")
        if quotable_line_seeds and not extra_compact:
            lines.append(f"短句种子：{' / '.join(quotable_line_seeds[:2])}")
        structure_mode_label, structure_mode_execution = _describe_structure_mode(
            structure_mode,
            inner_settlement_variant=inner_settlement_variant,
        )
        if structure_mode_label:
            lines.append(f"结构模式：{structure_mode_label}")
            lines.append(f"结构执行：{_truncate_text(structure_mode_execution)}")
        if opening_move:
            lines.append(f"开头动作：{_truncate_text(opening_move)}")
        if body_shift:
            lines.append(f"中段推进：{_truncate_text(body_shift)}")
        if ending_move:
            lines.append(f"结尾动作：{_truncate_text(ending_move)}")
        if recomposition_recipe and not extra_compact:
            lines.append(f"替代骨架：{' / '.join(recomposition_recipe[:3])}")
        if expression_constraints:
            constraint_limit = 2 if extra_compact else 3
            lines.append(f"表达约束：{' / '.join(expression_constraints[:constraint_limit])}")
        if divergence_axes:
            divergence_limit = 2 if extra_compact else 3
            lines.append(f"主动拉开距离：{' / '.join(divergence_axes[:divergence_limit])}")
        if execution_checklist and not extra_compact:
            lines.append(f"执行检查：{' / '.join(execution_checklist[:3])}")
        if benchmark_summary and not minimal_compact:
            lines.append(f"参考基准：{_truncate_text(benchmark_summary)}")
        if not minimal_compact:
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
    if emotional_value_goal:
        lines.append(f"情绪回报：{emotional_value_goal}")
    if theme_axis:
        lines.append(f"主题主线：{theme_axis}")
    if anti_drift_axis:
        lines.append(f"漂移禁区：{anti_drift_axis}")
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
    if positive_direction:
        lines.append(f"正向落点：{positive_direction}")
    if hook_trigger:
        lines.append(f"开头触发点：{hook_trigger}")
    if progression_drive:
        lines.append(f"中段推进力：{progression_drive}")
    if share_reason:
        lines.append(f"转发理由：{share_reason}")
    if quotable_line_goal:
        lines.append(f"短句目标：{quotable_line_goal}")
    if packaging_focus:
        lines.append(f"包装抓手：{packaging_focus}")
    if packaging_hook:
        lines.append(f"包装主钩子：{packaging_hook}")
    if writing_texture_notes:
        lines.append(f"写法纹理：{' / '.join(writing_texture_notes)}")
    if scene_anchor_requirements:
        lines.append(f"现实接口：{' / '.join(scene_anchor_requirements)}")
    if realism_texture_goal:
        lines.append(f"真实质感：{realism_texture_goal}")
    if quotable_line_seeds:
        lines.append(f"短句种子：{' / '.join(quotable_line_seeds)}")
    structure_mode_label, structure_mode_execution = _describe_structure_mode(
        structure_mode,
        inner_settlement_variant=inner_settlement_variant,
    )
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
    if _has_everyday_warmth_responsibility_shelter_focus(payload):
        borrow_focuses = [_sanitize_responsibility_shelter_prompt_text(item) for item in borrow_focuses]
        avoid_focuses = [_sanitize_responsibility_shelter_prompt_text(item) for item in avoid_focuses]

    if borrow_focuses:
        lines.append(f"可借动作：{' / '.join(dict.fromkeys(borrow_focuses))}")
    if avoid_focuses:
        lines.append(f"避开项：{' / '.join(dict.fromkeys(avoid_focuses))}")

    lines.append("原创距离最低要求：同时改掉标题骨架、开头入口、中段推进顺序和结尾动作，缺一项就继续重写。")
    lines.append("执行时只保留这些策略结论，不回看参考文章原始标题、摘要、段落顺序或问题说明书全文。")

    return "\n".join(lines) + "\n\n"


def _build_strategy_resonance_instructions(
    payload: Mapping[str, object],
    *,
    stage: str,
    compact: bool = False,
) -> str:
    problem_brief = payload.get("problem_brief")
    strategy_card = payload.get("strategy_card")
    if not isinstance(problem_brief, Mapping) or not isinstance(strategy_card, Mapping):
        return ""

    emotional_value_goal = _as_clean_text(problem_brief.get("emotional_value_goal"))
    theme_axis = _as_clean_text(problem_brief.get("theme_axis"))
    anti_drift_axis = _as_clean_text(problem_brief.get("anti_drift_axis"))
    positive_direction = _as_clean_text(strategy_card.get("positive_direction"))
    quotable_line_goal = _as_clean_text(strategy_card.get("quotable_line_goal"))
    packaging_focus = _as_clean_text(strategy_card.get("packaging_focus"))
    packaging_hook = _as_clean_text(strategy_card.get("packaging_hook"))
    realism_texture_goal = _as_clean_text(strategy_card.get("realism_texture_goal"))
    scene_anchor_requirements_value = strategy_card.get("scene_anchor_requirements")
    quotable_line_seeds_value = strategy_card.get("quotable_line_seeds")
    writing_texture_notes_value = strategy_card.get("writing_texture_notes")
    scene_anchor_requirements = (
        [_as_clean_text(item) for item in scene_anchor_requirements_value if _as_clean_text(item)]
        if isinstance(scene_anchor_requirements_value, list)
        else []
    )
    quotable_line_seeds = (
        [_as_clean_text(item) for item in quotable_line_seeds_value if _as_clean_text(item)]
        if isinstance(quotable_line_seeds_value, list)
        else []
    )
    writing_texture_notes = (
        [_as_clean_text(item) for item in writing_texture_notes_value if _as_clean_text(item)]
        if isinstance(writing_texture_notes_value, list)
        else []
    )
    if _has_everyday_warmth_responsibility_shelter_focus(payload):
        emotional_value_goal = _sanitize_responsibility_shelter_prompt_text(emotional_value_goal)
        theme_axis = _sanitize_responsibility_shelter_prompt_text(theme_axis)
        positive_direction = _sanitize_responsibility_shelter_prompt_text(positive_direction)
        quotable_line_goal = _sanitize_responsibility_shelter_prompt_text(quotable_line_goal)
        packaging_focus = _sanitize_responsibility_shelter_prompt_text(packaging_focus)
        packaging_hook = _sanitize_responsibility_shelter_prompt_text(packaging_hook)
        realism_texture_goal = _sanitize_responsibility_shelter_prompt_text(realism_texture_goal)
        scene_anchor_requirements = [
            _sanitize_responsibility_shelter_prompt_text(item) for item in scene_anchor_requirements
        ]
        quotable_line_seeds = [
            _sanitize_responsibility_shelter_prompt_text(item) for item in quotable_line_seeds
        ]
        writing_texture_notes = [
            _sanitize_responsibility_shelter_prompt_text(item) for item in writing_texture_notes
        ]

    notes: list[str] = []
    if stage == "draft":
        if theme_axis:
            notes.append(
                f"这篇真正要守住的主题主线：{_truncate_text(theme_axis) if compact else theme_axis}"
            )
        if anti_drift_axis:
            notes.append(
                f"这次不要漂去这条邻近假主题："
                f"{_truncate_text(anti_drift_axis) if compact else anti_drift_axis}"
            )
        if emotional_value_goal:
            notes.append(
                f"正文必须服务这个情绪回报："
                f"{_truncate_text(emotional_value_goal) if compact else emotional_value_goal}"
            )
        if positive_direction:
            notes.append(
                f"结尾必须落回这个正向方向："
                f"{_truncate_text(positive_direction) if compact else positive_direction}"
            )
        else:
            notes.append("结尾必须比前文更暖一点，给人被稳住、能继续往前的感觉。")
        if writing_texture_notes:
            limit = 2 if compact else 3
            notes.append(f"写法纹理优先守这几条：{' / '.join(writing_texture_notes[:limit])}")
        if scene_anchor_requirements:
            limit = 2 if compact else len(scene_anchor_requirements)
            notes.append(f"前六段至少把这些现实抓手写出来：{' / '.join(scene_anchor_requirements[:limit])}")
        if realism_texture_goal:
            notes.append(
                f"正文真实质感要求："
                f"{_truncate_text(realism_texture_goal) if compact else realism_texture_goal}"
            )
        if quotable_line_goal:
            notes.append(
                "如果要留可摘录短句，只允许 1 到 2 处，并且要满足："
                f"{_truncate_text(quotable_line_goal) if compact else quotable_line_goal}"
            )
        if quotable_line_seeds:
            limit = 2 if compact else len(quotable_line_seeds)
            notes.append(f"短句优先从这些位置长出来：{' / '.join(quotable_line_seeds[:limit])}")
        notes.append("不要把全文写成持续下坠、持续控诉或持续反刍；低点可以写，但后半篇必须开始回正。")
        return "".join(notes)

    if stage in {"assets", "publish_package"}:
        if theme_axis:
            notes.append(f"包装继续服务这条正文主线：{theme_axis}")
        if anti_drift_axis:
            notes.append(f"包装不要漂去：{anti_drift_axis}")
        if packaging_focus:
            notes.append(f"包装必须优先抓这个入口：{packaging_focus}")
        if packaging_hook:
            notes.append(f"包装主钩子要明显落在这里：{packaging_hook}")
        if writing_texture_notes:
            notes.append(f"包装也要守住这组写法纹理：{' / '.join(writing_texture_notes[:2])}")
        if positive_direction:
            notes.append(f"标题、导语和封面最终都要把人带回这个落点：{positive_direction}")
        notes.append("不要只把正文改写成摘要；至少要有一个更抓人的入口、一个更清楚的误判或一个更暖的回收。")
        return "".join(notes)

    return ""


def _describe_structure_mode(
    structure_mode: str, *, inner_settlement_variant: str = ""
) -> tuple[str, str]:
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
            "先抽出参考文自己的误认、执念或价值偏差，再展开判断与现实答案；默认不铺生活场景。",
        )
    if structure_mode == "scene_first_progression":
        return (
            "场景优先推进",
            "先让一到两个连续场景带路，再逐步展开判断，不要直接平铺成并列观点段。",
        )
    if structure_mode == "responsibility_shelter":
        return (
            "责任托家回温推进",
            "先守住来电、账单、安排调整和家里那一下先得稳住的现实接口，再顺着为什么总会先把顺序理清、这些认真怎样慢慢落成一家人的踏实往下推。",
        )
    if structure_mode == "everyday_warmth_return":
        return (
            "大事祛魅后的小事回归",
            "先拆成就叙事为什么会失重，再让饭桌、回家、有人惦记这些小日常慢慢重新显出分量。",
        )
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            return (
                "阶段回望再出发推进",
                "先守住阶段节点上的自我盘点和误判，再顺着为什么总把没完成、没拥有和没赶上一起算成失败，慢慢写到眼前支撑怎样把人接回来。",
            )
        return (
            "心安归位推进",
            "先守住那一下还没被安放好的现实接口，再沿着向外求稳到慢慢住回日常的路径往下推。",
        )
    if structure_mode == "self_reliance_inward_support":
        return (
            "向内求自救推进",
            "先守住参考文里的现实触发点，再沿着回稳、自我修复和具体行动怎样把人托回来的路径往下推。",
        )
    if structure_mode == "response_priority":
        return (
            "回应顺序显形推进",
            "先守住等待和找补里的顺序落差，再让时间投向、回应动作和投入意愿自己把位置感显出来。",
        )
    if structure_mode == "trust_boundary":
        return (
            "信任边界推进",
            "先守住信任出现裂缝的那一下，再写隐瞒、坦诚和说到做到怎样决定一段关系能不能继续让人心安。",
        )
    if structure_mode == "supportive_appreciation":
        return (
            "柔软珍惜推进",
            "先守住一次明明受了委屈却还是先把话放软的小接口，再让柔软为什么常被误读、为什么值得被认真珍惜慢慢显出来。",
        )
    if structure_mode == "relationship_aftercare":
        return (
            "争执后修复态度推进",
            "先守住争执后的空白、沉默或回避接口，再沿着有没有人回来沟通、有没有人接住失望往下推。",
        )
    if structure_mode == "resilience_reconstruction":
        return (
            "命运重击后的重建推进",
            "先守住重击、疼痛和训练代价，再让重复重来和拒绝被定义慢慢把人物托起来。",
        )
    return ("", "")


def _build_structure_mode_instructions(payload: Mapping[str, object], *, stage: str) -> str:
    strategy_card = payload.get("strategy_card")
    if not isinstance(strategy_card, Mapping):
        return ""
    structure_mode = _as_clean_text(strategy_card.get("structure_mode"))
    inner_settlement_variant = _resolve_inner_settlement_variant(payload)
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
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            if stage == "outline":
                return (
                    "若策略包要求阶段回望再出发推进，大纲先守住一个阶段节点上的自我盘点、自责或比较，"
                    "再顺着为什么总把没完成、没拥有和没赶上一起算成失败往下推。"
                    "中段至少留一段写眼前仍在的爱、普通支撑或阶段积累怎样把人接回来。"
                    "结尾回到接纳这个阶段的自己、继续生活和继续往前，不要写成励志口号或万能祝福。"
                )
            if stage == "draft":
                return (
                    "若策略包要求阶段回望再出发推进，正文第一屏先落一个阶段节点上的现实接口：某张清单、某个目标、某段时间、某个结果或某句先冒出来的自责。"
                    "不要先滑成深夜等回应、关系回忆、身体症状或抽象心灵总论。"
                    "前四段先让那一下阶段误判和心里发沉自己顶上来，不要一上来就排成成熟复盘稿。"
                    "中段至少留一段把“没完成、没拥有和没赶上，不等于这段路白走了”讲透，再留一段把眼前仍在的人、普通支撑或阶段积累写出分量。"
                    "最后两段明显往继续生活、继续珍惜和继续往前回正，不要收成空泛祝福或逆袭宣言。"
                )
        if stage == "outline":
            return (
                "若策略包要求心安归位推进，大纲先守住一个外界未必最糟、心却一直没松下来的时刻，"
                "再顺着为什么总想把一切想明白、又怎样把自己慢慢放回一餐一饮和一呼一吸往下推。"
                "前半篇尽量早点给读者一个被理解、被接住的落点。"
                "不要把大纲改写成关系等待、身体提醒或幸福定义翻案稿。"
            )
        if stage == "draft":
            return (
                "若策略包要求心安归位推进，正文第一屏先落一个还没被安放好的现实接口，"
                "不要先写等待回应、界面提醒或幸福大道理。"
                "第一屏要围绕当前策略卡和上游分析真正指向的牵挂接口重建，不要把不同主题统一压回同一组室内物件。"
                "第一屏最好压成 3 到 4 个短段；长段后面立刻接一句一段的动作或判断，不要连续两段都在平铺解释。"
                "第 2 到第 4 段之间就要给一次情绪承接，让读者感觉自己被理解，而不是被分析。"
                "前六段至少要冒出 2 处能单独成段的短句，其中 1 处要像从动作里长出来的人话，不要把全文写成一片匀速长段。"
                "中段围绕心为什么一直拧着、人怎样慢慢把自己放回当下推进；"
                "最后两段至少有一段要写日常回温，不要把尾声继续压在失序和最坏结果上。"
                "判断尽量压回轻动作和现实余波里，不要写成空泛看开文，也不要一路写成内耗诊断。"
                "除非参考文冲突本来就建在身体代价上，否则不要顺手排成身体不适清单。"
            )
    if structure_mode == "responsibility_shelter" or (
        structure_mode == "everyday_warmth_return" and _has_everyday_warmth_responsibility_shelter_focus(payload)
    ):
        if stage == "outline":
            return (
                "若策略包要求责任托家推进，大纲先写肩上责任带来的现实重量，"
                "比如来电、日历安排、请假前协调、复查预约或家里那一下先得理顺。"
                "中段再把责任为什么会让人多想一步，以及这些辛苦怎样慢慢变成父母、孩子、伴侣和家里的安稳讲清。"
                "不要把大纲压成苦难励志、身体追债或泛中年感慨。"
            )
        if stage == "draft":
            return (
                "若策略包要求责任托家推进，正文第一屏先落肩上责任带来的现实重量，"
                "比如来电、日历安排、请假前协调、家里先得稳住的那一下，不要先空讲成年人都不容易。"
                "前四段里至少有两段只写动作、对话或后果，不要连续两段都在解释责任。"
                "可以保留一句像“我来安排”这样当场会说出口的人话，不要全改成作者替读者总结。"
                "中段先写电话挂断后要挪的会、要接的人和要补的饭，再让责任为什么会把一个家的顺序慢慢理顺自己长出来。"
                "不要把中段写成苦难陈列、身体提醒清单或关系回应排序讲解。"
                "结尾收在家里仍亮着的一盏灯、一碗热汤、有人被护住或一句终于能松下来的回话上，让安稳自己落地。"
            )
    if structure_mode == "everyday_warmth_return":
        if stage == "outline":
            return (
                "若策略包要求大事祛魅后的小事回归推进，大纲先写成就叙事或重要感为什么慢慢失重，"
                "再把家人平安、知己仍在和有人可回去的日常重新接回来。"
                "不要把大纲压成家庭动作清单、身体提醒追债稿或关系回应排序稿。"
            )
        if stage == "draft":
            return (
                "若策略包要求大事祛魅后的小事回归推进，正文先写重要感为什么总被押在更大的目标上，"
                "再让家人平安、知己仍在和日常分量慢慢回到眼前。"
                "不要把中段写成三四个家庭动作并列清单，也不要滑成身体提醒或关系排序讲解稿。"
                "结尾收在一个还带着温度的日常动作或日常决定上，让人感觉生活重新有了轻重，不要靠祝福或顿悟翻牌。"
            )
    if structure_mode == "response_priority":
        if stage == "outline":
            return (
                "若策略包要求回应顺序显形推进，大纲先守住等待、找补和顺序落差，"
                "再让时间投向、回应动作和投入意愿把位置感慢慢写出来。"
                "主线留在顺序判断和位置感回正上。"
            )
        if stage == "draft":
            return (
                "若策略包要求回应顺序显形推进，正文第一屏先落一个回应接口或顺序落差，"
                "不要先下“爱不爱”“重不重要”的总判词。"
                "中段围绕时间投向、回应动作和投入意愿推进，让判断从接口里自己长出来；"
                "后半篇把情绪从等待感拉回位置感，不只是写受伤，而是写人怎样慢慢认清顺序、把时间留给值得的人。"
                "结尾回到位置感回正和时间该留给谁，不写成苦情控诉。"
            )
    if structure_mode == "trust_boundary":
        if stage == "outline":
            return (
                "若策略包要求信任边界推进，大纲先守住一句谎言、一次隐瞒或一次迟到的交代让信任裂开的那一下，"
                "再顺着怀疑怎样长出来、坦诚怎样把心安补回来往下推。"
                "不要写成回消息速度、点赞评论、争吵善后或纯放下过去。"
            )
        if stage == "draft":
            return (
                "若策略包要求信任边界推进，正文第一屏先落一个关系里信任被动摇的现实接口，"
                "比如一句没说清的话、一次迟到的坦白、一个后来才知道的隐瞒；不要从回消息、点赞评论或读懂你起手。"
                "中段围绕信任为什么贵、隐瞒为什么会留下疙瘩、坦诚和说到做到怎样重新给人心安推进；"
                "结尾回到珍惜那份敢信你的赤诚，也回到自己怎样把信任交给值得的人，不要收成苦情控诉。"
            )
    if structure_mode == "supportive_appreciation":
        if stage == "outline":
            return (
                "若策略包要求柔软珍惜推进，大纲先守住一次明明受了委屈却还是先把话放软、先照顾别人感受的小接口，"
                "再顺着柔软为什么常被误读、明明拎得清为什么还愿意体谅和包容往下推。"
                "结尾回到被认真回应、被珍惜或被牵紧的方向，让柔软的分量被看见。"
            )
        if stage == "draft":
            return (
                "若策略包要求柔软珍惜推进，正文第一屏先落那个先让一步、先把话放软的小接口，"
                "先让读者看见这个人为什么温柔却不糊涂，为什么会在乎却仍有分寸。"
                "中段围绕柔软为什么常被误读、明明拎得清为什么还愿意体谅和包容推进；"
                "结尾收在被认真回应、被珍惜或重新看见这种柔软分量的方向，把温暖落到一个具体回应上。"
            )
    if structure_mode == "relationship_aftercare":
        if stage == "outline":
            return (
                "若策略包要求争执后修复态度推进，大纲先守住一次争执后的空白、沉默或回避接口，"
                "再顺着谁先把话咽回去、谁愿意回头沟通、谁在接住失望往下推，让关系的重量从动作里自己显出来。"
                "不要把大纲改写成泛自我成长稿，也不要写成两边都有道理的平均讲解稿。"
            )
        if stage == "draft":
            return (
                "若策略包要求争执后修复态度推进，正文第一屏先落一个争执过后的关系余波接口，"
                "不要先抽象讲“爱不爱”或“成熟关系”。"
                "中段围绕谁先把话咽回去、谁先恢复正常、谁先试探气氛、谁愿意回来沟通推进；"
                "少写“真正伤人的不是……”这类整齐翻转句，让判断从动作里自己显出来；"
                "结尾只收在一个没被接住的动作、沉默或回应上，不要写成泛自我疗愈答案。"
            )
    if structure_mode == "resilience_reconstruction":
        if stage == "outline":
            return (
                "若策略包要求命运重击后的重建推进，大纲先守住重击、疼痛或训练代价，"
                "再沿着重复训练怎样逼人重来、人物为什么不肯被定义往下推。"
                "不要改写成术后恢复、自我照料提醒或泛励志答案稿。"
            )
        if stage == "draft":
            return (
                "若策略包要求命运重击后的重建推进，正文第一屏先落一个重击后的硬事实、训练动作或身体代价，"
                "不要先讲励志大道理。"
                "中段围绕疼痛、训练、重来和不被定义推进，让力量感从过程里自己长出来；"
                "结尾收在还在继续的动作、身体余波或不肯松掉的念头上，不要写成口号或万能鼓劲话。"
            )
    if structure_mode == "self_reliance_inward_support":
        if stage == "outline":
            return (
                "若策略包要求向内求或自我支撑推进，大纲先服从参考文章分析里的起笔方式、核心冲突和情绪出口，"
                "第一部分就安排一种正在发生的正向能力、选择或行动，不默认补写外求落空的前史。"
                "不要滑成关系里说不出口、需求包装、边界沟通或被误解退缩稿。"
            )
        if stage == "draft":
            return (
                "若策略包要求向内求或自我支撑推进，正文第一屏服从参考文章分析里的真实入口，"
                "前三段内就让判断力、行动力、恢复力或主动选择显形，让主镜头落在当前文章独有的现实接口上。"
                "关系或外部压力只作必要背景，不抢走向内求、自我支撑和正向变化的主线。"
                "前六段至少留 2 处能单独成段的短句，其中 1 处最好像从现实接口里突然冒出来的人话。"
                "不要连续两段都在平铺解释，动作、判断、选择和现实结果要轮换出现。"
                "负面处境只保留主题所需的最小背景，全文重心始终放在正向变化怎样真实发生。"
                "独立短句也要写成完整人话，不要为了节奏故意留半截句、悬空转折或没落地的句头。"
                "中段围绕参考文真正讨论的自我支撑方式推进，不固定套用向内稳住或自救自渡；"
                "不要改写成关系里越解释越沉默、越想开口越说不出口的表达退缩稿，也不要写成一味硬扛的口号。"
                "结尾服从分析合同里的正向出口，让读者获得清醒、温暖和继续向前的力量。"
            )
    if structure_mode == "emotional_engine_direct":
        if stage == "outline":
            return (
                "若策略包要求情绪发动机直接推进，大纲默认不规划场景段，"
                "先拆参考文自己的误认、执念、舍不得或价值偏差，再整理情绪出口和现实答案。"
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
            return (
                "若策略包强调场景优先推进，大纲前两到三行先沿同一个现场顺着动作、停顿、物件或位置变化往前走，"
                "再安排判断。"
                "判断必须从现场里自己长出来，不要第二行就改成泛关系结论，也不要直接平铺观点。"
            )
        if stage == "draft":
            return (
                "若策略包强调场景优先推进，正文前两到三段必须继续沿同一个现场顺着动作、停顿、物件、界面或位置变化往前走，"
                "不要第一段给场景、第二段立刻抽象讲“很多人”“关系里”“其实”。"
                "判断要从当场没说出口、没继续做下去或被压回去的那一下里慢慢长出来，再逐步展开，"
                "不要直接平铺观点，也不要写成标准答案讲解稿。"
            )
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


def _should_use_tracked_article_strategy_first_draft_mode(
    payload: Mapping[str, object],
    *,
    is_polish_mode: bool,
) -> bool:
    if is_polish_mode:
        return False
    if bool(payload.get("timeout_recovery_mode")):
        return False
    if bool(payload.get("compact_strategy_mode")):
        return False
    if _as_clean_text(payload.get("source_type")) != "tracked_article":
        return False
    return _has_strategy_package(payload)


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


def _build_tracked_article_strategy_first_draft_owner_instructions(
    *,
    tone_profile: Mapping[str, object] | None,
) -> str:
    lines = [
        "当前任务是参考文章策略稿的首稿阶段。",
        "这一轮先服从策略卡、大纲锚点和主题守卫，把主题、结构模式、情绪落点和现实接口写准。",
        "不要抢着把去 AI 味、平台包装、漂亮收尾和完整示范文腔一次做满；这些放到后面的精修和自动校正阶段。",
        "允许局部短句、停顿、改口和没讲满的地方存在，不要把每段都磨成宽度一致的成熟讲解段。",
        "优先写出有真话感、有位置感、有现实阻力的一版，再让后处理去拆模板和清残留。",
    ]
    if _is_jinwan_youyu_style(tone_profile):
        lines.append("仍然保持直接、温暖、有边界的底色，但首稿先保真话和抓手，不抢着把厂牌节拍写满。")
    return "".join(lines)


def _build_focused_quality_retry_prompt(
    payload: Mapping[str, object],
    *,
    current_draft: Mapping[str, object],
    tone_profile: Mapping[str, object] | None,
    polish_instruction: str,
) -> PromptTemplate:
    problem_brief = payload.get("problem_brief")
    strategy_card = payload.get("strategy_card")
    problem = problem_brief if isinstance(problem_brief, Mapping) else {}
    strategy = strategy_card if isinstance(strategy_card, Mapping) else {}
    theme_axis = _as_clean_text(problem.get("theme_axis"))
    anti_drift_axis = _as_clean_text(problem.get("anti_drift_axis"))
    positive_direction = _as_clean_text(strategy.get("positive_direction"))
    structure_mode = _as_clean_text(strategy.get("structure_mode"))
    target_wording = _render_draft_target_wording(tone_profile, payload=payload)
    instructions = (
        "你是中文公众号终稿编辑。当前正文已经完成主题分析，本轮只做聚焦质量修复，不重新套模板，也不另起主题。"
        "保留已有事实、人物关系和现实场景；直接修掉病句、重复字、截断对话、作者说明、过密推进词和重复翻转句。"
        "多数段落保持一到三句，补足信息和情绪推进时使用新的现实阻力、家人反馈或动作后果，不重复原观点凑字数。"
        "结尾必须落回当前主题的正向回报，但不要写万能祝福或漂亮口号。"
        "只返回 title 与 body_markdown，不解释修改过程。"
    )
    prompt = (
        f"选题标题：{_as_clean_text(payload.get('topic_title'))}\n"
        f"项目标题：{_as_clean_text(payload.get('project_title'))}\n"
        f"结构模式：{structure_mode or '沿用当前正文'}\n"
        f"主题主线：{theme_axis or '沿用当前正文'}\n"
        f"禁止漂移：{anti_drift_axis or '不要换题'}\n"
        f"正向落点：{positive_direction or '沿用当前正文已成立的落点'}\n"
        f"{target_wording}"
        f"本轮必须修复：{polish_instruction}\n"
        f"当前标题：{_as_clean_text(current_draft.get('title'))}\n"
        f"当前正文：\n{_as_clean_text(current_draft.get('body_markdown'))}\n"
        "返回：\n1. 标题 title\n2. 正文 markdown body_markdown"
    )
    return PromptTemplate(instructions=instructions, prompt=prompt)


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


def _build_tracked_article_timeout_recovery_draft_instructions(payload: Mapping[str, object]) -> str:
    return (
        "你是公众号作者。只返回 JSON 对象，字段 title 和 body_markdown。"
        "正文 700 到 900 字，短段落，有正向情绪价值，保留 1 到 2 句金句。"
        "语言像真人，具体、温暖，不卖惨，不成功学。"
    )


def _build_tracked_article_timeout_recovery_requirement(payload: Mapping[str, object]) -> str:
    if _has_everyday_warmth_responsibility_shelter_focus(payload):
        return "守住责任怎样落回家里踏实这条线，写现实开销、父母孩子和家人安心，不要写成吃苦赞歌。"
    if _has_broad_emotional_release_focus(payload):
        return "守住放下强求、珍惜已有或接纳结束这条线，不要缩成等回复、坏关系复盘或单一关系输赢。"
    if _has_inner_settlement_focus(payload):
        return "守住心安、从容和把心安放回日常这条线，不要改成关系试探、工作崩溃或身体告警。"
    if _has_self_reliance_inward_support_focus(payload):
        return "守住向内求、自救自渡和先把自己稳住这条线，不要改成没人回应或单一关系冷落。"
    if _has_response_priority_focus(payload):
        return "守住被认真回应、被读懂和双向在意这条线，不要只写发消息等回复。"
    if _has_supportive_appreciation_focus(payload):
        return "守住珍惜柔软、回应善意和双向珍重这条线，不要把好脾气写成好欺负。"
    if _has_relationship_aftercare_focus(payload):
        return "守住争执后的态度和关系修复这条线，不要把它写成单方忍让或冷处理总结。"
    if _has_resilience_reconstruction_focus(payload):
        return "守住韧性、重建和向上生长这条线，不要写成苦难崇拜。"
    topic_angle = _as_clean_text(payload.get("topic_angle"))
    if topic_angle:
        return f"贴住当前切口：{_truncate_text(topic_angle, max_length=76)}。不要套用其它主题。"
    return "贴住当前选题和大纲推进，不要套用责任、关系等待或自我消耗等其它主题。"


def _render_tracked_article_timeout_recovery_draft_prompt(payload: Mapping[str, object]) -> str:
    outline = payload.get("outline")
    project_title = _as_clean_text(payload.get("project_title")) or _as_clean_text(payload.get("topic_title"))
    lines = [f"主题：{project_title}"] if project_title else []

    hook = _as_clean_text(outline.get("hook")) if isinstance(outline, Mapping) else ""
    topic_angle = _as_clean_text(payload.get("topic_angle"))
    if hook:
        lines.append(f"开头：{_truncate_text(hook, max_length=44)}")
    elif topic_angle:
        lines.append(f"开头：{_truncate_text(topic_angle, max_length=52)}")

    problem_brief = payload.get("problem_brief")
    if isinstance(problem_brief, Mapping):
        theme_axis = _as_clean_text(problem_brief.get("theme_axis"))
        if theme_axis:
            lines.append(f"主线：{_truncate_text(theme_axis, max_length=72)}")
        core_conflict = _as_clean_text(problem_brief.get("core_conflict"))
        if core_conflict:
            lines.append(f"冲突：{_truncate_text(core_conflict, max_length=64)}")

    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping):
        positive_direction = _as_clean_text(strategy_card.get("positive_direction"))
        if positive_direction:
            lines.append(f"正向落点：{_truncate_text(positive_direction, max_length=64)}")

    requirement = _build_tracked_article_timeout_recovery_requirement(payload)
    lines.append(f"要求：{requirement}短句清晰，有现实动作，不要照搬原文，不要写成卖惨或成功学。")
    return "\n".join(line for line in lines if line)


def _build_outline_timeout_recovery_instructions() -> str:
    return (
        "你是公众号内容策划编辑。"
        "只返回一个 JSON 对象，包含 hook 和 outline_body。"
        "hook 1 句；outline_body 写 4 段 markdown 大纲，每段 1 行。"
        "不要解释。"
    )


def _render_outline_timeout_recovery_brief(
    payload: Mapping[str, object],
    *,
    tone_profile: Mapping[str, object] | None,
) -> str:
    strategy_card = payload.get("strategy_card")
    if not isinstance(strategy_card, Mapping):
        return ""

    lines: list[str] = []
    hook_trigger = _as_clean_text(strategy_card.get("hook_trigger"))
    if hook_trigger:
        opening = hook_trigger.replace("开头先停在：", "").replace("开头先停在", "").strip()
        lines.append(f"开头：{_truncate_text(opening, max_length=22)}")
    lines.append("中段：把它为什么会这样、代价落在哪、现实怎么顶上来写清楚。")
    positive_direction = _as_clean_text(strategy_card.get("positive_direction"))
    if positive_direction:
        ending = positive_direction.replace("结尾回到", "回到").strip()
        lines.append(f"结尾：{_truncate_text(ending, max_length=18)}")
    lines.append("不要写成鸡汤。")
    return "\n".join(lines) + "\n\n"


def build_outline_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    strategy_first_outline_mode = bool(payload.get("strategy_first_outline_mode"))
    outline_timeout_recovery_mode = bool(payload.get("outline_timeout_recovery_mode"))
    raw_tone_profile = payload.get("tone_profile")
    tone_profile = (
        _build_effective_tone_profile(raw_tone_profile, payload=payload)
        if isinstance(raw_tone_profile, Mapping)
        else None
    )
    if outline_timeout_recovery_mode:
        return PromptTemplate(
            instructions=_build_outline_timeout_recovery_instructions(),
            prompt=(
                f"标题：{payload['project_title']}\n"
                f"{_render_outline_timeout_recovery_brief(payload, tone_profile=tone_profile)}"
                "返回 JSON：hook, outline_body。"
            ),
        )
    style_section = render_tone_profile_section(tone_profile)
    preset_stage_instructions = _build_jinwan_youyu_stage_instructions(
        stage="outline",
        tone_profile=tone_profile,
        payload=payload,
    )
    theme_first_execution_instructions = _build_theme_first_execution_instructions(payload, stage="outline")
    pressure_topic_tweak = _build_jinwan_youyu_pressure_topic_tweak(stage="outline", payload=payload)
    content_skill_instructions = build_content_skill_instructions(stage="outline", payload=payload)
    target_wording = _render_outline_target_wording(tone_profile)
    reference_article_section = (
        ""
        if _has_strategy_package(payload)
        else _render_reference_article_section(payload, stage="outline")
    )
    post_strategy_reference_boundary = _render_post_strategy_reference_boundary(payload, stage="outline")
    theme_first_execution_card = _render_theme_first_execution_card(
        payload,
        stage="outline",
        compact=strategy_first_outline_mode,
    )
    strategy_package_section = _render_strategy_package_section(
        payload,
        compact=strategy_first_outline_mode,
        extra_compact=strategy_first_outline_mode,
    )
    reference_article_instructions = _build_reference_article_instructions(stage="outline")
    original_expression_instructions = _build_original_expression_instructions(stage="outline")
    humanizer_zh_review_instructions = _build_humanizer_zh_review_instructions(stage="outline")
    tracked_article_structure_priority_instructions = _build_tracked_article_structure_priority_instructions(
        payload, stage="outline"
    )
    structure_mode_instructions = _build_structure_mode_instructions(payload, stage="outline")
    recomposition_recipe_instructions = _build_recomposition_recipe_instructions(payload, stage="outline")
    pressure_guard_instructions = _build_tracked_article_pressure_guard_instructions(payload, stage="outline")
    emotional_release_guard_instructions = _build_tracked_article_emotional_release_guard_instructions(payload, stage="outline")
    everyday_warmth_guard_instructions = _build_tracked_article_everyday_warmth_guard_instructions(payload, stage="outline")
    response_priority_guard_instructions = _build_tracked_article_response_priority_guard_instructions(payload, stage="outline")
    supportive_appreciation_guard_instructions = _build_tracked_article_supportive_appreciation_guard_instructions(payload, stage="outline")
    self_worth_guard_instructions = _build_tracked_article_self_worth_guard_instructions(payload, stage="outline")
    inner_settlement_guard_instructions = _build_tracked_article_inner_settlement_guard_instructions(payload, stage="outline")
    self_reliance_guard_instructions = _build_tracked_article_self_reliance_guard_instructions(payload, stage="outline")
    resilience_guard_instructions = _build_tracked_article_resilience_guard_instructions(payload, stage="outline")
    relationship_aftercare_guard_instructions = _build_tracked_article_relationship_aftercare_guard_instructions(payload, stage="outline")
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="内容策划编辑",
            task_brief="请基于给定选题，输出一个适合女性情感成长公众号的文章大纲。",
            domain_pack=payload.get("domain_pack"),
        )
        + preset_stage_instructions
        + theme_first_execution_instructions
        + pressure_topic_tweak
        + content_skill_instructions
        + original_expression_instructions
        + humanizer_zh_review_instructions
        + tracked_article_structure_priority_instructions
        + "大纲只写段落职责和推进动作，不要把任何一段提前扩写成完整正文；每段尽量控制在 1 行。"
        + pressure_guard_instructions
        + emotional_release_guard_instructions
        + everyday_warmth_guard_instructions
        + response_priority_guard_instructions
        + supportive_appreciation_guard_instructions
        + self_worth_guard_instructions
        + inner_settlement_guard_instructions
        + self_reliance_guard_instructions
        + resilience_guard_instructions
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
            f"{theme_first_execution_card}"
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
    content_skill_instructions = build_content_skill_instructions(stage="topic", payload=payload)
    pressure_guard_instructions = _build_tracked_article_pressure_guard_instructions(payload, stage="topic")
    emotional_release_guard_instructions = _build_tracked_article_emotional_release_guard_instructions(payload, stage="topic")
    everyday_warmth_guard_instructions = _build_tracked_article_everyday_warmth_guard_instructions(
        payload, stage="topic"
    )
    response_priority_guard_instructions = _build_tracked_article_response_priority_guard_instructions(
        payload, stage="topic"
    )
    supportive_appreciation_guard_instructions = _build_tracked_article_supportive_appreciation_guard_instructions(
        payload, stage="topic"
    )
    self_worth_guard_instructions = _build_tracked_article_self_worth_guard_instructions(
        payload, stage="topic"
    )
    inner_settlement_guard_instructions = _build_tracked_article_inner_settlement_guard_instructions(
        payload, stage="topic"
    )
    self_reliance_guard_instructions = _build_tracked_article_self_reliance_guard_instructions(
        payload, stage="topic"
    )
    resilience_guard_instructions = _build_tracked_article_resilience_guard_instructions(payload, stage="topic")
    relationship_aftercare_guard_instructions = _build_tracked_article_relationship_aftercare_guard_instructions(payload, stage="topic")
    if source_type == "tracked_article":
        body_cue_section = _build_tracked_article_topic_body_cue_section(payload)
        summary = _build_tracked_article_topic_summary(payload)
        structure_notes = _build_tracked_article_topic_structure_notes(payload)
        analysis_theme = _as_clean_text(payload.get("analysis_theme"))
        analysis_core_conflict = _as_clean_text(payload.get("analysis_core_conflict"))
        analysis_emotional_exit = _as_clean_text(payload.get("analysis_emotional_exit"))
        analysis_structure_mode = _as_clean_text(payload.get("analysis_structure_mode"))
        analysis_opening_pattern = _as_clean_text(payload.get("analysis_opening_pattern"))
        analysis_hook_trigger = _as_clean_text(payload.get("analysis_hook_trigger"))
        analysis_progression_drive = _as_clean_text(payload.get("analysis_progression_drive"))
        analysis_share_reason = _as_clean_text(payload.get("analysis_share_reason"))
        analysis_do_not_turn_into = _as_clean_text(payload.get("analysis_do_not_turn_into"))
        source_prompt = (
            f"来源类型：{source_type}\n"
            f"参考文章 slug：{payload['source_ref_slug']}\n"
            f"参考文章标题：{payload['article_title']}\n"
            f"作者：{payload['author']}\n"
            f"来源账号：{payload['source_name'] or '未知公众号'}\n"
            f"摘要：{summary}\n"
            f"结构备注：{structure_notes}\n"
            f"分析主题：{analysis_theme or '无'}\n"
            f"核心矛盾：{analysis_core_conflict or '无'}\n"
            f"情绪出口：{analysis_emotional_exit or '无'}\n"
            f"结构模式：{analysis_structure_mode or '无'}\n"
            f"开头方式：{analysis_opening_pattern or '无'}\n"
            f"开头触发点：{analysis_hook_trigger or '无'}\n"
            f"中段推进力：{analysis_progression_drive or '无'}\n"
            f"转发理由：{analysis_share_reason or '无'}\n"
            f"不要写成：{analysis_do_not_turn_into or '无'}\n"
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
            + "先读懂参考文章在讲什么，再决定新选题怎么组织；不要跳过分析，直接拿标题或几句高频词改写。"
            + "如果上游已经给出分析主题、核心矛盾、情绪出口、结构模式或不要写成什么，优先服从这些分析结论。"
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
            + response_priority_guard_instructions
            + supportive_appreciation_guard_instructions
            + self_worth_guard_instructions
            + inner_settlement_guard_instructions
            + self_reliance_guard_instructions
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
    strategy_first_draft_mode = _should_use_tracked_article_strategy_first_draft_mode(
        payload,
        is_polish_mode=is_polish_mode,
    )
    explicit_strategy_first_draft_mode = bool(payload.get("strategy_first_draft_mode"))
    export_prompt_bundle_mode = bool(payload.get("export_prompt_bundle_mode"))
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
    if bool(payload.get("focused_quality_retry_mode")) and is_polish_mode and isinstance(current_draft, Mapping):
        return _build_focused_quality_retry_prompt(
            payload,
            current_draft=current_draft,
            tone_profile=tone_profile,
            polish_instruction=raw_polish_instruction,
        )
    if timeout_recovery_mode and _as_clean_text(payload.get("source_type")) == "tracked_article":
        return PromptTemplate(
            instructions=_build_tracked_article_timeout_recovery_draft_instructions(payload),
            prompt=_render_tracked_article_timeout_recovery_draft_prompt(payload),
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
        else (
            _build_tracked_article_strategy_first_draft_owner_instructions(tone_profile=tone_profile)
            if strategy_first_draft_mode
            else _build_jinwan_youyu_stage_instructions(
                stage="draft",
                tone_profile=tone_profile,
                payload=payload,
            )
        )
    )
    theme_first_execution_instructions = _build_theme_first_execution_instructions(payload, stage="draft")
    pressure_topic_tweak = _build_jinwan_youyu_pressure_topic_tweak(stage="draft", payload=payload)
    content_skill_instructions = (
        ""
        if timeout_recovery_mode
        else build_content_skill_instructions(stage="draft", payload=payload)
    )
    target_wording = _render_draft_target_wording(tone_profile, payload=payload)
    reference_article_section = (
        ""
        if _has_strategy_package(payload)
        else _render_reference_article_section(payload, stage="draft")
    )
    post_strategy_reference_boundary = _render_post_strategy_reference_boundary(payload, stage="draft")
    theme_first_execution_card = _render_theme_first_execution_card(
        payload,
        stage="draft",
        compact=explicit_strategy_first_draft_mode,
    )
    strategy_package_section = (
        ""
        if timeout_recovery_mode
        else _render_strategy_package_section(
            payload,
            compact=False if export_prompt_bundle_mode else compact_strategy_mode or strategy_first_draft_mode,
            extra_compact=False if export_prompt_bundle_mode else explicit_strategy_first_draft_mode,
            minimal_compact=not export_prompt_bundle_mode and strategy_first_draft_mode,
        )
    )
    strategy_resonance_instructions = (
        ""
        if timeout_recovery_mode
        else _build_strategy_resonance_instructions(
            payload,
            stage="draft",
            compact=compact_strategy_mode or explicit_strategy_first_draft_mode,
        )
    )
    reference_article_instructions = (
        ""
        if timeout_recovery_mode
        else _build_reference_article_instructions(stage="draft")
    )
    original_expression_instructions = (
        ""
        if timeout_recovery_mode or (strategy_first_draft_mode and not export_prompt_bundle_mode)
        else _build_original_expression_instructions(
            stage="draft",
            compact=compact_strategy_mode,
        )
    )
    humanizer_zh_review_instructions = (
        ""
        if timeout_recovery_mode or (strategy_first_draft_mode and not export_prompt_bundle_mode)
        else _build_humanizer_zh_review_instructions(
            stage="draft",
            compact=compact_strategy_mode and not is_polish_mode,
        )
    )
    tracked_article_structure_priority_instructions = (
        ""
        if timeout_recovery_mode
        else _build_tracked_article_structure_priority_instructions(payload, stage="draft")
    )
    ai_flavor_risk_instructions = (
        ""
        if timeout_recovery_mode or (strategy_first_draft_mode and not export_prompt_bundle_mode)
        else _build_localized_ai_flavor_risk_instructions(
            compact=compact_strategy_mode and not is_polish_mode
        )
    )
    wechat_public_account_instructions = (
        ""
        if timeout_recovery_mode or (strategy_first_draft_mode and not export_prompt_bundle_mode)
        else _build_wechat_public_account_draft_instructions(
            compact=compact_strategy_mode
        )
    )
    timeout_recovery_instructions = _build_timeout_recovery_draft_instructions(payload)
    pressure_guard_instructions = _build_tracked_article_pressure_guard_instructions(payload, stage="draft")
    emotional_release_guard_instructions = _build_tracked_article_emotional_release_guard_instructions(payload, stage="draft")
    everyday_warmth_guard_instructions = _build_tracked_article_everyday_warmth_guard_instructions(payload, stage="draft")
    response_priority_guard_instructions = _build_tracked_article_response_priority_guard_instructions(payload, stage="draft")
    supportive_appreciation_guard_instructions = _build_tracked_article_supportive_appreciation_guard_instructions(payload, stage="draft")
    self_worth_guard_instructions = _build_tracked_article_self_worth_guard_instructions(payload, stage="draft")
    inner_settlement_guard_instructions = _build_tracked_article_inner_settlement_guard_instructions(payload, stage="draft")
    self_reliance_guard_instructions = _build_tracked_article_self_reliance_guard_instructions(payload, stage="draft")
    resilience_guard_instructions = _build_tracked_article_resilience_guard_instructions(payload, stage="draft")
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
            (
                "请把选题和大纲扩写成一篇中文首稿。"
                "先保住主题、结构模式、情绪抓手和现实接口，不急着把每一层道理、平台包装和漂亮收尾一次写满。"
                "要求有标题、自然分段和具体抓手，允许局部停顿、回看和不完全收束。"
                if strategy_first_draft_mode
                else (
                    "请把选题和大纲扩写成一篇中文初稿。"
                    "它应该像作者仍在推进中的一版，不是已经准备进编辑排版的完整示范文。"
                    "要求有标题、自然分段和具体抓手，但不要求把每一段都补满，也不要求把结尾收得很完整。"
                    "如果来源是参考文章改写，不要自动把多个现实接口缝成一个人从早到晚一路推进的完整成稿，"
                    "允许局部停顿、回看和不完全收束。"
                )
                if _as_clean_text(payload.get("source_type")) == "tracked_article"
                else "请把选题和大纲扩写成一篇可直接进入编辑流程的中文初稿。要求有清晰标题、自然分段、具体场景和收束段。"
            )
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
        compact=compact_strategy_mode or strategy_first_draft_mode,
    )
    return PromptTemplate(
        instructions=build_stage_instructions(
            role="正文作者",
            task_brief=task_brief,
            domain_pack=payload.get("domain_pack"),
        )
        + preset_stage_instructions
        + theme_first_execution_instructions
        + strategy_resonance_instructions
        + pressure_topic_tweak
        + content_skill_instructions
        + timeout_recovery_instructions
        + original_expression_instructions
        + humanizer_zh_review_instructions
        + tracked_article_structure_priority_instructions
        + ai_flavor_risk_instructions
        + wechat_public_account_instructions
        + pressure_guard_instructions
        + emotional_release_guard_instructions
        + everyday_warmth_guard_instructions
        + response_priority_guard_instructions
        + supportive_appreciation_guard_instructions
        + self_worth_guard_instructions
        + inner_settlement_guard_instructions
        + self_reliance_guard_instructions
        + resilience_guard_instructions
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
            f"{theme_first_execution_card}"
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
    if bool(payload.get("assets_timeout_recovery_mode")):
        return PromptTemplate(
            instructions=_build_assets_timeout_recovery_instructions(),
            prompt=_render_assets_timeout_recovery_prompt(payload, draft=draft),
        )
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
    theme_first_execution_instructions = _build_theme_first_execution_instructions(payload, stage="assets")
    post_strategy_reference_boundary = _render_post_strategy_reference_boundary(payload, stage="assets")
    theme_first_execution_card = _render_theme_first_execution_card(payload, stage="assets")
    strategy_package_section = _render_strategy_package_section(payload, compact=True, minimal_compact=True)
    strategy_resonance_instructions = _build_strategy_resonance_instructions(payload, stage="assets")
    packaging_theme_alignment_instructions = _build_packaging_theme_alignment_instructions(payload, stage="assets")
    pressure_topic_tweak = _build_jinwan_youyu_pressure_topic_tweak(stage="assets", payload=payload)
    content_skill_instructions = build_content_skill_instructions(stage="assets", payload=payload)
    dbskill_assets_instructions = "".join(get_dbskill_rule_lines("assets", "extra_instructions"))
    responsibility_shelter_packaging_instructions = (
        "如果当前题材是责任托家回温稿，标题、封面文案和导语优先写成当场会冒出来的人话，不要先替读者总结意义。"
        "标题优先抓电话响了、门口停住、先翻日历、先排顺序这类现实动作，少写回看型总结句。"
        "标题也尽量别用先讲判断再回收的句式。"
        "标题尽量少用抽象比喻词，比如定盘星、灯塔、港湾、底气、铠甲这类先把人抬高的词。"
        "责任类标题优先做成一句日常口语，而不是一整句修辞。"
        "标题尽量短，优先 8 到 14 个字左右，优先从当前正文已经成立的现实动作或现场停顿起手。"
        "标题不要写成回环句，也不要先起修辞再落判断。"
        "标题可以从来电、门口、日历、接送、请假、复查、回家或开销等现实入口里选择，但必须跟正文主场景一致，少用总括前缀。"
        "不要为了套动作硬把电话、手机或日历塞进每篇；如果参考文主场景不是这些，就跟随参考文自己的现实接口。"
        "尽量不要把标题写成总结句。"
        "如果能选，优先用一个具体动作或一个当场停顿来定标题。"
        "封面图里手机必须入镜，最好是人正低头看手机或拿着手机；可以是暗屏、侧面或背向镜头，但不要露聊天界面。"
        "封面文案尽量压到 1 句或 2 个短分句，像人一下说出口的话，不要写成完整解释。"
        "封面文案要和标题拉开一点，不要把标题原样重复一遍。"
        "主导语和导语候选先给一个现场入口，再轻轻带回家里安稳，不要一上来就讲道理。"
        "导语首句优先短到像一下冒出来的话，最好先用 8 到 18 个字把电话、门口、日历、放学或回家这类现场顶出来。"
        "导语不要写成先下结论再补解释的句式。"
        "导语也别写成编辑说明。"
        "导语和封面文案都尽量少用工整反转骨架。"
        "导语也尽量少用“托稳”“撑起”“接住”这类过于整齐的总结词，优先写成日常动作和当下反应。"
    ) if _has_everyday_warmth_responsibility_shelter_focus(payload) else ""
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
        + theme_first_execution_instructions
        + strategy_resonance_instructions
        + packaging_theme_alignment_instructions
        + pressure_topic_tweak
        + content_skill_instructions
        + dbskill_assets_instructions
        + responsibility_shelter_packaging_instructions
        + "封面图提示词必须服务于 16:9 横版公众号头图。"
        + "禁止输出竖版、9:16、手机海报、竖构图或会导致上下裁切的画幅描述。",
        prompt=(
            f"趋势标题：{payload['trend_title']}\n"
            f"选题标题：{payload['topic_title']}\n"
            f"切入角度：{payload['topic_angle']}\n"
            f"项目标题：{payload['project_title']}\n"
            f"{post_strategy_reference_boundary}\n"
            f"{theme_first_execution_card}"
            f"{strategy_package_section}"
            f"{style_section}"
            f"正文标题：{draft['title']}\n"
            f"正文内容：\n{draft['body_markdown']}\n"
            f"{review_section}\n"
            "封面图提示词要求：\n"
            "1. 明确写成 16:9 横版公众号头图或横向宽画幅构图\n"
            "2. 主体位于画面中部安全区，避免关键元素贴近上下边缘\n"
            "3. 禁止出现竖版、9:16、手机海报、竖构图等冲突词\n"
            "4. 封面默认不要手机聊天界面、输入框或消息气泡；如果手机作为道具，只画人在看手机或握着手机，屏幕可以暗掉、虚化或背向镜头，不展示可读聊天内容；不要把聊天界面画在手机背面，不要生成双面手机、前后双屏手机或背面屏幕，不要让后摄模组和屏幕 UI 同时出现在同一可见面上；任何屏幕都必须正常朝向，不要镜像、反字、反向 UI，也不要生成可辨认乱码文字\n"
            "5. 用场景、人物状态、光线和留白描述画面，不要把长文案直接写进图里\n"
            "返回：\n"
            "1. 3 个标题备选 title_options（不要套反问翻转、痛点翻转或双重否定翻转这类模板骨架；不要用“很多人”“有些人”“总有人”这类泛主语起手；优先具体节点、误判或动作入口；至少有 1 条明显贴着策略包里的包装抓手）\n"
            "2. 1 条主推标题 recommended_title（必须从 title_options 中选，优先最适合直接发布的一条；不要选最像模板答案句的那条）\n"
            "3. 1 条封面图提示词 cover_prompt\n"
            "4. 1 条封面文案 cover_copy（优先短到一眼能截住人，少解释，像一句现场会冒出来的话）\n"
            "5. 1 条主社媒导语 social_teaser（不要只概述正文，要带一个明确入口或回正落点；优先像真人顺口说出来的开场，不要写成解释文案；首句优先短句化）\n"
            "6. 3 条导语候选 social_teaser_options（短句优先，彼此要有区分；不要用群体概括句起手；如果必须群体概括，只能放句中，开头要先给具体入口或动作；首句优先短句化）"
        ),
    )


def _build_assets_timeout_recovery_instructions() -> str:
    return (
        "你是公众号包装编辑。只返回 JSON 对象："
        "title_options 数组3条、recommended_title、cover_prompt、cover_copy、"
        "social_teaser、social_teaser_options 数组3条。推荐标题必须来自 title_options。"
        "标题、封面文案和导语不要用“很多人”“有些人”“总有人”起手。"
    )


def _render_assets_timeout_recovery_prompt(
    payload: Mapping[str, object],
    *,
    draft: Mapping[str, object],
) -> str:
    lines: list[str] = []
    project_title = _as_clean_text(payload.get("project_title")) or _as_clean_text(payload.get("topic_title"))
    if project_title:
        lines.append(f"主题：{_truncate_text(project_title, max_length=32)}")

    draft_title = _as_clean_text(draft.get("title"))
    if draft_title and draft_title != project_title:
        lines.append(f"正文标题：{_truncate_text(draft_title, max_length=32)}")

    problem_brief = payload.get("problem_brief")
    if isinstance(problem_brief, Mapping):
        theme_axis = _as_clean_text(problem_brief.get("theme_axis"))
        if theme_axis:
            lines.append(f"主线：{_truncate_text(theme_axis, max_length=54)}")
        emotional_value_goal = _as_clean_text(problem_brief.get("emotional_value_goal"))
        if emotional_value_goal:
            lines.append(f"情绪回报：{_truncate_text(emotional_value_goal, max_length=48)}")

    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping):
        packaging_focus = _as_clean_text(strategy_card.get("packaging_focus"))
        if packaging_focus:
            lines.append(f"包装抓手：{_truncate_text(packaging_focus, max_length=56)}")
        positive_direction = _as_clean_text(strategy_card.get("positive_direction"))
        if positive_direction:
            lines.append(f"正向落点：{_truncate_text(positive_direction, max_length=48)}")

    draft_excerpt = _truncate_text(
        _as_clean_text(draft.get("body_markdown")).replace("\n", " "),
        max_length=120,
    )
    if draft_excerpt:
        lines.append(f"正文抓手：{draft_excerpt}")

    lines.append("要求：标题短、有情绪价值；导语给现实入口和正向回落；标题、封面文案和导语不要用很多人/有些人/总有人起手；封面16:9横版，不要手机聊天界面，不要口号。")
    return "\n".join(lines)


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
            role="公众号内容分析编辑",
            task_brief="请先分析参考文章的主题和推进方式，再补全适合来源池审核的摘要、结构备注、分析结论和标签。",
            domain_pack=payload.get("domain_pack"),
        )
        + "这是参考文章分析与来源池字段补全，不是正文改写。"
        + "先分析文章，再补字段；不要跳过分析直接写摘要。"
        + "不要照搬原标题、摘要或正文原句。"
            + "摘要要像人工写的来源备注，1 到 2 句话，写清核心冲突、观察角度或主要判断。"
            + "结构备注要说明开头如何切入、中段如何推进、结尾如何收束，保持简洁具体。"
            + "分析主题要一句话说清这篇文章真正想讨论什么。"
            + "核心矛盾要写出文章想拆开的冲突或卡点，不要空泛。"
            + "情绪出口要说明文章最后把读者带向哪里，尽量正向、有人被接住的感觉。"
        + "开头触发点要写出原文第一下最容易把人停住的现实接口、物件、问句或画面，不要写成空泛的“很有代入感”。"
        + "中段推进力要写出文章靠什么一路往前推，比如误判被点破、代价被看见、被爱托住或关系意义被重估。"
        + "转发理由要说明它为什么容易让人觉得“这说的就是我”或“这段话我想发给谁看”，要具体，不要只写“有共鸣”。"
        + "结构模式只能从这些值里选一个：fragment_chain_observation / pressure_interface_direct / everyday_warmth_return / inner_settlement / self_worth_rebuild / self_reliance_inward_support / response_priority / trust_boundary / supportive_appreciation / relationship_aftercare / resilience_reconstruction / emotional_engine_direct / scene_first_progression。"
        + "如果原文重心是成年人把一家人的安稳放在心上，最后落回家里仍有灯、有回应、辛苦慢慢变成踏实，这也属于 everyday_warmth_return，不要误判成泛放下稿。"
        + "开头方式要说明原文如何起笔，例如从生活接口、关系现场、判断句、引用或身体信号切入。"
        + "偏题边界要写成一条最容易偏离的方向，短句即可，避免写成泛泛提醒或二次改写要求。"
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
            "4. 分析主题 analysis_theme\n"
            "5. 核心矛盾 analysis_core_conflict\n"
            "6. 情绪出口 analysis_emotional_exit\n"
            "7. 结构模式 analysis_structure_mode\n"
            "8. 开头方式 analysis_opening_pattern\n"
            "9. 开头触发点 analysis_hook_trigger\n"
            "10. 中段推进力 analysis_progression_drive\n"
            "11. 转发理由 analysis_share_reason\n"
            "12. 偏题边界 analysis_do_not_turn_into\n"
            "13. 标签 tags"
        ),
    )


def build_cover_image_prompt(payload: Mapping[str, object]) -> str:
    strategy_card = payload.get("strategy_card")
    responsibility_shelter_cover_focus = (
        isinstance(strategy_card, Mapping)
        and _as_clean_text(strategy_card.get("structure_mode")) == "responsibility_shelter"
    ) or _has_everyday_warmth_responsibility_shelter_focus(payload)

    responsibility_shelter_phone_requirement = (
        "当前题材里，手机必须清晰入镜，优先画成人物正拿着手机、低头看手机，或把手机贴在耳边接电话。"
        "不要只把手机远远丢在桌角，也不要被手、纸张或桌面杂物挡到几乎看不见。"
    ) if responsibility_shelter_cover_focus else ""

    return (
        "请生成适合公众号头图的横版封面图，目标视觉比例为 16:9。"
        "主体信息放在画面中部安全区，避免关键人物或文字落在上下裁切边缘。"
        "不要把画面做成整张雾化、过度柔焦或糊成大片色块；人物、门框、桌面物件要保持基本可辨识的轮廓和材质。"
        "如果画面里有人物，不要画成过于规整的插画剪影、空白面部或海报摆拍；要更像真实生活里的抓拍瞬间。"
        "人物可以是侧身、背身、低头或面部被自然遮挡，但整体气质要像真实回家、真实停顿，而不是抽象符号。"
        "封面默认不要手机聊天界面、输入框、消息气泡或可读屏幕文字。"
        f"{responsibility_shelter_phone_requirement}"
        "如果手机作为道具，只画人在看手机、拿着手机或手机放在桌边；屏幕可以暗掉、虚化、侧过去或背向镜头。"
        "即使原始创意提示词提到聊天界面，也要改成无可读屏幕内容的看手机场景。"
        "不要把聊天界面画在手机背面，不要生成双面手机、前后双屏手机或背面屏幕，不要让后摄像头模组和屏幕 UI 同时出现在同一可见面上。"
        "任何屏幕都必须保持正常朝向，不要镜像翻转，不要反字，不要生成可辨认乱码文字。"
        f"\n原始创意提示词：{payload['cover_prompt']}"
    )


def build_publish_package_prompt(payload: Mapping[str, object]) -> PromptTemplate:
    if bool(payload.get("publish_timeout_recovery_mode")):
        return PromptTemplate(
            instructions=_build_publish_timeout_recovery_instructions(),
            prompt=_render_publish_timeout_recovery_prompt(payload),
        )
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
    theme_first_execution_instructions = _build_theme_first_execution_instructions(payload, stage="publish_package")
    post_strategy_reference_boundary = _render_post_strategy_reference_boundary(payload, stage="publish_package")
    theme_first_execution_card = _render_theme_first_execution_card(payload, stage="publish_package")
    strategy_package_section = _render_strategy_package_section(payload, compact=True, minimal_compact=True)
    strategy_resonance_instructions = _build_strategy_resonance_instructions(payload, stage="publish_package")
    packaging_theme_alignment_instructions = _build_packaging_theme_alignment_instructions(
        payload,
        stage="publish_package",
    )
    pressure_topic_tweak = _build_jinwan_youyu_pressure_topic_tweak(stage="publish_package", payload=payload)
    content_skill_instructions = build_content_skill_instructions(stage="publish_package", payload=payload)
    dbskill_publish_instructions = "".join(get_dbskill_rule_lines("publish_package", "extra_instructions"))
    responsibility_shelter_publish_instructions = (
        "如果当前题材是责任托家回温稿，发布标题和导语优先保住那种先稳住家里、再轮到自己开口的口气。"
        "标题不要写成大而整齐的总结句，优先保留一个现实动作、当场停顿或顺手先做的事。"
        "标题尽量短，优先 8 到 14 个字左右，别做成长句收口。"
        "publish_lead 和 intro_options 优先像人站在具体现场处理事情时会说出来的话，少写作者替读者总结的句子。"
        "导语首句尽量更短，先拿一个现场动作把人拽进去，再用下一句补回家里的安稳。"
        "导语也别写成编辑说明。"
        "发布导语里也尽量少用工整反转句。"
    ) if _has_everyday_warmth_responsibility_shelter_focus(payload) else ""
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
        + theme_first_execution_instructions
        + strategy_resonance_instructions
        + packaging_theme_alignment_instructions
        + pressure_topic_tweak
        + content_skill_instructions
        + dbskill_publish_instructions
        + responsibility_shelter_publish_instructions,
        prompt=(
            f"项目标题：{payload['project_title']}\n"
            f"{post_strategy_reference_boundary}\n"
            f"{theme_first_execution_card}"
            f"{strategy_package_section}"
            f"{style_section}"
            f"正文标题：{payload['draft']['title']}\n"
            f"正文内容：\n{payload['draft']['body_markdown']}\n\n"
            f"封面文案：{payload['assets']['cover_copy']}\n"
            f"分发导语：{payload['assets']['social_teaser']}\n"
            f"导语候选：{' / '.join(payload['assets'].get('social_teaser_options', [])) or '空'}\n"
            f"主推标题：{payload['assets'].get('recommended_title') or '空'}\n"
            f"标题备选：{' / '.join(payload['assets']['title_options'])}\n"
            f"{review_section}\n"
            "返回：\n"
            "1. 发布摘要 abstract\n"
            "2. 最终发布标题 publish_title（优先基于标题备选微调，不要另起完全无关的新标题；不要套反问翻转、痛点翻转或双重否定翻转这类模板骨架；不要用“很多人”“有些人”“总有人”这类泛主语起手；责任类题材尤其优先动作型、现场型、停顿型标题，不要先讲道理；可以从来电、门口、日历、接送、请假、回家或开销等现实入口里选择，但必须跟正文主场景一致；不要写成回环句、总括前缀或总结句）\n"
            "3. 最终发布导语 publish_lead（适合微信正文前的简短导语，尽量像真人写的开场；不要写成编辑说明；要有入口，也要带回正落点；优先保留口语停顿和现场感，不要先替读者下总结；首句优先短句化；责任类题材优先先写正文已经成立的现场动作，再落一点情绪，不要先抽象概括辛苦）\n"
            "4. 3 条导语候选 intro_options（用于正文开头前的导语备选，和 publish_lead 保持同主题但不要完全重复；优先短句，允许口语停顿，不要整齐三段论；不要用群体概括句起手；如果必须群体概括，只能放句中，开头要先给具体入口或动作；首句优先短句化；责任类题材里，先给现场动作，再给轻一点的回落；少用“托稳”“底气”“定盘星”这种太整齐的词；封面文案也不要和标题重复）\n"
            "5. 3 到 5 个标签 tags\n"
            "6. 编辑备注 editor_note"
        ),
    )


def _build_publish_timeout_recovery_instructions() -> str:
    return (
        "你是公众号发布编辑。"
        "只返回一个 JSON 对象。"
        "字段必须包含 abstract、tags、editor_note、publish_title、publish_lead、intro_options。"
        "tags 写 3 到 5 个短标签；intro_options 写 3 条字符串。"
        "publish_title、abstract、publish_lead、intro_options 不要用“很多人”“有些人”“总有人”起手。"
        "publish_lead 和 intro_options 要像真人写的开场，不要编辑说明腔，不要喊口号。"
    )


def _render_publish_timeout_recovery_prompt(payload: Mapping[str, object]) -> str:
    draft = payload.get("draft")
    assets = payload.get("assets")
    lines = [f"项目标题：{_as_clean_text(payload.get('project_title'))}"]

    if isinstance(draft, Mapping):
        draft_title = _as_clean_text(draft.get("title"))
        if draft_title:
            lines.append(f"正文标题：{draft_title}")
        draft_excerpt = _truncate_text(
            _as_clean_text(draft.get("body_markdown")).replace("\n", " "),
            max_length=380,
        )
        if draft_excerpt:
            lines.append(f"正文要点：{draft_excerpt}")

    if isinstance(assets, Mapping):
        publish_title = _as_clean_text(assets.get("recommended_title"))
        if publish_title:
            lines.append(f"现成主推标题：{publish_title}")
        cover_copy = _as_clean_text(assets.get("cover_copy"))
        if cover_copy:
            lines.append(f"封面文案：{_truncate_text(cover_copy, max_length=60)}")
        social_teaser = _as_clean_text(assets.get("social_teaser"))
        if social_teaser:
            lines.append(f"现成导语：{_truncate_text(social_teaser, max_length=100)}")

    problem_brief = payload.get("problem_brief")
    if isinstance(problem_brief, Mapping):
        theme_axis = _as_clean_text(problem_brief.get("theme_axis"))
        if theme_axis:
            lines.append(f"主线：{_truncate_text(theme_axis, max_length=78)}")
        core_conflict = _as_clean_text(problem_brief.get("core_conflict"))
        if core_conflict:
            lines.append(f"冲突：{_truncate_text(core_conflict, max_length=72)}")
        emotional_value_goal = _as_clean_text(problem_brief.get("emotional_value_goal"))
        if emotional_value_goal:
            lines.append(f"情绪回报：{_truncate_text(emotional_value_goal, max_length=72)}")

    strategy_card = payload.get("strategy_card")
    if isinstance(strategy_card, Mapping):
        positive_direction = _as_clean_text(strategy_card.get("positive_direction"))
        if positive_direction:
            lines.append(f"正向落点：{_truncate_text(positive_direction, max_length=72)}")
        packaging_focus = _as_clean_text(strategy_card.get("packaging_focus"))
        if packaging_focus:
            lines.append(f"包装抓手：{_truncate_text(packaging_focus, max_length=88)}")
        packaging_hook = _as_clean_text(strategy_card.get("packaging_hook"))
        if packaging_hook:
            lines.append(f"主钩子：{_truncate_text(packaging_hook, max_length=72)}")

    review_comment = _as_clean_text(payload.get("review_comment"))
    if review_comment:
        lines.append(f"审核意见：{_truncate_text(review_comment, max_length=72)}")

    lines.append(
        "要求：摘要别空泛，发布标题、摘要、导语和候选导语不要用很多人/有些人/总有人起手；发布导语先给现实入口再回到正向落点，标签要具体，编辑备注只写最该提醒的一件事。"
    )
    return "\n".join(lines)
