---
number: "0066"
title: 阶段计时：墙钟 per-phase 时延——旁路 append-only 事件流 + 跨轮重建报告，定位流水线瓶颈
issue: 157
slug: phase-timing-wall-clock
summary: 为守夜流水线加墙钟阶段计时：每 tick 在生产者判定咽喉 _consider 旁路追加一条带时间戳的阶段信号事件到 .openagents/timing.jsonl（与 runtime-state.json 文件级零耦合、写失败不掀翻主流程），phase 直接取自 level-triggered 的 _Verdict 分类（solve/rebase/fix-ci/e2e/review-or-fix/merge + awaiting-ci/effect/mergeability/blockers + in-flight + terminal 各态），天然把旧栈会坍缩成一个 open 的合并段细分成 CI-wait / review-wait / merge；新增 runtime.timing 独立模块提供 append 写入器 + 跨轮时长重建聚合器（单 issue 时间线 + 跨 issue 每阶段 p50/p90 + 最长尾），oa report 子命令读 jsonl 输出文本报告并标注墙钟精度下限=轮询 interval。
e2e:
  intent: 证明「墙钟阶段计时旁路埋点 + 跨轮时长重建」在离线确定性链路上成立——反复调 run_vigil(once=True) 一次一个 tick 推一个 issue 环，每 tick 在 _consider/_reconcile 旁路把 level-triggered _Verdict 归一成 phase 事件 append 到 .openagents/timing.jsonl；跨轮把「等 CI」「等 review」「在合并」细分成独立 phase（不再糊成旧栈单一 open）；timing.record 写失败被容错吞掉、守夜照常推进、_fingerprint 埋点前后不变（护栏一不自毁）；oa report 读回 jsonl 聚合出单 issue 各阶段 duration + 跨 issue p50/p90 + 最长尾，并标注墙钟精度下限=轮询 interval。
  method: "形态：纯后端埋点 + 聚合 + CLI 报告，无 product-facing 前端可导航；自检工具列表无 Playwright /\nChrome DevTools MCP，故不设浏览器 e2e，改用离线确定性测法（沿用 Spec-0060/0061/0064 同款）：\n1. timing 模块针对性 pytest（纯标准库、不触网络/仓库）：record append 合法 JSON 五键 + UTC ISO8601；\n   注入 open/write 抛异常 → record 静默吞掉不 raise（容错）；load_events 跳损坏行；timelines 跨轮\n   重建各 phase duration（含 phase 复现分段累加、末条 terminal 时长 0）；phase_stats 出每 phase\n   p50/p90 + 最长尾 + interval 精度下限字段。\n2. vigil 埋点针对性 pytest（假 backend/github seam，不触真实 LLM/网络/仓库）：once 跑一 tick 后\n   timing.jsonl 生成含 dispatch/等待/合并各段；_phase_of 四值 verdict × facts 逐态归一；record 抛异常\n   时 _consider/_reconcile 照常返回（容错端到端）；_fingerprint 埋点前后相等（旁路不进 fp）；合并段\n   awaiting-ci 与 review-or-fix 可区分。\n3. CLI 针对性 pytest：oa report 对造好的 timing.jsonl 输出单 subject 时间线 + 跨 subject p50/p90 +\n   「精度下限 = interval」字样；空/缺文件友好提示、退出码 0。\n4. grep 锚点（e2e 脚本）：runtime/timing.py 存在且零 recipes.vigil import（无循环依赖）；timing 事件\n   写入点仅在 vigil.py 两处 _consider/_reconcile；record 容错（except 兜底）就位。\n脚本：scripts/e2e-spec-0066-phase-timing-wall-clock.sh（ruff check + ruff format --check + 针对性\npytest + grep 锚点），被 PR e2e signpost 采集。\n"
