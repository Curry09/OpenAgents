---
number: "0073"
title: openagents 桌面 app：并行看板 + 大窗流式 + tab 待看导航
issue: 170
slug: desktop-app
summary: Electron 桌面前端呈现 vigil --parallel N 的并行成果:N 个小窗看板(成果/状态)、点击进大窗看实时流式 agent 会话、Tab 按优先级跳到下一个待看窗;只读呈现,后端加 per-subject 流分流 + 本地 daemon 接口两样加法
tasks:
  - id: T1
    title: 后端：agent 输出按 subject 分流(stream tee)
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
    scope: 新增 streams.py:thread-local subject sink 注册表 + per-subject 定长 ring buffer;claude_code 的 print 换成 streams.emit(照旧打 stdout + 追加当前线程绑定 subject 的 buffer);vigil worker 认领 subject 进 _reconcile 前 bind、收工/异常 unbind
    acceptance: 单测:两线程各 bind 一个 subject 并发 emit,各自 ring buffer 只含自己的行不串扰;claude_code emit 落当前线程 sink;未绑定线程 emit 仅打 stdout 行为不变;既有 claude_code/vigil 测试替身更新且全绿
  - id: T2
    title: 后端：本地 daemon 接口(HTTP+SSE)
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
    scope: 新增 desktop/daemon.py:只听 127.0.0.1 的 stdlib http.server;GET /board 读 work_queue+GitHub 快照+每 subject 待看类别返 JSON;GET /stream/<subject> SSE 先补发再持续推 T1 ring buffer;cli 加 desktop 子命令启动 daemon(可 --port/--open)
    acceptance: 起服务 GET /board 返回 subjects/status/pr/待看类别 JSON;GET /stream/<subject> 以 SSE 逐条推该 subject ring buffer 行;端口占用/subject 不存在返明确错误 JSON;test_desktop_daemon 覆盖两端点 + 错误路径
  - id: T3
    title: 前端：Electron 外壳 + client + App 基座
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
    scope: Electron 主进程/preload/渲染入口;daemon 的 HTTP+SSE client;镜像 daemon JSON 的共享 TS 类型;App 持有 /board 轮询数据+选中 subject+待看列表经 context 下发,用 React.lazy 动态挂载 Board/Detail/Nav 三扩展点(不静态依赖 feature,避免循环)
    acceptance: electron-vite dev 起窗口;client 能拉 /board 与订 /stream/<subject>;App 渲染出 Board 空态占位;lazy slot 与 feature task 无静态循环依赖;tsc 通过
  - id: T4
    title: 前端：看板小窗(board)
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
    scope: N 小窗网格 + 成果卡(阶段/PR/证据戳/评论数/needs-human 徽标),消费 context 的 board 数据;卡片点击发 onOpen(subject) 事件;字段/配色以 board.html 为起点
    acceptance: vitest:给定 mock board 数据渲染 N 张卡,状态/徽标/PR 链接正确;点击卡片触发 onOpen(subject);空态渲染不报错
  - id: T5
    title: 前端：大窗流式 + 快切
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
    scope: 全屏大窗:上半 SSE 订 /stream/<subject> 实时渲染 agent 会话流,下半成果锚点(PR/diff 链接/阶段时间线);'下一个 ▶'按钮切下一 subject 重订流;Esc/关闭回看板
    acceptance: vitest:mock SSE 事件逐条渲染进 StreamView;'下一个'按钮切换 subject 并重订流;关闭触发 onClose;订阅在切换/卸载时正确清理
  - id: T6
    title: 前端：Tab 待看导航 + 优先级
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
    scope: 纯函数 pending.ts:从 subject 状态推待看类别与序(①needs-human>②PR等合并>③新评论待回>④刚变状态,同级按 enqueued_at);useTabNav 装 Tab 键 handler,把焦点/大窗跳到下一个待看 subject,循环到底回头,无待看则无操作
    acceptance: vitest:混合状态列表经 pending 排序符合四级优先级+同级 enqueued 序;Tab 从当前跳下一个待看并循环;无待看时 Tab 无操作
---

