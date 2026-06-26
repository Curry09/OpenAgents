---
number: "0025"
title: brownfield 反向补全 RFC:扫存量代码生成 9 段 RFC 草稿
issue: 73
slug: brownfield-backfill-rfc
summary: 新增 backfill-rfc <path> 子命令:扫存量代码 → 派 coding agent 反推 rust-RFC 9 段 spec 草稿(必填四段据实回填、难反推段标待补)→ 经 spec validate 后开 draft PR 交人评审,让 brownfield 仓库接入 RFC 驱动闭环。
tasks:
  - id: T1
    title: 代码盘点助手:扫 path 产出 inventory
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backfill.py
      - tests/test_backfill.py
    scope: 新模块 backfill.py:校验 path 存在(不存在/空目录报错),产出文件清单/模块docstring/公开符号 inventory,并据 path 形态确定一份 spec 的范围;纯函数无副作用。
    acceptance: 给定存在的 path 返回含文件清单与模块结构的 inventory;path 不存在或空目录抛错;pytest 覆盖单文件与目录两种形态。
  - id: T2
    title: 编排方法 backfill_rfc + 反向 RFC prompt
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/orchestrator.py
      - tests/test_orchestrator.py
    scope: 新增 _BACKFILL_RFC_TASK 模板 + Orchestrator.backfill_rfc(path,base):盘点(调T1)→worktree→backend跑反向prompt→spec validate门控(非0不开PR)→commit→draft PR;复用 start_rfc 骨架与 create_pr(draft=True)。
    acceptance: backfill_rfc 走通 盘点→后端→validate门控→draft PR;spec validate 非0时不开 PR;prompt 含「必填四段据实写满、难反推段标待补」约束;test_orchestrator 通过。
  - id: T3
    title: CLI 接线 backfill-rfc <path>
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: 新增 backfill-rfc subparser(位置参数 path + --base 默认 main)+ _cmd_backfill_rfc,转发到 Orchestrator.backfill_rfc;薄路由不含业务逻辑。
    acceptance: openagents backfill-rfc <path> 可解析并转发到 backfill_rfc;--base 默认 main;test_cli 覆盖子命令解析。
  - id: T4
    title: e2e 脚本演示反向补全闭环
    status: done
    priority: P2
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0025-backfill-rfc.sh
    scope: 新增 e2e 脚本:ruff + pytest + 对无 spec 的样例路径跑 backfill-rfc,断言产出 9 段草稿且 spec validate 0 error。
    acceptance: bash scripts/e2e-spec-0025-backfill-rfc.sh 全绿:ruff/pytest 通过,样例路径反向补全产出可过 spec validate 的 9 段草稿。
---

# 0025 · brownfield 反向补全 RFC:扫存量代码生成 9 段 RFC 草稿

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给 OpenAgents 增加一条「反向补全」能力:新增子命令 `openagents backfill-rfc <path>`,扫描指定路径下的存量代码 → 派一个 coding agent(Claude Code 等后端)读代码、反推出一份 rust-RFC 9 段 spec 草稿(据实回填已实现部分,难以反推的段落显式标「待人工补全」)→ 经 `spec validate` 0 error 把关后开一个 **draft PR** 交人评审。让没有 RFC/spec 的 brownfield(半成品)仓库也能接入 OpenAgents 的 RFC 驱动闭环,而不必从头重写。

## Motivation

OpenAgents 当前是「RFC 先行」:`openagents rfc <issue>` 从一个 GitHub issue 起草 spec、`spec new <slug>` 只生成空的 9 段骨架——两者都**假设代码还没写**,设计先于实现。但现实里常遇到**半成品 brownfield 仓库**:代码已经存在,却没有对应的 RFC/spec,无法纳入「先改 spec、再改代码」的对齐机制(CLAUDE.md 设计理念 4)。

现状缺口很具体:**没有任何命令能「扫现有代码 → 反向生成缺失的 RFC」**。需要澄清一个易混点:本仓库历史 commit `7415ac6`「回填 19 个存量 spec」是一次性**人工 docs 任务**——把已存在的 spec 重写成新的 rust-RFC 格式,**不是从代码生成 spec 的功能**,跑完即弃,不可复用。现有子命令清单 `init / rfc / refine-rfc / implement / iterate / issue / poll / watch / sync-prs / board / vigil / release` 逐一核对,均不覆盖「代码 → spec」这个方向:`rfc` 的输入是 issue 编号(从 GitHub 拉取),输出是凭空起草的设计;没有一条命令以**代码路径**为输入。

