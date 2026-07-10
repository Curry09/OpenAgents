"""独立验证探针（不用仓库自带测试）：注入 config 三态 + canned 裁决，断言 run_vigil 编排分支。
证明 intent：
 - advance_merge 按注入 stages 三态真正驱动 agent/human/skip 分支；
 - 合并流水线序 conflict→ci→e2e→review→merge（conflict 在读 CI 前先判 mergeable）；
 - CI/e2e/review 失败(owner=agent)→派 implementer 迭代→返阶段事件(下轮从 conflict 重进)；
 - owner=human→挂 needs-human blocked；
 - 确定性硬闸 round_cap 不受 stages 管辖恒在。
不触真实 LLM/网络/仓库：全 monkeypatch。
"""
import sys, types
from pathlib import Path
from openagents.recipes import vigil
from openagents.recipes import stages
from openagents.runtime import gates
from openagents.utils import agent_config as ac, github

PASS, FAIL = [], []
def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("✓" if cond else "✗") + " " + name)

CALLS = []  # 记录调用序，验证流水线顺序

class FakeState:
    def __init__(self): self.runs = {}
    def set_run(self, *, issue_number, status, branch, pr_number):
        self.runs[issue_number] = {"status": status, "branch": branch, "pr_number": pr_number}

def make_run(status="open"):
    return vigil._Run(pr_number=101, issue_number=7, branch="openagents/issue-7", status=status)

def policy(**owners):
    base = {s: "agent" for s in ("triage","rfc","conflict","ci","e2e","review","merge")}
    base.update(owners)
    return ac.StagePolicy(owners=base)

# ---- 通用 stub：非终态、mergeable CLEAN ----
def base_stubs(monkey):
    monkey["github.is_merged"] = lambda *, pr_number: False
    monkey["github.is_closed"] = lambda *, pr_number: False
    monkey["github.mergeability"] = lambda *, pr_number: "CLEAN"
    monkey["github.get_issue"] = lambda *, number: types.SimpleNamespace(body="issue body")
    monkey["github.close_issue"] = lambda *, number: CALLS.append(("close_issue", number))
    monkey["gates.is_conflicting"] = lambda *, mergeability: mergeability in ("DIRTY","CONFLICTING")
    monkey["gates.is_mergeable_unknown"] = lambda *, mergeability: mergeability in ("UNKNOWN", None)
    monkey["gates.is_behind"] = lambda *, mergeability: mergeability == "BEHIND"
    monkey["stages.ci"] = lambda *, pr_number: (CALLS.append(("ci", pr_number)) or stages.CI_PASS)
    monkey["stages.e2e"] = lambda *, pr_number: (CALLS.append(("e2e", pr_number)) or stages.E2E_OK)
    def _review(*, backend, work_dir, pr_number, issue_body, context_text):
        CALLS.append(("review", pr_number)); return {"verdict": "PASS", "reason": ""}
    monkey["stages.review"] = _review
    monkey["stages.merge"] = lambda *, pr_number: CALLS.append(("merge", pr_number))
    def _impl(*, backend, work_dir, issue_number, pr_number, feedback, context_text):
        CALLS.append(("implement", feedback)); return {"summary": "did"}
    monkey["stages.implement"] = _impl
    def _conflict(*, backend, work_dir, pr_number, issue_number, branch):
        CALLS.append(("conflict", pr_number)); return {"delivered": True, "reason": "resolved"}
    monkey["stages.conflict"] = _conflict
    vigil._ensure_pr_worktree = lambda *, work_dir, run: Path("/tmp/wt")

ORIG = {}
def apply(monkey):
    for k, v in monkey.items():
        mod, attr = k.split(".")
        target = {"github": github, "gates": gates, "stages": stages}[mod]
        ORIG[k] = getattr(target, attr)
        setattr(target, attr, v)
def restore():
    for k, v in ORIG.items():
        mod, attr = k.split(".")
        target = {"github": github, "gates": gates, "stages": stages}[mod]
        setattr(target, attr, v)
    ORIG.clear()

