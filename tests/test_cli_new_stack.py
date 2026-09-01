"""Spec-0064/T5: CLI 收敛为四命令 + 隐藏 reply-comment + YAML/flag 覆盖 + 签名硬化契约测试。

薄路由验证（打桩 recipe/工厂，不真跑守夜、不触真实 gh/后端）：
  - 人面向仅 vigil/issue/backfill-rfc/release 在册；旧九命令（rfc/refine-rfc/implement/iterate/
    solve/poll/watch/vigil-all/fleet）不再注册；reply-comment 仍可解析（隐藏，help=SUPPRESS）。
  - _effective_config：YAML 单一真源 + --skip 单次覆盖并存；非法旁路与零闸报错。
  - backfill-rfc 转发 recipes.backfill；reply-comment 转发 identity.post_signed_comment。
  - post_signed_comment 同步后校验漏签 → 补签（非只 warn）。
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
# 解析：四命令在册 + 旧九命令下线 + reply-comment 隐藏
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
# _effective_config：YAML 单一真源 + flag 单次覆盖
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
    with pytest.raises(ValueError, match="不许零闸"):
        _effective_config(ctx=ctx, args=_vigil_args(skip="review"))


# --------------------------------------------------------------------------- #
# 转发：backfill-rfc / reply-comment
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
# 签名硬化：同步后校验漏签 → 补签（非只 warn）
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
            Comment(id="1", author="a", body="裸回复无签名", created_at="2026-01-01")
        ],
    )
    identity_mod.post_signed_comment(pr_number=1, body="回复", agent_id="AID")
    assert len(posted) == 2  # 签名回复 + 补签（非只 warn）
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
                body="回复\n\n<!-- openagents:agent=AID -->",
                created_at="2026-01-01",
            )
        ],
    )
    identity_mod.post_signed_comment(pr_number=1, body="回复", agent_id="AID")
    assert len(posted) == 1  # 只有原始签名回复，无补签
