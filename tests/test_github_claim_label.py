"""Spec-0039/T1：github 认领原语层单元测试。

所有 gh 子进程一律 mock（monkeypatch subprocess.run），不真实调用 gh。覆盖：
- DISPATCH_LABEL 并入 PROCESS_LABELS，被 ensure_prerequisites 幂等自举；
- Issue.labels 由 list_issues / get_issue 正确解析；
- issue_add_label / issue_remove_label（幂等吞「标签本不在」/ 其它错误照抛）；
- issue_stamp_label = remove-then-add（两次 gh 调用、顺序正确、产生新 labeled 事件）；
- issue_label_age_seconds：取最近 labeled 事件秒龄；无该事件返回 None。
"""

import json
import subprocess
from dataclasses import dataclass

import pytest

from openagents import github
from openagents.github import (
    DISPATCH_LABEL,
    PROCESS_LABELS,
    GithubError,
    Issue,
    ensure_prerequisites,
    get_issue,
    issue_add_label,
    issue_label_age_seconds,
    issue_remove_label,
    issue_stamp_label,
    list_issues,
)


@dataclass
class _FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def _fake_run(*, returncode=0, stdout="", stderr=""):
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        return _FakeProc(returncode=returncode, stdout=stdout, stderr=stderr)

    runner.calls = calls
    return runner


# --------------------------------------------------------------------------- #
# DISPATCH_LABEL 并入 PROCESS_LABELS + ensure_prerequisites 自举
# --------------------------------------------------------------------------- #


def test_dispatch_label_in_process_labels():
    assert DISPATCH_LABEL == "openagents-dispatching"
    assert DISPATCH_LABEL in PROCESS_LABELS


def test_ensure_prerequisites_bootstraps_dispatch_label(monkeypatch):
    ensured: list[str] = []
    monkeypatch.setattr(github, "ensure_label", lambda *, name: ensured.append(name))

    ensure_prerequisites()

    # 四个流程标签都被幂等自举，含新增的认领标签。
    assert DISPATCH_LABEL in ensured
    assert set(PROCESS_LABELS) <= set(ensured)


# --------------------------------------------------------------------------- #
# Issue.labels 解析（list_issues / get_issue）
# --------------------------------------------------------------------------- #


def test_get_issue_parses_labels(monkeypatch):
    payload = json.dumps(
        {
            "number": 7,
            "title": "t",
            "body": "b",
            "labels": [{"name": "openagents"}, {"name": DISPATCH_LABEL}],
        }
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    issue = get_issue(number=7)

    assert issue.labels == ("openagents", DISPATCH_LABEL)
    # --json 请求里带上 labels 字段。
    cmd = runner.calls[-1]
    assert "labels" in cmd[cmd.index("--json") + 1]


def test_get_issue_missing_labels_becomes_empty(monkeypatch):
    payload = json.dumps({"number": 7, "title": "t", "body": "b"})
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    assert get_issue(number=7).labels == ()


def test_list_issues_parses_labels(monkeypatch):
    payload = json.dumps(
        [
            {"number": 9, "title": "t", "body": "b", "labels": [{"name": DISPATCH_LABEL}]},
            {"number": 8, "title": "u", "body": "", "labels": []},
        ]
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    issues = list_issues(labels=["openagents"])

    assert issues[0].labels == (DISPATCH_LABEL,)
    assert issues[1].labels == ()
    assert all(isinstance(i, Issue) for i in issues)
    cmd = runner.calls[-1]
    assert "labels" in cmd[cmd.index("--json") + 1]


# --------------------------------------------------------------------------- #
# issue_add_label / issue_remove_label
# --------------------------------------------------------------------------- #


def test_issue_add_label_invokes_gh_issue_edit(monkeypatch):
    runner = _fake_run()
    monkeypatch.setattr(subprocess, "run", runner)

    assert issue_add_label(number=9, name=DISPATCH_LABEL) is None
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "issue", "edit"]
    assert "9" in cmd and "--add-label" in cmd and DISPATCH_LABEL in cmd


def test_issue_remove_label_invokes_gh_issue_edit(monkeypatch):
    runner = _fake_run()
    monkeypatch.setattr(subprocess, "run", runner)

    assert issue_remove_label(number=9, name=DISPATCH_LABEL) is None
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "issue", "edit"]
    assert "--remove-label" in cmd and DISPATCH_LABEL in cmd


