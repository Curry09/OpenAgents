---
number: "0081"
title: "Autonomous Failure Closure and the Single-Copy Prompt Contract"
issue: 0
slug: autonomous-failure-and-prompt-contract
summary: "Remove the needs-human control protocol, terminal label states, human stages, and hold entry points, closing the unattended state machine with bounded retries and the automation-failed machine terminal state; also require large dynamic materials to be transmitted only once through context, with runtime overlap checks and stdin transport preventing prompt duplication and argv bloat."
e2e:
  intent: "Prove that each invocation of every production role carries only one copy of dynamic material, and that the Claude Code subprocess neither exposes nor duplicates the prompt in argv; prove that model refusals, protocol errors, repeated crashes, zero progress, and timeouts all converge to an explainable automation-failed within a bounded number of invocations, that the model is not invoked again for the same facts, and that automation can revive the work on its own after the material facts change, with the entire active runtime surface no longer producing or consuming needs-human."
  method: "Run scripts/e2e-spec-0081-autonomous-failure-and-prompt-contract.sh; the script uses a recording backend to cover the actual assembly paths for triage, draft, architecture, implement, reply, test, review, and merge, uses a unique sentinel to assert that it appears exactly once in the final prompt, and uses a Popen seam to assert that the prompt is passed only through stdin; it then injects retryable crashes, legacy needs-human output, zero progress, and fact changes into a temporary SQLite queue and a fake forge, asserting bounded invocation counts, persistence of the automation-failed label and a signed diagnostic containing a fingerprint, no redispatch for unchanged facts, and automatic clearing of the failure state and re-enqueuing for changed facts; finally, it scans active source code, templates, CLI help, and desktop types, where needs-human, OWNER_HUMAN, and --hold must not appear except in the dedicated migration script."
architecture:
  objective: "Ensure that the OpenAgents unattended loop neither offloads work it cannot complete to a terminal state requiring human intervention nor retries indefinitely on identical inputs; also eliminate token waste, argv limits, and exposure in process listings caused by carrying duplicate role instructions and context."
  constraints:
    - "Deterministic safety gates for merging, CI, evidence stamps, branch ownership, and delivery authenticity must not be weakened or skipped as a result of removing the human intervention exit."
    - "Transient backend, network, process, and protocol failures may be retried only within the existing bounded budget; once it is exhausted, model invocations must stop and a machine-readable reason must be left behind."
    - "automation-failed must be bound to a facts fingerprint that excludes its own label; revival is allowed only when relevant facts change or an explicit retry is requested, and must not automatically burn through more model invocations on each tick."
    - "An IN_FLIGHT task whose process is alive and holding the lock must not be moved to a terminal state or reclaimed by the watchdog; failure of the holder after a hard timeout must still follow the same bounded retry path."
    - "context is the sole owner of large dynamic payloads; task contains only stable role instructions and short scalar locators, and the final model input contains at most one copy of each piece of dynamic material."
    - "The Claude Code prompt must be passed through stdin, with no prompt body in argv; stream-json output, tool events, token usage, and watchdog behavior remain unchanged."
    - "Legacy repository state must have an explicit, idempotent, auditable migration path; upgrading must not silently restart existing suspended objects."
  non-goals:
    - "There is no promise that the model can complete every issue, and automation-failed must not be presented as success."
    - "Do not remove the ability to reply to human comments; people can still supply additional facts, but waiting for a person is not a mandatory state in the automated flow."
    - "Do not change the boundaries of each role's business decisions, model selection, or the role decomposition used in the current slimming experiment."
    - "Do not introduce unlimited self-reflection, retry budgets shared across subjects, or a new external queue service in this spec."
  candidates:
    - id: rename-only
      layer: forge-label
      boundary:
        - needs-human label
      evidence:
        - "The current engine envelope, human owner, hold, watchdog, release, and desktop all depend on the same human-intervention semantics"
      tradeoffs: "Renaming is inexpensive, but it retains the old state machine that waits for people and cannot resolve unbounded redispatch or prompt duplication."
    - id: always-retry
      layer: vigil-reconciliation
      boundary:
        - queue attempts
        - watchdog
      evidence:
        - "Current poison tasks already require MAX_ATTEMPTS to prevent them from continually occupying slots"
      tradeoffs: "It appears unattended, but in practice it burns through model invocations indefinitely on identical facts and floods the queue."
    - id: fingerprinted-machine-failure
      layer: runtime-contract-and-orchestrator
      boundary:
        - prompt envelope
        - engine protocol
        - vigil state machine
        - forge projection
      evidence:
        - "vigil already has stable facts fingerprints, attempt stamps, queue attempts, and lock-aware reclamation primitives"
        - "E2BIG and the 1800-second outer timeout for GLM FP8 issue 17 were both projected as needs-human, but after fixing transport, restoring the checkpoint, and resolving network problems, the same work was ultimately merged, demonstrating that these were recoverable machine failures rather than business states that required human judgment"
      tradeoffs: "The migration surface is relatively large, but existing deterministic primitives can be reused to bind both stopping and revival to observable facts."
    - id: role-by-role-prompt-cleanup
      layer: agent-prompts
      boundary:
        - individual Template placeholders
      evidence:
        - "Architect already has a local fix to carry a single copy, while Curator, Drafter, Triager, and Replier can still duplicate payloads"
        - "Architect for issue 17 could start normally once its input was reduced from approximately 145 KB with the complete Spec appearing twice to 73,834 bytes with it appearing only once, but the backend was still subject to the approximately 128 KiB limit on a single argv argument"
      tradeoffs: "This can reduce current token usage, but without a runtime invariant, new roles or invocation sites can easily cause regressions."
  selected: fingerprinted-machine-failure
  affected-components:
    - "The single-copy input protocol for runtime.engine and runtime.context"
    - "stdin transport for ClaudeCodeBackend"
    - "Dynamic payload assembly in agents and recipes.stages"
    - "Classification, retries, watchdog, failure projection, and revival in recipes.vigil"
    - "Forge labels, runtime state, release, and desktop observability"
    - "agent_config, CLI, default configuration, and legacy state migration"
  failure-modes:
    - "If overly broad overlap validation incorrectly treats short scalars or common wording as duplicate payloads, the backend will not be invoked and the specific conflicting segments will be reported; tests must cover permitted short scalars."
    - "If writing to stdin fails, the subprocess exits early, or the pipe closes, the backend must propagate the error using the existing nonzero invocation failure behavior; it must not swallow the error or lose watchdog reclamation."
    - "If the failure fingerprint includes the automation-failed label itself, it will trigger its own revival; failure projection fields must be explicitly excluded from the calculation."
    - "If the queue row is deleted before writing to the forge after the retry limit is reached, a transient forge failure will reset attempts; the failure projection must first be persisted atomically, and only then may the queue row be deleted."
    - "If legacy needs-human objects are not migrated and the runtime no longer recognizes them, they may restart unexpectedly; the pre-upgrade check must fail-closed, and vigil may start only after the migration command completes."
    - "Silently changing legacy human configuration to skip would weaken safety gates; the loader must reject it and instruct the user to change it to agent, rather than guessing the intended migration."
