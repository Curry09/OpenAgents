---
number: "0004"
title: openagents vigil —— 守夜人模式（自主 issue→PR 全流程循环）
issue: 9
slug: vigil-autonomous-loop
summary: 守夜人模式：让 OpenAgents 自主循环跑「发现 issue → 求解 → 提 PR」全流程，不用人盯着。含标签门控的 issue 发现、发现段+守候段两段循环与单 issue 错误隔离，以及 vigil 子命令和端到端脚本。
tasks:
  - id: T1
    title: github 层 `list_issues`（标签门控的 issue 发现）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - automation
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: 在 openagents/github.py 增加 list_issues(*, labels, state="open")，调用 gh issue list --state <state> [--label L ...] --json number,title,body，解析为既有 Issue 列表；复用 _gh_json/GithubError，不新增数据类型。
    acceptance: 单测覆盖——无 label 时命令不含 --label 且正确解析多条 issue；带多个 label 时命令含对应多个 --label；空结果返回 []；gh 非零退出抛 GithubError；ruff check / ruff format --check / pytest 通过。
  - id: T2
    title: '`Vigil` 守夜人循环模块（发现段 + 守候段 + 错误隔离）'
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - automation
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/vigil.py
      - tests/test_vigil.py
    scope: 新建 openagents/vigil.py，实现 Vigil（注入 Orchestrator/Messages/State）的 run、discover_and_dispatch。discover_and_dispatch 调 github.list_issues 后经三道闸（标签已在 list 层、State 无 run、远端无分支）过滤出新 issue，串行 start_rfc（派单只起草 RFC），单项失败记录并跳过。run 每轮先发现再 messages.poll，once 跑一轮即返回，否则 time.sleep(interval) 续循环，KeyboardInterrupt 干净退出。远端分支判据复用一处 git ls-remote（vigil 内最小私有助手或经注入的 orchestrator 暴露，不改 orchestrator 既有契约）。
    acceptance: 单测（mock github.list_issues/Orchestrator.start_rfc/Messages.poll/time.sleep 与远端分支判据）覆盖——已有 State run 的 issue 被跳过；远端已有分支的 issue 被跳过；全新 issue 触发一次 start_rfc；某 issue start_rfc 抛 OrchestratorError 时被跳过且不影响同轮其余 issue 与 poll；once=True 只跑一轮、不 sleep；once=False 多轮调用 sleep(interval)；KeyboardInterrupt 干净返回；discover_and_dispatch 返回实际派单编号列表。
  - id: T3
    title: CLI `vigil` 子命令 + 端到端脚本
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - automation
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
      - scripts/e2e-rfc-0004-vigil.sh
    scope: 在 openagents/cli.py 注册 vigil 子命令（--interval 默认 60、可重复 --label 默认 ["openagents"]、--base 默认 main、--once 旗标），实现 _cmd_vigil 走 preflight、构造 Vigil（新增 _vigil_for 工厂，复用既有 _orchestrator_for/_messages_for/_state_for）并调用 run，挂入 _dispatch handlers；运行期异常由既有 _run 统一处理。新增 scripts/e2e-rfc-0004-vigil.sh（离线确定性段 + 可选真实冒烟段，仿 e2e-rfc-0002）。
    acceptance: 单测覆盖——vigil 出现在子命令集合；默认 interval=60/labels=["openagents"]/base="main"/once=False；vigil --once --interval 5 --label a --label b --base dev 正确解析并透传给打桩的 Vigil.run；_cmd_vigil 先跑 preflight；返回码 0。e2e 脚本离线段（ruff + pytest）可独立跑通。
---

# 0004 · openagents vigil —— 守夜人模式（自主 issue→PR 全流程循环）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

「守夜人模式」让 OpenAgents 自主循环跑「发现 issue → 求解 → 提 PR」全流程，无需人持续盯守。它由三层组成：`github.list_issues` 做标签门控的 issue 发现、`Vigil` 模块以「发现段 + 守候段」两段循环驱动派单并对单 issue 失败做错误隔离、CLI `vigil` 子命令把它接成一条可一键启动的常驻循环，并配套端到端脚本。

## Motivation

OpenAgents 的目标是让人从代码细节中抽身、只做宏观把控。但在本 feature 之前，「领取 issue → 起草 RFC/PR」仍需人逐个手动触发：人得自己去仓库看有哪些待办 issue、判断哪些还没人接、再对每个未接的逐一发起派单。这一步是纯机械的轮询与去重，恰恰是机器该接管的部分。

「守夜人」（vigil）补上这个自动化缺口：它像一个常驻的值夜进程，周期性地扫描带特定标签的 open issue，自动把尚未开工的新 issue 派单出去起草 RFC，同时在每一轮里顺带处理 PR comment 消息（守候段）。人因此只需启动一次 `openagents vigil`，之后日常的「发现并派单」全自动完成，人的触点收敛到「提 issue」与「审 PR」两端。

## Guide-level explanation

对使用者：跑一条命令即可让 OpenAgents 进入守夜状态：

```
openagents vigil [--interval 60] [--label openagents ...] [--base main] [--once]
```

- `--label` 决定守夜人盯哪些标签的 issue（可重复，默认 `openagents`）——只有带这些标签的 open issue 才会被发现。
- `--interval` 是每一轮之间的休眠秒数（默认 60）。
- `--base` 是派单起草时 PR/worktree 的基线分支（默认 `main`）。
- `--once` 只跑一轮就返回（便于测试与脚本化），不带则常驻循环直到 `Ctrl-C`。

