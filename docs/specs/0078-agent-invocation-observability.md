---
number: "0078"
title: "Agent Invocation Protocol Fidelity and Privacy-Preserving Telemetry"
issue: 0
slug: agent-invocation-observability
summary: "Separate complete machine-readable output from length-limited summaries for humans, and record only the sequence of tool names to measure the investigation budget, ensuring reliable structured protocols and making experiment durations explainable."
architecture:
  objective: "Ensure that structured Agent output is not corrupted by display truncation, and measure each role's tool usage and investigation before the first edit using minimal data."
  constraints:
    - "Maintain compatibility when the old backend returns only summary"
    - "Telemetry failures must not affect workflow results"
    - "Do not record tool arguments, command bodies, file contents, or model reasoning"
  non-goals:
    - "Count model tokens precisely"
    - "Block calls that exceed the investigation budget"
    - "Save the complete Agent transcript for analysis"
  candidates:
    - id: parse-display-summary
      layer: runtime-parser
      boundary:
        - AgentResult summary
      evidence:
        - "Display summaries may be length-limited; structured JSON cannot be parsed if it lies beyond the truncation point"
      tradeoffs: "No backend protocol extension is required, but display requirements will continue to break the machine protocol."
    - id: split-protocol-and-telemetry
      layer: backend-result-runtime-observability
      boundary:
        - AgentResult
        - Backend adapters
        - Runtime engine
        - CLI report
      evidence:
        - "The backend itself holds the complete final output and ordered tool events; the runtime currently consumes only the length-limited summary"
      tradeoffs: "Extend the optional result fields and add local JSONL; this separates responsibility for the machine protocol, display summaries, and minimal telemetry."
  selected: split-protocol-and-telemetry
  affected-components:
    - openagents.backends
    - openagents.runtime.engine
    - openagents.runtime.tool_usage
    - openagents.cli
  failure-modes:
    - "The structured protocol cannot be parsed after long output is truncated"
    - "Telemetry records sensitive tool arguments or command bodies"
    - "Each linked worktree writes its own report, scattering the data from a single experiment"
    - "A telemetry write exception blocks the Agent's main workflow"
verification:
  behavior-cases:
    - id: parse-unabridged-protocol
      polarity: positive
      stimulus: "The display summary is truncated, but raw output contains the complete JSON on the final line"
      expected: "The runtime successfully parses the structured result from protocol_output"
      observation: "Unit tests for the backend and runtime engine"
    - id: telemetry-write-failure
      polarity: negative
      stimulus: "The telemetry directory is not writable or events are incomplete"
      expected: "Agent call results remain unchanged, and the report loader ignores invalid records"
      observation: "Unit tests for tool usage"
  repository-invariants:
    - "tool-usage.jsonl does not contain tool arguments or command bodies"
    - "Events from linked worktrees are aggregated in the main worktree"
    - "Behavior remains unchanged when the old AgentResult does not provide raw_output or tool_events"
  exemptions: []
tasks:
  - id: T1
    title: "Complete Machine Protocol Output"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backends/base.py
      - openagents/backends/claude_code.py
      - openagents/runtime/engine.py
      - openagents/utils/align.py
      - tests/test_base.py
      - tests/test_backend_claude_code.py
      - tests/test_runtime_engine.py
    scope: "Add optional raw_output and a protocol_output fallback property to AgentResult; backends retain the complete final output, and all structured protocol consumers stop parsing the length-limited display summary."
    acceptance: "Tests demonstrate that legacy results fall back to summary, long JSON remains parseable even when the display summary is truncated, alignment uses the complete output, and existing summary display behavior remains unchanged."
  - id: T2
    title: "Minimal Tool Invocation Telemetry"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/tool_usage.py
      - tests/test_runtime_tool_usage.py
    scope: "Calculate the total invocation count, the position of the first edit, the number of preceding investigation calls, and whether the default budget was exceeded from the ordered tool names; append records to JSONL in the main worktree, failing open on exceptions."
    acceptance: "Tests cover tool classification, budget boundaries, reasons for exceeding the budget, aggregation across linked worktrees, ignoring corrupted lines, and aggregation by role; persisted events contain only tool names and derived counts."
  - id: T3
    title: "Backend Event Wiring and Reporting"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli_timing.py
    scope: "The Claude streaming adapter extracts only tool_use names and returns them with AgentResult; runtime records invocations after successfully parsing the protocol, and report outputs an investigation budget table aggregated by role after the existing latency section."
    acceptance: "Tests demonstrate that tool order is preserved but inputs are not persisted, the existing timing report remains unchanged when no telemetry data is available, reporting still works when only telemetry is available, and write failures do not change the Agent return value."
