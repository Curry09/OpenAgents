---
number: "0001"
title: "MVP — The minimal bootstrapping loop from a single issue → a single agent → a real PR"
issue: 0
slug: mvp-issue-to-pr-loop
summary: "OpenAgents' minimal viable bootstrapping loop: fetch an issue, assign an agent, and use the Claude Code backend to turn it into a real GitHub PR. Deliver the package skeleton, CLI, backend integration, single-issue orchestration, PR comment messaging mechanism, and results dashboard as the starting point for the entire project."
tasks:
  - id: T1
    title: "Package skeleton + CLI framework + backend interface contract"
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/__init__.py
      - openagents/cli.py
      - openagents/config.py
      - openagents/backends/__init__.py
      - openagents/backends/base.py
      - pyproject.toml
      - tests/test_cli.py
      - tests/test_config.py
      - tests/test_base.py
    scope: "Create the openagents/ package; register five subcommands in cli.py: init/solve/poll/watch/board (lazily import business modules inside command bodies; this subtask provides only a runnable skeleton and placeholders); implement resolve_project/ensure_project in config.py (resolve the git root + remote from cwd, interactively create them if missing, and invoke github.create_repo via a lazy import for gh repo create); define the AgentBackend protocol and AgentResult in backends/base.py; declare the CLI entry point and dependencies in pyproject.toml."
    acceptance: "openagents --help lists the five subcommands; the AgentBackend protocol can be imported; resolve_project identifies the git root and remote from cwd and returns None outside a repository; ensure_project(interactive=False) raises an error when the project is missing (the interactive branch and git init/gh are mocked); ruff check / ruff format --check pass; tests/test_cli.py verifies subcommand registration and preflight calls."
  - id: T2
    title: "Claude Code backend adapter"
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/backends/claude_code.py
      - tests/test_backend_claude_code.py
    scope: "Implement ClaudeCodeBackend to invoke Claude Code non-interactively as a subprocess, modify code in the given working directory according to the task description, and return AgentResult."
    acceptance: "Given a temporary repository and a task, the adapter can drive Claude Code to produce file changes and correctly report changed/summary; unit tests with mocked subprocess calls pass."
  - id: T3
    title: "GitHub integration (issue/PR/comment)"
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: "Wrap the gh CLI to implement create_repo (for cold-start binding)/get_issue/create_pr/list_comments/post_comment/check_status (CI status), with consistent error handling."
    acceptance: "Each function correctly parses gh output into data classes; create_repo correctly assembles gh repo create arguments (private/public); check_status correctly classifies pass/fail and extracts a summary of failure logs; unit tests with mocked gh subprocesses cover normal and error paths."
  - id: T4
    title: "Single issue → single agent orchestration + state"
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - openagents/state.py
      - tests/test_orchestrator.py
      - tests/test_state.py
    scope: "Implement Orchestrator.solve (fetch issue → create branch → invoke backend → open PR → write State) and iterate (feed comments back → append commit → push); implement JSON persistence for State (.openagents/state.json), including a state machine (including done) and a comment cursor."
    acceptance: "With mocked backend + github, solve produces one RunRecord end to end with correct state transitions; unit tests for State reads/writes and cursor logic pass."
  - id: T5
    title: "PR comment messaging mechanism"
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
    scope: "Implement Messages.poll: for each open PR, first check whether it has been merged (if merged → set to done and skip); otherwise, (a) read CI status and, on failure, trigger iterate(reason=\"ci\") with the failure logs (fix until all CI checks are green); (b) compare against the cursor, trigger iterate(reason=\"comment\") for new comments, and update the cursor. Implement Messages.watch: repeatedly call poll at the specified interval."
    acceptance: "Given a mock PR with a new comment, poll correctly triggers iterate(reason=\"comment\") once and advances the cursor; a mock PR with failing CI triggers iterate(reason=\"ci\"), while all-green CI does not; merged PRs are set to done and undergo no further iterations; no iteration is triggered when there are no new comments and CI is green; unit tests for watch's loop interval logic (with time.sleep mocked) pass."
  - id: T6
    title: "Results dashboard + local launch command"
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/results.py
      - openagents/templates/board.html
      - tests/test_results.py
    scope: "Implement results.render(runs)->html and the board() startup logic (render State as a single HTML page and open it with webbrowser); provide an HTML template."
    acceptance: "Given several RunRecord instances, render produces HTML containing issue titles/statuses/PR links; the board command can generate the file and trigger opening it locally (the open action is mocked in tests); unit tests pass."
