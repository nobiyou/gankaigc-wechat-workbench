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
    r"^(?:很多时候|很多遗憾(?:都不是)?|说到底(?:[，,、:]?\s*)?|人总是这样|人很容易|我们总(?:习惯说|以为|觉得)|可生活(?:偏偏|最残酷的真相是)|真正的幸福|人生最大的遗憾|世间最痛的事|更常见的是|最磨人的(?:地方|时候)(?:在这里)?|事情常常(?:就是)?这样|身体的提醒(?:通常)?不响亮)",
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
_BRIDGING_SUMMARY_PARAGRAPH_PATTERN = re.compile(
    r"^(?:很多人|这里面|更麻烦的是|最麻烦的是|最磨人的(?:地方|时候)(?:在这里)?|关系里|有些代价|因为她|因为他|因为你|因为这|这句话|问题是|真正卡住的地方|她不是突然|他不是突然|不是某天|事情常常(?:就是)?这样|身体的提醒(?:通常)?不响亮|麻烦就麻烦在|难的地方就在这儿|很多人就是从这种地方开始变慢的|人很多时候就是从这里开始慢下来的|她还没倒下|身体先亮红灯)",
    re.UNICODE,
)
_EMBEDDED_BANNER_LEAD_PATTERN = re.compile(
    r"^(?:这条线(?:常常)?(?:就是)?这么出来的|关系(?:也是这样|就这样)(?:慢慢)?(?:淡下去|冷下去|远下去)的|真正[^。；\n]{0,14}(?:往往|常常|不是|不在)|原来不是|这句解释太顺手了|先别问为什么|这也是为什么|这种消耗(?:有点)?|屋里安静下来以后|真往前倒|可身体有时不按这套来|能让人往回退半步的|很多人就是从这种地方开始变慢的|人很多时候就是从这里开始慢下来的|麻烦就麻烦在|关系里的缺席(?:，也)?(?:是|就)?在这些时候(?:一点点)?长出来的|这句话很体谅|难的地方就在这儿|有些代价是延迟出现的|身体先亮红灯|她还没倒下)",
    re.UNICODE,
)
_STRUCTURAL_LADDER_PATTERN = re.compile(
    r"(?:先是.{0,80}后来.{0,80}再后来|先把.{0,80}后来.{0,80}再后来)",
    re.UNICODE,
)
_QUOTE_ONLY_PARAGRAPH_PATTERN = re.compile(
    r"^[“\"'‘’].+[”\"'‘’][。！？!?]?$",
    re.UNICODE,
)
_EXPLANATORY_BRIDGE_PARAGRAPH_PATTERN = re.compile(
    r"^(?:(?:解释|理由|安慰自己的话|脑子里的解释)(?:也)?(?:来得)?(?:很快|很齐|立刻|马上)?(?:就)?(?:来了|跟上来|冒出来|出现了)?|(?:第一个|先冒出来的)(?:解释|理由)|(?:第一反应|第一个念头)(?:通常)?(?:是|就是))[：:，,]",
    re.UNICODE,
)
_TIME_CHAIN_PREFIXES = (
    "电梯",
    "楼梯口",
    "中午",
    "饭局",
    "回家路上",
    "洗完澡",
    "夜里",
    "晚上",
    "周末",
    "早上",
    "深夜",
)


def _compact_text(value: str) -> str:
    return re.sub(r"\s+", "", value)


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


def _extract_first_sentence(paragraph: str) -> str:
    normalized = paragraph.strip()
    match = re.match(r"^\s*(.+?[。！？!?；;])", normalized)
    if match:
        return match.group(1).strip()
    return normalized


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


def _is_short_judgment_paragraph(paragraph: str) -> bool:
    normalized = paragraph.strip()
    compact = _compact_text(normalized)
    if not 5 <= len(compact) <= 28:
        return False
    if len(_extract_sentences(normalized)) != 1:
        return False
    if re.match(r"^[#>*\-•✔✘\d]", normalized):
        return False
    if re.search(r"[：:]", normalized):
        return False
    if re.search(r"[“”\"'‘’]", normalized):
        return False
    return True


def extract_short_judgment_paragraphs(markdown: str) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in _extract_paragraphs(markdown) if _is_short_judgment_paragraph(paragraph)]
    return _dedupe_preserve_order(paragraphs)


