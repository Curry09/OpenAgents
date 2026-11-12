---
number: "0090"
title: "Vigil workflow terminal states and closure of recoverable failures"
issue: 0
slug: convergence-safety
summary: "Recheck the terminal state after merging and route recoverable failures back to the correct stage to avoid incorrectly leaving the workflow hanging and terminating the entire round"
architecture:
  objective: "Close the loop on action results, fact rereads, and recoverable failure routing within the existing Vigil state machine to avoid incorrectly marking tasks and stopping the entire round"
  constraints:
    - "Do not add roles, persistent entities, or failure budgets"
    - "Reuse only the existing architecture, implement, deliver, and review paths"
  non-goals:
    - "Do not change the actual model's ability to understand requirements"
    - "Do not include platform export, permissions, or retention in this code change"
  candidates:
    - id: "existing-reconcile-routes"
      layer: "recipes.vigil and runtime.gates"
      boundary:
        - "Action return"
        - "Gate exception"
        - "Terminal-state recheck"
      evidence:
        - "Fault-injection unit tests"
        - "Local concurrency stress testing"
      tradeoffs: "Add one fact read while keeping the state model unchanged"
    - id: "increase-retry-budget"
      layer: "queue worker"
      boundary:
        - "Failure retries"
      evidence:
        - "Can only postpone round_cap or retry_exhausted"
      tradeoffs: "Does not resolve incorrect routing; reject this approach"
  selected: "existing-reconcile-routes"
  affected-components:
    - "recipes.vigil"
    - "runtime.gates"
  failure-modes:
    - "Successful merge overwritten by round_cap"
    - "Design summary/generated view mismatches repeatedly consume the failure budget"
    - "External call exceptions cross the worker boundary"
verification:
  behavior-cases:
    - id: "merge-terminal"
      polarity: positive
      stimulus: "The action has already returned a successful merge result, but the next remote snapshot has not yet been updated"
      expected: "Keep the task completed; do not write round_cap"
      observation: "reconcile unit tests"
    - id: "recoverable-gates"
      polarity: positive
      stimulus: "The design summary or OVERVIEW does not match the candidate tree"
      expected: "Route back through the existing review/delivery paths without repeatedly consuming the claim budget"
      observation: "Gate-type unit tests and integration regression tests"
    - id: "hard-failure-isolation"
      polarity: negative
      stimulus: "Unrecoverable exception or model call failure"
      expected: "Continue using the existing bounded retries; the worker does not exit"
      observation: "Full pytest suite and stress scripts"
  repository-invariants:
    - "Write done only when the merge reports success"
    - "Old review labels do not certify new candidates"
  exemptions: []
tasks:
  - id: T1
    title: "Terminal-state verification and routing recoverable failures back"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - openagents/runtime/gates.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - tests/test_runtime_gates.py
      - scripts/e2e-spec-0090.sh
      - docs/specs/0090-convergence-safety.md
    scope: "Fix routing for misclassified merge terminal states, design summary mismatches, and repository integrity mismatches, and add fault-injection tests"
    acceptance: "A successful merge must not write round_cap; recoverable mismatches must not repeatedly consume the claim budget; the full pytest suite and targeted stress tests must pass"
---

# 0090 · Vigil Workflow Terminal States and Recoverable Failure Resolution

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Code changes are complete, including timeout protection for calls on recovery paths, candidate binding, and renewed review after rework.

Vigil reads facts between actions and rechecks terminal states before reaching the round limit; a successful merge result concludes processing directly and is no longer overridden by the limit. Design digest
mismatches and repository generated-view mismatches are routed back through the existing review/delivery paths without consuming the claim failure budget; external model transport interruptions remain isolated by
the existing bounded retries. The verification here establishes that a single-ticket failure does not terminate the worker; it does not mean that recovery is guaranteed for the outer experiment main loop.

## Motivation

Four types of convergence failures occurred in experiments: a completed merge was recorded as `round_cap` in the final round; the same gate was repeated when code review had passed but the design digest
had changed; integrity checks were repeated when `OVERVIEW.md` was inconsistent with the Spec tree; and interrupted CLI responses were treated as
ordinary failures. Their shared root cause was that action results, fact rereads, and exception routing were not brought to closure within the same reconcile boundary.

## Guide-level explanation

