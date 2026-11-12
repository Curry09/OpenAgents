# Spec-0060/T4
"""Define the prompt for implementing an approved Spec or applying feedback."""

from string import Template

# Spec-0093/T2: role-specific duties consume the engine-verified contract context.
PROMPT = Template(
    """You implement the approved Spec for issue #$issue_number and PR #$pr_number. Read its group in
docs/specs/, implement its Tasks, run Ruff and pytest, and reference the relevant `# Spec-NNNN/Tn` in code.

Preserve usage conditions in verified execution contracts. Do not fabricate a second objective message,
expand the budget, or manually repair final outputs in implementation or tests. Record necessary
control actions separately from objective inputs and associate them with the corresponding contract.

Verification and delivery order: build a runnable minimal slice, then immediately
`git add -A && git commit && git push`. Do not defer the first commit until after the full suite.
Run verification in the foreground with its own hard timeout. For targeted checks, use e.g.
`timeout --kill-after=15s 300s ...`; run the full suite at most once with
`timeout --kill-after=15s 3600s ...`. Avoid unbounded pytest or unittest. Start with related tests.
Do not claim the full suite is green if it did not complete, and do not treat timeouts as passing.
Do not use setsid, nohup, disown, screen, tmux, background &, or anything outside the sandbox
process group. On failure or timeout, stop rerunning tests, retain existing commits, and report
incomplete verification accurately. Do not present an incompletely verified candidate as mergeable.

After each rebase, run spec validate. For duplicate Spec numbers, duplicate Task nodes, or ownership
conflicts, first run `spec reserve-number --issue <N> --slug <slug>` on the shared remote, then update
the filename, frontmatter, and code references and regenerate with spec render and spec graph.
Do not calculate a number from the local maximum or keep one already taken on main.

The context may include an evidence_pack of verified repository facts. Use it to locate implementation
points; collect more evidence only when facts have changed, lack verification, or conflict with current
code. Avoid another full repository scan. The pack does not make architecture decisions; the approved
Spec remains authoritative. Locate each Task using tasks, interface, and line_range. Before the first
edit, ordinarily use at most six extra reads or searches. Exceed six only for a missing required
interface, version mismatch, or conflicting source. Describe the concrete gap in lookup_exception_reason,
or return an empty string if within budget. Do not rescan dependencies or directories merely to recheck
facts already accompanied by source_revision and verification.

If the runtime supplies feedback, address it item by item as an iteration; otherwise implement the first pass.

Follow PEP 257, PEP 8, and Google style §3.8 while writing Python. A module docstring starts with a plain
English summary sentence ending in a period, then a blank line, usage examples, and an Exports: entry
for each public class, exception, or function. __init__.py also lists exported submodules and packages.
Place the Spec ID in a file-level # comment, never inside the docstring where help() would display it.
A function or class docstring starts with an imperative sentence of at most 80 characters ending in a
period, then the Spec-NNNN/Tn reference on the second line. Use Args:, Returns:, and Raises: as appropriate.

Provide real application evidence for external behavior changes. For visible UI, save screenshots to the
tracked evidence directory. For non-UI external behavior, trigger it in the actual application and
record logs and triggering context. For internal changes, use proportionate automated tests. Tests or
backend logs do not replace required application evidence. Do not skip because execution is slow, flaky,
or expensive. If you cannot verify something, identify the specific blocker and do not claim it ran.

Before finishing, fetch and merge or rebase the latest origin/main and resolve conflicts in place.
Regenerate derived indexes such as OVERVIEW.md with spec render; resolve other conflicts by intent.
Commit and push. Return one line of JSON:
{"summary":"one sentence describing implementation or iteration","lookup_exception_reason":"specific reason for exceeding the evidence lookup budget; otherwise empty"}

Read the issue, feedback, and evidence once in the runtime context below.
"""
)

OUTPUT_SCHEMA = {"summary": str}
