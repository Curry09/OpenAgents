"""#Spec-0016/T3: context.for_issue_reply (issue returns placeholder) unit testing.

Coverage:
- Placeholder for for_issue_reply output containing issue_number/ comment_body/ contrext/ work_dir key
- Key: ** does not include ** pr_number / brancy (issue has no branch);
-Context, the body of the comment (the object of the response itself), without reading the gthub (reference to submission already includes body);
- There is no change in the behaviour of the PR version of for_reply (no behavior change).
"""

from pathlib import Path

import pytest

from openagents.runtime import context
from openagents.utils.github import Comment


def _comment(*, body):
    return Comment(id="c1", author="alice", body=body, created_at="2026-07-14T12:00:00Z")


def test_for_issue_reply_placeholder_keys():
    payload = context.for_issue_reply(
        work_dir=Path("/tmp/wt"),
        issue_number=149,
        comment=_comment(body="Supplement: Support for codex as well"),
    )
    assert payload["issue_number"] == 149
    assert "Supplement: Support for codex as well" in payload["context"]
    assert "comment_body" not in payload
    assert payload["context"] == "--- human comment ---\nSupplement: Support for codex as well"
    assert payload["work_dir"] == Path("/tmp/wt")


def test_for_issue_reply_has_no_pr_keys():
    payload = context.for_issue_reply(
        work_dir=Path("/tmp/wt"), issue_number=149, comment=_comment(body="x")
    )
    assert "pr_number" not in payload
    assert "branch" not in payload


def test_for_reply_pr_version_unchanged():
    # Spec-0081/T1: The main body of the PR only keeps the positional cursor only at the context, the tsk.
    payload = context.for_reply(
        work_dir=Path("/tmp/wt"),
        pr_number=7,
        branch="openagents/issue-7",
        comment=_comment(body="PR Comments"),
    )
    assert payload["pr_number"] == 7
    assert payload["branch"] == "openagents/issue-7"
    assert "PR Comments" in payload["context"]
    assert "comment_body" not in payload


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
