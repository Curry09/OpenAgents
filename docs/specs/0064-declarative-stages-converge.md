---
number: "0064"
title: "Consolidate recipes into vigil+issue: declarative stages YAML defines agent/human/skip stage ownership"
issue: 161
slug: declarative-stages-converge
summary: "Consolidate the recipes layer from 6→3 (stages/vigil/backfill), and consolidate human-facing entry points into vigil+issue+backfill-rfc+release. Use a single declarative .openagents/openagents.yml (agents/three-state stages/release) as the single source of truth for “which agents to use + who controls each gate.” Extract stages into independent free functions outside the Vigil class, routed by run_vigil according to the stages policy, and connect the CI/e2e/review gates to a unified rejection loop: “failure→dispatch implementer to iterate→re-enter from conflict on the next round.”"
e2e:
  intent: "Prove that the architectural contract of “declarative stages policy routing + recipes-layer convergence from 6→3” holds in an offline deterministic flow—within the same issue loop, supplying different .openagents/openagents.yml files allows the three-state policies loaded by agent_config to actually drive run_vigil branches (agent→call the stage function / human→pause and wait for a human / skip→skip); the “no zero gates” guard blocks review:skip+merge:agent, and conflict/merge:skip is rejected; CI/e2e/review failures dispatch the implementer to iterate through a unified loop, with the next round re-entering at conflict; deterministic hard gates (head advancement/evidence stamps/round_cap) remain active at all times and are outside the control of stages; after convergence, recipes/ contains only stages/vigil/backfill, and the human-facing commands are only vigil/issue/backfill-rfc/release + the hidden reply-comment."
  method: "Form: backend-only configuration + orchestration + CLI convergence, with no navigable product-facing frontend; the self-check tool list contains no Playwright /\nChrome DevTools MCP, so no browser e2e is planned; use offline deterministic testing instead (the same approach as Spec-0060/0061/0062):\n1. Targeted configuration-layer pytest tests (fake YAML strings, without touching real repositories/networks): agent_config parses agents/stages/release/\n   defaults/repos + full fallback to built-in defaults + per-repository override merging; validate the allowed values for each gate under the three-state model (conflict/merge reject\n   skip, rfc allows only agent/skip, and hard-gate names in stages are rejected outright); the “no zero gates” guard rejects review:skip+merge:agent;\n   rfc:skip emits an explicit warning.\n2. Targeted orchestration-layer pytest tests (a fake backend supplies canned structured verdicts, without touching real LLMs/networks/repositories): assert the three\n   agent/human/skip branches in run_vigil according to the injected config; the merge pipeline follows the conflict→ci→e2e→review→merge order;\n   CI/e2e/review failure→dispatch implementer→re-enter at conflict in the next round; stages cannot disable deterministic hard gates.\n3. grep anchors (e2e script): recipes/ contains only {stages,vigil,backfill,__init__}.py; zero matches across the repository for bare imports of the deleted\n   recipes (solve_issue/merge_pr/poll_comments/rfc_lifecycle/fleet) or agents.planner;\n   all nine atomic functions in stages take parameters explicitly (no positional arguments, no private defaults); ensure a closed loop for signing agent comment replies\n   (identity.post_signed_comment repairs a missing signature with an edit, rather than merely warning).\n4. Real autonomous-loop smoke test (dogfood, Phase-3 human acceptance / runbook, not a deterministic CI gate): oa vigil uses a minimal\n   openagents.yml (rfc:skip + merge:human) to complete one issue→PR flow, with all PR CI checks green—record this in the runbook as outcome acceptance (Principle 8),\n   without putting it into the offline script.\nScript: scripts/e2e-spec-0064-declarative-stages-converge.sh (ruff check + ruff format --check +\ntargeted pytest tests + grep anchors), collected by the PR e2e signpost.\n"
