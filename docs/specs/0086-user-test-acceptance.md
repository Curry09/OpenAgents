---
number: "0086"
title: "Auditable acceptance led by User Test"
issue: 0
slug: user-test-acceptance
summary: "Use real user interactions instead of component self-verification as the primary evidence for v0.2 Acceptance, and preserve the complete results in an isolated copy."
architecture:
  objective: "Prevent acceptance workload from reducing development to prompt-only/toy changes; allow merging only after user-observable goals have been verified through real interactions."
  constraints:
    - "User Test must run in a temporary copy of the candidate HEAD outside the repository; the candidate worktree must remain immutable during acceptance."
    - "The input transcript, stdout, stderr, exit status, and copy's workspace diff must be persisted outside the candidate repository."
    - "timed_out, crashed, setup_failed, or a missing User Test configuration must not produce PASS."
    - "A PASS manifest must contain at least one entry with source=user_test, kind=behavior, and passed=true, and reference actual artifact paths."
    - "Static checks, Developer self-reported tests, and independent variants may only explain results; they cannot replace User Test."
  non-goals:
    - "Do not modify the candidate worktree during user testing, and do not allow the Acceptance agent to fix code."
    - "Do not require every issue to supply a fixed number of replay/variant cases."
  candidates:
    - id: disposable-user-test
      layer: acceptance
      boundary:
        - external disposable repository copy
        - interactive harness transcript and process lifecycle
      evidence:
        - candidate worktree remains unchanged while user-visible behavior is exercised
      tradeoffs: requires an explicit harness command and transcript for every production batch.
  failure-modes:
    - harness timeout or crash must remain a terminal non-PASS result.
    - model-cited evidence outside the generated artifact directory invalidates PASS.
    - missing user-test configuration must not silently fall back to component-only review.
  selected: disposable-user-test
  affected-components:
    - openagents/runtime/user_test.py
    - openagents/agents/acceptance.py
    - openagents/recipes/stages.py
    - openagents/runtime/evidence.py
    - openagents/v02/openagents_adapter.py
    - openagents/v02/model.py
    - openagents/cli.py
    - tests/test_runtime_user_test.py
    - tests/test_v02_openagents_adapter.py
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: "Run the configured JSONL user transcript against a delivered candidate."
      expected: "The harness runs only in the candidate copy; inputs, outputs, status, and diff can all be located, and the candidate worktree remains unchanged."
      observation: runtime user-test tests verify external copy and persisted paths.
    - id: BC2
      polarity: negative
      stimulus: "The harness times out or exits with a nonzero status."
      expected: "The result is timed_out/crashed, Acceptance is not invoked or PASS is not accepted, and the process group is terminated."
      observation: adapter fail-closed tests and runner process tests.
    - id: BC3
      polarity: positive
      stimulus: "User Test has completed, and Acceptance returns user_test behavior evidence."
      expected: "Proceed with the merge on PASS only when the evidence has source=user_test and is bound to the current HEAD."
      observation: adapter/stage contract tests.
  repository-invariants:
    - "The User Test subprocess cwd is always the disposable artifact/repo, never the candidate worktree."
    - "In v0.2, return PARTIAL when User Test is not configured; do not fall back to component review to approve the candidate."
    - "The candidate HEAD and meaningful worktree state remain unchanged before and after Acceptance."
  exemptions: []
