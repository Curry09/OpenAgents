# Spec-0074/T2: utils.gitea —— github.py 同名公共面的 Gitea driver（/api/v1，stdlib urllib 零新依赖）。

"""Gitea forge driver：实现 vigil 新栈消费的 github.py 公共面，语义映射见 Spec-0074 正文表。

- **数据类与错误类型复用 github.py 定义**（Issue/PR/Comment/CheckStatus/…/GithubError）——公共面
  的事实契约在 github.py，本模块只换传输层与语义映射，消费方（经 forge 分发）零感知。
- **单收口 `_http`**：全部 REST 调用经它（Authorization 头带 token、30s 超时、5xx/网络异常指数退避
  ×3 对齐 github._run_gh 的瞬时错误纪律），也是 hermetic 测试的唯一打桩缝。
- **鉴权**：token 只从环境变量读（configure 声明变量名，缺省 GITEA_TOKEN）——延续「OpenAgents 不
  存 token」纪律。
- **PR 评论 = issue 评论**：Gitea 的 PR 与 issue 共享 index 命名空间与 comments 端点，故
  list_comments/post_comment 与 issue 版同端点。
- 语义降级点全部就地注释（mergeable 无 BEHIND、head_pushed_at 用 updated_at 近似、
  author_association 只识别配置 owner）——对齐 Spec-0074 Unresolved 的实证清单。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

# Spec-0074/T2: 公共面契约复用——数据类/错误/流程标签常量与 github.py 同一份定义。
from openagents.utils.github import (  # noqa: F401  re-export 供直接 import 本模块的调用方
    APPROVAL_LABEL,
    BLOCKED_LABEL,
    DISCOVERY_LABEL,
    DISPATCH_LABEL,
    PROCESS_LABELS,
    Blocker,
    CheckSnapshot,
    CheckStatus,
    Comment,
    GithubError,
    Issue,
    Mergeability,
    PR,
    PRSnapshot,
    _strip_diff_file_blocks,
)

# 与 github._GH_TIMEOUT_SECONDS / 重试常量对齐（同一瞬时错误纪律，换传输层不换策略）。
_TIMEOUT_SECONDS = 30
_RETRY_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_BASE = 1.0
_TRANSIENT_STATUSES = {502, 503, 504}

# Gitea 的 draft 表达是标题前缀（服务端默认 "WIP:"；部分版本 PR 响应带原生 draft 字段，两者都认）。
_WIP_PREFIXES = ("WIP:", "[WIP]")
_WIP_CANONICAL = "WIP: "

# 列表端点单页上限（Gitea 默认分页 30/页；守夜的工作集远小于此，超出属异常规模，先不做翻页）。
_LIST_LIMIT = 50

_DEFAULT_TOKEN_ENV = "GITEA_TOKEN"

# configure 装载的连接设置（模块级，与 github.py 的「gh 绑 cwd」等价的进程级绑定）。
_base_url: str | None = None
_owner: str | None = None
_repo: str | None = None
_token_env: str = _DEFAULT_TOKEN_ENV

# 标签名→id 缓存（Gitea 的 issue/label 操作要 id 不要名；竞态由 409/422 幂等回退兜，
# 对齐消费方 GiteaTracker 的既有实践）。
_label_ids: dict[str, int] = {}


@dataclass(frozen=True)
class _HttpResult:
    """一次 REST 往返的原始结果（status + 解析出的 JSON + 原文），供语义层按状态码分支。"""

    status: int
    data: Any
    text: str


def configure(*, settings: dict[str, Any]) -> None:
    """装载 Gitea 连接设置（forge.configure 透传）：base_url/owner/repo 必填，token_env 缺省 GITEA_TOKEN。

    只存「怎么连」，不存 token 本体；设置不完整 → GithubError（fail-loud，绝不带残缺配置上路）。
    """
    global _base_url, _owner, _repo, _token_env
    missing = [key for key in ("base_url", "owner", "repo") if not settings.get(key)]
    if missing:
        raise GithubError(f"forge=gitea 缺少连接设置 {missing}（.openagents/openagents.yml 的 gitea 段）")
    _base_url = str(settings["base_url"]).rstrip("/")
    _owner = str(settings["owner"])
    _repo = str(settings["repo"])
    _token_env = str(settings.get("token_env") or _DEFAULT_TOKEN_ENV)
    _label_ids.clear()


def _ensure_configured() -> tuple[str, str, str]:
    """取 (base_url, owner, repo)；未 configure → GithubError（提示配置入口）。"""
    if not (_base_url and _owner and _repo):
        raise GithubError("gitea driver 未配置——需 forge.configure(name='gitea', settings=...) 装载连接设置")
    return _base_url, _owner, _repo


def _token() -> str:
    """从环境变量读 token；缺失 → GithubError（token 本体从不落配置文件）。"""
    token = os.environ.get(_token_env, "").strip()
    if not token:
        raise GithubError(f"环境变量 {_token_env} 为空——Gitea 鉴权 token 只从环境变量读")
    return token


def _http(*, method: str, path: str, body: dict | None, query: dict | None) -> _HttpResult:
    """唯一的传输缝：一次 REST 往返（不含重试/状态码语义）。测试 monkeypatch 本函数即离网。

    网络层异常（连接失败/超时）抛 TimeoutError 归一为瞬时错误交 `_request` 重试；HTTP 非 2xx
    不在此层抛——语义（404 幂等 / 409 已存在 / 422 已最新）由调用方按 status 分支。
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
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310  base_url 来自本地配置
            status = int(response.status)
            text = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        text = exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TimeoutError(f"gitea {method} {path} 网络失败：{exc}") from exc
    return _HttpResult(status=status, data=_maybe_json(text=text), text=text)