def test_issue_remove_label_ignores_absent(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        _fake_run(
            returncode=1, stderr="could not remove label: 'openagents-dispatching' not found"
        ),
    )
    # 标签本不在 → 幂等 no-op，不抛。
    assert issue_remove_label(number=9, name=DISPATCH_LABEL) is None


def test_issue_remove_label_reraises_other_errors(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", _fake_run(returncode=1, stderr="HTTP 401 must authenticate")
    )
    with pytest.raises(GithubError):
        issue_remove_label(number=9, name=DISPATCH_LABEL)


# --------------------------------------------------------------------------- #
# issue_stamp_label = remove-then-add
# --------------------------------------------------------------------------- #


def test_issue_stamp_label_removes_then_adds(monkeypatch):
    runner = _fake_run()
    monkeypatch.setattr(subprocess, "run", runner)

    issue_stamp_label(number=9, name=DISPATCH_LABEL)

    # 恰两次 gh issue edit：先 --remove-label 再 --add-label（每次都产生新 labeled 事件）。
    assert len(runner.calls) == 2
    assert "--remove-label" in runner.calls[0]
    assert "--add-label" in runner.calls[1]


def test_issue_stamp_label_absent_on_remove_still_adds(monkeypatch):
    # remove 阶段标签本不在（首次认领）→ 吞掉，仍继续 add，落一个 labeled 事件。
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(list(args))
        if "--remove-label" in args:
            return _FakeProc(returncode=1, stderr="label 'x' not found")
        return _FakeProc(returncode=0)

    monkeypatch.setattr(subprocess, "run", runner)

    issue_stamp_label(number=9, name=DISPATCH_LABEL)

    assert any("--add-label" in c for c in calls)


# --------------------------------------------------------------------------- #
# issue_label_age_seconds
# --------------------------------------------------------------------------- #


def test_issue_label_age_seconds_returns_positive_for_labeled_event(monkeypatch):
    timeline = json.dumps(
        [
            {
                "event": "labeled",
                "label": {"name": DISPATCH_LABEL},
                "created_at": "2000-01-01T00:00:00Z",
            },
            {"event": "commented", "created_at": "2000-01-02T00:00:00Z"},
        ]
    )
    runner = _fake_run(stdout=timeline)
    monkeypatch.setattr(subprocess, "run", runner)

    age = issue_label_age_seconds(number=9, name=DISPATCH_LABEL)

    # 一个 2000 年的 labeled 事件距今必然是很大的正秒数。
    assert age is not None and age > 0
    cmd = runner.calls[-1]
    assert cmd[:2] == ["gh", "api"]
    assert "timeline" in cmd[2]


def test_issue_label_age_seconds_picks_latest_labeled(monkeypatch):
    timeline = json.dumps(
        [
            {
                "event": "labeled",
                "label": {"name": DISPATCH_LABEL},
                "created_at": "2000-01-01T00:00:00Z",
            },
            {
                "event": "labeled",
                "label": {"name": DISPATCH_LABEL},
                "created_at": "2020-01-01T00:00:00Z",
            },
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=timeline))

    age_latest = issue_label_age_seconds(number=9, name=DISPATCH_LABEL)

    # 取最近一次（2020）→ 秒龄小于「取最早（2000）」的情形；这里只断言取了较近的那次。
    from datetime import UTC, datetime

    since_2000 = (
        datetime.now(UTC) - datetime.fromisoformat("2000-01-01T00:00:00+00:00")
    ).total_seconds()
    assert age_latest is not None and age_latest < since_2000


def test_issue_label_age_seconds_none_when_no_labeled_event(monkeypatch):
    timeline = json.dumps(
        [
            {"event": "commented", "created_at": "2020-01-01T00:00:00Z"},
            {
                "event": "labeled",
                "label": {"name": "other-label"},
                "created_at": "2020-01-01T00:00:00Z",
            },
        ]
    )
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=timeline))

    assert issue_label_age_seconds(number=9, name=DISPATCH_LABEL) is None


def test_issue_label_age_seconds_none_on_empty_timeline(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))
    assert issue_label_age_seconds(number=9, name=DISPATCH_LABEL) is None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
