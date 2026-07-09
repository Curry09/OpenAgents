"""RFC-0015 / Spec-0023/T1: ensure_prerequisites（统一冷启动兜底）+ 标签单一来源别名的单元测试。

覆盖：
  - ensure_prerequisites 对 PROCESS_LABELS 逐个 ensure_label 各一次（Spec-0023/T1：test 分支
    门控退役后不再建 test 分支，收敛为只预建流程标签）；
  - 重复调用对已存在标签 no-op（subprocess 层模拟「标签 already exists」，不抛错）；
  - 标签单一来源：cli 的既有公共名别名引用 github 的常量（is 同一对象）。
    Spec-0062/T6：messages 旧栈已删，其 APPROVAL_LABEL 别名断言随之退役。
    Spec-0063/T5：state 归一删 state.py，其 BLOCKED_LABEL 别名断言随之退役
    （BLOCKED_LABEL 权威源本就是 github，release/board 已直连）。
所有 gh 子进程一律 mock，不真实调用 gh。
"""

import subprocess
from dataclasses import dataclass

from openagents import cli
from openagents.utils import github
from openagents.utils.github import (
    APPROVAL_LABEL,
    BLOCKED_LABEL,
    DISCOVERY_LABEL,
    DISPATCH_LABEL,
    PROCESS_LABELS,
    ensure_prerequisites,
)


@dataclass
class _FakeProc:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


# --------------------------------------------------------------------------- #
# 编排：ensure_label × PROCESS_LABELS（Spec-0023/T1：不再建 test 分支）
# --------------------------------------------------------------------------- #


def test_ensure_prerequisites_orchestrates_labels_only(monkeypatch):
    # 打桩被复用的幂等函数，断言 ensure_prerequisites 只编排标签、不再建任何分支。
    label_calls = []
    monkeypatch.setattr(github, "ensure_label", lambda *, name: label_calls.append(name))

    ensure_prerequisites()

    # 对 PROCESS_LABELS 中每个标签各调一次 ensure_label（顺序一致）。
    assert label_calls == list(PROCESS_LABELS)
    # test 分支自举已移除：github 不再暴露 ensure_branch。
    assert not hasattr(github, "ensure_branch")


# --------------------------------------------------------------------------- #
# 幂等：已存在标签 → 重复调用均 no-op，不抛错
# --------------------------------------------------------------------------- #


def test_ensure_prerequisites_idempotent_when_all_exist(monkeypatch):
    # 在 subprocess 层模拟「标签 already exists（非零退出）」，连调两次断言不抛错——
    # 幂等性由被复用的 ensure_label 承担。
    def runner(args, **kwargs):
        # gh label create ... → 模拟 already exists（ensure_label 吞掉视为成功）。
        if args[:3] == ["gh", "label", "create"]:
            return _FakeProc(returncode=1, stderr="label already exists")
        return _FakeProc(returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", runner)

    ensure_prerequisites()
    ensure_prerequisites()  # 第二次仍 no-op，不应抛异常


# --------------------------------------------------------------------------- #
# 标签单一来源：三处既有公共名为 github 常量的别名（is 同一对象）
# --------------------------------------------------------------------------- #


def test_label_constants_are_aliases_of_github():
    assert cli.DISCOVERY_LABEL is github.DISCOVERY_LABEL


def test_process_labels_cover_all_four():
    # Spec-0039/T1：认领标签 openagents-dispatching 并入 PROCESS_LABELS（第 4 个流程标签），
    # 由 ensure_prerequisites 一并幂等自举。
    assert PROCESS_LABELS == (DISCOVERY_LABEL, APPROVAL_LABEL, BLOCKED_LABEL, DISPATCH_LABEL)
    assert (DISCOVERY_LABEL, APPROVAL_LABEL, BLOCKED_LABEL, DISPATCH_LABEL) == (
        "openagents",
        "rfc-approved",
        "needs-human",
        "openagents-dispatching",
    )
