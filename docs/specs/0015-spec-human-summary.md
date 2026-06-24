---
number: "0015"
title: spec 人类可读 summary：填 group 级 summary 字段 + render 大白话 TL;DR
issue: 58
slug: spec-human-summary
summary: '给每个 spec 加一段面向人的大白话 TL;DR：metadata 增组级 summary 字段、spec new 必填、validate 强制非空、render 在 OVERVIEW 顶部逐 feature 展示，并迁移补齐所有现存 spec。是 #59 人类监督闸门的地基。'
tasks:
  - id: T1
    title: 数据层：metadata 增 group 级 summary 字段
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/schema.py
      - openagents/spec/model.py
      - tests/test_spec_model.py
  - id: T2
    title: 授权路径：spec new --summary（cli + mutate）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/mutate.py
      - openagents/spec/cli.py
      - tests/test_spec_mutate.py
      - tests/test_spec_cli.py
  - id: T3
    title: 闸门：validate 强制 summary 非空
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/validate.py
      - tests/test_spec_validate.py
  - id: T4
    title: 人读视图：render 顶部 TL;DR 区块
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/render.py
      - tests/test_spec_render.py
  - id: T5
    title: 迁移：补齐 14 个现有 spec 的 summary + 重渲染
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - docs/specs/OVERVIEW.md
---

# 0015 · spec 人类可读 summary：填 group 级 summary 字段 + render 大白话 TL;DR

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据，正文为各 Task 设计 prose。 -->

## T1 · 数据层：metadata 增 group 级 summary 字段

### Summary

给 metadata（组级元数据）加一个 summary 字段，作为整个 feature「人话 TL;DR」的唯一存储位。这是本组其余 Task 的地基。

### Motivation

一个 spec 现在没有给人看的入口：per-Task 的 `summary` prose 字段是 task 粒度的、且全空着；`OVERVIEW.md` 只有一张 task-id/文件/状态的密表。人想一眼搞懂「这个 spec 在干嘛」做不到。

TL;DR 是 **feature/组** 级的概念（「这个 feature 是啥、为什么做、产出什么、不做什么」），不是 task 级。因此它的归属应是组级元数据 `metadata.yaml`，与 `title`/`issue`/`slug` 并列，而不是塞进某个代表性 Task 的 prose。本 Task 在数据层把这个字段立起来——schema 声明它、model 读写它、键序固定——后续 validate/render/迁移都建立在它之上。

### Scope

仅数据层：`schema.py` 给 METADATA_SCHEMA 增 summary 属性（string，不设 required）；`model.py` 的 Metadata dataclass 增 summary 字段、`_load_metadata` 兼容读旧文件、`dump_metadata` 固定键序 title/issue/slug/summary。不含 CLI、validate、render、内容迁移（分别由 T2–T5 负责）。

### Design

**落点决策（D1）**：summary 放 `metadata.yaml` 组级，而非复用 per-Task 的 `summary` prose 字段。理由：TL;DR 是 feature 级的，「group/feature 级 summary」是 issue #58 的原话；per-Task summary 语义是 task 粒度，复用会迫使「指定代表 Task / 聚合多个 task summary」的额外规则，违反奥卡姆。per-Task `summary` 字段保持原样、互不影响。

**三处改动**（都在数据层，理念 10 解耦，不感知 git/GitHub）：

1. `schema.py` 的 `METADATA_SCHEMA.properties` 增 `summary: {type: string}`。因为 metadata schema 是 `additionalProperties: False`，不声明的话任何带 summary 的 metadata.yaml 都会被判 schema 错误，所以这一步是 T2/T5 能写入 summary 的前置。**这里不设 `required`**——「非空」语义由 T3 的语义校验链统一负责（见权衡），schema 只负责「这个键合法、类型是 string」。
2. `model.py` 的 `Metadata` dataclass 增 `summary: str` 字段（frozen dataclass，放在 slug 之后）；`_load_metadata` 增 `summary=str(raw.get("summary", ""))`（缺字段降级空串，迁移期可平滑读旧文件）。
3. `model.py` 的 `dump_metadata` 把 payload 从 `[title, issue, slug]` 扩成 `[title, issue, slug, summary]`，键序固定——这是 `spec new`/迁移写出的单一来源，保证不漂移。summary 用普通标量还是块标量？TL;DR 是一两句话的短文，用普通字符串标量即可（不像 design 那样承载多段 Markdown/mermaid），保持 metadata.yaml 紧凑。

