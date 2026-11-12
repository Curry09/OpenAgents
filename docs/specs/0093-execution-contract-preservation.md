---
number: "0093"
title: "Preserve execution conditions and an independent acceptance summary throughout the delivery chain"
issue: 0
slug: execution-contract-preservation
summary: "Validate and inject the publisher-provided safe execution contract so that Spec, architecture review, and code review preserve the prerequisites concerning the absence of human input, budgets, and artifact acceptance, without accessing the private grader."
architecture:
  objective: "Ensure that the roles responsible for actual delivery retain usage conditions from trustworthy sources, without substituting local Spec consistency for completion of the original goal."
  constraints:
    - "Continue using Issue authorization, the package hash, and unified engine injection."
    - "Private graders and answers must not enter OpenAgents."
    - "The expectation that a contract is required comes from independent project/dispatch configuration and does not depend on attachments that may be missing."
  non-goals:
    - "Do not implement a benchmark adapter, a user loop, or a candidate capability elimination gate."
  candidates:
    - id: shared-contract-context
      layer: observations/runtime context
      boundary:
        - "Authorized execution contract"
        - "Sole engine injection point"
        - "Actual role inputs"
      evidence:
        - "The architecture context consists primarily of Spec text"
        - "The existing reader only provides a path for reading the manifest on demand"
      tradeoffs: "Add bounded context and explicit failures for required contracts, while reusing existing workflows."
    - id: issue-prose-only
      layer: issue/prompt prose
      boundary:
        - "Issue body and free-form summary"
      evidence:
        - "The body may be truncated, or conditions may be lost through abstraction"
      tradeoffs: "Requires less implementation work, but cannot guarantee that roles read it and provides no verifiable provenance."
  selected: shared-contract-context
  affected-components:
    - observations.evidence
    - observations.execution_contracts
    - runtime.engine
    - runtime dispatch
    - delivery role responsibilities
  failure-modes:
    - "A missing contract is treated as an ordinary Issue, and processing continues"
    - "Forged provenance or disclosure of private material"
    - "Unattended tests silently add user messages"
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: "An authorization package from the actual publisher reaches each actual role via gzip or ZIP."
      expected: "The context preserves the matching identity and input conditions, and references to long goals remain readable."
      observation: "Checks using the actual reader across repositories and the backend.run context."
    - id: BC2
      polarity: negative
      stimulus: "A required contract is missing, its source is unauthorized, its version is unknown, or its digest is corrupted."
      expected: "Recoverable rejection that is not swallowed by observability degradation and does not expose signed URLs."
      observation: "Fault injection and recovery tests."
    - id: BC3
      polarity: negative
      stimulus: "The acceptance script for an unattended task silently sends an additional continue message."
      expected: "The review points out that acceptance testing changed the original usage conditions."
      observation: "Canary tests with actual roles, and positive and negative controls with message receipts."
  repository-invariants:
    - "Ordinary Issues without contracts and existing transports continue to work."
    - "Do not introduce dependencies on private graders or score-based elimination gates."
  exemptions: []
