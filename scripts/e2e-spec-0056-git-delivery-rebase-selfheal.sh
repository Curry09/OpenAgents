#!/usr/bin/env bash
# Spec-0056/T3 End-to-end test start script: Git delivery/ conflict decentralization agent (rebase self-healing)+ Harness head before moving the hard gate.
#
# Demonstration: Devolve "real push-up of results" to agent (committee  →  setch before BASE  → )
#  → base --force-with-lease =<branch>: $BASE), only one dead code hard gate is left in the record
# assert_delivered (origin/<branch>= local HEAD is released, which does not mean that it is required-human to transfer the person).
#
# Two paragraphs:
#   1) Offline certainty (default execution) - ruff lint/format + pytest package, full mock, untouched real
#      gh/claude (covering T1 hardlock/decision 7, T2 delivery agreement contract lock + hardlock route + quarantine repair).
#   2) Offline Results Exercise (Default) - Construct a recovery state with **real local ** ** (Nud Library as Far + Worktree)
#      "Faceward PPR Branch Lead Base + Local Redrafting of the same file leads to a fork" to actually implement the delivery protocol** as git
#      The fake backend driver orchestrator.implement of command** asserts:
#        (a) Rebase self-healing + force-with-lease push, origin/<branch> forward to local HEAD (results reach PR head);
#        (b) Inverse example - make backend "presuming to finish but not push" assert_delivered judgement not delivered. PR #141 review must be corrected.
#            Two layers: (b1) implement type of throw-up DeliveryStalled, orchestler not plastering comments; (b2) messages
#            Catch _block (gate=delivery) with STATUS_BLOCKED (natural sticky)+ needs-human+ just one comment;
#            (b3) Second round of pol Keep up, no more coding, no more new comments (killing the unbounded + screen);
#        (c) --force-with-lease = <branch>: <BASE> and BASE is fech ex-SHA,** never** nud --force.
#
# Form description (evalence stratification, concept 8): This feature is **git delivery/formulation conduit within the Vigil autonomous ring**, none
# Program-facing front-end interface - the only visible result "Pre-Home" falls on the git ref and GitHub PR
# Metadata, without any HTTP frontend/paint rendering. So browser navigation/interception e2e** is not applicable** (no Playwright/
# Chrome DevTools MCP; result evidence with CLI/pytest+ real local git driven scripts for 'get rev-parse
# The rit ref claim as the correct view. make back (unreal LLM)
# The certificate is the syntax of** delivery protocol + hardlocks**, without verifying whether "real agent will do it as prompt" -- the latter is based on the line-up Vigil + PR person.
#
# Usage:
#   bash scripts/e2e-spec-0056-git-delivery-rebase-selfheal.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/2] Offline certainty verification (%2)lint + format + (Modular Test)"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest -q

echo
echo "==> [2/2] Offline result exercise: Real local git Fork → rebase Self-healing. → force-with-lease Delivery closed circle + Turn it around. needs-human"
uv run python - <<'PY'
# Spec-0056/T3: Construct a recovery state with a real local git, drive orchestrator.implement by 'delivering delegate + head
# The whole distance is closed. gh/LLM (github.* stakes, boxends for the implementation of the agreement).
import subprocess
import tempfile
from pathlib import Path

from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR
from openagents.orchestrator import Orchestrator, OrchestratorError
from openagents.state import State

BRANCH = "openagents/issue-3"


def git(*, cwd, args, check=True):
    return subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=check
    )


def init_repo(*, path, bare=False):
    path.mkdir(parents=True, exist_ok=True)
    git(cwd=path, args=["init", "--bare"] if bare else ["init"])
    if not bare:
        git(cwd=path, args=["config", "user.email", "e2e@openagents.test"])
        git(cwd=path, args=["config", "user.name", "e2e"])
        git(cwd=path, args=["config", "commit.gpgsign", "false"])


