---
number: "0082"
title: "Preserving the minimal goal and the generation delivery flow"
issue: 0
slug: minimal-objective-delivery-flow
summary: "Add minimal and generate-only delivery flows: both first write a compact Spec; the former has a single acceptance pass, while the latter uses a constrained executor to produce a PR directly and merge it mechanically, for isolated generation experiments without quality gates."
architecture:
  objective: "While preserving the current standard flow, provide a minimal delivery flow that treats the original issue as the final authority, fixed at three judgment calls: a compact Spec, one implementation, and one acceptance review of the results; difficult objectives must not automatically become PASS by narrowing the Spec."
  constraints:
    - "The original issue title and body always enter the context of the Spec Writer, Implementer, and Acceptance Reviewer; the Spec may only choose the implementation path and must not lower the original objective."
    - "The Spec Writer must return BLOCKED if it cannot provide an implementable plan covering the entire objective; the Acceptance Reviewer may return only PASS, PARTIAL, or FAIL, and only PASS may grant merge authorization."
    - "The minimal flow does not call Architect, Tester, the traditional Reviewer, or the Merger LLM; CI, repository integrity, head binding, and rereading before merge remain enforced by deterministic hard gates."
    - "The default behavior of the standard flow remains compatible with existing configurations."
    - "generate-only retains the Spec Writer and removes the subjective Implementer and Acceptance roles; it retains only structural hard gates such as the compact objective digest, head, evidence stamp, worktree, PR SHA, and conflicts, and moves quality validation to offline execution after the experiment; it must not apply standard's repository-wide gate for the integrity of derived docs/specs/OVERVIEW content."
  non-goals:
    - "Replace the standard multistage flow suited to high-risk or cross-team changes."
    - "Mechanically determine whether semantic objectives are satisfied using keywords or the presence of fields."
    - "Introduce an automatic rework loop in this change; PARTIAL/FAIL explicitly terminate execution, leaving a restart to new facts or subsequent decisions."
  candidates:
    - id: stage-skips-only
      layer: configuration
      boundary:
        - architecture/e2e stage ownership
      evidence:
        - "The existing configuration already allows architecture and e2e to be skipped"
      tradeoffs: "The change is small, but it still uses the traditional Spec-oriented Reviewer and Merger LLM, cannot express PARTIAL, and cannot anchor decisions to the original issue."
    - id: vigil-minimal-profile
      layer: orchestration
      boundary:
        - solve/review/merge decisions
        - existing worktree/PR/CI/gates
      evidence:
        - "The existing Vigil already centrally owns queue, claim, forge, recovery, auditing, and deterministic hard gates"
        - "Experimental traces show that the main collapse comes from multiple subjective roles successively rewriting the objective, rather than from missing basic scheduling capabilities"
      tradeoffs: "Two clear branches must be maintained within the state machine, but a single source of scheduling truth can be reused and the minimal role sequence can be made a testable contract."
    - id: independent-minimal-runner
      layer: orchestration
      boundary:
        - separate queue and delivery lifecycle
      evidence:
        - "An independent runner can physically isolate flow experiments"
      tradeoffs: "It would duplicate queue, claim, forge, recovery, and the audit chain, creating a second source of truth and increasing operational risk."
  selected: vigil-minimal-profile
  affected-components:
    - "openagents/utils/agent_config.py: declare the standard/minimal flow and pass it through to single-repository and fleet plans."
    - "openagents/agents/spec_writer.py, acceptance.py, implementer.py, executor.py: a compact objective contract, one implementation, adjudication of results against the original issue, and constrained execution without validation."
    - "openagents/recipes/stages.py, vigil.py: three-step routing, termination on PARTIAL/FAIL, and mechanical merging."
    - "tests and e2e scripts: role sequences, fail-closed behavior, standard flow compatibility, and no additional LLM calls."
  failure-modes:
    - "The Spec Writer still rewrites the objective into a weaker version; limit the impact by also giving the Acceptance Reviewer the verbatim original issue, stipulating that the Spec has no authority to override the issue, and preventing merges on PARTIAL/FAIL."
    - "The Acceptance Reviewer performs another repository-wide architecture audit; its task permits only checking the original failure, changed files, and declared evidence. Anything beyond that requires identifying a specific evidence gap, and it must not delay adjudication by expanding reconnaissance."
    - "The minimal profile unexpectedly enters the architecture/e2e/rework/merger branches; use a recording backend to assert that the complete role sequence is exactly spec_writer, implementer, acceptance."
    - "PARTIAL is mapped to REWORK and calls the Implementer again; the minimal path directly writes the automation-failed terminal state and does not produce review-changes-requested."
    - "generate-only degenerates again into an all-purpose Implementer or self-acceptance; fix the boundary by requiring the role sequence to be strictly spec_writer, executor, with zero acceptance/reviewer/tester/merger calls."
    - "The clean, frozen seed's docs/specs/OVERVIEW has not yet been rendered or is out of sync with the candidate tree, and the old repository-wide gate prevents generate-only from merging even when it has not modified that tree; generate-only rereads only this issue's compact objective digest, while the repository-level gates for standard/minimal remain unchanged."
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: "For an existing issue with a failure, under flow=minimal, a recording backend returns READY, implementation succeeds, and Acceptance returns PASS."
      expected: "Only spec_writer, implementer, acceptance are called; architect, tester, reviewer, merger are not called; after PASS is bound to the current head, the mechanical merge path completes the flow."
      observation: "The offline e2e outputs the role sequence, the review-approved label, and the merge call, with the sequence exactly matching the expected sequence."
    - id: BC2
      polarity: negative
      stimulus: "The Acceptance Reviewer returns PARTIAL for an implemented PR."
      expected: "The PR does not receive review-approved, does not enter a rework loop, and is not merged; automation-failed and the original PARTIAL reason are recorded."
      observation: "Execution terminates after one acceptance call; the forge probe shows no merge call and includes a machine-readable failure projection."
    - id: BC3
      polarity: negative
      stimulus: "The Spec Writer determines that the entire issue cannot be implemented within the current repository boundaries and returns BLOCKED."
      expected: "No PR is created and the Implementer is not called; a clear blocker is recorded directly on the issue, and execution terminates programmatically."
      observation: "The role sequence contains only spec_writer, with zero create_pr calls and zero subsequent role calls."
    - id: BC4
      polarity: positive
      stimulus: "flow is not configured, or flow=standard is explicitly configured."
      expected: "The existing Drafter→Architect→Implementer→Reviewer→Merger behavior remains unchanged."
      observation: "All existing Vigil, stage, and agent config tests pass, and compatibility assertions are added."
    - id: BC5
      polarity: positive
      stimulus: "Multiple existing issues enter Vigil under flow=generate-only, parallel=4, and the curator has already provided blocked_by relationships."
      expected: "Each executable issue calls only spec_writer, executor; issues whose dependencies are not closed wait, while independent issues run concurrently; PRs have no quality-role calls, and merging completes through a serialized mechanical critical section."
      observation: "The recording backend contains no implementer/acceptance/tester/reviewer/merger calls, dependency facts control the executable set, and all merge_pr calls pass through the same lock."
    - id: BC6
      polarity: positive
      stimulus: "A frozen seed's docs/specs/OVERVIEW is out of sync with the standard candidate tree, but the generate-only issue adds only the docs/objectives contract and implementation files."
      expected: "Merging rereads only the current issue's compact objective digest and does not call repository-wide repository-integrity; under the same conditions, standard/minimal still retain the original gate."
      observation: "The generate-only recording test still completes the mechanical merge with repository-integrity configured as a probe that throws an error, while the compact digest is reread as usual."
  repository-invariants:
    - "A minimal PASS must be bound to the current head; the verdict is automatically invalidated after head advances."
    - "PARTIAL, FAIL, and BLOCKED cannot call merge, nor can they masquerade as review-changes-requested to trigger automatic rework."
    - "repository-integrity remains enabled for minimal/standard; generate-only retains only structural hard gates such as compact objective digest, head-advanced, evidence-stamp, and merge-allowed, and does not treat repository-wide derived indexes as quality gates."
    - "standard is the default value, and existing openagents.yml files retain their original behavior without modification."
  exemptions: []
