# Architecture

English | [CREDIT Chinese](ARCHITECTURE.zh-CN.md)

OpenAgents separates delivery decisions, model execution, and forge operations. The [configuration guide](CONFIGURATION.md) describes user-facing choices; the generated [module map](specs/ARCHITECTURE.md) records imports and implementation ownership.

## Components

| Location | Responsibility |
| --- | --- |
| `openagents/cli.py` | Command parsing and project/configuration setup |
| `openagents/recipes/` | Persistent delivery, stage composition, and specification backfilling |
| `openagents/agents/` | Role prompts and structured output contracts |
| `openagents/runtime/` | Invocation, shared context, gates, state, telemetry, and user testing |
| `openagents/backends/` | Claude Code and NexAU execution adapters |
| `openagents/observations/` | Authorized evidence downloads and execution-condition validation |
| `openagents/utils/` | Git, GitHub/Gitea, workspaces, configuration, and release operations |
| `openagents/v02/` | Explicit finite-batch DAG scheduling and its production adapter |
| `openagents/spec/` | Spec authoring, validation, and generated views |
| `apps/desktop/` | Experimental desktop observation interface |

Role definitions vary by flow: standard delivery uses drafting, architecture, implementation, testing, and review roles; the explicit batch runner uses Spec Writer, Spec Curator, Developer, and Acceptance. They share execution and evidence contracts without requiring the same scheduling algorithm.

## Persistent reconciliation

Vigil schedules a **subject**, such as `issue:5` or `pr:12`. Each cycle reads current forge facts, classifies the subject, and either dispatches an action, waits, or records completion/failure. Persistent workers claim eligible subjects up to `--parallel K`; one slow subject does not impose a batch barrier on the others.

Typical actions are drafting and implementation, replying to a new human comment, resolving conflicts, fixing CI, collecting verification evidence, reviewing a candidate, and merging it. Decisions are derived from current state, so a restart can recover after a missed cycle. A passing check or review on an old PR head does not certify a newer head.

The default standard flow keeps model judgement in roles and mechanical facts in runtime gates. Head advancement, evidence provenance, and round limits remain deterministic checks. Skipping a configurable stage changes the delivery policy; it does not override remote branch protection.

## State and recovery

| Storage | Responsibility |
| --- | --- |
| Forge issues, PRs, comments, checks, and labels | Requirements, dependencies, delivered changes, and externally visible decisions |
| `.openagents/vigil-queue.db` | Subject queue, atomic claims, and unfinished-attempt accounting |
| `.openagents/claims/` | Process-liveness locks held through `flock` |
| `.openagents/runtime-state.json` and telemetry | Runtime records, progress, timings, and usage |

SQLite and process locks make this a **single-machine** scheduler. Do not share its queue database across machines through a network filesystem. Model workers may operate in separate repository workspaces; that does not make the scheduling database distributed.

Backend crashes, malformed output, time limits, and repeated lack of progress consume bounded retry budgets. On exhaustion, `automation-failed` records a machine failure tied to the relevant facts. A material change, such as a new PR head, corrected CI, or updated issue, allows reassessment. A live owner is not reclaimed merely because a lease appears old. Missing required execution evidence blocks dispatch and can be retried after the evidence is repaired.

## Verification boundaries

Implementation roles may edit the candidate. Testers and reviewers inspect the delivered commit and keep generated evidence outside its tracked source, using ignored or external directories. Missing evidence is not a passed check. A successful scripted contract test proves transport or control behavior; model understanding and real task completion require separate validation.

The evidence reader treats historical conversations as data, not role instructions. For negotiated execution contracts, original goals, input availability, budgets, and safe assessment summaries enter the shared role context. Private graders and answer material do not. See [integration](integrations/ahe-beta.md) and [verification](VERIFICATION.md).
