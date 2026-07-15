---
number: "0072"
title: spec 组 Task 数软上限：>6 主动提示 + 声明式豁免，大 feature 一个 spec/一个 PR 交付
issue: 156
slug: task-count-soft-cap
summary: 把 spec-driven 的 ≤6 Task 硬拆组约定降为可读性软上限：>6 由 spec validate 出 warning 主动提示，声明 oversized-rationale 即豁免；单一 writer 的 files 互斥不变，大 feature 得以在一个 spec/一个 PR 内做完
tasks:
  - id: T1
    title: frontmatter 增可选 oversized-rationale + model round-trip
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/schema.py
      - openagents/spec/model.py
    scope: schema 增可选 oversized-rationale(string)；Metadata 增字段，load_group 读入、render_group 非空才写回
    acceptance: 写入 oversized-rationale 的 spec 经 load→render round-trip 逐字节不变；schema 接受该键、拒未知键不变
  - id: T2
    title: validate 第 11 条链：>6 Task 软上限 warning + 声明式豁免
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/validate.py
    scope: 新增 _task_count_checks：当前版 Task 数 >6 且 oversized_rationale 空 → warning；已声明则静默；warning 不影响 ok
    acceptance: 6 Task 组无提示；7 Task 组出一条 warning 且 report.ok=True；7 Task+rationale 组静默且 ok=True
  - id: T3
    title: skill 文档 reframe：6-Task 软上限 + files 互斥硬不变量
    status: done
    priority: P2
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - .claude/skills/spec-driven-development/SKILL.md
      - .claude/skills/spec-driven-development/references/task-fields.md
    scope: 把 >6 too large 强制拆改写为可读性软上限+声明式豁免；区分硬不变量(files 互斥)与软上限(6-Task)；记录 oversized-rationale
    acceptance: SKILL.md 不再含硬性 too large 措辞；文档说明 oversized-rationale 用法与两类约束区别
  - id: T4
    title: 规则 11 + round-trip 单测
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - tests/test_spec_validate.py
      - tests/test_spec_model.py
    scope: validate 规则 11 三态测 + oversized-rationale round-trip 测
    acceptance: 新增测试覆盖 6/7/7+rationale 三态与 round-trip，uv run pytest 全绿
---

# 0072 · spec 组 Task 数软上限：>6 主动提示 + 声明式豁免，大 feature 一个 spec/一个 PR 交付

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把 spec-driven-development skill 的「单个 spec 组最多 6 个 Task，超出即强制拆组」从一条**硬约定**降级为**可读性软上限**：Task 数 > 6 时 `spec validate` 出一条 **warning** 主动提示（非 error，不挂 CI），作者若确认这是一次**原子交付**，在组 frontmatter 声明一句 `oversized-rationale` 即豁免该提示。单一 writer 的**同组 `files` 两两不相交**硬不变量（理念 6）原样保留为 error。这样一个天然拆解 > 6 工作单元的大 feature 得以合法地待在**一个 spec / 一个 PR** 内做完，不再被迫切成多 spec 号、多 PR、多批次。

## Motivation

`spec-driven-development` skill 有两条约束常被并列理解为同级硬规则：

1. **单个 spec 组 ≤ 6 Task**——skill 正文原话「A group with more than 6 Tasks is too large — split into multiple focused groups」。
2. **Task 间 `files` 两两不相交**——单一 writer 所有权，协同模式无写冲突的根（理念 6），也是 issue #71 运行期 owner 检查的结构化源。

问题在于二者性质不同却被同等对待：约束 2 是**真不变量**（两个 Task 抢写同一文件 = 真冲突），已在 `openagents/spec/validate.py` 的 `_file_overlap_checks` 里硬编码为 **error**；而约束 1 只是**可读性/可评审的经验值**，且**从未在代码里被强制**——`validate` 全链十条规则没有一条数 Task 个数。它仅以 skill 文档 prose 存在，却产生了真实摩擦：

- 一个大 feature 若天然拆解 > 6 工作单元，就「装不进一个 spec 组」，被迫另开 spec 号、拆成多 PR，与「一个大 feature 一个 PR / 一波交付」的诉求（对标 cursor/windsurf 的成果交付节奏，见 CLAUDE.md 总体原则）直接冲突。
- **实例**：架构收敛批 Spec-0062 已占满 6 Task（rfc_lifecycle / merge_pr / vigil / cli 改接 / 清 flat 层 / 测试收敛），紧随其后的「state 归一（删 state.py）」挤不进去，只能另开 Spec-0063；同一诉求被 6-Task 上限切成两个 spec，当前折中是「同分支、同一波做，最后合成一个 PR」——一个需要 workaround 的软约束。

既然约束 1 从不是代码不变量、只是经验值，正确的修法是**如实把它表达成软上限**：给出主动提示（issue #156 方向 d 明确要的「预计 > 6 Task 时主动提示」），同时让「一个 feature = 一个大 spec」成为一等公民（方向 a 的实质：放宽 / 可声明），而不是继续用 prose 硬拆组。

## Guide-level explanation

对使用 spec 流程的 agent / 人，规则变为：

- **6 是可读性软上限，不是硬墙。** 拆 Task 时优先控制在 6 个以内以保证一个 spec 读得动、评审得动。
- 当一个 feature 天然 > 6 工作单元时，**允许把它们放进同一个 spec 组**——只要仍满足「同组 `files` 两两不相交」这条真不变量。
- 此时 `spec validate` 会给一条 **warning**（非 error，CI 依旧绿）：`组 Task 数 N > 6：确认这是一次原子交付；否则拆成多个聚焦的组`。
- 若确属一次原子交付，在组 frontmatter 加一行声明即可让提示消失、`validate` 干净：

  ```yaml
  oversized-rationale: "桌面 app 一次交付：看板/流式/导航强耦合，拆组会割裂 e2e 验收"
  ```

