---
number: "0061"
title: "Architecture refactoring (batch two): establish the three vigil/poll_comments/fleet recipes + triager/replier agents + the full stable utils interface"
issue: 145
slug: agents-recipes-flows
summary: "Building on the architectural contract from Spec-0060 batch one (all operations requiring judgment go through agents, recipes route solely on structured decisions, runtime retains minimal hard gates, and utils contains deterministic primitives), additively establish the three recipes deferred to subsequent batches (the vigil discovery→triage→dispatch loop / poll_comments responses to new human comments on PRs / fleet concurrency across multiple repositories) and two agents (triager takes over issue alignment and conflict self-check judgments from align+issuecheck; replier takes over comment reply judgments), and expand utils from the two thin git/github re-exports in batch one into a complete stable import interface covering release/notes/hold/skip/results/identity/config/envcheck/fleet_config—allowing the new stack to independently orchestrate the full lifecycle of an issue from discovery to delivery, without directly importing legacy modules. This remains additive: do not delete the legacy orchestrator/vigil/messages/fleet or their test stubs (their deletion and the invalidation of legacy specs are deferred to the final consolidation batch)."
e2e:
  intent: "Demonstrate that the batch-two architectural contract holds along the offline deterministic path—the vigil recipe routes solely according to the triager's structured decisions (actionable→dispatch / otherwise→_park), and the three deduplication gates deterministically filter for new items; poll_comments implements only the control flow of fetching new human comments→replier→posting signed replies→advancing the cursor, with error isolation for individual PR failures; fleet reuses the old Fleet supervisor to fan out vigil on the new stack; triager/replier contain zero logic, and none of the three recipes directly invokes gh/git/subprocess."
  method: "Form: backend-only orchestration, with no navigable product-facing frontend; the self-check tool list contains neither Playwright nor Chrome DevTools MCP,\nso no browser e2e tests are planned; offline deterministic testing is used instead:\n1. Contract routing + targeted pytest tests at each layer (a fake backend supplies canned structured decisions, without accessing a real LLM/network/repository):\n   vigil triage routing + the three deduplication gates; poll_comments cursor advancement/error isolation; fleet fan-out + worker; parsing and forwarding for the three CLI commands.\n2. Zero-logic / zero-IO grep anchors (e2e script): triager/replier contain only Template( + OUTPUT_SCHEMA and no\n   def/subprocess; the three recipes contain no subprocess and do not directly import the underlying openagents.github/workspace modules (access is only through utils).\n3. Real multi-repository Vigil smoke testing (dogfood, Phase-3 human validation / runbook, not a deterministic CI gate): oa vigil-new / oa fleet\n   run successfully, and all PR CI checks pass—recorded in the runbook as outcome acceptance (Principle 8), rather than included in the offline script.\nScript: scripts/e2e-spec-0061-agents-recipes-flows.sh (ruff check + ruff format --check +\n targeted pytest tests + grep anchors), collected by the PR e2e signpost.\n"
tasks:
  - id: T1
    title: "Full stable utils import interface (thin re-exports of deterministic primitives)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/github.py
      - openagents/utils/git.py
      - openagents/utils/release.py
      - openagents/utils/notes.py
      - openagents/utils/hold.py
      - openagents/utils/skip.py
      - openagents/utils/results.py
      - openagents/utils/identity.py
      - openagents/utils/config.py
      - openagents/utils/envcheck.py
      - openagents/utils/fleet_config.py
    scope: "Expand utils from the two thin git/github re-exports in batch one into a complete stable interface covering release/notes/hold/skip/results/identity/config/envcheck/fleet_config; all are thin re-exports of legacy modules, with no copying or modifications (Occam's razor). Add remote_branch_exists to git as a free function that requires no instance."
    acceptance: "The new stack can obtain all deterministic primitives, including github/git/identity/fleet_config, by importing only openagents.utils.*; make zero changes to legacy modules and their 11 test stubs; ruff passes."
  - id: T2
    title: "triager + replier agents (Template prompts with zero logic)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/agents/triager.py
      - openagents/agents/replier.py
    scope: "triager takes over issue alignment and conflict self-check judgments from align.restate + issuecheck.check (fail-open); replier takes over comment reply judgments from _HUMAN_UNBLOCK_TASK. Both consist of a string.Template PROMPT + OUTPUT_SCHEMA, with zero control flow."
    acceptance: "triager outputs {actionable,reason}; replier outputs {reply,resolved}; the modules contain no def/subprocess (judgment is delegated entirely to the prompt); engine.run_agent can dispatch them."
  - id: T3
    title: "vigil + poll_comments + fleet recipes (pure control flow) + loop context assembly"
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
      - openagents/recipes/poll_comments.py
      - openagents/recipes/fleet.py
      - openagents/runtime/context.py
    scope: "vigil discovers→triager performs triage→dispatches solve_issue (the three deduplication gates remain in the recipe); poll_comments fetches new human comments→replier→posts a signed reply→advances the cursor; fleet reuses the legacy Fleet supervisor to fan out the new stack's vigil. Add module-level for_triage/for_reply assembly to context."
    acceptance: "The three recipes route solely on agents' structured decisions, contain no business judgments, and do not directly call git/gh/subprocess; dependencies (dispatch/spawn) are injectable, allowing hermetic unit tests; ruff passes."
  - id: T4
    title: "Additive CLI wiring for the new stack's three commands: comment polling/Vigil/fleet"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_agents_triager_replier.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_poll_comments.py
      - tests/test_recipe_fleet.py
      - tests/test_cli_new_stack.py
      - scripts/e2e-spec-0061-agents-recipes-flows.sh
    scope: "Add _new_runtime_state_for / _new_vigil_for factories + three subcommands: poll-comments / vigil-new / fleet; make zero changes to legacy vigil/vigil-all/poll routing, allowing both stacks to coexist. Targeted unit tests for each layer + an offline e2e script (ruff+pytest+grep anchors)."
    acceptance: "The three new commands parse and dispatch; vigil-new runs discovery+comment polling on each iteration; fleet skips cwd preflight, as vigil-all does; legacy command behavior remains unchanged. scripts/e2e-spec-0061-agents-recipes-flows.sh passes in full."
