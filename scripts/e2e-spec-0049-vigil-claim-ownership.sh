#!/usr/bin/env bash
# Spec-0049 端到端测试启动脚本：vigil 多后端派单认领去互撕（resume 免认领 + 认领带归属 + 二次确认退让）。
#
# 本组分两层根治「两后端对同一 issue 反复加/去认领标签互撕数分钟」：
#   ① 止血——resume 路径不再认领（认领只在 fresh 首次派单打一次）；
#   ② 治本——认领 = 幂等 add 固定标签 + 追加一条**署名认领便签**（归属凭证）+ read-after-write 二次
#      确认：贴完自己便签后重读，若被别的 agent 更晚认领即抛 ClaimLost、本后端主动退让（清本地 solving）。
# 结果：同一 issue 任一时刻只被一个后端有效认领，他方识别并退让；只贴自己的便签、幂等 add 标签，
# 绝不无差别撕别人的标签——互撕的物理来源被移除。
#
# **浏览器 e2e 不适用**：本 feature 是后端 GitHub 标签/评论并发时序问题，无任何产品前端界面可驱动
# （无导航/交互/截图可断言的视觉成果）。故成果测试形态为**确定性并发复现**（pytest 集成测试 +
# 本 shell 跑它并打印证据），而非浏览器 e2e。全程**不触网、不调真实 gh/LLM/git 远端**。
#
# 用法：
#   bash scripts/e2e-spec-0049-vigil-claim-ownership.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] 静态检查（ruff lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] 定向单元/集成测试（Spec-0049 T1–T5）"
uv run --extra dev pytest -q \
  tests/test_github_claim_label.py \
  tests/test_identity_claim.py \
  tests/test_vigil_claim.py \
  tests/test_orchestrator_claim.py \
  tests/test_claim_dedup_integration.py

echo
echo "==> [3/4] 成果证据：用**真实** Orchestrator + State 驱动两后端对同一 issue 竞态，打印三条断言证据"
uv run python - <<'PY'
# Spec-0049 成果演练：用**真实**产品代码——Orchestrator.start_rfc（含 _claim_issue 的幂等 add +
# 署名认领便签 + read-after-write 退让）+ State——把两个 agent 对同一 issue 的竞态跑出来，打印证据。
# 脚本只提供内存版 GitHub 世界（标签集合 + 评论账本 + 事件记录）与无 git 的 Workspace 替身（测试侧
# 夹具），认领时序 / 归属判定 / 退让全部来自产品代码。
from pathlib import Path

from openagents import github, identity
from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Comment, Issue
from openagents.orchestrator import ClaimLost, Orchestrator
from openagents.state import State

DISPATCH = github.DISPATCH_LABEL


class World:
    def __init__(self, *, number):
        self.number = number
        self.labels = {number: {"openagents"}}
        self.comments = {number: []}
        self.branches = set()
        self.events = []
        self._clock = 0
        self.on_after_note = None

    def _ts(self):
        self._clock += 1
        return f"2026-07-03T00:00:{self._clock:02d}Z"

    def get_issue(self, *, number):
        return Issue(number=number, title="并发去重", body="b", labels=tuple(self.labels[number]))

    def issue_add_label(self, *, number, name):
        if name not in self.labels.setdefault(number, set()):
            self.labels[number].add(name)
            self.events.append(("labeled", number))

    def issue_remove_label(self, *, number, name):
        if name in self.labels.setdefault(number, set()):
            self.labels[number].discard(name)
            self.events.append(("unlabeled", number))

    def issue_comment(self, *, number, body):
        self.events.append(("comment", number))
        self.comments.setdefault(number, []).append(
            Comment(id="IC", author="", body=body, created_at=self._ts())
        )
        hook, self.on_after_note = self.on_after_note, None
        if hook is not None:
            hook()

    def list_issue_comments(self, *, number):
        return list(self.comments.get(number, []))

    def create_pr(self, *, branch, title, body, base, draft):
        self.branches.add(branch)
        self.events.append(("pr", int(branch.rsplit("-", 1)[1])))
        return PR(number=int(branch.rsplit("-", 1)[1]), url=f"u/pull/{branch}")


class FakeWorkspace:
    def __init__(self, *, root):
        self._root = Path(root)

    def prepare(self, *, issue_number, branch, base):
        return self._root / str(issue_number)

    def ensure(self, *, issue_number, branch):
        return self._root / str(issue_number)

    def commit_and_push(self, *, worktree, branch, message):
        pass

    def changed_spec_group(self, *, worktree, base):
        return None


class FakeBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=True, summary="done")


