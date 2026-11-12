#!/usr/bin/env bash
# Spec-0049 end-to-end test start script: vigil multi-backend single-claim to tear each other (resume waiver + tie attribution + secondary confirmation of subordination).
#
# The group is divided into two layers to treat "two backends to the same issue and repeatedly/recognize the tags for minutes":
#   1 Stop the bleeding - resume path no longer recognized (claims are only given once in a single fight in fresh);
#   2 Thermolog - Claim = add et al. fixed tag + Add a **-Pertificate ** (attribution certificate) + read-after-write 2 times
#      Confirm: Read it again after posting and be accepted later by another agent, ClaimLost, and the back end of this offer (cleaning local solving).
# Result: The same issue is validly claimed at any given time by one backend, and identified and given back; only the tags are used to label the tags, the add, etc.
# There is no difference in tearing up the labels of others — the physical sources of torn-up are removed.
#
# ** Browser e2e Not applicable**: This feature is a backend GitHub tag/ comment and time-series problem, no product front-end interface is driven
# (no navigation)/Interactive/The results are in the form of a test result.**Certainness and Recurrence**（pytest Integrated Test +
# Ben Shell runs it and prints evidence) instead of browser e2e. The whole ** is netless and does not match the real gh/LLM/git ** remote.
#
# Usage:
#   bash scripts/e2e-spec-0049-vigil-claim-ownership.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] Static Check (Standard)ruff lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] Orientation module/Integrated Test (Integrator Test)Spec-0049 T1–T5）"
uv run --extra dev pytest -q \
  tests/test_github_claim_label.py \
  tests/test_identity_claim.py \
  tests/test_vigil_claim.py \
  tests/test_orchestrator_claim.py \
  tests/test_claim_dedup_integration.py

echo
echo "==> [3/4] Evidence of results: use**Real** Orchestrator + State Drive two backends to the same issue Competition, three pieces of evidence."
uv run python - <<'PY'
# Spec-0049 Result Exercise: add + with Orchestrator.start_rfc (soft _claim_issue) + real** product code
# Sign by signature + read-after-write surrender) + State — Run out two angents against the same issue and print out evidence.
# Scripts only provide memory versions of GitHub World (label collection + review book + event record) and a Gbit-free Workspace double (test side)
# Plugin) , time series / attribution determination / subordination is all from product code.
from pathlib import Path

from openagents import github, identity
from openagents import orchestrator as orch_module
from openagents.backends.base import AgentResult
from openagents.github import PR, Comment, Issue
from openagents.orchestrator import ClaimLost, Orchestrator
from openagents.state import State

DISPATCH = github.DISPATCH_LABEL


class World:
    def __init__(self, *, number):
        self.number = number
        self.labels = {number: {"openagents"}}
        self.comments = {number: []}
        self.branches = set()
        self.events = []
        self._clock = 0
        self.on_after_note = None

    def _ts(self):
        self._clock += 1
        return f"2026-07-03T00:00:{self._clock:02d}Z"

    def get_issue(self, *, number):
        return Issue(number=number, title="And it’s heavy.", body="b", labels=tuple(self.labels[number]))

    def issue_add_label(self, *, number, name):
        if name not in self.labels.setdefault(number, set()):
            self.labels[number].add(name)
            self.events.append(("labeled", number))

    def issue_remove_label(self, *, number, name):
        if name in self.labels.setdefault(number, set()):
            self.labels[number].discard(name)
            self.events.append(("unlabeled", number))

    def issue_comment(self, *, number, body):
        self.events.append(("comment", number))
        self.comments.setdefault(number, []).append(
            Comment(id="IC", author="", body=body, created_at=self._ts())
        )
        hook, self.on_after_note = self.on_after_note, None
        if hook is not None:
            hook()

    def list_issue_comments(self, *, number):
        return list(self.comments.get(number, []))

    def create_pr(self, *, branch, title, body, base, draft):
        self.branches.add(branch)
        self.events.append(("pr", int(branch.rsplit("-", 1)[1])))
        return PR(number=int(branch.rsplit("-", 1)[1]), url=f"u/pull/{branch}")


class FakeWorkspace:
    def __init__(self, *, root):
        self._root = Path(root)

    def prepare(self, *, issue_number, branch, base):
        return self._root / str(issue_number)

    def ensure(self, *, issue_number, branch):
        return self._root / str(issue_number)

    def commit_and_push(self, *, worktree, branch, message):
        pass

    def changed_spec_group(self, *, worktree, base):
        return None


class FakeBackend:
    name = "fake"

    def run(self, *, work_dir, task, context):
        return AgentResult(changed=True, summary="done")


