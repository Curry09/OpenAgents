---
number: "0063"
title: state 归一：折叠旧 State 进 RuntimeState 并删 state.py，flat 层收敛为 cli+__init__
issue: 145
slug: state-converge
summary: 承接 Spec-0062 两栈合一收尾：把旧 openagents/state.py 仍存活的三处生产读（agent_id 存储 / ui_capable 存储 / release+board 的 all_runs+RunRecord）迁到新栈 runtime.RuntimeState，STATUS_* 与 BLOCKED_LABEL/PR 改由权威源（runtime + utils.github）供给，随后删掉 state.py——flat 顶层最终仅剩 cli.py + __init__.py。因 .openagents/ 全 gitignore、state 文件为本地临时态，无需数据迁移。
tasks:
  - id: T1
    title: RuntimeState 扩容：agent_id/ui_capable 顶层存取 + 权威 STATUS_* 常量
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/runtime/state.py
      - tests/test_runtime_state_converge.py
    scope: 给 runtime.RuntimeState 补旧 State 独有、但仍被生产读的两组顶层存取：get_agent_id/set_agent_id、get_ui_capable/set_ui_capable（落进 runtime-state.json 顶层键，与 runs/cursors 平级）；并在 runtime 层定义权威 STATUS_* 常量（solving/rfc-review/pr-open/iterating/done/closed/blocked），作为 release 及后续消费方的唯一状态词表来源（旧 state.py 的同名副本随之退役）。additive，不动现有 runs/cursors 行为。
    acceptance: RuntimeState 提供 get/set_agent_id 与 get/set_ui_capable（hermetic 可测，落盘顶层键）；runtime 暴露公共 STATUS_*；现有 runs/cursors 测试不回归；ruff 绿。
  - id: T2
    title: identity 改接 RuntimeState（agent_id 存储）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/utils/identity.py
      - tests/test_identity.py
    scope: 把 utils.identity 里对旧 State 的依赖（类型注解 + get_agent_id/set_agent_id 调用）改为 runtime.RuntimeState；resolve_agent_id 经 RuntimeState 存取本实例签名。
    acceptance: identity 不再 import openagents.state；agent_id 幂等解析行为不变；test_identity 全绿；ruff 绿。
  - id: T3
    title: release + results/board 改接 RuntimeState + utils.github
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/utils/release.py
      - openagents/utils/results.py
      - tests/test_release.py
      - tests/test_results.py
    scope: release：all_runs()→list_runs()（dict 记录），STATUS_BLOCKED 改从 runtime 权威源、BLOCKED_LABEL 改从 utils.github；挂起预检语义不变。results/board：RunRecord→RuntimeState dict，render 只呈现新记录实有字段（issue_number/status/branch/pr_number/closed_at，pr_url 由 pr_number 派生或省略），退役旧栈专属列（rounds/fingerprint 等）。
    acceptance: release/board 不再 import openagents.state；release 挂起阻断行为不变；board 渲染 RuntimeState 记录；test_release/test_results 全绿；ruff 绿。
  - id: T4
    title: CLI 去 _state_for：ui_capable/agent_id/board/release 全走 RuntimeState
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: 删 cli._state_for 工厂与 from openagents.state import State；_persist_ui_capable、_agent_id_for、board、release 四条路径全部经 _new_runtime_state_for 拿 RuntimeState。cli 顶层不再有对 openagents.state 的任何 import。
    acceptance: oa 全命令解析并分发；cli 无 import openagents.state；ui_capable/agent_id 经 RuntimeState 存取；test_cli 全绿；ruff 绿。
  - id: T5
    title: 删 state.py + 收敛 state 测试 + docs 再生成
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
      - tests/test_state_closed_at.py
      - tests/test_state_code_fingerprint.py
    scope: 删除 openagents/state.py（其 BLOCKED_LABEL/PR 再导出的残余消费方改直连 utils.github）；删/重写 9 个 test_state*.py（行为已迁 RuntimeState 的删，仍有价值的迁到 test_runtime_*）；flat 顶层最终仅剩 cli.py+__init__.py。spec render/graph 再生成 OVERVIEW/ARCHITECTURE。
    acceptance: openagents/ 顶层仅 cli.py+__init__.py；全库 grep 对 openagents.state 的 import 零命中；全量 pytest 绿；spec validate 无 error；OVERVIEW/ARCHITECTURE drift-free。
