#!/usr/bin/env bash
# Spec-0056/T3 端到端测试启动脚本：git 交付/冲突下放 agent（rebase 自愈）+ harness head 前移硬闸。
#
# 演示 issue #140 的核心闭环：把「把成果真正推上远端」下放给 agent（commit → 记 fetch 前 BASE →
# rebase 解冲突 → push --force-with-lease=<branch>:$BASE），harness 只保留一道死代码硬闸
# assert_delivered（origin/<branch> == 本地 HEAD 才放行，不等即打 needs-human 转人工）。
#
# 两段：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，全程 mock，不触达真实
#      gh/claude（覆盖 T1 硬闸/决策 7、T2 交付协议契约锁 + 硬闸路由 + 隔离修复）。
#   2) 离线成果演练（默认执行）—— 用**真实本地 git**（裸库当远端 + worktree）构造复现态
#      「远端 PR 分支领先 base + 本地对同一文件重起草导致分叉」，用把交付协议**真正执行成 git
#      命令**的 fake backend 驱动 orchestrator.implement，断言：
#        (a) rebase 自愈 + force-with-lease 推上、origin/<branch> 前移到本地 HEAD（成果到达 PR head）;
#        (b) 反例——fake backend「假装完成但不 push」→ assert_delivered 判未交付。PR #141 review 必修后
#            分两层：(b1) implement 抛类型化 DeliveryStalled、orchestrator 不自打标签评论；(b2) messages
#            catch → _block(gate=delivery) 置 STATUS_BLOCKED（天然 sticky）+ needs-human + 恰一条评论；
#            (b3) 第二轮 poll 保持挂起、不再重入 coding、不再贴新评论（杀掉无界重烧 + 刷屏）;
#        (c) 推送用的是 --force-with-lease=<branch>:<BASE> 且 BASE 为 fetch 前 SHA、**从不**裸 --force。
#
# 形态说明（evidence 分层，理念 8）：本 feature 是守夜人自主环内部的 **git 交付/编排管道**，无任何
# product-facing 前端界面——唯一可观测成果「分叉后成果果真前移到 PR head」落在 git ref 与 GitHub PR
# 元数据上，不经任何 HTTP 前端/看板渲染。故浏览器导航/截图式 e2e **不适用**（本环境亦无 Playwright/
# Chrome DevTools MCP）；成果证据用 CLI/pytest + 真实本地 git 驱动的脚本，以「git rev-parse
# origin/<branch> 是否前移到本地 HEAD」这一 git ref 断言作为正确观测面。fake backend（非真 LLM）
# 验证的是**交付协议 + 硬闸的编排语义**，不验证「真 agent 会不会照 prompt 做」——后者靠线上守夜 + PR 人审兜。
#
# 用法：
#   bash scripts/e2e-spec-0056-git-delivery-rebase-selfheal.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] 离线成果演练：真实本地 git 分叉 → rebase 自愈 → force-with-lease 交付闭环 + 反例走 needs-human"
uv run python - <<'PY'
# Spec-0056/T3：用真实本地 git 构造复现态，驱动 orchestrator.implement 走「交付下放 agent + head
# 前移硬闸」闭环。全程离线：不触网、不调真实 gh/LLM（github.* 逐个打桩、backend 为执行协议的 fake）。
import subprocess
import tempfile
from pathlib import Path

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR
from openagents.orchestrator import Orchestrator, OrchestratorError
from openagents.state import State

BRANCH = "openagents/issue-3"


def git(*, cwd, args, check=True):
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check
    )


def init_repo(*, path, bare=False):
    path.mkdir(parents=True, exist_ok=True)
    git(cwd=path, args=["init", "--bare"] if bare else ["init"])
    if not bare:
        git(cwd=path, args=["config", "user.email", "e2e@openagents.test"])
        git(cwd=path, args=["config", "user.name", "e2e"])
        git(cwd=path, args=["config", "commit.gpgsign", "false"])


