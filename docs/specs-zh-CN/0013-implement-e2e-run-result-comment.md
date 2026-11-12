---
number: "0013"
title: 实跑端到端脚本并把「合否 + 日志」作为 PR 评论（RFC-0008 指路牌 → 实跑结果延伸）
issue: 31
slug: implement-e2e-run-result-comment
summary: 在 PR 转正前真正跑一遍端到端脚本，把「跑通没有 + 日志」作为带签名的 PR 评论贴出来。是 0008 指路牌（告诉怎么测）到实跑结果（直接给结论）的延伸。
tasks:
  - id: T1
    title: e2e 实跑封装 + 结果评论渲染（纯模块）
    status: done
    priority: P1
    tags:
      - dx
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/e2e.py
      - tests/test_e2e.py
    scope: 新建 openagents/e2e.py，实现 E2EResult、run_e2e_script、render_result 及 DEFAULT_TIMEOUT_SECONDS / DEFAULT_TAIL_LINES。在 worktree 内 bash <script_path> 跑离线段、捕获退出码与合并输出、施加超时、截尾部 N 行；脚本缺失 / 非常规文件 / 超时 / 非零退出 各自映射成结构化结果，绝不抛错。模块 docstring 与公开函数引用 RFC-0013。
    acceptance: 单测覆盖——退出码 0→passed；非零→failed 且退出码正确；超时→failed 且 timed_out=True；script_path=None / 文件不存在→skipped 不起子进程；render_result 对四种 outcome 各渲染对应「结果」行与日志块且不抛错。ruff + pytest 通过。
  - id: T2
    title: rfc.script_path_for（复用 extract_e2e 定位脚本）
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
    scope: 在 openagents/rfc.py 新增 script_path_for(*, rfc_path) -> str | None：读文件→extract_e2e→返回 hints.script_path，文件不可读返回 None（不抛错），与既有 signpost_for 对称。docstring 引用 RFC-0013（复用 RFC-0008 的 extract_e2e）。
    acceptance: 单测——含「集成测试」脚本的 RFC 抽出该脚本相对路径；无脚本段时返回 None；文件不可读返回 None 不抛错。不破坏既有 extract_e2e / signpost_for 用例。ruff + pytest 通过。
  - id: T3
    title: implement 转正前实跑 + 签名结果评论接线
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
    scope: 改 orchestrator.implement：import e2e；在 commit_and_push 之后、mark_ready 之前定位脚本（changed_rfc_path + rfc.script_path_for，base=DEFAULT_BASE）→ e2e.run_e2e_script 实跑→ e2e.render_result 渲染→ identity.post_signed_comment 盖章发评论→ github.mark_ready 照常转正。结果 ❌ 不阻断转正；发评论失败仅记进度并吞掉、不崩溃流程。新增/改动处注释引用 RFC-0013。
    acceptance: 单测（假 backend + 假 Workspace + monkeypatch e2e.* / identity.post_signed_comment / github.mark_ready）——implement 在 mark_ready 前调用 run_e2e_script、把渲染结果经 post_signed_comment（带本实例 agent_id）发出；e2e failed 时仍调用 mark_ready；changed_rfc_path 返回 None 时走 script_path=None（skipped）仍发评论且不抛错；发评论抛错时 mark_ready 仍被调用。ruff + pytest 通过。
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
      - scripts/e2e-rfc-0013-implement-e2e-comment.sh
      - docs/rfcs/README.md
    scope: 新增 scripts/e2e-rfc-0013-implement-e2e-comment.sh（两段式：默认离线 ruff check / ruff format --check / pytest；OPENAGENTS_E2E_REAL=1 时人工 opt-in 演练「implement 实跑 + 结果评论」路径）。在 docs/rfcs/README.md 的 RFC 列表追加 RFC-0013 行。
    acceptance: 离线段在干净仓库通过；脚本可执行（set -euo pipefail、chmod +x）；README 列表含 RFC-0013 条目。
---

# 0013 · 实跑端到端脚本并把「合否 + 日志」作为 PR 评论（RFC-0008 指路牌 → 实跑结果延伸）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

