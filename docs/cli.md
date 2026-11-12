# CLI guide

English | [CREDIT Chinese](cli.zh-CN.md)

Run commands from the target repository unless noted otherwise. `openagents --help` and `openagents COMMAND --help` list the installed version's arguments.

## Project setup and requirements

```bash
openagents init
openagents issue "Support CSV export" --body "Export the current filtered order list."
openagents issue "Fix login timeout" --yes
```

`init` prepares the repository and workflow labels, then writes the default configuration if it is missing. Other delivery commands also perform project preflight. `issue` asks for confirmation unless `--yes` is supplied, and adds the `openagents` discovery label. Additional `--label` options can be repeated. Issues created in the forge UI can be discovered by adding that label.

## Persistent delivery

```bash
openagents vigil
openagents vigil --parallel 4
openagents vigil --once
openagents vigil --interval 30 --base develop
openagents vigil --label bug --label p0
openagents vigil --config /path/to/openagents.yml
openagents vigil --skip ci,e2e
```

The default interval is 60 seconds and concurrency is 1; `--parallel` accepts 1–32. `--once` runs a bounded work cycle and drains its queue, without guaranteeing that externally blocked subjects finish. Configuration overrides apply only to this run. See [configuration](CONFIGURATION.md) for the effects of skipping gates.

Stop the process with Ctrl+C. Resume from the same target repository and configuration so the runtime can reconcile persisted work with current forge state. The local queue and locks belong on one machine; see [architecture](ARCHITECTURE.md).

## Specifications and releases

```bash
openagents backfill-rfc openagents/utils/git.py
openagents backfill-rfc openagents/recipes/ --base main
openagents release --bump patch
```

`backfill-rfc` infers specifications from an existing file or directory and opens a draft PR. `release` checks failures and main-branch CI, then pushes a `release/vX.Y.Z` branch and tag. It does not create a GitHub Release or build distribution assets; see [releasing](RELEASING.md).

## Local observation

```bash
openagents report
openagents board
openagents desktop --host 127.0.0.1 --port 8765
```

These commands read local runtime state without project-binding preflight. `board` creates a results dashboard; `desktop` serves the experimental observation API. They do not start delivery. To avoid a pre-command source update during an offline or frozen run, export `OPENAGENTS_NO_SELF_UPDATE=1`.

`report` reads append-only telemetry under `.openagents/` and shows phase timings, tool lookup metrics, and token usage by role. Token columns include:

| Column | Meaning |
| --- | --- |
| `calls` | Observed role invocations |
| `reported` / `missing` | Invocations with structured usage / unavailable usage |
| `input`, `cache-r`, `cache-w`, `reason`, `output` | Provider-reported components |
| `total(r/d)` | Counts of provider-reported / component-derived totals |

Totals cover reported calls; missing usage is not zero. Claude Code's final `result.usage` already aggregates the invocation's model turns, so intermediate assistant usage is not added again. The token ledger stores counts and invocation metadata, not prompts or responses. Other invocation traces can contain task content and need separate review before sharing.

## Evidence-reader capabilities

```bash
OPENAGENTS_NO_SELF_UPDATE=1 openagents observation-capabilities --json
```

This command runs before self-update and project lookup, emits one JSON object, and needs neither credentials nor a repository. `--json` is required. Query the actual delivery executable or image, rather than a different source checkout.

The `openagents-observation-reader-capabilities-v1` object declares supported markers, gzip/ZIP encodings, ZIP profile, download policies, and size limits (4,000,000 transferred bytes; 24,000,000 expanded bytes). It also declares execution-evidence schema support and required-dispatch enforcement. This is a capability declaration, not a live connectivity test; use the [reader probes](VERIFICATION.md) to validate behavior.

## Shell completion

For bash, add to `~/.bashrc`:

```bash
eval "$(register-python-argcomplete openagents)"
```

For zsh, add to `~/.zshrc`:

```zsh
autoload -U bashcompinit
bashcompinit
eval "$(register-python-argcomplete openagents)"
```

Completion is optional and reads the CLI definitions. `register-python-argcomplete` is supplied by the installed argcomplete dependency; ensure the uv tool environment's executable is on your PATH if your tool installation exposes only the OpenAgents entry points.
