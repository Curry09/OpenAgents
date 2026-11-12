# Spec-0074/T2: utils.gitea - github.py Publicly-named Gitea Driver (/api/v1, stdlib urllib zero-dependent).

"""Implement the shared forge interface using Gitea REST endpoints.

Use the shared data types and error contract. Read tokens from the configured
environment variable. The HTTP helper centralizes authentication, timeouts,
and transient retries. Gitea PR comments use issue endpoints. Where native
metadata differs from GitHub, apply the mapping documented in Spec-0074.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

# Spec-0074/T2: Reuse Public Compact——Data class/Error/Process Label Constants and github.py Same definition.
from openagents.utils.github import (  # noqa: F401  Re-export for direct import caller for this module
    APPROVAL_LABEL,
    AUTOMATION_FAILED_LABEL,
    DISCOVERY_LABEL,
    DISPATCH_LABEL,
    PR,
    PROCESS_LABELS,
    Blocker,
    CheckSnapshot,
    CheckStatus,
    Comment,
    GithubError,
    Issue,
    Mergeability,
    PRSnapshot,
    _strip_diff_file_blocks,
)

# Aligns with github._GH_TIMEOUT_SECONDS/ retry constant (the same instant error discipline, change the transfer layer without changing the policy).
_TIMEOUT_SECONDS = 30
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_BASE = 1.0
_TRANSIENT_STATUSES = {502, 503, 504}

# The draft expression for Gitea is the prefix to the title (service-side default "WIP: " ; part version PR responds to the original draft field, both recognized).
_WIP_PREFIXES = ("WIP:", "[WIP]")
_WIP_CANONICAL = "WIP: "

# Lists the endpoint single page limit (Gitea default page break 30/ page; driver flips the page itself, not allowing the service-end default cut-off discovery set).
_LIST_LIMIT = 50

_DEFAULT_TOKEN_ENV = "GITEA_TOKEN"

# Connect settings for configure load (module level, bound to process level of "gh cwd" equivalent of github.py).
_base_url: str | None = None
_owner: str | None = None
_repo: str | None = None
_token_env: str = _DEFAULT_TOKEN_ENV

# The tag name issue/label cache operation in Gitea is not named; the contest is backed back by 409/422 Quil.
# The current practice of aligning consumption with GiteaTracker)
_label_ids: dict[str, int] = {}


@dataclass(frozen=True)
class _HttpResult:
    """The original result of a RRT round-trip (status + excreted JSON + original) for the semantic layer by status code branch."""

    status: int
    data: Any
    text: str


def configure(*, settings: dict[str, Any]) -> None:
    """Configure the connection using a base URL, owner, repository, and token variable."""
    global _base_url, _owner, _repo, _token_env
    missing = [key for key in ("base_url", "owner", "repo") if not settings.get(key)]
    if missing:
        raise GithubError(
            f"Missing Gitea connection settings {missing}; check the gitea section in .openagents/openagents.yml"
        )
    _base_url = str(settings["base_url"]).rstrip("/")
    _owner = str(settings["owner"])
    _repo = str(settings["repo"])
    _token_env = str(settings.get("token_env") or _DEFAULT_TOKEN_ENV)
    _label_ids.clear()


def _ensure_configured() -> tuple[str, str, str]:
    """Return the current connection parameters or report incomplete configuration."""
    if not (_base_url and _owner and _repo):
        raise GithubError(
            "gitea driver is not configured - forge.configure (name=’geta’, settings=...) Load Connection Settings"
        )
    return _base_url, _owner, _repo


def _token() -> str:
    """Read the token from its environment variable without storing it in configuration."""
    token = os.environ.get(_token_env, "").strip()
    if not token:
        raise GithubError(
            f"Environmental variables {_token_env} Empty -Gitea Seasure token read only from environment variables"
        )
    return token


# Spec-0092/T2: one authenticated attachment hop may use Gitea.com's signed R2 URL.
_OBSERVATION_R2_HOST = re.compile(r"[a-f0-9]{32}\.r2\.cloudflarestorage\.com")


def _observation_r2_target(url: str) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
        return bool(
            parsed.scheme == "https"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and _OBSERVATION_R2_HOST.fullmatch(parsed.hostname or "")
            and not any(c.isspace() or ord(c) < 32 for c in url)
        )
    except ValueError:
        return False


def download_observation_asset(*, number: int, asset_id: int, limit: int) -> bytes:
    """Read an issue member with bounded, credential-free Gitea.com redirects."""
    base, owner, repo = _ensure_configured()
    origin = urllib.parse.urlsplit(base)
    hosted = (
        origin.scheme == "https"
        and origin.hostname == "gitea.com"
        and origin.port in (None, 443)
        and origin.username is None
        and origin.password is None
        and not origin.path
        and not origin.query
        and not origin.fragment
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    def read(url: str, budget: int, *, redirect: bool = False) -> bytes:
        deadline = time.monotonic() + 15
        authenticated = True
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("observation download exceeds budget")
            headers = {"Accept-Encoding": "identity"}
            if authenticated:
                headers["Authorization"] = f"token {_token()}"
            request = urllib.request.Request(url, headers=headers)
            # A fresh opener has no cookie/auth handler or netrc lookup, but retains proxies.
            try:
                response = urllib.request.build_opener(NoRedirect()).open(
                    request, timeout=min(5, remaining)
                )
            except urllib.error.HTTPError as exc:
                target = exc.headers.get("Location", "")
                status = exc.code
                exc.close()
                if (
                    redirect
                    and authenticated
                    and hosted
                    and status in (302, 303, 307, 308)
                    and _observation_r2_target(target)
                ):
                    url, authenticated = target, False
                    continue
                raise ValueError("observation download refused HTTP response") from None
            except (OSError, ValueError):
                # urllib exceptions can include the complete signed query; never propagate them.
                raise ValueError("observation download failed") from None
            chunks, size = [], 0
            with response:
                if getattr(response, "status", 200) != 200:
                    raise ValueError("observation download refused HTTP response")
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError("observation download exceeds budget")
                    sock = getattr(
                        getattr(getattr(response, "fp", None), "raw", None), "_sock", None
                    )
                    if sock is not None:
                        sock.settimeout(min(5, remaining))
                    try:
                        chunk = response.read1(min(65536, budget + 1 - size))
                    except (OSError, ValueError):
                        raise ValueError("observation download failed") from None
                    size += len(chunk)
                    if size > budget or time.monotonic() > deadline:
                        raise ValueError("observation download exceeds budget")
                    if not chunk:
                        break
                    chunks.append(chunk)
            return b"".join(chunks)

    assets = json.loads(
        read(base + f"/api/v1/repos/{owner}/{repo}/issues/{number}/assets", 1_000_000)
    )
    asset = next((a for a in assets if a["id"] == asset_id), None)
    if asset is None or not re.fullmatch(r"[a-fA-F0-9-]{36}", str(asset.get("uuid", ""))):
        raise ValueError("observation attachment outside issue")
    return read(base + "/attachments/" + asset["uuid"], limit, redirect=True)


def observation_request_exists(*, number: int, identity: str) -> bool:
    """Find our stable request across comment pages, including closed issues. Spec-0087/T1."""
    actor = _request(method="GET", path="user", body=None, query=None, allow=()).data["login"]
    for page in range(1, 21):
        rows = (
            _request(
                method="GET",
                path=_repo_path(suffix=f"issues/{number}/comments"),
                body=None,
                query={"page": page, "limit": 50},
                allow=(),
            ).data
            or []
        )
        if any(
            identity in str(row.get("body", "")).splitlines()
            and (row.get("user") or {}).get("login") == actor
            for row in rows
        ):
            return True
        if len(rows) < 50:
            return False
    raise ValueError("observation request identity scan exhausted; refusing ambiguous duplicate")


def _http(*, method: str, path: str, body: dict | None, query: dict | None) -> _HttpResult:
    """The only transfer stitch: a REST round-trip (without retry/state code). Test MonkeyPatch this function is off-grid.

    Network Layer Abnormal (Connect failure/timeout) Drop Timeout Error as an instant error handing `_request` over; HTTP not 2x
    Not on this level - semantics (404 & etc. / 422 already exists / up to date) by the caller press status branch.
    """
    base, _, _ = _ensure_configured()
    url = f"{base}/api/v1/{path}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    payload = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={
            "Authorization": f"token {_token()}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310  base_url from Local Configuration
            status = int(response.status)
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        text = exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TimeoutError(f"gitea {method} {path} Network failure:{exc}") from exc
    return _HttpResult(status=status, data=_maybe_json(text=text), text=text)


def _maybe_json(*, text: str) -> Any:
    """The responder tries to parse by JSON; nonJSON (e. g. .diff original) returns None, left in text."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _request(
    *, method: str, path: str, body: dict | None, query: dict | None, allow: tuple[int, ...]
) -> _HttpResult:
    """Send a REST request with bounded retries for transient transport failures."""
    for attempt in range(1, _RETRY_MAX_ATTEMPTS + 1):
        try:
            result = _http(method=method, path=path, body=body, query=query)
        except TimeoutError as exc:
            if attempt < _RETRY_MAX_ATTEMPTS:
                time.sleep(_RETRY_BACKOFF_BASE * 2 ** (attempt - 1))
                continue
            raise GithubError(str(exc)) from exc
        if result.status in _TRANSIENT_STATUSES and attempt < _RETRY_MAX_ATTEMPTS:
            time.sleep(_RETRY_BACKOFF_BASE * 2 ** (attempt - 1))
            continue
        if 200 <= result.status < 300 or result.status in allow:
            return result
        raise GithubError(f"gitea {method} {path} Back {result.status}：{result.text[:200]}")
    raise GithubError(f"gitea {method} {path} We’re running out of re-testing.")


