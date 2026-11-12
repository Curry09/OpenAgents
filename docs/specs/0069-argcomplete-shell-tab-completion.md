---
number: "0069"
title: "Integrate argcomplete Shell Tab completion into the openagents CLI (using the existing argparse parser as the single source of truth, with zero side effects)"
issue: 151
slug: argcomplete-shell-tab-completion
summary: "Insert argcomplete.autocomplete(parser) before parse_args in cli.main() so that openagents/oa generates zsh/bash Tab completion directly from the existing argparse parser, covering all subcommands and options without manually maintaining a second command list; argcomplete has zero side effects for non-completion invocations (it intervenes only when the _ARGCOMPLETE environment variable is present), preserving existing CLI behavior. Also add argcomplete as a runtime dependency and document the one-time user setup steps in the README."
e2e:
  intent: "Prove that the wiring in which argcomplete uses the existing argparse parser to generate Tab completion works in an offline, deterministic workflow with zero regressions—main() calls argcomplete.autocomplete(parser) before parse_args (intervening during the completion handshake, with zero side effects during normal invocation), and all subcommands and all vigil options are included in the parser (build_parser is the single source of truth for completion candidates); the CLI degrades gracefully without crashing when argcomplete is missing; argcomplete has been declared as a runtime dependency."
  method: "Form: CLI/backend wiring only, with no navigable product-facing frontend; the self-check tool list contains neither Playwright nor Chrome DevTools MCP, so no browser e2e is specified. Offline, deterministic testing is used instead (following the same approach as Spec-0064/0066/0067):\n1. Targeted CLI pytest tests (stub openagents.cli.argcomplete; hermetic, with no shell/network access): main([]) calls argcomplete.autocomplete exactly once before parse_args, with the ArgumentParser created by build_parser() as its argument, and main([]) still returns 2 (no command); stub openagents.cli.argcomplete as None → main([]) still returns 2 without raising an exception (graceful degradation); the complete set of subcommands registered by build_parser and all vigil options remain present (completion candidate coverage).\n2. grep anchors (e2e script): cli.py contains the argcomplete import with graceful degradation and the autocomplete(parser) call; dependencies in pyproject.toml includes argcomplete.\nScript: scripts/e2e-spec-0069-argcomplete-shell-tab-completion.sh (ruff check + ruff format --check + targeted pytest tests + grep anchors), collected by the PR e2e signpost.\n"
tasks:
  - id: T1
    title: "argcomplete wiring + dependency + documentation + tests"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - pyproject.toml
      - README.md
      - tests/test_cli.py
    scope: "Call argcomplete.autocomplete(parser) before parse_args in cli.main() (import it at module level with try/except ImportError for graceful degradation, setting it to None if unavailable); append argcomplete>=3.0 to pyproject.toml dependencies; add one-time Shell Tab completion setup steps (zsh/bash) to the README; add argcomplete wiring contract tests to tests/test_cli.py."
    acceptance: "uv run pytest tests/test_cli.py passes: main([]) calls argcomplete.autocomplete exactly once before parse_args, passing the ArgumentParser created by build_parser(), and main([]) returns 2; when openagents.cli.argcomplete is patched to None, main([]) still returns 2 without raising an exception (graceful degradation); build_parser registers all human-facing subcommands + all vigil options. ruff check/format are clean; pyproject.toml dependencies includes argcomplete."
---

# 0069 · Integrate argcomplete Shell Tab Completion into the openagents CLI (Read the Existing argparse Parser, Single Source of Truth, Zero Side Effects)

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level, nine-section rust-RFC overview. -->

## Summary

The `openagents` CLI (installed under the same entry-point name, also called `oa` in the README) is built entirely with
`argparse` (`build_parser`) in `openagents/cli.py`. argparse **provides no Shell Tab completion**—it only parses arguments
already entered at runtime; displaying candidates when Tab is pressed in zsh/bash is an entirely separate mechanism.
As a result, neither `openagents <Tab>` nor `openagents vigil --<Tab>` currently completes anything, and zsh can only fall
back to filename completion.

