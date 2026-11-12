---
number: "0074"
title: "forge dispatch layer and Gitea driver: consolidate GitHub coupling into a replaceable hosting-platform seam"
issue: 0
slug: gitea-forge-driver
summary: "All OpenAgents platform operations go through utils/github.py (a thin wrapper around the gh CLI), which the orchestration layer (vigil/stages/gates/context/identity/release/cli/backfill) consumes as module functions—this is both the coupling point and a natural seam. This spec adds the utils/forge.py dispatch module (selects a driver by reading the new forge section in .openagents/openagents.yml; defaults to github, with no noticeable change for existing users) and the utils/gitea.py driver (the same public interface as github.py, targeting Gitea /api/v1, using stdlib urllib with zero new dependencies). Consumers change only their import line to `from openagents.utils import forge as github` (alias-import, with zero changes to hundreds of call sites). Semantic mappings: checks→commit combined status, mergeable→bool+UNKNOWN normalization, draft→WIP title prefix, blocked_by→issue dependencies, update_branch→POST /pulls/{index}/update, Closes #N maps to native Gitea closing keywords. Read the authentication token from an environment variable, preserving the rule against storing tokens. Replace hardcoded gh commands in the merger prompt with $merge_command/$verify_command placeholders populated by stages.merge through the driver. The Gitea path uses the hidden CLI subcommand `openagents merge-pr --pr N`; token handling stays inside the driver and out of the prompt. The first consumer is auto-designer’s Harness evolution orchestration, which uses local Gitea infrastructure (its spec-0032)."
e2e:
  intent: "Prove that \"forge backends are switchable\" holds through an offline, deterministic flow—forge falls back to github by default (zero regressions for existing behavior); when forge=gitea, all public API functions call Gitea REST with correct semantic mappings (checks/mergeable/draft/deps/merge/update/label idempotency); the merger prompt contains no gh literals, and merge/verify commands are injected according to the forge; configuration validation rejects forge=gitea when the gitea section is missing."
  method: "Form: backend only (forge dispatch + gitea driver + configuration section + parameterized prompts), with no navigable frontend; no real LLM/network/repository access, and all tests are offline and deterministic (using the same approach as Spec-0071):\n1. Targeted pytest tests:\n   - test_forge.py: delegation to github by default, delegation to gitea after configure(gitea), constants (DISCOVERY_LABEL, etc.) available directly at import time with zero IO, lazy discovery through .openagents/openagents.yml after reset (repository created with tmp_path), and fail-open fallback to github for invalid YAML.\n   - test_gitea_driver.py: a fake HTTP layer (monkeypatch gitea._http) covers request shapes (method/path/body) and response parsing for all public API functions; semantic mappings checked individually—three-state classification of combined status + a count of 0 when there are no statuses, mergeable bool→MERGEABLE/CONFLICTING/missing→UNKNOWN, WIP prefix is_draft/mark_ready round trip, dependencies GET/POST shapes and 404→[], update 422 when already up to date→False, idempotent merge when already merged, idempotent error tolerance for label add/remove, label name→id resolution in create_issue, and backoff retries for transient 5xx errors.\n   - Add to test_agent_config.py: schema for the forge/gitea sections, an error when forge=gitea lacks a gitea section, and forge=github by default.\n   - Update test_agents_merger.py: PROMPT contains $merge_command/$verify_command and no gh literals.\n   - test_stages.py (if present)/new assertions: stages.merge injects merge_command/verify_command.\n2. grep anchors: the first line of forge.py is '# Spec-0074/T1'; the first line of gitea.py is '# Spec-0074/T2'; import lines in vigil/stages/gates/context/identity/release/cli/backfill all take the form 'from openagents.utils import forge as github'; agents/merger.py contains no 'gh pr merge' literal.\n3. ruff check + ruff format --check all pass.\n4. One manual smoke-test run against real Gitea 1.22 (the consuming project's deploy/gitea instance in auto-designer): create issue→apply label→open PR→merge→issue closes automatically (an acceptance criterion for the consuming project's spec-0032/T5, excluded from this repository's CI).\nScript: scripts/e2e-spec-0074-gitea-forge-driver.sh (ruff + the pytest tests above + grep anchors).\n"
