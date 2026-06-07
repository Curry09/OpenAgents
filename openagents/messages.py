"""RFC-0001 T5 + RFC-0005: PR 消息机制 + CI 监控，按**阶段**路由 GitHub 事件。

poll 对每个 open 状态的 run 做一次扫描，先判 merge，再按 run 所处阶段路由
（RFC-0005 决策 5）：

  1. github.is_merged：已合并 → State 置 done，跳过（决策 8）。
  1b. github.is_closed：关闭未合并 → State 置 closed，跳过（RFC-0006，merged 优先）。
  2. 阶段 rfc-review（PR 为 draft、承载 RFC）：
     a. 带 rfc-approved 标签 → Orchestrator.implement（转入 coding）。
     b. 否则有「游标后的新评论」→ Orchestrator.refine_rfc（精炼 RFC 并回贴说明），
        随后把游标推进到**触发评论本身**的 created_at（RFC-0011 决策 5）。
  3. 阶段 coding（pr-open / iterating）：
     a. CI 失败 → Orchestrator.iterate(reason="ci")（决策 11）。
     b. 否则有「游标后的新评论」→ Orchestrator.iterate(reason="comment")（决策 5）。

「新评论」= created_at 晚于游标、且**不带本实例签名**的最新一条评论
（RFC-0011 决策 1）：判定粒度收敛为「自己 vs 非自己」——只剔除「带我自己
agent=<my_id> 签名」的评论；其他 agent 的签名评论与无签名的真人评论都照常处理。
不按 GitHub 账号过滤（人机可能共用账号，会误杀真人）；自循环由签名过滤根治，
不再靠「把游标推进到 agent 回贴之后」消费自评论（RFC-0011 取代 RFC-0005 决策 6）。

watch：每隔 interval 秒循环调用 poll，无 open PR 或用户中断时退出（决策 6）。

依赖注入：orchestrator（Orchestrator）、state（State）由构造传入；GitHub 操作以模块
函数方式调用（测试里 monkeypatch github.*），time.sleep 同理可 mock。
"""

from __future__ import annotations

import time

from openagents import github, identity, rebase
from openagents.orchestrator import Orchestrator
from openagents.state import (
    STATUS_CLOSED,
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    STATUS_RFC_REVIEW,
    RunRecord,
    State,
)

# 需要继续轮询的状态（决策 8：done 终止，solving 尚未开 PR）。rfc-review 也在轮询范围。
_OPEN_STATUSES = {STATUS_RFC_REVIEW, STATUS_PR_OPEN, STATUS_ITERATING}

# RFC-0005 决策 4：批准信号——人在 draft PR 上打这个标签即视为 RFC 通过。
APPROVAL_LABEL = "rfc-approved"