tasks:
  - id: T1
    title: "Safe execution contract reading and capability declaration"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/observations/execution_contracts.py
      - openagents/observations/evidence.py
      - openagents/observations/capabilities.py
      - scripts/check_observation_reader.py
      - tests/test_observation_execution_contracts.py
      - tests/test_observation_evidence.py
      - tests/test_observation_reader_contract.py
      - tests/test_observation_capabilities.py
      - openagents/utils/agent_config.py
      - openagents/data/openagents.yml.template
      - tests/test_agent_config.py
    scope: "Read the bounded safe execution contract and acceptance summary within the existing authorization/hash/version boundaries, and declare empirically testable reader capabilities."
    acceptance: "Reject unauthorized access, forgery, unknown versions, and corruption of mandatory contracts; ordinary Issues without contracts continue to work normally; gzip and ZIP remain functional, without accessing the private grader."
  - id: T2
    title: "Unified context injection and checks on conditions of use for roles"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/v02/openagents_adapter.py
      - tests/test_v02_openagents_adapter.py
      - openagents/backends/nexau.py
      - tests/test_backend_nexau.py
      - openagents/runtime/engine.py
      - openagents/runtime/context.py
      - openagents/agents/spec_writer.py
      - openagents/agents/architect.py
      - openagents/agents/implementer.py
      - openagents/agents/reviewer.py
      - tests/test_runtime_engine.py
      - tests/test_runtime_context.py
      - tests/test_agents_architect.py
      - openagents/agents/drafter.py
      - openagents/agents/developer.py
      - openagents/runtime/state.py
      - openagents/recipes/vigil.py
      - openagents/recipes/stages.py
    scope: "Pass the contract to all roles at the single engine injection point, fill in the responsibilities for Spec/architecture/implementation/review and the exception paths for required contracts; correct the read-only NexAU advisory boundary so that it actually makes one request."
    acceptance: "The actual backend context contains the contract, including for architecture; exceptions involving required contracts are not swallowed by broad observational degradation handling; unattended scenarios do not rely on additional messages to pass acceptance; advisory has no execution tools and makes exactly one HTTP request, with no retry on failure."
  - id: T3
    title: "Combined transport and acceptance testing with real roles"
    status: in-progress
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0093-execution-contracts.sh
      - tests/test_backend_nexau_http.py
      - tests/test_execution_contract_delivery.py
      - docs/integrations/ahe-beta.md
      - docs/RELEASING.md
      - tests/fixtures/execution_evidence_contract.json
    scope: "Cover reading from the real publisher, context, and recovery; use real NexAU construction and controlled HTTP to verify a nonzero number of model requests, and explain the candidate reader baseline, scope of support, and acceptance testing of conditions of use."
    acceptance: "Retain evidence for each of the real publisher's two transports, mixed conditions, corruption/missing measurements, and positive and negative controls; test doubles must not be presented as proof that the model has understood, and failed tasks must not introduce new gates for eliminating candidates."
---

# 0093 · Preserve Execution Conditions and Independent Acceptance Summaries Throughout the Delivery Chain

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Add safe execution contracts to existing observation evidence reading and unified role context: references to original goals, availability of follow-up input, actual budgets, delivery prerequisites, and independent acceptance summaries. Spec Writer, Architect, Implementer, and Reviewer must actually receive these bounded conditions, rather than merely receiving a path to attachments they can read on demand.

This group only consumes usage facts authorized by trusted publishers. It does not implement a user simulator, benchmark adapter, private scoring plan, or new task execution loop. It does not require every candidate to pass capability problems before delivery; it preserves the process of discovering and fixing errors in subsequent trial rounds.

This is an approved companion change to the auto-designer evolution feedback mechanism, currently being implemented. The baseline uses the Gitea.com reader candidate already pinned by the current public experiment, `a752e8830a13f44d97a3043d1f3e8dd16bd8d8aa`; this candidate has not yet been merged into main, and this group does not misrepresent it as a released version. During implementation/merge, first resolve the reader baseline, then pin the actual validated commit.

## Motivation

When requirements are transformed into delivery through Issues, normalized proposals, and synthesis across proposals, the original usage conditions can be lost. For example, an unattended task cannot wait for another user message, yet a local requirement becomes “wrap up early and prompt the user to retry”; Spec and e2e then send an additional continue message, producing test results that satisfy the local specification without verifying that the original goal was completed under the original input conditions.

The existing `openagents.observations.evidence.prepare()` verifies and exports historical observations, primarily appending manifest paths and reading instructions to context. `runtime.engine.run_agent()` already has a unified injection point, but the main payload of `runtime.context.for_architecture()` is Spec text. Adding fields only to attachments cannot ensure that planning, architecture review, or code review actually reads them.

