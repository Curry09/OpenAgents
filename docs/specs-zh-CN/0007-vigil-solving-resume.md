---
number: "0007"
title: 守夜人恢复——激活 solving 为 resume 入口，修复 start_rfc 中途崩溃的孤儿 run
issue: 0
slug: vigil-solving-resume
summary: 修复守夜人半路崩溃留下的孤儿 run：把 solving 状态当成 resume 入口，让 start_rfc 中途崩溃后能接着干而不是从头再来。含 state/orchestrator/vigil 三处改动和崩溃恢复脚本。
tasks:
  - id: T1
    title: state：record_run 增 status 形参（一次写 rfc-review）
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
      - reliability
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/state.py
      - tests/test_state.py
    scope: 给 record_run 增加 status:str=STATUS_PR_OPEN 关键字形参，一次 _save 落盘带 pr_number/pr_url 且 status=<给定值> 的 run；更新 find_by_issue docstring 为「供发现段分流 fresh / resume」与 RunRecord docstring 的状态枚举说明（无新增状态）；不改 begin_run / update_status 签名。
    acceptance: 单测覆盖 record_run(status=STATUS_RFC_REVIEW) 一次落盘即得 rfc-review + 非零 pr_number；默认（不传 status）仍落 pr-open（既有用例不回归）；ruff 通过；注释引用 RFC-0007。
  - id: T2
    title: orchestrator：start_rfc 增 resume + 合并落盘
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
      - reliability
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: start_rfc 增加 resume:bool=False 形参。resume=False 保持现状（workspace.prepare + begin_run）；resume=True 改走 workspace.ensure（复用既有 worktree）且不调 begin_run。两分支汇合到同一尾段：backend.run（起草）→ commit_and_push → create_pr(draft=True) → 单次 record_run(status=STATUS_RFC_REVIEW, 带 pr)（删去原 record_run + update_status 两次写）。
    acceptance: 单测（假 backend + 注入假 Workspace + monkeypatch github）覆盖：fresh 走 prepare + begin_run；resume 走 ensure、不调 begin_run、不调 prepare；两者末态都是一次写成的 rfc-review（带 pr）、无瞬态 pr-open（断言 record_run 以 rfc-review 调用且不再单独 update_status）；ruff 通过；注释引用 RFC-0007。
  - id: T3
    title: vigil：发现段 solving 恢复三路分流
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
      - reliability
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/vigil.py
      - tests/test_vigil.py
    scope: 用 _dispatch_kind（返回 "fresh" | "resume" | None）取代 _is_new：record is None 且远端无分支 → "fresh"；record.status == STATUS_SOLVING and record.pr_number == 0 → "resume"；其它 → None。discover_and_dispatch 据此调 start_rfc(resume=...)，错误隔离（单 issue 失败记录跳过）保持不变，返回本轮派单编号列表。
    acceptance: 单测覆盖：无 run + 远端无分支 → fresh 派单（resume=False）；solving/pr=0 → resume 派单（resume=True）；rfc-review / pr-open / 已开 PR / done / closed → 跳过；远端已有分支但无 run → 跳过（去重闸 c）；resume 成功落 rfc-review 后下一轮不再重复派单。ruff 通过；注释引用 RFC-0007。
  - id: T4
    title: e2e 崩溃恢复脚本 + README 登记
    status: done
    priority: P1
    tags:
      - architecture
      - cli
      - dx
      - reliability
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-rfc-0007-resume.sh
      - docs/rfcs/README.md
    scope: 新增 scripts/e2e-rfc-0007-resume.sh：构造一条 solving/pr=0 的 run + 残留 worktree（模拟起草阶段崩溃），跑一轮 openagents vigil --once，断言该 issue 被自动恢复并最终开出 draft PR（state 落 rfc-review），无需人工干预。docs/rfcs/README.md 增加 RFC-0007 行。
    acceptance: 脚本可读、步骤完整（崩溃模拟 → discover 恢复 → 验证 draft PR + rfc-review）；README 列表含 RFC-0007 条目。
---

# 0007 · 守夜人恢复——激活 solving 为 resume 入口，修复 start_rfc 中途崩溃的孤儿 run

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

