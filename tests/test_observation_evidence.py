"""Spec-0087: opaque formats, scope, runner binding and recoverable delivery requests."""

import gzip
import hashlib
import json
import subprocess
from pathlib import Path
from string import Template
from types import SimpleNamespace

import pytest

from openagents.backends.base import AgentResult
from openagents.observations import evidence, gaps
from openagents.runtime import engine
from openagents.utils import forge


def package(issue=7, path="runs/r1/event-v2.tsv", content="work-token\tnew-request"):
    files = {path: content}
    files["manifest.json"] = json.dumps(
        {
            "session_id": "s1",
            "files": [{"path": path, "sha256": hashlib.sha256(content.encode()).hexdigest()}],
        }
    )
    value = {
        "format": evidence.MARKER,
        "issue": issue,
        "sessions": [{"session_id": "s1", "status": "available", "files": files}],
    }
    data = gzip.compress(json.dumps(value).encode())
    return data, hashlib.sha256(data).hexdigest()


def request(**kw):
    return {
        "request_id": "ownership",
        "scope": "harness",
        "question": "Which request?",
        "checked": "v1 logs",
        "unknowns": "old or new",
        "impact": "Cannot verify cancel",
        "desired_capability": "Distinguish owner",
        "verification": "Overlap two requests",
        "session_ids": ["s1"],
        "related_issues": [7],
        **kw,
    }


