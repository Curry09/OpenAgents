# RFC-0001
"""Define the backend protocol, invocation result, and shared execution limits."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

# Spec-0046: preserve the deployed name; Vigil and Claude share this invocation budget.
MAX_WALL_ENV = "OPENAGENTS_CLAUDE_MAX_WALL"
_DEFAULT_MAX_WALL = 3600.0


def effective_max_wall() -> float:
    """Spec-0046/T1: shared invocation budget; finite nonpositive values disable it."""
    raw = os.environ.get(MAX_WALL_ENV, "").strip()
    try:
        value = float(raw) if raw else _DEFAULT_MAX_WALL
    except ValueError:
        return _DEFAULT_MAX_WALL
    if not math.isfinite(value):
        return _DEFAULT_MAX_WALL
    return max(value, 0.0)


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
    """The result of an agent running.

    Changed: Is there a code change?
    Summary: A brief description of the change (for PR body/commentation, limited in length).
    raw_output: Full final output of the backend for the structification protocol; back-back of the old backend when not provided.
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
    """(d) The unified contract for the back end of the code of command (RFC-0001 interface contract)."""

    name: str

    def run(self, *, work_dir: Path, task: str, context: str) -> AgentResult:
        """Press task description to change code in work_dir; consult carries issue text and history comments."""
        ...
