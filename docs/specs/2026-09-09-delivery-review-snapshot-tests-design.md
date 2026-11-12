# Delivery and Review Version Consistency: Regression Test Design

> The following is the historical baseline from before the fix, retaining the results at that time. For the fix implementation and latest acceptance results, see
> [Delivery Recovery and Review Version Consistency Fix](2026-09-09-delivery-review-recovery-design.md).

Status: Test code changes are complete; the production fix has not yet been implemented. This document supplements the existing workspace, delivery, and review contracts in RFC-0005, Spec-0056, and Spec-0017 without adding roles, stages, queues, or persistent records.

## Problem and Scope

In the spec61-ronacher-next-20260909-retry2 experiment on 2026-09-09, development had pushed Spec commit
472621c, after which the implementation remained in the workspace; following a call timeout, the existing draft PR was marked ready. The reviewer inspected the uncommitted implementation in
`git diff HEAD -- entry.py`, but the framework applied the approval label to the remote Spec commit.
Evidence: recovery-20260909/old-scheduler.log:3692–3821 in the adjacent experiment directory.

The single core constraint: the approved candidate must be the candidate actually inspected; a passing result for additional local changes must not be bound to a remote commit. This change adds only offline unit regressions and normal-path protection; it does not modify running experiments or production logic.

## Verify Both Safety and Ability to Progress

| Scenario | Expected behavior |
| --- | --- |
| The workspace is clean, and local and remote versions match | Review, approve, and merge normally, without an additional call to the delivery role |
| Unstaged changes, staged changes, new source files, deletions, or conflicts | Do not count undelivered changes as delivered |
| Committed but not pushed | Do not approve the old remote version; continue through the existing delivery path |
| The delivery role only needs to push | Delivery is complete once the remote reaches the existing local commit; do not require an additional empty commit |
| A call times out, and both the draft and local implementation remain | Do not recreate or clear the implementation; resume existing development/delivery, then review again |
| The version or source changes while the reviewer is running | This result must not certify another candidate |
| Only test caches or observation artifacts ignored by Git are present | Do not block approval because of ordinary test byproducts |
| The workspace is not clean during CI fixes or review rework | Still allow the development role to continue; do not put delivery checks before every action |
| A Gitea draft has mergeable=false | Preserve the ability to mark it ready; do not reintroduce the old deadlock |
| A normal rebase changes the remote, leaving the old workspace behind | Synchronize and then review again; do not permanently reject it or directly approve the old workspace |

It is not enough to prove only that a candidate was “rejected.” Recovery tests must also prove that existing roles are called to resume delivery, that the latest commit is approved again, and that the workflow ultimately completes. Ignored caches are determined by Git ignore rules; do not arbitrarily exempt all untracked files or guess which files are source code by extension. Tests/documentation tracked by Git may also be part of the delivery; they are not caches.

## Test Locations and Execution

- tests/test_workspace.py: existing unit boundaries for assert_delivered and ensure, with Git subprocess test doubles.
- tests/test_recipe_vigil_act.py: reuse the existing rig and invoke real classification/actions/stage; the model and forge are offline.
  Snapshot scenarios restore the real Workspace.assert_delivered; an always-passing test double must not conceal the target vulnerability.
- Also run existing stages, gates, and vigil regressions to prevent the fix from disrupting the normal call order.
- tests/test_runtime_gates.py: when the remote version changes before merge but the old label remains, matching only the supplied old SHA is insufficient.
- tests/test_recipe_stages.py: under real HEAD/evidence gates, completing a pending push must not be classified as zero progress.

Confirmed defects are marked with strict xfail, and `--runxfail` runs them as ordinary failures; this explicitly records unresolved issues and is not acceptance of a fix. After implementation, an XPASS will cause the test to fail, requiring removal of the corresponding xfail and inspection of the assertions.
Normal paths must not use xfail.

```sh
.venv/bin/python -m pytest tests/test_workspace.py tests/test_recipe_vigil_act.py tests/test_runtime_gates.py tests/test_recipe_stages.py -q
.venv/bin/python -m pytest tests/test_workspace.py tests/test_recipe_vigil_act.py tests/test_runtime_gates.py tests/test_recipe_stages.py -k delivery_snapshot --runxfail -q
```

This is an entry point for component-level offline regressions, not a real end-to-end loop with the model/forge. No fix has been implemented yet, so these results cannot support a claim that the actual rate of blocked tasks in batch runs after the fix is zero. If the recovery path still cannot progress, first work through the handoffs along solve → ready → CI/e2e → review/rework
→ merge, rather than increasing retry counts or adding termination labels.

## Results of This Change and Development Workflow Audit

Added 33 parameterized cases: 13 passed, 20 strict xfailed. Running with `--runxfail` produced
13 passed, 20 failed; all failures occurred at the target assertions or confirmed delivery exceptions, rather than because of network/model issues or missing test doubles.
20 is the number of failing scenarios, not 20 independent bugs, and certainly not a production blocking rate.
The full test suite reported 1246 passed, 20 xfailed (16.53 seconds); Ruff check and git diff --check passed.
In the initial restricted-environment run, 3 local HTTP cases failed because of socket permissions. After loopback sockets were allowed, the full rerun passed; environment permission errors are not counted as product defects. No production code under openagents/ was modified in this change.

| Existing handoff | Verified problem or behavior that must be preserved | What the fix must not do as its sole solution |
| --- | --- | --- |
| implement → deliver within solve | Uncommitted changes are handed to deliver; however, when HEAD has advanced without a push, an exception is raised directly | Treat commit as equivalent to push, or merely raise an error and terminate |
| deliver → subsequent checks | Currently requires this call to produce a new commit; merely completing a push is classified as zero progress | Use an empty commit to advance the counter |
| Timeout → existing PR | Currently skips the remaining delivery after ready and proceeds directly to subsequent review | Treat “PR exists” as meaning the implementation has been delivered |
| draft → ready | Gitea drafts report mergeable=false; marking them ready early prevents deadlock | Simply move the transition to ready after all gates |
| CI / review rework → implement | Continued development must still be allowed in a workspace that is not clean | Require clean uniformly at every role entry point |
| rebase / review → approval | ensure reuses the old directory; the remote and workspace may be at different versions | Permanently reject a clean workspace that is behind, or approve old content |
| Approval → merge | The live snapshot contains HEAD, but the gate uses only labels and the supplied old HEAD | Assume that a push deletes old approval labels |

The first round of safety tests permits explicit rejection of inconsistent candidates; recovery tests do not swallow exceptions and require actual calls to existing development/delivery roles, PR reuse, renewed approval of the latest commit, and eventual done. This avoids mistaking “did not merge the wrong thing” for “the workflow is fixed.”
Git ignore is modeled by test doubles in these unit tests; compatibility with all log artifacts from the real harness has not been demonstrated.
Implementation completion is also not judged by whether “some particular kind of source file must be modified,” to avoid incorrectly blocking legitimate documentation tasks.

Acceptance criteria after the actual fix: remove xfail from fixed scenarios, have all applicable cases pass normally, and then use the same batch of real tasks to compare completion rates, additional role calls, and sustained retries; testing only the number of interceptions is insufficient to determine whether the fix causes widespread stalls.
