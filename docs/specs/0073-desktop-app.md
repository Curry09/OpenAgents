---
number: "0073"
title: "openagents desktop app: parallel board + large streaming view + Tab navigation for items awaiting review"
issue: 170
slug: desktop-app
summary: "An Electron desktop frontend presents the parallel results of vigil --parallel N: N small board panes (results/status); click to open a large view showing the live streaming agent session; Tab jumps to the next pane awaiting review in priority order. Read-only presentation, with two backend additions: per-subject stream routing + a local daemon interface"
tasks:
  - id: T1
    title: "Backend: route agent output by subject (stream tee)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/streams.py
      - openagents/backends/claude_code.py
      - openagents/recipes/vigil.py
      - tests/test_streams.py
    scope: "Add streams.py: a thread-local subject sink registry + a fixed-length ring buffer per subject; replace print in claude_code with streams.emit (continue writing to stdout as before + append to the buffer for the subject bound to the current thread); after a vigil worker claims a subject, bind before entering _reconcile, and unbind on completion/exception"
    acceptance: "Unit tests: two threads each bind a subject and emit concurrently; each ring buffer contains only its own lines, with no cross-contamination; claude_code emit writes to the current thread's sink; emit from an unbound thread only writes to stdout, preserving existing behavior; update existing claude_code/vigil test doubles and ensure all tests pass"
  - id: T2
    title: "Backend: local daemon interface (HTTP+SSE)"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/desktop/__init__.py
      - openagents/desktop/daemon.py
      - openagents/cli.py
      - tests/test_desktop_daemon.py
    scope: "Add desktop/daemon.py: stdlib http.server listening only on 127.0.0.1; GET /board reads work_queue + a GitHub snapshot + each subject's category of items awaiting review and returns JSON; GET /stream/<subject> uses SSE to replay buffered output first, then continuously push the T1 ring buffer; add a desktop subcommand to cli to start the daemon (with optional --port/--open)"
    acceptance: "With the service running, GET /board returns JSON containing subjects/status/pr/categories of items awaiting review; GET /stream/<subject> pushes that subject's ring buffer lines one by one via SSE; return explicit error JSON if the port is occupied or the subject does not exist; test_desktop_daemon covers both endpoints + error paths"
  - id: T3
    title: "Frontend: Electron shell + client + App foundation"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - apps/desktop/package.json
      - apps/desktop/tsconfig.json
      - apps/desktop/electron.vite.config.ts
      - apps/desktop/src/main/index.ts
      - apps/desktop/src/preload/index.ts
      - apps/desktop/src/renderer/index.html
      - apps/desktop/src/renderer/src/main.tsx
      - apps/desktop/src/renderer/src/App.tsx
      - apps/desktop/src/renderer/src/daemon-client.ts
      - apps/desktop/src/renderer/src/types.ts
    scope: "Electron main process/preload/renderer entry point; HTTP+SSE client for the daemon; shared TS types mirroring the daemon JSON; App holds /board polling data + the selected subject + the list of items awaiting review and distributes them through context, using React.lazy to dynamically mount the three extension points Board/Detail/Nav (no static dependencies on features, to avoid cycles)"
    acceptance: "electron-vite dev opens a window; the client can fetch /board and subscribe to /stream/<subject>; App renders the Board empty-state placeholder; no static circular dependencies between lazy slots and feature tasks; tsc passes"
  - id: T4
    title: "Frontend: small board panes (board)"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - apps/desktop/src/renderer/src/board/Board.tsx
      - apps/desktop/src/renderer/src/board/Card.tsx
      - apps/desktop/src/renderer/src/board/useBoard.ts
      - apps/desktop/src/renderer/src/board/Board.test.tsx
    scope: "A grid of N small panes + result cards (phase/PR/evidence timestamp/comment count/needs-human badge), consuming board data from context; clicking a card emits an onOpen(subject) event; use board.html as the starting point for fields/colors"
    acceptance: "vitest: given mock board data, render N cards with correct statuses/badges/PR links; clicking a card triggers onOpen(subject); rendering the empty state produces no errors"
  - id: T5
    title: "Frontend: large streaming view + quick switching"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - apps/desktop/src/renderer/src/detail/DetailOverlay.tsx
      - apps/desktop/src/renderer/src/detail/StreamView.tsx
      - apps/desktop/src/renderer/src/detail/useStream.ts
      - apps/desktop/src/renderer/src/detail/DetailOverlay.test.tsx
    scope: "Fullscreen large view: the upper half subscribes to /stream/<subject> via SSE and renders the agent session stream in real time; the lower half contains result anchors (PR/diff links/phase timeline); the 'Next ▶' button switches to the next subject and resubscribes to the stream; Esc/close returns to the board"
    acceptance: "vitest: mock SSE events render one by one in StreamView; the 'Next' button switches subjects and resubscribes to the stream; closing triggers onClose; subscriptions are properly cleaned up on switching/unmounting"
  - id: T6
    title: "Frontend: Tab navigation for items awaiting review + priorities"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - apps/desktop/src/renderer/src/nav/useTabNav.ts
      - apps/desktop/src/renderer/src/nav/pending.ts
      - apps/desktop/src/renderer/src/nav/pending.test.ts
    scope: "Pure function pending.ts: derive categories of items awaiting review and their order from subject statuses (①needs-human>②PR awaiting merge>③new comments awaiting replies>④recently changed status, ordered by enqueued_at within the same priority); useTabNav installs a Tab key handler to move focus/the large view to the next subject awaiting review, wrapping back to the beginning at the end and doing nothing when no subjects await review"
    acceptance: "vitest: pending sorts a mixed-status list according to the four priority levels + enqueued order within the same priority; Tab moves from the current subject to the next subject awaiting review and wraps around; Tab does nothing when no subjects await review"
