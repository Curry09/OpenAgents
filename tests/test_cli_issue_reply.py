"""# Spec-0016/T5：reply-comment --issue 手动出口（与 --pr 互斥二选一）契约测试。

覆盖：
- oa reply-comment --issue N --body X 经 identity.post_signed_comment_on_issue 落 issue；
- --pr 与 --issue 同给报错、都不给报错（argparse 互斥必选组）；
- --pr N --body X 仍走既有 post_signed_comment（零回归）。
"""

from pathlib import Path

import pytest

from openagents.cli import build_parser, main


class _FakeCtx:
    def __init__(self, repo_root):
        self.repo_root = Path(repo_root)
        self.remote = "origin"


def _stub_project(monkeypatch, ctx):
    monkeypatch.setattr("openagents.cli.ensure_project", lambda *, interactive: ctx)
    monkeypatch.setattr("openagents.cli.github.ensure_prerequisites", lambda: None)
    monkeypatch.setattr("openagents.cli._persist_ui_capable", lambda *, ctx: None)
    monkeypatch.setattr("openagents.cli._agent_id_for", lambda *, ctx: "AID")


# ---- argparse：--pr / --issue 互斥必选 -----------------------------------------------------------


def test_issue_flag_parses():
    args = build_parser().parse_args(["reply-comment", "--issue", "149", "--body", "hi"])
    assert args.issue == 149 and args.pr is None


def test_pr_flag_still_parses():
    args = build_parser().parse_args(["reply-comment", "--pr", "5", "--body", "hi"])
    assert args.pr == 5 and args.issue is None


def test_pr_and_issue_together_errors():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["reply-comment", "--pr", "5", "--issue", "149", "--body", "hi"])


def test_neither_pr_nor_issue_errors():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["reply-comment", "--body", "hi"])


# ---- 转发：--issue → post_signed_comment_on_issue；--pr → post_signed_comment（零回归）-------------


def test_issue_forwards_to_signed_issue_comment(monkeypatch, tmp_path):
    _stub_project(monkeypatch, _FakeCtx(tmp_path))
    captured = {}
    import openagents.utils.identity as identity_mod

    monkeypatch.setattr(
        identity_mod, "post_signed_comment_on_issue", lambda **kw: captured.update(kw)
    )
    rc = main(["reply-comment", "--issue", "149", "--body", "收到"])
    assert rc == 0
    assert captured == {"number": 149, "body": "收到", "agent_id": "AID"}


def test_pr_forwards_to_signed_pr_comment(monkeypatch, tmp_path):
    _stub_project(monkeypatch, _FakeCtx(tmp_path))
    captured = {}
    import openagents.utils.identity as identity_mod

    monkeypatch.setattr(identity_mod, "post_signed_comment", lambda **kw: captured.update(kw))
    rc = main(["reply-comment", "--pr", "3", "--body", "hi"])
    assert rc == 0
    assert captured == {"pr_number": 3, "body": "hi", "agent_id": "AID"}


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
