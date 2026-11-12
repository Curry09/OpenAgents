---
number: "0013"
title: "Actually run the end-to-end script and post “pass/fail + logs” as a PR comment (extending the RFC-0008 signpost → actual execution results)"
issue: 31
slug: implement-e2e-run-result-comment
summary: "Actually run the end-to-end script once before marking the PR ready, and post “whether it passed + logs” as a signed PR comment. This extends the 0008 signpost (explaining how to test) to actual execution results (providing the conclusion directly)."
tasks:
  - id: T1
    title: "e2e execution wrapper + result comment rendering (standalone module)"
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/e2e.py
      - tests/test_e2e.py
    scope: "Create openagents/e2e.py, implementing E2EResult, run_e2e_script, render_result, and DEFAULT_TIMEOUT_SECONDS / DEFAULT_TAIL_LINES. Run the offline portion with bash <script_path> inside the worktree, capture the exit code and combined output, enforce a timeout, and retain the last N lines; map a missing script / a non-regular file / a timeout / a nonzero exit to structured results in each case, never raising an exception. Reference RFC-0013 in the module docstring and public functions."
    acceptance: "Unit test coverage—exit code 0→passed; nonzero→failed with the correct exit code; timeout→failed with timed_out=True; script_path=None / nonexistent file→skipped without starting a subprocess; render_result renders the corresponding “Result” line and log block for each of the four outcomes without raising an exception. ruff + pytest pass."
  - id: T2
    title: "rfc.script_path_for (reuse extract_e2e to locate the script)"
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
    scope: "Add script_path_for(*, rfc_path) -> str | None to openagents/rfc.py: read the file→extract_e2e→return hints.script_path; return None if the file cannot be read (without raising an exception), mirroring the existing signpost_for. Reference RFC-0013 in the docstring (reusing extract_e2e from RFC-0008)."
    acceptance: "Unit tests—extract the relative script path from an RFC containing an “Integration Tests” script; return None when there is no script section; return None without raising an exception when the file cannot be read. Do not break existing extract_e2e / signpost_for test cases. ruff + pytest pass."
  - id: T3
    title: "Wire actual execution and a signed result comment into implement before marking the PR ready"
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
    scope: "Modify orchestrator.implement: import e2e; after commit_and_push and before mark_ready, locate the script (changed_rfc_path + rfc.script_path_for, base=DEFAULT_BASE)→actually run it with e2e.run_e2e_script→render with e2e.render_result→sign and post the comment with identity.post_signed_comment→mark the PR ready as usual with github.mark_ready. A ❌ result does not block marking the PR ready; if posting the comment fails, only record it in progress and swallow the exception without crashing the workflow. Reference RFC-0013 in comments at added/changed locations."
    acceptance: "Unit tests (fake backend + fake Workspace + monkeypatch e2e.* / identity.post_signed_comment / github.mark_ready)—implement calls run_e2e_script before mark_ready and posts the rendered result through post_signed_comment (with this instance’s agent_id); mark_ready is still called when e2e fails; when changed_rfc_path returns None, use script_path=None (skipped), still post a comment, and do not raise an exception; mark_ready is still called when posting the comment raises an exception. ruff + pytest pass."
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
      - scripts/e2e-rfc-0013-implement-e2e-comment.sh
      - docs/rfcs/README.md
    scope: "Add scripts/e2e-rfc-0013-implement-e2e-comment.sh (two stages: offline ruff check / ruff format --check / pytest by default; when OPENAGENTS_E2E_REAL=1, a manual opt-in exercise of the “implement actual execution + result comment” path). Append an RFC-0013 row to the RFC list in docs/rfcs/README.md."
    acceptance: "The offline portion passes in a clean repository; the script is executable (set -euo pipefail, chmod +x); the README list contains an RFC-0013 entry."
---

