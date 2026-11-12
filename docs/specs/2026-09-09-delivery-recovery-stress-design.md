# Concurrent Fault-Injection Stress Testing for Delivery Recovery

Status: Code changes are complete. Repeated version changes and regular stress retests have all passed; not deployed. Historical failure evidence is retained below.
Supplement to Spec-0056 / Spec-0017 / Spec-0065.

## Validation Question

Can the version-consistency fix preserve correct merging and normal task progress when concurrency, retries, and remote changes occur simultaneously?
“Rejecting everything” does not count as success, and deliberately injected persistent failures do not count as erroneous blocking of ordinary tasks.

## Setup

- Each batch has a temporary bare remote, a shared checkout, and a separate worktree for each issue, sharing native Git metadata.
- Retain the real engine, Vigil detection/classification/production enqueueing/worker/claim/reconcile, SQLite, flock, RuntimeState,
  Git delivery gates, and checks before and after review. Replace only the model backend and external forge; inject faults at the backend or Git IO boundary.
- Fake forge merging does more than update status: it performs real Git merges in a serialized local integration workspace, merging into the same main,
  and checks before merging whether the SHA carried by the call still matches the remote. Verify the review SHA, candidate content, and final main files for each task.
- Compare 1/4/8/16 workers; shuffle tasks with fixed random seeds, and report the normal baseline and mixed faults separately. Keep the production retry limit.
- Write temporary data only to newly created directories; do not access credentials or external APIs, or modify running experiments. No real models are called, so elapsed time does not represent
  real model throughput; validate timeout recovery by injecting the same exception, without claiming to have retested the 1800-second process termination mechanism in this test.

## Scenarios and Criteria

Normal delivery already completed, not yet implemented, uncommitted, committed but not pushed, pushed but response lost, timeouts during development before/after commit respectively,
review dirties the candidate once, remote version changes during review, remote version changes after the merge check, one Git fetch failure, ordinary cache,
one unignored log, and normal REWORK. There are also two negative controls: persistent review contamination and persistent fetch failures.

Extended boundary: the remote is legitimately updated three consecutive times during review of the same task, then stops changing. Candidate changes are not equivalent to persistent model/
network failures; review is expected to continue once the candidate stabilizes, rather than freezing the task by misapplying the retry budget. Run and report this case separately; do not
classify it as a persistent-failure negative control to conceal erroneous blocking.

Requirements: Recoverable tasks must ultimately merge with correct content; persistent failures must fail within a bounded number of attempts, must not merge, and must not affect other tasks in the same batch; no duplicate claims,
no loss of existing implementations, and no merging a new version using approval of an old version. Record task states, role calls, claims/retries, P50/P95, remaining queue entries,
peak concurrency, and complete failure logs. Preserve the failure state and report anomalies; do not make tests pass by increasing retry limits or disabling gates.

## Reproduction and Results

The entry point is `scripts/stress_delivery_recovery.py`, and results are saved in newly created `delivery-stress-*` directories.
The first round validates the stress harness with small batches before increasing repetitions; production code is not automatically patched based on test results.

## Formal Regular Stress Results (2026-09-09)

```sh
.venv/bin/python scripts/stress_delivery_recovery.py --workers 1 4 8 16 --repeats 8 --baseline 32 --seed 59 --deadline 180
.venv/bin/python scripts/stress_delivery_recovery.py --workers 4 16 --repeats 8 --baseline 32 --seed 83 --deadline 180
```

Across 1008 tasks in total: all 912 normal or recoverable tasks merged and passed content verification; all 96 persistent-failure tasks
exited as failed after 3 claims and did not merge. Incorrect merges, duplicate claims, unexpected blocking, producer errors, and remaining queue entries were all 0.
Scenarios including a single timeout, one remote version change, only push remaining, cache, unignored logs, and rework required eventual completion, rather than merely testing rejection.

Results by worker configuration for the first group (seed=59):

| Worker configuration / actual peak | Normal baseline merged | Mixed scenarios merged | Expected persistent-failure stops | Baseline elapsed time | Mixed elapsed time |
| --- | --- | --- | --- | --- | --- |
| 1 / 1 | 32/32 | 120/120 | 16/16 | 6.82s | 47.78s |
| 4 / 4 | 32/32 | 120/120 | 16/16 | 2.44s | 16.34s |
| 8 / 8 | 32/32 | 120/120 | 16/16 | 2.44s | 15.00s |
| 16 / 16 | 32/32 | 120/120 | 16/16 | 2.38s | 14.36s |

