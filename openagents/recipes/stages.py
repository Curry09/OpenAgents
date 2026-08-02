"""# Spec-0064/T2: recipes.stages —— 九个阶段抽成 `Vigil` 类外的独立自由函数（可单独寻址）。

现状 `review` 焊在 `solve_issue` 的 for 循环、`triage` 焊在 `Vigil` 类方法里、合并各闸埋在
`merge_pr._advance_merge` 里——阶段不可单独寻址，就没法对它设「谁把关」。本模块把
`triage / rfc / implement / conflict / ci / e2e / review / deliver / merge` 九个阶段从
`solve_issue` / `merge_pr` / `poll_comments` **逐字重立**为独立自由函数（旧文件零改动、additive），
各自**显式收参**（关键字-only、无位置参数、private 无默认值，符合 CLAUDE.md 约定），供 T3
`run_vigil` 按 `stages` 三态策略路由组合。

分界线（承 Spec-0060/0061/0062，逐字一致）：
- **judgment 段派既有 agent**（经 `engine.run_agent` 出结构化裁决）：triage→triager、rfc→drafter、
  implement→implementer、review→reviewer、conflict/deliver→deliver；
- **机械段走确定性 `utils`/`gates`**（读客观事实）：ci 读 github check + gates 分类、e2e 读证据溯源戳；
  merge 是「确定性硬闸兜底 + 下放 merger agent」（Spec-0017/T3：`gates.assert_merge_allowed` 把守不可逆
  红线后，动作下放 merger agent 落 `gh pr merge`）。**三态 `agent`/`human`/`skip` 是「这道闸归谁」而非
  「谁执行检测」**——`ci: agent`
  指「自动化拥有此闸、红了自动打回 implementer」，检测仍是客观读 check（见 spec 分界线）。

`rfc` 阶段收敛 `planner`+`drafter` 为**单一起草函数**——只依赖 `drafter`（承接五 mode 起草判断），
`planner` 是重复死代码（T6 删）。交付类阶段（rfc/deliver）内嵌三道确定性硬闸兜底 agent 自述：交付前
基点由本模块经 `gates.snapshot_head` **确定性记录**（不信 agent 自述 base_sha，防 #140 报假基点让闸恒
放行）、交付后 `assert_head_advanced` 断言 head 真前移 + `assert_evidence_stamp` 断言自报 head_sha 与
实际 HEAD 一致。

所有依赖（backend / github / gates / engine）可注入或 monkeypatch，hermetic 可测（不触真实 LLM/网络/仓库）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openagents.agents import admitter, drafter, implementer, merger, reviewer, triager
from openagents.agents import deliver as deliver_agent
from openagents.runtime import context, engine, gates
from openagents.runtime.context import Context

# Spec-0074/T1: alias-import 换轨——平台操作经 forge 分发层按配置委托 github/gitea driver，调用点零改动。
from openagents.utils import forge as github

# Spec-0064/T2: drafter 起草模式字面量（承 recipes.rfc_lifecycle._MODE_*）——rfc 阶段 draft、backfill
# recipe（T4）复用本函数传 backfill。仅这两种进本阶段函数（refine/implement/iterate 已由独立阶段承接）。
MODE_DRAFT = "draft"
MODE_BACKFILL = "backfill"

# Spec-0064/T2: ci / e2e 机械闸的分类字面量——T3 据此路由（fail/pending→打回或等，pass/ok→放行）。
CI_FAIL = "fail"
CI_PENDING = "pending"
CI_PASS = "pass"
E2E_STALE = "e2e"  # 证据戳缺失/陈旧/张冠李戴 → 该回去补 e2e（对齐 merge_pr 的 "e2e" 事件）
E2E_OK = "ok"


# --------------------------------------------------------------------------------------------------
# judgment 段：派既有 agent 出结构化裁决（本模块自身零业务判断，只组占位符 + 调 engine）。
# --------------------------------------------------------------------------------------------------


def triage(*, backend: Any, work_dir: Path, issue: Any) -> dict:
    """分诊阶段（triager agent）：判 issue 可不可派单，返回裁决 {actionable, reason}。承 vigil.discover 的分诊段。

    入参 `issue` 是发现段 `github.list_issues` 已拉到的 Issue（含 number/title/body），经
    `context.for_triage` 组占位符，不二次读 github。fail-open（拿不准判 actionable=True）在 triager
    prompt 内；本函数零判断。
    """
    return engine.run_agent(
        triager,
        backend=backend,
        **context.for_triage(work_dir=Path(work_dir), issue=issue),
    )


def admit(*, backend: Any, work_dir: Path, issue: Any, dialogue: str) -> dict:
    """准入裁决阶段（admitter agent）：读人在准入对话里的回话，判**人点头没有** → {approved, reason}。

    `triage: human` 专用（见 vigil `_ask_human`）。**不是 triage 的同义词**：triage 判「issue 正文自不
    自洽」且 fail-open（拿不准就放行），admit 判「人同意了吗」且 **fail-closed**（拿不准就当没点头）。
    拿 triager 顶这个位子，人明说「先别做」也会被放行——那道人闸会当场退化成一台偏向「是」的 agent 闸。
    纪律在 admitter prompt 内；本函数零判断。
    """
    return engine.run_agent(
        admitter,
        backend=backend,
        **context.for_admit(work_dir=Path(work_dir), issue=issue, dialogue=dialogue),
    )


def rfc(
    *,
    backend: Any,
    worktree: Path,
    mode: str,
    target: str,
    branch: str,
    detail: str,
    context_text: str,
    require_delivered: bool,
) -> dict:
    """起草阶段（drafter agent，**单一起草函数**）：据 issue 起草 / 据代码反推 spec，返回 {delivered, head_sha, summary}。

    收敛 planner+drafter 为单一起草函数——**只依赖 drafter**（planner 是重复死代码，T6 删）。`mode`
    ∈ {draft, backfill}：draft 据 issue 起草（require_delivered=False），backfill 据存量代码反推
    （require_delivered=True，未过 spec validate 则 delivered=false，caller 据此不开 PR）。内嵌三道
    确定性硬闸兜底交付自述（见模块 docstring）。
    """
    return _deliver_gated(
        agent_module=drafter,
        backend=backend,
        worktree=Path(worktree),
        placeholders={
            "context": context_text,
            "mode": mode,
            "target": target,
            "branch": branch,
            "detail": detail,
        },
        require_delivered=require_delivered,
    )


def implement(
    *,
    backend: Any,
    work_dir: Path,
    issue_number: int,
    pr_number: int,
    feedback: str,
    context_text: str,
) -> dict:
    """实现阶段（implementer agent）：按获批 spec 写码 / 据反馈迭代，返回 {summary}。承 solve_issue 的 implement/iterate。

    `feedback` 空 = 首轮实现、非空 = 据 reviewer/CI/e2e 反馈迭代（同模块两用，靠占位符区分，零控制流）。
    恒 agent（写码永远派 agent、不进 stages 策略点，见 T1 _ALWAYS_AGENT_STAGES）；也是 T3 CI/e2e/review
    三闸打回回环派去改代码的那个 agent。
    """
    return engine.run_agent(
        implementer,
        backend=backend,
        work_dir=Path(work_dir),
        context=context_text,
        issue_number=issue_number,
        pr_number=pr_number,
        feedback=feedback,
    )


def review(
    *,
    backend: Any,
    work_dir: Path,
    pr_number: int,
    issue_body: str,
    context_text: str,
) -> dict:
    """评审阶段（reviewer agent）：判这版能不能过评审，返回 {verdict, reason}（PASS/REWORK）。承 solve_issue/merge_pr 的 review。

    「这版能不能合」是主观判断，故下放 reviewer；本函数零判断，只组占位符 + 调 engine。REWORK 时由
    T3 派 implementer 迭代（打回回环）。
    """
    return engine.run_agent(
        reviewer,
        backend=backend,
        work_dir=Path(work_dir),
        context=context_text,
        pr_number=pr_number,
        issue_body=issue_body,
    )


def deliver(
    *,
    backend: Any,
    worktree: Path,
    branch: str,
    pr_number: int,
    issue_number: int,
    context_text: str = "",
) -> dict:
    """交付阶段（deliver agent）：commit/push 把改动落到 PR head，返回交付报告 {delivered, head_sha, ...}。承 solve_issue 的 deliver。

    恒 agent（git 交付永远派 agent、不进 stages 策略点）。内嵌三道确定性硬闸兜底（见模块 docstring）——
    交付前基点确定性记录、交付后断言 head 前移 + 证据戳一致，防 #140 空转/张冠李戴。

    # Spec-0065/T2: `context_text` 追加进 agent 上下文（缺省空串 = 既有调用方零变化）。守夜用它把
    # 「一等出口 needs-human」契约拼进解冲突 agent 的提示词——冲突解不动是它最该主动交人的场景之一。
    """
    ctx = Context(
        work_dir=Path(worktree),
        issue_number=issue_number,
        branch=branch,
        pr_number=pr_number,
    )
    placeholders = ctx.for_deliver(issue_number=issue_number)
    placeholders["context"] = f"{placeholders['context']}{context_text}"
    return _deliver_gated(
        agent_module=deliver_agent,
        backend=backend,
        worktree=Path(worktree),
        placeholders=placeholders,
        require_delivered=False,
    )


def conflict(
    *,
    backend: Any,
    work_dir: Path,
    pr_number: int,
    issue_number: int,
    branch: str,
    context_text: str = "",
) -> dict:
    """冲突解决阶段（deliver agent 去 rebase）：读冲突/判双方意图/自测下放 agent，返回 {delivered, reason}。承 merge_pr._resolve_conflict。

    backend 为 None → 回落人工（reason=unmergeable、delivered=False）；有则派 deliver agent rebase 解
    冲突——delivered=True → resolved（下轮 mergeability 客观复检确认，谎报则下轮仍 DIRTY 自然重试）；
    delivered=False → blocked（挂起等人，gate=conflict）。本函数自身零 git 直调（走 agent），零 state 写
    （state 归属 T3 编排）。
    """
    if backend is None:
        return {"delivered": False, "reason": "unmergeable"}
    resolved_branch = branch or github_pr_head_branch(pr_number=pr_number)
    report = deliver(
        backend=backend,
        worktree=Path(work_dir),
        branch=resolved_branch,
        pr_number=pr_number,
        issue_number=issue_number,
        context_text=context_text,  # Spec-0065/T2: 透传一等出口契约（守夜传，其它调用方缺省空串）
    )
    if report["delivered"]:
        return {"delivered": True, "reason": "resolved"}
    return {"delivered": False, "reason": "blocked", "gate": "conflict"}


# --------------------------------------------------------------------------------------------------
# 机械段：读客观事实经 gates 分类（ci/e2e）/ 调 github 落地（merge）。零业务判断、零 LLM。
# --------------------------------------------------------------------------------------------------


def ci(*, pr_number: int) -> str:
    """CI 闸（确定性读 github check + gates 分类）：返回 fail/pending/pass。承 merge_pr 的 CI 段。

    **不是「agent 判 CI」**——检测恒是客观读 check 的 conclusion；`stages.ci=agent` 只表示「红了自动
    打回 implementer」（T3 路由），本函数只读客观事实分类。
    """
    status = github.check_status(pr_number=pr_number)
    if gates.ci_failed(check_status=status):
        return CI_FAIL
    if gates.ci_pending(check_status=status):
        return CI_PENDING
    return CI_PASS


def e2e(*, pr_number: int) -> str:
    """e2e 闸（确定性读证据溯源戳 + gates 判读）：返回 e2e（该补）/ ok（放行）。承 merge_pr 的 e2e 证据段。

    读 PR 的 e2e 证据戳 `(实际 head, 证据自述 head)`——无证据要求（seam 默认 None）→ 放行（ok）；有戳
    但 `gates.evidence_stamp_ok` 判不匹配（缺证据/陈旧/张冠李戴）→ e2e（T3 派 implementer 补）。证据
    接线点单一 seam `_pr_evidence_stamp`，测试可 monkeypatch 注入戳。
    """
    stamp = _pr_evidence_stamp(pr_number=pr_number)
    if stamp is None:
        return E2E_OK
    if not gates.evidence_stamp_ok(head_sha=stamp[0], claimed=stamp[1]):
        return E2E_STALE
    return E2E_OK


def merge(
    *,
    backend: Any,
    pr_number: int,
    head_sha: str,
    work_dir: Path,
    context_text: str,
) -> dict:
    """合并阶段（Spec-0017/T3：确定性硬闸兜底 + 下放 merger agent）：返回 merger 报告 {merged, summary}。

    合并**不可逆**，故形态是「先闸后 agent」：
    1. 先经确定性 `gates.assert_merge_allowed(pr_number, head_sha)` **实时复读** CI + label 把守红线——不放行
       即抛 `GateError`，**决不派 agent**（agent 只能在闸放行后才被派上来落合并动作，防误派/TOCTOU 合未审代码）；
    2. 放行后经 `engine.run_agent` 派 merger agent 落 `gh pr merge`——把「动作」下放 agent（承 Spec-0064 动作
       全归 agent 层），merger 另带 `needs-human` 一等出口察觉硬闸没覆盖的异常。

    「要不要停下等人」（hold/merge:human）由调用方在调本函数前判；本函数只在闸放行后落合并动作、零业务判断。
    """
    gates.assert_merge_allowed(pr_number=pr_number, head_sha=head_sha)
    return engine.run_agent(
        merger,
        backend=backend,
        work_dir=Path(work_dir),
        context=context_text,
        pr_number=pr_number,
        # Spec-0074/T1: 平台命令按当前 forge 注入（GitHub=gh 原命令零变化；Gitea=openagents merge-pr）。
        merge_command=github.merge_command_text(pr_number=pr_number),
        verify_command=github.merge_verify_command_text(pr_number=pr_number),
    )


# --------------------------------------------------------------------------------------------------
# 内部：交付类阶段共用的三道硬闸兜底骨架 + e2e 证据 seam + github 薄引用。
# --------------------------------------------------------------------------------------------------


def _deliver_gated(
    *,
    agent_module: Any,
    backend: Any,
    worktree: Path,
    placeholders: dict,
    require_delivered: bool,
) -> dict:
    """派交付类 agent（drafter/deliver）+ 三道确定性硬闸兜底——rfc/deliver/conflict 共用（承 rfc_lifecycle._run_drafter / solve_issue 交付段）。

    交付前基点经 `gates.snapshot_head` 确定性记录（不信 agent 自述）；`require_delivered=True`（backfill
    validate 门控）时先据 agent 自述 delivered 短路——未交付即原样返回（caller 据此不开 PR、不进硬闸）；
    否则 `assert_head_advanced` + `assert_evidence_stamp` 兜底。engine 保留字 work_dir/context 从
    placeholders 取（context 必在 placeholders 里）。
    """
    before = gates.snapshot_head(workspace=Path(worktree))
    # placeholders 可能已含 work_dir（如 Context.for_deliver 产出）——统一以本函数的 worktree 为准，
    # 剔除 placeholders 里的 work_dir 避免与显式传参重复（engine 保留字 work_dir 单一来源）。
    payload = {key: value for key, value in placeholders.items() if key != "work_dir"}
    verdict = engine.run_agent(agent_module, backend=backend, work_dir=Path(worktree), **payload)
    if require_delivered and not verdict["delivered"]:
        return verdict
    after = gates.assert_head_advanced(before=before, workspace=Path(worktree))
    gates.assert_evidence_stamp(head_sha=after, claimed=verdict["head_sha"])
    return verdict


def _pr_evidence_stamp(*, pr_number: int) -> tuple[str, str] | None:
    """读 PR 的 e2e 证据溯源戳 `(实际 head, 证据自述 head)`；无证据要求 → None（e2e 闸放行）。承 merge_pr._pr_evidence_stamp。

    新栈尚未接 executor 真跑 e2e（承 Spec-0061 同一 Unresolved），故默认恒返回 None、e2e 闸放行；T3
    接线 / 测试可 monkeypatch 本函数注入戳，驱动 `gates.evidence_stamp_ok` 判读。单一 seam 使证据闸接
    线点明确、不散落进主控制流。
    """
    return None


def github_pr_head_branch(*, pr_number: int) -> str:
    """薄引用 `github.pr_head_branch`——conflict 阶段无 branch 归属时的兜底读（单点便于测试 monkeypatch）。"""
    return github.pr_head_branch(pr_number=pr_number)