def extract_bridging_summary_paragraphs(markdown: str) -> list[str]:
    paragraphs = _extract_paragraphs(markdown)
    hits: list[str] = []
    for index, paragraph in enumerate(paragraphs[:-1]):
        normalized = paragraph.strip()
        compact = _compact_text(normalized)
        if not 8 <= len(compact) <= 42:
            continue
        if len(_extract_sentences(normalized)) != 1:
            continue
        if re.search(r"[：:\"“”'‘’]", normalized):
            continue
        if len(_compact_text(paragraphs[index + 1])) < 30:
            continue
        if _BRIDGING_SUMMARY_PARAGRAPH_PATTERN.search(normalized):
            hits.append(normalized)
    return _dedupe_preserve_order(hits)


def extract_embedded_banner_paragraphs(markdown: str) -> list[str]:
    hits: list[str] = []
    for paragraph in _extract_paragraphs(markdown):
        normalized = paragraph.strip()
        compact = _compact_text(normalized)
        if not 60 <= len(compact) <= 220:
            continue
        sentences = _extract_sentences(normalized)
        if len(sentences) < 2:
            continue
        first_sentence = _extract_first_sentence(normalized)
        first_compact = _compact_text(first_sentence.rstrip("。！？!?；;"))
        if not 5 <= len(first_compact) <= 26:
            continue
        if re.search(r"[：:\"“”'‘’]", first_sentence):
            continue
        if _EMBEDDED_BANNER_LEAD_PATTERN.search(first_sentence.rstrip("。！？!?；;")):
            hits.append(first_sentence)
    return _dedupe_preserve_order(hits)


def extract_isolated_quote_paragraphs(markdown: str) -> list[str]:
    hits: list[str] = []
    for paragraph in _extract_paragraphs(markdown):
        normalized = paragraph.strip()
        compact = _compact_text(normalized)
        if not 4 <= len(compact) <= 42:
            continue
        if "\n" in normalized:
            continue
        if _QUOTE_ONLY_PARAGRAPH_PATTERN.match(normalized):
            hits.append(normalized)
    return _dedupe_preserve_order(hits)


def extract_explanatory_bridge_paragraphs(markdown: str) -> list[str]:
    paragraphs = _extract_paragraphs(markdown)
    hits: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        normalized = paragraph.strip()
        compact = _compact_text(normalized)
        if not 10 <= len(compact) <= 60:
            continue
        if len(_extract_sentences(normalized)) != 1:
            continue
        if not _EXPLANATORY_BRIDGE_PARAGRAPH_PATTERN.match(normalized):
            continue
        has_context_neighbor = False
        if index > 0 and len(_compact_text(paragraphs[index - 1])) >= 10:
            has_context_neighbor = True
        if index + 1 < len(paragraphs) and len(_compact_text(paragraphs[index + 1])) >= 24:
            has_context_neighbor = True
        if has_context_neighbor:
            hits.append(normalized)
    return _dedupe_preserve_order(hits)


def count_short_long_cadence_pairs(markdown: str) -> int:
    paragraphs = _extract_paragraphs(markdown)
    count = 0
    for index, paragraph in enumerate(paragraphs[:-1]):
        if not _is_short_judgment_paragraph(paragraph):
            continue
        if len(_compact_text(paragraphs[index + 1])) >= 60:
            count += 1
    return count


def _extract_paragraph_starter(paragraph: str) -> str:
    normalized = paragraph.strip().lstrip("“”\"'‘’（）()《》【】[]<>").strip()
    if normalized.startswith("我们"):
        return "我们"
    if normalized.startswith("他们"):
        return "他们"
    if normalized.startswith("她们"):
        return "她们"
    if normalized[:1] in {"她", "他", "你", "我"}:
        return normalized[:1]
    return ""


def count_repeated_paragraph_starter_run(markdown: str) -> tuple[str, int]:
    best_starter = ""
    best_run = 0
    current_starter = ""
    current_run = 0

    for paragraph in _extract_paragraphs(markdown):
        starter = _extract_paragraph_starter(paragraph)
        if not starter:
            current_starter = ""
            current_run = 0
            continue
        if starter == current_starter:
            current_run += 1
        else:
            current_starter = starter
            current_run = 1
        if current_run > best_run:
            best_starter = starter
            best_run = current_run

    return best_starter, best_run


def _count_time_chain_leads(markdown: str) -> int:
    count = 0
    for paragraph in _extract_paragraphs(markdown):
        normalized = paragraph.strip()
        if normalized.startswith(_TIME_CHAIN_PREFIXES):
            count += 1
    return count