verification:
  behavior-cases:
    - id: prompt-payload-single-copy
      polarity: positive
      stimulus: "Run every production role's assembly path with issue, comment, Spec, evidence, and ready issue snapshots containing unique long sentinels"
      expected: "The task received by the backend does not contain the dynamic payload, context contains exactly one copy, and the sentinel appears exactly once in the final assembled prompt"
      observation: "The task/context captured by the recording backend and the _build_prompt result"
    - id: duplicate-payload-rejected-before-dispatch
      polarity: negative
      stimulus: "When calling run_agent, inject the same non-short dynamic text through both a Template placeholder and context"
      expected: "Raise AgentOutputError, with the error identifying the duplicate segment and the backend invocation count equal to zero"
      observation: "The exception and spy count in tests/test_runtime_engine.py"
    - id: prompt-not-in-argv
      polarity: negative
      stimulus: "Pass a prompt whose length exceeds the typical ARG_MAX risk threshold and that contains a secret sentinel"
      expected: "Popen argv contains neither the sentinel nor the prompt body, stdin receives the complete input exactly once, and the stream-json result is parsed as usual"
      observation: "The Popen seam and result assertions in tests/test_backend_claude_code.py"
    - id: bounded-failure-convergence
      polarity: positive
      stimulus: "Repeatedly trigger backend crashes, protocol errors, or a legacy agent needs_human envelope for the same subject"
      expected: "Within no more than MAX_ATTEMPTS invocations, apply automation-failed, delete the queue row, and record category/attempts/fingerprint; subsequent ticks with identical facts do not invoke the backend again"
      observation: "The temporary queue, fake forge labels/comments, and backend invocation count"
    - id: changed-facts-auto-revive
      polarity: positive
      stimulus: "After automation-failed, change one of the issue body, PR head, CI, comments, or dependency completion status"
      expected: "The new fingerprint differs from the failure stamp, and Vigil automatically clears the failure projection and reclassifies based on the new facts; no dedicated human signal is required"
      observation: "The fake forge call order and re-enqueue records"
    - id: live-holder-not-terminalized
      polarity: negative
      stimulus: "A claimed row exceeds the age threshold, but its corresponding flock is still held by a live agent process"
      expected: "Record only stalled telemetry: do not add automation-failed, delete the row, or reclaim it; reclamation and retry rules take over only after the holder exits"
      observation: "Labels, queue owner, and concurrent invocation count in the multiprocess lock e2e"
    - id: legacy-state-fails-closed-until-migrated
      polarity: negative
      stimulus: "The repository contains a legacy needs-human label, a blocked run, or stages owner=human"
      expected: "vigil startup reports a migration diagnostic and makes zero agent invocations; startup is allowed after the migration command idempotently rewrites label/state, while human configuration must still be explicitly changed to agent"
      observation: "Forge/state/config snapshots before and after the migration script, and process exit codes"
  repository-invariants:
    - "needs-human, NeedsHumanRequest, OWNER_HUMAN, and --hold no longer appear in active Python, TypeScript, default configuration, README, or CLI help, except in the dedicated migration script and historical specs/evidence."
    - "The engine no longer accepts any role-level human-control envelope; model output containing needs_human can only become an ordinary protocol error and enter the bounded failure path."
    - "automation-failed is the forge projection of failure facts, not a state requiring a human reply; diagnostic messages must not promise to \"wait for you,\" say \"remove the label to continue,\" or \"hand off to a person.\""
    - "The same unchanged fingerprint consumes at most one group of action attempts and one idempotent failure diagnostic; the total number of process-level retries does not exceed the existing MAX_ATTEMPTS."
    - "The failure fingerprint excludes the automation-failed label, signed failure comments, and local queue metadata, but covers all remote facts that would change the next action."
    - "All prompt assembly tests assert that dynamic payloads appear only once, and Claude Code argv contains only the executable name, mode parameters, and output control parameters."
  exemptions: []