def _repo_path(*, suffix: str) -> str:
    """Reposs/{owner} / {repo}/<suffix> Paths package (owner/repo from configure)."""
    _, owner, repo = _ensure_configured()
    return f"repos/{owner}/{repo}/{suffix}" if suffix else f"repos/{owner}/{repo}"


# --------------------------------------------------------------------------------------------------
# Label (Gitea label operation id: Name id parsing + Cache + Contest etc. back).
# --------------------------------------------------------------------------------------------------


def _refresh_label_cache() -> None:
    """#Spec-0074/T2: complete refreshing of tab name id cache; back-up page when service ignores page.

    Gitea allows a label with the same name, so keep the first id in the API order; call side only one stable id to add/remove, find filter
    Look directly at the label name in the issue response, and no longer rely on which duplicate item is selected here.
    """
    page = 1
    seen_ids: set[int] = set()
    while True:
        result = _request(
            method="GET",
            path=_repo_path(suffix="labels"),
            body=None,
            query={"limit": _LIST_LIMIT, "page": page},
            allow=(),
        )
        rows = result.data or []
        if not rows:
            return
        added = 0
        for item in rows:
            label_id = int(item.get("id") or 0)
            name = str(item.get("name") or "")
            if not label_id or label_id in seen_ids:
                continue
            seen_ids.add(label_id)
            added += 1
            if name:
                _label_ids.setdefault(name, label_id)
        if len(rows) < _LIST_LIMIT or not added:
            return
        page += 1


