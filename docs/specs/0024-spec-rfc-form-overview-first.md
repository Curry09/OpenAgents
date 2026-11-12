---
number: "0024"
title: "Convert specs to rust-RFC format: overview first + each spec self-contained"
issue: 69
slug: spec-rfc-form-overview-first
summary: "Restructure specs around a nine-section rust-RFC overview (overview first, each spec self-contained), moving the DAG + file assignments into Reference-level; align the data model/validation/skill/README/orchestrator, and backfill 19 existing specs."
tasks:
  - id: T1
    title: "Spec data model: nine-section group-level Overview + streamlined Task"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/model.py
      - tests/test_spec_model.py
    scope: "Add a nine-section Overview dataclass + Group.overview; remove duplicated prose from Task and move scope/acceptance into frontmatter; change body parsing/rendering to use rust section names."
    acceptance: "Round-trip fidelity for the nine group-level sections + task scope/acceptance; no `## T` subsections in the body, and scope goes into frontmatter."
  - id: T2
    title: "Validation quality bar: required sections + self-containment warnings + streamlined schema"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/schema.py
      - openagents/spec/validate.py
      - tests/test_spec_validate.py
    scope: "Add files/acceptance to TASK_SCHEMA required and streamline _PROSE_KEYS; add checks to validate for four required sections being nonempty (error) + bare cross-spec references (warning)."
    acceptance: "Empty required section → error; “see Spec-NNNN” → warning without breaking ok; missing acceptance → schema error."
  - id: T3
    title: "Nine-section scaffolding for spec new + signpost/cli/mutate adaptations"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/spec/signpost.py
      - tests/test_spec_signpost.py
      - tests/test_spec_cli.py
      - tests/test_spec_mutate.py
    scope: "Include nine section headings in the spec new body; change signpost to extract e2e script clues from the group-level Overview instead of the deleted Task.tests; fix the adaptation tests."
    acceptance: "spec new produces nine sections; signpost extracts scripts/*.sh from Overview (Reference-level); pytest passes all tests."
  - id: T4
    title: "Align skill + references + README + orchestrator with rust-RFC"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - .claude/skills/spec-driven-development/SKILL.md
      - .claude/skills/spec-driven-development/references/task-fields.md
      - docs/specs/README.md
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: "Change SKILL Phase 2 to “write the nine-section overview first → then add-task” + a quality bar (self-containment, turning soft conventions into hard requirements); align README with the rust RFCs README; update the orchestrator's task assignment prompt accordingly."
    acceptance: "The skill/README explicitly state the two rules: overview first + each spec self-contained; orchestrator tests pass."
  - id: T5
    title: "Backfill 19 existing specs + e2e scripts"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0024-rfc-form.sh
      - docs/specs/0023-retire-test-branch-main-advancing-release.md
    scope: "Rewrite each existing spec as a nine-section overview + frontmatter tasks (scope/acceptance), restating necessary information from other specs locally; add e2e scripts demonstrating the new workflow."
    acceptance: "spec validate reports 0 errors; the e2e scripts' ruff+pytest+spec CLI workflow passes all checks."
---

# 0024 · Convert specs to rust-RFC form: overview first + self-contained individual specs

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview with the 9 rust-RFC sections. -->

## Summary

Change OpenAgents specs from “a Task DAG skeleton + prose for each Task” to “a feature-level overview with the 9 rust-RFC sections as the main body, with the DAG + file assignments placed in Reference-level,” so that any individual spec can be read on its own, with the overview first (issue #69).

## Motivation

The old form has two fundamental readability problems: ① Individual specs are not self-contained—the body contains many cross-spec references such as “see Spec-00XX decision N,” pushing key design rationale elsewhere and forcing readers to consult several specs to piece together the complete meaning; ② Tasks are broken down before there is a feature overview—`spec new` is immediately followed by `add-task`, with only a one-sentence summary at the group level, so readers initially face a Task table without an overall understanding. There is also a hidden flaw: the old data model does not parse group-level overview sections at all (the parser only recognizes `## T<n>`), so a manually written overview will be discarded on the next `spec render`.

## Guide-level explanation

The author creates a group with `spec new` (which automatically lays out scaffolding for 9 sections) → **first fills out the group-level overview with all 9 rust-RFC sections** (Summary/Motivation/Guide-level/Reference-level/Drawbacks/Rationale and alternatives/Prior art/Unresolved questions/Future possibilities) → **then** uses `spec add-task` to add work breakdown rows. A reader who receives a spec can understand the entire feature after reading the 9 sections, without opening other specs.

## Reference-level explanation

Data model (`openagents/spec/model.py`): add a group-level `Overview` dataclass with 9 sections + `Group.overview`; remove redundant prose fields from Task, and move `scope`/`acceptance` into frontmatter; change body parsing/rendering from “`## T<n>` Task subsections” to “`## <rust section name>` group-level sections.” Validation (`schema.py`/`validate.py`): add `files`/`acceptance` to TASK_SCHEMA required; add “the four required sections (Summary/Motivation/Reference-level/Rationale) must be nonempty = error” and “bare cross-spec references in the overview = warning.” `spec new` produces scaffolding for 9 sections; change signpost to extract e2e scripts from the group-level Overview. Align skill/README/orchestrator wording; backfill 19 existing specs.

The frontmatter `tasks[].files` remains the structured machine-readable source—this is a single-writer ownership declaration (principle 6), and also the source for the runtime owner checks in issue #71.

Task breakdown (files are mutually exclusive, with a single writer per Task): T1 data model; T2 validation quality gates; T3 scaffolding + signpost/cli adaptation; T4 skill+README+orchestrator; T5 backfill + e2e.

**End-to-end verification**: `bash scripts/e2e-spec-0024-rfc-form.sh` (ruff + pytest + spec CLI workflow exercise).

Dependency DAG: `T1 → T2 → T3`, with T4/T5 depending on T3. For detailed design rationale, see the dated design document docs/specs/2026-06-25-spec-rfc-form-design.md.

## Drawbacks

9 sections may be somewhat heavy for very small features (most sections will be very short or contain “None”); backfilling 19 existing specs in one pass makes for a large PR with a broad review scope.

## Rationale and alternatives

Based on rust-lang/rfcs 0000-template.md (9 sections) and README. **Alternative A: a single freeform overview field** (without requiring 9 sections)—more economical, but makes it difficult to establish stable, verifiable quality gates; rejected. **Alternative B: remove Tasks and use a pure design document**—would eliminate the within-group parallelism enabled by file assignments under principle 6; rejected. Instead, use the 9 RFC sections as the main body + retain the tasks DAG in frontmatter, providing both machine readability and human readability. **Bare cross-spec references initially produce a warning rather than an error**: this avoids blocking the backfill of existing specs at the outset; once all checks pass, this can be upgraded to an error.

## Prior art

rust-lang/rfcs: RFCs precede implementation + one RFC explains a feature in a self-contained way (9 sections: Summary/Motivation/Guide-level/Reference-level/Drawbacks/Rationale/Prior art/Unresolved/Future). This group adopts its template and “self-contained” principle, adapting them to OpenAgents frontmatter+tasks DAG.

## Unresolved questions

When to upgrade bare cross-spec references from warning to error (after all existing specs pass); whether `tasks[].acceptance` should be required even for very lightweight wrap-up Tasks (currently: yes, to maintain verifiability).

## Future possibilities

issue #71: advance the files assignments in Reference-level from design-time declarations to runtime owner enforcement (lease/CAS/capability), with a single writer for shared state + reads from versioned snapshots.
