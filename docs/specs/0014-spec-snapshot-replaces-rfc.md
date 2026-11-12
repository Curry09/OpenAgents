---
number: "0014"
title: "Replace RFCs with “Spec live snapshots + evolution history” — Specs always correspond one-to-one with the code, and legacy content is retained in history"
issue: 35
slug: spec-snapshot-replaces-rfc
summary: "Replace RFCs with “Spec live snapshots + evolution history”: Specs always correspond one-to-one with the current code; older versions are retained in history, which is no longer a running log. Includes the data layer/schema, validate, render (OVERVIEW), amend/abandon, CLI, and migration."
tasks:
  - id: T1
    title: "Data layer + JSON Schema + dependency/entry point declarations"
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/__init__.py
      - openagents/spec/model.py
      - openagents/spec/schema.py
      - pyproject.toml
      - tests/test_spec_model.py
    scope: "Create the openagents/spec/ package; model.py defines RelatesTo/Task/Metadata/Group and load_group/load_all/dump_task/qualified_id (use ruamel.yaml round-trip reading and writing to preserve block scalars and key order); schema.py defines TASK_SCHEMA/METADATA_SCHEMA/HISTORY_SCHEMA (JSON Schema draft 2020-12, covering all Task fields + enums). In pyproject.toml: add ruamel.yaml and jsonschema to dependencies; add spec = \"openagents.spec.cli:main\" under [project.scripts]."
    acceptance: "Unit tests cover fidelity across a load→dump→load round trip (block scalars, key order, relates-to lists); omitted optional fields (tags/tests/open-questions, etc.) have reasonable defaults; load_all aggregates multiple groups; qualified_id constructs NNNN/T*; all three schemas in schema.py are themselves valid JSON Schema (compilable by jsonschema). After pip install -e ., the spec entry point can be resolved (even though cli is implemented in T5, put the entry point declaration in place first)."
  - id: T2
    title: "spec validate (schema + semantic validation)"
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/validate.py
      - tests/test_spec_validate.py
    scope: "validate.py: ValidationIssue/ValidationReport + validate(), running checks in this order: JSON Schema validation → status is valid and consistent with the final state in history → no overlapping files within the same group (error) → the global depends-on DAG (including cross-group dependencies) is acyclic (error) → lineage/cross-group references exist (error) → cross-group files overlap (warning)."
    acceptance: "Unit tests use temporary specs trees to cover positive and negative cases for every rule: schema noncompliance → error; overlapping files within the same group → error; construct a cycle → cycle detected as an error; cross-group depends-on points to a nonexistent Task → error; cross-group files overlap → warning only and ok=True; fully compliant → ok=True with no issues."
  - id: T3
    title: "spec render → OVERVIEW.md (boards/relationship graph/conflicts/DAG/evolution graph)"
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/render.py
      - tests/test_spec_render.py
    scope: "render.py: render() (a pure function returning the full text, idempotent) + write_overview(). Generate four sections: a global board table, a cross-feature relationship graph (Mermaid subgraph, solid lines for depends-on / dashed lines labeled with type for relates-to), a file conflict report (cross-group files overlap), and per-feature sections (intra-group board + dependency DAG + evolution graph: nodes = Task versions, colored by status, with edges drawn from lineage fields)."
    acceptance: "Unit tests verify that two render calls with fixed input produce byte-for-byte identical output (idempotence); the output contains all four section headings; the number of board rows = the total number of current-version Tasks; the relationship graph contains cross-group dashed edges; the evolution graph contains a v1→v2 edge for a Task and coloring for abandoned nodes; an empty repository causes no errors."
  - id: T4
    title: "spec amend / abandon (append history + automatic render)"
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/spec/mutate.py
      - tests/test_spec_mutate.py
    scope: "mutate.py: amend() (append the current version to history/T*.yaml → overwrite tasks/T*.yaml with the new version with version+1/updated=today/change_reason → call render); abandon() (append the current task to history with the final status abandoned → delete it from tasks/ → render)."
    acceptance: "Unit tests: after amend, history length increases by 1 and includes a complete snapshot of the old version, tasks contains the new version with version incremented, and OVERVIEW.md is rewritten; version numbers increase monotonically across consecutive amend calls; after abandon, the file is absent from tasks/ and the final history entry has status=abandoned; amend on a nonexistent task → an error without damaging files."
  - id: T5
    title: "spec CLI + number validation script + CI integration"
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T2
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/spec/cli.py
      - scripts/check-spec-number-conflicts.py
      - .github/workflows/ci.yml
      - tests/test_spec_cli.py
    scope: "cli.py: main() routes render/amend/abandon/validate (if validate has an error → nonzero exit code). scripts/check-spec-number-conflicts.py: port check-rfc-number-conflicts.py, changing the path regex to docs/specs/(NNNN)-slug/, and check for conflicts across the union of local entries + open PRs. .github/workflows/ci.yml: rfc-conflicts job → spec-conflicts (calls the new script); add a spec validate step and an OVERVIEW drift-check (git diff --exit-code after spec render); update the gate job's needs/aggregation."
    acceptance: "Unit tests with a stubbed filesystem: spec render writes OVERVIEW; spec validate returns a nonzero exit code when there are errors and 0 when there are only warnings; spec amend/abandon route to mutate. check-spec-number-conflicts.py reports conflicts for duplicate numbers under docs/specs/ and passes unique numbers (stub gh). ci.yml is valid YAML and contains spec-conflicts + validate + drift steps."
  - id: T6
    title: "Migration script + spec-driven skill + specs README + e2e"
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/migrate-rfc-to-spec.py
      - tests/test_migrate_rfc_to_spec.py
      - .claude/skills/spec-driven-development/SKILL.md
      - .claude/skills/spec-driven-development/references/
      - docs/specs/README.md
      - scripts/e2e-spec-0014-spec-driven.sh
    scope: "scripts/migrate-rfc-to-spec.py: each docs/rfcs/NNNN-*.md → one spec group (metadata.yaml + tasks/ + origin.md); RFC header + each row in the subtask table → tasks/T*.yaml (status mappings: implemented→done, blocked→pending; parse files/depends-on; dependencies at the whole-RFC level in RFC-NNNN form do not constitute Task dependencies and are therefore discarded; extract each row's scope/acceptance criteria into scope/acceptance); retain the group-level body in origin.md within the group (read-only, not read by render). Migration produces current-version Tasks with version=1 and initially empty history. Rewrite the skill: .claude/skills/spec-driven-development/ (SKILL.md + references, including Task JSON Schema documentation, the # Spec-NNNN/T* comment convention, and the three-phase workflow). docs/specs/README.md (directory documentation + numbering rules). scripts/e2e-spec-0014-spec-driven.sh (end-to-end: migration→validate→render→amend→validate again/render idempotence)."
    acceptance: "Unit tests run migration on 1–2 real RFCs and assert that the output passes spec validate, the Task count = the number of atomic task rows, implemented→done, blocked→pending, and the output has version=1 with initially empty history; after migrating all 13 RFCs, spec validate passes all checks (only cross-group file warnings) and spec render is idempotent (no diff between two runs). The skill's SKILL.md contains the three phases + Task schema + new comment convention; docs/specs/README.md contains the numbering rules. The e2e script can run independently."
