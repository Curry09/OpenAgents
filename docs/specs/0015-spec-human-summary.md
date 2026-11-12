---
number: "0015"
title: "Human-readable spec summary: populate the group-level summary field + render a plain-language TL;DR"
issue: 58
slug: spec-human-summary
summary: "Add a plain-language TL;DR for human readers to every spec: add a group-level summary field to metadata, require it in spec new, enforce a nonempty value in validate, display it for each feature at the top of OVERVIEW in render, and migrate all existing specs to populate it. This is the foundation for the human oversight gate in #59."
tasks:
  - id: T1
    title: "Data layer: add a group-level summary field to metadata"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/schema.py
      - openagents/spec/model.py
      - tests/test_spec_model.py
    scope: "Data layer only. In schema.py, add a summary property to METADATA_SCHEMA (string, not marked required); in model.py, add a summary field to the Metadata dataclass (after slug), make _load_metadata backward-compatible with old files (fall back to an empty string when the field is missing), and fix the key order in dump_metadata to title/issue/slug/summary. Excludes CLI, validate, render, and content migration."
    acceptance: "A Metadata instance with summary preserves its contents through a dump_metadata→_load_metadata round trip; dump output uses the key order title/issue/slug/summary; reading an old metadata.yaml (without a summary key) yields summary == ''; the schema accepts a string summary and rejects non-string values; ruff + pytest pass."
  - id: T2
    title: "Authorized path: spec new --summary (cli + mutate)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/mutate.py
      - openagents/spec/cli.py
      - tests/test_spec_mutate.py
      - tests/test_spec_cli.py
    scope: "Authorized write path. Add a summary parameter to mutate.create_group (no default, passed by keyword) and write it into Metadata; add --summary (required=True) to the new subcommand in cli.py, and pass it through in _cmd_new. Keep routing thin, with no business logic in cli. Excludes schema/validate/render/migration."
    acceptance: "spec new <slug> --issue N --title T --summary S exits with code 0 and writes metadata.yaml containing that summary; omitting --summary causes an argparse error and exit code 2; create_group(..., summary=...) writes the correct data to disk; ruff + pytest pass."
  - id: T3
    title: "Gate: validate enforces a nonempty summary"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/validate.py
      - tests/test_spec_validate.py
    scope: "Append a seventh validation chain, _summary_checks, after the existing six validation chains (one semantic rule): iterate over every Group and read metadata.summary; if it is empty after .strip(), produce an error (covering a missing field, an empty string, and whitespace-only values, with one clear message in Chinese), with where pointing to that group's metadata.yaml. Keep validate a pure function, unaware of git/GitHub. Do not change schema/model/render or perform migration."
    acceptance: "A missing/empty/whitespace-only summary → validate reports an error with ok=False and exit code 1; a nonempty summary → no such error; when only one of multiple groups has an empty summary, where points precisely to that group; ruff + pytest pass."
  - id: T4
    title: "Human-readable view: TL;DR block at the top of render output"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/render.py
      - tests/test_spec_render.py
    scope: "render only. Insert a top-level TL;DR block, _render_tldr, before the global board table in render(), outputting `### {number} {title}` + metadata.summary for each group; add the constant _TLDR_HEADING. Preserve function purity and idempotence, and handle an empty repository without errors. Do not change schema/model/validate/data content."
    acceptance: "render output contains a TL;DR block before the board table, with one summary per feature, positioned before _BOARD_HEADING; two render runs produce byte-for-byte identical output; an empty repository causes no errors and still includes the TL;DR heading; ruff + pytest pass."
  - id: T5
    title: "Migration: populate summary for the 14 existing specs + re-render"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - docs/specs/OVERVIEW.md
    scope: "Data migration only. Populate metadata.yaml for each of 0001–0014 and this group, 0015, with an evidence-based, plain-language summary (what this is/why it is being done/what it produces/what it does not do), then regenerate OVERVIEW.md with spec render and confirm 0 errors with spec validate. Content edits to each metadata.yaml are execution work and are not included in files (files lists only the sole output, OVERVIEW.md), so they inherently avoid conflicts with other Tasks' code files. Do not change any code."
    acceptance: "Every existing group's metadata.yaml has a nonempty, plain-language summary; spec validate passes all checks (0 errors, including all of T3's nonempty-summary checks); after spec render, OVERVIEW.md has no git drift; the top of OVERVIEW makes every feature understandable at a glance."
---

# 0015 · Human-readable spec summary: populate the group-level summary field + render a plain-language TL;DR

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Add a **plain-language TL;DR for human readers** to every spec, so people can immediately understand “what this feature does” without first reading a dense table. It belongs in a new `summary` field in the **group/feature-level metadata**, `metadata.yaml` (alongside `title`/`issue`/`slug`), rather than reusing the per-Task `summary` prose. This group establishes the field at the data layer (T1), makes it mandatory when creating a group (T2 `spec new --summary`), enforces nonempty values through a CI gate (T3 validate), displays it for each feature at the top of the human-readable view (T4 render TL;DR block), and finally backfills all existing specs and re-renders them (T5). This is the foundation for issue #59’s “human oversight gate”—before a human can approve anything at the gate, there must first be something written for them to read.

