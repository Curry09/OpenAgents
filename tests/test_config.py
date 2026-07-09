"""RFC-0001 T1: 项目绑定（决策 10）的契约测试。

resolve_project: 以 cwd 解析 git root + origin 远端，非 git 仓库返回 None。
ensure_project: preflight；非交互模式下缺 git/remote 抛 ProjectNotReady。
"""

import subprocess

import pytest

from openagents.utils.config import ProjectContext, ProjectNotReady, ensure_project, resolve_project


def _git(*args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _init_repo(path, *, remote=None):
    _git("init", cwd=path)
    if remote is not None:
        _git("remote", "add", "origin", remote, cwd=path)


def test_resolve_project_returns_none_outside_git(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_project() is None


def test_resolve_project_finds_root_and_remote(tmp_path, monkeypatch):
    _init_repo(tmp_path, remote="https://github.com/acme/widget.git")
    monkeypatch.chdir(tmp_path)

    ctx = resolve_project()

    assert ctx is not None
    assert ctx.repo_root == tmp_path.resolve()
    assert ctx.remote == "https://github.com/acme/widget.git"


def test_resolve_project_no_remote_yields_none_remote(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    ctx = resolve_project()

    assert ctx is not None
    assert ctx.remote is None


def test_resolve_project_from_subdirectory(tmp_path, monkeypatch):
    _init_repo(tmp_path, remote="https://github.com/acme/widget.git")
    sub = tmp_path / "pkg" / "deep"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)

    ctx = resolve_project()

    assert ctx is not None
    assert ctx.repo_root == tmp_path.resolve()


def test_ensure_project_non_interactive_raises_without_git(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ProjectNotReady):
        ensure_project(interactive=False)


def test_ensure_project_non_interactive_raises_without_remote(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ProjectNotReady):
        ensure_project(interactive=False)


def test_ensure_project_returns_context_when_ready(tmp_path, monkeypatch):
    _init_repo(tmp_path, remote="https://github.com/acme/widget.git")
    monkeypatch.chdir(tmp_path)

    ctx = ensure_project(interactive=False)

    assert isinstance(ctx, ProjectContext)
    assert ctx.remote == "https://github.com/acme/widget.git"


def test_ensure_project_interactive_declines_git_init(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    with pytest.raises(ProjectNotReady):
        ensure_project(interactive=True)


def test_ensure_project_interactive_git_init_then_declines_remote(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    answers = iter(["y", "n"])  # 同意 git init，拒绝新建远端
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    with pytest.raises(ProjectNotReady):
        ensure_project(interactive=True)

    assert (tmp_path / ".git").exists()  # git init 确实执行了


def test_ensure_project_interactive_cold_start_writes_remote_origin(tmp_path, monkeypatch):
    """Spec-0033/T2: 冷启动新建远端后，本地 git config 的 remote.origin.url 已写入。

    stub 掉 github.create_repo（无网），驱动 ensure_project(interactive=True) 走完
    git init → 新建远端分支，断言收尾时 _bootstrap 已执行 git remote add origin。
    """
    url = "https://github.com/acme/widget.git"
    monkeypatch.chdir(tmp_path)
    # 同意 git init、同意新建远端、仓库名、设为私有
    answers = iter(["y", "y", "acme/widget", "y"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("openagents.utils.github.create_repo", lambda *, name, private: url)

    ctx = ensure_project(interactive=True)

    assert ctx.remote == url
    written = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert written.stdout.strip() == url
