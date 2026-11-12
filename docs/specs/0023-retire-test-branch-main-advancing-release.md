---
number: "0023"
title: "Retire the test branch: keep main advancing continuously + publish releases through release/vX.Y.Z version branches"
issue: 68
slug: retire-test-branch-main-advancing-release
summary: "Retire the test branch and reverse the old \"test gating\" model: main becomes the branch for day-to-day automated flow (automatic merging after the reviewer gate passes and CI is fully green, keeping main advancing continuously). When releasing, publish main to a release/vX.Y.Z branch and create a vX.Y.Z tag (automatically increment the version number from the latest tag, defaulting to patch). The human touchpoint changes from promote to release; rename and redirect promote.py to release.py, change the default base from test→main throughout the pipeline, remove test branch bootstrapping, and trigger CI only for main."
tasks:
  - id: T1
    title: "github layer: default base to main + remove test branch bootstrapping"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0012/T2
        type: supersedes
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
      - tests/test_ensure_prerequisites.py
    scope: "Change the default base for create_pr from test→main; ensure_prerequisites no longer creates the test branch (narrow its scope to pre-creating workflow labels only); delete ensure_branch, which has no callers, together with its 3 unit tests; leave branch_ci_green unchanged."
    acceptance: "Unit tests assert that create_pr passes through --base main by default; ensure_prerequisites only orchestrates pre-creation of workflow labels; ensure_branch and its unit tests have been deleted; branch_ci_green behavior remains unchanged."
  - id: T2
    title: "orchestrator + Vigil: default base to main"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to:
      - ref: 0012/T5
        type: supersedes
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
      - openagents/vigil.py
    scope: "Change DEFAULT_BASE from test→main; start_rfc/changed_spec_group consequently use main as their baseline; update documentation comments in Vigil to refer to main."
    acceptance: "Unit tests assert that start_rfc passes the default base=main through to create_pr; changed_spec_group uses base=main; no references to test remain in Vigil comments."
  - id: T3
    title: "promote→release module: create a release/vX.Y.Z branch + create a tag + increment the version"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to:
      - ref: 0012/T4
        type: supersedes
    parallel: false
    files:
      - openagents/release.py
      - tests/test_release.py
      - openagents/promote.py
      - tests/test_promote.py
    scope: "Rename promote.py to release.py; if the preflight checks for release(*, state, bump) pass (no BLOCKED run ∧ no open PR with needs-human ∧ branch_ci_green(main)), read the latest vX.Y.Z tag and increment it according to bump (no tag→v0.1.0), create a release/vX.Y.Z branch, create the tag, and push; add pure functions for version parsing/incrementing; delete promote.py/test_promote.py."
    acceptance: "Unit tests stub github/state/subprocesses: BLOCKED run→released=False; needs-human PR→False; main CI not green→False; all checks pass→create branch+create tag+push, with the correct version; no tag→v0.1.0; bump=minor/major takes effect."
  - id: T4
    title: "CLI: release subcommand + default base to main"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
    relates-to:
      - ref: 0012/T6
        type: supersedes
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: "Change the --base default for rfc/vigil from test→main; change the promote subcommand→release subcommand (_cmd_promote→_cmd_release, add --bump {patch,minor,major} with patch as the default), route to release.release, and set the exit code according to ReleaseResult."
    acceptance: "Unit tests assert that the --base default is main; the release subcommand routes to release.release and sets the exit code according to the result; --bump is passed through to release()."
  - id: T5
    title: "CI workflow + indexheal tests + wrap up old spec 0012"
    status: done
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - .github/workflows/ci.yml
      - tests/test_indexheal.py
      - docs/specs/0012-test-branch-gated-flow.md
      - openagents/messages.py
      - openagents/state.py
      - scripts/e2e-spec-0023-release-flow.sh
    scope: "Change ci.yml trigger branches from [main,test]→[main]; change the test_indexheal base from test→main (assert origin/main); add a superseded banner to the body of 0012 pointing to 0023; correct documentation drift in messages.py/state.py comments: promote→release and test staging environment→main; add an e2e script."
    acceptance: "ci.yml on.pull_request.branches contains only main; indexheal tests assert that origin/main is merged; spec validate reports no errors."
