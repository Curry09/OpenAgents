#!/usr/bin/env bash
# Spec-0054 端到端测试启动脚本：e2e v2——能力感知 + 说明书直喂 + 合并 review（重设计 0040）。
#
# 本组把 e2e 从 0040 的「form 分派 + finalize_runbook 定稿 + 独立证据闸」三层机械脚手架，重设计为：
#   ① 守夜启动 envcheck 扫一遍 → 固化「浏览器能力状态量」ui_capable 进 state.json（只在写测法时读）；
#   ② RFC 的 e2e 段 = intent + prose method（无 form、无精确命令）；RFC 起草/评审据 ui_capable 分流；
#   ③ implement 照常写码；
#   ④ CI 绿后派独立 executor 拿 prose method 直接跑（运行时自检工具，有浏览器就截图），证据落
#      docs/e2e-results/<pr>/，源码指纹（排除证据目录）幂等：源码没变就复用不重跑；
#   ⑤ 现有 review_code 同时判代码 + 证据（reviewer 亲眼看截图），无独立证据闸。
#   收敛：证据 commit 后源码指纹未变 → sticky 复用 PASS + 跳 executor，CI 绿即直接 merge；证据 commit
#   意外把 CI 弄红 → bad_ci_after_e2e 标签 + _block（needs-human + blocked）夯住不空转。
#
# 全程**不触网、不调真实 LLM、不碰真实 gh/git 远端、不装浏览器**：
#   1) 离线确定性验证（默认执行）—— ruff lint/format + pytest 全套，覆盖 T1 能力状态量、T2 spec 段瘦身、
#      T3 executor 重写、T4 reviewer 合并职责、T5 run_e2e 幂等 + 指纹排除证据目录、T6 流水线重排 +
#      bad_ci_after_e2e。
#   2) 离线成果演练（默认执行）—— 用真实 State + 内存 GitHub 世界驱动 _process_coding，以「executor 在
#      review 之前被调 / 源码未变复用不重跑 / bad_ci_after_e2e 走 blocked」这几个可观测成果验证语义（理念 8）。
#   3) 关键不变量 grep 锚点（默认执行）—— 断言代码层反转/瘦身确已落地（executor 无 form、reviewer 判证据、
#      run_e2e 存在、code_fingerprint 排除证据目录、bad_ci 标签）。
#
# 浏览器 e2e：本组交付物是纯后端编排机制（守夜人 poll 循环内部的 e2e 流水线重排），无 product-facing 前端
# 界面可导航；本组自身的 ui 能力路径（executor 真开浏览器截图）在**无浏览器的 CI 环境**下按设计降级、不可
# 在此脚本行使。故成果证据用下面 CLI/pytest 驱动的离线段断言，是此内部行为的正确观测面。
#
# 用法：
#   bash scripts/e2e-spec-0054-e2e-v2-capability-aware.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/3] 离线确定性验证（lint + format + 单元测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/3] 离线成果演练：executor 在 review 前 / 源码未变复用 / bad_ci_after_e2e 走 blocked"
uv run python - <<'PY'
# Spec-0054：真实 State + 内存 GitHub 世界，离线驱动 _process_coding，验证 e2e v2 流水线语义。
from openagents import messages as messages_module
from openagents.executor import ExecutorResult
from openagents.github import CheckStatus, Mergeability
from openagents.hold import NONE as NO_HOLD
from openagents.messages import Messages
from openagents.orchestrator import E2ERunResult
from openagents.reviewer import ReviewDecision
from openagents.state import STATUS_BLOCKED, STATUS_PR_OPEN, RunRecord

AGENT_ID = "agent-e2e-0054"


class _State:
    def __init__(self, record):
        self._runs = [record]
        self.status = []

    def all_runs(self):
        return list(self._runs)

    def update_status(self, *, issue_number, status):
        self.status.append(status)
        self._runs[0].status = status

    def increment_rounds(self, *, issue_number):
        self._runs[0].rounds += 1
        return self._runs[0].rounds

    def increment_review_invalid(self, *, issue_number):
        return 0

    def reset_rounds(self, *, issue_number):
        pass

    def set_block_gate(self, *, issue_number, gate):
        self._runs[0].block_gate = gate

    def set_block_watermark(self, *, issue_number, watermark):
        pass

    def set_code_fingerprint(self, *, issue_number, fingerprint):
        self._runs[0].code_passed_fingerprint = fingerprint


class _Orch:
    def __init__(self, *, e2e_result):
        self.e2e_result = e2e_result
        self.calls = []

    def run_e2e(self, *, pr_number):
        self.calls.append("run_e2e")
        return self.e2e_result

    def review_code(self, *, pr_number):
        self.calls.append("review_code")
        return ReviewDecision(passed=True, feedback="")

    def iterate(self, *, pr_number, reason, detail):
        self.calls.append(f"iterate:{reason}")
        return "s"


