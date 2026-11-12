---
number: "0004"
title: "openagents vigil — Vigil mode (autonomous full-cycle issue→PR loop)"
issue: 9
slug: vigil-autonomous-loop
summary: "Vigil mode: let OpenAgents autonomously repeat the full “discover issues → solve them → submit PRs” workflow without human supervision. Includes label-gated issue discovery, a two-phase loop with discovery and waiting phases, per-issue error isolation, a vigil subcommand, and an end-to-end script."
tasks:
  - id: T1
    title: "github-layer `list_issues` (label-gated issue discovery)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - automation
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: "Add list_issues(*, labels, state=\"open\") in openagents/github.py, invoking gh issue list --state <state> [--label L ...] --json number,title,body and parsing the result into a list of existing Issue objects; reuse _gh_json/GithubError without introducing new data types."
    acceptance: "Unit test coverage: with no labels, the command contains no --label and correctly parses multiple issues; with multiple labels, the command contains the corresponding multiple --label options; an empty result returns []; a nonzero gh exit raises GithubError; ruff check / ruff format --check / pytest pass."
  - id: T2
    title: "`Vigil` loop module (discovery phase + waiting phase + error isolation)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - automation
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/vigil.py
      - tests/test_vigil.py
    scope: "Create openagents/vigil.py and implement run and discover_and_dispatch on Vigil (with injected Orchestrator/Messages/State). discover_and_dispatch calls github.list_issues, then filters for new issues through three gates (labels already enforced at the list layer, no run in State, and no remote branch), calls start_rfc serially (dispatch only drafts an RFC), and logs and skips individual failures. In each iteration, run first performs discovery, then calls messages.poll; once returns after one iteration, otherwise time.sleep(interval) continues the loop; KeyboardInterrupt exits cleanly. Reuse a single git ls-remote implementation for the remote-branch check (a minimal private helper within vigil or exposed through the injected orchestrator, without changing the orchestrator's existing contract)."
    acceptance: "Unit tests (mocking github.list_issues/Orchestrator.start_rfc/Messages.poll/time.sleep and the remote-branch check) cover: issues with an existing State run are skipped; issues with an existing remote branch are skipped; a new issue triggers start_rfc once; when start_rfc raises OrchestratorError for an issue, that issue is skipped without affecting other issues or poll in the same iteration; once=True runs only one iteration without sleeping; once=False calls sleep(interval) across multiple iterations; KeyboardInterrupt returns cleanly; discover_and_dispatch returns the list of issue numbers actually dispatched."
  - id: T3
    title: "CLI `vigil` subcommand + end-to-end script"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - automation
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
      - scripts/e2e-rfc-0004-vigil.sh
    scope: "Register the vigil subcommand in openagents/cli.py (--interval defaults to 60, repeatable --label defaults to [\"openagents\"], --base defaults to main, and --once is a flag). Implement _cmd_vigil to run preflight, construct Vigil (add a _vigil_for factory, reusing the existing _orchestrator_for/_messages_for/_state_for), and call run; add it to the _dispatch handlers. Runtime exceptions are handled centrally by the existing _run. Add scripts/e2e-rfc-0004-vigil.sh (a deterministic offline section + an optional live smoke-test section, following e2e-rfc-0002)."
    acceptance: "Unit test coverage: vigil appears in the set of subcommands; defaults are interval=60/labels=[\"openagents\"]/base=\"main\"/once=False; vigil --once --interval 5 --label a --label b --base dev is parsed correctly and passed through to the stubbed Vigil.run; _cmd_vigil runs preflight first; the return code is 0. The offline section of the e2e script (ruff + pytest) can run successfully on its own."
---

# 0004 · openagents vigil — Vigil mode (autonomous end-to-end issue→PR loop)

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

“Vigil mode” lets OpenAgents autonomously cycle through the entire “discover issues → solve them → submit PRs” workflow without continuous human supervision. It consists of three layers: `github.list_issues` provides label-gated issue discovery; the `Vigil` module drives dispatch through a two-phase “discovery phase + watch phase” loop and isolates failures for individual issues; and the CLI `vigil` subcommand connects these into a persistent loop that can be started with a single command, accompanied by an end-to-end script.

## Motivation

OpenAgents aims to let people step away from code details and focus only on high-level oversight. Before this feature, however, “claim an issue → draft an RFC/PR” still required a person to trigger each case manually: someone had to look through the repository for outstanding issues, determine which ones had not yet been claimed, and initiate dispatch for each unclaimed issue individually. This step is purely mechanical polling and deduplication—precisely the part that machines should take over.

Vigil fills this automation gap: like a persistent overnight process, it periodically scans open issues with specific labels, automatically dispatches new issues on which work has not yet begun for RFC drafting, and also handles PR comment messages in each round (the watch phase). People therefore need only start `openagents vigil` once; routine “discovery and dispatch” then runs automatically, leaving human involvement at the two ends: “file issues” and “review PRs.”

## Guide-level explanation

For users: run a single command to put OpenAgents into Vigil mode:

```
openagents vigil [--interval 60] [--label openagents ...] [--base main] [--once]
```

- `--label` determines which issue labels Vigil watches (repeatable; defaults to `openagents`)—only open issues with these labels are discovered.
- `--interval` is the number of seconds to sleep between rounds (default: 60).
- `--base` is the base branch for the PR/worktree when dispatching drafting work (default: `main`).
- `--once` runs just one round and returns (useful for testing and scripting); without it, the loop runs persistently until `Ctrl-C`.

