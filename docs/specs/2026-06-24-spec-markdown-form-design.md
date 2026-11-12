# Converting Specs to Markdown Documents — Design

> Frozen forward-looking design document (dated design doc). Written on 2026-06-24, associated with issue #66.
> This file **is itself an example of requirement ②**: a dated Markdown design document, frozen once written, append-only, and preserved in git;
> together, these documents accumulate into “the history of the entire design.” Do not rewrite this file after the fact; create a new dated document for subsequent evolution.

## Background

Issue #66 originally proposed “code comments as the single source of truth + a sync engine that generates specs from them.” Design discussions concluded that this was **too heavyweight**
(violating CLAUDE.md principle 1, Occam's razor): it would require comment sentinel blocks, an extract/sync engine, dual current//history/
directories, and a full CI drift-check setup. This design supersedes #66, narrows the requirements to **two things**, and implements them
through “small changes to the existing spec system.”

Current state (the Spec-0014 system): each spec group is a directory,
`docs/specs/NNNN-slug/{metadata.yaml, tasks/T*.yaml, history/T*.yaml}`, driven by the `spec` CLI;
`render` generates `OVERVIEW.md`, and CI performs drift-checks.

## Goals (Two Things)

1. **The sole mapping to the code (current-state view)** — The code itself is the single source of truth. Use a **lightweight code graph**
   to generate a view of “what the architecture looks like now” from the code: files = nodes, imports = edges. Add **comment conventions**
   (file-level + module-level docstrings) so that “comments + the import graph” are sufficient to reconstruct the entire architecture.
2. **The history of the entire design** — Use **dated Markdown design documents** (such as this file) to carry the history,
   freeze them once written, and append them through git, following Superpowers' `docs/superpowers/specs/` convention.

## Design Decisions

### D1: Change a Spec Group from a “YAML Folder” to a “Single Markdown File”

The `docs/specs/NNNN-slug/` directory → a single `docs/specs/NNNN-slug.md` file:

- **YAML frontmatter** (read by machines, corresponding to KEP's `kep.yaml`): group metadata `number/title/issue/slug`
  + a `tasks` list containing each task's **structured fields** (`id/title/status/priority/depends-on/files`).
- **Markdown body** (read by humans/agents, corresponding to KEP's `README.md`): one `## <id> · <title>`
  section per task, containing prose subsections (`### Design` / `### Acceptance` / …).

“Frontmatter for machines, body for agents” is precisely the separation of **two types of readers** confirmed in the discussion.

### D2: Replace Only the Serialization Layer; Preserve the Data Model and Semantic Logic (Reduce Risk and Truly Make “Small Changes”)

Leave the `Task/Group/Metadata` data classes unchanged; the semantic checks in `validate` (acyclic DAG / no overlapping files within a group /
references exist) and `render` (board/relationship diagrams/individual feature sections) **consume model objects, with their logic unchanged**.
**Change only the load/dump operations in `model.py`** (YAML folder → single Markdown file), the schema-reading entry point in `validate`,
and the write paths in `mutate`. This converts the format to Markdown without starting over or breaking existing tests extensively.

### D3: Retire the Per-Task Version History Mechanism; Delegate History to git + Dated Documents

The old `history/T*.yaml` + `spec amend` mechanism (append the current version to history, version+1)
duplicates requirement ②. Retire it:

- Simplify `amend` to “edit the task in the md file in place”; **git history** carries version evolution.
- **Dated design documents** (requirement ②) carry the design-level explanation of “why it evolved this way.”
- During migration, preserve the existing `history/` (present only in 0014) as a **frozen appendix** in the group's md file under `## History (Migrated from the Old history/)`; nothing is lost.

This **reduces entities** (Occam): one fewer directory, one fewer set of amend/abandon-to-history logic, and one fewer set of schemas.

### D4: Requirement ① — `graph.py`, an Import Graph + Docstring Current-State View

Add `openagents/spec/graph.py`:

- Use the standard library's `ast` to scan `.py` files within the project and parse `import`/`from … import`, **connecting edges only between files within the project**
  (ignore standard-library/third-party imports). Files = nodes, imports = directed edges. **Do not introduce PageRank / tree-sitter / graph libraries /
  Neo4j** (reference to Aider's repo map confirmed that those serve to “fit within the prompt budget at runtime”; static documentation does not need them).
- **Comment conventions (hard requirements for agents)**: put a **file-level docstring** at the top of every `.py` file (what this file is responsible for);
  put a **module-level docstring** in each package's `__init__.py` (what this subsystem does as a whole).
- Generate `docs/specs/ARCHITECTURE.md`: subsystems (from package docstrings) → components (from file docstrings) →
  dependencies (import edges, Mermaid). The `graph` subcommand supports `--check` (for CI: fail if docstrings are missing or documentation has drifted).

### D5: Distinguishing Files in the Directory

Three types of files under `docs/specs/`: group files `NNNN-slug.md` (`^\d{4}-[a-z]`, with slugs starting with a letter, **excluding** the
`\d{4}-\d` pattern of dated documents), dated design documents `YYYY-MM-DD-*.md`, and generated files `OVERVIEW.md` / `ARCHITECTURE.md` plus the manually written
`README.md`. `load_all` recognizes only group files.

## Affected Modules

| Module | Change |
|---|---|
| `openagents/spec/model.py` | Change load/dump to a single Markdown file; retain data classes; remove the history dict |
| `openagents/spec/validate.py` | Read schema from frontmatter; keep semantic checks unchanged; remove history checks |
| `openagents/spec/mutate.py` | Have new/add-task/amend write to a single md file; simplify amend and remove history appending |
| `openagents/spec/render.py` | Continue consuming models unchanged; remove/downgrade per-task evolution diagrams |
| `openagents/spec/schema.py` | Remove version/change-reason/history-related elements from the task schema; retain structural fields |
| `openagents/spec/graph.py` | **New**: import graph + docstring validation + ARCHITECTURE.md |
| `openagents/spec/cli.py` | Add `spec graph [--check]` |
| `.github/workflows/*` | Connect drift-check to the new render + `spec graph --check` |
| `.claude/skills/spec-driven-development/**` | Update workflow documentation to the Markdown format |
| Migration script | Convert all 14 groups from YAML folders to md in a one-time migration; delete the old directories |

## Tradeoffs (Alternatives Considered)

- **Alternative A: Pure Markdown, no frontmatter (copy Superpowers exactly).** Rejected—this would lose machine-checkable
  DAG/files-disjoint constraints, leaving CI unable to perform drift-checks. Retain frontmatter to accommodate both types of readers.
- **Alternative B: Keep the YAML folders and add only graph.** Rejected—this does not satisfy the explicit request to “convert to Markdown documents.”
- **Alternative C: Code comments as the single source of truth + a sync engine (the original #66 proposal).** Rejected—too heavyweight; violates Occam's razor.

## Outside This PR's Scope (Follow-Up)

- **PR ②: Retire the `test` branch; merge everything into main + tag release versions instead** (the branching strategy separately proposed by the user). This PR temporarily uses
  `test` as its base to obtain a clean diff; merging into main belongs to PR ②.
- Function-level precision for the code graph (call graph): this iteration implements only a file-level import graph (sufficient to reconstruct the architecture, with the least effort).

## Acceptance Criteria

- `spec validate` / `spec render` / `spec graph --check` all pass; OVERVIEW.md / ARCHITECTURE.md
  are idempotent (no git diff after rendering).
- After migration, `load_all` reads all 14 groups correctly, and semantic validation passes.
- ruff check + format and pytest all pass.
