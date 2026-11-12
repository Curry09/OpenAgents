---
number: "0014"
title: 用「Spec 活快照 + 演化历史」取代 RFC —— Spec 永远与代码一一对应，legacy 沉淀到历史
issue: 35
slug: spec-snapshot-replaces-rfc
summary: 用「Spec 活快照 + 演化历史」取代 RFC：Spec 永远和当前代码一一对应，旧版本沉淀到 history、不再是流水账。含数据层/schema、validate、render（OVERVIEW）、amend/abandon、CLI 和迁移。
tasks:
  - id: T1
    title: 数据层 + JSON Schema + 依赖/入口声明
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/__init__.py
      - openagents/spec/model.py
      - openagents/spec/schema.py
      - pyproject.toml
      - tests/test_spec_model.py
    scope: 新建 openagents/spec/ 包；model.py 定义 RelatesTo/Task/Metadata/Group 与 load_group/load_all/dump_task/qualified_id（用 ruamel.yaml round-trip 读写，保留块标量与键序）；schema.py 定义 TASK_SCHEMA/METADATA_SCHEMA/HISTORY_SCHEMA（JSON Schema draft 2020-12，覆盖 Task 全字段 + 枚举）。pyproject.toml：dependencies 增 ruamel.yaml、jsonschema；[project.scripts] 增 spec = "openagents.spec.cli:main"。
    acceptance: 单测覆盖往返 load→dump→load 保真（块标量、键序、relates-to 列表）；缺省可选字段（tags/tests/open-questions 等）有合理默认；load_all 聚合多组；qualified_id 拼出 NNNN/T*；schema.py 三个 schema 本身是合法 JSON Schema（jsonschema 可编译）。pip install -e . 后 spec 入口可解析（即便 cli 由 T5 落地，入口声明先就位）。
  - id: T2
    title: spec validate（schema + 语义校验）
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/validate.py
      - tests/test_spec_validate.py
    scope: validate.py：ValidationIssue/ValidationReport + validate()，依序跑 JSON Schema 校验 → status 合法且与 history 末态自洽 → 同组 files 不重叠(error) → 全局（含跨组）depends-on DAG 无环(error) → 血缘/跨组引用存在(error) → 跨组 files 重叠(warning)。
    acceptance: 单测用临时 specs 树覆盖每条规则的正反例：schema 不合规→error；同组 files 重叠→error；构造环→检测到环 error；跨组 depends-on 指向不存在 Task→error；跨组 files 重叠→仅 warning 且 ok=True；全合规→ok=True 无 issue。
  - id: T3
    title: spec render → OVERVIEW.md（看板/关系图/冲突/DAG/演化图）
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/render.py
      - tests/test_spec_render.py
    scope: render.py：render()（纯函数返回全文，幂等）+ write_overview()。生成四块：全局看板表、跨 feature 关系图（Mermaid subgraph，depends-on 实线 / relates-to 虚线标 type）、文件冲突报告（跨组 files 重叠）、每 feature 段（组内看板 + 依赖 DAG + 演化图：节点=Task版本、按 status 着色、血缘字段连边）。
    acceptance: 单测固定输入两次 render 字节级一致（幂等）；输出含四块标题；看板行数 = 全部当前版 Task 数；关系图含跨组虚线边；演化图含某 Task 的 v1→v2 边与 abandoned 节点着色；空仓库不报错。
  - id: T4
    title: spec amend / abandon（历史追加 + 自动 render）
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/spec/mutate.py
      - tests/test_spec_mutate.py
    scope: mutate.py：amend()（当前版 append 进 history/T*.yaml → 覆盖 tasks/T*.yaml 为新版 version+1/updated=今天/change_reason → 调 render）；abandon()（当前 task append 进 history 末态 abandoned → 从 tasks/ 删除 → render）。
    acceptance: 单测：amend 后 history 长度 +1 且含旧版完整快照、tasks 为新版且 version 自增、OVERVIEW.md 被重写；连续 amend 版本号单调；abandon 后 tasks/ 无该文件、history 末项 status=abandoned；amend 不存在的 task→报错不破坏文件。
  - id: T5
    title: spec CLI + 编号校验脚本 + CI 接线
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T2
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - openagents/spec/cli.py
      - scripts/check-spec-number-conflicts.py
      - .github/workflows/ci.yml
      - tests/test_spec_cli.py
    scope: cli.py：main() 路由 render/amend/abandon/validate（validate 有 error → 退出码非 0）。scripts/check-spec-number-conflicts.py：移植 check-rfc-number-conflicts.py，路径正则改为 docs/specs/(NNNN)-slug/，本地 + open PR 并集查冲突。.github/workflows/ci.yml：rfc-conflicts job → spec-conflicts（调新脚本）；新增 spec validate 步与 OVERVIEW drift-check（spec render 后 git diff --exit-code）；更新 gate job 的 needs/汇总。
    acceptance: 单测打桩文件系统：spec render 写出 OVERVIEW；spec validate 在有 error 时退出码非 0、仅 warning 时为 0；spec amend/abandon 路由到 mutate。check-spec-number-conflicts.py 对 docs/specs/ 重复编号报冲突、唯一编号通过（打桩 gh）。ci.yml YAML 合法、含 spec-conflicts + validate + drift 步。
  - id: T6
    title: 迁移脚本 + spec-driven skill + specs README + e2e
    status: done
    priority: P1
    tags:
      - architecture
      - dx
      - cli
      - tooling
    depends-on:
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/migrate-rfc-to-spec.py
      - tests/test_migrate_rfc_to_spec.py
      - .claude/skills/spec-driven-development/SKILL.md
      - .claude/skills/spec-driven-development/references/
      - docs/specs/README.md
      - scripts/e2e-spec-0014-spec-driven.sh
    scope: scripts/migrate-rfc-to-spec.py：每份 docs/rfcs/NNNN-*.md → 一个 spec 组（metadata.yaml + tasks/ + origin.md）；RFC 头部 + 子任务表每行 → tasks/T*.yaml（status 映射 implemented→done、blocked→pending；files/depends-on 解析，整 RFC 级依赖 RFC-NNNN 形态不构成 Task 依赖故丢弃；每行 范围/验收标准 抽进 scope/acceptance）；组级正文留组内 origin.md（只读，render 不读取）。迁移产出 version=1 当前版 Task，history 初始为空。改写 skill：.claude/skills/spec-driven-development/（SKILL.md + references，含 Task JSON Schema 说明、# Spec-NNNN/T* 注释约定、三阶段工作流）。docs/specs/README.md（目录说明 + 编号规则）。scripts/e2e-spec-0014-spec-driven.sh（端到端：迁移→validate→render→amend→再 validate/render 幂等）。
    acceptance: 单测用 1~2 份真实 RFC 跑迁移，断言产出通过 spec validate、Task 数 = 原子任务行数、implemented→done、blocked→pending、产出 version=1 且 history 初始为空；全 13 份 RFC 迁移后 spec validate 全绿（仅跨组文件 warning）且 spec render 幂等（两次无 diff）。skill SKILL.md 含三阶段 + Task schema + 新注释约定；docs/specs/README.md 含编号规则。e2e 脚本可独立运行。