world = World(number=42)
for name in ("get_issue", "create_pr", "issue_add_label", "issue_remove_label", "issue_comment",
             "list_issue_comments"):
    setattr(orch_module.github, name, getattr(world, name))
setattr(github, "list_issue_comments", world.list_issue_comments)

tmp = Path("/tmp/oa-spec-0049-e2e")
state_a, state_b = State(path=tmp / "a.json"), State(path=tmp / "b.json")
for st in (state_a, state_b):
    store = {"runs": [], "cursors": {}}
    st._load = lambda store=store: store
    st._save = lambda *, data, store=store: store.update(data)


def make(agent_id, state):
    o = Orchestrator(backend=FakeBackend(), state=state, work_dir=tmp, agent_id=agent_id)
    o._workspace = FakeWorkspace(root=tmp)
    return o


orch_a, orch_b = make("agent-A", state_a), make("agent-B", state_b)

b_pr = {}
# A 贴完便签、尚未 read-after-write 时，B 更晚跑完整条认领 → 抢先。
world.on_after_note = lambda: b_pr.__setitem__("pr", orch_b.start_rfc(issue_number=42, base="main"))

retreated = False
try:
    orch_a.start_rfc(issue_number=42, base="main")
except ClaimLost as exc:
    retreated = True
    claim_lost_msg = str(exc)

unlabeled = [e for e in world.events if e[0] == "unlabeled"]
resume_events_before = len(world.events)
# resume 免认领：B 已在 rfc-review，再扫不产生新认领事件——这里直接演示 B 若 resume（solving/pr=0）
# 也零认领：新建一个孤儿 solving 状态，跑 start_rfc(resume=True)，断言零 labeled/comment。
world.events.clear()
state_c = State(path=tmp / "c.json")
store_c = {"runs": [], "cursors": {}}
state_c._load = lambda: store_c
state_c._save = lambda *, data: store_c.update(data)
orch_c = make("agent-C", state_c)
state_c.begin_run(issue_number=42, branch="openagents/issue-42")
orch_c.start_rfc(issue_number=42, base="main", resume=True)
resume_claim_events = [e for e in world.events if e[0] in ("labeled", "comment")]

winner = b_pr["pr"].number == 42 and retreated and state_a.all_runs() == []
notes = [identity.parse_agent_id(body=c.body) for c in world.comments[42]]

print("  证据①【唯一赢家】：B 开出 draft PR #%d，A 检出他方更晚认领 → ClaimLost 退让并清本地 solving："
      % b_pr["pr"].number, winner)
print("     └ A 退让原因：%s" % claim_lost_msg)
print("  证据②【零 unlabeled 互撕】：认领竞争期无人 remove 标签，便签只增不删（%d 条便签：%s）；"
      "唯一 unlabeled 是 B 开 PR 后的 _release_claim（%d 次，发生在 PR 之后）："
      % (len(notes), notes, len(unlabeled)),
      len(unlabeled) == 1)
print("  证据③【resume 零新认领事件】：solving/pr=0 孤儿 run 走 start_rfc(resume=True) 续跑，"
      "零 labeled、零 comment 认领事件（实测 %d 条）：" % len(resume_claim_events),
      resume_claim_events == [])

assert winner, "应恰一个赢家、输家退让清本地"
assert unlabeled == [("unlabeled", 42)], "认领竞争期不得有 unlabeled 互撕事件"
assert resume_claim_events == [], "resume 路径不得产生新认领事件"
print("  ✓ 三条断言全部通过")
PY

echo
echo "==> [4/4] spec 校验（Spec-0049 组结构 + OVERVIEW/ARCHITECTURE 无漂移）"
uv run spec validate --specs-root docs/specs
# 幂等（无漂移）自检：render/graph 前先存副本，重渲后 diff 应逐字节一致——不依赖 git 提交状态，
# 使脚本可在任意工作树上独立跑出退出码 0（CI 另有 git diff --exit-code 版本的等价漂移闸）。
cp docs/specs/OVERVIEW.md /tmp/oa-0049-overview.bak
cp docs/specs/ARCHITECTURE.md /tmp/oa-0049-arch.bak
uv run spec render --specs-root docs/specs
uv run spec graph --specs-root docs/specs
diff /tmp/oa-0049-overview.bak docs/specs/OVERVIEW.md
diff /tmp/oa-0049-arch.bak docs/specs/ARCHITECTURE.md
uv run spec graph --specs-root docs/specs --check

echo
echo "✅ Spec-0049 端到端验证通过：唯一赢家 + 零 unlabeled 互撕 + resume 零新认领事件（可复现证据见上）。"
