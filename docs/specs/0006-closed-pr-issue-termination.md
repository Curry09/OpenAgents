---
number: "0006"
title: "Vigil recognizes PR/issue closure as a termination signal"
issue: 0
slug: closed-pr-issue-termination
summary: "Vigil must know when to stop: when a PR or issue is closed, recognize it as a termination signal and stop trying to solve it, avoiding wasted cycles on work that has already been abandoned."
tasks:
  - id: T1
    title: "Recognize a closed PR as a termination signal"
    status: done
    priority: P1
    tags:
      - protocol
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - openagents/state.py
      - openagents/messages.py
      - tests/test_github.py
      - tests/test_messages.py
    scope: "Add is_closed(*, pr_number) to github.py, reading gh pr view --json state to determine whether state == CLOSED (symmetric with is_merged: GitHub's three PR states, OPEN/CLOSED/MERGED, are mutually exclusive; a merged PR has state MERGED and does not count as closed); add the STATUS_CLOSED = \"closed\" constant to state.py without including it in _OPEN_STATUSES; insert a closed branch in messages._process_run after the merged check and before stage routing: if matched, set STATUS_CLOSED and return reason=\"closed\", without triggering any orchestration actions."
    acceptance: "After polling a run with state=CLOSED, the rfc-approved label, and local state rfc-review, implement is not called, the state is set to closed, and the event has reason=\"closed\"; runs in the closed state are skipped in subsequent polls (they are not in _OPEN_STATUSES); merged still takes precedence over closed and stage routing, with no regressions in existing tests; ruff check / ruff format --check / pytest all pass."
---

# 0006 · Vigil recognizes PR/issue closure as a termination signal

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Teach Vigil (the vigil/poll loop) when to stop: when someone explicitly closes a PR (its GitHub state becomes `CLOSED` rather than `MERGED`), recognize this as a **termination signal** symmetric with “merged,” set the run to the new terminal status `STATUS_CLOSED`, and skip it in subsequent rounds. Stop trying to solve it, avoiding wasted cycles on work someone has already abandoned.

## Motivation

Vigil is a continuous polling (poll) loop: it traverses all local run records and advances runs that are still in an “open” status (`_OPEN_STATUSES`: rfc-review / pr-open / iterating) according to their stage (drafting an RFC, implementing code, iterating on reviews, etc.).

Before this feature, the loop recognized only one termination signal—**merged**: once `_process_run` discovered that a PR had been merged, it set `STATUS_DONE` and skipped it. But the equally explicit **“stop working on this”** signal of “someone explicitly closes a PR without merging it” went unrecognized. Consequently, when someone closed a PR after deciding to “abandon this approach,” the corresponding run remained in an open status such as rfc-review / pr-open, and Vigil continued trying to solve it according to its stage—repeatedly drafting, implementing, and reviewing work someone had already decided against. This wastes agent compute and violates the design goal of “humans provide high-level oversight; agents do not spin their wheels.”

Vigil needs to be as sensitive to “closed” as it is to “merged”: closure means termination; stop immediately.

## Guide-level explanation

A GitHub PR's `state` has three mutually exclusive values: `OPEN`, `CLOSED`, and `MERGED`. A merged PR has state `MERGED` (it does not count as `CLOSED`), so “closed without merging” can be uniquely and cleanly identified by `state == "CLOSED"`, naturally symmetric with and non-overlapping with the existing “merged” check (`MERGED`).

The behavioral change: from now on, whenever someone clicks “Close pull request” on GitHub (without merging), the next poll round will mark that run as `closed` and stop all orchestration actions for it; it will also no longer count toward “work that is still open.” This gives people a lightweight “stop” switch—close the PR, and the agent stops—without requiring a separate mechanism to terminate an abandoned line of problem-solving.

## Reference-level explanation

A single Task (T1, no dependencies), with three coordinated changes forming a “detection → terminal-status constant → routing” chain:

1. **Detection layer, `github.py`** — Add `is_closed(*, pr_number)`: run `gh pr view <n> --json state` through the single centralized entry point `_gh_json` (with built-in retries for transient failures), and return `str(state).upper() == "CLOSED"`. Its structure mirrors the existing `is_merged`; GitHub's three mutually exclusive states ensure that a merged PR (state=MERGED) cannot be misclassified as closed.
2. **State layer, `state.py`** — Add the constant `STATUS_CLOSED = "closed"`, representing the terminal status “PR closed without merging” (explicitly abandoned by a person). It is **deliberately excluded** from `messages._OPEN_STATUSES`, so poll automatically skips it.
3. **Routing layer, `messages.py` `_process_run`** — Insert a closed branch after the “merged check” and before “stage routing”:
   - Deliberately keep `merged` ahead of `closed`: if a PR has been merged, follow merge semantics and use `STATUS_DONE` (merged is the stronger successful terminal status); only “closed without merging” reaches closed.
   - On a closed match: call `state.update_status(... status=STATUS_CLOSED)`, return the event `{"pr_number": ..., "reason": "closed"}`, and **trigger no orchestration actions** (no implement, no rebase, no review).
   - Because `STATUS_CLOSED ∉ _OPEN_STATUSES`, the run is skipped directly in subsequent poll rounds and no longer spins its wheels.

**Task breakdown and dependency DAG**: T1 only, with no dependencies (`depends-on: []`); all three changes belong to a single writer in one PR and do not form an internal DAG.

**End-to-end validation**: This feature has no standalone `scripts/*.sh` e2e script; validation uses the repository's standard gates—all checks pass for `ruff check` / `ruff format --check`, and all `pytest` tests pass (including stub assertions for `is_closed` in `tests/test_github.py` and assertions for closed-branch routing and poll skipping in `tests/test_messages.py`).

## Drawbacks

- Terminal statuses expand from “done only” to “done / closed,” adding one value to the state machine. The poll skip logic must exclude both `STATUS_BLOCKED` and the new closed status (already handled uniformly by “excluding it from `_OPEN_STATUSES`,” without adding branch complexity).
- “Someone closes a PR” is an irreversible stop: if someone closes it by mistake, they must reopen the PR for Vigil to take over again (after GitHub reopens it, state returns to OPEN, and the next poll round naturally resumes).

## Rationale and alternatives

- **Why use `state == "CLOSED"` instead of an additional label**: GitHub's native three-state model already expresses “closed without merging” precisely. Reusing the state field requires no new labeling convention—Occam's razor: introduce no additional entities.
- **Why merged takes precedence over closed**: Merging is the stronger successful terminal status. The two are theoretically mutually exclusive (MERGED ≠ CLOSED), but keeping merged first leaves the existing merge semantics (setting done, closing the issue, fanning out rebase operations) completely unaffected, with zero regressions.
- **Alternative: uniformly filter out closed runs at the poll entry point**. Rejected—detection requires calling `gh` to obtain state. Placing it inside `_process_run` alongside the merged check is the most natural fit and also produces a `reason="closed"` event for observability; placing it at the entry point would instead require a duplicate remote query.
- **Alternative: treat closed as done as well**. Rejected—done means “the work has been successfully delivered” and triggers actions such as closing the issue / rebasing the remaining PRs; closed means “abandoned” and must be a pure terminal status that **triggers no orchestration actions**, hence the need for a separate constant.

## Prior art

This feature is a mirror extension of the existing “merged means termination” recognition (`is_merged` + `STATUS_DONE`) in the same repository, with complete symmetry. It corresponds to GitHub's three-state PR model (OPEN/CLOSED/MERGED are mutually exclusive)—“closed without merging” is a standard signal to “abandon this change” in mainstream CI/automation.

## Unresolved questions

None. The detection criterion (state==CLOSED), terminal-status constant, and routing order (merged first) have all been settled within this group.

## Future possibilities

- Direct closure of an issue (before a PR has been opened) could likewise be recognized as a termination signal, reusing the same “closure means stop” semantics.
- The closed terminal status could appear in a separate “Abandoned” category in the frontend results view, displayed distinctly from done / blocked.
</content>
</invoke>
