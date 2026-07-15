#!/usr/bin/env bash
# Spec-0016 端到端测试启动脚本：issue 页面新增评论 → agent 感知 → 派 replier → 带签名回帖到该 issue。
# 把「新人类评论→agent 签名回复」闭环从 PR 扩展到 issue 页（issue #149：只要回复、不要解决）。
#
# 形态说明（evidence 分层，理念 8）：本组是**纯后端编排**（vigil reconcile 分支②的 issue 支），无
# product-facing 前端可导航；已自检工具列表：无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，沿用
# 离线确定性测法（假 GitHub + 假 agent 的 tick 级状态机断言，承 Spec-0061/0065 风格）。真实自主环冒烟
# （`oa vigil` 在真仓 issue 上追加评论后收到署名回复）作为成果验收在 Phase-3 人验/runbook 记录，不塞进本脚本。
#
# 用法：
#   bash scripts/e2e-spec-0016-issue-comment-agent-reply.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] 离线确定性验证（lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] identity/state/replier/context/vigil/cli issue 回复契约单测"
uv run --extra dev pytest -q \
  tests/test_identity_issue_reply.py \
  tests/test_runtime_state_issue_cursor.py \
  tests/test_agents_replier_issue.py \
  tests/test_runtime_context_issue_reply.py \
  tests/test_recipe_vigil_issue_reply.py \
  tests/test_cli_issue_reply.py

echo
echo "==> [3/4] spec 校验 + 生成物无漂移"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/4] 闭环走查：ready 无-PR issue 上有新人类评论 → 派 replier → 签名回帖 → 不自触发"
uv run --extra dev python - <<'PY'
"""Spec-0016 闭环的可执行版：假 GitHub（内存）+ 假 backend（脚本化 replier 输出）+ 真 vigil（一字不改）。

被替换的只有**外部世界**：GitHub 读写（issue 评论）与那个真 agent 子进程（换成一个照剧本吐 JSON 的假
backend，它照样只能通过 GitHub 说话）。`_sense` / `_classify` / `_do_reply` / `_do_reply_issue` /
identity 签名读写全是**生产代码原件**。
"""

import sys
import tempfile
import types
from pathlib import Path

from openagents.recipes import vigil
from openagents.runtime.state import RuntimeState
from openagents.utils import github, identity

ISSUE = 149
AGENT_ID = "oa-e2e"
CLOCK = ["2026-07-15T12:00:00Z"]


def tick_stamp(suffix):
    return f"2026-07-15T12:{suffix}Z"


# ---------------------------------------------------------------------------------------------
# 假 GitHub：一个 ready、尚无 PR 的 issue，其评论流可追加。agent 与守夜都只能通过它交谈。
# ---------------------------------------------------------------------------------------------
class Hub:
    def __init__(self):
        self.labels = {"openagents", "ready"}  # 已准入
        self.comments = []  # list[(body, created_at)]
        self._machine_seq = 30  # 机器回帖用的单调递增分钟戳（避免同秒并列打乱 max 取最新）

    def add_comment(self, *, body, created_at):
        self.comments.append((body, created_at))

    def next_machine_stamp(self):
        self._machine_seq += 1
        return f"2026-07-15T12:{self._machine_seq:02d}:00Z"


HUB = Hub()


def fake_get_issue(*, number):
    return github.Issue(ISSUE, "支持 codex", "让 openagents 兼容 codex 后端", sorted(HUB.labels))


def fake_list_blocked_by(*, number):
    return []


def fake_pr_for_branch(*, branch):
    return None  # 尚无 PR


def fake_list_issue_comments(*, number):
    return [
        github.Comment(id=f"c{i}", author="alice", body=body, created_at=at,
                       author_association="NONE" if identity.parse_agent_id(body=body) is None else "OWNER")
        for i, (body, at) in enumerate(HUB.comments)
    ]


def fake_issue_comment(*, number, body):
    HUB.add_comment(body=body, created_at=HUB.next_machine_stamp())


for name, impl in {
    "get_issue": fake_get_issue,
    "list_blocked_by": fake_list_blocked_by,
    "pr_for_branch": fake_pr_for_branch,
    "list_issue_comments": fake_list_issue_comments,
    "issue_comment": fake_issue_comment,
}.items():
    setattr(github, name, impl)


# 假 backend：replier 被派时吐一条只答疑的 JSON（末行）。
class FakeBackend:
    def run(self, *, work_dir, task, context):
        assert "只答疑" in task and "不改代码" in task, "issue replier 未用 ISSUE_PROMPT（只答疑不改代码）"
        assert "branch" not in task, "issue replier 提示词混进了 PR 语境的 branch"
        return types.SimpleNamespace(
            summary='{"reply": "收到，我理解成要把后端抽象成可插拔、先接 codex，对吗？", "resolved": false}'
        )


WORK = Path(tempfile.mkdtemp(prefix="oa-0016-e2e-"))
STATE = RuntimeState(path=WORK / "runtime-state.json")


def check(label, condition, detail=""):
    if not condition:
        print(f"✗ {label}{(' —— ' + detail) if detail else ''}")
        sys.exit(1)
    print(f"  ✓ {label}")


# ---- 断言 1：ready 无-PR issue、最新是无签名人类评论 → _sense 判 latest_comment_is_ours=False → reply ----
HUB.add_comment(body="补充：能不能也支持 codex？", created_at=tick_stamp("10:00"))
# _sense 需要 config.stages —— 造一个最小 config（无 skip，纯 agent 面）。
from openagents.utils import agent_config

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
observed = vigil._sense(config=CONFIG, subject=f"issue:{ISSUE}")
facts = observed.facts
check("① ready 无-PR issue：pr_number 为 None（走 issue 支）", facts.pr_number is None)
check("① 最新是无签名人类评论 → latest_comment_is_ours=False", facts.latest_comment_is_ours is False)
verdict = vigil._classify(facts=facts, in_flight=False)
check("① _classify 判 ACTIONABLE:reply（而非 solve）",
      verdict.kind == vigil._ACTIONABLE and verdict.action == vigil._ACT_REPLY,
      f"{verdict.kind}/{verdict.action}")