tasks:
  - id: T1
    title: "Configuration layer: .openagents/openagents.yml schema + loader"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/agent_config.py
      - tests/test_agent_config.py
    scope: "Create utils/agent_config.py: reuse fleet_config's ruamel.yaml+jsonschema declarative validation to parse version/agents/stages/release/defaults/repos (the entire file may be omitted, with everything falling back to built-in defaults), producing resolved dataclasses (AgentPolicy/three-state StagePolicy/ReleasePolicy/RepoPlan). Validate allowed values for each gate individually (conflict/merge reject skip, rfc allows only agent/skip, and hard gate names in stages are rejected outright), add a cross-field guard prohibiting “zero gates” (reject review:skip+merge:agent), issue an explicit warning for rfc:skip, and merge per-repository overrides. Additive, with no changes to consumers."
    acceptance: "Hermetically testable (feed in YAML strings and assert parsing results/validation errors, without accessing real repositories or the network); omitting the entire file→all defaults; reject the review:skip+merge:agent combination; reject conflict/merge:skip; reject hard gate names in stages; emit a warning for rfc:skip; per-repository override merging takes effect; ruff passes."
  - id: T2
    title: "Extract the nine stages into independent free functions outside the Vigil class: recipes/stages.py"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/stages.py
      - tests/test_recipe_stages.py
    scope: "Extract the nine stages triage/rfc/implement/review/conflict/ci/e2e/deliver/merge into independent free functions outside the Vigil class, each explicitly accepting backend/state/ctx (positional arguments prohibited; defaults prohibited for private functions). Judgment stages (triage→triager, rfc→drafter, review→reviewer) dispatch existing agents; mechanical stages (ci/e2e reading github checks/evidence stamps, conflict/deliver performing git delivery, merge performing github merges) use utils/gates. Consolidate planner+drafter in the rfc stage into a single drafting function (drafter takes over; leave planner dead code for removal in T6). Additive: reproduce the code from solve_issue/merge_pr/poll_comments verbatim as atomic functions, with zero changes to the old files."
    acceptance: "Each of the nine atomic functions is hermetically testable (a fake backend supplies canned judgments, without accessing real LLMs/the network/repositories); each function accepts explicit parameters, allows no positional arguments, and private functions have no defaults; the rfc stage has a single drafting function that depends only on drafter; ruff passes."
  - id: T3
    title: "run_vigil policy-based routing and orchestration + CI/e2e/review rejection loop"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - tests/test_recipe_vigil.py
    scope: "Break up the Vigil class into the free function run_vigil(*, backend, state, work_dir, config, ...): route according to T1's three-state stages policy, replacing solve_issue's hard-coded plan→impl→review→deliver sequence—check the owner for each configurable stage (agent→call the T2 stage function / human→mark needs-human and stop to wait for a human / skip→skip). Run the merge pipeline in conflict→ci→e2e→review→merge order, and connect the CI/e2e/review gates to a unified loop: “failure→dispatch implementer to iterate→re-enter the pipeline from conflict on the next round” (not an in-place retry). Obtain the agent→backend mapping from config.agents. Fold fleet's multi-repository handling into one run_vigil invocation per repository. Deterministic hard gates (head advancement/evidence stamps/round_cap) are always active and are not governed by stages."
    acceptance: "Policy routing is hermetically testable (inject the three config states and assert the agent/human/skip branches); cover conflict→ci→e2e→review→merge ordering + the three-gate rejection loop; before reading CI, conflict first checks that mergeable is not CONFLICTING/DIRTY/UNKNOWN; stages cannot disable hard gates; ruff passes."
  - id: T4
    title: "Separate backfill-rfc as a path-driven recipe: recipes/backfill.py"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/backfill.py
      - tests/test_recipe_backfill.py
    scope: "Extract backfill_rfc from rfc_lifecycle into the independent recipe recipes/backfill.py (it does not enter the issue loop and is orthogonal to vigil's discovery stage): reuse the T2 stages rfc drafting primitive + drafter's backfill mode to scan existing code paths, infer a spec, and open a draft PR (implementation first/design afterward). Additive."
    acceptance: "Hermetically testable (fake backend + fake code paths, without accessing real repositories); does not trigger vigil's discovery stage; reuses stages.rfc drafting instead of duplicating its implementation; ruff passes."
  - id: T5
    title: "Consolidate the CLI surface into four commands + hidden reply-comment + hardened post-signing verification"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/utils/identity.py
      - tests/test_cli_new_stack.py
    scope: "Consolidate human-facing entry points into four commands: vigil/issue/backfill-rfc/release. Remove the nine commands rfc/refine-rfc/implement/iterate/solve/poll/watch/vigil-all/fleet (fold them into vigil, and rewire the cli to recipes.run_vigil); demote reply-comment to a hidden internal command (still using utils.identity.post_signed_comment); vigil/issue read .openagents/openagents.yml (through the T1 loader), while --hold/--skip/--base/--interval remain available as per-invocation overrides; release remains a deterministic action wired directly to utils.release (no agent), and issue is wired directly to github.create_issue. Harden identity.post_signed_comment into “sign replies + verify synchronously afterward and use edit to repair missing signatures (warning alone is insufficient),” completing the loop that prevents self-triggered cycles (constraint ③)."
    acceptance: "The human-facing commands are only vigil/issue/backfill-rfc/release, plus hidden reply-comment; parsing and dispatch work for all oa commands; YAML as the single source of truth coexists with per-invocation flag overrides; missing signatures are repaired via edit (not merely warned about); no routing remnants for the old nine commands; ruff passes."
  - id: T6
    title: "Remove 5 old recipes + merge planner + consolidate test stubs + regenerate docs"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/solve_issue.py
      - openagents/recipes/merge_pr.py
      - openagents/recipes/poll_comments.py
      - openagents/recipes/rfc_lifecycle.py
      - openagents/recipes/fleet.py
      - openagents/agents/planner.py
    scope: "Remove the 5 old recipes (solve_issue/merge_pr/poll_comments/rfc_lifecycle/fleet, whose logic has been incorporated into T2 stages.py / T3 vigil.py / T4 backfill.py) + remove agents/planner.py (merged into drafter). Also consolidate the test stubs that directly test these old modules (test_recipe_solve_issue/merge_pr/poll_comments/rfc_lifecycle/fleet, etc., whose behavior is already covered by test_recipe_stages/vigil/backfill) and the old commands referenced by dogfood/runbook; regenerate OVERVIEW/ARCHITECTURE using spec render/graph. Remove the old code only after all CLI wiring has been updated in T5."
    acceptance: "recipes/ contains only stages/vigil/backfill/__init__; a repository-wide grep finds zero bare imports of the deleted recipes or agents.planner; the full pytest suite passes; spec validate reports no errors; OVERVIEW/ARCHITECTURE are drift-free."
