from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any, Mapping


_SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]")
_CHINESE_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")
_NON_CJK_FRAGMENT_RE = re.compile(r"[^\u4e00-\u9fff]")
_COMMON_SHORT_FRAGMENTS = {
    "这个时候",
    "的时候",
    "很多人",
    "真正危险",
    "不是工作",
    "这篇稿子",
    "所以这篇",
    "身边的人",
    "身边的人也",
    "也不会",
}
_GENERIC_SHORT_HAVE_FRAGMENT_RE = re.compile(r"^有些[\u4e00-\u9fff]{2,5}$")
_GENERIC_SHORT_REFLECTIVE_FRAGMENTS = {
    "会不会不",
    "反复设想",
}


@dataclass(frozen=True)
class DangerFragmentHit:
    fragment: str
    length: int
    source_occurrences: int
    draft_occurrences: int
    source_context: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fragment": self.fragment,
            "length": self.length,
            "source_occurrences": self.source_occurrences,
            "draft_occurrences": self.draft_occurrences,
            "source_context": self.source_context,
        }


@dataclass(frozen=True)
class ReferenceOverlapReport:
    title_same: bool
    title_similarity: float
    heading_overlap: list[str]
    exact_long_sentence_overlap_count: int
    exact_long_sentence_overlap_samples: list[str]
    char_8gram_jaccard: float
    char_12gram_jaccard: float
    longest_common_substring_length: int
    longest_common_substring_sample: str

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "title_same": self.title_same,
            "heading_overlap": self.heading_overlap,
            "exact_long_sentence_overlap_count": self.exact_long_sentence_overlap_count,
            "exact_long_sentence_overlap_samples": self.exact_long_sentence_overlap_samples,
            "char_8gram_jaccard": self.char_8gram_jaccard,
            "char_12gram_jaccard": self.char_12gram_jaccard,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.to_legacy_dict()
        payload.update(
            {
                "title_similarity": self.title_similarity,
                "longest_common_substring_length": self.longest_common_substring_length,
                "longest_common_substring_sample": self.longest_common_substring_sample,
            }
        )
        return payload


@dataclass(frozen=True)
class ReferenceOriginalityReport:
    risk_level: str
    risk_label: str
    risk_score: int
    originality_score: int
    overlap: ReferenceOverlapReport
    danger_fragment_hits: list[DangerFragmentHit]
    suggestions: list[str]
    recommended_polish_instruction: str
    quality_signals: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_level": self.risk_level,
            "risk_label": self.risk_label,
            "risk_score": self.risk_score,
            "originality_score": self.originality_score,
            "overlap_report": self.overlap.to_dict(),
            "danger_fragment_hits": [hit.to_dict() for hit in self.danger_fragment_hits],
            "suggestions": self.suggestions,
            "recommended_polish_instruction": self.recommended_polish_instruction,
            "quality_signals": self.quality_signals,
        }

    def to_overlap_report_dict(self) -> dict[str, Any]:
        payload = self.overlap.to_dict()
        payload.update(
            {
                "reference_originality_risk_level": self.risk_level,
                "reference_originality_risk_label": self.risk_label,
                "reference_originality_risk_score": self.risk_score,
                "reference_originality_score": self.originality_score,
                "danger_fragment_hit_count": len(self.danger_fragment_hits),
                "danger_fragment_hits": [hit.to_dict() for hit in self.danger_fragment_hits],
                "reference_originality_suggestions": self.suggestions,
                "reference_originality_quality_signals": self.quality_signals,
            }
        )
        return payload


