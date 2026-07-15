---
number: "0066"
title: oa init 自动生成默认 .openagents/openagents.yml（打包内 template 拷出，幂等 + --force 覆盖）
issue: 165
slug: init-scaffold-config
summary: oa init 从打包进包内的 template 自动落一份带注释的默认 .openagents/openagents.yml：幂等（已存在跳过、--force 强制重写），运行时仍可被 oa vigil 的 --skip/--hold/--base 单次覆盖（_effective_config 不改），并加漂移测断言打包 template 经 load_agent_config 解析后语义等价于 default_config()。
e2e:
  intent: 证明 oa init 在真实项目里首次运行即自动落一份带注释的默认 .openagents/openagents.yml，重复运行幂等不覆盖用户改动，只有 --force 才重写回默认——这是本 issue 对外的可见产品行为。
  method: |
    1. 在一个临时 git 仓库里跑 oa init（github 前置检查按环境放行或打桩），断言 .openagents/openagents.yml 被创建，且内容字节等于包内 openagents/templates/openagents.yml。
    2. 手动编辑生成文件（改一行注释或某个 stage 值），再跑一次 oa init，断言文件内容原样不变（幂等、不覆盖用户改动），且输出提示「已存在，跳过（--force 覆盖）」。
    3. 跑 oa init --force，断言文件被重写回包内 template 内容，输出提示「已用默认重写」。
    4. 把三步的终端输出与文件 diff 存证到 docs/evidence/spec-0066/；gh 不可用时改直接驱动 scaffold.write_default_config 取同一生命周期的产品行为证据并注明。
tasks:
  - id: T1
    title: 打包 template（relocate 进包 + 删根副本）+ scaffold 写盘 util（幂等 + force）+ 单测 + README 起步说明
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/templates/openagents.yml
      - openagents/utils/scaffold.py
      - openagents.yml.template
      - README.md
      - tests/test_scaffold.py
    scope: 把 openagents.yml.template 内容 relocate 进包内 openagents/templates/openagents.yml 并删除仓库根副本（单一真源，装 wheel 可达）；新增 openagents/utils/scaffold.py 暴露 write_default_config(*, repo_root, force)——目标 repo_root/.openagents/openagents.yml，已存在且非 force 返回 SKIPPED（不读写、不碰用户改动），否则 mkdir(parents) 写入包内 template 文本返回 CREATED/OVERWRITTEN；包内 template 经 importlib.resources.files('openagents').joinpath('templates/openagents.yml').read_text('utf-8') 读取。scaffold 不感知 git/gh/子进程（理念10 解耦）。README 声明式配置小节补一句 oa init 自动生成起步文件。
    acceptance: pytest tests/test_scaffold.py 通过：临时目录首次 write_default_config(force=False) 生成 .openagents/openagents.yml 且内容字节等于包内 template；文件已存在时 force=False 返回 SKIPPED 且原内容（含用户改动）不变；force=True 返回 OVERWRITTEN 且回到 template 内容；父目录不存在时自动创建。仓库根 openagents.yml.template 已删除、openagents/templates/openagents.yml 存在。ruff 干净。
  - id: T2
    title: CLI 接线：oa init --force + _cmd_init 调 scaffold 生成/跳过/重写
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli.py
    scope: oa init 子命令加 --force（action=store_true，help 强制用包内默认重写 .openagents/openagents.yml）；_cmd_init 在「项目已就绪」打印后、envcheck 输出前调 scaffold.write_default_config(repo_root=ctx.repo_root, force=args.force)，按 ScaffoldResult 三态打印 已生成/已存在跳过（--force 覆盖）/已用默认重写。_cmd_init 只做编排与打印，写盘逻辑不下沉进 CLI。
    acceptance: pytest tests/test_cli.py 通过：build_parser() 解析 'init --force' 得 args.force=True、'init' 得 False；_cmd_init 用 fake ctx（tmp repo_root）+ 桩掉 github.ensure_prerequisites/envcheck 后，首跑生成 .openagents/openagents.yml 并打印 已生成；再跑打印 已存在跳过 且文件不变；--force 打印 已用默认重写。ruff 干净。
  - id: T3
    title: 防漂移测：包内 template 经 load_agent_config 语义等价 default_config()
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tests/test_config_template_drift.py
    scope: 新增 tests/test_config_template_drift.py：把包内 template（importlib.resources 读出写临时文件）经 load_agent_config 解析，与 default_config() 比 resolved 行为指纹（非 dataclass ==）——version/release.mode/interval/base/sorted(labels) 相等；每个 _ROLES 角色 backend_for 相等（吸收 显式列出=空dict回落）；每个可配阶段 owner_of 相等；repos 逐仓比 (name,interval,base,sorted(labels),各stage owner) 丢弃绝对 path。
    acceptance: pytest tests/test_config_template_drift.py 通过：断言 load_agent_config(包内 template) 与 default_config() 行为指纹全等；故意篡改（如临时把某 stage 改 human 的解析结果）应使断言失败以证明测试有效（可用局部构造验证）。ruff 干净。
