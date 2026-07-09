"""Spec-0060/T1: utils.github 稳定面单测——断言读/写/类型均为 github.py 同名原语的再导出。

薄再导出的契约就是「同一对象、行为等价」：逐个断言 utils.github.X is github.X，无需触网。
"""

from __future__ import annotations

from openagents.utils import github
from openagents.utils import github as ugithub


def test_read_primitives_are_reexports():
    for name in (
        "get_issue",
        "find_pr_by_branch",
        "list_comments",
        "list_issue_comments",
        "is_open",
        "pr_head_branch",
    ):
        assert getattr(ugithub, name) is getattr(github, name), name


def test_machine_comment_write_primitives_are_reexports():
    assert ugithub.post_comment is github.post_comment
    assert ugithub.issue_comment is github.issue_comment


def test_types_and_error_are_reexports():
    assert ugithub.Issue is github.Issue
    assert ugithub.PR is github.PR
    assert ugithub.Comment is github.Comment
    assert ugithub.GithubError is github.GithubError
