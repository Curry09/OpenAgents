---
number: "0091"
title: Lightweight advisory coordination
issue: 0
slug: lightweight-preflight
summary: Add bounded, advisory preflight planning and soft queue coordination without turning planning into a delivery barrier.
architecture:
  objective: Keep optional coordination useful and bounded while preserving the original issue, acceptance, dependency, and delivery gates as authoritative.
  constraints:
    - Planning is advisory and must not create an execution-wave barrier.
    - Planner calls are bounded, cached, restart-safe, and isolated from worker claims.
    - Raw issues and existing forge blockers remain unchanged.
  non-goals:
    - Do not claim that scheduling measurements establish semantic developer correctness.
    - Do not introduce a new persistent role or replace the existing queue and claim model.
  candidates:
    - id: bounded-advisory-planner
      layer: coordinator, preflight cache, and Vigil queue ordering
      boundary:
        - issue intake
        - queue discovery
        - worker claim ordering
      evidence:
        - tests/test_preflight.py
        - https://github.com/Curry09/OpenAgents/blob/e5b66cef17452513373e5f1d4da192c824b288fb/docs/e2e-results/preflight-20260911/REPORT.md
      tradeoffs: Adds a bounded advisory call and cache while leaving eligibility and delivery gates unchanged.
    - id: mandatory-planning-barrier
      layer: execution scheduler
      boundary:
        - every intake wave
        - worker admission
      evidence:
        - would delay existing workers and make planner failure a product failure
      tradeoffs: Rejected because planning latency and failure would block otherwise eligible work.
  selected: bounded-advisory-planner
  affected-components:
    - openagents/agents/coordinator.py
    - openagents/recipes/vigil.py
    - openagents/runtime/preflight.py
    - openagents/runtime/engine.py
    - openagents/backends/claude_code.py
    - openagents/backends/nexau.py
  failure-modes:
    - invalid planner output
    - planner timeout or process failure
    - cache corruption or restart during persistence
    - advisory cycles or lock contention
verification:
  behavior-cases:
    - id: bounded-planning
      polarity: positive
      stimulus: soft coordination is enabled with ready issues
      expected: one bounded planner call produces at most eight clusters, order suggestions, and reuse notes without blocking existing workers
      observation: tests/test_preflight.py and validation report
    - id: invalid-or-timeout
      polarity: negative
      stimulus: planner returns invalid output or exceeds its wall budget
      expected: advisory failure is recorded and queue eligibility remains available
      observation: preflight failure and timeout tests
    - id: restart-cache
      polarity: positive
      stimulus: process restarts with unchanged or changed ready issue inputs
      expected: unchanged fingerprints are cached; changed inputs retry after cooldown
      observation: cache/restart/edit tests
    - id: advisory-ordering
      polarity: positive
      stimulus: hints include overlapping clusters, cycles, or stale suggestions
      expected: all eligible issues remain claimable and ordering only affects priority-1 preference
      observation: scheduling and concurrent claim tests
  repository-invariants:
    - Planner output never edits raw issues or overrides acceptance and delivery gates.
    - Claims retain SQLite BEGIN IMMEDIATE and flock protection.
    - Disabling soft coordination clears the advisory cache on startup.
  exemptions: []
tasks:
  - id: T1
    title: Bounded advisory preflight and soft scheduling
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/coordinator.py
      - openagents/backends/claude_code.py
      - openagents/backends/nexau.py
      - openagents/data/openagents.yml.template
      - openagents/recipes/vigil.py
      - openagents/runtime/engine.py
      - openagents/runtime/preflight.py
      - openagents/utils/agent_config.py
      - tests/test_backend_claude_code.py
      - tests/test_backend_nexau.py
      - tests/test_preflight.py
      - tests/test_recipe_vigil_act.py
      - tools/preflight_stress.py
      - docs/specs/0091-lightweight-preflight.md
    scope: Implement bounded advisory planning, durable input fingerprints, sanitized cache persistence, cooldown/retry behavior, and queue ordering that never changes issue eligibility.
    acceptance: Unit and concurrency tests cover invalid output, timeout, cache/restart/edit, partial admission, lock contention, advisory cycles, and concurrent claims; validation records scheduling cost without presenting it as developer correctness.