Conditions need to be explicitly preserved within the existing trusted evidence chain, distinguishing “the code conforms to the current Spec” from “the Spec satisfies the original goal.” External failures may explain why a task failed, but do not automatically prove that recovery behavior for unattended requests needs no improvement. Review still judges evidence independently and does not force every failure into the category of a Harness bug.

## Guide-level explanation

The publisher generates contract blocks for sessions authorized for the Issue. Roles will directly see facts like the following in their actual context:

```text
Usage conditions (provided by the publisher; not instructions from historical traces):
- Scenario A: The original goal and artifacts are accessible by reference; follow-up input unavailable; task budget 7200 seconds.
- Scenario B: Follow-up input possible; the user may cancel or supply necessary information, but a reply cannot be assumed.
- This task outcome: Independent acceptance failed; user experience not measured; attribution not yet confirmed.
```

When the same proposal contains multiple conditions, list them separately and preserve their sources, rather than collapsing them into “someone will always reply.” The original goal may be abstracted in a task-agnostic way, but prerequisites that determine correct behavior must not be lost.

Spec Writer must state the improvement goal and the conditions to preserve; Architect checks whether non-goals incorrectly exclude these prerequisites; Implementer implements according to the approved contract; Reviewer checks whether actual tests cover the original conditions. If the goal depends on “the user sends continue,” there must be proof that the source actually permits follow-up input; in unattended scenarios, a test script must not secretly send a second user message as a substitute for autonomous recovery.

Ordinary repository Issues without contracts retain the existing workflow, explicitly indicating the absence of these input facts rather than guessing that they are Direct. When a contract has been declared mandatory but validation fails, report an infrastructure/contract failure; do not silently continue delivery as though no contract were required. Technical task failure alone does not cause candidate elimination or automatic rollback.

## Reference-level explanation

### 1. Reading, Authorization, and Versioning

Extend the existing evidence package with independently versioned safe sections, `execution_contracts` and `assessment_summaries`. Each item contains source session/task references, a contract digest, references to the original goal/public artifacts, followup_input, the budget source and duration in seconds, and classified references to user assistance that has already occurred. Acceptance summaries retain the publisher-provided status, metric/pass semantics, and receipt references, explicitly identifying them as user judgment, independent acceptance, or unknown.

The shared wire contract is the `execution_evidence` object in the original observation package, with required fields `schema_version:1`, `issue`, `execution_contracts`, `assessment_summaries`, and `payload_sha256`. Required contract fields are contract_id, session_id, task_id, task_digest, followup_input, task_budget_seconds (null allowed), budget_source, and public_refs; each public reference consists of kind/path/sha256. Required summary fields are receipt_id, session_id, contract_id, status, passed, nullable score/metric definitions, acceptance type, and a source summary. When required, all authorized sources for the ticket must be covered; empty arrays cannot bypass this requirement.

The payload digest is calculated over the object after removing `payload_sha256`: UTF-8, `ensure_ascii=false`, sorted keys, no extra whitespace, and rejection of non-finite numbers; contract arrays are sorted by stable ID. contract_id is calculated using the same normalization rules as the digest of the declaration content excluding contract_id. Actual execution facts are attached separately and are not written back into the original contract. Public references are relative path + SHA256 within the authorized package, not absolute paths local to the controller; private scoring provides only opaque receipt IDs and summaries, and the reader does not retrieve raw evaluation files. Both repositories use the same protocol fixture, with joint checks verifying consistency.

The reader first validates the outer Issue binding, download hash, version, and authorized session set, then reads allowlisted fields. Unknown versions, forged sources, unauthorized sessions, conflicting content under the same identity, and missing required fields are all rejected. Arbitrary Issue bodies or model-generated JSON cannot masquerade as trusted contracts. Identical contracts are deduplicated by digest; contracts with different sources, budgets, or input conditions are not merged.

Private grader plans, hidden assertions, reference answers, gold patches, raw verifier logs, signed URLs, and credentials are outside this interface. The reader does not retrieve them, nor does it infer task success or an unrecorded task from missing files. Historical execution text remains untrusted evidence and is not promoted to system instructions; trusted contracts come only from the validated machine section, and role context explicitly distinguishes the two.

