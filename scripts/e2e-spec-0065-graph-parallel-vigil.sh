#!/usr/bin/env bash
# Spec-0065/T1-T2: Offline coverage for graph-driven parallel Vigil.
#
# Exercise successive producer ticks against a fake forge. Independent subjects
# can run together, while a blocked subject waits for its upstream PR to merge.
# Check the terminal-failure path, attempt stamps for unchanged state, watchdog
# diagnostics, and queue ownership. No browser, model API, or real forge is
# needed for this script.
#
# Usage: bash scripts/e2e-spec-0065-graph-parallel-vigil.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/5] Lint and formatting"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/5] Queue, reconciliation, and CLI tests"
uv run --extra dev pytest -q \
  tests/test_agent_curator.py \
  tests/test_recipe_vigil.py \
  tests/test_cli.py

echo
echo "==> [3/5] spec Verify + Generating without drift"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/5] Check the watch. t0–t7：A / B(blocked_by A) / C，K=2      And then     And     And   And   tick The assertion."
uv run --extra dev python - <<'PY'
"""Spec-0065 §11 Executable version of the checklist: false GitHub(RAM)+ False agent(Scriptization)+ True vigil(none change).

Only replacements**Outside world**：GitHub Read & Write`utils.github` / `utils.identity` The blog also highlights the importance of the new media.triager/curator Twice.
LLM Call, and `_act` The one in the country. agent”In exchange for a script-based fake.” agentIt’s still only going through. GitHub Talk.
`_sense` / `_classify` / `_fingerprint` / Queue / flock / `_reconcile` / The producers are all**Original production code**。
"""

import io
import sys
import tempfile
from contextlib import redirect_stderr
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openagents.recipes import vigil
from openagents.runtime.state import RuntimeState
from openagents.utils import agent_config, github, identity

A, B, C = 101, 102, 103
CLOCK = [datetime(2026, 7, 14, 12, 0, 0, tzinfo=UTC)]


def now():
    return CLOCK[0]


def stamp():
    return now().isoformat().replace("+00:00", "Z")


def tick_clock(seconds):
    CLOCK[0] = CLOCK[0] + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------------------------
# Fake GitHub: A variable memory world. Angent and the Night's Watch can only talk through it.
# ---------------------------------------------------------------------------------------------
class Hub:
    def __init__(self):
        # Three to-do issues, all with triggers for label `openagents` (config.labels, the Vigil pick-up).
        self.issues = {
            A: {"title": "Definitions Storage Interface", "body": "Set interface first", "labels": {"openagents"}, "open": True},
            B: {"title": "implementation SQLite Backend", "body": "Dependency A Interfaces for", "labels": {"openagents"}, "open": True},
            C: {"title": "Fill README", "body": "Independent mission", "labels": {"openagents"}, "open": True},
        }
        self.edges = {A: [], B: [], C: []}  # blocked_by
        self.prs = {}  # number -> dict
        self.next_pr = 200

    def open_pr(self, *, issue_number):
        number = self.next_pr
        self.next_pr += 1
        self.prs[number] = {
            "issue": issue_number,
            "branch": f"openagents/issue-{issue_number}",
            "head": f"{issue_number}{'a' * 37}",
            "labels": set(),
            "merged": False,
            "open": True,
            "comments": [],
            "ci": ("pending", 2),  # (state, count)
            "ci_at": stamp(),
            "head_at": stamp(),
        }
        return number

    def pr_of(self, issue_number):
        for number, pr in self.prs.items():
            if pr["issue"] == issue_number:
                return number, pr
        return None, None


HUB = Hub()
ACTS = []  # False agent Every time they call up, they remember. —— ”Zero is redundant. LLM Call.


def fake_get_issue(*, number):
    data = HUB.issues[number]
    return github.Issue(number, data["title"], data["body"], sorted(data["labels"]))


def fake_list_issues(*, labels, state="open"):
    wanted = set(labels or [])
    return [
        github.Issue(number, data["title"], data["body"], sorted(data["labels"]))
        for number, data in sorted(HUB.issues.items())
        if data["open"] and wanted <= data["labels"]
    ]


