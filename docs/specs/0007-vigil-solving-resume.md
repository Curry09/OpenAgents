---
number: "0007"
title: "Vigil recovery—enable solving as a resume entry point and fix orphaned runs left by crashes midway through start_rfc"
issue: 0
slug: vigil-solving-resume
summary: "Fix orphaned runs left when Vigil crashes midway: treat the solving state as a resume entry point so that work can continue after a crash midway through start_rfc instead of starting over. Includes changes to state/orchestrator/vigil and a crash recovery script."
tasks:
  - id: T1
    title: "state: add a status parameter to record_run (write rfc-review in a single operation)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
      - reliability
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
    scope: "Add a status:str=STATUS_PR_OPEN keyword parameter to record_run, persisting a run with pr_number/pr_url and status=<specified value> in a single _save; update the find_by_issue docstring to say “used by the discovery phase to route to fresh / resume” and the RunRecord docstring's enumeration of states (no new states); do not change the begin_run / update_status signatures."
    acceptance: "Unit tests cover record_run(status=STATUS_RFC_REVIEW) yielding rfc-review + a nonzero pr_number in a single write; the default (without passing status) still persists pr-open (no regressions in existing cases); ruff passes; comments reference RFC-0007."
  - id: T2
    title: "orchestrator: add resume to start_rfc + consolidate persistence"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
      - reliability
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: "Add a resume:bool=False parameter to start_rfc. resume=False preserves the current behavior (workspace.prepare + begin_run); resume=True uses workspace.ensure instead (reusing the existing worktree) and does not call begin_run. Both branches converge on the same final sequence: backend.run (drafting) → commit_and_push → create_pr(draft=True) → a single record_run(status=STATUS_RFC_REVIEW, with PR data) (remove the original two writes via record_run + update_status)."
    acceptance: "Unit tests (with a fake backend + an injected fake Workspace + monkeypatched github) cover: fresh uses prepare + begin_run; resume uses ensure and calls neither begin_run nor prepare; both end in rfc-review (with PR data) persisted in a single write, with no transient pr-open (assert that record_run is called with rfc-review and that update_status is no longer called separately); ruff passes; comments reference RFC-0007."
  - id: T3
    title: "vigil: three-way routing for solving recovery in the discovery phase"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
      - reliability
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/vigil.py
      - tests/test_vigil.py
    scope: "Replace _is_new with _dispatch_kind (returning \"fresh\" | \"resume\" | None): record is None and no remote branch exists → \"fresh\"; record.status == STATUS_SOLVING and record.pr_number == 0 → \"resume\"; otherwise → None. discover_and_dispatch calls start_rfc(resume=...) accordingly, preserves error isolation (log and skip failures for individual issues), and returns the list of issue numbers dispatched in this round."
    acceptance: "Unit tests cover: no run + no remote branch → fresh dispatch (resume=False); solving/pr=0 → resume dispatch (resume=True); rfc-review / pr-open / PR already opened / done / closed → skip; remote branch already exists but no run → skip (deduplication gate c); after resume successfully persists rfc-review, the next round does not dispatch the issue again. ruff passes; comments reference RFC-0007."
  - id: T4
    title: "e2e crash recovery script + README entry"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
      - reliability
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-rfc-0007-resume.sh
      - docs/rfcs/README.md
    scope: "Add scripts/e2e-rfc-0007-resume.sh: construct a solving/pr=0 run + a leftover worktree (simulating a crash during drafting), run one round of openagents vigil --once, and assert that the issue is automatically resumed and ultimately gets a draft PR (with rfc-review persisted in state), without manual intervention. Add an RFC-0007 row to docs/rfcs/README.md."
    acceptance: "The script is readable and includes all steps (crash simulation → discover recovery → verify draft PR + rfc-review); the README list includes an RFC-0007 entry."
---

# 0007 · Vigil Recovery—Enable solving as a resume Entry Point and Recover Orphaned Runs Left by Midway start_rfc Crashes

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the 9-section rust-RFC format. -->

## Summary

