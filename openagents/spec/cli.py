"""Create, validate, and render OpenAgents Specs.

Commands manage numbered Markdown groups and tasks, regenerate the overview
and architecture, and check file ownership. The default root is docs/specs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from openagents.spec import graph, model, mutate, ownership
from openagents.spec.render import write_overview
from openagents.spec.reservation import reserve_number
from openagents.spec.schema import PRIORITY_VALUES, STATUS_VALUES
from openagents.spec.validate import validate

_DEFAULT_SPECS_ROOT = Path("docs/specs")
_DEFAULT_PACKAGE_ROOT = Path("openagents")


def _csv(value: str) -> list[str]:
    """Comma separator  →  to remove empty list of non-empty items (for --files / --depends-on)."""
    return [item.strip() for item in value.split(",") if item.strip()]


def main(*, argv: list[str] | None = None) -> int:
    """Entry point for the `spec` console_script. returns the exit code (0 failed/ non-0 failed)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 2

    specs_root = args.specs_root
    if args.command == "new":
        return _cmd_new(
            specs_root=specs_root,
            slug=args.slug,
            title=args.title,
            issue=args.issue,
            summary=args.summary,
            number=args.number,
        )
    if args.command == "reserve-number":
        print(
            reserve_number(
                specs_root=specs_root,
                issue=args.issue,
                slug=args.slug,
                number=args.number,
            )
        )
        return 0
    if args.command == "add-task":
        return _cmd_add_task(specs_root=specs_root, args=args)
    if args.command == "render":
        return _cmd_render(specs_root=specs_root)
    if args.command == "validate":
        return _cmd_validate(specs_root=specs_root)
    if args.command == "abandon":
        return _cmd_abandon(
            specs_root=specs_root, group=args.group, task=args.task, reason=args.reason
        )
    if args.command == "graph":
        return _cmd_graph(specs_root=specs_root, package_root=args.package_root, check=args.check)
    if args.command == "ownership":
        return _cmd_ownership(
            specs_root=specs_root,
            group=args.group,
            changed=args.changed,
            check=args.check,
        )
    parser.print_help()
    return 2


