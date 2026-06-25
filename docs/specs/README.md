# OpenAgents Specs

本目录存放 OpenAgents 的「当前规格」。每个 spec 组 = **一个 markdown 文件** `NNNN-slug.md`：
YAML frontmatter 放结构化源数据（机器读：组元数据 + `tasks[]` 工作分解 DAG），正文放
**组级 rust-RFC 9 段总览**（人/agent 读）。

> 形态对标 [rust-lang/rfcs](https://github.com/rust-lang/rfcs)：一篇 spec 像一篇 RFC，
> feature 全貌先讲清楚（总览先行），DAG + 文件分配收进 Reference-level（issue #69，
> 见 `2026-06-25-spec-rfc-form-design.md`）。

## What a spec is

一个 spec 是某个 feature「为什么做、做什么、整体方案、关键决策」的**自包含**书面产物。
任取一个 spec **单独阅读即可完整理解其语义**——不必打开其它 spec。可以提别的 spec 编号当
线索，但**理解本 spec 所必需的信息必须就地复述**（复述胜过一个引用）。

## When you need a spec

实质改动走 spec（`spec new`）：
- 新模块 / 服务 / 主要组件；
- 公共接口或协议变更（如 agent 消息协议）；
- 数据模型 / 持久化状态变更；
- 跨模块 feature；
- 任何值得记录设计权衡的改动。

可跳过（直接实现）当且仅当全部成立：无设计决策可记、只影响一个模块/文件、只有一个 Task。
小 feature 若是某组的自然延伸，`spec add-task` 挂到该组而非新建。

## The spec template (rust-RFC 9 sections)

`spec new` 在正文里铺好这 9 段（标题固定，空段填 `<!-- 待填 -->`）。**带 ★ 为必填**，
`spec validate` 对其空值报 error：

| Section | 写什么 |
|---|---|
| ★ Summary | 一段话：这个 feature 是什么 |
| ★ Motivation | 现状 + 为什么改；背景就地复述，无 load-bearing 跨 spec 引用 |
| Guide-level explanation | 当它已存在，如何向人讲解（示例为主） |
| ★ Reference-level explanation | 技术方案 + **DAG / 文件分配表** + e2e 脚本路径 |
| Drawbacks | 为什么不该做 |
| ★ Rationale and alternatives | 为什么这个方案；≥1 个备选及不选的理由 |
| Prior art | 先例（其它项目/语言/论文）；无则注明 |
| Unresolved questions | 仍待解决的问题 |
| Future possibilities | 自然的后续演化 |

`tasks[]`（frontmatter）是总览之下的工作分解行：每行 `id/title/status/priority/depends-on/
files/scope/acceptance`。`files` **必填且同组互斥**——单一 writer 所有权声明（理念 6，
issue #71 运行期 owner 检查的源）。字段全表见
`.claude/skills/spec-driven-development/references/task-fields.md`。

## The spec life-cycle

每个 Task 带 `status`，组随其 Task 推进：

- `pending` → `in-progress` → `done`：`done` 的 Task **留在快照**（它映射到活代码）。
- `abandoned`：被 `spec abandon` 从快照移除（历史在 git）。

「为什么这么演变」由 **dated 设计文档** `YYYY-MM-DD-<topic>-design.md`（写完冻结、append-only）
承载；版本演化交给 git。

## 目录结构

```
docs/specs/
├── OVERVIEW.md            # 唯一人读看板（spec render 生成，纯派生物，勿手改）
├── ARCHITECTURE.md        # 对代码的唯一映射（spec graph 生成：import 图 + docstring，勿手改）
├── README.md              # 本文件（人写，静态）
├── NNNN-slug.md           # 一个 spec 组 = 一个 issue/feature（frontmatter + 9 段总览正文）
└── YYYY-MM-DD-<topic>-design.md   # dated 设计文档（前向设计史，写完即冻结、append-only）
```

## `spec` 工具

```
spec new <slug> --issue N --title "…" --summary "…"   # 新建组（含 9 段脚手架）
spec add-task <组> --id T1 … --files … --acceptance …  # 往组的 DAG 加工作分解行
spec render                              # 重新生成 OVERVIEW.md（幂等）
spec graph                               # 重新生成 ARCHITECTURE.md（幂等）
spec graph --check                       # CI：校验 docstring 齐全 + ARCHITECTURE 无漂移
spec validate                            # schema + 语义 + 总览质量门槛（有 error 退出码非 0）
spec abandon <组> <task> --reason "…"    # 从快照移除 Task（历史在 git）
```

> 改组内容直接编辑 `NNNN-slug.md`（正文 9 段 / frontmatter tasks），再 `spec validate` /
> `spec render`。`spec amend` 已退役。不要手改 `OVERVIEW.md` / `ARCHITECTURE.md`（派生物，
> CI 有 drift-check 守护）。

## 编号规则

- 组文件用四位编号 `NNNN-slug.md`（slug 以字母起；与旧 RFC 编号 1:1 兼容）。
- 取下一号对本地 + 所有 open PR 取并集避免撞号：
  `python scripts/check-spec-number-conflicts.py --open-prs --current-pr <n>`。
- dated 设计文档（`YYYY-MM-DD-*`）不是组，不参与编号。

详见 `.claude/skills/spec-driven-development/`。