tasks:
  - id: T1
    title: "forge dispatch layer: configuration section + alias-import rewiring + merger prompt parameterization + hidden merge-pr command"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/forge.py
      - openagents/utils/agent_config.py
      - openagents/data/openagents.yml.template
      - openagents/utils/github.py
      - openagents/agents/merger.py
      - openagents/recipes/vigil.py
      - openagents/recipes/stages.py
      - openagents/recipes/backfill.py
      - openagents/runtime/gates.py
      - openagents/runtime/context.py
      - openagents/utils/identity.py
      - openagents/utils/release.py
      - openagents/cli.py
      - tests/test_forge.py
      - tests/test_agents_merger.py
      - tests/test_recipe_vigil_admit.py
      - tests/test_recipe_vigil_discovery.py
      - tests/test_recipe_vigil.py
    scope: "Create utils/forge.py: module-level configure(name, settings)/reset() + PEP 562 __getattr__ delegating to the github/gitea driver module according to the current forge; when configure has not been called explicitly, the first function access performs lazy discovery (search upward from cwd for .openagents/openagents.yml and read only the forge/gitea keys; missing/malformed files fail open by falling back to github—ensuring commands such as init/issue/release that do not explicitly load configuration still select the correct driver, consistently with gh's cwd semantics); workflow label constants and GithubError are directly re-exported from github.py at import time (forge-neutral, zero IO). agent_config.py: add forge (enum github/gitea) and a gitea section (base_url/owner/repo required + token_env defaults to GITEA_TOKEN, additionalProperties=False) to the top-level schema, add forge/gitea fields to AgentConfig, and manually validate that forge=gitea requires a gitea section; append a commented-out forge example section to the template. In eight consumer files, change only the import line to alias-import (zero call-site changes). Replace the hardcoded `gh pr merge`/`gh pr view` in merger.py PROMPT with $merge_command/$verify_command placeholders; add merge_command_text/merge_verify_command_text to github.py (return the existing gh command text, with zero behavioral changes on the github side); stages.merge injects the two placeholders. Add a hidden merge-pr subcommand to cli.py (--pr/--method, forwards to forge.merge_pr + is_merged, with output containing MERGED so the merger agent can determine success)—the merger agent's execution path for performing merges on Gitea; token handling stays inside the driver and out of the prompt (the same role as reply-comment). Correction based on production evidence: vigil rereads the issue before applying ready and proceeds only if the configured discovery label is still present, while also respecting concurrently added ready/needs-human labels, closing the TOCTOU window in which a human or concurrent workflow removes the label after discovery."
    acceptance: "pytest passes: forge delegates to github by default (zero regressions across the existing full test suite); delegates to gitea after configure; constant imports perform zero IO; lazy discovery reads configuration from a tmp repository, with malformed YAML falling back to github; validation of the new agent_config sections (forge=gitea without a gitea section raises an error); merger PROMPT contains no gh literals and includes both placeholders; stages.merge injects command text (monkeypatch the backend and assert task contents); cli merge-pr forwards to forge (assertions using stubs); when the discovery label is removed after discovery, ready is not applied and curator is not triggered. All ruff checks pass."
  - id: T2
    title: "Gitea driver: the same public interface as github.py, targeting Gitea /api/v1 (stdlib urllib, zero new dependencies)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/utils/gitea.py
      - tests/test_gitea_driver.py
      - scripts/e2e-spec-0074-gitea-forge-driver.sh
    scope: "Create utils/gitea.py, implementing the github.py public interface actually consumed by the new stack (ensure_prerequisites/ensure_label/create_issue/get_issue/list_issues/issue_comment/list_issue_comments/issue_add_label/issue_remove_label/close_issue/list_blocked_by/add_blocked_by/create_pr/find_pr_by_branch/pr_for_branch/list_open_prs/pr_head_branch/pr_snapshot/check_snapshot/check_status/check_logs/list_comments/post_comment/add_label/remove_label/has_label/mark_ready/update_branch/merge_pr/branch_ci_green/code_fingerprint/is_merged/is_open/is_closed/is_draft/mergeability/create_repo/merge_command_text/merge_verify_command_text), directly reusing the data classes and GithubError definitions from github.py. All requests target Gitea /api/v1: stdlib urllib.request is centralized in _http (Authorization header carries the token obtained from the token_env environment variable, 30s timeout, exponential backoff ×3 for 5xx/timeouts to match _run_gh, non-2xx responses raise GithubError with the status code and endpoint). Semantic mappings: PR comments=issue comments (shared index namespace); create_issue/label operations resolve names→IDs (module-level cache + idempotent handling of 409/422 already-exists responses); checks→GET /commits/{ref}/status (classify combined state as pass/fail/pending, count statuses and take the latest created_at, zero statuses→count 0 state pass); PR state open/closed+merged→OPEN/CLOSED/MERGED; mergeable bool→MERGEABLE/CONFLICTING, missing field→UNKNOWN, derive merge_state_status as CLEAN/DIRTY/UNKNOWN (no BEHIND—Gitea does not expose behind status; update_branch works only when explicitly called, see the main text); draft→WIP title prefix (is_draft recognizes the prefix or the native draft field, mark_ready=PATCH to remove the prefix); blocked_by→GET/POST /issues/{index}/dependencies (404/feature disabled→[], POST is idempotent when the dependency already exists); update_branch→POST /pulls/{index}/update?style=merge|rebase (already up to date, 422→False); merge_pr→POST /pulls/{index}/merge {Do:method} (already merged is an idempotent no-op); close_issue→PATCH state=closed (404/already closed is idempotent); code_fingerprint→GET /pulls/{index}.diff, reuse github._strip_diff_file_blocks, then sha256 (failure→\"\", fail-open); branch_ci_green→branch combined status success or zero statuses→True; ensure_prerequisites→nonempty token + reachable GET /repos/{owner}/{repo} + precreate PROCESS_LABELS; merge_command_text→'openagents merge-pr --pr N'. author_association mapping: commenter==configured owner→OWNER, otherwise an empty string (fail-closed; on Gitea, triage:human recognizes only decisions made by the owner personally—Unresolved in the main text). Wherever empirical results for 1.22 endpoints differ, apply the smallest semantic fallback and document it in code comments. Correction based on production evidence: the repository issues endpoint silently drops nonexistent labels and expands duplicate labels with the same name into multiple IDs, then queries them with AND; list_issues therefore first reads all repository labels, returns zero matches immediately for unknown names, then passes valid label names through the IncludedAnyLabelIDs path of `/repos/issues/search` for server-side OR filtering, and finally performs fail-closed verification against repository.full_name, response label names, and PR fields. Fall back to local matching over repository pagination only when a label name itself contains the API delimiter comma. Before POST, ensure_label refreshes the complete label list through pagination and returns immediately if the label already exists, preventing vigil from creating a same-named ready label on every tick."
    acceptance: "tests/test_gitea_driver.py uses a fake HTTP layer to cover request shapes and response parsing for all the functions above, with individual assertions for each semantic mapping (see e2e.method); it also covers search API server-side OR queries, fail-closed verification of the target repository and response labels, zero matches for unknown labels, pagination, PR exclusion, comma-label fallback, zero POSTs for existing labels, and 409/422 race-condition fallback; no network access. The ruff + pytest + grep anchor checks in scripts/e2e-spec-0074-gitea-forge-driver.sh pass. Acceptance of the end-to-end smoke test against real Gitea 1.22 is handled by the consumer auto-designer spec-0032/T5."
