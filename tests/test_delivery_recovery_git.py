"""Spec-0089/T1: real local Git proves recovery reaches the exact reviewed artifact.

Only model and forge IO are simulated. Workspace, Git gates, runtime checkpoints, sensing,
classification and reconcile remain real. No network, deployment or user repository writes.
"""

import subprocess
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from openagents.recipes import stages, vigil
from openagents.runtime import engine, gates
from openagents.runtime.state import RuntimeState
from openagents.spec.render import render
from openagents.utils import agent_config, forge
from openagents.utils.github import PR, CheckSnapshot, Issue, PRSnapshot
from openagents.utils.workspace import Workspace, WorkspaceError

_BRANCH = "openagents/issue-5"


def _git(*args: str, repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@dataclass
class LocalRepo:
    """Local-only delivery branch and independent publisher (Spec-0056)."""

    root: Path
    worktree: Path
    origin: Path
    publisher: Path
    initial: str

    def head(self) -> str:
        return _git("rev-parse", "HEAD", repo=self.worktree)

    def remote(self) -> str:
        return _git("rev-parse", f"refs/heads/{_BRANCH}", repo=self.origin)

    def commit(self, *, path: Path, name: str, content: str) -> str:
        (path / name).write_text(content, encoding="utf-8")
        _git("add", name, repo=path)
        _git("commit", "-m", f"test: update {name}", repo=path)
        return _git("rev-parse", "HEAD", repo=path)


@pytest.fixture
def local_repo(tmp_path):
    origin = tmp_path / "origin.git"
    root = tmp_path / "checkout"
    publisher = tmp_path / "publisher"
    root.mkdir()
    _git("init", "--bare", str(origin), repo=tmp_path)
    _git("init", "--initial-branch=main", repo=root)
    for key, value in (
        ("user.name", "Recovery Test"),
        ("user.email", "recovery@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.hooksPath", "/dev/null"),
    ):
        _git("config", key, value, repo=root)
    (root / ".gitignore").write_text(".openagents/\n.pytest_cache/\n__pycache__/\n")
    (root / "entry.py").write_text("value = 0\n")
    specs = root / "docs" / "specs"
    specs.mkdir(parents=True)
    (specs / "OVERVIEW.md").write_text(render(specs_root=specs))
    _git("add", ".", repo=root)
    _git("commit", "-m", "test: seed candidate", repo=root)
    _git("remote", "add", "origin", str(origin), repo=root)
    _git("push", "-u", "origin", "main", repo=root)
    worktree = root / ".openagents" / "worktrees" / "issue-5"
    _git("worktree", "add", "-b", _BRANCH, str(worktree), "main", repo=root)
    _git("push", "-u", "origin", _BRANCH, repo=worktree)
    _git("worktree", "add", "-b", "independent-publisher", str(publisher), "main", repo=root)
    return LocalRepo(root, worktree, origin, publisher, _git("rev-parse", "HEAD", repo=worktree))


@pytest.mark.parametrize("residue", ["modified", "staged", "untracked", "ignored"])
def test_real_git_worktree_gate_preserves_source_and_allows_cache(local_repo, residue):
    repo = local_repo
    name = "entry.py" if residue in {"modified", "staged"} else "new_feature.py"
    if residue == "ignored":
        name = ".pytest_cache/report.txt"
        (repo.worktree / ".pytest_cache").mkdir()
    path = repo.worktree / name
    path.write_text("unfinished work\n")
    if residue == "staged":
        _git("add", name, repo=repo.worktree)
    workspace = Workspace(work_dir=repo.root)
    assert workspace.ensure(issue_number=5, branch=_BRANCH) == repo.worktree
    if residue == "ignored":
        workspace.assert_delivered(worktree=repo.worktree, branch=_BRANCH)
        assert workspace.sync_delivered(worktree=repo.worktree, branch=_BRANCH)
    else:
        with pytest.raises(WorkspaceError, match="未提交"):
            workspace.assert_delivered(worktree=repo.worktree, branch=_BRANCH)
        assert not workspace.sync_delivered(worktree=repo.worktree, branch=_BRANCH)
    assert path.read_text() == "unfinished work\n"
    assert repo.head() == repo.initial


@pytest.mark.parametrize("relation", ["behind", "ahead", "diverged"])
def test_real_git_sync_only_fast_forwards_without_discarding_commits(local_repo, relation):
    repo = local_repo
    if relation in {"ahead", "diverged"}:
        repo.commit(path=repo.worktree, name="local.py", content="local work\n")
    original = repo.head()
    if relation in {"behind", "diverged"}:
        repo.commit(path=repo.publisher, name="remote.py", content="remote work\n")
        _git("push", "origin", f"HEAD:{_BRANCH}", repo=repo.publisher)
    ready = Workspace(work_dir=repo.root).sync_delivered(worktree=repo.worktree, branch=_BRANCH)
    assert ready == (relation == "behind")
    if ready:
        assert repo.head() == repo.remote()
        assert (repo.worktree / "remote.py").read_text() == "remote work\n"
    else:
        assert repo.head() == original
        assert (repo.worktree / "local.py").read_text() == "local work\n"


@pytest.mark.parametrize("operation", ["assert_delivered", "sync_delivered", "delivery_heads"])
def test_real_git_fetch_failure_cannot_use_stale_matching_ref(local_repo, operation):
    repo = local_repo
    _git("remote", "set-url", "origin", str(repo.root / "missing-remote.git"), repo=repo.root)
    workspace = Workspace(work_dir=repo.root)
    with pytest.raises(WorkspaceError, match="fetch"):
        getattr(workspace, operation)(worktree=repo.worktree, branch=_BRANCH)
    assert repo.head() == repo.initial


@pytest.fixture
def candidate_facts(local_repo, monkeypatch):
    """Spec-0017: real Git candidate with only the external forge read substituted."""

    def snapshot(*, pr_number):
        return PRSnapshot(
            number=pr_number,
            state="OPEN",
            head_sha=local_repo.remote(),
            labels=(),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            head_pushed_at="",
            is_draft=False,
        )

    monkeypatch.setattr(forge, "pr_snapshot", snapshot)
    return vigil._Facts(
        subject="issue:5",
        pr_number=12,
        head_sha=local_repo.initial,
        merged=False,
        closed=False,
        labels=frozenset(),
        deps_done=True,
        mergeable_state="clean",
        ci="none",
        e2e_head_sha=None,
        review_state=None,
        review_commit_id=None,
        latest_comment_is_ours=True,
    )


@pytest.mark.parametrize("when", ["before", "during-fetch", "after-git-read", "both-published"])
def test_real_git_candidate_change_requires_new_review_not_execution_retry(
    local_repo, candidate_facts, monkeypatch, when
):
    """Spec-0017: version changes at each IO boundary invalidate the old verdict."""
    repo = local_repo
    workspace = Workspace(work_dir=repo.root)
    vigil._verify_candidate(worktree=repo.worktree, facts=candidate_facts)

    def publish():
        repo.commit(path=repo.publisher, name="remote.py", content="valid new feature\n")
        _git("push", "origin", f"HEAD:{_BRANCH}", repo=repo.publisher)

    if when in {"before", "both-published"}:
        publish()
        if when == "both-published":
            assert workspace.sync_delivered(worktree=repo.worktree, branch=_BRANCH)
    elif when == "during-fetch":
        original = Workspace._git
        published = False

        def git_io(self, *, args, cwd, check):
            nonlocal published
            if args[0] == "fetch" and not published:
                publish()
                published = True
            return original(self, args=args, cwd=cwd, check=check)

        monkeypatch.setattr(Workspace, "_git", git_io)
    else:
        original_snapshot = forge.pr_snapshot

        def late_snapshot(*, pr_number):
            publish()
            return original_snapshot(pr_number=pr_number)

        monkeypatch.setattr(forge, "pr_snapshot", late_snapshot)
    preserved = repo.head()
    with pytest.raises(gates.MergeNotReady, match="候选版本已变化"):
        vigil._verify_candidate(worktree=repo.worktree, facts=candidate_facts)
    assert repo.head() == preserved  # Verification never changes reviewed files.
    assert _git("status", "--porcelain", repo=repo.worktree) == ""
    # The developer's delivery gate remains strict for this same local/remote mismatch.
    if when != "both-published":
        with pytest.raises(WorkspaceError):
            workspace.assert_delivered(worktree=repo.worktree, branch=_BRANCH)


@pytest.mark.parametrize("when", ["before", "during-fetch"])
def test_real_git_candidate_dirt_is_not_disguised_as_remote_churn(
    local_repo, candidate_facts, monkeypatch, when
):
    """Spec-0056: source dirt, including dirt created during IO, stays an execution error."""
    repo = local_repo
    path = repo.worktree / "entry.py"
    if when == "before":
        path.write_text("value = 2\n")
    else:
        original = Workspace._git

        def git_io(self, *, args, cwd, check):
            result = original(self, args=args, cwd=cwd, check=check)
            if args[0] == "fetch":
                path.write_text("value = 2\n")
            return result

        monkeypatch.setattr(Workspace, "_git", git_io)
    with pytest.raises(WorkspaceError, match="未提交"):
        vigil._verify_candidate(worktree=repo.worktree, facts=candidate_facts)
    assert path.read_text() == "value = 2\n"


@pytest.mark.parametrize("remote_moves", [False, True])
def test_real_git_unpublished_reader_commit_is_still_an_execution_error(
    local_repo, candidate_facts, remote_moves
):
    """Spec-0056: an unpushed reviewer commit must not gain unlimited churn retries."""
    repo = local_repo
    new_local = repo.commit(path=repo.worktree, name="local.py", content="unpublished\n")
    if remote_moves:
        repo.commit(path=repo.publisher, name="remote.py", content="published\n")
        _git("push", "origin", f"HEAD:{_BRANCH}", repo=repo.publisher)
    with pytest.raises(WorkspaceError, match="未推送"):
        vigil._verify_candidate(worktree=repo.worktree, facts=candidate_facts)
    assert repo.head() == new_local


@pytest.mark.parametrize(
    "failure", ["status", "fetch", "rev-parse", "empty-head", "forge", "empty-forge"]
)
def test_candidate_read_failures_cannot_be_classified_as_remote_churn(
    local_repo, candidate_facts, monkeypatch, failure
):
    """Spec-0017/0056: every failed or empty read keeps the bounded execution path."""
    original = Workspace._git

    def git_io(self, *, args, cwd, check):
        if args[0] == failure:
            raise WorkspaceError("injected Git read failure")
        if failure == "empty-head" and args == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        return original(self, args=args, cwd=cwd, check=check)

    monkeypatch.setattr(Workspace, "_git", git_io)
    original_snapshot = forge.pr_snapshot

    def snapshot(*, pr_number):
        if failure == "forge":
            raise forge.GithubError("injected forge read failure")
        result = original_snapshot(pr_number=pr_number)
        return replace(result, head_sha="") if failure == "empty-forge" else result

    monkeypatch.setattr(forge, "pr_snapshot", snapshot)
    expected = forge.GithubError if failure == "forge" else WorkspaceError
    with pytest.raises(expected):
        vigil._verify_candidate(worktree=local_repo.worktree, facts=candidate_facts)


@pytest.mark.parametrize("residue", ["spec-only", "uncommitted", "commit-only", "pushed"])
def test_real_git_interrupted_run_reconciles_through_review_to_merge(
    local_repo, monkeypatch, residue
):
    repo = local_repo
    if residue == "uncommitted":
        (repo.worktree / "entry.py").write_text("value = 0  # partial implementation\n")
    elif residue in {"commit-only", "pushed"}:
        repo.commit(path=repo.worktree, name="entry.py", content="value = 1\n")
        if residue == "pushed":
            _git("push", "origin", _BRANCH, repo=repo.worktree)
    preserved_head = repo.head()
    preserved_inode = repo.worktree.stat().st_ino
    state = RuntimeState(path=repo.root / ".openagents" / "runtime-state.json")
    state.set_run(issue_number=5, status="iterating", branch=_BRANCH, pr_number=12)
    config = replace(
        agent_config.default_config(),
        stages=agent_config.StagePolicy(owners={"e2e": "skip"}),
    )
    remote_state = {"merged": False, "closed": False, "draft": True}
    labels = set()
    calls = []
    reviewed = []

    def snapshot(*, pr_number):
        assert pr_number == 12
        return PRSnapshot(
            number=12,
            state="MERGED" if remote_state["merged"] else "OPEN",
            head_sha=repo.remote(),
            labels=tuple(labels),
            mergeable="MERGEABLE",
            merge_state_status="CLEAN",
            head_pushed_at="",
            is_draft=remote_state["draft"],
        )

    def run_agent(module, *, backend, **kw):
        name = module.__name__.rsplit(".", 1)[-1]
        calls.append(name)
        assert Path(kw["work_dir"]) == repo.worktree
        assert repo.worktree.stat().st_ino == preserved_inode
        if name == "implementer":
            assert "原任务" in kw["context"] or "original issue" in kw["context"]
            if residue == "uncommitted":
                assert "partial implementation" in (repo.worktree / "entry.py").read_text()
            (repo.worktree / "entry.py").write_text("value = 1\n")
            return {"summary": "finished original task"}
        if name == "deliver":
            before = repo.head()
            if _git("status", "--porcelain", repo=repo.worktree):
                _git("add", "entry.py", repo=repo.worktree)
                _git("commit", "-m", "test: finish feature", repo=repo.worktree)
            _git("push", "origin", _BRANCH, repo=repo.worktree)
            return {
                "delivered": True,
                "base_sha": before,
                "head_sha": repo.head(),
                "summary": "pushed",
            }
        if name == "reviewer":
            assert (repo.worktree / "entry.py").read_text() == "value = 1\n"
            assert not _git("status", "--porcelain", repo=repo.worktree)
            assert repo.head() == repo.remote()
            reviewed.append(repo.head())
            # A normal reader cache must not force another implementation/review cycle.
            cache = repo.worktree / ".pytest_cache"
            cache.mkdir(exist_ok=True)
            (cache / "result.txt").write_text("PASS\n")
            return {"verdict": "PASS", "reason": "original feature delivered"}
        if name == "merger":
            assert reviewed == [repo.remote()]
            assert f"--match-head-commit {repo.remote()}" in kw["merge_command"]
            assert f"review-approved:{repo.remote()[:7]}" in labels
            _git("update-ref", "refs/heads/main", repo.remote(), repo=repo.origin)
            remote_state["merged"] = True
            return {"merged": True, "summary": "merged exact candidate"}
        pytest.fail(f"unexpected role: {name}")

    # Patch only external forge and model IO; internal state and all Git gates stay real.
    monkeypatch.chdir(repo.root)
    monkeypatch.setattr(engine, "run_agent", run_agent)
    monkeypatch.setattr(
        forge, "get_issue", lambda **kw: Issue(5, "finish feature", "value must equal 1", ["ready"])
    )
    monkeypatch.setattr(forge, "list_blocked_by", lambda **kw: [])
    monkeypatch.setattr(
        forge, "pr_for_branch", lambda **kw: PR(12, "https://example.invalid/pr/12")
    )
    monkeypatch.setattr(forge, "pr_snapshot", snapshot)
    monkeypatch.setattr(forge, "check_snapshot", lambda **kw: CheckSnapshot("pass", 1, ""))
    monkeypatch.setattr(forge, "list_comments", lambda **kw: [])
    monkeypatch.setattr(forge, "ensure_label", lambda **kw: None)
    monkeypatch.setattr(forge, "add_label", lambda *, pr_number, name: labels.add(name))
    monkeypatch.setattr(forge, "remove_label", lambda *, pr_number, name: labels.discard(name))
    monkeypatch.setattr(forge, "mark_ready", lambda **kw: remote_state.update(draft=False))
    monkeypatch.setattr(forge, "close_issue", lambda **kw: remote_state.update(closed=True))

    vigil._reconcile(
        backend=object(),
        state=state,
        work_dir=repo.root,
        config=config,
        subject="issue:5",
        agent_id="test-recovery",
        now_fn=lambda: datetime.now(UTC),
        lock_fd=None,
    )

    assert remote_state == {"merged": True, "closed": True, "draft": False}
    assert state.get_run(issue_number=5)["status"] == "done"
    assert calls == [
        "implementer",
        *([] if residue == "pushed" else ["deliver"]),
        "reviewer",
        "merger",
    ]
    assert reviewed == [repo.head()] == [repo.remote()]
    assert _git("show", "main:entry.py", repo=repo.origin) == "value = 1"
    if residue in {"commit-only", "pushed"}:
        assert repo.head() == preserved_head  # No empty commit required for recovery.


@pytest.mark.parametrize("flow", [agent_config.FLOW_MINIMAL, agent_config.FLOW_GENERATE_ONLY])
@pytest.mark.parametrize("residue", ["uncommitted", "commit-only", "pushed"])
def test_compact_flow_resumes_same_objective_without_requiring_empty_commit(
    local_repo, monkeypatch, flow, residue
):
    """Spec-0082/0056: recovery retains the compact contract and actual delivery gates."""
    repo = local_repo
    objective = repo.worktree / "docs" / "objectives" / "issue-5.md"
    objective.parent.mkdir()
    compact = "\n".join(
        f"## {heading}\nvalue must equal 1\n"
        for heading in (
            "Objective contract",
            "Observed mechanism and evidence",
            "Decision rationale",
            "Invariants and risk ledger",
            "Developer design envelope",
            "Independent acceptance",
        )
    )
    repo.commit(path=repo.worktree, name="docs/objectives/issue-5.md", content=compact)
    _git("push", "origin", _BRANCH, repo=repo.worktree)
    (repo.worktree / "entry.py").write_text("value = 1\n")
    if residue != "uncommitted":
        _git("add", "entry.py", repo=repo.worktree)
        _git("commit", "-m", "test: completed implementation", repo=repo.worktree)
        if residue == "pushed":
            _git("push", "origin", _BRANCH, repo=repo.worktree)
    before = repo.head()
    state = RuntimeState(path=repo.root / ".openagents" / "runtime-state.json")
    state.set_run(issue_number=5, status="iterating", branch=_BRANCH, pr_number=12)
    facts = vigil._Facts(
        subject="issue:5",
        pr_number=12,
        head_sha=repo.remote(),
        merged=False,
        closed=False,
        labels=frozenset(),
        deps_done=True,
        mergeable_state="clean",
        ci="pending",
        e2e_head_sha=None,
        review_state=None,
        review_commit_id=None,
        latest_comment_is_ours=True,
    )
    calls = []

    def run_agent(module, *, backend, **kw):
        name = module.__name__.rsplit(".", 1)[-1]
        calls.append(name)
        if name in {"implementer", "executor"}:
            assert compact in kw["context"]
            assert vigil._MINIMAL_FLOW_CONTRACT in kw["context"]
        if name in {"executor", "deliver"}:
            if _git("status", "--porcelain", repo=repo.worktree):
                _git("add", "entry.py", repo=repo.worktree)
                _git("commit", "-m", "test: finish delivery", repo=repo.worktree)
            _git("push", "origin", _BRANCH, repo=repo.worktree)
        return {"summary": "completed", "head_sha": repo.head(), "delivered": True}

    monkeypatch.chdir(repo.root)
    monkeypatch.setattr(engine, "run_agent", run_agent)
    monkeypatch.setattr(forge, "get_issue", lambda **kw: Issue(5, "feature", "value must equal 1"))
    monkeypatch.setattr(forge, "list_comments", lambda **kw: [])
    vigil._do_solve(
        backend=object(),
        state=state,
        work_dir=repo.root,
        config=replace(agent_config.default_config(), flow=flow),
        facts=facts,
        agent_id="test",
    )
    assert state.get_run(issue_number=5)["status"] == "pr-open"
    Workspace(work_dir=repo.root).assert_delivered(worktree=repo.worktree, branch=_BRANCH)
    if residue != "uncommitted":
        assert repo.head() == before
    expected = ["executor"] if flow == agent_config.FLOW_GENERATE_ONLY else ["implementer"]
    if flow == agent_config.FLOW_MINIMAL and residue != "pushed":
        expected.append("deliver")
    assert calls == expected


def test_executor_cannot_use_resume_to_pass_without_pushing(local_repo, monkeypatch):
    """Spec-0056: unchanged HEAD on a retry is allowed only after real publication."""
    repo = local_repo
    repo.commit(path=repo.worktree, name="entry.py", content="value = 1\n")
    monkeypatch.setattr(engine, "run_agent", lambda *a, **kw: {"head_sha": repo.head()})
    with pytest.raises(WorkspaceError, match="未交付"):
        stages.execute_compact_spec(
            backend=object(),
            work_dir=repo.worktree,
            issue_number=5,
            pr_number=12,
            context_text="resume",
            resume_branch=_BRANCH,
        )