In each round, Vigil first performs “discovery and dispatch”: it lists labeled open issues and passes each issue through three gates—matching labels (already guaranteed at the listing layer), no run for that issue in the local State (not previously claimed), and no corresponding remote working branch (no one is working on it)—then dispatches each entirely new issue once, serially, to draft an RFC. A dispatch failure for an individual issue is logged and skipped without affecting the other issues in the same round. It then enters the “watch phase” to handle PR comment messages, sleeps for `interval` seconds, and begins the next round. `Ctrl-C` exits cleanly.

## Reference-level explanation

The changes are broken down into 3 Tasks, with mutually exclusive `files` and a single writer per Task:

1. **T1: `list_issues` in the github layer** — Add `list_issues(*, labels, state="open")` to `openagents/github.py`, invoking `gh issue list --state <state> [--label L ...] --json number,title,body` and parsing the result into a list of existing `Issue` objects. Reuse the existing `_gh_json` parsing helper and `GithubError` error type; introduce no new data structures. This is the data source for the discovery phase: label gating is passed directly through `--label` to `gh`, completing the first gate at the discovery layer.

2. **T2: `Vigil` module** (depends on T1) — Create `openagents/vigil.py` and implement the `Vigil` class (with `Orchestrator`/`Messages`/`State` injected at construction). Two core methods:
   - `discover_and_dispatch`: Call `github.list_issues` to retrieve labeled open issues, then apply two runtime gates—no run for that issue in the local `State` (deduplicate previously claimed issues), and no corresponding remote working branch (deduplicate issues already being worked on)—and serially call `Orchestrator.start_rfc` for the remaining entirely new issues (dispatch only drafts RFCs; it does not directly implement code). If `start_rfc` raises `OrchestratorError` for an individual issue, log it and skip that issue to ensure error isolation; the method returns the list of issue numbers actually dispatched.
   - `run`: In each round, first call `discover_and_dispatch`, then `messages.poll` (the watch phase, handling PR comments). With `once=True`, return after one round; otherwise, call `time.sleep(interval)` and continue looping. Exit cleanly on `KeyboardInterrupt`.

   Reuse a single `git ls-remote` check for the remote-branch criterion (implement a minimal private helper within vigil, or expose it through the injected orchestrator), without changing the orchestrator’s existing contract.

3. **T3: CLI `vigil` subcommand + e2e** (depends on T2) — Register the `vigil` subcommand in `openagents/cli.py` (`--interval` defaults to 60, repeatable `--label` defaults to `["openagents"]`, `--base` defaults to `main`, and `--once` is a flag). `_cmd_vigil` first runs preflight, then constructs `Vigil` using the new `_vigil_for` factory (reusing the existing `_orchestrator_for`/`_messages_for`/`_state_for`), calls `run`, and is registered in the `_dispatch` handlers; runtime exceptions are handled centrally by the existing `_run`.

**End-to-end validation**: `bash scripts/e2e-rfc-0004-vigil.sh`—the deterministic offline phase runs `ruff` + `pytest`, with an optional live smoke-test phase as well (following the structure of `e2e-rfc-0002`); the offline phase can pass independently.

Dependency DAG: `T1 → T2 → T3` (a linear chain, with no parallelism).

## Drawbacks

- Vigil is a persistent polling process. Setting `interval` too short increases request load on `gh` and the remote; setting it too long increases discovery latency. Responsiveness and overhead must be balanced.
- The “three gates” deduplication relies on two sources of truth: the local State and remote branches. If they are temporarily inconsistent (for example, a branch has been created but State has not yet been persisted to disk), a window for duplicate dispatch may arise, requiring idempotent downstream dispatch as a fallback.

## Rationale and alternatives

- **Why combine discovery and dispatch into a single loop module**: Discovery (list_issues), deduplication (State + remote branches), dispatch (start_rfc), and watching (poll) are consecutive actions within the same Vigil cycle. Orchestrating them together in `Vigil.run` is more cohesive than scattering them across the CLI, and also makes it easier to write hermetic unit tests for the entire loop (by mocking each dependency).
- **Why put label gating in the `list_issues` layer instead of filtering within the loop**: Pass `--label` directly through to `gh issue list` so GitHub performs the filtering, reducing the amount of data fetched and avoiding reimplementing label logic on the client (Occam’s razor; no new data types).
- **Why skip a failed individual issue instead of interrupting the entire round**: Vigil needs to run unattended for long periods. One bad issue should not bring down an entire round of discovery and watching—error isolation is a baseline robustness requirement for a persistent loop.
- **Alternative: replace polling with GitHub webhook push notifications**. Rejected (YAGNI): webhooks require a publicly accessible callback endpoint and additional infrastructure. Starting with polling is sufficient for “unattended discovery” at present; webhooks can be a future evolution.

## Prior art

“A persistent watcher periodically polls a task source, deduplicates and dispatches new tasks, and isolates individual task failures” is an established daemon pattern in CI/automation (for example, various polling-based job runners). This feature takes its core of “polling + deduplication + error isolation” and applies it to OpenAgents’ issue→RFC dispatch context.

## Unresolved questions

None. The deduplication criteria for the three gates, the cadence of the two-phase loop, and the error-isolation behavior have all been settled within this group.

## Future possibilities

- Replace periodic polling with GitHub webhook event push notifications to reduce discovery latency and request overhead.
- Extend the watch phase with finer-grained message classification and priority scheduling, beyond handling PR comments.
- Make dispatch concurrent (currently serial) to improve throughput for multiple issues within a round.
