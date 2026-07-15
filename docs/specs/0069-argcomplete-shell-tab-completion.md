---
number: "0069"
title: 为 openagents CLI 接入 argcomplete Shell Tab 补全（读现成 argparse parser，单一真源，零副作用）
issue: 151
slug: argcomplete-shell-tab-completion
summary: 在 cli.main() 的 parse_args 之前插一行 argcomplete.autocomplete(parser)，让 openagents/oa 直接从现成的 argparse parser 生成 zsh/bash Tab 补全，覆盖全部子命令与选项，无需手写维护第二份命令清单；argcomplete 对非补全调用零副作用（仅当 _ARGCOMPLETE 环境变量存在时介入），CLI 既有行为不变。配套加 argcomplete 运行时依赖 + README 文档给出用户侧一次性启用步骤。
e2e:
  intent: 证明「argcomplete 接现成 argparse parser 生成 Tab 补全」这一接线在离线确定性链路上成立且零回归——main() 在 parse_args 之前调 argcomplete.autocomplete(parser)（补全握手时介入、正常调用零副作用），全部子命令与 vigil 全部选项都进 parser（补全候选单一真源即 build_parser）；argcomplete 缺失时 CLI 优雅降级不崩；argcomplete 已作为运行时依赖声明。
  method: "形态：纯 CLI/后端接线，无 product-facing 前端可导航；自检工具列表无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，改用离线确定性测法（沿用 Spec-0064/0066/0067 同款）：\n1. CLI 针对性 pytest（打桩 openagents.cli.argcomplete，hermetic 不触 shell/网络）：main([]) 在 parse_args 前调 argcomplete.autocomplete 恰一次且入参是 build_parser() 造出的 ArgumentParser，且 main([]) 仍返回 2（无命令）；把 openagents.cli.argcomplete 打成 None → main([]) 仍返回 2 不抛（优雅降级）；build_parser 注册的子命令全集与 vigil 全部选项仍在（补全候选覆盖面）。\n2. grep 锚点（e2e 脚本）：cli.py 存在 argcomplete 优雅降级 import 与 autocomplete(parser) 调用；pyproject.toml 的 dependencies 含 argcomplete。\n脚本：scripts/e2e-spec-0069-argcomplete-shell-tab-completion.sh（ruff check + ruff format --check + 针对性 pytest + grep 锚点），被 PR e2e signpost 采集。\n"
tasks:
  - id: T1
    title: argcomplete 接线 + 依赖 + 文档 + 测试
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - pyproject.toml
      - README.md
      - tests/test_cli.py
    scope: cli.main() 在 parse_args 之前调 argcomplete.autocomplete(parser)（模块顶层 try/except ImportError 优雅降级导入，缺失置 None）；pyproject.toml dependencies 追加 argcomplete>=3.0；README 加 Shell Tab 补全一次性启用步骤（zsh/bash）；tests/test_cli.py 补 argcomplete 接线契约测试。
    acceptance: uv run pytest tests/test_cli.py 通过：main([]) 在 parse_args 前调 argcomplete.autocomplete 恰一次、入参为 build_parser() 造出的 ArgumentParser 且 main([]) 返回 2；把 openagents.cli.argcomplete 打成 None 时 main([]) 仍返回 2 不抛（优雅降级）；build_parser 注册全部人面向子命令 + vigil 全部选项。ruff check/format 干净；pyproject.toml dependencies 含 argcomplete。
---

# 0069 · 为 openagents CLI 接入 argcomplete Shell Tab 补全（读现成 argparse parser，单一真源，零副作用）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

`openagents`（安装后同名入口，README 里也叫 `oa`）CLI 完全由 `openagents/cli.py` 的 `argparse`
（`build_parser`）搭起来。argparse **不提供任何 Shell Tab 补全**——它只在运行时解析已经敲进来的参数，
和 zsh/bash 按 Tab 弹候选是两套完全不同的机制。于是今天 `openagents <Tab>`、`openagents vigil --<Tab>`
都不补全，zsh 只能回退到文件名补全。

