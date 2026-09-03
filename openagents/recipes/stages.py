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

import hashlib
import json
from pathlib import Path
from typing import Any

from openagents.agents import (
    acceptance as acceptance_agent,
)
from openagents.agents import (
    architect,
    drafter,
    executor,
    implementer,
    merger,
    reviewer,
    spec_writer,
    triager,
)
from openagents.agents import deliver as deliver_agent
from openagents.runtime import context, engine, gates, research
from openagents.runtime import evidence as evidence_validation
from openagents.runtime.context import Context
from openagents.spec import model as spec_model
from openagents.spec import validate as spec_validate

# Spec-0074/T1: alias-import 换轨——平台操作经 forge 分发层按配置委托 github/gitea driver，调用点零改动。
from openagents.utils import forge as github
from openagents.utils.workspace import Workspace

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
    evidence_pack: list | None = None,
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
            "context": context.sections(
                ("detail", detail),
                (
                    "runtime context",
                    _with_evidence(context_text=context_text, evidence_pack=evidence_pack),
                ),
            ),
            "mode": mode,
            "target": target,
            "branch": branch,
        },
        require_delivered=require_delivered,
        resume_branch=branch,
    )


def minimal_spec(
    *,
    backend: Any,
    worktree: Path,
    issue_number: int,
    issue_title: str,
    issue_body: str,
    branch: str,
    context_text: str,
) -> dict:
    """Create one compact Spec or return an explicit objective-level blocker.

    Spec-0082/T1: BLOCKED is a valid terminal judgment and therefore does not have to advance HEAD;
    READY and PARTIAL artifacts use the same delivery/evidence gates, but only READY may proceed.
    """
    before = gates.snapshot_head(workspace=Path(worktree))
    workspace = Workspace(work_dir=Path(worktree))
    resuming = workspace.remote_branch_exists(branch=branch)
    original_issue = f"# {issue_number} {issue_title}\n\n{issue_body}"

    def run_writer(*, mode: str, extra_context: str = "") -> dict:
        sections = [
            ("original issue", original_issue),
            ("runtime context", context_text),
        ]
        if extra_context:
            sections.append(("bounded repair context", extra_context))
        return engine.run_agent(
            spec_writer,
            backend=backend,
            work_dir=Path(worktree),
            context=context.sections(*sections),
            issue_number=issue_number,
            branch=branch,
            mode=mode,
        )

    verdict = run_writer(mode="AUTHOR")

    def validate(candidate: dict) -> str:
        status = candidate["status"]
        if status not in {"READY", "PARTIAL", "BLOCKED"}:
            raise gates.GateError(f"minimal Spec Writer 返回未知状态：{status!r}")
        if status in {"READY", "PARTIAL"}:
            assessments = candidate.get("candidate_assessments")
            required_candidate_fields = {
                "candidate",
                "ownership",
                "delivery",
                "control_effect",
                "evidence",
                "assumptions",
                "failure_modes",
                "verdict",
            }
            if not isinstance(assessments, list) or not assessments:
                raise gates.GateError("minimal Spec 缺少 candidate_assessments，拒绝无比较的方案")
            malformed = [
                index
                for index, item in enumerate(assessments)
                if not isinstance(item, dict) or not required_candidate_fields.issubset(item)
            ]
            if malformed:
                raise gates.GateError(
                    f"minimal Spec 候选未使用统一证据字段：candidate_assessments{malformed}"
                )
            coverage = candidate.get("objective_coverage")
            if not isinstance(coverage, list) or not coverage:
                raise gates.GateError("minimal Spec 缺少 objective_coverage")
            malformed_coverage = [
                index
                for index, item in enumerate(coverage)
                if not isinstance(item, dict)
                or "scope_coverage" not in item
                or "evidence_level" not in item
            ]
            if malformed_coverage:
                raise gates.GateError(
                    "minimal Spec 目标未分别记录覆盖与证据等级："
                    f"objective_coverage{malformed_coverage}"
                )
        blocker = candidate.get("blocker")
        if not isinstance(blocker, str):
            raise gates.GateError("minimal Spec blocker 必须是字符串")
        if status == "PARTIAL" and not blocker.strip():
            raise gates.GateError("minimal Spec 返回 PARTIAL 时必须说明真实未闭合项")
        if status == "BLOCKED" and not blocker.strip():
            raise gates.GateError("minimal Spec 返回 BLOCKED 时必须说明阻断原因")
        return status

    def ready_contract_violations(candidate: dict) -> list[str]:
        """Return repairable READY contradictions without demanding implementation evidence."""
        if candidate.get("status") != "READY":
            return []
        violations: list[str] = []
        if str(candidate.get("blocker") or "").strip():
            violations.append("READY 的 blocker 必须为空")
        coverage = candidate.get("objective_coverage") or []
        non_full = [
            str(item.get("id") or index)
            for index, item in enumerate(coverage)
            if item.get("scope_coverage") != "FULL"
        ]
        if non_full:
            violations.append("READY 仍有未完整进入契约的 objective：" + ", ".join(non_full))
        return violations

    status = validate(verdict)
    reported_head = verdict.pop("head_sha", None)
    contradictions = ready_contract_violations(verdict)
    if contradictions:
        prior = json.dumps(verdict, ensure_ascii=False, sort_keys=True)
        verdict = run_writer(
            mode="CONTRACT_REPAIR",
            extra_context=(
                "AUTHOR 自称 READY，但宿主发现以下契约内部矛盾：\n- "
                + "\n- ".join(contradictions)
                + "\n这不是要求在实现前提供行为证据。若目标已完整进入契约，只需用 "
                "FULL + HYPOTHESIS 表达；若契约遗漏目标，则补全控制语义与独立验收。"
                "\n上次结构化结论如下：\n" + prior
            ),
        )
        status = validate(verdict)
        repaired_reported_head = verdict.pop("head_sha", None)
        if repaired_reported_head is not None:
            reported_head = repaired_reported_head
        remaining = ready_contract_violations(verdict)
        if remaining:
            raise gates.GateError(
                "minimal Spec CONTRACT_REPAIR 后仍自相矛盾：" + "; ".join(remaining)
            )
    if status == "BLOCKED":
        verdict["head_sha"] = ""
        if reported_head is not None:
            verdict["reported_head_sha"] = reported_head
        return verdict
    after = gates.snapshot_head(workspace=Path(worktree))
    spec_path = Path(worktree) / "docs" / "objectives" / f"issue-{issue_number}.md"
    if after == before and not resuming and spec_path.is_file():
        prior = json.dumps(verdict, ensure_ascii=False, sort_keys=True)
        verdict = run_writer(
            mode="DELIVERY_REPAIR",
            extra_context=(
                "AUTHOR 已返回 READY/PARTIAL，但宿主客观读取到 Git HEAD 未前移。"
                "这是唯一一次修复机会。上次结构化结论如下；必须与磁盘文档核对后再交付：\n"
                f"{prior}"
            ),
        )
        status = validate(verdict)
        reported_head = verdict.pop("head_sha", reported_head)
        if status == "BLOCKED":
            verdict["head_sha"] = ""
            if reported_head is not None:
                verdict["reported_head_sha"] = reported_head
            return verdict
        after = gates.snapshot_head(workspace=Path(worktree))
    if after == before and resuming:
        workspace.assert_delivered(worktree=Path(worktree), branch=branch)
    else:
        after = gates.assert_head_advanced(before=before, workspace=Path(worktree))
        workspace.assert_delivered(worktree=Path(worktree), branch=branch)
    verdict["head_sha"] = after
    if reported_head is not None:
        verdict["reported_head_sha"] = reported_head
    return verdict


