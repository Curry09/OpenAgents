---
number: "0027"
title: 多仓库统管:单进程按配置文件并发守夜一组仓库
issue: 77
slug: multi-repo-vigil
summary: 新增 openagents vigil-all 命令:单进程读一份 YAML 配置(仓库列表 + 全局默认 + 每仓库可选覆盖 interval/labels/base/hold),为每个仓库起一个隔离子进程复用现有 Vigil 并发守夜(发现→派单→守候),各读写自己的 .openagents/state.json,统一带仓库前缀聚合日志;单仓库 vigil 命令与底层逻辑零改动。
tasks:
  - id: T1
    title: 配置加载:YAML 解析 + jsonschema 校验 + 默认合并
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/fleet_config.py
      - tests/test_fleet_config.py
    scope: 新模块 fleet_config.py:用既有 ruamel.yaml 读 YAML 配置、jsonschema 按最小 schema 校验(顶层 defaults+repos;repos[] 必填 path、可选 name + interval/labels/base/hold 覆盖),把 defaults 与每仓库覆盖合并、path 绝对化、name 缺省取 basename,产出 RepoPlan 列表;纯解析无副作用。
    acceptance: 给定合法 YAML 返回合并后的 RepoPlan 列表(默认值正确下沉、每仓库覆盖生效、path 绝对化、name 缺省 basename);缺 repos/未知键/path 缺失等非法配置抛清晰校验错误;pytest 覆盖默认合并与各类非法输入。
  - id: T2
    title: 并发编排:每仓库一子进程跑现有 Vigil + 日志聚合 + 错误隔离
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - openagents/fleet.py
      - tests/test_fleet.py
    scope: 新模块 fleet.py:Fleet.run(plans,once) 为每个 RepoPlan 起一个 multiprocessing.Process,子进程 os.chdir(path)→resolve_project→延迟 import 复用 cli._vigil_for 构造 Vigil→vigil.run(interval/labels/base/once/hold);日志经 Queue 回传父进程加 [name] 前缀聚合;子进程崩溃记一行不拖垮其余,KeyboardInterrupt 逐个 terminate+join 干净退出。
    acceptance: Fleet.run 为 N 个 plan 起 N 个隔离子进程并发跑 Vigil;某子进程抛错/退出不影响其余(错误隔离);日志带各自仓库前缀;Ctrl-C 停下全部;pytest 用假 vigil 工厂验证 fan-out、前缀聚合、单进程失败隔离、停止路径(不触达真实 gh/后端)。
  - id: T3
    title: CLI 接线 vigil-all(--config/--once)
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - openagents/cli.py
      - tests/test_cli_fleet.py
    scope: 在 cli.py 新增 vigil-all subparser(--config 默认 .openagents/fleet.yml、--once)+ _cmd_vigil_all + _fleet_for 工厂,解析→load_fleet_config→Fleet.run;薄路由不含业务逻辑,现有 vigil subparser/_cmd_vigil 逐字节不变。
    acceptance: openagents vigil-all 可解析 --config/--once 并转发到 Fleet.run;默认 config 路径 .openagents/fleet.yml;现有 vigil 命令行为/签名不变;tests/test_cli_fleet.py 覆盖子命令解析与转发(打桩 Fleet 工厂,不真跑子进程)。
  - id: T4
    title: e2e 脚本演示多仓库统管闭环
    status: done
    priority: P2
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - scripts/e2e-spec-0027-vigil-all.sh
    scope: 新增 e2e 脚本:离线段 ruff + pytest;可选 OPENAGENTS_E2E_REAL=1 真烟测——对指向两个本地临时仓库的 fleet.yml 跑 openagents vigil-all --once,断言两仓库各守夜一轮、日志带各自前缀、各自 .openagents/state.json 独立写入。
    acceptance: bash scripts/e2e-spec-0027-vigil-all.sh 离线段全绿(ruff/pytest);真烟测段对两仓库 fleet.yml 跑 vigil-all --once 后两个仓库各自状态独立、日志前缀可区分来源。
---

