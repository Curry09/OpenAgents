---
number: "0024"
title: spec 转 rust-RFC 形态:总览先行 + 单 spec 自包含
issue: 69
slug: spec-rfc-form-overview-first
summary: 把 spec 改成 rust-RFC 9 段总览为主体(总览先行、单 spec 自包含),DAG + 文件分配收进 Reference-level;数据模型/校验/skill/README/orchestrator 一并对齐,回填 19 个存量 spec。
tasks:
  - id: T1
    title: spec 数据模型:组级 Overview 9 段 + Task 瘦身
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/spec/model.py
      - tests/test_spec_model.py
    scope: 新增 Overview 9 段 dataclass + Group.overview;Task 删重 prose,scope/acceptance 进 frontmatter;正文 parse/render 改为 rust 段名。
    acceptance: round-trip 保真组级 9 段 + task scope/acceptance;正文无 `## T` 小节、scope 进 frontmatter。
  - id: T2
    title: 校验质量门槛:必填段 + 自包含 warning + schema 瘦身
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/spec/schema.py
      - openagents/spec/validate.py
      - tests/test_spec_validate.py
    scope: TASK_SCHEMA required 加 files/acceptance、瘦 _PROSE_KEYS;validate 加必填四段非空(error) + 跨 spec 裸引用(warning)。
    acceptance: 必填段空 → error;「见 Spec-NNNN」→ warning 不破 ok;缺 acceptance → schema error。
  - id: T3
    title: spec new 9 段脚手架 + signpost/cli/mutate 适配
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/spec/signpost.py
      - tests/test_spec_signpost.py
      - tests/test_spec_cli.py
      - tests/test_spec_mutate.py
    scope: spec new 正文含 9 段标题;signpost 的 e2e 脚本线索从已删的 Task.tests 改为从组级 Overview 抽;修适配测试。
    acceptance: spec new 产出 9 段;signpost 从 Overview(Reference-level)抽 scripts/*.sh;pytest 全绿。
  - id: T4
    title: skill + references + README + orchestrator 对齐 rust-RFC
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - .claude/skills/spec-driven-development/SKILL.md
      - .claude/skills/spec-driven-development/references/task-fields.md
      - docs/specs/README.md
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: SKILL Phase 2 改为「先写 9 段总览 → 再 add-task」+ quality bar(自包含、软约定硬化);README 对齐 rust RFCs README;orchestrator 派活 prompt 同步。
    acceptance: skill/README 明确总览先行 + 单 spec 自包含两条规范;orchestrator 测试通过。
  - id: T5
    title: 回填 19 个存量 spec + e2e 脚本
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0024-rfc-form.sh
      - docs/specs/0023-retire-test-branch-main-advancing-release.md
    scope: 每个存量 spec 重写为 9 段总览 + frontmatter tasks(scope/acceptance),跨 spec 必要信息就地复述;补 e2e 脚本演示新流程。
    acceptance: spec validate 0 error;e2e 脚本 ruff+pytest+spec CLI 流程全绿。
---

# 0024 · spec 转 rust-RFC 形态:总览先行 + 单 spec 自包含

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把 OpenAgents 的 spec 从「Task DAG 骨架 + 每个 Task 各写 prose」改成「feature 级 rust-RFC 9 段总览为主体，DAG + 文件分配收进 Reference-level」，使任取一个 spec 单独可读、总览先行（issue #69）。

## Motivation

旧形态有两个可读性病根:① 单个 spec 不自包含——正文大量「见 Spec-00XX 决策 N」式跨 spec 引用,把关键设计依据甩到别处,读者必须翻好几个 spec 才能拼出完整语义;② 没有 feature 总览就直接拆 Task——`spec new` 后马上 `add-task`,组级只有一句 summary,读者上来面对一张 Task 表而没有整体认知。还有一个隐藏缺陷:旧数据模型根本不解析组级总览段(解析器只认 `## T<n>`),手写的总览会在下次 `spec render` 时被丢弃。

## Guide-level explanation

作者用 `spec new` 建组(自动铺 9 段脚手架)→ **先写满组级 rust-RFC 9 段总览**(Summary/Motivation/Guide-level/Reference-level/Drawbacks/Rationale and alternatives/Prior art/Unresolved questions/Future possibilities)→ **再** `spec add-task` 补工作分解行。读者拿到一个 spec,读完 9 段即懂这个 feature 全貌,无需打开别的 spec。

## Reference-level explanation

数据模型(`openagents/spec/model.py`):新增组级 `Overview` 9 段 dataclass + `Group.overview`;Task 删重 prose 字段,`scope`/`acceptance` 移入 frontmatter;正文 parse/render 从「`## T<n>` Task 小节」改为「`## <rust 段名>` 组级段」。校验(`schema.py`/`validate.py`):TASK_SCHEMA required 加 `files`/`acceptance`;新增「必填四段(Summary/Motivation/Reference-level/Rationale)非空 = error」「总览里跨 spec 裸引用 = warning」。`spec new` 产出 9 段脚手架;signpost 改从组级 Overview 抽 e2e 脚本。skill/README/orchestrator 文案对齐;19 个存量 spec 回填。

frontmatter 的 `tasks[].files` 保留为结构化机器源——这是单一 writer 所有权声明(理念 6),也是 issue #71 运行期 owner 检查的源。

Task 分解(files 互斥,各 Task 单一 writer):T1 数据模型;T2 校验质量门槛;T3 脚手架 + signpost/cli 适配;T4 skill+README+orchestrator;T5 回填 + e2e。

**端到端验证**:`bash scripts/e2e-spec-0024-rfc-form.sh`(ruff + pytest + spec CLI 流程演练)。

依赖 DAG:`T1 → T2 → T3`,T4/T5 依赖 T3。设计依据详见 dated 设计文档 docs/specs/2026-06-25-spec-rfc-form-design.md。

## Drawbacks

9 段对很小的 feature 可能偏重(多数段会很短或填「无」);一次性回填 19 个存量 spec 是个大 PR,review 面广。

## Rationale and alternatives

参考 rust-lang/rfcs 的 0000-template.md(9 段)与 README。**备选 A:单 freeform overview 字段**(不强制 9 段)——更省但难形成稳定可校验门槛,否决。**备选 B:去掉 Task、纯设计文档**——会废掉理念 6 的组内文件分配并行,否决;改为 RFC 9 段为主体 + frontmatter 保留 tasks DAG,机器可读性与人可读性兼得。**跨 spec 裸引用先 warning 而非 error**:避免一上来卡死存量回填,待全绿后可升 error。

## Prior art

rust-lang/rfcs:RFC 先于实现 + 一篇 RFC 自包含讲清一个 feature(Summary/Motivation/Guide-level/Reference-level/Drawbacks/Rationale/Prior art/Unresolved/Future 9 段)。本组取其模板与「自包含」理念,适配到 OpenAgents 的 frontmatter+tasks DAG。

## Unresolved questions

跨 spec 裸引用何时从 warning 升 error(待存量全绿后);`tasks[].acceptance` 是否对极轻的收尾 Task 也强制(当前:是,保持可验证)。

## Future possibilities

issue #71:把 Reference-level 的 files 分配从设计期声明推进到运行期 owner 强制(lease/CAS/capability),共享状态单一 writer + 版本化快照读。

