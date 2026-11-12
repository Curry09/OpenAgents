---
number: "0070"
title: "openagents self-update precheck: check for and pull the latest version before every command (snapshot reinstall + re-execution)"
issue: 146
slug: self-update-precheck
summary: "Insert a self-update precheck before every execution of the openagents entry point: check whether the recorded branch is behind the source repository's remote (use git fetch to compare the local ref with remote/branch). If it is behind and an update is safe (current branch == recorded branch and the working tree is clean), run git pull --ff-only → uv tool install --force → os.execvp to re-execute the original command; if pulling fails or updating is unsafe, print actionable guidance and fail open to continue. Never block routine commands, switch branches, or modify a dirty working tree. Record the source repository path in ~/.openagents/source.json (default origin/main; OPENAGENTS_HOME can override the home directory); automatically detect and persist it when any command runs inside the source repository. Use OPENAGENTS_SELFUPDATE_DONE=1 as a re-execution guard to prevent loops, and OPENAGENTS_NO_SELF_UPDATE=1 as a hard switch to disable the entire precheck (for CI/tests). Implement the core logic as pure functions with injectable dependencies; keep tests hermetic by stubbing subprocess/execvp without accessing real git/uv/the network."
e2e:
  intent: "Prove that the wiring for the “self-update precheck before every command at the openagents entry point” works through an offline, deterministic verification path with zero regressions—the precheck is a pure function with injectable dependencies (run/execvp/environ/stderr are all injected externally); the DISABLE/DONE guards short-circuit, as does the absence of source.json; when behind and safe, it completes the full cycle (pull --ff-only → uv tool install --force → execvp with DONE=1 set); unsafe conditions or any exception always fail open, printing a notice and continuing; cli.main() calls precheck before parse_args, and normal invocation behavior remains unchanged verbatim."
  method: "Form: pure CLI/backend wiring, with no navigable product-facing frontend; the available self-check tools do not include Playwright / Chrome DevTools MCP, so no browser e2e is defined. Offline deterministic testing is used instead (following the same approach as Spec-0064/0066/0067/0069):\n1. Targeted selfupdate pytest tests (inject fake run/execvp; hermetic, without touching real git/uv/network/shell): precheck is a complete no-op under DISABLE/DONE; no-op when source.json is absent; behind + safe → record pull --ff-only / uv tool install --force / execvp in order, with OPENAGENTS_SELFUPDATE_DONE=1 in the execvp environment; behind but current branch ≠ recorded branch / dirty working tree / fetch raises an error → print a notice and do not exec (fail-open); detect_source_repo writes to disk inside the source repository, but does not write to disk inside the target project; OPENAGENTS_HOME overrides home.\n2. CLI wiring pytest tests: main() calls selfupdate.precheck exactly once before parse_args; when precheck is stubbed as a no-op, main([]) still returns 2 (normal behavior unchanged).\n3. grep anchors (e2e script): cli.py contains a selfupdate.precheck call; selfupdate.py contains OPENAGENTS_NO_SELF_UPDATE / OPENAGENTS_SELFUPDATE_DONE / --ff-only / execvp; tests/conftest.py contains OPENAGENTS_NO_SELF_UPDATE.\nScript: scripts/e2e-spec-0070-self-update-precheck.sh (ruff check + ruff format --check + targeted pytest tests + grep anchors), collected by the PR e2e signpost.\n"
