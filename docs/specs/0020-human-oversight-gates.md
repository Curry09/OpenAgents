---
number: "0020"
title: 人类监督闸门：提 issue 前需求对齐 + vigil 分级 --hold 闸控
issue: 59
slug: human-oversight-gates
summary: 给 OpenAgents 加两道人类监督闸门：提 issue 前的「需求对齐」（把模糊想法复述成 做什么X/边界Y/不做Z 让人确认），以及 vigil 自治循环的分级 --hold 闸（在 spec 批准、PR 合并等关键点停下等人点头）。让人从盯细节转向把控宏观；只在关键节点插入可配置暂停，不改既有 issue→PR 自动流程的内部逻辑。
tasks:
  - id: T1
    title: 前门对齐模块：把模糊想法复述成 X/边界Y/不做Z
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/align.py
      - tests/test_align.py
    scope: 新建纯模块 openagents/align.py：给定 issue 草稿（title/body），调注入的 backend 用大白话复述成结构化「我理解你要 X，边界是 Y，不做 Z」三段，供调用方拿去给人确认。仅做复述渲染 + 确认判定，不碰 GitHub、不碰 CLI argparse。复述生成（要 backend）与确认判定（纯谓词）拆成两个函数，便于 --yes 自动化路径跳过复述。模块 docstring 引用 Spec-0020。
    acceptance: restate(*, draft, backend) 给定 issue 草稿，调注入 backend 返回含 want(X)/boundary(Y)/non_goals(Z) 三段的 Alignment，其人类可读渲染含三段标识；确认判定是独立纯谓词，肯定应答→放行、否定/空应答→不放行，且不调 backend；模块不含任何 GitHub/argparse/stdin 读取，backend 以关键字参数注入；tests/test_align.py 以打桩 backend 全绿、hermetic（不触达真实 LLM）。
  - id: T2
    title: hold 配置模型：解析 spec,merge 成闸门集合
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/hold.py
      - tests/test_hold.py
    scope: 新建纯模块 openagents/hold.py：把 --hold 的逗号分隔字符串（'spec'/'merge'/'spec,merge'/空）解析成不可变 Hold 配置（含 at_spec/at_merge 谓词）。逐 token 去空白、归一化大小写映射，空/None→全不停（默认 vigil 行为），非法 token 立即抛携带合法取值的清晰错误。无任何 I/O、无 argparse、无 GitHub。模块 docstring 引用 Spec-0020。
    acceptance: parse_hold(*, raw)：''/None→默认 Hold(at_spec=at_merge=False)；'spec'→仅 at_spec；'merge'→仅 at_merge；'spec,merge' 与 'merge,spec'→两者皆 True；未知 token（如 'foo'）→抛 ValueError 类错误并列出合法取值(spec/merge)；多余空格/大小写（如 ' Spec , Merge '）归一化后正确解析；Hold 为不可变值对象仅暴露 at_spec/at_merge；tests/test_hold.py 全绿（纯函数）。
  - id: T3
    title: 流水线分级闸：hold 穿到 poll 两道闸分流
    status: done
    priority: P0
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/vigil.py
      - openagents/messages.py
      - tests/test_vigil.py
      - tests/test_messages.py
    scope: vigil.run 接收 Hold 并透传到 messages.poll；messages 在 spec 闸(_process_rfc_review)与 merge 闸(_process_coding)按 Hold 分流：hold.at_spec→停掉自动 reviewer、只认人工 rfc-approved label；hold.at_merge→CI 绿 + review PASS 后不自动 merge_pr，留给人。默认 Hold（全不停）行为与现状逐字节一致。hold 走 poll 方法参数而非 Messages 构造参数，保持 T3/T4 文件边界干净。改动处引用 Spec-0020。
    acceptance: vigil.run 接收 hold 并逐轮透传给 messages.poll（可断言 poll 收到的 hold 即传入值）；spec 闸 hold.at_spec：无 rfc-approved label→不调自动 reviewer/不打 label/不 implement（停在 rfc-review），带人工 label→照常 implement；merge 闸 hold.at_merge：CI 绿 + PASS→不调 merge_pr、状态不变，人手动 merge 后下一轮 is_merged 分支照常 reconcile 成 done；spec,merge 组合两闸各自停；默认 Hold 下既有自动评审/自动合并用例全绿、零回归；tests/test_vigil.py + tests/test_messages.py 全绿。
  - id: T4
    title: CLI 接线：issue 前门对齐 + vigil --hold 标志
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: 在 cli.py 这一处接线层：(1) openagents issue 在调 create_issue 前插一轮对齐确认——用 T1 align 复述、人确认才落 issue；加 --yes 跳过供自动化。(2) vigil 子命令加 --hold 标志，用 T2 parse_hold 解析成 Hold（None→默认全不停），传给 T3 的 vigil.run(hold=...)；非法值经既有异常通道转一行提示。align/hold 延迟 import。仅做参数解析与分发，业务逻辑下沉到 align/hold/vigil。改动处引用 Spec-0020。
    acceptance: openagents issue 默认路径建 issue 前调 align.restate 复述并请人确认，确认(y)才 create_issue、否定(n)则不建且非零退出；openagents issue --yes 跳过复述与确认直接 create_issue；openagents vigil --hold spec|merge|spec,merge 用 parse_hold 解析后以该 Hold 调 vigil.run(hold=...)，无 --hold→默认全不停；--hold 非法值→干净一行错误 + 非零退出（不 traceback）；cli.py 仅做参数解析/分发；tests/test_cli.py 全绿、hermetic（打桩 align/github/vigil）。
  - id: T5
    title: e2e 脚本：演示停在 spec → 人批 → 继续
    status: done
    priority: P2
    tags: []
    depends-on:
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0020-hold-gate.sh
    scope: 新增离线 e2e 脚本 scripts/e2e-spec-0020-hold-gate.sh（沿用现有 scripts/e2e-*.sh 风格，打桩/本地 state 模拟 GitHub，CI 可跑）：演示 vigil --hold spec 在 spec 写完后停住等人；模拟人工打 rfc-approved label 后再 poll 一轮，流水线继续进入 coding。脚本顶部注释引用 Spec-0020，并点明 spec 批准依据（OVERVIEW summary）的 issue-58 软依赖。
    acceptance: scripts/e2e-spec-0020-hold-gate.sh 离线可独立 bash 运行（打桩/本地 State 模拟 GitHub、无需凭证、CI 可跑可重复）；演示时间线：以 --hold spec 跑一轮→断言停在 spec 闸（未自动评审/未自动打 label/未 implement，状态仍 rfc-review），模拟人工打 rfc-approved label 后再跑一轮→断言继续推进（走 implement、进入 coding）；打印人类可读的「停→批→继续」轨迹，全部断言通过则退出码 0、任一失败即非零退出；与既有 e2e 脚本同目录、同命名规约(e2e-spec-NNNN-<slug>.sh)。
