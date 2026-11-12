# RFC-0001
"""Implement the shared forge interface through the GitHub CLI."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
import time
from dataclasses import dataclass
from typing import Any

# `gh pr checks` returns with exit code 8 when there is still check in the CI, stdout remains valid for JSON.
# See gh document: Non-zero exit does not always represent an error, and the exception is set out here.
_GH_CHECKS_PENDING_RETURNCODE = 8

# gh Subprocesses timeout seconds (decision 4: Timeout subprocess.TimeoutExpired, subtotaling to instantaneous error).
_GH_TIMEOUT_SECONDS = 30

# RFC-0010 Decision 3: The limit of the instantaneous error retry and the base figure of the deviation are the constants of the module level (ideology 1: do not include the configuration).
# Count the original call toward the retry limit and use exponential backoff.
_GH_RETRY_MAX_ATTEMPTS = 3
_GH_RETRY_BACKOFF_BASE = 1.0

# RFC-0010 Decision 2: Stderr tag for instant service failure (lowercase matching). Consider it "shrink" - only these
# Service end failure; no business errors such as not found/ already existaries/ no checks reported are never counted.
_GH_TRANSIENT_MARKERS = (
    "http 502",
    "http 503",
    "http 504",
    "bad gateway",
    "gateway timeout",
    "service unavailable",
)

# gh prchecks state take-down group.
_CHECK_FAIL_STATES = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
_CHECK_PASS_STATES = {"SUCCESS", "SKIPPED", "NEUTRAL"}

# RFC-0012: extract value for check-runs API - a collection considered "green" (with _CHECK_PASS_STATES)
# Synonyms, but RESTcheck-runs uses Concrusion field, take value lowercase. The rest conclusion or incomplete green.
_CHECK_RUN_PASS_CONCLUSIONS = {"success", "skipped", "neutral"}

# RFC-0012：gh api It's... owner/repo placeholder——gh It will be automatically replaced with the current repository, without a spelled-in. owner/repo。
_REPO_PLACEHOLDER = "repos/{owner}/{repo}"

# Shared process labels are defined here so callers and forge drivers agree.
DISCOVERY_LABEL: str = "openagents"
APPROVAL_LABEL: str = "rfc-approved"
AUTOMATION_FAILED_LABEL: str = "automation-failed"
# Spec-0039/T1: Mark an issue as dispatched so other workers skip it.
DISPATCH_LABEL: str = "openagents-dispatching"
PROCESS_LABELS: tuple[str, ...] = (
    DISCOVERY_LABEL,
    APPROVAL_LABEL,
    AUTOMATION_FAILED_LABEL,
    DISPATCH_LABEL,
)


class GithubError(Exception):
    """Report a failed GitHub CLI call with an actionable diagnostic."""


@dataclass(frozen=True)
class Issue:
    """Hold the issue fields read by discovery and delivery, including current labels."""

    number: int
    title: str
    body: str
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class PR:
    """Hold the identifying fields of a pull request."""

    number: int
    url: str


@dataclass(frozen=True)
class Comment:
    """Hold a forge comment and its authorship information.

    Sort by the creation timestamp, not the GraphQL ID. Only explicitly
    trusted author associations qualify as maintainers.
    """

    id: str
    author: str
    body: str
    created_at: str
    author_association: str = ""


@dataclass(frozen=True)
class CheckStatus:
    """Hold aggregate CI status and a summary of failing checks."""

    state: str
    failed_logs: list[str]


@dataclass(frozen=True)
class Mergeability:
    """Spec-0022/T1: Mergeable Summary of PR - as if two original fields of GitHub were actually carried, Zero Business Decision.

    : GitHub `mergeable` original value - MERGEABELE/CONFLICTING/UNKNOWN.
    merge_state_status: GitHub `mergeStateStatus` original value - CLEAN / DIRTY / BLONKED/
        BeHIND / UNKNOWN / ... (maintains a capital string, not at the infra-merger or re-bull).

    Reads the caller by field name and avoids it with frozen dataclass (similar to CheckStatus) instead of nud tuple/dict
    Locational ambiguity; the determination of which combination is not merged is left to the caller (ideology 10:github is thin gh seal).
    """

    mergeable: str
    merge_state_status: str


def _is_transient_gh_error(*, stderr: str) -> bool:
    """RFC-0010 Decision 2: Stderr Hit Time Service Fault Mark (HTTP 502 /503/504/ Bad)
    Gateway / Gateway Timeout / Service Unaviilable. Pure function, easy to measure."""
    lowered = stderr.lower()
    return any(marker in lowered for marker in _GH_TRANSIENT_MARKERS)


def _run_gh(args: list[str], *, allow_returncodes: set[int]) -> subprocess.CompletedProcess[str]:
    """Runs gh sub-command; dumps GithubError when returning non-zero and not in allow_returncodes.

    RFC-0010: An instant error (stderr hit _GH_TRANSIENT_MARKERS, or subprocess.TimeoutExpired)
    Refrain from retrying by index, up to _GH_RETRY_MAX_ATTEMPTS; non-stop error (including allow_returncodes)
    Released exit codes, not found business errors) return/show immediately, never try again. After re-drive (including time out)
    Unified launch GithubError - No change in the type of external signature/return, zero change in all calls (decision 1/4).
    """
    for attempt in range(1, _GH_RETRY_MAX_ATTEMPTS + 1):
        try:
            result = subprocess.run(
                ["gh", *args],
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            # Decision 4: Timeout is considered a instant error and retried; after exhaustion, it is converted to GithubError (non-TimeoutExpired).
            reason = f"gh {' '.join(args)} Timeout (Performance){_GH_TIMEOUT_SECONDS}s）"
            if attempt < _GH_RETRY_MAX_ATTEMPTS:
                time.sleep(_GH_RETRY_BACKOFF_BASE * 2 ** (attempt - 1))
                continue
            raise GithubError(reason) from None
        if result.returncode != 0 and result.returncode not in allow_returncodes:
            reason = result.stderr.strip() or f"gh {' '.join(args)} Return Code {result.returncode}"
            # Decision 2: Refrain from retrying when there is only a moment of error and there are still many re-tests; business error/last attempt is immediately dropped.
            if _is_transient_gh_error(stderr=result.stderr) and attempt < _GH_RETRY_MAX_ATTEMPTS:
                time.sleep(_GH_RETRY_BACKOFF_BASE * 2 ** (attempt - 1))
                continue
            raise GithubError(reason)
        return result
    # Inaccessible: return, continue, or raise (reserved to meet type check).
    raise GithubError(f"gh {' '.join(args)} We’re running out of re-testing.")


def _gh_json(args: list[str], *, allow_returncodes: set[int]) -> Any:
    """Run gh sub-command and resolve stdout to JSON; parsing failed to throw GithubError."""
    result = _run_gh(args, allow_returncodes=allow_returncodes)
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        raise GithubError(f"Could not parse gh output as JSON:{exc}") from exc


def create_repo(*, name: str, private: bool) -> str:
    """RFC-0001 T3: Create a new remote with `gh repo create`, return remote url.

    Private decides --private/ --public; for call to config.ensure_project for cold startup.
    """
    visibility = "--private" if private else "--public"
    result = _run_gh(["repo", "create", name, visibility], allow_returncodes=set())
    url = result.stdout.strip()
    if not url:
        raise GithubError("gh repo state returns return url")
    return url


def get_issue(*, number: int) -> Issue:
    """RFC-0001 T3：`gh issue view <n> --json number,title,body,labels`。

    Spec-0039/T1: --json Add labels field and resolve Issue.labels (Recognition of Condensation Gate Expedition), available
    number/title/body resolves the same.
    """
    data = _gh_json(
        ["issue", "view", str(number), "--json", "number,title,body,labels"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh issue view returned to unexpected structure")
    return Issue(
        number=int(data["number"]),
        title=data.get("title") or "",
        body=data.get("body") or "",
        labels=_parse_label_names(raw=data),
    )


def _parse_label_names(*, raw: dict[str, Any]) -> tuple[str, ...]:
    """Spec-0039/T1: From gh `--json labels` It’s... `[{"name": ...}, ...]` Parsing the label name bytes.

    gh’s labels structure is the object array (each with name/color/description); only name, missing/None is here
    Allows errors to be empty. get_issue/ list_issues shares to ensure that Issue.labels resolves a single source.
    """
    return tuple((label or {}).get("name") or "" for label in raw.get("labels") or [])


def list_issues(*, labels: list[str], state: str = "open") -> list[Issue]:
    """RFC-0004 T1: Lists (which can be controlled by label doors) issueue for the vigil watchman to find new issue.

    Go `gh issue list --state <state> [--label L ...] --json number,title,body`.
    Labels are empty for not filtering by tab (list all issues of this state); multiple labels by gh to
    Re-use the gh-sub-process wrap and existing Issue for decision 3
    Data model, no new data type (CLAUDE.md concept 1).
    """
    args = ["issue", "list", "--state", state, "--json", "number,title,body,labels"]
    for label in labels:
        args += ["--label", label]
    data = _gh_json(args, allow_returncodes=set())
    rows = data if isinstance(data, list) else []
    # Spec-0039/T1: --json Add labels and parse them so that the 3nd of the found sector can read issue.labels quick-check the tags.
    return [
        Issue(
            number=int(raw["number"]),
            title=raw.get("title") or "",
            body=raw.get("body") or "",
            labels=_parse_label_names(raw=raw),
        )
        for raw in rows
    ]


def create_issue(*, title: str, body: str, labels: list[str]) -> Issue:
    """Create a GitHub issue via gh and return its minimal projection.

    RFC-0002 T1：`gh issue create --title <title> --body <body> [--label <l> ...]`。

    Go gh-subprocesses in line with Decision 3 and reuse _run_gh bugs; gh returns new issue at stdout
    url (form .../issues/<n>), unsolved number number from the end, and assembled in title/body as imported
    Existing Issue returns (decision 2: no new data type added).
    """
    # 1. Grouping gh parameter: title/body shall be a strip, labels expands to --label
    args = ["issue", "create", "--title", title, "--body", body]
    for label in labels:
        args += ["--label", label]

    # 2. Call gh; Non-zero exit by _run_gh
    result = _run_gh(args, allow_returncodes=set())

    # 3. Parsing number from the end of issue URL of stdout
    url = result.stdout.strip()
    number = _parse_issue_number(url=url)
    if number is None:
        raise GithubError(f"Could not output issue number:{url!r}")
    return Issue(number=number, title=title, body=body)


def ensure_label(*, name: str, color: str = "ededed", description: str = "") -> None:
    """RFC-0002 Decision 6: Ensure that the repository has a label named name for `gh issue create --label`.

    `gh issue create --label <L>` requests that <L> pre-existing or otherwise ”cand not add label: ...not found”.
    Since decision 5 compels the discovery labels to exist first: `gh label create`
    Create; gh exits with non-zero already existing and reports ”already exists” - swallowing is considered successful,** does not cover** existing colours/descriptions
    (Same ”no checks reported” style as check_status. Other gh errors usually throw GithubError.
    """
    try:
        _run_gh(
            ["label", "create", name, "--color", color, "--description", description],
            allow_returncodes=set(),
        )
    except GithubError as exc:
        if "already exists" in str(exc).lower():
            return
        raise


def create_pr(*, branch: str, title: str, body: str, base: str = "main", draft: bool = False) -> PR:
    """Open a PR and parse its number and URL; allow draft and base overrides."""
    args = ["pr", "create", "--head", branch, "--base", base, "--title", title, "--body", body]
    if draft:
        args.append("--draft")
    result = _run_gh(args, allow_returncodes=set())
    url = result.stdout.strip()
    number = _parse_pr_number(url=url)
    if number is None:
        raise GithubError(f"Could not parse PR number:{url!r}")
    return PR(number=number, url=url)


def find_pr_by_branch(*, branch: str) -> PR | None:
    """RFC-0003 Decision 8: Check for the current open PR (`gh pr list --head <branch>`) of a branch.

    Reuses a PR for the Solve renewal/restoration, avoiding repetition of `gh pr create`; no one returns None.
    """
    data = _gh_json(
        ["pr", "list", "--head", branch, "--state", "open", "--json", "number,url", "--limit", "1"],
        allow_returncodes=set(),
    )
    rows = data if isinstance(data, list) else []
    if not rows:
        return None
    first = rows[0]
    number = first.get("number")
    url = first.get("url") or ""
    if number is None:
        return None
    return PR(number=int(number), url=url)


def pr_for_branch(*, branch: str) -> PR | None:
    """On a branch** the latest PR, open-ended** (open /merged / closed); never added None.

    # Spec-0065/T2: `_sense` must use it, not `find_pr_by_branch` (the latter only check open). A PR is merged from
    # Open list disappears # — if you follow the open-only search, the next round of the combined** ** will read this issue as “not yet PR”,
    # So walk in branch four and open a PR and redo the same issue. Meged is the end condition for `_classify`, which can only be terminated from
    ”What’s the state of that PR now?” So here you have to see the merged PR.
    # `--state all` + `--limit 1`: gh press the old line and take the latest one (one branch corresponds to the issue, one in practice).
    """
    data = _gh_json(
        [
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "all",
            "--json",
            "number,url",
            "--limit",
            "1",
        ],
        allow_returncodes=set(),
    )
    rows = data if isinstance(data, list) else []
    if not rows or rows[0].get("number") is None:
        return None
    return PR(number=int(rows[0]["number"]), url=rows[0].get("url") or "")


def list_comments(*, pr_number: int) -> list[Comment]:
    """RFC-0001 T3: `gh pr view <n> --json comments`, parsing as the Comment list.

    A message id is a node id string; also take createdAt to determine new comments by time.
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "comments"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view returned unexpected structures")
    return _parse_comments(data=data)


def _parse_comments(*, data: dict) -> list[Comment]:
    """Public Parsing for `--json comments`: Comment id is a node id string; createdat for new comments to be judged by time.

    Spec-0065/T2: Also parse `authorAssociation` - vigil access gate
    Recognize the maintainer. Leave a blank string when a field is missing (fail-closed: comments that cannot be read are not boarded).
    """
    comments: list[Comment] = []
    for raw in data.get("comments") or []:
        author = (raw.get("author") or {}).get("login") or ""
        comments.append(
            Comment(
                id=str(raw.get("id") or ""),
                author=author,
                body=raw.get("body") or "",
                created_at=raw.get("createdAt") or "",
                author_association=str(raw.get("authorAssociation") or ""),
            )
        )
    return comments


def post_comment(*, pr_number: int, body: str) -> None:
    """RFC-0001 T3：`gh pr comment <n> --body <body>`。"""
    _run_gh(
        ["pr", "comment", str(pr_number), "--body", body],
        allow_returncodes=set(),
    )


def issue_comment(*, number: int, body: str) -> None:
    """Spec-0043/T1: Append a comment to issue (`gh issue comment <number> --body <body>`).

    post_comment Go `gh pr comment` (PR special) - - But the issuecheck stops the issue and it’s not frozen yet **
    PR**, no comment. Add a symmetric assue level exit, go with issue_add_label / issue_remove_label
    `gh issue edit/view` is a co-column of the issuer class. Signature is covered by the caller (orchestrator via identity.sign)
    — This function maintains ”a thin wrap for gh without business logic” (idea 10). Failed to throw GithubError by _run_gh
    (Show RFC-0010 again with an instant error. Do not change post_comment and any existing function (no behavior change).
    """
    _run_gh(
        ["issue", "comment", str(number), "--body", body],
        allow_returncodes=set(),
    )


def list_issue_comments(*, number: int) -> list[Comment]:
    """Spec-0049/T1: Read all comments on the issue (`gh issue view <n> --json comments`).

    Symmetric with list_comments (PR, walk `gh pr view`), is the issue-class reading of the original language - recognition to read again
    The ”Sign and Sign” comment on the status/age of the issue (identity.latest_claim consumption).
    Structures with author.login / body / createdAt, projecting by article into an existingComment (id is node id string);
    created_at in order, not in id sorting. Failed to be _gh_json by GithubError.
    """
    data = _gh_json(
        ["issue", "view", str(number), "--json", "comments"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh issue view returned to unexpected structure")
    return _parse_comments(
        data=data
    )  # Spec-0065/T2: Share the resolution with list_comments, do not leave two copies


def mark_ready(*, pr_number: int) -> None:
    """RFC-0005 T3 (Decision 2: Revert Draft PR (`gh pr ready <n>`).

    The code is used after Implement has finished, which converts the draft PR that carries RFC into a formally reversible code.
    """
    _run_gh(["pr", "ready", str(pr_number)], allow_returncodes=set())


def has_label(*, pr_number: int, name: str) -> bool:
    """RFC-0005 T3 (decision 4): Whether PR should carry a label (`gh pr view <n> --json labels`).

    Message-level recognition of approval signals (refc-approved tags) - labels are structured signals and are not confused with discussion comments.
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "labels"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view returned unexpected structures")
    labels = data.get("labels") or []
    return any((label or {}).get("name") == name for label in labels)


def merge_pr(*, pr_number: int, method: str = "merge", head_sha: str = "") -> None:
    """Merge the given PR with the requested method and candidate head guard."""
    args = ["pr", "merge", str(pr_number), f"--{method}"]
    # Spec-0017 recovery: bind the write itself, not only the earlier approval check.
    if head_sha:
        args.extend(["--match-head-commit", head_sha])
    _run_gh(args, allow_returncodes=set())


def merge_command_text(*, pr_number: int, head_sha: str = "") -> str:
    """Spec-0074/T1:merger agent command text for combining actions - GitHub side is an existing gh command (behaviour change zero).

    merger Platform command parameter for the hint is as $merge_command After placeholder, by stages.merge (a) Injected by this function;
    The same name function for Gitea driver returns `openagents merge-pr --pr N` (token process to stay in driver without hints).
    """
    suffix = f" --match-head-commit {shlex.quote(head_sha)}" if head_sha else ""
    return f"gh pr merge {pr_number} --merge{suffix}"


def merge_verify_command_text(*, pr_number: int, head_sha: str = "") -> str:
    """The text of the command for the Spec-0074/T1:merger agent to verify the merger completion - the output containing MERGED is considered to be merged."""
    return f"gh pr view {pr_number} --json state"


def add_label(*, pr_number: int, name: str) -> None:
    """RFC-0012 Decision 1/3: Tag PR (`gh pr edit <n> --add-label <name>`).

    For automatic rifc-approved (RFC full vote PASS) or for automatic utomination-failed (decision 5).
    Symmetric with has_label: The label is a structured signal and is not confused with the discussion comment.
    """
    _run_gh(["pr", "edit", str(pr_number), "--add-label", name], allow_returncodes=set())


def remove_label(*, pr_number: int, name: str) -> None:
    """Remove a PR label, treating an already absent label as a no-op.
    Spec-0032/T2.
    """
    try:
        _run_gh(["pr", "edit", str(pr_number), "--remove-label", name], allow_returncodes=set())
    except GithubError as exc:
        if _is_label_absent(reason=str(exc)):
            return
        raise


def issue_add_label(*, number: int, name: str) -> None:
    """Spec-0039/T1: Tag the issue (`gh issue edit <n> --add-label <name>`), symmetry with add_label.

    add_label / remove_label / has_label all used in **PR** (`gh pr edit/view`) and found segment
    The recipient is **issue**, so a group of `gh issue edit/view`-class is used to run the issue level.

    Spec-0049/T1: Recognition of the bid to change from this function** to this function** add** (remove-then-add STamp not retired) -
    For those who already have the label issue Again. add yes gh Side no-op、**Do Not Generate labeled/unlabeled Events**  Get rid of the root
    Physical source of ”reverse each other’s tags” at both ends; retrofitted by ”sign and sign” comments on age
    (identity.latest_claim). Failed to throw GithubError by _run_gh.
    """
    _run_gh(["issue", "edit", str(number), "--add-label", name], allow_returncodes=set())


def issue_remove_label(*, number: int, name: str) -> None:
    """Spec-0039/T1: Remove the tag (`gh issue edit <n> --remove-label <name>`) on the issue.

    Symmetric with remove_label (PR version), re-use the same _is_label_absent Qim, etc. recognition: tab book is off-time gh to
    Not found / does not have... label / does not exist / swallow as success
    (PR clears the claim tag after it has been removed or people remove it manually without fault). Other gh errors are routinely thrown at GithubError.
    """
    try:
        _run_gh(["issue", "edit", str(number), "--remove-label", name], allow_returncodes=set())
    except GithubError as exc:
        if _is_label_absent(reason=str(exc)):
            return
        raise


def _is_label_absent(*, reason: str) -> bool:
    """Spec-0032/T2: remove_label ”not labeled” and ”not identified” - determines to be ”shrink” (symmetrically with _is_not_found).

    gh Text to remove a non-zero label from a PR
    or ”label does not exist / pull request does not have... label”; different size, lower case
    Substring matches. Consider only two types of business results, and all other gh errors are missed and thrown up the line.
    """
    lowered = reason.lower()
    return "not found" in lowered or "does not have" in lowered or "does not exist" in lowered


def close_issue(*, number: int) -> None:
    """Close the issue; tolerate an already closed or missing issue."""
    try:
        _run_gh(["issue", "close", str(number)], allow_returncodes=set())
    except GithubError as exc:
        if _is_already_closed_or_absent(reason=str(exc)):
            return  # Assue closed / does not exist No-op
        raise


def ensure_prerequisites() -> None:
    """Spec-0023/T1: Zips and so on ensure process structure prerequisite position: All process labels.

    Single-dip source - a centralized statement of ”the process depends on which prerequisite” and is unified by init/release/vigil 3-entry
    Call to eliminate fragmented and incomplete access walls (lack) automation-failed/rfc-approved Tag to add_label Report
    not found）。

    test branch after decommissioning (Spec-0023) the daily base is replaced by a constant default branch main without any branch
    Self-initiation - The ensure_branch that originally built the test branch in a back-to-back field was removed, and this function is reduced to a pre-established process label.
    New, existing, no-op: only ensure_label with a stint, do not create any new tolerance errors (stangular, etc.)
    An error is made to try RFC-0010, orready lists all of them by ensure_label/ _run_gh.
    """
    for label in PROCESS_LABELS:
        ensure_label(name=label)


def branch_ci_green(*, branch: str) -> bool:
    """Check the conclusions for the branch head; incomplete checks do not pass.
    Spec-0023/T1.
    """
    runs = _gh_json(
        ["api", f"{_REPO_PLACEHOLDER}/commits/{branch}/check-runs", "--jq", ".check_runs"],
        allow_returncodes=set(),
    )
    rows = runs if isinstance(runs, list) else []
    for run in rows:
        if str(run.get("status") or "").lower() != "completed":
            return False
        if str(run.get("conclusion") or "").lower() not in _CHECK_RUN_PASS_CONCLUSIONS:
            return False
    return True


def _is_not_found(*, reason: str) -> bool:
    """gh api’s ”Resource does not exist” recognition (404 / not found) - for _is_already_closed_or_absent reuse."""
    lowered = reason.lower()
    return "not found" in lowered or "404" in lowered


def _is_already_closed_or_absent(*, reason: str) -> bool:
    """RFC-0017 Decision 2: close_issue ”No-op” recognition - issue closed or non-existent.

    Deciding to be ”Small” (similar to _is_not_found / _is_already_up_to_date): Only two types of business
    gh issue closes on closed issue ”already closed”; on non-existent issue left on GramphQL,
    ”Could not report to an Issue...” (without ”not found” ) so outside _is_not_found
    And ”cand not resolve.” Other gh mistakes are never hit, and they are thrown up.
    """
    lowered = reason.lower()
    if "already closed" in lowered or "could not resolve" in lowered:
        return True
    return _is_not_found(reason=reason)


def check_status(*, pr_number: int) -> CheckStatus:
    """Aggregate gh check results, giving failures precedence over pending checks."""
    try:
        data = _gh_json(
            ["pr", "checks", str(pr_number), "--json", "name,state,link"],
            allow_returncodes={_GH_CHECKS_PENDING_RETURNCODE},
        )
    except GithubError as exc:
        # The warehouse is not configured for any CI when gh exits in non-zero and reports "no checks reported" - deemed passed.
        if "no checks reported" in str(exc).lower():
            return CheckStatus(state="pass", failed_logs=[])
        raise
    checks = data if isinstance(data, list) else []
    return _classify_checks(checks=checks)


def is_merged(*, pr_number: int) -> bool:
    """RFC-0001 T3 (Decision #8): PR whether or not it is merged (`gh pr view <n> --json state`).

    For presentation/message determination of termination conditions: PR Merges will place corresponding issue donee.
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "state"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view returned unexpected structures")
    return str(data.get("state") or "").upper() == "MERGED"


def mergeability(*, pr_number: int) -> Mergeability:
    """Spec-0022/T1: Check PR amalgamation (`gh pr view <n> --json mergeable,mergeStateStatus`).

    Structure mirror is_merged / is_closed: Run gh (with RFC-0010 in a flash) at the single point of entry _gh_json, and try again in a moment.
    Retrieving two fields at a time (same snapshot, one round trip, and avoiding reading inconsistent middle). Only replying to GitHub
    Original capital string, without any sub-or Boolean determination - ”What combination is a conflict” is determined by the caller (Spec-0022/T2).

    UNKNOWN (GitHub walk is not yet complete, just push is common) is ** a legal return value** and is not considered an error by the base level.
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "mergeable,mergeStateStatus"],
        allow_returncodes=set(),
    )
    # Non-dect or missing field is unexpected structure (deficient field  →  UNKNOWN: the latter is a legitimate upper case value returned by gh) and is not a valid upper case value.
    # Revert as it is; the former is structurally abnormal, compared to is_merged throw GithubError.
    if (
        not isinstance(data, dict)
        or data.get("mergeable") is None
        or data.get("mergeStateStatus") is None
    ):
        raise GithubError("gh pr view returned unexpected structures")
    return Mergeability(
        mergeable=str(data["mergeable"]).upper(),
        merge_state_status=str(data["mergeStateStatus"]).upper(),
    )


def pr_head_branch(*, pr_number: int) -> str:
    """Asset #48: Take the head branch name of PR (`gh pr view <n> --json headRefName`).

    For index conflict self-resort at local checkout branch, re-suppling Overview after merging base.
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "headRefName"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict) or not data.get("headRefName"):
        raise GithubError("gh pr view not returned headrefName")
    return str(data["headRefName"])


def is_closed(*, pr_number: int) -> bool:
    """RFC-0006: Whether PR is closed but not merged (`gh pr view <n> --json state` = = ”CLOSED”).

    For the message level to recognize ”persons voluntarily shut down” as an end signal: symmetrical with is_merged - GitHub PR state has
    OPEN / CLOSED / MERGED, tri-state and mutually exclusive, merged PR state is MERGED (not counting closed).
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "state"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view returned unexpected structures")
    return str(data.get("state") or "").upper() == "CLOSED"


def is_open(*, pr_number: int) -> bool:
    """Spec-0042/T2: PR is currently OPEN (`gh pr view <n> --json state`= ”OPEN”).

    The state of symmetric is_merged/is_closed - GitHub PR has OPEN/CLOSED/MERGED three-state and one-sided.
    The ”reopen” for the message layer: Locally set-up run, the PR is to be reopened if it is re-open on GitHub.
    So you can revive the run (close, opposite to irreversible merged). No change to the existing function (no behavior change).
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "state"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view returned unexpected structures")
    return str(data.get("state") or "").upper() == "OPEN"


def is_draft(*, pr_number: int) -> bool:
    """Spec-0042/T2: PR is currently draft (`gh pr view <n> --json isDraft`).

    The news layer is available at the backen Easter extrapolation stage: draft PR (RFC unapproved, code unwritten) resuscitation to refc-review;
    Pr has_label (rfc-approved) has been restored to pr-open. It isDraft/ Non-Ber is considered as an alternate witness.
    Unexpected structure (cf. is_closed throw GithubError). No function (zero regression) is changed.
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "isDraft"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict) or not isinstance(data.get("isDraft"), bool):
        raise GithubError("gh pr view returned unexpected structures")
    return data["isDraft"]


def list_open_prs() -> list[PR]:
    """RFC-0009 T1: Lists all open PR (`gh pr list --state open --json number,url`) currently in the repository.

    Based on GitHub, the coverage is more complete than that of local State, which only includes self-built run by openages, and is built manually.
    PR is also established - for the zip synchronizing polle cycle to list the open PRs currently pending. No return is possible.
    Reuse existing PR data class and _gh_json cover without adding data type (CLAUDE.md concept 1).
    """
    data = _gh_json(
        ["pr", "list", "--state", "open", "--json", "number,url"],
        allow_returncodes=set(),
    )
    rows = data if isinstance(data, list) else []
    prs: list[PR] = []
    for raw in rows:
        number = raw.get("number")
        if number is None:
            continue
        prs.append(PR(number=int(number), url=raw.get("url") or ""))
    return prs


def update_branch(*, pr_number: int, rebase: bool = False) -> bool:
    """RFC-0009 T1 (decision 2/5): join the latest base (main) into the PR branch (`gh pr update-branch <n>`).

    default walker mass (no rewrite, no force-push, suitable for unmanned loop); rebase=True Add
    `--rebase` is changed to rebase. This update will generate a synchronize event on PR, triggering its CI runback.

    Returns True means branch has been updated; returns False means ”no-op-gh” is ”new” with base
    & & & & & & & & & & & & & & & ensure_label
    ”already exists”, ”no checks reported” check_status, same wrong-minded style, decision-making 5.
    The conflict or other failure is routinely thrown at GithubError for the zip-sync caller (messes amalgamation pre-screening) to capture post-message messages (decision 4).
    """
    args = ["pr", "update-branch", str(pr_number)]
    if rebase:
        args.append("--rebase")
    try:
        _run_gh(args, allow_returncodes=set())
    except GithubError as exc:
        if _is_already_up_to_date(reason=str(exc)):
            return False
        raise
    return True


def code_fingerprint(
    *, pr_number: int, exclude_paths: tuple[str, ...] = ("docs/e2e-results/",)
) -> str:
    """Spec-0053/T2 (Spec-0055/T5 plus exclude_paths): Take a net diff fingerprint of PR relative to its base.

    `gh pr diff` returns the three-point calculation (base...head)unified diff - ”This PR adds to base
    What? It’s ”just base forward, PR itself unchanged” (e.g. update_branch without conflict to join the main) and it’s not changed by word.
    So the correct calibration of the sticky short circuit (Spec-0053) for ”Code state changed” instead of head tree SHA.
    lgtm store_tree_hash。

    Spec-0055/T5: `exclude_paths` Remove **Flended Blocks from Diff** (default exclusion of `docs/e2e-results/`)
    And Hashi -- keep the ** source code** fingerprinting to avoid e2e & & nicky being evidenced by **
    Self-trigger rerun (see Spec-0055 for key to condensation). The emptiness group is not excluded (old calibre).

    This function is a thin (ideology 10) for gh: do ”diff + clip the evidence box + fixed Hash” only, without ”doesn’t need short circuits”
    Business decision. gh malfunction (not zero exit throw GithubError) or (after elimination) empty output returns ”fail-open” (fail-open): Caller-in-empty string
    As usual, snicky never skips on the basis of ”no fingerprints.”
    """
    try:
        result = _run_gh(["pr", "diff", str(pr_number)], allow_returncodes=set())
    except GithubError:
        return ""
    diff = result.stdout or ""
    if exclude_paths:
        diff = _strip_diff_file_blocks(diff=diff, exclude_paths=exclude_paths)
    if not diff.strip():
        return ""
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def _strip_diff_file_blocks(*, diff: str, exclude_paths: tuple[str, ...]) -> str:
    """Spec-0055/T5: Remove the entire file block of `b/<path>` that fell on exclude_paths prefix from the UNified diff.

    gint diff picks up each block of file with `diff --git a/<path> b/<path>`; clicks these lines and discards b blocks with any prefix in the path.
    The rest of the original is spelled back. Pure string processing, no side effects (for ease of single measurement). The foreword (unusual) before the head block is retained together with ”no attribution”.
    """
    lines = diff.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("diff --git "):
            # Whether the path after b/ is excluded; the failure of the resolution is conservatively retained by "not excluding " .
            parts = line.split(" b/", 1)
            b_path = parts[1].rstrip("\n") if len(parts) == 2 else ""
            skipping = any(b_path.startswith(prefix) for prefix in exclude_paths)
        if not skipping:
            kept.append(line)
    return "".join(kept)


def _is_already_up_to_date(*, reason: str) -> bool:
    """gh update-branch’s ”subsection is the latest” special case recognition (decision 5).

    gh This is not zero, and the text is roughly ”branch is already up to date” ; case/hyphenation is different,
    When you are in a lower case, click a substring, which distinguishes you from real errors such as conflict.
    """
    lowered = reason.lower()
    return "up to date" in lowered or "up-to-date" in lowered


def _parse_pr_number(*, url: str) -> int | None:
    """Parsing PR number; failed to return None from the end of PR url, which is like .../pull/<n>."""
    return _parse_number_after(url=url, marker="/pull/")


def _parse_issue_number(*, url: str) -> int | None:
    """RFC-0002 T1: parsed number number from the end of the issue url in shape .../issues/<n>; failed to return to None."""
    return _parse_number_after(url=url, marker="/issues/")


def _parse_number_after(*, url: str, marker: str) -> int | None:
    """Parsing the whole number of numbers from the beginning of the marker in the url; no or non-number returns the Noone."""
    idx = url.rfind(marker)
    if idx == -1:
        return None
    tail = url[idx + len(marker) :].strip("/").split("/", 1)[0]
    if not tail.isdigit():
        return None
    return int(tail)


def _classify_checks(*, checks: list[dict[str, Any]]) -> CheckStatus:
    """The original list of gh prchecks is classified as CheckStatus."""
    failed_logs: list[str] = []
    has_pending = False
    for check in checks:
        state = str(check.get("state") or "").upper()
        if state in _CHECK_FAIL_STATES:
            name = check.get("name") or "unknown"
            link = check.get("link") or ""
            failed_logs.append(f"{name} [{state}] {link}".strip())
        elif state not in _CHECK_PASS_STATES:
            has_pending = True
    if failed_logs:
        return CheckStatus(state="fail", failed_logs=failed_logs)
    if has_pending:
        return CheckStatus(state="pending", failed_logs=[])
    return CheckStatus(state="pass", failed_logs=[])


# --------------------------------------------------------------------------------------------------
# Spec-0065/T2: level-triggered `_sense` needs four types of primary reading - PR snapshots (including headsha / label),
# check Scrap (incl.)**Count**And the beginning time,issue Primary dependency (%)blocked_by）。Still thin. gh Encapsulated: Only received as received GitHub
# Fields, zero business decisions ( "Zero check count as waiting CI" "What kind of conflict is determined by recipes.vigil").
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PRSnapshot:
    """Hold PR head, state, mergeability, and draft status from one forge read."""

    number: int
    state: str
    head_sha: str
    labels: tuple[str, ...]
    mergeable: str
    merge_state_status: str
    head_pushed_at: str
    is_draft: bool = (
        False  # Spec-0017/T1: draft to Snap fact (Line Default False, avoid Spec-0031 fake break)
    )


@dataclass(frozen=True)
class CheckSnapshot:
    """Hold aggregate check status, check count, and the latest check start time."""

    state: str  # Pass lid pending (same as CheckStatus.state)
    count: int
    latest_started_at: str


@dataclass(frozen=True)
class Blocker:
    """The back end of the issue `blocked_by`: the issue that stands in the way of the current issue.

    Reply to the `state`, so get the ”side” and ”blocker off” at once and calculate `deps_done` directly, without a second round
    Query. (https://docs.github.com/en/rest/issues/issue-dependencies))
    """

    number: int
    state: str  # OPEN  →  CLOSED (original capital)


def pr_snapshot(*, pr_number: int) -> PRSnapshot:
    """Spec-0065/T2: A `gh pr view` to retrieve the state / head share/ labels / massable / head push time of PR."""
    data = _gh_json(
        [
            "pr",
            "view",
            str(pr_number),
            "--json",
            "number,state,headRefOid,labels,mergeable,mergeStateStatus,commits,isDraft",
        ],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict) or data.get("number") is None:
        raise GithubError("gh pr view returned unexpected structures")
    return PRSnapshot(
        number=int(data["number"]),
        state=str(data.get("state") or "").upper(),
        head_sha=str(data.get("headRefOid") or ""),
        labels=_parse_label_names(raw=data),
        mergeable=str(data.get("mergeable") or "UNKNOWN").upper(),
        merge_state_status=str(data.get("mergeStateStatus") or "UNKNOWN").upper(),
        head_pushed_at=_head_committed_at(commits=data.get("commits")),
        # Spec-0017/T1: isDraft read with the rest of the current state; true/false/ is missing/ non-bull  →  Default False (relationships against is_draft).
        is_draft=data.get("isDraft") is True,
    )


def _head_committed_at(*, commits: Any) -> str:
    """PR It’s... commits List → End of article (i.e. head）It’s... `committedDate`;empty/Abnormal structure → Empty strings (the watchdogs do not look at the door on this basis)."""
    if not isinstance(commits, list) or not commits:
        return ""
    last = commits[-1]
    return str(last.get("committedDate") or "") if isinstance(last, dict) else ""


def check_snapshot(*, pr_number: int) -> CheckSnapshot:
    """Read check status, count, and latest start time for the current PR head.
    Spec-0065/T2.
    """
    try:
        data = _gh_json(
            ["pr", "checks", str(pr_number), "--json", "name,state,link,startedAt"],
            allow_returncodes={_GH_CHECKS_PENDING_RETURNCODE},
        )
    except GithubError as exc:
        if "no checks reported" in str(exc).lower():
            return CheckSnapshot(state="pass", count=0, latest_started_at="")
        raise
    checks = data if isinstance(data, list) else []
    aggregate = _classify_checks(checks=checks)
    started = [str(check.get("startedAt") or "") for check in checks]
    return CheckSnapshot(
        state=aggregate.state,
        count=len(checks),
        latest_started_at=max(started) if started else "",
    )


def check_logs(*, pr_number: int) -> list[str]:
    """Return a summary of failed checks at the current head for the implementer.
    Spec-0065/T2.
    """
    return check_status(pr_number=pr_number).failed_logs


def issue_rest_id(*, number: int) -> int:
    """Spec-0065/T2: Take issue id (`POST …/dependencies/blocked_by` requests it, not number)."""
    data = _gh_json(
        ["api", f"{_REPO_PLACEHOLDER}/issues/{number}", "--jq", "{id: .id}"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict) or data.get("id") is None:
        raise GithubError(f"# gh api not back issue #{number} id")
    return int(data["id"])


def list_blocked_by(*, number: int) -> list[Blocker]:
    """Spec-0065/T2: Native Dependency Edge for Readissue (`GET …/issues/{n}/dependencies/blocked_by`, 2025-08 GA).

    Reply to `state` with blocker, calling at once and giving ”Zid” and ”blocker off” at the same time. The repository does not open this feature/ no side
    returns [ ] (404 is empty, no drops - dependency is optional and its absence means only ”no dependence”.
    """
    try:
        data = _gh_json(
            ["api", f"{_REPO_PLACEHOLDER}/issues/{number}/dependencies/blocked_by"],
            allow_returncodes=set(),
        )
    except GithubError as exc:
        if _is_not_found(reason=str(exc)):
            return []
        raise
    rows = data if isinstance(data, list) else []
    blockers: list[Blocker] = []
    for raw in rows:
        if not isinstance(raw, dict) or raw.get("number") is None:
            continue
        blockers.append(
            Blocker(number=int(raw["number"]), state=str(raw.get("state") or "").upper())
        )
    return blockers


def add_blocked_by(*, number: int, blocker_number: int) -> None:
    """Spec-0065/T2: Puts a parent dependent side (`POST …/issues/{n}/dependencies/blocked_by`) on the issue.

    The requested body wants **REST id** (not issue number) of clocker. So `issue_rest_id` is changed. The border already exists
    . GitHub returns 4xx - Considers swallowing as success (single, same missty style as `ensure_label` swallowing ”already exists”).
    """
    blocker_id = issue_rest_id(number=blocker_number)
    try:
        _run_gh(
            [
                "api",
                "--method",
                "POST",
                f"{_REPO_PLACEHOLDER}/issues/{number}/dependencies/blocked_by",
                # Spec-0065/T2: It must be `-F` (type extrapolation JSON number) and not `-f` (always when stringing).
                # issue_id for dependencias API declares it as integer, stringing 422 and 422 not below
                # already/duplicate white list Z-X-rays can't fall on one side of the line.
                "-F",
                f"issue_id={blocker_id}",
            ],
            allow_returncodes=set(),
        )
    except GithubError as exc:
        reason = str(exc).lower()
        if "already" in reason or "duplicate" in reason:
            return
        raise
