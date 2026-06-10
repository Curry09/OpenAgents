"""RFC-0015: ensure_prerequisites（统一冷启动兜底）+ 标签单一来源别名的单元测试。

覆盖：
  - ensure_prerequisites 依次调 ensure_branch(test←main) 一次、对 PROCESS_LABELS 逐个
    ensure_label 各一次；
  - 重复调用对已存在分支/标签 no-op（subprocess 层模拟「ref 存在 + 标签 already exists」，
    不抛错）；
  - 标签单一来源：cli/messages/state 的既有公共名均别名引用 github 的常量（is 同一对象）。
所有 gh 子进程一律 mock，不真实调用 gh。
"""

import subprocess
from dataclasses import dataclass

from openagents import cli, github, messages, state
from openagents.github import (
    APPROVAL_LABEL,
    BLOCKED_LABEL,
    DISCOVERY_LABEL,
    PROCESS_LABELS,
    ensure_prerequisites,
)


@dataclass
class _FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


# --------------------------------------------------------------------------- #
# 编排：ensure_branch 一次 + ensure_label × PROCESS_LABELS
# --------------------------------------------------------------------------- #


def test_ensure_prerequisites_orchestrates_branch_and_labels(monkeypatch):
    # 打桩被复用的两个幂等函数，断言 ensure_prerequisites 只做编排、不新造容错。
    branch_calls = []
    label_calls = []
    monkeypatch.setattr(
        github, "ensure_branch", lambda *, name, from_ref: branch_calls.append((name, from_ref))
    )
    monkeypatch.setattr(github, "ensure_label", lambda *, name: label_calls.append(name))

    ensure_prerequisites()

    # ensure_branch 恰一次，且基线为 test←main。
    assert branch_calls == [("test", "main")]
    # 对 PROCESS_LABELS 中每个标签各调一次 ensure_label（顺序一致）。
    assert label_calls == list(PROCESS_LABELS)


# --------------------------------------------------------------------------- #
# 幂等：已存在分支/标签 → 重复调用均 no-op，不抛错
# --------------------------------------------------------------------------- #


def test_ensure_prerequisites_idempotent_when_all_exist(monkeypatch):
    # 在 subprocess 层模拟「分支 ref 已存在（查询成功）」与「标签 already exists（非零退出）」，
    # 连调两次断言不抛错——幂等性由被复用的 ensure_branch/ensure_label 承担。
    def runner(args, **kwargs):
        # gh label create ... → 模拟 already exists（ensure_label 吞掉视为成功）。
        if args[:3] == ["gh", "label", "create"]:
            return _FakeProc(returncode=1, stderr="label already exists")
        # gh api refs/heads/... → ref 已存在，查询成功（ensure_branch no-op）。
        return _FakeProc(returncode=0, stdout='{"ref": "refs/heads/test"}')

    monkeypatch.setattr(subprocess, "run", runner)

    ensure_prerequisites()
    ensure_prerequisites()  # 第二次仍 no-op，不应抛异常


# --------------------------------------------------------------------------- #
# 标签单一来源：三处既有公共名为 github 常量的别名（is 同一对象）
# --------------------------------------------------------------------------- #


def test_label_constants_are_aliases_of_github():
    assert cli.DISCOVERY_LABEL is github.DISCOVERY_LABEL
    assert messages.APPROVAL_LABEL is github.APPROVAL_LABEL
    assert state.BLOCKED_LABEL is github.BLOCKED_LABEL


def test_process_labels_cover_all_three():
    assert PROCESS_LABELS == (DISCOVERY_LABEL, APPROVAL_LABEL, BLOCKED_LABEL)
    assert (DISCOVERY_LABEL, APPROVAL_LABEL, BLOCKED_LABEL) == (
        "openagents",
        "rfc-approved",
        "needs-human",
    )