def fake_list_open_prs():
    return [github.PR(number, f"u/{number}") for number, pr in HUB.prs.items() if pr["open"]]


def fake_pr_head_branch(*, pr_number):
    return HUB.prs[pr_number]["branch"]


def fake_pr_for_branch(*, branch):
    # ** Unlimited**:merged PR should be visible (or the next round of consolidation will read "not yet PR" again).
    for number, pr in HUB.prs.items():
        if pr["branch"] == branch:
            return github.PR(number, f"u/{number}")
    return None


def fake_pr_snapshot(*, pr_number):
    pr = HUB.prs[pr_number]
    state = "MERGED" if pr["merged"] else ("OPEN" if pr["open"] else "CLOSED")
    return github.PRSnapshot(
        number=pr_number,
        state=state,
        head_sha=pr["head"],
        labels=tuple(sorted(pr["labels"])),
        mergeable="MERGEABLE",
        merge_state_status="CLEAN",
        head_pushed_at=pr["head_at"],
    )


def fake_check_snapshot(*, pr_number):
    state, count = HUB.prs[pr_number]["ci"]
    return github.CheckSnapshot(state, count, HUB.prs[pr_number]["ci_at"])


def fake_check_logs(*, pr_number):
    return ["ci: Single measure test_flaky_upstream Hang up."]


def fake_list_comments(*, pr_number):
    return [
        github.Comment(index, "bot", body, at)
        for index, (body, at) in enumerate(HUB.prs[pr_number]["comments"])
    ]


def fake_post_comment(*, pr_number, body):
    HUB.prs[pr_number]["comments"].append((body, stamp()))


def fake_issue_comment(*, number, body):
    pr_number, _ = HUB.pr_of(number)
    if pr_number is not None:
        fake_post_comment(pr_number=pr_number, body=body)


def fake_add_label(*, pr_number, name):
    HUB.prs[pr_number]["labels"].add(name)


def fake_remove_label(*, pr_number, name):
    HUB.prs[pr_number]["labels"].discard(name)


def fake_issue_add_label(*, number, name):
    HUB.issues[number]["labels"].add(name)


def fake_list_blocked_by(*, number):
    return [
        github.Blocker(blocker, "CLOSED" if not HUB.issues[blocker]["open"] else "OPEN")
        for blocker in HUB.edges[number]
    ]


def fake_add_blocked_by(*, number, blocker_number):
    HUB.edges[number].append(blocker_number)


def fake_post_signed_comment(*, pr_number, body, agent_id):
    fake_post_comment(pr_number=pr_number, body=identity.sign(body=body, agent_id=agent_id or "oa"))


for name, impl in {
    "get_issue": fake_get_issue,
    "list_issues": fake_list_issues,
    "list_open_prs": fake_list_open_prs,
    "pr_head_branch": fake_pr_head_branch,
    "pr_for_branch": fake_pr_for_branch,
    "pr_snapshot": fake_pr_snapshot,
    "check_snapshot": fake_check_snapshot,
    "check_logs": fake_check_logs,
    "list_comments": fake_list_comments,
    "post_comment": fake_post_comment,
    "issue_comment": fake_issue_comment,
    "add_label": fake_add_label,
    "remove_label": fake_remove_label,
    "issue_add_label": fake_issue_add_label,
    "list_blocked_by": fake_list_blocked_by,
    "add_blocked_by": fake_add_blocked_by,
    "ensure_label": lambda *, name, description="": None,
}.items():
    setattr(github, name, impl)
identity.post_signed_comment = fake_post_signed_comment

# LLM calls twice (access): Triager sentence actionable, Curator row B blocked_by A, C independent.
vigil.stages.triage = lambda **kw: {"actionable": True, "reason": "Directly assignable"}
vigil.engine.run_agent = lambda *a, **kw: {"edges": [{"issue": B, "blocked_by": [A]}]}


