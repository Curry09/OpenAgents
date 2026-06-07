"""RFC-0001 T3: GitHub 集成层 —— 对 gh CLI 的薄封装。

决策 3：GitHub 操作一律走 `gh` CLI 子进程，而非 REST SDK——零额外依赖，
鉴权/分页交由 gh 处理，与 scripts/check-rfc-number-conflicts.py 的用法一致。
决策 11：check_status 读 `gh pr checks` 的 CI 状态，失败时收集失败 check 的
摘要日志，供编排层把失败喂回 agent，反复修到 CI 全绿。

错误处理：任何 gh 返回非零（且非"仍有 check 进行中"的特例）时统一抛 GithubError，
携带 gh 的 stderr 摘要，便于上层定位。

RFC-0010：所有 gh 调用都经由唯一收口点 `_run_gh`，在此加一层瞬时错误（HTTP
502/503/504 等服务端网关故障、以及 subprocess 超时）的指数退避重试——一处覆盖全部
gh 调用，元凶 `gh pr checks`（statusCheckRollup 偶发 504）自然受益。业务错误（not
found / no checks reported / pending 退出码 8）绝不重试，立即按原样抛出/返回。
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from typing import Any

# `gh pr checks` 在 CI 仍有 check 进行中时以退出码 8 返回，stdout 仍是合法 JSON。
# 见 gh 文档：非零退出并不总代表错误，这里单独放行该特例。
_GH_CHECKS_PENDING_RETURNCODE = 8

# gh 子进程超时秒数（决策 4：超时抛 subprocess.TimeoutExpired，归一化为瞬时错误）。
_GH_TIMEOUT_SECONDS = 30

# RFC-0010 决策 3：瞬时错误重试上限与退避基数，均为模块级常量（理念 1：不引入配置项）。
# 总尝试 = 1 次原始 + 最多 (_GH_RETRY_MAX_ATTEMPTS - 1) 次重试；退避 base·2^(n-1) 秒。
_GH_RETRY_MAX_ATTEMPTS = 3
_GH_RETRY_BACKOFF_BASE = 1.0

# RFC-0010 决策 2：瞬时服务端故障的 stderr 标记（小写匹配）。判定要「窄」——只认这些
# 服务端瞬时故障；not found / already exists / no checks reported 等业务错误绝不算。
_GH_TRANSIENT_MARKERS = (
    "http 502",
    "http 503",
    "http 504",
    "bad gateway",
    "gateway timeout",
    "service unavailable",
)

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


def _is_transient_gh_error(*, stderr: str) -> bool:
    """RFC-0010 决策 2：stderr 是否命中瞬时服务端故障标记（HTTP 502/503/504 / Bad
    Gateway / Gateway Timeout / Service Unavailable）。纯函数，便于单测。"""
    lowered = stderr.lower()
    return any(marker in lowered for marker in _GH_TRANSIENT_MARKERS)


def _run_gh(args: list[str], *, allow_returncodes: set[int]) -> subprocess.CompletedProcess[str]:
    """运行 gh 子命令；返回非零且不在 allow_returncodes 中时抛 GithubError。

    RFC-0010：瞬时错误（stderr 命中 _GH_TRANSIENT_MARKERS，或 subprocess.TimeoutExpired）
    按指数退避重试，最多 _GH_RETRY_MAX_ATTEMPTS 次尝试；非瞬时错误（含 allow_returncodes
    放行的退出码、not found 等业务错误）立即返回/抛出，绝不重试。重试耗尽（含超时）后
    统一抛 GithubError——对外签名/返回类型不变，所有调用方零改动（决策 1/4）。
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
            # 决策 4：超时视为瞬时错误，重试；耗尽后归一化为 GithubError（非 TimeoutExpired）。
            reason = f"gh {' '.join(args)} 超时（{_GH_TIMEOUT_SECONDS}s）"
            if attempt < _GH_RETRY_MAX_ATTEMPTS:
                time.sleep(_GH_RETRY_BACKOFF_BASE * 2 ** (attempt - 1))
                continue
            raise GithubError(reason) from None
        if result.returncode != 0 and result.returncode not in allow_returncodes:
            reason = result.stderr.strip() or f"gh {' '.join(args)} 返回码 {result.returncode}"
            # 决策 2：仅瞬时错误且仍有重试次数时退避重试；业务错误/末次尝试立即抛。
            if _is_transient_gh_error(stderr=result.stderr) and attempt < _GH_RETRY_MAX_ATTEMPTS:
                time.sleep(_GH_RETRY_BACKOFF_BASE * 2 ** (attempt - 1))
                continue
            raise GithubError(reason)
        return result
    # 不可达：循环每轮要么 return、要么 continue、要么 raise（保留以满足类型检查）。
    raise GithubError(f"gh {' '.join(args)} 重试耗尽")


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


