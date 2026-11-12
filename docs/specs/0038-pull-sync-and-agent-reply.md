---
number: "0038"
title: "Switch merge-conflict handling to pull-based synchronization + have the conflict-resolution agent reply to comments itself using a signed tool"
issue: 96
slug: pull-sync-and-agent-reply
summary: "Change Vigil merge/conflict handling from \"push-based fan-out + deterministic heal\" to \"Gate 2 pull-based synchronization + agent autonomy\"; have the conflict-resolution agent reply to human comments itself using the signed reply-comment tool (eliminating irrelevant replies at the root)"
tasks:
  - id: T1
    title: "Gate 2 pull-based synchronization + remove push fan-out"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
      - tests/test_messages_resolve.py
      - tests/test_messages_conflict_diag.py
      - tests/test_messages_merge_unblock.py
      - tests/test_messages_comment_reply.py
    scope: "Add a BEHIND branch to Gate 2 (_process_coding) → use update_branch to pull main (synced/behind-conflict); remove eager fan-out from Gate 1 (is_merged)/Gate 3 (reviewer PASS), leaving reconcile to only mark done + close the issue; remove framework-generated replies from the armed path, retaining only the clearing of unblock_detail after the run finishes."
    acceptance: "BEHIND → update_branch is called and returns synced, or behind-conflict if it encounters a conflict; merge events carry no synced and trigger no fan-out; successful conflict resolution in the armed state clears armed + detail without sending a reply on the agent's behalf; ruff + pytest all pass."
  - id: T2
    title: "Remove dead code + migrate CONFLICT_COMMENT"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/conflictdiag.py
      - tests/test_conflictdiag.py
      - scripts/e2e-spec-0034-conflict-diagnostics.sh
    scope: "Delete rebase.py (fan-out) and indexheal.py (deterministic heal) and their tests; move the CONFLICT_COMMENT constant from rebase to conflictdiag (single source of truth); change e2e-spec-0034 to exercise only the surviving conflictdiag pipeline."
    acceptance: "rebase/indexheal and their tests are deleted, with no remaining imports anywhere in the repository; conflictdiag.CONFLICT_COMMENT is the sole source, and format_blocker falls back to it when diagnostics are empty; e2e-spec-0034 exits with code 0 offline; ruff + pytest all pass."
  - id: T3
    title: "Have the conflict-resolution agent reply to comments itself using a signed tool"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/conflict.py
      - openagents/cli.py
      - openagents/orchestrator.py
      - tests/test_conflict.py
      - tests/test_conflict_guidance.py
      - tests/test_cli.py
      - scripts/e2e-spec-0036-unblock-comment-read-and-reply.sh
    scope: "Add the reply-comment CLI command (a thin wrapper around post_signed_comment that applies a signature); when guidance+pr_number are present, conflict._REPLY_TOOL_SECTION requires the agent to reply to comments itself using the tool (direct gh use is prohibited); pass pr_number through resolve_branch/make_resolver; remove the sync-prs command; align with main at the end of implement/iterate."
    acceptance: "reply-comment posts a comment signed with the current agent_id; _resolve_task includes reply-comment instructions when guidance+pr_number are present, and omits them when pr_number is missing; sync-prs is removed from the CLI; e2e-spec-0036 exits with code 0 offline; ruff + pytest all pass."
---

# 0038 · Switch merge conflict handling to pull-based synchronization + have the conflict resolution agent reply to comments using a signed tool

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is the group's nine-section rust-RFC overview. -->

## Summary

Refactor merge/conflict handling in Vigil (`messages.Messages.poll`) from
“**push-based fan-out + deterministic indexheal**” to
“**Gate 2 pull-based synchronization + agent agency**”: when a PR's turn comes for processing, if it is behind main (`BEHIND`),
use `github.update_branch` to merge the latest main into it and trigger CI to rerun; if it has conflicts (`DIRTY`), dispatch a coding agent to resolve them semantically.
Remove the eager fan-out that “pushes main to all other PRs immediately after a merge,” along with its supporting `rebase.py`/`indexheal.py`/manual `sync-prs`.
Also change **comment replies** after unblocking the merge gate from “the framework sends one of two hardcoded canned responses on the agent's behalf” to “the conflict resolution agent **personally** replies to human comments using the new CLI tool
`openagents reply-comment` (automatically signed to prevent self-triggering loops).”

## Motivation

