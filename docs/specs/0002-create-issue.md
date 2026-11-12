---
number: "0002"
title: "OpenAgents proactively creates issues"
issue: 0
slug: create-issue
summary: "Enable OpenAgents to proactively create issues in the repository in addition to passively taking on issues. Add create_issue to the github layer and an issue subcommand to the CLI, and apply a discovery label to automatically discovered issues, ensuring that the label exists."
tasks:
  - id: T1
    title: "github layer create_issue"
    status: done
    priority: P1
    tags:
      - cli
      - github
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: "Add create_issue(*, title, body, labels) in openagents/github.py to call gh issue create, parse the issue number, and return an Issue; add a _parse_issue_number helper; and ensure that the required labels exist (ensure label, the github portion of the original T3, decision 6)."
    acceptance: "Unit test coverage—successfully parsing the number; the command includes --label when labels are provided; raising GithubError when the url cannot be parsed; raising GithubError when gh exits with a nonzero status."
  - id: T2
    title: "CLI issue subcommand"
    status: done
    priority: P1
    tags:
      - cli
      - github
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: "Register the issue subcommand in openagents/cli.py (positional title + --body + repeatable --label), implement _cmd_issue to run preflight and call github.create_issue, and add it to the _dispatch handlers; in _cmd_issue, also append the module-level DISCOVERY_LABEL=\"openagents\", deduplicate, and sort (the cli portion of the original T3, decisions 5/6)."
    acceptance: "Unit test coverage—the parser registers issue; issue \"T\" --body B --label x --label y correctly passes the arguments through to the stubbed create_issue and runs preflight; the return code is 0; the openagents discovery label is automatically appended in addition to the --label values, with duplicates removed."
---

# 0002 · OpenAgents Proactively Creates Issues

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Extend OpenAgents from “only passively taking on issues” to “also proactively creating issues in repositories.” Add `create_issue` to the github layer, expose an `issue` subcommand in the CLI, and consistently apply the discovery label `openagents` to automatically discovered and proactively created issues (ensuring that the label exists in the repository before creation), so that subsequent workflows can identify and pick up proactively created issues by label.

## Motivation

OpenAgents currently supports “claim an existing repository issue → draft changes → open a PR”; issue creation depends entirely on external input. But as a product intended to “iterate on itself,” the agent needs to be able to **proactively turn discovered problems and ideas into issues**, closing the workflow loop: discover → create an issue → claim → resolve → PR.

Three pieces are missing:

- The github layer has no wrapper for “creating an issue” (only operations for reading/listing issues and working with PRs).
- The CLI has no entry point for a person or agent to create an issue manually.
- Proactively/automatically generated issues need a stable **discovery label** to distinguish them from manually created issues, and that label must actually exist in the repository (otherwise `gh issue create --label` will fail because the label is missing).

## Guide-level explanation

Users create an issue with a single command:

```
openagents issue "Title" --body "Body" --label bug --label p1
```

It runs the same preflight checks as other commands, then creates an issue on GitHub. Whether or not the user explicitly supplies `--label`, the command automatically appends the discovery label `openagents` (deduplicating in order of appearance, without adding it again if already present), and ensures that the `openagents` label exists in the repository before creation. The fallback used by Vigil for automatic discovery also uses this same constant, ensuring consistent labeling of “proactively created” and “automatically discovered” issues.

## Reference-level explanation

The changes are split into 2 Tasks (see the DAG below; `files` are mutually exclusive, with a single writer for each Task). Note: “discovery label + ensuring the label exists (decisions 5/6)” was originally a separate small Task, but it modified both `cli.py` (owned by T2) and `github.py` (owned by T1), with no files exclusively its own. Under the single-writer principle, its cli portion is merged into T2 and its github portion into T1.