tasks:
  - id: T1
    title: runtime.timing 独立模块：append-only 事件写入器（容错） + 跨轮时长重建聚合器
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/timing.py
      - tests/test_runtime_timing.py
    scope: 新增独立模块 runtime.timing（仅依赖标准库，与 runtime-state.json / vigil-queue.db 文件级零耦合，理念 10）。三件事：①append-only 写入器 record(*, work_dir, subject, issue, pr, phase, now)——把一条 {subject, issue, pr, phase, at(ISO8601 UTC)} 事件 append 到 work_dir/.openagents/timing.jsonl（每行一个 JSON 对象）；**容错**：捕获全部异常、绝不向调用方抛（写失败只丢一条计时，不掀翻守夜主流程）。②loader load_events(path)——读 jsonl，逐行容错跳过损坏行。③聚合器（纯函数，可 hermetic 测）：timelines(events) 按 subject 排序事件、把连续同 phase 合并为占据区间（**每条事件占据「到该 subject 下一条事件为止」的墙钟区间**，末条事件为终点、时长 0），聚合出单 subject 各 phase 总 duration；phase_stats(events, interval) 跨 subject 汇总每 phase 的 p50/p90（对「各 subject 在该 phase 的总 dwell」求分位）+ 最长尾 subject；报告结构里带上 interval 作为墙钟精度下限标注。不含任何 vigil/_Verdict 类型依赖（phase 是纯字符串），避免与 recipes.vigil 循环 import。
    acceptance: pytest tests/test_runtime_timing.py 通过（不触真实网络/仓库）：record 追加一行合法 JSON 且含 subject/issue/pr/phase/at 五键、at 为 UTC ISO8601；record 在 open/write 抛异常时被 monkeypatch 注入后**静默吞掉、不 raise**（容错断言）；load_events 跳过损坏行只保留合法事件；timelines 对一条造好的跨轮事件序列正确重建各 phase 的 duration（含 phase 复现——review→fix-ci→review 分两段累加），末条 terminal 事件时长为 0；phase_stats 对多 subject 造样本给出每 phase 的 p50/p90 与最长尾 subject，且报告结构里带 interval 精度下限字段。函数全部关键字-only、private 无默认值。
  - id: T2
    title: vigil 旁路埋点：生产者 _consider（等待/终态段）+ worker _reconcile（活动动作段）追加阶段信号
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
    scope: 在 recipes.vigil 的两处判定咽喉旁路调 timing.record（只追加事件、**不改任何返回值/落盘形态/控制流/fp**，对齐既有「只富化不回归」）：①生产者 _consider（vigil.py:1472，每 tick 每 subject 算出 verdict 处）——把 verdict 归一成 phase 字符串追加事件，覆盖 QUIET 各 reason（awaiting-ci=CI-wait / awaiting-effect / awaiting-mergeability / awaiting-blockers）、TERMINAL（据 facts 细分 merged/closed/needs-human）、ACTIONABLE 入队瞬间（solve/reply/rebase/fix-ci/e2e/review-or-fix/merge）、IN_FLIGHT；②worker _reconcile（vigil.py:2351，推进分支表处）——按当轮实际执行的 verdict.action 追加**活动段**事件，把生产者视角的泛 in-flight 解析成 solving/fixing-ci/reviewing 等真动作。新增纯 helper _phase_of(verdict, facts) 做归一（vigil 内、读 _Verdict/_Facts，故归一留在 vigil 而非 timing，保 timing 零 vigil 依赖）。为取 work_dir 落盘路径，给 _consider 增关键字参 work_dir（additive）。record 容错保证任一计时失败不影响守夜推进。
    acceptance: pytest tests/test_recipe_vigil.py + tests/test_recipe_vigil_timing.py 全绿（既有 vigil 测试零回归——record 旁路不改 verdict/fp/state/GitHub 调用）：跑一轮 _producer_tick（once）后 timing.jsonl 生成、含 dispatch(solve)/等待(awaiting-*)/合并各段事件；_phase_of 对四值 verdict × facts 逐态断言归一正确（TERMINAL 细分 merged/closed/needs-human；QUIET 取 reason；ACTIONABLE 取 action；IN_FLIGHT→in-flight）；断言 record 抛异常（monkeypatch）时 _consider/_reconcile 不受影响照常返回（容错端到端）；断言 _fingerprint 在埋点前后不变（旁路写文件不进 fp、不触发护栏一自毁）；合并段能区分 awaiting-ci（CI-wait）与 review-or-fix（review-wait），不再糊成一段。
  - id: T3
    title: oa report CLI 子命令：读 timing.jsonl 输出单 issue 时间线 + 跨 issue p50/p90 文本报告
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
    scope: 在 cli.py 加子命令 oa report（sub.add_parser + _cmd_report handler，薄路由，业务在 timing 聚合器）：读 work_dir/.openagents/timing.jsonl，经 timing.load_events + timelines + phase_stats 输出 stdout 文本报告——单 issue/subject 时间线（各 phase duration）、跨 issue 每阶段 p50/p90 + 最长尾 subject，并**显式标注墙钟精度下限 = 轮询 interval**（从 config 读，缺省 60s）。空 jsonl / 文件缺失时给友好提示、退出码 0。HTML 看板（复用 utils/results.py 的 string.Template 静态渲染思路）列入 Future，本期只出文本表（奥卡姆，先给 stdout）。
    acceptance: pytest tests/test_cli_timing.py 通过：oa report 对造好的 timing.jsonl 输出含各 phase duration 的单 subject 时间线与跨 subject p50/p90，且输出里出现「精度下限 = interval」字样与实际 interval 值；timing.jsonl 缺失/空时打印友好提示、返回 0（不抛栈）；子命令注册进 argparse（--help 可见）、handler 关键字-only 调聚合器。