tasks:
  - id: T1
    title: "Single-Copy Prompt Envelope and Retirement of the needs-human Model Protocol"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - openagents/runtime/engine.py
      - openagents/runtime/context.py
      - openagents/backends/claude_code.py
      - openagents/agents/admitter.py
      - openagents/agents/architect.py
      - openagents/agents/curator.py
      - openagents/agents/deliver.py
      - openagents/agents/drafter.py
      - openagents/agents/implementer.py
      - openagents/agents/merger.py
      - openagents/agents/replier.py
      - openagents/agents/reviewer.py
      - openagents/agents/tester.py
      - openagents/agents/triager.py
      - openagents/recipes/stages.py
      - tests/test_runtime_engine.py
      - tests/test_runtime_context.py
      - tests/test_runtime_context_issue_reply.py
      - tests/test_backend_claude_code.py
      - tests/test_agents_architect.py
      - tests/test_agents_deliver.py
      - tests/test_agents_docstring_rule.py
      - tests/test_agents_drafter.py
      - tests/test_agents_merger.py
      - tests/test_agents_prompts.py
      - tests/test_agents_replier_issue.py
      - tests/test_agents_triager_replier.py
      - tests/test_recipe_stages.py
      - tests/test_prompt_contract.py
    scope: "Define calls between engine/backend explicitly as a single envelope containing instructions task + dynamic context: role Template retains only stable instructions and short scalars, while issue bodies, comments, Spec, snapshots, feedback, and evidence are all carried in titled sections in context; before dispatching to the backend, the engine performs a normalized overlap check on the rendered task/context and rejects duplicated dynamic segments that are not short. Change ClaudeCodeBackend to use claude -p to read the final prompt from stdin, so argv no longer carries the body, while preserving stream, watchdog, tool events, and usage. Delete NeedsHumanRequest, needs_human envelope recognition, and human intervention exits from role prompts; propagate legacy envelopes as schema/protocol errors."
    acceptance: "Unit tests cover sentinel single-copy counts along the actual invocation path of every production role, rejection of duplicate payloads before they reach the backend, and the absence of false positives for shared short ID/branch scalars; a Popen spy proves that an exceptionally long prompt is written to stdin only once and that argv contains no body, with no regressions in normal/nonzero-exit/timeout/usage paths; the engine reports a protocol error for legacy needs_human JSON and no longer exposes NeedsHumanRequest."
  - id: T2
    title: "Fingerprint-Bound Autonomous Failure Closure and Automatic Revival"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - openagents/runtime/gates.py
      - openagents/runtime/legacy.py
      - openagents/runtime/state.py
      - openagents/runtime/token_usage.py
      - openagents/utils/blocknote.py
      - openagents/utils/forge.py
      - openagents/utils/gitea.py
      - openagents/utils/github.py
      - openagents/utils/notes.py
      - openagents/utils/release.py
      - openagents/utils/workspace.py
      - openagents/desktop/daemon.py
      - apps/desktop/src/renderer/src/types.ts
      - apps/desktop/src/renderer/src/nav/pending.ts
      - apps/desktop/src/renderer/src/nav/pending.test.ts
      - tests/conftest.py
      - tests/test_blocknote.py
      - tests/test_blocknote_hold_merge.py
      - tests/test_desktop_daemon.py
      - tests/test_ensure_prerequisites.py
      - tests/test_gitea_driver.py
      - tests/test_github.py
      - tests/test_github_remove_label.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil_admit.py
      - tests/test_recipe_vigil_queue.py
      - tests/test_recipe_vigil_timing.py
      - tests/test_release.py
      - tests/test_runtime_gates.py
      - tests/test_runtime_state_converge.py
    scope: "Replace the human terminal state with automation-failed and rewrite Vigil closure: triage rejection, invalid dependency suggestions, consecutive claim failures, hard timeouts, excessive age with zero progress, and action exceptions are all normalized into idempotent signed diagnostics based on category/attempts/fingerprint; stop redispatching for the same fingerprint, and automatically clear projections and classify again from the beginning when facts change. For a live lock holder in IN_FLIGHT, only issue a warning; do not transition it to a terminal state. forge prerequisites, release, runtime state, token status, and desktop items awaiting review all consume machine failure semantics consistently; delete display surfaces such as blocknote that serve only human suspension."
    acceptance: "queue/fingerprint/watchdog tests prove bounded failure calls, persistence to forge before row deletion, zero redispatches for unchanged facts, automatic revival when any action-relevant fact changes, and that a live lock holder is never marked as failed or run twice concurrently; release rejects unresolved automation-failed states; desktop displays automation-failed without wording about waiting for a human; all relevant Python and TypeScript tests pass."
  - id: T3
    title: "Removal of Human Stage Owners, the hold CLI, and Configuration Surfaces"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - openagents/cli.py
      - openagents/data/openagents.yml.template
      - openagents/utils/agent_config.py
      - openagents/utils/fleet.py
      - openagents/utils/hold.py
      - openagents/utils/skip.py
      - tests/test_agent_config.py
      - tests/test_cli.py
      - tests/test_cli_new_stack.py
      - tests/test_hold.py
      - tests/test_skip.py
    scope: "Remove human owner from the stage schema, resolved policy, default templates, and routing; delete --hold, the legacy Hold value object, and hold/skip conflict logic, retaining skip while continuing to enforce the constraint that execution must not proceed with zero safety gates. Existing YAML containing human must produce a fail-closed migration error that names the stage, and must not silently become skip; clean up CLI help, init output, and fleet passthrough accordingly."
    acceptance: "The loader accepts only the valid subset of agent/skip for each stage; human configuration produces an actionable error with zero side effects; oa vigil --help no longer exposes --hold, and passing the legacy argument exits with a nonzero status; default templates support round-trip processing and retain fully automated, safe defaults; no active imports are left dangling after module deletion, and all CLI/config tests pass."
  - id: T4
    title: "Legacy State Migration, Current Documentation, and End-to-End Proof of Retirement"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - README.md
      - docs/specs/0081-autonomous-failure-and-prompt-contract.md
      - scripts/e2e-spec-0058-needs-human-reply-unblock.sh
      - scripts/e2e-spec-0081-autonomous-failure-and-prompt-contract.sh
      - scripts/migrate-needs-human-state.py
      - tests/test_migrate_needs_human_state.py
    scope: "Provide an explicit, idempotent migrator: when legacy needs-human forge objects or blocked runtime runs are found, first generate an audit plan, then map them to automation-failed through an explicit apply while preserving the original reasons; do not automatically rewrite human YAML, and report only paths and stages. Update README to reflect current behavior, retire the old reply-unblock e2e, and add comprehensive e2e coverage for single-copy prompts, bounded failures, revival after facts change, startup blocking for legacy states, and active source scanning. Preserve historical spec/evidence verbatim as design history."
    acceptance: "Migration dry-run performs zero writes; apply is repeatable and the second execution is a no-op, and partial forge failures can be rerun safely; while legacy objects remain unmigrated, vigil fails closed and does not dispatch to models, and all e2e tests pass after migration; scans of active code/templates/README/CLI help find no needs-human/NeedsHumanRequest/OWNER_HUMAN/--hold except in migration scripts; spec validate, render, and graph --check all pass."
