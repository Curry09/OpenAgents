---
number: "0063"
title: "state consolidation: fold the old State into RuntimeState and delete state.py, reducing the flat layer to cli+__init__"
issue: 145
slug: state-converge
summary: "Complete the unification of the two stacks from Spec-0062: migrate the three remaining production reads of the old openagents/state.py (agent_id storage / ui_capable storage / all_runs+RunRecord for release+board) to runtime.RuntimeState in the new stack, source STATUS_* and BLOCKED_LABEL/PR from the authoritative sources (runtime + utils.github), then delete state.py—the flat top level will ultimately contain only cli.py + __init__.py. Because all of .openagents/ is gitignored and state files hold temporary local state, no data migration is required."
tasks:
  - id: T1
    title: "Expand RuntimeState: top-level agent_id/ui_capable access + authoritative STATUS_* constants"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/state.py
      - tests/test_runtime_state_converge.py
    scope: "Add the two groups of top-level accessors that are exclusive to the old State but still read in production to runtime.RuntimeState: get_agent_id/set_agent_id and get_ui_capable/set_ui_capable (persisted as top-level keys in runtime-state.json, alongside runs/cursors); also define authoritative STATUS_* constants (solving/rfc-review/pr-open/iterating/done/closed/blocked) in the runtime layer as the sole source of the status vocabulary for release and subsequent consumers (the copies with the same names in the old state.py are retired accordingly). This is additive and does not change existing runs/cursors behavior."
    acceptance: "RuntimeState provides get/set_agent_id and get/set_ui_capable (testable hermetically, persisted as top-level keys); runtime exposes public STATUS_* constants; existing runs/cursors tests show no regressions; ruff passes."
  - id: T2
    title: "Switch identity to RuntimeState (agent_id storage)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/utils/identity.py
      - tests/test_identity.py
    scope: "Replace the dependency on the old State in utils.identity (type annotations + get_agent_id/set_agent_id calls) with runtime.RuntimeState; resolve_agent_id reads and writes this instance's signature through RuntimeState."
    acceptance: "identity no longer imports openagents.state; idempotent agent_id resolution behavior remains unchanged; all test_identity tests pass; ruff passes."
  - id: T3
    title: "Switch release + results/board to RuntimeState + utils.github"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/utils/release.py
      - openagents/utils/results.py
      - tests/test_release.py
      - tests/test_results.py
    scope: "release: all_runs()→list_runs() (dict records), source STATUS_BLOCKED from the authoritative runtime source and BLOCKED_LABEL from utils.github; suspension precheck semantics remain unchanged. results/board: RunRecord→RuntimeState dict; render displays only fields actually present in the new records (issue_number/status/branch/pr_number/closed_at, with pr_url derived from pr_number or omitted), retiring columns exclusive to the old stack (rounds/fingerprint, etc.)."
    acceptance: "release/board no longer import openagents.state; release's blocking behavior on suspension remains unchanged; board renders RuntimeState records; all test_release/test_results tests pass; ruff passes."
  - id: T4
    title: "Remove _state_for from CLI: ui_capable/agent_id/board/release all use RuntimeState"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: "Delete the cli._state_for factory and from openagents.state import State; all four paths—_persist_ui_capable, _agent_id_for, board, and release—obtain RuntimeState through _new_runtime_state_for. The cli top level no longer contains any imports of openagents.state."
    acceptance: "All oa commands parse and dispatch; cli has no import of openagents.state; ui_capable/agent_id are read and written through RuntimeState; all test_cli tests pass; ruff passes."
  - id: T5
    title: "Delete state.py + consolidate state tests + regenerate docs"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
      - tests/test_state_closed_at.py
      - tests/test_state_code_fingerprint.py
    scope: "Delete openagents/state.py (switch any remaining consumers of its BLOCKED_LABEL/PR re-exports to utils.github directly); delete/rewrite the 9 test_state*.py files (delete tests for behavior already migrated to RuntimeState, and migrate tests that retain value to test_runtime_*); the flat top level will ultimately contain only cli.py+__init__.py. Regenerate OVERVIEW/ARCHITECTURE with spec render/graph."
    acceptance: "The top level of openagents/ contains only cli.py+__init__.py; repository-wide grep finds zero imports of openagents.state; the full pytest suite passes; spec validate reports no errors; OVERVIEW/ARCHITECTURE are drift-free."
