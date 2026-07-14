#!/usr/bin/env bash
# Spec-0065/T1-T2 端到端测试启动脚本：图驱动的并行守夜 —— 准入面（三态门控 → `ready` → curator 排
# `blocked_by` 依赖边）+ 执行面（level-triggered reconcile：sense/classify/fingerprint → SQLite 队列 →
# K 个 worker 各领一个 subject 推到卡住）。
#
# 证明架构契约在离线确定性链路上成立（intent，见 spec §11 走查表）：
#   - 走查表 t0–t7 逐 tick 断言：**反复调 run_vigil(once=True)，一次一个 tick**（单趟 tick 覆盖不了
#     t1→t3 的跨轮解锁——B 要等 A 的 PR merged 后的**下一** tick 才就绪）；
#   - t1：K=2 一 tick 并起 A 和 C（并行），B 被 QUIET(awaiting-blockers) 挡住（依赖图生效）；
#   - t3：A 的 PR merged → 下一 tick B 的 blocker 关掉 → 自然解锁（传递依赖，无需任何本地记忆）；
#   - t4（主路径）：CI 红 → agent 判上游 flaky → **自己打 needs-human + 留理由** → 同一次认领内下一圈
#     `_sense` 即 TERMINAL，轮询当场停止，**零多余 LLM 调用**、不等任何阈值；
#   - t5（护栏一）：CI 红 → agent 以为自己修了但**零变更、未打 needs-human** → fp 未变 → 盖 `attempt fp=`
#     戳 → 下一 tick 见同 fp 戳 → 降 QUIET(awaiting-effect) → **不入队、零 LLM**（证明 agent 主动叫人
#     **替代不了** attempt 戳：它自己看不见自己在空转）；
#   - t6（护栏二）：awaiting-effect age 超阈值 → `_park` 机械打 needs-human（不叫 LLM）→ TERMINAL；
#   - t7（hang）：入队 0 → `_hang` 打分类提示（前沿空 / 在解决中 / 在等 CI），不静默卡死。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯后端调度器**（守夜循环 + 队列 + 依赖图），无 product-facing
# 前端可导航；已自检工具列表：无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，沿用离线确定性测法
# （假 GitHub + 假 agent 的 tick 级状态机断言 + 契约单测 + grep 锚点）。真实自主环冒烟（`oa vigil --parallel 2`
# 在真仓上跑通 issue→PR→merged）作为成果验收在 Phase-3 人验/runbook 记录，不塞进本离线脚本。
#
# 用法：
#   bash scripts/e2e-spec-0065-graph-parallel-vigil.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/5] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/5] 感知/队列/存活探测/卡死/收口 契约单测"
uv run --extra dev pytest -q \
  tests/test_agent_curator.py \
  tests/test_recipe_vigil.py \
  tests/test_cli.py

echo
echo "==> [3/5] spec 校验 + 生成物无漂移"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/5] 走查表 t0–t7：A / B(blocked_by A) / C，K=2，逐 tick 断言"
uv run --extra dev python - <<'PY'
"""Spec-0065 §11 走查表的可执行版：假 GitHub（内存）+ 假 agent（脚本化）+ 真 vigil（一字不改）。

被替换的只有**外部世界**：GitHub 读写（`utils.github` / `utils.identity` 的贴评论）、triager/curator 两次
LLM 调用、以及 `_act` 里那个真 agent（换成一个按剧本行事的假 agent，它照样只能通过 GitHub 说话）。
`_sense` / `_classify` / `_fingerprint` / 队列 / flock / `_reconcile` / 生产者全是**生产代码原件**。
"""

import io
import sys
import tempfile
from contextlib import redirect_stderr
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openagents.recipes import vigil
from openagents.runtime.state import RuntimeState
from openagents.utils import agent_config, github, identity

A, B, C = 101, 102, 103
CLOCK = [datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)]


def now():
    return CLOCK[0]


def stamp():
    return now().isoformat().replace("+00:00", "Z")


def tick_clock(seconds):
    CLOCK[0] = CLOCK[0] + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------------------------