world = World(number=42)
for name in ("get_issue", "create_pr", "issue_add_label", "issue_remove_label", "issue_comment",
             "list_issue_comments"):
    setattr(orch_module.github, name, getattr(world, name))
setattr(github, "list_issue_comments", world.list_issue_comments)

tmp = Path("/tmp/oa-spec-0049-e2e")
state_a, state_b = State(path=tmp / "a.json"), State(path=tmp / "b.json")
for st in (state_a, state_b):
    store = {"runs": [], "cursors": {}}
    st._load = lambda store=store: store
    st._save = lambda *, data, store=store: store.update(data)


def make(agent_id, state):
    o = Orchestrator(backend=FakeBackend(), state=state, work_dir=tmp, agent_id=agent_id)
    o._workspace = FakeWorkspace(root=tmp)
    return o


orch_a, orch_b = make("agent-A", state_a), make("agent-B", state_b)

b_pr = {}
# A after the pass sign, before read-after-write, B runs the full claim later.
world.on_after_note = lambda: b_pr.__setitem__("pr", orch_b.start_rfc(issue_number=42, base="main"))

retreated = False
try:
    orch_a.start_rfc(issue_number=42, base="main")
except ClaimLost as exc:
    retreated = True
    claim_lost_msg = str(exc)

unlabeled = [e for e in world.events if e[0] == "unlabeled"]
resume_events_before = len(world.events)
# Resume waiver: B is already in refc-review and does not create a new claim event - here is a direct demonstration of B if resume(solving/pr=0)
# Also zero claim: New orphan Solving state, running start_rfc (resume=True), claiming zero labeled/comment.
world.events.clear()
state_c = State(path=tmp / "c.json")
store_c = {"runs": [], "cursors": {}}
state_c._load = lambda: store_c
state_c._save = lambda *, data: store_c.update(data)
orch_c = make("agent-C", state_c)
state_c.begin_run(issue_number=42, branch="openagents/issue-42")
orch_c.start_rfc(issue_number=42, base="main", resume=True)
resume_claim_events = [e for e in world.events if e[0] in ("labeled", "comment")]

winner = b_pr["pr"].number == 42 and retreated and state_a.all_runs() == []
notes = [identity.parse_agent_id(body=c.body) for c in world.comments[42]]

print("  evidence①[Until winning]:B Open draft PR #%d，A Check out the other party’s claim later. → ClaimLost Deport and clear the area. solving："
      % b_pr["pr"].number, winner)
print("     └ A Reasons for subordination:%s" % claim_lost_msg)
print("  evidence②[Zeroes] unlabeled   Tore each other up     No one ever claimed competition   remove label, sign only without adding or deleting (%d Notes:%s）；"
      "Unique unlabeled yes B Open PR After _release_claim（%d - It happens a few times. PR After:"
      % (len(notes), notes, len(unlabeled)),
      len(unlabeled) == 1)
print("  evidence③【resume Zero new recognition event:solving/pr=0 Orphans run Let’s go. start_rfc(resume=True) Keep going."
      "nil labeledZero. comment Recognition event (actual) %d Article:" % len(resume_claim_events),
      resume_claim_events == [])

assert winner, "It’s a winner, a loser, and a local loser."
assert unlabeled == [("unlabeled", 42)], "No competition period. unlabeled Tore each other up."
assert resume_claim_events == [], "resume Paths should not create new identification events"
print("  ✓ All three claims passed.")
PY

echo
echo "==> [4/4] spec VerifySpec-0049 Group Structure + OVERVIEW/ARCHITECTURE No drift)"
uv run spec validate --specs-root docs/specs
# render/graph: First saves a copy, then replays the diff and then corresponds by bytes - without git-submitting,
# Make scripts run independently of exit codes on any work tree 0（CI And then there's something else. git diff --exit-code The price of the price is not the same as the price of the car.
cp docs/specs/OVERVIEW.md /tmp/oa-0049-overview.bak
cp docs/specs/ARCHITECTURE.md /tmp/oa-0049-arch.bak
uv run spec render --specs-root docs/specs
uv run spec graph --specs-root docs/specs
diff /tmp/oa-0049-overview.bak docs/specs/OVERVIEW.md
diff /tmp/oa-0049-arch.bak docs/specs/ARCHITECTURE.md
uv run spec graph --specs-root docs/specs --check

echo
echo "✅ Spec-0049 End-to-end authentication pass: only winner + nil unlabeled Tore each other up. + resume Zero new claims (repeated evidence available above)."
