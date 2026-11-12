---
number: "0067"
title: "oa init automatically generates the default .openagents/openagents.yml (the packaged template serves as the single source of truth; vigil runtime flags can still override it)"
issue: 165
slug: init-scaffold-config
summary: "Include the repository-root openagents.yml.template in the package as package data and the single source of truth. Have oa init idempotently copy it to .openagents/openagents.yml (--force overwrites it), so first-time users immediately have a commented, directly editable declarative default; runtime --skip/--hold/--base continue to provide per-run overrides as before. Add an anti-drift test asserting that the packaged template is semantically equivalent to default_config()."
tasks:
  - id: T1
    title: "Move the template into the package + packaging + scaffold_default_config + anti-drift/idempotency tests"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/data/openagents.yml.template
      - openagents.yml.template
      - openagents/utils/agent_config.py
      - tests/test_agent_config.py
    scope: "Move the repository-root openagents.yml.template verbatim into openagents/data/ as the packaged single source of truth and delete the repository-root copy (hatchling includes all files under the package directory by default, with openagents/utils/templates/board.html as an existing example; no additional pyproject configuration is needed); add to agent_config a pure I/O function scaffold_default_config(*, path, force) -> bool (read the packaged resource using importlib.resources → write it to disk idempotently; if the target exists and force is false, skip it and return False; otherwise, create the directory, write the template, and return True; no side effects other than writing the target file)."
    acceptance: "pytest tests/test_agent_config.py passes: ① Anti-drift—the packaged template, parsed with load_agent_config, has all 7 stages set to agent / every role's backend set to claude_code / release=manual / interval=60 / base=main / labels=[openagents] (semantically equivalent to default_config()); ② scaffold idempotency—target does not exist → write it, return True, and content == template; target already exists and force=False → return False without changes; force=True → rewrite it and return True; ③ the scaffold output can be parsed by load_agent_config without errors. After uv build, the wheel contains openagents/data/openagents.yml.template."
  - id: T2
    title: "Wire up oa init: --force + idempotent generation + messages"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: "Add --force (store_true) to the init subcommand; after preflight passes, _cmd_init calls agent_config.scaffold_default_config(path=ctx.repo_root/'.openagents'/'openagents.yml', force=args.force) and, based on the return value, prints “Generated / Overwritten / Already exists; skipped (use --force to overwrite)”. Leave the runtime override chain _effective_config unchanged."
    acceptance: "pytest tests/test_cli.py passes: the first oa init in a temporary repo generates .openagents/openagents.yml and prints Generated; running it again is idempotent (does not overwrite and prints Already exists; skipped); oa init --force overwrites it and prints Overwritten; init still runs preflight (ensure_project) + envcheck. build_parser registers --force."
---

# 0067 · oa init automatically generates a default .openagents/openagents.yml (bundled template as the single source of truth; vigil runtime flags can still override it)

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

`.openagents/openagents.yml` is the declarative single source of truth for “which agents to use + who controls each gate” (Spec-0064). It **can be omitted entirely**—if the file does not exist, everything falls back to the built-in defaults (fully automatic / all agents / single repository / 60s interval), transparently to users who do not write YAML. The tradeoff is that **first-time users see no configuration file at all**: they do not know which knobs are available or that each gate can be configured with the three states `agent`/`human`/`skip`, and can only consult the source code or README.

This spec makes **`oa init` idempotently generate a default `.openagents/openagents.yml`**: its contents come from an **annotated template bundled in the package** (`openagents/data/openagents.yml.template`, moved from the repository root to become the single source of truth). If the file already exists, generation is skipped (preserving user changes); `oa init --force` forces a rewrite. The generated file contains only **declarative defaults**—runtime flags such as `oa vigil --skip ci` / `--hold merge` / `--base` still override it for a single invocation according to the existing `_effective_config` logic; **this spec does not change that override chain**.

The key constraint is **preventing drift**: the hardcoded defaults in the template (all stages agent / claude_code / manual / interval 60 / base main / labels [openagents]) must always match the built-in defaults in `agent_config` (`default_config()`). A test asserting that “the bundled template, when parsed by `load_agent_config`, is semantically equivalent to the built-in defaults” turns this from a matter of diligence into a hard CI gate.

## Motivation

### Current state: friendly to zero configuration, but no discoverability

Spec-0064 designed the three stage states so that “the entire YAML file can be omitted.” For **experienced users**, this is a victory for Occam’s razor—omitting it means fully automatic defaults. But for **new users**, it is a wall:

1. There is no actual `.openagents/openagents.yml` file in the project, so users do not know it exists or what they can configure;
2. Valid values differ by gate (`conflict`/`merge` cannot be skip; `rfc` allows only agent/skip). These constraints exist only in `_STAGE_VALID_OWNERS` in `agent_config.py` and in the README, with no guidance at the point of configuration;
3. For a common requirement such as enabling `review: human` (pausing before merge to wait for human review), users must first know that the `stages` section exists, know the `review` key, and know that `human` is a valid value—three layers of prerequisites.

