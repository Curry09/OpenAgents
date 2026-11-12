---
number: "0003"
title: "Issue-solving isolation — a separate worktree for each issue + branch baseline pinned to the latest main"
issue: 0
slug: issue-worktree-isolation
summary: "Solve each issue in a separate git worktree, with the branch baseline pinned to the latest origin/main, to prevent cross-contamination between issues. Also add real-time event-stream feedback, interruptible and resumable idempotent solving, and unified CLI error handling (exceptions do not emit tracebacks)."
tasks:
  - id: T1
    title: "Switch solve/iterate to per-issue worktrees + an `origin/<base>` baseline + a `--base` option"
    status: done
    priority: P1
    tags:
      - architecture
      - backend
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - openagents/cli.py
      - tests/test_orchestrator.py
      - tests/test_cli.py
    scope: "Rewrite the Orchestrator workspace logic: solve first runs fetch origin <base>, then creates a worktree from origin/<base> at <repo_root>/.openagents/worktrees/issue-<n> (idempotently cleaning up leftovers before creation), invokes the backend within that worktree, runs add/commit/push, and opens a PR; iterate reuses or recreates the same worktree to continue the work. Add --base (default: main) to the solve subcommand in cli.py and pass it through to Orchestrator.solve; also catch runtime exceptions uniformly around CLI dispatch → print ✗ and exit cleanly without emitting a traceback (formerly T4)."
    acceptance: "The solve call sequence includes git fetch origin main and git worktree add -b openagents/issue-<n> <path> origin/main, and no longer runs checkout -b in the main working tree; the backend work_dir is the worktree path; commit/push work normally without force-push; with solve --base <ref>, the worktree is created from origin/<ref>; iterate appends commits within the worktree; the CLI passes --base through, with main as the default; ruff check/ruff format --check/pytest all pass; OrchestratorError/GithubError/RuntimeError are caught, resulting in a nonzero exit code without a traceback."
  - id: T2
    title: "Real-time solving feedback: backend stream-json event stream + progress lines for orchestration stages"
    status: done
    priority: P1
    tags:
      - architecture
      - backend
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backends/claude_code.py
      - tests/test_backend_claude_code.py
    scope: "Change ClaudeCodeBackend.run to use --output-format stream-json --verbose + Popen, parse NDJSON events line by line, print assistant text and tool actions (🔧 <tool>: <hint>) to stdout in real time, and obtain the summary from the result event; raise RuntimeError (with details) on a nonzero exit; pass non-JSON lines through unchanged and use them as fallback details. Orchestrator prints ▶ … progress lines to stderr at each stage. The git status logic for determining whether there are changes remains unchanged."
    acceptance: "The backend Popen command includes --output-format stream-json --verbose; assistant text/tool events are visible in real time through capsys; summary is obtained from the result event; a nonzero exit raises RuntimeError; each solve stage has a ▶ progress line on stderr; all unit tests with mocked subprocesses pass."
  - id: T3
    title: "Idempotent, resumable solve (route to fresh/resume based on State) + issue↔PR binding + gh fallback"
    status: done
    priority: P1
    tags:
      - architecture
      - backend
      - cli
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - openagents/github.py
      - tests/test_state.py
      - tests/test_github.py
    scope: "At the solve entry point, look up the existing record with state.find_by_issue and route according to decision 7: when resuming, reuse the branch/worktree (without the cleanup in decision 4), append commits, and use find_pr_by_branch to reuse the PR or open one if missing; for a fresh run, follow decisions 1/2/4 and first record solving with begin_run. _commit_and_push tolerates “no changes to commit” (skip commit but still push). Add begin_run / find_by_issue to state.py; add find_pr_by_branch to github.py."
    acceptance: "When the issue already has an open PR, solve resumes the work and reuses the PR (without calling create_pr), does not recreate the branch, and sets the state to iterating; if a crash occurs after begin_run (with no PR), rerunning can open the missing PR; unit tests for find_by_issue/begin_run/find_pr_by_branch pass."