---

# 0014 · Replace RFCs with “Spec Living Snapshots + Evolution History” — Specs Always Correspond One-to-One with Code, with Legacy Content Archived in History

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Replace the original RFC documentation system with “Spec living snapshots + evolution history”: each Spec always corresponds one-to-one with the **current code** (describing “what exists now,” rather than “what was once decided to change”). Every change uses `amend` to archive the entire previous version in `history/` and overwrite `tasks/` with the new version. The Spec body thus ceases to be an incrementally appended log and instead becomes a living snapshot that always matches the current state of the code; previous versions remain traceable without cluttering the current view. The complete capability is implemented in 6 Tasks: structured data layer + JSON Schema (T1), `spec validate` semantic validation (T2), `spec render` OVERVIEW generation (T3), `spec amend/abandon` history appending (T4), `spec` CLI + number validation + CI integration (T5), and RFC→Spec migration script + skill + e2e (T6).

## Motivation

**Current state: RFCs are append-only logs.** OpenAgents originally used `docs/rfcs/NNNN-*.md` to hold design decisions. An RFC means “one proposal + a set of subtasks”; it records “what we intended to change at the time.” As the same code undergoes repeated iterations, an RFC is either superseded by a new RFC or maintained by appending sections to the original text. Over time: ① To find out “what a module looks like now,” readers must read several related RFCs, along with all their appended sections, from beginning to end, then mentally merge their timelines; ② legacy (superseded decisions) and current (the present state) are mixed in the same document, with no mechanically verifiable relationship establishing that “this RFC matches the code”; ③ subtask dependencies, file ownership, and statuses are scattered across Markdown tables, so tools cannot check for cycles or detect two Tasks competing for the same file.

