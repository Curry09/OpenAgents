"""RFC-0001 T4: 状态持久化层（决策 4）。

把每个 issue → agent run 的状态与 comment 游标持久化到本地
`.openagents/state.json`：MVP 不引入数据库，状态需跨 solve/poll/board
多次进程调用共享，文件足够且可被成果看板直接读取。

JSON 结构：
    {
        "runs": [ {issue_number, branch, pr_number, pr_url, status, summary}, ... ],
        "cursors": { "<pr_number>": <last_comment_id> }
    }
读写一律容错：文件缺失/损坏视为空状态。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from openagents.github import PR

# 状态机取值（决策 8：PR 被 merge 时置 done）。
STATUS_SOLVING = "solving"
# RFC-0005：PR 为 draft、承载 RFC、待人评审/批准的阶段。
STATUS_RFC_REVIEW = "rfc-review"
STATUS_PR_OPEN = "pr-open"
STATUS_ITERATING = "iterating"
STATUS_DONE = "done"


@dataclass
class RunRecord:
    """一条 issue → agent run 的状态记录（RFC-0001 接口契约）。

    status ∈ {solving, rfc-review, pr-open, iterating, done}（rfc-review 为 RFC-0005 新增）。
    """

    issue_number: int
    branch: str
    pr_number: int
    pr_url: str
    status: str
    summary: str


class State:
    """RFC-0001 T4：本地 JSON 状态存储（决策 4）。

    构造接受 state 文件路径；所有读写直接落盘，保证多进程调用间共享。
    """

    def __init__(self, *, path: Path) -> None:
        self._path = Path(path)

    def begin_run(self, *, issue_number: int, branch: str) -> None:
        """RFC-0003 决策 8：进入 solve 即记下 (issue, branch)，状态 solving、PR 待开。

        「分步落 state」的第一步：哪怕后续 push / 开 PR 崩溃，重跑也能据此恢复。
        pr_number=0 / pr_url="" 表示 PR 尚未开（看板对空 url 渲染为 —）。
        """
        data = self._load()
        runs = [r for r in data["runs"] if r["issue_number"] != issue_number]
        runs.append(
            asdict(
                RunRecord(
                    issue_number=issue_number,
                    branch=branch,
                    pr_number=0,
                    pr_url="",
                    status=STATUS_SOLVING,
                    summary="",
                )
            )
        )
        data["runs"] = runs
        self._save(data=data)

    def record_run(self, *, issue_number: int, branch: str, pr: PR) -> None:
        """RFC-0001 T4：登记一条 run，状态为 pr-open（PR 已开）；按 issue 去重覆盖。"""
        data = self._load()
        runs = [r for r in data["runs"] if r["issue_number"] != issue_number]
        runs.append(
            asdict(
                RunRecord(
                    issue_number=issue_number,
                    branch=branch,
                    pr_number=pr.number,
                    pr_url=pr.url,
                    status=STATUS_PR_OPEN,
                    summary="",
                )
            )
        )
        data["runs"] = runs
        self._save(data=data)

    def update_status(self, *, issue_number: int, status: str) -> None:
        """RFC-0001 T4：更新某 issue 对应 run 的状态（状态机流转）。"""
        data = self._load()
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                record["status"] = status
        self._save(data=data)

    def get_cursor(self, *, pr_number: int) -> int | None:
        """RFC-0001 T4：读某 PR 已处理到的最后 comment id（决策 5 游标）。"""
        data = self._load()
        value = data["cursors"].get(str(pr_number))
        return int(value) if value is not None else None

    def set_cursor(self, *, pr_number: int, comment_id: int) -> None:
        """RFC-0001 T4：推进某 PR 的 comment 游标。"""
        data = self._load()
        data["cursors"][str(pr_number)] = comment_id
        self._save(data=data)

    def all_runs(self) -> list[RunRecord]:
        """RFC-0001 T4：返回全部 run 记录（供成果看板读取）。"""
        data = self._load()
        return [RunRecord(**record) for record in data["runs"]]

    def find_run(self, *, pr_number: int) -> RunRecord | None:
        """RFC-0001 T4：按 PR number 定位 run（供 iterate 找回分支）。"""
        for record in self.all_runs():
            if record.pr_number == pr_number:
                return record
        return None

    def find_by_issue(self, *, issue_number: int) -> RunRecord | None:
        """RFC-0003 决策 7：按 issue number 反查 run（供 solve 分流 fresh / resume）。"""
        for record in self.all_runs():
            if record.issue_number == issue_number:
                return record
        return None

    def _load(self) -> dict:
        """读 state 文件；缺失或损坏一律视为空状态（容错，决策 4）。"""
        if not self._path.exists():
            return {"runs": [], "cursors": {}}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"runs": [], "cursors": {}}
        if not isinstance(raw, dict):
            return {"runs": [], "cursors": {}}
        raw.setdefault("runs", [])
        raw.setdefault("cursors", {})
        return raw

    def _save(self, *, data: dict) -> None:
        """把状态写回磁盘，按需创建父目录。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
