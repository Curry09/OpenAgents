# RFC-0011
"""Identify the local agent and sign comments on issues and pull requests."""

from __future__ import annotations

import os
import re
import uuid
from datetime import UTC, datetime

from openagents.runtime.state import RuntimeState

# Spec-0074/T1: arias-import switch - Platform operations are configured by github/gitea driver to call zero changes.
from openagents.utils import forge as github

# RFC-0011 Decision 2: Environmental Variables for Visible Naming Examples; A Readable Naming Entry for Multiple Entries.
AGENT_ID_ENV = "OPENAGENTS_AGENT_ID"

# Spec-0049/T2: Sign the flag as required - hide the second paragraph with the existing agent** and sign the "Authorize the sign" from
# Other signed machine reviews (precheck cross-references, reviewer decision returns, etc.) are also on the same page <! -- openagets: agent=... >
# ) Distinguished in. GitHub does not render HTML comments, and interferes with humans without any interference; gh Raw body can be hit by `in`.
# Only "in-in-a-situ" determination (without variable fields) is required, so the constant + substring is matched and the regular rule is not introduced (Ocam, Concept 1).
_CLAIM_MARKER = "<!-- openagents:claim -->"

# RFC-0011 Decision 3: agent_id character set limited to [A-Za-z0-9_-] to secure the signature from accidental complication with the body.
_AGENT_ID_CHARS = "A-Za-z0-9_-"

# Hide signature tag template: GitHub Markdown does not render HTML comments, and does not interfere with human readers, and the user is not allowed to read them.
# But gh pr view --json comments can be dissected from the lower part of the original body returned.
_SIGNATURE_TEMPLATE = "<!-- openagents:agent={agent_id} -->"

# The regular rule for the declaring signature: agent_id is only for strict matching of character sets, and the normal text in the body is not misjudged.
_SIGNATURE_RE = re.compile(rf"<!-- openagents:agent=([{_AGENT_ID_CHARS}]+) -->")


def resolve_agent_id(*, state: RuntimeState) -> str:
    """RFC-0011 Decision 2: Parsing this instance agent_id (env > Runtimestate > Auto Generate and Discrete).

    # Spec-0063/T2: Reconnect the new inn - Access moved from old State to runtime.RuntimeState, Crashed from state.json Top Level
    # Replace the key with runtime-state.json top floor key (get/set_agent_id signature unchanged, behaviour fully equal).

    - env OPENAGENTS_AGENT_ID is not empty: direct use, no state (no contaminated drop value, env is temporary cover).
    - Otherwise Runtestate has its value: reuse, ensures cross-process/relaunch stability.
    - None: uuid4 generation short string, immediately state.set_agent_id drop (runtime-state.json), to get the follow-up process to the same id.

    returns the non-empty, charset limited ([A-Za-z0-9_-]) stability id.
    """
    env_value = os.environ.get(AGENT_ID_ENV)
    if env_value and env_value.strip():
        return env_value.strip()

    existing = state.get_agent_id()
    if existing:
        return existing

    # uuid4 hexadecimal string: no external dependence (ideology 1) and naturally falls within the restricted character set.
    generated = uuid.uuid4().hex[:12]
    state.set_agent_id(agent_id=generated)
    return generated


def sign(*, body: str, agent_id: str) -> str:
    """RFC-0011 Decision 3: Add a hidden signature tag to the end of body and return the new body (pure function) with the signature."""
    return f"{body}\n\n{_SIGNATURE_TEMPLATE.format(agent_id=agent_id)}"


def parse_agent_id(*, body: str) -> str | None:
    """RFC-0011: parsing the signature agent_id from body; returns None without signature (pure function).

    RFC-0019: `sign` is a verification inverse. No production currently exists for polll to call it filtering comment (the comment drive is retired, the comment side is retired, the comment side is not working.
    Poll does not read PR comments, automatically moving to reviewer gate; retains the claim as the subject of the public API+ test stamp round trip, and then leaves the page open.
    The blog also provides a good idea of how to use the Internet to help people in their own countries.
    """
    match = _SIGNATURE_RE.search(body)
    return match.group(1) if match else None