---

# 0063 · state 归一：折叠旧 State 进 RuntimeState 并删 state.py，flat 层收敛为 cli+__init__

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

Spec-0062 已把编排/判断类旧模块删净、原语物理搬进 `utils`，flat 顶层收敛到只剩三个文件：`cli.py`、`__init__.py`、`state.py`。本 spec 收掉最后一个——把旧 `openagents/state.py`（`State` 类 + `RunRecord` + `STATUS_*` 词表）**仍存活的三处生产读**迁到新栈 `runtime.RuntimeState`，权威常量改由 `runtime` 与 `utils.github` 供给，随后**删掉 `state.py`**。flat 顶层最终只剩 `cli.py` + `__init__.py`，state 从此单一模型、单一落盘文件（`runtime-state.json`），彻底两栈合一。因 `.openagents/` 全程 gitignore、state 文件是本地临时态，**无需数据迁移**。

## Motivation

现状：项目里并存**两个 state 模型**。旧 `openagents/state.py`（440 行）的 `State` 有一个 15 字段的富 `RunRecord`（issue/pr/status/summary + rounds/review_invalid/block_gate/merge_attempts/fingerprint 等一堆旧栈跨轮计数器），落盘 `.openagents/state.json`（`runs` 是 list、按 issue 去重）。新栈 `runtime/state.py`（116 行）的 `RuntimeState` 只留 status/branch/pr_number(/closed_at) 四键，落盘 `.openagents/runtime-state.json`（`runs` 是按 issue_number 索引的 dict）。Spec-0062 已让所有新栈 recipe（rfc_lifecycle/merge_pr/vigil/poll_comments）走 `RuntimeState`，并**有意丢弃**那些跨轮计数器（新栈无 MAX_ROUNDS 预算，见 merge_pr/vigil 注释）。

问题：`state.py` 之所以还没删，是因为**三处生产读仍绑在旧 `State` 上**，且新栈无等价物——
1. **agent_id 存储**：`utils.identity.resolve_agent_id`（经 `cli._agent_id_for`）用 `State.get_agent_id/set_agent_id` 存本实例签名（`.openagents/state.json` 顶层 `agent_id` 键）。`RuntimeState` 没有顶层 agent_id。
2. **ui_capable 存储**：`cli._persist_ui_capable` 用 `State.set_ui_capable` 固化 e2e 能力状态量（顶层 `ui_capable` 键）。`RuntimeState` 没有。
3. **release + board**：`utils.release` 用 `State.all_runs()` + `RunRecord.status==STATUS_BLOCKED` 做发布前挂起预检；`utils.results.board` 用 `all_runs()` + `RunRecord` 字段渲染成果看板。二者还依赖 `state.py` 再导出的 `BLOCKED_LABEL` 和只在 `state.py` 定义的 `STATUS_BLOCKED`。

只要这三处还读旧 `State`，`state.py` 就删不掉，flat 层就停在「两栈合一差最后一步」的中间态——认知上要记「新栈用 RuntimeState、但发布/看板/签名还偷偷用旧 State」，落盘上要同时维护 `state.json` 和 `runtime-state.json` 两个文件。本 spec 就是收掉这最后一步。

## Guide-level explanation