**The problem: why change this.** What we want is a **living snapshot that corresponds one-to-one with the code**: reading the current Spec is equivalent to reading the current state of the code, without reconstructing a timeline. Previous versions are archived in `history/` for auditing, while the default view always stays clean. At the same time, “Task dependencies / single-writer file ownership / status / lineage” are upgraded from free-form Markdown to **structured fields**, enabling `validate` to perform mechanical checks (an acyclic DAG, no file overlap within a group, and valid cross-group references), and enabling `render` to automatically produce a global board and evolution diagrams. People no longer maintain consistency manually; tools enforce it.

## Guide-level explanation

One Spec group = `metadata.yaml` (group-level metadata) + `tasks/T*.yaml` (one **current-version** structured snapshot per Task) + `history/T*.yaml` (the Task’s previous versions, whose final state may be `abandoned`) + `origin.md` (the read-only group-level body migrated from the RFC, which render does not read). Core Task fields include `status`/`priority`/`depends-on`/`relates-to` (lineage)/`files` (single-writer file ownership)/`scope`/`acceptance`/`version`.

Three routine actions:
- **`spec validate`**: Run schema + semantic validation as a CI gate; exit with a nonzero code if there are errors.
- **`spec render`**: Idempotently generate `OVERVIEW.md` from the current-version Tasks across all groups (global board + cross-feature relationship diagram + file conflict report + dependency DAG and evolution diagram for each feature).
- **`spec amend <NNNN/T*>` / `spec abandon`**: When changing a Task, first append its current version to `history/`, then overwrite `tasks/` with a new version at `version+1` (`amend`), or delete it from `tasks/` and mark its final state in history as `abandoned` (`abandon`). Both automatically rerun render. The invariant “Specs always match the current state of the code” is therefore guaranteed by the actions themselves, rather than by individual discipline.

For old content migrated from RFCs: the migration script splits each RFC into a Spec group, converts subtask rows into `tasks/T*.yaml`, and preserves the entire original design body in `origin.md`. All migration outputs are current versions with `version: 1`, and `history/` is initially empty (v1 is written there only on the first `amend`, avoiding duplicate v1 entries).

## Reference-level explanation

The changes are broken down into 6 Tasks (`files` are mutually exclusive, with each Task acting as the sole writer):

1. **T1 Data layer + JSON Schema + entry point** — Create the `openagents/spec/` package. `model.py` defines the `RelatesTo`/`Task`/`Metadata`/`Group` data classes and `load_group`/`load_all`/`dump_task`/`qualified_id`, using `ruamel.yaml` round-trip reads and writes to **preserve block scalars and key order** (a prerequisite for render idempotence). `schema.py` provides `TASK_SCHEMA`/`METADATA_SCHEMA`/`HISTORY_SCHEMA` (JSON Schema draft 2020-12). Add the `ruamel.yaml`/`jsonschema` dependencies to `pyproject.toml` and declare the `spec` entry-point script. This is the single source of structured data for the entire pipeline.

2. **T2 spec validate** (depends on T1) — `validate.py` provides `ValidationIssue`/`ValidationReport`/`validate()`, performing the following in order: JSON Schema validation → status is valid and consistent with the final state in history → **no overlapping files within a group (error)** → the global `depends-on` DAG (including cross-group dependencies) is **acyclic (error)** → lineage/cross-group references exist (error) → overlapping files across groups (warning). Only errors cause CI to fail; cross-group overlap produces warnings only.

3. **T3 spec render** (depends on T1) — The pure function `render()` in `render.py` returns the full text (idempotently), and `write_overview()` writes it to disk. It produces four parts: a global board table, a cross-feature relationship diagram (Mermaid, with solid lines for `depends-on` / dashed lines labeled with type for `relates-to`), a file conflict report, and per-feature sections (an in-group board + dependency DAG + evolution diagram: nodes = Task versions, colored by status, with edges based on lineage fields).

4. **T4 spec amend / abandon** (depends on T1, T3) — `mutate.py`: `amend()` appends the current version to `history/T*.yaml`, then overwrites `tasks/T*.yaml` with `version+1` (`updated` = today, with `change_reason` recorded), and calls render at the end; `abandon()` appends the current task to history and sets its final state to `abandoned`, deletes it from `tasks/`, and runs render. This is the write path that maintains the “living snapshot” invariant.