## Motivation

**Current state: specs have no entry point for human readers.** Currently, a spec’s per-Task `summary` prose field is at task granularity, and all such fields are empty; `OVERVIEW.md` starts with a dense table of task IDs/files/statuses (the global dashboard), which is extremely unfriendly to human readers. People cannot understand at a glance “what this spec does.”

**Why change this.** A TL;DR is a **feature/group**-level concept (“what this feature is, why we are building it, what it delivers, and what it does not do”), not a task-level concept. Issue #58 explicitly says to “populate the group/feature-level summary” and positions it as the **foundation** for #59’s “human oversight gate”—before people can “read a spec and approve it,” there must be a plain-language passage to read. This therefore requires: (1) establishing a summary field in group-level metadata as the single storage location; (2) ensuring it is actually populated (two layers of enforcement: mandatory at group creation + a CI gate); (3) rendering it at the top of OVERVIEW; (4) backfilling all existing specs, otherwise the gate will immediately make the repository’s own CI fail when introduced.

## Guide-level explanation

For users:

- When creating a group, `--summary` in `spec new <slug> --issue N --title T --summary S` becomes **required**—making “write the TL;DR” a mandatory step in group creation rather than something to fill in afterward. Omitting it is caught by argparse at group creation time (exit code 2), rather than remaining undiscovered until CI.
- At the CI layer, `spec validate` gains another gate: if any group’s `metadata.summary` is empty (missing field / empty string / whitespace only), it reports an error, elevating “every feature has a plain-language TL;DR” from a “group creation convention” to an “invariant that always holds across the repository.”
- For human readers, a “TL;DR (plain-language overview)” block is added at the **top** of `OVERVIEW.md`, listing each feature’s `summary` so readers can immediately understand what each feature does without first working through the dense table below.

The two enforcement mechanisms complement each other: fail-fast at authoring (T2 required argument) + gate at CI (T3 validate catches omissions from manual edits/migration).

## Reference-level explanation

The changes are broken down into 5 Tasks (see the DAG below; `files` are mutually exclusive, with a single writer for each Task):

1. **T1 Data layer** (no dependencies; the foundation)—`openagents/spec/schema.py`, `openagents/spec/model.py`, `tests/test_spec_model.py`. Add `summary: {type: string}` to `METADATA_SCHEMA.properties` in `schema.py` (because the metadata schema has `additionalProperties: False`, any file containing summary would otherwise fail schema validation—this is a prerequisite for writes by T2/T5); **do not set `required`**: leave “nonempty” semantics to T3’s semantic validation chain for consistent handling. Add a `summary: str` field to the frozen `Metadata` dataclass in `model.py` (after slug, with an empty-string default for compatibility with old call sites/files); add `summary=str(raw.get("summary", ""))` to `_load_metadata` (fall back to an empty string when the field is missing, allowing old files to be read smoothly during migration); expand the payload in `dump_metadata` from `[title, issue, slug]` to `[title, issue, slug, summary]`, with a fixed key order—this is the single source for output written by `spec new`/migration, ensuring it does not drift. Use a plain scalar for summary (the TL;DR is short, and a block scalar would make metadata.yaml verbose).
2. **T2 Authorized path** (depends on T1)—`openagents/spec/mutate.py`, `openagents/spec/cli.py`, `tests/test_spec_mutate.py`, `tests/test_spec_cli.py`. Add a `summary: str` parameter to `mutate.create_group` (without a default, following the repository’s convention that “callers pass arguments explicitly”), and construct `Metadata(..., summary=summary)`; leave the remaining logic (directory creation, dump_metadata, render) unchanged. Add `--summary` (`required=True`) to the `new` subparser in `cli.py`, and pass it through in `_cmd_new`—thin routing, with no business logic in cli.
3. **T3 Gate** (depends on T1)—`openagents/spec/validate.py`, `tests/test_spec_validate.py`. validate currently runs “six validation chains” in sequence (JSON Schema structural validation first + five semantic chains), with `ok=True` if there are no errors. This Task adds a new internal function `_summary_checks(*, groups: list[Group]) -> list[ValidationIssue]` (structured like the existing `_status_checks`): iterate over each Group and retrieve `group.metadata.summary`; if `.strip()` is empty → produce `ValidationIssue(level=error, where="<NNNN>/metadata.yaml", message="metadata.summary is empty (every feature must have a plain-language TL;DR)")`; in the main `validate()` flow, `extend` `issues` with the results immediately after the existing chains, so `ok` (false if there is any error) naturally accounts for them. Because `_load_metadata` normalizes a missing field to `""`, a single `.strip()` check covers “missing field/empty string/whitespace only,” with a consistent, friendly message. validate remains a pure function, unaware of git/GitHub.
4. **T4 Human-readable view** (depends on T1)—`openagents/spec/render.py`, `tests/test_spec_render.py`. `render()` currently assembles, in order: title/warning → global dashboard → cross-feature relationship diagram → file conflicts → per-feature details. This Task inserts `_render_tldr(*, groups)` **before the global dashboard table**: use the fixed constant `_TLDR_HEADING = "## TL;DR (plain-language overview)"` for the heading; for each group (already sorted by number), output `### {number} {title}` (using `metadata.title or metadata.slug` for title) + the group’s `metadata.summary` (normalized through `_cell`/newline normalization for determinism). Preserve pure-function behavior + idempotence (two renders from the same source data are byte-for-byte identical); in an empty repository with `groups=[]`, the block contains only the heading and raises no error.
5. **T5 Migration** (depends on T3, T4)—`docs/specs/OVERVIEW.md`. Add `summary` to each `docs/specs/<NNNN-slug>/metadata.yaml` (0001–0014)—the content must be **evidence-driven**: read the group’s metadata.title + actual tasks/ contents, then summarize them in plain language, with each passage covering at least the first three of “what this is / why we are doing it / what it delivers / what it does not do”; also add one for this group, 0015; run `spec render` to regenerate `OVERVIEW.md`, and `spec validate` to confirm 0 errors. **Explanation of files ownership (critical)**: each group’s `metadata.yaml` is **not listed** in any Task’s `files`—`files` is a collaboration mechanism for preventing conflicts, representing “code files owned by a Task, with a one-to-one correspondence to `# Spec-NNNN` comments”; bulk content editing is not code ownership. This Task’s `files` lists only the sole output, `OVERVIEW.md` (regenerated by render), while edits to each metadata.yaml are explicitly named in the scope as execution work, naturally avoiding conflicts with other Tasks.

