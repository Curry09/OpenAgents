"""Spec-0042/T2：github.is_open / is_draft 只读薄封装的契约测试。

所有 gh 子进程一律 mock（monkeypatch subprocess.run），不真实调用 gh。
覆盖：is_open 对 OPEN/CLOSED/MERGED 的判定；is_draft 对 draft/转正 PR 的判定；
非预期结构 → GithubError。
"""

import json
import subprocess
from dataclasses import dataclass

import pytest

from openagents.utils.github import GithubError, is_draft, is_open


@dataclass
class _FakeProc:
    """伪 subprocess.CompletedProcess。"""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    """返回一个 subprocess.run 替身。"""

    def runner(args, **kwargs):
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    return runner


# --------------------------------------------------------------------------- #
# is_open（Spec-0042：reopen 识别）
# --------------------------------------------------------------------------- #


def test_is_open_true_when_state_open(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "OPEN"})))
    assert is_open(pr_number=7) is True


def test_is_open_false_when_closed(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "CLOSED"})))
    assert is_open(pr_number=7) is False


def test_is_open_false_when_merged(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "MERGED"})))
    assert is_open(pr_number=7) is False


def test_is_open_gh_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not found"))
    with pytest.raises(GithubError):
        is_open(pr_number=7)


def test_is_open_non_dict_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps(["oops"])))
    with pytest.raises(GithubError):
        is_open(pr_number=7)


# --------------------------------------------------------------------------- #
# is_draft（Spec-0042：区分 draft→rfc-review 与 转正→pr-open）
# --------------------------------------------------------------------------- #


def test_is_draft_true_when_draft(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"isDraft": True})))
    assert is_draft(pr_number=7) is True


def test_is_draft_false_when_ready(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"isDraft": False})))
    assert is_draft(pr_number=7) is False


def test_is_draft_gh_error_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(returncode=1, stderr="not found"))
    with pytest.raises(GithubError):
        is_draft(pr_number=7)


def test_is_draft_missing_field_raises(monkeypatch):
    # isDraft 缺失属结构异常（非布尔）→ GithubError。
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"state": "OPEN"})))
    with pytest.raises(GithubError):
        is_draft(pr_number=7)


def test_is_draft_non_dict_raises(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps(["oops"])))
    with pytest.raises(GithubError):
        is_draft(pr_number=7)
