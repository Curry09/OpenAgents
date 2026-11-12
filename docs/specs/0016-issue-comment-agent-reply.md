---
number: "0016"
title: "Automatic agent replies to new comments on issue pages (extending comment replies from PRs to issues)"
issue: 149
slug: issue-comment-agent-reply
summary: "Extend the “new human comment → signed agent reply” loop from PRs to issue pages: reply branch ② of vigil also reads issue-page comments for **admitted issue subjects that do not yet have a PR**, filters for new human comments based on signatures, and dispatches replier (with an issue-context prompt, answering questions only without changing code) to post through the issue-level signed-comment interface. Complete the issue primitives on the read and write sides (identity.new_human_comments_on_issue / post_signed_comment_on_issue, reusing the existing github.list_issue_comments/issue_comment), add an issue-comment cursor to state, and add a manual --issue interface to the reply-comment CLI. The admission flow handled by admitter (the one-time triage:human admission conversation) and this reply flow (ongoing Q&A for admitted issues) are naturally separated by the issue's admission state and do not interfere with each other."
e2e:
  intent: "Prove that the closed loop “a new human comment appears on an issue page → the agent detects it → dispatches a replier → posts a signed reply to that issue” works through an offline deterministic execution path and does not trigger itself (its own signed reply is not treated as a new human comment in the next round)."
  method: "Form: backend-only orchestration, with no navigable product-facing frontend; the self-check tool list has no Playwright / Chrome DevTools MCP,\nso no browser e2e is specified. Instead, use an offline deterministic testing method (following the fake-github offline e2e style of Spec-0061/0065):\nthe script scripts/e2e-spec-0016-issue-comment-agent-reply.sh repeatedly calls run_vigil(once=True), using injected\nfake github + fake backend to construct an issue that **has been admitted (has the ready label) and has no PR yet**, whose latest comment\nis an unsigned human comment. Assertions:\n1. On that tick, vigil classifies this issue as ACTIONABLE:reply (rather than solve) and dispatches a replier;\n2. The replier's reply is posted to that issue (gh issue comment) through identity.post_signed_comment_on_issue and carries this\n   instance's signature `<!-- openagents:agent=… -->`;\n3. Run another tick: the latest comment now carries our signature → `_latest_is_ours` True → no duplicate reply is posted (no self-triggering infinite loop);\n4. The manual posting path `oa reply-comment --issue N --body …` likewise posts to the issue through the signed posting path.\n"
