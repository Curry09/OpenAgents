---
number: "0079"
title: "OpenAgents Claude Code API token usage observability"
issue: 0
slug: token-usage-observability
summary: "Collect API token usage from the final Claude Code stream-json event already consumed by OpenAgents, write it to a local ledger by role and invocation, and show both consumption and collection coverage in reports; when usage cannot be obtained, explicitly record unavailable, and never treat missing data as zero."
architecture:
  objective: "Establish the complete pipeline from the stream-json result.usage already read by ClaudeCodeBackend to AgentResult, the runtime ledger, and oa report, so that both usage and collection coverage are auditable when roles such as development run through the user's API."
  constraints:
    - "The data source must be the final result.usage output by Claude Code invocations launched by OpenAgents itself; statistics from the harness or other processes must not be used."
    - "Record only counts, model, backend, role, time, and status; do not record prompts, responses, tool arguments, or reasoning text."
    - "When the API does not report usage, record unavailable; do not estimate it as zero or silently omit the row."
    - "Telemetry failures must fail-open and must not change the Agent's business result or exception semantics."
    - "Maintain AgentResult source compatibility when older backends do not provide usage."
    - "Keep cache read, cache creation, and reasoning in separate columns from ordinary input/output; do not add them together redundantly without justification."
  non-goals:
    - "Monitor model invocations outside OpenAgents."
    - "Rewrite Claude Code's API client, proxy the user's gateway, or require replacing the existing backend."
    - "Infer exact billable token counts from text length."
    - "Implement price tables or billing settlement in this feature."
    - "Save complete model requests and responses."
  candidates:
    - id: outer-text-estimation
      layer: runtime
      boundary:
        - runtime.engine prompt/result text
      evidence:
        - "OpenAgents can see the outer prompt and final text."
      tradeoffs: "It cannot see multiple rounds of tool calls, caching, or reasoning inside the API backend; the numbers appear complete but systematically underestimate usage. Rejected."
    - id: harness-telemetry
      layer: unrelated-external-process
      boundary:
        - harness usage frames
        - harness usage ledger
      evidence:
        - "The harness may already record its own API usage."
      tradeoffs: "The statistics do not cover Claude Code role invocations initiated by OpenAgents, and the role and invocation boundaries differ. Rejected."
    - id: claude-result-usage-ledger
      layer: claude-code-stream-result-runtime-observability
      boundary:
        - ClaudeCodeBackend stream-json parser
        - AgentResult
        - runtime.engine
        - local JSONL ledger
        - oa report
      evidence:
        - "The final result event in Claude Code 2.1.12 directly provides usage and modelUsage aggregated over the entire CLI invocation."
      tradeoffs: "Depends on the Claude Code stream-json contract; missing fields or version drift must explicitly be recorded as unavailable."
  selected: claude-result-usage-ledger
  affected-components:
    - openagents.backends.base
    - openagents.backends.claude_code
    - openagents.runtime.engine
    - openagents.runtime.token_usage
    - openagents.cli
  failure-modes:
    - "Changes to Claude Code result.usage fields cause silent gaps in collection."
    - "Accumulating both assistant.message.usage and result.usage double-counts the entire invocation."
    - "Treating unavailable as zero underestimates role costs."
    - "Counting cache tokens in both input and total causes double-counting."
    - "Ledger writes scattered across linked worktrees prevent aggregation of the same run."
    - "Telemetry write failures block the normal Agent flow."
    - "Testing only with fabricated fixtures without ever confirming the actual stream-json event shape of the installed Claude Code."