在 PR 从 draft 转正（`mark_ready`）之前，真正执行本分支 RFC 声明的端到端脚本，把「跑通没有 + 日志末尾」渲染成一条带 agent 签名的 PR 评论贴出来。这是 RFC-0008 的自然延伸：0008 在 PR 正文加了「端到端验证」指路牌（告诉人怎么测，是指针），本 feature 直接替人把脚本跑一遍并给出确定性「合否」结论（是结果）。新增一个只懂 `subprocess` + 文本处理的纯旁路模块 `e2e.py`，一个在 `rfc.py` 上对称补齐的 `script_path_for` 定位器，并把两者接到 `orchestrator.implement` 的转正前一刻。

## Motivation

**现状（RFC-0008 指路牌，完整复述，不要求读者去翻别的 spec）。** RFC-0008 让 PR 正文里带一段「端到端验证」指路牌：从本分支改动的 RFC 文档里抽出「集成测试」段，把其中声明的 `scripts/*.sh` 脚本路径渲染进 PR 正文，告诉审阅者/人「要验证这个改动，跑这个脚本」。它给的是**指针**——一个让人手动去跑的路标，PR 本身并不包含「这次到底跑通没有」的结论。

**问题：为什么要改。** 「以成果为中心」（CLAUDE.md 理念 8）要求模型替人做端到端测试，人只面向成果。光给指路牌不够：审阅者仍要亲自把脚本跑一遍才知道合否，门控成本落回人身上。期望的新行为是——`implement` 在把 PR 转正之前，**自己把脚本跑一遍**（离线确定性段：ruff + pytest，全程 mock），把退出码映射成「跑通 / 跑挂 / 无脚本可跑」，连同日志末尾一起，作为一条带签名的评论发到 PR 上。于是 PR 自带「这次实跑的结论」，人只需看结论而非重跑。结果 ❌ 不阻断转正（信息透明优先于硬门控），但人看到失败评论后可介入。

## Guide-level explanation

把 RFC-0008 的「指针」升级为「结论」，新增一格：

| 维度 | 现状（RFC-0008 指路牌） | 本 feature（实跑结果延伸） |
|------|------|------|
| PR 携带的 e2e 信息 | 脚本路径（指针，让人去跑） | 脚本路径 + **这次实跑的合否 + 日志末尾**（结论） |
| 谁跑脚本 | 人（手动按指路牌跑） | **`implement` 转正前自动跑离线段** |
| 信息载体 | PR 正文一段指路牌 | PR 正文指路牌 + **一条带 agent 签名的结果评论** |

对使用者：照常提 issue、让 agent 起 PR；当 agent 跑 `implement` 把 PR 转正时，PR 上会自动多出一条「## 端到端测试结果」评论，写明 passed / failed / skipped 与日志末尾若干行，并带本 agent 实例的签名。脚本缺失或没声明时评论降级为 skipped（指回 RFC「集成测试」段供人工验证），不会让流程崩溃。

## Reference-level explanation

落到改动，分解为 4 个 Task（DAG 见下；`files` 互斥，各 Task 单一 writer）：

