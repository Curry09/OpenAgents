#!/usr/bin/env bash
# Spec-0017 End-to-end test start script: PR Life Cycle (create/ready/merge) decentralized agent - draft to first-class fact
# Love-triggered auto-corrected + merge action decentralizedr agent + irreversibly merge hardlocks.
#
# Proof that the architecture contract was set up on the offline certainty chain (incent, see spec §e2e):
#   - (1) The completion certificate for the deliver agent contains "PR non-draft" (reversion to it) - contract single test tests/test_agents_deliver.py;
#   - (2) steady state recile treat is_draft as a 1 dimensional of each tick check: a deleved but still draft green+approved
#     PR Yes.**One claim.**I'm going to go first. _ACT_READY Revert github.mark_ready）Again. merge——draft Self-healing branch**Strictly in the row.
#     Before the merge branch** (no PR is draft; merge:human when people get a tacted, direct PR-Close)
#     #168 Dead corner;
#   - (3) Merger action decentralized, but the "Clean green + report-approved: <head Sha7>@head" is unreversible red line of certainty
#     gates.assert_merge_allowed: Do not release the gate  →  Never send the merger, never merge unheard code.
#
# Form description (evidence layer, philosophy 8): This group is** pure backend + agent hint**, no produd-facing frontend to navigate;
# Self-checked tool list: Playwright / Crope DevTools MCP is not available, so no browser e2e is set, and offline certainty is used (fake GitHub+)
# fake agent's reconcile asserted + contract/ hard-lock single test + grep anchor. Real auto-smoking smoke (oa vigil runs through the real warehouse)
# As a result, the PR directly not draft, residual draft can be corrected in the next round) is accepted in the Phase-3 humans/runbook
# Record, do not plug into this offline script.
#
# Usage:
#   bash scripts/e2e-spec-0017-pr-lifecycle-delegated-to-agent.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> [1/5] Offline certainty verification (%2)lint + format）"
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .

echo
echo "==> [2/5] Quickshot/prompt/Hardlock./Branch Table Targeted contract single measure"
uv run --extra dev pytest -q \
  tests/test_utils_github_vigil.py \
  tests/test_agents_deliver.py \
  tests/test_agents_merger.py \
  tests/test_runtime_gates.py \
  tests/test_recipe_stages.py \
  tests/test_recipe_vigil.py \
  tests/test_recipe_vigil_act.py

echo
echo "==> [3/5] spec Verify + Generating without drift"
uv run spec validate
uv run spec graph --check

echo
echo "==> [4/5] grep Ocupies: Decentralization of life cycle straight (Presentation)_do_solve None mark_ready、stages.merge No Naked merge_pr）"
uv run --extra dev python - <<'PY'
"""Source-level anchor: Whether the ”one-time certainty straightness” has been delegated to an enforceable assertion (which is redundant with single measurements)"""

import ast
from pathlib import Path


def _func_node(path, name):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{path} No function found {name}")


def _calls(node):
    """The function is all shapes like `mod.attr(...)` , and then click the name (or the name)AST, so it won’t be commented on/Document string with textual errors."""
    names = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            base = sub.func.value
            if isinstance(base, ast.Name):
                names.add(f"{base.id}.{sub.func.attr}")
            else:
                names.add(sub.func.attr)
    return names


solve_calls = _calls(_func_node("openagents/recipes/vigil.py", "_do_solve"))
assert "github.mark_ready" not in solve_calls, "_do_solve Still certain. github.mark_ready”Return to return deliver agent）"
print("  ✓ _do_solve No more straight. github.mark_ready(Renewed decentralization) deliver agent）")

merge_calls = _calls(_func_node("openagents/recipes/stages.py", "merge"))
assert "github.merge_pr" not in merge_calls, "stages.merge Still nudity. github.merge_pr(Consolidation should be decentralized) merger agent）"
assert "gates.assert_merge_allowed" in merge_calls, "stages.merge Not before. gates.assert_merge_allowed Hardlock."
assert "engine.run_agent" in merge_calls, "stages.merge Not yet. engine.run_agent Pie. merger agent"
print("  ✓ stages.merge No Naked github.merge_prLet’s go through the hard gate before we send them. merger agent")