---

# 0066 · oa init 自动生成默认 .openagents/openagents.yml（打包内 template 拷出，幂等 + --force 覆盖）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

`oa init` 从**打包进包内**的 template 自动落一份带注释的默认 `.openagents/openagents.yml`，让首次上手的用户一眼看到「有哪些旋钮可调、每道闸能配 agent/human/skip 三态」，而不必去翻源码或 README。**幂等**——文件已存在则跳过、绝不覆盖用户改动；`oa init --force` 才强制用包内默认重写。生成的 YAML 只是**声明式默认**（每个值都等于内建默认），运行时仍可被既有 `oa vigil --skip/--hold/--base/--interval/--label` 等 flag 单次覆盖（`_effective_config` 不改，本 spec 不碰加载/校验）。再加一条**防漂移测**断言打包 template 经 `load_agent_config` 解析后**语义等价**于 `default_config()` 内建默认，把「示例 = 真默认」焊死。

## Motivation

`.openagents/openagents.yml` 是「用哪些 agent + 每道闸归谁把关」的声明式单一真源（Spec-0064）。它刻意设计成**整份可省**——文件不存在或空则全回落内建默认（全自动、全 agent、claude_code、单仓、间隔 60s），不写 YAML 的用户零感知。这对「不想配」的用户是好事，但对「想配、却不知道能配什么」的首次用户是一个**发现性黑洞**：磁盘上没有任何配置文件，他看不到有哪些键、每道闸的三态取值、有哪些约束（不许零闸 / 硬闸名进不了 stages）。要调一个旋钮，只能去读 `openagents/utils/agent_config.py` 源码或 README。

仓库根已有一份带丰富中文注释的 `openagents.yml.template`（PR #163 / commit 871ee6c 引入），但它有两个致命缺陷：

1. **装成 uv tool 后运行时拿不到**——它在仓库根、不在包内，`uv tool install` 后的运行环境里没有这个文件；
2. **要手动 `cp`**——用户得先知道有它、再手动 `cp openagents.yml.template .openagents/openagents.yml` 才生效，等于没解决发现性问题。

因此本 spec 让 `oa init`（用户初始化项目的必经入口）在绑定项目时**自动**从打包进包内的 template 拷一份到 `.openagents/openagents.yml`。用户一 `oa init` 就有一份带注释、可直接改的声明式配置摆在眼前——把「隐式默认」变成「显式可见、可改的起步文件」，同时保持「不改就等于内建默认」的语义（生成内容 = 内建默认，由防漂移测钉死）。

## Guide-level explanation

从用户视角，`oa init` 多打印一行：

```
$ oa init
✓ 项目已就绪：/path/to/repo（远端：git@github.com:owner/repo.git）
✓ 已生成 .openagents/openagents.yml（带注释的声明式默认，可直接编辑）
<envcheck 输出…>
```

三种情形：

- **首次**：`.openagents/openagents.yml` 不存在 → 从包内 template 拷一份，打印「已生成」。用户打开即见全部旋钮与注释。
- **再次（幂等）**：文件已存在 → **跳过、绝不覆盖**用户改动，打印「已存在，跳过（`--force` 覆盖）」。
- **`oa init --force`**：强制用包内 template 重写（丢弃本地改动、回到默认起步态）——给「配乱了想重置」的用户一个逃生口。

