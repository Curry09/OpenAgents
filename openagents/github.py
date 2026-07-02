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
from datetime import UTC, datetime
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

# RFC-0012：check-runs API 的 conclusion 取值——视为「绿」的集合（与 _CHECK_PASS_STATES
# 同义，但 REST check-runs 用 conclusion 字段、取值小写）。其余 conclusion 或未完成 → 非绿。
_CHECK_RUN_PASS_CONCLUSIONS = {"success", "skipped", "neutral"}

# RFC-0012：gh api 的 owner/repo 占位符——gh 会按当前仓库自动替换，无需显式拼 owner/repo。
_REPO_PLACEHOLDER = "repos/{owner}/{repo}"

# RFC-0015：流程标签——单一来源。三个标签常量原散在三处（cli.DISCOVERY_LABEL /
# messages.APPROVAL_LABEL / state.BLOCKED_LABEL），同一字符串散落易漂移。落点选 github：
# 它是依赖图的叶子模块（不 import 任何 openagents 内部模块），cli/messages/state 反向引用
# 它零循环依赖风险；ensure_prerequisites 与标签同处一文件，引用最直接。三处既有公共名改为
# 从此 re-import 的别名，所有调用点零改动（见 RFC-0015 决策 2）。
DISCOVERY_LABEL: str = "openagents"  # issue 发现门控
APPROVAL_LABEL: str = "rfc-approved"  # RFC 全票 PASS 的批准信号
BLOCKED_LABEL: str = "needs-human"  # 超 K 轮兜底挂起、待人介入
# Spec-0039/T1：第 4 个流程标签——跨后端可见的「已派发/认领中」信号。某后端判 fresh 决定派单
# 时给 issue 打上它，其它后端在发现段读到即跳过，把多后端重复派单的时间窗从「起草时长（分钟
# 级）」压到「建 worktree（秒级）」。并入 PROCESS_LABELS 同源管理，即被 ensure_prerequisites
# 的幂等自举一并预建（新增标签零改动 ensure_prerequisites）。
DISPATCH_LABEL: str = "openagents-dispatching"  # issue 已被某后端认领、派单中
PROCESS_LABELS: tuple[str, ...] = (
    DISCOVERY_LABEL,
    APPROVAL_LABEL,
    BLOCKED_LABEL,
    DISPATCH_LABEL,
)


class GithubError(Exception):
    """gh CLI 调用失败（返回非零）时抛出，携带可读的失败原因。"""


