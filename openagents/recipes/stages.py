# Spec-0064/T2
"""Run individual delivery stages and enforce their result contracts.

The stage functions are independently callable. They assemble the role context,
invoke the backend through runtime.engine, and check objective delivery facts.
"""

from __future__ import annotations

import hashlib
import json
import warnings
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

# Spec-0074/T1: arias-import switch - Platform operations are configured by github/gitea driver to call zero changes.
from openagents.utils import forge as github
from openagents.utils.workspace import Workspace

# Spec-0064/T2: drafting mode fonts (carrying recipes.rfc_lifecycle._MODE_*) - refc stage draft,backfill
# Recipe(T4) returns this function. Only these two in-stage functions (refine/implement/iterate has been taken over at the independent stage) are available.
MODE_DRAFT = "draft"
MODE_BACKFILL = "backfill"

# Spec-0064/T2: ci / e2e Catalogue of mechanical gates——T3 By which route (fail/pending→I'm not sure if I'm going to be able to do this.pass/ok→Let go.
CI_FAIL = "fail"
CI_PENDING = "pending"
CI_PASS = "pass"
E2E_STALE = "e2e"  # Evidence stamp missing/Old/Zhang Zhang Li Tai → We should go back and fix it. e2e( Alignment) merge_pr It's... "e2e" Events)
E2E_OK = "ok"


# --------------------------------------------------------------------------------------------------
# Judgment paragraph: Sends ant ant an existing agent to a structured decision (this module is its own zero business judgement, only group placeholders + tune engine).
# --------------------------------------------------------------------------------------------------


