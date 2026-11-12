---
number: "0010"
title: "gh transient-error retries + per-round fault tolerance in the Vigil loop"
issue: 0
slug: gh-transient-retry-and-vigil-round-guard
summary: "Make interactions with GitHub more resilient: retry gh commands with exponential backoff when transient errors occur, and wrap each round of the Vigil loop in try/except so that an error in one round does not bring down the entire loop."
tasks:
  - id: T1
    title: "Transient-error retries + exponential backoff in `_run_gh`"
    status: done
    priority: P1
    tags:
      - reliability
      - cli
      - resilience
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: "Add a retry loop inside `_run_gh`; add the pure function `_is_transient_gh_error` and module-level constants (`_GH_RETRY_MAX_ATTEMPTS`, `_GH_RETRY_BACKOFF_BASE`, `_GH_TRANSIENT_MARKERS`); catch and normalize `subprocess.TimeoutExpired` to `GithubError`. Keep the public signature/return type unchanged."
    acceptance: "First attempt fails with stderr containing `HTTP 504`/`Gateway Timeout`, etc., and the second attempt succeeds → eventual success, with `subprocess.run` called 2 times and `time.sleep` called 1 time; persistent transient failures → raise `GithubError` after `_GH_RETRY_MAX_ATTEMPTS` retries; `subprocess.TimeoutExpired` → treat as transient and retry, then raise `GithubError` (not TimeoutExpired) when retries are exhausted; a non-transient nonzero return code (such as `not found`) → do not retry, raise `GithubError` immediately, and call `subprocess.run` only 1 time; return codes permitted by `allow_returncodes` (such as pending=8) → do not trigger retries and retain current behavior; monkeypatch `time.sleep` so there is no actual waiting; all existing cases in `tests/test_github.py` must still pass."
  - id: T2
    title: "Per-round try/except fallback in `vigil.run`"
    status: done
    priority: P1
    tags:
      - reliability
      - cli
      - resilience
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/vigil.py
      - tests/test_vigil.py
    scope: "Extract the body of the `run` loop into `_run_one_round(labels, base)`; in long-running mode, wrap it in try/except, log any per-round `Exception`, and `continue`; in `once` mode, call it directly and let exceptions propagate; `KeyboardInterrupt` must still follow the existing clean-exit path."
    acceptance: "In long-running mode (`once=False`), if `discover_and_dispatch`/`poll` raises `GithubError`/a generic `Exception` in the first round → log it, do not propagate it, and proceed to the next round; with `once=True`, if the single round raises an exception → let the exception propagate as before (do not swallow it), so cron/CI receives a nonzero exit status; `KeyboardInterrupt` → still print “✓ Vigil has stopped” and return cleanly, without being inadvertently caught by the per-round fallback; normal-path behavior (without exceptions) must remain identical to current behavior, word for word; all existing cases in `tests/test_vigil.py` must still pass."
---

# 0010 · Retry transient gh errors + per-round fault tolerance for the Vigil loop

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Add resilience to two key paths through which OpenAgents interacts with GitHub: (1) when the low-level `_run_gh` function (which wraps subprocess calls to the `gh` CLI) encounters **transient errors** (such as `HTTP 504`, `Gateway Timeout`, network instability, or timeouts), it **automatically retries** with exponential backoff instead of raising on the first error; (2) wrap **each round** of the Vigil loop, `vigil.run`, in try/except so that an error during discovery/polling in a single round is logged and execution continues to the next round, preventing an occasional failure from bringing down the long-running process. Neither change alters external signatures or normal-path behavior; both add fault tolerance only to error paths.

## Motivation

