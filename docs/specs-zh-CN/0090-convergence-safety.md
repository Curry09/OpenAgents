---
number: "0090"
title: 守夜流程终态与可修复故障收口
issue: 0
slug: convergence-safety
summary: 合并后复核终态并将可修复故障回流到正确阶段，避免误挂和整轮终止
architecture:
  objective: "在现有守夜状态机内闭合动作结果、事实重读和可修复故障回流，避免误挂与整轮停止"
  constraints:
    - "不新增角色、持久化实体或失败预算"
    - "只复用现有 architecture、implement、deliver 和 review 路径"
  non-goals:
    - "不改变真实模型的需求理解能力"
    - "不把平台导出、权限和留存纳入本次代码改动"
  candidates:
    - id: "existing-reconcile-routes"
      layer: "recipes.vigil and runtime.gates"
      boundary:
        - "动作返回"
        - "门禁异常"
        - "终态复核"
      evidence:
        - "故障注入单测"
        - "本地并发压力"
      tradeoffs: "增加一次事实读取，保持状态模型不变"
    - id: "increase-retry-budget"
      layer: "queue worker"
      boundary:
        - "失败重试"
      evidence:
        - "只能延后 round_cap 或 retry_exhausted"
      tradeoffs: "不解决错误路由，拒绝采用"
  selected: "existing-reconcile-routes"
  affected-components:
    - "recipes.vigil"
    - "runtime.gates"
  failure-modes:
    - "合并成功后被 round_cap 覆盖"
    - "设计摘要/生成视图失配重复消耗失败预算"
    - "外部调用异常越过 worker 边界"
verification:
  behavior-cases:
    - id: "merge-terminal"
      polarity: positive
      stimulus: "动作已得到合并成功但下一次远端快照暂时未更新"
      expected: "任务保持完成，不写 round_cap"
      observation: "reconcile 单测"
    - id: "recoverable-gates"
      polarity: positive
      stimulus: "设计摘要或 OVERVIEW 与候选树失配"
      expected: "回流既有评审/交付路径，不重复烧认领预算"
      observation: "门禁类型单测与集成回归"
    - id: "hard-failure-isolation"
      polarity: negative
      stimulus: "不可恢复异常或模型调用失败"
      expected: "仍沿原有有界重试，worker 不退出"
      observation: "全量 pytest 与压力脚本"
  repository-invariants:
    - "只有合并报告成功才写 done"
    - "旧评审标签不会认证新候选"
  exemptions: []
tasks:
  - id: T1
    title: 终态复核与可修复故障回流
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/recipes/vigil.py
      - openagents/runtime/gates.py
      - tests/test_recipe_vigil.py
      - tests/test_recipe_vigil_act.py
      - tests/test_runtime_gates.py
      - scripts/e2e-spec-0090.sh
      - docs/specs/0090-convergence-safety.md
    scope: 修复合并终态误判、设计摘要失配和仓库完整性失配的路由，并补故障注入测试
    acceptance: 合并成功不得写 round_cap；可修复失配不得重复消耗认领预算；全量 pytest 与专项压力通过
---

# 0090 · 守夜流程终态与可修复故障收口

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

代码修改完毕：包括回流调用的超时保护、候选绑定和返工后重新评审。

守夜人在动作之间读取事实、并在轮次上限前复核终态；合并后的成功结果直接收口，不再被上限覆盖。设计摘要
失配和仓库生成视图失配沿现有评审/交付路径回流，不消耗认领失败预算；外部模型传输中断仍由
现有有界重试隔离。此处验证单票故障不会终止 worker，不代表外层实验主循环已获得恢复保证。

## Motivation

实验中出现四类收敛故障：合并已完成却在最后一轮写成 `round_cap`；已通过代码评审但设计摘要
已变化时重复同一门禁；`OVERVIEW.md` 与 Spec 树不一致时重复完整性检查；CLI 响应中断被当成
普通失败。共同根因是动作结果、事实重读和异常路由没有在同一个 reconcile 边界闭合。

## Guide-level explanation

