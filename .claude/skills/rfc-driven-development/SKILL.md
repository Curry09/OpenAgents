---
name: rfc-driven-development
description: >
  RFC-driven development for OpenAgents: requirements clarification → RFC design with
  subtask DAG (each subtask carries an explicit file list) → implementation with verification.
  Use this skill whenever the user wants to plan, design, or architect a non-trivial feature —
  even without saying "RFC". Triggers on: "RFC", "design doc", "technical design",
  "plan a feature", "break this down", "architect this", or any task involving multiple
  components, trade-offs, or cross-module changes that benefits from design-before-code.
  Supports multi-agent parallelism via subtask DAG + file allocation.
---

# RFC-Driven Development

Structured workflow for OpenAgents: **Requirements -> RFC Design (Subtask DAG + File Allocation) -> Implementation & Verification**.

Each phase requires human approval before proceeding. Within each phase, work autonomously.

## Language Convention

This skill's instructions are written in English for better model comprehension. The RFC
documents themselves are written in Chinese (read by the team). Code comments may be English
or Chinese — clarity over language choice (see `references/code-comment-conventions.md`).

## Core Principles

1. **RFC as single source of truth** — RFC documents persist as cross-task memory. Requirements get absorbed into RFCs. The subtask DAG lives in the RFC so any agent session can read it.
2. **Human-in-the-loop at phase gates** — Humans approve phase transitions; agents execute within phases.
3. **RFC ID as code index** — Implementation references RFC IDs in comments so other agents can trace code back to design rationale. See `references/code-comment-conventions.md`.
4. **Parallelism through DAG + file allocation** — The subtask DAG declares dependencies; each subtask declares the files it owns. In collaborative mode (one worktree) agents avoid conflicts by only touching files allocated to their subtask. See "Work Modes" below.

## Work Modes

OpenAgents has two parallelism layers (CLAUDE.md 设计理念 5–6):

