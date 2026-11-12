---
number: "0058"
title: "needs-human deadlock self-recovery: remove the label as soon as a human reply crosses the watermark, then reset and resume"
issue: 163
slug: needs-human-reply-unblock
e2e:
  intent: "Demonstrate that needs-human is no longer a one-way deadlock: after a parked subject receives an unsigned human comment beyond the watermark, the label is removed within one Vigil cycle, the subject is reset from TERMINAL to a state that can advance, and it can reach subsequent gates; when only our own signed comments are present, it remains TERMINAL (to prevent self-triggering)."
  method: "Form: backend-only orchestration (form=cli), with no navigable product-facing frontend; the self-check tool list contains no Playwright / Chrome DevTools\nMCP, so no browser e2e tests are specified. Instead, use offline deterministic testing (without calling a real LLM):\n1. Stub github: a PR labeled needs-human + a comment stream whose last entry is an **unsigned** human comment (beyond the\n   watermark of the signed comment explaining why the subject was parked); repeatedly drive single ticks with run_vigil(once=True) → assert that remove_label is called within that tick to remove needs-human,\n   and that _classify classifies the reset current state as non-TERMINAL (entering the reply/subsequent pipeline branch and able to reach subsequent gates).\n2. Control: another PR labeled needs-human, but with our own signed comment as the latest comment → assert that remove_label is not called and the state remains TERMINAL.\n3. Run the offline portion of scripts/e2e-spec-0058-needs-human-reply-unblock.sh with all checks passing: ruff check + ruff format --check +\n   the full pytest -q suite.\n"
