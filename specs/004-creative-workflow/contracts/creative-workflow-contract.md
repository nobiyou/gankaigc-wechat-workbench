# Contract: Creative Workflow

## `GET /api/projects/{project_slug}`

### Response Additions

```json
{
  "project": {
    "slug": "relationship-boundary-reset-v2"
  },
  "problem_brief": {
    "version": 2,
    "status": "ready",
    "clarified_problem": "这篇文章要解释，为什么很多关系不是毁在大冲突，而是毁在一次次没被接住的小失望。"
  },
  "benchmarks": [
    {
      "reference_kind": "tracked_article",
      "reference_label": "深夜关系观察",
      "borrow_focus": "开头的处境进入和中段停顿节奏",
      "avoid_focus": "不要复用对方的判断句和结尾收束"
    }
  ],
  "strategy_card": {
    "version": 2,
    "status": "ready",
    "reader_situation": "在关系里想解释，却越来越不想开口的人",
    "point_of_view": "不教训，不站高位，只把失望是怎么累出来的讲清楚"
  },
  "diagnosis_report": {
    "version": 1,
    "draft_version": 3,
    "recommended_next_action": "先重写开头和中段推进，不要急着修句子"
  },
  "creative_review_report": {
    "version": 1,
    "created_at": "2026-05-30T19:30:00+08:00"
  }
}
```

All existing fields remain available and backward-compatible.

## `GET /api/projects/{project_slug}/versions`

### Response Additions

```json
{
  "project_slug": "relationship-boundary-reset-v2",
  "strategy_cards": [
    {
      "version": 1,
      "status": "needs_review"
    },
    {
      "version": 2,
      "status": "ready"
    }
  ],
  "diagnosis_reports": [
    {
      "version": 1,
      "draft_version": 3
    }
  ],
  "creative_review_reports": [
    {
      "version": 1
    }
  ]
}
```

Existing outline, draft, asset, and publish-package version arrays remain unchanged.

## `POST /api/projects/{project_slug}/generate-strategy-package`

### Behavior

- Builds a project-owned prewriting package from the current topic or original idea
- Creates a new problem brief, zero or more benchmark references, and a strategy card
- Does not mutate existing outline or draft versions

### Response

```json
{
  "project_slug": "relationship-boundary-reset-v2",
  "problem_brief": {
    "version": 2,
    "status": "ready"
  },
  "benchmarks": [
    {
      "reference_label": "深夜关系观察"
    }
  ],
  "strategy_card": {
    "version": 2,
    "status": "ready"
  }
}
```

## `POST /api/projects/{project_slug}/adopt-strategy-card/{version}`

### Behavior

- Marks the selected strategy card as the active writing reference for future outline generation
- Supersedes the previously active strategy card when one exists

### Response

Returns the adopted strategy card summary plus the project’s current chain state.

## `POST /api/projects/{project_slug}/generate-outline`

### Behavior Addition

- Preserve the existing route and response shape
- When an active adopted strategy card exists, outline generation uses that strategy package as the primary prewriting context
- When no adopted strategy card exists, outline generation continues to work through the legacy direct path

## `POST /api/projects/{project_slug}/diagnose-draft`

### Behavior

- Diagnoses the current draft or an explicitly selected draft version
- Separates upstream and downstream issues
- Produces a diagnosis report without mutating draft content

### Request

```json
{
  "draft_version": 3
}
```

### Response

```json
{
  "project_slug": "relationship-boundary-reset-v2",
  "draft_version": 3,
  "version": 1,
  "opening_strength": "weak",
  "scene_specificity": "medium",
  "viewpoint_clarity": "medium",
  "progression_efficiency": "weak",
  "ending_quality": "medium",
  "ai_fingerprint_level": "medium",
  "upstream_findings": [
    "开头切口仍然偏抽象，没有把目标读者放进具体处境里"
  ],
  "downstream_findings": [
    "中段解释连接词偏多，推进像总结而不是叙述"
  ],
  "recommended_next_action": "strengthen_opening_and_progression"
}
```

## `POST /api/projects/{project_slug}/polish-draft`

### Request Extension

The existing manual instruction path is preserved. The request body may now include diagnosis-driven fields:

```json
{
  "instruction": null,
  "diagnosis_report_version": 1,
  "objective_key": "strengthen_opening_and_progression"
}
```

### Behavior

- If `instruction` is present, manual polish continues to work as before
- If `diagnosis_report_version` and `objective_key` are provided, the revision is tied to the chosen diagnosis objective
- The response remains a standard draft version payload

## `POST /api/projects/{project_slug}/generate-creative-review-report`

### Behavior

- Builds a project-level review artifact from available strategy, diagnosis, draft, publish, and retro information
- Works for both new and legacy projects

### Response

```json
{
  "project_slug": "relationship-boundary-reset-v2",
  "version": 1,
  "summary_markdown": "# Creative Review\\n\\n...",
  "retained_lessons": [
    {
      "title": "开头先落到动作，不先落结论",
      "pattern_type": "opening"
    }
  ]
}
```

## `GET /api/creative-patterns`

### Behavior

- Lists active reusable patterns for strategy use and settings management
- Supports optional filtering by pattern type or source project in implementation, but filtering is not required for the first slice

## `POST /api/projects/{project_slug}/promote-creative-pattern`

### Request

```json
{
  "report_version": 1,
  "lesson_index": 0,
  "title": "开头先落到动作，不先落结论",
  "pattern_type": "opening",
  "intended_use": "适合写关系中的微妙失望，不适合写大道理开篇",
  "caution_notes": "不要把上一稿的具体句子直接拿来复用"
}
```

### Response

Returns the newly created reusable pattern with source-project context.