### Interface

- `Metadata(title: str, issue: int, slug: str, summary: str = "")` —— 新增 `summary`，给默认空串以兼容旧调用点与旧文件加载。
- `dump_metadata(*, metadata: Metadata, path: Path)` —— 输出键序 `title / issue / slug / summary`，行为不变只多一键。
- `METADATA_SCHEMA` —— properties 多一个 `summary`（string），仍 `additionalProperties: False`。

### Tradeoffs

- **组级 metadata vs 复用 per-Task summary**：选组级。复用 per-Task 改动看似更小，但语义错配（task 级 ≠ feature 级），且要凭空发明「哪个 task 的 summary 代表整组」的规则。组级落点一字段一职责，最简。
- **「非空」放 schema 还是 validate**：选 validate（T3）。JSON Schema 可用 `required` + `minLength: 1`，但 `required` 缺失与空串会各报一次、消息也不友好；放 T3 一条语义链能用一条清晰中文消息覆盖「缺字段/空串/纯空白」三种情形。故此处 schema 只声明字段合法、**不设 required**。
- **普通标量 vs 块标量**：选普通标量。TL;DR 短，块标量 `|` 会让 metadata.yaml 变啰嗦；若未来 summary 需要多段，再升级为块标量。
- **与 done 组 0014 共享 spec 测试模块的跨组重叠**：可接受、不规避。本组 T1–T4 各扩写一个 0014 已创建的 spec 测试模块（`tests/test_spec_model.py`/`test_spec_mutate.py`/`test_spec_cli.py`/`test_spec_validate.py`/`test_spec_render.py`），`spec validate` 会报这些文件「跨组重叠：0014, 0015」——这是 **warning 级、非 error**，因为 0014 已 done、本组只是在同一模块上追加新测试（演进既有模块的自然结果），不是两个在途 Task 争抢同一文件。组内 `files` 仍两两不重叠（schema+model / mutate+cli / validate / render / OVERVIEW.md），协同模式的去冲突保证不受影响。若强行为消除该 warning 而新建独立测试文件，反会割裂同一模块的测试、违背奥卡姆，故保留现状。

### Acceptance

带 summary 的 Metadata 经 dump_metadata → _load_metadata round-trip 内容保真；dump 输出键序为 title/issue/slug/summary；旧 metadata.yaml（无 summary 键）读出 summary == ''；schema 接受 string summary、拒非字符串；ruff + pytest 通过。

### Tests

- 单测（`tests/test_spec_model.py`）：构造带 summary 的 `Metadata`，`dump_metadata` 后重新 `_load_metadata`，round-trip 内容保真；
- 断言 dump 输出键序为 `title/issue/slug/summary`；
- 旧 metadata.yaml（无 summary 键）经 `_load_metadata` 读出 `summary == ""`（向后兼容）；
- schema 单测：带合法 summary 的 metadata 通过校验，summary 为非字符串类型时被 schema 拒。

### References

- issue #58「feat: spec 人类可读 summary」范围条目「把 group/feature 级的 summary 填上」。
- 现有数据层契约：`openagents/spec/model.py`（Metadata / dump_metadata / _load_metadata）、`openagents/spec/schema.py`（METADATA_SCHEMA）。

## T2 · 授权路径：spec new --summary（cli + mutate）

### Summary

让 `spec new` 必须带一段人话 summary 才能建组——把「写 TL;DR」做成建组的硬步骤，而非事后补。

### Motivation

地基字段（T1）立起来后，要保证它真的被填。最可靠的填入时机是建组当下：人在 `spec new` 时脑子里就有「这 feature 是啥」。把 `--summary` 做成必填参数，新建组从源头不会漏 summary；validate（T3）则是手改 metadata.yaml 时的兜底闸门。两层互补：fail-fast at authoring + gate at CI。

### Scope

授权写入路径：`mutate.create_group` 增 summary 入参（无默认、关键字传参）并写进 Metadata；`cli.py` 的 `new` 子命令增 `--summary`（required=True），`_cmd_new` 透传。薄路由，cli 不含业务逻辑。不含 schema/validate/render/迁移。

### Design

**薄路由原则**（cli 不含业务逻辑）：

1. `mutate.create_group` 增 `summary: str` 入参（无默认值，遵循 private/显式传参规范由调用方显式给），构造 `Metadata(title=title, issue=issue, slug=slug, summary=summary)`。其余逻辑（建目录、dump_metadata、render）不变。
2. `cli.py` 的 `new` 子解析器增 `--summary`（`required=True`）；`_cmd_new` 透传给 `create_group`。

