---
number: "0012"
title: test 分支门控流程 —— 人只在「提 issue」与「promote」介入
issue: 32
slug: test-branch-gated-flow
summary: 改成 test 分支门控流程，人只在「提 issue」和「promote 上线」两处介入：N 个 reviewer 并行评审聚合裁决，promote 模块预检后快进 main，中间全自动。
tasks:
  - id: T1
    title: reviewer 编排模块（N 并行 + 裁决聚合）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/reviewer.py
      - tests/test_reviewer.py
    scope: 新建 reviewer.py：ReviewDecision 数据模型、review() 函数（线程池并行派 N 个 backend.run、解析每个 AgentResult.summary 的裁决 token、聚合「全票 PASS」）；内置 rfc/code 两套 review 任务模板（移植 vigil-reviewer 的 PASS/REWORK/RETHINK rubric）；N 从 OPENAGENTS_REVIEWERS(默认1) 读取。
    acceptance: 单测打桩 AgentBackend，覆盖：N=1 PASS→passed=True；N=3 含一个 REWORK→passed=False 且 feedback 含该反馈；RETHINK 同 REWORK 归为非 PASS；裁决 token 解析鲁棒（大小写/前后缀）。
  - id: T2
    title: github 扩展（base/merge/label/branch）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - tests/test_github.py
    scope: create_pr 增 base 形参（→ --base）；新增 merge_pr、add_label、ensure_branch（幂等）、branch_ci_green。复用 _run_gh/_gh_json（RFC-0010 重试）与既有 _classify_checks。
    acceptance: 单测打桩子进程，验证各函数拼出正确 gh 参数；ensure_branch 在分支已存在时不报错（幂等）；branch_ci_green 全绿→True、有失败→False；create_pr(base=...) 透传 --base。
  - id: T3
    title: state 扩展（rounds + STATUS_BLOCKED）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
    scope: 新增 STATUS_BLOCKED 常量；RunRecord 加 rounds:int=0（默认值保证 RunRecord(**旧记录) 不报错）；新增 increment_rounds/reset_rounds。
    acceptance: 单测：加载缺 rounds 键的旧 state.json 不抛错且 rounds=0；increment_rounds 返回递增值并落盘；reset_rounds 归零；STATUS_BLOCKED 不被 all_runs 误改。
  - id: T4
    title: promote 模块（预检 + 快进 main）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/promote.py
      - tests/test_promote.py
    scope: 新建 promote.py：PromoteResult + promote()，执行预检（无 STATUS_BLOCKED run ∧ 无 needs-human open PR ∧ branch_ci_green(test)），通过则 ensure_branch 兜底 + git push origin test:main。
    acceptance: 单测打桩 github/state/子进程：有 BLOCKED run→promoted=False 且 reason 指明；有 needs-human PR→False；CI 非绿→False；全通过→执行 push 并 promoted=True。
  - id: T5
    title: 闸接入（messages 路由 + orchestrator 评审/base）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/messages.py
      - openagents/orchestrator.py
      - tests/test_messages.py
      - tests/test_orchestrator.py
    scope: orchestrator：DEFAULT_BASE="test"、start_rfc 透传 base 给 create_pr、新增 review_rfc/review_code、implement 末尾 reset_rounds。messages：_process_rfc_review/_process_coding 接入评审闸（PASS→加标签/merge、非 PASS→rounds++ 后 refine/iterate、超 K→BLOCKED+needs-human），新增 MAX_ROUNDS/BLOCKED_LABEL。
    acceptance: 单测打桩 reviewer/github/state：rfc 闸 PASS→打 rfc-approved 并 implement；rfc 闸非 PASS 且 rounds<K→refine 且 rounds++；coding 闸 CI 绿+PASS→merge_pr+DONE+rebase；coding 闸非 PASS 超 K→STATUS_BLOCKED+needs-human 且 PR 不关；CI fail/pending 行为保持。
  - id: T6
    title: CLI/vigil 接线（promote 命令 + base 默认 + init 兜底）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
    depends-on:
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - openagents/vigil.py
      - tests/test_cli.py
      - scripts/e2e-rfc-0012-gated-flow.sh
    scope: cli：rfc/vigil 的 --base 默认改 test；_cmd_init 调 ensure_branch；注册 promote 子命令 + _cmd_promote。vigil：默认基线随之为 test。补 e2e 脚本。
    acceptance: 单测：promote 子命令路由到 promote.promote 并按结果设退出码；--base 默认值为 test；init 触发 ensure_branch。e2e 脚本可独立运行（见测试方案）。
---

# 0012 · test 分支门控流程 —— 人只在「提 issue」与「promote」介入

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

