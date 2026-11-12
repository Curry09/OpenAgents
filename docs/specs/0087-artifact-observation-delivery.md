---
number: "0087"
title: "Artifact observation evidence handoff and development reinforcement loop"
issue: 0
slug: artifact-observation-delivery
summary: "Obtain a version-matched, restricted diagnostic evidence bundle by issue; developers separately maintain the impacts on user feedback and diagnostic observations and validate each independently against its acceptance criteria. Only gaps in maintainer diagnostics are reported back through an authenticated runner for reinforcement."
architecture:
  objective: "Enable each development stage to read observations from historical versions within the authorization scope of the current issue and reliably report specific diagnostic gaps."
  constraints:
    - "Do not parse artifact event fields, expand the issue's session permissions, or change the frozen target."
    - "Keep read-only copies of historical evidence separate from current test results; do not use the existence of logs as a substitute for behavioral acceptance."
    - "Distinguish user feedback from maintainer diagnostics by whom they serve and what they aim to assess. They may share an implementation but must undergo independent acceptance, and dependencies must not be established automatically based on category."
  non-goals:
    - "Do not introduce a dedicated logging role or a unified schema for runtime events."
  candidates:
    - id: scoped-forge-attachment
      layer: delivery runtime
      boundary: [configured Gitea origin, current issue attachment membership]
      evidence: [runtime.engine role binding, Gitea issue assets API, content digests]
      tradeoffs: "Keep download and copy overhead bounded; explicitly degrade on transport failures while retaining other evidence paths."
  selected: scoped-forge-attachment
  affected-components: [runtime.engine, utils.gitea, observations.evidence, observations.gaps]
  failure-modes:
    - "External links, digest mismatches, or version mismatches must be rejected; do not present them as successes."
    - "Retain the outbox for offline reporting; retries with the same ID must not submit duplicates."
verification:
  behavior-cases:
    - id: BC1
      polarity: positive
      stimulus: "An authorized issue carries an observation package in the new format, and the development role starts."
      expected: "The role receives an entry point for reading the corresponding version; the runner reports specific gaps that can be written."
      observation: "test_observation_evidence.py and controlled cross-version experiments with auto-designer."
    - id: BC2
      polarity: negative
      stimulus: "External paths, packages from other issues, tampered digests, or unauthorized session requests."
      expected: "Reject privilege expansion or invalid packages; they must not be treated as original facts or used to generate supplementary evidence beyond the authorized scope."
      observation: "Tests cover path, digest, identity, and reference checks."
  repository-invariants:
    - "Do not initiate evidence collection from Gitea when GitHub has no such attachment contract."
    - "The artifact's internal event dictionary must not enter the runner's parsing logic."
  exemptions: []
tasks:
  - id: T1
    title: "Restricted attachment access, role responsibilities, and reinforcement reporting"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/observations/evidence.py
      - openagents/observations/gaps.py
      - openagents/runtime/engine.py
      - openagents/utils/gitea.py
      - openagents/recipes/stages.py
      - openagents/recipes/vigil.py
      - openagents/v02/openagents_adapter.py
      - openagents/runtime/context.py
      - tests/test_observation_evidence.py
    scope: "Code changes are complete. Fix the transport shell without interpreting artifact events; include evidence for the current issue only, and report gaps in maintainer diagnostics back through an authenticated runner; role contracts distinguish user feedback objectives from diagnostic objectives."
    acceptance: "Checks for format changes, version retention, and the absence of external links, as well as negative tests for tampering and unauthorized access, pass; roles actually enabled receive the evidence entry point and reinforcement path."
---

# 0087 · Artifact Observation Evidence Handoff and Development Enhancement Loop

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine rust-RFC sections. -->

## Summary

Code changes are complete. In conjunction with auto-designer spec-0061, the development runner gathers evidence
from the current issue's restricted attachments, providing version-matched reading entry points and enhancement
request paths for the existing Spec Writer/Drafter, Architect, Developer/Executor, and Reviewer/Acceptance.
No roles are added, and the freezing semantics of the Objective Contract remain unchanged.

The full regression run on 2026-09-08 had 1196 passed; the functional code commit is `1dda04ab2de550685b7bc181f6b61b26f8972b51`.
The pinned image `auto-designer-vigil:observability-spec61-1dda04a` has been verified to read private Gitea
attachments in a container with no host mounts; enhancements on both the requirements and development sides
have undergone validation with a controlled Owner, an actual PR merge, and review in a new-version session.
Role decisions were scripted; this does not amount to actual models autonomously adopting observations or
validation of the full Vigil engineering gates. For detailed results, see auto-designer
`docs/audits/0061-observation-lifecycle-validation.md`; the old experiments and latest image have not been replaced.

Subsequent clarifications of the boundaries between objectives have updated the shared development context.
All 15 existing observation regression checks pass, covering context handoff and diagnostic reporting for all
integrated roles. These regressions do not prove that actual models reliably distinguish user feedback from
diagnostic objectives; the image and full regression run in the preceding paragraph validate the earlier
lifecycle implementation. The new image containing the boundary clarifications is determined by the
auto-designer deployment pin.