def _wire(*, ci="pass", fingerprint="", labels=None, merged=None):
    labels = labels if labels is not None else []
    merged = merged if merged is not None else []
    g = messages_module.github
    for name, fn in {
        "is_merged": lambda *, pr_number: False,
        "is_closed": lambda *, pr_number: False,
        "has_label": lambda *, pr_number, name: False,
        "list_comments": lambda *, pr_number: [],
        "mergeability": lambda *, pr_number: Mergeability(
            mergeable="MERGEABLE", merge_state_status="CLEAN"
        ),
        "check_status": lambda *, pr_number: CheckStatus(state=ci, failed_logs=["boom"]),
        "code_fingerprint": lambda *, pr_number: fingerprint,
        "merge_pr": lambda *, pr_number, method="merge": merged.append(pr_number),
        "add_label": lambda *, pr_number, name: labels.append(name),
        "close_issue": lambda *, number: None,
    }.items():
        setattr(g, name, fn)
    messages_module.identity.post_signed_comment = lambda *, pr_number, body, agent_id: None
    messages_module.identity.new_human_comments = lambda *, pr_number, since: []


def _record(**kw):
    base = dict(
        issue_number=3, branch="b", pr_number=5, pr_url="u", status=STATUS_PR_OPEN, summary=""
    )
    base.update(kw)
    return RunRecord(**base)


# A) executor 在 review 之前：run_e2e 真跑（reused=False）→ 本轮不 review（早退让证据过 CI）。
orch = _Orch(e2e_result=E2ERunResult(reused=False, result=ExecutorResult(outcome="passed", notes="n")))
state = _State(_record())
merged = []
_wire(ci="pass", fingerprint="", merged=merged)
Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)._process_coding(
    record=state.all_runs()[0], hold=NO_HOLD
)
assert orch.calls == ["run_e2e"], f"executor 应在 review 前且真跑后早退，实得 {orch.calls}"
assert merged == [], "真跑当轮不应 merge（等证据过 CI）"
print("  ✓ A: executor 在 review 之前；真跑当轮早退、不 merge")

# B) 源码未变复用：run_e2e reused=True → 继续 review → merge。
orch = _Orch(e2e_result=E2ERunResult(reused=True, result=None))
state = _State(_record())
merged = []
_wire(ci="pass", fingerprint="", merged=merged)
Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)._process_coding(
    record=state.all_runs()[0], hold=NO_HOLD
)
assert orch.calls == ["run_e2e", "review_code"], f"复用应继续 review，实得 {orch.calls}"
assert merged == [5], "复用 + review PASS 应 merge"
print("  ✓ B: run_e2e 复用（源码未变）→ 继续 review → merge")

# C) bad_ci_after_e2e：源码自 e2e 真跑后未变（指纹相同），CI 变红 → blocked + 双标签、不 iterate(ci)。
orch = _Orch(e2e_result=E2ERunResult(reused=True, result=None))
state = _State(_record(e2e_ran_fingerprint="fp-x"))
labels = []
_wire(ci="fail", fingerprint="fp-x", labels=labels)
Messages(orchestrator=orch, state=state, agent_id=AGENT_ID)._process_coding(
    record=state.all_runs()[0], hold=NO_HOLD
)
assert "iterate:ci" not in orch.calls, "bad_ci 不应打回 iterate(ci)"
assert STATUS_BLOCKED in state.status, "bad_ci 应置 blocked 夯住"
assert "bad_ci_after_e2e" in labels, "应打 bad_ci_after_e2e 诊断标签"
print("  ✓ C: 证据 commit 弄红 CI → bad_ci_after_e2e + blocked（不 iterate）")

print("离线成果演练全绿 ✅")
PY

echo
echo "==> [3/3] 关键不变量 grep 锚点"
grep -q "def run_executor" openagents/executor.py
! grep -q "_run_by_form\|OUTCOME_SKIPPED\|_UI_FORM" openagents/executor.py \
  && echo "  ✓ executor 已删 form 分派 / ui-skipped"
grep -q "def run_e2e" openagents/orchestrator.py && echo "  ✓ orchestrator.run_e2e 存在"
! grep -q "def finalize_runbook\|def commit_evidence" openagents/orchestrator.py \
  && echo "  ✓ finalize_runbook / commit_evidence 已退役"
grep -q "exclude_paths" openagents/github.py && echo "  ✓ code_fingerprint 支持排除证据目录"
grep -q "也判运行时行为" openagents/reviewer.py && echo "  ✓ code reviewer 反转为判运行时行为"
grep -q "ui_capable" openagents/reviewer.py && echo "  ✓ RFC 闸据 ui_capable 分流"
grep -q "bad-ci-after-e2e" openagents/messages.py && echo "  ✓ messages 含 bad_ci_after_e2e 挂起"
grep -q "def ui_capable" openagents/envcheck.py && echo "  ✓ envcheck.ui_capable 存在"

echo
echo "全部通过 ✅（Spec-0054 e2e v2）"