The repository root already contains an `openagents.yml.template` with extensive Chinese comments explaining the three-state values key by key (commit 871ee6c), created specifically to lower this barrier. But it is **merely a document sitting in the repository root**:

- After installation as a uv tool (`uv tool install`), the repository root is not on a path accessible at runtime, so the code cannot access it;
- Even if it could, users would still have to manually run `cp openagents.yml.template .openagents/openagents.yml` for it to take effect—the “generate it by default” step is missing.

### Why `oa init`

`init` is the bootstrap command for “binding / initializing the current directory as an OpenAgents project” (RFC-0001 decision 10); semantically, it means “prepare this directory.” Currently, it only checks git/remote readiness and runs an environment health check, **without writing any project files**. Adding “generate declarative configuration defaults” is exactly within its remit—running `oa init` once gives users both “readiness validation” and “an annotated configuration they can edit directly.” A separate `init-config` subcommand would require users to know and type one more command, contrary to the goal of “generate it by default.”

## Guide-level explanation

New behavior added to a single `oa init` invocation:

```
$ oa init
✓ Project ready: /path/to/repo (remote: git@github.com:owner/repo.git)
✓ Generated default configuration .openagents/openagents.yml (editable; oa vigil --skip/--hold can override it for a single invocation)

▶ Environment health check
  ...

# Run again (file already exists)—idempotent, preserving your changes:
$ oa init
✓ Project ready: ...
· Configuration already exists; skipping generation of .openagents/openagents.yml (--force to overwrite)
  ...

# Reset using the latest template in the package:
$ oa init --force
✓ Overwrote configuration .openagents/openagents.yml
```

The generated file is a verbatim copy of the package’s `openagents/data/openagents.yml.template`—declarative defaults with Chinese comments explaining the three-state values key by key. Users edit it directly (for example, changing `review: agent` to `review: human`), and the next `oa vigil` invocation reads and applies it. If an edit breaks it, deleting the file restores the built-in defaults; to try a gate setting temporarily without changing the file on disk, use `oa vigil --skip`/`--hold` to override it for a single invocation.

**“Can be overridden by parameters” = runtime flags override YAML; this chain already exists** (`cli._effective_config`: `--hold`/`--skip` change the three-state settings, `--base`/`--interval`/`--label` change defaults, and the “zero gates are not allowed” constraint is enforced again after overrides). This spec only adds “generate the YAML by default” and leaves the override chain untouched.

The three-level hierarchy: **built-in defaults (`default_config()` in code) ← bundled template (the YAML on disk generated by init, equivalent to the built-in defaults) ← runtime flags (overrides for a single invocation)**. The three are semantically consistent, each successive level can override the previous one, and tests lock in the equivalence between the template and the built-in defaults.

## Reference-level explanation

### Data flow

```
openagents/data/openagents.yml.template   ← Single source of truth (moved from repository root, bundled in wheel)
        │  scaffold_default_config(path=…, force=…)  Read package resource → write to disk
        ▼
<repo_root>/.openagents/openagents.yml     ← Generated by oa init (idempotent; --force overwrites)
        │  load_agent_config(path=…)                  Existing loader, unchanged
        ▼
AgentConfig (resolved)  ← _effective_config applies runtime flags (existing, unchanged)
```

### Changes

**① Move the template into the package (single source of truth).** Repository-root `openagents.yml.template` → `openagents/data/openagents.yml.template` (move verbatim, with contents unchanged except for updating the header comments to point to the `oa init` generation flow). Delete the repository-root copy to prevent drift between two copies. **No changes to `pyproject.toml` are needed**—hatchling includes all files under the package directory in the wheel by default (the existing `openagents/utils/templates/board.html` is a precedent; after `uv build`, `unzip -l` can verify that the template is included in the package). Following Occam’s razor, do not add redundant packaging configuration.

**② `agent_config.scaffold_default_config` (new function, pure IO).** Signature: `scaffold_default_config(*, path: Path, force: bool) -> bool`:

- Read the bundled template through `importlib.resources.files("openagents") / "data" / "openagents.yml.template"` (accessible in both editable and wheel installations);
- If `path` already exists and `not force` → return `False` (idempotently skip without touching the user’s file);
- Otherwise, create the `.openagents/` directory with `mkdir(parents=True, exist_ok=True)`, write the template text, and return `True`;
- No side effects other than writing the target file (no git/gh/network reads; decoupling per principle 10).

**③ CLI wiring.** Add `--force` (`store_true`) to the `init` subcommand; after preflight passes, `_cmd_init` calls `scaffold_default_config(path=ctx.repo_root/".openagents"/"openagents.yml", force=args.force)` and prints “generated / overwritten / already exists, skipped” according to the return value.