因此 brownfield 仓库今天只有两条糟糕的路:要么手写 spec(费时、易和实际代码漂移),要么干脆不接入 RFC 闭环(失去多 agent 对齐基础)。本 feature 用一条 path 驱动的命令补上这个方向,且天然是个 dogfood:OpenAgents 自身就是用 MVP 迭代自身的产品,反向补全能直接服务于「让更多存量仓库接入」这一目标。

## Guide-level explanation

使用者在一个 brownfield 仓库里,对着一个还没有 spec 的模块/目录跑:

```
openagents backfill-rfc openagents/release.py
# 或按目录:openagents backfill-rfc openagents/backends/
```

发生的事:

1. **盘点**:命令先轻量盘点 `<path>` 下的存量代码(文件清单、模块/文件级 docstring、公开符号),既校验路径存在,也为 agent 圈定阅读范围、并确定「一次调用 = 一份 spec」的粒度。
2. **反推**:在隔离 worktree 里派一个 coding agent 读这些代码,按 spec-driven-development 的 Phase 2 产出一份 rust-RFC 9 段 spec 草稿——**据实回填**已实现部分:Summary/Motivation 复述「这块代码现在做什么、为何存在」,Reference-level 描述实际技术结构 + 文件分配 + e2e 脚本路径。对存量代码难以反推的段落(典型是 Drawbacks、Rationale 的备选、Prior art),允许显式写 `> 待人工补全(brownfield 反推困难)` 占位,但**必填四段(Summary/Motivation/Reference-level/Rationale and alternatives)必须据实写满**,否则过不了质量门槛。
3. **把关 + 开 PR**:草稿先过 `spec validate`(0 error 才放行),再开一个 **draft PR**——保持「人负责宏观把控、agent 负责细节」的闭环(理念 5),**不自动 merge**;人在 PR 上评审、补全 agent 标「待补」的段落,合格后才转正。

与 `rfc <issue>` 的区别一句话讲清:`rfc` 是 **issue 驱动、设计先行**(代码还不存在);`backfill-rfc` 是 **path 驱动、实现先行**(代码已存在,反推设计)。两者最终都落到「一份 spec + 一个 draft PR 交人评审」的同一出口。

## Reference-level explanation

**技术方案**——最大化复用 `rfc <issue>` 已有的编排骨架(`Orchestrator.start_rfc`:拉取 → worktree → 后端起草 → 提交推送 → 开 draft PR),只替换两端:输入端把「issue 拉取」换成「代码路径盘点」,任务端把「据 issue 起草」换成「据代码反推」。

- **代码盘点助手 `openagents/backfill.py`**(新模块):输入 `<path>`,校验存在(不存在/空目录报错),产出结构化 inventory——文件清单、模块/文件级 docstring 摘要、公开符号列表,并据 path 形态(单文件 / 目录)确定本次「一份 spec」的范围。纯函数、无副作用,便于单测。
- **编排方法 `Orchestrator.backfill_rfc(path, base)`** + 反向任务 prompt 模板 `_BACKFILL_RFC_TASK`(均在 `openagents/orchestrator.py`):盘点(调 `backfill`)→ `workspace.ensure/prepare` 隔离 worktree → `backend.run` 跑反向 prompt(指示 agent 读 `<path>`、按 9 段反推、难反推段标「待补」、必填四段写满)→ **`spec validate` 门控**(非 0 不开 PR)→ `workspace.commit_and_push` → `signpost.signpost_for_group` 抽 e2e 指路牌 → `github.create_pr(..., draft=True)`。复用现有 `github.create_pr` 的 `draft=True` 形参(已实现于 `openagents/github.py:280`),不新增 GitHub 能力。
- **CLI 接线 `backfill-rfc <path>`**(`openagents/cli.py`):新增 subparser + `_cmd_backfill_rfc`,解析 `path`(位置参数)与 `--base`(默认 main),转发到 `Orchestrator.backfill_rfc`;薄路由,不含业务逻辑(理念 1 奥卡姆)。

**与现有 spec 数据模型 / validate 的对齐**:本 feature **不新增任何 validate 规则、不改 spec 数据模型**,完全复用现有质量门槛——`spec validate` 已对「必填四段(Summary/Motivation/Reference-level/Rationale and alternatives)为空 = error、缺 acceptance/files、files 同组重叠」报错。backfill 把 `spec validate` 当作开 PR 前的硬门控:agent 反推的草稿必须先过这道闸,才能开 draft PR。难反推段落用 `> 待人工补全` 占位之所以安全,正因为它们是**非必填段**(Drawbacks/Prior art/Unresolved/Future),不触发 error;必填四段则强制据实写满。

**Task 分解(files 互斥,各 Task 单一 writer——理念 6)**:

| Task | 范围 | owns files | 依赖 |
|---|---|---|---|
| T1 | 代码盘点助手 | `openagents/backfill.py`, `tests/test_backfill.py` | — |
| T2 | 编排方法 + 反向 prompt | `openagents/orchestrator.py`, `tests/test_orchestrator.py` | T1 |
| T3 | CLI 子命令接线 | `openagents/cli.py`, `tests/test_cli.py` | T2 |
| T4 | e2e 脚本 | `scripts/e2e-spec-0025-backfill-rfc.sh` | T3 |

```mermaid
graph LR
  T1[T1 盘点助手] --> T2[T2 编排+prompt]
  T2 --> T3[T3 CLI 接线]
  T3 --> T4[T4 e2e 脚本]
```

**端到端验证**:`bash scripts/e2e-spec-0025-backfill-rfc.sh`(ruff + pytest + 对一个无 spec 的样例路径跑 `backfill-rfc`、断言产出 9 段草稿且 `spec validate` 0 error)。

## Drawbacks

- **反推可能失真**:agent 从代码反推的「设计意图」未必是当初真实意图,Drawbacks/Rationale 备选尤其容易编造,需人工评审兜底——这也是坚持 draft PR、不自动 merge 的原因。
- **多一条入口的认知成本**:`rfc`(issue 驱动)与 `backfill-rfc`(path 驱动)并存,使用者要分清何时用哪个。
- **「待补」占位的滥用风险**:若 agent 把本可反推的段也标「待补」,草稿质量会缩水;需在 prompt 里强约束「必填四段必须据实写满」。

## Rationale and alternatives

选「独立子命令 `backfill-rfc <path>` + 复用 start_rfc 骨架」是因为:输入模态根本不同(代码路径 vs issue 编号),拆成独立动词让每条命令单一职责、易读易测(理念 1);而开 PR/worktree/后端调度这些与 `rfc` 完全同构的部分则复用,不重复造轮子。

- **备选 A:`rfc --from-code <path>`(给现有 rfc 加 flag)**——省一个子命令,但会让 `rfc` 同时接受「issue 编号」和「代码路径」两种互斥输入,参数语义分叉、help 文案变拧巴,违背单一职责;否决。
- **备选 B:新增 validate 规则专门校验「反向补全 spec」(如允许必填段标待补)**——会侵入 spec 数据模型、为一个来源开后门,削弱质量门槛的统一性;否决。改为**不动数据模型**,靠「必填四段据实写满、其余可待补」的 prompt 约定 + 既有 validate 门控达成,模型保持单一。
- **备选 C:纯静态生成(模板填空,不派 agent)**——能反推文件结构,但写不出 Motivation/Guide-level 这类需要理解语义的散文;反推质量差,否决。派 coding agent 读代码是「据实回填语义」的必要手段。

## Prior art

- **rust-lang/rfcs**(<https://github.com/rust-lang/rfcs>):本仓库 spec 9 段形态的来源(见 `docs/specs/2026-06-25-spec-rfc-form-design.md`),但 rust RFC 是纯设计先行,没有「从代码反推 RFC」的对应物——本 feature 是把同一份 9 段模板用到反方向。
- **文档生成器谱系**(Doxygen / Sphinx autodoc / godoc):都是「从代码抽 API 文档」,证明「代码 → 文档」方向可行且常见;但它们只抽接口签名,不产出设计意图(Motivation/Rationale),粒度与目标不同。本 feature 借其「扫代码」思路,但用 agent 补上语义层。
- OpenAgents 内部:`rfc <issue>` 的 `start_rfc` 编排(`openagents/orchestrator.py`)是本 feature 直接复用的骨架先例。

## Unresolved questions

- **粒度上限**:目前定为「一次调用 = 一个 path = 一份 spec/一个 PR」。对很大的目录,一份 spec 可能超过「≤6 Task」的拆分约束,是否需要在盘点阶段自动建议拆分,留待实现期按真实样例定。
- **「待补」段落的回填闭环**:人工在 PR 上补全「待补」段后,是否要有命令辅助二次校验,本 spec 暂不覆盖。
- skill(`.claude/skills/spec-driven-development/`)文案是否补一句 backfill 入口——本组**不触碰 `.claude/` 任何内容**(硬约束),故该对齐留到 skill 维护方单独处理,不进本 spec 的 Task。

## Future possibilities

- **批量反向补全**:`backfill-rfc <dir> --per-module` 一次为子目录下每个模块各产一份 spec / 各开一个 PR,服务大规模 brownfield 接入。
- **与 vigil 串联**:守夜人发现仓库存在「无 spec 的活代码」时,自动派单 backfill,把反向补全纳入自治闭环。
- **漂移巡检**:对已有 spec 的模块,反向重新盘点并和现存 spec 比对,报「代码已变、spec 未更新」的漂移(与 `spec graph` 的 ARCHITECTURE 映射互补)。

