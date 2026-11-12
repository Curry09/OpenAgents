---
number: "0009"
title: "Automatically rebase other open PRs after a merge"
issue: 24
slug: auto-rebase-open-prs-on-merge
summary: "After a PR is merged into main, automatically rebase the remaining open PRs onto the latest main, eliminating manual rebasing. Includes list_open_prs/update_branch in the github layer, a fan-out module, post-merge integration, and a manual sync-prs command."
tasks:
  - id: T1
    title: "`list_open_prs` + `update_branch` in the github layer"
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: "Add two module-level functions in github.py: list_open_prs() (gh pr list --state open --json number,url, parsed into a list of PR objects) and update_branch(*, pr_number, rebase=False) (gh pr update-branch <n> [--rebase], returning True on success, swallowing the “already up to date” case and returning False, and raising GithubError for conflicts or other failures). Reuse the existing _run_gh / _gh_json / PR. Reference RFC-0009 in comments within the function bodies."
    acceptance: "Unit tests cover list_open_prs parsing (including an empty list) and the three outcomes of update_branch (updated→True / already-up-to-date→False / conflict→GithubError); ruff + pytest all pass."
  - id: T2
    title: "`rebase_open_prs` fan-out module"
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/rebase.py
      - tests/test_rebase.py
    scope: "Create openagents/rebase.py and implement rebase_open_prs(*, merged_pr_number=None, rebase=False): call github.list_open_prs, exclude merged_pr_number, and call github.update_branch for each PR; on a conflict (GithubError), post a comment indicating the conflict via github.post_comment and continue; return [{pr_number, result}]. Define the conflict comment text as a module constant. Reference RFC-0009 in comments."
    acceptance: "Unit tests (monkeypatching github.list_open_prs / update_branch / post_comment) cover: normal updates, exclusion of the merged PR, classification of up-to-date results, conflicts→posting a comment without interrupting subsequent processing, and an empty open PR list; ruff + pytest all pass."
  - id: T3
    title: "Post-merge fan-out integration in `messages.poll`"
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
    scope: "In messages._process_run, after detecting is_merged and setting STATUS_DONE, add a call to rebase.rebase_open_prs(merged_pr_number=pr_number); the merged event may include the synchronization results. Leave the remaining routing logic unchanged. Reference RFC-0009 in comments."
    acceptance: "A unit test asserts that “rebase.rebase_open_prs is called with the correct merged_pr_number when a merge is detected” (monkeypatching the rebase function); existing poll test cases have no regressions; ruff + pytest all pass."
  - id: T4
    title: "Manual `openagents sync-prs` command"
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: "Register the sync-prs subcommand (--merged, --rebase) in cli.build_parser, add a _cmd_sync_prs handler that performs a lazy import and calls rebase.rebase_open_prs, and print a summary of the results; wire it into the _dispatch handlers table. Reference RFC-0009 in comments."
    acceptance: "Unit tests assert argument parsing and handler pass-through (monkeypatch rebase.rebase_open_prs and verify the merged_pr_number / rebase arguments and exit code); ruff + pytest all pass."
  - id: T5
    title: "End-to-end script"
    status: done
    priority: P1
    tags:
      - cli
      - ci
      - automation
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-rfc-0009-auto-rebase.sh
    scope: "Add scripts/e2e-rfc-0009-auto-rebase.sh: create two open PRs in a test repository, merge one of them, run openagents sync-prs --merged <n> (or one poll cycle), verify that the other PR branch has incorporated the latest main (using gh pr view --json mergeStateStatus or by comparing commits), and demonstrate commenting in a conflict scenario. Include prerequisites and execution instructions in the script (following the style of the existing scripts/e2e-rfc-000X-*.sh scripts)."
    acceptance: "The script can run independently and prints the results of each step; README/RFC provides startup instructions; the bash -n syntax check passes."
---

