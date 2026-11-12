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
    scope: 仅数据层。schema.py 给 METADATA_SCHEMA 增 summary 属性（string，不设 required）；model.py 的 Metadata dataclass 增 summary 字段（放 slug 之后）、_load_metadata 兼容读旧文件（缺字段降级空串）、dump_metadata 固定键序 title/issue/slug/summary。不含 CLI、validate、render、内容迁移。
    acceptance: 带 summary 的 Metadata 经 dump_metadata→_load_metadata round-trip 内容保真；dump 输出键序为 title/issue/slug/summary；旧 metadata.yaml（无 summary 键）读出 summary == ''；schema 接受 string summary、拒非字符串；ruff + pytest 通过。
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
    scope: 授权写入路径。mutate.create_group 增 summary 入参（无默认、关键字传参）并写进 Metadata；cli.py 的 new 子命令增 --summary（required=True），_cmd_new 透传。薄路由，cli 不含业务逻辑。不含 schema/validate/render/迁移。
    acceptance: spec new <slug> --issue N --title T --summary S 退 0 且 metadata.yaml 落盘含该 summary；省略 --summary 时 argparse 报错、退出码 2；create_group(..., summary=...) 落盘正确；ruff + pytest 通过。
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
    scope: 在现有「六条校验链」之后追加第七条校验链 _summary_checks（一条语义规则）：遍历每个 Group 取 metadata.summary，.strip() 后为空 → 产出 error（覆盖缺字段/空串/纯空白，一条清晰中文消息），where 定位到该组 metadata.yaml。validate 保持纯函数、不感知 git/GitHub。不改 schema/model/render/迁移。
    acceptance: summary 缺失/空串/纯空白 → validate 报 error 且 ok=False、退出码 1；非空 → 无此 error；多组中仅一组空 summary 精确定位到该组的 where；ruff + pytest 通过。
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
    scope: 仅 render。在 render() 的全局看板表之前插入 TL;DR 顶部区块 _render_tldr，逐 group 输出 `### {number} {title}` + metadata.summary；新增常量 _TLDR_HEADING。保持纯函数与幂等，空仓库不报错。不改 schema/model/validate/数据内容。
    acceptance: render 输出在看板表前含 TL;DR 区块且每个 feature 一段 summary、位置在 _BOARD_HEADING 之前；两次 render 字节级一致；空仓库不报错且仍含 TL;DR 标题；ruff + pytest 通过。
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
    scope: 纯数据迁移。为 0001–0014 及本组 0015 的 metadata.yaml 逐一补写证据驱动的人话 summary（这是啥/为什么做/产出什么/不做什么），再 spec render 重生成 OVERVIEW.md、spec validate 确认 0 error。各 metadata.yaml 的内容编辑是执行内容，不进 files（files 仅列唯一产物 OVERVIEW.md），从而与其它 Task 代码文件天然不冲突。不改任何代码。
    acceptance: 所有现有组 metadata.yaml 有非空人话 summary；spec validate 全绿（0 error，含 T3 的 summary 非空检查全过）；spec render 后 OVERVIEW.md 无 git drift；OVERVIEW 顶部一眼看懂每个 feature。
---

# 0015 · spec 人类可读 summary：填 group 级 summary 字段 + render 大白话 TL;DR

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给每个 spec 加一段**面向人的大白话 TL;DR**，让人不必先读密表就能一眼看懂「这个 feature 在干嘛」。落点是 **group/feature 级元数据** `metadata.yaml` 的新字段 `summary`（与 `title`/`issue`/`slug` 并列），而非复用 per-Task 的 `summary` prose。本组从数据层立起这个字段（T1），到建组时必填（T2 `spec new --summary`）、CI 闸门强制非空（T3 validate）、人读视图顶部逐 feature 展示（T4 render TL;DR 区块），再到迁移补齐全部现存 spec 并重渲染（T5）。这是 issue #59「人类监督闸门」的地基——闸门要能点头，先得保证有给人看的东西。

## Motivation

**现状：spec 没有给人看的入口。** 一个 spec 现在：per-Task 的 `summary` prose 字段是 task 粒度、且全空着；`OVERVIEW.md` 开头就是一张 task-id/文件/状态的密表（全局看板），对人极不友好。人想一眼搞懂「这个 spec 在干嘛」做不到。

**为什么要改。** TL;DR 是 **feature/组** 级的概念（「这个 feature 是啥、为什么做、产出什么、不做什么」），不是 task 级。issue #58 的原话就是「把 group/feature 级的 summary 填上」，并把它定位成 #59「人类监督闸门」的**地基**——人要「看 spec 批准」，先得有一段人话可看。因此需要：(1) 在组级元数据立一个 summary 字段作为唯一存储位；(2) 保证它真的被填（建组必填 + CI 闸门双层兜底）；(3) 把它渲染到 OVERVIEW 顶部；(4) 迁移补齐所有现存 spec，否则闸门一上线就把仓库自己卡红。