---

# 0073 · openagents desktop app: parallel board + streaming detail view + Tab navigation for items awaiting attention

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG); the body is a group-level overview in the nine-section rust-RFC format. -->

## Summary

Build an **Electron desktop app** for OpenAgents (a standalone `apps/desktop`) to visualize the parallel results of
`vigil --parallel N`: the `N` subjects being processed appear as **N small board windows** (small window = results/status: stage, PR, evidence stamps, comment count,
`needs-human` badge, polling `work_queue` + GitHub); **click a small window to enter a detail view**, which presents that worker's
coding-agent session as a **live SSE stream**, with a button to **quickly switch to the next one**; the **Tab key** moves focus to
the **next small window awaiting attention**, cycling through four categories in priority order
(① suspended with `needs-human` > ② PR waiting for you to merge > ③ new human comments awaiting a reply > ④ just completed/just changed state). The frontend
**displays information read-only** (approvals/merges/comment replies still happen on GitHub or through the CLI). The backend makes
**only two additive changes**: ① **route each worker's agent output by subject**
(tee into a per-subject ring buffer) to feed the streaming detail view; ② provide a **local daemon interface** (localhost HTTP + SSE) for the Electron
main process to read `work_queue`/GitHub/streams.

## Motivation

**Current state.** `openagents vigil --parallel 3` starts one producer + K workers, advancing multiple subjects (`issue:N` /
`pr:N`) in parallel until they get stuck. But the only observation surface currently available to humans is **a single stderr text stream**: all workers' progress and all agents' live
output are **interleaved** in the same terminal stream (`_log` in `recipes/vigil.py` writes to stderr; stream-json events in
`backends/claude_code.py` also `print` to the same stdout). As parallelism increases, “who is doing what, which one is stuck, which one is waiting for me” all
**blur together**, making high-level oversight impossible. The only structured results view is `openagents/utils/templates/board.html`
(the static table from RFC-0001 decision 9: issue→status→PR→summary), which is neither live nor able to open an individual agent's session to see what it is changing.

**Why do this now.** CLAUDE.md principle 8, “Focus on results: humans no longer test at the code level, but test results,” + goal 2,
“Change what humans are responsible for (from details to high-level oversight)”—these call for a **results presentation surface**:
let a person see the outputs of N parallel tracks at a glance and press Tab once to jump to the next place that needs their decision. Commercially, the benchmark is the interactive agent experience of cursor/windsurf (CLAUDE.md
“General Principles”); a frontend that makes results visible is essential.

**The specific pain points it addresses.**
- Parallel progress is indistinguishable → a board of N small windows, one subject per window.
- No way to see what a particular agent is changing → a detail view with an SSE session stream.
- No way to know which one to inspect first → Tab navigation ordered by priority for items awaiting attention, turning “high-level oversight” into a single key.

## Guide-level explanation