This spec integrates [`argcomplete`](https://github.com/kislyuk/argcomplete): insert
`argcomplete.autocomplete(parser)` **before** `parser.parse_args()` in `cli.main()`, so completion generates candidates
by **reading the existing argparse parser directly**, covering all subcommands
(init/vigil/backfill-rfc/issue/release/board/report + the hidden reply-comment) and all options
(such as `vigil --interval/--label/--base/--once/--parallel/--hold/--skip/--config`).
There is no need to write and maintain a separate `_openagents` zsh script or a second command list for completion
(consistent with Principle 1, Occam's razor: `build_parser` remains the single source of truth for the command list).
The accompanying changes add `argcomplete` as a runtime dependency and provide one-time user activation steps in the README.

Key property: `argcomplete.autocomplete()` **intervenes and calls `exit()` only during the shell completion handshake
(when the `_ARGCOMPLETE` environment variable is present)**; during normal calls such as `openagents vigil ...`,
it returns immediately with zero side effects, leaving existing CLI behavior unchanged down to the letter.

## Motivation

### Verified current state

- The `dependencies` in `pyproject.toml` contain only `ruamel.yaml` / `jsonschema`, **with no `argcomplete`**;
  `openagents/` also contains no completion wiring or accompanying `_openagents` script.
- `main()` in `openagents/cli.py` is `parser = build_parser(); args = parser.parse_args(argv)`, with no completion hook
  between the two.
- Consequently, neither `openagents <Tab>` (subcommand completion) nor `openagents vigil --<Tab>` (option completion)
  works. This applies uniformly to **all** subcommands and all options, not just `vigil`.

### Why do this

The CLI has 7 user-facing subcommands, each with a set of options (`vigil` alone has 8 flags). Without Tab completion,
users must either memorize command names or repeatedly invoke `--help`. This both slows onboarding (against the benchmark
of cursor/windsurf's smooth interaction) and is inconsistent with the fact that the command interface is already
declarative and self-describing—the parser already contains all the information; it simply is not connected to the shell.
The standard answer in the argparse ecosystem is argcomplete: it treats the argparse parser as the single source of truth
for completion, without forcing us to maintain a second command list that can drift.

## Guide-level explanation

One-time user activation (zsh, add to `~/.zshrc`):

```zsh
autoload -U bcompinit && compinit
eval "$(register-python-argcomplete openagents)"
```

bash (add to `~/.bashrc`):

```bash
eval "$(register-python-argcomplete openagents)"
```

After activation:

```
$ openagents <Tab>
backfill-rfc  board  init  issue  release  report  vigil
$ openagents vigil --<Tab>
--base  --config  --hold  --interval  --label  --once  --parallel  --skip
```

Users who do not enable completion will notice no difference: `argcomplete` intervenes only during the shell completion
handshake (when the `_ARGCOMPLETE` environment variable is present). During normal execution,
`argcomplete.autocomplete(parser)` returns immediately, leaving CLI behavior unchanged down to the letter.

## Reference-level explanation

### Wiring (the only change point in `cli.py`)

Use an **import with graceful degradation** at module scope—`argcomplete` is a declared dependency and will normally
be installed; however, if it is missing from the environment (an old snapshot / minimal installation), completion should
be silently unavailable rather than crash the entire CLI:

```python
try:
    import argcomplete
except ImportError:  # argcomplete is a declared dependency; if missing, silently disable completion without breaking the CLI
    argcomplete = None
```

Insert the hook in `main()` before `parse_args` (between `build_parser()` and `parse_args` is the only correct location
specified by the argcomplete documentation):

```python
def main(argv=None) -> int:
    parser = build_parser()
    if argcomplete is not None:
        argcomplete.autocomplete(parser)   # Intervene and exit only during the shell completion handshake; zero side effects in normal calls
    args = parser.parse_args(argv)
    ...
```

The semantics of `argcomplete.autocomplete()`: only when the shell completer has set the `_ARGCOMPLETE` environment
variable does it read the parser to generate candidates, print them, and call `os._exit()`; otherwise, it simply executes
`return None`. It is therefore a **no-op** for all normal calls, such as `main([])` / `main(["vigil", ...])`, leaving the
existing dispatch / exit-code / error-handling chain entirely unchanged.

### Dependencies

Append `argcomplete>=3.0` to `[project].dependencies` in `pyproject.toml` (3.x is the current mainline and provides
the `register-python-argcomplete` entry-point script).

### DAG + file allocation

A single Task (minimal changes, four non-overlapping files, no internal dependencies):

| Task | Title | files | depends-on |
| --- | --- | --- | --- |
| T1 | argcomplete wiring + dependency + documentation + tests | `openagents/cli.py`, `pyproject.toml`, `README.md`, `tests/test_cli.py` | — |

### e2e script

`scripts/e2e-spec-0069-argcomplete-shell-tab-completion.sh` (offline and deterministic: ruff check + ruff format --check
+ targeted pytest + grep anchors), collected by the PR e2e signpost. This is purely CLI/backend wiring, with no
product-facing frontend to navigate, so no browser e2e is specified (see frontmatter `e2e.method`).

## Drawbacks

- One additional runtime dependency, `argcomplete` (small, pure Python, no binary extensions, low risk).
- Completion requires users to run `eval "$(register-python-argcomplete openagents)"` in their shell as a one-time setup;
  without activation, there is no completion (this is inherent in argcomplete's model and cannot be eliminated by this wiring).

## Rationale and alternatives

- **Choose argcomplete (this proposal)**: reads the existing argparse parser directly; `build_parser` remains the single
  source of truth for the command list, with no second copy to maintain and just one line of wiring.
- **Alternative ①: handwrite an `_openagents` zsh completion script**—requires copying all subcommands/options into a
  zsh script; it drifts as soon as `build_parser` changes, violating Occam's razor (Principle 1) and the single source of
  truth; rejected.
- **Alternative ②: migrate to `click`/`typer` (with built-in completion)**—rewrites the entire CLI framework for
  completion, with a scope of change and regression risk far exceeding the benefits; rejected.
- **Alternative ③: do nothing**—retains the status quo, with poor interaction and a widening gap relative to benchmark
  products; rejected.

## Prior art

- [argcomplete](https://github.com/kislyuk/argcomplete) (official documentation: call
  `argcomplete.autocomplete(parser)` before `parse_args`, and register using `register-python-argcomplete <prog>`)
  is the de facto standard for completion in the argparse ecosystem, widely adopted by `pip`, `aws-cli` (in its early
  versions), and others.
- This repository already favors consolidating command-interface information into the parser as the single source of
  truth (Spec-0064 merged nine automation commands into `vigil`); argcomplete is a natural extension of this direction
  to shell interaction.

## Unresolved questions

- Should `oa init` automatically inject the activation line into the user's shell rc file? The preference is not to do
  this—modifying users' shell configuration has substantial side effects, and shells differ; leaving activation as an
  explicit one-time user action is more reliable (not included in this spec).

## Future possibilities

- Add **custom completers** for specific arguments (for example, complete existing repository labels for `--label`,
  or active items for PR/issue numbers); argcomplete supports attaching `.completer` to an individual `add_argument`.
- Integrate argcomplete into the `spec` console_script as well (this spec covers only the `openagents` entry point).
