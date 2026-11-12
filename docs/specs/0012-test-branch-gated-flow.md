---
number: "0012"
title: "test branch gating workflow — humans intervene only when filing an issue and during promote"
issue: 32
slug: test-branch-gated-flow
summary: "Switch to a test branch gating workflow, with humans intervening only when filing an issue and during promote to production: N reviewers review in parallel and their decisions are aggregated; the promote module runs preflight checks and then fast-forwards main. All intermediate steps are fully automated."
tasks:
  - id: T1
    title: "reviewer orchestration module (N parallel reviewers + decision aggregation)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/reviewer.py
      - tests/test_reviewer.py
    scope: "Create reviewer.py: the ReviewDecision data model and the review() function (use a thread pool to dispatch N backend.run calls in parallel, parse the decision token in each AgentResult.summary, and aggregate the results using a unanimous PASS requirement); include two built-in review task templates, rfc/code (port the PASS/REWORK/RETHINK rubric from vigil-reviewer); read N from OPENAGENTS_REVIEWERS (default: 1)."
    acceptance: "Unit tests with a stubbed AgentBackend, covering: N=1 PASS→passed=True; N=3 with one REWORK→passed=False and feedback includes that review's feedback; RETHINK is classified as non-PASS, like REWORK; robust decision token parsing (case/prefixes/suffixes)."
  - id: T2
    title: "github extensions (base/merge/label/branch)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: "Add a base parameter to create_pr (→ --base); add merge_pr, add_label, ensure_branch (idempotent), and branch_ci_green. Reuse _run_gh/_gh_json (RFC-0010 retries) and the existing _classify_checks."
    acceptance: "Unit tests with stubbed subprocesses to verify that each function constructs the correct gh arguments; ensure_branch does not raise an error when the branch already exists (idempotent); branch_ci_green returns True when all checks are green and False when any check fails; create_pr(base=...) passes through --base."
  - id: T3
    title: "state extensions (rounds + STATUS_BLOCKED)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
    scope: "Add the STATUS_BLOCKED constant; add rounds:int=0 to RunRecord (the default ensures that RunRecord(**old_record) does not raise an error for old records); add increment_rounds/reset_rounds."
    acceptance: "Unit tests: loading an old state.json without the rounds key does not raise an exception and yields rounds=0; increment_rounds returns the incremented value and persists it to disk; reset_rounds resets it to zero; all_runs does not inadvertently change STATUS_BLOCKED."
  - id: T4
    title: "promote module (preflight checks + fast-forward main)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/promote.py
      - tests/test_promote.py
    scope: "Create promote.py: PromoteResult + promote(), running preflight checks (no STATUS_BLOCKED run ∧ no open PR with needs-human ∧ branch_ci_green(test)); if they pass, call ensure_branch as a fallback safeguard + git push origin test:main."
    acceptance: "Unit tests with stubbed github/state/subprocesses: a BLOCKED run→promoted=False with reason identifying the cause; a needs-human PR→False; CI not green→False; all checks pass→execute push and promoted=True."
  - id: T5
    title: "Gate integration (messages routing + orchestrator review/base)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - openagents/orchestrator.py
      - tests/test_messages.py
      - tests/test_orchestrator.py
    scope: "orchestrator: DEFAULT_BASE=\"test\", pass base through from start_rfc to create_pr, add review_rfc/review_code, and call reset_rounds at the end of implement. messages: integrate review gates into _process_rfc_review/_process_coding (PASS→add label/merge; non-PASS→rounds++ followed by refine/iterate; exceeding K→BLOCKED+needs-human), and add MAX_ROUNDS/BLOCKED_LABEL."
    acceptance: "Unit tests with stubbed reviewer/github/state: rfc gate PASS→apply rfc-approved and call implement; rfc gate non-PASS with rounds<K→refine and rounds++; coding gate CI green+PASS→merge_pr+DONE+rebase; coding gate non-PASS exceeding K→STATUS_BLOCKED+needs-human while leaving the PR open; preserve CI fail/pending behavior."
  - id: T6
    title: "CLI/vigil wiring (promote command + base default + init fallback safeguard)"
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on:
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/vigil.py
      - tests/test_cli.py
      - scripts/e2e-rfc-0012-gated-flow.sh
    scope: "cli: change the --base default for rfc/vigil to test; call ensure_branch from _cmd_init; register the promote subcommand + _cmd_promote. vigil: change the default base to test accordingly. Add an e2e script."
    acceptance: "Unit tests: the promote subcommand routes to promote.promote and sets the exit code according to the result; the --base default is test; init triggers ensure_branch. The e2e script can run independently (see the test plan)."
---

# 0012 · test Branch Gated Workflow — Humans Intervene Only to “File Issues” and “promote”

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine rust-RFC sections. -->

## Summary