---

# 0061 · Architecture Refactoring (Batch Two): Establish the vigil/poll_comments/fleet Recipes + triager/replier Agents + the Full Stable utils Interface

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

Building on the new stack skeleton established in batch one (Spec-0060)—the four layers of agents/recipes/runtime/utils + the single-issue `solve_issue` vertical slice—batch two additively introduces three **loop-based** recipes (`vigil` for discovery → triage → dispatch, `poll_comments` for responding to new human comments on PRs, and `fleet` for concurrency across multiple repositories) and two new agents (`triager` for issue triage and `replier` for comment responses). It also expands utils into a complete stable import interface covering `release/notes/hold/skip/results/identity/config/envcheck/fleet_config`. At this point, the new stack can independently orchestrate the full lifecycle of “an issue from discovery to delivery, plus human-agent conversations on PRs,” without directly importing old modules. This remains strictly additive: the old `orchestrator/vigil/messages/fleet` and their ~11 test stubs receive zero changes, both stacks coexist, and deletion of the old stack and invalidation of old specs are left to the final consolidation batch.

## Motivation

Batch one delivered only `solve_issue`, which “solves a single issue once,” but the autonomous closed loop the product needs still lacks three loops: **discovery** (fetching issues from GitHub and proactively dispatching them), **conversation** (having an agent respond when a human asks follow-up questions on a PR), and **scale** (watching multiple repositories at once). In the old stack, these are implemented by `vigil.py` (248 lines), `messages.py` (a 964-line phase state machine), and `fleet.py`, respectively. They mix “judgment” (is the issue clear enough? what does the comment ask for?) with “mechanics” (deduplication, routing, process orchestration), which is exactly what this refactoring aims to separate.

The motivation for batch two is to reestablish these three parts along the boundary drawn in batch one: **delegate judgment to agents (triager/replier), and keep objective mechanics in deterministic code (recipe control flow + hard gates + utils primitives)**. It also completes the stable utils interface: batch one only re-exported git/github, so as soon as recipes need to fetch comments, determine identity, or read fleet configuration, they would have to import old modules again. The stable interface is not self-contained, so this batch completes it in one pass to the point where “the new stack only needs to import `openagents.utils.*`.”

## Guide-level explanation

Each of the three recipes is a **pure control-flow** vertical slice. It only “calls the engine to dispatch agents + routes based on structured agent verdicts + calls deterministic utils/gates as safeguards.” It contains no business judgment and makes no direct calls to git/gh/subprocess:

- **`recipes.vigil`**: Each iteration calls `github.list_issues(labels)` → dispatches `triager` for each **new** issue (three deduplication gates: no run record AND no remote branch AND no needs-human label) to produce an `actionable` verdict → if True, calls `dispatch` (by default, creates a worktree + assembles Context + runs `solve_issue`); if False, applies needs-human + posts the rationale for clarification and suspends the issue. At the end of each iteration, it also runs the `poll_comments` watch phase once.
- **`recipes.poll_comments`**: Each iteration calls `github.list_open_prs()` → retrieves “new human comments after the cursor” for each PR (`identity.new_human_comments` filters out all machine comments by signature) → dispatches `replier` to produce `{reply, resolved}` → posts a signed reply through `identity.post_signed_comment` → advances the cursor. The two deterministic mechanisms, signature + cursor, prevent a self-triggering infinite loop in which “a reply is treated as a new comment in the next iteration.”
- **`recipes.fleet`**: Starts one isolated subprocess per `RepoPlan` to run the new stack's `vigil` (cwd isolation, because gh is bound to the process cwd). Process supervision (fan-out/log aggregation/crash isolation/Ctrl-C) is independent of the old and new stacks, so it directly reuses the old `fleet.Fleet` supervisor. This module provides just one new capability: “constructing the new stack's vigil as the subprocess target.”