---

# 0078 · Agent Invocation Protocol Fidelity and Privacy-Preserving Telemetry

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

OpenAgents explicitly separates the machine protocol payload, human-facing display summary, and tool usage telemetry for each Agent invocation. The backend retains the complete final output
for structured parsing, while extracting only the ordered tool names for local budget statistics; tool arguments, command bodies, and file contents never enter telemetry.

## Motivation

Currently, `AgentResult.summary` serves as both PR display text and machine protocol input. The display layer truncates long results for readability, but the final-line JSON from roles such as Drafter and
Reviewer may fall beyond the truncation point, causing runtime parsing to fail even when the model actually followed the protocol. Meanwhile,
experiments show that roles spend substantial time repeatedly gathering evidence, yet there is no data explaining investigation counts by role, leaving only total wall-clock time as a basis for inference.

These two problems share the same boundary: the backend has already observed the complete final output and streaming tool events, but the result protocol exposes only the display summary.
Machine data must be separated from display data, and data minimization must be applied to observable information.

## Guide-level explanation

After the backend completes an invocation, `summary` remains a short text suitable for a comment or PR body; `raw_output` stores the complete text returned by the model.
The runtime reads the complete value through `protocol_output`, automatically falling back to summary when an older backend does not provide it. Long responses therefore no longer have their final-line JSON broken by display
truncation.

Only names and ordering are extracted from `tool_use` in Claude streaming events, such as Read, Grep, and Edit. The system counts investigation
calls before the first edit and appends the count to `.openagents/tool-usage.jsonl`. `openagents report` can display invocation counts, average and maximum investigation counts before
the first edit, and counts of budget overruns by role. The report cannot answer questions about token usage, nor does it store the specific content that tools read or execute.

## Reference-level explanation

`AgentResult` gains optional `raw_output` and `tool_events` fields and a read-only `protocol_output` property. The Claude adapter saves
the complete final text from the result event and extracts `tool_use.name` in order from assistant content blocks. `runtime.engine` and the alignment parser
both consume `protocol_output`, ensuring compatibility with older backends.

`runtime.tool_usage` treats Read, Bash, Grep, Glob, Search, and Find as investigation tools, and Edit, Write, MultiEdit, and
NotebookEdit as editing tools, with a default baseline of six investigation calls before the first edit. If there is no edit, it counts investigation calls over the entire invocation. Records include a random
invocation ID, UTC time, role, tool names, and derived counts; a length-limited reason is saved only when the budget is exceeded and the role explicitly returns a reason.

A linked worktree locates the main worktree through the `.git` pointer, directing events from the same Vigil experiment into a single append-only JSONL file. All telemetry
exceptions are isolated and must not change the Agent's business result. The CLI appends a separate table after the timing data; a report can be generated when either type of data is present.

Task dependencies are `T1 → T2 → T3`. Offline tests cover truncated protocols, backend event extraction, main worktree discovery, corrupt data, and report combinations,
without calling real models or accessing the external network.

## Drawbacks

The complete output remains in memory longer during an invocation, and the tool name sequence also slightly increases the result size. The local JSONL file grows with invocations and must be
rotated by the deployment operator according to the existing policy for runtime assets. Tool names are an approximate signal and cannot be equated with actual cognitive effort.

## Rationale and alternatives

Extending `AgentResult` was chosen because both the complete output and tool events originate at the backend boundary, and exposing optional fields to the runtime preserves compatibility with older implementations.
One alternative is to remove summary truncation, but that would make comments and terminal output unmanageable; another is to require the model to put JSON at the beginning, but that still couples display policy with
the machine protocol. For telemetry, saving complete tool input would provide more detail, but would record commands, paths, and content, with disproportionate privacy and audit
costs; tool names and ordering are sufficient to answer the current budget questions.

## Prior art

Logging systems typically distinguish complete structured events from human-facing formatted views, and distributed tracing likewise prioritizes recording span names and aggregate metrics over
arbitrary business payloads. This design adopts the same principles of data separation and minimization.

## Unresolved questions

Whether tool names from different backends need a standardized vocabulary, and the default rotation limit for JSONL, must be decided after integrating a second backend capable of reporting tool events.

## Future possibilities

In the future, the model-side token ledger and phase timing could be correlated to provide a view of invocation costs without sensitive arguments; investigation budgets could also be configured for different roles,
but budgets should remain an observable baseline rather than a mechanism for forced termination.