## Guide-level explanation

对使用者：

- 建组时，`spec new <slug> --issue N --title T --summary S` 的 `--summary` 变为**必填**——把「写 TL;DR」做成建组的硬步骤，而非事后补。漏写会在建组那一刻被 argparse 拦下（退出码 2），而不是拖到 CI 才发现。
- CI 层，`spec validate` 多一道闸门：任何组的 `metadata.summary` 为空（缺字段 / 空串 / 纯空白）就报 error，把「每个 feature 都有人话 TL;DR」从「建组约定」升级为「仓库恒成立的不变量」。
- 人读时，`OVERVIEW.md` **顶部**多一段「TL;DR（人话速览）」区块，逐 feature 列出 `summary`，一眼看懂每个 feature 在干嘛，而不必先啃下面的密表。

两层填入机制互补：fail-fast at authoring（T2 必填）+ gate at CI（T3 validate 兜底手改/迁移漏填场景）。

## Reference-level explanation

落到改动，分解为 5 个 Task（DAG 见下；`files` 互斥，各 Task 单一 writer）：

1. **T1 数据层**（无依赖，地基）— `openagents/spec/schema.py`、`openagents/spec/model.py`、`tests/test_spec_model.py`。`schema.py` 的 `METADATA_SCHEMA.properties` 增 `summary: {type: string}`（因 metadata schema 是 `additionalProperties: False`，不声明则任何带 summary 的文件被判 schema 错——这是 T2/T5 写入的前置）；**不设 `required`**，「非空」语义交给 T3 的语义链统一负责。`model.py` 的 `Metadata` frozen dataclass 增 `summary: str` 字段（放 slug 之后，给默认空串以兼容旧调用点/旧文件）；`_load_metadata` 增 `summary=str(raw.get("summary", ""))`（缺字段降级空串，迁移期平滑读旧文件）；`dump_metadata` 的 payload 从 `[title, issue, slug]` 扩成 `[title, issue, slug, summary]`，键序固定——这是 `spec new`/迁移写出的单一来源，保证不漂移。summary 用普通标量（TL;DR 短，块标量会让 metadata.yaml 啰嗦）。
2. **T2 授权路径**（依赖 T1）— `openagents/spec/mutate.py`、`openagents/spec/cli.py`、`tests/test_spec_mutate.py`、`tests/test_spec_cli.py`。`mutate.create_group` 增 `summary: str` 入参（无默认值，遵循仓库「调用方显式传参」规范），构造 `Metadata(..., summary=summary)`；其余逻辑（建目录、dump_metadata、render）不变。`cli.py` 的 `new` 子解析器增 `--summary`（`required=True`），`_cmd_new` 透传——薄路由，cli 不含业务逻辑。
3. **T3 闸门**（依赖 T1）— `openagents/spec/validate.py`、`tests/test_spec_validate.py`。validate 现依序跑「六条校验链」（第一条 JSON Schema 结构校验 + 五条语义链），无 error 即 `ok=True`。本 Task 追加新增内部函数 `_summary_checks(*, groups: list[Group]) -> list[ValidationIssue]`（与现有 `_status_checks` 同构）：遍历每个 Group 取 `group.metadata.summary`，`.strip()` 为空 → 产出 `ValidationIssue(level=error, where="<NNNN>/metadata.yaml", message="metadata.summary 为空（每个 feature 必须有人话 TL;DR）")`；在 `validate()` 主流程把结果 `extend` 进 `issues`，紧跟现有链之后，`ok`（任一 error 即不 ok）天然纳入。因 `_load_metadata` 把缺字段归一为 `""`，一条 `.strip()` 检查即可同时覆盖「缺字段/空串/纯空白」，消息统一友好。validate 保持纯函数、不感知 git/GitHub。
4. **T4 人读视图**（依赖 T1）— `openagents/spec/render.py`、`tests/test_spec_render.py`。`render()` 现按序拼：标题/警示 → 全局看板 → 跨 feature 关系图 → 文件冲突 → 各 feature 详情。本 Task 在**全局看板表之前**插入 `_render_tldr(*, groups)`：标题用固定常量 `_TLDR_HEADING = "## TL;DR（人话速览）"`；逐 group（已按编号排序）输出 `### {number} {title}`（title 取 `metadata.title or metadata.slug`）+ 该组 `metadata.summary`（经 `_cell`/换行归一以确定性）。保持纯函数 + 幂等（同源数据两次 render 字节级一致），空仓库 `groups=[]` 时区块只剩标题、不报错。
5. **T5 迁移**（依赖 T3、T4）— `docs/specs/OVERVIEW.md`。逐个为 `docs/specs/<NNNN-slug>/metadata.yaml`（0001–0014）补 `summary`——内容须**证据驱动**：读该组 metadata.title + tasks/ 真实内容后用大白话概括，每段覆盖「这是啥 / 为什么做 / 产出什么 / 不做什么」中至少前三项；为本组 0015 自己也补；跑 `spec render` 重生成 `OVERVIEW.md`、`spec validate` 确认 0 error。**files 归属说明（关键）**：各组 `metadata.yaml` **不列进**任何 Task 的 `files`——`files` 是「Task 拥有的代码文件、与 `# Spec-NNNN` 注释一一对应」的协同去冲突机制，批量内容编辑不是代码归属；本 Task 的 `files` 只列唯一产物 `OVERVIEW.md`（render 重生成物），各 metadata.yaml 的编辑作为执行内容在 scope 里点名，从而与其它 Task 天然不冲突。