def new_human_comments(*, pr_number: int, since: str) -> list[github.Comment]:
    """Spec-0032/T4: Read side resurrection - returns to the PR ”New Human Review After Block” in time order.

    github.list_comments to take full-scale comments and keep those that satisfy both hard-bound:
    - created_at is more than `since` (string waterline block_watermark) - Historical review, comments before last unmounted
      created_at is new when it’s not empty (a human comment can trigger).
    - parse_agent_id (body) is None (no OpenAgents hidden signature) - All machine reviews with signatures (this example just happened)
      Hanging comments,reviewer Backup.refine/iterate/The conflict has been leached.

    Two-barrel superstitions  →  agent never reads its comments to trigger, accurately restores the security subset, orientation of the RFC-0011 side of the read.
    Unable to read comments on RFC-0019 (Auto-Transmit main path is still driven by reviewer gate, which only serves blocked unmounted).
    """
    fresh = [
        comment
        for comment in github.list_comments(pr_number=pr_number)
        if comment.created_at > since and parse_agent_id(body=comment.body) is None
    ]
    return sorted(fresh, key=lambda comment: comment.created_at)


def new_human_comments_on_issue(*, number: int, since: str) -> list[github.Comment]:
    """#Spec-0016/T1: Read side issue - Return to the ”Since New Humanity Review” page, in chronological order.

    with `new_human_comments`（PR The only difference is the re-reading of the source. `github.list_issue_comments`
    （`gh issue view --json comments`）Not `list_comments`（`gh pr view`）。Follow the same hard-barrel:
    - created_at is more than `since` (issue comment state.get_issue_cursor) - History review, last response
      The comments were all filtered out; the since=”any non-empty created_at is new (a trigger for any human comment).
    - parse_agent_id (body) is None (no OpenAgents hidden signature) - All machine comments with signatures (this instance reply,
      The following is a list of the most recent posts on the website of the World Health Organization (WHO) that have been posted on the website:

    The two restraints added that the comment never read itself triggers (issue #149, ”Reaction is the message” closed to the issue page).
    It is identical to the PPR side protection from the cycling semantics. The PR version `new_human_comments` zero changes (zero returns).
    """
    fresh = [
        comment
        for comment in github.list_issue_comments(number=number)
        if comment.created_at > since and parse_agent_id(body=comment.body) is None
    ]
    return sorted(fresh, key=lambda comment: comment.created_at)


def build_claim_note(*, agent_id: str) -> str:
    """Render a signed claim comment for an issue.

    The claim marker identifies the comment and the signature identifies its owner.
    """
    body = f"OpenAgents claimed this issue and is drafting a Spec.\n\n{_CLAIM_MARKER}"
    return sign(body=body, agent_id=agent_id)


def latest_claim(*, comments: list[github.Comment]) -> tuple[str, float] | None:
    """Spec-0049/T2: Parsing the most recent sign-on from the issue review list** (owner_agent_id, age_seconds).

    Pure function (the only ”now” from datetime.now is used to calculate age):
    - Only two comments satisfied when agreeing: `_CLAIM_MARKER` (take-in-and-check-out precheck alignment comments/reviewer
      The decision returns / unsigned human review)** and ** parse_agent_id can remove the owner (attribution).
    - created_at (ISO 8601, dictionary in chronological order)** in these identification notes, returns the latest item** to the owner and
      ”now - created_at” seconds old. Sign None without any valid endorsement.

    Attribution + Fresh Read One: From this basis, the caller (vigil found paragraph at the gate / orchestranter confirmed the surrender)
    ”Isn’t mine” ”is it past?” created_at is empty/ undefeated conservatively agg = 0.0 (previously, prefers to keep another round of the pit)
    The decision is not to be misjudged at the back end of the recovery activity - it is the same source as the discovery that ”the conservative decision not to take evidence is not expired”.
    """
    notes = [
        (comment, owner)
        for comment in comments
        if _CLAIM_MARKER in comment.body
        and (owner := parse_agent_id(body=comment.body)) is not None
    ]
    if not notes:
        return None
    comment, owner = max(notes, key=lambda pair: pair[0].created_at)
    return owner, _claim_age_seconds(created_at=comment.created_at)


def _claim_age_seconds(*, created_at: str) -> float:
    """Spec-0049/T2: Number of seconds from now when you sign created_at (ISO 8601) on your confirmation; empty/unresolved conservative sentence 0.0 (unexpired)."""
    if not created_at:
        return 0.0
    try:
        stamped = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return (datetime.now(UTC) - stamped).total_seconds()


