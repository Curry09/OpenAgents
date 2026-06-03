"""RFC-0001 T2: ClaudeCodeBackend 适配器的单元测试。

所有子进程副作用（claude CLI、git）一律 mock，不真实调用外部进程。
"""

import subprocess
from pathlib import Path

import pytest

from openagents.backends.base import AgentBackend, AgentResult
from openagents.backends.claude_code import CLAUDE_BIN, ClaudeCodeBackend


class _FakeCompleted:
    """模拟 subprocess.run 的返回对象。"""

    def __init__(self, *, returncode, stdout, stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_runner(*, claude_result, git_porcelain):
    """构造一个 subprocess.run 替身，按调用的命令首元素分派。"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        if cmd[0] == CLAUDE_BIN:
            return claude_result
        if cmd[0] == "git":
            return _FakeCompleted(returncode=0, stdout=git_porcelain)
        raise AssertionError(f"未预期的命令: {cmd!r}")

    fake_run.calls = calls
    return fake_run


def test_backend_satisfies_protocol():
    assert isinstance(ClaudeCodeBackend(), AgentBackend)


def test_name_is_claude_code():
    assert ClaudeCodeBackend().name == "claude-code"


def test_changed_true_when_git_reports_diff(monkeypatch, tmp_path):
    runner = _make_runner(
        claude_result=_FakeCompleted(returncode=0, stdout="done editing"),
        git_porcelain=" M foo.py\n",
    )
    monkeypatch.setattr(subprocess, "run", runner)

    backend = ClaudeCodeBackend()
    result = backend.run(work_dir=tmp_path, task="改 foo", context="issue 正文")

    assert isinstance(result, AgentResult)
    assert result.changed is True
    assert "done editing" in result.summary


def test_changed_false_when_git_clean(monkeypatch, tmp_path):
    runner = _make_runner(
        claude_result=_FakeCompleted(returncode=0, stdout="nothing to do"),
        git_porcelain="",
    )
    monkeypatch.setattr(subprocess, "run", runner)

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert result.changed is False


def test_invokes_claude_print_mode_in_work_dir(monkeypatch, tmp_path):
    runner = _make_runner(
        claude_result=_FakeCompleted(returncode=0, stdout="ok"),
        git_porcelain="",
    )
    monkeypatch.setattr(subprocess, "run", runner)

    ClaudeCodeBackend().run(work_dir=tmp_path, task="修复 bug", context="历史 comment")

    claude_calls = [c for c in runner.calls if c[0][0] == CLAUDE_BIN]
    assert len(claude_calls) == 1
    cmd, kwargs = claude_calls[0]
    # headless/print 模式：claude -p "<prompt>" --permission-mode acceptEdits
    assert cmd[:2] == [CLAUDE_BIN, "-p"]
    prompt = cmd[2]
    assert "修复 bug" in prompt
    assert "历史 comment" in prompt
    assert "--permission-mode" in cmd and "acceptEdits" in cmd
    assert kwargs["cwd"] == tmp_path


def test_git_status_runs_against_work_dir(monkeypatch, tmp_path):
    runner = _make_runner(
        claude_result=_FakeCompleted(returncode=0, stdout="ok"),
        git_porcelain="",
    )
    monkeypatch.setattr(subprocess, "run", runner)

    ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    git_calls = [c for c in runner.calls if c[0][0] == "git"]
    assert len(git_calls) == 1
    cmd, _ = git_calls[0]
    assert cmd == ["git", "-C", str(tmp_path), "status", "--porcelain"]


def test_raises_when_claude_fails(monkeypatch, tmp_path):
    runner = _make_runner(
        claude_result=_FakeCompleted(returncode=2, stdout="", stderr="boom"),
        git_porcelain="",
    )
    monkeypatch.setattr(subprocess, "run", runner)

    with pytest.raises(RuntimeError) as exc:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "boom" in str(exc.value)


def test_accepts_path_work_dir(monkeypatch, tmp_path):
    runner = _make_runner(
        claude_result=_FakeCompleted(returncode=0, stdout="ok"),
        git_porcelain=" M a\n",
    )
    monkeypatch.setattr(subprocess, "run", runner)

    result = ClaudeCodeBackend().run(work_dir=Path(tmp_path), task="t", context="c")
    assert result.changed is True
