---
number: "0062"
title: "Architectural refactoring (consolidation batch): fully migrate the RFC lifecycle + PR merge pipeline to the new stack, delete the old stack, and unify the two stacks"
issue: 145
slug: agents-recipes-converge
summary: "Building on the agents/recipes/runtime/utils stack established by Spec-0060/0061, reimplement in one pass the two major areas still 100% on the old stack—orchestrator's RFC lifecycle (rfc/backfill/refine/implement/iterate) and messages' PR merge pipeline (the mergeability/CI/e2e/review/merge stage machine)—as new-stack recipes along the established boundary (judgment goes to agents; mechanical operations stay in deterministic recipes/gates/utils). Switch the entire CLI to the new stack, then physically move the 15 primitives (including fleet/align) into utils and delete the 10 old modules devoted solely to orchestration/judgment (orchestrator/messages/vigil/reviewer/issuecheck/backfill/agentcontext/executor/conflict/conflictdiag), consolidate their test stubs, and reduce the flat layer to the three files cli/__init__/state, unifying the two stacks."
tasks:
  - id: T1
    title: "RFC lifecycle recipes + drafter agent (additive)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/rfc_lifecycle.py
      - openagents/agents/drafter.py
      - tests/test_recipe_rfc_lifecycle.py
      - tests/test_agents_drafter.py
    scope: "Reimplement orchestrator's five RFC lifecycle flows—start_rfc/backfill_rfc/refine_rfc/implement/iterate—as recipes.rfc_lifecycle along the established boundary: delegate judgment (drafting RFCs / inferring specs / refining based on comments) to the drafter agent (a zero-logic Template), while keeping mechanical operations (claim labels / open draft PRs / mark PRs ready / write files) in the recipe via utils/engine. Additive; no changes to the old orchestrator."
    acceptance: "The five recipe entry points can be tested hermetically (a fake backend supplies canned decisions, without touching real LLMs/networks/repositories); drafter has zero def/subprocess; ruff passes."
  - id: T2
    title: "merge_pr recipe + merge pipeline gates (additive)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/merge_pr.py
      - openagents/runtime/gates.py
      - tests/test_recipe_merge_pr.py
    scope: "Reimplement the stage state machine in messages.poll (mergeability precheck / CI gate / e2e evidence gate / review / merge + symmetric hold/skip short-circuiting + closed-run revival + conflict self-healing) as recipes.merge_pr along the established boundary: deterministic gates stay in the recipe/runtime.gates, review judgment goes through the existing reviewer agent, and conflict self-healing goes through the existing git delivery agent. Additive; no changes to the old messages."
    acceptance: "merge_pr can be tested hermetically, covering all merged/blocked/ci/review/e2e/reopened/error routes; symmetric hold/skip short-circuiting; ruff passes."
  - id: T3
    title: "vigil claim ownership + expired-claim reclamation + connect the watch phase to merge_pr"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - openagents/recipes/poll_comments.py
      - openagents/runtime/state.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_poll_comments.py
    scope: "Add signed claim notes + expired-claim reclamation to vigil's deduplication gate (identity.latest_claim + a threshold, for claims across processes and multiple backends); expand vigil's watch phase in each round from poll_comments to “poll_comments responds to comments + merge_pr advances merging,” completing the discovery → solution → response → merge cycle. Also add the fields needed to wire the merge/rfc pipelines into runtime.RuntimeState: find runs by PR number (find_run(pr_number=)), and include issue_number and closed_at in run records—connecting T1/T2's fake-state seam to the real state. Blocking based on the rounds budget across rounds (the old MAX_ROUNDS) is not migrated in this batch; leave it in Unresolved as a known simplification."
    acceptance: "vigil's watch phase drives merge progress; claim notes/expired-claim reclamation can be tested hermetically; RuntimeState provides find_run(pr_number=)/issue_number/closed_at; ruff passes."
  - id: T4
    title: "Switch the entire CLI to the new stack + delete old routing"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli_new_stack.py
    scope: "Switch all nine commands—rfc/backfill-rfc/refine-rfc/implement/iterate/poll/watch/vigil/vigil-all—to recipes.*; delete the _orchestrator_for factory, the messages.Messages import, and old stage-machine routing; consolidate new and old command names (absorb vigil-new into vigil, and poll-comments into poll's comment phase)."
    acceptance: "All CLI commands use new-stack recipes; all oa commands parse and dispatch; no import of openagents.orchestrator/messages; ruff passes."
  - id: T5
    title: "Physically move utils primitives + clear out the entire old flat module layer"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/utils/identity.py
      - openagents/utils/release.py
      - openagents/utils/notes.py
      - openagents/utils/blocknote.py
      - openagents/utils/replynote.py
      - openagents/utils/worknote.py
      - openagents/utils/hold.py
      - openagents/utils/skip.py
      - openagents/utils/results.py
      - openagents/utils/config.py
      - openagents/utils/envcheck.py
      - openagents/utils/fleet_config.py
      - openagents/utils/fleet.py
      - openagents/utils/workspace.py
      - openagents/utils/github.py
      - openagents/utils/align.py
    scope: "Physically move the implementations of the 15 primitives from the old top-level modules into openagents/utils/* (no longer thin re-exports): config/envcheck/fleet_config/github/hold/identity/release/results/skip/workspace/blocknote/replynote/worknote/fleet/align; also move templates/ with results into utils/templates/. Of these, fleet (the process supervisor) and align (the alignment entry point before issue creation, still used by cli) are **moved, not deleted**—they are referenced by recipes.fleet / cli, so they belong in utils rather than disappearing. Then clear out the entire old flat module layer—delete the 10 classes of modules devoted solely to orchestration/judgment (already replaced by recipes/agents, with 0 references): orchestrator/messages/vigil/reviewer/issuecheck/backfill/agentcontext/executor/conflict/conflictdiag. Also repoint direct flat imports in the surviving cli.py (owned by T4) and state.py (owned by T3) to utils (finishing the physical move; this crosses Task ownership boundaries, but deletion cannot be left half-finished). **Keep cli.py + __init__.py; retain state.py temporarily because the new and old state implementations have not yet been unified** (its deletion will be handled alongside state unification in a separate Spec-0063; this group already has its full allocation of 6 Tasks)."
    acceptance: "Only openagents/{cli.py,__init__.py,state.py} remain in the flat layer; repository-wide grep finds zero direct imports of deleted/moved modules; all oa commands parse; ruff passes."
  - id: T6
    title: "Test consolidation + docs regeneration"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T5
    relates-to: []
    parallel: false
    files:
      - tests/test_orchestrator.py
      - tests/test_messages.py
      - tests/test_vigil.py
      - tests/test_issuecheck.py
      - tests/test_ensure_prerequisites.py
    scope: "Consolidate tests to reflect the unified stack—delete the 38 test stubs that directly test deleted orchestration modules (orchestrator*/messages*/vigil*(old)/reviewer*/conflict*/executor/backfill/agentcontext/issuecheck and their integration stubs; their behavior is already covered by test_recipe_*); repoint imports in the 40 test stubs for moved primitives from the old top-level paths to openagents.utils.* (including test_cli/test_fleet/test_align/test_workspace/test_recipe_* and others—moving primitives does not mean deleting their tests); retire test_ensure_prerequisites assertions for label aliases in the deleted messages module, retaining cli/state alias checks. Regenerate OVERVIEW/ARCHITECTURE with spec render/graph, with no drift. Abandoning old specs (0001–0057) is a separate discussion: their bodies document the design history of the old stack, and abandoning them in bulk would reshape the entire snapshot. This is an independent decision outside the scope of this migration/CI gating; leave it for dedicated follow-up."
    acceptance: "The full pytest suite passes (669 passed); no direct imports of deleted modules; spec validate reports no errors; OVERVIEW/ARCHITECTURE are drift-free."