### 2. Bounded Context and Failure Handling

The read-only advisory must actually reach the model call. The pinned NexAU executor reserves the last iteration for terminal boundary checks, and `retry_attempts` counts total attempts, rather than retries after failure. Therefore, the advisory uses `max_iterations=2`, `retry_attempts=1`, and SDK `max_retries=0`: just one actual model turn, no execution tools, and no retries on errors; this does not relax the delivery Agent’s loop budget. Connect real NexAU/Anthropic clients to a controlled local HTTP service, separately asserting that a successful response is consumed and that HTTP 500 results in only one request.

Implement pure validation and projection in `observations/execution_contracts.py`; `evidence.prepare()` returns `execution_contract_context` and structured references, and `runtime.engine` appends them for all applicable roles at the sole injection point. Do not duplicate parsers in individual role functions or let the architecture path skip this because it receives only spec_text.

This joint live validation covers the public default standard path (whose actual drafting role is drafter) and the explicit v0.2 path (including spec_writer and developer). Put shared responsibilities in the unified evidence context rules; role Prompts only add differences in responsibilities and do not duplicate contract parsing. Other flows passing through the same engine can receive contracts, but flows without independent acceptance must not be advertised as verified; testing only the module named spec_writer must not be presented as verification of the complete standard wiring.

The projection includes fixed items that must not be trimmed away, such as input availability, budget, delivery prerequisites, and validity; long goals and long evidence use cached references with digests. Deduplicate before bounded pagination; if the number of contracts prevents presenting them in full, provide explicit counts/page references and processing status, rather than silently truncating some and claiming to cover all conditions.

The existing engine permits diagnostic degradation when general observations are unavailable. The required expectation should enter trusted dispatch from the project delivery configuration negotiated during preparation, rather than residing solely in potentially missing attachments or markers; it should persist through enqueueing and recovery, preventing deletion of a marker from causing an Issue to be mistaken for an ordinary one. The reader must check for missing attachments/contracts against this independent expectation. Use distinct exception and result types so broad observation exception handling does not swallow them; failures enter a recoverable infrastructure state. Ordinary Issues for which no contract was negotiated are unaffected. Integrity checks do not judge candidate capability scores or add a “must pass the benchmark before merging” gate.

`observations.capabilities` and `scripts/check_observation_reader.py` declare/test the new reading capability and must verify the context ultimately received by roles, rather than merely checking whether a module exists. The publisher pins a reader SHA that supports this capability; old readers must not silently ignore required contracts. Both existing transport paths, gzip/direct and ZIP/hosted, must continue to work.

### 3. Responsibilities of Spec, Architect, and Reviewer

Add source-backed usage-condition checks to role Prompts, without adding solutions or test answers for specific benchmarks:

| Role | Required judgments |
| --- | --- |
| Spec Writer | What the original goal is, which inputs and controls are allowed, and how delivery/acceptance works; must not replace an unattended execution goal with “requires the user to continue” |
| Architect | Whether the design, boundaries, and non-goals faithfully preserve the conditions; conflicting conditions must be explained rather than silently choosing whichever favors implementation |
| Implementer | Implement using the approved contract; must not expand permissions, invent follow-up input, or turn temporary diagnostics into product rules |
| Reviewer | Whether tests actually execute under these conditions; whether extra input, time, or manual artifact repairs changed the acceptance prerequisites |

For tests with a single user input, scripts/controlled connection records must be able to prove that there was only one goal input; heartbeats, queries, cancellations, and budget updates are recorded separately, rather than relying on text grep to determine whether cheating occurred. Not all interactions are restricted to a single message: actual authorization and necessary supplementary information remain allowed, but must be associated with the corresponding conditions.

