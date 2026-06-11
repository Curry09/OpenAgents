# Task Fields Reference

A Task is one `docs/specs/<NNNN-slug>/tasks/T*.yaml` file — the basic unit of the living
snapshot. Authored via `spec new` / `spec add-task`; refined via `spec amend`. The canonical
key order and block-scalar styling are produced by the `spec` CLI — **don't hand-format**.

## Identity & status (structured, machine-validated)

| Field | Type | Notes |
|-------|------|-------|
| `id` | `T<n>` | group-local id (`T3`); cross-group qualified id is `NNNN/T3` |
| `title` | string | short Task title |
| `status` | enum | `pending` \| `in-progress` \| `done` \| `abandoned` |
| `priority` | enum | `P0` \| `P1` \| `P2` \| `P3` |
| `tags` | list[str] | freeform labels |

`done` Tasks **stay in the snapshot** (they map to live code). `abandoned` Tasks live only
in `history/` (removed from the snapshot by `spec abandon`).

## Relations & parallelism

| Field | Type | Notes |
|-------|------|-------|
| `depends-on` | list[str] | blocking deps; cross-group uses `NNNN/Tn`. Enters the global DAG (no cycles). |
| `relates-to` | list[{ref,type}] | non-blocking links; `type` ∈ `extends` \| `supersedes` \| `note` |
| `parallel` | bool | hint that this Task can run alongside siblings |
| `files` | list[str] | exact files this Task owns. **Must be disjoint within a group** (collaborative-mode conflict-free guarantee). |

## Evolution / lineage (drives the auto-rendered evolution graph)

| Field | Type | Notes |
|-------|------|-------|
| `version` | int ≥ 1 | bumped by `spec amend` |
| `updated` | str | ISO date, set by the CLI |
| `change-reason` | str | why this version exists (set via `--reason`) |
| `supersedes` / `split-from` / `merged-from` / `derived-from` | lineage refs | how this Task descended from prior Tasks; `spec render` connects them into the evolution graph |

## Design prose (block scalars carrying Markdown; mermaid allowed in `design`)

`summary`, `motivation`, `scope`, `design`, `interface`, `tradeoffs`, `acceptance`,
`tests`, `references`, `open-questions`.

These map 1:1 from the old RFC sections (see RFC-0014 "RFC 元素 → Task 字段覆盖对照"). Keep
them architectural — **what & why, not implementation code**. After editing prose by hand,
run `spec validate` then `spec render`.

## Required vs optional

Only `id`, `title`, `status`, `priority` are required. Everything else is optional and
defaults empty — fill what the Task actually needs (a migrated legacy `done` Task may leave
most prose empty; a freshly designed Task should fill `scope`/`acceptance`/`design`/`tests`).
