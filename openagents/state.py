"""RFC-0001 T4: 状态持久化层（决策 4）。

把每个 issue → agent run 的状态与 comment 游标持久化到本地
`.openagents/state.json`：MVP 不引入数据库，状态需跨 solve/poll/board
多次进程调用共享，文件足够且可被成果看板直接读取。

JSON 结构：
    {
        "runs": [ {issue_number, branch, pr_number, pr_url, status, summary}, ... ],
        "cursors": { "<pr_number>": <last_comment_id> },
        "agent_id": "<本实例稳定身份>"   # RFC-0011 T1：可选键，首次自动生成后落盘
    }
读写一律容错：文件缺失/损坏视为空状态。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# RFC-0015：BLOCKED_LABEL 从 github re-import（标签单一来源），保留 state.BLOCKED_LABEL
# 公共名向后兼容；github 是叶子模块，此 import 无循环依赖风险。`as BLOCKED_LABEL` 的显式
# 再导出形式让 ruff 不把它当未使用（state 内不引用，仅供 promote 等外部模块经 state 访问）。
from openagents.github import BLOCKED_LABEL as BLOCKED_LABEL
from openagents.github import PR

# 状态机取值（决策 8：PR 被 merge 时置 done）。
STATUS_SOLVING = "solving"
# RFC-0005：PR 为 draft、承载 RFC、待人评审/批准的阶段。
STATUS_RFC_REVIEW = "rfc-review"
STATUS_PR_OPEN = "pr-open"
STATUS_ITERATING = "iterating"
STATUS_DONE = "done"
# RFC-0006：PR 被关闭但未合并的终态（人主动放弃）；不在 messages._OPEN_STATUSES 内，
# 故置 closed 后该 run 不再被守夜人轮询处理。与 done（合并成功）语义相反。
STATUS_CLOSED = "closed"
# RFC-0012 决策 5：评审超 K 轮挂起的终态（卡住兜底）；同样不在 _OPEN_STATUSES，poll 自动
# 跳过该 run（软挂起），且 PR 不关——等人据 needs-human 标签介入。与 closed 区别：closed 是
# 人主动放弃，blocked 是 agent 反复评审不过、显式把无解工作交还给人。
STATUS_BLOCKED = "blocked"

# RFC-0012 决策 5：卡住兜底打给 PR 的标签——与 STATUS_BLOCKED 配对的结构化「求救」信号。
# RFC-0015：字面量定义上移至 github（流程标签单一来源），此处经上面的 re-import 别名暴露
# state.BLOCKED_LABEL（向后兼容，promote 预检与 messages 路由的既有引用零改动）。


@dataclass
class RunRecord:
    """一条 issue → agent run 的状态记录（RFC-0001 接口契约）。

    status ∈ {solving, rfc-review, pr-open, iterating, done, closed}
    （rfc-review 为 RFC-0005 新增；closed 为 RFC-0006 新增——PR 关闭未合并的终态）。
    """

    issue_number: int
    branch: str
    pr_number: int
    pr_url: str
    status: str
    summary: str
    # RFC-0012 决策 6：当前闸内已迭代回合数。默认 0 使 RunRecord(**旧记录) 不报错（向后
    # 兼容缺该键的旧 state.json）。每次 refine_rfc/iterate（评审未过一回合）令其 +1；
    # implement（RFC 闸→代码闸的阶段切换）清零，使 K 按「每个闸」独立计。
    rounds: int = 0


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

    def record_run(
        self, *, issue_number: int, branch: str, pr: PR, status: str = STATUS_PR_OPEN
    ) -> None:
        """RFC-0001 T4 / RFC-0007 T1：一次 _save 落盘一条带 pr_number/pr_url 的 run；按 issue 去重覆盖。

        RFC-0007 决策 4：新增 status 形参（默认 pr-open，既有调用方/测试夹具行为不变）。
        start_rfc 传 status=STATUS_RFC_REVIEW，使「开 PR + 翻到 rfc-review」一次写成，
        消除原 record_run(pr-open) → update_status(rfc-review) 两次写之间的瞬态 pr-open 窗口
        （否则恰被 poll 扫到会把 draft RFC 误当 coding 阶段处理）。
        """
        data = self._load()
        runs = [r for r in data["runs"] if r["issue_number"] != issue_number]
        runs.append(
            asdict(
                RunRecord(
                    issue_number=issue_number,
                    branch=branch,
                    pr_number=pr.number,
                    pr_url=pr.url,
                    status=status,
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

    def increment_rounds(self, *, issue_number: int) -> int:
        """RFC-0012 决策 6：把某 issue 对应 run 的 rounds +1 并落盘，返回新值。

        用 record.get("rounds", 0) 兜底缺该键的旧记录（向后兼容）。供闸口每判一次「评审
        未过」即递增；调用方据返回值与 MAX_ROUNDS 比较决定 refine/iterate 还是 BLOCKED。
        """
        data = self._load()
        new_value = 0
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                new_value = record.get("rounds", 0) + 1
                record["rounds"] = new_value
        self._save(data=data)
        return new_value

    def reset_rounds(self, *, issue_number: int) -> None:
        """RFC-0012 决策 6：把某 issue 对应 run 的 rounds 归零（阶段切换时调，如 implement）。"""
        data = self._load()
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                record["rounds"] = 0
        self._save(data=data)

    def get_agent_id(self) -> str | None:
        """RFC-0011 T1：读已落盘的本实例 agent_id；未设过返回 None。

        agent_id 是 state.json 顶层可选键（与 runs/cursors 平级）。供
        identity.resolve_agent_id 在 env 未指定时复用既有值、保证跨进程/重启稳定。
        """
        data = self._load()
        agent_id = data.get("agent_id")
        return agent_id if isinstance(agent_id, str) and agent_id else None

    def set_agent_id(self, *, agent_id: str) -> None:
        """RFC-0011 T1：落盘本实例 agent_id（首次自动生成后写回，使后续进程拿到同一 id）。

        _load 保留顶层的全部既有键，故写 agent_id 不影响 runs/cursors（反之亦然）。
        """
        data = self._load()
        data["agent_id"] = agent_id
        self._save(data=data)

    def get_cursor(self, *, pr_number: int) -> str | None:
        """RFC-0001 T4：读某 PR 已处理到的游标（RFC-0005：comment 的 created_at）。

        RFC-0005 决策 6：comment id 是 node id 字符串、不可排序，故游标存 created_at
        （ISO 8601，字典序即时间序），原样返回不做类型强转。
        """
        data = self._load()
        return data["cursors"].get(str(pr_number))

    def set_cursor(self, *, pr_number: int, comment_id: str) -> None:
        """RFC-0001 T4：推进某 PR 的 comment 游标（RFC-0005：存 created_at 字符串）。"""
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
        """RFC-0003 决策 7 / RFC-0007 决策 3：按 issue number 反查 run（供发现段分流 fresh / resume）。

        RFC-0005 删除了原 solve 里的 reader（_should_resume），此 reader 退化为去重闸；
        RFC-0007 把它重新归位为 vigil 发现段的分流依据（无 run→fresh、solving/pr=0→resume）。
        """
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
