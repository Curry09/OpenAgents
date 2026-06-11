# Specs —— Spec 活快照 + 演化历史

> Spec-0014: 用「Spec 活快照 + 演化历史」取代 RFC。

本目录是**源数据树**，存放 OpenAgents 的「当前规格」。基本单元是 **Task**：稳定 ID、
自包含、与当前活着的代码一一对应。做完的 Task 留在快照（`status: done`），只有「被重构
Task 的旧版本」与「被废弃的 Task」进 `history/`——**快照里永远没有 legacy**。

## 目录结构

```
docs/specs/
├── OVERVIEW.md          # 唯一人读视图（spec render 生成，纯派生物，勿手改）
├── README.md            # 本文件（人写，静态）
└── NNNN-slug/           # 一个 spec 组 = 一个 issue / feature
    ├── metadata.yaml    # 组级元数据：title / issue / slug
    ├── tasks/T*.yaml    # 当前版 Task 快照（纯结构化 YAML + 块标量 prose）
    ├── history/T*.yaml  # Task 历史版本列表（追加式，首次 amend 才出现）
    └── origin.md        # （迁移产生）原 RFC 正文归档，只读，render 不读取
```

## 编号规则

- 组目录用四位编号 `NNNN-slug/`，与旧 RFC 编号 **1:1 兼容**（RFC-0009 ≡ spec 组 0009）。
- 取下一号时，需对**本地 `docs/specs/` + 所有 open PR** 取并集，避免撞号：
  `python scripts/check-spec-number-conflicts.py --open-prs --current-pr <n>`。
- 同一编号不可被不同 slug 复用（本地冲突由上面脚本报 error）。

## `spec` 工具

```
spec render                       # 重新生成 OVERVIEW.md（幂等）
spec validate                     # schema + 语义校验（有 error 退出码非 0）
spec amend   <组> <task> --reason  # 改一个 Task：旧版进 history，当前版 version+1，自动 render
spec abandon <组> <task> --reason  # 废弃一个 Task：进 history（末态 abandoned），从快照删除
```

> 改 Task 用 `spec amend` / `spec abandon`，不要手改 `OVERVIEW.md`（它是派生物，CI 有
> drift-check 守护）。新建组 / 改 Task 内容直接编辑 `tasks/T*.yaml`，再 `spec validate`。

详见 `.claude/skills/spec-driven-development/`。
