"""#Spec-0016/T3: replier.ISSUE_PROMPT (issue language, no change in code only) unit testing

Coverage:
- ISSUE_PROMPT.substitute can fill issue_number/ comment_body;
- Rendering text** does not contain ** bold / change code / delivery protocol,** including ** intent to ”suspension of the code”;
- Reuse the same OUTPUT_SCHEMA;
- The existing PR version of PROMPT is unchanged (the placeholder remains pr_number/branch/comment_body).
"""

import pytest

from openagents.agents import replier


def test_issue_prompt_substitutes_placeholders():
    text = replier.ISSUE_PROMPT.substitute(issue_number=149)
    assert "149" in text
    assert "context below" in text


def test_issue_prompt_has_no_branch_or_code_change_intent():
    text = replier.ISSUE_PROMPT.substitute(issue_number=149, comment_body="x")
    # Issue has no branch of work: no branch placeholder or word should appear.
    assert "$branch" not in replier.ISSUE_PROMPT.template
    assert "branch" not in text
    # The only answer is: "Answer only, not change the code" and "P" only appears in the negative context (do not open the PR).
    assert "Reply only" in text and "Do not edit code" in text
    assert "open a PR" in text  # In the negative of "Don't open the PR"


def test_issue_prompt_reuses_output_schema():
    assert replier.OUTPUT_SCHEMA == {"reply": str, "resolved": bool}


def test_pr_prompt_unchanged():
    # Spec-0081/T1: Only pr_number/ Branch is reserved for PR, comment body to be used as a context.
    text = replier.PROMPT.substitute(pr_number=7, branch="openagents/issue-7")
    assert "7" in text and "openagents/issue-7" in text
    assert "context below" in text


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
