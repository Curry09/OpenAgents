---
number: "0020"
title: "Human oversight gates: requirements alignment before issue creation + tiered vigil --hold gates"
issue: 59
slug: human-oversight-gates
summary: "Add two human oversight gates to OpenAgents: \"requirements alignment\" before issue creation (restate a vague idea as what to do X / boundaries Y / what not to do Z for a human to confirm), and tiered --hold gates in the vigil autonomous loop (pause at key points such as spec approval and PR merging to wait for human approval). Shift humans from watching details to overseeing the big picture; insert configurable pauses only at key points, without changing the internal logic of the existing issue→PR automated workflow."
tasks:
  - id: T1
    title: "Entry-point alignment module: restate vague ideas as X / boundaries Y / what not to do Z"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/align.py
      - tests/test_align.py
    scope: "Create a pure module openagents/align.py: given an issue draft (title/body), call an injected backend to restate it in plain language as three structured sections, \"I understand that you want X, the boundaries are Y, and Z is out of scope,\" for the caller to present to a human for confirmation. Handle only restatement rendering and confirmation evaluation; do not interact with GitHub or CLI argparse. Split restatement generation (which requires a backend) and confirmation evaluation (a pure predicate) into two functions so that the --yes automation path can skip restatement. Reference Spec-0020 in the module docstring."
    acceptance: "restate(*, draft, backend), given an issue draft, calls the injected backend and returns an Alignment containing three sections: want(X)/boundary(Y)/non_goals(Z); its human-readable rendering includes identifiers for all three sections. Confirmation evaluation is a separate pure predicate: an affirmative response allows proceeding, while a negative/empty response does not, and it does not call the backend. The module contains no GitHub/argparse/stdin reads, and the backend is injected as a keyword argument. All tests in tests/test_align.py pass with a stubbed backend and are hermetic (never accessing a real LLM)."
  - id: T2
    title: "hold configuration model: parse spec,merge into a set of gates"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/hold.py
      - tests/test_hold.py
    scope: "Create a pure module openagents/hold.py: parse the comma-separated --hold string ('spec'/'merge'/'spec,merge'/empty) into an immutable Hold configuration (with at_spec/at_merge predicates). Trim whitespace from each token and normalize case for mapping; empty/None→no pauses anywhere (the default vigil behavior). For an invalid token, immediately raise a clear error that includes the valid values. No I/O, argparse, or GitHub. Reference Spec-0020 in the module docstring."
    acceptance: "parse_hold(*, raw): ''/None→default Hold(at_spec=at_merge=False); 'spec'→at_spec only; 'merge'→at_merge only; 'spec,merge' and 'merge,spec'→both True; an unknown token (such as 'foo')→raise a ValueError-type error and list the valid values (spec/merge); extra whitespace/case variations (such as ' Spec , Merge ') are normalized and parsed correctly; Hold is an immutable value object exposing only at_spec/at_merge; all tests in tests/test_hold.py pass (pure functions)."
  - id: T3
    title: "Tiered pipeline gates: pass hold through to poll to branch at the two gates"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/vigil.py
      - openagents/messages.py
      - tests/test_vigil.py
      - tests/test_messages.py
    scope: "vigil.run accepts Hold and passes it through to messages.poll; messages branches according to Hold at the spec gate (_process_rfc_review) and the merge gate (_process_coding): hold.at_spec→disable the automatic reviewer and recognize only a human-applied rfc-approved label; hold.at_merge→after CI is green and review is PASS, do not automatically call merge_pr, leaving the merge to a human. Behavior with the default Hold (no pauses anywhere) is byte-for-byte identical to the current behavior. Pass hold as a poll method argument rather than a Messages constructor argument, keeping the T3/T4 file boundaries clean. Reference Spec-0020 at the modified locations."
    acceptance: "vigil.run accepts hold and passes it through to messages.poll on every iteration (it must be possible to assert that the hold received by poll is the value passed in); spec gate with hold.at_spec: without an rfc-approved label→do not call the automatic reviewer/apply a label/call implement (remain in rfc-review), with a human-applied label→call implement as usual; merge gate with hold.at_merge: CI green + PASS→do not call merge_pr, leave the state unchanged, and after a human merges manually, the is_merged branch on the next iteration reconciles to done as usual; the spec,merge combination pauses at each gate independently; with the default Hold, existing automatic review/automatic merge cases all pass with zero regressions; all tests in tests/test_vigil.py + tests/test_messages.py pass."
  - id: T4
    title: "CLI wiring: alignment at the issue entry point + vigil --hold flag"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: "Wire this in cli.py as the single wiring layer: (1) For openagents issue, insert one round of alignment confirmation before calling create_issue—use T1 align to restate, and create the issue only after human confirmation; add --yes to skip this for automation. (2) Add a --hold flag to the vigil subcommand, use T2 parse_hold to parse it into Hold (None→the default of no pauses anywhere), and pass it to T3's vigil.run(hold=...); route invalid values through the existing exception channel to produce a one-line message. Import align/hold lazily. Handle only argument parsing and dispatch, with business logic delegated to align/hold/vigil. Reference Spec-0020 at the modified locations."
    acceptance: "The default openagents issue path calls align.restate to restate the request and asks for human confirmation before creating an issue; only confirmation (y) leads to create_issue, while rejection (n) creates no issue and exits with a nonzero status; openagents issue --yes skips restatement and confirmation and calls create_issue directly; openagents vigil --hold spec|merge|spec,merge parses the value with parse_hold and calls vigil.run(hold=...) with that Hold, while omitting --hold→the default of no pauses anywhere; an invalid --hold value→a clean one-line error + nonzero exit (no traceback); cli.py handles only argument parsing/dispatch; all tests in tests/test_cli.py pass and are hermetic (with align/github/vigil stubbed)."
  - id: T5
    title: "e2e script: demonstrate pausing at spec → human approval → continuation"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0020-hold-gate.sh
    scope: "Add an offline e2e script scripts/e2e-spec-0020-hold-gate.sh (following the style of existing scripts/e2e-*.sh, using stubs/local state to simulate GitHub, runnable in CI): demonstrate vigil --hold spec pausing to wait for a human after the spec is written; simulate a human applying the rfc-approved label, then poll once more so that the pipeline continues into coding. The comment at the top of the script references Spec-0020 and explicitly identifies the soft dependency on issue-58 for the basis of spec approval (the OVERVIEW summary)."
    acceptance: "scripts/e2e-spec-0020-hold-gate.sh can run independently offline with bash (using stubs/local State to simulate GitHub, requiring no credentials, runnable in CI and repeatable); demonstration timeline: run one iteration with --hold spec→assert that it pauses at the spec gate (no automatic review/no automatic label application/no implement call, with the state still rfc-review), simulate a human applying the rfc-approved label, then run another iteration→assert that progress resumes (calls implement and enters coding); print a human-readable \"pause→approve→continue\" trace, exit with code 0 if all assertions pass, and exit with a nonzero code if any assertion fails; use the same directory and naming convention as the existing e2e scripts (e2e-spec-NNNN-<slug>.sh)."
