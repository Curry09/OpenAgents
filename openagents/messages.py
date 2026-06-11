"""RFC-0001 T5 + RFC-0005 + RFC-0012: PR 消息机制 + CI 监控，按**阶段**路由 GitHub 事件。

poll 对每个 open 状态的 run 做一次扫描，先判 merge/close，再按 run 所处阶段路由
（RFC-0005 决策 5）。RFC-0012 把两处「等人」的判定换成「调 reviewer 闸 + 自动推进」，
让人的触点收敛到「提 issue」与「promote」：

  1. github.is_merged：已合并 → State 置 done，跳过（决策 8）+ 合并后扇出 rebase（RFC-0009）。
  1b. github.is_closed：关闭未合并 → State 置 closed，跳过（RFC-0006，merged 优先）。
  2. 阶段 rfc-review（PR 为 draft、承载 RFC）—— RFC 评审闸（RFC-0012 决策 1/3）：
     a. 已带 rfc-approved 标签（人/agent 谁打都认，向后兼容）→ Orchestrator.implement。
     b. 否则调 Orchestrator.review_rfc：
        - 全票 PASS → 自动打 rfc-approved → implement（转入 coding）。
        - 非 PASS → rounds++；未超 K → refine_rfc（喂 reviewer 反馈）；超 K → BLOCKED+needs-human。
  3. 阶段 coding（pr-open / iterating）—— 代码评审闸（RFC-0012 决策 1）：
     a. CI 失败 → Orchestrator.iterate(reason="ci")（行为保持，CI 回合不计入 rounds）。
     b. CI 进行中 → 等待（本轮不动）。
     c. CI 全绿 → 调 Orchestrator.review_code：
        - 全票 PASS → github.merge_pr（合入 test）→ DONE → 扇出 rebase 其余 PR。
        - 非 PASS → rounds++；未超 K → iterate(reason="review")；超 K → BLOCKED+needs-human。

卡住兜底（RFC-0012 决策 5）：rounds（每个闸独立计，implement 时清零）达到 MAX_ROUNDS 时
置 STATUS_BLOCKED + 打 needs-human 标签 + **PR 不关**；STATUS_BLOCKED 不在 _OPEN_STATUSES，
下一轮 poll 自动跳过（软挂起），等人据标签介入。

watch：每隔 interval 秒循环调用 poll，无 open PR 或用户中断时退出（决策 6）。

依赖注入：orchestrator（Orchestrator）、state（State）由构造传入；GitHub 操作以模块
函数方式调用（测试里 monkeypatch github.*），time.sleep 同理可 mock。
"""

from __future__ import annotations

import os
import time

from openagents import github, rebase
from openagents.orchestrator import Orchestrator
from openagents.state import (
    BLOCKED_LABEL,
    STATUS_BLOCKED,
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
    State,
)

# 需要继续轮询的状态（决策 8：done 终止，solving 尚未开 PR）。rfc-review 也在轮询范围。
# RFC-0012：blocked（评审超 K 轮挂起）与 closed/done 一样不在此集合，poll 自动跳过。
_OPEN_STATUSES = {STATUS_RFC_REVIEW, STATUS_PR_OPEN, STATUS_ITERATING}

# RFC-0005 决策 4：批准信号——带这个标签即视为 RFC 通过。RFC-0012 决策 3：reviewer 闸
# 全票 PASS 时由 add_label 自动打它，与人工打标签走同一下游路径（向后兼容）。
# RFC-0015：字面量上移至 github（流程标签单一来源），此处改为别名引用，保留
# messages.APPROVAL_LABEL 公共名向后兼容，消除「同一字符串散落三处」的漂移风险。
APPROVAL_LABEL = github.APPROVAL_LABEL

# RFC-0012 决策 6：每个闸的最大评审回合数旋钮——env OPENAGENTS_MAX_ROUNDS，默认 3。
# 模块常量在 import 时定值；测试可 monkeypatch messages.MAX_ROUNDS 覆盖（方法内按全局取值）。
MAX_ROUNDS_ENV = "OPENAGENTS_MAX_ROUNDS"
_DEFAULT_MAX_ROUNDS = 3