def minimal_design_snapshot(*, work_dir: Path, issue_number: int) -> dict[str, str]:
    """Validate and hash the compact objective contract for a minimal-flow issue.

    Spec-0082/T1: unlike the standard RFC, this artifact has a fixed six-heading contract and no
    generated indexes or DAG. Its byte digest is persisted and re-read before merge.
    """
    path = Path(work_dir) / "docs" / "objectives" / f"issue-{issue_number}.md"
    if not path.is_file():
        raise gates.GateError(f"minimal objective spec 不存在：{path.relative_to(work_dir)}")
    text = path.read_text(encoding="utf-8")
    required = (
        "## Objective contract",
        "## Observed mechanism and evidence",
        "## Decision rationale",
        "## Invariants and risk ledger",
        "## Developer design envelope",
        "## Independent acceptance",
    )
    missing = [heading for heading in required if heading not in text]
    if missing:
        raise gates.GateError(f"minimal objective spec 缺少固定段落：{missing}")
    # Keep the artifact compact by prompt guidance, but do not turn an arbitrary
    # line count into a semantic gate.  A few extra lines must not discard a
    # complete, actionable contract before Developer can exercise it.  The
    # actual gates here are the six required sections and the digest binding.
    return {
        "design_digest": hashlib.sha256(text.encode()).hexdigest(),
        "spec_path": str(path),
    }


