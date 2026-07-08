"""Spec-0049/T5：多后端竞态复现集成测试（离线、确定性、可重复）。

不触网、不调真实 gh/LLM/git：用一个内存版 GitHub 世界（issue 标签集合 + 评论账本 + 事件记录）
驱动**两个真实** Orchestrator + State 实例（两个 agent_id）对**同一** issue 竞态，断言：
  1. 二者几乎同时 fresh 起草 → 恰好**一个**成功开 draft PR，另一个抛 ClaimLost 退让并清空本地 solving；
  2. 全程**零 unlabeled 互撕事件**（认领竞争期无人 remove 标签；唯一 remove 是赢家开 PR 后的
     _release_claim）；便签评论**只增不删**；
  3. 双 solving 下 resume → **零新认领事件**（不打标、不贴便签）；
  4. 僵尸认领（便签龄 > CLAIM_EXPIRY_SECONDS）能被他方回收重认领，未过期则跳过。

浏览器 e2e 不适用：本 feature 无产品前端界面（后端并发时序问题），成果测试取确定性并发复现。
"""

from pathlib import Path

import pytest

from openagents import github, identity
from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import DISPATCH_LABEL, PR, Comment, Issue
from openagents.orchestrator import ClaimLost, Orchestrator
from openagents.state import State
from openagents.vigil import Vigil

_BRANCH_PREFIX = "openagents/issue-"


class FakeGitHubWorld:
    """内存版跨后端共享事实源：issue 标签集合 + 评论账本 + labeled/unlabeled/comment 事件记录。

    两后端各自的本地 State 互不可见，唯一共享的就是这个世界（对应真实里的 GitHub）。评论 created_at
    用单调递增逻辑时钟保证严格有序（末位 created_at 唯一 → 恰一个赢家）；标签 add 幂等（已在不重复
    记 labeled 事件，镜像 gh 侧 no-op），故「零 unlabeled 事件」可精确断言。on_after_note 一次性钩子
    把「他方更晚认领」塞进本后端读—写之间的窗口，复现 read-after-write 二次确认捕获竞态。
    """

    def __init__(self, *, issues):
        self._issues = list(issues)  # [(number, title, body)]
        self.issue_labels: dict[int, set[str]] = {n: {"openagents"} for n, _, _ in issues}
        self.comments: dict[int, list[Comment]] = {n: [] for n, _, _ in issues}
        self.branches: set[str] = set()
        self.events: list[tuple] = []  # ("labeled"/"unlabeled"/"comment", number, ...)
        self._clock = 0
        self.on_after_note = None

    def _ts(self) -> str:
        self._clock += 1
        return f"2026-07-03T00:00:{self._clock:02d}Z"

    # --- 对应 github.* 的内存实现（测试里 monkeypatch 上去）--------------------- #
    def list_issues(self, *, labels, state="open"):
        return [
            Issue(number=n, title=t, body=b, labels=tuple(sorted(self.issue_labels.get(n, set()))))
            for n, t, b in self._issues
        ]

    def get_issue(self, *, number):
        for n, t, b in self._issues:
            if n == number:
                return Issue(number=n, title=t, body=b, labels=tuple(sorted(self.issue_labels[n])))
        raise github.GithubError(f"no such issue #{number}")

    def issue_add_label(self, *, number, name):
        # 幂等 add：已在则不记新 labeled 事件（镜像 gh no-op），根除「重复打标产生事件」。
        if name not in self.issue_labels.setdefault(number, set()):
            self.issue_labels[number].add(name)
            self.events.append(("labeled", number, name))

    def issue_remove_label(self, *, number, name):
        if name in self.issue_labels.setdefault(number, set()):
            self.issue_labels[number].discard(name)
            self.events.append(("unlabeled", number, name))

    def issue_comment(self, *, number, body):
        self.events.append(("comment", number))
        self.comments.setdefault(number, []).append(
            Comment(id=f"IC{self._clock}", author="", body=body, created_at=self._ts())
        )
        hook = self.on_after_note
        self.on_after_note = None  # 一次性，避免他方 start_rfc 里再贴便签时重入递归
        if hook is not None:
            hook(self, number)

    def list_issue_comments(self, *, number):
        return list(self.comments.get(number, []))

    def create_pr(self, *, branch, title, body, base, draft):
        self.branches.add(branch)
        num = int(branch.rsplit("-", 1)[1])
        self.events.append(("pr", num))
        return PR(number=num, url=f"u/pull/{num}")

    def preset_claim_note(self, *, number, agent_id, created_at):
        """预置一条他方认领便签（用于僵尸回收子用例，created_at 可控年龄）。"""
        self.comments.setdefault(number, []).append(
            Comment(
                id="preset",
                author=agent_id,
                body=identity.build_claim_note(agent_id=agent_id),
                created_at=created_at,
            )
        )

    def branch_exists(self, *, branch):
        return branch in self.branches