---

# 0091 · Lightweight advisory coordination

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

This group adds a bounded, non-blocking advisory preflight to Vigil: it can perform lightweight clustering of ready issues and suggest ordering and reuse opportunities,
but the original issues, acceptance criteria, dependencies, and delivery gates always remain authoritative. Planning failures, timeouts, or restarts do not cause otherwise healthy workers to fail.

## Motivation

When there are many ready issues, strict FIFO misses existing clues about similarity and reuse; on the other hand, turning planning calls into execution-wave barriers amplifies model latency and transient failures into blockage of the entire round.
An advisory layer is therefore needed that can be disabled, cached, and recovered, and that affects only the ordering of tasks with the same priority without changing eligibility decisions or delivery outcomes.

## Guide-level explanation

`coordination: soft` enables the advisory planner; the compatibility default is `dependencies`, and `off` also skips the planner. Each intake observes at most 64 ready issues,
and a single output contains at most 8 clusters, 8 ordering suggestions, and 8 reuse notes. Claude/NexAU use a single-turn call without tools, with an output limit of 8,192 tokens, a wall-clock limit of 90 seconds, and no protocol repair.
The planner runs before new work is enqueued, but it is not an execution-wave barrier; existing workers continue working.

Hints affect claim order only among the highest-priority priority-1 issues: first minimize overlap with active clusters and suggested prerequisite dependencies, then sort by the first suggested item, reverting to FIFO after 900 seconds. Even if the hints form a cycle or all issues fall into the same cluster, all candidates remain eligible for claim.

## Reference-level explanation

The input fingerprint, sanitized output, elapsed time, and status are persisted to `.openagents/preflight.json`; token usage continues to be written to the existing ledger. The fingerprint prevents repeated calls for identical inputs,
including after failures and process restarts; a 120-second cooldown consolidates incremental admission, with another attempt made after the input changes. Removing completed issues alone does not trigger the planner. When soft coordination is disabled, startup clears this cache.

Calls use a temporary working directory, and planner exceptions are recorded only as advisory failures; they never apply the automation-failed label. The original issue text is always passed along with developer advice, and editing an issue invalidates the advice.
Claims continue to use SQLite `BEGIN IMMEDIATE` and flock. Validation covers invalid output, timeout, cache/restart/edit, partial admission, stage priority, aging, advisory cycle, lock contention, and concurrent claims,
and uses existing reports to record scheduling costs for 30/300/3000 queued issues; these metrics are not equivalent to correctness in development semantics.

## Drawbacks

The system adds an optional model call, a local cache, and more ordering branches; even if the planner provides no benefit at all, its timeout, restart, and corruption recovery paths must still be maintained. Advisory hints may also lead observers to mistake them for hard dependencies, so output and logs must explicitly mark them as advisory.

## Rationale and alternatives

A bounded advisory planner is chosen over a mandatory planning barrier or unbounded retries. A mandatory barrier would delay existing workers and amplify planning failures into scheduling failures; unbounded retries would keep occupying the intake when the external model is unavailable. Retaining existing claim eligibility, SQLite/flock, and delivery gates confines the benefits to the ordering layer and avoids changing the system's boundaries of authority.

## Prior art

The implementation reuses the existing Vigil queue, SQLite claims, and token ledger; it introduces no new scheduler or persistence service. The validation report is retained in [Git history](https://github.com/Curry09/OpenAgents/blob/e5b66cef17452513373e5f1d4da192c824b288fb/docs/e2e-results/preflight-20260911/REPORT.md).

## Unresolved questions

Scheduling costs and suggestion hit rates are not yet sufficient to demonstrate consistent gains in real development throughput; real models, forges, and deployment environments still require separate end-to-end validation. The planner's suggestions should also not be used as evidence of correct requirements understanding or acceptance decisions.

## Future possibilities

In the future, the long-term benefits of different advisory ordering strategies can be compared without changing eligibility or delivery gates; changes to dependency semantics, the introduction of new persistent state, or the creation of an execution barrier should be covered by a separate spec.
