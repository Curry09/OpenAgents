"""Spec-0039/T1 + Spec-0049/T1：github 认领原语层单元测试。

所有 gh 子进程一律 mock（monkeypatch subprocess.run），不真实调用 gh。覆盖：
- DISPATCH_LABEL 并入 PROCESS_LABELS，被 ensure_prerequisites 幂等自举；
- Issue.labels 由 list_issues / get_issue 正确解析；
- issue_add_label / issue_remove_label（幂等吞「标签本不在」/ 其它错误照抛）；
- Spec-0049/T1：认领打标改为**幂等 add**——不再有 remove-then-add stamp；对已带标签的 issue
  再 add 只发一次 `gh issue edit --add-label`、不删（无 unlabeled 事件）。
- Spec-0049/T1：list_issue_comments 取回 issue 全部评论（含 author/body/createdAt）。
"""

import json
import subprocess
from dataclasses import dataclass

import pytest

from openagents.utils import github
from openagents.utils.github import (
    DISPATCH_LABEL,
    PROCESS_LABELS,
    Comment,
    GithubError,
    Issue,
    ensure_prerequisites,
    get_issue,
    issue_add_label,
    issue_remove_label,
    list_issue_comments,
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
# issue_add_label（Spec-0049：认领打标的幂等 add 原语）/ issue_remove_label
# --------------------------------------------------------------------------- #


def test_issue_add_label_invokes_gh_issue_edit(monkeypatch):
    runner = _fake_run()
    monkeypatch.setattr(subprocess, "run", runner)

    assert issue_add_label(number=9, name=DISPATCH_LABEL) is None
    cmd = runner.calls[-1]
    assert cmd[:3] == ["gh", "issue", "edit"]
    assert "9" in cmd and "--add-label" in cmd and DISPATCH_LABEL in cmd


def test_issue_add_label_is_single_idempotent_add_no_remove(monkeypatch):
    # Spec-0049/T1 核心：认领打标只发一次 `--add-label`，**绝不** remove（无 unlabeled 事件、
    # 不撕别人标签）——即便对「已带该标签」的 issue 再认领也一样（gh 侧 add 幂等 no-op）。
    runner = _fake_run()
    monkeypatch.setattr(subprocess, "run", runner)

    issue_add_label(number=9, name=DISPATCH_LABEL)

    assert len(runner.calls) == 1
    assert "--add-label" in runner.calls[0]
    assert not any("--remove-label" in c for c in runner.calls)


def test_no_stamp_label_primitive_remains(monkeypatch):
    # Spec-0049/T1：退役的 remove-then-add stamp 原语不复存在（互撕的物理来源被移除）。
    assert not hasattr(github, "issue_stamp_label")
    assert not hasattr(github, "issue_label_age_seconds")


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
# list_issue_comments（Spec-0049/T1：issue 级读评论原语）
# --------------------------------------------------------------------------- #


def test_list_issue_comments_parses_all_fields(monkeypatch):
    payload = json.dumps(
        {
            "comments": [
                {
                    "id": "IC_1",
                    "author": {"login": "pcj-sudo"},
                    "body": "🤖 认领 <!-- openagents:claim --> <!-- openagents:agent=a1 -->",
                    "createdAt": "2026-07-03T06:25:44Z",
                },
                {
                    "id": "IC_2",
                    "author": {"login": "drifting"},
                    "body": "另一条评论",
                    "createdAt": "2026-07-03T06:25:49Z",
                },
            ]
        }
    )
    runner = _fake_run(stdout=payload)
    monkeypatch.setattr(subprocess, "run", runner)

    comments = list_issue_comments(number=116)

    assert [c.id for c in comments] == ["IC_1", "IC_2"]
    assert comments[0].author == "pcj-sudo"
    assert "openagents:claim" in comments[0].body
    assert comments[0].created_at == "2026-07-03T06:25:44Z"
    assert all(isinstance(c, Comment) for c in comments)
    # 走 `gh issue view <n> --json comments`。
    cmd = runner.calls[-1]
    assert cmd[:4] == ["gh", "issue", "view", "116"]
    assert "comments" in cmd


def test_list_issue_comments_empty_when_none(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=json.dumps({"comments": []})))
    assert list_issue_comments(number=116) == []


def test_list_issue_comments_tolerates_missing_author(monkeypatch):
    payload = json.dumps({"comments": [{"id": "IC_1", "body": "x", "createdAt": "t"}]})
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout=payload))

    comments = list_issue_comments(number=116)
    assert comments[0].author == ""


def test_list_issue_comments_raises_on_non_dict(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(stdout="[]"))
    with pytest.raises(GithubError):
        list_issue_comments(number=116)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