---

# 0066 · 阶段计时：墙钟 per-phase 时延——旁路 append-only 事件流 + 跨轮重建报告，定位流水线瓶颈

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给守夜流水线（发现 → triage → 编码 → 交付 → CI → review → merge）加**墙钟阶段计时**：一个 issue/PR
在每个阶段停留的**日历时间**，用来定位瓶颈——到底是编码慢、CI 排队久、还是卡在 review。

做法一句话：守夜是**轮询式**的（每 tick 把每个 subject 往前推一步，`time.sleep(interval)` 后再来一轮，
没有任何一处阻塞等 CI/review），所以墙钟时延**必须跨轮重建**。每 tick 在守夜已有的判定咽喉
`_consider`（生产者）与 `_reconcile`（worker）**旁路**追加一条带时间戳的「阶段信号」事件到独立文件
`.openagents/timing.jsonl`；某阶段的墙钟时长由聚合器从这串事件跨轮重算。**精度下限 = 轮询 interval**
（默认 60s），报告里如实标注。

**关键洞察（与 issue 原文的偏差，见 Motivation/Rationale）**：issue 写于旧栈，担心「合并段的 status
会坍缩成一个 `open`、测不出 CI-wait/review-wait」。但 Spec-0064 已把 `merge_pr.py`/`_advance_merge`
收敛进 `recipes/vigil.py` 的 level-triggered `_classify`——它每 tick 对每个 subject 输出一个**四值 +
细分动作/成因**的 `_Verdict`（`awaiting-ci`/`review-or-fix`/`merge`/…），**合并段本就已经细分好了**。
故本 spec 的阶段信号直接取自 `_Verdict`，一处旁路埋点即天然区分 CI-wait / review-wait / merge，无需
再去 `set_run` 上补细分（新栈 `set_run` 只在两处被调，是稀疏信号，见 Reference-level）。

## Motivation

**现状：全仓没有任何计时埋点。** 全仓 `datetime` 只用于认领过期/复活窗口（`_INFLIGHT_ALARM_SECONDS`
看门狗、`closed_at` 复活窗口）与看门狗的 `age = now − last_progress_at`——**没有一处测量「某阶段花了
多久」**。要优化先得能量化：我们并不知道一个 issue 从被认领到合并，时间耗在哪。拍脑袋优化没有依据。

