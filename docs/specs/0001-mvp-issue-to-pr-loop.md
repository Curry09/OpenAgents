---
number: "0001"
title: MVP — 单 issue → 单 agent → 真实 PR 的最小自举闭环
issue: 0
slug: mvp-issue-to-pr-loop
summary: OpenAgents 的最小可用自举闭环：拉一个 issue、派一个 agent、用 Claude Code 后端把它做成一个真实的 GitHub PR。产出包骨架、CLI、后端适配、单 issue 编排、PR 评论消息机制和成果看板，是整个项目的起点。
tasks:
  - id: T1
    title: 包骨架 + CLI 框架 + 后端接口契约
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/__init__.py
      - openagents/cli.py
      - openagents/config.py
      - openagents/backends/__init__.py
      - openagents/backends/base.py
      - pyproject.toml
      - tests/test_cli.py
      - tests/test_config.py
      - tests/test_base.py
    scope: 建 openagents/ 包；cli.py 注册 init/solve/poll/watch/board 五个子命令（命令体内延迟 import 业务模块，本子任务只放可运行骨架与占位）；config.py 实现 resolve_project/ensure_project（cwd 解析 git root + remote，缺失时交互式新建，gh repo create 经延迟 import 调用 github.create_repo）；backends/base.py 定义 AgentBackend 协议与 AgentResult；pyproject.toml 声明 CLI entry point 与依赖。
    acceptance: openagents --help 列出五个子命令；AgentBackend 协议可被导入；resolve_project 能从 cwd 识别 git root 与 remote、非仓库返回 None，ensure_project(interactive=False) 缺失时抛错（交互分支与 git init/gh 被 mock）；ruff check / ruff format --check 通过；tests/test_cli.py 验证子命令注册与 preflight 调用。
  - id: T2
    title: Claude Code 后端适配器
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/backends/claude_code.py
      - tests/test_backend_claude_code.py
    scope: 实现 ClaudeCodeBackend，以子进程方式非交互调用 Claude Code，在给定工作目录按任务描述改代码，返回 AgentResult。
    acceptance: 给定临时仓库与任务，适配器能驱动 Claude Code 产生文件改动并正确报告 changed/summary；子进程调用被 mock 的单测通过。
  - id: T3
    title: GitHub 集成（issue/PR/comment）
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: 封装 gh CLI，实现 create_repo（供冷启动绑定）/get_issue/create_pr/list_comments/post_comment/check_status（CI 状态），统一错误处理。
    acceptance: 各函数对 gh 输出正确解析为数据类；create_repo 正确组装 gh repo create 参数（私有/公开）；check_status 正确归类 pass/fail 并提取失败日志摘要；gh 子进程被 mock 的单测覆盖正常与错误路径。
  - id: T4
    title: 单 issue → 单 agent 编排 + 状态
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - openagents/state.py
      - tests/test_orchestrator.py
      - tests/test_state.py
    scope: 实现 Orchestrator.solve（拉 issue→建分支→调后端→开 PR→写 State）与 iterate（喂回 comment→追加 commit→push）；实现 State 的 JSON 持久化（.openagents/state.json）含状态机（含 done）与 comment 游标。
    acceptance: 用 mock 的 backend + github，solve 端到端产出一条 RunRecord 且状态流转正确；State 读写与游标逻辑单测通过。
  - id: T5
    title: PR comment 消息机制
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - tests/test_messages.py
    scope: 实现 Messages.poll：对 open PR 先检测是否已 merge（已 merge→置 done 并跳过）；否则 (a) 读 CI 状态，失败则以失败日志触发 iterate(reason="ci")（修到 CI 全绿）；(b) 比对游标，新 comment 触发 iterate(reason="comment") 并更新游标。实现 Messages.watch：按间隔循环 poll。
    acceptance: 给定带新 comment 的 mock PR，poll 正确触发一次 iterate(reason="comment") 并推进游标；CI 失败的 mock PR 触发 iterate(reason="ci")，CI 全绿则不触发；已 merge 的 PR 被置 done 且不再迭代；无新 comment 且 CI 绿时不触发；watch 的循环间隔逻辑（time.sleep 被 mock）单测通过。
  - id: T6
    title: 成果看板 + 本地启动命令
    status: done
    priority: P0
    tags:
      - architecture
      - cli
      - protocol
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/results.py
      - openagents/templates/board.html
      - tests/test_results.py
    scope: 实现 results.render(runs)->html 与 board() 启动逻辑（渲染 State 为单页 HTML 并用 webbrowser 打开）；提供 HTML 模板。
    acceptance: 给定若干 RunRecord，render 产出含 issue 标题/状态/PR 链接的 HTML；board 命令能生成文件并触发本地打开（打开动作在测试中被 mock）；单测通过。