OpenAgents' automated agent workflow relies heavily on `gh` commands: claiming issues, opening PRs, reading comments, and checking CI status all go through `_run_gh`. In practice, however, the GitHub API and `gh` CLI experience **transient** failures—`HTTP 5xx`, `Gateway Timeout`, connection resets, and command timeouts—and **a single retry often succeeds**. Currently, `_run_gh` normalizes every nonzero exit (except codes permitted by `allow_returncodes`) into a `GithubError` and raises it immediately, turning transient instability that could resolve on its own into a hard failure that bubbles up the call chain and often terminates an entire round of automated processing.

The Vigil loop, `vigil.run`, is a long-running process: it periodically performs `discover_and_dispatch` (discover and dispatch issues) + `poll` (poll PR comments/status) + `sleep`. Currently, if any step in the loop body raises an exception (even if just one issue in one round triggers the transient gh error described above), the exception escapes the entire `while` loop, and **the entire Vigil process crashes and exits**—until someone manually restarts it. For a process intended to “make continuous progress unattended,” this “one failure stops everything” behavior is unacceptable.

The two problems share the same root cause (transient failures are amplified into fatal failures), but occur at different levels: T1 **handles transient gh errors locally** at the lowest level; T2 **adds a safety net** around the Vigil loop at the outermost level, so that even an exception that slips through costs only one round, not the entire process. Together, these two layers provide defense in depth: “recover automatically wherever possible + remain nonfatal even when recovery fails.”

## Guide-level explanation

For users, the only behavioral change is “greater resilience when something goes wrong”; the normal path is completely unaffected:

- **More robust gh commands**: Previously, a `gh` call that encountered a GitHub 504 would immediately report an error and stop; now it waits briefly (exponential backoff: wait base before the 1st retry, base×2 before the 2nd retry…) and then retries automatically, up to `_GH_RETRY_MAX_ATTEMPTS` times. Only **persistent** failures or **non-transient** errors (such as `not found` or permission denied) actually raise `GithubError`. The pure function `_is_transient_gh_error` determines whether an error is transient based on marker strings in stderr (`_GH_TRANSIENT_MARKERS`), making it easy to test and extend.
- **A more resilient Vigil**: In long-running mode (`once=False`), if discovery/polling fails in a round, Vigil **logs the exception** and then proceeds to the next round as usual, instead of crashing the entire process. One-shot mode (`once=True`, for cron/CI) retains the semantics of propagating exceptions upward so that the outer layer can use a nonzero exit code to trigger alerts. `Ctrl-C` (`KeyboardInterrupt`) still follows the existing clean shutdown path, printing “✓ Vigil stopped” before exiting, and is not accidentally swallowed by the per-round exception handler.

## Reference-level explanation

The changes are divided into 2 Tasks (`files` are mutually exclusive, with a single writer per Task):

1. **T1 Transient-error retries + exponential backoff in `_run_gh`** (`openagents/github.py` / `tests/test_github.py`)—
   - Wrap the single `subprocess.run` call inside `_run_gh` in a retry loop;
   - Add the pure function `_is_transient_gh_error(stderr) -> bool`, matching against `_GH_TRANSIENT_MARKERS` (a collection of marker strings such as `HTTP 504` and `Gateway Timeout`);
   - Add module-level constants `_GH_RETRY_MAX_ATTEMPTS` (maximum number of attempts) and `_GH_RETRY_BACKOFF_BASE` (backoff base, with the nth backoff = base × 2^(n-1));
   - Catch `subprocess.TimeoutExpired` and treat it as transient (retry); once attempts are exhausted, normalize it into `GithubError` (**do not** expose `TimeoutExpired` to callers);
   - **Keep the external signature and return type unchanged**—exit codes permitted by `allow_returncodes` do not enter the retry branch, and their behavior remains exactly as it is today, ensuring backward compatibility.
