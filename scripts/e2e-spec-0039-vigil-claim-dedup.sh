#!/usr/bin/env bash
# Spec-0039/T4 端到端成果测试启动脚本：vigil 多后端并发派单去重——「已派发」认领标签。
# 把「两后端同时抢同一新 issue」从『各建分支/各开 PR 撞车』压到『恰一个后端派单』，
# 并用标签事件时戳做过期回收兜底僵尸认领。
#
# 本脚本有两条**互斥**的成果路径，运行时显式 echo 当前跑的是哪一条（避免「离线通过」被误读
# 成「真实链路通过」）：
#
#   [LIVE]（OA_E2E_LIVE=1 且 `gh auth status` 通过）—— **真端到端、打真实 gh/git**：
#     `gh repo create` 建一次性 scratch 私有仓库 → 真开一个带 `openagents` 标签的 issue →
#     两份独立 State 各跑一次**真实** `discover_and_dispatch`（A 用慢起草后端在真实 worktree 里
#     坐实认领窗口，B 在窗口内到达）。它真正触达**只能靠 e2e 验的集成路径**：
#       · 真实 `gh issue edit --add/remove-label`（issue_stamp_label / issue_remove_label）
#       · 真实 `gh api repos/{owner}/{repo}/issues/N/timeline --paginate --slurp`（认领龄，含
#         gh 版本兼容 / {owner}/{repo} 占位替换 / 分页摊平）——过期回收子用例把 T 调小实打此路径
#       · 真实远端分支探测 `git ls-remote --heads origin openagents/issue-N`
#       · 真实 `gh pr create --draft` / `gh pr list`（远端 draft PR 恰一个）
#     断言全部对**真实远端事实**（`git ls-remote` 的分支、`gh pr list` 的 PR、`gh issue view`
#     的标签），不是内存桩。跑完删除 scratch 仓库（best-effort）。
#
#   [OFFLINE]（默认 / 无 gh auth）—— **离线降级、确定性、不触网**：ruff + pytest 全套 + 一次
#     内存版竞态成果演示。**它不触达上面任何真实 gh/git 集成路径**（用内存桩替代），仅用于无
#     gh auth 环境下的确定性回归与成果看板产出；脚本会显式打印「未打真实 gh/git」的告示。
#
# 两条路径都会把 A/B 两块成果看板渲染到 ${OA_E2E_BOARD_DIR:-/tmp/oa-e2e-0039}/{A,B}/board.html，
# 供评审方用浏览器 MCP（Playwright / chrome-devtools）按 Spec-0039 步骤 4 做 navigate + snapshot +
# take_screenshot + console/network 断言（A 看板有 issue#N 行、B 看板无、无 console/network 报错）；
# 确无浏览器 MCP 时才降级为下方脚本内的 HTML 文本 grep，并把降级原因打进输出。
#
# 用法：
#   bash scripts/e2e-spec-0039-vigil-claim-dedup.sh              # 离线降级路径
#   OA_E2E_LIVE=1 bash scripts/e2e-spec-0039-vigil-claim-dedup.sh # 真端到端（需 gh auth）
set -euo pipefail

cd "$(dirname "$0")/.."

BOARD_DIR="${OA_E2E_BOARD_DIR:-/tmp/oa-e2e-0039}"
export OA_E2E_BOARD_DIR="$BOARD_DIR"

echo "==> [1/3] 离线确定性验证（lint + format + 单元/集成测试）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

# --------------------------------------------------------------------------- #
# 路径选择：OA_E2E_LIVE=1 且 gh 已登录 → 真端到端；否则离线降级。
# --------------------------------------------------------------------------- #
LIVE=0
if [ "${OA_E2E_LIVE:-0}" = "1" ]; then
  if gh auth status >/dev/null 2>&1; then
    LIVE=1
  else
    echo
    echo "⚠ OA_E2E_LIVE=1 但 \`gh auth status\` 未通过（无 gh 登录）——无法建 scratch 仓库/打真实 gh。"
    echo "  降级到离线路径。要跑真链路请先 \`gh auth login\`（需 repo + delete_repo scope）。"
  fi
fi

