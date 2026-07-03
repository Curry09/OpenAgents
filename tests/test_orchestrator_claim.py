"""Spec-0049/T4：orchestrator 认领（署名便签 + read-after-write 退让）与 state 清 run 原语单测。

github.* 与 git 子进程（Workspace）一律 mock/注入；聚焦：
- fresh 认领 = 幂等 add 标签 + 贴署名认领便签 + read-after-write 二次确认；PR 开出后摘标签；
- **零 unlabeled 互撕**：认领全程不产生 remove 事件（唯一 remove 是 PR 开出后的 _release_claim）；
- 被他方更晚认领 → 抛 ClaimLost，start_rfc 退让、清本地 solving 记录、上抛；
- resume **不再认领**（零认领事件）；
- state.clear_run 幂等。
不真实联网。既有 start_rfc 主流程回归由 test_orchestrator.py 覆盖。
"""

import subprocess
from collections import defaultdict

import pytest

from openagents import identity
from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Comment, GithubError, Issue
from openagents.orchestrator import ClaimLost
from openagents.state import STATUS_SOLVING, State

SELF_ID = "agent-x"


class _FakeBackend:
    name = "fake"

    def __init__(self, *, events):
        self._events = events
        self._result = AgentResult(changed=True, summary="done")

    def run(self, *, work_dir, task, context):
        self._events.append("backend.run")
        return self._result


class _GitRecorder:
    def __call__(self, args, **kwargs):
        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Proc()


class FakeGh:
    """内存版 issue 标签 + 评论账本 + 事件记录（对应 github.* 的认领相关子集）。

    on_after_note 钩子在「本后端刚贴完自己的认领便签」后触发，用于把**他方更晚认领**塞进读—写
    之间的窗口（复现 read-after-write 二次确认捕获竞态）。created_at 用单调递增逻辑时钟保证严格有序。
    """

    def __init__(self):
        self.labels: dict[int, set[str]] = defaultdict(set)
        self.comments: dict[int, list[Comment]] = defaultdict(list)
        self.events: list[tuple] = []
        self._clock = 0
        self.on_after_note = None

    def _ts(self) -> str:
        self._clock += 1
        return f"2026-07-03T00:00:{self._clock:02d}Z"

    def issue_add_label(self, *, number, name):
        self.events.append(("add", number, name))
        self.labels[number].add(name)

    def issue_remove_label(self, *, number, name):
        self.events.append(("remove", number, name))
        self.labels[number].discard(name)

    def issue_comment(self, *, number, body):
        self.events.append(("comment", number))
        self.comments[number].append(
            Comment(id=f"IC{self._clock}", author="", body=body, created_at=self._ts())
        )
        if self.on_after_note is not None:
            self.on_after_note(self, number)

    def list_issue_comments(self, *, number):
        return list(self.comments[number])

    def post_competitor(self, *, number, agent_id):
        """他方（agent_id）贴一条更晚的认领便签（created_at 更大）。"""
        self.comments[number].append(
            Comment(
                id=f"C{self._clock}",
                author=agent_id,
                body=identity.build_claim_note(agent_id=agent_id),
                created_at=self._ts(),
            )
        )


def _make(tmp_path, *, events):
    backend = _FakeBackend(events=events)
    state = State(path=tmp_path / ".openagents" / "state.json")
    orch = orch_module.Orchestrator(
        backend=backend, state=state, work_dir=tmp_path, agent_id=SELF_ID
    )
    return orch, state


def _wire(monkeypatch, gh):
    monkeypatch.setattr(subprocess, "run", _GitRecorder())
    monkeypatch.setattr(
        orch_module.github, "get_issue", lambda *, number: Issue(number=number, title="t", body="b")
    )
    monkeypatch.setattr(
        orch_module.github,
        "create_pr",
        lambda *, branch, title, body, base, draft: PR(number=5, url="u/pull/5"),
    )
    monkeypatch.setattr(orch_module.github, "issue_add_label", gh.issue_add_label)
    monkeypatch.setattr(orch_module.github, "issue_remove_label", gh.issue_remove_label)
    monkeypatch.setattr(orch_module.github, "issue_comment", gh.issue_comment)
    monkeypatch.setattr(orch_module.github, "list_issue_comments", gh.list_issue_comments)


# --------------------------------------------------------------------------- #
# 单赢家：幂等 add + 署名便签 + read-after-write 通过 → 正常开 PR、零 unlabeled 互撕
# --------------------------------------------------------------------------- #