def setup_diverged(*, root):
    """Far-out Naked Library + PR Branch leads base;local worktree Redrafting the same document leads to a fork (conflict) and returns. worktree Path."""
    remote = root / "remote.git"
    init_repo(path=remote, bare=True)
    seed = root / "seed"
    init_repo(path=seed)
    (seed / "spec.txt").write_text("base\n")
    git(cwd=seed, args=["add", "-A"])
    git(cwd=seed, args=["commit", "-m", "chore: base"])
    git(cwd=seed, args=["branch", "-M", "main"])
    git(cwd=seed, args=["remote", "add", "origin", str(remote)])
    git(cwd=seed, args=["push", "-u", "origin", "main"])
    # The remote PR branch leads the case (rechanged spec.txt, in conflict with local writing).
    git(cwd=seed, args=["checkout", "-b", BRANCH, "main"])
    (seed / "spec.txt").write_text("remote-change\n")
    git(cwd=seed, args=["add", "-A"])
    git(cwd=seed, args=["commit", "-m", "docs: remote draft"])
    git(cwd=seed, args=["push", "-u", "origin", BRANCH])
    # Local worktree: Branches from origin/main (and origin/<branch> fork), with a conflict to change to the committee.
    wt = root / ".openagents" / "worktrees" / "issue-3"
    wt.parent.mkdir(parents=True, exist_ok=True)
    git(cwd=root, args=["clone", str(remote), str(wt)])
    git(cwd=wt, args=["config", "user.email", "e2e@openagents.test"])
    git(cwd=wt, args=["config", "user.name", "e2e"])
    git(cwd=wt, args=["config", "commit.gpgsign", "false"])
    git(cwd=wt, args=["checkout", "-b", BRANCH, "origin/main"])
    (wt / "spec.txt").write_text("local-change\n")
    return wt


class ProtocolBackend:
    """Real implementation of the delivery agreement git Ordered fake backend：commit → Remember fetch Front BASE → rebase Conflict resolution →
    push --force-with-lease=<branch>:$BASE。stall=True ”Fake it and do it without push」(Reverse)."""

    name = "protocol"

    def __init__(self, *, stall):
        self._stall = stall
        self.push_cmd = None
        self.base = None

    def run(self, *, work_dir, task, context):
        wt = Path(work_dir)
        git(cwd=wt, args=["add", "-A"])
        git(cwd=wt, args=["commit", "-m", "feat: local draft"], check=False)
        if self._stall:
            return AgentResult(changed=True, summary="pretend-done-but-no-push")
        # BASE takes the fech ** the remote base point (footgun defence) of ** before.
        self.base = git(cwd=wt, args=["rev-parse", f"origin/{BRANCH}"]).stdout.strip()
        git(cwd=wt, args=["fetch", "origin", BRANCH])
        rebase = git(cwd=wt, args=["rebase", f"origin/{BRANCH}"], check=False)
        if rebase.returncode != 0:
            (wt / "spec.txt").write_text("resolved-by-agent\n")
            git(cwd=wt, args=["add", "-A"])
            cont = git(cwd=wt, args=["rebase", "--continue"], check=False)
            if cont.returncode != 0:
                git(cwd=wt, args=["-c", "core.editor=true", "rebase", "--continue"], check=False)
        self.push_cmd = ["push", f"--force-with-lease={BRANCH}:{self.base}", "origin", BRANCH]
        git(cwd=wt, args=self.push_cmd)
        return AgentResult(changed=True, summary="delivered")


def make_orch(*, root, backend):
    state = State(path=root / ".openagents" / "state.json")
    state.record_run(issue_number=3, branch=BRANCH, pr=PR(number=5, url="u/pull/5"))
    return Orchestrator(backend=backend, state=state, work_dir=root, agent_id="agent-e2e")


import openagents.github as gh  # noqa: E402

