#!/usr/bin/env bash
# Spec-0016 peer-to-end test boot script: add a new comment to the issue page  → andent awareness  →  send replier  →  to the issue with a signature return.
# Extend the "New Human Review Signed Reply" closed loop from PR to issue page (issue #149: Just answer, do not solve).
#
# Form description (evidence layer, philosophy 8): This group is** a back-end ** (issues for vigil subdivision 2), none
# Program-facing frontend navigable; self-checked tool list: Playwright / Chrome DevTools MCP not available, therefore no browser e2e, continue
# Offline certainty (a fake GitHub + fake agent's tick status machine asserted that Spec-0061/0065). True auto-smoking smoke
# (`oa vigil` received a signed response after adding comments on the genuine warehouse issue) as a result acceptance in the Phase-3 verification/runbook record, without plugging in a script.
#
# Usage:
#   bash scripts/e2e-spec-0016-issue-comment-agent-reply.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/4] Offline certainty verification (%2)lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/4] identity/state/replier/context/vigil/cli issue Reply to contract single test"
uv run --extra dev pytest -q \
  tests/test_identity_issue_reply.py \
  tests/test_runtime_state_issue_cursor.py \
  tests/test_agents_replier_issue.py \
  tests/test_runtime_context_issue_reply.py \
  tests/test_recipe_vigil_issue_reply.py \
  tests/test_cli_issue_reply.py

echo
echo "==> [3/4] spec Verify + Generating without drift"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/4] Close the door and check:ready None-PR issue New human commentary. → Pie. replier → Signing Return → Untriggered"
uv run --extra dev python - <<'PY'
"""Spec-0016 Executable version of closed loop: false GitHub(RAM)+ False backend(Scriptization) replier Output)+ True vigil(none change).

Only replacements**Outside world**：GitHub Read & Writeissue   And that’s true   agent Subprocess (in exchange for a script-based vomiting) JSON False
backendIt’s still only going through. GitHub Talk.`_sense` / `_classify` / `_do_reply` / `_do_reply_issue` /
identity It’s all signed and written.**Original production code**。
"""

import sys
import tempfile
import types
from pathlib import Path

from openagents.recipes import vigil
from openagents.runtime.state import RuntimeState
from openagents.utils import github, identity

ISSUE = 149
AGENT_ID = "oa-e2e"
CLOCK = ["2026-07-15T12:00:00Z"]


def tick_stamp(suffix):
    return f"2026-07-15T12:{suffix}Z"


# ---------------------------------------------------------------------------------------------
# Fake GitHub: A ready, not yet PR issue, can be added to the comment stream. Angent and the watch can only talk through it.
# ---------------------------------------------------------------------------------------------
class Hub:
    def __init__(self):
        self.labels = {"openagents", "ready"}  # Accessed
        self.comments = []  # list[(body, created_at)]
        self._machine_seq = 30  # Single-tone increment minute stamp for machine return (avoids disruption of the same second line) max (Renewed)

    def add_comment(self, *, body, created_at):
        self.comments.append((body, created_at))

    def next_machine_stamp(self):
        self._machine_seq += 1
        return f"2026-07-15T12:{self._machine_seq:02d}:00Z"


HUB = Hub()


def fake_get_issue(*, number):
    return github.Issue(ISSUE, "Support codex", "Jean. openagents Compatibility codex Backend", sorted(HUB.labels))


def fake_list_blocked_by(*, number):
    return []


def fake_pr_for_branch(*, branch):
    return None  # Not yet. PR


def fake_list_issue_comments(*, number):
    return [
        github.Comment(id=f"c{i}", author="alice", body=body, created_at=at,
                       author_association="NONE" if identity.parse_agent_id(body=body) is None else "OWNER")
        for i, (body, at) in enumerate(HUB.comments)
    ]


def fake_issue_comment(*, number, body):
    HUB.add_comment(body=body, created_at=HUB.next_machine_stamp())


