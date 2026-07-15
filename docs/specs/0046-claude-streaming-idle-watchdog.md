---
number: "0046"
title: claude -p 流式调用 idle 看门狗：无进展停顿超时防 agent 僵死冻死 vigil
issue: 148
slug: claude-streaming-idle-watchdog
summary: 给 ClaudeCodeBackend._run_claude_streaming 的阻塞式 stream-json 逐行读加一道 idle（停顿）看门狗：连续 N 秒无新输出行判定 claude 僵死 → terminate→kill 子进程 + 抛既有 RuntimeError，交既有 per-issue/per-round try/except 隔离（跳过、下轮重试）。判据是有没有进展（新输出）不是总时长——健康长任务持续吐 stream-json 事件不受影响，逐字节零回归。阈值走 OPENAGENTS_CLAUDE_IDLE_TIMEOUT 环境旋钮（宽默认不误杀长任务），再设一个远大于 idle 的绝对墙钟上限做最后兜底。与 vigil 既有硬超时（_AGENT_TIMEOUT_SECONDS，会误杀健康长任务）互补：本 spec 管 agent 流的停顿，#147 管 git 网络的硬超时，二者合起来才让「vigil 再也不会无输出地永久卡死」成立。
e2e:
  intent: 证明 _run_claude_streaming 的 idle 看门狗在「真长时间静默」时确定性触发（terminate→kill 子进程 + 抛既有 RuntimeError），而在「健康持续吐 stream-json 事件」时逐字节零回归、绝不误杀；绝对墙钟上限兜住「每 tick 吐一行垃圾但永不结束」的病态流。
  method: |
    形态：纯内部后端进程管理改动，无 product-facing 前端可导航、无对外可见产物；自检工具列表无浏览器 MCP，
    故不设浏览器 e2e，改用相称的 hermetic 自动化测试（不调真实 claude）：
    1. 假 Popen 覆盖看门狗三分支——stdout 为可控节奏行序列生成器，「长时间静默」用 threading.Event 阻塞
       模拟读挂住，terminate()/kill() 置该 Event 解除阻塞→迭代结束（复刻「杀进程→管道关→for 退出」）；
       测试把 OPENAGENTS_CLAUDE_IDLE_TIMEOUT 设极小值（如 0.1s）使触发确定性、亚秒级，不真等。
       ① idle 触发：静默流 → terminate 后 kill 被调 + 抛 RuntimeError 含「停顿超时」；
       ② 墙钟触发：每 tick 吐一行但总时长超 OPENAGENTS_CLAUDE_MAX_WALL → 抛 RuntimeError 含「墙钟超时」；
       ③ 零回归：连续正常流 → 看门狗从不介入读、从不杀，输出/摘要/returncode 与改动前逐字节一致；
       ④ 访问器：effective_idle_timeout/effective_max_wall 解析 env、非法/空白/<=0 落缺省或关闭。
    2. 离线 e2e 脚本 scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh：ruff check + ruff format
       --check + 针对性 pytest tests/test_backend_claude_code.py，被 PR e2e signpost 采集。
tasks:
  - id: T1
    title: backend 加 idle 看门狗 + env 旋钮
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - openagents/backends/claude_code.py
    scope: 在 _run_claude_streaming 的阻塞式 stream-json 读外挂一个轻量守护看门狗线程：主循环逐行读时刷新 last_activity（monotonic），看门狗轮询检查 idle（连续静默超 OPENAGENTS_CLAUDE_IDLE_TIMEOUT）与绝对墙钟（超 OPENAGENTS_CLAUDE_MAX_WALL）→ terminate()→kill() 子进程 → 主循环随管道关闭而退出 → 收尾抛既有 RuntimeError（带停顿/墙钟超时详情），交上游 per-issue/per-round try/except 隔离。新增模块级常量 IDLE_TIMEOUT_ENV/MAX_WALL_ENV + 缺省 + 访问器 effective_idle_timeout()/effective_max_wall()，镜像既有 effective_permission_mode 范式。读路径处理逻辑逐字节不变（零回归）。
    acceptance: ruff check + ruff format --check 绿；健康连续流路径的输出/摘要/returncode 与改动前逐字节一致（看门狗从不介入读、从不杀）；真静默流超 idle → terminate 后 kill 被调用且抛 RuntimeError 含「停顿超时」；每 tick 吐一行但总时长超 max_wall → 抛「墙钟超时」；effective_idle_timeout/effective_max_wall 正确解析 env、非法/空白/<=0 落缺省或关闭；不新增异常类型（复用 RuntimeError）；不引入线程池/async 框架。
  - id: T2
    title: hermetic 测试 + 离线 e2e 脚本
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tests/test_backend_claude_code.py
      - scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh
    scope: 用假 Popen（stdout 为可控节奏行序列 + threading.Event 制造长时间静默，terminate/kill 置 Event 解除阻塞→迭代结束）覆盖 idle 看门狗三条分支，不调真实 claude：① idle 触发（静默→terminate/kill 被调 + RuntimeError 含停顿超时）；② 墙钟触发（每 tick 吐一行但超绝对上限→RuntimeError 含墙钟超时）；③ 零回归（连续正常流→看门狗不杀、输出/摘要/returncode 不变）；④ 访问器解析/缺省/关闭。测试把 OPENAGENTS_CLAUDE_IDLE_TIMEOUT 设极小值（如 0.1s）使触发确定性、亚秒级。新增离线 e2e 脚本（ruff check + ruff format --check + 针对性 pytest），供 PR e2e signpost 采集。
    acceptance: pytest tests/test_backend_claude_code.py 通过，覆盖 idle 触发 / 墙钟触发 / 零回归 / 访问器四类，全部用假 Popen 不触真实 claude；静默用 threading.Event 阻塞、terminate/kill 解除，测试亚秒级不真等；bash scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh 绿（ruff check + ruff format --check + 针对性 pytest 全过）。
