from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


DEFAULT_TONE_PROFILE_PRESET_KEY = "women-growth-classic"
JINWAN_YOUYU_PRESET_KEY = "jinwan-youyu-answer"


@dataclass(frozen=True)
class BuiltinToneProfilePreset:
    preset_key: str
    name: str
    opening_style: str
    paragraph_rhythm: str
    closing_style: str
    forbidden_phrases: list[str]
    value_constraints: str
    target_word_count: int
    default_polish_instruction: str
    is_active: bool = False


DEFAULT_TONE_PROFILE_PRESET = BuiltinToneProfilePreset(
    preset_key=DEFAULT_TONE_PROFILE_PRESET_KEY,
    name="女性成长克制陪伴风",
    opening_style="直接问题、现实接口或判断切入，不用生活场景冷启动",
    paragraph_rhythm="中短段直接推进；多数段落以 1 到 3 句为主，不靠整段场景铺陈，但也不要把现象、解释、转折和结论全压进一个长段；允许少量现实细节穿针引线，每段都要带来新判断、机制、情绪承接或行动落点",
    closing_style="明确结论或行动落点收束",
    forbidden_phrases=["你必须", "立刻改变"],
    value_constraints=(
        "不说教，不制造羞耻感，避免空泛鸡汤；"
        "必须有情绪价值，让读者感到被看见、被松绑或被提醒；"
        "表达要具体、克制、有承接，不用整段空场景托情绪；"
        "不要靠环境、动作、物件和氛围凑篇幅，但允许保留 1 到 2 处有情绪功能的现实细节；"
        "结尾直接给出判断或行动落点"
    ),
    target_word_count=1400,
    default_polish_instruction=(
        "请执行原创增强精修：先拆掉模板化开头、含蓄留白结尾和场景铺陈，重写开头、中段推进与收束方式，"
        "把抽象判断改成可感知的情绪命名、现实机制和行动答案，减少“一点、一下、一个、一种”这类重复量词节奏，"
        "不要保留整段场景描述；但可以留下 1 到 2 处必要事实、动作后果或物件线索，并补足情绪承接或现实机制，"
        "避免同义替换式改写和情绪空转。"
    ),
    is_active=True,
)


JINWAN_YOUYU_PRESET = BuiltinToneProfilePreset(
    preset_key=JINWAN_YOUYU_PRESET_KEY,
    name="今晚有语",
    opening_style="直接问题、现实接口或一句共鸣判断切入，直接点破问题和答案入口",
    paragraph_rhythm="标准三段式直接推进，中段围绕 2 到 4 个明确判断展开；多数段落以 1 到 2 句为主，3 句只留给必须补机制、后果或情绪承接的段落，遇到动作变化、转折或落点就拆段；每个判断都要给出依据、情绪承接或行动落点，不靠整段氛围铺陈，也不要把几层意思压进一个长段，但允许少量现实细节带路；至少保住 1 到 2 处能单独摘录的短句或引用式表达",
    closing_style="直接结论、现实落点或轻微余波收束，给答案，不拖鸡汤尾音",
    forbidden_phrases=[
        "你应该",
        "你必须",
        "总之",
        "说到底",
        "归根结底",
        "值得一提的是",
        "不可否认",
        "在当今社会",
    ],
    value_constraints=(
        "面向 25 到 45 岁女性，直接有力、给出答案、温暖但不软弱；"
        "直接给答案，不绕弯，不说教，不写教程式逐条拆解；"
        "必须有情绪价值，让读者感到被看见、被松绑或被轻轻推动；"
        "每个判断都要给依据、情绪承接或行动落点，不能只靠标题钩子和情绪反复；"
        "不要靠大段场景描写托情绪，但允许保留 1 到 2 个能承接情绪和判断的现实接口；"
        "全文最好保住 1 处从具体处境里长出来、可以单独成段的可摘录短句或引用式短句，但不要连发口号，也不要把整篇写成截图文案；"
        "如果状态允许，可以再留 1 处，但不要把整篇堆成截图文案；"
        "封面文案和导语要短、准、有抓手，尽量一句说透，不要把情绪铺成长文案；"
        "不含蓄收尾，不铺大段场景。"
    ),
    target_word_count=1500,
    default_polish_instruction=(
        "请把正文改成“今晚有语”完整风格：开头用直接问题、现实接口或一句共鸣判断迅速点题，"
        "中段围绕 2 到 4 个明确判断展开，每个判断都要贴依据、情绪承接或行动落点，"
        "并补出新的判断依据、情绪承接或行动落点，"
        "多数段落控制在 1 到 2 句，只有补机制、后果或情绪承接时才放到 3 句；如果单段超过 3 句，先拆段，不要让解释盖住情绪价值；单段如果同时塞了现象、解释、转折和落点，也要主动拆开，"
        "不要保留大段场景描写；例子可以保留一句事实、一个后果，或 1 到 2 个有情绪功能的现实细节，但不要写成场景散文，"
        "全文最好保住 1 处从具体处境里长出来、可以单独成段的可摘录短句或引用式短句，但不要连发口号，也不要把空结论单独抬成一段，"
        "如果状态允许，可以再留 1 处，但不要把整篇排成截图文案，"
        "结尾直接给结论、祝福或行动落点。全文控制在 1200 到 1800 字，"
        "语气直接有力、温暖但有边界。删掉内心独白词、AI 套话、未来安慰句和教程式分条解释，"
        "压低“不是A，是B”句式与破折号密度，避免空转抒情。"
    ),
    is_active=False,
)

