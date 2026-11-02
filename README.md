# OpenAgents

English | [简体中文](README.zh-CN.md)

**A spec-driven framework for multi-agent software delivery.** OpenAgents takes issues through specifications, implementation, acceptance checks, review, and PR merging. It supports GitHub/Gitea and Claude Code, Codex, and NexAU backends. Agents run the quality gates by default, and PRs are merged automatically; `release: manual` only means that a person decides when to publish a release.

This CLI can run independently or serve as the delivery plane for auto-designer. Python 3.12+ · MIT.

For integration with auto-designer, see the [joint usage guide](docs/AUTO_DESIGNER.md) (Chinese). The v0.2 functionality has been merged into `main`, which supports multiple flows. The runtime still defaults to `standard`; configure `v0.2` explicitly to use it. See [Contributing](CONTRIBUTING.md) for development installation and offline tests, and the [release guide](docs/RELEASING.md) (Chinese) for release status. The desktop app remains experimental.

---

## Quickstart: standalone GitHub + Claude Code

```bash
# 1. Install from the repository root (add --force after changing the source)
uv tool install --from . openagents

# 2. Authenticate with GitHub (Gitea uses an environment token; see the joint guide)
gh auth login && gh auth status

# 3. Bind the project from the target repository root
openagents init

# 4. Create a requirement (automatically adds the openagents discovery label)
openagents issue "Your requirement"

# 5. Start unattended delivery through to merging
#    --parallel 4 allows up to 4 concurrent subjects; --once runs one cycle and exits
openagents vigil
```

> `vigil` / `issue` perform real operations: they can invoke Claude to change code and use `gh` to open PRs or post comments. Try them in a practice repository first.

---

## Prerequisites