- 声明是**显式且被机器记录**的（软约定硬化：想越过软上限，必须留下一句为什么，而不是静默越过）。

单一 writer 的 `files` 互斥**丝毫不放松**——它才是协同并行安全的根。放宽的只是「一个组能装多少个互不抢文件的 Task」这个可读性经验值。

## Reference-level explanation

**改动面（4 个 Task，`files` 两两不相交）：**

| Task | files | 改什么 |
|----|----|----|
| T1 | `openagents/spec/schema.py`, `openagents/spec/model.py` | frontmatter schema 增可选 `oversized-rationale`（string）；`Metadata` 增 `oversized_rationale` 字段，`load_group` 读入、`render_group` 仅在非空时写回（夹在 summary 之后、e2e/tasks 之前），保证 round-trip 幂等零漂移 |
| T2 | `openagents/spec/validate.py` | 新增第 11 条链 `_task_count_checks`：当前版 Task 数 > `_TASK_SOFT_CAP`(=6) 且 `oversized_rationale` 去空白后为空 → 一条 **warning**；已声明则不提示。warning 不影响 `ok`（大 feature 一个 spec 不挂 CI） |
| T3 | `.claude/skills/spec-driven-development/SKILL.md`, `.claude/skills/spec-driven-development/references/task-fields.md` | 把「> 6 即 too large 强制拆」reframe 为可读性软上限 + 声明式豁免；区分「files 互斥=硬不变量」与「6-Task=软上限」；记录 `oversized-rationale` 字段 |
| T4 | `tests/test_spec_validate.py`, `tests/test_spec_model.py` | 规则 11 正反例（6 个不提示 / 7 个出 warning 且 ok=True / 7 个+rationale 静默）+ `oversized-rationale` round-trip |

**DAG**：T1 → T2（validate 依赖 model 的新字段）；T3、T4 依赖 T1/T2 语义成型。T3 与其余文件不相交可并行。

**软上限常量**：`validate.py` 内 `_TASK_SOFT_CAP = 6`，单一真源，注释指向本 spec。

**e2e / 成果验收**：纯离线后端 + skill 文档改动，验收即 `uv run pytest`（规则 11 三态 + round-trip）+ `uv run spec validate/render/graph` 生成物零漂移；无浏览器 e2e，故本 spec 不声明 `e2e` 块（form 天然为 cli/offline）。

## Drawbacks

- warning 是非阻塞的，理论上作者可以既不拆组也不声明 rationale，长期无视提示——但这与「files 互斥」这类真不变量不同层级，6-Task 本就是经验值，非阻塞是刻意选择（阻塞会把「大 feature 一个 PR」重新堵死，正是本 issue 要解决的）。
- 多一个可选 frontmatter 字段与一条 validate 链，是极小的实体增加（理念 1 奥卡姆），但确实让 spec 面多一个概念。

## Rationale and alternatives

**选定：软上限 warning + 声明式豁免（issue #156 方向 a + d 的合流）。** 如实表达「6 是经验值不是不变量」，非阻塞让大 feature 一个 spec/一个 PR 成为一等公民，声明式豁免把「越过软上限」从静默变成留痕（软约定硬化）。改动面最小、自包含、不引新跨模块概念。

**备选一（否决）——方向 c：跨 spec「交付单元」链接。** 让多个 spec 组通过新 frontmatter 关联成「一次交付」，把「多 spec 一个 PR」的 workaround 变一等公民。否决理由：引入「跨组交付单元」这个全新概念与机器（render/validate/CLI 都要认它），实体更多；且它只是祝福「多 spec 一 PR」，并未解决「装不进**一个** spec」——本 spec 的 reframe 让一个大 spec 直接装下整个 feature，更强也更简。

**备选二（否决）——方向 b：子组 / 分层 Task。** 一个组下再分层。否决理由：给 Task DAG 叠一层层级结构，render/validate/schema 全要改，破坏「Task 是扁平工作分解行」的现有简洁模型，与奥卡姆冲突。

**备选三（否决）——硬拆但仅改文档措辞。** 只把 skill 文档写软、不加任何机器信号。否决理由：issue 方向 d 明确要「> 6 时主动提示」，纯文档改动给不了 `spec validate` 层面的提示，agent 起草时仍无从感知上限已触发。

## Prior art

- 本仓库 `_file_overlap_checks`（同组 files 重叠 = error）确立了「真不变量入 validate」的先例；本 spec 对称地确立「软上限出 warning」。
- rust-lang/rfcs 的 RFC 无「章节 / 工作项数量上限」，规模由评审者判断——佐证「Task 数是可读性经验值而非硬约束」。
- issue #71（单一 writer 所有权从设计期推到运行期）已把 `files` 互斥确立为运行期守卫，进一步说明「files 互斥」与「6-Task 上限」不是同级——前者是安全不变量，后者是可读性经验值。

## Unresolved questions

- `_TASK_SOFT_CAP` 是否需要可配置（per-repo `.openagents` 声明）？本 spec 先用固定 6 + 声明式豁免覆盖已知诉求，留待后续按需再抽。

## Future possibilities

- 若 `oversized-rationale` 被频繁使用，可在 `spec render` 的 OVERVIEW 里给这类组打「原子交付」标记，让看板一眼可辨。
- 可把软上限做成 per-repo 可配置阈值（承接 Unresolved questions）。