---

# 0063 · State unification: fold the old State into RuntimeState and delete state.py, reducing the flat layer to cli+__init__

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

Spec-0062 removed all legacy orchestration/decision modules and physically moved the primitives into `utils`, reducing the flat top level to just three files: `cli.py`, `__init__.py`, and `state.py`. This spec takes care of the last one: migrate the **three remaining production reads** of the old `openagents/state.py` (`State` class + `RunRecord` + `STATUS_*` vocabulary) to the new stack's `runtime.RuntimeState`, source authoritative constants from `runtime` and `utils.github`, and then **delete `state.py`**. The flat top level will ultimately contain only `cli.py` + `__init__.py`, with a single state model and a single persisted file (`runtime-state.json`), fully unifying the two stacks. Because `.openagents/` has been gitignored throughout and the state files hold temporary local state, **no data migration is required**.

## Motivation

Current situation: **two state models** coexist in the project. The old `State` in `openagents/state.py` (440 lines) has a rich, 15-field `RunRecord` (issue/pr/status/summary + rounds/review_invalid/block_gate/merge_attempts/fingerprint and various other legacy counters spanning rounds), persisted to `.openagents/state.json` (`runs` is a list, deduplicated by issue). The new stack's `RuntimeState` in `runtime/state.py` (116 lines) retains only four keys: status/branch/pr_number(/closed_at), persisted to `.openagents/runtime-state.json` (`runs` is a dict indexed by issue_number). Spec-0062 already moved all new-stack recipes (rfc_lifecycle/merge_pr/vigil/poll_comments) to `RuntimeState` and **deliberately discarded** those counters spanning rounds (the new stack has no MAX_ROUNDS budget; see the merge_pr/vigil comments).

The problem: `state.py` has not yet been deleted because **three production reads still depend on the old `State`**, with no equivalents in the new stack—
1. **agent_id storage**: `utils.identity.resolve_agent_id` (via `cli._agent_id_for`) uses `State.get_agent_id/set_agent_id` to store this instance's signature (the top-level `agent_id` key in `.openagents/state.json`). `RuntimeState` has no top-level agent_id.
2. **ui_capable storage**: `cli._persist_ui_capable` uses `State.set_ui_capable` to persist the e2e capability state variable (the top-level `ui_capable` key). `RuntimeState` has no equivalent.
3. **release + board**: `utils.release` uses `State.all_runs()` + `RunRecord.status==STATUS_BLOCKED` for a pre-release check for blocked runs; `utils.results.board` uses `all_runs()` + `RunRecord` fields to render the results board. Both also depend on `BLOCKED_LABEL`, re-exported by `state.py`, and `STATUS_BLOCKED`, defined only in `state.py`.

As long as these three places still read the old `State`, `state.py` cannot be deleted, leaving the flat layer in an intermediate state, “one last step away from unifying the two stacks.” Conceptually, one must remember that “the new stack uses RuntimeState, but releases/the board/signatures still quietly use the old State”; on disk, both `state.json` and `runtime-state.json` must be maintained. This spec completes that final step.

## Guide-level explanation

