"""Spec-0023/T3: release 模块 —— 把持续推进的 main 物化成一个版本（人唯一的宏观决策点）。

test 分支门控退役后（Spec-0023），main 成为日常自动流转分支、经 reviewer 闸+CI 全绿持续向前
推进；人不再每次"把 test 上线到 main"，而是在满意时跑 `openagents release` 发一个版本。release
预检通过则读取最新 vX.Y.Z tag，按 bump 语义化递增出新版本号，把 main 当前 HEAD 物化为一条
release/vX.Y.Z 分支并打不可变 tag。

预检（照搬 RFC-0012 决策 7「全过才扬升」，只把取绿对象从 test 换成 main）：
  ① 无 STATUS_BLOCKED 的 run —— 没有"评审反复不过、挂起等人"的工作被悄悄带进发布；
  ② 无带 needs-human 标签的 open PR —— 同①，从 GitHub 真源再确认一次；
  ③ github.branch_ci_green(main) —— main 分支 HEAD CI 全绿。
通过 → ensure_prerequisites() 兜底流程标签 → 物化版本：
  · git push origin main:refs/heads/release/vX.Y.Z  （以 main HEAD 新建发布分支）
  · git tag vX.Y.Z main && git push origin vX.Y.Z    （钉死不可变快照）

版本号（语义化三段 vX.Y.Z）：读 `git tag --list 'v*'` 取已发布的最大版本（**语义化**排序而非
字典序，避免 v0.10.0 < v0.9.0 之误），按 bump∈{patch,minor,major} 递增；仓库无任何版本 tag 时
首发起点 v0.1.0。版本号计算抽成纯函数，便于 hermetic 单测。

解耦设计（CLAUDE.md 理念 10）：以模块函数方式调 github.* 与注入的 state，git 操作走
subprocess——便于单测打桩三者保持 hermetic（不触达真实 gh/git）。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from openagents import github
from openagents.state import BLOCKED_LABEL, STATUS_BLOCKED, State

# Spec-0023/T3：语义化版本三段 vX.Y.Z；仓库无任何版本 tag 时的首发起点。
_INITIAL_VERSION = (0, 1, 0)
_VERSION_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_BUMPS = ("patch", "minor", "major")


@dataclass(frozen=True)
class ReleaseResult:
    """Spec-0023/T3：一次 release 的结果。

    released: 是否完成发布（预检全过且分支/tag 推送成功）。
    version: 本次发布的版本号 "vX.Y.Z"；未发布为 ""。
    reason: 失败时指明被哪个预检拦下（或 git 失败原因）；成功为 "ok"。
    """

    released: bool
    version: str
    reason: str


def release(*, state: State, bump: str = "patch", source: str = "main") -> ReleaseResult:
    """Spec-0023/T3：预检通过则把 source（main）当前 HEAD 物化为新版本分支 + tag。

    预检任一不过即返回 released=False 且 reason 指明原因，不建任何分支/tag（决策照搬
    RFC-0012 决策 7，只把取绿对象从 test 换成 main）。
    """
    blocked = [r for r in state.all_runs() if r.status == STATUS_BLOCKED]
    if blocked:
        issues = ", ".join(f"#{r.issue_number}" for r in blocked)
        return ReleaseResult(
            released=False, version="", reason=f"存在挂起（{STATUS_BLOCKED}）的 run：{issues}"
        )

    needs_human = [
        pr.number
        for pr in github.list_open_prs()
        if github.has_label(pr_number=pr.number, name=BLOCKED_LABEL)
    ]
    if needs_human:
        prs = ", ".join(f"#{n}" for n in needs_human)
        return ReleaseResult(
            released=False, version="", reason=f"存在待人介入（{BLOCKED_LABEL}）的 open PR：{prs}"
        )

    if not github.branch_ci_green(branch=source):
        return ReleaseResult(released=False, version="", reason=f"{source} 分支 CI 未全绿")

    version = _next_version(latest=_latest_version(), bump=bump)
    # 兜底流程标签就位（与原 promote 一致，幂等 no-op）；test 分支自举已随 Spec-0023 移除。
    github.ensure_prerequisites()
    _materialize_release(source=source, version=version)
    return ReleaseResult(released=True, version=version, reason="ok")


def _latest_version() -> tuple[int, int, int] | None:
    """已发布的最大语义化版本 (X, Y, Z)；仓库无任何 vX.Y.Z tag 时返回 None。

    按整数三元组比较取 max（语义化排序），而非字符串字典序——否则 v0.10.0 会被误判小于
    v0.9.0。非 vX.Y.Z 形态的 tag 一律忽略。
    """
    versions: list[tuple[int, int, int]] = []
    for tag in _list_version_tags():
        matched = _VERSION_RE.match(tag)
        if matched:
            versions.append((int(matched.group(1)), int(matched.group(2)), int(matched.group(3))))
    return max(versions) if versions else None


def _next_version(*, latest: tuple[int, int, int] | None, bump: str) -> str:
    """按 bump 从 latest 递增出下一个版本号字符串 "vX.Y.Z"（纯函数）。

    latest=None（仓库无任何版本 tag）→ 起点 v0.1.0（忽略 bump：首发即起点）。
    bump=patch → Z+1；minor → Y+1 且 Z 归零；major → X+1 且 Y、Z 归零。
    """
    if bump not in _BUMPS:
        raise ValueError(f"未知 bump：{bump!r}（应为 {', '.join(_BUMPS)} 之一）")
    if latest is None:
        major, minor, patch = _INITIAL_VERSION
        return f"v{major}.{minor}.{patch}"
    major, minor, patch = latest
    if bump == "patch":
        patch += 1
    elif bump == "minor":
        minor, patch = minor + 1, 0
    else:  # major
        major, minor, patch = major + 1, 0, 0
    return f"v{major}.{minor}.{patch}"


def _list_version_tags() -> list[str]:
    """`git tag --list 'v*'` → 非空 tag 名列表。隔离 subprocess 便于打桩。"""
    result = subprocess.run(
        ["git", "tag", "--list", "v*"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        reason = result.stderr.strip() or f"git tag --list 返回码 {result.returncode}"
        raise RuntimeError(f"读取已发布 tag 失败：{reason}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _materialize_release(*, source: str, version: str) -> None:
    """把 source 当前 HEAD 物化为 release/<version> 分支并打不可变 tag <version>。

    三步 git（均走 subprocess，便于打桩；分支与 tag 都基于同一个 source 提交，保证一致）：
      ① git push origin <source>:refs/heads/release/<version> —— 以 source HEAD 新建发布分支；
      ② git tag <version> <source>                            —— 在 source HEAD 上打 tag（本地）；
      ③ git push origin <version>                             —— 推送 tag，钉死远端不可变快照。
    任一步非零退出抛 RuntimeError（CLI 层转成干净一行提示）。
    """
    _git(
        args=["push", "origin", f"{source}:refs/heads/release/{version}"],
        action=f"物化发布分支 release/{version}",
    )
    _git(args=["tag", version, source], action=f"打 tag {version}")
    _git(args=["push", "origin", version], action=f"推送 tag {version}")


def _git(*, args: list[str], action: str) -> None:
    """跑一条 git 子命令；非零退出抛 RuntimeError，附带 action 语境与 stderr。"""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        reason = result.stderr.strip() or f"git {' '.join(args)} 返回码 {result.returncode}"
        raise RuntimeError(f"{action}失败：{reason}")
