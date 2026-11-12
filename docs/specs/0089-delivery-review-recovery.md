---
number: "0089"
title: "Recovery of interrupted delivery and review version consistency"
issue: 0
slug: delivery-review-recovery
summary: "Resume delivery after an interruption, binding review and merge to the same pushed candidate; require a new review for legitimate version changes without incorrectly consuming the execution failure budget."
architecture:
  objective: "Preserve and complete the original development work after an interruption, ultimately merge the pushed candidate that was actually reviewed, and ensure that version checks do not prevent normal tasks from making progress."
  constraints:
    - "Reuse existing roles, run.status, queues, approval labels, and failure budgets without adding persistent entities."
    - "Do not clear or rebuild existing workspaces; unpushed and uncommitted work must not claim approval granted to remote code."
    - "A legitimate version change invalidates the previous verdict; read failures and undelivered code must not masquerade as version changes."
  non-goals:
    - "Do not implement a return to architecture review after a design summary mismatch, and do not modify the requirements in Spec-0088 that remain to be implemented."
    - "Do not deploy images, restart experiments, revise historical archives, or guarantee real models' ability to understand requirements."
  candidates:
    - id: existing-recovery-and-sha-gates
      layer: existing Vigil recipe, Workspace and forge adapters
      boundary:
        - "Development handoff"
        - "Candidate checks"
        - "Native conditional merge"
      evidence:
        - tests/test_delivery_recovery_git.py
        - tests/test_delivery_recovery_stress.py
        - scripts/stress_delivery_recovery.py
      tradeoffs: "Add a small number of Git fact checks; real version changes require another review, but the normal path does not require additional model calls."
    - id: strict-rejection-only
      layer: delivery gate
      boundary:
        - "Only reject discrepancies between local and remote state"
      evidence:
        - docs/specs/2026-09-09-delivery-review-snapshot-tests-design.md
        - docs/specs/2026-09-09-delivery-recovery-stress-design.md
      tradeoffs: "This can prevent incorrect merges, but cannot complete resumed delivery after a timeout, and consecutive version changes will exhaust the execution failure budget."
  selected: existing-recovery-and-sha-gates
  affected-components:
    - recipes.vigil
    - recipes.stages
    - utils.workspace
    - runtime.gates
    - utils.github
    - utils.gitea
    - cli
    - agents
  failure-modes:
    - "After a timeout, implementation is skipped solely because a PR exists, resulting in only the Spec being merged."
    - "The review reads uncommitted code, but approval is bound to an older pushed commit."
    - "Consecutive legitimate version changes are mistaken for execution failures, causing permanent suspension after the third occurrence."
    - "If the remote changes again after the check or the merge fails, a new version is still merged under the old approval or the issue is closed."
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: "Interrupt development before commit, after commit, or after push, then resume the same task."
      expected: "Preserve the original workspace and work, resume delivery, review again, and merge the corresponding implementation; completing a missing push must not create an empty commit."
      observation: "tests/test_delivery_recovery_git.py checks the actual main contents in the bare remote and the original workspace; a dedicated script verifies all three flows."
    - id: BC2
      polarity: positive
      stimulus: "Legitimately update the remote three consecutive times during review, after which the candidate stabilizes."
      expected: "Invalidate the first three verdicts, then review and merge on the fourth review; execution failure attempts do not accumulate."
      observation: "All 40 targets in the remote-churn-3 stress test complete, with only the final SHA approved; 104 normal controls in the same batch also complete."
    - id: BC3
      polarity: negative
      stimulus: "The workspace has uncommitted changes, a reviewer leaves unpushed commits, or a Git/forge read fails."
      expected: "Do not approve inconsistent candidates; real persistent failures stop under the existing three-attempt budget without affecting other tasks."
      observation: "Regression tests of actual Git read boundaries and 96 persistent-failure controls in the regular stress tests."
    - id: BC4
      polarity: positive
      stimulus: "Concurrently run a mix of normal execution, a single timeout, completion of a missing push, version changes, REWORK, caches, and a single read failure."
      expected: "912 normal or recoverable tasks complete, with merged contents matching the SHA actually reviewed, no duplicate claims, and no entries left in the queues."
      observation: "Two sets of fixed-seed stress tests using scripts/stress_delivery_recovery.py with 1/4/8/16-worker configurations, totaling 1008 tasks."
  repository-invariants:
    - "Allow changes during development; check for a clean candidate only at delivery and reader acceptance boundaries, preserving the ordering of terminal states, replies, dependencies, and draft-to-ready transitions."
    - "All automatic merge calls pass the approved SHA; GitHub uses match-head-commit, and Gitea uses head_commit_id."
    - "Do not mark a task done or close the issue unless the merge is reported as successful; caches ignored by Git do not count as undelivered source code."
  exemptions: []