**End-to-end verification**: use `spec validate` (0 errors, including passing all of T3’s nonempty summary checks) + `git diff --exit-code docs/specs/OVERVIEW.md` after `spec render` (no drift) for verification; this group has no separate `scripts/*.sh` e2e script, and verification is performed through ruff + pytest and the spec self-checks above.

Dependency DAG: `T1 → T2`, `T1 → T3`, `T1 → T4`, `T3 → T5`, `T4 → T5`.

## Drawbacks

- The top TL;DR block slightly duplicates information in the “per-feature details” section at the end—but an overview and detailed information serve different reader needs, so this is acceptable.
- Requiring `spec new --summary` makes the command line a little longer; during migration, every existing group needs a real, plain-language summary written individually, incurring a one-time manual cost (but that is precisely where the feature’s value lies).

## Rationale and alternatives

- **Location: group-level metadata vs. reusing per-Task summary**. Choose group-level metadata. Reusing per-Task summary appears to require fewer changes, but is a semantic mismatch (task level ≠ feature level) and requires inventing additional rules for “which task’s summary represents the whole group / how to aggregate multiple task summaries,” violating Occam’s razor. A group-level field with a single responsibility is the simplest option; the per-Task `summary` field remains as it is, with neither affecting the other.
- **Put “nonempty” in schema or validate**. Choose validate (T3). JSON Schema could use `required` + `minLength: 1`, but “missing field” and “empty string” would each produce a separate, unfriendly message; placing this in a single T3 semantic chain allows one clear Chinese message to cover all three cases: “missing field/empty string/whitespace only.” Therefore, T1’s schema only declares the field valid and does not set required.
- **Required --summary vs. optional + validate as a fallback**. Choose required. The issue positions summary as the “foundation,” and the foundation should not be optional; requiring it catches “forgot to write it” immediately at group creation, earlier and at lower cost than discovering it in CI. validate is retained to cover manual edits.
- **Render location: separate top block vs. beginning of each feature’s details section**. Choose a separate top block—the issue repeatedly emphasizes “understand at a glance at the **top** of OVERVIEW.md,” and a separate top block addresses this most directly; details sections at the end cannot provide that quick overview.
- **TL;DR rendering format: table vs. headings + paragraphs**. Choose headings + paragraphs. A TL;DR is plain-language prose in paragraphs; forcing it into table cells would compress it into a single line and hurt readability.
- **Migration and T3 gate: same PR vs. separate PRs**. Choose an atomic rollout in the same PR—otherwise, introducing T3 would immediately make CI fail on main (the gate would block itself).

## Prior art

- The rust-RFC (rfcs.rs) RFC template opens with a Summary paragraph, allowing readers to grasp the main points before reading the details; this feature brings the same “plain-language overview first” approach to the top of the spec OVERVIEW.
- Shared spec test modules with done group 0014: T1–T4 in this group each extend a test module already created by 0014 (`test_spec_model.py`, etc.); `spec validate` will report “cross-feature overlap: 0014, 0015” for these files—this is a warning, not an error, because 0014 is already done and this group merely adds new tests to the same modules. Within this group, `files` remain pairwise non-overlapping, so the collaboration guarantees for preventing conflicts remain intact.

## Unresolved questions

None. Field placement, the division of responsibilities between required fields and gates, render location, and migration ownership (metadata.yaml is not included in files) have all been settled in this group.

## Future possibilities

- If summary needs to contain multiple Markdown paragraphs in the future, the plain scalar can be upgraded to a block scalar `|`.
- The TL;DR block can also be used for the human oversight gate UI in #59 (the frontend presents the results, and a human reads summary to give high-level approval).