---

# 0003 · Issue-solving isolation — a separate worktree per issue + branch baseline pinned to the latest main

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine rust-RFC sections. -->

## Summary

Run each issue-solving process in a **separate git worktree**, created from the latest `origin/<base>` (`main` by default), with the branch named `openagents/issue-<n>`, completely isolating issues from cross-issue working-tree contamination and stale baselines. Add three capabilities on top of this isolation framework: **real-time event-stream feedback** during solving (backend stream-json + orchestration-stage progress lines), **idempotent, resumable** solving (fresh/resume routing based on persisted State, issue↔PR binding, and fallback PR reuse through gh), and **consistent CLI error handling** (print a clean `✗` line and exit with a nonzero status on runtime exceptions, without emitting a traceback).

## Motivation

The old implementation solved issues directly in the main working tree (`git checkout -b`), causing two types of problems:

- **Cross-issue contamination**: When solving multiple issues concurrently in the same repository, sharing a working tree lets uncommitted changes and branch switching interfere with one another; creating branches from the “current HEAD” also makes it easy to carry stale local state into a new solving run.
- **Baseline drift**: Branches are not created from the latest remote state, so solving results may lag behind `main`, causing frequent merge conflicts.

In addition, the solving process is a black box to users (results appear only after the backend finishes, with no visible progress along the way); once interrupted (by a crash or a manual stop), it cannot resume, leaving users to start over or retain an unfinished PR; runtime exceptions in the CLI directly emit Python tracebacks, creating substantial noise for users ultimately focused on “results.” This feature addresses isolation and drift together through “a separate worktree per issue + pinning to the latest remote baseline,” while also closing three experience gaps: feedback, resumability, and clean error reporting.

## Guide-level explanation

For users, the workflow remains the same—`openagents solve <issue>`—but there are four changes to the underlying behavior and experience:

1. **Isolation**: Each issue has its own worktree at `<repo_root>/.openagents/worktrees/issue-<n>`, with branch `openagents/issue-<n>` created from the latest commit on `origin/main`. To use a different baseline, run `solve --base <ref>` (`main` by default).
2. **Visibility**: During solving, users see assistant text and tool actions (`🔧 <tool>: <hint>`) in real time, and each orchestration stage prints a `▶ …` progress line to stderr.
3. **Resumability**: Rerunning the same issue after an interruption automatically detects the existing branch/PR and resumes work (appending commits and reusing the PR), without recreating them or opening duplicate PRs.
4. **Clean errors**: Runtime errors produce only a single `✗ <reason>` line and a nonzero exit status, without a traceback.

## Reference-level explanation

The changes are divided into 3 Tasks (see the DAG at the end; each Task has a disjoint set of `files`, with a single writer). Note: “Consistent CLI error handling” was originally a separate small Task, but it only changes `cli.py` + `tests/test_cli.py`—both owned by T1, with no files exclusive to that Task—so it is merged into T1 under the single-writer principle.

