---
number: "0085"
title: "v0.2 Minimal Batch Development and Acceptance"
issue: 0
slug: v02-batch-delivery
summary: "Use a single batch runner to execute Spec, DAG, Developer, objective results, Acceptance, and mechanical merging."
architecture:
  objective: "Provide a minimal, auditable development loop with no synchronous NeedHuman, no multilayer review, and no automatic rework."
  constraints:
    - "The only LLM roles are Spec Writer, Curator, Developer, and Acceptance."
    - "Developer must not rewrite the Spec or perform its own acceptance; Acceptance must not modify code."
    - "Development within each DAG batch may proceed in parallel; irreversible merges are serialized and accept only PASS@current HEAD."
    - "PARTIAL, BLOCKED, FAILED, and NEEDS_DECISION are all non-blocking terminal states; other nodes continue."
  non-goals:
    - "Remove standard Vigil and all historical migration code in the first version."
    - "Automatic rework or requiring humans to answer questions synchronously within a worker."
  candidates:
    - id: additive-v02-batch
      layer: orchestration
      boundary:
        - isolated batch recipe over existing adapters and gates
      evidence:
        - "The old Vigil can continue to provide standard compatibility, and the batch core can be verified hermetically."
      tradeoffs: "Two entry points exist during the stabilization period, but directly rewriting the large old state machine is avoided."
    - id: mutate-vigil-in-place
      layer: orchestration
      boundary:
        - existing per-issue reconcile loop
      evidence:
        - "The existing queue can be reused."
      tradeoffs: "The batch barrier and post-Spec DAG would intrude into the single-issue state machine and expand the regression surface."
  selected: additive-v02-batch
  affected-components:
    - openagents/agents/developer.py
    - openagents/backends/nexau.py
    - openagents/data/nexau/agent.yaml
    - openagents/v02/runner.py
    - openagents/v02/audit.py
    - openagents/utils/agent_config.py
    - openagents/cli.py
    - tests/test_v02_runner.py
  failure-modes:
    - "A single node failure brings the entire batch to a halt; the runner must limit the effects of the failure to dependent successors, while independent nodes continue."
    - "Acceptance's self-reported PASS is bound to an old head; the runner rereads HEAD and executes a mechanical gate."
    - "The Spec declares itself READY but omits objectives; the runner permits only one constrained contract repair and does not misclassify effects that have yet to be implemented as PARTIAL."
    - "Acceptance records explicit failures in evidence but still declares PASS; the host validates per-case results and requires evidence of actual User Test behavior."
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: "Two independent READY Specs and one dependent node, with Developer delivering all of them and Acceptance returning PASS."
      expected: "The first two Developers run in parallel, the dependent node runs afterward, and merges are serialized."
      observation: "The event sequence from the recording adapter matches the topo batches."
    - id: BC2
      polarity: negative
      stimulus: "One Developer fails or Acceptance returns PARTIAL."
      expected: "The node is not merged, its successors are marked blocked, and other independent nodes continue; there is no NeedHuman wait or rework."
      observation: "Each node's terminal state in BatchResult and zero erroneous merge calls."
  repository-invariants:
    - "PASS must be bound to the current HEAD and the frozen Spec digest."
    - "The runner does not generate a review-changes-requested loop."
  exemptions: []