# 0013 · Run end-to-end scripts and post “pass/fail + logs” as a PR comment (RFC-0008 signpost → extension with execution results)

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Before a PR transitions from draft to ready for review (`mark_ready`), actually run the end-to-end script declared in this branch’s RFC, render “whether it passed + the log tail,” and post it as an agent-signed PR comment. This is a natural extension of RFC-0008: 0008 adds an “End-to-end verification” signpost to the PR body (telling people how to test—a pointer); this feature runs the script on their behalf and provides a deterministic pass/fail conclusion (a result). It adds a pure sidecar module, `e2e.py`, that knows only `subprocess` + text processing, a corresponding `script_path_for` locator in `rfc.py`, and wires both into `orchestrator.implement` immediately before the PR is marked ready.

## Motivation

**Current behavior (the RFC-0008 signpost, restated in full so readers do not need to consult another spec).** RFC-0008 adds an “End-to-end verification” signpost to the PR body: it extracts the “Integration tests” section from the RFC document changed on this branch and renders the declared `scripts/*.sh` script path into the PR body, telling reviewers/people, “To verify this change, run this script.” It provides a **pointer**—a signpost for someone to run the script manually. The PR itself contains no conclusion about “whether it actually passed this time.”

**The problem: why change this.** “Focus on outcomes” (CLAUDE.md principle 8) requires the model to perform end-to-end testing on people’s behalf, leaving people to focus only on outcomes. A signpost alone is insufficient: reviewers must still run the script themselves to determine pass/fail, putting the cost of gating back on people. The desired new behavior is for `implement` to **run the script itself** before marking the PR ready (the offline deterministic stage: ruff + pytest, mocked throughout), map its exit code to “passed / failed / no script to run,” and post that result together with the log tail as a signed PR comment. The PR then carries “the conclusion from this execution,” so people need only read the conclusion rather than rerun the script. A ❌ result does not block marking the PR ready (information transparency takes priority over hard gating), but people can intervene after seeing the failure comment.

## Guide-level explanation

Upgrade RFC-0008’s “pointer” to a “conclusion,” adding another piece of information:

| Dimension | Current behavior (RFC-0008 signpost) | This feature (extension with execution results) |
|------|------|------|
| e2e information carried by the PR | Script path (a pointer asking someone to run it) | Script path + **pass/fail from this execution + log tail** (a conclusion) |
| Who runs the script | A person (manually following the signpost) | **`implement` automatically runs the offline stage before marking the PR ready** |
| Information medium | A signpost section in the PR body | PR body signpost + **one agent-signed result comment** |

For users: open an issue and have the agent create a PR as usual. When the agent runs `implement` to mark the PR ready, a “## End-to-end test results” comment automatically appears on the PR, stating passed / failed / skipped and showing the last several lines of the log, with this agent instance’s signature. If the script is missing or undeclared, the comment falls back to skipped (pointing back to the RFC’s “Integration tests” section for manual verification), without crashing the workflow.

## Reference-level explanation

The changes break down into 4 Tasks (see the DAG below; `files` are mutually exclusive, with a single writer for each Task):