1. **T1 worktree isolation + baseline pinning + consistent CLI error handling** (no dependencies; the framework)—Rewrite `Orchestrator` workspace logic: `solve` first runs `git fetch origin <base>`, then creates a worktree at `<repo_root>/.openagents/worktrees/issue-<n>` using `git worktree add -b openagents/issue-<n> <path> origin/<base>` (idempotently cleaning up leftovers before creation), invokes the backend, performs `add/commit/push`, and opens a PR within that worktree; `iterate` reuses/recreates the same worktree and continues work. It **no longer** runs `checkout -b` in the main tree and does **not** force-push. The `solve` subcommand in `cli.py` gains `--base` (`main` by default), passed through to `Orchestrator.solve`; an outer handler around dispatch consistently catches `OrchestratorError` / `GithubError` / `RuntimeError`, prints `✗ <message>` to stderr, and returns a nonzero exit code, while unknown exceptions still propagate upward (they are not swallowed).
2. **T2 real-time feedback** (no dependencies; can run in parallel with T1)—Change `ClaudeCodeBackend.run` to use `--output-format stream-json --verbose` + `Popen`, parse NDJSON events line by line, print assistant text and tool actions to stdout in real time, and extract the summary from the `result` event; raise `RuntimeError` (with details) on a nonzero exit status, pass non-JSON lines through unchanged, and use them as fallback details. `Orchestrator` prints `▶ …` progress lines to stderr at each stage. The logic for detecting changes using `git status` remains unchanged.
3. **T3 idempotent, resumable solving** (depends on T1)—At the `solve` entry point, look up persisted state through `state.find_by_issue` and route accordingly: **resume** reuses the existing branch/worktree (without running the cleanup used by the fresh path), appends commits, and uses `find_pr_by_branch` to reuse a PR or open one if missing; **fresh** first records `solving` through `begin_run`, then proceeds to create the worktree/open a PR. `_commit_and_push` tolerates “nothing to commit” (skips the commit but still pushes). Add `begin_run` / `find_by_issue` to `state.py` and `find_pr_by_branch` to `github.py` (fallback PR lookup through gh).

**End-to-end validation**: This group uses `ruff check` / `ruff format --check` / `pytest` (including subprocess-mock unit tests for the Tasks above) as its offline e2e acceptance criteria, with no separate `scripts/*.sh` scripts; acceptance is covered by unit-test assertions such as “the `solve` call sequence includes `git worktree add ... origin/main`,” “resuming reuses the PR,” and “the CLI exits cleanly.”

Dependency DAG: `T1 → T3`; T2 is independent and can run in parallel.

## Drawbacks

- A worktree per issue consumes additional disk space and inodes under `.openagents/worktrees/`; idempotent cleanup before creation is needed to prevent leftovers from accumulating.
- Line-by-line stream-json parsing adds a layer of parsing logic compared with retrieving the result all at once, and non-JSON lines require fallback handling.
- Idempotent resumption introduces fresh/resume routing branches, increasing state-machine complexity.

## Rationale and alternatives

- **Why use git worktree instead of multiple clones**: worktrees share the same `.git` object database, are lightweight to create/delete, and consume far less disk space than multiple clones, making them a natural fit for “a temporary working tree per issue.”
- **Why branch from `origin/<base>` instead of the current HEAD**: Running `fetch` first and then creating a branch from the remote ref ensures that the baseline is the latest trunk and avoids carrying stale local state into the run, eliminating baseline drift at its source.
- **Why rely on State + `find_pr_by_branch` as a fallback instead of purely local records**: A crash can occur between “PR opened” and “state persisted.” Looking up the PR by branch through `gh` can restore the issue↔PR binding when state is missing, avoiding duplicate PRs.
- **Alternative: let the CLI emit tracebacks directly**. Rejected—users focused on “results” only need to know the reason for failure; tracebacks are noise. Consistently catching known exception types while allowing unknown exceptions to propagate preserves both readability and debuggability.

## Prior art

git worktree is the officially recommended mechanism for “multiple working trees in parallel within the same repository” and is widely used to isolate parallel tasks; trunk-based development advocates creating branches from the latest trunk and merging them back after a short lifetime, consistent with this feature’s “baseline pinned to the latest `origin/main`.” stream-json/NDJSON event streams are common real-time output protocols for CLI agent backends.

## Unresolved questions

None. The worktree path layout, baseline ref, fresh/resume routing decisions, and error-handling boundaries have all been settled within this group.

## Future possibilities

- Worktree lifecycle management could be extended to automatic archiving or cleanup based on completion/failure.
- Real-time event streams could be further structured (for example, to supply stage progress to a frontend “results” view).
- The gh fallback in `find_pr_by_branch` could be extended to more scenarios for self-healing issue↔PR state.