---

# 0064 · Consolidate recipes into vigil+issue: declarative stages YAML defines agent/human/skip stage ownership

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG); the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

`openagents/recipes/` currently has 6 modules (`fleet`/`merge_pr`/`poll_comments`/`rfc_lifecycle`/`solve_issue`/`vigil`), and the CLI exposes 16 subcommands. Among these commands, `rfc`/`refine-rfc`/`implement`/`iterate`/`solve`/`poll`/`watch`/`vigil-all`/`fleet` are effectively “manual single-step versions” of what `vigil` does automatically each round. “Which agents run, which backend each agent uses, and who controls each stage” are hardcoded across individual recipes and the `--hold`/`--skip` flags in `gates.py`, with no single source of truth. `review` is embedded in the `solve_issue` for loop, and `triage` is embedded in methods of the `Vigil` class; stages cannot be addressed individually.

This spec makes three interlocking changes: **(1) Consolidate user-facing entry points into four orthogonal triggers: `oa vigil` (the autonomous loop) + `oa issue` (create work) + `oa backfill-rfc` (path-driven retrospective specification) + `oa release` (repository-level releases)** (the other nine commands exposing slices of the automation loop are folded into `vigil`, and `reply-comment` becomes a hidden internal command); **(2) Use a declarative YAML file, `.openagents/openagents.yml`, as the single source of truth for “which agents to use + who controls each gate”**—the `agents` section declares which backend each role uses (principle 2, decentralization: the same project can mix Claude Code / Codex / nexau), while the `stages` section declares each stage’s ownership using the three states `agent`/`human`/`skip`; the loader validates allowed values for each gate and enforces “no zero-gate configurations”; **(3) Extract each stage into an independent free function outside the `Vigil` class** (`recipes/stages.py`), compose them through a single **orchestration point that routes according to the `stages` policy**, `run_vigil` (`recipes/vigil.py`), and connect the CI/e2e/review gates to a unified feedback loop: “failure → dispatch the implementer to iterate → re-enter the pipeline from conflict in the next round.” After consolidation, the `recipes/` layer shrinks from 6 files to 3 (`stages.py`/`vigil.py`/`backfill.py`).

## Motivation

**Current state (restated here without relying on cross-spec references)**: Spec-0060/0061/0062/0063 have established four layers in the new stack—`agents/` (Template prompts with no logic, such as `triager`/`drafter`/`reviewer`/`implementer`/`replier`/`deliver`), `recipes/` (pure control flow), `runtime/` (`engine.run_agent` + minimal hard gates in `gates.py` + `context`/`state`), and `utils/` (deterministic primitives such as `git`/`github`/`identity`/`fleet_config`/`release`). The old flat layer has been completely removed, and the two stacks have been unified. Currently, `recipes/` has 6 modules: `solve_issue` (a vertical slice for solving an issue: plan→impl→review→deliver), `merge_pr` (a merge-pipeline stage machine: mergeability preflight/CI/e2e evidence gate/review/merge + hold/skip short-circuiting), `poll_comments` (fetch new human comments→replier→signed replies), `rfc_lifecycle` (five entry points: `start_rfc`/`backfill_rfc`/`refine_rfc`/`implement`/`iterate`), `vigil` (the `Vigil` class: discovery→triage→dispatch + calls to `poll_comments`+`merge_pr` during the monitoring phase of each round), and `fleet` (subprocess fan-out across multiple repositories). The CLI’s 16 commands connect directly to these modules.

**Four reasons**:

1. **Scattered entry points violate principle 1 (Occam)**—`rfc`/`refine-rfc`/`implement`/`iterate`/`solve`/`poll`/`watch`/`vigil-all`/`fleet` are all “manual single-step versions” of what `vigil` does automatically each round. Users must remember 9 commands for manual steps, imposing too much cognitive load. The high-level triggers users actually need are just three orthogonal actions: run the autonomous loop, submit an issue, and derive a spec from existing code at a path.

2. **Gate policies are one-off CLI flags with no single source of truth**—`--hold` (stop and wait for a human)/`--skip` (allow through as PASS) are scattered across `_HOLD_GATES=("spec","merge")`/`_SKIP_GATES=("ci","code","evidence","spec")` in `gates.py`. Every experiment requires remembering the flags, and no record persists across runs. There is no single place to see at a glance “who controls each gate in this project.”

3. **Which agents run and which backend each agent uses are hardcoded in recipes**—`backends/` currently contains only `claude_code`, but principle 2 requires that “different Agents in the same project may use different coding agents behind them, including both Claude Code and Codex, among others.” There is currently nowhere to declare “the implementer uses Codex, and the reviewer uses Claude Code.”

