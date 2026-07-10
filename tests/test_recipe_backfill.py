"""Spec-0064/T4: recipes.backfill path 驱动追溯单测——假 backend + 假代码路径 + 打桩 github/worktree。

证明：backfill 复用 stages.rfc（backfill mode）而非重复实现；validate 门控（delivered=false → 不开
PR、抛 BackfillError）；delivered=true → 开 draft PR。不触发 vigil 发现段。全程不触真实仓库/网络。
"""

from __future__ import annotations

import json

import pytest

from openagents.backends.base import AgentResult
from openagents.recipes import backfill
from openagents.recipes.backfill import BackfillError


class _DrafterBackend:
    def __init__(self, *, delivered, head="AFTER"):
        self._delivered = delivered
        self._head = head
        self.tasks: list[str] = []

    def run(self, *, work_dir, task, context):
        self.tasks.append(task)
        return AgentResult(
            changed=True,
            summary=json.dumps(
                {"delivered": self._delivered, "head_sha": self._head, "summary": "反推"}
            ),
        )


class _PR:
    number = 200


def _patch(monkeypatch, *, head_seq):
    # worktree 走假实现（不建真 git）；head_sha 按序返回区分交付前/后。
    monkeypatch.setattr(backfill, "prepare_worktree", lambda *, work_dir, slug, branch, base: "/wt")
    seq = list(head_seq)
    box = {"last": seq[-1] if seq else ""}

    def _head(*, work_dir):
        if seq:
            box["last"] = seq.pop(0)
        return box["last"]

    monkeypatch.setattr(backfill.stages.gates.git, "head_sha", _head)


def test_delivered_opens_draft_pr(monkeypatch):
    _patch(monkeypatch, head_seq=["BEFORE", "AFTER"])
    created = {}
    monkeypatch.setattr(
        backfill.github,
        "create_pr",
        lambda **kw: created.update(kw) or _PR(),
    )
    backend = _DrafterBackend(delivered=True, head="AFTER")
    result = backfill.backfill_rfc(path="openagents/utils/foo.py", backend=backend, work_dir=".")
    assert result["pr_number"] == 200
    assert result["reason"] == "backfilled"
    assert created["draft"] is True
    # 复用 stages.rfc：drafter 被派、backfill mode。
    assert "起草 agent" in backend.tasks[0]
    assert "mode=backfill" in backend.tasks[0]


def test_not_delivered_does_not_open_pr(monkeypatch):
    _patch(monkeypatch, head_seq=["SAME", "SAME"])

    def _no_pr(**kw):
        raise AssertionError("未过 validate 不应开 PR")

    monkeypatch.setattr(backfill.github, "create_pr", _no_pr)
    backend = _DrafterBackend(delivered=False, head="")
    with pytest.raises(BackfillError):
        backfill.backfill_rfc(path="x/y.py", backend=backend, work_dir=".")


def test_slug_for_path():
    assert backfill._slug_for(path="openagents/utils/foo.py") == "openagents-utils-foo-py"
    assert backfill._slug_for(path="/") == "root"