**必填 vs 可选决策（D2）**：选必填。issue 把 summary 定位成 #59「人类监督闸门」的「地基」——地基不该可缺省。必填参数让「忘写」在建组那一刻就报错，比留到 CI validate 才发现更早、成本更低。代价是 `spec new` 命令行更长一点，可接受。

### Interface

- `mutate.create_group(*, specs_root, slug, title, issue, summary, number)` —— 新增 `summary` 形参（关键字、无默认）。
- `spec new <slug> --issue N --title T --summary S [--number NNNN]` —— `--summary` 必填，缺失时 argparse 报错、退出码 2。

### Tradeoffs

- **--summary 必填 vs 可选+validate 兜底**：选必填。可选更宽松但建组易漏；必填把 TL;DR 前置到建组当下，最契合「地基」定位。validate（T3）仍保留，覆盖手改场景。
- **create_group 的 summary 给不给默认值**：不给。遵循仓库规范（调用方显式传参），也避免「悄悄建出空 summary 组」。

### Acceptance

`spec new <slug> --issue N --title T --summary S` 退 0 且 metadata.yaml 落盘含该 summary；省略 `--summary` 时 argparse 报错、退出码 2；`create_group(..., summary=...)` 落盘正确；ruff + pytest 通过。

### Tests

- `tests/test_spec_mutate.py`：`create_group(..., summary="一句话")` 后读 metadata.yaml，summary 落盘正确。
- `tests/test_spec_cli.py`：`spec new ... --summary "x"` 退 0 且 metadata 含 summary；省略 `--summary` 时 `main` 触发 argparse 错误（SystemExit / 非 0）。

### References

- issue #58 范围「schema/validate 保证新建 spec 时 summary 非空」与意义「#59 人类监督闸门的地基」。
- 现有授权路径：`openagents/spec/mutate.py: create_group`、`openagents/spec/cli.py: _build_parser / _cmd_new`。

## T3 · 闸门：validate 强制 summary 非空

### Summary

给 validate 加一道闸门：任何组的 metadata.summary 为空（缺字段 / 空串 / 纯空白）就报 error，让 CI 挡住没填人话 TL;DR 的 spec。

### Motivation

T2 的 `--summary` 必填只能管住 `spec new` 这一条建组路径；一旦有人手改 metadata.yaml、或迁移期漏填，仍会冒出空 summary。validate 作为 CI 层的兜底闸门，把「每个 feature 都有人话 TL;DR」从「建组时的约定」升级为「仓库层面恒成立的不变量」——这正是 #59 人类监督闸门「看 spec 批准」能立起来的前提：闸门要能点头，先得保证有东西可看。

### Scope

在现有「六条校验链」（`validate.py` 模块 docstring 原话：第一条 JSON Schema + 五条语义链）之后追加**第七条校验链**——一条语义规则：每个组的 metadata.summary 去空白后为空 → error（覆盖缺字段与空串两种情形，一条清晰消息）。六链扩成七链。

### Design

validate 现在依序跑**六条校验链**（`validate.py` docstring 原话；决策 D7）：第一条是 JSON Schema 结构校验，第二至第六条是五条语义链；无 error 即 `ok=True`。本 Task 追加**第七条校验链** `_summary_checks`（语义维度上它是第六条语义规则，按代码 1–6 的整体校验链编号则排第七）：

- 遍历 `model.load_all` 出的每个 Group，取 `group.metadata.summary`；`.strip()` 为空 → 产出一条 `ValidationIssue(level=error, where="<NNNN>/metadata.yaml", message="metadata.summary 为空（每个 feature 必须有人话 TL;DR）")`。
- 在 `validate()` 主流程里把这条链的结果 `extend` 进 `issues`，紧跟在现有链之后；`ok` 的计算逻辑（任一 error 即不 ok）天然把它纳入。

**为什么放语义链而非 schema**（呼应 T1 的 D 决策）：`model._load_metadata` 把缺失的 summary 降级为 `""`，所以「缺字段」和「空串」在 model 层归一成同一种情况，一条 `.strip()` 非空检查即可同时覆盖，消息统一、友好；放 schema 的 `required`+`minLength` 会割裂成两类错误。validate 保持纯函数、不感知 git/GitHub（理念 10）。

### Interface