# 0027 · 多仓库统管:单进程按配置文件并发守夜一组仓库

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给 OpenAgents 增加一条「多仓库统管」能力:新增子命令 `openagents vigil-all`(暂名,见 Unresolved questions),启动后**单进程**读取一份 **YAML 配置文件**——里面列出要统管的一组仓库(本地路径)、一份全局默认、以及每个仓库可选覆盖的 `interval` / `labels` / `base` / `hold`——然后**为每个仓库各起一个隔离子进程**,在其中复用**现有 `Vigil`** 跑各自的守夜循环(发现 issue → 派单 → 守候 PR),各仓库互不阻塞、各读写**自己的** `.openagents/state.json`,所有日志带「仓库名前缀」统一聚合到一处。等价于「同时拉起多个 `vigil` 并集中管理」,但只需一条命令、一份配置、一个总览入口。单仓库 `openagents vigil` 命令的签名与底层发现/派单/守候逻辑**零改动**。

## Motivation

当前 `openagents vigil` 是**逐仓库**的。把现状说清楚(单 spec 自包含,不靠裸引用):`Vigil`(`openagents/vigil.py`)的构造函数是 `Vigil(*, orchestrator, messages, state, work_dir)`,其中 `work_dir` 被绑定成**那一个** repo 的根——它在发现段去重闸里用 `git -C <work_dir> ls-remote ...` 查远端分支(`vigil.py:141-148`);状态存在**各自的** `work_dir/.openagents/state.json`(CLI 工厂 `_state_for` 用 `repo_root / ".openagents" / "state.json"` 派生,`cli.py:140-143`);发现段 `github.list_issues` 最终落到 `gh issue list`,而 `github` 模块所有 `gh` 调用都是 `subprocess.run(["gh", *args], ...)` **不传 `cwd`**(`github.py:140-156`)——也就是说 `gh` 永远操作**当前进程工作目录**所在的那个仓库。整条 CLI 接线(`_vigil_for` / `_orchestrator_for` / `_messages_for`,`cli.py:163-197`)都从 `resolve_project()`(读 cwd 的 git root,`config.py:36-44`)推出的单个 `ctx.repo_root` 派生。

结论:**一个 vigil 进程在结构上就只能管它启动所在的那一个仓库**。要同时守夜 N 个仓库,今天只能起 N 个 vigil 进程、各自 `cd` 进对应目录后台跑、各看各的 log。仓库一多,运维成本(N 条启动/重启/查日志命令)和心智负担(没有一个统一总览,不知道哪个仓库此刻在干什么)都线性上涨,也没有「集中管理」的入口。

这正是实际使用中暴露的缺口:多仓库场景下「逐仓库一个进程」不便,需要**单进程 + 配置文件**统管的入口。本 feature 用一条编排命令补上它,且天然是 dogfood——OpenAgents 自身就是用 MVP 迭代自身的产品,统管多个被它服务的仓库,正是把守夜能力规模化的下一步。

## Guide-level explanation

使用者写一份配置文件(默认 `.openagents/fleet.yml`),列出要统管的仓库:

```yaml
# 全局默认:每个仓库未显式覆盖时取这里的值
defaults:
  interval: 60          # 轮询间隔(秒)
  labels: [openagents]  # issue 发现标签门控
  base: main            # 派单起草改动的分支基线
  hold: null            # 闸门(spec / merge / spec,merge);null = 全自动不停

# 要统管的仓库列表(本地路径);每项可选覆盖上面任一默认
repos:
  - path: /Users/me/work/repo-a          # 全用默认
  - path: ../repo-b
    interval: 120                        # 这个仓库轮得慢一点
    labels: [openagents, urgent]
    base: develop
  - path: ~/work/repo-c
    name: c                              # 可选:日志前缀显示名,缺省取路径 basename
    hold: spec,merge                     # 这个仓库要人在 spec/merge 闸停一下
```

然后一条命令拉起统管:

```
openagents vigil-all                       # 读默认 .openagents/fleet.yml
openagents vigil-all --config fleet.yml    # 指定配置
openagents vigil-all --once                # 每个仓库各跑一轮即退出(cron/CI/e2e 用)
```

看到的输出是**带仓库前缀的聚合日志**,一眼区分是哪个仓库的事件:

```
[repo-a] ▶ issue #12:修登录 bug → 派单起草 RFC
[repo-b] … 守夜中,120s 后再扫一轮
[c]      ✗ 本轮守夜失败,跳过、60s 后再扫一轮:gh 超时
[repo-a] … 守夜中,60s 后再扫一轮
```

心智模型:`vigil-all` 就是「**一次拉起 N 个 `vigil`、并集中看日志**」。每个仓库背后跑的就是原来那个 `openagents vigil`——同样的发现→派单→守候、同样的 `.openagents/state.json`、同样的错误隔离行为,只是不用再手动开 N 个终端 `cd` 进去。某个仓库卡住或报错,只影响它自己那一行日志,其余仓库照常推进。`Ctrl-C` 一次性停下全部。