---

# 0062 · Architecture Refactoring (Convergence Batch): Fully Migrate the RFC Lifecycle + PR Merge Pipeline to the New Stack, Remove the Old Stack, and Unify the Two Stacks

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level, nine-section rust-RFC overview. -->

## Summary

The previous two batches (the Spec-0060 skeleton + the Spec-0061 autonomous loop) established the new stack across the four layers of `agents/recipes/runtime/utils`, enabling it to independently orchestrate the autonomous loop of “an issue from discovery → triage → solution → delivery, plus human–agent conversations on PRs.” But the other half of the product—the **RFC-driven development lifecycle** (`rfc/backfill-rfc/refine-rfc/implement/iterate`, totaling 914 lines in `orchestrator.py`) and the **PR merge pipeline** (the mergeability/CI/e2e/review/merge stage state machine, 963 lines in `messages.py`)—still resides 100% in the old stack, with no equivalents in the new stack. This convergence batch completes **all remaining migration in one pass**: reestablish these two major components as new-stack recipes along the established boundary (**judgment goes to agents; objective, mechanical operations remain in deterministic recipes/gates/utils**), rewire all nine CLI commands to the new stack, then upgrade utils from “thin re-exports” to **physical relocation** (15 primitives move into utils, including the still-referenced fleet/align), and **delete** 10 old modules devoted solely to orchestration/judgment (`orchestrator/messages/vigil/reviewer/issuecheck/backfill/agentcontext/executor/conflict/conflictdiag`), consolidating their test scaffolding—thus **unifying the two stacks**, reducing the flat layer to three files, `cli.py/__init__.py/state.py`, and eliminating parallel old and new modules with the same name at the top level of `openagents/`.

