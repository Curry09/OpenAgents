---
number: "0008"
title: PR 正文「端到端验证」指路牌（从 RFC 自动生成）
issue: 0
slug: pr-e2e-signpost
summary: 在 PR 正文里自动生成一段「怎么做端到端验证」的指路牌，内容从该分支新增的 RFC 自动解析渲染，让审核者一眼知道如何验收。
tasks:
  - id: T1
    title: RFC 解析与指路牌渲染（纯模块）
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/rfc.py
      - tests/test_rfc.py
    scope: 新建 openagents/rfc.py，实现 E2EHints、extract_e2e、render_signpost、signpost_for（见接口契约）。抽取脚本路径（限 `### 集成测试` 子段）与一行预期（限 `### 手动验证` 子段），各字段缺失置 None 并在渲染时降级；从文件名解析 NNNN。全程不抛错。模块 docstring 与公开函数引用 RFC-0008。
    acceptance: 单测覆盖——完整 RFC 抽出脚本+预期并渲染三行；无集成测试脚本 / 无手动验证 / 二者皆无时各自降级且不抛错；畸形 Markdown 不抛错；文件名 0008-x.md 解析出编号 8。ruff + pytest 通过。
  - id: T2
    title: 定位本分支新增的 RFC 文件
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/workspace.py
      - tests/test_workspace.py
    scope: 在 Workspace 增 changed_rfc_path，用 `git diff --name-only origin/<base>...HEAD -- docs/rfcs/` 取首个 NNNN-*.md（排除 README.md）返回绝对 Path，无则 None；复用既有 _git 封装。方法 docstring 引用 RFC-0008。
    acceptance: 单测——在临时 git 仓库造 base 与含新 RFC 的分支，方法返回该 RFC 路径；无新增 RFC 时返回 None；不把 README.md 误判为 RFC。ruff + pytest 通过。
  - id: T3
    title: 接线进 PR 正文编排
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: 改 orchestrator：import rfc；扩展 _pr_body 增 e2e_section（无默认值）；start_rfc 在 commit_and_push 后、create_pr 前定位 RFC 文件→渲染指路牌→拼进正文。定位失败/渲染为 None 时正文回退为原样、不抛错。新增/改动处注释引用 RFC-0008。
    acceptance: 单测（假 backend + 假 Workspace + monkeypatch github）——start_rfc 传给 create_pr 的 body 含「## 端到端验证」段且内容来自 RFC；changed_rfc_path 返回 None 时 body 不含该段且不抛错。ruff + pytest 通过。
  - id: T4
    title: 端到端脚本 + RFC 索引
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-rfc-0008-pr-e2e-signpost.sh
      - docs/rfcs/README.md
    scope: 新增 scripts/e2e-rfc-0008-pr-e2e-signpost.sh（沿用既有 e2e 脚本两段式：默认离线 ruff check / ruff format --check / pytest；OPENAGENTS_E2E_REAL=1 + OPENAGENTS_E2E_ISSUE 时真实演练 openagents rfc <issue> 并断言其 draft PR 正文含「## 端到端验证」段）。在 docs/rfcs/README.md 的 RFC 列表追加 RFC-0008 行。
    acceptance: 离线段在干净仓库通过；脚本可执行（set -euo pipefail、chmod +x）；README 列表含 RFC-0008 条目。
---

# 0008 · PR 正文「端到端验证」指路牌（从 RFC 自动生成）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

在 agent 自动开出的 PR 正文里，自动生成一段「端到端验证」指路牌：从该分支新增的 RFC 文件里解析出**集成测试脚本路径**与**一行手动验证预期**，渲染成正文中的一个固定小节，让审核者无需翻代码即可一眼知道「这个 PR 怎么验收」。整条链路纯解析、纯渲染、全程不抛错，定位不到 RFC 或字段缺失时正文自动降级为原样。

## Motivation

OpenAgents 的协作模型以 PR + comment 为消息总线，PR 是 agent 之间、以及 agent 与人之间对齐的核心载体。审核者（人或 reviewer agent）面对一个 PR 时，最先想知道的不是逐行 diff，而是「以成果为中心」的问题：这个改动要怎么端到端验证、跑什么脚本、期望看到什么。这部分信息其实已经写在每个改动配套的 RFC 里（集成测试脚本、手动验证预期），但散落在 RFC 正文中，审核者得自己去翻 `docs/rfcs/` 找到对应文件、读完才能动手验收。

把这段「怎么验收」的信息从 RFC 自动抽出、直接钉在 PR 正文顶部，能消除这层手工查找：审核者一眼看到脚本路径与预期，立刻可以验证成果。这正契合 OpenAgents「以成果为中心、人面向成果测试」的理念——把验收入口前置到 PR 正文。

## Guide-level explanation

对审核者：以后打开 agent 开的 PR，正文里会多出一段「## 端到端验证」小节，里面直接给出该改动配套 RFC 中声明的集成测试脚本（例如 `bash scripts/xxx.sh`）和一行预期结果。照着跑即可验收，不用再去 `docs/rfcs/` 翻文件。