1. **T1 github-layer create_issue + ensure_label** — Add `create_issue(*, title, body, labels)` to `openagents/github.py`: call `gh issue create` (including `--label` in the command when labels are supplied), parse the issue number from the output URL, and return an `Issue`; extract the parsing logic into a `_parse_issue_number` helper. Raise `GithubError` if the URL cannot be parsed or `gh` exits with a nonzero status. Also add `ensure_label` (create the label if it does not exist, suppress `"already exists"` if it already exists, and propagate other gh errors as usual; decision 6), ensuring that the label exists when creating an issue with `--label openagents`. This provides the lowest-level capability for “creating an issue.”

2. **T2 CLI issue subcommand + discovery label** (depends on T1) — Register the `issue` subcommand in `openagents/cli.py`: positional `title` + `--body` + repeatable `--label`; `_cmd_issue` runs preflight first, then calls `github.create_issue`, and is added to the handlers table in `_dispatch`. Introduce the module-level constant `DISCOVERY_LABEL = "openagents"`; `_cmd_issue` appends `DISCOVERY_LABEL` to the user's `--label` values and deduplicates in order of appearance, calling `github.ensure_label(name=DISCOVERY_LABEL)` before creation; change the discovery fallback in `_cmd_vigil` to use the same constant (decision 5). This is the sole CLI entry point for people/agents to create issues.

**Decisions 5/6 restated (self-contained)**: All proactively/automatically generated issues carry the same discovery label, `openagents`, so that subsequent workflows can identify them by label; to prevent creation from failing because `--label` references a nonexistent label, idempotently ensure that the label exists before creation.

**End-to-end verification**: This group has no standalone `scripts/*.sh` e2e scripts; verification relies on each Task's unit tests in `tests/test_github.py` and `tests/test_cli.py` (stubbing the `gh` subprocess and asserting command construction, number parsing, label appending and deduplication, ensure_label calls, and error propagation).

Dependency DAG: `T1 → T2` (linear, no parallelism).

## Drawbacks

- Forcing the `openagents` label onto all proactively created issues introduces a conventionally reserved label into the repository's labeling scheme; if the repository already has a label with the same name but different semantics, ambiguity may result.
- `ensure_label` adds one extra `gh` call before each creation (suppressing the error if the label already exists), adding a small overhead to the creation path in exchange for the idempotent guarantee that “the label exists.”

## Rationale and alternatives

- **Why use a module-level constant for the discovery label instead of scattered literals**: `_cmd_issue` and `_cmd_vigil` share the same constant, `DISCOVERY_LABEL`, preventing label conventions from drifting between “proactively created” and “automatically discovered” issues (decoupling + a single source).
- **Why call `ensure_label` before creation instead of relying on repository setup**: A new repository may not have this label, causing `gh issue create --label openagents` to fail outright; idempotent `ensure_label` (suppressing "already exists") makes the creation path self-contained, without requiring manual label creation in advance.
- **Alternative: identify the discovery source with a marker string in the issue body instead of a label**. Rejected: labels are a first-class search dimension in GitHub, and filtering/picking up issues by label is far more robust than parsing body text.
- **Extract number parsing into a `_parse_issue_number` helper**: Centralize fragile URL parsing and error raising in one place, making it easier for unit tests to cover each failure branch.

## Prior art

`gh issue create` is the standard entry point for creating issues in GitHub's official CLI; using labels to mark “bot/automated origins” is common community practice (for example, various bots use dedicated labels to mark automatically generated issues/PRs). This feature follows the existing pattern of “a dedicated discovery label + idempotently ensuring the label exists,” without introducing an additional metadata channel.

## Unresolved questions

None. The discovery label value (`openagents`), deduplication order (order of appearance), and the boundary for suppressing versus propagating ensure_label errors (suppress only "already exists") have all been settled within this group.

## Future possibilities

- When an agent discovers related problems while resolving an issue, automatically invoke this capability to split them out into child issues.
- Make the discovery label configurable, or subdivide it into multiple labels by source (manual discovery / Vigil automatic discovery).