## Motivation

Current state: after Spec-0060/0061, the repository is in an intermediate state with **two coexisting stacks**. The new stack can run autonomous discovery → solution → response, but all **RFC-driven** actions (drafting an RFC for an issue and opening a draft PR, scanning existing code to infer a spec, refining an RFC based on review, implementing an approved RFC and marking the PR ready for review, and iterating on feedback) still have only one implementation, in the old `orchestrator.py`; all **PR progression toward merge** actions (checking mergeability, running CI/e2e evidence gates, reviewing, merging, hold/skip short-circuiting, reviving closed runs, and conflict self-healing) still have only one implementation, the old 964-line stage state machine in `messages.py`. Nine CLI commands (`rfc/backfill-rfc/refine-rfc/implement/iterate/poll/watch/vigil/vigil-all`) connect directly to these two old modules.

Two coexisting stacks are not a steady state: readers must distinguish “which is the new stack,” modules with the same name coexist (new `recipes.vigil`/`recipes.fleet` versus old `vigil.py`/`fleet.py`), thin utils re-exports add an extra hop between imports and implementations, and ~29 test scaffolds remain tied to old modules. The previous two batches explicitly deferred “removal of the old stack and convergence” to the “final convergence batch” (see their Unresolved/Future sections). **This is that convergence batch.** The user explicitly requested completing everything in one pass without further batching, so this batch covers the full scope of “complete the remaining two major recipe components + fully rewire the CLI + physically relocate implementations and remove the old stack.”

The boundary underlying this motivation is **identical, word for word**, to that of the previous two batches: judgment → agent (RFC drafting decisions go to `drafter`, review decisions to the existing `reviewer`, comment responses to the existing `replier`, and conflict self-healing to the existing git delivery agent); objective, mechanical operations remain in deterministic code (recipe control flow + `runtime.gates` hard gates + `utils` primitives).

## Guide-level explanation

This batch reestablishes the two remaining main branches of the old stack as recipes along that boundary, then performs a single convergence and removal pass, organized into six Tasks:

- **`recipes.rfc_lifecycle` (T1)**: Reestablish the orchestrator’s five entry points, `start_rfc/backfill_rfc/refine_rfc/implement/iterate`, as five **pure-control-flow** recipes. Each only “calls the engine to dispatch an agent for a structured decision + follows that decision with deterministic utils fallback actions”: parts requiring judgment (how to write the RFC body, what spec to infer from existing code, how to refine based on comments, and how to implement after approval) are delegated to the new `drafter` agent (a zero-logic `string.Template` PROMPT + `OUTPUT_SCHEMA`); mechanical parts (adding a claim label to an issue, opening a draft PR or marking it ready for review, writing spec files, and posting announcement comments) remain in recipes through `utils.github`/`utils.identity`.
- **`recipes.merge_pr` (T2)**: Reestablish the messages.poll stage state machine as a recipe. Deterministic gates (mergeability prechecks, reading CI conclusions, validating e2e evidence provenance stamps, symmetric hold/skip short-circuiting, and the watermark for reviving closed runs) remain in the recipe/`runtime.gates`—all of these **read objective facts**, rather than exercise judgment; the judgment of “can this version be merged” goes to the existing `reviewer` agent, and “how to resolve conflicts through rebase” goes to the existing git delivery agent. Return an event list with the same structure as the old poll (reasons such as `merged/blocked/ci/review/e2e/reopened/error`) for logging and assertions.
- **Vigil consolidation (T3)**: Add the old stack’s **signed claim notes + expiration reclamation** to the deduplication gates in `recipes.vigil` (cross-process claim ownership across multiple backends), and expand each round’s waiting phase from “respond to comments only” to “respond to comments (poll_comments) + advance merging (merge_pr),” completing the full **discovery → solution → response → merge** loop.
- **Full CLI rewiring (T4)**: Rewire nine commands to `recipes.*`, delete the `_orchestrator_for` factory and the `messages.Messages` import, and consolidate old and new command names (`vigil-new` → `vigil`, with `poll-comments` incorporated into the comment phase of `poll`).
- **Clear out the flat layer (T5)**: Upgrade utils from thin re-exports to physically relocated implementations (including workspace and the note family), move the `Fleet` supervisor into `utils.fleet`, then **delete the entire old flat module layer**—orchestration/judgment modules (orchestrator/messages/vigil/reviewer/align/issuecheck/backfill/agentcontext/executor/conflict/conflictdiag) + primitive files absorbed by utils (github/config/envcheck/hold/skip/release/results/identity/fleet/fleet_config/blocknote/replynote/worknote/workspace). Reduce the flat layer to just `cli.py` + `__init__.py` + `state.py` (`state.py` remains temporarily because state has not yet been unified; its deletion will be covered by a separate Spec-0063 for state unification).
- **Test and documentation consolidation (T6)**: Delete/migrate ~29 test scaffolds that directly test old modules, invalidate old specs, and regenerate OVERVIEW/ARCHITECTURE.

## Reference-level explanation

**Boundary classification (consistent with the previous two batches)**: Everything retained in recipes/gates “reads objective facts”—mergeability (the mergeable flag provided by GitHub), CI conclusions (a check’s conclusion), e2e evidence stamps (whether head_sha matches), hold/skip matches (whether present in configuration), the revival window (whether closed_at is newer than the threshold), and claim-note existence and expiration (timestamps compared against a threshold). Everything delegated to agents involves “subjective judgment”—what to write in the RFC body, whether this version of the code/RFC can pass review, what a comment is asking for, and how to resolve conflicts through rebase.

**Task DAG + file allocation** (`files` are pairwise disjoint across the entire group—the foundation of conflict-free collaboration, principle 6):