# 0073 · openagents 桌面 app：并行看板 + 大窗流式 + tab 待看导航

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给 OpenAgents 造一个 **Electron 桌面 app**（独立 `apps/desktop`），把 `vigil --parallel N` 的并行成果
可视化：`N` 个正在被处理的 subject 呈现为 **N 个小窗看板**（小窗=成果/状态：阶段、PR、证据戳、评论数、
`needs-human` 徽标，轮询 `work_queue` + GitHub）；**点击小窗进大窗**，大窗以 **SSE 实时流**呈现该 worker 的
coding-agent 会话，一个按钮**快切下一个**；**Tab 键**把焦点跳到**下一个「待看」小窗**，四类待看按优先级循环
（① `needs-human` 挂起 > ② PR 等你合并 > ③ 人类新评论待回 > ④ 刚完成/刚变状态）。前端**只读呈现**（审批/
合并/回评论仍回 GitHub 或 CLI）。后端只做**两样纯加法**：① 把每个 worker 的 agent 输出**按 subject 分流**
（tee 到 per-subject ring buffer）喂大窗流式；② 一个**本地 daemon 接口**（localhost HTTP + SSE）供 Electron
主进程读 `work_queue`/GitHub/流。

## Motivation

**现状。** `openagents vigil --parallel 3` 会起一个生产者 + K 个 worker，并行推进多个 subject（`issue:N` /
`pr:N`）到卡住为止。但人类当前唯一的观测面是**一条 stderr 文本流**：所有 worker 的进度、所有 agent 的实时
输出，全都**交织**在同一条终端流里（`recipes/vigil.py` 的 `_log` 打到 stderr；`backends/claude_code.py` 的
stream-json 事件也 `print` 到同一 stdout）。并行度一上去，「谁在干什么、哪个卡了、哪个等我」就**糊成一段**，
无法宏观把控。唯一的结构化成果视图是 `openagents/utils/templates/board.html`（RFC-0001 决策 9 的静态表：
issue→状态→PR→摘要），既非实时、也不能进单个 agent 的会话看它在改什么。

**为什么现在要做。** CLAUDE.md 理念 8「以成果为中心，人不再做代码层面的测试，而是面向成果测试」+ 目标 2
「改变人类负责的部分（不再是细节，而是宏观把控）」——这正需要一个**成果呈现面**：让人一眼看到 N 路并行各自
的产出，Tab 一下就跳到下一个需要他拍板的地方。商业上对标 cursor/windsurf 的交互式 agent 场景（CLAUDE.md
「总体原则」），一个看得见成果的前端是必需品。

**它解决的具体痛点。**
- 并行进度不可分辨 → N 小窗看板，一窗一 subject。
- 看不到某路 agent 正在改什么 → 大窗 SSE 流式会话。
- 不知道该先看谁 → Tab 按「待看」优先级导航，把「宏观把控」落成一个键。

## Guide-level explanation

一次典型使用（人类视角）：

1. 后台已在跑 `openagents vigil --parallel 3`。人类另起一条 `openagents desktop`（本 spec 新增命令，启动
   本地 daemon 并拉起 Electron 窗口）。
2. **看板**：窗口里出现 3 个小窗，每个小窗是一个 subject 的**成果卡**——标题（`issue:163`）、当前阶段
   （`↻ 推进 3/8` / `⏸ needs-human` / `✅ PR#170 等合并`）、PR 链接、证据戳、评论数、`needs-human` 徽标。
   小窗每 ~2s 轮询刷新（数据来自 daemon 的 `/board`）。
3. **进大窗**：点任意小窗 → 全屏大窗。大窗上半是该 worker 的**实时 agent 会话流**（SSE 逐条推 coding-agent
   的文本与工具动作，像看它敲键盘），下半是该 subject 的成果锚点（PR、diff 链接、阶段时间线）。