- **Python 3.12+** and [uv](https://docs.astral.sh/uv/).
- **An authenticated [`gh` CLI](https://cli.github.com/)**: sign in with `gh auth login` and verify with `gh auth status`.
  GitHub authentication is delegated to `gh`. The Gitea backend reads the environment variable named in the configuration; the YAML does not store the token itself.
- **The [`claude` CLI](https://docs.claude.com/claude-code)** for the default coding backend.

---

## Installation

```bash
uv tool install --from . openagents
```

After installation, `openagents` is available from any directory. Reinstall with `--force` after changing the source:

```bash
uv tool install --force --from . openagents
```

> `openagents` runs from a uv tool snapshot. Editing the source without reinstalling leaves the command running the old code.

The optional NexAU backend is pinned to commit `28511d9f0362191a6c378fd441b2be55309a9e32` of [hzhua/nexau](https://github.com/hzhua/nexau). Run `uv sync --locked --extra nexau` in this repository, or install the OpenAgents wheel with the `nexau` extra, to fetch that fixed Git version. This repository does not embed a copy of the SDK source.

### Optional shell completion

OpenAgents includes [argcomplete](https://github.com/kislyuk/argcomplete). Completions read the command definitions directly and cover the subcommands (`init`, `vigil`, `backfill-rfc`, `issue`, `release`, `board`, and `report`) and their options, such as `vigil --interval/--label/--base/--once/--parallel/--skip/--config`. Once enabled, use `openagents <Tab>` or `openagents vigil --<Tab>` to see candidates.

For zsh, add to `~/.zshrc`:

```zsh
autoload -U bcompinit && compinit
eval "$(register-python-argcomplete openagents)"
```

For bash, add to `~/.bashrc`:

```bash
eval "$(register-python-argcomplete openagents)"
```

> Completion is optional. Argcomplete only participates during a completion request and does not affect ordinary command invocation. `register-python-argcomplete` is installed with the argcomplete dependency.

---

## Usage

Common commands cover project setup, requirements, automated delivery, specification backfilling, releases, and read-only observation:

```bash
openagents init                 # Bind the current directory to a repository (once)
openagents issue "Your requirement" # Create an issue with the openagents discovery label
openagents vigil                # Discover, dispatch, open PRs, and monitor through merging
openagents vigil --parallel 4   # Advance up to 4 issues/PRs concurrently
openagents backfill-rfc <path>  # Infer specs from existing code and open a draft PR
openagents release              # Create a version from the current main HEAD
openagents board                # Open the local results dashboard (read-only)
```

> Earlier manual commands such as `rfc`, `implement`, `iterate`, `poll`, `watch`, and `fleet` have been consolidated into `vigil`. These steps now run automatically within its reconciliation cycle (Spec-0064).

### `init`: bind a project

Bind or initialize the current directory as an OpenAgents project and ensure the workflow labels exist. If Git or a remote is missing, the command prompts you to create it. Every command except `board` performs this binding preflight. A new repository can start directly with `vigil`, without running `init` first: it bootstraps workflow labels before entering the main loop.

### `issue`: create a requirement

```bash
openagents issue "Support CSV export"       # Restate the request and ask for confirmation
openagents issue "Fix login timeout" --yes # Skip confirmation for automation
```

Create an issue in the current repository with the `openagents` discovery label so that `vigil` can discover and dispatch it. You can also create an issue in the GitHub UI and add the `openagents` label manually.

Common options: `--body <text>`, repeatable `--label <label>`, and `--yes` to skip confirmation.

### `vigil`: unattended delivery

`vigil` runs the complete loop: discover labeled issues, dispatch work, draft RFCs and open PRs, monitor comments/conflicts/CI/e2e/review, iterate, and merge. Agents execute the quality gates by default.

```bash
openagents vigil                          # Read .openagents/openagents.yml; serial, 60s interval by default
openagents vigil --once                   # Run one cycle, drain the queue, and exit
openagents vigil --parallel 4             # Run agents for up to 4 subjects concurrently
openagents vigil --label bug --label p0   # Override discovery labels (repeatable)
openagents vigil --interval 30            # Override the polling interval in seconds
openagents vigil --base develop           # Override the base branch for dispatched work
openagents vigil --skip ci,e2e            # Skip stages for this run; equivalent to stages.<stage>=skip
```

`--skip`, `--base`, `--interval`, and `--label` override a single run. They do not modify `openagents.yml` on disk.

#### Graph-driven, level-triggered reconciliation

The scheduler, `recipes.vigil.run_vigil`, uses graph-driven, level-triggered reconciliation (Spec-0065), rather than separate discovery and monitoring batches:

- **The scheduling unit is a subject**, such as `issue:5` or `pr:12`, rather than an event. `--parallel K` sets the concurrency limit; serial execution is simply `K=1`. The issue dependency graph (GitHub's native `blocked_by`) further constrains which work can run concurrently.
- **The producer feeds persistent workers.** On each tick, the main thread reads current GitHub state and queues eligible subjects. The K workers advance PRs until they must wait. SQLite `BEGIN IMMEDIATE` serializes concurrent writes to `work_queue`, without in-process locks. There is no batch barrier: a worker takes the next queued item as soon as it finishes, so slow tasks do not leave other slots idle.
- **Level-triggered means deciding from current state.** Predicates ask whether work is needed now, rather than whether something changed since the last tick. They are recomputed for every subject on each tick, allowing recovery after missed ticks. This follows the reconciliation approach in the [Kubernetes design principles](https://github.com/kubernetes/design-proposals-archive/blob/main/architecture/principles.md). If the process crashes after observing green CI but before merging, the next tick reads the current GitHub state and continues.

##### Reconciliation decisions for a subject

Each tick runs `_sense` (the GitHub read), `_classify` (a pure four-outcome classifier), then queueing or watchdog handling. Conditions short-circuit in this order; the ordering matters for correctness:

| Order | Current condition | Action |
| --- | --- | --- |
| 1 | Merged, closed, or `automation-failed` | Stop; changed facts can reactivate the subject |
| 2 | Latest comment is from a human | `reply` |
| 3 | Some `blocked_by` dependencies remain open | Wait for upstream work |
| 4 | No PR yet | `solve`: implement a vertical slice and open a PR |
| 5 | Mergeability is `unknown` | Wait for GitHub to calculate it |
| 6 | Mergeability is `dirty` | `rebase`: resolve conflicts before checking CI |
| 7 | CI on the current head is pending, or there are no checks | Wait for CI |
| 8 | CI on the current head failed | `fix-ci` |
| 9 | E2e evidence is missing or its `head_sha` is stale | `e2e`: collect current evidence |
| 10 | Review is absent, refers to a different head, or requests changes | `review`: review or address feedback |
| 11 | All checks pass and `review-approved:<current head sha7>` exists | `merge` into main |

##### `automation-failed`: a terminal machine failure tied to a fingerprint

Backend crashes, protocol errors, hard timeouts, and repeated lack of progress are retried within bounded budgets. Once the budget is exhausted, Vigil adds `automation-failed` to the issue/PR and records the category, attempts, a fact fingerprint excluding the label itself, and the last error. The same fingerprint does not consume further model calls. A material change to the issue body, PR head, CI, dependencies, or relevant comments causes Vigil to clear the stale failure state and reassess the subject.

Three safeguards cover failures an agent cannot reliably detect itself:

1. **No progress:** if an attempt finishes without changing the fingerprint, record an attempt stamp tied to that fingerprint. Work with the same fingerprint waits for side effects rather than being repeatedly queued and consuming model calls.
2. **Work is stuck without an agent running:** for example, CI never starts. The watchdog marks a subject `automation-failed` with a mechanical diagnosis when its QUIET age exceeds the threshold. The duration is derived from current state, without local history.
3. **An agent crashes, is killed, or hangs without leaving GitHub evidence:** a hard timeout kills the subprocess, `flock` determines whether its owner has died, and an attempt limit ends retries in a machine failure. A task that is alive and holds its lock receives warnings only; it is neither failed nor reclaimed.

##### Storage responsibilities

- **GitHub holds domain state:** dependencies (`blocked_by`), decisions (`ready`, `automation-failed`, and `review-approved:<sha7>` labels), native facts (checks and mergeability), and e2e evidence comments. Decisions use labels; native facts are read directly rather than copied into labels.
- **SQLite `work_queue`** stores what GitHub cannot express: which worker atomically claimed a subject, how many unfinished attempts it has made, and claim ordering. Lost queued rows can be reconstructed from GitHub on the next tick.
- **`.openagents/claims/{subject}.lock` (`flock`)** proves the owner's liveness. The kernel releases it when the process dies. Reclamation relies on the lock, rather than inferring death from an expired lease.

> The queue database is at `<repo>/.openagents/vigil-queue.db`. SQLite and `flock` constrain this deployment to one machine. Do not share the database over a network filesystem because it risks corruption; see the [SQLite guidance](https://www.sqlite.org/whentouse.html). Multi-machine operation would require replacing the four claim functions; the current version does not add that abstraction in advance.

##### Hard gates that the CLI cannot disable

`runtime.gates` contains three deterministic gates that `--skip` cannot disable: `head-advanced` (delivery must advance the head), `evidence-stamp` (e2e provenance must match the current head), and `round-cap` (limit reconciliation rounds to stop oscillation). `implement` and `deliver` always dispatch agents and do not support configurable gate ownership.

GitHub branch protection separately enforces required status checks such as lint, tests, commitlint, and spec validation. Change those rules under **Settings → Branches**. `--skip ci` only tells Vigil to stop waiting for CI; it does not change GitHub's permission to merge.

### `backfill-rfc`: document existing implementations

```bash
openagents backfill-rfc openagents/utils/git.py # One file
openagents backfill-rfc openagents/recipes/    # A directory
```

For code written before its design documentation, scan the path, infer a spec, and open a draft PR containing it. Set the base branch with `--base`; the default is `main`.

### `release`: create a version

```bash
openagents release              # Patch bump by default
openagents release --bump minor
```

Release timing is a human decision. After preflight checks pass, this command creates a `release/vX.Y.Z` branch and tag from the current `main` HEAD. These are deterministic operations and do not dispatch an agent.

### `board`: view results

Open a read-only dashboard based on `RuntimeState`. It does not require Git or a remote and can be used offline.

---

## Declarative configuration: `.openagents/openagents.yml`

`.openagents/openagents.yml` is the single source of truth for agent backends and stage ownership (Spec-0064). The entire file is optional: a missing or empty file uses the built-in defaults, with automatic agent-driven stages, one repository, and a 60-second interval.

```yaml
version: 1

# Roles can mix Claude Code, Codex, and nexau. Omitted roles use claude_code.
agents:
  implementer: { backend: claude_code }
  reviewer:    { backend: claude_code }

# Configurable stages use agent; eligible optional gates also allow skip (treated as PASS).
stages:
  triage:   agent      # Admission gate
  rfc:      agent      # RFC drafting; skip warns because design should precede code
  conflict: agent      # Resolve conflicts; cannot skip
  ci:       agent      # Wait for passing CI; may skip
  e2e:      agent      # Collect end-to-end evidence; may skip
  review:   agent      # Review; review:skip + merge:agent is rejected
  merge:    agent      # Merge; cannot skip

release: manual        # manual (human chooses release timing, default) / auto

defaults:              # Repository defaults; per-repository overrides take precedence
  interval: 60
  base: main
  labels: [openagents]

repos:                 # One run_fleet subprocess per repository; isolates gh/git working directories
  - path: .
```

Constraints:

- **Automatic merging requires review.** `review: skip` together with `merge: agent` is rejected because it would merge unreviewed code into main.
- **Hard gates cannot appear in `stages`.** `head-advanced`, `evidence-stamp`, and `round-cap` are always deterministic machine checks. `implement` and `deliver` always dispatch agents. These names are rejected in `stages`.
- **Skips are normalized when sensing state.** `ci: skip` treats CI as successful; `e2e: skip` stamps evidence for the current head; `review: skip` records approval at that head. This keeps `_classify` a pure mechanical decision table.

When upgrading from older terminal states, first run the Spec-0081 migrator under `scripts/migrate-*state.py` to inspect its dry-run plan, then add `--apply` after reviewing it. It idempotently converts forge labels and runtime failure states. For legacy configuration owners, it only reports the exact paths; explicitly change each owner to `agent` or, where allowed, `skip`.

---

## Working with Claude Code

[Claude Code](https://docs.claude.com/claude-code) is the default coding backend:

- **Develop OpenAgents interactively and use it for automated delivery.** The project uses this workflow itself: work on RFCs and code with Claude Code, then let `openagents vigil` advance issues through PRs unattended.
- **Choose the workflow to fit the task.** Use interactive Claude Code sessions for work needing close human involvement; hand well-defined issues to `vigil` for unattended execution.
- **Check authentication first.** OpenAgents invokes the `claude` CLI as its coding agent. Complete a working interactive `claude` session before starting `vigil`.

> `vigil` / `issue` perform real operations: they can invoke Claude to change code and use `gh` to open PRs or post comments. Try them in a practice repository first.

## License and project policies

[MIT](LICENSE) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Third-party sources](THIRD_PARTY.md) (Chinese) · [Changelog](CHANGELOG.md).