# 假 GitHub：一个可变的内存世界。agent 与守夜都只能通过它交谈（真实拓扑：GitHub 是唯一共享真相）。
# ---------------------------------------------------------------------------------------------
class Hub:
    def __init__(self):
        # 三个待办 issue，都带触发 label `openagents`（config.labels，即守夜的取件口）。
        self.issues = {
            A: {"title": "定义 Storage 接口", "body": "先定接口", "labels": {"openagents"}, "open": True},
            B: {"title": "实现 SQLite 后端", "body": "依赖 A 的接口", "labels": {"openagents"}, "open": True},
            C: {"title": "补 README", "body": "独立任务", "labels": {"openagents"}, "open": True},
        }
        self.edges = {A: [], B: [], C: []}  # blocked_by
        self.prs = {}  # number -> dict
        self.next_pr = 200

    def open_pr(self, *, issue_number):
        number = self.next_pr
        self.next_pr += 1
        self.prs[number] = {
            "issue": issue_number,
            "branch": f"openagents/issue-{issue_number}",
            "head": f"{issue_number}{'a' * 37}",
            "labels": set(),
            "merged": False,
            "open": True,
            "comments": [],
            "ci": ("pending", 2),  # (state, count)
            "ci_at": stamp(),
            "head_at": stamp(),
        }
        return number

    def pr_of(self, issue_number):
        for number, pr in self.prs.items():
            if pr["issue"] == issue_number:
                return number, pr
        return None, None


HUB = Hub()
ACTS = []  # 假 agent 每被叫起一次记一笔 —— 「零多余 LLM 调用」靠它断言


def fake_get_issue(*, number):
    data = HUB.issues[number]
    return github.Issue(number, data["title"], data["body"], sorted(data["labels"]))


def fake_list_issues(*, labels, state="open"):
    wanted = set(labels or [])
    return [
        github.Issue(number, data["title"], data["body"], sorted(data["labels"]))
        for number, data in sorted(HUB.issues.items())
        if data["open"] and wanted <= data["labels"]
    ]


def fake_list_open_prs():
    return [github.PR(number, f"u/{number}") for number, pr in HUB.prs.items() if pr["open"]]


def fake_pr_head_branch(*, pr_number):
    return HUB.prs[pr_number]["branch"]


def fake_pr_for_branch(*, branch):
    # **不限状态**：merged 的 PR 也要看得见（否则合并后下一圈会把 issue 读成「还没有 PR」→ 重做一遍）。
    for number, pr in HUB.prs.items():
        if pr["branch"] == branch:
            return github.PR(number, f"u/{number}")
    return None


def fake_pr_snapshot(*, pr_number):
    pr = HUB.prs[pr_number]
    state = "MERGED" if pr["merged"] else ("OPEN" if pr["open"] else "CLOSED")
    return github.PRSnapshot(
        number=pr_number,
        state=state,
        head_sha=pr["head"],
        labels=tuple(sorted(pr["labels"])),
        mergeable="MERGEABLE",
        merge_state_status="CLEAN",
        head_pushed_at=pr["head_at"],
    )


def fake_check_snapshot(*, pr_number):
    state, count = HUB.prs[pr_number]["ci"]
    return github.CheckSnapshot(state, count, HUB.prs[pr_number]["ci_at"])


def fake_check_logs(*, pr_number):
    return ["ci: 单测 test_flaky_upstream 挂了"]


def fake_list_comments(*, pr_number):
    return [
        github.Comment(index, "bot", body, at)
        for index, (body, at) in enumerate(HUB.prs[pr_number]["comments"])
    ]


def fake_post_comment(*, pr_number, body):
    HUB.prs[pr_number]["comments"].append((body, stamp()))


def fake_issue_comment(*, number, body):
    pr_number, _ = HUB.pr_of(number)
    if pr_number is not None:
        fake_post_comment(pr_number=pr_number, body=body)


def fake_add_label(*, pr_number, name):
    HUB.prs[pr_number]["labels"].add(name)


def fake_remove_label(*, pr_number, name):
    HUB.prs[pr_number]["labels"].discard(name)


def fake_issue_add_label(*, number, name):
    HUB.issues[number]["labels"].add(name)


def fake_list_blocked_by(*, number):
    return [
        github.Blocker(blocker, "CLOSED" if not HUB.issues[blocker]["open"] else "OPEN")
        for blocker in HUB.edges[number]
    ]


def fake_add_blocked_by(*, number, blocker_number):
    HUB.edges[number].append(blocker_number)


def fake_post_signed_comment(*, pr_number, body, agent_id):
    fake_post_comment(pr_number=pr_number, body=identity.sign(body=body, agent_id=agent_id or "oa"))