---

# 0020 · Human Oversight Gates: Requirements Alignment Before Issue Creation + Tiered vigil --hold Gating

<!-- This file is maintained by the spec tool: the frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Add two **human oversight gates** to OpenAgents, moving human review upstream from “reviewing PRs after the fact” to the intent level:

1. **Front-door alignment**—before creating an issue, have the agent restate your vague idea in plain language in three parts: “I understand that you want **X**, the boundaries are **Y**, and we will not do **Z**.” Create the issue only after you approve (`--yes` can skip this for automation).
2. **Tiered vigil `--hold` gates**—add an optional flag to the autonomous loop so the pipeline pauses at key points to wait for a person: `--hold spec` pauses after the spec is written and before any code changes, proceeding only when a human applies the `rfc-approved` label; `--hold merge` automatically proceeds all the way to a PR, leaving the final merge to a person; without `--hold`, everything remains fully automatic as before.

Let people shift from watching details to overseeing the big picture; insert configurable pauses only at key points, **without changing the internal logic of the existing issue→PR automation flow**.

## Motivation

**Current behavior (restated in full, without requiring readers to consult another spec).** OpenAgents’ existing poll state machine has already narrowed human touchpoints to “creating an issue” and “promote / release”: after an issue is claimed, the agent drafts a spec and opens a draft PR; at the spec gate, an agent reviewer **automatically reviews it and automatically applies the `rfc-approved` label** to allow coding to begin; at the merge gate, the PR is **automatically merged** after **all CI checks are green + reviewer PASS**. The entire issue→PR→merge chain is fully automatic, and people generally do not intervene midway.