@dataclass(frozen=True)
class DraftDiagnosisReport:
    project_slug: str
    draft_version: int
    version: int
    opening_strength: str
    scene_specificity: str
    viewpoint_clarity: str
    progression_efficiency: str
    ending_quality: str
    ai_fingerprint_level: str
    upstream_findings: list[str]
    downstream_findings: list[str]
    recommended_next_action: str
    objective_summary: str
    recommended_polish_instruction: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_slug": self.project_slug,
            "draft_version": self.draft_version,
            "version": self.version,
            "opening_strength": self.opening_strength,
            "scene_specificity": self.scene_specificity,
            "viewpoint_clarity": self.viewpoint_clarity,
            "progression_efficiency": self.progression_efficiency,
            "ending_quality": self.ending_quality,
            "ai_fingerprint_level": self.ai_fingerprint_level,
            "upstream_findings": self.upstream_findings,
            "downstream_findings": self.downstream_findings,
            "recommended_next_action": self.recommended_next_action,
            "objective_summary": self.objective_summary,
            "recommended_polish_instruction": self.recommended_polish_instruction,
            "created_at": self.created_at,
        }


_CONCRETE_DETAIL_PATTERN = re.compile(
    r"(?:早上|中午|晚上|夜里|深夜|周末|电梯|地铁|楼道|厨房|卧室|办公室|工位|手机|微信|消息|"
    r"饭桌|门口|医院|复查|咖啡|杯子|窗|灯|包|钥匙|身体|胃|头晕|睡眠|她|他|我|你)",
    re.UNICODE,
)
_GENERIC_OPENING_PATTERN = re.compile(
    r"^(?:很多时候|很多人|其实|说到底|真正|人生|关系里|生活中|我们总是|你有没有发现|"
    r"这几年|不知道从什么时候开始)",
    re.UNICODE,
)
_VIEWPOINT_PATTERN = re.compile(
    r"(?:不是|而是|关键|真正|核心|问题|我想说|这篇|要写|要提醒|更重要|最值得)",
    re.UNICODE,
)
_ENDING_SLOGAN_PATTERN = re.compile(
    r"(?:愿你|愿我们|从今天开始|好好爱自己|成为更好的自己|你要相信|终会|一起加油)",
    re.UNICODE,
)
_OBJECTIVE_SUMMARIES = {
    "separate_reference_surface": "先拉开参考文表层表达，重写标题、段落骨架和连续片段。",
    "strengthen_opening_and_progression": "先重写开头和中段推进，让读者从具体处境进入，再顺着判断前进。",
    "reduce_ai_fingerprint": "优先降低 AI 指纹，把模板句、解释连接词和口号式收束改成自然表达。",
    "increase_scene_specificity": "补足场景、动作和细节密度，让观点从真实处境里长出来。",
    "tighten_ending": "重写结尾，收得更克制、更有余味，避免喊话式总结。",
    "final_expression_sweep": "做一次轻量表达巡检，保留当前结构，压低套话和重复。",
}


def build_reference_originality_report(
    *,
    source_title: str,
    source_markdown: str,
    draft_title: str,
    draft_markdown: str,
) -> ReferenceOriginalityReport:
    normalized_source_title = _compact_inline(source_title)
    normalized_draft_title = _compact_inline(draft_title)
    title_similarity = _similarity_ratio(normalized_source_title, normalized_draft_title)
    source_sentences = {item for item in _extract_sentences(source_markdown) if len(item) >= 18}
    draft_sentences = {item for item in _extract_sentences(draft_markdown) if len(item) >= 18}
    exact_overlap = sorted(source_sentences & draft_sentences)
    source_headings = set(_extract_headings(source_markdown))
    draft_headings = set(_extract_headings(draft_markdown))
    longest_length, longest_sample = _longest_common_substring(source_markdown, draft_markdown)
    danger_hits = _find_danger_fragment_hits(source_markdown, draft_markdown)

    overlap = ReferenceOverlapReport(
        title_same=normalized_source_title == normalized_draft_title,
        title_similarity=title_similarity,
        heading_overlap=sorted(source_headings & draft_headings),
        exact_long_sentence_overlap_count=len(exact_overlap),
        exact_long_sentence_overlap_samples=exact_overlap[:5],
        char_8gram_jaccard=_jaccard(_char_ngrams(source_markdown, 8), _char_ngrams(draft_markdown, 8)),
        char_12gram_jaccard=_jaccard(_char_ngrams(source_markdown, 12), _char_ngrams(draft_markdown, 12)),
        longest_common_substring_length=longest_length,
        longest_common_substring_sample=longest_sample,
    )
    risk_score = _score_reference_risk(overlap, danger_hits)
    risk_level, risk_label = _risk_level_and_label(risk_score)
    quality_signals = _build_quality_signals(
        overlap=overlap,
        danger_fragment_count=len(danger_hits),
        risk_level=risk_level,
        risk_score=risk_score,
    )

    return ReferenceOriginalityReport(
        risk_level=risk_level,
        risk_label=risk_label,
        risk_score=risk_score,
        originality_score=max(0, 100 - risk_score),
        overlap=overlap,
        danger_fragment_hits=danger_hits,
        suggestions=_build_suggestions(overlap, danger_hits, risk_level),
        recommended_polish_instruction=_build_recommended_polish_instruction(overlap, danger_hits, risk_level),
        quality_signals=quality_signals,
    )