守夜人（vigil）在每轮发现段会扫描 issue 并派单。当 `start_rfc` 在「起草 RFC → 提交 → 开 PR」这条链路中途崩溃时，会留下一条 `solving`、`pr_number=0` 的孤儿 run 和一个残留 worktree——既不是全新 issue（已有 run 记录），又没开出 PR（无法被「已开 PR 则跳过」的去重闸接住），于是它永远卡在那里，既不会被恢复也不会被重派。本 feature 把 `solving/pr=0` 这一状态识别为 **resume 入口**：让 `start_rfc` 支持 `resume=True` 复用既有 worktree 接着干，让 vigil 的发现段做 fresh / resume / skip 三路分流，并把原本「先 `pr-open` 再 `update_status` 改 `rfc-review`」的两次写合并为一次写成 `rfc-review`，消灭瞬态中间态。

## Motivation

**现状（完整复述，不要求读者去翻别的 spec）。** 守夜人 `vigil` 以 `--once` 或循环方式运行，每轮做两件事：发现段扫描仓库 issue，对「该派单」的 issue 调 `orchestrator.start_rfc` 起草 RFC 并开 draft PR。派单与否由发现段的一个判定函数（旧版 `_is_new`）决定，配合去重闸：已有 run 记录、或远端已存在工作分支、或已开出 PR 的 issue，都不再重复派单。

`start_rfc` 的链路是：`workspace.prepare`（建 worktree）→ `begin_run`（落一条 `solving` 的 run，`pr_number=0`）→ `backend.run`（让 coding agent 起草 RFC）→ `commit_and_push` → `create_pr(draft=True)` → `record_run`（落 `pr-open` 带 pr）→ `update_status`（改 `rfc-review`）。

**问题。** 这条链路有两个缺陷：

1. **孤儿 run 无法恢复。** 若进程在 `begin_run` 之后、`create_pr` 之前崩溃（起草耗时最长、最易中断），留下的 run 是 `solving/pr=0`、worktree 还在。下一轮 vigil 发现这条 issue「已有 run」→ 不是 fresh，又「没开 PR」→ 去重闸放行不了，结果是夹在中间没人管。人必须手动清理 state 和 worktree 才能让它重来——违背「守夜人自动兜底」的初衷。
2. **存在瞬态中间态。** 正常路径先写 `pr-open` 再改 `rfc-review`，中间存在一个一闪而过的 `pr-open`。若恰在两次写之间崩溃，又会留下一个新的孤儿态。两次写本可合并为一次。

期望：把 `solving/pr=0` 当作「起草阶段崩溃、可从既有 worktree 续跑」的信号，让 vigil 自动 resume；并用一次写成的 `rfc-review` 消除瞬态态，缩小崩溃窗口。

## Guide-level explanation

对使用者，行为变化是「守夜人更鲁棒」：当某次起草半路崩溃，下一轮 `openagents vigil --once` 会自动认出那条 `solving/pr=0` 的 run，复用它残留的 worktree 接着把 RFC 起草完、开出 draft PR，无需任何人工清理。

发现段对每条 issue 现在判三种结局（旧版只判「新/不新」二元）：

| 情形 | 结局 | 含义 |
|------|------|------|
| 无 run 记录 且 远端无工作分支 | **fresh** | 全新 issue，`start_rfc(resume=False)` 从头起草 |
| run 为 `solving` 且 `pr_number=0` | **resume** | 起草阶段崩溃的孤儿，`start_rfc(resume=True)` 复用 worktree 续跑 |
| 其它（`rfc-review` / `pr-open` / 已开 PR / `done` / `closed` / 远端有分支但无 run） | **skip** | 已在流程中或已完结，不重派 |

## Reference-level explanation

落到改动，分解为 4 个 Task（DAG 见下；`files` 互斥，各 Task 单一 writer）：