tasks:
  - id: T1
    title: "Self-update precheck module + main() wiring + hard network isolation for tests"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/selfupdate.py
      - openagents/cli.py
      - tests/conftest.py
      - tests/test_selfupdate.py
    scope: "Add openagents/utils/selfupdate.py (pure functions + injectable run/execvp seam): home_dir/source_config_path (respecting OPENAGENTS_HOME), SourceConfig(repo_path/remote=origin/branch=main), load/save_source_config, detect_source_repo (cwd is inside the OpenAgents source repository → persist to disk), and precheck(argv,environ,run,execvp,stderr) orchestration: short-circuit on DISABLE/DONE → automatically detect and persist → short-circuit if source.json is absent → git fetch (fail open on timeout) → compare to determine whether the branch is behind → if safe (current branch == recorded branch and the working tree is clean), run pull --ff-only + uv tool install --force + execvp to re-execute (set DONE=1) / if unsafe, print actionable guidance and fail open to continue; fail open on any exception without ever blocking execution. Call selfupdate.precheck(argv=...) in cli.main() before parse_args (only for the openagents entry point; do not wire it into the standalone spec command). In tests/conftest.py, globally set OPENAGENTS_NO_SELF_UPDATE=1 in an autouse fixture to ensure zero regressions in existing tests and no network access."
    acceptance: "uv run pytest tests/test_selfupdate.py passes: with the DISABLE/DONE environment variables set, precheck is a complete no-op (no fetch, no exec); without source.json, it is a no-op; behind + safe → run pull --ff-only/uv tool install --force/execvp in order and set OPENAGENTS_SELFUPDATE_DONE=1; behind but current branch ≠ recorded branch or working tree is dirty → print guidance and continue without exec (fail open); git fetch/subprocess raises an exception → print guidance and continue without exec (fail open, do not propagate the exception); detect_source_repo persists source.json inside the source repository but does not persist it inside the target project; OPENAGENTS_HOME overrides the home path. The autouse fixture in tests/conftest.py sets DISABLE=1, and the full existing pytest suite still passes. ruff check/format are clean."
---

# 0070 · openagents Self-Update Precheck: Detect and Pull the Latest Version Before Every Command (Snapshot Reinstallation + Re-execution)

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

`openagents` is installed via `uv tool install --from . openagents` and runs a **uv tool snapshot**
(`~/.local/bin/openagents`), **not** the live code in the git worktree. After a `git pull` of the source, the snapshot still runs old code;
it must be reinstalled with `uv tool install --force` to update. OpenAgents itself is a product being dogfooded and continuously iterated on, so users can easily
run an old version that is several commits behind without realizing it.

This spec inserts a **self-update precheck before every command execution at the `openagents` entry point**
(the pure function `precheck` in the new module `openagents/utils/selfupdate.py`,
called by `cli.main()` before `parse_args`):

1. **Detect** whether the recorded branch is behind the source repository's remote (after `git fetch`, compare the local `<branch>` ref with `<remote>/<branch>`).
2. When it is behind and **safe to update**, complete the full cycle: `git pull --ff-only` → `uv tool install --force` → `os.execvp`
   to **re-execute** the original command, so the user's current invocation immediately runs the latest code.
3. If pulling fails or updating is unsafe, print an **actionable error message** directing the user to update manually, then **fail open and continue executing** the current command.

The source repository path is recorded in `~/.openagents/source.json` (defaults: `origin` / `main`; `OPENAGENTS_HOME` can override the location)
and is automatically detected and persisted when any command is run inside the source repository. `OPENAGENTS_SELFUPDATE_DONE=1` is the loop guard for re-execution, and `OPENAGENTS_NO_SELF_UPDATE=1`
is the hard switch that disables the entire precheck (for CI / tests / hermetic environments). The core logic consists of pure functions, the `run` / `execvp` seams are injectable, and all tests are hermetic.

## Motivation

### Verification of the Current State

- `[project.scripts]` in `pyproject.toml` installs `openagents = "openagents.cli:main"` as a console_script;
  actual distribution uses `uv tool install`, which runs a **snapshot taken at installation time**, decoupled from the source worktree.
- `main()` in `openagents/cli.py` currently consists of `parser = build_parser(); argcomplete...; args = parser.parse_args(argv)`
  (Spec-0069 already inserted an argcomplete hook before `parse_args`), with **no self-update check at all**.
- There is no `selfupdate.py` under `openagents/utils/`; the `~/.openagents/` namespace is already used by `agent_config` /
  `fleet_config` (`Path(raw_path).expanduser()`) and others, but there is no record for locating the source repository.

### Why This Is Needed

OpenAgents is continuously iterated on and dogfooded by itself. The **hidden trap** of decoupling the snapshot from the source means that after a source `git pull`, the `openagents`
command still silently runs the old snapshot. Users are often several commits behind without knowing it—bugs that have already been fixed still reproduce, and newly merged commands “do not exist.”
What is missing is a precheck that “automatically ensures the latest version runs every time a command is used.” This is precisely what is required to match
the smooth interaction of cursor/windsurf (automatically staying up to date), and it also fits this repository's orientation toward “focusing on outcomes, with humans providing high-level oversight”: keeping the version current should not be a cognitive burden on users.