def _label_id(*, name: str) -> int:
    """Resolve a label name to its ID, refreshing the cache on a miss."""
    if name not in _label_ids:
        _refresh_label_cache()
    if name not in _label_ids:
        raise GithubError(f"Tab {name!r} Not Existing (ensure_label first)")
    return _label_ids[name]


def ensure_label(*, name: str, color: str = "ededed", description: str = "") -> None:
    """# Spec-0074/T2: Read first and build first; zero POST, 409/422 contests are in place and re-done.

    Gitea 1.22 allows the creation of multiple labels with the same name, so the ”POST Report already exists” cannot be used as a guarantee. vigil is used as a tool to create a label.
    Always adequate ready; only a complete read-cachel and a direct return before POST can prevent the repetition of labels from continuing to accumulate.
    """
    if name not in _label_ids:
        _refresh_label_cache()
    if name in _label_ids:
        return
    normalized = color if color.startswith("#") else f"#{color}"
    result = _request(
        method="POST",
        path=_repo_path(suffix="labels"),
        body={"name": name, "color": normalized, "description": description},
        query=None,
        allow=(409, 422),
    )
    if 200 <= result.status < 300 and isinstance(result.data, dict):
        _label_ids[name] = int(result.data.get("id") or 0)
        return
    _refresh_label_cache()  # Competition: built elsewhere, re-used id
    if name not in _label_ids:
        raise GithubError(
            f"Tab {name!r} Not available (gitea back) after construction {result.status}）"
        )