迁移完成后，state 只有一个模型 `runtime.RuntimeState`、一个文件 `runtime-state.json`：
- **agent_id / ui_capable**：升级成 `RuntimeState` 的顶层存取（`get/set_agent_id`、`get/set_ui_capable`），和 `runs`/`cursors` 平级落进 `runtime-state.json`。`identity` 与 `cli` 改调它。
- **状态词表**：`STATUS_*`（solving/rfc-review/pr-open/iterating/done/closed/blocked）在 `runtime` 层定一份**权威公共常量**，`release` 从这里拿 `STATUS_BLOCKED`。（新栈各 recipe 现有的 module-private `_STATUS_*` 字面量本 spec 不强行收编，避免范围外扩；权威源就位后它们可在后续自然收敛。）
- **release / board**：`all_runs()`（返回 `RunRecord`）换成 `list_runs()`（返回 dict）；`BLOCKED_LABEL` 直连 `utils.github`；board 的渲染退役旧栈专属列（rounds/fingerprint 等旧计数器新记录里根本没有），只呈现新记录实有字段。
- **`state.py` 删除**：其唯一还在被外部依赖的两个再导出 `BLOCKED_LABEL`/`PR` 本就权威定义在 `utils.github`，残余消费方改直连即可。

对用户/agent 行为**零可见变化**：签名幂等、发布挂起阻断、看板呈现语义都保持；变的只是这些数据从哪个模块、哪个文件读写。

## Reference-level explanation

**分界线不变**：state 是确定性存储原语，归 `runtime`（机制层），非 agent 判断。本 spec 是纯机械归一，无新判断下放。

**无数据迁移**：`.gitignore:17` 忽略整个 `.openagents/`，`state.json`/`runtime-state.json` 都是本地临时态，不进版本库。删 `state.py` 后旧 `state.json` 自然废弃，新 run 重新填 `runtime-state.json`。故本 spec 不写任何 JSON 迁移/兼容 shim（Occam）。

**Task DAG（5 Task，≤6 上限内）**：

```
T1（RuntimeState 扩容：agent_id/ui_capable 存取 + 权威 STATUS_*）
 ├─→ T2（identity → RuntimeState）
 └─→ T3（release + results/board → RuntimeState + utils.github）
        T2, T3 ─→ T4（CLI 去 _state_for，四路径全走 RuntimeState）
                    └─→ T5（删 state.py + 收敛 9 个 state 测试 + docs 再生成）
```

T2 ∥ T3 可并行（文件不相交）。

**文件分配（两两不相交，单一 writer）**：

| Task | files | 依赖 |
|---|---|---|
| T1 | `openagents/runtime/state.py`, `tests/test_runtime_state_converge.py` | — |
| T2 | `openagents/utils/identity.py`, `tests/test_identity.py` | T1 |
| T3 | `openagents/utils/release.py`, `openagents/utils/results.py`, `tests/test_release.py`, `tests/test_results.py` | T1 |
| T4 | `openagents/cli.py`, `tests/test_cli.py` | T2, T3 |
| T5 | `openagents/state.py`(删), `tests/test_state.py`, `tests/test_state_closed_at.py`, `tests/test_state_code_fingerprint.py` | T4 |

> T5 的 `files` 列关键删除项；实际 T5 还会删/重写其余 6 个 `test_state_*.py`（merge_unblock/needs_human_unblock/unblock_detail 等，测旧栈跨轮阻塞字段，行为已随计数器废弃）——这些桩测的是 0062 已判定作废的旧栈语义，直接删。它们不与其它 Task 的 files 重叠，故不逐一列进 frontmatter。

**e2e 脚本**：本 spec 无独立 e2e；归一后跑既有全量 `pytest`（0062 基线 669 passed）+ `oa --help` 冒烟即验收。

**验收硬闸（每 Task）**：ruff check+format 绿、相关 pytest 绿、`spec validate` 无 error；T5 额外要求全库 grep `openagents.state` import 零命中 + OVERVIEW/ARCHITECTURE drift-free。

## Drawbacks

