# Design Document: Converting specs to a rust-RFC Format (Overview First + Self-Contained Individual Specs)

> Dated design document (forward-looking design history; frozen once written, append-only). Corresponds to issue #69.
> After implementation, a corresponding spec group will be created (this group will itself dogfood the new format).

## Background and Problems (issue #69)

Individual specs are currently “hard to understand on their own.” The root cause is **incomplete semantics**, in two respects:

1. **Individual specs are not self-contained**: The body contains many cross-spec references such as “see Spec-0012 Decision 7 / Decision 8 / Decision 2,” offloading key design rationale elsewhere. Readers (human or agent) given one spec must consult several others to piece together its full meaning.
2. **Tasks are broken down before there is a feature overview**: `spec new` is immediately followed by `spec add-task`, with only a one-line `summary` at the group level. Readers are presented with a Task table before they have developed an overall understanding.

There is also a **hidden code-level defect** (discovered during investigation): The parser in `openagents/spec/model.py` does not parse the manually written `## Overview (feature overview)` section in 0023 at all—it only recognizes `## T<n>` Task sections (`_TASK_HEADING_RE = ^##\s+(T...)`). Consequently, this overview **never enters the data model** and will be **discarded outright** the next time any `spec render` / tool rewrites the group file. Therefore, “supporting group-level overview fields in the data model” is mandatory, not optional.

## Decision: A spec = a rust-style RFC, with the Task DAG Incorporated into the Design Section