4. **Stages are not decoupled and cannot be addressed individually**—`review` is embedded in the `solve_issue` for loop, and `triage` is embedded in methods of the `Vigil` class. Also, the `planner` and `drafter` agents do the same job of “drafting a spec” (a remnant of the coexistence of the old and new stacks: `planner` came from demoting Spec-0060’s inline `_DRAFT_RFC_TASK` string, while `drafter` arrived later in Spec-0062 to take over drafting decisions for the five entry points; the two duplicate each other). If stages cannot be addressed individually, “who controls the gate” cannot be configured for them.

**The actual gap (this spec must close it)**: When CI fails, `merge_pr` currently only does `return {"reason": "ci"}`; when review returns REWORK, it only does `return {"reason": "review"}`—**it detects the problem but does not automatically dispatch the implementer to revise the work** (the old stack relied on manually sending it back with `iterate --reason ci`; that command disappears after consolidation). The monitoring phase of `vigil` also takes no action when it receives these events. The CI/e2e/review gates must be connected to a unified feedback loop: “failure → dispatch the implementer to iterate → re-enter the pipeline from conflict in the next round.” Otherwise, after the manual `iterate` command is consolidated away, the autonomous loop will spin at “reports errors but does not fix them.”

## Guide-level explanation

After consolidation, the user-facing mental model is: **four orthogonal commands + one optional YAML file**.

**Four commands**:

- `oa vigil` — The autonomous loop. Each round fetches label-gated issues from GitHub and reads `.openagents/openagents.yml` to determine “which agents run and who owns each stage,” then automatically executes the full loop: discovery→triage→(draft spec→implement→review→deliver)→monitoring (respond to comments + advance merges). The `rfc`/`implement`/`iterate`/`poll`/`watch`/`vigil-all`/`fleet` commands that must be entered manually today are all individual steps within one of its rounds and will no longer be listed separately.
- `oa issue` — A human proactively submits an issue to the repository (an independent action that creates work, connected directly to `github.create_issue`).
- `oa backfill-rfc <path>` — Path-driven retrospective specification: point at a section of existing code to derive a spec and open a draft PR (implementation first, design afterward). This is orthogonal to the issue-driven vigil loop—the discovery phase of vigil scans issues, not code paths that need documentation backfilled, so it has a separate entry point.
- `oa release` — A repository-level release action spanning issues (a human decides when to materialize the current HEAD of main as a version). It is a deterministic action with no agent, and it is not a pipeline stage for an individual issue, so it is configured as a separate top-level policy rather than included in `stages`.

`reply-comment` is retained but becomes a **hidden/internal command**—it is the only route for dispatched sub-agents (such as conflict-resolution agents) to post signed comment replies. Removing it would break the closed loop that prevents self-triggering loops (see Reference-level constraint ③), but users do not need to keep it in mind.

**One YAML file**—the entire `.openagents/openagents.yml` file is optional (everything falls back to built-in defaults). A minimal configuration for everyday use:

```yaml
version: 1
stages:
  rfc:   skip     # For small changes, bypass the RFC and implement directly (mark no-rfc intent; the loader emits an explicit warning)
  merge: human    # Pause merging and wait for human approval
```

A complete configuration declares “which backend each role uses” + “who owns each gate”:

```yaml
version: 1
agents:                          # Principle 2: the same project can mix different coding agents
  triager:     { backend: claude_code }
  drafter:     { backend: claude_code }   # Draft the spec (= the former planner, now merged)
  implementer: { backend: codex }         # Example: switch implementation to Codex
  reviewer:    { backend: claude_code }
stages:                          # agent=automation owns this gate | human=pause for a human | skip=do not establish this gate
  triage:   agent    # Whether work can be dispatched (human=pause for human approval on every new issue)
  rfc:      agent    # Draft the spec: agent | skip (skip=implement directly without writing it)
  conflict: agent    # Resolve conflicts through rebase: agent | human (cannot skip)
  ci:       agent    # CI gate: agent(red→automatically send back to implementer) | human(red→pause) | skip
  e2e:      agent    # End-to-end: agent | human | skip
  review:   agent    # Review PASS/REWORK: agent | human | skip
  merge:    human    # Merge control: agent(automatically merge when CI is green) | human (cannot skip)
release: manual      # Top-level policy, outside stages; auto=automatically materialize when main is green and there is no BLOCKED
defaults: { interval: 60, base: main, labels: [openagents] }
repos:               # Unified management of multiple repositories (absorbs fleet.yml; omit the entire section for a single repository)
  - path: .
  - path: ../other-repo
    base: develop
    stages: { merge: agent }   # Each repository can override individual stages
```

`--hold`/`--skip`/`--base`/`--interval` can still override YAML for a **single run**—“single source of truth” means consolidating declarative defaults in one place, not eliminating all flags.

## Reference-level explanation

### Boundary (carried forward from the previous four batches, identical word for word)

