# Spec-0081 E2E Result

Date: 2026-08-30

Result: PASS

The offline acceptance script `scripts/e2e-spec-0081-autonomous-failure-and-prompt-contract.sh`
completed with exit code 0. It made no model or forge network calls.

Verified outcomes:

- The active-source and CLI-help retirement scan found none of the retired label, control-exception,
  owner constant, or CLI flag spellings outside the dedicated migration surface.
- Ruff passed for the changed runtime, backend, Vigil, migration, desktop, and contract-test files.
- The focused Spec-0081 suite passed: 309 tests.
- The complete repository Python suite passed: 1,095 tests in 15.54 seconds. The run used localhost
  binding permission for the desktop daemon's three real HTTP socket cases.
- Ten production roles passed the all-role sentinel invariant: dynamic material was absent from task,
  present once in context, and present once in the final backend prompt.
- Claude Code argv/stdin seams proved the prompt is absent from argv and written to stdin exactly once.
- Failure convergence, fingerprint-idempotent stopping, changed-fact revival, live-holder safety,
  migration dry-run/apply idempotence, release gating, and desktop projection tests passed.
- `spec validate`, `spec render`, and `spec graph --check` passed. Existing cross-spec ownership and
  historical-reference warnings remained warnings and did not change acceptance.

The design evidence recorded in Spec-0081 remains the quantitative basis for the change: the issue
#17 prompt fell from roughly 145 KB with two Spec copies to 73,834 bytes with one copy; the local argv
boundary reproduced at 131,072 bytes; and the earlier duplicate retry path consumed about 4m52s and
1,170,901 avoidable tokens.