**Problem: the only real checkpoint comes too late.** In this fully automated chain, a person’s **only** real review checkpoint is PR review—meaning misunderstandings are exposed only after all the code has been written, the most expensive point at which to correct them. Principle 5 in CLAUDE.md, “People oversee the big picture, not the details,” lacks two kinds of gates:

- **An intent-level gate**: before an idea becomes a formal issue, there is no checkpoint that aligns the scope in language a person can understand, so vague requirements carry through into the code.
- **Tiered oversight**: full automation is a good default, but people sometimes want to reinsert oversight at **intent checkpoints** such as spec approval or PR merge—there is currently no switch for this; it is either fully automatic or has no intermediate setting.

Issue #59 asks for precisely these two gates: front-door **requirements alignment** + **optional tiered `--hold`** for vigil. The key constraint is “tiered”—the default behavior must not change by a single byte, and a corresponding gate pauses only when a person explicitly selects it.

## Guide-level explanation

Two new behaviors are visible to users; the default experience remains unchanged:

| Scenario | Command | Behavior |
|------|------|------|
| Create an issue | `openagents issue <title> [--body]` | Before creating the issue, print the agent’s three-part restatement, “Do X / Boundaries Y / Do not do Z,” and ask you to confirm with y/n; create it only on confirmation, and abort cleanly without creating it if declined |
| Create an issue through automation | `openagents issue <title> --yes` | Skip the restatement and confirmation and create it directly (for scripted paths such as vigil/CI) |
| Default autonomous loop | `openagents vigil` | Byte-for-byte identical to before, fully automatic |
| Pause at the spec gate | `openagents vigil --hold spec` | Pause after writing the spec and before changing code; proceed only when a human applies the `rfc-approved` label |
| Pause at the merge gate | `openagents vigil --hold merge` | Automatically proceed all the way to a PR; after CI is green + review passes, **do not merge automatically**, leaving the final merge to a person |
| Pause at both gates | `openagents vigil --hold spec,merge` | Pause at each gate according to its own rules |

An invalid `--hold` value (such as the typo `spc`) produces a clean one-line error + a nonzero exit, rather than being silently treated as “pause nowhere” and quietly discarding oversight.

## Reference-level explanation

The changes are divided into 5 Tasks (see the DAG below; `files` are mutually exclusive, with a single writer per Task):

