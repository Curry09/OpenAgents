"""Spec-0036/T2: replynote.build quotes the unit test (pure function, no IO) of the original comment response structure.

Coverage:
- Normal original/response reference block + response paragraph is complete;
- Original multiline line-by-line reference block packages;
- Response is empty and unobserved;
- Original is empty and the reference section is not missing;
- Not including a signature (signature is covered by the call);
- Pure function does not have IO (only by input output).
"""

import pytest

from openagents.utils import replynote


def test_build_has_quote_and_response():
    body = replynote.build(
        original="Resolve OVERVIEW.md first, then move state.py.",
        response="Resolved the conflict and pushed the changes",
    )
    # The quote is the original comment.
    assert "> Resolve OVERVIEW.md first, then move state.py." in body
    # The response is complete.
    assert "Resolved the conflict and pushed the changes" in body


def test_build_wraps_multiline_original_in_quote():
    body = replynote.build(original="First line\nSecond line", response="Copy that.")
    assert "> First line" in body
    assert "> Second line" in body


def test_build_empty_response_has_placeholder():
    body = replynote.build(original="Human Review", response="")
    # The reference paragraph is still in place (structure complete, no missing paragraph).
    assert "> Human Review" in body
    assert "(No further details)" in body


def test_build_blank_response_has_placeholder():
    # Only empty response is also in position (strip is empty).
    body = replynote.build(original="Human Review", response="   \n  ")
    assert "(No further details)" in body


def test_build_empty_original_has_placeholder():
    body = replynote.build(original="", response="I did it, X.")
    # Reference paragraph is not missing (in place), response paragraph remains the same.
    assert "(Original comment is empty)" in body
    assert "I did it, X." in body


def test_build_contains_no_signature():
    # The signature is covered by the caller - the build itself may not contain a hidden signature mark.
    body = replynote.build(original="x", response="y")
    assert "openagents:agent=" not in body


def test_build_is_pure_function():
    # Same bytes of the same caller output (no hidden status / no IO / no read clock).
    a = replynote.build(original="x", response="y")
    b = replynote.build(original="x", response="y")
    assert a == b


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