> **⚠️ 本 spec 已被 Spec-0023 取代（test 分支退役）。** 本文件是「test 分支门控流程」时代的历史
> 设计快照：彼时 `test` 是长期体验服、issue→PR 全程以 test 为 base 自动合回 test，`main` 只被
> `openagents promote` 快进。Spec-0023 将此模型反转——`main` 成为日常自动流转分支并持续推进，
> 发版改走 `release/vX.Y.Z` 分支 + tag（`openagents release` 取代 promote）。其 T2/T4/T5/T6 经
> `supersedes` 分别取代本 spec 的 T2（github base）、T4（promote 模块）、T5（orchestrator base）、
> T6（CLI/base）。本文件保留作历史参照，不再反映现状代码。

把 OpenAgents 的交付流程改造为「test 分支门控流程」，让人只在两个触点介入：**「提 issue」** 与 **「promote 上线」**。`test` 是一条长期存在的体验服分支；issue→PR→评审→合回 test 中间全自动。每个 PR 由 N 个 reviewer 并行评审、裁决聚合为「全票 PASS」后才放行；reviewer/CI 闸全过即自动合回 `test`，非 PASS 则自动迭代，超过轮数上限则挂起并打 `needs-human`。`main` 平时冻结，仅在人执行 `openagents promote`（预检三条全过）时被从 `test` 快进一次。

## Motivation

在本 feature 之前，人需要在代码细节层面反复介入：逐个 PR 判断要不要合、什么时候上线。目标是把人的触点收敛到 **宏观把控** 两点——决定「做什么」（提 issue）和「上不上线」（promote），中间的评审/合并/迭代全部自动化（符合 OpenAgents「人做宏观把控、不再负责细节」的目标）。

为达成此目标，本组确立并固化以下决策（被其它 spec 以「见 Spec-0012 决策 N」引用，故此处完整复述，使其自包含）：

- **决策 1（双触点门控模型）**：人只在「提 issue」与「promote」两处介入。issue 被领取后从 `test` 切出工作树、起草改动、开 PR；PR base 锁定 `test`。评审+CI 全过自动合回 `test`，于是 `test` 持续累加为「最新可体验」版本。
- **决策 2（N 并行评审 + 全票 PASS 聚合）**：每个 PR 派 N 个 reviewer（线程池并行 `backend.run`），各自产出 PASS/REWORK/RETHINK 裁决；聚合规则是「全票 PASS 才算通过」，任一 REWORK/RETHINK 即非 PASS 并回收其 feedback。N 由环境变量 `OPENAGENTS_REVIEWERS`（默认 1）控制。rfc 评审与 code 评审各有一套 review 任务模板（移植自 vigil-reviewer 的 rubric）。
- **决策 3（轮次上限 + 自动挂起）**：非 PASS 时不立即放弃，而是 `rounds++` 后自动 refine（rfc 阶段）/iterate（coding 阶段）；超过上限 `MAX_ROUNDS`（K）则把 run 置 `STATUS_BLOCKED` 并给 PR 打 `needs-human` 标签、**不关闭 PR**，交人接手。`rounds` 计数随 `implement` 成功而 `reset_rounds` 归零。
- **决策 4（promote 三条预检 + 快进语义）**：`promote` 前跑三条预检，全过才扬升——① 没有挂起（`STATUS_BLOCKED`）的 run；② 没有打了 `needs-human` 标签的 open PR；③ `test` 分支 HEAD 的 CI 全绿。通过后以 `git push origin test:main` 把 `main` **快进**（fast-forward）到 `test`，`main` 平时冻结、只此一处前进。
- **决策 5（全链路 base 默认 test + test 分支自举）**：全链路 base 默认值（`orchestrator.DEFAULT_BASE`、`cli` 的 `--base`、`github.create_pr` 的 `base`）统一为 `"test"`；冷启动时 `init`/`ensure_prerequisites` 通过幂等的 `ensure_branch` 兜底创建 `test` 分支，避免全新仓库缺 `test` 导致 prepare 永久失败。

> 注：上述决策中与 base/promote/自举相关的部分（决策 4、决策 5）已被 Spec-0023 反转——`main` 改为日常自动流转分支、发版改走 `release/vX.Y.Z` + tag。此处复述仅为保留历史语义供回溯引用。

## Guide-level explanation

三个角色的分工如下表（这是 Spec-0023 后来反转的对象）：

| 角色 | 本 spec（test 门控时代） |
|------|------|
| 日常自动流转分支（issue→PR 的 base、自动合入目标） | `test`（体验服） |
| 人工门控的发布目标 | `main`（被 promote 快进） |
| 人的门控触点 | 提 issue + `promote` |

对使用者：平时提 issue，agent 自动从 `test` 切出、起草、开 PR、跑 N 路评审，PASS+CI 绿就自动合回 `test`；遇到反复改不好的会挂起并打 `needs-human` 等人。想上线时跑一次 `openagents promote`，它预检三条全过后把 `main` 快进到 `test`。

## Reference-level explanation

落到改动，分解为 6 个 Task（DAG 见下；`files` 互斥，各 Task 单一 writer）：