---

# 0046 · claude -p 流式调用 idle 看门狗：无进展停顿超时防 agent 僵死冻死 vigil

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给 `ClaudeCodeBackend._run_claude_streaming`（`openagents/backends/claude_code.py`）派 coding agent 的
`claude -p` 流式读加一道 **idle（停顿）看门狗**：以「有没有新输出行」为**进展**判据，若连续 `N` 秒没有任何
新的 stream-json 行到达，就判定 claude 已僵死，`terminate()`→（超时再）`kill()` 子进程，抛出**既有的**
`RuntimeError`（带「claude 停顿超时」详情），交由既有的 per-issue / per-round `try/except` 隔离（这一轮这个
agent 失败 → 跳过、下轮重试），**绝不掀翻整个守夜进程**。阈值走环境变量旋钮 `OPENAGENTS_CLAUDE_IDLE_TIMEOUT`
（与既有 `OPENAGENTS_*` 风格一致，缺省给一个足够宽、不误杀正常长任务的值）；再设一个**远大于 idle 的绝对墙钟
上限**（`OPENAGENTS_CLAUDE_MAX_WALL`）做最后兜底，防「每隔 59 秒吐一行垃圾但永不结束」的病态流。关键不变量：
**健康的长任务会持续吐 stream-json 事件，其读取行为逐字节不变**——idle 超时只在真长时间静默时触发。

## Motivation

### 现状（就地复述，单 spec 自包含）

`_run_claude_streaming` 以子进程非交互方式起 `claude -p`，用 `Popen` 逐行读 NDJSON 事件流：

```python
proc = subprocess.Popen(
    [CLAUDE_BIN, "-p", prompt, "--permission-mode", effective_permission_mode(), *_STREAM_ARGS],
    cwd=work_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    text=True, bufsize=1, pass_fds=proc_utils.inherited_fds(),
)
proc_utils.publish(pid=proc.pid, handle=proc)
for raw in proc.stdout:        # ← 阻塞式逐行读，没有任何超时保护
    ...
returncode = proc.wait()
```

`for raw in proc.stdout:` 是**阻塞式**的：每次迭代都等下一行到来。一旦 claude 侧卡住——挂在对 Anthropic API
的网络请求上、等一个永不到来的输入、或进程僵死——这个 for 循环会**无限等**，把 orchestrator / vigil 整轮
冻死，症状与 #147 一致（进程活着、零输出、不前进）。

### 为什么不能用硬超时

与 #147 的区别：那批是**裸 git 网络调用**，可以直接加**硬超时**；而 `claude -p` 是**长时运行**的 agent
调用，正常也可能跑好几分钟甚至更久，硬超时会**误杀健康的长任务**。所以要的是**空闲/停顿（idle/stall）超时**，
不是硬超时——判据是**有没有进展（新输出）**，不是**总时长**。健康的长任务会持续吐 stream-json 事件（助手
文本 + 每一次工具动作都是一条事件），只有真僵死才会长时间静默。

### 为什么 vigil 既有的硬超时不够（关键：这不是重复造轮子）

vigil 已在 recipes 层给 backend 套了一道**硬墙钟** `_TimedBackend`（Spec-0065/T2，`_AGENT_TIMEOUT_SECONDS
= 1800`s）：在专跑 agent 的那个线程里 `join(timeout=…)`，超时按 `thread.ident` 取认领桶、`proc.kill_tree`
杀进程树。它为什么补不上本 issue 的洞：

