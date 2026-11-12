---
number: "0066"
title: "Phase timing: wall-clock per-phase latency—an append-only side-channel event stream + reports reconstructed across rounds to locate pipeline bottlenecks"
issue: 157
slug: phase-timing-wall-clock
summary: "Add wall-clock phase timing to the Vigil pipeline: on each tick, append a timestamped phase-signal event through a side channel at the producer's decision choke point _consider to .openagents/timing.jsonl (zero file-level coupling with runtime-state.json; write failures do not bring down the main flow). Take phase directly from the level-triggered _Verdict classification (solve/rebase/fix-ci/e2e/review-or-fix/merge + awaiting-ci/effect/mergeability/blockers + in-flight + terminal states), naturally subdividing the merge segment that the old stack would collapse into a single open state into CI-wait / review-wait / merge. Add an independent runtime.timing module providing an append writer + an aggregator that reconstructs durations across rounds (a per-issue timeline + per-phase p50/p90 across issues + the longest tail). The oa report subcommand reads jsonl, outputs a text report, and labels the lower bound on wall-clock precision = polling interval."
e2e:
  intent: "Demonstrate that “out-of-band wall-clock phase-timing instrumentation + duration reconstruction across iterations” works in an offline deterministic flow—repeatedly call run_vigil(once=True), advancing an issue cycle one tick at a time; on each tick, out-of-band instrumentation in _consider/_reconcile normalizes level-triggered _Verdict values into phase events and appends them to .openagents/timing.jsonl; across iterations, split “waiting for CI,” “waiting for review,” and “merging” into separate phases (instead of lumping them together into the old stack's single open phase); timing.record write failures are swallowed for fault tolerance, Vigil continues advancing normally, and _fingerprint remains unchanged before and after instrumentation (guardrail one does not undermine itself); oa report reads back the jsonl and aggregates per-phase durations for each issue + p50/p90 across issues + the longest tail, and indicates that the wall-clock precision floor = the polling interval."
  method: "Form: backend-only instrumentation + aggregation + CLI reporting, with no navigable product-facing frontend; the self-check tool list contains no Playwright /\nChrome DevTools MCP, so no browser e2e is specified; use offline deterministic testing instead (following the same approach as Spec-0060/0061/0064):\n1. Targeted pytest for the timing module (standard library only, no network/repository access): record appends valid JSON with five keys + UTC ISO8601;\n   inject exceptions from open/write → record silently swallows them without raising (fault tolerance); load_events skips corrupted lines; timelines reconstructs\n   per-phase durations across iterations (including summing separate segments when a phase recurs, and a duration of 0 for the final terminal event); phase_stats produces per-phase\n   p50/p90 + the longest tail + a field for the interval precision floor.\n2. Targeted pytest for vigil instrumentation (fake backend/github seam, no real LLM/network/repository access): after once runs one tick,\n   timing.jsonl is generated with dispatch/waiting/merging segments; _phase_of normalizes the four verdict values × facts state by state; when record raises an exception,\n   _consider/_reconcile still return normally (end-to-end fault tolerance); _fingerprint is equal before and after instrumentation (out-of-band instrumentation does not enter fp); in the merging segment,\n   awaiting-ci and review-or-fix are distinguishable.\n3. Targeted pytest for the CLI: given a prepared timing.jsonl, oa report outputs a single-subject timeline + p50/p90 across subjects +\n   the text “precision floor = interval”; friendly messages for empty/missing files, exit code 0.\n4. grep anchors (e2e script): runtime/timing.py exists and has zero recipes.vigil imports (no circular dependency); timing event\n   write sites occur only at the two locations _consider/_reconcile in vigil.py; record fault tolerance (an except fallback) is in place.\nScript: scripts/e2e-spec-0066-phase-timing-wall-clock.sh (ruff check + ruff format --check + targeted\npytest + grep anchors), collected by the PR e2e signpost.\n"
