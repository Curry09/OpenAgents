---
number: "0083"
title: "v0.2 Causal Spec Contract"
issue: 0
slug: v02-causal-spec-contract
summary: "Formalize the experimentally validated, deep-evidence Spec Writer as the sole single-issue design role for v0.2."
architecture:
  objective: "Before a single issue enters development, produce a compact Spec that preserves its objectives, is implementable and falsifiable, and clearly distinguishes evidence of reachability, control effects, and final behavior."
  constraints:
    - "The original issue is the authority on objectives; the Spec must not scale back difficult objectives."
    - "The current worktree is the only writable repository; read-only investigation of the NexAU version actually loaded and all runtime dependencies is permitted."
    - "All candidates use the same evidence fields; the presence of a prompt or a reference to it in configuration does not establish actual reachability, much less behavioral effectiveness."
    - "READY, PARTIAL, and BLOCKED fail closed; only READY may enter the v0.2 DAG."
  non-goals:
    - "Implement code or run full product acceptance testing during the Spec phase."
    - "Write special-case keyword rules for different issues."
  candidates:
    - id: single-causal-writer
      layer: design
      boundary:
        - issue objective to frozen compact spec
      evidence:
        - "A comparison across four issues shows that continuous investigation can find actual NexAU control points and avoid false READY results"
      tradeoffs: "Investigation by a single role is slower, but avoids repeatedly establishing context across roles."
    - id: split-design-committee
      layer: design
      boundary:
        - research, architecture and review handoffs
      evidence:
        - "The old workflow has corresponding roles"
      tradeoffs: "Each layer rereads the context and creates incentives to progressively scale back objectives."
  selected: single-causal-writer
  affected-components:
    - openagents/agents/spec_writer.py
    - openagents/recipes/stages.py
    - tests/test_agents_prompts.py
    - tests/test_recipe_stages.py
  failure-modes:
    - "Candidate comparisons are reduced to free text; the production hard gate rejects READY/PARTIAL outputs that lack the standardized fields."
    - "Future plans are passed off as existing evidence; roles must separately label HYPOTHESIS, STRUCTURAL, and BEHAVIORAL."
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: "The Spec Writer establishes a complete chain of evidence for actual runtime control points."
      expected: "Output READY, a compact Spec, complete candidate fields, and evidence levels listed separately for each objective."
      observation: "The engine output passes the structural and head/digest hard gates for minimal_spec."
    - id: BC2
      polarity: negative
      stimulus: "Candidates provide only reason, or treat a prompt configuration reference as a behavioral effect."
      expected: "The output is downgraded to PARTIAL, or rejected by the standardized-field hard gate."
      observation: "Targeted pytest tests raise GateError, and the experiment on four real issues produces no false READY results."
  repository-invariants:
    - "Write the Spec only to docs/objectives/issue-N.md."
    - "PARTIAL/BLOCKED do not proceed to Developer."
  exemptions: []
tasks:
  - id: T1
    title: "Formalize the Deep-Evidence Spec Writer and Hard Production Gates"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/spec_writer.py
      - openagents/recipes/stages.py
      - tests/test_agents_prompts.py
      - tests/test_recipe_stages.py
    scope: "Formalize read-only access to NexAU, a unified candidate evaluation standard, prompt reachability, separation of delivery/control_effect, evidence levels, and three-state closure."
    acceptance: "Role contract tests, negative cases for unified fields, and the minimal_spec delivery hard gate all pass."
---

# 0083 · v0.2 Causal Spec Contract

## Summary

v0.2 retains only one design role per issue. The Spec Writer continuously performs objective decomposition, investigation of the repository and the actual NexAU implementation, candidate comparison, causal-chain development, and falsification design, producing a compact objective contract; this cognitive chain is no longer split among multiple roles that repeat the same in-depth investigation.

## Motivation

The minimal Spec Writer treats “the file exists” and “the prompt is referenced” as direct evidence of behavioral improvement, and prioritizes prompt changes that are easy to implement. A comparison across four issues demonstrated that real control points such as `before_model`, `wrap_tool_call`, and tracers can only be found after access to the actual NexAU implementation is opened up; a unified evidence standard prevents continued selective inference after reading the source code.

## Guide-level explanation

Run the Spec Writer independently for each issue. READY means the complete objective has a closed causal mechanism and independent acceptance; PARTIAL means there is a valuable path, but some objectives remain unclosed; BLOCKED means current capabilities are insufficient. The latter two stop as normal, auditable outcomes without creating a PR.

## Reference-level explanation

Each candidate must record ownership, delivery, control_effect, evidence, assumptions, failure_modes, and verdict. Each objective must record scope_coverage and evidence_level. After model-schema validation, `stages.minimal_spec` again enforces hard gates for nested fields, HEAD advancement, and evidence stamps.

## Drawbacks

Complex runtime problems require 20–35 tool calls and take 5–8 minutes. v0.2 accepts this cost, but will not continue adding scheduling, implementation, or acceptance authority to the role.

## Rationale and alternatives

Splitting the work back into Researcher/Architect/Reviewer roles would require rebuilding context at every small step. A single role preserves continuity of reasoning, while independence is instead provided by Acceptance after implementation.

## Prior art

Builds on the minimal flow from Spec-0082 and the experimental results from `glm52fp8-1m-specwriter-deep-clean-r2/r3`.

## Unresolved questions

The NexAU evidence index and stopping conditions may be optimized later, but speed must not be gained by restoring a fixed number of reads.

## Future possibilities

Convert the compact Spec into a structured `submit_spec` stop tool, with the host mechanically rendering and submitting it, to remove the dependency on Claude Code.