tasks:
  - id: T1
    title: "Resume delivery and verify the same candidate through to merge"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/deliver.py
      - openagents/agents/executor.py
      - openagents/agents/merger.py
      - openagents/agents/reviewer.py
      - openagents/agents/tester.py
      - openagents/cli.py
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - openagents/runtime/gates.py
      - openagents/utils/gitea.py
      - openagents/utils/github.py
      - openagents/utils/workspace.py
      - tests/test_forge.py
      - tests/test_gitea_driver.py
      - tests/test_github.py
      - tests/test_recipe_stages.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil_timing.py
      - tests/test_runtime_gates.py
      - tests/test_workspace.py
      - tests/test_delivery_recovery_git.py
      - tests/test_delivery_recovery_stress.py
      - scripts/e2e-delivery-review-recovery.sh
      - scripts/stress_delivery_recovery.py
      - docs/specs/2026-09-09-delivery-review-recovery-design.md
      - docs/specs/2026-09-09-delivery-review-snapshot-tests-design.md
      - docs/specs/2026-09-09-delivery-recovery-stress-design.md
    scope: "Reuse existing state and roles to complete interrupted development; read the actual Git candidate and bind it to the native merge SHA; require a new review for legitimate version changes; archive stress tests covering positive and negative cases and reproducible entry points."
    acceptance: "Full and targeted regression tests pass; the original target of 40 consecutive version changes is completed after stabilization; 912 regular recoverable tasks complete, and 96 persistent failures stop within bounds; incorrect merges, unintended blocking, duplicate claims, and leftover queue entries are all zero; uncommitted and unpushed review changes must not falsely claim PASS."
  - id: T2
    title: "Clean up the Claude process group and close out the post-recovery exit boundary"
    status: in-progress
    priority: P1
    tags: []
    depends-on: [T1]
    relates-to: []
    parallel: false
    files:
      - openagents/backends/claude_code.py
      - tests/test_backend_claude_code.py
      - docs/specs/0089-delivery-review-recovery.md
    scope: "After the Claude main process receives a stop signal, even if the leader has already exited, confirm that its independent process group has no leftover shell/MCP child processes; if the process group still exists, escalate to SIGKILL and preserve the exit boundary required to resume the next delivery."
    acceptance: "In fault injection where the leader exits normally in response to SIGTERM but child processes remain alive, send SIGTERM first, confirm that the process group still exists, and then send SIGKILL; when the leader has exited and the process group has disappeared, do not mistakenly kill a new process group that reuses the same ID; targeted backend tests pass."
---

# 0089 · Interrupted Delivery Recovery and Review Version Consistency

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is the group-level nine-section rust-RFC overview. -->

## Summary

The code changes are complete. This group delivers interruption recovery, delivery checks,
review acceptance, and conditional merging as one atomic fix: development that is not yet complete continues in the original workspace, review certifies only the pushed candidate,
and merging accepts only that candidate; legitimate candidate changes trigger a new review without consuming the execution failure budget. No runtime roles or state entities are added.
The dated design document retains the original diagnosis, failure evidence, and fix evidence; this file is the formal specification of the current implementation.

## Motivation

In the experiment, development first pushed Spec commit `472621c`, then left the implementation and tests locally; after the call timed out, the retry found an existing PR
and skipped the remaining development. The reviewer inspected the uncommitted implementation and returned PASS, but the host bound that PASS to the remote Spec commit, so
the implementation was never merged. The root cause was not a failure to write code, but a failure to cross-check “development handoff complete” against “the version actually reviewed” at the delivery boundary.

The initial addition of a strict equality check prevented incorrect merges, but treated legitimate remote advancement during review as an undelivered-change error; in stress testing,
all 40 tasks with three consecutive candidate changes exhausted their failure budgets. The fix must both prevent incorrect merges and allow normal tasks to complete eventually,
without masking a lack of progress by increasing retry counts or merely counting rejections.

## Guide-level explanation

1. Set the existing state `iterating` before development, and set `pr-open` only after actual delivery. After a timeout, recover the same PR and workspace,
   and continue with the original requirements and remaining development; neither an existing PR nor marking a draft ready for review counts as completed delivery.
2. If changes are uncommitted, finish the implementation and commit; if already committed, only push what is missing; if already pushed but the return was lost, verify and finalize without creating an empty commit.
3. Before review, synchronize a workspace that is clean and only behind; if it has local changes or has diverged, hand it back to the existing development/delivery flow without deleting source code.
4. Check the candidate again after review and testing. A legitimate candidate change discards the old verdict and triggers a new review; a dirty workspace, unpushed changes, and read failures
   still count as real failures. Caches follow Git’s existing ignore rules; unknown files receive no exemption based on extension.
