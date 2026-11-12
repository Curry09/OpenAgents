# Spec-0036/T2
"""Render a reply quoting the original comment.

Formatting is pure. The caller signs and posts the completed text.
"""

from __future__ import annotations

# Text: Quote Heads Up + Respond Up. Quote Heads Up: "I'm responding to your comment below" and use robots in response.
# The emoji is the same as the hanging/judgment comment. Response is the place for free time, ensuring that the two paragraphs of the Quote + Response are always structured.
_QUOTE_HEADER = "In response to your comment:"
_RESPONSE_HEADER = "🤖"
_EMPTY_RESPONSE = "(No further details)"


def build(*, original: str, response: str) -> str:
    """Quote the original comment and append the agent reply; do not sign or post it.
    Spec-0036/T2.
    """
    quoted = _as_quote(text=original) if original.strip() else "> (Original comment is empty)"
    body = response.strip() if response.strip() else _EMPTY_RESPONSE
    return f"{_QUOTE_HEADER}\n{quoted}\n\n{_RESPONSE_HEADER} {body}"


def _as_quote(*, text: str) -> str:
    """Wrap each line in a Markdown block quote."""
    return "\n".join(f"> {line}" for line in text.splitlines())
