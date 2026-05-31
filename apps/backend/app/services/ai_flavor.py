from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class AiFlavorRiskSummary:
    score: int
    level: str
    hits: list[str]
    suggestions: list[str]


_NOT_AB_PATTERN = re.compile(r"不是[^，。；\n]{1,20}[，,、]?\s*而?是[^，。；\n]{1,20}", re.UNICODE)
_GENERIC_REFLECTIVE_OPENING_PATTERN = re.compile(
    r"^(?:很多时候|很多遗憾(?:都不是)?|说到底(?:[，,、:]?\s*)?|人总是这样|人很容易|我们总(?:习惯说|以为|觉得)|可生活(?:偏偏|最残酷的真相是)|真正的幸福|人生最大的遗憾|世间最痛的事)",
    re.UNICODE,
)
_CONNECTOR_PATTERN = re.compile(
    r"(?:比如|例如|其实|所以|因此|也就是说|换句话说|接下来|然后|首先|其次|最后)",
    re.UNICODE,
)
_CLICHE_PATTERN = re.compile(
    r"(?:真正的成长|好好爱自己|成为更好的自己|重新选择自己|从今天开始|愿你|治愈自己)",
    re.UNICODE,
)
_ENDING_SLOGAN_PATTERN = re.compile(
    r"(?:愿你|愿我们|愿你我|愿大家|愿每个人|从今天开始|好好爱自己|成为更好的自己|你要相信|终会)",
    re.UNICODE,
)
_YI_CADENCE_PATTERN = re.compile(
    r"^(?:一点|一下|一些|一个|一种|一件|一句|一段|一整天|一会儿|一遍)",
    re.UNICODE,
)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    deduped: list[str] = []
    for item in items:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _extract_paragraphs(markdown: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"\n\s*\n", markdown)
        if part.strip() and not part.strip().startswith("#")
    ]


def _pick_trailing_excerpt(markdown: str) -> str:
    paragraphs = _extract_paragraphs(markdown)
    return paragraphs[-1] if paragraphs else "暂无内容"


def _count_pattern_matches(markdown: str, pattern: re.Pattern[str]) -> int:
    return len(pattern.findall(markdown))


def _extract_sentences(markdown: str) -> list[str]:
    sentences: list[str] = []
    for paragraph in _extract_paragraphs(markdown):
        for sentence in re.split(r"[。！？!?；;\n]", paragraph):
            normalized = sentence.strip()
            if normalized:
                sentences.append(normalized)
    return sentences


def _should_keep_not_ab_match(*, sentence: str, match_start: int) -> bool:
    compact_sentence = re.sub(r"\s+", "", sentence)
    if len(compact_sentence) <= 32:
        return True

    prefix = sentence[:match_start].strip()
    compact_prefix = re.sub(r"[“”\"'‘’\s，,、：:（）()《》【】\[\]<>]", "", prefix)
    return len(compact_prefix) <= 4


def _extract_not_ab_matches(markdown: str) -> list[str]:
    matches: list[str] = []
    for sentence in _extract_sentences(markdown):
        for match in _NOT_AB_PATTERN.finditer(sentence):
            if _should_keep_not_ab_match(sentence=sentence, match_start=match.start()):
                matches.append(match.group(0).strip())
    return matches


def extract_generic_reflective_openers(markdown: str) -> list[str]:
    openers: list[str] = []
    for paragraph in _extract_paragraphs(markdown):
        first_sentence = re.split(r"[。！？!?；;\n]", paragraph.strip(), maxsplit=1)[0].strip()
        if not first_sentence:
            continue
        match = _GENERIC_REFLECTIVE_OPENING_PATTERN.match(first_sentence)
        if not match:
            continue
        opener = match.group(0).strip().rstrip("，,、：:")
        if opener:
            openers.append(opener)
    return openers


def extract_not_ab_skeletons(markdown: str) -> list[str]:
    return _dedupe_preserve_order(_extract_not_ab_matches(markdown))


def extract_growth_cliches(markdown: str) -> list[str]:
    matches = [match.group(0).strip() for match in _CLICHE_PATTERN.finditer(markdown)]
    return _dedupe_preserve_order(matches)


def _extract_clause_leading_yi_phrases(markdown: str) -> list[str]:
    phrases: list[str] = []
    for paragraph in _extract_paragraphs(markdown):
        for clause in re.split(r"[，,、。！？!?；;\n]", paragraph):
            normalized = clause.strip()
            if not normalized:
                continue
            normalized = normalized.lstrip("“”\"'‘’（）()《》【】[]<>").strip()
            match = _YI_CADENCE_PATTERN.match(normalized)
            if match:
                phrases.append(match.group(0))
    return phrases


def _extract_clause_leading_connectors(markdown: str) -> list[str]:
    connectors: list[str] = []
    for paragraph in _extract_paragraphs(markdown):
        for clause in re.split(r"[，,、。！？!?；;\n]", paragraph):
            normalized = clause.strip()
            if not normalized:
                continue
            normalized = normalized.lstrip("“”\"'‘’（）()《》【】[]<>").strip()
            match = _CONNECTOR_PATTERN.match(normalized)
            if match:
                connectors.append(match.group(0))
    return connectors