---

# 0001 · MVP — 单 issue → 单 agent → 真实 PR 的最小自举闭环

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

OpenAgents 的最小可用自举闭环：从一个 GitHub issue 出发，派单个 agent（以 Claude Code 为后端）在隔离工作目录里改代码，产出一个**真实的** GitHub PR，并在 PR 上通过 comment 与 CI 状态驱动迭代，直到合入；所有运行状态落盘为 `.openagents/state.json`，并渲染成一个单页成果看板。本组交付包骨架、CLI 框架、后端接口契约、Claude Code 适配器、GitHub 集成、单 issue 编排、消息机制与看板共 6 个 Task，是整个项目能「自己迭代自己」的起点。

## Motivation

OpenAgents 的目标是用多 agent 协作把人从代码细节里解放出来、只做宏观把控，而这套系统本身就是它要交付的产品——因此第一步必须先搭出一个能跑通「issue→PR」的最小骨架，再用这个骨架来迭代自身。

在有完整多 agent 协同之前，需要先证明最关键的单条链路是可行的：**一个 issue、一个 agent、一个真实 PR**。这条链路一旦闭合，就具备了「拉 issue→改代码→开 PR→按反馈迭代→合入」的自举能力，后续的多 agent 并行、reviewer 闸、版本发布等都建立在它之上。本组刻意只做这条最小闭环（奥卡姆剃刀，如无必要勿增实体），不引入多 agent 调度、并行裁决等更重的机制。

## Guide-level explanation

使用者的视角是一组 CLI 子命令：

- `openagents init` — 把当前目录绑定到一个 GitHub 仓库（解析 git root + remote；缺失时可交互式新建仓库）。
- `openagents solve <issue>` — 拉取该 issue，建工作分支，调用后端（Claude Code）改代码，开一个真实 PR，并把这次运行记录进 State。
- `openagents poll` / `openagents watch` — 轮询 / 持续监听 open PR：已合并的置为 `done`；CI 失败的用失败日志触发一次迭代修到全绿；有新 comment 的把 comment 喂回 agent 追加提交。
- `openagents board` — 把 State 渲染成单页 HTML 成果看板并在浏览器打开，呈现每个 issue 的标题、状态与 PR 链接。

核心心智模型：**一个 issue 对应一次 run，一个 run 对应一个 PR**；人不在代码层介入，而是看看板（成果）、必要时在 PR 上留 comment，agent 收到 comment 就迭代。

## Reference-level explanation

落到代码，分解为 6 个 Task（`files` 互斥，各 Task 单一 writer；DAG 见末尾）：

