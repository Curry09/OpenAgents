# Specs —— Spec 活快照（markdown 形态）+ 代码现状映射

> 2026-06-24 spec-markdown-form（取代 Spec-0014 的 YAML 文件夹形态，见 `2026-06-24-spec-markdown-form-design.md`）。

本目录存放 OpenAgents 的「当前规格」。每个 spec 组 = **一个 markdown 文件** `NNNN-slug.md`：
YAML frontmatter 放结构化源数据（机器读），正文放各 Task 的设计 prose（人/agent 读）。

## 目录结构

```
docs/specs/
├── OVERVIEW.md            # 唯一人读看板（spec render 生成，纯派生物，勿手改）
├── ARCHITECTURE.md        # 对代码的唯一映射（spec graph 生成：import 图 + docstring，勿手改）
├── README.md              # 本文件（人写，静态）
├── NNNN-slug.md           # 一个 spec 组 = 一个 issue/feature（frontmatter + 正文 prose）
└── YYYY-MM-DD-<topic>-design.md   # dated 设计文档（前向设计史，写完即冻结、append-only）
```

## 两件事（设计意图）

1. **对代码的唯一映射（现状）** —— `ARCHITECTURE.md` 由 `spec graph` 从代码生成：文件级 import 图
   （`ast` 扫，文件=节点、import=边）+ 文件级/模块级 docstring。**代码本身是唯一真源**。
2. **整个设计的历史** —— dated 设计文档（`YYYY-MM-DD-*-design.md`），写完冻结、靠 git 追加，
   累积即设计演化史（参考 Superpowers `docs/superpowers/specs/`）。

## 编号规则

- 组文件用四位编号 `NNNN-slug.md`（slug 以字母起；与旧 RFC 编号 1:1 兼容）。
- 取下一号对本地 + 所有 open PR 取并集避免撞号：
  `python scripts/check-spec-number-conflicts.py --open-prs --current-pr <n>`。
- dated 设计文档（`YYYY-MM-DD-*`）不是组，不参与编号。

## `spec` 工具

```
spec new <slug> --issue N --title "…"   # 新建组 markdown（NNNN-slug.md）
spec add-task <组> --id T1 …            # 往组里加 Task
spec render                              # 重新生成 OVERVIEW.md（幂等）
spec graph                               # 重新生成 ARCHITECTURE.md（幂等）
spec graph --check                       # CI：校验 docstring 齐全 + ARCHITECTURE 无漂移
spec validate                            # schema + 语义校验（有 error 退出码非 0）
spec abandon <组> <task> --reason "…"    # 从快照移除 Task（历史在 git）
```

> 改 Task 内容直接编辑组 `NNNN-slug.md`，再 `spec validate` / `spec render`。`spec amend` 已退役
> ——版本演化由 git 历史承载，「为什么这么演变」由 dated 设计文档承载。
> 不要手改 `OVERVIEW.md` / `ARCHITECTURE.md`（派生物，CI 有 drift-check 守护）。

详见 `.claude/skills/spec-driven-development/`。
