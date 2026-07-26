from __future__ import annotations

from pydantic import BaseModel, Field


class ProblemBriefItem(BaseModel):
    project_slug: str
    version: int
    source_mode: str
    raw_goal: str
    clarified_problem: str
    observed_phenomenon: str = ""
    writing_goal: str = ""
    problem_explanation: str = ""
    emotional_value_goal: str = ""
    theme_axis: str = ""
    anti_drift_axis: str = ""
    target_reader_situation: str
    core_conflict: str
    unknowns: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    feedback_entry: str = ""
    problem_statement_markdown: str = ""
    status: str
    created_at: str | None = None


class BenchmarkReferenceItem(BaseModel):
    project_slug: str
    strategy_version: int
    reference_kind: str
    reference_label: str
    reference_pointer: str
    borrow_focus: str
    avoid_focus: str
    rationale: str
    sort_order: int


class StrategyCardItem(BaseModel):
    project_slug: str
    version: int
    problem_brief_version: int
    reader_situation: str
    point_of_view: str
    conflict_frame: str
    emotional_path: str
    hook_trigger: str = ""
    progression_drive: str = ""
    share_reason: str = ""
    positive_direction: str = ""
    quotable_line_goal: str = ""
    packaging_focus: str = ""
    packaging_hook: str = ""
    realism_texture_goal: str = ""
    structure_mode: str = ""
    opening_move: str = ""
    body_shift: str = ""
    ending_move: str = ""
    recomposition_recipe: list[str] = Field(default_factory=list)
    writing_texture_notes: list[str] = Field(default_factory=list)
    scene_anchor_requirements: list[str] = Field(default_factory=list)
    quotable_line_seeds: list[str] = Field(default_factory=list)
    expression_constraints: list[str] = Field(default_factory=list)
    divergence_axes: list[str] = Field(default_factory=list)
    execution_checklist: list[str] = Field(default_factory=list)
    benchmark_summary: str
    strategy_markdown: str = ""
    status: str
    created_at: str | None = None
    adopted_at: str | None = None


class StrategyPackageResult(BaseModel):
    project_slug: str
    problem_brief: ProblemBriefItem
    benchmarks: list[BenchmarkReferenceItem] = Field(default_factory=list)
    strategy_card: StrategyCardItem


class AdoptStrategyCardResponse(BaseModel):
    project_slug: str
    strategy_card: StrategyCardItem
    project: dict[str, object]


class DraftDiagnosisReportItem(BaseModel):
    project_slug: str
    draft_version: int
    version: int
    opening_strength: str
    scene_specificity: str
    viewpoint_clarity: str
    progression_efficiency: str
    ending_quality: str
    ai_fingerprint_level: str
    upstream_findings: list[str] = Field(default_factory=list)
    downstream_findings: list[str] = Field(default_factory=list)
    recommended_next_action: str
    objective_summary: str = ""
    recommended_polish_instruction: str = ""
    created_at: str | None = None


class DraftQualitySummaryItem(BaseModel):
    draft_version: int
    diagnosis_version: int | None = None
    reference_risk_level: str = "low"
    reference_risk_score: int = 0
    ai_fingerprint_level: str = "low"
    ai_flavor_score: int = 0
    ai_flavor_level: str = "low"
    recommended_next_action: str = ""
    recommended_polish_instruction: str = ""
    key_findings: list[str] = Field(default_factory=list)


class DirectionalPolishLinkItem(BaseModel):
    project_slug: str
    source_draft_version: int
    target_draft_version: int
    diagnosis_version: int | None = None
    objective_key: str
    objective_summary: str
    created_at: str | None = None


class RetainedLessonItem(BaseModel):
    title: str
    pattern_type: str
    intended_use: str
    pattern_content: str
    caution_notes: str


class CreativeReviewReportItem(BaseModel):
    project_slug: str
    version: int
    strategy_version: int | None = None
    draft_version: int | None = None
    summary_markdown: str
    retained_lessons: list[RetainedLessonItem] = Field(default_factory=list)
    created_at: str | None = None


class ReusablePatternItem(BaseModel):
    id: str
    source_project_slug: str
    source_report_version: int
    pattern_type: str
    title: str
    intended_use: str
    pattern_content: str
    caution_notes: str
    status: str
    created_at: str | None = None


class PromoteCreativePatternAction(BaseModel):
    report_version: int
    lesson_index: int
    title: str | None = None
    pattern_type: str | None = None
    intended_use: str | None = None
    caution_notes: str | None = None