# --------------------------------------------------------------------------------------------------
# - I'm gonna go.
# --------------------------------------------------------------------------------------------------


def _issue_labels(*, raw: dict) -> tuple[str, ...]:
    return tuple(str((label or {}).get("name") or "") for label in raw.get("labels") or [])


def _issue_from(*, raw: dict) -> Issue:
    return Issue(
        number=int(raw["number"]),
        title=str(raw.get("title") or ""),
        body=str(raw.get("body") or ""),
        labels=_issue_labels(raw=raw),
    )


def get_issue(*, number: int) -> Issue:
    result = _request(
        method="GET", path=_repo_path(suffix=f"issues/{number}"), body=None, query=None, allow=()
    )
    if not isinstance(result.data, dict):
        raise GithubError("The details returned to unexpected structures.")
    return _issue_from(raw=result.data)


def _list_issue_pages(
    *, path: str, query: dict, wanted: set[str], repo_full_name: str | None
) -> list[Issue]:
    """Page through issue results and filter by repository, labels, and item type.
    Spec-0074/T2.
    """
    seen: dict[int, Issue] = {}
    raw_seen: set[tuple[str, int]] = set()
    page = 1
    while True:
        page_query = dict(query)
        page_query.update({"limit": _LIST_LIMIT, "page": page})
        result = _request(
            method="GET",
            path=path,
            body=None,
            query=page_query,
            allow=(),
        )
        rows = result.data or []
        if not rows:
            break
        added = 0
        for raw in rows:
            number = int(raw["number"])
            raw_repo = str((raw.get("repository") or {}).get("full_name") or "")
            raw_key = (raw_repo, number)
            if raw_key not in raw_seen:
                raw_seen.add(raw_key)
                added += 1
            if repo_full_name is not None and raw_repo.casefold() != repo_full_name.casefold():
                continue
            if raw.get("pull_request") is not None:
                continue
            issue = _issue_from(raw=raw)
            if wanted and wanted.isdisjoint(issue.labels):
                continue
            seen.setdefault(issue.number, issue)
        if len(rows) < _LIST_LIMIT or not added:
            break
        page += 1
    return list(seen.values())


def list_issues(*, labels: list[str], state: str = "open") -> list[Issue]:
    """Return issues with all requested labels, filtering server-side OR matches.
    Spec-0074/T2.
    """
    if not labels:
        return _list_issue_pages(
            path=_repo_path(suffix="issues"),
            query={"state": state, "type": "issues"},
            wanted=set(),
            repo_full_name=None,
        )

    _refresh_label_cache()
    known = list(dict.fromkeys(label for label in labels if label in _label_ids))
    if not known:
        return []

    _, owner, repo = _ensure_configured()
    server_labels = [label for label in known if "," not in label]
    fallback_labels = {label for label in known if "," in label}
    seen: dict[int, Issue] = {}
    if server_labels:
        for issue in _list_issue_pages(
            path="repos/issues/search",
            query={
                "owner": owner,
                "state": state,
                "type": "issues",
                "labels": ",".join(server_labels),
            },
            wanted=set(server_labels),
            repo_full_name=f"{owner}/{repo}",
        ):
            seen.setdefault(issue.number, issue)
    if fallback_labels:
        for issue in _list_issue_pages(
            path=_repo_path(suffix="issues"),
            query={"state": state, "type": "issues"},
            wanted=fallback_labels,
            repo_full_name=None,
        ):
            seen.setdefault(issue.number, issue)
    return list(seen.values())


def create_issue(*, title: str, body: str, labels: list[str]) -> Issue:
    """Builds a notsue (label unnamed id resolution; unknown tag prefix etc., relaxed to self-healing by the pre-established semantic)."""
    for name in labels:
        if name not in _label_ids:
            ensure_label(name=name)
    result = _request(
        method="POST",
        path=_repo_path(suffix="issues"),
        body={"title": title, "body": body, "labels": [_label_id(name=name) for name in labels]},
        query=None,
        allow=(),
    )
    if not isinstance(result.data, dict) or result.data.get("number") is None:
        raise GithubError(
            "No, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no, no."
        )
    return Issue(number=int(result.data["number"]), title=title, body=body, labels=tuple(labels))


