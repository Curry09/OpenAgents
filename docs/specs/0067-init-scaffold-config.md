---
number: "0067"
title: oa init 自动生成默认 .openagents/openagents.yml（打包 template 作单一真源，vigil 运行时 flag 仍可覆盖）
issue: 165
slug: init-scaffold-config
summary: 把仓库根的 openagents.yml.template 收进包内作 package data 单一真源，oa init 幂等地把它拷成 .openagents/openagents.yml（--force 覆盖），让首次上手即有带注释、可直接改的声明式默认；运行时 --skip/--hold/--base 仍单次覆盖不变。加防漂移测试断言打包 template 语义等价 default_config()。
tasks:
  - id: T1
    title: 模板迁入包内 + 打包 + scaffold_default_config + 防漂移/幂等测试
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/data/openagents.yml.template
      - openagents.yml.template
      - openagents/utils/agent_config.py
      - tests/test_agent_config.py
    scope: 把仓库根 openagents.yml.template 逐字迁入 openagents/data/ 作打包单一真源并删仓库根副本（hatchling 默认纳入包目录下所有文件，openagents/utils/templates/board.html 即先例，无需额外 pyproject 配置）；agent_config 加纯 IO 函数 scaffold_default_config(*, path, force) -> bool（读包内资源 importlib.resources → 幂等写盘，存在且非 force 跳过返 False，否则建目录写模板返 True，除写目标文件外无副作用）。
    acceptance: pytest tests/test_agent_config.py 通过：① 防漂移——打包模板经 load_agent_config 解析后 7 道 stage 全 agent / 各角色 backend 全 claude_code / release=manual / interval=60 / base=main / labels=[openagents]（语义等价 default_config()）；② scaffold 幂等——目标不存在→写入返 True 且内容==模板；已存在且 force=False→返 False 不改；force=True→重写返 True；③ scaffold 产物能被 load_agent_config 无错解析。uv build 后 wheel 内含 openagents/data/openagents.yml.template。
  - id: T2
    title: oa init 接线：--force + 幂等生成 + 提示
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: init 子命令加 --force（store_true）；_cmd_init 在 preflight 通过后调 agent_config.scaffold_default_config(path=ctx.repo_root/'.openagents'/'openagents.yml', force=args.force)，按返回值印「已生成 / 已覆盖 / 已存在跳过（--force 覆盖）」。运行时覆盖链 _effective_config 不动。
    acceptance: pytest tests/test_cli.py 通过：oa init 首次在临时 repo 生成 .openagents/openagents.yml 并印已生成；再跑幂等（不覆盖、印已存在跳过）；oa init --force 覆盖并印已覆盖；init 仍跑 preflight（ensure_project）+ envcheck。build_parser 注册 --force。
---

# 0067 · oa init 自动生成默认 .openagents/openagents.yml（打包 template 作单一真源，vigil 运行时 flag 仍可覆盖）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

`.openagents/openagents.yml` 是「用哪些 agent + 每道闸归谁把关」的声明式单一真源（Spec-0064）。它**整份可省**——文件不存在 → 全回落内建默认（全自动 / 全 agent / 单仓 / 间隔 60s），不写 YAML 的用户零感知。代价是**首次上手的用户看不到任何配置文件**：不知道有哪些旋钮、每道闸能配成 `agent`/`human`/`skip` 三态，只能翻源码或 README。

本 spec 让 **`oa init` 幂等地生成一份默认 `.openagents/openagents.yml`**：内容来自一份**打包进包内的注释模板**（`openagents/data/openagents.yml.template`，从仓库根迁入、成为单一真源）。文件已存在则跳过（不覆盖用户改动），`oa init --force` 强制重写。生成物只是**声明式默认**——运行时的 `oa vigil --skip ci` / `--hold merge` / `--base` 等 flag 仍按既有 `_effective_config` 逻辑单次覆盖它，**这条覆盖链本 spec 不改**。

关键约束是**防漂移**：模板里写死的默认（stages 全 agent / claude_code / manual / interval 60 / base main / labels [openagents]）必须与 `agent_config` 的内建默认（`default_config()`）永远一致。用一条测试断言「打包模板被 `load_agent_config` 解析后语义等价于内建默认」把它从自觉变成 CI 硬闸。

## Motivation

### 现状：零配置友好，但零发现性

Spec-0064 把 stages 三态设计成「整份 YAML 可省」，这对**老手**是奥卡姆的胜利——不写就是全自动默认。但对**新手**是一堵墙：

1. 项目里没有任何 `.openagents/openagents.yml` 实体，用户不知道它存在、也不知道能配什么；
2. 每道闸的合法取值不一样（`conflict`/`merge` 不可 skip、`rfc` 只 agent/skip），这些约束只活在 `agent_config.py` 的 `_STAGE_VALID_OWNERS` 和 README 里，配置面前没有就地提示；
3. 想开一个 `review: human`（合并前停等人审）这样的常见需求，得先知道有 `stages` 段、知道 `review` 键、知道 `human` 是合法值——三层门槛。

