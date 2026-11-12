# Delivery Recovery and Review Version Consistency Fix

Status: Code changes are complete. Local regression tests and subsequent concurrent stress acceptance tests passed; erroneous suspension during successive remote candidate changes has been fixed. Not deployed.
See [Concurrent Fault-Injection Stress Testing](2026-09-09-delivery-recovery-stress-design.md). Supplements Spec-0056 /
Spec-0017; the earlier snapshot-tests documentation is retained as evidence from before the fix.

## Core Contract

Unfinished development is not completed delivery; committed but unpushed work does not necessarily require rewriting code; review approval certifies only the candidate actually inspected. Reuse the existing Implementer, Deliver, Reviewer, run.status, and scheduling queue without adding roles,
queues, database fields, or approval ledgers.

## Workflow

1. Before invoking the developer, record the unfinished handoff using the existing run.status=iterating; return to
   pr-open only after successful delivery. After an interruption, recover the same PR and the same workspace, continue checking the task and self-tests, and do not invoke prepare
   to force a rebuild. When no explicit completion result exists, allow the existing developer to verify and finish the work, but do not require an additional empty commit.
2. After development returns, check whether the results have been committed and pushed. Invoke the existing Deliver when only Git
   delivery remains; success requires local HEAD to equal the remote and no undelivered files to remain. The delivery role's completion criterion no longer requires HEAD to change during the current invocation.
3. Resume pending development before waiting for CI/review/merge; preserve the priorities for
   replies to humans, terminal states, dependencies, and in-flight work.
   Normal draft-to-ready transitions must remain possible, without introducing a deadlock through Gitea draft mergeable=false.
4. Before review, confirm that the workspace matches the remote candidate: when it is clean and only behind, synchronize only by fast-forward; if there are local changes or divergence,
   hand it back to the existing development/delivery flow without reset, clean, rebuilding, or silently discarding any commits.
5. After review, check the workspace and remote HEAD again. If the candidate changed in the meantime, discard this verdict and return to the existing scheduler for reassessment;
   immediately before merging, check the live PR HEAD and approval labels, and pass the same SHA into the forge's native merge condition to cover
   the time gap between checking and execution; a failed merge must not close the issue. The REWORK branch must not be blocked by a preceding clean check.
6. Git-ignored caches do not affect delivery; new files that are not ignored cannot all be exempted. Git read errors caused by networking, permissions, or similar problems
   must not be treated as “delivered” or automatically cause a model to be assigned to fix source code. The existing bounded exception recovery remains responsible for bringing genuine failures to a bounded conclusion.
7. `delivery_heads` reuses Git facts already checked, without prematurely classifying a local/remote mismatch as a delivery failure. When the original candidate
   is legitimately replaced during review, use the existing `MergeNotReady` path to detect the new state again, without consuming the execution-failure budget; unpushed
   review commits, uncommitted source code, and read errors still fail within bounded limits. The strict equality gate for development delivery remains unchanged.

## Implementation and Acceptance Criteria

