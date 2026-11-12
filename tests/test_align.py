"""Spec-0020/T1: Unit testing for front door alignment module align.

Backend, over: reset backend refill retend to repeat the draft as X/Y/Z in three,
Backend is inserted with keyword parameters and called only once, return values are correctly removed, and render contains three-part identifiers; confirmation of determination
It is a pure word (removable, negative/free, unmodified) that generates a solution to the repetition.
"""

from pathlib import Path

from openagents.backends.base import AgentResult
from openagents.utils import align
from openagents.utils.align import Alignment, Draft, is_confirmed, restate


class _StubBackend:
    """The log calls and enters false backends, which are repeated in three paragraphs by preset text (without real LLM)."""

    name = "stub"

    def __init__(self, *, summary):
        self.calls = []
        self._summary = summary

    def run(self, *, work_dir, task, context):
        self.calls.append({"work_dir": work_dir, "task": task, "context": context})
        return AgentResult(changed=False, summary=self._summary)


_RESTATED = (
    "want: Add a café sign-in page\nboundary: Email and password only\nnon_goals: Third-party OAuth"
)


def test_restate_splits_into_three_sections():
    backend = _StubBackend(summary=_RESTATED)

    alignment = restate(draft=Draft(title="Sign in", body="Request sign-in"), backend=backend)

    assert isinstance(alignment, Alignment)
    assert alignment.want == "Add a café sign-in page"
    assert alignment.boundary == "Email and password only"
    assert alignment.non_goals == "Third-party OAuth"


def test_restate_calls_backend_once_with_keyword_args():
    backend = _StubBackend(summary=_RESTATED)

    restate(draft=Draft(title="T", body="B"), backend=backend)

    # Backend is injected with a keyword parameter and called in a timely manner; draft title/body is entered into the context.
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert isinstance(call["work_dir"], Path)
    assert "T" in call["context"] and "B" in call["context"]


def test_render_contains_three_section_markers():
    rendered = Alignment(want="X", boundary="Y", non_goals="Z").render()

    assert "Objective:" in rendered
    assert "Scope:" in rendered
    assert "Out of scope:" in rendered
    assert "X" in rendered and "Y" in rendered and "Z" in rendered


def test_parse_tolerates_missing_section():
    # Missing paragraph back-firing (incorrect) without error.
    backend = _StubBackend(summary="want: One section only")

    alignment = restate(draft=Draft(title="T", body="B"), backend=backend)

    assert alignment.want == "One section only"
    assert alignment.boundary == ""
    assert alignment.non_goals == ""


def test_is_confirmed_affirmative_passes():
    assert is_confirmed(answer="y") is True
    assert is_confirmed(answer="yes") is True
    assert is_confirmed(answer="  Y  ") is True
    assert is_confirmed(answer="YES") is True


def test_is_confirmed_negative_or_empty_does_not_pass():
    assert is_confirmed(answer="n") is False
    assert is_confirmed(answer="no") is False
    assert is_confirmed(answer="") is False
    assert is_confirmed(answer="   ") is False


def test_is_confirmed_does_not_touch_backend():
    # Confirms that the determination is a pure word - a combination with the recapitulation generation and does not depend on any back / I/O.
    assert align.is_confirmed.__module__ == "openagents.utils.align"
    assert is_confirmed(answer="random") is False
