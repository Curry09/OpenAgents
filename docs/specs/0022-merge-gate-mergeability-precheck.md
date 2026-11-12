---
number: "0022"
title: "Code gate mergeability precheck + poll error isolation + decision comment idempotency"
issue: 62
slug: merge-gate-mergeability-precheck
summary: "Three improvements to the code gate (merge gate): precheck PR mergeability before merging (skip unmergeable PRs immediately, without busy-looping or crashing poll), isolate individual PR errors during poll so they do not bring down the entire round, and make decision comments idempotent to avoid spamming duplicate PASS comments. Migrated from legacy metadata (which originally had no summary; filled in based on the title and tasks)."
tasks:
  - id: T1
    title: "github.mergeability: query PR mergeability (mergeable / mergeStateStatus)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: "Add a read-only query mergeability(*, pr_number) in github.py, running gh pr view <n> --json mergeable,mergeStateStatus through _gh_json and returning a frozen dataclass Mergeability{mergeable, merge_state_status}. Preserve the fields as GitHub's original uppercase strings without normalization; leave interpretation to T2. Mirror the structure of is_merged/is_closed/check_status, with keyword-only parameters and read-only behavior without side effects."
    acceptance: "Unit tests (monkeypatch _run_gh/_gh_json, hermetic) must assert that all three field combinations—DIRTY/CONFLICTING, CLEAN/MERGEABLE, and UNKNOWN/UNKNOWN—are returned faithfully and UNKNOWN does not raise an exception; _gh_json returning a non-dict or missing fields raises GithubError; and the arguments passed to gh are exactly pr view <n> --json mergeable,mergeStateStatus."
  - id: T2
    title: "Code gate mergeability precheck + per-PR error isolation in poll"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
    scope: "Make two changes in messages.py. (1) Insert a mergeability precheck at the very beginning of _process_coding: treat mergeStateStatus==DIRTY or mergeable==CONFLICTING as a genuine conflict, reuse rebase.CONFLICT_COMMENT to post one rebase prompt through identity.post_signed_comment, then call _block(gate=\"merge\") and return reason=\"unmergeable\"; for UNKNOWN, return None and check again in the next round; for CLEAN, continue through CI→reviewer→merge as usual. (2) In poll, wrap _process_run in try/except for each record; when an exception is caught, append an event with reason=\"error\" and continue, without changing state or bringing down the entire round."
    acceptance: "Unit tests (monkeypatch github/identity/orchestrator, hermetic) must assert: DIRTY/CONFLICTING→no calls to review_code/merge_pr, exactly 1 call to post_signed_comment with rebase.CONFLICT_COMMENT as the body, the record set to STATUS_BLOCKED+needs-human, and event reason==\"unmergeable\"; in the second round, that record returns None (regression check for exactly one comment); UNKNOWN triggers no review, no block, and no comment; CLEAN follows the existing path without regressions; when a record raises GithubError, poll does not raise, produces an event with reason==\"error\", and processes the remaining records as usual."
  - id: T3
    title: "Decision comment idempotency: do not repost the same decision every round"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: "Modify orchestrator._post_review_decision: before posting a comment, query existing comments using github.list_comments (read-only), identify decision comments by reviewer.render_decision's stable heading \"## Review gate verdict\" + kind, and deduplicate by decision outcome (PASS/non-PASS)—if the latest decision of the same kind has the same outcome as the current round, skip posting (record a line with _progress); if the outcome differs or there is no previous decision, post as usual. Any exception from list_comments or comparison must fall back to posting as usual (fail-open, best-effort bypass). Do not compare bodies byte for byte or modify reviewer/github."
    acceptance: "Unit tests (monkeypatch github.list_comments/identity.post_signed_comment/reviewer, hermetic) must assert: when a PASS decision of the same kind already exists, PASS in the current round does not call post_signed_comment again (skip identical outcomes); PASS↔non-PASS transitions post as usual; the first decision posts as usual when there is no previous decision; rfc and code decisions do not suppress each other (kind isolation); when list_comments raises an exception, it does not propagate, posting proceeds as the fallback, and ReviewDecision is unaffected."
---

# 0022 · Code gate mergeability precheck + poll error isolation + decision comment idempotency

