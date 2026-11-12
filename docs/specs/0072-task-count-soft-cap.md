---
number: "0072"
title: "Soft limit on the number of Tasks in a spec group: proactive warning when >6 + declarative exemption; deliver a large feature in one spec/one PR"
issue: 156
slug: task-count-soft-cap
summary: "Relax the spec-driven convention requiring groups to be split to contain ≤6 Tasks into a soft limit for readability: spec validate proactively emits a warning when >6, and declaring oversized-rationale grants an exemption; the single writer's files remain mutually exclusive, allowing a large feature to be completed within one spec/one PR"
tasks:
  - id: T1
    title: "Add optional oversized-rationale to frontmatter + model round-trip"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/schema.py
      - openagents/spec/model.py
    scope: "Add optional oversized-rationale(string) to the schema; add a field to Metadata, read it in load_group, and write it back in render_group only when nonempty"
    acceptance: "A spec containing oversized-rationale remains byte-for-byte unchanged after a load→render round-trip; the schema accepts this key and continues to reject unknown keys"
  - id: T2
    title: "Rule 11 in the validate chain: warning for the >6 Task soft limit + declarative exemption"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/validate.py
    scope: "Add _task_count_checks: if the current version has >6 Tasks and oversized_rationale is empty → warning; remain silent if it is declared; the warning does not affect ok"
    acceptance: "A group with 6 Tasks produces no message; a group with 7 Tasks produces one warning with report.ok=True; a group with 7 Tasks+rationale remains silent with ok=True"
  - id: T3
    title: "Reframe the skill documentation: 6-Task soft limit + hard invariant of mutually exclusive files"
    status: done
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - .claude/skills/spec-driven-development/SKILL.md
      - .claude/skills/spec-driven-development/references/task-fields.md
    scope: "Rewrite the mandatory split requirement for >6 as too large into a soft limit for readability + declarative exemption; distinguish the hard invariant (mutually exclusive files) from the soft limit (6-Task); document oversized-rationale"
    acceptance: "SKILL.md no longer contains mandatory too large wording; the documentation explains how to use oversized-rationale and the distinction between the two types of constraints"
  - id: T4
    title: "Unit tests for rule 11 + round-trip"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - tests/test_spec_validate.py
      - tests/test_spec_model.py
    scope: "Tests for the three states of validate rule 11 + an oversized-rationale round-trip test"
    acceptance: "New tests cover the three states of 6/7/7+rationale and round-trip; uv run pytest passes all tests"
---

# 0072 · Soft cap on Task count per spec group: proactive warning at >6 + declarative exemption, delivering a large feature in one spec / one PR

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Downgrade the spec-driven-development skill's rule that “a single spec group may contain at most 6 Tasks; exceeding this requires splitting the group” from a **hard convention** to a **soft cap for readability**: when the Task count is > 6, `spec validate` proactively emits a **warning** (not an error; it does not fail CI). If the author confirms that this is an **atomic delivery**, declaring an `oversized-rationale` in the group frontmatter exempts it from the warning. The single-writer **hard invariant that `files` within the same group must be pairwise disjoint** (Principle 6) remains an error, unchanged. This allows a large feature that naturally breaks down into > 6 work units to be completed legitimately within **one spec / one PR**, without being forced into multiple spec numbers, multiple PRs, or multiple batches.

## Motivation

The `spec-driven-development` skill has two constraints that are often understood as equally hard rules:

1. **A single spec group contains ≤ 6 Tasks**—the skill states verbatim: “A group with more than 6 Tasks is too large — split into multiple focused groups”.
2. **The `files` of different Tasks are pairwise disjoint**—single-writer ownership, the foundation of conflict-free writes in collaboration mode (Principle 6), and the structured source for the runtime owner checks in issue #71.

The problem is that the two constraints differ in nature but receive equal treatment: constraint 2 is a **true invariant** (two Tasks competing to write the same file = a real conflict), already hardcoded as an **error** in `_file_overlap_checks` in `openagents/spec/validate.py`; constraint 1 is merely a **readability/reviewability heuristic**, and **has never been enforced in code**—none of the ten rules in the full `validate` chain counts Tasks. It exists only as prose in the skill documentation, yet causes real friction:

- If a large feature naturally breaks down into > 6 work units, it “does not fit into one spec group” and is forced to use another spec number and split into multiple PRs. This directly conflicts with the goal of “one large feature, one PR / one delivery batch” (matching the delivery cadence of cursor/windsurf; see the general principles in CLAUDE.md).
- **Example**: the architecture consolidation batch Spec-0062 already fills all 6 Task slots (rfc_lifecycle / merge_pr / vigil / cli rewiring / flat-layer cleanup / test consolidation). The immediately following “state unification (delete state.py)” cannot fit and must become Spec-0063. The same objective is split into two specs by the 6-Task cap. The current compromise is “use the same branch, do them in the same batch, and combine them into one PR at the end”—a soft constraint that requires a workaround.

Since constraint 1 has never been a code invariant and is merely a heuristic, the right fix is to **express it honestly as a soft cap**: provide a proactive warning (the explicit request in direction d of issue #156: “proactively warn when > 6 Tasks are expected”), while making “one feature = one large spec” a first-class option (the substance of direction a: relax the limit / allow a declaration), instead of continuing to force group splits through prose.

## Guide-level explanation

For agents / people using the spec workflow, the rules become:

- **6 is a soft cap for readability, not a hard wall.** When breaking work into Tasks, aim for no more than 6 so that a spec remains manageable to read and review.
- When a feature naturally comprises > 6 work units, **they may be placed in the same spec group**—provided that the true invariant, “`files` within the same group are pairwise disjoint,” still holds.
- In this case, `spec validate` emits a **warning** (not an error; CI stays green): `Group Task count N > 6: confirm that this is an atomic delivery; otherwise, split it into multiple focused groups`.
- If it is indeed an atomic delivery, add a one-line declaration to the group frontmatter to suppress the warning and get a clean `validate` result:

  ```yaml
  oversized-rationale: "Desktop app delivered in one batch: the board/streaming/navigation are tightly coupled; splitting groups would fragment e2e acceptance"
  ```

- The declaration is **explicit and machine-recorded** (making a soft convention enforceable: exceeding the soft cap requires leaving a sentence explaining why, rather than silently exceeding it).

The single-writer mutual exclusion of `files` is **not relaxed at all**—it is the foundation of safe collaborative parallelism. Only the readability heuristic governing “how many Tasks that do not compete for files can fit in one group” is relaxed.

## Reference-level explanation

**Scope of changes (4 Tasks, with pairwise-disjoint `files`):**

| Task | files | Changes |
|----|----|----|
| T1 | `openagents/spec/schema.py`, `openagents/spec/model.py` | Add optional `oversized-rationale` (string) to the frontmatter schema; add an `oversized_rationale` field to `Metadata`, read it in `load_group`, and write it back in `render_group` only when nonempty (after summary and before e2e/tasks), ensuring idempotent round-tripping with zero drift |
| T2 | `openagents/spec/validate.py` | Add the 11th check in the chain, `_task_count_checks`: if the current version's Task count > `_TASK_SOFT_CAP`(=6) and `oversized_rationale` is empty after trimming whitespace → emit one **warning**; emit no warning if a rationale is declared. The warning does not affect `ok` (a large feature in one spec does not fail CI) |
| T3 | `.claude/skills/spec-driven-development/SKILL.md`, `.claude/skills/spec-driven-development/references/task-fields.md` | Reframe “> 6 is too large and must be split” as a readability soft cap + declarative exemption; distinguish “files mutual exclusion = hard invariant” from “6 Tasks = soft cap”; document the `oversized-rationale` field |
| T4 | `tests/test_spec_validate.py`, `tests/test_spec_model.py` | Positive and negative cases for rule 11 (6 Tasks produce no warning / 7 Tasks produce a warning with ok=True / 7 Tasks+rationale produce no warning) + `oversized-rationale` round-trip |

**DAG**: T1 → T2 (validate depends on the new model field); T3 and T4 depend on the semantics of T1/T2 being established. T3's files are disjoint from all the others, so it can run in parallel.

**Soft-cap constant**: `_TASK_SOFT_CAP = 6` in `validate.py`, as the single source of truth, with a comment pointing to this spec.

**e2e / outcome acceptance**: purely offline backend + skill documentation changes. Acceptance consists of `uv run pytest` (the three states of rule 11 + round-trip) + zero drift in artifacts generated by `uv run spec validate/render/graph`; there is no browser e2e, so this spec does not declare an `e2e` block (the form is inherently cli/offline).

## Drawbacks

- The warning is nonblocking. In theory, an author could neither split the group nor declare a rationale, ignoring the warning indefinitely—but this is on a different level from true invariants such as “files mutual exclusion.” The 6-Task limit is a heuristic to begin with, and making it nonblocking is deliberate (blocking would once again prevent “one large feature, one PR,” precisely the problem this issue aims to solve).
- One additional optional frontmatter field and one validate check constitute a very small increase in entities (Principle 1, Occam's razor), but they do add one more concept to the spec surface.

## Rationale and alternatives

**Selected: soft-cap warning + declarative exemption (combining directions a + d of issue #156).** This accurately expresses that “6 is a heuristic, not an invariant.” Nonblocking behavior makes one spec / one PR for a large feature a first-class option, while the declarative exemption turns “exceeding the soft cap” from a silent act into a recorded decision (making a soft convention enforceable). The scope of changes is minimal and self-contained, with no new cross-module concepts.

**Alternative 1 (rejected)—direction c: cross-spec “delivery unit” links.** Associate multiple spec groups into “one delivery” through new frontmatter, making the “multiple specs, one PR” workaround a first-class option. Reason for rejection: this introduces the entirely new concept and machinery of a “cross-group delivery unit” (render/validate/CLI would all need to recognize it), adding more entities. It also merely endorses “multiple specs, one PR” without solving “it does not fit into **one** spec”—this spec's reframing lets one large spec directly contain the entire feature, which is both more capable and simpler.

**Alternative 2 (rejected)—direction b: subgroups / hierarchical Tasks.** Add another level within a group. Reason for rejection: this adds a hierarchy on top of the Task DAG, requiring changes to render/validate/schema and disrupting the existing simple model in which “a Task is a flat work-breakdown row,” contrary to Occam's razor.

**Alternative 3 (rejected)—retain mandatory splitting but change only the documentation wording.** Soften only the skill documentation, without adding any machine signal. Reason for rejection: direction d of the issue explicitly requests “proactively warn at > 6.” Documentation-only changes cannot provide a warning at the `spec validate` level, leaving agents unable to detect that the cap has been triggered while drafting.

## Prior art

- This repository's `_file_overlap_checks` (overlapping files within the same group = error) establishes the precedent that “true invariants belong in validate”; this spec symmetrically establishes that “soft caps produce warnings.”
- RFCs in rust-lang/rfcs have no “cap on the number of sections / work items”; reviewers judge their size—supporting the view that “Task count is a readability heuristic rather than a hard constraint.”
- Issue #71 (extending single-writer ownership from design time to runtime) has already established `files` mutual exclusion as a runtime guard, further demonstrating that “files mutual exclusion” and “the 6-Task cap” are not on the same level—the former is a safety invariant, while the latter is a readability heuristic.

## Unresolved questions

- Does `_TASK_SOFT_CAP` need to be configurable (a per-repo `.openagents` declaration)? This spec initially uses a fixed value of 6 + declarative exemption to cover known needs, leaving any further abstraction for later as needed.

## Future possibilities

- If `oversized-rationale` is used frequently, `spec render` could mark these groups as “atomic delivery” in OVERVIEW so they are immediately identifiable on the board.
- The soft cap could become a configurable per-repo threshold (following up on Unresolved questions).