### Constraints (Restated Here from the Original Text of Issue #146)

- **Source repository location**: The running snapshot does not know where the source is (cwd is usually the *target* project rather than the OpenAgents source repository). Record
  the source repository path / remote / branch in `~/.openagents/source.json` (defaults: `origin` / `main`); automatically detect and persist them
  when any command is run inside the OpenAgents source repository (self-configuration), with an explicit override supported via `OPENAGENTS_HOME`.
- **cadence = every invocation, fail-open**: Check on every invocation; any `git fetch` / network / subprocess failure only produces a non-blocking message and execution continues,
  **never blocking** the actual command (usable offline).
- **Protect developers' WIP**: The source repository is often on a feature branch / has uncommitted changes. Automatically run `pull --ff-only` only when “current branch == recorded branch” and “the worktree
  is clean”; otherwise, treat updating as unsafe and use “message + continue,” **never switching branches or touching a dirty worktree**.
- **Loop prevention for re-execution**: Set `OPENAGENTS_SELFUPDATE_DONE=1` when re-executing after reinstallation, so the child process skips the precheck and infinite self-update loops are prevented.
- **Can be disabled**: The hard switch `OPENAGENTS_NO_SELF_UPDATE=1` disables the entire precheck (for CI / tests / hermetic environments); the precheck applies only to
  the `openagents` entry point and does not affect the standalone `spec` command.
- **Occam's razor**: Do not introduce a configuration framework or add a networking library; run git / uv entirely through subprocesses; keep the core logic as injectable pure functions and the tests hermetic.
- **Zero regressions**: Behavior on the default path (already up to date / no source.json) remains unchanged; add `tests/conftest.py` to globally set
  `OPENAGENTS_NO_SELF_UPDATE=1` so existing tests do not access the network.

## Guide-level explanation

**From an ordinary user's perspective**: The first time you run any `openagents` command inside the OpenAgents source repository, the precheck automatically records the source repository path in
`~/.openagents/source.json`. After that, when you run `openagents <command>` in **any directory** (usually your target project), the precheck will:

- If you are already up to date → remain completely unobtrusive; the command runs as usual.
- If you are behind and the source repository is on a clean `main` → automatically run `git pull --ff-only` + `uv tool install --force`,
  then **immediately rerun the current command with the new version**; you will only see two additional lines indicating “New version detected, updating…”.
- If you are behind but the source repository is on a feature branch or has uncommitted changes → the precheck **never touches your worktree** and only prints an actionable message:

  ```
  ⚠ openagents is behind the source repository's remote, but automatic updating is currently unsafe (branch/worktree).
    Update manually: git -C <src> pull --ff-only && uv tool install --force --from <src> openagents
  ```
  Then it **fails open and continues** running your original command.

- Offline / `git fetch` fails → likewise, only print a non-blocking message and continue, never blocking execution.

**Turn it off**: `export OPENAGENTS_NO_SELF_UPDATE=1` (CI / tests / situations where you do not want to fetch every time).

**Applies only to the `openagents` entry point**: The standalone `spec` console_script does not invoke the precheck (it is a purely local tool with no self-update semantics).

## Reference-level explanation

### New Module `openagents/utils/selfupdate.py`

Pure functions + injectable seams (`run` defaults to `subprocess.run`, `execvp` defaults to `os.execvp`, `environ` defaults to `os.environ`,
and `stderr` defaults to `sys.stderr`) keep tests hermetic, without accessing real git / uv / network / shell. Key constants and APIs:

```python
DISABLE_ENV = "OPENAGENTS_NO_SELF_UPDATE"   # Hard switch: any nonempty value → the entire precheck is a no-op
DONE_ENV    = "OPENAGENTS_SELFUPDATE_DONE"  # Re-execution guard: the re-executed child process carries it → skip the precheck to prevent loops
HOME_ENV    = "OPENAGENTS_HOME"             # Override the ~/.openagents location
_GIT_NET_TIMEOUT_SECONDS = 30               # Mirror utils.git; safeguard against a hung git fetch, failing open on timeout

@dataclass(frozen=True)
class SourceConfig:
    repo_path: str
    remote: str = "origin"
    branch: str = "main"

def home_dir(*, environ) -> Path          # OPENAGENTS_HOME or ~/.openagents
def source_config_path(*, environ) -> Path
def load_source_config(*, environ) -> SourceConfig | None   # Missing file/invalid JSON → None (fail-open)
def save_source_config(*, config, environ) -> None
def detect_source_repo(*, cwd, run, environ) -> Path | None # cwd is inside the OpenAgents source repository → persist and return toplevel
def precheck(*, argv, environ, run, execvp, stderr) -> None # Sole orchestration entry point; never raises (fail-open)
```