| Task | depends-on | Owned files | Deliverable |
|------|-----------|-------------|------|
| **T1** | — | `recipes/rfc_lifecycle.py`, `agents/drafter.py`, `tests/test_recipe_rfc_lifecycle.py`, `tests/test_agents_drafter.py` | Five RFC lifecycle recipes + drafter (additive) |
| **T2** | — | `recipes/merge_pr.py`, `runtime/gates.py`, `tests/test_recipe_merge_pr.py` | Merge pipeline recipe + gates (additive) |
| **T3** | T1, T2 | `recipes/vigil.py`, `recipes/poll_comments.py`, `tests/test_recipe_vigil.py`, `tests/test_recipe_poll_comments.py` | Vigil claim reclamation + merge_pr wired into the waiting phase |
| **T4** | T1, T2, T3 | `cli.py`, `tests/test_cli_new_stack.py` | All nine commands rewired to the new stack; old routing removed |
| **T5** | T4 | `utils/{identity,release,notes,hold,skip,results,config,envcheck,fleet_config,fleet,workspace}.py` | Physical relocation + clearing out the entire flat layer (only cli/__init__/state remain) |
| **T6** | T5 | `tests/test_{orchestrator,messages,vigil,fleet,align,issuecheck}.py` | Test consolidation + invalidation of old specs + docs regeneration |

DAG shape: T1 ∥ T2 have no dependencies and can run in parallel → T3 joins them → T4 rewires → T5 removes the old stack → T6 consolidates. Additive T1/T2 go first and can be tested hermetically (a fake backend supplies canned decisions, without touching real LLMs/networks/repositories); destructive T4 → T5 → T6 run strictly in sequence, with the full pytest suite + ruff as hard gates at every step. Any failure stops progression.

**e2e script**: `scripts/e2e-spec-0062-converge.sh`—ruff check + ruff format --check + targeted pytest (routing for the five RFC recipes / routing for every merge_pr reason / Vigil claim reclamation / forwarding for the nine CLI commands) + grep anchors (drafter has zero def/subprocess; `grep -r 'openagents.orchestrator|messages|align|issuecheck'` yields zero matches across the repository, proving complete removal of the old stack). This is pure backend orchestration with no product-facing frontend, so no browser e2e is specified; it follows the offline deterministic testing approach of the previous two batches.

**Single wiring point**: Retain Spec-0061’s `cli._new_vigil_for(ctx)` pattern of constructing backend/RuntimeState/agent_id once. T4 also brings the RFC lifecycle and merge_pr factories into this single wiring point, ensuring consistent backend/state/identity within a process.

## Drawbacks

- **Large single batch and broad review surface**: One change spans new recipes + CLI rewiring + deletion of six modules + rewriting ~29 tests, making this the project’s largest single batch to date. Mitigation: the DAG strictly separates additive work (T1/T2) from destructive work (T4–T6), with the full pytest suite + ruff as hard gates at each layer; deletion of the old stack occurs only after the CLI has been fully rewired (nothing imports the old modules anymore).
- **Loss of the fallback safety provided by two coexisting stacks**: The previous two additive batches retained the old stack as a fallback. Once this batch deletes it, no in-process fallback remains; recovery requires git revert. Mitigation: deletion of the old stack is the final step and requires prior hard evidence of “zero imports of old modules in grep.”
- **Some historical semantics of `messages.poll` may be missed during reestablishment**: The 964-line state machine contains branches accumulated across multiple Specs (0020 hold/0021 review-invalid/0031 merge-retry/0040 e2e/0042 reopened/0054 skip). Mitigation: T2 uses the old poll’s set of reasons as the acceptance criteria checklist, building hermetic tests for each reason.
- **A single `drafter` agent handles five kinds of drafting judgment**: The prompts for RFC drafting/reverse inference/refinement/implementation/iteration differ substantially. Mitigation: drafter uses the same Template skeleton + differentiation through a `mode` placeholder supplied by each recipe, still with zero control flow.

## Rationale and alternatives