---

# 0074 · forge dispatch layer and Gitea driver: consolidate GitHub coupling into a swappable hosting-platform seam

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG); the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

All hosting-platform operations in OpenAgents are concentrated in `utils/github.py` (a thin wrapper around the gh CLI), which the orchestration layer consumes through module functions. This spec elevates that de facto coupling point into an **explicit seam**: add a `utils/forge.py` dispatch module (selecting a driver from the `forge` section in `.openagents/openagents.yml`, defaulting to github with no visible change for existing users) and a `utils/gitea.py` driver (exposing the same public API against Gitea /api/v1); consumers change only their import line (`from openagents.utils import forge as github`), with zero changes to hundreds of call sites. The gh commands in the merger prompt are parameterized with placeholders, and Gitea merges are performed through a new hidden command, `openagents merge-pr`.

## Motivation

Principle 2 (decentralized, multiple backends) already states that coding backends can be mixed (Claude Code / Codex / nexau); hosting platforms form another dimension of the same kind—the design in which “agents pass messages through PRs + comments” does not depend on GitHub itself, but on any forge with issue/PR/label/comment semantics. The first real consumer has already emerged: auto-designer (self-evolving harness orchestration) wants to move its developer side to OpenAgents, while its infrastructure is pinned to **local Gitea** (to meet containment requirements for isolated sandboxes without external credentials), and cannot and should not migrate to GitHub.