def triage(*, backend: Any, work_dir: Path, issue: Any) -> dict:
    """Return the triage role’s structured admission decision."""
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
    """Draft or refine a Spec, or backfill it from existing code, then verify delivery."""
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
            raise gates.GateError(f"Minimal Spec Writer returned an unknown status: {status!r}")
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
                raise gates.GateError(
                    "Minimal Spec is missing candidate_assessments; compare the alternatives"
                )
            malformed = [
                index
                for index, item in enumerate(assessments)
                if not isinstance(item, dict) or not required_candidate_fields.issubset(item)
            ]
            if malformed:
                raise gates.GateError(
                    f"Minimal Spec candidates must use the same evidence fields: candidate_assessments{malformed}"
                )
            coverage = candidate.get("objective_coverage")
            if not isinstance(coverage, list) or not coverage:
                raise gates.GateError("Minimal Spec is missing objective_coverage")
            malformed_coverage = [
                index
                for index, item in enumerate(coverage)
                if not isinstance(item, dict)
                or "scope_coverage" not in item
                or "evidence_level" not in item
            ]
            if malformed_coverage:
                raise gates.GateError(
                    "Minimal Spec objectives must record coverage and evidence level separately: "
                    f"objective_coverage{malformed_coverage}"
                )
        blocker = candidate.get("blocker")
        if not isinstance(blocker, str):
            raise gates.GateError("Minimal Spec blocker must be a string")
        if status == "PARTIAL" and not blocker.strip():
            raise gates.GateError("A PARTIAL Minimal Spec must name the unresolved items")
        if status == "BLOCKED" and not blocker.strip():
            raise gates.GateError("A BLOCKED Minimal Spec must explain the blocker")
        return status

    def ready_contract_violations(candidate: dict) -> list[str]:
        """Return repairable READY contradictions without demanding implementation evidence."""
        if candidate.get("status") != "READY":
            return []
        violations: list[str] = []
        if str(candidate.get("blocker") or "").strip():
            violations.append("A READY Spec must have an empty blocker")
        coverage = candidate.get("objective_coverage") or []
        non_full = [
            str(item.get("id") or index)
            for index, item in enumerate(coverage)
            if item.get("scope_coverage") != "FULL"
        ]
        if non_full:
            violations.append(
                "READY Spec has objectives without full contract coverage: " + ", ".join(non_full)
            )
        return violations

    status = validate(verdict)
    reported_head = verdict.pop("head_sha", None)
    contradictions = ready_contract_violations(verdict)
    if contradictions:
        prior = json.dumps(verdict, ensure_ascii=False, sort_keys=True)
        verdict = run_writer(
            mode="CONTRACT_REPAIR",
            extra_context=(
                "AUTHOR returned READY, but the host found these contradictions in the contract:\n- "
                + "\n- ".join(contradictions)
                + "\nBehavioral evidence is not required before implementation. If the contract fully covers the objective, use "
                "FULL + HYPOTHESIS. If the contract omits the objective, complete the control semantics and independent acceptance criteria."
                "\nPrevious structured result:\n" + prior
            ),
        )
        status = validate(verdict)
        repaired_reported_head = verdict.pop("head_sha", None)
        if repaired_reported_head is not None:
            reported_head = repaired_reported_head
        remaining = ready_contract_violations(verdict)
        if remaining:
            raise gates.GateError(
                "Minimal Spec is still inconsistent after CONTRACT_REPAIR: " + "; ".join(remaining)
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
                "AUTHOR returned READY/PARTIAL, but the host verified that Git HEAD did not advance. "
                "This is the only repair attempt. Check the prior structured result below against the document on disk before delivering:\n"
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
    """Read and hash the compact objective contract for a minimal-flow issue.

    Spec-0082/T1: unlike the standard RFC, this artifact has an expected six-heading format and no
    generated indexes or DAG. Empty/missing artifacts remain hard failures; heading deviations are
    warnings so a present contract can still be implemented. Its byte digest is persisted and
    re-read before merge.
    """
    path = Path(work_dir) / "docs" / "objectives" / f"issue-{issue_number}.md"
    if not path.is_file():
        raise gates.GateError(f"Minimal objective Spec not found: {path.relative_to(work_dir)}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        # An empty artifact cannot provide an objective contract at all.  Keep this as a
        # hard gate; the warning-only relaxation below is specifically for presentation
        # format, not for an absent design.
        raise gates.GateError(f"Minimal objective Spec is empty: {path.relative_to(work_dir)}")
    required = (
        "## Objective contract",
        "## Observed mechanism and evidence",
        "## Decision rationale",
        "## Invariants and risk ledger",
        "## Developer design envelope",
        "## Independent acceptance",
    )
    missing = [heading for heading in required if heading not in text]
    format_warning = ""
    if missing:
        format_warning = (
            f"Minimal objective Spec format warning: missing required section {missing}；"
            "Continuing; implementation and user acceptance will check semantic completeness"
        )
        # Do not turn a present, non-empty contract into a failed run merely because the
        # model used numbered/translated Markdown headings.  Keep the warning observable
        # both on the normal warnings channel and in the returned snapshot for audit logs.
        warnings.warn(format_warning, UserWarning, stacklevel=2)
    # Keep the artifact compact by prompt guidance, but do not turn presentation
    # details into a semantic gate.  A few extra lines or non-canonical headings
    # must not discard a complete, actionable contract before Developer can
    # exercise it.  The hard gates here are readability/non-emptiness and the
    # digest binding; section-format deviations remain explicitly observable as
    # warnings above.
    snapshot = {
        "design_digest": hashlib.sha256(text.encode()).hexdigest(),
        "spec_path": str(path),
    }
    if format_warning:
        snapshot["format_warning"] = format_warning
    return snapshot


def assert_minimal_design_approved(
    *, work_dir: Path, issue_number: int, approved_digest: str
) -> None:
    """Reject merge when the compact objective contract changed after implementation approval."""
    current = minimal_design_snapshot(work_dir=work_dir, issue_number=issue_number)
    if current["design_digest"] != approved_digest:
        raise gates.GateError(
            "The minimal objective Spec changed after implementation; repeat acceptance against the original issue"
        )


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
    """Implement the approved Spec or address feedback in the candidate worktree."""
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
    resume_branch: str | None = None,
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
    if after == before and resume_branch is not None:
        # Spec-0056 recovery: a timed-out executor may already have pushed this exact commit.
        Workspace(work_dir=Path(work_dir)).assert_delivered(
            worktree=Path(work_dir), branch=resume_branch
        )
    else:
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
        raise gates.GateError(f"issue #{issue_number}: candidate Spec validation failed: {details}")
    groups = spec_model.load_all(specs_root=specs_root)
    changed_paths = Workspace(work_dir=Path(work_dir)).changed_spec_groups(
        worktree=Path(work_dir), base=base
    )
    if changed_paths:
        changed_names = {path.name for path in changed_paths}
        candidates = [
            group
            for group in groups
            if spec_model.group_path(
                specs_root=specs_root, number=group.number, slug=group.metadata.slug
            ).name
            in changed_names
            and group.metadata.issue == issue_number
        ]
    else:
        # Compatibility fallback for repositories without a usable git comparison
        # (including isolated validation fixtures). Runtime issue branches normally
        # take the branch-diff path above.
        candidates = [group for group in groups if group.metadata.issue == issue_number]
    if len(candidates) != 1:
        raise gates.GateError(
            f"issue #{issue_number} must have exactly one candidate Spec; found {len(candidates)}"
        )
    group = candidates[0]
    digest = spec_model.design_digest(group=group)
    spec_path = spec_model.group_path(
        specs_root=specs_root, number=group.number, slug=group.metadata.slug
    )
    # Spec-0088/T1: preserve the unnormalized approval hash alongside v2 semantics.
    return {
        "design_digest": digest,
        "design_raw_digest": spec_model.legacy_design_digest(group=group),
        "spec_path": str(spec_path),
    }


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
    issue_number: int = 0,
) -> dict:
    """Review stage (reviewer agent): Could this version be evaluated and returned to {verdict, reason} (PASS/REWORK). solve_issue/merge_pr review.

    ”Is this version fit?” is subjective, so it is a default; this function is zero, only set placeholders + engine. ReWORK is used by
    T3-implementer iterative (back to back loop).
    """
    verdict = engine.run_agent(
        reviewer,
        issue_number=issue_number,
        backend=backend,
        work_dir=Path(work_dir),
        context=context.sections(("issue", issue_body), ("runtime context", context_text)),
        pr_number=pr_number,
    )

    # Transport casing must not turn an explicit approval into a rework request.
    normalized = verdict["verdict"].strip().upper()
    if normalized not in {"PASS", "REWORK"}:
        raise engine.AgentOutputError(f"reviewer returned unknown verdict: {verdict['verdict']!r}")
    return {**verdict, "verdict": normalized}


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
                (
                    (
                        "user test artifact",
                        json.dumps(user_test_result, ensure_ascii=False, sort_keys=True),
                    ),
                )
                if user_test_result is not None
                else ()
            ),
            ("runtime context", context_text),
        ),
        issue_number=issue_number,
        pr_number=pr_number,
    )
    if verdict["verdict"] not in {"PASS", "PARTIAL", "FAIL"}:
        raise gates.GateError(
            f"Acceptance Reviewer returned an unknown verdict: {verdict['verdict']!r}"
        )
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
            raise gates.GateError(f"Invalid evidence for Acceptance PASS: {exc}") from exc
        if any(item.get("passed") is not True for item in manifest):
            raise gates.GateError(
                "Every Acceptance PASS evidence item must explicitly have passed=true"
            )
        if require_user_test:
            if not isinstance(user_test_result, dict):
                raise gates.GateError("Acceptance PASS lacks an actual User Test artifact")
            if user_test_result.get("status") != "completed":
                raise gates.GateError(
                    "User Test did not complete normally; Acceptance PASS is rejected"
                )
            if not any(
                item.get("kind") == "behavior" and item.get("source") == "user_test"
                for item in manifest
            ):
                raise gates.GateError(
                    "Acceptance PASS lacks behavioral evidence with source=user_test"
                )
        else:
            # Legacy recipe callers may still use replay/variant evidence while they
            # migrate.  v0.2 always sets require_user_test=True.
            behavior_sources = {
                item.get("source") for item in manifest if item.get("kind") == "behavior"
            }
            missing_sources = {"original_replay", "independent_variant"} - behavior_sources
            if missing_sources:
                raise gates.GateError(
                    "Acceptance PASS lacks independent behavioral evidence: "
                    + ", ".join(sorted(missing_sources))
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
    """Ask the delivery role to publish changes, then verify the resulting Git state."""
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
        resume_branch=branch,
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
    """Ask the delivery role to resolve a rebase and verify the result."""
    if backend is None:
        return {"delivered": False, "reason": "unmergeable"}
    resolved_branch = branch or github_pr_head_branch(pr_number=pr_number)
    try:
        report = deliver(
            backend=backend,
            worktree=Path(work_dir),
            branch=resolved_branch,
            pr_number=pr_number,
            issue_number=issue_number,
            rebase_onto=base,
            context_text=context_text,  # Spec-0065/T2: Pass through first-class export contracts (Vigil, other caller default)
        )
    except gates.GateError as exc:
        return {"delivered": False, "reason": f"delivery gate: {exc}", "gate": "conflict"}
    if report["delivered"]:
        return {"delivered": True, "reason": "resolved"}
    return {"delivered": False, "reason": "blocked", "gate": "conflict"}


# --------------------------------------------------------------------------------------------------
# Mechanical segment: Read objective facts classified by ci/e2e/ gitthub landing (merge). Zero business judgement, zero LLM.
# --------------------------------------------------------------------------------------------------


def ci(*, pr_number: int) -> str:
    """CI gate (refined genthub check + lots): returns fail/pending/pass. merge_pr section of the CI.

    ** Not ”agent ruling CI”** - constant testing is objectively read check conclusion; `stages.ci=agent` only means ”red automatically”
    Call back the implementer” (T3 route) and this function reads only objective fact categories.
    """
    status = github.check_status(pr_number=pr_number)
    if gates.ci_failed(check_status=status):
        return CI_FAIL
    if gates.ci_pending(check_status=status):
        return CI_PENDING
    return CI_PASS


def e2e(*, pr_number: int) -> str:
    """e2e (Retroactive + Gates interpretation of definitive reading evidence): returns e2e (supplement)/ ok (dismissal). e2e evidence section of merge_pr.

    Read it. PR It’s... e2e Evidence stamp ’(Actual head, The evidence says it. head)’——No evidentiary requirements (No evidence)seam Default None）→ Release ok）;touching
    But... `gates.evidence_stamp_ok` Discrepancies (inventory missing)/Old/Zhang Zhang Li Tai)→ e2e（T3 Pie. implementer - I’ll get it.
    Single Seam `_pr_evidence_stamp` for the test to inject a jab with a mokey Patch.
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
    """Verify the deterministic gate, then dispatch the merge role.
    Spec-0017/T3.
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
        # Spec-0074/T1: Platform command injects at the current forge (GitHub=gh original command zero change; Gitea=openagents merge-pr).
        merge_command=github.merge_command_text(pr_number=pr_number, head_sha=head_sha),
        verify_command=github.merge_verify_command_text(pr_number=pr_number, head_sha=head_sha),
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
    github.merge_pr(pr_number=pr_number, head_sha=head_sha)
    return {"merged": True, "summary": "merged mechanically"}


# --------------------------------------------------------------------------------------------------
# Internal: Three hard-barrel skeletons shared during the delivery type + e2e evidence Seam + github thin references.
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
    """Dispatch a delivery role and check its report against observed Git facts."""
    before = gates.snapshot_head(workspace=Path(worktree))
    workspace = Workspace(work_dir=Path(worktree))
    resuming = bool(
        agent_module is not deliver_agent
        and resume_branch is not None
        and workspace.remote_branch_exists(branch=resume_branch)
    )
    # Placeholds may already contain work_dir (e. g. Context.for_deliver output) - unified to worktree of this function,
    # Remove work_dir from placeholds to avoid repeating it with a visible transfer (engine reserved word work_dir single source).
    payload = {key: value for key, value in placeholders.items() if key != "work_dir"}
    verdict = engine.run_agent(agent_module, backend=backend, work_dir=Path(worktree), **payload)
    if require_delivered and not verdict["delivered"]:
        return verdict
    after = gates.snapshot_head(workspace=Path(worktree))
    if agent_module is deliver_agent:
        # Spec-0056 recovery: publishing an existing commit is progress; an empty commit is not
        # required. Verify the actual remote and worktree, not the model's self-report alone.
        if not verdict["delivered"] or resume_branch is None:
            summary = str(verdict.get("summary") or "No diagnostic from the agent")
            raise gates.GateError(
                f"Delivery agent did not finish commit and push; agent_summary={summary}"
            )
        workspace.assert_delivered(worktree=Path(worktree), branch=resume_branch)
    elif after == before and resuming and resume_branch is not None:
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
    """Read it. PR It’s... e2e Evidence trace ’(Actual head, The evidence says it. head)’;no evidentiary requirements → None（e2e The gate is clear. merge_pr._pr_evidence_stamp。

    New Inn has not yet been replaced by execuator True Run e2e (submit Spec-0061 is the same Unresolved), so the default is to return to the Noone, e2e gate and release; T3
    Connect / Test to improvise this function by placing a jab, driving `gates.evidence_stamp_ok` interpretation. Single Seam connects the evidence lock
    Line points are clear and do not disperse into the main control stream.
    """
    return None


def github_pr_head_branch(*, pr_number: int) -> str:
    """The thin reference `github.pr_head_branch` - conflict stage does not have a brancy-based reading (one point is easy to test for MonkeyPatch)."""
    return github.pr_head_branch(pr_number=pr_number)
