"""RFC-0001 T1: 后端抽象层 —— AgentBackend 协议与 AgentResult。

决策 2：用 Protocol 抽象后端，MVP 只实现一个适配器（Claude Code，见 T2）。
新增后端只需实现满足本协议的类，无需改动编排层。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class TokenUsage:
    """Normalized token counts reported by one backend invocation."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    model: str | None = None
    total_source: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise ValueError(f"{name} must be a non-negative integer or None")
        if self.total_source not in (None, "reported", "derived-components"):
            raise ValueError("total_source must be reported, derived-components, or None")
        if self.total_tokens is None and self.total_source is not None:
            raise ValueError("total_source requires total_tokens")
        if self.total_tokens is not None and self.total_source is None:
            raise ValueError("total_tokens requires total_source")


@dataclass(frozen=True)
class AgentResult:
    """一次 agent 运行的结果。

    changed: 是否产生了代码改动。
    summary: 对本次改动的简短说明（供 PR 正文/评论使用，可限长）。
    raw_output: 后端的完整最终输出，供结构化协议解析；旧后端不提供时回退 summary。
    """

    changed: bool
    summary: str
    raw_output: str | None = None
    tool_events: tuple[str, ...] = ()
    usage: TokenUsage | None = None

    @property
    def protocol_output(self) -> str:
        """Return the unabridged machine-protocol payload when available."""
        return self.summary if self.raw_output is None else self.raw_output


@runtime_checkable
class AgentBackend(Protocol):
    """coding agent 后端的统一契约（RFC-0001 接口契约）。"""

    name: str

    def run(self, *, work_dir: Path, task: str, context: str) -> AgentResult:
        """在 work_dir 内按 task 描述改代码；context 携带 issue 正文与历史 comment。"""
        ...