What stays in deterministic code (recipe control flow + `runtime.gates` hard gates + `utils` primitives) is **reading objective facts**: mergeability (the mergeable bit provided by GitHub), CI results (a check’s conclusion), e2e evidence stamps (whether head_sha matches), hold/skip matches, and claim-note expiration. What is delegated to agents is **subjective judgment**: whether an issue is clearly explained/whether it should be done (triager), what to write in the RFC body (drafter), whether this version can pass review (reviewer), what a comment is asking for (replier), and how to rebase to resolve conflicts (deliver). **The three `stages` states mean “who owns this gate,” not “who performs the check”**: `ci: agent` means “automation owns this gate—the check still objectively reads checks, and a red result automatically sends the work back to the implementer”; it does **not** mean asking an agent to judge whether CI passed.

### Configuration layer: `.openagents/openagents.yml` schema + loader (T1)

Follow the declarative validation pattern in `utils/fleet_config.py`, using `ruamel.yaml` + `jsonschema` Draft202012, and create `utils/agent_config.py`. The top-level keys `version`/`agents`/`stages`/`release`/`defaults`/`repos` are all optional (omit the entire configuration → use built-in defaults). The loader produces resolved dataclasses (`AgentPolicy`{role→backend}, `StagePolicy`{stage→three-state owner}, `ReleasePolicy`, `RepoPlan`) and performs the following:

- **Validate allowed values separately for each gate** (not every gate accepts all three states)—see the “Allowed values” column below. Invalid values (such as `merge: skip`, `conflict: skip`, `rfc: human`) produce a schema error.
- **Reject deterministic hard-gate names directly when they appear in `stages`**—hard-gate names from `gates.py`, such as `head-advanced`/`evidence-stamp`/`round-cap`, are not configurable stages; placing them in `stages` produces an error (reinforcing the separation of layers; see constraint ②).
- **Cross-field “no zero gates” guard**—reject combinations such as `review: skip` + `merge: agent` (+ CI allowing passage), which “blindly merge straight into main without review or testing” (analogous to the existing contradiction checks in `fleet_config`). A natural fallback is principle 5, “PRs require human review”—as long as `merge: human` is present, skipping agent review is defensible.
- **Explicit warning for `rfc: skip`**—skipping is allowed (it conflicts with principle 4, update the RFC before changing code), but the loader emits an explicit warning so that a global default does not silently disable the framework’s RFC selling point (constraint ①).
- **Merge per-repository overrides**—`repos[].stages` overrides individual stages in the top-level `stages` (following the defaults-merging pattern in fleet_config).

### Atomic stage functions: `recipes/stages.py` (T2)

Extract the nine stages into independent free functions outside the `Vigil` class, each **explicitly accepting backend/state/ctx** (following the CLAUDE.md conventions: “no positional arguments, no default values for private functions, and explicit arguments at call sites”):

| stage | Implementation | Policy point in `stages`? | Allowed values | Notes |
|---|---|---|---|---|
| `triage` | agent function (triager) | ✅ | agent/human/skip | Whether the issue can be assigned |
| `rfc` (draft spec) | agent function (drafter) | ✅ | agent/skip | Combine planner+drafter |
| `implement` | agent function (implementer) | ❌ Always agent | — | Write code according to the approved spec |
| `conflict` | agent function (deliver rebase) | ✅ | agent/human | Conflicts must be resolved; cannot skip |
| `ci` | Deterministic gate read (github check) | ✅ | agent/human/skip | agent=automatically send back on red; not “an agent judges CI” |
| `e2e` | Deterministic gate read + executor run | ✅ | agent/human/skip | Can be skipped independently (skip) |
| `review` | agent function (reviewer) | ✅ | agent/human/skip | PASS/REWORK |
| `deliver` | agent function (deliver git delivery) | ❌ Always agent | — | git delivery |
| `merge` | Deterministic action (github merge) | ✅ | agent/human | Cannot skip |

The `rfc` stage consolidates `planner`+`drafter` into a single drafting function (drafter already handles drafting decisions for all five modes; planner is redundant dead code, deleted in T6).

### Orchestration point: `run_vigil` policy routing + rework loop (T3)

Dissolve the `Vigil` class into a free function, `run_vigil(*, backend, state, work_dir, config, ...)`—once all stages explicitly accept their arguments, the class contains only “dependency packaging + the main loop,” with no substance left; breaking it apart better follows Occam’s razor. **Key point**: extracting functions is a necessary condition, not the goal. There must also be an **orchestration point that routes according to the `stages` policy**, replacing today’s hard-coded `plan→impl→review→deliver` in `solve_issue`—look up the owner for each configurable stage: `agent`→call the agent version of the stage function; `human`→stop at this gate, mark needs-human, and suspend until a human intervenes; `skip`→skip it. Extraction without composition still leaves nowhere to apply `review: skip`. Obtain the agent→backend mapping from `config.agents` (principle 2). Fold multi-repository `fleet` into “one `run_vigil` call per repository”; no class is needed.

**Finalized merge pipeline order**: `conflict → CI → e2e → review → merge`. Each gate = (detector) + (fixer on failure) + (re-entry from the top of the pipeline after the fix):

