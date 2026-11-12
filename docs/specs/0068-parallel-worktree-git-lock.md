---
number: "0068"
title: "Eliminating shared .git lock contention during parallel Vigil worktree prepare: a single coarse-grained git-mutation serialization lock"
issue: 137
slug: parallel-worktree-git-lock
summary: "Spec-0065 has already converted vigil into a K-worker parallel pool (--parallel K) and implemented P1/P3/P4/P5; the only remaining concurrency risk is P2—K workers concurrently running Workspace.prepare/ensure (fetch + worktree remove/prune/add + branch -D) against the same main repository's .git contend for packed-refs.lock / worktree management locks, and worktree prune has global side effects across workers that can mistakenly clean up another worker's partially created worktree. The fix follows Occam's razor (direction 1 suggested in the issue): add a process-level git-mutation serialization lock in utils/workspace.py (at module scope, analogous to state._LOCK) to serialize the entire sequence of shared .git mutations in prepare/ensure; prepare takes only seconds, while drafting + reconcile takes minutes, so serialization barely reduces parallelism while eliminating all git lock races in one step. Since prune is covered by the same lock, it can no longer collide with concurrent add operations. commit_and_push runs against each worktree's private index and is inherently isolated, so it does not acquire the lock."
e2e:
  intent: "Prove that \"K workers concurrently creating worktrees in the same main repository's .git\" no longer causes Git lock contention after adding a process-level serialization lock for git mutations—N (≥4) threads, each with a different issue_number/branch, call Workspace.prepare concurrently; all successfully create worktrees, with zero WorkspaceError instances, and git stderr contains neither cannot lock ref nor could not lock working tree; moreover, the shared .git mutation sections in prepare/ensure are mutually exclusive under the lock, while commit_and_push and assert_delivered do not acquire the lock."
  method: "Form: a purely internal concurrency correctness fix (form=cli), with no navigable product-facing frontend; under the evidence-gathering discipline of \"purely internal →\nproportionate automated tests,\" use concurrent regression testing (without accessing real LLMs / GitHub / the network, using only local temporary git repositories):\n1. Workspace unit tests (tests/test_workspace.py): monkeypatch Workspace._git to record call order, and assert\n   that the .git mutation sections in prepare and ensure execute while _GIT_MUTATION_LOCK is held (the lock is already held upon entering the callback);\n   commit_and_push / assert_delivered do not acquire this lock.\n2. Concurrent regression test (tests/test_workspace_concurrency.py): actually start N (≥4) threading.Thread instances to call prepare concurrently against the same\n   temporary git repository (each with a different issue_number/branch); after join, assert that all return valid worktree\n   paths, that there are zero WorkspaceError instances, and that captured git stderr contains neither 'cannot lock ref' nor 'could not lock working\n   tree'; document that removing the lock makes this test flaky (a control comparison, not run on an ongoing basis).\n3. Run the offline portion of scripts/e2e-spec-0068-parallel-worktree-git-lock.sh with all checks passing: ruff check +\n   ruff format --check + pytest tests/test_workspace.py tests/test_workspace_concurrency.py.\n"
tasks:
  - id: T1
    title: "Add a process-level git-mutation serialization lock in workspace.py, covering the shared .git mutation sections in prepare/ensure"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/workspace.py
      - tests/test_workspace.py
    scope: "Add a module-level _GIT_MUTATION_LOCK = threading.Lock() in utils/workspace.py (analogous to RuntimeState._LOCK); use it in a with block around the entire fetch→worktree remove→prune→branch -D→worktree add sequence in Workspace.prepare, and around fetch→worktree add in ensure; commit_and_push (worktree-private index) and assert_delivered (read-only) do not acquire the lock. Reference # Spec-0068/T1 in a code comment."
    acceptance: "pytest tests/test_workspace.py passes: prepare and ensure execute while holding the lock (monkeypatch _git to record the call sequence + assert that the lock is already held on entry / or use a reentrancy probe to demonstrate mutual exclusion between the two), and commit_and_push and assert_delivered do not acquire this lock; all ruff checks pass."
  - id: T2
    title: "Concurrency regression test + offline e2e script: N threads concurrently prepare worktrees against the same main repository's .git with zero lock contention"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tests/test_workspace_concurrency.py
      - scripts/e2e-spec-0068-parallel-worktree-git-lock.sh
    scope: "Add a concurrency regression test: start N(≥4) threads that concurrently call Workspace.prepare against the same temporary git repository (each with a different issue_number/branch), and assert that all worktrees are successfully created, there are zero WorkspaceError exceptions, and git stderr contains neither 'cannot lock ref' nor 'could not lock working tree'; as a control, assert that removing the lock makes this test flaky/fail (document this; it does not need to be run on an ongoing basis). Add an offline e2e script that aggregates ruff check + ruff format --check + targeted pytest tests."
    acceptance: "bash scripts/e2e-spec-0068-parallel-worktree-git-lock.sh passes: ruff check + ruff format --check + pytest tests/test_workspace_concurrency.py all pass; the concurrency test passes consistently with N≥4 (no git lock errors, all worktrees created)."
