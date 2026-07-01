"""Spec-0034/T1：conflictdiag.collect / format_blocker / make_diagnoser 单元测试。

run（git）与 github 全部注入桩，保持 hermetic（不触达真实 git / 真实 gh）。merge-tree 输出取自实测
git 2.39 `git merge-tree --write-tree` 的冲突格式（首行 tree OID + `<mode> <obj> <stage>\t<path>`
stage 行 + 信息段）；关键 hunk 经 `git show <tree>:<path>` 从 blob 读出。

覆盖：collect 的冲突解析 + hunk 提取、stage 去重、干净合并/命令缺失/异常的空诊断降级；
format_blocker 的非空渲染与空诊断退回 CONFLICT_COMMENT；make_diagnoser 的 happy path 与安全降级；
_first_conflict_block 的截断。
"""

import subprocess

from openagents import conflictdiag
from openagents.conflictdiag import ConflictDiag, collect, format_blocker, make_diagnoser

# 实测 git 2.39 merge-tree --write-tree 冲突 stdout：首行 tree OID + 三个 stage 行 + 信息段。
_MERGE_TREE_CONFLICT = (
    "024c0515807b89dc52f29f54d0025ae41eee4aca\n"
    "100644 83db48f84ec878fbfb30b46d16630e944e34f205 1\tf.txt\n"
    "100644 39aa102c5896143ea31aaf3404efe59b6b91f62e 2\tf.txt\n"
    "100644 f80d8ff774d980e0c4b0899c6f0e6a737b06938e 3\tf.txt\n"
    "\n"
    "Auto-merging f.txt\n"
    "CONFLICT (content): Merge conflict in f.txt\n"
)

# 干净合并：merge-tree 仅输出一行 tree OID，无 stage 行。
_MERGE_TREE_CLEAN = "024c0515807b89dc52f29f54d0025ae41eee4aca\n"

# `git show <tree>:f.txt` 的 blob 内容（含冲突标记），关键 hunk 的来源。
_BLOB_WITH_CONFLICT = "line1\n<<<<<<< \nBBB\n=======\nAAA\n>>>>>>> branchA\nline3\n"


def _cp(*, returncode=0, stdout=""):
    return subprocess.CompletedProcess(
        args=["git"], returncode=returncode, stdout=stdout, stderr=""
    )


class _FakeRun:
    """注入桩 run(*, args)：按子命令分发 merge-tree / show，记录调用。"""

    def __init__(self, *, merge_tree, blob, raise_on=None):
        self._merge_tree = merge_tree
        self._blob = blob
        self._raise_on = raise_on or set()
        self.calls = []

    def __call__(self, *, args):
        self.calls.append(args)
        if args[0] in self._raise_on:
            raise FileNotFoundError("git not found")
        if args[0] == "merge-tree":
            return _cp(returncode=1, stdout=self._merge_tree)
        if args[0] == "show":
            return _cp(returncode=0, stdout=self._blob)
        return _cp(returncode=0)


# --------------------------------------------------------------------------- #
# collect
# --------------------------------------------------------------------------- #


def test_collect_parses_files_and_hunks():
    run = _FakeRun(merge_tree=_MERGE_TREE_CONFLICT, blob=_BLOB_WITH_CONFLICT)

    diag = collect(base="main", head="feature", run=run)

    assert diag.files == ["f.txt"]  # 三个 stage 去重成一个文件
    assert "<<<<<<<" in diag.hunks["f.txt"]
    assert ">>>>>>> branchA" in diag.hunks["f.txt"]
    # merge-tree 被以 origin/<base>/origin/<head> 调用，hunk 经 git show <tree>:<path> 取。
    assert run.calls[0] == ["merge-tree", "--write-tree", "origin/main", "origin/feature"]
    assert ["show", "024c0515807b89dc52f29f54d0025ae41eee4aca:f.txt"] in run.calls


def test_collect_clean_merge_returns_empty():
    run = _FakeRun(merge_tree=_MERGE_TREE_CLEAN, blob="")

    diag = collect(base="main", head="feature", run=run)

    assert diag.is_empty()
    assert diag.files == []


def test_collect_swallows_command_missing():
    run = _FakeRun(merge_tree="", blob="", raise_on={"merge-tree"})

    diag = collect(base="main", head="feature", run=run)

    assert diag.is_empty()