| Order | Gate | Detector | Send back to whom on failure | Skippable |
|---|---|---|---|---|
| ① | conflict / behind | Deterministic read of the mergeable field | deliver agent to rebase | No (prerequisite) |
| ② | CI/CD | Deterministic read of check conclusions | **Send back to implementer for rework** | skip ci |
| ③ | e2e | Deterministic read of the evidence stamp (or an actual run) | Send back to implementer for rework | ✅ Independently skippable |
| ④ | review | reviewer agent judgment (most expensive) | Send back to implementer for rework (REWORK) | skip code |
| ⑤ | merge | — (github merge) | — | hold=stop and wait for a human |

Three ordering principles: **cheaper checks first** (reading API fields < LLM review), **objective gates before judgment gates**, and **prerequisite dependencies first**. **Placing conflict before CI is not merely about cost; it is a hard dependency**: when a PR has conflicts (`mergeable=false` / `mergeStateStatus=DIRTY`), GitHub cannot create a merge ref, so `pull_request` CI has nothing to run against or has only stale head results → green/red CI results are untrustworthy while conflicts remain unresolved. Also, immediately after a push, when `mergeable=null` (asynchronous background computation)/`UNKNOWN`, neither a conflict determination nor trust in CI is possible; wait for the next round. Therefore, **before reading CI, first confirm that mergeable is neither CONFLICTING/DIRTY nor UNKNOWN/null** (the existing `gates.is_conflicting`/`is_mergeable_unknown` already provide these interpretations, and `merge_pr` already short-circuits before reading CI).

**Rework loop (the real gap this spec fills)**: connect the CI/e2e/review gates to a unified loop—on failure, **no longer merely `return {"reason": ...}`**; instead, dispatch `implementer` to iteratively revise the code. After revision, **re-enter the pipeline from conflict in the next round** (not a retry in place—the base may have changed again after the code was revised, so re-entry must start with an objective conflict recheck; refusal by `github.merge_pr` when merging is impossible is the final fallback).

### Constraints (non-negotiable, hard-coded into validation/layering)