def assert_minimal_design_approved(
    *, work_dir: Path, issue_number: int, approved_digest: str
) -> None:
    """Reject merge when the compact objective contract changed after implementation approval."""
    current = minimal_design_snapshot(work_dir=work_dir, issue_number=issue_number)
    if current["design_digest"] != approved_digest:
        raise gates.GateError("minimal objective spec 在实现后发生变化，必须重新走原 issue 验收")


def implement(
    *,
    backend: Any,
    work_dir: Path,
    issue_number: int,
    pr_number: int,
    feedback: str,
    context_text: str,
    evidence_pack: list | None = None,
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
        context=context.sections(
            ("feedback", feedback),
            (
                "runtime context",
                _with_evidence(context_text=context_text, evidence_pack=evidence_pack),
            ),
        ),
        issue_number=issue_number,
        pr_number=pr_number,
    )


def execute_compact_spec(
    *,
    backend: Any,
    work_dir: Path,
    issue_number: int,
    pr_number: int,
    context_text: str,
) -> dict:
    """Execute one compact objective without review or validation work.

    Spec-0082/T1: generate-only keeps coding capability but removes the autonomous Implementer
    role.  The executor must deliver one pushed commit and cannot judge or merge its own work.
    """
    before = gates.snapshot_head(workspace=Path(work_dir))
    verdict = engine.run_agent(
        executor,
        backend=backend,
        work_dir=Path(work_dir),
        context=context_text,
        issue_number=issue_number,
        pr_number=pr_number,
    )
    after = gates.snapshot_head(workspace=Path(work_dir))
    gates.assert_head_advanced(before=before, workspace=Path(work_dir))
    gates.assert_evidence_stamp(head_sha=after, claimed=verdict["head_sha"])
    return verdict


def design_snapshot(*, work_dir: Path, issue_number: int, base: str = "main") -> dict[str, str]:
    """Validate and identify the candidate Spec changed by the current issue branch."""
    specs_root = Path(work_dir) / "docs" / "specs"
    report = spec_validate.validate(specs_root=specs_root)
    if not report.ok:
        details = "; ".join(
            f"{item.where}: {item.message}" for item in report.issues if item.level == "error"
        )
        raise gates.GateError(f"issue #{issue_number} 的候选 Spec 校验失败：{details}")
    groups = spec_model.load_all(specs_root=specs_root)
    changed_path = Workspace(work_dir=Path(work_dir)).changed_spec_group(
        worktree=Path(work_dir), base=base
    )
    if changed_path is not None:
        changed_name = changed_path.name
        candidates = [
            group
            for group in groups
            if spec_model.group_path(
                specs_root=specs_root, number=group.number, slug=group.metadata.slug
            ).name
            == changed_name
            and group.metadata.issue == issue_number
        ]
    else:
        # Compatibility fallback for repositories without a usable git comparison
        # (including isolated validation fixtures). Runtime issue branches normally
        # take the branch-diff path above.
        candidates = [group for group in groups if group.metadata.issue == issue_number]
    if len(candidates) != 1:
        raise gates.GateError(
            f"issue #{issue_number} 必须恰好对应一个候选 Spec，实际 {len(candidates)} 个"
        )
    group = candidates[0]
    digest = spec_model.design_digest(group=group)
    spec_path = spec_model.group_path(
        specs_root=specs_root, number=group.number, slug=group.metadata.slug
    )
    return {"design_digest": digest, "spec_path": str(spec_path)}