1. **T1 reviewer 编排模块**（无依赖） — 新建 `reviewer.py`：`ReviewDecision` 模型 + `review()`（线程池并行派 N 个 `backend.run`、解析每个 `AgentResult.summary` 的裁决 token、聚合「全票 PASS」），内置 rfc/code 两套模板（移植 vigil-reviewer 的 PASS/REWORK/RETHINK rubric），N 读 `OPENAGENTS_REVIEWERS`（默认 1）。落实决策 2。
2. **T2 github 扩展**（无依赖） — `create_pr` 增 `base` 形参（→`--base`）；新增 `merge_pr`、`add_label`、`ensure_branch`（幂等）、`branch_ci_green`；复用 `_run_gh`/`_gh_json`（RFC-0010 重试）与 `_classify_checks`。是决策 4/5 的能力底座。
3. **T3 state 扩展**（无依赖） — 新增 `STATUS_BLOCKED` 常量；`RunRecord` 加 `rounds:int=0`（默认值保证 `RunRecord(**旧记录)` 向后兼容）；新增 `increment_rounds`/`reset_rounds`。支撑决策 3 的轮次计数与挂起态。
4. **T4 promote 模块**（依赖 T2、T3） — 新建 `promote.py`：`PromoteResult` + `promote()`，预检三条（无 `STATUS_BLOCKED` run ∧ 无 `needs-human` open PR ∧ `branch_ci_green(test)`）全过则 `ensure_branch` 兜底 + `git push origin test:main`。实现决策 4。
5. **T5 闸接入**（依赖 T1、T2、T3） — `orchestrator`：`DEFAULT_BASE="test"`、`start_rfc` 透传 base 给 `create_pr`、新增 `review_rfc`/`review_code`、`implement` 末尾 `reset_rounds`；`messages`：`_process_rfc_review`/`_process_coding` 接入评审闸（PASS→加标签/merge、非 PASS→`rounds++` 后 refine/iterate、超 K→`STATUS_BLOCKED`+`needs-human`），新增 `MAX_ROUNDS`/`BLOCKED_LABEL`。把决策 1/2/3 接成自动闭环。
6. **T6 CLI/vigil 接线**（依赖 T4、T5） — `cli`：`rfc`/`vigil` 的 `--base` 默认改 `test`、`_cmd_init` 调 `ensure_branch` 兜底、注册 `promote` 子命令 + `_cmd_promote`；`vigil` 默认基线随之为 test；补 e2e 脚本。收口决策 5 的 base 默认与 test 自举，并把 promote 暴露为人的触点。

**端到端验证**：`bash scripts/e2e-rfc-0012-gated-flow.sh`（离线跑 ruff + pytest，演示 base=test 门控流 + promote 快进 main）。

依赖 DAG：`T2 → T4`，`T3 → T4`，`T1 → T5`，`T2 → T5`，`T3 → T5`，`T4 → T6`，`T5 → T6`。T1/T2/T3 无依赖、可并行起步。

## Drawbacks

- `main` 长期冻结、只靠人 `promote` 前进，人被绑在「每次上线」这个细节决策上（这正是 Spec-0023 反转此模型的动因）。
- 多了一条长期 `test` 分支与其自举逻辑（`ensure_branch` 兜底），冷启动路径上多一层概念。
- N 并行评审会放大每个 PR 的 backend 调用成本（N 倍 `backend.run`）。

## Rationale and alternatives

- **为什么用 test 体验服而非直接合 main**：当时希望 `main` 保持「已上线」语义、由人显式 promote 把关，`test` 充当「最新可体验」缓冲带。（后被 Spec-0023 判定为多余的中介而反转。）
- **为什么全票 PASS 聚合而非多数票**：评审是质量门，宁可保守——任一 reviewer 给出 REWORK/RETHINK 都触发迭代，避免「多数通过但少数发现真问题」被淹没。
- **为什么 promote 用 fast-forward push 而非 merge**：`main` 只追 `test`、不产生独立提交，保证 `main` 是 `test` 的子集、历史线性、可直接回退。
- **备选：人逐 PR 手动 merge**。否决：与「人只做宏观把控」的目标相悖，中间环节应自动化。
- **轮次上限 + 挂起而非无限重试**：避免 agent 在改不好的 PR 上空转，超 K 轮即交人（`needs-human`），把人的注意力导向真正卡住的少数 PR。

## Prior art

- 「体验服/staging 分支 + 人工 promote 到生产」是常见的分支发布模型。
- N 并行评审 + 裁决聚合移植自 vigil-reviewer 的 PASS/REWORK/RETHINK rubric。
- `gh` 调用的重试封装沿用 RFC-0010 既有 `_run_gh`/`_gh_json`。

## Unresolved questions

无。评审聚合规则、轮次上限语义、promote 三条预检均已在本组确定（后续的 base/发布模型变更见 Spec-0023）。

## Future possibilities

- 评审 reviewer 数 N 与轮次上限 K 可扩展为按仓库/按 spec 可配置策略。
- promote 预检可加入更多门槛（如最低覆盖率）。
- （已实现于 Spec-0023）把「test 体验服 + promote 快进」反转为「main 持续推进 + release 版本分支」。