---

# 0023 · Retire the test branch: continuous advancement of main + releases from release/vX.Y.Z version branches

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Retire the long-lived `test` preview-environment branch and switch the target of the routine automated workflow from `test` to `main`: issue→PR work now branches from `main` and uses `main` as its base, then automatically merges back into `main` after passing the same reviewer gate + CI gate, so `main` advances continuously. Formal releases use a separate `release/vX.Y.Z` branch and a `vX.Y.Z` tag (the version is incremented semantically from the latest tag, with patch as the default). The human gate moves downstream from `promote` (fast-forwarding main from test) to `release` (deciding to publish a version).

## Motivation

**Current state: the test-branch gating workflow (restated in full, without requiring readers to consult another spec).** OpenAgents previously used a “test-branch gating workflow”:

- `test` is a long-lived “preview-environment” branch. After each issue is claimed, the agent creates a worktree from `test`, drafts changes, and opens a PR with **the PR base locked to `test`**. After N reviewers review the PR in parallel (with verdicts aggregated to require unanimous PASS) and all CI checks pass, it **automatically merges back into `test`**. Changes thus accumulate continuously in `test`, making it the “latest version available to try.”
- `main` does not participate in the routine workflow and remains frozen. It is **fast-forwarded** from `test` only when a human runs `openagents promote`. Before `promote`, three preflight checks run, and promotion proceeds only if all pass: ① no suspended (`STATUS_BLOCKED`) runs; ② no open PRs labeled `needs-human`; ③ all CI checks on the HEAD of the `test` branch pass.
- Humans have only two touchpoints: “file an issue” and “promote to production.” The intervening issue→PR→merge back into test workflow is fully automated.

Several pieces of “test-specific” logic in the code support this workflow: the base defaults throughout the pipeline (`orchestrator.DEFAULT_BASE`, the CLI's `--base`, and `github.create_pr`'s `base`) are all `"test"`; during cold start, `ensure_prerequisites` idempotently creates the `test` branch as a fallback (otherwise, the absence of `test` in a fresh repository would cause prepare to fail indefinitely); index self-healing, `indexheal`, also uses `origin/test` as its merge baseline.

**Problem: why change this.** The “preview environment” intermediary is no longer needed. The desired new way of working is: **`main` itself advances continuously** (without a `test` branch ahead of it as a buffer), while **formal releases** use a separate `release` branch. This moves the human gate from “each promotion of test to main” **downstream to “deciding to publish a version”**—main keeps advancing during routine work, and releasing is when a human makes the high-level decision.

## Guide-level explanation

**Shift all three roles above together by one step**:

| Role | Current state (superseded) | This feature |
|------|------|------|
| Branch for the routine automated workflow (base for issue→PR, target for automatic merges) | `test` (preview environment) | **`main`** |
| Release target gated by a human | `main` (fast-forwarded by promote) | **`release/vX.Y.Z`** |
| Human gating touchpoint | `promote` | **`release`** |

For users: file issues as before during routine work, and the agent automatically merges changes into `main`; when you want to publish a release, run `openagents release [--bump patch|minor|major]` once. After all preflight checks pass, it materializes a `release/vX.Y.Z` branch from the current HEAD of `main` and creates an immutable tag.

## Reference-level explanation

The changes are divided into 5 Tasks (see the DAG below; `files` do not overlap, and each Task has a single writer):

