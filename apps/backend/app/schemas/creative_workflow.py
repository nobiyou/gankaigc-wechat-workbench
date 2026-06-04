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
    structure_mode: str = ""
    opening_move: str = ""
    body_shift: str = ""
    ending_move: str = ""
    recomposition_recipe: list[str] = Field(default_factory=list)
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
