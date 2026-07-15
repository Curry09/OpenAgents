---
number: "0070"
title: openagents 自更新预检：每次命令前检测并拉取最新版（快照重装 + 重执行）
issue: 146
slug: self-update-precheck
summary: 在 openagents 入口每次执行前插一段自更新预检：检测记录分支是否落后源仓库远端(git fetch 比对本地 ref 与 remote/branch)，落后且可安全更新(当前分支==记录分支且工作区干净)则 git pull --ff-only → uv tool install --force → os.execvp 重执行原命令；拉取失败/不可安全更新则打印可操作提示并 fail-open 继续，绝不阻断日常命令、绝不切分支动脏工作区；源仓库路径记于 ~/.openagents/source.json(默认 origin/main，OPENAGENTS_HOME 可覆盖)，在源仓库内运行任一命令时自动侦测落盘；OPENAGENTS_SELFUPDATE_DONE=1 重执行守卫防循环，OPENAGENTS_NO_SELF_UPDATE=1 硬开关整段关闭(供 CI/测试)；核心逻辑纯函数可注入，测试 hermetic 打桩 subprocess/execvp 不触真实 git/uv/网络。
e2e:
  intent: 证明「openagents 入口每次命令前的自更新预检」这一接线在离线确定性链路上成立且零回归——precheck 纯函数可注入（run/execvp/environ/stderr 全部外部注入），DISABLE/DONE 两把守卫短路、无 source.json 短路、落后+安全走完整闭环(pull --ff-only → uv tool install --force → execvp 置 DONE=1)、不安全或任何异常一律 fail-open 打印提示继续；cli.main() 在 parse_args 前调 precheck 且正常调用行为逐字不变。
  method: "形态：纯 CLI/后端接线，无 product-facing 前端可导航；自检工具列表无 Playwright / Chrome DevTools MCP，故不设浏览器 e2e，改用离线确定性测法（沿用 Spec-0064/0066/0067/0069 同款）：\n1. selfupdate 针对性 pytest（注入 fake run/execvp，hermetic 不触真实 git/uv/网络/shell）：DISABLE/DONE 下 precheck 完全 no-op；无 source.json no-op；落后+安全→依次记录 pull --ff-only / uv tool install --force / execvp 且 execvp 环境含 OPENAGENTS_SELFUPDATE_DONE=1；落后但当前分支≠记录分支 / 工作区脏 / fetch 抛错 → 打印提示且不 exec（fail-open）；detect_source_repo 源仓库内落盘、目标项目内不落盘；OPENAGENTS_HOME 覆盖 home。\n2. CLI 接线 pytest：main() 在 parse_args 前调 selfupdate.precheck 恰一次；打桩 precheck 为 no-op 时 main([]) 仍返回 2（正常行为不变）。\n3. grep 锚点（e2e 脚本）：cli.py 存在 selfupdate.precheck 调用；selfupdate.py 存在 OPENAGENTS_NO_SELF_UPDATE / OPENAGENTS_SELFUPDATE_DONE / --ff-only / execvp；tests/conftest.py 存在 OPENAGENTS_NO_SELF_UPDATE。\n脚本：scripts/e2e-spec-0070-self-update-precheck.sh（ruff check + ruff format --check + 针对性 pytest + grep 锚点），被 PR e2e signpost 采集。\n"