仓库根已有一份带丰富中文注释、逐键讲解三态取值的 `openagents.yml.template`（commit 871ee6c），它正是为降这道门槛而生。但它**只是一份躺在仓库根的文档**：

- 装成 uv tool（`uv tool install`）后，仓库根不在运行时可达路径里，代码拿不到它；
- 就算能拿到，用户仍需手动 `cp openagents.yml.template .openagents/openagents.yml` 才让它生效——「默认生成一下」这一步缺席。

### 为什么是 `oa init`

`init` 是「绑定 / 初始化当前目录为 OpenAgents 项目」的自举命令（RFC-0001 决策 10），语义上就是「把这个目录准备好」。当前它只做 git/remote 就绪检查 + 环境体检，**不落任何项目文件**。补上「生成声明式配置默认」正是它该干的事——用户 `oa init` 一次，就同时拿到「就绪校验」与「一份可直接改的带注释配置」。放独立 `init-config` 子命令则要求用户多知道、多敲一条命令，与「默认生成一下」的诉求相悖。

## Guide-level explanation

一次 `oa init` 的新增行为：

```
$ oa init
✓ 项目已就绪：/path/to/repo（远端：git@github.com:owner/repo.git）
✓ 已生成默认配置 .openagents/openagents.yml（可编辑；oa vigil --skip/--hold 可单次覆盖）

▶ 环境体检
  ...

# 再跑一次（文件已存在）——幂等，不覆盖你的改动：
$ oa init
✓ 项目已就绪：...
· 配置已存在，跳过生成 .openagents/openagents.yml（--force 覆盖）
  ...

# 想用包内最新模板重置：
$ oa init --force
✓ 已覆盖配置 .openagents/openagents.yml
```

生成的文件就是包内 `openagents/data/openagents.yml.template` 的逐字拷贝——一份带中文注释、逐键讲三态取值的声明式默认。用户直接改它（如把 `review: agent` 改成 `review: human`），下次 `oa vigil` 读它生效。改坏了删掉即回落内建默认；想临时试某个闸而不改盘上文件，用 `oa vigil --skip`/`--hold` 单次覆盖。

**「可被参数覆盖」= 运行时 flag 覆盖 YAML，这条链已存在**（`cli._effective_config`：`--hold`/`--skip` 改三态、`--base`/`--interval`/`--label` 改 defaults，且覆盖后重守「不许零闸」）。本 spec 只补「默认把 YAML 生成出来」，不碰覆盖链。

三态的层次关系：**内建默认（代码里的 `default_config()`）← 打包模板（init 生成的盘上 YAML，等价内建默认）← 运行时 flag（单次覆盖）**。三者语义一致、层层可覆盖，模板与内建默认的等价由测试钉死。

## Reference-level explanation

### 数据流

```
openagents/data/openagents.yml.template   ← 单一真源（从仓库根迁入，打包进 wheel）
        │  scaffold_default_config(path=…, force=…)  读包内资源 → 写盘
        ▼
<repo_root>/.openagents/openagents.yml     ← oa init 生成（幂等；--force 覆盖）
        │  load_agent_config(path=…)                  既有加载器，不改
        ▼
AgentConfig（resolved）  ← _effective_config 叠加运行时 flag（既有，不改）
```

### 变更点

**① 模板迁入包内（单一真源）。** 仓库根 `openagents.yml.template` → `openagents/data/openagents.yml.template`（逐字迁移，内容不变，仅更新头部注释指向 `oa init` 生成流程）。删除仓库根副本，避免两份漂移。**无需改 `pyproject.toml`**——hatchling 默认把包目录下所有文件纳入 wheel（现存 `openagents/utils/templates/board.html` 即先例，`uv build` 后 `unzip -l` 可验证模板已随包），奥卡姆下不增冗余打包配置。

**② `agent_config.scaffold_default_config`（新函数，纯 IO）。** 签名 `scaffold_default_config(*, path: Path, force: bool) -> bool`：

- 读包内模板走 `importlib.resources.files("openagents") / "data" / "openagents.yml.template"`（editable 与 wheel 两种安装都可达）；
- `path` 已存在且 `not force` → 返回 `False`（幂等跳过，不碰用户文件）；
- 否则 `mkdir(parents=True, exist_ok=True)` 建 `.openagents/` 目录后写入模板文本，返回 `True`；
- 除写目标文件外无副作用（不读 git/gh/网络，理念 10 解耦）。

**③ CLI 接线。** `init` 子命令加 `--force`（`store_true`）；`_cmd_init` 在 preflight 通过后调 `scaffold_default_config(path=ctx.repo_root/".openagents"/"openagents.yml", force=args.force)`，按返回值印「已生成 / 已覆盖 / 已存在跳过」。