---

# 0014 · 用「Spec 活快照 + 演化历史」取代 RFC —— Spec 永远与代码一一对应，legacy 沉淀到历史

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

用「Spec 活快照（living snapshot）+ 演化历史」取代原先的 RFC 文档体系：每个 Spec 永远与**当前代码**一一对应（描述「现在是什么」，而非「曾经决定改什么」），任何一次改动通过 `amend` 把旧版整体沉淀进 `history/`、把 `tasks/` 覆盖为新版——于是 Spec 正文不再是逐次追加的流水账，而是恒等于代码现状的活快照，旧版本可追溯但不污染当前视图。整套能力分 6 个 Task 落地：结构化数据层 + JSON Schema（T1）、`spec validate` 语义校验（T2）、`spec render` 生成 OVERVIEW（T3）、`spec amend/abandon` 历史追加（T4）、`spec` CLI + 编号校验 + CI 接线（T5）、RFC→Spec 迁移脚本 + skill + e2e（T6）。

## Motivation

**现状：RFC 是只增不改的流水账。** OpenAgents 原本用 `docs/rfcs/NNNN-*.md` 承载设计决策。RFC 的语义是「一次提案 + 一组子任务」，它记录的是「当时打算改什么」。随着同一块代码被多次迭代，RFC 要么被新 RFC 取代、要么靠在原文里追加章节维持，久而久之：① 想知道「某模块现在是什么样」，得把若干份相关 RFC 连同其历次追加从头读到尾，再在脑子里做时间线合并；② legacy（已被取代的旧决策）和 current（当前现状）混在同一篇里，没有机械可校验的「这份 RFC 与代码一致」关系；③ 子任务的依赖、文件归属、状态都散落在 Markdown 表格里，工具无法校验环、无法检测两个 Task 抢同一个文件。