def list_issues(*, labels: list[str], state: str = "open") -> list[Issue]:
    """RFC-0004 T1：列出（可按标签门控的）issue，供 vigil 守夜人发现新 issue。

    走 `gh issue list --state <state> [--label L ...] --json number,title,body`。
    labels 为空表示不按标签过滤（列出该 state 的全部 issue）；多个 label 由 gh 以
    并集（OR）语义处理（任一命中即返回）。复用决策 3 的 gh 子进程封装与既有 Issue
    数据模型，不新增数据类型（CLAUDE.md 理念 1）。
    """
    args = ["issue", "list", "--state", state, "--json", "number,title,body"]
    for label in labels:
        args += ["--label", label]
    data = _gh_json(args, allow_returncodes=set())
    rows = data if isinstance(data, list) else []
    return [
        Issue(
            number=int(raw["number"]),
            title=raw.get("title") or "",
            body=raw.get("body") or "",
        )
        for raw in rows
    ]


def create_issue(*, title: str, body: str, labels: list[str]) -> Issue:
    """Create a GitHub issue via gh and return its minimal projection.

    RFC-0002 T1：`gh issue create --title <title> --body <body> [--label <l> ...]`。

    与决策 3 一致走 gh 子进程，复用 _run_gh 的错误处理；gh 在 stdout 返回新 issue 的
    url（形如 .../issues/<n>），从末段解析出 number，连同传入的 title/body 组装成
    既有的 Issue 返回（决策 2：不新增数据类型）。
    """
    # 1. 组装 gh 参数：title/body 必带，labels 逐个展开为 --label
    args = ["issue", "create", "--title", title, "--body", body]
    for label in labels:
        args += ["--label", label]

    # 2. 调用 gh；非零退出由 _run_gh 抛 GithubError
    result = _run_gh(args, allow_returncodes=set())

    # 3. 从 stdout 的 issue url 末段解析 number
    url = result.stdout.strip()
    number = _parse_issue_number(url=url)
    if number is None:
        raise GithubError(f"无法从 gh issue create 输出解析 issue number：{url!r}")
    return Issue(number=number, title=title, body=body)


def ensure_label(*, name: str, color: str = "ededed", description: str = "") -> None:
    """RFC-0002 决策 6：确保仓库存在名为 name 的标签，供 `gh issue create --label` 使用。

    `gh issue create --label <L>` 要求 <L> 预先存在，否则报 "could not add label: ... not found"。
    既然决策 5 强制附加发现标签 openagents，提 issue 前先确保它存在：不存在则 `gh label create`
    创建；已存在时 gh 以非零退出并报 "already exists"——吞掉视为成功，**不覆盖**既有颜色/描述
    （与 check_status 吞 "no checks reported" 同一容错风格）。其它 gh 错误照常抛 GithubError。
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


def create_pr(*, branch: str, title: str, body: str, draft: bool = False) -> PR:
    """RFC-0001 T3：`gh pr create`，从 stdout 的 PR url 解析出 number 与 url。

    RFC-0005 决策 2：draft=True 时追加 `--draft`，使 PR 先以草稿形态承载 RFC，
    待人评审/批准后由 mark_ready 转正。默认 False，保持既有调用向后兼容。
    """
    args = ["pr", "create", "--head", branch, "--title", title, "--body", body]
    if draft:
        args.append("--draft")
    result = _run_gh(args, allow_returncodes=set())
    url = result.stdout.strip()
    number = _parse_pr_number(url=url)
    if number is None:
        raise GithubError(f"无法从 gh pr create 输出解析 PR number：{url!r}")
    return PR(number=number, url=url)


def find_pr_by_branch(*, branch: str) -> PR | None:
    """RFC-0003 决策 8：查某分支当前的 open PR（`gh pr list --head <branch>`）。

    供 solve 续写/恢复时复用已有 PR、避免重复 `gh pr create`；无则返回 None。
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