# ---------------------------------------------------------------------------------------------
# False agent: `_act`. It can only change GitHub - route still a branch of the code.
# ---------------------------------------------------------------------------------------------
def fake_act(*, backend, state, work_dir, config, observed, verdict, agent_id, now, lock_fd):
    facts = observed.facts
    ACTS.append((facts.subject, verdict.action))
    kind, number = vigil._split_subject(subject=facts.subject)

    if verdict.action == vigil._ACT_SOLVE:
        HUB.open_pr(issue_number=number)
        return "Open draft PR And push the first edition to achieve"

    pr = HUB.prs[facts.pr_number]
    if verdict.action == vigil._ACT_E2E:
        fake_post_signed_comment(
            pr_number=facts.pr_number,
            body=f"<!-- openagents:e2e head={facts.head_sha} -->\n✅ e2e passed",
            agent_id=agent_id,
        )
        return "e2e passed"
    if verdict.action == vigil._ACT_REVIEW_OR_FIX:
        pr["labels"].add(f"review-approved:{facts.head_sha[:7]}")
        return "review passed"
    if verdict.action == vigil._ACT_MERGE:
        pr["merged"] = True
        pr["open"] = False
        HUB.issues[pr["issue"]]["open"] = False
        return "Merged"
    if verdict.action == vigil._ACT_FIX_CI:
        if pr["issue"] == B:
            # t4 Main path: agent determined it was upstream flaky, unable to fix it, walking through the first exit, calling himself a human.
            pr["labels"].add("needs-human")
            fake_post_signed_comment(
                pr_number=facts.pr_number,
                body="⏸ CI Red is upstream. flakyI can’t fix it, man.",
                agent_id=agent_id,
            )
            return "He’s been beaten. needs-human"
        # t5 Guard I: agent** thought ** had repaired (rerun only CI), no real change, no needs-human.
        return "I ran again. CII think it’s done."
    raise AssertionError(f"The checklist should not have come to this:{verdict.action}")


vigil._act = fake_act

CONFIG = agent_config.AgentConfig(
    version=1,
    agents=agent_config.AgentPolicy(backends={}),
    stages=agent_config.StagePolicy(owners={"triage": "agent"}),
    release=agent_config.ReleasePolicy(),
    interval=1,
    base="main",
    labels=["openagents"],
    repos=[],
)
WORK = Path(tempfile.mkdtemp(prefix="oa-0065-e2e-"))
STATE = RuntimeState(path=WORK / "runtime-state.json")


def run_tick():
    """Run!**One.** tick(a producer determination) + Empty tick I’m going back to Ben. tick the log."""
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        vigil.run_vigil(
            backend=None,
            state=STATE,
            work_dir=WORK,
            config=CONFIG,
            once=True,
            concurrency=2,  # K=2: Parallel ceiling
            agent_id="oa-e2e",
            now_fn=now,
        )
    return buffer.getvalue()


def check(label, condition, detail=""):
    if not condition:
        print(f"✗ {label}{(' —— ' + detail) if detail else ''}", file=sys.stdout)
        sys.exit(1)
    print(f"  ✓ {label}")


# ---- t0/t1: Access + Dependence on Edge GitHub; K=2 and A and C, B blocked by -------------------------
run_tick()
check("t0 Triple access:A/B/C All over the door. Hit it. ready", all("ready" in HUB.issues[n]["labels"] for n in (A, B, C)))
check("t0 curator Line GitHub Native blocked_by：B←A、C Independence", HUB.edges[B] == [A] and not HUB.edges[C])
check("t1 A with C Start parallel work (each one) PR）", HUB.pr_of(A)[0] is not None and HUB.pr_of(C)[0] is not None)
check("t1 B Pour QUIET(awaiting-blockers) Block: Not opened PRZero. agent Call", HUB.pr_of(B)[0] is None)
check("t1 I’ve only called twice. agent（A/C Once each. solve）", ACTS == [("issue:101", "solve"), ("issue:103", "solve")]
      or ACTS == [("issue:103", "solve"), ("issue:101", "solve")], str(ACTS))