After the merge action returns success, the orchestration layer accepts the definitive result supplied by that action and releases the slot; for other actions, it reads facts in the next round,
then rereads them once more before reaching the limit, without recording failure if the ticket has already been merged/closed or is waiting on an external dependency. A design digest mismatch goes through the existing architecture reconfirmation,
clears the old verdict, and returns to the existing review-or-fix path; a generated-view mismatch returns to the existing
delivery repair path; only genuinely unrecoverable gate errors enter the original failure budget. Transport errors do not change business state and are retried only within the existing
claim boundary, with the existing bound.

## Reference-level explanation

This fix changes only `recipes.vigil`, `runtime.gates`, and their tests. The new exception types are used only for in-process routing; they are not persisted,
and no roles or state fields are added. `_reconcile` ends immediately after `_act` returns `merged` and performs one more
terminal-state-aware check before the round limit; `_do_merge` marks design digest mismatches and repository integrity mismatches as separate errors that can be routed back for recovery; `_run_claimed` preserves
worker exception isolation and the existing three-attempt budget.

Recovery paths still go through the existing `_TimedBackend` and inherit the claim lock; after design rework, architecture PASS must be obtained again, and candidate
reads, reviews, and approval updates must be bound to the same pushed version. Fixes that make no changes remain subject to the zero-progress guardrail; when rounds are exhausted, the system first checks whether
the work has already completed or entered an external wait; otherwise, it retains the existing eight-round limit and does not reset the budget to conceal continued rework. No new retry mechanism for real model transport is added;
persistent external failures may still cause a single ticket to fail within the defined bounds, and this specification does not guarantee that the outer experiment supervisor will never abort.

### Task DAG

| id | status | scope | files | acceptance |
|----|----|----|----|----|
| T1 | done | Terminal-state rechecks, recoverable gate routing, and fault-injection regression tests | `openagents/recipes/vigil.py`, `openagents/runtime/gates.py`, `tests/test_recipe_vigil.py`, `tests/test_recipe_vigil_act.py`, `tests/test_runtime_gates.py` | No round_cap after merging; digest/integrity mismatches do not repeatedly consume the budget; full test suite and targeted stress tests pass |

Acceptance entry point: `bash scripts/e2e-spec-0090.sh`. The first half includes tests for the terminal states addressed here, timeout wrapping on recovery paths, actual PASS results,
review after rework, candidate version changes, integrity rechecks, and worker isolation; the second half reuses the delivery stress-test entry point for concurrency regression testing.
The second half does not simulate a real model or the outer experiment runner, nor does it claim that its 17 categories of delivery scenarios cover all recovery-path behavior introduced here.

Final verification on 2026-09-10: full pytest suite, 1336 passed; targeted tests, 266 passed; 1/4/8/16 workers, with mixed
faults repeated 4 times for each configuration, for a total of 336 tasks (all 304 normal/recoverable tasks merged; 32 tasks with persistent faults stopped as expected). Unexpected outcomes,
approval of incorrect candidates, duplicate claims, and leftover queue entries were all 0. Behavior in the newly added recovery branches is verified by targeted positive and negative cases; existing delivery stress-test
results are not presented as a real-model closed-loop validation. Desktop HTTP tests require local loopback port permissions; the full suite passed once those permissions were granted.

Ruff check/format for the files changed here, Spec validate, and graph validation passed. The repository still has 2 pre-existing
import-sorting errors and formatting differences in 22 files; these were not folded into this runtime logic fix, so no claim is made that repository-wide CI is green.
The current test environment has no coverage plugin, so no new coverage percentage is reported here. When GitHub credentials are missing, new remote
commits or open PR number conflicts cannot be checked; successful pushes and remote CI must be confirmed by actual remote acknowledgments.

## Drawbacks

One lightweight fact read is added after the merge action; recoverable mismatches retrigger existing role calls, slightly increasing latency while avoiding erroneous suspension
and incorrect merges.

## Rationale and alternatives

The chosen approach reuses existing actions, labels, and failure budgets, filling in only the state-machine boundaries. Increasing the retry count was rejected because it would merely delay suspension, as was
adding a dedicated recovery queue, which would introduce a persistent entity unnecessarily.

## Prior art

This follows Spec-0065's level-triggered reconcile, Spec-0074's transient-state resolution using `MergeNotReady`, and Spec-0089's
candidate version binding.

## Unresolved questions

None. This task does not change real model capabilities, platform deployment, or historical experiment archives.

## Future possibilities

The outer experiment supervisor's restart/recovery behavior could later be included in the same fault-injection matrix, but no supervisor component is added in this change.