---

# 0020 · 人类监督闸门：提 issue 前需求对齐 + vigil 分级 --hold 闸控

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给 OpenAgents 加两道**人类监督闸门**，把人的把关从「事后审 PR」前移到意图层：

1. **前门对齐**——提 issue 前先让 agent 用大白话把你的模糊想法复述成「我理解你要 **X**，边界是 **Y**，不做 **Z**」三段，你点头才正式建 issue（`--yes` 可跳过供自动化）。
2. **vigil 分级 `--hold` 闸**——给自治循环加一个可选标志，让流水线在关键节点停下等人：`--hold spec` 写完 spec、动代码前停住，只认人工 `rfc-approved` label 才放行；`--hold merge` 一路自动到 PR、把最后 merge 留给人；不带 `--hold` 时一切照旧全自动。

让人从盯细节转向把控宏观；只在关键节点插入可配置暂停，**不改既有 issue→PR 自动流程的内部逻辑**。

## Motivation

**现状（完整复述，不要求读者去翻别的 spec）。** OpenAgents 此前的 poll 状态机已把人的触点收敛到「提 issue」与「promote / release」：issue 被领取后 agent 起草 spec、开 draft PR；spec 闸由 agent reviewer **自动评审、自动打 `rfc-approved` label** 放行进 coding；merge 闸在 **CI 全绿 + reviewer PASS** 后**自动 merge**。整条 issue→PR→合并链路全自动，人原则上不在中途介入。

**问题：唯一真实检查点太靠后。** 在这套全自动链路里，人**唯一**的真实把关是审 PR——也就是代码全写完之后才暴露理解偏差，这是最贵的纠错点。CLAUDE.md 理念 5「人负责宏观把控、不管细节」缺两类闸门：

- **意图层闸门**：想法落成正式 issue 之前，没有一道用人能读懂的话把范围对齐的关口，模糊需求会一路带到代码里。
- **分级监督**：默认全自动很好，但人有时想在 spec 批准或 PR 合并这种**意图节点**上重新插回把关——当前没有这个开关，要么全自动、要么没有中间档。

issue #59 要的正是这两道闸：前门**需求对齐** + vigil **可选分级 `--hold`**。关键约束是「分级」——默认行为一个字节都不能变，只有人显式选择时才在对应闸门停下。

## Guide-level explanation

对使用者，新增两个可见行为，默认体验不变：