def build_draft_diagnosis_report(
    *,
    project_slug: str,
    draft_version: int,
    version: int,
    title: str,
    body_markdown: str,
    created_at: str,
    reference_originality_report: Mapping[str, Any] | None = None,
    has_strategy_card: bool = False,
) -> DraftDiagnosisReport:
    from app.services.ai_flavor import evaluate_ai_flavor_risk

    paragraphs = _extract_paragraphs(body_markdown)
    opening = paragraphs[0] if paragraphs else ""
    ending = paragraphs[-1] if paragraphs else ""
    stripped_body = _strip_markdown(body_markdown)
    structural_residue = build_structural_residue_report(body_markdown)
    ai_summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)

    opening_strength = _score_to_strength_label(_score_opening(opening, title))
    scene_specificity = _score_to_strength_label(_score_scene_specificity(stripped_body, paragraphs))
    viewpoint_clarity = _score_to_strength_label(_score_viewpoint_clarity(title, stripped_body))
    progression_efficiency = _score_to_strength_label(_score_progression_efficiency(paragraphs, structural_residue))
    ending_quality = _score_to_strength_label(_score_ending(ending))
    ai_fingerprint_level = _map_ai_fingerprint_level(ai_summary.level)

    upstream_findings = _build_upstream_findings(
        opening_strength=opening_strength,
        viewpoint_clarity=viewpoint_clarity,
        reference_originality_report=reference_originality_report,
        has_strategy_card=has_strategy_card,
    )
    downstream_findings = _build_downstream_findings(
        scene_specificity=scene_specificity,
        progression_efficiency=progression_efficiency,
        ending_quality=ending_quality,
        ai_fingerprint_level=ai_fingerprint_level,
        ai_hits=ai_summary.hits,
        structural_residue=structural_residue,
        reference_originality_report=reference_originality_report,
    )
    recommended_next_action = _select_recommended_next_action(
        opening_strength=opening_strength,
        scene_specificity=scene_specificity,
        progression_efficiency=progression_efficiency,
        ending_quality=ending_quality,
        ai_fingerprint_level=ai_fingerprint_level,
        reference_originality_report=reference_originality_report,
    )
    objective_summary = resolve_diagnosis_objective_summary(recommended_next_action)

    draft_report = DraftDiagnosisReport(
        project_slug=project_slug,
        draft_version=draft_version,
        version=version,
        opening_strength=opening_strength,
        scene_specificity=scene_specificity,
        viewpoint_clarity=viewpoint_clarity,
        progression_efficiency=progression_efficiency,
        ending_quality=ending_quality,
        ai_fingerprint_level=ai_fingerprint_level,
        upstream_findings=upstream_findings,
        downstream_findings=downstream_findings,
        recommended_next_action=recommended_next_action,
        objective_summary=objective_summary,
        recommended_polish_instruction="",
        created_at=created_at,
    )
    instruction = build_diagnosis_polish_instruction(draft_report.to_dict(), objective_key=recommended_next_action)
    return DraftDiagnosisReport(
        **{
            **draft_report.to_dict(),
            "recommended_polish_instruction": instruction,
        }
    )