Now is also precisely when the cost of this change is lowest: after the major consolidation in Spec-0060–0065, github.py is a leaf in the dependency graph, and all consumers use `github.fn()` module-function calls—a one-line alias import can switch platforms. The later this is done, the more scattered the consumption points will become.

## Guide-level explanation

From the user's perspective: in a Gitea project, add one section to `.openagents/openagents.yml`—

```yaml
forge: gitea
gitea:
  base_url: http://localhost:3000
  owner: harness
  repo: harness
  token_env: GITEA_TOKEN   # Optional; defaults to GITEA_TOKEN; the token itself is stored only in an environment variable
```

All other commands, the three-state stages behavior, and vigil behavior remain unchanged. Omitting the `forge` section = github (gh CLI), with no visible change for existing users. Authentication continues to follow the rule that “OpenAgents does not store tokens”: GitHub delegates to gh, and Gitea delegates to environment variables.

From the developer's perspective: any code that needs to access the platform imports `forge as github` and calls `github.list_issues(...)` as usual; forge delegates calls to the appropriate driver according to configuration. A new forge (GitLab, etc.) = a new module exposing the same public API + one enum entry.

## Reference-level explanation

### forge.py dispatch (T1)

- `configure(*, name, settings)` explicitly loads configuration (vigil/CLI paths, tests); when unconfigured, the first **function** access performs lazy discovery: search upward from cwd for `.openagents/openagents.yml`, read only the `forge`/`gitea` keys using a lightweight reader (without full agent_config validation, to avoid circular dependencies), and fail open by falling back to github if the file is missing or invalid. Lazy discovery ensures that commands such as `issue`/`release`, which do not load configuration, also select the correct driver, with the same cwd-bound semantics as gh.
- Workflow label constants (DISCOVERY_LABEL, etc.) and `GithubError` are re-exported directly from github.py at import time—they are forge-neutral, and this avoids “accessing a constant at module scope triggers IO.”
- Error types do not diverge: the gitea driver also raises `GithubError` (zero changes to CLI error normalization).

### Platform commands in prompts (T1)

merger is the only agent with hardcoded gh commands in its PROMPT. Replace these with `$merge_command`/`$verify_command` placeholders, injected by `stages.merge` through the driver's `merge_command_text()`/`merge_verify_command_text()`: github returns the original gh commands unchanged (zero regressions); gitea returns `openagents merge-pr --pr N`—a new hidden CLI subcommand (serving the same role as reply-comment) that internally forwards to `forge.merge_pr` + `is_merged`, keeping token handling inside the driver and credentials out of prompts.

### Gitea semantic mapping (T2)

