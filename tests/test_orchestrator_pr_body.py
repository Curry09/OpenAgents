"""Spec-0028/T1：PR 正文内嵌总览摘要的接线测试。

覆盖 _pr_body / _backfill_pr_body 的 digest_section 插入位置（summary 之后、e2e 之前）、
None 时逐字节回退（零回归），以及 start_rfc 端到端把 digest 拼进 PR 正文。
git / github / backend 全部注入或 monkeypatch，hermetic。
"""

import subprocess

import pytest

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Issue
from openagents.orchestrator import Orchestrator
from openagents.spec import model as spec_model
from openagents.spec.model import Group, Metadata, Overview, Task
from openagents.state import State


class _FakeBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=True, summary="done")


class _GitRecorder:
    def __call__(self, args, **kwargs):
        # Spec-0049/T4：start_rfc fresh 认领会 read-after-write 调 `gh issue view --json comments`；
        # 回一个空评论 JSON，使 latest_claim 返回 None（无他方认领）→ 不抛 ClaimLost（本用例验 PR 正文）。
        class _Proc:
            returncode = 0
            stdout = '{"comments": []}' if "comments" in args else ""
            stderr = ""

        return _Proc()


def _make(tmp_path):
    state = State(path=tmp_path / ".openagents" / "state.json")
    return Orchestrator(backend=_FakeBackend(), state=state, work_dir=tmp_path, agent_id="agent-x")


def test_pr_body_inserts_digest_between_summary_and_e2e(tmp_path):
    orch = _make(tmp_path)
    body = orch._pr_body(
        issue_number=79,
        summary="spec 草稿待评审。",
        digest_section="## spec 总览（摘自 docs/specs/x.md）\n\n### Summary\n摘要。",
        e2e_section="## 端到端验证\n- 跑：`bash scripts/x.sh`",
    )
    assert body.startswith("Closes #79")
    # 顺序：summary < digest < e2e。
    summary_at = body.index("spec 草稿待评审。")
    digest_at = body.index("## spec 总览")
    e2e_at = body.index("## 端到端验证")
    assert summary_at < digest_at < e2e_at


def test_pr_body_byte_identical_when_both_none(tmp_path):
    orch = _make(tmp_path)
    body = orch._pr_body(
        issue_number=79, summary="spec 草稿待评审。", digest_section=None, e2e_section=None
    )
    assert body == "Closes #79\n\nspec 草稿待评审。"


def test_backfill_pr_body_inserts_digest_before_e2e(tmp_path):
    orch = _make(tmp_path)
    body = orch._backfill_pr_body(
        path="openagents/x.py",
        digest_section="## spec 总览（摘自 docs/specs/x.md）",
        e2e_section="## 端到端验证",
    )
    digest_at = body.index("## spec 总览")
    e2e_at = body.index("## 端到端验证")
    assert digest_at < e2e_at
    assert "Closes #" not in body  # path 驱动无关联 issue


def _spec_group_with_overview(*, root):
    group = Group(
        number="0028",
        metadata=Metadata(title="示例", issue=79, slug="pr-digest-and-conflict-agent", summary="t"),
        tasks=[Task(id="T1", title="t", status="pending", priority="P1")],
        overview=Overview(
            summary="源自实跑 PR #76 的两个观察。",
            reference_level="离线跑 `scripts/e2e-spec-0028-pr-digest-and-conflict.sh`。",
        ),
    )
    path = spec_model.group_path(
        specs_root=root, number="0028", slug="pr-digest-and-conflict-agent"
    )
    spec_model.dump_group(group=group, path=path)
    return path


def test_start_rfc_embeds_digest_in_pr_body(tmp_path, monkeypatch):
    orch = _make(tmp_path)
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    monkeypatch.setattr(
        orch_module.github,
        "get_issue",
        lambda *, number: Issue(number=number, title="某 feature", body="正文"),
    )
    group_path = _spec_group_with_overview(root=tmp_path)
    monkeypatch.setattr(orch._workspace, "changed_spec_group", lambda *, worktree, base: group_path)
    captured = {}

    def _create_pr(*, branch, title, body, base, draft):
        captured.update(body=body)
        return PR(number=9, url="u/pull/9")

    monkeypatch.setattr(orch_module.github, "create_pr", _create_pr)

    orch.start_rfc(issue_number=79)

    body = captured["body"]
    assert body.startswith("Closes #79")
    assert "## spec 总览" in body
    assert "源自实跑 PR #76 的两个观察。" in body
    # digest 在 e2e 指路牌之前。
    assert body.index("## spec 总览") < body.index("## 端到端验证")


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
