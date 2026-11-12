"""Spec-0051/T3: worknote (agent ”What’s This Round done” in response) module testing.

Worknote is a pure string module (simulated blocknote/replynote) that only eats base dollars st, no side effects, no signature, no IO.
Coverage: two render_* stable upswings; culture in reason ci/review; summy empty-backed seating;
Pure function certainty; no external import side effects (no reverse import orcherator).
"""

from openagents.utils import worknote


def test_render_implement_header_and_summary():
    body = worknote.render_implement(summary="T1/T2 was achieved with two pure functions")
    assert body.startswith("## Implementation report")
    assert "T1/T2 was achieved with two pure functions" in body


def test_render_iterate_reasons_localized():
    ci = worknote.render_iterate(reason="ci", summary="I’ve completed the single test.")
    review = worknote.render_iterate(reason="review", summary="Changed the name.")
    assert ci.startswith("## Iteration report (CI feedback)")
    assert review.startswith("## Iteration report (Code review feedback)")
    # Two types of reasson look different to re-register natural sub-breaths, unstoppable.
    assert len({ci.splitlines()[0], review.splitlines()[0]}) == 2
    assert "I’ve completed the single test." in ci


def test_render_iterate_unknown_reason_falls_back_to_literal():
    body = worknote.render_iterate(reason="mystery", summary="x")
    assert body.startswith("## Iteration report")


def test_empty_summary_falls_back_to_placeholder():
    # # Sommary = ''back to the seat, not to miss, to keep the structure intact.
    assert "(No summary)" in worknote.render_implement(summary="")
    assert "(No summary)" in worknote.render_iterate(reason="ci", summary="   ")


def test_render_functions_are_deterministic():
    assert worknote.render_implement(summary="a") == worknote.render_implement(summary="a")
    assert worknote.render_iterate(reason="ci", summary="a") == worknote.render_iterate(
        reason="ci", summary="a"
    )


def test_worknote_does_not_import_orchestrator():
    """Worknote does not reverse i.M.I. Report orchestrator/github/identity (maintain display module decoupling, concept 10).

    Check only**import line** (rather than the words in the text/docstring) to avoid miscalculation of the reference to the module name.
    """
    import openagents.utils.worknote as mod

    with open(mod.__file__, encoding="utf-8") as fh:
        import_lines = [line for line in fh if line.startswith(("import ", "from "))]
    for line in import_lines:
        for forbidden in ("orchestrator", "identity", "github", "openagents"):
            assert forbidden not in line, f"Worknote should not irk {forbidden}：{line!r}"