ready_calls = _calls(_func_node("openagents/recipes/vigil.py", "_do_ready"))
assert "github.mark_ready" in ready_calls, "_do_ready Due certainty github.mark_ready（level-triggered Safety net)"
print("  ✓ _do_ready Determination github.mark_ready（level-triggered   The safety net  ")
PY

echo
echo "==> [5/5] reconcile Go check:draft green+approved PR - I’m not sure.merge:human Let’s get this straight. park(Manafe) draft PR）"
uv run --extra dev python - <<'PY'
"""Spec-0017 §e2e implementable version of the report: fake GitHub(RAM)+ False merger agent + True vigil（sense/classify/_act I’ll leave you to it.

Only replacements**Outside world**：GitHub Read and write + merger That time. LLM Call (replaced as script-based fakes) agentIt’s still only going through.
GitHub Talk.`_sense` / `_classify` / `_fingerprint` / `_reconcile` / `_do_ready` / `_do_merge` /
`stages.merge` / `gates.assert_merge_allowed` It’s all over.**Original production code**。
"""

import io
import sys
from contextlib import redirect_stderr
from datetime import UTC, datetime
from pathlib import Path
import tempfile

from openagents.recipes import stages, vigil
from openagents.runtime import engine
from openagents.runtime.state import RuntimeState
from openagents.utils import agent_config, github, identity

NOW = datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC)
HEAD = "300" + "a" * 37  # 40 bits head；sha7 = "300aaaa"
SHA7 = HEAD[:7]
PR = 300


class World:
    """A variable memory PR World. Naked. PR(Stips are not with openagents/issue- Prefix)→ subject `pr:300`。"""

    def __init__(self):
        self.is_draft = True  # Delivery but residual draft（deliver The shot off)
        self.labels = {f"review-approved:{SHA7}"}  # reviewer Triald, ruling binding current head
        self.merged = False
        self.open = True
        self.comments = []  # (body, at)


W = World()
ACTS = []  # `_act` Every time they call me a note, verdict.action —— ”Assume.”ready Strictly Prior to merge」


def spy_act(**kw):
    ACTS.append(kw["verdict"].action)
    return real_act(**kw)


real_act = vigil._act
vigil._act = spy_act


def fake_pr_snapshot(*, pr_number):
    state = "MERGED" if W.merged else ("OPEN" if W.open else "CLOSED")
    return github.PRSnapshot(
        number=pr_number,
        state=state,
        head_sha=HEAD,
        labels=tuple(sorted(W.labels)),
        mergeable="MERGEABLE",
        merge_state_status="CLEAN",
        head_pushed_at="2026-07-15T11:00:00Z",
        is_draft=W.is_draft,
    )


def fake_mark_ready(*, pr_number):
    W.is_draft = False  # Retrospect:level-triggered Safety net, hold the residue. draft Top


def fake_run_agent(agent_module, *, backend, **kw):
    name = agent_module.__name__.rsplit(".", 1)[-1]
    if name == "merger":
        W.merged = True
        W.open = False
        return {"merged": True, "summary": "Merged"}
    raise AssertionError(f"I’m not supposed to be on the road. {name} agent")


FAKES = {
    "list_issues": lambda *, labels, state="open": [],
    "list_open_prs": lambda: [github.PR(PR, f"u/{PR}")] if W.open else [],
    "pr_head_branch": lambda *, pr_number: f"iter/{pr_number}",  # Naked. PR(Not with issue Prefix)
    "pr_snapshot": fake_pr_snapshot,
    "check_snapshot": lambda *, pr_number: github.CheckSnapshot("pass", 3, "2026-07-15T11:00:00Z"),
    "list_comments": lambda *, pr_number: [
        github.Comment(i, "bot", body, at) for i, (body, at) in enumerate(W.comments)
    ],
    "post_comment": lambda *, pr_number, body: W.comments.append((body, "2026-07-15T11:30:00Z")),
    "mark_ready": fake_mark_ready,
    "merge_pr": lambda *, pr_number, method="merge": (_ for _ in ()).throw(
        AssertionError("stages.merge I shouldn’t have been naked. github.merge_pr——Consolidation of delegation of authority merger agent")
    ),
    "add_label": lambda *, pr_number, name: W.labels.add(name),
    "remove_label": lambda *, pr_number, name: W.labels.discard(name),
    "ensure_label": lambda *, name, description="": None,
    "close_issue": lambda *, number: None,
}
for name, impl in FAKES.items():
    setattr(github, name, impl)