1. **T1 Front-door alignment module** (no dependencies)—create the pure module `openagents/align.py`: `restate(*, draft, backend) -> Alignment` takes an issue draft and calls an **injected backend** (the same backend abstraction as Orchestrator, using dependency injection rather than importing a concrete implementation) to restate it in plain language as a three-part structured object, `want(X)/boundary(Y)/non_goals(Z)`. `Alignment` provides stable, human-readable rendering. Split **restatement generation** (which requires a backend) and **confirmation evaluation** (a pure predicate that takes a person’s response and returns whether to proceed) into two functions: this makes them independently testable and lets T4’s `--yes` path skip restatement without constructing a backend. The module contains no GitHub / argparse / stdin.
2. **T2 hold configuration model** (no dependencies)—create the pure module `openagents/hold.py`: `Hold` is a frozen value object carrying only the two Boolean intents `at_spec` / `at_merge` (corresponding to the two gates listed in the issue; deliberately avoid an open-ended enumeration to keep it minimal). `parse_hold(*, raw) -> Hold` splits the comma-separated string, trims whitespace, normalizes case, and maps each token; empty/None → pause nowhere by default; unknown token → raise a ValueError-type error listing the valid values. Use a standalone module rather than an inline argparse `type=` so the CLI and tests can share the same parser and avoid drift from strings scattered across multiple locations.
3. **T3 Tiered pipeline gates** (depends on T2)—add a `hold` keyword parameter to `vigil.run(*, ..., hold)` (defaulting to an instance that pauses nowhere, backward-compatible with existing calls), and pass it through to `messages.poll(*, hold)` on every iteration; vigil itself does not consume Hold and remains a thin scheduling loop, carrying the intent to the messages layer where the actual branching occurs. Branch at the two messages gates according to Hold: **spec gate `_process_rfc_review`**—when `at_spec` is set, skip the automatic reviewer and retain only “implement if a human-applied `rfc-approved` label is present; otherwise do nothing this iteration and wait for a person at the spec gate”; **merge gate `_process_coding`**—when `at_merge` is set, CI/iterate/review continue as usual, but after reviewer PASS, do not call `merge_pr`; pause at “awaiting human merge” (the PR remains open). After a person manually merges it, the next iteration’s `is_merged` branch reconciles it to done as usual (reuse existing logic, with no new State required). Branch by “adding an `if hold.at_xxx` early return” to the existing paths; the default branch runs the original code unchanged. Pass hold through a poll **method parameter**, rather than a Messages constructor parameter, to avoid changing the CLI’s `_messages_for` factory and keep the T3/T4 file boundaries clean.
4. **T4 CLI wiring** (depends on T1, T2, T3)—cli.py is the sole command entry point for people and handles only argument parsing and dispatch. In `_cmd_issue`, insert a step before calling `github.create_issue`: construct a backend, call T1’s `align.restate` to obtain the restatement, print it for the person, and read y/n; create the issue only on confirmation, and abort cleanly if declined. Add a `--yes` switch to skip restatement and confirmation and create the issue directly. Add `--hold` to the `vigil` subcommand (a comma-separated string, default None); in the handler, use T2’s `parse_hold` to parse it into Hold (None → pause nowhere) and pass it to `vigil.run(hold=...)`; parsing errors are handled by the existing `_run` exception→one-line-message channel. Import align / hold lazily to keep the CLI’s top level lightweight and allow stubbing in tests. **Note**: issue alignment and vigil `--hold` both modify the same file, cli.py. Under the spec collaboration model’s constraint that “files must not overlap between Tasks,” they must be combined into one Task (cli.py is the single wiring point).
5. **T5 e2e script** (depends on T3, T4)—add the offline script `scripts/e2e-spec-0020-hold-gate.sh`, following the existing `scripts/e2e-*.sh` pattern (use stubs/local State to simulate remote GitHub, drive vigil/poll offline, and assert observable signals, without accessing real gh; runnable and repeatable in CI). Demonstration timeline: ① prepare a run in the rfc-review stage with a draft PR already open and no `rfc-approved` label; ② run one iteration with `--hold spec` → assert that it pauses at the spec gate (no automatic review, no automatic label application, no implement, and the state remains rfc-review); ③ simulate a person applying the `rfc-approved` label to the PR; ④ run another iteration → assert that progress resumes (execute implement and enter coding); ⑤ print a human-readable “pause→approve→continue” trace and exit with code 0.

**End-to-end validation**: `bash scripts/e2e-spec-0020-hold-gate.sh` (offline stubs, demonstrating the complete “pause at spec → human approval → continue” timeline).

Dependency DAG: `T2 → T3`, `T1 → T4`, `T2 → T4`, `T3 → T4`, `T3 → T5`, `T4 → T5`. T1 and T2 can start in parallel.

## Drawbacks