生成的文件只是**声明式默认**：它写的每个值都等于内建默认，删任意键（乃至整份删除）都回落同一行为。运行时想临时改，仍走既有 `oa vigil --skip ci` / `--hold merge` / `--base <b>` 等 flag（`_effective_config` 单次覆盖、不落盘，本 spec 不改）。三层关系一句话：**磁盘 YAML（持久默认）被 flag（单次运行覆盖）盖过**，而磁盘 YAML 不存在时回落**内建默认**——`oa init` 只是把「内建默认」显式物化成一份可读可改的磁盘 YAML，不改变任何运行时优先级。

## Reference-level explanation

### 打包 template（单一真源、装包可达）

把现有 `openagents.yml.template` 的内容 **relocate 进包内** `openagents/templates/openagents.yml`，并**删除仓库根的 `openagents.yml.template`**——单一真源，避免两份 template 各自漂移（防漂移测只能守一份）。包内数据文件由 hatchling 默认随 wheel 打包（package 目录下的非 `.py` 文件默认纳入，无需改 `pyproject.toml`）；运行时经

```python
importlib.resources.files("openagents").joinpath("templates/openagents.yml").read_text("utf-8")
```

读取——以真实包 `openagents` 为锚点 joinpath，`templates` 无需是子包（不必加 `__init__.py`），`uv tool install`（wheel）与 editable 安装均可达。

### scaffold util（纯写盘，解耦 CLI）

新增 `openagents/utils/scaffold.py`，暴露：

```python
def write_default_config(*, repo_root: Path, force: bool) -> ScaffoldResult
```

- 目标路径 `repo_root / ".openagents" / "openagents.yml"`（承 `.openagents/` 命名空间，与 `agent_config.DEFAULT_CONFIG_PATH` 同源）；
- 已存在且非 `force` → 返回 `SKIPPED`，**不读不写**（幂等，绝不碰用户改动）；
- 否则 `mkdir(parents=True, exist_ok=True)` → 写入包内 template 文本 → 返回 `CREATED`（原不存在）/ `OVERWRITTEN`（`force` 覆盖已存在）；
- 不感知 git / gh / 子进程（理念 10 解耦）；只依赖 `importlib.resources` + `pathlib`。

`ScaffoldResult` 是一个轻量结果（三态字面量/枚举 + 目标 `path`），供 CLI 决定打印哪条提示——把「写盘」与「打印/交互」的职责切开。

### CLI 接线

- `oa init` 子命令加 `--force`（`action="store_true"`，help「强制用包内默认重写 `.openagents/openagents.yml`」）；
- `_cmd_init` 在「项目已就绪」打印之后、`envcheck` 输出之前，调 `scaffold.write_default_config(repo_root=ctx.repo_root, force=args.force)`，按 `ScaffoldResult` 三态打印「已生成 / 已存在，跳过（--force 覆盖）/ 已用默认重写」。`_cmd_init` 仍只做编排与打印，写盘逻辑全在 scaffold（可无 CLI 独立测）。

### 防漂移测（示例 = 真默认）

新增 `tests/test_config_template_drift.py`：把包内 template 经 `load_agent_config` 解析，断言其与 `default_config()` **语义等价**。这里的「语义等价」不是 dataclass `==`——template 为了教学**显式列出**了 `agents: {implementer/reviewer: claude_code}`、`stages: 全 agent` 等（这些值恰好等于 fallback），而 `default_config()` 的 `AgentPolicy.backends` 是**空 dict**（靠 `backend_for` 回落 claude_code），且 `repos[0].path` 因解析基准不同（template 相对其所在目录、default 相对 cwd）绝对路径不相等。故比较取「resolved 行为指纹」：

- `version` / `release.mode` / `interval` / `base` / `sorted(labels)` 逐一相等；
- 每个已知角色（`_ROLES`）的 `agents.backend_for(role=…)` 相等（吸收「显式列出 = 空 dict 回落」的表达差异）；
- 每个可配阶段的 `stages.owner_of(stage=…)` 相等；
- `repos` 逐仓比 `(name, interval, base, sorted(labels), 各 stage 的 owner)`——**丢弃绝对 `path`**（只比结构，不比解析基准）。

这条测试把「template 里写的示例值」与「内建默认」焊死：谁改了 `default_config()` 却忘了同步 template（或反之），CI 立刻红。

### DAG + 文件分配