tasks:
  - id: T1
    title: "Independent runtime.timing module: append-only event writer (fault-tolerant) + aggregator that reconstructs durations across rounds"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/timing.py
      - tests/test_runtime_timing.py
    scope: "Add an independent runtime.timing module (standard-library dependencies only, zero file-level coupling with runtime-state.json / vigil-queue.db, principle 10). Three responsibilities: ① An append-only writer record(*, work_dir, subject, issue, pr, phase, now)—append one {subject, issue, pr, phase, at(ISO8601 UTC)} event to work_dir/.openagents/timing.jsonl (one JSON object per line); **fault tolerance**: catch all exceptions and never propagate them to the caller (a write failure only loses one timing event and does not bring down the main Vigil flow). ② A loader load_events(path)—read jsonl, tolerating errors line by line and skipping corrupt lines. ③ Aggregators (pure functions, suitable for hermetic tests): timelines(events) orders events by subject and merges consecutive events with the same phase into occupancy intervals (**each event occupies the wall-clock interval up to that subject's next event**; the last event is the endpoint, with duration 0), aggregating the total duration of each phase for each subject; phase_stats(events, interval) aggregates per-phase p50/p90 across subjects (quantiles of each subject's total dwell time in that phase) + the subject with the longest tail; the report structure includes interval to label the lower bound on wall-clock precision. No dependencies on any vigil/_Verdict types (phase is a plain string), avoiding circular imports with recipes.vigil."
    acceptance: "pytest tests/test_runtime_timing.py passes (without accessing a real network/repository): record appends one valid JSON line containing the five keys subject/issue/pr/phase/at, with at in UTC ISO8601; when monkeypatch injects exceptions from open/write, record **silently swallows them without raising** (fault-tolerance assertion); load_events skips corrupt lines and retains only valid events; timelines correctly reconstructs each phase's duration from a constructed sequence of events spanning rounds (including phase recurrence—review→fix-ci→review accumulates across two segments), and the final terminal event has duration 0; phase_stats produces per-phase p50/p90 and the subject with the longest tail for constructed samples spanning multiple subjects, and the report structure includes an interval field for the lower bound on precision. All functions are keyword-only, and private functions have no default values."
  - id: T2
    title: "Vigil side-channel instrumentation: append phase signals in the producer's _consider (waiting/terminal segments) + the worker's _reconcile (active-action segments)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - tests/test_recipe_vigil_timing.py
    scope: "Call timing.record through a side channel at two decision choke points in recipes.vigil (only append events; **do not change any return values/on-disk representations/control flow/fp**, in line with the existing rule of “enrichment only, no regressions”): ① Producer _consider (vigil.py:1472, where a verdict is computed for each subject on each tick)—normalize the verdict into a phase string and append an event, covering all QUIET reasons (awaiting-ci=CI-wait / awaiting-effect / awaiting-mergeability / awaiting-blockers), TERMINAL (subdivided into merged/closed/needs-human based on facts), the instant ACTIONABLE is enqueued (solve/reply/rebase/fix-ci/e2e/review-or-fix/merge), and IN_FLIGHT; ② Worker _reconcile (vigil.py:2351, at the branch table that advances execution)—append **active-segment** events according to the verdict.action actually executed in the current round, resolving the producer's generic in-flight view into actual actions such as solving/fixing-ci/reviewing. Add a pure helper _phase_of(verdict, facts) for normalization (inside vigil, reading _Verdict/_Facts, so normalization stays in vigil rather than timing, keeping timing free of vigil dependencies). Add a keyword parameter work_dir to _consider to obtain the work_dir output path (additive). Fault tolerance in record ensures that any timing failure does not affect Vigil's progress."
    acceptance: "pytest tests/test_recipe_vigil.py + tests/test_recipe_vigil_timing.py are all green (zero regressions in existing vigil tests—the record side channel does not change verdict/fp/state/GitHub calls): after one _producer_tick (once), timing.jsonl is generated and contains events for dispatch(solve)/waiting(awaiting-*)/merge segments; _phase_of is asserted to normalize each state correctly across the four verdict values × facts (TERMINAL subdivides into merged/closed/needs-human; QUIET takes reason; ACTIONABLE takes action; IN_FLIGHT→in-flight); assert that when record raises an exception (monkeypatch), _consider/_reconcile remain unaffected and return normally (end-to-end fault tolerance); assert that _fingerprint is unchanged before and after instrumentation (side-channel file writes do not enter fp or trigger guardrail one's self-destruction); the merge segment can distinguish awaiting-ci (CI-wait) from review-or-fix (review-wait), instead of blurring them into one segment."
  - id: T3
    title: "oa report CLI subcommand: read timing.jsonl and output a text report with per-issue timelines + p50/p90 across issues"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli_timing.py
    scope: "Add the oa report subcommand in cli.py (sub.add_parser + _cmd_report handler, thin routing, with business logic in the timing aggregators): read work_dir/.openagents/timing.jsonl and use timing.load_events + timelines + phase_stats to output a text report to stdout—per-issue/subject timelines (duration of each phase), per-phase p50/p90 across issues + the subject with the longest tail—and **explicitly label the lower bound on wall-clock precision = polling interval** (read from config, default 60s). For empty jsonl / a missing file, display a friendly message and exit with code 0. An HTML dashboard (reusing the string.Template static-rendering approach from utils/results.py) is listed under Future; this iteration outputs only text tables (Occam's razor: provide stdout first)."
    acceptance: "pytest tests/test_cli_timing.py passes: for a constructed timing.jsonl, oa report outputs a per-subject timeline containing each phase's duration and p50/p90 across subjects, and the output includes the wording “lower bound on precision = interval” and the actual interval value; when timing.jsonl is missing/empty, print a friendly message and return 0 (without a stack trace); the subcommand is registered with argparse (visible in --help), and the handler calls the aggregators using keyword-only arguments."