- 新增内部函数 `_summary_checks(*, groups: list[Group]) -> list[ValidationIssue]`，与现有 `_status_checks` 等同构。
- `validate(*, specs_root)` 行为扩展：summary 为空时报 error，`ValidationReport.ok=False`；`spec validate` 据此退出码 1。公共签名不变。

### Tradeoffs

- **error vs warning**：选 error。issue 验收明确「validate 在 summary 缺失时报错」，且这是 #59 监督闸门的硬前置，必须挡住 CI。
- **统一一条消息 vs 区分缺字段/空串**：选统一。对填写者而言「summary 没填」是同一件事，区分无价值、徒增噪音。

### Acceptance

summary 缺失/空串/纯空白 → validate 报 error 且 ok=False、退出码 1；非空 → 无此 error；ruff + pytest 通过。

### Tests

- `tests/test_spec_validate.py`：构造一个 metadata.summary 为空串的临时 specs 树 → report.ok=False 且 issues 含该 error；
- summary 为纯空白（如 "   "）→ 同样 error；
- summary 非空 → 无 summary 相关 error（其余链不受影响）；
- 多组中仅一组空 summary → 精确定位到该组的 where。

### References

- issue #58 验收「validate 在 summary 缺失时报错」。
- 现有校验框架：`openagents/spec/validate.py`（六链汇总、ValidationIssue/ValidationReport）。

## T4 · 人读视图：render 顶部 TL;DR 区块

### Summary

让 OVERVIEW.md 顶部多一段人话 TL;DR——逐 feature 列出 summary，人一眼看懂每个 feature 在干嘛，而不必先读密表。

### Motivation

OVERVIEW.md 现在开头就是「全局看板」密表（组/任务/状态/文件），对人极不友好。issue 要的是「OVERVIEW.md 顶部能一眼看懂每个 feature」。把 metadata.summary 渲染到顶部，OVERVIEW 才真正有了给人看的入口。

### Scope

仅 render：在 `render()` 的全局看板表之前插入一个 TL;DR 顶部区块，逐 feature 输出 `metadata.summary`；新增 `_render_tldr` 与 `_TLDR_HEADING`。保持纯函数与幂等，空仓库不报错。不改 schema/model/validate/数据内容。

### Design

`render()` 现在按顺序拼四块：标题/警示 → 全局看板 → 跨 feature 关系图 → 文件冲突 → 各 feature 详情。本 Task 在**全局看板表之前**插入第五块 `_render_tldr`：

- 标题用固定常量 `_TLDR_HEADING = "## TL;DR（人话速览）"`（与现有 `_BOARD_HEADING` 等同构，便于测试断言「区块齐全」）。
- 逐 group（已按编号排序）输出一段：`### {number} {title}` 后跟该组 `metadata.summary`。title 取 `metadata.title or metadata.slug`（与各 feature 详情段一致）。summary 经 `_cell`/换行归一以保持确定性。
- 放在 `render()` 的 blocks 列表里、`_render_board` 之前。

**位置决策（D3）**：选「顶部独立区块」，而非塞进底部「各 feature 详情」段。issue 反复强调「OVERVIEW.md **顶部**」「**顶部**一眼看懂」，独立顶部区块最直给；详情段在文末，达不到「顶部速览」效果。保持纯函数 + 幂等（决策 D3/D9）：同源数据两次 render 字节级一致；空仓库 groups=[] 时区块只剩标题，不报错。

### Interface

- 新增内部函数 `_render_tldr(*, groups: list[Group]) -> str`，签名风格同 `_render_board`。
- `render()` 的 blocks 列表在 `_render_board` 前插入 `_render_tldr(groups=groups)`。
- 新增常量 `_TLDR_HEADING`。输出仍以单换行连接、整体换行结尾（确定性不变）。

### Tradeoffs

- **顶部独立区块 vs 各 feature 详情段开头**：选顶部独立区块（贴合 issue「顶部」原话、速览集中）。代价是与文末详情段有轻度信息重复，但速览与详情读者诉求不同，可接受。
- **表格 vs 标题+段落**：选标题+段落。TL;DR 是成段人话，硬塞进表格单元格会被压成一行、可读性差；标题+段落更像「给人看的简介」。

### Acceptance

render 输出在看板表前含 TL;DR 区块且每个 feature 一段 summary；两次 render 字节级一致；空仓库不报错；ruff + pytest 通过。

### Tests