4. **快切**：大窗右上角一个「下一个 ▶」按钮，一键切到下一个 subject 的大窗（重订它的流），不必退回看板。
5. **Tab 待看导航**：任意位置按 **Tab**，焦点/大窗跳到**下一个「待看」窗**。「待看」按四级优先级排序：先
   `needs-human`（机器投降、等你），再 PR-等合并（一键出成果），再有人类新评论待回，最后刚完成/刚变状态
   （瞥一眼）。同级按入队顺序。循环到底回头；没有待看则 Tab 无动作。
6. 人类**只读**地看完，去 GitHub 点合并 / 回评论 / 摘 `needs-human` label——前端不写 GitHub。

## Reference-level explanation

### 后端加法一：agent 输出按 subject 分流（T1）

**埋点。** `backends/claude_code.py` 的 `_run_claude_streaming` 里 `for raw in proc.stdout:`（现约 184 行）
逐行读 stream-json 事件并 `print(human)`。这是唯一把「这一路 agent 说了什么」变成文本的地方。改法：新增
`openagents/utils/streams.py`，提供一个 **thread-local 的 subject sink 注册表** + **per-subject ring buffer**
（定长环，防长会话吃爆内存）。`claude_code.py` 把 `print(...)` 换成 `streams.emit(line=...)`：既照旧打
stdout（行为不变），又把行追加进**当前线程绑定的 subject** 的 ring buffer。`recipes/vigil.py` 的 worker 在
认领某 subject、进入 `_reconcile` 前 `streams.bind(subject=...)`，收工/异常时 `streams.unbind()`。

**为什么 thread-local 键得住。** 领取时的 `subject UNIQUE` 已保证一个 worker 线程**同一时刻只处理一个
subject**（见 `vigil.py` `_worker_loop` 注释），故「当前线程 → 当前 subject」是一一映射，无需把 subject
参数一路透传穿过 `engine.run_agent`→`backend.run`（那会污染 `AgentBackend` 协议）。未绑定的线程（非 vigil
调用方，如 `oa solve` 单跑）`emit` 只打 stdout、不进任何 buffer——行为完全不变。

### 后端加法二：本地 daemon 接口（T2）

新增 `openagents/desktop/daemon.py`：一个只听 `127.0.0.1` 的轻量 HTTP 服务（stdlib `http.server`，理念 1
不引重依赖），两个端点：
- `GET /board` → 读 `work_queue`（subject/status/worker/attempts）+ GitHub 快照（PR/label/评论数）+ 每个
  subject 的**待看类别**（见下），返回 JSON 数组。前端轮询它渲染小窗。
- `GET /stream/<subject>` → **SSE**（`text/event-stream`），把 T1 那个 subject 的 ring buffer 已有内容
  先补发、再持续推新行。大窗订它。

`openagents/cli.py` 新增 `desktop` 子命令：启动 daemon（默认端口，可 `--port`），可选 `--open` 拉起 Electron。
端口占用 / subject 不存在 → 明确错误 JSON，不静默。

### 前端：Electron 桌面（T3 基座 / T4 看板 / T5 大窗 / T6 导航）

对标 multica `apps/desktop` 结构（见 Prior art）：Electron 主进程 + preload + React 渲染层。**基座（T3）**
含主进程/preload/渲染入口、daemon 的 HTTP+SSE client、镜像 daemon JSON 的共享 TS 类型、以及 `App` —— `App`
持有 `/board` 轮询数据 + 选中 subject + 待看列表，经 React context 下发，并用 `React.lazy` **动态挂载**
Board/Detail/Nav 三个扩展点（动态 import，故 T3 不静态依赖 feature task，避免循环依赖）。**看板（T4）**、
**大窗（T5）**、**导航（T6）** 都是 context 的纯消费者，互不 import，可并行开发。

**待看优先级（T6，纯函数 `nav/pending.ts`）。** 对每个 subject 从其状态推出类别与序：
```
① needs-human 挂起      (最高：机器投降、不动你活儿就停)
② PR CI/e2e/review 全绿、等人合并
③ issue/PR 有人类新评论、agent 尚未回应
④ 本轮刚发生状态跃迁（新开 PR / 刚合并 / 刚推进）   (最低：仅 FYI)
无类别 → 不在待看集
```
Tab 从当前焦点在「① 优先、同级按 `enqueued_at`」的序里取下一个，循环到底回头。

