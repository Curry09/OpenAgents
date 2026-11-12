---
name: spec-driven-development
description: >
  Design and implement substantive OpenAgents changes using a self-contained Spec, a task
  dependency graph, explicit file ownership, and verification. Use for new components, public
  contracts, persistence changes, and cross-module designs.
---

# Spec-Driven Development

Use English for the active Spec, model instructions, and code comments. Numbered source Specs live
in `docs/specs/NNNN-slug.md`; each has YAML frontmatter and a nine-section Rust RFC-style overview.
Generate the overview and architecture views with `spec render` and `spec graph`. Git records design
revisions and dropped tasks.

## 1. Clarify the request

Identify unresolved objectives, scope, affected components, and compatibility constraints. Ask focused
questions when their answers change the design. Confirm the requirements before designing. Record the
agreed objective and constraints in the Spec itself.

## 2. Design the Spec

Create a group for major components, public interface or protocol changes, data or persistence changes,
cross-module work, or design trade-offs. A small change can skip a group only when it affects one file
or module, needs one task, and has no design decision to record. Extend an existing group when the work
naturally belongs there.

1. Run `spec new <slug> --issue <N> --title "<title>" --summary "<summary>"`. Shared repositories
   reserve a number atomically under `spec-reservations/NNNN` on the remote. Resolve remote errors
   before continuing. If an existing PR needs to renumber, run
   `spec reserve-number --issue <N> --slug <slug>` before changing names, metadata, source references,
   tests, and generated views. Never guess the next shared number from a local checkout.
2. Read the current code. Identify behavior owners, reachable interfaces, and relevant repository
   evidence. Compare viable alternatives and record invariants, failure modes, and acceptance.
3. Write the nine sections before adding tasks. Summary, Motivation, Reference-level explanation, and
   Rationale and alternatives are required. Restate essential context instead of relying on a bare
   reference to another Spec. Include the task graph, file allocation, and verification method in the
   reference section. Consider at least one alternative.
4. Add tasks with `spec add-task`. Each task has explicit `files` and `acceptance`, and declares
   `depends-on` where required. Within the group, each file has exactly one owning task. Across issues,
   use separate worktrees. Use qualified task references (e.g. `0012/T2`) across groups.
5. Aim for at most six tasks per group. This is a readability warning, separate from the hard
   single-writer requirement. Set `oversized-rationale` for an atomic delivery that needs more than
   six tasks; split unrelated work into distinct groups.
6. Resolve design questions with the operator or record those intentionally left open. Run
   `spec validate`, `spec render`, and `spec graph`. Present the Spec and file allocation for review
   before implementation.

See the [field reference](references/task-fields.md) for the exact headings and task fields.

## 3. Implement and verify

Start a pending task after its dependencies are done. Set its frontmatter status to `in-progress`.
Change only the task's allocated files and cite `# Spec-NNNN/Tn` where it clarifies the design.
Follow the [code comment conventions](references/code-comment-conventions.md).

Run the [verification checklist](references/verification-checklist.md) and provide real application
evidence for user-visible changes. Test internal changes proportionately. Report blocked checks and
unfinished validation accurately. If the design needs revision, update the Spec and revisit approval
before proceeding outside the approved scope.

Mark verified tasks `done`, leaving them in the snapshot to map to live code. Use `spec abandon` to
drop a task entirely. Regenerate both views, verify them against the latest base, and present the
candidate and evidence for review.