for name, impl in {
    "get_issue": fake_get_issue,
    "list_issues": fake_list_issues,
    "list_open_prs": fake_list_open_prs,
    "pr_head_branch": fake_pr_head_branch,
    "pr_for_branch": fake_pr_for_branch,
    "pr_snapshot": fake_pr_snapshot,
    "check_snapshot": fake_check_snapshot,
    "check_logs": fake_check_logs,
    "list_comments": fake_list_comments,
    "post_comment": fake_post_comment,
    "issue_comment": fake_issue_comment,
    "add_label": fake_add_label,
    "remove_label": fake_remove_label,
    "issue_add_label": fake_issue_add_label,
    "list_blocked_by": fake_list_blocked_by,
    "add_blocked_by": fake_add_blocked_by,
    "ensure_label": lambda *, name, description="": None,
}.items():
    setattr(github, name, impl)
identity.post_signed_comment = fake_post_signed_comment

# 两次 LLM 调用（准入面）：triager 判 actionable、curator 排边 B blocked_by A、C 独立。
vigil.stages.triage = lambda **kw: {"actionable": True, "reason": "可直接派单"}
vigil.engine.run_agent = lambda *a, **kw: {"edges": [{"issue": B, "blocked_by": [A]}]}


# ---------------------------------------------------------------------------------------------
# 假 agent：`_act` 的替身。它只能改 GitHub（开 PR / 打 label / 贴评论）——路由仍是生产代码的分支表。
# ---------------------------------------------------------------------------------------------
def fake_act(*, backend, state, work_dir, config, observed, verdict, agent_id, now, lock_fd):
    facts = observed.facts
    ACTS.append((facts.subject, verdict.action))
    kind, number = vigil._split_subject(subject=facts.subject)

    if verdict.action == vigil._ACT_SOLVE:
        HUB.open_pr(issue_number=number)
        return "已开 draft PR 并推上首版实现"

    pr = HUB.prs[facts.pr_number]
    if verdict.action == vigil._ACT_E2E:
        fake_post_signed_comment(
            pr_number=facts.pr_number,
            body=f"<!-- openagents:e2e head={facts.head_sha} -->\n✅ e2e 通过",
            agent_id=agent_id,
        )
        return "e2e 通过"
    if verdict.action == vigil._ACT_REVIEW_OR_FIX:
        pr["labels"].add(f"review-approved:{facts.head_sha[:7]}")
        return "review 通过"
    if verdict.action == vigil._ACT_MERGE:
        pr["merged"] = True
        pr["open"] = False
        HUB.issues[pr["issue"]]["open"] = False
        return "已合并"
    if verdict.action == vigil._ACT_FIX_CI:
        if pr["issue"] == B:
            # t4 主路径：agent 判定这是上游 flaky、自己修不了 → 走一等出口，自己叫人。
            pr["labels"].add("needs-human")
            fake_post_signed_comment(
                pr_number=facts.pr_number,
                body="⏸ CI 红是上游依赖 flaky，我修不了，交人。",
                agent_id=agent_id,
            )
            return "自判无解，已打 needs-human"
        # t5 护栏一：agent **以为**自己修了（只 rerun 了 CI），实际零变更、也没打 needs-human。
        return "我重跑了一遍 CI，应该好了"
    raise AssertionError(f"走查表不该走到这一支：{verdict.action}")


vigil._act = fake_act

CONFIG = agent_config.AgentConfig(
    version=1,
    agents=agent_config.AgentPolicy(backends={}),
    stages=agent_config.StagePolicy(owners={"triage": "agent"}),
    release=agent_config.ReleasePolicy(),
    interval=1,
    base="main",
    labels=["openagents"],
    repos=[],
)
WORK = Path(tempfile.mkdtemp(prefix="oa-0065-e2e-"))
STATE = RuntimeState(path=WORK / "runtime-state.json")


def run_tick():
    """跑**一个** tick（一次生产者判定 + 排空本 tick 入的活），返回本 tick 的日志。"""
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        vigil.run_vigil(
            backend=None,
            state=STATE,
            work_dir=WORK,
            config=CONFIG,
            once=True,
            concurrency=2,  # K=2：并行上限
            agent_id="oa-e2e",
            now_fn=now,
        )
    return buffer.getvalue()


def check(label, condition, detail=""):
    if not condition:
        print(f"✗ {label}{(' —— ' + detail) if detail else ''}", file=sys.stdout)
        sys.exit(1)
    print(f"  ✓ {label}")