def _maybe_json(*, text: str) -> Any:
    """响应体尝试按 JSON 解析；非 JSON（如 .diff 原文）返回 None，原文留在 text。"""
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
    """带瞬时重试的 REST 调用：5xx 网关故障/网络异常指数退避（对齐 github._run_gh 纪律）；
    非 2xx 且不在 allow 白名单 → GithubError（带状态码与端点，便于定位）。"""
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
        raise GithubError(f"gitea {method} {path} 返回 {result.status}：{result.text[:200]}")
    raise GithubError(f"gitea {method} {path} 重试耗尽")


def _repo_path(*, suffix: str) -> str:
    """repos/{owner}/{repo}/<suffix> 路径拼装（owner/repo 来自 configure）。"""
    _, owner, repo = _ensure_configured()
    return f"repos/{owner}/{repo}/{suffix}" if suffix else f"repos/{owner}/{repo}"


# --------------------------------------------------------------------------------------------------
# 标签（Gitea 的标签操作要 id：名→id 解析 + 缓存 + 竞态幂等回退）。
# --------------------------------------------------------------------------------------------------


def _refresh_label_cache() -> None:
    result = _request(
        method="GET",
        path=_repo_path(suffix="labels"),
        body=None,
        query={"limit": _LIST_LIMIT},
        allow=(),
    )
    for item in result.data or []:
        _label_ids[str(item.get("name") or "")] = int(item.get("id") or 0)


def _label_id(*, name: str) -> int:
    """标签名→id；未知名先刷新缓存，仍无 → GithubError（调用方应先 ensure_label）。"""
    if name not in _label_ids:
        _refresh_label_cache()
    if name not in _label_ids:
        raise GithubError(f"标签 {name!r} 不存在（先 ensure_label）")
    return _label_ids[name]


def ensure_label(*, name: str, color: str = "ededed", description: str = "") -> None:
    """幂等建标签：已存在（409/422）→ 刷新缓存复用（与 github.ensure_label 吞 already exists 同风格）。"""
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
    _refresh_label_cache()  # 竞态：他处已建 → 复用既有 id
    if name not in _label_ids:
        raise GithubError(f"标签 {name!r} 建后仍缺（gitea 返回 {result.status}）")


# --------------------------------------------------------------------------------------------------
# issue 侧。
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
        raise GithubError("gitea issue 详情返回了非预期的结构")
    return _issue_from(raw=result.data)


def list_issues(*, labels: list[str], state: str = "open") -> list[Issue]:
    """列 issue（`type=issues` 排除 PR——Gitea 的 issues 列表默认混含 PR）。

    多标签按 gh 的 OR 语义处理：逐标签查询后按 number 去重合并（Gitea 的 labels 查询参数是 AND 语义，
    不能直接逗号拼接）。labels 为空 = 不过滤。
    """
    queries: list[dict] = (
        [{"state": state, "type": "issues", "limit": _LIST_LIMIT, "labels": label} for label in labels]
        if labels
        else [{"state": state, "type": "issues", "limit": _LIST_LIMIT}]
    )
    seen: dict[int, Issue] = {}
    for query in queries:
        result = _request(
            method="GET", path=_repo_path(suffix="issues"), body=None, query=query, allow=()
        )
        for raw in result.data or []:
            issue = _issue_from(raw=raw)
            seen.setdefault(issue.number, issue)
    return list(seen.values())