Following `0000-template.md` (the nine-section template) and `README.md` (process/lifecycle) in [rust-lang/rfcs](https://github.com/rust-lang/rfcs), change the **main body** of a spec from “a Task DAG skeleton + separate prose for each Task” to “**nine sections of feature-level RFC prose as the main body**, with Tasks reduced to a work breakdown + file allocation table in the design section.”

The key insight: **RFCs do not conflict with a DAG + file allocation**. rust RFCs omit DAGs because rust completely separates design (the RFC repository) from implementation (issues/PRs in the main repository); OpenAgents chooses to let both coexist—the nine RFC sections explain the feature as a whole, while the DAG goes into **Reference-level explanation**, preserving principle 6, “parallelism = DAG + file allocation,” unchanged.

### New spec File Structure

**Frontmatter (machine-readable, structured source data)**
- Group metadata: `number / title / issue / slug / summary(one-line TL;DR) / status`
- `tasks[]`: **Retained**, but limited to structured fields + two short, single-line prose fields:
  `id / title / status / priority / tags / depends-on / relates-to / parallel / files / scope(one sentence describing what changes) / acceptance(verifiable acceptance criteria)`
  This is the DAG + file allocation; `spec render` / `spec graph` / `spec validate` continue to consume it.

**Body (read by humans/agents, nine sections of group-level prose from rust)**

| Section (original rust name) | What to write |
|------|------|
| **Summary** | One paragraph explaining what this feature is |
| **Motivation** | The current situation + why change it; **restate the background fully in place**, without leaving necessary information behind a “see Spec-00XX” reference |
| **Guide-level explanation** | How to explain it to someone as though it already exists (primarily through examples) |
| **Reference-level explanation** | Technical design details + **the DAG + file allocation belong in this section** (Task breakdown table / mermaid dependency diagram) |
| **Drawbacks** | Why this should *not* be done |
| **Rationale and alternatives** | Why this approach is best; **at least one alternative** and the reason for rejecting it |
| **Prior art** | Relevant precedents (other projects/languages/papers); state explicitly if there are none |
| **Unresolved questions** | Questions still to be resolved (replaces the former Task-level `Open-Questions`) |
| **Future possibilities** | Natural subsequent evolution |

### Why This Eliminates “Overlap”

In the old model, each Task has its own `Design / Interface / Tradeoffs / Open-Questions`; adding nine sections at the group level would create semantic conflicts with the Task-level prose. In the new model, **the design narrative is told only once, at the feature level (nine sections)**, and Tasks are reduced to a work breakdown/file allocation table within Reference-level explanation. There is no overlap, and this naturally satisfies the two acceptance criteria in issue #69: overview first + self-contained individual specs.

### File Allocation = OpenAgents’ Version of “Unique Ownership” (Reserving an Extension Point for issue #71)

The “Task → `files`” allocation table in Reference-level explanation is essentially OpenAgents’ version of the **Rust ownership model**: Each Task is the **single writer** for the `files` assigned to it (exclusive `&mut` access), and mutually exclusive allocation brings “aliasing XOR mutability” into the collaboration model—this is precisely the foundation of principle 6 that allows multiple agents to work in parallel within the same group without conflicts.

[issue #71](https://github.com/Curry09/OpenAgents/issues/71) will advance this ownership layer from “**design-time declarations**” to “**runtime enforcement**” (lease / versioned shared state / capability). **This design reserves an extension point for it**, with one hard constraint:

> **`tasks[].files` must remain a structured, machine-readable source in frontmatter**, rather than existing only as a human-readable table in the Reference-level explanation body. This allows a future orchestrator/harness to perform runtime ownership checks based on `tasks[].files` (unauthorized writes to files outside its own `files` → reject), without reparsing prose.

This also implies an RFC writing rule (to be incorporated into the skill’s quality bar): **Whenever you want to put a soft convention such as “callers must…” into the body, first ask whether it can become a frontmatter field / `spec validate` rule that makes violation impossible**—overlapping `files` within a group already produces an error, which is an existing example of this rule.

## Data Model Changes (`openagents/spec/`)

1. **`model.py`**
   - Add nine group-level prose fields to `Group` (or a new `GroupProse`): `summary / motivation / guide_level / reference_level / drawbacks / rationale_alternatives / prior_art / unresolved_questions / future_possibilities`.
   - **Remove** the long-form prose fields from `Task` (`motivation / design / interface / tradeoffs / tests / references / open_questions`), retaining structured fields + adding/retaining two short, single-line fields, `scope / acceptance` (in frontmatter).
   - Change body parsing in `_parse_body` from “split Tasks by `## T<n>`” to “split the nine group-level sections by `## <rust section name>`”; `_render_body` renders the nine sections symmetrically.
   - Add `scope / acceptance` to `_TASK_FM_ORDER`.
2. **`schema.py` / `validate.py`**
   - Add quality-bar validation: ① The **required sections** among the nine (Summary / Motivation / Reference-level / Rationale and alternatives) must be nonempty; ② Motivation/the body **must not contain bare references such as “see Spec-NNNN” that carry necessary information** (numbers may be mentioned as pointers, but lint rules should prompt self-containment—as warnings or errors; see Open questions); ③ Every row in `tasks[]` must have `files` (mutually exclusive) + `acceptance`.
3. **`render.py`** (OVERVIEW.md): Change group cards to display the group-level Summary section + Task breakdown table (instead of the former per-Task prose).
4. **`cli.py`**: `spec new` generates a group file containing an empty nine-section template; `spec add-task` still adds rows to `tasks[]` (prose is no longer attached to Tasks).
5. **`graph.py`**: Unaffected (consumes the import graph + docstrings); only confirm that ARCHITECTURE rendering does not reference deleted fields.

## Scope of Changes (All in One PR)

- `openagents/spec/`: model / schema / validate / render / cli (+ corresponding unit tests using TDD).
- `.claude/skills/spec-driven-development/`: Change Phase 2 in SKILL.md to “first write the nine-section RFC overview → then use add-task to add DAG rows”; add “individual specs must be self-contained; cross-spec references must not carry necessary information” to the quality bar; update field tables in references/.
- `docs/specs/README.md`: Align with the rust RFCs README style (when a spec is needed / process / template guidance / lifecycle status).
- `openagents/orchestrator.py`: Change the `_DRAFT_RFC_TASK` / `_REFINE_RFC_TASK` prompts to “write the nine RFC sections, with the DAG in Reference-level explanation.”
- **22 existing specs**: Rewrite all of them into the new format—add the nine-section overview and restate in place any content in cross-spec references that is “necessary to understand this spec”; prioritize 0023 / 0012 and those containing “see Spec-00XX Decision.”
- **89 `# Spec-NNNN/T*` code comments**: Grandfather them in (spec numbers remain valid; `/T*` suffixes serve as historical pointers and do not require cleanup; new code uses `# Spec-NNNN`).

## Tradeoffs and Alternatives (Rationale and alternatives)

- **Alternative A: A single freeform `overview` field** (without requiring nine sections). Less work, but it does not meet the requirement to “strictly follow the rust template,” and makes it difficult to establish a stable, verifiable quality bar. **Rejected**: The user explicitly requires strict adherence to rust.
- **Alternative B: Remove Tasks and use a pure design document** (complete separation of design/implementation, as in rust). This would eliminate the within-group parallelism through file allocation in principle 6 and have a larger blast radius. **Rejected**: The user clarified that a DAG can coexist with an RFC; it simply needs to be incorporated into the design section.
- **Chosen: Nine RFC sections as the main body + retain the `tasks[]` DAG in frontmatter**. This provides both machine readability (graph/validate) and human readability (nine self-contained sections).

## Boundaries (What Is Out of Scope)

- Do not introduce rust’s FCP / sub-team / rfcbot review process (YAGNI; OpenAgents already covers this with PRs + the reviewer gate).
- Do not require cleanup of the 89 historical `/T*` comments (grandfathered in).
- Do not change orchestrator/vigil gate logic; only change the task-assignment prompt wording.
- ARCHITECTURE.md / graph mechanisms remain unchanged.
- **Do not implement the runtime ownership enforcement in issue #71** (lease/CAS/capability); this PR only ensures that `tasks[].files` remains a machine-parseable structured source, preserving an interface for #71.

## Unresolved questions

- Should “no bare cross-spec references” produce an **error (blocked by CI)** or a **warning (advisory)**? (Decided: Start with **warning**—to avoid immediately blocking backfilling existing specs; it can be raised to an error once everything is green.)
- Should `acceptance` still be required for every row in `tasks[]`? (Decided: **Required**, to preserve verifiability.)

## Future possibilities

- **Runtime ownership enforcement ([issue #71](https://github.com/Curry09/OpenAgents/issues/71))**: Move Reference-level `files` assignments from design-time declarations to runtime enforcement—a single writer for shared state + versioned snapshot reads + capability declarations, with unauthorized writes rejected at the orchestration layer. This design retains `tasks[].files` as a structured source to pave the way for this.

## References (reviewed word for word, Principle 7)

- Rust RFC template: `rust-lang/rfcs` `0000-template.md` (9 sections and their guidance text).
- Rust RFC process/lifecycle: `rust-lang/rfcs` `README.md` (When you need to follow this process / What the process is / The RFC life-cycle).