## Reference-level explanation

**技术方案总纲**——`vigil-all` 是一层**薄编排**(理念 1 奥卡姆):`读配置 → 为每个 repo 起一个隔离执行单元、在其中复用现有 Vigil → 并发调度 → 聚合日志`。它**不重写**任何发现/派单/守候逻辑,也**不碰** `vigil` / `Vigil` / `github` / `Orchestrator` 的现有签名与行为。

**核心决策:进程级隔离(每仓库一个子进程),不是线程。** 原因直接来自 Motivation 里的现状约束:`github` 模块的 `gh` 调用绑定**进程工作目录**(`subprocess.run(["gh", ...])` 不传 `cwd`),而 `os.chdir` 改的是**进程全局** cwd——同一进程内多个线程无法各自拥有不同的 cwd,因此线程模型下两个仓库的 `gh issue list` 会互相串台,根本不可行。给每个仓库一个**独立子进程**则一举解决:子进程启动后 `os.chdir(repo_path)`,于是它的 cwd、它构造的 `Vigil`/`State`、它的 `gh` 调用全部锁定到自己的仓库;子进程之间内存隔离(状态天然不混)、崩溃隔离(一个挂掉不波及其余)、且真正并行(各自的 `time.sleep(interval)` 阻塞与 `gh`/`git` 子调用互不影响)。

各组件:

- **配置加载 `openagents/fleet_config.py`**(新模块):用项目既有的 `ruamel.yaml`(已是依赖,`pyproject.toml:9-12`)读 YAML,用既有的 `jsonschema`(同上)按一份**最小 schema** 声明式校验,再把 `defaults` 与每个 repo 的覆盖项**合并**成一组 `RepoPlan`(每项含绝对化后的 `path`、显示 `name`、以及 `interval`/`labels`/`base`/`hold`)。纯解析、无副作用,便于单测。沿用项目既有约定:YAML 格式(`lefthook.yml` / `.commitlintrc.yml` / spec frontmatter 都是 YAML)、`ruamel.yaml` + `jsonschema` 校验(`openagents/spec/` 同款),不引入任何新依赖或新格式(理念 1)。
- **并发编排 `openagents/fleet.py`**(新模块):入口 `Fleet.run(*, plans, once)`——为每个 `RepoPlan` 起一个 `multiprocessing.Process`,目标函数 `_run_repo(plan, log_queue)`:`os.chdir(plan.path)` → `resolve_project()` → 复用现有 CLI 工厂 `_vigil_for(ctx=...)` 构造 `Vigil`(延迟 import,沿用本仓库「命令体内延迟 import」惯例,避免与 `cli` 形成顶层循环依赖)→ 调 `vigil.run(interval=plan.interval, labels=plan.labels, base=plan.base, once=once, hold=parse_hold(plan.hold))`。子进程的守夜日志(`Vigil._log` 写 stderr)经一个 `multiprocessing.Queue` 回传父进程,父进程统一加 `[name] ` 前缀打到 stderr(可观测:统一视图、区分来源)。父进程监管子进程生命周期:子进程异常退出 → 记一行 `[name] 守夜进程退出(code N)` 但**不拖垮其余**(对齐 `Vigil` 既有错误隔离:RFC-0004 决策 8 单 issue 跳过 + RFC-0010 决策 5/6 单轮失败进下一轮——这里把同一隔离哲学上升到「单仓库失败不拖垮 fleet」);父进程收到 `KeyboardInterrupt` → 逐个 `terminate()`+`join()` 所有子进程后干净退出。
- **CLI 接线 `vigil-all`**(`openagents/cli.py`):新增 subparser(`--config` 默认 `.openagents/fleet.yml`、`--once`)+ `_cmd_vigil_all` + `_fleet_for` 工厂,解析 → `load_fleet_config` → `Fleet.run`;薄路由不含业务逻辑,与现有 `vigil` 子命令并存、互不影响(`vigil` 的 subparser 与 handler `cli.py:104-123` / `_cmd_vigil` 保持逐字节不变)。

