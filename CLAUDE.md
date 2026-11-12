# Development guidance

OpenAgents is a spec-driven software delivery CLI. Read [README.md](README.md) for usage and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the current module layout. The implemented execution backends are Claude Code and NexAU.

## Design and implementation

- Keep modules small and responsibilities separate. Reuse existing runtime, forge, and backend contracts before adding abstractions.
- For substantive features and cross-module behavior changes, update the design contract before implementation. Follow [docs/specs/README.md](docs/specs/README.md) and the repository's [spec-driven workflow](.claude/skills/spec-driven-development/SKILL.md).
- Record implementation ownership through Spec task mappings and source references. Comment conventions are in [.claude/skills/spec-driven-development/references/code-comment-conventions.md](.claude/skills/spec-driven-development/references/code-comment-conventions.md).
- Preserve the original issue and acceptance conditions through delivery. Tests and reviews must inspect the delivered candidate; missing evidence does not establish success.
- Keep model judgement in roles and mechanical repository facts in deterministic code. Do not introduce a benchmark-specific rule into a shared runtime layer.
- Cite verifiable sources for external factual claims and distinguish them from implementation assumptions.

## Conventions

Use Python 3.12+ and Ruff with a 100-character line length. Use English for source comments, model instructions, runtime diagnostics, and active Specs. Do not use positional-only function parameters; private functions, except dunder methods, require explicit arguments without defaults.

Use Conventional Commits. Allowed scopes are `backend`, `cli`, `ci`, `deps`, and `docs`. Lefthook runs the configured lint and commit-message hooks. When a first push is requested, set the branch's upstream with `git push -u origin <branch>`.

## Verification and documentation

Follow [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/VERIFICATION.md](docs/VERIFICATION.md). Regenerate Spec views rather than editing generated files. Use proportionate automated checks, and collect real application evidence when claiming a user-visible behavior works. Keep test artifacts outside the candidate's tracked source while verifying it, and report unverified behavior explicitly.

Keep English and Chinese user guides aligned. Do not commit or publish changes unless the current task authorizes it.