---

# 0081 · Autonomous Failure Closure and the Single-Copy Prompt Contract

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

OpenAgents will no longer route work that the model or pipeline cannot complete to `needs-human`. Transient errors will continue to be retried within a strict budget; budget exhaustion under unchanged remote facts, deterministic rejection, or zero progress will converge to an `automation-failed` machine terminal state carrying a reason, attempt count, and facts fingerprint. This terminal state does not require a human reply: once relevant facts change, automation will clear the old failure projection and reassess; if the facts remain unchanged, it will stop consuming model resources.

The same change will also consolidate model input into a single-copy prompt envelope. The role task will contain only stable responsibilities and short scalars, while dynamic material such as issues, comments, Specs, snapshots, feedback, and evidence will appear only in context; the engine will reject duplicate sections before dispatch, and Claude Code will receive the final prompt through stdin, avoiding duplicate tokens, command-line length limits, and exposure in process listings.

## Motivation

The current system uses `needs-human` simultaneously as a first-class model control output, a Vigil terminal state, an exit for queue poison pills, a watchdog exit, a way to represent human stage owners, a release-blocking condition, and the highest desktop priority. This welds “automation cannot do it” and “a human decision is required” into the same thing. In actual unattended experiments, a killed model process, endpoint instability, protocol parsing failure, or zero progress in the same state does not equate to a need for product judgment; applying a human-intervention label both obscures the machine failure category and makes subsequent recovery depend on someone removing the label.