for name, impl in {
    "get_issue": fake_get_issue,
    "list_blocked_by": fake_list_blocked_by,
    "pr_for_branch": fake_pr_for_branch,
    "list_issue_comments": fake_list_issue_comments,
    "issue_comment": fake_issue_comment,
}.items():
    setattr(github, name, impl)


# Fake: replier spits a question-and-answer JSON when sent.
class FakeBackend:
    def run(self, *, work_dir, task, context):
        assert "Only answer questions" in task and "No code changes" in task, "issue replier Unused ISSUE_PROMPT”Assisting the code.”"
        assert "branch" not in task, "issue replier The hint is mixed. PR Language branch"
        return types.SimpleNamespace(
            summary='{"reply": "Roger, I understand that the back end is abstract, and it’s available. codexRight?", "resolved": false}'
        )


WORK = Path(tempfile.mkdtemp(prefix="oa-0016-e2e-"))
STATE = RuntimeState(path=WORK / "runtime-state.json")


def check(label, condition, detail=""):
    if not condition:
        print(f"✗ {label}{(' —— ' + detail) if detail else ''}")
        sys.exit(1)
    print(f"  ✓ {label}")


# ---- The assertion. 1：ready None-PR issue The latest is the unsigned Human Review. → _sense Judgement latest_comment_is_ours=False → reply ----
HUB.add_comment(body="Supplement: Can you support it? codex？", created_at=tick_stamp("10:00"))
# _sense needs config.stages - Make a minimum config (no skip, pure agent face).
from openagents.utils import agent_config

CONFIG = agent_config.AgentConfig(
    version=1,
    agents=agent_config.AgentPolicy(backends={}),
    stages=agent_config.StagePolicy(owners={}),
    release=agent_config.ReleasePolicy(),
    interval=1,
    base="main",
    labels=["openagents"],
    repos=[],
)
observed = vigil._sense(config=CONFIG, subject=f"issue:{ISSUE}")
facts = observed.facts
check("① ready None-PR issue：pr_number Yes NoneLet’s go. issue (in millions of dollars)", facts.pr_number is None)
check("① The latest is an unsigned human review. → latest_comment_is_ours=False", facts.latest_comment_is_ours is False)
verdict = vigil._classify(facts=facts, in_flight=False)
check("① _classify Judgement ACTIONABLE:reply”not solve）",
      verdict.kind == vigil._ACTIONABLE and verdict.action == vigil._ACT_REPLY,
      f"{verdict.kind}/{verdict.action}")

# ---- asserted 2: _do_reply recier  →  post_signed_comment_on_issue falls issue, with the example ----------
reply = vigil._do_reply(
    backend=FakeBackend(), state=STATE, work_dir=WORK, facts=facts, agent_id=AGENT_ID
)
check("② replier I’m just saying one thing.", "codex" in reply)
latest_body, _ = HUB.comments[-1]
check("② Reply issue_comment   To the end   issue（gh issue comment Path)", "Abstract the backend as to which to insert" in latest_body)
check("② Reply with this instance signature <!-- openagents:agent=… -->",
      identity.parse_agent_id(body=latest_body) == AGENT_ID, latest_body)
check("② issue The landmark has been pushed to the human comment.", STATE.get_issue_cursor(number=ISSUE) == tick_stamp("10:00"))

# ---- asserts 3: Run a tick again -- the latest comment has been signed by our side latest_comment_is_ours True  →  do not repeat the return (untriggered) --
count_before = len(HUB.comments)
observed2 = vigil._sense(config=CONFIG, subject=f"issue:{ISSUE}")
check("③ We’ll get a new one after the return. → _latest_is_ours True", observed2.facts.latest_comment_is_ours is True)
verdict2 = vigil._classify(facts=observed2.facts, in_flight=False)
check("③ branch②Ceasefire: no more sentences reply  Falling in   solve）", verdict2.action == vigil._ACT_SOLVE)
# Even if _do_reply is directly re-tuned (the human comment has been pushed) there is no new response.
vigil._do_reply(backend=FakeBackend(), state=STATE, work_dir=WORK, facts=observed2.facts, agent_id=AGENT_ID)
check("③ Non-starting death cycle: the cruise sign is over → No new human comment → Zero New Message",
      len(HUB.comments) == count_before, f"{len(HUB.comments)} vs {count_before}")

