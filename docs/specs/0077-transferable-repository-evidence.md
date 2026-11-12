---
number: "0077"
title: "Repository evidence transferable across roles"
issue: 0
slug: transferable-repository-evidence
summary: "Save objective repository facts verified by a role as a bounded evidence pack and pass it along the delivery chain, enabling subsequent roles to gather evidence incrementally based on differences, reducing repeated scans without reusing judgments or conclusions."
architecture:
  objective: "Reuse verified repository facts while preserving each role's independent judgment, reducing repeated investigation before implementation and review."
  constraints:
    - "The evidence package contains only objective facts, with no architectural decisions or candidate evaluations"
    - "The content and number of entries must have deterministic upper bounds"
    - "Maintain compatibility with legacy run state and callers that do not provide an evidence package"
  non-goals:
    - "Bypass the judgments that are the responsibility of the implementer or reviewer"
    - "Persist model context or complete command output"
    - "Prevent necessary investigation by imposing a fixed number of reads"
  candidates:
    - id: prompt-only
      layer: agent-prompts
      boundary:
        - Drafter
        - Implementer
      evidence:
        - "Role prompts can request fewer repeated reads but cannot convey facts already known to preceding roles"
      tradeoffs: "The change is small, but subsequent roles still need to reconstruct the repository context from scratch."
    - id: bounded-evidence-pack
      layer: role-protocol-runtime-state
      boundary:
        - Drafter output
        - Runtime state
        - Implementer and Reviewer context
      evidence:
        - "Currently, only summaries are passed between roles, without reusable location information such as paths, symbols, verification methods, and source revisions"
      tradeoffs: "Introduce a small persistence protocol that can deterministically bound context and determine whether evidence remains valid based on its version."
  selected: bounded-evidence-pack
  affected-components:
    - openagents.agents
    - openagents.recipes.stages
    - openagents.recipes.vigil
    - openagents.runtime.state
  failure-modes:
    - "Presenting design judgments as facts causes subsequent roles to accept them mechanically"
    - "Evidence from an older revision is incorrectly reused because its source is not identified"
    - "An unbounded evidence package instead increases context size and token consumption"
verification:
  behavior-cases:
    - id: reuse-current-evidence
      polarity: positive
      stimulus: "A preceding role provides evidence containing paths, symbols, verification methods, and the current source revision"
      expected: "Subsequent roles receive a normalized evidence package and gather additional evidence only for gaps or changes"
      observation: "Tests of scripted stage invocation context and state round trips"
    - id: reject-subjective-or-malformed-data
      polarity: negative
      stimulus: "Input contains facts without paths, non-object entries, excessively long fields, or more entries than the limit"
      expected: "The normalization layer discards invalid entries and deterministically truncates the remaining content"
      observation: "runtime research unit tests"
  repository-invariants:
    - "The evidence package contains at most 24 records"
    - "Persisted fields come only from a public allowlist and contain no candidate evaluations or review conclusions"
    - "Existing role invocation behavior remains unchanged when no evidence package is provided"
  exemptions: []
tasks:
  - id: T1
    title: "Bounded objective evidence pack model"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/research.py
      - tests/test_runtime_research.py
    scope: "Define an allowlist of evidence fields, limits on entries and fields, normalization, deterministic merging, and compact rendering; accept only objective facts that can be located and verified."
    acceptance: "Unit tests cover discarding invalid entries, field truncation, the 24-entry limit, refreshing records with later arrivals for the same path and symbol, and compact Unicode rendering."
  - id: T2
    title: "Role protocols and incremental evidence-gathering contract"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/agents/drafter.py
      - openagents/agents/implementer.py
      - tests/test_agents_prompts.py
    scope: "Drafter outputs an objective evidence_pack; Implementer prioritizes locating relevant information by task, interface, and version, conducts additional investigation only when evidence is missing, stale, or conflicting, and explains why the budget was exceeded."
    acceptance: "Prompt contract tests demonstrate that the evidence_pack field, objectivity boundaries, a budget of six supplementary evidence-gathering operations before the first edit, and justifications for exceptions are all present, and that the approved Spec remains the authoritative input for implementation."
  - id: T3
    title: "Evidence state propagation and role wiring"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/state.py
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - tests/test_runtime_state.py
      - tests/test_recipe_stages.py
      - tests/test_recipe_vigil_act.py
    scope: "Save the normalized evidence pack to the issue run and pass it through draft, architecture, implement, and review; refine merges only new or changed facts, and calls that omit the evidence pack remain compatible."
    acceptance: "Scripted tests demonstrate that evidence is preserved through state round trips, refine merge results are passed to implementation and review, the default empty pack does not alter the context, and old state files remain readable."