tasks:
  - id: T1
    title: "Implement the three-step minimal delivery flow"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/agent_config.py
      - openagents/data/openagents.yml.template
      - openagents/agents/spec_writer.py
      - openagents/agents/acceptance.py
      - openagents/agents/implementer.py
      - openagents/agents/executor.py
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - tests/test_agent_config.py
      - tests/test_agents_prompts.py
      - tests/test_recipe_stages.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil.py
    scope: "Add standard/minimal/generate-only profiles; minimal retains compact Spec→single implementation pass→Acceptance, while generate-only is fixed as compact Spec→constrained executor→mechanical merge; retain hard structural gates, dependency scheduling, and standard compatibility."
    acceptance: "Configuration round-trip; the minimal sequence is strictly spec_writer→implementer→acceptance; generate-only is strictly spec_writer→executor with zero roles that make quality judgments; development may proceed concurrently according to the issue DAG, while merges are serialized; BLOCKED does not open a PR; the relevant pytest tests pass."
  - id: T2
    title: "Verify the minimal flow's role sequence and fail-closed behavior"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0082-minimal-objective-delivery-flow.sh
    scope: "Provide an offline, reproducible results script that runs tests for minimal PASS, PARTIAL, and BLOCKED behavior and standard compatibility, and outputs role sequences and deterministic gate results."
    acceptance: "The script runs successfully without interaction; the PASS sequence contains only three roles, PARTIAL/FAIL/BLOCKED result in zero merges and no rework, and existing standard tests show no regressions; exit codes and key assertions are available for reruns in CI and audits."
