---
number: "0065"
title: "Graph-driven parallel Vigil: an LLM arranges dependency edges (stored in GitHub native dependencies) + vigil level-triggered reconcile runs the frontier in parallel"
issue: 150
slug: issue-graph-parallel-vigil
summary: "Refactor Vigil from “scan everything each round and process one issue serially” into two planes. Admission plane (agentic): new issues pass through a three-state gate; once approved, they receive a ready label as an admission token, after which an LLM curator arranges their dependencies and writes the edges into GitHub native issue dependencies (blocked_by, GA in 2025-08). Execution plane (mechanical): level-triggered reconcile—the producer reads the current GitHub state once per subject on each tick, and a pure function returns one of four verdicts (IN_FLIGHT / TERMINAL / QUIET / ACTIONABLE); only ACTIONABLE subjects enter the queue. Each of K persistent workers atomically claims one subject and runs a reconcile branch table (new input from a human → unmet dependencies → no PR → conflicts → CI → e2e → review → merge; the order constitutes hard dependencies), advancing until blocked on something external. State is stored according to a “decisions vs. facts” distinction: **decisions we make go into labels** (ready admission / needs-human terminal state / review verdicts—verdicts are tied to commits, so the label name must contain the head sha: `review-approved:<sha7>`; otherwise, a push after review would allow unreviewed code to be merged); **facts owned by GitHub are read from native state** (CI / mergeable are already tied to a sha; copying them into labels creates a second source of truth that must be reconciled). When an agent cannot proceed, the **normal way to finish is for the agent itself to apply needs-human + leave a reason** (a first-class exit: immediately TERMINAL, polling stops, zero additional LLM calls). Change detection is deliberately omitted (edges can be lost; see the k8s level-triggered principle). The cost is that three kinds of failure **the agent itself cannot see** require guardrails: it does not realize it is spinning its wheels (it will not proactively call for a human, and the comment it leaves each round refreshes the timestamp and silences the watchdog) → stamp an attempt fingerprint when finishing (stored in a GitHub comment; **the stamp itself must not change fp**, so facts exclude comment id, or the guardrail destroys itself by becoming an infinite loop); state should advance but does not (the agent was never invoked at all) → watchdog (age calculated from GitHub timestamps, zero local memory). Claims are stored in a single SQLite table (queue + ownership + crash count, one UNIQUE row per subject), and proof of liveness rests on fcntl.flock: acquiring the lock ⇒ the kernel has reclaimed the holder’s lock ⇒ the holder is indeed dead, so there are no leases and no guesses about death; duplicate execution is structurally impossible, rather than merely unlikely. SQLite and flock together constrain deployment to a single machine; the replacement points for multiple machines are contained in 4 claim functions. Continuing the convergence arc of 0062–0064: all control flow for both planes is inlined into internal functions in recipes.vigil, with no new modules; the old serial implementation is deleted outright (git history is the rollback point; no dead-code copy is retained), and the number of recipes remains 3 (stages / backfill / vigil). New files: agents/curator.py (a zero-logic Template for arranging dependencies), agents/admitter.py (a **fail-closed human gate** for the admission conversation in the human state of the three-state gate: it judges “has the human actually agreed?”—putting the fail-open triager in this role would classify even an explicit human “don’t do this yet” as dispatchable, immediately degrading the human gate into an agent gate biased toward “yes”; this gate must also **recognize humans** (accepting statements only from OWNER/MEMBER/COLLABORATOR) and apply a try stamp before invoking the agent, or the gate is fail-closed while the key hangs outside the door, and every failed agent judgment burns another LLM call on every tick), utils/proc.py (per-thread PID claim buckets + kill_tree + flock fd inheritance registration, allowing hard timeouts to kill precisely the process tree started by this invocation), and an offline e2e script; utils/github.py gains read-side functions (pr_snapshot / check_snapshot / list_blocked_by / add_blocked_by / pr_for_branch)."
tasks:
  - id: T1
    title: "graph-curator agent (zero-logic Template: issue snapshots + existing edges as anchors → proposed blocked_by edges)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/curator.py
      - openagents/agents/admitter.py
      - tests/test_agent_curator.py
      - tests/test_agent_admitter.py
    scope: "Add agents.curator (the only new file in the agents/ layer, following the zero-logic Template convention): it consumes snapshots of ready open issues + current dependency edges (anchors), and uses engine.run_agent to produce a proposed set of blocked_by edges (each entry is {issue, blocked_by:[...], rationale}). Control flow does not belong in this layer; the agent only produces structured semantic judgments, without scheduling or persisting edges."
    acceptance: "pytest tests/test_agent_curator.py passes: the prompt incorporates placeholders for issue snapshots and existing edges as anchors; the output schema validates edges as a list at the top level (`engine._validate` only checks top-level key → type mappings, following the existing minimal schema convention); each edge’s `blocked_by` is validated **at the consumption site** (T2 `_proposed_edges`), while `rationale` is **a side note for human auditing, not an input to a machine gate** (nothing reads it, so by Occam’s razor no validation machinery is added for it); existing edges are included unchanged in the prompt as anchors. No real LLM is contacted."
  - id: T2
    title: "Rewrite vigil in place as level-triggered reconcile (three pure perception functions + SQLite claim queue + flock proof of liveness + branch table); repoint the CLI"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - openagents/recipes/stages.py
      - openagents/runtime/context.py
      - openagents/runtime/state.py
      - openagents/backends/claude_code.py
      - openagents/cli.py
      - openagents/utils/github.py
      - openagents/utils/proc.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil_queue.py
      - tests/test_recipe_vigil_admit.py
      - tests/conftest.py
      - tests/test_runtime_context.py
      - tests/test_github.py
      - tests/test_utils_github_vigil.py
      - tests/test_utils_proc.py
      - tests/test_backend_claude_code.py
      - tests/test_cli.py
      - scripts/e2e-spec-0065-graph-parallel-vigil.sh
    scope: "Rewrite recipes.vigil in place as the sole vigil recipe, with all control flow for both planes inlined into its internal `_` functions (no new graph/scheduler/intake modules). Five parts: ① Three pure perception functions—`_sense` (one GitHub read per subject → immutable `_Observed{facts, clock}`, the sole side effect) / `_classify` (pure function consuming facts + in_flight → four-valued `_Verdict`; **`_reconcile` always passes False for in_flight when calling it**, or every worker would conclude “someone is working on this” as soon as it claims work and then spin without doing anything) / `_fingerprint` (pure function consuming only facts → hash; its field set is always exactly the full facts field set, excluding both clock and in_flight; **facts exclude comment id**—applying an attempt stamp creates a new comment, and including its id in fp would immediately invalidate the stamp → infinite agent reinvocation); see the main text §3–§4. State is stored according to “decisions vs. facts”: decisions go into labels (`ready` / `needs-human` / `review-approved:<sha7>`, `review-changes-requested:<sha7>`—**verdicts are tied to commits, so the sha must be part of the label name**, or a push after review would allow unreviewed code to be merged), while facts are read from native state (CI / mergeable, never copied into labels). The agent has a **first-class `needs-human` exit** in every `_act` branch (it applies the label itself + leaves a reason → immediately TERMINAL); this contract must be included in each branch agent’s prompt. ② SQLite queue—`.openagents/vigil-queue.db`, a single `work_queue` table with one row per subject (the `subject` column is UNIQUE, combining deduplication + mutual exclusion for the same subject + idempotency), with no lease column; see §5. ③ Claim and reclamation—`_claim_next` uses `BEGIN IMMEDIATE` + `UPDATE…RETURNING` to atomically claim the head of the queue, acquires `flock(LOCK_EX|LOCK_NB)` on `claims/{subject}.lock` before COMMIT, and holds the fd until finishing; `_reclaim_dead` determines death by attempting to acquire the lock (no threshold parameters of any kind): acquisition means immediate reclamation, and EWOULDBLOCK means never reclaim; finishing must delete the row before close(fd); see §6/§6.1. ④ Producer/consumers—`run_vigil` starts K persistent workers + a tick loop on the main thread; `_producer_tick` = `_reclaim_dead` → `_intake` (three-state admission + invoke curator + persist blocked_by edges) → `_sense`/`_classify`/`_fingerprint` for each subject → route according to the four verdicts (`_enqueue` only if ACTIONABLE and no stamp with the same fp exists); after claiming work, `_worker_loop` runs the branch table through `_reconcile`, advancing until blocked; see §7/§9. ⑤ Guardrails—a hard timeout for each individual agent invocation in `_act` (kill child processes on timeout; the holder itself uses `_requeue_or_park` to release the row and lock, so claimed rows never become orphans) + an IN_FLIGHT watchdog (if too old, only `_park` to apply needs-human; never touch the row) + an `attempts` limit. Also absorb the old serial vigil capabilities (claim / three-state route / discover / merge pipeline / run_fleet) to achieve serial parity; K=1 reduces to serial execution. Delete the old serial implementation outright (git history is the rollback point), point cli.py to recipes.vigil, and keep the number of recipes at 3. Include an offline e2e script. Two additions during implementation (both are read-side utils for `_sense`, with no architectural change): add to utils/github.py `pr_snapshot` (including `head_pushed_at`—a PR that was “just pushed, with zero checks and zero comments” has no timestamp other than this one; without it, the watchdog never fires) / `check_snapshot` (including count; zero checks ≠ green) / `list_blocked_by` + `add_blocked_by` (native dependencies) / **`pr_for_branch` (find PRs regardless of state—`find_pr_by_branch` only finds open PRs, so a PR disappears as soon as it is merged, causing Vigil on the next round after merging to read the issue as “still has no PR” → branch ④ opens another PR and repeats the work)**; add utils/proc.py (**per-thread PID claim buckets** `track`/`publish`/`untrack` + `kill_tree` to kill the entire process tree, allowing the `_act` hard timeout to **precisely** kill the process tree started by this invocation—the backend reports its PID after starting Popen, and the timeout side kills by bucket; replacing this with “guess by diffing this process’s set of child processes” would misidentify concurrent gh/git processes or another worker’s agent, and killing the wrong process = the agent that actually hung is still pushing, introducing duplicate execution. The recipes layer must not call subprocess directly, per the Spec-0064 layering anchor)."
    acceptance: "pytest tests/test_recipe_vigil.py + tests/test_cli.py pass. Lifecycle: once uses `_drain_queue` to drain the queue / interval / errors in an individual round are isolated without killing the producer / an exception for one subject does not kill a worker / KeyboardInterrupt shuts down the pool through stop_event / K=1 serial and K=2 parallel execution reach the same final GitHub state / an empty frontier or a frontier entirely in flight → hang message. Queue: `_claim_next` claims atomically, exactly-once, without duplicate execution / `subject UNIQUE` + `INSERT OR IGNORE` makes enqueueing idempotent without duplicates / `_mark_done` is DELETE. Liveness detection (zero duplicate execution, this spec’s core assertion): holder process alive → `_reclaim_dead` attempts to acquire the lock and gets EWOULDBLOCK → the row remains untouched (even if claimed_at has exceeded the IN_FLIGHT alert threshold, only `_park` to apply needs-human, without reclaiming; assert that the row remains claimed and the worker is unchanged); holder process dead (after kill -9 of the child process, the kernel releases its flock) → `_reclaim_dead` acquires the lock → the row immediately returns to queued and can be claimed again (without waiting for any timeout); two fds in the same process are mutually exclusive on the same lock file (establishing that “flock is required, lockf is not acceptable”; this assertion would fail with lockf); `_mark_done` / `_requeue_or_park` delete the row before close(fd); `_reconcile` holds the lock throughout, without releasing it. Budget exhaustion: `_act` exceeds the shared total invocation-duration budget → kill child processes + raise → the holder itself calls `_requeue_or_park` (the row does not become an orphan); `_requeue_or_park` reaches `_MAX_ATTEMPTS` → needs-human. Perception: every branch of the four-valued `_classify`; `_classify(in_flight=True)` → IN_FLIGHT takes precedence over every other branch (including needs-human), while calls inside `_reconcile` **always use in_flight=False** (assertion: the holder of a claimed row does not immediately return when running `_reconcile`, so the worker does not spin without doing work); `_fingerprint` field set == the full set of `dataclasses.fields(_Facts)`, excluding clock, in_flight, and **comment id** (assertions: appending only one comment from us → fp unchanged; `_fingerprint` is equal before and after `_post_attempt_stamp`—this directly establishes that guardrail one does not destroy itself); an attempt stamp with the same fp exists → do not enqueue (prevent infinite agent reinvocation); fp changes → enqueue again; each QUIET reason’s `_watchdog` threshold is reached → `_park`. Completion: the agent applies `needs-human` in any `_act` branch → `_classify` returns TERMINAL on the next iteration (assert zero subsequent agent calls, no enqueueing, and no waiting for any threshold). Label semantics: the sha in `review-approved:<sha7>` == current head → branch ⑪ merge; after head advances, the sha in the same label ≠ current head → **fall back to branch ⑩ review-or-fix (assert never merge)**; bare `review-approved` (without a sha) is not recognized. Branch table: mergeable UNKNOWN must not read CI; CI considers only the current head_sha; three-state route; a rejected merge loops back. e2e: bash scripts/e2e-spec-0065-graph-parallel-vigil.sh is green—**repeatedly call run_vigil(once=True), one tick at a time** (a single pass cannot cover unlocking across rounds): supply A / B (blocked_by A) / C; the curator produces the A←B edge while C is independent; with K=2, one tick starts A and C concurrently, while B is blocked by QUIET(awaiting-blockers); after A’s PR is merged, B is ready on the next tick. Then assert the main path and two guardrails: “CI red → agent judges the upstream to be flaky → **applies needs-human itself + leaves a reason** → immediately TERMINAL, zero additional LLM calls” (main path); “CI red → agent believes it fixed the problem but makes zero changes, **does not apply needs-human** → apply fp stamp → do not invoke the agent again on the next tick → age exceeds threshold → needs-human” (guardrail one, proving that the agent proactively calling for a human **cannot replace it**); “CI never starts → QUIET(awaiting-ci) times out → needs-human” (guardrail two)."
---

# 0065 · Graph-Driven Parallel Vigil

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

### In one sentence

Vigil is currently a **serial loop with no concept of dependencies and no admission control**: each round performs three full scans in sequence, advancing only one issue at a time. This spec changes it to **have an LLM first map the dependencies between issues, then run them in parallel according to that graph**—closing both issue #137 (parallel solving) and issue #150 (cross-issue dependency scheduling).

### Split into two planes

| | Admission plane | Execution plane |
|---|---|---|
| **Nature** | Agentic (the LLM makes judgments) | Mechanical (pure functions make judgments) |
| **Responsibilities** | Which issues can start, and which issues block which others | What each issue / PR needs now, and who will do it |
| **Mechanism** | Review through a three-mode gate → apply the `ready` label → have the LLM curator arrange dependency edges → write them to GitHub's native `blocked_by` | level-triggered reconcile: read current state → make a four-way classification → enqueue → each of K workers claims one subject and advances it until blocked |
| **Where truth lives** | GitHub (edges, labels) | GitHub (pipeline state) + one SQLite queue table |

The **structure** of dependency edges is the product of LLM judgment, but their **storage** is a first-class GitHub feature (`blocked_by`, GA in 2025-08). This division of responsibility runs throughout the document: **the LLM produces only structure; facts and selections are mechanical.**

### How to read this document

This document has four levels; stop wherever suits your needs:

1. **You only want to know what changed** — The table above is enough.
2. **You want to know why it is designed this way** — Read Motivation (three defects + five constraints) and §1–§2 of the Guide.
3. **You want to understand the four core mechanisms** (level-triggered / four-way classification / branch table / three safeguards) — Read the entire Guide. This is the main path to understanding this spec.
4. **You are implementing it** — Read Reference (data structures, SQL, sequencing, walkthrough tables).

The core mechanism in one sentence: **keep no history; ask again on every tick, “What should happen now?”** (level-triggered, because edges can be lost). The normal way for an agent to stop when it cannot make progress is to **apply `needs-human` itself** (a first-class exit that stops polling immediately). The cost is that three failure modes **it cannot see itself** require safeguards. The memory for those three safeguards lives in **GitHub comments**, **GitHub timestamps**, and **the kernel**, respectively—only one queue table is added locally.

## Motivation

### Current behavior: how the old serial Vigil runs

Before the rewrite, `run_vigil` (now deleted; see git history) performed three **full scans** in sequence each round:

1. `discover_and_dispatch` — List all fresh issues, then triage and dispatch them one by one;
2. Poll comments — Iterate over all open PRs and reply whenever there is a new comment;
3. Advance merges — Iterate over all in-flight runs and advance each merge pipeline by one step.

After all three scans, `sleep(interval)`, then start another round.

### Four structural defects

**Defect one: serial, with no concurrency.** Issues are handled one after another within a round, leaving multicore / multi-agent parallelism entirely unused. This is precisely what issue #137, “vigil --parallel: solve multiple issues in parallel within the same repository (worker pool + shared .git lock + concurrent State writes),” aims to address.

**Defect two: no concept of dependencies.** Among 10 issues, there are often logical ordering constraints such as “B cannot start until A is done”—A defines an interface / data model that B then uses. The current implementation flattens them into an unordered set: it can neither express this order nor schedule accordingly. This is precisely what issue #150, “Cross-issue scheduling: agent semantically orders dependencies → blocked-by + DAG,” aims to address.

**Defect three: no admission control and no priority.** New issues enter the dispatch flow without review. Although three-mode triage exists, there is no explicit boundary of “reviewed → admitted → added to the pending set”; there is also no mechanism for deciding which issue goes first.

**Defect four (newly identified in this revision): the three scans are three manifestations of the same thing.** They look like three separate tasks, but they are actually three aspects of the same question—**“What should happen to this subject now?”** The evidence is `advance_merge` in the old serial vigil: it **already is** a reconcile branch table (terminal-state short circuit → conflicts → CI → e2e → review → merge, with an early return in each branch). All that is missing is two more branches at the top: “no PR yet → solve” and “latest comment is from a human → reply.”

Once this is clear, the “event type” (solve / advance / reply) is **redundant**: it is a copy of GitHub's current state, which must be reread on every tick anyway.

### Why #137 and #150 must ship together

They are two sides of the same architecture, with a strict dependency order:

> **To run in parallel, we must first know which issues can run in parallel**—only mutually independent issues can run simultaneously. And “what depends on what” is a **semantic judgment**: arranging the dependencies accurately requires understanding the issue content.

Implementing #137 without #150 means running in parallel without regard to order: B starts before A has defined the interface. Implementing #150 without #137 produces a graph with nothing to execute it in parallel.

### Five constraints

Every design decision below follows from these five constraints. Whenever you encounter “why not choose a simpler approach” later on, the answer is generally in this table.