def issue_comment(*, number: int, body: str) -> None:
    _request(
        method="POST",
        path=_repo_path(suffix=f"issues/{number}/comments"),
        body={"body": body},
        query=None,
        allow=(),
    )


def _comments_from(*, rows: list) -> list[Comment]:
    _, owner, _ = _ensure_configured()
    comments: list[Comment] = []
    for raw in rows:
        login = str(((raw or {}).get("user") or {}).get("login") or "")
        comments.append(
            Comment(
                id=str(raw.get("id") or ""),
                author=login,
                body=str(raw.get("body") or ""),
                created_at=str(raw.get("created_at") or ""),
                # The post is part of our special coverage Global Voices Online, which is a series of events that have been held in the past few years.
                # The remaining empty space (fail-closed: comments that cannot read are not boarded, see Comment doingcstring).
                author_association="OWNER" if login and login == owner else "",
            )
        )
    return comments


def list_issue_comments(*, number: int) -> list[Comment]:
    result = _request(
        method="GET",
        path=_repo_path(suffix=f"issues/{number}/comments"),
        body=None,
        query=None,
        allow=(),
    )
    return _comments_from(rows=result.data or [])


def list_comments(*, pr_number: int) -> list[Comment]:
    """PR Comment - The PR of Gitea shares an index with the peer of the committees, and directly re-uses the issue."""
    return list_issue_comments(number=pr_number)


def post_comment(*, pr_number: int, body: str) -> None:
    issue_comment(number=pr_number, body=body)


def issue_add_label(*, number: int, name: str) -> None:
    """Add a label to an issue; keep repeat additions idempotent."""
    if name not in _label_ids:
        ensure_label(name=name)
    _request(
        method="POST",
        path=_repo_path(suffix=f"issues/{number}/labels"),
        body={"labels": [_label_id(name=name)]},
        query=None,
        allow=(),
    )


def issue_remove_label(*, number: int, name: str) -> None:
    """Remove a label and tolerate an already absent label."""
    if name not in _label_ids:
        _refresh_label_cache()
    if name not in _label_ids:
        return  # There's no such label in the warehouse.
    _request(
        method="DELETE",
        path=_repo_path(suffix=f"issues/{number}/labels/{_label_ids[name]}"),
        body=None,
        query=None,
        allow=(404,),
    )


def add_label(*, pr_number: int, name: str) -> None:
    issue_add_label(number=pr_number, name=name)


def remove_label(*, pr_number: int, name: str) -> None:
    issue_remove_label(number=pr_number, name=name)


def has_label(*, pr_number: int, name: str) -> bool:
    result = _request(
        method="GET", path=_repo_path(suffix=f"issues/{pr_number}"), body=None, query=None, allow=()
    )
    return name in _issue_labels(raw=result.data or {})


def close_issue(*, number: int) -> None:
    """Close an issue and tolerate a 404 if the issue no longer exists."""
    _request(
        method="PATCH",
        path=_repo_path(suffix=f"issues/{number}"),
        body={"state": "closed"},
        query=None,
        allow=(404,),
    )


# --------------------------------------------------------------------------------------------------
# blocked_by - Gitea issue dependencias API.
# --------------------------------------------------------------------------------------------------


def list_blocked_by(*, number: int) -> list[Blocker]:
    """Read the list of ”issues blocking this issue”; character closing/no-point (404) is considered non-dependent (symmetrical with github version)."""
    result = _request(
        method="GET",
        path=_repo_path(suffix=f"issues/{number}/dependencies"),
        body=None,
        query=None,
        allow=(404,),
    )
    if result.status == 404:
        return []
    blockers: list[Blocker] = []
    for raw in result.data or []:
        if not isinstance(raw, dict) or raw.get("number") is None:
            continue
        blockers.append(
            Blocker(number=int(raw["number"]), state=str(raw.get("state") or "").upper())
        )
    return blockers


