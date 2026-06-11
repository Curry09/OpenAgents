"""RFC-0012 T4: promote 模块（预检 + 快进 main）的单元测试。

打桩 github.* / state / subprocess（git push），保持 hermetic（不触达真实 gh/git）。
覆盖：有 BLOCKED run → False；有 needs-human PR → False；CI 非绿 → False；
全过 → 执行 push 且 promoted=True，并先 ensure_prerequisites 统一兜底（RFC-0015）。
"""

import subprocess

import pytest

from openagents import promote as promote_module
from openagents.github import PR
from openagents.promote import PromoteResult, promote
from openagents.state import STATUS_BLOCKED, STATUS_PR_OPEN, State


def _state(tmp_path, *, runs=()):
    state = State(path=tmp_path / ".openagents" / "state.json")
    for issue_number, status in runs:
        state.record_run(
            issue_number=issue_number,
            branch=f"openagents/issue-{issue_number}",
            pr=PR(number=issue_number * 10, url=f"u/pull/{issue_number * 10}"),
            status=status,
        )
    return state


def _patch_github(monkeypatch, *, open_prs=(), labeled=(), ci_green=True):
    """打桩 github：open PR 列表、带 needs-human 的 PR 集合、分支 CI 绿否。"""
    monkeypatch.setattr(
        promote_module.github,
        "list_open_prs",
        lambda: [PR(number=n, url=f"u/pull/{n}") for n in open_prs],
    )
    monkeypatch.setattr(
        promote_module.github,
        "has_label",
        lambda *, pr_number, name: pr_number in labeled,
    )
    monkeypatch.setattr(promote_module.github, "branch_ci_green", lambda *, branch: ci_green)
    # RFC-0015：promote 改为调统一兜底 ensure_prerequisites（取代裸 ensure_branch）；
    # 打桩记录调用次数，避免触达真实 gh。
    bootstrapped = []
    monkeypatch.setattr(
        promote_module.github,
        "ensure_prerequisites",
        lambda: bootstrapped.append(True),
    )
    return bootstrapped


def _patch_push(monkeypatch, *, returncode=0, stderr=""):
    calls = []

    def runner(args, **kwargs):
        calls.append(list(args))

        class _Proc:
            pass

        _Proc.returncode = returncode
        _Proc.stdout = ""
        _Proc.stderr = stderr
        return _Proc()

    monkeypatch.setattr(subprocess, "run", runner)
    return calls


# --------------------------------------------------------------------------- #
# 预检拦截
# --------------------------------------------------------------------------- #


def test_blocked_run_blocks_promote(tmp_path, monkeypatch):
    state = _state(tmp_path, runs=[(3, STATUS_BLOCKED)])
    _patch_github(monkeypatch)
    push_calls = _patch_push(monkeypatch)

    result = promote(state=state)

    assert isinstance(result, PromoteResult)
    assert result.promoted is False
    assert "#3" in result.reason
    assert push_calls == []  # 预检未过 → 不 push


def test_needs_human_pr_blocks_promote(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch, open_prs=[8], labeled=[8])
    push_calls = _patch_push(monkeypatch)

    result = promote(state=state)

    assert result.promoted is False
    assert "#8" in result.reason
    assert push_calls == []


def test_ci_not_green_blocks_promote(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch, ci_green=False)
    push_calls = _patch_push(monkeypatch)

    result = promote(state=state)

    assert result.promoted is False
    assert "CI" in result.reason
    assert push_calls == []


# --------------------------------------------------------------------------- #
# 预检全过 → 快进
# --------------------------------------------------------------------------- #


def test_all_checks_pass_pushes_and_promotes(tmp_path, monkeypatch):
    state = _state(tmp_path, runs=[(3, STATUS_PR_OPEN)])
    bootstrapped = _patch_github(monkeypatch, open_prs=[8], labeled=[])
    push_calls = _patch_push(monkeypatch)

    result = promote(state=state)

    assert result.promoted is True
    assert result.reason == "ok"
    # RFC-0015：先 ensure_prerequisites 统一兜底（test 分支 + 流程标签），再 push test:main。
    assert bootstrapped == [True]
    assert push_calls == [["git", "push", "origin", "test:main"]]


def test_custom_source_target(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    push_calls = _patch_push(monkeypatch)

    result = promote(state=state, source="staging", target="prod")

    assert result.promoted is True
    assert push_calls == [["git", "push", "origin", "staging:prod"]]


def test_push_failure_raises(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    _patch_push(monkeypatch, returncode=1, stderr="non-fast-forward")

    with pytest.raises(RuntimeError):
        promote(state=state)
