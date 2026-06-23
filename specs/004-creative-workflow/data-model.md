# Data Model: Creative Workflow

## Overview

This feature adds project-owned creative workflow artifacts on top of the existing topic, outline, draft, asset, publish-package, and retro chain.

## Problem Brief

**Purpose**: Captures the clarified writing problem that the article is trying to address before outline generation begins.

**Fields**

- `project_slug`: owning content project
- `version`: ordered version within the project
- `source_mode`: whether the input started from a trend-based topic or an original idea
- `raw_goal`: the original operator phrasing or project framing
- `clarified_problem`: the refined statement of what needs to be explained, shifted, or resolved
- `target_reader_situation`: the reader context or emotional situation being written for
- `core_conflict`: the tension or contradiction that makes the topic worth writing
- `unknowns`: unresolved questions or weak assumptions that still need review
- `status`: `needs_review`, `ready`, or `superseded`
- `created_at`: generation timestamp

**Rules**

- A project can have multiple problem-brief versions
- Outline generation reads the latest `ready` problem brief when one exists
- `unknowns` must be visible to operators when status is `needs_review`

## Benchmark Reference

**Purpose**: Records one reference example used to shape angle, pacing, structure, or emotional handling for a project.

**Fields**

- `project_slug`: owning content project
- `strategy_version`: associated strategy-card version
- `reference_kind`: source family such as tracked article, operator-supplied reference, or internal pattern
- `reference_label`: human-readable identifier
- `reference_pointer`: source slug, URL, or internal pattern identifier
- `borrow_focus`: what is safe to emulate, such as opening rhythm, scene density, or ending restraint
- `avoid_focus`: what must not be copied directly, such as phrases, structure overfit, or tone mismatch
- `rationale`: why this benchmark was chosen for this project
- `sort_order`: operator-facing order

**Rules**

- A strategy card can have zero or more benchmark references
- Benchmarks are advisory references, not auto-applied templates
- Borrow and avoid notes are both required so the operator sees the boundary clearly

## Strategy Card

**Purpose**: Serves as the approved prewriting package that downstream outline and draft generation can follow.

**Fields**

- `project_slug`: owning content project
- `version`: ordered version within the project
- `problem_brief_version`: linked problem brief
- `reader_situation`: who the article is for right now
- `point_of_view`: the stance or narrative posture the article should take
- `conflict_frame`: how the core tension should be staged
- `emotional_path`: expected emotional progression across the article
- `expression_constraints`: banned or discouraged expression habits for this project
- `benchmark_summary`: short synthesis of benchmark guidance
- `status`: `needs_review`, `ready`, or `superseded`
- `created_at`: generation timestamp
- `adopted_at`: timestamp when the operator explicitly adopted it for writing

**Rules**

- Only one strategy card version can be the active `ready` card for a project at a time
- Manual operators may skip strategy-card generation entirely and continue on the legacy path
- Strategy cards remain attached to the project even after later versions supersede them

## Draft Diagnosis Report

**Purpose**: Records a structured assessment of one draft version before revision.

**Fields**

- `project_slug`: owning content project
- `draft_version`: linked draft version
- `version`: ordered diagnosis version for that draft family
- `opening_strength`: labeled assessment of the opening
- `scene_specificity`: labeled assessment of scene and detail density
- `viewpoint_clarity`: labeled assessment of perspective and argument clarity
- `progression_efficiency`: labeled assessment of paragraph advancement and repetition
- `ending_quality`: labeled assessment of the close or final emotional residue
- `ai_fingerprint_level`: labeled AI-like phrasing risk
- `upstream_findings`: strategy or angle problems discovered in the draft
- `downstream_findings`: expression or structure problems discovered in the draft body
- `recommended_next_action`: highest-priority operator action
- `created_at`: generation timestamp

**Rules**

- A draft can have multiple diagnosis reports over time
- Diagnosis findings must separate upstream and downstream issues
- Diagnosis itself does not mutate the draft

## Directional Polish Link

**Purpose**: Connects a revised draft version to the diagnosis or chosen objective that triggered it.

**Fields**

- `project_slug`: owning content project
- `source_draft_version`: draft version that was revised
- `target_draft_version`: resulting draft version
- `diagnosis_version`: optional linked diagnosis report
- `objective_key`: selected revision objective such as opening, progression, ending, or de-templating
- `objective_summary`: operator-facing summary of the chosen direction
- `created_at`: execution timestamp

**Rules**

- Manual polish remains valid without a diagnosis link
- Diagnosis-driven polish must keep a traceable objective even if the operator overrides the wording

## Creative Review Report

**Purpose**: Summarizes the project’s creative decisions and revisions in one reviewable artifact.

**Fields**

- `project_slug`: owning content project
- `version`: ordered report version
- `strategy_version`: latest strategy card included in the report
- `draft_version`: latest draft version included in the report
- `summary_markdown`: rendered report body
- `retained_lessons`: structured lessons extracted for possible reuse
- `created_at`: generation timestamp

**Rules**

- A project can generate reports even if some upstream artifacts are missing
- Reports should summarize available truth rather than force backfill

## Reusable Pattern

**Purpose**: Stores one operator-curated lesson or reusable creative rule promoted from a project report.

**Fields**

- `id`: stable identifier
- `source_project_slug`: project where the pattern came from
- `source_report_version`: originating creative review report
- `pattern_type`: category such as opening, benchmark pairing, conflict frame, ending restraint, or warning
- `title`: short operator-facing name
- `intended_use`: when this pattern is useful
- `pattern_content`: the reusable lesson itself
- `caution_notes`: limits or anti-copy guidance
- `status`: `active` or `archived`
- `created_at`: promotion timestamp

**Rules**

- Reusable patterns are optional references, never auto-applied defaults
- Archived patterns remain part of history but do not surface as active recommendations

## Project Detail Extensions

**Purpose**: Extends the existing project detail response with current creative workflow state.

**Fields**

- `problem_brief`: latest current problem brief or `null`
- `benchmarks`: current benchmark references for the active strategy package
- `strategy_card`: latest active strategy card or `null`
- `diagnosis_report`: latest diagnosis report for the current draft or `null`
- `creative_review_report`: latest project report or `null`

**Rules**

- Legacy projects may return `null` for all new creative-workflow artifacts
- Existing outline, draft, asset, publish-package, and retro fields remain unchanged
