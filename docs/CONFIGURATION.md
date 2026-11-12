# Configuration

English | [CREDIT Chinese](CONFIGURATION.zh-CN.md)

OpenAgents reads `.openagents/openagents.yml` in the target repository. `openagents init` creates the [annotated template](../openagents/data/openagents.yml.template) without replacing an existing file; `init --force` replaces it. A missing or empty file uses the built-in defaults.

## Default delivery

```yaml
version: 1
flow: standard
coordination: dependencies
forge: github
stages:
  triage: agent
  rfc: agent
  architecture: agent
  conflict: agent
  ci: agent
  e2e: agent
  review: agent
  merge: agent
release: manual
defaults:
  interval: 60
  base: main
  labels: [openagents]
repos:
  - path: .
```

Unspecified stages use `agent`; the CLI uses Claude Code unless the backend environment selects NexAU. `vigil --config PATH` selects another file. `--base`, `--interval`, `--label`, and `--skip` override one run without rewriting YAML. Per-repository entries can override shared defaults; use a separate configuration per deployment when their credentials or environments differ.

## Backends

The implemented backends are `claude_code` and `nexau`. For `vigil`, select NexAU with `OPENAGENTS_BACKEND=nexau`; the CLI otherwise creates a Claude Code backend.

The loader accepts `agents.<role>.backend` declarations, but the current CLI does not route execution through those per-role mappings. Setting them alone does not switch the actual backend or provide mixed-backend execution. Do not use an unimplemented backend name just because the configuration accepts a string.

Claude Code uses the installed `claude` CLI and its authentication, model, and endpoint configuration. The default permission mode is `acceptEdits`; `OPENAGENTS_PERMISSION_MODE` overrides it. Set permissions for the tools the target project actually requires.

NexAU requires the optional package extra and these exported variables:

```bash
export OPENAGENTS_BACKEND=nexau
export OPENAGENTS_NEXAU_MODEL='your-model'
export OPENAGENTS_NEXAU_BASE_URL='https://your-provider.example'
export OPENAGENTS_NEXAU_API_KEY='your-local-secret'
```

The backend uses an Anthropic-compatible **Messages** API. An OpenAI `/chat/completions` URL is not interchangeable with that endpoint. Optional limits are `OPENAGENTS_NEXAU_MAX_CONTEXT_TOKENS` (default `262144`) and `OPENAGENTS_NEXAU_MAX_OUTPUT_TOKENS` (default `32768`). See [`.env.example`](../.env.example); the CLI does not source it automatically.

`OPENAGENTS_CLAUDE_MAX_WALL` controls the shared per-invocation wall-clock budget, including Vigil dispatches; its historical name also applies when Vigil dispatches NexAU. The default is `3600` seconds; a finite value at or below zero disables it. Claude Code also has an output-idle limit, `OPENAGENTS_CLAUDE_IDLE_TIMEOUT`, default `300` seconds; a value at or below zero disables that limit. Activity does not extend the wall-clock budget.

## GitHub and Gitea

GitHub uses `gh` authentication. For Gitea, configure the API base URL and repository identity:

```yaml
version: 1
forge: gitea
gitea:
  base_url: https://gitea.com
  owner: your-user
  repo: your-project
  token_env: GITEA_TOKEN
```

Export the named token before launching the command. Use your deployment's reachable base URL for self-hosted Gitea. The remote Git transport must also be authenticated: a REST token in the environment does not by itself configure Git's credential helper or SSH identity.

## Flows and coordination

| Flow | Entry point | Behavior |
| --- | --- | --- |
| `standard` | `openagents vigil` | Persistent delivery with specification, architecture review, implementation, verification, review, and rework |
| `minimal` | `openagents vigil` with `flow: minimal` | Experimental compact specification, one implementation, and acceptance against the original issue |
| `generate-only` | `openagents vigil` with `flow: generate-only` | Research profile: constrained generation and mechanical merging without quality verification |

`coordination: dependencies` lets the curator establish hard issue dependencies. `soft` generates non-blocking ordering advice while preserving the original issue and acceptance conditions. `off` disables model-based coordination; existing forge dependencies still apply.

## Quality gates

`triage`, `rfc`, `architecture`, `ci`, and `e2e` accept `agent` or `skip`. Architecture can be skipped only together with RFC drafting. `conflict` and `merge` cannot be skipped, and `review: skip` with automatic merging is rejected. Skipping CI in OpenAgents does not bypass branch protection on the forge.

`head-advanced`, `evidence-stamp`, and `round-cap` are deterministic runtime gates rather than configurable stages. `implement` and `deliver` always dispatch agents. These names are rejected under `stages`.

`release: manual` is the default release policy. The loader also accepts `auto`, but automatic release publication is not implemented; use the explicit `release` command. PR merging remains controlled by the delivery flow.

## Required execution evidence

For a publisher that supports execution-condition evidence, a trusted project configuration can require it:

```yaml
execution_evidence:
  required: true
```

Missing, damaged, unauthorized, or unsupported required evidence blocks model dispatch. Ordinary projects default to `false`. The issue body cannot turn this requirement off. See [AHE-Beta integration](integrations/ahe-beta.md) for publication and reader checks.