def resolve_diagnosis_objective_summary(objective_key: str | None) -> str:
    normalized = (objective_key or "").strip()
    return _OBJECTIVE_SUMMARIES.get(normalized, _OBJECTIVE_SUMMARIES["final_expression_sweep"])


def build_diagnosis_polish_instruction(
    report: Mapping[str, Any],
    *,
    objective_key: str | None = None,
) -> str:
    chosen_objective = (objective_key or str(report.get("recommended_next_action") or "")).strip()
    objective_summary = resolve_diagnosis_objective_summary(chosen_objective)
    upstream_findings = _coerce_string_list(report.get("upstream_findings"))
    downstream_findings = _coerce_string_list(report.get("downstream_findings"))

    lines = [
        f"请按内容诊断目标精修：{objective_summary}",
        "保留当前稿的主题、读者对象和主要信息，不新增夸张承诺，不改成教程腔。",
    ]
    if upstream_findings:
        lines.append("先处理上游问题：" + " / ".join(upstream_findings[:3]) + "。")
    if downstream_findings:
        lines.append("再处理表达问题：" + " / ".join(downstream_findings[:4]) + "。")

    if chosen_objective == "separate_reference_surface":
        lines.append("重点验收：标题、开头、段落骨架、长句和危险片段都不再贴着参考文走。")
    elif chosen_objective == "strengthen_opening_and_progression":
        lines.append("重点验收：开头先出现具体人和具体时刻，中段每一段都有新推进，不连续总结。")
    elif chosen_objective == "reduce_ai_fingerprint":
        lines.append("重点验收：减少“不是A而是B”、解释连接词、整齐短判断段和口号式结尾。")
    elif chosen_objective == "increase_scene_specificity":
        lines.append("重点验收：每个核心判断前至少有动作、物件、时间或身体感受承托。")
    elif chosen_objective == "tighten_ending":
        lines.append("重点验收：结尾收在一个克制画面或轻判断上，不喊话、不许愿、不鸡汤。")
    else:
        lines.append("重点验收：保留好段落，只做必要的去模板和节奏整理。")
    return "\n".join(lines)


def build_structural_residue_report(markdown: str) -> dict[str, int]:
    from app.services.ai_flavor import (
        _count_paragraph_shell_burden,
        count_repeated_paragraph_starter_run,
        count_short_long_cadence_pairs,
        extract_bridging_summary_paragraphs,
        extract_embedded_banner_paragraphs,
        extract_short_judgment_paragraphs,
    )

    paragraph_shell_burden, paragraph_count, shell_like_blocks = _count_paragraph_shell_burden(markdown)
    short_judgment_count = len(extract_short_judgment_paragraphs(markdown))
    embedded_banner_count = len(extract_embedded_banner_paragraphs(markdown))
    bridging_summary_count = len(extract_bridging_summary_paragraphs(markdown))
    short_long_cadence_pairs = count_short_long_cadence_pairs(markdown)
    repeated_starter_run = count_repeated_paragraph_starter_run(markdown)[1]
    residue_score = (
        paragraph_shell_burden
        + short_judgment_count * 2
        + embedded_banner_count * 3
        + bridging_summary_count * 2
        + short_long_cadence_pairs * 2
        + max(0, repeated_starter_run - 2) * 2
    )
    return {
        "residue_score": residue_score,
        "paragraph_shell_burden": paragraph_shell_burden,
        "paragraph_count": paragraph_count,
        "shell_like_blocks": shell_like_blocks,
        "short_judgment_count": short_judgment_count,
        "embedded_banner_count": embedded_banner_count,
        "bridging_summary_count": bridging_summary_count,
        "short_long_cadence_pairs": short_long_cadence_pairs,
        "repeated_starter_run": repeated_starter_run,
    }