tasks:
  - id: T1
    title: "identity issue signature read/write primitives (new_human_comments_on_issue + post_signed_comment_on_issue)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/identity.py
      - tests/test_identity_issue_reply.py
    scope: "Add issue-specific signature read/write primitives to identity, symmetric with the existing PR versions, with zero changes to the existing PR functions (zero regressions). On the read side, new_human_comments_on_issue(*, number, since) mirrors new_human_comments, calling github.list_issue_comments(number=…) instead and retaining the two constraints “created_at > since and parse_agent_id is None” (new comments only + humans only, to prevent self-triggering). On the write side, post_signed_comment_on_issue(*, number, body, agent_id): apply the signature with sign → github.issue_comment(number=…, body=…) → issue-specific read-back verification and an additional signed comment if the signature is missing (read back through list_issue_comments and add the signed comment through issue_comment), fully satisfying Spec-0064 constraint ③ (rather than merely warning). Reuse the existing github.list_issue_comments/issue_comment; do not modify github.py."
    acceptance: "pytest tests/test_identity_issue_reply.py passes: new_human_comments_on_issue returns only unsigned human comments after since, filters out all signed machine comments, and sorts by created_at in ascending order (monkeypatch github.list_issue_comments); post_signed_comment_on_issue applies the signature and posts to the issue through issue_comment, then performs a no-op if the latest comment read back already contains this instance's signature, or adds a signed comment if the signature is missing (monkeypatch list_issue_comments/issue_comment); the behavior of the existing PR versions, new_human_comments/post_signed_comment, remains unchanged. ruff clean; comments reference # Spec-0016/T1."
  - id: T2
    title: "state issue-comment cursor (get/set_issue_cursor, independent namespace)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/state.py
      - tests/test_runtime_state_issue_cursor.py
    scope: "Add an issue-comment cursor to RuntimeState, at the same level as the existing PR cursor (the cursors key, indexed by pr_number) but in an independent namespace (such as the issue_cursors key, indexed by issue number), to avoid key collisions between issue N and PR N. get_issue_cursor(*, number) -> str | None / set_issue_cursor(*, number, comment_id), persisted to runtime-state.json; the write path holds RuntimeState._LOCK (as with set_cursor; losing a cursor entry means replying to the same human comment again). Zero changes to the existing get_cursor/set_cursor."
    acceptance: "pytest tests/test_runtime_state_issue_cursor.py passes: get reads back the same value after set; get returns None by default; the cursors for issue N and PR N do not interfere with each other (writing issue N does not affect get_cursor(pr_number=N)); the write path runs under the lock. ruff clean; comments reference # Spec-0016/T2."
  - id: T3
    title: "replier issue prompt + context issue-reply placeholders (answer questions only, without changing code)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/agents/replier.py
      - openagents/runtime/context.py
      - tests/test_agents_replier_issue.py
      - tests/test_runtime_context_issue_reply.py
    scope: "Add an issue-context prompt to replier and issue-reply placeholder assembly to context, coexisting with the existing PR versions with zero changes to them. replier.ISSUE_PROMPT (string.Template, with placeholders $issue_number / $comment_body, **no** $branch, and **no** “change the code if needed” branch—answer questions only, without triggering the delivery protocol, aligned with issue #149's “reply only, do not solve”), reusing the existing replier.OUTPUT_SCHEMA={reply:str, resolved:bool} (resolved indicates whether this round's reply has adequately addressed the request in this comment). context.for_issue_reply(*, work_dir, issue_number, comment) -> dict assembles the {issue_number, comment_body, context} placeholders (following the style of for_reply, using the issue key, with lazy injection on the read side). Leave the existing replier.PROMPT / context.for_reply unchanged."
    acceptance: "pytest tests/test_agents_replier_issue.py + tests/test_runtime_context_issue_reply.py pass: ISSUE_PROMPT.substitute can fill in issue_number/comment_body, and the rendered text contains no branch/code-change wording and conveys the intent “reply only without changing code”; for_issue_reply produces a placeholder dict containing the issue_number/comment_body/context keys (monkeypatch the github read side to keep it hermetic); the behavior of the existing PR versions, PROMPT/for_reply, remains unchanged. ruff clean; comments reference # Spec-0016/T3."
  - id: T4
    title: "vigil wiring: _sense populates issue latest_comment_is_ours (only for ready issues without a PR) + _do_reply issue dispatch + offline e2e"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - tests/test_recipe_vigil_issue_reply.py
      - scripts/e2e-spec-0016-issue-comment-agent-reply.sh
    scope: "Wire issue-page replies into vigil reconcile, keeping the scope of changes minimal and the structure parallel to the PR side. _sense: when kind==_KIND_ISSUE and pr_number is None and _LABEL_READY in labels, read github.list_issue_comments(number) → latest_comment_is_ours=_latest_is_ours(comments) (reuse the existing pure function); otherwise preserve the current behavior (issues that are not ready belong to admitter; issues with a PR follow the PR flow). Do not add a _Facts field carrying a comment id—change only the source of the existing latest_comment_is_ours value, leaving the complete _fingerprint field set and the “applying an attempt stamp does not change fp” invariant unchanged (guardrail one must not undermine itself). _do_reply: the pr_number is None (and kind is issue) branch—new_human_comments_on_issue(number, since=state.get_issue_cursor) → context.for_issue_reply → engine.run_agent(replier, ISSUE_PROMPT placeholders) → identity.post_signed_comment_on_issue → state.set_issue_cursor; incorporate _NEEDS_HUMAN_CONTRACT as a first-class exit path. Branch ② (_classify:738), the watchdog, and priority handling work as-is without changes. Include an offline e2e script (see frontmatter e2e.method)."
    acceptance: "pytest tests/test_recipe_vigil_issue_reply.py passes: the latest comment on a ready issue without a PR is from an unsigned human → _sense sets latest_comment_is_ours=False → _classify returns ACTIONABLE:reply (rather than solve); for an issue without a PR that is not ready / an issue with a PR → latest_comment_is_ours retains its current behavior (no unintended activation); the _do_reply issue branch posts to the issue through post_signed_comment_on_issue and advances the issue cursor; after the reply, the latest comment bears our signature → on the next tick, _latest_is_ours is True → no duplicate reply; the _fingerprint field set still == the complete set of dataclasses.fields(_Facts), with no comment id. bash scripts/e2e-spec-0016-issue-comment-agent-reply.sh passes. ruff clean; comments reference # Spec-0016/T4."
  - id: T5
    title: "reply-comment --issue manual interface (mutually exclusive with --pr; exactly one required)"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli_issue_reply.py
    scope: "Add --issue N to the hidden internal command reply-comment, forming a mutually exclusive argument group with the existing --pr N (exactly one must be supplied). --issue routes to identity.post_signed_comment_on_issue(number=…, body=…, agent_id=…); --pr retains the existing post_signed_comment. Continue to omit help= (a hidden command; its role under Spec-0064/T5 remains unchanged). Zero changes to the existing --pr path."
    acceptance: "pytest tests/test_cli_issue_reply.py passes: oa reply-comment --issue N --body X posts to the issue through post_signed_comment_on_issue (monkeypatch); supplying both --pr and --issue produces an error, and supplying neither produces an error (an argparse required mutually exclusive group); --pr N --body X still uses the existing post_signed_comment (zero regressions). ruff clean; comments reference # Spec-0016/T5."