**端到端验证**：以 `spec validate`（0 error，含 T3 的 summary 非空检查全过）+ `spec render` 后 `git diff --exit-code docs/specs/OVERVIEW.md`（无漂移）作为验证手段；本组无独立 `scripts/*.sh` e2e 脚本，验证经 ruff + pytest 与上述 spec 自检完成。

依赖 DAG：`T1 → T2`，`T1 → T3`，`T1 → T4`，`T3 → T5`，`T4 → T5`。

## Drawbacks

- 顶部 TL;DR 区块与文末「各 feature 详情」段有轻度信息重复——但速览与详情读者诉求不同，可接受。
- `spec new --summary` 必填让命令行更长一点；迁移期需为全部现存组逐一补写真实人话 summary，有一次性人工成本（但这正是特性价值所在）。

## Rationale and alternatives

- **落点：组级 metadata vs 复用 per-Task summary**。选组级。复用 per-Task 改动看似更小，但语义错配（task 级 ≠ feature 级），且要凭空发明「哪个 task 的 summary 代表整组 / 如何聚合多个 task summary」的额外规则，违反奥卡姆。组级落点一字段一职责、最简，per-Task `summary` 字段原样保留、互不影响。
- **「非空」放 schema 还是 validate**。选 validate（T3）。JSON Schema 可用 `required` + `minLength: 1`，但「缺字段」与「空串」会各报一次、消息不友好；放 T3 一条语义链能用一条清晰中文消息统一覆盖「缺字段/空串/纯空白」三种情形。故 T1 的 schema 只声明字段合法、不设 required。
- **--summary 必填 vs 可选 + validate 兜底**。选必填。issue 把 summary 定位成「地基」，地基不该可缺省；必填把「忘写」前置到建组当下，比拖到 CI 才发现更早、成本更低。validate 仍保留，覆盖手改场景。
- **render 位置：顶部独立区块 vs 各 feature 详情段开头**。选顶部独立区块——issue 反复强调「OVERVIEW.md **顶部**一眼看懂」，独立顶部区块最直给；详情段在文末达不到速览效果。
- **TL;DR 渲染形态：表格 vs 标题 + 段落**。选标题 + 段落。TL;DR 是成段人话，硬塞表格单元格会被压成一行、可读性差。
- **迁移与 T3 闸门：同 PR vs 拆独立 PR**。选同 PR 原子落地——否则 T3 一上线 main 上 CI 直接红（闸门挡住自己）。

## Prior art

- rust-RFC（rfcs.rs）的 RFC 模板以一段 Summary 开篇，让读者先抓住要点再读细节；本 feature 把同样的「人话速览先行」思路引入 spec 的 OVERVIEW 顶部。
- 与 done 组 0014 共享 spec 测试模块：本组 T1–T4 各扩写一个 0014 已创建的测试模块（`test_spec_model.py` 等），`spec validate` 会报这些文件「跨 feature 重叠：0014, 0015」——这是 warning 级、非 error，因 0014 已 done、本组只是在同一模块追加新测试，组内 `files` 仍两两不重叠，协同去冲突保证不受影响。

## Unresolved questions

无。字段落点、必填/闸门分工、render 位置、迁移归属（metadata.yaml 不进 files）均已在本组确定。

## Future possibilities

- 若未来 summary 需要承载多段 Markdown，可把普通标量升级为块标量 `|`。
- TL;DR 区块可进一步用于 #59 的人类监督闸门 UI（前端呈现成果、人看 summary 做宏观批准）。