---

# 0001 · MVP — The minimal bootstrapping loop: single issue → single agent → real PR

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

The minimal viable bootstrapping loop for OpenAgents: start from a GitHub issue, assign a single agent (with Claude Code as the backend) to modify code in an isolated working directory, produce a **real** GitHub PR, and drive iterations through comments and CI status on the PR until it is merged; persist all runtime state in `.openagents/state.json` and render it as a single-page results board. This group delivers the package skeleton, CLI framework, backend interface contract, Claude Code adapter, GitHub integration, single-issue orchestration, messaging mechanism, and board across 6 Tasks, providing the starting point for the entire project to "iterate on itself."

## Motivation

OpenAgents aims to use multi-agent collaboration to free people from code details so they can focus on high-level oversight, and this system itself is the product it is meant to deliver. The first step must therefore be to build a minimal skeleton that can complete the "issue→PR" flow, then use that skeleton to iterate on itself.

Before implementing full multi-agent collaboration, the most critical individual path must first be proven viable: **one issue, one agent, one real PR**. Once this loop is closed, the system gains the bootstrapping capability to "fetch an issue→modify code→open a PR→iterate on feedback→merge." Subsequent multi-agent parallelism, reviewer gates, releases, and other capabilities all build on this foundation. This group deliberately implements only this minimal loop (Occam's razor: do not multiply entities beyond necessity), without introducing heavier mechanisms such as multi-agent scheduling or parallel arbitration.

## Guide-level explanation

From the user's perspective, the interface is a set of CLI subcommands:

- `openagents init` — Bind the current directory to a GitHub repository (resolve the git root + remote; interactively create a repository if missing).
- `openagents solve <issue>` — Fetch the issue, create a working branch, invoke the backend (Claude Code) to modify code, open a real PR, and record this run in State.
- `openagents poll` / `openagents watch` — Poll / continuously watch open PRs: mark merged PRs as `done`; use failure logs to trigger an iteration for PRs with failing CI and fix them until all checks pass; feed new comments back to the agent so it can add commits.
- `openagents board` — Render State as a single-page HTML results board and open it in a browser, showing each issue's title, status, and PR link.

The core mental model: **one issue corresponds to one run, and one run corresponds to one PR**; people view the board (results) and leave comments on PRs when necessary, rather than intervening at the code level. The agent iterates when it receives a comment.

## Reference-level explanation

At the code level, this is divided into 6 Tasks (`files` are mutually exclusive, with a single writer for each Task; see the DAG at the end):

1. **T1 Package skeleton + CLI framework + backend interface contract** — Create the `openagents/` package; register the five subcommands `init`/`solve`/`poll`/`watch`/`board` in `cli.py`, with **deferred imports** of business modules inside command bodies (keeping the skeleton runnable and decoupling module loading). In `config.py`, `resolve_project`/`ensure_project` handle project binding: resolve the git root + remote from cwd; if missing and `interactive=True`, interactively create a repository (`gh repo create` is invoked through a deferred import of `github.create_repo`); if missing and `interactive=False`, raise an error. `backends/base.py` defines the `AgentBackend` protocol and `AgentResult` dataclass as the contract for all backend adapters (supporting different cli-agents such as Claude Code / Codex). `pyproject.toml` declares the CLI entry point and dependencies.
2. **T2 Claude Code backend adapter** (depends on T1) — Implement `ClaudeCodeBackend`, invoking Claude Code **non-interactively** as a subprocess to modify code according to a task description in the given working directory, and returning `AgentResult(changed, summary, ...)`. This is the first concrete implementation of the `AgentBackend` protocol.
3. **T3 GitHub integration** (depends on T1) — Wrap the `gh` CLI: `create_repo` (for initial binding from a cold start)/`get_issue`/`create_pr`/`list_comments`/`post_comment`/`check_status`. `check_status` reads CI status, classifies it as pass/fail, and extracts a summary of failure logs, providing the data for subsequent "CI failure triggers iteration" behavior; all functions use consistent error handling and parse `gh` output into dataclasses.
4. **T4 Single issue → single agent orchestration + state** (depends on T2, T3) — `Orchestrator.solve`: fetch the issue→create a branch→invoke the backend→open a PR→write State, producing a `RunRecord` end to end. `Orchestrator.iterate`: feed incoming comments / CI failure logs back to the backend, add commits, and push (this is the mechanism by which agents resume work after "receiving a comment message"). `State` is persisted in `.openagents/state.json` and includes a state machine (including the terminal state `done`) and a comment cursor (recording which comment has been processed so far to avoid duplicate triggers).
5. **T5 PR comment messaging mechanism** (depends on T3, T4) — For each open PR, `Messages.poll` first checks whether it has been merged; if merged→mark it `done` and skip it; otherwise, (a) read CI status and, on failure, trigger `iterate(reason="ci")` with the failure logs to fix CI until all checks pass; (b) compare against the cursor, trigger `iterate(reason="comment")` when new comments are found, and advance the cursor. `Messages.watch` repeatedly calls `poll` at a fixed interval (`time.sleep` is mocked in tests). This layer turns "a PR receives a comment / CI changes" into calls to `iterate`, providing the minimal implementation of OpenAgents' GitHub-comment-style messaging mechanism.
6. **T6 Results board + local launch command** (depends on T4) — `results.render(runs) -> html` renders the `RunRecord` entries in State as a single-page HTML document (including issue titles/statuses/PR links); `board()` generates the file and opens it with `webbrowser`; provide the `templates/board.html` template. The frontend is used only to present results (centered on results, with people performing acceptance based on results rather than code details).

**Dependency DAG**: `T1 → T2`, `T1 → T3`, `T2,T3 → T4`, `T3,T4 → T5`, `T4 → T6`. T1 is the root; T2 and T3 can run in parallel after T1; T4 brings together T2/T3; T5 and T6 follow T4 (and T3).

This group implements a minimal loop. End-to-end verification is covered by the mocked unit tests for each Task (backend / github / subprocesses / `time.sleep` / `webbrowser` are all stubbed); no separate `scripts/*.sh` e2e scripts are specified.

## Drawbacks

- Supports only serial single issue → single agent execution, without multi-agent parallelism or reviewer arbitration, limiting throughput and collaboration capabilities—but this is a deliberate MVP tradeoff, with subsequent specs building on this foundation.
- Strongly depends on the external `gh` CLI and Claude Code executable, which must be preinstalled in the runtime environment.

## Rationale and alternatives

- **Why start with the minimal single-issue loop**: Bootstrapping requires the shortest working path. Closing the issue→PR→iteration→merge loop first provides the vehicle for "using OpenAgents to iterate on OpenAgents"; multi-agent parallelism is a subsequent addition, and introducing it prematurely would increase the blast radius and violate Occam's razor.
- **Use a protocol + adapter (`AgentBackend`) for the backend instead of hardcoding Claude Code**: Decentralization requires allowing different agents in the same project to use different underlying coding agents (Claude Code / Codex / nexau…). Define the contract first (T1), then implement the first backend (T2), allowing subsequent backends to integrate at zero cost while keeping modules decoupled.
- **Defer imports of business modules until inside CLI subcommand bodies**: Keep `--help`/the skeleton runnable when dependencies are not yet ready, and decouple the loading of business modules to avoid coupling cycles caused by top-level imports.
- **Persist State as JSON + a comment cursor**: Use the simplest file-based persistence to support the state machine, with the cursor preventing repeated processing of the same comment; there is no need to introduce a database (YAGNI).
- **Use single-page static HTML for the board + open it locally with `webbrowser`**: Present results at minimal cost, without introducing a frontend framework or server.

## Prior art

Draws on GitHub's PR + comment collaboration model: use a PR to represent a delivery, and comments as the vehicle for feedback and messages between agents ("your PR received a comment"). The backend's protocol + adapter structure follows the approach used by interactive coding agents such as cursor / windsurf to support multiple backends.

## Unresolved questions

None. This group's scope is limited to the minimal single-issue loop; multi-agent parallelism, reviewer gates, releases, and other capabilities are left to subsequent specs.

## Future possibilities

- Issue-level parallelism: assign one agent to each of multiple issues simultaneously.
- Feature-level multi-agent collaboration: multiple agents collaborate within the same feature (reviewer arbitration and aggregation, etc.).
- Extend backends to support more cli-agents, such as Codex / nexau.
- Upgrade the board from static HTML to an interactive frontend that presents more dimensions of results.