---

# 0066 · Phase Timing: Wall-Clock per-phase Latency—An Out-of-Band Append-Only Event Stream + Reports Reconstructed Across Ticks to Locate Pipeline Bottlenecks

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level overview in the 9-section rust-RFC format. -->

## Summary

Add **wall-clock phase timing** to the Vigil pipeline (discovery → triage → coding → delivery → CI → review → merge): the **calendar time** an issue/PR
spends in each phase, to locate bottlenecks—whether coding is slow, CI queues are long, or review is stalled.

The approach in one sentence: Vigil is **polling-based** (each tick advances each subject by one step, then
`time.sleep(interval)` before the next tick; nothing blocks waiting for CI/review), so wall-clock latency **must be reconstructed across ticks**. On each tick, append a timestamped “phase signal” event **out of band** at Vigil’s existing decision chokepoints,
`_consider` (producer) and `_reconcile` (worker), to a separate file,
`.openagents/timing.jsonl`; an aggregator recalculates each phase’s wall-clock duration across ticks from this event stream. **Resolution limit = polling interval**
(default 60s), stated explicitly in the report.

**Key insight (a departure from the original issue; see Motivation/Rationale)**: the issue was written for the old stack and raised the concern that “statuses
in the merge portion collapse into a single `open`, making CI-wait/review-wait impossible to measure.” But Spec-0064 has already consolidated `merge_pr.py`/`_advance_merge`
into the level-triggered `_classify` in `recipes/vigil.py`—on each tick, it produces a `_Verdict` with **four possible kinds +
a specific action/reason** (`awaiting-ci`/`review-or-fix`/`merge`/…) for each subject. **The merge portion is already subdivided**.
Therefore, this spec takes phase signals directly from `_Verdict`: out-of-band instrumentation at one point naturally distinguishes CI-wait / review-wait / merge, without
adding subdivisions to `set_run` (in the new stack, `set_run` is called in only two places and is a sparse signal; see Reference-level).

## Motivation

**Current state: there is no timing instrumentation anywhere in the repository.** Across the repository, `datetime` is used only for claim expiration/revival windows (the `_INFLIGHT_ALARM_SECONDS`
watchdog and the `closed_at` revival window) and the watchdog’s `age = now − last_progress_at`—**nothing measures “how long
a phase took.”** Optimization requires quantification first: we do not know where an issue spends its time between being claimed and being merged. Optimizing by guesswork has no evidential basis.

