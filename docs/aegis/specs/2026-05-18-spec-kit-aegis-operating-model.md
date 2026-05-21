# Spec Kit + Aegis Operating Model

## Goal

Define how `spec-kit` and `Aegis` coexist in this project without creating duplicate specs, plans, or task lists.

## Scope

This document applies to all future feature work in `gankaigc-wechat-workbench`.

## Decision

Use a balanced split:

- `spec-kit` owns feature delivery artifacts
- `Aegis` owns execution discipline and project governance

## Ownership Split

### `spec-kit` owns

- Feature specification drafts
- Implementation plans for a specific feature
- Task breakdowns for a specific feature
- Workflow commands used to move from idea to executable task list

### `Aegis` owns

- Project baseline and architecture guardrails
- Governance rules and compatibility boundaries
- Evidence-first execution discipline
- Verification expectations before claiming completion
- Long-task continuity and change review hygiene

## Directory Rules

### `spec-kit` primary artifacts

- `.specify/`
- `.agents/skills/speckit-*`

### `Aegis` primary artifacts

- `docs/aegis/baseline/`
- `docs/aegis/specs/`
- `docs/aegis/plans/`
- `docs/aegis/INDEX.md`
- `docs/aegis/BASELINE-GOVERNANCE.md`

## Anti-Duplication Rules

Do not maintain the same feature in two parallel planning systems.

- A feature-level spec should have one primary owner: `spec-kit`
- A feature-level implementation plan should have one primary owner: `spec-kit`
- A feature-level task list should have one primary owner: `spec-kit`
- Architecture baseline, module boundaries, and governance notes should live in `Aegis`

## When To Write Into `docs/aegis/specs`

Write a project-level Aegis spec only when at least one of these is true:

- The change affects architecture ownership or module boundaries
- The change introduces a new long-lived subsystem
- The change modifies compatibility expectations
- The change needs a governance decision beyond one feature

Do not create an Aegis spec for every normal feature if `spec-kit` already owns the feature spec.

## Standard Feature Flow

For a normal product feature, use this order:

1. `spec-kit` creates or updates the feature spec
2. `spec-kit` creates the feature plan
3. `spec-kit` creates the task list
4. `Aegis` reads relevant baseline and governance docs before implementation
5. Implementation proceeds under Aegis execution discipline
6. If architecture or governance changed, update `docs/aegis/` before closing the work

## Current Project Interpretation

For this project:

- Hotspot discovery, topics, projects, drafts, publish packages, and tone profiles are normal feature work
- Content-domain boundaries, workflow ownership, and migration strategy are project-level architecture concerns

That means:

- New feature delivery should start from `spec-kit`
- Cross-cutting structure decisions should still be recorded in `docs/aegis/`

## Compatibility Boundary

The following must remain true unless explicitly changed:

- `spec-kit` does not become the owner of project governance
- `Aegis` does not create duplicate feature plans when `spec-kit` already owns them
- A single feature should not require contributors to reconcile two competing task lists

## Immediate Working Agreement

Starting now:

- Keep the existing project direction documents under `docs/aegis/`
- Use `spec-kit` as the default entrypoint for new feature work
- Use `Aegis` as the default execution and review discipline

## Review Trigger

Revisit this operating model if one of the following happens:

- `spec-kit` artifacts start drifting from actual implementation
- `Aegis` usage begins recreating feature plans already present in `spec-kit`
- The project expands into multi-repo or multi-team coordination