# ---- t0/t1：准入 + 依赖边落 GitHub；K=2 并起 A 和 C，B 被 blocker 挡住 -------------------------
run_tick()
check("t0 三态准入：A/B/C 全过门控、打上 ready", all("ready" in HUB.issues[n]["labels"] for n in (A, B, C)))
check("t0 curator 排边落 GitHub 原生 blocked_by：B←A、C 独立", HUB.edges[B] == [A] and not HUB.edges[C])
check("t1 A 与 C 并行开工（各自开出 PR）", HUB.pr_of(A)[0] is not None and HUB.pr_of(C)[0] is not None)
check("t1 B 被 QUIET(awaiting-blockers) 挡住：未开 PR、零 agent 调用", HUB.pr_of(B)[0] is None)
check("t1 只叫了两次 agent（A/C 各一次 solve）", ACTS == [("issue:101", "solve"), ("issue:103", "solve")]
      or ACTS == [("issue:103", "solve"), ("issue:101", "solve")], str(ACTS))

# ---- t2/t3：CI 出结果 → A 走完流水线 merged；C 的 CI 红（护栏一登场）------------------------------
tick_clock(60)
pr_a, data_a = HUB.pr_of(A)
data_a["ci"] = ("pass", 3)
pr_c, data_c = HUB.pr_of(C)
data_c["ci"] = ("fail", 3)
ACTS.clear()
run_tick()
check("t3 A：CI 绿 → 同一次认领内 e2e→review→merge 一趟走完（无批屏障）",
      [action for subject, action in ACTS if subject == "issue:101"] == ["e2e", "review-or-fix", "merge"],
      str(ACTS))
check("t3 A 的 PR 已 merged、issue 已关", data_a["merged"] and not HUB.issues[A]["open"])
check("t5 C：CI 红 → agent 出手但零变更 → 盖 attempt fp 戳收工",
      any(vigil._ATTEMPT_MARKER in body for body, _ in data_c["comments"]))
check("t5 C 本 tick 只被叫起一次（同一 fp 上不重复出手）",
      [action for subject, action in ACTS if subject == "issue:103"] == ["fix-ci"], str(ACTS))

# ---- t3(下半)：A merged → B 的 blocker 关掉 → 自然解锁；C 见同 fp 戳 → 零 LLM ----------------------
tick_clock(60)
ACTS.clear()
run_tick()
check("t3 B：上游 A 合并后**下一 tick** 自然解锁 → solve 开出 PR", HUB.pr_of(B)[0] is not None)
check("t5 护栏一：C 的 fp 未变、见同 fp 戳 → 不入队、**零 LLM 调用**",
      not [action for subject, action in ACTS if subject == "issue:103"], str(ACTS))

# ---- t4：B 的 CI 红 → agent 自己打 needs-human（主路径：当场 TERMINAL，不等任何阈值）----------------
tick_clock(60)
pr_b, data_b = HUB.pr_of(B)
data_b["ci"] = ("fail", 3)
ACTS.clear()
run_tick()
check("t4 主路径：agent 判上游 flaky → 自己打 needs-human + 留理由",
      "needs-human" in data_b["labels"]
      and any("上游依赖 flaky" in body for body, _ in data_b["comments"]))
check("t4 同一次认领内下一圈即 TERMINAL：只叫了一次 agent（fix-ci），不再重试",
      [action for subject, action in ACTS if subject == "issue:102"] == ["fix-ci"], str(ACTS))

tick_clock(60)
ACTS.clear()
run_tick()
check("t4 轮询当场停止：B 已 TERMINAL，后续 tick 零 agent 调用", not ACTS, str(ACTS))

# ---- t6：护栏二 —— C 的 awaiting-effect 超阈值 → 机械 park（不叫 LLM）------------------------------
tick_clock(4000)
ACTS.clear()
logs = run_tick()
# `_park` 把 needs-human 打在 **issue** 上（subject=issue:103）；`_sense` 取 issue ∪ PR 的 label 并集，
# 故下一圈照样判 TERMINAL。
check("t6 护栏二：awaiting-effect 超阈值 → _park 打 needs-human（机械诊断，不叫 LLM）",
      "needs-human" in HUB.issues[C]["labels"] and not ACTS, str(ACTS))
check("t6 park 附了机械诊断 + agent 自己那条结论",
      any("重跑了一遍 CI" in body or "openagents 守夜" in body for body, _ in data_c["comments"]))

