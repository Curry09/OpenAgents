---
number: "0021"
title: "Fix long reviewer replies being truncated before VERDICT → UNPARSED → false non-PASS results that waste rounds and incorrectly trigger needs-human"
issue: 63
slug: reviewer-truncated-verdict-fix
summary: "Fix the bug where long reviewer replies are truncated before the VERDICT line, causing parsing failures (UNPARSED) to be misclassified as \"non-PASS\", needlessly consuming Vigil rounds and even incorrectly triggering needs-human. Approach: put the verdict token first, parse the first line, distinguish \"the review itself is invalid\" from \"genuine REWORK\", and add a single retry of the review and truthful escalation. Change only reviewer parsing and fault tolerance in the orchestration layer; do not change the verdict criteria themselves."
tasks:
  - id: T1
    title: "Reviewer side: verdict token first + first-line parsing + distinguish \"invalid reviews\" + a single retry of the review"
    status: done
    priority: P0
    tags:
      - backend
      - reviewer
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/reviewer.py
      - tests/test_reviewer.py
    scope: "Strengthen _RUBRIC_TAIL to require VERDICT at the very beginning of the reply (before any reasoning); _parse_verdict prioritizes parsing the first line/paragraph and falls back to matching the full text if unsuccessful; review() reruns backend.run once for a reviewer whose result parses as UNPARSED; add a boolean field actionable to ReviewDecision to distinguish \"genuine REWORK (REWORK/RETHINK was parsed and there is substantive ISSUES body text)\" from \"invalid review (non-PASS solely because the verdict cannot be parsed or there are no actionable items)\"; render_decision renders \"invalid review\" and \"REWORK\" separately. Use keyword-only parameters and pass arguments explicitly to private functions."
    acceptance: "Unit tests with a stubbed AgentBackend: truncated positive review (no VERDICT, still absent after rerun) → passed=False and actionable=False, with verdicts containing UNPARSED placeholders and length=N; genuine REWORK with ISSUES → passed=False, actionable=True, feedback contains ISSUES; first-line VERDICT:PASS + a bare REWORK word in the body → parses as PASS; first run UNPARSED, rerun PASS → backend.run called twice, final passed=True; rerun still UNPARSED → rerun only once and classify as \"invalid review\"; all PASS → passed=True, actionable=False, feedback=\"\"; render_decision renders different messages for \"invalid review\" and \"REWORK\"; all existing regression tests pass; ruff check + ruff format --check + pytest pass."
  - id: T2
    title: "Orchestration layer: invalid reviews do not consume rounds, empty feedback does not cause pointless iterations, and truthful escalation follows a separate retry limit"
    status: done
    priority: P0
    tags:
      - backend
      - orchestration
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
      - openagents/state.py
      - tests/test_state.py
    scope: "_process_rfc_review / _process_coding branch on decision.actionable when not passed—genuine REWORK continues to use rounds++ + refine_rfc/iterate as before (behavior remains byte-for-byte unchanged); \"invalid review\" does not perform rounds++ or refine/iterate, and instead uses a separate small retry counter (env OPENAGENTS_MAX_REVIEW_RETRIES, default 2); if the limit has not been exceeded, return a review-invalid event for this cycle and wait for the next cycle to review again; once exceeded, call _block to apply needs-human with the truthful reason \"reviewer output cannot be parsed\" (gate carries a distinguishable marker); add a review-invalid counter field to State/RunRecord independent of rounds (default 0, backward compatible), with a corresponding increment_review_invalid, and reset it to zero at the same points as the existing reset_rounds. Use keyword-only parameters and pass arguments explicitly to private functions."
    acceptance: "Unit tests monkeypatch github.* + inject stubbed ReviewDecision instances: truncated positive review (passed=False, actionable=False) at both spec/merge gates does not call increment_rounds or refine_rfc/iterate, and returns reason=\"review-invalid\"; genuine REWORK continues to call increment_rounds + refine_rfc/iterate(detail=feedback); MAX_REVIEW_RETRIES consecutive invalid reviews → _block applies needs-human, with a gate identifier distinguishable from a block for genuine REWORK; the review-invalid counter is reset to zero at the same points as implement / reset_rounds; env missing/invalid/<1 → fall back to the default of 2; no regressions—all existing tests for default all PASS → merge → done, genuine REWORK → rounds++ → iterate, and reaching MAX_ROUNDS → _block pass; ruff check + ruff format --check + pytest pass."
---