Each normal baseline task called Tester/Reviewer/Merger once each, with no additional Implementer/Deliver calls.
Gains level off once concurrency reaches 4, due to serialized local Git merges, Python/Git processes, and production scanning costs; these figures cannot be used to
predict throughput for real models/network services. The second group and boundary retests ran concurrently on the same machine and are not used for precise performance comparisons with the first group.

Raw reports:

- `/tmp/delivery-stress-lbm7p4md/summary.json`: 672 tasks, seed=59.
- `/tmp/delivery-stress-13d6acmg/summary.json`: 336 tasks, seed=83.
- Each batch directory retains `result.json`, `scheduler.log`, evidence from each test, the bare remote, the original workspace, and runtime state.

## Failed Boundary Case: Legitimate Version Changes Consumed the Execution-Failure Budget

```sh
.venv/bin/python scripts/stress_delivery_recovery.py --workers 4 16 --repeats 4 --baseline 16 --scenarios clean remote-churn-3 --seed 61 --deadline 60
.venv/bin/python scripts/stress_delivery_recovery.py --workers 1 16 --repeats 16 --baseline 16 --scenarios clean remote-churn-3 --seed 83 --deadline 90
```

Across the two groups, totaling 144 tasks: all 104 normal controls merged; of the 40 tasks with three consecutive legitimate version changes, **40/40 were incorrectly suspended**,
all receiving `automation-failed` after claims `[1, 2, 3]`. There were no incorrect merges or duplicate claims; both commands exited with code 1.
The actual peak concurrency in the large-batch 16-worker boundary retest was 16. When small batches had few tasks, the actual peak was below the configured value, as accurately recorded in the reports.

The fault injection did not involve source corruption or persistent network failures: every update published a valid implementation retaining `value = 1`, replacing the valid
candidate once per update; after the third update, the remote remained stable, and checking the new version should have continued. This case is not NEGATIVE, and its failure is not presented as success.

Root-cause chain:

1. `vigil._verify_candidate` first calls `Workspace.assert_delivered`.
2. The remote advances during review while the local checkout remains at the old commit being reviewed, and `assert_delivered` raises `WorkspaceError`.
3. The subsequent `MergeNotReady` branch (candidate changed → normal reassessment) never gets a chance to execute.
4. `_run_claimed` accumulates retries as ordinary failures; on the third attempt, it writes the failure label instead of rereading the fourth, stable candidate.

Code locations: `openagents/recipes/vigil.py:3052`, `openagents/utils/workspace.py:136`,
`openagents/recipes/vigil.py:2167`. Log available for verification:
`/tmp/delivery-stress-ja1pjm6c/mixed-w4/scheduler.log:79`, followed by lines 87, 95, and 98 recording the second attempt, third attempt, and suspension.

Boundary reports:

- `/tmp/delivery-stress-ja1pjm6c/summary.json`: 8 target failures, 40 normal controls passed.
- `/tmp/delivery-stress-0ctcl838/summary.json`: 32 target failures, 64 normal controls passed.

Additional causal recheck (not counted among the 40 formal targets above):
`/tmp/delivery-stress-snmo74wv/summary.json`, with 1 target failing again and 1 normal control passing. After the terminal state,
the stress harness called the real `_refresh_failure_projection` to recheck the stable facts; the log recorded `terminal recheck issue 2: failed=True`,
confirming that this was not a transient condition that would automatically recover on the next tick.

The next fix should distinguish “candidate changed” from “execution failed”: the former invalidates the old decision and triggers a new review without consuming the ordinary failure budget;
uncommitted source, read failures, and similar cases must retain the existing checks. The fix must cover the time window in which another version change occurs between checks; it must not simply swallow all
WorkspaceError exceptions or increase the retry limit. This section provides diagnosis only; production code has not yet been modified in this round to fix this boundary issue.

## Acceptance Interpretation and Limitations

The newly added `tests/test_delivery_recovery_stress.py` covers small-batch concurrency and the stress harness's own evaluator: deliberately marking a dirty candidate PASS
is independently detected as a failure. The most recent ordinary test suite run reported 1306 passed; this **does not mean the repeated-version-change stress test passed**.
Failures from the full stress commands are retained above; no xfail is added, no gates are disabled, and no failed targets are removed from the statistics.

This test demonstrates reachability and the boundary of erroneous blocking in offline scheduling/Git; it does not establish actual model reasoning capability, real forge service availability, or
overall production incidence rates. All experiments use temporary isolated repositories; no fix has been committed/deployed, and no running experiments have been touched.

## Fix Design for Repeated Version Changes (Subsequent Development)