## Motivation

Development containers cannot see host log paths; the current source version does not necessarily match
the version associated with historical events. Merely changing prompts or having agents search all sessions
on their own is unreliable and exceeds the evidence scope. Feature development must maintain both diagnostic
capabilities and the accompanying version-specific documentation.

## Guide-level explanation

The two types of objectives are distinguished by whom the information serves and what judgments it supports,
regardless of the role that discovers the need or the underlying event source:

- User-facing status feedback: users understand the current situation during use and decide what to do next.
  Acceptance checks whether the information actually visible at the decision point is accurate, timely, and
  supports the required judgment; backend logs or after-the-fact explanations cannot substitute for it.
  Requirements follow the ordinary product proposal process.
- Design and development diagnostics and observation: maintainers reconstruct what happened, distinguish
  causes, and verify changes. When there is a specific question, first read the version-specific documentation
  and authorized records; acceptance checks whether evidence from the corresponding version can answer that
  diagnostic question. The presence of progress indicators cannot substitute for it.

Within its existing sections, the Spec separately describes “user feedback impact” (when users learn what,
and which decisions this supports) and “diagnostic observation impact” (what needs to be reconstructed or
distinguished, and whether existing evidence is sufficient), along with their respective verification.
If there is no impact, a brief explanation is sufficient. Implementation must also maintain the affected
user output/help, diagnostic records/reading instructions, and tests. The two may share an implementation
within the same issue or delivery, but retain independent acceptance and the individual statuses of linked
issues; passing one cannot be used to close the other, and splitting them into separate issues is not mandatory.

Request files are dedicated to gaps in evidence gathering for maintainer diagnostics. question, impact, and
verification should clearly state the maintainer's question, its impact on judgment, and diagnostic verification.
When development roles discover insufficient user feedback, they retain the specific requirement and its links
in the existing delivery report and pass it to the requirements side for handling as an ordinary product
proposal. They must not disguise it as a logging gap or claim that the report has already created an issue.
If the objective is already within the frozen contract, implement it normally; otherwise, do not independently
expand the frozen objectives. Neither type of requirement imposes a prerequisite gate on the other; explicitly
mark a blocker only when choosing an approach or verifying it is actually impossible.
After validating the references in a diagnostic request, the runner reports it through an authenticated Gitea
comment. Transient failures remain in the outbox and are retried on the next invocation.
`observation-gap` and the request format remain compatible; no semantic classifier is added, and no claim is
made that text validation can automatically identify misrouted requests.

## Reference-level explanation

The fixed envelope is `auto-designer:observation-evidence-v1`: a machine handle in the issue body specifies
that issue's attachment ID, digest, and size. Downloads request only UUIDs of attachments belonging to that
issue from the configured Gitea origin, use no external links, and prohibit redirects; both compression and
decompression are bounded. The JSON package contains only text files, versions, and digests from authorized
sessions; files are not executed. The cache is validated before each role invocation and stored in isolation,
without writing to harness main. The internal log format is determined by the artifact.

A gap includes the question, scope already examined, unknowns, impact, expected capability, verification, and
authorization references. The runner binds the actual role/issue and reports back with a signed comment
containing a stable request_id; auto-designer accepts only authenticated automation identities, revalidates
authorization, and records an ordinary proposal. framework scope records infrastructure diagnostics only;
the framework remains fixed during the experiment, and no harness delivery issues are generated.

On restart and while idle, Vigil's regular tick / v0.2 adapter startup triggers a single bounded background
retry of pending reports, providing a recovery opportunity without waiting for a new agent task and without
blocking scheduling. Report deduplication checks all necessary comment pages by authenticated account;
when the scan limit is reached, the report remains pending, rather than assuming it does not exist and
submitting it again. The runner cache is isolated from the artifact source through Git's local exclude
mechanism and does not depend on the artifact's .gitignore.

## Drawbacks

Evidence gathering adds bounded I/O; when attachments are unavailable, the system explicitly falls back to
other evidence rather than pretending the logs are empty. Identity boundaries in a private experimental
repository do not amount to multitenant isolation.

## Rationale and alternatives

Reuse the existing forge and roles without introducing a public internet logging service, mounting all host
sessions, or mandating a shared event dictionary. The runner handles transport and validation, while agents
retain discretion over reading and judgment as needed.

## Prior art

0074 provides the Gitea boundary, 0078 records invocation audits, and 0082/0083 retain independent objective
acceptance; auto-designer 0059/0060 define native log reading and dual-track input isolation, and 0061 defines
the lifecycle of artifact-owned logs across rounds.

## Unresolved questions

Changes to the published envelope version require compatibility testing on both sides; deployment must
update the image pin, since source changes do not mean that running containers have been updated.

## Future possibilities

Compare how well specific diagnostic questions can be answered, rather than measuring quality by log volume;
replacing the harness requires no changes to this transport layer.