def _extract_paragraphs(markdown: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"\n\s*\n", markdown or "")
        if part.strip() and not part.strip().startswith("#")
    ]


def _strip_markdown(markdown: str) -> str:
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"[*`>_-]+", " ", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _compact_text(markdown: str) -> str:
    return _compact_inline(_strip_markdown(markdown))


def _compact_inline(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _extract_headings(markdown: str) -> list[str]:
    headings: list[str] = []
    for line in markdown.splitlines():
        if not line.lstrip().startswith("#"):
            continue
        heading = re.sub(r"^\s{0,3}#{1,6}\s*", "", line).strip()
        if heading:
            headings.append(heading)
    return headings


def _extract_sentences(markdown: str) -> list[str]:
    stripped = re.sub(r"^\s{0,3}#{1,6}\s*", "", markdown or "", flags=re.MULTILINE)
    stripped = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", stripped)
    stripped = re.sub(r"[*`>_-]+", " ", stripped)
    sentences: list[str] = []
    for part in _SENTENCE_SPLIT_RE.split(stripped):
        normalized = _compact_inline(part)
        if normalized:
            sentences.append(normalized)
    return sentences


def _char_ngrams(text: str, n: int) -> set[str]:
    compact = _compact_text(text)
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[index : index + n] for index in range(len(compact) - n + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return round(len(left & right) / len(left | right), 6)


def _score_to_strength_label(score: int) -> str:
    if score >= 70:
        return "strong"
    if score >= 45:
        return "medium"
    return "weak"


def _score_opening(opening: str, title: str) -> int:
    if not opening.strip():
        return 0
    score = 20
    opening_length = len(_compact_inline(opening))
    if 35 <= opening_length <= 180:
        score += 25
    elif 18 <= opening_length < 35:
        score += 10
    if _CONCRETE_DETAIL_PATTERN.search(opening):
        score += 25
    if not _GENERIC_OPENING_PATTERN.search(opening.strip()):
        score += 20
    if title and title not in opening:
        score += 10
    return min(100, score)


def _score_scene_specificity(stripped_body: str, paragraphs: list[str]) -> int:
    if not stripped_body:
        return 0
    detail_count = len(_CONCRETE_DETAIL_PATTERN.findall(stripped_body))
    paragraph_count = max(1, len(paragraphs))
    density = detail_count / paragraph_count
    score = min(70, int(density * 22))
    if any(re.search(r"\d|[一二三四五六七八九十]点|分钟|小时|天", item) for item in paragraphs):
        score += 15
    if any(len(item) >= 60 and _CONCRETE_DETAIL_PATTERN.search(item) for item in paragraphs):
        score += 15
    return min(100, score)


def _score_viewpoint_clarity(title: str, stripped_body: str) -> int:
    if not stripped_body:
        return 0
    score = 20
    if _VIEWPOINT_PATTERN.search(title):
        score += 20
    viewpoint_hits = len(_VIEWPOINT_PATTERN.findall(stripped_body))
    score += min(35, viewpoint_hits * 7)
    first_sentences = "".join(_extract_sentences(stripped_body)[:3])
    if _VIEWPOINT_PATTERN.search(first_sentences):
        score += 15
    if "？" in title or "?" in title:
        score += 10
    return min(100, score)


def _score_progression_efficiency(paragraphs: list[str], structural_residue: Mapping[str, int]) -> int:
    if not paragraphs:
        return 0
    score = 80
    if len(paragraphs) < 3:
        score -= 20
    score -= min(35, int(structural_residue.get("residue_score", 0)) * 3)
    score -= min(15, max(0, int(structural_residue.get("repeated_starter_run", 0)) - 2) * 5)
    score -= min(15, int(structural_residue.get("short_long_cadence_pairs", 0)) * 4)
    return max(0, min(100, score))


def _score_ending(ending: str) -> int:
    if not ending.strip():
        return 0
    score = 25
    ending_length = len(_compact_inline(ending))
    if 28 <= ending_length <= 180:
        score += 30
    elif 16 <= ending_length < 28:
        score += 15
    if _CONCRETE_DETAIL_PATTERN.search(ending):
        score += 15
    if not _ENDING_SLOGAN_PATTERN.search(ending):
        score += 25
    if ending.rstrip().endswith(("。", "！", "?", "？")):
        score += 5
    return min(100, score)


def _map_ai_fingerprint_level(level: str) -> str:
    if level == "高":
        return "high"
    if level == "中":
        return "medium"
    return "low"


def _reference_risk_level(reference_originality_report: Mapping[str, Any] | None) -> str:
    if not reference_originality_report:
        return "low"
    return str(reference_originality_report.get("risk_level") or "low")


def _build_upstream_findings(
    *,
    opening_strength: str,
    viewpoint_clarity: str,
    reference_originality_report: Mapping[str, Any] | None,
    has_strategy_card: bool,
) -> list[str]:
    findings: list[str] = []
    if opening_strength == "weak":
        findings.append("开头切口偏弱，读者还没有被放进一个具体处境。")
    if viewpoint_clarity == "weak":
        findings.append("核心观点不够早、不够清楚，稿子容易变成泛泛说明。")
    if _reference_risk_level(reference_originality_report) in {"medium", "high"}:
        findings.append("参考文隔离不足，上游角度和段落骨架还需要重新拉开。")
    if not has_strategy_card:
        findings.append("当前稿未绑定已采纳策略卡，诊断只能基于正文表现判断上游问题。")
    return findings or ["上游策略暂无明显阻塞，主要问题可以进入表达层处理。"]


def _build_downstream_findings(
    *,
    scene_specificity: str,
    progression_efficiency: str,
    ending_quality: str,
    ai_fingerprint_level: str,
    ai_hits: list[str],
    structural_residue: Mapping[str, int],
    reference_originality_report: Mapping[str, Any] | None,
) -> list[str]:
    findings: list[str] = []
    if scene_specificity == "weak":
        findings.append("场景和动作细节偏少，判断多于可感知材料。")
    if progression_efficiency == "weak":
        findings.append("中段推进效率偏低，存在重复起手、短判断段或结构残留。")
    if ending_quality == "weak":
        findings.append("结尾收束偏模板，容易落入口号或泛安慰。")
    if ai_fingerprint_level in {"medium", "high"}:
        findings.append("AI 指纹风险偏高：" + " / ".join(ai_hits[:3]) + "。")
    if int(structural_residue.get("residue_score", 0)) >= 8:
        findings.append(f"结构残留分较高（{structural_residue['residue_score']}），需要重排段落节奏。")
    if _reference_risk_level(reference_originality_report) in {"medium", "high"}:
        danger_count = len(_coerce_string_list(reference_originality_report.get("danger_fragment_hits")))
        if danger_count:
            findings.append(f"仍有 {danger_count} 个参考文危险片段，需要删除或彻底重写。")
    return findings or ["表达层暂无高风险残留，可做轻量节奏和措辞巡检。"]


def _select_recommended_next_action(
    *,
    opening_strength: str,
    scene_specificity: str,
    progression_efficiency: str,
    ending_quality: str,
    ai_fingerprint_level: str,
    reference_originality_report: Mapping[str, Any] | None,
) -> str:
    if _reference_risk_level(reference_originality_report) in {"medium", "high"}:
        return "separate_reference_surface"
    if opening_strength == "weak" or progression_efficiency == "weak":
        return "strengthen_opening_and_progression"
    if ai_fingerprint_level in {"medium", "high"}:
        return "reduce_ai_fingerprint"
    if scene_specificity == "weak":
        return "increase_scene_specificity"
    if ending_quality == "weak":
        return "tighten_ending"
    return "final_expression_sweep"


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, Mapping):
            fragment = item.get("fragment")
            if fragment:
                result.append(str(fragment))
    return result


def _similarity_ratio(left: str, right: str) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return round(SequenceMatcher(None, left, right, autojunk=False).ratio(), 6)


def _longest_common_substring(source_markdown: str, draft_markdown: str) -> tuple[int, str]:
    source = _compact_text(source_markdown)
    draft = _compact_text(draft_markdown)
    if not source or not draft:
        return 0, ""
    match = SequenceMatcher(None, source, draft, autojunk=False).find_longest_match(0, len(source), 0, len(draft))
    sample = source[match.a : match.a + match.size]
    return match.size, sample[:80]


def _find_danger_fragment_hits(
    source_markdown: str,
    draft_markdown: str,
    *,
    min_length: int = 4,
    max_length: int = 8,
    limit: int = 20,
) -> list[DangerFragmentHit]:
    source = _compact_text(source_markdown)
    draft = _compact_text(draft_markdown)
    if len(source) < min_length or len(draft) < min_length:
        return []

    selected: list[DangerFragmentHit] = []
    selected_spans: list[tuple[int, int]] = []
    for length in range(max_length, min_length - 1, -1):
        source_counts = Counter(source[index : index + length] for index in range(len(source) - length + 1))
        for index in range(len(source) - length + 1):
            fragment = source[index : index + length]
            if source_counts[fragment] != 1:
                continue
            if fragment not in draft:
                continue
            if _is_noise_fragment(fragment):
                continue
            span = (index, index + length)
            if any(_spans_overlap(span, selected_span) for selected_span in selected_spans):
                continue
            selected.append(
                DangerFragmentHit(
                    fragment=fragment,
                    length=length,
                    source_occurrences=source_counts[fragment],
                    draft_occurrences=draft.count(fragment),
                    source_context=_fragment_context(source, index, length),
                )
            )
            selected_spans.append(span)
            if len(selected) >= limit:
                return selected
    return selected


def _is_noise_fragment(fragment: str) -> bool:
    normalized_fragment = _NON_CJK_FRAGMENT_RE.sub("", fragment)
    if normalized_fragment in _COMMON_SHORT_FRAGMENTS:
        return True
    if len(normalized_fragment) >= 4 and any(
        normalized_fragment in common_fragment for common_fragment in _COMMON_SHORT_FRAGMENTS
    ):
        return True
    if normalized_fragment in _GENERIC_SHORT_REFLECTIVE_FRAGMENTS:
        return True
    if _GENERIC_SHORT_HAVE_FRAGMENT_RE.match(normalized_fragment):
        return True
    chinese_chars = _CHINESE_CHAR_RE.findall(normalized_fragment)
    if len(chinese_chars) < 3:
        return True
    if len(set(chinese_chars)) <= 1:
        return True
    return False


def _spans_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return min(left[1], right[1]) - max(left[0], right[0]) >= 2


def _fragment_context(text: str, start: int, length: int, window: int = 12) -> str:
    context_start = max(0, start - window)
    context_end = min(len(text), start + length + window)
    return text[context_start:context_end]


def _score_reference_risk(overlap: ReferenceOverlapReport, danger_hits: list[DangerFragmentHit]) -> int:
    score = 0
    if overlap.title_same:
        score += 25
    elif overlap.title_similarity >= 0.85:
        score += 12
    score += min(20, len(overlap.heading_overlap) * 5)
    score += min(30, overlap.exact_long_sentence_overlap_count * 15)
    score += min(15, int(overlap.char_8gram_jaccard * 50))
    score += min(25, int(overlap.char_12gram_jaccard * 100))
    if overlap.longest_common_substring_length >= 40:
        score += 25
    elif overlap.longest_common_substring_length >= 24:
        score += 15
    elif overlap.longest_common_substring_length >= 16:
        score += 8
    score += min(25, len(danger_hits) * 3)
    return min(100, score)


def _risk_level_and_label(score: int) -> tuple[str, str]:
    if score >= 60:
        return "high", "原创隔离风险高"
    if score >= 30:
        return "medium", "原创隔离风险中"
    return "low", "原创隔离风险低"


def _build_quality_signals(
    *,
    overlap: ReferenceOverlapReport,
    danger_fragment_count: int,
    risk_level: str,
    risk_score: int,
) -> dict[str, Any]:
    surface_reuse_detected = (
        overlap.title_same
        or overlap.exact_long_sentence_overlap_count > 0
        or overlap.longest_common_substring_length >= 24
        or overlap.char_12gram_jaccard >= 0.08
        or danger_fragment_count > 0
    )
    return {
        "functional_equivalence_ready": risk_level == "low" and not surface_reuse_detected,
        "surface_reuse_detected": surface_reuse_detected,
        "danger_fragment_count": danger_fragment_count,
        "risk_score": risk_score,
    }


def _build_suggestions(
    overlap: ReferenceOverlapReport,
    danger_hits: list[DangerFragmentHit],
    risk_level: str,
) -> list[str]:
    suggestions: list[str] = []
    if overlap.title_same:
        suggestions.append("标题仍与参考文一致，先重命名角度、承诺和读者收益。")
    elif overlap.title_similarity >= 0.85:
        suggestions.append("标题与参考文过近，换成新的问题入口或判断句。")
    if overlap.heading_overlap:
        suggestions.append("小标题仍沿用参考文结构，先重排段落功能，再重新命名小节。")
    if overlap.exact_long_sentence_overlap_count:
        suggestions.append("存在参考文长句残留，逐句删除或重写，不做近义词替换。")
    if danger_hits:
        suggestions.append("清理危险片段：保留功能等价，不保留参考文的连续表达。")
    if (
        overlap.longest_common_substring_length >= 24
        or overlap.char_12gram_jaccard >= 0.08
        or overlap.char_8gram_jaccard >= 0.12
    ):
        suggestions.append("按观点功能重组素材顺序，避免逐句对应和段落贴合。")
    if not suggestions and risk_level == "low":
        return ["参考隔离良好，继续检查信息增量、情绪价值和发布表达。"]
    return suggestions


def _build_recommended_polish_instruction(
    overlap: ReferenceOverlapReport,
    danger_hits: list[DangerFragmentHit],
    risk_level: str,
) -> str:
    if risk_level == "low":
        return ""

    lines = [
        "请执行参考文隔离精修：保留当前稿的主题功能和读者收益，但不要逐句对应参考文。",
        "把标题、段落顺序、小标题和连续表达重新组织成新的问题入口、判断推进和情绪承接。",
    ]
    if overlap.title_same:
        lines.append("标题必须重写，不沿用参考文标题结构。")
    if overlap.heading_overlap:
        lines.append(f"重命名或重排这些小标题/标题残留：{' / '.join(overlap.heading_overlap[:4])}。")
    if overlap.exact_long_sentence_overlap_samples:
        lines.append(
            "删除或彻底重写这些长句残留，不做近义词替换："
            + " / ".join(overlap.exact_long_sentence_overlap_samples[:3])
            + "。"
        )
    if danger_hits:
        lines.append(
            "清理这些危险片段，避免在新稿中连续出现："
            + " / ".join(hit.fragment for hit in danger_hits[:8])
            + "。"
        )
    if overlap.longest_common_substring_sample:
        lines.append(f"最长连续重合片段需要拆开重写：{overlap.longest_common_substring_sample}。")
    lines.append("验收标准：功能等价，但标题、开头、段落骨架、长句和危险片段都不再贴着参考文走。")
    return "\n".join(lines)