Removing the label alone is not enough. Without new termination semantics, poison-pill tasks will be enqueued again on every tick, repeatedly consuming model resources; if all failures terminate immediately, transient 429s, process exits, and asynchronous CI windows will be misclassified as permanent failures. Stopping conditions must therefore be tied to “retry budget + current facts fingerprint,” and recovery conditions must be tied to “facts have actually changed,” rather than whether someone has spoken.

Model input has another problem that surfaced earlier: if a role Template has already expanded the issue body, comments, or ready snapshot, and the caller also puts the same material in `context`, the backend concatenates both copies into the same final prompt. A local Architect patch demonstrated that one instance could be removed manually, but paths such as Curator’s snapshot, Drafter’s detail/context, and Triager’s and Replier’s body/context still allow recurrence. Meanwhile, ClaudeCodeBackend puts the entire final prompt in `argv`, so long inputs hit `ARG_MAX` and expose their contents in process listings. Single-copy ownership needs to become a runtime contract rather than remain a convention maintained role by role.

### Experimental evidence (2026-08-28 to 2026-08-30)

This design was not derived solely from static code review. The three-task unattended GLM-5.2 FP8 run and subsequent continuation experiments retained manifests, token/tool ledgers, containers, and final Git/Gitea states; the consolidated report is at `/root/src/openagents-model-capability-threshold-experiment.md`, and the independent process audit is at `/root/src/auto-designer-experiments/20260828-harness-v2-r3-design-glm52fp8-5/openagents-process-audit-20260829.md`. Observations directly relevant to this spec are:

- After the full Spec for issue #17 was included in both task/context, the final prompt was approximately 145 KB, the Spec appeared twice, and all three attempts failed with `Argument list too long` before the `claude` process started. A minimal local reproduction could launch with a single argument of 131,071 bytes, but 131,072 bytes produced `errno=7 E2BIG`, so this was neither a model capability failure nor an API failure.
- After changing only Architect’s Spec to a single copy in context, the prompt dropped to 73,834 bytes, the Spec appeared only once, and Architect started normally and achieved PASS; however, the backend still used argv, demonstrating that local role deduplication can only mitigate the problem, while stdin is the fundamental transport fix.
- Treating deterministic E2BIG as an ordinary Exception caused an excessively broad fallback, making Drafter run three times in total; the two extra runs wasted approximately 4m52s and 1,170,901 tokens. The Implementer, which subsequently maintained continuous tool activity, was then killed by the outer 1800-second hard timeout and assigned `needs-human`. After restoring the checkpoint, correcting the network, and retaining the backend idle watchdog, implementation, 138 tests, review, and merge were all completed for the same issue, and the final repository state for the three tasks was 3/3 merged. Both `needs-human` outcomes were therefore incorrect projections of machine faults, rather than missing human business decisions.
- All four primary/recovery containers eventually exited with 137, but Docker reported `OOMKilled=false`, and their application logs had already stopped at either a failure projection or merged/frontier-empty; an exit code cannot directly serve as the application terminal state and must be classified together with lock ownership, invocation events, and remote facts.
- The process review confirmed that effective Curator and Drafter runs still transmitted the same payload twice, and Triager and both types of Replier also had code paths that transmitted identical text twice; 166 checks covering backend/protocol/telemetry and workspace/context/prompt passed, but at that time they did not cover the invariant that “all active roles have a single copy of each dynamic payload.”
- Subsequent paired Drafter experiments further demonstrated that “retaining file checkpoints and starting a separate short repair after validator failure” could pass all quality gates while reducing tokens for #16/#18 by 52.2% and 39.9%, respectively; directly resuming a huge session instead increased them by 47.4% and 46.1%. This supports retaining deterministic checkpoints/fingerprints in this spec and retrying only with new facts or a minimal failure summary, rather than resuming or replaying the entire old prompt.
- In the Implementer segmentation experiment, input for the effective editing chain fell by 74.9%, but only 81/82 tests passed, and T3b/T4 were not completed; this spec therefore does not declare the Implementer segmentation approach a validated optimization, nor does it use that experiment as grounds to remove Implementer/Reviewer. It addresses only the input transport and failure closure problems conclusively established by complete counterexamples.