**为什么必须跨轮重建、不能包一个阻塞调用计时。** 流水线是轮询式 reconcile：`run_vigil` 每 tick 读一次
GitHub 现态、推一步、`sleep(interval)`，**没有任何一处阻塞等待 CI 或 review**（这是 level-triggered
的架构第一原则，见 `recipes/vigil.py` 模块头引 Kubernetes design principles）。所以「某阶段耗时」不是
一次函数调用的墙钟，而是**该 subject 反复被判成同一个阶段的那段连续 tick 覆盖的日历时间**。做法：每次
产生「阶段信号」时追加一条带时间戳事件；阶段时长由聚合器从事件流重算。精度下限 = interval（每条相邻
事件间隔≈一个轮询），报告里标注为测量下限，不当精确值。

**issue 原文的埋点地图已过期（证据驱动，理念 7）。** issue 指向 `openagents/recipes/merge_pr.py` 的
`_advance_merge`（`merge_pr.py:176`）与 `runtime/state.py:41` 的 `set_run`。实际（`git` 现态）：
- `recipes/merge_pr.py` **已不存在**——Spec-0064 把 recipes 层 6→3 收敛，合并各闸迁进
  `recipes/stages.py`（`ci`/`e2e`/`merge` 自由函数）+ 由 `recipes/vigil.py` 的 `_classify` 分支表编排。
- `RuntimeState.set_run` 在 `state.py:67`（非 41 行），且在新栈**只被调两次**（`vigil.py:2626` 置
  `pr-open`、`vigil.py:2772` 置 `done`）——它不再是「状态转移咽喉」，是稀疏信号。
- issue 担心的「合并段坍缩成一个 `open`」在新栈**已被 `_Verdict` 解决**：level-triggered 分类每 tick
  就把等 CI（`awaiting-ci`）、要 review（`review-or-fix`）、可合（`merge`）判成不同值。

因此本 spec **落实 issue 的意图**（细分合并段、定位瓶颈），但**换用新栈的真实咽喉**（`_Verdict` 而非
`merge_pr` 的 `reason` 字符串、`_consider` 而非 `set_run`）。这是 brownfield 对齐，不是抗命。

## Guide-level explanation

把守夜想成一台状态机，每 tick 对每个在飞的 issue/PR 盖一个「你现在在哪个阶段」的时间戳邮戳。攒够邮戳，
就能倒推出「这个 issue 在 CI 队列里排了 40 分钟、在 review 上卡了 2 小时」。

**三个动作：**

1. **盖戳（埋点）**。守夜每 tick 已经在 `_consider`（生产者判每个 subject 该不该动手）和 `_reconcile`
   （worker 推进它领到的 subject）里算出一个 `_Verdict`。我们只在这两处**旁路**加一行
   `timing.record(...)`：把 `_Verdict` 归一成一个 phase 字符串（`solving` / `awaiting-ci` /
   `review-or-fix` / `merged` …），连同 subject / issue / pr / 当前时间，append 一行到
   `.openagents/timing.jsonl`。**旁路 = 不改任何返回值、不改控制流、不进 fingerprint、写失败就吞掉**
   （对齐守夜「只富化不回归」的既有做法）。

2. **攒戳（存储）**。`.openagents/timing.jsonl` 每行一个 JSON 事件，与 `runtime-state.json`、
   `vigil-queue.db` **文件级零耦合**（理念 10 解耦）。append-only、容错——一条计时写崩，绝不能掀翻守夜
   主流程（守夜第一要务是「活着进下一轮」）。

   ```jsonl
   {"subject": "issue:145", "issue": 145, "pr": 154, "phase": "solving",      "at": "2026-07-09T12:00:00Z"}
   {"subject": "issue:145", "issue": 145, "pr": 154, "phase": "awaiting-ci",  "at": "2026-07-09T12:03:11Z"}
   {"subject": "issue:145", "issue": 145, "pr": 154, "phase": "review-or-fix","at": "2026-07-09T12:41:02Z"}
   {"subject": "issue:145", "issue": 145, "pr": 154, "phase": "merged",       "at": "2026-07-09T12:44:20Z"}
   ```

