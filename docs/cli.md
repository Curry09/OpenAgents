# OpenAgents CLI reports

`oa report` reads local append-only telemetry under `.openagents/`. In addition to phase timing and
tool lookup metrics, it reports token usage by agent role when `token-usage.jsonl` is present.

The token table always shows both invocation coverage and token totals:

- `calls`: every `run_agent` invocation observed by the runtime;
- `reported`: invocations whose backend supplied structured usage;
- `missing`: invocations recorded as `unavailable`;
- `input`, `cache-r`, `cache-w`, `reason`, `output`: provider-reported components;
- `total(r/d)`: how many totals were provider-reported versus derived from mutually exclusive
  reported components.

Token totals cover only `reported` calls. An `unavailable` call is not zero tokens and is never
silently added as zero. The ledger stores counts, backend/model identity, role, timestamp and status;
it does not store prompts, responses, tool parameters or reasoning text.

## Claude Code API usage

No backend change is required. Roles that already use `claude_code` continue to run through Claude
Code and its configured API:

```yaml
agents:
  implementer: { backend: claude_code }
  reviewer:    { backend: claude_code }
```

OpenAgents does not read, copy, or persist the API key or base URL. Existing Claude Code environment
configuration such as `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_MODEL` remains
owned by Claude Code.

One `token-usage.jsonl` row represents one OpenAgents role invocation. Claude Code's final
stream-json `result.usage` is already aggregated across all model turns in that invocation, so
OpenAgents reads it exactly once. Intermediate `assistant.message.usage` events are deliberately not
added again.

## `openagents observation-capabilities --json`

Spec-0092 adds an offline machine interface for the installed evidence reader. It runs
before self-update and project resolution, emits one JSON object and does not create
project files or call a model. `--json` is required; malformed arguments fail without
triggering self-update.

The `openagents-observation-reader-capabilities-v1` object contains `marker`, `encodings`
(`gzip`, `zip`), `zip_profile` (`single-evidence-json-v1`), `download_policies`
(`same-origin-v1`, `gitea-com-r2-v1`), `max_transfer_bytes` (4,000,000), and
`max_expanded_bytes` (24,000,000). Query the exact executable/image used for delivery.
Use `OPENAGENTS_NO_SELF_UPDATE=1` when probing older installations as well. This command
declares reader support; it does not test live credentials or network reachability.