5. Before merging, check the live PR SHA and approval label, then pass that same SHA into the platform’s native merge condition; do not close the task unless the merge succeeds.

## Reference-level explanation

### Contract and file allocation

One Task, `T1`, covers the complete handoff fix, regressions, and delivery notes, with no new Task dependencies; the exact file list is in the frontmatter.
Development recovery and review gates must ship together to avoid adding rejection alone without a recovery path.

| Layer | Changes |
| --- | --- |
| Workspace | `delivery_heads` checks Git reads and workspace cleanliness; `assert_delivered` requires the local head to equal the remote head; `sync_delivered` only fast-forwards clean directories that are behind |
| Vigil | Uses existing states to recover unfinished development; unifies implement→deliver; checks the candidate before and after readers run; re-evaluates candidate changes through the existing `MergeNotReady` path |
| Stages/roles | Completing a missing push does not require a new commit; standard/minimal/generate-only retain their original context and policies; readers do not modify the candidate |
| Gates/CLI/forge | Checks the live SHA; both GitHub conditional merging and Gitea execution/idempotency verification retain the SHA; does not write done when merging fails |
| Verification tools | Real local Git, RuntimeState, and queue/worker/claim fault injection independently verify the approved SHA, merged content, and completion rate |

`delivery_heads` refreshes only remote-tracking refs and does not modify the files under review; it checks the workspace both before and after network reads.
The old verdict becomes invalid whether the local head remains at the original candidate while the remote changes, or the local and remote heads have both changed together. An unpushed
new commit created by a reviewer is not a legitimate remote candidate change and still raises a delivery error. Starting a new draft still requires HEAD to advance; delivery recovery allows the same SHA.

Acceptance entry point: `bash scripts/e2e-delivery-review-recovery.sh`. The full test suite uses
`.venv/bin/python -m pytest -q`; desktop service tests require permission to use loopback ports. Stress-test commands and complete historical results are in the
[Concurrent Fault Injection Record](2026-09-09-delivery-recovery-stress-design.md); the script does not read credentials or access real models.

Existing local evidence: 1322 full-suite regression tests and 507 targeted regression tests; among 1152 stress-test tasks, all 1056 normal/recoverable tasks
were merged, and 96 tasks with persistent faults stopped under the original three-attempt budget. Incorrect merges, unexpected blocking, duplicate claims, and leftover queue entries were all zero.
Formal archiving for this round will revalidate the actual committed tree, without treating test results from uncommitted workspace content as evidence for the commit.

## Drawbacks

This adds a small amount of Git-check overhead, and legitimate new candidates require testing/review again. Repositories with incomplete ignore rules may still be rejected because of unknown
files; all untracked files cannot simply be treated as caches. If the remote never stabilizes, completion within a finite number of steps cannot be guaranteed.
The mechanism guarantees consistency between the reviewed and merged versions; it does not automatically prove that the requirements have been fully implemented, nor does it replace acceptance testing with real models.

## Rationale and alternatives

The chosen approach reuses existing states, roles, and failure branches. Adding equality-based rejection alone cannot recover interrupted work, and stress testing has already shown that it can incorrectly suspend tasks;
increasing retry counts only delays incorrect suspension; swallowing all Git exceptions would cause real faults to retry without bound; having the host automatically commit all dirty files
could publish unfinished work; rebuilding the workspace before review would lose the implementation. None of these approaches is adopted.
Merging itself uses the platform’s existing SHA condition, without adding locks, an approval-version database, or a commit ledger.

## Prior art

This directly extends the repository’s existing Git delivery, PR lifecycle, and bounded scheduling. The development role is responsible for committing and pushing, while Workspace provides
deterministic Git facts; Vigil uses those facts to decide whether to recover or re-evaluate. For existing platform capabilities, see
[GitHub CLI conditional merging](https://cli.github.com/manual/gh_pr_merge) and
[Gitea merge API](https://docs.gitea.com/api/operations/repo-merge-pull-request/).

## Unresolved questions

The user has confirmed the requirements and fix for this round; no design choices remain open. A complete workflow with real models/remote services, image deployment, and recovery of historical experiments
are outside this commit. If an old record was incorrectly marked `pr-open` and only a clean Spec remains, the new mechanism cannot reconstruct the missing historical facts.

## Future possibilities

After explicit authorization, build the fixed commit into a new image and run the full real-user workflow; preserve old experiments and archives unchanged.
Continue using the same positive- and negative-case stress-test entry point to validate subsequent workflow changes, without substituting more roles or more retries for the delivery contract.