# --- exercise (a): Fork  →  rebase self-healing  →  force-with-lease push  →  head forward to move ---#
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    wt = setup_diverged(root=root)
    # Pre-set fork: origin/<branch> is not the ancestral of the local HEAD (Jan-Dun, Re-emercing Issue #140).
    git(cwd=wt, args=["fetch", "origin", BRANCH])
    anc = git(cwd=wt, args=["merge-base", "--is-ancestor", f"origin/{BRANCH}", "HEAD"], check=False)
    assert anc.returncode != 0, "Expected fork, but origin/<branch> It’s local. HEAD The ancestors of the world."
    print(f"  · Retroactive readiness: local and origin/{BRANCH} Fork split (non-fast-in) push # Will be rejected #")

    backend = ProtocolBackend(stall=False)
    orch = make_orch(root=root, backend=backend)
    gh.mark_ready = lambda *, pr_number: None  # type: ignore[assignment]
    orch.implement(pr_number=5)

    head = git(cwd=wt, args=["rev-parse", "HEAD"]).stdout.strip()
    remote_head = git(cwd=wt, args=["rev-parse", f"origin/{BRANCH}"]).stdout.strip()
    assert head == remote_head, f"head Move forward:HEAD={head[:12]} ≠ origin={remote_head[:12]}"
    print(f"  ✓ (a) rebase Self-healing. + force-with-lease Push up:origin/{BRANCH} Move Locally HEAD={head[:12]}")

    # (c): Push the belt lace + BASE (fetch ex SHA), this branch alone, and never naked --force.
    joined = " ".join(backend.push_cmd or [])
    assert f"--force-with-lease={BRANCH}:{backend.base}" in joined, f"lease/BASE Not in accordance with:{joined}"
    assert "--force " not in joined and not joined.endswith("--force"), f"Show up naked. --force：{joined}"
    print(f"  ✓ (c) Push the tape. lease、BASE Yes fetch Front SHA={backend.base[:12]}No nudity. --force")

