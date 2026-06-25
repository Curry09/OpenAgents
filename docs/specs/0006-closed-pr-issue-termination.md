---
number: "0006"
title: 守夜人识别 PR/issue 关闭作为终止信号
issue: 0
slug: closed-pr-issue-termination
summary: 守夜人要懂得收手：当一个 PR 或 issue 被关闭时，把它识别成终止信号，不再继续求解，避免对已放弃的工作空转。
tasks:
  - id: T1
    title: closed PR 识别为终止信号
    status: done
    priority: P1
    tags:
      - protocol
      - cli
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/github.py
      - openagents/state.py
      - openagents/messages.py
      - tests/test_github.py
      - tests/test_messages.py
    scope: github.py 新增 is_closed(*, pr_number)，读 gh pr view --json state 判定是否 == CLOSED（与 is_merged 对称：GitHub PR 三态 OPEN/CLOSED/MERGED 互斥，已合并 PR 的 state 是 MERGED 不算 closed）；state.py 新增 STATUS_CLOSED = "closed" 常量，不纳入 _OPEN_STATUSES；messages._process_run 在 merged 判定之后、阶段路由之前插入 closed 分支：命中则置 STATUS_CLOSED、返回 reason="closed"，不触发任何编排动作。
    acceptance: 一个 state=CLOSED、带 rfc-approved 标签、本地状态 rfc-review 的 run 经 poll 后不调用 implement、状态被置为 closed、事件 reason="closed"；closed 状态的 run 在后续 poll 中被跳过（不在 _OPEN_STATUSES）；merged 仍优先于 closed 与阶段路由，既有测试不回归；ruff check / ruff format --check / pytest 全绿。
---

# 0006 · 守夜人识别 PR/issue 关闭作为终止信号

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

让守夜人（vigil/poll 循环）懂得「收手」：当一个 PR 被人主动关闭（GitHub state 进入 `CLOSED` 而非 `MERGED`）时，把它识别成与「已合并」对称的**终止信号**，将该 run 置为新终态 `STATUS_CLOSED` 并在后续轮次跳过，不再继续求解，避免对已被人放弃的工作空转。

## Motivation

守夜人是一个持续轮询（poll）的循环：它遍历所有本地 run 记录，对仍处于「开放」状态（`_OPEN_STATUSES`：rfc-review / pr-open / iterating）的 run，按其阶段把工作推进下去（起草 RFC、实现代码、迭代评审等）。

在本 feature 之前，循环只识别一个终止信号——**merged**：`_process_run` 一旦发现 PR 已合并，就置 `STATUS_DONE` 并跳过。但「人主动关闭一个 PR（不合并）」这个同样明确的「**别再做了**」信号没有被识别。其后果是：一个被人关闭、判定为「放弃这条路」的 PR，对应的 run 仍停留在 rfc-review / pr-open 等开放状态里，守夜人会继续按阶段对它求解——重复起草、重复实现、重复评审一份人已经决定不要的工作。这既浪费 agent 算力，也违反「人做宏观把控、agent 不空转」的设计目标。

需要让守夜人对「关闭」与对「合并」一样敏感：关闭即终止，立刻收手。

## Guide-level explanation

GitHub 的 PR `state` 有三个互斥取值：`OPEN`、`CLOSED`、`MERGED`。已合并的 PR 其 state 是 `MERGED`（不算 `CLOSED`），所以「关闭未合并」可以干净地由 `state == "CLOSED"` 唯一识别，与既有的「合并」判定（`MERGED`）天然对称、互不重叠。

行为上的变化：从此以后，人只要在 GitHub 上点「Close pull request」（不合并），下一轮 poll 就会把这个 run 标记为 `closed` 并停止对它的一切编排动作；它也不再出现在「仍有开放工作」的统计里。人因此多了一个轻量的「叫停」开关——关掉 PR，agent 就收手——而不必另寻机制去中止一条已放弃的求解线。

## Reference-level explanation

单 Task（T1，无依赖），三处协同改动构成一条「检测 → 终态常量 → 路由」的链路：