- **协同工作模式（collaborative, same worktree）** — multiple agents implement one RFC/issue together in a single worktree. Conflict-free because each subtask owns a disjoint set of files (the DAG's file list). This is the default within one RFC.
- **多 worktree 模式（across issues）** — different issues run in separate worktrees in parallel. Each worktree drives its own RFC(s).

Within a single RFC, always use collaborative mode and rely on the per-subtask file list.

## RFC Scope Boundaries

### When to Create an RFC

Generate an RFC for any of these changes:
- New module / service / major component
- Public interface or protocol changes (e.g. agent message protocol)
- Data model / persisted state changes
- Cross-module feature implementations
- Anything with design trade-offs worth recording

### When to Skip RFC (Implement Directly)

Skip the RFC process when ALL of the following are true:
- No design decisions to document (no trade-offs to discuss)
- Only affects a single module/file
- Only requires 1 subtask

### Merge into Existing RFC

If a small feature is a natural extension of an existing RFC's scope, add it as a new subtask to that RFC rather than creating a new one.

### When to Split an RFC

If an RFC has more than 6 subtasks, the scope is too large — split into multiple independent RFCs, each with a focused scope.

## Workflow

### Phase 1: Requirements Clarification

Users rarely articulate complete requirements upfront. Iteratively clarify before designing.

**Process:**
1. Read the user's initial request carefully
2. Identify ambiguities, missing details, and implicit assumptions
3. Present 3–5 focused questions with selectable options where possible (faster feedback)
4. Repeat until requirements are clear and complete
5. Summarize the finalized requirements for user confirmation

**Guidelines:**
- Ask the most important questions first; avoid overwhelming with too many at once
- Cover: scope boundaries, affected modules, performance, backward compatibility
- Once confirmed, proceed to Phase 2 — do NOT persist requirements as a separate document (they get captured in the RFC)

### Phase 2: RFC Design (Subtask DAG + File Allocation)

The RFC is the core artifact. It captures design rationale, trade-offs, and the subtask DAG.

**Process:**
1. Ensure `docs/rfcs/` exists; if not, create it together with `docs/rfcs/README.md` (see `references/rfc-readme-template.md`).
2. **Determine the next RFC number** from the union of local RFC files and open PR files:
   - Scan local `docs/rfcs/NNNN-*.md`.
   - Scan open GitHub PR files: `gh pr list --state open --json number,files --limit 100` (or run `python scripts/check-rfc-number-conflicts.py`).
   - Do not reuse a number that appears in any open PR. If the open-PR check cannot be completed, stop and ask the user before creating RFC files.
   - In shared-repo work, push the RFC skeleton and open a draft PR early so the number is visible to other agents.
3. Create `docs/rfcs/NNNN-slug.md` using the template (see `references/rfc-template.md`). Status starts at `draft`.
4. Fill in all sections based on clarified requirements:
   - **Explore the codebase** thoroughly before writing the design — use subagents for parallel context gathering.
   - Write high-level architecture, key design decisions, and interface contracts.
   - Document alternatives considered and why they were rejected.
   - **Do NOT include implementation code** in the RFC — keep it at the architectural level; concrete code belongs in Phase 3.
5. **Decompose into subtask DAG** — fill in the 子任务分解 section:
   - Break the implementation into independently implementable and verifiable subtasks.
   - **Subtask count must not exceed 6.** If it does, the scope is too large — split into multiple RFCs.
   - For each subtask define: **scope**, **acceptance criteria**, and **file list (涉及文件)** — the exact files this subtask creates/modifies.
   - **File lists across subtasks must be disjoint** — this is what makes collaborative mode conflict-free. If two subtasks must touch the same file, either merge them or split that file's changes out into its own subtask.
   - Map dependencies between subtasks as a DAG (Mermaid). Subtasks with no mutual dependency can run in parallel.
6. **Confirm open questions with the user** before writing the `## 未解决的问题` section. For each candidate question, ask whether to keep it as an open question (defer to implementation) or discuss & resolve now. Only questions the user chooses to keep go into `## 未解决的问题`.
7. Update `docs/rfcs/README.md` with the new RFC entry.
8. Present the RFC (including subtask DAG + file lists) to the user for review.

**RFC quality bar:**
- Design section focuses on architecture, key decisions, and interface contracts — NOT implementation code.
- RFC answers "what" and "why", not "how to code it".
- Trade-offs section must include at least one alternative considered.
- Every subtask is independently implementable/verifiable, has a disjoint file list, and clear dependencies.
- Test plan covers unit tests and integration tests for the RFC scope.

**User review flow (uninterrupted):**
- Present the full RFC for review; let the human collect ALL feedback at once; apply all changes in one pass.
- Repeat until the user approves — then change status from `draft` to `accepted`.

### Phase 3: Implementation & Verification

Execute subtasks according to the DAG in the RFC.

**Before starting:**
1. Read the RFC's subtask DAG to identify executable subtasks (status = `pending`, all dependencies = `implemented`).
2. Present the list of executable subtasks to the user.
3. If multiple subtasks are independent, the user can open separate agent sessions (collaborative mode, same worktree) to work them in parallel — each session reads the RFC for full context and only touches its subtask's file list.

**Process per subtask:**
1. **Claim & update status** — set the subtask's status to `in-progress` in the RFC's 子任务列表 table (this corresponds to CLAUDE.md「代码修改中」). Set RFC-level status to `implementing` if not already.
2. **Plan** — design the detailed implementation for this subtask (concrete code structure, file changes). This detail lives in your working session, NOT in the RFC.
3. **Implement** — write code, touching ONLY the files allocated to this subtask. Reference the RFC ID in comments (see `references/code-comment-conventions.md`), e.g. `# RFC-0007: 实现消息转告队列`.
4. **Verify** — run the verification checklist (see `references/verification-checklist.md`): ruff check + ruff format --check, pytest with coverage, RFC ID comments present, rebase on latest main and re-run tests.
5. **Update RFC** — set the subtask status to `implemented`（CLAUDE.md「代码修改完毕」), optionally noting a ref (PR URL / commit). When all subtasks are done, advance RFC-level status `implementing` → `implemented`.
6. **AI Review** — provide a summary of changes and potential concerns for human review.
7. **Human Test Plan** — write step-by-step manual verification instructions.
8. **Collect feedback** — let the human review, gather ALL comments at once, fix in one pass.

**Parallel execution:**
- When a subtask completes, check the DAG for newly unblocked subtasks and tell the user which are now available.
- Each parallel session: read the RFC → pick an available subtask → set it `in-progress` → implement within its file list → set it `implemented`.

**Failure handling:**
- If tests fail: fix and re-verify, do not merge.
- If a subtask's plan or implementation is fundamentally flawed: document what went wrong, fully revert, update the subtask definition with lessons learned, and restart.

**RFC amendments during Phase 3:**
- Implementation sometimes reveals the design needs adjustment. Keep the RFC as the source of truth, not a stale snapshot.
- Minor adjustments (rename a field, tweak a path): update the RFC inline and note the change.
- Significant pivots (new component, changed architecture): pause, update the RFC's design section, get human approval before continuing.
- If scope grows beyond the RFC's boundaries, split into a new RFC rather than overloading the current one.

## Phase Gate Summary

```
[Requirements]   --human approves-->  [RFC Design + Subtask DAG + File Allocation]
[RFC + DAG]      --human approves-->  [Implementation per subtask]
[Implementation] --human verifies-->  [Merge to Main]
```

Never skip a phase gate. If blocked, ask the human rather than proceeding with assumptions.

## References

- `references/rfc-template.md` — RFC document template (Markdown, includes subtask DAG with file lists)
- `references/rfc-readme-template.md` — RFC index README template
- `references/verification-checklist.md` — Phase 3 implementation verification checklist
- `references/code-comment-conventions.md` — Code comment style guide with RFC ID referencing