| GitHub (gh) | Gitea /api/v1 | Degradation notes |
|---|---|---|
| checks (check runs) | `GET /commits/{ref}/status` combined | Zero statuses → count=0 (the caller remains responsible for Vigil's “wait for CI” decision) |
| Three-state mergeable | PR `mergeable: bool` | false→CONFLICTING/DIRTY; missing field→UNKNOWN; **no BEHIND** (Gitea does not expose behind, so Vigil will not automatically trigger update_branch; merging is left to Gitea's server-side merge handling) |
| draft PR | `WIP: ` title prefix | is_draft recognizes the prefix or the native draft field; mark_ready=PATCH to remove the prefix |
| Native blocked_by | `GET/POST /issues/{index}/dependencies` | 404/feature disabled→no dependencies |
| `gh pr merge` | `POST /pulls/{index}/merge` | Idempotent if already merged |
| update branch | `POST /pulls/{index}/update?style=` | Already up to date, 422→False |
| authorAssociation | No equivalent | Commenter==configured owner→"OWNER", otherwise "" (fail-closed) |
| Automatic closing via `Closes #N` | Native closing keywords | Same |

PR comments and issue comments share an index namespace in Gitea (`/issues/{index}/comments` serves both), so `list_comments`/`post_comment` use the same endpoints as their issue counterparts. Label operations require name→id resolution (module-level cache + idempotent fallback for races, aligned with the consumer's existing GiteaTracker practice).

## Drawbacks

1. The public API of github.py is the de facto contract, without strict Protocol enforcement—if a new function is added to github.py but omitted from gitea.py, a Gitea project fails only at the call site (AttributeError→wrapped by forge in an error with guidance). Grep anchors + consumer smoke tests provide a backstop.
2. author_association on Gitea recognizes only the owner, limiting multi-maintainer scenarios with `triage: human` (the first consumer uses triage=skip and is unaffected).
3. Risk of semantic drift between the two drivers: the mergeable/BEHIND details on which the merge pipeline depends inherently differ between the platforms; this has been handled through “conservative convergence + documentation in comments.”

## Rationale and alternatives

- **Alias imports instead of a major forge Protocol refactor**: there are hundreds of consumption points, and module-function calls are already a stable pattern; changing import lines is the least invasive approach at O(number of files). The public API of github.py is the interface contract; do not pay the abstraction cost for a “third forge” in advance (Principle 1).
- **stdlib urllib instead of requests/tea CLI**: keep the dependency set unchanged at ruamel.yaml+jsonschema; tea CLI has incomplete coverage and introduces an external binary.
- **Keep merge actions in agent form** (`$merge_command` injection) instead of direct mechanical calls from stages: preserve the tradeoff in Spec-0017/T3 that “lifecycle actions belong to agents + needs-human is the final escape hatch”; leave mechanization as an optional future consolidation.
- **Rejected alternative: consumers monkeypatch sys.modules**: leave this repository unchanged and have consumers replace the github module at runtime—any upstream change to the function API would silently break this, and it would turn internal structure into an external contract; rejected.

## Prior art

- This repository's Spec-0064 (declarative agents/stages with three states): the forge section follows the same configuration source of truth and validation style.
- Consumer auto-designer spec-0032 (requirements side/delivery side split): the motivating use case for this spec and the party performing acceptance checks through real Gitea smoke tests.
- Consumer GiteaTracker (auto-designer spec-0002): existing practice for label name→id caching and idempotent fallback.

## Unresolved questions

1. Empirical verification of Gitea 1.22 endpoints: the dependencies API shape, whether PR responses include a native draft field, and the update endpoint's return code for “already up to date”—the first task when T2 begins is to verify these against a real instance and fine-tune the mapping table based on the evidence.
2. Maintainer identification for `triage: human` on Gitea (the collaborators list API could fill the gap; wait for a real requirement).
3. Impact of the absence of BEHIND: when the PR base is behind, do not proactively call update_branch; rely on server-side merging at merge time—observe consumer runtime data before deciding whether to add simulated BEHIND through “comparing base sha.”

## Future possibilities

- GitLab driver (same approach: a new module + one enum entry).
- forge capability declarations (drivers declare which optional features they support: dependencies/draft/behind), allowing Vigil to degrade behavior according to capabilities instead of hardcoded comments.
- Mechanized merger option (stages calls forge.merge_pr directly, selectable through configuration).