### Task DAG + 文件分配（协同模式，files 两两不相交）

| Task | 标题 | depends-on | files（单一 writer） |
|------|------|-----------|----------------------|
| T1 | 后端：agent 输出按 subject 分流 | — | `openagents/utils/streams.py`(新) · `openagents/backends/claude_code.py` · `openagents/recipes/vigil.py` · `tests/test_streams.py` |
| T2 | 后端：本地 daemon 接口(HTTP+SSE) | T1 | `openagents/desktop/__init__.py`(新) · `openagents/desktop/daemon.py`(新) · `openagents/cli.py` · `tests/test_desktop_daemon.py` |
| T3 | 前端：Electron 外壳 + client + App 基座 | T2 | `apps/desktop/package.json` · `apps/desktop/tsconfig.json` · `apps/desktop/electron.vite.config.ts` · `apps/desktop/src/main/index.ts` · `apps/desktop/src/preload/index.ts` · `apps/desktop/src/renderer/index.html` · `apps/desktop/src/renderer/src/main.tsx` · `apps/desktop/src/renderer/src/App.tsx` · `apps/desktop/src/renderer/src/daemon-client.ts` · `apps/desktop/src/renderer/src/types.ts` |
| T4 | 前端：看板小窗(board) | T3 | `apps/desktop/src/renderer/src/board/Board.tsx` · `.../board/Card.tsx` · `.../board/useBoard.ts` · `.../board/Board.test.tsx` |
| T5 | 前端：大窗流式 + 快切 | T3 | `apps/desktop/src/renderer/src/detail/DetailOverlay.tsx` · `.../detail/StreamView.tsx` · `.../detail/useStream.ts` · `.../detail/DetailOverlay.test.tsx` |
| T6 | 前端：Tab 待看导航 + 优先级 | T3 | `apps/desktop/src/renderer/src/nav/useTabNav.ts` · `.../nav/pending.ts` · `.../nav/pending.test.ts` |

并行度：T1→T2→T3 串行（后端契约先于前端基座）；T3 之后 **T4 / T5 / T6 三路并行**（context 纯消费者，
文件不相交）。

### 端到端验证脚本

`scripts/e2e-desktop.sh`（form=cli，离线可跑、作门控成果）：起 daemon 打向一份 seed 过的 fake `work_queue`
+ 桩 GitHub → `curl /board` 断言 JSON（subjects/status/待看类别）→ `curl -N /stream/<subject>` 断言 SSE 逐条
推出 ring buffer 行 → 跑前端 `vitest`（Board/Detail/pending 组件与纯函数单测）→ `electron-vite build` 冒烟。
桌面窗口的**视觉交互**（点击进大窗、Tab 循环的观感）列为**人工验证步骤**（无 browser MCP 的 headless 环境
跑不了真实 Electron GUI，见 Drawbacks），不进离线门控。

## Drawbacks

- **顶撞奥卡姆（理念 1）。** Electron = 一整套独立 Node/TS 栈（`apps/desktop` 几十个文件 + 主进程 + 打包
  链），与 Python 后端两条栈并存，是本仓最大的一次「增实体」。用户在设计环节**明确选择**全 multica 对标而非
  更轻的本地 Web/TUI（见 Rationale），故接受此代价。
- **`spec graph` 覆盖不到前端。** ARCHITECTURE.md 由 Python import 图 + docstring 生成，TS 文件不进图；前端
  的「对代码映射」只靠本 spec 正文 + `# Spec-0073/T*` 注释，无自动漂移闸兜底。
- **只读的天花板。** 看到「PR 等合并」却要切去 GitHub 点，动作面割裂；这是 MVP 边界的自觉取舍（见 Future）。
- **触碰共享后端文件。** T1 改 `claude_code.py` / `vigil.py`，可能碰既有测试替身（历史教训：shared prod code
  会打破 `_Fake*` 双),T1 验收含「既有测试更新且全绿」。
- **桌面 GUI 无离线 e2e。** 真实 Electron 窗口的视觉验证进不了 CI 门控，退化为人工步骤。

