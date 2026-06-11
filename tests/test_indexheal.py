"""issue #48: 索引冲突自愈（indexheal）单元测试。

git 与 render 全部注入桩，保持 hermetic（不触达真实 git / spec render）。
覆盖 heal_branch 的三条路径（干净合并 / 仅 OVERVIEW 冲突重渲 / 含其它冲突 abort）+
make_healer 的安全降级（取 head 分支失败 → False）。
"""

import subprocess

import pytest

from openagents import indexheal
from openagents.indexheal import GENERATED_INDEX, heal_branch


def _cp(*, returncode=0, stdout=""):
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=""
    )


class _FakeGit:
    """按命令分发的伪 git：记录调用、按预设回应 merge / diff，其余返回成功。"""

    def __init__(self, *, merge_rc, conflicts):
        self._merge_rc = merge_rc
        self._conflicts = conflicts
        self.calls = []

    def __call__(self, *, args, cwd, check):
        self.calls.append(args)
        if args[0] == "merge" and args[1] != "--abort":
            return _cp(returncode=self._merge_rc)
        if args[:3] == ["diff", "--name-only", "--diff-filter=U"]:
            return _cp(stdout="\n".join(self._conflicts))
        return _cp(returncode=0)


def test_clean_merge_returns_true_without_render(tmp_path):
    git = _FakeGit(merge_rc=0, conflicts=[])
    rendered = []
    ok = heal_branch(worktree=tmp_path, base="test", render=lambda wt: rendered.append(wt), run=git)
    assert ok is True
    assert rendered == []
    assert ["merge", "origin/test", "--no-edit"] in git.calls
    # 干净合并不应触碰 OVERVIEW（不 add/commit/abort）。
    assert not any(c[0] in {"add", "commit"} or c[:2] == ["merge", "--abort"] for c in git.calls)


def test_only_overview_conflict_rerenders_and_resolves(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=[str(GENERATED_INDEX)])
    rendered = []
    ok = heal_branch(worktree=tmp_path, base="test", render=lambda wt: rendered.append(wt), run=git)
    assert ok is True
    assert rendered == [tmp_path]  # 重渲被调用
    assert ["add", str(GENERATED_INDEX)] in git.calls
    assert ["commit", "--no-edit"] in git.calls
    assert ["merge", "--abort"] not in git.calls


def test_other_conflict_aborts_and_returns_false(tmp_path):
    git = _FakeGit(merge_rc=1, conflicts=[str(GENERATED_INDEX), "openagents/messages.py"])
    rendered = []
    ok = heal_branch(worktree=tmp_path, base="test", render=lambda wt: rendered.append(wt), run=git)
    assert ok is False
    assert rendered == []  # 含真实冲突不重渲
    assert ["merge", "--abort"] in git.calls


def test_make_healer_degrades_on_github_error(monkeypatch, tmp_path):
    # 取 PR head 分支失败 → heal 安全降级为 False（回落到人工留言路径），绝不抛错。
    def _boom(*, pr_number):
        raise indexheal.github.GithubError("gh 失败")

    monkeypatch.setattr(indexheal.github, "pr_head_branch", _boom)
    heal = indexheal.make_healer(work_dir=tmp_path, base="test")
    assert heal(pr_number=7) is False


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
