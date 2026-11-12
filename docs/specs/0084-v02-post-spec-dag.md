---
number: "0084"
title: v0.2 post-Spec Curator DAG
issue: 0
slug: v02-post-spec-dag
summary: "Generate the dependency DAG and parallel batches together after a batch of Specs is complete; Curator no longer participates in the initial technical review."
architecture:
  objective: "Use the structured mechanisms, files, and evidence in READY Specs to generate a verifiable DAG, allowing independent issues to run in parallel and dependent issues to execute in order."
  constraints:
    - "Curator reads only frozen Spec summaries; it does not reinvestigate the repository or veto technical approaches."
    - "PARTIAL/BLOCKED do not enter the graph."
    - "Edges must reference actual nodes and must not be self-referential or form cycles; an invalid graph causes the entire batch to be rejected, and no development is performed."
    - "Do not create edges when dependencies are uncertain; use deterministic anchors for file overlap and explicit interface dependencies."
  non-goals:
    - "Handle git content conflicts that arise during execution."
    - "Replace the Spec Writer's judgment of the implementation mechanism for an individual issue."
  candidates:
    - id: post-spec-batch-plan
      layer: orchestration
      boundary:
        - frozen READY specs to validated DAG batches
      evidence:
        - "Specs already include predicted files, control points, and interface dependencies"
      tradeoffs: "Must wait for this batch's Spec barrier, but dependency assessment has reliable inputs."
    - id: intake-issue-plan
      layer: orchestration
      boundary:
        - raw issue text to dependency edges
      evidence:
        - "The existing Vigil curator uses this approach"
      tradeoffs: "Guess files and mechanisms prematurely, or be forced to reinvestigate the repository."
  selected: post-spec-batch-plan
  affected-components:
    - openagents/agents/spec_curator.py
    - openagents/v02/model.py
    - openagents/v02/planner.py
    - tests/test_v02_planner.py
  failure-modes:
    - "Curator hallucinates nonexistent issues; graph validation fails closed."
    - "Nodes involving the same file are incorrectly run in parallel; deterministic file-conflict edges are added before model suggestions."
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: "Four READY Specs, two of which share a file, one with an explicit dependency, and one independent."
      expected: "Output stable topological batches, with independent nodes running in parallel and nodes sharing files staggered."
      observation: "Pure in-memory tests assert batches and edges."
    - id: BC2
      polarity: negative
      stimulus: "Curator outputs a cycle, a self-reference, or an unknown node."
      expected: "The planner throws PlanError, with zero Developer calls."
      observation: "The runner records the plan_failed terminal state."
  repository-invariants:
    - "Each issue has at most one node in the DAG."
    - "Each development batch contains only nodes whose current in-degree is zero."
  exemptions: []
tasks:
  - id: T1
    title: "Implement frozen Spec nodes, DAG validation, and topological batches"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/spec_curator.py
      - openagents/v02/model.py
      - openagents/v02/planner.py
      - tests/test_v02_planner.py
    scope: "Define SpecNode, the Curator output contract, deterministic file conflict anchors, acyclicity validation, and stable layered topological sorting."
    acceptance: "Tests pass for READY filtering, negative cases involving unknown nodes, self-references, and cycles, and parallel execution of independent nodes."
---

# 0084 · v0.2 post-Spec Curator DAG

> **Historical design.** This design describes the retired standalone batch runner. Vigil's existing issue coordination is separate.

## Summary

Curator changes from an intake triager to a batch planner: after waiting for all Specs in the current batch to be completed, it plans implementation dependencies and parallel batches only for READY Specs.

## Motivation

The original issue text is insufficient to reliably predict which files will be modified and which control points will be affected. Planning edges too early means guessing dependencies; having Curator read the repository again would reconstruct context that Spec Writer has already acquired. Frozen Specs already contain selected intervention, files, ownership, and evidence, making them the correct input for planning the DAG.

## Guide-level explanation

The runner first writes all Specs in parallel, then filters for READY Specs. Curator proposes semantic edges based on the READY summaries; the planner also adds stable conflict edges based on deterministic file intersections, then validates the graph and generates batches.

## Reference-level explanation

The edge direction is `issue -> blocked_by`. In each round, topological layering selects nodes whose blockers have all been completed and sorts them by issue number. For two nodes that share files but have no semantic dependency, the issue with the smaller number goes first, ensuring determinism and preventing concurrent writes to the same files.

## Drawbacks

Predicted files may differ from those the Developer actually writes; runtime git mergeability checks and write-set audits are still needed as safeguards.

## Rationale and alternatives

Directly reusing Vigil's intake curator would continue to infer the graph from issue text. The new planner reuses its acyclic-graph approach, but changes the input to frozen Specs.

## Prior art

Spec-0065's `_proposed_edges` and `_cycle_members` have already demonstrated the feasibility of edge validation and the parallel worker model.

## Unresolved questions

Cross-repository interface dependencies are excluded from the simplified v0.2 version for now.

## Future possibilities

Feed actual changed-files back into batches that have not yet started to dynamically tighten conflict edges.
