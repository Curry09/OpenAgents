#!/usr/bin/env bash
# Spec-0058/T1-T2 端到端测试启动脚本：needs-human 死锁自愈 —— 人类越水位线回复即撤 label、复位续跑。
#
# 证明架构契约在离线确定性链路上成立（intent，见 spec §e2e）：
#   - 反复调 run_vigil(once=True)，一次一个 tick（生产代码 `_consider` / `_sense` / `_classify` / `_unblock_if_replied`
#     全是原件，被替换的只有**外部世界**：假 GitHub 内存世界 + 按剧本行事的假 agent）；
#   - 解挂支：一个挂 needs-human 的 PR，评论流最后一条为**无签名**人类评论（越过 park 签名理由评论的水位线）
#     → 一 tick 内 `_unblock_if_replied` 调 remove_label 撤 needs-human，`_classify` 当轮从头重判落②reply、
#     入队并叫 replier（subject 从 TERMINAL 复位为可推进态、能走到后续闸）；
#   - 对照支：另一个挂 needs-human 的 PR，最新评论为**我方签名** → 不调 remove_label、保持 TERMINAL、零 agent
#     调用（防自触发 + 幂等：park 后无人回复不解挂）。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯后端编排**（form=cli），无 product-facing 前端可导航；已自检
# 工具列表：无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，沿用离线确定性测法（假 GitHub + 假 agent 的
# tick 级状态机断言 + 契约单测）。不触真实 LLM。
#
# 用法：
#   bash scripts/e2e-spec-0058-needs-human-reply-unblock.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] 解挂路径 + 分支表 + 生产者契约单测"
uv run --extra dev pytest -q \
  tests/test_recipe_vigil.py