tasks:
  - id: T1
    title: 自更新预检模块 + main() 接线 + 测试离网硬闸
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/utils/selfupdate.py
      - openagents/cli.py
      - tests/conftest.py
      - tests/test_selfupdate.py
    scope: 新增 openagents/utils/selfupdate.py（纯函数 + 可注入 run/execvp seam）：home_dir/source_config_path(尊重 OPENAGENTS_HOME)、SourceConfig(repo_path/remote=origin/branch=main)、load/save_source_config、detect_source_repo(cwd 在 OpenAgents 源仓库→落盘)、precheck(argv,environ,run,execvp,stderr) 编排：DISABLE/DONE 短路 → 自侦测落盘 → 无 source.json 短路 → git fetch(超时 fail-open) → 比对落后 → 安全(当前分支==记录分支且工作区干净)则 pull --ff-only + uv tool install --force + execvp 重执行(置 DONE=1) / 不安全则打印可操作提示 fail-open 继续；任何异常一律 fail-open 绝不阻断。cli.main() 在 parse_args 前调 selfupdate.precheck(argv=...)（仅 openagents 入口，spec 独立命令不接）。tests/conftest.py 全局 autouse 置 OPENAGENTS_NO_SELF_UPDATE=1 保证既有测试零回归不触网。
    acceptance: uv run pytest tests/test_selfupdate.py 通过：DISABLE/DONE 环境变量下 precheck 完全 no-op（不 fetch 不 exec）；无 source.json 时 no-op；落后+安全→依次 pull --ff-only/uv tool install --force/execvp 且置 OPENAGENTS_SELFUPDATE_DONE=1；落后但当前分支≠记录分支或工作区脏→打印提示且不 exec 继续（fail-open）；git fetch/子进程抛错→打印提示且不 exec 继续（fail-open，不上抛）；detect_source_repo 在源仓库内落盘 source.json、在目标项目内不落盘；OPENAGENTS_HOME 覆盖 home 路径。tests/conftest.py autouse 置 DISABLE=1，既有全套 pytest 仍绿。ruff check/format 干净。
---

# 0070 · openagents 自更新预检：每次命令前检测并拉取最新版（快照重装 + 重执行）

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

`openagents` 通过 `uv tool install --from . openagents` 安装，跑的是一份 **uv tool 快照**
（`~/.local/bin/openagents`），**不是** git 工作区的实时代码。源码 `git pull` 之后，快照仍跑旧代码，
必须 `uv tool install --force` 重装才更新。OpenAgents 自身是被 dogfood 的产品、持续自迭代，用户极易在
不知情下用着落后好几个提交的旧版本。

本 spec 在 **`openagents` 入口每次命令执行前**插一段**自更新预检**（新模块 `openagents/utils/selfupdate.py`
的纯函数 `precheck`，由 `cli.main()` 在 `parse_args` 之前调用）：

1. **检测**记录分支是否落后源仓库远端（`git fetch` 后比对本地 `<branch>` 的 ref 与 `<remote>/<branch>`）。
2. 落后且**可安全更新**时走完整闭环：`git pull --ff-only` → `uv tool install --force` → `os.execvp`
   **重执行**原命令，用户当次即刻跑在最新代码上。
3. 拉取失败 / 不可安全更新时打印**可操作报错提示**引导手动更新，随后 **fail-open 继续执行**当前命令。

源仓库路径记于 `~/.openagents/source.json`（默认 `origin` / `main`，`OPENAGENTS_HOME` 可覆盖），在源仓库内
运行任一命令时自动侦测落盘；`OPENAGENTS_SELFUPDATE_DONE=1` 是重执行防循环守卫，`OPENAGENTS_NO_SELF_UPDATE=1`
是硬开关整段关闭（供 CI / 测试 / hermetic）。核心逻辑纯函数、`run` / `execvp` seam 可注入，测试全 hermetic。

## Motivation

### 现状核实

- `pyproject.toml` 的 `[project.scripts]` 把 `openagents = "openagents.cli:main"` 装成 console_script；
  实际分发用 `uv tool install`，跑的是**安装时的快照**，与源码工作区解耦。
- `openagents/cli.py` 的 `main()` 现为 `parser = build_parser(); argcomplete...; args = parser.parse_args(argv)`
  （Spec-0069 已在 `parse_args` 前插过一次 argcomplete 钩子），**没有任何自更新检查**。
- `openagents/utils/` 下无 `selfupdate.py`；`~/.openagents/` 命名空间已被 `agent_config` /
  `fleet_config`（`Path(raw_path).expanduser()`）等使用，但没有「源仓库定位」这一份记录。

### 为什么要做

OpenAgents 持续自迭代、被自己 dogfood。快照与源码解耦这个**隐蔽陷阱**导致：源码 `git pull` 后，`openagents`
命令仍安静地跑旧快照，用户往往落后好几个提交而不自知——bug 早修好了却仍复现，新命令已合入却「不存在」。
缺一个「每次用命令时自动保证跑在最新版」的预检。这正是对标 cursor/windsurf 的交互顺滑（自动保持最新）
所要求的，也契合本仓「以成果为中心、人做宏观把控」的取向：版本新鲜度不该是用户的心智负担。