---

# 0016 · Automatic agent replies to new comments on issue pages (extending comment replies from PRs to issues)

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Extend OpenAgents' existing "**new human comment → signed agent reply**" loop from **PRs** to **issue pages**. Today, this loop works only on PRs: in vigil's reconcile branch table, `_classify` branch ② (`not facts.latest_comment_is_ours` → `ACTIONABLE:reply`) → `_do_reply` reads PR comments, dispatches the `replier` agent, and posts a signed reply through `identity.post_signed_comment` (the PR version). Human comments on issue pages have no reply path: for **issues without a PR yet**, `_sense` deliberately does **not** set `latest_comment_is_ours` (`vigil.py:654-655`: "Human–agent conversations on issues without a PR belong to the admission-side admitter; reply branch ② requires PR context, so it is not activated here"), and the reply-comment CLI accepts only `--pr`.

This spec specifically removes that restriction: for issue subjects that **have been admitted (`ready`) and do not yet have a PR**, vigil will also read issue-page comments, use signatures to filter for new human comments, dispatch `replier` (with an issue-context prompt—answer questions only, **do not change code**, aligned with issue #149's "reply only, do not solve"), and post replies through an **issue-level signed posting path**. The underlying gh read/write primitives (`github.list_issue_comments` / `github.issue_comment`) **already exist**. What is missing is the three layers above them: issue versions of signed reads/writes (identity), issue comment cursors (state), issue reply context and prompts (context/replier), plus vigil's branch wiring and the manual `--issue` path in reply-comment (cli).

## Motivation

**Current state (restated in place, evidence-driven · Principle 8).** Comments are messages, and an agent receiving and responding to each new comment is the core loop of CLAUDE.md Principle 2. Today, this loop is implemented in the level-triggered reconcile loop in `openagents/recipes/vigil.py` (**not** in the `messages.poll` mentioned in the issue body—the `messages` module was **removed entirely** during the unification of the two stacks in Spec-0062/0064, and `messages.poll` remains only in historical comments; the wording in issue #149's body is outdated and based on an old mental model, which this spec corrects to reflect the facts). The concrete chain is:

- **Sense**: `_sense` (`vigil.py:598`) reads the current GitHub state once per tick for each subject. For subjects with a PR, it reads `github.list_comments(pr_number=…)` (the PR version, using `gh pr view --json comments`) → `_latest_is_ours` (`vigil.py:858`: does the latest comment carry our signature? No comments counts as True) → stores the result in the immutable `facts.latest_comment_is_ours`.
- **Classify**: `_classify` (`vigil.py:686`) is a pure-function branch table; branch ② (`vigil.py:738`) is `if not facts.latest_comment_is_ours: return _Verdict(ACTIONABLE, action=reply)`—**this branch itself is subject-independent** and can be reused as long as `facts.latest_comment_is_ours` is populated with issue semantics. It precedes solve/rebase/ci/… (a person is waiting, so it has the highest priority).
- **Execute**: `_do_reply` (`vigil.py:2548`) runs `if pr_number is None: return ""` (returns an empty string immediately when there is no PR) → `identity.new_human_comments(pr_number, since=cursor)` fetches new human comments → `context.for_reply(pr_number, branch, comment)` assembles placeholders → `engine.run_agent(replier, …)` → `identity.post_signed_comment(pr_number, …)` posts a signed reply → `state.set_cursor(pr_number, …)` advances the cursor. **Every step in the chain is keyed by `pr_number`.**
- **Prevent self-triggering**: `identity.sign` appends the hidden HTML signature `<!-- openagents:agent=<id> -->` to the end of the body; `identity.new_human_comments` (`identity.py:94`) filters out comments where `parse_agent_id(body) is not None` (all machine comments), retaining only unsigned human comments with `created_at > since`. These two constraints (new only + human only) ensure that the agent never reads its own replies and starts talking to itself.

**Gaps.** Three places **hardwire the capability to PRs**:
1. `_sense` **does not activate** `latest_comment_is_ours` for issues without a PR (`vigil.py:647-656`; it only feeds issue comment timestamps into the progress clock for the watchdog, leaving `latest_comment_is_ours` at its default True) → branch ② never triggers for issues.
2. Issue pages have no agent reply path: `identity.new_human_comments` / `post_signed_comment` / `_verify_signature_or_fix` all accept only `pr_number` and call `gh pr view` / `gh pr comment`; `context.for_reply` is also keyed by PR; the `replier` prompt uses **PR context** (`$pr_number` / `$branch` / "change code if needed").
3. The `reply-comment` CLI (`cli.py:149`) accepts only `--pr`.

The result: after an issue is opened, when a person adds comments on the issue page (additional requirements, questions, corrections), the current workflow **does not respond at all**. Alignment and clarification at the issue level depend entirely on people manually relaying information—inconsistent with Principle 2. **This is precisely the gap issue #149 aims to fill.**

**Why now, and why it is worthwhile.** Issues are the entry point to the autonomous loop (vigil discovers an issue → dispatches an agent to solve it). Issue-page comments are the **only human–agent alignment channel** between the issue being opened and the first PR being delivered; today, that window is silent. Filling this gap lets an agent respond immediately to a person's follow-up questions or corrections on an issue (even if only with "Understood; I take this to mean X—is that right?" or "This is beyond what I can decide; handing it to a human"), truly moving high-level oversight to the issue layer (Principle 2: "People handle the big picture, not the details").

## Guide-level explanation

From the user's perspective, this feature adds one natural behavior: **leave a comment on an issue page managed by OpenAgents, and receive a signed agent reply shortly afterward.**

- **Who receives a reply**: an issue that **has been admitted** (has the `ready` label and has passed the three-state admission gate), **does not yet have a PR**, and whose latest comment is a **human** comment (without an OpenAgents hidden signature).
- **What the reply covers**: replier (in issue context) understands what your comment is asking for (a follow-up question? additional requirements? a correction?) and **answers questions only, without changing code** (issue #149 explicitly says "reply only, do not solve"—changing code/opening a PR belongs to the solve branch and is outside the scope of this issue). If it cannot answer, lacks authorization, or encounters ambiguous requirements → use the first-class exit path: apply `needs-human` + leave a reason; Vigil immediately classifies the subject as terminal, stops polling, and hands it to a human.
- **What the reply looks like**: a comment posted on the issue page, ending with the hidden signature `<!-- openagents:agent=… -->` (not rendered by GitHub, with no impact on people). This signature is key to preventing self-triggering: on the next tick, vigil sees that the latest comment has its own signature → `_latest_is_ours` is True → no repeated reply.
- **Manual path**: a dispatched sub-agent (or an operator) can use `oa reply-comment --issue N --body "…"` to manually post a signed comment to an issue, symmetric with the existing `--pr` path (choose one; mutually exclusive).

**Admission side vs. reply side (a key boundary that readers can easily confuse).** Today, vigil already converses with people in issue comments—but that is the **admission-side** admitter (`_ask_human`, handling the `triage: human` state: a one-time answer to the admission question "Should this issue be worked on at all?"). This feature is the **reply side**: **ongoing answers** to subsequent human comments **after the issue has been admitted**. The two are naturally separate and do not conflict, because admitter runs only in `_intake` (the producer's admission stage) for issues in `triage:human` (**not ready**). Once an issue receives `ready`, it leaves the admission stage and enters the reconcile frontier; subsequent human comments then belong to this feature's reply branch. Admission state (whether `ready` is present) is the sole criterion for this boundary; no new coordination mechanism is needed.

## Reference-level explanation

### Overall approach

Reuse the fact that "branch ② itself is subject-independent": **populate `facts.latest_comment_is_ours` with issue semantics for admitted issues without a PR, and branch ② and the watchdog come for free**; add an issue dispatch path to `_do_reply`; add issue-specific signed versions of the underlying primitives. Scope is strictly limited to issues that **have been admitted and do not yet have a PR**—subjects with a PR continue using the existing PR-comment path unchanged (merging the issue-page and PR-page streams is Future work; see below).

### Key contracts and invariants

- **fp safety (do not undermine guardrail one)**: `_Facts.latest_comment_is_ours` is an existing bool field already included in the complete set used by `_fingerprint`; this feature **only changes the source of its value** (computed from issue comments for issues without a PR) and **does not add a field carrying a comment id**. After we post a reply, the latest comment carries our signature → the bool flips to True → fp changes = legitimate progress (the person has received an answer), and branch ② stops firing. This is exactly isomorphic to the PR-side semantics; `_Facts` still contains no comment id (the invariant that recording an attempt stamp does not change fp remains intact).
- **Prevent self-triggering**: the issue read-side `new_human_comments_on_issue` retains the two constraints "`created_at > since` **and** `parse_agent_id is None`"; the issue write-side `post_signed_comment_on_issue` retains the "sign, then post + read back to verify, and add the signature if missing" loop (Spec-0064 constraint ③, not merely a warning), with reads through `list_issue_comments` and writes through `issue_comment`.
- **Enforce the admission/reply boundary**: for issue subjects, reply branch ② activates only when `ready in facts.labels` (issues without `ready` still belong to admitter). Turn "admitter before admission, replier after admission" from a soft convention in comments into explicit conditions in `_sense`/`_classify` (principle: turn soft conventions into enforced constraints).
- **Answer questions only, without changing code**: the issue replier prompt **does not contain** the "change code if needed" branch and **does not** trigger the delivery protocol; the output schema is restricted to `{"reply": str, "resolved": bool}` (the same schema as PR replier, where `resolved` means "whether this comment's request has been adequately addressed by this round's reply").

### DAG + file assignments

| Task | Content | files (exclusive single writer) | depends-on |
|---|---|---|---|
| T1 | identity issue signed read/write primitives | `openagents/utils/identity.py`, `tests/test_identity_issue_reply.py` | — |
| T2 | state issue comment cursor | `openagents/runtime/state.py`, `tests/test_runtime_state_issue_cursor.py` | — |
| T3 | replier issue prompt + context issue reply placeholders | `openagents/agents/replier.py`, `openagents/runtime/context.py`, `tests/test_agents_replier_issue.py`, `tests/test_runtime_context_issue_reply.py` | — |
| T4 | vigil wiring: `_sense` populates issue `latest_comment_is_ours` (only ready issues without a PR) + `_do_reply` issue dispatch + offline e2e | `openagents/recipes/vigil.py`, `tests/test_recipe_vigil_issue_reply.py`, `scripts/e2e-spec-0016-issue-comment-agent-reply.sh` | T1, T2, T3 |
| T5 | `reply-comment --issue` manual path | `openagents/cli.py`, `tests/test_cli_issue_reply.py` | T1 |

- T1/T2/T3 have pairwise disjoint files and **can run in parallel** (no mutual dependency).
- T4 is the convergence point, depending on T1 (read/write primitives) + T2 (cursor) + T3 (prompts/placeholders).
- T5 depends on T1 (`post_signed_comment_on_issue`); its files do not overlap with T4, so it can run in parallel with T4.
- `github.py` **is not in any Task's files**—`list_issue_comments` (`github.py:447`) / `issue_comment` (`github.py:432`) already exist and are reused directly, with zero changes (zero regressions).

### Interface contracts for each Task

- **T1**: `identity.new_human_comments_on_issue(*, number: int, since: str) -> list[github.Comment]` (mirrors `new_human_comments`, switching the call to `github.list_issue_comments(number=…)`); `identity.post_signed_comment_on_issue(*, number: int, body: str, agent_id: str) -> None` (sign → `github.issue_comment(number=…, body=…)` → issue version of `_verify_signature_or_fix`, reading back through `list_issue_comments` and adding a missing signature through `issue_comment`). Existing PR functions **remain unchanged** (zero regressions).
- **T2**: `state.get_issue_cursor(*, number: int) -> str | None` / `state.set_issue_cursor(*, number: int, comment_id: str)`, stored under a separate namespace key in `runtime-state.json` (such as `issue_cursors`, alongside `cursors`, to avoid key collisions between issue N and PR N); the write path holds `RuntimeState._LOCK` (as `set_cursor` does).
- **T3**: `replier.ISSUE_PROMPT` (Template, with placeholders `$issue_number` / `$comment_body`, **no** `$branch`, and **no** “modify code” branch; answers questions only) + reuse `replier.OUTPUT_SCHEMA`; `context.for_issue_reply(*, work_dir, issue_number, comment) -> dict` assembles the `{issue_number, comment_body, context}` placeholders (following the style of `for_reply`, with an issue key).
- **T4**: `_sense`—when `kind == _KIND_ISSUE and pr_number is None and _LABEL_READY in labels`, read `github.list_issue_comments(number)` → `latest_comment_is_ours = _latest_is_ours(comments)` (reuse the existing pure function); otherwise retain current behavior. `_do_reply`—the `pr_number is None` (and kind issue) branch: `new_human_comments_on_issue(number, since=get_issue_cursor)` → `context.for_issue_reply` → `run_agent(replier, ISSUE_PROMPT…)` → `post_signed_comment_on_issue` → `set_issue_cursor`; append `_NEEDS_HUMAN_CONTRACT` as a first-class exit path.
- **T5**: Add a mutually exclusive argument group `--pr N | --issue N` to `reply-comment` (exactly one is required); `--issue` routes to `post_signed_comment_on_issue`, while `--pr` retains the existing `post_signed_comment`.

### e2e script

`scripts/e2e-spec-0016-issue-comment-agent-reply.sh` (offline, fake-github + fake-backend, following the Spec-0061/0065 style)—see frontmatter `e2e.method` for details.

## Drawbacks

- **One additional read request**: For each admitted issue without a PR, `_sense` makes one additional `gh issue view --json comments` call per tick. GitHub's authenticated quota is 5000 req/h; with hundreds of issues, this adds to the need for batching already recorded in Spec-0065's Future section (fetching multiple subjects with a single GraphQL query).
- **Polling latency**: Retains polling (no webhook); the lower bound on reply latency = vigil tick interval, structurally identical to the PR side (issue #149 explicitly says “retain polling for now”).
- **The admission/reply boundary depends on the correctness of the `ready` label**: If an issue should be admitted but has not been labeled `ready`, its comments will continue to be handled by the admitter rather than the replier. This makes the boundary depend on the correctness of the existing admission gate (acceptable: `ready` is already the sole token for admission).
- **Single-stream limitation**: This iteration covers comments on an issue page **only while that issue has no PR**; once the issue has a PR, new comments on the issue page no longer receive replies (handling switches to the PR flow). See Future.

## Rationale and alternatives

**Selected approach: Extend the semantics of `latest_comment_is_ours` + reuse branch ② (limited to ready issues without a PR).** Because branch ② and the watchdog are already subject-independent pure logic, feeding issue comments into the existing fact provides classification, priority, and guardrails with no additional logic, minimizing the scope of changes (Principle 1, Occam). It is also **fully structurally identical** to the PR side's mechanisms for preventing self-triggering, tracking cursors, and signing—one mental model applied in two places, with no second parallel mechanism to keep consistent.

**Alternative 1: Revive a separate issue-comment poller in the style of `messages.poll` (new module).** This matches the original description in the body of issue #149, but the `messages` stack was removed entirely when the two stacks were unified; reopening a parallel polling loop means building a second “read comments → filter signatures → reply → advance cursor” pipeline, duplicating vigil's reconcile and requiring separate concurrency/claim/watchdog mechanisms. This goes against the convergence trajectory of 0062-0065 (the number of recipes remains 3). **Rejected.**

**Alternative 2: Directly reuse the PR replier prompt + allow it to modify code.** This eliminates T3's issue prompt. However, issue #149 explicitly scopes the work to “reply only, do not solve”; the PR replier's “modify code if needed + delivery protocol” would prompt the agent to start making changes in situations that call only for answering questions, exceeding the scope. In addition, issues have no `$branch` context, so the PR prompt's placeholders do not match. **Rejected** (preserve the clear semantic boundary that “issues are for answering questions only”).

**Alternative 3: Fold issue replies into the admitter (have the admitter handle both admission and subsequent questions).** This eliminates the branch wiring. But the admitter is a **fail-closed human-approval gate** (determining “whether the human has actually approved”), responsible for admission decisions; adding ongoing question answering would compromise its single responsibility, and its output schema/prompt have admission semantics. **Rejected** (separating admission from replies based on the `ready` state is cleaner).

## Prior art

- **This repository's complete PR-comment reply loop** (RFC-0011 signatures / Spec-0032 targeted restoration of the read side / Spec-0061 replier+poll_comments / Spec-0065 vigil reconcile branch ②)—this spec extends the same structure to issues, reusing all existing primitives and invariants for reading, writing, and preventing self-triggering.
- **Existing uses of issue comments in this repository**: Spec-0043 `issue_comment` (issue-level writes), Spec-0049 `list_issue_comments` + signed claim notes, Spec-0065 admitter `_ask_human` (admission conversations through issue comments)—these demonstrate that the issue-comment read/write primitives and gh paths already work; this spec reuses them rather than creating new ones.
- **GitHub's comment model**: At the REST layer, PR comments are essentially issue comments (the same endpoint), but this repository deliberately uses two subcommand paths, `gh pr view` / `gh issue view` (a thin wrapper around gh, without touching REST), so the PR and issue versions are two symmetric functions rather than one.

## Unresolved questions

> To be confirmed with the user during review (record only questions the user chooses to retain):
- Should new comments on the issue page also receive replies after a PR exists? This iteration specifies **no replies** (handling switches to the PR flow). If the team wants questions to remain answerable on the issue page at all times, the two streams must be merged (see Future)—is that needed in this iteration?
- Is `ready` sufficient as the admission/reply boundary? If there are issues that are “not ready but require ongoing question answering,” should the activation conditions be broadened?

## Future possibilities

- **Merge the two streams**: Once an issue has a PR, merge comments from the issue page + PR page into a single timeline; `_sense` uses the latest human comment across the two streams to determine the reply target (`reply_target` fact).
- **Real-time delivery through webhooks**: Replace polling, reducing reply latency from the tick interval to near real time (issue #149 explicitly excludes this from the current iteration).
- **Trigger solving through issue comments**: Upgrade “reply” to “reply + modify code/open a PR according to requests in comments” (explicitly excluded from this iteration; an extension of the solve branch).
- **Batched reads**: Incorporate this into the single GraphQL query for fetching comments across multiple subjects recorded in Spec-0065, easing the quota pressure from one `_sense` read per subject.
- **Cross-repository issue aggregation** (explicitly excluded by issue #149).