本 spec 接入 [`argcomplete`](https://github.com/kislyuk/argcomplete)：在 `cli.main()` 的
`parser.parse_args()` **之前**插一行 `argcomplete.autocomplete(parser)`，让补全**直接读现成的 argparse
parser** 生成候选，覆盖全部子命令（init/vigil/backfill-rfc/issue/release/board/report + 隐藏的
reply-comment）与全部选项（如 `vigil --interval/--label/--base/--once/--parallel/--hold/--skip/--config`）。
无需为补全另写、另维护一份 `_openagents` zsh 脚本或第二份命令清单（符合理念 1 奥卡姆剃刀：命令清单单一
真源仍是 `build_parser`）。配套加 `argcomplete` 运行时依赖，并在 README 给出用户侧一次性启用步骤。

关键性质：`argcomplete.autocomplete()` **只在 shell 补全握手时（环境变量 `_ARGCOMPLETE` 存在）才介入**并
`exit()`；正常 `openagents vigil ...` 调用下它立即返回、零副作用，CLI 既有行为逐字不变。

## Motivation

### 现状核实

- `pyproject.toml` 的 `dependencies` 只有 `ruamel.yaml` / `jsonschema`，**无 `argcomplete`**；`openagents/`
  下也无任何补全接线或配套 `_openagents` 脚本。
- `openagents/cli.py` 的 `main()` 是 `parser = build_parser(); args = parser.parse_args(argv)`，中间没有
  任何补全钩子。
- 因此 `openagents <Tab>`（补子命令）、`openagents vigil --<Tab>`（补选项）都不工作。这对**所有**子命令、
  所有选项一致，不限于 `vigil`。

### 为什么要做

CLI 有 7 个人面向子命令 + 各自一串选项（`vigil` 一个就有 8 个 flag）。没有 Tab 补全时，用户要么背命令名、
要么反复 `--help`。这既伤上手速度（对标 cursor/windsurf 的交互顺滑），也和「命令面已经声明式自描述」的现状
不匹配——parser 里明明有全部信息，只是没接到 shell。argparse 生态的标准答案就是 argcomplete：它把 argparse
parser 当补全的单一真源，不逼我们维护第二份会漂移的命令清单。

## Guide-level explanation

用户一次性启用（zsh，写进 `~/.zshrc`）：

```zsh
autoload -U bcompinit && compinit
eval "$(register-python-argcomplete openagents)"
```

bash（写进 `~/.bashrc`）：

```bash
eval "$(register-python-argcomplete openagents)"
```

启用后：

```
$ openagents <Tab>
backfill-rfc  board  init  issue  release  report  vigil
$ openagents vigil --<Tab>
--base  --config  --hold  --interval  --label  --once  --parallel  --skip
```

不启用补全的用户完全无感：`argcomplete` 只在 shell 补全握手（`_ARGCOMPLETE` 环境变量存在）时介入，普通
运行下 `argcomplete.autocomplete(parser)` 立即返回，CLI 行为逐字不变。

## Reference-level explanation

### 接线（唯一改动点 `cli.py`）

模块顶层做**优雅降级导入**——`argcomplete` 是声明依赖，正常一定装了；但万一环境缺失（老快照 / 精简安装），
补全应静默不可用而非让整个 CLI 崩：

```python
try:
    import argcomplete
except ImportError:  # argcomplete 是声明依赖；缺失时补全静默不可用，不拖垮 CLI
    argcomplete = None
```

`main()` 在 `parse_args` 之前插桩（`build_parser()` 与 `parse_args` 之间是 argcomplete 文档规定的唯一
正确位置）：

```python
def main(argv=None) -> int:
    parser = build_parser()
    if argcomplete is not None:
        argcomplete.autocomplete(parser)   # 仅 shell 补全握手时介入并 exit；正常调用零副作用
    args = parser.parse_args(argv)
    ...
```

`argcomplete.autocomplete()` 的语义：仅当环境变量 `_ARGCOMPLETE` 被 shell 补全器设置时，它读 parser 生成
候选、打印、并 `os._exit()`；否则直接 `return None`。因此对 `main([])` / `main(["vigil", ...])` 等所有正常
调用它是**无操作**，既有分发/退出码/错误处理链全部不变。

### 依赖

`pyproject.toml` 的 `[project].dependencies` 追加 `argcomplete>=3.0`（3.x 是当前主线，提供
`register-python-argcomplete` 入口脚本）。

### DAG + 文件分配

单 Task（改动最小、四文件互不重叠、无内部依赖）：

| Task | 标题 | files | depends-on |
| --- | --- | --- | --- |
| T1 | argcomplete 接线 + 依赖 + 文档 + 测试 | `openagents/cli.py`, `pyproject.toml`, `README.md`, `tests/test_cli.py` | — |

### e2e 脚本

`scripts/e2e-spec-0069-argcomplete-shell-tab-completion.sh`（离线确定性：ruff check + ruff format --check
+ 针对性 pytest + grep 锚点），被 PR e2e signpost 采集。形态为纯 CLI/后端接线，无 product-facing 前端可
导航，故不设浏览器 e2e（见 frontmatter `e2e.method`）。

## Drawbacks

- 多一个运行时依赖 `argcomplete`（体积小、纯 Python、无二进制扩展，风险低）。
- 补全需用户在 shell 里一次性 `eval "$(register-python-argcomplete openagents)"`；不启用则无补全（这是
  argcomplete 的固有模型，非本接线可消除）。

## Rationale and alternatives

- **选 argcomplete（本方案）**：直接读现成 argparse parser，命令清单单一真源仍是 `build_parser`，零第二份
  维护，接线仅一行。
- **备选①：手写 `_openagents` zsh 补全脚本**——要把全部子命令/选项在 zsh 脚本里再抄一遍，`build_parser`
  一改就漂移，违背奥卡姆剃刀（理念 1）与单一真源，弃用。
- **备选②：迁到 `click`/`typer`（自带补全）**——为补全重写整个 CLI 框架，改动面与回归风险远超收益，弃用。
- **备选③：不做**——保持现状，交互体验差、与对标产品差距扩大，弃用。

## Prior art

- [argcomplete](https://github.com/kislyuk/argcomplete)（官方文档：在 `parse_args` 前调
  `argcomplete.autocomplete(parser)`，用 `register-python-argcomplete <prog>` 注册）是 argparse 生态补全的
  事实标准，被 `pip`、`aws-cli`（早期）等广泛采用。
- 本仓已有把「命令面信息收敛到 parser 单一真源」的取向（Spec-0064 把九条自动化命令并入 `vigil`），argcomplete
  正是这一取向在 shell 交互层的自然延伸。

## Unresolved questions

- 是否要在 `oa init` 里自动往用户 shell rc 注入启用行？倾向不做——改用户 shell 配置副作用大、不同 shell 各异，
  留给用户显式一次性启用更稳（本 spec 不含）。

## Future possibilities

- 为特定参数加**自定义 completer**（如 `--label` 补全仓库现有标签、PR/issue 编号补全活跃项），argcomplete
  支持给单个 `add_argument` 挂 `.completer`。
- 给 `spec` 那个 console_script 同样接入 argcomplete（本 spec 只覆盖 `openagents` 入口）。