A typical usage flow (from the human's perspective):

1. `openagents vigil --parallel 3` is already running in the background. The human separately runs `openagents desktop` (a command added
   by this spec, which starts the local daemon and opens the Electron window).
2. **Board**: the window displays 3 small windows, each a **results card** for one subject—title (`issue:163`), current stage
   (`↻ Advancing 3/8` / `⏸ needs-human` / `✅ PR#170 awaiting merge`), PR link, evidence stamps, comment count, and `needs-human` badge.
   The small windows refresh by polling every ~2s (data comes from the daemon's `/board`).
3. **Open the detail view**: click any small window → a full-screen detail view. Its upper half shows that worker's **live agent session stream**
   (SSE pushes the coding-agent's text and tool actions event by event, like watching it type); its lower half shows the subject's result anchors (PR, diff link, stage timeline).
4. **Quick switch**: a “Next ▶” button in the upper-right corner of the detail view switches to the next subject's detail view with one click
   (resubscribing to its stream), without returning to the board.
5. **Tab navigation for items awaiting attention**: press **Tab** anywhere, and focus/the detail view jumps to the **next window awaiting attention**.
   Items awaiting attention are sorted into four priority levels: first `needs-human` (the machine has given up and is waiting for you), then PRs awaiting merge
   (one click delivers the result), then new human comments awaiting a reply, and finally just completed/just changed state
   (take a glance). Within each level, use enqueue order. Wrap around at the end; if nothing is awaiting attention, Tab does nothing.
6. After viewing the information **read-only**, the human goes to GitHub to merge / reply to comments / remove the `needs-human` label—the frontend does not write to GitHub.

## Reference-level explanation

### Backend addition one: route agent output by subject (T1)

**Instrumentation.** In `_run_claude_streaming` in `backends/claude_code.py`, `for raw in proc.stdout:` (currently around line 184)
reads stream-json events line by line and calls `print(human)`. This is the only place where “what this agent said” becomes text. The change: add
`openagents/utils/streams.py`, providing a **thread-local subject sink registry** + **per-subject ring buffers**
(fixed-length rings to prevent long sessions from exhausting memory). In `claude_code.py`, replace `print(...)` with `streams.emit(line=...)`: it both writes to
stdout as before (unchanged behavior) and appends the line to the ring buffer for **the subject bound to the current thread**. A worker in `recipes/vigil.py`
calls `streams.bind(subject=...)` after claiming a subject and before entering `_reconcile`, then calls `streams.unbind()` on completion or exception.

**Why thread-local binding works.** The `subject UNIQUE` constraint at claim time already guarantees that a worker thread **processes only one
subject at a time** (see the `_worker_loop` comment in `vigil.py`), so “current thread → current subject” is a one-to-one mapping. There is no need to
pass a subject parameter all the way through `engine.run_agent`→`backend.run` (which would pollute the `AgentBackend` protocol). For unbound threads
(non-Vigil callers, such as a standalone `oa solve` run), `emit` only writes to stdout and does not enter any buffer—behavior remains entirely unchanged.

### Backend addition two: local daemon interface (T2)

Add `openagents/desktop/daemon.py`: a lightweight HTTP service listening only on `127.0.0.1` (stdlib `http.server`; principle 1:
do not introduce heavy dependencies), with two endpoints:
- `GET /board` → reads `work_queue` (subject/status/worker/attempts) + GitHub snapshots (PR/label/comment count) + each
  subject's **category of attention needed** (see below), returning a JSON array. The frontend polls it to render the small windows.
- `GET /stream/<subject>` → **SSE** (`text/event-stream`), first replaying the existing contents of that subject's ring buffer from T1,
  then continuously pushing new lines. The detail view subscribes to it.

Add a `desktop` subcommand in `openagents/cli.py`: start the daemon (default port, configurable with `--port`), optionally launch Electron with `--open`.
Port in use / subject does not exist → explicit error JSON, never silent failure.

### Frontend: Electron desktop (T3 foundation / T4 board / T5 detail view / T6 navigation)

Use multica's `apps/desktop` structure as a reference (see Prior art): Electron main process + preload + React renderer. The **foundation (T3)**
includes the main process/preload/renderer entry points, an HTTP+SSE client for the daemon, shared TS types mirroring the daemon JSON, and `App`—`App`
holds the `/board` polling data + selected subject + list of items awaiting attention, distributes them through React context, and uses `React.lazy` to **dynamically mount**
the Board/Detail/Nav extension points (dynamic imports, so T3 has no static dependencies on feature tasks, avoiding circular dependencies). The **board (T4)**,
**detail view (T5)**, and **navigation (T6)** are all pure consumers of context, do not import one another, and can be developed in parallel.

**Priority for items awaiting attention (T6, pure function `nav/pending.ts`).** Derive each subject's category and ordering from its state:
```
① Suspended with needs-human      (highest: the machine has given up; work stops unless you act)
② PR CI/e2e/review all green, awaiting human merge
③ New human comments on the issue/PR, with no agent response yet
④ A state transition just occurred in this round (new PR / just merged / just advanced)   (lowest: FYI only)
No category → excluded from the set awaiting attention
```
Tab selects the next item after the current focus in the order “① first, then `enqueued_at` within each level,” wrapping around at the end.

### Task DAG + file allocation (collaborative mode, pairwise-disjoint files)

| Task | Title | depends-on | files (single writer) |
|------|------|-----------|----------------------|
| T1 | Backend: route agent output by subject | — | `openagents/utils/streams.py` (new) · `openagents/backends/claude_code.py` · `openagents/recipes/vigil.py` · `tests/test_streams.py` |
| T2 | Backend: local daemon interface (HTTP+SSE) | T1 | `openagents/desktop/__init__.py` (new) · `openagents/desktop/daemon.py` (new) · `openagents/cli.py` · `tests/test_desktop_daemon.py` |
| T3 | Frontend: Electron shell + client + App foundation | T2 | `apps/desktop/package.json` · `apps/desktop/tsconfig.json` · `apps/desktop/electron.vite.config.ts` · `apps/desktop/src/main/index.ts` · `apps/desktop/src/preload/index.ts` · `apps/desktop/src/renderer/index.html` · `apps/desktop/src/renderer/src/main.tsx` · `apps/desktop/src/renderer/src/App.tsx` · `apps/desktop/src/renderer/src/daemon-client.ts` · `apps/desktop/src/renderer/src/types.ts` |
| T4 | Frontend: small board windows (board) | T3 | `apps/desktop/src/renderer/src/board/Board.tsx` · `.../board/Card.tsx` · `.../board/useBoard.ts` · `.../board/Board.test.tsx` |
| T5 | Frontend: streaming detail view + quick switch | T3 | `apps/desktop/src/renderer/src/detail/DetailOverlay.tsx` · `.../detail/StreamView.tsx` · `.../detail/useStream.ts` · `.../detail/DetailOverlay.test.tsx` |
| T6 | Frontend: Tab navigation for items awaiting attention + priorities | T3 | `apps/desktop/src/renderer/src/nav/useTabNav.ts` · `.../nav/pending.ts` · `.../nav/pending.test.ts` |

Parallelism: T1→T2→T3 run sequentially (the backend contract precedes the frontend foundation); after T3, **T4 / T5 / T6 run in three parallel tracks**
(pure context consumers with disjoint files).

### End-to-end validation script

`scripts/e2e-desktop.sh` (form=cli, runnable offline, serves as a gating deliverable): start the daemon against a seeded fake `work_queue`
+ stub GitHub → `curl /board` to assert JSON (subjects/status/categories awaiting review) → `curl -N /stream/<subject>` to assert that SSE emits
ring buffer lines one by one → run frontend `vitest` (unit tests for Board/Detail/pending components and pure functions) → `electron-vite build` smoke test.
Desktop window **visual interactions** (clicking to open a large window, the look and feel of Tab cycling) are listed as **manual validation steps** (a headless environment without browser MCP
cannot run a real Electron GUI; see Drawbacks) and are excluded from the offline gate.

## Drawbacks

- **At odds with Occam's razor (Principle 1).** Electron = an entire independent Node/TS stack (dozens of files in `apps/desktop` + a main process + a packaging
  pipeline), coexisting with the Python backend as two separate stacks. This is the largest single addition of entities in this repository. During design, the user **explicitly chose** full multica parity over
  a lighter local Web/TUI (see Rationale), so this cost is accepted.
- **`spec graph` does not cover the frontend.** ARCHITECTURE.md is generated from the Python import graph + docstrings; TS files are not included in the graph. The frontend's
  mapping to code relies solely on the body of this spec + `# Spec-0073/T*` comments, with no automated drift gate as a backstop.
- **The read-only ceiling.** Users can see “PR awaiting merge” but must switch to GitHub to click, fragmenting the action interface; this is a deliberate tradeoff at the MVP boundary (see Future).
- **Touches shared backend files.** T1 modifies `claude_code.py` / `vigil.py`, potentially affecting existing test doubles (historical lesson: shared prod code
  can break `_Fake*` doubles). T1 acceptance criteria include “existing tests updated and all passing.”
- **No offline e2e for the desktop GUI.** Visual validation of real Electron windows cannot be included in the CI gate and falls back to manual steps.

## Rationale and alternatives

**Why an Electron desktop app (rather than local Web / TUI).** Four forms were offered during design: local Web (Python serves HTTP+SSE,
the browser runs an SPA; the most economical and closest to Occam's razor), static polling HTML (extend board.html; minimal), terminal TUI (close to vigil's terminal home),
and Electron desktop (full multica parity; the heaviest). The user explicitly chose **Electron**, seeking parity with multica's desktop experience in one step. This spec
**reuses as much as possible** of the Web frontend assets (the rendering layer is standard React + SSE and can be placed inside any shell in the future) to offset the weight.

**Why results in small windows / streaming in large windows (rather than streaming in both or results in both).** The user decided that the board should provide “the whole picture at a glance,” so small windows present only results/
status (polling suffices, with no changes to backend streams); real-time streaming is needed only when drilling into an individual subject, so only large windows subscribe to SSE. This
**limits backend changes for per-subject stream routing to where large windows need them**, with zero backend burden from the board layer.

**Why read-only.** Principle 8, “test for outcomes,” + Principle 5, “PRs require human review”—GitHub is the authoritative interface for approval and merging. The frontend initially handles **presentation**
without taking over **operations**, giving the cleanest MVP boundary, with zero authentication / zero risk from GitHub writes. Action capabilities are left to Future.

**Alternative: no frontend; improve stderr log routing.** Add a subject prefix to `_log` + one log file per subject. The cost is extremely low, but this cannot provide
the **parallel overview** offered by the board / large windows / Tab navigation, and does not satisfy Goal 2. Rejected for that reason.

## Prior art

- **multica (github.com/multica-ai/multica, source code reviewed)** — Two frontends: `apps/web` (Next.js dashboard
  `/[workspace]/(dashboard)/agents/[id]`) + `apps/desktop` (Electron). The desktop structure is borrowed directly: `tab-bar.tsx` /
  `tab-content.tsx` / `window-overlay.tsx` (+`stores/window-overlay-store.ts`). Architecture: the daemon polls the server every 3s,
  spawns a CLI agent, and **streams results back**; CLI↔server uses HTTP REST + incremental updates via `--since`—our daemon↔desktop
  has the same structure (local HTTP + SSE). **Note the differences**: multica's `window-overlay-store` has **a single overlay, no next/prev**
  (used only for the onboarding flow), and its `keyboard-shortcuts.ts` only supports zoom/closing tabs, **with no window cycling**—so “small window↔large window +
  Tab cycling through items awaiting review” is **entirely new in this spec**, rather than copied.
- **This repository's `openagents/utils/templates/board.html` (RFC-0001 Decision 9)** — The existing static results table serves as the starting point for the fields
  and colors of T4 board cards.
- **`backends/claude_code.py` (RFC-0003 Decision 6)** — The existing line-by-line stream-json passthrough is the instrumentation point for T1's tee.

## Unresolved questions

- The process relationship between the daemon and vigil: does `openagents desktop` **only connect** to an already-running vigil (reading its sqlite `work_queue`
  + ring buffer), or can it **launch** a vigil on the user's behalf? A contract for ring buffer visibility across processes (vigil process memory vs. files on disk) needs to be established between T1/T2
  —the preference is to persist the ring buffer at the tail of `.openagents/streams/<subject>.log`, allowing the daemon and vigil to run as separate processes.
- Ports and multiple repositories: should the default port be fixed or discovered? When running Vigil for multiple repositories in parallel, should one daemon manage several repositories, or should each repository have its own daemon?
- Should the build/release of `apps/desktop` be incorporated into existing CI (Node toolchain, lefthook), or use a separate pipeline?

## Future possibilities

- **Action interface**: approve/merge PRs, respond to `needs-human`, and remove labels directly within large windows (add GitHub writes + authentication).
- **Electron packaging and distribution**: persistent system tray presence and automatic updates (align with multica SELF_HOSTING).
- **Multi-repository board**: aggregate Vigil runs for multiple repositories in one window (building on the `repos` section of `agent_config`).
- **Replace board.html**: incorporate the static results table into the desktop app as a read-only snapshot view.
- **Dependency graph visualization**: draw the `blocked_by` edges arranged by the curator as a DAG, with the board layered by dependency.