def _configured_max_rounds() -> int:
    """读 OPENAGENTS_MAX_ROUNDS；缺省/非法/<1 回落到默认值（至少给一回合迭代机会）。"""
    raw = os.environ.get(MAX_ROUNDS_ENV)
    if not raw:
        return _DEFAULT_MAX_ROUNDS
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_ROUNDS
    return value if value >= 1 else _DEFAULT_MAX_ROUNDS


MAX_ROUNDS = _configured_max_rounds()


class Messages:
    """RFC-0001 T5 + RFC-0005 + RFC-0012：按阶段轮询 PR 的 merge/CI/评审闸，路由回编排层。"""

    def __init__(self, *, orchestrator: Orchestrator, state: State, agent_id: str) -> None:
        self._orchestrator = orchestrator
        self._state = state
        # RFC-0011 决策 7：本实例身份，由 CLI 接线处解析后注入；poll 合并分支时透传给
        # rebase.rebase_open_prs（冲突留言据此盖章、保持 rebase 无状态）。
        self._agent_id = agent_id

    def poll(self) -> list[dict]:
        """RFC-0001 T5：扫描所有 open 状态 run，按 merge → 阶段 路由。

        返回本轮事件列表，每个事件含 pr_number 与 reason（reason ∈ {"merged", "closed",
        "approved", "rfc-pass", "refine", "ci", "review", "blocked"}），便于日志与测试断言。
        """
        events: list[dict] = []
        for record in self._state.all_runs():
            if record.status not in _OPEN_STATUSES:
                continue
            event = self._process_run(record=record)
            if event is not None:
                events.append(event)
        return events

    def watch(self, *, interval: int) -> None:
        """RFC-0001 T5（决策 6）：每隔 interval 秒循环 poll，无 open PR 或中断时退出。"""
        try:
            while self._has_open_pr():
                self.poll()
                if not self._has_open_pr():
                    break
                time.sleep(interval)
        except KeyboardInterrupt:
            return

    def _process_run(self, *, record: RunRecord) -> dict | None:
        """处理单个 open run：merge 优先，其后按阶段（rfc-review / coding）路由。"""
        pr_number = record.pr_number
        # 1. 已合并优先于一切：置 done 并跳过（决策 8）。
        if github.is_merged(pr_number=pr_number):
            self._state.update_status(issue_number=record.issue_number, status=STATUS_DONE)
            # RFC-0017：合进 test（非默认分支）GitHub 不会自动关 issue，由框架显式关——
            # 与 STATUS_DONE「工作落进体验分支即完成」语义一致。close_issue 幂等，多轮 poll
            # 重复命中已合并分支重复调用安全（决策 2）。
            github.close_issue(number=record.issue_number)
            # RFC-0009 决策 1/3：合并即信号——同一 poll 轮内扇出，把最新 base 并入其余
            # open PR（排除刚合并的这个），触发它们 CI 重跑；冲突的 PR 由 rebase 层留言。
            synced = rebase.rebase_open_prs(merged_pr_number=pr_number, agent_id=self._agent_id)
            return {"pr_number": pr_number, "reason": "merged", "synced": synced}

        # 1b. RFC-0006：人主动关闭（未合并）也是终止信号 → 置 closed 并跳过。merged 优先于 closed。
        if github.is_closed(pr_number=pr_number):
            self._state.update_status(issue_number=record.issue_number, status=STATUS_CLOSED)
            return {"pr_number": pr_number, "reason": "closed"}

        # 2. 按阶段路由（决策 5）。
        if record.status == STATUS_RFC_REVIEW:
            return self._process_rfc_review(record=record)
        return self._process_coding(record=record)

    def _process_rfc_review(self, *, record: RunRecord) -> dict | None:
        """RFC 评审闸（RFC-0012 决策 1/3）：标签 / reviewer 全票 PASS → implement；非 PASS → refine 或 BLOCKED。"""
        pr_number = record.pr_number
        # 2a. 已带批准标签（人或上一轮 reviewer 打的）优先：直接转入实现（向后兼容）。
        if github.has_label(pr_number=pr_number, name=APPROVAL_LABEL):
            self._orchestrator.implement(pr_number=pr_number)
            return {"pr_number": pr_number, "reason": "approved"}
        # 2b. 主动调 reviewer 评审 RFC（决策 3：不再等人打标签）。
        decision = self._orchestrator.review_rfc(pr_number=pr_number)
        if decision.passed:
            github.add_label(pr_number=pr_number, name=APPROVAL_LABEL)
            self._orchestrator.implement(pr_number=pr_number)
            return {"pr_number": pr_number, "reason": "rfc-pass"}
        # 非 PASS：回合 +1，未超 K 则按 reviewer 反馈精炼 RFC，超 K 则挂起等人（决策 5）。
        rounds = self._state.increment_rounds(issue_number=record.issue_number)
        if rounds >= MAX_ROUNDS:
            return self._block(record=record, gate="rfc")
        self._orchestrator.refine_rfc(pr_number=pr_number, detail=decision.feedback)
        return {"pr_number": pr_number, "reason": "refine"}

    def _process_coding(self, *, record: RunRecord) -> dict | None:
        """代码评审闸（RFC-0012 决策 1）：CI 失败→iterate(ci)；CI 绿+reviewer PASS→merge；非 PASS→iterate 或 BLOCKED。"""
        pr_number = record.pr_number
        # 3a. CI 失败：以失败日志喂回 agent（决策 11，行为保持——CI 回合不计入 rounds）。
        status = github.check_status(pr_number=pr_number)
        if status.state == "fail":
            detail = "\n".join(status.failed_logs)
            self._orchestrator.iterate(pr_number=pr_number, reason="ci", detail=detail)
            return {"pr_number": pr_number, "reason": "ci"}
        # 3b. CI 进行中：等下一轮（不评审、不动状态）。
        if status.state == "pending":
            return None
        # 3c. CI 全绿 → 调 reviewer 评审代码（决策 1）。
        decision = self._orchestrator.review_code(pr_number=pr_number)
        if decision.passed:
            github.merge_pr(pr_number=pr_number)
            self._state.update_status(issue_number=record.issue_number, status=STATUS_DONE)
            # RFC-0017：合进 test 后显式关 issue（与上方已合并分支同理，幂等容错）。
            github.close_issue(number=record.issue_number)
            synced = rebase.rebase_open_prs(merged_pr_number=pr_number, agent_id=self._agent_id)
            return {"pr_number": pr_number, "reason": "merged", "synced": synced}
        # 非 PASS：回合 +1，未超 K 则按 reviewer 反馈迭代代码，超 K 则挂起等人（决策 5）。
        rounds = self._state.increment_rounds(issue_number=record.issue_number)
        if rounds >= MAX_ROUNDS:
            return self._block(record=record, gate="code")
        self._orchestrator.iterate(pr_number=pr_number, reason="review", detail=decision.feedback)
        return {"pr_number": pr_number, "reason": "review"}

    def _block(self, *, record: RunRecord, gate: str) -> dict:
        """RFC-0012 决策 5：评审超 K 轮 → 置 STATUS_BLOCKED + 打 needs-human + PR 不关。

        STATUS_BLOCKED 不在 _OPEN_STATUSES，下一轮 poll 自动跳过（软挂起）；needs-human
        标签是给人/promote 预检看的「求救」信号。PR 保持 open，等人修完再恢复流转。
        """
        pr_number = record.pr_number
        self._state.update_status(issue_number=record.issue_number, status=STATUS_BLOCKED)
        github.add_label(pr_number=pr_number, name=BLOCKED_LABEL)
        return {"pr_number": pr_number, "reason": "blocked", "gate": gate}

    def _has_open_pr(self) -> bool:
        """是否还有 rfc-review/pr-open/iterating 的 run（watch 循环的退出条件）。"""
        return any(r.status in _OPEN_STATUSES for r in self._state.all_runs())
