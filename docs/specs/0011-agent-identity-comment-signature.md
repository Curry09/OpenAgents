---
number: "0011"
title: "Local Agent Identity + Comment Signatures (Distinguish Self-Comments from Human Comments and Eliminate poll Self-Loops)"
issue: 28
slug: agent-identity-comment-signature
summary: "Give the local agent a persistent identity and sign its comments to distinguish comments it posted itself from human comments, eliminating the self-loop in which poll treats its own comments as new messages."
tasks:
  - id: T1
    title: "Persist agent_id in the state layer"
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
    scope: "Add `get_agent_id` / `set_agent_id` to `State`, and add an optional top-level `\"agent_id\"` key to state.json; make `_load` fault-tolerant (if the key is missing, return a state without agent_id), preserving existing runs/cursors."
    acceptance: "After set, get returns the same value; if never set, get returns None; writes do not damage existing runs/cursors; a missing/corrupted file is still handled gracefully as an empty state."
  - id: T2
    title: "identity module (identity resolution + comment signatures)"
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/identity.py
      - tests/test_identity.py
    scope: "Create `openagents/identity.py`, implementing `resolve_agent_id` (env > state > generate and persist to disk), `sign`, `parse_agent_id`, and `post_signed_comment`, along with the signature marker constant and character set constraints."
    acceptance: "`sign` → `parse_agent_id` round-trips consistently; for unsigned comments/human-authored bodies, `parse_agent_id` returns None; `resolve_agent_id` correctly follows the three-level priority order, persists automatically generated IDs to disk, and remains stable across calls; `post_signed_comment` calls `github.post_comment` with a signed body (assert using monkeypatch)."
  - id: T3
    title: "Exclude self-comments from poll processing decisions + simplify cursors"
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T2
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
    scope: "Add `agent_id` to `Messages.__init__`; additionally exclude comments signed by this agent in `_latest_new_comment`; in `_process_rfc_review`, advance the cursor only to the triggering comment; delete `_newest_comment_id`; in the merge branch of `poll`, pass `agent_id` through to `rebase.rebase_open_prs`."
    acceptance: "Comments signed by this agent do not trigger processing (including the scenario where the process crashes and restarts after posting but before advancing the cursor); comments signed by other agents / unsigned comments still trigger processing as usual; after refine, the cursor equals the triggering comment's `created_at`; human comments arriving while work is in progress are processed in the next cycle."
  - id: T4
    title: "Sign comments posted by the orchestrator"
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: "Add `agent_id` to `Orchestrator.__init__`; change replies in `refine_rfc` to use `identity.post_signed_comment(..., agent_id=self._agent_id)`."
    acceptance: "The body of comments posted by `refine_rfc` carries this instance's signature (assert by monkeypatching `identity.post_signed_comment` or `github.post_comment`); the rest of the workflow (commit/push, state transitions) remains unchanged."
  - id: T5
    title: "Sign rebase conflict comments"
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/rebase.py
      - tests/test_rebase.py
    scope: "Add a required `agent_id` parameter to `rebase_open_prs`; change conflict comments to use `identity.post_signed_comment(..., agent_id=agent_id)`."
    acceptance: "Comments posted when conflicts occur carry a signature; `agent_id` is passed through correctly; error isolation/result classification behavior remains unchanged."
  - id: T6
    title: "Wire up the CLI + remove current_login"
    status: done
    priority: P1
    tags:
      - architecture
      - protocol
      - dx
    depends-on:
      - T3
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/github.py
      - tests/test_cli.py
      - tests/test_github.py
    scope: "Have `cli` resolve `agent_id` and inject it into `Orchestrator` / `Messages`, and have `_cmd_sync_prs` pass `agent_id` through; delete `github.current_login` and its tests."
    acceptance: "poll / vigil / sync-prs receive a consistent agent_id end to end; there are no references to `current_login` anywhere in the repository; ruff + the full pytest suite pass."
---

# 0011 · Local Agent Identity + Comment Signatures (Distinguishing Self-Comments from Human Comments to Eliminate poll Self-Loops)

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Give every locally running agent a **persistent, stable identity** (`agent_id`), and stamp the body of every PR comment it posts with a **parseable signature marker**. When fetching comments, poll can then mechanically distinguish “I just posted this myself” from “a human or another agent posted this,” eliminating **self-loops** in which poll treats its own reply as a new message and triggers processing again.