2. **T2 Per-round try/except protection in `vigil.run`** (`openagents/vigil.py` / `tests/test_vigil.py`)—
   - Extract the loop body of `run` into an internal function `_run_one_round(labels, base)` (one round = discovery and dispatch + polling);
   - In long-running mode (`once=False`), wrap the call to `_run_one_round` in `try/except Exception`: when a general `Exception` is caught (including a `GithubError` raised after T1's recovery attempts fail), **log it + `continue`** to the next round;
   - In one-shot mode (`once=True`), **call directly**, without wrapping the call in try, so exceptions propagate naturally;
   - `KeyboardInterrupt` is not caught by `except Exception` (`KeyboardInterrupt` is not a subclass of `Exception`) and still follows the existing clean exit path.

**Dependencies**: T1 and T2 **do not depend on each other** (`depends-on: []`). They belong to the two decoupled modules github / vigil, their `files` do not overlap at all, and they can be implemented entirely in parallel. Dependency DAG: no edges (two independent nodes, T1 and T2).

**End-to-end validation**: All changes in this group enhance fault tolerance at the unit level, so validation primarily relies on unit test coverage for the two modules—`pytest tests/test_github.py tests/test_vigil.py` (`time.sleep` is monkeypatched in tests, with no actual waiting). This group does not add any `scripts/*.sh` e2e scripts.

## Drawbacks

- Retries **increase the worst-case duration of a single gh call**: with persistent transient failures, all `_GH_RETRY_MAX_ATTEMPTS` backoffs must complete before an error is finally reported, making it slower than “raise on the first error.” Keep this bounded by using a small backoff base and a low attempt limit.
- Vigil's per-round exception handler “swallows” exceptions and only logs them, which may cause **a repeatedly failing round** to be retried silently without anyone noticing immediately—this relies on people/alerting systems consuming the logs to compensate.

## Rationale and alternatives

- **Why add retries at the `_run_gh` layer**: It is the single convergence point for all gh calls, so a change in one place benefits the entire call chain (DRY), and this is where the information needed to distinguish transient from non-transient errors (stderr, exit codes, timeouts) is most complete.
- **Why identify transient errors using stderr marker strings instead of exit codes**: Exit codes from transient failures in `gh`/the underlying HTTP layer do not reliably distinguish those failures; markers such as `HTTP 5xx`/`Gateway Timeout` in stderr text are more reliable. Extracting this into the pure function `_is_transient_gh_error` + the constant collection `_GH_TRANSIENT_MARKERS` makes hermetic testing and future additions to the markers easier.
- **Why Vigil's exception handler uses only `except Exception`, not `except BaseException`**: `KeyboardInterrupt`/`SystemExit` must be allowed through; otherwise, `Ctrl-C` would be accidentally swallowed and Vigil could not be stopped.
- **Why `once=True` has no exception protection**: One-shot mode is intended for cron/CI and needs **nonzero exit codes** to trigger alerts; swallowing exceptions there as well would conceal failures.
- **Alternative: implement retries at every call site**. Rejected—duplicative and easy to miss, violating Occam's razor; centralizing them at the single `_run_gh` entry point is simplest.
- **Alternative: one large try/except around the entire Vigil loop**. Rejected—such coarse granularity would also swallow “errors that should be fatal”; only per-round protection achieves “lose one round, not the process.”

## Prior art

Retries with exponential backoff are an industry-standard fault-tolerance technique for interacting with remote/network services (commonly built into HTTP clients and cloud SDKs). For long-running workers, “per-round exception protection, with no single failure being fatal” is also a common robustness pattern in daemons/event loops. This feature adopts the minimal form of these patterns, without introducing heavier mechanisms such as jitter or circuit breakers.

## Unresolved questions

None. The transient marker collection, backoff parameters, and exception-handling boundaries for the `once` and long-running modes have all been settled within this group.

## Future possibilities

- Add random jitter to backoff to mitigate the thundering herd effect when multiple agents retry simultaneously.
- Make `_GH_RETRY_MAX_ATTEMPTS`/`_GH_RETRY_BACKOFF_BASE` configurable.
- Trigger alerts/circuit breaking when cumulative per-round Vigil failures reach a threshold (currently, failures are only logged).
