# Spec-0079 verification evidence

Date: 2026-08-28

## Offline verification

- The installed Claude Code 2.1.12 stream was inspected with a privacy-minimal probe. Its final
  `result` event contains aggregate `usage` and `modelUsage`; intermediate assistant events also
  contain usage and must not be added again.
- Backend tests use that observed result shape and cover input/output/cache fields, single and
  multiple models, explicit and derived totals, malformed or absent usage, and double-counting
  prevention while preserving protocol output and tool streaming.
- Runtime tests cover one ledger row per invocation, reported/unavailable coverage, backend and
  protocol failures, privacy allowlisting, linked worktrees, malformed rows, and report aggregation.
- `scripts/e2e-spec-0079-token-usage-observability.sh` is the repeatable offline acceptance command.

## Live API canary

Status: passed.

The opt-in probe ran through OpenAgents' existing `ClaudeCodeBackend` and the installed Claude Code
2.1.12 using the experiment's API gateway configuration and model
`deepseek/deepseek-v4-flash`. The provider returned a successful model response with aggregate
usage. OpenAgents captured one invocation and produced these sanitized values:

- input tokens: 18,642
- output tokens: 34
- cache read tokens: 0
- cache creation tokens: 0
- reasoning tokens: unavailable
- total tokens: 18,676 (`derived-components`)
- ledger events: 1 (`reported`)
- `AgentResult.usage` matched the ledger: yes
- `oa report` matched the ledger: yes

An earlier attempt using the shell's inherited `ANTHROPIC_*` credentials was rejected before model
generation with HTTP 403 because that API user was blocked; it produced no successful usage and is
not counted as evidence. The successful retry used the WIS configuration used by the DS4 experiment,
temporarily translated to Claude Code's environment contract without changing persistent settings.
No API key, base URL, prompt, response body, request identifier, or tool arguments are preserved here.
