from __future__ import annotations

import re
from typing import Any, Mapping

from app.schemas.creative_workflow import DraftQualitySummaryItem


_CONNECTOR_PATTERN = re.compile(r"(?:比如|例如|其实|所以|因此|也就是说|换句话说|接下来|然后|首先|其次|最后)")
_YI_CADENCE_PATTERN = re.compile(r"(?:一点|一下|一些|一个|一种|一件|一句|一段|一整天|一会儿|一遍)")
_NOT_AB_PATTERN = re.compile(r"不是[^，。；\n]{1,20}[，,、]?\s*而?是[^，。；\n]{1,20}")
_SLOGAN_ENDING_PATTERN = re.compile(r"(?:愿你|从今天开始|好好爱自己|成为更好的自己|你要相信|终会)")


def build_draft_quality_summary(
    *,
    draft_version: int,
    draft_title: str,
    draft_body_markdown: str,
    diagnosis_report: Mapping[str, Any] | None = None,
    reference_originality_report: Mapping[str, Any] | None = None,
) -> DraftQualitySummaryItem:
    ai_flavor_score, ai_flavor_level, ai_findings = _build_ai_flavor_snapshot(
        title=draft_title,
        body_markdown=draft_body_markdown,
    )
    reference_risk_level = _text(reference_originality_report.get("risk_level")) if reference_originality_report else "low"
    reference_risk_score = _safe_int(reference_originality_report.get("risk_score")) if reference_originality_report else 0
    recommended_next_action = _text(diagnosis_report.get("recommended_next_action")) if diagnosis_report else ""
    recommended_polish_instruction = _text(diagnosis_report.get("recommended_polish_instruction")) if diagnosis_report else ""

    key_findings: list[str] = []
    if diagnosis_report:
        key_findings.extend(_string_list(diagnosis_report.get("upstream_findings"))[:2])
        key_findings.extend(_string_list(diagnosis_report.get("downstream_findings"))[:2])
    if reference_originality_report and reference_risk_level in {"medium", "high"}:
        key_findings.append(f"参考文隔离风险：{reference_risk_level} / {reference_risk_score}")
    key_findings.extend(ai_findings[:2])

    return DraftQualitySummaryItem(
        draft_version=draft_version,
        diagnosis_version=_safe_int(diagnosis_report.get("version")) if diagnosis_report else None,
        reference_risk_level=reference_risk_level or "low",
        reference_risk_score=reference_risk_score,
        ai_fingerprint_level=_text(diagnosis_report.get("ai_fingerprint_level")) if diagnosis_report else "low",
        ai_flavor_score=ai_flavor_score,
        ai_flavor_level=ai_flavor_level,
        recommended_next_action=recommended_next_action,
        recommended_polish_instruction=recommended_polish_instruction,
        key_findings=key_findings,
    )


def _build_ai_flavor_snapshot(*, title: str, body_markdown: str) -> tuple[int, str, list[str]]:
    findings: list[str] = []
    score = 0

    not_ab_count = len(_NOT_AB_PATTERN.findall(body_markdown))
    if not_ab_count:
        findings.append(f"整齐反转句偏多 x{not_ab_count}")
        score += min(30, not_ab_count * 12)

    connector_count = len(_CONNECTOR_PATTERN.findall(body_markdown))
    if connector_count >= 4:
        findings.append(f"解释连接词偏多 x{connector_count}")
        score += min(22, max(8, connector_count))

    yi_cadence_count = len(_YI_CADENCE_PATTERN.findall(body_markdown))
    if yi_cadence_count >= 5:
        findings.append(f"一字量词节奏偏密 x{yi_cadence_count}")
        score += min(18, yi_cadence_count * 2)

    trailing = body_markdown[-120:]
    if _SLOGAN_ENDING_PATTERN.search(trailing):
        findings.append("结尾口号感偏强")
        score += 16

    if "不是" in title and "，" in title:
        findings.append("标题仍像判断句模板")
        score += 16

    bounded_score = max(0, min(100, round(score)))
    if bounded_score >= 60:
        level = "high"
    elif bounded_score >= 30:
        level = "medium"
    else:
        level = "low"
    return bounded_score, level, findings


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]