def post_signed_comment(*, pr_number: int, body: str, agent_id: str) -> None:
    """RFC-0011 Decision 4 / Spec-0064/T5: post after stamp + **Sync check and check check and sign after mark** - All ’agents’
    The only export (bound 3: the self-closure of the loop is not to be removed) is the comment.

    Seal-in-the-port logic, keeping github.post_comment in a thin wrap. `sign` always adds a hidden signature to the end of body, so post
    The text must be signed; however, Spec-0064 bound 3 requires ”Sync and verify the missing signature to be completed (not just warm)” - post back to PR.
    A recent comment from the example confirms that the signature is actually on the ground, and in the event of a omission (e.g. external rewriting/cut)** a signature comment** is being prepared to restore the closed ring, and the signature is being replaced by a signature comment.
    The poll_comments filters human comments by signing.
    The omission would have allowed agent to turn his response into a new human commentary, a self-questioning loop -- so it had to close.
    """
    github.post_comment(pr_number=pr_number, body=sign(body=body, agent_id=agent_id))
    _verify_signature_or_fix(pr_number=pr_number, agent_id=agent_id)


def _verify_signature_or_fix(*, pr_number: int, agent_id: str) -> None:
    """Spec-0064/T5: Read back the last comment check-in example of whether the signature has landed; the omission adds a signature comment (bound 3, not just warn).

    Normal Path (`sign` stamped)  →  no-op. Unusual Path (signature stopped/rewritten)  →  Add a strip
    Signing a restoration comment that ensures that a signature comment from this example is available on PR, closed from the loop. Reading/remedial failure swallows (best-effort, etc.)
    No response sent; the github side’s real failure is blocked by per-PR error in the upper guard segment).
    """
    try:
        comments = github.list_comments(pr_number=pr_number)
    except github.GithubError:
        return
    if not comments:
        return
    latest = max(comments, key=lambda comment: comment.created_at)
    if parse_agent_id(body=latest.body) == agent_id:
        return
    try:
        github.post_comment(
            pr_number=pr_number,
            body=sign(
                body="(openagents additional signature: correction of the previous reply to attribution)",
                agent_id=agent_id,
            ),
        )
    except github.GithubError:
        return


def post_signed_comment_on_issue(*, number: int, body: str, agent_id: str) -> None:
    """#Spec-0016/T1: Post after stamp to **issue page** + Sync and check and check for slips and sign - issue only exit for signature return.

    Symmetry with `post_signed_comment` (PR version), the only difference is the `github.issue_comment`
    （`gh issue comment`）Not `post_comment`（`gh pr comment`）Read back and change the tone `list_issue_comments`。
    `sign` Always hides the signature at the end of body, so the text will be signed; Spec-0064 bound 3 requires ”Sync and check the missing signature rule”
    The last comment in the post-issue example confirms that the signature is actually on the ground, and in case of a default**
    A signed comment** closed from the loop (failure to make the next round `new_human_comments_on_issue` new)
    The re-signing is not a fallout (best-effort, does not block the response already sent).
    """
    github.issue_comment(number=number, body=sign(body=body, agent_id=agent_id))
    _verify_signature_or_fix_on_issue(number=number, agent_id=agent_id)


def _verify_signature_or_fix_on_issue(*, number: int, agent_id: str) -> None:
    """#Spec-0016/T1:issue version of the check-back — the last comment with this example is signed no-op, while the omission is supplemented by a signature comment.

    Symmetrical with `_verify_signature_or_fix` (PR version): Read `list_issue_comments`, and sign `issue_comment`.
    Read/refill failure swallows (best-effort, without blocking the response sent; the real failure is being driven by a per-subject error isolation in the upper guard segment).
    """
    try:
        comments = github.list_issue_comments(number=number)
    except github.GithubError:
        return
    if not comments:
        return
    latest = max(comments, key=lambda comment: comment.created_at)
    if parse_agent_id(body=latest.body) == agent_id:
        return
    try:
        github.issue_comment(
            number=number,
            body=sign(
                body="(openagents additional signature: correction of the previous reply to attribution)",
                agent_id=agent_id,
            ),
        )
    except github.GithubError:
        return