- **① `rfc: skip` conflicts with principle 4**—allow skipping, but require an explicit choice at issue granularity or at least an explicit loader warning; do not put it into global defaults and silently disable the RFC selling point.
- **② Deterministic hard gates never enter `stages`**—head advancement / evidence provenance stamps (`assert_evidence_stamp`) / the `round_cap` infinite-loop limit are always machine-enforced and always present (the safety baseline against spinning without progress in #140; `skip` cannot disable them). Keep the terminology for `stages` (configurable stages) separate from `gates.py` (hard baselines) to reinforce the separation of layers; the loader treats hard-gate names in `stages` as errors.
- **③ The closed loop that prevents self-replies must remain intact**—agent comment replies must carry the hidden signature `<!-- openagents:agent=xxx -->` (agents and humans may share the same gh account, so only a body signature can distinguish them, not the author); `poll_comments` uses it to filter for “reply only to new, unsigned human comments.” After `reply-comment` is demoted to a hidden command, `identity.post_signed_comment` must still guarantee “add the signature when replying + verify after synchronization (if the signature is missing, edit to add it; a warning alone is insufficient),” or the infinite loop of self-directed questions and answers will recur.

### Task DAG + file allocation

The `files` sets across all groups are pairwise disjoint—the foundation of conflict-free collaboration (principle 6, single-writer ownership).

| Task | depends-on | Owned files | Deliverable |
|------|-----------|-------------|------|
| **T1** | — | `openagents/utils/agent_config.py`, `tests/test_agent_config.py` | Configuration layer: schema + loader + three-state validation + no-zero-gates guard (additive) |
| **T2** | — | `openagents/recipes/stages.py`, `tests/test_recipe_stages.py` | Extract nine stages into free functions outside the `Vigil` class (additive) |
| **T3** | T1, T2 | `openagents/recipes/vigil.py`, `tests/test_recipe_vigil.py` | `run_vigil` policy routing + CI/e2e/review rework loop + fold in fleet |
| **T4** | T2 | `openagents/recipes/backfill.py`, `tests/test_recipe_backfill.py` | Separate path-driven backfill-rfc flow (additive) |
| **T5** | T3, T4 | `openagents/cli.py`, `openagents/utils/identity.py`, `tests/test_cli_new_stack.py` | Consolidate the CLI surface into four commands + hide reply-comment + harden post-signature verification |
| **T6** | T5 | `openagents/recipes/solve_issue.py`, `openagents/recipes/merge_pr.py`, `openagents/recipes/poll_comments.py`, `openagents/recipes/rfc_lifecycle.py`, `openagents/recipes/fleet.py`, `openagents/agents/planner.py` | Delete 5 old recipes + planner (merged into drafter) + consolidate test stubs + regenerate docs |

DAG shape: T1 ∥ T2 have no dependencies and can run in parallel (both additive and hermetically testable) → T3 joins them (reads T1 config, composes T2 stages) → T4 reuses the T2 rfc primitive → T5 rewires the CLI (the new stack is already in place) → T6 deletes the old code (nothing imports the old recipes anymore). The additive T1/T2/T4 go first; the destructive T5→T6 are strictly sequential. Run the full pytest suite + ruff at every step as a hard gate; stop if either is red.

### e2e script

`scripts/e2e-spec-0064-declarative-stages-converge.sh`—ruff check + ruff format --check + targeted pytest (configuration-layer three-state validation/no zero gates/per-repository overrides; orchestration-layer agent·human·skip branches + rework loop + hard gates outside policy control) + grep anchors (only stages/vigil/backfill remain under `recipes/`; zero matches for bare imports of deleted recipes/planner; explicit parameters for the nine atomic functions; the signature loop). This is purely backend configuration/orchestration/CLI consolidation, with no product-facing frontend, so no browser e2e is specified; continue using the offline deterministic testing approach from the previous four batches (see the frontmatter `e2e` block).

## Drawbacks

- **Large batch size and broad review scope**: Adding a configuration layer + extracting stage functions + rewriting orchestration + consolidating the CLI by deleting nine commands + deleting 5 recipes/1 agent makes this another major consolidation after Spec-0062. Mitigation: the DAG strictly separates additive work (T1/T2/T4) from destructive work (T5/T6), with the full pytest+ruff suite as a hard gate at each layer. Old code is deleted only after the CLI has been rewired (with no remaining imports of the old recipes).
- **The configuration layer adds a source of truth and another parsing layer**: Introducing `.openagents/openagents.yml` turns “who owns each gate” from code constants into runtime configuration. Reading the code alone no longer directly reveals behavior—the YAML must be read alongside it. Mitigation: the entire file is optional, with everything falling back to built-in defaults (= today's hardcoded behavior), so users who do not write YAML see no change; the loader also rejects invalid combinations at startup.
- **Three-state semantics impose a cognitive cost**: The three states `agent`/`human`/`skip`, combined with different legal values for each gate (conflict/merge cannot be skipped; rfc allows only agent/skip), may confuse users. Mitigation: the loader validates values per gate and provides clear error messages; the Guide-level documentation includes a fully commented example.
- **`rfc: skip` creates a way to bypass the RFC selling point**: Even with warnings, leaving skip enabled long term would erode principle 4. Mitigation: allow it only as an explicit choice per issue + issue an explicit loader warning; exclude it from global defaults (constraint ①).
- **Rejection loops may compound with a reviewer that always returns REWORK, increasing the number of rounds**: All three gates—CI/e2e/review—can trigger implementer iterations; in the worst case, multiple gates take turns rejecting the work. Mitigation: the `gates.round_cap` limit on infinite loops always remains in force (outside the control of stages), with a fallback raise when the limit is reached.

## Rationale and alternatives

- **Alternative A: Continue using CLI flags (`--hold`/`--skip`) for policy, without introducing YAML**. Minimal changes and no new source of truth. **Rejected**: flags apply only once, leave no record across runs, provide no place to see “who owns each gate” at a glance, and cannot express “which backend each agent uses” (principle 2). Choose declarative YAML as the single source of truth, reducing flags to per-run overrides.
- **Alternative B: Extract stage functions only, without adding an orchestration point for policy routing**. Avoids the three-state `stages` model and the loader. **Rejected**: extracting functions is a prerequisite, not the goal—without composition, `review: skip` still has nowhere to take effect; stages become addressable but remain unconfigurable. A `run_vigil` that routes according to `stages` is also required.
- **Alternative C: Make CI/e2e/review “agent decision gates” as well** (have an agent read logs to decide whether CI passed). Appears uniform. **Rejected**: violates constraint ②—CI/e2e **detection** always consists of deterministic reads (github check / evidence stamps); `agent` means only “automation owns this gate and automatically sends work back when it turns red,” not that an agent subjectively judges objective facts. The detector and the owner are separate things.
- **Alternative D: Bring deterministic hard gates under `stages` as well** (allow `skip` for head advancement/evidence stamps/round_cap). Makes configuration more “complete.” **Rejected**: violates constraint ②—hard gates are the safety baseline against the unproductive looping in #140; their purpose depends on `skip` being unable to disable them. Configurable stages and the hard safety baseline must remain separate layers. A hard gate name in `stages` produces an error.
- **Alternative E: Keep both `planner` and `drafter` without merging them**. Leaves one more agent untouched. **Rejected**: both “draft specs without writing implementation code,” making them redundant remnants of the old and new stacks; drafter already handles drafting decisions across five modes, while planner is dead code. Merging them into a single drafting stage better follows Occam's razor.
- **Alternative F: Consolidate the recipes layer but retain old files and both stacks as a fallback**. Safer. **Rejected**: Spec-0062 already unified the two stacks. Retaining old recipes would return to an intermediate state of coexistence, increasing cognitive load and adding an import indirection layer. Old code is deleted only after the CLI has been fully rewired, with hard evidence from a preceding grep showing zero imports.

## Prior art

- **Spec-0027 (multi-repository vigil) and `utils/fleet_config.py`**: The existing pattern of declarative configuration loading with `ruamel.yaml` + `jsonschema` Draft202012, `defaults`/`repos` merging, and contradiction validation is the template directly reused by T1 `agent_config.py` (incorporating the `repos` section of `fleet.yml`).
- **Spec-0060/0061/0062 (three batches of the new agents/recipes/runtime/utils stack)**: Established the boundaries between the four layers (judgment → agent; mechanical work → deterministic code), the `solve_issue`/`merge_pr`/`poll_comments`/`vigil`/`fleet` recipes and `triager`/`drafter`/`reviewer`/`replier`/`deliver` agents, the minimal hard gates in `gates.py`, and `cli._new_vigil_for` as the single wiring point. This spec directly builds on that work to extract stage functions, introduce an orchestration point, and consolidate by deleting old code.
- **Spec-0020 (human-oversight-gates) and `gates.hold_hits`/`skip_hits`**: The existing gate-name allowlist and short-circuit semantics of `--hold` (stop and wait for a human)/`--skip` (let through as PASS) are the current behavior that the three-state `stages` model will bring under a single source of truth.
- **Spec-0055/0057 (e2e evidence provenance stamps) and `gates.assert_evidence_stamp`**: The hard-gate decision made by deterministically reading evidence stamps at the e2e gate is the concrete subject of constraint ②, “hard gates do not go into stages.”
- **Spec-0011 (agent identity signatures) and `utils/identity.post_signed_comment`**: The hidden signature `<!-- openagents:agent=xxx -->`, together with `poll_comments` using it to filter for human comments, forms the closed loop that prevents self-triggering. This is the behavioral baseline for constraint ③ and for demoting `reply-comment` to a hidden command.
- **GitHub merge-state semantics**: [REST — pulls (`mergeable` can be true/false/null, where null = being computed in the background)](https://docs.github.com/en/rest/pulls/pulls) · [GraphQL Enums — `MergeableState`/`MergeStateStatus` (DIRTY/BEHIND/UNKNOWN/CLEAN…)](https://docs.github.com/en/graphql/reference/enums) · [Troubleshooting required status checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/defining-the-mergeability-of-pull-requests/troubleshooting-required-status-checks)—support the ordering argument that “conflict must be a hard dependency before CI.”
- **[rust-lang/rfcs](https://github.com/rust-lang/rfcs)**: The source of this spec's nine-section overview structure at the group level.

## Unresolved questions

The following three questions come from “Open questions” in issue #161. They record this spec's preferences and require a user decision before implementation:

- **1. Where the `board` command belongs**: Retain it as an independent read-only observation command (**preferred**, eventually incorporating it into the frontend to present results, principle 8)? Or place it under `vigil` as a subcommand? For now, this spec treats it as “remain independent, outside stages/outside this consolidation scope”—it provides read-only observation rather than a slice of the automation loop, so incorporating it has little value. (`release` is already settled: top-level `release: manual|auto`, not a stage.)
- **2. How deterministic hard gates are exposed in YAML**: Exclude them from YAML entirely (**preferred**, safest, and adopted by this spec—a hard gate name in `stages` produces an error)? Or retain the semantics of `--skip ci/evidence`, allowing YAML to specify `skip` but never `agent`/`human`? These implement constraint ② differently and require confirmation.
- **3. How `reply-comment` is implemented**: Simply demote it to a hidden internal command (**preferred**, still using `identity.post_signed_comment` as the single signing outlet)? Or switch entirely to “raw gh + post-validation and signature repair”? This spec adopts the former and requires hardening `post_signed_comment` to “add signatures to replies + synchronously validate afterward and edit to add any missing signature” (constraint ③).
- **4. Whether the single `drafter` agent should be split to handle drafting and backfill decisions separately**: `recipes/backfill.py` (T4) reuses drafter's backfill mode; if a mode's prompt grows enough to interfere with other modes, it can be split into multiple agents later. Whether to split it, and what signals should trigger a split, will be decided during T4 implementation based on the actual prompt complexity (carried over from the same Unresolved question in Spec-0062).

## Future possibilities

- **Implement the `codex`/`nexau` backends**: `backends/` currently contains only `claude_code`; this spec reserves only the schema slot for `agents.<role>.backend` (the declarative interface for decentralization in principle 2). Implementation will be discussed separately. Only then will mixing different coding agents within the same project actually work end to end.
- **Extend `stages` to finer-grained per-role policies**: For example, put “reviewer uses strict mode / lenient mode” and “implementer iteration limit” into YAML so that configuration covers more adjustable controls.
- **Incorporate `board` into the frontend**: Bring the read-only observation command into the frontend, where “the primary visual area is used to present results” (principle 8), with YAML `stages`/`agents` also serving as the policy data source for frontend visualization.
- **Materialize `release: auto`**: This spec declares only the top-level `release: manual|auto` policy slot; implementation of `auto` (automatically cut a version when main is green + there is no BLOCKED) will be discussed separately.
- **Develop reusable orchestration combinators from the recipe layer**: If `run_vigil`'s pattern of “look up the owner → route by the three states (call an agent function / stop and wait for a human / skip)” recurs in multiple places, it can be extracted into a policy-routing combinator in the `runtime` layer for further consolidation.