summary: "Fix the one-way needs-human deadlock: in graph-driven Vigil (Spec-0065), `_classify` branch ① is `needs-human ∈ labels → TERMINAL → polling stops`, and the only way to clear it is for a human to **manually remove the label**; a human replying with a comment on the parked PR has no effect—because ① short-circuits before ② (latest comment is from a human → reply). This violates Decision 5 (the agent comments first, and the workflow resumes after human review) and the promise made to users in the comment explaining the park blocker (\"Once you clarify, the predicate automatically becomes active again\"), and is the same class of problem as #140 (stuck without self-recovery). Fix: insert **unblocking preprocessing** in the producer's per-subject evaluation `_consider` (vigil.py), after `_sense` and before `_classify`—when the subject has `needs-human` and **the latest comment does not bear our signature** (= someone has spoken after the comment explaining the park reason, crossing the watermark), remove the `needs-human` label and strip it from the facts already sensed for this tick, so `_classify` immediately reevaluates from the beginning in the same tick (②reply → ③…⑪ conservatively reenter the merge pipeline). In the new model, the watermark is no longer the `block_watermark` field in state, but the live fact already computed by `_sense`: \"Does the latest comment bear our signature?\" (the comment explaining the park reason must be signed and is always the last comment at the time of parking, so any newer **unsigned** human comment naturally crosses it); self-triggering is prevented by the signature check in `latest_comment_is_ours`, and the machine's own signed comments never unblock the subject. Rebuild, in the graph-driven stack using the single primitive \"remove label,\" the unblocking loop implemented in the old flat stack under Spec-0032 (#89) and lost during the consolidation and migration in Spec-0062/0064."
tasks:
  - id: T1
    title: "Producer unblocking preprocessing: needs-human + latest comment lacks our signature → remove label + strip it from facts, then reevaluate from the beginning and resume in this tick"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
    scope: "Add unblocking preprocessing `_unblock_if_replied` in `_consider` (openagents/recipes/vigil.py:1472), after `_sense` and before `_classify`: when `_LABEL_NEEDS_HUMAN in facts.labels` and `not facts.latest_comment_is_ours` (someone has spoken after the signed comment explaining the park reason, crossing the watermark), call `github.remove_label` (PR) / `github.issue_remove_label` (issue), according to the subject type, to remove needs-human, and use `dataclasses.replace` to strip that label from the facts already sensed for this tick, so `_classify` immediately reevaluates from the beginning against the current state with \"needs-human now absent\" (②reply→③…⑪ conservatively reenter the merge pipeline). Removing the label is the only state reset (no state fields are written); `_log` records which comment prompted unblocking. Keep `_classify` unchanged as a pure function (unblocking is a side effect, performed only on the producer side and outside `_classify`, structurally equivalent to the guardrail's one-attempt stamp). Protection against self-triggering is inherently built into the signature check in `latest_comment_is_ours`. # Spec-0058/T1."
    acceptance: "pytest tests/test_recipe_vigil.py passes. Assertions: (a) needs-human + latest comment is an unsigned human comment → `_unblock_if_replied` calls remove_label/issue_remove_label to remove needs-human, the returned facts.labels does not contain needs-human, and the subsequent `_classify` result is non-TERMINAL (reaching ACTIONABLE:reply or a subsequent pipeline branch); (b) needs-human + latest comment bears our signature → do not remove the label, leave facts unchanged, and `_classify` remains TERMINAL (self-trigger protection + idempotence: no unblocking if no one replies after parking); (c) no needs-human label → preprocessing passes the input through unchanged; (d) PR subjects use remove_label, and issue subjects use issue_remove_label; (e) after label removal, `_classify` can reach ②/subsequent gates in the same tick (reset to a state that can advance). ruff check + ruff format --check are clean."
  - id: T2
    title: "Unblocking-path tests + correction of the old \"needs-human is always TERMINAL\" assertion + offline e2e script"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tests/test_recipe_vigil.py
      - scripts/e2e-spec-0058-needs-human-reply-unblock.sh
    scope: "Add unblocking-path tests in tests/test_recipe_vigil.py (covering a–e of the T1 acceptance criteria); locate and correct/replace existing assertions that hard-code \"needs-human is always TERMINAL / always blocked after projection\" (the issue refers to the old-stack equivalent at test_recipe_vigil.py:450-455; in the graph-driven stack, these are cases asserting that a needs-human subject remains TERMINAL after `_consider`), updating them to reflect the new path \"human reply crosses the watermark → unblock → able to advance\" (retain \"no reply after parking / only comments bearing our signature → still TERMINAL\" as a control to prevent a regression that reverses the behavior). Add the offline e2e script scripts/e2e-spec-0058-needs-human-reply-unblock.sh: repeatedly drive single ticks with `run_vigil(once=True)`, feed in a PR labeled needs-human + an unsigned human comment that crosses the watermark, and assert that within one tick the label is removed and the subject is reset to a state that can advance (advance can reach subsequent gates); then feed in a control PR with only a comment bearing our signature and assert that it is not unblocked. The script's offline section runs ruff check + ruff format --check + pytest -q, all passing. # Spec-0058/T2."
    acceptance: "pytest tests/test_recipe_vigil.py passes all tests and includes at least one assertion that \"run=needs-human + an unsigned human comment crossing the watermark → on the next tick, status changes to a state that can advance and can reach subsequent gates,\" one that \"the machine's own signed comments do not trigger unblocking,\" and one corrected control asserting \"no reply after parking remains TERMINAL.\" bash scripts/e2e-spec-0058-needs-human-reply-unblock.sh exits with code 0 (offline and deterministic, without accessing a real LLM / no browser)."
---

# 0058 · Self-healing for needs-human deadlocks: remove the label, reset, and resume when a human reply crosses the watermark

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine rust-RFC sections. -->

## Summary

Complete the “human reply → automatically remove `needs-human` → revive predicates and resume” loop in graph-driven Vigil, eliminating the one-way `needs-human` deadlock.
When a subject labeled `needs-human` receives a **new human comment beyond the watermark that does not carry our signature**, the next Vigil tick (or even the current tick)
removes that label, resets the subject from TERMINAL to a state that can advance, and lets the merge pipeline (conflict→CI→e2e→review→merge) proceed normally.
The implementation touches only one production file, `openagents/recipes/vigil.py` (adding an unblocking preprocessing step), plus one test file, reusing the existing
`github.remove_label` / `github.issue_remove_label` and the signature fact `latest_comment_is_ours` already computed by `_sense`,
without adding state fields or modules (Principle 1, Occam).

## Motivation