# ---- t2/t3: CI output  →  A discharge line meggered; C CI Red (first column) ------------------------------
tick_clock(60)
pr_a, data_a = HUB.pr_of(A)
data_a["ci"] = ("pass", 3)
pr_c, data_c = HUB.pr_of(C)
data_c["ci"] = ("fail", 3)
ACTS.clear()
run_tick()
check("t3 A：CI Green → I’m going to take it from you. e2e→review→merge I’m going to go through the walk.",
      [action for subject, action in ACTS if subject == "issue:101"] == ["e2e", "review-or-fix", "merge"],
      str(ACTS))
check("t3 A It’s... PR Already merged、issue Disabled", data_a["merged"] and not HUB.issues[A]["open"])
check("t5 C：CI Red → agent It’s a change. → Guy. attempt fp - It’s over.",
      any(vigil._ATTEMPT_MARKER in body for body, _ in data_c["comments"]))
check("t5 C Ben. tick Just once. fp No more fights on top",
      [action for subject, action in ACTS if subject == "issue:103"] == ["fix-ci"], str(ACTS))

# ---- t3 (second half): blocker of A mergid  → B turns off  →  natural unlocking; C see pt pt zero LLM ----------------------
tick_clock(60)
ACTS.clear()
run_tick()
check("t3 B: Upstream A After Merge**Next tick** Unlock Nature → solve Open PR", HUB.pr_of(B)[0] is not None)
check("t5 Watchout I:C It’s... fp Unchanged, same as above fp Poke → No, no, no, no, no.**nil LLM Call**",
      not [action for subject, action in ACTS if subject == "issue:103"], str(ACTS))

# CI of ---- t4:B plays the red agent self needs-human (main path: on-site TERMINAL, without any threshold) ----------------
tick_clock(60)
pr_b, data_b = HUB.pr_of(B)
data_b["ci"] = ("fail", 3)
ACTS.clear()
run_tick()
check("t4 Main path:agent Upstream. flaky → Fight yourself. needs-human + Reasons for staying",
      "needs-human" in data_b["labels"]
      and any("Upstream dependency flaky" in body for body, _ in data_b["comments"]))
check("t4 The same time you claim the next lap in the same circle. TERMINAL: Only once agent（fix-ci）Do not try again",
      [action for subject, action in ACTS if subject == "issue:102"] == ["fix-ci"], str(ACTS))

tick_clock(60)
ACTS.clear()
run_tick()
check("t4 The round stops on the spot:B Already TERMINALFollow-up tick nil agent Call", not ACTS, str(ACTS))

# ---- t6: Watchbar II - C Awaiting-effect Superthreshold  →  Mechanical Park (other than LLM) ------------------------------
tick_clock(4000)
ACTS.clear()
logs = run_tick()
# `_park` beats needss-human** (subject=issue:103);  takes the label of issue  →  PR and collects it in a series of `_sense`s.
# So the next round will be the TéRMINAL.
check("t6 Watcht two:awaiting-effect Super-threshold → _park Fight! needs-human(Mechanical diagnosis, no calls) LLM）",
      "needs-human" in HUB.issues[C]["labels"] and not ACTS, str(ACTS))
check("t6 park With a mechanical diagnosis. + agent That conclusion of my own.",
      any("Run again. CI" in body or "openagents Vigil" in body for body, _ in data_c["comments"]))

# ---- t7: All TERMINAL Zone 0  → hang Call a classification hint and die -------------------------------------
tick_clock(60)
ACTS.clear()
logs = run_tick()
check("t7 All TERMINAL → Ben. tick Incoming! 0 → _hang Call for a visual tip.", "This is a round of nobody moving." in logs, logs)
check("t7 nil agent Call.", not ACTS, str(ACTS))

print("✓ Check the watch. t0–t7 All adopted (includes) t4 Main Path / t5 Guard I / t6 Watcht 2 / t7 hang）")
PY

echo
echo "==> [5/5] grep anchor:flock No, it’s not. lockf / _mark_done yes DELETE / None lease Columns / recipes None subprocess Straight"

