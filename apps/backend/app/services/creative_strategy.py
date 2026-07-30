from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re

from app.schemas.creative_workflow import (
    BenchmarkReferenceItem,
    ProblemBriefItem,
    StrategyCardItem,
    StrategyPackageResult,
)
from app.services.dbskill_bridge import get_dbskill_rule_lines, merge_unique_lines


_TRACKED_ARTICLE_STRUCTURE_MODES = {
    "fragment_chain_observation",
    "pressure_interface_direct",
    "everyday_warmth_return",
    "inner_settlement",
    "self_worth_rebuild",
    "self_reliance_inward_support",
    "response_priority",
    "trust_boundary",
    "supportive_appreciation",
    "relationship_aftercare",
    "resilience_reconstruction",
    "emotional_engine_direct",
    "scene_first_progression",
}


@dataclass(frozen=True)
class ReferenceArticleFingerprint:
    groups: tuple[str, ...] = ()
    has_dialogue: bool = False
    has_object_residue: bool = False
    has_time_marker: bool = False


@dataclass(frozen=True)
class AnalysisFirstContract:
    theme: str = ""
    core_conflict: str = ""
    emotional_exit: str = ""
    opening_pattern: str = ""
    do_not_turn_into: str = ""


_REFERENCE_HOME_RETURN_KEYWORDS = (
    "回家",
    "晚饭",
    "饭桌",
    "厨房",
    "灯",
    "热饭",
    "家里",
    "一顿饭",
    "散步",
    "超市",
    "晒太阳",
    "小区",
    "阳台",
    "沙发",
)
_REFERENCE_CHILD_WAITING_KEYWORDS = (
    "放学",
    "孩子",
    "画",
    "爸爸",
    "妈妈",
    "父母",
    "孙女",
    "门口",
)
_REFERENCE_WEATHER_CARE_KEYWORDS = (
    "天气预报",
    "暴雨",
    "爷爷",
    "奶奶",
    "电话",
    "叮嘱",
    "当心点",
    "老家",
    "牵挂",
    "惦记",
)
_REFERENCE_RESPONSIBILITY_SHELTER_KEYWORDS = (
    "没事，有我",
    "没事有我",
    "父母日渐佝偻",
    "补习费用",
    "各种账单",
    "扛住压力",
    "喉咙发紧",
    "父母的拐杖",
    "孩子的雨伞",
    "伴侣的靠山",
    "撑起一个家",
    "缴费窗口",
    "温暖的屋檐",
    "撑起一片晴空",
    "人间安稳",
    "家在哪里",
    "有人在爱你",
    "暖黄灯光",
    "热气腾腾的羹汤",
    "天一定会亮",
)
_REFERENCE_STAGE_NODE_KEYWORDS = (
    "半年",
    "上半年",
    "下半年",
    "年初",
    "年中",
    "清单",
    "目标",
    "阶段",
    "盘点",
    "白走",
)
_REFERENCE_HEART_SETTLEMENT_KEYWORDS = (
    "心安",
    "淡定",
    "从容",
    "一餐一饮",
    "一呼一吸",
    "安顿",
    "心结",
    "郁结",
    "放平",
    "放回今天",
)
_REFERENCE_OLD_OBJECT_KEYWORDS = (
    "旧衣",
    "碎花裙",
    "栀子花",
    "游园会",
    "旧相册",
    "聊天记录",
    "垃圾桶",
    "阳台",
    "发呆",
    "摩挲",
)
_REFERENCE_OFFICE_SCENE_KEYWORDS = (
    "会议",
    "会议室",
    "方案",
    "投影",
    "主管",
    "散会",
    "屏幕",
    "资料",
    "水杯",
    "邮件",
)
_REFERENCE_TRANSIT_UNSENT_KEYWORDS = (
    "地铁口",
    "接驳车",
    "围巾",
    "没发出去",
    "上车",
    "车来了",
    "窗户",
    "最后一班",
)
_REFERENCE_RESPONSE_PRIORITY_KEYWORDS = (
    "消息",
    "回信息",
    "回电话",
    "电话",
    "回复",
    "朋友圈",
    "点赞",
    "评论",
    "追问",
    "多问一句",
    "言外之意",
    "没说完",
    "接住",
    "红灯",
    "蓝牙",
    "没时间",
)
_REFERENCE_RESPONSE_PRIORITY_FOLLOWUP_KEYWORDS = (
    "评论",
    "追问",
    "多问一句",
    "愿意停下来",
    "读懂",
    "言外之意",
    "没说完",
    "我没事",
    "我有点累",
    "注意力",
)
_REFERENCE_TRUST_BOUNDARY_KEYWORDS = (
    "信任",
    "相信",
    "谎言",
    "隐瞒",
    "撒谎",
    "欺骗",
    "辜负",
    "裂缝",
    "裂了一道缝",
    "疙瘩",
    "出轨",
    "怀疑",
    "敏感多疑",
    "坦诚",
    "真诚",
    "诚实",
    "赤诚",
    "说到做到",
    "不查手机",
    "不追问行踪",
    "把心交出来",
)
_REFERENCE_AFTERCARE_CONFLICT_KEYWORDS = (
    "吵架",
    "争吵",
    "冷暴力",
    "沉默",
    "善后",
    "不理不睬",
    "沟通",
    "妥协",
    "失望",
)
_REFERENCE_RESILIENCE_BODY_KEYWORDS = (
    "车祸",
    "手术",
    "残肢",
    "泳池",
    "训练",
    "肩伤",
    "背痛",
    "炎症",
    "疼痛",
    "残奥",
)
_REFERENCE_SELF_SUPPORT_KEYWORDS = (
    "倾诉",
    "愁眉不展",
    "焦头烂额",
    "束手无策",
    "睡不着",
    "朋友圈",
    "向内求",
    "自救",
    "自渡",
    "外求",
    "靠自己",
)
_REFERENCE_SUPPORTIVE_SOFTNESS_KEYWORDS = (
    "心软",
    "包容",
    "原谅",
    "道歉",
    "重感情",
    "照顾",
    "温暖",
    "牵紧",
)
_REFERENCE_ENDINGS_ACCEPTANCE_KEYWORDS = (
    "离开",
    "结束",
    "相遇",
    "亏欠",
    "聚散",
    "允许一切发生",
    "允许一切结束",
    "不谈亏欠",
    "继续前行",
)
_REFERENCE_FINGERPRINT_GROUP_RULES = (
    ("responsibility_shelter", _REFERENCE_RESPONSIBILITY_SHELTER_KEYWORDS, 2),
    ("weather_care", _REFERENCE_WEATHER_CARE_KEYWORDS, 3),
    ("stage_node", _REFERENCE_STAGE_NODE_KEYWORDS, 2),
    ("heart_settlement", _REFERENCE_HEART_SETTLEMENT_KEYWORDS, 2),
    ("old_object_regret", _REFERENCE_OLD_OBJECT_KEYWORDS, 2),
    ("office_scene", _REFERENCE_OFFICE_SCENE_KEYWORDS, 2),
    ("transit_unsent", _REFERENCE_TRANSIT_UNSENT_KEYWORDS, 2),
    ("response_followup_detail", _REFERENCE_RESPONSE_PRIORITY_FOLLOWUP_KEYWORDS, 2),
    ("response_priority_detail", _REFERENCE_RESPONSE_PRIORITY_KEYWORDS, 2),
    ("trust_boundary_detail", _REFERENCE_TRUST_BOUNDARY_KEYWORDS, 3),
    ("aftercare_conflict", _REFERENCE_AFTERCARE_CONFLICT_KEYWORDS, 2),
    ("resilience_body", _REFERENCE_RESILIENCE_BODY_KEYWORDS, 2),
    ("self_support", _REFERENCE_SELF_SUPPORT_KEYWORDS, 2),
    ("supportive_softness", _REFERENCE_SUPPORTIVE_SOFTNESS_KEYWORDS, 2),
    ("endings_acceptance", _REFERENCE_ENDINGS_ACCEPTANCE_KEYWORDS, 2),
    ("child_waiting", _REFERENCE_CHILD_WAITING_KEYWORDS, 2),
    ("home_return", _REFERENCE_HOME_RETURN_KEYWORDS, 2),
)
_REFERENCE_OBJECT_RESIDUE_KEYWORDS = (
    "灯",
    "饭",
    "钥匙",
    "屏幕",
    "手机",
    "围巾",
    "资料",
    "水杯",
    "裙",
    "相册",
    "聊天记录",
    "画",
    "清单",
)
_REFERENCE_TIME_MARKER_KEYWORDS = (
    "今天",
    "今晚",
    "昨天",
    "后来",
    "这天",
    "过去的这半年",
    "年初",
    "下半年",
    "放学",
    "散会",
    "上车",
)
_SELF_RELIANCE_INWARD_SUPPORT_KEYWORDS = (
    "向内求",
    "向外求",
    "向外找安慰",
    "向外求助",
    "向内稳住",
    "自救",
    "自渡",
    "靠自己",
    "自己熬过",
    "自扫门前雪",
    "自我疗愈",
    "自我修复",
    "自我支撑",
    "自我托住",
    "托住自己",
    "托住你",
    "自己扛",
    "自己撑",
    "自己稳住",
    "把自己托起来",
    "把自己托过去",
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
    "外求未必可靠",
    "外求未必总能及时接住",
    "外部支撑",
    "别人也各自承压",
    "把依靠收回",
    "把依靠收回自己身上",
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
    "外部支撑未必总能及时到位",
    "外求未必总能及时接住",
    "真正能托住你的",
    "最终还得靠自己",
    "把依靠收回自己身上",
    "把自己托起来",
    "把自己托过去",
    "向内稳住",
    "最累最难的时候可以忍住不哭",
    "别人再好再强大",
    "终有靠不到",
    "终有靠不住",
    "自己也有能力",
    "试着向上爬",
    "能够自救自渡",
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
    "身价",
    "抬高门槛",
    "标准收紧",
    "树边界",
    "重新定义",
    "别低到尘埃里",
    "把自己放在心上",
    "体面",
    "边界",
    "标准",
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
)
_SELF_WORTH_REBUILD_EXCLUSION_KEYWORDS = (
    "没时间",
    "回信息",
    "回消息",
    "回电话",
    "红灯30秒",
    "24小时在线",
    "时间在哪儿",
    "心就在哪儿",
    "吵架",
    "冷战",
    "和好",
    "修复",
    "善后",
    "冷暴力",
    "复合",
)


def normalize_structure_mode_hint(value: str | None) -> str:
    normalized = re.sub(r"\s+", "_", (value or "").strip().lower())
    normalized = re.sub(r"[^a-z_]+", "", normalized)
    if normalized in _TRACKED_ARTICLE_STRUCTURE_MODES:
        return normalized
    return ""


def _is_everyday_warmth_family_mode(structure_mode: str) -> bool:
    return structure_mode in {"everyday_warmth_return", "responsibility_shelter"}


def _resolve_effective_structure_mode(*, structure_mode: str, everyday_warmth_variant: str = "") -> str:
    if structure_mode == "everyday_warmth_return" and everyday_warmth_variant == "responsibility_shelter":
        return "responsibility_shelter"
    return structure_mode


def resolve_tracked_article_structure_mode(
    *,
    article_title: str = "",
    body_markdown: str,
    summary: str = "",
    structure_notes: str = "",
    analysis_structure_mode_hint: str = "",
    analysis_theme: str = "",
    analysis_core_conflict: str = "",
    analysis_emotional_exit: str = "",
    analysis_opening_pattern: str = "",
    analysis_do_not_turn_into: str = "",
) -> str:
    normalized_hint = normalize_structure_mode_hint(analysis_structure_mode_hint)
    synthetic_angle = " ".join(
        part.strip()
        for part in (
            analysis_theme,
            analysis_core_conflict,
            analysis_emotional_exit,
            analysis_opening_pattern,
        )
        if part and part.strip()
    )
    reference_summary = " ".join(
        part.strip()
        for part in (
            article_title,
            summary,
            analysis_theme,
            analysis_core_conflict,
            analysis_emotional_exit,
        )
        if part and part.strip()
    )
    if not any(
        part.strip()
        for part in (
            body_markdown,
            structure_notes,
            synthetic_angle,
            reference_summary,
            normalized_hint,
        )
        if part
    ):
        return normalized_hint

    return _build_structure_mode(
        source_mode="tracked_article",
        topic_angle=synthetic_angle,
        tracked_article_scene=_extract_reference_scene(body_markdown),
        reference_body_markdown=body_markdown,
        reference_summary=reference_summary,
        reference_structure_notes=structure_notes,
        reference_analysis_structure_mode=normalized_hint,
    )


