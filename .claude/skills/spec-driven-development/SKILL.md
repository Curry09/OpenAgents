---
name: spec-driven-development
description: >
  Spec-driven development for OpenAgents: requirements clarification → Spec design as a
  living snapshot (a docs/specs/ group of Task YAML files, each Task carrying an explicit
  file list) → implementation with verification. Use this skill whenever the user wants to
  plan, design, or architect a non-trivial feature — even without saying "spec". Triggers on:
  "spec", "design doc", "technical design", "plan a feature", "break this down",
  "architect this", or any task involving multiple components, trade-offs, or cross-module
  changes that benefits from design-before-code. Supersedes rfc-driven-development.
  Supports multi-agent parallelism via Task DAG + file allocation.
---

# Spec-Driven Development

> **格式更新（2026-06-24 spec-markdown-form，见 `docs/specs/2026-06-24-spec-markdown-form-design.md`）：**
> spec 组从「YAML 文件夹 `docs/specs/<NNNN-slug>/{metadata.yaml,tasks/,history/}`」改为
> **单个 markdown 文件 `docs/specs/<NNNN-slug>.md`**（YAML frontmatter 放结构化字段 + 正文放 prose）。
> 新增「对代码的唯一映射」：`spec graph` 由 import 图 + 文件/模块级 docstring 生成 `ARCHITECTURE.md`。
> 设计历史改用 **dated 设计文档** `docs/specs/YYYY-MM-DD-<topic>-design.md`（冻结、append）。
> `spec amend` 与 per-task `history/` 已退役（版本演化交给 git）。下文凡提「tasks/T*.yaml 文件夹 /
> metadata.yaml / amend」均按上述映射理解；改 Task 直接编辑组 `.md`。

