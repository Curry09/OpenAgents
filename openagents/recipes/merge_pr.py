"""# Spec-0062/T2: recipes.merge_pr —— PR 合并流水线（纯控制流，零业务判断）。

新栈把旧 `messages.poll` 的 964 行阶段状态机（mergeability 预检 / CI 闸 / e2e 证据闸 / review /
merge + hold/skip 对称短路 + closed-run 复活 + 冲突自愈）按既定分界线重立为一条**纯控制流** recipe：

- **确定性闸留 recipe/`runtime.gates`**（读客观事实、非判断）：可合并性预检（GitHub 的 mergeable 位）、
  CI 结论读取（check 的 conclusion）、e2e 证据溯源戳（head_sha 匹配否）、hold/skip 命中（配置里有没有）、
  closed-run 复活窗口（closed_at 比不比阈值新）——全部经 `gates.*` 判读，本 recipe 只按判读结果路由。
- **「这版能不能合」的判断走既有 `reviewer` agent**（经 `engine.run_agent`）；
- **「冲突怎么 rebase 解」走既有 git delivery（`deliver`）agent**——把冲突读/双方意图判/自测下放 agent，
  recipe 自身绝不碰 git/gh/subprocess（那是 utils / agent 的活）。

返回与旧 poll **同构**的事件列表，reason 词表对齐旧 poll（`merged/closed/reopened/resolved/unmergeable/
blocked/ci/e2e/review/synced/behind-conflict/hold-merge/skip-ci/skip-code/error`），便于日志与断言复用。
单 PR 处理失败只追加一条 `error` 事件并 continue，绝不让异常掀翻整轮（错误隔离，对齐旧 messages.poll）。

与旧 poll 的差异（见本文件末 `merge_pr` docstring 与交付说明）：新栈 `RuntimeState` 不持久化
rounds/block_gate 等富状态，故「review REWORK 攒满 K 轮才 blocked」的跨轮回合预算暂不复现——review
REWORK 本轮返 `review` 事件，blocked 只由「冲突无法自愈」这一确定性终态触发；深度回合治理留后续批次。
所有依赖（backend / state / gates / github）可注入或 monkeypatch，hermetic 可测（不触真实 LLM/网络/仓库）。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openagents.agents import deliver, reviewer
from openagents.runtime import engine, gates
from openagents.runtime.context import Context
from openagents.runtime.state import RuntimeState
from openagents.utils import github
from openagents.utils.hold import NONE as NO_HOLD
from openagents.utils.hold import Hold
from openagents.utils.skip import NONE as NO_SKIP
from openagents.utils.skip import Skip

# Spec-0062/T2: 新栈 run 极简三态字面量（与 recipes.vigil 一致）——复活/合并/挂起时落 RuntimeState。
_STATUS_OPEN = "open"
_STATUS_DONE = "done"
_STATUS_BLOCKED = "blocked"


@dataclass(frozen=True)
class Run:
    """# Spec-0062/T2: merge_pr 迭代的一条待推进记录——旧 messages.RunRecord 的最小投影。

    `pr_number` 必填；`issue_number`/`branch` 用于合并/复活/挂起时回写 RuntimeState 与关 issue，
    默认 open PR 迭代源（`github.list_open_prs`）取不到 issue 归属时留空（None/""），此时状态回写
    优雅降级（只推进 PR、不回写 run），由上层（vigil T3）注入带 issue 归属的 runs 才做完整回写。
    `status` ∈ {open, blocked, closed}——closed 为复活候选（`closed_at` 携复活窗口判读的时间戳）。
    """

    pr_number: int
    issue_number: int | None = None
    branch: str = ""
    status: str = _STATUS_OPEN
    closed_at: str = ""


def merge_pr(
    *,
    backend: Any,
    state: RuntimeState,
    agent_id: str,
    work_dir: Path,
    hold: Hold = NO_HOLD,
    skip: Skip = NO_SKIP,
    runs: list[Run] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """扫一轮待推进的 PR，按确定性闸路由推进合并，返回本轮事件列表（reason 对齐旧 messages.poll）。

    `runs` 是迭代源（open / blocked / closed 复活候选）：None 时默认从 `github.list_open_prs()` 派生
    （每个 open PR → 一条 open Run，无 issue 归属）；上层可注入带 issue 归属 / closed 候选的 runs。
    `hold`/`skip` 为默认「全不停 / 全不跳」的值对象，命中即在对应闸对称短路（hold=停下等人、skip=当
    PASS 放行）。`now` 供复活窗口判读（默认取 UTC 墙钟；测试可注入定值 hermetic 可测）。

    每个事件形如 `{"pr_number": int, "reason": <reason>, ...}`。单 PR 处理失败（gh/agent 异常）只记
    一条 `{"reason": "error", "error": str}` 事件并 continue——错误隔离，绝不让异常掀翻整轮（对齐旧 poll）。
    """
    resolved_now = now if now is not None else datetime.now(UTC)
    candidates = (
        runs if runs is not None else [Run(pr_number=pr.number) for pr in github.list_open_prs()]
    )
    events: list[dict] = []
    for run in candidates:
        try:
            event = _process_run(
                run=run,
                backend=backend,
                state=state,
                agent_id=agent_id,
                work_dir=Path(work_dir),
                hold=hold,
                skip=skip,
                now=resolved_now,
            )
        except Exception as error:  # noqa: BLE001 —— 错误隔离：单 PR 失败不拖垮整轮
            events.append({"pr_number": run.pr_number, "reason": "error", "error": str(error)})
            continue
        if event is not None:
            events.append(event)
    return events


def _process_run(
    *,
    run: Run,
    backend: Any,
    state: RuntimeState,
    agent_id: str,
    work_dir: Path,
    hold: Hold,
    skip: Skip,
    now: datetime,
) -> dict | None:
    """处理单条 run：merged/closed 终态优先 reconcile，closed 查复活，blocked 短路，其余走合并流水线。

    次序逐字对齐旧 messages._process_run：① is_merged 优先于一切（合并不可逆）；② closed 候选查
    reopen（复活）；③ is_closed（open→closed 转移）落终态；④ blocked 短路（解挂是 replier 的活，
    merge_pr 只对它做终态 reconcile、不重跑闸，防震荡）；⑤ 其余走 `_advance_merge` 合并流水线。
    """
    pr_number = run.pr_number
    # ① 已合并优先：置 done + 关 issue（若知 issue 归属），跳过（对齐旧 poll 决策 8）。
    if github.is_merged(pr_number=pr_number):
        _mark_done(run=run, state=state)
        return {"pr_number": pr_number, "reason": "merged"}
    # ② closed 复活候选：查它对应的 PR 是否已被 reopen（放在 is_closed 之前，已 closed 的 run 走复活分支）。
    if run.status == _STATUS_BLOCKED:
        return None  # blocked 短路：解挂走 replier 的评论回应，merge_pr 不重跑闸（对齐旧 poll 软挂起）。
    if run.status not in (_STATUS_OPEN,):
        return _revive_if_reopened(run=run, state=state, now=now)
    # ③ 人主动关闭（未合并）也是终止信号——本轮 run 仍标 open 但 PR 已 closed → 落 closed（merged 优先）。
    if github.is_closed(pr_number=pr_number):
        return {"pr_number": pr_number, "reason": "closed"}
    # ⑤ 仍 open：走合并流水线（mergeability → CI → e2e → review → merge）。
    return _advance_merge(
        run=run,
        backend=backend,
        state=state,
        agent_id=agent_id,
        work_dir=work_dir,
        hold=hold,
        skip=skip,
    )


def _revive_if_reopened(*, run: Run, state: RuntimeState, now: datetime) -> dict | None:
    """Spec-0062/T2: closed 复活候选的 reconcile——窗口内且 PR 已 reopen 则复活归位，否则保持跳过。

    确定性判读：复活窗口（`gates.revive_eligible`，读 closed_at vs 阈值）→ 窗口外/无戳直接 None；
    窗口内再查 PR 是否 OPEN（`github.is_open`）——仍非 OPEN → None（保持跳过、不重打戳、成本有界）；
    已 OPEN → 按 draft 与否推断复活阶段（draft→rfc-review、已转正→pr-open），回写 run 为 open。
    复活只做状态归位、当轮返回 `reopened` 事件不续跑闸——下一轮该 run 已是正常 open run 走既有路径。
    """
    pr_number = run.pr_number
    if not gates.revive_eligible(closed_at=run.closed_at, now=now):
        return None
    if not github.is_open(pr_number=pr_number):
        return None
    stage = "rfc-review" if github.is_draft(pr_number=pr_number) else "pr-open"
    if run.issue_number is not None:
        state.set_run(
            issue_number=run.issue_number,
            status=_STATUS_OPEN,
            branch=run.branch,
            pr_number=pr_number,
        )
    return {"pr_number": pr_number, "reason": "reopened", "stage": stage}


def _advance_merge(
    *,
    run: Run,
    backend: Any,
    state: RuntimeState,
    agent_id: str,
    work_dir: Path,
    hold: Hold,
    skip: Skip,
) -> dict | None:
    """合并流水线（对齐旧 messages._process_coding 的 Spec-0055/T6 重排次序）：
    ①mergeability → ②CI → ③e2e 证据戳 → ④review → ⑤merge。

    每道闸都先经 `gates.*` **读客观事实判读**，再据判读路由：需判断处（这版能不能合）派 reviewer
    agent，需解冲突处派 deliver agent；hold/skip 命中即在对应闸对称短路。本函数自身零业务判断、零 git/gh 直调。
    """
    pr_number = run.pr_number

    # ① 可合并性预检（跑 reviewer 前先短路真冲突的 PR——越早越省）。
    merge_state = github.mergeability(pr_number=pr_number)
    if gates.is_conflicting(mergeability=merge_state):
        return _resolve_conflict(
            run=run, backend=backend, state=state, agent_id=agent_id, work_dir=work_dir
        )
    if gates.is_mergeable_unknown(mergeability=merge_state):
        return None  # GitHub 异步尚未算完（刚 push 常见）：本轮不推进、下轮重查。
    if gates.is_behind(mergeability=merge_state):
        # 拉式同步：落后 base 无冲突 → update_branch 并入最新 base 触发 CI 在集成态重跑；撞冲突则下轮 DIRTY。
        try:
            github.update_branch(pr_number=pr_number)
        except github.GithubError:
            return {"pr_number": pr_number, "reason": "behind-conflict"}
        return {"pr_number": pr_number, "reason": "synced"}

    # ② CI 闸（skip.at_ci 旁路）。
    if gates.skip_hits(skip=skip, gate="ci"):
        _log(message=f"⏭ PR #{pr_number}：--skip ci，把 CI 当全绿放行")
    else:
        status = github.check_status(pr_number=pr_number)
        if gates.ci_failed(check_status=status):
            return {"pr_number": pr_number, "reason": "ci"}
        if gates.ci_pending(check_status=status):
            return None  # CI 进行中：等下一轮（不评审、不动状态）。

    # ③ e2e 证据溯源戳闸（skip.at_evidence 旁路）——证据是 review 的对象之一，故在 review 前。
    if not gates.skip_hits(skip=skip, gate="evidence"):
        stamp = _pr_evidence_stamp(pr_number=pr_number)
        if stamp is not None and not gates.evidence_stamp_ok(head_sha=stamp[0], claimed=stamp[1]):
            return {"pr_number": pr_number, "reason": "e2e"}

    # ④ 代码评审闸（skip.at_code 旁路）——「这版能不能合」的判断下放 reviewer agent。
    if gates.skip_hits(skip=skip, gate="code"):
        return _finish_merge(run=run, state=state, hold=hold, reason_when_held="skip-code")
    verdict = engine.run_agent(
        reviewer,
        backend=backend,
        **_review_placeholders(work_dir=work_dir, run=run),
    )
    if verdict["verdict"] == "PASS":
        return _finish_merge(run=run, state=state, hold=hold, reason_when_held="hold-merge")
    # ⑤ 非 PASS：本轮返 review 事件（携 reviewer 反馈）。新栈 RuntimeState 无跨轮 rounds 预算，
    # 「攒满 K 轮才 blocked」暂不复现（见模块 docstring / 交付说明）——blocked 只由冲突无法自愈触发。
    return {"pr_number": pr_number, "reason": "review", "feedback": verdict["reason"]}


def _finish_merge(*, run: Run, state: RuntimeState, hold: Hold, reason_when_held: str) -> dict:
    """评审通过后收口：hold.at_merge 命中 → 夯住待人合并（不自动 merge）；否则 merge_pr + 置 done。

    `reason_when_held` 区分「因 --hold merge 夯住」（hold-merge）与「因 --skip code 放行后仍夯住」
    （skip-code）——两条都走 hold.at_merge 判读，命中即不自动合并、返对应短路事件（对称短路）。
    """
    pr_number = run.pr_number
    if gates.hold_hits(hold=hold, gate="merge"):
        return {"pr_number": pr_number, "reason": reason_when_held}
    github.merge_pr(pr_number=pr_number)
    _mark_done(run=run, state=state)
    return {"pr_number": pr_number, "reason": "merged"}


def _resolve_conflict(
    *,
    run: Run,
    backend: Any,
    state: RuntimeState,
    agent_id: str,
    work_dir: Path,
) -> dict:
    """冲突自愈：无 backend → 回落人工（unmergeable）；有则派 git delivery（deliver）agent 去 rebase 解。

    「冲突怎么 rebase 解」是需判断的操作（读冲突标记、判双方意图、跑自测），故下放既有 deliver agent；
    本 recipe 只据 deliver 的结构化裁决路由：delivered=True → resolved（下轮 mergeability 客观复检确认，
    若 agent 谎报未真解则下轮仍 DIRTY、自然重试——objective 复检兜底，无需在此加 head 前移硬闸）；
    delivered=False → blocked（挂起等人，block_gate=merge，对齐旧 poll 的 _block(gate=merge)）。
    """
    pr_number = run.pr_number
    if backend is None:
        _mark_blocked(run=run, state=state)
        return {"pr_number": pr_number, "reason": "unmergeable"}
    branch = run.branch or github.pr_head_branch(pr_number=pr_number)
    ctx = Context(
        work_dir=work_dir,
        issue_number=run.issue_number or 0,
        branch=branch,
        pr_number=pr_number,
    )
    report = engine.run_agent(
        deliver, backend=backend, **ctx.for_deliver(issue_number=run.issue_number or 0)
    )
    if report["delivered"]:
        return {"pr_number": pr_number, "reason": "resolved"}
    _mark_blocked(run=run, state=state)
    return {"pr_number": pr_number, "reason": "blocked", "gate": "merge"}


def _review_placeholders(*, work_dir: Path, run: Run) -> dict:
    """组装 reviewer agent 的占位符：work_dir + PR 编号 + issue 正文（无 issue 归属则留空）。

    reviewer PROMPT 需 `pr_number` / `issue_body` 两个占位符；issue 正文仅在 run 携 issue 归属时经
    `github.get_issue` 读（open PR 迭代源无归属 → 空串，reviewer 仍在 work_dir 内亲看 PR 改动评审）。
    """
    issue_body = "" if run.issue_number is None else github.get_issue(number=run.issue_number).body
    return {
        "work_dir": Path(work_dir),
        "context": "",
        "pr_number": run.pr_number,
        "issue_body": issue_body,
    }


def _pr_evidence_stamp(*, pr_number: int) -> tuple[str, str] | None:
    """读 PR 的 e2e 证据溯源戳 `(实际 head, 证据自述 head)`；无证据要求 → None（e2e 闸放行）。

    新栈尚未接 executor 真跑 e2e（承 Spec-0061 同一 Unresolved，本批不含），故默认恒返回 None、
    e2e 闸放行；vigil 接线 / 测试可 monkeypatch 本函数注入戳，驱动 `gates.evidence_stamp_ok` 判读
    走 "e2e" 路由。留此单一 seam 使证据闸接线点明确、不散落进主控制流。
    """
    return None


def _mark_done(*, run: Run, state: RuntimeState) -> None:
    """确定性收口：知 issue 归属则置 run=done + 关 issue（幂等），否则只推进 PR（优雅降级）。"""
    if run.issue_number is None:
        return
    state.set_run(
        issue_number=run.issue_number,
        status=_STATUS_DONE,
        branch=run.branch,
        pr_number=run.pr_number,
    )
    github.close_issue(number=run.issue_number)


def _mark_blocked(*, run: Run, state: RuntimeState) -> None:
    """确定性挂起：知 issue 归属则置 run=blocked（下轮经 blocked 分支短路、不重跑闸），否则降级 no-op。"""
    if run.issue_number is None:
        return
    state.set_run(
        issue_number=run.issue_number,
        status=_STATUS_BLOCKED,
        branch=run.branch,
        pr_number=run.pr_number,
    )


def _log(*, message: str) -> None:
    """守候进度打到 stderr，保证无人值守时仍有可观测轨迹（与 recipes.poll_comments/vigil 同通道）。"""
    print(message, file=sys.stderr, flush=True)
