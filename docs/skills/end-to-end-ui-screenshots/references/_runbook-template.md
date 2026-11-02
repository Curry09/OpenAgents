# Application verification runbook: <project>

Copy this template into the target project's documentation and replace the placeholders with its actual commands. The [verification method](../SKILL.md) describes how to choose evidence; this runbook records how to exercise this application.

## Candidate and scope

- Candidate commit or build: `<identity>`
- Behavior under test: `<user action and expected result>`
- Regression check: `<test or assertion that detects the failure>`
- External services and credentials required: `<names only; no secrets>`

## Environment

- Test data/profile directory: `<isolated location>`
- Backend endpoint: `<URL>`
- Frontend endpoint: `<URL>`
- Evidence directory outside tracked candidate source: `<location>`
- Application or dependency build command: `<command>`

## Start and check readiness

- Backend command and log destination: `<command>`
- Frontend command and log destination: `<command>`
- Readiness condition and timeout: `<check>`
- Expected effective configuration: `<non-secret settings>`

## Exercise and capture

1. Open `<entry URL>` with `<automation tool>`.
2. Perform `<specific actions>`.
3. Wait for `<observable condition>` within `<timeout>`.
4. Capture `<UI screenshot or runtime evidence>`.
5. Inspect `<relevant errors and failed requests>`.
6. Run `<negative control>` where feasible and record the expected failure.

## Clean up and report

Stop the processes created by this run and remove temporary fixtures. Check the tracked candidate diff. Record observed results, evidence paths, and any behavior that could not be verified. Review artifacts for sensitive content before sharing.