# ---- 断言 2：_do_reply 派 replier → 经 post_signed_comment_on_issue 落 issue、带本实例签名 ----------
reply = vigil._do_reply(
    backend=FakeBackend(), state=STATE, work_dir=WORK, facts=facts, agent_id=AGENT_ID
)
check("② replier 只答疑地回了一句", "codex" in reply)
latest_body, _ = HUB.comments[-1]
check("② 回复经 issue_comment 落到该 issue（gh issue comment 路径）", "把后端抽象成可插拔" in latest_body)
check("② 回复带本实例签名 <!-- openagents:agent=… -->",
      identity.parse_agent_id(body=latest_body) == AGENT_ID, latest_body)
check("② issue 游标已推到那条人类评论", STATE.get_issue_cursor(number=ISSUE) == tick_stamp("10:00"))

# ---- 断言 3：再跑一 tick —— 最新评论已是我方签名 → latest_comment_is_ours True → 不重复回帖（不自触发）--
count_before = len(HUB.comments)
observed2 = vigil._sense(config=CONFIG, subject=f"issue:{ISSUE}")
check("③ 回帖后最新评论我方签名 → _latest_is_ours True", observed2.facts.latest_comment_is_ours is True)
verdict2 = vigil._classify(facts=observed2.facts, in_flight=False)
check("③ 分支②停火：不再判 reply（落到 solve）", verdict2.action == vigil._ACT_SOLVE)
# 即便直接再调 _do_reply（游标已推过那条人类评论）也不再新增回帖。
vigil._do_reply(backend=FakeBackend(), state=STATE, work_dir=WORK, facts=observed2.facts, agent_id=AGENT_ID)
check("③ 不自触发死循环：游标已过 → 无新人类评论 → 零新增回帖",
      len(HUB.comments) == count_before, f"{len(HUB.comments)} vs {count_before}")

# ---- 断言 4：手动出口 identity.post_signed_comment_on_issue 同样经签名出口落 issue ----------------------
before = len(HUB.comments)
identity.post_signed_comment_on_issue(number=ISSUE, body="运维手动补一句", agent_id="oa-manual")
check("④ 手动出口 post_signed_comment_on_issue 落 issue + 带签名",
      len(HUB.comments) == before + 1
      and identity.parse_agent_id(body=HUB.comments[-1][0]) == "oa-manual")

print("✓ Spec-0016 闭环走查全部通过（感知→reply分类→签名回帖→不自触发→手动出口）")
PY

echo
echo "==> grep 锚点：issue 版原语在册 + reply 分支②的 issue 支接线"

fail() {
  echo "✗ 锚点失败：$1" >&2
  exit 1
}

# 底层 gh 读/写原语已存在、直接复用（github.py 零改动）——issue 版签名读/写只在 identity 上加一层。
grep -q "def new_human_comments_on_issue" openagents/utils/identity.py \
  || fail "identity 缺 new_human_comments_on_issue（issue 版读侧防自触发原语）"
grep -q "def post_signed_comment_on_issue" openagents/utils/identity.py \
  || fail "identity 缺 post_signed_comment_on_issue（issue 版签名回帖出口）"
grep -q "def get_issue_cursor" openagents/runtime/state.py \
  || fail "state 缺 get_issue_cursor（issue 评论游标，独立命名空间）"
grep -q "issue_cursors" openagents/runtime/state.py \
  || fail "state issue 游标未落独立命名空间键 issue_cursors（与 cursors 撞键会重复回帖）"
grep -q "ISSUE_PROMPT" openagents/agents/replier.py \
  || fail "replier 缺 ISSUE_PROMPT（issue 语境提示词，只答疑不改代码）"
grep -q "def for_issue_reply" openagents/runtime/context.py \
  || fail "context 缺 for_issue_reply（issue 回复占位符组装）"
grep -q "_do_reply_issue" openagents/recipes/vigil.py \
  || fail "vigil 缺 _do_reply_issue（reply 分支②的 issue 支分派）"

# ISSUE_PROMPT 必须**无** branch、**无**改代码分支（issue #149：只要回复、不要解决）。
uv run --extra dev python -c "
from openagents.agents import replier
tmpl = replier.ISSUE_PROMPT.template
assert '\$branch' not in tmpl, 'ISSUE_PROMPT 混进了 PR 语境的 \$branch'
assert '只答疑' in tmpl and '不改代码' in tmpl, 'ISSUE_PROMPT 未写明只答疑不改代码'
assert replier.ISSUE_PROMPT is not replier.PROMPT, 'issue/PR 提示词必须分家'
" || fail "ISSUE_PROMPT 语义不符（含 branch / 未写只答疑不改代码 / 与 PR 版未分家）"

# _sense 只在 ready 时才对无-PR issue 激活 latest_comment_is_ours（未 ready 归准入面 admitter）。
grep -q "if _LABEL_READY in labels:" openagents/recipes/vigil.py \
  || fail "vigil _sense 未把 issue reply 激活门控在 ready（未 ready 该归 admitter）"

echo "✓ grep 锚点全部通过：issue 版签名读/写 + 独立游标 + issue 提示词分家 + reply 分支②issue 支 + ready 门控"
echo
echo "✅ Spec-0016 离线 e2e 全绿"