- **Alternative A: Continue in batches (implement only merge_pr in this batch and leave the RFC lifecycle for the next batch)**. This follows the established cadence of the first two batches and carries the lowest risk. **Rejected**: The user explicitly requested completing everything in one pass, with no further batching; each additional batch in which the two stacks coexist adds another batch’s worth of cognitive overhead and import indirection.
- **Alternative B: Port the 964-line state machine from messages.poll to merge_pr verbatim**. This saves the cost of rebuilding it. **Rejected**: It defeats the purpose of the refactor (judgment and mechanics remain intertwined) and transfers the old stack’s historical baggage wholesale into the new stack. The chosen approach is to rebuild along the layer boundaries, keeping deterministic gates in the recipe and routing review judgments through the reviewer.
- **Alternative C: Keep utils as thin re-exports without physically moving implementations, and delete only orchestrator/messages**. This deletes less code and is safer. **Rejected**: Thin re-exports add an extra hop between the import surface and the implementation surface, while implementations such as identity/fleet_config remain in old files that have already been declared obsolete, leaving the consolidation incomplete. The chosen approach is to physically move the implementations into utils as their sole home.
- **Alternative D: Hard-code drafter judgments in the recipe (without dispatching an agent)**. This saves one agent. **Rejected**: RFC drafting unit tests would then necessarily invoke a real LLM, and this would violate the layer boundaries. The chosen approach is to delegate to an agent and have the recipe inject the mode.

## Prior art

- **Spec-0060 (batch one)**: Established the four-layer boundaries and `solve_issue`/`engine`/`gates`/`Context`/`RuntimeState`; this batch directly builds on its recipe/agent/gates skeleton.
- **Spec-0061 (batch two)**: Established the `vigil`/`poll_comments`/`fleet` recipes and `triager`/`replier` agents, the stable utils surface, and `cli._new_vigil_for` as the single wiring point; T3 in this batch adds claim reclamation to its Vigil, T4 follows its wiring pattern, and T5 upgrades its thin re-exports to physical relocation.
- **Old `orchestrator.py` (RFC-0001/0005/0011/0019/Spec-0020/0025)**: Its existing implementations of the five RFC lifecycle entry points plus `precheck_issue`/`review_rfc`/`review_code`/`run_e2e` are the behavioral baseline for the T1 rebuild.
- **Old `messages.py` (RFC-0001/0012, Spec-0020/0021/0031/0040/0042/0054)**: The set of reasons and the hold/skip/revive semantics in its poll-stage state machine form the acceptance checklist for the T2 rebuild.
- **Old `vigil.py` (RFC-0004/0007, Spec-0039/0049)**: Signed claim notes and expiration-based reclamation are the behavioral baseline for the additions to `recipes.vigil` in T3.

## Unresolved questions

- **Whether the five `drafter` modes need to be split into multiple agents**: This batch initially uses a single agent + mode placeholder; if the prompts for any mode grow to the point that they interfere with one another, they can be split later. Whether to split them, and what signals should trigger a split, will be determined during T1 implementation based on the actual prompt complexity.
- **The eventual unified form of the two state systems (`runtime-state.json` vs `state.json`)**: T5 in this batch physically relocates utils, but state unification (choosing one or merging the schemas) involves data migration. Whether to include it in this batch’s T5 or create a separate batch immediately afterward requires user confirmation (see the clarification below).
- **Deeper code changes by `replier` remain unresolved**: This batch’s merge_pr completes the “advance the merge” workflow, but having replier “actually change code based on comments and push” still requires a PR worktree (carrying forward the same Unresolved item from Spec-0061) and is outside this batch’s scope.

## Future possibilities

- **State unification**: Merge `runtime-state.json` and `state.json` into a single runtime state source, completely eliminating dual state.
- **Upgrade replier to “deliver iteratively based on comments”**: After connecting a PR worktree, reuse deliver from `solve_issue` + the hard gate requiring head to advance.
- **Develop common orchestration primitives in the recipe layer**: If the five RFC recipes + merge_pr + Vigil exhibit a repeated “dispatch agent → route according to the verdict → fall back to utils” skeleton, it can be extracted into recipe combinators at the runtime layer.