---

# 0082 · Minimal Objective-Preserving Development Flow

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Add optional `flow: minimal`. It fixes the judgment-based delivery chain for a single issue at three calls: Spec Writer freezes the original issue and writes a compact, implementable Spec; Implementer implements it in one pass; Acceptance Reviewer directly replays the original failure and assigns `PASS / PARTIAL / FAIL` against the original issue. Only PASS can authorize deterministic merging; BLOCKED, PARTIAL, and FAIL all terminate the flow, without shrinking scope or repeating audits to obtain “success.”

Also add experimental `flow: generate-only`: it first writes the same compact Spec, but then dispatches a constrained coding executor only once, skips CI, e2e, Acceptance, Reviewer, and the Merger LLM, and merges mechanically through structural hard gates. It is used to observe what the model naturally produces without quality gates; merged does not mean the objective has been verified.

## Motivation

For a single issue, the current Vigil runs Drafter, Architect, possibly a redraft, Implementer, Reviewer, possibly re-implement/re-review, and Merger in sequence. Actual runs show that this chain can easily turn “preserve the original objective” into “prove at each layer that the current Spec is internally consistent”: Architect can request removal of parts that are difficult to bring to completion, Drafter narrows delivery by marking them as non-goals or future work, and Reviewer ultimately assigns PASS only against the reduced Spec. Meanwhile, each role rereads the same source code and revalidates the same boundaries, producing hundreds of tool calls even for simple changes.

The minimal flow tests a different hypothesis: a single issue that has already passed requirements admission no longer needs a design-committee-style pipeline. What it needs is a short objective contract that cannot be reduced, a developer responsible for implementation, and an acceptance reviewer who evaluates the result from the perspective of the original issue. If the underlying layer is read-only or current capabilities are insufficient, the correct result is BLOCKED/PARTIAL, rather than degrading into an easy-to-pass prompt change.

## Guide-level explanation

With `flow: minimal` configured, users still apply discovery labels to issues and have Vigil create worktrees and PRs in the same way. Only the judgment chain changes:

1. **Spec Writer** receives the full original issue text, performs at most bounded code location work, and writes a compact Spec centered on a single Task. The Spec must include an “original objective contract” and falsifiable acceptance criteria; it may change the implementation path, but may not remove objectives. If the complete solution cannot be delivered, it returns `BLOCKED`; Vigil records the blocker on the issue and does not open a PR.
2. **Implementer** reads this Spec and the same original issue text, then implements it directly. Validation prioritizes replaying the original failure; expanding into unrelated investigations of the entire repository, all versions, or the entire filesystem to demonstrate “rigor” is prohibited.
3. **Acceptance Reviewer** does not redo the architectural design; it answers only whether the original failure has disappeared at the current head. `PASS` means the objective is fully satisfied; `PARTIAL` means the result is valuable but does not fully resolve the issue; `FAIL` means the result is ineffective or introduces a regression. The latter two both stop the flow without merging.

After step 1, `generate-only` switches to a **coding executor**: it executes only the compact Spec’s sole implementation task, and is prohibited from rewriting objectives, reviewing, self-testing, or expanding the investigation; after commit/push, it enters the mechanical PR queue directly. Vigil’s existing curator manages the issue `blocked_by` DAG, and `--parallel 4` runs concurrently only those issues whose dependencies are satisfied; irreversible merges into the same base are serialized through a critical section.

After a pass, the Merger LLM is no longer called. Vigil rechecks CI, head binding, repository integrity, and the review-approved label, then directly calls the forge’s idempotent merge primitive.

## Reference-level explanation

Add a top-level `flow` configuration field with valid values `standard | minimal`, defaulting to `standard`. Both the resolved `AgentConfig` and `RepoPlan` carry this value so that configuration is preserved for both single-repository and fleet operation.