- Introduces a backend dependency into the `openagents issue` path (the restatement uses an LLM)—mitigated through injection rather than hard-coding, with a stub backend keeping tests hermetic.
- Because both features modify cli.py, T4 is forced to combine two features (issue alignment and vigil `--hold`) into one Task, spanning two concerns; mitigated by keeping the CLI purely responsible for wiring and placing all logic in the modules it depends on.
- The two `--hold` gates add configurable branches to the pipeline, requiring regression cases with the default Hold to preserve “zero regression by default.”

## Rationale and alternatives

- **LLM restatement vs. deterministic templates** (choose LLM): templates have zero dependencies and work offline, but can only mechanically echo the title/body; they cannot provide “inferred boundaries and non-goals,” contrary to issue #59’s original intent to “restate in plain language and reorganize.” Choose an LLM and reuse the existing backend; use injection + stubs to control dependencies and testability.
- **Combine vs. split restatement generation and confirmation evaluation** (choose split): splitting adds one function, but lets the `--yes` automation path work without a backend and makes the two pieces of logic independently testable.
- **Two Boolean fields vs. an open-ended enumeration set for Hold** (choose two Booleans): a set is more “extensible,” but there are currently only two gates and the issue asks for no more; an open-ended set is overengineering. Two named predicates read more directly and make consumer branches clearer. Refactor later if more gates are added.
- **Strict parsing errors vs. silently ignoring unknown tokens** (choose strict): silently ignoring them would treat a mistyped `--hold spc` as “pause nowhere,” quietly discarding oversight and violating safe defaults; a strict error makes the problem immediately visible.
- **Pass hold through a poll method parameter vs. a Messages constructor parameter** (choose method parameter): a constructor parameter would require changing the CLI’s `_messages_for` factory and pull cli.py into T3’s scope; a method parameter lets hold follow the vigil→poll call chain, keeps file ownership clean, and better reflects that “hold is the intent for this run, not an inherent instance property.”
- **Stop the reviewer when holding at the spec gate vs. retain the reviewer but disable automatic approval** (choose stop): retaining it would keep consuming backend resources and blur the meaning of “waiting for human approval”; stopping it is the simplest, most economical option with the clearest semantics—“hold spec means handing this gate entirely to a person.”
- **Offline e2e mocks vs. real GitHub round trips** (choose offline): real round trips require credentials, are not repeatable in CI, and are slow and brittle; all existing e2e scripts use offline stubs, so follow the same pattern to ensure discoverability, repeatability, and CI integration.
- **Issue alignment enabled vs. disabled by default** (choose enabled by default, disabled with `--yes`): issue #59’s acceptance criteria require “a round of alignment and confirmation before creation (skippable with `--yes`)”; retain the safe default for people and give scripts the ability to skip it.

## Prior art

- “Restate and align vague requirements before starting work” is a standard requirements-engineering practice (restate / reflect back). This feature adopts its lightweight form: one three-part restatement + human approval, without introducing heavyweight requirements documents.
- The “define once, reference in multiple places” parsing model follows the same structural idea as the existing RFC-0015, “Single Source of Truth for Workflow Labels,” whose numbering is unrelated to this group—only its single-definition pattern is borrowed, to avoid drift from the same string being scattered across multiple locations; it does **not** share a number or scope with this group’s Spec-0020.

## Unresolved questions

- “Approval after reading the spec” depends on the human-readable summary from #58: people cannot sign off on a mass of technical task YAML. This group implements only the gating mechanism and does **not** implement the summary; the basis for approval that people see when execution pauses at the spec gate (the OVERVIEW summary) is provided by the #58 / Spec-0014 system. If #58 is not ready, `--hold spec` can still pause execution and allow it to proceed, but the human reading experience is degraded—explicitly note this soft dependency in the T5 e2e and rollout notes.

## Future possibilities

- `--hold` can be extended to support more gates (such as confirmation before a release), but this requires reconsidering the trade-off between “two named booleans” and “an open-ended set of enum values”; defer this until a real need arises.
- Beyond the hold at the spec gate, a separate command could provide “preliminary reviewer feedback” for people to consult before approval, keeping it out of this gate to preserve the clarity of its semantics.
