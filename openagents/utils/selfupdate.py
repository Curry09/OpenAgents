"""# Spec-0070/T1: openagents 自更新预检——每次 `openagents` 命令前保证跑在最新快照。

`openagents` 装成一份 uv tool 快照（`~/.local/bin/openagents`），与 git 源码工作区解耦：源码 `git pull`
后，快照仍跑旧代码，须 `uv tool install --force` 重装才更新。本模块在 `cli.main()` 的 `parse_args` 之前跑
一段预检：检测记录分支是否落后源仓库远端，落后且可安全更新则 `git pull --ff-only` → `uv tool install
--force` → `os.execvp` 重执行原命令（用户当次即刻跑最新）；否则打印可操作提示并 **fail-open 继续**。

设计要点（issue #146 约束）：
- **纯函数 + 可注入 seam**：`run`（默认 `subprocess.run`）/ `execvp`（默认 `os.execvp`）/ `environ`
  （默认 `os.environ`）/ `stderr`（默认 `sys.stderr`）全部外部注入，测试 100% hermetic，不触真实 git/uv/
  网络/shell。
- **cadence=每次，fail-open**：任何 fetch/网络/子进程失败一律只打软提示并返回，`precheck` 对调用方**永不
  抛**——离线可用、绝不阻断真实命令。
- **保护开发者 WIP**：仅当「当前分支 == 记录分支」且「工作区干净」才自动 `pull --ff-only`；否则视为不可
  安全更新，走「提示 + 继续」，**绝不切分支、绝不动脏工作区**。
- **重执行防循环**：重执行的子进程带上 `OPENAGENTS_SELFUPDATE_DONE=1`，它一进来就短路，杜绝无限自更新。
- **可关**：`OPENAGENTS_NO_SELF_UPDATE=1` 硬开关整段关闭（供 CI/测试/hermetic）；仅接 `openagents` 入口，
  `spec` 独立命令不接。
- **奥卡姆**：不引入配置框架、不加网络库；git/uv 全走子进程（本模块属 utils 确定性层，正是机械子进程操作
  的归口）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Spec-0070/T1: 环境变量旋钮——三把守卫。DISABLE 硬关整段预检；DONE 是重执行守卫（重执行子进程带上它 →
# 一进来就短路，防无限循环）；HOME 覆盖 ~/.openagents 落点（对齐 agent_config/fleet_config 的 expanduser）。
DISABLE_ENV = "OPENAGENTS_NO_SELF_UPDATE"
DONE_ENV = "OPENAGENTS_SELFUPDATE_DONE"
HOME_ENV = "OPENAGENTS_HOME"

# Spec-0070/T1: 子进程网络 git 超时秒数（镜像 utils.git._GIT_NET_TIMEOUT_SECONDS = 30）。git fetch 走网络、
# 可能被半开 socket 挂死；超时即中断，最外层按 fail-open 转软提示继续——绝不无限卡住真实命令。
_GIT_NET_TIMEOUT_SECONDS = 30

# Spec-0070/T1: 侦测「cwd 是否 OpenAgents 源仓库」的两个必要标志——toplevel 下有本包 CLI 且 pyproject 声明
# openagents 入口。二者同时满足才认，避免把随便一个 python 仓库误判成源仓库。
_SOURCE_MARKER_CLI = Path("openagents") / "cli.py"
_SOURCE_MARKER_PYPROJECT = "pyproject.toml"

__all__ = [
    "DISABLE_ENV",
    "DONE_ENV",
    "HOME_ENV",
    "SourceConfig",
    "detect_source_repo",
    "home_dir",
    "load_source_config",
    "precheck",
    "save_source_config",
    "source_config_path",
]

# subprocess.run / os.execvp 的注入别名类型（测试传 fake，生产传真身）。
_Runner = Callable[..., subprocess.CompletedProcess[str]]
_Execvp = Callable[[str, Sequence[str]], Any]


@dataclass(frozen=True)
class SourceConfig:
    """# Spec-0070/T1: 源仓库定位记录（落盘 `~/.openagents/source.json`）。

    运行的快照不知道源码在哪（cwd 通常是*目标*项目而非 OpenAgents 源仓库），故显式记录源仓库路径 + 追踪的
    remote/branch（默认 `origin`/`main`）。仅当「当前分支 == branch」且工作区干净才自动更新（保护 WIP）。
    """

    repo_path: str
    remote: str = "origin"
    branch: str = "main"


def home_dir(*, environ: Mapping[str, str]) -> Path:
    """`OPENAGENTS_HOME` 覆盖点或默认 `~/.openagents`（对齐既有 .openagents 命名空间）。"""
    override = environ.get(HOME_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".openagents"


def source_config_path(*, environ: Mapping[str, str]) -> Path:
    """源仓库定位记录的落盘路径 `<home>/source.json`。"""
    return home_dir(environ=environ) / "source.json"


def load_source_config(*, environ: Mapping[str, str]) -> SourceConfig | None:
    """读回 `source.json` → `SourceConfig`；缺文件/坏 JSON/缺字段一律返回 None（fail-open，不打扰）。"""
    path = source_config_path(environ=environ)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    repo_path = raw.get("repo_path") if isinstance(raw, dict) else None
    if not repo_path:
        return None
    return SourceConfig(
        repo_path=str(repo_path),
        remote=str(raw.get("remote") or "origin"),
        branch=str(raw.get("branch") or "main"),
    )


def save_source_config(*, config: SourceConfig, environ: Mapping[str, str]) -> None:
    """把 `SourceConfig` 落盘 `source.json`（幂等；父目录不存在则建）。"""
    path = source_config_path(environ=environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"repo_path": config.repo_path, "remote": config.remote, "branch": config.branch}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def detect_source_repo(*, cwd: Path, run: _Runner, environ: Mapping[str, str]) -> Path | None:
    """若 cwd 处在 OpenAgents 源仓库内 → 自侦测源仓库 toplevel 并 `save_source_config`（自配置）。

    判据：cwd 的 git toplevel 下同时有 `openagents/cli.py` 与 `pyproject.toml` 且后者声明 openagents 入口。
    满足则用 toplevel + 默认 origin/main 落盘（幂等）。非 git / 非源仓库 / 任何异常 → 返回 None（不落盘）。
    """
    try:
        result = run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=_GIT_NET_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if getattr(result, "returncode", 1) != 0:
        return None
    toplevel = Path(result.stdout.strip())
    if not _looks_like_source_repo(toplevel=toplevel):
        return None
    save_source_config(config=SourceConfig(repo_path=str(toplevel)), environ=environ)
    return toplevel


def _looks_like_source_repo(*, toplevel: Path) -> bool:
    """toplevel 下有本包 CLI + 声明 openagents 入口的 pyproject → 认作 OpenAgents 源仓库。"""
    if not (toplevel / _SOURCE_MARKER_CLI).is_file():
        return False
    pyproject = toplevel / _SOURCE_MARKER_PYPROJECT
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    # 声明了 `openagents = "openagents.cli:main"` console_script 才算源仓库（而非随便一个含 openagents/ 的仓库）。
    return "openagents.cli:main" in text


def precheck(
    *,
    argv: Sequence[str],
    environ: Any = None,
    run: _Runner | None = None,
    execvp: _Execvp | None = None,
    stderr: Any = None,
) -> None:
    """自更新预检唯一编排出口——`cli.main()` 在 `parse_args` 之前调，`argv` 传 `sys.argv`（重执行要完整 argv）。

    顺序即短路优先级：DISABLE/DONE 两把守卫 → 自侦测落盘 → 无 source.json 短路 → fetch → 比对落后 → 安全闸
    → pull --ff-only → uv tool install --force → execvp 重执行（置 DONE=1）。**任何步骤异常一律被最外层捕获
    转软提示 + 返回**，对调用方永不抛（fail-open，绝不阻断真实命令、绝不动脏工作区）。
    """
    environ = environ if environ is not None else _os_environ()
    run = run if run is not None else subprocess.run
    execvp = execvp if execvp is not None else _os_execvp()
    stderr = stderr if stderr is not None else sys.stderr

    # ① 硬开关：整段关闭（CI/测试/hermetic）。 ② 重执行守卫：重执行子进程带 DONE=1 → 一进来即短路，防循环。
    if environ.get(DISABLE_ENV):
        return
    if environ.get(DONE_ENV):
        return

    try:
        # execvp 成功即进程镜像被替换、不返回；execvp 抛错则被这里兜住转软提示（fail-open）。
        _precheck_inner(argv=argv, environ=environ, run=run, execvp=execvp, stderr=stderr)
    except Exception as exc:  # noqa: BLE001 - fail-open 是本模块铁律：任何异常都不许阻断真实命令
        _warn(stderr=stderr, message=f"自更新预检跳过（非致命）：{exc}")


def _precheck_inner(
    *,
    argv: Sequence[str],
    environ: Mapping[str, str],
    run: _Runner,
    execvp: _Execvp,
    stderr: Any,
) -> None:
    # ③ 自侦测：在源仓库内跑任一命令时把源仓库路径落盘（幂等自配置）。目标项目内跑则 None、不落盘。
    detect_source_repo(cwd=Path.cwd(), run=run, environ=environ)

    # ④ 无 source.json：还没在源仓库里跑过、无从检测 → 静默返回（不打扰）。
    config = load_source_config(environ=environ)
    if config is None:
        return
    src = Path(config.repo_path)

    # ⑤ git fetch（走网络，超时/失败 → fail-open 软提示返回，离线可用）。
    fetched = _git(
        run=run,
        cwd=src,
        args=["fetch", config.remote, config.branch],
    )
    if fetched is None or fetched.returncode != 0:
        _warn(stderr=stderr, message="自更新预检：git fetch 失败或超时，跳过更新（离线不阻断）。")
        return

    # ⑥ 比对是否落后：记录分支落后 remote/branch 多少个提交；不落后 → 静默返回（已是最新）。
    if not _is_behind(run=run, cwd=src, remote=config.remote, branch=config.branch):
        return

    # ⑦ 安全闸：仅当「当前分支 == 记录分支」且「工作区干净」才自动更新——否则绝不动 WIP，走提示 + 继续。
    if not _is_safe_to_update(run=run, cwd=src, branch=config.branch):
        _warn(stderr=stderr, message=_manual_update_hint(config=config))
        return

    # ⑧ pull --ff-only（只快进、绝不制造合并提交；失败 → fail-open 提示返回）。
    pulled = _git(run=run, cwd=src, args=["pull", "--ff-only", config.remote, config.branch])
    if pulled is None or pulled.returncode != 0:
        _warn(stderr=stderr, message=_manual_update_hint(config=config))
        return

    # ⑨ uv tool install --force：把新源码重装成快照（失败 → fail-open 提示返回）。
    installed = _uv_reinstall(run=run, src=src)
    if installed is None or installed.returncode != 0:
        _warn(stderr=stderr, message=_manual_update_hint(config=config))
        return

    # ⑩ execvp 重执行原命令：进程镜像被最新快照替换、PID 不变、DONE=1 使重执行的自己跳过预检（防循环）。
    _warn(stderr=stderr, message="✓ 已更新到最新版 openagents，正在用新版重跑当前命令…")
    _reexec(argv=argv, environ=environ, execvp=execvp)


def _is_behind(*, run: _Runner, cwd: Path, remote: str, branch: str) -> bool:
    """记录分支是否落后 `<remote>/<branch>`（`git rev-list --count <branch>..<remote>/<branch>` > 0）。"""
    upstream = f"{remote}/{branch}"
    result = _git(run=run, cwd=cwd, args=["rev-list", "--count", f"{branch}..{upstream}"])
    if result is None or result.returncode != 0:
        return False
    try:
        return int(result.stdout.strip() or "0") > 0
    except ValueError:
        return False


def _is_safe_to_update(*, run: _Runner, cwd: Path, branch: str) -> bool:
    """当前分支 == 记录分支 且 工作区干净 → 可安全自动更新（否则绝不动开发者 WIP）。"""
    head = _git(run=run, cwd=cwd, args=["rev-parse", "--abbrev-ref", "HEAD"])
    if head is None or head.returncode != 0 or head.stdout.strip() != branch:
        return False
    porcelain = _git(run=run, cwd=cwd, args=["status", "--porcelain"])
    if porcelain is None or porcelain.returncode != 0:
        return False
    return porcelain.stdout.strip() == ""


def _git(*, run: _Runner, cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str] | None:
    """在 cwd 内跑一条 git 子命令，带网络超时；任何 OSError/子进程异常 → None（由调用方 fail-open 处理）。"""
    try:
        return run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=_GIT_NET_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _uv_reinstall(*, run: _Runner, src: Path) -> subprocess.CompletedProcess[str] | None:
    """`uv tool install --force --from <src> openagents`——把最新源码重装成快照；异常 → None。"""
    try:
        return run(
            ["uv", "tool", "install", "--force", "--from", str(src), "openagents"],
            capture_output=True,
            text=True,
            timeout=_GIT_NET_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _reexec(*, argv: Sequence[str], environ: Mapping[str, str], execvp: _Execvp) -> None:
    """置 `DONE=1` 后 `execvp` 重执行原命令。成功则进程被替换、不返回；execvp 环境经 os.environ 生效。"""
    # execvp 继承的是当前进程 environ，故直接写进 os.environ（注入点已把它作 environ 传入，测试用 fake dict）。
    try:
        environ[DONE_ENV] = "1"  # type: ignore[index] - 生产传的是 os.environ（可写）；测试传 dict（可写）
    except TypeError:
        pass
    argv = list(argv)
    if not argv:
        return
    execvp(argv[0], argv)


def _manual_update_hint(*, config: SourceConfig) -> str:
    """不可安全自动更新时的可操作提示：给出手动更新的确切命令。"""
    return (
        "⚠ openagents 已落后源仓库远端，但当前不可安全自动更新（分支非记录分支 / 工作区有未提交改动）。\n"
        f"  手动更新：git -C {config.repo_path} pull --ff-only && "
        f"uv tool install --force --from {config.repo_path} openagents\n"
        f"  （或 export {DISABLE_ENV}=1 关闭本预检）"
    )


def _warn(*, stderr: Any, message: str) -> None:
    """软提示——一律走 stderr、不阻断（fail-open 的输出面）。"""
    print(message, file=stderr, flush=True)


def _os_environ() -> Any:
    # 延迟到调用时取 os.environ，保持顶层纯（便于测试注入 fake）。
    import os

    return os.environ


def _os_execvp() -> _Execvp:
    import os

    return os.execvp