**Why reconstruction across ticks is necessary, and timing a wrapped blocking call will not work.** The pipeline uses polling-based reconciliation: on each tick, `run_vigil` reads
GitHub’s current state, advances one step, and calls `sleep(interval)`. **Nothing blocks waiting for CI or review** (this is a first architectural principle of the level-triggered
design; see the Kubernetes design principles cited in the `recipes/vigil.py` module header). Thus, “time spent in a phase” is not
the wall-clock duration of one function call, but **the calendar time covered by the consecutive ticks during which that subject is repeatedly classified into the same phase**. The approach: append a timestamped event
whenever a “phase signal” is produced; the aggregator recalculates phase durations from the event stream. Resolution limit = interval (the gap between adjacent
events is approximately one polling interval); the report labels this as the measurement limit rather than presenting the values as exact.

**The original issue’s instrumentation map is outdated (evidence-driven, principle 7).** The issue points to
`_advance_merge` in `openagents/recipes/merge_pr.py` (`merge_pr.py:176`) and `set_run` at `runtime/state.py:41`. In fact (in the current `git` state):
- `recipes/merge_pr.py` **no longer exists**—Spec-0064 consolidated the recipes layer from 6→3, moving the merge gates into
  `recipes/stages.py` (the `ci`/`e2e`/`merge` free functions), orchestrated by the `_classify` branch table in `recipes/vigil.py`.
- `RuntimeState.set_run` is at `state.py:67` (not line 41), and in the new stack **it is called only twice** (`vigil.py:2626` sets
  `pr-open`; `vigil.py:2772` sets `done`)—it is no longer a “state-transition chokepoint”; it is a sparse signal.
- The issue’s concern that “the merge portion collapses into a single `open`” **has already been addressed by `_Verdict`** in the new stack: on each tick, level-triggered classification
  assigns different values to waiting for CI (`awaiting-ci`), needing review (`review-or-fix`), and ready to merge (`merge`).

This spec therefore **implements the issue’s intent** (subdivide the merge portion and locate bottlenecks), but **uses the actual chokepoints in the new stack** (`_Verdict` instead of
`merge_pr`’s `reason` string, and `_consider` instead of `set_run`). This is alignment with the existing codebase, not defiance.

## Guide-level explanation

Think of Vigil as a state machine that gives every in-flight issue/PR a timestamped stamp on each tick saying “this is the phase you are in now.” Once enough stamps have accumulated,
they let us reconstruct that “this issue spent 40 minutes in the CI queue and was stuck in review for 2 hours.”

**Three actions:**

1. **Stamp (instrumentation).** On each tick, Vigil already computes a `_Verdict` in `_consider` (where the producer decides whether to act on each subject) and `_reconcile`
   (where a worker advances the subject it has claimed). We add just one out-of-band
   `timing.record(...)` line at each of these two points: normalize `_Verdict` into a phase string (`solving` / `awaiting-ci` /
   `review-or-fix` / `merged` …), then append a line containing it along with the subject / issue / pr / current time to
   `.openagents/timing.jsonl`. **Out of band = no changes to return values, no changes to control flow, no inclusion in the fingerprint, and swallowed write failures**
   (consistent with Vigil’s existing practice of “enrichment without regression”).

2. **Accumulate stamps (storage).** `.openagents/timing.jsonl` contains one JSON event per line and has **zero file-level coupling** to `runtime-state.json` and
   `vigil-queue.db` (principle 10: decoupling). Append-only and fault-tolerant—a failed timing write must never bring down Vigil’s
   main flow (Vigil’s first priority is to “stay alive for the next tick”).

   ```jsonl
   {"subject": "issue:145", "issue": 145, "pr": 154, "phase": "solving",      "at": "2026-07-09T12:00:00Z"}
   {"subject": "issue:145", "issue": 145, "pr": 154, "phase": "awaiting-ci",  "at": "2026-07-09T12:03:11Z"}
   {"subject": "issue:145", "issue": 145, "pr": 154, "phase": "review-or-fix","at": "2026-07-09T12:41:02Z"}
   {"subject": "issue:145", "issue": 145, "pr": 154, "phase": "merged",       "at": "2026-07-09T12:44:20Z"}
   ```

