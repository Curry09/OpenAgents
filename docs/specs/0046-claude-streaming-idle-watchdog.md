---
number: "0046"
title: Claude 静默超时与共享调用时间预算
issue: 148
slug: claude-streaming-idle-watchdog
summary: Claude 按连续无输出期限停止调用；Vigil 与 Claude 共用既有总时长配置，分别记录长时间无输出和预算耗尽，保留现有终止与有界重试流程。
e2e:
  intent: 验证静默终止、活跃流预算耗尽、Vigil 与后端预算一致、关闭预算以及进程归属和重排队兼容性。
  method: |-
    bash scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh
    使用假 Popen、真实线程和受控事件，不调用真实模型或远端仓库；验证默认、覆写、非法值与关闭配置，
    以及总时长到点和长时间无输出分别留下真实原因。持续输出不续时，未完成不算交付成功。
tasks:
  - id: T1
    title: backend 看门狗与 Vigil 共用时间预算
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backends/base.py
      - openagents/backends/claude_code.py
      - openagents/recipes/vigil.py
    scope: 代码修改完毕。将既有总时长读取移入公共后端层，Vigil 两个派发入口复用；保留静默计时、终止、锁与重试流程，仅统一配置和纠正终止原因。
    acceptance: Vigil 不再用固定 1800 秒覆盖配置；预算关闭时不立即超时；总时长耗尽不称为挂死；静默只说明长时间无输出。
  - id: T2
    title: hermetic 回归与离线验证入口
    status: done
    priority: P1
    tags: []
    depends-on: [T1]
    relates-to: []
    parallel: false
    files:
      - tests/test_backend_claude_code.py
      - tests/test_recipe_vigil_act.py
      - tests/test_recipe_vigil.py
      - scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh
    scope: 代码修改完毕。验证配置确实到达派发路径、关闭语义、健康流输出兼容性、两类终止原因，以及已有进程归属、锁和有界重试。
    acceptance: 定向 pytest、Ruff、spec 校验通过；无需真实模型或长时间等待；不宣称已测得生产完成率或成本收益。
---

# 0046 · Claude 静默超时与共享调用时间预算

## Summary

保留两种已有机制：静默期限用于发现长时间无输出，总时长预算用于限制单次调用投入。
Vigil 与 Claude 后端共用既有 `OPENAGENTS_CLAUDE_MAX_WALL` 配置，取消 Vigil 独立的
1800 秒常量。到达总时长只说明预算耗尽，不证明 agent 挂死；持续输出也不证明有效推进。

## Motivation

较大开发任务可能同时承担实现、测试与主干集成。此前 Claude 后端默认允许 3600 秒，
Vigil 却在外层固定 1800 秒终止，导致仍有活动的调用被提前结束并误称为挂死。
本次统一配置与原因表述，继续使用现有调度、工作区和有界重试；不增加进展评分、
软预算收尾、交接摘要或续做状态。

## Guide-level explanation

| 配置 | 默认 | 含义 |
|---|---|---|
| `OPENAGENTS_CLAUDE_IDLE_TIMEOUT` | 300 秒 | Claude 连续无新输出的期限 |
| `OPENAGENTS_CLAUDE_MAX_WALL` | 3600 秒 | Claude 及 Vigil 包装调用共用的单次总时长预算 |

总时长变量保留原名兼容已有部署，在 Vigil 中适用于其包装的所有后端调用；独立的非
Claude 后端不因此新增看门狗。未配置、空白或非法值使用默认；有限值小于等于零关闭
相应限制。总时长的 NaN/Infinity 视为非法值，不把坏配置变成无限运行或立即终止。

例如设 `OPENAGENTS_CLAUDE_MAX_WALL=5400` 后，Vigil 和 Claude 都使用 5400 秒预算；
设置为零则同时关闭这两处总时长限制，Claude 静默期限仍独立生效。
默认 Vigil 单次上限由 1800 秒变为 3600 秒，会允许更长运行，也可能增加低效任务成本。
预算按调用计时，不因新输出或新工具活动而重置；不是单 issue 的累计预算。

## Reference-level explanation

`backends.base.effective_max_wall()` 是总时长配置的唯一读取源；Claude 模块保留同名
导出及 `MAX_WALL_ENV` 兼容调用方。Vigil 的准入和执行入口均使用此访问器构造已有
`_TimedBackend`。关闭预算时 `thread.join` 无期限等待，仍执行原进程跟踪和锁登记。

两层计时范围保持原状：Vigil 覆盖整个 `backend.run`，Claude 覆盖其流式调用；相同
额度下外层可能先结束，但不再存在隐藏的更短额度。终止与清理仍有已有的调度/回收延迟。
静默计时仍按每个输出行刷新（包括空行），不将其升级为有效进展判定。

终止原因明确区分：

- 静默看门狗：长时间无输出；不推断死锁或没有有效工作。
- 总时长看门狗及 `_ActTimeout`：本次调用时间预算耗尽；不推断挂死或任务已完成。

异常类型、进程认领与终止、flock、attempt 次数和重排队流程保持现状。后端异常沿
原通路记录，Vigil 的总预算异常也沿既有有界重试处理，达到重试上限后收口。
终止仍是尽力而为，本组不新增恢复保证，也不把超时当成验收通过。

## Drawbacks

默认允许更长运行会增加部分任务占槽时间。静默可能来自安静的长操作；持续输出可能
来自循环。两种期限都是运行策略，不能单独证明任务质量。关闭总预算是显式配置行为，
不由框架因观察到活动而自动关闭。

## Rationale and alternatives

复用已有配置、读取接口和异常路径，解决隐藏上限与原因误报。自动分段续做会引入上下文
交接成本和新的恢复状态，进展评分会引入误判；本组不需要这些机制。

## Prior art

原 0046 引入 Claude 流式静默看门狗和总时长上限；0065 的 Vigil 包装器跟踪并终止本次
调用所属进程，持有者负责队列收尾。本次将两个已有总时长入口接到同一配置，不替换它们。

## Unresolved questions

更合适的预算值应依据真实任务耗时和资源成本决定；定向回归只验证机制和兼容性。
与历史实验比较时需记录实际配置，不能将增加预算带来的收益直接归因于 harness 改进。

## Future possibilities

若统一预算后仍有可复现的恢复损失或无效循环，再针对具体证据独立设计；不预先增加实体。
