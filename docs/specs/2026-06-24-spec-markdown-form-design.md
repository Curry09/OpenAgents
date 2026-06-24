# Spec 改为 Markdown 文档形态 —— 设计

> 冻结的前向设计文档（dated design doc）。写于 2026-06-24，关联 issue #66。
> 本文件**本身就是需求②的范例**：dated markdown 设计文档，写完即冻结、append-only、靠 git 留存，
> 累积起来即「整个设计的历史」。请勿事后改写本文件；后续演进另起新 dated 文档。

## 背景

issue #66 最初提议「代码注释为唯一真源 + sync 引擎反向生成 spec」。经设计讨论判定**过重**
（违反 CLAUDE.md 理念 1 奥卡姆）：要造注释 sentinel 块、extract/sync 引擎、current//history/
双目录、CI drift 一整套。本设计取代 #66，把需求收窄到**两件事**，并以「在现有 spec 体系上稍改」
的方式落地。

现状（Spec-0014 体系）：每个 spec 组是一个目录
`docs/specs/NNNN-slug/{metadata.yaml, tasks/T*.yaml, history/T*.yaml}`，由 `spec` CLI 驱动，
`render` 生成 `OVERVIEW.md`，CI 做 drift-check。

## 目标（两件事）

1. **对代码的唯一映射（现状视图）** —— 代码本身是唯一真源。用一个**轻量 code graph**
   从代码生成「现在架构长什么样」：文件 = 节点，import = 边。再叠加**注释规范**
   （文件级 + 模块级 docstring），使「注释 + import 图」足以还原整个架构。
2. **整个设计的历史** —— 用 **dated markdown 设计文档**（如本文件）当历史载体，
   写完冻结、靠 git append，参考 Superpowers 的 `docs/superpowers/specs/` 约定。

## 设计决策

### D1：spec 组由「YAML 文件夹」改为「单个 markdown 文件」

`docs/specs/NNNN-slug/` 目录 → `docs/specs/NNNN-slug.md` 单文件：

- **YAML frontmatter**（机器读，对应 KEP 的 `kep.yaml`）：组元数据 `number/title/issue/slug`
  + `tasks` 列表，每个 task 的**结构化字段**（`id/title/status/priority/depends-on/files`）。
- **Markdown 正文**（人/agent 读，对应 KEP 的 `README.md`）：每个 task 一个 `## <id> · <title>`
  小节，内含 prose 子节（`### Design` / `### Acceptance` / …）。

「frontmatter 给机器、正文给 agent」正是讨论中确认的**两类读者**分离。

### D2：只换序列化层，保留数据模型与语义逻辑（降风险，真正的「稍改」）

`Task/Group/Metadata` 数据类不动；`validate` 的语义检查（DAG 无环 / 同组 files 不重叠 /
引用存在）与 `render`（看板/关系图/各 feature 段）**消费 model 对象，逻辑不变**。
**只改 `model.py` 的 load/dump**（YAML 文件夹 → markdown 单文件）与 `validate` 的 schema 读取入口、
`mutate` 的写入路径。这样既改成 markdown，又不推倒重来、不大面积破坏既有测试。

### D3：退役 per-task 版本历史机制，历史交给 git + dated 文档

旧的 `history/T*.yaml` + `spec amend`（当前版 append 进 history、version+1）这套，
与需求② 重复。退役之：

- `amend` 简化为「就地改 md 里的 task」，版本演化由 **git 历史**承载。
- 设计层「为什么这么演变」由 **dated 设计文档**（需求②）承载。
- 迁移时，现存 `history/`（仅 0014 有）作为**冻结附录**保留进该组 md 的 `## 历史（迁移自旧 history/）`，不丢。

这是**减实体**（Occam）：少一个目录、少一套 amend/abandon-to-history 逻辑、少一组 schema。

### D4：需求① —— `graph.py`，import 图 + docstring 现状视图

新增 `openagents/spec/graph.py`：

- 用标准库 `ast` 扫项目内 `.py`，解析 `import`/`from … import`，**只连项目内文件间的边**
  （标准库/第三方忽略）。文件 = 节点，import = 有向边。**不引入 PageRank / tree-sitter / 图库 /
  Neo4j**（参考 Aider repo map 确认那些是为「运行时挤进 prompt 预算」服务的，静态文档不需要）。
- **注释规范（对 agent 的硬要求）**：每个 `.py` 顶部写**文件级 docstring**（本文件负责什么）；
  每个包 `__init__.py` 写**模块级 docstring**（本子系统整体做什么）。
- 生成 `docs/specs/ARCHITECTURE.md`：子系统（按包 docstring）→ 组件（按文件 docstring）→
  依赖（import 边，Mermaid）。`graph` 子命令支持 `--check`（CI 用：缺 docstring 或文档漂移则失败）。

### D5：目录辨识

`docs/specs/` 下三类文件：组文件 `NNNN-slug.md`（`^\d{4}-[a-z]`，slug 以字母起，**排除** dated 文档的
`\d{4}-\d`）、dated 设计文档 `YYYY-MM-DD-*.md`、生成物 `OVERVIEW.md` / `ARCHITECTURE.md` 与手写
`README.md`。`load_all` 只认组文件。

## 影响的模块

| 模块 | 改动 |
|---|---|
| `openagents/spec/model.py` | load/dump 改 markdown 单文件；保留数据类；去 history dict |
| `openagents/spec/validate.py` | schema 读 frontmatter；语义检查不变；去 history 检查 |
| `openagents/spec/mutate.py` | new/add-task/amend 写单 md；amend 简化、去 history append |
| `openagents/spec/render.py` | 消费 model 不变；去/降级 per-task 演化图 |
| `openagents/spec/schema.py` | task schema 去 version/change-reason/history 相关；保留结构字段 |
| `openagents/spec/graph.py` | **新增**：import 图 + docstring 校验 + ARCHITECTURE.md |
| `openagents/spec/cli.py` | 加 `spec graph [--check]` |
| `.github/workflows/*` | drift-check 接新 render + `spec graph --check` |
| `.claude/skills/spec-driven-development/**` | 工作流文档改为 markdown 形态 |
| 迁移脚本 | 一次性把 14 组 YAML 文件夹转为 md，删旧目录 |

## 取舍（考虑过的替代）

- **替代 A：纯 markdown、无 frontmatter（完全照搬 Superpowers）。** 弃用——会丢掉机器可校验的
  DAG/files-disjoint，CI 无法 drift-check。保留 frontmatter 兼顾两类读者。
- **替代 B：保留 YAML 文件夹只加 graph。** 弃用——没满足「改成 markdown 文档形态」的明确诉求。
- **替代 C：代码注释为唯一真源 + sync 引擎（#66 原案）。** 弃用——过重，违反奥卡姆。

## 不在本 PR 范围（后续）

- **PR ②：退役 `test` 分支、改为一律合 main + 打 release 版本**（用户另提的分支策略）。本 PR 基线
  暂设 `test` 以得到干净 diff，main 合并归 PR ②。
- code graph 的函数级（call graph）精度：本期只做文件级 import 图（够还原架构、最省）。

## 验收

- `spec validate` / `spec render` / `spec graph --check` 全绿；OVERVIEW.md / ARCHITECTURE.md
  幂等（render 后无 git diff）。
- 14 组迁移后 `load_all` 读取无误、语义校验通过。
- ruff check + format、pytest 全绿。
