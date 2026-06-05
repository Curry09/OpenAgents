"""RFC-0007: openagents doctor —— 环境健康自检（pipeline 预检）。

纯只读地体检 issue→RFC→PR 闭环所依赖的外部前置条件，产出一组结构化
`CheckResult`（不打印、不退出）。打印与退出码归 cli.py（决策 3：检查项与渲染解耦）。

检查项分「必需 / 可选」两档（决策 1），退出码只由必需项决定：
- git 仓库绑定 / gh 安装+鉴权 / 后端 claude → 必需（缺则流水线必然失败）；
- origin 远端 → 可选（纯本地仓库仍可起草 RFC，到推送/开 PR 才需要 → warning）。

所有检查都是只读探测（复用 config.resolve_project 的结果、`gh auth status`、
`shutil.which`），零副作用、零新依赖（决策 5）。
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from openagents.backends.claude_code import CLAUDE_BIN
from openagents.config import ProjectContext

# RFC-0007: gh CLI 可执行名做成常量，便于测试 mock / 替换（与 github 层一致取向）。
_GH_BIN = "gh"

# RFC-0007: 探测类子进程的超时上限，避免体检本身被卡死（与 github._run_gh 同档）。
_PROBE_TIMEOUT = 30


@dataclass(frozen=True)
class CheckResult:
    """One environment check outcome.

    RFC-0007: doctor 的结构化检查结果（决策 3：纯数据，供 cli 渲染 / 未来 board 复用）。
    """

    # RFC-0007: 检查项名（如 "git 仓库" / "gh 鉴权" / "后端 claude"）
    name: str
    # RFC-0007: 是否通过
    ok: bool
    # RFC-0007: 是否为必需项——决定退出码（决策 1）
    required: bool
    # RFC-0007: 通过/失败的可读明细（如版本号、路径、错误摘要）
    detail: str
    # RFC-0007: 失败时的修复提示（可执行的下一步，决策 4）；通过时为 None
    fix: str | None


def _first_line(*, text: str) -> str:
    """Return the first non-empty line of text, stripped.

    RFC-0007: gh / 探测命令的输出常为多行，明细只取首行以保持清单单行可读。
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _check_git(*, ctx: ProjectContext | None) -> CheckResult:
    """Check the cwd is a bound git repository.

    RFC-0007: 复用 config.resolve_project 的结果（ctx 为 None 即非 git 仓库）。必需项。
    """
    name = "git 仓库"
    if ctx is None:
        return CheckResult(
            name=name,
            ok=False,
            required=True,
            detail="当前目录不是 git 仓库",
            fix="cd 到目标仓库，或执行 git init 初始化",
        )
    return CheckResult(
        name=name, ok=True, required=True, detail=f"仓库根：{ctx.repo_root}", fix=None
    )


def _check_remote(*, ctx: ProjectContext | None) -> CheckResult:
    """Check the origin remote is configured.

    RFC-0007: 可选项（决策 1）——纯本地仓库也能起草 RFC，到推送/开 PR 才需要远端，
    故缺失记为 warning 而非 blocking。
    """
    name = "origin 远端"
    remote = ctx.remote if ctx is not None else None
    if remote:
        return CheckResult(name=name, ok=True, required=False, detail=remote, fix=None)
    return CheckResult(
        name=name,
        ok=False,
        required=False,
        detail="未配置 origin 远端（仅本地仓库）",
        fix="git remote add origin <url>（推送 / 开 PR 时才必需）",
    )


def _check_gh_auth() -> CheckResult:
    """Check gh CLI is installed and authenticated.

    RFC-0007: 沿用 github 层「走 gh 子进程」的既定决策——先 `shutil.which` 判安装，
    再以 `gh auth status` 的退出码判鉴权（决策 5：只读探测）。必需项。
    """
    name = "gh 鉴权"
    # 1. 先判 gh 是否安装；未安装则不必再跑子进程
    if shutil.which(_GH_BIN) is None:
        return CheckResult(
            name=name,
            ok=False,
            required=True,
            detail="未找到 gh CLI",
            fix="安装 GitHub CLI：https://cli.github.com",
        )
    # 2. `gh auth status` 退出码 0 即已鉴权；非零判定未鉴权（只看退出码，缺点见 RFC）
    result = subprocess.run(
        [_GH_BIN, "auth", "status"],
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT,
        check=False,
    )
    if result.returncode == 0:
        detail = _first_line(text=result.stdout or result.stderr) or "已鉴权"
        return CheckResult(name=name, ok=True, required=True, detail=detail, fix=None)
    detail = _first_line(text=result.stderr or result.stdout) or "gh 未鉴权"
    return CheckResult(name=name, ok=False, required=True, detail=detail, fix="gh auth login")


def _check_backend() -> CheckResult:
    """Check the backend coding CLI (claude) is on PATH.

    RFC-0007: 只查 PATH 存在性（`shutil.which(CLAUDE_BIN)`），不实跑推理（避免耗时/计费，
    缺点见 RFC）。必需项。
    """
    name = "后端 claude"
    path = shutil.which(CLAUDE_BIN)
    if path is None:
        return CheckResult(
            name=name,
            ok=False,
            required=True,
            detail=f"PATH 中未找到 {CLAUDE_BIN}",
            fix=f"安装 Claude Code CLI 并确保 {CLAUDE_BIN} 在 PATH 中",
        )
    return CheckResult(name=name, ok=True, required=True, detail=path, fix=None)


def run_checks(*, ctx: ProjectContext | None) -> list[CheckResult]:
    """Run all environment checks and return their results.

    RFC-0007: 编排全部检查项，返回结果列表（不打印、不退出）。ctx 由调用方用
    config.resolve_project() 取得（可能为 None）。
    """
    return [
        _check_git(ctx=ctx),
        _check_remote(ctx=ctx),
        _check_gh_auth(),
        _check_backend(),
    ]


def has_blocking_failure(*, results: list[CheckResult]) -> bool:
    """Whether any required check failed.

    RFC-0007: cli 据此决定退出码（决策 1：退出码只由必需项决定）。
    """
    return any(r.required and not r.ok for r in results)