engine.run_agent = fake_run_agent
identity.post_signed_comment = lambda *, pr_number, body, agent_id: W.comments.append(
    (identity.sign(body=body, agent_id=agent_id or "oa"), "2026-07-15T11:30:00Z")
)


def build_config(*, merge_owner):
    # e2e:skip pegs the evidence into a head (e2e) and review stays on ant, real reported-approved label;
    # Merge owner is switched by scene (agent = decentralized merger / human = stop at gate and others).
    return agent_config.AgentConfig(
        version=1,
        agents=agent_config.AgentPolicy(backends={}),
        stages=agent_config.StagePolicy(owners={"e2e": "skip", "merge": merge_owner}),
        release=agent_config.ReleasePolicy(),
        interval=1,
        base="main",
        labels=["openagents"],
        repos=[],
    )


def run_once(config, work):
    buffer = io.StringIO()
    with redirect_stderr(buffer):
        vigil.run_vigil(
            backend=None,
            state=RuntimeState(path=work / "runtime-state.json"),
            work_dir=work,
            config=config,
            once=True,
            concurrency=1,
            agent_id="oa-e2e",
            now_fn=lambda: NOW,
        )
    return buffer.getvalue()


def check(label, cond, detail=""):
    if not cond:
        print(f"✗ {label}{(' —— ' + detail) if detail else ''}")
        sys.exit(1)
    print(f"  ✓ {label}")


# ---- scene A：merge:agent —— delivered But... draft It's... green+approved PR First, first, first, first, then, then, then, again. merger CUT ----------
W = World()
ACTS.clear()
work_a = Path(tempfile.mkdtemp(prefix="oa-0017-a-"))
run_once(build_config(merge_owner="agent"), work_a)
check("A draft Self-healing is strictly in line. merge Before:ACTS == [ready, merge]", ACTS == ["ready", "merge"], str(ACTS))
check("A The transition occurs before the merger:merge When you land, PR Cannot initialise Evolution’s mail component. draft(Any) PR It’s not here. draft I’m not sure.", not W.is_draft)
check("A Merger action delegated merger agent(Locking off)→ PR Already merged", W.merged and not W.open)

# ---- scene B:merge:human - Correct first, Park needs-human: People get ** ** *Reformed and directly ** PR --------------
W = World()
ACTS.clear()
work_b = Path(tempfile.mkdtemp(prefix="oa-0017-b-"))
run_once(build_config(merge_owner="human"), work_b)
check("B Turn it back and touch it. merge Support:ACTS == [ready, merge]", ACTS == ["ready", "merge"], str(ACTS))
check("B People get what they want.**Not draft** PR(Reverse prefix) human Merge Actions, Close #168 People are being... draft   The wall  ", not W.is_draft)
check("B merge:human → Stop at the gate. needs-human、**Never automatically.**", "needs-human" in W.labels and not W.merged)

# ---- scene C: Merge the hard-barrel pending —— head Forward mover review-approved The award is set aside. → The gate is not going to merge the unheard code. ------------
from openagents.runtime import gates  # noqa: E402

W = World()
W.is_draft = False  # It’s back up. The rest is green.
try:
    gates.assert_merge_allowed(pr_number=PR, head_sha="f" * 40)  # head Move forward → label sha I don’t know.
    check("C Hardlock response. head Old award thrown forward GateError", False)
except gates.GateError:
    check("C Merge hard-lock ties head sha：head The award is annulled. → Throw! GateErrorNever merge unreviewed code", True)

print("\n✅ Spec-0017 Offline e2e All green:PR Decentralization of the life cycle agent + draft level-triggered Self-healing. + Merge the hard-barded.")
PY

echo
echo "✅ Spec-0017 End-to-end offline verification pass."