1. **它是进展盲（progress-blind）的硬墙钟。** 为了不误杀健康的长任务，它必须设得**很宽**（30 分钟）；于是
   一个**真僵死**的 agent 会白白冻死最多 30 分钟才被它捞起——而 idle 看门狗在真静默几分钟后就该动手。二者
   是**互补**关系：idle 管「静默 = 僵死」的快速判定，硬墙钟管「持续吐垃圾但永不结束」的绝对上限（本 spec
   自带的 `OPENAGENTS_CLAUDE_MAX_WALL` 兜底与它同源同理，但落在 backend 层、对所有调用方生效）。
2. **它只在 vigil 路径上存在。** `_TimedBackend` 是 recipes.vigil 的包装层；backend `_run_claude_streaming`
   被**任何调用方**（非 vigil 的直接 orchestrator 路径、future CLI、测试夹具）调用时**裸奔无保护**。把 idle
   看门狗放进 backend 自身，才是「谁阻塞谁自保」的正确落点——每个调用方都免疫，无需各自再包一层。
3. **fail-open 语义要就地对齐。** 超时转为「这轮这个 agent 失败 → 跳过、下轮重试」，与守夜「活着进下一轮」
   一致；本 spec 复用**既有的** `RuntimeError`（`_run_claude_streaming` 非零退出时已在抛它），让上游隔离
   逻辑零改动地接住。

本 issue 与 #147 独立、可并行；二者合起来才让「**vigil 再也不会无输出地永久卡死**」这条不变量成立（#147 管
git 网络的硬超时、本 issue 管 agent 流的停顿）。

## Guide-level explanation

对使用者而言，行为的默认表现**不变**——正常跑的 agent 调用（持续吐事件）逐字节照旧。新增的是两个环境旋钮
和一条静默保护：

```bash
# 停顿超时：连续这么多秒没有任何新输出行 → 判 claude 僵死、杀掉、抛 RuntimeError。默认足够宽（见 §Reference）。
export OPENAGENTS_CLAUDE_IDLE_TIMEOUT=300
# 绝对墙钟上限（可选兜底）：单次调用总时长超它 → 同样杀掉、抛出。远大于 idle，防「每 59s 吐一行垃圾」的病态流。
export OPENAGENTS_CLAUDE_MAX_WALL=3600     # 设 0（或留空）关闭该兜底
```

三种典型情形：

- **健康长任务**（跑 10 分钟、期间持续吐 stream-json 事件）：每来一行都刷新「上次进展时间」，idle 计时归零，
  看门狗**永不触发**；`OPENAGENTS_CLAUDE_MAX_WALL` 默认远大于它，也不触发。行为与今天完全一致。
- **真僵死**（claude 挂在网络请求上、零输出）：静默满 `OPENAGENTS_CLAUDE_IDLE_TIMEOUT` 秒 → 看门狗
  `terminate()`→`kill()` 子进程 → `_run_claude_streaming` 抛 `RuntimeError("...claude 停顿超时...")` →
  被既有 per-issue / per-round `try/except` 接住 → 这一轮这个 agent 跳过、下轮重试。守夜活着进下一轮。
- **病态流**（每隔 59 秒吐一行垃圾、永不 `result`）：idle 判据被它骗过（一直有「新行」），但总时长撞到
  `OPENAGENTS_CLAUDE_MAX_WALL` → 同样被杀 + 抛出。

## Reference-level explanation

### 机制：轻量看门狗线程 + 单调时钟「上次进展」戳

遵循奥卡姆约束（**不引入线程池 / async 框架**），采用「一个轻量看门狗线程 + 主循环读 `proc.stdout`」：

- **主读循环逐字节不变。** 仍是 `for raw in proc.stdout:`，每处理一行**只多做一件事**：把 `last_activity`
  刷成 `time.monotonic()`（单调钟，不受系统时间回拨影响）。事件解析、打印、`result` 提取全部原样——这是
  「零回归」的结构保证：健康流的输出路径不经过看门狗。
- **看门狗守护线程（daemon）** 起一个 `stop_event`，循环 `wait(poll_interval)`（`poll_interval` 取一个小
  值，如 `min(idle, 5)`），每轮检查：
  - `idle > 0 且 now - last_activity > idle` → 记 `reason = "停顿超时"`、`terminate()`→ 宽限 → `kill()`、
    置 `stop_event`；
  - `max_wall > 0 且 now - start > max_wall` → 记 `reason = "墙钟超时"`，同样终止。
  - 杀掉子进程会关闭其 stdout 管道 → 主循环的 `for raw in proc.stdout:` **随即结束迭代**（这是唤醒阻塞读
    的唯一手段，无需在读路径里插任何超时判断，故读路径零改动）。