---

# 0068 · Eliminating shared .git lock contention during parallel Vigil worktree prepare: a single coarse-grained git-mutation serialization lock

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

issue #137 calls for “vigil --parallel N: solving multiple issues in parallel within the same repository” and lists six concurrency risks, P1–P6. Readers must first understand a key premise: **P1/P3/P4/P5 were already delivered by Spec-0065 (graph-driven parallel Vigil, issue #150) and merged into main as part of its in-place rewrite of vigil into level-triggered reconcile + a K-worker pool**—the `vigil --parallel K` command **can run right now**. This spec therefore does not rebuild the worker pool; it addresses only the one remaining risk that Spec-0065 did not touch:

**P2 — K workers concurrently run `Workspace.prepare` / `Workspace.ensure` (`fetch` + `worktree remove` + `worktree prune` + `branch -D` + `worktree add`) against the same main repository’s `.git`, without any serialization lock. They contend for git ref locks / worktree management locks, and `worktree prune` has global side effects across workers that can mistakenly clean up another worker’s partially completed worktree.**

The fix follows Occam’s razor (Principle 1, also the issue’s own suggested direction 1): add **a single process-level git-mutation serialization lock** in `openagents/utils/workspace.py` (at module scope, directly copying this repository’s existing `RuntimeState._LOCK` pattern), and serialize the entire sequence of mutations to the shared `.git` inside `prepare` / `ensure`. `prepare` takes only seconds, while the subsequent drafting + reconcile takes minutes. Serializing those few seconds barely reduces parallelism, yet eliminates all three categories of git lock races at once; `worktree prune` runs under the same lock, making collisions with concurrent `worktree add` impossible from then on. The genuinely isolated `commit_and_push` (which runs against each worktree’s private index) does not acquire the lock.

## Motivation

### The target model in issue #137 (restated here to make this spec self-contained)

issue #137 calls for “a worker pool where each worker claims one issue and runs its entire lifecycle sequentially (claim → draft → advance its PR through to merge), with N workers running in parallel, each managing its own issue.” It lists six risks **newly introduced** by parallelism:

- **P1 — Concurrent writes to shared local State**: N workers concurrently write to the same RuntimeState → lost updates / file corruption.
- **P2 — git lock contention on the shared main repository’s `.git`**: every worker creates a worktree by issuing `fetch` / `worktree remove` / `worktree prune` / `branch -D` / `worktree add` in succession against the same `.git`.
- **P3 — `messages.poll` is global**: the old poll advances all open PRs, which does not match “each worker advances only its own PR.”
- **P4 — Concurrency limits and rate limiting**: no upper bound = a backend fork bomb; `--parallel N` is required (with a conservative default).
- **P5 — Interleaved logs / cascading cleanup on Ctrl-C / worker-level error isolation**.
- **P6 — Specific to multiple users**: agent_id collisions / thrashing over preemption by the last-place created_at / human review throughput bottlenecks.

### Current status: P1/P3/P4/P5 were delivered by Spec-0065 (evidence-driven)

