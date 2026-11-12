---
number: "0076"
title: "Technical Architecture Decisions and Pre-implementation Quality Gates for Delivery"
issue: 0
slug: architecture-decision-gate
summary: "Turn confirmed requirements into reviewable technical architecture decisions, validate the intervention layer, alternatives, and behavioral evidence before implementation, and recheck global repository invariants before merging."
architecture:
  objective: "Establish technical architecture decisions before implementation and verifiable quality gates for OpenAgents without redoing product admission."
  constraints:
    - "Maintain compatibility with existing Spec snapshots that have no architecture field"
    - "Preserve unattended Vigil operation and needs-human closure"
    - "Do not replace technical judgment with keyword rules"
  non-goals:
    - "Reassess the product value of the requirements"
    - "Write special cases for defects from a single experiment"
  candidates:
    - id: prompt-only
      layer: role-prompt
      boundary:
        - Drafter
      evidence:
        - "The existing Prompt already includes requirements for Rationale and alternatives, but mechanical expansion still occurred in experiments"
      tradeoffs: "The change is small, but without state gates and deterministic invariants, it cannot prevent omissions or concurrency conflicts."
    - id: contract-and-gates
      layer: spec-contract-agent-workflow-runtime-gates
      boundary:
        - Spec model and validator
        - Drafter and Architect
        - Vigil and merge gates
        - Tester and Reviewer
      evidence:
        - "Currently, _do_solve calls Implementer immediately after drafting"
        - "Currently, Reviewer checks acceptance only against the generated Spec"
        - "Concurrent experiments produced duplicate Spec numbers that made it into main"
      tradeoffs: "Adds the cost of one architecture review and structured data, but can block errors before implementation and before merging, respectively."
  selected: contract-and-gates
  affected-components:
    - openagents.spec
    - openagents.agents
    - openagents.recipes.vigil
    - openagents.runtime.gates
  failure-modes:
    - "Drafter treats implementation suggestions in the issue as immutable requirements"
    - "Architect and Drafter develop correlated biases"
    - "Stale approval is reused after the design changes"
    - "Local validation on concurrent branches passes, but global uniqueness is violated after merging"
verification:
  behavior-cases:
    - id: architecture-rework
      polarity: positive
      stimulus: "Architect returns REWORK for intervention at the wrong layer"
      expected: "Drafter is limited to one revision; after deterministic Spec validation passes, Implementer is called without another model review"
      observation: "Record of the scripted Vigil call sequence"
    - id: architecture-human-stop
      polarity: negative
      stimulus: "The architecture stage is configured as human"
      expected: "The workflow stops after Drafter and does not call Implementer"
      observation: "Runtime needs-human exception and agent call records"
    - id: presence-only-evidence
      polarity: negative
      stimulus: "Tester submits only grep/static evidence of existence and claims PASS"
      expected: "The evidence validator refuses to allow progression"
      observation: "Deterministic unit test exception"
  repository-invariants:
    - "Spec number and slug are unique within the candidate tree"
    - "OVERVIEW is consistent with the candidate Spec source"
    - "Changes to design semantics change the design digest; changes to Task status do not change the digest"
  exemptions: []
