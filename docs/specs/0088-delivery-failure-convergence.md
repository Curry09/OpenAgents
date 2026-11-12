---
number: "0088"
title: "Approval identity and failure convergence for parallel delivery"
issue: 0
slug: delivery-failure-convergence
summary: "Renumbering self-references in the Spec does not revoke semantic approval; reasonable design changes return to the existing review (not yet implemented), and failures without sufficient evidence are not automatically revived."
tasks:
  - id: T1
    title: "Versioned design digests and approval auditing"
    status: pending
    priority: P1
    depends-on: []
    files:
      - openagents/spec/model.py
      - openagents/runtime/gates.py
      - openagents/recipes/stages.py
      - openagents/runtime/state.py
      - tests/test_spec_model.py
      - tests/test_runtime_gates.py
      - tests/test_recipe_stages.py
      - tests/test_runtime_state.py
    scope: "Digest normalization and auditing of original approvals have been implemented; the acceptance criteria were revised on 2026-09-09, but the integration that returns digest changes to the existing architecture review has not yet been implemented. This change only modifies the requirements and does not alter the running experiment."
    acceptance: "Renumbering self-references does not revoke approval; a digest mismatch means the old approval does not cover the current design, so return to the existing architecture review instead of repeatedly attempting to merge. Make the determination based on the original requirements, constraints, and old design, together with the current main branch and candidate changes; reusing the implementation on the main branch must not lose the original acceptance criteria. Once reasonable adjustments pass review, update the existing approval and continue the original delivery process. Unconfirmed weakening of goals, constraints, or acceptance criteria must not be allowed through; insufficient evidence requires explaining the gaps and reworking the changes. Do not migrate old approvals based on guesses, directly replace them with the current digest, or introduce new roles, stages, or approval ledgers."
  - id: T2
    title: "Consistent reading and writing of failure markers and conservative convergence when evidence is missing"
    status: done
    priority: P1
    depends-on: [T1]
    files:
      - openagents/recipes/vigil.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - scripts/e2e-spec-0088.sh
    scope: "Code changes are complete. Approval digests are persisted with the run; the failure marker is read according to the issue or PR to which the subject belongs, without reusing attempt comment routing."
    acceptance: "After an issue with an associated PR fails, do not requeue it while the facts remain unchanged; missing or invalid markers preserve the terminal state; a genuine change in facts permits one recovery; standalone PRs remain supported."
---

# 0088 · Approval Identity and Failure Convergence in Parallel Delivery

## Summary

The initial code changes are complete. They fix two delivery framework issues discovered in the two-user experiment, without replacing the source code or images of the archived experiments.
2026-09-09: This revision changes only the acceptance criteria for T1: reasonable design changes may be reconfirmed through the existing review process;
the corresponding return to review has not yet been implemented, so T1 is marked pending again, while the existing implementation of T2 remains done. The test results below apply to the initial implementation
and do not constitute evidence that the new acceptance criteria have been implemented.
Offline integration regression entry point: `bash scripts/e2e-spec-0088.sh`; covers actual Spec reads and writes, the approval gate, state persistence,
failure marker reads and writes, and scheduling. forge and the model use test doubles; this is not claimed to be end-to-end validation with a real model in a new image.
2026-09-09: The final full regression run reported 1223 passed, the integration entry point above reported 235 passed, and Ruff check and Spec/graph validation passed.
Local HTTP tests in the full regression suite require an environment that permits creating loopback sockets; sandbox permission denials are not attributed to product failures.

The original digests of the actual archived post-rebase histories `e5dc3fc`（0002）and `b65184a`（0005）are, respectively,
`e1221dd3b7bfa9c45281ee1600de9d2eeadb1727a40622651ec6289f5c71bef0` and
`71b06698f1550998dffd46cb79a8dca7b62051fb7646580240a9a3578a88b41d`, matching the manually verified audit.
Both new semantic digests are `v2:b96ed7ffbce8e4163cc147c61050d8cbd237d9827ab26c473ebcd1befda79c4d`;
modifying the acceptance criteria in memory changes the new digest. The original experiment archives have not been modified.