With this group’s extensions, the valid values become `standard | minimal | generate-only`. generate-only reuses the compact Spec digest, worktree isolation, head-advanced, evidence-stamp, PR head binding, and forge conflict detection; the head-bound approval label it writes mechanically is only a state-machine token and does not express a quality PASS.

`stages.minimal_spec` calls the new `agents.spec_writer`. Its output is `READY | BLOCKED`; READY writes only `docs/objectives/issue-N.md`, a compact contract with five fixed sections (original objective, invariants, implementation path, falsifiable acceptance criteria, and one implementation task), without invoking the standard flow’s nine-section RFC/DAG/render/graph. It must pass the existing head-advance and evidence-stamp hard gates, after which `minimal_design_snapshot` validates the fixed sections and the 120-line limit and records a byte-level digest; the same digest is rechecked before merging. BLOCKED does not require creating an empty commit.

In the minimal branch, `_do_solve` skips Architect and calls Implementer only once after creating the PR, passing an explicit minimal contract and the original issue. Under minimal, `_sense` treats the independent e2e stage as folded into implementation and acceptance, avoiding an additional Tester call.

`stages.acceptance` calls the new `agents.acceptance`, with the original issue, candidate Spec, diff/PR context, and existing evidence as input. Its output is strictly enumerated as `PASS | PARTIAL | FAIL`. Under minimal, `_do_review_or_fix` does not use the review-changes-requested loop: PASS produces a head-bound review-approved; PARTIAL/FAIL call the existing `_fail_automation`, persisting the reason verbatim.

`stages.merge_mechanical` executes only the forge merge primitive after `gates.assert_merge_allowed`; the minimal branch of `_do_merge` still executes the repository-integrity and design-digest hard gates before taking action.

Task DAG:

```mermaid
graph LR
  T1[Configuration, roles, three-step state machine, and unit tests] --> T2[Offline end-to-end role sequence and failure closure]
```

Offline outcome script: `scripts/e2e-spec-0082-minimal-objective-delivery-flow.sh`. This round will also perform a real Gitea + GLM trial run using an existing experimental issue, with the actual results recorded in the experiment’s role_runs; this run is used to evaluate the flow and is not presented as hermetic CI.

## Drawbacks

The minimal flow deliberately gives up multiple rounds of architectural debate, the full RFC template, and automatic rework; if the first implementation is incomplete, it stops with PARTIAL. Throughput is higher, but the first-attempt success rate may be lower than standard. Acceptance remains a semantic judgment; pure code cannot prove that the model will never misjudge. Mechanical merging eliminates one LLM call, but also removes the Merger’s ability to handle exceptions beyond the hard gates as they arise; all exceptions follow the existing machine failure path.

generate-only is more aggressive: code that is incorrect, untested, or fails to satisfy the objective may also be merged, so its results can be used only for isolated experiments and retrospective evaluation, and cannot count toward the production success rate. Dependency inference relies on the existing curator and forge-native edges; undeclared semantic conflicts can surface only at the PR mergeability stage.

## Rationale and alternatives

Add a profile within the existing Vigil rather than a new runner because queues, claim, worktree, forge, recovery, auditing, and hard gates are already correctly in place; copying them would only create a second state machine. Choose three judgment roles rather than two to prevent Implementer from accepting its own work; remove the independent Architect, Tester, traditional Reviewer, and Merger to prevent the same problem from being reinterpreted four times.

The alternative of “using only stages to skip architecture/e2e” is insufficient: it still makes the traditional Reviewer treat the current Spec as authoritative, still offers only PASS/REWORK, still performs automatic rework, and still calls Merger. The alternative of “retaining Architect but limiting the tool budget” only reduces time; it does not change the incentive to obtain PASS after shrinking the objective.

## Prior art

Direct delivery of a single issue by a single agent is an existing principle in the repository’s `CLAUDE.md`; the existing Vigil worktree and deterministic hard gates provide a reusable foundation. A principle similar to trunk-based delivery is to base irreversible merging on a small number of objective thresholds, rather than having multiple roles repeatedly prove the same design.

## Unresolved questions

This round leaves no open questions requiring a user decision first: minimal is explicitly an optional experimental profile, and standard remains the default; the results of the real trial run will determine whether to expand its use.

## Future possibilities

If the real trial run demonstrates that the three-step flow is effective, the original failure trace could be attached to the issue as a structured artifact rather than appearing only in the body; tool calls per step, model latency, and objective outcome could also be collected to compare standard/minimal. If Acceptance has a high misjudgment rate, one arbitration pass limited to disputed evidence could be added, but repeated reconnaissance across the entire chain must not be restored.