1. **T1 Pure e2e module** — Create `openagents/e2e.py`, which knows only `subprocess` + text processing and has no awareness of git / GitHub / RFC document semantics / orchestrator (principle 10: decoupling). Expose: `E2EResult` (a structured container for execution results), `run_e2e_script` (runs the offline stage via `bash <script_path>` inside the worktree, captures the exit code and combined output, enforces a timeout of `DEFAULT_TIMEOUT_SECONDS=600`, and retains the last `DEFAULT_TAIL_LINES=40` lines), and `render_result` (a pure function that renders the result as “## End-to-end test results” Markdown). Four outcomes: exit code 0→`passed`; nonzero→`failed`; timeout→`failed` with `timed_out=True`; missing script / non-regular file / `script_path=None`→`skipped` (without starting a subprocess). **Never raise an exception** throughout—all exception paths map to structured results.
2. **T2 rfc.script_path_for** — Add `script_path_for(*, rfc_path) -> str | None` to `openagents/rfc.py`: read the file→reuse RFC-0008’s `extract_e2e`→return `hints.script_path`; return `None` if the file is unreadable (without raising an exception), mirroring the existing `signpost_for`. Only locate the script; do not execute it (decoupling: rfc owns location, e2e owns execution).
3. **T3 Wire into implement** (depends on T1 and T2) — Modify `orchestrator.implement`: `import e2e`; after `commit_and_push` and before `mark_ready`, use `changed_rfc_path` (`base=DEFAULT_BASE`) + `rfc.script_path_for` to locate the script→execute it with `e2e.run_e2e_script`→render with `e2e.render_result`→sign and post the comment via `identity.post_signed_comment` (with this instance’s `agent_id`)→mark the PR ready via `github.mark_ready` as usual. A ❌ e2e result does not block marking the PR ready; a failure to post the comment is only recorded in progress and swallowed, without crashing the workflow; when `changed_rfc_path` is `None`, use `script_path=None` (skipped) and still post a comment.
4. **T4 End-to-end script + index** (depends on T3) — Add `scripts/e2e-rfc-0013-implement-e2e-comment.sh`, with two stages: the default offline deterministic stage (`ruff check` / `ruff format --check` / `pytest`, mocked throughout without accessing real gh); and, when `OPENAGENTS_E2E_REAL=1` and `OPENAGENTS_E2E_PR=<n>` is supplied, a manual opt-in exercise of the real “implement execution + result comment” path. Use `set -euo pipefail` in the script and apply `chmod +x`. Append an RFC-0013 row to the RFC list in `docs/rfcs/README.md`.

**End-to-end verification**: `bash scripts/e2e-rfc-0013-implement-e2e-comment.sh` (offline stage only by default: ruff + pytest).

Dependency DAG: `T1 → T3`, `T2 → T3`, `T3 → T4`. T1 and T2 are independent and can run in parallel.

## Drawbacks

- `implement` runs the offline stage (ruff + pytest) once more before marking the PR ready, lengthening that path—but the `DEFAULT_TIMEOUT_SECONDS=600` timeout cap prevents it from hanging indefinitely.
- An e2e failure does not block marking the PR ready. The result comment is a “soft signal” rather than a hard gate, so people need to watch for failure comments; choosing information transparency over a hard blocking point is intentional (see Rationale).

## Rationale and alternatives

- **Why execute the script instead of continuing to provide only a signpost**: Principle 8, “Focus on outcomes,” requires the model to perform end-to-end testing on people’s behalf. Providing only a pointer still leaves people with the cost of running the script; executing it and posting the conclusion actually takes this verification work off their hands.
- **Why an e2e failure does not block marking the PR ready**: A hard gate would also turn “script environment instability / a script that has not yet been implemented” into a hard error that stalls the workflow. Posting the result transparently as a signed comment (passed/failed/skipped) leaves room for human intervention without letting a sidecar verification step crash the workflow.
- **Why e2e.py is a pure sidecar module**: It depends only on `subprocess` + text, with no awareness of git/GitHub/RFC/orchestrator (principle 10: decoupling), making hermetic unit testing straightforward and allowing reuse by any caller.
- **Why location (rfc.script_path_for) and execution (e2e.run_e2e_script) are separate**: Location requires understanding RFC document semantics (reusing 0008’s `extract_e2e`), whereas execution only requires understanding subprocess; separating them allows each side to be unit-tested independently, without coupling them.
- **Alternative: write the rendered result into the PR body instead of a comment**. Rejected: the body is the domain of 0008’s signpost (a static pointer), while an execution conclusion is an event at a particular point in time. A signed comment better fits “one record per execution” and does not overwrite the body.

## Prior art

“CI posts test pass/fail and log summaries back to a PR as a status/comment” is mainstream industry practice (for example, various CI bots post check results + failure log summaries on PRs). This feature takes the core idea of “run automatically before marking ready, and post pass/fail + the log tail back to the PR” and implements it through OpenAgents’ agent-signed comment mechanism, without introducing an external CI service.

## Unresolved questions

None. The four outcome mappings, timeout cap, number of log tail lines, and non-blocking behavior on failure have all been settled within this group.

## Future possibilities

- Expand execution from the “offline deterministic stage” to a configurable real stage (the real stage currently requires manual opt-in via `OPENAGENTS_E2E_REAL=1`).
- Result comments could accumulate into a timeline / trend of the PR’s execution history.
