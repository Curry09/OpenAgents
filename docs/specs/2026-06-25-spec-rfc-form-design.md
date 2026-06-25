# 设计文档:spec 转 rust-RFC 形态(总览先行 + 单 spec 自包含)

> Dated 设计文档(前向设计史,写完冻结、append-only)。对应 issue #69。
> 落地后会新建对应的 spec 组(本组自身用新格式 dogfood)。

## 背景与问题(issue #69)

当前 spec 单独看「看不太懂」,根因是**语义不完整**,两条:

1. **单个 spec 不自包含**:正文大量「见 Spec-0012 决策 7 / 决策 8 / 决策 2」式跨 spec 引用,把关键设计依据甩到别处。读者(人或 agent)拿到一个 spec 必须再翻另外几个才能拼出完整语义。
2. **没有 feature 总览就直接拆 Task**:`spec new` 后马上 `spec add-task`,组级只有一句 `summary`,读者上来面对一张 Task 表,没有先建立整体认知。

还有一个**代码层面的隐藏缺陷**(调查时发现):0023 里手写的 `## 总览(feature overview)` 段落,`openagents/spec/model.py` 的解析器根本不解析——它只认 `## T<n>` Task 小节(`_TASK_HEADING_RE = ^##\s+(T...)`)。于是这段总览**不进数据模型**,下次任何 `spec render` / 工具改写组文件时会被**直接丢弃**。所以「数据模型支持组级总览字段」不是可选项,是必须做。

## 决策:spec = 一篇 rust 风格 RFC,Task DAG 收进设计节

