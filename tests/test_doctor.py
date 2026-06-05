"""RFC-0007: doctor 核心检查模块（T1）的契约测试。

全程 hermetic——monkeypatch `shutil.which` 与 `subprocess.run`，不触达真实 gh/git/claude。
覆盖：每项通过/失败两态、required 与可选项分档、has_blocking_failure 判定、失败项 fix 非空。
"""

from pathlib import Path

import openagents.doctor as doctor
from openagents.config import ProjectContext
from openagents.doctor import CheckResult, has_blocking_failure, run_checks


class _Proc:
    """最小 CompletedProcess 替身，仅暴露 doctor 用到的字段。"""

    def __init__(self, returncode, *, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _ctx(*, remote="https://github.com/acme/widget.git"):
    return ProjectContext(repo_root=Path("/repo"), remote=remote)


def _which_all_found(name):
    return f"/usr/bin/{name}"


def _patch_all_ok(monkeypatch):
    """让所有外部探测都成功：which 命中、gh auth status 退出 0。"""
    monkeypatch.setattr(doctor.shutil, "which", _which_all_found)
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *a, **k: _Proc(0, stdout="✓ Logged in to github.com as alice"),
    )


def _by_name(results, fragment):
    return next(r for r in results if fragment in r.name)


# --------------------------------------------------------------------------- #
# 全通过
# --------------------------------------------------------------------------- #


def test_run_checks_all_pass(monkeypatch):
    _patch_all_ok(monkeypatch)
    results = run_checks(ctx=_ctx())
    assert all(r.ok for r in results)
    assert not has_blocking_failure(results=results)
    # 通过项不带修复提示
    assert all(r.fix is None for r in results)


def test_run_checks_order_is_stable(monkeypatch):
    _patch_all_ok(monkeypatch)
    names = [r.name for r in run_checks(ctx=_ctx())]
    assert names == ["git 仓库", "origin 远端", "gh 鉴权", "后端 claude"]


# --------------------------------------------------------------------------- #
# git 仓库（必需）
# --------------------------------------------------------------------------- #


def test_git_missing_is_blocking(monkeypatch):
    _patch_all_ok(monkeypatch)
    results = run_checks(ctx=None)
    git = _by_name(results, "git")
    assert not git.ok
    assert git.required
    assert git.fix
    assert has_blocking_failure(results=results)


# --------------------------------------------------------------------------- #
# origin 远端（可选 → warning，不阻断）
# --------------------------------------------------------------------------- #


def test_missing_remote_is_warning_not_blocking(monkeypatch):
    _patch_all_ok(monkeypatch)
    results = run_checks(ctx=_ctx(remote=None))
    remote = _by_name(results, "origin")
    assert not remote.ok
    assert not remote.required
    assert remote.fix
    # 仅可选项失败 → 不阻断
    assert not has_blocking_failure(results=results)


def test_remote_present_passes(monkeypatch):
    _patch_all_ok(monkeypatch)
    results = run_checks(ctx=_ctx(remote="git@github.com:a/b.git"))
    remote = _by_name(results, "origin")
    assert remote.ok
    assert remote.detail == "git@github.com:a/b.git"


# --------------------------------------------------------------------------- #
# gh 安装 + 鉴权（必需）
# --------------------------------------------------------------------------- #


def test_gh_not_installed_is_blocking_without_subprocess(monkeypatch):
    # gh 未安装时应短路、绝不调用 subprocess。
    monkeypatch.setattr(
        doctor.shutil, "which", lambda name: None if name == "gh" else _which_all_found(name)
    )

    def _boom(*a, **k):
        raise AssertionError("gh 未安装时不应调用 subprocess")

    monkeypatch.setattr(doctor.subprocess, "run", _boom)
    results = run_checks(ctx=_ctx())
    gh = _by_name(results, "gh")
    assert not gh.ok
    assert gh.required
    assert gh.fix
    assert has_blocking_failure(results=results)


def test_gh_not_authed_is_blocking(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", _which_all_found)
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda *a, **k: _Proc(1, stderr="You are not logged into any GitHub hosts"),
    )
    results = run_checks(ctx=_ctx())
    gh = _by_name(results, "gh")
    assert not gh.ok
    assert gh.required
    assert gh.fix == "gh auth login"
    assert "not logged" in gh.detail.lower()
    assert has_blocking_failure(results=results)


# --------------------------------------------------------------------------- #
# 后端 claude（必需）
# --------------------------------------------------------------------------- #


def test_backend_missing_is_blocking(monkeypatch):
    monkeypatch.setattr(
        doctor.shutil, "which", lambda name: None if name == "claude" else _which_all_found(name)
    )
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: _Proc(0))
    results = run_checks(ctx=_ctx())
    backend = _by_name(results, "claude")
    assert not backend.ok
    assert backend.required
    assert backend.fix
    assert has_blocking_failure(results=results)


def test_backend_present_reports_path(monkeypatch):
    _patch_all_ok(monkeypatch)
    backend = _by_name(run_checks(ctx=_ctx()), "claude")
    assert backend.ok
    assert backend.detail == "/usr/bin/claude"


# --------------------------------------------------------------------------- #
# has_blocking_failure 判定 + 失败项 fix 非空
# --------------------------------------------------------------------------- #


def test_has_blocking_failure_ignores_optional_failures():
    results = [
        CheckResult(name="a", ok=True, required=True, detail="", fix=None),
        CheckResult(name="b", ok=False, required=False, detail="", fix="x"),
    ]
    assert not has_blocking_failure(results=results)


def test_has_blocking_failure_true_when_required_fails():
    results = [CheckResult(name="a", ok=False, required=True, detail="", fix="x")]
    assert has_blocking_failure(results=results)


def test_every_failing_check_carries_a_fix(monkeypatch):
    # 整机皆坏：which 全 None、gh auth 非零、非 git 仓库——每个失败项都要有可执行修复提示。
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    monkeypatch.setattr(doctor.subprocess, "run", lambda *a, **k: _Proc(1, stderr="not logged in"))
    results = run_checks(ctx=None)
    failing = [r for r in results if not r.ok]
    assert failing
    for r in failing:
        assert r.fix, f"{r.name} 失败却无修复提示"