def add_blocked_by(*, number: int, blocker_number: int) -> None:
    """Add a native dependency, tolerating an edge that already exists."""
    _, owner, repo = _ensure_configured()
    _request(
        method="POST",
        path=_repo_path(suffix=f"issues/{number}/dependencies"),
        body={"index": blocker_number, "owner": owner, "repo": repo},
        query=None,
        allow=(404, 409, 422),
    )


# --------------------------------------------------------------------------------------------------
# PR side.
# --------------------------------------------------------------------------------------------------


def _get_pull(*, pr_number: int) -> dict:
    result = _request(
        method="GET", path=_repo_path(suffix=f"pulls/{pr_number}"), body=None, query=None, allow=()
    )
    if not isinstance(result.data, dict):
        raise GithubError("gitea PR details returned to unexpected structures")
    return result.data


def _pr_from(*, raw: dict) -> PR:
    return PR(number=int(raw["number"]), url=str(raw.get("html_url") or ""))


def create_pr(*, branch: str, title: str, body: str, base: str = "main", draft: bool = False) -> PR:
    """Opens the PR; Draft expression with a WIP prefix (the gitea ’s draft syntax, mark_ready prefix)."""
    final_title = f"{_WIP_CANONICAL}{title}" if draft else title
    result = _request(
        method="POST",
        path=_repo_path(suffix="pulls"),
        body={"head": branch, "base": base, "title": final_title, "body": body},
        query=None,
        allow=(),
    )
    if not isinstance(result.data, dict) or result.data.get("number") is None:
        raise GithubError("gitea build PR not returned number")
    return _pr_from(raw=result.data)


def _pr_by_branch(*, branch: str, state: str) -> PR | None:
    """Press head branch to find the nearest PR-Gitea list endpoint without head filter parameters, and the client filters with head.ref
    (sort=recentupdate, first; branch corresponds to issue, only one in practice)."""
    result = _request(
        method="GET",
        path=_repo_path(suffix="pulls"),
        body=None,
        query={"state": state, "sort": "recentupdate", "limit": _LIST_LIMIT},
        allow=(),
    )
    for raw in result.data or []:
        head_ref = str(((raw or {}).get("head") or {}).get("ref") or "")
        if head_ref == branch and raw.get("number") is not None:
            return _pr_from(raw=raw)
    return None


def find_pr_by_branch(*, branch: str) -> PR | None:
    return _pr_by_branch(branch=branch, state="open")


def pr_for_branch(*, branch: str) -> PR | None:
    """The last PR of a branch, open-ended status (all merged/closed) - the `_sense` termination condition is visible as a merged PR."""
    return _pr_by_branch(branch=branch, state="all")


def list_open_prs() -> list[PR]:
    result = _request(
        method="GET",
        path=_repo_path(suffix="pulls"),
        body=None,
        query={"state": "open", "limit": _LIST_LIMIT},
        allow=(),
    )
    return [_pr_from(raw=raw) for raw in result.data or [] if raw.get("number") is not None]


def pr_head_branch(*, pr_number: int) -> str:
    head_ref = str((_get_pull(pr_number=pr_number).get("head") or {}).get("ref") or "")
    if not head_ref:
        raise GithubError("gitea PR did not return head branch name")
    return head_ref


def _pr_title_is_wip(*, title: str) -> bool:
    return any(title.startswith(prefix) for prefix in _WIP_PREFIXES)


def _pr_is_draft(*, raw: dict) -> bool:
    # Semantic map: Native draft fields (more recent Gitea) or WIP headers prefix (service-end default agreement), either of which is draft.
    return raw.get("draft") is True or _pr_title_is_wip(title=str(raw.get("title") or ""))


def _pr_state(*, raw: dict) -> str:
    # Gitea PR state only open/closed;merged is the synonym for the Brigible - which is to GitHub.
    if raw.get("merged") is True:
        return "MERGED"
    return str(raw.get("state") or "").upper() or "OPEN"


def _pr_mergeable(*, raw: dict) -> tuple[str, str]:
    # Semantic Map: Gitea mergeable is bool (no BEHIND/UNKNOWN breakdown) - false → CONFLICTING/DIRTY,
    # True → MERGEABLE/CLEAN, missing fields (old version/calculation) → UNKNOWN/UNKNOWN (tick self-healing at Vigil).
    # No BEHIND: base does not stand by the Vigil update_branch, when merged by the service merge (Spec-0074 Unresolved 3).
    mergeable = raw.get("mergeable")
    if mergeable is True:
        return "MERGEABLE", "CLEAN"
    if mergeable is False:
        return "CONFLICTING", "DIRTY"
    return "UNKNOWN", "UNKNOWN"


