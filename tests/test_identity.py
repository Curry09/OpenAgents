"""RFC-0011 T2: module (IDM+VP)

All external side effects amock/injection:
- env：monkeypatch os.environ（OPENAGENTS_AGENT_ID）。
-state: Control get/set_agent_id with real Runtestate (tmp_path) or pseudostate.
- github.post_comment:monkeypayt, which asserts that the text after the stamp is sent.

Overwrite: sign/parse round-trip; unsigned/real text resolution to None; resolve_agent_id
env > Runtestate > automatically generate three-tier priority and drop-stability; post_signed_comment stamp and send.

# Spec-0063/T2: identity reconnect runtime.RuntimeState, and then the test moved from the old State to Runtestate.
"""

import pytest

from openagents.runtime.state import RuntimeState
from openagents.utils import identity as identity_module
from openagents.utils.identity import (
    AGENT_ID_ENV,
    parse_agent_id,
    post_signed_comment,
    resolve_agent_id,
    sign,
)


class _FakeState:
    """Hypothetically Runtestate: Memory maintenance agent_id, record number of calls."""

    def __init__(self, *, agent_id=None):
        self._agent_id = agent_id
        self.set_calls = []

    def get_agent_id(self):
        return self._agent_id

    def set_agent_id(self, *, agent_id):
        self.set_calls.append(agent_id)
        self._agent_id = agent_id


# --------------------------------------------------------------------------- #
# Sign / parse_agent_id round-trip
# --------------------------------------------------------------------------- #


def test_sign_then_parse_roundtrips():
    signed = sign(body="Text", agent_id="alice")
    assert parse_agent_id(body=signed) == "alice"


def test_sign_appends_marker_at_end_and_keeps_body():
    signed = sign(body="hello", agent_id="bot-1")
    assert signed.startswith("hello")
    assert "<!-- openagents:agent=bot-1 -->" in signed
    # The signature is added at the end and the original text is retained in its entirety.
    assert signed.index("hello") < signed.index("openagents:agent")


def test_parse_agent_id_none_for_unsigned_body():
    assert parse_agent_id(body="A real comment. No signature.") is None


def test_parse_agent_id_none_for_empty_body():
    assert parse_agent_id(body="") is None


def test_parse_agent_id_ignores_lookalike_text():
    # The character set is limited ([A-Za-z0-9_-]) and the non-annotated text in the body is not missigned.
    assert parse_agent_id(body="Opengents: agent=alice") is None


def test_sign_roundtrip_with_hex_id():
    signed = sign(body="x", agent_id="a1b2c3d4")
    assert parse_agent_id(body=signed) == "a1b2c3d4"


# --------------------------------------------------------------------------- #
# resolve_agent_id Level 3 Priority
# --------------------------------------------------------------------------- #


def test_resolve_prefers_env(monkeypatch):
    # env top priority: use env even if the state has already been given value.
    monkeypatch.setenv(AGENT_ID_ENV, "from-env")
    state = _FakeState(agent_id="from-state")

    assert resolve_agent_id(state=state) == "from-env"
    # env does not write state (no-contaminated drop value) when hit.
    assert state.set_calls == []


def test_resolve_falls_back_to_state(monkeypatch):
    monkeypatch.delenv(AGENT_ID_ENV, raising=False)
    state = _FakeState(agent_id="from-state")

    assert resolve_agent_id(state=state) == "from-state"
    # state does not drop a disk when a value already exists.
    assert state.set_calls == []


def test_resolve_generates_and_persists_when_missing(monkeypatch):
    monkeypatch.delenv(AGENT_ID_ENV, raising=False)
    state = _FakeState(agent_id=None)

    agent_id = resolve_agent_id(state=state)

    # Automatically generate non-empty, restricted character sets.
    assert agent_id
    assert all(c.isalnum() or c in "_-" for c in agent_id)
    # Put the wheel down immediately so that the follow-up process can be brought to the same id.
    assert state.set_calls == [agent_id]


def test_resolve_generated_id_is_stable_across_calls(monkeypatch, tmp_path):
    # Use real Runtestate: First creation of a landing disc, second (new Runtestate instance, simulation of new process) to reuse the same value.
    monkeypatch.delenv(AGENT_ID_ENV, raising=False)
    path = tmp_path / ".openagents" / "runtime-state.json"

    first = resolve_agent_id(state=RuntimeState(path=path))
    second = resolve_agent_id(state=RuntimeState(path=path))

    assert first == second


def test_resolve_env_blank_falls_through(monkeypatch):
    # Sets the env as a blank string view unset, which goes back to state/ generation.
    monkeypatch.setenv(AGENT_ID_ENV, "   ")
    state = _FakeState(agent_id="from-state")

    assert resolve_agent_id(state=state) == "from-state"


# --------------------------------------------------------------------------- #
# post_signed_comment
# --------------------------------------------------------------------------- #


def test_post_signed_comment_signs_then_posts(monkeypatch):
    # Spec-0064/T5: post_signed_comment now reads "Sync and read back to check the missing signature" - normal path reads back comments with its own signature.
    # No signature. Therefore, in addition to post_comment, a stick of list_comments is required to return the newly sent signature comment, so that this example is used in hermetic.
    from openagents.utils.github import Comment

    posted = {}

    def _post(*, pr_number, body):
        posted.update(pr_number=pr_number, body=body)

    monkeypatch.setattr(identity_module.github, "post_comment", _post)
    monkeypatch.setattr(
        identity_module.github,
        "list_comments",
        lambda *, pr_number: [
            Comment(
                id="1",
                author="alice",
                body="🤖 Updated RFC\n\n<!-- openagents:agent=alice -->",
                created_at="2026-01-01T00:00:00Z",
            )
        ],
    )

    post_signed_comment(pr_number=5, body="Updated RFC", agent_id="alice")

    assert posted["pr_number"] == 5
    # Read back comments with this instance signature  →  without a signature, posted still the original signature reply.
    assert posted["body"].startswith("Updated RFC")
    # The text of the sent text is signed and can be parsed back to agent_id.
    assert parse_agent_id(body=posted["body"]) == "alice"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