def _count_paragraph_shell_burden(markdown: str) -> tuple[int, int, int]:
    paragraphs = _extract_paragraphs(markdown)
    paragraph_count = len(paragraphs)
    if not paragraph_count:
        return (0, 0, 0)

    announcing_count = len(extract_bridging_summary_paragraphs(markdown)) + len(
        extract_embedded_banner_paragraphs(markdown)
    )
    repeated_run = count_repeated_paragraph_starter_run(markdown)[1]
    generic_openers = len(extract_generic_reflective_openers(markdown))
    medium_paragraphs = sum(1 for paragraph in paragraphs if 70 <= len(re.sub(r"\s+", "", paragraph)) <= 220)
    shell_like_blocks = medium_paragraphs if medium_paragraphs / paragraph_count >= 0.7 else 0
    time_chain_leads = _count_time_chain_leads(markdown)
    burden = (
        announcing_count * 3
        + max(0, repeated_run - 2) * 2
        + max(0, generic_openers - 1) * 2
        + max(0, paragraph_count - 8)
        + max(0, time_chain_leads - 2) * 2
        + (2 if shell_like_blocks else 0)
    )
    return (burden, paragraph_count, shell_like_blocks)


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

    short_judgment_paragraphs = extract_short_judgment_paragraphs(body_markdown)
    if len(short_judgment_paragraphs) >= 3:
        hits.append(f"命中：单句敲钟段偏多 x{len(short_judgment_paragraphs)}")
        suggestions.append("建议：删掉一半以上只负责点题的短判断段，把判断并回前后场景或动作段里。")
        score += min(18, len(short_judgment_paragraphs) * 4)

    cadence_pairs = count_short_long_cadence_pairs(body_markdown)
    if cadence_pairs >= 2:
        hits.append(f"命中：短句敲钟后接长解释的固定节拍 x{cadence_pairs}")
        suggestions.append("建议：打散“短句点一下 + 下一段长解释”的重复节拍，至少留一段只停在观察里。")
        score += min(18, 10 + (cadence_pairs - 2) * 4)

    paragraphs = _extract_paragraphs(body_markdown)
    short_paragraphs = sum(1 for item in paragraphs if len(item) <= 38)
    if paragraphs and len(paragraphs) >= 4 and short_paragraphs / len(paragraphs) >= 0.55:
        hits.append(f"命中：短促判断段偏多 {short_paragraphs}/{len(paragraphs)}")
        suggestions.append("建议：把连续短判断段合并为带场景推进的长短句组合。")
        score += 12

    time_chain_leads = _count_time_chain_leads(body_markdown)
    medium_scene_paragraphs = sum(1 for item in paragraphs if 35 <= len(_compact_text(item)) <= 160)
    medium_scene_ratio = medium_scene_paragraphs / max(1, len(paragraphs))
    if len(paragraphs) >= 10 and time_chain_leads >= 5 and medium_scene_ratio >= 0.7:
        hits.append(f"命中：时间节点串珠式单线推进 x{time_chain_leads}")
        suggestions.append("建议：不要把电梯、楼梯、饭局、回家、深夜这类节点按时间表排成单人单线成稿，至少打断一处，改成回看、插入或接口回环。")
        score += min(24, 18 + (time_chain_leads - 5) * 2)

    if len(paragraphs) >= 10 and time_chain_leads >= 4 and medium_scene_ratio >= 0.75:
        hits.append(f"命中：中长段匀速排布 {medium_scene_paragraphs}/{len(paragraphs)}")
        suggestions.append("建议：不要一段一个职责地匀速排布，至少合并两处，让动作、解释、余波回到同一段。")
        score += 14

    paragraph_shell_burden, paragraph_count, shell_like_blocks = _count_paragraph_shell_burden(body_markdown)
    if paragraph_count >= 16 and shell_like_blocks >= 10 and paragraph_shell_burden >= 14:
        hits.append(f"命中：段落职责切分过细 {paragraph_count}段")
        suggestions.append("建议：不要把正文切成十几段每段只承担一个推进职责，至少合并 3 到 5 段，让观察、解释和后续影响回到同一段。")
        score += min(24, 12 + (paragraph_count - 16) + max(0, paragraph_shell_burden - 14))

    bridging_summary_paragraphs = extract_bridging_summary_paragraphs(body_markdown)
    if len(bridging_summary_paragraphs) >= 2:
        hits.append(f"命中：宣布式锚句偏多 x{len(bridging_summary_paragraphs)}")
        suggestions.append("建议：把“更麻烦的是”“有些代价是延迟出现的”这类宣布式小段并回前后过程段。")
        score += min(18, 8 + (len(bridging_summary_paragraphs) - 2) * 4)

    embedded_banner_paragraphs = extract_embedded_banner_paragraphs(body_markdown)
    if len(embedded_banner_paragraphs) >= 2:
        hits.append(f"命中：长段前置总括句偏多 x{len(embedded_banner_paragraphs)}")
        suggestions.append("建议：把“这条线常常就是这么出来的”这类先总括再展开的起手拆回后面的过程里。")
        score += min(24, 10 + (len(embedded_banner_paragraphs) - 1) * 6)

    if len(paragraphs) >= 10 and len(embedded_banner_paragraphs) >= 3:
        hits.append(f"命中：锚句起段台阶推进 x{len(embedded_banner_paragraphs)}")
        suggestions.append("建议：不要每隔一两段先敲一句锚句再进入长解释，至少把一半锚句并回前后过程段。")
        score += min(22, 12 + (len(embedded_banner_paragraphs) - 3) * 4)

    isolated_quote_paragraphs = extract_isolated_quote_paragraphs(body_markdown)
    if len(isolated_quote_paragraphs) >= 2:
        hits.append(f"命中：独立引语段偏多 x{len(isolated_quote_paragraphs)}")
        suggestions.append("建议：不要把一句消息或引用单独切成展示段，把它和动作、反应放回同一段。")
        score += min(14, 8 + (len(isolated_quote_paragraphs) - 2) * 4)

    explanatory_bridge_paragraphs = extract_explanatory_bridge_paragraphs(body_markdown)
    if len(explanatory_bridge_paragraphs) >= 2:
        hits.append(f"命中：独立解释段偏多 x{len(explanatory_bridge_paragraphs)}")
        suggestions.append("建议：把“解释也来得很快”这类短解释段并回前后过程，让理由从动作后面慢慢冒出来。")
        score += min(14, 8 + (len(explanatory_bridge_paragraphs) - 2) * 4)

    ladder_count = _count_pattern_matches(body_markdown, _STRUCTURAL_LADDER_PATTERN)
    if ladder_count > 0:
        hits.append(f"命中：先是后来再后来的整齐梳理 x{ladder_count}")
        suggestions.append("建议：把整齐梳理链拆开，改成更自然的时间推进或保留一点断裂感。")
        score += min(14, ladder_count * 10)

    repeated_starter, repeated_run = count_repeated_paragraph_starter_run(body_markdown)
    if repeated_starter and repeated_run >= 3:
        hits.append(f"命中：连续同主语起段 {repeated_starter} x{repeated_run}")
        suggestions.append("建议：打散连续同主语起段，改用动作、物件、时间节点或环境先起句。")
        score += min(16, 8 + (repeated_run - 3) * 4)

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