JINWAN_YOUYU_INTERNAL_PRESSURE_OPENING_STYLE = (
    "如果题材是自我消耗、生活排序失衡、健康透支或身体提醒，"
    "开头先落到一个真实接口、被顺手往后放的安排或已经露出的代价，不要先写成空泛答案句；"
    "可以直接，但不要把答案先钉死在抽象判断上。"
)

JINWAN_YOUYU_INTERNAL_PRESSURE_PARAGRAPH_RHYTHM = (
    "先用真实接口带路，再给判断与落点；多数段落以 1 到 2 句为主，只有需要补代价、机制或现实余波时才放到 3 句，超过 3 句先拆段，中段可以明确，"
    "但不要一上来就写成通用讲解稿，也不要把几层意思压成一个长段；"
    "每段都要能让读者认出自己当下正在经历的那一下，并尽量留 1 句能单独截出来的短句。"
)

JINWAN_YOUYU_INTERNAL_PRESSURE_CLOSING_STYLE = (
    "收束时优先落在一个现实动作、后果余波或轻微决定上，"
    "可以给判断，但不要把结尾写成已经讲完题的标准答案。"
)

JINWAN_YOUYU_INTERNAL_PRESSURE_VALUE_CONSTRAINTS = (
    "如果题材是自我消耗、生活排序失衡、健康透支或身体提醒，"
    "必须先给出一个具体接口、被顺手往后放的安排或已经露出的代价，再给判断；"
    "不要把话题抽成空泛答案句，也不要顺手排成身体症状清单，必须让读者先认出自己。"
)

JINWAN_YOUYU_INTERNAL_PRESSURE_POLISH = (
    "如果稿子是自我消耗、生活排序失衡、健康透支或身体提醒题材，"
    "请保留直接感，但把空泛答案句改成真实接口、被顺手往后放的安排或已经露出的代价；"
    "不要让开头和结尾都先端出结论，先让读者看见具体代价，再给行动落点。"
    "多数段落控制在 1 到 2 句，只有补代价、机制或现实余波时才放到 3 句；段落职责一变就拆，不要为了显得完整把几层意思压成一个长段。"
    "除非参考文主冲突本来就建立在身体代价上，否则不要自动排成胸口、胃口、睡眠这类症状清单。"
    "全文最好保住 1 句从真实代价里长出来、可以单独成段的可摘录短句，但不要抬成空口号。"
    "如果状态允许，可以再留 1 句，但不要抬成空口号。"
)


BUILTIN_TONE_PROFILE_PRESETS: tuple[BuiltinToneProfilePreset, ...] = (
    DEFAULT_TONE_PROFILE_PRESET,
    JINWAN_YOUYU_PRESET,
)


def list_builtin_tone_profile_presets() -> list[BuiltinToneProfilePreset]:
    return list(BUILTIN_TONE_PROFILE_PRESETS)


def get_builtin_tone_profile_preset(preset_key: str | None) -> BuiltinToneProfilePreset | None:
    normalized = (preset_key or "").strip()
    if not normalized:
        return None
    for preset in BUILTIN_TONE_PROFILE_PRESETS:
        if preset.preset_key == normalized:
            return preset
    return None


def resolve_tone_profile_preset_key(tone_profile: Mapping[str, object] | None) -> str | None:
    if not isinstance(tone_profile, Mapping):
        return None
    value = tone_profile.get("preset_key")
    normalized = str(value).strip() if value is not None else ""
    return normalized or None