# ---- asserts that the manual exit identity.post_signed_comment_on_issue is also signed off issue ----------------------
before = len(HUB.comments)
identity.post_signed_comment_on_issue(number=ISSUE, body="I’ll make it up to you manually.", agent_id="oa-manual")
check("④ Manual exit post_signed_comment_on_issue Fall issue + Sign",
      len(HUB.comments) == before + 1
      and identity.parse_agent_id(body=HUB.comments[-1][0]) == "oa-manual")

print("✓ Spec-0016 All go through the closed loop.→replyClassification→Signing Return→Untriggered→Manual exit)")
PY

echo
echo "==> grep anchor:issue Original language in book + reply branch②It’s... issue Sub-connection"

fail() {
  echo "✗ Organisation$1" >&2
  exit 1
}

# Bottom gh Read/ Write Original Exists, Direct Re-use (github.py zero change) - Issue Signing/Write Only One Level on Aidity.
grep -q "def new_human_comments_on_issue" openagents/utils/identity.py \
  || fail "identity Missing new_human_comments_on_issue（issue The page is self-triggered."
grep -q "def post_signed_comment_on_issue" openagents/utils/identity.py \
  || fail "identity Missing post_signed_comment_on_issue（issue (Signed) Zeinobia"
grep -q "def get_issue_cursor" openagents/runtime/state.py \
  || fail "state Missing get_issue_cursor（issue Comment on the cursor, independent naming space)"
grep -q "issue_cursors" openagents/runtime/state.py \
  || fail "state issue Free Namespace Key without Cursor issue_cursors(with cursors The key crashes and repeats the post."
grep -q "ISSUE_PROMPT" openagents/agents/replier.py \
  || fail "replier Missing ISSUE_PROMPT（issue Only answer the question and change the code)"
grep -q "def for_issue_reply" openagents/runtime/context.py \
  || fail "context Missing for_issue_reply（issue Reply to Placeholder"
grep -q "_do_reply_issue" openagents/recipes/vigil.py \
  || fail "vigil Missing _do_reply_issue（reply branch②It’s... issue (as at 31 December 2002)"

# ISSUE_PROMPT must** have ** ** brancy,** no change ** code branch (issue #149: do not solve it if you answer).
uv run --extra dev python -c "
from openagents.agents import replier
tmpl = replier.ISSUE_PROMPT.template
assert '\$branch' not in tmpl, 'ISSUE_PROMPT I’m in. PR Language \$branch'
assert 'Only answer questions' in tmpl and 'No code changes' in tmpl, 'ISSUE_PROMPT I didn’t say that I was just gonna answer the question and not change the code.'
assert replier.ISSUE_PROMPT is not replier.PROMPT, 'issue/PR The hints must be split.'
" || fail "ISSUE_PROMPT Semantics Not Conform (Incl. branch / No answer or change of code / with PR   I’m not even gonna be home  "

# _sense only activates latest_comment_is_ours for no-PR issue (without ready return entry) when ready.
grep -q "if _LABEL_READY in labels:" openagents/recipes/vigil.py \
  || fail "vigil _sense Not put issue reply Activate door control ready(Not available) ready It’s time to go. admitter）"

echo "✓ grep All anchor points pass:issue Copy Signing Read/Write + Independent Curve + issue A hint to break up. + reply branch②issue Expenditure + ready Door control."
echo
echo "✅ Spec-0016 Offline e2e All green."