每一轮，守夜人先「发现并派单」：列出带标签的 open issue，对每个 issue 过三道闸——标签匹配（已在列举层保证）、本地 State 里没有该 issue 的 run（没接过）、远端没有对应工作分支（没人在做）——只对全新 issue 串行发起一次派单（起草 RFC）。某个 issue 派单失败只记录并跳过，不影响同轮其余 issue。随后进入「守候段」处理 PR comment 消息，再休眠 `interval` 秒进入下一轮。`Ctrl-C` 干净退出。

## Reference-level explanation

落到改动，分解为 3 个 Task，`files` 互斥、各 Task 单一 writer：

1. **T1 github 层 `list_issues`** — 在 `openagents/github.py` 增加 `list_issues(*, labels, state="open")`，调用 `gh issue list --state <state> [--label L ...] --json number,title,body`，解析为既有 `Issue` 列表。复用现有的 `_gh_json` 解析助手与 `GithubError` 错误类型，不新增数据结构。这是发现段的数据来源：标签门控直接由 `--label` 透传给 `gh`，发现层即完成第一道闸。

2. **T2 `Vigil` 模块**（依赖 T1） — 新建 `openagents/vigil.py`，实现 `Vigil` 类（构造时注入 `Orchestrator`/`Messages`/`State`）。两个核心方法：
   - `discover_and_dispatch`：调 `github.list_issues` 取带标签的 open issue，再过两道运行期闸——本地 `State` 无该 issue 的 run（去重已接过的）、远端无对应工作分支（去重正在做的）——对剩下的全新 issue 串行调用 `Orchestrator.start_rfc`（派单只起草 RFC，不直接落地代码）。单个 issue `start_rfc` 抛 `OrchestratorError` 时记录并跳过，保证错误隔离；方法返回实际派单的 issue 编号列表。
   - `run`：每一轮先 `discover_and_dispatch`，再 `messages.poll`（守候段，处理 PR comment）。`once=True` 跑一轮即返回；否则 `time.sleep(interval)` 后续循环。`KeyboardInterrupt` 干净退出。

   远端分支判据复用一处 `git ls-remote`（在 vigil 内实现最小私有助手，或经注入的 orchestrator 暴露），不改动 orchestrator 既有契约。

3. **T3 CLI `vigil` 子命令 + e2e**（依赖 T2） — 在 `openagents/cli.py` 注册 `vigil` 子命令（`--interval` 默认 60、可重复 `--label` 默认 `["openagents"]`、`--base` 默认 `main`、`--once` 旗标）。`_cmd_vigil` 先跑 preflight，再用新增的 `_vigil_for` 工厂构造 `Vigil`（复用既有 `_orchestrator_for`/`_messages_for`/`_state_for`），调用 `run`，并挂入 `_dispatch` handlers；运行期异常由既有 `_run` 统一处理。

**端到端验证**：`bash scripts/e2e-rfc-0004-vigil.sh`——离线确定性段跑 `ruff` + `pytest`，外加可选的真实冒烟段（仿 `e2e-rfc-0002` 结构），离线段可独立跑通。

依赖 DAG：`T1 → T2 → T3`（线性链，无并行）。

## Drawbacks

- 守夜人是常驻轮询进程，`interval` 设得过短会增加对 `gh` 与远端的请求压力；过长则发现延迟变大，需在响应性与开销间权衡。
- 「三道闸」去重依赖本地 State 与远端分支两处真值来源，若二者短暂不一致（如分支已建但 State 未落盘）可能出现重复派单的窗口，需靠幂等的下游派单兜底。

## Rationale and alternatives

- **为什么把发现与派单合进一个循环模块**：发现（list_issues）、去重（State + 远端分支）、派单（start_rfc）与守候（poll）是同一值夜节律下的连续动作，合到 `Vigil.run` 一处编排比散落在 CLI 里更内聚，也便于对整段循环做 hermetic 单测（mock 各依赖即可）。
- **为什么标签门控放在 `list_issues` 层而非循环里过滤**：直接把 `--label` 透传给 `gh issue list`，让 GitHub 端完成筛选，减少拉取量也避免在客户端重复实现标签逻辑（奥卡姆，不新增数据类型）。
- **为什么单 issue 失败只跳过而非中断整轮**：守夜人要长期无人值守地跑，一个坏 issue 不应拖垮整轮发现与守候——错误隔离是常驻循环的健壮性底线。
- **备选：用 GitHub webhook 推送替代轮询**。否决（YAGNI）：webhook 需公网回调端点与额外基础设施，当前以轮询起步即可满足「无人值守发现」，后续可作演进项。

## Prior art

「常驻 watcher 周期性轮询任务源、对新任务去重后派发、隔离单任务失败」是 CI/自动化领域成熟的守护进程模式（如各类 polling-based job runner）。本 feature 取其「轮询 + 去重 + 错误隔离」核心，落到 OpenAgents 的 issue→RFC 派单语境。

## Unresolved questions

无。三道闸的去重判据、两段循环节律、错误隔离行为均已在本组确定。

## Future possibilities

- 用 GitHub webhook 事件推送替代周期轮询，降低发现延迟与请求开销。
- 守候段可扩展为更细的消息分类与优先级调度，不止处理 PR comment。
- 派单并发化（当前串行）以提升一轮内多 issue 的吞吐。