| 场景 | 命令 | 行为 |
|------|------|------|
| 提 issue | `openagents issue <title> [--body]` | 建 issue 前先打印 agent 的三段复述「要做 X / 边界 Y / 不做 Z」，请你 y/n 确认；确认才建，否定则干净中止不建 |
| 自动化建 issue | `openagents issue <title> --yes` | 跳过复述与确认，直接建（供 vigil/CI 等脚本路径） |
| 默认自治循环 | `openagents vigil` | 与以前逐字节一致，全自动 |
| 停在 spec 闸 | `openagents vigil --hold spec` | 写完 spec、动代码前停住，只认人工打的 `rfc-approved` label 才放行 |
| 停在 merge 闸 | `openagents vigil --hold merge` | 一路自动到 PR，CI 绿 + 评审过后**不自动合**，把最后 merge 留给人 |
| 两道都停 | `openagents vigil --hold spec,merge` | 两道闸各自按规则停 |

`--hold` 非法值（如拼错 `spc`）会得到一行干净错误 + 非零退出，而非静默被当成「全不停」悄悄丢掉监督。

## Reference-level explanation

落到改动，分解为 5 个 Task（DAG 见下；`files` 互斥，各 Task 单一 writer）：

1. **T1 前门对齐模块**（无依赖）— 新建纯模块 `openagents/align.py`：`restate(*, draft, backend) -> Alignment` 给定 issue 草稿，调**注入的 backend**（与 Orchestrator 同一 backend 抽象，依赖注入而非 import 具体实现）用大白话复述成 `want(X)/boundary(Y)/non_goals(Z)` 三段结构化对象，`Alignment` 带稳定的人类可读渲染。**复述生成**（要 backend）与**确认判定**（纯谓词，输入人的应答、输出是否放行）拆成两个函数：便于分别测试，也让 T4 的 `--yes` 路径跳过复述、无需构造 backend。模块不含任何 GitHub / argparse / stdin。
2. **T2 hold 配置模型**（无依赖）— 新建纯模块 `openagents/hold.py`：`Hold` 是 frozen 值对象，只携带 `at_spec` / `at_merge` 两个布尔意图（对应 issue 列出的两道闸，刻意不做开放枚举以保持最小）。`parse_hold(*, raw) -> Hold` 切分逗号串、去空白、归一化大小写逐 token 映射；空/None → 默认全不停；未知 token → 抛 ValueError 类错误并列出合法取值。独立模块而非 argparse `type=` 内联，便于 CLI 与测试共用同一份解析、避免字符串散落多处漂移。
3. **T3 流水线分级闸**（依赖 T2）— `vigil.run(*, ..., hold)` 新增 `hold` 关键字参数（默认全不停实例，向后兼容现有调用），逐轮透传给 `messages.poll(*, hold)`；vigil 自身不消费 Hold，仍是薄调度循环，只把意图带到真正分流的 messages 层。messages 两道闸按 Hold 分流：**spec 闸 `_process_rfc_review`**——`at_spec` 时跳过自动 reviewer，只保留「带人工 `rfc-approved` label 才 implement，否则本轮什么都不做、停在 spec 闸等人」；**merge 闸 `_process_coding`**——`at_merge` 时 CI/iterate/评审照跑，但 reviewer PASS 后不调 `merge_pr`、停在「待人 merge」（PR 保持 open），人手动 merge 后下一轮 `is_merged` 分支照常 reconcile 成 done（复用既有逻辑、无需新增 State）。分流是在既有路径上「加一个 `if hold.at_xxx` 提前 return」，默认分支走原代码不变。hold 走 poll **方法参数**而非 Messages 构造参数，避免改动 cli 的 `_messages_for` 工厂、保持 T3/T4 文件边界干净。
4. **T4 CLI 接线**（依赖 T1、T2、T3）— cli.py 是人的唯一命令入口、仅做参数解析与分发。`_cmd_issue` 在调 `github.create_issue` 之前插一步：构造 backend、调 T1 `align.restate` 拿复述、打印给人、读 y/n，确认才建、否定干净中止；新增 `--yes` 开关跳过复述与确认直接建。`vigil` 子命令加 `--hold`（逗号分隔串，默认 None），handler 里用 T2 `parse_hold` 解析成 Hold（None → 全不停）传给 `vigil.run(hold=...)`；解析报错由既有 `_run` 的异常→一行提示通道兜。align / hold 延迟 import，保持 cli 顶层轻、测试可打桩。**注**：issue 对齐与 vigil `--hold` 都改 cli.py 这一个文件，按 spec 协同模式「Task 间文件不重叠」的约束，二者必须合在同一 Task（cli.py 是单一接线点）。
5. **T5 e2e 脚本**（依赖 T3、T4）— 新增离线脚本 `scripts/e2e-spec-0020-hold-gate.sh`，沿用既有 `scripts/e2e-*.sh` 范式（打桩/本地 State 模拟 GitHub 远端，离线驱动 vigil/poll，断言可观测信号，不触达真实 gh、CI 可跑可重复）。演示时间线：① 准备一个处于 rfc-review 阶段、已开 draft PR、无 `rfc-approved` label 的 run；② 以 `--hold spec` 跑一轮 → 断言停在 spec 闸（未自动评审、未自动打 label、未 implement，状态仍 rfc-review）；③ 模拟人工给 PR 打上 `rfc-approved` label；④ 再跑一轮 → 断言继续推进（走 implement、进入 coding）；⑤ 打印人类可读的「停→批→继续」轨迹、退出码 0。

