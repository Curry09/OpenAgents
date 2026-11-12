# Contributing

English | [CREDIT Chinese](CONTRIBUTING.zh-CN.md)

We welcome reproducible bug reports, documentation fixes, and focused implementation changes. Read the [README](README.md) and [Spec guide](docs/specs/README.md) first. Update the relevant design contract before adding a feature or changing behavior across modules. Do not manually edit the generated `docs/specs/OVERVIEW.md` or `docs/specs/ARCHITECTURE.md` files.

## Local checks

From the repository root:

```bash
uv sync --locked --extra dev
uv run --locked --extra dev pytest -q
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked spec validate
uv run --locked spec render
uv run --locked spec graph
```

The desktop app requires Node.js 22. Run `npm ci`, `npm run typecheck`, `npm test`, and `npm run build` in `apps/desktop/`. You can use `npm ci --ignore-scripts` for type checking, tests, and builds only; trying the GUI requires the Electron binary to be installed.

Commit lockfile updates together with dependency changes; routine CI uses `--locked`. When changing the delivery contract, run the cross-repository configuration check in AHE-Beta and record both repository commits. Ordinary PRs do not need model API keys. For live model canary runs, record costs, versions, and sanitized evidence separately.

See the [verification guide](docs/VERIFICATION.md) for optional NexAU checks, cross-repository probes, and the boundary between offline and live validation.

## Commits and review

Use Conventional Commits, for example `fix(cli): preserve resume identity`. If you specify a scope, it must be one of `backend`, `cli`, `ci`, `deps`, or `docs`. Describe the problem, resulting behavior, validation commands, and limitations in the PR. Keep experiment traces, credentials, and machine-specific configuration out of source changes. Reserve new spec numbers through the repository CLI and regenerate the views after editing specs. Do not rewrite existing experiment results as part of cleanup PRs.

By contributing, you confirm that you have the right to submit your contribution and agree to distribute it under the project's MIT license. Preserve the licenses and attribution of third-party material. Check [THIRD_PARTY.md](THIRD_PARTY.md) before contributing personas or benchmark content.

## Bilingual documentation

The root README, CONTRIBUTING, SECURITY, and THIRD_PARTY documents each have an English version (`.md`) and a Simplified Chinese version (`.zh-CN.md`). When editing either version, update the content, commands, and links in the other version as well, and retain the language switch at the top. User guides under `docs/` also provide both languages. Write active Specs, role prompts, and source comments in English. The [original Chinese Specs](docs/specs-zh-CN/README.md) are a historical snapshot.