1. **T1 e2e 纯模块** — 新建 `openagents/e2e.py`，只懂 `subprocess` + 文本处理，不感知 git / GitHub / RFC 文档语义 / orchestrator（理念 10 解耦）。对外暴露：`E2EResult`（实跑结果的结构化载体）、`run_e2e_script`（在 worktree 内 `bash <script_path>` 跑离线段、捕获退出码与合并输出、施加超时 `DEFAULT_TIMEOUT_SECONDS=600`、截尾部 `DEFAULT_TAIL_LINES=40` 行）、`render_result`（把结果渲染成「## 端到端测试结果」Markdown，纯函数）。四种 outcome：退出码 0→`passed`；非零→`failed`；超时→`failed` 且 `timed_out=True`；脚本缺失 / 非常规文件 / `script_path=None`→`skipped`（不起子进程）。全程**绝不抛错**——所有异常路径都映射成结构化结果。
2. **T2 rfc.script_path_for** — 在 `openagents/rfc.py` 新增 `script_path_for(*, rfc_path) -> str | None`：读文件→复用 RFC-0008 的 `extract_e2e`→返回 `hints.script_path`，文件不可读返回 `None`（不抛错），与既有 `signpost_for` 对称。仅做定位，不实跑（解耦：定位归 rfc，实跑归 e2e）。
3. **T3 implement 接线**（依赖 T1、T2） — 改 `orchestrator.implement`：`import e2e`；在 `commit_and_push` 之后、`mark_ready` 之前，用 `changed_rfc_path`（`base=DEFAULT_BASE`）+ `rfc.script_path_for` 定位脚本→`e2e.run_e2e_script` 实跑→`e2e.render_result` 渲染→`identity.post_signed_comment`（带本实例 `agent_id`）盖章发评论→`github.mark_ready` 照常转正。e2e 结果 ❌ 不阻断转正；发评论失败仅记进度并吞掉、不崩溃流程；`changed_rfc_path` 为 `None` 时走 `script_path=None`（skipped）仍发评论。
4. **T4 端到端脚本 + 索引**（依赖 T3） — 新增 `scripts/e2e-rfc-0013-implement-e2e-comment.sh`，两段式：默认离线确定性段（`ruff check` / `ruff format --check` / `pytest`，全程 mock 不触达真实 gh）；`OPENAGENTS_E2E_REAL=1` 且给定 `OPENAGENTS_E2E_PR=<n>` 时人工 opt-in 演练真实「implement 实跑 + 结果评论」路径。脚本 `set -euo pipefail` 且 `chmod +x`。在 `docs/rfcs/README.md` 的 RFC 列表追加 RFC-0013 行。

**端到端验证**：`bash scripts/e2e-rfc-0013-implement-e2e-comment.sh`（默认仅离线段：ruff + pytest）。

依赖 DAG：`T1 → T3`，`T2 → T3`，`T3 → T4`。T1 与 T2 互相独立、可并行。

## Drawbacks

- `implement` 转正前多跑一遍离线段（ruff + pytest），转正路径变长——但有 `DEFAULT_TIMEOUT_SECONDS=600` 超时上限保护，不会被拖死。
- e2e 失败不阻断转正，结果评论是「软信号」而非硬门控，需要人留意失败评论；选择信息透明而非硬卡点是有意为之（见 Rationale）。

## Rationale and alternatives

- **为什么实跑而非继续只给指路牌**：理念 8「以成果为中心」要求模型替人做端到端测试。只给指针仍把跑脚本的成本压在人身上；实跑并贴结论才真正把这层验证从人手里接过来。
- **为什么 e2e 失败不阻断转正**：硬门控会把「脚本环境抖动 / 暂未落地」也变成卡死流程的硬错误；选择把结果作为带签名评论透明贴出（passed/failed/skipped），保留人介入空间，又不让流程崩在一个旁路验证上。
- **为什么 e2e.py 做成纯旁路模块**：只依赖 `subprocess` + 文本，不感知 git/GitHub/RFC/orchestrator（理念 10 解耦），便于 hermetic 单测、可被任意调用方复用。
- **为什么定位（rfc.script_path_for）与实跑（e2e.run_e2e_script）分离**：定位需要懂 RFC 文档语义（复用 0008 的 `extract_e2e`），实跑只需懂 subprocess；分开后两边各自单测、互不耦合。
- **备选：把渲染结果写进 PR 正文而非评论**。否决：正文是 0008 指路牌的领地（静态指针），实跑结论是一次性时间点事件，作为带签名评论更贴合「每次实跑一条记录」且不覆盖正文。

## Prior art

「CI 把测试合否与日志摘要作为 PR 状态/评论回贴」是业界主流实践（如各类 CI 机器人在 PR 上贴 check 结果 + 失败日志摘要）。本 feature 取其「在转正前自动跑、把合否 + 日志末尾回贴到 PR」的核心，落在 OpenAgents 的 agent 签名评论机制上，不引入外部 CI 服务。

## Unresolved questions

无。四种 outcome 映射、超时上限、日志截尾行数、失败不阻断转正均已在本组确定。

## Future possibilities

- 把实跑从「离线确定性段」扩展到可配置的真实段（当前真实段需人工 `OPENAGENTS_E2E_REAL=1` opt-in）。
- 结果评论可累积成 PR 的实跑历史时间线 / 趋势。

