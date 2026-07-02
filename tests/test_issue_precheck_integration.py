"""Spec-0043/T4：issue precheck 端到端集成回归（离线确定性，全程 mock）。

以 **issue #106 的真实标题/正文**为一等回归样例，用真实 Orchestrator + 真实 Vigil（只桩住
github IO 与 backend），一轮 discover_and_dispatch 断言「冲突识别 + 冻结」，二轮断言「反震荡
（needs-human 在场 → 不重判、无新评论）」，另一自洽 issue 断言放行（零回归），摘标签断言解冻。

这是本 spec 的自指铁证：判读用非确定 LLM，若每轮重跑就会自造 issue 级复审震荡；needs-human
标签把结论钉死，同一 issue 只判一次——正是把 issue #106/Spec-0041「同码只判一次」内建进这道闸。
"""

from openagents import github, identity, vigil
from openagents.backends.base import AgentResult
from openagents.orchestrator import Orchestrator
from openagents.state import State
from openagents.vigil import Vigil

# issue #106 真实标题/正文（逐字回归样例）。
_106_TITLE = "已 PASS 的 PR 被反复重审：评审结论应按 commit sha 缓存，避免同码 PASS/REWORK 震荡"
_106_BODY = "hold-merge 后已 PASS 的 PR 仍被反复重审，应冻结成 needs-human，避免继续重跑 reviewer"

_CONFLICT_SUMMARY = (
    "冲突：是\n"
    "冲突点：标题主张按 commit sha 缓存评审结论；正文主张 hold-merge 后把已 PASS 的 PR 冻结成 needs-human。\n"
    "候选修法：按 commit sha 缓存评审结论\n"
    "候选修法：hold-merge 冻结 PR\n"
)


class _FakeWorld:
    """内存 GitHub 世界：issues（含可变标签集）+ issue 评论。"""

    def __init__(self):
        self.issues: dict[int, dict] = {}
        self.comments: list[tuple[int, str]] = []

    def add_issue(self, *, number, title, body, labels):
        self.issues[number] = {"title": title, "body": body, "labels": set(labels)}

    def _issue(self, number):
        data = self.issues[number]
        return github.Issue(
            number=number,
            title=data["title"],
            body=data["body"],
            labels=tuple(sorted(data["labels"])),
        )

    def list_issues(self, *, labels, state="open"):
        return [self._issue(n) for n in sorted(self.issues)]

    def get_issue(self, *, number):
        return self._issue(number)

    def issue_comment(self, *, number, body):
        self.comments.append((number, body))

    def issue_add_label(self, *, number, name):
        self.issues[number]["labels"].add(name)


class _JudgeBackend:
    """按 context 里的 issue 内容判读：#106 样本 → 冲突；其余 → 冲突：否。记录调用次数。"""

    name = "judge"

    def __init__(self):
        self.calls = 0

    def run(self, *, work_dir, task, context):
        self.calls += 1
        summary = _CONFLICT_SUMMARY if "commit sha 缓存" in context else "冲突：否"
        return AgentResult(changed=False, summary=summary)


def _wire(monkeypatch, world):
    monkeypatch.setattr(github, "list_issues", world.list_issues)
    monkeypatch.setattr(github, "get_issue", world.get_issue)
    monkeypatch.setattr(github, "issue_comment", world.issue_comment)
    monkeypatch.setattr(github, "issue_add_label", world.issue_add_label)
    # vigil 远端分支探测走 git ls-remote 子进程 → 一律判「无远端分支」（走 fresh 判定）。
    monkeypatch.setattr(Vigil, "_remote_branch_exists", lambda self, *, branch: False)


def _make(tmp_path, monkeypatch, world):
    _wire(monkeypatch, world)
    backend = _JudgeBackend()
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = Orchestrator(backend=backend, state=state, work_dir=tmp_path, agent_id="agent-e2e-0043")
    # start_rfc 打桩成 spy——本组只验证 precheck 的「拦 / 放」控制流，不真实起草。
    started: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        orch,
        "start_rfc",
        lambda *, issue_number, base, resume=False: started.append((issue_number, resume)),
    )
    v = Vigil(orchestrator=orch, messages=object(), state=state, work_dir=tmp_path)
    return v, orch, backend, state, started