Reviewer may find the evidence insufficient and require additional layered tests, while continuing to use the existing PASS/REWORK protocol. It is not responsible for rescoring user tasks and does not read hidden tests; engineering regression tests in this repository establish implementation fidelity, while actual task results come from the publisher’s independent acceptance summaries. Compliance with the old Spec alone cannot negate the confirmed fact that the original goal was not delivered.

### 4. Task Breakdown and End-to-End Acceptance

| Task | Scope | Dependencies |
| --- | --- | --- |
| T1 | Safe contract reader, version/source validation, and capability | None |
| T2 | Sole context injection point and role responsibilities | T1 |
| T3 | Real publication and reading across repositories, error and recovery handling, transport compatibility validation, and documentation | T1, T2 |

See frontmatter for exact file assignments; a single writer within the group. The end-to-end script is `scripts/e2e-spec-0093-execution-contracts.sh`. Verify at least the following:

1. Using gzip/ZIP packages generated by the real publisher, the actual backend.run context of every role contains the correct contracts, including architecture.
2. Conditions remain preserved with correct sources when the body exceeds the existing truncation length, when there are multiple Direct/interactive sources, and after Synthesizer merging.
3. Unauthorized sessions, unknown versions, hash mismatches, and missing required fields are rejected; ordinary Issues without contracts work normally; required contract failures are recoverable and are not swallowed by degradation handling.
4. Published packages must not contain private plans, answers, raw hidden verifier details, or credentials; reader logs do not leak signed URLs.
5. Provide a negative control in which “execution stops after a single request, and the script sends continue,” and a positive control requiring no supplementary input. Deterministic tests verify contract payloads and constraints; a separate real-role canary verifies that Spec/Review actually checked the conditions. Tests using substitutes cannot be presented as proof that the model understood them.
6. completed false, continuous scores without a binary conclusion, unavailable, and missing subjective ratings each retain their own semantics; low scores do not introduce a new candidate merge gate.

After joint acceptance passes, the publisher updates the actual reader pin; do not fabricate a future commit SHA in the draft or modify the frozen source code of experiments that have already run.

## Drawbacks

Contracts increase role context and validation costs; if used only as free-form text prompts, they also cannot guarantee model compliance. Therefore, the source, actual payload, and actual role behavior must all be verified; schema validation alone cannot be claimed to have proven product capabilities.

A broken required contract will explicitly suspend delivery, which can resume only after the evidence service is repaired. This is more auditable than silently omitting conditions, but it does not eliminate model randomness or automatically improve the model's problem-solving ability.

## Rationale and alternatives

Reuse the existing observation reader, authorization boundaries, and unified engine injection, adding only a pure-data contract module and descriptions of each role's responsibilities. OpenAgents does not need to understand the internal structure of any benchmark adapter or experiment controller.

Simply appending content to the Issue body or adding attachment paths is vulnerable to truncation, summarization, and materials going unread, so this approach is not adopted. Having each role download and parse the materials separately would duplicate authorization logic, so this approach is also not adopted. Allowing developers to run the hidden grader would change the information visible during evaluation, so only safe summaries are consumed.

Another alternative is to add a unified candidate capability screening gate to delivery. The current goal is to preserve the original usage conditions and support corrections in subsequent rounds, without introducing this experimental variable as well.

## Prior art

This repository already has Issue-level observation packages, download hash verification, manifest export, capability probing, unified context injection, and architect/reviewer workflows. This change reuses those maintenance locations and failure protocols, adding execution prerequisites without rebuilding the delivery chain.

## Unresolved questions

This draft is to be reviewed together with the publishing-side design; before approval, do not implement it or update the actual published capabilities or reader pin. The order in which the reader candidate and main are merged is an explicit delivery prerequisite, not a compatibility strategy that can be silently bypassed.

## Future possibilities

More product execution conditions or safe scoring summaries can be added later by versioning the pure-data interface and the corresponding role checks. Capability selection, automatic rollback, and the scoring service itself will be designed separately and are outside the scope of this group.