### 约束（issue #146 原文，就地复述）

- **源仓库定位**：运行的快照不知道源码在哪（cwd 通常是*目标*项目而非 OpenAgents 源仓库）。在
  `~/.openagents/source.json` 记录源仓库路径 / remote / branch（默认 `origin` / `main`）；在 OpenAgents 源
  仓库内运行任一命令时自动侦测并落盘（自配置），支持 `OPENAGENTS_HOME` 显式覆盖。
- **cadence = 每次，fail-open**：每次调用都检测；任何 `git fetch` / 网络 / 子进程失败只打软提示并继续，
  **绝不阻断**真实命令（离线可用）。
- **保护开发者 WIP**：源仓库常处于 feature 分支 / 有未提交改动。仅当「当前分支 == 记录分支」且「工作区
  干净」才自动 `pull --ff-only`；否则视为不可安全更新，走「提示 + 继续」，**绝不切分支、绝不动脏工作区**。
- **重执行防循环**：重装后重执行时置 `OPENAGENTS_SELFUPDATE_DONE=1`，子进程跳过预检，杜绝无限自更新循环。
- **可关**：`OPENAGENTS_NO_SELF_UPDATE=1` 硬开关关闭整段预检（供 CI / 测试 / hermetic）；预检仅作用于
  `openagents` 入口，对 `spec` 独立命令不生效。
- **奥卡姆**：不引入配置框架、不加网络库；git / uv 全走子进程；核心逻辑纯函数可注入，测试 hermetic。
- **零回归**：默认路径（已是最新 / 无 source.json）行为不变；新增 `tests/conftest.py` 全局置
  `OPENAGENTS_NO_SELF_UPDATE=1` 保证既有测试不触网。

## Guide-level explanation

**普通用户视角**：在 OpenAgents 源仓库里第一次跑任一 `openagents` 命令时，预检自动把源仓库路径记进
`~/.openagents/source.json`。此后在**任何目录**（通常是你的目标项目）跑 `openagents <命令>`，预检会：

- 若你已是最新 → 完全无感，命令照常跑。
- 若你落后了、且源仓库正停在干净的 `main` 上 → 自动 `git pull --ff-only` + `uv tool install --force`，
  然后**当次命令立刻用新版重跑**，你只会多看到两行「检测到新版本，正在更新…」的提示。
- 若你落后、但源仓库停在 feature 分支或有未提交改动 → 预检**绝不碰你的工作区**，只打印一行可操作提示：

  ```
  ⚠ openagents 已落后源仓库远端，但当前不可安全自动更新（分支/工作区）。
    手动更新：git -C <src> pull --ff-only && uv tool install --force --from <src> openagents
  ```
  然后 **fail-open 继续**跑你原本的命令。

- 离线 / `git fetch` 失败 → 同样只打软提示并继续，绝不阻断。

**关掉它**：`export OPENAGENTS_NO_SELF_UPDATE=1`（CI / 测试 / 不想每次 fetch 的场景）。

**只作用于 `openagents` 入口**：`spec` 那个独立 console_script 不接预检（它是纯本地工具，无自更新语义）。

## Reference-level explanation

### 新模块 `openagents/utils/selfupdate.py`

纯函数 + 可注入 seam（`run` 默认 `subprocess.run`，`execvp` 默认 `os.execvp`，`environ` 默认 `os.environ`，
`stderr` 默认 `sys.stderr`），使测试 hermetic 不触真实 git / uv / 网络 / shell。关键常量与 API：

```python
DISABLE_ENV = "OPENAGENTS_NO_SELF_UPDATE"   # 硬开关：置任意非空值 → 整段预检 no-op
DONE_ENV    = "OPENAGENTS_SELFUPDATE_DONE"  # 重执行守卫：重执行的子进程带上它 → 跳过预检，防循环
HOME_ENV    = "OPENAGENTS_HOME"             # 覆盖 ~/.openagents 落点
_GIT_NET_TIMEOUT_SECONDS = 30               # 镜像 utils.git；git fetch 挂死兜底，超时即 fail-open

@dataclass(frozen=True)
class SourceConfig:
    repo_path: str
    remote: str = "origin"
    branch: str = "main"

def home_dir(*, environ) -> Path          # OPENAGENTS_HOME 或 ~/.openagents
def source_config_path(*, environ) -> Path
def load_source_config(*, environ) -> SourceConfig | None   # 缺文件/坏 JSON → None（fail-open）
def save_source_config(*, config, environ) -> None
def detect_source_repo(*, cwd, run, environ) -> Path | None # cwd 在 OpenAgents 源仓库 → 落盘并返回 toplevel
def precheck(*, argv, environ, run, execvp, stderr) -> None # 唯一编排出口；绝不抛（fail-open）
```

