"""Spec-0023/T3: release 模块（预检 + 物化版本分支/tag + 版本递增）的单元测试。

打桩 github.* / state / subprocess（git tag/push），保持 hermetic（不触达真实 gh/git）。
覆盖：有 BLOCKED run → False；有 needs-human PR → False；main CI 非绿 → False；
全过 → 建 release/vX.Y.Z 分支 + 打 tag + 推送且 released=True（版本号语义化递增）；
无 tag → v0.1.0；bump=minor/major 生效；语义化排序（v0.10.0 > v0.9.0）；push 失败抛错。
"""

import subprocess

import pytest

from openagents import release as release_module
from openagents.github import PR
from openagents.release import ReleaseResult, _next_version, release
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
        release_module.github,
        "list_open_prs",
        lambda: [PR(number=n, url=f"u/pull/{n}") for n in open_prs],
    )
    monkeypatch.setattr(
        release_module.github,
        "has_label",
        lambda *, pr_number, name: pr_number in labeled,
    )
    monkeypatch.setattr(release_module.github, "branch_ci_green", lambda *, branch: ci_green)
    bootstrapped = []
    monkeypatch.setattr(
        release_module.github,
        "ensure_prerequisites",
        lambda: bootstrapped.append(True),
    )
    return bootstrapped


def _patch_git(monkeypatch, *, tags=(), push_returncode=0, stderr=""):
    """打桩 subprocess.run：`git tag --list v*` 返回 tags，其余（push/tag）记录并按结果返回。

    返回 calls 列表，供断言依次发生了哪些 git 调用。
    """
    calls = []

    def runner(args, **kwargs):
        calls.append(list(args))

        class _Proc:
            pass

        # 读取已发布 tag：返回换行分隔的 tags（始终成功）。
        if args[:3] == ["git", "tag", "--list"]:
            _Proc.returncode = 0
            _Proc.stdout = "\n".join(tags)
            _Proc.stderr = ""
            return _Proc()
        # 物化动作（push 分支 / 打 tag / push tag）：按预设结果返回。
        _Proc.returncode = push_returncode
        _Proc.stdout = ""
        _Proc.stderr = stderr
        return _Proc()

    monkeypatch.setattr(subprocess, "run", runner)
    return calls


# --------------------------------------------------------------------------- #
# _next_version：版本递增纯函数
# --------------------------------------------------------------------------- #


def test_next_version_no_tag_starts_at_initial():
    # 无任何版本 tag → 首发 v0.1.0（忽略 bump）。
    assert _next_version(latest=None, bump="patch") == "v0.1.0"
    assert _next_version(latest=None, bump="major") == "v0.1.0"


def test_next_version_patch_minor_major():
    assert _next_version(latest=(1, 2, 3), bump="patch") == "v1.2.4"
    assert _next_version(latest=(1, 2, 3), bump="minor") == "v1.3.0"
    assert _next_version(latest=(1, 2, 3), bump="major") == "v2.0.0"


def test_next_version_rejects_unknown_bump():
    with pytest.raises(ValueError):
        _next_version(latest=(1, 0, 0), bump="huge")


# --------------------------------------------------------------------------- #
# 预检拦截
# --------------------------------------------------------------------------- #


def test_blocked_run_blocks_release(tmp_path, monkeypatch):
    state = _state(tmp_path, runs=[(3, STATUS_BLOCKED)])
    _patch_github(monkeypatch)
    git_calls = _patch_git(monkeypatch, tags=["v1.0.0"])

    result = release(state=state)

    assert isinstance(result, ReleaseResult)
    assert result.released is False
    assert result.version == ""
    assert "#3" in result.reason
    assert git_calls == []  # 预检未过 → 完全不碰 git


def test_needs_human_pr_blocks_release(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch, open_prs=[8], labeled=[8])
    git_calls = _patch_git(monkeypatch)

    result = release(state=state)

    assert result.released is False
    assert "#8" in result.reason
    assert git_calls == []


def test_main_ci_not_green_blocks_release(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch, ci_green=False)
    git_calls = _patch_git(monkeypatch)

    result = release(state=state)

    assert result.released is False
    assert "CI" in result.reason
    assert "main" in result.reason
    assert git_calls == []


# --------------------------------------------------------------------------- #
# 预检全过 → 物化版本
# --------------------------------------------------------------------------- #


def test_all_checks_pass_materializes_branch_and_tag(tmp_path, monkeypatch):
    state = _state(tmp_path, runs=[(3, STATUS_PR_OPEN)])
    bootstrapped = _patch_github(monkeypatch, open_prs=[8], labeled=[])
    git_calls = _patch_git(monkeypatch, tags=["v1.2.3"])

    result = release(state=state)  # 默认 bump=patch

    assert result.released is True
    assert result.version == "v1.2.4"
    assert result.reason == "ok"
    assert bootstrapped == [True]  # 物化前先兜底流程标签
    # 依次：读 tag → push 发布分支 → 打 tag → push tag。
    assert git_calls == [
        ["git", "tag", "--list", "v*"],
        ["git", "push", "origin", "main:refs/heads/release/v1.2.4"],
        ["git", "tag", "v1.2.4", "main"],
        ["git", "push", "origin", "v1.2.4"],
    ]


def test_first_release_without_tags_is_v0_1_0(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    git_calls = _patch_git(monkeypatch, tags=[])  # 仓库无任何 tag

    result = release(state=state)

    assert result.version == "v0.1.0"
    assert ["git", "push", "origin", "main:refs/heads/release/v0.1.0"] in git_calls


def test_bump_minor_and_semantic_ordering(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    # 语义化排序：最新应取 v0.10.0（而非字典序的 v0.9.0）。
    _patch_git(monkeypatch, tags=["v0.9.0", "v0.10.0"])

    result = release(state=state, bump="minor")

    assert result.version == "v0.11.0"


def test_bump_major(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    _patch_git(monkeypatch, tags=["v1.4.2"])

    result = release(state=state, bump="major")

    assert result.version == "v2.0.0"


def test_push_failure_raises(tmp_path, monkeypatch):
    state = _state(tmp_path)
    _patch_github(monkeypatch)
    _patch_git(monkeypatch, tags=["v1.0.0"], push_returncode=1, stderr="protected branch")

    with pytest.raises(RuntimeError):
        release(state=state)