# 0021 · Fix long reviewer responses truncated before VERDICT → UNPARSED → false non-PASS results wasting rounds and incorrectly triggering needs-human

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Fix a bug where a long reviewer response is truncated before the `VERDICT` line and incorrectly classified as “non-PASS” (issue #63, observed in PR #61 / issue #58). The reviewer is a stateless function that “reads the RFC/diff → returns a verdict token.” The model often puts a lengthy argument first and leaves `VERDICT` until the end. When a long response is truncated before the token, `_parse_verdict` cannot find the token and returns None, which is normalized to UNPARSED under a “when in doubt, treat as failure” policy and counted as non-PASS. As a result, a response containing **nothing but praise** is treated as REWORK. The downstream orchestration layer increments `rounds++` and feeds back empty feedback, wasting Vigil rounds; once `MAX_ROUNDS=3` is reached, `_block` incorrectly applies `needs-human`. The approach has two layers: on the reviewer side, put the verdict token first, prioritize parsing the first line, and retry parsing once, while distinguishing “the review itself is invalid” from “actual REWORK” in the decision result; the orchestration layer branches accordingly, so invalid reviews neither consume a round nor trigger iterations with nothing to act on, are bounded by a separate retry limit, and escalate honestly with the **actual** reason when that limit is reached. Only reviewer parsing and orchestration fault tolerance change; **the verdict criteria themselves do not change**.

## Motivation

The root cause lies in weaknesses on both the reviewer and orchestration sides (issue #63):

1. **The verdict token is easily truncated**: although `_RUBRIC_TAIL` says “the response must begin with VERDICT,” the model actually puts its argument first and leaves VERDICT until the end, so long responses are truncated before the token (even the summaries end mid-sentence).
2. **Parsing failure loses its semantic distinction**: when `_parse_verdict` cannot find a token, it returns None; `review()` normalizes this to UNPARSED under a “when in doubt, treat as failure” policy and counts it as non-PASS—a response containing nothing but praise is treated as REWORK.
3. **The incorrect needs-human trigger occurs in the orchestration layer** (non-PASS handling in messages.py): every non-PASS result triggers `rounds++` + `refine_rfc/iterate(decision.feedback)`. When the feedback is praise with no defect items, the coding agent has nothing to act on and makes changes to no effect; the next reviewer response is truncated again → the process can never converge to a parseable PASS → `MAX_ROUNDS=3` is reached → `_block` → `needs-human` is incorrectly applied (even though the content could have passed).

**Why change this**: this is a real false positive—praise is treated as rejection, and a person is needlessly pulled in. Two types of misclassification must be addressed together: ① invalid reviews should not consume the rounds budget for “actual REWORK”; ② empty/non-actionable feedback should not drive fruitless refine/iterate cycles. The fix requires both a source (the reviewer can truthfully report “this is an invalid review, not REWORK”) and an execution endpoint (the orchestration layer uses that distinction to decide whether to consume a round, whether to iterate, and how to conclude after the limit is reached). Neither is sufficient alone, so both Tasks are P0.

## Guide-level explanation

Think of the fix as “three lines of defense + one branch”:

- **Defense one (avoid truncation)**: the rubric strictly requires that **the first line must be `VERDICT: <token>`**, with the argument after the verdict—even if the response is truncated for length, what is lost is the end of the argument, not the verdict at the start.
- **Defense two (first-line parsing)**: `_parse_verdict` first looks for a `VERDICT:` token in the first line/paragraph, then falls back to matching the full text if the first paragraph yields nothing (backward compatibility with the old format). A first-line match is accepted immediately, preventing incidental occurrences of "REWORK" in the body (such as a quotation of someone else’s review) from contaminating the verdict.
- **Defense three (one parsing retry)**: run `backend.run` again for the reviewer whose result parsed as UNPARSED (only once). Truncation is random, so a rerun has a substantial chance of producing a parseable verdict.
- **Branching (orchestration layer)**: the reviewer classifies decisions into three categories—`passed` (all PASS), `actionable REWORK` (REWORK/RETHINK with a nonempty body and something to change), and `invalid review` (non-PASS solely because the verdict cannot be parsed/there are no actionable items). The orchestration layer continues to consume a round and feed back feedback for actual REWORK, while invalid reviews **consume no round and trigger no fruitless iteration**. A separate small retry limit bounds them; once it is reached, needs-human is applied with the actual reason, “reviewer output cannot be parsed.”

For users: someone watching the PR can immediately distinguish “⚠️ Invalid review (verdict cannot be parsed; reviewer output may have been truncated)” from “❌ REWORK” in the comments. What they see is “the review failed; investigate the reviewer/truncation,” rather than “the code was rejected for 3 rounds.”

## Reference-level explanation

The changes break down into 2 Tasks (mutually exclusive `files`, a single writer per Task):

1. **T1 reviewer side** (no dependencies, P0, source of the fix chain) — `openagents/reviewer.py` / `tests/test_reviewer.py`. All three lines of defense are implemented within the reviewer:
   - **Put the verdict first (strengthen the rubric)**: upgrade “begin with VERDICT” in `_RUBRIC_TAIL` to the strict requirement “the first line must be `VERDICT: <token>`, before any REASON/ISSUES/argument” (separate the verdict from its argument).
   - **First-line-priority parsing**: change the parsing order of `_parse_verdict(*, summary) -> str | None` to “first line/paragraph first → full-text `_VERDICT_RE` / bare-token fallback,” without changing the signature.
   - **One parsing retry**: during aggregation in `review(*, backend, work_dir, kind, pr_number, n) -> ReviewDecision`, run `backend.run` again for the reviewer whose result parsed as UNPARSED (only once); do not rerun PASS/REWORK/RETHINK.
   - **Three-way decision classification**: add a boolean field to `ReviewDecision` (tentatively named `actionable`, with a default that preserves backward compatibility for existing construction sites). Predicate: `actionable := (not passed) and ∃ verdict ∈ {REWORK, RETHINK}` with a corresponding nonempty `summary.strip()`; otherwise, if `not passed`, the review is invalid. Preserve the existing semantics of the three fields passed/feedback/verdicts; the change is purely additive.
   - **render_decision(*, decision, kind) -> str**: render “invalid review” with wording distinct from “REWORK,” without changing the signature.
2. **T2 orchestration layer** (depends on T1, P0) — `openagents/messages.py` / `tests/test_messages.py` / `openagents/state.py` / `tests/test_state.py`. The not-passed branching shared by both gates (the RFC review gate in `_process_rfc_review` and the code review gate in `_process_coding`, with structurally identical logic):
   ```
   if decision.passed:            # Unchanged (apply labels/implement or merge)
       ...
   elif decision.actionable:      # Actual REWORK — behavior unchanged byte for byte
       rounds = increment_rounds(...)
       if rounds >= MAX_ROUNDS: _block(gate)
       else: refine_rfc/iterate(detail=decision.feedback)
   else:                          # Invalid review (unparseable verdict / no actionable feedback)
       invalid = increment_review_invalid(...)      # Separate counter; do not touch rounds
       if invalid >= MAX_REVIEW_RETRIES:
           _block(gate, reason="review-unparseable") # Escalate honestly
       else:
           return {... "reason": "review-invalid"}   # Do not change rounds or refine; wait for the next review cycle
   ```
   Key invariants: invalid reviews **never** trigger `rounds++` and **never** trigger refine/iterate; preserve the actual REWORK path byte for byte (existing test cases serve as regression guardrails). Add the env knob `OPENAGENTS_MAX_REVIEW_RETRIES` (default 2; missing/invalid/<1 values fall back to the default), mirroring `_configured_max_rounds`. Add `increment_review_invalid(*, issue_number) -> int` to `State` (mirroring `increment_rounds`), and reset this counter to zero at the same points as the existing `reset_rounds`; add the corresponding field to `RunRecord` (default 0, backward compatible with old records). The counter is independent of `rounds` but shares its lifecycle (reset on implement / unblocking).

**End-to-end validation**: this group of changes is entirely at the unit level (no new standalone e2e script). Validation relies on both sets of unit tests passing—`tests/test_reviewer.py` (stub AgentBackend, covering truncated praise / actual REWORK / first-line priority / one parsing retry / all PASS / render wording) + `tests/test_messages.py` + `tests/test_state.py` (monkeypatch github.* + inject stub ReviewDecision, covering branching at both gates / counter resets / env fallback / zero regressions)—plus running `ruff check` + `ruff format --check` + `pytest`.

Dependency DAG: `T1 → T2` (T2’s input contract is the `ReviewDecision.actionable` field and “invalid review” semantics supplied by T1).

## Drawbacks

- `ReviewDecision` gains an `actionable` field, and `State`/`RunRecord` gain a review-invalid counter, adding a conceptual branching layer compared with “every non-PASS triggers rounds++.”
- Under extreme, persistent truncation, invalid reviews will still cause `_block` to apply needs-human after reaching their separate limit. This does not achieve “absolutely never block”; it uses “an actual reason + bounded cost” to avoid misrepresenting the failure as REWORK.

## Rationale and alternatives

- **Put the verdict first vs. hard-truncate backend output** (choose putting it first): hard-truncating `AgentResult.summary` to a fixed length may seem direct, but if VERDICT is at the end, it actually makes the token **more likely to be lost**, and requires changing the reviewer’s contract for backend output. Moving the verdict to the first line + first-line parsing fundamentally prevents truncation from affecting the verdict.
- **One parsing retry vs. no retry** (choose one retry): no retry is simplest, but a single truncated positive review would still become an “invalid review,” placing all fallback responsibility on the orchestration layer. One rerun has bounded cost (N defaults to 1) and can probabilistically resolve most random truncation; do not retry indefinitely—that belongs to the orchestration layer’s separate retry limit, keeping responsibilities layered.
- **Add an actionable field vs. reuse `feedback == ""`** (choose an explicit field): relying only on whether feedback is empty would conflate this with “REWORK but the reviewer did not write ISSUES” (that feedback is placeholder wording, nonempty but not actionable). An explicit boolean field has clear semantics and can be asserted in unit tests, while keeping the orchestration layer from having to parse verdicts again.
- **Separate retry counter vs. reuse MAX_ROUNDS as the fallback** (choose a separate counter): reusing rounds would minimize changes, but “invalid reviews also increment rounds and still trigger _block when the limit is reached” directly contradicts the issue’s expectation that they “consume no round,” and continues to conflate “the reviewer failed” with “the code should be rejected.” A separate counter gives each type of failure its own budget and its own honest escalation reason.
- **_block after reaching the limit vs. never block (retry only)** (choose _block): never blocking comes closest to “never misclassify praise,” but extreme, persistent truncation would cause endless polling and ongoing backend consumption. Giving invalid reviews a separate small limit and escalating to a person with the actual reason (reviewer output cannot be parsed) when it is reached both bounds cost and avoids misrepresenting the failure as REWORK.
- **Return an event this cycle and wait for the next cycle vs. immediately review again in the same cycle** (choose waiting for the next cycle): immediately rerunning review in the same cycle would increase the wall-clock duration of a single poll, and T1 already performs one parsing retry inside the reviewer (avoid duplicating work across layers). Polling is periodic, so waiting for the next cycle is natural, simple, and consistent with messages’ role as a “thin router.”
- **Leave verdict criteria/CI/the main internal logic of messages unchanged**, and only “split the existing not-passed path into two branches based on actionable”—minimize the blast radius (decoupling, principle 10).

## Prior art

“Separating the verdict from its rationale and placing the machine-parseable conclusion at the very beginning of the output” is a common robustness technique for LLM judges / structured output (to avoid losing the conclusion when long output is truncated); “distinguishing ‘failure of the judge itself’ from ‘a negative judgment’” is also standard practice in evaluation systems for distinguishing invalid from negative. This feature retains vigil-reviewer’s existing three-verdict PASS/REWORK/RETHINK rubric (RFC-0012) and `UNPARSED_VERDICT` (RFC-0018), adding only an observable “invalid review” classification on top, without introducing a new verdict system.

## Unresolved questions

- The threshold for “substantive ISSUES body text”: currently, a review is considered actionable if `summary.strip()` is nonempty. Whether a reviewer response with `VERDICT: REWORK` but an extremely short body / no ISSUES should also count as an “invalid review” is for a human to decide; this group will initially adopt the conservative interpretation that “REWORK/RETHINK with a verdict token is actionable,” leaving extreme cases of empty REWORK responses to be calibrated against data from actual runs.
- Whether the default value of `OPENAGENTS_MAX_REVIEW_RETRIES` (provisionally 2) is sufficient: 2 review retries are enough to obtain a parseable verdict in most cases; if actual runs show that this is too restrictive / too permissive, the default for this env variable can be adjusted. Initially, ship with 2 and calibrate against e2e data.
- The chosen way to close out repeated invalid reviews once the limit is reached is “use _block to mark needs-human (reviewer output cannot be parsed)”; if the team would prefer “never block, only retry reviews indefinitely,” it must accept the backend costs under extreme, persistent truncation—this group chooses the former (controlled costs + honest escalation), leaving this point for human confirmation.

## Future possibilities

- Include the “invalid review rate / reparsing hit rate” in observability metrics, and dynamically adjust the `MAX_REVIEW_RETRIES` default and rubric wording based on the actual distribution of truncation.
- If the backend later supports longer output or streaming verdicts, reliance on reparsing can be reduced further.