After migration, state has just one model, `runtime.RuntimeState`, and one file, `runtime-state.json`:
- **agent_id / ui_capable**: add top-level accessors to `RuntimeState` (`get/set_agent_id`, `get/set_ui_capable`), persisting these keys alongside `runs`/`cursors` in `runtime-state.json`. Update `identity` and `cli` to call them.
- **Status vocabulary**: define one set of **authoritative public constants** for `STATUS_*` (solving/rfc-review/pr-open/iterating/done/closed/blocked) in the `runtime` layer, from which `release` obtains `STATUS_BLOCKED`. (This spec does not require incorporating each new-stack recipe's existing module-private `_STATUS_*` literals, to avoid expanding scope; once the authoritative source is in place, they can naturally converge in subsequent work.)
- **release / board**: replace `all_runs()` (returns `RunRecord`) with `list_runs()` (returns dict); source `BLOCKED_LABEL` directly from `utils.github`; retire the board's legacy-stack-only columns (old counters such as rounds/fingerprint do not exist in new records at all), displaying only fields actually present in new records.
- **Delete `state.py`**: its only two re-exports still depended on externally, `BLOCKED_LABEL`/`PR`, already have authoritative definitions in `utils.github`; remaining consumers can simply reference that module directly.

There is **zero visible change** to user/agent behavior: signature idempotency, release blocking for blocked runs, and the semantics of the board's presentation all remain intact. Only the module and file used to read and write this data change.

## Reference-level explanation

**The boundary remains unchanged**: state is a deterministic storage primitive belonging to `runtime` (the mechanism layer), not agent judgment. This spec is purely mechanical unification, with no new judgment delegated downward.

**No data migration**: `.gitignore:17` ignores the entire `.openagents/` directory; `state.json`/`runtime-state.json` both hold temporary local state and are not versioned. After `state.py` is deleted, the old `state.json` is naturally abandoned, and new runs repopulate `runtime-state.json`. Therefore, this spec adds no JSON migration/compatibility shim (Occam).

**Task DAG (5 Tasks, within the ≤6 limit)**:

```
T1 (Expand RuntimeState: agent_id/ui_capable accessors + authoritative STATUS_*)
 ├─→ T2 (identity → RuntimeState)
 └─→ T3 (release + results/board → RuntimeState + utils.github)
        T2, T3 ─→ T4 (Remove _state_for from CLI; all four paths use RuntimeState)
                    └─→ T5 (Delete state.py + consolidate 9 state tests + regenerate docs)
```

T2 ∥ T3 can run in parallel (their files do not overlap).

**File assignments (pairwise disjoint, single writer)**:

| Task | files | Dependencies |
|---|---|---|
| T1 | `openagents/runtime/state.py`, `tests/test_runtime_state_converge.py` | — |
| T2 | `openagents/utils/identity.py`, `tests/test_identity.py` | T1 |
| T3 | `openagents/utils/release.py`, `openagents/utils/results.py`, `tests/test_release.py`, `tests/test_results.py` | T1 |
| T4 | `openagents/cli.py`, `tests/test_cli.py` | T2, T3 |
| T5 | `openagents/state.py` (delete), `tests/test_state.py`, `tests/test_state_closed_at.py`, `tests/test_state_code_fingerprint.py` | T4 |

> T5's `files` column lists the key deletion targets; in practice, T5 will also delete/rewrite the other 6 `test_state_*.py` files (merge_unblock/needs_human_unblock/unblock_detail, etc., which test legacy blocking fields spanning rounds, whose behavior was abandoned along with the counters)—these stub tests cover legacy-stack semantics already declared obsolete in 0062, so delete them outright. They do not overlap with any other Task's files, so they are not individually listed in the frontmatter.

**e2e script**: this spec has no standalone e2e test; after unification, acceptance is verified by running the existing full `pytest` suite (0062 baseline: 669 passed) + an `oa --help` smoke test.

**Mandatory acceptance gates (per Task)**: ruff check+format passes, relevant pytest tests pass, and `spec validate` reports no errors; T5 additionally requires zero matches for `openagents.state` imports in a repository-wide grep + drift-free OVERVIEW/ARCHITECTURE.

## Drawbacks

- **Discarding the legacy stack's rich fields**: `RunRecord`'s rounds/review_invalid/block_gate/merge_attempts/block_watermark/unblock_detail/two fingerprints disappear along with `state.py`. These provide budget and sticky-gate bookkeeping across rounds for the legacy stack's messages/orchestrator; the new stack has already abandoned them by design (no rounds budget spanning rounds). If the new stack needs to rebuild “bookkeeping across rounds” in the future, it must be redesigned on `RuntimeState` rather than reviving the old fields—this is a deliberate cost, not an omission.
- **Less information on the board**: the results board no longer displays rounds/fingerprint columns. But the board focuses on “results” (issue→PR→status), and these old counters were never dimensions of results; reducing the information makes it more focused.
- **Deleting ~9 state tests in one go**: the test coverage figure will decrease, but what is being deleted consists of stub tests for obsolete semantics, not real regression protection.

## Rationale and alternatives

**Selected approach**: migrate the three production reads to `RuntimeState`, add top-level agent_id/ui_capable keys and authoritative STATUS_* constants, then delete `state.py`. Rationale: `RuntimeState` is already the new stack's sole state model and has been adopted by every recipe. Having it carry two additional top-level scalar keys (agent_id/ui_capable) costs very little (the schema is already an open dict) and is the shortest path to “a single state model.”

**Alternative 1: retain state.py solely as a thin re-export wrapper** (like the utils shims before 0062, with state.py re-exporting RuntimeState). Rejected: that adds another layer of indirection rather than achieving unification; the user wants the flat layer **deleted**, not wrapped.

**Alternative 2: move all 15 fields of the rich RunRecord into RuntimeState** (preserving the legacy stack's counters). Rejected: this contradicts 0062's established decision that “the new stack abandons budgets spanning rounds,” resurrecting obsolete legacy bookkeeping in the new stack and multiplying entities against Occam's principle. Migrate only fields **still being read**.

**Alternative 3: create a separate small module for agent_id/ui_capable** (such as `runtime/identity_state.py`) instead of putting them into RuntimeState. Rejected: both are single per-project scalars and, like runs/cursors, belong to “project runtime state”; keeping them in the same file and class is most natural. A separate module would be excessive fragmentation.

## Prior art

- **Spec-0062** (the predecessor in this wave, PR#158 already opened): removed all legacy orchestration modules and moved 15 primitives into utils, reducing the flat layer from 28 files to the three files `{cli,__init__,state}`. This spec addresses the loose end it explicitly left (0062/T5 body: “state.py is temporarily retained because the old and new state models have not been unified; its deletion will be addressed separately in Spec-0063 as part of state unification”).
- **Spec-0060/0061**: established `runtime.RuntimeState` and persistence for its `runs`/`cursors`, along with the `find_run(pr_number=)`/`list_runs()` interfaces (added in 0062/T3), providing the foundation for this spec's expansion.
- The old `State` field lineage (starting with RFC-0001, followed by RFC-0011 agent_id, RFC-0012 rounds, and bookkeeping fields added successively in Spec-0021/0031/0032/0042/0053/0055)—this spec is their endpoint: migrate those still being read and discard those exclusive to the legacy stack.

## Unresolved questions

- **Whether recipe-private `_STATUS_*` should be incorporated into the authoritative STATUS_***: This spec only guarantees that an authoritative source is available for `release`; it does not require changes to the module-private `_STATUS_*` in rfc_lifecycle/merge_pr/vigil (changing them would be internal cleanup of recipes already migrated under 0062 and is out of scope). This remains optional cleanup for later.
- **Whether board needs a pr_url column**: `RuntimeState` records contain only pr_number. Whether rendering should “derive a PR link from pr_number + the repository slug” or “display only pr_number” will be decided during T3 implementation based on the smallest change; this does not affect the unification goal.

## Future possibilities

- Once a single state model is in place, a layer of **runtime owner validation/leases** could be added to `RuntimeState` (the direction of issue #71: turning design-time ownership in files-allocation into runtime enforcement), because there is now only one source of truth for state, so locking/leases do not require synchronization across two places.
- If a “global runtime-state dashboard across issues” is needed in the future, unifying state into a single `runtime-state.json` file will allow aggregation from a single read point, without merging two models.