tasks:
  - id: T1
    title: "Spec Architecture Decisions and Behavioral Acceptance Contract"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/schema.py
      - openagents/spec/model.py
      - openagents/spec/mutate.py
      - openagents/spec/validate.py
      - tests/test_spec_model.py
      - tests/test_spec_mutate.py
      - tests/test_spec_validate.py
    scope: "Extend the structured architecture/verification data model for single-file Specs, the normalized design digest, and repository-wide number/slug uniqueness validation; enforce only determinable invariants, without substituting keywords for semantic judgment."
    acceptance: "Positive and negative schema tests demonstrate the relationship between candidates and selections, positive and negative behavioral examples or explicit exemptions, stable boundaries for the design digest, and number/slug uniqueness; changes to Task status and derived artifacts do not change the digest, while changes to design fields or acceptance semantics must change it; the compatibility and migration strategy for existing Specs is explicit, and full validate produces no errors."
  - id: T2
    title: "Drafter Technical Architecture Output Contract and Skill Wiring"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/agents/drafter.py
      - openagents/runtime/context.py
      - tests/test_agents_drafter.py
      - tests/test_runtime_context.py
    scope: "Define draft/refine modes as the transformation from confirmed goals to technical architecture, explicitly distinguish goals from proposed implementations, integrate the current spec-driven-development methodology, and require repository evidence when filling in structured architecture candidates, selections, failure modes, and behavioral cases."
    acceptance: "Positive and negative scripted tests demonstrate that Drafter preserves issue goals while being able to replace incorrect implementation suggestions, and that its output includes repository evidence and falsifiable behavioral acceptance criteria; skill names referenced by the Prompt match the actual installed names; existing contracts for backfill/implement/iterate modes do not regress."
  - id: T3
    title: "Independent Architect Role and Architecture Adjudication"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/agents/architect.py
      - tests/test_agents_architect.py
    scope: "Add an Architect responsible solely for pre-implementation technical architecture review, producing PASS/REWORK and structured findings based on fidelity to goals, intervention-layer fit, boundary completeness, and the strength of behavioral evidence, without repeating product admission review or implementing code."
    acceptance: "The role's output schema and value domains are machine-checkable; positive examples pass, while designs that mechanically accept issue implementation suggestions, use only keywords for acceptance criteria, ignore process/concurrency ownership, or lack negative examples all receive REWORK; insufficient evidence may use the unified needs-human path and must not silently receive PASS."
  - id: T4
    title: "Vigil Pre-implementation Architecture Gate and Final Integration Gate"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - openagents/runtime/gates.py
      - openagents/runtime/state.py
      - openagents/utils/agent_config.py
      - tests/test_recipe_stages.py
      - tests/test_recipe_vigil_act.py
      - tests/test_runtime_gates.py
      - tests/test_runtime_state.py
      - tests/test_agent_config.py
    scope: "Split the current vertical path that proceeds directly from draft to implement; add an independent architecture stage that performs agent/human/skip design review and saves approval bound to the design digest; both implementation and merging reject stale approvals; run global Spec/artifact/DAG checks on the latest base+head candidate tree and bind the results to the base, head, design triple."
    acceptance: "Configuration tests demonstrate that the architecture default is derived compatibly and that invalid rfc/architecture combinations are rejected; state-machine tests demonstrate that unapproved designs do not invoke Implementer, REWORK returns to refine, human genuinely pauses execution, and design changes invalidate approval; when concurrent branches reuse a Spec number, the one merged later is rejected against the latest base; any change to base/head/design invalidates the integration stamp; existing code review, CI configuration, and needs-human semantics do not regress."
  - id: T5
    title: "Behavioral Evidence Manifest, Implementation Review, and End-to-end Falsification"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/agents/tester.py
      - openagents/agents/reviewer.py
      - openagents/runtime/evidence.py
      - tests/test_runtime_evidence.py
      - scripts/e2e-spec-0076-architecture-decision-gate.sh
    scope: "Have Tester generate an evidence manifest bound to the current head from the Spec's behavioral cases, and have Reviewer check the implementation against the approved design and evidence coverage; static existence checks can establish only format compliance and cannot, on their own, approve behavioral claims; provide a fully offline script for full-chain falsification."
    acceptance: "The evidence manifest is traceable to head, cases, observed values, and evidence paths; Reviewer must issue REWORK when evidence for a behavioral change consists only of grep/field-existence checks; PASS is permitted when positive and negative cases are complete and results match expectations; the e2e script covers an incorrect intervention layer, invalidation following design revision, insufficient evidence, and concurrent number conflicts, using a scripted backend and temporary repositories without accessing external networks or invoking real models."