- `tests/test_spec_render.py`：渲染含 summary 的多组 specs 树 → 输出含 `_TLDR_HEADING`，且 TL;DR 区块出现在 `_BOARD_HEADING` 之前（位置断言）；
- 每个组的 summary 文本出现在 TL;DR 区块内；
- 幂等：连续两次 `render` 字节级一致；
- 空仓库：`render` 不报错且仍含 TL;DR 标题（骨架）。

### References

- issue #58 范围「spec render 在 OVERVIEW.md 顶部为每个 feature 输出这段 summary」、验收「OVERVIEW.md 顶部能一眼看懂每个 feature」。
- 现有渲染管线：`openagents/spec/render.py`（render / _render_board / 固定标题常量）。

## T5 · 迁移：补齐 14 个现有 spec 的 summary + 重渲染

### Summary

给现存全部 spec 组补一段人话 summary，并重渲染 OVERVIEW.md——把闸门（T3）从「会报错」变成「绿灯」，让本特性真正落地。

### Motivation

T3 的 validate 一旦上线，所有 summary 为空的现存组都会变红、CI 失败。本 Task 是必须与之同 PR 落地的「数据迁移」：逐组写出真实、人话、准确的 TL;DR（这是啥/为什么做/产出什么/不做什么），再 `spec render` 让 OVERVIEW 顶部 TL;DR 区块成型。没有它，特性是半成品（闸门挡住自己）。

### Scope

纯数据迁移：为 0001–0014 及本组 0015 的 `metadata.yaml` 逐一补写证据驱动的人话 summary，再 `spec render` 重生成 OVERVIEW.md、`spec validate` 确认 0 error。不改任何代码；唯一进 files 清单的产物是重生成的 OVERVIEW.md（各 metadata.yaml 的内容编辑见 design 的 files 归属说明，不进 files）。

### Design

**执行顺序**（依赖 T1 字段、T3 闸门、T4 渲染都已就位）：

1. 逐个为 `docs/specs/<NNNN-slug>/metadata.yaml`（0001–0014）补 `summary`——内容须**证据驱动**：读该组 metadata.title + tasks/ 真实内容后用大白话概括，不可臆造；每段覆盖「这是啥 / 为什么做 / 产出什么 / 不做什么」中至少前三项。
2. 为本组 0015 自己的 metadata.yaml 也补 summary。
3. 跑 `spec render` 重生成 `docs/specs/OVERVIEW.md`；跑 `spec validate` 确认 0 error。

**files 归属说明（关键）**：各组的 `metadata.yaml` **不列进**本 Task（或任何 Task）的 `files` 清单——`files` 是「Task 拥有的代码文件、与 `# Spec-NNNN` 注释一一对应」的协同模式去冲突机制，而批量内容编辑不是代码归属。本 Task 的 `files` 只列其唯一产物 `docs/specs/OVERVIEW.md`（render 重生成物）。各 metadata.yaml 的编辑作为本 Task 的执行内容、在 scope/design 里点名，不进 files，从而与其它 Task 的代码文件天然不冲突。

### Interface

无代码接口改动。产物：14 个现存组 + 本组的 `metadata.yaml` 各含非空 summary；重生成的 `OVERVIEW.md`。

### Tradeoffs

- **本组迁移 vs 拆独立 PR**：选同 PR。T3 闸门与迁移必须原子落地，否则 main 上 CI 直接红。
- **metadata.yaml 是否进 files 清单**：不进。若把 14 个 metadata.yaml 塞进 files，会与「文件不重叠」语义和「files=代码归属」约定打架；批量内容迁移用 scope 描述、单一产物 OVERVIEW.md 进 files 即可。

### Acceptance

所有现有组 metadata.yaml 有非空人话 summary；spec validate 全绿（0 error）；spec render 后 OVERVIEW.md 无 git drift；OVERVIEW 顶部一眼看懂每个 feature。

### Tests

- 验证手段是 `spec validate`（0 error，含 T3 的 summary 非空检查全过）与 `spec render` 后 `git diff --exit-code docs/specs/OVERVIEW.md`（无漂移）。
- 人工抽查若干组 summary 是否准确、是否大白话（面向人不面向 agent）。

### References

- issue #58 范围「把 group/feature 级的 summary 填上（迁移现有 spec 时补齐）」、验收「每个现有 spec 有非空、人类可读的 summary」。
- CLAUDE.md 理念 7「证据驱动」：summary 内容须基于各组真实 metadata/tasks。