5. **T5 CLI + number validation + CI** (depends on T2, T3, T4) — `main()` in `cli.py` routes `render`/`amend`/`abandon`/`validate` (validate has errors → nonzero exit code). `scripts/check-spec-number-conflicts.py` is ported from `check-rfc-number-conflicts.py`, with the path regex changed to `docs/specs/(NNNN)-slug/`, and checks for conflicts across the union of local changes and open PRs. `ci.yml`: change the original `rfc-conflicts` job to `spec-conflicts`, add a `spec validate` step + OVERVIEW drift-check (`git diff --exit-code` after `spec render`), and update the `gate` job’s `needs`/aggregation.

6. **T6 Migration + skill + README + e2e** (depends on T2, T3) — `scripts/migrate-rfc-to-spec.py` splits each `docs/rfcs/NNNN-*.md` into a Spec group (`metadata.yaml` + `tasks/` + `origin.md`): the RFC header (priority/labels/issue) + each subtask table row → `tasks/T*.yaml` (status mappings: `implemented`→`done`, `blocked`→`pending`; parse `files`/`depends-on`; **whole-RFC dependencies in the form `RFC-NNNN` do not constitute Task dependencies and are therefore discarded**; extract each row’s `scope`/`acceptance criteria` into `scope`/`acceptance`). Preserve the group-level design/motivation/interface contracts/tradeoffs/references in their entirety in `origin.md` (read-only; render does not read it). Migration produces current versions with `version: 1`, and `history/` is initially empty. Rewrite `.claude/skills/spec-driven-development/` (SKILL.md + references, including Task JSON Schema documentation, the `# Spec-NNNN/T*` comment convention, and the three-phase workflow clarify→design→implementation and verification). Add `docs/specs/README.md` (directory documentation + numbering rules).

**End-to-end verification**: `bash scripts/e2e-spec-0014-spec-driven.sh` (end-to-end execution: migrate → validate → render → amend → validate again / verify render idempotence).

Dependency DAG: `T1 → T2`, `T1 → T3`, `T1 → T4`, `T3 → T4`, `T2 → T5`, `T3 → T5`, `T4 → T5`, `T2 → T6`, `T3 → T6`.

## Drawbacks

- Introducing two sets of files, “current version + history,” along with the `amend`/`abandon` write paths, is conceptually heavier than a single append-only Markdown document; changing a Task requires using `amend` rather than editing the body directly.
- Structured YAML + JSON Schema impose stronger formatting constraints on authors (block scalars, key order, enum values), creating a one-time learning cost.
- The rendered OVERVIEW is a derived artifact and requires CI’s drift-check to prevent divergence from the source data, adding another CI gate.

## Rationale and alternatives

- **Why living snapshots instead of continuing to append to RFCs**: The append-only nature of RFCs means that “reading the current state” requires merging timelines; living snapshots ensure that the current version always matches the current state of the code, while archiving previous versions in history enables auditing without cluttering the default view. This directly serves the goal of “people handling the big picture, tools ensuring consistency.”
- **Why structured YAML instead of free-form Markdown**: Only structured fields enable `validate` to mechanically check that the DAG is acyclic, files within a group have a single writer, and cross-group references exist, and enable `render` to automatically produce boards/evolution diagrams; free-form Markdown cannot be validated by tools.
- **Alternative: retain RFCs and only add an indexing tool**. Rejected: indexing cannot address the root causes of “legacy and current content mixed in one document” and “dependencies/file ownership that cannot be validated.”
- **Why use ruamel.yaml round-trip**: Preserving block scalars and key order is a prerequisite for byte-level render idempotence; ordinary yaml libraries lose formatting, causing false positives in drift-check.
- **Migration produces version:1 with empty history**: This is consistent with `amend` semantics of “append the current version first, then bump,” avoiding duplicate v1 entries in history after the first amend.

## Prior art

“Documentation as a snapshot of the current code” and “structured metadata + a validation/rendering toolchain” are common industry practices (such as using machine-readable frontmatter to hold status, linting dependency graphs, and generating overviews with generators). Semantic status transitions (done/pending/abandoned) and dependency DAG validation also come from standard engineering practice. This feature adopts the core of “structured source data + automatically generated derived views + CI drift prevention” without introducing a heavier external documentation system.

## Unresolved questions

None. The data model fields, validation rule set, four-part render structure, amend/abandon semantics, and migration mapping rules have all been settled in this group.

## Future possibilities

- The single-writer declaration in `files` could further drive “automatic Task dispatch based on file ownership / parallel conflict detection” (providing a foundation for issue #71).
- render could support additional views (such as aggregation by owner or milestone) or export results as a dashboard for frontend visualization.
- `validate` could incorporate additional policies (such as requiring every done Task to have acceptance, or making cross-group file overlap a configurable error).
</content>
</invoke>
