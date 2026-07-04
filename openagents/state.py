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
# 再导出形式让 ruff 不把它当未使用（state 内不引用，仅供 release 等外部模块经 state 访问）。
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
# state.BLOCKED_LABEL（向后兼容，release 预检与 messages 路由的既有引用零改动）。


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
    # Spec-0021/T2：当前闸内「评审无效」（裁决无法解析/无可操作反馈）的重试计数，独立于
    # rounds。默认 0 向后兼容旧记录。每轮 poll 判定评审无效则 +1；达 MAX_REVIEW_RETRIES 后以
    # 「reviewer 输出无法解析」这一真实理由升级 needs-human（区别于真 REWORK 攒满 MAX_ROUNDS）。
    # 与 rounds 同生命周期：reset_rounds（implement / 解挂）同点一并归零，但二者预算彼此独立。
    review_invalid: int = 0
    # Spec-0031/T1：上一次 _block 是哪道闸挂起的（""/"rfc"/"code"/"merge"/*-unparseable）。
    # 默认 "" 使 RunRecord(**旧记录) 不报错（向后兼容缺该键的旧 state.json）。merge 闸据
    # block_gate=="merge"（且 status 已回 pr-open）判「armed」——人解挂 merge 冲突后派 agent
    # 主动解冲突的标记；状态机不变式保证该组合只能由 merge 解挂产生，故无需再加 armed 布尔。
    # 兼作可观测性（日志/看板可读「哪道闸挂的」）。由 _block / 解挂分支经 set_block_gate 显式管理。
    block_gate: str = ""
    # Spec-0031/T1：armed 窗口内已用的 agent 解冲突重试次数（类比 rounds / review_invalid，
    # 独立预算）。默认 0 向后兼容旧记录。每轮 poll 派一次 agent 解冲突失败则 +1；达
    # MAX_MERGE_ATTEMPTS 才重新挂起。与 rounds 同生命周期：reset_rounds 同点归零（给满预算），
    # 但 reset_rounds 不动 block_gate（armed 标记独立管理）。
    merge_attempts: int = 0
    # Spec-0032/T1：上一次 _block 时刻 PR 上最新评论的 createdAt（ISO 8601 字符串，字典序即
    # 时序）——「挂起水位线」。默认 "" 使 RunRecord(**旧记录) 不报错（向后兼容缺该键的旧
    # state.json），且任何真实 createdAt 都 > ""，故挂起后第一条人类评论即可触发解挂。解挂判定
    # 只认 createdAt 严格大于该水位线的评论——历史评论、本实例刚贴的挂起评论都在水位线之内、
    # 不会误触发（化解 RFC-0019 自循环顾虑的两道硬约束之一，另一道是只认无签名的人类评论）。
    # 由 _block 经 set_block_watermark 落盘、由解挂分支经 identity.new_human_comments 消费。
    block_watermark: str = ""
    # Spec-0036/T1：merge 闸解挂时人类评论正文——从「解挂 arming 这一轮」带到「下一轮 armed
    # 解冲突」（二者跨 poll）。默认 "" 使 RunRecord(**旧记录) 不报错（向后兼容缺该键的旧
    # state.json）。_process_armed_conflict 取它当解冲突 guidance 透传给解冲突器，并在回应时
    # 引用原评论；消费后 / 重新挂起时经 set_unblock_detail("") 清除，避免陈旧 guidance 渗进后续轮次。
    unblock_detail: str = ""
    # Spec-0042/T1：PR 被 close（未合并）reconcile 到 STATUS_CLOSED 的那一刻打的时间戳（ISO 8601
    # UTC 字符串）——「复活窗口」的起点。默认 "" 使 RunRecord(**旧记录) 不报错（向后兼容缺该键的
    # 旧 state.json，镜像 block_watermark 的加法）。GitHub 的 PR close 可逆（可 reopen 回 OPEN），
    # 故 closed 不是真终态：messages 只对 closed_at 在 REOPEN_REVIVE_WINDOW_SECONDS 内的 closed run
    # 每轮花一次 gh 查 reopen，超窗口即硬化成真终态（成本有界）。仅 open→closed 这一次转移打戳、
    # 复查仍 closed 绝不重打戳（否则窗口永远刷新→退化成无界）；复活时经 set_closed_at(when="") 清除。
    # 由 messages 的 is_closed 分支 / 复活分支经 set_closed_at 显式管理；与 block_* / merge_attempts 互不干扰。
    closed_at: str = ""
    # Spec-0053/T1：上一次 reviewer 全票 PASS 时 PR 净 diff 的指纹（sha256(gh pr diff)）。
    # 默认 "" 使 RunRecord(**旧记录) 不报错（向后兼容缺该键的旧 state.json）。代码闸每轮据它短路：
    # 本轮 code_fingerprint 与它相等 → 复用上轮 PASS、跳过重审；不等 → 照常重审、PASS 后更新它。
    # 对照 k8s Tide sticky approve / lgtm store_tree_hash（代码状态没变就别重签）。
    # 与 block_* / merge_attempts / closed_at 互不干扰。
    code_passed_fingerprint: str = ""


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

    def clear_run(self, *, issue_number: int) -> None:
        """Spec-0049/T4：抹掉某 issue 的 run 记录（认领二次确认退让时清本轮 begin_run 的 solving/pr=0）。

        与 begin_run/record_run 的「按 issue 去重覆盖」同构，但只删不写：读侧竞态里本后端 fresh
        认领后被他方更晚认领（ClaimLost），start_rfc 退让时调本原语抹掉刚落的 solving/pr=0 记录，
        使**下一轮** _dispatch_kind 回到「record is None → 看见他方有效认领 → 跳过」，而不是命中
        solving/pr=0 走 resume 续跑（那会与赢家双开）。幂等：无匹配记录即 no-op（重复退让不报错）。
        cursors/agent_id 等顶层键原样保留（_load 幂等填充，只重写 runs）。
        """
        data = self._load()
        data["runs"] = [r for r in data["runs"] if r["issue_number"] != issue_number]
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

    def increment_review_invalid(self, *, issue_number: int) -> int:
        """Spec-0021/T2：把某 issue 对应 run 的 review_invalid +1 并落盘，返回新值。

        镜像 increment_rounds，但计的是「评审无效」轮次（裁决无法解析/无可操作反馈），与
        rounds 预算彼此独立。用 record.get("review_invalid", 0) 兜底缺该键的旧记录（向后兼容）。
        调用方据返回值与 MAX_REVIEW_RETRIES 比较，决定本轮等下一轮重评还是诚实升级 needs-human。
        """
        data = self._load()
        new_value = 0
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                new_value = record.get("review_invalid", 0) + 1
                record["review_invalid"] = new_value
        self._save(data=data)
        return new_value

    def set_block_gate(self, *, issue_number: int, gate: str) -> None:
        """Spec-0031/T1：落盘某 issue 对应 run 的 block_gate（哪道闸挂的），gate="" 即清除。

        供 _block 记账挂起入口、供解挂分支判 armed（block_gate=="merge"），以及解 armed 时
        显式清除（gate=""，避免 "rfc"/"code" 残留误判后续 merge 入口）。block_gate 是 armed
        标记，刻意独立于 reset_rounds 的生命周期——只由 _block / 解挂 / armed 解决经此显式管理。
        """
        data = self._load()
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                record["block_gate"] = gate
        self._save(data=data)

    def set_block_watermark(self, *, issue_number: int, watermark: str) -> None:
        """Spec-0032/T1：落盘某 issue 对应 run 的 block_watermark（挂起时刻最新评论 createdAt）。

        镜像 set_block_gate 的写法（按 issue 定位 run、改单字段、整体落盘）。_block 贴完结构化
        挂起评论后取当前最新评论 createdAt 写入；解挂分支只考虑 createdAt 严格大于它的人类新评论，
        故本实例刚贴的挂起评论天然在水位线之内、不会自触发（与 block_gate/merge_attempts 互不干扰）。
        """
        data = self._load()
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                record["block_watermark"] = watermark
        self._save(data=data)

    def set_unblock_detail(self, *, issue_number: int, detail: str) -> None:
        """Spec-0036/T1：落盘某 issue 对应 run 的 unblock_detail（merge 闸解挂时人类评论正文）。

        镜像 set_block_gate / set_block_watermark 的写法（按 issue 定位 run、改单字段、整体落盘）。
        merge 闸解挂当轮存触发评论正文，供下一轮 armed 解冲突取出当 guidance + 回应时引用原文；
        detail="" 即清除（armed 消费后 / 重新挂起时清，避免陈旧 guidance 渗进后续轮次）。与
        block_gate / block_watermark / merge_attempts 互不干扰。
        """
        data = self._load()
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                record["unblock_detail"] = detail
        self._save(data=data)

    def set_closed_at(self, *, issue_number: int, when: str) -> None:
        """Spec-0042/T1：落盘某 issue 对应 run 的 closed_at（复活窗口起点时间戳），when="" 即清除。

        镜像 set_block_gate / set_block_watermark / set_unblock_detail 的写法（按 issue 定位 run、
        只改单字段、整体落盘）。messages 的 is_closed 分支在 open→closed 转移时写入当前 UTC 时间戳
        （仅这一次转移打戳、复查仍 closed 不重打戳，否则窗口永远刷新→退化成无界成本）；复活分支
        在 reopen 后经 when="" 清除。与 block_gate / block_watermark / unblock_detail / merge_attempts
        互不干扰（同住一条记录、各管各的）。
        """
        data = self._load()
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                record["closed_at"] = when
        self._save(data=data)

    def set_code_fingerprint(self, *, issue_number: int, fingerprint: str) -> None:
        """Spec-0053/T1：落盘某 issue 对应 run 的 code_passed_fingerprint（上轮 PASS 的 PR 净 diff 指纹）。

        镜像 set_block_gate / set_block_watermark / set_unblock_detail 的写法（按 issue 定位 run、
        只改单字段、整体落盘）。代码闸只在 reviewer 全票 PASS 时写入当轮指纹，下一轮进 review_code
        前据它短路（指纹一致复用 PASS）；fingerprint="" 即清除（本设计不主动清，留作对称）。与
        block_gate / block_watermark / unblock_detail / merge_attempts / closed_at 互不干扰。
        """
        data = self._load()
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                record["code_passed_fingerprint"] = fingerprint
        self._save(data=data)

    def increment_merge_attempts(self, *, issue_number: int) -> int:
        """Spec-0031/T1：把某 issue 对应 run 的 merge_attempts +1 并落盘，返回新值。

        镜像 increment_rounds，但计的是 armed 模式下 agent 解冲突的重试次数，与 rounds /
        review_invalid 预算彼此独立。用 record.get("merge_attempts", 0) 兜底缺该键的旧记录
        （向后兼容）。调用方据返回值与 MAX_MERGE_ATTEMPTS 比较，决定本轮 merge-retry 还是重新挂起。
        """
        data = self._load()
        new_value = 0
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                new_value = record.get("merge_attempts", 0) + 1
                record["merge_attempts"] = new_value
        self._save(data=data)
        return new_value

    def reset_rounds(self, *, issue_number: int) -> None:
        """RFC-0012 决策 6：把某 issue 对应 run 的 rounds 归零（阶段切换时调，如 implement）。

        Spec-0021/T2：同点把 review_invalid 也归零——评审无效计数与 rounds 同生命周期
        （implement / 解挂时一并清），但二者预算独立（评审无效不偷吃真 REWORK 的 rounds）。
        Spec-0031/T1：同点把 merge_attempts 也归零（解挂 arm 时给满 agent 解冲突预算），但
        **不动 block_gate**——block_gate 是 armed 标记，由解挂分支 / merge 闸经 set_block_gate
        显式管理（解挂 merge 闸时刻意保留 "merge" 作 armed 标记，故不能在此一并清掉）。
        """
        data = self._load()
        for record in data["runs"]:
            if record["issue_number"] == issue_number:
                record["rounds"] = 0
                record["review_invalid"] = 0
                record["merge_attempts"] = 0
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
