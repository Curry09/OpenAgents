"""Spec-0068/T2: N 线程并发对同一主仓 .git 建 worktree 的零锁竞争回归测试。

真起 N(≥4) 条 threading.Thread 对**同一个临时 git 仓**并发调 Workspace.prepare（各带不同
issue_number/branch，base=main），join 后断言：
  - 全部返回有效 worktree 路径、目录真实建成；
  - 零 WorkspaceError；
  - 捕获到的 git stderr 不含 'cannot lock ref' / 'could not lock working tree'。

用真实本地 git（bare origin + 工作仓），不触网络 / LLM / GitHub——prepare 的 fetch 走本地 file://
远端。锁在 openagents/utils/workspace.py 的 _GIT_MUTATION_LOCK：把 prepare 整段共享 .git 变更
串行化，消除 packed-refs / worktree 管理锁竞争与 prune 误清半成品（P2）。

对照（文档化，不长期跑）：去掉 _GIT_MUTATION_LOCK（把两处 `with` 段去掉）后，N 越大越易复现
`cannot lock ref … File exists` / `could not lock working tree`，本测试转 flaky/失败——正是本锁要消除的。
"""

import subprocess
import threading
from pathlib import Path

import pytest

from openagents.utils.workspace import Workspace

_N_WORKERS = 6  # ≥4：加大并发窗口以稳定暴露锁竞争（去锁则 flaky）


def _run_git(*, cwd: Path, args: list[str]) -> None:
    """跑一条 git 命令（测试夹具用，失败即抛，带 stderr 便于定位）。"""
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=60
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败：{proc.stderr}")


def _make_origin_and_work(*, tmp_path: Path) -> Path:
    """建一个带 main 分支的 bare origin + 一个以它为 origin 的工作仓，返回工作仓路径。"""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    _run_git(cwd=tmp_path, args=["init", "--bare", "-b", "main", str(origin)])
    _run_git(cwd=tmp_path, args=["clone", str(origin), str(work)])
    _run_git(cwd=work, args=["config", "user.email", "t@t.io"])
    _run_git(cwd=work, args=["config", "user.name", "t"])
    (work / "README.md").write_text("seed\n")
    _run_git(cwd=work, args=["add", "README.md"])
    _run_git(cwd=work, args=["commit", "-m", "seed"])
    _run_git(cwd=work, args=["push", "origin", "main"])
    return work


class _StderrCapturingWorkspace(Workspace):
    """Workspace 子类：记录每条 git 子命令的 stderr，供并发后断言无锁竞争字样。

    check=False 的 git 命令（worktree remove/prune、branch -D）出锁错时**不抛**，故必须
    抓其 stderr——单看「零 WorkspaceError」会漏掉这类静默锁错。
    """

    def __init__(self, *, work_dir: Path, sink: list) -> None:
        super().__init__(work_dir=work_dir)
        self._sink = sink

    def _git(self, *, args, cwd, check):
        result = super()._git(args=args, cwd=cwd, check=check)
        if result.stderr:
            self._sink.append(result.stderr)
        return result


def test_concurrent_prepare_same_repo_no_git_lock_contention(tmp_path):
    work = _make_origin_and_work(tmp_path=tmp_path)

    stderr_sink: list[str] = []
    errors: list[BaseException] = []
    paths: dict[int, Path] = {}
    barrier = threading.Barrier(_N_WORKERS)  # 让 N 条线程尽量同时冲进 .git 变更段

    def _worker(n: int) -> None:
        ws = _StderrCapturingWorkspace(work_dir=work, sink=stderr_sink)
        try:
            barrier.wait(timeout=30)
            path = ws.prepare(issue_number=n, branch=f"openagents/issue-{n}", base="main")
            paths[n] = path
        except BaseException as exc:  # noqa: BLE001 —— 收集任意异常统一断言
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(n,)) for n in range(_N_WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    # 1. 零 WorkspaceError / 任何异常。
    assert not errors, f"并发 prepare 出错（锁竞争？）：{[repr(e) for e in errors]}"
    # 2. 全部 worktree 都建成、目录真实存在、互不相同。
    assert len(paths) == _N_WORKERS
    for n, path in paths.items():
        assert path.exists(), f"issue-{n} 的 worktree 未建成：{path}"
    assert len({str(p) for p in paths.values()}) == _N_WORKERS
    # 3. 捕获的 git stderr 不含内核锁竞争字样。
    joined = "\n".join(stderr_sink)
    assert "cannot lock ref" not in joined, f"出现 ref 锁竞争：{joined}"
    assert "could not lock working tree" not in joined, f"出现 worktree 管理锁竞争：{joined}"


def test_concurrent_prepare_lock_serializes_git_mutation_segment(tmp_path):
    # 直接验证互斥：探针在持锁段内断言至多一个线程在 .git 变更段（并发观测到的最大并发度=1）。
    work = _make_origin_and_work(tmp_path=tmp_path)
    from openagents.utils import workspace as ws_module

    active = {"n": 0, "max": 0}
    guard = threading.Lock()
    errors: list[BaseException] = []
    barrier = threading.Barrier(_N_WORKERS)

    real_git = Workspace._git

    def _observing_git(self, *, args, cwd, check):
        # 只在 .git 变更子命令上采样并发度（fetch/worktree/branch）。
        sub = args[0] if args else ""
        sample = sub in {"fetch", "worktree", "branch"}
        if sample:
            with guard:
                active["n"] += 1
                active["max"] = max(active["max"], active["n"])
        try:
            return real_git(self, args=args, cwd=cwd, check=check)
        finally:
            if sample:
                with guard:
                    active["n"] -= 1

    def _worker(n: int) -> None:
        ws = Workspace(work_dir=work)
        try:
            barrier.wait(timeout=30)
            ws.prepare(issue_number=n, branch=f"openagents/issue-{n}", base="main")
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    import unittest.mock as _mock

    with _mock.patch.object(ws_module.Workspace, "_git", _observing_git):
        threads = [threading.Thread(target=_worker, args=(n,)) for n in range(_N_WORKERS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)

    assert not errors, f"并发 prepare 出错：{[repr(e) for e in errors]}"
    # 锁把变更段串起来 → 任一时刻至多一个线程在 .git 变更子命令内。
    assert active["max"] == 1, f"锁未串行化 .git 变更段，观测最大并发度={active['max']}"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