These figures serve only to establish the intervention layer and failure semantics, and are not extrapolated into a general model success rate; token/cache accounting conventions from different providers are also not used for cross-model cost comparisons.

## Guide-level explanation

After the upgrade, ordinary operators will see only three kinds of progression outcomes: successful progress, retryable failure, and `automation-failed`. For example, if an agent fails to finish three consecutive times because the backend process exits, Vigil will write a signed diagnostic to the corresponding issue/PR and add `automation-failed`:

```text
OpenAgents automation failed
category: backend-error
attempts: 3
fingerprint: 9f2a1c...
last_error: Claude Code CLI exited 137
```

As long as facts that affect the next action—such as the issue body, PR head, CI, dependencies, and applicable comments—remain unchanged, subsequent ticks will only observe this terminal state and will no longer invoke the model. If someone supplements the issue, an external system pushes a new commit, the CI conclusion changes, or a dependency is merged, the new fingerprint will differ from the failure stamp, and Vigil will clear `automation-failed` itself and resume progression from the top of the decision table. This is “new evidence triggers an automatic retry,” rather than “wait for someone to unblock it.”

Each optional stage in the configuration can only be executed by `agent` or, where permitted, set to `skip`; `human` and the command-line `--hold` are removed. Old configurations will not be migrated speculatively: startup will report an error naming the offending setting and require the operator to explicitly select `agent`. Old forge labels and runtime `blocked` states, however, will be converted through a one-time explicit migration command, because they represent actual objects that have already stopped, and silently ignoring them would unexpectedly restart work.

For model invocations, callers still pass `task` and `context`, but their meanings become strict:

```text
task    = stable role instructions + short locators such as issue/pr number, mode, and branch
context = dynamic [issue] / [comment] / [spec] / [feedback] / [evidence] sections, one copy each
```

If the same dynamic text section appears on both sides, the engine reports an error before starting the backend. The backend ultimately assembles guardrail, task, and context exactly once and feeds them to `claude -p` through stdin; the body does not appear in argv.

## Reference-level explanation

### 1. Single-copy prompt envelope

`runtime.context` becomes the sole assembly layer for all dynamic material. Each context section uses a stable heading to identify its source; Agent Templates remove large placeholders such as `$issue_body`, `$comment_body`, `$issue_snapshot`, `$dialogue`, `$detail`, and `$spec_text`, retaining only short scalars such as numbers, mode, branch, and commands. Evidence is appended to context exactly once.

`engine.run_agent` performs overlap validation after Template rendering and before the backend call. Validation normalizes line breaks and runs of whitespace, and compares non-short sections in context as well as the string placeholder values for the current invocation; if a dynamic section appears in full in both task and context, it raises `AgentOutputError`, with an error containing the role and a truncated section summary. Short numbers, branch names, protocol keywords, and the like may appear on both sides to prevent false positives. This check is a hard gate against regressions; role invocation tests must still individually demonstrate that normal paths contain no duplication.

`ClaudeCodeBackend` launches the subprocess with `claude -p --permission-mode ... --output-format stream-json --verbose`, without the body, writes the final prompt once through `stdin=PIPE`, and then closes stdin. Line-by-line stdout reading, the watchdog, subprocess registration, and result/usage/tool event parsing retain their existing semantics. stdin write failures, early exits, and BrokenPipe are all normalized into existing backend failures and passed upstream for retry.

