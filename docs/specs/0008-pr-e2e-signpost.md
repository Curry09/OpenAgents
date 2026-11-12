---
number: "0008"
title: "“End-to-End Verification” signpost in the PR body (automatically generated from the RFC)"
issue: 0
slug: pr-e2e-signpost
summary: "Automatically generate a signpost in the PR body explaining how to perform end-to-end verification, with content automatically parsed and rendered from the RFC added on the branch, so reviewers can see at a glance how to verify acceptance."
tasks:
  - id: T1
    title: "RFC parsing and signpost rendering (pure module)"
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/rfc.py
      - tests/test_rfc.py
    scope: "Create openagents/rfc.py and implement E2EHints, extract_e2e, render_signpost, and signpost_for (see the interface contract). Extract the script path (only from the `### Integration Tests` subsection) and a one-line expected result (only from the `### Manual Verification` subsection); set each missing field to None and fall back appropriately during rendering; parse NNNN from the filename. Never raise errors throughout. Reference RFC-0008 in the module docstring and public functions."
    acceptance: "Unit test coverage—a complete RFC yields the script path and expected result and renders three lines; a missing integration test script, missing manual verification, and both missing each fall back appropriately without raising errors; malformed Markdown does not raise errors; the filename 0008-x.md yields the number 8. ruff + pytest pass."
  - id: T2
    title: "Locate the RFC file added on this branch"
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/workspace.py
      - tests/test_workspace.py
    scope: "Add changed_rfc_path to Workspace. Use `git diff --name-only origin/<base>...HEAD -- docs/rfcs/` to obtain the first NNNN-*.md file (excluding README.md) and return its absolute Path, or None if none exists; reuse the existing _git wrapper. Reference RFC-0008 in the method docstring."
    acceptance: "Unit tests—in a temporary git repository, create a base and a branch containing a new RFC, and verify that the method returns that RFC's path; return None when no RFC has been added; do not misidentify README.md as an RFC. ruff + pytest pass."
  - id: T3
    title: "Wire into PR body assembly"
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: "Modify orchestrator: import rfc; extend _pr_body with e2e_section (without a default value); in start_rfc, after commit_and_push and before create_pr, locate the RFC file → render the signpost → append it to the body. If locating the file fails or rendering returns None, fall back to the original body without raising errors. Reference RFC-0008 in comments at additions/changes."
    acceptance: "Unit tests (fake backend + fake Workspace + monkeypatch github)—the body passed by start_rfc to create_pr contains a “## End-to-End Verification” section whose content comes from the RFC; when changed_rfc_path returns None, the body does not contain that section and no errors are raised. ruff + pytest pass."
  - id: T4
    title: "End-to-end script + RFC index"
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-rfc-0008-pr-e2e-signpost.sh
      - docs/rfcs/README.md
    scope: "Add scripts/e2e-rfc-0008-pr-e2e-signpost.sh (follow the existing two-phase structure of e2e scripts: offline ruff check / ruff format --check / pytest by default; when OPENAGENTS_E2E_REAL=1 + OPENAGENTS_E2E_ISSUE are set, perform a real run of openagents rfc <issue> and assert that its draft PR body contains the “## End-to-End Verification” section). Append an RFC-0008 row to the RFC list in docs/rfcs/README.md."
    acceptance: "The offline phase passes in a clean repository; the script is executable (set -euo pipefail, chmod +x); the README list contains an RFC-0008 entry."
---

# 0008 · “End-to-End Verification” Signpost in PR Bodies (Automatically Generated from RFCs)

> Historical labels are translated here for readability. See the [original text](../specs-zh-CN/0008-pr-e2e-signpost.md) for exact historical values.

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Automatically generate an “End-to-End Verification” signpost in the bodies of PRs opened automatically by agents: extract the **integration test script path** and **one-line expected outcome for manual verification** from the RFC file added on the branch, and render them as a fixed section in the body so reviewers can see at a glance “how to verify this PR against its acceptance criteria” without browsing the code. The entire pipeline consists solely of parsing and rendering and never raises errors; if the RFC cannot be located or fields are missing, the body automatically falls back to its original form.

## Motivation

The OpenAgents collaboration model uses PRs + comments as its message bus, and PRs are the central vehicle for alignment between agents and between agents and humans. When reviewers (humans or reviewer agents) encounter a PR, their first concern is an outcome-focused question, rather than the line-by-line diff: how to verify this change end to end, which script to run, and what to expect. This information is already written in the RFC accompanying each change (the integration test script and the expected outcome for manual verification), but it is scattered throughout the RFC body. Reviewers must browse `docs/rfcs/`, find the corresponding file, and read it before they can begin acceptance testing.

Automatically extracting this “how to perform acceptance testing” information from the RFC and pinning it directly to the top of the PR body eliminates that manual lookup: reviewers can see the script path and expected outcome at a glance and immediately verify the result. This directly aligns with the OpenAgents principle of “focusing on outcomes, with humans testing outcomes”—placing the entry point for acceptance testing up front in the PR body.

## Guide-level explanation

For reviewers: when you open a PR created by an agent, its body will now contain an additional “## End-to-End Verification” section, directly listing the integration test script declared in the RFC accompanying the change (for example, `bash scripts/xxx.sh`) and a one-line expected result. Run it as indicated to perform acceptance testing, without browsing files in `docs/rfcs/`.

