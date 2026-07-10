# Spec-0064 成果证据（离线确定性 + 真实 CLI 触发）

生成时间：2026-07-10  ·  生成命令见本文件各段 $ 提示符

本 spec 是纯后端配置 + 编排 + CLI 收敛（无 product-facing 前端可导航；工具集无 Playwright /
Chrome DevTools MCP，故不设浏览器 e2e）。产品对外行为的两处可观测点用真实 app 触发取证：
① CLI 命令面收敛（用户可见）→ 真跑 oa --help 截取命令清单；② 声明式配置真生效（UI 不可见但
改对外行为）→ 真加载 .openagents/openagents.yml 触发三态路由 / 校验 / 告警，贴真实运行日志。

## ① CLI 命令面收敛（真实 `python -m openagents.cli --help`）

```
$ uv run python -m openagents.cli --help
usage: openagents [-h] <command> ...

RFC 驱动的多 Agent 框架：拉取 issue → 派单 agent → 提 PR。

positional arguments:
  <command>
    init          绑定/初始化当前目录为 OpenAgents 项目
    vigil         守夜人：自主监控 issue → 派单 → 守候 PR（读 openagents.yml）
    backfill-rfc  扫存量代码路径反推 spec 并开 draft PR
    issue         往当前项目仓库提一个 GitHub issue
    release       把 main 当前 HEAD 发布为一个版本（预检通过后物化）
    board         启动本地成果看板

options:
  -h, --help      show this help message and exit
```

人面向仅 init/vigil/backfill-rfc/issue/release/board 在册；旧九命令
（rfc/refine-rfc/implement/iterate/solve/poll/watch/vigil-all/fleet）已并入 vigil 消失；
reply-comment 从清单隐去（省略 help）但仍可解析分发（下方 ② 之外单证）。

## ② 声明式配置真生效（真实加载 `.openagents/openagents.yml` + 真跑 run_vigil 路由）

以下用真实产品代码（openagents.utils.agent_config + openagents.recipes.vigil）执行，非 mock：

```
$ uv run python <驱动脚本，见下>
(a) 三态解析: merge= human ci= skip review= agent
(b) 不许零闸守卫拦截: <root>: 不许零闸——review:skip + merge:agent 会让未审代码自动盲合进 main；要么开 ...
(c) merge 拒 skip: 已拒绝 ✓
(c) conflict 拒 skip: 已拒绝 ✓
(c) 硬闸名进 stages 拒: 已拒绝 ✓
(d) rfc:skip 告警: 有告警 ✓ — stages.rfc=skip：将跳过 RFC 起草直接实现，撞理念 4（先改 RFC 再改代码）
(e) run_vigil.route 三态分支: ['AGENT', 'HUMAN', 'SKIP']
```

结论：一份 `.openagents/openagents.yml` 真被产品代码加载为三态策略、每闸合法取值/不许零闸/硬闸
分层被真实校验拦截、rfc:skip 真发告警；run_vigil 的 route 原语真按 owner 三分支——「用哪些 agent +
每道闸归谁」的声明式单一真源在离线确定性链路上确实驱动编排。