**`precheck` orchestration (the order determines short-circuit priority)**:

1. `DISABLE_ENV` is nonempty → return immediately (hard switch).
2. `DONE_ENV` is nonempty → return immediately (re-execution guard, preventing loops).
3. `detect_source_repo`: If cwd's git toplevel is the OpenAgents source repository (`openagents/cli.py` exists under toplevel
   and `pyproject.toml` declares the `openagents` entry point) → use it to call `save_source_config` (idempotent self-configuration).
4. `load_source_config`: No `source.json` → return (no command has yet been run inside the source repository, so there is no basis for detection; remain silent and unobtrusive).
5. `git -C <src> fetch <remote> <branch>` (with the `_GIT_NET_TIMEOUT_SECONDS` timeout); any nonzero exit status/timeout/exception →
   print a non-blocking message and return (fail-open, usable offline).
6. Compare: `git rev-parse <branch>` vs `git rev-parse <remote>/<branch>`, and run `git rev-list --count
   <branch>..<remote>/<branch>`; count == 0 (not behind) → return.
7. **Safety gate**: `git rev-parse --abbrev-ref HEAD == <branch>` and `git status --porcelain` is empty. If these conditions are not met
   → print an actionable message and return (fail-open, **never switch branches or touch a dirty worktree**).
8. `git -C <src> pull --ff-only <remote> <branch>`; failure → print a message and return (fail-open).
9. `uv tool install --force --from <src> openagents`; failure → print a message and return (fail-open).
10. `execvp(argv[0], argv)`, with `DONE_ENV=1` injected into the environment—re-execute the original command using the latest snapshot. **Exceptions from any step are always
    caught by the outermost handler and converted into a non-blocking message + return**; `precheck` never raises to its caller.

### `cli.main()` wiring (the only integration point)

`main()` calls `selfupdate.precheck` before `parse_args` (after the argcomplete hook and before `parse_args`—
during the completion handshake, argcomplete has already called `exit`, so execution never reaches the precheck; the precheck runs only during normal execution):

```python
def main(argv=None) -> int:
    parser = build_parser()
    if argcomplete is not None:
        argcomplete.autocomplete(parser)
    from openagents.utils import selfupdate
    selfupdate.precheck(argv=sys.argv)   # Self-update precheck before every command; fail-open, never raises
    args = parser.parse_args(argv)
    ...
```

Wire this into the `openagents` entry point only; **do not wire it into** the `spec` command in `openagents/spec/cli.py` (constraint: applies only to the openagents entry point).
Pass `sys.argv` to `precheck` (re-execution requires the complete process argv, not the optional test argument to `main(argv)`).

### Global offline guard in tests/conftest.py

The existing `tests/conftest.py` already has an autouse fixture that acts as a “hard offline gate” (blocking real `gh` invocations). This spec adds an autouse fixture
(or adds to the existing fixture) that calls `monkeypatch.setenv(selfupdate.DISABLE_ENV, "1")`, ensuring that the entire precheck is a no-op
when **the entire existing test suite** imports/calls `cli.main`, with zero regressions and no network access.

### DAG + file allocation

A single Task (cohesive changes, four non-overlapping files, no internal dependencies):

| Task | Title | files | depends-on |
| --- | --- | --- | --- |
| T1 | Self-update precheck module + main() wiring + hard offline gate for tests | `openagents/utils/selfupdate.py`, `openagents/cli.py`, `tests/conftest.py`, `tests/test_selfupdate.py` | — |

### e2e script

`scripts/e2e-spec-0070-self-update-precheck.sh` (offline and deterministic: ruff check + ruff format --check + targeted
pytest + grep anchors), collected by the PR e2e signpost. This consists entirely of CLI/backend wiring, with no navigable product-facing frontend, so no
browser e2e is provided (see frontmatter `e2e.method`).

## Drawbacks

