#!/usr/bin/env python3
"""Spec-0092/T4: offline reader contract, or explicit live synthetic-issue readback.

Live mode only reads the specified issue and its member asset; it neither calls a
model nor writes a remote comment. Temporary evidence and Git metadata are removed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import io
import json
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from openagents.observations import evidence
from openagents.runtime import context as runtime_context
from openagents.runtime import engine
from openagents.runtime.state import RuntimeState
from openagents.utils import forge

FIXTURE = Path(__file__).resolve().parents[1] / "tests/fixtures/observation_transport_contract.json"


def encode(value: dict, encoding: str) -> bytes:
    """Make deterministic synthetic envelopes, not production publication code."""
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    if encoding == "gzip":
        return gzip.compress(raw, mtime=0)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        entry = zipfile.ZipInfo("evidence.json", date_time=(1980, 1, 1, 0, 0, 0))
        entry.compress_type = zipfile.ZIP_DEFLATED
        entry.external_attr = (stat.S_IFREG | 0o600) << 16
        archive.writestr(entry, raw, compresslevel=6)
    return output.getvalue()


def verify_scope(*, scope: dict | None, expected: dict, digest: str) -> dict:
    """Require actual authorized, verified files; a degraded prepare is a failure."""
    assert scope is not None, "reader did not prepare evidence"
    assert scope.get("digest") == digest, "reader did not verify expected digest"
    assert scope["sessions"] == [row["session_id"] for row in expected["sessions"]]
    root = Path(scope["request_path"]).parent
    checked = 0
    for row in expected["sessions"]:
        if row["status"] != "available":
            continue
        for name, text in row["files"].items():
            path = root / row["session_id"] / name
            assert path.is_file() and not path.is_symlink(), "missing evidence file"
            assert path.read_text(encoding="utf-8") == text, "evidence content mismatch"
            assert stat.S_IMODE(path.stat().st_mode) == 0o400, "evidence must be read-only"
            checked += 1
    assert checked > 0, "probe must contain available evidence"
    return {"sessions": scope["sessions"], "digest": digest, "files_checked": checked}


def prepare_probe(*, expected: dict, digest: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="oa-evidence-probe-") as name:
        root = Path(name)
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        scope = evidence.prepare(work_dir=root, issue=expected["issue"], role="implementer")
        return verify_scope(scope=scope, expected=expected, digest=digest)


def check_offline(fixture: Path = FIXTURE) -> dict:
    contract = json.loads(fixture.read_text())
    value = contract["package"]
    results = []
    for variant in contract["accepted"]:
        data = encode(value, variant["encoding"])
        digest = hashlib.sha256(data).hexdigest()
        handle = {"asset_id": 1, "name": "synthetic", "sha256": digest, "bytes": len(data)}
        if variant["declare"]:
            handle["encoding"] = variant["encoding"]
        body = f"<!-- {evidence.MARKER} {json.dumps(handle)} -->"
        with (
            patch.object(forge, "active_forge", return_value="gitea"),
            patch.object(forge, "get_issue", return_value=SimpleNamespace(body=body)),
            patch.object(forge, "download_observation_asset", return_value=data, create=True),
        ):
            results.append(prepare_probe(expected=value, digest=digest))
    data = encode(value, "zip")
    digest = hashlib.sha256(data).hexdigest()
    cases = {
        "missing-zip-declaration": {"encoding": "gzip"},
        "unknown-encoding": {"encoding": "unknown"},
        "wrong-digest": {"digest": "0" * 64},
        "wrong-issue": {"issue": value["issue"] + 1},
    }
    for case in contract["rejected"]:
        args = dict(data=data, digest=digest, issue=value["issue"], encoding="zip")
        args.update(cases[case["case"]])
        try:
            evidence.decode_package(**args)
        except ValueError as exc:
            assert case["reason"] in str(exc), "unexpected rejection reason"
        else:
            raise AssertionError("invalid envelope accepted")
    return {"status": "passed", "accepted": len(results), "rejected": len(cases)}


def check_execution_contract(*, fixture: Path) -> dict:
    """Spec-0093/T1,T3: exercise verified transport and real engine/role context.

    No model is called. The backend boundary is observed, not simulated reasoning.
    """
    value = json.loads(fixture.read_text())["package"]
    roles = (
        "drafter",
        "spec_writer",
        "architect",
        "implementer",
        "executor",
        "reviewer",
        "acceptance",
    )
    calls = []

    class Observed(Exception):
        pass

    class Backend:
        name = "execution-context-probe"

        def run(self, *, work_dir, task, context):
            for contract in value["execution_evidence"]["execution_contracts"]:
                assert contract["contract_id"] in context, "missing contract in final context"
                assert f"followup_input={contract['followup_input']}" in context
                assert f"budget_seconds={contract['task_budget_seconds']}" in context
            assert value["execution_evidence"]["payload_sha256"] in context
            assert "execution-page-" in context
            calls.append(context)
            raise Observed()

    for encoding in ("gzip", "zip"):
        data = encode(value, encoding)
        digest = hashlib.sha256(data).hexdigest()
        handle = {"asset_id": 1, "sha256": digest, "bytes": len(data), "encoding": encoding}
        body = f"<!-- {evidence.MARKER} {json.dumps(handle)} -->"
        with tempfile.TemporaryDirectory(prefix="oa-execution-probe-") as name:
            root = Path(name)
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            state = RuntimeState(path=root / ".openagents" / "runtime-state.json")
            with (
                patch.object(forge, "active_forge", return_value="gitea"),
                patch.object(forge, "get_issue", return_value=SimpleNamespace(body=body)),
                patch.object(forge, "download_observation_asset", return_value=data, create=True),
                runtime_context.execution_dispatch(state=state, required=True),
            ):
                scope = evidence.prepare(
                    work_dir=root, issue=value["issue"], role="implementer", execution_required=True
                )
                verify_scope(scope=scope, expected=value, digest=digest)
                for role in roles:
                    module = importlib.import_module(f"openagents.agents.{role}")
                    placeholders = {key: f"probe-{key}" for key in module.PROMPT.get_identifiers()}
                    placeholders.update(
                        work_dir=root,
                        issue_number=value["issue"],
                        context="original public issue context",
                        target=f"issue #{value['issue']}",
                    )
                    try:
                        engine.run_agent(module, backend=Backend(), **placeholders)
                    except Observed:
                        pass
                    else:
                        raise AssertionError("backend boundary was not observed")
    return {
        "status": "passed",
        "encodings": ["gzip", "zip"],
        "roles": list(roles),
        "backend_contexts": len(calls),
        "model_calls": 0,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument(
        "--execution-fixture",
        type=Path,
        help="also verify execution facts at actual role/backend boundaries",
    )
    parser.add_argument(
        "--live", action="store_true", help="explicitly read a synthetic probe issue"
    )
    parser.add_argument("--base-url")
    parser.add_argument("--owner")
    parser.add_argument("--repo")
    parser.add_argument("--token-env", default="GITEA_TOKEN")
    parser.add_argument(
        "--expected-package", type=Path, help="synthetic inner JSON with issue number"
    )
    parser.add_argument("--sha256", help="expected attachment digest")
    args = parser.parse_args(argv)
    try:
        if args.live:
            if not all([args.base_url, args.owner, args.repo, args.expected_package, args.sha256]):
                parser.error("--live requires base URL, owner, repo, expected package and sha256")
            forge.configure(
                name="gitea",
                settings={
                    "base_url": args.base_url,
                    "owner": args.owner,
                    "repo": args.repo,
                    "token_env": args.token_env,
                },
            )
            result = prepare_probe(
                expected=json.loads(args.expected_package.read_text()), digest=args.sha256
            )
            result["status"] = "passed"
        else:
            result = check_offline(args.fixture)
            if args.execution_fixture:
                result["execution_evidence"] = check_execution_contract(
                    fixture=args.execution_fixture
                )
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        # Never print a transport exception or signed query from a failed live probe.
        print(json.dumps({"status": "failed", "error": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