- **丢弃旧栈富字段**：`RunRecord` 的 rounds/review_invalid/block_gate/merge_attempts/block_watermark/unblock_detail/两个 fingerprint 随 `state.py` 一起消失。这些是旧栈 messages/orchestrator 的跨轮预算与 sticky-gate 记账，新栈已按设计放弃（无跨轮 rounds 预算）。若将来新栈要重建「跨轮记账」，得在 `RuntimeState` 上重新设计，而非复活旧字段——这是刻意的账，不是遗漏。
- **board 信息变薄**：成果看板不再显示 rounds/fingerprint 列。但看板面向「成果」（issue→PR→状态），这些旧计数器本就不是成果维度，变薄反而更聚焦。
- **一次性删 ~9 个 state 测试**：test coverage 数字会降，但删的是测已废语义的桩，非真实回归保护。

## Rationale and alternatives

**选定方案**：把三处生产读迁到 `RuntimeState`、给它补 agent_id/ui_capable 顶层键与权威 STATUS_*，然后删 `state.py`。理由：`RuntimeState` 已是新栈唯一 state、已被全部 recipe 采用，让它多承载两个顶层标量键（agent_id/ui_capable）成本极低（schema 本就是开放 dict），是通往「单一 state 模型」的最短路径。

**备选 1：保留 state.py 只做薄壳再导出**（像 0062 前的 utils shim 那样，state.py 再导出 RuntimeState）。否决：那不是归一，是再加一层间接；用户诉求是**删掉** flat 层，不是给它套壳。

**备选 2：把富 RunRecord 15 字段整体搬进 RuntimeState**（保旧栈计数器）。否决：违背 0062 已定的「新栈放弃跨轮预算」，把已作废的旧栈记账复活进新栈，增实体反奥卡姆。只迁**仍被读**的字段。

**备选 3：给 agent_id/ui_capable 另立独立小模块**（如 `runtime/identity_state.py`）而非塞进 RuntimeState。否决：它俩是 per-project 单标量，和 runs/cursors 同属「项目运行态」，同文件同类最自然；另立模块是过度拆分。

## Prior art

- **Spec-0062**（本波前序，已开 PR#158）：删净编排类旧模块、15 原语搬进 utils，把 flat 层从 28 文件压到 `{cli,__init__,state}` 三文件。本 spec 是它显式留的尾巴（0062/T5 正文：「state.py 因新旧 state 未归一暂留，其删除随 state 归一另开 Spec-0063」）。
- **Spec-0060/0061**：立起 `runtime.RuntimeState` 及其 `runs`/`cursors` 落盘、`find_run(pr_number=)`/`list_runs()` 接口（0062/T3 补入），是本 spec 扩容的基底。
- 旧 `State` 的字段谱系（RFC-0001 起，RFC-0011 agent_id、RFC-0012 rounds、Spec-0021/0031/0032/0042/0053/0055 陆续加的记账字段）——本 spec 是它们的终点：仍被读的迁走，旧栈专属的废弃。

## Unresolved questions

- **recipe-private `_STATUS_*` 是否收编进权威 STATUS_***：本 spec 只保证 `release` 有权威源可用，不强制改 rfc_lifecycle/merge_pr/vigil 里各自的 module-private `_STATUS_*`（改它们属 0062 已迁 recipe 的内部整理，范围外）。留作后续可选清理。
- **board 是否需要 pr_url 列**：`RuntimeState` 记录只有 pr_number。渲染时是「由 pr_number + 仓库 slug 派生 PR 链接」还是「只显示 pr_number」，T3 实现时按最小改动定；不影响归一目标。

## Future possibilities

- state 单一模型就位后，可给 `RuntimeState` 加一层**运行期 owner 校验/lease**（issue #71 的方向：把 files-allocation 的设计期所有权变成运行期强制），因为现在只有一个 state 真源，加锁/租约不用两处同步。
- 若将来要「跨 issue 的全局运行态仪表盘」，统一到单文件 `runtime-state.json` 后，一个读取点即可聚合，不用合并两个模型。