@dataclass(frozen=True)
class Issue:
    """一个 GitHub issue 的最小投影。

    Spec-0039/T1：新增 labels（issue 当前所带标签名，带默认值 ()）——既有 `Issue(number,
    title,body)` 构造零改动。vigil 发现段的认领闸（闸 3）直接读 `issue.labels` 快检是否带
    DISPATCH_LABEL，不再额外发一次网络请求（labels 随 list_issues/get_issue 一次取回）。
    """

    number: int
    title: str
    body: str
    labels: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class Mergeability:
    """Spec-0022/T1：PR 的可合并性快照——如实承载 GitHub 的两个原始字段，零业务判定。

    mergeable: GitHub `mergeable` 原值——MERGEABLE / CONFLICTING / UNKNOWN。
    merge_state_status: GitHub `mergeStateStatus` 原值——CLEAN / DIRTY / BLOCKED /
        BEHIND / UNKNOWN / …（保持大写字符串，不在本层归一化或转布尔）。

    用 frozen dataclass（仿 CheckStatus）而非裸 tuple/dict，让调用方按字段名读、避免
    位置歧义；「哪种组合算不可合并」的判定留给调用方（理念 10：github 是薄 gh 封装）。
    """

    mergeable: str
    merge_state_status: str


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
    """RFC-0001 T3：`gh issue view <n> --json number,title,body,labels`。

    Spec-0039/T1：--json 增 labels 字段并解析进 Issue.labels（供认领闸快检），既有
    number/title/body 解析不变。
    """
    data = _gh_json(
        ["issue", "view", str(number), "--json", "number,title,body,labels"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh issue view 返回了非预期的结构")
    return Issue(
        number=int(data["number"]),
        title=data.get("title") or "",
        body=data.get("body") or "",
        labels=_parse_label_names(raw=data),
    )


def _parse_label_names(*, raw: dict[str, Any]) -> tuple[str, ...]:
    """Spec-0039/T1：从 gh `--json labels` 的 `[{"name": ...}, ...]` 解析出标签名元组。

    gh 的 labels 结构是对象数组（每项含 name/color/description）；这里只取 name，缺失/None
    容错为空。get_issue / list_issues 共用，保证 Issue.labels 解析单一来源。
    """
    return tuple((label or {}).get("name") or "" for label in raw.get("labels") or [])


def list_issues(*, labels: list[str], state: str = "open") -> list[Issue]:
    """RFC-0004 T1：列出（可按标签门控的）issue，供 vigil 守夜人发现新 issue。

    走 `gh issue list --state <state> [--label L ...] --json number,title,body`。
    labels 为空表示不按标签过滤（列出该 state 的全部 issue）；多个 label 由 gh 以
    并集（OR）语义处理（任一命中即返回）。复用决策 3 的 gh 子进程封装与既有 Issue
    数据模型，不新增数据类型（CLAUDE.md 理念 1）。
    """
    args = ["issue", "list", "--state", state, "--json", "number,title,body,labels"]
    for label in labels:
        args += ["--label", label]
    data = _gh_json(args, allow_returncodes=set())
    rows = data if isinstance(data, list) else []
    # Spec-0039/T1：--json 增 labels 并解析，使发现段闸 3 能直接读 issue.labels 快检认领标签。
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


def create_pr(*, branch: str, title: str, body: str, base: str = "main", draft: bool = False) -> PR:
    """RFC-0001 T3：`gh pr create`，从 stdout 的 PR url 解析出 number 与 url。

    RFC-0005 决策 2：draft=True 时追加 `--draft`，使 PR 先以草稿形态承载 RFC，
    待人评审/批准后由 mark_ready 转正。默认 False，保持既有调用向后兼容。

    Spec-0023/T1：base 形参（→ `--base`）默认 main——test 分支门控退役后 main 成为日常
    自动流转分支，issue→PR 全程以 main 为 base、经 reviewer 闸+CI 全绿自动合回 main。
    start_rfc 透传基线（默认值随 orchestrator.DEFAULT_BASE 一同从 test 改 main）。
    """
    args = ["pr", "create", "--head", branch, "--base", base, "--title", title, "--body", body]
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


def merge_pr(*, pr_number: int, method: str = "merge") -> None:
    """RFC-0012 决策 1：代码闸全票 PASS 后自动合入（`gh pr merge <n> --<method>`）。

    method ∈ {"merge", "squash", "rebase"}（默认 merge，见未解决问题 4）；合入其 base（Spec-0023
    后为 main），使 main 成为持续推进的日常分支。失败由 _run_gh 抛 GithubError。
    """
    _run_gh(["pr", "merge", str(pr_number), f"--{method}"], allow_returncodes=set())


def add_label(*, pr_number: int, name: str) -> None:
    """RFC-0012 决策 1/3：给 PR 打标签（`gh pr edit <n> --add-label <name>`）。

    供 reviewer 闸自动打 rfc-approved（RFC 全票 PASS）、或卡住兜底打 needs-human（决策 5）。
    与 has_label 对称：标签是结构化信号，不与讨论评论混淆。
    """
    _run_gh(["pr", "edit", str(pr_number), "--add-label", name], allow_returncodes=set())


def remove_label(*, pr_number: int, name: str) -> None:
    """Spec-0032/T2：摘掉 PR 上的标签（`gh pr edit <n> --remove-label <name>`），与 add_label 对称。

    供解挂分支自动摘 needs-human（检测到人回新评论时）。幂等容错：标签本就不在时 gh 以非零退出
    并报「not found / does not have ... label」之类——吞掉视为成功 no-op（与 ensure_label 吞
    "already exists"、close_issue 吞 "already closed" 同一容错风格），使「人已先手动摘了标签、
    框架又摘一次」不报错。其它 gh 错误（鉴权、瞬时穿透重试后仍败）照常抛 GithubError。
    """
    try:
        _run_gh(["pr", "edit", str(pr_number), "--remove-label", name], allow_returncodes=set())
    except GithubError as exc:
        if _is_label_absent(reason=str(exc)):
            return
        raise


def issue_add_label(*, number: int, name: str) -> None:
    """Spec-0039/T1：给 issue 打标签（`gh issue edit <n> --add-label <name>`），与 add_label 对称。

    add_label / remove_label / has_label 都作用于 **PR**（`gh pr edit/view`），而发现段的
    认领对象是 **issue**，故补一组走 `gh issue edit/view` 的 issue 级操作。认领打标经
    issue_stamp_label（remove-then-add）复用本函数。失败由 _run_gh 抛 GithubError。
    """
    _run_gh(["issue", "edit", str(number), "--add-label", name], allow_returncodes=set())


def issue_remove_label(*, number: int, name: str) -> None:
    """Spec-0039/T1：摘掉 issue 上的标签（`gh issue edit <n> --remove-label <name>`）。

    与 remove_label（PR 版）对称、复用同一 _is_label_absent 幂等识别：标签本就不在时 gh 以
    非零退出并报「not found / does not have ... label / does not exist」——吞掉视为成功 no-op
    （PR 已开出后清理认领标签、或人已手动摘除时不报错）。其它 gh 错误照常抛 GithubError。
    """
    try:
        _run_gh(["issue", "edit", str(number), "--remove-label", name], allow_returncodes=set())
    except GithubError as exc:
        if _is_label_absent(reason=str(exc)):
            return
        raise


def issue_stamp_label(*, number: int, name: str) -> None:
    """Spec-0039/T1：给 issue「盖」认领标签——remove-then-add，保证产生一个全新的 `labeled` 事件。

    为什么不能直接 `--add-label`：对已带该标签的 issue 再 add 是 no-op，**不刷新时间线时戳**；
    而认领年龄取该标签最近 `labeled` 事件的 created_at，若不刷新，回收僵尸认领（对已带标签的
    issue 重新认领）后会立刻又被判过期而抖动。故先幂等 remove（吞「本不在」）、再 add，使每次
    认领都在时间线上落一个新的 `labeled` 事件，让「认领年龄」对首次认领与重新认领都有良定义。
    """
    issue_remove_label(number=number, name=name)
    issue_add_label(number=number, name=name)


def issue_label_age_seconds(*, number: int, name: str) -> float | None:
    """Spec-0039/T1：issue 上某标签最近一次 `labeled` 事件距今的秒数；无该事件返回 None。

    走 `gh api repos/{owner}/{repo}/issues/<n>/timeline`（跨后端共享的时钟），筛出 event==
    "labeled" 且 label.name==name 的事件，取最近一条 created_at（ISO 8601，字典序即时序），
    返回 `now - created_at` 秒数。供发现段判「认领是否过期（僵尸认领）」——仅在「带认领标签且
    远端无分支」这一罕见路径调用，不拖慢常态扫描。

    必须 `--paginate`：timeline 端点固定按**时间升序**（最旧在前）返回、且不支持排序/倒序参数，
    单页 `per_page=100` 只取**最旧的 100 条**事件；而认领 `labeled` 事件总在时间线**尾部**（新近
    打上）。对「打认领标签前已积累 >100 条事件」的老 issue（vigil 恰会派单这类），不翻页就取不到
    那条 labeled → 错判 None → 僵尸认领永远回收不掉、认领永久卡死。故 `--paginate --slurp` 拉全部
    页（`--slurp` 把各页数组包成「数组的数组」，保持单次 JSON 可解析），跨全页取 max(created_at)。
    """
    data = _gh_json(
        [
            "api",
            f"{_REPO_PLACEHOLDER}/issues/{number}/timeline?per_page=100",
            "--paginate",
            "--slurp",
        ],
        allow_returncodes=set(),
    )
    # --slurp 输出为「数组的数组」（每页一个数组）；无分页/单页时也可能是「事件数组」。逐层摊平。
    rows: list[Any] = []
    for item in data if isinstance(data, list) else []:
        rows.extend(item) if isinstance(item, list) else rows.append(item)
    stamps = [
        str(event.get("created_at") or "")
        for event in rows
        if isinstance(event, dict)
        and str(event.get("event") or "") == "labeled"
        and (event.get("label") or {}).get("name") == name
        and event.get("created_at")
    ]
    if not stamps:
        return None
    latest = max(stamps)  # ISO 8601 → 字典序即时间序，取最近一次 labeled
    stamped_at = datetime.fromisoformat(latest.replace("Z", "+00:00"))
    return (datetime.now(UTC) - stamped_at).total_seconds()


def _is_label_absent(*, reason: str) -> bool:
    """Spec-0032/T2：remove_label 的「标签本不在」幂等识别——判定要「窄」（同 _is_not_found 风格）。

    gh 对摘一个 PR 上不存在的标签以非零退出，文案大致为 "could not remove label: 'X' not found"
    或 "label does not exist / pull request does not have ... label"；大小写不一，统一小写后按
    子串匹配。只认这两类业务性结果，其它 gh 错误一律不命中、照常上抛。
    """
    lowered = reason.lower()
    return "not found" in lowered or "does not have" in lowered or "does not exist" in lowered


def close_issue(*, number: int) -> None:
    """RFC-0017 T1：显式关闭 issue（`gh issue close <number>`）。

    背景（RFC-0017）：`Closes #N` 关键字只在 PR 合入**默认分支**时自动关 issue，而
    RFC-0012 起 PR 以 test（非默认分支）为 base、合回 test，关键字永不触发——故由框架
    在「工作落进 test → STATUS_DONE」时显式关。与决策 3「一律走 gh CLI」一致，经唯一收口
    点 _run_gh 调用，自带 RFC-0010 的瞬时错误重试，零额外依赖、零新数据类型（理念 1）。

    幂等容错（决策 2）：issue 已是 CLOSED 或不存在 → 视为成功 no-op、静默返回，与
    ensure_label 吞 "already exists"、update_branch 吞 "already up to date" 同一风格。
    两条合并路径会在多轮 poll 重复触发同一 issue，重复关闭不能把守夜循环打断。容错判定要
    「窄」——只吞「已关闭/不存在」这两类业务性结果，其它 gh 错误（鉴权、瞬时穿透重试后
    仍败）照常抛 GithubError。
    """
    try:
        _run_gh(["issue", "close", str(number)], allow_returncodes=set())
    except GithubError as exc:
        if _is_already_closed_or_absent(reason=str(exc)):
            return  # issue 已关闭 / 不存在 → 幂等 no-op
        raise


def ensure_prerequisites() -> None:
    """Spec-0023/T1：幂等确保流程结构性 prerequisite 就位：全部流程标签。

    单一兜底来源——集中声明「流程依赖哪些 prerequisite」，由 init/release/vigil 三入口统一
    调用，根除各入口零散且不完整的兜底（缺 needs-human/rfc-approved 标签致 add_label 报
    not found）。

    test 分支门控退役后（Spec-0023），日常 base 改为恒存在的默认分支 main，无需任何分支
    自举——原先兜底建 test 分支的 ensure_branch 一并移除，本函数收敛为只预建流程标签。
    缺标签就新建、已存在就 no-op：只编排既有幂等的 ensure_label，不新造任何容错（幂等性、
    瞬时错误重试 RFC-0010、already exists 归一化全由 ensure_label / _run_gh 承担）。
    """
    for label in PROCESS_LABELS:
        ensure_label(name=label)


def branch_ci_green(*, branch: str) -> bool:
    """RFC-0012 决策 7（Spec-0023/T1 平移到 release 预检）：分支 HEAD 的 check-runs 是否全绿。

    走 `gh api repos/{owner}/{repo}/commits/<branch>/check-runs`，逐个 check-run 判定：
    任一未完成（status != completed）→ False（pending 不算绿）；任一 conclusion 不在
    _CHECK_RUN_PASS_CONCLUSIONS → False；全部通过（或无 check）→ True（与 check_status
    「无 check 视为 pass」一致：green-by-construction 下 main 通常本就绿）。函数签名/语义
    不变，仅调用方从 promote 对 test 取绿改为 release 对 main 取绿。
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
    """gh api 的「资源不存在」识别（404 / not found）——供 _is_already_closed_or_absent 复用。"""
    lowered = reason.lower()
    return "not found" in lowered or "404" in lowered


def _is_already_closed_or_absent(*, reason: str) -> bool:
    """RFC-0017 决策 2：close_issue 的「幂等 no-op」识别——issue 已关闭或不存在。

    判定要「窄」（与 _is_not_found / _is_already_up_to_date 同风格）：只认这两类业务性
    结果。gh issue close 对已关闭的 issue 报 "already closed"；对不存在的 issue 走 GraphQL，
    报 "Could not resolve to an Issue ..."（不含 "not found" 字样），故在 _is_not_found 之外
    再补 "could not resolve"。其它 gh 错误一律不命中、照常上抛。
    """
    lowered = reason.lower()
    if "already closed" in lowered or "could not resolve" in lowered:
        return True
    return _is_not_found(reason=reason)


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


def mergeability(*, pr_number: int) -> Mergeability:
    """Spec-0022/T1：查 PR 可合并性（`gh pr view <n> --json mergeable,mergeStateStatus`）。

    结构镜像 is_merged / is_closed：经唯一收口点 _gh_json 跑 gh（自带 RFC-0010 瞬时重试），
    一次取回两字段（同源快照、省一次往返、避免读到不一致的中间态）。只如实回传 GitHub
    原值大写字符串，不做任何归一化或布尔判定——「哪种组合算冲突」由调用方（Spec-0022/T2）决定。

    UNKNOWN（GitHub 异步尚未算完，刚 push 常见）是**合法返回值**，照实回传、本层不视为错误。
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "mergeable,mergeStateStatus"],
        allow_returncodes=set(),
    )
    # 非 dict 或缺任一字段都算非预期结构（缺字段 ≠ UNKNOWN：后者是 gh 返回的合法大写值，
    # 照实回传；前者是结构异常，比照 is_merged 抛 GithubError）。
    if (
        not isinstance(data, dict)
        or data.get("mergeable") is None
        or data.get("mergeStateStatus") is None
    ):
        raise GithubError("gh pr view 返回了非预期的结构")
    return Mergeability(
        mergeable=str(data["mergeable"]).upper(),
        merge_state_status=str(data["mergeStateStatus"]).upper(),
    )