> **⚠️ This spec has been superseded by Spec-0023 (retirement of the test branch).** This file is a historical
> design snapshot from the “test branch gated workflow” era: at that time, `test` was the long-lived staging branch, the entire issue→PR flow used test as its base and automatically merged back into test, and `main` was
> only fast-forwarded by `openagents promote`. Spec-0023 reversed this model—`main` became the branch for routine automated workflows and advances continuously,
> while releases moved to `release/vX.Y.Z` branches + tags (`openagents release` replaced promote). Through
> `supersedes`, its T2/T4/T5/T6 respectively supersede this spec’s T2 (github base), T4 (promote module), T5 (orchestrator base),
> and T6 (CLI/base). This file is retained as a historical reference and no longer reflects the current code.

Restructure the OpenAgents delivery workflow into a “test branch gated workflow,” with humans intervening at only two touchpoints: **“filing issues”** and **“promoting to production.”** `test` is a long-lived staging branch; issue→PR→review→merge back into test is fully automated. Each PR is reviewed by N reviewers in parallel and proceeds only after their decisions aggregate to “unanimous PASS”; once all reviewer/CI gates pass, it automatically merges back into `test`. A non-PASS result triggers automatic iteration; exceeding the round limit suspends the run and applies `needs-human`. `main` normally remains frozen and is fast-forwarded from `test` only when a human runs `openagents promote` (after all three preflight checks pass).

## Motivation

Before this feature, humans had to intervene repeatedly at the level of code details: deciding, for each PR, whether to merge it and when to deploy. The goal is to reduce human involvement to two points of **high-level oversight**—deciding “what to do” (filing issues) and “whether to deploy” (promote)—while automating all intermediate review/merge/iteration steps (consistent with the OpenAgents goal that “humans provide high-level oversight and are no longer responsible for details”).

To achieve this goal, this group establishes and codifies the following decisions (other specs reference them as “see Spec-0012 Decision N,” so they are restated in full here to make this document self-contained):

- **Decision 1 (two-touchpoint gating model)**: Humans intervene only to “file issues” and “promote.” After an issue is claimed, a worktree is created from `test`, changes are drafted, and a PR is opened; the PR base is fixed to `test`. Once review + CI all pass, the PR automatically merges back into `test`, so `test` continuously accumulates changes as the “latest version available to try.”
- **Decision 2 (N parallel reviews + unanimous PASS aggregation)**: Each PR is assigned N reviewers (`backend.run` calls run in parallel in a thread pool), each producing a PASS/REWORK/RETHINK decision. The aggregation rule is “only unanimous PASS counts as passing”; any REWORK/RETHINK means non-PASS, and the corresponding feedback is collected. N is controlled by the environment variable `OPENAGENTS_REVIEWERS` (default 1). rfc review and code review each have their own review task template (ported from the vigil-reviewer rubric).
- **Decision 3 (round limit + automatic suspension)**: A non-PASS result does not cause immediate abandonment; instead, `rounds++` is followed by automatic refine (rfc phase)/iterate (coding phase). If the limit `MAX_ROUNDS` (K) is exceeded, the run is set to `STATUS_BLOCKED` and the PR is labeled `needs-human`, **without closing the PR**, for a human to take over. The `rounds` counter is reset to zero by `reset_rounds` when `implement` succeeds.
- **Decision 4 (three promote preflight checks + fast-forward semantics)**: Before `promote`, run three preflight checks and promote only if all pass: ① no suspended (`STATUS_BLOCKED`) runs; ② no open PRs labeled `needs-human`; ③ all CI checks for the `test` branch HEAD are green. After they pass, use `git push origin test:main` to **fast-forward** `main` to `test`; `main` normally remains frozen and advances only here.
- **Decision 5 (test as the default base throughout + test branch bootstrapping)**: Unify the default base throughout the workflow (`orchestrator.DEFAULT_BASE`, `cli`’s `--base`, and `github.create_pr`’s `base`) as `"test"`. During a cold start, `init`/`ensure_prerequisites` use the idempotent `ensure_branch` to ensure that the `test` branch exists, preventing prepare from failing indefinitely because a new repository lacks `test`.

> Note: The parts of these decisions concerning base/promote/bootstrapping (Decision 4 and Decision 5) have been reversed by Spec-0023—`main` became the branch for routine automated workflows, and releases moved to `release/vX.Y.Z` + tags. They are restated here solely to preserve their historical semantics for retrospective references.

## Guide-level explanation

The division of responsibilities among the three roles is shown below (this is what Spec-0023 later reversed):

| Role | This spec (the test gating era) |
|------|------|
| Branch for routine automated workflows (issue→PR base and automatic merge target) | `test` (staging) |
| Human-gated release target | `main` (fast-forwarded by promote) |
| Human gating touchpoints | File issues + `promote` |

For users: file issues as usual, and the agent automatically branches from `test`, drafts changes, opens a PR, and runs N parallel reviews. With PASS + green CI, it automatically merges back into `test`; if repeated attempts fail to resolve the problems, it suspends the run and applies `needs-human` to await a human. When ready to deploy, run `openagents promote` once; after all three preflight checks pass, it fast-forwards `main` to `test`.

## Reference-level explanation

The changes are divided into 6 Tasks (see the DAG below; `files` are mutually exclusive, with a single writer per Task):

