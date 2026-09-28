#!/usr/bin/env python3
"""Stress real delivery scheduling with a local forge and scripted models.

Spec-0089/T1. All writes stay in a new temporary campaign directory. Production engine,
queue, workers, state and Git gates stay active; only external IO and explicit faults are simulated.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from contextlib import ExitStack, chdir
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

# The stress harness is also invoked directly by pytest via ``python script.py``.
# Keep that supported without requiring callers to preconfigure PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ruff: noqa: E402 - imports intentionally follow the direct-execution path bootstrap.
from openagents.backends.base import AgentResult
from openagents.recipes import vigil
from openagents.runtime.state import RuntimeState
from openagents.spec.render import render
from openagents.utils import agent_config, forge, gitea, github
from openagents.utils.github import PR, CheckSnapshot, Comment, Issue, PRSnapshot
from openagents.utils.workspace import Workspace, WorkspaceError

SCENARIOS = (
    "clean",
    "normal-build",
    "uncommitted",
    "commit-only",
    "pushed-lost-return",
    "timeout-before-commit",
    "timeout-after-commit",
    "timeout-after-push",
    "review-mutates",
    "remote-moves",
    "merge-race",
    "fetch-once",
    "cache",
    "untracked-log-once",
    "rework",
    "persistent-review-dirt",
    "persistent-fetch-failure",
)
NEGATIVE = {"persistent-review-dirt", "persistent-fetch-failure"}
ADVERSARIAL = ("remote-churn-3",)


def _now() -> datetime:
    """Read the real clock (Spec-0065)."""
    return datetime.now(UTC)


def local_git(
    *args: str, repo: Path, input_text: str | None = None, index: Path | None = None
) -> str:
    """Run only local campaign Git commands (Spec-0056)."""
    env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
    if index is not None:
        env["GIT_INDEX_FILE"] = str(index)
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
        env=env,
    ).stdout.strip()


@dataclass
class Job:
    """Hold external test facts, never replace runtime state (Spec-0065)."""

    number: int
    scenario: str
    worktree: Path
    branch: str
    filename: str
    inode: int = 0
    merged: bool = False
    closed: bool = False
    draft: bool = True
    labels: set[str] = field(default_factory=set)
    issue_labels: set[str] = field(default_factory=lambda: {"ready"})
    comments: list[Comment] = field(default_factory=list)
    issue_comments: list[Comment] = field(default_factory=list)
    calls: Counter = field(default_factory=Counter)
    injected: Counter = field(default_factory=Counter)
    claims: list[int] = field(default_factory=list)
    reviewed: list[str] = field(default_factory=list)
    approved: list[str] = field(default_factory=list)
    merged_sha: str = ""
    finished_at: float = 0.0
    preserved_sha: str = ""


class Campaign:
    """Drive the existing scheduler against one shared local repository (Spec-0065)."""

    name = "scripted-stress"

    def __init__(self, *, root: Path, scenarios: list[str], workers: int, seed: int) -> None:
        self.root = root
        self.checkout = root / "checkout"
        self.origin = root / "origin.git"
        self.workers = workers
        self.seed = seed
        self.jobs: dict[int, Job] = {}
        self.lock = threading.RLock()
        self.merge_lock = threading.Lock()
        self.active: set[int] = set()
        self.peak_active = 0
        self.duplicates = 0
        self.violations: list[str] = []
        self.errors: list[str] = []
        self.git_calls: Counter = Counter()
        self.started = 0.0
        self.state = RuntimeState(path=self.checkout / ".openagents" / "runtime-state.json")
        self.config = agent_config.default_config()
        self.logfile = (root / "scheduler.log").open("w", encoding="utf-8")
        self._setup(scenarios=scenarios)

    def _setup(self, *, scenarios: list[str]) -> None:
        """Create distinct issue files, branches and worktrees (Spec-0056)."""
        self.checkout.mkdir()
        local_git("init", "--bare", str(self.origin), repo=self.root)
        local_git("init", "--initial-branch=main", repo=self.checkout)
        for path in (self.checkout, self.origin):
            for key, value in (
                ("user.name", "Stress Test"),
                ("user.email", "stress@example.invalid"),
                ("commit.gpgsign", "false"),
                ("core.hooksPath", "/dev/null"),
            ):
                local_git("config", key, value, repo=path)
        (self.checkout / ".gitignore").write_text(".openagents/\n.pytest_cache/\n__pycache__/\n")
        specs = self.checkout / "docs" / "specs"
        specs.mkdir(parents=True)
        (specs / "OVERVIEW.md").write_text(render(specs_root=specs))
        (self.checkout / "features").mkdir()
        for number in range(1, len(scenarios) + 1):
            (self.checkout / "features" / f"issue-{number}.py").write_text("value = 0\n")
        local_git("add", ".", repo=self.checkout)
        local_git("commit", "-m", "test: seed independent feature tasks", repo=self.checkout)
        local_git("remote", "add", "origin", str(self.origin), repo=self.checkout)
        local_git("push", "-u", "origin", "main", repo=self.checkout)
        for number, scenario in enumerate(scenarios, 1):
            branch = f"openagents/issue-{number}"
            worktree = self.checkout / ".openagents" / "worktrees" / f"issue-{number}"
            local_git("worktree", "add", "-b", branch, str(worktree), "main", repo=self.checkout)
            job = Job(number, scenario, worktree, branch, f"features/issue-{number}.py")
            job.inode = worktree.stat().st_ino
            self.jobs[number] = job
            pending = scenario in {
                "normal-build",
                "uncommitted",
                "commit-only",
                "pushed-lost-return",
            } or scenario.startswith("timeout-")
            if scenario not in {"normal-build", "uncommitted"} and not scenario.startswith(
                "timeout-"
            ):
                (worktree / job.filename).write_text("value = 1\n")
                self._commit(job=job)
            # A commit-only residue publishes the base first, not the local implementation.
            remote_ref = "main" if scenario == "commit-only" else "HEAD"
            local_git("push", "origin", f"{remote_ref}:{branch}", repo=worktree)
            if scenario == "uncommitted":
                (worktree / job.filename).write_text("value = 0  # preserved partial work\n")
            job.preserved_sha = self._head(job=job)
            self.state.set_run(
                issue_number=number,
                status="iterating" if pending else "pr-open",
                branch=branch,
                pr_number=number + 10000,
            )
        print(
            json.dumps(
                {
                    "phase": "setup",
                    "workers": self.workers,
                    "jobs": len(self.jobs),
                    "root": str(self.root),
                }
            ),
            flush=True,
        )

    def _head(self, *, job: Job) -> str:
        """Read the actual candidate HEAD (Spec-0017)."""
        return local_git("rev-parse", "HEAD", repo=job.worktree)

    def _remote(self, *, job: Job) -> str:
        """Read the bare remote branch, never a model-reported SHA (Spec-0017)."""
        return local_git("rev-parse", f"refs/heads/{job.branch}", repo=self.origin)

    def _commit(self, *, job: Job) -> None:
        """Commit only genuine changes to this task's file (Spec-0056)."""
        local_git("add", job.filename, repo=job.worktree)
        if local_git("diff", "--cached", "--name-only", repo=job.worktree):
            local_git("commit", "-m", f"test: implement issue {job.number}", repo=job.worktree)

    def _publish(self, *, job: Job) -> None:
        """Push the existing issue branch without empty commits (Spec-0056)."""
        local_git("push", "origin", job.branch, repo=job.worktree)

    def _remote_change(self, *, job: Job) -> None:
        """Publish a real changed tree without touching the reader worktree (Spec-0017)."""
        old = self._remote(job=job)
        index = self.root / f"publisher-index-{job.number}"
        local_git("read-tree", old, repo=self.origin, index=index)
        blob = local_git(
            "hash-object",
            "-w",
            "--stdin",
            repo=self.origin,
            input_text="value = 1  # independently published revision\n",
        )
        local_git(
            "update-index",
            "--add",
            "--cacheinfo",
            "100644",
            blob,
            job.filename,
            repo=self.origin,
            index=index,
        )
        tree = local_git("write-tree", repo=self.origin, index=index)
        newer = local_git(
            "commit-tree", tree, "-p", old, "-m", "test: concurrent publication", repo=self.origin
        )
        local_git("update-ref", f"refs/heads/{job.branch}", newer, old, repo=self.origin)

    def log(self, *, message: str) -> None:
        """Persist scheduler output without suppressing failures (Spec-0065)."""
        with self.lock:
            self.logfile.write(message + "\n")
            self.logfile.flush()

    def get_issue(self, *, number: int) -> Issue:
        """Return isolated external issue facts (Spec-0065)."""
        with self.lock:
            job = self.jobs[number]
            return Issue(
                number,
                f"feature {number}",
                f"{job.filename} must define value = 1",
                tuple(job.issue_labels),
            )

    def pr_snapshot(self, *, pr_number: int) -> PRSnapshot:
        """Expose the real remote SHA and simulated forge metadata (Spec-0017)."""
        job = self.jobs[pr_number - 10000]
        sha = self._remote(job=job)
        with self.lock:
            return PRSnapshot(
                number=pr_number,
                state="MERGED" if job.merged else "OPEN",
                head_sha=sha,
                labels=tuple(job.labels),
                mergeable="MERGEABLE",
                merge_state_status="CLEAN",
                head_pushed_at="",
                is_draft=job.draft,
            )

    def check_snapshot(self, *, pr_number: int) -> CheckSnapshot:
        """Keep CI pending until the implementation is actually published (Spec-0065)."""
        job = self.jobs[pr_number - 10000]
        text = local_git("show", f"{job.branch}:{job.filename}", repo=self.origin)
        return CheckSnapshot("pass" if "value = 1" in text else "pending", 1, "")

    def add_label(self, *, pr_number: int, name: str) -> None:
        """Audit any approval against a clean candidate the reviewer saw (Spec-0017)."""
        job = self.jobs[pr_number - 10000]
        if name.startswith("review-approved:"):
            head = self._remote(job=job)
            if head not in job.reviewed or name != f"review-approved:{head[:7]}":
                self.violations.append(f"issue {job.number}: approval without exact review")
            if self._head(job=job) != head or local_git("status", "--porcelain", repo=job.worktree):
                self.violations.append(
                    f"issue {job.number}: approval of an unpublished/dirty worktree"
                )
            job.approved.append(head)
        with self.lock:
            job.labels.add(name)

    def _comment(self, *, number: int, body: str, issue: bool) -> None:
        """Keep signed comments visible to the real scheduler (Spec-0065)."""
        with self.lock:
            job = self.jobs[number if issue else number - 10000]
            target = job.issue_comments if issue else job.comments
            target.append(Comment(len(target) + 1, "stress-bot", body, _now().isoformat()))

    def run(self, *, work_dir: Path, task: str, context: str) -> AgentResult:
        """Execute deterministic roles through the real engine and timed backend (Spec-0065)."""
        number = int(Path(work_dir).name.removeprefix("issue-"))
        job = self.jobs[number]
        role = next(
            (
                name
                for marker, name in (
                    ("你是实现 agent", "implementer"),
                    ("你是交付 agent", "deliver"),
                    ("你是评审 agent", "reviewer"),
                    ("你是合并 agent", "merger"),
                    ("你是独立测试 agent", "tester"),
                )
                if marker in task
            ),
            "unknown",
        )
        with self.lock:
            job.calls[role] += 1
            call = job.calls[role]
        # Reproducible per-call jitter varies interleavings without changing production limits.
        time.sleep(random.Random(f"{self.seed}:{number}:{role}:{call}").uniform(0.001, 0.015))
        assert Path(work_dir) == job.worktree and job.worktree.stat().st_ino == job.inode
        if role == "implementer":
            if job.scenario == "uncommitted" and call == 1:
                assert "preserved partial work" in (job.worktree / job.filename).read_text()
            if job.scenario.startswith("timeout-") and call == 1:
                (job.worktree / job.filename).write_text("value = 1\n")
                if job.scenario != "timeout-before-commit":
                    self._commit(job=job)
                if job.scenario == "timeout-after-push":
                    self._publish(job=job)
                job.injected["timeout"] += 1
                raise vigil._ActTimeout(f"injected {job.scenario}; completed side effects retained")
            log = job.worktree / "debug.log"
            if log.exists():
                log.rename(self.root / f"preserved-debug-{number}-{call}.log")
            content = "value = 1\n"
            if job.scenario == "rework":
                content += "# review-fixed\n"
            (job.worktree / job.filename).write_text(content)
            out = {"summary": "finished original objective"}
        elif role == "deliver":
            before = self._head(job=job)
            self._commit(job=job)
            self._publish(job=job)
            out = {
                "delivered": True,
                "base_sha": before,
                "head_sha": self._head(job=job),
                "summary": "published",
            }
        elif role in {"tester", "reviewer"}:
            sha = self._head(job=job)
            assert not local_git("status", "--porcelain", repo=job.worktree)
            assert sha == self._remote(job=job)
            subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import runpy,sys; assert runpy.run_path(sys.argv[1])['value'] == 1",
                    str(job.worktree / job.filename),
                ],
                check=True,
                capture_output=True,
                timeout=10,
            )
            evidence_path = self.root / f"evidence-{number}-{role}-{call}.txt"
            evidence_path.write_text(f"PASS candidate={sha} value=1\n")
            if job.scenario == "cache":
                cache = job.worktree / ".pytest_cache"
                cache.mkdir(exist_ok=True)
                (cache / "result").write_text("normal ignored cache\n")
            verdict = "PASS"
            if role == "reviewer":
                job.reviewed.append(sha)
                if job.scenario == "rework" and call == 1:
                    verdict = "REWORK"
                if (
                    job.scenario == "review-mutates" and call == 1
                ) or job.scenario == "persistent-review-dirt":
                    (job.worktree / job.filename).write_text(
                        "value = 2  # invalid review-side edit\n"
                    )
                    job.injected["review-dirt"] += 1
                if job.scenario == "untracked-log-once" and call == 1:
                    (job.worktree / "debug.log").write_text("unignored diagnostic evidence\n")
                    job.injected["untracked-log"] += 1
                if (job.scenario == "remote-moves" and call == 1) or (
                    job.scenario == "remote-churn-3" and call <= 3
                ):
                    self._remote_change(job=job)
                    job.injected["remote-change"] += 1
            out = {
                "verdict": verdict,
                "reason": "add review-fixed comment" if verdict == "REWORK" else "verified value=1",
            }
            if role == "tester":
                out["evidence"] = [
                    {
                        "case_id": f"feature-{number}",
                        "kind": "behavior",
                        "observed": "value=1",
                        "expected": "value=1",
                        "path": str(evidence_path),
                        "passed": True,
                    }
                ]
        elif role == "merger":
            expected = re.search(r"--match-head-commit ([a-f0-9]{40})", task)
            assert expected is not None, "native merge is missing its approved SHA"
            with self.merge_lock:
                if job.scenario == "merge-race" and call == 1:
                    self._remote_change(job=job)
                    job.injected["merge-race"] += 1
                head = self._remote(job=job)
                if expected[1] != head:
                    out = {
                        "merged": False,
                        "summary": "native compare-and-merge rejected changed head",
                    }
                else:
                    assert head in job.approved and head in job.reviewed
                    local_git("merge", "--no-ff", "--no-edit", head, repo=self.checkout)
                    local_git("push", "origin", "main", repo=self.checkout)
                    with self.lock:
                        job.merged = True
                        job.merged_sha = head
                    out = {"merged": True, "summary": "merged exact approved candidate"}
        else:
            raise AssertionError(f"unexpected model role: {role}")
        return AgentResult(changed=role in {"implementer", "deliver"}, summary=json.dumps(out))

    def execute(self, *, deadline_seconds: float) -> dict:
        """Run actual workers, producer consideration and recovery until terminal (Spec-0065)."""
        db = self.checkout / ".openagents" / vigil._QUEUE_DB_FILENAME
        vigil._init_db(db_path=db)
        original_git = Workspace._git
        original_claimed = vigil._run_claimed

        def git_io(workspace, *, args, cwd, check):
            with self.lock:
                self.git_calls[args[0]] += 1
            job = next((j for j in self.jobs.values() if j.worktree == Path(cwd)), None)
            if job and args[0] == "fetch":
                with self.lock:
                    inject = job.scenario == "persistent-fetch-failure" or (
                        job.scenario == "fetch-once" and not job.injected["fetch"]
                    )
                    if inject:
                        job.injected["fetch"] += 1
                if inject:
                    raise WorkspaceError("injected fetch transport failure; no source changes")
            return original_git(workspace, args=args, cwd=cwd, check=check)

        def claimed(**kw):
            number = int(kw["row"]["subject"].split(":")[1])
            with self.lock:
                self.duplicates += number in self.active
                self.active.add(number)
                self.peak_active = max(self.peak_active, len(self.active))
                self.jobs[number].claims.append(kw["row"]["attempts"])
            try:
                return original_claimed(**kw)
            finally:
                with self.lock:
                    self.active.discard(number)

        patches = {
            "get_issue": self.get_issue,
            "pr_snapshot": self.pr_snapshot,
            "check_snapshot": self.check_snapshot,
            "active_forge": lambda: "github",
            "list_blocked_by": lambda **kw: [],
            "pr_for_branch": lambda *, branch: PR(
                int(branch.rsplit("-", 1)[1]) + 10000, "https://example.invalid/pr"
            ),
            "pr_head_branch": lambda *, pr_number: self.jobs[pr_number - 10000].branch,
            "list_comments": lambda *, pr_number: list(self.jobs[pr_number - 10000].comments),
            "list_issue_comments": lambda *, number: list(self.jobs[number].issue_comments),
            "ensure_label": lambda **kw: None,
            "add_label": self.add_label,
            "remove_label": lambda *, pr_number, name: self.jobs[pr_number - 10000].labels.discard(
                name
            ),
            "issue_add_label": lambda *, number, name: self.jobs[number].issue_labels.add(name),
            "issue_remove_label": lambda *, number, name: self.jobs[number].issue_labels.discard(
                name
            ),
            "post_comment": lambda *, pr_number, body: self._comment(
                number=pr_number, body=body, issue=False
            ),
            "issue_comment": lambda *, number, body: self._comment(
                number=number, body=body, issue=True
            ),
            "mark_ready": lambda *, pr_number: setattr(
                self.jobs[pr_number - 10000], "draft", False
            ),
            "close_issue": lambda *, number: setattr(self.jobs[number], "closed", True),
        }
        stop = threading.Event()
        threads = []
        self.started = time.monotonic()
        with ExitStack() as stack, chdir(self.checkout):
            for name, callback in patches.items():
                stack.enter_context(patch.object(forge, name, callback, create=True))
            stack.enter_context(
                patch.object(
                    github, "_run_gh", side_effect=AssertionError("external gh IO forbidden")
                )
            )
            stack.enter_context(
                patch.object(
                    gitea, "_http", side_effect=AssertionError("external HTTP IO forbidden")
                )
            )
            stack.enter_context(patch.object(Workspace, "_git", git_io))
            stack.enter_context(patch.object(vigil, "_run_claimed", claimed))
            stack.enter_context(patch.object(vigil, "_log", self.log))
            conn = vigil._connect(db_path=db)
            order = list(self.jobs)
            random.Random(self.seed).shuffle(order)
            try:
                # Fill through the real producer before launching workers: otherwise a fast
                # local job can drain the queue while other workers are in their 1s idle poll.
                for number in order:
                    vigil._consider(
                        conn=conn,
                        state=self.state,
                        subject=f"issue:{number}",
                        config=self.config,
                        work_dir=self.checkout,
                        in_flight={},
                        priority_fn=lambda **kw: 0,
                        thresholds=vigil._WATCHDOG_DEFAULTS,
                        quiet_counts={},
                        now=_now(),
                        agent_id="stress-bot",
                    )
                for worker in range(self.workers):
                    thread = threading.Thread(
                        target=vigil._worker_loop,
                        kwargs=dict(
                            db_path=db,
                            backend=self,
                            state=self.state,
                            work_dir=self.checkout,
                            config=self.config,
                            agent_id="stress-bot",
                            now_fn=_now,
                            stop_event=stop,
                            worker_id=f"stress-{worker}",
                        ),
                        daemon=True,
                    )
                    thread.start()
                    threads.append(thread)
                last_print = self.started
                while time.monotonic() - self.started < deadline_seconds:
                    vigil._reclaim_dead(conn=conn, work_dir=self.checkout)
                    in_flight = {
                        row["subject"]: row["claimed_at"]
                        for row in conn.execute(
                            "SELECT subject, claimed_at FROM work_queue WHERE status='claimed'"
                        )
                    }
                    terminal = 0
                    for number in order:
                        job = self.jobs[number]
                        if "automation-failed" in job.issue_labels:
                            # Let production failure revival examine the final stable facts;
                            # a failure label alone is not proof the next tick stays blocked.
                            vigil._refresh_failure_projection(
                                observed=vigil._sense(
                                    config=self.config, subject=f"issue:{number}"
                                ),
                                subject=f"issue:{number}",
                            )
                            self.log(
                                message=f"terminal recheck issue {number}: failed={'automation-failed' in job.issue_labels}"
                            )
                        if job.closed or "automation-failed" in job.issue_labels:
                            if not job.finished_at:
                                job.finished_at = time.monotonic() - self.started
                            terminal += 1
                            continue
                        try:
                            vigil._consider(
                                conn=conn,
                                state=self.state,
                                subject=f"issue:{number}",
                                config=self.config,
                                work_dir=self.checkout,
                                in_flight=in_flight,
                                priority_fn=lambda **kw: 0,
                                thresholds=vigil._WATCHDOG_DEFAULTS,
                                quiet_counts={},
                                now=_now(),
                                agent_id="stress-bot",
                            )
                        except Exception as exc:
                            self.errors.append(
                                f"producer issue {number}: {type(exc).__name__}: {exc}"
                            )
                    if (
                        terminal == len(self.jobs)
                        and not conn.execute("SELECT 1 FROM work_queue LIMIT 1").fetchone()
                    ):
                        break
                    if time.monotonic() - last_print > 5:
                        print(
                            json.dumps(
                                {
                                    "phase": "running",
                                    "workers": self.workers,
                                    "terminal": terminal,
                                    "total": len(self.jobs),
                                    "elapsed_s": round(time.monotonic() - self.started, 1),
                                }
                            ),
                            flush=True,
                        )
                        last_print = time.monotonic()
                    stop.wait(0.05)
            finally:
                stop.set()
                for thread in threads:
                    thread.join(timeout=40)
                if any(thread.is_alive() for thread in threads):
                    self.violations.append("worker survived campaign shutdown")
                queue = [dict(row) for row in conn.execute("SELECT * FROM work_queue")]
                conn.close()
        self.logfile.close()
        return self.report(queue=queue, elapsed=time.monotonic() - self.started)

    def report(self, *, queue: list[dict], elapsed: float) -> dict:
        """Verify final content and report failures without forgiving them (Spec-0017)."""
        rows = []
        for job in self.jobs.values():
            final = local_git("show", f"main:{job.filename}", repo=self.origin)
            run = self.state.get_run(issue_number=job.number) or {}
            failed = "automation-failed" in job.issue_labels
            good = (
                job.merged and job.closed and "value = 1" in final and run.get("status") == "done"
            )
            if job.merged and (
                job.merged_sha not in job.approved
                or job.merged_sha not in job.reviewed
                or "value = 1" not in final
            ):
                self.violations.append(f"issue {job.number}: incorrect final merge")
            if (
                job.scenario in {"commit-only", "pushed-lost-return", "clean", "cache"}
                and job.merged
                and job.merged_sha != job.preserved_sha
            ):
                self.violations.append(f"issue {job.number}: unnecessary extra commit")
            expected = (
                (failed and not job.merged and len(job.claims) <= vigil._MAX_ATTEMPTS)
                if job.scenario in NEGATIVE
                else good
            )
            rows.append(
                {
                    "issue": job.number,
                    "scenario": job.scenario,
                    "expected_outcome": expected,
                    "merged": job.merged,
                    "failed": failed,
                    "state": run.get("status"),
                    "final": final,
                    "seconds": round(job.finished_at, 3),
                    "calls": dict(job.calls),
                    "claims": job.claims,
                    "injected": dict(job.injected),
                    "reviewed": job.reviewed,
                    "approved": job.approved,
                    "merged_sha": job.merged_sha,
                }
            )
        durations = sorted(row["seconds"] for row in rows if row["merged"])
        unexpected = [row for row in rows if not row["expected_outcome"]]
        totals = Counter()
        for job in self.jobs.values():
            totals.update(job.calls)
        result = {
            "workers": self.workers,
            "seed": self.seed,
            "jobs": len(rows),
            "elapsed_s": round(elapsed, 3),
            "merged": sum(row["merged"] for row in rows),
            "expected_failures": sum(row["failed"] and row["scenario"] in NEGATIVE for row in rows),
            "unexpected_outcomes": len(unexpected),
            "duplicates": self.duplicates,
            "peak_active": self.peak_active,
            "violations": self.violations,
            "producer_errors": self.errors,
            "queue_residue": queue,
            "role_calls": dict(totals),
            "git_calls": dict(self.git_calls),
            "p50_s": durations[len(durations) // 2] if durations else None,
            "p95_s": durations[min(len(durations) - 1, int(len(durations) * 0.95))]
            if durations
            else None,
            "rows": rows,
            "root": str(self.root),
        }
        result["passed"] = not (
            unexpected or self.violations or self.errors or self.duplicates or queue
        )
        (self.root / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        )
        print(
            json.dumps(
                {key: value for key, value in result.items() if key != "rows"}, ensure_ascii=False
            ),
            flush=True,
        )
        return result


def main() -> int:
    """Run repeatable baseline and mixed-fault campaigns (Spec-0065)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 4, 8, 16])
    parser.add_argument("--repeats", type=int, default=4, help="repetitions per mixed scenario")
    parser.add_argument(
        "--baseline", type=int, default=16, help="clean controls per concurrency level"
    )
    parser.add_argument("--seed", type=int, default=59)
    parser.add_argument(
        "--scenarios", nargs="+", choices=(*SCENARIOS, *ADVERSARIAL), default=list(SCENARIOS)
    )
    parser.add_argument("--deadline", type=float, default=300)
    parser.add_argument("--output-parent", type=Path, default=Path(tempfile.gettempdir()))
    args = parser.parse_args()
    if min(args.workers) < 1 or args.repeats < 1 or args.baseline < 0 or args.deadline <= 0:
        parser.error("workers/repeats/deadline must be positive; baseline must be nonnegative")
    root = Path(tempfile.mkdtemp(prefix="delivery-stress-", dir=args.output_parent))
    results = []
    for workers in args.workers:
        for kind, scenarios in (
            ("baseline", ["clean"] * args.baseline),
            ("mixed", args.scenarios * args.repeats),
        ):
            if not scenarios:
                continue
            campaign_root = root / f"{kind}-w{workers}"
            campaign_root.mkdir()
            result = Campaign(
                root=campaign_root, scenarios=scenarios, workers=workers, seed=args.seed
            ).execute(deadline_seconds=args.deadline)
            results.append(result)
            (root / "summary.json").write_text(
                json.dumps(results, ensure_ascii=False, indent=2) + "\n"
            )
    print(
        json.dumps(
            {
                "report": str(root / "summary.json"),
                "passed": all(result["passed"] for result in results),
            }
        ),
        flush=True,
    )
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