def pr_head_branch(*, pr_number: int) -> str:
    """issue #48：取 PR 的 head 分支名（`gh pr view <n> --json headRefName`）。

    供索引冲突自愈在本地 checkout 该分支、把 base 并入后重渲 OVERVIEW 再 push。
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "headRefName"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict) or not data.get("headRefName"):
        raise GithubError("gh pr view 未返回 headRefName")
    return str(data["headRefName"])


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


def is_open(*, pr_number: int) -> bool:
    """Spec-0042/T2：PR 当前是否为 OPEN（`gh pr view <n> --json state` == "OPEN"）。

    与 is_merged / is_closed 对称——GitHub PR 的 state 有 OPEN / CLOSED / MERGED 三态且互斥。
    供消息层识别「reopen」：本地已置 closed 的 run，其 PR 若在 GitHub 上又变回 OPEN 即为被重开，
    据此复活该 run（close 可逆，与不可逆的 merged 相反）。不改既有函数（零回归）。
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "state"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view 返回了非预期的结构")
    return str(data.get("state") or "").upper() == "OPEN"


def is_draft(*, pr_number: int) -> bool:
    """Spec-0042/T2：PR 当前是否为 draft（`gh pr view <n> --json isDraft`）。

    供消息层在 reopen 复活时推断阶段：draft PR（RFC 未批、代码未写完）→ 复活到 rfc-review；
    已转正 PR → 复活到 pr-open。与 has_label(rfc-approved) 互为旁证。isDraft 缺失/非布尔视为
    非预期结构（比照 is_closed 抛 GithubError）。不改既有函数（零回归）。
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "isDraft"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict) or not isinstance(data.get("isDraft"), bool):
        raise GithubError("gh pr view 返回了非预期的结构")
    return data["isDraft"]


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