3. **倒推（报告）**。`oa report` 读 jsonl，按 subject 把连续同 phase 的事件合并成占据区间，算出每阶段
   duration；跨 issue 汇总每阶段 p50/p90 + 最长尾 issue，指出哪个阶段是长尾。stdout 文本表即可（HTML
   看板列 Future）。报告顶部标注：**墙钟精度下限 = 轮询 interval（本次 Ns），各段时延有 ±interval 粒度
   误差，勿当精确值。**

**「纯等待」发生在哪** 一眼可辨：`awaiting-ci` 段长 = CI 排队；`review-or-fix`/`awaiting-effect` 段长 =
卡在评审推进；`awaiting-blockers` = 等上游依赖合并。这正是 issue 要回答的问题。

## Reference-level explanation

### 埋点咽喉：level-triggered `_Verdict`（新栈真相，替代 issue 的 `merge_pr.reason`）

`recipes/vigil.py` 的 `_classify`（`vigil.py:686`）是纯函数分支表，每 tick 对每个 subject 输出一个
`_Verdict{kind, reason?, action?}`：

- `kind` ∈ `IN_FLIGHT` / `TERMINAL` / `QUIET` / `ACTIONABLE`；
- `ACTIONABLE.action` ∈ `reply` / `solve` / `rebase` / `fix-ci` / `e2e` / `review-or-fix` / `merge`；
- `QUIET.reason` ∈ `awaiting-blockers` / `awaiting-mergeability` / `awaiting-ci` / `awaiting-effect`。

这张表**天生细分了合并段**——`awaiting-ci`（CI 排队）、`review-or-fix`（评审推进）、`merge`（合并动作）
是不同取值。这就是为什么本 spec **不碰 `set_run`**（它稀疏、且信息量被 `_Verdict` 完全覆盖），而把阶段
信号直接挂到 `_Verdict`。

**两个旁路埋点（均在 `vigil.py`，T2 独占该文件）：**

1. **生产者 `_consider`（`vigil.py:1472`）** — 每 tick 每 subject 算出 `verdict` 处（`vigil.py:1489`）。
   记录**等待段 + 终态 + 入队瞬间**：`QUIET` 取 `reason`（含护栏一降级后的 `awaiting-effect`）、
   `TERMINAL` 据 `facts` 细分 `merged`/`closed`/`needs-human`、`ACTIONABLE` 取 `action`、`IN_FLIGHT`
   记 `in-flight`。为落盘路径给 `_consider` 增关键字参 `work_dir`（additive）。
2. **worker `_reconcile`（`vigil.py:2351`）** — worker 持锁推进分支表处，按当轮实际执行的
   `verdict.action` 记**活动段**事件，把生产者视角的泛 `in-flight` 解析成 `solving`/`fixing-ci`/
   `reviewing` 等真动作（生产者只看得到「有人在干」，worker 才知道在干哪一步）。

归一逻辑 `_phase_of(verdict, facts)` 是 `vigil.py` 内的纯 helper（它读 `_Verdict`/`_Facts` 类型，故留在
`vigil` 而非 `timing`，保 `timing` 对 `vigil` **零依赖**、杜绝循环 import）。

### 跨轮时长重建（聚合模型）

`timing.timelines(events)`：按 subject 分组、按 `at` 排序，**每条事件占据「到该 subject 下一条事件为止」
的墙钟区间**（末条事件为终点、区间 0）；把连续同 phase 的区间累加得该 subject 各 phase 总 duration。此
模型天然支持 **phase 复现**（`review-or-fix → fix-ci → review-or-fix` 分两段累加）且每区间≈一个 interval
（精度下限的来源）。

`timing.phase_stats(events, interval)`：对每个 phase，收「各 subject 在该 phase 的总 dwell」求 p50/p90
（尾延迟看 p90，见 Prior art 引 Google SRE），并给出该 phase 的最长尾 subject；报告结构携带 `interval`
作为精度下限标注。

