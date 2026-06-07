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
    opening_style="直接问题、终局问题或判断切入，不用生活场景冷启动",
    paragraph_rhythm="中短段直接推进；不铺场景，每段都要带来新判断、机制、情绪承接或行动落点",
    closing_style="明确结论或行动落点收束",
    forbidden_phrases=["你必须", "立刻改变"],
    value_constraints=(
        "不说教，不制造羞耻感，避免空泛鸡汤；"
        "必须有情绪价值，让读者感到被看见、被松绑或被提醒；"
        "表达要具体、克制、有承接，不用场景托情绪；"
        "原则上删除场景描写，直接接上情绪命名、现实机制或行动答案；"
        "结尾直接给出判断或行动落点"
    ),
    target_word_count=1400,
    default_polish_instruction=(
        "请执行原创增强精修：先拆掉模板化开头、含蓄留白结尾和场景铺陈，重写开头、中段推进与收束方式，"
        "把抽象判断改成可感知的情绪命名、现实机制和行动答案，减少“一点、一下、一个、一种”这类重复量词节奏，"
        "原则上删除场景描述，只保留一句必要事实或结果，并补足情绪承接或现实机制，"
        "避免同义替换式改写和情绪空转。"
    ),
    is_active=True,
)


JINWAN_YOUYU_PRESET = BuiltinToneProfilePreset(
    preset_key=JINWAN_YOUYU_PRESET_KEY,
    name="今晚有语",
    opening_style="问句、引用或共鸣开场，直接点破问题和答案入口",
    paragraph_rhythm="标准三段式直接推进，中段围绕 2 到 4 个明确判断展开；每个判断都要给出依据、情绪承接或行动落点，不铺氛围",
    closing_style="直接结论或温暖祝福收束，给答案，不拖鸡汤尾音",
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
        "原则上删除场景描写，直接接上情绪命名、现实机制或行动答案；"
        "不含蓄收尾，不铺大段场景。"
    ),
    target_word_count=1500,
    default_polish_instruction=(
        "请把正文改成“今晚有语”完整风格：开头用问句、引用或共鸣迅速点题，"
        "中段围绕 2 到 4 个明确判断展开，每个判断都要贴依据、情绪承接或行动落点，"
        "并补出新的判断依据、情绪承接或行动落点，"
        "原则上删除场景描写；例子只保留一句事实或结果，不写场景散文，"
        "结尾直接给结论、祝福或行动落点。全文控制在 1200 到 1800 字，"
        "语气直接有力、温暖但有边界。删掉内心独白词、AI 套话、未来安慰句和教程式分条解释，"
        "压低“不是A，是B”句式与破折号密度，避免空转抒情。"
    ),
    is_active=False,
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