**④ Drift-prevention test.** Assert that, after the bundled template is parsed by `load_agent_config`, all 7 stages are `agent`, all role backends are `claude_code`, release=manual, interval=60, base=main, and labels=[openagents]—that is, it is semantically equivalent to the built-in defaults from `default_config()`. If either side changes its defaults without synchronizing the other, CI fails immediately.

### DAG + file allocation

| Task | Dependencies | Assigned files (pairwise disjoint) |
|---|---|---|
| **T1** Move template into package + `scaffold_default_config` + drift-prevention/idempotency tests | — | `openagents/data/openagents.yml.template` (new, moved from repository root), `openagents.yml.template` (delete), `openagents/utils/agent_config.py`, `tests/test_agent_config.py` |
| **T2** Wire up `oa init` (`--force` + generation + messages) | T1 | `openagents/cli.py`, `tests/test_cli.py` |

T1’s `scaffold_default_config` is a dependency of T2, so T1 → T2 runs sequentially. The file lists are pairwise disjoint (T1 touches data/agent_config/test_agent_config; T2 touches cli/test_cli), so the collaboration model has no conflicts.

### e2e verification script

`scripts/e2e-spec-0067-init-scaffold-config.sh` (offline, CLI only): run `oa init` in a temporary git repository → assert that `.openagents/openagents.yml` is generated and can be parsed by `load_agent_config` → run it again and assert idempotency (contents unchanged, prints “already exists, skipped”) → change one line, then run `oa init --force` and assert that the file is reset to the template.

## Drawbacks

- **One more artifact to keep in sync with the built-in defaults.** The defaults in the template and `agent_config._DEFAULT_*` express the same facts in two places, inherently risking drift. Mitigation: the drift-prevention test in ④ makes this a hard CI gate; changing either side without synchronizing the other causes a failure. (We do not choose “render the template programmatically from constants” because that would lose the core value of the Chinese comments explaining each key; see Rationale.)
- **`init` has more substantial side effects.** It changes from “read-only validation” to “writes a file.” Mitigation: idempotent + writes only when the file does not exist, never overwriting user changes; rewriting requires `--force`, and the file is written under the gitignored `.openagents/` directory (without cluttering the user’s version-controlled repository).

## Rationale and alternatives

**Why copy a bundled template rather than generate YAML programmatically from constants?** The alternative is to `render` YAML from constants such as `agent_config._DEFAULT_STAGES`/`_ROLES`—with the benefit of zero drift from the built-in defaults. But this would lose the template’s **Chinese comments explaining the three-state values, constraints, and examples key by key**, which are precisely this feature’s core value in lowering the barrier for new users: programmatically rendering a pile of uncommented `key: value` pairs does nothing for discoverability. Choose “bundled annotated template + one drift-prevention test”: retain the comments while using a test to turn the risk of drift into a hard CI gate, getting both benefits.

**Why move the template into the package and delete the repository-root copy rather than force-include the repository-root file?** hatchling can force-include a repository-root file in the wheel, but in editable installations (`uv sync` / tests with `pythonpath=.`), `importlib.resources` resolves to the source tree’s `openagents/` package directory, which does not contain the repository-root file, causing behavior to diverge between the two installation modes. Moving it into `openagents/data/` makes the path consistent between the source tree and the wheel, giving both modes the same source. Deleting the repository-root copy preserves the single source of truth (two annotated templates will inevitably drift).

**Why put this in `oa init` rather than a separate subcommand?** See “Why `oa init`” in Motivation—`init` means “prepare this directory,” and “generate it by default” requires zero additional commands.


## Prior art

- **Spec-0064** established the declarative three-state configuration in `.openagents/openagents.yml` and the loader (`agent_config`) that allows the entire file to be omitted, falling back to built-in defaults; this spec completes its onboarding experience by materializing those optional defaults as a commented file on disk.
- **`git init` generates a `.git/config` skeleton**, **`npm init` generates `package.json`**, and **`eslint --init` generates configuration**—having init write an editable configuration with defaults is standard practice for scaffolding tools. This spec follows the same pattern: init writes a default configuration that is idempotent, editable, and commented.
- **Idempotent drift checks in CI** (the drift gate for `spec render` / `spec graph`; see `.github/workflows/ci.yml`) are an existing repository pattern: generated artifacts must not drift from their sources, or CI fails. The drift-prevention test in ④ follows the same approach.

## Unresolved questions

None (the three design choices—trigger = `oa init`, content source = packaged template, overwrite semantics = existing runtime flag—have all been confirmed with the requester).

## Future possibilities

- **Interactive selection in `oa init`**: Before generation, ask, “Should an agent or a human handle review?” and adjust the corresponding template line based on the answer (this spec only writes a static default template; interactive selection is future work).
- **`oa doctor` / `oa config validate`**: Run `load_agent_config` against an existing `.openagents/openagents.yml` and present errors in a user-friendly way, as a standalone diagnostic command.
- **Template variants for multiple backends**: Once `backends/` actually supports codex/nexau, `oa init --backend codex` generates the corresponding defaults for the `agents` section.
