#!/usr/bin/env python3
"""Plan or apply the explicit Spec-0081 legacy-state migration.

The default is a read-only dry run. ``--apply`` converts runtime ``blocked`` records and
forge ``needs-human`` labels to their autonomous failure equivalents. Configuration owners
set to ``human`` are only reported: choosing ``agent`` versus ``skip`` remains an operator decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from openagents.runtime.legacy import LEGACY_LABEL, LEGACY_RUN_STATUS  # noqa: E402
from openagents.runtime.state import RUNTIME_STATE_FILENAME, STATUS_FAILED  # noqa: E402
from openagents.utils import forge, identity  # noqa: E402
from openagents.utils.github import AUTOMATION_FAILED_LABEL  # noqa: E402

_CONFIG = Path(".openagents/openagents.yml")
_MARKER = "<!-- openagents:migration:0081"
_yaml = YAML(typ="safe")


def scan_local(*, repo: Path) -> dict[str, Any]:
    """Return runtime conversions and manual configuration decisions without writing."""
    root = Path(repo).resolve()
    runtime_path = root / ".openagents" / RUNTIME_STATE_FILENAME
    runtime = _read_json(path=runtime_path)
    runs = runtime.get("runs") if isinstance(runtime, dict) else {}
    blocked_runs = sorted(
        int(key)
        for key, record in (runs or {}).items()
        if isinstance(record, dict) and record.get("status") == LEGACY_RUN_STATUS
    )
    config_path = root / _CONFIG
    config = _read_yaml(path=config_path)
    manual_owners = _manual_owner_paths(value=config)
    return {
        "runtime_path": runtime_path,
        "blocked_runs": blocked_runs,
        "config_path": config_path,
        "manual_owners": manual_owners,
    }


def apply_runtime(*, runtime_path: Path) -> list[int]:
    """Atomically and idempotently map legacy runtime terminals to ``failed``."""
    data = _read_json(path=runtime_path)
    if not data:
        return []
    changed: list[int] = []
    for key, record in (data.get("runs") or {}).items():
        if isinstance(record, dict) and record.get("status") == LEGACY_RUN_STATUS:
            record["status"] = STATUS_FAILED
            changed.append(int(key))
    if not changed:
        return []
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = runtime_path.with_suffix(runtime_path.suffix + ".spec0081.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, runtime_path)
    return sorted(changed)


def scan_forge() -> dict[str, list[Any]]:
    """Discover open forge objects carrying the retired terminal label."""
    issues = forge.list_issues(labels=[LEGACY_LABEL])
    prs = [
        pr
        for pr in forge.list_open_prs()
        if forge.has_label(pr_number=pr.number, name=LEGACY_LABEL)
    ]
    return {"issues": issues, "prs": prs}


def apply_forge(*, plan: dict[str, list[Any]]) -> list[str]:
    """Migrate forge objects in add-comment-remove order so partial failure is retry-safe."""
    forge.ensure_label(
        name=AUTOMATION_FAILED_LABEL,
        description="OpenAgents autonomous failure terminal",
    )
    changed: list[str] = []
    for issue in plan["issues"]:
        subject = f"issue:{issue.number}"
        comments = forge.list_issue_comments(number=issue.number)
        body = _diagnostic(subject=subject, comments=comments)
        forge.issue_add_label(number=issue.number, name=AUTOMATION_FAILED_LABEL)
        if not _already_diagnosed(subject=subject, comments=comments):
            forge.issue_comment(number=issue.number, body=body)
        forge.issue_remove_label(number=issue.number, name=LEGACY_LABEL)
        changed.append(subject)
    for pr in plan["prs"]:
        subject = f"pr:{pr.number}"
        comments = forge.list_comments(pr_number=pr.number)
        body = _diagnostic(subject=subject, comments=comments)
        forge.add_label(pr_number=pr.number, name=AUTOMATION_FAILED_LABEL)
        if not _already_diagnosed(subject=subject, comments=comments):
            forge.post_comment(pr_number=pr.number, body=body)
        forge.remove_label(pr_number=pr.number, name=LEGACY_LABEL)
        changed.append(subject)
    return changed


def _already_diagnosed(*, subject: str, comments: list[Any]) -> bool:
    return any(f"{_MARKER} subject={subject} -->" in str(comment.body) for comment in comments)


def _diagnostic(*, subject: str, comments: list[Any]) -> str:
    previous = next(
        (
            str(comment.body).strip()
            for comment in reversed(comments)
            if LEGACY_LABEL in str(comment.body)
        ),
        "No prior signed diagnostic was found; the retired label itself was preserved as the source fact.",
    )
    digest = hashlib.sha256(f"{subject}\0{previous}".encode()).hexdigest()
    return identity.sign(
        body=(
            f"{_MARKER} subject={subject} -->\n"
            "OpenAgents automation failed\n\n"
            "category: migrated-legacy-terminal\n"
            "attempts: unknown\n"
            f"fingerprint: legacy:{digest}\n\n"
            "Original diagnostic:\n\n"
            f"{previous[-2000:]}"
        ),
        agent_id="spec-0081-migration",
    )


def _read_json(*, path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read runtime state {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"runtime state {path} must contain a JSON object")
    return value


def _read_yaml(*, path: Path) -> Any:
    if not path.exists():
        return {}
    return _yaml.load(path.read_text(encoding="utf-8")) or {}


def _manual_owner_paths(*, value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}/{key}" if prefix else str(key)
            if (
                key in {"triage", "rfc", "architecture", "ci", "e2e", "review", "conflict", "merge"}
                and child == "human"
            ):
                found.append(path)
            else:
                found.extend(_manual_owner_paths(value=child, prefix=path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_manual_owner_paths(value=child, prefix=f"{prefix}/{index}"))
    return sorted(found)


def _configure_forge(*, repo: Path) -> None:
    data = _read_yaml(path=Path(repo).resolve() / _CONFIG)
    name = str(data.get("forge") or "github") if isinstance(data, dict) else "github"
    settings = data.get("gitea") if isinstance(data, dict) else None
    forge.configure(name=name, settings=settings if isinstance(settings, dict) else {})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--no-forge", action="store_true", help="Only inspect local config/runtime state"
    )
    args = parser.parse_args(argv)

    local = scan_local(repo=args.repo)
    forge_plan: dict[str, list[Any]] = {"issues": [], "prs": []}
    if not args.no_forge:
        _configure_forge(repo=args.repo)
        forge_plan = scan_forge()

    for issue in local["blocked_runs"]:
        print(f"runtime issue #{issue}: {LEGACY_RUN_STATUS} -> {STATUS_FAILED}")
    for path in local["manual_owners"]:
        print(f"config {path}: human owner requires an explicit edit to agent or an allowed skip")
    for issue in forge_plan["issues"]:
        print(f"forge issue #{issue.number}: {LEGACY_LABEL} -> {AUTOMATION_FAILED_LABEL}")
    for pr in forge_plan["prs"]:
        print(f"forge PR #{pr.number}: {LEGACY_LABEL} -> {AUTOMATION_FAILED_LABEL}")

    if not args.apply:
        print("dry-run: no changes written")
        return 0
    changed_runs = apply_runtime(runtime_path=local["runtime_path"])
    changed_forge = [] if args.no_forge else apply_forge(plan=forge_plan)
    print(f"applied: runtime={len(changed_runs)} forge={len(changed_forge)}")
    if local["manual_owners"]:
        print("configuration was not rewritten; Vigil remains fail-closed until owners are edited")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