3. **Reconstruct (report).** `oa report` reads the jsonl, groups events by subject, merges consecutive events with the same phase into occupancy intervals, and calculates each phase’s
   duration; across issues, it aggregates p50/p90 for each phase plus the issue with the longest duration, identifying which phase has the long tail. A text table on stdout is sufficient (an HTML
   dashboard is listed under Future). The top of the report states: **Wall-clock resolution limit = polling interval (Ns for this run); each phase’s latency has an error at ±interval granularity.
   Do not treat these values as exact.**

**Where “pure waiting” occurs** is immediately apparent: a long `awaiting-ci` phase = CI queueing; a long `review-or-fix`/`awaiting-effect` phase =
stalled review progress; `awaiting-blockers` = waiting for upstream dependencies to merge. This is precisely the question the issue seeks to answer.

## Reference-level explanation

### Instrumentation chokepoint: level-triggered `_Verdict` (the actual new stack, replacing the issue’s `merge_pr.reason`)

`_classify` in `recipes/vigil.py` (`vigil.py:686`) is a pure-function branch table that produces a
`_Verdict{kind, reason?, action?}` for each subject on each tick:

- `kind` ∈ `IN_FLIGHT` / `TERMINAL` / `QUIET` / `ACTIONABLE`;
- `ACTIONABLE.action` ∈ `reply` / `solve` / `rebase` / `fix-ci` / `e2e` / `review-or-fix` / `merge`;
- `QUIET.reason` ∈ `awaiting-blockers` / `awaiting-mergeability` / `awaiting-ci` / `awaiting-effect`.

This table **inherently subdivides the merge portion**—`awaiting-ci` (CI queueing), `review-or-fix` (advancing review), and `merge` (the merge action)
are distinct values. This is why this spec **does not touch `set_run`** (it is sparse, and all the information it carries is already covered by `_Verdict`), instead attaching phase
signals directly to `_Verdict`.

**Two out-of-band instrumentation points (both in `vigil.py`, with T2 holding exclusive ownership of that file):**

1. **Producer `_consider` (`vigil.py:1472`)** — at the point where `verdict` is computed for each subject on each tick (`vigil.py:1489`).
   Records **waiting phases + terminal states + the instant of enqueueing**: for `QUIET`, use `reason` (including `awaiting-effect` after downgrading by guardrail one);
   for `TERMINAL`, use `facts` to distinguish `merged`/`closed`/`needs-human`; for `ACTIONABLE`, use `action`; for `IN_FLIGHT`,
   record `in-flight`. Add a keyword parameter `work_dir` to `_consider` for the on-disk path (additive).
2. **Worker `_reconcile` (`vigil.py:2351`)** — where the worker advances the branch table while holding the lock, record **active-phase** events according to the
   `verdict.action` actually executed in that tick, resolving the producer’s generic `in-flight` view into actual actions such as `solving`/`fixing-ci`/
   `reviewing` (the producer can see only that “someone is working”; only the worker knows which step is being performed).

The normalization logic `_phase_of(verdict, facts)` is a pure helper inside `vigil.py` (it reads the `_Verdict`/`_Facts` types, so it stays in
`vigil` rather than `timing`, preserving **zero dependency** from `timing` on `vigil` and preventing circular imports).

### Duration reconstruction across ticks (aggregation model)

`timing.timelines(events)`: group by subject and sort by `at`; **each event occupies the wall-clock interval “until that subject’s next event”**
(the last event is the endpoint, with an interval of 0). Sum consecutive intervals with the same phase to obtain that subject’s total duration for each phase. This
model naturally supports **phase recurrence** (`review-or-fix → fix-ci → review-or-fix` accumulates the two separate segments), and each interval is approximately one interval
(the source of the resolution limit).

`timing.phase_stats(events, interval)`: for each phase, collect “each subject’s total dwell time in that phase” and calculate p50/p90
(use p90 for tail latency; see the Google SRE citation in Prior art), and provide the subject with the longest duration in that phase; the report structure carries `interval`
to label the resolution limit.

### Storage and fault tolerance