## Motivation

OpenAgents agents exchange messages through a GitHub-style PR + comment mechanism: whenever a new comment appears on a PR, the agent receives “your PR received a comment” and advances the workflow accordingly (for example, refining an RFC or posting a conclusion). This mechanism has a fatal reflexive flaw: **a comment posted by the agent itself is also “a new comment” to its own poll**.

The old implementation filtered self-comments using “latest comment author != current GitHub login (`github.current_login`).” This criterion fails in several scenarios:

- When multiple agent instances run concurrently under the same GitHub account, their login names are identical, so it cannot distinguish “this instance posted it” from “another instance posted it”—the latter should be processed as a real message.
- It depends on an additional network call (to fetch the current login), which is both slow and a potential point of failure.
- In the window where the agent “crashes and restarts after posting a comment but before it has time to advance the cursor,” poll after restart treats that self-comment as a new message, triggering **duplicate processing / a self-loop**.

The root cause is that the agent **has no process-level stable identity independent of the GitHub account**, and does not **attach that identity to the messages it produces**. This feature introduces a persistent `agent_id` + comment signatures, changing “who posted this comment” from “guess from the author's login” to “read the signature in the body,” making self-comment detection deterministic, local, and persistent across restarts.

## Guide-level explanation

Introduce two concepts:

- **agent_id (identity)**: A process-level stable identifier. Resolution precedence is **env > state > automatic generation and persistence**: use the environment variable if explicitly provided; otherwise, read the `agent_id` persisted in state.json; if neither exists, generate one and write it back to state.json, so subsequent calls (including after a restart) receive the same id.
- **Comment signature (message stamp)**: When an agent posts a comment, it embeds a signature marker containing its `agent_id` in the body. Any party reading the comment can use `parse_agent_id` to recover the sender's `agent_id` from the body; human comments or unsigned comments parse to `None`.

Once wired up, poll's criterion changes from “latest comment author != my login” to “latest comment's **signature** != my `agent_id`.” As a result, comments just posted by the agent itself are precisely excluded (even after a crash and restart, and even with multiple instances running concurrently under the same account); comments stamped with a **different** signature by other agents, and **unsigned** comments posted by humans, continue to be processed as new messages. The old `github.current_login` criterion is then retired entirely.

## Reference-level explanation

The changes are broken down into 6 Tasks (see the DAG at the end; `files` are mutually exclusive, with a single writer per Task):

