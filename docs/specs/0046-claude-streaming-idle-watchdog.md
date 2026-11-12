---
number: "0046"
title: "Claude silence timeout and shared invocation time budget"
issue: 148
slug: claude-streaming-idle-watchdog
summary: "Claude stops invocations after a continuous period without output; Vigil and Claude share the existing total-duration configuration, record prolonged absence of output and budget exhaustion separately, and retain the existing termination and bounded retry flows."
e2e:
  intent: "Verify termination after prolonged silence, budget exhaustion during active streaming, consistency between Vigil and backend budgets, budget disabling, and compatibility with process ownership and requeuing."
  method: "bash scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh\nUse a fake Popen, real threads, and controlled events, without invoking real models or remote repositories; verify defaults, overrides, invalid values, and the disabled configuration,\nand verify that reaching the total duration limit and prolonged periods without output each record the actual reason. Continuous output does not extend the time limit, and unfinished work does not count as successful delivery."
tasks:
  - id: T1
    title: "Shared time budget for the backend watchdog and Vigil"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backends/base.py
      - openagents/backends/claude_code.py
      - openagents/recipes/vigil.py
    scope: "Code changes are complete. Reading the existing total-duration setting has been moved into the common backend layer for reuse by both Vigil dispatch entry points; silence timing, termination, locking, and retry flows are retained, with changes limited to unifying configuration and correcting termination reasons."
    acceptance: "Vigil no longer overrides the configuration with a fixed 1800 seconds; disabling the budget does not cause an immediate timeout; exhaustion of the total-duration budget is not described as a hang; silence indicates only a prolonged absence of output."
  - id: T2
    title: "Hermetic regression tests and offline validation entry point"
    status: done
    priority: P1
    tags: []
    depends-on: [T1]
    relates-to: []
    parallel: false
    files:
      - tests/test_backend_claude_code.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil.py
      - scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh
    scope: "Code changes are complete. Validation covers whether the configuration actually reaches the dispatch path, disablement semantics, compatibility with healthy streaming output, the two categories of termination reasons, and existing process ownership, locking, and bounded retries."
    acceptance: "Targeted pytest tests, Ruff, and spec validation passed; no real model or long waits are required; no claim is made that production completion rates or cost benefits have been measured."
---

# 0046 · Claude Idle Timeout and Shared Invocation Time Budget

## Summary

Retain the two existing mechanisms: an idle timeout detects prolonged periods without output, and a total duration budget limits the time invested in a single invocation.
Vigil and the Claude backend share the existing `OPENAGENTS_CLAUDE_MAX_WALL` configuration, removing Vigil's separate
1800-second constant. Reaching the total duration limit means only that the budget has been exhausted; it does not prove that the agent is hung. Continuous output does not prove meaningful progress either.

## Motivation

Larger development tasks may involve implementation, testing, and integration into the main branch. Previously, the Claude backend allowed 3600 seconds by default,
while Vigil terminated invocations at a fixed outer limit of 1800 seconds, ending still-active invocations prematurely and incorrectly describing them as hung.
This change unifies the configuration and the wording used to describe the reasons, while continuing to use the existing scheduling, workspaces, and bounded retries; it does not add progress scoring,
a wrap-up phase under a soft budget, handoff summaries, or continuation state.

## Guide-level explanation

| Configuration | Default | Meaning |
|---|---|---|
| `OPENAGENTS_CLAUDE_IDLE_TIMEOUT` | 300 seconds | The limit on how long Claude can go without new output |
| `OPENAGENTS_CLAUDE_MAX_WALL` | 3600 seconds | The total duration budget per invocation, shared by Claude and invocations wrapped by Vigil |

The total duration variable retains its original name for compatibility with existing deployments. In Vigil, it applies to all backend invocations that Vigil wraps; standalone non-Claude
backends do not gain a watchdog as a result. Unset, blank, or invalid values use the default; finite values less than or equal to zero disable
the corresponding limit. NaN/Infinity values for the total duration are treated as invalid, so a bad configuration does not cause unlimited execution or immediate termination.

For example, setting `OPENAGENTS_CLAUDE_MAX_WALL=5400` makes both Vigil and Claude use a 5400-second budget;
setting it to zero disables both total duration limits, while Claude's idle timeout remains independently in effect.
The default limit for a single Vigil invocation changes from 1800 seconds to 3600 seconds, allowing longer runs and potentially increasing the cost of inefficient tasks.
The budget is timed per invocation and does not reset on new output or new tool activity; it is not a cumulative budget per issue.

## Reference-level explanation

`backends.base.effective_max_wall()` is the sole source for reading the total duration configuration; the Claude module retains the export with the same name
and `MAX_WALL_ENV` for compatibility with callers. Both Vigil's admission and execution entry points use this accessor to construct the existing
`_TimedBackend`. When the budget is disabled, `thread.join` waits indefinitely, while the original process tracking and lock registration still take place.

The timing scopes of the two layers remain unchanged: Vigil covers the entire `backend.run`, while Claude covers its streaming invocation; with the same
budget, the outer layer may terminate first, but there is no longer a hidden, shorter budget. Termination and cleanup remain subject to the existing scheduling/reaping delays.
The idle timer still resets on every output line, including blank lines; it is not elevated into a measure of meaningful progress.

Termination reasons are explicitly distinguished:

- Idle watchdog: no output for a prolonged period; this does not imply deadlock or the absence of meaningful work.
- Total duration watchdog and `_ActTimeout`: the time budget for this invocation has been exhausted; this does not imply that the invocation is hung or that the task is complete.

Exception types, process claiming and termination, flock, attempt counts, and the requeueing flow remain unchanged. Backend exceptions are recorded through
the original path, and Vigil's total budget exceptions are also handled through the existing bounded retry mechanism, with processing brought to a close once the retry limit is reached.
Termination remains best-effort. This set of changes adds no recovery guarantees and does not treat a timeout as passing acceptance criteria.

## Drawbacks

Allowing longer runs by default increases the time some tasks occupy a slot. Silence may result from a quiet, long-running operation; continuous output may
result from a loop. Both limits are runtime policies and cannot independently establish task quality. Disabling the total budget is an explicit configuration choice;
the framework does not automatically disable it upon observing activity.

## Rationale and alternatives

Reusing the existing configuration, accessor, and exception paths addresses the hidden limit and incorrectly reported reasons. Automatic continuation in segments would introduce context
handoff costs and new recovery state, while progress scoring would introduce misjudgments; this set of changes does not require these mechanisms.

## Prior art

The original 0046 introduced Claude's streaming idle watchdog and total duration limit; the Vigil wrapper in 0065 tracks and terminates processes belonging to the current
invocation, with the holder responsible for queue finalization. This change connects the two existing total duration entry points to the same configuration without replacing them.

## Unresolved questions

More appropriate budget values should be determined based on actual task durations and resource costs; targeted regression testing verifies only the mechanisms and compatibility.
Comparisons with historical experiments must record the actual configuration; gains from an increased budget cannot be attributed directly to harness improvements.

## Future possibilities

If reproducible recovery losses or unproductive loops remain after unifying the budget, design separate solutions based on specific evidence; do not add entities in advance.