echo
echo "==> [3/4] spec 校验 + 生成物无漂移"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/4] 活体走查：needs-human + 越水位线人类回复 → 一 tick 撤 label 复位续跑；仅我方签名 → 保持 TERMINAL"
uv run --extra dev python - <<'PY'
"""Spec-0058 §e2e 的可执行版：假 GitHub（内存）+ 假 agent（脚本化）+ 真 vigil（一字不改）。

被替换的只有**外部世界**：GitHub 读写（`utils.github`）、`utils.identity` 的签名回帖、以及 `_act` 里那个真
agent（换成一个按剧本行事的假 replier，它照样只能通过 GitHub 说话）。`_sense` / `_classify` /
`_unblock_if_replied` / `_consider` / 队列 / `_reconcile` / 生产者全是**生产代码原件**。
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

# UNBLK = 挂 needs-human 且最新评论是人发的（越水位线）；PARKED = 挂 needs-human 但最新评论是我方签名。
UNBLK, PARKED = 12, 13
AGENT = "oa-e2e"
CLOCK = [datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)]


def now():
    return CLOCK[0]


def stamp():
    return now().isoformat().replace("+00:00", "Z")


# ------------------------------------------------------------------------------------------------
# 假 GitHub：一个可变的内存世界。agent 与守夜都只能通过它交谈（真实拓扑：GitHub 是唯一共享真相）。
# ------------------------------------------------------------------------------------------------
class Hub:
    def __init__(self):
        # 两个裸 PR，都挂着 needs-human。UNBLK 的评论流最后一条是人写的无签名评论（越过 park 水位线）；
        # PARKED 的最后一条是我方**签名**的 park 理由评论（无人越水位线说话）。
        self.prs = {
            UNBLK: {
                "labels": {"needs-human"},
                "merged": False,
                "comments": [
                    (identity.sign(body="⏸ 需求有歧义，交人。", agent_id=AGENT), "2026-07-14T11:00:00Z"),
                    ("澄清了：按方案 B 做，继续。", "2026-07-14T11:30:00Z"),  # 人越水位线回复（无签名）
                ],
            },
            PARKED: {
                "labels": {"needs-human"},
                "merged": False,
                "comments": [
                    (identity.sign(body="⏸ CI 是上游 flaky，交人。", agent_id=AGENT), "2026-07-14T11:00:00Z"),
                ],
            },
        }

    def head_of(self, pr_number):
        return f"{pr_number}{'a' * 37}"


HUB = Hub()
ACTS = []  # 假 agent 每被叫起一次记一笔 —— 「解挂后落②reply」「对照零调用」都靠它断言
REMOVED = []  # remove_label 每被调一次记 (pr_number, name) —— 「撤 needs-human」的直接证据


def fake_pr_snapshot(*, pr_number):
    # 全绿快照：解挂后先落②reply（人有新话，先于一切），reply 后再沿 e2e→review→merge 走到后续闸。
    pr = HUB.prs[pr_number]
    return github.PRSnapshot(
        number=pr_number,
        state="MERGED" if pr["merged"] else "OPEN",
        head_sha=HUB.head_of(pr_number),
        labels=tuple(sorted(pr["labels"])),
        mergeable="MERGEABLE",
        merge_state_status="CLEAN",
        head_pushed_at=stamp(),
    )


def fake_check_snapshot(*, pr_number):
    return github.CheckSnapshot("SUCCESS", 3, stamp())


def fake_list_comments(*, pr_number):
    return [
        github.Comment(index, "bot", body, at)
        for index, (body, at) in enumerate(HUB.prs[pr_number]["comments"])
    ]


def fake_post_comment(*, pr_number, body):
    HUB.prs[pr_number]["comments"].append((body, stamp()))


def fake_remove_label(*, pr_number, name):
    REMOVED.append((pr_number, name))
    HUB.prs[pr_number]["labels"].discard(name)


def fake_post_signed_comment(*, pr_number, body, agent_id):
    fake_post_comment(pr_number=pr_number, body=identity.sign(body=body, agent_id=agent_id or "oa"))


for name, impl in {
    "pr_snapshot": fake_pr_snapshot,
    "check_snapshot": fake_check_snapshot,
    "list_comments": fake_list_comments,
    "post_comment": fake_post_comment,
    "remove_label": fake_remove_label,
    "ensure_label": lambda *, name, description="": None,
}.items():
    setattr(github, name, impl)
identity.post_signed_comment = fake_post_signed_comment


# ------------------------------------------------------------------------------------------------
# 假 agent：`_act` 的替身。它只能改 GitHub（reply 盖一条签名回帖）——路由仍是生产代码的分支表。
# ------------------------------------------------------------------------------------------------
def fake_act(*, backend, state, work_dir, config, observed, verdict, agent_id, now, lock_fd):
    facts = observed.facts
    ACTS.append((facts.subject, verdict.action))
    pr = HUB.prs[facts.pr_number]
    if verdict.action == vigil._ACT_REPLY:
        fake_post_signed_comment(pr_number=facts.pr_number, body="收到，按方案 B 继续。", agent_id=agent_id)
        return "已回应人的评论并推进"
    if verdict.action == vigil._ACT_E2E:  # 解挂后保守重进流水线：补 e2e 证据溯源戳
        fake_post_signed_comment(
            pr_number=facts.pr_number,
            body=f"{vigil._E2E_MARKER}{facts.head_sha} -->\n✅ e2e 通过",
            agent_id=agent_id,
        )
        return "e2e 通过"
    if verdict.action == vigil._ACT_REVIEW_OR_FIX:  # 落 review-approved:<当前 head sha7> 裁决
        pr["labels"].add(f"{vigil._LABEL_REVIEW_APPROVED_PREFIX}{facts.head_sha[:7]}")
        return "review 通过"
    if verdict.action == vigil._ACT_MERGE:  # 全绿 + 已审 → 合并（走到最后一道闸）
        pr["merged"] = True
        return "已合并"
    raise AssertionError(f"本走查不该走到这一支：{verdict.action}")


vigil._act = fake_act

CONFIG = agent_config.AgentConfig(
    version=1,
    agents=agent_config.AgentPolicy(backends={}),
    stages=agent_config.StagePolicy(owners={}),
    release=agent_config.ReleasePolicy(),
    interval=1,
    base="main",
    labels=["openagents"],
    repos=[],
)
# 裸 PR 走执行面，不经准入面；直接把两个 subject 喂给生产者（`_intake` 无关，置空）。
vigil._subjects = lambda *, config: [f"pr:{UNBLK}", f"pr:{PARKED}"]
vigil._intake = lambda **kw: None

WORK = Path(tempfile.mkdtemp(prefix="oa-0058-e2e-"))
STATE = RuntimeState(path=WORK / "runtime-state.json")


def run_tick():
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        vigil.run_vigil(
            backend=None,
            state=STATE,
            work_dir=WORK,
            config=CONFIG,
            once=True,
            concurrency=1,
            agent_id=AGENT,
            now_fn=now,
        )
    return buffer.getvalue()


def check(label, condition, detail=""):
    if not condition:
        print(f"✗ {label}{(' —— ' + detail) if detail else ''}", file=sys.stdout)
        sys.exit(1)
    print(f"  ✓ {label}")


# ---- t0：一 tick 内 UNBLK 撤 label 复位续跑（②reply）；PARKED 保持 TERMINAL（防自触发）----------
logs = run_tick()

check(
    "解挂支：越水位线人类回复 → remove_label 撤掉 UNBLK 的 needs-human",
    (UNBLK, "needs-human") in REMOVED and "needs-human" not in HUB.prs[UNBLK]["labels"],
    str(REMOVED),
)
check(
    "解挂支：同 tick `_classify` 从头重判落②reply → 叫 replier（复位为可推进态）",
    (f"pr:{UNBLK}", vigil._ACT_REPLY) in ACTS,
    str(ACTS),
)
check(
    "解挂支：复位后保守重进流水线 reply→e2e→review→merge，走到最后一道闸（merged）",
    [action for subject, action in ACTS if subject == f"pr:{UNBLK}"]
    == [vigil._ACT_REPLY, vigil._ACT_E2E, vigil._ACT_REVIEW_OR_FIX, vigil._ACT_MERGE]
    and HUB.prs[UNBLK]["merged"],
    str(ACTS),
)
check(
    "对照支：PARKED 最新评论为我方签名 → 不撤 label（防自触发 + 幂等：park 后无人回复不解挂）",
    (PARKED, "needs-human") not in REMOVED and "needs-human" in HUB.prs[PARKED]["labels"],
    str(REMOVED),
)
check(
    "对照支：PARKED 保持 TERMINAL → 零 agent 调用",
    not [subject for subject, _ in ACTS if subject == f"pr:{PARKED}"],
    str(ACTS),
)

# ---- t1：UNBLK 被 replier 回帖后，最新评论变回我方签名 → 幂等，不再重撤 --------------------------
CLOCK[0] = CLOCK[0] + timedelta(seconds=60)
REMOVED.clear()
ACTS.clear()
# 人为再挂一次 needs-human（模拟看门狗/agent 又打），但此刻最新评论是上一轮 replier 的签名回帖：
HUB.prs[UNBLK]["labels"].add("needs-human")
run_tick()
check(
    "幂等：撤一次后最新评论回落我方签名 → 下一 tick 不再重撤 needs-human",
    (UNBLK, "needs-human") not in REMOVED,
    str(REMOVED),
)

print("✓ Spec-0058 活体走查通过（解挂支复位续跑 / 对照支保持 TERMINAL / 幂等不重撤）")
PY

echo
echo "✅ Spec-0058 离线 e2e 全绿"