Extract the Git fact reads in the existing `assert_delivered` into `Workspace.delivery_heads`: check that the workspace is clean,
fetch successfully, successfully read nonempty local and remote SHAs, and return both without judging their intended use; check the workspace again after fetching/reading
to prevent uncommitted files created during the reads from going undetected. Refresh only the tracking ref; do not switch the workspace, commit, or push.

Development delivery still uses `assert_delivered` to require strict equality between local and remote. Review acceptance reuses the fact reads: when the local checkout remains at
the original candidate and the remote has legitimately advanced, or when local and remote have both moved to a new version, raise the existing `MergeNotReady`, invalidate the old decision,
and let the existing producer detect and review the candidate again; do not consume the execution-failure budget. New unpushed commits left by the reviewer, uncommitted files,
and Git/forge read failures still count as execution failures and must not masquerade as legitimate version changes. Do not add exception types, state fields, queues, or
retry attempts, and do not catch and swallow `WorkspaceError`.

Regression coverage must include version changes during fetch, another forge version change after Git reads, dirtying the workspace during reads, unpushed review commits,
read failures, and completion on the fourth review after three version changes. Retest the original 40 incorrectly suspended tasks with the original commands, seeds, and retry limit;
then rerun the original 1008 regular stress tasks to verify that normal progress and persistent-failure isolation have not regressed.

## Post-Fix Acceptance (2026-09-09)

The four formal stress commands above were rerun unchanged, with the same seeds, task counts, concurrency configurations, deadline, and production retry limit.
Only the fix to Git fact reads and acceptance classification was added; the stress evaluator also explicitly counts duplicate claims as failures, without relaxing the criteria.

| Scenario | Before fix | After fix |
| --- | --- | --- |
| Three consecutive legitimate version changes | 40/40 incorrectly suspended | 40/40 merged; all succeeded on the fourth review |
| Normal controls in boundary groups | 104/104 merged | 104/104 merged |
| Regular normal/recoverable tasks | 912/912 merged | 912/912 merged |
| Persistent Git failures/persistent contamination | 96/96 stopped within a bounded number of attempts, did not merge | 96/96 stopped within a bounded number of attempts, did not merge |

Claim attempts for version-change tasks changed from `[1, 2, 3]` to `[1, 1, 1, 1]`: each attempt reread the actual candidate,
and only the stable SHA actually reviewed on the fourth review was approved and merged into main; no old decision was applied to a new version. Persistent failures still
stopped after `[1, 2, 3]`. Across all 1152 stress tasks, incorrect merges, unexpected blocking, duplicate claims, producer errors,
and remaining queue entries were all 0. The regular clean scenarios totaled 240 tasks, each calling Tester/Reviewer/Merger only once, with no additional development/
delivery calls. Actual peak concurrency in the regular tests covered 1/4/8/16; peaks for small boundary batches were recorded as observed, without claiming that all reached 16.

Post-fix reports (old reports were not overwritten):

- `/tmp/delivery-stress-anmmashk/summary.json`: all 8 version-change targets and 40 normal controls completed.
- `/tmp/delivery-stress-d0hhl1uc/summary.json`: all 32 version-change targets and 64 normal controls completed.
- `/tmp/delivery-stress-0v0n4qia/summary.json`: all 672 regular tasks met expectations.
- `/tmp/delivery-stress-5wj0s9pt/summary.json`: all 336 regular tasks met expectations.

Unit/integration regression: the final `pytest -q` run reported **1322 passed, 28.07 seconds**; the dedicated script
`bash scripts/e2e-delivery-review-recovery.sh` reported **507 passed, 19.88 seconds**, now including the small-batch repeated-version-change test.
There were 35 dedicated real-Git cases, covering version changes during and after fetch, dirtying during reads, unpushed review commits, empty SHAs, and
Git/forge read exceptions. The three-version-change regression was first observed to fail on the old implementation and then passed after the fix, without xfail.
Ruff check/format for modified files, Spec validate / graph --check, and git diff --check passed; historical Spec warnings remain.

Costs and limitations: one local workspace check was added after reads to avoid missing dirtying during fetch; normal tasks require no additional model calls.
If the remote continuously produces genuinely new candidates, review must still be repeated, and completion cannot be guaranteed when the candidate never stabilizes; this success was not obtained by
retrying real errors indefinitely. Multiple stress batches and regression tests ran in parallel in this round, so their elapsed-time differences are not treated as strict performance comparisons.
The changes have not been committed, pushed, or deployed, and no running or archived user experiments have been resumed or rewritten.