def test_collect_dedups_repeated_paths():
    merge_tree = (
        "024c0515807b89dc52f29f54d0025ae41eee4aca\n"
        "100644 83db48f84ec878fbfb30b46d16630e944e34f205 1\tdocs/specs/OVERVIEW.md\n"
        "100644 39aa102c5896143ea31aaf3404efe59b6b91f62e 2\tdocs/specs/OVERVIEW.md\n"
        "100644 f80d8ff774d980e0c4b0899c6f0e6a737b06938e 3\tdocs/specs/OVERVIEW.md\n"
        "100644 1234567890abcdef1234567890abcdef12345678 1\topenagents/messages.py\n"
        "100644 abcdef1234567890abcdef1234567890abcdef12 2\topenagents/messages.py\n"
    )
    run = _FakeRun(merge_tree=merge_tree, blob=_BLOB_WITH_CONFLICT)

    diag = collect(base="main", head="feature", run=run)

    assert diag.files == ["docs/specs/OVERVIEW.md", "openagents/messages.py"]


def test_collect_file_without_hunk_still_listed():
    # show 取不到冲突块（blob 无标记）→ 文件仍进清单、hunks 缺省该键。
    run = _FakeRun(merge_tree=_MERGE_TREE_CONFLICT, blob="no markers here\n")

    diag = collect(base="main", head="feature", run=run)

    assert diag.files == ["f.txt"]
    assert "f.txt" not in diag.hunks


# --------------------------------------------------------------------------- #
# format_blocker
# --------------------------------------------------------------------------- #


def test_format_blocker_empty_falls_back_to_conflict_comment():
    assert format_blocker(diag=ConflictDiag(), step="x") == conflictdiag.CONFLICT_COMMENT


def test_format_blocker_renders_files_and_hunk():
    diag = ConflictDiag(
        files=["docs/specs/OVERVIEW.md", "openagents/messages.py"],
        hunks={"docs/specs/OVERVIEW.md": "<<<<<<< (ours)\nA\n=======\nB\n>>>>>>> theirs"},
    )

    body = format_blocker(diag=diag, step="自动合并目标分支 origin/main 时")

    assert "自动合并目标分支 origin/main 时" in body
    assert "冲突文件清单（2）" in body
    assert "- docs/specs/OVERVIEW.md" in body
    assert "- openagents/messages.py" in body
    assert "关键 hunk 摘要 · docs/specs/OVERVIEW.md" in body
    assert "<<<<<<< (ours)" in body
    # 无 hunk 的文件不渲 hunk 段。
    assert "关键 hunk 摘要 · openagents/messages.py" not in body


# --------------------------------------------------------------------------- #
# make_diagnoser
# --------------------------------------------------------------------------- #


def test_make_diagnoser_happy_path(monkeypatch):
    monkeypatch.setattr(conflictdiag.github, "pr_head_branch", lambda *, pr_number: "feature")

    def _fake_subprocess_run(argv, *, cwd, capture_output, text):
        if argv[:2] == ["git", "merge-tree"]:
            return _cp(returncode=1, stdout=_MERGE_TREE_CONFLICT)
        if argv[:2] == ["git", "show"]:
            return _cp(returncode=0, stdout=_BLOB_WITH_CONFLICT)
        return _cp(returncode=0)

    monkeypatch.setattr(conflictdiag.subprocess, "run", _fake_subprocess_run)

    diagnose = make_diagnoser(work_dir="/repo", base="main")
    body = diagnose(pr_number=11)

    assert "冲突文件清单（1）" in body
    assert "f.txt" in body
    assert "<<<<<<<" in body


def test_make_diagnoser_falls_back_when_branch_unavailable(monkeypatch):
    def _raise(*, pr_number):
        raise conflictdiag.github.GithubError("no headRefName")

    monkeypatch.setattr(conflictdiag.github, "pr_head_branch", _raise)

    diagnose = make_diagnoser(work_dir="/repo", base="main")

    assert diagnose(pr_number=11) == conflictdiag.CONFLICT_COMMENT


# --------------------------------------------------------------------------- #
# _first_conflict_block 截断
# --------------------------------------------------------------------------- #


def test_first_conflict_block_truncates():
    big = "<<<<<<<\n" + ("x" * 5000) + "\n=======\ny\n>>>>>>> b\n"
    out = conflictdiag._first_conflict_block(text=big)

    assert out.endswith(conflictdiag._TRUNCATED_HINT)
    assert len(out) <= conflictdiag._MAX_HUNK_CHARS + len(conflictdiag._TRUNCATED_HINT)