**问题：为什么要改。** 我们想要的是一种**与代码一一对应的活快照**——读 Spec 当前版就等于读代码现状，无需做时间线回溯；旧版沉淀到 `history/` 供审计，但默认视图永远干净。同时把「Task 的依赖 / 文件单一 writer 归属 / 状态 / 血缘」从自由 Markdown 升级为**结构化字段**，让 `validate` 能机械检查（DAG 无环、同组文件不重叠、跨组引用存在），让 `render` 能自动产出全局看板与演化图——人不再手工维护一致性，工具来兜底。

## Guide-level explanation

一个 Spec 组 = `metadata.yaml`（组级元信息）+ `tasks/T*.yaml`（每个 Task 一份**当前版**结构化快照）+ `history/T*.yaml`（该 Task 的历次旧版，末态可为 `abandoned`）+ `origin.md`（迁移自 RFC 的只读组级正文，render 不读取）。Task 的核心字段包括 `status`/`priority`/`depends-on`/`relates-to`（血缘）/`files`（单一 writer 文件所有权）/`scope`/`acceptance`/`version`。

日常三个动作：
- **`spec validate`**：跑 schema + 语义校验，CI 闸；有 error 退出码非 0。
- **`spec render`**：从所有组的当前版 Task 幂等生成 `OVERVIEW.md`（全局看板 + 跨 feature 关系图 + 文件冲突报告 + 每 feature 的依赖 DAG 与演化图）。
- **`spec amend <NNNN/T*>` / `spec abandon`**：改动一个 Task 时，先把它的当前版 append 进 `history/`，再把 `tasks/` 覆盖为 `version+1` 的新版（`amend`），或从 `tasks/` 删除并在 history 末态标 `abandoned`（`abandon`）——两者都自动重跑 render。于是「Spec 永远等于代码现状」这条不变量由动作本身保证，而不是靠人自觉。

对从 RFC 迁移过来的旧内容：迁移脚本把每份 RFC 拆成一个 Spec 组，子任务行变 `tasks/T*.yaml`，原文设计正文整体留进 `origin.md`，迁移产出的都是 `version: 1` 当前版、`history/` 初始为空（首次 `amend` 才落 v1，避免重复 v1）。

## Reference-level explanation

落到改动，分解为 6 个 Task（`files` 互斥，各 Task 单一 writer）：

1. **T1 数据层 + JSON Schema + 入口** — 新建 `openagents/spec/` 包。`model.py` 定义 `RelatesTo`/`Task`/`Metadata`/`Group` 数据类与 `load_group`/`load_all`/`dump_task`/`qualified_id`，用 `ruamel.yaml` round-trip 读写以**保留块标量与键序**（保证 render 幂等的前提）。`schema.py` 给出 `TASK_SCHEMA`/`METADATA_SCHEMA`/`HISTORY_SCHEMA`（JSON Schema draft 2020-12）。`pyproject.toml` 增依赖 `ruamel.yaml`/`jsonschema` 并声明 `spec` 入口脚本。这是全链路结构化数据的单一来源。

2. **T2 spec validate**（依赖 T1） — `validate.py` 提供 `ValidationIssue`/`ValidationReport`/`validate()`，依序：JSON Schema 校验 → status 合法且与 history 末态自洽 → **同组 files 不重叠(error)** → 全局（含跨组）`depends-on` DAG **无环(error)** → 血缘/跨组引用存在(error) → 跨组 files 重叠(warning)。error 才让 CI 红，跨组重叠仅警告。

3. **T3 spec render**（依赖 T1） — `render.py` 的 `render()` 纯函数返回全文（幂等）、`write_overview()` 落盘。产出四块：全局看板表、跨 feature 关系图（Mermaid，`depends-on` 实线 / `relates-to` 虚线标 type）、文件冲突报告、每 feature 段（组内看板 + 依赖 DAG + 演化图：节点=Task 版本、按 status 着色、按血缘字段连边）。

4. **T4 spec amend / abandon**（依赖 T1、T3） — `mutate.py`：`amend()` 把当前版 append 进 `history/T*.yaml`，再覆盖 `tasks/T*.yaml` 为 `version+1`（`updated`=今天、记 `change_reason`），末尾调 render；`abandon()` 把当前 task append 进 history 并末态置 `abandoned`、从 `tasks/` 删除、render。这是维持「活快照」不变量的写路径。

