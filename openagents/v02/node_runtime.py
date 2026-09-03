# Spec-0085/T3
"""Phase runner used inside one isolated v0.2 issue container."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import asdict
from pathlib import Path

from openagents.backends.claude_code import ClaudeCodeBackend
from openagents.backends.nexau import NexAUBackend
from openagents.utils import forge
from openagents.v02.model import DevelopmentResult, IssueInput, SpecNode
from openagents.v02.openagents_adapter import OpenAgentsAdapter
from openagents.v02.planner import build_plan

_WORKSPACE = Path("/workspace/repo")
_EXPORT = Path("/export")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("spec", "plan", "develop", "merge"))
    args = parser.parse_args(argv)
    _EXPORT.mkdir(parents=True, exist_ok=True)
    try:
        if args.phase == "spec":
            _spec()
        elif args.phase == "plan":
            _plan()
        elif args.phase == "develop":
            _develop()
        else:
            _merge()
    except Exception as exc:
        _write_json(
            path=_EXPORT / f"{args.phase}.error.json",
            payload={"phase": args.phase, "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    return 0


def _spec() -> None:
    issue_number = int(os.environ["V02_ISSUE_NUMBER"])
    _prepare_repository(issue_number=issue_number)
    _configure_forge()
    remote_issue = forge.get_issue(number=issue_number)
    issue = IssueInput(remote_issue.number, remote_issue.title, remote_issue.body)
    adapter = _adapter()
    outcome = adapter.write_spec(issue=issue)
    if isinstance(outcome, SpecNode):
        payload = {
            "kind": "ready",
            "issue": asdict(issue),
            "branch": outcome.branch,
            "worktree": str(outcome.worktree),
            "spec_path": str(outcome.spec_path),
            "spec_digest": outcome.spec_digest,
            "summary": outcome.summary,
            "files": list(outcome.files),
            "selected_intervention": outcome.selected_intervention,
            "evidence_pack": list(outcome.evidence_pack),
        }
        shutil.copy2(outcome.spec_path, _EXPORT / f"issue-{issue_number}.md")
    else:
        payload = {"kind": "terminal", "result": asdict(outcome)}
    _write_json(path=_EXPORT / "spec.json", payload=payload)


def _plan() -> None:
    inputs_root = Path(os.environ["V02_PLAN_INPUTS"])
    nodes = []
    for path in sorted(inputs_root.glob("issue-*/spec.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("kind") == "ready":
            nodes.append(_node(payload=payload))
    if not nodes:
        _write_json(path=_EXPORT / "plan.json", payload={"blocked_by": {}, "batches": []})
        return
    control = Path("/workspace/control")
    control.mkdir(parents=True, exist_ok=True)
    if not (control / ".git").exists():
        _run("git", "init", cwd=control)
    semantic = _adapter(work_dir=control).curate(nodes=tuple(nodes))
    plan = build_plan(nodes=nodes, semantic_edges=semantic)
    _write_json(path=_EXPORT / "plan.json", payload=asdict(plan) | {"semantic_edges": semantic})


def _develop() -> None:
    payload = json.loads((_EXPORT / "spec.json").read_text(encoding="utf-8"))
    if payload.get("kind") != "ready":
        _write_json(path=_EXPORT / "development.json", payload={"status": "NOT_RUN"})
        return
    node = _node(payload=payload)
    _configure_forge()
    adapter = _adapter()
    development = adapter.develop(node=node)
    record: dict = {"development": asdict(development)}
    if development.status == "DELIVERED":
        acceptance = adapter.accept(node=node, development=development)
        record["acceptance"] = asdict(acceptance)
    _write_json(path=_EXPORT / "development.json", payload=record)


def _merge() -> None:
    node = _node(payload=json.loads((_EXPORT / "spec.json").read_text(encoding="utf-8")))
    record = json.loads((_EXPORT / "development.json").read_text(encoding="utf-8"))
    acceptance = record.get("acceptance") or {}
    if acceptance.get("verdict") != "PASS":
        raise RuntimeError("Acceptance 未 PASS，拒绝合并")
    development = DevelopmentResult(**_tuple_development(record["development"]))
    if acceptance.get("head_sha") != development.head_sha:
        raise RuntimeError("Acceptance PASS 未绑定 Developer 当前 HEAD")
    _configure_forge()
    _adapter().merge(node=node, development=development)
    _write_json(
        path=_EXPORT / "merge.json",
        payload={"status": "PASS", "head_sha": development.head_sha, "pr_number": development.pr_number},
    )


def _adapter(*, work_dir: Path = _WORKSPACE) -> OpenAgentsAdapter:
    return OpenAgentsAdapter(
        backend=_backend(), work_dir=work_dir, base=os.environ.get("V02_BASE", "main")
    )


def _backend() -> ClaudeCodeBackend | NexAUBackend:
    name = os.environ.get("V02_BACKEND", "nexau").strip().lower()
    if name in {"claude-code", "claude_code", "cc"}:
        return ClaudeCodeBackend()
    if name == "nexau":
        return NexAUBackend()
    raise ValueError(f"未知 V02_BACKEND：{name}")


def _node(*, payload: dict) -> SpecNode:
    issue_raw = payload["issue"]
    return SpecNode(
        issue=IssueInput(**issue_raw),
        branch=payload["branch"],
        worktree=Path(payload["worktree"]),
        spec_path=Path(payload["spec_path"]),
        spec_digest=payload["spec_digest"],
        summary=payload["summary"],
        files=tuple(payload.get("files") or ()),
        selected_intervention=dict(payload.get("selected_intervention") or {}),
        evidence_pack=tuple(payload.get("evidence_pack") or ()),
    )


def _tuple_development(payload: dict) -> dict:
    normalized = dict(payload)
    normalized["changed_files"] = tuple(normalized.get("changed_files") or ())
    normalized["evidence"] = tuple(normalized.get("evidence") or ())
    return normalized


def _prepare_repository(*, issue_number: int) -> None:
    if _WORKSPACE.exists():
        return
    _WORKSPACE.parent.mkdir(parents=True, exist_ok=True)
    _run("git", "clone", os.environ["V02_REPO_URL"], str(_WORKSPACE), cwd=_WORKSPACE.parent)
    _run("git", "config", "user.name", "OpenAgents v0.2", cwd=_WORKSPACE)
    _run("git", "config", "user.email", "openagents-v02@example.invalid", cwd=_WORKSPACE)
    helper = "!f(){ echo username=openagents; echo password=$GITEA_TOKEN; };f"
    _run("git", "config", "credential.helper", helper, cwd=_WORKSPACE)
    seed_sha = os.environ.get("V02_SEED_SHA", "").strip()
    if seed_sha:
        _run("git", "checkout", "--detach", seed_sha, cwd=_WORKSPACE)
        _run("git", "branch", "-f", os.environ.get("V02_BASE", "main"), seed_sha, cwd=_WORKSPACE)
        _run("git", "checkout", os.environ.get("V02_BASE", "main"), cwd=_WORKSPACE)
    # Workspace.prepare owns the actual issue branch and worktree.
    if issue_number < 1:
        raise ValueError("issue number must be positive")


def _configure_forge() -> None:
    forge.configure(
        name="gitea",
        settings={
            "base_url": os.environ["V02_GITEA_BASE_URL"],
            "owner": os.environ["V02_GITEA_OWNER"],
            "repo": os.environ["V02_GITEA_REPO"],
            "token_env": "GITEA_TOKEN",
        },
    )


def _run(*args: str, cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise RuntimeError(f"{args[0]} {args[1]} failed: {detail}")


def _write_json(*, path: Path, payload: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