def test_fresh_claim_stamps_note_and_opens_pr(tmp_path, monkeypatch):
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)
    gh = FakeGh()
    _wire(monkeypatch, gh)

    pr = orch.start_rfc(issue_number=3, resume=False)

    assert pr.number == 5
    # 认领全程：一次 add（幂等标签）+ 一条署名认领便签；PR 开出后一次 remove（_release_claim）。
    add_events = [e for e in gh.events if e[0] == "add"]
    remove_events = [e for e in gh.events if e[0] == "remove"]
    comment_events = [e for e in gh.events if e[0] == "comment"]
    assert len(add_events) == 1
    assert len(comment_events) == 1
    # **认领阶段零 unlabeled**：唯一的 remove 发生在 backend.run（起草）之后（即 PR 开出后清理）。
    assert len(remove_events) == 1
    add_idx = gh.events.index(add_events[0])
    remove_idx = gh.events.index(remove_events[0])
    assert add_idx < gh.events.index(comment_events[0]) < remove_idx
    # 认领便签是本实例署名的。
    note = gh.comments[3][0]
    assert identity.parse_agent_id(body=note.body) == SELF_ID
    assert "openagents:claim" in note.body
    # 状态一次写成 rfc-review。
    assert state.all_runs()[0].status == "rfc-review"


# --------------------------------------------------------------------------- #
# 输家：被他方更晚认领 → ClaimLost 退让、清本地 solving、不开 PR
# --------------------------------------------------------------------------- #


def test_loser_raises_claim_lost_and_clears_local_run(tmp_path, monkeypatch):
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)
    gh = FakeGh()
    # 本后端贴完自己的便签后，他方（agent-winner）更晚贴一条 → read-after-write 检出。
    gh.on_after_note = lambda world, number: world.post_competitor(
        number=number, agent_id="agent-winner"
    )
    _wire(monkeypatch, gh)

    with pytest.raises(ClaimLost):
        orch.start_rfc(issue_number=3, resume=False)

    # 退让：本地 solving/pr=0 记录被清空（下轮回到「看见他方认领 → 跳过」，而非 resume 续跑）。
    assert state.all_runs() == []
    # 起草未发生（认领先于起草，退让即中止本轮），也没开 PR。
    assert "backend.run" not in events
    # 全程零 unlabeled 互撕：本后端从不 remove 别人的标签（唯一动作是 add + 贴自己便签）。
    assert not any(e[0] == "remove" for e in gh.events)


def test_winner_holds_when_own_note_is_latest(tmp_path, monkeypatch):
    # read-after-write：最近便签是自己的（他方更早）→ 认领成立，不抛。
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)
    gh = FakeGh()
    # 预置一条他方**更早**的便签，再由本后端贴出更晚的自己便签 → 最新是自己 → 不退让。
    gh.post_competitor(number=3, agent_id="agent-early")
    _wire(monkeypatch, gh)

    pr = orch.start_rfc(issue_number=3, resume=False)

    assert pr.number == 5
    assert state.all_runs()[0].status == "rfc-review"


# --------------------------------------------------------------------------- #
# resume 免认领：零认领事件
# --------------------------------------------------------------------------- #


def test_resume_does_not_claim(tmp_path, monkeypatch):
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)
    gh = FakeGh()
    _wire(monkeypatch, gh)
    # 前置：已有 solving/pr=0 的孤儿 run。
    state.begin_run(issue_number=3, branch="openagents/issue-3")

    orch.start_rfc(issue_number=3, resume=True)

    # resume 全程不打标、不贴便签、不 read-after-write（唯一 remove 是 PR 开出后的 _release_claim）。
    assert not any(e[0] == "add" for e in gh.events)
    assert not any(e[0] == "comment" for e in gh.events)
    assert gh.comments[3] == []


# --------------------------------------------------------------------------- #
# 失败传播：add 失败上抛（不吞噬隔离语义）
# --------------------------------------------------------------------------- #


def test_add_label_failure_propagates_as_github_error(tmp_path, monkeypatch):
    events: list[str] = []
    orch, state = _make(tmp_path, events=events)
    gh = FakeGh()
    _wire(monkeypatch, gh)

    def _boom(*, number, name):
        raise GithubError("HTTP 401 must authenticate")

    monkeypatch.setattr(orch_module.github, "issue_add_label", _boom)

    with pytest.raises(GithubError):
        orch.start_rfc(issue_number=3, resume=False)
    assert "backend.run" not in events


# --------------------------------------------------------------------------- #
# state.clear_run 幂等
# --------------------------------------------------------------------------- #


def test_clear_run_removes_record_and_is_idempotent(tmp_path):
    state = State(path=tmp_path / ".openagents" / "state.json")
    state.begin_run(issue_number=7, branch="openagents/issue-7")
    assert state.find_by_issue(issue_number=7) is not None
    assert state.find_by_issue(issue_number=7).status == STATUS_SOLVING

    state.clear_run(issue_number=7)
    assert state.find_by_issue(issue_number=7) is None
    # 幂等：再清一次不报错、仍为空。
    state.clear_run(issue_number=7)
    assert state.find_by_issue(issue_number=7) is None


def test_clear_run_preserves_other_runs(tmp_path):
    state = State(path=tmp_path / ".openagents" / "state.json")
    state.begin_run(issue_number=7, branch="openagents/issue-7")
    state.begin_run(issue_number=8, branch="openagents/issue-8")

    state.clear_run(issue_number=7)

    assert state.find_by_issue(issue_number=7) is None
    assert state.find_by_issue(issue_number=8) is not None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