# ---- t7：全 TERMINAL → 入队 0 → _hang 打分类提示，不静默卡死 -------------------------------------
tick_clock(60)
ACTS.clear()
logs = run_tick()
check("t7 全 TERMINAL → 本 tick 入队 0 → _hang 打可观测提示", "本轮无人可动" in logs, logs)
check("t7 零 agent 调用（守夜停在那里，不空烧）", not ACTS, str(ACTS))

print("✓ 走查表 t0–t7 全部通过（含 t4 主路径 / t5 护栏一 / t6 护栏二 / t7 hang）")
PY

echo
echo "==> [5/5] grep 锚点：flock 不是 lockf / _mark_done 是 DELETE / 无 lease 列 / recipes 无 subprocess 直调"

fail() {
  echo "✗ 锚点失败：$1" >&2
  exit 1
}

# 5a. 存活证明必须是 flock 调用（`lockf` 的锁是 per-process 的，同进程 K 条 worker 线程的互斥会静默失效）。
# 只认**调用**（`fcntl.xxx(`），不认散文里的提及——模块文档正是在讲「为什么不能用 lockf」。
grep -q "fcntl\.flock(" openagents/recipes/vigil.py || fail "vigil 未用 fcntl.flock 取存活证明"
grep -q "fcntl\.lockf(" openagents/recipes/vigil.py && fail "vigil 调了 fcntl.lockf（同进程两 fd 不互斥 → 双跑）"

# 5b. 收工是 DELETE 行（留 status='done' 会被 subject UNIQUE 永久锁死该 subject）；建表 DDL 里无租约列
# （判死凭内核放锁，不凭阈值猜——一个可以调错的旋钮就是一次可能的双跑）。
grep -q "DELETE FROM work_queue" openagents/recipes/vigil.py || fail "_mark_done 不是 DELETE"
uv run --extra dev python -c "
from openagents.recipes.vigil import _SCHEMA
ddl = ' '.join(_SCHEMA.lower().split())
assert 'subject text not null unique' in ddl, 'work_queue.subject 缺 UNIQUE（去重/互斥/幂等三合一的柱子）'
assert 'lease' not in ddl and 'expires' not in ddl, '建表 DDL 含租约字段（本设计凭 flock 判死，无阈值）'
" || fail "work_queue 建表 DDL 不符（缺 subject UNIQUE / 含租约列）"

# 5c. recipes 层不直调 subprocess（Spec-0064 分层锚点：recipe 只走 utils 稳定面；进程探测落 utils/proc.py）。
for r in stages vigil backfill; do
  grep -nE 'import subprocess|subprocess\.' "openagents/recipes/${r}.py" \
    && fail "openagents/recipes/${r}.py 含 subprocess 直接调用（应走 utils）"
done

# 5d. 硬超时必须**精确**杀本次调用起的进程树：backend 自报 PID 进认领桶（`proc.publish`），超时方按桶
# 杀（`proc.kill_tree`）。若回退成「diff 本进程的子进程集合去猜」，会认错并发的 gh/git 或别的 worker 的
# agent —— 杀错人 = 那个真挂住的 agent 还在推，双跑就此发生（本 spec 的头号不变量塌掉）。
uv run --extra dev python -c "
from openagents.utils import proc
for name in ('track', 'publish', 'untrack', 'child_pids', 'kill_tree', 'hold_fd', 'inherited_fds'):
    assert hasattr(proc, name), f'utils.proc 缺 {name}（认领桶/精确杀/存活证明继承的接口面）'
" || fail "utils/proc.py 接口面不符（认领桶 + kill_tree + hold_fd/inherited_fds）"
grep -q "proc_utils\.publish(pid=proc\.pid, handle=proc)" openagents/backends/claude_code.py \
  || fail "backend 未自报 PID+句柄（裸 PID 会杀到 PID 复用后的无辜进程 → 双跑）"

# 5d-bis. **存活证明必须跟着真正在干活的进程走。** flock 只证明「守夜进程活着」；守夜被 SIGKILL/OOM/docker
# stop 打死时，它起的 agent 子进程是被**孤儿化**、不是被杀（要到下次写 stdout 才发现父亲没了——足够它跑完一次
# push）。故把锁的 fd 传给 agent 子进程继承（pass_fds）：孤儿还在跑 → 锁抢不到 → 行不会被回收重领 → 无双跑。
grep -q "pass_fds=proc_utils\.inherited_fds()" openagents/backends/claude_code.py \
  || fail "backend 未把 flock fd 传给 agent 子进程继承（守夜被杀 → 孤儿 agent 仍在推 → 行被回收 → 双跑）"
