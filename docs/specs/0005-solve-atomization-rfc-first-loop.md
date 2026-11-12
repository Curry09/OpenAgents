---
number: "0005"
title: "Split solve into atomic operations + RFC-first review loop"
issue: 0
slug: solve-atomization-rfc-first-loop
summary: "Split the original monolithic solve into four atomic operations and introduce an RFC-first review loop (write the RFC before writing code). Extract a workspace module, extend github/state, filter out self-comments by phase in messages, and replace solve in the CLI with 4 subcommands."
tasks:
  - id: T1
    title: "Extract the workspace module"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/workspace.py
      - tests/test_workspace.py
    scope: "Create a Workspace class and move the orchestrator's existing worktree/git logic (_prepare_worktree / _ensure_worktree / _commit_and_push / _remote_branch_exists / _worktree_path / _git) into it unchanged, exposing prepare / ensure / commit_and_push / remote_branch_exists. Pure git, with no GitHub / backend / state dependencies. This subtask only adds files and does not modify the orchestrator (T2 handles that)."
    acceptance: "Unit tests cover prepare (fetch + idempotent cleanup + worktree add), ensure (reuse if present / recreate if missing), and commit_and_push (skip commit when there are no changes but still push); ruff passes; comments reference RFC-0005."
  - id: T2
    title: "Slim down the orchestrator to four atomic operations"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on:
      - T1
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: "Delete solve / _fresh_solve / _resume and the private git/worktree methods that have been moved out; instead, hold a Workspace instance and implement start_rfc / refine_rfc / implement (retain the existing iterate, but route it through Workspace). The backend task for start_rfc must instruct it to follow the rfc-driven skill to draft the RFC (including obtaining an RFC number). Retain _pr_body / _open_or_reuse_pr as needed."
    acceptance: "Unit tests use a fake backend / monkeypatch github and inject a fake Workspace to cover the sequence “ensure workspace → run → commit and push → GitHub action → state transition” for all four operations; ruff passes; comments reference RFC-0005."
  - id: T3
    title: "Extend github (draft / mark_ready / has_label / current_login)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: "Add draft: bool = False to create_pr (pass it through to gh pr create --draft); add mark_ready (gh pr ready), has_label (gh pr view --json labels), and current_login (gh api user --jq .login)."
    acceptance: "Unit tests monkeypatch the gh subprocess and cover draft passthrough, mark_ready, has_label (match/no match), and current_login parsing; existing create_pr calls (without draft) retain their behavior; ruff passes."
  - id: T4
    title: "Extend state (rfc-review status)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
    scope: "Add the constant STATUS_RFC_REVIEW = \"rfc-review\" and include it among the valid statuses; do not change existing method signatures (start_rfc reuses record_run + update_status). Update the status enumeration description in the RunRecord docstring."
    acceptance: "Unit tests verify persistence and reading of update_status(status=rfc-review); existing tests show no regressions; ruff passes."
  - id: T5
    title: "Phase-based messages + self-comment filtering"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on:
      - T2
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
    scope: "Route _process_run by phase according to the run status (see the interface contract); add APPROVAL_LABEL; comment processing takes the “latest comment after the cursor” (regardless of author); in the rfc-review phase, call implement if the label is present; otherwise, call refine_rfc for the latest comment and advance the cursor past the latest comment on the PR after the reply is posted (consuming the agent's own reply)."
    acceptance: "Unit tests cover: rfc-review + label → implement; rfc-review + new comment → refine_rfc and advance the cursor to the latest PR comment; cursor already past the latest comment → no repeated triggering (prevent self-loops); coding phase CI/comment → iterate; merged → done; ruff passes."
  - id: T6
    title: "Revise cli (remove solve, add 4 subcommands) + e2e"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - protocol
      - dx
    depends-on:
      - T2
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
      - scripts/e2e-rfc-0005-rfc-first.sh
    scope: "Delete the solve subcommand and _cmd_solve; add the rfc / refine-rfc / implement / iterate subcommands and their handler functions (refine-rfc/iterate use the latest human comment as detail); update the _dispatch routing table. Add the end-to-end script scripts/e2e-rfc-0005-rfc-first.sh (a demonstration of drafting an RFC → simulating a comment → refine → applying a label → implement → poll transitioning to done)."
    acceptance: "Unit tests stub the factory to verify that the four subcommands dispatch to their corresponding operations and that solve has been removed; the e2e script is readable and includes all steps; ruff passes."