- workspace.py: Include workspace checks in delivery and safely synchronize candidates that are clean and behind.
- stages.py, agents/deliver.py: Prioritize actual push results; completing a missing push does not require an empty commit.
- recipes/vigil.py: Recover the existing development state, unify development handoffs, and validate before and after review.
- runtime/gates.py: Check the live HEAD when merging.
- forge / merge-pr: Pass through the existing candidate SHA without adding locks or version ledgers. GitHub uses
  [--match-head-commit](https://cli.github.com/manual/gh_pr_merge), and Gitea uses
  [head_commit_id](https://docs.gitea.com/api/operations/repo-merge-pull-request/); Gitea's
  idempotency verification command must also carry the same condition and must not retry the merge unconditionally during rechecking.
- Rerun the 33 existing regression scenarios and remove the fixed xfail markers; add real local Git regression tests, recovery scheduling tests, and tests
  that protect normal workflows. Test doubles must simulate the new IO; they must not obtain passing results by disabling the checks under test.

The local acceptance entry point is scripts/e2e-delivery-review-recovery.sh. It uses a fake model and local Git,
does not claim to have verified the completion rate of large batches of tasks with real models, and does not replace running experiments or old archives.

## Acceptance Record (2026-09-09)

Execution directory: `/root/src/OpenAgents`.

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q` | 1304 passed, 18.49 seconds; no xfail; desktop tests require local loopback socket permissions |
| `bash scripts/e2e-delivery-review-recovery.sh` | 489 passed, 14.08 seconds; no model, external Git service, or credentials required |
| Dedicated real local Git tests | 20 passed; includes 4 complete recovery → review → merge scenarios and 6 minimal/generate-only recovery delivery scenarios |
| Original 33 snapshot regression tests | All passed as regular tests; the original 20 strict xfail markers were removed |
| Ruff check / format for files modified in this change | Passed |
| Spec validate, graph --check, git diff --check | Passed; historical Spec warnings remain |

The complete recovery tests actually use a local bare remote, independent worktrees, real Git, and RuntimeState; they replace only
model and forge IO, without replacing classification, scheduling, delivery checks, or post-review version checks. At the end, the tests read `entry.py`
on remote main to confirm that the implementation reached the final candidate, rather than merely observing a PASS label.

| What remains after interruption | Verified recovery path |
| --- | --- |
| Only a pushed Spec/base candidate, with no implementation yet | Original developer continues implementation → Deliver → Reviewer → merge |
| Partially written, uncommitted implementation | Continue writing in the original workspace → Deliver → Reviewer → merge |
| Implementation committed but not pushed | Developer verifies completion → complete only the push → Reviewer → merge; HEAD need not change |
| Implementation pushed, but completion response lost due to timeout | Developer verifies once → Reviewer → merge; no Deliver invocation and no empty commit |

Progress safeguards also cover: pending development can enter the original queue while CI is pending and is not suppressed by an old zero-progress stamp;
priorities for dependencies, human replies, terminal states, in-flight work, and draft-ready are preserved; normal REWORK can modify a dirty
workspace; skipped stages do not unexpectedly trigger development; clean branches that are behind can fast-forward; divergence/local-ahead states do not lose commits;
Git-ignored caches do not trigger repeated development; network read failures cannot use stale refs to masquerade as completed delivery; reported merge failures do not close issues.

Boundary: This proves offline correctness and the reachability of recovery paths, not production throughput. No batch
comparison using real models has been run, and no experiment containers have been modified. For historical runs incorrectly marked pr-open whose workspaces contain only a clean Spec, there is insufficient information
to automatically reconstruct the lost stage facts; they still proceed to review against the exact remote candidate, and this cannot be claimed to have automatically repaired all old archives.

Repository-wide Ruff checks still have historical issues untouched by this change: import sorting in `tests/test_fleet.py` and
`tests/test_runtime_state_converge.py`, as well as formatting drift in other unchanged files.
This change did not bulk-rewrite unrelated files to make repository-wide lint pass; the pre-existing Spec-0088 / OVERVIEW edits were also left intact.

## Acceptance of the Subsequent Fix for Successive Candidate Changes

The final full suite reported **1322 passed**, and the dedicated script reported **507 passed**. The same commands used before the fix were rerun for 1152 stress tasks:
40 candidate-change targets, 104 normal boundary-case controls, and 912 routine recoverable tasks all merged; 96 persistent failures stopped under the original three-attempt
budget and did not merge. Unexpected blocks, incorrect merges, duplicate claims, and leftover queue entries were all 0; no roles, queues, state fields,
or retry limits were added. See the concurrent fault-injection stress-testing document linked above for detailed historical comparisons, raw report paths, and offline validation limitations.

## Formal Spec and Commit Acceptance

This change was organized according to the repository's `spec-driven-development` conventions as
[Spec-0089](0089-delivery-review-recovery.md): a nine-part overview, architectural choices, positive and negative behavioral acceptance criteria, a single Task, and
an exact file list, with status done. Existing dated records are retained as historical evidence; unfinished requirements from Spec-0088 are not counted as part of this delivery.

An independent snapshot was exported from the Git staging area, and OVERVIEW was then generated from that snapshot; only changes for this Spec were staged from the generated output,
while the original workspace edits to Spec-0088 and its derived views were retained. The full test suite was rerun against that independent snapshot: **1322 passed**;
aggregate coverage for the 12 modified production files, including branch coverage, was **88%**, with per-file coverage of **83%–100%**. The coverage tooling reused
the coverage package from a nearby installed environment, without adding project dependencies or replacing packages already present in the test environment. The report is in the local temporary snapshot at
`/tmp/openagents-spec0089-submit-qZTdxJ/coverage.data`; it is not claimed to be a remote CI result.

Ruff check / format passed for the 24 Python files in this change; Spec validate, graph --check, file ownership,
local numbering conflict checks, and staged diff checks passed. The repository still has the historical Ruff issues noted above; CI was not disabled and unrelated files were not modified
to conceal failures. Remote numbering/branches and CI status require a usable GitHub identity to confirm. Currently, origin HTTPS lacks
usable authentication, so fetch cannot complete; pushing or deployment may be reported separately only after actually succeeding.