verification:
  behavior-cases:
    - id: claude-result-usage-roundtrip
      polarity: positive
      stimulus: "The final result event from Claude Code launched by OpenAgents contains input/output/cache usage and modelUsage."
      expected: "AgentResult retains normalized counts, the runtime writes one reported ledger entry, and the aggregate values in oa report match result.usage."
      observation: "Unit tests using real-event fixtures + a comparison of sanitized usage against the ledger from one opt-in Claude Code API canary."
    - id: backend-without-usage-is-visible
      polarity: negative
      stimulus: "An older backend returns an AgentResult without usage."
      expected: "The business result remains unchanged, an unavailable row is added to the ledger, and the report's coverage denominator includes that invocation."
      observation: "Integration tests with a fake backend."
    - id: telemetry-write-failure-isolated
      polarity: negative
      stimulus: "The .openagents path is not writable."
      expected: "Telemetry does not override the original Agent return value or the original backend exception."
      observation: "Runtime ledger and engine exception tests."
    - id: real-claude-schema-drift-visible
      polarity: negative
      stimulus: "The Claude Code result event from the opt-in live canary has no parseable usage."
      expected: "The canary fails and prints only sanitized field names; the feature must not pass acceptance as live-verified."
      observation: "Claude Code live canary exit code."
  repository-invariants:
    - "token-usage.jsonl contains no prompts, responses, tool arguments, or reasoning text."
    - "Each engine.run_agent invocation has exactly one reported or unavailable record, including when the backend throws an exception."
    - "The ledger for linked worktrees is written to .openagents in the main worktree."
    - "oa report displays the invocation count, reported count, and unavailable count together, without hiding coverage gaps in the totals."
    - "The source of total must be labeled reported or derived-components."
  exemptions:
    - "Until result.usage has been obtained from a successful real Claude Code model response, passing all tests for the public contract, ledger, and report does not mean live acceptance is complete; harness results must not be used as a substitute."
tasks:
  - id: T1
    title: "TokenUsage backend result contract"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backends/base.py
      - tests/test_base.py
    scope: "Add optional TokenUsage to AgentResult; separate input/output/cache-read/cache-creation/reasoning/total fields, and include model and total_source; maintain compatibility with existing construction patterns without requiring any changes."
    acceptance: "Tests prove that existing AgentResult construction defaults to usage=None; invalid counts such as negative numbers and booleans cannot enter normalized results; total_source permits only reported/derived-components."
  - id: T2
    title: "Claude Code stream usage adaptation and integration into the existing execution path"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/backends/claude_code.py
      - openagents/runtime/engine.py
      - tests/test_backend_claude_code.py
      - tests/test_runtime_engine.py
    scope: "Keep the existing backend=claude_code and user API configuration unchanged; ClaudeCodeBackend parses only the final result.usage within the existing stream-json read loop, and identifies the model using modelUsage or init.model. result.usage is already aggregated for the entire CLI invocation; adding assistant.message.usage again is prohibited. Return the counts with AgentResult; when fields are missing, set usage=None. Do not read prompts, response bodies, harness ledgers, or API keys to fill in missing values."
    acceptance: "When agents.implementer.backend=claude_code, usage can be collected during development without switching backends; real Claude Code 2.1.12 result fixtures cover input/output/cache, single/multiple models, partial/malformed/absent usage, and explicit/derived total; assistant usage is excluded from totals; existing stream output, tool events, protocol results, and exception semantics remain unchanged."
  - id: T3
    title: "Invocation-level token ledger and runtime integration"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/token_usage.py
      - tests/test_runtime_token_usage.py
    scope: "Append one line to .openagents/token-usage.jsonl in the main worktree for every run_agent invocation, whether it succeeds or fails; record role/backend/model/status/source and token components; the aggregator summarizes by role and reports coverage; write failures fail open."
    acceptance: "Tests cover reported/unavailable, backend exceptions, unwritable directories, corrupted lines, linked worktrees, aggregation by role, exactly one line per invocation, and a privacy field allowlist; application results and original exceptions remain unchanged."
  - id: T4
    title: "Token reports and user contract"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - tests/test_cli_timing.py
      - docs/cli.md
    scope: "Add a per-role token table to oa report, showing invocation/reported/unavailable counts and input/cache-read/cache-write/reasoning/output/total separately; explain total_source and coverage without changing existing timing/tool reports."
    acceptance: "Tests cover token-only data, coexistence with timing/tool data, all unavailable, mixed coverage, and empty data; documentation explicitly defines how total is calculated and states that unavailable does not equal zero."
  - id: T5
    title: "Offline end-to-end validation and live Claude Code API canary"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T2
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0079-token-usage-observability.sh
      - scripts/live-spec-0079-token-usage-observability.sh
      - scripts/live_spec_0079_token_usage_observability.py
    scope: "The offline script runs lint, targeted tests, and spec validate/render/graph check; an opt-in live canary sends a minimal request through OpenAgents' existing ClaudeCodeBackend, cross-checks result.usage, AgentResult, the ledger, and the report, and saves only sanitized evidence such as field names, counts, and versions."
    acceptance: "All offline script checks pass; the live script succeeds at least once in an acceptance environment where Claude Code is configured to use the user's API; evidence includes backend/model, result usage fields, ledger values, report values, and consistency across the three; T5 must not be marked done without a successful model response."
---