`runtime/timing.py` (new module, **standard library only**):
- `record(*, work_dir, subject, issue, pr, phase, now)` → append one line to `work_dir/.openagents/timing.jsonl`;
  **catch all exceptions, never raise** (a failed write loses only one timing event).
- `load_events(*, path)` → read jsonl, tolerating errors line by line and skipping corrupt lines.
- `timelines` / `phase_stats` → pure aggregation functions, suitable for hermetic testing.

Event schema: `{subject, issue, pr, phase, at}` (`subject` = `"issue:5"`/`"pr:12"` is the unique key; `issue`/`pr`
may be null—a standalone PR has no associated issue; `at` = UTC ISO8601). **Do not change** the return values or
existing on-disk formats of `set_run`/`_classify`/`merge`; only append through a side channel (consistent with “enrichment only, no regressions”).

### DAG + file allocation

| Task | Files (mutually exclusive) | Dependencies | Purpose |
|---|---|---|---|
| **T1** | `openagents/runtime/timing.py`, `tests/test_runtime_timing.py` | — | Standalone module: fault-tolerant append writer + aggregator that reconstructs timelines across polling cycles |
| **T2** | `openagents/recipes/vigil.py`, `tests/test_recipe_vigil_timing.py` | T1 | Side-channel instrumentation at two points, `_consider`/`_reconcile`, + `_phase_of` normalization |
| **T3** | `openagents/cli.py`, `tests/test_cli_timing.py` | T1 | `oa report` subcommand: read jsonl and output a text report + interval annotation |

The `files` sets are pairwise disjoint (no sources of conflicts in collaborative mode, Principle 6). T2 and T3 both depend only on T1, with no dependency on each other → they can run in parallel.

### e2e script

`scripts/e2e-spec-0066-phase-timing-wall-clock.sh` (offline and deterministic: ruff + targeted pytest + grep anchors),
collected by the PR e2e signpost. This is purely backend work, with no browser e2e (see frontmatter `e2e.method`).

## Drawbacks

- **One additional side-channel write point and one additional file**. One extra append IO per subject per tick. Mitigation: writes are tiny (one JSON line),
  exceptions are swallowed for fault tolerance, and storage is decoupled from the main state file—the worst case is lost timing data, with no effect on Vigil correctness.
- **Precision is limited by the interval**. With 60s polling, sub-minute phases cannot be measured; this is an inherent lower bound of the polling architecture and can only be annotated, not eliminated
  (finer precision would require switching to blocking timing, which would rewrite the entire level-triggered architecture and is not worth the cost).
- **Human waiting after `needs-human` cannot be fully measured**. Once `needs-human` is applied, `_classify` determines `TERMINAL` and **polling stops**
  → no further timestamps are recorded while polling is stopped. After a person removes the label, a new event appears only on the next tick; “how long the person took” can only be approximated by the interval from the `needs-human`
  event to the next event (see Unresolved).
- **The event stream keeps growing**. With long-running operation, jsonl grows larger; rotation/compression is out of scope for this iteration (listed under Future).
- **The side-channel instrumentation still changes the `_consider` signature** (adding `work_dir`)—although additive, it touches the large shared file `vigil.py`, so
  existing vigil tests must have zero regressions (the T2 acceptance criteria already include this assertion).

## Rationale and alternatives

**Why instrument `_Verdict` instead of the issue-specified `set_run` + `merge_pr.reason`.** The issue’s instrumentation map was written for the old stack and is
outdated (`merge_pr.py` was deleted by Spec-0064, and `set_run` has only two call sites in the new stack). In the new stack, `_Verdict` is the **only**
point that emits a detailed phase for every subject on every tick; one side-channel hook covers the full spectrum of dispatch/RFC/CI-wait/review-wait/merge/terminal
—strictly better than adding finer distinctions to sparse `set_run` calls. This makes a “soft convention” concrete: instead of recording timestamps in two places and stitching them together, attach
to the single source of classification truth that already exists.

**Alternative A: instrument only `set_run` (following the issue literally).** Rejected—in the new stack, `set_run` emits only two signals, `pr-open`/`done`,
and cannot measure any waiting phase (CI/review/mergeability are all inside `_classify` and never pass through `set_run`), precisely reproducing the issue’s own
concern about “collapsing into a single phase.”