1. **T1 Persist agent_id in the state layer** (no dependencies) — Add `get_agent_id` / `set_agent_id` to `State`, and add an optional top-level key `"agent_id"` to state.json. `_load` tolerates a missing key (returning state without agent_id), and the existing `runs` / `cursors` structures remain unchanged. This provides the persistence foundation for `agent_id`, required by T2's “persist after generation” step.
2. **T2 identity module** (depends on T1) — Create `openagents/identity.py`: `resolve_agent_id` (env > state > generate and persist, using T1's `set_agent_id` for persistence), `sign` (encode `agent_id` as a signature marker in the body), `parse_agent_id` (decode it from the body, returning `None` if unsigned), and `post_signed_comment` (wrap `github.post_comment`, automatically adding a signature to the body). Also define signature marker constants and `agent_id` character-set constraints to ensure an unambiguous `sign` → `parse_agent_id` round trip. This is the shared signature functionality hub for T3/T4/T5.
3. **T3 Exclude self-comments in poll + simplify cursors** (depends on T2, T5) — Add `agent_id` to `Messages.__init__`; in addition to the existing “newer than the cursor” criterion, `_latest_new_comment` **also excludes comments whose signature equals its own `agent_id`**; the cursor in `_process_rfc_review` **advances only to the triggering comment** (no longer jumping to the latest one), eliminating the self-loop window caused by “a crash after posting but before advancing the cursor”; delete the now-unneeded `_newest_comment_id`; the merge branch in `poll` passes `agent_id` through to `rebase.rebase_open_prs` (hence the dependency on T5 having the signature parameter in place).
4. **T4 Stamp orchestrator reply comments** (depends on T2) — Add `agent_id` to `Orchestrator.__init__`; change conclusion replies in `refine_rfc` to use `identity.post_signed_comment(..., agent_id=self._agent_id)`, so the comments it produces carry signatures and are recognized as self-comments by T3. The commit/push and state transition logic remain unchanged.
5. **T5 Stamp rebase conflict comments** (depends on T2) — Add a **required** `agent_id` to `rebase_open_prs`; change comments posted on rebase conflicts to use `identity.post_signed_comment(..., agent_id=agent_id)`. Error isolation and result classification behavior remain unchanged.
6. **T6 CLI wiring + retire current_login** (depends on T3, T4, T5) — At entry, `cli` resolves `agent_id` (via `resolve_agent_id`) and injects it into `Orchestrator` / `Messages`; `_cmd_sync_prs` passes `agent_id` through to the rebase path; delete `github.current_login` and its tests (signatures have replaced the old self-comment criterion, with no remaining references anywhere in the repository).

**End-to-end validation**: Validation of this feature is based on the full unit test suite — `ruff check` + `pytest` (each Task's `tests/test_*.py` uses monkeypatch to stub `github.post_comment` / state IO, asserting signature round trips, self-comment exclusion, cursor advancement only to the triggering comment, and no references to `current_login`). There is currently no e2e script dedicated to this feature under the repository's `scripts/`; if external regression testing is needed, add `scripts/e2e-spec-0011-agent-identity.sh` to chain together the assertions above offline.

Dependency DAG: `T1 → T2`, `T2 → T3`, `T2 → T4`, `T2 → T5`, `T5 → T3`, `T3 → T6`, `T4 → T6`, `T5 → T6`.

## Drawbacks

- An additional signature marker in the comment body introduces minor noise for human readers (the marker must remain compact and unobtrusive).
- Once persisted, `agent_id` remains for the long term; if the same working directory is reused for multiple unrelated purposes, they may inadvertently share an identity (in practice, state.json corresponds one-to-one with a worktree, so the risk is manageable).

## Rationale and alternatives

- **Why use a “body signature” rather than “rely on the author's login”**: Login names cannot distinguish multiple instances running concurrently under the same account, require an additional network call, and leave a crash-and-restart window. Attaching the identity to the message body makes detection purely local string parsing: deterministic, persistent across restarts, and requiring zero additional network calls.
- **Why persist `agent_id` in state.json rather than use only an environment variable**: Environment variables are suitable for explicit overrides, but the default scenario needs an identity that is **stable without configuration**, hence the three-level env > state > generate and persist approach, supporting both overrides and zero-configuration stability.
- **Why the cursor “advances only to the triggering comment”**: Aligning the “processing action” and “cursor advancement” with the same triggering comment eliminates the window where “a self-comment has been posted, but a crash occurs before the cursor has moved past it,” causing duplicate processing in the next round; together with signature-based exclusion, this provides two safeguards.
- **Alternative: Apply a GitHub label to comments / mark them with reactions**. Rejected (YAGNI + decoupling): labels/reactions require additional APIs and do not travel with the body; body signatures have zero dependencies and naturally travel with the message.

## Prior art

“Embedding a parseable sender marker in a message body for self-identification / loop prevention” is common practice in messaging systems (such as email's `Message-ID` / `In-Reply-To`, or bots checking sender ids to avoid responding to their own messages). This feature takes the core idea of “using a stable identity to identify message origins and filter out one's own messages” and applies it to the specific medium of PR comments.

## Unresolved questions

None. Identity resolution precedence, signature round trips, cursor semantics, and retirement of `current_login` have all been settled within this group.

## Future possibilities

- Signatures could be extended to carry more structured metadata (such as the type of connected coding agent, claude-code / codex), allowing the frontend to distinguish output from different agents.
- In collaboration among multiple agents, signatures could support visualization / auditing of comment ownership.
- Add an offline end-to-end script, `scripts/e2e-spec-0011-agent-identity.sh`, chaining together regression checks for signature round trips + self-comment exclusion.