def _build_parser() -> argparse.ArgumentParser:
    """Construct anargparse solver. --specs-root sets shared parent solver, written before and after the sub-command."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--specs-root",
        type=Path,
        default=_DEFAULT_SPECS_ROOT,
        help="Spec source directory (default docs/specs)",
    )

    parser = argparse.ArgumentParser(prog="spec", description=__doc__, parents=[common])
    sub = parser.add_subparsers(dest="command")

    new = sub.add_parser("new", help="Create a Spec group as a Markdown file", parents=[common])
    new.add_argument("slug", help="Group slug in kebab case")
    new.add_argument("--issue", type=int, required=True, help="Linked issue number")
    new.add_argument("--title", required=True, help="Group title")
    # Spec-0015: human voice TL; DR will fill - make writing summary a hard step to build.
    new.add_argument("--summary", required=True, help="Plain-language group summary (required)")
    new.add_argument(
        "--number",
        default=None,
        help="Group number NNNN; shared repositories require a remote reservation",
    )

    reserve = sub.add_parser(
        "reserve-number", help="Reserve a replacement number for an existing Spec", parents=[common]
    )
    reserve.add_argument("--issue", type=int, required=True, help="Linked issue number")
    reserve.add_argument("--slug", required=True, help="Group slug")
    reserve.add_argument(
        "--number", default=None, help="Requested number NNNN (default: next available)"
    )

    add = sub.add_parser("add-task", help="Add a task to a Spec group", parents=[common])
    add.add_argument("group", help="Group number NNNN or filename")
    add.add_argument("--id", required=True, dest="task_id", help="Task ID, e.g. T1")
    add.add_argument("--title", required=True, help="Task title")
    add.add_argument("--priority", choices=list(PRIORITY_VALUES), required=True, help="Priority")
    add.add_argument(
        "--status", choices=list(STATUS_VALUES), default="pending", help="Status (default pending)"
    )
    add.add_argument("--files", type=_csv, default=[], help="Owned files (comma-separated)")
    add.add_argument(
        "--depends-on",
        type=_csv,
        default=[],
        dest="depends_on",
        help="Dependencies (comma-separated)",
    )
    add.add_argument("--scope", default="", help="Task scope (Markdown)")
    add.add_argument("--acceptance", default="", help="Acceptance criteria (Markdown)")

    sub.add_parser("render", help="Generate OVERVIEW.md", parents=[common])
    sub.add_parser("validate", help="Validate Spec schema and semantics", parents=[common])

    abandon = sub.add_parser(
        "abandon", help="Remove a task from the snapshot; history remains in Git", parents=[common]
    )
    abandon.add_argument("group", help="Group number NNNN or filename")
    abandon.add_argument("task", help="Task ID, e.g. T3")
    abandon.add_argument(
        "--reason", required=True, help="Reason for removal, recorded in the commit message"
    )

    g = sub.add_parser("graph", help="Generate or validate ARCHITECTURE.md", parents=[common])
    g.add_argument(
        "--package-root",
        type=Path,
        default=_DEFAULT_PACKAGE_ROOT,
        help="Package to scan (default openagents)",
    )
    g.add_argument(
        "--check",
        action="store_true",
        help="Check module docstrings and verify the generated view is current",
    )

    own = sub.add_parser(
        "ownership",
        help="Show file ownership or validate a changeset (Spec-0071)",
        parents=[common],
    )
    own.add_argument("--group", default=None, help="Group number NNNN (required with --check)")
    own.add_argument(
        "--changed",
        type=_csv,
        default=[],
        help="Changed repository-relative paths (comma-separated) for --check",
    )
    own.add_argument(
        "--check",
        action="store_true",
        help="Exit with status 1 if a changed file has no owner in the group",
    )

    return parser


def _cmd_new(
    *, specs_root: Path, slug: str, title: str, issue: int, summary: str, number: str | None
) -> int:
    """New sub-command: Forward mutate.create_group, print new files."""
    path = mutate.create_group(
        specs_root=specs_root, slug=slug, title=title, issue=issue, summary=summary, number=number
    )
    print(f"✓ Created Spec group {path.name} ({path})")
    return 0


def _cmd_add_task(*, specs_root: Path, args: argparse.Namespace) -> int:
    """Add-task sub-command: forward mutate.add_task."""
    task = mutate.add_task(
        specs_root=specs_root,
        group=args.group,
        task_id=args.task_id,
        title=args.title,
        priority=args.priority,
        status=args.status,
        files=args.files,
        depends_on=args.depends_on,
        scope=args.scope,
        acceptance=args.acceptance,
    )
    print(f"✓ Added task {args.group}/{task.id} ({task.status})")
    return 0


def _cmd_render(*, specs_root: Path) -> int:
    """Render sub-command: Write OVERVIEW.md and print the path."""
    path = write_overview(specs_root=specs_root)
    print(f"✓ Wrote {path}")
    return 0


def _cmd_validate(*, specs_root: Path) -> int:
    """Validate sub-command: Print issues; there is an error returning 1, only warning returns 0."""
    report = validate(specs_root=specs_root)
    for issue in report.issues:
        print(f"[{issue.level}] {issue.where}: {issue.message}")
    if not report.ok:
        print("✗ Spec validation failed")
        return 1
    print("✓ Spec validation passed")
    return 0


def _cmd_abandon(*, specs_root: Path, group: str, task: str, reason: str) -> int:
    """abandon sub-command: forward mutate.abandon."""
    mutate.abandon(specs_root=specs_root, group=group, task_id=task, reason=reason)
    print(f"✓ Removed task {group}/{task}")
    return 0


def _cmd_ownership(*, specs_root: Path, group: str | None, changed: list[str], check: bool) -> int:
    """An downership sub-command: --check verify changeset unauthorised (exit code 1); otherwise print a single Writer title table.

    Spec-0071/T2: Make the ownership of a ”single Writer” file a searchable/ verifiable run-time. --check requires --group designation
    Verify which group, according to `spec.ownership.unowned_writes`, is unauthorised; none --check prints the owner → path table by group.
    """
    groups = model.load_all(specs_root=specs_root)
    if check:
        if group is None:
            print("[error] --check requires --group NNNN")
            return 2
        target = next((g for g in groups if g.number == group), None)
        if target is None:
            print(f"[error] Group {group} not found under {specs_root}")
            return 2
        offenders = ownership.unowned_writes(
            group=target, changed_paths=changed, specs_root=specs_root
        )
        for path in offenders:
            print(
                f"[error] {path}: unowned write (group {target.number} does not own this file and it is not generated)"
            )
        if offenders:
            print(f"✗ Ownership check failed: {len(offenders)} unowned writes")
            return 1
        print(
            f"✓ Ownership check passed for group {target.number}: all {len(list(changed))} changed files are owned or generated"
        )
        return 0

    # No --check: Print a single writer ownership table (owner Task  →  declaration file, sorted by group, by path).
    print("# File ownership (Spec-0071: owning task and declared file)")
    for grp in groups:
        index = ownership.build_index(group=grp)
        for path in sorted(index.by_path):
            print(f"{index.by_path[path]}\t{path}")
    return 0


def _cmd_graph(*, specs_root: Path, package_root: Path, check: bool) -> int:
    """Sub-command for graph: --check verify docstring + drift; otherwise ARCHITECTURE.md is generated."""
    if not check:
        path = graph.write_architecture(specs_root=specs_root, package_root=package_root)
        print(f"✓ Wrote {path}")
        return 0

    # --check 1:) Docstrining All; 2) ARCHITECTURE.md does not drift with the code.
    missing = graph.missing_docstrings(package_root=package_root)
    current = specs_root / graph.ARCHITECTURE_FILENAME
    expected = graph.render_architecture(package_root=package_root)
    drift = (not current.is_file()) or current.read_text(encoding="utf-8") != expected

    for path_str in missing:
        print(f"[error] {path_str}: missing a module docstring")
    if drift:
        print(f"[error] {current}: does not match the code; regenerate with `spec graph`")
    if missing or drift:
        print("✗ Architecture graph validation failed")
        return 1
    print("✓ Architecture graph is current and docstrings are present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
