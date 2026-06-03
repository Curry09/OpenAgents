"""RFC-0001 T2 + RFC-0003: ClaudeCodeBackend 适配器的单元测试。

所有子进程副作用一律 mock，不真实调用外部进程：
- claude CLI 走 subprocess.Popen（RFC-0003 实时透传）；
- git status 走 subprocess.run。
"""

import subprocess
from pathlib import Path

import pytest

from openagents.backends.base import AgentBackend, AgentResult
from openagents.backends.claude_code import CLAUDE_BIN, ClaudeCodeBackend


class _FakePopen:
    """模拟 subprocess.Popen：stdout 为可迭代行序列，wait() 返回退出码。"""

    def __init__(self, *, lines, returncode):
        self.stdout = iter(lines)
        self._returncode = returncode

    def wait(self):
        return self._returncode


class _FakeCompleted:
    """模拟 subprocess.run 的返回对象（用于 git status）。"""

    def __init__(self, *, returncode, stdout):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def _patch(monkeypatch, *, claude_lines, claude_returncode, git_porcelain):
    """打桩 Popen(claude) 与 run(git)，记录调用以便断言。"""
    popen_calls = []
    run_calls = []

    def fake_popen(cmd, **kwargs):
        popen_calls.append((cmd, kwargs))
        return _FakePopen(lines=claude_lines, returncode=claude_returncode)

    def fake_run(cmd, **kwargs):
        run_calls.append((cmd, kwargs))
        return _FakeCompleted(returncode=0, stdout=git_porcelain)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subprocess, "run", fake_run)
    return popen_calls, run_calls


def test_backend_satisfies_protocol():
    assert isinstance(ClaudeCodeBackend(), AgentBackend)


def test_name_is_claude_code():
    assert ClaudeCodeBackend().name == "claude-code"


def test_changed_true_when_git_reports_diff(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=["done editing\n"],
        claude_returncode=0,
        git_porcelain=" M foo.py\n",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="改 foo", context="issue 正文")

    assert isinstance(result, AgentResult)
    assert result.changed is True
    assert "done editing" in result.summary


def test_changed_false_when_git_clean(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=["nothing to do\n"],
        claude_returncode=0,
        git_porcelain="",
    )

    result = ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert result.changed is False


def test_streams_claude_output_to_stdout(monkeypatch, tmp_path, capsys):
    # RFC-0003 决策 6：claude 输出实时透传到终端（不再整段吞掉）。
    _patch(
        monkeypatch,
        claude_lines=["第一行\n", "第二行\n"],
        claude_returncode=0,
        git_porcelain=" M a.py\n",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    out = capsys.readouterr().out
    assert "第一行" in out
    assert "第二行" in out


def test_invokes_claude_print_mode_in_work_dir(monkeypatch, tmp_path):
    popen_calls, _ = _patch(
        monkeypatch,
        claude_lines=["ok\n"],
        claude_returncode=0,
        git_porcelain="",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="修复 bug", context="历史 comment")

    assert len(popen_calls) == 1
    cmd, kwargs = popen_calls[0]
    # headless/print 模式：claude -p "<prompt>" --permission-mode acceptEdits
    assert cmd[:2] == [CLAUDE_BIN, "-p"]
    prompt = cmd[2]
    assert "修复 bug" in prompt
    assert "历史 comment" in prompt
    assert "--permission-mode" in cmd and "acceptEdits" in cmd
    assert kwargs["cwd"] == tmp_path


def test_git_status_runs_against_work_dir(monkeypatch, tmp_path):
    _, run_calls = _patch(
        monkeypatch,
        claude_lines=["ok\n"],
        claude_returncode=0,
        git_porcelain="",
    )

    ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    git_calls = [c for c in run_calls if c[0][0] == "git"]
    assert len(git_calls) == 1
    cmd, _ = git_calls[0]
    assert cmd == ["git", "-C", str(tmp_path), "status", "--porcelain"]


def test_raises_when_claude_fails(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=["boom\n"],
        claude_returncode=2,
        git_porcelain="",
    )

    with pytest.raises(RuntimeError) as exc:
        ClaudeCodeBackend().run(work_dir=tmp_path, task="t", context="c")

    assert "boom" in str(exc.value)


def test_accepts_path_work_dir(monkeypatch, tmp_path):
    _patch(
        monkeypatch,
        claude_lines=["ok\n"],
        claude_returncode=0,
        git_porcelain=" M a\n",
    )

    result = ClaudeCodeBackend().run(work_dir=Path(tmp_path), task="t", context="c")
    assert result.changed is True