---

# 0076 · Delivery-Side Technical Architecture Decisions and Pre-Implementation Quality Gates

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

After receiving an issue whose requirements-side assessment is complete, OpenAgents should translate the requirements objective into an independent, reviewable technical architecture decision,
rather than directly expanding the issue's suggested implementation into a Spec. This stage does not redefine the user problem or repeat product admission; it determines
the technical layer at which the system should intervene, how existing boundaries are affected, why the current approach is selected, which failure modes must be guarded against, and what
behavioral evidence will demonstrate that the implementation achieves the objective.

This group elevates that responsibility from a soft Prompt requirement into four mutually constraining mechanisms: the Spec stores a structured architecture decision and a behavioral acceptance plan;
an independent Architect reviews the decision before any implementation occurs; Vigil binds the review conclusion to a design digest and blocks unapproved implementation; and before merging,
the design digest, behavioral evidence, and global repository invariants are validated again against the latest mainline. The code Reviewer continues to review the implementation but no longer also serves as the architecture
approver.

## Motivation

The current delivery path appears to be Spec-first, but its actual control flow is: the Drafter writes and commits a Spec based on the issue, Vigil creates a draft PR,
and then immediately invokes the Implementer within the same `_do_solve` call. The Drafter's direct output consists only of `delivered/head_sha/summary`;
the deterministic gates prove only that the commit has actually advanced and that the self-reported SHA is correct. They neither express nor check the technical intervention layer, interface boundaries, the quality of alternatives, or
behavioral acceptance. The existing Reviewer adjudicates only against the Spec's Task acceptance, tests, and evidence after implementation is complete. Consequently, once the Spec
turns an unvalidated implementation suggestion into acceptance criteria, subsequent implementation and review form a closed loop within that same premise.

An unattended experiment involving five issues with a concurrency of two provided concrete counterevidence: all five PRs were automatically reviewed and merged, and the full test suite passed,
yet the final mainline still contained duplicate Spec numbers; a command duplication guard treated nonconsecutive commands on different files as the same duplicate operation; an approach that claimed
to terminate commands after thirty seconds only stopped the waiting path, without proving that the subprocess had been terminated; and multiple Prompt changes used only keyword presence as
acceptance criteria. These defects cannot be fully explained by “a missing sentence in a Prompt”: local Specs, local tests, and per-PR Reviewers can all be
internally consistent while batch-level consistency, the choice of technical layer, and actual behavior remain incorrect.

The historical approach required RFCs/Specs to receive human stage approval before implementation, but declarative Vigil interprets `rfc: agent` as drafting by an Agent,
without providing an equivalent automated architecture review state; `rfc: human` also does not establish a genuine pre-implementation pause point in the current vertical-slice control flow. Meanwhile,
the skill name referenced by the Drafter Prompt has drifted from the repository's current `spec-driven-development` name. This indicates that the current defect lies at
the combined boundaries of role contracts, context, the stage machine, and gates, rather than in a single model or a single passage of text.

## Guide-level explanation

The new delivery semantics explicitly distinguish three kinds of delivery information:

1. **Requirements objective** comes from an admitted issue and describes the results to achieve and the constraints. OpenAgents accepts this objective without repeating product discovery or
   admission.
2. **Implementation suggestions**, even when present in the issue, are only candidate technical hypotheses. The Drafter must select the actual intervention layer based on the current repository,
   and may adopt, modify, or reject the suggested implementation, but must not change the requirements objective.
3. **Technical architecture decisions** record the selected intervention layer, affected boundaries, at least one genuine alternative, failure modes, and positive and negative behavioral acceptance cases.

