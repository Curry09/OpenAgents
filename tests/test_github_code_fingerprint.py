"""Spec-0053/T2：github.code_fingerprint（PR 净 diff 指纹）的契约测试。

所有 gh 子进程一律 mock（monkeypatch subprocess.run），不真实调用 gh。覆盖：
- 同一 diff 输入哈希稳定且等长（sha256 hexdigest = 64 位十六进制）；
- gh 失败（非零退出抛 GithubError）→ 返回 ""（fail-open）；
- gh 空输出 → 返回 ""；
- 两次相同 diff 指纹相等、diff 变化后指纹不等。
"""

import hashlib
import subprocess
from dataclasses import dataclass

from openagents.utils.github import code_fingerprint


@dataclass
class _FakeProc:
    """伪 subprocess.CompletedProcess。"""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    """返回一个 subprocess.run 替身，并记录每次调用的参数。"""
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    runner.calls = calls
    return runner


_DIFF = "diff --git a/openagents/foo.py b/openagents/foo.py\n@@ -1,1 +1,2 @@\n x = 1\n+y = 2\n"


def test_code_fingerprint_matches_sha256_of_diff(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_DIFF))
    fp = code_fingerprint(pr_number=5)
    # 与直接 sha256(diff) 逐位一致；hexdigest 定长 64。
    assert fp == hashlib.sha256(_DIFF.encode("utf-8")).hexdigest()
    assert len(fp) == 64


def test_code_fingerprint_invokes_gh_pr_diff(monkeypatch):
    runner = _fake_run(stdout=_DIFF)
    monkeypatch.setattr(subprocess, "run", runner)
    code_fingerprint(pr_number=42)
    assert runner.calls[-1] == ["gh", "pr", "diff", "42"]


def test_code_fingerprint_stable_across_calls(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_DIFF))
    first = code_fingerprint(pr_number=5)
    second = code_fingerprint(pr_number=5)
    assert first == second


def test_code_fingerprint_changes_when_diff_changes(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_DIFF))
    before = code_fingerprint(pr_number=5)
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=_DIFF + "+z = 3\n"))
    after = code_fingerprint(pr_number=5)
    assert before != after


def test_code_fingerprint_empty_output_returns_empty(monkeypatch):
    # gh 返回空 stdout（无 diff）→ ""（fail-open，调用方落回照常评审）。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=""))
    assert code_fingerprint(pr_number=5) == ""


def test_code_fingerprint_gh_failure_returns_empty(monkeypatch):
    # gh 非零退出（业务错误，非瞬时）→ _run_gh 抛 GithubError → 吞成 ""（fail-open）。
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="pr not found"))
    assert code_fingerprint(pr_number=5) == ""