fail() {
  echo "✗ Organisation$1" >&2
  exit 1
}

# 5a. The survival certificate must be aflock call (the lock of `lockf` is per-process, and the cross-repeated with the K-worker line of the process will be silently invalidated).
# Only** call** (`fcntl.xxx(`) does not recognize the references in the text - the modular document is exactly "Why can't we use lockf".
grep -q "fcntl\.flock(" openagents/recipes/vigil.py || fail "vigil Unused fcntl.flock - To get a living certificate."
grep -q "fcntl\.lockf(" openagents/recipes/vigil.py && fail "vigil I’ve got it. fcntl.lockf(Same as Process) fd No one else. → Double running)"

# 5b. The closure is a DELETE line (staying status='done' will be permanently locked to the subject UniQUE to the subject); no lease line in the form DDL
# (Death by kernel locking, not by threshold — a glitch that can be mistled is a possible double run).
grep -q "DELETE FROM work_queue" openagents/recipes/vigil.py || fail "_mark_done No, it’s not. DELETE"
uv run --extra dev python -c "
from openagents.recipes.vigil import _SCHEMA
ddl = ' '.join(_SCHEMA.lower().split())
assert 'subject text not null unique' in ddl, 'work_queue.subject Missing UNIQUE(Stick it up)/Crust./  I’ll be waiting for a three-in-one  '
assert 'lease' not in ddl and 'expires' not in ddl, 'Form DDL Including lease fields (this design is based on flock Death sentence, no threshold)'
" || fail "work_queue Form DDL Not in line (lack) subject UNIQUE / including lease line)"

# 5c. recipes layer does not directly adjust subproces (Spec-0064 strebular anchor: recipe only takes utils stabilizer; process detection utils/proc.py).
for r in stages vigil backfill; do
  grep -nE 'import subprocess|subprocess\.' "openagents/recipes/${r}.py" \
    && fail "openagents/recipes/${r}.py Ham subprocess Direct Call (should go) utils）"
done

# 5d. Hard timeout must** kill the exact ** process tree from which this call is made:backend self-report PID into the collectible (`proc.publish`), time-lapse-barrel
# Kill`proc.kill_tree`）。If you return to the "A"diff "The sub-process of this process is gathered to guess." gh/git Or something. worker It's...
# Angent - Kill the Wrong Person = The really hung agent is pushing, and double running is happening.
uv run --extra dev python -c "
from openagents.utils import proc
for name in ('track', 'publish', 'untrack', 'child_pids', 'kill_tree', 'hold_fd', 'inherited_fds'):
    assert hasattr(proc, name), f'utils.proc Missing {name}(Recognition of a barrel)/Exactly./(a) The interface of the certificate of survival)'
" || fail "utils/proc.py Interface interface does not match (recognizing a barrel) + kill_tree + hold_fd/inherited_fds）"
grep -q "proc_utils\.publish(pid=proc\.pid, handle=proc)" openagents/backends/claude_code.py \
  || fail "backend Unreported PID+Snack. PID I’ll kill you. PID Innocent Process after Reuse → Double running)"

# 5d-bis.** Survivors must follow the real work process.** Flock only proves that the Vigil is alive; Vigil is being held by SIGKILL/OOM/docker
# When he was killed, it started an agent process that was orphaned, not killed.
# Push. So pass the lock fd to agent subprocessor inheritance (pass_fds): Orphanes are still running Zoom locks cannot grab Zoom lines will not be recycled Zoom without running.
grep -q "pass_fds=proc_utils\.inherited_fds()" openagents/backends/claude_code.py \
  || fail "backend Not put flock fd Pass it. agent The Son Process is inherited (Silver Watch killed) → Orphans agent Still pushing. → Lines Recycled → Double running)"
grep -q "proc\.hold_fd(fd=self\._lock_fd)" openagents/recipes/vigil.py \
  || fail "vigil Unclaimed flock fd Registered to agent Subprocess Succession"

