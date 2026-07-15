"""# Spec-0016/T3：context.for_issue_reply（issue 回复占位符组装）单元测试。

覆盖：
- for_issue_reply 产出含 issue_number / comment_body / context / work_dir 键的占位符 dict；
- issue 键：**不含** pr_number / branch（issue 尚无工作分支）；
- context 即那条评论正文（回应对象本身），不二次读 github（入参 comment 已含 body）；
- 既有 PR 版 for_reply 行为不变（零回归）。
"""

from pathlib import Path

import pytest

from openagents.runtime import context
from openagents.utils.github import Comment


def _comment(*, body):
    return Comment(id="c1", author="alice", body=body, created_at="2026-07-14T12:00:00Z")


def test_for_issue_reply_placeholder_keys():
    payload = context.for_issue_reply(
        work_dir=Path("/tmp/wt"), issue_number=149, comment=_comment(body="补充：也要支持 codex")
    )
    assert payload["issue_number"] == 149
    assert payload["comment_body"] == "补充：也要支持 codex"
    assert payload["context"] == "补充：也要支持 codex"
    assert payload["work_dir"] == Path("/tmp/wt")


def test_for_issue_reply_has_no_pr_keys():
    payload = context.for_issue_reply(
        work_dir=Path("/tmp/wt"), issue_number=149, comment=_comment(body="x")
    )
    assert "pr_number" not in payload
    assert "branch" not in payload


def test_for_reply_pr_version_unchanged():
    # 零回归：PR 版仍带 pr_number / branch / comment_body。
    payload = context.for_reply(
        work_dir=Path("/tmp/wt"),
        pr_number=7,
        branch="openagents/issue-7",
        comment=_comment(body="PR 评论"),
    )
    assert payload["pr_number"] == 7
    assert payload["branch"] == "openagents/issue-7"
    assert payload["comment_body"] == "PR 评论"


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
