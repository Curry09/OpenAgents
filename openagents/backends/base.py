"""RFC-0001 T1: 后端抽象层 —— AgentBackend 协议与 AgentResult。

决策 2：用 Protocol 抽象后端，MVP 只实现一个适配器（Claude Code，见 T2）。
新增后端只需实现满足本协议的类，无需改动编排层。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AgentResult:
    """一次 agent 运行的结果。

    changed: 是否产生了代码改动。
    summary: 对本次改动的简短说明（供 PR 正文/评论使用）。
    """

    changed: bool
    summary: str


@runtime_checkable
class AgentBackend(Protocol):
    """coding agent 后端的统一契约（RFC-0001 接口契约）。"""

    name: str

    def run(self, *, work_dir: Path, task: str, context: str) -> AgentResult:
        """在 work_dir 内按 task 描述改代码；context 携带 issue 正文与历史 comment。"""
        ...