- **收尾判定。** 主循环退出后 `returncode = proc.wait()`；置 `stop_event` 并 `join` 看门狗线程；若看门狗
  记了 `reason`，则抛**既有的** `RuntimeError(f"Claude Code CLI 调用停顿超时…{reason}…")`（**不新增异常
  类型**，上游 `try/except Exception` 零改动接住）；否则走既有的 returncode 分支。
- **终止走 `proc.terminate()`→ 宽限 → `proc.kill()`**（issue 明列）。backend 已在 `Popen` 后
  `proc_utils.publish(pid, handle)`，与 vigil 的进程树杀彼此独立、不冲突（看门狗是 backend 层的**内层**
  自保，先于 vigil 30 分钟硬墙钟在真静默时动手）。

### 环境旋钮（模块级常量 + 访问器，镜像 `effective_permission_mode`）

沿用同文件既有 `PERMISSION_MODE_ENV` / `_DEFAULT_PERMISSION_MODE` / `effective_permission_mode()` 的最小
env-旋钮范式（不引入配置文件、单一真相源访问器）：

| 常量 | 环境变量 | 缺省 | 语义 |
|---|---|---|---|
| `IDLE_TIMEOUT_ENV` | `OPENAGENTS_CLAUDE_IDLE_TIMEOUT` | `300`（秒） | 连续静默上限；`<=0` 视为关闭 idle 看门狗 |
| `MAX_WALL_ENV` | `OPENAGENTS_CLAUDE_MAX_WALL` | `3600`（秒） | 绝对墙钟兜底；`<=0` 关闭 |

`effective_idle_timeout()` / `effective_max_wall()`：读 env、`float()` 解析、非法/空白/`<=0` 落缺省或关闭
（默认行为不变、非侵入）。缺省值取「足够宽、不误杀正常长任务」：idle 300s（5 分钟**完全**静默对健康的
stream-json 流已是极强的僵死信号），墙钟 3600s（1 小时，远大于 idle，且小于/接近 vigil 1800s 硬墙钟的量级
但作用于所有调用方）。**确切默认值列入 Unresolved，交人确认。**

### DAG + 文件分配

| Task | 标题 | files（互斥） | depends-on |
|---|---|---|---|
| T1 | backend 加 idle 看门狗 + env 旋钮 | `openagents/backends/claude_code.py` | — |
| T2 | hermetic 测试 + 离线 e2e 脚本 | `tests/test_backend_claude_code.py`、`scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh` | T1 |

```mermaid
graph LR
  T1[T1 backend idle 看门狗 + env 旋钮] --> T2[T2 hermetic 测试 + e2e 脚本]
```

两 Task 文件两两不相交（T1 只碰 prod、T2 只碰 test + script），协同模式无写冲突。`tests/
test_backend_claude_code.py` 虽同时列在已 done 的 Spec-0065/T2 里，但那是跨组、非本组内冲突（本组内互斥
即可）。

### e2e / 测试方案（纯内部改动 → hermetic pytest 即成果证据）

本改动是**纯内部**行为（后端进程管理，无 product-facing UI 可导航、无对外可见产物），取证走**相称的自动化
测试**：用假 `Popen` 覆盖 idle / 墙钟 / 零回归三条分支，**不调真实 claude**。

- 假 `Popen` 的 `stdout` 是可控节奏的行序列生成器；**制造长时间静默**用 `threading.Event` 阻塞
  （模拟「读挂住」），`terminate()`/`kill()` 置该 Event → 迭代随即结束（复刻「杀进程 → 管道关 → for 退出」）。
- 测试把 `OPENAGENTS_CLAUDE_IDLE_TIMEOUT` 设成极小值（如 `0.1`s）使看门狗确定性、亚秒级触发，不用真等。
- 覆盖：① idle 触发（静默流 → `terminate`/`kill` 被调 + 抛 `RuntimeError` 含「停顿超时」）；② 墙钟触发
  （每 tick 吐一行但超绝对上限 → 抛「墙钟超时」）；③ **零回归**（连续正常流 → 看门狗从不杀 + 输出/摘要/
  returncode 与今天逐字节一致）；④ 访问器解析/缺省/关闭（`effective_idle_timeout`/`effective_max_wall`）。