> Historical labels are translated here for readability. See the [original text](../specs-zh-CN/0022-merge-gate-mergeability-precheck.md) for exact historical values.

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Harden the code gate (merge gate) in three places to address the problem exposed by issue #62: “an unmergeable PR makes poll repeatedly do useless work and crash, while posting the same decision as dozens of comments”: (1) precheck the PR’s actual mergeability with the base before running the reviewer; for a genuine conflict, transition once to blocked + needs-human + post one rebase prompt, instead of repeating useless work every round; (2) isolate errors in poll’s per-record processing, so that a single PR failure (including an exception from merge_pr) records just one error event and processing continues, without taking down the entire round; (3) make decision comments idempotent, so that the same decision outcome is not reposted every round. These three changes are divided into T1 (github leaf-level query) → T2 (code gate precheck + error isolation), and the orthogonal T3 (decision deduplication).

## Motivation

**Root-cause reproduction (issue #62 / PR #61, restated in full so readers do not need to consult another spec).** The current code gate, `messages._process_coding`, **does not check PR mergeability at all** before gate evaluation: as long as CI is green + the reviewer returns PASS, it calls `github.merge_pr` directly (messages.py:230; this call has **no try/except**). When `merge_pr` encounters a conflict, it raises `GithubError` through `_run_gh`, and the per-record loop in `poll()` (messages.py:117-125) does not catch exceptions either—so once any PR is unmergeable, **the entire poll round crashes immediately**. Because mergeability is not checked before gate evaluation, each interval reruns the reviewer (wasting another agent run) → returns PASS again → fails to merge again → crashes again.

Concrete example, PR #61: 14 `docs/specs/*/metadata.yaml` files had **content conflicts** (`mergeable=CONFLICTING`, `mergeStateStatus=DIRTY`) that automatic rebase could not resolve (`update-branch` is not a true rebase, and heal’s self-repair only re-renders OVERVIEW.md and cannot modify metadata). As a result, it received PASS 33 times, accumulated 33 identical `## Review gate decision ✅ PASS` comments, and could never be merged.

**Why this needs to change.** This vicious cycle has three independent causes, corresponding exactly to the three acceptance criteria in issue #62: no mergeability check before gate evaluation (the source of useless repeated work), no per-record exception handling in poll (the source of entire-round crashes), and unconditional decision comments every round (the source of comment spam). Each needs its own fix.

**How decision comment spam arose.** RFC-0018 made the reviewer gate post decisions back to the PR (restoring human visibility into the review gate), but posting is **unconditional every round**: as long as a record remains in the coding/rfc-review phase and the reviewer reruns each interval, another decision comment is posted. When a PR stays open for a long time and the decision does not change (not limited to conflict scenarios), this produces comment spam.

## Guide-level explanation

The three hardening changes are independent and do not depend on one another’s runtime state:

| Cause (issue #62) | Symptom | This feature’s remedy |
|------|------|------|
| No mergeability check before gate evaluation | A PR with genuine conflicts reruns the reviewer uselessly every round | T1 provides a read-only query + T2 short-circuits with a precheck and transitions to blocked once |
| No per-record exception handling in poll | One PR failure takes down the entire poll round | T2 adds error isolation around per-record processing |
| Decision comments are posted unconditionally every round | The same decision produces dozens of PASS comments | T3 deduplicates by decision outcome and skips identical outcomes |

For users: behavior is extended without changing the existing flow—a PR with genuine conflicts is marked `needs-human` once and receives one rebase prompt (instead of repeatedly doing useless work); other PRs continue through CI→reviewer→merge as usual. A single bad PR no longer crashes the entire poll round, and PR comments are no longer flooded with identical decisions. There are no public signature changes, and no configuration or command changes are required.

## Reference-level explanation

The changes are divided into 3 Tasks (see the DAG below; `files` are mutually exclusive, with a single writer for each Task):

1. **T1 github.mergeability (leaf-level capability, no dependencies)** — Add a read-only query in `openagents/github.py`, structurally **mirroring the existing `is_merged` (512) / `is_closed` (540) / `check_status` (492)**: run `gh pr view <n> --json mergeable,mergeStateStatus` through the sole centralized entry point, `_gh_json`, inheriting RFC-0010’s transient-error retries, with zero additional dependencies and zero new external data sources (principle 1, Occam). Carry the two raw fields in a small frozen dataclass (a lightweight structure modeled on `CheckStatus`), **not** a bare tuple—so callers read fields by name and avoid positional ambiguity. Keep the fields as GitHub’s original uppercase strings (`"DIRTY"` / `"CONFLICTING"` / `"UNKNOWN"`, etc.), with no normalization or Boolean determination in this layer (leave “which combinations count as unmergeable” to T2; principle 10, decoupling). Suggested signature:

   ```python
   @dataclass(frozen=True)
   class Mergeability:
       mergeable: str            # Original GitHub value: MERGEABLE / CONFLICTING / UNKNOWN
       merge_state_status: str   # Original GitHub value: CLEAN / DIRTY / BLOCKED / BEHIND / UNKNOWN / ...

   def mergeability(*, pr_number: int) -> Mergeability: ...
   ```

   All parameters are keyword-only (CLAUDE.md prohibits positional arguments). This is a pure read with no side effects and no state changes. Error handling follows the existing style: if `_gh_json` returns a non-dict or a field is missing → raise `GithubError` (identical to `is_merged`/`is_closed`). `UNKNOWN` (GitHub has not yet finished its asynchronous computation) is a **valid return value**; return it as-is, without treating it as an error in this layer. T2 decides whether to wait.

2. **T2 Code gate precheck + poll error isolation (depends on T1)** — Change two places in `openagents/messages.py`, without adding modules or changing the state machine definition (principle 1).
   - **(1) Mergeability precheck** goes at the **very beginning** of `_process_coding` (even before the CI check—a conflicting PR need not even wait for CI; the earlier the short-circuit, the greater the savings). Rule: `mergeStateStatus == "DIRTY"` or `mergeable == "CONFLICTING"` counts as a genuine conflict (both occur together in conflict scenarios; using OR is more robust). Conflict handling: first post one rebase prompt via `identity.post_signed_comment` (**reuse the wording in `rebase.CONFLICT_COMMENT`** to avoid scattered, diverging text; use `self._agent_id` for agent_id), then call the existing `self._block(record=record, gate="merge")` (set `STATUS_BLOCKED` + apply `needs-human`), and return an event with `{"reason": "unmergeable"}`. **“Exactly one comment” is guaranteed by the state machine’s short-circuit**: after `_block`, the record becomes `STATUS_BLOCKED`; on the next poll round, it follows the blocked branch in `_process_run` (messages.py:168)—if the needs-human label is still present, it skips processing with `return None` and never enters `_process_coding` again. Thus the prompt is naturally posted only once, with no additional deduplication state. For `UNKNOWN` (common immediately after a push): `return None`, with neither review nor blocking this round; check again at the next interval.
   - **(2) Per-record error isolation in poll** wraps `self._process_run(record=...)` in try/except (following the error-isolation style of RFC-0004 decision 8 / `rebase.rebase_open_prs` (rebase.py:55-76)): after catching an exception, append one `{"pr_number": ..., "reason": "error", "error": <summary>}` event and `continue`; never allow a single record’s exception to propagate and take down the entire round. **Do not change state** (the failure may be a transient gh error; the next round naturally retries, while the error event + watch logs provide observability). Wrap “the entire `_process_run`” rather than “only merge_pr” to cover all record-processing paths. Extend `_block`’s `gate` values with `"merge"` (currently `"rfc"`/`"code"`), used only for event annotation.

3. **T3 Decision comment idempotency (no dependencies, orthogonal to T2, can run in parallel)** — Change only `_post_review_decision` in `openagents/orchestrator.py` (the single centralized point that posts a decision as soon as it is produced, 239-253). Before posting a comment, call `github.list_comments` (read-only, already exists) to query existing comments. Identify decision comments by the stable heading `## Review gate verdict` (the legacy Chinese heading) produced by `reviewer.render_decision` + kind (rfc/code), and **deduplicate by decision outcome (PASS / non-PASS)**: compare the most recent decision outcome of the same kind with this round’s `decision.passed`; if they match, skip posting (record a line via `_progress`); if they differ (the outcome flips), or there is no previous decision, post as usual. **Do not compare the body byte for byte** (small changes in the rendered vote count, “X of N votes PASS,” or wording each round would make a byte-for-byte comparison report “different” and continue the spam). **Best effort; never block** (following RFC-0018 decision 2): if `list_comments` or any comparison raises an exception, catch it and **fall back to sending as usual** (fail-open), recording only a line via `_progress`; the review gate and downstream refine/iterate/merge must neither crash nor be blocked. This is orthogonal to T2: T2 uses the state machine short-circuit to stop the source of repeated work for conflicting PRs, while T3 compares comments to cover all other cases where “the decision is unchanged but is still reposted.” The files do not overlap, and the changes can be verified independently.

**End-to-end verification**: this group was migrated from legacy metadata and has no standalone e2e script; hermetic verification is handled by each Task’s `tests/test_github.py`, `tests/test_messages.py`, and `tests/test_orchestrator.py` (all use monkeypatch and never access real gh). Run repository-wide regression tests with `uv run pytest` (the same as CI).

Dependency DAG: `T1 → T2`; `T3` is independent (no dependencies on T1/T2, can run in parallel).

## Drawbacks

- The precheck criterion (`DIRTY` or `CONFLICTING` means conflict) is a fixed OR condition. If another `mergeStateStatus` needs to be blocked in the future, T2 will need adjustment (but the logic is centralized in one place, so the change is small).
- T3’s outcome-based deduplication means a version with “the same outcome but an updated feedback body” will not be reposted—people see a signal when “the outcome changed,” while details must be checked in the worktree/logs; this is acceptable.
- Error isolation only records events and does not escalate state. In theory, a PR that repeatedly encounters transient failures will be isolated every round without being proactively blocked; this group keeps things simple and does not introduce counter-based state escalation (see Rationale).

## Rationale and alternatives

- **T1 small dataclass vs bare tuple/dict**: choose dataclass. Tuple positions are error-prone, and dict keys become scattered; a dataclass has the same structure as `CheckStatus`, makes named-field access clearest for callers, and costs only one lightweight type (acceptable under principle 1).
- **T1 retrieve raw values only vs directly provide `is_unmergeable() -> bool` in this layer**: choose raw values only, leaving the Boolean determination to T2 and keeping the github layer a “thin gh wrapper with zero business logic” (principle 10); otherwise, threshold logic leaks into the leaf module, and future adjustments require changes in two places.
- **T1 query both fields once vs query them separately**: use one `--json mergeable,mergeStateStatus`, saving one gh round trip and obtaining both fields from the same snapshot to avoid reading inconsistent intermediate states.
- **T2 precheck at the very beginning of `_process_coding` vs after CI**: choose the beginning. Waiting for CI on a conflicting PR is pointless; short-circuiting earlier saves more work (even CI polling is avoided).
- **T2 error isolation scope: all of `_process_run` vs only `merge_pr`**: choose all of `_process_run`. The fundamental crash cause is “no exception handling per record”; wrapping at record scope covers all paths at once, follows rebase.py’s style of “one PR failure must not take down the entire round,” and automatically protects future gh calls.
- **T2 whether error isolation changes state (escalates to needs-human)**: choose no state change, only event recording. Failures are often transient (gh rate limits/network); blocking too readily would lock out PRs that could recover on their own. Preserve natural retries in the next round. Escalating after N accumulated rounds is a more proactive approach, but it requires counter state and adds entities; this group keeps things simple and does not implement it.
- **T2 reuse `rebase.CONFLICT_COMMENT` for the rebase prompt vs write new wording**: reuse it. The same “please rebase manually” message should have only one source of wording, avoiding separate text in RFC-0009 and this group that could diverge later.
- **T3 deduplicate by decision outcome vs compare the body byte for byte**: choose the outcome. Byte-for-byte comparison fails when vote counts/wording change slightly and allows spam to continue; deduplicating by PASS/non-PASS outcome addresses the actual intent of “do not repost the same decision.”
- **T3 deduplication in orchestrator vs reviewer**: put it in orchestrator. Posting is already centralized in `_post_review_decision`; reviewer remains a pure function of “input diff → output decision,” without depending on PR comment state (principle 10, decoupling).
- **T3 send by default vs skip by default when deduplication fails**: send by default (fail-open). An occasional extra comment is preferable to missing a decision because of a transient query problem and harming observability; this is consistent with best-effort side-channel semantics.


## Prior art

GitHub splits PR mergeability into two fields: `mergeable`（MERGEABLE / CONFLICTING / UNKNOWN）and `mergeStateStatus`（CLEAN / DIRTY / BLOCKED / BEHIND / DRAFT / HAS_HOOKS / UNKNOWN / UNSTABLE）(see the `gh pr view --json` documentation and the corresponding GitHub GraphQL enums). Conflicts appear as `mergeable=CONFLICTING` and `mergeStateStatus=DIRTY`; T1 retrieves these two fields faithfully. Error isolation—“a single PR failure does not bring down the entire round”—follows the existing pattern in this repository’s `rebase.rebase_open_prs` and RFC-0004 Decision 8; the best-effort side-channel semantics for posting the adjudication back follow RFC-0018.

## Unresolved questions

None. The decision thresholds, deduplication granularity, and error isolation granularity for all three hardening measures have been settled within this group.

## Future possibilities

- Error isolation could be extended into a proactive approach that “escalates to needs-human after failures accumulate over N rounds” (requires introducing counter state; currently YAGNI).
- Preflight checks could be extended to cover more `mergeStateStatus` values as GitHub’s fields evolve (for example, BEHIND automatically triggering a rebase).