---

# 0005 · Splitting solve into atomic operations + an RFC-first review loop

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Split the formerly monolithic `solve` operation into four atomic operations (`start_rfc` / `refine_rfc` / `implement` / `iterate`) and introduce an **RFC-first review loop**: the agent first drafts an RFC (a draft PR), humans comment on the PR or apply an approval label, and the agent uses that feedback to refine the RFC or move on to writing code. Supporting changes extract a `workspace` module (containing pure git/worktree logic), extend `github` (draft / mark_ready / has_label / current_login) and `state` (adding the `rfc-review` status), route message processing by run phase and filter out the agent's own replies, and replace the single `solve` CLI subcommand with four atomic subcommands.

## Motivation

The old `solve` was one large operation encompassing “claim an issue → create a worktree → draft changes → open a PR → iterate.” Git/worktree logic, GitHub actions, state transitions, and message routing were all coupled in the orchestrator, making them difficult to test independently and reuse. It also lacked a step for “aligning on the design before writing code”—the agent started modifying code immediately, leaving humans no opportunity to intervene before the code stage.

A core principle of OpenAgents is that agents align through a GitHub-like PR + comment mechanism, and that **every change updates the RFC before updating the code** (principle 4). Putting this loop into practice requires: (1) splitting `solve` into independently schedulable atomic operations so that “draft the RFC” and “write the implementation” become two distinct phases; (2) decoupling pure git logic from the orchestrator (principle 10) to slim it down and enable independent testing; and (3) enabling the message layer to recognize “whether the current phase is rfc-review or coding” and route accordingly, while preventing agents from treating their own replies as new input and entering a self-loop.

## Guide-level explanation

The new workflow operates on one issue at a time and progresses through these phases:

| Phase | Trigger | Agent action | Resulting status |
|------|------|------|------|
| Drafting | `openagents rfc` | Create a worktree, draft an RFC following the rfc-driven skill (including assigning a number), and open a **draft PR** | `rfc-review` |
| Review | The PR receives a new human comment | `refine_rfc`: revise the RFC based on the comment, post a reply, and advance the cursor | `rfc-review` |
| Approval | An approval label is applied to the PR | `implement`: mark_ready the draft PR and start writing the implementation | coding |
| Iteration | CI feedback / comments | `iterate`: modify the code based on feedback | coding |
| Merge | PR merged | Wrap up | done |

For users: `solve` no longer exists. It is replaced by four atomic subcommands, `rfc` / `refine-rfc` / `implement` / `iterate`, with `refine-rfc` / `iterate` taking the latest human comment on the PR as detail. The message polling layer (`messages`) automatically routes PR events to the corresponding atomic operation based on the run's current status; humans only need to comment on the PR or apply labels.

## Reference-level explanation

The changes are divided into 6 Tasks (`files` are mutually exclusive, with a single writer for each Task):

