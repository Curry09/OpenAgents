"""RFC-0001 T3: GitHub 集成层 —— 对 gh CLI 的薄封装。

决策 3：GitHub 操作一律走 `gh` CLI 子进程，而非 REST SDK——零额外依赖，
鉴权/分页交由 gh 处理，与 scripts/check-rfc-number-conflicts.py 的用法一致。
决策 11：check_status 读 `gh pr checks` 的 CI 状态，失败时收集失败 check 的
摘要日志，供编排层把失败喂回 agent，反复修到 CI 全绿。

错误处理：任何 gh 返回非零（且非"仍有 check 进行中"的特例）时统一抛 GithubError，
携带 gh 的 stderr 摘要，便于上层定位。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

# `gh pr checks` 在 CI 仍有 check 进行中时以退出码 8 返回，stdout 仍是合法 JSON。
# 见 gh 文档：非零退出并不总代表错误，这里单独放行该特例。
_GH_CHECKS_PENDING_RETURNCODE = 8

# gh pr checks 的 state 取值归类。
_CHECK_FAIL_STATES = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED"}
_CHECK_PASS_STATES = {"SUCCESS", "SKIPPED", "NEUTRAL"}


class GithubError(Exception):
    """gh CLI 调用失败（返回非零）时抛出，携带可读的失败原因。"""


@dataclass(frozen=True)
class Issue:
    """一个 GitHub issue 的最小投影。"""

    number: int
    title: str
    body: str


@dataclass(frozen=True)
class PR:
    """一个 pull request 的最小投影。"""

    number: int
    url: str


@dataclass(frozen=True)
class Comment:
    """PR 上的一条评论。

    id 是 GitHub 的 GraphQL node id（字符串，非数字）；评论的先后顺序用
    created_at（ISO 8601，可按字典序比较）判断，不能用 id 排序。
    """

    id: str
    author: str
    body: str
    created_at: str


@dataclass(frozen=True)
class CheckStatus:
    """PR 的 CI 聚合状态（决策 11）。

    state: "pass" | "fail" | "pending" 之一。
    failed_logs: 失败 check 的摘要（名称 + 链接），供喂回 agent。
    """

    state: str
    failed_logs: list[str]


def _run_gh(args: list[str], *, allow_returncodes: set[int]) -> subprocess.CompletedProcess[str]:
    """运行 gh 子命令；返回非零且不在 allow_returncodes 中时抛 GithubError。"""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0 and result.returncode not in allow_returncodes:
        reason = result.stderr.strip() or f"gh {' '.join(args)} 返回码 {result.returncode}"
        raise GithubError(reason)
    return result


def _gh_json(args: list[str], *, allow_returncodes: set[int]) -> Any:
    """运行 gh 子命令并把 stdout 解析为 JSON；解析失败抛 GithubError。"""
    result = _run_gh(args, allow_returncodes=allow_returncodes)
    try:
        return json.loads(result.stdout or "null")
    except json.JSONDecodeError as exc:
        raise GithubError(f"无法解析 gh 输出为 JSON：{exc}") from exc


def create_repo(*, name: str, private: bool) -> str:
    """RFC-0001 T3：用 `gh repo create` 新建远端，返回 remote url。

    private 决定 --private / --public；供 config.ensure_project 冷启动调用。
    """
    visibility = "--private" if private else "--public"
    result = _run_gh(["repo", "create", name, visibility], allow_returncodes=set())
    url = result.stdout.strip()
    if not url:
        raise GithubError("gh repo create 未返回 remote url")
    return url


def get_issue(*, number: int) -> Issue:
    """RFC-0001 T3：`gh issue view <n> --json number,title,body`。"""
    data = _gh_json(
        ["issue", "view", str(number), "--json", "number,title,body"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh issue view 返回了非预期的结构")
    return Issue(
        number=int(data["number"]),
        title=data.get("title") or "",
        body=data.get("body") or "",
    )


def create_pr(*, branch: str, title: str, body: str) -> PR:
    """RFC-0001 T3：`gh pr create`，从 stdout 的 PR url 解析出 number 与 url。"""
    result = _run_gh(
        ["pr", "create", "--head", branch, "--title", title, "--body", body],
        allow_returncodes=set(),
    )
    url = result.stdout.strip()
    number = _parse_pr_number(url=url)
    if number is None:
        raise GithubError(f"无法从 gh pr create 输出解析 PR number：{url!r}")
    return PR(number=number, url=url)


def list_comments(*, pr_number: int) -> list[Comment]:
    """RFC-0001 T3：`gh pr view <n> --json comments`，解析为 Comment 列表。

    comment id 是 node id 字符串；同时取 createdAt 供消息层按时间判定新评论。
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "comments"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view 返回了非预期的结构")
    comments: list[Comment] = []
    for raw in data.get("comments") or []:
        author = (raw.get("author") or {}).get("login") or ""
        comments.append(
            Comment(
                id=str(raw.get("id") or ""),
                author=author,
                body=raw.get("body") or "",
                created_at=raw.get("createdAt") or "",
            )
        )
    return comments


def post_comment(*, pr_number: int, body: str) -> None:
    """RFC-0001 T3：`gh pr comment <n> --body <body>`。"""
    _run_gh(
        ["pr", "comment", str(pr_number), "--body", body],
        allow_returncodes=set(),
    )


def check_status(*, pr_number: int) -> CheckStatus:
    """RFC-0001 T3（决策 11）：读 `gh pr checks <n> --json`，聚合为 CI 状态。

    归类：任一 check 失败 → "fail"（收集失败摘要）；否则任一进行中 → "pending"；
    全部通过（或无 check）→ "pass"。失败优先于进行中。
    """
    try:
        data = _gh_json(
            ["pr", "checks", str(pr_number), "--json", "name,state,link"],
            allow_returncodes={_GH_CHECKS_PENDING_RETURNCODE},
        )
    except GithubError as exc:
        # 仓库未配置任何 CI 时 gh 以非零退出并报 "no checks reported"——视为通过。
        if "no checks reported" in str(exc).lower():
            return CheckStatus(state="pass", failed_logs=[])
        raise
    checks = data if isinstance(data, list) else []
    return _classify_checks(checks=checks)


def is_merged(*, pr_number: int) -> bool:
    """RFC-0001 T3（决策 8）：PR 是否已合并（`gh pr view <n> --json state`）。

    供编排/消息层判定终止条件：PR 合并即把对应 issue 置 done。
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "state"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view 返回了非预期的结构")
    return str(data.get("state") or "").upper() == "MERGED"


def _parse_pr_number(*, url: str) -> int | None:
    """从形如 .../pull/<n> 的 PR url 末段解析 PR number；失败返回 None。"""
    marker = "/pull/"
    idx = url.rfind(marker)
    if idx == -1:
        return None
    tail = url[idx + len(marker) :].strip("/").split("/", 1)[0]
    if not tail.isdigit():
        return None
    return int(tail)


def _classify_checks(*, checks: list[dict[str, Any]]) -> CheckStatus:
    """把 gh pr checks 的原始列表归类为 CheckStatus。"""
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