grep -q "proc\.hold_fd(fd=self\._lock_fd)" openagents/recipes/vigil.py \
  || fail "vigil 未把认领的 flock fd 登记给 agent 子进程继承"

# 5d-ter. **继承必须配一道闸。** 锁传给 agent 后也会传给它的孙子（pass_fds 在子进程里清了 CLOEXEC，而 agent
# 不是 python，不会替我们关）：agent 泄漏一个长命孙子（MCP server / 后台 dev server），那把锁就永远不放 →
# 那个 queued 行永远领不走，而所有看门狗都看不见它（回收只扫 claimed / IN_FLIGHT 看 claimed_at / QUIET 看门狗
# 只对 QUIET 生效）。没有 _sweep_stalled，这里就是拿一个罕见的双跑换一个**永久的静默停摆**。
uv run --extra dev python -c "
import inspect
from openagents.recipes import vigil
assert '_sweep_stalled(' in inspect.getsource(vigil._producer_tick), (
    '生产者 tick 未扫「queued 却领不走」的行（存活证明被泄漏进程占死 → 永久静默停摆）'
)
" || fail "生产者 tick 未扫陈锁"

# 5d-quater. **那道闸自己会误伤，必须再配三道。** _sweep_stalled 会 park 一个 subject（停掉一个 issue 的活），
# 所以它的假阳性比它要治的病更贵。三个已证的误伤面：
#   (1) TOCTOU：SELECT 出快照后，park 一行要花好几秒的 gh 往返；这期间 worker 完全可以合法领走**另一行**并
#       拿走它的锁 —— 再去探它，锁是「被占着」的，于是把一个正在干活的 claimed 行 park 掉并删了。故 park 前
#       必须在 BEGIN IMMEDIATE 里复核「这行还是 queued」，且 DELETE 必须带 AND status='queued'。
#   (2) 交接窗口：_requeue_or_park/_reclaim_dead 先把 status 改回 queued 提交、再 os.close(fd)，中间那一瞬
#       就是合法的「queued 且锁被持有」。而 enqueued_at 为了防饿死是**从不刷新**的，拿它当年龄闸 → 长命行一
#       requeue 就「超龄」，正好在这个窗口里被判死。故年龄必须是**跨 tick** 的 seen_locked 记忆：一次 tick 里
#       只可能观测到一次，活不过第二次 tick。
#   (3) 一行 park 不成（gh 429）不许掀桌：异常逃出去 → 整个 tick 死 → 不 _intake、不感知，全线停摆。
grep -q "BEGIN IMMEDIATE" openagents/recipes/vigil.py \
  || fail "park 前未在 BEGIN IMMEDIATE 里复核行状态（TOCTOU：会把 worker 正在跑的 claimed 行删掉）"
grep -q "DELETE FROM work_queue WHERE id=? AND status='queued'" openagents/recipes/vigil.py \
  || fail "park 的 DELETE 未带 status='queued' 守卫（发标签那几秒里被领走 → 删掉在跑的行）"
# 而且**删行必须发生在 gh 之前**：只「复核一下再发 label」救得了行、救不了话——复核到发完 label 的那几秒里
# 泄漏进程可能恰好死掉、锁一自由 worker 就合法领走并开跑，那条 needs-human 于是落在一个**健康且正在被执行**
# 的 subject 上 → 下一圈判 TERMINAL → worker 掉头就走 → 这个 issue 再也不会被动手。删行即预约（_claim_next
# 只认 queued），抢到了才开口。
uv run --extra dev python -c "
import ast, inspect, textwrap
from openagents.recipes import vigil
fn = ast.parse(textwrap.dedent(inspect.getsource(vigil._park_stalled))).body[0]
body = fn.body[1:] if ast.get_docstring(fn) else fn.body   # 只看**代码**：文档字符串里也写着这两个词，
code = chr(10).join(ast.unparse(node) for node in body)    # 拿原文找会被自己的注释喂成一条恒真断言
assert code.index('DELETE FROM work_queue') < code.index('_park_needs_human'), (
    '_park_stalled 先发 label 再删行 → label 会落在一个 worker 已合法领走的健康 subject 上（永久停摆）'
)
" || fail "park 的顺序错了（必须先抢行、再开口）"
grep -q "seen_locked" openagents/recipes/vigil.py \
  || fail "陈锁判定未跨 tick（用 enqueued_at 当年龄闸会误杀 requeue/reclaim 的交接窗口）"
