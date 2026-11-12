# Verification

English | [CREDIT Chinese](VERIFICATION.zh-CN.md)

Run these checks from the OpenAgents source root. Use a fixed source checkout and the committed lockfile. Pre-command self-update is disabled here so the checked code remains the code being exercised.

## Offline checks

```bash
export OPENAGENTS_NO_SELF_UPDATE=1
uv sync --locked --extra dev
uv run --locked --extra dev ruff check .
uv run --locked --extra dev ruff format --check .
uv run --locked --extra dev pytest -q
uv run --locked --extra dev spec validate
uv run --locked --extra dev spec render
uv run --locked --extra dev spec graph
uv run --locked --extra dev spec graph --check
```

Regeneration should not change `docs/specs/OVERVIEW.md` or `docs/specs/ARCHITECTURE.md` unless the corresponding sources changed. CI also checks spec-number conflicts and commit messages.

For NexAU, install its extra and verify both the pinned dependency and the real client against a controlled local HTTP server:

```bash
uv sync --locked --extra dev --extra nexau
uv run --locked --extra dev --extra nexau python scripts/check_nexau_dependency.py --installed
uv run --locked --extra dev --extra nexau pytest -q \
  tests/test_backend_nexau.py tests/test_backend_nexau_http.py
```

These checks do not require model credentials. Local HTTP tests exercise SDK construction and request/response handling; they do not establish that a real model understands a delivery requirement.

## Evidence-reader checks

```bash
uv run --locked --extra dev python scripts/check_observation_reader.py
uv run --locked --extra dev python scripts/check_observation_reader.py \
  --execution-fixture tests/fixtures/execution_evidence_contract.json
```

The synthetic probes exercise real evidence preparation, gzip/ZIP decoding, scope and hash checks, read-only files, and execution-condition delivery to role contexts. They replace the remote forge with fixtures. A warning followed by degraded delivery is not a successful required-evidence check.

For a live **read-only** check, first publish a synthetic package in a dedicated test repository and export `GITEA_TOKEN`:

```bash
uv run --locked --extra dev python scripts/check_observation_reader.py --live \
  --base-url https://gitea.com --owner YOUR_USER --repo YOUR_PROBE_REPO \
  --expected-package /private/synthetic-package.json --sha256 ATTACHMENT_SHA256
```

The expected package contains the test issue, authorized sessions, and synthetic files. The probe reads that issue and attachment; it does not post comments or call a model. Run it in the actual deployment network and with the intended reader version.

## Cross-repository checks

In a compatible AHE-Beta checkout, run its checks against this OpenAgents checkout:

```bash
uv run --locked --extra dev python backend/scripts/check_openagents_contract.py \
  --openagents /path/to/OpenAgents
uv run --locked --extra dev python backend/scripts/check_observation_contract.py \
  --openagents /path/to/OpenAgents
```

These cover the controller's real configuration writer and evidence publisher against the supplied reader. Record both commits. An individual historical test may expect an older controller package path; use the current controller-side checks for the current pair rather than assuming that such a test passed because it was skipped.

## Desktop and packaging

In `apps/desktop/`, use Node.js 22 and run `npm ci --ignore-scripts`, `npm run typecheck`, `npm test`, and `npm run build`. To launch the GUI, install Electron normally with `npm ci`. A bundle build is not a GUI interaction test.

CI builds the Python wheel and installs it outside the source tree, checks both CLI help commands, and separately tests installation with the NexAU extra. This catches imports accidentally satisfied by the development checkout.

## Live delivery validation

Use a dedicated target repository and the selected deployment's real backend. Verify requirement intake, specification, implementation, review, merge, and restart behavior; include negative cases that must be rejected. Record the exact source/package versions, configuration, invocation limits, and sanitized receipts. UI behavior needs evidence from the running UI; optional methodology is provided in the [UI verification guide](skills/end-to-end-ui-screenshots/README.md).

Keep runtime evidence outside the candidate's tracked source while testing or reviewing it. Publish only selected, sanitized results. Clearly separate successful execution, a model's judgement, and an infrastructure failure. An unavailable model response is not PASS or REWORK.

Historical one-off reports are retained in Git history. For example, the [execution-contract canary record](https://github.com/Curry09/OpenAgents/blob/e5b66cef17452513373e5f1d4da192c824b288fb/docs/validation/execution-contract-preservation.md) documents a successful negative control and a positive control that never obtained a model verdict. Deterministic contract tests do not complete that missing semantic check.