# 5d-ter. ** Succession must be accompanied by a gate.** The lock passed to agent and then passed to his grandson. (pass_fds clears CLOEXEC in the child process, and angen
# Not python, not for us: agent leaks a long-lived grandson (MCP server/ backstage dev server), and the lock never goes.
# That. queued The line never goes away, and all the watchdogs can't see it. claimed / IN_FLIGHT Look. claimed_at / QUIET watchdog
# Only QuiET. Without _sweep_stalled, this is a rare double run for a permanent quiet stop**.
uv run --extra dev python -c "
import inspect
from openagents.recipes import vigil
assert '_sweep_stalled(' in inspect.getsource(vigil._producer_tick), (
    'Producers tick Unsweeped”queued ”and he can’t take it.” →   I’m going to be quiet forever  '
)
" || fail "Producers tick Uncleaned lock"

# ** _sweep_stalled will park a subject (stopping a job of a sossue)
# So it's more positive than it needs.
#   (1) TOCTOU: SELECT takes several seconds for the line to go and go; during this period, worker can legally take ** another line** and
#       Take its lock -- go and look it up, it's "occupied" and then remove and delete a working claimed park. So park before
#       The "business or queued" must be reviewed in the BEGIN IMMEDIATE and DESETE must take AND status= queued.
#   (2) Console window: _requeue_or_park/_reclaim_dead first to reset status to queued submission, then os.close (fd), in the middle of the moment
#       enqueued_at is never updated to keep the hunger alive, and it's used as a gate for the long life of the world.
#       Requeue is "overage" and is the right time to die in this window. The age must be seen_locked memory: a tick in **
#       Only one can be observed, but no second tick.
#   (3) The row of Park is closed: the whole of the tick dies, and the whole line is shut down.
grep -q "BEGIN IMMEDIATE" openagents/recipes/vigil.py \
  || fail "park Not before BEGIN IMMEDIATE Review status in (in)TOCTOU: Will put worker Running. claimed Deleted)"
grep -q "DELETE FROM work_queue WHERE id=? AND status='queued'" openagents/recipes/vigil.py \
  || fail "park It’s... DELETE Not with status='queued' Guards. → Delete the line that runs)"
# And ** the deletions must have taken place before gh**: only "reveal the label" can save the speech, and the review can't save the moment the label is finished.
# The leak may happen to be dead, lock a free worker, and then legally take away and run, the needs-human, and then falls in a ** healthy and being executed**
# It's... subject Go, go, go! → Next round. TERMINAL → worker Turn around and leave. → This. issue No more hands._claim_next
# I'm just saying, I'm not gonna say anything until I get it.
uv run --extra dev python -c "
import ast, inspect, textwrap
from openagents.recipes import vigil
fn = ast.parse(textwrap.dedent(inspect.getsource(vigil._park_stalled))).body[0]
body = fn.body[1:] if ast.get_docstring(fn) else fn.body   # Just looking.**Code**: These two words are also written in the document string.
code = chr(10).join(ast.unparse(node) for node in body)    # I’ll be fed my own notes to a constant claim.
assert code.index('DELETE FROM work_queue') < code.index('_park_needs_human'), (
    '_park_stalled First. label Delete the line. → label It’ll fall on one. worker Health legally recovered subject Top (permanently suspended)'
)
" || fail "park It’s in the wrong order."
grep -q "seen_locked" openagents/recipes/vigil.py \
  || fail "The lock is not broken. tick(Used) enqueued_at When you’re at the age gate, you kill by mistake. requeue/reclaim )"
uv run --extra dev python -c "
import inspect
from openagents.recipes import vigil
sweep = inspect.getsource(vigil._sweep_stalled)
assert 'except' in sweep, '_sweep_stalled No single line separated park Failed (one time) gh 429 It’ll turn off the whole producer. tick）'
drain = inspect.getsource(vigil._drain_queue)
assert '_sweep_stalled' in drain, '_drain_queue Do not sweep locks (--once It’ll be drying up on the leak locks. _DRAIN_MAX_SECONDS）'
" || fail "The Chen lock and quarantine./The empty face doesn’t match."