1. **T1 reviewer orchestration module** (no dependencies) — Create `reviewer.py`: the `ReviewDecision` model + `review()` (dispatch N `backend.run` calls in parallel through a thread pool, parse the decision token in each `AgentResult.summary`, and aggregate using “unanimous PASS”), with two built-in templates for rfc/code (porting the vigil-reviewer PASS/REWORK/RETHINK rubric). Read N from `OPENAGENTS_REVIEWERS` (default 1). Implements Decision 2.
2. **T2 github extensions** (no dependencies) — Add a `base` parameter to `create_pr` (→`--base`); add `merge_pr`, `add_label`, `ensure_branch` (idempotent), and `branch_ci_green`; reuse `_run_gh`/`_gh_json` (RFC-0010 retries) and `_classify_checks`. Provides the underlying capabilities for Decisions 4/5.
3. **T3 state extensions** (no dependencies) — Add the `STATUS_BLOCKED` constant; add `rounds:int=0` to `RunRecord` (the default ensures backward compatibility when constructing `RunRecord(**old_record)`); add `increment_rounds`/`reset_rounds`. Supports the round counter and suspended state in Decision 3.
4. **T4 promote module** (depends on T2, T3) — Create `promote.py`: `PromoteResult` + `promote()`. If all three preflight checks pass (no `STATUS_BLOCKED` runs ∧ no `needs-human` open PRs ∧ `branch_ci_green(test)`), use `ensure_branch` as a fallback + `git push origin test:main`. Implements Decision 4.
5. **T5 gate integration** (depends on T1, T2, T3) — `orchestrator`: `DEFAULT_BASE="test"`, pass base through from `start_rfc` to `create_pr`, add `review_rfc`/`review_code`, and call `reset_rounds` at the end of `implement`; `messages`: integrate the review gate into `_process_rfc_review`/`_process_coding` (PASS→label/merge, non-PASS→`rounds++` then refine/iterate, exceeding K→`STATUS_BLOCKED`+`needs-human`), and add `MAX_ROUNDS`/`BLOCKED_LABEL`. Connects Decisions 1/2/3 into an automated loop.
6. **T6 CLI/vigil wiring** (depends on T4, T5) — `cli`: change the default `--base` for `rfc`/`vigil` to `test`, call `ensure_branch` from `_cmd_init` as a fallback, and register the `promote` subcommand + `_cmd_promote`; the default base for `vigil` consequently becomes test; add an e2e script. Completes the default base and test bootstrapping in Decision 5 and exposes promote as a human touchpoint.

**End-to-end validation**: `bash scripts/e2e-rfc-0012-gated-flow.sh` (runs ruff + pytest offline and demonstrates the base=test gated workflow + promote fast-forwarding main).

Dependency DAG: `T2 → T4`, `T3 → T4`, `T1 → T5`, `T2 → T5`, `T3 → T5`, `T4 → T6`, `T5 → T6`. T1/T2/T3 have no dependencies and can start in parallel.

## Drawbacks

- `main` remains frozen for long periods and advances only through a human running `promote`, tying humans to the detailed decision of “every deployment” (which is precisely what motivated Spec-0023 to reverse this model).
- Adds a long-lived `test` branch and its bootstrapping logic (`ensure_branch` as a fallback), introducing another concept into the cold-start path.
- N parallel reviews multiply the backend invocation cost per PR (N times as many `backend.run` calls).

## Rationale and alternatives

- **Why use test for staging instead of merging directly into main**: At the time, the intent was for `main` to retain the meaning of “deployed,” with a human explicitly gating deployment through promote, while `test` served as a buffer for the “latest version available to try.” (Spec-0023 later deemed this intermediary unnecessary and reversed the model.)
- **Why aggregate with unanimous PASS instead of a majority vote**: Review is a quality gate, so conservatism is preferable—any reviewer returning REWORK/RETHINK triggers iteration, preventing “the majority passes it, but a minority finds a real problem” from being drowned out.
- **Why promote uses a fast-forward push instead of a merge**: `main` only follows `test` and produces no independent commits, ensuring that `main` is a subset of `test`, history remains linear, and rollback is straightforward.
- **Alternative: humans manually merge each PR**. Rejected: this conflicts with the goal that “humans provide only high-level oversight”; intermediate steps should be automated.
- **Round limit + suspension instead of unlimited retries**: Prevents agents from spinning on PRs they cannot fix. After K rounds are exceeded, hand over to a human (`needs-human`), directing human attention to the few PRs that are truly stuck.

## Prior art

- “Staging branch + manual promote to production” is a common branching and release model.
- N parallel reviews + decision aggregation are ported from the vigil-reviewer PASS/REWORK/RETHINK rubric.
- Retry wrappers for `gh` invocations reuse the existing `_run_gh`/`_gh_json` from RFC-0010.

## Unresolved questions

None. The review aggregation rule, round-limit semantics, and three promote preflight checks have all been settled within this group (see Spec-0023 for subsequent changes to the base/release model).

## Future possibilities

- The number of reviewers N and round limit K could be extended into policies configurable per repository/per spec.
- Promote preflight checks could include additional thresholds (such as minimum coverage).
- (Already implemented in Spec-0023) Reverse “test staging + promote fast-forward” into “main advancing continuously + versioned release branches.”