def test_106_conflict_is_detected_and_frozen(tmp_path, monkeypatch):
    world = _FakeWorld()
    world.add_issue(number=106, title=_106_TITLE, body=_106_BODY, labels={"openagents"})
    v, orch, backend, state, started = _make(tmp_path, monkeypatch, world)

    dispatched = v.discover_and_dispatch(labels=["openagents"], base="main")

    # (a) start_rfc 未被调 → 无 worktree / begin_run / 新 spec 组。
    assert started == []
    assert dispatched == []
    assert state.find_by_issue(issue_number=106) is None
    # (b) issue 被打上 needs-human。
    assert github.BLOCKED_LABEL in world.issues[106]["labels"]
    # (c) 恰一条署名对齐评论，含两个修法方向 + 候选修法段，不含 PR 失败文案。
    assert len(world.comments) == 1
    number, body = world.comments[0]
    assert number == 106
    assert "按 commit sha 缓存评审结论" in body and "hold-merge 冻结 PR" in body
    assert "候选修法" in body
    assert identity.parse_agent_id(body=body) == "agent-e2e-0043"
    assert "卡住了" not in body and "🤖" not in body


def test_second_round_does_not_re_judge_frozen_issue(tmp_path, monkeypatch):
    # 反震荡铁证：首轮冻结后带上 needs-human，二轮不重判、不再贴评论。
    world = _FakeWorld()
    world.add_issue(number=106, title=_106_TITLE, body=_106_BODY, labels={"openagents"})
    v, orch, backend, state, started = _make(tmp_path, monkeypatch, world)

    v.discover_and_dispatch(labels=["openagents"], base="main")
    assert backend.calls == 1  # 首轮判读一次
    assert len(world.comments) == 1

    # 第二轮：needs-human 在场 → _dispatch_kind 返回 None、判读不再被调、无新评论、start_rfc 仍不调。
    v.discover_and_dispatch(labels=["openagents"], base="main")
    assert backend.calls == 1, "反震荡：判读 backend 不得再被调用"
    assert len(world.comments) == 1, "二轮不得再贴评论"
    assert started == []


def test_self_consistent_issue_dispatches_and_unfreeze_re_judges(tmp_path, monkeypatch):
    world = _FakeWorld()
    world.add_issue(number=200, title="加一个登录页", body="仅邮箱密码登录", labels={"openagents"})
    v, orch, backend, state, started = _make(tmp_path, monkeypatch, world)

    # 放行断言（不吹毛求疵）：自洽 issue 正常派单、无 needs-human、无对齐评论。
    v.discover_and_dispatch(labels=["openagents"], base="main")
    assert started == [(200, False)]
    assert github.BLOCKED_LABEL not in world.issues[200]["labels"]
    assert world.comments == []

    # 解冻断言：给它人为打上 needs-human（模拟曾冻结）→ 下一轮 _dispatch_kind 跳过、判读不调。
    world.issues[200]["labels"].add(github.BLOCKED_LABEL)
    calls_before = backend.calls
    started.clear()
    v.discover_and_dispatch(labels=["openagents"], base="main")
    assert started == [] and backend.calls == calls_before  # 冻结 → 不重判、不派单

    # 摘掉 needs-human → 重新成 fresh → 判读被重新调用、放行派单（人触发的一次重判，有界）。
    world.issues[200]["labels"].discard(github.BLOCKED_LABEL)
    v.discover_and_dispatch(labels=["openagents"], base="main")
    assert backend.calls == calls_before + 1
    assert started == [(200, False)]


def test_precheck_is_wired_into_discovery(tmp_path, monkeypatch):
    # 结构断言：vigil 发现段确实调了 precheck_issue（源码层面防回归接线被删）。
    # 「precheck 在 start_rfc 之前拦下」的时序由上面的行为用例证明（冲突时 start_rfc 不被调）。
    import inspect

    source = inspect.getsource(vigil.Vigil.discover_and_dispatch)
    assert "self._orchestrator.precheck_issue(" in source