@pytest.fixture
def configured(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    data, digest = package()
    handle = {"asset_id": 1, "sha256": digest, "bytes": len(data)}
    body = f"<!-- {evidence.MARKER} {json.dumps(handle)} -->"
    monkeypatch.setattr(forge, "active_forge", lambda: "gitea")
    monkeypatch.setattr(forge, "get_issue", lambda **kw: SimpleNamespace(body=body))
    monkeypatch.setattr(forge, "download_observation_asset", lambda **kw: data, raising=False)
    monkeypatch.setattr(forge, "list_issue_comments", lambda **kw: [])
    monkeypatch.setattr(forge, "observation_request_exists", lambda **kw: False, raising=False)
    comments = []
    monkeypatch.setattr(forge, "issue_comment", lambda **kw: comments.append(kw))
    return tmp_path, comments


def test_opaque_data_need_not_use_nexau_fields():
    data, digest = package()
    assert evidence.decode_package(data=data, digest=digest, issue=7)["sessions"][0]["files"]


@pytest.mark.parametrize(
    "path", ["../outside", "/tmp/outside", "a/../../outside", "a\\escape", "."]
)
def test_unsafe_paths_rejected(path):
    data, digest = package(path=path)
    with pytest.raises(ValueError):
        evidence.decode_package(data=data, digest=digest, issue=7)


def test_digest_issue_and_expansion_limits():
    data, digest = package()
    with pytest.raises(ValueError):
        evidence.decode_package(data=data, digest="0" * 64, issue=7)
    with pytest.raises(ValueError):
        evidence.decode_package(data=data, digest=digest, issue=8)
    bomb = gzip.compress(b"x" * (evidence.MAX_EXPANDED + 1))
    with pytest.raises(ValueError, match="expanded"):
        evidence.decode_package(data=bomb, digest=hashlib.sha256(bomb).hexdigest(), issue=7)


def test_every_delivery_role_receives_scoped_context_and_can_report(configured):
    work_dir, comments = configured

    class Backend:
        name = "controlled"

        def run(self, *, work_dir, task, context):
            assert "runs" not in task  # raw runtime data is not in the role instruction
            assert "s1:" in context and "manifest.json" in context
            assert "日志" in context and "framework" in context
            candidates = list((work_dir / ".openagents/observation-evidence").glob("issue-7-*"))
            invocation = max(candidates, key=lambda p: p.stat().st_mtime_ns)
            (invocation / "requests.json").write_text(json.dumps([request()]))
            return AgentResult(changed=False, summary='{"status":"ok"}')

    for role in sorted(evidence.ROLES):
        module = SimpleNamespace(
            __name__=f"openagents.agents.{role}",
            PROMPT=Template("role task"),
            OUTPUT_SCHEMA={"status": str},
        )
        assert engine.run_agent(
            module, backend=Backend(), work_dir=work_dir, issue_number=7, context="issue objective"
        ) == {"status": "ok"}
    assert len(comments) == len(evidence.ROLES)
    assert all(c["number"] == 7 and gaps.MARKER in c["body"] for c in comments)


def test_offline_queue_retries_without_losing_scope(configured, monkeypatch):
    work_dir, comments = configured
    scope = evidence.prepare(work_dir=work_dir, issue=7, role="reviewer")
    Path(scope["request_path"]).write_text(json.dumps([request()]))
    send = forge.issue_comment
    monkeypatch.setattr(
        forge, "issue_comment", lambda **kw: (_ for _ in ()).throw(OSError("offline"))
    )
    gaps.collect_requests(scope=scope)
    row = json.loads(next(gaps.outbox_root(work_dir=work_dir).glob("*.json")).read_text())
    assert row["state"] == "pending"
    monkeypatch.setattr(forge, "issue_comment", send)
    gaps.retry_pending(work_dir=work_dir)
    gaps.retry_pending(work_dir=work_dir)
    assert len(comments) == 1


def test_request_cannot_expand_scope_or_treat_logs_as_requests(configured):
    work_dir, comments = configured
    scope = evidence.prepare(work_dir=work_dir, issue=7, role="implementer")
    Path(scope["request_path"]).write_text(json.dumps([request(session_ids=["other"])]))
    gaps.collect_requests(scope=scope)
    assert not comments
    Path(scope["request_path"]).unlink()
    Path(scope["request_path"]).with_name("random.log").write_text(json.dumps([request()]))
    gaps.collect_requests(scope=scope)
    assert not comments


def test_mutated_copy_not_reused_as_original_evidence(configured):
    work_dir, _ = configured
    first = evidence.prepare(work_dir=work_dir, issue=7, role="architect")
    old = Path(first["request_path"]).parent / "s1/runs/r1/event-v2.tsv"
    old.chmod(0o600)
    old.write_text("fabricated")
    second = evidence.prepare(work_dir=work_dir, issue=7, role="acceptance")
    fresh = Path(second["request_path"]).parent / "s1/runs/r1/event-v2.tsv"
    assert fresh.read_text() == "work-token\tnew-request"
    assert old != fresh


def test_runtime_evidence_does_not_dirty_an_artifact_without_gitignore(configured):
    work_dir, _ = configured
    scope = evidence.prepare(work_dir=work_dir, issue=7, role="acceptance")
    assert scope["sessions"] == ["s1"]
    assert not (work_dir / ".gitignore").exists()
    status = subprocess.run(
        ["git", "-C", str(work_dir), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert status.stdout == ""


def test_download_is_issue_bound_and_cannot_follow_browser_links(monkeypatch):
    from openagents.utils import gitea

    gitea.configure(settings={"base_url": "http://trusted", "owner": "o", "repo": "r"})
    monkeypatch.setenv("GITEA_TOKEN", "test-only-token")
    uid = "12345678-1234-1234-1234-123456789012"
    metadata = json.dumps(
        [{"id": 1, "uuid": uid, "browser_download_url": "http://evil/private"}]
    ).encode()
    replies = iter([[metadata, b""], [b"package", b""]])
    urls = []

    class Response:
        def __init__(self, chunks):
            self.chunks = iter(chunks)

        def read1(self, size):
            return next(self.chunks)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(handler):
        assert handler.redirect_request(None, None, 302, "redirect", {}, "http://evil") is None

        def read(req, **kwargs):
            urls.append(req.full_url)
            return Response(next(replies))

        return SimpleNamespace(open=read)

    monkeypatch.setattr(gitea.urllib.request, "build_opener", opener)
    assert gitea.download_observation_asset(number=7, asset_id=1, limit=100) == b"package"
    assert urls == [
        "http://trusted/api/v1/repos/o/r/issues/7/assets",
        f"http://trusted/attachments/{uid}",
    ]
    replies = iter([[metadata, b""], [b"a"]])
    ticks = iter([0, 0, 0, 0, 16])
    monkeypatch.setattr(gitea, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    with pytest.raises(ValueError, match="budget"):
        gitea.download_observation_asset(number=7, asset_id=1, limit=100)


def test_outbox_restarts_without_waiting_for_a_new_agent(configured, monkeypatch):
    import threading

    work_dir, _ = configured
    gaps.outbox_root(work_dir=work_dir).joinpath("pending.json").write_text("{}")
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def replay(**kwargs):
        entered.set()
        release.wait(2)
        finished.set()

    monkeypatch.setattr(gaps, "retry_pending", replay)
    gaps.sweep_async(work_dir=work_dir)
    assert entered.wait(1)
    # The scheduling caller returned even though the retry has not finished.
    assert not finished.is_set()
    release.set()
    assert finished.wait(1)


def test_retry_identity_finds_later_comment_pages_and_rejects_other_authors(monkeypatch):
    from openagents.utils import gitea

    gitea.configure(settings={"base_url": "http://trusted", "owner": "o", "repo": "r"})
    identity = "observation-request-id: test"
    seen = []

    def request(**kwargs):
        if kwargs["path"] == "user":
            return SimpleNamespace(data={"login": "bot"})
        page = kwargs["query"]["page"]
        seen.append(page)
        if page == 1:
            return SimpleNamespace(
                data=[{"body": identity, "user": {"login": "someone-else"}}] * 50
            )
        return SimpleNamespace(data=[{"body": identity, "user": {"login": "bot"}}])

    monkeypatch.setattr(gitea, "_request", request)
    assert gitea.observation_request_exists(number=7, identity=identity)
    assert seen == [1, 2]