**端到端验证**：`bash scripts/e2e-spec-0020-hold-gate.sh`（离线打桩，演示「停在 spec → 人批 → 继续」完整时间线）。

依赖 DAG：`T2 → T3`，`T1 → T4`，`T2 → T4`，`T3 → T4`，`T3 → T5`，`T4 → T5`。T1、T2 可并行起步。

## Drawbacks

- 给 `openagents issue` 这条线引入 backend 依赖（复述用 LLM）——用注入而非硬编码缓解，测试以打桩 backend 保持 hermetic。
- T4 因「同改 cli.py」被迫把两个特性（issue 对齐、vigil `--hold`）合进一个 Task，单 Task 跨了两个关注点；以「cli 纯接线、逻辑都在被依赖模块」缓解。
- 两道 `--hold` 闸增加了流水线的可配置分支，需以默认 Hold 的回归用例守住「默认零回归」。

## Rationale and alternatives

- **LLM 复述 vs 确定性模板**（选 LLM）：模板零依赖、可离线，但只能机械回显 title/body，给不出「归纳出的边界与非目标」，违背 issue #59「用大白话复述、重新组织」的原意。选 LLM 复用既有 backend；用注入 + 打桩控制依赖与可测性。
- **复述生成与确认判定合并 vs 拆分**（选拆分）：拆分多一个函数，但让 `--yes` 自动化路径无需 backend、让两条逻辑各自可测。
- **Hold 用两个布尔字段 vs 开放枚举 set**（选两个布尔）：set 更「可扩展」，但当前只有两道闸、issue 未要求更多，开放集合是过度设计；两个具名谓词读起来更直白、消费方分支更清晰。将来闸门增多再重构。
- **解析时严格报错 vs 静默忽略未知 token**（选严格）：静默忽略会让拼错的 `--hold spc` 被当成「全不停」悄悄丢掉监督，违背安全默认；严格报错让人立刻看到。
- **hold 走 poll 方法参数 vs Messages 构造参数**（选方法参数）：构造参数要改 cli 的 `_messages_for` 工厂、把 cli.py 卷进 T3 边界；方法参数让 hold 顺着 vigil→poll 调用链走，文件归属干净，也更贴合「hold 是本次运行的意图、非实例固有属性」。
- **spec 闸 hold 时停掉 reviewer vs 保留 reviewer 仅不自动批**（选停掉）：保留会持续消耗 backend、且与「等人批」语义混淆；停掉最简、最省、语义最干净——「hold spec 就是把这道闸完全交给人」。
- **e2e 离线 mock vs 真实 GitHub 往返**（选离线）：真实往返需凭证、不可在 CI 重复、慢且脆；既有全部 e2e 脚本均为离线打桩，沿用同范式保证可发现、可复跑、可纳入 CI。
- **issue 对齐默认开 vs 默认关**（选默认开、`--yes` 关）：issue #59 验收要求「创建前有一轮对齐确认（可被 `--yes` 跳过）」，把安全默认留给人、把跳过权交给脚本。

## Prior art

- 「先把模糊需求复述对齐再动手」是需求工程里的常规做法（restate / reflect back），本 feature 取其轻量形态：一段三段式复述 + 人点头，不引入重型需求文档。
- 「单点定义、多处引用」的解析模型与既有、与本组无编号关联的 RFC-0015「流程标签单一来源」属同构思路——仅借鉴其单点定义模式，避免同一字符串散落多处漂移，**不**与本组 Spec-0020 同号或同范围。

## Unresolved questions

- 「看 spec 批准」依赖 #58 的人类可读 summary：人对着一坨技术 task YAML 没法点头。本组只做闸控机制，**不**实现 summary；spec 闸停下时人看到的批准依据（OVERVIEW summary）由 #58 / Spec-0014 体系提供。若 #58 未就绪，`--hold spec` 仍能停/放行，只是人的阅读体验降级——T5 e2e 与上线说明里点明这条软依赖。

## Future possibilities

- `--hold` 可扩展更多闸门（如发版前确认），但需在「两个具名布尔」与「开放枚举集合」之间重新权衡，待真实需求出现再做。
- spec 闸的 hold 之外，可由独立命令提供「reviewer 预审意见」能力，给人批前参考，不塞进本闸以保持其语义干净。