1. **T1 包骨架 + CLI 框架 + 后端接口契约** — 建 `openagents/` 包；`cli.py` 注册 `init`/`solve`/`poll`/`watch`/`board` 五个子命令，命令体内**延迟 import** 业务模块（保证骨架可运行、解耦各模块加载）。`config.py` 的 `resolve_project`/`ensure_project` 负责项目绑定：从 cwd 解析 git root + remote，缺失且 `interactive=True` 时交互式新建仓库（`gh repo create` 经延迟 import 调用 `github.create_repo`），`interactive=False` 缺失时抛错。`backends/base.py` 定义 `AgentBackend` 协议与 `AgentResult` 数据类，作为所有后端适配器的契约（兼容 Claude Code / Codex 等不同 cli-agent）。`pyproject.toml` 声明 CLI entry point 与依赖。
2. **T2 Claude Code 后端适配器**（依赖 T1） — 实现 `ClaudeCodeBackend`，以子进程方式**非交互**调用 Claude Code，在给定工作目录按任务描述改代码，返回 `AgentResult(changed, summary, ...)`。它是 `AgentBackend` 协议的第一个具体实现。
3. **T3 GitHub 集成**（依赖 T1） — 封装 `gh` CLI：`create_repo`（供冷启动绑定）/`get_issue`/`create_pr`/`list_comments`/`post_comment`/`check_status`。`check_status` 读取 CI 状态并归类 pass/fail、提取失败日志摘要，是后续「CI 失败触发迭代」的数据来源；所有函数统一错误处理并把 `gh` 输出解析为数据类。
4. **T4 单 issue → 单 agent 编排 + 状态**（依赖 T2、T3） — `Orchestrator.solve`：拉 issue→建分支→调后端→开 PR→写 State，端到端产出一条 `RunRecord`。`Orchestrator.iterate`：把回流的 comment / CI 失败日志喂回后端，追加 commit 并 push（这就是 agent 之间「收到一条 comment 消息」后继续工作的机制）。`State` 用 `.openagents/state.json` 持久化，含状态机（包含终态 `done`）与 comment 游标（记录已处理到哪条 comment，避免重复触发）。
5. **T5 PR comment 消息机制**（依赖 T3、T4） — `Messages.poll` 对每个 open PR：先检测是否已 merge，已 merge→置 `done` 并跳过；否则 (a) 读 CI 状态，失败则以失败日志触发 `iterate(reason="ci")` 修到 CI 全绿；(b) 比对游标，发现新 comment 触发 `iterate(reason="comment")` 并推进游标。`Messages.watch` 按固定间隔循环调用 `poll`（`time.sleep` 在测试中被 mock）。这层把「PR 收到 comment / CI 变化」转化为对 `iterate` 的驱动，是 OpenAgents 类 GitHub comment 消息传递机制的最小实现。
6. **T6 成果看板 + 本地启动命令**（依赖 T4） — `results.render(runs) -> html` 把 State 里的 `RunRecord` 渲染为单页 HTML（含 issue 标题/状态/PR 链接），`board()` 生成文件并用 `webbrowser` 打开；提供 `templates/board.html` 模板。前端只用于呈现成果（以成果为中心，人面向成果而非代码细节做验收）。

**依赖 DAG**：`T1 → T2`，`T1 → T3`，`T2,T3 → T4`，`T3,T4 → T5`，`T4 → T6`。T1 是根；T2、T3 在 T1 后可并行；T4 汇聚 T2/T3；T5、T6 在 T4（及 T3）后。

本组为最小闭环，端到端验证通过各 Task 的 mock 单测覆盖（backend / github / 子进程 / `time.sleep` / `webbrowser` 均被打桩），未单列 `scripts/*.sh` e2e 脚本。

## Drawbacks

- 只支持单 issue → 单 agent 串行，没有多 agent 并行与 reviewer 裁决，吞吐与协同能力有限——但这是 MVP 的有意取舍，后续 spec 在此基础上叠加。
- 强依赖外部 `gh` CLI 与 Claude Code 可执行文件，运行环境需预装。

## Rationale and alternatives

- **为什么先做单 issue 最小闭环**：自举需要一条最短的可工作链路。先闭合 issue→PR→迭代→合入，才有「用 OpenAgents 迭代 OpenAgents」的载体；多 agent 并行属于后续叠加，过早引入会增大 blast radius、违背奥卡姆剃刀。
- **后端做成协议 + 适配器（`AgentBackend`）而非写死 Claude Code**：去中心化要求同一项目里不同 agent 背后的 coding agent 可不同（Claude Code / Codex / nexau…），先定契约（T1）再落第一个实现（T2），让后续后端零成本接入、模块解耦。
- **CLI 子命令体内延迟 import 业务模块**：保证 `--help`/骨架在依赖未就绪时仍可运行，并把各业务模块的加载解耦，避免顶层 import 形成耦合环。
- **State 落盘为 JSON + comment 游标**：用最简单的文件持久化承载状态机，游标避免重复处理同一条 comment；无需引入数据库（YAGNI）。
- **看板用单页静态 HTML + 本地 `webbrowser` 打开**：以最小成本呈现成果，不引入前端框架或服务端。

## Prior art

借鉴 GitHub 的 PR + comment 协作模型：用 PR 承载一次交付、用 comment 作为反馈与 agent 间消息的载体（"your PR received a comment"）。后端的协议 + 适配器形态对标 cursor / windsurf 等交互式 coding agent 对多后端的兼容思路。

## Unresolved questions

无。本组范围限定为单 issue 最小闭环，多 agent 并行、reviewer 闸、版本发布等留待后续 spec。

## Future possibilities

- issue 层面的并行：同时为多个 issue 各派一个 agent。
- feature 层面的多 agent 协同：同一 feature 内多 agent 协作（reviewer 裁决聚合等）。
- 后端扩展到 Codex / nexau 等更多 cli-agent。
- 看板从静态 HTML 升级为可交互前端，呈现更丰富的成果维度。

