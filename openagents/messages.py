"""RFC-0001 T5: PR comment 消息机制 + CI 监控（决策 6/8/11）。

poll：对所有 pr-open/iterating 状态的 run 做一次扫描——
  1. 先 github.is_merged：已合并 → State 置 done，跳过该 PR（决策 8）。
  2. 否则读 github.check_status：CI 失败 → 以失败日志触发
     Orchestrator.iterate(reason="ci")，反复修到 CI 全绿（决策 11）。
  3. 再比对 comment 游标：github.list_comments 中 created_at 晚于游标的为新评论，
     对最新一条触发 Orchestrator.iterate(reason="comment") 并推进游标（决策 5）。
watch：每隔 interval 秒循环调用 poll（决策 6），无 open PR 或用户中断时退出。

依赖注入：orchestrator（Orchestrator）、state（State）由构造传入；
GitHub 操作以模块函数方式调用（测试里 monkeypatch github.*），time.sleep 同理可 mock。
"""

from __future__ import annotations

import time

from openagents import github
from openagents.orchestrator import Orchestrator
from openagents.state import (
    STATUS_DONE,
    STATUS_ITERATING,
    STATUS_PR_OPEN,
    State,
)

# 只有这两个状态的 run 才需要继续轮询（决策 8：done 终止，solving 尚未开 PR）。
_OPEN_STATUSES = {STATUS_PR_OPEN, STATUS_ITERATING}


class Messages:
    """RFC-0001 T5：轮询 PR 的 merge/CI/comment，生成事件并回送编排层。"""

    def __init__(self, *, orchestrator: Orchestrator, state: State) -> None:
        self._orchestrator = orchestrator
        self._state = state

    def poll(self) -> list[dict]:
        """RFC-0001 T5：扫描所有 open 状态 PR，按 merge→CI→comment 顺序处理。

        返回本轮产生的事件列表，每个事件含 pr_number 与 reason
        （reason ∈ {"merged", "ci", "comment"}），便于日志与测试断言。
        """
        events: list[dict] = []
        for record in self._state.all_runs():
            if record.status not in _OPEN_STATUSES:
                continue
            event = self._process_run(issue_number=record.issue_number, pr_number=record.pr_number)
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

    def _process_run(self, *, issue_number: int, pr_number: int) -> dict | None:
        """处理单个 open run，按决策 8→11→5 的优先级返回至多一个事件。"""
        # 1. 已合并优先于一切：置 done 并跳过（决策 8）。
        if github.is_merged(pr_number=pr_number):
            self._state.update_status(issue_number=issue_number, status=STATUS_DONE)
            return {"pr_number": pr_number, "reason": "merged"}

        # 2. CI 失败：以失败日志喂回 agent（决策 11）。
        status = github.check_status(pr_number=pr_number)
        if status.state == "fail":
            detail = "\n".join(status.failed_logs)
            self._orchestrator.iterate(pr_number=pr_number, reason="ci", detail=detail)
            return {"pr_number": pr_number, "reason": "ci"}

        # 3. 新 comment：对最新一条喂回 agent 并推进游标（决策 5）。
        return self._process_comments(pr_number=pr_number)

    def _process_comments(self, *, pr_number: int) -> dict | None:
        """比对游标（comment 的 created_at），对最新的新 comment 触发 iterate。

        comment id 是 node id 字符串、不可排序，故用 created_at（ISO 8601，
        字典序即时间序）判断「新」并推进游标。
        """
        cursor = self._state.get_cursor(pr_number=pr_number)
        comments = github.list_comments(pr_number=pr_number)
        new_comments = [c for c in comments if cursor is None or c.created_at > cursor]
        if not new_comments:
            return None

        latest = max(new_comments, key=lambda c: c.created_at)
        self._orchestrator.iterate(pr_number=pr_number, reason="comment", detail=latest.body)
        self._state.set_cursor(pr_number=pr_number, comment_id=latest.created_at)
        return {"pr_number": pr_number, "reason": "comment"}

    def _has_open_pr(self) -> bool:
        """是否还有 pr-open/iterating 的 run（watch 循环的退出条件）。"""
        return any(r.status in _OPEN_STATUSES for r in self._state.all_runs())
