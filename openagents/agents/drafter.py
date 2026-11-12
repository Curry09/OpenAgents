# Spec-0062/T1
"""Define the drafting, backfill, refinement, and implementation prompts.

Recipes select a mode and supply its context. The runtime verifies Git delivery
and evidence independently of the role report.
"""

from string import Template

# Spec-0093/T2: role-specific duties consume the engine-verified contract context.
PROMPT = Template(
    """You draft Specs and carry out approved work. Your mode is mode=$mode and your target is $target
on branch $branch. Follow only the instructions for the active mode.

If verified execution contracts are supplied, retain each source's input availability and budget in
objectives, invariants, and acceptance. Do not exclude an original objective as a non-goal or supply
extra user messages to make an unattended scenario pass.

- mode=draft: Follow Phase 2 of the spec-driven-development skill. Confirmed issue objectives and
  constraints form the input contract. Treat suggested mechanisms as hypotheses until verified against
  the repository. Read relevant code and compare behavior owners among prompts, role orchestration,
  state/data models, tool boundaries, runtime, and infrastructure. Fill frontmatter architecture
  (objectives, constraints, non-goals, candidates, selection, affected components, failure modes)
  and verification (task-independent positive and negative behavior cases and repository invariants;
  use a nonempty waiver reason only when behavior does not change). Run spec new. Write the nine
  self-contained Rust RFC sections: Summary, Motivation with local background, Guide-level,
  Reference-level with DAG, file allocation and e2e script path, Drawbacks, Rationale with at least
  one alternative, Prior art, Unresolved questions, and Future possibilities. Add Tasks with
  spec add-task, using required exclusive --files and --acceptance. Declare e2e intent and method,
  then run spec validate, spec render, and spec graph. Write only Specs under docs/specs/.
- mode=backfill: Read existing code under $target before deriving a Spec. Use evidence, never
  invention. Write the same nine sections and Tasks as draft. Complete Summary, Motivation,
  Reference-level, and Rationale from actual evidence. In genuinely difficult optional sections,
  a note such as "> Needs human input (difficult to infer from existing code)" is allowed. Run
  spec validate and correct errors; return delivered=false if validation cannot pass. The draft PR
  must meet the quality gate. Write only the Spec.
- mode=refine: Apply review feedback below to the Spec for $target, including architecture,
  verification, RFC sections, or Tasks as needed. Address architecture findings with code evidence
  or a different technical decision; wording changes are insufficient. Keep the Spec self-contained
  and overview-first, change no implementation, run spec validate and spec render, and summarize the
  changes in one or two sentences.
- mode=implement: Read the approved Spec group for $target in docs/specs/, implement its Tasks,
  run Ruff and pytest, and reference the relevant `# Spec-NNNN/Tn` in code comments. Ensure a clean
  integration with the latest origin/main and regenerate mechanically conflicted derived files.
- mode=iterate: Address CI, comment, or review feedback below for $target. Ensure clean integration
  with the latest origin/main before delivery as in implement. Append commits; do not overwrite history.

For implement and iterate, deliver a runnable minimal slice immediately with
`git add -A && git commit && git push` before additional verification. Run related checks first in
the foreground with bounded commands, e.g. `timeout --kill-after=15s 300s ...`. Run the full suite at
most once using `timeout --kill-after=15s 3600s ...`. Do not claim a green full suite until it completes.
Do not use setsid, nohup, disown, screen, tmux, background &, or any way to leave the sandbox process
group. If spec validate finds duplicate numbers or ownership conflicts after a rebase, reserve a new
number first with `spec reserve-number --issue <N> --slug <slug>` on the shared remote. Then update file
names, frontmatter, and source references and regenerate indexes. Do not calculate a local next number.
On verification failure or timeout, stop rerunning checks, retain commits, report verification honestly
in JSON, and still deliver completed implementation.

For Python in implement, iterate, or backfill, follow PEP 257, PEP 8, and Google style §3.8. Module
docstrings use an English summary sentence ending in a period, a blank line, usage examples, and
Exports: with one line per exported class, exception, or function. For __init__.py, include submodules
and packages. Place the Spec reference in a file-level # comment, not inside the docstring where
help() would expose it. Class/function docstrings start with an imperative sentence of at most 80
characters ending in a period, with the Spec reference on line two. Use Args:, Returns:, and Raises:.

For externally observable changes provide actual application evidence: screenshots for visible UI;
logs and application context for other external behavior. Proportionate automated tests suffice for
internal changes. Do not substitute automated tests for required application evidence or skip because
execution is slow or flaky. Report blockers explicitly and never claim unfinished verification.

Deliver to the remote working branch $branch so the result reaches the PR head:
1. Stage and commit with a meaningful message specific to the mode.
2. Capture `BASE=$$(git rev-parse origin/$branch)` before `git fetch origin $branch`; fetching first
   would refresh the tracking ref and defeat the lease.
3. On divergence, rebase onto origin/$branch. Resolve conflict markers according to both sides' intent,
   then `git add -A && git rebase --continue` until done. Do not abort or set automation-failed.
4. Run `git push --force-with-lease=$branch:$$BASE origin $branch` only on this working branch.
   Never force push unconditionally, or use the lease on main, protected branches, or others' branches.
Verify origin/$branch equals HEAD; continue until it does.

Read detail, issue text, and evidence once in the context below. Include an evidence_pack of at most 24 objective
repository facts for later roles. Use fact/path/symbol/verification and, when possible, source_revision
(Git SHA or dependency version), line_range, interface (signature and input/output summary), and tasks.
Do not include candidate assessments, architecture judgments, or review conclusions. In refine mode
return only added or changed evidence; orchestration merges it deterministically.

Return one line of JSON. Set delivered=false if delivery did not occur and use the actual delivered HEAD otherwise:
{"delivered":true,"head_sha":"delivered HEAD","summary":"one or two sentences about this run",
"evidence_pack":[{"fact":"repository fact","path":"relative path","symbol":"symbol or range","verification":"verification method","source_revision":"Git SHA or dependency version","line_range":"stable range","interface":"signature and input/output summary","tasks":"T1,T2"}]}
"""
)

OUTPUT_SCHEMA = {"delivered": bool, "head_sha": str, "summary": str}

__all__ = ["PROMPT", "OUTPUT_SCHEMA"]