Vigil (`vigil`) scans issues and dispatches work during the discovery phase of each iteration. When `start_rfc` crashes midway through the “draft RFC → commit → open PR” sequence, it leaves behind an orphaned run with `solving`, `pr_number=0`, and a leftover worktree. The issue is neither new (a run record already exists) nor associated with an open PR (so the “skip if a PR is already open” deduplication gate cannot handle it). It therefore remains stuck indefinitely, neither resumed nor redispatched. This feature recognizes the `solving/pr=0` state as a **resume entry point**: `start_rfc` supports `resume=True` to reuse the existing worktree and continue; Vigil's discovery phase routes issues to fresh / resume / skip; and the original two writes—first `pr-open`, then `update_status` to `rfc-review`—are combined into a single write of `rfc-review`, eliminating the transient intermediate state.

## Motivation

**Current behavior (restated in full so readers do not need to consult another spec).** Vigil (`vigil`) runs with `--once` or in a loop, performing two things in each iteration: the discovery phase scans repository issues and calls `orchestrator.start_rfc` for issues that should be dispatched, drafting an RFC and opening a draft PR. Whether to dispatch is determined by a predicate in the discovery phase (formerly `_is_new`), together with a deduplication gate: issues with an existing run record, an existing remote working branch, or an open PR are not dispatched again.

The `start_rfc` sequence is: `workspace.prepare` (create a worktree) → `begin_run` (persist a `solving` run with `pr_number=0`) → `backend.run` (have the coding agent draft the RFC) → `commit_and_push` → `create_pr(draft=True)` → `record_run` (persist `pr-open` with PR details) → `update_status` (change to `rfc-review`).

**Problems.** This sequence has two flaws:

1. **Orphaned runs cannot be resumed.** If the process crashes after `begin_run` but before `create_pr` (drafting takes the longest and is most susceptible to interruption), the remaining run is `solving/pr=0`, and the worktree still exists. In the next iteration, Vigil discovers that the issue “already has a run” → it is not fresh, and also “has no open PR” → the deduplication gate cannot let it through. As a result, it falls between the two cases and is left unattended. A person must manually clean up the state and worktree before it can start again—contrary to the original goal of having Vigil provide automatic recovery.
2. **A transient intermediate state exists.** The normal path first writes `pr-open` and then changes it to `rfc-review`, leaving a momentary `pr-open` state in between. A crash between the two writes leaves another orphaned state. These two writes could be combined into one.

Desired behavior: treat `solving/pr=0` as a signal that “drafting crashed and can resume from the existing worktree,” allowing Vigil to resume automatically; and eliminate the transient state by writing `rfc-review` in a single operation, narrowing the crash window.

## Guide-level explanation

For users, the behavioral change is that “Vigil is more robust”: when a drafting attempt crashes midway, the next `openagents vigil --once` automatically recognizes the `solving/pr=0` run, reuses its leftover worktree to finish drafting the RFC, and opens a draft PR, with no manual cleanup required.

The discovery phase now determines one of three outcomes for each issue (previously, it only made the binary distinction “new / not new”):

| Situation | Outcome | Meaning |
|------|------|------|
| No run record and no remote working branch | **fresh** | A new issue; `start_rfc(resume=False)` drafts from scratch |
| The run is `solving` and `pr_number=0` | **resume** | An orphan left by a crash during drafting; `start_rfc(resume=True)` reuses the worktree and resumes |
| Anything else (`rfc-review` / `pr-open` / an open PR / `done` / `closed` / a remote branch but no run) | **skip** | Already in progress or completed; do not redispatch |

## Reference-level explanation

The changes are divided into 4 Tasks (see the DAG below; `files` do not overlap, and each Task has a single writer):