class _FakeBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=True, summary="done")


class _FakeWorkspace:
    """无 git 的 Workspace 替身：prepare/ensure 返回一个路径，commit/changed_spec_group 是 no-op。"""

    def __init__(self, *, root):
        self._root = Path(root)

    def prepare(self, *, issue_number, branch, base):
        return self._root / f"issue-{issue_number}"

    def ensure(self, *, issue_number, branch):
        return self._root / f"issue-{issue_number}"

    def assert_delivered(self, *, worktree, branch):
        # Spec-0056/T2：交付下放 agent 后，交付点改调 head 前移硬闸；替身 no-op = 已交付放行。
        # （Spec-0056/T4：commit_and_push 已随交付下放删除，替身不再实现它。）
        pass

    def changed_spec_group(self, *, worktree, base):
        return None


def _orchestrator(*, world, state, agent_id, tmp_path):
    orch = Orchestrator(backend=_FakeBackend(), state=state, work_dir=tmp_path, agent_id=agent_id)
    orch._workspace = _FakeWorkspace(root=tmp_path)
    return orch


def _wire_world(monkeypatch, world):
    monkeypatch.setattr(github, "list_issues", world.list_issues)
    monkeypatch.setattr(orch_module.github, "get_issue", world.get_issue)
    monkeypatch.setattr(orch_module.github, "create_pr", world.create_pr)
    for name in ("issue_add_label", "issue_remove_label", "issue_comment", "list_issue_comments"):
        monkeypatch.setattr(github, name, getattr(world, name))
    monkeypatch.setattr(
        Vigil, "_remote_branch_exists", lambda self, *, branch: world.branch_exists(branch=branch)
    )


def _memory_state(monkeypatch, tmp_path, name):
    state = State(path=tmp_path / name)
    store = {"runs": [], "cursors": {}}
    monkeypatch.setattr(state, "_load", lambda: store)
    monkeypatch.setattr(state, "_save", lambda *, data: store.update(data))
    return state


# --------------------------------------------------------------------------- #
# 主竞态：两后端同时 fresh 起草 → 恰一个赢、另一个 ClaimLost 退让清本地
# --------------------------------------------------------------------------- #


def test_two_backends_race_single_winner_and_loser_retreats(tmp_path, monkeypatch):
    world = FakeGitHubWorld(issues=[(42, "并发去重", "body")])
    _wire_world(monkeypatch, world)

    state_a = _memory_state(monkeypatch, tmp_path, "a.json")  # A：先起手、后读 → 输家
    state_b = _memory_state(monkeypatch, tmp_path, "b.json")  # B：在 A 读—写窗口里更晚认领 → 赢家
    orch_a = _orchestrator(world=world, state=state_a, agent_id="agent-A", tmp_path=tmp_path)
    orch_b = _orchestrator(world=world, state=state_b, agent_id="agent-B", tmp_path=tmp_path)

    b_result = {}

    def b_claims_in_a_window(_world, _number):
        # A 刚贴完自己的便签、尚未 read-after-write 时，B 跑完整条 start_rfc（更晚认领 → 抢先）。
        b_result["pr"] = orch_b.start_rfc(issue_number=42, base="main")

    world.on_after_note = b_claims_in_a_window

    # A 起草：贴便签触发 B 抢认领；A 随后 read-after-write 检出他方更晚认领 → ClaimLost 退让。
    with pytest.raises(ClaimLost):
        orch_a.start_rfc(issue_number=42, base="main")

    # 1. 恰一个赢家：B 开出 draft PR，A 未开。
    assert b_result["pr"].number == 42
    assert world.branches == {"openagents/issue-42"}
    assert [e for e in world.events if e[0] == "pr"] == [("pr", 42)]
    # 2. 输家 A 退让、清空本地 solving；赢家 B 记录 rfc-review。
    assert state_a.all_runs() == []
    assert [r.status for r in state_b.all_runs()] == ["rfc-review"]
    # 3. 零 unlabeled 互撕：认领竞争期无人 remove；唯一 unlabeled 是 B 开 PR 后的 _release_claim。
    unlabeled = [e for e in world.events if e[0] == "unlabeled"]
    assert unlabeled == [("unlabeled", 42, DISPATCH_LABEL)]
    assert world.events.index(("pr", 42)) < world.events.index(unlabeled[0])
    # 便签评论只增不删：两条署名认领便签都在（A 一条、B 一条），无删除事件。
    bodies = [c.body for c in world.comments[42]]
    assert len(bodies) == 2
    owners = sorted(identity.parse_agent_id(body=b) for b in bodies)
    assert owners == ["agent-A", "agent-B"]