### 2. Retirement of the model control protocol

Remove `NeedsHumanRequest` and the special handling of `{"needs_human": true, ...}`. Each role may return only its own `OUTPUT_SCHEMA`: a negative judgment is expressed using the existing `REWORK`, `false`, `delivered=false`, or `merged=false`; actual backend/protocol errors raise exceptions. If an old model still returns needs_human, it becomes a `protocol_error` because it does not conform to the role schema, and is handled by Vigil’s unified bounded retries. The model no longer directly determines orchestration terminal states or writes to the forge.

`admitter` is removed along with `triage: human`. Ordinary human comments are still handled by replier and remain one source of new facts, but do not serve as a dedicated unblocking protocol.

### 3. `automation-failed` projection

The forge adds a single label constant, `AUTOMATION_FAILED_LABEL = "automation-failed"`, replacing BLOCKED/needs-human naming in active code. Failure diagnostics contain at least: `category`, `attempts`, the facts fingerprint excluding the failure projection, the last error summary, and a timestamp. Comments use the existing identity signature and are idempotent by `(subject, fingerprint, category)`; the label and comment must be successfully written to the forge before the queue entry can be deleted, preventing transient forge failures from resetting attempts to zero.

Failure categories distinguish at least: `backend-error`, `protocol-error`, `no-progress`, `invalid-input`, `invalid-dependency`, `action-timeout`, and `deterministic-gate`. These categories are used for diagnostics and statistics and do not change safety hard gates.

### 4. Classification, stopping, and revival

`_classify` does not unconditionally place `automation-failed` ahead of all branches. It first reads the most recent valid signed failure stamp:

1. Compute the current fingerprint from remote facts, excluding the `automation-failed` label, failure comments, and queue fields;
2. If it matches the failure stamp, return `TERMINAL(automation-failed)` without enqueueing;
3. If it differs, mechanically remove the failure label, retain historical diagnostic comments, and reassess the new facts from the top of the classification table.

Explicitly removing the failure label can serve as an operational forced retry, but is not a human protocol on which the pipeline depends; while the failure stamp remains, the producer treats “the label has been explicitly removed” as permission for one retry, and any new failure is still subject to the full budget. The implementation must avoid automatically clearing and then reapplying the label on every tick.

Exceptions during a claim continue to use `_MAX_ATTEMPTS`. Within the same queue lifecycle, the entry returns to the queue if the limit has not been reached; at the limit, the failure projection is written before the row is deleted. When an agent returns a normal schema but the remote fingerprint has not changed by even one byte, record an attempt stamp and, after the grace period for asynchronous effects expires, project `no-progress` rather than repeatedly invoking the model. Natural waits in QUIET for CI, mergeability, blockers, and similar conditions continue to follow their respective thresholds and become machine failures only after an explicit limit is exceeded.

The IN_FLIGHT watchdog must first verify whether the lock holder is alive. If a live holder exceeds the age threshold, write only telemetry/logs; do not add a failure label or delete the claimed row. An actual `_TimedBackend` hard timeout is handled by the holder killing the process and raising an error, which then enters the attempts rules above. This prevents removal of the human exit from reintroducing duplicate execution.

### 5. Configuration and product surface

`OWNER_HUMAN`, the `human` enum value in every stage, `--hold`, the old Hold model, and the `triage: human` conversation path are all removed. The set of stages that allow skip remains unchanged; conflict/merge, which cannot be skipped, must still use agent; combinations with zero safety gates, such as `review: skip + merge: agent`, continue to be rejected. Legacy YAML containing human must produce a precise configuration error and must never be silently interpreted as skip.

release fails closed for unresolved `automation-failed` runs/PRs. desktop displays them as machine failures awaiting review, but its wording does not require human input. The old blocking-note module and the promise that “removing the label/replying resumes execution” are retired.

### 6. Migration and compatibility

If the upgrade check finds a legacy `needs-human` label or a runtime `blocked` run, Vigil exits before any agent invocation and prints the migration command. A dedicated script defaults to dry-run and lists the issues/PRs/runs it would modify; after an explicit `--apply`, it adds `automation-failed` and migration-signature diagnostics to the objects, then removes the old labels and changes the local run state to `failed`. This ordering ensures that the script can be rerun after an intermediate failure and that objects never briefly lack a terminal state. Historical specs/evidence retain the old terms as design history; within active source code, only the migration script may contain the legacy literals.

### 7. DAG and file ownership

`T1` first establishes the model input and output protocol; `T2` rewrites the failure state machine on that foundation. `T3` can clean up the configuration surface in parallel with `T1`; `T4` completes migration and comprehensive verification after both the state machine and configuration have stabilized. Each Task's `files` in frontmatter are mutually exclusive to avoid conflicts between parallel writers.