def architecture(
    *,
    backend: Any,
    work_dir: Path,
    issue_number: int,
    context_text: str = "",
    evidence_pack: list | None = None,
) -> dict:
    """Review the issue's candidate Spec before any implementation is dispatched."""
    snapshot = design_snapshot(work_dir=work_dir, issue_number=issue_number)
    return (
        engine.run_agent(
            architect,
            backend=backend,
            **context.for_architecture(
                work_dir=Path(work_dir),
                issue_number=issue_number,
                design_digest=snapshot["design_digest"],
                spec_text=_with_evidence(
                    context_text=Path(snapshot["spec_path"]).read_text(encoding="utf-8")
                    + context_text,
                    evidence_pack=evidence_pack,
                ),
            ),
        )
        | snapshot
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
        context=context.sections(("issue", issue_body), ("runtime context", context_text)),
        pr_number=pr_number,
    )


def acceptance(
    *,
    backend: Any,
    work_dir: Path,
    issue_number: int,
    pr_number: int,
    issue_title: str,
    issue_body: str,
    context_text: str,
    user_test_result: dict | None = None,
    require_user_test: bool = False,
) -> dict:
    """Judge the current candidate once against the complete original issue.

    Spec-0082/T1: this role cannot request a rework loop; PARTIAL and FAIL are terminal outcomes.
    """
    verdict = engine.run_agent(
        acceptance_agent,
        backend=backend,
        work_dir=Path(work_dir),
        context=context.sections(
            ("original issue", f"# {issue_number} {issue_title}\n\n{issue_body}"),
            *(
                (("user test artifact", json.dumps(user_test_result, ensure_ascii=False, sort_keys=True)),)
                if user_test_result is not None
                else ()
            ),
            ("runtime context", context_text),
        ),
        issue_number=issue_number,
        pr_number=pr_number,
    )
    if verdict["verdict"] not in {"PASS", "PARTIAL", "FAIL"}:
        raise gates.GateError(f"Acceptance Reviewer 返回未知裁决：{verdict['verdict']!r}")
    if verdict["verdict"] == "PASS":
        manifest = verdict["evidence"]
        try:
            evidence_validation.validate_manifest(
                verdict="PASS",
                evidence=manifest,
                require_behavior=True,
                required_source="user_test" if require_user_test else None,
            )
        except evidence_validation.EvidenceError as exc:
            raise gates.GateError(f"Acceptance PASS 证据无效：{exc}") from exc
        if any(item.get("passed") is not True for item in manifest):
            raise gates.GateError("Acceptance PASS 的每项证据必须显式 passed=true")
        if require_user_test:
            if not isinstance(user_test_result, dict):
                raise gates.GateError("Acceptance PASS 缺少实际 User Test artifact")
            if user_test_result.get("status") != "completed":
                raise gates.GateError("Acceptance PASS 的 User Test 未正常完成，必须 fail-closed")
            if not any(
                item.get("kind") == "behavior" and item.get("source") == "user_test"
                for item in manifest
            ):
                raise gates.GateError("Acceptance PASS 缺少 source=user_test 的行为证据")
        else:
            # Legacy recipe callers may still use replay/variant evidence while they
            # migrate.  v0.2 always sets require_user_test=True.
            behavior_sources = {
                item.get("source") for item in manifest if item.get("kind") == "behavior"
            }
            missing_sources = {"original_replay", "independent_variant"} - behavior_sources
            if missing_sources:
                raise gates.GateError(
                    "Acceptance PASS 缺少独立行为证据：" + ", ".join(sorted(missing_sources))
                )
    return verdict