def setup_diverged(*, root):
    """远端裸库 + PR 分支领先 base；本地 worktree 对同一文件重起草导致分叉（冲突）。返回 worktree 路径。"""
    remote = root / "remote.git"
    init_repo(path=remote, bare=True)
    seed = root / "seed"
    init_repo(path=seed)
    (seed / "spec.txt").write_text("base\n")
    git(cwd=seed, args=["add", "-A"])
    git(cwd=seed, args=["commit", "-m", "chore: base"])
    git(cwd=seed, args=["branch", "-M", "main"])
    git(cwd=seed, args=["remote", "add", "origin", str(remote)])
    git(cwd=seed, args=["push", "-u", "origin", "main"])
    # 远端 PR 分支领先 base（改了 spec.txt，与本地将写内容冲突）。
    git(cwd=seed, args=["checkout", "-b", BRANCH, "main"])
    (seed / "spec.txt").write_text("remote-change\n")
    git(cwd=seed, args=["add", "-A"])
    git(cwd=seed, args=["commit", "-m", "docs: remote draft"])
    git(cwd=seed, args=["push", "-u", "origin", BRANCH])
    # 本地 worktree：从 origin/main 起分支（与 origin/<branch> 分叉），带一处冲突改动待 commit。
    wt = root / ".openagents" / "worktrees" / "issue-3"
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(cwd=root, args=["clone", str(remote), str(wt)])
    git(cwd=wt, args=["config", "user.email", "e2e@openagents.test"])
    git(cwd=wt, args=["config", "user.name", "e2e"])
    git(cwd=wt, args=["config", "commit.gpgsign", "false"])
    git(cwd=wt, args=["checkout", "-b", BRANCH, "origin/main"])
    (wt / "spec.txt").write_text("local-change\n")
    return wt


class ProtocolBackend:
    """把交付协议真正执行成 git 命令的 fake backend：commit → 记 fetch 前 BASE → rebase 解冲突 →
    push --force-with-lease=<branch>:$BASE。stall=True 时「假装完成但不 push」（反例）。"""

    name = "protocol"

    def __init__(self, *, stall):
        self._stall = stall
        self.push_cmd = None
        self.base = None

    def run(self, *, work_dir, task, context):
        wt = Path(work_dir)
        git(cwd=wt, args=["add", "-A"])
        git(cwd=wt, args=["commit", "-m", "feat: local draft"], check=False)
        if self._stall:
            return AgentResult(changed=True, summary="pretend-done-but-no-push")
        # BASE 取 fetch **之前**的远端基点（footgun 防线）。
        self.base = git(cwd=wt, args=["rev-parse", f"origin/{BRANCH}"]).stdout.strip()
        git(cwd=wt, args=["fetch", "origin", BRANCH])
        rebase = git(cwd=wt, args=["rebase", f"origin/{BRANCH}"], check=False)
        if rebase.returncode != 0:
            (wt / "spec.txt").write_text("resolved-by-agent\n")
            git(cwd=wt, args=["add", "-A"])
            cont = git(cwd=wt, args=["rebase", "--continue"], check=False)
            if cont.returncode != 0:
                git(cwd=wt, args=["-c", "core.editor=true", "rebase", "--continue"], check=False)
        self.push_cmd = ["push", f"--force-with-lease={BRANCH}:{self.base}", "origin", BRANCH]
        git(cwd=wt, args=self.push_cmd)
        return AgentResult(changed=True, summary="delivered")


def make_orch(*, root, backend):
    state = State(path=root / ".openagents" / "state.json")
    state.record_run(issue_number=3, branch=BRANCH, pr=PR(number=5, url="u/pull/5"))
    return Orchestrator(backend=backend, state=state, work_dir=root, agent_id="agent-e2e")


import openagents.github as gh  # noqa: E402