# --------------------------------------------------------------------------- #
# resume 免认领：双 solving 下多轮扫描零新认领事件
# --------------------------------------------------------------------------- #


def test_double_solving_resume_produces_zero_new_claim_events(tmp_path, monkeypatch):
    world = FakeGitHubWorld(issues=[(50, "断点续跑", "body")])
    _wire_world(monkeypatch, world)
    state = _memory_state(monkeypatch, tmp_path, "resume.json")
    # 前置：本后端已在 solving/pr=0（孤儿 run），且 issue 上已带认领标签（fresh 首认领时打的）。
    state.begin_run(issue_number=50, branch=f"{_BRANCH_PREFIX}50")
    world.issue_labels[50].add(DISPATCH_LABEL)
    orch = _orchestrator(world=world, state=state, agent_id="agent-A", tmp_path=tmp_path)
    vig = Vigil(
        orchestrator=orch, messages=object(), state=state, work_dir=tmp_path, agent_id="agent-A"
    )

    world.events.clear()  # 只观测「进入 solving 之后」的扫描是否产生新认领事件
    # 第一轮：record 是 solving/pr=0 → resume（不认领），start_rfc(resume) 续跑开 PR、转 rfc-review。
    vig.discover_and_dispatch(labels=["openagents"], base="main")
    # 第二轮：record 已是 rfc-review → _dispatch_kind 返回 None，跳过。
    vig.discover_and_dispatch(labels=["openagents"], base="main")

    # 两轮都**零新认领事件**：既不打标（labeled）、也不贴便签（comment）。
    assert not any(e[0] == "labeled" for e in world.events)
    assert not any(e[0] == "comment" for e in world.events)
    # resume 便签账本没有新增认领便签（仍为空——首认领的便签在 begin_run 之前，这里模拟其未落）。
    assert world.comments[50] == []


# --------------------------------------------------------------------------- #
# 僵尸回收：过期他方认领可回收（fresh），未过期则跳过
# --------------------------------------------------------------------------- #


def test_zombie_claim_recovered_but_fresh_other_claim_skipped(tmp_path, monkeypatch):
    world = FakeGitHubWorld(issues=[(60, "僵尸认领", "body")])
    _wire_world(monkeypatch, world)
    world.issue_labels[60].add(DISPATCH_LABEL)

    # 子用例 A：他方**过期**认领（很久以前的便签）→ 可回收，判 fresh。
    world.preset_claim_note(number=60, agent_id="agent-dead", created_at="2000-01-01T00:00:00Z")
    state_x = _memory_state(monkeypatch, tmp_path, "x.json")
    vig_x = Vigil(
        orchestrator=object(),
        messages=object(),
        state=state_x,
        work_dir=tmp_path,
        agent_id="agent-X",
    )
    issue = world.list_issues(labels=["openagents"])[0]
    assert vig_x._dispatch_kind(issue=issue) == "fresh"

    # 子用例 B：换成他方**未过期**认领（刚贴的便签）→ 他人活认领，跳过。
    world.comments[60] = []
    from datetime import UTC, datetime

    fresh_ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    world.preset_claim_note(number=60, agent_id="agent-live", created_at=fresh_ts)
    issue2 = world.list_issues(labels=["openagents"])[0]
    assert vig_x._dispatch_kind(issue=issue2) is None


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
