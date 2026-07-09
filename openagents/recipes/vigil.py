"""# Spec-0061/T3: recipes.vigil —— 发现→分诊→派单 循环（纯控制流，零业务判断）。

新栈的守夜人：逐轮从 GitHub 列出标签门控的 open issue，对每个**新** issue 派 triager agent 出
分诊裁决，据裁决路由——可派单（actionable）→ 跑 `solve_issue` 竖切求解；不可派单 → 打
needs-human + 贴对齐评论、挂起等人。整条循环**只**做三件事：调 engine 派 agent、按 agent 的
结构化裁决分支、调确定性 utils/gates 兜底；自己不判「issue 讲清没/该不该做」（那是 triager 的活）、
也不直接碰 git/gh/subprocess（那是 utils 的活）。

去重四闸留在 recipe（**确定性**、非判断，故不下放 agent，对齐 Spec-0060 分界线）：
  ① 本地已有 run 记录 → 跳过（已在飞行/已完成，交守候段推进）；
  ② 远端已有该 issue 分支（`utils.git.remote_branch_exists`）→ 跳过（别的后端已认领在途）；
  ③ issue 带 BLOCKED_LABEL（needs-human）→ 跳过（已挂起待人对齐，人摘标签前不重判、防震荡）；
  ④ 带 DISPATCH_LABEL 且有**他人未过期的署名认领便签** → 跳过（跨后端认领归属，承旧 Spec-0039/0049）；
     便签已过期（龄 > 阈值，僵尸认领）/ 无有效便签 / 是自己的残留 → 可回收、视同「新」重新认领。
四闸都不命中才算「新」，才派 triager 分诊。每轮都从 GitHub+本地 State 重新推导「现在该做什么」，
不持内存态——被 kill/崩溃后重跑即从断点续（去重闸据 State+远端+认领便签重新推导，「代码即 checkpoint」）。
认领便签闸的过期判定读客观事实（便签在不在？谁的签名？created_at 距 `now` 的秒龄比不比阈值），仍是
确定性、非判断，故留 recipe——`now`/阈值可注入（不读墙钟的纯路径，镜像 merge_pr 注入 `now`）。

派单动作（`dispatch`）默认走 `dispatch_solve`（建 worktree→组 Context→跑 solve_issue→记 run），
但作可注入依赖（理念 10 解耦）——单测注入假 dispatch 验证「发现+分诊+路由」控制流，不触真 git/后端。

守候段（每轮发现后）闭合**发现→求解→回应→合并**全环：先跑 poll_comments 回应 PR 上的人类评论，
再跑 merge_pr 推进合并（vigil 据本地 run 记录投影出携 issue 归属的 `runs` 注入 merge_pr，让合并/关
issue 能回写 state）。两段皆可注入（理念 10），缺则跳过——单轮 hermetic 可测。
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openagents.agents import triager
from openagents.recipes.merge_pr import Run as MergeRun
from openagents.recipes.solve_issue import solve_issue
from openagents.runtime import context, engine
from openagents.runtime.context import Context
from openagents.runtime.state import RuntimeState
from openagents.utils import git, github, identity

# Spec-0061/T3: 单 issue → 单分支命名（与 solve_issue 交付、旧栈 orchestrator 一致）。
_BRANCH_PREFIX = "openagents/issue-"

# Spec-0061/T3: 新栈 run 记录的状态字面量——极简三态（求解中/已完成/已挂起），落 RuntimeState。
_STATUS_SOLVING = "solving"
_STATUS_DONE = "done"
_STATUS_BLOCKED = "blocked"

# Spec-0062/T3: merge_pr.Run 的状态字面量（与 recipes.merge_pr._STATUS_OPEN/_STATUS_BLOCKED 对齐）——
# 守候段把本地 run 投影成 merge Run 时用：blocked 短路、其余（在飞待合并）当 open 交 merge_pr 推进。
_MERGE_OPEN = "open"

# Spec-0062/T3: 认领过期阈值（秒）——带认领便签但便签龄超过它 → 判「僵尸认领」允许回收（承旧
# vigil.CLAIM_EXPIRY_SECONDS / Spec-0039/0049）。默认 1 小时：同后端崩溃已由本地 run + 去重闸①兜住，
# 过期回收只针对跨后端的死后端，误回收（把仍在慢速起草的活后端判过期）代价只是重复派单一次，故取
# 「足够大于最坏起草时长」的保守值。模块级常量，可 monkeypatch 覆盖，或按实例注入 claim_expiry_seconds。
CLAIM_EXPIRY_SECONDS = 3600

# Spec-0062/T3: 已知简化 —— 认领便签的隐藏标记，镜像 openagents.identity._CLAIM_MARKER（未经 utils
# 再导出）。此处复制为字面量以走**可注入 now** 的确定性过期判定（不消费 identity.latest_claim 内置的
# 墙钟 age）；T5 把 identity 物理搬进 utils.identity 后应改为从单一常量复用，消除这份字面量重复。
_CLAIM_MARKER = "<!-- openagents:claim -->"


def dispatch_solve(
    *,
    issue_number: int,
    base: str,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
) -> dict:
    """默认派单：建隔离 worktree → 组装 Context → 跑 solve_issue 竖切 → 记 run 记录。

    worktree 建/拉（agent 无法自建沙箱的**编排** git）经 `utils.git.Workspace`；组 `Context`
    绑定该 worktree 供 solve_issue 各阶段读占位符；派单前先 set_run(solving) 落 checkpoint（崩溃
    重跑时去重闸①命中即不重派），solve_issue 返回后 set_run(done)。本函数是 recipe 的**默认**
    派单实现（可被注入替换），故允许经 utils 触 git——vigil 主循环自身仍零 git 直调。
    """
    branch = f"{_BRANCH_PREFIX}{issue_number}"
    workspace = git.Workspace(work_dir=Path(work_dir))
    worktree = workspace.prepare(issue_number=issue_number, branch=branch, base=base)
    state.set_run(issue_number=issue_number, status=_STATUS_SOLVING, branch=branch, pr_number=None)
    ctx = Context(work_dir=worktree, issue_number=issue_number, branch=branch)
    report = solve_issue(issue_number=issue_number, backend=backend, ctx=ctx)
    state.set_run(
        issue_number=issue_number,
        status=_STATUS_DONE,
        branch=branch,
        pr_number=report.get("pr_number"),
    )
    return report


class Vigil:
    """# Spec-0061/T3: 新栈守夜人——发现→分诊→派单，逐轮从 GitHub+State 重推进度（去中心、可重入）。"""

    def __init__(
        self,
        *,
        backend: Any,
        state: RuntimeState,
        work_dir: Path,
        agent_id: str = "",
        dispatch: Callable[..., Any] = dispatch_solve,
        claim_expiry_seconds: int = CLAIM_EXPIRY_SECONDS,
    ) -> None:
        self._backend = backend
        self._state = state
        self._work_dir = Path(work_dir)
        # Spec-0062/T3: 本实例身份——认领归属闸据此判「最近认领便签是不是别人的」。默认 "" 使既有
        # 构造零改动：空 id 永不等于任一真实 owner，故任何他人活认领都被当「别人的」保守跳过（安全侧），
        # 生产由 cli 注入真实 id 精确判归属（承旧 vigil._agent_id 语义）。
        self._agent_id = agent_id
        # 派单动作可注入（默认 dispatch_solve）：单测替假实现即可验发现+分诊+路由控制流。
        self._dispatch = dispatch
        # Spec-0062/T3: 认领过期阈值可按实例注入（默认模块常量），配合注入 now 走确定性过期判定。
        self._claim_expiry_seconds = claim_expiry_seconds

    def run(
        self,
        *,
        interval: int,
        labels: list[str],
        base: str,
        once: bool,
        poll: Callable[[], Any] | None = None,
        merge: Callable[..., Any] | None = None,
    ) -> None:
        """守夜主循环：每轮先发现+分诊+派单，再（可选）跑守候段（回应评论 + 推进合并）；到 Ctrl-C 停。

        once=True 跑一轮即返回（适配 cron/CI 周期触发），异常照旧上抛让调度器看见非零退出；
        长驻（once=False）模式单轮失败记日志进下一轮，不掀掉整夜守候（对齐旧 vigil 决策 5/6）。
        `except Exception` 天然放行 KeyboardInterrupt（非 Exception 子类），Ctrl-C 走干净退出。
        poll/merge 可注入（守候段 recipes.poll_comments / merge_pr 的偏函数）；None 时该段跳过。
        每轮解析一个 `now`（墙钟），同时喂发现段认领过期判定与守候段 merge_pr 复活窗口判读，同轮一致。
        """
        try:
            while True:
                try:
                    now = datetime.now(UTC)
                    self.discover_and_dispatch(labels=labels, base=base, now=now)
                    self._watch(poll=poll, merge=merge, now=now)
                except Exception as exc:  # noqa: BLE001 —— 守夜第一要务是「活着进下一轮」
                    if once:
                        raise
                    self._log(message=f"✗ 本轮守夜失败，跳过、{interval}s 后再扫一轮：{exc}")
                if once:
                    return
                self._log(message=f"… 守夜中，{interval}s 后再扫一轮（Ctrl-C 停止）")
                time.sleep(interval)
        except KeyboardInterrupt:
            self._log(message="✓ 守夜人已停止（Ctrl-C）")
            return

    def _watch(
        self,
        *,
        poll: Callable[[], Any] | None,
        merge: Callable[..., Any] | None,
        now: datetime,
    ) -> None:
        """守候段：先回应评论（poll_comments），再推进合并（merge_pr）。两段皆可注入，缺则跳过。

        次序固定「先回应、后合并」：人在 PR 上的追问先得到回应，再据本地 run 记录推进已在飞的 PR 合并。
        merge_pr 需携 issue 归属的 `runs`——由本函数据本地 run 记录投影（`_merge_runs`），并透传同轮 `now`
        供其复活窗口判读（镜像 merge_pr 的 now 注入）。vigil 自身零业务判断，只组 runs、按次序调两段。
        """
        if poll is not None:
            poll()
        if merge is not None:
            merge(runs=self._merge_runs(), now=now)

    def _merge_runs(self) -> list[MergeRun]:
        """把本地 run 记录投影成 merge_pr 的 Run 列表——只取已有 PR 号的在飞 run，携 issue 归属。

        无 pr_number（起草/求解中，尚无 PR）→ 跳过（无可推进的合并）。状态映射：blocked → merge 的
        blocked（短路、不重跑闸）；其余（solving/done/rfc-review/pr-open/iterating）→ merge 的 open
        交 merge_pr 走合并流水线。携 issue_number/branch/closed_at 让 merge_pr 能回写 state / 关 issue。
        """
        # Spec-0062/T3: 已知简化 —— 跨轮 rounds 预算（旧 MAX_ROUNDS：review 恒 REWORK 攒满 K 轮才
        # blocked）本批不搬：新栈 RuntimeState 无 rounds 计数器，merge_pr 的 review REWORK 每轮只返
        # 单个 review 事件、blocked 仅由「冲突无法自愈」触发（见 merge_pr 模块 docstring）。留后续批次。
        runs: list[MergeRun] = []
        for record in self._state.list_runs():
            pr_number = record.get("pr_number")
            if pr_number is None:
                continue
            runs.append(
                MergeRun(
                    pr_number=pr_number,
                    issue_number=record.get("issue_number"),
                    branch=record.get("branch", ""),
                    status=_merge_status(status=record.get("status", "")),
                    closed_at=record.get("closed_at", ""),
                )
            )
        return runs

    def discover_and_dispatch(
        self, *, labels: list[str], base: str, now: datetime | None = None
    ) -> list[int]:
        """发现段：列标签门控 open issue → 去重四闸滤新 → triager 分诊 → 据裁决路由。返回本轮派单编号。

        对每个「新」issue（四道确定性去重闸都不命中）派 triager 出 `actionable` 裁决：
          - actionable=True  → 调 dispatch 跑 solve_issue 求解（并记入派单列表）；
          - actionable=False → _park：打 needs-human + 贴 triager 的对齐理由，挂起等人（不派单）。
        单 issue 失败（gh/agent/worktree 异常）只记日志跳过，不拖垮整轮（错误隔离，对齐旧 vigil 决策 8）。
        `now` 供认领过期判定（默认取 UTC 墙钟；测试可注入定值 hermetic 可测，镜像 merge_pr 的 now 注入）。
        """
        resolved_now = now if now is not None else datetime.now(UTC)
        dispatched: list[int] = []
        for issue in github.list_issues(labels=labels):
            if not self._is_fresh(issue=issue, now=resolved_now):
                continue
            try:
                verdict = engine.run_agent(
                    triager,
                    backend=self._backend,
                    **context.for_triage(work_dir=self._work_dir, issue=issue),
                )
                if not verdict["actionable"]:
                    self._park(issue=issue, reason=verdict["reason"])
                    continue
                self._log(message=f"▶ issue #{issue.number}：{issue.title} → 分诊通过，派单求解")
                self._dispatch(
                    issue_number=issue.number,
                    base=base,
                    backend=self._backend,
                    state=self._state,
                    work_dir=self._work_dir,
                )
                dispatched.append(issue.number)
            except (
                github.GithubError,
                engine.AgentOutputError,
                git.WorkspaceError,
            ) as exc:
                self._log(message=f"✗ issue #{issue.number} 派单失败，跳过：{exc}")
        return dispatched

    def _is_fresh(self, *, issue: github.Issue, now: datetime) -> bool:
        """去重四闸（确定性）：本地无 run 记录 且 远端无分支 且 未挂 needs-human 且 无他人未过期认领 → 「新」。

        认领闸（闸④）只在 issue 带 DISPATCH_LABEL（便宜的粗信号，已随 issue 拉下）时才读署名认领便签
        判归属+过期——常态无标签的 fresh issue 不额外发一次网络请求。`now` 供过期判定（不读墙钟）。
        """
        if self._state.get_run(issue_number=issue.number) is not None:
            return False
        if git.remote_branch_exists(
            work_dir=self._work_dir, branch=f"{_BRANCH_PREFIX}{issue.number}"
        ):
            return False
        if github.BLOCKED_LABEL in issue.labels:
            return False
        if github.DISPATCH_LABEL in issue.labels and not self._claim_reclaimable(
            issue=issue, now=now
        ):
            return False
        return True

    def _claim_reclaimable(self, *, issue: github.Issue, now: datetime) -> bool:
        """Spec-0062/T3: 带认领标签的 issue 是否**可被本后端回收重认领**（读署名认领便签判归属+过期）。

        承旧 vigil._claim_reclaimable（Spec-0049）语义：
          - 无有效认领便签 → True（只有粗标签、没归属凭证，落「新」）；
          - 最近便签是**自己**的残留 → True（上轮退让 / 起草失败的残留，重认领）；
          - 最近便签是**他人**且已过期（龄 > 阈值，僵尸认领）→ True（回收死后端占坑）；
          - 最近便签是**他人**且未过期 → False（他人在起草，跳过让路）。

        读评论失败（GithubError，权限/限流/gh 抖动）**不上抛**、保守判 False（不可回收 → 跳过）：本方法
        经 _is_fresh 在 discover_and_dispatch 的 per-issue try/except **之外**被调用，在此抛错会掀翻整轮
        发现。保守取「他人活认领」侧——宁可占坑多留一轮，也不误回收把活后端的认领抢掉，更不阵亡整轮。
        """
        try:
            comments = github.list_issue_comments(number=issue.number)
        except github.GithubError as exc:
            self._log(message=f"… issue #{issue.number} 认领便签查询失败，保守跳过：{exc}")
            return False
        claim = _latest_claim(comments=comments)
        if claim is None:
            return True
        owner, created_at = claim
        if owner == self._agent_id:
            return True
        return _claim_expired(created_at=created_at, now=now, threshold=self._claim_expiry_seconds)

    def _park(self, *, issue: github.Issue, reason: str) -> None:
        """分诊判不可派单 → 确定性挂起：打 needs-human + 贴 triager 的对齐理由，记 blocked run。

        这是**据 agent 裁决执行的确定性动作**（打标签/贴评论/记状态），不含二次判断——「该不该
        挂起」已由 triager 判完，recipe 只落地。记 blocked run 使去重闸①下轮命中，人摘标签前不重判。
        """
        github.issue_add_label(number=issue.number, name=github.BLOCKED_LABEL)
        github.issue_comment(
            number=issue.number,
            body=f"⏸ openagents 分诊：本 issue 暂不可直接派单，请对齐后再触发。\n\n{reason}",
        )
        self._state.set_run(
            issue_number=issue.number,
            status=_STATUS_BLOCKED,
            branch=f"{_BRANCH_PREFIX}{issue.number}",
            pr_number=None,
        )
        self._log(message=f"⏸ issue #{issue.number}：分诊判需对齐，已挂 needs-human")

    def _log(self, *, message: str) -> None:
        """守夜进度打到 stderr，保证无人值守时仍有可观测轨迹（对齐旧 vigil._log）。"""
        print(message, file=sys.stderr, flush=True)


