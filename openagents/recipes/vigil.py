"""# Spec-0064/T3: recipes.vigil —— `run_vigil` 策略路由编排 + CI/e2e/review 打回回环（纯控制流）。

`Vigil` 类散成自由函数 `run_vigil(*, backend, state, work_dir, config, ...)`——stage 都显式收参后
（T2 `recipes.stages`），类只剩「打包依赖 + 主循环」无肉，散开更符合奥卡姆。**关键**：抽函数是必要
条件不是目的，必须同时有一个**按 `stages` 策略路由的编排点**取代 `solve_issue` 写死的
`plan→impl→review→deliver`——对每个可配阶段查 owner（`agent`→调 T2 stage 函数 / `human`→打
needs-human 挂起等人 / `skip`→跳过）。agent→backend 映射从 `config.agents` 取（理念 2，backends 目前
只有 claude_code，声明面先立）。多仓 `fleet` 收编为「每仓一次 `run_vigil` 调用」（`run_fleet`），不需类。

**合并流水线定稿顺序** `conflict → CI → e2e → review → merge`（承 merge_pr 的 Spec-0055/T6 重排 + spec
排序三原则）。**conflict 必须在 CI 前是硬依赖**（非只成本）：PR 冲突时 GitHub 造不出 merge ref、CI 无
东西可跑 / 只有陈旧结果 → 读 CI 前必先确认 mergeable 既非 CONFLICTING/DIRTY 也非 UNKNOWN/null。

**打回回环（本 spec 补的真缺口）**：CI/e2e/review 三闸失败**不再只 `return {"reason": ...}`**，而是
（owner=agent 时）派 `implementer` 迭代改代码、下轮从 conflict 重进流水线（不是原地重试——改完 base
可能又变，须从冲突客观复检重进）；owner=human 时打 needs-human 挂起等人。

**确定性硬闸恒在、不受 stages 管辖**（约束②）：head 前移 / 证据溯源戳（`gates.assert_*`）/ round_cap
死循环上限恒机器、`skip` 关不掉——它们在 T2 交付类 stage 内嵌 + review 循环 round_cap，`stages` 只决定
「这道闸归谁」不能关掉硬底线。

所有依赖（backend / github / git / engine / stages）可注入或 monkeypatch，hermetic 可测。
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openagents.agents import replier
from openagents.recipes import stages
from openagents.runtime import context, engine
from openagents.runtime.state import RuntimeState
from openagents.utils import agent_config, git, github, identity

# Spec-0064/T3: 单 issue → 单分支命名（承 solve_issue / 旧 orchestrator 一致）。
_BRANCH_PREFIX = "openagents/issue-"

# Spec-0064/T3: 新栈 run 极简三态字面量（承 recipes.vigil/merge_pr）——落 RuntimeState。
_STATUS_SOLVING = "solving"
_STATUS_RFC_REVIEW = "rfc-review"
_STATUS_PR_OPEN = "pr-open"
_STATUS_DONE = "done"
_STATUS_BLOCKED = "blocked"

# Spec-0064/T3: 认领过期阈值（秒）——带认领便签但便签龄超它 → 判「僵尸认领」允许回收（承 Spec-0062/T3
# / 旧 Spec-0039/0049）。默认 1 小时。可 monkeypatch 或按调用注入 claim_expiry_seconds。
CLAIM_EXPIRY_SECONDS = 3600

# Spec-0064/T3: 认领便签隐藏标记（镜像 identity._CLAIM_MARKER，走可注入 now 的确定性过期判定）。
_CLAIM_MARKER = "<!-- openagents:claim -->"

# Spec-0064/T3: 三态所有者别名（从配置层单一真源引用，避免字面量漂移）。
_AGENT = agent_config.OWNER_AGENT
_HUMAN = agent_config.OWNER_HUMAN
_SKIP = agent_config.OWNER_SKIP


# --------------------------------------------------------------------------------------------------
# 策略路由原语：查 owner → 三态分派。抽成一处，所有可配闸共用（agent 调 stage / human 停等 / skip 跳）。
# --------------------------------------------------------------------------------------------------


def route(
    *,
    owner: str,
    on_agent: Callable[[], Any],
    on_human: Callable[[], Any],
    on_skip: Callable[[], Any],
) -> Any:
    """三态策略路由：owner=agent→on_agent() / human→on_human() / skip→on_skip()。编排点的唯一分支源。

    高阶函数——各闸把「自动化怎么做 / 停等人怎么做 / 跳过怎么做」以三个零参 thunk 传入，本函数只据
    config 的 owner 选一个执行。抽成一处使「按 stages 三态路由」成单一可测支点（注入 owner 断言三分支）。
    """
    if owner == _AGENT:
        return on_agent()
    if owner == _HUMAN:
        return on_human()
    return on_skip()


# --------------------------------------------------------------------------------------------------
# 发现段：列标签门控 open issue → 去重四闸滤新 → triage 路由（承旧 Vigil.discover_and_dispatch）。
# --------------------------------------------------------------------------------------------------


def discover_and_dispatch(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    stages_policy: agent_config.StagePolicy,
    labels: list[str],
    base: str,
    agent_id: str,
    dispatch: Callable[..., Any],
    now: datetime,
    claim_expiry_seconds: int,
) -> list[int]:
    """发现段：滤「新」issue → 按 `stages.triage` 三态路由。返回本轮派单编号。

    triage 路由：`agent`→派 triager 出裁决（actionable→dispatch 求解 / 否→park 挂 needs-human）；
    `human`→每个新 issue 都 park 停等人点头（不自动派单）；`skip`→跳过分诊直接 dispatch（无闸放行）。
    单 issue 失败只记日志跳过，不拖垮整轮（错误隔离）。
    """
    dispatched: list[int] = []
    triage_owner = stages_policy.owner_of(stage=agent_config.STAGE_TRIAGE)
    for issue in github.list_issues(labels=labels):
        if not _is_fresh(
            state=state,
            work_dir=Path(work_dir),
            agent_id=agent_id,
            issue=issue,
            now=now,
            claim_expiry_seconds=claim_expiry_seconds,
        ):
            continue
        try:
            _route_triage(
                owner=triage_owner,
                backend=backend,
                state=state,
                work_dir=Path(work_dir),
                issue=issue,
                base=base,
                dispatch=dispatch,
                dispatched=dispatched,
            )
        except (github.GithubError, engine.AgentOutputError, git.WorkspaceError) as exc:
            _log(message=f"✗ issue #{issue.number} 派单失败，跳过：{exc}")
    return dispatched


def _route_triage(
    *,
    owner: str,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    issue: Any,
    base: str,
    dispatch: Callable[..., Any],
    dispatched: list[int],
) -> None:
    """triage 三态路由的落地：agent 派 triager 按裁决走 / human 直接 park / skip 直接 dispatch。"""

    def _on_agent() -> None:
        verdict = stages.triage(backend=backend, work_dir=work_dir, issue=issue)
        if not verdict["actionable"]:
            _park(state=state, issue=issue, reason=verdict["reason"])
            return
        _do_dispatch(
            dispatch=dispatch,
            backend=backend,
            state=state,
            work_dir=work_dir,
            issue=issue,
            base=base,
            dispatched=dispatched,
        )

    def _on_human() -> None:
        _park(state=state, issue=issue, reason="triage:human——每个新 issue 停下等人点头")

    def _on_skip() -> None:
        _do_dispatch(
            dispatch=dispatch,
            backend=backend,
            state=state,
            work_dir=work_dir,
            issue=issue,
            base=base,
            dispatched=dispatched,
        )

    route(owner=owner, on_agent=_on_agent, on_human=_on_human, on_skip=_on_skip)


def _do_dispatch(
    *,
    dispatch: Callable[..., Any],
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    issue: Any,
    base: str,
    dispatched: list[int],
) -> None:
    """派单求解：调注入的 dispatch（默认 dispatch_solve 建 worktree 跑 solve 竖切），记入派单列表。"""
    _log(message=f"▶ issue #{issue.number}：{issue.title} → 派单求解")
    dispatch(
        issue_number=issue.number,
        base=base,
        backend=backend,
        state=state,
        work_dir=work_dir,
    )
    dispatched.append(issue.number)


# --------------------------------------------------------------------------------------------------
# 去重四闸 + 认领归属（确定性、非判断，故留 recipe，承旧 Vigil._is_fresh/_claim_reclaimable）。
# --------------------------------------------------------------------------------------------------


def _is_fresh(
    *,
    state: RuntimeState,
    work_dir: Path,
    agent_id: str,
    issue: Any,
    now: datetime,
    claim_expiry_seconds: int,
) -> bool:
    """去重四闸：本地无 run 且 远端无分支 且 未挂 needs-human 且 无他人未过期认领 → 「新」。"""
    if state.get_run(issue_number=issue.number) is not None:
        return False
    if git.remote_branch_exists(work_dir=Path(work_dir), branch=f"{_BRANCH_PREFIX}{issue.number}"):
        return False
    if github.BLOCKED_LABEL in issue.labels:
        return False
    if github.DISPATCH_LABEL in issue.labels and not _claim_reclaimable(
        agent_id=agent_id, issue=issue, now=now, claim_expiry_seconds=claim_expiry_seconds
    ):
        return False
    return True


def _claim_reclaimable(
    *, agent_id: str, issue: Any, now: datetime, claim_expiry_seconds: int
) -> bool:
    """带认领标签的 issue 是否可被本后端回收重认领（读署名认领便签判归属+过期）。承旧语义。

    无有效便签 / 最近是自己的残留 / 最近是他人且已过期 → True（可回收）；他人且未过期 → False（让路）。
    读评论失败保守判 False（不上抛，被 per-issue try/except 之外调用，抛错会掀翻整轮）。
    """
    try:
        comments = github.list_issue_comments(number=issue.number)
    except github.GithubError as exc:
        _log(message=f"… issue #{issue.number} 认领便签查询失败，保守跳过：{exc}")
        return False
    claim = _latest_claim(comments=comments)
    if claim is None:
        return True
    owner, created_at = claim
    if owner == agent_id:
        return True
    return _claim_expired(created_at=created_at, now=now, threshold=claim_expiry_seconds)


def _park(*, state: RuntimeState, issue: Any, reason: str) -> None:
    """据裁决确定性挂起：打 needs-human + 贴对齐理由 + 记 blocked run（下轮去重闸①命中不重判）。"""
    github.issue_add_label(number=issue.number, name=github.BLOCKED_LABEL)
    github.issue_comment(
        number=issue.number,
        body=f"⏸ openagents 分诊：本 issue 暂不可直接派单，请对齐后再触发。\n\n{reason}",
    )
    state.set_run(
        issue_number=issue.number,
        status=_STATUS_BLOCKED,
        branch=f"{_BRANCH_PREFIX}{issue.number}",
        pr_number=None,
    )
    _log(message=f"⏸ issue #{issue.number}：分诊判需对齐，已挂 needs-human")


# --------------------------------------------------------------------------------------------------
# 派单默认实现：建 worktree → 跑路由化 solve 竖切（rfc→implement→review→deliver）→ 开 PR。
# --------------------------------------------------------------------------------------------------


def dispatch_solve(
    *,
    issue_number: int,
    base: str,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    stages_policy: agent_config.StagePolicy | None = None,
) -> dict:
    """默认派单：建隔离 worktree → 组 Context → 跑路由化 solve 竖切 → 记 run。可被注入替换（hermetic 测）。

    `stages_policy` 决定 rfc/review 归谁（agent/human/skip）；缺省全 agent（内建默认）。worktree 建/拉
    经 utils.git.Workspace（agent 无法自建沙箱的编排 git），本函数是**默认**派单实现故允许触 git——
    run_vigil 主循环自身仍零 git 直调。
    """
    policy = stages_policy or agent_config.StagePolicy(owners={})
    branch = f"{_BRANCH_PREFIX}{issue_number}"
    workspace = git.Workspace(work_dir=Path(work_dir))
    worktree = workspace.prepare(issue_number=issue_number, branch=branch, base=base)
    state.set_run(issue_number=issue_number, status=_STATUS_SOLVING, branch=branch, pr_number=None)
    report = run_solve(
        backend=backend,
        state=state,
        worktree=worktree,
        stages_policy=policy,
        issue_number=issue_number,
        branch=branch,
        base=base,
    )
    return report


def run_solve(
    *,
    backend: Any,
    state: RuntimeState,
    worktree: Path,
    stages_policy: agent_config.StagePolicy,
    issue_number: int,
    branch: str,
    base: str,
) -> dict:
    """路由化 solve 竖切：rfc（routed）→ 开 draft PR → implement → review（routed loop）→ deliver。

    取代 solve_issue 写死的 plan→impl→review→deliver：每可配阶段查 owner——`rfc: agent`→drafter 起草 /
    `rfc: skip`→跳过起草直接实现；`review: agent`→reviewer 判 PASS/REWORK（REWORK 派 implementer 迭代，
    round_cap 兜底）/ `review: human`→挂 needs-human / `review: skip`→放行。implement/deliver 恒 agent。
    """
    issue = github.get_issue(number=issue_number)
    rfc_owner = stages_policy.owner_of(stage=agent_config.STAGE_RFC)

    # ① rfc（routed agent/skip）——起草 spec；skip 时跳过起草直接实现（打 no-rfc 意图）。
    def _draft() -> None:
        stages.rfc(
            backend=backend,
            worktree=worktree,
            mode=stages.MODE_DRAFT,
            target=f"issue #{issue.number}「{issue.title}」",
            branch=branch,
            detail=issue.body,
            context_text=issue.body,
            require_delivered=False,
        )

    route(owner=rfc_owner, on_agent=_draft, on_human=_draft, on_skip=lambda: None)

    pr = github.create_pr(
        branch=branch,
        base=base,
        title=f"docs: spec for issue #{issue.number} {issue.title}".strip(),
        body=f"Closes #{issue.number}\n\nopenagents 自动求解，待评审。",
        draft=True,
    )
    state.set_run(
        issue_number=issue_number, status=_STATUS_RFC_REVIEW, branch=branch, pr_number=pr.number
    )

    ctx = context.Context(
        work_dir=worktree, issue_number=issue_number, branch=branch, pr_number=pr.number
    )

    # ② implement（恒 agent）——按 spec 首轮实现。
    stages.implement(
        backend=backend,
        work_dir=worktree,
        issue_number=issue_number,
        pr_number=pr.number,
        feedback="",
        context_text=ctx.for_review(issue_number=issue_number)["context"],
    )

    # ③ review（routed）——PASS→跳出；REWORK→派 implementer 迭代（round_cap 兜死循环，硬闸不受 stages 关）。
    _routed_review_loop(
        backend=backend,
        state=state,
        worktree=worktree,
        stages_policy=stages_policy,
        ctx=ctx,
        issue=issue,
        issue_number=issue_number,
        pr_number=pr.number,
    )

    # ④ deliver（恒 agent）——git 交付 + 三道硬闸兜底（内嵌于 stages.deliver）。
    report = stages.deliver(
        backend=backend,
        worktree=worktree,
        branch=branch,
        pr_number=pr.number,
        issue_number=issue_number,
    )
    state.set_run(
        issue_number=issue_number, status=_STATUS_PR_OPEN, branch=branch, pr_number=pr.number
    )
    return {"pr_number": pr.number, "reason": "solved", "summary": report.get("summary", "")}


def _routed_review_loop(
    *,
    backend: Any,
    state: RuntimeState,
    worktree: Path,
    stages_policy: agent_config.StagePolicy,
    ctx: Any,
    issue: Any,
    issue_number: int,
    pr_number: int,
) -> None:
    """review 三态路由的评审循环：agent→reviewer 判（REWORK 派 implementer，round_cap 兜底）/ human→park / skip→放行。"""
    owner = stages_policy.owner_of(stage=agent_config.STAGE_REVIEW)
    if owner == _SKIP:
        return
    if owner == _HUMAN:
        _park(state=state, issue=issue, reason="review:human——评审停下等人")
        return
    # owner == agent：reviewer 判 PASS/REWORK，round_cap 硬闸兜死循环（不受 stages 关）。
    from openagents.runtime import gates

    for _ in gates.round_cap():
        verdict = stages.review(
            backend=backend,
            work_dir=worktree,
            pr_number=pr_number,
            issue_body=issue.body,
            context_text=ctx.for_review(issue_number=issue_number)["context"],
        )
        if verdict["verdict"] == "PASS":
            return
        stages.implement(
            backend=backend,
            work_dir=worktree,
            issue_number=issue_number,
            pr_number=pr_number,
            feedback=verdict["reason"],
            context_text="",
        )


# --------------------------------------------------------------------------------------------------
# 守候段：回应人类评论（折入旧 poll_comments）+ 合并流水线（conflict→ci→e2e→review→merge + 打回回环）。
# --------------------------------------------------------------------------------------------------


def poll_comments(
    *, backend: Any, state: RuntimeState, work_dir: Path, agent_id: str
) -> list[dict]:
    """回应 PR 上的新人类评论（折入旧 recipes.poll_comments）：拉游标后新人类评论→派 replier→盖签名回帖→推进游标。

    去重两道确定性机制：只取无 OpenAgents 签名的人类评论（防自触发）+ created_at 严于上次游标（不重复回）。
    单 PR 失败错误隔离、不拖垮整轮。
    """
    events: list[dict] = []
    for pr in github.list_open_prs():
        try:
            event = _reply_one_pr(
                pr_number=pr.number,
                backend=backend,
                state=state,
                work_dir=Path(work_dir),
                agent_id=agent_id,
            )
        except Exception as error:  # noqa: BLE001 —— 错误隔离：单 PR 失败不拖垮整轮
            events.append({"pr_number": pr.number, "reason": "error", "error": str(error)})
            continue
        if event is not None:
            events.append(event)
    return events


def _reply_one_pr(
    *, pr_number: int, backend: Any, state: RuntimeState, work_dir: Path, agent_id: str
) -> dict | None:
    """处理单个 PR：拉游标后新人类评论→无则跳过→派 replier 回应最新一条→盖签名回帖→推进游标。"""
    since = state.get_cursor(pr_number=pr_number) or ""
    news = identity.new_human_comments(pr_number=pr_number, since=since)
    if not news:
        return None
    latest = news[-1]
    branch = github.pr_head_branch(pr_number=pr_number)
    verdict = engine.run_agent(
        replier,
        backend=backend,
        **context.for_reply(work_dir=work_dir, pr_number=pr_number, branch=branch, comment=latest),
    )
    identity.post_signed_comment(pr_number=pr_number, body=verdict["reply"], agent_id=agent_id)
    state.set_cursor(pr_number=pr_number, comment_id=latest.created_at)
    reason = "resolved" if verdict["resolved"] else "replied"
    _log(message=f"↩ PR #{pr_number}：已回应人类评论（{reason}）")
    return {"pr_number": pr_number, "reason": reason}


def merge_prs(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    stages_policy: agent_config.StagePolicy,
    runs: list[Any],
    now: datetime,
) -> list[dict]:
    """扫一轮待推进 run，按合并流水线推进（conflict→ci→e2e→review→merge + 打回回环）。折入旧 merge_pr。

    单 PR 失败只记 error 事件并 continue（错误隔离）。`runs` 由 run_vigil 据本地 run 投影（携 issue 归属）。
    """
    events: list[dict] = []
    for run in runs:
        try:
            event = advance_merge(
                backend=backend,
                state=state,
                work_dir=Path(work_dir),
                stages_policy=stages_policy,
                run=run,
                now=now,
            )
        except Exception as error:  # noqa: BLE001 —— 错误隔离：单 PR 失败不拖垮整轮
            events.append({"pr_number": run.pr_number, "reason": "error", "error": str(error)})
            continue
        if event is not None:
            events.append(event)
    return events


def advance_merge(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    stages_policy: agent_config.StagePolicy,
    run: Any,
    now: datetime,
) -> dict | None:
    """单条 run 的合并流水线（定稿序 conflict→CI→e2e→review→merge + CI/e2e/review 打回回环）。

    终态优先（merged/closed/blocked 短路）；随后按序推进——**读 CI 前必先确认 mergeable 非 CONFLICTING/
    DIRTY 也非 UNKNOWN/null**（conflict 是 CI 的硬依赖）。每道可配闸查 owner 三态路由；CI/e2e/review 没过
    时（owner=agent）派 implementer 迭代、返阶段事件（下轮从 conflict 重进）；owner=human 挂 needs-human。
    """
    from openagents.runtime import gates

    pr_number = run.pr_number
    # 终态优先（对齐 merge_pr._process_run）。
    if github.is_merged(pr_number=pr_number):
        _mark_done(state=state, run=run)
        return {"pr_number": pr_number, "reason": "merged"}
    if run.status == _STATUS_BLOCKED:
        return None
    if github.is_closed(pr_number=pr_number):
        return {"pr_number": pr_number, "reason": "closed"}

    # ① conflict / behind（确定性读 mergeable 位）——CI 的硬依赖，必在 CI 前。
    merge_state = github.mergeability(pr_number=pr_number)
    if gates.is_conflicting(mergeability=merge_state):
        return _route_conflict(
            owner=stages_policy.owner_of(stage=agent_config.STAGE_CONFLICT),
            backend=backend,
            state=state,
            work_dir=Path(work_dir),
            run=run,
        )
    if gates.is_mergeable_unknown(mergeability=merge_state):
        return None  # GitHub 异步尚未算完：本轮不推进、下轮重查。
    if gates.is_behind(mergeability=merge_state):
        try:
            github.update_branch(pr_number=pr_number)
        except github.GithubError:
            return {"pr_number": pr_number, "reason": "behind-conflict"}
        return {"pr_number": pr_number, "reason": "synced"}

    # ② CI（routed agent/human/skip）——检测恒确定性读 check；红了 agent 自动打回、human 挂起。
    ci_event = _route_ci(
        owner=stages_policy.owner_of(stage=agent_config.STAGE_CI),
        backend=backend,
        state=state,
        work_dir=Path(work_dir),
        run=run,
    )
    if ci_event is not None:
        return ci_event

    # ③ e2e（routed）——读证据溯源戳；陈旧/缺失 agent 打回、human 挂起。
    e2e_event = _route_e2e(
        owner=stages_policy.owner_of(stage=agent_config.STAGE_E2E),
        backend=backend,
        state=state,
        work_dir=Path(work_dir),
        run=run,
    )
    if e2e_event is not None:
        return e2e_event

    # ④ review（routed）——reviewer 判 PASS/REWORK；REWORK agent 打回、human 挂起、skip 放行。
    review_event = _route_review(
        owner=stages_policy.owner_of(stage=agent_config.STAGE_REVIEW),
        backend=backend,
        state=state,
        work_dir=Path(work_dir),
        run=run,
    )
    if review_event is not None:
        return review_event

    # ⑤ merge（routed agent/human）——agent 自动合、human 停等人（不可 skip）。
    return _route_merge(
        owner=stages_policy.owner_of(stage=agent_config.STAGE_MERGE),
        state=state,
        run=run,
    )


def _route_conflict(
    *, owner: str, backend: Any, state: RuntimeState, work_dir: Path, run: Any
) -> dict:
    """conflict 三态（agent/human）：agent 派 deliver rebase 解 / human 挂 needs-human 等人解（不可 skip）。"""
    pr_number = run.pr_number

    def _on_agent() -> dict:
        result = stages.conflict(
            backend=backend,
            work_dir=work_dir,
            pr_number=pr_number,
            issue_number=run.issue_number or 0,
            branch=run.branch or "",
        )
        if result["delivered"]:
            return {"pr_number": pr_number, "reason": "resolved"}
        _mark_blocked(state=state, run=run)
        return {"pr_number": pr_number, "reason": "blocked", "gate": "conflict"}

    def _on_human() -> dict:
        _mark_blocked(state=state, run=run)
        return {"pr_number": pr_number, "reason": "blocked", "gate": "conflict"}

    return route(owner=owner, on_agent=_on_agent, on_human=_on_human, on_skip=_on_human)


def _route_ci(
    *, owner: str, backend: Any, state: RuntimeState, work_dir: Path, run: Any
) -> dict | None:
    """CI 三态：skip 放行（None）；agent/human 读 check——fail 时 agent 打回 implementer / human 挂起；pending 等下轮。"""
    if owner == _SKIP:
        return None
    classification = stages.ci(pr_number=run.pr_number)
    if classification == stages.CI_PASS:
        return None
    if classification == stages.CI_PENDING:
        return None  # CI 进行中：等下一轮。
    # CI_FAIL：打回回环 / 挂起。
    return _fail_gate(
        owner=owner,
        backend=backend,
        state=state,
        work_dir=work_dir,
        run=run,
        gate="ci",
        feedback="CI 红了，请据失败日志修复",
    )


def _route_e2e(
    *, owner: str, backend: Any, state: RuntimeState, work_dir: Path, run: Any
) -> dict | None:
    """e2e 三态：skip 放行；agent/human 读证据戳——陈旧/缺失时 agent 打回 / human 挂起。"""
    if owner == _SKIP:
        return None
    if stages.e2e(pr_number=run.pr_number) == stages.E2E_OK:
        return None
    return _fail_gate(
        owner=owner,
        backend=backend,
        state=state,
        work_dir=work_dir,
        run=run,
        gate="e2e",
        feedback="e2e 证据缺失或陈旧，请补齐成果证据",
    )


def _route_review(
    *, owner: str, backend: Any, state: RuntimeState, work_dir: Path, run: Any
) -> dict | None:
    """review 三态：skip 放行；human 挂起等人评审；agent 派 reviewer 判——PASS 放行、REWORK 打回 implementer。"""
    if owner == _SKIP:
        return None
    if owner == _HUMAN:
        _mark_blocked(state=state, run=run)
        return {"pr_number": run.pr_number, "reason": "blocked", "gate": "review"}
    issue_body = _issue_body_for(run=run)
    verdict = stages.review(
        backend=backend,
        work_dir=work_dir,
        pr_number=run.pr_number,
        issue_body=issue_body,
        context_text="",
    )
    if verdict["verdict"] == "PASS":
        return None
    return _fail_gate(
        owner=owner,
        backend=backend,
        state=state,
        work_dir=work_dir,
        run=run,
        gate="review",
        feedback=verdict["reason"],
    )


def _fail_gate(
    *,
    owner: str,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    run: Any,
    gate: str,
    feedback: str,
) -> dict:
    """CI/e2e/review 没过的统一打回回环：owner=agent 派 implementer 迭代（下轮从 conflict 重进）；human 挂 needs-human。

    **不再只 `return {"reason": gate}`**（旧栈 merge_pr 的真缺口）——agent 时真派 implementer 改代码、
    返阶段事件，下轮 advance_merge 从头（conflict）客观复检重进流水线（非原地重试：改完 base 可能又变）。
    """

    def _on_agent() -> dict:
        worktree = _ensure_pr_worktree(work_dir=work_dir, run=run)
        stages.implement(
            backend=backend,
            work_dir=worktree,
            issue_number=run.issue_number or 0,
            pr_number=run.pr_number,
            feedback=f"[{gate}] {feedback}",
            context_text="",
        )
        return {"pr_number": run.pr_number, "reason": gate}

    def _on_human() -> dict:
        _mark_blocked(state=state, run=run)
        return {"pr_number": run.pr_number, "reason": "blocked", "gate": gate}

    return route(owner=owner, on_agent=_on_agent, on_human=_on_human, on_skip=_on_human)


def _route_merge(*, owner: str, state: RuntimeState, run: Any) -> dict:
    """merge 三态（agent/human）：agent 自动合（CI 绿评审过后）+ 置 done + 关 issue / human 停等人点头（不可 skip）。"""
    pr_number = run.pr_number

    def _on_agent() -> dict:
        stages.merge(pr_number=pr_number)
        _mark_done(state=state, run=run)
        return {"pr_number": pr_number, "reason": "merged"}

    def _on_human() -> dict:
        return {"pr_number": pr_number, "reason": "hold-merge"}

    return route(owner=owner, on_agent=_on_agent, on_human=_on_human, on_skip=_on_human)


def _ensure_pr_worktree(*, work_dir: Path, run: Any) -> Path:
    """为打回回环的 implementer 迭代备好 PR 分支 worktree（承旧 iterate 的 ensure_worktree）。可 monkeypatch。"""
    return git.Workspace(work_dir=Path(work_dir)).ensure(
        issue_number=run.issue_number or 0, branch=run.branch or ""
    )


def _issue_body_for(*, run: Any) -> str:
    """读 run 归属 issue 的正文供 reviewer 上下文；无 issue 归属（open PR 迭代源）→ 空串。"""
    if run.issue_number is None:
        return ""
    return github.get_issue(number=run.issue_number).body


def _mark_done(*, state: RuntimeState, run: Any) -> None:
    """合并收口：知 issue 归属则置 done + 关 issue（幂等），否则只推进 PR（优雅降级）。"""
    if run.issue_number is None:
        return
    state.set_run(
        issue_number=run.issue_number,
        status=_STATUS_DONE,
        branch=run.branch,
        pr_number=run.pr_number,
    )
    github.close_issue(number=run.issue_number)


def _mark_blocked(*, state: RuntimeState, run: Any) -> None:
    """确定性挂起：知 issue 归属则置 blocked（下轮短路不重跑闸），否则降级 no-op。"""
    if run.issue_number is None:
        return
    state.set_run(
        issue_number=run.issue_number,
        status=_STATUS_BLOCKED,
        branch=run.branch,
        pr_number=run.pr_number,
    )


# --------------------------------------------------------------------------------------------------
# merge 迭代源投影 + run 数据类（承旧 merge_pr.Run / vigil._merge_runs）。
# --------------------------------------------------------------------------------------------------


class _Run:
    """merge 流水线的一条待推进记录——本地 run 投影（携 issue 归属，供合并/关 issue 回写 state）。"""

    def __init__(
        self, *, pr_number: int, issue_number: int | None, branch: str, status: str
    ) -> None:
        self.pr_number = pr_number
        self.issue_number = issue_number
        self.branch = branch
        self.status = status


def _merge_runs(*, state: RuntimeState) -> list[_Run]:
    """把本地 run 记录投影成合并流水线的 run 列表——只取已有 PR 号的在飞 run，携 issue 归属。

    无 pr_number（起草/求解中，尚无 PR）→ 跳过；blocked → blocked（短路）；其余当 open 交流水线推进。
    """
    runs: list[_Run] = []
    for record in state.list_runs():
        pr_number = record.get("pr_number")
        if pr_number is None:
            continue
        status = record.get("status", "")
        runs.append(
            _Run(
                pr_number=pr_number,
                issue_number=record.get("issue_number"),
                branch=record.get("branch", ""),
                status=_STATUS_BLOCKED if status == _STATUS_BLOCKED else "open",
            )
        )
    return runs


# --------------------------------------------------------------------------------------------------
# 主循环：run_vigil（发现段 + 守候段，每轮从 GitHub+State 重推进度，去中心、可重入）。
# --------------------------------------------------------------------------------------------------


def run_vigil(
    *,
    backend: Any,
    state: RuntimeState,
    work_dir: Path,
    config: agent_config.AgentConfig,
    once: bool,
    agent_id: str = "",
    dispatch: Callable[..., Any] | None = None,
    poll: Callable[[], Any] | None = None,
    merge: Callable[..., Any] | None = None,
    claim_expiry_seconds: int = CLAIM_EXPIRY_SECONDS,
    now_fn: Callable[[], datetime] | None = None,
) -> None:
    """守夜主循环：每轮 发现+分诊+派单（按 config.stages 三态路由）→ 守候（回应评论 + 推进合并）。

    `config` 是 T1 加载的 `AgentConfig`（单一真源：stages 三态 + agents 后端映射 + base/labels/interval）。
    `dispatch`/`poll`/`merge` 可注入（缺省内建默认）：dispatch 默认 dispatch_solve（带 config.stages）、
    poll 默认 poll_comments、merge 默认 merge_prs（据本地 run 投影 runs）。once=True 跑一轮即返回。
    确定性硬闸（head/证据/round_cap）恒在、不受 config.stages 管辖（内嵌于 stages 与 review 循环）。
    """
    stages_policy = config.stages
    resolved_dispatch = (
        dispatch if dispatch is not None else _default_dispatch(stages_policy=stages_policy)
    )
    resolved_poll = (
        poll
        if poll is not None
        else _default_poll(backend=backend, state=state, work_dir=work_dir, agent_id=agent_id)
    )
    resolved_merge = (
        merge
        if merge is not None
        else _default_merge(
            backend=backend, state=state, work_dir=work_dir, stages_policy=stages_policy
        )
    )
    resolved_now = now_fn or (lambda: datetime.now(UTC))
    interval = config.interval
    labels = config.labels
    base = config.base

    try:
        while True:
            try:
                now = resolved_now()
                discover_and_dispatch(
                    backend=backend,
                    state=state,
                    work_dir=work_dir,
                    stages_policy=stages_policy,
                    labels=labels,
                    base=base,
                    agent_id=agent_id,
                    dispatch=resolved_dispatch,
                    now=now,
                    claim_expiry_seconds=claim_expiry_seconds,
                )
                _watch(state=state, poll=resolved_poll, merge=resolved_merge, now=now)
            except Exception as exc:  # noqa: BLE001 —— 守夜第一要务是「活着进下一轮」
                if once:
                    raise
                _log(message=f"✗ 本轮守夜失败，跳过、{interval}s 后再扫一轮：{exc}")
            if once:
                return
            _log(message=f"… 守夜中，{interval}s 后再扫一轮（Ctrl-C 停止）")
            time.sleep(interval)
    except KeyboardInterrupt:
        _log(message="✓ 守夜人已停止（Ctrl-C）")
        return


def _watch(
    *,
    state: RuntimeState,
    poll: Callable[[], Any] | None,
    merge: Callable[..., Any] | None,
    now: datetime,
) -> None:
    """守候段：先回应评论（poll），再推进合并（merge 收携 issue 归属的 runs + 同轮 now）。次序固定。"""
    if poll is not None:
        poll()
    if merge is not None:
        merge(runs=_merge_runs(state=state), now=now)


def _default_dispatch(*, stages_policy: agent_config.StagePolicy) -> Callable[..., Any]:
    """默认派单偏函数——dispatch_solve 绑定本轮 stages 策略（rfc/review 归谁）。"""

    def _dispatch(
        *, issue_number: int, base: str, backend: Any, state: RuntimeState, work_dir: Path
    ) -> dict:
        return dispatch_solve(
            issue_number=issue_number,
            base=base,
            backend=backend,
            state=state,
            work_dir=work_dir,
            stages_policy=stages_policy,
        )

    return _dispatch


def _default_poll(
    *, backend: Any, state: RuntimeState, work_dir: Path, agent_id: str
) -> Callable[[], Any]:
    """默认守候回应偏函数——poll_comments 绑定依赖。"""

    def _poll() -> Any:
        return poll_comments(backend=backend, state=state, work_dir=work_dir, agent_id=agent_id)

    return _poll


def _default_merge(
    *, backend: Any, state: RuntimeState, work_dir: Path, stages_policy: agent_config.StagePolicy
) -> Callable[..., Any]:
    """默认合并推进偏函数——merge_prs 绑定依赖 + 本轮 stages 策略。"""

    def _merge(*, runs: list[Any], now: datetime) -> Any:
        return merge_prs(
            backend=backend,
            state=state,
            work_dir=work_dir,
            stages_policy=stages_policy,
            runs=runs,
            now=now,
        )

    return _merge


# --------------------------------------------------------------------------------------------------
# 多仓库统管：fleet 收编为「每仓一次 run_vigil 调用」（承旧 recipes.fleet，复用 utils.fleet 监管器）。
# --------------------------------------------------------------------------------------------------


def run_fleet(*, config: agent_config.AgentConfig, once: bool) -> None:
    """多仓库并发守夜（fleet 折入）：config.repos 每仓一子进程跑 run_vigil，复用 utils.fleet 进程监管器。

    为什么进程而非线程：gh/git 绑进程 cwd，一仓一进程才拿到 cwd 隔离 + 崩溃隔离 + 真并行（承旧 fleet
    论证）。单仓（repos 只一项）时父进程直接顺跑，不起子进程（理念 1 奥卡姆）。
    """
    from openagents.utils import fleet as fleet_util

    if len(config.repos) == 1:
        # 单仓库：直接在本进程跑（cwd 已是该仓，无需子进程隔离）。
        repo = config.repos[0]
        _run_repo_inline(repo=repo, agents=config.agents, release=config.release, once=once)
        return
    fleet_util.Fleet(spawn=_default_spawn, queue_factory=fleet_util.default_queue).run(
        plans=config.repos, once=once
    )


def _run_repo_inline(
    *,
    repo: agent_config.RepoPlan,
    agents: agent_config.AgentPolicy,
    release: agent_config.ReleasePolicy,
    once: bool,
) -> None:
    """在本进程跑单仓库 run_vigil——延迟 import cli 工厂构造 backend/state/身份（沿用「命令体内延迟 import」）。"""
    from openagents import cli
    from openagents.utils import config as config_mod

    ctx = config_mod.resolve_project()
    if ctx is None:
        raise RuntimeError(f"{repo.path} 不是 git 仓库，无法守夜")
    backend, state, agent_id = cli._vigil_deps_for(ctx=ctx)
    run_vigil(
        backend=backend,
        state=state,
        work_dir=ctx.repo_root,
        config=_repo_as_config(repo=repo, agents=agents, release=release),
        once=once,
        agent_id=agent_id,
    )


def _repo_as_config(
    *,
    repo: agent_config.RepoPlan,
    agents: agent_config.AgentPolicy,
    release: agent_config.ReleasePolicy,
) -> agent_config.AgentConfig:
    """把单个 RepoPlan 包成 run_vigil 需要的 AgentConfig（该仓 resolved stages + 顶层共享 agents/release）。"""
    return agent_config.AgentConfig(
        version=1,
        agents=agents,
        stages=repo.stages,
        release=release,
        interval=repo.interval,
        base=repo.base,
        labels=repo.labels,
        repos=[repo],
    )


def _run_repo_entry(*, plan: agent_config.RepoPlan, log_queue: Any, once: bool) -> None:
    """子进程真实入口：os.chdir 钉 cwd → 跑单仓 run_vigil，任何失败转一行干净日志 + 非零退出（承旧 fleet）。"""
    import os

    os.chdir(plan.path)
    from openagents.utils import fleet as fleet_util

    writer = fleet_util._QueueWriter(name=plan.name, log_queue=log_queue)
    original_stderr = sys.stderr
    sys.stderr = writer
    try:
        _run_repo_inline(
            repo=plan,
            agents=agent_config.AgentPolicy(backends={}),
            release=agent_config.ReleasePolicy(),
            once=once,
        )
    except KeyboardInterrupt:
        raise
    except BaseException as exc:  # noqa: BLE001 —— 子进程兜底：任何失败转干净一行
        log_queue.put((plan.name, f"✗ 守夜失败：{exc}"))
        raise SystemExit(1) from exc
    finally:
        writer.flush()
        sys.stderr = original_stderr


def _default_spawn(*, plan: agent_config.RepoPlan, log_queue: Any, once: bool) -> Any:
    """真正起一个子进程跑 `_run_repo_entry`（承旧 fleet.default_spawn；RepoPlan 可 pickle 满足 spawn）。"""
    import multiprocessing

    process = multiprocessing.Process(
        target=_run_repo_entry,
        kwargs={"plan": plan, "log_queue": log_queue, "once": once},
        name=plan.name,
        daemon=True,
    )
    process.start()
    return process


# --------------------------------------------------------------------------------------------------
# 认领便签解析（纯函数，承旧 vigil._latest_claim/_claim_expired）。
# --------------------------------------------------------------------------------------------------


def _latest_claim(*, comments: list[Any]) -> tuple[str, str] | None:
    """从 issue 评论解析最近一条署名认领便签的 (owner, created_at)；无有效便签 → None（纯函数）。"""
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
    """认领便签是否过期：`now - created_at` 秒龄 > 阈值 → True（僵尸认领可回收）。纯函数、不读墙钟。"""
    if not created_at:
        return False
    try:
        stamped = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (now - stamped).total_seconds() > threshold


def _log(*, message: str) -> None:
    """守夜进度打到 stderr，保证无人值守时仍有可观测轨迹（承旧 vigil._log）。"""
    print(message, file=sys.stderr, flush=True)