### 存储与容错

`runtime/timing.py`（新模块，**仅标准库**）：
- `record(*, work_dir, subject, issue, pr, phase, now)` → append 一行到 `work_dir/.openagents/timing.jsonl`；
  **捕获全部异常、绝不抛**（写失败只丢一条计时）。
- `load_events(*, path)` → 读 jsonl，逐行容错跳过损坏行。
- `timelines` / `phase_stats` → 纯函数聚合，hermetic 可测。

事件 schema：`{subject, issue, pr, phase, at}`（`subject` = `"issue:5"`/`"pr:12"` 唯一键，`issue`/`pr`
可为 null——裸 PR 无 issue 归属；`at` = UTC ISO8601）。**不改** `set_run`/`_classify`/`merge` 的返回值与
既有落盘形态，只旁路追加（对齐「只富化、不回归」）。

### DAG + 文件分配

| Task | 文件（互斥） | 依赖 | 干什么 |
|---|---|---|---|
| **T1** | `openagents/runtime/timing.py`, `tests/test_runtime_timing.py` | — | 独立模块：容错 append 写入器 + 跨轮重建聚合器 |
| **T2** | `openagents/recipes/vigil.py`, `tests/test_recipe_vigil_timing.py` | T1 | 两处旁路埋点 `_consider`/`_reconcile` + `_phase_of` 归一 |
| **T3** | `openagents/cli.py`, `tests/test_cli_timing.py` | T1 | `oa report` 子命令：读 jsonl 输出文本报告 + interval 标注 |

`files` 两两不相交（协同模式无冲突根，理念 6）。T2、T3 均只依赖 T1、彼此无依赖 → 可并行。

### e2e 脚本

`scripts/e2e-spec-0066-phase-timing-wall-clock.sh`（离线确定性：ruff + 针对性 pytest + grep 锚点），
被 PR e2e signpost 采集。形态为纯后端，无浏览器 e2e（见 frontmatter `e2e.method`）。

## Drawbacks

- **多一个旁路写点、多一个文件**。每 tick 每 subject 多一次 append IO。缓解：写入极小（一行 JSON）、
  容错吞异常、与主状态文件解耦——最坏情况是丢计时，不影响守夜正确性。
- **精度受限于 interval**。60s 轮询下测不出亚分钟级阶段；这是轮询架构的固有下限，只能标注、不能消除
  （要更细就得改成阻塞式计时，那会重写整个 level-triggered 架构，得不偿失）。
- **`needs-human` 之后的人工等待测不全**。一旦打 `needs-human`，`_classify` 判 `TERMINAL`、**轮询停止**
  → 停止期间不再盖戳。人摘 label 后下一 tick 才有新事件；「人花了多久」只能由 `needs-human` 事件到下一
  事件的间隔近似（见 Unresolved）。
- **事件流会持续增长**。长期运行 jsonl 会变大；本期不做轮转/压缩（列 Future）。
- **旁路埋点仍改了 `_consider` 签名**（加 `work_dir`）——虽 additive，但触了共享大文件 `vigil.py`，需保
  既有 vigil 测试零回归（T2 acceptance 已含此断言）。

## Rationale and alternatives

**为什么埋 `_Verdict` 而非 issue 指定的 `set_run` + `merge_pr.reason`。** issue 的埋点地图写于旧栈、已
过期（`merge_pr.py` 被 Spec-0064 删除，`set_run` 在新栈仅两处调用）。新栈的 `_Verdict` 是**唯一**每
tick 对每 subject 输出细分阶段的咽喉，一处旁路即覆盖 dispatch/RFC/CI-wait/review-wait/merge/terminal
全谱——严格优于在稀疏 `set_run` 上补细分。这是把「软约定」硬化：与其在两个地方分别打戳再拼，不如挂到
本就存在的单一分类真源。