class Messages:
    """RFC-0001 T5 + RFC-0005：按阶段轮询 PR 的 merge/标签/CI/comment，路由回编排层。"""

    def __init__(self, *, orchestrator: Orchestrator, state: State, agent_id: str) -> None:
        self._orchestrator = orchestrator
        self._state = state
        # RFC-0011 决策 1/7：本实例身份，由 CLI 接线处解析后注入。_latest_new_comment 据此
        # 剔除自己的签名评论；poll 合并分支再透传给 rebase.rebase_open_prs（保持 rebase 无状态）。
        self._agent_id = agent_id

    def poll(self) -> list[dict]:
        """RFC-0001 T5：扫描所有 open 状态 run，按 merge → 阶段 路由。

        返回本轮事件列表，每个事件含 pr_number 与 reason
        （reason ∈ {"merged", "approved", "refine", "ci", "comment"}），便于日志与测试断言。
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
            # RFC-0009 决策 1/3：合并即信号——同一 poll 轮内扇出，把最新 main 并入其余
            # open PR（排除刚合并的这个），触发它们 CI 重跑；冲突的 PR 由 rebase 层留言。
            synced = rebase.rebase_open_prs(merged_pr_number=pr_number, agent_id=self._agent_id)
            return {"pr_number": pr_number, "reason": "merged", "synced": synced}

        # 1b. RFC-0006：人主动关闭（未合并）也是终止信号 → 置 closed 并跳过，不触发任何
        # 编排动作。closed 不在 _OPEN_STATUSES，下一轮直接被跳过。merged 优先于 closed。
        if github.is_closed(pr_number=pr_number):
            self._state.update_status(issue_number=record.issue_number, status=STATUS_CLOSED)
            return {"pr_number": pr_number, "reason": "closed"}

        # 2. 按阶段路由（决策 5）。
        if record.status == STATUS_RFC_REVIEW:
            return self._process_rfc_review(record=record)
        return self._process_coding(record=record)

    def _process_rfc_review(self, *, record: RunRecord) -> dict | None:
        """rfc-review 阶段：批准标签 → implement；否则游标后的新评论 → refine_rfc。"""
        pr_number = record.pr_number
        # 2a. 批准标签优先：转入实现（决策 4）。
        if github.has_label(pr_number=pr_number, name=APPROVAL_LABEL):
            self._orchestrator.implement(pr_number=pr_number)
            return {"pr_number": pr_number, "reason": "approved"}
        # 2b. 游标后、非本实例签名的最新评论 → 精炼 RFC（RFC-0011 决策 1）。
        comment = self._latest_new_comment(pr_number=pr_number)
        if comment is None:
            return None
        self._orchestrator.refine_rfc(pr_number=pr_number, detail=comment.body)
        # RFC-0011 决策 5：游标只推进到**触发评论本身**的 created_at（与 coding 阶段一致）。
        # refine 回贴的「已更新 RFC」自评论带本实例签名，下一轮由 _latest_new_comment 的
        # 签名过滤剔除，不靠推游标越过——与游标是否推进无关，故抗崩溃、不误跳真人、不撞秒。
        self._state.set_cursor(pr_number=pr_number, comment_id=comment.created_at)
        return {"pr_number": pr_number, "reason": "refine"}

    def _process_coding(self, *, record: RunRecord) -> dict | None:
        """coding 阶段（pr-open / iterating）：CI 失败 → iterate(ci)；否则人类新评论 → iterate(comment)。"""
        pr_number = record.pr_number
        # 3a. CI 失败：以失败日志喂回 agent（决策 11）。
        status = github.check_status(pr_number=pr_number)
        if status.state == "fail":
            detail = "\n".join(status.failed_logs)
            self._orchestrator.iterate(pr_number=pr_number, reason="ci", detail=detail)
            return {"pr_number": pr_number, "reason": "ci"}
        # 3b. 游标后的新评论 → 迭代代码（决策 5）。iterate 不回贴评论，故游标推进到
        # 触发评论即可（无 agent 自评论需消费）。
        comment = self._latest_new_comment(pr_number=pr_number)
        if comment is None:
            return None
        self._orchestrator.iterate(pr_number=pr_number, reason="comment", detail=comment.body)
        self._state.set_cursor(pr_number=pr_number, comment_id=comment.created_at)
        return {"pr_number": pr_number, "reason": "comment"}

    def _latest_new_comment(self, *, pr_number: int) -> github.Comment | None:
        """取晚于游标、且非本实例签名的最新评论；无则 None（RFC-0011 决策 1）。

        comment id 是 node id 字符串、不可排序，故用 created_at（ISO 8601，
        字典序即时间序）判断「新」并供调用方推进游标。判定粒度是「自己 vs 非自己」：
        只剔除 identity.parse_agent_id(body) == 我自己 agent_id 的评论；其他 agent 的
        签名评论、无签名的真人评论都保留。这样既根治自循环，又不依赖按账号区分人/机。
        """
        cursor = self._state.get_cursor(pr_number=pr_number)
        comments = github.list_comments(pr_number=pr_number)
        fresh = [
            c
            for c in comments
            if (cursor is None or c.created_at > cursor)
            and identity.parse_agent_id(body=c.body) != self._agent_id
        ]
        if not fresh:
            return None
        return max(fresh, key=lambda c: c.created_at)

    def _has_open_pr(self) -> bool:
        """是否还有 rfc-review/pr-open/iterating 的 run（watch 循环的退出条件）。"""
        return any(r.status in _OPEN_STATUSES for r in self._state.all_runs())