The end-to-end entry point is `scripts/e2e-spec-0081-autonomous-failure-and-prompt-contract.sh`. All tests use temporary repositories, temporary queues, and fake forge/backend implementations, without accessing real issues, PRs, or model services.

## Drawbacks

`automation-failed` is still a terminal-state label; it addresses “the machine has explicitly failed and stopped spending money,” without magically improving model capabilities. Compared with the previous behavior, where anyone could remove a label to trigger a rerun, fingerprint binding and migration checks increase state-machine complexity. Runtime overlap checks may also produce false positives on borderline wording, so the boundary between “dynamic segments” and “short scalars” must be expressed as testable rules rather than fuzzy similarity.

Removing the `human` owner means that OpenAgents no longer provides a mode for human approval at each stage. Teams that need human governance must use protected branches or forge permissions, or disable automatic merge, outside the automation; this deliberately narrows the product's commitments, but constitutes an incompatible configuration change.

The stdin changes touch process-lifecycle details. If the write end is not closed promptly, Claude CLI will wait for EOF; if a synchronous write of very long input blocks while stdout has not yet been consumed, pipe backpressure could theoretically occur. The implementation should use a safe approach equivalent to communicate or a separate, controlled writer, while retaining streaming reads and the watchdog.

## Rationale and alternatives

Fingerprint-bound machine failure was chosen because the existing Vigil already has a stable hash over all `_Facts` fields, an attempt stamp, SQLite attempts, and flock-based proof of liveness, so most of the required mechanisms already exist; the new design simply changes them from “eventually call a human” to “stop on the same evidence, revive on new evidence.” It satisfies both bounded costs and autonomous recovery without requiring a new service.

Simply renaming `needs-human` to `automation-failed` was rejected: the old “revive when a human replies/removes the label” behavior and the human owner would remain, leaving the concept intact. Unlimited automatic retries were rejected: the expected benefit from the same prompt and facts is close to zero, turning a model failure into a resource incident. Closing the issue/PR after failure was rejected: closing is a stronger action in human collaboration that could cause unintended harm, whereas a failure label preserves the work and diagnostics.

On the prompt side, fixing only the current few duplicate call sites was rejected because Architect has already demonstrated that local patches cannot protect future paths. Putting all context directly back into Template was also rejected: that would lose the task/context separation and continue to let each role invent its own format. The choice is “single ownership of context + a hard engine gate + role-path tests,” aligning the contract, detection, and evidence across all three layers.

Claude CLI does not continue to use argv because stdin is a standard input channel already supported by its print mode, eliminating both `ARG_MAX` limits and exposure through process listings; this does not reduce model tokens, but ensures that the single, streamlined copy of the content can be safely transmitted at any length.

## Prior art

Build systems commonly cache failure or success results by a hash of the input content and execute again only when the input changes; this spec's failure fingerprint follows the same principle. Message queues likewise isolate poison messages in a dead-letter queue after a finite number of delivery attempts, but here no second queue is created: the failure projection remains in the forge source of truth, and new facts can automatically revive execution.

Claude Code's non-interactive print mode supports reading prompts from stdin; Unix tools also commonly put large payloads in stdin/files and reserve argv for control parameters. OpenAgents' existing `runtime.context`, `engine.run_agent`, `_fingerprint`, queue attempts, and process locks provide direct precedents for this approach.

## Unresolved questions

1. The initial version retains the existing `_MAX_ATTEMPTS` and all QUIET watchdog thresholds, without retuning them in this spec; calibration by failure category will follow once sufficient token usage data is available.
2. Whether explicitly deleting the `automation-failed` label should remain a permanent entry point for forced retries, or whether a separate `oa retry <subject>` should be added later to leave a clearer audit event, is left to operational feedback.
3. The initial runtime overlap detection uses deterministic full-segment matching, without fuzzy semantic deduplication; token redundancy caused by synonymous rewording will be assessed using subsequent observability data.

## Future possibilities

Failure rates could be aggregated by `category × role × model` to dynamically select shorter sessions, fallback backends, or stricter budgets; automation-failed events could also be exported to monitoring and alerting, but alerts would still not become inputs required for the pipeline to continue.

The prompt envelope could later evolve from a string with headings into a structured list of sections, with token budgets, truncation priorities, content hashes, and cache reuse handled uniformly at the backend boundary. If multiple backends support file input, a read-only context artifact could also be passed, further avoiding copies of large text between processes.
