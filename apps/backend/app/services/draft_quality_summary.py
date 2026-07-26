from __future__ import annotations

from typing import Any, Mapping

from app.schemas.creative_workflow import DraftQualitySummaryItem
from app.services.ai_flavor import evaluate_ai_flavor_risk


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
    summary = evaluate_ai_flavor_risk(title=title, body_markdown=body_markdown)
    findings = [hit.removeprefix("命中：") for hit in summary.hits]
    return summary.score, summary.level, findings


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