1. **T1 state**（无依赖） — 给 `record_run` 增 `status: str = STATUS_PR_OPEN` 关键字形参，使其一次 `_save` 即落盘带 `pr_number/pr_url` 且 `status=<给定值>` 的 run，从而把「先 pr-open 再 update_status」两次写收敛为一次。`begin_run` / `update_status` 签名不变；`find_by_issue` 与 `RunRecord` 的 docstring 更新为「供发现段分流 fresh / resume」，无新增状态枚举。
2. **T2 orchestrator**（依赖 T1） — `start_rfc` 增 `resume: bool = False`。`resume=False` 走 `workspace.prepare` + `begin_run`（现状）；`resume=True` 改走 `workspace.ensure`（复用既有 worktree）且**不**调 `begin_run`。两分支汇合到同一尾段：`backend.run`（起草）→ `commit_and_push` → `create_pr(draft=True)` → **单次** `record_run(status=STATUS_RFC_REVIEW, 带 pr)`，删去原 `record_run` + `update_status` 两次写。一次写成 `rfc-review`，消灭瞬态 `pr-open`。
3. **T3 vigil**（依赖 T2） — 用 `_dispatch_kind`（返回 `"fresh" | "resume" | None`）取代旧 `_is_new`：`record is None` 且远端无分支 → `"fresh"`；`record.status == STATUS_SOLVING and record.pr_number == 0` → `"resume"`；其它 → `None`（跳过）。`discover_and_dispatch` 据此调 `start_rfc(resume=...)`，单 issue 失败记录跳过的错误隔离不变，返回本轮派单编号列表。去重闸「远端已有分支但无 run → 跳过」保持不变。
4. **T4 e2e + README**（依赖 T3） — 新增 `scripts/e2e-rfc-0007-resume.sh`：构造一条 `solving/pr=0` 的 run + 残留 worktree（模拟起草阶段崩溃），跑一轮 `openagents vigil --once`，断言该 issue 被自动恢复并最终开出 draft PR（state 落 `rfc-review`），无需人工干预。`docs/rfcs/README.md` 增加 RFC-0007 行。

**端到端验证**：`bash scripts/e2e-rfc-0007-resume.sh`（构造孤儿 run + 残留 worktree → vigil --once 自动 resume → 验证 draft PR + rfc-review）。

依赖 DAG：`T1 → T2 → T3 → T4`（线性链）。

## Drawbacks

- 把 `solving/pr=0` 一刀切判为「可恢复」，假定该状态只可能源于起草阶段崩溃；若未来 `solving` 被赋予其它语义，恢复判据需同步收紧。
- resume 复用既有 worktree，若崩溃留下的 worktree 已脏（半截改动），续跑会在其上继续——依赖 coding agent 的幂等起草能容忍既有内容。

## Rationale and alternatives

- **为什么用 `solving/pr=0` 当 resume 信号**：它精确刻画「已登记 run、但还没开出 PR」这一崩溃窗口，与「fresh（无 run）」「已开 PR（去重闸接住）」两端互不重叠，三路分流无歧义。
- **为什么合并两次写为一次**：`pr-open→rfc-review` 的瞬态态本身就是一个潜在孤儿源；一次写成 `rfc-review` 把崩溃窗口缩到最小，且无需新增状态枚举（奥卡姆，理念 1）。
- **备选：人工清理脚本**。否决——违背「守夜人自动兜底」目标，把恢复负担压回人身上。
- **备选：崩溃即回滚（删 run + worktree 从头重来）**。否决：起草是最贵的一步，丢弃已起草内容浪费算力，resume 续跑更省。
- **不改 `begin_run` / `update_status` 签名**，只加 `record_run` 的可选 `status` 形参——把 blast radius 收到最小（解耦，理念 10），既有调用方零回归。

## Prior art

「崩溃后从持久化状态 resume 而非重跑」是工作流引擎（如 Airflow、Temporal）的标准 checkpoint/resume 模式；本 feature 取其「以一条带状态的持久 run 记录作 checkpoint、按状态决定续跑还是新起」的核心，落到 vigil 发现段的轻量三路分流，不引入额外引擎。

## Unresolved questions

无。三路分流判据、一次写成 rfc-review、resume 复用 worktree 的语义均已在本组确定。

## Future possibilities

- resume 判据可扩展到更多崩溃点（如 `pr-open` 但 PR 实际未建成），按需细化状态机。
- e2e 脚本可纳入 CI 的离线冒烟集，常态化验证崩溃恢复路径。