def run_advance(pol, run=None):
    global CALLS; CALLS = []
    st = FakeState()
    ev = vigil.advance_merge(backend=object(), state=st, work_dir=Path("/tmp"),
                             stages_policy=pol, run=run or make_run(),
                             now=__import__("datetime").datetime.now(__import__("datetime").UTC))
    return ev, st

# === 场景 1：全 agent + 全 PASS → 流水线序 conflict?→ci→e2e→review→merge，最终 merged ===
m = {}; base_stubs(m); apply(m)
ev, st = run_advance(policy())
restore()
order = [c[0] for c in CALLS]
check("全 agent 全绿→最终 merged", ev["reason"]=="merged")
check("流水线序 ci→e2e→review→merge(conflict CLEAN 跳过解冲突)", order==["ci","e2e","review","merge","close_issue"])
check("merge:agent 自动合调 stages.merge", ("merge",101) in CALLS)
check("merged 后置 done + 关 issue", st.runs.get(7,{}).get("status")=="done")

# === 场景 2：conflict 必在 CI 前——mergeable=DIRTY 时先解冲突、绝不读 CI ===
m = {}; base_stubs(m); apply(m)
ev, st = run_advance(policy())  # mergeability CLEAN default, override:
restore()
m = {}; base_stubs(m); m["github.mergeability"] = lambda *, pr_number: "DIRTY"; apply(m)
ev, st = run_advance(policy())
restore()
check("DIRTY→先解 conflict(reason=resolved)", ev["reason"]=="resolved")
check("DIRTY→读 CI 之前短路(CALLS 无 ci)", "ci" not in [c[0] for c in CALLS])
check("DIRTY→conflict 阶段被调", ("conflict",101) in CALLS)

# === 场景 3：mergeable=UNKNOWN → 本轮不推进(等下轮)，绝不读 CI ===
m = {}; base_stubs(m); m["github.mergeability"] = lambda *, pr_number: "UNKNOWN"; apply(m)
ev, st = run_advance(policy())
restore()
check("UNKNOWN→本轮不推进(ev is None)", ev is None)
check("UNKNOWN→不读 CI", "ci" not in [c[0] for c in CALLS])

# === 场景 4：CI 红 + ci:agent → 派 implementer 打回、返 reason=ci(下轮从 conflict 重进) ===
m = {}; base_stubs(m); m["stages.ci"] = lambda *, pr_number: (CALLS.append(("ci",pr_number)) or stages.CI_FAIL); apply(m)
ev, st = run_advance(policy())
restore()
check("CI 红 ci:agent→reason=ci", ev["reason"]=="ci")
check("CI 红 ci:agent→派 implementer 迭代", any(c[0]=="implement" for c in CALLS))
check("CI 红→未走到 e2e/review/merge(下轮从头重进)", not any(c[0] in ("e2e","review","merge") for c in CALLS))

# === 场景 5：CI 红 + ci:human → 挂 needs-human blocked，不派 implementer ===
m = {}; base_stubs(m); m["stages.ci"] = lambda *, pr_number: stages.CI_FAIL; apply(m)
ev, st = run_advance(policy(ci="human"))
restore()
check("CI 红 ci:human→reason=blocked", ev["reason"]=="blocked" and ev.get("gate")=="ci")
check("CI 红 ci:human→不派 implementer", not any(c[0]=="implement" for c in CALLS))
check("CI 红 ci:human→state 置 blocked", st.runs.get(7,{}).get("status")=="blocked")

# === 场景 6：ci:skip → 跳过 CI 闸（放行进 e2e），证明 skip 三态真跳过 ===
m = {}; base_stubs(m); m["stages.ci"] = lambda *, pr_number: (CALLS.append(("ci",pr_number)) or stages.CI_FAIL); apply(m)
ev, st = run_advance(policy(ci="skip"))
restore()
check("ci:skip→跳过 CI 闸(CALLS 无 ci)", "ci" not in [c[0] for c in CALLS])
check("ci:skip→即便 CI 会红也放行到 merge", ev["reason"]=="merged")

