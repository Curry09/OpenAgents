# Spec Fields Reference (rust-RFC form, issue #69)

A spec group = one markdown file `docs/specs/<NNNN-slug>.md`:
- **frontmatter** (machine-read): group metadata + a `tasks[]` work-breakdown (structured).
- **body** (human/agent-read): the group-level **rust-RFC 9-section overview** (the feature
  told once, self-contained).

Authored via `spec new` / `spec add-task` or by editing the markdown directly, then
`spec validate` + `spec render` + `spec graph`. Canonical key order is produced by the CLI —
**don't hand-format frontmatter**.

## Group-level overview (body — rust-RFC 9 sections)

The feature's whole story lives here, **before** any task breakdown. Single spec must be
self-contained: a reader understands it without opening any other spec. Reproduce, don't
cross-reference — say "复述胜过一个引用". `spec new` scaffolds all 9 headings.

| Section (`## heading`) | What goes in it |
|---|---|
| `Summary` | One paragraph: what this feature is. **(required)** |
| `Motivation` | Current state + why change. Reproduce background in place — **no load-bearing「见 Spec-NNNN」refs**. **(required)** |
| `Guide-level explanation` | Teach it as if it already exists; examples. |
| `Reference-level explanation` | Technical design **+ the DAG / file-allocation breakdown** (task table, mermaid), **+ the e2e script path** (`scripts/*.sh`, picked up by the PR signpost). **(required)** |
| `Drawbacks` | Why we should *not* do this. |
| `Rationale and alternatives` | Why this design; **at least one alternative considered**. **(required)** |
| `Prior art` | Precedents (other projects/langs/papers); "none" is fine. |
| `Unresolved questions` | Open questions to settle (replaces the old per-Task `open-questions`). |
| `Future possibilities` | Natural follow-on evolution. |

`spec validate` errors if any **required** section is empty, and warns on suspected bare
cross-spec refs (`Spec-NNNN [决策 N] / Spec-NNNN/Tn`) inside the overview.

## Task fields (frontmatter — the work-breakdown row)

A Task is no longer a prose carrier — it's a **work-breakdown + file-allocation row** under
the overview. The design narrative lives in the overview above; the Task only declares *who
owns what* and *how to verify it*.

### Identity & status (structured, machine-validated)

| Field | Type | Notes |
|-------|------|-------|
| `id` | `T<n>` | group-local id (`T3`); cross-group qualified id is `NNNN/T3` |
| `title` | string | short Task title |
| `status` | enum | `pending` \| `in-progress` \| `done` \| `abandoned` |
| `priority` | enum | `P0` \| `P1` \| `P2` \| `P3` |
| `tags` | list[str] | freeform labels |

`done` Tasks **stay in the snapshot** (they map to live code). `abandoned` Tasks are removed
from the snapshot by `spec abandon` (history lives in git).

### Relations & parallelism

| Field | Type | Notes |
|-------|------|-------|
| `depends-on` | list[str] | blocking deps; cross-group uses `NNNN/Tn`. Enters the global DAG (no cycles). |
| `relates-to` | list[{ref,type}] | non-blocking links; `type` ∈ `extends` \| `supersedes` \| `note` |
| `parallel` | bool | hint that this Task can run alongside siblings |
| `files` | list[str] | exact files this Task owns. **Required + disjoint within a group.** This is the single-writer ownership declaration (理念 6) and the structured source for issue #71's runtime owner checks. |

### Short prose (frontmatter, one line each)

| Field | Type | Notes |
|-------|------|-------|
| `scope` | str | what this Task changes (one line) |
| `acceptance` | str | a verifiable acceptance criterion. **Required.** |

## Required vs optional

Required per Task: `id`, `title`, `status`, `priority`, `files`, `acceptance`.
Required per group: metadata `summary` (one-line TL;DR) + the 4 required overview sections.
Everything else defaults empty — fill what the feature actually needs.