## Motivation

In the 2026-09-08 spec61 two-user experiment, issue #8 changed from Spec-0002 to 0005. A change solely to the
self-reference in the task description caused the approved digest to mismatch; failure markers were written to the issue, but reads followed the PR, causing repeated revivals when markers were missing.
The evidence is in archive/harness.bundle, telemetry/gitea-snapshot.json, and manual-interventions.jsonl
under the adjacent auto-designer-experiments/spec61-two-user-glm53-glm52-20260908 directory.

## Guide-level explanation

New approvals use versioned semantic digests; explicit renumbering of self-references is an identity migration, not a new design. The raw design digest is still persisted,
and the original text is retained by Git and the architecture input audit. Old approvals retain exact matching against the original digest; automatic reapproval is not permitted without a trusted old snapshot.
A failure state is cleared only when a valid marker for the object it belongs to is found and the facts have actually changed; when the marker is missing, the failure is explicitly retained, without repeated retries.

Revised acceptance criteria (return to review pending implementation): a digest identifies only the version covered by approval; it does not determine whether a change is reasonable.
After a digest changes, reuse the existing architecture review to assess the change against the original requirements, constraints, originally approved design, and the differences between the current main branch and the candidate.
For example, if another ticket has already implemented the same capability on the main branch, this ticket may reuse it instead of implementing it again, but it must demonstrate that the final version still satisfies
this ticket's original acceptance criteria; the bar must not be lowered by deleting requirements or tests. Once a reasonable adjustment passes review, update the existing approval record
and continue the existing code review and merge process; do not introduce new stages, roles, or approval ledgers into the framework. Approvals and test results must still correspond to
the candidate version actually examined; a successful rebase alone must not automatically allow it through.

## Reference-level explanation

design_digest v2 normalizes only standalone Spec-NNNN/Tn references in prose, and only when NNNN is the current group number and Tn exists.
They are normalized into typed fragments to avoid collisions with ordinary text placeholders; file declarations and dependencies participate in the digest unchanged.
legacy_design_digest retains the original algorithm; merging selects the algorithm according to the approval version and does not rewrite approvals from the current source code.
design_raw_digest is saved alongside new approvals and must not be overwritten or lost during subsequent state changes.
Failure reads are routed separately by subject, decoupled from the existing PR-first routing for attempt-stamp.
The existing convention for recognizing identity markers remains in use; textual markers are not claimed to provide cryptographic identity authentication.
The above describes the digest and failure convergence mechanisms implemented in the initial version. The return to review required by the revision must be added to the existing delivery process;
this revision changes no runtime code and no approval states in any running or archived experiments.

## Drawbacks

In the current implementation, mismatched legacy approvals still require manual verification and cannot be automatically revived by upgrading. Once the return to review is connected as required by the revision,
the existing architecture review will confirm changes based on trusted original context; if the original requirements or the previously approved design cannot be obtained, approval must not be granted by guesswork.
Only explicit syntax can be normalized automatically; other changes are left to review. A reasonable change may require one additional invocation of the existing review.

## Rationale and alternatives

Do not automatically accept new digests, disable the architecture gate, replace numbers globally, or introduce a shared number allocation service for renumbering.
Retaining the failure when a marker is missing is preferable to treating a gap in reads as an actual new fact.

## Prior art

The existing implementations of design digests and assert_design_approved in this repository, and the fact-fingerprint failure convergence contract in Spec-0081.
Recognition of automation-failed in the outer layer is fixed separately by auto-designer Spec-0062.

## Unresolved questions

Source-code regression testing is not equivalent to end-to-end validation with a real model in a new image; deployment must rebuild and freeze a new image without replacing the old experiment artifacts.

## Future possibilities

First verify that the existing return to review can handle positive and negative examples involving reuse of the main branch, reasonable design adjustments, and weakened acceptance criteria; do not expand a set of number replacement rules that guess semantic
equivalence. Merging remains prohibited until valid approval has been obtained.
