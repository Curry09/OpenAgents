# CLI 指南

[English](cli.md) | 简体中文

除非另有说明，命令在目标仓库中执行。`openagents --help` 和 `openagents COMMAND --help` 显示当前安装版本的参数。

## 项目准备与需求录入

```bash
openagents init
openagents issue "Support CSV export" --body "Export the current filtered order list."
openagents issue "Fix login timeout" --yes
```

`init` 准备仓库及工作流标签，并在配置缺失时写入默认文件。其他交付命令也会进行项目预检查。`issue` 默认要求确认，传入 `--yes` 可跳过确认；创建的 Issue 自动带有 `openagents` 发现标签，额外的 `--label` 可以重复指定。在 Forge 网页创建的 Issue 也可以通过添加该标签被发现。

## 持续交付

```bash
openagents vigil
openagents vigil --parallel 4
openagents vigil --once
openagents vigil --interval 30 --base develop
openagents vigil --label bug --label p0
openagents vigil --config /path/to/openagents.yml
openagents vigil --skip ci,e2e
```

默认轮询间隔为 60 秒，并发为 1；`--parallel` 支持 1–32。`--once` 运行一个有限周期并处理其队列，不保证仍在等待外部条件的任务全部完成。参数覆盖仅作用于本次运行；跳过门禁的含义见[配置指南](CONFIGURATION.zh-CN.md)。

使用 Ctrl+C 停止进程。恢复时使用相同的目标仓库和配置，运行时会将持久化工作与 Forge 当前状态重新核对。本地队列和锁应位于同一台机器，详见[架构指南](ARCHITECTURE.zh-CN.md)。

## 显式批量交付

```bash
openagents v02 --issue 12 --issue 15 --parallel 4 \
  --user-test-command 'python3 app.py' \
  --user-test-transcript /path/to/user-test.json \
  --user-test-timeout 900
```

`v02` 选择一批已有 Issue，起草并冻结规格，按依赖 DAG 调度 Developer 和 Acceptance，最后合并成功的结果。它逐项打印终态并保存审计产物，不轮询发现新 Issue；默认并发为 4。

Acceptance 需要真实可执行命令和 JSON 交互输入列表，列表元素可以是事件对象或字符串。可选的 `wait_seconds` 字段指定事件发送前的等待时间，发送时移除该字段；其余对象字段原样作为 JSON 行发送，字符串转为 `{"message": "..."}`。应提供**目标应用实际支持的协议**。命令按参数拆分，不作为 Shell 管道执行；它在已交付候选的一次性副本中运行，超时、崩溃或环境准备失败均不能记为用户测试通过。

对应环境变量为 `OPENAGENTS_USER_TEST_COMMAND`、`OPENAGENTS_USER_TEST_TRANSCRIPT` 和 `OPENAGENTS_USER_TEST_TIMEOUT`，命令行参数只在本批次覆盖它们。此格式用于 OpenAgents 验收，与 AHE-Beta 的实验配置不同。

## 规格补录与版本发布

```bash
openagents backfill-rfc openagents/utils/git.py
openagents backfill-rfc openagents/recipes/ --base main
openagents release --bump patch
```

`backfill-rfc` 根据已有文件或目录推导规格并创建 Draft PR。`release` 检查失败记录及 main 分支 CI，通过后推送 `release/vX.Y.Z` 分支和标签；它不会创建 GitHub Release 或构建分发资产，详见[发布指南](RELEASING.zh-CN.md)。

## 本地观测

```bash
openagents report
openagents board
openagents desktop --host 127.0.0.1 --port 8765
```

这些命令读取本地运行状态，跳过项目绑定预检查。`board` 生成成果看板；`desktop` 提供实验性的观测 API，不会启动交付。离线或冻结版本运行时，先设置 `OPENAGENTS_NO_SELF_UPDATE=1`，避免命令执行前更新源码。

`report` 读取 `.openagents/` 下的追加式记录，展示阶段耗时、工具查询指标和按角色统计的 Token 用量：

| 列 | 含义 |
| --- | --- |
| `calls` | 已观测的角色调用次数 |
| `reported` / `missing` | 有结构化用量 / 用量缺失的调用次数 |
| `input`、`cache-r`、`cache-w`、`reason`、`output` | 提供方返回的各项用量 |
| `total(r/d)` | 提供方直接返回总量 / 根据分量推导总量的调用次数 |

总量仅覆盖已报告的调用，缺失用量不等于零。Claude Code 的最终 `result.usage` 已汇总一次角色调用内的模型轮次，因此不再累加中间 assistant 事件的用量。Token 账本只保存计数和调用元数据；其他调用轨迹可能包含任务内容，分享前需要单独检查。

## 证据读取能力

```bash
OPENAGENTS_NO_SELF_UPDATE=1 openagents observation-capabilities --json
```

该命令先于自动更新和项目查找执行，输出一个 JSON 对象，不需要凭证或仓库，且必须带 `--json`。应查询真正用于交付的可执行文件或镜像，而非另一份源码。

`openagents-observation-reader-capabilities-v1` 对象声明支持的 Marker、gzip/ZIP 编码、ZIP 结构、下载策略和大小限制：传输上限 4,000,000 字节，展开上限 24,000,000 字节。它还声明执行条件证据的版本支持与必需证据派发约束。这只是能力声明；实际行为应通过[读取端探针](VERIFICATION.zh-CN.md)验证。

## 命令补全

Bash 在 `~/.bashrc` 中添加：

```bash
eval "$(register-python-argcomplete openagents)"
```

Zsh 在 `~/.zshrc` 中添加：

```zsh
autoload -U bashcompinit
bashcompinit
eval "$(register-python-argcomplete openagents)"
```

补全是可选功能，读取 CLI 参数定义。`register-python-argcomplete` 由已安装的 argcomplete 依赖提供；如果 uv tool 只暴露了 OpenAgents 自身入口，需要将对应工具环境的可执行目录加入 PATH。