## Rationale and alternatives

**为什么 Electron 桌面（而非本地 Web / TUI）。** 设计环节给了四个形态：本地 Web（Python 起 HTTP+SSE，
浏览器跑 SPA，最省、最贴奥卡姆）、静态轮询 HTML（扩展 board.html，最小）、终端 TUI（贴 vigil 终端老家）、
Electron 桌面（全 multica 对标，最重）。用户明确选 **Electron**，要一步到位对标 multica 的桌面体验。本 spec
把 Web 前端的资产**尽量复用**（渲染层是标准 React + SSE，将来可塞进任意壳）以对冲重量。

**为什么小窗成果 / 大窗流式（而非都流式或都成果）。** 用户拍板：看板层要「一眼看全局」，故小窗只呈现成果/
状态（轮询即可，不改后端流）；深入某一路才需要实时流，故只有大窗订 SSE。这把「按 subject 分流」的后端改动
**收窄到大窗需要时**，看板层零后端负担。

**为什么只读。** 理念 8「面向成果测试」+ 理念 5「PR 需人审」——审批合并的权威面是 GitHub。前端先做**呈现**、
不接管**操作**，MVP 边界最干净、零鉴权/零 GitHub 写风险。可操作留给 Future。

**备选：不做前端，改进 stderr 日志分流。** 给 `_log` 加 subject 前缀 + 每路一个日志文件。成本极低，但给不了
看板/大窗/Tab 导航的**并行宏观视图**，不满足目标 2。故否。

## Prior art

- **multica（github.com/multica-ai/multica，已读源码）** —— 双前端：`apps/web`(Next.js dashboard
  `/[workspace]/(dashboard)/agents/[id]`) + `apps/desktop`(Electron)。桌面结构直接借鉴：`tab-bar.tsx` /
  `tab-content.tsx` / `window-overlay.tsx`(+`stores/window-overlay-store.ts`)。架构：daemon 每 3s 轮询 server、
  spawn CLI agent、**stream results back**，CLI↔server 走 HTTP REST + `--since` 增量——我们的 daemon↔desktop
  同构（本地 HTTP + SSE）。**注意分歧**：multica 的 `window-overlay-store` 是**单 overlay、无 next/prev**
  （只用于 onboarding 流），其 `keyboard-shortcuts.ts` 只有 zoom/关 tab、**无窗口循环**——故「小窗↔大窗 +
  Tab 待看循环」是**本 spec 净新增**，不照搬。
- **本仓 `openagents/utils/templates/board.html`（RFC-0001 决策 9）** —— 现有静态成果表，作 T4 看板卡的字段
  与配色起点。
- **`backends/claude_code.py`（RFC-0003 决策 6）** —— 现有 stream-json 逐行透传，是 T1 tee 的埋点。

## Unresolved questions

- daemon 与 vigil 的进程关系：`openagents desktop` 是**只连**一个已在跑的 vigil（读它的 sqlite `work_queue`
  + ring buffer），还是可**代拉**一个 vigil？ring buffer 跨进程可见性（vigil 进程内存 vs. 落文件）需在 T1/T2
  之间定契约——倾向 ring buffer 落 `.openagents/streams/<subject>.log` 尾部，使 daemon 与 vigil 可分进程。
- 端口与多仓库：默认端口固定还是探测？多仓库并行守夜时一个 daemon 管几仓还是一仓一 daemon？
- `apps/desktop` 的构建/发布是否纳入现有 CI（Node 工具链、lefthook）还是独立流水线？

## Future possibilities

- **可操作面**：大窗内直接 approve/merge PR、回 `needs-human`、摘 label（接 GitHub 写 + 鉴权）。
- **Electron 打包分发**：托盘常驻、自动更新（对齐 multica SELF_HOSTING）。
- **多仓库看板**：一个窗口聚合多仓守夜（承 `agent_config` 的 `repos` 段）。
- **取代 board.html**：静态成果表并入桌面 app 的一个只读快照视图。
- **依赖图可视化**：把 curator 排的 `blocked_by` 边画成 DAG，看板按依赖分层。

