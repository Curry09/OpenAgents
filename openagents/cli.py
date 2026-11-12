# Spec-0064/T5
"""Expose OpenAgents project, delivery, reporting, and dashboard commands."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

# Spec-0069/T1: Shell Tab Completion - Direct reading of argparse parser 's candidate (the single real source of the command list remains build_parser, which is still available for the command list)
# Do not maintain the second floating completed script.
# (old snapshot/simplified installation) The completion should be silent rather than a drag on the entire CLI.
try:
    import argcomplete
except (
    ImportError
):  # pragma: no cover - aggcomplete is declared dependent; complete silent downgrade if missing
    argcomplete = None

# Spec-0074/T1: arias-import switch - Platform operations are configured by github/gitea driver to call zero changes.
from openagents.utils import forge as github
from openagents.utils.config import ProjectContext, ensure_project, resolve_project

# Spec-0065/T2: maximum `--parallel K`. Each workingr is a permanent range + a private sqlite connection + an agent subprocess
# And K-worker plays GitHub API at the same time -- K-to-large will only be more locking competition and 429, not faster.
# The true simultaneous capbook is bound by the issuer blocked_by, which is a hand-defaulted fence (`--parallel 99999`).
_MAX_PARALLEL = 32


def _parallel_k(value: str) -> int:
    """Argparse’s `--parallel` verification: Must be the integer number of `1..{_MAX_PARALLEL}`, otherwise you will be wrong on the spot.

    Unquieted pliers (`max(1, K)` earlier): `--parallel 0` is obviously a slip or misunderstanding, and quietly gives one to think that ”single-off without a verse”
    ”Flower,” turns an input error into a performance puzzle. CLI ’s error should ring in CLI.
    """
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"--parallel requires an integer; got {value!r}") from None
    if not 1 <= parsed <= _MAX_PARALLEL:
        raise argparse.ArgumentTypeError(
            f"--parallel must be between 1 and {_MAX_PARALLEL} (1 runs serially); got {parsed}"
        )
    return parsed


# RFC-0002 Decision 5 / RFC-0004 Decision 2: Found the label - Single Real Source. Automatically attach it to `oa issue` to issue, vigil found
# The paragraph is defaulted on the door; both ends share the same constant. RFC-0015: the word is moved to gthub, where the aliases quote the security back to the public name.
DISCOVERY_LABEL = github.DISCOVERY_LABEL


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openagents",
        description="Spec-driven software delivery: triage issues, assign work, and open pull requests.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # Spec-0092/T3: registered here, dispatched before self-update in main.
    capability = sub.add_parser(
        "observation-capabilities", help="Show offline evidence reader capabilities"
    )
    capability.add_argument("--json", action="store_true", required=True)

    # Spec-0067/T2:init produces the default . openagents/openagents.yml (supplexed, etc.) by hand, except for pre-reading.
    p_init = sub.add_parser(
        "init",
        help="Initialize the current directory as an OpenAgents project and write the default configuration",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Replace the existing .openagents/openagents.yml with the packaged template",
    )

    # Spec-0064/T5: Auto-ring - Automation One Step for rfc/implement/iterate/poll/watch/vigil-all/fleet etc.
    p_vigil = sub.add_parser(
        "vigil", help="Watch issues, assign work, and advance pull requests using openagents.yml"
    )
    p_vigil.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Poll interval in seconds; overrides YAML defaults",
    )
    p_vigil.add_argument(
        "--label",
        action="append",
        default=None,
        metavar="LABEL",
        help="Required issue discovery label; repeatable and overrides YAML defaults",
    )
    p_vigil.add_argument(
        "--base", default=None, help="Base branch for new work; overrides YAML defaults"
    )
    p_vigil.add_argument(
        "--once", action="store_true", help="Run one discovery and reconciliation cycle, then exit"
    )
    p_vigil.add_argument(
        # Spec-0065/T2: Complementation cap (and at most several sub-projects running ant)**K=1 i.e. degradation line** - parallel not
        # Another mode, only this number is greater than 1. The ceiling is naturally bound by the assue-dependent blocked_by, without a different sling button.
        "--parallel",
        type=_parallel_k,
        default=1,
        metavar="K",
        help=f"Maximum concurrent issues or PRs (default 1, maximum {_MAX_PARALLEL})",
    )
    p_vigil.add_argument(
        "--skip",
        default=None,
        metavar="STAGES",
        help="Treat stages as passed for this run, e.g. ci,e2e (stages.<stage>=skip)",
    )
    p_vigil.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="OpenAgents configuration file (default .openagents/openagents.yml)",
    )

    # Spec-0085/T2: finite, explicit v0.2 batch; unlike vigil it never polls or waits for humans.
    p_v02 = sub.add_parser(
        "v02", help="Run one v0.2 batch: Spec, DAG, Developer, Acceptance, merge"
    )
    p_v02.add_argument(
        "--issue",
        type=int,
        action="append",
        required=True,
        metavar="N",
        help="Issue number to include in the batch; repeatable",
    )
    p_v02.add_argument(
        "--parallel",
        type=_parallel_k,
        default=4,
        metavar="K",
        help="Maximum concurrent Spec and Developer jobs (default 4)",
    )
    p_v02.add_argument(
        "--base", default=None, help="Target branch (default from configuration, usually main)"
    )
    p_v02.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Configuration file (default .openagents/openagents.yml)",
    )
    p_v02.add_argument(
        "--user-test-command",
        default=None,
        metavar="COMMAND",
        help="Harness command for the User Test; requires --user-test-transcript",
    )
    p_v02.add_argument(
        "--user-test-transcript",
        default=None,
        metavar="PATH",
        help="JSON array of user events to replay against a candidate copy as primary Acceptance evidence",
    )
    p_v02.add_argument(
        "--user-test-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="User Test wall-clock limit in seconds (default 900)",
    )

    # Spec-0064/T5:path driver retroactive - Script inventory code path reverses and starts draft PR (achievement first, design later).
    p_backfill = sub.add_parser(
        "backfill-rfc", help="Backfill a Spec from existing code and open a draft PR"
    )
    p_backfill.add_argument("path", help="File or directory to inspect for Spec backfill")
    p_backfill.add_argument("--base", default="main", help="Base branch (default main)")

    # RFC-0002 T2: Proactively bring a GitHub issue (activated independent creation work, straight to github.create_issue) to the current project warehouse.
    p_issue = sub.add_parser("issue", help="Open an issue in the current GitHub repository")
    p_issue.add_argument("title", help="Issue title")
    p_issue.add_argument("--body", default="", help="Issue body (empty by default)")
    p_issue.add_argument(
        "--label",
        action="append",
        default=[],
        metavar="LABEL",
        help=f"Add a label (repeatable); always includes discovery label {DISCOVERY_LABEL!r}",
    )
    p_issue.add_argument(
        "--yes",
        action="store_true",
        help="Create the issue without interactive confirmation",
    )

    # Spec-0023/T4:release - the only macro-decision point for people: Pre-screening translates the main object that continues to advance into a version.
    p_release = sub.add_parser(
        "release", help="Release the current main HEAD after preflight checks"
    )
    p_release.add_argument(
        "--bump",
        choices=["patch", "minor", "major"],
        default="patch",
        help="Version component to bump (default patch); starts at v0.1.0 if there is no tag",
    )

    sub.add_parser("board", help="Open the local delivery dashboard")

    # Spec-0073/T2: desktop up local daemon (HTTP+SSE) for the Electron desktop app to read work_queue/ streams; read-only presentation.
    p_desktop = sub.add_parser(
        "desktop", help="Start the local HTTP and SSE daemon for the desktop dashboard"
    )
    p_desktop.add_argument(
        "--host", default="127.0.0.1", metavar="HOST", help="Listen address (default 127.0.0.1)"
    )
    p_desktop.add_argument(
        "--port",
        type=int,
        default=8765,
        metavar="PORT",
        help="Listen port (default 8765; 0 lets the OS choose)",
    )

    # Spec-0066/T3: Read. openagents/timing.jsonl, output single issue: length of wall clocks at each stage + cross issue p50/p90 text report
    # (Liability flow line bottlenecks: CI queue / review / waiting for how long each of the questions is waiting). Thin route, polymer logic in runtime.timing.
    p_report = sub.add_parser(
        "report",
        help="Report phase timings from timing.jsonl, with per-issue timelines and p50/p90",
    )
    p_report.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        help="Configuration file for the poll interval (default .openagents/openagents.yml)",
    )

    # Spec-0064/T5: hide internal commands -- only signed by a given (conflict resolution agent etc.) to comment back
    # The exits are broken by the removal of the self-reconcretional closed loop (bound to be 3 and still to identity.post_signed_comment.** Untransmitted `help=`**:argparse
    # Only add sub-commands to help list when they are available, so leave help to hide from the `--help` list but still interpret the distribution (no share)
    # The human mind; the help = SUPPRESS instead prints the text "=SUPPRESS=" noise.
    # Spec-0074/T1:merge-pr hides internal commands --merger agent down to merged**
    # Positioning: no help= hidden from the help list and still parsed for distribution. GitHub side meger still runs gh pr merge (zero changes);
    # $merge_command on Gitea is this command that token processes to stay in the driver without a hint.
    p_merge_pr = sub.add_parser("merge-pr")
    p_merge_pr.add_argument(
        "--pr", type=int, required=True, metavar="N", help="Pull request number to merge"
    )
    p_merge_pr.add_argument("--head-sha", default="", help="Merge only this approved candidate SHA")
    p_merge_pr.add_argument(
        "--method", default="merge", choices=["merge", "squash", "rebase"], help="Merge method"
    )

    p_reply = sub.add_parser("reply-comment")
    # Spec-0016/T5: --pr / --issue Second and First (Crust each other) - issue #149 - expand the number of signatures from PR to issue page.
    # Manual exit symmetry --issue. Still without help= (hidden internal command, Spec-0064/T5 position unchanged).
    p_reply_target = p_reply.add_mutually_exclusive_group(required=True)
    p_reply_target.add_argument(
        "--pr", type=int, metavar="N", help="Pull request number to reply to"
    )
    p_reply_target.add_argument("--issue", type=int, metavar="N", help="Issue number to reply to")
    p_reply.add_argument(
        "--body", required=True, help="Reply body; signed automatically with the agent identity"
    )

    return parser


# --------------------------------------------------------------------------------------------------
# Plant: Backend / state / Identity / e2e capacity solidification (delaying Import to keep cli top floor light, test to stick).
# --------------------------------------------------------------------------------------------------


def _persist_ui_capable(*, ctx: ProjectContext) -> None:
    # Spec-0055/T1: Zuile the "e2e capability" into state (single source of truth) when the Vigil entrance is launched.
    from openagents.utils import envcheck

    _new_runtime_state_for(ctx=ctx).set_ui_capable(value=envcheck.ui_capable())


def _agent_id_for(*, ctx: ProjectContext) -> str:
    # RFC-0011 Decision 7: The connection analyzes this example of identity and injects it downstream (vigil / reply-comment).
    from openagents.utils import identity

    return identity.resolve_agent_id(state=_new_runtime_state_for(ctx=ctx))


def _backend_for():
    # Spec-0020/T4: Single-line backend factory - delay import keeps cli top level light and tests can place a pillar on the plant (without touching the real LLM).
    if os.environ.get("OPENAGENTS_BACKEND", "").strip() == "nexau":
        from openagents.backends.nexau import NexAUBackend

        return NexAUBackend()
    from openagents.backends.claude_code import ClaudeCodeBackend

    return ClaudeCodeBackend()


def _new_runtime_state_for(*, ctx: ProjectContext):
    # Spec-0061/T4: New Dock RunteSlate Plant - Independent Namespace File runtime-state.json.
    from openagents.runtime.state import RUNTIME_STATE_FILENAME, RuntimeState

    return RuntimeState(path=ctx.repo_root / ".openagents" / RUNTIME_STATE_FILENAME)


def _vigil_deps_for(*, ctx: ProjectContext):
    """Spec-0064/T5: New Inn Vigil relies on a single link point for three sets (backend, state, agent_id) - run_vigil.

    backend/state/ identity is constructed to ensure consistency within the same Vigil process. The multiple-gauge recipes.vigil process interface
    `_run_repo_inline` also moved to the plant (which is co-sourced with CLI `vigil`), which is therefore a single point of contact for the Vigil of the new inn.
    """
    return _backend_for(), _new_runtime_state_for(ctx=ctx), _agent_id_for(ctx=ctx)


def _effective_config(*, ctx: ProjectContext, args: argparse.Namespace):
    """Spec-0064/T5: Load `.openagents/openagents.yml` (Single Real Source)+ superimpose the flag overlay of this run.

    `--skip <stages>`  →  One-time Skip (owner=skip); `--base` / `--interval` / `--label` over over overdone defaults.
    The coverage is still in its stages of legal extraction, a framework review package and ”no zero locks”.
    Do not change disk configuration.
    """
    import dataclasses

    from openagents.utils.agent_config import (
        OWNER_AGENT,
        OWNER_SKIP,
        STAGE_ARCHITECTURE,
        STAGE_CI,
        STAGE_E2E,
        STAGE_MERGE,
        STAGE_REVIEW,
        STAGE_RFC,
        STAGE_TRIAGE,
        StagePolicy,
        load_agent_config,
    )

    config_path = (
        Path(args.config) if args.config else ctx.repo_root / ".openagents" / "openagents.yml"
    )
    config = load_agent_config(path=config_path)

    skip_stages = _parse_gate_list(raw=args.skip)
    skippable = {STAGE_TRIAGE, STAGE_RFC, STAGE_ARCHITECTURE, STAGE_CI, STAGE_E2E, STAGE_REVIEW}
    invalid = skip_stages - skippable
    if invalid:
        raise ValueError(f"--skip does not support these stages: {sorted(invalid)}")

    owners = dict(config.stages.owners)
    for stage in skip_stages:
        owners[stage] = OWNER_SKIP
    # The coverage is re-enacted by "No Zero Gate" (without trial and blinding directly into the main).
    review = owners.get(STAGE_REVIEW, OWNER_AGENT)
    merge = owners.get(STAGE_MERGE, OWNER_AGENT)
    rfc = owners.get(STAGE_RFC, OWNER_AGENT)
    architecture = owners.get(STAGE_ARCHITECTURE, OWNER_AGENT)
    if rfc != OWNER_SKIP and architecture == OWNER_SKIP:
        raise ValueError("architecture can be skipped only when rfc is also skipped")
    if review == OWNER_SKIP and merge == OWNER_AGENT:
        raise ValueError("Automatic merge requires agent review")

    stages = StagePolicy(owners=owners)
    updates: dict = {"stages": stages}
    if args.base is not None:
        updates["base"] = args.base
    if args.interval is not None:
        updates["interval"] = args.interval
    if args.label:
        updates["labels"] = list(args.label)
    return dataclasses.replace(config, **updates)


def _parse_gate_list(*, raw: str | None) -> set[str]:
    """The comma-separated phase is deciphered into a collection (empty/None-square collection)."""
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip()}


# --------------------------------------------------------------------------------------------------
# Command handler.
# --------------------------------------------------------------------------------------------------


def _cmd_init(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0067/T2: Check and check and check and check and check and check. openagents/openagents.yml (Quix et al., --force over) --
    # Allows to have a commentable, directly reversible, declaration default for first time. The generator is only default, and the flag can still be overridden once in a run.
    from openagents.utils import envcheck
    from openagents.utils.agent_config import scaffold_default_config

    github.ensure_prerequisites()
    print(f"✓ Project ready: {ctx.repo_root} (remote: {ctx.remote})")

    config_path = ctx.repo_root / ".openagents" / "openagents.yml"
    existed = config_path.exists()
    if scaffold_default_config(path=config_path, force=args.force):
        if existed:
            print("✓ Replaced .openagents/openagents.yml with the packaged template")
        else:
            print(
                "✓ Wrote .openagents/openagents.yml. Edit it or override stages once with oa vigil --skip."
            )
    else:
        print("· Kept the existing .openagents/openagents.yml. Use --force to replace it.")

    print()
    print(envcheck.check().text)
    return 0


def _cmd_vigil(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0065/T2: Vigil Main Cycle - Read openagents.yml (+flag One-time overlay) run_vigil Chart-drived Parallel Vigil
    # (level-triggered reconcile: Producers are rated in GitHub, K-worker leads subproject).
    # `--parallel K` is the concurring cap;**K=1 is the degradation swab**(not another way) → run_fleet One process per warehouse.
    from openagents.recipes.vigil import run_fleet, run_vigil

    config = _effective_config(ctx=ctx, args=args)
    github.ensure_prerequisites()
    _persist_ui_capable(ctx=ctx)
    if len(config.repos) > 1:
        run_fleet(config=config, once=args.once)
        return 0
    backend, state, agent_id = _vigil_deps_for(ctx=ctx)
    from openagents.runtime import legacy

    # Test doubles without RuntimeState's read surface do not model persisted startup state.
    legacy.assert_migrated(state=state, inspect_forge=callable(getattr(state, "list_runs", None)))
    run_vigil(
        backend=backend,
        state=state,
        work_dir=ctx.repo_root,
        config=config,
        once=args.once,
        concurrency=args.parallel,
        agent_id=agent_id,
    )
    return 0


def _cmd_v02(args: argparse.Namespace, ctx: ProjectContext) -> int:
    """Run one explicit v0.2 batch and print every terminal result."""
    from openagents.runtime.user_test import load_user_test_plan
    from openagents.utils.agent_config import load_agent_config
    from openagents.v02.audit import write_result
    from openagents.v02.model import IssueInput
    from openagents.v02.openagents_adapter import OpenAgentsAdapter
    from openagents.v02.runner import run_batch

    config_path = (
        Path(args.config) if args.config else ctx.repo_root / ".openagents" / "openagents.yml"
    )
    config = load_agent_config(path=config_path)
    github.configure(name=config.forge, settings=config.gitea)
    github.ensure_prerequisites()
    issues = []
    for number in dict.fromkeys(args.issue):
        issue = github.get_issue(number=number)
        issues.append(IssueInput(number=issue.number, title=issue.title, body=issue.body))
    user_test_plan = _user_test_plan_from_args(args=args, loader=load_user_test_plan)
    result = run_batch(
        issues=issues,
        adapter=OpenAgentsAdapter(
            backend=_backend_for(),
            work_dir=ctx.repo_root,
            base=args.base or config.base,
            user_test_plan=user_test_plan,
            execution_evidence_required=config.execution_evidence_required,
        ),
        concurrency=args.parallel,
    )
    audit_path = write_result(work_dir=ctx.repo_root, result=result)
    for number in sorted(result.nodes):
        node = result.nodes[number]
        pr = f" PR #{node.pr_number}" if node.pr_number is not None else ""
        detail = f" — {node.reason}" if node.reason else ""
        print(f"{node.status:>21}  issue #{number}{pr}{detail}")
    print(f"Audit log: {audit_path}")
    return 0 if result.nodes and all(node.status == "PASS" for node in result.nodes.values()) else 1


def _user_test_plan_from_args(*, args: argparse.Namespace, loader):
    """Resolve v0.2 user-test flags without mutating the process environment."""
    command = getattr(args, "user_test_command", None)
    transcript = getattr(args, "user_test_transcript", None)
    timeout = getattr(args, "user_test_timeout", None)
    if command is None and transcript is None and timeout is None:
        return loader()
    values = dict(os.environ)
    if command is not None:
        values["OPENAGENTS_USER_TEST_COMMAND"] = command
    if transcript is not None:
        values["OPENAGENTS_USER_TEST_TRANSCRIPT"] = transcript
    if timeout is not None:
        values["OPENAGENTS_USER_TEST_TIMEOUT"] = str(timeout)
    return loader(values)


def _cmd_backfill_rfc(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0064/T5: Reconnect recipes.backfill.backfill_rfc (spec drive draft PR by code path).
    from openagents.recipes import backfill

    github.ensure_prerequisites()
    result = backfill.backfill_rfc(
        path=args.path, base=args.base, backend=_backend_for(), work_dir=ctx.repo_root
    )
    print(f"✓ Backfilled the Spec for `{args.path}` and opened draft PR #{result['pr_number']}")
    return 0


def _cmd_issue(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # RFC-0002 T2: Raise issue (Cront github.create_issue)+ Add Found Tags to reorder.
    labels = list(dict.fromkeys([*args.label, DISCOVERY_LABEL]))
    if not args.yes and not _confirm_issue_alignment(title=args.title, body=args.body):
        print("✗ Issue creation canceled", file=sys.stderr)
        return 1
    github.ensure_label(name=DISCOVERY_LABEL)
    issue = github.create_issue(title=args.title, body=args.body, labels=labels)
    print(f"✓ Created issue #{issue.number}：{issue.title}")
    return 0


def _confirm_issue_alignment(*, title: str, body: str) -> bool:
    # Spec-0020/T4: Build front door alignment before issue - repeat to read answer to decide whether release is granted.
    from openagents.utils import align

    alignment = align.restate(draft=align.Draft(title=title, body=body), backend=_backend_for())
    print("Confirm the scope before creating the issue:")
    print(alignment.render())
    answer = input("Create this issue? Enter y or yes: ")
    return align.is_confirmed(answer=answer)


def _cmd_reply_comment(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0064/T5: Hide Internal Command - coding agent returns the only exit to comment. post_signed_comment Queue Sign + Sync
    # Verifying the omission of the signature edit supplement (bound 3) so that the response is not considered a new human comment (prevent self-recycling).
    # Spec-0016/T5：--issue Roadway to the issue Signature export post_signed_comment_on_issue(Cyclical conjunction);
    # --pr maintains the existing post_signed_comment (no behavior change). The two are guaranteed by the mutual rebuffing of the Árgparse.
    from openagents.utils import identity

    agent_id = _agent_id_for(ctx=ctx)
    if args.issue is not None:
        identity.post_signed_comment_on_issue(number=args.issue, body=args.body, agent_id=agent_id)
        print(f"✓ Posted an agent reply to issue #{args.issue}")
        return 0
    identity.post_signed_comment(pr_number=args.pr, body=args.body, agent_id=agent_id)
    print(f"✓ Posted an agent reply to PR #{args.pr}")
    return 0


def _cmd_merge_pr(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # The platform for Spec-0074/T1:merger agent does not have a connection to the merger export - forwarding forge.merge_pr (merged, etc. is considered successful).
    # The sentence is output. "MERGED"（merger The word of the hint. $verify_command Contract; successful merger with non-zero exit.
    if not github.is_merged(pr_number=args.pr):
        github.merge_pr(pr_number=args.pr, method=args.method, head_sha=args.head_sha)
    if github.is_merged(pr_number=args.pr):
        print(f"✓ PR #{args.pr} state: MERGED")
        return 0
    print(f"✗ PR #{args.pr} is still not marked MERGED after the merge attempt", file=sys.stderr)
    return 1


def _cmd_release(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0023/T4: Determine hairstyle action, no agent - pre-checked and materialized release/vX.Y.Z branch + tag.
    from openagents.utils.release import release

    result = release(state=_new_runtime_state_for(ctx=ctx), bump=args.bump)
    if result.released:
        print(f"✓ Released {result.version} (release/{result.version} branch and tag)")
        return 0
    print(f"✗ Release preflight failed: {result.reason}", file=sys.stderr)
    return 1


def _cmd_report(args: argparse.Namespace, ctx: ProjectContext) -> int:
    # Spec-0066/T3: Read timing.jsonl  → titleting polymer  →  stdout text report. Thin route: Parsing path + fetch interval,
    # Aggregation/reconstruction is all on runtime.timing (uniissue time line + cross issue p50/p90 + Longest). Empty/missing file friendly tip, exit code 0.
    from openagents.runtime import timing, token_usage, tool_usage

    path = ctx.repo_root / ".openagents" / timing.TIMING_FILENAME
    events = timing.load_events(path=path)
    usage_path = ctx.repo_root / ".openagents" / tool_usage.TOOL_USAGE_FILENAME
    usage_events = tool_usage.load_events(path=usage_path)
    token_path = ctx.repo_root / ".openagents" / token_usage.TOKEN_USAGE_FILENAME
    token_events = token_usage.load_events(path=token_path)
    interval = _report_interval(ctx=ctx, args=args)
    print(
        _render_report(
            events=events,
            interval=interval,
            path=path,
            usage_events=usage_events,
            usage_path=usage_path,
            token_events=token_events,
            token_path=token_path,
        )
    )
    return 0


def _report_interval(*, ctx: ProjectContext, args: argparse.Namespace) -> int:
    # Spec-0066/T3: Round interval as a limit for wall clock accuracy -- read from openagents.yml, cannot read to create a default 60s for the return-down.
    from openagents.utils.agent_config import AgentConfigError, load_agent_config

    config_path = (
        Path(args.config) if args.config else ctx.repo_root / ".openagents" / "openagents.yml"
    )
    try:
        return load_agent_config(path=config_path).interval
    except (AgentConfigError, FileNotFoundError, OSError):
        return (
            60  # Missing profile should not fail the report - Build default query interval back in
        )


def _render_report(
    *,
    events: list,
    interval: int,
    path: Path,
    usage_events: list | None = None,
    usage_path: Path | None = None,
    token_events: list | None = None,
    token_path: Path | None = None,
) -> str:
    # Spec-0066/T3: Synthesize the fusion result into a stdout text table.** A visible indicator indicates the lower limit of the wall clock accuracy = a round of inquiry acceptance** (issue acceptance).
    from openagents.runtime import timing, token_usage, tool_usage

    usage_events = usage_events or []
    token_events = token_events or []
    if not events and not usage_events and not token_events:
        return (
            f"timing.jsonl is empty or missing: {path}\n"
            "Run `oa vigil` to collect phase timings before generating a report."
        )

    out: list[str] = []
    if events:
        lines = timing.timelines(events=events)
        stats = timing.phase_stats(events=events, interval=interval)
        out.append("OpenAgents phase timings")
        out.append(
            f"Phase durations are approximate to within the {interval}s poll interval (±{interval}s)."
        )
        out.append("")
        out.append("Time spent in each phase, by subject")
        for line in lines:
            head = f"{line.subject}"
            if line.pr is not None:
                head += f" (PR #{line.pr})"
            out.append(f"• {head}  total {_fmt_duration(seconds=line.total)}")
            for segment in line.segments:
                out.append(f"    {segment.phase:<20} {_fmt_duration(seconds=segment.seconds)}")
        out.append("")
        out.append("Phase duration distribution across subjects")
        out.append(f"    {'phase':<20} {'p50':>10} {'p90':>10}   Longest")
        for stat in stats.phases:
            out.append(
                f"    {stat.phase:<20} {_fmt_duration(seconds=stat.p50):>10} "
                f"{_fmt_duration(seconds=stat.p90):>10}   "
                f"{stat.max_subject} ({_fmt_duration(seconds=stat.max_seconds)})"
            )
    if usage_events:
        if out:
            out.append("")
        out.append("Agent tool usage and evidence lookup budgets")
        out.append(
            f"Data: {usage_path or tool_usage.TOOL_USAGE_FILENAME} (tool names only; arguments excluded)"
        )
        out.append(
            f"    {'role':<18} {'Calls':>6} {'Avg. lookups':>14} {'Max':>8} "
            f"{'Over limit':>8} {'No reason':>8}"
        )
        for row in tool_usage.aggregate(events=usage_events):
            out.append(
                f"    {row['role']:<18} {row['invocations']:>6} "
                f"{row['average_lookup_before_edit']:>14.1f} "
                f"{row['max_lookup_before_edit']:>8} {row['budget_exceeded']:>8} "
                f"{row['exceeded_without_reason']:>8}"
            )
    if token_events:
        if out:
            out.append("")
        out.append("Agent token usage and reporting coverage")
        out.append(f"Data: {token_path or token_usage.TOKEN_USAGE_FILENAME}")
        out.append(
            f"    {'role':<16} {'calls':>6} {'reported':>9} {'missing':>8} "
            f"{'input':>10} {'cache-r':>10} {'cache-w':>10} {'reason':>9} "
            f"{'output':>10} {'total':>11} {'total(r/d)':>11}"
        )
        for row in token_usage.aggregate(events=token_events):
            total_kinds = f"{row['reported_total_count']}/{row['derived_total_count']}"
            out.append(
                f"    {row['role']:<16} {row['invocations']:>6} {row['reported']:>9} "
                f"{row['unavailable']:>8} {row['input_tokens']:>10} "
                f"{row['cache_read_input_tokens']:>10} "
                f"{row['cache_creation_input_tokens']:>10} {row['reasoning_tokens']:>9} "
                f"{row['output_tokens']:>10} {row['total_tokens']:>11} {total_kinds:>11}"
            )
        out.append(
            "Missing counts are excluded. total(r/d) counts calls with reported or derived totals."
        )
    return "\n".join(out)


def _fmt_duration(*, seconds: float) -> str:
    # Spec-0066/T3: Second  →  time for reading people (0s / 45s / 3m0s / 1h2m). Pure display, no change in the aggregate value.
    total = int(round(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h{mins}m"


def _cmd_board(args: argparse.Namespace) -> int:
    # RFC-0001 T6：board No request. git/remote( Skipping) preflight）Read the new inn. RuntimeState Rendering board.
    from openagents.utils.results import board

    ctx = resolve_project()
    if ctx is None:
        ctx = ProjectContext(repo_root=Path.cwd(), remote=None)
    path = board(state=_new_runtime_state_for(ctx=ctx))
    print(f"✓ Delivery dashboard: {path}")
    return 0


def _cmd_desktop(args: argparse.Namespace) -> int:
    # Spec-0073/T2: Start local daemon (HTTP+SSE). Read only work_queue + streads ring Buffer, do not operate the repository/map, and do not operate the database.
    # So skip the preflight (sympathetic) db at <repo> /.openagents/vigil-queue.db (vigil --parallel drop-down).
    from openagents.desktop import daemon

    ctx = resolve_project()
    repo_root = ctx.repo_root if ctx is not None else Path.cwd()
    db_path = repo_root / ".openagents" / "vigil-queue.db"
    board_fn = daemon.default_board_fn(db_path=db_path, enrich=None)
    daemon.run(host=args.host, port=args.port, board_fn=board_fn)
    return 0


def _dispatch(args: argparse.Namespace) -> int:
    # Board does not operate the warehouse, skips the preflight.
    if args.command == "board":
        return _cmd_board(args)
    # Spec-0073/T2: desktop read only local work_queue/ streams, do not operate the repository/distant, and skip preflight.
    if args.command == "desktop":
        return _cmd_desktop(args)
    # Spec-0066/T3: report only local timing.jsonl, does not operate the repository/distant end, also skips preflight (no remote can report).
    if args.command == "report":
        ctx = resolve_project()
        if ctx is None:
            ctx = ProjectContext(repo_root=Path.cwd(), remote=None)
        return _cmd_report(args, ctx)

    ctx = ensure_project(interactive=True)
    handlers = {
        "init": _cmd_init,
        "vigil": _cmd_vigil,
        "v02": _cmd_v02,
        "backfill-rfc": _cmd_backfill_rfc,
        "issue": _cmd_issue,
        "reply-comment": _cmd_reply_comment,
        "merge-pr": _cmd_merge_pr,
        "release": _cmd_release,
    }
    return handlers[args.command](args, ctx)


def _run(args: argparse.Namespace) -> int:
    # RFC-0003 Decision 9: Converts known run-time errors into a clean line of tips + Non-zero exit without trailback (business abnormal delay import).
    # Spec-0064/T5: Error type change to accept back-up post-closure inn -backfill configuration failed to walk recipes.backfill.BackfillError; configuration
    # Illegally utils.agent_config.AgentConfigError; runtime GateError / AgentOutputError;utils stabilization face
    # GithubError / WorkspaceError。
    from openagents.recipes.backfill import BackfillError
    from openagents.runtime.engine import AgentOutputError
    from openagents.runtime.gates import GateError
    from openagents.utils.agent_config import AgentConfigError
    from openagents.utils.git import WorkspaceError
    from openagents.utils.github import GithubError

    try:
        return _dispatch(args)
    except ModuleNotFoundError as exc:
        top = (exc.name or "").split(".", 1)[0]
        if top == "openagents":
            raise
        print(
            f"✗ Missing dependency '{exc.name}'. Reinstall from the project root and retry:"
            f"uv pip install -e . (or uv sync)",
            file=sys.stderr,
        )
        return 1
    except (
        BackfillError,
        AgentConfigError,
        GateError,
        AgentOutputError,
        GithubError,
        WorkspaceError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    # Spec-0092/T3: even malformed capability arguments must never trigger updates.
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv and effective_argv[0] == "observation-capabilities":
        parser.parse_args(effective_argv)
        from openagents.observations.capabilities import emit

        return emit()
    # Spec-0069/T1: It must be tuned before parse_args (the only correct position specified in the argcomplete document). It is only filled with shell
    # Read parser when handshake (environmental variable _ARGCOMPLETE exists) create candidate and exit; return immediately in full operation, zero side effects, so below
    # Distribution/Exit Code/The chain of error processing is unchanged.
    if argcomplete is not None:
        argcomplete.autocomplete(parser)
    # Spec-0070/T1: Self-update Pre-screening - Ensured running on the latest uv tool before each command (scrap to git source decorate, source after pull)
    # The snapshot does not update automatically. pull --ff-only + uv tool install --force + execvp (a) Re-enforce this order;
    # Otherwise print actionable tips and fail-open Continue (offline)/Dirty workspace/feature The branch will never stop, never move. WIP）。Just answer openagents
    # Entry (spec command not answered); pass sys.argv (optional test participation for re-examining argv, not maain (argv)).
    # After argcomplete: argcomplete is out of here when handshake is completed; run a pre-check.
    from openagents.utils import selfupdate

    selfupdate.precheck(argv=sys.argv)
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help(sys.stderr)
        return 2
    return _run(args)


if __name__ == "__main__":
    sys.exit(main())