# 0009 · Automatically rebase other open PRs after a merge

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is the group-level overview in the nine-section rust-RFC format. -->

## Summary

After a PR is merged into `main`, automatically rebase all remaining open PRs, one by one (`gh pr update-branch`), onto the latest `main`, eliminating the need to rebase each one manually. The implementation has four layers: new `list_open_prs` / `update_branch` functions in the github layer; a `rebase.py` fan-out module that centrally orchestrates “list open PRs → exclude the merged PR → update branches one by one → comment on conflicts without stopping”; automatic fan-out triggered by `messages.poll` when it detects a merge; and a manual `openagents sync-prs` command as a fallback.

## Motivation

OpenAgents is a decentralized framework for collaboration among multiple agents. It is common for several issues to have agents assigned to them at the same time, each with an open PR progressing in parallel. When one of those PRs is merged into `main` first, the base of the remaining open PR branches falls behind: they are still based on the old `main`, and merging them directly later can easily produce outdated diffs or conflicts with the new mainline.

Without automation, someone must either click GitHub's “Update branch” button for each PR or wait until a PR is being processed before discovering that it needs a rebase. The former ties people back to the details of “cleaning up after every merge,” contrary to OpenAgents' goal of “people overseeing the big picture without handling code-level details”; the latter exposes conflicts too late.

The desired workflow is: **as soon as a PR is merged into `main`, the framework automatically brings the remaining open PRs up to the latest mainline**. Branches that can be rebased automatically are updated directly. If a conflict cannot be resolved automatically, a comment is left on that PR indicating that human/agent intervention is needed, without blocking the processing of other PRs. This keeps the latest mainline as the base for all branches when multiple PRs are progressing in parallel, and exposes conflicts early on the corresponding PRs.

## Guide-level explanation

For users: file issues and let agents open PRs in parallel as usual. Whenever a PR is merged into `main`, the framework's polling (`messages.poll`) automatically initiates a round of rebasing for the remaining open PRs. Branches that can be updated are updated automatically; PRs that cannot be updated because of conflicts receive a comment explaining the conflict and the need for intervention. Other PRs are unaffected and continue to be updated.

To trigger this manually (for example, after manually merging a PR, or to bring all branches up to date immediately), run:

```
openagents sync-prs [--merged <merged-PR-number>] [--rebase]
```

`--merged` specifies the number of the PR that was just merged (excluding that PR itself from the list to update), and `--rebase` selects rebase as the branch update method. The command prints a summary of the processing result for each PR.

## Reference-level explanation

The changes are divided into 5 Tasks (see the DAG at the end; each Task has a mutually exclusive set of `files`, with a single writer):

1. **T1 github-layer `list_open_prs` + `update_branch`** (no dependencies) — Add two module-level functions to `github.py` as the underlying capabilities for the entire fan-out process. `list_open_prs()` executes `gh pr list --state open --json number,url` and parses the output into a list of `PR` objects (correctly returning an empty list as well). `update_branch(*, pr_number, rebase=False)` executes `gh pr update-branch <n> [--rebase]`, with three-state semantics: return `True` on a successful update, suppress the “already up to date” condition and return `False`, and raise `GithubError` on conflicts or other failures. Reuse the existing `_run_gh` / `_gh_json` / `PR`.

2. **T2 `rebase_open_prs` fan-out module** (depends on T1) — Create `openagents/rebase.py` and implement `rebase_open_prs(*, merged_pr_number=None, rebase=False)`: call `github.list_open_prs` to retrieve all open PRs, exclude `merged_pr_number` itself, and call `github.update_branch` for each PR. If a PR encounters a conflict (`GithubError`), call `github.post_comment` to post a conflict notification comment on that PR (with the text defined as a module constant) and **continue processing subsequent PRs**, without interrupting the entire operation. Return a list of `[{pr_number, result}]`, with result distinguishing three categories: “updated successfully / already up to date / conflict.”