For the development pipeline: this signpost is generated automatically during the PR creation process in `start_rfc`, rather than written by hand—the orchestrator locates the RFC file added on the current branch, parses two convention-based subsections (`### Integration tests` supplies the script path and `### Manual verification` supplies a one-line expected outcome), and renders a three-line section to insert into the PR body. If the branch adds no RFC, or the RFC does not contain these fields, the body falls back to its original form; this must never cause an error or block PR creation. The convention is lightweight: as long as the RFC clearly describes the acceptance procedure in these two subsections, the signpost appears automatically.

## Reference-level explanation

The changes are broken down into 4 Tasks (see the DAG below; `files` are mutually exclusive, and each Task has a single writer):

1. **T1 RFC parsing and signpost rendering (pure module, no dependencies)** — Create `openagents/rfc.py`, providing `E2EHints`, `extract_e2e`, `render_signpost`, and `signpost_for`. `extract_e2e` extracts content only from designated subsections of the RFC text: the script path comes only from the `### Integration tests` subsection, and the one-line expected outcome comes only from the `### Manual verification` subsection; missing fields are set to `None`, and the corresponding lines are omitted during rendering as a fallback. It also parses the number NNNN from the filename (such as `0008-x.md`). The entire module **must never raise errors** (even malformed Markdown must not cause a crash), and the module docstring and public function comments reference `RFC-0008`.
2. **T2 Locate the RFC file added on the current branch (no dependencies)** — Add a `changed_rfc_path` method to `Workspace`. Use `git diff --name-only origin/<base>...HEAD -- docs/rfcs/` to obtain the first `NNNN-*.md` added on the current branch relative to base (excluding `README.md`), and return an absolute `Path`, or `None` if there is none; reuse the existing `_git` wrapper. The method docstring references `RFC-0008`.
3. **T3 Wire into PR body orchestration (depends on T1 and T2)** — Modify `orchestrator`: `import rfc`, and add an `e2e_section` parameter to `_pr_body` (with no default value; it must be passed explicitly). After `commit_and_push` and before `create_pr`, `start_rfc` calls `changed_rfc_path` to locate the RFC → `signpost_for` to render the signpost → inserts it into the body. If locating the file fails or rendering returns `None`, the body falls back to its original form without raising an error. Comments at the modification sites reference `RFC-0008`.
4. **T4 End-to-end script + RFC index (depends on T3)** — Add the end-to-end script **`scripts/e2e-rfc-0008-pr-e2e-signpost.sh`**, following the two-phase structure of existing e2e scripts: the default offline phase runs `ruff check` / `ruff format --check` / `pytest`; when `OPENAGENTS_E2E_REAL=1` + `OPENAGENTS_E2E_ISSUE` are set, it performs a real run of `openagents rfc <issue>` and asserts that the resulting draft PR body contains the “## End-to-End Verification” section. The script uses `set -euo pipefail` and is made executable with `chmod +x`. Append an RFC-0008 row to the RFC list in `docs/rfcs/README.md`.

**End-to-end verification (the script extracted by the signpost is this group’s e2e script)**: `bash scripts/e2e-rfc-0008-pr-e2e-signpost.sh` (runs ruff + pytest offline by default; real mode exercises `openagents rfc` and asserts that the PR body contains the “## End-to-End Verification” section).

Dependency DAG: `T1 → T3`, `T2 → T3`, `T3 → T4`; T1 and T2 are independent of each other and can run in parallel.

## Drawbacks

- Introduces implicit coupling between the PR body and the RFC through “convention-based subsections” (`### Integration tests` / `### Manual verification`): if the RFC does not use these two subsection headings, the signpost cannot extract the content (but degrades gracefully without raising an error).
- Parsing relies on lightweight conventions in Markdown text rather than structured fields, so drift in how RFCs are written may cause content to be missed.

## Rationale and alternatives

- **Why parse the RFC instead of manually filling in a PR template**: the acceptance procedure belongs in the RFC in the first place (a single source of truth); manual entry would duplicate it and be prone to drift. Automatic parsing allows “write the RFC once” to also drive the signpost (DRY, decoupling, principle 10).
- **Why pure functions + never raising errors**: the signpost is supplementary information that is “nice to have”; a parsing failure must never block PR creation. Accordingly, `rfc.py` is designed as a pure module with no side effects, with graceful fallback for every missing field, making it easy to cover combinations of missing fields with hermetic unit tests.
- **Alternative: carry acceptance information in structured frontmatter fields**. Rejected (YAGNI): currently, only two items are needed—a script path and a one-line expected outcome—and extraction from designated subsections is already lightweight enough; introducing an additional structured schema would be overengineering.
- **Alternative: have the reviewer agent look up the RFC at review time**. Rejected: placing the information up front in the PR body is more direct for both humans and agents and does not depend on the reviewer-side implementation.

## Prior art

Placing “how to verify / how to run” information up front in PR bodies is common practice in industry PR templates (GitHub PR templates often include a "How to test" section). What distinguishes this feature is that the section is automatically parsed and rendered from the RFC accompanying the change, rather than filled in manually in a template, aligning with OpenAgents’ RFC-driven development.

## Unresolved questions

None. The subsection convention (`### Integration tests` / `### Manual verification`), fallback semantics, and lookup rule (the first `NNNN-*.md`, excluding README) have all been settled within this group.

## Future possibilities

- The signpost could be extended with more fields (such as expected screenshots or key metrics), still using the same “RFC subsection → rendering” pipeline.
- A reviewer agent could consume the signpost to automatically execute the e2e script and post the results back to the PR as a comment.