def is_merged(*, pr_number: int) -> bool:
    return _pr_state(raw=_get_pull(pr_number=pr_number)) == "MERGED"


def is_open(*, pr_number: int) -> bool:
    return _pr_state(raw=_get_pull(pr_number=pr_number)) == "OPEN"


def is_closed(*, pr_number: int) -> bool:
    return _pr_state(raw=_get_pull(pr_number=pr_number)) == "CLOSED"


def is_draft(*, pr_number: int) -> bool:
    return _pr_is_draft(raw=_get_pull(pr_number=pr_number))


def mergeability(*, pr_number: int) -> Mergeability:
    mergeable, merge_state = _pr_mergeable(raw=_get_pull(pr_number=pr_number))
    return Mergeability(mergeable=mergeable, merge_state_status=merge_state)


def mark_ready(*, pr_number: int) -> None:
    """Remove the draft title prefix; do nothing if the PR is already ready."""
    raw = _get_pull(pr_number=pr_number)
    title = str(raw.get("title") or "")
    stripped = title
    for prefix in _WIP_PREFIXES:
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix) :].lstrip()
            break
    if stripped == title:
        return
    _request(
        method="PATCH",
        path=_repo_path(suffix=f"pulls/{pr_number}"),
        body={"title": stripped},
        query=None,
        allow=(),
    )


def pr_snapshot(*, pr_number: int) -> PRSnapshot:
    """Read the PR state, head, mergeability, and draft information in one request."""
    raw = _get_pull(pr_number=pr_number)
    mergeable, merge_state = _pr_mergeable(raw=raw)
    return PRSnapshot(
        number=int(raw["number"]),
        state=_pr_state(raw=raw),
        head_sha=str((raw.get("head") or {}).get("sha") or ""),
        labels=_issue_labels(raw=raw),
        mergeable=mergeable,
        merge_state_status=merge_state,
        head_pushed_at=str(raw.get("updated_at") or ""),
        is_draft=_pr_is_draft(raw=raw),
    )


def update_branch(*, pr_number: int, rebase: bool = False) -> bool:
    """Update the PR from its base; return false when already up to date."""
    style = "rebase" if rebase else "merge"
    result = _request(
        method="POST",
        path=_repo_path(suffix=f"pulls/{pr_number}/update"),
        body=None,
        query={"style": style},
        allow=(422,),
    )
    return 200 <= result.status < 300


def merge_pr(*, pr_number: int, method: str = "merge", head_sha: str = "") -> None:
    """Merge the requested PR at the approved head, tolerating an already merged PR."""
    body = {"Do": method}
    # Spec-0017 recovery: Gitea rejects a changed head atomically with HTTP 409.
    if head_sha:
        body["head_commit_id"] = head_sha
    result = _request(
        method="POST",
        path=_repo_path(suffix=f"pulls/{pr_number}/merge"),
        body=body,
        query=None,
        allow=(405, 409),
    )
    if 200 <= result.status < 300:
        return
    if is_merged(pr_number=pr_number):
        return  # I've been together.
    raise GithubError(
        f"Gitea merge PR#{pr_number} Failed (%1){result.status}）：{result.text[:200]}"
    )


def code_fingerprint(
    *, pr_number: int, exclude_paths: tuple[str, ...] = ("docs/e2e-results/",)
) -> str:
    """PR net diff fingerprints (.diff original endpoint + re-use gethub file block removed); failed/empty ”fail-open and gethub version”."""
    try:
        result = _request(
            method="GET",
            path=_repo_path(suffix=f"pulls/{pr_number}.diff"),
            body=None,
            query=None,
            allow=(),
        )
    except GithubError:
        return ""
    diff = result.text or ""
    if exclude_paths:
        diff = _strip_diff_file_blocks(diff=diff, exclude_paths=exclude_paths)
    if not diff.strip():
        return ""
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------------------
# CI (committee joined status-Gitea without check runs, Actions/ External CI both fall together status).
# --------------------------------------------------------------------------------------------------