**Alternative B: wrap a call with a blocking timer (`perf_counter` around a call).** Rejected—the polling architecture has no blocking wait to wrap; this measures
the agent’s active compute time (`engine.run_agent`), which is **a different dimension** and explicitly a non-goal of this spec.

**Alternative C: write timing data into `runtime-state.json` (reuse the existing state file).** Rejected—this violates decoupling (Principle 10): timing is an
append-only event stream, while state is a key-value snapshot of the latest values; combining them either pollutes the state schema or makes the state file grow indefinitely. State writes also
follow “read the entire JSON → change one key → write the whole file back”; mixing in high-frequency events would increase exposure to lost updates from concurrent writes, which Spec-0065 already addressed. A separate jsonl file is inherently
append-oriented, fault-tolerant, and decoupled.

**Alternative D: reconstruct intervals using “first timestamp − last timestamp” (the issue’s literal wording).** Adopt the intent, but refine it to “each event occupies the interval until the next event; accumulate
by phase”—this is more robust: it correctly handles recurring phases (two review segments in review→fix→review) and attribution of dwell time, while each interval ≈ one polling interval
naturally establishes the precision limit.

## Prior art

- **rust-lang RFC format** (the source of this spec’s nine-section structure): <https://github.com/rust-lang/rfcs>.
- **Kubernetes level-triggered reconcile** (why wall-clock time must be reconstructed across polling cycles and cannot rely on edge-triggered/blocking timing):
  <https://github.com/kubernetes/design-proposals-archive/blob/main/architecture/principles.md>
  (the module header of Vigil’s `recipes/vigil.py` already establishes this basis; this spec follows that architecture).
- **Append-only logs / event logs as a stream of truth from which history can be reconstructed** (why jsonl events are used instead of snapshots): Jay Kreps,
  "The Log: What every software engineer should know about real-time data's unifying abstraction",
  <https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying-abstraction>.
- **Use percentiles (p50/p90/p99) rather than means for tail latency** (why the report includes p50/p90 + the longest tail): Google SRE Book,
  "Monitoring Distributed Systems", <https://sre.google/sre-book/monitoring-distributed-systems/>.
- **Existing results-layer rendering in the repository** (a reuse point for the future HTML dashboard): `openagents/utils/results.py` (`string.Template`
  + standard-library `webbrowser` for static rendering, zero frontend dependencies, RFC-0001/T6).

## Unresolved questions

- **How should human waiting during `needs-human` be counted**? Polling stops at `TERMINAL`, with no events while stopped, so it can only be approximated by the interval
  between the surrounding events. Whether a side channel is needed to “add a timestamp when a label changes” (reading the GitHub label timeline) is left for human confirmation—for this iteration, use only the approximation
  and mark that segment as a “lower bound” in the report.
- **Event-stream rotation policy**? With long-running operation, jsonl grows; when to rotate/archive/compress it is out of scope for this iteration (Future).
- **How should precision be annotated when the interval changes dynamically**? If the same issue spans different interval configurations, which should determine the precision limit—for this iteration, assume
  a constant interval and use the current config value.

## Future possibilities

- **HTML results dashboard**: reuse the `string.Template` approach from `utils/results.py` to render the timing report as a single-page HTML dashboard
  (Principle 8, results layer, Gantt-style phase bars + p50/p90 distribution charts); `oa report --html` writes it to disk and opens it locally.
- **Agent active compute time (a different dimension, a non-goal for this iteration)**: wrap `run_agent` in `runtime/engine.py` with
  `perf_counter` to measure the agent’s actual compute time and compare it with wall-clock latency (wall-clock − active = pure waiting). Open a separate issue.
- **Real-time monitoring / alerting**: feed timing events into a time-series database (Prometheus/alerting), explicitly a non-goal for this iteration.
- **Old-stack instrumentation**: the old `orchestrator.py`/`messages.py`/`state.py` stack has already been abandoned by the CLI and will not be instrumented (a non-goal for this iteration).
- **Event-stream rotation + aggregation across runs**: combine timing data from multiple Vigil runs into a trend dashboard.