# --- Exercise (b) Reverse: Pretend to be finished but not push assert_delivered sentence not delivered ---#
# PR #141 review will have to be modified in two layers:
#   (b1) Orchestrian Layer: record-based implement paragraph typed DeliveryStalled,** no more self-playing** labels/comments
#        (routing up to messages, avoid need-human not sticky).
#   (b2) Messages: Poll Stage router for the outer layer Catch DeliveryStalled  → block (gate= "delivery")
#        STATUS_BLOCKED (natural snicky)+ needs-human+ just a structured review;** second round of pol will not be re-entered into the coding,
#        The comment is not published (positively proof that the text is originally intended: kill the two "quiet/sound but no bounds" reburning cycles).
from openagents.messages import Messages  # noqa: E402
from openagents.orchestrator import DeliveryStalled  # noqa: E402
from openagents.hold import NONE as NO_HOLD  # noqa: E402
from openagents.state import STATUS_BLOCKED, STATUS_PR_OPEN  # noqa: E402
from openagents.github import Comment  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    setup_diverged(root=root)
    backend = ProtocolBackend(stall=True)  # commit No, but... push
    orch = make_orch(root=root, backend=backend)
    state = orch._state  # Reuse Same State(Incl. pr=5 It’s... coding record）

    # (b1: Orchestrian Layer - Implement Throwed DeliveryStalled, and ** does not touch add_label/post_comment.
    routed = {"add_label": 0, "post_comment": 0}
    gh.mark_ready = lambda *, pr_number: None  # type: ignore[assignment]
    gh.add_label = lambda *, pr_number, name: routed.__setitem__("add_label", 1)  # type: ignore[assignment]
    gh.post_comment = lambda *, pr_number, body: routed.__setitem__("post_comment", 1)  # type: ignore[assignment]

    stalled = None
    try:
        orch.implement(pr_number=5)
    except DeliveryStalled as exc:
        stalled = exc
    assert stalled is not None, "The reverse is still there. DeliveryStalled(hard gate pending delivery)"
    assert isinstance(stalled, OrchestratorError), "DeliveryStalled If I were. OrchestratorError Subcategory (Living) catch   And they’re stuck  "
    assert stalled.pr_number == 5 and stalled.branch == BRANCH, "Signal not with location information"
    assert sum(routed.values()) == 0, f"orchestrator Should not label yourself/Comments:{routed}"
    print("  ✓ (b1) implement Throw! DeliveryStalled- Take it. branch/pr、orchestrator Not Label Comment (Performance)routing Move Up)")

    # (b2) Messages - Poll's route is outside the outer layer catch  →  _block (gate=delivery) with STATUS_BLOCKED (sticky).
    posted: list[str] = []
    labels: list[str] = []
    gh.is_merged = lambda *, pr_number: False  # type: ignore[assignment]
    gh.is_closed = lambda *, pr_number: False  # type: ignore[assignment]
    gh.add_label = lambda *, pr_number, name: labels.append(name)  # type: ignore[assignment]
    gh.list_comments = lambda *, pr_number: []  # type: ignore[assignment]
    # Lets the coded stream read orchestrator deliver call: CLEAR + CI Green + no sticky fingerprints.
    gh.mergeability = lambda *, pr_number: type(  # type: ignore[assignment]
        "_M", (), {"merge_state_status": "CLEAN", "mergeable": "MERGEABLE"}
    )()
    gh.check_status = lambda *, pr_number: type(  # type: ignore[assignment]
        "_S", (), {"state": "pass", "failed_logs": []}
    )()
    gh.code_fingerprint = lambda *, pr_number: ""  # type: ignore[assignment]
    import openagents.identity as ident  # noqa: E402

    ident.post_signed_comment = lambda *, pr_number, body, agent_id: posted.append(body)  # type: ignore[assignment]
    ident.new_human_comments = lambda *, pr_number, since: []  # type: ignore[assignment]
    # The orchestrator delivery for the coding phase (run_e2e) also threw DeliveryStalled (simulation executor without evidence).
    orch.run_e2e = lambda *, pr_number: (_ for _ in ()).throw(  # type: ignore[assignment]
        DeliveryStalled(branch=BRANCH, reason="head Unsold, suspected undelivered", pr_number=pr_number)
    )
    msgs = Messages(orchestrator=orch, state=state, agent_id="agent-e2e")
    rec = state.find_run(pr_number=5)
    rec.status = STATUS_PR_OPEN
    state.update_status(issue_number=3, status=STATUS_PR_OPEN)

    ev1 = msgs._process_run(record=state.find_run(pr_number=5), hold=NO_HOLD)
    assert ev1 == {"pr_number": 5, "reason": "blocked", "gate": "delivery"}, f"Unreceived blocked：{ev1}"
    assert state.find_run(pr_number=5).status == STATUS_BLOCKED, "Unset STATUS_BLOCKED（sticky The key to the end of the line"
    assert gh.BLOCKED_LABEL in labels and len(posted) == 1, f"I should just hang up my comments. + needs-human：{labels}/{len(posted)}"
    print(f"  ✓ (b2) messages catch → _block(delivery) Set STATUS_BLOCKED + {gh.BLOCKED_LABEL} + Just one comment.")

    # Second round: blocked + needs-human is still + no new human comment  →  no more coding, no more new comments.
    gh.has_label = lambda *, pr_number, name: True  # type: ignore[assignment]
    ev2 = msgs._process_run(record=state.find_run(pr_number=5), hold=NO_HOLD)
    assert ev2 is None, f"Second round should be held up (no re-entry) coding）：{ev2}"
    assert len(posted) == 1, "No new comments should be posted in the second round.sticky Kill screen)"
    print("  ✓ (b3) Second round poll Hanging up: No more pie agentNo more new comments. + Screenshot)")

print("\n[Spec-0056/T3] Practice All Green: Fork→rebase Self-healing.→head Forward close; counter-delivery of hard gates→sticky needs-human→No re-entry; always carry leaseNo nudity. force。")
PY

echo
echo "==> [Extra] spec Tool 3 Gate (validate / render / graph）Confirm. spec Contact."
uv run spec validate
uv run spec render >/dev/null
uv run spec graph >/dev/null

echo
echo "✅ Spec-0056 End to end scripts all pass."