3. **T3 Post-merge fan-out integration in `messages.poll`** (depends on T2) — In `messages._process_run`, after detecting `is_merged` and setting the run to `STATUS_DONE`, add a call to `rebase.rebase_open_prs(merged_pr_number=pr_number)`. The `merged` event may include the synchronization results. Keep the remaining routing logic unchanged.

4. **T4 Manual `openagents sync-prs` command** (depends on T2) — Register the `sync-prs` subcommand in `cli.build_parser` (with the `--merged` and `--rebase` arguments), and add a `_cmd_sync_prs` handler: lazily import `rebase`, call `rebase.rebase_open_prs`, and print a summary of the results. Add it to the handlers table in `_dispatch`.

5. **T5 End-to-end script** (depends on T3 and T4) — Add `scripts/e2e-rfc-0009-auto-rebase.sh`: create two open PRs in a test repository, merge one of them, run `openagents sync-prs --merged <n>` (or one polling cycle), verify that the other PR's branch has incorporated the latest `main` (`gh pr view --json mergeStateStatus` or a comparison of commits), and demonstrate commenting in a conflict scenario. Include prerequisites and instructions for running the script, following the style of the existing `scripts/e2e-rfc-000X-*.sh` scripts.

**End-to-end validation**: `bash scripts/e2e-rfc-0009-auto-rebase.sh` (create two PRs, merge one, run sync-prs and verify that the other branch is up to date with the latest main, and demonstrate conflict commenting).

Dependency DAG: `T1 → T2`, `T2 → T3`, `T2 → T4`, `T3 → T5`, `T4 → T5`.

## Drawbacks

- Each merge triggers a fan-out update of all open PRs, producing a batch of `gh pr update-branch` calls when there are many PRs (N open PRs ⇒ N updates). However, the update itself is idempotent (branches that are already up to date are skipped), and the scale is linear in the number of open PRs.
- Automatic rebasing may rewrite the commit base of each open PR's branch; people/agents working manually on that branch need to pull again.

## Rationale and alternatives

- **Why add `update_branch` to the github layer instead of constructing `gh` commands directly in the fan-out module**: Encapsulating “call gh once to update one branch” in a single github-layer function with three-state semantics (True/False/raise an error) leaves the fan-out module responsible only for orchestration, without needing to know gh details. This decouples responsibilities (principle 10) and makes it easy to use monkeypatch for hermetic unit tests.
- **Why comment on conflicts instead of stopping**: When multiple PRs are progressing in parallel, a conflict in one PR should not block the others from being brought up to date. A comment leaves the signal that “human/agent intervention is needed” on the corresponding PR, consistent with OpenAgents' collaboration model of using PRs/comments as message carriers.
- **Why provide both automatic (poll integration) and manual (sync-prs) entry points**: The automatic path covers normal operation (triggered by an agent merging a PR); the manual command covers manual merges or situations that require bringing branches up to date immediately. Both share the same `rebase_open_prs`, with no duplicated logic.
- **Alternative: do not rebase automatically; update on demand only when a PR is processed**. Rejected: conflicts are exposed too late, and cleanup is pushed back into each PR's processing workflow.

## Prior art

GitHub natively provides the “Update branch” button for PRs, the `gh pr update-branch` command, and the “require branches to be up to date before merging” repository setting. This feature reuses `gh pr update-branch` as the underlying action and automates the orchestration of “bringing the remaining open PRs up to date in a batch after a merge.” This is a common practice in trunk-based development: keeping each branch based on the latest mainline.

## Unresolved questions

None. The three-state update semantics, commenting on conflicts without stopping, and the automatic + manual entry points have all been decided within this group.

## Future possibilities

- Conflict comments could be extended to automatically dispatch an agent to resolve the PR's rebase conflicts.
- Concurrency/rate-limiting strategies could be added to the fan-out process for repositories with very large numbers of open PRs.
