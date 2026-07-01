"""Spec-0034/T3：Messages 的 merge 闸诊断接线单元测试。

覆盖 _make_diagnoser 门控（work_dir+base 齐备才构造、缺一返 None）、_conflict_blocker 取舍（有诊断器
带诊断 / 无诊断器退回 CONFLICT_COMMENT）、merge 闸 _block 的「卡在哪」段携带诊断、合并 reconcile
拉式同步后不再扇出。github / conflictdiag / rebase 全部 monkeypatch，hermetic（不触真实 git/gh/LLM）。
"""

from openagents import messages as messages_module
from openagents.messages import Messages
from openagents.state import STATUS_DONE, STATUS_PR_OPEN, RunRecord

_AGENT_ID = "agent-self"

# 一段「带诊断」的 blocker 正文样例（冲突文件清单 + 关键 hunk 摘要），供断言诊断确已进入评论。
_DIAG_BODY = (
    "自动合并目标分支 origin/main 时以下文件存在无法自动解决的冲突，需人工裁断——\n"
    "冲突文件清单（1）\n- docs/specs/OVERVIEW.md"
)


class _FakeOrchestrator:
    def review_code(self, *, pr_number):  # pragma: no cover - 冲突预检阶段不应触达
        raise AssertionError("真冲突预检阶段不应调 review_code")


class _FakeState:
    def __init__(self, *, runs):
        self._runs = list(runs)

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        for record in self._runs:
            if record.issue_number == issue_number:
                record.status = status

    def reset_rounds(self, *, issue_number):  # pragma: no cover - 本文件用例不触达
        pass

    def set_block_gate(self, *, issue_number, gate):
        for record in self._runs:
            if record.issue_number == issue_number:
                record.block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        for record in self._runs:
            if record.issue_number == issue_number:
                record.block_watermark = watermark


def _run(*, issue_number=3, pr_number=5, status=STATUS_PR_OPEN):
    return RunRecord(
        issue_number=issue_number,
        branch=f"openagents/issue-{issue_number}",
        pr_number=pr_number,
        pr_url=f"u/pull/{pr_number}",
        status=status,
        summary="",
        rounds=0,
        review_invalid=0,
    )


def _messages(*, runs, work_dir="/repo", base="main", backend=None):
    return Messages(
        orchestrator=_FakeOrchestrator(),
        state=_FakeState(runs=runs),
        agent_id=_AGENT_ID,
        work_dir=work_dir,
        base=base,
        backend=backend,
    )


# --------------------------------------------------------------------------- #
# _make_diagnoser 门控
# --------------------------------------------------------------------------- #


def test_make_diagnoser_none_without_work_dir():
    msgs = _messages(runs=[_run()], work_dir=None)
    assert msgs._make_diagnoser() is None


def test_make_diagnoser_none_without_base():
    msgs = _messages(runs=[_run()], base=None)
    assert msgs._make_diagnoser() is None


def test_make_diagnoser_built_when_all_present(monkeypatch):
    captured = {}

    def _fake_make(*, work_dir, base):
        captured.update(work_dir=work_dir, base=base)
        return lambda *, pr_number: _DIAG_BODY

    monkeypatch.setattr(messages_module.conflictdiag, "make_diagnoser", _fake_make)
    msgs = _messages(runs=[_run()], work_dir="/repo", base="main")

    diagnose = msgs._make_diagnoser()
    assert diagnose is not None
    assert captured == {"work_dir": "/repo", "base": "main"}


# --------------------------------------------------------------------------- #
# _conflict_blocker 取舍
# --------------------------------------------------------------------------- #


def test_conflict_blocker_uses_diagnosis_when_available(monkeypatch):
    monkeypatch.setattr(
        messages_module.conflictdiag,
        "make_diagnoser",
        lambda *, work_dir, base: lambda *, pr_number: _DIAG_BODY,
    )
    msgs = _messages(runs=[_run()])

    assert msgs._conflict_blocker(pr_number=5) == _DIAG_BODY