1. **检测层 `github.py`** — 新增 `is_closed(*, pr_number)`：经唯一收口点 `_gh_json` 跑 `gh pr view <n> --json state`（自带瞬时重试），返回 `str(state).upper() == "CLOSED"`。结构镜像既有的 `is_merged`；GitHub 三态互斥保证已合并 PR（state=MERGED）不会被误判为 closed。
2. **状态层 `state.py`** — 新增常量 `STATUS_CLOSED = "closed"`，表示「PR 被关闭但未合并」的终态（人主动放弃）。它**刻意不纳入** `messages._OPEN_STATUSES`，从而被 poll 自动跳过。
3. **路由层 `messages.py` `_process_run`** — 在「merged 判定」之后、「阶段路由」之前插入 closed 分支：
   - 顺序刻意保持 `merged` 优先于 `closed`：若一个 PR 既已合并，按合并语义走 `STATUS_DONE`（merged 是更强的成功终态）；只有「关闭且未合并」才落到 closed。
   - 命中 closed 时：调用 `state.update_status(... status=STATUS_CLOSED)`，返回事件 `{"pr_number": ..., "reason": "closed"}`，**不触发任何编排动作**（不 implement、不 rebase、不评审）。
   - 因为 `STATUS_CLOSED ∉ _OPEN_STATUSES`，该 run 在后续 poll 轮次中被直接跳过，不再空转。

**Task 分解与依赖 DAG**：仅 T1，无依赖（`depends-on: []`），三处改动同属一个 PR 的单一 writer，不构成内部 DAG。

**端到端验证**：本 feature 无独立 `scripts/*.sh` e2e 脚本；以仓库标准门禁验证——`ruff check` / `ruff format --check` 全绿，`pytest`（含 `tests/test_github.py` 对 `is_closed` 的桩断言、`tests/test_messages.py` 对 closed 分支路由与 poll 跳过的断言）全绿。

## Drawbacks

- 终态从「仅 done」扩为「done / closed」两类，状态机多一个取值，poll 跳过逻辑需同时排除 `STATUS_BLOCKED` 与新增的 closed（已通过「不纳入 `_OPEN_STATUSES`」统一处理，未增分支复杂度）。
- 「人关 PR」是不可逆的叫停：若人误关，需要重开 PR 才能让守夜人重新接管（GitHub 重开后 state 回 OPEN，下一轮 poll 自然恢复）。

## Rationale and alternatives

- **为什么用 `state == "CLOSED"` 而非额外标签**：GitHub 原生三态已能精确表达「关闭未合并」，复用 state 字段无需新增标签约定，奥卡姆——不增实体。
- **为什么 merged 优先于 closed**：合并是更强的成功终态；二者理论上互斥（MERGED ≠ CLOSED），但保持 merged 在前可让既有合并语义（置 done、关 issue、扇出 rebase）完全不受影响，零回归。
- **备选：在 poll 入口统一过滤已关闭 run**。否决——检测需要调 `gh` 拿 state，放在 `_process_run` 内与 merged 判定并列最自然，且能同时产出 `reason="closed"` 事件供观测；放到入口反而要重复一次远程查询。
- **备选：把 closed 也当 done**。否决——done 语义是「工作成功落地」，会触发关 issue / rebase 其余 PR 等动作；closed 语义是「放弃」，必须是一个**不触发任何编排动作**的纯终态，故需独立常量。

## Prior art

与同仓既有的「merged 即终止」识别（`is_merged` + `STATUS_DONE`）完全对称，本 feature 是其镜像扩展。对应 GitHub PR 的三态模型（OPEN/CLOSED/MERGED 互斥）——「关闭未合并」在主流 CI/自动化中是标准的「放弃此变更」信号。

## Unresolved questions

无。检测口径（state==CLOSED）、终态常量、路由顺序（merged 优先）均已在本组确定。

## Future possibilities

- issue 被直接关闭（尚未开 PR 阶段）亦可对称识别为终止信号，复用同一「关闭即收手」语义。
- closed 终态可在前端成果视图中单列「已放弃」分类，与 done / blocked 区分呈现。
</content>
</invoke>