**`precheck` 编排（顺序即短路优先级）**：

1. `DISABLE_ENV` 非空 → 直接 return（硬开关）。
2. `DONE_ENV` 非空 → 直接 return（重执行守卫，防循环）。
3. `detect_source_repo`：若 cwd 的 git toplevel 是 OpenAgents 源仓库（toplevel 下有 `openagents/cli.py`
   且 `pyproject.toml` 声明 `openagents` 入口）→ 用它 `save_source_config`（幂等自配置）。
4. `load_source_config`：无 `source.json` → return（还没在源仓库里跑过、无从检测，静默不打扰）。
5. `git -C <src> fetch <remote> <branch>`（带 `_GIT_NET_TIMEOUT_SECONDS` 超时）；任何非零/超时/异常 →
   打软提示、return（fail-open，离线可用）。
6. 比对：`git rev-parse <branch>` vs `git rev-parse <remote>/<branch>`，并 `git rev-list --count
   <branch>..<remote>/<branch>`；count == 0（不落后）→ return。
7. **安全闸**：`git rev-parse --abbrev-ref HEAD == <branch>` 且 `git status --porcelain` 为空。不满足
   → 打印可操作提示、return（fail-open，**绝不切分支、绝不动脏工作区**）。
8. `git -C <src> pull --ff-only <remote> <branch>`；失败 → 打提示、return（fail-open）。
9. `uv tool install --force --from <src> openagents`；失败 → 打提示、return（fail-open）。
10. `execvp(argv[0], argv)`，环境注入 `DONE_ENV=1`——用最新快照重执行原命令。**任何步骤的异常一律被
    最外层捕获转为软提示 + return**，`precheck` 对调用方永不抛。

### `cli.main()` 接线（唯一改动点）

`main()` 在 `parse_args` 之前调 `selfupdate.precheck`（放在 argcomplete 钩子之后、`parse_args` 之前——
补全握手时 argcomplete 已 `exit`，走不到预检；正常运行才做预检）：

```python
def main(argv=None) -> int:
    parser = build_parser()
    if argcomplete is not None:
        argcomplete.autocomplete(parser)
    from openagents.utils import selfupdate
    selfupdate.precheck(argv=sys.argv)   # 每次命令前自更新预检；fail-open，永不抛
    args = parser.parse_args(argv)
    ...
```

只接 `openagents` 入口；`openagents/spec/cli.py` 的 `spec` 命令**不接**（约束：仅作用于 openagents 入口）。
`precheck` 传 `sys.argv`（重执行要的是完整进程 argv，不是 `main(argv)` 的可选测试入参）。

### tests/conftest.py 全局离网守卫

现有 `tests/conftest.py` 已有「离网硬闸」autouse fixture（拦真实 `gh`）。本 spec 追加一条 autouse fixture
（或在既有 fixture 里）`monkeypatch.setenv(selfupdate.DISABLE_ENV, "1")`，保证**既有全套测试**在导入/调用
`cli.main` 时预检整段 no-op，零回归、不触网。

### DAG + 文件分配

单 Task（改动内聚、四文件互不重叠、无内部依赖）：

| Task | 标题 | files | depends-on |
| --- | --- | --- | --- |
| T1 | 自更新预检模块 + main() 接线 + 测试离网硬闸 | `openagents/utils/selfupdate.py`, `openagents/cli.py`, `tests/conftest.py`, `tests/test_selfupdate.py` | — |

### e2e 脚本

`scripts/e2e-spec-0070-self-update-precheck.sh`（离线确定性：ruff check + ruff format --check + 针对性
pytest + grep 锚点），被 PR e2e signpost 采集。形态为纯 CLI/后端接线，无 product-facing 前端可导航，故不设
浏览器 e2e（见 frontmatter `e2e.method`）。