def test_conflict_blocker_falls_back_without_diagnoser():
    # work_dir=None → 无诊断器 → 退回静态 CONFLICT_COMMENT。
    msgs = _messages(runs=[_run()], work_dir=None)
    assert msgs._conflict_blocker(pr_number=5) == messages_module.conflictdiag.CONFLICT_COMMENT


# --------------------------------------------------------------------------- #
# merge 闸 _block 携带诊断（首次发现冲突、无 backend）
# --------------------------------------------------------------------------- #


def _patch_conflict_precheck(monkeypatch, *, comments):
    """让 poll 走到 coding 真冲突预检：未合并/未关闭、mergeability=DIRTY/CONFLICTING。"""
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: False)
    monkeypatch.setattr(messages_module.github, "is_closed", lambda *, pr_number: False)

    class _MS:
        merge_state_status = "DIRTY"
        mergeable = "CONFLICTING"

    monkeypatch.setattr(messages_module.github, "mergeability", lambda *, pr_number: _MS())
    monkeypatch.setattr(messages_module.github, "add_label", lambda *, pr_number, name: None)
    monkeypatch.setattr(messages_module.github, "list_comments", lambda *, pr_number: [])
    monkeypatch.setattr(
        messages_module.identity,
        "post_signed_comment",
        lambda *, pr_number, body, agent_id: comments.append(
            {"pr_number": pr_number, "body": body}
        ),
    )


def test_first_conflict_block_comment_carries_diagnosis(monkeypatch):
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    monkeypatch.setattr(
        messages_module.conflictdiag,
        "make_diagnoser",
        lambda *, work_dir, base: lambda *, pr_number: _DIAG_BODY,
    )
    # 无 backend → resolve 恒 None → 首次冲突直接 _block（merge 闸），blocker 取诊断。
    msgs = _messages(runs=[_run(pr_number=5)], backend=None)

    events = msgs.poll()

    assert any(e["reason"] == "unmergeable" for e in events)
    assert len(comments) == 1
    assert "冲突文件清单" in comments[0]["body"]
    assert "docs/specs/OVERVIEW.md" in comments[0]["body"]


def test_block_comment_falls_back_to_static_without_diagnoser(monkeypatch):
    comments: list[dict] = []
    _patch_conflict_precheck(monkeypatch, comments=comments)
    # work_dir=None → 无诊断器 → blocker 退回静态 CONFLICT_COMMENT。
    msgs = _messages(runs=[_run(pr_number=5)], work_dir=None, backend=None)

    msgs.poll()

    assert len(comments) == 1
    assert messages_module.conflictdiag.CONFLICT_COMMENT in comments[0]["body"]


# --------------------------------------------------------------------------- #
# 合并 reconcile：拉式同步后不再扇出
# --------------------------------------------------------------------------- #


def test_merged_reconcile_no_fanout(monkeypatch):
    # 拉式同步取代 push 扇出：is_merged（人手动合并）只 reconcile——置 done + 关 issue，**不再扇出**
    # （rebase 模块已删，无从扇出）。其余 open PR 各自轮到时在 _process_coding 的 BEHIND 分支跟上。
    monkeypatch.setattr(messages_module.github, "is_merged", lambda *, pr_number: True)
    closed: list[int] = []
    monkeypatch.setattr(
        messages_module.github, "close_issue", lambda *, number: closed.append(number)
    )
    msgs = _messages(runs=[_run(issue_number=3, pr_number=5)])

    events = msgs.poll()

    assert any(e["reason"] == "merged" for e in events)
    assert closed == [3]
    assert msgs._state.all_runs()[0].status == STATUS_DONE
    # 守护：merged 事件不再带扇出结果 synced（拉式同步后无 push 扇出）。
    merged_event = next(e for e in events if e["reason"] == "merged")
    assert "synced" not in merged_event