_PRESSURE_TOPIC_HARD_SIGNALS = (
    "体检",
    "复查",
    "透析",
    "尿毒症",
    "褥疮",
    "轮椅",
    "身体提醒",
    "身体信号",
    "求救信号",
)
_PRESSURE_TOPIC_BODY_SIGNALS = (
    "身体",
    "休息",
    "自我照料",
    "照顾自己",
    "生活排序",
    "生活接口",
    "身体代价",
    "情绪",
)
_PRESSURE_TOPIC_INTERFACE_SIGNALS = (
    "推迟",
    "往后放",
    "压后",
    "等有空",
    "等忙完",
    "拖延",
    "推后",
    "往后推",
    "往后排",
    "顺延",
    "还能扛",
    "该停了",
    "撤掉",
)
_PRESSURE_TOPIC_CONSEQUENCE_SIGNALS = (
    "胃口变差",
    "作息发乱",
    "没耐心",
    "负荷",
    "疲惫",
    "耗尽",
    "撑住",
    "稳住",
    "倦怠",
    "报警",
    "代价链",
    "坏一点",
    "失衡",
    "追债",
)
_PRESSURE_REFERENCE_HARD_SIGNALS = (
    "尿毒症",
    "褥疮",
    "透析",
    "轮椅",
    "体检",
    "复查",
    "身体提醒",
    "身体信号",
    "求救信号",
)
_PRESSURE_REFERENCE_SOFT_SIGNALS = (
    "身体",
    "疲惫",
    "耗尽",
    "报警",
    "推迟",
    "往后放",
    "照顾好自己",
    "自我照料",
    "休息",
    "工作",
    "家人",
    "失衡",
)
_PRESSURE_REFERENCE_CONSEQUENCE_MARKERS = ("后来", "又开始", "直到", "迟早", "怀念")
_EMOTIONAL_RELEASE_REFERENCE_KEYWORDS = (
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
    "感谢相遇",
    "不谈亏欠",
    "允许一切发生",
    "允许一切结束",
    "接纳离开",
    "接纳结束",
    "关系结束",
    "离别",
    "聚散终有时",
    "过客",
    "允许他们走进",
    "允许他们离开",
    "相遇意义",
    "内化",
    "内在消化",
    "留给你的温暖",
    "变成了你自己",
    "整理行囊",
    "拥抱下一场",
    "未知的山海",
)
_BROAD_EMOTIONAL_RELEASE_STRATEGY_KEYWORDS = (
    "幸福",
    "放下",
    "放手",
    "知足",
    "珍惜",
    "拥有",
    "得不到",
    "不甘心",
    "强求",
    "执念",
    "拉扯",
    "继续投入",
    "投入",
    "停下",
    "松手",
    "舍不得",
    "腾出位置",
    "心力",
)
_BROAD_EMOTIONAL_RELEASE_THESIS_MARKERS = (
    "幸福",
    "放下",
    "放手",
    "知足",
    "珍惜",
    "拥有",
    "误认成",
    "还有希望",
    "更接近幸福",
    "停下也是一种保护",
    "眼前拥有",
    "已经拥有",
    "放手不是失去",
    "不再强求",
    "别无所求",
    "感谢相遇",
    "不谈亏欠",
    "允许一切发生",
    "允许一切结束",
    "接纳离开",
    "接纳结束",
    "只适合收藏",
    "聚散终有时",
    "过去了",
    "带着遗憾往前走",
)
_INNER_SETTLEMENT_REFERENCE_KEYWORDS = (
    "心安",
    "安顿",
    "安顿好自己的心",
    "归宿",
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
    "回到当下",
    "回到日常",
    "住回日子里",
    "重新有了轻重",
    "有归处",
)
_INNER_SETTLEMENT_RUMINATION_KEYWORDS = (
    "想明白",
    "想透",
    "想稳",
    "悬着",
    "反复想",
    "反复琢磨",
    "心结",
    "过不去",
    "拧着",
    "郁结",
    "没松下来",
    "一直在想",
)
_INNER_SETTLEMENT_REGRET_RELEASE_KEYWORDS = (
    "遗憾",
    "往事",
    "回头",
    "如果当初",
    "当初",
    "错过",
    "旧事",
    "旧物",
    "旧裙子",
    "旧照片",
    "聊天记录",
    "收藏",
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
    "重新有轻重",
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
    "隐瞒",
    "撒谎",
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
_RELATIONSHIP_AFTERCARE_WITHDRAWN_STRONG_SIGNALS = (
    "推开",
    "嫌烦",
    "不被理解",
    "误读",
    "无理取闹",
    "不再示弱",
    "收起依赖",
    "袒露软弱",
    "求助落空",
    "没被接住",
    "最需要被接住",
)
_SCENE_FIRST_PROGRESSION_STRUCTURE_KEYWORDS = (
    "连续场景",
    "场景带路",
    "先让场景带路",
    "一到两个连续场景",
    "先写场景",
    "场景推进",
    "画面推进",
    "同一段时间",
    "同一处境现场",
)
_SCENE_FIRST_PROGRESSION_PROGRESS_KEYWORDS = (
    "再展开判断",
    "再安排判断",
    "逐步展开判断",
    "不要直接平铺观点",
    "先不抛结论",
    "先不下判断",
    "后面再提判断",
)
_SCENE_FIRST_PROGRESSION_BODY_TIME_MARKERS = (
    "第二天",
    "清晨",
    "早上",
    "傍晚",
    "夜里",
    "夜里十点",
    "周一早会开始前",
    "散会以后",
    "午休回来",
    "雨停以后",
    "回到家",
    "送孩子",
    "出门前",
    "车来了",
    "推开门",
)
_SCENE_FIRST_PROGRESSION_BODY_ACTION_MARKERS = (
    "推开门",
    "放下",
    "放在",
    "摸了一下",
    "坐下来",
    "坐在原位",
    "站在",
    "听见",
    "看见",
    "看着",
    "盯着",
    "压回",
    "换鞋",
    "换衣",
    "排队",
    "进门",
    "翻了一页",
    "低头",
    "路过",
    "上去",
    "拉了拉",
    "问了一句",
    "端上桌",
    "响了一下",
    "暗了下去",
    "露出一角",
    "揉了揉眉心",
    "收了回去",
    "抬了抬手",
)
_SCENE_FIRST_PROGRESSION_BODY_OBJECT_MARKERS = (
    "餐桌",
    "厨房",
    "屋子",
    "手机屏幕",
    "水壶",
    "药盒",
    "检查单",
    "茶几",
    "玄关",
    "购物车",
    "货架",
    "水杯",
    "便利贴",
    "投影幕布",
    "会议室",
    "灯",
    "桌角",
    "资料",
    "屏幕",
    "白板",
    "记号笔",
    "工牌",
    "电梯门",
    "地铁口",
    "围巾",
    "窗户",
    "白雾",
    "咖啡",
)
_SCENE_FIRST_PROGRESSION_ABSTRACT_THESIS_MARKERS = (
    "原来我们都一样",
    "其实答案很简单",
    "真正的原因",
    "真正让人",
    "很多时候",
    "人这一生",
    "我们终其一生",
    "真正的强大",
    "世界很大",
    "世界也很小",
)
_SCENE_FIRST_OFFICE_KEYWORDS = (
    "会议",
    "会议室",
    "散会",
    "投影",
    "排期",
    "方案",
    "主管",
    "同事",
    "发言",
    "意见",
    "需求",
    "协作",
    "资源",
    "优先级",
    "汇报",
    "工位",
    "白板",
)
_SCENE_FIRST_HOUSEHOLD_KEYWORDS = (
    "钥匙",
    "换鞋",
    "孩子",
    "药盒",
    "检查单",
    "茶几",
    "玄关",
    "厨房",
    "餐桌",
    "爱人",
    "爸妈",
    "晚饭",
    "回家",
    "阳台",
)
_SCENE_FIRST_RELATIONSHIP_KEYWORDS = (
    "地铁口",
    "接驳车",
    "围巾",
    "朋友",
    "关系",
    "疏远",
    "靠近",
    "问出口",
    "没发出去",
    "分别",
    "窗户",
    "白雾",
    "消息框",
    "消息",
    "回消息",
    "开口",
    "算了",
)
_RESILIENCE_RECONSTRUCTION_ADVERSITY_KEYWORDS = (
    "韧性",
    "命运",
    "重击",
    "淬炼",
    "凤凰涅槃",
    "车祸",
    "手术台",
    "剧痛",
    "伤痛",
    "残缺",
    "破碎",
    "疼痛",
)
_RESILIENCE_RECONSTRUCTION_TRAINING_KEYWORDS = (
    "残奥",
    "冠军",
    "泳池",
    "游泳",
    "划水",
    "多划11下",
    "11下",
    "训练",
    "肩伤",
    "背痛",
    "炎症",
    "反复重来",
)
_RESILIENCE_RECONSTRUCTION_IDENTITY_KEYWORDS = (
    "不要让任何人",
    "限制你",
    "破碎中重建",
    "不被定义",
    "自己的太阳",
    "破局而上",
    "重新站起来",
)
_RESILIENCE_RECONSTRUCTION_THESIS_MARKERS = (
    "百折不回",
    "真正的强大",
    "完整的人生",
    "一步步生长",
    "不必借光而行",
)
_SUPPORTIVE_HEALTHY_BODY_MARKERS = ("健康的身体", "爱你的家人", "三两好友", "一碗热饭")


def _read_project_value(project: Mapping[str, object], key: str, default: str = "") -> str:
    try:
        value = project[key]
    except (KeyError, IndexError, TypeError):
        value = default
    if value is None:
        return default
    return str(value)


def _count_keyword_hits(text: str, keywords: tuple[str, ...]) -> int:
    return sum(1 for keyword in keywords if keyword in text)


def build_strategy_package(
    *,
    project: Mapping[str, object],
    problem_brief_version: int,
    strategy_version: int,
    created_at: str,
) -> StrategyPackageResult:
    topic_title = _read_project_value(project, "topic_title")
    topic_angle = _read_project_value(project, "topic_angle")
    trend_title = _read_project_value(project, "trend_title")
    project_slug = _read_project_value(project, "slug")
    source_mode = _read_project_value(project, "source_type", "trend") or "trend"
    reference_title = _read_project_value(project, "reference_article_title")
    reference_source_name = _read_project_value(project, "reference_article_source_name", "手动录入")
    reference_summary = _read_project_value(project, "reference_article_summary")
    reference_structure_notes = _read_project_value(project, "reference_article_structure_notes")
    reference_body_markdown = _read_project_value(project, "reference_article_body_markdown")
    reference_analysis_theme = _read_project_value(project, "reference_article_analysis_theme")
    reference_analysis_core_conflict = _read_project_value(project, "reference_article_analysis_core_conflict")
    reference_analysis_emotional_exit = _read_project_value(project, "reference_article_analysis_emotional_exit")
    reference_analysis_opening_pattern = _read_project_value(project, "reference_article_analysis_opening_pattern")
    reference_analysis_hook_trigger = _read_project_value(project, "reference_article_analysis_hook_trigger")
    reference_analysis_progression_drive = _read_project_value(project, "reference_article_analysis_progression_drive")
    reference_analysis_share_reason = _read_project_value(project, "reference_article_analysis_share_reason")
    reference_analysis_do_not_turn_into = _read_project_value(project, "reference_article_analysis_do_not_turn_into")
    reference_analysis_structure_mode = normalize_structure_mode_hint(
        _read_project_value(project, "reference_article_analysis_structure_mode")
    )
    reference_detection_summary = " ".join(
        part.strip()
        for part in (reference_title, reference_summary)
        if part and part.strip()
    )
    analysis_contract = _build_analysis_first_contract(
        reference_analysis_theme=reference_analysis_theme,
        reference_analysis_core_conflict=reference_analysis_core_conflict,
        reference_analysis_emotional_exit=reference_analysis_emotional_exit,
        reference_analysis_opening_pattern=reference_analysis_opening_pattern,
        reference_analysis_do_not_turn_into=reference_analysis_do_not_turn_into,
    )
    pressure_reference_cues = _extract_pressure_reference_cues(reference_body_markdown)
    primary_pressure_cue = _compact_pressure_reference_cue(pressure_reference_cues[0]) if pressure_reference_cues else ""
    secondary_pressure_cue = _compact_pressure_reference_cue(pressure_reference_cues[1]) if len(pressure_reference_cues) > 1 else ""
    tracked_article_scene = _extract_reference_scene(reference_body_markdown)
    reference_shell_signals = _extract_reference_shell_signals(reference_body_markdown)
    structure_mode = _build_structure_mode(
        source_mode=source_mode,
        topic_angle=topic_angle,
        tracked_article_scene=tracked_article_scene,
        reference_body_markdown=reference_body_markdown,
        reference_summary=reference_detection_summary,
        reference_structure_notes=reference_structure_notes,
        reference_analysis_structure_mode=reference_analysis_structure_mode,
    )
    response_priority_followup_variant = structure_mode == "response_priority" and _uses_response_priority_followup_variant(
        topic_title,
        topic_angle,
        tracked_article_scene,
        reference_detection_summary,
        reference_structure_notes,
        reference_body_markdown,
        reference_analysis_theme,
        reference_analysis_core_conflict,
        reference_analysis_emotional_exit,
        reference_analysis_opening_pattern,
        reference_analysis_do_not_turn_into,
    )
    scene_first_variant = ""
    scene_first_profile: dict[str, str] = {}
    everyday_warmth_variant = ""
    everyday_warmth_profile: dict[str, str] = {}
    self_worth_profile: dict[str, str] = {}
    supportive_profile: dict[str, str] = {}
    inner_settlement_variant = ""
    inner_settlement_profile: dict[str, str] = {}
    emotional_release_variant = ""
    emotional_release_profile: dict[str, str] = {}
    if structure_mode == "scene_first_progression":
        scene_first_variant = _resolve_scene_first_progression_variant(
            topic_title=topic_title,
            topic_angle=topic_angle,
            context_text=" ".join(
                part
                for part in (
                    tracked_article_scene,
                    reference_detection_summary,
                    reference_structure_notes,
                    reference_analysis_theme,
                    reference_analysis_core_conflict,
                    reference_analysis_emotional_exit,
                    reference_analysis_opening_pattern,
                    reference_analysis_do_not_turn_into,
                )
                if part
            ),
        )
        scene_first_profile = _build_scene_first_progression_profile(variant=scene_first_variant)
    if structure_mode == "everyday_warmth_return":
        everyday_warmth_variant = _resolve_everyday_warmth_variant(
            topic_title=topic_title,
            topic_angle=topic_angle,
            context_text=" ".join(
                part
                for part in (
                    tracked_article_scene,
                    reference_detection_summary,
                    reference_structure_notes,
                    reference_body_markdown,
                    reference_analysis_theme,
                    reference_analysis_core_conflict,
                    reference_analysis_emotional_exit,
                    reference_analysis_opening_pattern,
                    reference_analysis_do_not_turn_into,
                )
                if part
            ),
        )
        if everyday_warmth_variant:
            everyday_warmth_profile = _build_everyday_warmth_profile(variant=everyday_warmth_variant)
        if everyday_warmth_variant == "responsibility_shelter":
            analysis_contract = _sanitize_responsibility_shelter_analysis_contract(analysis_contract)
            reference_analysis_theme = analysis_contract.theme
            reference_analysis_core_conflict = analysis_contract.core_conflict
            reference_analysis_emotional_exit = analysis_contract.emotional_exit
            reference_analysis_opening_pattern = analysis_contract.opening_pattern
            reference_analysis_hook_trigger = _sanitize_responsibility_shelter_contract_text(
                reference_analysis_hook_trigger
            )
            reference_analysis_progression_drive = _sanitize_responsibility_shelter_contract_text(
                reference_analysis_progression_drive
            )
            reference_analysis_share_reason = _sanitize_responsibility_shelter_contract_text(
                reference_analysis_share_reason
            )
    if structure_mode == "supportive_appreciation":
        supportive_profile = _build_supportive_appreciation_profile()
    if structure_mode == "self_worth_rebuild":
        self_worth_profile = _build_self_worth_rebuild_profile()
    if structure_mode == "inner_settlement":
        inner_settlement_variant = _resolve_inner_settlement_variant(
            topic_title=topic_title,
            topic_angle=topic_angle,
            context_text=" ".join(
                part
                for part in (
                    tracked_article_scene,
                    reference_detection_summary,
                    reference_structure_notes,
                    reference_body_markdown,
                    reference_analysis_theme,
                    reference_analysis_core_conflict,
                    reference_analysis_emotional_exit,
                    reference_analysis_opening_pattern,
                    reference_analysis_do_not_turn_into,
                )
                if part
            ),
        )
        inner_settlement_profile = _build_inner_settlement_profile(variant=inner_settlement_variant)
    if structure_mode == "emotional_engine_direct":
        emotional_release_variant = _resolve_emotional_release_variant(
            topic_title=topic_title,
            topic_angle=topic_angle,
            context_text=" ".join(
                part
                for part in (
                    tracked_article_scene,
                    reference_detection_summary,
                    reference_structure_notes,
                    reference_body_markdown,
                    reference_analysis_theme,
                    reference_analysis_core_conflict,
                    reference_analysis_emotional_exit,
                    reference_analysis_opening_pattern,
                    reference_analysis_do_not_turn_into,
                )
                if part
            ),
        )
        if emotional_release_variant != "generic":
            emotional_release_profile = _build_emotional_release_profile(variant=emotional_release_variant)
    effective_structure_mode = _resolve_effective_structure_mode(
        structure_mode=structure_mode,
        everyday_warmth_variant=everyday_warmth_variant,
    )
    reader_situation = _build_reader_situation(
        topic_title,
        topic_angle,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    core_conflict = _build_core_conflict(
        topic_title,
        topic_angle,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    normalized_topic_angle = _normalize_topic_angle(
        topic_angle=topic_angle,
        topic_title=topic_title,
        source_mode=source_mode,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    observed_phenomenon = _build_observed_phenomenon(
        topic_title=topic_title,
        topic_angle=topic_angle,
        trend_title=trend_title,
        source_mode=source_mode,
        tracked_article_scene=tracked_article_scene,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    writing_goal = _build_writing_goal(
        topic_title=topic_title,
        topic_angle=topic_angle,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    constraints = _build_problem_constraints(source_mode=source_mode)
    unknowns = _build_unknowns(
        topic_angle=topic_angle,
        source_mode=source_mode,
        tracked_article_scene=tracked_article_scene,
    )
    benchmark_borrow_focus = _build_benchmark_borrow_focus(source_mode, reference_structure_notes, tracked_article_scene)
    benchmark_avoid_focus = _build_benchmark_avoid_focus(source_mode)
    benchmark_summary = _build_benchmark_summary(
        source_mode,
        tracked_article_scene,
        reference_shell_signals,
    )
    point_of_view = _build_point_of_view(
        topic_angle,
        topic_title=topic_title,
        primary_pressure_cue=primary_pressure_cue,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    conflict_frame = _build_conflict_frame(
        topic_title,
        topic_angle,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    emotional_path = _build_emotional_path(
        topic_angle=topic_angle,
        structure_mode=structure_mode,
        pressure_reference_cues=pressure_reference_cues,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    opening_move = _build_opening_move(
        topic_title=topic_title,
        topic_angle=topic_angle,
        tracked_article_scene=tracked_article_scene,
        structure_mode=structure_mode,
        pressure_reference_cues=pressure_reference_cues,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    body_shift = _build_body_shift(
        topic_angle=topic_angle,
        core_conflict=core_conflict,
        structure_mode=structure_mode,
        pressure_reference_cues=pressure_reference_cues,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    ending_move = _build_ending_move(
        topic_angle=topic_angle,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    recomposition_recipe = _build_recomposition_recipe(
        structure_mode=structure_mode,
        topic_angle=topic_angle,
        everyday_warmth_variant=everyday_warmth_variant,
        reference_shell_signals=reference_shell_signals,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    divergence_axes = _build_divergence_axes(
        source_mode=source_mode,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    execution_checklist = _build_execution_checklist(
        structure_mode=structure_mode,
        reference_shell_signals=reference_shell_signals,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    expression_constraints = [
        "不要用口号式收尾",
        "不要复用不是A而是B的对称判断句",
        "不要沿用参考文章的开头对象、推进顺序和结尾判断",
    ]
    if structure_mode == "scene_first_progression":
        expression_constraints.append(scene_first_profile.get("expression_constraint", "不要把场景优先稿写成泛内耗、单人稳情绪或勇敢发声技巧稿。"))
    if structure_mode == "everyday_warmth_return":
        expression_constraints.append("不要把正文重心滑成“长期体谅”“别人继续等你的心气”或“关系坏在冲突之外”这类关系善后判断。")
        expression_constraints.append("不要把手术、停下来或身体受挫写成主要问题，它们只承担价值祛魅的转折证据。")
    if everyday_warmth_profile.get("expression_constraint"):
        expression_constraints.append(str(everyday_warmth_profile["expression_constraint"]))
    if structure_mode == "supportive_appreciation":
        expression_constraints.append("主题必须继续停留在柔软为什么被误读、为什么值得被珍惜，不要偏离参考文真正的矛盾和情绪出口。")
    if structure_mode == "response_priority" and response_priority_followup_variant:
        expression_constraints.append("少重复“真正的关心”“真正让人踏实”这类总括句，同一个抽象判断最多点明 1 次，其余都落回补问、停顿、记得和被听懂的动作。")
        expression_constraints.append("少把“轻互动”“很多人”“很多女生”“很多时候”“其实”放在段首做总括，前半篇优先让对话、停顿和小动作自己把意思顶出来。")
    if structure_mode == "self_worth_rebuild":
        expression_constraints.append("主题必须继续停留在自我价值、边界和标准为什么会一路被放低，以及人怎样把尊重和分量收回来，不要滑成消息悬停、沟通表达或高位狠话。")
    if structure_mode == "relationship_aftercare":
        expression_constraints.append("少写“真正伤人的不是……”或“关系不是输在……而是输在……”这类整齐翻转句。")
    if structure_mode == "resilience_reconstruction":
        expression_constraints.append("不要把命运重击和训练重建稿改写成“把自己排回前面”“照顾自己”或“术后恢复”这类自我照料文。")
        expression_constraints.append("不要把人物写成被别人接住的关系稿，主线要留在疼痛、训练和不被定义的重建上。")
    if emotional_release_profile.get("expression_constraint"):
        expression_constraints.append(str(emotional_release_profile["expression_constraint"]))
    expression_constraints = merge_unique_lines(
        expression_constraints,
        _build_reference_shell_expression_constraints(reference_shell_signals),
    )
    divergence_axes = merge_unique_lines(
        divergence_axes,
        _build_reference_shell_divergence_axes(reference_shell_signals),
    )
    feedback_entry = _build_feedback_entry(
        reader_situation=reader_situation,
        core_conflict=core_conflict,
        topic_title=topic_title,
        topic_angle=topic_angle,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    problem_explanation = _build_problem_explanation(
        topic_title=topic_title,
        topic_angle=topic_angle,
        observed_phenomenon=observed_phenomenon,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    if structure_mode == "scene_first_progression":
        reader_situation = scene_first_profile.get("reader_situation", reader_situation)
        core_conflict = scene_first_profile.get("core_conflict", core_conflict)
        normalized_topic_angle = scene_first_profile.get("normalized_topic_angle", normalized_topic_angle)
        observed_phenomenon = scene_first_profile.get("observed_phenomenon", observed_phenomenon)
        writing_goal = scene_first_profile.get("writing_goal", writing_goal)
        benchmark_borrow_focus = scene_first_profile.get("benchmark_borrow_focus", benchmark_borrow_focus)
        benchmark_summary = scene_first_profile.get("benchmark_summary", benchmark_summary)
        point_of_view = scene_first_profile.get("point_of_view", point_of_view)
        conflict_frame = scene_first_profile.get("conflict_frame", conflict_frame)
        emotional_path = scene_first_profile.get("emotional_path", emotional_path)
        opening_move = scene_first_profile.get("opening_move", opening_move)
        body_shift = scene_first_profile.get("body_shift", body_shift)
        ending_move = scene_first_profile.get("ending_move", ending_move)
        feedback_entry = scene_first_profile.get("feedback_entry", feedback_entry)
        problem_explanation = scene_first_profile.get("problem_explanation", problem_explanation)
    if everyday_warmth_profile:
        reader_situation = everyday_warmth_profile.get("reader_situation", reader_situation)
        core_conflict = everyday_warmth_profile.get("core_conflict", core_conflict)
        normalized_topic_angle = everyday_warmth_profile.get("normalized_topic_angle", normalized_topic_angle)
        observed_phenomenon = everyday_warmth_profile.get("observed_phenomenon", observed_phenomenon)
        writing_goal = everyday_warmth_profile.get("writing_goal", writing_goal)
        benchmark_borrow_focus = everyday_warmth_profile.get("benchmark_borrow_focus", benchmark_borrow_focus)
        benchmark_summary = everyday_warmth_profile.get("benchmark_summary", benchmark_summary)
        point_of_view = everyday_warmth_profile.get("point_of_view", point_of_view)
        conflict_frame = everyday_warmth_profile.get("conflict_frame", conflict_frame)
        emotional_path = everyday_warmth_profile.get("emotional_path", emotional_path)
        opening_move = everyday_warmth_profile.get("opening_move", opening_move)
        body_shift = everyday_warmth_profile.get("body_shift", body_shift)
        ending_move = everyday_warmth_profile.get("ending_move", ending_move)
        feedback_entry = everyday_warmth_profile.get("feedback_entry", feedback_entry)
        problem_explanation = everyday_warmth_profile.get("problem_explanation", problem_explanation)
    if structure_mode == "supportive_appreciation":
        reader_situation = supportive_profile.get("reader_situation", reader_situation)
        core_conflict = supportive_profile.get("core_conflict", core_conflict)
        normalized_topic_angle = supportive_profile.get("normalized_topic_angle", normalized_topic_angle)
        observed_phenomenon = supportive_profile.get("observed_phenomenon", observed_phenomenon)
        writing_goal = supportive_profile.get("writing_goal", writing_goal)
        benchmark_borrow_focus = supportive_profile.get("benchmark_borrow_focus", benchmark_borrow_focus)
        benchmark_summary = supportive_profile.get("benchmark_summary", benchmark_summary)
        point_of_view = supportive_profile.get("point_of_view", point_of_view)
        conflict_frame = supportive_profile.get("conflict_frame", conflict_frame)
        emotional_path = supportive_profile.get("emotional_path", emotional_path)
        opening_move = supportive_profile.get("opening_move", opening_move)
        body_shift = supportive_profile.get("body_shift", body_shift)
        ending_move = supportive_profile.get("ending_move", ending_move)
        feedback_entry = supportive_profile.get("feedback_entry", feedback_entry)
        problem_explanation = supportive_profile.get("problem_explanation", problem_explanation)
    if structure_mode == "self_worth_rebuild":
        reader_situation = self_worth_profile.get("reader_situation", reader_situation)
        core_conflict = self_worth_profile.get("core_conflict", core_conflict)
        normalized_topic_angle = self_worth_profile.get("normalized_topic_angle", normalized_topic_angle)
        observed_phenomenon = self_worth_profile.get("observed_phenomenon", observed_phenomenon)
        writing_goal = self_worth_profile.get("writing_goal", writing_goal)
        benchmark_summary = self_worth_profile.get("benchmark_summary", benchmark_summary)
        point_of_view = self_worth_profile.get("point_of_view", point_of_view)
        conflict_frame = self_worth_profile.get("conflict_frame", conflict_frame)
        emotional_path = self_worth_profile.get("emotional_path", emotional_path)
        opening_move = self_worth_profile.get("opening_move", opening_move)
        body_shift = self_worth_profile.get("body_shift", body_shift)
        ending_move = self_worth_profile.get("ending_move", ending_move)
        feedback_entry = self_worth_profile.get("feedback_entry", feedback_entry)
        problem_explanation = self_worth_profile.get("problem_explanation", problem_explanation)
    if structure_mode == "inner_settlement":
        reader_situation = inner_settlement_profile.get("reader_situation", reader_situation)
        core_conflict = inner_settlement_profile.get("core_conflict", core_conflict)
        normalized_topic_angle = inner_settlement_profile.get("normalized_topic_angle", normalized_topic_angle)
        observed_phenomenon = inner_settlement_profile.get("observed_phenomenon", observed_phenomenon)
        writing_goal = inner_settlement_profile.get("writing_goal", writing_goal)
        benchmark_borrow_focus = inner_settlement_profile.get("benchmark_borrow_focus", benchmark_borrow_focus)
        benchmark_summary = inner_settlement_profile.get("benchmark_summary", benchmark_summary)
        point_of_view = inner_settlement_profile.get("point_of_view", point_of_view)
        conflict_frame = inner_settlement_profile.get("conflict_frame", conflict_frame)
        emotional_path = inner_settlement_profile.get("emotional_path", emotional_path)
        opening_move = inner_settlement_profile.get("opening_move", opening_move)
        body_shift = inner_settlement_profile.get("body_shift", body_shift)
        ending_move = inner_settlement_profile.get("ending_move", ending_move)
        feedback_entry = inner_settlement_profile.get("feedback_entry", feedback_entry)
        problem_explanation = inner_settlement_profile.get("problem_explanation", problem_explanation)
    if emotional_release_profile:
        reader_situation = emotional_release_profile.get("reader_situation", reader_situation)
        core_conflict = emotional_release_profile.get("core_conflict", core_conflict)
        normalized_topic_angle = emotional_release_profile.get("normalized_topic_angle", normalized_topic_angle)
        observed_phenomenon = emotional_release_profile.get("observed_phenomenon", observed_phenomenon)
        writing_goal = emotional_release_profile.get("writing_goal", writing_goal)
        benchmark_summary = emotional_release_profile.get("benchmark_summary", benchmark_summary)
        point_of_view = emotional_release_profile.get("point_of_view", point_of_view)
        conflict_frame = emotional_release_profile.get("conflict_frame", conflict_frame)
        emotional_path = emotional_release_profile.get("emotional_path", emotional_path)
        opening_move = emotional_release_profile.get("opening_move", opening_move)
        body_shift = emotional_release_profile.get("body_shift", body_shift)
        ending_move = emotional_release_profile.get("ending_move", ending_move)
        feedback_entry = emotional_release_profile.get("feedback_entry", feedback_entry)
        problem_explanation = emotional_release_profile.get("problem_explanation", problem_explanation)
    point_of_view = _enrich_point_of_view_with_analysis_contract(point_of_view, contract=analysis_contract)
    conflict_frame = _enrich_conflict_frame_with_analysis_contract(conflict_frame, contract=analysis_contract)
    problem_explanation = _enrich_problem_explanation_with_analysis_contract(
        problem_explanation,
        contract=analysis_contract,
    )
    opening_move = _enrich_opening_move_with_analysis_contract(opening_move, contract=analysis_contract)
    body_shift = _enrich_body_shift_with_analysis_contract(body_shift, contract=analysis_contract)
    ending_move = _enrich_ending_move_with_analysis_contract(ending_move, contract=analysis_contract)
    problem_statement_markdown = _build_problem_statement_markdown(
        topic_title=topic_title,
        normalized_topic_angle=normalized_topic_angle,
        trend_title=trend_title,
        source_mode=source_mode,
        structure_mode=structure_mode,
        observed_phenomenon=observed_phenomenon,
        writing_goal=writing_goal,
        reader_situation=reader_situation,
        core_conflict=core_conflict,
        constraints=constraints,
        feedback_entry=feedback_entry,
        problem_explanation=problem_explanation,
        reference_title=reference_title,
        reference_source_name=reference_source_name,
        reference_summary=reference_summary,
        tracked_article_scene=tracked_article_scene,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
    )
    emotional_value_goal = _build_emotional_value_goal(
        structure_mode=structure_mode,
        reference_analysis_emotional_exit=reference_analysis_emotional_exit,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    theme_axis = _build_theme_axis(
        structure_mode=structure_mode,
        reference_analysis_theme=reference_analysis_theme,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    anti_drift_axis = _build_anti_drift_axis(
        structure_mode=structure_mode,
        reference_analysis_do_not_turn_into=reference_analysis_do_not_turn_into,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    positive_direction = _build_positive_direction(
        structure_mode=structure_mode,
        reference_analysis_emotional_exit=reference_analysis_emotional_exit,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    hook_trigger = _build_hook_trigger(
        structure_mode=structure_mode,
        reference_analysis_hook_trigger=reference_analysis_hook_trigger,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    progression_drive = _build_progression_drive(
        structure_mode=structure_mode,
        reference_analysis_progression_drive=reference_analysis_progression_drive,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    share_reason = _build_share_reason(
        structure_mode=structure_mode,
        reference_analysis_share_reason=reference_analysis_share_reason,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    reference_fingerprint = _build_reference_article_fingerprint(
        structure_mode=structure_mode,
        reference_body_markdown=reference_body_markdown,
        reference_summary=reference_summary,
        reference_analysis_theme=reference_analysis_theme,
        reference_analysis_core_conflict=reference_analysis_core_conflict,
        reference_analysis_emotional_exit=reference_analysis_emotional_exit,
        reference_analysis_opening_pattern=reference_analysis_opening_pattern,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    quotable_line_goal = _build_quotable_line_goal(
        structure_mode=structure_mode,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    scene_anchor_requirements = _build_scene_anchor_requirements(
        structure_mode=structure_mode,
        topic_title=topic_title,
        topic_angle=topic_angle,
        reference_body_markdown=reference_body_markdown,
        reference_fingerprint=reference_fingerprint,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    realism_texture_goal = _build_realism_texture_goal(
        structure_mode=structure_mode,
        reference_fingerprint=reference_fingerprint,
    )
    quotable_line_seeds = _build_quotable_line_seeds(
        structure_mode=structure_mode,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        reference_fingerprint=reference_fingerprint,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    writing_texture_notes = _build_writing_texture_notes(
        structure_mode=structure_mode,
        reference_body_markdown=reference_body_markdown,
        reference_analysis_opening_pattern=reference_analysis_opening_pattern,
        reference_analysis_do_not_turn_into=reference_analysis_do_not_turn_into,
        reference_analysis_emotional_exit=reference_analysis_emotional_exit,
        reference_shell_signals=reference_shell_signals,
        reference_fingerprint=reference_fingerprint,
    )
    packaging_focus = _build_packaging_focus(
        structure_mode=structure_mode,
        reference_analysis_opening_pattern=reference_analysis_opening_pattern,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        reference_fingerprint=reference_fingerprint,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    packaging_focus = _enrich_packaging_focus_with_analysis_contract(
        packaging_focus,
        contract=analysis_contract,
    )
    packaging_hook = _build_packaging_hook(
        structure_mode=structure_mode,
        topic_title=topic_title,
        topic_angle=topic_angle,
        reference_analysis_opening_pattern=reference_analysis_opening_pattern,
        reference_body_markdown=reference_body_markdown,
        everyday_warmth_variant=everyday_warmth_variant,
        reference_fingerprint=reference_fingerprint,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    if structure_mode == "scene_first_progression":
        hook_trigger = scene_first_profile.get("hook_trigger", hook_trigger)
        progression_drive = scene_first_profile.get("progression_drive", progression_drive)
        share_reason = scene_first_profile.get("share_reason", share_reason)
        packaging_hook = scene_first_profile.get("packaging_hook", packaging_hook)
    strategy_markdown = _build_strategy_markdown(
        topic_title=topic_title,
        normalized_topic_angle=normalized_topic_angle,
        source_mode=source_mode,
        reader_situation=reader_situation,
        point_of_view=point_of_view,
        conflict_frame=conflict_frame,
        emotional_path=emotional_path,
        emotional_value_goal=emotional_value_goal,
        theme_axis=theme_axis,
        anti_drift_axis=anti_drift_axis,
        hook_trigger=hook_trigger,
        progression_drive=progression_drive,
        share_reason=share_reason,
        positive_direction=positive_direction,
        quotable_line_goal=quotable_line_goal,
        packaging_focus=packaging_focus,
        packaging_hook=packaging_hook,
        writing_texture_notes=writing_texture_notes,
        scene_anchor_requirements=scene_anchor_requirements,
        realism_texture_goal=realism_texture_goal,
        quotable_line_seeds=quotable_line_seeds,
        structure_mode=structure_mode,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
        opening_move=opening_move,
        body_shift=body_shift,
        ending_move=ending_move,
        recomposition_recipe=recomposition_recipe,
        benchmark_summary=benchmark_summary,
        expression_constraints=expression_constraints,
        divergence_axes=divergence_axes,
        execution_checklist=execution_checklist,
        reference_title=reference_title,
        reference_source_name=reference_source_name,
        benchmark_borrow_focus=benchmark_borrow_focus,
        benchmark_avoid_focus=benchmark_avoid_focus,
        tracked_article_scene=tracked_article_scene,
        reference_shell_signals=reference_shell_signals,
    )
    clarified_problem = _build_clarified_problem(
        topic_title=topic_title,
        topic_angle=topic_angle,
        observed_phenomenon=observed_phenomenon,
        primary_pressure_cue=primary_pressure_cue,
        secondary_pressure_cue=secondary_pressure_cue,
        structure_mode=structure_mode,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    if structure_mode == "scene_first_progression":
        clarified_problem = scene_first_profile.get("clarified_problem", clarified_problem)
    if structure_mode == "supportive_appreciation":
        clarified_problem = supportive_profile.get("clarified_problem", clarified_problem)
    if structure_mode == "inner_settlement":
        clarified_problem = inner_settlement_profile.get("clarified_problem", clarified_problem)
    if everyday_warmth_profile:
        clarified_problem = everyday_warmth_profile.get("clarified_problem", clarified_problem)
    if emotional_release_profile:
        clarified_problem = emotional_release_profile.get("clarified_problem", clarified_problem)

    problem_brief = ProblemBriefItem(
        project_slug=project_slug,
        version=problem_brief_version,
        source_mode=source_mode,
        raw_goal=topic_title,
        clarified_problem=clarified_problem,
        observed_phenomenon=observed_phenomenon,
        writing_goal=writing_goal,
        problem_explanation=problem_explanation,
        emotional_value_goal=emotional_value_goal,
        theme_axis=theme_axis,
        anti_drift_axis=anti_drift_axis,
        target_reader_situation=reader_situation,
        core_conflict=core_conflict,
        unknowns=unknowns,
        constraints=constraints,
        feedback_entry=feedback_entry,
        problem_statement_markdown=problem_statement_markdown,
        status="ready",
        created_at=created_at,
    )

    benchmarks = [
        BenchmarkReferenceItem(
            project_slug=project_slug,
            strategy_version=strategy_version,
            reference_kind=_resolve_reference_kind(source_mode),
            reference_label=_resolve_reference_label(project, source_mode),
            reference_pointer=_read_project_value(project, "source_ref_slug", project_slug) or project_slug,
            borrow_focus=benchmark_borrow_focus,
            avoid_focus=benchmark_avoid_focus,
            rationale="只借观察路径、冲突组织和节奏职责，不借原标题、现成判断句和段落次序。",
            sort_order=1,
        )
    ]

    strategy_card = StrategyCardItem(
        project_slug=project_slug,
        version=strategy_version,
        problem_brief_version=problem_brief_version,
        reader_situation=reader_situation,
        point_of_view=point_of_view,
        conflict_frame=conflict_frame,
        emotional_path=emotional_path,
        hook_trigger=hook_trigger,
        progression_drive=progression_drive,
        share_reason=share_reason,
        positive_direction=positive_direction,
        quotable_line_goal=quotable_line_goal,
        packaging_focus=packaging_focus,
        packaging_hook=packaging_hook,
        realism_texture_goal=realism_texture_goal,
        structure_mode=effective_structure_mode,
        opening_move=opening_move,
        body_shift=body_shift,
        ending_move=ending_move,
        recomposition_recipe=recomposition_recipe,
        writing_texture_notes=writing_texture_notes,
        scene_anchor_requirements=scene_anchor_requirements,
        quotable_line_seeds=quotable_line_seeds,
        expression_constraints=expression_constraints,
        divergence_axes=divergence_axes,
        execution_checklist=execution_checklist,
        benchmark_summary=benchmark_summary,
        strategy_markdown=strategy_markdown,
        status="ready",
        created_at=created_at,
        adopted_at=None,
    )

    if everyday_warmth_variant == "responsibility_shelter":
        problem_brief = _sanitize_responsibility_shelter_problem_brief(problem_brief)
        benchmarks = [_sanitize_responsibility_shelter_benchmark(item) for item in benchmarks]
        strategy_card = _sanitize_responsibility_shelter_strategy_card(strategy_card)

    return StrategyPackageResult(
        project_slug=project_slug,
        problem_brief=problem_brief,
        benchmarks=benchmarks,
        strategy_card=strategy_card,
    )


def _resolve_reference_kind(source_mode: str) -> str:
    if source_mode == "tracked_article":
        return "tracked_article"
    if source_mode == "manual":
        return "operator_reference"
    return "trend"


def _resolve_reference_label(project: Mapping[str, object], source_mode: str) -> str:
    if source_mode == "tracked_article":
        title = _read_project_value(project, "reference_article_title").strip()
        if title:
            return title
    if source_mode == "manual":
        return _read_project_value(project, "topic_title")
    return _read_project_value(project, "trend_title")


def _build_emotional_value_goal(
    *,
    structure_mode: str,
    reference_analysis_emotional_exit: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    normalized_exit = re.sub(r"\s+", " ", reference_analysis_emotional_exit).strip(" \n\t。；;，,")
    if structure_mode == "inner_settlement" and inner_settlement_variant == "stage_restart":
        if normalized_exit:
            return (
                "让读者读完后不只明白道理，还能真的从阶段性自责里退一步："
                f"{normalized_exit}。"
            )
        return "让读者从阶段性自责里退一步，不再急着给这段路判输赢，而是重新看见仍在发生的支撑、积累和下一步要过的生活。"
    if normalized_exit:
        return f"让读者读完后不只明白道理，还能真的被带到这一步：{normalized_exit}。"

    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            return "让读者不只觉得辛苦被看见，还能感到自己为家多想的每一步，都在慢慢换来父母安心、孩子底气和家里的踏实。"
        return "让读者从成就叙事和重要感焦虑里松下来，重新认出眼前生活里已经拥有的温度。"
    if structure_mode == "inner_settlement":
        return "让读者先被理解、再被安顿，不是继续反刍，而是慢慢回到今天能过下去的状态。"
    if structure_mode == "self_worth_rebuild":
        return "让读者不只是在委屈里被共情，而是真的慢慢把分量、边界和尊重收回自己身上。"
    if structure_mode == "self_reliance_inward_support":
        return "让读者读完后不只是更能忍，而是知道怎样从慌乱里回神，用一个具体动作把眼前这一步接稳。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "让读者从轻互动的热闹里松下来，重新认出真正让人踏实的，是有人愿意停下来读懂你。"
        return "让读者从等待和替人找理由里清醒一点，把时间和心收回更值得的地方。"
    if structure_mode == "supportive_appreciation":
        return "让读者读完后能看见柔软不是软弱，也更愿意珍惜真正会接住自己的人。"
    if structure_mode == "relationship_aftercare":
        return "让读者在失望之外，看清修复有没有发生，也看清一段关系值不值得继续。"
    if structure_mode == "resilience_reconstruction":
        return "让读者从佩服走到被鼓舞，看见一个人怎样在反复重来里把自己慢慢重建起来。"
    if structure_mode == "emotional_engine_direct":
        return "让读者从执念、遗憾或误认里退一步，最后留下的是理解、释怀和继续往前的力气。"
    if structure_mode == "scene_first_progression":
        return "让读者先进入参考文自己的现场，再顺着现场里的变化慢慢看懂这段情绪。"
    if structure_mode == "pressure_interface_direct":
        return "让读者读完后不再只会硬扛，而是会重新看见生活排序和自我照料的必要。"
    return "让读者先认出参考文自己的处境，再从这篇文章的关系、选择或日常里得到一点继续往前的力气。"


def _build_positive_direction(
    *,
    structure_mode: str,
    reference_analysis_emotional_exit: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    normalized_exit = re.sub(r"\s+", " ", reference_analysis_emotional_exit).strip()
    if structure_mode == "inner_settlement" and inner_settlement_variant == "stage_restart":
        if normalized_exit:
            return f"{normalized_exit}，并把人继续送回眼前生活和下一步。"
        return "结尾回到阶段误判被松开、眼前生活重新接住人，以及人怎样带着下一步的期待继续往前，不要停在年中自责和给自己打分上。"
    if normalized_exit:
        return normalized_exit

    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            return "结尾回到家里仍亮着的灯、有人一起分担和日子被慢慢托稳，不要收成苦难赞歌、消耗诊断或空泛打气。"
        if everyday_warmth_variant == "simple_happiness":
            return "结尾回到家人平安、知己仍在和一顿热饭这样的具体回温，让人重新相信简单快乐不是退而求其次。"
        return "结尾回到普通日常、陪伴和已经拥有的部分，让人从“大事执念”里退出来。"
    if structure_mode == "inner_settlement":
        return "结尾回到心慢慢放平、日常重新回温，不要停在悬着、难受和继续反刍上。"
    if structure_mode == "self_worth_rebuild":
        return "结尾回到边界重新立住、标准慢慢收紧和人终于不再总把自己放轻，不要停在控诉、委屈或翻旧账上。"
    if structure_mode == "self_reliance_inward_support":
        return "结尾回到求助不丢人、自救也不丢人，把判断和行动重新放回自己手里，不要把情绪停在失落和空转里。"
    if structure_mode == "trust_boundary":
        return "结尾回到坦诚、交代和日常里一次次说到做到，让读者看见这份心安值得被认真守住。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "结尾回到被理解、被记得和真正被放在心上的安稳感，不要只停在比较谁更在乎。"
        return "结尾回到认清位置、重新分配时间和感情，不要只停在被忽视和难过上。"
    if structure_mode == "supportive_appreciation":
        return "结尾回到珍惜、被珍惜和关系里的尊重感，不要把柔软写成一味受委屈。"
    if structure_mode == "relationship_aftercare":
        return "结尾回到修复有没有发生、有没有人回来承担，而不是把整篇停在争吵后的冷气里。"
    if structure_mode == "resilience_reconstruction":
        return "结尾回到继续重建、拒绝被定义和仍在向前，不要写成单纯苦难陈列。"
    if structure_mode == "emotional_engine_direct":
        return "结尾回到理解、释怀或带着所得继续往前，不要只收在遗憾和舍不得里。"
    if structure_mode == "scene_first_progression":
        return "结尾回到一个更清楚、更轻一点的判断或动作，让人感觉现场之后还有路能走。"
    if structure_mode == "pressure_interface_direct":
        return "结尾回到排序被重新看见和一点点调回来的生活，不要只停在代价上。"
    return "结尾要比前文更暖一点，给人被稳住、能继续往前的感觉。"


def _build_hook_trigger(
    *,
    structure_mode: str,
    reference_analysis_hook_trigger: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    normalized = re.sub(r"\s+", " ", reference_analysis_hook_trigger).strip()
    if normalized:
        return normalized
    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            return "家里临时有事、自己先把顺序理清，让一家人跟着稳下来的当场。"
        if everyday_warmth_variant == "simple_happiness":
            return "某个普通晚上，一顿热饭、一句惦记，突然让人不想再拿更大的拥有证明日子。"
        return "有些晚上，推开家门闻到饭香，人才忽然不想再和谁比较了。"
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            return "翻到阶段清单、对着没完成的几项停住，却差点把自己整段算低的那一下。"
        return "心明明还悬着，却被一个普通安排慢慢接回今天的那一下。"
    if structure_mode == "self_worth_rebuild":
        return "你其实已经不舒服了，可那句“都可以”还是比真实想法先出了口。"
    if structure_mode == "self_reliance_inward_support":
        return "有些委屈，话到嘴边会先停一下。你开始懂得，每个人都有自己的难处，也都有撑不住的时候。"
    if structure_mode == "trust_boundary":
        return "听见前后两个版本时，手里的筷子会先停一下。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "一句轻描淡写的话，到底有没有被听懂、有没有人愿意继续多问一句。"
        return "消息、评论或碎片时间被给出去的那一下，谁真正被排在了前面。"
    if structure_mode == "supportive_appreciation":
        return "她顺手让了一步、先顾了别人感受，结果又被当成理所当然的那一下。"
    if structure_mode == "relationship_aftercare":
        return "吵完以后那段冷下来的空白里，到底有没有人回来接住。"
    if structure_mode == "resilience_reconstruction":
        return "重击、手术、训练或疼痛第一次把人真正按在现实里的那一下。"
    if structure_mode == "scene_first_progression":
        return "明明就差一句，话到嘴边时，人还是先沉默了。"
    if structure_mode == "pressure_interface_direct":
        return "身体或生活顺序已经开始出代价，却还在往后拖的那一下。"
    return ""


def _build_progression_drive(
    *,
    structure_mode: str,
    reference_analysis_progression_drive: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    normalized = re.sub(r"\s+", " ", reference_analysis_progression_drive).strip()
    if normalized:
        return normalized
    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            return "责任先把人往前推，再让父母、孩子、伴侣和家里的安稳把这些辛苦一点点说成值得。"
        if everyday_warmth_variant == "simple_happiness":
            return "人为什么总把幸福押在更大的拥有上，以及家人平安、知己仍在为什么会在后来重新显出分量。"
        return "更大的拥有为什么会慢慢失重，以及普通日常为什么会重新把一个人接住。"
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            return "阶段误判怎样被认出来，遗憾怎样被安放，眼前生活又怎样把人送回下一步。"
        return "那颗心为什么一直悬着，又怎样从现实余波里慢慢回稳。"
    if structure_mode == "self_worth_rebuild":
        return "迁就怎样慢慢变成降级，边界怎样一退再退，又怎样被重新立住。"
    if structure_mode == "self_reliance_inward_support":
        return "人为什么会被处境推到慌里，又怎样用一个具体判断、动作或选择把日子慢慢接稳。"
    if structure_mode == "trust_boundary":
        return "信任怎样从放心到裂缝，再怎样靠坦诚、交代和说到做到一点点重新落稳。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "表面热闹和真正被读懂之间的分量差别，怎样一点点把心放稳。"
        return "表层回应怎样被误认成在乎，顺序和追问又怎样更早显出位置感。"
    if structure_mode == "supportive_appreciation":
        return "柔软为什么总被误读，以及真正愿意珍惜这份柔软的人为什么稀缺。"
    if structure_mode == "relationship_aftercare":
        return "争执过后谁回来修复、谁继续回避，关系怎样在这些动作里显出答案。"
    if structure_mode == "resilience_reconstruction":
        return "疼痛、训练和拒绝被定义，怎样一起把人从重击里重新立起来。"
    if structure_mode == "scene_first_progression":
        return "那句没说出口的话怎样在现场被压回去，又怎样在事后把位置感慢慢改写。"
    if structure_mode == "pressure_interface_direct":
        return "代价怎样一点点显形，人又为什么总要拖到更难受时才肯回头。"
    return ""


def _build_share_reason(
    *,
    structure_mode: str,
    reference_analysis_share_reason: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    normalized = re.sub(r"\s+", " ", reference_analysis_share_reason).strip()
    if normalized:
        return normalized
    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            return "它写出了很多成年人嘴上轻描淡写、心里却一直惦记家里的那部分，也给了人继续认真往前走的安慰。"
        if everyday_warmth_variant == "simple_happiness":
            return "它会让人重新校准幸福的坐标，认出家人平安、知己仍在和日子热乎着，本来就是很大的福气。"
        return "它会让人重新看见那些一直被放轻的小日常，认出原来真正托住自己的东西并不喧哗。"
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            return "它接住了阶段节点上的自责，也把人慢慢送回眼前还能继续的生活里。"
        return "它不像空泛安慰，更像把那颗一直悬着的心轻轻放回今天。"
    if structure_mode == "self_worth_rebuild":
        return "它会让总把自己放轻的人认出问题不只在别人，也在自己一次次退让的地方。"
    if structure_mode == "self_reliance_inward_support":
        return "它不是硬扛鸡血，而是让人在承压时看到自己还能做的那一步，慢慢把日子接稳。"
    if structure_mode == "trust_boundary":
        return "它会让人想起那个愿意放心相信自己的人，也提醒读到的人别把这份赤诚当成可以含糊带过的小事。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "它会让人想起自己那句没说完的话，有没有真的被谁听懂和接住。"
        return "它会让人一下看清时间和顺序到底给了谁，也帮人把心力收回来。"
    if structure_mode == "supportive_appreciation":
        return "它会让柔软的人被看见，也会让读到的人更知道该怎样珍惜这样的人。"
    if structure_mode == "relationship_aftercare":
        return "它让人看见争执之后真正伤人的地方，也给出关系值不值得继续的判断入口。"
    if structure_mode == "resilience_reconstruction":
        return "它不只讲苦难，更让人看见继续重建和不被定义的力量。"
    if structure_mode == "scene_first_progression":
        return "它像把一个人卡住很久的现场重新照亮，让读者很容易认出自己的那一下犹豫。"
    if structure_mode == "pressure_interface_direct":
        return "它不是泛泛喊累，而是把代价已经发生的那部分写得很具体，读者容易立刻对号入座。"
    return ""


def _build_quotable_line_goal(
    *,
    structure_mode: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            return "允许 1 句把责任、家里踏实和自我照顾说透的人话短句，像从来电、日历和灯光后面自己长出来，不要写成苦难赞歌或万能鸡汤。"
        if everyday_warmth_variant == "simple_happiness":
            return "允许 1 句把幸福坐标改回来的人话短句，像从一顿热饭、一盏灯或一句惦记里自己长出来，不要写成空泛知足宣言。"
        return "允许 1 句贴着日常长出来的短判断，像把人从宏大叙事里轻轻拉回饭桌、灯光或陪伴，不要空降大道理。"
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            return "允许 1 句把阶段误判点破、又把人从自我清算里轻轻接回来的短句，不要写成万能疗愈句或年中鸡汤标语。"
        return "允许 1 句像心里忽然松一下的人话，短一点，贴着当下，不要写成万能疗愈句。"
    if structure_mode == "self_worth_rebuild":
        return "允许 1 句把自我轻放、边界松动或重新把自己抬回来的那一下说透的短句，锋利一点，但不要写成狠话宣言。"
    if structure_mode == "self_reliance_inward_support":
        return "允许 1 句从硬撑和回稳动作里长出来的短句，像从慌里把今天接回来，不要喊励志口号。"
    if structure_mode == "trust_boundary":
        return "允许 1 句把信任、坦诚或说到做到讲透的短句，温柔但要有分量，不要写成审判、查岗或控制欲。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "允许 1 句把被读懂、被追问或被轻轻接住那一下说透的短句，温暖一点，但不要写成社交平台热评体。"
        return "允许 1 句把顺序显出来的短判断，直接一点，但不要写成网络热评体。"
    if structure_mode == "supportive_appreciation":
        return "允许 1 句把柔软和珍贵点亮的短句，温柔但别悬浮。"
    if structure_mode == "relationship_aftercare":
        return "允许 1 句把失望或修复说透的短判断，像关系里真实会冒出来的话，不要像模板金句。"
    if structure_mode == "resilience_reconstruction":
        return "允许 1 句从训练、疼痛或不被定义里长出来的短句，不要排比励志。"
    if structure_mode == "emotional_engine_direct":
        return "允许 1 句把误认点破或把放下说透的短句，但必须贴着前文冲突，不要空喊看开。"
    if structure_mode == "scene_first_progression":
        return "允许 1 句从场景里突然冒出来的人话，像走到某一步才终于认出来的判断。"
    if structure_mode == "pressure_interface_direct":
        return "允许 1 句把代价和回神点出来的短判断，别写成教程标题。"
    return "允许 1 到 2 句贴着现实处境长出来的短句，但不要堆砌成金句墙。"


def _build_packaging_focus(
    *,
    structure_mode: str,
    reference_analysis_opening_pattern: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    reference_fingerprint: ReferenceArticleFingerprint | None = None,
    response_priority_followup_variant: bool = False,
) -> str:
    normalized_opening = re.sub(r"\s+", " ", reference_analysis_opening_pattern).strip()
    specific_focus = _build_reference_specific_packaging_focus(
        reference_fingerprint or ReferenceArticleFingerprint()
    )
    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            base = "标题、导语和封面优先抓肩上的责任、先稳住家里的顺序和被护住的安稳，不要再借别的回温模板去转述。"
            return f"{specific_focus} {base}".strip() if specific_focus else base
        if everyday_warmth_variant == "simple_happiness":
            base = "标题、导语和封面优先抓“更大的拥有慢慢失重”和“家人平安、知己仍在重新有分量”的改写瞬间，不要落回泛幸福感悟。"
            return f"{specific_focus} {base}".strip() if specific_focus else base
        base = "标题、导语和封面优先抓“大事祛魅/小事回温”的入口，最好有一个误判被改写的瞬间，再把落点带回普通生活。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            base = "包装优先抓阶段节点上的自我误判、几项空着的结果和回神点，不要只概括成长道理，也不要滑成泛心安摘要。"
            return f"{specific_focus} {base}".strip() if specific_focus else base
        base = "包装优先抓“心一直没放下”的接口和回稳落点，不要只做心灵感悟摘要。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "self_worth_rebuild":
        base = "包装优先抓一个人总把自己放轻、后来才认出边界和体面正在往下掉的那一下，再带回尊重自己、把分寸和分量收回来的回正点。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "self_reliance_inward_support":
        base = "包装优先抓参考文里的现实触发点，以及人怎样用判断力、行动力或恢复力把眼前这一步接稳；不要写成单纯硬扛、求助技巧或统一自救模板。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "trust_boundary":
        base = "包装优先抓信任裂开的那一下、隐瞒带来的心里疙瘩，以及坦诚和说到做到怎样把关系重新托稳。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            base = "包装优先抓被看见、被读懂和一句追问带来的安稳感，不要写成谁回得更快、谁排得更前的关系排序。"
            return f"{specific_focus} {base}".strip() if specific_focus else base
        base = "包装优先抓回应顺序、表层互动和追问落差背后的真实分量，不要写成抽象关系道理。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "supportive_appreciation":
        base = "包装优先抓柔软被误读、却依然值得被珍惜这一层，不要只写成性格评价。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "relationship_aftercare":
        base = "包装优先抓争执后的空白、有没有人回来修复，不要写成泛吵架感悟。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "resilience_reconstruction":
        base = "包装优先抓命运重击、训练代价和不被定义，不要压成轻飘飘的励志鸡汤。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "emotional_engine_direct":
        base = "包装优先抓误认被点破、执念被松开的那一下，再给一个继续往前的落点。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "scene_first_progression":
        if normalized_opening:
            base = f"标题、导语和封面先沿着这句起笔往前走：{normalized_opening}。先把人带进现场，再把判断慢慢放出来。"
            return f"{specific_focus} {base}".strip() if specific_focus else base
        base = "标题、导语和封面先把人带进参考文自己的连续现场，再让判断从现场里自然浮出来。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if structure_mode == "pressure_interface_direct":
        base = "包装优先抓已经开始出代价的现实接口或身体提醒，再把回神点提出来。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    if normalized_opening:
        base = f"包装优先沿着上游最有抓力的起笔方式走：{normalized_opening}；不要只概括主题。"
        return f"{specific_focus} {base}".strip() if specific_focus else base
    base = "标题、导语和封面优先抓参考文自己的触发点、人物关系或核心物件，再落到这篇文章自己的正向出口。"
    return f"{specific_focus} {base}".strip() if specific_focus else base


def _normalize_strategy_contract_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value)
    for source, replacement in (
        ("这篇文章真正想讨论的是：", "核心主题："),
        ("这篇文章真正想谈的是：", "核心主题："),
        ("文章真正讨论的是：", "核心主题："),
    ):
        normalized = normalized.replace(source, replacement)
    return normalized.strip(" \n\t。；;，,")


_RESPONSIBILITY_SHELTER_CONTRACT_REPLACEMENTS = (
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
    ("没事，有我", "先稳住场面"),
    ("没事有我", "先稳住场面"),
    ("“我没事”", "先稳住场面"),
    ("我没事", "先稳住场面"),
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
    ("能扛", "能把事情接住"),
    ("强撑", "先把事情稳住"),
    ("或倒下", "或停下"),
    ("倒下", "停下"),
    ("沉默疲惫", "不张扬的责任感"),
    ("长期疲惫、委屈、想停下却不敢停的内在消耗", "现实责任和自己也需要被照顾之间的拉扯"),
    ("长期疲惫", "长时间不容易"),
    ("疲惫", "不容易"),
    ("委屈", "心里的不容易"),
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


def _sanitize_responsibility_shelter_contract_text(value: str) -> str:
    sanitized = _normalize_strategy_contract_text(value)
    for source, replacement in sorted(
        _RESPONSIBILITY_SHELTER_CONTRACT_REPLACEMENTS,
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        sanitized = sanitized.replace(source, replacement)
    return _normalize_strategy_contract_text(sanitized)


def _sanitize_responsibility_shelter_contract_list(values: list[str]) -> list[str]:
    return [_sanitize_responsibility_shelter_contract_text(value) for value in values]


def _sanitize_responsibility_shelter_analysis_contract(contract: AnalysisFirstContract) -> AnalysisFirstContract:
    return AnalysisFirstContract(
        theme=_sanitize_responsibility_shelter_contract_text(contract.theme),
        core_conflict=_sanitize_responsibility_shelter_contract_text(contract.core_conflict),
        emotional_exit=_sanitize_responsibility_shelter_contract_text(contract.emotional_exit),
        opening_pattern=_sanitize_responsibility_shelter_contract_text(contract.opening_pattern),
        do_not_turn_into=_sanitize_responsibility_shelter_contract_text(contract.do_not_turn_into),
    )


def _sanitize_responsibility_shelter_problem_brief(problem_brief: ProblemBriefItem) -> ProblemBriefItem:
    data = problem_brief.model_dump()
    text_fields = (
        "raw_goal",
        "clarified_problem",
        "observed_phenomenon",
        "writing_goal",
        "problem_explanation",
        "emotional_value_goal",
        "theme_axis",
        "anti_drift_axis",
        "target_reader_situation",
        "core_conflict",
        "feedback_entry",
        "problem_statement_markdown",
    )
    list_fields = ("unknowns", "constraints")
    for field in text_fields:
        data[field] = _sanitize_responsibility_shelter_contract_text(str(data.get(field) or ""))
    for field in list_fields:
        data[field] = _sanitize_responsibility_shelter_contract_list(list(data.get(field) or []))
    return ProblemBriefItem(**data)


def _sanitize_responsibility_shelter_benchmark(benchmark: BenchmarkReferenceItem) -> BenchmarkReferenceItem:
    data = benchmark.model_dump()
    for field in ("borrow_focus", "avoid_focus", "rationale"):
        data[field] = _sanitize_responsibility_shelter_contract_text(str(data.get(field) or ""))
    return BenchmarkReferenceItem(**data)


def _sanitize_responsibility_shelter_strategy_card(strategy_card: StrategyCardItem) -> StrategyCardItem:
    data = strategy_card.model_dump()
    text_fields = (
        "reader_situation",
        "point_of_view",
        "conflict_frame",
        "emotional_path",
        "hook_trigger",
        "progression_drive",
        "share_reason",
        "positive_direction",
        "quotable_line_goal",
        "packaging_focus",
        "packaging_hook",
        "realism_texture_goal",
        "opening_move",
        "body_shift",
        "ending_move",
        "benchmark_summary",
        "strategy_markdown",
    )
    list_fields = (
        "recomposition_recipe",
        "writing_texture_notes",
        "scene_anchor_requirements",
        "quotable_line_seeds",
        "expression_constraints",
        "divergence_axes",
        "execution_checklist",
    )
    for field in text_fields:
        data[field] = _sanitize_responsibility_shelter_contract_text(str(data.get(field) or ""))
    for field in list_fields:
        data[field] = _sanitize_responsibility_shelter_contract_list(list(data.get(field) or []))
    return StrategyCardItem(**data)


def _build_analysis_first_contract(
    *,
    reference_analysis_theme: str,
    reference_analysis_core_conflict: str,
    reference_analysis_emotional_exit: str,
    reference_analysis_opening_pattern: str,
    reference_analysis_do_not_turn_into: str,
) -> AnalysisFirstContract:
    return AnalysisFirstContract(
        theme=_normalize_strategy_contract_text(reference_analysis_theme),
        core_conflict=_normalize_strategy_contract_text(reference_analysis_core_conflict),
        emotional_exit=_normalize_strategy_contract_text(reference_analysis_emotional_exit),
        opening_pattern=_normalize_strategy_contract_text(reference_analysis_opening_pattern),
        do_not_turn_into=_normalize_strategy_contract_text(reference_analysis_do_not_turn_into),
    )


def _append_analysis_hint(current: str, addition: str) -> str:
    normalized_current = _normalize_strategy_contract_text(current)
    normalized_addition = _normalize_strategy_contract_text(addition)
    if not normalized_addition:
        return current
    if normalized_addition in normalized_current:
        return current
    rendered_addition = addition.strip()
    if rendered_addition and rendered_addition[-1] not in "。！？!?":
        rendered_addition = f"{rendered_addition}。"
    if not current.strip():
        return rendered_addition
    return f"{current}{rendered_addition}"


def _enrich_problem_explanation_with_analysis_contract(
    current: str,
    *,
    contract: AnalysisFirstContract,
) -> str:
    if not contract.core_conflict:
        return current
    return _append_analysis_hint(current, f"真正要拆开的，是{contract.core_conflict}")


def _enrich_point_of_view_with_analysis_contract(
    current: str,
    *,
    contract: AnalysisFirstContract,
) -> str:
    if not contract.core_conflict:
        return current
    return _append_analysis_hint(current, f"下笔时先围着这层矛盾推进：{contract.core_conflict}")


def _enrich_conflict_frame_with_analysis_contract(
    current: str,
    *,
    contract: AnalysisFirstContract,
) -> str:
    if not contract.core_conflict:
        return current
    return _append_analysis_hint(current, f"更具体地说，{contract.core_conflict}")


def _enrich_opening_move_with_analysis_contract(
    current: str,
    *,
    contract: AnalysisFirstContract,
) -> str:
    if not contract.opening_pattern:
        return current
    return _append_analysis_hint(current, f"优先沿着这篇真正的起笔方式重建入口：{contract.opening_pattern}")


def _enrich_body_shift_with_analysis_contract(
    current: str,
    *,
    contract: AnalysisFirstContract,
) -> str:
    if not contract.core_conflict:
        return current
    return _append_analysis_hint(current, f"中段优先把这层矛盾拆开：{contract.core_conflict}")


def _enrich_ending_move_with_analysis_contract(
    current: str,
    *,
    contract: AnalysisFirstContract,
) -> str:
    if not contract.emotional_exit:
        return current
    return _append_analysis_hint(current, f"最后把人送回：{contract.emotional_exit}")


def _enrich_packaging_focus_with_analysis_contract(
    current: str,
    *,
    contract: AnalysisFirstContract,
) -> str:
    if not contract.emotional_exit:
        return current
    return _append_analysis_hint(current, f"包装也要继续服务这个情绪出口：{contract.emotional_exit}")


def _build_theme_axis(
    *,
    structure_mode: str,
    reference_analysis_theme: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    normalized_theme = _normalize_strategy_contract_text(reference_analysis_theme)
    if normalized_theme:
        return normalized_theme

    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            return "主线是很多成年人为什么会先把父母、孩子、伴侣和家里的日子安排稳，以及这些认真托住日子的时刻后来怎样变成继续往前的底气。"
        if everyday_warmth_variant == "simple_happiness":
            return "主线是人为什么总把好日子押在更大的拥有上，后来又怎样被家人平安、知己仍在和热乎日常慢慢劝回来。"
        return "主线是人为什么总把更大的成就误认成更重要的东西，最后又怎样被日常陪伴和眼前拥有的部分慢慢托住。"
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            return "主线是人为什么一到阶段节点就容易先否定自己，后来又怎样把遗憾从自我定性里拆开，并被眼前生活和仍在身边的支撑慢慢托住。"
        return "主线是人为什么总想先把自己说服明白，最后才发现真正缺的不是答案，而是把心放回眼前生活的能力。"
    if structure_mode == "self_worth_rebuild":
        return "主线是人为什么总在关系里先把自己放轻、把边界和标准往后撤，后来又怎样重新尊重自己，让体面和分量慢慢回到自己身上。"
    if structure_mode == "self_reliance_inward_support":
        return "主线是人在想求助却看见别人也各自有难处时，怎样先恢复判断和行动，也在合适的时候开口、分担，把生活慢慢接回来。"
    if structure_mode == "trust_boundary":
        return "主线是信任为什么珍贵又脆弱：一次谎言或隐瞒会让心安裂开，而真正走得远的关系，靠坦诚、交代和日常里的说到做到重新托住。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "主线是轻互动为什么不等于真正的关心；真正让人踏实的，常常是有人愿意停下来读懂你、把你那句没说完的话接下去。"
        return "主线是表层回应为什么常被误认成在乎；顺序、追问和回头动作会比嘴上的在乎更早显出位置感。"
    if structure_mode == "supportive_appreciation":
        return "主线是柔软为什么总被误读，又为什么真正愿意包容、珍惜和接住这份柔软的人格外难得。"
    if structure_mode == "relationship_aftercare":
        return "主线不是争执本身，而是争执之后有没有人回来善后、接住失望，并把关系重新修回去。"
    if structure_mode == "resilience_reconstruction":
        return "主线是命运重击之后，一个人怎样在长期疼痛、重复训练和外界定义里继续重建自己。"
    if structure_mode == "emotional_engine_direct":
        return "主线是人为什么总把执念、遗憾或舍不得误认成非要抓住不放，后来又怎样把这段经历安放回自己的人生里。"
    if structure_mode == "scene_first_progression":
        return "主线要跟着参考文自己的现场变化走，后面的判断都要从人物、关系或处境里慢慢长出来。"
    if structure_mode == "pressure_interface_direct":
        return "主线是那些已经开始出代价的现实接口为什么总被往后推，以及一个人怎样重新把生活顺序调回来。"
    if structure_mode == "fragment_chain_observation":
        return "主线不是把道理讲圆，而是借几个现实接口把同一种误判、拖延或消耗慢慢看清。"
    return "主线要先守住参考文自己的现实和情绪重心，再把人带回一个更稳、更亮一点的落点。"


def _build_anti_drift_axis(
    *,
    structure_mode: str,
    reference_analysis_do_not_turn_into: str,
    inner_settlement_variant: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    normalized_forbidden = _normalize_strategy_contract_text(reference_analysis_do_not_turn_into)
    if normalized_forbidden:
        return normalized_forbidden

    if structure_mode == "everyday_warmth_return":
        return "不要漂成泛幸福定义、关系等待复盘或空泛知足感想。"
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            return "不要漂成失恋复盘、深夜自责诊断、泛心灵鸡汤、年中励志口号或只剩“看开点”的安慰稿。"
        return "不要漂成失恋回忆、深夜自责诊断、泛心灵鸡汤或只剩“看开点”的安慰稿。"
    if structure_mode == "self_worth_rebuild":
        return "不要漂成关系沟通技巧、狠话训诫、谁爱不爱你的判案文，或只会鼓励离开的泛爽文。"
    if structure_mode == "self_reliance_inward_support":
        return "不要漂成放大失落的控诉稿、泛负能量诊断或一套标准自助步骤。"
    if structure_mode == "trust_boundary":
        return "不要漂成回消息速度、点赞评论、谁更懂你、放下过去或查岗控制的关系稿；主线必须留在信任被隐瞒划出裂缝后，怎样靠坦诚和说到做到重建心安。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "不要漂成回复速度比较、关系排位、社交平台礼仪评判或“谁更在乎你”的定胜负稿。"
        return "不要漂成关系总论、情绪发泄稿或“他爱不爱你”的一句话判案。"
    if structure_mode == "supportive_appreciation":
        return "不要漂成性格测评、单向受委屈叙述或泛关系鸡汤。"
    if structure_mode == "relationship_aftercare":
        return "不要漂成抽象三观争论、单人内耗诊断或泛沟通技巧清单。"
    if structure_mode == "resilience_reconstruction":
        return "不要漂成苦难陈列、轻量自助提醒或排比式励志稿。"
    if structure_mode == "emotional_engine_direct":
        return "不要漂成纯怀旧、纯失恋止损或只剩大道理的感悟稿。"
    if structure_mode == "scene_first_progression":
        return "不要漂成空场景抒情、泛内耗诊断或只教人勇敢表达的技巧稿。"
    if structure_mode == "pressure_interface_direct":
        return "不要漂成关系修复、泛焦虑解释或只剩健康提醒口号。"
    if structure_mode == "fragment_chain_observation":
        return "不要漂成平均分论点、完整短篇故事或过度工整的教程壳。"
    return "不要漂成另一篇更顺手的泛情绪稿。"


def _has_stage_node_reference(*, topic_title: str, topic_angle: str, reference_body_markdown: str) -> bool:
    corpus = " ".join(part for part in (topic_title, topic_angle, reference_body_markdown) if part)
    return any(keyword in corpus for keyword in ("上半年", "下半年", "这半年", "年初", "阶段", "目标", "清单"))


def _build_scene_anchor_requirements(
    *,
    structure_mode: str,
    topic_title: str,
    topic_angle: str,
    reference_body_markdown: str,
    reference_fingerprint: ReferenceArticleFingerprint | None = None,
    response_priority_followup_variant: bool = False,
) -> list[str]:
    fingerprint_specific = _build_reference_specific_scene_requirements(
        reference_fingerprint or ReferenceArticleFingerprint()
    )
    if structure_mode == "everyday_warmth_return":
        base = [
            "前六段至少放进 1 个家里日常接口，比如晚饭、散步、回家、放学或灯还亮着这类回温动作。",
            "中后段至少保住 1 个陪伴动作接口，让珍贵不是抽象价值判断。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "inner_settlement":
        if _has_stage_node_reference(
            topic_title=topic_title,
            topic_angle=topic_angle,
            reference_body_markdown=reference_body_markdown,
        ):
            base = [
                "前六段至少放进 1 个阶段节点接口，比如翻到某个月、某张清单或某个没完成的计划。",
                "中后段至少保住 1 个日常回温接口，让回神不是空结论。",
            ]
            return merge_unique_lines(fingerprint_specific + base, [])
        base = [
            "前六段至少放进 1 个心没落稳的现实接口，不要直接讲道理。",
            "中后段至少保住 1 个日常回温接口，让回稳动作能被看见。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "self_worth_rebuild":
        base = [
            "前六段至少放进 1 个自己其实不想再配合、却还是顺手让步的现实接口。",
            "中后段至少保住 1 个边界重新立住或标准重新收回来的现实动作，不要只停在感受判断上。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "self_reliance_inward_support":
        base = [
            "前六段至少放进 1 个想求助却看见别人也各自承压的具体接口，让主题从真实处境里发生。",
            "中段至少保住 1 个恢复判断、继续行动或主动分担的现实动作，而不是只写感受。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "trust_boundary":
        base = [
            "前六段至少放进 1 个信任从放心到松动的现实接口，比如一句谎言、一次隐瞒、一个没有说清的细节。",
            "中后段至少保住 1 个坦诚、交代或说到做到的现实动作，让重建心安不是空泛保证。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            base = [
                "前六段至少放进 1 个轻互动接口，比如一句“我没事”、一张随手发的照片、一次评论或一句追问。",
                "前半篇至少保住 1 个被读懂或没被读懂的动作差别，让真正的关心从细节里自己长出来。",
            ]
            return merge_unique_lines(fingerprint_specific + base, [])
        base = [
            "前六段至少放进 1 个回应接口，比如消息、电话、点赞或等回复这类顺序落差。",
            "前半篇至少放进 1 个碎片时间接口，让时间分配自己把位置感写出来。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "supportive_appreciation":
        base = [
            "前六段至少放进 1 个柔软被误读的小接口，不要一上来就下性格判断。",
            "中后段至少保住 1 个被珍惜或没被珍惜的动作差别。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "relationship_aftercare":
        base = [
            "前六段至少放进 1 个争执后空掉的现场接口，比如沉默、冷掉、没人回来善后的那一下。",
            "中段至少保住 1 个回来修复或始终没回来修复的动作差别。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "resilience_reconstruction":
        base = [
            "前六段至少放进 1 个身体限制、治疗、训练或疼痛余波接口。",
            "中后段至少保住 1 个继续重建的现实动作，不要只留下励志判断。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "emotional_engine_direct":
        base = [
            "前半篇至少放进 1 个误判真正发生时的现实接口，不要只剩感悟。",
            "正文至少保住 1 个已经拥有却差点被忽略掉的现实抓手。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "scene_first_progression":
        base = [
            "前六段至少保住 1 个连续现场，让判断从现场里慢慢长出来。",
            "中段至少保住 1 个事后补救、动作残留或关系余波，不要很快跳成总论。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "pressure_interface_direct":
        base = [
            "前六段至少放进 1 个已经开始出代价的现实接口或身体提醒。",
            "中段至少保住 1 个被推迟的决定、检查或收手动作。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    if structure_mode == "fragment_chain_observation":
        base = [
            "前半篇至少并列 2 个现实接口，让同一种误判在不同处境里显形。",
            "中后段至少保住 1 个生活秩序或身体余波接口，别只剩观点。",
        ]
        return merge_unique_lines(fingerprint_specific + base, [])
    base = [
        "前六段至少放进 1 个现实接口，不要直接空降总判断。",
        "中后段至少保住 1 个动作残留或关系余波，让落点能被看见。",
    ]
    return merge_unique_lines(fingerprint_specific + base, [])


def _build_realism_texture_goal(
    *, structure_mode: str, reference_fingerprint: ReferenceArticleFingerprint | None = None
) -> str:
    specific_hint = _build_reference_specific_realism_hint(
        reference_fingerprint or ReferenceArticleFingerprint()
    )
    if structure_mode == "self_worth_rebuild":
        base = "前六段至少保住 2 个让步或降级接口、1 处动作残留和 1 处没讲满的停顿；不要连续两段都在替读者总结自爱道理。"
        return f"{base} {specific_hint}".strip() if specific_hint else base
    if structure_mode == "inner_settlement":
        base = "前六段至少保住 2 个现实接口、1 处动作残留和 1 处没讲满的停顿；如果是阶段节点题，前屏必须让某个时间节点、清单、计划或比较心先落地，不要连续两段都在替读者解释人生。"
        return f"{base} {specific_hint}".strip() if specific_hint else base
    if structure_mode == "trust_boundary":
        base = "前六段至少保住 2 个和信任有关的真实接口、1 处没说满的停顿和 1 个坦诚动作；不要连续两段都在解释信任道理，也不要写成查手机或审问。"
        return f"{base} {specific_hint}".strip() if specific_hint else base
    if structure_mode == "scene_first_progression":
        base = "前六段至少保住 2 个现场动作或动作余波，允许 1 处像真人写作时的停顿、改口或心里一沉，不要连续两段都在解释为什么。"
        return f"{base} {specific_hint}".strip() if specific_hint else base
    if structure_mode == "emotional_engine_direct":
        base = "即便偏观点推进，前六段也至少保住 2 个现实抓手、1 处动作残留和 1 处没讲满的停顿，不要通篇只剩感悟句。"
        return f"{base} {specific_hint}".strip() if specific_hint else base
    base = "前六段至少保住 2 个现实接口、1 处动作残留和 1 处没讲满的停顿；不要连续两段都在替读者解释人生。"
    return f"{base} {specific_hint}".strip() if specific_hint else base


def _build_quotable_line_seeds(
    *,
    structure_mode: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    reference_fingerprint: ReferenceArticleFingerprint | None = None,
    response_priority_followup_variant: bool = False,
) -> list[str]:
    specific_seeds = _build_reference_specific_quotable_seeds(
        reference_fingerprint or ReferenceArticleFingerprint()
    )
    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            base = [
                "把一个家托住的人，往往把累藏得最深",
                "你替家里挡住的风，会慢慢变成日子的踏实",
                "肩上有责任的人，心里也要留一盏灯",
            ]
            return merge_unique_lines(specific_seeds + base, [])
        base = ["幸福被误判的那一下", "普通日常重新有分量的那一下", "想回家的人话"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            base = ["阶段误判被认出来的那一下", "几项空着不等于白走的那一句", "把力气收回下一步生活的那一句"]
            return merge_unique_lines(specific_seeds + base, [])
        base = ["终于不再跟自己较劲的那一下", "心慢慢放平的那一下", "回到今天能过下去的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "self_worth_rebuild":
        base = ["原来一直在把自己放轻的那一下", "边界重新立住的那一下", "把分量收回自己身上的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "self_reliance_inward_support":
        base = ["不是不想开口，是每个人都有自己的那场雨", "先把自己扶稳，才有力气接住明天", "自救和求助都不丢人的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "trust_boundary":
        base = ["信任裂开时心里一沉的那一下", "坦诚把心安重新放回来的那一句", "说到做到比解释更有分量的那一下"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            base = ["一句轻描淡写的话被听懂的那一下", "有人愿意停下来多问一句的那一下", "原来真正的关心是可以被认出来的那一句"]
            return merge_unique_lines(specific_seeds + base, [])
        base = ["顺序显形的那一下", "时间给了谁的那一下", "把时间收回来的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "supportive_appreciation":
        base = ["柔软被误读的那一下", "被认真珍惜的那一下", "关系里值得牵紧的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "relationship_aftercare":
        base = ["吵完以后谁回来善后的那一下", "失望被接住或没被接住的那一下", "这段关系值不值得继续的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "resilience_reconstruction":
        base = ["疼痛和训练都没收走人的那一下", "不被定义的那一下", "继续重建的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "emotional_engine_direct":
        base = ["误认被点破的那一下", "终于肯放回过去的那一下", "带着所得继续往前的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "scene_first_progression":
        base = ["现场里突然认出来的那一下", "那句本来没说出口的话", "事后回想才明白的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "pressure_interface_direct":
        base = ["代价终于被看见的那一下", "该停下来却一直没停的那一下", "重新把顺序调回来的那一句"]
        return merge_unique_lines(specific_seeds + base, [])
    if structure_mode == "fragment_chain_observation":
        base = ["几个碎片终于串成同一种问题的那一下", "原来一直在垫付同一种代价的那一下"]
        return merge_unique_lines(specific_seeds + base, [])
    base = ["现实抓手压成一句人话的那一下", "回神或回稳的那一句"]
    return merge_unique_lines(specific_seeds + base, [])


def _build_packaging_hook(
    *,
    structure_mode: str,
    topic_title: str,
    topic_angle: str,
    reference_analysis_opening_pattern: str,
    reference_body_markdown: str,
    everyday_warmth_variant: str = "",
    reference_fingerprint: ReferenceArticleFingerprint | None = None,
    response_priority_followup_variant: bool = False,
) -> str:
    normalized_opening = _normalize_strategy_contract_text(reference_analysis_opening_pattern)
    specific_hook = _build_reference_specific_packaging_hook(
        reference_fingerprint or ReferenceArticleFingerprint()
    )
    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            base = "再把落点带回：原来这些认真多想的一步，最后都在把家里那点安稳托住。"
            return f"{specific_hook} {base}".strip() if specific_hook else base
        base = "先抓把幸福误认成更大目标的那一下，再带回饭桌、灯火、陪伴和已经拥有的回温。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "inner_settlement":
        if _has_stage_node_reference(
            topic_title=topic_title,
            topic_angle=topic_angle,
            reference_body_markdown=reference_body_markdown,
        ):
            base = "先抓阶段节点上的自我误判，再带回事与愿违未必是坏消息、眼前日子还值得继续过下去的回神点。"
            return f"{specific_hook} {base}".strip() if specific_hook else base
        base = "先抓那一下心一直没放下的接口，再带回慢慢住回今天的回稳点。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "self_worth_rebuild":
        base = "先抓一个人又顺手把自己放轻、把边界往后挪的现实接口，再带回她怎样把分寸和分量重新收回来。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "self_reliance_inward_support":
        base = "先抓参考文里的现实触发点，再带回人怎样用一个动作、判断或选择把眼前这一步接稳。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "trust_boundary":
        base = "先抓信任裂开的具体瞬间，再带回坦诚、交代和说到做到怎样让心安重新落下来。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            base = "先抓一句轻描淡写的话有没有被听懂，再带回真正让人踏实的，是有人愿意停下来理解你。"
            return f"{specific_hook} {base}".strip() if specific_hook else base
        base = "先抓一个回应顺序或碎片时间里的落差，再带回时间给了谁、位置就偏向谁。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "supportive_appreciation":
        base = "先抓柔软被误读的那一下，再带回真正值得珍惜和牵紧的人。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "relationship_aftercare":
        base = "先抓吵完以后空下来的那一下，再带回有没有人回来修复。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "resilience_reconstruction":
        base = "先抓命运重击、治疗或训练代价，再带回不被定义和继续重建。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "emotional_engine_direct":
        base = "先抓误认被点破的那一下，再带回放下以后还能继续往前的力气。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "scene_first_progression":
        if normalized_opening:
            base = f"先抓这个现场入口：{normalized_opening}，再把判断慢慢递出来。"
            return f"{specific_hook} {base}".strip() if specific_hook else base
        base = "先抓参考文自己的连续现场，再把判断从现场里慢慢递出来。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "pressure_interface_direct":
        base = "先抓一个已经开始出代价的现实接口或身体提醒，再带回顺序被重新看见。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    if structure_mode == "fragment_chain_observation":
        base = "先抓一个最能让人停住的现实碎片，再把几个接口串成同一种误判。"
        return f"{specific_hook} {base}".strip() if specific_hook else base
    base = "先抓参考文自己的触发点、人物关系或核心物件，再顺着这篇文章自己的主线往下推。"
    return f"{specific_hook} {base}".strip() if specific_hook else base


def _has_pressure_interface_topic(topic_angle: str) -> bool:
    normalized = topic_angle.strip()
    if not normalized:
        return False
    hard_hits = _count_keyword_hits(normalized, _PRESSURE_TOPIC_HARD_SIGNALS)
    body_hits = _count_keyword_hits(normalized, _PRESSURE_TOPIC_BODY_SIGNALS)
    interface_hits = _count_keyword_hits(normalized, _PRESSURE_TOPIC_INTERFACE_SIGNALS)
    consequence_hits = _count_keyword_hits(normalized, _PRESSURE_TOPIC_CONSEQUENCE_SIGNALS)
    return hard_hits >= 1 or (body_hits >= 1 and (interface_hits >= 1 or consequence_hits >= 1)) or (
        interface_hits >= 1 and consequence_hits >= 1
    )


def _uses_pressure_interface_mode(*, topic_angle: str, structure_mode: str = "") -> bool:
    if structure_mode:
        return structure_mode == "pressure_interface_direct"
    return _has_pressure_interface_topic(topic_angle)


def _has_pressure_interface_summary(reference_summary: str) -> bool:
    normalized = reference_summary.strip()
    if not normalized:
        return False
    pressure_keywords = (
        "身体代价",
        "身体提醒",
        "生活排序",
        "自我照料",
        "自我关照",
        "照顾好自己",
        "内耗",
        "耗尽",
        "疲惫",
        "体检",
        "报警",
    )
    relationship_negations = (
        "不是关系修复",
        "不是关系主线",
        "不在亲密关系沟通里打转",
        "不要写成冷战复合流程",
        "不是关系摊牌",
        "不是沟通修复",
    )
    return any(keyword in normalized for keyword in pressure_keywords) and any(
        phrase in normalized for phrase in relationship_negations
    )


def _has_pressure_interface_reference(reference_body_markdown: str) -> bool:
    normalized = reference_body_markdown.strip()
    if not normalized:
        return False
    hard_hits = _count_keyword_hits(normalized, _PRESSURE_REFERENCE_HARD_SIGNALS)
    soft_hits = _count_keyword_hits(normalized, _PRESSURE_REFERENCE_SOFT_SIGNALS)
    consequence_hits = _count_keyword_hits(normalized, _PRESSURE_REFERENCE_CONSEQUENCE_MARKERS)
    supportive_hits = _count_keyword_hits(normalized, _SUPPORTIVE_HEALTHY_BODY_MARKERS)
    if supportive_hits >= 2 and hard_hits == 0 and consequence_hits == 0:
        return False
    return hard_hits >= 2 or (hard_hits >= 1 and consequence_hits >= 1) or (
        hard_hits == 0 and soft_hits >= 3 and consequence_hits >= 2 and not _has_emotional_release_reference(normalized)
    )


def _has_emotional_release_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    keyword_hits = _count_keyword_hits(corpus, _EMOTIONAL_RELEASE_REFERENCE_KEYWORDS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    return keyword_hits >= 3 and hard_pressure_hits == 0


def _has_endings_acceptance_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    relationship_hits = _count_keyword_hits(
        corpus,
        (
            "关系结束",
            "离开",
            "离别",
            "过客",
            "聚散",
            "相遇",
            "感谢相遇",
            "不谈亏欠",
            "允许一切发生",
            "允许一切结束",
            "接纳离开",
            "接纳结束",
            "任务完成了",
            "退场",
            "并肩同行",
            "那一抹光亮",
            "留给你的温暖",
            "变成了你自己",
            "整理行囊",
            "拥抱下一场",
            "未知的山海",
            "更辽阔的自己",
        ),
    )
    release_hits = _count_keyword_hits(
        corpus,
        (
            "不再执着",
            "不再追问",
            "不再要结果",
            "坦然释怀",
            "允许一切发生",
            "允许一切结束",
            "接纳离开",
            "最好的祝福",
            "保存和内化",
            "价值的保存",
            "关系中留下的温暖",
            "把遗憾成全",
            "从容与爱意",
        ),
    )
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    aftercare_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_CONFLICT_KEYWORDS)
    return relationship_hits >= 4 and release_hits >= 2 and hard_pressure_hits == 0 and aftercare_hits == 0


def _has_everyday_warmth_return_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    achievement_hits = _count_keyword_hits(corpus, _EVERYDAY_WARMTH_RETURN_ACHIEVEMENT_KEYWORDS)
    daily_hits = _count_keyword_hits(corpus, _EVERYDAY_WARMTH_RETURN_DAILY_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _EVERYDAY_WARMTH_RETURN_THESIS_MARKERS)
    simple_happiness_hits = _count_keyword_hits(
        corpus,
        (
            "大富大贵",
            "简单快乐",
            "知己二三",
            "家人安康",
            "四季平安",
            "一家温暖",
            "知足最幸福",
        ),
    )
    responsibility_hits = _count_keyword_hits(corpus, _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_KEYWORDS)
    responsibility_marker_hits = _count_keyword_hits(corpus, _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_MARKERS)
    responsibility_strong_hits = _count_keyword_hits(corpus, _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_STRONG_ANCHORS)
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


def _has_supportive_appreciation_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    softness_hits = _count_keyword_hits(corpus, _SUPPORTIVE_APPRECIATION_SOFTNESS_KEYWORDS)
    cherish_hits = _count_keyword_hits(corpus, _SUPPORTIVE_APPRECIATION_CHERISH_KEYWORDS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    negative_aftercare_hits = _count_keyword_hits(corpus, _SUPPORTIVE_APPRECIATION_NEGATIVE_EXCLUSION_KEYWORDS)
    return softness_hits >= 3 and cherish_hits >= 1 and hard_pressure_hits == 0 and negative_aftercare_hits == 0


def _has_self_reliance_inward_support_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    support_hits = _count_keyword_hits(corpus, _SELF_RELIANCE_INWARD_SUPPORT_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _SELF_RELIANCE_INWARD_SUPPORT_THESIS_MARKERS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    relationship_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS)
    return (
        support_hits >= 5
        and thesis_hits >= 1
        and hard_pressure_hits == 0
        and relationship_hits <= 2
    ) or (
        support_hits >= 4
        and thesis_hits >= 2
        and hard_pressure_hits == 0
        and relationship_hits <= 2
    )


def _build_reference_summary_for_strategy(
    *,
    structure_mode: str,
    reference_summary: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
) -> str:
    if structure_mode == "supportive_appreciation":
        return (
            "参考文围绕一种常被误读的柔软展开，重点不是复用‘吃亏’‘耗空’或关系善后的旧判断，"
            "而是确认：那些明明拎得清、却仍愿意体谅、包容和先照顾别人感受的人，"
            "为什么并不软弱，反而最值得被认真珍惜。"
        )
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            return (
                "参考文围绕人在阶段节点上为什么会突然开始清算自己、又怎样把这份误判慢慢拆开展开，"
                "重点不是复用祝福、鸡汤或结果论，而是确认：很多没有圆满的地方，并不等于这段路白走了，"
                "真正要被重新看见的是过程里的支撑、积累和下一步还能继续过下去的生活。"
            )
        return (
            "参考文围绕人为什么总被外界牵着心走、又怎样把自己慢慢安顿回内在归处展开，"
            "重点不是复用名言、祝福或抚慰口吻，而是确认：很多时候最先需要被安放的，"
            "不是某个标准答案，而是那颗迟迟不肯松下来的心。"
        )
    if structure_mode == "everyday_warmth_return":
        if everyday_warmth_variant == "responsibility_shelter":
            return (
                "参考文围绕成年人为什么会先把家里的事理顺、把自己的辛苦往后放展开，"
                "重点不是复用‘幸福回归’或‘热饭灯光’的通用回温模板，"
                "而是确认：责任怎样让人多想一步，这些认真又怎样慢慢落进父母安心、孩子底气和一个家的踏实里。"
            )
        return (
            "参考文围绕成就叙事为什么会在某个阶段失重展开，重点不是复用某个家庭场景，"
            "而是确认：那些总被放轻的吃饭、回家、有人惦记和有人说话的日常，为什么会在慢下来以后重新显出分量。"
        )
    if _has_self_reliance_inward_support_reference(reference_summary):
        return (
            "参考文围绕成年人承压时怎样从慌乱回到判断、行动和恢复展开，"
            "重点不是复用关系表达或求助技巧，而是确认：人如何把眼前顺序理清、把能做的一步做实，"
            "并在这个过程中长出自我支撑、自我修复和自救自渡的力气。"
        )
    return reference_summary


def _has_relationship_aftercare_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    if _has_supportive_appreciation_reference(corpus):
        return False
    conflict_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_CONFLICT_KEYWORDS)
    repair_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_REPAIR_KEYWORDS)
    relationship_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_THESIS_MARKERS)
    vulnerability_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_VULNERABILITY_KEYWORDS)
    withdrawn_strong_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_WITHDRAWN_STRONG_SIGNALS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    classic_aftercare = (
        relationship_hits >= 1
        and conflict_hits >= 1
        and repair_hits >= 2
        and (thesis_hits >= 1 or conflict_hits >= 2)
    )
    withdrawn_aftercare = (
        relationship_hits >= 1
        and thesis_hits >= 1
        and vulnerability_hits >= 2
        and (conflict_hits >= 1 or repair_hits >= 1 or withdrawn_strong_hits >= 2)
    )
    return (
        (classic_aftercare or withdrawn_aftercare)
        and hard_pressure_hits == 0
    )


def _has_inner_settlement_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    calm_hits = _count_keyword_hits(corpus, _INNER_SETTLEMENT_REFERENCE_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _INNER_SETTLEMENT_THESIS_MARKERS)
    daily_hits = _count_keyword_hits(corpus, _INNER_SETTLEMENT_DAILY_GROUNDING_KEYWORDS)
    daily_return_hits = _count_keyword_hits(corpus, _INNER_SETTLEMENT_DAILY_RETURN_KEYWORDS)
    stage_restart_hits = _count_keyword_hits(corpus, _INNER_SETTLEMENT_STAGE_RESTART_KEYWORDS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    relationship_hits = _count_keyword_hits(corpus, _RELATIONSHIP_AFTERCARE_RELATIONSHIP_KEYWORDS)
    return (
        hard_pressure_hits == 0
        and relationship_hits <= 2
        and (
            (calm_hits >= 4 and thesis_hits >= 1 and daily_hits >= 1)
            or (calm_hits >= 6 and thesis_hits >= 1)
            or (
                stage_restart_hits >= 4
                and (
                    daily_return_hits >= 1
                    or stage_restart_hits >= 8
                )
            )
        )
    )


def _has_self_worth_rebuild_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    theme_hits = _count_keyword_hits(corpus, _SELF_WORTH_REBUILD_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _SELF_WORTH_REBUILD_THESIS_MARKERS)
    positive_hits = _count_keyword_hits(corpus, _SELF_WORTH_REBUILD_POSITIVE_MARKERS)
    exclusion_hits = _count_keyword_hits(corpus, _SELF_WORTH_REBUILD_EXCLUSION_KEYWORDS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    return (
        hard_pressure_hits == 0
        and exclusion_hits <= 2
        and (
            (theme_hits >= 5 and thesis_hits >= 1 and positive_hits >= 2)
            or (theme_hits >= 4 and thesis_hits >= 2 and positive_hits >= 1)
        )
    )


def _has_response_priority_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    time_hits = _count_keyword_hits(corpus, _RESPONSE_PRIORITY_TIME_KEYWORDS)
    priority_hits = _count_keyword_hits(corpus, _RESPONSE_PRIORITY_PRIORITY_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _RESPONSE_PRIORITY_THESIS_MARKERS)
    interaction_hits = _count_keyword_hits(corpus, _RESPONSE_PRIORITY_INTERACTION_KEYWORDS)
    followup_hits = _count_keyword_hits(corpus, _RESPONSE_PRIORITY_FOLLOWUP_KEYWORDS)
    care_hits = _count_keyword_hits(corpus, ("在意", "在乎", "关心", "注意力"))
    exclusion_hits = _count_keyword_hits(corpus, _RESPONSE_PRIORITY_RELATIONSHIP_EXCLUSION_KEYWORDS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    classic_branch = time_hits >= 3 and priority_hits >= 2 and thesis_hits >= 1
    followup_branch = interaction_hits >= 3 and followup_hits >= 3 and (care_hits >= 1 or priority_hits >= 1)
    return (
        (classic_branch or followup_branch)
        and exclusion_hits <= 2
        and hard_pressure_hits == 0
    )


def _has_trust_boundary_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    core_hits = _count_keyword_hits(corpus, _TRUST_BOUNDARY_CORE_KEYWORDS)
    breach_hits = _count_keyword_hits(corpus, _TRUST_BOUNDARY_BREACH_KEYWORDS)
    repair_hits = _count_keyword_hits(corpus, _TRUST_BOUNDARY_REPAIR_KEYWORDS)
    response_hits = _count_keyword_hits(corpus, _RESPONSE_PRIORITY_TIME_KEYWORDS + _RESPONSE_PRIORITY_PRIORITY_KEYWORDS)
    hard_pressure_hits = _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS)
    explicit_trust_contract = core_hits >= 2 and (breach_hits >= 2 or (breach_hits >= 1 and repair_hits >= 2))
    strong_breach_repair_contract = core_hits >= 1 and breach_hits >= 2 and repair_hits >= 2
    return hard_pressure_hits == 0 and response_hits <= 2 and (explicit_trust_contract or strong_breach_repair_contract)


def _uses_response_priority_followup_variant(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    followup_hits = _count_keyword_hits(corpus, _RESPONSE_PRIORITY_FOLLOWUP_KEYWORDS)
    interaction_hits = _count_keyword_hits(
        corpus,
        ("评论", "追问", "多问一句", "读懂", "没说完", "愿意停下来", "我没事", "我有点累", "注意力"),
    )
    care_hits = _count_keyword_hits(corpus, ("在意", "在乎", "关心", "理解", "珍惜"))
    classic_hits = _count_keyword_hits(
        corpus,
        (
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
        ),
    )
    return followup_hits >= 3 and interaction_hits >= 4 and care_hits >= 1 and (followup_hits + interaction_hits) >= classic_hits + 2


def _has_scene_first_progression_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    structure_hits = _count_keyword_hits(corpus, _SCENE_FIRST_PROGRESSION_STRUCTURE_KEYWORDS)
    progression_hits = _count_keyword_hits(corpus, _SCENE_FIRST_PROGRESSION_PROGRESS_KEYWORDS)
    return structure_hits >= 2 and progression_hits >= 1


def _looks_like_scene_first_progression_body(reference_body_markdown: str) -> bool:
    blocks = _extract_reference_blocks(reference_body_markdown)
    if len(blocks) < 3:
        return False

    opening_blocks = [_strip_markdown_label(block) for block in blocks[:3]]
    scene_like_blocks = 0
    abstract_thesis_hits = 0

    for index, block in enumerate(opening_blocks):
        if not block:
            continue
        time_hits = _count_keyword_hits(block, _SCENE_FIRST_PROGRESSION_BODY_TIME_MARKERS)
        action_hits = _count_keyword_hits(block, _SCENE_FIRST_PROGRESSION_BODY_ACTION_MARKERS)
        object_hits = _count_keyword_hits(block, _SCENE_FIRST_PROGRESSION_BODY_OBJECT_MARKERS)
        abstract_hits = _count_keyword_hits(block, _SCENE_FIRST_PROGRESSION_ABSTRACT_THESIS_MARKERS)

        if index == 0 and abstract_hits >= 1 and action_hits == 0 and object_hits == 0:
            return False

        if abstract_hits >= 1 and action_hits == 0 and object_hits == 0:
            abstract_thesis_hits += 1

        if (time_hits >= 1 and action_hits >= 1) or (action_hits >= 1 and object_hits >= 1):
            scene_like_blocks += 1

    return scene_like_blocks >= 2 and abstract_thesis_hits <= 1


def _has_resilience_reconstruction_reference(*parts: str) -> bool:
    corpus = " ".join(part.strip() for part in parts if part and part.strip())
    if not corpus:
        return False
    adversity_hits = _count_keyword_hits(corpus, _RESILIENCE_RECONSTRUCTION_ADVERSITY_KEYWORDS)
    training_hits = _count_keyword_hits(corpus, _RESILIENCE_RECONSTRUCTION_TRAINING_KEYWORDS)
    identity_hits = _count_keyword_hits(corpus, _RESILIENCE_RECONSTRUCTION_IDENTITY_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _RESILIENCE_RECONSTRUCTION_THESIS_MARKERS)
    return adversity_hits >= 2 and training_hits >= 2 and (identity_hits >= 1 or thesis_hits >= 1)


def _uses_broad_emotional_release_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    if structure_mode != "emotional_engine_direct":
        return False
    corpus = " ".join(part.strip() for part in (topic_title, topic_angle) if part and part.strip())
    if not corpus:
        return False
    if _count_keyword_hits(corpus, _PRESSURE_REFERENCE_HARD_SIGNALS) > 0:
        return False
    if any(marker in corpus for marker in ("边界", "开口", "修复", "冷战", "复合", "关系缓回来")):
        return False
    if _has_emotional_release_reference(corpus):
        return True
    if _has_endings_acceptance_reference(corpus):
        return True
    keyword_hits = _count_keyword_hits(corpus, _BROAD_EMOTIONAL_RELEASE_STRATEGY_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _BROAD_EMOTIONAL_RELEASE_THESIS_MARKERS)
    return keyword_hits >= 2 and thesis_hits >= 1


def _uses_self_reliance_inward_support_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    if structure_mode == "self_reliance_inward_support":
        return True
    if structure_mode != "emotional_engine_direct":
        return False
    corpus = " ".join(part.strip() for part in (topic_title, topic_angle) if part and part.strip())
    if not corpus:
        return False
    support_hits = _count_keyword_hits(corpus, _SELF_RELIANCE_INWARD_SUPPORT_KEYWORDS)
    thesis_hits = _count_keyword_hits(corpus, _SELF_RELIANCE_INWARD_SUPPORT_THESIS_MARKERS)
    return support_hits >= 3 and thesis_hits >= 1


def _uses_self_worth_rebuild_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    if structure_mode == "self_worth_rebuild":
        return True
    if structure_mode != "emotional_engine_direct":
        return False
    return _has_self_worth_rebuild_reference(topic_title, topic_angle)


def _uses_everyday_warmth_return_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return _is_everyday_warmth_family_mode(structure_mode)


def _uses_inner_settlement_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return structure_mode == "inner_settlement"


def _uses_response_priority_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return structure_mode == "response_priority"


def _uses_trust_boundary_mode(*, topic_title: str = "", topic_angle: str = "", structure_mode: str = "") -> bool:
    if structure_mode == "trust_boundary":
        return True
    if structure_mode != "emotional_engine_direct":
        return False
    return _has_trust_boundary_reference(topic_title, topic_angle)


def _uses_supportive_appreciation_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return structure_mode == "supportive_appreciation"


def _uses_relationship_aftercare_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return structure_mode == "relationship_aftercare"


def _uses_resilience_reconstruction_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return structure_mode == "resilience_reconstruction"


def _uses_scene_first_progression_mode(*, topic_title: str = "", topic_angle: str, structure_mode: str = "") -> bool:
    return structure_mode == "scene_first_progression"


def _resolve_emotional_release_variant(*, topic_title: str = "", topic_angle: str = "", context_text: str = "") -> str:
    normalized = re.sub(r"\s+", "", " ".join(part for part in (topic_title, topic_angle, context_text) if part))
    if any(
        keyword in normalized
        for keyword in (
            "感谢相遇",
            "不谈亏欠",
            "允许一切发生",
            "允许一切结束",
            "接纳离开",
            "接纳结束",
            "关系结束",
            "聚散终有时",
            "过客",
            "最好的祝福",
            "相遇意义",
            "内在消化",
            "变成了你自己",
            "整理行囊",
            "未知的山海",
            "完整定义",
            "追讨完整定义",
        )
    ):
        return "endings_acceptance"
    if any(keyword in normalized for keyword in ("要是他还在", "还在就好了", "回潮", "未完成", "没收尾")):
        return "memory_reflux"
    if any(keyword in normalized for keyword in ("幸福", "放下", "放手", "强求", "不再强求", "知足")):
        return "happiness_release"
    return "generic"


def _build_emotional_release_profile(*, variant: str) -> dict[str, str]:
    profile = {
        "reader_situation": "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人",
        "core_conflict": "真正把人困住的，不是没有答案，而是总把舍不得放手误认成还有希望。",
        "observed_phenomenon": "很多人不是看不见自己已经被拖累，而是总把还没停下误认成还来得及，于是越消耗越不肯松手。",
        "normalized_topic_angle": "从人为什么总在得不到的东西上反复拉扯切入，重点写人怎样把继续投入误认成更接近圆满，又怎样慢慢把心力收回来。",
        "writing_goal": "把人为什么总会把不肯停下误认成认真讲清楚，也让读者看见，停下来不是认输，而是把心力慢慢收回自己手里。",
        "clarified_problem": "关键不在于人人都懂却做不到的道理，而在于很多人明明已经很累了，还是会把不甘心、投入感和希望错当成继续消耗自己的理由。",
        "feedback_entry": "总在得不到的东西上反复拉扯的人会先认出自己的处境，也会意识到自己不是离幸福太远，而是一直把不肯停下误认成更接近幸福。",
        "problem_explanation": "核心要拆开的，是为什么人明明已经被拖得很累了，还是会把继续投入误认成更接近圆满。",
        "point_of_view": "不急着讲知足、放下或清醒的大道理，先把人为什么明明已经很累，却还是觉得自己不能停讲清楚。",
        "conflict_frame": "真正把人困住的，不是没有答案，而是总把舍不得放手误认成还有希望。",
        "emotional_path": "先认出自己一直在和得不到的东西拉扯，再看为什么人总要等到透支之后才愿意停下。",
        "opening_move": "开头不要整段生活场景冷启动，先用一句会让人停一下的误认判断把读者拉进来；需要细节时，只留一个能挂住“继续投入”或“不肯松手”的小接口。",
        "body_shift": "中段先拆情绪发动机：人为什么会把继续投入误认成还有希望，又为什么总要等到透支之后才看见已经拥有的部分。",
        "ending_move": "结尾给读者一个明确的价值赦免和现实答案：停下来不是失去，是把心力收回来。",
        "benchmark_summary": "只借原文对应的情绪发动机和价值转向，不借原文标题骨架、首段场景、推进顺序和结尾动作。",
        "expression_constraint": "不要把情绪释放稿改写成身体告警、自我耗空、先把自己排回前面或泛成长诊断文。",
    }
    if variant == "memory_reflux":
        profile.update(
            {
                "reader_situation": "明明已经往前走了，心里却总会被没收尾的旧关系拉回去的人",
                "core_conflict": "真正拖住人的，未必是过去本身还在发生，而是心里一直替那段回不去的东西留着位置。",
                "observed_phenomenon": "很多旧关系不是天天想起，却会在某个小瞬间突然回潮，让人又回到那句没说完的话和那个没被接住的位置上。",
                "normalized_topic_angle": "从那些会把旧念头重新勾回来的现实接口切入，重点写人为什么总会在过去和如果当初里停一下，又怎样把遗憾慢慢安放回过去。",
                "writing_goal": "把人为什么总会被旧事和当初拉回去讲清楚，也让读者看见，放下不是背叛过去，而是让今天和以后重新有位置。",
                "clarified_problem": "关键不在于人该不该赶快忘掉，而在于很多旧关系明明已经结束，还是会在某个当下重新回潮，占住今天的心力。",
                "feedback_entry": "明明已经往前走了、心里却还会被旧事拉回去的人会先认出自己的处境，也会知道放下不是逼自己忘掉，而是把过去放回过去，让今天继续往前。",
                "problem_explanation": "核心要拆开的，是为什么人明明知道很多旧事已经回不去，还是会在某个物件、某句话或某个瞬间里再次被拉回当时；也要落到把遗憾安放好，今天才会重新腾出位置。",
                "point_of_view": "不急着催人忘掉，先把为什么总会被过去拉回去讲清楚，再把读者带回今天还能继续发生的生活。",
                "conflict_frame": "真正拖住人的，未必是过去本身还在发生，而是心里一直替那段回不去的东西留着位置。",
                "emotional_path": "先认出旧事为什么总会在不经意时被勾回来，再看遗憾怎样从一直占心，慢慢变成可以被收好的过去。",
                "opening_move": "开头先落一个会把旧念头勾回来的现实接口：旧物、旧话、旧地方、一次擦肩，或一句突然想起的话。不要先讲看开，更不要写成立刻翻篇的励志口号。",
                "body_shift": "中段先拆人为什么明知回不去，还会在“如果当初”里停一下；再写遗憾怎样从一直占心，慢慢变成可以被收好的过去，让今天和以后重新腾出位置。",
                "ending_move": "结尾回到一个不再反复回头、而是把注意力交还给今天的小动作，不写空泛看开，也不写强行振作。",
            }
        )
    elif variant == "endings_acceptance":
        profile.update(
            {
                "reader_situation": "明知一段关系已经结束，却还没学会把那段相遇安放回心里的人",
                "core_conflict": "真正让人迟迟放不下的，常常不是离开本身，而是还没承认：有些关系的意义，本来就不靠走到最后来证明。",
                "observed_phenomenon": "很多人并不是还想回头，而是舍不得把一段真心只算成失去，于是一直停在遗憾里，忘了相遇留下来的温暖和改变其实已经成为自己的一部分。",
                "normalized_topic_angle": "从人为什么总把关系结束误认成全盘落空切入，重点写有些相遇本就有阶段，它留下来的温暖、眼界和成长怎样慢慢留在一个人身上，让人带着感谢继续往前。",
                "writing_goal": "把人为什么会把结束误认成白费讲清楚，也让读者看见，真正的释怀不是否认疼痛，而是承认相遇真实、收好留下来的温暖，然后继续往前走。",
                "clarified_problem": "关键不在于关系结束以后谁更亏、谁更错，而在于很多人一面对离开，就下意识把整段相遇都算成白费。",
                "feedback_entry": "经历过关系结束、心里还舍不得把那段相遇放回过去的人，会先认出“原来我难过的不只是失去”，也会慢慢松开那种非得等结果来证明自己没有爱错的执拗。",
                "problem_explanation": "核心要拆开的，是为什么人总把没走到最后理解成白费；也要落到当你看见那段相遇已经在你身上留下温暖和改变，离开就不再只剩亏欠感。",
                "point_of_view": "不急着催人忘掉，先把为什么我们总想用结果给一段相遇定价讲清楚，再把读者带回那段关系真正留下来的东西上。",
                "conflict_frame": "真正让人迟迟放不下的，往往不是离开本身，而是你还没承认：有些关系的意义，本来就不靠走到最后来证明。",
                "emotional_path": "先认出人为什么会把结束理解成白费，再看相遇里留下来的温暖、眼界和自我认识，怎样慢慢替代那个必须有结果的执念。",
                "opening_move": "开头先落一个离开以后仍会轻轻停一下的现实接口：一句旧话、一个熟悉地方，或一瞬间想起当初被照顾过的细节。不要先写身体失序，也不要先把重心压在追交代和翻旧账上。",
                "body_shift": "中段先拆人为什么总把结束理解成亏欠、把没走到最后理解成全盘落空，接着写那段相遇留下来的温暖、边界和成长，怎样一点点让人从遗憾里长出从容。",
                "ending_move": "结尾回到一个把感谢收好、把关系放回过去、把自己交还给今天的小动作，不写强行振作，也不写万能感恩。",
                "expression_constraint": "不要把关系收尾稿改写成生活失序、自我照料补课、体检改期或把自己排回前面的诊断文，也不要把主线写成旧账清算和追交代诊断；主线必须留在接纳结束、保存相遇意义和继续往前。",
            }
        )
    return profile


def _build_self_worth_rebuild_profile() -> dict[str, str]:
    return {
        "reader_situation": "总把体谅、迁就和退让走在自己前面，后来才发现自己在关系里越站越靠后的人",
        "core_conflict": "越怕失去、越急着证明自己值得被爱，越容易先把边界、标准和体面一点点让出去。",
        "observed_phenomenon": "很多人不是不知道自己委屈了，而是总把将就、示好和先退一步误认成感情会更顺，于是越想被珍惜，越先把自己放轻。",
        "normalized_topic_angle": "从人为什么总在关系里先把自己往后放切入，重点写边界一退再退、位置感越来越轻，怎样让一个人越来越容易被随便对待；也写她怎样把精力收回来，重新尊重自己，让日子慢慢变稳、变体面。",
        "writing_goal": "把人为什么总会把迁就误认成爱、把退让误认成关系会更顺讲清楚，也让读者看见，边界、标准和尊重可以一点点回到自己这边。",
        "clarified_problem": "关键要写出来的是，很多人明明已经在将就里受委屈了，还是会下意识把问题先归到自己不够好、不够懂事或不够值得。",
        "feedback_entry": "总在委屈里迁就、总把别人排在自己前面的人会先认出自己的处境，也会慢慢看到，很多轻慢常常从自己一次次把边界、标准和体面让出去开始。",
        "problem_explanation": "核心要拆开的，是为什么人明明已经在将就、示好和降低标准里一点点受伤，还是会继续把自己往后放；也要落到当一个人开始尊重自己、守住边界，很多关系的轻慢才会真正停下来。",
        "point_of_view": "不急着把文章写成识人清单或狠话宣言，先把一个人为什么会一路迁就、一路退让讲清楚，再把尊重自己和重新立住边界这件事慢慢接回来。",
        "conflict_frame": "越怕失去、越急着证明自己值得被爱，越容易先把边界、标准和体面一点点让出去。",
        "emotional_path": "先认出那些总把自己往后放的时刻，再看边界怎样在一次次将就里慢慢变薄，最后把尊重和分量重新收回自己这边。",
        "opening_move": "开头先落一个自己其实并不舒服、却还是顺手说了“都可以”“算了”“我没事”的现实接口；不要写消息打了又删、解释说不出口，也不要先把第一屏抬成关系沟通道理。",
        "body_shift": "中段先拆一个人为什么总把迁就误认成懂事、把示好误认成在乎，再写边界、标准和体面是怎样在一次次退让里被放低；后半程把判断落回尊重自己、守住边界和重新把自己放回前面。",
        "ending_move": "结尾回到边界重新立住、精力终于收回自己手里，不要停在控诉、翻旧账或谁更辜负谁。",
        "benchmark_summary": "只借原文对自我价值、边界和标准的判断路径，不借原文的提醒句骨架、关系沟通壳子或界面细节。",
        "expression_constraint": "不要把自我价值重建稿写成消息打了又删、越想解释越说不出口、谁先回头沟通或争吵后善后的关系表达稿。",
    }


def _resolve_scene_first_progression_variant(*, topic_title: str = "", topic_angle: str = "", context_text: str = "") -> str:
    normalized = re.sub(r"\s+", "", " ".join(part for part in (topic_title, topic_angle, context_text) if part))
    if any(keyword in normalized for keyword in _SCENE_FIRST_OFFICE_KEYWORDS):
        return "office"
    if any(keyword in normalized for keyword in _SCENE_FIRST_HOUSEHOLD_KEYWORDS):
        return "household"
    if any(keyword in normalized for keyword in _SCENE_FIRST_RELATIONSHIP_KEYWORDS):
        return "relationship"
    return "generic"


def _build_scene_first_progression_profile(*, variant: str) -> dict[str, str]:
    profile = {
        "reader_situation": "总在那个该开口的现场里，先把更重要的话压回去的人",
        "core_conflict": "明明感觉到了变化，也知道有句话该问清楚，可一回到那个具体现场里，人还是会先把更重要的话压回去，后来只能靠回放和猜测补那段空白。",
        "observed_phenomenon": "很多关系不是没有问题，而是每次走到那个该问清楚、该确认、该靠近的现场里，人都会先把更重要的话压回去，转身后再一个人反复回想。",
        "normalized_topic_angle": "从那个原本可以问清楚、确认或靠近的现场切入，重点写人为什么总把更重要的话留到转身以后，最后只剩自己补那段空白。",
        "writing_goal": "把人为什么总在该开口的现场里先把更重要的话压回去讲清楚，也让读者看见，一次次让位是怎样慢慢改写位置感和关系里的在场感。",
        "clarified_problem": "关键不在于一个人会不会沟通，而在于很多人一回到那个该开口的现场里，就先把更重要的话压回去；也要让读者看见，一次次让位为什么会慢慢改写位置感和关系里的在场感。",
        "feedback_entry": "总在那个该开口的现场里，先把更重要的话压回去的人会先认出自己的处境，也会认出，很多关系变远并不是突然没了答案，而是那个该开口的现场一次次被自己让过去了。",
        "problem_explanation": "核心要拆开的，是为什么人明明已经感觉到了变化，还是会在那个该开口的现场里先把更重要的话压回去；也要落到一次次让位以后，位置感和关系里的在场感会一起变淡。",
        "point_of_view": "不急着给关系道理或沟通答案，先把那句为什么总在现场里被压回去讲清楚。",
        "conflict_frame": "真正把关系拉远的，常常不是某一次翻脸，而是每次走到那个该问清楚的现场里，人都先把更重要的话让过去。",
        "emotional_path": "先认出那句话为什么总在现场里被压回去，再看一次次让位是怎样把靠近的机会、位置感和关系里的在场感一起往后推。",
        "hook_trigger": "明明就差一句，话到嘴边时，人还是先沉默了。",
        "progression_drive": "那句没说出口的话，当场只是停了一下，后来却慢慢变成了两个人之间的空白。",
        "share_reason": "它会让人认出，很多走远不是突然发生的，而是从一次次先算了开始的。",
        "packaging_hook": "你明明感觉到了变化，却还是把那句话留到了转身以后。很多关系，也就是从这里慢慢变远的。",
        "opening_move": "开头先落那个原本可以问一句、确认一下，却还是被气氛、时间或体面顺过去的现场，不要先抽象讲关系道理。",
        "body_shift": "中段先拆那句话为什么在当场没问出口，再写转身以后补台词、补解释、自己反复回想这套动作怎样把关系里的在场感慢慢耗薄。",
        "ending_move": "结尾回到一个还没完全说出口、却终于不再整段咽回去的小动作，不要写成万能关系鸡汤或成熟沟通清单。",
        "benchmark_borrow_focus": "原文连续现场里的动作链 / 那句话怎样在现场被压后 / 判断怎样从当场犹豫里慢慢长出来",
        "benchmark_summary": "只借原文里连续现场、话被压回去的节点和判断慢慢长出来的顺序，不借原文标题、场景物件和结尾动作。",
        "expression_constraint": "不要把场景优先稿写成泛内耗、单人稳情绪或勇敢发声技巧稿。",
    }
    if variant == "office":
        profile.update(
            {
                "reader_situation": "总在会议上先把关键意见、边界或需求压回去，散会后再一个人补救的人",
                "core_conflict": "明明看见了排期、协作或边界上的问题，可一回到会议室和当场顺序里，人就先把更重要的话压回去，事后又把补救和代价一起揽回自己身上。",
                "observed_phenomenon": "很多人不是没有判断，而是在会议室、排期和协作现场里，一次次先替气氛和秩序让路，等散会后才一个人补那句没说出口的话。",
                "normalized_topic_angle": "从会议现场里那句想说又咽回去的话切入，重点写人为什么总在会上先替气氛和秩序让路，事后又把需求和补救一起揽回自己身上。",
                "writing_goal": "把人为什么总在会上先把关键意见、边界和需求压回去讲清楚，也让读者看见，事后补救为什么会慢慢把位置感和协作里的分量一起让出去。",
                "clarified_problem": "关键不在于一个人会不会发声，而在于很多人一回到会议室和协作现场里，就先把那句更重要的话压回去；也要让读者看见，事后补救为什么会慢慢把位置感和需求表达一起让出去。",
                "feedback_entry": "总在会议上先把关键意见、边界或需求压回去，散会后再一个人补救的人会先认出自己的处境，也会认出，很多协作里的失衡不是从任务太多开始的，而是从那句该在会上说出口的话被你一次次留到散会后开始的。",
                "problem_explanation": "核心要拆开的，是为什么人明明已经看见了排期、协作和边界上的问题，还是会在会议室里先把更重要的话压回去；也要落到一次次散会后补救，会慢慢把位置感和需求表达一起让出去。",
                "point_of_view": "不急着讲职场沟通技巧，先把一句话为什么总在会议室里被咽回去讲清楚。",
                "conflict_frame": "真正让人慢慢失去位置感的，常常不是不会做事，而是每次一到会议室和协作现场，就先把那句更重要的话留到散会后。",
                "emotional_path": "先认出那句话为什么总在会议室里被压回去，再看散会后补邮件、补解释和自己兜底，怎样把位置感和需求表达一起往后挪。",
                "hook_trigger": "会还没散，你已经把那句更重要的话咽回去了。",
                "progression_drive": "那句没说出口的话，先在会上被压回去，后来又在散会后把人往后推了一点。",
                "share_reason": "它会让很多总在会上先点头、散会后再补救的人，一下认出自己到底卡在了哪里。",
                "packaging_hook": "会还没散，你已经开始替那句没说出口的话收尾了。真正让人难受的，不只这一次沉默，而是你慢慢不再觉得自己该开口。",
                "opening_move": "开头先落一个会议还没结束、那句话却已经被删掉或咽回去的瞬间，不要先讲职场沟通道理，也不要把问题写成泛内耗。",
                "body_shift": "中段先拆那句话为什么在当场没说出口，再写散会后补邮件、补解释、自己兜底这套动作怎样把需求表达训练得越来越晚。",
                "ending_move": "结尾回到一个还没说满、却终于留在会议现场里的事实接口：时间不够、优先级冲突、需要协作，不要写成勇敢发声清单或自我打鸡血。",
                "benchmark_borrow_focus": "原文连续会议现场里的动作链 / 那句话怎样在会上被压后 / 判断怎样从会议前后慢慢长出来",
                "benchmark_summary": "只借原文里会议前后那条连续现场、话被压回去的节点和判断长出来的顺序，不借原文标题、会议话术和散会后补救动作。",
            }
        )
    elif variant == "household":
        profile.update(
            {
                "reader_situation": "总在家里那个该说清楚的时刻，把更重要的话又往后放的人",
                "core_conflict": "明明知道家里有件事该说清楚，可一回到那张餐桌、那道门口或那个夜里，人就先把更重要的话往后放，后来只能靠沉默和日常顺过去。",
                "observed_phenomenon": "很多家里的卡住不是没人察觉，而是每次走到那个该说清楚的时刻，人都会先把更重要的话往后放，接着让日常把它顺过去。",
                "normalized_topic_angle": "从家里那个原本该说清楚、却又被日常顺过去的时刻切入，重点写人为什么总把更重要的话留到后来，最后把沉默也过成了秩序。",
                "writing_goal": "把人为什么总在家里那个该说清楚的时刻先把更重要的话往后放讲清楚，也让读者看见，日常顺过去以后，沉默是怎样慢慢改写亲近感和位置感的。",
                "clarified_problem": "关键不在于家里有没有那件事，而在于很多人一回到那个熟悉现场里，就先把更重要的话往后放；也要让读者看见，日常把它顺过去以后，沉默会怎样慢慢改写亲近感和位置感。",
                "feedback_entry": "总在家里那个该说清楚的时刻，把更重要的话又往后放的人会先认出自己的处境，也会认出，很多沉默不是没机会说，而是太熟悉先把日子过下去，再把自己往后放。",
                "problem_explanation": "核心要拆开的，是为什么人明明知道家里那件事该说清楚，还是会在那个熟悉现场里先把更重要的话往后放；也要落到日常顺过去以后，沉默会慢慢变成新的秩序。",
                "point_of_view": "不急着讲家庭沟通道理，先把那句话为什么总在家里被顺过去讲清楚。",
                "conflict_frame": "真正把亲近感拖薄的，常常不是一件大事，而是每次走到那个该说清楚的时刻，人都先把更重要的话让给了日常秩序。",
                "emotional_path": "先认出那句话为什么总在家里被往后放，再看一次次顺过去是怎样把亲近感、位置感和表达欲一起磨薄。",
                "hook_trigger": "饭桌边明明该说清楚了，你还是先把那句话顺回了日常。",
                "progression_drive": "那句没说出口的话，先被一顿饭和一句改天再说带过去，后来就慢慢成了家里的沉默。",
                "share_reason": "它会让很多总想等气氛更好一点再开口的人，认出日常是怎么把沉默坐实的。",
                "packaging_hook": "那件事明明该在家里说清楚，却又被顺进了吃饭、收拾和明天再说。沉默久了，亲近感也会跟着往后退。",
                "opening_move": "开头先落一个家里已经很熟，却还是把更重要的话顺过去的瞬间，不要先讲家庭和解道理。",
                "body_shift": "中段先拆那句话为什么在当场没说出来，再写饭桌、门口、夜里和第二天清晨这些顺过去的动作怎样把沉默慢慢坐实。",
                "ending_move": "结尾回到一个还没完全说出口、却终于不再被日常整段顺过去的小动作，不要写成和解鸡汤或家庭关系标准答案。",
                "benchmark_borrow_focus": "原文家庭现场里的动作链 / 那句话怎样在家里被顺过去 / 判断怎样从日常停顿里慢慢长出来",
                "benchmark_summary": "只借原文里家中现场、话被往后放的节点和判断长出来的顺序，不借原文标题、家庭物件和结尾动作。",
            }
        )
    return profile


def _build_supportive_appreciation_profile() -> dict[str, str]:
    return {
        "reader_situation": "总在体谅别人、包容别人，却常被误读成太好说话的人",
        "core_conflict": "真正容易被错过的，不是这样的人吃了点亏，而是很多人把这份明明拎得清、却还是愿意温柔待人的珍贵，当成了理所当然。",
        "observed_phenomenon": "很多人并不是不懂分寸，只是心里明白归明白，还是会先照顾别人感受、先把争辩和计较放下来；也正因为这样，这份柔软反而最容易被误解。",
        "normalized_topic_angle": "从人为什么总把心软误认成好说话切入，重点写那些明明拎得清、却还是愿意体谅和包容别人的人，为什么最值得被认真珍惜。",
        "writing_goal": "把心软为什么不是傻、包容为什么不是没底线讲清楚，也让读者看见，真正稀缺的从来不是会说漂亮话的人，而是明明拎得清还愿意温柔待人的人。",
        "clarified_problem": "关键不在于心软的人吃了多少亏，而在于很多人会把这种明明拎得清、却仍愿意体谅和包容别人的柔软，误读成软弱和理所当然。",
        "feedback_entry": "总在体谅别人、包容别人，却常被误读成太好说话的人会先认出“原来我不是太傻，只是一直把感情放得很重”；而读到这篇的人，也会更知道该怎样认真回应、珍惜和善待这样的人。",
        "problem_explanation": "核心要拆开的，是为什么柔软常常会被误读成软弱，也要落到那些明明拎得清、却还是愿意体谅和包容别人的人，反而最值得被认真珍惜。",
        "point_of_view": "不急着劝人变硬一点，先把柔软为什么常被误读、又为什么其实最难得讲清楚。",
        "conflict_frame": "真正可惜的，不是心软的人吃了点亏，而是很多人把这份明明拎得清、却还是愿意体谅和包容的珍贵，当成了理所当然。",
        "emotional_path": "先认出心软不是傻，而是明明拎得清还愿意在乎；再看这份柔软为什么总被误读，最后落到这样的人为什么本来就值得被认真珍惜和回应。",
        "opening_move": "开头先落一个她顺手照顾别人、把场面放软、把分寸留出来的小接口，让那份柔软先被读者看见，不要急着先写她受了多大委屈。",
        "body_shift": "中段先拆柔软为什么常被误读成好说话，再写这种明明拎得清还愿意体谅和包容的分量，最后把真正值得珍惜和认真回应的地方落出来。",
        "ending_move": "结尾回到一次认真回应、牵紧或者终于没有把这份柔软当成理所当然的轻动作上，让人感觉温柔被看见了，也被认真放在心上。",
        "benchmark_borrow_focus": "原文对柔软人格的重新命名 / 明明拎得清却仍愿意体谅包容的分量 / 结尾落回珍惜与善待的方向",
        "benchmark_summary": "只借原文里柔软被正名、被误读又被重新看见的主线，不借原文标题骨架、现成判断句和结尾口号。",
        "expression_constraint": "不要把柔软珍惜稿写成自我耗空、身体告警、争吵后善后或“先把自己排回前面”的泛成长结论。",
    }


def _resolve_inner_settlement_variant(*, topic_title: str = "", topic_angle: str = "", context_text: str = "") -> str:
    primary = re.sub(r"\s+", "", " ".join(part for part in (topic_title, topic_angle) if part))
    normalized = re.sub(r"\s+", "", " ".join(part for part in (topic_title, topic_angle, context_text) if part))

    daily_return_signal = (
        _count_keyword_hits(normalized, _INNER_SETTLEMENT_REFERENCE_KEYWORDS) >= 4
        and _count_keyword_hits(normalized, _INNER_SETTLEMENT_THESIS_MARKERS) >= 1
        and (
            _count_keyword_hits(normalized, _INNER_SETTLEMENT_DAILY_GROUNDING_KEYWORDS) >= 2
            or _count_keyword_hits(normalized, _INNER_SETTLEMENT_DAILY_RETURN_KEYWORDS) >= 3
        )
    )

    if any(keyword in primary for keyword in _INNER_SETTLEMENT_STAGE_RESTART_KEYWORDS):
        return "stage_restart"
    if any(keyword in primary for keyword in _INNER_SETTLEMENT_REGRET_RELEASE_KEYWORDS):
        return "regret_release"
    if any(keyword in primary for keyword in _INNER_SETTLEMENT_DAILY_RETURN_KEYWORDS):
        return "daily_return"
    if daily_return_signal:
        return "daily_return"
    if any(keyword in primary for keyword in _INNER_SETTLEMENT_RUMINATION_KEYWORDS):
        return "rumination"
    if any(keyword in normalized for keyword in _INNER_SETTLEMENT_STAGE_RESTART_KEYWORDS):
        return "stage_restart"
    if any(keyword in normalized for keyword in _INNER_SETTLEMENT_REGRET_RELEASE_KEYWORDS):
        return "regret_release"
    if any(keyword in normalized for keyword in _INNER_SETTLEMENT_DAILY_RETURN_KEYWORDS):
        return "daily_return"
    if any(keyword in normalized for keyword in _INNER_SETTLEMENT_RUMINATION_KEYWORDS):
        return "rumination"
    return "gentle_unsettled"


def _build_inner_settlement_profile(*, variant: str) -> dict[str, str]:
    profile = {
        "reader_situation": "明明外面未必最糟，心里却一直悬着、放不下或迟迟回不了稳的人",
        "core_conflict": "很多时候真正拖住人的，不是外面已经坏到无路可走，而是我们总想先把一切安排好、解释清、证明稳，才肯让那颗心慢慢松下来。",
        "observed_phenomenon": "很多人日子照常过着，却很少真正把自己放回日子里：手上在往前推，心里却一直没有找到能安顿下来的位置。",
        "normalized_topic_angle": "从人为什么明明日子还在往前走，心却迟迟回不了位切入，重点写那颗心怎样慢慢放平，以及人怎样重新住回自己的日子里。",
        "writing_goal": "把人为什么总在心里悬着、迟迟回不了稳讲清楚，也让读者看见，真正的回稳不是把一切想通，而是先把自己慢慢安顿回当下。",
        "clarified_problem": "关键不在于事情有没有一个足够标准的答案，而在于很多人明明还在正常过日子，心却总落不到实处，反而忘了先让自己坐回生活里；也要让读者看见，心慢慢安顿下来以后，很多事才会重新有轻重。",
        "feedback_entry": "明明外面未必最糟、却一直安不下来的读者会先认出自己的处境，也会知道自己不是非得先把内心说服完，才配慢慢松下来。",
        "problem_explanation": "核心要拆开的，是为什么人明明还在正常过日子，却总让那颗心停在没收好的地方；也要落到把自己慢慢放回今天、放回日常，反而更容易让生活重新有序。",
        "point_of_view": "不急着给人生答案，先把那颗心为什么一直没有真正安顿好讲清楚，再把读者慢慢带回她已经在过的日子里。",
        "conflict_frame": "真正困住人的，常常不是外界已经坏到无路可走，而是那颗心一直停在半空里，不肯跟着人一起回到当下。",
        "emotional_path": "先认出心为什么一直悬着、一直在心里较劲，再看那股劲怎样慢慢松开，最后把人重新送回今天还能过、还能握住的生活里。",
        "opening_move": "开头先落一个心还没完全安顿好、却已经想慢慢回位的现实接口：热闹散了，人终于停下来，才发现自己很久没有真正松过一口气；忙碌过去了，心却还没找到安放的位置。第一屏以短段为主，不要先讲大道理、关系结果、身体告警或幸福定义。",
        "body_shift": "中段先拆那颗心为什么总想先把一切想稳、想透、想明白，结果越想越回不了位；再写人怎样从现实余波里慢慢回稳，把心一点点放回眼前正在过的生活。",
        "ending_move": "结尾回到一个心重新住回日子的轻动作、现实余波或继续生活的安排，不写空泛看开，也不写祝福口号。",
        "benchmark_borrow_focus": "原文里那颗心为什么迟迟落不下来的牵挂 / 情绪怎样慢慢回稳 / 结尾怎样把人送回仍在继续的生活",
        "benchmark_summary": "只借原文里心一直悬着与慢慢回稳的主线，不借原文标题骨架、固定安抚句、开头物件组和结尾抚慰口吻。",
        "expression_constraint": "不要把心安归位稿统一写成夜深灯光、饭凉水杯那一组小失序模板，也不要滑成关系等待、身体告警、症状清单或空泛幸福定义。",
    }
    if variant == "rumination":
        profile.update(
            {
                "normalized_topic_angle": "从那些一句话过去了、心却还停在原地的时刻切入，重点写人为什么总想把过去想透、把未来想稳，结果把自己一直留在悬着的位置。",
                "writing_goal": "把人为什么总会在心里反复回放、越想越难松下来讲清楚，也让读者看见，那股劲慢下来以后，日子才会重新有地方落脚。",
                "point_of_view": "不急着劝人立刻放下，先把为什么总在心里反复回放讲清楚，再把读者慢慢带回眼前的生活。",
                "opening_move": "开头先落一个还在反复回想、反复琢磨的瞬间：一句话已经过去了，心却还停在那儿；事情没有继续发酵，脑子却还想把它彻底想明白。第一屏以短段为主，不要先讲大道理，也不要滑成胸口、胃口、睡眠这类症状化起手。",
                "body_shift": "中段先拆人为什么总想把过去想透、把未来想稳，结果把自己一直留在悬着的位置；再写那股劲怎样慢下来，心怎样一点点回到眼前。",
            }
        )
    elif variant == "regret_release":
        profile.update(
            {
                "normalized_topic_angle": "从那些会把旧念头重新勾回来的现实接口切入，重点写人为什么总会在过去和如果当初里停一下，又怎样把遗憾慢慢安放回过去。",
                "writing_goal": "把人为什么总会被旧事和当初拉回去讲清楚，也让读者看见，放下不是背叛过去，而是让今天和以后重新有位置。",
                "feedback_entry": "明明已经往前走了，心里却还会被旧事拉回去的人会先认出自己的处境，也会知道放下不是逼自己忘掉，而是把过去放回过去，让今天继续往前。",
                "problem_explanation": "核心要拆开的，是为什么人明明知道很多旧事已经回不去，还是会在某个物件、某句话或某个瞬间里再次被拉回当时；也要落到把遗憾安放好，今天才会重新腾出位置。",
                "point_of_view": "不急着催人忘掉，先把为什么总会被过去拉回去讲清楚，再把读者带回今天还能继续发生的生活。",
                "conflict_frame": "真正拖住人的，未必是过去本身还在发生，而是心里一直替那段回不去的东西留着位置。",
                "emotional_path": "先认出旧事为什么总会在不经意时被勾回来，再看遗憾怎样从一直占心，慢慢变成可以被收好的过去。",
                "opening_move": "开头先落一个会把旧念头勾回来的现实接口：旧物、旧话、旧地方、一次擦肩，或一句突然想起的话。不要先讲看开，更不要写成立刻翻篇的励志口号。",
                "body_shift": "中段先拆人为什么明知回不去，还会在“如果当初”里停一下；再写遗憾怎样从一直占心，慢慢变成可以被收好的过去，让今天和以后重新腾出位置。",
                "ending_move": "结尾回到一个不再反复回头、而是把注意力交还给今天的小动作，不写空泛看开，也不写强行振作。",
            }
        )
    elif variant == "daily_return":
        profile.update(
            {
                "normalized_topic_angle": "从那些把人慢慢接回自己的普通接口切入，重点写真正的心安为什么要从向内安顿开始，又怎样在真实日常里一点点生长出来。",
                "writing_goal": "把心为什么迟迟安不下来讲清楚，也让读者看见，真正把人接回来的，往往不是顿悟，而是那些重新有轻重的普通日常。",
                "feedback_entry": "明明心里一直悬着，却慢慢被普通日常接回来的读者会先认出自己的处境，也会知道不是非得等到彻底想通，生活才可以重新有轻重。",
                "point_of_view": "不急着把心安写成抽象道理，先把人为什么迟迟回不了稳讲清楚，再把那股回到当下的力量交还给真实日常。",
                "opening_move": "开头先落一个日子正在把人往回接的小接口：终于坐下来吃一顿饭、一次慢下来的呼吸、一个原本被忽略的普通安排重新有了分量。不要先讲幸福定义，也不要照搬参考文那组家庭动作清单。",
                "body_shift": "中段先拆那颗心为什么总想先把自己说服明白、把日子安排妥帖，结果反而越悬越紧；再写那些普通但真实的日常安排怎样一点点把人接回来，让今天重新有轻重。",
                "ending_move": "结尾回到一个继续生活、继续在场、重新有轻重的普通动作，不写祝福，也不写宏大顿悟。",
            }
        )
    elif variant == "stage_restart":
        profile.update(
            {
                "reader_situation": "站在阶段交界处，容易把没完成、没拥有和没赶上一起算成自己不够好的人",
                "core_conflict": "很多人在阶段性回望里最容易犯的，不是看不清现实，而是把未完成、错过和眼下的不如意全扣成“我这段时间白过了”，于是越回望越否定自己。",
                "observed_phenomenon": "到了半年、年中或某个阶段节点，很多人都会突然开始清点：目标做了多少，错过了什么，人有没有留住，自己是不是又慢了一点。看起来像复盘，其实常常先变成了一场对自己的追责。",
                "normalized_topic_angle": "从人为什么总会在阶段节点把没完成、没拥有和没赶上一起算成失败切入，写遗憾怎样被安放、温暖怎样把人托住，以及人怎样重新接纳眼前这个阶段的自己，带着期待继续往前。",
                "writing_goal": "把人为什么总会在阶段节点先否定自己讲清楚，也让读者看见，真正能把人送去下一个阶段的，不是更狠地追责自己，而是重新安放遗憾、看见仍在身边的爱与支撑，并把力气收回到眼前的人生里。",
                "clarified_problem": "关键不在于一个人上半年做得够不够好，而在于很多人一到阶段节点，就会把没完成、没拥有和没赶上一起算成“自己不够好”；也要让读者看见，阶段性的失落并不等于这一段人生白过了，重新出发往往是从接纳此刻和珍惜眼前开始的。",
                "feedback_entry": "那些一到阶段节点就开始否定自己的人，会先认出自己的处境，也会慢慢相信：事与愿违未必是失败，很多正在发生的爱、支撑和成长，本来就在把自己送往下一个更好的阶段。",
                "problem_explanation": "核心要拆开的，是为什么人一到阶段节点，总会拿结果倒扣自己，把遗憾、疲惫和比较一起压成失败感；也要落到把遗憾安放好、把眼前的关系和生活重新看见，人才有力气继续往前。",
                "point_of_view": "不急着催人翻篇和振作，先把阶段性回望里那股自责和失落讲清楚，再把读者慢慢带回眼前仍在托住她的人和生活里。",
                "conflict_frame": "真正让人难受的，常常不是这一阶段没有圆满，而是总想用结果一次性证明自己有没有白走这段路。",
                "emotional_path": "先认出阶段节点上的自责、遗憾和比较是怎样一起压上来的，再看温暖、陪伴和阶段自洽怎样一点点把人从否定自己里接回来，最后把力气还给接下来的生活。",
                "opening_move": "开头先落一个阶段节点上很真实的自我盘点接口：年初定下的目标、这半年过得好不好、某个人是不是留在身边、自己是不是又慢了一点。不要先写深夜翻旧消息，也不要先给人生答案。",
                "body_shift": "中段先拆人为什么总会把没完成、没拥有和没赶上一起算成失败，再写那些仍在身边的爱、牵挂、普通支撑和阶段积累，怎样把人从自责里慢慢接回来；后半篇把比较心收回，落到每个阶段都有自己的分量与光亮。",
                "ending_move": "结尾回到一个继续生活、继续珍惜、继续往前的小动作或新期待上，不写口号式祝福，也不写空泛逆袭宣言。",
                "benchmark_borrow_focus": "半年节点上的回望情绪 / 事与愿违后的安放方式 / 亲情支撑与阶段自洽怎样把人重新送回生活",
                "benchmark_summary": "只借原文里阶段节点回望、遗憾安放、被爱托住和接纳当下阶段的主线，不借原文标题骨架、分段顺序和祝福式收尾。",
                "expression_constraint": "不要把阶段回望稿写成深夜自责诊断、结果依赖分析或单一失恋复盘；重点要留在阶段安放、重新出发和对当下自己的接纳上。",
            }
        )
    return profile


def _resolve_everyday_warmth_variant(*, topic_title: str = "", topic_angle: str = "", context_text: str = "") -> str:
    normalized = re.sub(r"\s+", "", " ".join(part for part in (topic_title, topic_angle, context_text) if part))
    responsibility_hits = _count_keyword_hits(normalized, _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_KEYWORDS)
    responsibility_marker_hits = _count_keyword_hits(normalized, _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_MARKERS)
    responsibility_strong_hits = _count_keyword_hits(normalized, _EVERYDAY_WARMTH_RETURN_RESPONSIBILITY_STRONG_ANCHORS)
    daily_hits = _count_keyword_hits(normalized, _EVERYDAY_WARMTH_RETURN_DAILY_KEYWORDS)
    if (responsibility_hits >= 4 and daily_hits >= 2 and responsibility_marker_hits >= 1) or (
        responsibility_hits >= 3 and responsibility_marker_hits >= 2
    ) or (
        responsibility_hits >= 6
        and daily_hits >= 2
        and responsibility_strong_hits >= 3
        and any(token in normalized for token in ("安稳", "一个家", "家里", "有我"))
    ):
        return "responsibility_shelter"
    if any(
        keyword in normalized
        for keyword in (
            "大富大贵",
            "简单快乐",
            "家人安康",
            "家人平安",
            "知己二三",
            "知己仍在",
            "四季平安",
            "高朋满座",
            "香车美宅",
            "一家温暖",
            "平安健康",
            "有家可回",
            "有人可爱",
            "知足最幸福",
            "更大的拥有",
            "一顿热饭",
        )
    ):
        return "simple_happiness"
    return ""


def _build_everyday_warmth_profile(*, variant: str) -> dict[str, str]:
    if variant == "responsibility_shelter":
        return {
            "reader_situation": "家里临时有事时，总会先把现实顺序理清的人",
            "core_conflict": "家里临时有事时，最重的往往不是事有多大，而是你总想先把人稳住、先把顺序理清。",
            "observed_phenomenon": "事情一来，手上的安排会先停一下，脑子里已经开始看谁要陪、哪件要挪、哪一步要先做。",
            "normalized_topic_angle": "从参考文已经成立的现实入口切入，写这个人为什么总先把顺序理清，也写这些认真怎样慢慢变成一家人的踏实。",
            "writing_goal": "把一个临时状况怎样把家的顺序重新排开讲清楚，也让读者看见，很多认真不是白费，它们最后会落成父母安心、孩子底气和家里的稳当。",
            "clarified_problem": "关键不在于中年有多辛苦，而在于家里临时有事时，现实安排怎样一起推到眼前；也要让读者看见，这些安排最后怎样变成一个家的安稳。",
            "feedback_entry": "那些总是先把家里安排好的人，会先认出“这说的就是我”；读完也会更确定，自己一次次多想一步，真的正在托住这个家。",
            "problem_explanation": "核心要拆开的，不是中年为什么总在扛事，而是一个现实入口为什么会把陪护、接送、开销、请假或晚饭一起推到眼前；也要落到这些细小安排最后会变成一个家的安稳。",
            "benchmark_borrow_focus": "现实入口出现后立刻开始排顺序的那一下 / 父母孩子伴侣怎样让辛苦变得值得 / 家里有人被护住时的回温动作",
            "benchmark_summary": "只借参考文里现实入口、家里临时有事和安稳回温这条主线，不借原文标题骨架、排比句势和结尾口号。",
            "point_of_view": "不急着把文章写成中年励志，先把参考文自己的现实动作和那句“我来安排”写实，再让责任和安稳慢慢浮出来。",
            "conflict_frame": "真正让人愿意多想一步的，不是口号，是事情一来就要挪开的几件现实安排。",
            "emotional_path": "先看见现实入口里的具体安排，再看见这些安排怎样一点点换来家里的踏实。",
            "opening_move": "开头先落参考文已经成立的真实动作，不要先用泛泛总括句起手，也不要硬套电话、日历或消息入口。",
            "body_shift": "中段先写事情来了以后要挪的安排、要顾的人和要补上的日常，再讲责任怎样把一个家的顺序慢慢理顺；不要先把责任讲成大道理。",
            "ending_move": "结尾回到灯还亮着、饭先热着、事情终于安顿下来的那一下，让回温落在具体动作上。",
            "packaging_focus": "包装先抓肩上的责任、现实入口后的安排和家里为什么会被托稳，再带回那点安稳怎么回来。",
            "packaging_hook": "事情一来，顺序先乱了半步，人也先稳住了一家。",
            "expression_constraint": "不要把责任托家稿写成放下执念、关系回消息排序、争吵后修复、泛内耗诊断、身体告警或空泛正能量口号；重点要留在责任、安稳、家里有人和辛苦为什么值得。",
        }
    if variant != "simple_happiness":
        return {}
    return {
        "reader_situation": "总把好日子押在更大的拥有上，走到后来才发现自己真正想守住的其实很简单的人",
        "core_conflict": "越把幸福押在更大的拥有、更体面的配置和更热闹的人生上，越容易忽略真正托住自己的家人平安、知己仍在和日子踏实。",
        "observed_phenomenon": "很多人年轻时忙着追更大的房子、更多的钱、更热闹的圈子，到了后来才发现，真正让人安心的往往不是这些外在配置，而是有人可爱、有家可回、还有能说心里话的人。",
        "normalized_topic_angle": "人会一路追着更多拥有往前走，直到某个普通晚上被一顿热饭、一通惦记和一句到哪了轻轻接住，才重新看见家人平安、知己仍在的分量。",
        "writing_goal": "把人为什么总会把幸福误判成更多拥有讲清楚，也让读者看见，真正让日子稳下来的，往往是家人平安、知己仍在和那些看起来不耀眼却最能托底的日常。",
        "clarified_problem": "关键不在于一个人该不该继续努力，而在于很多人会把幸福长期押在财富、体面和外在拥有上，直到走了一段路以后，才发现真正想守住的，不过是家人平安、知己仍在和日子简单。",
        "feedback_entry": "那些一直把好日子押在下一次达成、下一笔收入和下一层体面上的人，会先认出“原来我的幸福坐标偏远了”，也会慢慢看见：真正让自己踏实的，原来一直是家人平安、知己仍在和生活还热乎着。",
        "problem_explanation": "核心要拆开的，是为什么人总要走一段路、见过一些热闹、背过一些目标，才会重新明白什么才是最值得守住的幸福；也要落到家人平安、知己仍在和日子简单，反而最难被及时看见。",
        "benchmark_borrow_focus": "幸福坐标的重估 / 财富排场与踏实感的落差 / 家人平安知己仍在怎样重新托住一个人",
        "benchmark_summary": "只借原文里幸福观重估、知己与家人回到主位这条主线，不借原文标题骨架、举例顺序和收束动作。",
        "point_of_view": "不急着把文章写成反努力宣言或空泛知足文，先把幸福的坐标为什么会慢慢偏掉，又怎样回到家人、朋友和真实日子里讲清楚。",
        "conflict_frame": "真正让人后知后觉的，常常不是自己没得到更多，而是一路追着体面和热闹往前跑的时候，把最能托住自己的那几样东西放轻了。",
        "emotional_path": "先认出人为什么总会把幸福押在更大的拥有上，再看家人、知己和踏实日常怎样一点点把心从外面收回来。",
        "opening_move": "开头先落一个外在标准明明够了、心却没有更安稳的瞬间，或一串很朴素却很准确的生活愿望；不要从回消息、改期、待办堆积这类别的主题接口起手。",
        "body_shift": "中段先拆财富、排场、圈子和房子为什么不能持续提供踏实感，再把家人平安、朋友仍在、有人可回去的日常怎样重新显出分量讲清；不要把这些分量压成几个空标签。",
        "ending_move": "结尾回到简单快乐、家人平安、知己仍在或一顿热饭一盏灯这类具体回温动作，不要收成冷冰冰的机制分析、待办回填或回应排序。",
        "expression_constraint": "不要把简单幸福稿写成回消息排序、关系善后、身体告警或待办清单分析；重点要留在幸福观重估、家人平安、知己仍在和日子踏实。",
    }


def _extract_pressure_reference_cues(reference_body_markdown: str, *, max_items: int = 3) -> list[str]:
    if not reference_body_markdown.strip():
        return []

    generic_prefixes = ("其实", "人啊", "你每天", "人这一生", "生活从来", "生活，从来", "平日里", "我想", "如果生活")
    generic_phrases = ("这个世界上", "真正的完美", "所谓的完美人生", "生活本身", "真正的自己")

    cues: list[tuple[int, str]] = []
    for block in _extract_reference_blocks(reference_body_markdown):
        sentences = [item.strip() for item in re.split(r"[。！？!?；;\n]", block) if item.strip()]
        for raw_sentence in sentences:
            compact = re.sub(r"\s+", "", raw_sentence).strip()
            if not compact:
                continue
            if any(compact.startswith(prefix) for prefix in generic_prefixes):
                continue
            if any(phrase in compact for phrase in generic_phrases):
                continue
            hard_hits = _count_keyword_hits(compact, _PRESSURE_REFERENCE_HARD_SIGNALS)
            soft_hits = _count_keyword_hits(compact, _PRESSURE_REFERENCE_SOFT_SIGNALS)
            consequence_hits = _count_keyword_hits(compact, _PRESSURE_REFERENCE_CONSEQUENCE_MARKERS)
            if (
                "健康的身体" in compact
                and hard_hits == 0
                and not any(marker in compact for marker in ("改", "拖", "推", "往后", "报警", "提醒", "怀念", "后来", "直到"))
            ):
                continue
            if _has_emotional_release_reference(compact) and hard_hits == 0:
                continue
            if hard_hits == 0 and soft_hits == 0:
                continue
            if hard_hits == 0 and (soft_hits < 2 or consequence_hits == 0):
                continue
            sentence = compact
            if len(sentence) > 42:
                sentence = sentence[:42].rstrip() + "..."
            score = hard_hits * 3 + soft_hits + consequence_hits
            cues.append((score, sentence))

    selected: list[str] = []
    for _, cue in sorted(cues, key=lambda item: (-item[0], len(item[1]))):
        if cue in selected:
            continue
        selected.append(cue)
        if len(selected) >= max_items:
            break
    return selected


def _compact_pressure_reference_cue(cue: str) -> str:
    if not cue:
        return ""
    for part in re.split(r"[，,、]", cue):
        normalized = part.strip()
        if not normalized:
            continue
        if any(keyword in normalized for keyword in ("尿毒症", "褥疮", "透析", "轮椅", "体检", "身体", "疲惫", "耗尽")):
            normalized = re.sub(r"^(后来|几年后|又过了一些年|又过了几年|又过些年|前两年|当初|刚得|要|便|又开始|开始)+", "", normalized)
            return normalized or part.strip()
    return cue[:18].rstrip() + ("..." if len(cue) > 18 else "")


def _build_reader_situation(
    topic_title: str,
    topic_angle: str,
    *,
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        return "总把休息、体检、吃饭、回复和自己顺手往后挪的人"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "一路追着更大的目标往前跑，慢下来后才意识到真正重要的东西一直没走远的人"
    if _uses_inner_settlement_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "明明外面未必最糟，却总把心安交给结果和答案、很少先把自己安顿下来的人"
    if _uses_self_worth_rebuild_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "总把体谅、迁就和退让走在自己前面，后来才发现自己在关系里越站越靠后的人"
    if _uses_trust_boundary_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "曾经愿意放心相信一个人，却被一句谎言、一次隐瞒弄得心里开始发紧的人"
    if _uses_response_priority_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        if response_priority_followup_variant:
            return "轻互动并不少、真正被读懂却不多，所以格外珍惜那种愿意停下来多问一句、把情绪接住的人"
        return "总在表层互动里替人找理由，后来才慢慢意识到回应顺序、追问动作和心力投向本身就是答案的人"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "每次吵完都要自己消化情绪、把日子接回去的人"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "被命运或身体限制迎头打过，却还得一次次把自己重新托住的人"
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "在低谷里也想有人陪一程，却慢慢学会先把自己安顿住的人"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "总在得不到的东西上反复拉扯，明明已经很累却还是不肯松手的人"
    if "边界" in topic_angle:
        return "总把自己的感受、门槛和位置往后放，后来才发现体面一路被放轻的人"
    if "情绪" in topic_angle:
        return "明明已经很累，却还是习惯把自己的感受往后放的人"
    if "自我" in topic_angle:
        return "总想把一切都稳妥接住，却很少让自己真正松一口气的人"
    return f"正在为“{topic_title}”这类处境反复卡住的人"


def _build_core_conflict(
    topic_title: str,
    topic_angle: str,
    *,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if primary_pressure_cue and secondary_pressure_cue and _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        return f"越觉得 `{primary_pressure_cue}` 还能再拖一拖，后面就越容易一路追到 `{secondary_pressure_cue}` 这种更重的代价。"
    if primary_pressure_cue and _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        return f"越觉得 `{primary_pressure_cue}` 还能先压一压，后面越容易把身体和生活一起拖乱。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "越把重要感押在更大的目标上，越容易在一路往前赶的时候，错过那些真正托住自己的陪伴和日常。"
    if _uses_inner_settlement_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "越想先从外面拿到一个足够确定的答案，越容易把现在的自己留在那颗一直绷着、不肯松下来的心里。"
    if _uses_self_worth_rebuild_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "越怕失去、越急着证明自己值得被爱，越容易先把边界、标准和体面一点点让出去。"
    if _uses_trust_boundary_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "越把别人的信任当成可以含糊带过的小事，一句谎言、一次隐瞒就越容易把原本稳定的心安划出裂缝。"
    if _uses_response_priority_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        if response_priority_followup_variant:
            return "越把热闹互动误认成关心，越容易忽略真正让人踏实的，往往只是有人愿意停下来读懂你没说完的话。"
        return "越替那些停在表面的回应找理由，越容易忽略顺序、追问和心力投向早就把自己放在了什么位置。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "冲突本身未必会让关系散掉，可如果每次吵完都只有一方在善后，安全感就会被一点点磨掉。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正难的，不只是命运下手太重，而是长期疼痛、重复训练和外界定义都在往下拽，人还是得决定不把残缺和低谷收成自己的结论。"
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "越把全部希望都压在外面的回应上，心越容易悬着；真正让人慢慢站稳的，是先恢复判断和行动，再学会清楚地求助、分担。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "越舍不得停下，越容易把继续消耗误认成认真，最后连眼前真正重要的东西也一起忽略掉。"
    if "边界" in topic_angle:
        return "越怕关系散掉、越急着证明自己值得，越容易先把边界、标准和体面一点点让出去。"
    if "情绪" in topic_angle:
        if primary_pressure_cue:
            return f"越想把 `{primary_pressure_cue}` 这类信号压回去，后面越容易追出更大的身体和生活代价。"
        return "越想赶快恢复正常，越容易忽略身体和情绪已经在报警。"
    if "自我" in topic_angle:
        return "越想证明自己能扛住，越容易把真正的疲惫藏得更深。"
    return f"{topic_title}里最难的是把心里明白的事落回当下，真的动到自己的生活顺序。"


def _build_observed_phenomenon(
    *,
    topic_title: str,
    topic_angle: str,
    trend_title: str,
    source_mode: str,
    tracked_article_scene: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        normalized = f"{topic_title} {topic_angle}"
        if primary_pressure_cue and any(marker in normalized for marker in ("复查", "体检", "拖延", "推后", "还能扛", "该停了", "判断", "求救")):
            return f"`{primary_pressure_cue}` 这种信号已经冒出来了，人却还在把复查、休息和身体判断一次次往后推。"
        if primary_pressure_cue and ("透析" in normalized or secondary_pressure_cue):
            return f"`{primary_pressure_cue}` 这种信号已经冒出来了，人却还在把复查、休息和判断一次次往后压。"
        if primary_pressure_cue:
            return f"`{primary_pressure_cue}` 这种信号已经冒出来了，人却还在把该停下来的那一步继续往后拖。"
        return "很多事会被一次次往后顺延，顺延久了，连该不该停下来都会慢慢判断不准"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多人一路追着更大的目标往前跑，等真正慢下来以后，才慢慢认出那些最普通的陪伴和日常，其实一直在托住生活"
    if _uses_inner_settlement_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多人外面看着一切照常，心里却一直没松下来；不是被某一件大事一下压垮，而是被反复想、反复拧和迟迟放不下慢慢拖钝了"
    if _uses_self_worth_rebuild_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多人不是不知道自己受了委屈，而是总把体谅、退让和示好摆在前面，等到边界、标准和体面一路往下掉，才后知后觉地看见自己在关系里越站越靠后。"
    if _uses_trust_boundary_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多关系原本不用反复证明，可一次谎言、一次隐瞒以后，人就会从放心变成猜测；真正需要被写清的，是信任怎样裂开，又怎样靠坦诚和说到做到重新落稳。"
    if _uses_response_priority_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        if response_priority_followup_variant:
            return "很多互动看起来并不冷，可真正让人放下心的，从来不是有人路过式回应，而是有人能从一句轻描淡写的话里听出你的真实情绪，并愿意顺着它再往前走一步。"
        return "很多人不是看不见回应里的差别，而是总想再等等看，直到表层热闹、顺手点赞、肯不肯追问和会不会回头这些动作一次次重复，才承认位置早就写出来了"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多关系表面还能照常过下去，可真正决定它会不会继续往前的，是争执后有没有人回来沟通、接住失望。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "有些人不是没有被命运打碎过，而是被打碎以后，还得在长期疼痛、重复训练和别人想替她下定义的目光里，一次次把自己重新托起来"
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多人一到低谷，也想暂时靠一靠，可真正让人发慌的，往往不是没人关心，而是现实一下子挤满了，谁都抽不出那点余力。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多人把继续投入误认成再坚持一下就会圆满，等真正停下来时，才发现自己早已忽略了眼前拥有的部分。"
    if source_mode == "tracked_article":
        if "推迟" in topic_angle or "往后放" in topic_angle or "等有空再说" in topic_angle:
            return "很多事会被一次次往后顺延，顺延久了，生活的轻重顺序也会慢慢倒过来"
        if "边界" in topic_angle:
            return "很多人不是一下子就把自己放低，而是在一次次“都可以”“算了”和先让一步里，慢慢把边界、标准和体面一起放轻了"
        if "情绪" in topic_angle:
            if primary_pressure_cue:
                return f"`{primary_pressure_cue}` 这种信号已经冒出来了，人却还在逼自己装作一切正常"
            return "人已经在日常里明显变慢、变钝、变得不想说话，却还在逼自己装作没事"
        if "自我" in topic_angle:
            return "表面看起来还在正常生活，心里却一直绷着，不敢承认自己已经快撑不住了"
        return f"{topic_title}会在日常里反复出现，像一种总也绕不过去的卡住状态"
    if tracked_article_scene:
        return tracked_article_scene
    if "边界" in topic_angle:
        return "很多人不是一下子就把自己放低，而是在一次次“都可以”“算了”和先让一步里，慢慢把边界、标准和体面一起放轻了"
    if "情绪" in topic_angle:
        return "人已经在日常里明显变慢、变钝、变得不想说话，却还在逼自己装作没事"
    if "自我" in topic_angle:
        return "表面看起来还在正常生活，心里却一直绷着，不敢承认自己已经快撑不住了"
    if source_mode == "trend":
        return f"{trend_title}这一类处境正在被很多人反复经历，但大多数表达只停在道理层"
    return f"{topic_title}会在日常里反复出现，像一种总也绕不过去的卡住状态"


def _normalize_topic_angle(
    *,
    topic_angle: str,
    topic_title: str,
    source_mode: str,
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    normalized = re.sub(r"\s+", " ", topic_angle).strip()
    if not normalized:
        return "未显式提供"
    if source_mode != "tracked_article":
        return normalized
    if structure_mode == "inner_settlement":
        return "从那些心里一直没落稳、却还在照常生活的时刻切入，重点写人为什么总想把一切想明白，最后忘了先把自己安放回一餐一饮和一呼一吸。"
    if structure_mode == "self_worth_rebuild":
        return "从一个人总把自己放轻、把体谅和迁就走在前面切入，重点写边界、标准和体面为什么会在一次次退让里往下掉，以及人怎样重新把尊重和分量收回来。"
    if structure_mode == "trust_boundary":
        return "从一句谎言、一次隐瞒让信任裂开的瞬间切入，重点写信任为什么珍贵又脆弱，以及关系想走得长久，怎样靠坦诚、交代和说到做到把心安重新托住。"
    if structure_mode == "everyday_warmth_return":
        return normalized
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "从轻互动为什么不等于真正的在乎切入，重点写一句追问、一次补问和一次认真停下来怎样把人从表层热闹里轻轻接住。"
        return "从表层回应为什么常被误认成在乎切入，重点写顺序、追问、回头动作和投入意愿怎样显出一个人的真实在乎程度。"
    if structure_mode == "relationship_aftercare":
        return normalized
    if structure_mode == "resilience_reconstruction":
        return "从命运重击、长期疼痛和重复训练切入，重点写一个人怎样在反复重来里把身体与意志重新托住，而不是被残缺、低谷和外界定义收走人生。"
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=normalized, structure_mode=structure_mode):
        return "从想求助却发现别人也各自承压的处境切入，重点写一个人怎样先稳住判断和行动，再在合适的时候求助、分担，长出自救自渡的力气。"
    if structure_mode == "emotional_engine_direct":
        return normalized
    if structure_mode == "pressure_interface_direct":
        joined = f"{topic_title} {normalized}"
        if any(keyword in joined for keyword in ("复查", "体检", "拖延", "推后", "还能扛", "该停了", "判断", "求救")):
            return "从已经开始往坏处走的身体提醒切入，重点写复查、休息和自我判断怎样被一再往后推。"
        if "透析" in joined or "尿毒症" in joined or "求救信号" in joined or "压后" in joined:
            return "从已经拖到更重代价的身体信号切入，重点写复查、休息和自我判断是怎样被一再压后的。"
        if "胃口变差" in joined or "作息发乱" in joined or "没耐心" in joined or "负荷" in joined:
            return "从生活接口的长期负荷切入，重点写人为什么会把身体提醒放到所有事情后面。"
        return "从那些已经开始出代价的身体提醒和生活接口切入，重点写人为什么总把该先顾自己的事一再压后。"
    if "透析" in normalized or "尿毒症" in normalized or "求救信号" in normalized or "压后" in normalized:
        return "从已经拖到更重代价的身体信号切入，重点写复查、休息和自我判断是怎样被一再压后的。"
    if any(keyword in normalized for keyword in ("复查", "体检", "拖延", "推后", "还能扛", "该停了")):
        return "从已经开始往坏处走的身体提醒切入，重点写复查、休息和自我判断怎样被一再往后推。"
    if "推迟" in normalized or "往后放" in normalized or "等有空再说" in normalized:
        return "从一再被顺手往后挪开的接口切入，重点写生活顺序怎样被慢慢改写、代价怎样一点点堆出来。"
    if "胃口变差" in normalized or "作息发乱" in normalized or "没耐心" in normalized or "负荷" in normalized:
        return "从生活接口的长期负荷切入，重点写人为什么会把身体提醒放到所有事情后面。"
    if "情绪" in normalized or "报警" in normalized or "耗尽" in normalized:
        return "从身体和日常节奏已经开始变钝的迹象切入，重点写这些提醒怎样被一再压后。"
    if "边界" in normalized or "开口" in normalized or "误解" in normalized or "沟通" in normalized:
        return "从一个人总把体谅和迁就放在自己前面切入，重点写边界、标准和体面为什么会在一次次退让里往下掉，以及人怎样重新把自己抬回来。"
    if "自我" in normalized or "撑住" in normalized or "稳住" in normalized:
        return "从总想把自己绷住的日常代价切入，重点写人为什么越想稳住越累。"
    return f"围绕 `{topic_title}` 重建新的现实入口和推进顺序，不沿用原始说明书的句式、顺序和收束动作。"


def _build_writing_goal(
    *,
    topic_title: str,
    topic_angle: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue and secondary_pressure_cue:
            return f"把 `{primary_pressure_cue}` 怎样一路追到 `{secondary_pressure_cue}` 这种更重代价讲清楚，让读者先认出自己已经在透支什么。"
        if primary_pressure_cue:
            return f"把 `{primary_pressure_cue}` 这种信号为什么会越压越重讲清楚，让读者先认出自己已经在透支什么。"
        return "把那些被顺手往后挪开的接口怎样一步步堆出代价讲清楚，让读者先认出自己已经在透支什么。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把人为什么总把幸福和重要感押在更大的目标上讲清楚，也把人慢下来以后，为什么反而会被家人平安、朋友仍在和日常烟火重新托住讲清楚。"
    if _uses_inner_settlement_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把人为什么总在事情未必最糟的时候，先把自己困在那颗一直绷着的心里讲清楚，也让读者看见心安不是放弃，而是把自己慢慢安放回生活。"
    if _uses_self_worth_rebuild_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把人为什么总会把体谅、迁就和示好误认成在乎讲清楚，也让读者看见边界、标准和体面是怎样在一次次退让里被放低的；最后把尊重自己、把分寸和分量收回来写清楚。"
    if _uses_trust_boundary_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把信任为什么会被一句谎言、一次隐瞒划出裂缝讲清楚，也把坦诚、交代和说到做到怎样让关系重新有心安写出来。"
    if _uses_response_priority_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        if response_priority_followup_variant:
            return "把为什么很多人并不缺回应、心里却还是悬着讲清楚，也把被读懂、被追问和被认真放在心上的那种安稳写出来，让读者更会珍惜真正愿意停下来理解自己的人。"
        return "把人为什么总会替停在表面的回应找补讲清楚，也把顺序、追问和回头动作怎样比解释更早显出在乎程度讲清楚，让读者把位置感重新放回自己手里。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把为什么争吵并不可怕、争吵后有没有人回来沟通和接住失望才最说明关系分量讲清楚，让读者看见修复态度真正意味着什么。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把人为什么能在命运重击、长期疼痛和重复训练里，一点点把自己重新托住讲清楚，让读者看到韧性不是口号，而是拒绝被残缺和低谷定义。"
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把成年人为什么想求助时也会看见别人的难处讲清楚，也让读者看见，自救自渡不是硬扛，而是先恢复判断和行动，再在合适的时候求助、分担。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "把人为什么会把继续投入误认成更接近圆满讲清楚，让读者看见停下不是认输，而是把心力和目光收回到真正重要的东西上。"
    if "边界" in topic_angle:
        return "把人为什么总会先把自己放轻、把将就误认成懂事讲清楚，也让读者看见边界、标准和体面是怎样一点点被放低的。"
    if "情绪" in topic_angle:
        if primary_pressure_cue and secondary_pressure_cue:
            return f"把 `{primary_pressure_cue}` 为什么会一路追到 `{secondary_pressure_cue}` 这种更重代价讲清楚，让读者先意识到这不是一时状态差。"
        if primary_pressure_cue:
            return f"把 `{primary_pressure_cue}` 这种信号为什么不能再当成小事讲清楚，让读者先意识到这已经不是普通疲惫。"
        return "把“为什么人会一点点耗尽”讲清楚，让读者先意识到这已经是身体和情绪在报警，不必再把它误认成偷懒。"
    if "自我" in topic_angle:
        return "把“为什么越想稳住自己越累”讲清楚，让读者愿意先承认疲惫，再谈修复。"
    return f"把 `{topic_title}` 从抽象判断改写成能让读者认出处境、看到代价并获得情绪承接的现实推进。"


def _build_problem_constraints(*, source_mode: str) -> list[str]:
    constraints = [
        "不要写成口号文、模板鸡汤文或标准答案式议论文。",
        "不要做近义词改写，要换观察路径和情绪发动机。",
        "优先把情绪价值落在具体处境、触发反应、关系变化和现实结果上，不要先抽成终局问题或万能答案。",
        "不要靠整段场景描写起稿或凑篇幅，但允许保留 1 到 2 个有情绪功能的动作、物件或现实接口。",
    ]
    if source_mode == "tracked_article":
        constraints.append("参考材料只用于确认赛道和冲突，不得沿用原标题骨架、段落顺序和结尾动作。")
        constraints = merge_unique_lines(
            constraints,
            get_dbskill_rule_lines("strategy", "problem_constraints"),
        )
    return constraints


def _build_clarified_problem(
    *,
    topic_title: str,
    topic_angle: str,
    observed_phenomenon: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue and secondary_pressure_cue:
            return (
                f"关键要写出来的是，`{primary_pressure_cue}` 这样的信号为什么会一路拖到 `{secondary_pressure_cue}`，"
                f"中间那些已经开始失衡的生活接口又是怎么被一次次压过去的。"
            )
        if primary_pressure_cue:
            return (
                f"关键要写出来的是，`{primary_pressure_cue}` 这样的信号已经冒出来了，"
                f"人却还在把它往后顺延，最后让{observed_phenomenon}慢慢变成日常。"
            )
        return f"关键要写出来的是，{observed_phenomenon}背后那些被顺手往后挪开的接口，怎样一点点把压力和失衡堆了出来。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "关键不在于人该不该追求更大的目标，而在于很多人总要等到慢下来甚至差点错过的时候，才重新承认家人平安、朋友仍在和普通日常才是生活真正的底座。"
    if _uses_inner_settlement_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "关键不在于事情到底有没有标准答案，而在于很多人总把心放在悬空处，忘了先让自己落地；也要让读者看见，当那颗心慢慢安顿下来，很多事会重新有了轻重。"
    if _uses_self_worth_rebuild_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "关键要写出来的是，很多人明明已经在将就里受委屈了，还是会下意识把问题先归到自己不够好、不够值得；也要让读者看见，很多轻慢会停下来，往往是从你先尊重自己开始的。"
    if _uses_trust_boundary_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "关键要写出来的是，那份放心被隐瞒和谎言划出裂缝后，人为什么会开始不安；也要让读者看见，坦诚交代和日常里的说到做到，怎样把信任一点点托回来。"
    if _uses_response_priority_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        if response_priority_followup_variant:
            return "关键不在于谁更会互动，而在于很多人明明收到的回应并不少，心里却还是悬着；也要让读者看见，真正让人安稳的，往往不是热闹，而是有人愿意停下来理解你。"
        return "关键不在于替谁定罪，而在于很多人总把偶尔的回应当成例外、把长期的顺序当成误会；也要让读者看见，认清位置并不是失去爱，而是把自己放回该在的位置。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "关键要写出来的是，为什么一次次争执之后，总是只有一方在回收情绪、重建秩序，关系也就从这里开始慢慢失温。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "关键不在于一个励志标签，而在于有些人明明被命运重击、长期疼痛和训练代价反复碾过，还是会在一次次重来里拒绝把残缺和低谷收成自我定义。"
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "关键不在于一个人会不会求助，而在于当回应一时赶不上时，人怎样先把能做的事放回手里；也要让读者看见，自救和求助本来可以同时成立。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "关键不在于人人都懂却做不到的道理，而在于人为什么明明已经很累了，还是会把不甘心、投入感和希望错当成继续消耗自己的理由。"
    return f"{topic_title}要写清楚的，是{observed_phenomenon}里一点点累积出来的压力和失衡。"


def _build_feedback_entry(
    *,
    reader_situation: str,
    core_conflict: str,
    topic_title: str,
    topic_angle: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        anchor = f"`{primary_pressure_cue}` 这样的信号" if primary_pressure_cue else "这些已经被顺手往后挪开的接口"
        consequence = _build_pressure_feedback_consequence(
            topic_title=topic_title,
            topic_angle=topic_angle,
            secondary_pressure_cue=secondary_pressure_cue,
        )
        return (
            f"{reader_situation}会先认出自己的处境，"
            f"也会顺着{anchor}看到，自己为什么总把该先顾自己的事拖到更后面，"
            f"{consequence}。"
        )
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"{reader_situation}会先认出自己的处境，"
            "也会重新衡量家人平安、朋友仍在和普通日常的分量，认出它们不是附属品，而是这些年最该护住的生活底座。"
        )
    if _uses_inner_settlement_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"{reader_situation}会先认出自己的处境，"
            "也会松一口气，知道自己不是非得先把一切想透，才有资格慢慢松下来、把自己放回当下。"
        )
    if _uses_self_worth_rebuild_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"{reader_situation}会先认出自己的处境，"
            "也会慢慢看到，很多分量不是别人凭空给的，而是从你不再顺手退让、开始认真对待自己那一刻，才一点点回到你身上的。"
        )
    if _uses_trust_boundary_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"{reader_situation}会先认出“原来我介意的不是小事”，"
            "也会看见信任真正需要的，是坦诚、交代和说到做到带来的心安。"
        )
    if _uses_response_priority_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        if response_priority_followup_variant:
            return (
                f"{reader_situation}会先认出自己的处境，"
                "也会更清楚地看见，真正让人踏实的关心，往往不用你反复猜，而会从一句追问、一次补问和一次认真停下来里自己长出来。"
            )
        return (
            f"{reader_situation}会先认出自己的处境，"
            "也会更清楚地看见，真正值得留心的人，往往不会总让你靠猜去维持位置感。"
        )
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"{reader_situation}会先认出自己的处境，"
            "也会认出，关系发冷常常就是从每次架后都没人回来接住她开始的。"
        )
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"{reader_situation}会先认出自己的处境，"
            "也会认出，真正托住一个人的往往不是一句励志话，而是那些没人替她完成的重复训练和不肯被定义的那股劲。"
        )
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"{reader_situation}会先认出自己的处境，"
            "也会慢慢放下那种一下子必须全都撑住的慌张，知道求助不丢人，自救也不丢人。"
        )
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return (
            f"{reader_situation}会先认出自己的处境，"
            "也会意识到自己不是离幸福太远，而是一直把不肯停下误认成更接近幸福。"
        )
    return (
        f"{reader_situation}会先认出自己的处境，"
        f"并且能从 `{core_conflict}` 里看到自己为什么一直没能往前走。"
    )


def _build_pressure_feedback_consequence(
    *,
    topic_title: str,
    topic_angle: str,
    secondary_pressure_cue: str = "",
) -> str:
    normalized = f"{topic_title} {topic_angle}"
    if any(marker in normalized for marker in ("判断力", "判断", "求救", "该停了")):
        if secondary_pressure_cue:
            return f"最后连该不该停下来都越来越判断不准，等回过神来，已经拖到 `{secondary_pressure_cue}` 这一步了"
        return "最后连该不该停下来都越来越判断不准"
    if secondary_pressure_cue:
        return f"最后把原本还来得及回头的提醒，一路拖到 `{secondary_pressure_cue}` 这种更难收拾的后果"
    return "最后把原本该早点处理的提醒拖成更难收拾的麻烦"


def _build_problem_explanation(
    *,
    topic_title: str,
    topic_angle: str,
    observed_phenomenon: str,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue and secondary_pressure_cue:
            return (
                f"核心要拆开的，是为什么 `{primary_pressure_cue}` 这类提醒已经冒头了，"
                f"人还是会继续往后拖，最后一路拖到 `{secondary_pressure_cue}` 这种更重后果。"
            )
        if primary_pressure_cue:
            return (
                f"核心要拆开的，是为什么 `{primary_pressure_cue}` 这类提醒已经出来了，"
                "人还是会把该停下来的那一步继续往后推。"
            )
        return f"核心要拆开的，是为什么{observed_phenomenon}会一遍遍重演。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "核心要拆开的，是为什么很多人明明已经拥有家人平安、朋友仍在和一份能过下去的日常，却总在一路往前赶、差点错过之后，才肯重新给它们应有的分量。"
    if _uses_inner_settlement_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "核心要拆开的，是为什么人明明没有被某件大事彻底压垮，心里却一直安不下来；也要落到把自己重新放回一餐一饮和一呼一吸，很多事反而更容易被放稳。"
    if _uses_self_worth_rebuild_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "核心要拆开的，是为什么人明明已经在将就、示好和降低标准里一点点受伤，还是会继续把自己往后放；也要落到当一个人开始尊重自己、守住边界，很多关系的轻慢才会真正停下来。"
    if _uses_trust_boundary_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "核心要拆开的，是为什么一句谎言、一次隐瞒会让原本放心的关系开始松动；也要落到坦诚、交代和日常里的说到做到，怎样把信任一点点补回来。"
    if _uses_response_priority_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        if response_priority_followup_variant:
            return "核心要拆开的，是为什么人明明收到的回应并不少，心里却还是会空一下；也要落到一句追问、一次补问和一次真正被听懂，会比表面热闹更能把人轻轻安放下来。"
        return "核心要拆开的，是为什么人明明已经在回应动作里看见了答案，还是会继续替对方找补；也要落到一旦把顺序、追问和心力投向看清，人就更容易把期待和精力留给真正愿意回应的人。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "核心要拆开的，是为什么在有些关系里，架一吵完，总是同一个人先把话咽回去、把日常接回去，久了以后先退掉的往往是安全感和表达欲。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "核心要拆开的，是为什么人明明已经被命运和疼痛打得很重，还是会在重复训练和反复重来里，不肯把自己交给残缺、低谷和外界定义。"
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "核心要拆开的，是为什么人想开口时会先看见别人的难处；也要落到恢复判断、继续行动和清楚求助，反而更能把自己从慌里带回来。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "核心要拆开的，是为什么人明明已经被拖得很累了，还是会把继续投入误认成更接近幸福。"
    return f"核心要拆开的，是为什么{observed_phenomenon}会一遍遍重演，读者真正卡住的那一步到底在哪。"


def _build_unknowns(*, topic_angle: str, source_mode: str, tracked_article_scene: str) -> list[str]:
    unknowns: list[str] = []
    if not topic_angle.strip():
        unknowns.append("切口仍偏泛，大纲阶段要主动收窄到一个更具体的处境。")
    if source_mode == "tracked_article" and not tracked_article_scene:
        unknowns.append("参考材料缺少足够清晰的现实锚点，开头需要自行补出一个更具体的压力接口、后果或身体提醒。")
    return unknowns


def _build_point_of_view(
    topic_angle: str,
    *,
    topic_title: str = "",
    primary_pressure_cue: str = "",
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue:
            return f"不急着端出答案，先把 `{primary_pressure_cue}` 这种信号为什么会被一路压后讲清楚。"
        return "不急着端出答案，先把人是怎么一步步把自己往后放讲清楚。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着把文章写成反努力宣言或人生箴言，先把那些被高估的大事为什么会慢慢祛魅、家人平安、朋友仍在和日常烟火为什么反而更重要讲清楚。"
    if _uses_inner_settlement_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着劝人立刻看开，先把那颗心为什么一直落不下来讲清楚，再把读者慢慢带回她真正想安顿的地方。"
    if _uses_self_worth_rebuild_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着把文章写成识人清单、狠话宣言或谁对谁错的判案文，先把一个人为什么总会先把自己放轻、先把边界和标准让出去讲清楚。"
    if _uses_trust_boundary_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着把文章写成查岗、审判或控诉，先把信任为什么会被隐瞒划出裂缝讲清楚，再把坦诚和说到做到怎样重新托住心安写出来。"
    if _uses_response_priority_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        if response_priority_followup_variant:
            return "不急着用轻互动给关系排座次，先把被看见和被真正读懂之间的差别讲清楚；让一句追问、一次补问和一次认真停下来自己把关心显出来。"
        return "不急着替谁下判决，先把表层回应为什么常被误认成在乎讲清楚；让顺序、追问和心力投向自己把答案显出来，也让读者把位置感重新收回自己手里。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着给争吵贴对错，先把争执后有没有人回来沟通、有没有人愿意接住失望讲清楚。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着把人物写成励志样板或术后恢复案例，先把命运下手有多重、训练怎样一点点把身体与意志重新托住讲清楚。"
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着劝人独立坚强，先把成年人想求助却不总能立刻被接住的现实讲清楚，再把人怎样恢复判断、继续行动、也学会清楚求助写出来。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "不急着讲知足、放下或清醒的大道理，先把人为什么明明已经很累，却还是觉得自己不能停讲清楚。"
    if "边界" in topic_angle:
        return "不教训，不站高位，只把人为什么总会先把自己放轻、先把边界和标准让出去讲清楚。"
    if "情绪" in topic_angle:
        if primary_pressure_cue:
            return f"不急着给解决方案，先把 `{primary_pressure_cue}` 这种信号为什么会被继续压下去讲清楚。"
        return "不急着给解决方案，先把人为什么会一点点耗尽讲清楚。"
    return "不说教，不站高位，先把读者当下真正卡住的地方讲清楚。"


def _build_conflict_frame(
    topic_title: str,
    topic_angle: str,
    *,
    primary_pressure_cue: str = "",
    secondary_pressure_cue: str = "",
    structure_mode: str = "",
    response_priority_followup_variant: bool = False,
) -> str:
    if _uses_pressure_interface_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        if primary_pressure_cue and secondary_pressure_cue:
            return f"很多失序，都是从 `{primary_pressure_cue}` 被压过去，最后一路追到 `{secondary_pressure_cue}` 这种更重后果开始堆出来的。"
        if primary_pressure_cue:
            return f"很多失序，都是从 `{primary_pressure_cue}` 这种已经冒头的信号被继续压过去开始堆出来的。"
        return "很多失序，都是从那些被反复往后挪开的接口开始堆出来的。"
    if _uses_everyday_warmth_return_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正让人后知后觉的，不是没做成更大的事，而是一路忙着往前赶的时候，把最能托住自己的日常和陪伴慢慢放轻了。"
    if _uses_inner_settlement_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多难熬，不是因为事情本身一定多糟，而是那颗心一直绷着，不肯把自己放回当下。"
    if _uses_self_worth_rebuild_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "很多轻慢，不是突然发生的，而是在一次次先退一步、先把自己放轻、先把标准往下调里慢慢积出来的。"
    if _uses_trust_boundary_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "信任最难的地方，是它把自由和心安一起交出去；可一句谎言、一次隐瞒，就足以让人从放心变成反复确认。"
    if _uses_response_priority_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        if response_priority_followup_variant:
            return "很多时候真正让人踏实的，不是互动不断，而是有人能从你轻描淡写的话里听出分量，并愿意把那句话接下去；真正让人一点点放下防备的，也往往就是这一小步。"
        return "很多关系真正让人清醒的，不是某次嘴上说得难不难听，而是回应只停在表面，顺序、追问和心力总没有真正落到你这里；真正让人慢慢站稳的，也是从这里开始不再替这些落差找补。"
    if _uses_relationship_aftercare_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "一段关系会慢慢变冷，常常是因为争执过后，总是同一个人留在原地处理沉默、试探气氛，再把情绪和日常接回去。"
    if _uses_resilience_reconstruction_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正难的，不只是命运下手太重，而是长期疼痛、训练消耗和外界定义都在往下拽，人还得决定自己不被它们收走。"
    if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "最难的，从来不是承认自己也会慌，而是在回应还没到来之前，先把能处理的事放回手里，也把该求助的话说清楚。"
    if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
        return "真正把人困住的，不是没有答案，而是总把舍不得放手误认成还有希望。"
    if "边界" in topic_angle:
        return "真正把人拖住的，往往不是一开始就遇错了人，而是明明已经委屈了，还是会下意识先把自己往后放。"
    if "情绪" in topic_angle:
        if primary_pressure_cue and secondary_pressure_cue:
            return f"真正麻烦的，不是人一时状态差，而是 `{primary_pressure_cue}` 已经冒出来了，却还会一路拖到 `{secondary_pressure_cue}` 这种更重后果。"
        if primary_pressure_cue:
            return f"真正麻烦的，不是人一时状态差，而是 `{primary_pressure_cue}` 这种信号已经冒出来了，却还在被继续压下去。"
        return "那些失去电量的迹象，往往很早就开始一点点积着。"
    return f"把 {topic_title} 背后的自我亏欠、失去感和现实压力讲清楚。"


def _build_emotional_path(
    *,
    topic_angle: str,
    structure_mode: str,
    pressure_reference_cues: list[str] | None = None,
    response_priority_followup_variant: bool = False,
) -> str:
    if structure_mode == "pressure_interface_direct":
        cue = (pressure_reference_cues or [None])[0]
        if cue:
            return f"先让读者认出 `{cue}` 这种已经在出代价的信号，再看类似接口怎样一点点堆出更大的失序。"
        return "先让读者认出哪些事被顺手往后挪，再看这些小接口怎样一点点堆出更大的代价。"
    if structure_mode == "everyday_warmth_return":
        return "先认出人为什么总把重要感押在更大的目标上，再看一顿饭、一次回家、有人惦记这些不起眼的日常，是怎样在慢下来以后重新显出分量的。"
    if structure_mode == "inner_settlement":
        return "先认出那颗心为什么总悬着、总想先把一切想稳，再看人怎样从反复较劲里慢慢松下来，重新住回一餐一饮和眼前的日常。"
    if structure_mode == "self_worth_rebuild":
        return "先认出一个人为什么总把迁就误认成懂事、把示好误认成在乎，再看边界、标准和体面怎样在一次次退让里被放低；最后落到怎样重新尊重自己，把分量慢慢收回来。"
    if structure_mode == "trust_boundary":
        return "先认出信任从放心到裂开的那一下，再看一句谎言、一次隐瞒怎样让心安松动；最后落到坦诚、交代和说到做到怎样把关系重新托稳。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "先认出为什么轻互动不少、人却还是会悬着；再看一句追问、一次补问和一次被认真听懂怎样把人从硬撑里轻轻接住；最后落到真正的关心原来可以被认出来，也值得被珍惜。"
        return "先认出表层热闹为什么会被误认成在乎，再看顺序、追问和回头动作怎样一点点把真实分量露出来；最后落到不再靠猜测维持位置感，而是把心力留给真正愿意回应的人。"
    if structure_mode == "relationship_aftercare":
        return "先认出争执过后最难熬的，不只是那场冲突本身，而是失望有没有被看见、关系有没有被接回去；再看人为什么会从还想沟通，慢慢退到不再开口。"
    if structure_mode == "resilience_reconstruction":
        return "先认出命运怎样把人逼到极限，再看她怎样在训练、疼痛和反复重来里一点点把自己重新托住，最后落到不肯被定义上。"
    if _uses_self_reliance_inward_support_mode(topic_title="", topic_angle=topic_angle, structure_mode=structure_mode):
        return "先认出想求助却迟迟没有回应的那一下失落，再看人怎样恢复判断、继续行动，也学会在合适的时候求助分担。"
    if structure_mode == "fragment_chain_observation":
        return "先让不同接口里的压力互相照见，再慢慢显出真正被牺牲掉的部分。"
    if _uses_broad_emotional_release_mode(topic_angle=topic_angle, structure_mode=structure_mode):
        return "先认出自己一直在和得不到的东西拉扯，再看为什么人总要等到透支之后才愿意停下。"
    if "边界" in topic_angle:
        return "先认出人为什么总把自己放轻，再看边界、标准和体面是怎样在一次次退让里往下掉的。"
    if "情绪" in topic_angle:
        return "先认出身体和日常节奏已经在变慢，再看这些提醒为什么总被继续往后放。"
    if "自我" in topic_angle:
        return "先认出撑住的代价，再看为什么越想稳住越累。"
    return "先把当下卡点钉住，再顺着触发、反应和后续影响往前推进。"


def _build_opening_move(
    *,
    topic_title: str,
    topic_angle: str,
    tracked_article_scene: str,
    structure_mode: str,
    pressure_reference_cues: list[str] | None = None,
    response_priority_followup_variant: bool = False,
) -> str:
    if structure_mode == "pressure_interface_direct":
        cue = (pressure_reference_cues or [None])[0]
        if cue:
            return f"开头先落 `{cue}` 这种已经开始出代价的接口或身体后果，不要先抛终局问题或价值赦免。"
        return "开头先落一个已经开始出代价的接口：被改期的体检、没吃完的饭、没回的消息，或突然发钝的身体提醒；不要先抛终局问题或价值赦免。"
    if structure_mode == "everyday_warmth_return":
        return "开头先点破“更大的事未必更重要”这种误认，再用一个被长期放轻的饭桌、回家、说心里话或有人在等你这类日常接口托住判断；不要复述参考文现成的家庭动作，也不要铺成长场景。"
    if structure_mode == "inner_settlement":
        return "开头先落一个心还没完全安顿好、却已经想慢慢回位的现实接口：忙完以后还是坐不住、热闹散了才发现自己很久没松口气，或终于慢下来时心还没真正住回日子里。第一屏以短段为主，不要先写消息界面、关系结果、幸福定义或大道理。"

    if structure_mode == "self_worth_rebuild":
        return "开头先落一个自己其实并不想再配合、却还是顺手说了“都可以”“算了”“我没事”的现实接口；不要写消息打了又删、越想解释越说不出口，也不要先把第一屏抬成沟通技巧或关系判案。"

    if structure_mode == "trust_boundary":
        return "开头先落一个信任开始松动的现实接口：一句没有说清的话、一次被发现的隐瞒、一个让人心里一沉的细节；不要写成查手机、审问或回复速度比较。"

    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "开头先落一个轻描淡写的话有没有被听懂的小接口：一句“我没事”、一张随手发的照片、一次看似平常的状态更新；先让读者看见“谁只是路过一下、谁愿意停下来”，不要先把镜头压成回复速度比较或关系排位判断。"
        return "开头先落一个回应差别正在显形的小接口：消息停在那儿、评论只停在表层、有人会追问一句也有人顺手带过去；先让读者看见“谁真正停下来、谁只是路过一下”，不要先把题眼抬成关系总论或情绪判决。"
    if structure_mode == "relationship_aftercare":
        return "开头先落一个吵完之后还得照常上班、做饭、回消息，但胸口还紧着的小接口，不要先抽象讲“爱不爱”或“成熟关系”。"
    if structure_mode == "resilience_reconstruction":
        return "开头先落一个命运重击后的硬事实：手术台、泳池里多划11下、肩伤背痛这类抓手，不要先讲励志大道理，也不要滑成术后恢复稿。"
    if structure_mode == "self_reliance_inward_support":
        return "开头先落一个想求助却发现别人也在各自稳住生活的真实接口，让读者先看见处境，再尽早让判断、行动或分担显形。"
    if structure_mode == "emotional_engine_direct":
        if _uses_self_reliance_inward_support_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
            return "开头先落一个想求助却没有立刻被接住的真实处境，并让具体行动、判断或分担尽早显形；不要为这种结构模式另造一套固定前史。"
        if _uses_broad_emotional_release_mode(topic_title=topic_title, topic_angle=topic_angle, structure_mode=structure_mode):
            return "开头不要整段生活场景冷启动，先用一句会让人停一下的误认判断把读者拉进来；需要细节时，只留一个能挂住“继续投入”或“不肯松手”的小接口。"
        return "开头不要整段生活场景冷启动，先用终局问题、反常识判断、情绪命名或价值赦免把读者拉进来；需要细节时，只留能挂住判断的一个小接口。"
    if structure_mode == "fragment_chain_observation":
        if "推迟" in topic_angle or "往后放" in topic_angle or "等有空再说" in topic_angle:
            return "开头先落一个被顺手往后挪开的普通接口：没回的消息、改掉的预约、没吃完的饭或被推迟的电话，不要铺成完整小说场景。"
        return "开头先落一个最小但真实的生活碎片，不要先总括题眼，也不要把场景铺成完整短篇小说。"
    if "推迟" in topic_angle or "往后放" in topic_angle or "等有空再说" in topic_angle:
        return "开头先写一次消息停住、日程改期或身体提醒被顺手往后挪开的瞬间，不要先讲生活排序的大道理。"
    if tracked_article_scene:
        return "开头不要概括主题，先从一个新的生活瞬间切入，但不要复述参考文章现成处境。"
    if "边界" in topic_angle:
        return "开头先写一次自己其实并不想再退让，却还是顺手说了“都可以”“算了”的瞬间，不要先讲沟通道理或关系判案。"
    if "情绪" in topic_angle:
        return "开头先写身体或日常节奏出问题的一个小瞬间，不要先给“倦怠”下定义。"
    if "自我" in topic_angle:
        return "开头先写一个人表面平静、心里已经开始发紧的瞬间，不要先讲成长观点。"
    return f"开头先落一个能承住 `{topic_title}` 的具体动作入口。"


def _build_body_shift(
    *,
    topic_angle: str,
    core_conflict: str,
    structure_mode: str,
    pressure_reference_cues: list[str] | None = None,
    response_priority_followup_variant: bool = False,
) -> str:
    if "胃口变差" in topic_angle or "作息发乱" in topic_angle or "没耐心" in topic_angle or "负荷" in topic_angle:
        return "中段先拆生活接口为什么长期超负荷，再讲人为什么会把身体提醒放到所有事情后面。"
    if structure_mode == "pressure_interface_direct":
        cues = pressure_reference_cues or []
        if len(cues) >= 2:
            return f"中段沿着 `{cues[0]}` 到 `{cues[1]}` 这类代价链推进：哪件事先被顺手往后挪，当时怎么处理，后面又怎样追到账上。"
        if cues:
            return f"中段沿着 `{cues[0]}` 这条代价线推进：哪件事先被顺手往后挪，当时怎么处理，后面又留下什么新的失序。"
        return "中段沿着 1 到 2 条压力链推进：哪件事先被顺手往后挪，当时怎么处理，后面又留下什么代价、误差或新的失序。"
    if structure_mode == "everyday_warmth_return":
        return "中段先拆成就、体面、宏大目标为什么会在某个阶段突然祛魅，再把家人平安、朋友仍在、有家可回和日常烟火的分量接回来，让读者看见真正托住生活的到底是什么。"
    if structure_mode == "inner_settlement":
        return "中段先拆人为什么总把心安寄托在结果、标准答案或外部确定感上；再写人怎样从现实余波里慢慢回稳，把心一点点放回眼前正在过的生活。前半篇至少要长出 1 句贴着处境自己冒出来的人话，让读者先被理解，再慢慢被安放。"
    if structure_mode == "self_worth_rebuild":
        return "中段先拆一个人为什么总把迁就误认成懂事、把示好误认成在乎，再写边界、标准和体面是怎样在一次次退让里被放低；后半程把判断落回尊重自己、守住边界和重新把自己放回前面。"
    if structure_mode == "trust_boundary":
        return "中段先拆信任背后那份交出去的心安；再写谎言和隐瞒怎样让人从放心变成不安，后半篇把判断落回坦诚、交代和日常里的说到做到。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "中段先拆为什么表面互动会让人误以为自己已经被在意，再写真正让心安落下来的，是有人愿意停下来读懂言外之意、顺着情绪多走一步；后半篇把判断落回被理解为什么稀缺，也落回双向珍惜和关系里的安稳感。"
        return "中段先拆表层回应为什么常常会被误认成在乎，再写顺序、追问、回头动作和投入意愿怎样把真实位置慢慢暴露出来；后半篇把判断落回位置感怎么回正、心力怎样慢慢收回到真正值得的人和自己身上。"
    if structure_mode == "relationship_aftercare":
        return "中段先写每次吵完谁先把话咽回去、谁先恢复正常、谁先试探气氛，再写长期单人善后怎样让表达欲、期待感和安全感一点点退掉。"
    if structure_mode == "resilience_reconstruction":
        return "中段先拆长期疼痛和训练代价怎样一遍遍逼人重来，再写她为什么没有把残缺、低谷或外界定义收成自我结论。"
    if structure_mode == "self_reliance_inward_support":
        return "中段先拆为什么成年人想求助时常常也会看见别人的难处；再写一个人怎样先稳住判断和行动，慢慢走到向内求、自救自渡，也能在合适的时候求助分担。"
    if structure_mode == "emotional_engine_direct":
        if _uses_self_reliance_inward_support_mode(topic_title="", topic_angle=topic_angle, structure_mode=structure_mode):
            return "中段先拆为什么想求助时也会看见别人的难处，再写成年人怎样恢复判断、继续行动，慢慢走到向内求冷静，也在合适的时候求助分担。"
        if _uses_broad_emotional_release_mode(topic_angle=topic_angle, structure_mode=structure_mode):
            return "中段先拆这种误认是怎样长出来的：人为什么总以为再坚持一点就会圆满，又为什么总要停下来以后，才看见已经拥有的部分。"
        return "中段先拆情绪发动机：人为什么总在失去后才懂得拥有，又为什么会把照顾自己放到最后。"
    if structure_mode == "fragment_chain_observation":
        return "中段围绕同一个问题串起 2 到 4 个现实接口，让每个碎片各自承担不同压力：有人际回应，有身体提醒，也有被往后挪开的日常动作，不要平均写成并列分论点。"
    if "边界" in topic_angle:
        return "中段先拆人为什么总把迁就误认成懂事，再进入边界、标准和体面是怎样在一次次退让里被放低的。"
    if "情绪" in topic_angle:
        return "中段先写人是怎么一点点变慢的，再讲为什么她还会误以为自己只是状态不好。"
    if "自我" in topic_angle:
        return "中段先写撑住这件事的代价，再转到为什么这种用力方式会把人拖得更累。"
    return f"中段不要平铺讲道理，要围绕 `{core_conflict}` 完成一次从场景到判断的推进。"


def _build_ending_move(
    topic_angle: str,
    structure_mode: str,
    *,
    response_priority_followup_variant: bool = False,
) -> str:
    if structure_mode == "pressure_interface_direct":
        return "结尾回到一个还没完全处理完的普通接口或轻微决定，不抛万能答案，也不写祝福式收束。"
    if structure_mode == "everyday_warmth_return":
        return "结尾回到一个具体回温动作上：一顿热饭、一次回家、有人还在说话或心终于放下来的那一下，让分量自然落下来，不要写成身体告诫、关系排序或口号式收束。"
    if structure_mode == "inner_settlement":
        return "结尾回到一个心终于有地方放的小动作：把饭认真吃完、把脚步慢下来、坐一会儿也不再着急，或者终于能安静顺一口气；最后最好留一句短而轻的人话，让人感觉日子又能住进去，不要写成万能祝福或人生标准答案。"
    if structure_mode == "self_worth_rebuild":
        return "结尾回到一个门槛重新被抬高、边界重新立住或顺手退让终于停下来的小动作上，不要写成控诉、翻旧账或“谁配不上你”的宣判。"
    if structure_mode == "trust_boundary":
        return "结尾回到一个重新说清、主动交代或把答应过的事做到的小动作上，让信任回到日常里，不要写成审判、查岗或万能祝福。"
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return "结尾回到一个很小却很暖的被理解动作上：一句补问、一次记得、一次没有把你轻轻带过；让人读完感到真正的关心是可以被认出来、也值得被珍惜，不要收成关系排位或输赢判断。"
        return "结尾回到一个很小却很清楚的回应判断上：不再替那些停在表面的互动找补，把心力慢慢收回自己和真正愿意回应的人身上；让人读完更清醒也更轻一点，不要写成万能情感鸡汤或高位宣判。"
    if structure_mode == "relationship_aftercare":
        return "结尾回到一个还没被接住的小动作、沉默或没等来的回应上，不要写成万能关系鸡汤。"
    if structure_mode == "resilience_reconstruction":
        return "结尾回到一个还在继续的训练动作、身体余波或不肯松掉的念头上，不写成励志口号，也不写成自我照料宣言。"
    if structure_mode == "self_reliance_inward_support":
        return "结尾回到一个已经让日子重新动起来的小动作、现实判断或明天的第一件事上，让人感觉外面也许还在忙，但自己已经能先把这一程走稳。"
    if structure_mode == "emotional_engine_direct":
        if _uses_self_reliance_inward_support_mode(topic_title="", topic_angle=topic_angle, structure_mode=structure_mode):
            return "结尾回到一个已经让日子重新动起来的小动作、现实判断或明天的第一件事上，让人感觉外面也许还在忙，但自己已经能先把这一程走稳。"
        if _uses_broad_emotional_release_mode(topic_angle=topic_angle, structure_mode=structure_mode):
            return "结尾给读者一个明确的价值赦免和现实答案：停下来不是失去，是把心力收回来。"
        return "结尾给读者一个明确的价值赦免和现实答案：不必再把自己排到最后。"
    if structure_mode == "fragment_chain_observation":
        return "结尾回到其中一个还没完全处理完的小动作或未回的接口，停在那里，不要写成总结清单、三连问或温柔祝福。"
    if "边界" in topic_angle:
        return "结尾回到一个门槛重新被抬回去、顺手退让终于停下来的小动作，不要写成关系励志口号。"
    if "情绪" in topic_angle:
        return "结尾回到一个允许自己慢下来的动作，不要写成瞬间满血复活。"
    if "自我" in topic_angle:
        return "结尾回到承认疲惫后的一个轻动作，不要写成重新变强的宣言。"
    return "结尾回到人物处境里的一个更小动作，不要口号式升华。"


def _extract_reference_blocks(reference_body_markdown: str) -> list[str]:
    text = reference_body_markdown.strip()
    if not text:
        return []
    blocks: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        normalized = re.sub(r"^\s{0,3}#{1,6}\s*", "", block).strip()
        if normalized:
            blocks.append(normalized)
    return blocks


def _build_reference_article_fingerprint(
    *,
    structure_mode: str,
    reference_body_markdown: str,
    reference_summary: str,
    reference_analysis_theme: str,
    reference_analysis_core_conflict: str,
    reference_analysis_emotional_exit: str,
    reference_analysis_opening_pattern: str,
    response_priority_followup_variant: bool = False,
) -> ReferenceArticleFingerprint:
    blocks = _extract_reference_blocks(reference_body_markdown)
    focus_corpus = " ".join(
        blocks[:6]
        + [
            reference_summary,
            reference_analysis_theme,
            reference_analysis_core_conflict,
            reference_analysis_emotional_exit,
            reference_analysis_opening_pattern,
        ]
    )
    full_corpus = " ".join(
        [
            reference_body_markdown,
            reference_summary,
            reference_analysis_theme,
            reference_analysis_core_conflict,
            reference_analysis_emotional_exit,
            reference_analysis_opening_pattern,
        ]
    )
    ranked_groups: list[tuple[int, str]] = []
    for group, keywords, minimum_hits in _REFERENCE_FINGERPRINT_GROUP_RULES:
        focus_hits = _count_keyword_hits(focus_corpus, keywords)
        full_hits = _count_keyword_hits(full_corpus, keywords)
        if focus_hits >= minimum_hits or (focus_hits + full_hits) >= minimum_hits + 1:
            ranked_groups.append((focus_hits * 2 + full_hits, group))

    if not ranked_groups:
        fallback_group = ""
        if structure_mode == "everyday_warmth_return":
            fallback_group = "home_return"
        elif structure_mode == "inner_settlement":
            fallback_group = "heart_settlement"
        elif structure_mode == "self_reliance_inward_support":
            fallback_group = "self_support"
        elif structure_mode == "relationship_aftercare":
            fallback_group = "aftercare_conflict"
        elif structure_mode == "response_priority":
            fallback_group = "response_followup_detail" if response_priority_followup_variant else "response_priority_detail"
        elif structure_mode == "resilience_reconstruction":
            fallback_group = "resilience_body"
        if fallback_group:
            ranked_groups.append((1, fallback_group))

    if response_priority_followup_variant:
        ranked_groups = [(score, group) for score, group in ranked_groups if group != "response_priority_detail"]
        has_followup_group = any(group == "response_followup_detail" for _, group in ranked_groups)
        if not has_followup_group:
            ranked_groups.append((2, "response_followup_detail"))

    ranked_groups.sort(key=lambda item: (-item[0], item[1]))
    groups = tuple(group for _, group in ranked_groups[:3])
    first_blocks = blocks[:6]
    has_dialogue = any(any(token in block for token in ("“", "”", "说", "问", "回", "喊", "念叨")) for block in first_blocks)
    has_object_residue = any(any(token in block for token in _REFERENCE_OBJECT_RESIDUE_KEYWORDS) for block in first_blocks)
    has_time_marker = any(any(token in block for token in _REFERENCE_TIME_MARKER_KEYWORDS) for block in first_blocks)
    return ReferenceArticleFingerprint(
        groups=groups,
        has_dialogue=has_dialogue,
        has_object_residue=has_object_residue,
        has_time_marker=has_time_marker,
    )


def _build_reference_specific_scene_requirements(reference_fingerprint: ReferenceArticleFingerprint) -> list[str]:
    lines: list[str] = []
    for group in reference_fingerprint.groups:
        if group == "responsibility_shelter":
            lines.extend(
                [
                    "前六段优先放进 1 个来电、日历安排、复查预约、请假前的协调或家里临时有事的现实接口，让责任先落地，不要直接夸苦难有意义。",
                    "中后段保住 1 个父母、孩子、伴侣或家里安稳正在被托住的回温动作，让辛苦怎样变得值得被看见。",
                ]
            )
        elif group == "home_return":
            lines.extend(
                [
                    "前六段优先放进 1 个像回家开门、灯还亮着、饭桌还热着这种家里日常接口，不要刚起笔就空着讲珍惜。",
                    "中后段保住 1 个有人应声、有人等你或有人愿意一起把日子过下去的陪伴动作。",
                ]
            )
        elif group == "child_waiting":
            lines.extend(
                [
                    "前六段优先放进 1 个放学、门口、画纸或扑过来的小动作接口，让珍贵先被看见。",
                    "中后段保住 1 个被等着、被认出来或家里有人在意你回来的回温动作。",
                ]
            )
        elif group == "weather_care":
            lines.extend(
                [
                    "前六段优先放进 1 个天气预报、来电叮嘱、异地牵挂这种被惦记接口，不要把温暖写成空话。",
                    "中后段保住 1 个坏天气里心慢慢松下来、日子重新被托住的回温动作。",
                ]
            )
        elif group == "stage_node":
            lines.extend(
                [
                    "前六段优先放进 1 个阶段节点接口，比如翻到某张清单、某个月份或对着目标进度停住的那一下。",
                    "中段保住 1 个没完成的具体项和 1 次差点给自己打低分的当场反应。",
                ]
            )
        elif group == "heart_settlement":
            lines.extend(
                [
                    "前六段优先放进 1 个一餐一饮、一呼一吸、把心放回今天这种回稳接口，不要空着讲心安。",
                    "中后段保住 1 个普通安排重新有了分量的动作，让心落下来是能被看见的。",
                ]
            )
        elif group == "old_object_regret":
            lines.extend(
                [
                    "前六段优先放进 1 个旧物、旧衣、相册或聊天记录把人拽回去的现实接口，不要一上来就总结释怀。",
                    "中后段保住 1 个站住、发呆、摩挲或反复设想当初如果怎样的动作余波。",
                ]
            )
        elif group == "office_scene":
            lines.extend(
                [
                    "前六段优先把会议室、方案、投影，或散会后还坐在原位的那一下写出来，不要把职场现场蒸发掉。",
                    "中段保住 1 句本来要说却又咽回去的话，和 1 处事后补救的动作残留。",
                ]
            )
        elif group == "transit_unsent":
            lines.extend(
                [
                    "前六段优先把地铁口、接驳车、围巾，或手机停在那句没发出去的话上写出来。",
                    "中段保住 1 个上车以后谁都没再提、关系慢慢空下来的余波动作。",
                ]
            )
        elif group == "response_followup_detail":
            lines.extend(
                [
                    "前六段优先放进 1 个一句轻描淡写的话有没有被听懂的接口，比如一张随手发的照片、一次评论或一句“我没事”。",
                    "中段保住 1 处有人停下来多问一句、或把你没说完的话接下去的动作差别，不要先下关系排名。",
                ]
            )
        elif group == "response_priority_detail":
            lines.extend(
                [
                    "前六段优先放进 1 个消息、评论、回电、追问或碎片时间被给出去的回应接口。",
                    "中段保住 1 处只停在表层和愿意继续往前问一句之间的具体落差，不要先下关系结论。",
                ]
            )
        elif group == "aftercare_conflict":
            lines.extend(
                [
                    "前六段优先放进 1 个吵完以后空掉、沉下来或没人回来修复的现场接口。",
                    "中段保住 1 个谁回来沟通、谁继续沉默、失望留在哪边发酵的善后动作。",
                ]
            )
        elif group == "resilience_body":
            lines.extend(
                [
                    "前六段优先放进 1 个手术、训练、疼痛余波或重新适应身体限制的现场接口。",
                    "中后段保住 1 个继续练下去、继续重建或拒绝被定义的现实动作。",
                ]
            )
        elif group == "self_support":
            lines.extend(
                [
                    "前六段优先放进 1 个想求助却看见别人也各自有难处的接口，让正向动作尽早出现。",
                    "中段保住 1 个恢复判断、继续行动或主动求助分担的动作。",
                ]
            )
        elif group == "supportive_softness":
            lines.extend(
                [
                    "前六段优先放进 1 个一句道歉就算了、总先顾别人感受的柔软接口，不要直接下性格结论。",
                    "中后段保住 1 个被珍惜或被忽略的动作差别，让在乎不是抽象词。",
                ]
            )
        elif group == "endings_acceptance":
            lines.extend(
                [
                    "前六段优先放进 1 个还想要交代、还在替一段相遇追完整定义的接口，不要直接写成看开了。",
                    "中后段保住 1 个终于肯认领得到过什么、并把自己从亏欠叙事里慢慢松开的转身动作。",
                ]
            )
    return merge_unique_lines(lines, [])


def _build_reference_specific_quotable_seeds(
    reference_fingerprint: ReferenceArticleFingerprint,
) -> list[str]:
    seeds: list[str] = []
    for group in reference_fingerprint.groups:
        if group == "responsibility_shelter":
            seeds.extend(["肩上有责任的人，心里也要留一盏灯", "你为家多想的每一步，都会慢慢把日子托稳"])
        elif group == "home_return":
            seeds.extend(["回到家那一刻，才知道自己真正想要什么", "原来把人托住的，是这些小安稳"])
        elif group == "child_waiting":
            seeds.extend(["有人在门口等你，日子就没那么冷", "最能让人回神的，常是那一眼认出的奔向"])
        elif group == "weather_care":
            seeds.extend(["原来最能托住人的，是还有人在替你惦记天气", "坏天气里，心也能被一句叮嘱照亮"])
        elif group == "stage_node":
            seeds.extend(["几项空着，不等于这一程白走", "把力气收回眼前，人才走得下去"])
        elif group == "heart_settlement":
            seeds.extend(["把心放回今天，脚下才会慢慢顺起来", "今晚不必把所有事都想明白"])
        elif group == "old_object_regret":
            seeds.extend(["放下不是忘记，是把心从过去里慢慢松出来", "旧东西会把人拽回去，但路还是得朝前走"])
        elif group == "office_scene":
            seeds.extend(["不是没想法，是总在现场里先把自己撤回", "那句没说出口的话，后来会变成很长的自我收缩"])
        elif group == "transit_unsent":
            seeds.extend(["真正把人拉远的，常是那句最后还是没问出口的话", "车开走了，话也跟着停在了原地"])
        elif group == "response_followup_detail":
            seeds.extend(["你说“我没事”时，有人听出了你其实很累", "那句补问落下来，心里悬着的地方会先松一下"])
        elif group == "response_priority_detail":
            seeds.extend(["时间给了谁，位置就偏向谁", "愿意多问一句的人，才是真的把你放在心上"])
        elif group == "aftercare_conflict":
            seeds.extend(["关系值不值得，常看吵完以后", "失望最怕的，不是争执，是没人回来接住"])
        elif group == "resilience_body":
            seeds.extend(["命运给了重击，也没收走继续重建的力气", "每一次疼痛过去，都是重新定义自己的那一下"])
        elif group == "self_support":
            seeds.extend(["把力气收回眼前，人就会一点点稳下来", "真正的成熟，是先把能做的那一步接住"])
        elif group == "supportive_softness":
            seeds.extend(["心软不是没分寸，是因为太在乎", "愿意包容你的人，往往是真的把你放在心上"])
        elif group == "endings_acceptance":
            seeds.extend(["承认结束，不是否定相遇", "把温暖留在心里，人才能继续往前走"])
    return merge_unique_lines(seeds, [])


def _build_reference_specific_texture_notes(reference_fingerprint: ReferenceArticleFingerprint) -> list[str]:
    notes: list[str] = []
    for group in reference_fingerprint.groups:
        if group == "responsibility_shelter":
            notes.append("真人抓手：优先保留来电、日历安排、请假前协调、先把家里理顺的动作和一句像“我来安排”这样当场会说的话，不要只剩中年辛苦的大判断。")
        elif group == "home_return":
            notes.append("真人抓手：优先保留回家、饭桌、灯还亮着和有人应声这类生活细节，不要只剩珍惜家人的大道理。")
        elif group == "child_waiting":
            notes.append("真人抓手：优先保留放学、画纸、步子快一点、扑过来这类被等着的动作，不要把温暖写成概念。")
        elif group == "weather_care":
            notes.append("真人抓手：优先保留天气、来电、叮嘱和异地牵挂，不要把被惦记写成抽象温暖。")
        elif group == "stage_node":
            notes.append("真人抓手：优先保留清单、时间节点、没划掉的几项和当场自我清算，不要直接讲阶段感悟。")
        elif group == "heart_settlement":
            notes.append("真人抓手：优先保留一餐一饮、一呼一吸、坐下来慢一点这类回稳动作，不要全写成心态说明。")
        elif group == "old_object_regret":
            notes.append("真人抓手：优先保留旧物、摩挲、发呆、阳台或垃圾桶旁停住这类物件余波。")
        elif group == "office_scene":
            notes.append("真人抓手：优先保留投影、屏幕、资料、水杯和散会后的停留，不要把职场现场蒸发掉。")
        elif group == "transit_unsent":
            notes.append("真人抓手：优先保留地铁口、围巾、没发出去那句话和上车后的沉默余波。")
        elif group == "response_followup_detail":
            notes.append("真人抓手：优先保留评论、追问、读懂言外之意和那句被轻轻接住的话，不要滑回回消息排序。")
        elif group == "response_priority_detail":
            notes.append("真人抓手：优先保留回消息、评论、追问、点赞、碎片时间这些回应差别，不要直接宣判关系。")
        elif group == "aftercare_conflict":
            notes.append("真人抓手：优先保留吵后沉默、没人回来、谁先低头这些善后动作，不要只谈对错。")
        elif group == "resilience_body":
            notes.append("真人抓手：优先保留手术、训练、疼痛和重复适应的身体细节，不要把人直接写成励志标签。")
        elif group == "self_support":
            notes.append("真人抓手：优先保留想求助却看见别人也有难处的接口，再写人怎样通过具体行动、判断或求助分担慢慢自稳。")
        elif group == "supportive_softness":
            notes.append("真人抓手：优先保留一句道歉、一次原谅、一次顺手让步这类柔软接口，不要直接下性格结论。")
        elif group == "endings_acceptance":
            notes.append("真人抓手：优先保留还想要交代和终于肯认领得到过什么这两个心理转折，不要强催放下。")

    if reference_fingerprint.has_dialogue:
        notes.append("真人抓手：能保一句当场会说出来的话，就别把它全部改写成作者替读者总结。")
    if reference_fingerprint.has_object_residue:
        notes.append("真人抓手：优先保留 1 个物件细节，让情绪从物件后面自己冒出来。")
    if reference_fingerprint.has_time_marker:
        notes.append("节奏抓手：可以保 1 个具体时间节点或前后顺序，让情绪变化长在过程里。")
    return merge_unique_lines(notes, [])


def _build_reference_specific_realism_hint(reference_fingerprint: ReferenceArticleFingerprint) -> str:
    detail_fragments: list[str] = []
    for group in reference_fingerprint.groups:
        if group == "responsibility_shelter":
            detail_fragments.append("1 个来电、日历安排或请假前协调接口，和 1 处家里安稳被护住的回温动作")
        elif group == "home_return":
            detail_fragments.append("1 个回家/饭桌/灯还亮着的接口和 1 处有人应声的余波")
        elif group == "child_waiting":
            detail_fragments.append("1 个放学或门口等待的动作和 1 个被认出来的回温细节")
        elif group == "weather_care":
            detail_fragments.append("1 个天气或来电细节、1 句叮嘱和 1 处坏天气里的心绪回温")
        elif group == "stage_node":
            detail_fragments.append("1 个阶段节点、1 个没完成的具体项和 1 次当场自我打分的反应")
        elif group == "heart_settlement":
            detail_fragments.append("1 个普通安排、1 处呼吸或吃饭动作和 1 次心慢慢落下来的停顿")
        elif group == "old_object_regret":
            detail_fragments.append("1 个旧物接口、1 处摩挲或发呆动作和 1 个反复设想当初的回勾")
        elif group == "office_scene":
            detail_fragments.append("1 个现场物件、1 句没说出口的话和 1 处散会后的动作残留")
        elif group == "transit_unsent":
            detail_fragments.append("1 个交通现场、1 处屏幕停留和 1 个没问出口的句子余波")
        elif group == "response_followup_detail":
            detail_fragments.append("1 个轻描淡写的话被听懂的接口、1 处追问或补问和 1 段情绪被放稳的落点")
        elif group == "response_priority_detail":
            detail_fragments.append("1 个消息或评论接口、1 处追问或没追问的差别和 1 段顺序落差")
        elif group == "aftercare_conflict":
            detail_fragments.append("1 个吵后沉默接口、1 个善后动作和 1 处失望继续发酵的余波")
        elif group == "resilience_body":
            detail_fragments.append("1 个身体代价、1 个重复训练动作和 1 处不肯松掉的念头")
        elif group == "self_support":
            detail_fragments.append("1 个想求助却看见别人也有难处的接口、1 个恢复判断的动作和 1 个求助或分担后的余波")
        elif group == "supportive_softness":
            detail_fragments.append("1 次顺手让步、1 句道歉后的原谅和 1 个被珍惜或被轻放的差别")
        elif group == "endings_acceptance":
            detail_fragments.append("1 个还想要交代的心理回勾和 1 个终于肯把相遇意义认领回来的转身")

    if not detail_fragments:
        if reference_fingerprint.has_dialogue:
            detail_fragments.append("1 句像真人当场会说出来的话")
        if reference_fingerprint.has_object_residue:
            detail_fragments.append("1 个能挂住情绪的物件接口")
        if reference_fingerprint.has_time_marker:
            detail_fragments.append("1 个具体时间节点或前后顺序")

    if not detail_fragments:
        return ""
    return "同时优先保住 " + "；".join(detail_fragments[:2]) + "。"


def _build_reference_specific_packaging_focus(reference_fingerprint: ReferenceArticleFingerprint) -> str:
    for group in reference_fingerprint.groups:
        if group == "responsibility_shelter":
            return "包装最好先抓肩上的责任、来电或日历里的安排，再带回家里安稳为什么会把人托住。"
        if group == "home_return":
            return "包装最好先抓回家、饭桌、灯还亮着这类小安稳，不要只剩珍惜家人的结论。"
        if group == "child_waiting":
            return "包装最好先抓放学、门口、画纸和那一下认出来的奔向，不要把温暖写成大词。"
        if group == "weather_care":
            return "包装最好先抓天气预报、来电叮嘱和有人替你惦记这类小事。"
        if group == "stage_node":
            return "包装最好先抓年中、清单、没划掉的几项和阶段自我清算的那一下。"
        if group == "heart_settlement":
            return "包装最好先抓一餐一饮、一呼一吸和那颗心终于慢慢落回今天的过程。"
        if group == "old_object_regret":
            return "包装最好先抓旧物回勾、垃圾桶旁停住或聊天记录翻出来那一下。"
        if group == "office_scene":
            return "最好把会还没散、那句话却已经咽回去的那一下放到最前面，再把散会后的补救和位置变化带出来。"
        if group == "transit_unsent":
            return "最好把地铁口那句没问出口的话、上车后的安静和后面慢慢长出来的距离连起来。"
        if group == "response_followup_detail":
            return "包装最好先抓一句轻描淡写的话被听懂、有人停下来多问一句和那种被理解后的安稳。"
        if group == "response_priority_detail":
            return "包装最好先抓消息、评论、追问、红灯几十秒或顺序落差，不要先空讲在乎。"
        if group == "aftercare_conflict":
            return "包装最好先抓吵完以后有没有人回来，不要只写吵架感悟。"
        if group == "resilience_body":
            return "包装最好先抓手术、训练和疼痛代价，不要先压成励志口号。"
        if group == "self_support":
            return "包装最好先抓参考文里的现实触发点，再带出理清顺序、把今天接稳的回正动作。"
        if group == "supportive_softness":
            return "包装最好先抓一句道歉就算了、总把别人放前面的柔软接口。"
        if group == "endings_acceptance":
            return "包装最好先抓还想要交代和终于肯认领相遇意义的那个转折。"
    return ""


def _build_reference_specific_packaging_hook(reference_fingerprint: ReferenceArticleFingerprint) -> str:
    for group in reference_fingerprint.groups:
        if group == "responsibility_shelter":
            return "先抓家里临时有事时那份先把顺序理清的认真，再带回原来很多辛苦最后都在把家里那点安稳托住。"
        if group == "home_return":
            return "先抓回到家那一刻的松动，再带回原来把人托住的是这些小安稳。"
        if group == "child_waiting":
            return "先抓那一下被认出来、被等着的动作，再把分量慢慢接回来。"
        if group == "weather_care":
            return "先抓一句普通叮嘱和坏天气里的来电，再带回被惦记为什么能把人托住。"
        if group == "stage_node":
            return "先抓翻到清单那一刻的自我打分，再带回几项空着不等于白走一程。"
        if group == "heart_settlement":
            return "先抓那颗心一直悬着的状态，再带回把心放回今天的回稳过程。"
        if group == "old_object_regret":
            return "先抓旧物把人拽回去的那一下，再带回放下不是忘记，而是继续往前。"
        if group == "office_scene":
            return "先抓会议室里那句没说出口的话，再带回长期让位怎样改写一个人的位置感。"
        if group == "transit_unsent":
            return "先抓地铁口那句没问出口的话，再带回关系为什么会在一次次算了里慢慢变淡。"
        if group == "response_followup_detail":
            return "先抓一句轻描淡写的话有没有被听懂，再带回真正的关心为什么总藏在那句追问里。"
        if group == "response_priority_detail":
            return "先抓表层回应和继续追问之间的落差，再带回心力给了谁、关系就偏向谁。"
        if group == "aftercare_conflict":
            return "先抓吵完以后空下来的那一下，再带回有没有人回来接住失望。"
        if group == "resilience_body":
            return "先抓命运重击和训练代价，再带回不被定义和继续重建。"
        if group == "self_support":
            return "先抓参考文里的现实触发点，再带回人怎样通过具体行动、判断或选择把日子稳稳接回来。"
        if group == "supportive_softness":
            return "先抓柔软被误读的那一下，再带回真正值得牵紧和珍惜的人。"
        if group == "endings_acceptance":
            return "先抓还想要交代的执念，再带回承认结束并不等于否定相遇。"
    return ""


def _build_writing_texture_notes(
    *,
    structure_mode: str,
    reference_body_markdown: str,
    reference_analysis_opening_pattern: str,
    reference_analysis_do_not_turn_into: str,
    reference_analysis_emotional_exit: str,
    reference_shell_signals: list[str] | None = None,
    reference_fingerprint: ReferenceArticleFingerprint | None = None,
) -> list[str]:
    blocks = _extract_reference_blocks(reference_body_markdown)
    shell_signals = reference_shell_signals or []
    notes = _build_reference_specific_texture_notes(reference_fingerprint or ReferenceArticleFingerprint())

    opening_pattern = _normalize_strategy_contract_text(reference_analysis_opening_pattern)
    if opening_pattern:
        if any(token in opening_pattern for token in ("场景", "现场", "偶遇", "会议室", "地铁口", "起笔")):
            notes.append("起笔方式：先给一个当下现场或小动作，再把判断慢慢提出来。")
        elif any(token in opening_pattern for token in ("引语", "一句话", "发问", "提问")):
            notes.append("起笔方式：可以先借一句会让人停一下的话起笔，但第二步要马上落回现实处境。")
        elif any(token in opening_pattern for token in ("阶段节点", "盘点", "半年", "年初", "清单")):
            notes.append("起笔方式：先落阶段节点或现实切面，再进入自我判断，不要空着讲心情。")
        else:
            notes.append("起笔方式：先给读者一个能看见的入口，再往判断里推进。")

    if blocks:
        first_blocks = blocks[:6]
        short_blocks = sum(1 for block in first_blocks if len(block) <= 36)
        long_blocks = sum(1 for block in first_blocks if len(block) >= 70)
        if short_blocks >= 3:
            notes.append("段落节奏：前半篇以短段推进为主，让识别和停顿自己冒出来，不要一上来就写成长整段抒情。")
        elif long_blocks >= 2:
            notes.append("段落节奏：先让一小段处境完整落地，再进入判断，不要把每段都削成同样长短。")
        else:
            notes.append("段落节奏：前半篇保持长短交替，让现场、判断和回神错开出现。")

        if any(any(token in block for token in ("“", "”", "说", "问", "回", "喊", "念叨")) for block in first_blocks):
            notes.append("真人抓手：优先保留一句对话、回话或嘴边那句没说满的人话，不要全改成作者代读者总结。")
        elif any(any(token in block for token in ("看见", "抬手", "停住", "转身", "坐", "翻到", "推开", "回家", "吃饭")) for block in first_blocks):
            notes.append("真人抓手：优先保留动作余波和物件接口，让情绪从动作后面长出来。")

    if "blessing_close" in shell_signals:
        notes.append("收束方式：不要照着祝福句收尾，最好停在一个已经发生的小动作或顺序变化上。")
    elif reference_analysis_emotional_exit.strip():
        notes.append("收束方式：把正向出口落回现实余波，不要直接把结尾写成万能安慰。")
    else:
        notes.append("收束方式：结尾回到一个更轻但真实的落点，不要另补大而全的人生答案。")

    if structure_mode in {"scene_first_progression", "relationship_aftercare"}:
        notes.append("短句来源：可摘录句尽量从现场里那一下没说出口、没接住或慢半拍里长出来。")
    elif structure_mode in {"everyday_warmth_return", "inner_settlement"}:
        notes.append("短句来源：可摘录句尽量从回神、回稳或重新认出分量的那一下长出来。")
    else:
        notes.append("短句来源：可摘录句要从现实接口突然照见主题的那一下长出来，不要单独制造金句。")

    forbidden = _normalize_strategy_contract_text(reference_analysis_do_not_turn_into)
    if forbidden:
        notes.append(f"改写禁区：{forbidden}")

    return notes[:6]


def _looks_like_short_banner_block(block: str) -> bool:
    normalized = re.sub(r"\s+", "", block)
    if not (4 <= len(normalized) <= 18):
        return False
    if re.search(r"[。！？!?；;：:，,]", normalized):
        return False
    if normalized.startswith(("“", "\"", "'")):
        return False
    return True


def _has_fragment_chain_source(reference_body_markdown: str) -> bool:
    blocks = _extract_reference_blocks(reference_body_markdown)
    if not blocks:
        return False
    short_banners = sum(1 for block in blocks if _looks_like_short_banner_block(block))
    quoted_lines = sum(
        1
        for line in reference_body_markdown.splitlines()
        if re.match(r"^\s*[\"“].+[\"”]\s*$", line.strip())
    )
    return short_banners >= 3 or (short_banners >= 2 and quoted_lines >= 2)


def _build_structure_mode(
    *,
    source_mode: str,
    topic_angle: str,
    tracked_article_scene: str,
    reference_body_markdown: str,
    reference_summary: str = "",
    reference_structure_notes: str = "",
    reference_analysis_structure_mode: str = "",
) -> str:
    normalized = topic_angle.strip()
    if source_mode == "tracked_article":
        shell_signals = _extract_reference_shell_signals(reference_body_markdown)
        reference_has_pressure = _has_pressure_interface_summary(reference_summary) or _has_pressure_interface_reference(
            reference_body_markdown
        )
        reference_is_everyday_warmth_return = _has_everyday_warmth_return_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_inner_settlement = _has_inner_settlement_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_self_worth_rebuild = _has_self_worth_rebuild_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_response_priority = _has_response_priority_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_trust_boundary = _has_trust_boundary_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_supportive_appreciation = _has_supportive_appreciation_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_relationship_aftercare = _has_relationship_aftercare_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_self_reliance_inward_support = _has_self_reliance_inward_support_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_resilience_reconstruction = _has_resilience_reconstruction_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_emotional_release = _has_emotional_release_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_endings_acceptance = _has_endings_acceptance_reference(
            normalized,
            tracked_article_scene,
            reference_summary,
            reference_structure_notes,
            reference_body_markdown,
        )
        reference_is_scene_first_progression = _has_scene_first_progression_reference(
            normalized,
            reference_summary,
            reference_structure_notes,
        )
        reference_has_scene_first_body = _looks_like_scene_first_progression_body(reference_body_markdown)
        if reference_analysis_structure_mode:
            if reference_analysis_structure_mode == "response_priority" and reference_is_response_priority:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "trust_boundary" and reference_is_trust_boundary:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "supportive_appreciation" and reference_is_supportive_appreciation:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "relationship_aftercare" and reference_is_relationship_aftercare:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "inner_settlement" and reference_is_inner_settlement:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "self_worth_rebuild" and reference_is_self_worth_rebuild:
                return reference_analysis_structure_mode
            if (
                reference_analysis_structure_mode == "self_reliance_inward_support"
                and reference_is_self_reliance_inward_support
            ):
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "everyday_warmth_return" and reference_is_everyday_warmth_return:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "resilience_reconstruction" and reference_is_resilience_reconstruction:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "emotional_engine_direct" and reference_is_emotional_release:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "emotional_engine_direct" and reference_is_endings_acceptance:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "pressure_interface_direct" and reference_has_pressure:
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "fragment_chain_observation" and _has_fragment_chain_source(
                reference_body_markdown
            ):
                return reference_analysis_structure_mode
            if reference_analysis_structure_mode == "scene_first_progression" and (
                reference_is_scene_first_progression or reference_has_scene_first_body
            ):
                return reference_analysis_structure_mode
        if _has_fragment_chain_source(reference_body_markdown):
            return "fragment_chain_observation"
        if reference_is_everyday_warmth_return:
            return "everyday_warmth_return"
        if reference_is_inner_settlement:
            return "inner_settlement"
        if reference_is_self_worth_rebuild:
            return "self_worth_rebuild"
        if reference_is_self_reliance_inward_support:
            return "self_reliance_inward_support"
        if reference_is_trust_boundary:
            return "trust_boundary"
        if reference_is_response_priority:
            return "response_priority"
        if reference_is_supportive_appreciation:
            return "supportive_appreciation"
        if reference_is_relationship_aftercare:
            return "relationship_aftercare"
        if reference_is_resilience_reconstruction:
            return "resilience_reconstruction"
        if (
            reference_analysis_structure_mode == "emotional_engine_direct"
            and not reference_has_pressure
            and not reference_is_relationship_aftercare
            and not reference_has_scene_first_body
        ):
            return "emotional_engine_direct"
        if reference_is_scene_first_progression or reference_has_scene_first_body:
            return "scene_first_progression"
        if (
            (reference_is_emotional_release or reference_is_endings_acceptance)
            and not reference_has_pressure
            and not reference_is_relationship_aftercare
        ):
            return "emotional_engine_direct"
        if _has_pressure_interface_topic(normalized) or reference_has_pressure:
            return "pressure_interface_direct"
        return "emotional_engine_direct"
    scene_first_keywords = (
        "情绪",
        "耗尽",
        "报警",
        "开口",
        "解释",
        "边界",
        "失望",
        "推迟",
        "往后放",
        "等有空",
        "疲惫",
        "撑住",
        "稳住",
        "倦怠",
    )
    if tracked_article_scene or any(keyword in normalized for keyword in scene_first_keywords):
        if _has_self_worth_rebuild_reference(normalized, tracked_article_scene):
            return "self_worth_rebuild"
        if _has_self_reliance_inward_support_reference(normalized, tracked_article_scene):
            return "self_reliance_inward_support"
        return "emotional_engine_direct"
    return "emotional_engine_direct"


def _describe_structure_mode(
    structure_mode: str,
    *,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
    response_priority_followup_variant: bool = False,
) -> tuple[str, str]:
    if structure_mode == "fragment_chain_observation":
        return (
            "碎片回环观察推进",
            "围绕同一个问题串起 2 到 4 个现实接口，让每个碎片承担不同压力，不要压成单主角完整短篇，也不要平均拆成对称分论点。",
        )
    if structure_mode == "responsibility_shelter" or (
        structure_mode == "everyday_warmth_return" and everyday_warmth_variant == "responsibility_shelter"
    ):
        return (
            "责任托家回温推进",
            "先守住来电、账单、请假前协调、家里临时有事这类现实接口，再沿着为什么总是先把家里顺序理清、为谁多想一步、这些认真怎样慢慢落成一家人的安稳推进；不要滑成简单幸福、小确幸盘点或泛中年感慨。",
        )
    if structure_mode == "everyday_warmth_return":
        return (
            "日常价值回归推进",
            "先拆更大目标为什么会祛魅，再把饭桌、回家、陪人说话这些真正托人的日常分量接回来；手术、停下来或身体受挫只承担转折证据，不抢主线。",
        )
    if structure_mode == "inner_settlement":
        if inner_settlement_variant == "stage_restart":
            return (
                "阶段回望再出发推进",
                "先守住阶段节点上的自我盘点和误判，再沿着为什么总把没完成、没拥有和没赶上一起算成失败，写到眼前支撑怎样把人接回来、把力气还给下一步生活。",
            )
        return (
            "心安归位推进",
            "先守住那颗心一直没被安放好的当下接口，再沿着向外求稳到慢慢住回日常的路径推进，不写成关系等待、身体告警或幸福定义稿。",
        )
    if structure_mode == "self_worth_rebuild":
        return (
            "自我分量回收推进",
            "先守住一个明明不舒服却还是顺手退让的现实接口，再沿着为什么总把体谅和迁就走在前面，写到边界、标准和体面怎样被放低，以及人怎样把尊重和分量慢慢收回来。",
        )
    if structure_mode == "self_reliance_inward_support":
        return (
            "向内求自救推进",
            "先守住参考文里想求助却看见别人也各自承压的接口，再沿着恢复判断、继续行动和求助分担的过程推进，不写成表达退缩、求助技巧或泛独立宣言。",
        )
    if structure_mode == "trust_boundary":
        return (
            "信任边界修复推进",
            "先守住信任从放心到裂开的现实接口，再沿着谎言、隐瞒、心安松动和坦诚交代推进，让说到做到怎样重新托住关系从细节里长出来。",
        )
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            return (
                "轻互动读懂推进",
                "先守住被路过和被认真停下来之间的落差，再沿着评论、追问、补问和读懂言外之意往前推，让真正的关心怎样显形这件事从细节里自己长出来。",
            )
        return (
            "回应优先级推进",
            "先守住表层回应和真正接住之间的落差，再沿着回应动作、追问、时间投向和投入意愿往前推，让在乎程度怎样显形这件事从细节里自己长出来。",
        )
    if structure_mode == "supportive_appreciation":
        return (
            "柔软珍惜推进",
            "先把心软为什么常被误读讲清楚，再沿着体谅、包容和愿意在乎的分量往前推，让这份柔软为什么最值得被珍惜从细节里自己长出来。",
        )
    if structure_mode == "relationship_aftercare":
        return (
            "争吵后善后推进",
            "先守住争执过后的空白、沉默或回避接口，再顺着谁先把话咽回去、谁先恢复正常、谁先把场面接回去推进，让安全感变薄这件事从动作里自己显出来。",
        )
    if structure_mode == "resilience_reconstruction":
        return (
            "逆境重建推进",
            "先守住命运重击、身体限制或训练代价，再沿着疼痛、重复训练和拒绝被定义的反抗往前推，不写成术后恢复、自我照料或泛励志鸡汤。",
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
            "先抽出终局感、亏欠感、失去后的反省和价值赦免，再展开判断与现实答案；默认不靠整段生活场景带路，但允许点状现实细节承重。",
        )
    if structure_mode == "scene_first_progression":
        return (
            "场景优先推进",
            "先让一到两个连续场景带路，再逐步展开判断，不要直接平铺成对称分论点。",
        )
    return ("", "")


def _build_recomposition_recipe(
    *,
    structure_mode: str,
    topic_angle: str,
    everyday_warmth_variant: str = "",
    reference_shell_signals: list[str] | None = None,
    response_priority_followup_variant: bool = False,
) -> list[str]:
    opening_step = "标题和开头都换成新的现实入口：不用命令句，不直接复述题眼，先让一个具体接口、后果、身体提醒或当下卡点顶上来。"
    middle_step = "中段先把压力是怎么一点点堆起来的讲清楚，再补局部机制；不要按“观点一句 + 解释一句”的标准答案节拍平推。"
    ending_step = "结尾换成新的处境落点：可以停在余波、阻力或还没处理完的接口上，不提问、不列清单，也不要抛万能答案。"

    if structure_mode == "fragment_chain_observation":
        recipe = [
            opening_step,
            "前两段只守住一个被顺手推迟、取消、压下去或没接住的现实接口，不要立刻抬升成总论。",
            "中段改成“主接口继续发酵 + 两到三个回绕碎片补压力”的回环结构，不设并列小标题，不平均分三段讲道理。",
            "只在后半篇补一次机制说明，把为什么会这样贴着前文细节讲透一点，不要每个碎片后都单独补结论。",
            ending_step,
        ]
    elif structure_mode == "pressure_interface_direct":
        recipe = [
            opening_step,
            "前半篇先守住一个已经开始出代价的接口：被改期的体检、没回的消息、被压后的身体提醒，不要立刻抬成整篇总论。",
            "中段沿着 1 到 2 条压力链推进：哪件事先被往后放、当时怎样处理、后来又留下什么新的失序或代价。",
            "需要判断时，把判断压回事实、后果和当场反应里，不要排成“先摆现象，再补道理，再给答案”的成熟讲解稿。",
            ending_step,
        ]
    elif structure_mode == "responsibility_shelter" or (
        structure_mode == "everyday_warmth_return" and everyday_warmth_variant == "responsibility_shelter"
    ):
        recipe = [
            opening_step,
            "前半篇先守住责任落到日常里的现实重量：来电、账单、请假前协调、家里临时有事、先把顺序理清。不要一上来就空讲中年不容易，也不要滑成泛幸福回归。",
            "中段沿着“先把谁安顿好 -> 为什么总是自己多想一步 -> 这些认真怎样慢慢换来家里的踏实”推进，不要回到简单快乐、小确幸清单或苦难勋章叙事。",
            "后半篇把情绪带回父母安心、孩子底气、有人一起分担和那个一直用心的人也值得被照顾，不要改写成关系回应排序、身体告警或长期体谅善后稿。",
            ending_step,
        ]
    elif structure_mode == "everyday_warmth_return":
        recipe = [
            opening_step,
            "前半篇先守住“大事 / 成就 / 体面 / 向上奔跑”为什么会慢慢失重，不要一上来就滑进某段关系谁更委屈、谁在长期体谅的善后逻辑。",
            "中段沿着“宏大叙事祛魅 -> 眼前日常重新回到视野里 -> 吃饭、回家、有人惦记这些小事重新显出分量”推进，不要回收参考文那组高识别度家庭动作。",
            "不要把身体不适、手术或停下来写成主要问题，它们只负责提供转折证据；也不要把正文改写成“别人还在等你回应”的关系排序稿。",
            ending_step,
        ]
    elif structure_mode == "inner_settlement":
        recipe = [
            opening_step,
            "前半篇先守住一个心还没完全坐稳、也正在寻找归处的现实卡点：忙完以后突然坐不住、热闹散了才发现自己很久没松口气，或一次普通日常重新有了分量；不要一上来就滑去关系等待、身体告警或幸福公式。",
            "中段沿着“人为什么总把心安押给外部结果 -> 那颗心怎样慢慢松开 -> 人怎样把自己重新放回日常”推进，让回稳、放平和一餐一饮、一呼一吸彼此咬住。",
            "判断要压回心里的拉扯、现实余波和轻动作里，不要写成名言抚慰、祝福收束或空泛看开文。",
            ending_step,
        ]
    elif structure_mode == "self_worth_rebuild":
        recipe = [
            opening_step,
            "前半篇先守住一个自己其实并不舒服、却还是顺手退让的现实接口：说了“都可以”、替别人圆场、把要求收回去，或把标准悄悄往下调；不要滑成消息框停顿、谁先解释或关系审判。",
            "中段沿着“为什么总把迁就误认成懂事 -> 边界、标准和体面怎样在一次次退让里被放低 -> 人什么时候才认出轻慢已经发生”推进，让自我价值感和关系位置的变化从细节里自己长出来。",
            "后半篇要把回正动作写出来：分寸怎么慢慢回到自己手里，位置怎么不再随手后撤，尊重自己怎样开始替文章收口；不要把判断写成狠话宣言、翻旧账或一键离开的爽文。",
            ending_step,
        ]
    elif structure_mode == "self_reliance_inward_support":
        recipe = [
            opening_step,
            "前半篇先守住参考文章真正给出的现实触发点：可以是事情压到眼前、阶段节点、家庭责任、低谷判断、情绪回稳或具体行动。",
            "开头的现实接口要从参考文分析里来，让主镜头更早落到当事人的判断、行动或回稳细节上。",
            "中段沿着“处境怎样让人差点乱了顺序 -> 哪个判断或动作让人回神 -> 现实怎样一点点被接住”推进，让回稳动作和行动感自己长出来。",
            "最迟在前半篇后段就要给出一个已经发生的正向动作、选择或判断，比如把事情排清、把眼前事做完、照顾好一顿饭、把明天缩成第一步；不要一直停在那一下空落里打转。",
            "回稳动作要像从处境里自然长出来，不要排成“先做这个、再做那个”的匀速步骤，也别让“先……”连续顶着句子往前走。",
            "不要把自救自渡写成硬扛、拒绝求助或高位打鸡血；主线必须留在参考文的具体自我支撑方式，以及它怎样给人带回力量。",
            "结尾不要收在悬着的情绪上，要收在已经发生的小动作、顺序恢复和继续过日子的踏实感上。",
            ending_step,
        ]
    elif structure_mode == "trust_boundary":
        recipe = [
            opening_step,
            "前半篇先守住一个信任开始松动的现实接口：一句没说清的话、一次隐瞒被发现、一个本来可以坦诚却被含糊带过的细节；不要写成查手机、审问或回消息速度比较。",
            "中段沿着“原本放心 -> 谎言或隐瞒出现 -> 心安裂开 -> 人开始不敢再完全相信”推进，让信任的代价从细节里自己显出来。",
            "后半篇必须把回正动作写出来：该交代的时候交代，该说清的时候说清，答应过的事尽量做到；不要只停在请珍惜、别辜负这类口号。",
            "结尾收在一个坦诚或说到做到的小动作上，让信任回到日常，不要收成查岗控制、关系审判或万能祝福。",
            ending_step,
        ]
    elif structure_mode == "response_priority":
        if response_priority_followup_variant:
            recipe = [
                opening_step,
                "前半篇先守住一个轻互动差别里的现实接口：一句“我没事”有没有被听懂、一张随手发的照片有没有人停下来多看一眼、一次评论有没有继续往前问。",
                "中段沿着“表面热闹为什么会让人误以为自己已经被在意 -> 真正的关心怎样藏在追问、补问和读懂里 -> 被理解为什么会把人轻轻放稳”推进，让安稳感从接口里自己长出来。",
                "不要把正文滑成等回复、回复速度比较或谁更在乎你的定胜负稿；主线必须留在被看见、被读懂和双向珍惜上。",
                ending_step,
            ]
        else:
            recipe = [
                opening_step,
                "前半篇先守住一个回应差别里的现实接口：没回的消息、只停在表层的评论、有没有继续追问或碎片时间里的选择，不要一上来就抬成“他爱不爱你”的整篇总论。",
                "中段沿着“表层回应为什么会被误认成在乎 -> 顺序和追问先显出分量 -> 回头动作比解释更早给答案”推进，让位置判断从接口里自己长出来。",
                "不要把正文滑成吵后善后、冷战修复或争执后谁来收场的关系后处理稿；主线必须留在回应差别、顺序判断和心力投向上，也要把结尾落到位置感回正和心力收回自己手里。",
                ending_step,
            ]
    elif structure_mode == "relationship_aftercare":
        recipe = [
            opening_step,
            "前半篇先守住一次吵完之后的空白、沉默或回避接口，不要立刻抬成“爱不爱”的整篇总论。",
            "中段沿着“谁先把话咽回去 / 谁先恢复正常 / 谁先试探气氛 / 谁把情绪和日常接回去”这条关系代价线推进。",
            "少写“真正伤人的不是……”或“关系不是输在……而是输在……”这类整齐翻转句，判断要压回动作、回避、回应顺序和后续失温里自己长出来。",
            ending_step,
        ]
    elif structure_mode == "resilience_reconstruction":
        recipe = [
            opening_step,
            "前半篇先守住命运重击后的硬事实：手术台、身体限制、训练动作或长期疼痛，不要一上来就抬成励志总论，也不要转成术后恢复或自我照料提醒。",
            "中段沿着“重击留下的代价 -> 重复训练怎样逼人重来 -> 为什么她还是不肯被定义”推进，让疼痛、训练和意志重建彼此咬住。",
            "判断要压回训练动作、身体余波和被命运逼到极限后的选择里，不要写成高位赞美、女性成长口号或万能鼓劲话。",
            ending_step,
        ]
    elif structure_mode == "single_window_scene":
        recipe = [
            opening_step,
            "前半篇尽量守住同一段时间和同一处境现场，只把人物当下怎么卡住写扎实，不急着换第二个案例。",
            "中后段再回看一到两个更早的动作或后续影响，让判断从同一现场里慢慢长出来，不要直接切成并列分论点。",
            "机制说明集中在一次回看或停顿里，不要每推进一段就补一个抽象判断段。",
            ending_step,
        ]
    elif structure_mode == "emotional_engine_direct":
        recipe = [
            opening_step,
            "前半篇不要守生活场景，先守住一个情绪问题：人为什么总把自己放到最后，又为什么失去后才看见当下。",
            "中段用 2 到 4 层推进：终局感、失去链条、自我亏欠、被允许的松绑；每层都要给读者情绪价值。",
            "需要例子时优先保留一句事实、一个后果，或 1 到 2 个有情绪功能的现实细节，并并入判断段；不要展开整段环境和氛围描写，也不要保留只负责摆拍的动作残留段。",
            ending_step,
        ]
    else:
        recipe = [
            opening_step,
            "前半篇先让连续场景带路，再顺着动作、停顿和关系变化带出判断，不要开头第一屏就把道理讲完。",
            middle_step,
            "至少保留一段只停在观察、动作残留、对话碎片或身体反应上，不要让所有段落职责都完全对称。",
            ending_step,
        ]

    shell_signals = reference_shell_signals or []
    if "imperative_title_banner" in shell_signals:
        recipe.append("如果参考标题本身是“别…… / 不要……”式提醒句，你的新标题必须改成情绪发动机入口，不能再像劝告。")
    if "banner_case_banner_case_banner" in shell_signals or "imperative_heading_chain" in shell_signals:
        recipe.append("正文默认不用分节小标题，整篇靠自然段推进；如果出现小标题，必须确保它不是命令句，也不负责替段落下结论。")
    if "self_check_triplet_closing" in shell_signals or "quoted_waiting_list" in shell_signals:
        recipe.append("尾段不要做三连问、三连引语或自查清单；只留一个最小但真实的余波动作。")
    if "blessing_close" in shell_signals:
        recipe.append("最后一句不要写成“愿你 / 愿我们 / 希望你”式抚慰总结，宁可停在普通动作上。")
    if "push_then_moral_chain" in shell_signals:
        recipe.append("不要把整篇排成“先摆现象，再补道理，再给结论”的匀速阶梯，至少打断一次既定节拍。")
    if "推迟" in topic_angle or "往后放" in topic_angle or "等有空再说" in topic_angle:
        recipe.append("如果题眼是推迟或顺延，优先围绕一个被改期、没处理、先放着的接口反复推进，不要扩大成泛人生感悟。")
    return merge_unique_lines(recipe)


def _build_divergence_axes(
    *,
    source_mode: str,
    structure_mode: str,
    response_priority_followup_variant: bool = False,
) -> list[str]:
    axes = [
        "标题骨架要换成新的现实入口或处境入口",
        "开头入口必须重建，不能复用原文现成判断、反问节拍或命名句",
        "中段推进顺序必须重排，不能照着原文先后关系走",
        "结尾要换成新的处境落点，不能回到原文那种万能答案、祝福或劝告收束",
    ]
    if structure_mode == "fragment_chain_observation":
        axes.append("不要把原文压成一个连续主角场景，要保留多个现实接口之间的散落感和错位感")
    if structure_mode == "single_window_scene":
        axes.append("前半篇尽量守住同一段时间和同一处境现场，不要平均铺开多个平行案例")
    if structure_mode == "emotional_engine_direct":
        axes.append("不要把原创距离理解成换场景，必须换情绪发动机、判断顺序和价值赦免方式")
    if structure_mode == "pressure_interface_direct":
        axes.append("不要把普通接口重新抬成终局问题、人生总结或价值赦免台词，要让代价从过程里自己长出来")
    if structure_mode == "everyday_warmth_return":
        axes.append("不要把小事回归文改写成长期体谅、关系善后或术后恢复自我照料稿，主线必须留在成就祛魅和日常分量回归上")
        axes.append("不要回收参考文里那组高识别度家庭动作，必须另建新的饭桌、回家、说话或有人惦记这类日常接口")
    if structure_mode == "inner_settlement":
        axes.append("不要把心安归位文改写成坏关系等待、身体追债提醒或幸福定义翻案稿，主线必须留在心为什么一直安不下来，以及人怎样慢慢把自己放回当下")
        axes.append("不要回收参考文里的名言、祝福口吻或现成心灵判断，必须另建新的现实入口和轻动作落点")
        axes.append("开头不能统一滑向夜深、灯光、饭凉、水杯这组固定物件，必须围绕参考文真正的牵挂接口重建")
    if structure_mode == "self_worth_rebuild":
        axes.append("主线必须留在自我价值、边界、标准和体面怎样一路被放低，不要改写成消息悬停、表达退缩或关系判案稿")
        axes.append("不要把尊重自己写成高姿态宣言或筛人狠话，必须写出分寸回到自己手里、分量回收和位置感回来的过程")
        axes.append("不要复用消息框、删了重写、说不出口这组旧壳子，必须另建顺手退让、把自己放轻或降低标准的现实接口")
    if structure_mode == "self_reliance_inward_support":
        axes.append("主线必须留在参考文分析出的求助处境、自我支撑方式和正向出口，不能被固定关系外壳取代")
        axes.append("自救自渡要写出恢复判断、自我修复和求助分担的真实过程，不能写成硬扛、拒绝求助或泛独立宣言")
        axes.append("第一屏要更早落到参考文真正的触发点、正向动作、判断、行动或分担上")
        axes.append("回稳动作必须更早出现，而且要具体落在参考文对应的行动、选择、判断、求助或现实结果上")
    if structure_mode == "trust_boundary":
        axes.append("主线必须留在信任、隐瞒、坦诚和说到做到上，不要改写成回复速度、点赞评论、被读懂或放下过去的关系稿")
        axes.append("不要把信任写成查岗、审问或控制欲，必须写清放心被辜负以后，怎样靠透明交代和日常兑现重新托住心安")
        axes.append("开头必须另建信任裂开的现实接口，不要复用原文晚归、手机响和查手机这组高识别度动作")
    if structure_mode == "response_priority":
        if response_priority_followup_variant:
            axes.append("主线必须留在被看见、被读懂和被轻轻接住，不要改写成谁回得快、谁更上心或谁更在乎你的定胜负稿")
            axes.append("不要把‘真正的关心’写成抽象赞美，必须让一句追问、一次补问和一次认真停下来自己把分量显出来")
        else:
            axes.append("回应优先级文的主线必须留在时间投向、回应顺序和位置感判断上，不要把文章拐到别的关系命题里")
            axes.append("不要把判断偷换成一锤定音式宣判，必须让顺序、时间和回应动作自己把答案显出来")
    if structure_mode == "relationship_aftercare":
        axes.append("关系修复文的主线必须留在争执后的态度、有没有人回来沟通和接住失望上，不要把文章改写成抽象人生感悟")
    if structure_mode == "resilience_reconstruction":
        axes.append("不要把命运重击和训练重建稿改写成术后恢复、自我照料或泛励志样板文，主线必须留在疼痛、重复训练和不被定义的重建上")
    if source_mode == "tracked_article":
        axes.append("判断句的措辞和情绪转折不能复用参考文章现成表达")
        axes = merge_unique_lines(
            axes,
            get_dbskill_rule_lines("strategy", "divergence_axes"),
        )
    return axes


def _build_execution_checklist(
    *,
    structure_mode: str,
    reference_shell_signals: list[str] | None = None,
    response_priority_followup_variant: bool = False,
) -> list[str]:
    shell_checks: list[str] = []
    for signal in reference_shell_signals or []:
        if signal == "abstract_reflection_opening":
            shell_checks.append("开头是否避开了抽象反思总论起手，而是真从一个小接口或动作进入。")
        elif signal == "imperative_title_banner":
            shell_checks.append("标题是否已经离开“别…… / 不要……”式提醒句骨架，换成新的处境入口。")
        elif signal == "imperative_heading_chain":
            shell_checks.append("是否拆掉了“别…… / 不要……”式命令型小标题串联，没有照着原文节拍分节。")
        elif signal == "quoted_waiting_list":
            shell_checks.append("是否没有复用原文那种排队式引语或愿望清单。")
        elif signal == "dense_short_conclusion_chain":
            shell_checks.append("是否没有在每个案例后都单独补一句短判断或金句结论。")
        elif signal == "banner_case_banner_case_banner":
            shell_checks.append("是否已经打散“分节标题 - 单个案例 - 独立结论段”的循环骨架。")
        elif signal == "self_check_triplet_closing":
            shell_checks.append("结尾是否没有写成“最近一次……”式自查问卷、三连追问或对号入座清单。")
        elif signal == "blessing_close":
            shell_checks.append("最后一两段是否没有滑回“愿你 / 愿我们 / 希望你”式祝福总结。")
        elif signal == "push_then_moral_chain":
            shell_checks.append("是否没有继续按“摆现象 - 补道理 - 下结论”的匀速阶梯推进。")

    return merge_unique_lines(
        [
            "标题是否已经换成新的现实入口，而不是复述题眼。",
            "开头是否先给一个真实接口、后果或身体提醒，而不是抽象总论起手。",
            "中段是否讲清了哪件事先被往后放、当场怎么处理、后面又留下什么代价。",
            "结尾是否换成新的处境落点，而不是滑回万能答案、劝告或祝福。",
        ]
        + (
            [
                "前半篇是否基本守住同一段时间和同一处境现场，没有平均拆成几个并列观点段。",
            ]
            if structure_mode == "single_window_scene"
            else [
                "是否先压住一个已经开始出代价的接口，再沿着触发、反应和后果推进，而不是一上来就宣布终局道理。",
            ]
            if structure_mode == "pressure_interface_direct"
            else [
                "是否先拆成就祛魅，再把那些总被放轻的吃饭、回家、陪人说话和有人惦记的分量接回来，而不是滑成长期体谅、关系排序或身体提醒告诫。",
            ]
            if structure_mode == "everyday_warmth_return"
            else [
                "是否先守住心没安下来带出的现实卡点，再推进人为什么总想把一切想明白、又怎样慢慢把自己放回一餐一饮和一呼一吸，而不是滑成关系等待、身体告警或幸福定义翻案。",
            ]
            if structure_mode == "inner_settlement"
            else [
                "是否先守住一个自己明明不舒服却还是顺手退让的现实接口，再推进边界、标准和体面怎样一路被放低，并把文章落回尊重自己和分量回收，而不是滑成消息悬停、沟通表达或高位狠话。",
            ]
            if structure_mode == "self_worth_rebuild"
            else [
                "是否先守住参考文分析出的现实触发点，再推进向内稳住、自我修复和把日子慢慢接回来，并让正向动作或判断尽早出现。",
            ]
            if structure_mode == "self_reliance_inward_support"
            else [
                "是否先守住信任从放心到裂开的具体接口，再推进谎言、隐瞒、坦诚和说到做到怎样重新托住心安，而不是滑成回复速度、点赞评论或查岗审问。",
            ]
            if structure_mode == "trust_boundary"
            else [
                "是否先守住一句轻描淡写的话有没有被听懂，再推进追问、补问和真正理解怎样把人轻轻接住，并把文章落回被理解后的安稳与珍惜。",
            ]
            if structure_mode == "response_priority" and response_priority_followup_variant
            else [
                "是否先守住表层回应和继续追问之间的落差，再推进顺序、心力投向和回应动作怎样显出在乎程度，并把文章落回位置感判断。",
            ]
            if structure_mode == "response_priority"
            else [
                "是否先守住吵后空白、沉默或回避接口，再推进有没有人回来沟通、有没有人接住失望，而不是滑成抽象对错判断。",
            ]
            if structure_mode == "relationship_aftercare"
            else [
                "是否先守住命运重击、身体限制或训练代价，再推进重复训练和拒绝被定义，而不是滑成术后恢复、自我照料或泛励志口号。",
            ]
            if structure_mode == "resilience_reconstruction"
            else [
                "是否避开了整段空场景铺陈，同时保留了 1 到 2 个能挂住判断的真实接口，而不是把事实全蒸发成抽象判断。",
            ]
            if structure_mode == "emotional_engine_direct"
            else [
                "是否串起了 2 到 4 个现实接口，并让每个碎片承担不同压力，而不是平均排成几条并列观点。"
            ]
            if structure_mode == "fragment_chain_observation"
            else []
        )
        + shell_checks,
        get_dbskill_rule_lines("strategy", "execution_checklist"),
    )


def _extract_reference_scene(reference_body_markdown: str) -> str:
    text = reference_body_markdown.strip()
    if not text:
        return ""
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    for block in blocks:
        normalized = re.sub(r"^\s{0,3}#{1,6}\s*", "", block).strip()
        if not normalized:
            continue
        if len(normalized) <= 80:
            return normalized
        return normalized[:80].rstrip() + "..."
    return ""


def _extract_reference_shell_signals(reference_body_markdown: str) -> list[str]:
    text = reference_body_markdown.strip()
    if not text:
        return []

    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    normalized_blocks = [_strip_markdown_label(block) for block in blocks if _strip_markdown_label(block)]
    signals: list[str] = []
    title_match = re.search(r"^\s{0,3}#\s*(.+?)\s*$", reference_body_markdown, re.MULTILINE)
    title_text = title_match.group(1).strip() if title_match else ""

    first_substantive_block = next(
        (
            block
            for block in normalized_blocks
            if len(block) >= 16 or any(token in block for token in ("。", "，", "？", "！", "“", "”"))
        ),
        "",
    )
    if first_substantive_block:
        first_block = first_substantive_block
        if len(first_block) >= 10 and any(token in first_block for token in ("如果当初", "总在", "才懂得", "才想起", "才明白")):
            signals.append("abstract_reflection_opening")
    if title_text and title_text.startswith(("别", "不要", "别把", "别用", "别等")):
        signals.append("imperative_title_banner")

    short_heading_blocks = [block for block in normalized_blocks if 4 <= len(block) <= 12 and "。" not in block and "，" not in block]
    imperative_headings = [
        block for block in short_heading_blocks if any(block.startswith(prefix) for prefix in ("别", "不要", "别把", "别用", "别等"))
    ]
    if len(imperative_headings) >= 2:
        signals.append("imperative_heading_chain")

    quote_like_lines = 0
    for block in normalized_blocks:
        if "“等" in block or "等有钱了" in block or "等忙完" in block or "等退休了" in block:
            quote_like_lines += 1
    if quote_like_lines >= 2:
        signals.append("quoted_waiting_list")

    short_conclusion_blocks = [
        block
        for block in normalized_blocks
        if len(block) <= 26 and any(token in block for token in ("最", "真正", "有些", "人生", "生活", "幸福", "遗憾"))
    ]
    if len(short_conclusion_blocks) >= 3:
        signals.append("dense_short_conclusion_chain")

    if len(imperative_headings) >= 3 and len(short_conclusion_blocks) >= 2:
        signals.append("banner_case_banner_case_banner")
    if text.count("最近一次") >= 2 or ("想看的风景" in text and "想见的人" in text):
        signals.append("self_check_triplet_closing")
    if re.search(r"(愿你|愿我们|希望你|希望我们).{0,18}(都能|不再|可以)", text):
        signals.append("blessing_close")
    if len(short_conclusion_blocks) >= 2 and len(normalized_blocks) >= 7:
        signals.append("push_then_moral_chain")

    return signals


def _strip_markdown_label(block: str) -> str:
    return re.sub(r"^\s{0,3}#{1,6}\s*", "", block).replace("\n", " ").strip()


def _build_reference_shell_expression_constraints(reference_shell_signals: list[str]) -> list[str]:
    constraints: list[str] = []
    if "abstract_reflection_opening" in reference_shell_signals:
        constraints.append("不要沿用“深夜独处时 / 如果当初 / 我们总在……”这类抽象反思开头，直接从当下接口或动作切入。")
    if "imperative_title_banner" in reference_shell_signals:
        constraints.append("标题不要沿用“别…… / 不要……”式提醒句或训诫句，换成具体处境、动作断面或现实接口。")
    if "imperative_heading_chain" in reference_shell_signals:
        constraints.append("不要把正文切成一串“别…… / 不要……”式命令型小标题，章节关系要换成新的处境推进。")
    if "quoted_waiting_list" in reference_shell_signals:
        constraints.append("不要复用“等有钱了 / 等忙完 / 等退休了”这类排队式引语清单，换成新的现实接口。")
    if "dense_short_conclusion_chain" in reference_shell_signals:
        constraints.append("不要连续插入很多 1 到 2 句的价值判断小段，尤其不要每写完一个案例就单独敲一句结论。")
    if "banner_case_banner_case_banner" in reference_shell_signals:
        constraints.append("不要沿用“标题式分节 + 案例 + 总结句”三连壳子，至少拆掉其中两层。")
    if "self_check_triplet_closing" in reference_shell_signals:
        constraints.append("结尾不要写成“最近一次……”式自查问卷、三连追问或对号入座清单。")
    if "blessing_close" in reference_shell_signals:
        constraints.append("结尾不要再补“愿你 / 愿我们 / 希望你”式祝福或抚慰总结。")
    if "push_then_moral_chain" in reference_shell_signals:
        constraints.append("不要把整篇推进写成“摆现象 - 补道理 - 下结论”的匀速阶梯，至少打断一次节拍。")
    return constraints


def _build_reference_shell_divergence_axes(reference_shell_signals: list[str]) -> list[str]:
    axes: list[str] = []
    if "abstract_reflection_opening" in reference_shell_signals:
        axes.append("开头入口不能继续走抽象反思 + 普遍感慨，要改成更小、更近、更当下的动作入口")
    if "imperative_title_banner" in reference_shell_signals:
        axes.append("标题不能继续沿用提醒句或训诫句骨架，要换成新的情绪发动机入口")
    if "imperative_heading_chain" in reference_shell_signals:
        axes.append("中段结构不能照搬命令式小标题串联，要改成新的问题推进或接口回环")
    if "quoted_waiting_list" in reference_shell_signals:
        axes.append("不要复用原文那种三连引语或愿望清单壳子，引用型排队结构必须换掉")
    if "dense_short_conclusion_chain" in reference_shell_signals:
        axes.append("不能每推进一节就补一个短判断段，结论密度要明显低于原文")
    if "banner_case_banner_case_banner" in reference_shell_signals:
        axes.append("整篇不能再走“分节标题 - 单个案例 - 独立结论段”的循环骨架")
    if "self_check_triplet_closing" in reference_shell_signals:
        axes.append("尾段不能再走三连追问或自查清单壳子，要收在一个单独动作或余波上")
    if "blessing_close" in reference_shell_signals:
        axes.append("最后一段不能靠祝福或抚慰总结收尾，要改成普通动作留下的余波")
    if "push_then_moral_chain" in reference_shell_signals:
        axes.append("中后段不要继续按“摆现象 - 补道理 - 下结论”的匀速台阶推进")
    return axes


def _build_benchmark_borrow_focus(source_mode: str, structure_notes: str, tracked_article_scene: str) -> str:
    parts: list[str] = []
    if tracked_article_scene:
        parts.append("原文压力类型和情绪发动机")
    if structure_notes:
        parts.append("段落职责分配")
    if source_mode == "tracked_article":
        parts.append("中段情绪推进和价值赦免节奏")
    else:
        parts.append("开头先给问题再推进判断的节奏")
    return " / ".join(parts) if parts else "观察路径和段落职责"


def _build_benchmark_avoid_focus(source_mode: str) -> str:
    if source_mode == "tracked_article":
        return "不要复用原标题骨架、原文判断句、段落顺序和结尾收束"
    return "不要复用现成判断句、整齐反转和口号式结尾"


def _build_benchmark_summary(source_mode: str, tracked_article_scene: str, reference_shell_signals: list[str] | None = None) -> str:
    if source_mode == "tracked_article" and tracked_article_scene:
        summary = "只借原文对应的生活压力类型和情绪发动机，不借原文标题、首段场景、推进顺序和结尾动作。"
    elif source_mode == "tracked_article":
        summary = "只借赛道冲突和观察路径，不借现成表达和段落次序。"
    else:
        return "开头先落动作和停顿，中段再进入判断。"

    shell_signals = reference_shell_signals or []
    if "banner_case_banner_case_banner" in shell_signals or "imperative_heading_chain" in shell_signals:
        summary += " 原文如果自带命令式分节和案例轮转壳子，也只借压力类型，不借那套外壳。"
    if "abstract_reflection_opening" in shell_signals:
        summary += " 原文开头如果先抽象反思，也不能继续沿用那种总论起手。"
    if "quoted_waiting_list" in shell_signals:
        summary += " 原文如果用了排队式引语清单，也必须整体换掉。"
    if "imperative_title_banner" in shell_signals:
        summary += " 原文标题如果本身像提醒句，新标题也必须换掉那层训诫骨架。"
    if "self_check_triplet_closing" in shell_signals:
        summary += " 原文如果用三连追问或自查问卷收尾，尾段也不能再走那条路。"
    if "blessing_close" in shell_signals:
        summary += " 原文如果以祝福式抚慰收束，新稿必须改成普通动作或余波式结尾。"
    return summary


def _build_problem_statement_markdown(
    *,
    topic_title: str,
    normalized_topic_angle: str,
    trend_title: str,
    source_mode: str,
    structure_mode: str,
    observed_phenomenon: str,
    writing_goal: str,
    reader_situation: str,
    core_conflict: str,
    constraints: list[str],
    feedback_entry: str,
    problem_explanation: str,
    reference_title: str,
    reference_source_name: str,
    reference_summary: str,
    tracked_article_scene: str,
    everyday_warmth_variant: str = "",
    inner_settlement_variant: str = "",
) -> str:
    lines = [
        "# 问题说明书",
        "",
        f"## 原始目标",
        f"- 选题：{topic_title}",
        f"- 切口：{normalized_topic_angle}",
        "",
        "## 现象",
        f"- {observed_phenomenon}",
        f"- 目标读者：{reader_situation}",
        "",
        "## 目标",
        f"- {writing_goal}",
        "",
        "## 核心冲突",
        f"- {core_conflict}",
        "",
        "## 核心拆解",
        f"- {problem_explanation}",
        "",
        "## 约束",
    ]
    for constraint in constraints:
        lines.append(f"- {constraint}")
    lines.extend(
        [
            "",
            "## 反馈入口",
            f"- {feedback_entry}",
        ]
    )
    if source_mode == "tracked_article":
        reference_summary_for_strategy = _build_reference_summary_for_strategy(
            structure_mode=structure_mode,
            reference_summary=reference_summary,
            everyday_warmth_variant=everyday_warmth_variant,
            inner_settlement_variant=inner_settlement_variant,
        )
        lines.extend(
            [
                "",
                "## 参考材料只承担什么作用",
                f"- 来源：{reference_source_name or '手动录入'}",
                f"- 原文标题：{reference_title or '无'}",
                f"- 原文摘要线索：{reference_summary_for_strategy or '无'}",
                "- 可借的情绪线索：只借原文的压力类型、价值转向和情绪发动机，不借可识别的现成场景或家庭动作。",
                "- 参考材料只用于确认赛道、冲突和读者处境，不得沿用原标题骨架、段落顺序、论断次序和结尾动作。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## 来源线索",
                f"- 当前来源主题：{trend_title}",
                "- 来源线索只用于确认现实处境，不自动决定标题骨架和段落顺序。",
            ]
        )
    return "\n".join(lines)


def _build_strategy_markdown(
    *,
    topic_title: str,
    normalized_topic_angle: str,
    source_mode: str,
    reader_situation: str,
    point_of_view: str,
    conflict_frame: str,
    emotional_path: str,
    emotional_value_goal: str,
    theme_axis: str,
    anti_drift_axis: str,
    hook_trigger: str,
    progression_drive: str,
    share_reason: str,
    positive_direction: str,
    quotable_line_goal: str,
    packaging_focus: str,
    packaging_hook: str,
    writing_texture_notes: list[str],
    scene_anchor_requirements: list[str],
    realism_texture_goal: str,
    quotable_line_seeds: list[str],
    structure_mode: str,
    everyday_warmth_variant: str,
    inner_settlement_variant: str,
    response_priority_followup_variant: bool,
    opening_move: str,
    body_shift: str,
    ending_move: str,
    recomposition_recipe: list[str],
    benchmark_summary: str,
    expression_constraints: list[str],
    divergence_axes: list[str],
    execution_checklist: list[str],
    reference_title: str,
    reference_source_name: str,
    benchmark_borrow_focus: str,
    benchmark_avoid_focus: str,
    tracked_article_scene: str,
    reference_shell_signals: list[str],
) -> str:
    structure_label, structure_execution = _describe_structure_mode(
        structure_mode,
        everyday_warmth_variant=everyday_warmth_variant,
        inner_settlement_variant=inner_settlement_variant,
        response_priority_followup_variant=response_priority_followup_variant,
    )
    lines = [
        "# 创作策略卡",
        "",
        "## 写给谁",
        f"- {reader_situation}",
        "",
        "## 叙述位置",
        f"- {point_of_view}",
        "",
        "## 冲突怎么立",
        f"- {conflict_frame}",
        "",
        "## 情绪推进",
        f"- {emotional_path}",
        "",
    ]
    if hook_trigger or progression_drive or share_reason:
        lines.append("## 爆点机制")
        if hook_trigger:
            lines.append(f"- 开头触发点：{hook_trigger}")
        if progression_drive:
            lines.append(f"- 中段推进力：{progression_drive}")
        if share_reason:
            lines.append(f"- 容易被转发的原因：{share_reason}")
        lines.append("")
    if emotional_value_goal:
        lines.extend(
            [
                "## 情绪回报",
                f"- {emotional_value_goal}",
                "",
            ]
        )
    if theme_axis or anti_drift_axis:
        lines.append("## 主题合同")
        if theme_axis:
            lines.append(f"- 主题主线：{theme_axis}")
        if anti_drift_axis:
            lines.append(f"- 漂移禁区：{anti_drift_axis}")
        lines.append("")
    if positive_direction or quotable_line_goal or packaging_focus:
        lines.append("## 正向落点 / 可摘录短句 / 对外呈现")
        if positive_direction:
            lines.append(f"- 正向落点：{positive_direction}")
        if quotable_line_goal:
            lines.append(f"- 短句目标：{quotable_line_goal}")
        if packaging_focus:
            lines.append(f"- 对外呈现：{packaging_focus}")
        if packaging_hook:
            lines.append(f"- 对外主钩子：{packaging_hook}")
        lines.append("")
    if writing_texture_notes:
        lines.append("## 写法纹理")
        for item in writing_texture_notes:
            lines.append(f"- {item}")
        lines.append("")
    if scene_anchor_requirements or realism_texture_goal or quotable_line_seeds:
        lines.append("## 真人感抓手")
        if scene_anchor_requirements:
            lines.append(f"- 画面锚点：{' / '.join(scene_anchor_requirements)}")
        if realism_texture_goal:
            lines.append(f"- 真实质感：{realism_texture_goal}")
        if quotable_line_seeds:
            lines.append(f"- 短句种子：{' / '.join(quotable_line_seeds)}")
        lines.append("")
    if structure_label:
        lines.extend(
            [
                "## 结构模式",
                f"- {structure_label}",
                f"- 结构执行：{structure_execution}",
                "",
            ]
        )
    lines.extend(
        [
            "## 开头 / 中段 / 结尾动作",
            f"- 开头：{opening_move}",
            f"- 中段：{body_shift}",
            f"- 结尾：{ending_move}",
            "",
            "## 替代骨架",
        ]
    )
    for item in recomposition_recipe:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 表达约束",
        ]
    )
    for item in expression_constraints:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## 对标与借用边界",
            f"- 可借：{benchmark_borrow_focus}",
            f"- 不借：{benchmark_avoid_focus}",
            f"- 基准总结：{benchmark_summary}",
            "",
            "## 主动拉开距离的维度",
        ]
    )
    for axis in divergence_axes:
        lines.append(f"- {axis}")
    lines.extend(
        [
            "",
            "## 执行检查清单",
        ]
    )
    for item in execution_checklist:
        lines.append(f"- {item}")
    if source_mode == "tracked_article":
        lines.extend(
            [
                "",
                "## 参考文章消化说明",
                f"- 来源账号：{reference_source_name or '手动录入'}",
                f"- 参考标题：{reference_title or '无'}",
                "- 可借的原文情绪线索：只借原文的压力类型、价值转向和情绪发动机，不借可识别的现成场景或家庭动作。",
                "- 必须主动拉开距离的维度：标题骨架、开头入口、中段顺序、结尾落点。",
            ]
        )
        if reference_shell_signals:
            lines.append(
                "- 这篇参考文自带的高风险外壳也不能复用："
                + " / ".join(_build_reference_shell_divergence_axes(reference_shell_signals)[:3])
            )
    if normalized_topic_angle and normalized_topic_angle != "未显式提供":
        lines.extend(
            [
                "",
                "## 本次优先强化",
                f"- 把 `{normalized_topic_angle}` 做成读者能认出处境、看到代价并获得情绪承接的现实推进，而不是停在句式替换上。",
            ]
        )
    return "\n".join(lines)