5. **T5 CLI + 编号校验 + CI**（依赖 T2、T3、T4） — `cli.py` 的 `main()` 路由 `render`/`amend`/`abandon`/`validate`（validate 有 error → 退出码非 0）。`scripts/check-spec-number-conflicts.py` 移植自 `check-rfc-number-conflicts.py`，路径正则改为 `docs/specs/(NNNN)-slug/`，并查本地 + open PR 并集冲突。`ci.yml`：原 `rfc-conflicts` job → `spec-conflicts`，新增 `spec validate` 步 + OVERVIEW drift-check（`spec render` 后 `git diff --exit-code`），更新 `gate` 的 `needs`/汇总。

6. **T6 迁移 + skill + README + e2e**（依赖 T2、T3） — `scripts/migrate-rfc-to-spec.py` 把每份 `docs/rfcs/NNNN-*.md` 拆成一个 Spec 组（`metadata.yaml` + `tasks/` + `origin.md`）：RFC 头部（优先级/标签/issue）+ 子任务表每行 → `tasks/T*.yaml`（status 映射 `implemented`→`done`、`blocked`→`pending`；`files`/`depends-on` 解析；**整 RFC 级依赖 `RFC-NNNN` 形态不构成 Task 依赖故丢弃**；每行 `范围`/`验收标准` 抽进 `scope`/`acceptance`）；组级设计/动机/接口契约/权衡/参考资料整体留 `origin.md`（只读，render 不读取）。迁移产出 `version: 1` 当前版、`history/` 初始为空。改写 `.claude/skills/spec-driven-development/`（SKILL.md + references，含 Task JSON Schema 说明、`# Spec-NNNN/T*` 注释约定、三阶段工作流 clarify→设计→实施验证）。新增 `docs/specs/README.md`（目录说明 + 编号规则）。

**端到端验证**：`bash scripts/e2e-spec-0014-spec-driven.sh`（端到端跑：迁移 → validate → render → amend → 再 validate/render 幂等）。

依赖 DAG：`T1 → T2`，`T1 → T3`，`T1 → T4`，`T3 → T4`，`T2 → T5`，`T3 → T5`，`T4 → T5`，`T2 → T6`，`T3 → T6`。

## Drawbacks

- 引入「当前版 + history」两套文件 + `amend`/`abandon` 写路径，比一篇只增不改的 Markdown 概念更重；改一个 Task 必须走 `amend` 而非直接编辑正文。
- 结构化 YAML + JSON Schema 对作者的格式约束更强（块标量、键序、枚举值），上手有一次性学习成本。
- render 出的 OVERVIEW 是派生物，需靠 CI 的 drift-check 防止与源数据漂移，多了一个 CI 闸。

## Rationale and alternatives

- **为什么活快照而非继续追加 RFC**：RFC「只增不改」导致「读现状」要做时间线合并；活快照让当前版恒等于代码现状，旧版沉淀进 history 既可审计又不污染默认视图——直接服务「人做宏观把控、工具兜一致性」的目标。
- **为什么结构化 YAML 而非自由 Markdown**：只有结构化字段才能让 `validate` 机械检查 DAG 无环、同组文件单一 writer、跨组引用存在，让 `render` 自动产出看板/演化图；自由 Markdown 无法被工具校验。
- **备选：保留 RFC、仅加一个索引工具**。否决：索引解决不了「legacy 与 current 混在一篇」和「依赖/文件归属不可校验」的根因。
- **为什么用 ruamel.yaml round-trip**：保留块标量与键序是 render 字节级幂等的前提；普通 yaml 库会丢格式导致 drift-check 误报。
- **迁移产出 version:1 且 history 为空**：与 `amend`「先 append 当前版再 bump」语义自洽，避免首次 amend 后 history 出现重复 v1。

## Prior art

「文档即代码当前快照」与「结构化元数据 + 校验/渲染工具链」是业界常见做法（如以机器可读 frontmatter 承载状态、用 lint 校验依赖图、用生成器产出总览）。语义化 status 流转（done/pending/abandoned）与依赖 DAG 校验亦取自常规工程实践。本 feature 取其「源数据结构化 + 派生视图自动生成 + CI 防漂移」核心，不引入更重的外部文档系统。

## Unresolved questions

无。数据模型字段、校验规则集、render 四块结构、amend/abandon 语义、迁移映射规则均已在本组确定。

## Future possibilities

- `files` 单一 writer 声明可进一步驱动「按文件所有权自动派发 Task / 检测并行冲突」（为 issue #71 留源）。
- render 可扩展更多视图（如按 owner、按里程碑聚合）或导出为前端可视化的成果看板。
- `validate` 可加入更多策略（如要求每个 done Task 必须有 acceptance、跨组文件重叠升级为可配置 error）。
</content>
</invoke>