**Current behavior (the Spec-0065 graph-driven stack).** Progress in Vigil is determined by a mechanical branch table in the pure function
`_classify` (`openagents/recipes/vigil.py:686`), whose first branch checks for terminal states:

```python
# vigil.py:734-737
if in_flight:
    return _Verdict(kind=_IN_FLIGHT)
if facts.merged or facts.closed or _LABEL_NEEDS_HUMAN in facts.labels:
    return _Verdict(kind=_TERMINAL)          # ← Branch ①: needs-human immediately makes it terminal
if not facts.latest_comment_is_ours:
    return _Verdict(kind=_ACTIONABLE, action=_ACT_REPLY)   # ← Branch ②: a human has something new to say
```

In the producer `_consider` (`vigil.py:1504`), `_TERMINAL` immediately causes `return 0`: nothing is queued, no agent is called, and polling
does no work at all for this subject. `needs-human` is a **first-class exit** for agents (the `_classify` docstring at `vigil.py:706` explicitly states that when an agent decides
“I have no way forward / a human needs to decide this,” it applies the label itself and leaves a reason, immediately entering TERMINAL, stopping polling, and making zero extra LLM calls). This is sound by design—
but its **only reversal path is for a human to remove the label manually**. The reason comment from `_park_needs_human` (`vigil.py:2886`) even instructs people to “clarify things, then
remove the label,” and its docstring (`vigil.py:2892`) considers only the case where “the human follows the instructions (**removes only the label, without commenting**), after which the predicates come back to life.”

**The gap.** Decision 5 (the design principles in CLAUDE.md) calls for “the agent comments first, then **the workflow resumes after human review**”; the comment explaining the blockage when parking
promises the user that “reply / clarify things and the workflow will resume automatically.” But the code has never delivered on this:

- Branch ① (needs-human→TERMINAL) **short-circuits before** branch ② (a human has something new to say→reply). When a human replies with a comment on a parked PR
  but does not manually remove the label, ① still returns TERMINAL and the subject remains motionless—**a human reply cannot revive it**.
- As a result, `needs-human` becomes a **one-way dead state**: it can be entered (the agent applies it proactively / the watchdog applies it as a fallback), but cannot be exited (unless a human manually changes the label
  or edits the state). Any PR/issue escalated to needs-human is **permanently deadlocked**, in the same category as #140 recorded in memory (a responsibility vacuum in git-in-harness,
  stuck with no self-healing): escalation = the endpoint, with no complete “human provides guidance → automatically resume” loop.