**Background (restated here to make this spec self-contained)**: OpenAgents is an RFC/spec-driven multi-agent framework. Vigil,
`messages.Messages.poll`, periodically scans all open PRs and routes them by stage: first reconcile merged/closed PRs, then proceed through the rfc review gate
(draft PRs carry RFCs) or the code gate (`_process_coding`: first check mergeability, then wait for CI and run the reviewer). This document calls the mergeability
precheck “**Gate 2**.” In the original design, merging a PR into main is a signal that triggers **fan-out** (`rebase.rebase_open_prs`):
run `github.update_branch` for every other open PR, with layered fallback on conflicts from `indexheal` (deterministically re-render `OVERVIEW.md`) →
`conflict.resolve` (agent-based semantic conflict resolution) → a comment.

**Three problems**:

1. **The two fan-out call sites have asymmetric capabilities**: the `is_merged` reconcile path injects heal/resolve/diagnose, whereas
   the site where the framework itself merges after reviewer PASS **only injects diagnose**—so conflicts such as those in `OVERVIEW.md`, which **could have healed deterministically**,
   are immediately escalated to `needs-human` if they emerge through the latter gate. The fate of the same conflict depends on which fan-out entry point
   it comes through, effectively a coin flip (this is precisely the asymmetry reported in issue #96 / PR #99).
2. **Gate 2 only “looks”; it does not “pull”**: the precheck only reads `mergeability` and never merges main in—so a PR that is behind but has no conflicts
   never undergoes integration testing again, and under “require branches up to date,” it may never be mergeable.
3. **Replies after unblocking the merge gate are irrelevant to the comment**: when someone comments on a PR suspended because of merge conflicts, the framework feeds the comment
   to the conflict resolver as guidance, but the resolver only returns a bool. As a result, the reply is always one of two hardcoded canned responses (“Resolved conflicts and pushed” /
   “Could not resolve automatically this round”), regardless of what the person said.

**Why make this change**: consolidate “who integrates/resolves conflicts” from “push to everyone at merge time” into “each PR pulls at Gate 2 when its turn comes.”
This leaves just one processing point with inherently symmetric capabilities, structurally eliminating the asymmetry in issue #96. Letting the agent personally send replies through a signed tool
both reuses the proven “agent speaks for itself” pattern from the rfc/code gates and uses signatures to prevent self-triggering loops.

## Guide-level explanation

The new flow from a PR's perspective:

- **I am behind main (BEHIND)**: when my turn comes, Gate 2 calls `update_branch` to merge the latest main into me, and my CI reruns on the “integrated
  code.” No review takes place this round; the next round proceeds from the integrated state.
- **I conflict with main (DIRTY)**: Gate 2 dispatches a conflict resolution agent to run `git merge` + semantic conflict resolution + self-testing
  + push in a temporary worktree. For generated indexes such as `docs/specs/OVERVIEW.md`, the agent is instructed to re-render using `spec render` instead of merging manually.
- **Someone merged another PR**: no one proactively pushes main to me anymore; I pull when my own turn comes (pull replaces push).
- **A human comments on this suspended PR of mine**: the comment is fed to the conflict resolution agent as guidance; after resolving the conflicts, the agent **itself** uses
  `openagents reply-comment --pr <me> --body "..."` to reply to that comment—the command automatically applies an OpenAgents signature, so my
  reply will not be treated as a new human comment by the next poll (no self-triggering loop). The framework no longer sends canned replies on the agent's behalf.

Human-visible changes: remove the `openagents sync-prs` command (redundant after switching to pull); add the `openagents reply-comment` command
(mainly for coding agents).

## Reference-level explanation

**Core changes**:

- **Add a `BEHIND` branch to Gate 2 (`_process_coding`)**: `merge_state_status == "BEHIND"` → `try
  github.update_branch(pr_number)`; return `synced` on success, or `behind-conflict` on a conflict (`GithubError`)
  (on the next round, mergeability will be `DIRTY`, entering the existing agent conflict resolution path—there is only one conflict resolution brain for the hard work).
- **Remove eager fan-out from Gate 1 (`is_merged`)/Gate 3 (reviewer PASS)**: remove both `rebase.rebase_open_prs` calls;
  reconcile retains only “mark done + close issue,” and merged events no longer include `synced`.
- **Delete dead code**: `openagents/rebase.py` (fan-out), `openagents/indexheal.py` (deterministic healing), `_make_heal`,
  and the CLI `sync-prs` command; move the `rebase.CONFLICT_COMMENT` constant to `conflictdiag.CONFLICT_COMMENT` (single source).
- **Make comment replies tool-based**: add the CLI command `reply-comment` (a thin wrapper around `identity.post_signed_comment`, signing with this instance's agent_id);
  append `conflict._REPLY_TOOL_SECTION` to the conflict resolution task when both guidance + pr_number are available, instructing the agent:
  “only unsigned comments are human comments; reply only to relevant ones; the tool is mandatory; direct gh use is forbidden”; pass
  `pr_number` through `resolve_branch`/`make_resolver`; remove `_reply_resolve_outcome`, which sends replies on the agent's behalf, from the messages armed path, retaining only the clearing of `unblock_detail` after execution.

**Task DAG + file allocation** (the three Tasks own non-overlapping files; all are done):

| Task | owns files | Dependencies |
|---|---|---|
| T1 Gate 2 pull-based synchronization + remove fan-out | `openagents/messages.py` + `tests/test_messages*.py` | — |
| T2 Delete dead code + migrate constant | `openagents/conflictdiag.py`, `tests/test_conflictdiag.py`, `scripts/e2e-spec-0034-conflict-diagnostics.sh` | — |
| T3 Conflict resolution agent replies to comments using a signed tool | `openagents/{conflict,cli,orchestrator}.py`, `tests/test_{conflict,conflict_guidance,cli}.py`, `scripts/e2e-spec-0036-...sh` | — |

**e2e scripts**: `bash scripts/e2e-spec-0034-conflict-diagnostics.sh`, `bash
scripts/e2e-spec-0036-unblock-comment-read-and-reply.sh` (both offline; no network/gh/LLM access).

## Drawbacks

- **Deterministic indexheal is removed**: conflicts in `OVERVIEW.md` were previously handled by deterministic code that re-rendered it (with almost no errors); they are now handled by “an LLM instructed to run
  `spec render`”—theoretically less reliable than deterministic code (the cost of trading determinism for agency).
- **The reply tool relies on prompt discipline**: “the tool is mandatory; direct gh use is forbidden” is a prompt constraint, not enforced by a sandbox; if the agent stubbornly uses a direct,
  unsigned `gh pr comment`, self-triggering loops will return (this group explicitly chooses **not to add** an author-based fallback).
- **Pull converges more slowly than push**: integration changes from “push concurrently to everyone the instant a merge happens” to “each PR pulls once when its turn comes.”

## Rationale and alternatives

- **Alternative A: only restore symmetry (the approach in PR #99)**—add heal/resolve back to the reviewer-PASS fan-out site to make the two fan-out entry points
  symmetric. Rejected: this fixes only half the problem (conflicts first encountered at Gate 2 still do not attempt healing) and retains the complexity of the entire push-based fan-out system. This group goes further: remove fan-out
  and consolidate processing at a single point in Gate 2.
- **Alternative B: retain framework-sent replies and pass the agent's summary through as the reply**—a small change, but the agent's response must pass through the framework,
  and summary must be added to the return type. Rejected: not sufficiently agent-native, and reply content remains constrained by the framework's template structure. This group lets
  the agent send replies personally using a tool, which is more direct.
- **Alternative C: add an “author-based fallback” for comment replies** (change poll's identification of “self-authored” comments from checking signatures to checking authors as well)—more robust (even direct gh use would not
  cause loops). This group explicitly chooses **not to implement it for now**, recording it under Future possibilities.

## Prior art

- issue #48 `indexheal` (deterministic OVERVIEW re-rendering), Spec-0028 `conflict.resolve` (agent-based semantic conflict resolution),
  Spec-0034 `conflictdiag` (conflict notifications with diagnostics)—this group removes the former and reuses the mechanisms of the latter two.
- issue #96 / PR #99 “asymmetric capabilities at the two fan-out call sites”—this group addresses the root cause (removes fan-out) rather than restoring symmetry.
- The `_HUMAN_UNBLOCK_TASK` + `replynote` “agent speaks for itself” pattern in the rfc/code gates—this group adds equivalent capabilities to the merge gate
  (using a signed CLI tool instead).
- RFC-0019 self-triggering loop prevention / Spec-0032 “read only human comments newer than the watermark and without signatures”—this group's comment reply tool applies signatures precisely
  to rely on this signature filtering to prevent self-triggering.

## Unresolved questions

- **livelock**: when main changes faster than “one PR synchronizes + runs CI + undergoes review + merges,” Gate 2 pulls may never catch up. Whether to introduce
  a merge queue (serializing merges) is left for later.
- **Reply reliability**: whether the agent consistently calls `reply-comment` (instead of forgetting or bypassing it) requires observation in a real environment.

## Future possibilities

- Author-based fallback (Alternative C): extend poll's identification of “self-authored comments” from signatures to author identity, enforcing protection against self-triggering loops caused by direct gh use.
- Extend “reply tool + read the entire comment section and select what to reply to” to the rfc/code gates, unifying how agents reply across all gates.
- merge queue: serialize merges to eliminate livelock at its root.