_STATUS_FAIL = {"failure", "error"}


def _combined_status(*, ref: str) -> tuple[str, list[dict]]:
    """ET /committees / {ref} / status (combined state, statuss details). State is empty when zero status."""
    result = _request(
        method="GET",
        path=_repo_path(suffix=f"commits/{urllib.parse.quote(ref, safe='')}/status"),
        body=None,
        query=None,
        allow=(),
    )
    data = result.data if isinstance(result.data, dict) else {}
    statuses = [raw for raw in data.get("statuses") or [] if isinstance(raw, dict)]
    return str(data.get("state") or "").lower(), statuses


def _classify_statuses(*, state: str, statuses: list[dict]) -> CheckStatus:
    """Aggregate status results, with failures taking precedence over pending checks."""
    failed = [
        f"{raw.get('context') or 'unknown'} [{str(raw.get('status') or '').upper()}] "
        f"{raw.get('target_url') or ''}".strip()
        for raw in statuses
        if str(raw.get("status") or "").lower() in _STATUS_FAIL
    ]
    if failed or state in _STATUS_FAIL:
        return CheckStatus(state="fail", failed_logs=failed)
    if state == "pending":
        return CheckStatus(state="pending", failed_logs=[])
    return CheckStatus(state="pass", failed_logs=[])


def _pr_head_sha(*, pr_number: int) -> str:
    return str((_get_pull(pr_number=pr_number).get("head") or {}).get("sha") or "")


def check_status(*, pr_number: int) -> CheckStatus:
    state, statuses = _combined_status(ref=_pr_head_sha(pr_number=pr_number))
    return _classify_statuses(state=state, statuses=statuses)


def check_snapshot(*, pr_number: int) -> CheckSnapshot:
    """Return current-head status and count so zero checks can be handled separately."""
    state, statuses = _combined_status(ref=_pr_head_sha(pr_number=pr_number))
    aggregate = _classify_statuses(state=state, statuses=statuses)
    started = [str(raw.get("created_at") or "") for raw in statuses]
    return CheckSnapshot(
        state=aggregate.state,
        count=len(statuses),
        latest_started_at=max(started) if started else "",
    )


def check_logs(*, pr_number: int) -> list[str]:
    return check_status(pr_number=pr_number).failed_logs


def branch_ci_green(*, branch: str) -> bool:
    """Return whether branch CI passed under the forge driver contract."""
    state, statuses = _combined_status(ref=branch)
    if not statuses:
        return True
    return state == "success"


# --------------------------------------------------------------------------------------------------
# Pre-inspection/ build/merger command text.
# --------------------------------------------------------------------------------------------------


def ensure_prerequisites() -> None:
    """Check token and repository access, then ensure the process labels exist."""
    _token()
    _request(method="GET", path=_repo_path(suffix=""), body=None, query=None, allow=())
    for label in PROCESS_LABELS:
        ensure_label(name=label)


def create_repo(*, name: str, private: bool) -> str:
    """New remote storage (cold start-up pocket):owner/repo Form taken repo - Step aside. /user/repos, Back clone url。"""
    repo_name = name.split("/", 1)[1] if "/" in name else name
    result = _request(
        method="POST",
        path="user/repos",
        body={"name": repo_name, "private": private, "auto_init": False},
        query=None,
        allow=(),
    )
    data = result.data if isinstance(result.data, dict) else {}
    url = str(data.get("clone_url") or data.get("html_url") or "")
    if not url:
        raise GithubError("Gitea builder not returned")
    return url


def merge_command_text(*, pr_number: int, head_sha: str = "") -> str:
    """The merger agent’s drop-down command - the platform has no hidden CLI (token process left in driver without hint)."""
    suffix = f" --head-sha {shlex.quote(head_sha)}" if head_sha else ""
    return f"openagents merge-pr --pr {pr_number}{suffix}"


def merge_verify_command_text(*, pr_number: int, head_sha: str = "") -> str:
    """The completion order for the merger agent - merge-pr & so on (merge-pr & so on) has been merged to directly export MERGED, and rerun is verified."""
    return merge_command_text(pr_number=pr_number, head_sha=head_sha)