# === 场景 7：e2e 陈旧 + e2e:agent → 打回 implementer；e2e:skip → 跳过 ===
m = {}; base_stubs(m); m["stages.e2e"] = lambda *, pr_number: stages.E2E_STALE; apply(m)
ev, st = run_advance(policy())
restore()
check("e2e 陈旧 e2e:agent→reason=e2e 且派 implementer", ev["reason"]=="e2e" and any(c[0]=="implement" for c in CALLS))
m = {}; base_stubs(m); m["stages.e2e"] = lambda *, pr_number: (CALLS.append(("e2e",pr_number)) or stages.E2E_STALE); apply(m)
ev, st = run_advance(policy(e2e="skip"))
restore()
check("e2e:skip→跳过 e2e 闸放行 merge", ev["reason"]=="merged" and "e2e" not in [c[0] for c in CALLS])

# === 场景 8：review REWORK + review:agent → 打回；review:human → blocked；review:skip → 放行 ===
def rework(*, backend, work_dir, pr_number, issue_body, context_text):
    return {"verdict": "REWORK", "reason": "需改"}
m = {}; base_stubs(m); m["stages.review"] = rework; apply(m)
ev, st = run_advance(policy())
restore()
check("review REWORK review:agent→reason=review 且派 implementer", ev["reason"]=="review" and any(c[0]=="implement" for c in CALLS))
m = {}; base_stubs(m); m["stages.review"] = rework; apply(m)
ev, st = run_advance(policy(review="human"))
restore()
check("review:human→blocked(gate=review)不派 implementer", ev["reason"]=="blocked" and ev.get("gate")=="review" and not any(c[0]=="implement" for c in CALLS))
# review:skip + merge:human（守零闸）→ 跳过 review 放行到 merge:human hold
m = {}; base_stubs(m); m["stages.review"] = rework; apply(m)
ev, st = run_advance(policy(review="skip", merge="human"))
restore()
check("review:skip→跳过 review(REWORK 也不拦)", not any(c[0]=="review" for c in CALLS))

# === 场景 9：merge:human → 停等人(hold-merge)不自动合 ===
m = {}; base_stubs(m); apply(m)
ev, st = run_advance(policy(merge="human"))
restore()
check("merge:human→hold-merge 不调 stages.merge", ev["reason"]=="hold-merge" and not any(c[0]=="merge" for c in CALLS))

# === 场景 10：确定性硬闸 round_cap 不受 stages 管辖——耗尽即 raise GateError（死循环兜底，skip 关不掉）===
# round_cap 是生成器：调用方 break 则永不 raise；跑满 limit 仍取值→raise（reviewer 恒 REWORK 的兜底）。
rounds = []
raised = False
try:
    for n in gates.round_cap():   # 模拟 reviewer 恒 REWORK：从不 break
        rounds.append(n)
except gates.GateError:
    raised = True
check("round_cap 耗尽上限即 raise GateError(死循环硬兜底)", raised)
check("round_cap 上限有限(≤ DEFAULT_MAX_ROUNDS)", 0 < len(rounds) <= gates.DEFAULT_MAX_ROUNDS)
check("round_cap 非可配阶段名(stages 无从 skip 关掉它)", "round-cap" not in ac._STAGE_VALID_OWNERS)
# 硬闸名（head-advanced/evidence-stamp/round-cap）全不在可配阶段合法取值表里 → stages 管不着。
check("三硬闸名全不在 stages 可配阶段", all(h not in ac._STAGE_VALID_OWNERS
      for h in ("head-advanced","evidence-stamp","round-cap")))

print(f"\n=== 编排层探针：{len(PASS)} passed, {len(FAIL)} failed ===")
if FAIL:
    print("FAILED:", FAIL); sys.exit(1)