# 5d-quinquies. ** `triage: human` is a dialogue, not a one-time hang-up**, and the gate must be ** a human gate**.
#   (1) Hangs needs-human et al. label is a dead end: Neds-human in `_classify` is TERMINAL, `_intake` also skips to take it
#       The issue -- you can't watch this until after the Vigil, and nobody reads anything down there. So ask the comment and wait for a response.
#   (2) "Nods"** cannot be given: Triager is another issue, and discipline is
#       **fail-open** (shows if you can't.) People say "do it first" does not belong to any of its five categories.
#       ** Send the living under a clear veto**. The gate will be turned into a "yes" agent. So you must go fail-CLOSED
#       It's... admitter（stages.admit）。
#   (3) The part that waits must **LLLM**: every tick on the access is re-scanning this issue (it has neither been ready nor needs-human) and it is not a good idea to be able to get back to the rest of the world.
#       Every round is called antent = a tick-based machine.
#   (4) The sentence of "persons answer" must be passed in code**: comments issued after we ask the questions** and** without our signature**.
#       This is the one we write ourselves for Park Reason/attempt, and it's a human response to what you write.
uv run --extra dev python -c "
import ast, inspect, textwrap
from openagents.recipes import vigil

def _code(fn):  # Just looking.**Code**: Words appear unnumbered in document string (words are not deceptive) AST）
    node = ast.parse(textwrap.dedent(inspect.getsource(fn))).body[0]
    stmts = node.body[1:] if ast.get_docstring(node) else node.body
    return chr(10).join(ast.unparse(s) for s in stmts)

code = _code(vigil._ask_human)
assert '_ADMIT_ASK_MARK' in code, '_ask_human There’s no ”Is there a question” tag. → Every tick Repeat the question.'
assert 'stages.admit' in code, '_ask_human Not gone. fail-closed It’s... admitter'
assert 'stages.triage' not in code, (
    '_ask_human Take it. triager ”Nods.”→ It’s... fail-openPeople say ”don’t do it” and they get a pass.'
)
assert '_human_replies' in code, '_ask_human No ”does anyone answer?”→ Waiting period every tick Call me once. agent(Cellprinter)'
assert code.index('_human_replies') < code.index('stages.admit'), (
    '_ask_human Go ahead. agent And if anyone answers, → The waiting period is the same. LLM'
)
assert '_dialogue' in code, '_ask_human I didn’t feed the conversation. admitter → People say nothing.'
assert code.index('_post_admit_verdict') < code.index('_grant_ready'), (
    'The award was not set. GitHub Fall back. → Fight! label That step goes on.429）Next tick You’re gonna have to re-sentencing. LLM）'
)
assert code.index('_post_admit_try') < code.index('stages.admit'), (
    'try Poke (Puncture)LLM   The coupons   agent Before the cover → agent - One sentence./timeout/429）The blogger says that the government is not going to let anything last.'
    'Next tick Here we go again. issue → Every tick Burn it once. LLMForever.'
)
assert '_admit_tried' in code, (
    'I’ve never said ”person” before. agent」→ It’s a sentence. issue Every tick It’s a new burn. It’s not a transfer.'
)
replies = _code(vigil._human_replies)
assert 'parse_agent_id' in replies and 'created_at >' in replies, (
    'The verdict ”he said he did” was incomplete. + Without our signature, we will take our comments as a human reply.'
)
assert '_MAINTAINER_ASSOCIATIONS' in replies, (
    'The gate is not a person. → Any one of the people in the public warehouse can send the living.admitter The text of the message cannot be stopped:'
    'It reads only a text that an outsider can write, and it doesn’t even know who to listen to.'
)
dialogue = _code(vigil._dialogue)
assert '_human_replies' in dialogue, (
    'Here. admitter The conversation wasn’t ”Our questions.” + ”The defender’s response.”→ The passersby is a commenter. prompt = - Put it on. fail-closed The gate.'
    'Exposure to infusion of hints; our own poking prompt = agent I’m meeting myself in the same conversation.'
)
verdict = _code(vigil._admit_verdict)
assert 'reply_key' in verdict and 'created_at' not in verdict, (
    'The award is suspended on time rather than on comment. id → GitHub It’s... createdAt In seconds, a new word will hit a sentence.'
    'refused Poke → No one can nod their head.fail-closed The blogger says that the ”one word more” is being reduced to ”permanent rejection”.'
)
key = _code(vigil._reply_key)
assert 'reply.id' in key, 'The person must be the identity of the person. comment id”Never again” ”Don’t use the second to mark”'
park = _code(vigil._park_needs_human)
assert 'identity.sign' in park, (
    'park The reason for not signing. → People only pick them up. label We wrote it when we didn’t answer. park The reason is to be taken as a human reply.'
)
assert '_already_said' in park, (
    'park No Serious → Take them off. label And when nothing changes, every time, tick Repost an identical reason (s)label Wait, wait, wait, wait.'
)
" || fail "Access human Triple state is not a conversation. / Take it. fail-open It’s... triager As a human gate. / Waiting period for burning LLM / We’re not signing the comment. / The gate is not a person."