def _merge_status(*, status: str) -> str:
    """本地 run 状态 → merge_pr.Run 状态：blocked 原样短路，其余当 open 交合并流水线（承 T3 投影）。"""
    return _STATUS_BLOCKED if status == _STATUS_BLOCKED else _MERGE_OPEN


def _latest_claim(*, comments: list[github.Comment]) -> tuple[str, str] | None:
    """从 issue 评论解析**最近一条署名认领便签**的 `(owner, created_at)`；无有效便签 → None（纯函数）。

    只认同时满足两条的评论：含 `_CLAIM_MARKER`（是认领便签，滤掉 precheck 对齐评论 / reviewer 回贴 /
    无签名人类评论）**且** `identity.parse_agent_id` 能取出 owner（有归属）。在这些便签里按 created_at
    （ISO 8601，字典序即时序）取最新一条，返回 (owner, created_at)——过期判定交 `_claim_expired` 据注入
    `now` 算龄（不像旧 identity.latest_claim 内置墙钟，保证纯路径 now 可注入、hermetic 可测）。
    """
    notes = [
        (comment.created_at, owner)
        for comment in comments
        if _CLAIM_MARKER in comment.body
        and (owner := identity.parse_agent_id(body=comment.body)) is not None
    ]
    if not notes:
        return None
    created_at, owner = max(notes, key=lambda pair: pair[0])
    return owner, created_at


def _claim_expired(*, created_at: str, now: datetime, threshold: int) -> bool:
    """认领便签是否过期：`now - created_at` 秒龄 > 阈值 → True（僵尸认领可回收）。纯函数、不读墙钟。

    created_at 空 / 不可解析 → 保守判 False（未过期、不回收）——不误把活后端的认领判过期（承旧
    identity._claim_age_seconds 的「保守判未过期」侧）。
    """
    if not created_at:
        return False
    try:
        stamped = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - stamped).total_seconds() > threshold