## Drawbacks

- 每次 `openagents` 命令多一次 `git fetch`（网络往返，源仓库在本地磁盘、fetch 一个分支通常很快；超时兜底
  + fail-open 保证离线/慢网不阻断，但确实多一次网络调用）。可用 `OPENAGENTS_NO_SELF_UPDATE=1` 关。
- 自动 `execvp` 重执行对用户有一次「命令跑了两遍」的隐性成本（第一遍只做预检就重执行了）——但仅在真的落后
  且安全时发生，且重执行的子进程带 `DONE=1` 不再预检，最多一次。
- 侦测源仓库依赖「在源仓库内至少跑过一次任一命令」来落盘 `source.json`；从没在源仓库里跑过则无从检测
  （静默不打扰，非缺陷，见 Unresolved）。

## Rationale and alternatives

- **选「入口纯函数 precheck + 可注入 seam」（本方案）**：逻辑内聚在一个 utils 模块、`cli.main` 只加两行；
  git/uv 全走子进程（不加网络库、不引配置框架，符合理念 1 奥卡姆）；`run`/`execvp` 注入使测试 100% hermetic。
- **备选①：包管理器/后台守护自动更新**——引入常驻进程或第三方 auto-updater，重且与「快照跑在本地源仓库」
  的模型不符，弃用。
- **备选②：仅打印「有新版」提示、不自动更新**——少了「当次即刻跑最新」的闭环价值（用户仍在旧版上跑完这次），
  且 issue 明确要求 pull+重装+重执行闭环，弃用（但它正是**不可安全更新**分支的 fail-open 行为）。
- **备选③：在 shell wrapper / rc 里做更新**——改用户 shell 配置、跨 shell 各异、副作用大，弃用（同 Spec-0069
  对 argcomplete 自动注入 rc 的取舍）。
- **安全闸取「当前分支==记录分支 且 工作区干净」而非 `git stash`/切分支自动更新**：绝不动开发者 WIP 是硬
  约束——宁可不更新（fail-open 提示），也不能因自更新弄丢未提交改动或切走分支。

## Prior art

- **`os.execvp` 重执行**是 CLI 自更新/自重启的标准手法（如 `pyenv`/`rustup` 的 self-update 后重跑，
  Python 官方文档 `os.execvp` 说明进程镜像被替换、PID 不变）——用它让「更新后当次即刻生效」而不必让用户手动
  重敲命令。
- **`uv tool install --force`** 是 astral `uv` 官方文档给出的「重装/更新已安装 tool」方式，本仓 CLAUDE.md
  与既有实践（memory: openagents CLI 是 uv tool snapshot，改代码后须 `uv tool install --force --editable .`
  重装）都印证这一快照模型。
- **`git pull --ff-only`** 是「只在能快进时更新、否则拒绝」的安全更新惯例（git 官方文档），契合「绝不制造
  合并提交、绝不动分叉工作区」的约束。
- 本仓已有把网络 git 子进程加超时 + fail-open 的先例（Spec-0035 `_GIT_NET_TIMEOUT_SECONDS=30`），本模块
  镜像同一常量与 fail-open 取向。

## Unresolved questions

- **从没在源仓库里跑过任一命令**的用户（直接在目标项目里装了 openagents 快照、从未 cd 进源仓库）→ 无
  `source.json`、预检静默 no-op。是否要额外让 `oa init` 或某处显式落盘源路径？倾向不做（保持奥卡姆、自侦测
  已覆盖绝大多数 dogfood 路径），留作 future。
- 是否要节流「每次 fetch」为「每 N 分钟至多一次」（记 `last_check` 时间戳）以省网络往返？本 spec 遵 issue
  「cadence=每次」不做节流；若实测 fetch 开销明显，future 可加。

## Future possibilities

- 记 `last_check` 时间戳做 fetch 节流（上面 Unresolved 的自然延伸）。
- 给 `spec` 独立入口也接一个（可选）版本新鲜度提示（本 spec 明确只覆盖 `openagents` 入口）。
- 更新后在提示里附上 `git log <old>..<new> --oneline` 的变更摘要，让用户知道这次更新带来了什么。