- Every `openagents` command adds one `git fetch` (a network round trip; the source repository is on local disk, and fetching one branch is usually fast; a timeout fallback
  + fail-open behavior ensure that offline operation/slow networks do not block execution, but this does add a network call). Disable it with `OPENAGENTS_NO_SELF_UPDATE=1`.
- Automatic re-execution with `execvp` imposes the implicit cost of “running the command twice” on the user (the first run performs only the precheck before re-executing)—but this happens only when the installation is actually behind
  and updating is safe, and the re-executed child process carries `DONE=1` and skips the precheck, so re-execution occurs at most once.
- Detecting the source repository depends on “having run any command at least once inside the source repository” to persist `source.json`; if no command has ever been run inside the source repository, there is no way to detect it
  (silently stays out of the way; this is not a defect; see Unresolved).

## Rationale and alternatives

- **Choose “a pure precheck function at the entry point + injectable seams” (this proposal)**: the logic is kept together in one utils module, and `cli.main` gains only two lines;
  git/uv operations all use subprocesses (no added networking library or configuration framework, consistent with principle 1, Occam’s razor); injecting `run`/`execvp` makes tests 100% hermetic.
- **Alternative ①: automatic updates through a package manager/background daemon**—introduces a persistent process or a third-party auto-updater, is heavyweight, and does not fit the model in which “the snapshot runs against the local source repository”;
  rejected.
- **Alternative ②: only print a “new version available” notice, without updating automatically**—loses the value of the complete “run the latest version immediately for this invocation” loop (the user still completes this invocation on the old version),
  and the issue explicitly requires the complete pull + reinstall + re-execute loop; rejected (but this is precisely the fail-open behavior of the **cannot update safely** branch).
- **Alternative ③: perform updates in a shell wrapper / rc**—changes the user’s shell configuration, varies across shells, and has substantial side effects; rejected (the same tradeoff as Spec-0069
  regarding automatic injection of argcomplete into rc).
- **Use “current branch == recorded branch AND working tree is clean” as the safety gate, rather than automatically updating with `git stash`/branch switching**: never touching a developer’s WIP is a hard
  constraint—it is preferable to skip the update (with a fail-open notice) than to lose uncommitted changes or switch away from the current branch because of self-updating.

## Prior art

- **Re-execution with `os.execvp`** is a standard technique for CLI self-updates/self-restarts (such as rerunning after a `pyenv`/`rustup` self-update;
  the official Python documentation for `os.execvp` explains that the process image is replaced while the PID stays the same)—it makes “the update take effect immediately for this invocation” without requiring the user to
  manually enter the command again.
- **`uv tool install --force`** is the method documented by astral `uv` for “reinstalling/updating an installed tool.” This repository’s CLAUDE.md
  and existing practice (memory: the openagents CLI is a uv tool snapshot; after changing code, reinstall with `uv tool install --force --editable .`)
  both corroborate this snapshot model.
- **`git pull --ff-only`** is a conventional safe-update approach that “updates only when a fast-forward is possible, otherwise refusing” (official git documentation), matching the constraints to “never create
  merge commits and never touch a diverged working tree.”
- This repository already has a precedent for adding a timeout + fail-open behavior to network git subprocesses (Spec-0035 `_GIT_NET_TIMEOUT_SECONDS=30`); this module
  mirrors that constant and the same fail-open approach.

## Unresolved questions

- Users who **have never run any command inside the source repository** (installed an openagents snapshot directly in a target project and never used cd to enter the source repository) → no
  `source.json`, so the precheck silently does nothing. Should `oa init` or another location explicitly persist the source path as an additional measure? The preference is not to do this (to preserve simplicity under Occam’s razor; self-detection
  already covers the vast majority of dogfooding workflows), leaving it for the future.
- Should “fetch on every invocation” be throttled to “at most once every N minutes” (by recording a `last_check` timestamp) to save network round trips? This spec follows the issue’s
  “cadence=every invocation” requirement and does not throttle; if measurements show significant fetch overhead, throttling can be added in the future.

## Future possibilities

- Record a `last_check` timestamp to throttle fetches (a natural extension of Unresolved above).
- Also wire an (optional) version freshness notice into the separate `spec` entry point (this spec explicitly covers only the `openagents` entry point).
- Include a change summary from `git log <old>..<new> --oneline` in the post-update notice so users know what the update brought.