def create_issue(*, title: str, body: str, labels: list[str]) -> Issue:
    """建 issue（标签走名→id 解析；未知标签先幂等补建，比照 gh 需预建的语义放宽为自愈）。"""
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
        raise GithubError("gitea 建 issue 未返回 number")
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
                # 语义降级：Gitea 无 authorAssociation——只把「配置里的 repo owner 本人」认作 OWNER，
                # 其余留空（fail-closed：读不到关系的评论不算拍板，见 Comment docstring）。
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
    """PR 评论——Gitea 的 PR 与 issue 共享 index 与 comments 端点，直接复用 issue 版。"""
    return list_issue_comments(number=pr_number)


def post_comment(*, pr_number: int, body: str) -> None:
    issue_comment(number=pr_number, body=body)


def issue_add_label(*, number: int, name: str) -> None:
    """幂等加标签（标签缺失先补建；对已带该标签的 issue 再 add 是服务端 no-op）。"""
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
    """幂等摘标签：标签名未知 / 服务端 404（本就不带）→ no-op（对齐 github._is_label_absent 风格）。"""
    if name not in _label_ids:
        _refresh_label_cache()
    if name not in _label_ids:
        return  # 仓库都没有这个标签 → issue 上必然没有，no-op
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
    """幂等关 issue：不存在（404）→ no-op；已关闭时 PATCH 本就幂等成功。"""
    _request(
        method="PATCH",
        path=_repo_path(suffix=f"issues/{number}"),
        body={"state": "closed"},
        query=None,
        allow=(404,),
    )


# --------------------------------------------------------------------------------------------------
# issue 原生依赖（blocked_by）——Gitea issue dependencies API。
# --------------------------------------------------------------------------------------------------


def list_blocked_by(*, number: int) -> list[Blocker]:
    """读「挡着本 issue 的 issue」列表；特性关闭/无端点（404）→ 视为无依赖（与 github 版同语义）。"""
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
        blockers.append(Blocker(number=int(raw["number"]), state=str(raw.get("state") or "").upper()))
    return blockers


def add_blocked_by(*, number: int, blocker_number: int) -> None:
    """给 issue 落一条依赖边（body 是 IssueMeta：index+owner+name）；已存在（409/422）幂等 no-op。"""
    _, owner, repo = _ensure_configured()
    _request(
        method="POST",
        path=_repo_path(suffix=f"issues/{number}/dependencies"),
        body={"index": blocker_number, "owner": owner, "name": repo},
        query=None,
        allow=(409, 422),
    )


# --------------------------------------------------------------------------------------------------
# PR 侧。
# --------------------------------------------------------------------------------------------------


def _get_pull(*, pr_number: int) -> dict:
    result = _request(
        method="GET", path=_repo_path(suffix=f"pulls/{pr_number}"), body=None, query=None, allow=()
    )
    if not isinstance(result.data, dict):
        raise GithubError("gitea PR 详情返回了非预期的结构")
    return result.data


def _pr_from(*, raw: dict) -> PR:
    return PR(number=int(raw["number"]), url=str(raw.get("html_url") or ""))


def create_pr(*, branch: str, title: str, body: str, base: str = "main", draft: bool = False) -> PR:
    """开 PR；draft 以 WIP 标题前缀表达（Gitea 的 draft 语义，mark_ready 时去前缀）。"""
    final_title = f"{_WIP_CANONICAL}{title}" if draft else title
    result = _request(
        method="POST",
        path=_repo_path(suffix="pulls"),
        body={"head": branch, "base": base, "title": final_title, "body": body},
        query=None,
        allow=(),
    )
    if not isinstance(result.data, dict) or result.data.get("number") is None:
        raise GithubError("gitea 建 PR 未返回 number")
    return _pr_from(raw=result.data)


def _pr_by_branch(*, branch: str, state: str) -> PR | None:
    """按 head 分支找最近的 PR——Gitea 列表端点无 head 过滤参数，客户端按 head.ref 过滤
    （sort=recentupdate 新→旧，取首个；分支与 issue 一一对应，实践上就一个）。"""
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
    """某分支最近的一个 PR，不限状态（merged/closed 都算）——`_sense` 的终止条件靠它可见已合并 PR。"""
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
        raise GithubError("gitea PR 未返回 head 分支名")
    return head_ref


def _pr_title_is_wip(*, title: str) -> bool:
    return any(title.startswith(prefix) for prefix in _WIP_PREFIXES)


def _pr_is_draft(*, raw: dict) -> bool:
    # 语义映射：原生 draft 字段（较新 Gitea）或 WIP 标题前缀（服务端默认约定），两者任一即 draft。
    return raw.get("draft") is True or _pr_title_is_wip(title=str(raw.get("title") or ""))


def _pr_state(*, raw: dict) -> str:
    # Gitea PR state 只有 open/closed；merged 是并列布尔——归一到 GitHub 的三态互斥语义。
    if raw.get("merged") is True:
        return "MERGED"
    return str(raw.get("state") or "").upper() or "OPEN"