# The discipline of 5d-sexies.admitter must be **fail-closed**: the default "no nod" is not.
# The output side {approved, reason} is not the same name {actionable, reason} of Triager -- a place is a contract, and the string is made
# Re-mail it as a synonym to Triage.
uv run --extra dev python -c "
from openagents.agents import admitter
assert admitter.OUTPUT_SCHEMA == {'approved': bool, 'reason': str}, 'admitter The output contract is not in line.'
tmpl = admitter.PROMPT.template
for token in ('\$issue_body', '\$dialogue'):
    assert token in tmpl, f'admitter PROMPT Missing placeholder {token}'
assert 'fail-closed' in tmpl or 'You can’t start without permission.' in tmpl, 'admitter Not written dead. fail-closed Discipline (unruly)=No nods.'
" || fail "admitter Contracts/I don’t know. fail-closed）"

# `needs-human` is the first-class exit for an individual: every branch called an agent** must spell the contract in a hint, otherwise the branch should be
# Angent has no way back, but he can only walk down with his head (the main path). 7 _do_* of _do_merge is purely mechanical, not agent.
uv run --extra dev python -c "
import inspect
from openagents.recipes import vigil
src = inspect.getsource(vigil)
branches = [n for n in dir(vigil) if n.startswith('_do_') and n != '_do_merge']
missing = [
    n for n in branches
    if '_NEEDS_HUMAN_CONTRACT' not in inspect.getsource(getattr(vigil, n))
]
assert not missing, f'These. agent The branch’s not working. needs-human Contract:{missing}'
assert len(branches) >= 6, f'agent The branch only found {len(branches)} One, the anchor could be off the grid.'
" || fail "Yes. agent Branches Not Injected _NEEDS_HUMAN_CONTRACT  First exit blocked  "

# 5f. `--parallel` is a side-shot slinger, which must close the boundary at the argparse level: 0/negatives will be treated as 1 (K machines converted to 1), and the QC will be used to keep silent.
# The Queue is dead, and the huge value is really going to drive so many lines (the gh limit/file handle).
uv run --extra dev python -c "
import argparse
from openagents.cli import _MAX_PARALLEL, _parallel_k
assert _parallel_k('1') == 1 and _parallel_k(str(_MAX_PARALLEL)) == _MAX_PARALLEL
for bad in ('0', '-3', str(_MAX_PARALLEL + 1), 'abc'):
    try:
        _parallel_k(bad)
    except argparse.ArgumentTypeError:
        continue
    raise AssertionError(f'--parallel Accept cross-border values {bad!r}')
" || fail "--parallel Unreceipt of border (in thousands of United States dollars)0/Negative/Super-high value released)"

echo "✓ grep All anchor points pass:flock(No lockf）、DELETE Payback, no lease,recipes nil subprocess Straight, straight."
echo "  Precision kill process tree (self-reported) PID）、needs-human The contract is in the whole branch.--parallel boundary"
echo
echo "✅ Spec-0065 Offline e2e All green."