1. **T1 Extract the workspace module** — Create a `Workspace` class and move the orchestrator's existing private worktree/git logic (`_prepare_worktree` / `_ensure_worktree` / `_commit_and_push` / `_remote_branch_exists` / `_worktree_path` / `_git`) into it unchanged, exposing `prepare` / `ensure` / `commit_and_push` / `remote_branch_exists`. Pure git, with no GitHub / backend / state dependencies; this Task only adds files and does not modify the orchestrator.
2. **T2 Slim down the orchestrator** (depends on T1, T3, T4) — Remove `solve` / `_fresh_solve` / `_resume` and the private git/worktree methods that have been moved out; instead, hold a `Workspace` and implement the four atomic operations `start_rfc` / `refine_rfc` / `implement` (retain the existing `iterate`, changing it to use `Workspace`). The backend task for `start_rfc` instructs it to follow the rfc-driven skill to draft an RFC (including assigning a number); retain `_pr_body` / `_open_or_reuse_pr` as needed.
3. **T3 Extend github** — Add `draft: bool = False` to `create_pr` (passed through to `gh pr create --draft`); add `mark_ready` (`gh pr ready`), `has_label` (`gh pr view --json labels`), and `current_login` (`gh api user --jq .login`). These are the GitHub primitives required by the RFC-first loop: a draft PR represents “RFC under review,” mark_ready represents “transition to implementation,” has_label identifies approval, and current_login filters out self-comments.
4. **T4 Extend state** — Add the constant `STATUS_RFC_REVIEW = "rfc-review"` and include it in the set of valid statuses so that a run can represent the “RFC under review” phase; do not change existing method signatures (`start_rfc` reuses `record_run` + `update_status`), and update the status enumeration description in the `RunRecord` docstring.
5. **T5 Make messages phase-aware** (depends on T2, T4) — Route `_process_run` by phase based on the run's status; add `APPROVAL_LABEL`; comment processing takes “the latest comment after the cursor” (regardless of author). In the `rfc-review` phase: approval label present → `implement`; otherwise, if there is a new comment → `refine_rfc`, then advance the cursor past the latest comment on the PR after the reply has been posted (thereby consuming the agent's own reply and preventing a self-loop); in the coding phase, CI/comment → `iterate`; merged → done.
6. **T6 Revise the CLI + e2e** (depends on T2, T5) — Remove the `solve` subcommand and `_cmd_solve`; add the four subcommands `rfc` / `refine-rfc` / `implement` / `iterate` and their handlers (`refine-rfc` / `iterate` take the latest human comment as detail), and update the `_dispatch` routing table.

**End-to-end validation**: `bash scripts/e2e-rfc-0005-rfc-first.sh` (demonstrates: draft RFC → simulate comment → refine → apply approval label → implement → poll to transition to done).

Dependency DAG: `T1 → T2`, `T3 → T2`, `T4 → T2`, `T2 → T5`, `T4 → T5`, `T2 → T6`, `T5 → T6`. T1 / T3 / T4 have no incoming edges and can start in parallel.

## Drawbacks

- Splitting a single `solve` into four atomic operations + a `workspace` module increases the number of files and subcommands, making it harder to understand initially.
- The RFC-first loop adds an `rfc-review` phase and a draft/ready PR state machine, introducing an additional round trip compared with “writing code directly”; however, this is the necessary cost of the principle of “aligning on the design before writing code.”
- The message layer's logic for “advancing the cursor to consume self-comments” is subtle and needs unit tests to guard against self-loops.

## Rationale and alternatives

- **Why split into four atomic operations**: A single `solve` couples git / GitHub / state / message routing, cannot express the two phases of “RFC review” and “writing the implementation,” and is difficult to test independently. After splitting, each operation has a single responsibility and can be scheduled and stubbed independently, aligning with OpenAgents' principles of “minimalism and decoupling” (principles 1, 10).
- **Why extract `workspace` instead of leaving it in the orchestrator**: Pure git/worktree logic is orthogonal to orchestration logic. Extracting it slims down the orchestrator and allows Workspace to be unit-tested independently (fetch / idempotent cleanup / reuse or recreate / push even when there are no changes).
- **Why use draft PRs to represent rfc-review**: Reuse GitHub's native draft/ready mechanism to represent the phase, without inventing a custom way to expose state externally; alignment between agents through PR + comment is precisely this framework's messaging model.
- **Alternative: only recognize human authors when processing comments**. Rejected: taking “the latest comment after the cursor” (regardless of author) + advancing the cursor to consume self-comments is simpler and inherently prevents self-loops, without relying on filtering each comment by login.
- **Leave the internal review/CI logic untouched**, only layering phase routing on top to minimize the scope of changes.

## Prior art

“RFC before implementation” corresponds to Rust RFC / various design review processes; the two-stage draft PR → ready PR approach is a common “design first” collaboration pattern on GitHub. Using git worktree for parallel, isolated workspaces is mainstream practice. This feature takes those core ideas and applies them to OpenAgents' multi-agent + PR/comment messaging model.

## Unresolved questions

None. The boundaries of the four atomic operations, the rfc-review state machine, and the semantics of message cursor advancement have all been settled within this group.

## Future possibilities

- `refine_rfc` could introduce more structured aggregation of review decisions (voting by multiple reviewers).
- RFC numbering / templates could be further validated automatically by the skill.
- Phase routing could be extended with more statuses (such as blocked / needs-human) to support more complex collaboration.