# --- 演练 (a)：分叉 → rebase 自愈 → force-with-lease 推上 → head 前移硬闸放行 --- #
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    wt = setup_diverged(root=root)
    # 预置分叉证据：origin/<branch> 不是本地 HEAD 的祖先（真·分叉，复现 issue #140）。
    git(cwd=wt, args=["fetch", "origin", BRANCH])
    anc = git(cwd=wt, args=["merge-base", "--is-ancestor", f"origin/{BRANCH}", "HEAD"], check=False)
    assert anc.returncode != 0, "预期分叉，但 origin/<branch> 竟是本地 HEAD 的祖先"
    print(f"  · 复现态就绪：本地与 origin/{BRANCH} 已分叉（非快进 push 会被拒）")

    backend = ProtocolBackend(stall=False)
    orch = make_orch(root=root, backend=backend)
    gh.mark_ready = lambda *, pr_number: None  # type: ignore[assignment]
    orch.implement(pr_number=5)

    head = git(cwd=wt, args=["rev-parse", "HEAD"]).stdout.strip()
    remote_head = git(cwd=wt, args=["rev-parse", f"origin/{BRANCH}"]).stdout.strip()
    assert head == remote_head, f"head 未前移：HEAD={head[:12]} ≠ origin={remote_head[:12]}"
    print(f"  ✓ (a) rebase 自愈 + force-with-lease 推上：origin/{BRANCH} 前移到本地 HEAD={head[:12]}")

    # (c)：推送带 lease + BASE（fetch 前 SHA），仅本分支，绝不裸 --force。
    joined = " ".join(backend.push_cmd or [])
    assert f"--force-with-lease={BRANCH}:{backend.base}" in joined, f"lease/BASE 不符：{joined}"
    assert "--force " not in joined and not joined.endswith("--force"), f"出现裸 --force：{joined}"
    print(f"  ✓ (c) 推送带 lease、BASE 为 fetch 前 SHA={backend.base[:12]}、无裸 --force")