**④ 防漂移测试。** 断言打包模板经 `load_agent_config` 解析后，7 道 stage 全 `agent`、各角色 backend 全 `claude_code`、release=manual、interval=60、base=main、labels=[openagents]——即语义等价 `default_config()` 的内建默认。任何一方改了默认而没同步另一方，CI 直接红。

### DAG + 文件分配

| Task | 依赖 | 负责文件（两两不相交） |
|---|---|---|
| **T1** 模板迁入 + `scaffold_default_config` + 防漂移/幂等测试 | — | `openagents/data/openagents.yml.template`（新，自仓库根迁入）、`openagents.yml.template`（删）、`openagents/utils/agent_config.py`、`tests/test_agent_config.py` |
| **T2** `oa init` 接线（`--force` + 生成 + 提示） | T1 | `openagents/cli.py`、`tests/test_cli.py` |

T1 的 `scaffold_default_config` 是 T2 的依赖，故 T1 → T2 串行。文件清单两两不相交（T1 碰 data/agent_config/test_agent_config，T2 碰 cli/test_cli），协同模式无冲突。

### e2e 验证脚本

`scripts/e2e-spec-0067-init-scaffold-config.sh`（离线，纯 CLI）：在一个临时 git 仓库里跑 `oa init` → 断言 `.openagents/openagents.yml` 生成且能被 `load_agent_config` 解析 → 再跑一次断言幂等（内容不变、印「已存在跳过」）→ 改一行后 `oa init --force` 断言被重置回模板。

## Drawbacks

- **多一份需与内建默认保持同步的产物。** 模板里的默认值与 `agent_config._DEFAULT_*` 是两处表述同一事实，天然有漂移风险。缓解：④ 的防漂移测试把它变成 CI 硬闸，改一方不同步另一方就红。（不选「模板从常量程序化 render」是因为会丢掉逐键中文注释这一核心价值，见 Rationale。）
- **`init` 副作用变重。** 从「只读校验」变成「会写一个文件」。缓解：幂等 + 只在文件不存在时写，绝不覆盖用户改动；`--force` 才重写，且写的是 gitignored 的 `.openagents/`（不污染用户版本库）。

## Rationale and alternatives

**为什么打包模板拷贝，而非从常量程序化生成 YAML？** 备选是从 `agent_config._DEFAULT_STAGES`/`_ROLES` 等常量 `render` 出 YAML——好处是与内建默认零漂移。但它会丢掉模板里**逐键讲三态取值、约束、示例的中文注释**，而这正是本 feature 降新手门槛的核心价值：程序化 render 一堆无注释的 `key: value` 对发现性毫无帮助。选「打包注释模板 + 一条防漂移测试」：既保住注释，又用测试把漂移风险摁成 CI 硬闸，鱼与熊掌兼得。

**为什么迁入包内并删仓库根副本，而非 force-include 仓库根文件？** hatchling 可 force-include 仓库根文件进 wheel，但 editable 安装（`uv sync` / 测试的 `pythonpath=.`）下 `importlib.resources` 解析的是源码树的 `openagents/` 包目录，仓库根文件不在其中，两种安装模式行为会分叉。迁入 `openagents/data/` 让源码树与 wheel 里路径一致，两模式同源。删仓库根副本是为守单一真源（两份注释模板必然漂移）。

**为什么放 `oa init` 而非独立子命令？** 见 Motivation「为什么是 `oa init`」——`init` 语义即「准备好这个目录」，且「默认生成一下」要求零额外命令。

## Prior art

- **Spec-0064** 立了 `.openagents/openagents.yml` 声明式三态配置与「整份可省 → 内建默认」的加载器（`agent_config`）；本 spec 是它的上手补全（把「可省的默认」实体化成带注释的盘上文件）。
- **`git init` 生成 `.git/config` 骨架**、**`npm init` 生成 `package.json`**、**`eslint --init` 生成配置**——脚手架工具「init 落一份带默认的可编辑配置」是通行实践。本 spec 取同一形态：init 落一份幂等、可编辑、带注释的默认配置。
- **CI 幂等漂移检查**（`spec render` / `spec graph` 的 drift gate，见 `.github/workflows/ci.yml`）是本仓已有的「生成物与源不许漂移 → CI 红」范式；④ 的防漂移测试沿用同一思路。

## Unresolved questions

无（触发点 = `oa init`、内容来源 = 打包模板、覆盖语义 = 既有运行时 flag，三个设计岔口已与需求方确认）。

## Future possibilities

- **`oa init` 交互式选型**：生成前问「review 要 agent 还是 human 把关？」按答案调模板对应行（本 spec 只落静态默认模板，交互式选型是后续）。
- **`oa doctor` / `oa config validate`**：对已存在的 `.openagents/openagents.yml` 跑 `load_agent_config` 并把错误友好化，作为独立体检命令。
- **多后端模板变体**：当 `backends/` 真正支持 codex/nexau 后，`oa init --backend codex` 生成对应 `agents` 段默认。