For example, with “avoid ineffective duplicate operations,” the requirements objective remains unchanged; the architecture design must compare intervention points such as Prompt reminders, the orchestration state machine, tool-call boundaries,
and the process executor. If the objective requires reliable termination of external commands, the design cannot select the Prompt layer simply because modifying a Prompt is easiest;
it must explain which component actually owns the subprocess lifecycle and use process exit and the cessation of side effects as behavioral evidence. Conversely, if the objective is only
to standardize the format of user-facing expressions, a role Prompt may be precisely the right intervention layer. The design should make its boundaries explicit and use positive and negative interaction examples,
rather than merely checking for the presence of strings, as acceptance criteria.

The automated flow becomes:

`Admitted issue → Draft Spec → Architect reviews design → Implement → Tester/Reviewer validate behavior → Integration validation against latest mainline → Merge`

The Architect's PASS is bound to a normalized design digest, rather than to a permanent label. When design-related content changes, the old approval automatically
becomes invalid and review is repeated; changes only to Task status, implementation commit references, or derived indexes do not change the design digest. Declarative configuration adds an independent
`architecture` stage: `agent` means automated architecture review, and `human` means waiting for human approval after the Spec is drafted; `skip` is allowed only together with
`rfc: skip`, indicating that the repository explicitly does not require a Spec, and must not fabricate architecture approval.

## Reference-level explanation

### Architecture Decision Contract

Spec frontmatter adds two structured objects, `architecture` and `verification`. They are machine-readable indexes into the nine-section body,
not duplicates of the body:

- `architecture.objective`: the delivery objective, faithfully preserved from the admitted issue;
- `architecture.constraints`: compatibility, security, performance, runtime environment, and explicit non-goals;
- `architecture.candidates[]`: candidate intervention layers, required boundaries, evidence, and major costs;
- `architecture.selected`: the selected intervention layer, affected components/interfaces, and the rationale for selection;
- `architecture.failure_modes[]`: relevant failure modes involving concurrency, state, processes, compatibility, rollback, and so on;
- `verification.behavior_cases[]`: task-independent positive cases, negative cases, observation methods, and expected results;
- `verification.repository_invariants[]`: repository-level invariants such as unique numbering, consistent generated artifacts, and a valid dependency graph;
- `verification.exemptions[]`: explicit exemptions and their rationale for documentation-only changes or changes without externally observable behavior changes.

`spec validate` enforces only what can be determined deterministically: complete fields, valid enum values, nonempty candidates, a selected option that belongs to the candidates, at least
one positive case and one negative case for behavior changes, nonempty exemption rationales, and repository-wide uniqueness of Spec numbers/slugs. It does not use keywords to infer “whether the architecture is good.”
`design_digest` computes a normalized digest of the design fields above, the design content in the nine-section body, and each Task's scope/files/dependencies/acceptance,
excluding Task status, implementation references, and derived artifacts such as OVERVIEW.

### Independent Architect

A new Architect role takes the admitted issue, candidate Spec, repository structure, and relevant implementation read as needed as input. It reviews only the transformation from the requirements objective to
the technical architecture; it neither reassesses product value nor writes code. Its structured output contains at least:

- `verdict: PASS | REWORK`;
- `objective_fidelity`: whether the design preserves the requirements objective and distinguishes it from the suggested implementation;
- `intervention_fit`: whether the selected technical layer actually owns the behavior to be changed;
- `boundary_integrity`: whether interfaces, state, consistency, and failure modes are fully accounted for;
- `verification_strength`: whether acceptance observes outcomes and includes negative cases capable of disproving the approach;
- `reason/findings`: actionable revision guidance.

The Architect and Drafter use different role contracts; configuration allows them to use different backends. They may still run on the same model, but the trace must retain
the role, model, design digest, and verdict to make correlated bias identifiable. An Architect REWORK returns to the Drafter for one bounded
refine; after revision, deterministic `spec validate` runs and the design digest is rebound, then implementation continues without repeatedly
invoking the Architect. The existing `needs-human` control exit is used only when necessary evidence cannot be obtained, the Architect explicitly requests human involvement,
or deterministic validation fails after revision.