tasks:
  - id: T1
    title: "Implement the Developer contract and an injectable batch runner"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/developer.py
      - openagents/v02/runner.py
      - openagents/v02/audit.py
      - tests/test_v02_runner.py
      - tests/test_v02_audit.py
    scope: "Execute one Developer invocation and one Acceptance invocation per task in DAG layers, with localized failures, blocking propagation, and serial merges; inject all external actions through adapters."
    acceptance: "Tests for parallel layers, dependency blocking, PARTIAL/FAIL, exceptions, and merge sequences pass."
  - id: T2
    title: "Declare the v0.2 flow and command entry point"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/utils/agent_config.py
      - openagents/data/openagents.yml.template
      - openagents/cli.py
      - tests/test_agent_config.py
      - tests/test_cli.py
    scope: "Configuration accepts flow=v0.2 and provides an explicit batch entry point; standard/minimal/generate-only remain compatible."
    acceptance: "Tests for configuration round-tripping, CLI arguments, and legacy defaults pass."
  - id: T3
    title: "Integrate the NexAU coding backend with a Messages gateway"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/backends/nexau.py
      - openagents/v02/node_runtime.py
      - openagents/data/nexau/agent.yaml
      - openagents/data/nexau/system.md
      - openagents/data/nexau/run_shell_command.tool.yaml
      - openagents/data/nexau/complete_task.tool.yaml
      - docker/v02-nexau.Dockerfile
    scope: "Use a NexAU local tool loop or the Claude Code backend to connect to an Anthropic Messages-compatible gateway, with Bearer authentication and defaults of a 256k context and 32k output per invocation."
    acceptance: "Probes for direct WIS connectivity, the NexAU shell tool, and complete_task pass; persist a complete local trace for every role invocation, and keep secrets out of logs and the repository."
  - id: T4
    title: "Tighten contract consistency and behavioral acceptance in the minimal flow"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/agents/spec_writer.py
      - openagents/agents/acceptance.py
      - openagents/recipes/stages.py
      - openagents/v02/openagents_adapter.py
      - tests/test_recipe_stages.py
      - tests/test_agents_prompts.py
    scope: "Internal contradictions in READY trigger one bounded contract repair; HYPOTHESIS may still proceed to implementation; v0.2 Acceptance PASS must include behavioral evidence from a host-run User Test."
    acceptance: "FULL+HYPOTHESIS does not trigger a conservative exit; READY+PARTIAL automatically triggers one repair; the host rejects PASS if the User Test is incomplete, behavioral evidence is missing, or any evidence indicates failure."
---

# 0085 · v0.2 Minimal Batch Development and Acceptance

## Summary

The v0.2 batch runner orchestrates only four responsibilities: Spec, DAG, Developer, and Acceptance; testing, head/digest, PRs, and merging are all mechanical operations. There are no Owner, Architect, traditional Reviewer, Tester, or Merger LLMs.

## Motivation

The old development chain reread context at every layer and ruled out difficult implementations, ultimately producing prompt-only changes and burdensome self-verification. The minimal closed loop concentrates design understanding in the Spec Writer and implementation in the Developer, while keeping final judgment against the goals independent.

## Guide-level explanation

The user explicitly starts a v0.2 batch. The runner generates Specs in parallel, invokes the Curator once, and performs development in parallel by topological layer; each delivery undergoes acceptance exactly once. Failed nodes terminate and block their successors, but do not affect nodes that do not depend on them.

## Reference-level explanation

The initial runner isolates forge/worktree/backend through an adapter protocol, allowing hermetic testing of the core scheduling logic. Node states include READY, DEVELOPED, PASS, PARTIAL, FAIL, FAILED, BLOCKED_BY_DEPENDENCY, and NEEDS_DECISION. Only PASS invokes the serial merge callback.

## Drawbacks

The absence of automatic rework will reduce the first-attempt success rate; this is an explicit choice, as failed results are more auditable than hidden reductions in scope.

## Rationale and alternatives

Directly modifying the old Vigil state machine would insert a batch barrier into single-issue reconcile and expand the regression surface. A standalone v0.2 recipe reuses the underlying adapters, with the default entry point to be replaced once behavior stabilizes.

## Prior art

Builds on Spec-0082's three-phase flow, Spec-0065's concurrent queue, and Spec-0081's handling of machine failures.

## Unresolved questions

The initial version does not support dynamic reordering across batches; conflicts between actual write sets are left to forge/rebase to handle in a fail-closed manner.

## Future possibilities

Once stable, make v0.2 the default and remove the standard compatibility stack and the old needs-human migration code.
