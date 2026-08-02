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

import hashlib
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

    Spec-0065/T2：新增 author_association（GitHub 原生 `authorAssociation`：OWNER / MEMBER /
    COLLABORATOR / CONTRIBUTOR / NONE …）——vigil 的准入人闸靠它认「谁说的话算数」。缺省 ""（未知）
    是**故意的 fail-closed**：读不到关系 ⇒ 不是维护者 ⇒ 这句话不算拍板。
    """

    id: str
    author: str
    body: str
    created_at: str
    author_association: str = ""


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


def pr_for_branch(*, branch: str) -> PR | None:
    """某分支上**最近的一个 PR，不限状态**（open / merged / closed 都算）；从没开过则 None。

    # Spec-0065/T2：`_sense` 必须用它，不能用 `find_pr_by_branch`（后者只查 open）。一个 PR 一被合并就从
    # open 列表里消失——守夜若沿用 open-only 的查法，会在合并的**下一圈**把这个 issue 读成「还没有 PR」，
    # 于是走分支④再开一个 PR 把同一个 issue 重做一遍。merged 是 `_classify` 的终止条件，而终止条件只能从
    # 「那个 PR 现在是什么状态」读出来，故这里必须能看见已合并的 PR。
    # `--state all` + `--limit 1`：gh 按新→旧排，取最近一个（分支与 issue 一一对应，实践上就一个）。
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
    """RFC-0001 T3：`gh pr view <n> --json comments`，解析为 Comment 列表。

    comment id 是 node id 字符串；同时取 createdAt 供消息层按时间判定新评论。
    """
    data = _gh_json(
        ["pr", "view", str(pr_number), "--json", "comments"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh pr view 返回了非预期的结构")
    return _parse_comments(data=data)


def _parse_comments(*, data: dict) -> list[Comment]:
    """`--json comments` 的公共解析：comment id 是 node id 字符串；createdAt 供按时间判定新评论。

    Spec-0065/T2：同时解析 `authorAssociation`（说话的人跟本仓库是什么关系）——vigil 准入人闸凭它
    认维护者。字段缺失时留空串（fail-closed：读不到关系的评论不算拍板）。
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
    """Spec-0043/T1：给 issue 贴评论（`gh issue comment <number> --body <body>`）。

    post_comment 走 `gh pr comment`（PR 专用）——但 issuecheck 拦下一个 issue 冻结时它**还没有
    PR**，无从贴评论。补一个对称的 issue 级出口，与 issue_add_label / issue_remove_label 走
    `gh issue edit/view` 的 issue 级操作族并列。签名由调用方（orchestrator 经 identity.sign）盖
    ——本函数保持「对 gh 的薄封装、不含业务逻辑」（理念 10）。失败由 _run_gh 抛 GithubError
    （自带 RFC-0010 瞬时错误重试）。不改 post_comment 及任何既有函数（零回归）。
    """
    _run_gh(
        ["issue", "comment", str(number), "--body", body],
        allow_returncodes=set(),
    )


def list_issue_comments(*, number: int) -> list[Comment]:
    """Spec-0049/T1：读 issue 全部评论（`gh issue view <n> --json comments`）。

    与 list_comments（PR 版，走 `gh pr view`）对称，是 issue 级读原语——认领去重需要读
    issue 上的「署名认领便签」评论判归属/年龄（identity.latest_claim 消费）。gh 的 comments
    结构含 author.login / body / createdAt，逐条投影成既有 Comment（id 为 node id 字符串；
    先后顺序用 created_at 判，不能用 id 排序）。失败由 _gh_json 抛 GithubError。
    """
    data = _gh_json(
        ["issue", "view", str(number), "--json", "comments"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict):
        raise GithubError("gh issue view 返回了非预期的结构")
    return _parse_comments(data=data)  # Spec-0065/T2：与 list_comments 共用解析，别留两份拷贝


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


def merge_command_text(*, pr_number: int) -> str:
    """Spec-0074/T1：merger agent 落合并动作的命令文本——GitHub 侧即既有 gh 命令（行为零变化）。

    merger 提示词的平台命令参数化为 $merge_command 占位符后，由 stages.merge 经本函数注入；
    Gitea driver 的同名函数返回 `openagents merge-pr --pr N`（token 处理留在 driver 内，不进提示词）。
    """
    return f"gh pr merge {pr_number} --merge"


def merge_verify_command_text(*, pr_number: int) -> str:
    """Spec-0074/T1：merger agent 验证合并完成的命令文本——输出含 MERGED 即视为已合并。"""
    return f"gh pr view {pr_number} --json state"


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
    认领对象是 **issue**，故补一组走 `gh issue edit/view` 的 issue 级操作。

    Spec-0049/T1：认领打标改由本函数**幂等 add**（不再经已退役的 remove-then-add stamp）——
    对已带该标签的 issue 再 add 是 gh 侧 no-op、**不产生 labeled/unlabeled 事件**，从根上消除
    「两后端每轮互相撕掉对方标签」的物理来源；认领新鲜度改由「署名认领便签」评论年龄承载
    （identity.latest_claim）。失败由 _run_gh 抛 GithubError。
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
    PR 也成立——供拉式同步下 poll 循环枚举当前待处理的 open PR。无则返回 []。
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
    冲突或其它失败照常抛 GithubError，供拉式同步调用方（messages 可合并性预检）捕获后留言（决策 4）。
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
    """Spec-0053/T2（Spec-0055/T5 加 exclude_paths）：取 PR 相对其 base 的净 diff 指纹。

    `gh pr diff` 返回 GitHub 侧计算的三点语义（base...head）unified diff——「这个 PR 在 base 之上加了
    什么」。它在「只是 base 前进、PR 自身未改」（如 update_branch 无冲突并入 main）时保持逐字节不变，
    故是 sticky 短路（Spec-0053）判「代码状态是否变」的正确口径，而非 head tree SHA。对照 k8s
    lgtm store_tree_hash。

    Spec-0055/T5：`exclude_paths` 从 diff 里剔掉这些前缀下的**文件块**（默认排除 `docs/e2e-results/`）
    再哈希——使「executor 写证据的 commit」不改**源码**指纹，避免 e2e 幂等闸/代码 sticky 被证据 commit
    自触发重跑重审（收敛的关键，见 Spec-0055）。传空元组即不排除（旧口径）。

    本函数是对 gh 的薄封装（理念 10）：只做「取 diff + 剔证据文件块 + 定长哈希」，不含「要不要短路」的
    业务判定。gh 故障（非零退出抛 GithubError）或（剔除后）空输出 → 返回 ""（fail-open）：调用方据空串
    落回照常，sticky 永不基于「算不出指纹」做跳过。
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
    """Spec-0055/T5：从 unified diff 里剔掉 `b/<path>` 落在 exclude_paths 前缀下的整个文件块。

    git diff 以 `diff --git a/<path> b/<path>` 起每个文件块；按这些行切块，丢弃 b 路径命中任一前缀的块，
    其余原样拼回。纯字符串处理、无副作用（便于单测）。首块之前的前言（罕见）归属「无归属」一并保留。
    """
    lines = diff.splitlines(keepends=True)
    kept: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("diff --git "):
            # 取 b/ 后的路径判是否排除；解析失败按「不排除」保守保留。
            parts = line.split(" b/", 1)
            b_path = parts[1].rstrip("\n") if len(parts) == 2 else ""
            skipping = any(b_path.startswith(prefix) for prefix in exclude_paths)
        if not skipping:
            kept.append(line)
    return "".join(kept)


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


# --------------------------------------------------------------------------------------------------
# Spec-0065/T2：level-triggered `_sense` 需要的四类原生读——PR 快照（含 head sha / label）、
# check 快照（含**计数**与开始时间）、issue 原生依赖（blocked_by）。仍是薄 gh 封装：只如实回传 GitHub
# 字段，零业务判定（「零个 check 算不算等 CI」「哪种 mergeable 算冲突」都由 recipes.vigil 决定）。
# --------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PRSnapshot:
    """一次 `gh pr view` 取回的 PR 现态快照——**同源、一次往返**，不会读到互相矛盾的中间态。

    `_sense` 要在同一时刻拿到 state / head sha / label / mergeable：分四次读会在 agent 正好 push 的
    瞬间读到「旧 head + 新 mergeable」这种自相矛盾的组合，而分支表的顺序依赖（冲突必须在 CI 前判）正
    建立在「这些字段属于同一个 head」之上。

    state: OPEN | CLOSED | MERGED（GitHub 原值大写）。
    labels: PR 当前所带标签名（`review-approved:<sha7>` 等裁决落处）。
    mergeable / merge_state_status: 同 `Mergeability`，原值大写，不归一化。
    head_pushed_at: 当前 head commit 的提交时间（ISO）——喂看门狗的 `last_progress_at`。**不可省**：
      一个「刚推上去、CI 一个 check 都没起、也无任何评论」的 PR，除了它自己没有任何时间戳可读；缺了它
      `last_progress_at` 恒为 None → 看门狗永远不响 → 「CI 永不启动」这条死法（护栏二要抓的正主）会静默
      烂在那里。head 一变它自动前移，计时随之归零。
    is_draft: PR 是否为 draft（GitHub 原生事实）。**置于末位、默认 False**——`_sense` 把它当每 tick 复检的
      一等事实（Spec-0017/T1），与 state/head/mergeable **同源一次 `gh pr view` 往返**读入（不复用独立的
      `github.is_draft`，免每 tick 多一次网络往返）。缺省 False 使既有构造点/测试 fake 零改动仍可实例化。
    """

    number: int
    state: str
    head_sha: str
    labels: tuple[str, ...]
    mergeable: str
    merge_state_status: str
    head_pushed_at: str
    is_draft: bool = (
        False  # Spec-0017/T1: draft 升为快照事实（末位默认 False，避 Spec-0031 式 fake 破裂）
    )


@dataclass(frozen=True)
class CheckSnapshot:
    """`gh pr checks` 的聚合 + **计数** + 最近开始时间。

    `count` 不能省：`check_status` 把「零个 check」归成 `pass`（无 CI 的仓库照常放行），但守夜必须把
    「当前 head 上一个 check 都没有」读成**还在等 CI**（workflow 可能刚触发、也可能永不触发——后者正是
    看门狗要抓的死法），绝不能读成「CI 绿了」→ 直接合并一份没跑过 CI 的代码。

    `latest_started_at`: 最近一次 check 的开始时间（ISO，无 check 时为空串）——喂 `_Clock`，让「卡了
    多久」成为当前态的纯函数（零本地记忆）。
    """

    state: str  # pass | fail | pending（同 CheckStatus.state）
    count: int
    latest_started_at: str


@dataclass(frozen=True)
class Blocker:
    """issue 原生依赖（`blocked_by`）的对端：挡着当前 issue 的那个 issue。

    响应自带 `state`，故一次调用同时拿到「边」和「blocker 关没关」→ `deps_done` 直接算出，无需第二轮
    查询。(https://docs.github.com/en/rest/issues/issue-dependencies)
    """

    number: int
    state: str  # OPEN | CLOSED（原值大写）


def pr_snapshot(*, pr_number: int) -> PRSnapshot:
    """Spec-0065/T2：一次 `gh pr view` 取回 PR 的 state / head sha / labels / mergeable / head 推送时间。"""
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
        raise GithubError("gh pr view 返回了非预期的结构")
    return PRSnapshot(
        number=int(data["number"]),
        state=str(data.get("state") or "").upper(),
        head_sha=str(data.get("headRefOid") or ""),
        labels=_parse_label_names(raw=data),
        mergeable=str(data.get("mergeable") or "UNKNOWN").upper(),
        merge_state_status=str(data.get("mergeStateStatus") or "UNKNOWN").upper(),
        head_pushed_at=_head_committed_at(commits=data.get("commits")),
        # Spec-0017/T1: isDraft 与其余现态同源读入；true/false/缺失/非布尔 → 默认 False（比照 is_draft 容错）。
        is_draft=data.get("isDraft") is True,
    )


def _head_committed_at(*, commits: Any) -> str:
    """PR 的 commits 列表 → 末条（即 head）的 `committedDate`；空/异常结构 → 空串（看门狗据此不看门）。"""
    if not isinstance(commits, list) or not commits:
        return ""
    last = commits[-1]
    return str(last.get("committedDate") or "") if isinstance(last, dict) else ""


def check_snapshot(*, pr_number: int) -> CheckSnapshot:
    """Spec-0065/T2：读**当前 head** 上的 check（`gh pr checks` 天然按 head 报），带计数与最近开始时间。

    `gh pr checks` 在仓库无任何 CI 时以非零退出并报 "no checks reported"——照 `check_status` 的容错风格
    吞掉，但**计数如实为 0**（区分「没有 check」与「check 全绿」的责任在调用方，见 `CheckSnapshot`）。
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
    """Spec-0065/T2：当前 head 上失败 check 的摘要（薄引用 `check_status`），供喂回 fix-ci 的 agent。"""
    return check_status(pr_number=pr_number).failed_logs


def issue_rest_id(*, number: int) -> int:
    """Spec-0065/T2：取 issue 的 REST 数字 id（`POST …/dependencies/blocked_by` 的请求体要它，不是 number）。"""
    data = _gh_json(
        ["api", f"{_REPO_PLACEHOLDER}/issues/{number}", "--jq", "{id: .id}"],
        allow_returncodes=set(),
    )
    if not isinstance(data, dict) or data.get("id") is None:
        raise GithubError(f"gh api 未返回 issue #{number} 的 id")
    return int(data["id"])


def list_blocked_by(*, number: int) -> list[Blocker]:
    """Spec-0065/T2：读 issue 的原生依赖边（`GET …/issues/{n}/dependencies/blocked_by`，2025-08 GA）。

    响应自带各 blocker 的 `state`，一次调用同时给出「边」与「blocker 关没关」。仓库未开启该特性 / 无边
    时返回 []（404 归成空，不抛——依赖是可选特性，缺它只意味着「无依赖」）。
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
    """Spec-0065/T2：给 issue 落一条原生依赖边（`POST …/issues/{n}/dependencies/blocked_by`）。

    请求体要的是 blocker 的 **REST 数字 id**（不是 issue number），故先 `issue_rest_id` 换一次。边已存在
    时 GitHub 返回 4xx——吞掉视为成功（幂等，与 `ensure_label` 吞 "already exists" 同一容错风格）。
    """
    blocker_id = issue_rest_id(number=blocker_number)
    try:
        _run_gh(
            [
                "api",
                "--method",
                "POST",
                f"{_REPO_PLACEHOLDER}/issues/{number}/dependencies/blocked_by",
                # Spec-0065/T2: 必须是 `-F`（类型推断 → JSON number），不能是 `-f`（一律当字符串发）。
                # dependencies API 的 issue_id 声明为 integer，发字符串会 422，且 422 不在下面的
                # already/duplicate 白名单里 → 直接抛 → 依赖边一条也落不下去。
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