Both agents consist of a logic-free `string.Template` PROMPT + `OUTPUT_SCHEMA`: `triager` restates the issue in three parts and performs a self-check for conflicts between fixes (**fail-open**: allow it through when uncertain); `replier` reads one human comment and decides how to respond and whether to change code (`resolved` indicates whether the request has been sufficiently addressed).

The CLI additively introduces three commands, `poll-comments`/`vigil-new`/`fleet`, and the `_new_vigil_for` factory (shared wiring for fleet subprocesses and the CLI). The old `vigil`/`vigil-all`/`poll` routing remains unchanged down to the last line.

## Reference-level explanation

**Boundary (identical to batch one, word for word)**: judgment → agents; mechanics → deterministic code. Applied to this batch:

- **The deterministic gates kept in recipes are not judgment**: vigil's three deduplication gates (run record/remote branch/presence of the needs-human label), and poll_comments' cursor watermark + signature filtering, all **read objective facts** (whether something exists, whether it is newer than since, whether it carries a signature). They are not judgments such as “is this issue good enough/how should this comment be answered,” so they remain in recipes rather than being delegated to agents.
- **`triager`'s fail-open is the opposite of `reviewer`'s fail-closed**: triage is an “entry gate,” where incorrectly blocking a healthy issue is worse than missing a problem (PR review can still catch a missed problem), so uncertainty means allowing it through; review is an “exit gate,” so it is strict.
- **Context assembly for loop-based recipes uses module-level functions**: the `Context` class is bound to one run for a single issue/PR, but vigil scans issue by issue and poll_comments scans PR by PR, with no “single run instance.” Therefore, `context.for_triage/for_reply` are module-level functions. Their inputs are Issue/Comment objects that the recipe has already fetched during deduplication/cursor processing; they perform only pure assembly and do not read github a second time.
- **Run records use batch one's `RuntimeState`** (a separate file, `runtime-state.json`): both vigil's dispatch deduplication and poll_comments' comment cursors are stored there, with zero file-level conflicts with the old `state.json`. Identity resolution through `_agent_id_for` still uses the old `State` (env > state > generate), keeping identity consistent between the new and old stacks within the same process.
- **All `utils` modules are thin re-exports**: release/notes/hold/skip/results/identity/config/envcheck/fleet_config each only use `from openagents.<mod> import ...` and expose the imports through `__all__`, without copying or changing a single line of the old modules (Occam's razor, principle 1). The only new deterministic primitive is `git.remote_branch_exists` (a free function requiring no instance, needed by vigil's deduplication gate, whereas the old `Workspace` only has an instance method).
- **`fleet` reuses the old `Fleet` supervisor**: `from openagents.fleet import Fleet, _QueueWriter, default_queue`—process fan-out/log aggregation with prefixes/crash isolation/Ctrl-C are pure mechanisms, and rewriting them would be duplication (violating Occam's razor). This module only replaces the per-repo target `_run_repo`, having it construct the **new stack's** vigil through `cli._new_vigil_for`.

**Single wiring point**: `cli._new_vigil_for(ctx)` constructs backend/RuntimeState/agent_id once and returns `(Vigil, a partially applied poll function)`. Both the CLI's `vigil-new` and fleet's subprocess `_run_repo` call it, ensuring consistent backend/state/identity within the Vigil process.

## Drawbacks

- **Cognitive load and size while both stacks coexist**: the new `vigil`/`poll_comments`/`fleet`/`triager`/`replier` sit alongside old modules with the same names, so readers need to know “which belongs to the new stack.” Mitigation: the first line of each module's docstring identifies Spec-0061 and explicitly states its relationship to the old module; CLI help uses the prefix `[New stack]`.
- **`poll_comments` does not cover all the gates in the old `messages.poll`**: the old poll has a full set of mergeability/CI/e2e/review/merge phase gates. The new stack puts “the complete solution of one issue” inside synchronous `solve_issue`, while poll_comments only handles “a human asks a follow-up question on a PR → respond.” This is an **intentional reassignment of responsibilities** (principle 1), but it means the new stack currently does not drive “the automatic merge pipeline for already-open PRs.” Reestablishing that pipeline along the new boundary is left to a later batch.
- **Thin utils re-exports add a layer between the import interface and the implementation**: one extra level of indirection. Mitigation: re-export modules are extremely short (pure imports + `__all__`) and provide substantial regression safety by allowing “zero changes to old modules and 11 test stubs,” yielding a positive net benefit.
- **`replier` runs with the repo root as work_dir in this batch**: substantive “code changes based on comments” require a PR worktree. This batch only completes responses/Q&A (see Unresolved).

## Rationale and alternatives

- **Alternative A: Physically move old modules into utils (instead of thin re-exports)**. This would change the import paths of identity/github/fleet_config and others all at once, breaking ~11 test stubs in the process, and would conflict with the batch discipline of “additive, zero changes to the old stack.” Alternative B in batch one's Spec-0060 already explicitly deferred physical relocation to the consolidation batch; this batch continues using thin re-exports.
- **Alternative B: Port the old messages.poll's 964-line state machine verbatim into poll_comments**. This would defeat the purpose of the refactoring (judgment and mechanics would remain mixed together) and bring all the old stack's historical baggage into the new stack. The choice is to **reestablish** a comment-response vertical slice with a single responsibility along the new boundary, leaving reestablishment of the “automatic PR merge pipeline” to a later batch.
- **Alternative C: Rewrite process supervision in fleet**. This would simply duplicate the old `Fleet` (violating Occam's razor). The choice is to reuse the supervisor and replace only the per-repo target.
- **Alternative D: Hard-code vigil's dispatch action in the recipe**. Unit tests would then necessarily invoke real git/backends. The choice is to make `dispatch` an injectable dependency (defaulting to `dispatch_solve`), mirroring fleet's injectable `spawn`, so the recipe remains hermetically testable.

## Prior art

- **Spec-0060 (batch one)**: established the four-layer boundary and `solve_issue`/`engine`/`gates`/`Context`/`RuntimeState`; this batch builds directly on it.
- **Old `vigil.py` (RFC-0004/0007)**: three-way discovery routing (fresh/resume/None) + three deduplication gates + per-issue error isolation + once/long-running modes. This batch's `recipes.vigil` retains its deduplication/isolation/dual-mode skeleton, replacing “precheck_issue conflict judgment” with a verdict from the `triager` agent.
- **Old `messages.py` (RFC-0012/Spec-0032)**: `identity.new_human_comments` resolves self-loops through two hard constraints, “new comments only + unsigned human comments only.” This batch's `poll_comments` directly reuses that primitive for deduplication.
- **Old `fleet.py` (Spec-0027)**: the rationale for cwd isolation through one process per repository, and the `Fleet` supervisor, are reused in this batch.
- **Choice of `string.Template`**: already justified in batch one (f-strings that cannot be stored / `.format`, which conflicts with JSON examples / `.md` without a schema were all ruled out); both agents in this batch continue using it.

## Unresolved questions

- **Substantive code changes by replier require a PR worktree**: in this batch, replier runs in the supplied work_dir (the repo root), completing “responses/Q&A.” “Actually changing code based on comments and pushing it” requires first using `Workspace.ensure` to check out a worktree for the PR branch. This is left to a later batch (at that point, poll_comments will need to establish a PR → issue → worktree mapping).
- **The new stack lacks an “automatic merge pipeline for already-open PRs”**: the CI/mergeability/review/merge gates from the old messages.poll have not yet been reestablished in the new stack, so vigil-new currently handles “dispatching solutions + responding to comments” but does not automatically advance merges. When to reestablish this pipeline, and in what recipe form, is left to a later batch.
- **When to unify the two sets of state**: `runtime-state.json` and `state.json` coexist. Whether to perform a final migration or discard the old state will be decided in the consolidation batch for the full vigil migration (carrying forward the same Unresolved item from batch one).
- **triager and the old issuecheck's stale-claim reclamation are not included**: the old vigil's signed claim notes + stale-claim reclamation (Spec-0039/0049) have not been ported into this batch's vigil (deduplication only uses the coarse “remote branch exists” gate). When cross-backend claim ownership determination should enter the new stack's vigil is left to a later batch.

## Future possibilities

- **Move the PR auto-merge pipeline to the new stack**: Rebuild the old messages.poll mergeability/CI/e2e/review/merge stages as a single `recipes.merge_pr`, following the responsibility boundaries (keep deterministic gates in the recipe and delegate review judgments to a reviewer agent), completing the new stack’s “watch → merge” loop.
- **Upgrade replier to “modify code based on comments”**: After connecting it to the PR worktree, upgrade replier from “responding” to “responding + iterative delivery,” reusing `solve_issue`’s deliver + hard gate requiring head to advance.
- **Bring claim ownership + expired-claim reclamation into the new stack’s vigil**: Move `identity.latest_claim` + the expiration threshold into the deduplication gate in `recipes.vigil`, supporting claims across processes and multiple backends.
- **Consolidation batch**: Physically move old modules into utils/delete the old orchestrator/vigil/messages/fleet + invalidate their specs, unifying the two stacks.