1. **T1 state** (no dependencies) — Add the keyword parameter `status: str = STATUS_PR_OPEN` to `record_run`, allowing a single `_save` to persist a run with `pr_number/pr_url` and `status=<specified value>`, thereby consolidating the two writes, “first pr-open, then update_status,” into one. The signatures of `begin_run` / `update_status` remain unchanged; update the docstrings of `find_by_issue` and `RunRecord` to say “used by the discovery phase to route fresh / resume”; no new status enum values are added.
2. **T2 orchestrator** (depends on T1) — Add `resume: bool = False` to `start_rfc`. With `resume=False`, use `workspace.prepare` + `begin_run` (the current behavior); with `resume=True`, use `workspace.ensure` instead (reuse the existing worktree) and **do not** call `begin_run`. Both branches converge on the same final sequence: `backend.run` (drafting) → `commit_and_push` → `create_pr(draft=True)` → a **single** `record_run(status=STATUS_RFC_REVIEW, with PR details)`, removing the original two writes via `record_run` + `update_status`. Write `rfc-review` in one operation, eliminating the transient `pr-open` state.
3. **T3 vigil** (depends on T2) — Replace the old `_is_new` with `_dispatch_kind` (returning `"fresh" | "resume" | None`): `record is None` and no remote branch → `"fresh"`; `record.status == STATUS_SOLVING and record.pr_number == 0` → `"resume"`; anything else → `None` (skip). `discover_and_dispatch` calls `start_rfc(resume=...)` accordingly, retains the existing error isolation that logs a failure for an individual issue and skips it, and returns the list of issue numbers dispatched in this iteration. The deduplication gate “remote branch already exists but no run → skip” remains unchanged.
4. **T4 e2e + README** (depends on T3) — Add `scripts/e2e-rfc-0007-resume.sh`: construct a `solving/pr=0` run + a leftover worktree (simulating a crash during drafting), run one iteration of `openagents vigil --once`, and assert that the issue is automatically resumed and ultimately gets a draft PR (with `rfc-review` persisted in state), without manual intervention. Add an RFC-0007 row to `docs/rfcs/README.md`.

**End-to-end validation**: `bash scripts/e2e-rfc-0007-resume.sh` (construct an orphaned run + a leftover worktree → vigil --once automatically resumes → verify draft PR + rfc-review).

Dependency DAG: `T1 → T2 → T3 → T4` (a linear chain).

## Drawbacks

- Classifying all `solving/pr=0` runs as “resumable” assumes that this state can only result from a crash during drafting; if `solving` acquires other meanings in the future, the recovery criteria will need to be tightened accordingly.
- Resuming reuses the existing worktree. If the crash leaves the worktree dirty (with partial changes), execution continues on top of those changes—this relies on the coding agent's idempotent drafting being able to tolerate existing content.

## Rationale and alternatives

- **Why use `solving/pr=0` as the resume signal**: it precisely describes the crash window in which “a run has been registered, but no PR has been opened yet.” It does not overlap with either “fresh (no run)” or “PR already open (handled by the deduplication gate),” making the three-way routing unambiguous.
- **Why combine two writes into one**: the transient `pr-open→rfc-review` state is itself a potential source of orphans; writing `rfc-review` in one operation minimizes the crash window without requiring new status enum values (Occam's razor, principle 1).
- **Alternative: a manual cleanup script.** Rejected—it contradicts the goal of “Vigil provides automatic recovery” and puts the recovery burden back on people.
- **Alternative: roll back on a crash (delete the run + worktree and start from scratch).** Rejected: drafting is the most expensive step, and discarding already drafted content wastes compute; resuming is more economical.
- **Leave the signatures of `begin_run` / `update_status` unchanged**, adding only the optional `status` parameter to `record_run`—this minimizes the blast radius (decoupling, principle 10), with zero regressions for existing callers.

## Prior art

“Resuming from persisted state after a crash rather than rerunning” is a standard checkpoint/resume pattern in workflow engines such as Airflow and Temporal. This feature adopts its core idea—using a persisted run record with a status as a checkpoint and deciding whether to resume or start fresh based on that status—and implements it as lightweight three-way routing in Vigil's discovery phase, without introducing an additional engine.

## Unresolved questions

None. The three-way routing criteria, writing rfc-review in one operation, and the semantics of reusing a worktree on resume have all been settled within this group.

## Future possibilities

- The resume criteria could be extended to cover more crash points (such as `pr-open` when the PR was not actually created), refining the state machine as needed.
- The e2e script could be included in CI's offline smoke suite to routinely validate the crash recovery path.