def build_ai_flavor_polish_instruction(summary: AiFlavorRiskSummary, *, compact: bool = False) -> str:
    if compact:
        actions: list[str] = []
        if any("不是A，是B" in hit for hit in summary.hits):
            actions.append("删掉全部“不是A，而是B / 不是不……只是……”骨架，改成具体处境、动作或停顿。")
        if any("单句敲钟段偏多" in hit for hit in summary.hits):
            actions.append("把独立短判断段压到最多 2 处，至少合并 3 个短段回前后过程段。")
        if any("短句敲钟后接长解释的固定节拍" in hit for hit in summary.hits):
            actions.append("打散至少 3 处“短句点一下 + 下一段长解释”的节拍，优先改成同段完成动作、反应和后果。")
        if any("解释连接词偏多" in hit for hit in summary.hits):
            actions.append("删掉一半以上“其实 / 所以 / 因此 / 换句话说 / 也就是说”这类连接词。")
        if any("“一”字节奏偏密" in hit for hit in summary.hits):
            actions.append("把“一点 / 一下 / 一个 / 一种”这类一字量词替掉一半以上，换成具体动作、物件或时间推进。")
        if any("时间节点串珠式单线推进" in hit for hit in summary.hits):
            actions.append("不要把多个现实接口顺着时间缝成一个人从早到晚一路推进的完整日程线，至少打断一处，改成回看、插入或接口回环。")
        if any("中长段匀速排布" in hit for hit in summary.hits):
            actions.append("不要一段一个职责地匀速排布，至少合并两处，让动作、解释和后续影响回到同一段。")
        if any("宣布式锚句偏多" in hit for hit in summary.hits):
            actions.append("不要单独起段宣布观点，把“更麻烦的是 / 有些代价是延迟出现的”并回前后过程。")
        if any("长段前置总括句偏多" in hit for hit in summary.hits):
            actions.append("长段不要先下总括句，直接从后面的过程、动作或细节起笔。")
        if any("锚句起段台阶推进" in hit for hit in summary.hits):
            actions.append("不要每隔一两段先敲一句锚句再进入长解释，至少把一半锚句并回前后过程段。")
        if any("独立引语段偏多" in hit for hit in summary.hits):
            actions.append("不要把一句消息、对话或引用单独切成展示段，把它并回前后动作和反应。")
        if any("独立解释段偏多" in hit for hit in summary.hits):
            actions.append("把单独站出来的解释短段并回过程段，不要先给理由再补动作。")
        if any("连续同主语起段" in hit for hit in summary.hits):
            actions.append("打散连续“她 / 你 / 我”起段，改用动作、物件、时间点或环境先起句。")
        if any("标题判断句模板" in hit for hit in summary.hits):
            actions.append("标题改成具体处境入口，不要用宽泛判断句。")
        if any("先是后来再后来的整齐梳理" in hit for hit in summary.hits):
            actions.append("拆开“先是……后来……再后来……”这种整齐梳理链，保留更自然的时间推进。")
        if not actions:
            actions.append("优先删掉最像模板成稿的判断段，把判断压回现有动作、场景和反应里。")
        action_block = " ".join(f"{index + 1}. {action}" for index, action in enumerate(actions))
        return (
            "请基于现有草稿做一次去模板化精修。"
            "只做下面这些调整："
            + action_block
            + "保留原事实、人物关系、案例和主题，不虚构新人物、新职业、新病症、新地点或新剧情。"
            "如果原稿本来是议论或随笔推进，不要硬改成小说化故事开场。"
            "开头和结尾必须一起重写，但只用原稿已给出的事实和处境。"
            "输出只返回重写后的标题和正文。"
        )

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
        "如果原稿里已经出现很多只负责点题的独立短段，至少合并掉一半；"
        "但可以保留 1 到 3 个带具体动作、物件或身体反应的短段，不要把这些阻力线也一起抹平。"
        "不要反复使用“短句点一下，下一段再长解释”的固定节拍，允许某一段只停在观察、动作或余波里。"
        "不要把所有停顿句、改口句和动作残留都清掉，保留少量真正具体的毛边，比统一磨成顺滑总结更接近人写。"
        "不要单独起一段宣布“更麻烦的是”“有些代价是延迟出现的”“关系里的缺席”这类观点，把它并回前后过程段。"
        "不要在长段开头先补“这条线常常就是这么出来的”“关系也是这样淡下去的”“真正磨人的，往往……”这类总括句，再往下接一整段解释。"
        "不要把一句消息、对话或引用单独切成一个展示段这种做法写成固定排版习惯；如果全文只有一处且确实能增强现场感，可以保留。"
        "不要单独起一个只负责解释的短段这种做法写成固定排版习惯；如果全文只有一处且能保住当场心理跳转，可以保留。"
        "打散连续“她……她……她……”或“你……你……你……”起段，优先让动作、物件、时间节点或环境先起句。"
        "少用“先是……后来……再后来……”这种整理得过于整齐的梳理链。"
        "优先把纯判断段改成机制段：补出触发动作、当场反应和后续影响，不要只留下情绪结论。"
        "每 2 到 3 段至少保住一个稳定抓手：同一个物件、界面、空间位置、时间节点或身体信号。"
        "允许少量说明性句子把事情为什么会变成这样讲清楚，但说明必须贴着原稿已有细节，不要升空成大道理。"
        "优先在原稿已有事实、人物、关系和例子里重写，不要另起原稿没有的人物、职业、病症、时间地点或故事支线。"
        "如果原稿本来是议论或随笔推进，不要硬改成虚构故事开场。"
        "不要把原稿抹成统一的成熟公众号成稿腔，允许保留原稿里更硬一点、更直一点的表达重心。"
        "保留主题和大纲方向，但不要做同义替换式改写。"
        "输出只返回重写后的标题和正文。"
    )