uv run --extra dev python -c "
import inspect
from openagents.recipes import vigil
sweep = inspect.getsource(vigil._sweep_stalled)
assert 'except' in sweep, '_sweep_stalled 未隔离单行 park 失败（一次 gh 429 会掀掉整个生产者 tick）'
drain = inspect.getsource(vigil._drain_queue)
assert '_sweep_stalled' in drain, '_drain_queue 不扫陈锁（--once 会在泄漏的锁上干等满 _DRAIN_MAX_SECONDS）'
" || fail "陈锁闸的隔离/排空面不符"

# 5d-quinquies. **`triage: human` 是一场对话，不是一次挂起**，而且那道闸必须是**人闸**。
#   (1) 挂 needs-human 等人摘 label 是死胡同：needs-human 在 `_classify` 里是 TERMINAL、`_intake` 也跳过带它
#       的 issue —— 挂上之后守夜再不看这个 issue，人在底下回什么话都没人读。故要在评论里问、等人回话再判。
#   (2) 判「人点头没有」**不能拿 triager 顶**：triager 判的是另一个问题（issue 正文自不自洽），且纪律是
#       **fail-open**（拿不准就派单）。人明说「先别做」不属于它那五类矛盾中的任何一类 → 它照判 actionable
#       → **在人明确否决之下把活派出去**。那道人闸会当场退化成一台偏向「是」的 agent 闸。故必须走 fail-CLOSED
#       的 admitter（stages.admit）。
#   (3) 等的那段必须**零 LLM**：准入面每 tick 都会重新扫到这个 issue（它既没 ready 也没 needs-human），
#       每轮叫一次 agent = 一台按 tick 计费的印钞机。
#   (4) 「人回话了」的判据必须在**代码**里判死：只认我们提问**之后**发的、**没有我方签名**的评论。少了签名
#       这一条，我们自己写的 park 理由/attempt 戳就会被当成人的回话 → agent 对着自己写的话开会（自问自答）。
uv run --extra dev python -c "
import ast, inspect, textwrap
from openagents.recipes import vigil

def _code(fn):  # 只看**代码**：文档字符串里出现的词不算数（措辞骗不过 AST）
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    stmts = node.body[1:] if ast.get_docstring(node) else node.body
    return chr(10).join(ast.unparse(s) for s in stmts)

code = _code(vigil._ask_human)
assert '_ADMIT_ASK_MARK' in code, '_ask_human 没有「问过了吗」的标记 → 每 tick 重复提问'
assert 'stages.admit' in code, '_ask_human 未走 fail-closed 的 admitter'
assert 'stages.triage' not in code, (
    '_ask_human 拿 triager 判「人点头没有」→ 它 fail-open，人明说「先别做」也会被判可派单（人闸退化）'
)
assert '_human_replies' in code, '_ask_human 不判「人回话了没」→ 等待期每 tick 叫一次 agent（印钞机）'
assert code.index('_human_replies') < code.index('stages.admit'), (
    '_ask_human 先叫 agent 再判有没有人回话 → 等待期照样烧 LLM'
)
assert '_dialogue' in code, '_ask_human 没把对话喂给 admitter → 人说的话等于没说'
assert code.index('_post_admit_verdict') < code.index('_grant_ready'), (
    '裁决未先落 GitHub 再落地 → 打 label 那步一挂（429），下一 tick 就要重判一次（重复烧 LLM）'
)
assert code.index('_post_admit_try') < code.index('stages.admit'), (
    'try 戳（LLM 的准入券）没在叫 agent 之前盖 → agent 一判崩（输出不合约/超时/429）就什么持久痕迹都不留，'
    '下一 tick 又扫到这个 issue → 每 tick 烧一次 LLM，永远'
)
assert '_admit_tried' in code, (
    '没判「人这句话是不是已经烧过一次 agent」→ 判崩的 issue 每 tick 重烧一次，不会转人工'
)
replies = _code(vigil._human_replies)
assert 'parse_agent_id' in replies and 'created_at >' in replies, (
    '「人回话了」的判据不全（须同时是：提问之后 + 无我方签名），否则会把自己写的评论当成人的回话'
)
assert '_MAINTAINER_ASSOCIATIONS' in replies, (
    '人闸不认人 → 公开仓库里任何路人回一句「可以，做吧」都能把活派出去（admitter 的提示词拦不住：'
    '它读到的只是一段外人可写的文本，压根不知道该听谁的）'
)
dialogue = _code(vigil._dialogue)
assert '_human_replies' in dialogue, (
    '喂给 admitter 的对话不是「我们的提问 + 维护者的回话」→ 路人评论进 prompt = 把 fail-closed 的人闸'
    '暴露给提示词注入；我方自己的戳进 prompt = agent 在同一段对话里跟自己开会'
)
verdict = _code(vigil._admit_verdict)
assert 'reply_key' in verdict and 'created_at' not in verdict, (
    '裁决戳挂时间戳而不是评论 id → GitHub 的 createdAt 只到秒，人在同一秒里改口说的新话会命中上一句话的'
    'refused 戳 → 人再也无法点头（fail-closed 从「多等一句话」退化成「永久拒绝」）'
)
key = _code(vigil._reply_key)
assert 'reply.id' in key, '人那句话的身份必须是 comment id（永不复用），不能拿只到秒的时间戳当身份'
park = _code(vigil._park_needs_human)
assert 'identity.sign' in park, (
    'park 的理由评论没签名 → 人只摘 label 不回话时，我们自己写的 park 理由会被当成人的回话（自问自答）'
)
assert '_already_said' in park, (
    'park 不查重 → 人摘掉 label 却什么也没改变时，每 tick 重贴一条一模一样的理由（label 幂等，评论不幂等）'
)
" || fail "准入面 human 三态不是对话 / 拿 fail-open 的 triager 当人闸 / 等待期烧 LLM / 我方评论未签名 / 人闸不认人"