def deliver(
    *,
    backend: Any,
    worktree: Path,
    branch: str,
    pr_number: int,
    issue_number: int,
    rebase_onto: str | None = None,
    context_text: str = "",
) -> dict:
    """交付阶段（deliver agent）：commit/push 把改动落到 PR head，返回交付报告 {delivered, head_sha, ...}。承 solve_issue 的 deliver。

    恒 agent（git 交付永远派 agent、不进 stages 策略点）。内嵌三道确定性硬闸兜底（见模块 docstring）——
    交付前基点确定性记录、交付后断言 head 前移 + 证据戳一致，防 #140 空转/张冠李戴。

    # Spec-0065/T2: `context_text` 追加进 agent 上下文（缺省空串 = 既有调用方零变化）。守夜用它把
    # `context_text` 可追加本轮机械约束与诊断材料。
    """
    ctx = Context(
        work_dir=Path(worktree),
        issue_number=issue_number,
        branch=branch,
        pr_number=pr_number,
    )
    placeholders = ctx.for_deliver(issue_number=issue_number)
    placeholders["rebase_onto"] = rebase_onto or branch
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
    base: str = "main",
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
        rebase_onto=base,
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
    require_ci: bool = True,
) -> dict:
    """合并阶段（Spec-0017/T3：确定性硬闸兜底 + 下放 merger agent）：返回 merger 报告 {merged, summary}。

    合并**不可逆**，故形态是「先闸后 agent」：
    1. 先经确定性 `gates.assert_merge_allowed(pr_number, head_sha)` **实时复读** CI + label 把守红线——不放行
       即抛 `GateError`，**决不派 agent**（agent 只能在闸放行后才被派上来落合并动作，防误派/TOCTOU 合未审代码）；
    2. 放行后经 `engine.run_agent` 派 merger agent 落 `gh pr merge`——把「动作」下放 agent（承 Spec-0064 动作
       全归 agent 层）；merger 对硬闸未覆盖的异常返回 merged=false，由统一失败路径收口。

    本函数只在机械闸放行后落合并动作，自身零业务判断。
    """
    if require_ci:
        gates.assert_merge_allowed(pr_number=pr_number, head_sha=head_sha)
    else:
        gates.assert_merge_allowed(pr_number=pr_number, head_sha=head_sha, require_ci=False)
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


def merge_mechanical(*, pr_number: int, head_sha: str, require_ci: bool = True) -> dict:
    """Merge a minimal-flow PASS after re-reading deterministic hard gates.

    Spec-0082/T1: no merger model is involved; the forge operation is mechanical and idempotent.
    """
    gates.assert_merge_allowed(
        pr_number=pr_number,
        head_sha=head_sha,
        require_ci=require_ci,
    )
    github.merge_pr(pr_number=pr_number)
    return {"merged": True, "summary": "merged mechanically"}


# --------------------------------------------------------------------------------------------------
# 内部：交付类阶段共用的三道硬闸兜底骨架 + e2e 证据 seam + github 薄引用。
# --------------------------------------------------------------------------------------------------


def _with_evidence(*, context_text: str, evidence_pack: list | None) -> str:
    """Append a bounded objective evidence pack without changing agent schemas."""
    rendered = research.render(evidence_pack)
    if rendered == "[]":
        return context_text
    return f"{context_text}\n\n--- repository evidence_pack (objective facts only) ---\n{rendered}"


def _deliver_gated(
    *,
    agent_module: Any,
    backend: Any,
    worktree: Path,
    placeholders: dict,
    require_delivered: bool,
    resume_branch: str | None = None,
) -> dict:
    """派交付类 agent（drafter/deliver）+ 三道确定性硬闸兜底——rfc/deliver/conflict 共用（承 rfc_lifecycle._run_drafter / solve_issue 交付段）。

    交付前基点经 `gates.snapshot_head` 确定性记录（不信 agent 自述）；`require_delivered=True`（backfill
    validate 门控）时先据 agent 自述 delivered 短路——未交付即原样返回（caller 据此不开 PR、不进硬闸）；
    否则 `assert_head_advanced` + `assert_evidence_stamp` 兜底。engine 保留字 work_dir/context 从
    placeholders 取（context 必在 placeholders 里）。
    """
    before = gates.snapshot_head(workspace=Path(worktree))
    workspace = Workspace(work_dir=Path(worktree))
    resuming = bool(
        resume_branch is not None and workspace.remote_branch_exists(branch=resume_branch)
    )
    # placeholders 可能已含 work_dir（如 Context.for_deliver 产出）——统一以本函数的 worktree 为准，
    # 剔除 placeholders 里的 work_dir 避免与显式传参重复（engine 保留字 work_dir 单一来源）。
    payload = {key: value for key, value in placeholders.items() if key != "work_dir"}
    verdict = engine.run_agent(agent_module, backend=backend, work_dir=Path(worktree), **payload)
    if require_delivered and not verdict["delivered"]:
        return verdict
    after = gates.snapshot_head(workspace=Path(worktree))
    if after == before and resuming and resume_branch is not None:
        # A retry may be validating an artifact already committed and pushed by the
        # previous attempt. Accept it only when local HEAD exactly matches the remote
        # issue branch; this preserves the delivery and evidence gates without
        # requiring a meaningless extra commit.
        workspace.assert_delivered(worktree=Path(worktree), branch=resume_branch)
    else:
        gates.assert_head_advanced(before=before, workspace=Path(worktree))
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