| # | Constraint | Direct consequence |
|---|---|---|
| **C1** | Dependencies require **semantic judgment**; mechanical methods (file overlap analysis) can capture only “file-conflict ordering,” not “logical ordering” | The LLM must arrange edges → add `agents/curator.py` |
| **C2** | Dependency edges are **mutable truth jointly written by humans and machines** (humans set them manually in the UI; agents use the API), requiring concurrency / locking semantics | Store edges in GitHub's native dependencies, with no second local copy; the curator may only add edges **incrementally, constrained by existing anchors**, never overwrite the whole graph |
| **C3** | **GitHub cannot express “who has claimed this subject”**—REST does not support conditional requests for POST/PUT/PATCH/DELETE (no CAS), and label POST has append semantics (two concurrent claims both succeed without errors); RuntimeState uses whole-file JSON read-modify-write (which can lose updates, a risk explicitly listed in #137) | Claim atomicity must reside in **transactional storage** → SQLite `work_queue` table |
| **C4** | **Edges can be lost** (the process crashes between “detected” and “completed”), and missing one edge means a PR stalls permanently | Predicates must be **level-triggered** (no history, read only current state); change detection can only be an optimization, never the source of correctness |
| **C5** | The previous batch just consolidated recipes from 6 modules into 3; adding separate modules for admission / scheduling / the graph, while keeping old and new vigil implementations side by side indefinitely, would reverse that consolidation and add net dead code (violating Occam's razor) | **Inline all** control flow for both planes into deep functions in `recipes.vigil`; **rewrite in place** instead of creating `vigil2` |

### Why dependency edges belong in GitHub's native dependencies (expanding on C2)

In 2025-08, GitHub made issue `blocked_by` / `blocking` relationships first-class features: a full REST API + webhooks + a UI sidebar, with up to 50 relationships of each type, creatable with triage permissions. This eliminates both hacks in the original proposal for issue #150:

- The **custom naming convention** for “blocked-by labels”—native relationships have their own namespace, do not get confused with business labels, and require no string parsing;
- The **separate persistence** of a “local DAG topology”—native `GET .../blocked_by` directly returns the blocker list, with each blocker's `state` included. One call retrieves both the “edges” and “whether each blocker is closed,” requiring neither local persistence nor reconciliation.

## Guide-level explanation

### 0. Three terms

You only need to remember three terms as you read on:

- **subject** — The smallest scheduling unit, represented as a string: `issue:5` (an issue and the PR it eventually produces) or `pr:12` (a standalone PR with no associated issue). **One queue row per subject.**
- **verdict** — A four-way classification of a subject: `IN_FLIGHT` / `TERMINAL` / `QUIET` / `ACTIONABLE`. Only ACTIONABLE subjects are enqueued.
- **fp (fingerprint)** — A hash of GitHub's current state. Unchanged fp = zero progress.

### 1. The big picture: a subject's complete journey

```
  A new issue appears
      │
      │  ┌──────────── Admission plane (agentic; calls _intake within the producer tick) ────────────┐
      ▼  │                                                                                         │
   Three-mode gate ── agent → triager judges actionable ──┐                                      │
      │             ── human → ask the human in comments;├ Reviewed → apply ready label           │
      │                        admitter judges whether   │                                      │
      │                        they approved (fail-closed)│                                     │
      │             ── skip  → admit directly ───────────┘   (admission token, stored in GitHub)  │
      ▼                                                                                         │
   curator (LLM) reads “snapshot of all ready issues + existing edges (anchors)” → proposes blocked_by
      │                                                                                         │
      ▼  validate (acyclic + references real issues) → POST edges only for new nodes (leave existing edges intact)
      └─────────────────────────────────────────────────────────────────────────────────────────┘
      │
      ▼  ┌──────────── Execution plane (mechanical, level-triggered reconcile) ─────────────────┐
         │                                                                                       │
  Producer (main thread, every tick, for each subject)    Consumers (K persistent workers)         │
  ───────────────────────────────────────────────────    ────────────────────────────────         │
  observed = _sense(subject)   ← sole GitHub read          while not stop:                         │
  verdict  = _classify(observed.facts)  ← pure function      row = _claim_next()  ← atomic          │
  fp       = _fingerprint(observed.facts) ← pure function    if None: wait; continue                │
                                                           _reconcile(row.subject)               │
    IN_FLIGHT  → skip (queue contains a claimed row)        _mark_done / _requeue_or_park          │
    TERMINAL   → skip (merged/closed/needs-human)                                                 │
    QUIET      → do not enqueue; _watchdog(age > threshold) → _park                               │
    ACTIONABLE → Is there an attempt stamp on GitHub with the same fp?                            │
                   Yes → downgrade to QUIET(awaiting-effect)                                     │
                   No  → _enqueue(INSERT OR IGNORE) ──┐                                          │
                                                      ▼                                          │
                                         [SQLite work_queue table]                               │
                                         One row = one subject (UNIQUE)                          │
                                         priority + attempts                                     │
                                         Proof of liveness in claims/{subject}.lock(flock)        │
         └───────────────────────────────────────────────────────────────────────────────────────┘
```

The next four sections follow the order in which decisions are made: **§2 determines “how to sense,” §3 determines “who should be enqueued,” §4 determines “what to do after claiming,” and §5 adds “how it can die silently, and how to prevent that.”**

### 2. Layer One: Read Only the Current State; Do Not Detect Changes

A natural but mistaken intuition is to “remember the previous round’s GitHub state and call an agent when it changes.” This spec **does not do that**, because edges can be lost:

> Kubernetes’ architectural principles state it plainly—*"Functionality must be level-based, meaning the system must operate correctly given the desired state and the current/observed state, **regardless of how many intermediate state updates may have been missed**. Edge-triggered behavior must be just an optimization."* ([k8s design-proposals · principles.md](https://github.com/kubernetes/design-proposals-archive/blob/main/architecture/principles.md))

If the Vigil process crashes between “detecting that CI has turned green” and “actually merging,” that edge is lost forever—the PR will sit there, green, until the heat death of the universe. So the predicate **does not ask “has anything changed?”; it asks only “should we act now?”** It is recomputed every tick, allowing recovery whether one round or a hundred rounds are missed (constraint C4).

In code, all observation on the execution side is concentrated in three functions, which consume the same immutable structure:

```
observed = _sense(subject)                # The only side effect: read GitHub once
verdict  = _classify(observed.facts)      # Pure function → four-valued verdict
fp       = _fingerprint(observed.facts)   # Pure function → hash
```

`_Observed` has two halves, and **this division is a hard constraint**:

- **`facts`** — Every field read by the branch table (head_sha / merged / closed / labels / mergeable_state / CI on the current head / e2e evidence / review verdict / whether the latest comment is from a human / whether all dependencies are merged / pr_number). **Only this goes into `fp`.**
- **`clock`** — Timestamps (when the head was pushed, the latest check’s `started_at`, the latest comment time, the latest attempt timestamp). **Read only by the watchdog; never included in `fp`.**

**Invariant: the field set of `_fingerprint` ≡ the input field set of `_classify` ≡ `facts`.** Either direction can cause trouble:

- **One missing field → silent blindness.** A classic mistake: forgetting `mergeable_state` in `facts`—someone merges a PR into main, the base advances, and your PR now has conflicts: no new comments, no new commits, unchanged CI results → nothing is detected → the PR sits there rotting.
- **`clock` leaks into `fp` → guardrails fail.** A check run starting refreshes `started_at` → fp changes → the agent is called again, even though the branch table does not care about this field at all.

Having both consume the same structure prevents drift **structurally**.

### 3. Layer Two: Four-Valued Classification—What Should Be Enqueued

| verdict | Meaning | Producer action | Watchdog |
|---|---|---|---|
| **IN_FLIGHT** | The queue contains a `claimed` row for this subject—**my agent is working on it** | Skip | Alert only; do not reclaim (see §5.3) |
| **TERMINAL** | `merged` / `closed` / labeled `needs-human` | Skip | Ignore |
| **QUIET** | No work for me right now; wait for the state to change on its own | Do not enqueue | Evaluate age against the threshold for the reason |
| **ACTIONABLE** | It is time to act | `_enqueue` (`INSERT OR IGNORE`) | — |

**IN_FLIGHT must be the first check**; otherwise, the watchdog will treat an agent that is actively writing code (an 8-minute run is perfectly normal) as “no state change for 5 minutes” and apply `needs-human`.

**QUIET has four reasons whose natural durations differ by two orders of magnitude**, so thresholds must be configurable and set separately by reason:

| reason | What it is waiting for | Suggested default threshold | Mechanical diagnosis after timeout |
|---|---|---|---|
| `awaiting-blockers` | Upstream subjects to be merged | **Off by default** (upstream subjects have their own watchdogs; duplicate timing only causes false positives) | — |
| `awaiting-mergeability` | GitHub to asynchronously calculate the merge ref in the background | ~3 minutes | “GitHub is taking too long to determine mergeable” |
| `awaiting-ci` | CI runners (pending, or zero checks on the current head) | ~CI p95 × 3 (varies by repository; must be configurable) | “Head `abc123` was pushed 43 minutes ago and still has no checks: is the base something other than main? Are Actions disabled? Did no workflow match?” |
| `awaiting-effect` | The agent’s last action to take effect asynchronously (or perhaps it did nothing at all) | ~5 minutes | “The agent has acted, but `fp` has not changed—it cannot make progress; attach its own conclusion” |

**Err on the side of generous thresholds.** A threshold that is too short will mistakenly park normally running CI, which is worse than having no watchdog. And parking only applies a label + posts a diagnostic note—fully reversible; once a human removes the label, the system immediately resumes.

### 4. Layer Three: The Reconcile Branch Table—What to Do After Claiming Work

After a worker claims a subject, it runs this table. **This is the old serial vigil’s `advance_merge` with two branches added at the beginning and end** (defect four).

```
① merged / closed / needs-human ............... TERMINAL      ← A first-class exit for the agent; see below
② Latest comment is from a human (without our signature) ... ACTIONABLE: reply     ← Humans take priority over the pipeline
③ Dependencies are not all closed ............. QUIET(awaiting-blockers)
④ No PR yet ................................... ACTIONABLE: solve
⑤ mergeable_state = UNKNOWN / null ............ QUIET(awaiting-mergeability)
⑥ Conflicts (mergeable_state = dirty) ......... ACTIONABLE: rebase     ← Must precede CI
⑦ CI on the current head = pending / zero checks ... QUIET(awaiting-ci)
⑧ CI on the current head = failure ............ ACTIONABLE: fix-ci
⑨ e2e evidence missing / head_sha stale ....... ACTIONABLE: e2e
⑩ No review-* label / its sha ≠ current head /
  review-changes-requested .................... ACTIONABLE: review-or-fix
⑪ All green + review-approved:<sha7 of the current head> .. ACTIONABLE: merge
```

**Every branch has a second exit: `needs-human`.** If, in any branch, the agent concludes “I cannot resolve this / a human needs to decide”—CI is flaky upstream, the requirements themselves are ambiguous, the necessary changes exceed its authorization, or two consecutive attempts have failed to make progress—it **applies the `needs-human` label itself + leaves a comment explaining why**. On the next round, `_sense` reads it → ① returns TERMINAL → **polling stops there**.

This is **a first-class exit, not a fallback**: ordinary cases of “I cannot proceed” should be completed through this path. No extra LLM call is spent, no timeout is awaited, and the reason is written directly on the issue for a human to read. When a human removes the label, the predicate automatically becomes active again. The three guardrails in §5 cover only failure modes **the agent cannot see for itself** (it forgot to apply the label, judged incorrectly, failed to realize it was spinning its wheels, or crashed before it could apply the label)—the normal path never reaches them. **This contract must be written into the agent prompt for every branch** (`agents/*.py`); otherwise, the fallback becomes the main path.

**Four ordering requirements are correctness dependencies, not matters of style:**

- **① comes first** — Once `needs-human` is applied, no branch may take further action. It signals that a human is taking over.
- **② immediately follows** — A human saying “do not merge yet; I have a question” must be able to preempt a merge. Merging is irreversible.
- **⑤/⑥ precede ⑦** — `mergeable_state = UNKNOWN` does not mean “no conflicts”; it means GitHub has not finished calculating. And **a PR with conflicts cannot obtain a merge ref, so GitHub gives it no checks at all** (this repository has already encountered this). Without handling this first, ⑦ interprets “zero checks” as “CI is still running,” and `awaiting-ci` waits until it times out—the symptom is “CI is stuck,” while the cause is “there are conflicts.” This is exactly what the old serial vigil meant by “conflict must precede CI as a hard dependency,” and what its `if gates.is_mergeable_unknown(...): return None` implements.
- **⑦/⑧ look only at the current `head_sha`** — Not “this PR’s most recent CI.” Otherwise, immediately after the agent pushes a fix, GitHub still shows red for the old head → the predicate decides “a fix is needed” → another agent is dispatched to fix **code that has already been fixed**.

**The review verdicts in ⑩/⑪ are stored as labels, but the label names must include the head sha.** See §4.5.

**Advance until blocked, rather than advancing one step per tick.** The worker loops through `_sense → _classify → action` until the verdict is no longer ACTIONABLE (blocked on something external / the agent has applied needs-human itself / the terminal state has been reached), or until fp stops changing (it cannot make progress). Thus, an all-green PR is merged within a single claim instead of consuming three ticks.

**When a worker calls `_classify`, it always passes `False` for `in_flight`.** IN_FLIGHT means “**someone else’s** agent is working on it,” whereas the worker itself **is** the holder. If it truthfully passes True, the first thing it does after claiming work is conclude “someone is working on this” → immediately stop → **every worker spins without doing anything, and the system makes no progress**. `in_flight` is a producer-only concept.

### 4.5 Labels Record “Decisions”; Native Fields Record “Facts”

The information read by the branch table falls into two categories, stored in different places:

| | Who produces it | Where it is stored | Why |
|---|---|---|---|
| **Decisions** — `ready` (admission) / `needs-human` (human takeover) / review verdicts | Us (agents or humans) | **GitHub labels** | GitHub has no other place to express them; labels are also immediately visible in the UI and can be manually added or removed by humans (the entry point for recovery) |
| **Facts** — CI results / `mergeable_state` / `merged` / `blocked_by` | GitHub itself | **Read native fields** | They are **already tied to a sha and read in one operation**. Copying them into labels creates a second source of truth, and then we are responsible for keeping the two consistent—who updates the label when CI is rerun? One missed update causes a silent misclassification |

**When storing a review verdict as a label, the head sha must be included in the label name**: `review-approved:abc1234` / `review-changes-requested:abc1234`.

A verdict is not a permanently true property; it is **a judgment tied to a particular commit**. If the label is simply `review-approved`: the head is `abc1234` during review, and after review the agent pushes `def5678` to fix CI—**the label is still there**, so ⑪ sees “all green + reviewed” → merges directly. **The merged code has never been reviewed, and merging is irreversible.**

With the sha included, any head change makes the label fail to match the current head → the verdict is automatically invalidated → execution returns to ⑩ for another review. This is precisely the property GitHub’s native PR reviews (inherently tied to `commit_id`) provide for free. We reproduce it with labels, while also making it possible for “a human to see at a glance in the UI which commit has been reviewed.”

### 5. Layer Four: The Main Path Is for the Agent to Call for Human Help; Guardrails Cover Only Failure Modes It Cannot See

**The main path first.** When an agent cannot proceed, the normal way to finish is for it to **apply `needs-human` itself + leave a comment explaining why** (the second exit in the §4 branch table). Polling stops immediately, without burning additional LLM calls or waiting for any timeout, and the reason is written directly on the issue for people to see. **This path covers the vast majority of cases where the agent cannot proceed.**

**Guardrails cover failure modes the agent itself cannot see.** The remaining gaps have one thing in common: **in the logs, they look exactly like “everything is normal,”** and while the agent is in one of these states, **it does not know it is in that state**, so relying on it to call for help proactively will not work:

| Failure mode | Why the agent cannot call for human help itself | Guardrail | Where memory is stored | Does it need counting? |
|---|---|---|---|---|
| The agent **does not realize** it is spinning its wheels | It thinks it has done work | attempt fingerprint stamp (§5.1) | GitHub comments | No (one bit) |
| State should change but does not (CI never starts) | The agent was never invoked at all | Watchdog (§5.2) | GitHub timestamps | No |
| The owner process dies | The dead do not speak | Detect death by trying to acquire the flock (§5.3) | Kernel | No |
| The owner is alive but hung | It is stuck in a call that never returns | `_act` hard timeout + IN_FLIGHT alarm (§5.3) | In-process / `claimed_at` | No |
| The agent crashes repeatedly (without a trace) | Same as above, and leaves no trace | `attempts` limit (§5.4) | SQLite | **Yes** |

**The main path and all guardrails end the same way**: `needs-human` → TERMINAL → polling stops. When a human removes the label, the predicate automatically becomes active again. **This is self-healing that comes for free with level-triggered behavior.** The only difference is **who** applies the label—the agent itself (fast, precise, cheap, with a reason it wrote), or a guardrail (slow, able to provide only a mechanical diagnosis, but covering what the agent cannot see).

#### 5.1 Guardrail One: An attempt Stamp with the Same fp → Stop Invoking the Agent

**This guardrail is not intended for an agent that knows it is stuck**—that kind of agent will apply `needs-human` itself and never reach this point. It guards against an agent that **does not realize it is spinning its wheels**:

It reruns CI but fails to trigger it successfully; it changes an unrelated file and then ends up with an empty commit; it reads through the logs, posts a comment saying “I analyzed it; we just need to wait for CI to rerun,” and finishes, satisfied. **It does not think it is stuck, so it will not apply `needs-human`.** And the comment it leaves each round **refreshes GitHub’s last-activity timestamp, ensuring the watchdog (§5.2) never fires**.

The result: zero substantive progress on GitHub → the predicate still says ACTIONABLE on the next round → another agent is invoked → it performs the same analysis again and leaves another comment → **an infinite loop that looks extremely busy in the logs.** Nothing can stop it except mechanically comparing state.

An unchanged `fp` means “after I acted, every field the branch table cares about remained unchanged”—**that is, zero progress, regardless of what the agent says**. Any real progress necessarily changes `fp` (a push changes head_sha, a rerun changes CI, applying `review-*:<sha7>` after a review changes labels, an upstream merge changes deps_done). So unchanged fp = the agent has hit a wall (whether it knows it or not); invoking it again merely sends it into the same wall again.

At this exit, the worker leaves a comment with a signature:

```html
<!-- openagents:attempt fp=9f2a1c… -->
Conclusion for this round: `test_upload_timeout` is flaky (it failed randomly in 4 of the last 20 CI runs, all due to timeouts unrelated to this PR's changes).
No code changes were made.
```

When the producer sees a stamp with the same fp → it downgrades ACTIONABLE to `QUIET(awaiting-effect)` and does not enqueue it. **Present / absent, one bit, no counting needed**—invoking it again with the same evidence and the same prompt has an expected benefit close to zero.

> **The act of stamping must never change fp—otherwise this guardrail will destroy itself by turning into the very infinite loop it is meant to prevent.**
>
> The stamp is a **new comment**. If fp’s inputs include “the latest comment ID,” fp changes the instant the stamp is posted (9f2a → 7b31). On the next tick, the producer computes 7b31 and looks for a stamp for 7b31—there is none, only one for 9f2a → decides this is a “new situation” → enqueues it again → invokes the agent again → hits the wall again → leaves another new stamp (with another new fp) … **Repeatedly invoking the LLM forever is exactly what this guardrail is meant to prevent.**
>
> Therefore, `facts` **retains only the boolean `latest_comment_is_ours`, not the comment id** (§Reference·3). This loses no signal: branch ② only needs to know “whether the latest comment is from a human”; when a human comments again, `is_ours` flips from True back to False, and fp still changes.
>
> More generally, the rule for `fp` is “**any real progress necessarily changes fp**,” but **the converse does not hold**: some actions change fp without making progress. Before adding any new field to `facts`, first ask: **might the worker change it as part of finishing up?** If so, guardrail one fails immediately.

The reason `awaiting-effect` has a threshold (rather than parking immediately) **is not to give the model a second roll of the dice**; it is to absorb **the window before asynchronous effects become visible**: the agent has pushed, but the GitHub API still returns the old head (eventual consistency); the agent has triggered a CI rerun, but the check has not yet switched to pending. In these cases, fp may briefly “look unchanged.” Allow a few minutes of grace: real progress will take effect, fp will change, and the stamp will automatically become invalid; actually hitting a wall will lead to parking after the timeout.

#### 5.2 Guardrail Two: QUIET Exceeds Its Age Limit → Call for Human Help

Symptom: CI never starts (the workflow does not match / base is not main / Actions is disabled) → nothing invokes the agent → the PR silently rots, looking exactly like “normally waiting for CI” in the logs.

“Nothing has changed” can itself be a failure. And **determining “how long it has been stuck” does not require remembering the previous round**—every GitHub object carries its own timestamps:

```
age = now − max(head push time, latest check's started_at, latest comment time, latest attempt stamp time)
```

As soon as head changes, the timer automatically resets. **Zero local memory**—restarts, database loss, and switching machines have no effect. Threshold exceeded → `_park` (apply `needs-human` + post a mechanical diagnosis).

#### 5.3 Guardrail Three: Reclaiming Claims—Observe Death, Do Not Guess at It

When can someone else reclaim a `claimed` row?

**The intuitive answer is a lease** (an SQS-style visibility timeout: claimed for more than T seconds without finishing → consider it dead → return it to `queued`). This spec **does not use leases**, because a lease **infers death from silence**—it inherently cannot distinguish “the process died” from “the agent has spent 40 minutes writing a large feature”:

- Set the threshold too short → mistakenly judge a live worker to be dead → reclaim its row → a second agent starts running on the same PR = **duplicate execution**;
- Set the threshold too long (the 1 hour proposed in v0) → a subject that really crashed **silently stalls for an hour**.

Any timeout-based liveness check can only choose between these two kinds of error; **the probability of duplicate execution is always nonzero**.

**But in a single-machine topology (§12 already pins SQLite to a single machine), death does not need to be guessed—the kernel knows the exact answer.** When claiming, the worker acquires `fcntl.flock(LOCK_EX | LOCK_NB)` on `.openagents/claims/{subject}.lock` and holds it until it finishes. flock is attached to the **open file description**, and **the kernel automatically releases it when the process dies**—`kill -9`, OOM, segmentation faults, and a machine power failure followed by a reboot all count. The reclamation criterion thus becomes a single nonblocking attempt to acquire the lock:

| Attempt to acquire `flock` | What the kernel is saying | Action taken by `_reclaim_dead` |
|---|---|---|
| **Success** | The previous owner **is already gone** (the process is gone, and the kernel has reclaimed the lock) | **Immediately** return the row to `queued`—without waiting for any timeout |
| **`EWOULDBLOCK`** | The previous owner **is still alive** and holding the lock | **Never reclaim it**—regardless of how long it has been running |

Both outcomes are facts, not guesses. **Zero false death determinations ⇒ zero duplicate execution** (a live owner’s row is never taken away); **zero missed deaths ⇒ crash recovery changes from “wait up to an hour” to “immediately on the next tick.”**

**Why flock rather than PID probing.** PID probing (`os.kill(pid, 0)`) looks more straightforward, but PIDs can be **reused**—after a restart, a new process that happens to receive the old PID will be misread as “the previous owner is still alive,” leaving that subject stuck forever. Preventing this requires additionally storing the process creation time (`psutil.Process(pid).create_time()`), introducing a third-party dependency to plug a hole that flock does not have in the first place. `fcntl` is in the stdlib, and the kernel manages the lock’s lifetime.

**It must be flock, not `fcntl.lockf` (POSIX `F_SETLK`).** The latter’s locks are **per-process**: locks acquired through two fds for the same file within one process **do not exclude each other**. This spec uses “one process with K worker threads”; using `lockf` would cause mutual exclusion within the same process to **silently fail**. flock locks are attached to the open file description, so separate `open()` calls within the same process still conflict—exactly what we need.

**“Alive but hung” is a separate matter, handled by a separate gate.** flock answers only the question of **existence** (whether the process is still there). If the process is alive but the agent is hung (stuck in a network call with no timeout), the lock remains held → the subject stalls. This is a hang problem, not a duplicate-execution problem, and **it cannot be solved by reclamation** (reclaiming a live owner’s row is, by definition, duplicate execution). Two measures:

1. **`_act` imposes a hard wall-clock budget on each agent invocation** (sharing `OPENAGENTS_CLAUDE_MAX_WALL` with Claude, default 3600 seconds; see 0046; exhausting it does not imply a hang)—on timeout, it kills the agent subprocess and raises an exception, and the worker **itself** follows `_requeue_or_park` to release the row and lock. A `claimed` row is always released by its owner and never becomes orphaned.
2. **IN_FLIGHT watchdog** (`_INFLIGHT_ALARM_SECONDS`, default 2 hours)—the `claimed_at` of a `claimed` row exceeds the age limit → `_park` (apply `needs-human` + diagnosis). Note that it **only raises an alarm and never reclaims the row**.

This asymmetry—**only a dead owner’s row can be reclaimed; a live owner’s row can only be handled by the owner itself or a human**—is the final pillar of zero duplicate execution. Together, these three measures mean: **duplicate execution is structurally zero, not “very unlikely once the thresholds are tuned.”**

#### 5.4 Guardrail Four (the Only One That Requires Counting): `attempts`

The agent crashes / is killed → it **has not left a stamp** (it did not finish) → zero trace on GitHub, and no timestamps refreshed → fp cannot detect it, nor can age → the kernel releases flock → `_reclaim_dead` returns the row to `queued` → it is claimed again → crashes again → infinite repeated claims, with nothing visible outside the logs.

**This is the only failure mode that must be counted**, covered by the queue row’s `attempts` column (+1 when claimed; park upon reaching `_MAX_ATTEMPTS`).

### 6. Storage Responsibilities: Each Stores Its Own Part, with No Overlap or Reconciliation

| Storage | What it stores | What happens if it is lost |
|---|---|---|
| **GitHub labels** (**decisions** we make) | Admission (`ready`) + terminal state (`needs-human`) + review verdict (`review-approved:<sha7>`) | Cannot be lost—it is the source of truth. Humans can edit it manually, providing the entry point for self-healing |
| **GitHub native fields** (its own **facts**) | Dependency structure (`blocked_by`) + pipeline state (checks / mergeable / merged) + e2e evidence comments + **states in which action has already been taken** (attempt stamps) | Cannot be lost—it is the source of truth |
| **SQLite `work_queue`** | Queue + claim ownership + crash count | Harmless: rebuilt from GitHub in one tick (`queued` rows); `claimed` rows are reclaimed by `_reclaim_dead` using flock |
| **`claims/{subject}.lock` (flock)** | Proof that the owner is alive (held by the kernel, automatically released when the process dies) | Harmless: the file itself has no state; the lock exists only while the process is alive |

**The boundary between decisions and facts** (§4.5): CI results / `mergeable_state` are facts maintained by GitHub itself and tied to a sha; **they are not copied into labels**—copying them would create a second source of truth, followed by the responsibility to keep the two from conflicting. A review verdict, however, is a decision we make, and GitHub has nowhere else to express it, so it goes into a label, and **the head sha must be included in the label name**; otherwise, a head change would not invalidate the verdict → code that nobody has reviewed gets merged.

**The queue is not a second source of truth for GitHub.** It stores only three things GitHub cannot express: who atomically claimed this subject (C3: no CAS; label POST has append semantics), how many times it was claimed without finishing (crashes leave zero trace on GitHub), and the ordering established at claim time.

### 7. The unit of concurrency is the subject

- **Serial within a subject** —— The `subject` column is UNIQUE: a subject has at most one row in the queue; after it is claimed, `INSERT OR IGNORE` is a no-op. **There is never more than one agent on the same PR.**
- **Parallel across subjects** —— Limited by the bounded pool of K workers.
- **Serial execution = the degenerate case K=1** —— `oa vigil` defaults to K=1, with behavior equivalent to today's; `oa vigil --parallel K` expands the pool to K.

### 8. User perspective and analogies

People participate in only two places: confirming through a comment conversation when an issue is triaged into the `human` state; or manually setting / changing dependencies directly in the GitHub UI (agents respect these as anchors and do not overwrite them). Everything else runs unattended—until a guardrail raises `needs-human`.

The execution side resembles `make -j K`: the dependency graph determines whether work can start, and `-j K` determines how many jobs run at once. A closer comparison is a **Kubernetes controller**: `reconcile → workqueue → N workers`. This is not a structure we impose from outside; it is the natural shape of systems like this.

## Reference-level explanation

### 1. Storage responsibilities (expanding on Guide §6)

| Storage | Role | Writers |
|---|---|---|
| **GitHub** | Dependency structure + decisions (labels: admission / terminal states / review verdicts) + facts (checks / mergeable, read native fields without copying) + attempt stamps | Admission side (apply `ready`, POST edges); workers (advance the pipeline, apply `review-*:<sha7>`, apply `needs-human` when no way forward remains, stamp attempts); producer (`_park` applies `needs-human` on guardrail timeout); people (manually set edges in the UI, remove labels) |
| **SQLite `work_queue`** (`work_dir/.openagents/vigil-queue.db`) | Queue + claim ownership + crash counts | Producer (`_enqueue` / `_reclaim_dead`) + each worker (`_claim_next` / `_mark_done` / `_requeue_or_park`) |

Three implications:

- **Facts** (whether a PR is merged, whether CI is green) are read mechanically from GitHub and **never enter** the LLM;
- **Selection** (what runs next) is a mechanical claim using SQLite `ORDER BY priority`, **not** an LLM decision;
- Only **structure** (what depends on what) is an LLM judgment.

**Why the LLM cannot be the router.** Every predicate in the branch table is a boolean / enum read from GitHub—having the LLM evaluate it trades certainty for uncertainty with zero benefit, while introducing a fatal failure mode: hallucinating “all green → merge” on a red PR. **Merging is irreversible.**

### 2. Admission side: from a new issue to a GitHub edge

For each “new issue without a `ready` label” (possibly collected into a batch), `_intake` (called within the producer tick) performs the following:

1. **Three-state gate** —— `skip` admits directly; `agent` dispatches `triager` to judge whether it is actionable and admits it if it passes; `human` **confirms with a person through a conversation in issue comments** (`_ask_human`), a conversation spanning ticks, with all three states derived from GitHub's current state (zero local memory):

   - **Never asked** (no `_ADMIT_ASK_MARK` in the comment stream) → post a **signed** question comment, **zero LLM**.
   - **Asked, but no maintainer reply yet** → do nothing, **zero LLM**. (The admission side scans it again every tick—it has neither `ready` nor `needs-human`—so calling an agent on every round would turn an issue waiting for a human reply into a money-printing machine billed per tick.)
   - **A maintainer has replied** → first apply a **try stamp** (`_ADMIT_TRY_MARK` + the comment id of the person's reply; **this step is the admission ticket for the LLM**) → then dispatch **`admitter`** (`stages.admit`) to read the conversation and judge “has the person agreed?” → record the verdict **as a signed comment** (if a `gh` hiccup prevents the label from being applied, the next tick reads this stamp and retries directly, with zero LLM) → apply `ready` if they agreed; otherwise apply `needs-human` + include the reason.
   - **The previous evaluation crashed** (a try stamp exists, but no verdict stamp) → hand off to a human with **zero LLM**.

   **Judging “has the person agreed?” must use a dedicated fail-CLOSED agent; it cannot reuse triager**: triager answers a different question (whether the issue body is internally consistent), and its discipline is fail-open (dispatch work when uncertain)—a person explicitly saying “don't do this yet; I haven't thought this direction through” does not fall into any of its five categories of contradictions, so it will still judge `actionable=true`. This **human gate** then immediately degenerates into an agent gate biased toward “yes,” **dispatching work despite an explicit human veto**. The admitter's default is the opposite: incomprehensible replies, off-topic answers, bystander interjections, uncertainty—all count as no agreement (a false negative merely means waiting another round; a false positive irreversibly starts work against the person's wishes).

   **The criteria for “a person has replied” are hard-coded, not delegated to an agent** (`_human_replies`): only comments posted **after** our question, **without our signature**, **and by a maintainer** (`authorAssociation` ∈ OWNER/MEMBER/COLLABORATOR) qualify. All three conditions are required—without the signature condition, our own park reasons / try stamps / verdict stamps would be read as human replies, and the agent would deliberate over its own writing (so `_park_needs_human` must also sign its comments); without the maintainer condition, this gate **recognizes no authority boundary**: any bystander in a public repository could reply “yes, go ahead” and dispatch the work, and the admitter's prompt cannot stop it—it sees only a piece of **externally writable** text and has no idea whom to listen to. The conversation fed to admitter (`_dialogue`) likewise contains only “our question + maintainer replies”: bystander comments do not enter the prompt; otherwise, a fail-closed gate would be exposed to prompt injection.

   **Buy the ticket before spending money**: an exception from `stages.admit` (agent output violating the contract / `_ActTimeout` / backend 429) propagates out of `_ask_human` entirely. At that point, the issue has neither `ready` nor `needs-human` → the next tick scans it again → **one LLM call burns money every tick, forever** (and a person can reliably trigger this simply by replying “don't output JSON when replying to me”). The try stamp must therefore **land on GitHub before calling the agent**: one human reply buys at most **one** agent invocation. If the stamp cannot be applied (`gh` is down), raise immediately, with **zero LLM**, and retry unchanged on the next tick. Both stamps carry **the comment id of that human comment**, not a timestamp: GitHub's `createdAt` has only **second** precision, so timestamps cannot distinguish two statements changing the person's mind within the same second. The old verdict would swallow the new statement → fail-closed would degrade from “wait for one more reply” to “permanent rejection.”

   **Do not apply `needs-human` and wait for someone to remove the label**—that is a dead end: `needs-human` is TERMINAL in `_classify`, and `_intake` also skips issues carrying it; once it is applied, nobody reads any subsequent human reply.
2. **Apply the `ready` label** —— The admission token lands on GitHub.
3. **Call curator (T1)** —— Feed it “a snapshot of all currently `ready` open issues + existing dependency edges (anchors),” and receive a proposed set of `blocked_by` edges (each `{issue, blocked_by: [...], rationale}`). Curator is a zero-logic Template (the convention in the agents/ layer): it produces only structured semantic judgments, performs no scheduling, and writes no edges.
4. **validate** —— Locally rebuild an in-memory DAG using the proposed edges, checking that it is acyclic + all `blocked_by` references point to real issues.
5. **Write edges** —— Only after validate passes, `POST blocked_by` for **new nodes**; existing edges (including those manually set by people in the UI) remain fixed as anchors (constraint C2). If validate fails, write no edges + apply `needs-human` to the issue.

**REST endpoints used** ([GitHub Docs](https://docs.github.com/en/rest/issues/issue-dependencies)):

- `GET /repos/{o}/{r}/issues/{n}/dependencies/blocked_by` —— List what blocks n; returns a list of issue objects, including each blocker's `state`.
- `POST /repos/{o}/{r}/issues/{n}/dependencies/blocked_by` —— Add a dependency (body: `issue_id`).
- `DELETE /repos/{o}/{r}/issues/{n}/dependencies/blocked_by/{issue_id}` —— Delete one.
- `GET /repos/{o}/{r}/issues/{n}/dependencies/blocking` —— List what n blocks.

Because the `blocked_by` response includes each blocker's `state`, one call retrieves both “edges” and “whether the blockers are closed,” **with no second round of queries needed**.

### 3. `_sense`: the sole GitHub read, producing an immutable `_Observed`

```
_Observed
├── facts   ← _classify reads this; _fingerprint hashes it. Both must use the same set of fields.
│   ├── subject            "issue:5" | "pr:12"
│   ├── pr_number          int | None          (None when the issue has no PR yet → branch ④ solve)
│   ├── head_sha           str  | None
│   ├── merged / closed    bool                (GitHub facts → branch ①)
│   ├── labels             frozenset           (our decisions: needs-human → branch ①; ready → admission;
│   │                                            review-approved:<sha7> / review-changes-requested:<sha7>
│   │                                            → branches ⑩⑪)
│   ├── deps_done          bool                (whether all counterparts in blocked_by are closed → branch ③)
│   ├── mergeable_state    "clean"|"dirty"|"unknown"|None   ← GitHub fact, read natively (branches ⑤⑥)
│   ├── ci                 "success"|"failure"|"pending"|"none"  ← GitHub fact, for the current head_sha (⑦⑧)
│   ├── e2e_head_sha       str | None          (provenance stamp on the e2e evidence comment; ≠ head_sha means stale → branch ⑨)
│   ├── review_state       "APPROVED"|"CHANGES_REQUESTED"|None   ← parsed from review-* labels (⑩⑪)
│   ├── review_commit_id   str | None          (the commit bound to the verdict, i.e. the sha7 segment in the label name;
│   │                                            ≠ current head_sha means the verdict is stale → return to branch ⑩ for re-review)
│   └── latest_comment_is_ours  bool           (whether the latest comment carries our signature → branch ②)
│                                              ★ Only this boolean; **do not store the comment id**—see below
└── clock   ← Only _watchdog reads this. Never enters the fingerprint.
    └── last_progress_at   max(head push time, latest check.started_at,
                               latest comment time, latest attempt stamp time)
```

**`latest_comment` retains only a boolean, not an id**; this is the lifeline of guardrail one. If the id enters fp, applying an attempt stamp (a new comment) changes fp → the stamp is immediately invalidated → the agent is called again indefinitely (see the quoted block in Guide §5.1 for the full derivation). Dropping the id loses no signal: branch ② needs only “was the latest comment posted by a person?”

**`labels` contains “decisions we made,” not GitHub facts.** `ci` / `mergeable_state` / `merged` are always read from native fields and **never copied into labels**—they are already bound to a sha and retrieved in one read; copying them creates a second source of truth (who updates the label when CI is rerun?). See Guide §4.5.

**`deps_done` must be in `facts`**; this is the easiest requirement to miss. Issue A is `blocked_by` issue B, and B's PR merges—not a single byte of A's own PR / CI / comments changes. Without `deps_done` in `facts`, A's fp stays unchanged, A is never reconsidered, and **the entire dependency graph gets stuck at the first node**, even though parallelism across the issue graph is this spec's core selling point.

**Two pitfalls that must be hard-coded into `_sense`** (see the branch-table ordering in Guide §4): `ci` is taken only from the current `head_sha`; `unknown` / `None` in `mergeable_state` means “computation not finished yet,” not “no conflicts.”

**All these reads already exist in the old serial Vigil**, but are scattered across `_route_triage` / `advance_merge` / `_reply_one_pr`, each reading independently. `_sense` is not a new feature; it puts them together in one place—giving the invariants a place to attach.

### 4. `_classify` / `_fingerprint` / `_watchdog`

```
_classify(facts, in_flight) → _Verdict:
      IN_FLIGHT                              ← in_flight (before everything else)
    | TERMINAL                               ← merged / closed / needs-human
    | QUIET(reason)                          ← awaiting-blockers | -mergeability | -ci | -effect
    | ACTIONABLE(action)                     ← reply|solve|rebase|fix-ci|e2e|review-or-fix|merge

_fingerprint(facts) → str                    ← hash all fields of facts; neither clock nor in_flight is included
_watchdog(verdict, clock, thresholds, now) → bool   ← QUIET and age > the threshold for that reason → should park
```

`in_flight` (“the queue contains a `claimed` row for this subject”) is the only non-GitHub input, supplied by the caller—so, strictly speaking, the invariant is “**the field set of `_fingerprint` ≡ all fields of `facts` ≡ the set of GitHub fields read by the branch table**,” while `in_flight` and `clock` are both explicitly **excluded from fp**.

**The two callers pass different values; this is required for correctness:**

- The **producer** passes the actual value (checking whether the queue contains a claimed row for this subject). IN_FLIGHT must be the first check; otherwise, the watchdog will mistake an agent that is writing code (an 8-minute run is perfectly normal) for a case where “the state has not changed for 5 minutes” and incorrectly mark it `needs-human`.
- The **worker (`_reconcile`) always passes `False`.** It **is** the in-flight holder. If it passed the actual value, True, the first thing it would do after claiming work would be to decide “someone is working on this; I should leave it alone” → finish immediately → **every worker spins without doing any work, and the entire system stands still.** IN_FLIGHT means “**someone else** is working on it,” a concept exclusive to the producer.

For each subject, the producer does the following:

```
ACTIONABLE and GitHub has an attempt stamp with the same fp
    → downgrade to QUIET(awaiting-effect)        ← guardrail one: do not hit the same wall again
ACTIONABLE (no stamp with the same fp)  → _enqueue
QUIET                     → do not enqueue; if _watchdog reports a timeout → _park (needs-human + mechanical diagnostics)
IN_FLIGHT / TERMINAL      → skip
```

### 5. Table Schema: One Row = One Subject

```sql
CREATE TABLE IF NOT EXISTS work_queue (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    subject          TEXT    NOT NULL UNIQUE,        -- "issue:5" | "pr:12"
                                                     -- deduplication + same-subject mutual exclusion + idempotent enqueueing, all three in one
    priority         INTEGER NOT NULL DEFAULT 0,     -- higher values first (ordering at claim time)
    enqueued_at      TEXT    NOT NULL,               -- ISO; FIFO tie-break among equal priorities
    status           TEXT    NOT NULL DEFAULT 'queued',   -- queued | claimed
    worker           TEXT,                           -- identifier of the claimant (for observability)
    worker_pid       INTEGER,                        -- holder's process ID—for human diagnosis with ps only, not for deciding liveness
    claimed_at       TEXT,                           -- claim time; feeds only IN_FLIGHT watchdog alerts, not reclamation decisions
    attempts         INTEGER NOT NULL DEFAULT 0      -- number of claims that did not finish; exceeding _MAX_ATTEMPTS → park
);
CREATE INDEX IF NOT EXISTS ix_work_queue_claimable
    ON work_queue (status, priority DESC, enqueued_at ASC);
```

**There is no lease column**—reclamation is determined by flock, not a timeout (Guide §5.3).

**`subject UNIQUE` supports three properties on its own**:

| Property | How it is achieved |
|---|---|
| **Idempotent enqueueing** | The producer unconditionally runs `INSERT OR IGNORE` on every tick—no change detection; duplicate enqueueing is a no-op |
| **Same-subject serialization** | At most one row per subject; inserting again after it has been claimed is still a no-op → there is always only one agent working on the same PR |
| **Deduplication** | As above; no `dedup_key` is needed |

**`subject` is TEXT, not INTEGER**: `issue INTEGER NOT NULL` cannot represent a standalone PR with no associated issue (the old serial vigil explicitly supported an “open PR iteration source” with `run.issue_number is None`; see git history).

**`_mark_done` must DELETE, not set `status='done'`**: `subject` has a UNIQUE constraint, so retaining a done row would prevent that subject from ever being enqueued again → PR deadlock. The truth about completion lives in GitHub; queue rows are merely a scheduling cache.

There is no longer an in-process `_tracked` set + lock: deduplication, ordering, claiming, and same-subject serialization all move into the DB, leaving only a `threading.Event` (`stop_event`) to signal pool shutdown. Each worker / producer opens its own thread-private SQLite connection (`_connect`: `isolation_level=None` + manual `BEGIN IMMEDIATE` for transaction control, `PRAGMA busy_timeout`, WAL, `row_factory=sqlite3.Row`)—sqlite3 connections are not shared across threads by default.

### 6. `_claim_next`: Atomic Claim + Acquisition of Proof of Liveness

```sql
BEGIN IMMEDIATE;
UPDATE work_queue
   SET status='claimed', worker=?, worker_pid=?, claimed_at=?, attempts=attempts+1
 WHERE id = (SELECT id FROM work_queue
              WHERE status='queued'
              ORDER BY priority DESC, enqueued_at ASC
              LIMIT 1)
 RETURNING *;                                   -- SQLite 3.35+
-- After obtaining the row and before COMMIT: flock(claims/{subject}.lock, LOCK_EX|LOCK_NB)
--   Acquired → COMMIT; this worker holds the fd until it finishes (proof of liveness)
--   Not acquired → ROLLBACK (defensive: a queued row should not have a live holder), skip this row
COMMIT;
```

| Clause | Property it provides | What happens without it |
|---|---|---|
| `WHERE status='queued'` + `BEGIN IMMEDIATE` | **exactly-once claiming** | When two workers concurrently claim the same row, serialization ensures that the second `UPDATE` matches nothing and returns an empty result. This is precisely the duplicate execution that C3 must eliminate |
| `ORDER BY priority DESC, enqueued_at ASC` | **Ordering at claim time** | Priority is frozen at enqueue time, distorting aging for rows that have waited a long time |
| **flock and the row share the same lifetime** | **Correct reclamation** | Without it, reclamation can only guess at death using leases → incorrectly kill a live worker → duplicate execution |

**There is no `NOT EXISTS` subquery**—same-subject mutual exclusion is already structurally guaranteed at enqueue time by `subject UNIQUE` (two rows for one subject cannot exist in the first place); checking again at claim time is purely redundant.

`attempts` **increments by 1 at claim time** (not at failure time), so even work that crashes and is repeatedly reclaimed by `_reclaim_dead` will be parked at `_MAX_ATTEMPTS`, rather than occupying a slot indefinitely.

**Finishing must delete the row first, then release the lock** (the same applies to `_mark_done` / `_requeue_or_park`). Reversing the order (releasing the lock before deleting the row) opens a window: the lock has been released, but the row is still marked `claimed` → another process's `_reclaim_dead` acquires the lock, decides “dead,” and resets the row to `queued` → it is claimed again → **duplicate execution**. Deleting the row before releasing the lock means that, in the worst case, a crash occurs between the two steps—the row is already deleted, and the kernel releases the lock, leaving a clean state.

### 6.1 `_reclaim_dead`: Determine Death by flock, Not by Timeout

```
for row in SELECT * FROM work_queue WHERE status='claimed':
    fd = open(claims/{row.subject}.lock)
    try flock(fd, LOCK_EX | LOCK_NB)
    ├─ Success     → the holder process is gone (the kernel has reclaimed its lock)
    │               UPDATE … SET status='queued', worker=NULL, worker_pid=NULL, claimed_at=NULL
    │               release(fd)        ← release immediately; this function does not execute work
    └─ EWOULDBLOCK → the holder is still alive → leave unchanged (regardless of how long it has been running)
```

**This is the only place in the entire concurrency model that “determines whether someone else is still alive,” and it makes no determination itself—it asks the kernel.** `_reclaim_dead` has no threshold parameters, so there are no knobs that can be tuned incorrectly.

**A mandatory implementation constraint**: the worker's lock-holding fd **must not** be `close()`d during `_reconcile`. A flock lock is attached to an open file description, and **closing any fd pointing to that description releases the lock**—one careless `with open(...)` can discard the proof of liveness prematurely, allowing someone else to reclaim the worker's row → duplicate execution, silently. The fd's lifetime must be explicitly tied to the interval from “claim → finish” (`_claim_next` returns the fd; `_mark_done` / `_requeue_or_park` are responsible for close).

### 7. `_reconcile`: After a Worker Claims a Subject

```
_reconcile(subject):
    last_fp = None
    while True:
        observed = _sense(subject)
        fp       = _fingerprint(observed.facts)
        verdict  = _classify(observed.facts, in_flight=False)   # ★ I am the in-flight holder

        if verdict is not ACTIONABLE:          # Blocked externally (QUIET) / reached an endpoint (TERMINAL, including
            return                             #   needs-human set by the agent itself) → return the slot

        if fp == last_fp:                      # Fallback: I acted, but the state did not change → zero progress (the agent did not notice)
            _post_attempt_stamp(subject, fp, agent_conclusion)   # Guardrail one: stamp it so it will not be invoked again
            return

        last_fp = fp
        _act(observed)                         # Dispatch to an agent / mechanical action according to verdict.action
```

**`in_flight=False` is not a typo; it is required for correctness**—see §4. Passing True would make every worker decide “someone is working on this” as soon as it claims work, then finish immediately.

**The main path is in `_act`, not in `fp == last_fp`.** The agent determines that it cannot proceed → sets `needs-human` itself + leaves a reason → `_sense` reads it on the next iteration → TERMINAL → the first `return` above. The `fp == last_fp` branch is a **fallback**, specifically guarding against an agent **failing to realize that it is spinning without progress** (see Guide §5.1).

**Inside `_act`: mechanical routing + agent work.** Routing (which branch to take) is always mechanical; agents appear only within the concrete actions (writing code, fixing CI, reviewing, replying). **Every branch has a second exit, `needs-human`, and it is a first-class exit**—it must be included in each branch's agent prompt (`agents/*.py`). When the `review-or-fix` branch issues a verdict, it sets `review-approved:<sha7>` / `review-changes-requested:<sha7>`, using the sha of **the head to which that verdict applies** (see §4.5).

The branches of `_act` reuse the vertical-slice / merge segments in `recipes.stages` and `runtime.messages`; deterministic hard gates (head advancement / evidence provenance stamps / round_cap) always remain in force and cannot be disabled by `skip`.

### 8. task State Machine

```
                    _enqueue (INSERT OR IGNORE; subject UNIQUE → idempotent)
                              │
                              ▼
   ┌──────────────────────► queued ◄───────────────────────┐
   │  _reclaim_dead             │                          │  _requeue_or_park
   │  (flock can be acquired ⇒  │ _claim_next              │  (attempts < limit; delete row before releasing lock)
   │   kernel proves holder    │ (BEGIN IMMEDIATE atomic  │
   │   is dead → reclaim)       ▼  claim + hold flock + attempts+1)
   └────────────────────────claimed ───────────────────────┘
                              │  │
       _mark_done(delete row) │  │ _requeue_or_park (attempts ≥ limit)
                              ▼  ▼
                       [delete row]   [delete row + label subject needs-human]
```

Two persistent states (`queued` / `claimed`); delete the row on completion (see §5: keeping it would cause a deadlock because of UNIQUE).

### 9. Loop Timing

```
Producer _producer_tick (main thread, every interval)     worker _worker_loop (K persistent threads)
───────────────────────────────────────────────────     ─────────────────────────────────────────
 0. _reclaim_dead      flock acquired ⇒ claimed→queued     while not stop_event.is_set():
 1. _intake            Three-state triage of new issues     row, fd = _claim_next()  # Atomic claim + hold lock
                       → apply ready → curator arranges     if row is None:
                       edges → validate → POST                stop_event.wait(POLL); continue
 2. for subject in _subjects():                             try:
       observed = _sense(subject)                            _reconcile(row['subject'])  # Advance until blocked
       verdict  = _classify(observed.facts)                   _mark_done(row['id'], fd)
       fp       = _fingerprint(observed.facts)              except Exception:   # Includes _act hard timeout
       IN_FLIGHT → claimed_at too old? _park(alert only)      _requeue_or_park(row['id'], subject, fd)
       TERMINAL  → skip                                    # Both exits: delete row first, then close(fd) to release lock
       QUIET → _watchdog timed out? _park : skip            # Immediately return to the top to claim again; no batch wait
       ACTIONABLE → stamp with same fp? downgrade to QUIET : _enqueue
 3. Number enqueued this tick == 0 → _hang (distinguish "empty frontier" / "all in flight" / "N waiting for CI")
 4. once? _drain_queue (poll until no queued/claimed rows remain): sleep(interval)
```

**Data flows strictly in one direction**: the producer only writes to GitHub (apply labels / POST edges / `_park`) + writes to the queue (`_enqueue`), and **never claims work**; workers only read the queue (`_claim_next`) + write to GitHub (open PRs / advance pipelines / reply to comments / apply stamps) + delete queue rows, and **never produce work**. All concurrent writes by both sides to `work_queue` are serialized through `BEGIN IMMEDIATE`; no in-process locks are needed.

**How the "no batch barrier" property arises.** As soon as a worker finishes, it claims the head of the queue. Compare this with the "batch" model (each round: `sense → schedule → run the entire batch → sleep`): with K=4, four subjects are selected; three finish in two minutes, and one takes forty minutes, leaving those three freed slots idle for 38 minutes. Separating producer and consumers removes the barrier, reducing slot reuse latency from "the slowest in the same batch" to "≤ one pull" (`_WORKER_POLL_SECONDS`).

**Lifecycle and pool shutdown:**

- `once=True` (tests / single pass): run one `_producer_tick` → `_drain_queue` polls until the table contains neither `queued` nor `claimed` rows → shut down the pool and return (providing deterministic synchronization semantics for tests).
- `once=False` (daemon): loop through tick → sleep. If `_producer_tick` raises an exception, log it and continue (do not kill the producer); exceptions for individual subjects are isolated within workers (do not kill the worker).
- `KeyboardInterrupt`: `stop_event.set()` → workers finish their current work and exit naturally (deleting their own rows + releasing their locks). `queued` rows remain in the DB—idempotent + persistent, safe to leave behind and resume after restart.
- `kill -9` / OOM / power failure: `claimed` rows remain in the database, but the kernel reclaims the locks along with the process. After restart, the first `_reclaim_dead` can acquire the lock → determines that the holder is dead → immediately resets the row to `queued` → it is claimed again. **Recovery latency = one tick, not one lease.** Progress already pushed to GitHub (commits / PRs / comments) will be read as-is by the next `_sense`, and reconcile continues from the point actually reached—the cost of a crash is rereading the current state once, not redoing the work.

### 10. `priority`: Finish Work in Progress Before Starting New Work

A nearly merged PR is occupying the downstream portion of a dependency chain; opening a new issue merely adds work in progress. Therefore, the default weights are based on `_Verdict.action`:

```
reply(6) > merge(5) > review-or-fix(4) > e2e(3) > fix-ci(2) > rebase(2) > solve(1)
   ↑                                                                        ↑
A person is waiting                                            Start new work, last
```

Weights are pluggable (injected through `priority_fn`). `ORDER BY priority DESC` is evaluated at claim time; the priority of a row that has waited a long time is not frozen at enqueue time.

### 11. Walkthrough: Three Subjects, A / B (blocked_by A) / C, K=2

| tick | Producer's determination for each subject | `work_queue` | worker |
|---|---|---|---|
| **t0** | `_intake`: passes three-state triage → apply `ready`; curator establishes `B blocked_by A`, with no incoming edges for C; validation passes → `POST blocked_by`(B←A) | Empty | Poll empty table |
| **t1** | A: `deps_done` ✓, no PR → **ACTIONABLE(solve)**; C: same → **ACTIONABLE(solve)**; B: blocker A not merged → **QUIET(awaiting-blockers)** (no threshold by default; do not park) | `issue:A`, `issue:C` (queued) | W0/W1 each claim one → `_reconcile` advances to opening a draft PR and starting CI → blocked at **QUIET(awaiting-ci)** → release slot |
| **t2** | A/C: **IN_FLIGHT** (if still running), or reclassify after CI produces results; B remains QUIET | — | — |
| **t3** | A's PR is **merged** → A is **TERMINAL**; B's `deps_done` is now ✓, no PR → **ACTIONABLE(solve)** (transitive dependencies unlock naturally) | `issue:B` | Claim B → implement a vertical slice |
| **t4 (main path: the agent asks for human help itself)** | B's CI fails → ACTIONABLE(fix-ci) → enqueue → the agent recognizes an upstream flaky failure that it cannot fix → **apply `needs-human` + leave a comment explaining why** → the next `_sense` iteration within the same claim reads it → **TERMINAL**, finish. **Polling stops immediately, without waiting for any threshold** | `issue:B` row deleted | Claim B → apply label → done |
| **t5 (guardrail one: the agent does not realize it is spinning its wheels)** | C's CI fails → ACTIONABLE(fix-ci) → the agent **thinks it has fixed it** (reran CI but did not get a successful result), makes zero changes, and **does not apply needs-human** → `fp` is unchanged → worker applies an `attempt fp=…` stamp and finishes. Next tick: still ACTIONABLE, but sees a stamp with the **same fp** → downgrade to **QUIET(awaiting-effect)** → do not enqueue, **zero LLM calls** (without this stamp, it would keep invoking the agent forever here) | — | Silent |
| **t6 (guardrail two: timeout fallback)** | C's `awaiting-effect` age exceeds the threshold → `_park`: apply `needs-human` + post a mechanical diagnostic (including the agent's own conclusion) → C enters **TERMINAL**, polling stops | — | — |
| **t7 (hang)** | A/B/C are all in flight or all QUIET → 0 enqueued this tick → `_hang` (distinguish "empty frontier" / "N being worked on" / "N waiting for CI") | Only claimed rows | Poll empty queue |

This table **is** the assertion sequence for the e2e script (**repeated calls** to `run_vigil(once=True)`, one tick per call—a single tick cannot cover the unlocking across rounds from t1→t3).

**t4 and t5 are the two legs of this design, and both must be covered by assertions:** t4 proves that "an agent that knows it is stuck takes a first-class exit: fast, cheap, and with a reason it wrote itself"; t5 proves that "an agent that **does not know** it is stuck is caught mechanically and cannot burn money indefinitely"—the latter is precisely why an agent proactively asking for human help **cannot replace** attempt stamps.

A cycle (the curator mistakenly arranges A↔B) leaves both permanently `QUIET(awaiting-blockers)` → each tick enters `_hang` and emits a notice, rather than silently deadlocking.

### 12. Deployment Boundary: Multiple Processes on One Machine, Not Multiple Machines

SQLite's official documentation **explicitly prohibits** sharing the same database across network filesystems, and the issue is **data corruption**, not performance:

> "file locking logic is buggy in many network filesystem implementations (on both Unix and Windows). If file locking does not work correctly, two or more clients might try to modify the same part of the same database at the same time, **resulting in corruption**."
> "**A good rule of thumb is to avoid using SQLite in situations where the same database will be accessed directly (without an intervening application server) and simultaneously from many computers over a network.**"
> — [sqlite.org/whentouse.html](https://www.sqlite.org/whentouse.html)
>
> "Rely upon it at your (and your customers') peril." — [sqlite.org/useovernet.html](https://www.sqlite.org/useovernet.html)

flock is **likewise** confined to one machine: on NFS, it is emulated as a `fcntl` byte-range lock covering the entire file (man7), and `fcntl` locks are per-process—so the property we rely on, "mutual exclusion among multiple fds within the same process," **silently fails**, breaking mutual exclusion among the K worker threads outright. **Both have the same boundary; flock introduces no new constraint.**

The deployment boundary of this spec is therefore: **one machine, multiple processes, K threads** (`BEGIN IMMEDIATE` serializes concurrent writes and is the single-machine equivalent of Postgres `SELECT … FOR UPDATE SKIP LOCKED`).

**What about a multi-machine topology?** The key distinction: **the queue does not need to be shared across machines; only claims do.**

- The **queue** is a projection of GitHub and can be rebuilt in one tick. Two processes each running `_sense` will independently derive the same frontier—this is precisely the nature of level-triggered behavior. Each stores its own queue; no sharing or reconciliation is needed.
- A **claim** is the only thing that must be globally unique.

GitHub happens to provide **true CAS**: `POST /repos/{o}/{r}/git/refs` — fails if the ref already exists (422). This is one of GitHub's only two CAS primitives (the other is the required `sha` for `PUT /contents/{path}`, which returns 409 if stale). For multiple machines, simply replace claiming with "create `refs/openagents/claims/{subject}`; whoever successfully creates it wins."

**However, the guarantee of zero duplicate execution weakens across multiple machines.** flock is a kernel-level proof of liveness, and kernels do not span machines—when a remote process dies, the local kernel has no way to know. Across machines, the only option is to fall back to leases (a timestamp in the object the ref points to + DELETE-then-CREATE after expiry: DELETE is idempotent and CREATE is CAS, so there is exactly one winner), reintroducing "inferring death from silence" and the resulting window for duplicate execution. At that point, the mitigation is to push "safety under duplicate execution" into the GitHub delivery layer (`force-with-lease`, a hard gate on head advancement, idempotent merge; Spec-0056 already has one of these), downgrading from "duplicate execution never occurs" to "duplicate execution does not break things." **This downgrade is unnecessary in a single-machine topology, so this spec does not implement it** (Occam: do not pay for a "maybe"). The replacement points are contained in four functions: `_claim_next` / `_reclaim_dead` / `_mark_done` / `_requeue_or_park`.

### 13. DAG + File Allocation

| Task | Title | Dependencies | files (single writer) |
|---|---|---|---|
| **T1** | graph-curator agent (zero-logic Template) | — | `openagents/agents/curator.py`, `tests/test_agent_curator.py` |
| **T2** | Rewrite vigil in place as level-triggered reconcile + absorb the old serial capabilities + redirect the CLI | T1 | `openagents/recipes/vigil.py`, `openagents/recipes/stages.py`, `openagents/runtime/state.py`, `openagents/backends/claude_code.py`, `openagents/cli.py`, `openagents/utils/github.py`, `openagents/utils/proc.py`, `tests/test_recipe_vigil.py`, `tests/test_recipe_vigil_act.py`, `tests/test_recipe_vigil_queue.py`, `tests/test_utils_github_vigil.py`, `tests/test_utils_proc.py`, `tests/test_backend_claude_code.py`, `tests/test_cli.py`, `scripts/e2e-spec-0065-graph-parallel-vigil.sh` |

T1 is the parallel root; T2 follows T1 and completes the work. The recipe count remains 3 (stages / backfill / vigil).

**e2e script** (`scripts/e2e-spec-0065-graph-parallel-vigil.sh`): run `run_vigil(once=True)` offline, inject a fixed clock + fake backend / github (including a stub for the `blocked_by` endpoint), feed in three issues (B `blocked_by` A, C independent), and assert the walkthrough table in Section 11. The offline portion is the gating deliverable.

### 14. Implementation Status (T2 `status: done`)

**Everything has been implemented and hardened through review.** Both planes (admission plane / execution plane), the three pure sensing functions, the SQLite claim queue, flock proof of liveness, reconcile branch table ①–⑪, the four guardrails, CLI `--parallel K`, and the offline e2e script (t0–t7) are all implemented, with no `NotImplementedError` placeholders. The old serial implementation was **deleted outright** (git history is the rollback point—keeping a dead copy of 1120 lines would violate Occam's razor and permanently pin a module with no callers onto the architecture diagram).

**Pre-merge review fixes** (made after multiple agents independently reviewed PR #164; all include added tests):

| # | Defect | Fix |
|---|---|---|
| 1 | The `_act` hard timeout claimed the agent's child processes by “diffing this process's set of children before and after the call”—but the producer thread is also running `gh`/`git` (also children of this process), and the K workers run concurrently with one another: **it can identify the wrong processes → kill the wrong ones on timeout while the genuinely hung agent stays alive and continues pushing** (duplicate execution leaks through precisely this hole, which is also the hole flock cannot cover). | Switch to **backend-reported PIDs** (a thread-level claim bucket in `utils/proc.py` + `claude_code` calling `publish` after `Popen`); on timeout, retrieve the bucket by `thread.ident` and use `kill_tree` to kill descendants as well. Also, on timeout, **do not requeue for a retry** (thorough cleanup is only best effort); park directly for human intervention instead. |
| 2 | The three bare sqlite calls for claiming/completing work in `_worker_loop` (`_claim_next` / `_mark_done` / `_requeue_or_park`) were outside a try block—a single `database is locked` exception would **silently kill the worker thread**. If it died between `DELETE` and `close(fd)`, the lock for that `claimed` row would still be held by this process → `_reclaim_dead` would judge its “holder alive” → **never reclaim it, never requeue it**, leaving that subject dead permanently. | Extract `_run_claimed` / `_finish`: no exception may escape this layer, and `finally` **guarantees `close(fd)`** (returning the lock to the kernel; at worst, the row is reclaimed and rerun—reruns are idempotent, whereas an orphaned row is permanent). |
| 3 | The `fp == last_fp` check in `_reconcile` remembered only **the previous round** and could not detect **oscillation** with a period ≥2 (review rejects → implement pushes a new head → review rejects again → …): fp changes every round, so it spins forever at one LLM call per round until someone responds to the IN_FLIGHT alert 2 hours later. | Add a `_MAX_RECONCILE_ROUNDS` (8) round limit; park for human intervention when it is reached (oscillation should be decided by a human anyway). |
| 4 | For a standalone PR, the worktree directory key was derived as “owning issue → 0,” so `pr:12` and `pr:13` shared `.worktrees/issue-0`: agents from two workers **edited code in the same directory simultaneously**, and the later arrival stood on the earlier one's branch, potentially pushing changes to someone else's PR (subject-level flock cannot prevent this—they are two different subjects; what they share is a **resource**). | Use the **PR number** as the directory key for standalone PRs (GitHub issues and PRs share one numbering scheme, so `pr:N` and `issue:N` cannot coexist). |
| 5 | `RuntimeState` performed an unlocked “read the entire JSON → change one key → write the whole thing back,” yet K workers wrote it concurrently: **lost updates** (the later writer erases the earlier writer's records) + **whole-file truncation** (a reader reads partial JSON → falls back to empty state → its next write replaces the entire file with just its own entry). | A class-level `RLock` serializes the entire read-modify-write operation; `_save` uses tmp + `os.replace` (atomic replacement). |
| 6 | `add_blocked_by` used `gh api -f issue_id=…` to send a **string**, while the dependencies API declares `issue_id` as an integer → every dependency edge receives a 422 (and 422 is not on the already/duplicate allowlist → it raises immediately). | Change to `-F` (type inference → JSON number). |
| 7 | `_claim_next` returned `None` on a transient lock conflict, which the worker interpreted as “the queue is empty” → a submillisecond lock conflict on the first row kept **all** workers out (head-of-line blocking). Also, if COMMIT failed after obtaining an fd, it did not close it → that row **could never be claimed again** (the lock was held by this process while the row was queued, and reclamation handles only claimed rows). | Skip that row and continue to the next; always `close(fd)` on the exception path. |
| 8 | A single bad edge in `_proposed_edges` parked the **entire ready set** (one curator hallucination froze the whole pipeline). Also, an unparseable number became `issue:0` → labels/comments were written to **nonexistent issue #0**. | Park only those involved (the host of the bad edge + the cycle members returned by `_cycle_members`); for hallucinated numbers, reject the entire batch and log it, without wrongly implicating any issue. |
| 9 | `--parallel 0` / `-3` were silently clamped to 1, while `--parallel 99999` really started 99999 threads. | Validate `1..32` at the argparse layer and report out-of-range values immediately (no silent clamping—turning an input error into a performance mystery is the worst outcome). |
| 10 | `_drain_queue` (the `once=True` path) had no limit, so any stuck row caused it to **never return**; `_enqueue` froze priority at enqueue time (a solve→merge priority increase while waiting had no effect); `_reclaim_dead` misreported the number reclaimed. | Add a `_DRAIN_MAX_SECONDS` limit, refresh priority for queued rows (without refreshing `enqueued_at`, to prevent starvation), and count using `rowcount`, respectively. |
| 11 | On the path that parks at the limit, the fd could be **closed twice**: `_requeue_or_park` deletes the row → `close(fd)` → `_park_needs_human` runs `gh` (which may raise); when the exception returns to `_finish`, `closed` is still `False` → `finally` closes it again. By then, another thread may already have reused the fd number (another worker's claims lock / a sqlite handle) → **release someone else's flock** → `_reclaim_dead` judges that still-running worker dead and reclaims it → duplicate execution (flock can prevent everything except “someone else released my lock for me”). | Transfer fd ownership with the call: `_mark_done` / `_requeue_or_park` each guarantee exactly one close in their own `finally`; `_finish` sets `closed` as soon as it enters either branch, so its fallback does not close again. (This item originally moved the park network call after lock release, but item 14 later overturned that—parking must **apply the label before deleting the row**, so the network call remains before close(fd); the `closed` flag + each function's own `finally` prevent double-close, rather than relying on call order.) |
| 12 | The delivery portion of `_do_solve` (`stages.deliver`) was the only agent call that did not include `_NEEDS_HUMAN_CONTRACT`—if it could not push (protected branch / permissions / repeated rebase conflicts), that agent had no way out. | Add `context_text=_NEEDS_HUMAN_CONTRACT`; add an e2e anchor: reflect over every `_do_*` (except the purely mechanical `_do_merge`), and fail if even one is missing it. |
| 13 | **The proof of liveness proved the wrong entity alive.** flock is held by the **Vigil process**, but the entity actually changing code and pushing is the **agent child process** it started—when Vigil is killed by SIGKILL / OOM / `docker stop`, that child is **orphaned rather than killed** (it discovers its parent is gone only on its next stdout write, which may be minutes later, enough time to complete a `git push`). The kernel releases Vigil's lock at that point → after restart, `_reclaim_dead` acquires the lock, judges the “holder dead,” and returns the row to queued → another worker claims the same subject → **duplicate execution**, in precisely the scenario this document claimed was “structurally zero.” | **Pass the claimed flock fd to the agent child process for inheritance** (`proc.hold_fd` registers it → `Popen(pass_fds=proc.inherited_fds())` in `claude_code`; flock is bound to the open file description, so inheriting the fd means sharing the same lock). The lock's semantics thus become “the Vigil process **or** its agent is still alive”—while the orphan is running, the lock cannot be acquired and the row will not be reclaimed. The cost falls on the safe side: if the agent leaks a long-lived grandchild process, the row will only **get stuck** (handed to a human by the watchdog), rather than execute twice. |
| 14 | **Parking was not durable.** The path that parks at the limit first `DELETE`d the queue row, then applied the `needs-human` label; if `gh` failed (network / rate limiting), the row was gone and the label was absent. On the next tick, `_sense` derived it as a new subject again → `attempts` **reset to zero** → an infinite park-and-redispatch loop, without the “hand off to a human” terminal state ever taking effect. | Reverse the order: **apply the label first (the only durable trace of parking), then delete the row**. If `gh` fails, the row remains `claimed`; once the lock is released, `_reclaim_dead` reclaims it normally for a retry—retrying is idempotent, whereas losing the terminal state is irreversible. |
| 15 | `kill_tree` sent SIGKILL using a **bare PID**: once the child exits and is reaped, its PID is returned to the kernel and may be reassigned (a long-running Vigil starts several `gh`/`git` processes per tick; PID wraparound is only a matter of time). The timeout handler might therefore kill **another worker's agent** → that row is reclaimed and claimed again → duplicate execution. | Store the `Popen` handle in the claim bucket as well (`publish(pid=…, handle=proc)`); `kill_tree` first verifies identity—`handle.poll() is not None` means “exited and reaped” → return immediately without killing. At worst, failing to kill leaves a stuck row for the watchdog to hand to a human; killing the wrong process directly creates duplicate execution. |
| 16 | The two agent calls in the producer thread (curator admission in `_admit` + edge ordering in `_order_edges`) **did not pass through `_TimedBackend`**—a hang there stalled all of Vigil (including dispatch to the K workers), without triggering any guardrail. | Wrap the producer in `_TimedBackend` too (`lock_fd=None`—the producer holds no row lock, so there is no proof to inherit). |
| 17 | **The fix in item 13 itself opened a worse hole.** Once the lock is passed to the agent child, **it also passes to the agent's grandchildren** (`pass_fds` clears CLOEXEC in the child, and the agent is not python, so it does not close extra fds for us the way `subprocess` does): if the agent leaves even one long-lived grandchild (an MCP server or a background dev server it started), the lock is **never released** → that subject's `queued` row can never be claimed. And **all watchdogs are blind to it**: `_reclaim_dead` scans only `claimed` rows; the IN_FLIGHT alert reads `claimed_at` (which it does not have); the QUIET watchdog applies only to QUIET decisions (this one is ACTIONABLE—which is precisely why it was queued); `_claim_next` silently reports `skipped` each round, so `_hang` reports “frontier empty”—**a lie**. The net effect is to trade rare duplicate execution (only when Vigil is forcibly killed) for a **permanent, silent, undiagnosed** stall. | Add `_sweep_stalled` (in the producer tick, immediately after `_reclaim_dead`): the criterion is structural—**a `queued` row's lock should be free** (the only legitimate holder is the worker for a claimed row). Lock free = merely waiting for one of the K slots → leave it alone (this is the crucial false-positive gate: a long queue ≠ a fault); lock held beyond `_STALE_LOCK_SECONDS`(300) = the holder is not any worker → it can only be a leaked process → park for human intervention (put the diagnostic command `lsof <lock>` directly in the label). **The invariant gained through inheritance holds only if it comes with this gate.** |
| 18 | `attempts` was read only **inside failure handling**; the claim predicate in `_claim_next` ignored it: if the parking `gh` failed (rate limiting / lost network), the row stayed `claimed` → `_reclaim_dead` reclaimed it normally → it was claimed again → **another full agent call ran** before reaching the limit check. Persistent `gh` failure = an infinite loop burning LLM calls (the whole point of `_MAX_ATTEMPTS` is to prevent poison pills from burning calls this way). The **timeout park** path was worse—the forcibly killed agent might already have pushed something, and redispatching is precisely the duplicate execution that the label's “not automatically retried” wording is meant to prevent. | Check the limit on entry to `_run_claimed`: a row with `attempts > _MAX_ATTEMPTS` has only one origin (the previous round already decided to park it, but parking did not take effect) → **retry that park, not that agent call** → go directly to `_finish(park=True)`, with zero LLM calls. |
| 19 | In `_TimedBackend._call`, `track()` / `hold_fd()` were outside the `try`: if `hold_fd` encountered a bad fd and raised `EBADF`, the child thread died leaving an empty box with neither `result` nor `error` → `run()` got `KeyError` from `box["result"]`, turning a diagnosable failure into a mystery. | Move both inside the `try`. |
| 20 | **The gate in item 17 can wrongly park a row that is actively working (TOCTOU).** `_sweep_stalled` first `SELECT`s a snapshot of `queued` rows, then parks them **one by one**—but parking a row requires `gh` (several seconds of network round trips). During those seconds, a worker can legitimately claim **another row** in the snapshot and take its lock; when that row's turn comes, its lock is “held” → judged leaked → apply `needs-human` and **delete a `claimed` row from under a running worker**. With the row gone, `_mark_done`'s DELETE hits nothing when the worker finishes, and `_reclaim_dead` can no longer see it either → the result of that agent call is left entirely unaccounted for. Parking a subject = stopping work on an issue; a false positive costs more than the disease it is meant to cure. | Before parking, **recheck “this row is still `queued`”** inside a `BEGIN IMMEDIATE` transaction (if it reads `claimed` → a worker legitimately claimed it; leave it alone), and guard `DELETE` with `AND status='queued'`. **This version is still wrong; see item 25**—it saves the row, but not the label. |
| 25 | **Item 20 closed only half the hole: it guarded the row, but not what was said.** The recheck is followed by `COMMIT`, and only then by the two `gh` calls (several seconds)—if the leaked process happens to die during that interval, the lock becomes free and a worker **legitimately claims** the row and starts running; our `needs-human` then lands on a **healthy subject currently being executed**. `DELETE … AND status='queued'` faithfully deletes 0 rows (the row is preserved), but the label is already out there: on the next round, `_classify` reads `needs-human` → judges TERMINAL → that worker turns around and leaves, and `_mark_done` deletes the row → **this issue will never be worked on again**. The net effect is identical to what item 17 sought to eliminate—a permanent silent stall, except this time **the gate itself** inflicts it on a healthy issue. (The original implementation's comment reasoned all the way to this window, but stopped one line short.) | **Use `DELETE` itself as the reservation**: inside `BEGIN IMMEDIATE`, `_park_stalled` performs `DELETE … AND status='queued'`; only if `rowcount == 1` (it won the reservation) does it issue `gh`, otherwise it says nothing. `_claim_next` can no longer see the deleted row (it recognizes only `queued`), so “reservation won ⇒ no worker can possibly be running it” is structural. This is **deliberately the opposite** of `_requeue_or_park`'s “apply the label before deleting the row”: that path deletes its own `claimed` row (no one can take it, while losing the label resets `attempts`, causing infinite redispatch that burns LLM calls); this path deletes a `queued` row anyone can claim (losing the label merely lets `_intake` derive it again from GitHub's current state on the next tick and restart timing—a **throttled, zero-LLM** retry). The failure costs are asymmetric, hence the opposite order. |
| 26 | **A promise that was never implemented.** Three places in the body (summary / Guide diagram / Reference §2 step 1) say that the `human` state seeks confirmation from a human **through dialogue**, but `_on_human` in the code merely applies `needs-human` and waits for someone to **manually remove the label**. Yet `needs-human` is TERMINAL in `_classify`, and `_intake` also skips issues carrying it—**once it is applied, Vigil never looks at the issue again**, and nobody reads anything the human replies below. This is no “confirmation through dialogue”; it is a dead end: the precise meaning of the `human` state is “a human must decide this,” and the natural way for a human to decide is **to speak**, rather than manipulate a label. | Implement `_ask_human`: derive all three states from GitHub's current state (level-triggered, zero local memory)—① never asked (no comment with the `_ADMIT_ASK_MARK` marker) → post a **signed** question comment, **zero LLM**; ② asked, human has not replied (the latest comment bears our signature) → do nothing, **zero LLM** (crucial: the admission plane scans this issue again every tick; calling an agent each round would be a money-printing machine billing by the tick); ③ human replied → splice the dialogue into the issue body (`_with_dialogue`—the triager consumes only `issue.body`; without splicing it in, the human's words might as well never have been said) and have the **triager** reassess → if it agrees, apply `ready`; otherwise apply `needs-human` + a reason. **Use triager rather than replier** (the original body said replier): replier's prompt uses **PR context** (`$pr_number` / `$branch` / “if code changes are needed, make them, commit+push”); invoking it on an issue with no PR amounts to asking it to change code, whereas the judgment needed here is precisely the triager's decision surface (`{actionable, reason}`). The **form** of the dialogue (signed comments + checking “is the latest comment ours?” to detect new speech) still reuses replier's discipline against self-loops. **This version is still wrong; see items 27–30**—it connected the human gate to a fail-open agent. |
| 27 | **Item 26 connected the human gate to a machine biased toward “yes.”** `_ask_human` used `stages.triage` to decide “has the human agreed?”—but the triager answers **a different question** (whether the issue body contradicts itself), and its discipline is explicitly **fail-open**: “when uncertain, judge it dispatchable.” If a human replies “don't do this yet; I haven't thought this direction through,” that falls into none of its five contradiction categories → it still judges `actionable=true` → **dispatches work despite the human's explicit rejection**. The entire meaning of `triage: human` is “a human must decide this,” but this version handed that decision back to an agent that defaults to “yes”: worse than the dead end it replaced—the dead end merely stopped, whereas this **starts work against the human's wishes**. | Add `agents/admitter.py` + `stages.admit` + `context.for_admit`: there is only one criterion (did the human actually agree?), with discipline **opposite to the triager—fail-CLOSED**: return `approved=true` only for explicit permission to start work; objections, requests for a plan first, irrelevant answers, bystander interjections, or **uncertainty** all yield `false`. The cost of a missed approval is waiting one more round (the human says another sentence); the cost of a false approval is irreversibly starting work—the costs are asymmetric, so the default must be “no approval.” Feed the dialogue through a **separate placeholder** `$dialogue` (stuffing it into `issue_body` as if it were the body mixes “what the human said” with “the original issue text,” leaving the agent unable to tell which it is judging). |
| 28 | **Our comments were unsigned → the agent deliberated over its own words.** The reason comment posted by `_park_needs_human` was **unsigned**, and every park message instructed the human to “**remove this label** when done; Vigil will automatically take over again.” After the human followed that instruction (removing only the label, without replying), `_intake` could see the issue again, and `_ask_human` read the comment stream—**the latest comment was precisely our own park reason**, unsigned → judged “the human replied” → ask an agent to read our own words → (before item 27) the fail-open triager sees no contradiction → apply `ready` and dispatch. The human said nothing; the gate approved on their behalf. The same hole exists for attempt stamps (if unsigned). The **entire point** of `identity`'s signature discipline is to close this hole. | Sign at the source: `_park_needs_human(*, subject, body, agent_id)` uses `identity.sign`, with `agent_id` passed through all 9 park call sites (`_park_stalled` / `_requeue_or_park` / `_admit._on_agent` / `_ask_human` / `_proposed_edges` / `_park` / `_finish` / `_reconcile` / `_park_gate`). Also, replace the **positional** “latest comment is not ours” test for “the human replied” with the set-based `_human_replies`: comments posted **after** our question **and** lacking our signature—both conditions are required (without “after,” old comments from before the question count as replies; without the signature check, our own words count as replies). |
| 29 | **One `gh` hiccup = one reassessment (the money-printing machine billing by the tick, version two).** Human replies → ask agent to judge → apply `ready` after judgment. If the label step fails (429/403/lost network), `_intake` swallows the exception and logs it; on the next tick, the issue still has “no ready, no needs-human” → run `_ask_human` again → the human's reply is still there → **call the agent again**. Every failed `gh` round causes another judgment: one human reply can burn N LLM calls (observed: 1 reply → 5 ticks → 5 agent calls). Item 26 ensured zero LLM calls only for the “human has not replied yet” portion, not the “judged but not applied” portion. | **Record the verdict on GitHub before applying it**: `_post_admit_verdict` stamps `{approved}` into a **signed + marked** comment (`_ADMIT_VERDICT_MARK` + `approved`/`refused`), then applies the label. On the next tick, `_admit_verdict` reads that stamp back (requiring it to be **newer** than our question) → directly retry applying the label, **zero LLM**. Still level-triggered: all truth resides in GitHub's comment stream, with zero local memory. |
| 30 | Duplicate machinery on the read side: item 26 added `github.issue_comments` to read issue comments, but `list_issue_comments` (Spec-0049/T1) already existed, using the same `gh issue view --json comments`. Two synonymous functions each parse the same data; a future change to the `Comment` structure is bound to miss one. | Delete the newly added function and fold both read paths (`list_comments` using `gh pr view` / `list_issue_comments` using `gh issue view`) into shared `_parse_comments`—only the retrieval command differs; parsing has a single implementation. |
| 31 | **The stamp in item 29 turns `fail-closed` into “permanent rejection”** (found through self-check, not in any review round). If the reuse criterion is “reuse the stamp if it is newer than the **question**,” then after one `refused`: we apply `needs-human` (TERMINAL, skipped by `_intake`), the human follows the instructions and replies “okay, do it,” then removes the label—on the next tick, `_ask_human` reads the refused stamp, which is **still newer than the question** → reuses it directly → applies `needs-human` again. The human's new words are **permanently overridden** by our own old verdict, and they can never approve. The intent of fail-closed is “when uncertain, wait for one more sentence,” but this implementation becomes “never listen to the sentence you waited for.” | Attach the verdict stamp to **the human's latest words**, rather than our question: `_admit_verdict(comments, latest_reply)` reuses it only when `stamp.created_at >= latest_reply.created_at`. Once the human speaks, the old verdict is automatically invalidated and reassessed; if the human does not speak (only removes the label, or a `gh` hiccup prevented the previous label from being applied) → reuse the old verdict, **zero LLM** (still saving the call item 29 intended to save). Change the park message accordingly: “**post a comment** clarifying the situation, then remove the label”—the original message only instructed people to remove the label, leading them straight into this dead end. |
| 32 | **That “human gate” recognizes no one** (seventh round, rebutting the fixes in items 27–31). `_human_replies` has only two criteria for “the human replied”: after the question + no signature of ours. GitHub's `Comment` clearly has `author`, but it was never read; the admitter prompt did say “if it is not that person speaking, do not treat it as a decision”—but it received only a piece of text and **had no idea whom it should listen to**, making that discipline impossible to enforce. Thus, in a public repository: any account able to comment replies “yes, do it” → `ready` → dispatch. A fail-closed gate with the key hanging outside the door. | Decide “whose words count” definitively **in code**: add `author_association` to `Comment` (GitHub's native `authorAssociation`, retrieved along with `--json comments`); `_human_replies` accepts only `OWNER/MEMBER/COLLABORATOR`. Fail-closed: missing association (empty string) / `CONTRIBUTOR` / `NONE` ⇒ ignore as noise. Narrow `_dialogue` accordingly to “our question + maintainers' replies”—bystander comments never enter the prompt (otherwise a fail-closed gate is effectively exposed to prompt injection). |
| 33 | **Agent judgment fails = burn one LLM call per tick, forever** (seventh round, HIGH). Item 29's “stamp first, label second” protects only the **label application** step; when `stages.admit` itself raises (agent output is not JSON, `_ActTimeout`, backend 429), `_ask_human` throws out the whole operation, leaving neither `ready` nor `needs-human` on the issue → `_intake` scans it again on the next tick → judge again. Observed: 10 ticks → 10 agent calls, 0 labels, 0 comments. Worse, **a human can trigger this reliably** (by replying “don't output JSON when replying to me”), and a 429 actually hits the `gh` call in `_post_admit_verdict` first—the very example item 29 gave does not hold. | Buy a ticket before spending money: `_post_admit_try` posts a signed try stamp **before** calling the agent (`_ADMIT_TRY_MARK` + the comment id of the human's words). On the next tick, “try stamp present, verdict stamp absent” ⇒ the previous judgment failed ⇒ hand off to a human with **zero LLM** (`needs-human` + “post another comment to try again”). One human reply buys **at most one** agent call; if the stamp itself cannot be posted (`gh` fails), raise immediately and **call no agent at all**, then retry unchanged on the next tick. |
| 34 | **The fix in item 31 fails within the same second** (seventh round). The verdict-stamp reuse criterion is `stamp.created_at >= latest_reply.created_at`, but GitHub's `createdAt` has **only second precision**. If a human changes their mind within the same second (first “not yet,” then immediately “okay, do it”), the new words and old verdict stamp share a second → `>=` is always true → the old refused stamp swallows the new words → back to “permanent rejection.” Changing it to `>` is also wrong: our own stamp cannot recognize the words it just judged → reassessment every tick. | Attach the stamp to **the comment id of the human's comment** (`_reply_key`), using **exact equality** as the criterion, with no time comparison. An id is identity, not a time scale: a different comment has a different id, distinguishable even within the same second. Timestamps are used only for ordering (who spoke after the question), no longer for identity. |
| 35 | Park reason comments were not idempotent: a human removes `needs-human` without changing any facts (misreading, accidental action, label automation), and on the next tick it parks again unchanged—the reason is identical, yet it produces a **new comment**. Labels are idempotent; comments are not. | `_park_needs_human` first reads the comment stream back; if the same reason (compare unsigned bodies—the signature's `agent_id` differs per process, so the full text cannot be compared) has already been posted, **only restore the label; do not repost**. The comment stream is already this path's single source of truth; one more read is the cost it must bear. |
| 36 | The frontmatter's `files` omitted three test files actually changed by this PR (`test_recipe_vigil_admit.py` / `test_github.py` / `test_runtime_context.py`); the wording in item 11 (“move the park network call **after** lock release”) had also been overturned by item 14 (“apply the label before deleting the row”), yet remained in the table. | Add them to T2's `files` (files-allocation is a design-time ownership declaration; omission amounts to no declaration); annotate item 11 in place with “overturned by item 14”—this table is **history**, so it must be annotated rather than rewritten retrospectively. |
| 37 | **The local all-green 788 was false** (exposed immediately by the fix in item 35; CI red, local green). `_park_needs_human` began **reading the comment stream** for idempotent deduplication—six existing park tests had no stub for this new path, so they actually shelled out to `gh issue view 5 --json comments`: `gh` was logged in on the development machine, and issue #5 really existed in the real repository, so everything read back normally → **flawlessly green tests, except they were reading live data**. They failed only in CI without `GH_TOKEN`. Nothing in the test suite prevented network access: for a new GitHub read/write path, the cost of a missing stub was **silent**. | Add `tests/conftest.py`: an autouse **hard gate against network access** wraps `subprocess.run`, raising `AssertionError` whenever `argv[0] == "gh"` (other commands such as git pass through unchanged; tests that stub `subprocess.run` themselves setattr after the fixture, naturally overriding this gate). From then on, whenever production code touches GitHub in a new place, tests missing a stub fail immediately **on the development machine**, directly identifying the `gh` command. Also add `list_issue_comments` / `list_comments` stubs to the six park tests missing them. |
| 38 | **Guardrail two was dead for the entire `solve` stage** (eighth round, independent review checking each item against the code, HIGH). `_sense` fed timestamps into `progress` (head pushes, CI, PR comments) only inside `if pr_number is not None:`; an `issue:N` **without a PR yet** (the normal state for `solve`) can never enter that branch → `progress` always empty → `last_progress_at` always `None` → `_watchdog` immediately short-circuits at its first line, `if … clock.last_progress_at is None: return False`. Thus the chain most in need of protection was completely exposed: agent runs `solve` without producing a PR (unaware it accomplished nothing) → fp unchanged → `_reconcile` posts a same-fp attempt stamp on the **issue** → producer `_consider` downgrades to QUIET(awaiting-effect) → stays there **forever**, with no age calculable by the watchdog, no needs-human trigger, and nobody called in. Guardrail one (attempt stamps) only stops spending; it does not stop deadlock. This is exactly what both the §5 table, “state should move but does not → watchdog → GitHub timestamps,” and §Reference-3, “`last_progress_at = max(…, latest comment time, latest attempt stamp time)`,” promised but the code lacked—spec-ahead-of-code. | Add an `elif kind == _KIND_ISSUE:` branch to `_sense`: issues without a PR also read `list_issue_comments` and feed comment timestamps into `progress` (both attempt stamps and human comments reside on the issue). The watchdog can now calculate age; QUIET(awaiting-effect) beyond the threshold → needs-human. (Do not change `latest_comment_is_ours`: human-machine dialogue on issues without a PR belongs to the **admission plane** admitter; reply branch ② requires PR context and is not activated here.) Test `test_sense_clock_reads_the_issue_comments_when_there_is_no_pr_yet`: mutate away this branch → `last_progress_at` returns to `None`, and the assertion fails immediately. |
| 39 | **It checks the identity of “who replied,” but accepts anyone as “who posted the stamp”** (eighth round, independent security review, HIGH). `_human_replies` checked `authorAssociation` to block bystanders, but the stamp readers `_admit_verdict` / `_admit_tried` performed only bare substring matching, with no such check anywhere. The marker strings (`_ADMIT_VERDICT_MARK`, etc.) and signature `<!-- openagents:agent=… -->` are **all public text anyone can copy**—in a public repository, any NONE bystander can post `<!-- openagents:admit-verdict:approved:<comment id of the maintainer's neutral reply> -->` + a copied signature; on the next tick, `_admit_verdict` treats it as “already judged last round, approved” → **allow directly with zero LLM**, bypassing the maintainer gate and admitter (the hole item 32 just closed leaks back unchanged from the **stamp-reading** side). The reverse also works: forge a try stamp to force a maintainer's **genuine approval** back to needs-human. | The only thing that cannot be forged is `authorAssociation` (GitHub calculates it from the real author; it is outside the body and cannot be written by a bystander). New `_is_our_stamp(comment)` = maintainer association **and** our signature; both stamp readers must pass it first. Our bot posts these stamps as a maintainer (an account able to apply labels / push branches / merge must be OWNER/MEMBER/COLLABORATOR), so no number of forged markers from NONE/CONTRIBUTOR can pass. Fail-closed: missing association (empty string) is always rejected. Two mutation tests (forged verdict stamps must not allow admission / forged try stamps must not force parking) fail if the gate is removed. |
| 40 | Three **known boundaries, not fixed this round** (raised in eighth-round review, recorded here, with no code changes): (a) If a maintainer **edits an old comment in place** to change their mind instead of posting a new one—GitHub preserves comment id and createdAt (changing only updatedAt), and the verdict stamp is attached to the id → the old refused stamp continues to match → edited approval is never reassessed. **Fail-closed and safe** (no false admission), and the park message already explicitly says “**post a comment**, then remove the label”—changing one's mind through editing goes against the instructions. (b) When **two** vigil producers run in the same repository, the admission plane's try stamp is a non-atomic “read—check absence—post stamp”; both processes may each spend one LLM call. **Outside this spec's deployment model** (single producer + K workers; execution-plane flock/SQLite protects only workers, while admission runs inside the producer-exclusive `_producer_tick`). (c) Item 39's `_is_our_stamp` identifies “our stamp” by **maintainer association**, rather than the bot's own login—consistent only under a `gh`-CLI-as-user deployment (the gh account able to post stamps necessarily has write permission, i.e. OWNER/MEMBER/COLLABORATOR). This repository **currently has no** GitHub-App token path (`_run_gh` only invokes bare `gh`; no GH_TOKEN/installation anywhere in the repository), so this is not a problem; but **if App authentication is introduced later**, an App bot's `authorAssociation` may be NONE while it still has write permission → our own stamps are silently rejected → admit burns another LLM call every tick (the §14/33 money-printing machine leaks back from the **stamp-reading** side, with **silent** degradation rather than an error). At that point, bind the gate to `comment.author == this instance's login` instead of association (GitHub calculates it from the real author, making it unforgeable and more precise—also fixing the looseness of “maintainer + **any** signature ≠ this exact bot”). None of the three is changed: (a) fixing it requires introducing updatedAt as identity, disrupting the idempotency of “do not reassess the same words”; (b) fixing it requires locking the admission plane, burdening the main path for an unsupported deployment; (c) there is currently no App path, so adding a self_login pipeline adds complexity for a nonexistent deployment. Prefer **explicitly documenting boundaries** to adding needless complexity (Occam's razor). |
| 21 | **The age gate used the wrong data.** The original criterion was an over-age `enqueued_at`, but `enqueued_at` is **never refreshed**, to prevent starvation (as established in item 10). Both `_requeue_or_park` / `_reclaim_dead` first change `status` back to `queued` and **commit**, then `os.close(fd)`—the instant between is a **legitimate** “`queued` with lock held.” Thus, as soon as a long-running row is requeued, its `enqueued_at` is already “over-age,” and it can be judged leaked and parked precisely during this handoff window. The more frequently a healthy row retries, the more likely this gate is to kill it. | Change age to **cross-tick** memory (`seen_locked: dict[subject, first observation time]`, held by `run_vigil` and passed to the producer): “`queued` with lock held” must be observed on **two different ticks** before timing counts, and parking occurs only beyond `_STALE_LOCK_SECONDS`. The handoff window is a microsecond-scale instant within the process and cannot survive a tick; once the lock is free, erase the memory (restart timing). |
| 22 | One failed row park takes down everything: a `gh` exception in `_park_needs_human` (429 / lost network) escapes all the way out of `_sweep_stalled` → `_producer_tick` dies entirely → this round has **no `_intake`, no sensing, no enqueueing**. One rate limit turns the peripheral task of “sweeping stale locks” into a full-line outage. | One `try/except` per row: if parking fails, log it, leave the row, and retry next round (retries are idempotent); also, **do not reset** the first observation time in `seen_locked`—one 429 should not restart the stale-lock clock. |
| 23 | `_drain_queue` (the `--once` / test path) did not sweep stale locks: a row with a leaked lock remains `queued` and can never be claimed → the drain loop waits through all of `_DRAIN_MAX_SECONDS`(1h), exiting only at the hard limit. | Call `_sweep_stalled` in drain polling too—park rows that need parking immediately, and let `--once` finish at once. |
| 24 | Item 18's park reason stated **inference as fact** (“the previous round already decided to park it, but parking did not take effect”): `attempts` can exceed the limit through other paths—if the Vigil process is restarted repeatedly, `_reclaim_dead` returns running rows to `queued` and applies `attempts+1` each time, so even a **healthy** row can be driven to the limit this way. With the original wording, the very first sentence handed to the human is misleading. | Change the reason to state only verifiable facts (claimed N times, never completed, and what the limit is), **listing** possible causes rather than asserting one. |

**Review discipline**: This table is a chain of **fixes correcting fixes** (item 31 was even caught by a self-review during the same round of fixes—if a `fail-closed` default sticks to an old verdict, it turns from “caution” into “permanent refusal”)—items 13/15 came out of the second review round; items 17/18 were the third round’s rebuttal of **those fixes**; items 20–24 were the fourth round’s rebuttal of **the gate in item 17**; and item 25 was the fifth round’s rebuttal of **the gate in item 20** (it blocked rows but missed labels). Each round’s fixes deserve more scrutiny than the original code they fix: they are newly written, have never actually been run, and often sit on the critical path—the gate introduced in item 17 can **park**, which means it can **stop work on a healthy issue**. Its false-positive cost is higher than the problem it is meant to cure, which is why three consecutive rounds kept refining the same few dozen lines of code. Item 26 is a different kind: the fix was not “implemented incorrectly”; rather, **the prose promised it, but the code did not implement it at all**—only checking the spec against the code clause by clause could uncover it. Items 27–30 were precisely the sixth round’s rebuttal of **the implementation added in item 26**, and the worst episode in this chain: it did not stop Vigil; it made Vigil **start work despite an explicit human veto** (by wiring a human gate to a fail-open agent), plus a self-dialogue loop of “our comments are unsigned → the agent holds a meeting over its own words.” The pattern is consistent: **the most dangerous part of each round’s fixes is precisely those few dozen newly written lines that have never actually been run and sit on the critical path**. Items 32–35 were the seventh round’s rebuttal of **the fixes in items 27–31**, confirming the pattern: those fixes rescued the human gate from a “fail-open agent” but forgot to make it **recognize who people are** (item 32: the gate was fail-closed, but the key hung outside the door, so any passerby could open it). And the stamp introduced in item 29 to save LLM calls was completely ineffective on the path where the agent’s **judgment crashes** (item 33: one reply could burn an unlimited number of LLM calls)—**the guardrail written to save money missed precisely the most expensive path**. The self-review fix in item 31 did not survive even one round either: it used timestamps with only **second** precision as identity (item 34). Item 37 was the most embarrassing episode in the chain: the fix in item 35 proved **on the spot** that “all green locally” was itself untrustworthy—the test suite had nothing preventing network access, and six old tests with missing stubs read all the way through to **the real production repository**, passing without a hint of trouble. These test false positives were not a matter of “incorrectly written tests”; **the acceptance criteria were broken**: they were testifying against the production environment. Hence the addition of a hard offline gate (item 37), turning this kind of green from “silent” into “immediately red on the developer’s machine.” The eighth round changed tactics: instead of having “the previous round’s fixes” rebut one another, **two independent reviews each pinned the spec to the code clause by clause**—one focused on the admission gate’s safety invariants, while the other checked every promise in the spec. Each track uncovered one HIGH, and neither had been in view during the first seven rounds: item 38 was **promised in the prose, but unreachable in the code** (the §5 watchdog was ineffective throughout solve without a PR, the same category as item 26 but deeper because it was hidden inside the indentation of an `if pr_number is not None`); item 39 was **the same hole leaking back in from the symmetric opposite side** (item 32 had just established identity checks for “who replied,” while the “who applied the stamp” side still checked nobody). The pattern was confirmed again: the most dangerous parts are never the old code, but the few newly written pieces that have never actually been run and sit on the critical path. Every fix is pinned down by a test that turns red if the fix is reverted (mutation verification was performed item by item: revert the fix → the corresponding test must fail).

**Tests** (791, all green): `tests/test_recipe_vigil.py` (branch table / fp invariants / flock reclamation under a real `kill -9` / failure to park one row does not take down the entire producer tick / **issues without a PR also obtain their progress clock from the issue comment stream**—otherwise the watchdog is ineffective throughout solve), `tests/test_recipe_vigil_act.py` (`_act` routing for every branch + first-class exit contract on every agent call + `_TimedBackend` kills precisely by claim bucket + no worktree collisions for bare PRs), `tests/test_recipe_vigil_queue.py` (exactly-once claims / no head-of-line blocking / zero fd leaks and **exactly one close** / worker exception isolation / oscillation cap / bad edges park only those involved / reclamation does not falsely report success / queued rows with leaked locks are swept out and handed to a human without penalizing long queues / stale-lock detection must span ticks and must not mistakenly kill the handoff window when returning to the queue / rows claimed by a worker during parking are neither parked nor deleted (TOCTOU) / the drain path also sweeps stale locks / above the cap, retry only park with zero LLM calls and give only provable reasons), `tests/test_utils_proc.py` (claim buckets isolated by thread + real process-tree `kill_tree` + no mistaken kills from PID reuse + inherited fd registration), `tests/test_utils_github_vigil.py` (parsing invariants for 8 new github read/write functions), `tests/test_agent_curator.py`, `tests/test_agent_admitter.py`, `tests/test_cli.py`, `tests/test_recipe_vigil_admit.py` (cross-tick dialogue for the three admission `human` states: ask only once / zero agent calls while waiting for a human reply / old comments from before the question do not count as replies / judge only after the human replies, using the **fail-closed admitter** rather than the fail-open triager / apply a signed verdict stamp before applying the label—if the label write fails, retry on the next tick with zero LLM calls / **if a human speaks again after refused, immediately invalidate the old verdict and judge again** (otherwise fail-closed degenerates into permanent refusal) / the park-reason comment **is signed**—if a human only removes the label without leaving a comment, our own words must not be read as the human’s reply / **a passerby’s “yes, go ahead” does not count as authorization**, and is not included in the prompt (the human gate recognizes only OWNER/MEMBER/COLLABORATOR) / **if the admitter’s judgment crashes, one reply burns only one LLM call**, then hands off to a human, and if the try stamp cannot be applied, there are zero LLM calls / **two comments in the same second are two turns**—stamps are tied to comment ids, not timestamps / post the same park reason only once / **check identity on the stamp-reading side too**—a passerby’s forged verdict stamp must not grant admission, and a forged try stamp must not force park (the one thing they cannot forge is `authorAssociation`)), `tests/conftest.py` (**hard offline gate**: any test that actually shells out to invoke `gh` immediately raises `AssertionError`—every additional GitHub interaction in production code makes tests with missing stubs fail on the developer’s machine, instead of using the locally authenticated `gh` to read the real production repository and pretend to pass). Offline e2e: `scripts/e2e-spec-0065-graph-parallel-vigil.sh` (t0–t7 + grep/reflection anchors: flock rather than lockf, `_mark_done` is DELETE, no lease column, zero direct subprocess calls in recipes, self-reported PID+handle, flock fd inheritance, the stale-lock gate’s BEGIN IMMEDIATE recheck / DELETE guard / cross-tick memory / single-row isolation / sweeping during drain too, needs-human contract injection across all branches, `--parallel` boundaries).

## Drawbacks

**Engineering scope**

- **T2 is a heavy single-file task.** “Rewrite vigil in place as level-triggered reconcile + absorb the old serial parity + DB claim queue + change the CLI target” is packed into one Task / one PR, making it large. This is an inherent cost of “converge on a single file + rewrite in place”: `vigil.py` is a single-writer file and cannot be split into multiple parallel Tasks. If smaller PRs are desired, the only path is two **sequential** PRs (first serial parity + the sensing layer, then add the queue + parallelism).
- **vigil.py becomes a large file.** Both sides + the reconcile branch table + the fleet are all in one file. This is a **deep module** in Ousterhout’s sense (a simple `run_vigil` interface + extensive inline functionality), preferable to spreading it across a collection of intertwined shallow modules—but the file is indeed long.

**Invariants that must be pinned down by tests**

- **The field set of `facts`.** It is both the input to `_classify` and the hash input to `_fingerprint`. Add a branch but forget to add the fields it reads to `facts` → that branch **silently never triggers**; conversely, mix `clock` into `fp` → guardrail one fails and the agent is repeatedly invoked. The code structure (two functions consuming the same immutable structure) prevents much of this, but a test must directly assert that their field sets are identical; otherwise this invariant is merely a matter of discipline.
- **`facts` must not contain fields that “the worker also changes as it finishes.”** The fp rule is “any real progress must change fp,” but **the converse does not hold**—some actions change fp without making progress, and the most dangerous is the attempt stamp itself (it is a new comment). If the comment id enters fp, applying the stamp immediately invalidates that stamp → infinite agent reinvocation, **guardrail one destroys itself by becoming the very infinite loop it is meant to prevent**. Therefore, `facts` retains only the `latest_comment_is_ours` boolean. Before adding any field to `_Facts`, ask: will the worker touch it as it finishes? Test: `_fingerprint` must be equal before and after `_post_attempt_stamp`.
- **`_reconcile` must pass `in_flight=False` when calling `_classify`.** The worker itself is the in-flight holder. Passing True means that the first thing it does after claiming work is conclude “someone is working on it” → immediately finish → **every worker spins without doing work, and the system makes no progress**, while the logs look entirely normal (the queue is moving, rows are being deleted). This is a fatal default differing by a single word and must be pinned down directly by a test.
- **The sha in the review verdict label.** A bare `review-approved` remains in place after “review complete → agent pushes again to fix CI” → branch ⑪ merges **code that nobody has reviewed**, irreversibly. Test: after head advances, the same `review-approved:<old sha>` must make the predicate fall back to ⑩, never ⑪.
- **The flock fd lifecycle.** The lock is bound to the open file description, and **closing any fd pointing to it releases the lock**—a casually written `with open(...)` can make a worker lose its proof of liveness midway through its work, causing `_reclaim_dead` to declare the row dead and reclaim it → duplicate execution, silently (no exception, no log). The fd must be passed explicitly from `_claim_next` to `_mark_done` / `_requeue_or_park`. This is the **only** cost this design pays for “zero duplicate execution,” and it can be pinned down by tests (see T2 acceptance criteria).

**Tuning risks**

- **The watchdog threshold is a double-edged sword.** Set it too tight and it will misclassify normally running CI as STUCK → mistakenly apply `needs-human` → block a good PR, making it worse than having no watchdog. Mitigation: give the threshold ample slack (CI p95 × 3), make it configurable per repository, and make park fully reversible (only add a label + comment; removing the label revives it). But the “right threshold” still requires empirical measurement and is listed under Unresolved.
- **The `awaiting-effect` grace period slows cases that have truly hit a wall.** After the agent judges “flaky, no changes,” it must wait for the threshold (~5 minutes) before parking and calling for a human. This is the cost of accommodating the window for asynchronous effects to take hold. Mitigation: the agent can proactively apply `needs-human` to take the fast path.

**Costs of feature tradeoffs**

- **`reply` is blocked behind long-running tasks by mutual exclusion on the same subject.** If a human comments on a PR with a 40-minute solve in progress, they must wait for solve to release the slot before receiving a reply. This is the direct cost of the serial safety provided by `subject UNIQUE`. Acceptable (replies do not require hard real-time guarantees), but it must be accounted for honestly.
- **Using an LLM to arrange dependencies has cost and uncertainty.** Calling an LLM for every new issue is slower than a purely mechanical approach and may arrange dependencies incorrectly. Three layers of mitigation: existing edge anchors are fixed; a hard validate gate (cycles / references); and **incorrect ordering affects only scheduling order, not correctness**—`deps_done` mechanically rechecks GitHub’s current state, so an incorrectly arranged graph can at worst reduce parallelism somewhat.
- **The curator’s “full reordering” is constrained to “anchored incremental updates.”** Dependency edges are mutable truth jointly written by humans and machines; the curator cannot overwrite the entire graph (doing so would erase manually set edges). The benefit is natural collaboration with humans; the cost is that the curator cannot correct existing edges it arranged incorrectly in its previous round (a human must change them in the UI)—listed under Unresolved.

**Scale and boundaries**

- **1+N dependency reads per round + one `_sense` per subject.** These accumulate at scale, and GitHub REST’s authenticated rate limit is 5000 requests/hour. With dozens of subjects, the impact is negligible; at hundreds, batching is needed (see GraphQL under Future).
- **Parallelism amplifies contention for shared resources.** With K>1, multiple workers contend for the same `.git` and write RuntimeState concurrently (a risk explicitly listed in #137). Isolation comes from “subject as the unit of concurrency + an independent worktree per worker,” but locking in the shared bare `.git` must be covered by actual e2e testing.
- **SQLite + flock tie deployment to a single machine.** See §12: network filesystems cause data corruption (explicitly stated by sqlite.org), and flock semantics fail on NFS. Multiple machines require replacing the claim backend (git-ref CAS or Postgres), and the zero-duplicate-execution guarantee will degrade back to leases. This is an explicit scale boundary, not a current problem—but it is a **hard constraint on deployment topology**, and cannot be left for later.
- **One new storage entity.** `.openagents/vigil-queue.db` appears to violate “do not add entities unnecessarily.” Guide §6 has already argued that it stores only three things GitHub cannot express (atomic claims / crash counts / claim ordering), and losing it is harmless (rebuilt in one tick). The cost is minimized: stdlib `sqlite3`, a single file, zero external services, and a schema with one table and nine columns.

## Rationale and alternatives

**Observation model**

- **level-triggered (history-free predicates) vs change detection (remember the previous round's state and invoke the agent when it changes).** Choose **level-triggered** (constraint C4). Change detection has four unfixable holes: (1) **Edges can be lost**—if the process crashes between “detecting that CI has turned green” and “actually merging,” the snapshot has already been overwritten with “green,” so the next round's diff is empty → the PR will never be merged; (2) **the agent's own writes are changes**—pushes / label changes / comments all trigger the next round, requiring an “ignore myself” filter at every write site; miss one and you have a money-burning infinite loop; (3) **omitting one field from the hash = permanent blindness to an entire class of work**—the most typical example is forgetting `mergeable_state`: when the base advances and causes a PR to develop conflicts, the comments have not changed, the commits have not changed, and the CI results have not changed → zero edges → it never triggers; (4) **changes to the dependency frontier do not occur on the subject itself**—B has merged, but not a single byte of A's state has changed; per-subject change detection cannot see this at all, and the entire issue graph gets stuck at the first node. This is exactly what the K8s principle ("Edge-triggered behavior must be just an optimization") means.
- **Where change detection remains.** It remains as an **optimization**, but with two semantic changes: what is stored is not “the state polled in the previous round,” but “**the state I saw when I took action**”; it is written not during polling, but **when the agent finishes**; and it lives in **GitHub** (an attempt stamp), rather than locally. These two changes simultaneously fix hole (1) (crash → no stamp → retry next round) and hole (2) (fp is the input state when I took action; even if my output changes fp, it will not trigger me again).
- **Split `_Observed` into `facts` / `clock` vs use one flat structure.** Choose **the split**. If `clock` is mixed into `fp`, starting a check run refreshes `started_at` → fp changes → the agent is invoked again, even though the branch table never examines this field. Only after the split does “fp field set ≡ branch table input set” become an invariant that can be expressed as a test.

**Event model**

- **One row per subject vs one row per event (`kind` = solve/advance/reply).** Choose **one row per subject**. `kind` is a copy of GitHub's current state (“what stage this PR is currently in”), and the current state must be reread every tick—under this spec's own storage principles (no overlap, no reconciliation), it should not exist. Nor does it buy any parallelism: the three event types for the same subject must already run serially, so “one row per event” additionally requires a `NOT EXISTS` subquery in `_claim_next` to **take that parallelism back**—it creates a problem that only it needs to solve. Removing `kind` also eliminates `dedup_key`, `NOT EXISTS`, `ix_work_queue_issue_status`, and the three-way dispatch in `_execute`, while the single pillar of `subject UNIQUE` provides deduplication, serialization, and idempotency together.
- **Collapse three scanning passes into one branch table vs three event types.** Choose **the branch table**. The three passes look like three separate tasks, but they are actually three facets of the same question (“what should this subject do now?”)—the evidence is that `advance_merge` in the old serial Vigil already implements sections ⑤–⑪ of this table.
- **Have the worker advance until blocked vs take one step per tick.** Choose **advance until blocked**. An all-green PR should be merged within a single claim, rather than burning three ticks. The stopping condition is “verdict is not ACTIONABLE (blocked on something external) or fp stops changing (cannot advance further on its own)”—both are pure-function checks and require no counter.

**Resolution and guardrails**

- **Have the agent apply `needs-human` itself (a first-class exit) vs rely entirely on mechanical guardrails.** Choose **a first-class exit**. When the agent determines it has no way forward, applying the label and leaving a reason itself is the fastest, most accurate, and cheapest way to resolve the situation: it burns no extra LLM calls, waits for no timeout threshold, and writes the reason itself (providing far more information than mechanical diagnostics). This contract goes into the prompt for every branch. **The previous version relegated it to a footnote (“that is the fast path”) and put the entire main narrative on fp stamps + the watchdog—the emphasis was misplaced: those two should be fallbacks.**
- **Then why not remove fp stamps too and rely entirely on the agent to call for a human?** Because that **only covers cases where “the agent knows it has no way forward.”** Another class remains: **the agent does not know it is spinning its wheels**. It reruns CI but fails to trigger it successfully, changes an unrelated file, or leaves a comment saying “just wait for CI to rerun” and finishes—it does not think it has no way forward, **so it will not apply `needs-human`**. And the comment it leaves each round **refreshes `last_progress_at`, preventing the watchdog from ever firing either**. At that point, apart from mechanically comparing “whether meaningful fields on GitHub changed before and after you took action,” **nothing can stop it from rerunning indefinitely**. The value of fp stamps is precisely that they **do not trust the agent's self-assessment**.
- **Use one bit, “present / absent,” for the fp stamp vs a counter (park only after N attempts).** Choose **one bit**. fp unchanged ⟺ every field the branch table cares about is unchanged ⟺ zero progress—invoking it again with the same evidence and the same prompt has an expected benefit close to zero. And parking is cheap and reversible (a human removes the label to reactivate it), so calling for a human early has almost no cost. Retries for actual transient failures belong **inside the agent** and should not bubble up into a tunable parameter at the orchestration layer.
- **Use a time threshold for `awaiting-effect` vs park immediately.** Choose **a time threshold**. Because **fp unchanged ≠ zero progress**—it only means “I have not seen progress yet.” The agent has pushed, but the GitHub API still returns the old head (eventual consistency); the agent has triggered a CI rerun, but the check has not yet switched to pending… In these cases, parking immediately would incorrectly stop an agent that is actually doing work, which is worse than not parking.
- **Calculate watchdog age from GitHub timestamps vs local timing.** Choose **GitHub timestamps**. Time itself is part of the current state (every GitHub object carries it), so “how long it has been stuck” is a **pure function of the current state**, requiring no local memory—restarts, database loss, and machine changes have no effect. And as soon as the head changes, `last_progress_at` refreshes automatically and the timer resets.
- **Why `attempts` cannot also be removed.** It handles **ways of dying that leave no trace on GitHub**: the agent crashes / is killed—it has not stamped anything (it did not finish), nor has it refreshed any timestamp. Neither fp nor age can detect this. The only option is to count it in the queue row.

**Claiming and reclamation** (the most contentious point in this spec)

- **`flock` (observe death) vs leases (infer death).** Choose **`flock`**. A lease infers death from silence, but silence has two possible causes—“the process is dead” and “the agent is writing a large feature”—and **no timeout threshold can distinguish them**. A narrow threshold → incorrectly declare a living worker dead → reclaim its row → duplicate execution; a wide threshold (1 hour in v0) → a genuinely crashed subject silently stalls for an hour. By contrast, the **kernel** automatically releases `flock` when the process dies (including `kill -9` / OOM / power loss), so “the lock can be acquired” is **proof** that “the holder is gone,” rather than an inference. The probability of duplicate execution thus goes from “small if the threshold is tuned well” to **structurally zero**, and crash recovery latency drops from “one lease” to “one tick.” The cost: deployment is pinned to a single machine—but the SQLite prohibition in §12 **already** pins it to a single machine; flock introduces no new constraint.
- **`flock` vs PID probing (`os.kill(pid, 0)`).** Choose `flock`. PIDs can be **reused**: after a restart, a new process happens to receive the old PID → it is misread as “the holder is still alive” → the subject is stuck forever. Closing this hole requires additionally storing and comparing process creation times (`psutil.Process.create_time()`), introducing a third-party dependency to patch a hole that `flock` does not have in the first place. The `worker_pid` column remains, but only for human diagnostics (so it can be inspected with `ps`); it participates in no decisions.
- **Must use `flock`, not `fcntl.lockf` (POSIX `F_SETLK`).** The latter's locks are per-process; two fds in the same process locking the same file do not exclude each other—yet this spec uses “one process, K threads,” so `lockf` would make mutual exclusion within the same process **silently fail**. `flock` locks are bound to the open file description, so separate `open()` calls in the same process still conflict. This is correctness, not style.
- **Why a hang (alive but making no progress) cannot be solved through reclamation.** “Reclaiming a row from a living holder” **is duplicate execution by definition**. Hangs therefore follow two paths that do not reclaim: an `_act` hard timeout (the holder itself kills the agent and releases the row and lock) + the IN_FLIGHT watchdog (only `_park` to call for a human; never touch the row). This asymmetry—only a dead holder's row may be reclaimed; a living holder's row can only be dealt with by the holder itself or a human—is the final pillar of zero duplicate execution.

**Architectural layers**

- **Avoid new recipe modules vs add a layer each for intake / scheduler / graph.** Choose **inline everything into Vigil** (constraint C5). The previous batch just consolidated recipes from 6 to 3; adding three new modules + keeping two Vigil implementations side by side = reversing that consolidation and adding dead code on net.
- **Rewrite Vigil in place vs create vigil2 and keep both stacks.** Choose **rewrite in place**—there is only one CLI entry point, vigil, and no deferred debt. During the rewrite, the old implementation was temporarily saved as `vigil_backup` for reference; **delete** it when wrapping up: it has zero callers and zero coverage; keeping it would leave a dead module permanently pinned into the architecture diagram, while git history already provides a better rollback point.
- **Put curator in agents/ vs inline it into Vigil.** Choose `agents/curator.py`. The convention for the agents/ layer is “Template prompts with zero logic,” while the recipes/ layer contains control flow—putting prompts into a control-flow file is what would violate the layering.
- **Put prompts in agents/*.py vs Claude Code skills.** Choose `agents/*.py`. Skills are specific to Claude Code, while CLAUDE.md requires backend compatibility with claude code / codex / nexau—prompts must remain somewhere that lets `engine.run_agent` feed them to any backend.

**Where state belongs: labels vs native fields**

- **Put “decisions” in labels; read “facts” from native fields.** Choose **separation**. `ready` / `needs-human` / review verdicts are all **decisions we make**—GitHub has nowhere else to express them, and labels are immediately visible in the UI and can be manually added or removed by humans (this is the entry point for self-healing). Conversely, CI results and `mergeable_state` are **facts maintained by GitHub itself**: they are already bound to a sha and read in one go. Copying them into labels as well (“put every state variable in a label”) **creates a second source of truth**, then makes us responsible for keeping the two from conflicting—who updates the label when CI reruns? Miss one update and there is a silent misjudgment. This violates this spec's own storage principles (no overlap, no reconciliation).
- **Review verdict labels must include the head sha.** Choose `review-approved:<sha7>` rather than bare `review-approved`. A verdict is not an eternally true property; it is **a judgment tied to a particular commit**: the head was `abc1234` during review, then the agent pushed `def5678` to fix CI after the review—the bare label remains → branch ⑪ reads it as “all green + reviewed” → **code that nobody has reviewed gets merged**, and merging is irreversible. Including the sha automatically invalidates the verdict when the head changes and sends it back to ⑩ for another review. This is a property GitHub's native PR reviews (inherently bound to `commit_id`) provide for free; reproducing it with labels gives us “humans can see at a glance in the UI which commit was reviewed.” If native PR reviews are adopted in the future (see Future), this duplication can be removed.

**Dependency edges**

- **Where to store them: GitHub native dependencies vs custom labels vs local graph.json.** Choose **native dependencies** (the endpoint has been tested and works for this repository). Native dependencies provide a dedicated namespace, structured reads (directly returning blockers with `state`), webhook + UI support, and a shared place for humans and machines to write. Custom labels require preventing naming collisions + parsing strings; local graph.json requires reconciling two stores with labels.
- **Who determines the ordering: LLM vs purely mechanical analysis (static analysis of file overlap).** Choose LLM (constraint C1). Purely mechanical analysis can only capture “file-conflict ordering,” not “logical ordering” (A defines an interface before B can use it; the two may not touch the same file). File-conflict ordering remains a mechanical supplement for `priority_fn` (see Future).
- **Graph updates: incremental updates constrained by anchors vs unconstrained full reordering.** Choose **incremental updates constrained by anchors** (required by constraint C2). Existing edges (including those set by humans) are anchors that cannot be overwritten.

**Queue**

- **Store in a DB vs an in-memory `queue.PriorityQueue`.** Choose SQLite. An in-memory queue cannot provide atomic claiming (constraint C3), crash durability, or ordering at claim time.
- **SQLite vs Postgres vs GitHub labels.** Choose SQLite (stdlib, zero external services). GitHub labels are ruled out not because “they cannot hold the data,” but because **they lack atomicity**: REST does not support conditional requests for POST/PUT/PATCH/DELETE, and label POST uses append semantics—two concurrent claims both succeed, and neither reports an error. Postgres is an option for multiple machines (see §12), but this spec does not pay that cost in advance.
- **Remove the `NOT EXISTS` subquery from `_claim_next`.** Mutual exclusion for the same subject is already structurally guaranteed at enqueue time by `subject UNIQUE`; checking again at claim time is pure redundancy. This is a direct benefit of “one row per subject” over “one row per event.”
- **`_mark_done` must DELETE, not set `status='done'`.** Under the UNIQUE constraint, retaining a done row prevents that subject from ever being enqueued again → PR deadlock. This is correctness, not style.

**Scheduling**

- **Frontier: a local predicate for each node vs topological sorting of the entire graph.** Choose **local predicates** (all direct blockers merged). Transitive dependencies emerge naturally as merges occur (in A→B→C, C unlocks only after B is merged, and B can only be merged after A is merged). Only cycle detection requires scanning the entire graph; do that once in validate.
- **Correct a design debt along the way.** The old `vigil.py` used the higher-order function `route(*, owner, on_agent, on_human, on_skip)` + a set of factories that merely forwarded calls—**shallow modules + entanglement**, with interfaces as complex as their implementations. The new Vigil is structured around deep modules: read the branch table from top to bottom.

## Prior art

**The shape of the execution plane (level-triggered + workqueue)**

- **Kubernetes architectural principles: level-triggered behavior ensures correctness; edge-triggered behavior is merely an optimization** —— *"Functionality must be level-based, meaning the system must operate correctly given the desired state and the current/observed state, regardless of how many intermediate state updates may have been missed. Edge-triggered behavior must be just an optimization."* This is the **first principle** of this spec's execution plane (constraint C4). https://github.com/kubernetes/design-proposals-archive/blob/main/architecture/principles.md
- **The client-go controller workqueue: put only KEYs in the queue, not objects** —— Reflector → DeltaFIFO → Informer → WorkQueue (deduplication + rate limiting) → N workers → `processNextWorkItem`; after receiving a key, a worker **goes back to the Indexer to retrieve the current object**. Deduplication is lossless precisely because the queue contains only keys. **This is exactly where this spec's approach of “put only `subject` in the queue, then have the worker reread GitHub through `_sense` after receiving it” comes from**—the `kind`/`dedup_key` version put “objects” into the queue, violating this principle. The Informer's periodic resync (a full relist) corresponds to this spec's `_sense` on every tick. https://github.com/kubernetes/sample-controller/blob/master/docs/controller-client-go.md
- **Airflow pools + `priority_weight`** —— A pool's slot count limits concurrency, while `priority_weight` orders the runnable set. This corresponds to this spec's “K-slot bounded pool + `priority_fn` stored in the `work_queue.priority` column.” https://airflow.apache.org/docs/apache-airflow/stable/administration-and-deployment/pools.html

**Storing dependency edges in GitHub**

- **Native GitHub issue dependencies (GA in 2025-08)** —— `blocked_by` / `blocking` become first-class entities, with a full REST API + webhooks + a UI sidebar. This spec stores dependency edges directly in this facility. https://github.blog/changelog/2025-08-21-dependencies-on-issues/ ; API: https://docs.github.com/en/rest/issues/issue-dependencies
- **GitHub REST does not support conditional requests for unsafe methods** —— *"Conditional requests for unsafe methods, such as POST, PUT, PATCH, and DELETE are not supported unless otherwise noted."* Combined with the **append** semantics of label POST ("adds labels to an issue's existing labels"), these two facts form the complete argument for why “claiming cannot be implemented on GitHub” (constraint C3). GitHub's only two CAS primitives are `POST /git/refs` (fails if the ref already exists) and `PUT /contents/{path}` (requires `sha`; returns 409 if stale)—neither operates on issue metadata, but the former is the basis for multi-machine claims in §12. https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api

**Queues and claims**

- **A DB as a persistent work queue** —— A single table + atomic claiming within a transaction (Postgres `SELECT … FOR UPDATE SKIP LOCKED` / SQLite `BEGIN IMMEDIATE` + `RETURNING`) replaces an in-memory queue, providing crash durability + ordering at claim time. Postgres SKIP LOCKED: https://www.postgresql.org/docs/current/sql-select.html ; SQLite WAL: https://www.sqlite.org/wal.html ; `RETURNING`: https://www.sqlite.org/lang_returning.html
- **Multica's `agent_task_queue`** —— A multi-agent coding system with “cloud control-plane orchestration + local daemon execution-plane task claiming”: `ClaimAgentTask` uses `UPDATE … WHERE id=(SELECT … FOR UPDATE SKIP LOCKED) RETURNING *` for atomic claiming, `prepare_lease_expires_at` for an SQS-style visibility timeout, and `MaxConcurrentTasks` + slot semaphores for two layers of backpressure. This spec's `_claim_next` / `attempts` directly follow that model. **Two differences**: (1) Multica has multiple daemon **processes** claiming from the same queue, so it requires Postgres; this repository uses K threads on a single machine, with SQLite `BEGIN IMMEDIATE`. (2) Multica uses **leases** for reclamation; this spec does not—leases guess whether a worker is dead, forcing a choice between “mistakenly treating a live worker as dead (duplicate execution)” and “stalling for one lease duration after a real crash”; in a single-machine topology, `flock` lets the kernel provide the answer directly, so we use it (see Rationale). (Internal system; notes from studying its source code.)
- **`flock(2)`: locks are attached to an open file description and released when all associated fds are closed** —— *"Locks created by flock() are associated with an open file description (see open(2)). This means that duplicate file descriptors (created by, for example, fork(2) or dup(2)) refer to the same lock…"*, and the release condition is *"the lock is released either by an explicit LOCK_UN operation on any of these duplicate file descriptors, or when all such file descriptors have been closed."* **When a process terminates, the kernel closes all of its fds**, so the lock is unconditionally released—this applies equally to `kill -9` / OOM / segmentation faults / rebooting after a power failure; the process has no opportunity to “forget” to release it. This is the foundation of this spec's **zero duplicate execution**: “being able to acquire the lock” = proof that “the holder is no longer there,” rather than an inference.
  The same page also directly supports the critical property that “K threads in the same process still provide mutual exclusion” —— *"If a process uses open(2) (or similar) to obtain more than one file descriptor for the same file, these file descriptors are treated independently by flock(). An attempt to lock the file using one of these file descriptors **may be denied by a lock that the calling process has already placed via another file descriptor**."* That is, each worker uses `open()` to obtain its own fd, and locks still conflict within the same process, exactly as required. (Compare `fcntl(2)` record locks—the man page explicitly states *"flock() and fcntl(2) locks have different semantics with respect to forked processes and dup(2)"*; those locks are per-process, so multiple fds within the same process do not provide mutual exclusion → they would **silently fail** under the “one process with K worker threads” model. This is a hard reason to choose `flock` over `lockf`.) https://man7.org/linux/man-pages/man2/flock.2.html

**Deployment boundary**

- **SQLite's official guidance: do not share the same database across a network filesystem** —— *"file locking logic is buggy in many network filesystem implementations… resulting in corruption."* This firmly fixes this spec's deployment boundary at **multiple processes on a single machine** (§12). https://www.sqlite.org/whentouse.html ; https://www.sqlite.org/useovernet.html
- **On network filesystems, `flock` is “emulated” rather than native** —— *"Since Linux 2.6.12, NFS clients support flock() locks by emulating them as fcntl(2) byte-range locks on the entire file."* Once this degrades to `fcntl` byte-range locks, the property of “mutual exclusion across multiple fds within the same process” no longer holds, and mutual exclusion in the K-thread model silently fails. This is the same boundary as SQLite's prohibition. https://man7.org/linux/man-pages/man2/flock.2.html

**Other**

- **LangGraph** —— Models workflows as graphs, supports runtime `add_node` / `add_edge`, cycles, and parallel fan-out, and allows the graph itself to be orchestrated by an LLM into a “living graph.” This corresponds to this spec's curator. https://langchain-ai.github.io/langgraph/concepts/low_level/
- **Ousterhout's *A Philosophy of Software Design*** —— Deep modules (simple interfaces + substantial functionality) are preferable to shallow modules. This guides the choice to “inline both planes entirely into deep functions in vigil” (constraint C5). https://milkov.tech/assets/psd.pdf

## Unresolved questions

**Thresholds (all require empirical measurement)**

- **Default watchdog thresholds** —— What should `awaiting-ci` use (proposal: CI p95 × 3, but p95 must be measured); `awaiting-mergeability` (proposal: 3 minutes); `awaiting-effect` (proposal: 5 minutes, which must cover GitHub's eventual-consistency window after a push + the delay before a CI rerun switches to pending). Setting these too narrowly will mistakenly kill normally running CI, which is worse than having no watchdog.
- **Whether `awaiting-blockers` should have a threshold.** Disabled by default (upstream blockers have their own watchdogs; duplicate timing would only cause false kills). But if a cycle forms (the curator mistakenly arranges A↔B), both remain permanently QUIET, with only `_hang` emitting an aggregate notice—should there be a very long fallback threshold (such as 24h) that directly parks subjects in cycles?
- **Time budget for a single invocation**—shares `OPENAGENTS_CLAUDE_MAX_WALL` with Claude (default: 3600 seconds; finite values <=0 disable it; see 0046). Exhausting the total duration only means the budget has expired; it does not prove a hang. `_reconcile` can dispatch multiple invocations in succession, so this is not a cumulative per-subject budget. IN_FLIGHT alerts still only observe that the holder has exceeded its age threshold; they do not reclaim active rows.
- **The value of `_MAX_ATTEMPTS`** (default: 3), and whether exceptions thrown by `_reconcile` (actual failures) and worker crashes (leaving no trace) should be counted differently.
- **Default priority weights** —— §10 provides an interpretable default (`reply > merge > review > e2e > fix-ci ≈ rebase > solve`), but the strength of the bias toward “finishing work in progress first,” and whether to add an aging factor, require empirical testing. The contract is settled: return an integer (`ORDER BY priority DESC`).
- ~~**Lease duration and heartbeat renewal**~~ —— **Closed**. Leases have been replaced entirely by `flock` (Guide §5.3): reclamation no longer depends on any timeout threshold, so both “how long should the lease be?” and “should heartbeats renew it?” disappear together. The `CLAIM_LEASE_SECONDS` constant is removed.

**Details still to be settled**

- **The form of the test for the `facts` field-set invariant** —— How can one test directly assert that “the set of fields hashed by `_fingerprint` == the set of fields read by `_classify`”? (Option: `_Facts` is a frozen dataclass, `_fingerprint` hashes the full set from `dataclasses.fields()`, and a test then asserts that perturbing each field can change `_classify`'s verdict.) To be settled in T2.
- **Concurrency strategy for shared `.git` locks** —— When K>1, the granularity of serialization for multiple workers operating on the bare `.git` (global lock vs. per-worktree fetch) needs e2e stress testing to establish the limits (aligned with the risks explicitly listed in #137).
- **A channel for the curator to correct existing incorrect edges** —— Under anchor-constrained incremental updates, the curator cannot modify existing edges. Should this go through “a human manually editing them in the UI,” or should there be an explicit “reordering instruction” bypass?
- **Visibility noise from attempt stamps.** Each fp that hits a wall leaves a comment on the PR. There is a natural upper bound (one per fp; a changed fp = a genuinely new situation), with about 3–6 comments for a normal PR—exactly the work log a human wants to see. But if fp changes frequently because of some high-frequency field (such as a flaky check repeatedly flipping), stamps will accumulate. The actual frequency of fp changes needs to be measured.
- **Debouncing `_hang` notices** —— Emitting a notice every round while the frontier remains empty would flood the output; a debounce that “stays silent if the state has not changed” is needed (it could follow review's sticky-pass fingerprint).
- **Whether to split T2 into two sequential PRs** —— Whether the substantial single-file task should be split into two sequential PRs: “serial parity + sensing layer” / “add queue + parallelism.” Neither approach produces “two implementations of vigil coexisting at the CLI entry point.”
- **Windows does not support `fcntl`.** Development in this repository is on macOS and CI is on Linux, so v1 does not address this. If support is needed in the future, the replacement points remain those 4 claim functions (`msvcrt.locking` or a switch to PID + create_time)—but note that the PID approach reintroduces the PID-reuse hole.

## Future possibilities

- **Multi-machine topology: replace claims with GitHub git-ref CAS.** §12 has already identified the primitive (`POST /git/refs`, which fails if the ref already exists) and the replacement points (4 claim functions). The queue itself does not need to be shared across machines—each of the two processes will independently derive the same frontier through `_sense`. Note that the guarantee of zero duplicate runs will degrade back to a lease-based guarantee.
- **Use the GitHub Notifications API as an “early wake-up” signal.** `GET /notifications` + `If-Modified-Since` (304 responses do not count against the quota) + respecting `X-Poll-Interval` can wake a tick early when a new comment arrives / CI completes. This **can only be an optimization**: `ci_activity` notifications are sent only to the person who triggered the run, are off by default, and have an “only notify on failure” mode (green CI may produce no notification at all). `_sense` remains the source of truth. This is exactly the shape of client-go’s “watch leg + resync leg.”
- **Batch `_sense` with GraphQL.** Fetch PRs + checks + reviews + `blockedBy` for multiple subjects in a single query, collapsing one REST round trip per subject into a single-digit number of round trips—directly easing pressure on the quota of 5000 requests/hour.
- **Use native PR reviews for review verdicts (instead of ordinary comments).** A PR review is inherently tied to a `commit_id`; as soon as the head changes, the verdict is automatically invalidated—an “evidence provenance stamp” comes for free, without having to embed head_sha in comments yourself.
- **Parallel fleets across multiple repositories** — Bring `run_fleet`’s “one `run_vigil` per repository” into the same pool of K slots, with unified scheduling across repositories.
- **Sequence scheduling around file conflicts** — Feed static file-overlap analysis into `priority_fn` so that “issues that will write to the same file” run at staggered times, while also strengthening the runtime owner checks proposed in issue #71.
- **Self-healing for STUCK** — The watchdog currently only parks the task and calls for human intervention. In the future, it could self-heal for specific causes (`awaiting-ci` timeout → call the API to rerun the workflow / push an empty commit). But the causes vary too widely (Actions disabled, workflow syntax errors, misconfigured base, GitHub down); blind self-healing would only create noise—observe the actual distribution first.