**备选 A：只埋 `set_run`（照 issue 字面）。** 否决——新栈 `set_run` 只发 `pr-open`/`done` 两个信号，
测不出任何等待段（CI/review/mergeability 全在 `_classify` 里、根本不经 `set_run`），恰好复刻 issue 自己
担心的「坍缩成一段」。

**备选 B：wrap 一个阻塞计时器（`perf_counter` 包住某调用）。** 否决——轮询架构没有阻塞等待可包；这测的
是 agent 活跃算力时长（`engine.run_agent`），是**另一维度**，本 spec 明确非目标。

**备选 C：把计时写进 `runtime-state.json`（复用现有状态文件）。** 否决——违反解耦（理念 10）：计时是
append-only 事件流，状态是最新快照 kv；混在一起要么污染状态 schema、要么让状态文件无限增长，且状态写是
「读整个 JSON→改一键→整写回」，掺进高频事件会放大 Spec-0065 已治理的并发写丢更新面。独立 jsonl 天然
append、天然容错、天然解耦。

**备选 D：区间重建用「首戳−末戳」（issue 字面）。** 采纳其精神但精化为「事件占据到下一事件的区间、按
phase 累加」——更稳健：正确处理 phase 复现（review→fix→review 两段）与 dwell 归属，且每区间≈一 interval
自然导出精度下限。

## Prior art

- **rust-lang RFC 形态**（本 spec 的 9 段结构来源）：<https://github.com/rust-lang/rfcs>。
- **Kubernetes level-triggered reconcile**（为什么墙钟必须跨轮重建、不能靠边沿/阻塞计时）：
  <https://github.com/kubernetes/design-proposals-archive/blob/main/architecture/principles.md>
  （守夜 `recipes/vigil.py` 模块头已据此建成，本 spec 顺其架构）。
- **append-only 日志 / event log 作为可倒推的真相流**（为什么用 jsonl 事件而非快照）：Jay Kreps,
  "The Log: What every software engineer should know about real-time data's unifying abstraction"，
  <https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying-abstraction>。
- **尾延迟看百分位（p50/p90/p99）而非均值**（为什么报告出 p50/p90 + 最长尾）：Google SRE Book,
  "Monitoring Distributed Systems"，<https://sre.google/sre-book/monitoring-distributed-systems/>。
- **仓内既有成果层渲染**（HTML 看板的 Future 复用点）：`openagents/utils/results.py`（`string.Template`
  + 标准库 `webbrowser` 静态渲染，零前端依赖，RFC-0001/T6）。

## Unresolved questions

- **`needs-human` 期间的人工等待如何计入**？轮询在 `TERMINAL` 停止、停止期间无事件，只能由前后事件间隔
  近似。是否需要一个「label 变更时补一戳」的旁路（读 GitHub label timeline）留待人工确认——本期先只近似，
  报告里标注该段为「下限」。
- **事件流轮转策略**？长期运行 jsonl 增长，何时轮转/归档/压缩，本期不做（Future）。
- **interval 动态变化时的精度标注**？若同一 issue 跨越过不同 interval 配置，精度下限该取哪个——本期假设
  interval 恒定、取当前 config 值。

## Future possibilities

- **HTML 成果看板**：复用 `utils/results.py` 的 `string.Template` 思路把 timing 报告渲成单页 HTML 看板
  （理念 8 成果层，甘特式阶段条 + p50/p90 分布图），`oa report --html` 落盘并本地打开。
- **agent 活跃算力时长（另一维度，本期非目标）**：wrap `runtime/engine.py` 的 `run_agent` 用
  `perf_counter` 测 agent 实际计算时长，与墙钟时延对照（墙钟 − 活跃 = 纯等待）。另开 issue。
- **实时监控 / 告警**：把 timing 事件接到时序库（Prometheus/告警），本期明确非目标。
- **旧栈埋点**：`orchestrator.py`/`messages.py`/`state.py` 旧栈已被 CLI 弃用，不埋（本期非目标）。
- **事件流轮转 + 跨 run 聚合**：多次守夜 run 的 timing 合并成趋势看板。