### Pre-Implementation State Gate

Vigil no longer unconditionally executes draft and implement consecutively within `_do_solve`. The `rfc` stage continues to determine only who drafts the Spec;
after creating the draft PR, it computes the design digest and routes to the new `architecture` gate:

- `agent`: dispatch the Architect once; after PASS, record `design-approved:<digest>` evidence; after REWORK, perform a bounded
  Spec revision, run deterministic validation, and recompute the digest, without spending another model call on re-review;
- `human`: pause at the draft PR; human approval must be bound to the current design digest;
- `skip`: valid only when `rfc: skip`; do not create false approval evidence, and explicitly follow the no-Spec path according to configuration.

Configuration validation rejects `rfc != skip` with `architecture = skip`, preventing a silent bypass in which “a Spec is written but no one reviews it.” For compatibility with existing
configuration, a missing `architecture` is inferred from `rfc`: `rfc: agent` defaults to `architecture: agent`, `rfc: human` defaults to
`architecture: human`, and `rfc: skip` defaults to `architecture: skip`; templates and migration guidance will explicitly state the final value.

The Implementer's precondition is valid approval for the current design digest. Any Spec revision that changes the digest invalidates approval; in the next round, Vigil
returns to the Architect first instead of continuing implementation. Design approval and code `review-approved:<head>` are stored separately, because the former answers
“is the approach sound?” while the latter answers “does the current commit correctly implement the approach?”

### Behavioral Evidence and Code Review

The Tester reads `verification.behavior_cases` and produces a structured evidence manifest bound to the current head: which cases were executed,
observed values, expected values, conclusions, and evidence paths. Static text, grep, or field presence can verify loading and formatting, but when the objective claims to change runtime
behavior, they cannot be the sole evidence for PASS. The Reviewer reads the Spec, implementation diff, and manifest together, checks that the implementation conforms to the approved design,
and confirms that each behavioral claim has corresponding evidence; the Reviewer has no authority to fill in or tacitly accept missing architecture decisions.

### Global Integrity Gate at Merge Time

Per-branch `spec validate` can see only the current branch and cannot establish mainline consistency after concurrent PRs are merged. A deterministic integration
gate is added before merging: fetch the latest base, construct a `base + PR head` candidate tree, and run repository-level checks for Spec schema/number uniqueness, render/graph drift, Task
DAG/file ownership, and checks configured by the project. Results are bound to `(base_sha, head_sha, design_digest)`; if any value changes, they become invalid and
must be rerun. The Merger may process only PRs with a valid integration stamp, a current code review, and CI conclusions when required by configuration. Thus, even if two parallel
branches select the same number at the same time, the one merged later will be rejected or automatically renumbered against the latest base, rather than introducing the conflict into main.

### DAG and File Allocation

| Task | Content | Dependencies |
|---|---|---|
| T1 | Spec architecture decision and behavioral acceptance schema, and deterministic validation | — |
| T2 | Drafter technical architecture output contract and skill wiring | T1 |
| T3 | Independent Architect role and structured verdicts | T1, T2 |
| T4 | Vigil pre-implementation architecture gate, digest state, and final integration gate | T1, T3 |
| T5 | Tester/Reviewer consumption of behavioral evidence and end-to-end counterevidence | T3, T4 |

File ownership for each Task is specified in frontmatter and does not overlap. The end-to-end validation script is
`scripts/e2e-spec-0076-architecture-decision-gate.sh`: it uses temporary repositories and a scripted backend to cover replacement of a suggested
implementation, one bounded revision and deterministic validation after architecture REWORK, invalidation of approval by Spec changes, refusal to pass with grep-only evidence, and rejection by the integration gate of the second
merge when two parallel branches reuse a number. Default tests do not call real models or external forges.

## Drawbacks