参考 [rust-lang/rfcs](https://github.com/rust-lang/rfcs) 的 `0000-template.md`(9 段模板)与 `README.md`(流程/生命周期),把 spec 的**主体**从「Task DAG 骨架 + 每个 Task 各写 prose」翻成「**feature 级 RFC 9 段 prose 为主体**,Task 退化成设计节里的工作分解 + 文件分配表」。

关键认识:**RFC 与 DAG+文件分配不冲突**。rust 之所以 RFC 里没有 DAG,是因为它把设计(RFC 仓库)与实现(主仓 issue/PR)彻底分离;OpenAgents 选择让二者共存——RFC 9 段讲清 feature 全貌,DAG 收进 **Reference-level explanation** 一节,理念 6「并行 = DAG + 文件分配」原样保住。

### 新的 spec 文件结构

**Frontmatter(机器读,结构化源数据)**
- 组元数据:`number / title / issue / slug / summary(一句话 TL;DR) / status`
- `tasks[]`:**保留**,但只剩结构化字段 + 两个一行短 prose:
  `id / title / status / priority / tags / depends-on / relates-to / parallel / files / scope(一句话改什么) / acceptance(可验证验收)`
  这就是 DAG + 文件分配,`spec render` / `spec graph` / `spec validate` 继续吃它。

**正文(人/agent 读,rust 9 段组级 prose)**

| 段(rust 原名) | 写什么 |
|------|------|
| **Summary** | 一段话讲清这个 feature 是什么 |
| **Motivation** | 现状 + 为什么改;**背景就地复述完整**,禁止把必要信息留给「见 Spec-00XX」 |
| **Guide-level explanation** | 当它已存在,如何向人讲解(以例子为主) |
| **Reference-level explanation** | 技术方案细节 + **DAG + 文件分配就放这一节**(Task 分解表 / mermaid 依赖图) |
| **Drawbacks** | 为什么*不*该做 |
| **Rationale and alternatives** | 为什么这个方案最好;**至少一个备选方案**及不选它的理由 |
| **Prior art** | 相关先例(其它项目/语言/论文);无则注明 |
| **Unresolved questions** | 仍待解决的问题(取代原 Task 级 `Open-Questions`) |
| **Future possibilities** | 自然的后续演化 |

### 为什么这样能消除「重叠」

旧模型每个 Task 各写 `Design / Interface / Tradeoffs / Open-Questions`,若组级再塞 9 段会与 Task 级 prose 语义打架。新模型里**设计叙述只在 feature 级讲一遍(9 段)**,Task 退化成 Reference-level 里的一张工作分解/文件分配表。无重叠,且天然满足 issue #69 的两条验收:总览先行 + 单 spec 自包含。

## 数据模型改动(`openagents/spec/`)

1. **`model.py`**
   - `Group`(或新增 `GroupProse`)新增 9 个组级 prose 字段:`summary / motivation / guide_level / reference_level / drawbacks / rationale_alternatives / prior_art / unresolved_questions / future_possibilities`。
   - `Task` **删除**重 prose 字段(`motivation / design / interface / tradeoffs / tests / references / open_questions`),保留结构化字段 + 新增/保留两个一行短字段 `scope / acceptance`(进 frontmatter)。
   - 正文解析 `_parse_body`:从「按 `## T<n>` 切 Task」改为「按 `## <rust 段名>` 切 9 个组级段」;`_render_body` 对称渲染 9 段。
   - `_TASK_FM_ORDER` 增加 `scope / acceptance`。
2. **`schema.py` / `validate.py`**
   - 质量门槛(quality bar)新增校验:① 9 段中**必填段**(Summary / Motivation / Reference-level / Rationale and alternatives)非空;② Motivation/正文**不得出现「见 Spec-NNNN」式承载必要信息的裸引用**(可提编号作线索,但用 lint 规则提示自包含——以告警或 error 形式,见 Open questions);③ `tasks[]` 每行有 `files`(互斥)+ `acceptance`。
3. **`render.py`**(OVERVIEW.md):组卡片改为展示组级 Summary 段 + Task 分解表(而非旧的逐 Task prose)。
4. **`cli.py`**:`spec new` 生成含 9 段空模板的组文件;`spec add-task` 仍往 `tasks[]` 加行(prose 不再挂 Task)。
5. **`graph.py`**:不受影响(吃 import 图 + docstring),仅确认 ARCHITECTURE 渲染不引用已删字段。

## 改动面清单(一个 PR 全塞)

- `openagents/spec/`:model / schema / validate / render / cli(+ 对应单测 TDD)。
- `.claude/skills/spec-driven-development/`:SKILL.md Phase 2 改为「先写 9 段 RFC 总览 → 再用 add-task 补 DAG 行」;quality bar 写入「单 spec 自包含、禁止跨 spec 承载必要信息」;references/ 更新字段表。
- `docs/specs/README.md`:对齐 rust RFCs README 风格(何时需要 spec / 流程 / 模板指引 / 生命周期 status)。
- `openagents/orchestrator.py`:`_DRAFT_RFC_TASK` / `_REFINE_RFC_TASK` prompt 改为「按 RFC 9 段写,DAG 进 Reference-level」。
- **22 个存量 spec**:全部重写成新形态——补 9 段总览,把跨 spec 引用里「理解本 spec 必需」的内容就地复述;首当其冲 0023 / 0012 及含「见 Spec-00XX 决策」的。
- **89 处 `# Spec-NNNN/T*` 代码注释**:祖父化保留(spec 号仍有效,`/T*` 后缀作为历史线索不强制清理;新代码用 `# Spec-NNNN`)。

## 取舍与备选(Rationale and alternatives)

- **备选 A:单 freeform `overview` 字段**(不强制 9 段)。更省,但不满足「严格按 rust 模板」,也难形成稳定可校验的质量门槛。**否决**:用户明确要严格按 rust。
- **备选 B:去掉 Task,纯设计文档**(rust 式设计/实现彻底分离)。会废掉理念 6 的组内文件分配并行,blast radius 更大。**否决**:用户澄清 DAG 可与 RFC 共存,收进设计节即可。
- **采用:RFC 9 段为主体 + frontmatter 保留 `tasks[]` DAG**。机器可读性(graph/validate)与人可读性(9 段自包含)兼得。

## 边界(不做什么)

- 不引入 rust 的 FCP / sub-team / rfcbot 评审流程(YAGNI;OpenAgents 用 PR + reviewer 闸已覆盖)。
- 不强制清洗 89 处历史 `/T*` 注释(祖父化)。
- 不改 orchestrator/vigil 的闸门逻辑,只改派活 prompt 文案。
- ARCHITECTURE.md / graph 机制不变。

## Unresolved questions

- 「禁止跨 spec 裸引用」用 **error(CI 拦)** 还是 **warning(提示)**?倾向先 warning,避免一上来卡住 22 个存量回填;待全绿后可升 error。
- `tasks[]` 的 `acceptance` 是否仍要求每行都有(P2 收尾类 Task 可能很轻)?倾向必填,保持可验证。

## 参考(已逐字查看,理念 7)

- rust RFC 模板:`rust-lang/rfcs` `0000-template.md`(9 段及其指引文字)。
- rust RFC 流程/生命周期:`rust-lang/rfcs` `README.md`(When you need to follow this process / What the process is / The RFC life-cycle)。