**The old stack had this; it was lost during consolidation.** Spec-0032 (issue #89, `e2e-spec-0032-needs-human-comment-unblock.sh`) implemented the read side of
“unblock when a human comment crosses the suspension watermark” in the old flat stack (`identity.new_human_comments`, `utils/identity.py:94`;
its docstring still says “created_at strictly greater than `since` (the suspension watermark block_watermark) … supports unblocking blocked subjects”). That read-side
function **still exists**, but during the successive migrations in Spec-0062 (moving the merge pipeline to the new stack) /0064 (consolidating recipes from 6→3) /0065 (rewriting vigil in place as graph-driven),
**the step that triggers unblocking was lost and never rebuilt**—the read side remains, but the write side (revoking terminal status) is gone. This spec addresses only this general deadlock,
rebuilding that step in the graph-driven stack with minimal primitives, without changing the agentic admission surface or the three guardrails: park / watchdog / attempt stamps.

(The specific cause of the triggering incident, PR #162 (Spec-0064, `block_gate=bad-ci-after-e2e`), has already been fixed separately through ruff `extend-exclude`; that was
the specific reason it got stuck **this time**. This spec addresses the general mechanism of “once stuck, it can never get out.” The two are orthogonal.)

## Guide-level explanation

In one sentence: **“A human has spoken on the parked subject” is itself the unblocking signal**; when Vigil sees it, it removes `needs-human` and lets the predicates naturally come back to life.

From the user's perspective, the completed loop is:

1. A PR is labeled `needs-human` (applied proactively by the agent or as a fallback by the watchdog), and park leaves a **signed** reason comment explaining the blockage.
2. The human reads it and **replies with a comment** on that PR (providing guidance / saying “continue” / correcting the requirements), **without having to remove the label manually**.
3. On the next Vigil tick (when `_consider` evaluates each subject), it discovers that this subject has `needs-human`, **and the latest comment does not carry our
   signature**—indicating that someone has spoken since park. Vigil treats this as an “unblocking signal”: it removes the `needs-human` label and strips it
   from the current state already read during this tick.
4. In the same tick, `_classify` immediately reevaluates the current state, which “no longer has needs-human”: branch ② (a human has something new to say) → the replier responds to the human's comment and advances
   the cursor; after the response, the latest comment carries our signature again → subsequent ticks enter the merge pipeline (③ dependencies → ⑤⑥ conflicts → ⑦⑧CI → ⑨e2e → ⑩⑪review/
   merge), **conservatively revalidating the PR from the beginning** before merging.

**In the graph-driven model, the watermark is a live fact, not a stored field.** The old stack stored “when it was suspended” in `state.block_watermark`,
then compared against it using `new_human_comments(since=block_watermark)`. The new stack's philosophy is “GitHub = domain truth” (Spec-0065): park's
reason comment **must be signed** (the `_park_needs_human` docstring at `vigil.py:2894` makes the signature discipline mandatory precisely to avoid treating its own words as a human's),
and it is the **last** comment at the moment of parking. Thus, “does the latest comment carry our signature” (`latest_comment_is_ours`, already computed by `_sense`,
`vigil.py:391/645`) is **exactly equivalent to** “has a human spoken beyond the watermark since park”—there is no need to store
a separate watermark or perform a second read. **Protection against self-triggering** is built in: `latest_comment_is_ours` is determined by the signature (`_latest_is_ours` →
`identity.parse_agent_id`); any signed comment subsequently posted by the machine itself sets `latest_comment_is_ours` back to True, so unblocking cannot
trigger itself (this also makes the rebuilt unblocking step idempotent: after the label is removed once, without a newer unsigned comment, the next tick does not remove it again).

## Reference-level explanation

**Change location: the producer's per-subject evaluation function `_consider` (`openagents/recipes/vigil.py:1472`).** This function was already “extracted from
`_producer_tick` solely to make the four-way dispatch unit-testable, with the error-isolating try boundary enclosing exactly one subject.” Placing the unblocking preprocessing
here naturally provides unit testability + per-subject error isolation.

Add an unblocking step with controlled side effects (proposed name: `_unblock_if_replied`), called after `_sense` and before `_classify`:

```text
def _consider(...):
    observed = _sense(config=config, subject=subject)
    observed = _unblock_if_replied(observed=observed, subject=subject, agent_id=agent_id)  # ← New
    verdict  = _classify(facts=observed.facts, in_flight=subject in in_flight)
    ...

def _unblock_if_replied(*, observed, subject, agent_id) -> _Observed:
    facts = observed.facts
    if _LABEL_NEEDS_HUMAN not in facts.labels:
        return observed                      # Not suspended → return unchanged
    if facts.latest_comment_is_ours:
        return observed                      # Latest carries our signature (including the reason just posted by park) → no human has crossed the watermark → do not unblock
    # Someone has spoken after park's reason comment (crossed the watermark) → remove needs-human and reevaluate from the beginning in this tick
    _remove_needs_human(subject=subject)     # Use github.remove_label for PRs / issue_remove_label for issues
    _log(message=f"⟳ {subject}: human reply crossed the watermark; removed {_LABEL_NEEDS_HUMAN}; reset and resuming")
    return replace(observed, facts=replace(facts, labels=facts.labels - {_LABEL_NEEDS_HUMAN}))
```

**Why “preprocess + strip from facts” instead of putting it inside `_classify`.** `_classify` must remain a **pure function** (the worker's
`_reconcile` calls it repeatedly at no cost; guardrail one's attempt-stamp preprocessing is likewise wrapped by the producer **outside `_classify`**, for the same reason;
see `vigil.py:1507`). Removing a label is IO with side effects and can only happen on the producer side. After removal, use `dataclasses.replace` to strip the label from
**the facts already read during this tick**, so `_classify` takes branch ②reply in the same tick against a current state that “no longer has needs-human” (resuming in the
same tick satisfies the acceptance criterion “automatically resume within one Vigil tick”), without a second `_sense`. (See Rationale for the alternative.)

**Why removing the label is sufficient, with no need to reset any state fields.** In the new stack, the `needs-human` **label itself** is the single source of truth for terminal status
(branch ① of `_classify` reads only `facts.labels`, not state.status). Remove the label = reset. The human–machine conversation remains in the GitHub comment stream
(the signed response from ②reply + the human's own comment), while a `_log` line records “which comment prompted unblocking.” Together these are where the `unblock_detail` audit information
requested by the issue resides—GitHub is the domain truth; no second copy is created in state.

**Conservative reentry rather than resuming from a checkpoint.** After removing the label, do not record a `block_gate` checkpoint or trust old evidence; let the predicates
**revalidate** the entire pipeline (conflict→CI→e2e→review→merge) starting at branch ② (the decision point in the issue's “Suggested fix” recommends the former: deterministic, with no need to trust old evidence).
This follows naturally with zero additional code—the `_classify` branch table already evaluates from the beginning.

**Existing capabilities relied on (all already exist; zero new read/write primitives during implementation):**

- `github.remove_label(pr_number, name)` (`utils/github.py:505`) / `github.issue_remove_label(number, name)`
  (`utils/github.py:535`)—the two label-removal primitives (`_split_subject` dispatches based on whether the subject is a PR or an issue).
- `facts.latest_comment_is_ours`, already computed by `_sense` (`vigil.py:391`, with signature detection via `_latest_is_ours` →
  `identity.parse_agent_id`)—watermark + protection against self-triggering in one.
- `_LABEL_NEEDS_HUMAN` (`vigil.py:221` = `github.BLOCKED_LABEL`)—the single source for the terminal-state label.

### DAG + file assignment

| Task | Description | depends-on | files (pairwise disjoint) |
| --- | --- | --- | --- |
| T1 | Add unblocking preprocessing `_unblock_if_replied` in `_consider`: needs-human + latest comment without our signature → remove the label + strip facts, so `_classify` reassesses from scratch and resumes processing within this tick | — | `openagents/recipes/vigil.py` |
| T2 | Tests for the unblocking path + correction of the old “needs-human is always TERMINAL” assertion + offline e2e script | T1 | `tests/test_recipe_vigil.py`, `scripts/e2e-spec-0058-needs-human-reply-unblock.sh` |

The T1 and T2 file sets are disjoint (production vs. tests/scripts), so there are no write conflicts in collaborative mode.

### e2e script path

`scripts/e2e-spec-0058-needs-human-reply-unblock.sh` (offline and deterministic; form=cli, with no product-facing frontend).

## Drawbacks

- **Coarser watermark granularity.** Replace the precise comparison “created_at > block_watermark” with “the latest comment does not bear our signature”: unblocking occurs whenever
  the last comment after parking is from a human, without distinguishing “whether this comment addresses the current blocker.” This cost is acceptable—normally, no one posts unrelated comments after parking;
  and unblocking merely makes the pipeline **validate everything again** (rerunning each gate reversibly and without side effects). The worst outcome of a false unblock is one wasted round of gate checks, far less severe than permanent deadlock.
- **Can an agent also “reply” to override the terminal state?** No—unblocking recognizes only comments **without our signature**; the machine’s own signed comments set `latest_comment_is_ours`
  back to True. The only risk is unsigned comments from **third-party bots** (CI bot, dependabot) triggering false unblocks; see Unresolved for mitigation.
- **One additional GitHub write (removing the label).** This occurs only when an actual unblock happens (rarely), and is isolated by the per-subject try in `_consider`, so a failure
  does not bring down the entire production cycle.

## Rationale and alternatives

**Selected approach: producer preprocessing removes the label + strips facts, using the live fact `latest_comment_is_ours` as the watermark.** Minimal change surface (one addition in one production
file), reuse of existing primitives, no new state / no new modules, no impact on `_classify` purity, and resumed processing within the same tick.

**Alternative A: revive `state.block_watermark` + `new_human_comments(since=watermark)` (copying the old flat stack).** This requires writing a watermark
when parking and comparing it when unblocking—**creating a second source of truth** (GitHub comment timestamps vs. a state field), conflicting with Spec-0065’s philosophy of “record decisions as labels,
read facts from their native source, do not duplicate them,” and adding another piece of persisted state to reconcile. Choosing the live fact `latest_comment_is_ours` avoids that bookkeeping.

**Alternative B: merge unblocking into branch ②, having `_classify` return ACTIONABLE:reply directly for needs-human + a new human message.** This violates
the pure-function contract of `_classify` (removing a label is a side effect), and the worker’s `_reconcile` also calls `_classify`, which would spread side effects into the worker.
Rejected—preprocessing must happen on the producer side, outside `_classify` (structurally equivalent to the attempt stamp in guardrail one).

**Alternative C: do not strip facts after unblocking; simply `return` and wait until the next tick to classify again.** This also works, but adds one interval (60s) of latency and fails to meet the immediacy of the acceptance criterion
“automatically resume within one Vigil cycle”; stripping facts allows processing to resume in the current cycle at almost zero additional cost.

**Alternative D: resume after unblocking from the checkpoint recorded in `block_gate` (trusting old evidence).** Already rejected at the issue’s decision point—prioritize determinism and conservatively
restart the entire pipeline from the beginning, without needing to trust that “the evidence from before parking still holds now.”

## Prior art

- **Spec-0032 / issue #89** (`e2e-spec-0032-needs-human-comment-unblock.sh`)—the original implementation in the old flat stack of “unblock when a human comment crosses the
  watermark,” which selectively revived the read-side `identity.new_human_comments`. This spec reconstructs it in the graph-driven stack (the read side still reuses its
  signature-filtering approach, but replaces the watermark with a live fact and changes the write side to label removal).
- **Spec-0031 / 0036** (unblock-agent-resolve / unblock-comment-read-and-reply)—adjacent links in the old stack’s unblocking chain.
- **Kubernetes level-triggered reconcile** ([k8s API conventions](https://github.com/kubernetes/community/blob/master/contributors/devel/sig-api-machinery/controllers.md))—
  Spec-0065’s Vigil model follows this approach: recompute from the source of truth every tick, without tracking edges. Unblocking is naturally expressed as “the current state shows someone has spoken and the label is still
  attached → reconcile by removing the label,” rather than as a one-time event callback.
- **memory: #140 git-in-harness responsibility gap**—the same kind of “stuck with no self-recovery”; this spec fills the self-recovery gap on the needs-human side.

## Unresolved questions

- **Should unsigned comments from third-party bots trigger unblocking?** In the current design, unsigned comments from CI bot / dependabot are treated as “a human has spoken”
  and cause false unblocks. Should the unblocking read side be narrowed to “comments from OWNER/MEMBER/COLLABORATOR only” (as with the admitter’s identity checks in Spec-0065)?
  Inclination: do not narrow it yet (a false unblock merely wastes one round of gate checks and is reversible); leave this for Future, and add identity filtering if bot noise appears in actual testing. **Pending confirmation with the user.**
- **What if a human deletes the comment explaining the parking reason** (so the latest comment in the comment stream no longer bears our signature)? Inclination: `latest_comment_is_ours` reads a human comment
  → unblock; this behavior is correct (a human has intervened), with no special case needed.

## Future possibilities

- **Identity filtering**: connect the unblocking read side to the admitter’s OWNER/MEMBER/COLLABORATOR checks to eliminate third-party bot noise entirely.
- **Include the unblocking reason in the review report**: structure “which comment prompted unblocking, who posted it, and when unblocking occurred” in the unified agent run report (Spec-0051),
  making unblocking events visible in the frontend’s results view, rather than only in `_log`.
- **Distinguish needs-human applied by the watchdog as a fallback from needs-human applied proactively by the agent** with a source marker, allowing different unblocking policies for the two (for example, allow automatic
  retries for fallback parking, while requiring human input for proactive parking).