---

# 0077 · Repository Evidence Transferable Across Roles

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

OpenAgents organizes repository facts already verified by preceding roles into a bounded `evidence_pack` and passes it to subsequent roles along with the issue's runtime state.
Evidence records provide location information such as paths, symbols, verification methods, and optional source revisions, but do not carry design choices, quality assessments, or review verdicts. Subsequent roles
continue to exercise independent judgment, conducting incremental supplementary investigation only for version changes, gaps in evidence, or contradictions with the current repository.

## Motivation

The existing workflow primarily passes the Spec, issue body, and natural-language summaries between Drafter, Implementer, Tester, and Reviewer. Even when
Drafter has identified the actual entry points, key interfaces, and verification methods, Implementer still needs to scan the repository again to reconstruct the same facts; once iteration begins,
subsequent roles repeat this process. In experiments, the main time cost was not the changes themselves, but multiple roles obtaining the same set of repository facts from scratch.

Simply requiring “fewer reads” cannot resolve missing information and may force roles to guess with insufficient evidence. What needs to be transferred is verifiable facts rather than the preceding role's
judgments, while allowing recipients to determine whether those facts remain reusable based on the current revision.

## Guide-level explanation

After completing its repository investigation, Drafter can record “the path and symbol of the entry function, the inputs an interface accepts, the test used to verify it, and the
Git SHA at the time of investigation.” The orchestration layer normalizes these records and applies length limits before saving them. Implementer first uses tasks, interfaces, and line ranges to locate implementation points; if
the current source matches the evidence's revision, it does not need to traverse the same directory again. If files have changed, records lack verification methods, or interfaces contradict the current repository,
Implementer conducts supplementary investigation as usual and explains the specific gaps when exceeding the default budget.

An evidence pack is not proof of approval. Architect still makes independent judgments about the technical architecture, and Reviewer must still check the implementation and behavioral evidence; assessments such as “the solution is excellent”
or “this should pass” are not transferable fields.

## Reference-level explanation

`runtime.research` provides `normalize`, `merge`, and `render`. Each record has `fact/path/symbol/verification` at its core,
with optional `source_revision/line_range/interface/tasks`. The normalization layer limits the pack to 24 records and applies length limits to each field; records without a fact or a path are
discarded. The merge key is the path plus the symbol (using the fact when there is no symbol), and incoming records update existing records using only nonempty fields.

Drafter's structured output gains `evidence_pack`. `RuntimeState` stores the normalized result in the corresponding issue run; incremental evidence returned by refine
is merged deterministically with the existing pack. `stages` appends compact JSON to the context only when the pack is nonempty, making it available in sequence to architecture, implement,
and review. An older backend without this field, an older state without this field, or a direct stage call that omits this parameter is treated as having an empty pack.

Implementer's default budget for supplementary reads/searches before the first edit is six calls. The budget is an observable investigation baseline rather than a cutoff: when evidence is missing, versions
do not match, or code presents contradictions, investigation may continue, with `lookup_exception_reason` returned. This group is not responsible for counting tool events; that counting belongs to a separate invocation
telemetry capability.

Task dependencies are `T1 → T2 → T3`. Offline acceptance testing is performed by the relevant runtime, agent prompt, stage, and Vigil scripted tests,
without invoking models, forge, or the external network.

## Drawbacks

State files and prompts gain a small amount of data; paths or line ranges may become outdated after refactoring. Field limits discard lower-priority facts, and excessive reliance on old
evidence may also miss changes in the current repository, so recipients must still check revisions and signals of contradictions.

## Rationale and alternatives

A bounded pack of objective evidence was chosen because it preserves both role independence and reusable location information. The first alternative is to modify only the prompts to require each role
to investigate less; however, roles do not know what preceding roles discovered, so they can only investigate less or investigate again. The second alternative is to pass the full transcript; it contains commands,
reasoning, and assessments, has an uncontrolled size, and would inject preceding biases directly into subsequent roles. An allowlisted fact protocol is smaller and easier to verify and invalidate.

## Prior art

Dependency manifests in build systems, content addressing in compilation caches, and provenance in data pipelines all bind artifacts to source revisions for reuse. This design
borrows only the principle of “facts plus sources” and does not treat model judgments as cacheable truth.

## Unresolved questions

Whether evidence entries should eventually be upgraded to content hashes, and whether symbol locators for different languages need to be typed, remain to be decided after data on actual invalidation has accumulated.

## Future possibilities

In the future, suspect records could be marked automatically based on the source revision, or some interface facts could be generated by a deterministic index; reuse rates for each role could also be measured, but
must not be used to automatically skip role judgments.