> **格式更新（issue #69 rust-RFC 形态，见 `docs/specs/2026-06-25-spec-rfc-form-design.md`）：**
> spec 正文从「每个 Task 各写 prose」改为 **组级 rust-RFC 9 段总览**（Summary / Motivation /
> Guide-level / Reference-level / Drawbacks / Rationale and alternatives / Prior art /
> Unresolved questions / Future possibilities，参考 [rust-lang/rfcs](https://github.com/rust-lang/rfcs)）。
> **总览先行**：feature 全貌在这 9 段里自包含地讲一遍，**DAG + 文件分配收进 Reference-level**；
> Task 退化成 frontmatter 里的工作分解行（结构化字段 + `scope`/`acceptance`，不再挂重 prose）。
> 下文凡提「各 Task 的 `design`/`interface`/`tradeoffs`/`tests`/`open-questions` prose」均已上移到
> 组级总览;字段细节见 `references/task-fields.md`。

Structured workflow for OpenAgents: **Requirements -> Spec Design (组级 RFC 总览先行 → Task DAG + File Allocation) -> Implementation & Verification**.

This skill **supersedes `rfc-driven-development`**. The unit of design is a **living snapshot**: a `docs/specs/<NNNN-slug>.md` group file whose basic unit is a **Task** (stable id, self-contained, one-to-one with live code). You drive the `spec` CLI (`new` / `add-task` / `render` / `graph` / `validate` / `abandon`) or edit the group markdown directly, then `spec validate` + `spec render` + `spec graph`.

Each phase requires human approval before proceeding. Within each phase, work autonomously.

## Language Convention

This skill's instructions are in English for model comprehension. Spec prose fields
(summary/design/…) are written in Chinese (read by the team). Code comments may be English
or Chinese — clarity first (see `references/code-comment-conventions.md`).

## Core Principles

1. **Spec is a living snapshot, the single source of truth** — `docs/specs/` is always a snapshot of the repo. Every Task in the snapshot maps to currently-live code, so the snapshot never contains legacy. Done Tasks stay in the snapshot (`status: done`); only a refactored Task's *old version* or an *abandoned* Task leaves the snapshot into `history/`. The Task DAG lives in the spec so any agent session can read it.
2. **Source data vs generated view are separated** — `docs/specs/<group>/` holds only structured YAML source (`metadata.yaml`, `tasks/T*.yaml`, `history/T*.yaml`). The single human-readable view `docs/specs/OVERVIEW.md` is a pure derivative produced by `spec render` (committed for GitHub visibility; CI drift-checks it). Never hand-edit OVERVIEW.md.
3. **Drive the `spec` CLI, never hand-write the tree** — use `spec new` / `spec add-task` / `spec amend` / `spec abandon`. They keep canonical key order, append history, and auto-render. Hand-editing risks schema/drift failures.
4. **Spec id as code index** — new code references `# Spec-NNNN/T*` in comments so other agents can trace code to design. Existing `# RFC-NNNN` comments are grandfathered (spec group NNNN ≡ old RFC NNNN). See `references/code-comment-conventions.md`.
5. **Human-in-the-loop at phase gates** — humans approve phase transitions; agents execute within phases.
6. **Parallelism through DAG + file allocation** — each Task declares `depends-on` and the `files` it owns. In collaborative mode (one worktree) agents avoid conflicts by only touching files allocated to their Task.

## Work Modes

OpenAgents has two parallelism layers (CLAUDE.md 设计理念 5–6):

- **协同工作模式（collaborative, same worktree）** — multiple agents implement one spec group together; conflict-free because each Task owns a disjoint `files` set. Default within one group.
- **多 worktree 模式（across issues）** — different issues run in separate worktrees in parallel, each driving its own spec group(s).

Within a single group, always use collaborative mode and rely on the per-Task `files` list.

## Spec Scope Boundaries

### When to Create a Spec group

Create a group (`spec new`) for any of these:
- New module / service / major component
- Public interface or protocol changes (e.g. agent message protocol)
- Data model / persisted state changes
- Cross-module feature implementations
- Anything with design trade-offs worth recording

### When to Skip (Implement Directly)

Skip when ALL hold: no design decisions to document, only one module/file affected, only one Task.

### Merge into an Existing group

If a small feature is a natural extension of an existing group's scope, `spec add-task` it onto that group rather than creating a new one.

### When to Split

A group with more than 6 Tasks is too large — split into multiple focused groups.

## Disk Layout (reference)

```
docs/specs/
├── OVERVIEW.md            # ONLY human view (spec render output; never hand-edit)
├── README.md              # specs dir doc + numbering rules (hand-written, static)
└── <NNNN-slug>/
    ├── metadata.yaml      # group meta: title / issue / slug
    ├── tasks/T*.yaml      # current-version Task snapshot (one-to-one with live code)
    └── history/T*.yaml    # append-only old versions (only legacy lives here)
```

Task fields and meaning: see `references/task-fields.md`.

## Workflow

### Phase 1: Requirements Clarification

Same as before — iteratively clarify before designing.

1. Read the request carefully; identify ambiguities, missing details, implicit assumptions.
2. Present 3–5 focused questions with selectable options where possible.
3. Repeat until requirements are clear; summarize for confirmation.
4. Cover: scope boundaries, affected modules, performance, backward compatibility.
5. Do NOT persist requirements separately — they get absorbed into the spec's prose fields.

### Phase 2: Spec Design (组级 RFC 总览先行 → Task DAG + File Allocation)

The spec group is the core artifact. Author it via the CLI — never hand-write frontmatter.
**总览先行**：先把组级 rust-RFC 9 段总览写清楚（feature 全貌），**再**拆 Task；Task 是总览
之下的分解，不是总览的替代。

1. **Create the group:**
   ```
   spec new <slug> --issue <N> --title "<组标题>" --summary "<一句话 TL;DR>"
   ```
   The number is auto-assigned as local-max + 1. Cross-PR number conflicts are caught by CI (`check-spec-number-conflicts.py`); in shared-repo work, push the group skeleton and open a draft PR early so the number is visible to other agents. If you must pin a number, pass `--number NNNN`. `spec new` 已在正文里铺好 9 段 `## <heading>` 脚手架（含 `<!-- 待填 -->` 占位）。
2. **Explore the codebase** thoroughly before designing — use subagents for parallel context gathering.
3. **先写组级 RFC 总览（before any Task）** — 直接编辑组 `.md` 正文，填满 9 段（顺序见 `references/task-fields.md`）：
   - **Summary**（必填）/ **Motivation**（必填，现状+为什么，**背景就地复述**）/ Guide-level / **Reference-level**（必填，技术方案 + **DAG + 文件分配表** + e2e 脚本路径）/ Drawbacks / **Rationale and alternatives**（必填，≥1 备选）/ Prior art / Unresolved questions / Future possibilities。
   - **单 spec 自包含**：读完这 9 段即理解本 feature，**不能把必要信息留给「见 Spec-NNNN」式裸引用**；要提别的 spec 编号只能当线索，关键内容必须就地复述完整。
4. **再拆 Task DAG（总览之后）** and add each Task:
   ```
   spec add-task <NNNN> --id T1 --title "<标题>" --priority P1 \
     --files openagents/x.py,tests/test_x.py \
     --depends-on T0 \
     --scope "<这个 Task 改什么>" --acceptance "<可验证的验收标准>"
   ```
   - **Task count must not exceed 6.** If it does, split into multiple groups.
   - **`files` across Tasks must be disjoint** — 这是协同模式无冲突的根（单一 writer 所有权，理念 6），也是 issue #71 运行期 owner 检查的结构化源。两个 Task 必须碰同一文件就合并它们，或把该文件的改动独立成一个 Task。
   - `depends-on` declares the DAG (cross-group refs use qualified ids like `0012/T2`). Tasks with no mutual dependency run in parallel. New Tasks start `status: pending`.
   - Task 不再挂重 prose；它的设计依据在组级 Reference-level 里讲。每行必填 `files` + `acceptance`。
5. **Confirm open questions with the user** before writing the `Unresolved questions` section — only questions the user chooses to keep are recorded.
6. **Validate & render:**
   ```
   spec validate          # must be error-free（必填段空 / 缺 acceptance / files 重叠 = error）
   spec render            # regenerates OVERVIEW.md
   spec graph             # regenerates ARCHITECTURE.md
   ```
7. Present the group (9 段总览 + Task 表 + DAG，via the group `.md` / OVERVIEW.md) to the user for review. Collect ALL feedback at once; apply in one pass. Repeat until approved.

**Quality bar:**
- **总览先行**：每个组在拆 Task 前先有完整的 feature 级 9 段总览；读完总览即懂全貌。
- **单 spec 自包含**：禁止把理解本 spec 的必要信息留在别处（无 load-bearing 跨 spec 引用）；复述胜过一个引用。`spec validate` 对必填段空报 error、对疑似裸引用报 warning。
- **软约定硬化**：凡是想写进正文「调用方请务必…/别…/记得…」的软约定,先问能不能改成 frontmatter 字段 / `spec validate` 规则让它**根本无法违反**(`files` 同组互斥即范例——它把「别让两个 Task 抢写同一文件」从自觉变成 error；延伸见 issue #71)。
- 总览叙述聚焦架构、关键决策、接口契约——不是实现代码;`Rationale and alternatives` 含 ≥1 备选。
- Every Task is independently implementable/verifiable, has a disjoint required `files` list, clear `depends-on`, and a required `acceptance` criterion.

### Phase 3: Implementation & Verification

Execute Tasks according to the DAG.

**Before starting:** identify executable Tasks (`status: pending`, all `depends-on` are `done`). Present them. Independent Tasks can run in parallel sessions (collaborative mode), each reading the group for context and touching only its `files`.

**Per Task:**
1. **Claim** — mark in-progress:
   ```
   spec amend <NNNN> <Tn> --reason "claim: start implementing"
   ```
   then set `status: in-progress` in `tasks/Tn.yaml` and re-`spec validate`/`render`. (`amend` snapshots the prior version into history and bumps `version`.)
2. **Plan** — design the detailed implementation in your working session, NOT in the spec.
3. **Implement** — write code, touching ONLY this Task's `files`. Reference the spec id in comments: `# Spec-NNNN/Tn: …`.
4. **Verify** — `references/verification-checklist.md`: ruff check + ruff format --check, pytest, spec comment present, `spec validate` clean, OVERVIEW drift-free (`spec render` then no git diff), rebase on latest base and re-run tests.
5. **Complete** — set `status: done` (via `spec amend … --reason "done"` + edit) and re-validate/render. The Task **stays in the snapshot** as `done` (it maps to live code). Only use `spec abandon` if the Task is dropped entirely.
6. **AI Review + Human Test Plan** — summarize changes/concerns; write manual verification steps. Collect ALL feedback at once; fix in one pass.

**Evolution (the core differentiator):**
- Redefining a Task → `spec amend` (old version goes to `history/`, snapshot keeps only the current version). Set `change-reason` / lineage fields (`supersedes`/`split-from`/`merged-from`/`derived-from`) so `spec render` can draw the evolution graph.
- Dropping a Task → `spec abandon` (tombstoned into history, removed from snapshot).
- Never leave a stale old definition in the snapshot — that's the流水账 problem this model exists to kill.

**Failure handling:** tests fail → fix and re-verify, do not merge. Fundamentally flawed Task → document what went wrong, revert, `spec amend` the Task definition with lessons learned, restart.

## Phase Gate Summary

```
[Requirements]   --human approves-->  [Spec group + Task DAG + File Allocation]
[Spec + DAG]     --human approves-->  [Implementation per Task]
[Implementation] --human verifies-->  [Merge to base (test)]
```

Never skip a phase gate. If blocked, ask the human rather than proceeding with assumptions.

## References

- `references/task-fields.md` — Task YAML field reference (structured + prose fields, lineage)
- `references/verification-checklist.md` — Phase 3 implementation verification checklist
- `references/code-comment-conventions.md` — code comment style with `Spec-NNNN/T*` referencing