def mark_ready(*, pr_number: int) -> None:
    """RFC-0005 T3（决策 2）：把 draft PR 转正（`gh pr ready <n>`）。

    implement 写完代码后调用，使承载 RFC 的草稿 PR 转为可正式评审的代码 PR。
    """
    _run_gh(["pr", "ready", str(pr_number)], allow_returncodes=set())


def has_label(*, pr_number: int, name: str) -> bool:
    """RFC-0005 T3（决策 4）：PR 是否带某标签（`gh pr view <n> --json labels`）。

    供消息层识别批准信号（rfc-approved 标签）——标签是结构化信号，不与讨论评论混淆。
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "labels"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view 返回了非预期的结构")
    labels = data.get("labels") or []
    return any((label or {}).get("name") == name for label in labels)


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


def is_closed(*, pr_number: int) -> bool:
    """RFC-0006：PR 是否被关闭但未合并（`gh pr view <n> --json state` == "CLOSED"）。

    供消息层把「人主动关闭」识别为终止信号：与 is_merged 对称——GitHub PR 的 state 有
    OPEN / CLOSED / MERGED 三态且互斥，已合并的 PR state 是 MERGED（不算 closed）。
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "state"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view 返回了非预期的结构")
    return str(data.get("state") or "").upper() == "CLOSED"


def list_open_prs() -> list[PR]:
    """RFC-0009 T1：列出仓库当前所有 open PR（`gh pr list --state open --json number,url`）。

    以 GitHub 为真源，覆盖面比本地 State（只含 openagents 自建的 run）更全，对人工建的
    PR 也成立——供合并后自动同步扇出（rebase_open_prs）枚举待更新的 PR。无则返回 []。
    复用既有 PR 数据类与 _gh_json 封装，不新增数据类型（CLAUDE.md 理念 1）。
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
    """RFC-0009 T1（决策 2/5）：把最新 base（main）并入 PR 分支（`gh pr update-branch <n>`）。

    默认走 merge（不重写历史、不需 force-push，适合无人值守循环）；rebase=True 追加
    `--rebase` 改为 rebase。该更新会在 PR 上产生 synchronize 事件，触发其 CI 重跑。

    返回 True 表示分支已被更新；返回 False 表示「已是最新」no-op——gh 在分支已与 base
    同步时以非零退出并报 "already up to date" 之类信息，这里吞掉视为成功（与 ensure_label
    吞 "already exists"、check_status 吞 "no checks reported" 同一容错风格，决策 5）。
    冲突或其它失败照常抛 GithubError，供 rebase_open_prs 捕获后留言（决策 4）。
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


def _is_already_up_to_date(*, reason: str) -> bool:
    """gh update-branch 的「分支已是最新」特例识别（决策 5）。

    gh 对此以非零退出，文案大致为 "branch is already up to date"；大小写/连字符不一，
    统一小写后按子串匹配，与冲突等真错误区分开。
    """
    lowered = reason.lower()
    return "up to date" in lowered or "up-to-date" in lowered


def _parse_pr_number(*, url: str) -> int | None:
    """从形如 .../pull/<n> 的 PR url 末段解析 PR number；失败返回 None。"""
    return _parse_number_after(url=url, marker="/pull/")


def _parse_issue_number(*, url: str) -> int | None:
    """RFC-0002 T1：从形如 .../issues/<n> 的 issue url 末段解析 number；失败返回 None。"""
    return _parse_number_after(url=url, marker="/issues/")


def _parse_number_after(*, url: str, marker: str) -> int | None:
    """从 url 中 marker 之后的首段解析整数 number；找不到或非数字返回 None。"""
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