**配置 schema(最小够用)**:顶层两键 `defaults`(对象,可选,全局默认)+ `repos`(数组,必填,至少 1 项)。`defaults` 与每个 `repos[]` 项共享同一组可选键 `interval`(int)/`labels`(string 数组)/`base`(string)/`hold`(string 或 null);`repos[]` 项另有必填 `path`(string,本地路径,支持 `~`/相对路径,解析时绝对化)与可选 `name`(string,日志前缀名,缺省取 `basename(path)`)。未识别键报校验错误,防手滑。

**Task 分解(files 互斥,各 Task 单一 writer——理念 6)**:

| Task | 范围 | owns files | 依赖 |
|---|---|---|---|
| T1 | 配置加载:YAML 解析 + jsonschema 校验 + 默认合并 → `RepoPlan` 列表 | `openagents/fleet_config.py`, `tests/test_fleet_config.py` | — |
| T2 | 并发编排:每仓库一子进程跑现有 Vigil + 日志聚合 + 崩溃/Ctrl-C 隔离 | `openagents/fleet.py`, `tests/test_fleet.py` | T1 |
| T3 | CLI 接线 `vigil-all`(`--config`/`--once`)+ `_cmd_vigil_all` + `_fleet_for` | `openagents/cli.py`, `tests/test_cli_fleet.py` | T2 |
| T4 | e2e 脚本演示多仓库统管闭环 | `scripts/e2e-spec-0027-vigil-all.sh` | T3 |

```mermaid
graph LR
  T1[T1 配置加载] --> T2[T2 并发编排]
  T2 --> T3[T3 CLI 接线]
  T3 --> T4[T4 e2e 脚本]
```

**端到端验证**:`bash scripts/e2e-spec-0027-vigil-all.sh`(ruff + pytest 离线段;可选 `OPENAGENTS_E2E_REAL=1` 真烟测:对一份指向两个本地临时仓库的 `fleet.yml` 跑 `openagents vigil-all --once`,断言两个仓库各被守夜一轮、日志带各自前缀、各自 `.openagents/state.json` 独立写入)。

## Drawbacks

- **多进程的运维复杂度**:`vigil-all` 父进程要正确管理 N 个子进程的生命周期(回收僵尸、转发停止信号、聚合输出)。比起「人手开 N 个 vigil」,代码层面的并发/IPC 复杂度上升,父进程本身成了一个新的单点(它崩了全停)。
- **进程数随仓库数线性增长**:每仓库一个子进程,外加每个 vigil 内部派单还会再起 worktree/后端子进程,仓库一多对机器资源(内存、文件句柄、`gh` 速率限制)有压力;MVP 不设并发上限(见 Future possibilities)。
- **多一条入口的认知成本**:`vigil`(单仓库、在仓库内跑)与 `vigil-all`(多仓库、读配置)并存,使用者要分清何时用哪个。
- **配置文件即新的可漂移源**:路径写错、仓库被移动/删除,要到运行期才暴露;需要清晰的校验报错兜底。

## Rationale and alternatives

选「**单进程 + 每仓库一个 `multiprocessing` 子进程,子进程内复用现有 `Vigil`**」是因为它同时满足全部硬约束:复用而非重写(子进程内走的就是现有 `_vigil_for` → `Vigil.run`)、单仓库逻辑零改动、状态隔离(各子进程各自的 cwd → 各自的 `state.json`)、错误隔离(进程级崩溃不传染)、真正并发(绕开 cwd 全局性与 `time.sleep` 阻塞),且编排层极薄。

- **备选 A:线程池(`ThreadPoolExecutor`),每线程一个 `Vigil`**——本仓库已有线程先例(`reviewer.py` 用 `ThreadPoolExecutor` 并发 reviewer)。但**根本不可行**:`github` 的 `gh` 调用绑进程 cwd、`os.chdir` 是进程全局,多线程无法各持不同 cwd,两个仓库的 `gh issue list` 会串台;且 `Vigil.run` 的 `time.sleep` 与诸多同步子调用也不天然适配线程。否决——这正是选进程的直接理由。
- **备选 B:父进程 `subprocess.Popen(["openagents", "vigil", ...], cwd=repo)` 监管 N 个 CLI 子进程**——更解耦(只依赖 `vigil` 公共命令、零 import 耦合),cwd/状态/崩溃隔离同样免费。但要稳定地以「子进程方式」调起本包入口(`python -m openagents` 需 `__main__.py` / 或依赖 console_script 在 PATH),在测试与不同安装形态下较脆;且把编排参数序列化成命令行 flag 再解析一遍,不如直接传 `RepoPlan` 对象顺手。保留为合理近邻,但选 `multiprocessing` 以「在进程内直接构造 `Vigil` 对象」更贴合「为每个 repo 构造一个 Vigil」的本意、也更好单测(可对 `Fleet` 注入假 vigil 工厂)。
- **备选 C:单进程串行轮询(一个线程里 `chdir` 到 A 跑一轮、再 `chdir` 到 B 跑一轮……)**——最省事、无并发,但任一仓库的派单/守候一旦卡住(如后端长跑、`gh` 重试退避)就阻塞全部仓库,违背「一个仓库卡住不拖垮其余」的硬要点。否决。
- **配置格式备选:TOML / JSON**——项目无 TOML 依赖;JSON 不便人手写(无注释)。YAML 是项目既有约定(`lefthook.yml`/`.commitlintrc.yml`/spec frontmatter)且 `ruamel.yaml` 已在依赖里,选 YAML 不增实体(理念 1)。