# --- 演练 (b) 反例：假装完成但不 push → assert_delivered 判未交付 → 交付硬闸兜底 --- #
# PR #141 review 必修后分两层演示：
#   (b1) orchestrator 层：有 record 的 implement 段抛类型化 DeliveryStalled，**不再自打**标签/评论
#        （routing 上移到 messages，避免 needs-human 不 sticky）。
#   (b2) messages 层：poll 的阶段路由外层 catch DeliveryStalled → _block(gate="delivery") 置
#        STATUS_BLOCKED（天然 sticky）+ needs-human + 恰一条结构化评论；**第二轮 poll 不再重入 coding、
#        不再贴新评论**（正面证明本 spec 初衷：杀掉「静默 / 有声但无界」两种重烧循环）。
from openagents.messages import Messages  # noqa: E402
from openagents.orchestrator import DeliveryStalled  # noqa: E402
from openagents.hold import NONE as NO_HOLD  # noqa: E402
from openagents.state import STATUS_BLOCKED, STATUS_PR_OPEN  # noqa: E402
from openagents.github import Comment  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    setup_diverged(root=root)
    backend = ProtocolBackend(stall=True)  # commit 了但不 push
    orch = make_orch(root=root, backend=backend)
    state = orch._state  # 复用同一 State（含 pr=5 的 coding record）

    # (b1)：orchestrator 层——implement 抛 DeliveryStalled，且**不**碰 add_label/post_comment。
    routed = {"add_label": 0, "post_comment": 0}
    gh.mark_ready = lambda *, pr_number: None  # type: ignore[assignment]
    gh.add_label = lambda *, pr_number, name: routed.__setitem__("add_label", 1)  # type: ignore[assignment]
    gh.post_comment = lambda *, pr_number, body: routed.__setitem__("post_comment", 1)  # type: ignore[assignment]

    stalled = None
    try:
        orch.implement(pr_number=5)
    except DeliveryStalled as exc:
        stalled = exc
    assert stalled is not None, "反例未抛 DeliveryStalled（硬闸应判未交付）"
    assert isinstance(stalled, OrchestratorError), "DeliveryStalled 须是 OrchestratorError 子类（漏 catch 也被兜住）"
    assert stalled.pr_number == 5 and stalled.branch == BRANCH, "信号未携定位信息"
    assert sum(routed.values()) == 0, f"orchestrator 不该自打标签/评论：{routed}"
    print("  ✓ (b1) implement 抛 DeliveryStalled、携 branch/pr、orchestrator 不自打标签评论（routing 上移）")

    # (b2)：messages 层——poll 的路由外层 catch → _block(gate=delivery) 置 STATUS_BLOCKED（sticky）。
    posted: list[str] = []
    labels: list[str] = []
    gh.is_merged = lambda *, pr_number: False  # type: ignore[assignment]
    gh.is_closed = lambda *, pr_number: False  # type: ignore[assignment]
    gh.add_label = lambda *, pr_number, name: labels.append(name)  # type: ignore[assignment]
    gh.list_comments = lambda *, pr_number: []  # type: ignore[assignment]
    # 让 coding 流水线读到 orchestrator 交付调用：CLEAN + CI 绿 + 无 sticky 指纹。
    gh.mergeability = lambda *, pr_number: type(  # type: ignore[assignment]
        "_M", (), {"merge_state_status": "CLEAN", "mergeable": "MERGEABLE"}
    )()
    gh.check_status = lambda *, pr_number: type(  # type: ignore[assignment]
        "_S", (), {"state": "pass", "failed_logs": []}
    )()
    gh.code_fingerprint = lambda *, pr_number: ""  # type: ignore[assignment]
    import openagents.identity as ident  # noqa: E402

    ident.post_signed_comment = lambda *, pr_number, body, agent_id: posted.append(body)  # type: ignore[assignment]
    ident.new_human_comments = lambda *, pr_number, since: []  # type: ignore[assignment]
    # coding 阶段的 orchestrator 交付调用（run_e2e）同样抛 DeliveryStalled（模拟 executor 没推证据）。
    orch.run_e2e = lambda *, pr_number: (_ for _ in ()).throw(  # type: ignore[assignment]
        DeliveryStalled(branch=BRANCH, reason="head 未前移、疑似未交付", pr_number=pr_number)
    )
    msgs = Messages(orchestrator=orch, state=state, agent_id="agent-e2e")
    rec = state.find_run(pr_number=5)
    rec.status = STATUS_PR_OPEN
    state.update_status(issue_number=3, status=STATUS_PR_OPEN)

    ev1 = msgs._process_run(record=state.find_run(pr_number=5), hold=NO_HOLD)
    assert ev1 == {"pr_number": 5, "reason": "blocked", "gate": "delivery"}, f"未收口成 blocked：{ev1}"
    assert state.find_run(pr_number=5).status == STATUS_BLOCKED, "未置 STATUS_BLOCKED（sticky 的关键那半）"
    assert gh.BLOCKED_LABEL in labels and len(posted) == 1, f"应恰一条挂起评论 + needs-human：{labels}/{len(posted)}"
    print(f"  ✓ (b2) messages catch → _block(delivery) 置 STATUS_BLOCKED + {gh.BLOCKED_LABEL} + 恰一条评论")

    # 第二轮 poll：blocked + needs-human 仍在 + 无新人类评论 → 不再重入 coding、不再贴新评论。
    gh.has_label = lambda *, pr_number, name: True  # type: ignore[assignment]
    ev2 = msgs._process_run(record=state.find_run(pr_number=5), hold=NO_HOLD)
    assert ev2 is None, f"第二轮应保持挂起（不再重入 coding）：{ev2}"
    assert len(posted) == 1, "第二轮不该再贴新评论（sticky 杀掉刷屏）"
    print("  ✓ (b3) 第二轮 poll 保持挂起：不再派 agent、不再贴新评论（杀掉无界重烧 + 刷屏）")

print("\n[Spec-0056/T3] 演练全绿：分叉→rebase 自愈→head 前移闭环；反例交付硬闸→sticky needs-human→无重入；推送始终带 lease、无裸 force。")
PY

echo
echo "==> [额外] spec 工具三闸（validate / render / graph）确认 spec 组自洽"
uv run spec validate
uv run spec render >/dev/null
uv run spec graph >/dev/null

echo
echo "✅ Spec-0056 端到端脚本全部通过。"