# 0079 · OpenAgents Claude Code API Token Usage Observability

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine rust-RFC sections. -->

## Summary

OpenAgents establishes a token usage pipeline for each of its own role Agent invocations: the existing ClaudeCodeBackend extracts API counts for the entire CLI invocation from the final `result.usage` in Claude Code
stream-json, passes them to the runtime through the optional `AgentResult.usage`, appends them per invocation to a local ledger in the main worktree, and finally
displays consumption and collection coverage by role through `oa report`. Invocations without usage are explicitly recorded as `unavailable`, without estimation or substitution with zero.

## Motivation

OpenAgents currently cannot answer how many tokens an implementation, review, or architecture invocation consumes. The outer layer can see only the task text and final result; it cannot account for
the multiple rounds of tool calls, caching, and model requests inside Claude Code. Treating missing data as zero would systematically underestimate costs; estimating from text length would create false
precision. Usage must therefore be collected at the boundary of OpenAgents' own model API calls.

The scope of these statistics is strictly limited to OpenAgents. Even if other processes call the same API, their usage belongs to a separate execution boundary and cannot
substitute for OpenAgents' ledger or acceptance criteria.

## Guide-level explanation

Each `run_agent` ultimately produces one ledger record. If the final Claude Code event reports usage, the record is marked `reported`; if the backend does not support it,
the fields are missing, or the invocation fails before usage is obtained, the record is marked `unavailable`. The report presents invocation counts, collected counts, missing counts, and token totals side by side,
so users do not mistake partial coverage for complete costs.

## Reference-level explanation

`TokenUsage` is an optional immutable value in the backend result protocol, containing input/output, cache read, cache creation, reasoning,
total, model, and `total_source`. The adapter accepts only nonnegative integers; when Claude Code supplies an explicit total, it is marked `reported`. A total may be derived from components
and marked `derived-components` only when the field semantics are confirmed to be mutually exclusive. The runtime does not guess provider fields on its own.

This feature reuses the existing `claude -p --output-format stream-json --verbose`. Claude Code's `assistant.message.usage`
belongs to intermediate messages, whereas the final `result.usage` already aggregates the entire run; the adapter reads only the latter, once, to avoid double counting across multiple rounds. Users' existing
Claude Code API configurations, such as `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, and `ANTHROPIC_MODEL`, remain unchanged. OpenAgents
neither reads nor persists secrets. When `modelUsage` contains only one model, that model is recorded; when it contains multiple models, a model-set identifier is retained.

Task DAG:

```text
T1 Public contract ─→ T2 Claude stream adapter ──────┐
     └──────→ T3 ledger/runtime → T4 report ─→ T5 Real API acceptance
```

T1, T3, and T4 can prove only that the shared data pipeline works. After T2 integrates the existing Claude Code stream, T5 must still use the user's real API
configuration to prove that result usage, the ledger, and the report are consistent before the entire feature can be declared complete. Usage from a harness or other processes is outside the scope of this spec.

## Drawbacks

The ledger will grow continuously, so rotation will need to be considered later. Different API providers may define cache and total differently; comparisons across backends must
consider model, components, and `total_source` together. A real canary depends on credentials and network access and is unsuitable as a mandatory check for every commit, but it must pass for release acceptance.

## Rationale and alternatives

The Claude result usage ledger was chosen because OpenAgents already reads this structured stream line by line, and the final event is precisely the aggregation boundary for the entire Claude Code
invocation. Estimates based on outer-layer text would miss internal rounds of calls; proxy gateway logs require additional correlation; a harness ledger measures a different scope.
Adding NexAU or a direct API backend would change the user's existing execution chain and cannot be a prerequisite for this requirement.

## Prior art

OpenTelemetry's LLM semantic conventions and the usage objects of multiple model APIs separate counts from message bodies and distinguish model,
input, output, and cache dimensions. This design follows the same principles, but the first version keeps a local JSONL ledger and does not introduce a remote collector.

## Unresolved questions

Whether different Claude Code versions and compatible API gateways consistently provide the same set of usage fields requires ongoing evidence from live canaries; when fields are missing, the status remains
`unavailable`. Intermediate assistant events or text estimates must not be used to fill the gaps.

## Future possibilities

The ledger could later be associated with issue/PR/round, phase timing, and API request ID to calculate the token cost per effective merge; other possible additions
include JSON/CSV export, ledger rotation, and budget alerts by role. All extensions should continue to retain coverage information for unavailable usage.