# 5d-sexies. admitter 的纪律必须是 **fail-closed**：默认「没点头」。它的判据只有一个（人到底同意没有），
# 输出面 {approved, reason} 与 triager 的 {actionable, reason} 刻意不同名——一个位子一份契约，串了就会被
# 当成同义词重新接回 triager 去。
uv run --extra dev python -c "
from openagents.agents import admitter
assert admitter.OUTPUT_SCHEMA == {'approved': bool, 'reason': str}, 'admitter 的输出契约不符'
tmpl = admitter.PROMPT.template
for token in ('\$issue_body', '\$dialogue'):
    assert token in tmpl, f'admitter PROMPT 缺占位符 {token}'
assert 'fail-closed' in tmpl or '不可擅自开工' in tmpl, 'admitter 未写死 fail-closed 纪律（拿不准=没点头）'
" || fail "admitter 契约/纪律不符（人闸必须 fail-closed）"

# 5e. `needs-human` 是 agent 的一等出口：每个**叫起 agent** 的分支都要把契约拼进提示词，否则该分支的
# agent 无路可退，只能硬着头皮往下走（兜底变主路径）。7 个 _do_* 里 _do_merge 是纯机械的，不叫 agent。
uv run --extra dev python -c "
import inspect
from openagents.recipes import vigil
src = inspect.getsource(vigil)
branches = [n for n in dir(vigil) if n.startswith('_do_') and n != '_do_merge']
missing = [
    n for n in branches
    if '_NEEDS_HUMAN_CONTRACT' not in inspect.getsource(getattr(vigil, n))
]
assert not missing, f'这些 agent 分支没拼 needs-human 契约：{missing}'
assert len(branches) >= 6, f'agent 分支只找到 {len(branches)} 个，锚点可能失准'
" || fail "有 agent 分支未注入 _NEEDS_HUMAN_CONTRACT（一等出口被堵死）"

# 5f. `--parallel` 是并发度旋钮，必须在 argparse 层收边界：0/负数会被静默当成 1（K 台机器变 1 台，
# 排队假死），巨大值会真的去开那么多线程（打爆 gh 限流/文件句柄）。
uv run --extra dev python -c "
import argparse
from openagents.cli import _MAX_PARALLEL, _parallel_k
assert _parallel_k('1') == 1 and _parallel_k(str(_MAX_PARALLEL)) == _MAX_PARALLEL
for bad in ('0', '-3', str(_MAX_PARALLEL + 1), 'abc'):
    try:
        _parallel_k(bad)
    except argparse.ArgumentTypeError:
        continue
    raise AssertionError(f'--parallel 接受了越界值 {bad!r}')
" || fail "--parallel 未收边界（0/负数/超大值被放行）"

echo "✓ grep 锚点全部通过：flock（非 lockf）、DELETE 收工、无租约列、recipes 零 subprocess 直调、"
echo "  精确杀进程树（自报 PID）、needs-human 契约注入全分支、--parallel 边界"
echo
echo "✅ Spec-0065 离线 e2e 全绿"
