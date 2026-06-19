from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services.content_diagnosis import (
    build_diagnosis_polish_instruction,
    build_draft_diagnosis_report,
    build_reference_originality_report,
    build_structural_residue_report,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_originality_case.py"


def _load_run_originality_case_module():
    spec = importlib.util.spec_from_file_location("run_originality_case_script_for_diagnosis", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reference_originality_report_flags_reference_residue() -> None:
    source_title = "当身体开始提醒你，别再把自己往后放"
    source_markdown = (
        "# 当身体开始提醒你，别再把自己往后放\n\n"
        "## 先把身体放在日程里\n\n"
        "很多人最早忽略的不是工作，而是身体已经连续发出的求救信号。\n\n"
        "真正危险的地方，是你把每一次头晕都当成小事，把每一次复查都往后推。\n"
    )
    draft_markdown = (
        "# 当身体开始提醒你，别再把自己往后放\n\n"
        "## 先把身体放在日程里\n\n"
        "稿子先换一个入口。\n\n"
        "真正危险的地方，是你把每一次头晕都当成小事，把每一次复查都往后推。\n\n"
        "所以这篇稿子要提醒读者，把身体已经连续发出的求救信号放回第一位。\n"
    )

    report = build_reference_originality_report(
        source_title=source_title,
        source_markdown=source_markdown,
        draft_title=source_title,
        draft_markdown=draft_markdown,
    )

    assert report.risk_level == "high"
    assert report.risk_label == "原创隔离风险高"
    assert report.overlap.title_same is True
    assert report.overlap.heading_overlap == ["先把身体放在日程里", source_title]
    assert report.overlap.exact_long_sentence_overlap_count == 1
    assert "每一次复查都往后推" in report.overlap.exact_long_sentence_overlap_samples[0]
    assert report.overlap.char_8gram_jaccard > 0
    assert report.overlap.char_12gram_jaccard > 0
    assert report.overlap.longest_common_substring_length >= 30
    assert any("求救信号" in hit.fragment or hit.fragment in "身体已经连续发出的求救信号" for hit in report.danger_fragment_hits)
    assert any("参考文" in suggestion or "原创隔离" in suggestion for suggestion in report.suggestions)
    assert "参考文隔离精修" in report.recommended_polish_instruction
    assert "危险片段" in report.recommended_polish_instruction
    assert "每一次复查都往后推" in report.recommended_polish_instruction
    assert report.quality_signals["functional_equivalence_ready"] is False


def test_reference_originality_report_allows_functional_equivalence_without_surface_reuse() -> None:
    report = build_reference_originality_report(
        source_title="别总把身体提醒排到最后",
        source_markdown=(
            "# 别总把身体提醒排到最后\n\n"
            "很多人最早忽略的不是工作，而是身体已经连续发出的求救信号。\n\n"
            "真正危险的地方，是你把每一次头晕都当成小事，把每一次复查都往后推。\n"
        ),
        draft_title="忙到最后，身体会替你重新排序",
        draft_markdown=(
            "# 忙到最后，身体会替你重新排序\n\n"
            "人一旦长期把休息放到最低优先级，生活会先从睡眠、胃口和耐心上露出裂缝。\n\n"
            "这篇稿子不劝读者突然停摆，而是提醒他们提前给恢复留出位置。\n"
        ),
    )

    assert report.risk_level == "low"
    assert report.overlap.title_same is False
    assert report.overlap.exact_long_sentence_overlap_count == 0
    assert report.danger_fragment_hits == []
    assert report.quality_signals["functional_equivalence_ready"] is True
    assert report.recommended_polish_instruction == ""
    assert report.suggestions == ["参考隔离良好，继续检查信息增量、情绪价值和发布表达。"]


def test_structural_residue_report_keeps_existing_score_fields() -> None:
    residue = build_structural_residue_report(
        "# 标题\n\n"
        "这时候最容易发生的误认，是把报警当偷懒。\n\n"
        "明明已经开始耗了，她还是先把身体往后排。\n\n"
        "这不是突然发生的。\n"
    )

    assert set(residue) == {
        "residue_score",
        "paragraph_shell_burden",
        "paragraph_count",
        "shell_like_blocks",
        "short_judgment_count",
        "embedded_banner_count",
        "bridging_summary_count",
        "short_long_cadence_pairs",
        "repeated_starter_run",
    }
    assert residue["residue_score"] >= 0


def test_draft_diagnosis_report_separates_upstream_and_downstream_findings() -> None:
    reference_report = build_reference_originality_report(
        source_title="别总把身体提醒排到最后",
        source_markdown=(
            "# 别总把身体提醒排到最后\n\n"
            "## 先把身体放回日程里\n\n"
            "真正危险的地方，是你把每一次头晕都当成小事，把每一次复查都往后推。\n"
        ),
        draft_title="别总把身体提醒排到最后",
        draft_markdown=(
            "# 别总把身体提醒排到最后\n\n"
            "## 先把身体放回日程里\n\n"
            "真正危险的地方，是你把每一次头晕都当成小事，把每一次复查都往后推。\n\n"
            "愿你从今天开始，好好爱自己，成为更好的自己。\n"
        ),
    )

    report = build_draft_diagnosis_report(
        project_slug="demo",
        draft_version=2,
        version=1,
        title="别总把身体提醒排到最后",
        body_markdown=(
            "# 别总把身体提醒排到最后\n\n"
            "很多时候，我们总是把自己放在最后。\n\n"
            "真正危险的地方，是你把每一次头晕都当成小事，把每一次复查都往后推。\n\n"
            "愿你从今天开始，好好爱自己，成为更好的自己。\n"
        ),
        created_at="2026-06-19T00:00:00+00:00",
        reference_originality_report=reference_report.to_dict(),
        has_strategy_card=False,
    )

    assert report.project_slug == "demo"
    assert report.draft_version == 2
    assert report.version == 1
    assert report.recommended_next_action == "separate_reference_surface"
    assert any("参考文隔离不足" in finding for finding in report.upstream_findings)
    assert any("未绑定已采纳策略卡" in finding for finding in report.upstream_findings)
    assert any("AI 指纹风险" in finding or "参考文危险片段" in finding for finding in report.downstream_findings)
    assert "内容诊断目标精修" in report.recommended_polish_instruction
    assert "参考文表层表达" in report.objective_summary
    assert "参考文" in build_diagnosis_polish_instruction(report.to_dict())


def test_originality_script_overlap_report_uses_backend_diagnosis_owner() -> None:
    script = _load_run_originality_case_module()

    overlap = script._build_overlap_report(
        source_title="标题",
        source_markdown="# 标题\n\n## 同一小节\n\n这是一句足够长的原文表达，需要被识别出来。",
        draft_title="标题",
        draft_markdown="# 标题\n\n## 同一小节\n\n这是一句足够长的原文表达，需要被识别出来。",
    )

    assert overlap["title_same"] is True
    assert overlap["heading_overlap"] == ["同一小节", "标题"]
    assert overlap["exact_long_sentence_overlap_count"] == 1
    assert overlap["char_8gram_jaccard"] == 1.0
    assert overlap["reference_originality_risk_level"] == "high"
    assert overlap["danger_fragment_hit_count"] > 0
