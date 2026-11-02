---
name: end-to-end-ui-screenshots
description: Verify user-facing behavior in a running application, using screenshots for visible UI results and runtime evidence for behavior that is not visible. Use when a task asks for end-to-end UI verification or evidence of an application behavior.
---

# Verify a running application

## Select evidence for the claim

| Claim | Evidence |
| --- | --- |
| A user-visible UI behavior works | Interact with the running application and capture the relevant UI state |
| A non-visible product behavior takes effect | Exercise the real application path and capture runtime records plus the triggering actions |
| An internal refactor preserves behavior | Proportionate automated tests and any integration checks required by the change |

Automated tests prevent regressions; application evidence establishes what happened in the exercised environment. Do not present a static page, mocked response, old screenshot, or test result as proof of a different live behavior.

## Procedure

1. Read or create the project's runbook using the [template](references/_runbook-template.md). Identify the candidate commit, environment, expected behavior, and available tools.
2. Start the actual application with isolated test data and explicit endpoints. Capture startup logs and wait for a defined readiness check with a finite timeout.
3. Drive the relevant user actions using an available browser or application automation tool. Wait for an observable condition rather than an arbitrary fixed sleep.
4. Capture the result: a screenshot for visible UI behavior, or runtime records with reproduction context for non-visible behavior. Check relevant errors and failed requests.
5. For the main regression, exercise a negative control where feasible to show that the check detects the original failure. Identify any fixture or instrumentation used; it must not fabricate the behavior under test.
6. Stop processes started for the test, restore temporary setup, and verify that the candidate's tracked source has not been altered by evidence generation.

Store evidence in an ignored or external directory during testing or review. Preserve the candidate identity and commands alongside it. Select and sanitize artifacts before publication; never include secrets or unrelated user data.

## Report the result

State which behavior was exercised, its observed result, the environment and candidate, and the evidence location. Link related automated regression tests where available. Distinguish a successful run from a blocked or incomplete check.

If the application cannot start or the required browser, service, or permission is unavailable, identify the missing prerequisite and mark that behavior unverified. Do not replace the missing run with another kind of check and claim equivalent coverage.