run_offline() {
  echo
  echo "==> [2/3] [OFFLINE] 离线竞态成果演示（内存桩，**不触真实 gh/git**）"
  echo "    说明：本路径用内存版 GitHub 世界替代真实 gh/git，仅作无 gh auth 时的确定性回归与看板产出；"
  echo "    真实 gh issue label / timeline 分页 / git ls-remote / draft PR 等集成路径**未被触达**（需 OA_E2E_LIVE=1）。"
  uv run python - <<'PY'
# Spec-0039/T4[OFFLINE]：复用集成测试的内存世界与竞态骨架，离线驱动一次两后端竞态并渲染看板。
# 明确定位：这是**降级路径**，不代表真实 gh/git 链路已验证（那需 [LIVE] 路径）。
import os
from pathlib import Path
from unittest.mock import patch

from openagents import github, results
from openagents.github import DISPATCH_LABEL
from openagents.state import State
from openagents.vigil import CLAIM_EXPIRY_SECONDS, Vigil
from tests.test_claim_dedup_integration import (
    FakeGitHubWorld,
    RaceOrchestrator,
    RecordingOrchestrator,
)

ISSUE = 42
BOARD_DIR = Path(os.environ["OA_E2E_BOARD_DIR"])
world = FakeGitHubWorld(issues=[(ISSUE, "并发去重", "body")])


def _in_memory(state):
    store = {"runs": [], "cursors": {}}
    state._load = lambda: store
    state._save = lambda *, data: store.update(data)
    return state


state_a = _in_memory(State(path=Path("/tmp/oa-e2e-0039-a")))
state_b = _in_memory(State(path=Path("/tmp/oa-e2e-0039-b")))


def _vigil(*, orchestrator, state):
    return Vigil(orchestrator=orchestrator, messages=object(), state=state, work_dir=Path("/repo"))


with (
    patch.object(github, "list_issues", world.list_issues),
    patch.object(github, "issue_stamp_label", world.issue_stamp_label),
    patch.object(github, "issue_remove_label", world.issue_remove_label),
    patch.object(github, "issue_add_label", world.issue_add_label),
    patch.object(github, "issue_label_age_seconds", world.issue_label_age_seconds),
    patch.object(Vigil, "_remote_branch_exists", lambda self, *, branch: world.branch_exists(branch=branch)),
):
    b_seen = {}

    def b_runs_during_a_drafting():
        labels_now = set(world.issue_labels.get(ISSUE, set()))
        b_disp = _vigil(orchestrator=RecordingOrchestrator(), state=state_b).discover_and_dispatch(
            labels=["openagents"], base="main"
        )
        b_seen["labels"] = labels_now
        b_seen["dispatched"] = b_disp

    orch_a = RaceOrchestrator(world=world, state=state_a, on_draft=b_runs_during_a_drafting)
    a_disp = _vigil(orchestrator=orch_a, state=state_a).discover_and_dispatch(
        labels=["openagents"], base="main"
    )

    assert a_disp == [ISSUE], f"A 应恰派单 issue#{ISSUE}，实际 {a_disp}"
    print(f"  [A 派单] A 判 fresh、认领 issue#{ISSUE} 并起草 → 派单 {a_disp}")
    assert DISPATCH_LABEL in b_seen["labels"], "B 到达时 issue 应带认领标签"
    assert b_seen["dispatched"] == [], f"B 应据认领标签跳过，实际 {b_seen['dispatched']}"
    print(f"  [B 跳过] B 在起草窗口内到达，读到 {DISPATCH_LABEL} 标签 → 跳过（不重复派单）")

    assert world.branches == {f"openagents/issue-{ISSUE}"}, f"应恰一个分支，实际 {world.branches}"
    assert DISPATCH_LABEL not in world.issue_labels.get(ISSUE, set()), "PR 开出后认领标签应已摘"
    print(f"  [去重成果] （内存）恰一个 openagents/issue-{ISSUE} 分支；PR 开出后认领标签已摘")

    # 过期回收子用例：僵尸认领超 T 判 fresh、未超 T 跳过（内存逻辑时钟）。
    world2 = FakeGitHubWorld(issues=[(43, "僵尸认领", "body")])
    state_c = _in_memory(State(path=Path("/tmp/oa-e2e-0039-c")))
    with (
        patch.object(github, "list_issues", world2.list_issues),
        patch.object(github, "issue_label_age_seconds", world2.issue_label_age_seconds),
        patch.object(Vigil, "_remote_branch_exists", lambda self, *, branch: world2.branch_exists(branch=branch)),
        patch.object(github, "issue_stamp_label", world2.issue_stamp_label),
        patch.object(github, "issue_add_label", world2.issue_add_label),
        patch.object(github, "issue_remove_label", world2.issue_remove_label),
    ):
        world2.clock = 0
        github.issue_stamp_label(number=43, name=DISPATCH_LABEL)
        world2.clock = CLAIM_EXPIRY_SECONDS - 1
        d_fresh = _vigil(orchestrator=RecordingOrchestrator(), state=state_c).discover_and_dispatch(
            labels=["openagents"], base="main"
        )
        assert d_fresh == [], "未超 T：应跳过（别人可能仍在慢起草）"
        world2.clock = CLAIM_EXPIRY_SECONDS + 1
        d_recover = _vigil(orchestrator=RecordingOrchestrator(), state=state_c).discover_and_dispatch(
            labels=["openagents"], base="main"
        )
        assert d_recover == [43], "超 T：应判僵尸认领并回收（视同 fresh 派单）"
    print("  [过期回收] 认领龄未超 T 跳过、超 T 判僵尸认领并回收派单（内存逻辑时钟）")

    # 看板成果（理念 8）：渲染 A/B 两块 board.html 到文件，供浏览器 MCP 断言；脚本内做文本 grep 降级。
    for name, state in (("A", state_a), ("B", state_b)):
        out = BOARD_DIR / name / "board.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(results.render(runs=state.all_runs()), encoding="utf-8")
    board_a = (BOARD_DIR / "A" / "board.html").read_text(encoding="utf-8")
    board_b = (BOARD_DIR / "B" / "board.html").read_text(encoding="utf-8")
    assert f"#{ISSUE}" in board_a, "A 看板应有 issue#N 行"
    assert f"#{ISSUE}" not in board_b and "暂无成果记录" in board_b, "B 看板应无 issue#N 行"
    print(f"  [看板成果] 已渲染 {BOARD_DIR}/A/board.html（有 #{ISSUE} 行）与 B/board.html（暂无成果记录）")

print("✓ Spec-0039/T4[OFFLINE] 竞态成果断言全部通过（内存桩，未触真实 gh/git）。")
PY
}

