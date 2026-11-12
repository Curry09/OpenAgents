# Spec-0020/T1
"""Restate an issue objective, scope, and exclusions before creating it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openagents.backends.base import AgentBackend

# The backend output uses stable field names, independent of display labels.
_MARK_WANT = "want:"
_MARK_BOUNDARY = "boundary:"
_MARK_NON_GOALS = "non_goals:"
_AFFIRMATIVE = {"y", "yes"}

_RESTATE_TASK = (
    "Restate the draft issue in plain language so its author can confirm the scope. "
    "Return exactly three lines, with these field names and no other text:\n"
    f"{_MARK_WANT} <requested outcome>\n"
    f"{_MARK_BOUNDARY} <scope and constraints>\n"
    f"{_MARK_NON_GOALS} <explicit exclusions>"
)


@dataclass(frozen=True)
class Draft:
    """Hold the draft issue title and body."""

    title: str
    body: str


@dataclass(frozen=True)
class Alignment:
    """Hold the requested outcome, scope, and exclusions."""

    want: str
    boundary: str
    non_goals: str

    def render(self) -> str:
        """Format the restatement for the issue author's confirmation."""
        return f"Objective: {self.want}\nScope: {self.boundary}\nOut of scope: {self.non_goals}"


def restate(*, draft: Draft, backend: AgentBackend) -> Alignment:
    """Ask the backend to restate the issue without prompting the operator."""
    result = backend.run(
        work_dir=Path.cwd(),
        task=_RESTATE_TASK,
        context=f"Title: {draft.title}\nBody: {draft.body}",
    )
    return _parse_alignment(text=getattr(result, "protocol_output", result.summary))


def is_confirmed(*, answer: str) -> bool:
    """Accept only an explicit affirmative response."""
    return answer.strip().lower() in _AFFIRMATIVE


def _parse_alignment(*, text: str) -> Alignment:
    """Parse stable field markers, using an empty string for missing fields."""
    sections = {_MARK_WANT: "", _MARK_BOUNDARY: "", _MARK_NON_GOALS: ""}
    for line in text.splitlines():
        stripped = line.strip()
        for mark in sections:
            if stripped.startswith(mark):
                sections[mark] = stripped[len(mark) :].strip()
    return Alignment(
        want=sections[_MARK_WANT],
        boundary=sections[_MARK_BOUNDARY],
        non_goals=sections[_MARK_NON_GOALS],
    )