When Spec-0065 (issue #150) rewrote `run_vigil` into K persistent worker threads + a SQLite claim queue + flock proof of liveness + level-triggered reconcile, it also closed out most of issue #137. Checking each item against the current code on main:

| Risk | Status | Evidence (current code) |
|---|---|---|
| **P1** Concurrent State writes | ✅ Resolved | `RuntimeState._LOCK = threading.RLock()` (`openagents/runtime/state.py:58`); every read-modify-write operation, including `set_run` / cursor updates, runs entirely within `with RuntimeState._LOCK` (same file :81/:123/:161/:180…)—concurrent writes by K workers no longer lose updates |
| **P3** Global poll | ✅ Obsolete | The old `messages.poll` was deleted along with the old sequential vigil; it is now per-subject `_reconcile` (`recipes/vigil.py`), with each worker advancing only the one subject it claimed |
| **P4** `--parallel N` | ✅ Delivered | `oa vigil --parallel K` (`openagents/cli.py`: `_parallel_k` validates `1..{_MAX_PARALLEL}`, and `default=1` means sequential execution); K is naturally constrained by the issue dependency graph, while `_MAX_PARALLEL` is merely a guardrail against accidental input |
| **P5** Logs/Ctrl-C/isolation | ✅ Delivered | `run_vigil` starts K worker threads; an exception in one subject does not kill the worker, and `KeyboardInterrupt` shuts down the pool via `stop_event` (the Spec-0065/T2 acceptance criteria already include these items) |

**So `vigil --parallel K` can run right now.** Designing another worker pool in this spec would insert a duplicate design that conflicts with already merged code into a “living snapshot with no legacy,” violating Occam’s razor.

### P2 is still present: the worktree prepare sequence has no serialization lock on the shared `.git`

Spec-0065 focused entirely on the reconcile loop, the SQLite queue, and flock-based claims; it **did not touch** the git operations that create/clean up worktrees. The current `Workspace.prepare` (`openagents/utils/workspace.py:55-72`) runs these commands sequentially:

```
fetch origin <base>            # Decision 2: fetch the latest base
worktree remove --force <path> # Decision 4: idempotently clean up leftovers
worktree prune                 # ← Global side effect
branch -D <branch>
worktree add -b <branch> <path> origin/<base>
```

**All five commands act on the same main repository’s `.git`**, and `_do_solve` (`openagents/recipes/vigil.py:2802`: `git.Workspace(work_dir=work_dir).prepare(...)`) calls this sequence **concurrently from K worker threads**, with no serialization lock in between (the only relevant locks anywhere in the repository are `state._LOCK` and the claim flock, neither of which covers this sequence). `ensure` (`workspace.py:74-81`, continuation paths at `vigil.py:3048/3051`) likewise runs `fetch` + `worktree add` and has the same exposure. Specific failures under concurrency:

- **`fetch` + `branch -D` contend for `.git/packed-refs.lock`** → `cannot lock ref … File exists`, and git exits with a nonzero status (`fetch` / `worktree add` in `prepare` use `check=True`, so an exception immediately interrupts that worker’s solve).
- **`worktree add` / `worktree remove` contend for management locks under `.git/worktrees/`** → `could not lock working tree`.
- **`worktree prune` has global side effects across workers**: it cleans up registration entries in `$GIT_DIR/worktrees` whose “working trees have disappeared”; if worker A is executing `worktree add` (the directory has been created, but the management entry is only partially written) and worker B happens to run prune → prune may treat A’s partially completed registration entry as a “disappeared working tree” and remove it, breaking the isolation rule that “each worker touches only its own issue.”
- **`fetch` may trigger auto-gc**, locking the object store and crippling concurrent git operations.

The only operation that is truly isolated by design is `commit_and_push` (which runs against each worktree’s **private index**, using add/commit in `workspace.py`). It does not touch ref/worktree management in the shared `.git`, so it does not need the lock.

### Why P6 is outside this spec’s scope

- **agent_id collisions** → Already addressed by `identity.resolve_agent_id` (env > state > generate); if startup uniqueness validation is needed, that is a separate small feature requiring its own spec.
- **Thrashing over preemption by the last-place created_at** → Already covered by the existing claim debouncing (Spec-0049 anti-thrash); its ownership/age checks are independent of the worker count, and K>1 does not change their validity.
- **Human review throughput bottlenecks** → An operational parameter (reduce `--parallel`), not a code defect.

Adding these three items to this spec would dilute its focus on “one concurrency correctness fix,” so they are explicitly excluded under Unresolved.

## Guide-level explanation

Described as though it has already been implemented:

`run_vigil` starts K persistent workers (already provided by Spec-0065). When a worker claims an issue that does not yet have a PR and enters the solve branch to create an isolated worktree, the first thing `Workspace.prepare` does is **acquire a process-level git-mutation lock**. Once it holds the lock, it executes the entire sequence of mutations to the shared `.git`—`fetch` → `worktree remove` → `worktree prune` → `branch -D` → `worktree add`—serially in one pass (taking seconds). After obtaining the worktree path, it **immediately releases the lock**, then proceeds to drafting + reconcile, which take minutes. As a result:

- **Drafting / advancement by K workers runs truly in parallel** (each has its own worktree-private index, independent of the others);
- **Only those few seconds of `.git` mutations are serialized**—at any moment, at most one worker is modifying the main repository’s refs and worktree management records, structurally eliminating `cannot lock ref` / `could not lock working tree`;
- **`worktree prune` runs inside the lock** → it executes only when no other worker is executing `worktree add` → it can no longer mistakenly clean up partially completed worktrees.

**Why one coarse lock is enough, and why that small amount of serialization is acceptable**: `prepare` / `ensure` take seconds, while drafting + reconcile for each issue take minutes. At K=3, the lock contention window is only the first few seconds of each issue’s entire lifecycle, accounting for less than 1%. Trading this negligible loss of parallelism for “one lock that eliminates three categories of races at once, with changes concentrated in one file” directly fulfills Principle 1.

## Reference-level explanation

### Lock placement and type

Add a **module-level** lock in `openagents/utils/workspace.py`:

```python
# Spec-0068/T1: Process-level git-mutation serialization lock — see the same pattern in RuntimeState._LOCK.
_GIT_MUTATION_LOCK = threading.Lock()
```

- **Why module-level rather than instance-level**: `Workspace` currently creates a new instance on every call (`git.Workspace(work_dir=work_dir).prepare(...)`, `vigil.py:2802`); an instance lock cannot serialize calls across workers. A single module-level lock covers all workers in the same process.
- **Why one lock is enough, without partitioning by work_dir**: one vigil process serves only one repository (one `work_dir` / one `.git`); cross-repository parallelism (fleet / `vigil-all`) uses **subprocesses**, providing inherent process isolation → different processes each hold an independent module-level lock → this neither needlessly serializes operations across repositories nor leaves operations unprotected.
- **Why `threading.Lock` rather than `RLock`**: the mutation sequences in `prepare` / `ensure` do not nest within themselves (they do not call `prepare`/`ensure` again while holding the lock), so mutual exclusion is sufficient; reentrancy is unnecessary.

### Lock scope (what acquires the lock and what does not)

| Method | Acquires the lock? | Reason |
|---|---|---|
| `Workspace.prepare` | ✅ The entire `fetch`→`remove`→`prune`→`branch -D`→`add` sequence runs under the lock | All operations act on refs / worktree registry entries in the shared `.git` |
| `Workspace.ensure` | ✅ The entire `fetch`→`worktree add` sequence runs under the lock | Also touches the shared `.git` |
| `Workspace.commit_and_push` | ❌ Does not acquire the lock | Runs against each worktree's **private index**, which is inherently isolated (issue #137 explicitly identifies this as the only truly isolated part) |
| `Workspace.assert_delivered` | ❌ Does not acquire the lock | Read-only (`fetch` + `rev-parse`); acts on the worktree itself without changing shared refs |

`prune` and `add` now run **under the same lock** → the two are serialized → prune never runs while an add is in flight → “accidentally cleaning up a partially created worktree” is structurally eliminated, with **no need** to move prune out into a separate maintenance step (that is alternative A; see Rationale).

### DAG + file allocation

```mermaid
graph LR
  T1[T1 workspace.py locking + unit tests] --> T2[T2 concurrency regression + offline e2e]
```

| Task | Owned files (pairwise disjoint) | Work |
|---|---|---|
| **T1** | `openagents/utils/workspace.py`, `tests/test_workspace.py` | Add `_GIT_MUTATION_LOCK`; use it to wrap the `.git` mutation sections in `prepare` / `ensure`; add unit tests asserting that both methods acquire the lock and that `commit_and_push`/`assert_delivered` do not |
| **T2** | `tests/test_workspace_concurrency.py`, `scripts/e2e-spec-0068-parallel-worktree-git-lock.sh` | Start N threads that call `prepare` concurrently against the same temporary git repository; assert zero `cannot lock ref` / `could not lock working tree` errors and successful creation of all worktrees; aggregate ruff + pytest in an offline e2e script |

### e2e script path

`scripts/e2e-spec-0068-parallel-worktree-git-lock.sh` (offline and deterministic: `ruff check` + `ruff format --check` + targeted `pytest`; collected by the PR e2e signpost). This is purely an internal concurrency correctness fix, with no product-facing frontend to navigate, so the evidence-gathering discipline of “purely internal → proportionate automated tests” calls for concurrency regression testing, with no browser e2e.

## Drawbacks

- **The coarse lock serializes worktree creation/cleanup across all workers**: at the theoretical peak, if K workers all need `prepare` at the same instant, they will queue for approximately “a few seconds × K.” This is negligible given that drafting currently takes minutes; however, if `prepare` becomes slower in the future (for example, `fetch` on a very large repository), this lock will become a bottleneck, at which point finer-grained locks (alternative B) or moving `fetch` out (alternative A) will be needed.
- **A single module-level lock hard-codes the assumption that “one process serves only one `.git`”**: if multiple `work_dir` values are ever processed concurrently within the same process (this does not happen now—fleet uses subprocesses), this lock will unnecessarily serialize `prepare` calls across different repositories. A per-work_dir lock dictionary would solve this, but it is currently YAGNI.

## Rationale and alternatives

**Selected: serialize the entire sequence with one coarse-grained git-mutation lock.** Reasons: Occam's razor (principle 1) + suggested direction 1 in the issue; one lock eliminates three classes of races at once (ref locks / worktree registry locks / prune-vs-add), with changes confined to two methods in one file, making correctness easy to review.

- **Alternative A — Move `fetch` / `prune` out into a single-threaded producer maintenance step** (the second half of suggested direction 1 in the issue): run `fetch origin <base>` once centrally per round, and move `prune` into a single-threaded maintenance step. This is semantically more “correct” (global operations should be single-threaded in the first place), but requires changing the `run_vigil` producer tick + changing the `prepare` signature (removing its internal `fetch`/`prune`) + handling the timing dependency of “whether the base ref has already been fetched when a worker creates a worktree” → changes span modules and have a broader scope. The coarse lock achieves **the same correctness** with changes to **one file**, so it is selected first; moving `prune` out is left for Future.
- **Alternative B — Fine-grained per-op locks / lock only the `packed-refs` section**: finer granularity and slightly higher concurrency, but this requires precisely identifying which kernel lock each git command touches, while the global side effects of `worktree prune` inherently require “mutual exclusion with add” → fine-grained locks make it easier to miss a case. Given that “`prepare` takes only a few seconds of the lifecycle,” the concurrency benefit is negligible and does not justify taking on the correctness risk of fine-grained locking.
- **Alternative C — Switch to the fleet subprocess model** (one process per worker): subprocesses provide State/cwd/crash isolation, but **still share the same main repository's `.git` filesystem, so git lock contention remains**—this does not solve P2 itself. Moreover, Spec-0065 has already established the thread model (cwd dependencies in the solving path have been audited: all git commands use the `cwd=` argument and do not rely on `os.chdir`, so they are thread-safe). Overturning that decision would be extremely costly and would not address the root cause, so this alternative is rejected.

## Prior art

- **git worktree is the standard isolation mechanism for parallel AI agents, but explicit locking is needed to prevent concurrent access**:
  - Augment Code — “Git Worktrees for Parallel AI Agent Execution” https://www.augmentcode.com/guides/git-worktrees-parallel-ai-agent-execution
  - sandcastle #427 — “Worktree locking to prevent concurrent agent access” https://github.com/mattpocock/sandcastle/issues/427
- **Concurrent git operations cause `cannot lock ref`**:
  - desktop/desktop #5438 https://github.com/desktop/desktop/issues/5438
  - Baeldung — “Fixing cannot lock ref” https://www.baeldung.com/ops/git-repo-structure-cannot-lock-ref
- **`worktree prune` removes registry entries for missing working trees from `$GIT_DIR/worktrees` (globally)**: official git documentation https://git-scm.com/docs/git-worktree
- **Internal precedent in this repository**: `RuntimeState._LOCK = threading.RLock()` (`openagents/runtime/state.py:58`)—the same pattern of “protect a shared mutable resource with an in-process lock and serialize read-modify-write”; this spec applies it to workspace's git mutation sections, with consistency yielding maintainability.

## Unresolved questions

- **This spec explicitly excludes all three P6 items** (see Motivation §P6): startup uniqueness validation for agent_id (open a separate spec if needed), thrashing of the last-place created_at (already covered by the existing claim debouncing mechanism; K>1 does not invalidate it), and human review throughput (reduce the operational parameter `--parallel`; not a code change).
- **This spec requires no new open questions**: whether the lock covers `ensure` is already settled in the design (it does; `ensure` also touches the shared `.git`).

## Future possibilities

- If `prepare` becomes slower or redundant `fetch` operations need to be reduced, move `fetch` / `prune` out into a single-threaded producer maintenance step (alternative A).
- If multiple repositories are processed concurrently within the same process in the future (this does not happen now), replace the single lock with a per-work_dir lock dictionary.
- If target git versions broadly support `worktree add --lock` (eliminating the race in “add, then lock”), the cleanup logic can be simplified further.