- 离线 e2e 脚本 `scripts/e2e-spec-0046-claude-streaming-idle-watchdog.sh`（`ruff check` + `ruff format
  --check` + 针对性 pytest），被 PR e2e signpost 采集。

## Drawbacks

- **每次 agent 调用多一个守护线程。** 极轻（一个 `Event.wait` 轮询循环），但确实多一个线程；与 vigil 已有的
  `_TimedBackend` 线程叠加，一次调用最多两层看门狗线程（可接受，二者互补且都 daemon）。
- **单调墙钟对机器休眠不敏感。** 笔记本睡眠期间 `monotonic()` 通常不走，唤醒后不会误判；但若部署环境的
  monotonic 语义异常，宽默认（300s/3600s）是主要缓冲。
- **`terminate`/`kill` 只作用于直接子进程。** claude 若留下孙子进程（MCP server 等），本 spec 的
  terminate→kill 不递归杀树；vigil 层的 `proc.kill_tree` 才杀整棵。列入 Future（可让看门狗复用
  `kill_tree`）。此处按 issue 明列的 `terminate→kill` 直接实现，奥卡姆优先。
- **多两个 env 旋钮**扩大配置面（但与既有 `OPENAGENTS_*` 同风格，且都有安全缺省）。

## Rationale and alternatives

**选定：看门狗线程 + 单调钟「上次进展」戳。** 理由：（a）**零回归**——热读路径逐字节不变，看门狗不介入读；
（b）**可移植**——不依赖 `select`/`poll` 对缓冲文件对象的脆弱行为；（c）**hermetic 可测**——假 `Popen` +
`Event` 即可全程在进程内确定性复现停顿，不需真管道 / 真子进程。

**备选 1：`select`/`poll` 带超时读 `proc.stdout.fileno()`。** 否决：`proc.stdout` 是 `text=True, bufsize=1`
的 `TextIOWrapper`——`select` 盯**裸 fd**，可能在**缓冲区已有整行**时仍报「未就绪」，造成**误判空闲**；要
绕开就得放弃文本行缓冲、改按字节自己重组行，**改动了读路径**（正是零回归要守住的那条），且难以 hermetic
造假（需真管道）。

**备选 2：调低/仅依赖 vigil 硬超时。** 否决：硬墙钟**进展盲**——调低会误杀健康长任务，调高则真停顿冻死最多
30 分钟；且它只在 vigil 路径存在，backend 的其他调用方仍裸奔。见 §Motivation。

**备选 3：`signal.alarm` / `SIGALRM`。** 否决：仅主线程可用、与 vigil `_TimedBackend` 的**工作线程**模型不
相容（信号只投递主线程），且会污染全局信号处置状态；线程化看门狗无这些约束。

## Prior art

- **k8s liveness probe**——按「有没有进展/健康信号」重启容器，而非按总运行时长杀；本 spec 的「进展 = 新输出
  行」与之同构。
- **TCP keepalive / curl `--speed-time` + `--speed-limit`**——都是**停顿/低速**检测而非总时长上限的成熟先例
  （curl 明确区分 `--max-time` 硬上限 vs `--speed-time` 停顿窗口，正对应本 spec 的墙钟兜底 vs idle 看门狗）。
- **pytest-timeout `method=thread`**——用后台线程实现「超时即杀」，与本 spec 的看门狗线程选型一致（都规避
  `SIGALRM` 的主线程限制）。
- 仓内先例：Spec-0065/T2 的 `_TimedBackend` 硬墙钟 + `utils/proc` 认领/杀树——本 spec 是它在 backend 层、
  以「进展」为判据的互补内层。

## Unresolved questions

- **确切缺省值**：idle 300s、墙钟 3600s（0=关闭）是否合适？是否希望墙钟兜底**默认关闭**（仅在需要时开），
  以最小化默认行为改动？交人确认。
- **是否复用 `proc.kill_tree`** 递归杀孙子进程，还是按 issue 明列的 `terminate→kill` 只杀直接子进程即可
  （杀直接子进程已足以关闭管道、唤醒阻塞读；孙子进程的锁继承问题由 Spec-0065 的 `hold_fd` 另行覆盖）？

## Future possibilities

- **软告警心跳**：idle 越过阈值一半时先打一行 `⏳ claude 已静默 Ns…` 进度提示，再到点才杀（先警后杀）。
- **与 #147 合并成一条不变量测试**：「vigil 在 git 网络挂死 / agent 流挂死两种情形下都不无限阻塞」写成一个
  端到端回归断言。
- **看门狗复用 `proc.kill_tree`**：把终止从「直接子进程」升级为「整棵进程树」，收编 MCP server 等孙子进程。