run_live() {
  echo
  echo "==> [2/3] [LIVE] 真端到端：建 scratch 仓库 + 真 issue，两后端并发真实 discover_and_dispatch"
  local ts repo owner tmp clone
  ts="$(date +%Y%m%d%H%M%S)"
  repo="oa-e2e-0039-${ts}-$$"
  owner="$(gh api user --jq .login)"
  tmp="$(mktemp -d)"
  echo "  · gh repo create ${owner}/${repo}（私有、含初始 README 提交、克隆到临时目录）…"
  ( cd "$tmp" && gh repo create "$repo" --private --add-readme --clone \
      --description "Spec-0039/T4 e2e scratch（脚本自动创建/删除）" >/dev/null )
  clone="$tmp/$repo"

  export OA_E2E_REPO="${owner}/${repo}"
  export OA_E2E_CLONE="$clone"

  # 跑完删除 scratch 仓库 + 本地克隆（best-effort；删仓需 delete_repo scope）。
  # shellcheck disable=SC2064
  trap "echo; echo '==> [LIVE] 清理 scratch 仓库 ${owner}/${repo} …'; gh repo delete '${owner}/${repo}' --yes >/dev/null 2>&1 || echo '⚠ 删 scratch 仓库失败（缺 delete_repo scope？请手动删除 ${owner}/${repo}）'; rm -rf '${tmp}' || true" EXIT

  uv run python - <<'PY'
# Spec-0039/T4[LIVE]：对真实 GitHub scratch 仓库跑一次两后端竞态，全程打真实 gh/git。
import json
import os
import subprocess
import threading
import time
from pathlib import Path

from openagents import github, results
from openagents import vigil as vigil_mod
from openagents.backends.base import AgentResult
from openagents.github import DISPATCH_LABEL
from openagents.orchestrator import Orchestrator, OrchestratorError
from openagents.state import State
from openagents.vigil import Vigil

REPO = os.environ["OA_E2E_REPO"]
CLONE = Path(os.environ["OA_E2E_CLONE"])
BOARD_DIR = Path(os.environ["OA_E2E_BOARD_DIR"])
# gh 从 cwd 的 git 远端解析 scratch 仓库；git worktree/ls-remote 也以此为 work_dir。
os.chdir(CLONE)


def _log(msg):
    print(msg, flush=True)


# 1) 自举 4 个流程标签（含 openagents-dispatching）+ 真开主竞态 issue（带 openagents 标签）。
#    过期回收子用例的 issue 延迟到步骤 9 才开——否则 B 在 A 的认领窗口内跑发现段时，会把这个
#    尚未认领的 issue 判成 fresh 并起草（ExplodingBackend 触发），污染「B 应恰跳过、零派单」断言。
_log("  · ensure_prerequisites（真实 gh label create，自举含 openagents-dispatching）…")
github.ensure_prerequisites()
race_issue = github.create_issue(title="并发去重 e2e", body="两后端抢我", labels=["openagents"])
ISSUE = race_issue.number
_log(f"  · 真 issue #{ISSUE}（主竞态）已开，带 openagents 标签")


class SlowDraftBackend:
    """真起草后端的占位：写一个最小 spec 文件（让 commit/push 有内容），并阻塞坐实认领窗口。

    Spec-0039/T4 scope 明写 A「用慢起草后端坐实窗口」——LLM 起草被替成确定性慢桩，但**其外围的
    真实认领打标 / worktree / push / draft PR / 摘标签全部照跑真实 gh/git**（这正是 e2e 要验的）。
    """

    name = "slow-draft-e2e"

    def __init__(self, *, release):
        self._release = release

    def run(self, *, work_dir, task, context):
        specs = Path(work_dir) / "docs" / "specs"
        specs.mkdir(parents=True, exist_ok=True)
        (specs / f"9999-e2e-live-{ISSUE}.md").write_text(
            f"# 9999 · e2e live draft for issue #{ISSUE}\n\n（Spec-0039/T4 e2e 慢起草桩产物）\n",
            encoding="utf-8",
        )
        # 坐实认领窗口：阻塞到主线程放行（B 已在窗口内跑完），最多等 120s 防挂死。
        self._release.wait(timeout=120)
        return AgentResult(changed=True, summary="e2e live slow draft")


class ExplodingBackend:
    """B 的后端：B 理应被认领闸拦下、绝不进 start_rfc；若被调起即抛，暴露重复派单回归。"""

    name = "b-should-never-draft"

    def run(self, *, work_dir, task, context):
        raise AssertionError("B 不应起草：去重认领闸未拦住 B（重复派单回归）")


class RecordingOrchestrator:
    """过期回收子用例用：只记录 start_rfc 调用、不动真实 git/gh（只关心 fresh/None 归类）。"""

    def __init__(self):
        self.started = []

    def start_rfc(self, *, issue_number, base, resume=False):
        self.started.append(issue_number)
        return None


state_a = State(path=CLONE / ".openagents" / "state-A.json")
state_b = State(path=CLONE / ".openagents" / "state-B.json")
release = threading.Event()
orch_a = Orchestrator(
    backend=SlowDraftBackend(release=release), state=state_a, work_dir=CLONE, agent_id="e2e-A"
)
vigil_a = Vigil(orchestrator=orch_a, messages=object(), state=state_a, work_dir=CLONE)
orch_b = Orchestrator(
    backend=ExplodingBackend(), state=state_b, work_dir=CLONE, agent_id="e2e-B"
)
vigil_b = Vigil(orchestrator=orch_b, messages=object(), state=state_b, work_dir=CLONE)

# 2) A 在后台线程跑真实 discover_and_dispatch（真认领→真起草窗口→真 push→真 draft PR→真摘标签）。
a_result = {}


def run_a():
    try:
        a_result["dispatched"] = vigil_a.discover_and_dispatch(labels=["openagents"], base="main")
    except BaseException as exc:  # noqa: BLE001 —— 线程内异常带回主线程断言
        a_result["error"] = exc


ta = threading.Thread(target=run_a, name="vigil-A")
ta.start()

# 3) 轮询真实 issue，直到 A 打上认领标签（认领窗口打开）——证明认领走了真实 gh issue edit。
_log("  · 等 A 认领（真实 gh issue edit --add-label openagents-dispatching）…")
deadline = time.monotonic() + 90
while DISPATCH_LABEL not in github.get_issue(number=ISSUE).labels:
    if "error" in a_result:
        raise a_result["error"]
    if time.monotonic() > deadline:
        release.set()
        raise SystemExit(f"A 未在 90s 内认领 issue #{ISSUE}（真实 gh 链路异常）")
    time.sleep(1.0)
_log(f"  [A 认领] 真实 issue #{ISSUE} 已带 {DISPATCH_LABEL} 标签（gh 打标成功）")

# 4) 认领窗口内跑 B 的真实发现段：真 list_issues + 真 ls-remote（此刻 A 未推分支）+ 真读认领标签 → 跳过。
b_dispatched = vigil_b.discover_and_dispatch(labels=["openagents"], base="main")
assert b_dispatched == [], f"B 应据真实认领标签 + 真 ls-remote 跳过，实际 {b_dispatched}"
_log(f"  [B 跳过] B 在窗口内到达，真读到 {DISPATCH_LABEL} + 真 ls-remote 无分支 → 跳过（不重复派单）")

# 5) 放行 A 完成起草→真 push→真 draft PR→真摘认领标签。
release.set()
ta.join(timeout=180)
if "error" in a_result:
    raise a_result["error"]
assert not ta.is_alive(), "A 起草线程未在 180s 内结束"
assert a_result.get("dispatched") == [ISSUE], f"A 应恰派单 issue #{ISSUE}，实际 {a_result.get('dispatched')}"
_log(f"  [A 派单] A 真实起草→push→开 draft PR→摘标签，派单 {a_result['dispatched']}")

# 6) 真实远端断言（证据驱动，理念 7）：git ls-remote 的分支恰一个；gh pr list 的 draft PR 恰一个。
branch = f"openagents/issue-{ISSUE}"
ls = subprocess.run(
    ["git", "-C", str(CLONE), "ls-remote", "--heads", "origin", branch],
    capture_output=True,
    text=True,
)
remote_branches = [line for line in ls.stdout.splitlines() if line.strip()]
assert len(remote_branches) == 1, f"远端应恰一个 {branch} 分支，实际 {remote_branches}"
_log(f"  [去重成果·分支] 真实 git ls-remote：远端恰一个 {branch} 分支")

pr_json = subprocess.run(
    ["gh", "pr", "list", "--state", "open", "--json", "number,headRefName,isDraft"],
    capture_output=True,
    text=True,
    check=True,
)
prs = [p for p in json.loads(pr_json.stdout or "[]") if p.get("headRefName") == branch]
assert len(prs) == 1, f"远端应恰一个 {branch} 的 PR，实际 {prs}"
assert prs[0].get("isDraft") is True, f"应为 draft PR，实际 {prs[0]}"
_log(f"  [去重成果·PR] 真实 gh pr list：远端恰一个 {branch} 的 draft PR（#{prs[0]['number']}）")

# 7) 认领标签生命周期：PR 开出后真实 issue 上认领标签已摘。
after = github.get_issue(number=ISSUE).labels
assert DISPATCH_LABEL not in after, f"draft PR 开出后认领标签应已摘，实际 {after}"
_log(f"  [认领生命周期] 真实 gh issue view：#{ISSUE} 认领标签已摘（打→摘闭环）")

# 8) B 侧 state 无该 issue run；A 侧有。
assert [r.issue_number for r in state_a.all_runs()] == [ISSUE], "A 的 state 应恰有 issue#N 的 run"
assert state_b.all_runs() == [], "B 的 state 应无任何 run（B 全程跳过）"
_log("  [State] A 的 state 有 issue#N run、B 的 state 空（一个 issue 只被一个后端领取）")

# 9) 过期回收子用例——**真实打认领标签 + 真实 timeline 分页 API 读认领龄**；把 T 调小实打过期路径。
#    此刻主竞态已收尾，才开这个 issue（见步骤 1 说明）：给它打认领标签但**不建分支**，模拟「领了没人干」。
expiry_issue = github.create_issue(title="过期回收 e2e", body="僵尸认领", labels=["openagents"])
MISS = expiry_issue.number
_log(f"  · 真 issue #{MISS}（过期回收）已开，带 openagents 标签")
_log(f"  · 过期回收：真 gh 给 #{MISS} 打认领标签、不建分支，真 timeline API 读龄（T 调小到 8s）…")
vigil_mod.CLAIM_EXPIRY_SECONDS = 8  # 单处可配的过期阈值（spec Unresolved）——e2e 调小以实打真实过期
github.issue_stamp_label(number=MISS, name=DISPATCH_LABEL)  # 真实 gh issue edit
vigil_e = Vigil(
    orchestrator=RecordingOrchestrator(), messages=object(), state=state_b, work_dir=CLONE
)
# 未超 T：真实 issue_label_age_seconds（真 timeline --paginate --slurp）读到龄 < 8 → 跳过。
d_fresh = vigil_e.discover_and_dispatch(labels=["openagents"], base="main")
assert MISS not in d_fresh, f"未超 T：#{MISS} 应跳过（别人可能仍在慢起草），实际 {d_fresh}"
_log(f"  [过期回收·未超T] 真 timeline API 读龄<8s → #{MISS} 跳过")
# 超 T：等过阈值后重扫，真 timeline API 读到龄 > 8 → 判僵尸认领回收（视同 fresh 派单）。
time.sleep(11)
vigil_e2 = Vigil(
    orchestrator=RecordingOrchestrator(), messages=object(), state=state_b, work_dir=CLONE
)
d_recover = vigil_e2.discover_and_dispatch(labels=["openagents"], base="main")
assert MISS in d_recover, f"超 T：#{MISS} 应判僵尸认领并回收（fresh），实际 {d_recover}"
_log(f"  [过期回收·超T] 真 timeline API 读龄>8s → #{MISS} 判僵尸认领并回收派单")

# 10) 渲染 A/B 两块 board.html 到文件，供浏览器 MCP 断言；脚本内做文本 grep 降级。
for name, state in (("A", state_a), ("B", state_b)):
    out = BOARD_DIR / name / "board.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(results.render(runs=state.all_runs()), encoding="utf-8")
board_a = (BOARD_DIR / "A" / "board.html").read_text(encoding="utf-8")
board_b = (BOARD_DIR / "B" / "board.html").read_text(encoding="utf-8")
assert f"#{ISSUE}" in board_a, "A 看板应有 issue#N 行"
assert f"#{ISSUE}" not in board_b, "B 看板应无 issue#N 行（B 全程跳过）"
_log(f"  [看板成果] 已渲染 {BOARD_DIR}/A/board.html（有 #{ISSUE} 行）与 B/board.html")

print("✓ Spec-0039/T4[LIVE] 真端到端断言全部通过：真实 gh/git 下两后端抢同一 issue → 恰一个派单 "
      "+ 认领标签打/摘闭环 + 真 timeline 过期回收 + 看板成果。", flush=True)
PY
}

if [ "$LIVE" = "1" ]; then
  run_live
  MODE="LIVE（真实 gh/git）"
else
  run_offline
  MODE="OFFLINE（内存桩，未触真实 gh/git）"
fi

echo
echo "==> [3/3] 成果看板已渲染，供浏览器 MCP 按 Spec-0039 步骤 4 断言："
echo "    A 看板：file://${BOARD_DIR}/A/board.html   （应有 issue#N 行）"
echo "    B 看板：file://${BOARD_DIR}/B/board.html   （应无 issue#N 行 / 暂无成果记录）"
echo "    评审方具备 Playwright / chrome-devtools MCP 时：navigate 两块看板 → snapshot + take_screenshot"
echo "    → list_console_messages / list_network_requests 断言无报错；确无浏览器 MCP 才降级为上方脚本内 HTML 文本 grep。"
echo
echo "✓ Spec-0039/T4 端到端演示完成 —— 本次跑的是：${MODE}。"