Adding one independent review before implementation increases model calls and initial delivery latency; when a design is sent back, it also adds one Drafter round trip. Structured architecture
fields also increase the cost of writing Specs, and simple changes can become overly burdensome if misclassified. Constructing a candidate tree and regenerating indexes in the integration gate
increases merge latency in large repositories. If different roles still use the same model, correlated bias can only be observed and reduced; the structure itself cannot
eliminate it completely.

These costs are controlled in three ways: single-file changes with no design decisions may still skip the Spec under existing rules; deterministic schema validation and digest computation do
not call models; and behavioral evidence is tiered by change category, with justified exemptions allowed for purely internal or documentation-only changes. The architecture gate does not require reinvestigating the product problem,
so its context and responsibilities should be narrower than those of requirements-side roles.

## Rationale and alternatives

We chose “a structured design contract + an independent Architect + two deterministic binding gates” because each addresses a different failure mode: the structured contract makes design
decisions addressable, the Architect judges the quality of the technical approach, and the digest and integration gates prevent concurrent or subsequent changes from bypassing the ruling. Implementing only one of these would leave
obvious bypasses.

We did not adopt “only strengthen the Drafter Prompt.” The existing Prompt already requires architecture, Rationale, and alternatives, yet experiments still produced mechanical elaboration;
without a pre-implementation state gate, the workflow proceeds immediately to implementation even if the model omits these requirements. Adding more prohibitions would only expand the wording and create new
existence tests.

We did not adopt “have the existing code Reviewer also review the architecture.” Code review takes place after implementation, when overturning the design incurs greater sunk costs, and
its current benchmark is “does this conform to the Spec,” which would create self-referential acceptance. An independent Architect rules before implementation and is accountable along different output dimensions.

We did not adopt “require human approval for every Spec.” A human gate offers high quality but does not meet Vigil’s goal of unattended operation. This proposal retains `rfc: human`,
while providing an auditable automated equivalent for `rfc: agent`; when evidence is insufficient, the process can still conclude with `needs-human`.

We did not adopt central database preallocation of Spec numbers as the sole fix. Central allocation can reduce collisions, but it cannot prevent manually created files, offline branches, or other
drift in global invariants; an integration gate against the latest base is a necessary safety net. An atomic Spec number lease provided by the forge could be added as an optimization in the future.

## Prior art

Compilation pipelines transform source semantics into a typed intermediate representation, then use an independent checking stage to prevent invalid programs from entering the backend; this design likewise makes the transformation from requirements and objectives to
a technical approach explicit, rather than relying solely on natural-language role names. Database optimistic concurrency control uses version stamps to verify that “the basis for the judgment is still the current
state,” corresponding to this group’s use of the design digest and `(base_sha, head_sha)` to bind approvals. Required checks in continuous integration follow
the same principle: a ruling must be bound to a specific commit, and the old conclusion becomes invalid when the state changes.

OpenAgents’ existing `review-approved:<sha>`, e2e head evidence stamps, and level-triggered Vigil have already demonstrated that the pattern of “binding conclusions to the observed
version and automatically recomputing them after changes” suits this system; this group moves that pattern earlier, to technical architecture, and extends it to the final integration tree.

## Unresolved questions

None. The initial version uses an independent Architect, a normalized design digest, a behavioral evidence manifest, and integration validation of the candidate tree against the latest base;
whether to add central Spec number leases for highly concurrent forges is a subsequent performance optimization and does not affect this group’s correctness boundaries.

## Future possibilities

Once enough traces have been collected, different Drafter/Architect model combinations can be compared in terms of architecture rejection rates, implementation rework rates, and post-merge defect rates to quantify
correlated bias and the additional review cost. Architecture candidates and behavioral cases could also form a repository-level pattern library, but patterns can serve only as candidate evidence and cannot automatically
replace analysis of the current code boundaries. The integration gate could later be extended into an atomic merge queue on the forge, ensuring that multiple validated PRs are rechecked serially, strictly against
the latest mainline.