## Prior art

- **进程级 supervisor 谱系**(`supervisord`、`foreman`/Procfile、`pm2`、`tmuxinator`):都是「一份声明式配置列出一组要跑的进程,一个监管者并发拉起、聚合输出、管理重启」。`vigil-all` 是这一模式在 OpenAgents 守夜场景的最小特化——配置项就是「仓库 + 各自的守夜参数」,被监管的进程就是 vigil。证明「配置文件 + 单监管者 + 多子进程 + 日志聚合」是成熟可行的形态。
- **OpenAgents 内部先例**:`Vigil` 自身的错误隔离决策(RFC-0004 决策 8「单 issue 失败跳过」、RFC-0010 决策 5/6「单轮失败进下一轮、once 模式照旧上抛」,均在 `openagents/vigil.py`)是本组「单仓库失败不拖垮 fleet」的同构上层延伸;`reviewer.py` 的 `ThreadPoolExecutor` 是并发先例(但因 cwd 全局性不适用于本场景,见备选 A)。
- **CLI 多目标编排通例**(如 `kubectl --context`、`git -C <dir>`、monorepo 任务跑器 `turbo`/`nx` 的 `--parallel`):证明「一条命令按配置并发作用于多个目标 + 带目标前缀聚合输出」是用户熟悉的交互范式。

## Unresolved questions

- **命令最终名**:`vigil-all` vs `fleet` vs 其它(issue 里标「名字待定」)。本 spec 默认采用 `vigil-all`(对 `vigil` 用户最自解释、可发现性最好);若评审更偏好 `fleet`(更短、有「机群」隐喻),实现期一处改名即可。**待人确认**。
- **默认配置路径**:默认 `.openagents/fleet.yml`(与 `.openagents/state.json` 同目录,符合既有约定)是否合适,还是只接受显式 `--config`。倾向保留默认以省一个 flag。**待人确认**。
- **子进程异常退出后是否自动重启**:MVP 仅「记一行并保留其余」,不自动重启(对齐「代码即 checkpoint、重跑即续」的哲学——人重跑 `vigil-all` 即可恢复)。是否要加 `--restart`/退避重启留待真实需要。
- **`multiprocessing` 启动方式**:macOS/Win 默认 `spawn`(子进程重新 import 模块、要求 target 函数与 `RepoPlan` 可 pickle),Linux 默认 `fork`。实现期需确保 target 为模块级函数、`RepoPlan` 为可 pickle dataclass;是否显式固定 start method 留待实现期按测试表现定。

## Future possibilities

- **并发上限旋钮**:仓库很多时用 `--max-parallel N`(或配置项)限制同时活跃的子进程数,排队调度,缓解资源压力。
- **远端仓库直管**:配置项支持 `remote`(而非仅本地 `path`),`vigil-all` 先按约定克隆/更新到本地工作区再守夜,省去手动 clone(本组**不做**,issue 边界明确只收本地路径)。
- **统一总览看板**:把各仓库 `state.json` 聚合成一个跨仓库 `board`(复用 `openagents board` 的成果看板),给一个「所有仓库此刻在做什么」的可视化总览(理念 8 以成果为中心)。
- **与常驻服务/Web 控制台串联**:把 `vigil-all` 升级为带 HTTP 状态端点的常驻服务(issue 明确把这列为后续话题,本组不做)。
- **守护进程化**:`vigil-all --daemon` 后台化 + 日志落盘 + 健康检查,进一步降低长期运维成本。