tasks:
  - id: T1
    title: "Implement an isolated User Test runner and artifact ledger"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/user_test.py
      - tests/test_runtime_user_test.py
    scope: "Launch the harness using the configured command and JSON transcript, execute it in an isolated copy, and collect process/frame/tool events/workspace diffs."
    acceptance: "Deterministic tests cover the four states completed, timed_out, crashed, and setup_failed, as well as external artifact paths."
  - id: T2
    title: "Integrate User Test into the v0.2 Acceptance gate"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/agents/acceptance.py
      - openagents/recipes/stages.py
      - openagents/runtime/evidence.py
      - openagents/v02/openagents_adapter.py
      - openagents/v02/model.py
    scope: "Use User Test as the sole primary behavioral evidence for a production PASS; fail closed on abnormal states, and do not allow tests to write to the candidate worktree."
    acceptance: "Timeouts/crashes must neither invoke nor accept PASS; completed permits only a behavior manifest with source=user_test."
  - id: T3
    title: "Provide CLI configuration options and traceable documentation"
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
      - docs/specs/0086-user-test-acceptance.md
    scope: "v0.2 supports --user-test-command, --user-test-transcript, and --user-test-timeout; explicitly report PARTIAL when not configured."
    acceptance: "CLI flags can construct the same UserTestPlan without modifying the global environment."
---

# 0086 · Auditable Acceptance Driven by User Test

## Summary

Past acceptance processes could easily turn into component reviews: there was abundant evidence, but actual user goals were never carried out, so the Developer tended to choose
prompt-only or toy changes that were easiest to substantiate under the rules. This group of changes brings real user interactions forward as the primary evidence for v0.2 Acceptance and strictly separates the interaction runtime from the candidate workspace.

## Motivation

If acceptance considers only diffs, static checks, and model self-reports, the system rewards changes that are easy to explain rather than effective. Real user interactions directly expose whether functionality is reachable,
whether it works along the original operation path, and whether the implementation is merely a superficial change that sidesteps a difficult goal.

## Reference-level explanation

`OpenAgentsAdapter.accept` first creates an external copy from the candidate HEAD, then uses `run_user_test` to launch the harness and feed it the transcript.
The results are passed to Acceptance as a structured `UserTestResult`; PASS is possible only if the run completed normally and the model manifest cites
`source=user_test` behavioral evidence from this run's artifact. A PASS must then still clear the hard gates requiring an unchanged HEAD and a clean worktree.

## Rationale and alternatives

An external copy is used instead of placing the harness directly in the candidate worktree to preserve both real code paths and verifiable immutability. Running directly in the candidate directory
would save one copy operation, but would allow test caches, temporary patches, or background processes to contaminate the deliverable; adding more static checks alone cannot address the current root cause of “lots of acceptance checks, but very toy functionality.”
Legacy recipes retain a compatibility branch for now; the v0.2 production entry point does not allow User Test to be bypassed.

## Runtime contract

`OPENAGENTS_USER_TEST_COMMAND` specifies the interaction harness, and `OPENAGENTS_USER_TEST_TRANSCRIPT` specifies a nonempty JSON array. String events
are encoded as `{"message": ...}`, while object events are sent unchanged as JSONL; each item may include `wait_seconds`. `OPENAGENTS_USER_TEST_TIMEOUT`
defaults to 900 seconds. The command runs in a disposable `repo/` under the artifact directory, and the candidate is read only through `git archive/clone`.

Each run leaves at least `input.jsonl`, `stdout.log`, `stderr.log`, `status.json`, and `workspace.diff`. In `status.json`,
`completed` means only that the harness exited normally, not that the goal was met; the Acceptance agent must write a
`source=user_test` behavior case based on the transcript and output. Other evidence can only provide supplementary explanation.

## Failure semantics

If the user test times out, its harness process group is terminated and `timed_out` is recorded; a nonzero exit records `crashed`; a copy or launch failure records
`setup_failed`. The model can never rewrite these statuses as PASS. When User Test is not configured, v0.2 does not fall back to the old component review path; instead, it returns
`PARTIAL` and requires explicit configuration.

## Migration

Direct calls to legacy recipes remain compatible with replay/variant manifests to avoid breaking the standard flow; v0.2 `OpenAgentsAdapter.accept`
always passes `require_user_test=True`, so production batches cannot bypass the real-interaction gate. Once User Test is stable on real harnesses, the
legacy acceptance compatibility branch will be retired.