对开发链路：这段指路牌不是手写的，而是在 `start_rfc` 开 PR 的过程中自动生成的——编排器定位本分支新增的那个 RFC 文件，解析其中两个约定子段（`### 集成测试` 给脚本路径、`### 手动验证` 给一行预期），渲染成三行小节拼进 PR 正文。如果这个分支没有新增 RFC、或 RFC 里没写这些字段，正文就回退为原样，绝不因此报错或阻塞开 PR。约定很轻：只要 RFC 在这两个子段里写清验收方式，指路牌就会自动出现。

## Reference-level explanation

落到改动，分解为 4 个 Task（DAG 见下；`files` 互斥，各 Task 单一 writer）：

1. **T1 RFC 解析与指路牌渲染（纯模块，无依赖）** — 新建 `openagents/rfc.py`，提供 `E2EHints`、`extract_e2e`、`render_signpost`、`signpost_for`。`extract_e2e` 从 RFC 文本里限定子段抽取：脚本路径只取 `### 集成测试` 子段、一行预期只取 `### 手动验证` 子段；字段缺失置 `None`，渲染时对应行降级省略；并从文件名（如 `0008-x.md`）解析出编号 NNNN。整模块**全程不抛错**（畸形 Markdown 也不崩），模块 docstring 与公开函数注释引用 `RFC-0008`。
2. **T2 定位本分支新增的 RFC 文件（无依赖）** — 在 `Workspace` 增方法 `changed_rfc_path`，用 `git diff --name-only origin/<base>...HEAD -- docs/rfcs/` 取本分支相对 base 新增的首个 `NNNN-*.md`（排除 `README.md`），返回绝对 `Path`，无则 `None`；复用既有 `_git` 封装。方法 docstring 引用 `RFC-0008`。
3. **T3 接线进 PR 正文编排（依赖 T1、T2）** — 改 `orchestrator`：`import rfc`，给 `_pr_body` 增参数 `e2e_section`（无默认值，显式传参）；`start_rfc` 在 `commit_and_push` 之后、`create_pr` 之前调用 `changed_rfc_path` 定位 RFC →`signpost_for` 渲染指路牌→拼进正文。定位失败或渲染结果为 `None` 时正文回退原样、不抛错。改动处注释引用 `RFC-0008`。
4. **T4 端到端脚本 + RFC 索引（依赖 T3）** — 新增端到端脚本 **`scripts/e2e-rfc-0008-pr-e2e-signpost.sh`**，沿用既有 e2e 脚本两段式：默认离线段跑 `ruff check` / `ruff format --check` / `pytest`；置 `OPENAGENTS_E2E_REAL=1` + `OPENAGENTS_E2E_ISSUE` 时真实演练 `openagents rfc <issue>` 并断言其 draft PR 正文含「## 端到端验证」段。脚本 `set -euo pipefail` 且 `chmod +x`。在 `docs/rfcs/README.md` 的 RFC 列表追加 RFC-0008 行。

**端到端验证（signpost 提取的脚本即此组的 e2e 脚本）**：`bash scripts/e2e-rfc-0008-pr-e2e-signpost.sh`（默认离线跑 ruff + pytest；真实模式演练 `openagents rfc` 并断言 PR 正文含「## 端到端验证」段）。

依赖 DAG：`T1 → T3`，`T2 → T3`，`T3 → T4`；T1 与 T2 彼此独立、可并行。

## Drawbacks

- 在 PR 正文与 RFC 之间引入一层「约定子段」（`### 集成测试` / `### 手动验证`）的隐式耦合：RFC 若不按这两个子段标题书写，指路牌就抽不到内容（但会优雅降级、不报错）。
- 解析基于 Markdown 文本的轻量约定，而非结构化字段，存在 RFC 写法漂移导致漏抽的可能。

## Rationale and alternatives

- **为什么从 RFC 解析而非在 PR 模板里手填**：验收方式本就该写在 RFC 里（单一事实来源），手填会重复且易漂移；自动解析让「写一次 RFC」即可同时驱动指路牌（DRY、解耦，理念 10）。
- **为什么纯函数 + 全程不抛错**：指路牌是「锦上添花」的辅助信息，绝不能因解析失败而阻塞开 PR；因此 `rfc.py` 设计为无副作用纯模块、所有字段缺失都降级，便于 hermetic 单测覆盖各缺失组合。
- **备选：结构化 frontmatter 字段承载验收信息**。否决（YAGNI）：当前只需脚本路径 + 一行预期两项，限定子段抽取已够轻量；引入额外结构化 schema 是过度设计。
- **备选：在 reviewer agent 侧实时去翻 RFC**。否决：把信息前置到 PR 正文对人和 agent 都更直接，且不依赖 reviewer 侧实现。

## Prior art

将「如何验证 / 如何运行」前置到 PR 正文是业界 PR 模板的常见实践（GitHub PR template 常含 "How to test" 小节）。本 feature 的差异点是：该小节不靠人工填写模板，而是从改动配套的 RFC 自动解析渲染，与 OpenAgents 的 RFC 驱动开发对齐。

## Unresolved questions

无。子段约定（`### 集成测试` / `### 手动验证`）、降级语义、定位规则（首个 `NNNN-*.md` 排除 README）均已在本组确定。

## Future possibilities

- 指路牌可扩展更多字段（如预期截图、关键指标），仍走同一套「RFC 子段 → 渲染」管线。
- 可由 reviewer agent 消费指路牌自动执行 e2e 脚本并把结果作为 comment 回贴 PR。