def evaluate_ai_flavor_risk(*, title: str, body_markdown: str) -> AiFlavorRiskSummary:
    hits: list[str] = []
    suggestions: list[str] = []
    score = 0

    not_ab_count = len(_extract_not_ab_matches(body_markdown))
    if not_ab_count > 0:
        hits.append(f"命中：不是A，是B x{not_ab_count}")
        suggestions.append("建议：把整齐反转句拆成一个具体场景和一个延迟出现的判断。")
        score += min(30, not_ab_count * 12)

    step_count = _count_pattern_matches(body_markdown, re.compile(r"第[一二三四五六七八九十]+步", re.UNICODE))
    if step_count > 0:
        hits.append(f"命中：教程分步 x{step_count}")
        suggestions.append("建议：把分步教程改成自然叙事推进，让观察和情绪先发生。")
        score += min(24, step_count * 8)

    connector_count = len(_extract_clause_leading_connectors(body_markdown))
    if connector_count >= 4:
        hits.append(f"命中：解释连接词偏多 x{connector_count}")
        suggestions.append("建议：删掉部分解释连接词，让动作和细节承担转场。")
        score += min(22, max(8, connector_count))

    yi_cadence_count = len(_extract_clause_leading_yi_phrases(body_markdown))
    if yi_cadence_count >= 5:
        hits.append(f"命中：“一”字节奏偏密 x{yi_cadence_count}")
        suggestions.append("建议：替换一半以上的一字量词起手，改用具体动作、物件或时间推进。")
        score += min(18, yi_cadence_count * 2)

    paragraphs = _extract_paragraphs(body_markdown)
    short_paragraphs = sum(1 for item in paragraphs if len(item) <= 38)
    if paragraphs and len(paragraphs) >= 4 and short_paragraphs / len(paragraphs) >= 0.55:
        hits.append(f"命中：短促判断段偏多 {short_paragraphs}/{len(paragraphs)}")
        suggestions.append("建议：把连续短判断段合并为带场景推进的长短句组合。")
        score += 12

    if "不是" in title and "，" in title:
        hits.append("命中：标题判断句模板")
        suggestions.append("建议：标题少用对称判断，优先写具体处境或情绪入口。")
        score += 16

    cliche_count = _count_pattern_matches(body_markdown, _CLICHE_PATTERN)
    if cliche_count > 0:
        hits.append(f"命中：万能成长套话 x{cliche_count}")
        suggestions.append("建议：把万能成长句改成本文人物当下能看见的动作、物件或停顿。")
        score += min(24, cliche_count * 10)

    generic_reflective_openers = extract_generic_reflective_openers(body_markdown)
    if len(generic_reflective_openers) >= 2:
        hits.append(f"命中：泛感慨过渡句偏多 x{len(generic_reflective_openers)}")
        suggestions.append("建议：删掉部分“很多时候”“说到底”式过渡句，直接回到具体人物、动作或处境。")
        score += min(18, len(generic_reflective_openers) * 6)

    ending = _pick_trailing_excerpt(body_markdown)
    if re.search(_ENDING_SLOGAN_PATTERN, ending):
        hits.append("命中：结尾口号感")
        suggestions.append("建议：结尾回到人物处境或心绪余波，避免喊话式总结。")
        score += 16

    bounded_score = max(0, min(100, round(score)))
    level = "高" if bounded_score >= 60 else "中" if bounded_score >= 30 else "低"

    return AiFlavorRiskSummary(
        score=bounded_score,
        level=level,
        hits=hits,
        suggestions=_dedupe_preserve_order(suggestions),
    )


def build_ai_flavor_polish_instruction(summary: AiFlavorRiskSummary) -> str:
    hit_summary = "；".join(summary.hits[:4]) or "命中轻微模板风险"
    suggestion_summary = "；".join(summary.suggestions[:3]) or "改成更具体、更自然的表达。"
    return (
        "请对当前草稿做一次去模板化重写。"
        "这次不是局部润色，而是要拆掉 AI 味最重的段落和句式骨架。"
        f"当前命中：{hit_summary}。"
        f"{suggestion_summary}"
        "必须至少改写标题、开头第一屏、一个中段判断段和结尾段。"
        "如果出现“不是……而是……”或“不是不……只是……”这类骨架，直接改成具体处境、动作、停顿或物件。"
        "不要为了把段落接顺，额外补“很多时候”“说到底”“人总是这样”这类泛感慨过渡句。"
        "压低解释连接词，以及“一点、一下、一个、一种”这类泛化量词。"
        "优先在原稿已有事实、人物、关系和例子里重写，不要另起原稿没有的人物、职业、病症、时间地点或故事支线。"
        "如果原稿本来是议论或随笔推进，不要硬改成虚构故事开场。"
        "不要把原稿抹成统一的成熟公众号成稿腔，允许保留原稿里更硬一点、更直一点的表达重心。"
        "保留主题和大纲方向，但不要做同义替换式改写。"
        "输出只返回重写后的标题和正文。"
    )