| Task | 内容 | files（两两互斥） | depends-on |
|---|---|---|---|
| T1 | 打包 template（relocate 进包 + 删根副本）+ scaffold 写盘 util + 单测 + README 起步说明 | `openagents/templates/openagents.yml`、`openagents/utils/scaffold.py`、`openagents.yml.template`（删）、`README.md`、`tests/test_scaffold.py` | — |
| T2 | CLI 接线：`oa init --force` + `_cmd_init` 调 scaffold | `openagents/cli.py`、`tests/test_cli.py` | T1 |
| T3 | 防漂移测：包内 template 经 `load_agent_config` 语义等价 `default_config()` | `tests/test_config_template_drift.py` | T1 |

T2、T3 互不依赖 → 并行。

### e2e 脚本路径

`scripts/e2e-spec-0066-init-scaffold-config.sh`（离线）：在临时 git 仓库里驱动 `oa init` → 编辑生成文件 → 再 `oa init`（断言未被覆盖）→ `oa init --force`（断言重写回默认），覆盖「生成 → 幂等不覆盖 → force 重写」生命周期，并 diff 生成内容字节等于包内 template。`oa init` 会先 `github.ensure_prerequisites()`（需 gh），离线脚本据环境或对该 preflight 打桩、或直接驱动 `scaffold.write_default_config` 取产品行为证据。

## Drawbacks

- **多一个磁盘文件**：本来「零配置、零文件」的极简用户，`oa init` 后会多出一份 40 行注释 YAML。缓解：内容 = 内建默认，删任意键乃至整份都回落同一行为，纯可选。
- **两份「默认」定义并存**（`default_config()` 代码 + template 文本）天然有漂移风险——但这正是防漂移测存在的理由，把风险从「静默漂移」变成「CI 红」。
- **relocate 删根 template** 让 PR #163 刚加的文件一版即走，git 历史上看略突兀（但语义上是去重 relocate、不是回退）。

## Rationale and alternatives

**选定**：relocate template 进包 + `oa init` 自动拷（幂等 + `--force`）+ 语义等价防漂移测。

**备选 1：保留根 `openagents.yml.template`，`oa init` 从仓库根拷。** 否决——装成 uv tool 后根文件不在运行环境里（issue 明列缺陷 1），且要维护「根 template ↔ 包内」两份。relocate 进包是唯一让「装包可达」与「单一真源」同时成立的方案。

**备选 2：不落盘，`oa init` 只把默认注释打印到 stdout。** 否决——用户还得手动粘贴成文件，没解决「要一份可直接改的文件」的诉求；也无法承载 `--force` 重置语义。

**备选 3：把 template 精简成结构上恰等于 `default_config()`（去掉显式 `agents`/`stages`）。** 否决——template 的**全部价值就是把旋钮显式列出来给人看**；精简掉就退回「发现性黑洞」。故选择保留教学式显式值，改用「resolved 行为指纹」比较来定义语义等价（吸收「显式 = 回落」的差异）。

**备选 4：`oa init` 默认即 `--force`（每次重写）。** 否决——会覆盖用户改动、违背幂等；默认必须 skip，只有显式 `--force` 才重写。

## Prior art

- **Spec-0064**：`.openagents/openagents.yml` 声明式配置层（`load_agent_config` / `default_config` / 三态 stages / 每闸合法取值）——本 spec 的直接上游，只加「生成」，不改「加载 / 校验」。
- **`git init` / `npm init` / `cargo new`**：init 类命令生成带默认的起步配置是通行实践；本 spec 沿用「init 落一份可改默认」的成熟模式。
- **`importlib.resources.files()`**（Python 3.9+ 的 traversable API）：包内数据文件的标准读取方式，wheel（`uv tool install`）与 editable 安装均可达。
- 仓库内既有 `envcheck` / `github.ensure_prerequisites` 在 `_cmd_init` 的接线点——scaffold 挂同一 handler，复用既有 preflight 顺序。

## Unresolved questions

- 生成文件落点固定 `.openagents/openagents.yml`；是否需要 `oa init --config <path>` 生成到别处？倾向不做（Occam——`oa vigil --config` 已能读别处，生成入口保持单一）。待人确认是否保留此问。

## Future possibilities

- `oa config check` / `oa config explain`：打印当前 resolved 三态（含 flag 覆盖后），帮用户确认「现在每道闸归谁」。
- template 分档：`oa init --template minimal|full` 生成极简版 / 全注释版。
- `release: auto` 落地后，template 补 auto 档注释与约束说明。

