"""Spec-0064/T5: CLI Condense as Four Commands + Hide Reply-Commment + YAML/flag Overwrite + Scorching Compact Test.

Thin route (stabbing pillar recipe/workshop, not really running Vigil, not touching real gh/back end):
  - Persons are only on vigil/issue/backfill-rfc/release; old nine commands (rfc/refine-rfc/implement/iterate/)
    solve/poll/watch/vigil-all/fleet is no longer registered; reply-comment can still be deciphered (hidden, help=SUPPRESS).
  - _effective_config: YAML Single Source + --skip One-time cover; illegal sidewalks and zero locks report errors.
  -backfill-refc forward recipes.backfill; reply-comment forward identity.post_signed_comment.
  - post_signed_comment synced and verified the missing signature  →  supplementary signature (not just warn).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openagents.cli import _effective_config, build_parser, main


def _subparsers(parser):
    return next(a for a in parser._actions if getattr(a, "choices", None))


class _FakeCtx:
    def __init__(self, repo_root):
        self.repo_root = Path(repo_root)
        self.remote = "origin"


def _stub_project(monkeypatch, ctx):
    monkeypatch.setattr("openagents.cli.ensure_project", lambda *, interactive: ctx)
    monkeypatch.setattr("openagents.cli.github.ensure_prerequisites", lambda: None)
    monkeypatch.setattr("openagents.cli._persist_ui_capable", lambda *, ctx: None)


# --------------------------------------------------------------------------- #
# Parsing: Four Commands in Book + the old nine commands downline + fully-comment hidden
# --------------------------------------------------------------------------- #


def test_four_human_facing_commands_registered():
    choices = _subparsers(build_parser()).choices
    for cmd in ("vigil", "issue", "backfill-rfc", "release"):
        assert cmd in choices


def test_old_nine_commands_removed():
    choices = _subparsers(build_parser()).choices
    for cmd in (
        "rfc",
        "refine-rfc",
        "implement",
        "iterate",
        "solve",
        "poll",
        "watch",
        "vigil-all",
        "fleet",
    ):
        assert cmd not in choices


def test_reply_comment_hidden_but_parseable():
    choices = _subparsers(build_parser()).choices
    assert "reply-comment" in choices
    args = build_parser().parse_args(["reply-comment", "--pr", "5", "--body", "hi"])
    assert args.pr == 5


def test_vigil_parses_override_flags():
    args = build_parser().parse_args(
        [
            "vigil",
            "--interval",
            "5",
            "--label",
            "bug",
            "--base",
            "dev",
            "--once",
            "--skip",
            "ci",
            "--config",
            "x.yml",
        ]
    )
    assert args.interval == 5
    assert args.label == ["bug"]
    assert args.skip == "ci"
    assert args.once is True


# --------------------------------------------------------------------------- #
# _effective_config: YAML Single Real Source + flag One-time overwrite
# --------------------------------------------------------------------------- #


def _write_config(tmp_path, text):
    d = tmp_path / ".openagents"
    d.mkdir(parents=True, exist_ok=True)
    (d / "openagents.yml").write_text(text, encoding="utf-8")


def _vigil_args(**over):
    argv = ["vigil"]
    for k, v in over.items():
        argv += [f"--{k}", str(v)]
    return build_parser().parse_args(argv)


def test_effective_config_missing_yaml_defaults(tmp_path):
    ctx = _FakeCtx(tmp_path)
    config = _effective_config(ctx=ctx, args=_vigil_args())
    assert config.stages.owner_of(stage="merge") == "agent"
    assert config.base == "main"


def test_effective_config_reads_yaml(tmp_path):
    _write_config(tmp_path, "stages:\n  e2e: skip\n")
    ctx = _FakeCtx(tmp_path)
    config = _effective_config(ctx=ctx, args=_vigil_args())
    assert config.stages.owner_of(stage="e2e") == "skip"


def test_effective_config_flag_overrides_yaml(tmp_path):
    _write_config(tmp_path, "stages:\n  e2e: skip\n")
    ctx = _FakeCtx(tmp_path)
    config = _effective_config(ctx=ctx, args=_vigil_args(skip="ci", base="dev"))
    assert config.stages.owner_of(stage="ci") == "skip"
    assert config.base == "dev"
    assert config.stages.owner_of(stage="e2e") == "skip"


def test_retired_hold_flag_is_rejected_by_parser():
    with pytest.raises(SystemExit):
        build_parser().parse_args(["vigil", "--hold", "ci"])


def test_effective_config_zero_gate_override_raises(tmp_path):
    ctx = _FakeCtx(tmp_path)
    with pytest.raises(ValueError, match="Automatic merge requires agent review"):
        _effective_config(ctx=ctx, args=_vigil_args(skip="review"))


# --------------------------------------------------------------------------- #
# Forward: Backfill-refc /reply-comment
# --------------------------------------------------------------------------- #


def test_backfill_rfc_forwards_to_recipe(monkeypatch, tmp_path):
    ctx = _FakeCtx(tmp_path)
    _stub_project(monkeypatch, ctx)
    monkeypatch.setattr("openagents.cli._backend_for", lambda: "BE")
    captured = {}
    import openagents.recipes.backfill as backfill_mod

    monkeypatch.setattr(
        backfill_mod, "backfill_rfc", lambda **kw: captured.update(kw) or {"pr_number": 9}
    )
    rc = main(["backfill-rfc", "openagents/x.py"])
    assert rc == 0
    assert captured["path"] == "openagents/x.py"


def test_reply_comment_forwards_signed(monkeypatch, tmp_path):
    ctx = _FakeCtx(tmp_path)
    _stub_project(monkeypatch, ctx)
    monkeypatch.setattr("openagents.cli._agent_id_for", lambda *, ctx: "AID")
    captured = {}
    import openagents.utils.identity as identity_mod

    monkeypatch.setattr(identity_mod, "post_signed_comment", lambda **kw: captured.update(kw))
    rc = main(["reply-comment", "--pr", "3", "--body", "hi"])
    assert rc == 0
    assert captured == {"pr_number": 3, "body": "hi", "agent_id": "AID"}


# --------------------------------------------------------------------------- #
# Comment signing: route the request and verify the final signature.
# --------------------------------------------------------------------------- #


def test_post_signed_comment_verifies_and_fixes_missing_signature(monkeypatch):
    import openagents.utils.identity as identity_mod
    from openagents.utils.github import Comment

    posted: list[str] = []
    monkeypatch.setattr(
        identity_mod.github, "post_comment", lambda *, pr_number, body: posted.append(body)
    )
    monkeypatch.setattr(
        identity_mod.github,
        "list_comments",
        lambda *, pr_number: [
            Comment(
                id="1", author="a", body="No signature for naked reply", created_at="2026-01-01"
            )
        ],
    )
    identity_mod.post_signed_comment(pr_number=1, body="Reply", agent_id="AID")
    assert len(posted) == 2  # Sign Reply + Backup (not just Warn)
    assert "openagents:agent=AID" in posted[1]


def test_post_signed_comment_no_fix_when_signature_present(monkeypatch):
    import openagents.utils.identity as identity_mod
    from openagents.utils.github import Comment

    posted: list[str] = []
    monkeypatch.setattr(
        identity_mod.github, "post_comment", lambda *, pr_number, body: posted.append(body)
    )
    monkeypatch.setattr(
        identity_mod.github,
        "list_comments",
        lambda *, pr_number: [
            Comment(
                id="1",
                author="a",
                body="Reply\n\n<!-- openagents:agent=AID -->",
                created_at="2026-01-01",
            )
        ],
    )
    identity_mod.post_signed_comment(pr_number=1, body="Reply", agent_id="AID")
    assert len(posted) == 1  # Only original signature reply, no backup