def _pr_mergeable(*, raw: dict) -> tuple[str, str]:
    # 语义映射：Gitea mergeable 是 bool（无 BEHIND/UNKNOWN 细分）——false→CONFLICTING/DIRTY、
    # true→MERGEABLE/CLEAN、字段缺失（老版本/计算中）→UNKNOWN/UNKNOWN（守夜下一 tick 自愈）。
    # 无 BEHIND：base 落后不会被守夜主动 update_branch，合并时由服务端 merge 兜底（Spec-0074 Unresolved 3）。
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
    """draft 转正 = PATCH 去掉 WIP 标题前缀；本就非 draft → no-op。"""
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
    """一次 GET 取回 PR 现态快照（同源往返，与 github.pr_snapshot 同义）。

    语义降级：head_pushed_at 用 PR 的 updated_at 近似（Gitea 详情不带 head commit 提交时间；
    评论也会刷新它 → 看门狗只会更宽松、不会误报，检测「静默烂掉」略延迟）。
    """
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
    """把最新 base 并入 PR 分支；「已是最新」（Gitea 以 422 表达）→ False no-op（同 github 版语义）。"""
    style = "rebase" if rebase else "merge"
    result = _request(
        method="POST",
        path=_repo_path(suffix=f"pulls/{pr_number}/update"),
        body=None,
        query={"style": style},
        allow=(422,),
    )
    return 200 <= result.status < 300


def merge_pr(*, pr_number: int, method: str = "merge") -> None:
    """落合并（POST merge，Do=method）；已合并/暂不可合（405/409）时若确已 MERGED → 幂等 no-op。"""
    result = _request(
        method="POST",
        path=_repo_path(suffix=f"pulls/{pr_number}/merge"),
        body={"Do": method},
        query=None,
        allow=(405, 409),
    )
    if 200 <= result.status < 300:
        return
    if is_merged(pr_number=pr_number):
        return  # 已经合过 → 幂等
    raise GithubError(f"gitea 合并 PR #{pr_number} 失败（{result.status}）：{result.text[:200]}")


def code_fingerprint(
    *, pr_number: int, exclude_paths: tuple[str, ...] = ("docs/e2e-results/",)
) -> str:
    """PR 净 diff 指纹（.diff 原文端点 + 复用 github 的文件块剔除）；失败/空 → ""（fail-open 同 github 版）。"""
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
# CI（commit combined status——Gitea 没有 check runs，Actions/外部 CI 都落 commit status）。
# --------------------------------------------------------------------------------------------------

_STATUS_FAIL = {"failure", "error"}


def _combined_status(*, ref: str) -> tuple[str, list[dict]]:
    """GET /commits/{ref}/status → (combined state, statuses 明细)。零 status 时 state 归空串。"""
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
    """combined status 归类为 CheckStatus（fail 优先收集失败明细；零 status → pass，责任在调用方，
    与 github「无 check 视为 pass、守夜按计数另判」同一分工）。"""
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
    """当前 head 的 status 聚合 + 计数 + 最近开始时间（零 status 如实计 0——「没有 check」≠「绿」，
    判「等 CI」的责任在守夜调用方，与 github 版同一分工）。"""
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
    """分支 combined status 是否全绿：success 或零 status → True；pending/failure → False（同 github 版）。"""
    state, statuses = _combined_status(ref=branch)
    if not statuses:
        return True
    return state == "success"


# --------------------------------------------------------------------------------------------------
# 预检 / 建仓 / merger 命令文本。
# --------------------------------------------------------------------------------------------------


def ensure_prerequisites() -> None:
    """幂等前置检查：token 可读 + 仓库可达（鉴权/连通一次探测）+ 预建全部流程标签。"""
    _token()
    _request(method="GET", path=_repo_path(suffix=""), body=None, query=None, allow=())
    for label in PROCESS_LABELS:
        ensure_label(name=label)


def create_repo(*, name: str, private: bool) -> str:
    """新建远端仓库（冷启动兜底）：owner/repo 形态取 repo 段走 /user/repos，返回 clone url。"""
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
        raise GithubError("gitea 建仓未返回 clone url")
    return url


def merge_command_text(*, pr_number: int) -> str:
    """merger agent 的落合并命令——平台无关的隐藏 CLI（token 处理留在 driver 内，不进提示词）。"""
    return f"openagents merge-pr --pr {pr_number}"


def merge_verify_command_text(*, pr_number: int) -> str:
    """merger agent 的完成判据命令——merge-pr 幂等（已合并直接输出 MERGED），复跑即验证。"""
    return f"openagents merge-pr --pr {pr_number}"