merge 动作返回成功后，编排层接受该动作提供的确定性结果并交还 slot；其它动作在下一轮读取事实，
到顶前再复读一次，已合并/关闭或等待外部时不写失败。设计摘要失配经已有 architecture 重新确认，
清理旧裁决后回到既有 review-or-fix；生成视图失配回到既有
交付修复；只有真正不可恢复的门禁错误才进入原有失败预算。传输错误不改变业务状态，只按现有
认领边界有界重试。

## Reference-level explanation

本修复只修改 `recipes.vigil`、`runtime.gates` 及其测试。新增的异常类型仅用于进程内路由，不落盘、
不新增角色或状态字段。`_reconcile` 在 `_act` 返回 `merged` 后立即结束，并在轮次上限前再做一次
终态感知；`_do_merge` 将设计摘要失配和仓库完整性失配分别标为可回流错误；`_run_claimed` 保持
worker 异常隔离和既有三次预算。

回流仍经现有 `_TimedBackend` 并继承认领锁；设计返工后必须再次获得 architecture PASS，且候选
读取、评审和审批更新绑定同一已推送版本。无变化的修复仍受零进展护栏约束；轮数耗尽时先确认是否
已经完成或进入外部等待，否则保留现有八轮上限，不以清零预算掩盖持续返工。没有新增真实模型传输重试机制；
持续外部故障仍可能令单票有界失败，本规格不保证外层实验监督器永不中止。

### Task DAG

| id | status | scope | files | acceptance |
|----|----|----|----|----|
| T1 | done | 终态复核、可修复门禁路由及故障注入回归 | `openagents/recipes/vigil.py`, `openagents/runtime/gates.py`, `tests/test_recipe_vigil.py`, `tests/test_recipe_vigil_act.py`, `tests/test_runtime_gates.py` | 合并后不再 round_cap；摘要/完整性失配不重复烧预算；全量测试与专项压力通过 |

验收入口：`bash scripts/e2e-spec-0090.sh`。前半段包含本次终态、回流超时封装、实际 PASS、
返工后再评审、候选换版、完整性复检和 worker 隔离测试；后半段复用交付压力入口做并发回归。
后半段不模拟真实模型、外层实验 runner，也不声称其 17 类交付场景覆盖所有本次回流行为。

2026-09-10 最终验证：全量 pytest 1336 passed，专项 266 passed；1/4/8/16 worker、每类混合
故障重复 4 次，共 336 个任务（304 正常/可恢复任务全部合并，32 持续故障按预期停止）。意外结果、
错误候选审批、重复认领、队列残留均为 0。新增回流分支的行为由专项正反例验证，不将既有交付压力
结果冒充真实模型闭环。桌面 HTTP 测试需本地回环端口权限；允许后全量通过。

本次变更文件 Ruff check/format、Spec validate 和 graph 校验通过。全仓仍有改动前已有的 2 个
import 排序错误及 22 个文件格式差异；它们未作为本次运行逻辑修复混入，因此不声明全仓 CI 已绿。
当前测试环境没有 coverage 插件，本次不报告新的覆盖率百分比。GitHub 凭据缺失时不能核对远端
新提交或开放 PR 编号冲突；推送成功和远端 CI 应以实际远端回执为准。

## Drawbacks

合并动作后增加一次轻量事实读取；可修复失配会重新触发既有角色调用，延迟略增，但避免错误挂起
和错误合并。

## Rationale and alternatives

选择复用现有动作、标签和失败预算，只补齐状态机边界。拒绝提高重试次数（只会延后挂起），也拒绝
新增专用恢复队列（引入持久化实体且没有必要）。

## Prior art

沿用 Spec-0065 的 level-triggered reconcile、Spec-0074 的 `MergeNotReady` 暂态收口和 Spec-0089
的候选版本绑定。

## Unresolved questions

无。本任务不改变真实模型能力、平台部署或历史实验归档。

## Future possibilities

后续可把外层实验监督器的重启/恢复纳入同一故障注入矩阵，但本次不新增监督器组件。