1. **T1 github layer** — The default `base` value in `create_pr` is the lowest-level source of the base throughout the pipeline: test→main. Delete the fallback code in `ensure_prerequisites` that creates the `test` branch (`main` is the default branch and always exists, so no bootstrapping is needed). As a result, `ensure_branch` has no remaining callers, so delete it together with its 3 unit tests (Occam's razor); leave `branch_ci_green` unchanged (release preflight checks use it for main), and retain idempotent pre-creation of workflow labels (needs-human, etc.).
2. **T2 orchestrator + vigil** — `orchestrator.DEFAULT_BASE` is the single constant supplying the worktree baseline and PR base: test→main. `cli.py` passes `DEFAULT_BASE` through as the merge baseline for `indexheal` self-healing, so changing this constant automatically makes `git merge origin/main` follow suit; `vigil.py` receives its `base` from the CLI and has no default of its own, so only its documentation comments need correction.
3. **T3 promote→release module** (depends on T1) — Copy the three preflight checks unchanged (no BLOCKED runs ∧ no open PRs labeled needs-human ∧ all CI checks on the target branch pass), changing only the branch checked for green CI from test to main. Change the action from “fast-forward main” to “materialize a version”: `_latest_version()` uses `git tag --list 'v*'` to find the greatest `vX.Y.Z` (sorted semantically); `_next_version(latest, bump)` increments according to `bump∈{patch,minor,major}` (no tag→`v0.1.0`); `git push origin main:refs/heads/release/vX.Y.Z` creates the release branch + `git tag vX.Y.Z` pins the immutable snapshot. `ReleaseResult(released, version, reason)` replaces `PromoteResult`.
4. **T4 CLI** (depends on T2 and T3) — The CLI is the single point where human touchpoints converge. Rename the `promote` subcommand to `release` in its entirety, and add `--bump` forwarding in `_cmd_release`; change the `--base` defaults for `rfc`/`vigil` from test→main together with T2's `DEFAULT_BASE`.
5. **T5 cleanup** (no dependencies; can run in parallel) — Remove test from `ci.yml`'s `pull_request.branches` (release branches are materialized from main after its CI has passed and do not accept PRs); change the stub assertion in `test_indexheal` from `origin/test`→`origin/main`; add a superseded banner to Spec-0012; clean up documentation drift in messages.py/state.py.

**End-to-end verification**: `bash scripts/e2e-spec-0023-release-flow.sh` (runs ruff + pytest offline and demonstrates base=main + release materialization).

Dependency DAG: `T1 → T3`, `T2 → T4`, `T3 → T4`; T5 is independent.

## Drawbacks

- After removing the “preview environment” buffer, changes merged into `main` immediately become the latest trunk state, eliminating the buffer of “accumulating changes in test before putting them into production”—but the reviewer gate + all-green CI gate remain unchanged, so the quality threshold is not lowered.
- Introducing both `release/*` branches and tags as release artifacts adds a conceptual layer compared with simply “fast-forwarding main.”

## Rationale and alternatives

- **Why reverse the model instead of making small adjustments**: in the old model, `main` was frozen and depended on humans running promote, tying humans to the details of “each production rollout”; after the reversal, humans intervene only at the high-level decision point of “publishing a release,” consistent with OpenAgents' goal of “humans providing high-level oversight.”
- **Alternative: create a GitHub Release page**. Rejected (YAGNI): creating a `release/vX.Y.Z` branch + a git tag already satisfies “immutable snapshot + rollback capability”; a Release page can be added later (see Future possibilities).
- **Alternative: use dates/build numbers for versions**. Rejected: the three-part semantic version `vX.Y.Z` (patch increments by default) is the most intuitive for humans, and `_next_version` is a pure function that is easy to test hermetically.
- **Leave review/CI/messages internal logic unchanged**, changing only the base they depend on—minimizing the blast radius (decoupling, principle 10).

## Prior art

Semantic versioning (SemVer `vX.Y.Z`) and “continuous trunk advancement + releases from version branches” are mainstream release models in the industry (for example, most libraries use trunk-based development + tagged releases). This feature adopts the core ideas of “trunk advances, tags pin versions” without introducing a heavier release train process.

## Unresolved questions

None. The three preflight checks, version increment semantics, and release artifact form (branch + tag) have all been settled within this group.

## Future possibilities

- Automatically create a GitHub Release page / generate a changelog on top of `release/vX.Y.Z` (currently YAGNI).
- Extend `release` preflight checks into configurable policies (such as requiring minimum coverage).
